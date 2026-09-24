#!/usr/bin/env python3
"""
🛡️ ماژول مدیریت و زمان‌بندی پشتیبان‌گیری جامع (Main Panel & Hiddify)
- تهیه پشتیبان فشرده و ایمن از پایگاه داده و تنظیمات پنل اصلی و نمایندگان
- دریافت پشتیبان کامل تنظیمات و کاربران پنل هیدیفای (Hiddify)
- ارسال مستقیم به کانال یا گروه تلگرام با فرمت زیبا و متادیتا
- ثبت تاریخچه و گزارشات دقیق به تفکیک پنل اصلی و هیدیفای
- زمان‌بندی هوشمند بر اساس بازه ساعتی یا ساعات مشخص شبانه‌روز
- لغو شیوه قدیمی ارسال به چت خصوصی ادمین
"""

import os
import shutil
import logging
import asyncio
import json
import zipfile
import sqlite3
import httpx
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from database import db, DB_DIR
from utils import get_now_shamsi, get_now_naive, get_now, get_now_iso, TEHRAN_TZ, parse_to_tehran_dt

logger = logging.getLogger(__name__)

# مسیر ذخیره پشتیبان‌ها
BACKUP_DIR = DB_DIR / "backups"
BACKUP_DIR.mkdir(parents=True, exist_ok=True)


def format_file_size(size_bytes: int) -> str:
    """تبدیل بایت به فرمت خوانا (KB, MB)"""
    if not size_bytes or size_bytes <= 0:
        return "0 B"
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.2f} MB"


class BackupManager:
    """کلاس مدیریت ایجاد و بازیابی فایل‌های پشتیبان"""

    def __init__(self):
        pass

    def create_database_backup(self, compress=True):
        """
        ایجاد پشتیبان آنلاین و ایمن از دیتابیس SQLite بدون قفل جدول‌ها
        و فشرده‌سازی در قالب فایل Zip همراه با متادیتا
        """
        try:
            timestamp = get_now_naive().strftime("%Y%m%d_%H%M%S")
            raw_db_filename = f"backup_main_{timestamp}.db"
            raw_db_path = BACKUP_DIR / raw_db_filename

            source_path = db.db_path
            if not source_path.exists():
                logger.error("Database file not found for backup")
                return {"success": False, "error": "فایل دیتابیس اصلی یافت نشد."}

            # استفاده از SQLite Online Backup API برای ایجاد اسنپ‌شات اتمیک و هماهنگ
            src_conn = sqlite3.connect(str(source_path))
            dst_conn = sqlite3.connect(str(raw_db_path))
            src_conn.backup(dst_conn)
            dst_conn.close()
            src_conn.close()

            metrics = db.get_system_backup_metrics()
            final_file = raw_db_path
            final_filename = raw_db_filename

            if compress:
                zip_filename = f"backup_main_{timestamp}.zip"
                zip_path = BACKUP_DIR / zip_filename
                with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
                    zipf.write(raw_db_path, arcname=raw_db_filename)
                    meta_info = {
                        "timestamp": timestamp,
                        "shamsi_date": get_now_shamsi(),
                        "metrics": metrics
                    }
                    zipf.writestr("backup_metadata.json", json.dumps(meta_info, ensure_ascii=False, indent=2))
                
                # حذف فایل خام پس از فشرده‌سازی موفق
                try:
                    raw_db_path.unlink()
                except Exception:
                    pass
                final_file = zip_path
                final_filename = zip_filename

            file_size = final_file.stat().st_size
            logger.info(f"Main database backup created: {final_filename} ({file_size:,} bytes)")
            return {
                "success": True,
                "file": str(final_file),
                "filename": final_filename,
                "size": file_size,
                "metrics": metrics
            }

        except Exception as e:
            logger.error(f"Error creating database backup: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    def create_backup(self):
        """متد سازگاری با کدهای پیشین"""
        return self.create_database_backup(compress=True)

    async def create_hiddify_backup(self):
        """دریافت فایل پشتیبان کامل از پنل هیدیفای به صورت JSON با مشخصات معتبر دیتابیس و محیط"""
        try:
            b_txt = None

            # واکشی مشخصات اتصال به هیدیفای با اولویت دیتابیس سپس متغیرهای محیطی
            from database import db
            panel_url = (
                db.get_setting("hidify_panel_url")
                or db.get_setting("hiddify_url")
                or os.getenv("HIDIFY_PANEL_URL")
                or ""
            ).strip().rstrip("/")
            api_key = (
                db.get_setting("hidify_api_key")
                or db.get_setting("hiddify_api_key")
                or os.getenv("HIDIFY_API_KEY")
                or ""
            ).strip()
            proxy_path = (
                db.get_setting("hidify_proxy_path")
                or db.get_setting("hiddify_proxy_path")
                or os.getenv("HIDIFY_PROXY_PATH")
                or ""
            ).strip().strip("/")

            if not panel_url or not api_key:
                return {
                    "success": False,
                    "error": "مشخصات اتصال به پنل هیدیفای (آدرس پنل یا کلید API) در تنظیمات سامانه یافت نشد."
                }

            from hidify import HidifyClient
            temp_client = HidifyClient(panel_url, api_key, proxy_path)
            try:
                b_txt = await temp_client.get_backup()
            finally:
                await temp_client.close()

            if not b_txt:
                return {"success": False, "error": "دریافت اطلاعات پشتیبان از وب‌سرویس هیدیفای ناموفق بود."}

            timestamp = get_now_naive().strftime("%Y%m%d_%H%M%S")
            filename = f"backup_hiddify_{timestamp}.json"
            file_path = BACKUP_DIR / filename
            file_path.write_text(b_txt, encoding="utf-8")
            file_size = file_path.stat().st_size

            details = {
                "users_count": 0,
                "domains_count": 0,
                "proxies_count": 0,
                "admin_users_count": 0,
                "status": "ok"
            }
            try:
                parsed = json.loads(b_txt)
                if isinstance(parsed, dict):
                    details["users_count"] = len(parsed.get("users", [])) or len(parsed.get("user", []))
                    details["domains_count"] = len(parsed.get("domains", []))
                    details["proxies_count"] = len(parsed.get("proxies", []))
                    details["admin_users_count"] = len(parsed.get("admin_users", []))
                elif isinstance(parsed, list):
                    details["users_count"] = len(parsed)
            except Exception:
                pass

            logger.info(f"Hiddify backup created: {filename} ({file_size:,} bytes)")
            return {
                "success": True,
                "file": str(file_path),
                "filename": filename,
                "size": file_size,
                "details": details
            }

        except Exception as e:
            logger.error(f"Error creating Hiddify backup: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    def restore_backup(self, backup_path):
        """بازیابی دیتابیس از فایل پشتیبان"""
        try:
            backup_path = Path(backup_path)
            if not backup_path.exists():
                return {"success": False, "error": "فایل پشتیبان انتخاب‌شده یافت نشد."}

            # در صورتی که فایل ارسالی zip باشد، ابتدا فایل .db را استخراج می‌کنیم
            actual_db_file = backup_path
            temp_extracted = None
            if backup_path.suffix.lower() == ".zip":
                with zipfile.ZipFile(backup_path, "r") as zf:
                    for name in zf.namelist():
                        if name.endswith(".db"):
                            temp_extracted = BACKUP_DIR / f"extracted_{name}"
                            with open(temp_extracted, "wb") as f_out:
                                f_out.write(zf.read(name))
                            actual_db_file = temp_extracted
                            break

            # کپی امنیتی از وضعیت فعلی قبل از بازنویسی
            current_backup = BACKUP_DIR / f"pre_restore_{get_now_naive().strftime('%Y%m%d_%H%M%S')}.db"
            if db.db_path.exists():
                shutil.copy2(db.db_path, current_backup)

            # کپی فایل دیتابیس
            shutil.copy2(actual_db_file, db.db_path)
            try:
                db.sync_configs_from_settings()
            except Exception as e_sync:
                logger.warning(f"Could not auto-sync configs after restore: {e_sync}")

            if temp_extracted and temp_extracted.exists():
                try:
                    temp_extracted.unlink()
                except Exception:
                    pass

            logger.info(f"Database restored from {backup_path.name}")
            return {
                "success": True,
                "message": f"پایگاه داده با موفقیت از فایل {backup_path.name} بازیابی شد.",
                "pre_restore_backup": str(current_backup),
            }

        except Exception as e:
            logger.error(f"Error restoring backup: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    def list_backups(self, backup_type=None):
        """لیست فایل‌های فیزیکی موجود در دایرکتوری پشتیبان"""
        backups = []
        patterns = ["backup_*.zip", "backup_*.db", "backup_*.json"]
        for pat in patterns:
            for f in sorted(BACKUP_DIR.glob(pat), reverse=True):
                is_hiddify = "hiddify" in f.name.lower()
                if backup_type == "hiddify" and not is_hiddify:
                    continue
                if backup_type == "main_panel" and is_hiddify:
                    continue
                backups.append({
                    "filename": f.name,
                    "path": str(f),
                    "size": f.stat().st_size,
                    "created": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
                    "is_hiddify": is_hiddify
                })
        return backups

    def delete_old_backups(self, keep_count=25, backup_type=None):
        """پاک‌سازی خودکار فایل‌های پشتیبان قدیمی جهت جلوگیری از اشغال دیسک"""
        try:
            main_files = sorted(
                list(BACKUP_DIR.glob("backup_main_*.zip")) + list(BACKUP_DIR.glob("backup_main_*.db")),
                key=lambda x: x.stat().st_mtime
            )
            if len(main_files) > keep_count:
                for f in main_files[:-keep_count]:
                    try:
                        f.unlink()
                        logger.info(f"Deleted old main backup: {f.name}")
                    except Exception:
                        pass

            hiddify_files = sorted(
                list(BACKUP_DIR.glob("backup_hiddify_*.json")),
                key=lambda x: x.stat().st_mtime
            )
            if len(hiddify_files) > keep_count:
                for f in hiddify_files[:-keep_count]:
                    try:
                        f.unlink()
                        logger.info(f"Deleted old hiddify backup: {f.name}")
                    except Exception:
                        pass
        except Exception as e:
            logger.warning(f"Error cleaning old backups: {e}")


# نمونه یکتای BackupManager
backup_manager = BackupManager()


# ═══════════════════════════════════════════════════════════════
# ارتباط با تلگرام و ارسال فایل‌ها (Telegram Dispatcher)
# ═══════════════════════════════════════════════════════════════

def get_effective_bot_token() -> str:
    """دریافت توکن فعال ربات از متغیرهای محیطی یا دیتابیس"""
    tok = os.getenv("BOT_TOKEN")
    if tok:
        return tok.strip()
    return (db.get_setting("bot_token") or "").strip()


def normalize_telegram_chat_id(target_chat: str) -> str:
    """اصلاح و استانداردسازی آیدی یا شناسه کانال/گروه تلگرام و پاکسازی کاراکترهای مخفی RTL و اعداد فارسی"""
    if not target_chat:
        return ""
    s = str(target_chat).strip()
    for c in ["\u200e", "\u200f", "\u202a", "\u202b", "\u202c", "\u202d", "\u202e", "\ufeff"]:
        s = s.replace(c, "")
    s = s.strip()
    fa_digits = "۰۱۲۳۴۵۶۷۸۹"
    ar_digits = "٠١٢٣٤٥٦٧٨٩"
    for i in range(10):
        s = s.replace(fa_digits[i], str(i)).replace(ar_digits[i], str(i))
    s = s.strip()
    if s.startswith("@"):
        return s
    # در صورت وجود منفی در انتها بر اثر کپی در محیط راست‌به‌چپ (مثلاً 5362393523-)
    if s.endswith("-") and not s.startswith("-"):
        s = "-" + s[:-1].strip()
    return s


def send_telegram_backup_file(target_chat: str, file_path: str, filename: str, caption: str) -> dict:
    """
    ارسال فایل پشتیبان به کانال یا گروه تلگرام با استفاده از httpx
    کاملاً ایزوله از تردها و بدون ایجاد تداخل با حلقه asyncio
    """
    token = get_effective_bot_token()
    if not token:
        return {"success": False, "error": "توکن ربات تلگرام (BOT_TOKEN) تنظیم نشده است."}

    clean_target = normalize_telegram_chat_id(target_chat)
    if not clean_target:
        return {"success": False, "error": "شناسه یا آیدی کانال/گروه تلگرام مقصد مشخص نشده است."}

    p = Path(file_path)
    if not p.exists():
        return {"success": False, "error": f"فایل پشتیبان {filename} در سرور یافت نشد."}

    url = f"https://api.telegram.org/bot{token}/sendDocument"

    try:
        with open(p, "rb") as fp:
            files = {"document": (filename, fp)}
            data = {
                "chat_id": clean_target,
                "caption": caption,
                "parse_mode": "HTML"
            }
            with httpx.Client(timeout=180.0) as client:
                resp = client.post(url, data=data, files=files)
                res_data = resp.json()

                if res_data.get("ok"):
                    msg_id = res_data.get("result", {}).get("message_id")
                    logger.info(f"Backup {filename} successfully sent to {clean_target} (message_id: {msg_id})")
                    return {"success": True, "message_id": msg_id}
                else:
                    desc = res_data.get("description", "خطای ناشناخته تلگرام")
                    logger.warning(f"Telegram sendDocument rejected for {clean_target}: {desc}")
                    return {"success": False, "error": desc}

    except Exception as e:
        logger.error(f"HTTP error sending backup to Telegram: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


def test_telegram_connection(target_chat: str) -> dict:
    """ارسال پیام آزمایشی جهت تایید دسترسی ادمین ربات در کانال یا گروه مقصد"""
    token = get_effective_bot_token()
    if not token:
        return {"success": False, "error": "توکن ربات تلگرام تنظیم نشده است."}

    clean_target = normalize_telegram_chat_id(target_chat)
    if not clean_target:
        return {"success": False, "error": "لطفاً شناسه کانال یا گروه تلگرام را وارد فرمایید."}

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    now_sh = get_now_shamsi()

    text = (
        "🧪 <b>پیام آزمایشی سیستم پشتیبان‌گیری خودکار</b>\n"
        "━━━━━━━━━━━━━━━━━\n"
        "✅ <b>اتصال با موفقیت برقرار شد!</b>\n"
        "ربات به این کانال/گروه دسترسی دارد و پشتیبان‌های خودکار به این مقصد ارسال خواهند شد.\n\n"
        f"📅 <b>زمان تست:</b> {now_sh}\n"
        "🔒 سامانه مدیریت یکپارچه سرویس"
    )

    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(url, json={
                "chat_id": clean_target,
                "text": text,
                "parse_mode": "HTML"
            })
            res_data = resp.json()

            if res_data.get("ok"):
                return {"success": True, "message": "پیام آزمایشی با موفقیت در کانال/گروه ارسال گردید."}
            else:
                desc = res_data.get("description", "خطای تلگرام")
                return {"success": False, "error": f"پاسخ تلگرام: {desc}"}
    except Exception as e:
        return {"success": False, "error": f"خطا در برقراری ارتباط: {str(e)}"}


# ═══════════════════════════════════════════════════════════════
# توابع اجرایی پشتیبان‌گیری (Trigger Functions)
# ═══════════════════════════════════════════════════════════════

def trigger_main_panel_backup(trigger_type: str = "auto", target_chat: str = None) -> dict:
    """اجرای پشتیبان‌گیری از پنل اصلی، ارسال به تلگرام و ثبت گزارش در دیتابیس"""
    dest_chat = (target_chat or db.get_setting("backup_telegram_target", "") or db.get_setting("hiddify_backup_channel_id", "")).strip()
    
    # ۱. ایجاد فایل پشتیبان دیتابیس
    b_res = backup_manager.create_database_backup(compress=True)
    if not b_res.get("success"):
        err = b_res.get("error", "خطا در ایجاد پشتیبان دیتابیس")
        db.save_backup_record(
            backup_file="",
            backup_size=0,
            backup_type="main_panel",
            status="failed",
            target_chat=dest_chat,
            error_message=err,
            trigger_type=trigger_type
        )
        return {"success": False, "error": err}

    f_path = b_res["file"]
    f_name = b_res["filename"]
    f_size = b_res["size"]
    metrics = b_res.get("metrics", {})
    now_sh = get_now_shamsi()
    trigger_label = "خودکار (زمان‌بندی‌شده)" if trigger_type == "auto" else "دستی (توسط ادمین)"

    caption = (
        "🛡️ <b>پشتیبان خودکار پنل اصلی و نمایندگان</b>\n"
        "━━━━━━━━━━━━━━━━━\n"
        f"📅 <b>تاریخ و ساعت:</b> {now_sh}\n"
        f"📁 <b>نام فایل:</b> <code>{f_name}</code>\n"
        f"📊 <b>حجم فایل:</b> {format_file_size(f_size)}\n\n"
        "📈 <b>شاخص‌های آماری لحظه‌ای سیستم:</b>\n"
        f"👥 <b>تعداد کل مشتریان (اشتراک‌ها):</b> {metrics.get('total_subscriptions', 0):,}\n"
        f"🟢 <b>اشتراک‌های فعال:</b> {metrics.get('active_subscriptions', 0):,}\n"
        f"👔 <b>تعداد نمایندگان فعال:</b> {metrics.get('active_resellers', 0):,}\n"
        f"👤 <b>کل کاربران دیتابیس:</b> {metrics.get('total_users', 0):,}\n"
        f"💳 <b>کارت‌های بانکی فعال:</b> {metrics.get('active_cards', 0):,}\n\n"
        f"⚙️ <b>نوع اجرا:</b> {trigger_label}\n"
        "━━━━━━━━━━━━━━━━━\n"
        "🔒 سامانه مدیریت یکپارچه سرویس"
    )

    # ۲. ارسال به تلگرام در صورت وجود مقصد
    send_res = {"success": True, "message_id": None}
    if dest_chat:
        send_res = send_telegram_backup_file(dest_chat, f_path, f_name, caption)

    status = "success" if send_res.get("success") else "failed"
    err_msg = send_res.get("error") if not send_res.get("success") else None

    # ۳. ثبت گزارش در دیتابیس
    db.save_backup_record(
        backup_file=f_name,
        backup_size=f_size,
        backup_type="main_panel",
        status=status,
        target_chat=dest_chat,
        telegram_message_id=send_res.get("message_id"),
        error_message=err_msg,
        details_json=json.dumps(metrics, ensure_ascii=False),
        trigger_type=trigger_type
    )

    # ۴. پاک‌سازی فایل‌های قدیمی
    backup_manager.delete_old_backups(keep_count=25)

    if not send_res.get("success"):
        return {"success": False, "error": f"فایل ایجاد شد ولی ارسال به تلگرام با خطا مواجه گردید: {err_msg}", "filename": f_name}

    return {"success": True, "filename": f_name, "size": f_size, "metrics": metrics}


async def trigger_hiddify_panel_backup_async(trigger_type: str = "auto", target_chat: str = None) -> dict:
    """اجرای ناهمگام پشتیبان‌گیری هیدیفای"""
    raw_dest = (target_chat or db.get_setting("backup_telegram_target", "") or db.get_setting("hiddify_backup_channel_id", "")).strip()
    dest_chat = normalize_telegram_chat_id(raw_dest)

    # ۱. دریافت بکاپ هیدیفای
    h_res = await backup_manager.create_hiddify_backup()
    if not h_res.get("success"):
        err = h_res.get("error", "خطا در دریافت پشتیبان هیدیفای")
        db.save_backup_record(
            backup_file="",
            backup_size=0,
            backup_type="hiddify",
            status="failed",
            target_chat=dest_chat,
            error_message=err,
            trigger_type=trigger_type
        )
        return {"success": False, "error": err}

    f_path = h_res["file"]
    f_name = h_res["filename"]
    f_size = h_res["size"]
    details = h_res.get("details", {})
    now_sh = get_now_shamsi()
    trigger_label = "خودکار (زمان‌بندی‌شده)" if trigger_type == "auto" else "دستی (توسط ادمین)"

    extra_details = ""
    if details.get("proxies_count"):
        extra_details += f"🔌 <b>تعداد کانفیگ‌ها و پروکسی‌ها:</b> {details.get('proxies_count', 0):,}\n"
    if details.get("admin_users_count"):
        extra_details += f"👔 <b>تعداد مدیران پنل:</b> {details.get('admin_users_count', 0):,}\n"

    caption = (
        "⚡ <b>پشتیبان خودکار پنل هیدیفای (Hiddify)</b>\n"
        "━━━━━━━━━━━━━━━━━\n"
        f"📅 <b>تاریخ و ساعت:</b> {now_sh}\n"
        f"📁 <b>نام فایل:</b> <code>{f_name}</code>\n"
        f"📊 <b>حجم فایل:</b> {format_file_size(f_size)}\n\n"
        f"👥 <b>تعداد کاربران ثبت‌شده در هیدیفای:</b> {details.get('users_count', 0):,}\n"
        f"🌐 <b>تعداد دامنه‌ها و نودها:</b> {details.get('domains_count', 0):,}\n"
        f"{extra_details}\n"
        f"⚙️ <b>نوع اجرا:</b> {trigger_label}\n"
        "━━━━━━━━━━━━━━━━━\n"
        "🔒 سامانه مدیریت یکپارچه سرویس"
    )

    # ۲. ارسال به تلگرام
    send_res = {"success": True, "message_id": None}
    if dest_chat:
        send_res = send_telegram_backup_file(dest_chat, f_path, f_name, caption)

    status = "success" if send_res.get("success") else "failed"
    err_msg = send_res.get("error") if not send_res.get("success") else None

    # ۳. ثبت گزارش در دیتابیس
    db.save_backup_record(
        backup_file=f_name,
        backup_size=f_size,
        backup_type="hiddify",
        status=status,
        target_chat=dest_chat,
        telegram_message_id=send_res.get("message_id"),
        error_message=err_msg,
        details_json=json.dumps(details, ensure_ascii=False),
        trigger_type=trigger_type
    )

    backup_manager.delete_old_backups(keep_count=25)

    if not send_res.get("success"):
        return {"success": False, "error": f"بکاپ هیدیفای دریافت شد اما ارسال به تلگرام با خطا مواجه شد: {err_msg}", "filename": f_name}

    return {"success": True, "filename": f_name, "size": f_size, "details": details}


def trigger_hiddify_panel_backup(trigger_type: str = "auto", target_chat: str = None) -> dict:
    """اجرای همگام پشتیبان‌گیری هیدیفای جهت فراخوانی از روت‌های فلسک"""
    try:
        loop = asyncio.new_event_loop()
        res = loop.run_until_complete(trigger_hiddify_panel_backup_async(trigger_type=trigger_type, target_chat=target_chat))
        loop.close()
        return res
    except Exception as e:
        logger.error(f"Error in synchronous trigger_hiddify_panel_backup: {e}")
        return {"success": False, "error": str(e)}


# ═══════════════════════════════════════════════════════════════
# متد لغو شده قدیمی (Deprecated - No Private Chat Spams)
# ═══════════════════════════════════════════════════════════════

async def send_backup_to_admin(bot=None, admin_id=None):
    """
    متد قدیمی ارسال به چت خصوصی ادمین به طور کامل لغو شده است.
    منحصراً پشتیبان‌ها به کانال یا گروه مشخص‌شده ارسال می‌شوند.
    """
    logger.info("Legacy send_backup_to_admin called: Sending to admin private chat is permanently disabled.")
    return {"success": False, "error": "ارسال پشتیبان به چت خصوصی ادمین لغو شده است."}


# ═══════════════════════════════════════════════════════════════
# زمان‌بند هوشمند پشتیبان‌گیری خودکار (AutoBackupScheduler)
# ═══════════════════════════════════════════════════════════════

class AutoBackupScheduler:
    """
    زمان‌بند پیشرفته پشتیبان‌گیری خودکار
    - پشتیبانی از اجرای دوره‌ای (هر X ساعت)
    - پشتیبانی از اجرای سر ساعات مشخص شبانه‌روز (Fixed Hours)
    - ارسال مستقل پنل اصلی و هیدیفای به کانال/گروه تلگرام
    """

    def __init__(self, admin_id=None, db_instance=None):
        self.is_running = False
        self.task = None
        self.bot = None
        self.db = db_instance or db
        self.last_main_run_time = None
        self.last_hiddify_run_time = None
        self.last_main_slot = None
        self.last_hiddify_slot = None
        self.last_checked_hour = None

    def set_bot(self, bot):
        self.bot = bot

    def _load_last_run_times_from_db(self):
        """بازخوانی هوشمند تاریخچه آخرین بکاپ‌های موفق از دیتابیس هنگام استارت سیستم جهت جلوگیری از اجرای تکراری پس از دیپلوی"""
        try:
            stats = self.db.get_backup_stats()
            if stats.get("last_main") and stats["last_main"].get("created_at"):
                dt = parse_to_tehran_dt(stats["last_main"]["created_at"])
                if dt:
                    self.last_main_run_time = dt
                    self.last_main_slot = (dt.year, dt.month, dt.day, dt.hour)
            if stats.get("last_hiddify") and stats["last_hiddify"].get("created_at"):
                dt = parse_to_tehran_dt(stats["last_hiddify"]["created_at"])
                if dt:
                    self.last_hiddify_run_time = dt
                    self.last_hiddify_slot = (dt.year, dt.month, dt.day, dt.hour)
            logger.info(f"Loaded backup history from DB: last_main={self.last_main_run_time}, last_hiddify={self.last_hiddify_run_time}")
        except Exception as e:
            logger.warning(f"Could not load last backup times from database: {e}")

    async def start(self):
        if self.is_running:
            logger.warning("Auto backup scheduler is already running")
            return
        self.is_running = True
        self.task = asyncio.create_task(self._main_scheduler_loop())
        logger.info("Universal Auto Backup Scheduler started")

    async def stop(self):
        self.is_running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        logger.info("Universal Auto Backup Scheduler stopped")

    def _should_run_interval(self, last_run: datetime, interval_hours: int, now: datetime = None) -> bool:
        """بررسی فرارسیدن موعد اجرای دوره‌ای بر مبنای ساعت تهران"""
        if not last_run:
            return True
        if now is None:
            now = get_now()
        if last_run.tzinfo is None:
            last_run = last_run.replace(tzinfo=TEHRAN_TZ)
        if now.tzinfo is None:
            now = now.replace(tzinfo=TEHRAN_TZ)
        return (now - last_run) >= timedelta(hours=interval_hours)

    def _should_run_fixed_hours(self, fixed_hours_str: str, current_hour_or_now=None, last_slot=None, last_run=None) -> bool:
        """
        بررسی فرارسیدن موعد ساعت مشخص شبانه‌روز به وقت تهران.
        پشتیبانی دوگانه: عدد ساعت جهت سازگاری با تست‌های واحد، یا آبجکت datetime و بررسی اسلات و پنجره اجرا.
        """
        if not fixed_hours_str:
            return False

        if isinstance(current_hour_or_now, int):
            hours = [int(h.strip()) for h in fixed_hours_str.split(",") if h.strip().isdigit()]
            return current_hour_or_now in hours

        now = current_hour_or_now if isinstance(current_hour_or_now, datetime) else get_now()
        if now.tzinfo is None:
            now = now.replace(tzinfo=TEHRAN_TZ)

        hours = [int(h.strip()) for h in fixed_hours_str.split(",") if h.strip().isdigit()]
        current_hour = now.hour
        if current_hour not in hours:
            return False

        current_slot = (now.year, now.month, now.day, current_hour)
        if last_slot == current_slot:
            return False

        if last_run:
            if last_run.tzinfo is None:
                last_run = last_run.replace(tzinfo=TEHRAN_TZ)
            # اگر در کمتر از ۳۰ دقیقه گذشته بکاپ گرفته شده باشد (مثلاً ریستارت کانتینر در همان ساعت)، دوباره اجرا نشود
            if (now - last_run).total_seconds() < 1800:
                return False

        # پنجره باز اجرای مطمئن در ۱۵ دقیقه اول ساعت
        return now.minute < 15

    async def _main_scheduler_loop(self):
        """حلقه اصلی بررسی هر ۶۰ ثانیه به وقت تهران"""
        logger.info("Backup scheduler loop active")
        # بارگذاری آخرین سابقه اجرا از دیتابیس
        self._load_last_run_times_from_db()

        # مکث اولیه کوتاه بعد از استارت سیستم
        await asyncio.sleep(45)

        while self.is_running:
            try:
                main_enabled = self.db.is_setting_enabled("backup_main_enabled", default=True)
                hiddify_enabled = self.db.is_setting_enabled("backup_hiddify_enabled", default=True)
                sched_type = str(self.db.get_setting("backup_schedule_type", "interval") or "interval").strip()
                try:
                    interval_hours = int(self.db.get_setting("backup_interval_hours", 6) or 6)
                except Exception:
                    interval_hours = 6
                fixed_hours_str = str(self.db.get_setting("backup_fixed_hours", "00,06,12,18") or "00,06,12,18").strip()

                now = get_now()
                current_hour = now.hour
                current_slot = (now.year, now.month, now.day, current_hour)

                # ۱. بررسی اجرای پشتیبان‌گیری پنل اصلی
                if main_enabled:
                    run_main = False
                    if sched_type == "fixed_hours":
                        if self._should_run_fixed_hours(fixed_hours_str, now, self.last_main_slot, self.last_main_run_time):
                            run_main = True
                    else:
                        if self._should_run_interval(self.last_main_run_time, interval_hours, now):
                            run_main = True

                    if run_main:
                        logger.info("Executing scheduled Main Panel backup...")
                        # ثبت اسلات قبل از اجرا جهت جلوگیری از اجرای موازی در تسک‌های طولانی
                        self.last_main_slot = current_slot
                        self.last_main_run_time = now
                        await asyncio.to_thread(trigger_main_panel_backup, trigger_type="auto")
                        self.last_main_run_time = get_now()

                # ۲. بررسی اجرای پشتیبان‌گیری پنل هیدیفای
                if hiddify_enabled:
                    run_hid = False
                    if sched_type == "fixed_hours":
                        if self._should_run_fixed_hours(fixed_hours_str, now, self.last_hiddify_slot, self.last_hiddify_run_time):
                            run_hid = True
                    else:
                        if self._should_run_interval(self.last_hiddify_run_time, interval_hours, now):
                            run_hid = True

                    if run_hid:
                        logger.info("Executing scheduled Hiddify backup...")
                        self.last_hiddify_slot = current_slot
                        self.last_hiddify_run_time = now
                        await trigger_hiddify_panel_backup_async(trigger_type="auto")
                        self.last_hiddify_run_time = get_now()

                self.last_checked_hour = current_hour

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in backup scheduler loop: {e}", exc_info=True)

            # هر ۶۰ ثانیه بررسی تکرار می‌شود
            await asyncio.sleep(60)


# سازگاری با کدهای پیشین که مستقیماً trigger_hiddify_backup را ایمپورت می‌کردند
async def trigger_hiddify_backup(db_instance=None):
    return await trigger_hiddify_panel_backup_async(trigger_type="auto")
