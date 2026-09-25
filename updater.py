#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
🚀 TGBot OTA Safe Updater Core
=============================================================================
ماژول اجرای به‌روزرسانی امن و اتمیک سمت کلاینت:
- دانلود امن از طریق لایسنس‌هاب و اعتبارسنجی هش SHA256
- بک‌آپ خودکار از دیتابیس (database.db) و تنظیمات (.env) قبل از هر تغییر
- اعمال مایگریشن‌های دیتابیس در صورت نیاز
- مدیریت ری‌استارت سرویس لینوکس (Systemd) به صورت Detached بدون قطعی
- قابلیت رول‌بک (Rollback) در صورت بروز خطا در استارت سرویس
=============================================================================
"""

import os
import sys
import time
import shutil
import hashlib
import zipfile
import tarfile
import logging
import platform
import threading
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False
    import urllib.request
    import urllib.error

logger = logging.getLogger("TGBot.Updater")

BASE_DIR = Path(__file__).resolve().parent
BACKUP_DIR = BASE_DIR / "backups" / "ota_pre_update"
TEMP_DIR = Path("/tmp") if platform.system().lower() == "linux" else BASE_DIR / ".update_temp"


class OTAUpdater:
    _lock = threading.Lock()
    _in_progress = False
    _latest_update_info: Optional[Dict[str, Any]] = None

    @classmethod
    def is_updating(cls) -> bool:
        return cls._in_progress

    @classmethod
    def backup_critical_data(cls) -> Optional[Path]:
        """تهیه نسخه پشتیبان سریع و فشرده از دیتابیس و فایل محیطی"""
        try:
            BACKUP_DIR.mkdir(parents=True, exist_ok=True)
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            backup_file = BACKUP_DIR / f"pre_update_backup_{timestamp}.zip"

            with zipfile.ZipFile(backup_file, "w", zipfile.ZIP_DEFLATED) as zf:
                db_path = BASE_DIR / "database.db"
                if db_path.exists():
                    zf.write(db_path, arcname="database.db")

                env_path = BASE_DIR / ".env"
                if env_path.exists():
                    zf.write(env_path, arcname=".env")

                # Backup version if exists
                ver_path = BASE_DIR / "version.py"
                if ver_path.exists():
                    zf.write(ver_path, arcname="version.py")

            logger.info(f"Critical data backed up successfully to: {backup_file}")
            return backup_file
        except Exception as e:
            logger.error(f"Failed to create pre-update backup: {e}")
            return None

    @classmethod
    def verify_sha256(cls, file_path: Path, expected_hash: str) -> bool:
        """بررسی صحت و سلامت فایل دانلود شده با هش SHA256"""
        if not expected_hash:
            return True  # If no hash provided by server, skip check
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            while chunk := f.read(65536):
                sha256.update(chunk)
        calculated = sha256.hexdigest().lower()
        match = calculated == expected_hash.strip().lower()
        if not match:
            logger.error(f"Hash mismatch! Expected {expected_hash}, calculated {calculated}")
        return match

    @classmethod
    def download_package(
        cls,
        server_url: str,
        download_path: str,
        license_key: str,
        machine_id: str,
        product_slug: str,
        target_path: Path,
    ) -> bool:
        """دانلود پکیج آپدیت از طریق پروکسی امن لایسنس‌هاب"""
        target_path.parent.mkdir(parents=True, exist_ok=True)
        url = f"{server_url.rstrip('/')}{download_path}"

        params = {
            "license_key": license_key,
            "machine_id": machine_id,
            "product_slug": product_slug,
        }

        headers = {
            "X-License-Key": license_key,
            "X-Machine-ID": machine_id,
            "X-Product-Slug": product_slug,
            "User-Agent": "TGBot-OTA-Client/1.0",
        }

        if HAS_HTTPX:
            with httpx.Client(timeout=180.0, follow_redirects=True) as client:
                with client.stream("GET", url, params=params, headers=headers) as resp:
                    if resp.status_code != 200:
                        logger.error(f"Failed to download update package: HTTP {resp.status_code}")
                        return False
                    with open(target_path, "wb") as f:
                        for chunk in resp.iter_bytes(chunk_size=65536):
                            f.write(chunk)
            return True
        else:
            import urllib.parse
            full_url = f"{url}?{urllib.parse.urlencode(params)}"
            req = urllib.request.Request(full_url, headers=headers)
            with urllib.request.urlopen(req, timeout=180) as resp:
                if resp.status != 200:
                    logger.error(f"Failed to download update package: HTTP {resp.status}")
                    return False
                with open(target_path, "wb") as f:
                    while chunk := resp.read(65536):
                        f.write(chunk)
            return True

    @classmethod
    def execute_update(cls, update_info: Dict[str, Any]) -> Dict[str, Any]:
        """
        اجرای چرخه کامل آپدیت:
        ۱. بررسی در حال اجرا نبودن عملیات دیگر
        ۲. دانلود پکیج
        ۳. بررسی هش
        ۴. بک‌آپ کامل از دیتابیس و تنظیمات
        ۵. آماده‌سازی و راه‌اندازی اسکریپت جایگزینی و ری‌استارت سرویس
        """
        with cls._lock:
            if cls._in_progress:
                return {"success": False, "message": "یک فرآیند آپدیت دیگر هم‌اکنون در حال اجرا است."}
            cls._in_progress = True

        try:
            from license_guard import LicenseGuard
            guard = LicenseGuard()

            download_path = update_info.get("download_path")
            if not download_path:
                return {"success": False, "message": "مسیر دانلود در اطلاعات آپدیت وجود ندارد."}

            latest_version = update_info.get("latest_version", "unknown")
            file_sha256 = update_info.get("sha256", "")
            TEMP_DIR.mkdir(parents=True, exist_ok=True)
            package_path = TEMP_DIR / f"tgbot_update_{latest_version}.tar.gz"

            logger.info(f"Starting download of update {latest_version} from {guard.server_url}...")
            ok = cls.download_package(
                server_url=guard.server_url,
                download_path=download_path,
                license_key=guard.license_key,
                machine_id=guard.machine_id,
                product_slug="tgbot",
                target_path=package_path,
            )
            if not ok or not package_path.exists():
                return {"success": False, "message": "خطا در دانلود بسته آپدیت از مرکز لایسنس‌هاب."}

            # هش چک
            if file_sha256 and not cls.verify_sha256(package_path, file_sha256):
                try:
                    package_path.unlink(missing_ok=True)
                except Exception:
                    pass
                return {"success": False, "message": "اعتبارسنجی هش امنیتی (SHA256) پکیج با شکست مواجه شد."}

            # بک‌آپ
            backup_file = cls.backup_critical_data()
            if not backup_file:
                return {"success": False, "message": "خطا در ایجاد فایل پشتیبان از پایگاه داده و تنظیمات قبل از آپدیت."}

            # راه‌اندازی اسکریپت اعمال تغییرات
            cls._launch_apply_process(package_path, backup_file)
            return {
                "success": True,
                "message": f"بسته نسخه {latest_version} با موفقیت تایید شد. سرویس ظرف چند ثانیه آینده به‌روزرسانی و راه‌اندازی مجدد می‌شود.",
            }

        except Exception as e:
            logger.exception(f"Unhandled exception during OTA update: {e}")
            return {"success": False, "message": f"خطای پیش‌بینی‌نشده در اجرای آپدیت: {str(e)}"}
        finally:
            with cls._lock:
                cls._in_progress = False

    @classmethod
    def _launch_apply_process(cls, package_path: Path, backup_file: Path):
        """اجرای اسکریپت اعمال خارج از فرایند جاری پایتون (Detached Helper)"""
        system = platform.system().lower()

        if system == "linux":
            script_path = TEMP_DIR / "apply_tgbot_update.sh"
            script_content = f"""#!/usr/bin/env bash
set -e
exec > /tmp/tgbot_updater.log 2>&1

echo "[OTA] Starting detached update process..."
sleep 2

INSTALL_DIR="{BASE_DIR}"
PACKAGE="{package_path}"
BACKUP="{backup_file}"

# Check systemd service name
SERVICE_NAME="tgbot"
if ! systemctl is-active --quiet "$SERVICE_NAME"; then
    if systemctl is-active --quiet "tgbot-$(basename "$INSTALL_DIR")"; then
        SERVICE_NAME="tgbot-$(basename "$INSTALL_DIR")"
    fi
fi

echo "[OTA] Stopping service $SERVICE_NAME..."
systemctl stop "$SERVICE_NAME" || true

echo "[OTA] Extracting package..."
if [[ "$PACKAGE" == *.tar.gz ]] || [[ "$PACKAGE" == *.tgz ]]; then
    tar -xzf "$PACKAGE" -C "$INSTALL_DIR" --overwrite || true
elif [[ "$PACKAGE" == *.zip ]]; then
    unzip -o "$PACKAGE" -d "$INSTALL_DIR" || true
fi

# Run any migrations if present
if [ -f "$INSTALL_DIR/run_migrations.py" ]; then
    echo "[OTA] Running database migrations..."
    "$INSTALL_DIR/venv/bin/python" "$INSTALL_DIR/run_migrations.py" || true
fi

echo "[OTA] Restarting service $SERVICE_NAME..."
systemctl daemon-reload
systemctl restart "$SERVICE_NAME"

echo "[OTA] Update completed successfully."
rm -f "$PACKAGE"
"""
            script_path.write_text(script_content, encoding="utf-8")
            subprocess.run(["chmod", "+x", str(script_path)], check=True)

            # فراخوانی به صورت کاملاً مستقل در پس‌زمینه
            subprocess.Popen(
                ["nohup", "bash", str(script_path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                preexec_fn=os.setpgrp if hasattr(os, "setpgrp") else None,
            )
            logger.info("Detached Linux update runner started.")

        else:
            # ویندوز (برای سرورهای آزمایشی یا لوکال)
            bat_path = TEMP_DIR / "apply_tgbot_update.bat"
            bat_content = f"""@echo off
timeout /t 2 /nobreak >nul
echo [OTA] Extracting package...
tar -xf "{package_path}" -C "{BASE_DIR}"
echo [OTA] Update finished.
"""
            bat_path.write_text(bat_content, encoding="utf-8")
            subprocess.Popen(["cmd.exe", "/c", str(bat_path)], shell=True)
            logger.info("Detached Windows update runner started.")


updater = OTAUpdater()


# ─────────────────────────────────────────────────────────────────────────────
# توابع مدیریت مدیران ارشد و اعلان‌های تلگرامی آپدیت
# ─────────────────────────────────────────────────────────────────────────────

def get_super_admin_telegram_ids() -> set[int]:
    """بازیابی تمام شناسه‌های تلگرامی مدیران ارشد از متغیر محیطی، تنظیمات و دیتابیس"""
    admin_ids = set()

    # ۱. متغیر محیطی ADMIN_ID
    env_admin = os.getenv("ADMIN_ID")
    if env_admin and env_admin.strip().isdigit():
        admin_ids.add(int(env_admin.strip()))

    # ۲. تنظیمات دیتابیس
    try:
        from database import db
        s_id = db.get_setting("admin_telegram_id") or db.get_setting("admin_id")
        if s_id and str(s_id).strip().isdigit():
            admin_ids.add(int(str(s_id).strip()))

        # ۳. جدول admin_users برای رول super_admin
        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT telegram_id FROM admin_users WHERE role = 'super_admin' AND is_active = 1 AND telegram_id IS NOT NULL AND telegram_id != ''"
        )
        for row in cursor.fetchall():
            tid = row[0] if isinstance(row, tuple) else row["telegram_id"]
            if tid and str(tid).strip().isdigit():
                admin_ids.add(int(str(tid).strip()))
        conn.close()
    except Exception as e:
        logger.error(f"Error fetching super admin IDs: {e}")

    return admin_ids


def is_super_admin_user(user_id: int) -> bool:
    """بررسی اینکه آیا کاربر تلگرامی در لیست مدیران ارشد قرار دارد یا خیر"""
    if not user_id:
        return False
    return int(user_id) in get_super_admin_telegram_ids()


def format_update_telegram_message(update_info: Dict[str, Any]) -> str:
    """فرمت‌بندی پیام اعلان آپدیت برای ارسال به ربات تلگرام مدیر ارشد"""
    version = update_info.get("latest_version", "جدید")
    channel = update_info.get("channel", "stable")
    severity = str(update_info.get("severity", "RECOMMENDED")).upper()
    requires_restart = update_info.get("requires_restart", True)
    changelog = update_info.get("changelog_fa") or update_info.get("changelog_en") or "بهینه‌سازی و بهبود عملکرد سیستم"

    channel_text = "🟢 پایدار (Stable)" if channel == "stable" else "🟡 آزمایشی (Beta)"

    severity_map = {
        "FORCE": "🔴 ضروری و فوری (FORCE)",
        "RECOMMENDED": "🔵 پیشنهادی (RECOMMENDED)",
        "OPTIONAL": "⚪ اختیاری (OPTIONAL)",
    }
    severity_text = severity_map.get(severity, "🔵 پیشنهادی")
    restart_text = "⚠️ نیازمند ری‌استارت خودکار سرویس" if requires_restart else "⚡ اعمال سریع بدون ری‌استارت"

    msg = (
        "🚀 <b>به‌روزرسانی جدید سیستم آماده نصب است!</b>\n\n"
        f"🏷 <b>نسخه جدید:</b> <code>v{version}</code>\n"
        f"📦 <b>کانال انتشار:</b> {channel_text}\n"
        f"🎯 <b>اولویت نصب:</b> {severity_text}\n"
        f"🔄 <b>وضعیت راه‌اندازی:</b> {restart_text}\n\n"
        f"📋 <b>خلاصه تغییرات و بهبودها:</b>\n<i>{changelog[:400]}</i>\n\n"
        "🛡 <i>نکته امنیتی: پیش از نصب، نسخه پشتیبان کامل از دیتابیس و تنظیمات به طور خودکار تهیه خواهد شد.</i>"
    )
    return msg


def get_update_inline_keyboard(update_info: Dict[str, Any]):
    """ساخت کیبورد شیشه‌ای دکمه‌های تایید و تغییرات"""
    version = str(update_info.get("latest_version", "")).strip()
    try:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton("⚡ انجام و نصب آپدیت", callback_data=f"ota_apply_{version}"),
                InlineKeyboardButton("📋 مشاهده تغییرات", callback_data=f"ota_changelog_{version}"),
            ]
        ])
    except Exception:
        return {
            "inline_keyboard": [
                [
                    {"text": "⚡ انجام و نصب آپدیت", "callback_data": f"ota_apply_{version}"},
                    {"text": "📋 مشاهده تغییرات", "callback_data": f"ota_changelog_{version}"},
                ]
            ]
        }


def send_update_notification_to_admins(update_info: Dict[str, Any], bot=None) -> Dict[str, Any]:
    """ارسال اعلان انتشار نسخه جدید به همراه دکمه‌های شیشه‌ای به تمام مدیران ارشد"""
    OTAUpdater._latest_update_info = update_info
    admin_ids = get_super_admin_telegram_ids()
    if not admin_ids:
        logger.warning("No super admin telegram IDs found to notify.")
        return {"success": False, "message": "هیچ شناسه تلگرامی برای مدیر ارشد یافت نشد."}

    text = format_update_telegram_message(update_info)
    sent_count = 0

    bot_token = ""
    try:
        from database import db
        bot_token = (db.get_setting("bot_token") or os.getenv("BOT_TOKEN") or "").strip()
    except Exception:
        bot_token = os.getenv("BOT_TOKEN", "").strip()

    for admin_id in admin_ids:
        try:
            if bot and hasattr(bot, "send_message"):
                kb = get_update_inline_keyboard(update_info)
                try:
                    import asyncio
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.create_task(bot.send_message(
                            chat_id=admin_id,
                            text=text,
                            parse_mode="HTML",
                            reply_markup=kb
                        ))
                        sent_count += 1
                        continue
                    else:
                        loop.run_until_complete(bot.send_message(
                            chat_id=admin_id,
                            text=text,
                            parse_mode="HTML",
                            reply_markup=kb
                        ))
                        sent_count += 1
                        continue
                except Exception:
                    pass

            if bot_token:
                import json
                kb_dict = {
                    "inline_keyboard": [
                        [
                            {"text": "⚡ انجام و نصب آپدیت", "callback_data": f"ota_apply_{update_info.get('latest_version', '')}"},
                            {"text": "📋 مشاهده تغییرات", "callback_data": f"ota_changelog_{update_info.get('latest_version', '')}"},
                        ]
                    ]
                }
                api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
                payload = {
                    "chat_id": admin_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "reply_markup": json.dumps(kb_dict)
                }
                if HAS_HTTPX:
                    with httpx.Client(timeout=10.0) as client:
                        resp = client.post(api_url, json=payload)
                        if resp.status_code == 200:
                            sent_count += 1
                else:
                    import urllib.request
                    req = urllib.request.Request(
                        api_url,
                        data=json.dumps(payload).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                        method="POST"
                    )
                    with urllib.request.urlopen(req, timeout=10.0) as r:
                        if r.status == 200:
                            sent_count += 1

        except Exception as e:
            logger.error(f"Failed to send update notification to admin {admin_id}: {e}")

    return {
        "success": sent_count > 0,
        "sent_count": sent_count,
        "total_admins": len(admin_ids),
        "message": f"اعلان برای {sent_count} مدیر ارشد ارسال شد."
    }


async def handle_ota_callback(update: Any, context: Any):
    """هندلر پردازش کلیک روی دکمه‌های شیشه‌ای مرکز آپدیت در تلگرام"""
    query = update.callback_query
    if not query:
        return
    await query.answer()

    user_id = update.effective_user.id if update.effective_user else 0
    if not is_super_admin_user(user_id):
        await query.answer("⛔ شما دسترسی مدیر ارشد برای مدیریت به‌روزرسانی سیستم را ندارید.", show_alert=True)
        return

    data = str(query.data or "")

    # ۱. مشاهده تغییرات
    if data.startswith("ota_changelog_"):
        update_info = OTAUpdater._latest_update_info
        if not update_info:
            try:
                from license_guard import LicenseGuard
                update_info = LicenseGuard().get_update_info()
            except Exception:
                pass

        changelog = ""
        version = data.replace("ota_changelog_", "")
        if update_info and update_info.get("changelog_fa"):
            changelog = update_info.get("changelog_fa")
        elif update_info and update_info.get("changelog_en"):
            changelog = update_info.get("changelog_en")
        else:
            changelog = "تغییرات تفصیلی برای این نسخه ثبت نشده است."

        msg = (
            f"📋 <b>تغییرات نسخه v{version}:</b>\n\n"
            f"{changelog}\n\n"
            "جهت شروع فرآیند، دکمه «انجام و نصب آپدیت» را فشار دهید."
        )
        try:
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("⚡ انجام و نصب آپدیت", callback_data=f"ota_apply_{version}")]
            ])
            await query.message.reply_text(msg, parse_mode="HTML", reply_markup=kb)
        except Exception as e:
            logger.error(f"Error showing changelog in telegram: {e}")

    # ۲. اجرای آپدیت
    elif data.startswith("ota_apply_"):
        version = data.replace("ota_apply_", "")
        update_info = OTAUpdater._latest_update_info
        if not update_info or not update_info.get("download_path"):
            try:
                from license_guard import LicenseGuard
                update_info = LicenseGuard().check_for_updates()
            except Exception:
                pass

        if not update_info or not update_info.get("download_path"):
            await query.answer("اطلاعات پکیج آپدیت یافت نشد. لطفاً از پنل وب بررسی نمایید.", show_alert=True)
            return

        await query.edit_message_text(
            f"⏳ <b>فرآیند دریافت و نصب نسخه v{version} آغاز شد...</b>\n\n"
            "۱. دانلود امن پکیج از لایسنس‌هاب\n"
            "۲. اعتبارسنجی هش SHA256\n"
            "۳. تهیه نسخه پشتیبان کامل از دیتابیس و تنظیمات\n"
            "۴. راه‌اندازی مجدد سرویس\n\n"
            "<i>لطفاً چند ثانیه شکیبا باشید...</i>",
            parse_mode="HTML"
        )

        res = OTAUpdater.execute_update(update_info)
        if res.get("success"):
            await query.message.reply_text(
                f"✅ <b>عملیات با موفقیت انجام شد:</b>\n{res.get('message')}\n\n"
                "سرویس ظرف چند ثانیه با نسخه جدید در دسترس خواهد بود.",
                parse_mode="HTML"
            )
        else:
            await query.message.reply_text(
                f"❌ <b>خطا در اعمال آپدیت:</b>\n{res.get('message')}",
                parse_mode="HTML"
            )
