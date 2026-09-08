#!/usr/bin/env python3
"""
ماژول پشتیبان‌گیری خودکار از دیتابیس
"""

import os
import shutil
import logging
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from database import db, DB_DIR
from utils import get_now_shamsi, get_now_naive, get_now

logger = logging.getLogger(__name__)

# مسیر پشتیبان‌ها - ذخیره در کنار دیتابیس (Railway Volume یا محلی)
BACKUP_DIR = DB_DIR / "backups"
BACKUP_DIR.mkdir(parents=True, exist_ok=True)


class BackupManager:
    """کلاس مدیریت پشتیبان‌گیری"""

    def __init__(self):
        pass

    def create_backup(self):
        """ایجاد پشتیبان از دیتابیس"""
        try:
            timestamp = get_now_naive().strftime("%Y%m%d_%H%M%S")
            backup_filename = f"backup_{timestamp}.db"
            backup_path = BACKUP_DIR / backup_filename

            # کپی دیتابیس
            source_path = db.db_path
            if source_path.exists():
                shutil.copy2(source_path, backup_path)
                backup_size = backup_path.stat().st_size

                # ذخیره رکورد پشتیبان
                result = db.save_backup_record(str(backup_path), backup_size)

                # خروجی نسخه جامع JSON
                try:
                    db.export_full_backup_json()
                except Exception:
                    pass

                logger.info(f"Backup created: {backup_filename} ({backup_size} bytes)")
                return {
                    "success": True,
                    "file": str(backup_path),
                    "filename": backup_filename,
                    "size": backup_size,
                    "backup_id": result.get("id"),
                }
            else:
                logger.error("Database file not found")
                return {"success": False, "error": "Database file not found"}

        except Exception as e:
            logger.error(f"Error creating backup: {e}")
            return {"success": False, "error": str(e)}

    def restore_backup(self, backup_path):
        """بازیابی دیتابیس از پشتیبان"""
        try:
            backup_path = Path(backup_path)
            if not backup_path.exists():
                return {"success": False, "error": "Backup file not found"}

            # کپی به عنوان پشتیبان از وضعیت فعلی
            current_backup = BACKUP_DIR / f"pre_restore_{get_now_naive().strftime('%Y%m%d_%H%M%S')}.db"
            if db.db_path.exists():
                shutil.copy2(db.db_path, current_backup)

            # بازیابی
            shutil.copy2(backup_path, db.db_path)

            logger.info(f"Database restored from {backup_path.name}")
            return {
                "success": True,
                "message": f"Database restored from {backup_path.name}",
                "pre_restore_backup": str(current_backup),
            }

        except Exception as e:
            logger.error(f"Error restoring backup: {e}")
            return {"success": False, "error": str(e)}

    def list_backups(self):
        """لیست پشتیبان‌های موجود"""
        backups = []
        for backup_file in sorted(BACKUP_DIR.glob("backup_*.db"), reverse=True):
            backups.append({
                "filename": backup_file.name,
                "path": str(backup_file),
                "size": backup_file.stat().st_size,
                "created": datetime.fromtimestamp(backup_file.stat().st_mtime).isoformat(),
            })
        return backups

    def delete_old_backups(self, keep_count=10):
        """حذف پشتیبان‌های قدیمی"""
        backups = sorted(BACKUP_DIR.glob("backup_*.db"), key=lambda x: x.stat().st_mtime)
        if len(backups) > keep_count:
            for backup in backups[:len(backups) - keep_count]:
                backup.unlink()
                logger.info(f"Deleted old backup: {backup.name}")


async def send_backup_to_admin(bot, admin_id):
    """ارسال پشتیبان به ادمین ارشد سامانه (فقط Super Admin)"""
    if not bot:
        logger.error("Bot not set for backup")
        return {"success": False, "error": "Bot not set"}

    # اعتبارسنجی قطعی مقصد: پشتیبان باید صرفاً و منحصراً به مدیر ارشد سیستم ارسال شود
    # و تحت هیچ شرایطی به نماینده یا ادمین ربات نماینده ارسال نگردد!
    target_admin_id = admin_id
    try:
        conn = db.get_connection()
        sa_row = conn.execute("SELECT telegram_id FROM admin_users WHERE role='super_admin' AND is_active=1 AND telegram_id IS NOT NULL LIMIT 1").fetchone()
        conn.close()
        if sa_row and sa_row["telegram_id"]:
            target_admin_id = sa_row["telegram_id"]
    except Exception as e_sa:
        logger.debug(f"Error resolving super_admin telegram_id: {e_sa}")

    if not target_admin_id:
        logger.error("No valid super admin Telegram ID found for backup")
        return {"success": False, "error": "No super admin found"}

    # بررسی صریح عدم ارسال به نماینده یا ادمین ربات نماینده
    try:
        is_r_adm, _, _ = db.is_telegram_user_any_reseller_admin(target_admin_id)
        is_reseller = db.get_reseller_by_telegram_id(target_admin_id) is not None
        if is_r_adm or is_reseller:
            logger.warning(f"Prevented sending backup to reseller or reseller admin: {target_admin_id}")
            return {"success": False, "error": "Recipient is a reseller admin; backup sending aborted"}
    except Exception as e_chk:
        logger.warning(f"Error checking reseller status for backup recipient: {e_chk}")

    try:
        backup_mgr = BackupManager()
        
        # ایجاد پشتیبان
        backup_result = backup_mgr.create_backup()
        if not backup_result.get("success"):
            return backup_result

        backup_path = backup_result["file"]
        backup_size = backup_result["size"]
        backup_id = backup_result.get("backup_id")

        # ارسال فایل به ادمین ارشد
        with open(backup_path, "rb") as f:
            await bot.send_document(
                chat_id=target_admin_id,
                document=f,
                caption=f"🔒 پشتیبان خودکار دیتابیس\n\n"
                        f"📅 تاریخ: {get_now_shamsi()}\n"
                        f"📊 حجم: {backup_size:,} بایت\n"
                        f"📁 فایل: {backup_result['filename']}\n\n"
                        f"برای بازیابی، فایل را ذخیره کرده و دکمه «🔄 بازیابی پشتیبان» را بزنید.",
            )

        # علامت‌گذاری آپلود شده
        if backup_id:
            db.mark_backup_uploaded(backup_id)

        # حذف پشتیبان‌های قدیمی
        backup_mgr.delete_old_backups()

        logger.info(f"Backup sent to super admin {target_admin_id}")
        return {"success": True, "filename": backup_result["filename"]}

    except Exception as e:
        logger.error(f"Error sending backup to admin: {e}")
        return {"success": False, "error": str(e)}


class AutoBackupScheduler:
    """زمان‌بند پشتیبان‌گیری خودکار - ساعت 12 و 24"""

    def __init__(self, admin_id):
        self.admin_id = admin_id
        self.is_running = False
        self.task = None
        self.bot = None

    def set_bot(self, bot):
        """تنظیم bot بعد از شروع application"""
        self.bot = bot

    async def start(self):
        """شروع پشتیبان‌گیری خودکار"""
        if self.is_running:
            logger.warning("Auto backup scheduler is already running")
            return

        self.is_running = True
        self.task = asyncio.create_task(self._run_scheduler())
        logger.info("Auto backup scheduler started (every 12 hours at 12:00 and 00:00)")

    async def stop(self):
        """توقف پشتیبان‌گیری خودکار"""
        self.is_running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        logger.info("Auto backup scheduler stopped")

    def _seconds_until_next(self, hour: int) -> float:
        """محاسبه ثانیه‌های باقیمانده تا ساعت مشخص"""
        now = get_now_naive()
        target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return (target - now).total_seconds()

    async def _run_scheduler(self):
        """حلقه اصلی زمان‌بند - ارسال دقیقاً در ساعت 12 و 24"""
        while self.is_running:
            try:
                # انتظار تا ساعت 12 بعدی
                wait_12 = self._seconds_until_next(12)
                logger.info(f"Next backup at 12:00 (in {wait_12/3600:.1f} hours)")
                await asyncio.sleep(wait_12)

                if not self.is_running:
                    break

                # ارسال پشتیبان ساعت 12
                if self.bot:
                    logger.info("Creating 12:00 backup...")
                    result = await send_backup_to_admin(self.bot, self.admin_id)
                    if result.get("success"):
                        logger.info(f"12:00 backup completed: {result.get('filename')}")

                # انتظار تا ساعت 24 (نیمه‌شب)
                wait_24 = self._seconds_until_next(0)
                logger.info(f"Next backup at 00:00 (in {wait_24/3600:.1f} hours)")
                await asyncio.sleep(wait_24)

                if not self.is_running:
                    break

                # ارسال پشتیبان ساعت 24
                if self.bot:
                    logger.info("Creating 00:00 backup...")
                    result = await send_backup_to_admin(self.bot, self.admin_id)
                    if result.get("success"):
                        logger.info(f"00:00 backup completed: {result.get('filename')}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in auto backup scheduler: {e}")
                await asyncio.sleep(300)  # 5 دقیقه صبر در صورت خطا


# نمونه singleton (فقط برای BackupManager)
backup_manager = BackupManager()
