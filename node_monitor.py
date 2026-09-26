#!/usr/bin/env python3
"""
Node & Server Health Monitoring & Smart Failover Engine
موتور پایش سلامت نودها، تست پینگ و پکت‌لاس، سوییچینگ اضطراری (Failover) و مدیریت دامنه‌ها
"""

import asyncio
import time
import socket
import logging
from typing import Tuple, Dict, Any, List, Optional
from database import db
from hidify import HidifyClient

logger = logging.getLogger(__name__)


class NodeMonitor:
    """موتور پایش سلامت نودها و اجرای سوییچینگ اضطراری سرور"""

    @staticmethod
    async def ping_tcp(host: str, port: int = 443, timeout: float = 3.5) -> Tuple[bool, float, str]:
        """
        تست پینگ TCP سوکت جهت سنجش دقیق در دسترس بودن نود و محاسبه تاخیر (Latency) به میلی‌ثانیه
        """
        import urllib.parse
        clean_host = host.strip()
        
        if "://" in clean_host:
            parsed = urllib.parse.urlparse(clean_host)
            if parsed.hostname:
                clean_host = parsed.hostname
                if parsed.port:
                    port = parsed.port
            else:
                clean_host = clean_host.split("://")[-1]
                if "/" in clean_host:
                    clean_host = clean_host.split("/")[0]
                if "@" in clean_host:
                    clean_host = clean_host.split("@")[-1]
                if ":" in clean_host:
                    port_str = clean_host.split(":")[1]
                    if port_str.isdigit(): port = int(port_str)
                    clean_host = clean_host.split(":")[0]
        else:
            if "/" in clean_host:
                clean_host = clean_host.split("/")[0]
            if "@" in clean_host:
                clean_host = clean_host.split("@")[-1]
            if ":" in clean_host:
                port_str = clean_host.split(":")[1]
                if port_str.isdigit(): port = int(port_str)
                clean_host = clean_host.split(":")[0]

        start_time = time.perf_counter()
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(clean_host, port),
                timeout=timeout
            )
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            return True, round(latency_ms, 1), "OK"
        except asyncio.TimeoutError:
            return False, -1.0, "Timeout (تایم‌اوت در برقراری اتصال)"
        except ConnectionRefusedError:
            return False, -1.0, "Connection Refused (پورت بسته یا فیلتر)"
        except socket.gaierror:
            return False, -1.0, "DNS Error (دامنه شناسایی نشد)"
        except Exception as e:
            return False, -1.0, f"Error: {type(e).__name__}"

    @classmethod
    async def check_single_node(cls, node: Dict[str, Any]) -> Dict[str, Any]:
        """بررسی وضعیت سلامت یک نود و ثبت آن در دیتابیس"""
        node_id = node.get("id")
        host = node.get("host")
        port = int(node.get("port") or 443)
        name = node.get("name") or host

        is_alive, ping_ms, err = await cls.ping_tcp(host, port)
        if is_alive:
            status = "online" if ping_ms < 600 else "degraded"
            db.record_node_ping(node_id, ping_ms, status)
            result = {
                "id": node_id,
                "name": name,
                "host": host,
                "status": status,
                "ping_ms": ping_ms,
                "is_alive": True,
                "error": None
            }
        else:
            status = "offline"
            db.record_node_ping(node_id, -1, status, error=err)
            result = {
                "id": node_id,
                "name": name,
                "host": host,
                "status": status,
                "ping_ms": -1,
                "is_alive": False,
                "error": err
            }

        return result

    @classmethod
    async def check_all_nodes(cls, trigger_failover: bool = True) -> List[Dict[str, Any]]:
        """
        بررسی همزمان تمامی نودهای فعال و اجرای سوییچ خودکار در صورت تشخیص اختلال مداوم
        """
        nodes = db.get_all_nodes(active_only=True)
        if not nodes:
            return []

        tasks = [cls.check_single_node(node) for node in nodes]
        results = await asyncio.gather(*tasks, return_exceptions=False)

        if trigger_failover:
            for node in nodes:
                node_id = node.get("id")
                updated_node = db.get_node(node_id)
                if not updated_node:
                    continue

                consecutive_fails = updated_node.get("consecutive_fails", 0)
                auto_failover = bool(updated_node.get("auto_failover", False))
                fallback_target_id = updated_node.get("fallback_target_id")
                node_type = updated_node.get("node_type", "")

                # هشدار تلگرامی برای کانفیگ و سایت ایران
                if consecutive_fails == 3 and node_type in ("config_node", "iran_site"):
                    try:
                        from notifications import send_admin_notification
                        type_str = "سایت/سرور ایران" if node_type == "iran_site" else "کانفیگ پروکسی"
                        alert_msg = f"⚠️ <b>هشدار قطعی ارتباط!</b>\n\nتست ارتباط با <b>{updated_node.get('name')}</b> ({type_str}) با شکست مواجه شد.\n\n🌐 آدرس: <code>{updated_node.get('host')}</code>\n🔌 پورت: {updated_node.get('port')}"
                        send_admin_notification(alert_msg)
                    except Exception as e:
                        logger.error(f"Failed to send telegram alert for node {node_id}: {e}")

                if consecutive_fails >= 3 and auto_failover and fallback_target_id:
                    target_node = db.get_node(fallback_target_id)
                    if target_node and target_node.get("status") == "online" and target_node.get("is_active"):
                        logger.warning(f"Auto-Failover triggered for node {updated_node['name']} -> {target_node['name']}")
                        await cls.execute_failover(
                            source_node_id=node_id,
                            target_node_id=fallback_target_id,
                            reason="سوییچ خودکار به دلیل ۳ مرتبه عدم پاسخگویی و تایم‌اوت نود اصلی"
                        )

        return results

    @classmethod
    async def execute_failover(cls, source_node_id: int, target_node_id: int, reason: str = "سوییچ دستی توسط مدیر") -> Dict[str, Any]:
        """
        انجام سوییچینگ اضطراری از یک نود آسیب‌دیده به نود سالم رزرو
        """
        source_node = db.get_node(source_node_id)
        target_node = db.get_node(target_node_id)

        if not source_node or not target_node:
            return {"success": False, "error": "نود مبدا یا مقصد یافت نشد"}

        s_host = source_node.get("host", "").strip()
        t_host = target_node.get("host", "").strip()

        conn = db.get_connection()
        cursor = conn.cursor()
        affected_count = 0
        try:
            cursor.execute("SELECT COUNT(*) as cnt FROM subscriptions WHERE status='active'")
            row = cursor.fetchone()
            affected_count = row["cnt"] if row else 0
        except Exception:
            affected_count = 0

        try:
            curr_domain = db.get_setting("server_domain")
            if curr_domain and s_host in curr_domain:
                db.save_setting("server_domain", t_host)

            sub_domain = db.get_setting("subscription_domain")
            if sub_domain and s_host in sub_domain:
                db.save_setting("subscription_domain", t_host)
        except Exception as e:
            logger.error(f"Error updating domain settings in failover: {e}")

        db.add_failover_log(
            source_id=source_node_id,
            source_name=source_node.get("name", s_host),
            target_id=target_node_id,
            target_name=target_node.get("name", t_host),
            reason=reason,
            affected_users=affected_count
        )

        alert_msg = (
            f"🚨 <b>هشدار و گزارش سوییچ اضطراری شبکه</b>\n\n"
            f"🔴 <b>نود از دسترس خارج‌شده:</b> <code>{source_node.get('name')} ({s_host})</code>\n"
            f"🟢 <b>نود جایگزین فعال:</b> <code>{target_node.get('name')} ({t_host})</code>\n"
            f"👥 <b>تعداد سرویس‌های فعال منتفع:</b> {affected_count:,} کاربر\n"
            f"📝 <b>دلیل سوییچ:</b> {reason}\n"
            f"⏱ <b>زمان اقدام:</b> هم‌اکنون\n\n"
            f"✅ ترافیک و سوییچینگ با موفقیت بدون قطعی سرویس اعمال گردید."
        )
        try:
            from notifications import send_admin_notification
            send_admin_notification(alert_msg)
        except Exception as e:
            logger.warning(f"Could not send failover alert: {e}")

        return {
            "success": True,
            "source_name": source_node.get("name"),
            "target_name": target_node.get("name"),
            "affected_users": affected_count,
            "message": f"سوییچ اضطراری از «{source_node.get('name')}» به «{target_node.get('name')}» با موفقیت انجام شد."
        }

    @classmethod
    async def sync_hiddify_domains(cls, hidify_client: HidifyClient) -> int:
        """
        همگام‌سازی خودکار دامنه‌های موجود در هیدیفای و اضافه کردن آنها به لیست نودهای تحت پایش
        """
        try:
            domains = await hidify_client.get_domains()
            if not domains or not isinstance(domains, list):
                return 0

            existing_nodes = db.get_all_nodes()
            existing_hosts = {n.get("host", "").lower().strip() for n in existing_nodes}
            added = 0

            for d in domains:
                if not isinstance(d, dict):
                    continue
                d_domain = d.get("domain", "").strip()
                d_alias = d.get("alias") or d_domain
                d_mode = d.get("mode", "direct")
                if not d_domain or d_domain.lower() in existing_hosts:
                    continue

                db.add_node(
                    name=f"هیدیفای: {d_alias} ({d_mode})",
                    host=d_domain,
                    port=443,
                    node_type="domain_node",
                    is_fallback=False,
                    auto_failover=False
                )
                existing_hosts.add(d_domain.lower())
                added += 1

            logger.info(f"Synced {added} new domains from Hiddify to node_servers.")
            return added
        except Exception as e:
            logger.error(f"Error syncing Hiddify domains: {e}")
            return 0
