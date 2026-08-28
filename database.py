#!/usr/bin/env python3
"""
ماژول دیتابیس برای ذخیره‌سازی مشتریان، تنظیمات و تراکنش‌ها
"""

import sqlite3
import json
import os
import logging
from datetime import datetime, timedelta
from utils import get_now_naive, get_now_iso
from pathlib import Path

logger = logging.getLogger(__name__)

# مسیر دیتابیس - از Railway persistent storage یا متغیر محیطی استفاده میکنه
# Railway: اگر Volume دارید، DATA_DIR=/data تنظیم کنید
# در غیر این صورت، دیتابیس در مسیر پروژه ذخیره میشه
POSSIBLE_PATHS = [
    Path(os.environ.get("DATA_DIR", "")),  # Railway Volume
    Path("/data"),  # Railway default persistent
    Path(os.path.expanduser("~/.vpn-bot/data")),  # Home directory
    Path("data"),  # Fallback to project directory
]

DB_DIR = None
for path in POSSIBLE_PATHS:
    if path and path != Path(""):
        try:
            path.mkdir(parents=True, exist_ok=True)
            # تست نوشتن
            test_file = path / ".write_test"
            test_file.write_text("test")
            test_file.unlink()
            DB_DIR = path
            break
        except (PermissionError, OSError) as e:
            logger.warning(f"Cannot write to {path}: {e}")
            continue

if DB_DIR is None:
    DB_DIR = Path("data")
    DB_DIR.mkdir(exist_ok=True)

DB_PATH = DB_DIR / "bot_database.db"
logger.info(f"Database path: {DB_PATH}")
logger.info(f"Data directory: {DB_DIR}")


class Database:
    """کلاس مدیریت دیتابیس"""

    def __init__(self, db_path=None):
        self.db_dir = DB_DIR
        self.db_path = db_path or DB_PATH
        self.init_db()
        self.migrate_add_columns()

    def get_connection(self):
        """دریافت اتصال دیتابیس"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def init_db(self):
        """ایجاد جداول دیتابیس"""
        conn = self.get_connection()
        cursor = conn.cursor()

        # جدول مشتریان
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE NOT NULL,
                username TEXT,
                phone_number TEXT,
                is_verified BOOLEAN DEFAULT 0,
                hidify_uuid TEXT,
                plan_id TEXT,
                data_limit REAL DEFAULT 0,
                expire_at INTEGER,
                language TEXT DEFAULT 'fa',
                created_at TEXT,
                updated_at TEXT
            )
        """)

        # جدول اشتراک‌ها
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL,
                hidify_uuid TEXT,
                plan_id TEXT,
                plan_name TEXT,
                account_name TEXT,
                account_comment TEXT,
                data_limit REAL DEFAULT 0,
                data_used REAL DEFAULT 0,
                duration INTEGER DEFAULT 30,
                start_date TEXT,
                expire_date TEXT,
                status TEXT DEFAULT 'active',
                created_at TEXT,
                updated_at TEXT,
                FOREIGN KEY (telegram_id) REFERENCES users(telegram_id)
            )
        """)

        # جدول تراکنش‌ها
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT UNIQUE NOT NULL,
                user_id INTEGER NOT NULL,
                username TEXT,
                plan_name TEXT,
                amount INTEGER,
                gateway TEXT,
                tracking_code TEXT,
                account_name TEXT,
                account_comment TEXT,
                status TEXT DEFAULT 'pending',
                ref_id TEXT,
                subscription_id INTEGER,
                created_at TEXT,
                updated_at TEXT,
                FOREIGN KEY (user_id) REFERENCES users(telegram_id),
                FOREIGN KEY (subscription_id) REFERENCES subscriptions(id)
            )
        """)

        # جدول تنظیمات
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TEXT
            )
        """)

        # جدول پشتیبان‌ها
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS backups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                backup_file TEXT,
                backup_size INTEGER,
                created_at TEXT,
                uploaded BOOLEAN DEFAULT 0
            )
        """)

        # جدول کیف پول
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS wallet (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE NOT NULL,
                balance INTEGER DEFAULT 0,
                created_at TEXT,
                updated_at TEXT,
                FOREIGN KEY (telegram_id) REFERENCES users(telegram_id)
            )
        """)

        # جدول کدهای تخفیف
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS discount_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE NOT NULL,
                discount_percent INTEGER DEFAULT 0,
                discount_amount INTEGER DEFAULT 0,
                max_uses INTEGER DEFAULT 0,
                used_count INTEGER DEFAULT 0,
                valid_until TEXT,
                is_active BOOLEAN DEFAULT 1,
                created_at TEXT,
                updated_at TEXT
            )
        """)

        # جدول بلاک لیست
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS blocked_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE NOT NULL,
                reason TEXT,
                blocked_by INTEGER,
                created_at TEXT
            )
        """)

        # جدول تیکت‌های پشتیبانی
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS support_tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL,
                subject TEXT,
                message TEXT,
                status TEXT DEFAULT 'open',
                admin_reply TEXT,
                created_at TEXT,
                updated_at TEXT,
                FOREIGN KEY (telegram_id) REFERENCES users(telegram_id)
            )
        """)

        # جدول اعلان‌های ارسال شده
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sent_notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL,
                notification_type TEXT,
                subscription_id INTEGER,
                sent_at TEXT,
                FOREIGN KEY (telegram_id) REFERENCES users(telegram_id)
            )
        """)

        # جدول رفرال و معرفی
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id INTEGER NOT NULL,
                referred_id INTEGER UNIQUE NOT NULL,
                reward_amount INTEGER DEFAULT 0,
                status TEXT DEFAULT 'pending',
                created_at TEXT,
                updated_at TEXT
            )
        """)

        # جدول همکاران و نمایندگان فروش (Resellers)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS resellers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                name TEXT NOT NULL,
                telegram_id INTEGER,
                balance INTEGER DEFAULT 0,
                discount_percent INTEGER DEFAULT 20,
                status TEXT DEFAULT 'active',
                created_at TEXT,
                updated_at TEXT
            )
        """)

        # جدول تراکنش‌های نمایندگان
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS reseller_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reseller_id INTEGER NOT NULL,
                type TEXT NOT NULL,
                amount INTEGER NOT NULL,
                plan_name TEXT,
                account_name TEXT,
                description TEXT,
                created_at TEXT,
                FOREIGN KEY (reseller_id) REFERENCES resellers(id)
            )
        """)

        # جدول کارت‌های بانکی مقصد
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bank_cards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                card_number TEXT NOT NULL,
                card_holder TEXT NOT NULL,
                bank_name TEXT NOT NULL,
                daily_limit INTEGER DEFAULT 50000000,
                is_active BOOLEAN DEFAULT 1,
                created_at TEXT
            )
        """)

        # جدول سابقه و تاریخچه مصرف دوره‌های گذشته اشتراک‌ها هنگام تمدید
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS subscription_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subscription_id INTEGER,
                telegram_id INTEGER,
                hidify_uuid TEXT,
                account_name TEXT,
                plan_name TEXT,
                previous_usage_gb REAL,
                previous_limit_gb REAL,
                period_days INTEGER,
                renewal_type TEXT,
                renewed_at TEXT,
                reseller_id INTEGER
            )
        """)

        # جدول اسناد حسابداری و مدیریت مالی پیشرفته (درآمدها و مخارج)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS accounting_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL,
                category TEXT NOT NULL,
                title TEXT NOT NULL,
                amount INTEGER NOT NULL,
                source TEXT DEFAULT 'manual',
                ref_type TEXT,
                ref_id TEXT,
                description TEXT,
                date TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)

        # جدول مدیران پنل و سطوح دسترسی (RBAC)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS admin_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                display_name TEXT NOT NULL,
                telegram_id INTEGER,
                role TEXT NOT NULL DEFAULT 'super_admin',
                permissions TEXT NOT NULL DEFAULT '*',
                is_active BOOLEAN DEFAULT 1,
                created_at TEXT NOT NULL,
                last_login TEXT
            )
        """)

        # مایگریشن خودکار ستون‌های جدید
        try:
            cursor.execute("ALTER TABLE admin_users ADD COLUMN telegram_id INTEGER")
        except Exception:
            pass
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN referred_by INTEGER")
        except Exception:
            pass

        try:
            cursor.execute("ALTER TABLE users ADD COLUMN phone_number TEXT")
        except Exception:
            pass

        try:
            cursor.execute("ALTER TABLE users ADD COLUMN is_verified BOOLEAN DEFAULT 0")
        except Exception:
            pass

        try:
            cursor.execute("ALTER TABLE transactions ADD COLUMN is_renewal BOOLEAN DEFAULT 0")
        except Exception:
            pass

        try:
            cursor.execute("ALTER TABLE transactions ADD COLUMN renew_sub_id INTEGER")
        except Exception:
            pass

        try:
            cursor.execute("ALTER TABLE transactions ADD COLUMN discount_code TEXT")
        except Exception:
            pass

        try:
            cursor.execute("ALTER TABLE transactions ADD COLUMN rejection_reason TEXT")
        except Exception:
            pass

        try:
            cursor.execute("ALTER TABLE transactions ADD COLUMN receipt_photo_id TEXT")
        except Exception:
            pass

        try:
            cursor.execute("ALTER TABLE transactions ADD COLUMN receipt_image TEXT")
        except Exception:
            pass

        try:
            cursor.execute("ALTER TABLE transactions ADD COLUMN receipt_file_type TEXT")
        except Exception:
            pass

        try:
            cursor.execute("ALTER TABLE subscriptions ADD COLUMN reseller_id INTEGER")
        except Exception:
            pass

        # ستون‌های پروفایل و مشخصات فردی نمایندگان
        try:
            cursor.execute("ALTER TABLE resellers ADD COLUMN phone TEXT")
        except Exception:
            pass

        try:
            cursor.execute("ALTER TABLE resellers ADD COLUMN email TEXT")
        except Exception:
            pass

        try:
            cursor.execute("ALTER TABLE resellers ADD COLUMN bank_card TEXT")
        except Exception:
            pass

        try:
            cursor.execute("ALTER TABLE resellers ADD COLUMN notes TEXT")
        except Exception:
            pass

        conn.commit()
        conn.close()
        logger.info("Database initialized successfully")

        # بازیابی جامع اطلاعات در صورت خالی بودن دیتابیس پس از دیپلوی
        try:
            self.auto_restore_full()
        except Exception as e:
            logger.warning(f"Initial auto_restore_full check: {e}")

    def export_full_backup_json(self) -> dict:
        """پشتیبان‌گیری کامل از تمام جداول، کاربران، پلن‌ها، کارت‌ها، تنظیمات، تخفیف‌ها و نمایندگان در قالب یک فایل JSON پایدار"""
        conn = self.get_connection()
        cursor = conn.cursor()
        backup_data = {
            "version": "2.0",
            "timestamp": get_now_iso(),
            "tables": {}
        }
        
        tables = [
            "users", "subscriptions", "transactions", "resellers",
            "reseller_transactions", "bank_cards", "discount_codes",
            "settings", "support_tickets", "referrals", "subscription_history",
            "accounting_records", "admin_users"
        ]
        
        for table in tables:
            try:
                cursor.execute(f"SELECT * FROM {table}")
                rows = cursor.fetchall()
                backup_data["tables"][table] = [dict(r) for r in rows]
            except Exception as e:
                logger.warning(f"Could not export table {table}: {e}")
                backup_data["tables"][table] = []
        
        conn.close()
        
        # ذخیره در فایل‌های پشتیبان پایدار
        try:
            backup_dirs = [Path("data"), Path("/data"), DB_DIR]
            for bdir in backup_dirs:
                if bdir.exists():
                    fpath = bdir / "backup_full_latest.json"
                    with open(fpath, "w", encoding="utf-8") as f:
                        json.dump(backup_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Error writing backup_full_latest.json: {e}")
            
        return backup_data

    def auto_restore_full(self) -> dict:
        """بازیابی جامع اطلاعات تمام جداول (کاربران، کارت‌ها، پلن‌ها، نمایندگان، کد تخفیف و تنظیمات) پس از دیپلوی"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            # بررسی خالی بودن جداول کلیدی
            cursor.execute("SELECT COUNT(*) FROM users")
            users_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM bank_cards")
            cards_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM resellers")
            resellers_count = cursor.fetchone()[0]
            
            needs_restore = (users_count == 0 and cards_count == 0 and resellers_count == 0)
            if not needs_restore and users_count > 0:
                conn.close()
                logger.info(f"Database contains {users_count} users, full restore skipped.")
                return {"restored": False, "reason": "database_not_empty"}
            
            # جستجوی فایل JSON فول بک‌آپ
            candidate_files = [
                Path("data/backup_full_latest.json"),
                Path("/data/backup_full_latest.json"),
                Path("/data/backups/backup_full_latest.json"),
                DB_DIR / "backup_full_latest.json",
            ]
            
            found_file = None
            for cand in candidate_files:
                if cand.exists():
                    found_file = cand
                    break
            
            if not found_file:
                # تلاش برای بازیابی از فایل‌های .db
                conn.close()
                return self.auto_restore()
                
            logger.info(f"Restoring full database from {found_file}...")
            with open(found_file, "r", encoding="utf-8") as f:
                backup_data = json.load(f)
                
            tables_data = backup_data.get("tables", {})
            restored_stats = {}
            
            for table_name, rows in tables_data.items():
                if not rows:
                    continue
                try:
                    for row in rows:
                        columns = list(row.keys())
                        placeholders = ", ".join(["?"] * len(columns))
                        col_names = ", ".join(columns)
                        values = [row[c] for c in columns]
                        cursor.execute(f"INSERT OR REPLACE INTO {table_name} ({col_names}) VALUES ({placeholders})", values)
                    restored_stats[table_name] = len(rows)
                except Exception as ex:
                    logger.warning(f"Error restoring table {table_name}: {ex}")
            
            conn.commit()
            conn.close()
            logger.info(f"Full restore completed successfully: {restored_stats}")
            return {"restored": True, "stats": restored_stats, "source": str(found_file)}
        except Exception as e:
            logger.error(f"Error in auto_restore_full: {e}")
            return {"restored": False, "error": str(e)}

    def auto_restore(self):
        """بازیابی خودکار از آخرین پشتیبان اگر دیتابیس خالی باشد"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            # بررسی تعداد کاربران
            cursor.execute("SELECT COUNT(*) FROM users")
            count = cursor.fetchone()[0]
            conn.close()
            
            if count > 0:
                logger.info(f"Database has {count} users, no restore needed")
                return {"restored": False, "reason": "database_not_empty"}
            
            logger.info("Database is empty, looking for backups...")
            
            # جستجو برای فایل‌های پشتیبان
            backup_dirs = [
                Path("backups"),
                Path("/data/backups"),
                DB_DIR / "backups",
                Path(os.path.expanduser("~/.vpn-bot/data/backups")),
            ]
            
            all_backups = []
            for backup_dir in backup_dirs:
                if backup_dir.exists():
                    for f in backup_dir.glob("backup_*.db"):
                        all_backups.append(f)
            
            if not all_backups:
                logger.info("No backup files found")
                return {"restored": False, "reason": "no_backups_found"}
            
            # مرتب‌سازی بر اساس تاریخ (جدیدترین اول)
            all_backups.sort(key=lambda x: x.stat().st_mtime, reverse=True)
            latest_backup = all_backups[0]
            
            logger.info(f"Restoring from backup: {latest_backup.name}")
            
            # کپی پشتیبان به مسیر دیتابیس فعلی
            import shutil
            shutil.copy2(latest_backup, self.db_path)
            
            # بررسی نتیجه
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM users")
            restored_count = cursor.fetchone()[0]
            conn.close()
            
            logger.info(f"Restored {restored_count} users from {latest_backup.name}")
            return {
                "restored": True,
                "backup_file": latest_backup.name,
                "users_restored": restored_count,
            }
            
        except Exception as e:
            logger.error(f"Error in auto_restore: {e}")
            return {"restored": False, "error": str(e)}

    def sync_from_hidify(self, hidify_users: list) -> dict:
        """همگام‌سازی و بازیابی خودکار تمامی کاربران و اشتراک‌ها از پنل هیدیفای"""
        if not hidify_users or not isinstance(hidify_users, list):
            return {"success": False, "count": 0, "error": "لیست کاربران هیدیفای خالی یا نامعتبر است"}

        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        restored_users = 0
        restored_subs = 0

        try:
            for u in hidify_users:
                if not isinstance(u, dict):
                    continue
                
                uuid = u.get("uuid")
                if not uuid:
                    continue

                name = u.get("name") or ""
                comment = str(u.get("comment") or "").strip()
                usage_limit = float(u.get("usage_limit_GB") or 0)
                current_usage = float(u.get("current_usage_GB") or 0)
                package_days = int(u.get("package_days") or 30)
                is_active = u.get("is_active", True)
                enable = u.get("enable", True)
                start_date = u.get("start_date") or now
                status = "active" if (is_active and enable) else "expired"

                # استخراج telegram_id از کامنت یا نام کاربری
                telegram_id = 0
                if comment.isdigit() and len(comment) >= 5:
                    telegram_id = int(comment)
                elif name.startswith("tg_") and name.replace("tg_", "").isdigit():
                    telegram_id = int(name.replace("tg_", ""))

                # ۱. ثبت یا بروزرسانی در جدول users
                if telegram_id > 0:
                    cursor.execute("SELECT id FROM users WHERE telegram_id = ?", (telegram_id,))
                    existing_user = cursor.fetchone()
                    if not existing_user:
                        cursor.execute("""
                            INSERT INTO users (telegram_id, username, hidify_uuid, plan_id, data_limit, created_at, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                        """, (telegram_id, name, uuid, "custom", usage_limit, now, now))
                        restored_users += 1
                    else:
                        cursor.execute("""
                            UPDATE users SET
                                username = COALESCE(?, username),
                                hidify_uuid = COALESCE(?, hidify_uuid),
                                data_limit = ?,
                                updated_at = ?
                            WHERE telegram_id = ?
                        """, (name, uuid, usage_limit, now, telegram_id))

                    # ایجاد کیف پول در صورت عدم وجود
                    cursor.execute("SELECT id FROM wallet WHERE telegram_id = ?", (telegram_id,))
                    if not cursor.fetchone():
                        cursor.execute("""
                            INSERT INTO wallet (telegram_id, balance, created_at, updated_at)
                            VALUES (?, 0, ?, ?)
                        """, (telegram_id, now, now))

                # ۲. ثبت یا بروزرسانی در جدول subscriptions
                cursor.execute("SELECT id FROM subscriptions WHERE hidify_uuid = ?", (uuid,))
                existing_sub = cursor.fetchone()

                plan_name = f"{usage_limit} گیگ {package_days} روزه" if usage_limit > 0 else f"{package_days} روزه"
                if "test" in name.lower() or (usage_limit > 0 and usage_limit <= 0.5):
                    plan_id = "test"
                    plan_name = "اشتراک تست"
                else:
                    plan_id = "custom"

                if existing_sub:
                    # بروزرسانی مصرف، حجم و وضعیت
                    cursor.execute("""
                        UPDATE subscriptions SET
                            data_used = ?,
                            data_limit = ?,
                            status = ?,
                            account_name = COALESCE(?, account_name),
                            updated_at = ?
                        WHERE hidify_uuid = ?
                    """, (current_usage, usage_limit, status, name, now, uuid))
                else:
                    # درج اشتراک جدید بازیابی شده
                    cursor.execute("""
                        INSERT INTO subscriptions (
                            telegram_id, hidify_uuid, plan_id, plan_name, account_name,
                            account_comment, data_limit, data_used, duration, start_date,
                            status, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        telegram_id, uuid, plan_id, plan_name, name,
                        comment, usage_limit, current_usage, package_days, start_date,
                        status, now, now
                    ))
                    restored_subs += 1

            conn.commit()
            logger.info(f"Hiddify sync complete: {restored_users} users, {restored_subs} subscriptions imported/updated.")
            return {
                "success": True,
                "restored_users": restored_users,
                "restored_subs": restored_subs,
                "total_hiddify": len(hidify_users)
            }
        except Exception as e:
            logger.error(f"Error syncing from Hiddify: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    # ═══════════════════════════════════════════════════════════════
    # مدیریت مشتریان
    # ═══════════════════════════════════════════════════════════════

    def save_user(self, telegram_id, username=None, hidify_uuid=None, plan_id=None, data_limit=None, expire_at=None):
        """ذخیره یا بروزرسانی اطلاعات کاربر"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()

        try:
            # بررسی وجود کاربر
            cursor.execute("SELECT id FROM users WHERE telegram_id = ?", (telegram_id,))
            existing = cursor.fetchone()

            if existing:
                # بروزرسانی با حفظ فیلدهای قبلی در صورت None بودن
                cursor.execute("""
                    UPDATE users SET
                        username = COALESCE(?, username),
                        hidify_uuid = COALESCE(?, hidify_uuid),
                        plan_id = COALESCE(?, plan_id),
                        data_limit = COALESCE(?, data_limit),
                        expire_at = COALESCE(?, expire_at),
                        updated_at = ?
                    WHERE telegram_id = ?
                """, (username, hidify_uuid, plan_id, data_limit, expire_at, now, telegram_id))
            else:
                # درج جدید
                cursor.execute("""
                    INSERT INTO users (telegram_id, username, hidify_uuid, plan_id, data_limit, expire_at, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (telegram_id, username or f"user_{telegram_id}", hidify_uuid, plan_id, data_limit or 0, expire_at, now, now))

            conn.commit()
            logger.info(f"User {telegram_id} saved successfully")
            return {"success": True}
        except Exception as e:
            logger.error(f"Error saving user {telegram_id}: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def get_user(self, telegram_id):
        """دریافت اطلاعات کاربر"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None
        except Exception as e:
            logger.error(f"Error getting user {telegram_id}: {e}")
            return None
        finally:
            conn.close()

    def set_user_phone(self, telegram_id: int, phone_number: str) -> bool:
        """ثبت و تایید شماره تماس تلگرام کاربر"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        clean_phone = str(phone_number).strip().replace(" ", "").replace("-", "")
        if not clean_phone.startswith("+") and clean_phone.startswith("98"):
            clean_phone = "+" + clean_phone
        elif not clean_phone.startswith("+") and not clean_phone.startswith("0"):
            clean_phone = "+" + clean_phone

        try:
            cursor.execute("SELECT id FROM users WHERE telegram_id = ?", (telegram_id,))
            if cursor.fetchone():
                cursor.execute("""
                    UPDATE users SET phone_number = ?, is_verified = 1, updated_at = ? WHERE telegram_id = ?
                """, (clean_phone, now, telegram_id))
            else:
                cursor.execute("""
                    INSERT INTO users (telegram_id, username, phone_number, is_verified, created_at, updated_at)
                    VALUES (?, ?, ?, 1, ?, ?)
                """, (telegram_id, f"user_{telegram_id}", clean_phone, now, now))
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error setting user phone {telegram_id}: {e}")
            return False
        finally:
            conn.close()

    def is_user_verified(self, telegram_id: int) -> bool:
        """بررسی احراز هویت شماره تلفن کاربر"""
        user = self.get_user(telegram_id)
        if not user:
            return False
        phone = user.get("phone_number")
        return bool(phone and str(phone).strip())

    def get_all_users(self):
        """دریافت تمام کاربران"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("SELECT * FROM users ORDER BY created_at DESC")
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error getting all users: {e}")
            return []
        finally:
            conn.close()

    def delete_user(self, telegram_id):
        """حذف کاربر"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("DELETE FROM users WHERE telegram_id = ?", (telegram_id,))
            conn.commit()
            logger.info(f"User {telegram_id} deleted")
            return {"success": True}
        except Exception as e:
            logger.error(f"Error deleting user {telegram_id}: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    # ═══════════════════════════════════════════════════════════════
    # مدیریت اشتراک‌ها
    # ═══════════════════════════════════════════════════════════════

    def save_subscription(self, telegram_id, hidify_uuid, plan_id, plan_name, data_limit, duration, data_used=0, status="active", account_name=None, account_comment=None):
        """ذخیره اشتراک جدید"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        expire_date = (get_now_naive() + timedelta(days=duration)).isoformat()

        try:
            cursor.execute("""
                INSERT INTO subscriptions
                (telegram_id, hidify_uuid, plan_id, plan_name, account_name, account_comment, data_limit, data_used, duration, start_date, expire_date, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (telegram_id, hidify_uuid, plan_id, plan_name, account_name, account_comment, data_limit, data_used, duration, now, expire_date, status, now, now))
            conn.commit()
            subscription_id = cursor.lastrowid
            logger.info(f"Subscription {subscription_id} saved for user {telegram_id}")
            return {"success": True, "subscription_id": subscription_id}
        except Exception as e:
            logger.error(f"Error saving subscription: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def get_user_subscriptions(self, telegram_id, status=None):
        """دریافت اشتراک‌های کاربر"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            if status:
                cursor.execute("""
                    SELECT * FROM subscriptions
                    WHERE telegram_id = ? AND status = ?
                    ORDER BY created_at DESC
                """, (telegram_id, status))
            else:
                cursor.execute("""
                    SELECT * FROM subscriptions
                    WHERE telegram_id = ?
                    ORDER BY created_at DESC
                """, (telegram_id,))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error getting subscriptions for user {telegram_id}: {e}")
            return []
        finally:
            conn.close()

    def get_active_subscription(self, telegram_id):
        """دریافت اشتراک فعال کاربر"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT * FROM subscriptions
                WHERE telegram_id = ? AND status = 'active'
                ORDER BY created_at DESC
                LIMIT 1
            """, (telegram_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting active subscription for user {telegram_id}: {e}")
            return None
        finally:
            conn.close()

    def update_subscription(self, subscription_id, **kwargs):
        """بروزرسانی اشتراک"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()

        try:
            updates = []
            values = []
            for key, value in kwargs.items():
                updates.append(f"{key} = ?")
                values.append(value)
            updates.append("updated_at = ?")
            values.append(now)
            values.append(subscription_id)

            query = f"UPDATE subscriptions SET {', '.join(updates)} WHERE id = ?"
            cursor.execute(query, values)
            conn.commit()
            logger.info(f"Subscription {subscription_id} updated")
            return {"success": True}
        except Exception as e:
            logger.error(f"Error updating subscription {subscription_id}: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def cancel_subscription(self, subscription_id):
        """لغو اشتراک"""
        return self.update_subscription(subscription_id, status="cancelled")

    def update_subscription_by_uuid(self, hidify_uuid, **kwargs):
        """بروزرسانی اشتراک بر اساس hidify_uuid"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()

        try:
            updates = []
            values = []
            for key, value in kwargs.items():
                updates.append(f"{key} = ?")
                values.append(value)
            updates.append("updated_at = ?")
            values.append(now)
            values.append(hidify_uuid)

            query = f"UPDATE subscriptions SET {', '.join(updates)} WHERE hidify_uuid = ?"
            cursor.execute(query, values)
            conn.commit()
            return {"success": True}
        except Exception as e:
            logger.error(f"Error updating subscription by uuid {hidify_uuid}: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    # ═══════════════════════════════════════════════════════════════
    # مدیریت تراکنش‌ها
    # ═══════════════════════════════════════════════════════════════

    def save_transaction(self, order_id, user_id, username, plan_name, amount, gateway, tracking_code, status="pending", account_name=None, account_comment=None, is_renewal=0, renew_sub_id=None, discount_code=None, receipt_image=None, receipt_file_type=None):
        """ذخیره تراکنش"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()

        try:
            cursor.execute("""
                INSERT OR REPLACE INTO transactions
                (order_id, user_id, username, plan_name, amount, gateway, tracking_code, account_name, account_comment, status, is_renewal, renew_sub_id, discount_code, receipt_image, receipt_photo_id, receipt_file_type, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (order_id, user_id, username, plan_name, amount, gateway, tracking_code, account_name, account_comment, status, 1 if is_renewal else 0, renew_sub_id, discount_code, receipt_image, receipt_image, receipt_file_type, now, now))
            conn.commit()
            logger.info(f"Transaction {order_id} saved (is_renewal={is_renewal})")
            
            # ذخیره بک‌آپ فوری
            try:
                self.export_full_backup_json()
            except Exception:
                pass

            return {"success": True}
        except Exception as e:
            logger.error(f"Error saving transaction {order_id}: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def update_transaction(self, order_id, status, ref_id=None):
        """بروزرسانی وضعیت تراکنش"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()

        try:
            if ref_id:
                cursor.execute("""
                    UPDATE transactions SET status = ?, ref_id = ?, updated_at = ?
                    WHERE order_id = ?
                """, (status, ref_id, now, order_id))
            else:
                cursor.execute("""
                    UPDATE transactions SET status = ?, updated_at = ?
                    WHERE order_id = ?
                """, (status, now, order_id))
            conn.commit()
            logger.info(f"Transaction {order_id} updated to {status}")
            return {"success": True}
        except Exception as e:
            logger.error(f"Error updating transaction {order_id}: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def get_user_transactions(self, user_id):
        """دریافت تراکنش‌های کاربر"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT * FROM transactions WHERE user_id = ?
                ORDER BY created_at DESC
            """, (user_id,))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error getting transactions for user {user_id}: {e}")
            return []
        finally:
            conn.close()

    def get_transaction_by_order_id(self, order_id):
        """دریافت تراکنش بر اساس order_id"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT * FROM transactions WHERE order_id = ?
            """, (order_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting transaction {order_id}: {e}")
            return None
        finally:
            conn.close()

    def get_pending_transactions(self):
        """دریافت تراکنش‌های در انتظار"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT * FROM transactions WHERE status = 'pending'
                ORDER BY created_at DESC
            """)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error getting pending transactions: {e}")
            return []
        finally:
            conn.close()

    # ═══════════════════════════════════════════════════════════════
    # مدیریت تنظیمات
    # ═══════════════════════════════════════════════════════════════

    def save_setting(self, key, value):
        """ذخیره تنظیم"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()

        try:
            # تبدیل dict/list به JSON
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False)

            cursor.execute("""
                INSERT OR REPLACE INTO settings (key, value, updated_at)
                VALUES (?, ?, ?)
            """, (key, str(value), now))
            conn.commit()
            logger.info(f"Setting {key} saved")
            try:
                self.export_full_backup_json()
            except Exception:
                pass
            return {"success": True}
        except Exception as e:
            logger.error(f"Error saving setting {key}: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def set_setting(self, key, value):
        """نام مستعار برای save_setting"""
        return self.save_setting(key, value)

    def get_setting(self, key, default=None):
        """دریافت تنظیم"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
            row = cursor.fetchone()
            if row:
                value = row["value"]
                # تلاش برای تبدیل از JSON
                try:
                    return json.loads(value)
                except:
                    return value
            return default
        except Exception as e:
            logger.error(f"Error getting setting {key}: {e}")
            return default
        finally:
            conn.close()

    def get_all_settings(self):
        """دریافت تمام تنظیمات"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("SELECT * FROM settings")
            rows = cursor.fetchall()
            result = {}
            for row in rows:
                try:
                    result[row["key"]] = json.loads(row["value"])
                except:
                    result[row["key"]] = row["value"]
            return result
        except Exception as e:
            logger.error(f"Error getting all settings: {e}")
            return {}
        finally:
            conn.close()

    # ═══════════════════════════════════════════════════════════════
    # مدیریت پشتیبان‌ها
    # ═══════════════════════════════════════════════════════════════

    def save_backup_record(self, backup_file, backup_size):
        """ذخیره رکورد پشتیبان"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()

        try:
            cursor.execute("""
                INSERT INTO backups (backup_file, backup_size, created_at, uploaded)
                VALUES (?, ?, ?, 0)
            """, (backup_file, backup_size, now))
            conn.commit()
            return {"success": True, "id": cursor.lastrowid}
        except Exception as e:
            logger.error(f"Error saving backup record: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def mark_backup_uploaded(self, backup_id):
        """علامت‌گذاری پشتیبان به عنوان آپلود شده"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("UPDATE backups SET uploaded = 1 WHERE id = ?", (backup_id,))
            conn.commit()
            return {"success": True}
        except Exception as e:
            logger.error(f"Error marking backup as uploaded: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def get_backups(self, limit=10):
        """دریافت لیست پشتیبان‌ها"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT * FROM backups ORDER BY created_at DESC LIMIT ?
            """, (limit,))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error getting backups: {e}")
            return []
        finally:
            conn.close()

    # ═══════════════════════════════════════════════════════════════
    # مدیریت کیف پول
    # ═══════════════════════════════════════════════════════════════

    def get_wallet(self, telegram_id):
        """دریافت موجودی کیف پول"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT * FROM wallet WHERE telegram_id = ?", (telegram_id,))
            row = cursor.fetchone()
            if row:
                return dict(row)
            # ایجاد کیف پول جدید
            now = get_now_iso()
            cursor.execute("INSERT INTO wallet (telegram_id, balance, created_at, updated_at) VALUES (?, 0, ?, ?)",
                          (telegram_id, now, now))
            conn.commit()
            return {"telegram_id": telegram_id, "balance": 0}
        except Exception as e:
            logger.error(f"Error getting wallet for {telegram_id}: {e}")
            return {"telegram_id": telegram_id, "balance": 0}
        finally:
            conn.close()

    def update_wallet(self, telegram_id, amount):
        """بروزرسانی موجودی کیف پول"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("""
                INSERT INTO wallet (telegram_id, balance, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(telegram_id) DO UPDATE SET balance = balance + ?, updated_at = ?
            """, (telegram_id, amount, now, now, amount, now))
            conn.commit()
            # دریافت موجودی جدید
            cursor.execute("SELECT balance FROM wallet WHERE telegram_id = ?", (telegram_id,))
            row = cursor.fetchone()
            return {"success": True, "balance": row["balance"] if row else 0}
        except Exception as e:
            logger.error(f"Error updating wallet for {telegram_id}: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def get_all_wallets(self):
        """دریافت تمام کیف پول‌ها"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT * FROM wallet ORDER BY balance DESC")
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting all wallets: {e}")
            return []
        finally:
            conn.close()

    # ═══════════════════════════════════════════════════════════════
    # مدیریت کدهای تخفیف
    # ═══════════════════════════════════════════════════════════════

    def create_discount_code(self, code, discount_percent=0, discount_amount=0, max_uses=0, valid_until=None):
        """ایجاد کد تخفیف جدید"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("""
                INSERT INTO discount_codes (code, discount_percent, discount_amount, max_uses, valid_until, is_active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 1, ?, ?)
            """, (code.upper(), discount_percent, discount_amount, max_uses, valid_until, now, now))
            conn.commit()
            return {"success": True, "id": cursor.lastrowid}
        except Exception as e:
            logger.error(f"Error creating discount code: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def use_discount_code(self, code):
        """استفاده از کد تخفیف"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("SELECT * FROM discount_codes WHERE code = ? AND is_active = 1", (code.upper(),))
            row = cursor.fetchone()
            if not row:
                return {"success": False, "error": "کد تخفیف یافت نشد"}
            
            discount = dict(row)
            
            # بررسی تاریخ اعتبار
            if discount["valid_until"]:
                valid_until = datetime.fromisoformat(discount["valid_until"])
                if get_now_naive() > valid_until:
                    return {"success": False, "error": "کد تخفیف منقضی شده"}
            
            # بررسی تعداد استفاده
            if discount["max_uses"] > 0 and discount["used_count"] >= discount["max_uses"]:
                return {"success": False, "error": "کد تخفیف به حداکثر استفاده رسیده"}
            
            # بروزرسانی تعداد استفاده
            cursor.execute("UPDATE discount_codes SET used_count = used_count + 1, updated_at = ? WHERE code = ?", (now, code.upper()))
            conn.commit()
            
            return {
                "success": True,
                "discount_percent": discount["discount_percent"],
                "discount_amount": discount["discount_amount"]
            }
        except Exception as e:
            logger.error(f"Error using discount code: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def get_all_discount_codes(self):
        """دریافت تمام کدهای تخفیف"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT * FROM discount_codes ORDER BY created_at DESC")
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting discount codes: {e}")
            return []
        finally:
            conn.close()

    def delete_discount_code(self, code):
        """حذف کد تخفیف"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("DELETE FROM discount_codes WHERE code = ?", (code.upper(),))
            conn.commit()
            return {"success": True}
        except Exception as e:
            logger.error(f"Error deleting discount code: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    # ═══════════════════════════════════════════════════════════════
    # مدیریت بلاک لیست
    # ═══════════════════════════════════════════════════════════════

    def block_user(self, telegram_id, reason=None, blocked_by=None):
        """بلاک کردن کاربر"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("""
                INSERT OR REPLACE INTO blocked_users (telegram_id, reason, blocked_by, created_at)
                VALUES (?, ?, ?, ?)
            """, (telegram_id, reason, blocked_by, now))
            conn.commit()
            return {"success": True}
        except Exception as e:
            logger.error(f"Error blocking user {telegram_id}: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def unblock_user(self, telegram_id):
        """آنبلاک کردن کاربر"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("DELETE FROM blocked_users WHERE telegram_id = ?", (telegram_id,))
            conn.commit()
            return {"success": True}
        except Exception as e:
            logger.error(f"Error unblocking user {telegram_id}: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def is_blocked(self, telegram_id):
        """بررسی بلاک بودن کاربر"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT * FROM blocked_users WHERE telegram_id = ?", (telegram_id,))
            row = cursor.fetchone()
            return row is not None
        except Exception as e:
            logger.error(f"Error checking block status: {e}")
            return False
        finally:
            conn.close()

    def get_blocked_users(self):
        """دریافت لیست کاربران بلاک شده"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT * FROM blocked_users ORDER BY created_at DESC")
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting blocked users: {e}")
            return []
        finally:
            conn.close()

    # ═══════════════════════════════════════════════════════════════
    # مدیریت تیکت‌های پشتیبانی
    # ═══════════════════════════════════════════════════════════════

    def create_ticket(self, telegram_id, subject, message):
        """ایجاد تیکت پشتیبانی جدید"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("""
                INSERT INTO support_tickets (telegram_id, subject, message, status, created_at, updated_at)
                VALUES (?, ?, ?, 'open', ?, ?)
            """, (telegram_id, subject, message, now, now))
            conn.commit()
            return {"success": True, "ticket_id": cursor.lastrowid}
        except Exception as e:
            logger.error(f"Error creating ticket: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def reply_ticket(self, ticket_id, admin_reply):
        """پاسخ ادمین به تیکت"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("""
                UPDATE support_tickets SET admin_reply = ?, status = 'replied', updated_at = ?
                WHERE id = ?
            """, (admin_reply, now, ticket_id))
            conn.commit()
            return {"success": True}
        except Exception as e:
            logger.error(f"Error replying to ticket: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def close_ticket(self, ticket_id):
        """بستن تیکت"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("UPDATE support_tickets SET status = 'closed', updated_at = ? WHERE id = ?", (now, ticket_id))
            conn.commit()
            return {"success": True}
        except Exception as e:
            logger.error(f"Error closing ticket: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def get_user_tickets(self, telegram_id, status=None):
        """دریافت تیکت‌های کاربر"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            if status:
                cursor.execute("SELECT * FROM support_tickets WHERE telegram_id = ? AND status = ? ORDER BY created_at DESC", (telegram_id, status))
            else:
                cursor.execute("SELECT * FROM support_tickets WHERE telegram_id = ? ORDER BY created_at DESC", (telegram_id,))
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting tickets: {e}")
            return []
        finally:
            conn.close()

    def get_ticket(self, ticket_id):
        """دریافت یک تیکت بر اساس شناسه"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT * FROM support_tickets WHERE id = ?", (ticket_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting ticket {ticket_id}: {e}")
            return None
        finally:
            conn.close()

    # ═══════════════════════════════════════════════════════════════
    # مدیریت رفرال و زیرمجموعه‌گیری
    # ═══════════════════════════════════════════════════════════════

    def add_referral(self, referrer_id, referred_id):
        """ثبت کاربر معرفی شده"""
        if referrer_id == referred_id:
            return {"success": False, "error": "self_referral"}
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            # ثبت در جدول referrals
            cursor.execute("""
                INSERT OR IGNORE INTO referrals (referrer_id, referred_id, reward_amount, status, created_at, updated_at)
                VALUES (?, ?, 0, 'pending', ?, ?)
            """, (referrer_id, referred_id, now, now))
            # ثبت معرف در جدول users
            cursor.execute("""
                UPDATE users SET referred_by = ?, updated_at = ?
                WHERE telegram_id = ? AND referred_by IS NULL
            """, (referrer_id, now, referred_id))
            conn.commit()
            return {"success": True}
        except Exception as e:
            logger.error(f"Error adding referral ({referrer_id} -> {referred_id}): {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def get_referral_stats(self, referrer_id):
        """دریافت آمار رفرال کاربر"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT COUNT(*) as total FROM referrals WHERE referrer_id = ?", (referrer_id,))
            total_invites = cursor.fetchone()["total"]

            cursor.execute("SELECT COUNT(*) as rewarded FROM referrals WHERE referrer_id = ? AND status = 'rewarded'", (referrer_id,))
            rewarded_invites = cursor.fetchone()["rewarded"]

            cursor.execute("SELECT COALESCE(SUM(reward_amount), 0) as total_reward FROM referrals WHERE referrer_id = ? AND status = 'rewarded'", (referrer_id,))
            total_reward = cursor.fetchone()["total_reward"]

            return {
                "total_invites": total_invites,
                "rewarded_invites": rewarded_invites,
                "total_reward": total_reward,
            }
        except Exception as e:
            logger.error(f"Error getting referral stats for {referrer_id}: {e}")
            return {"total_invites": 0, "rewarded_invites": 0, "total_reward": 0}
        finally:
            conn.close()

    def complete_referral(self, referred_id, reward_amount=10000):
        """تکمیل پاداش رفرال پس از خرید کاربر"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("SELECT * FROM referrals WHERE referred_id = ? AND status = 'pending'", (referred_id,))
            ref = cursor.fetchone()
            if not ref:
                return {"success": False, "reason": "no_pending_referral"}
            
            referrer_id = ref["referrer_id"]
            cursor.execute("""
                UPDATE referrals SET status = 'rewarded', reward_amount = ?, updated_at = ?
                WHERE referred_id = ?
            """, (reward_amount, now, referred_id))
            
            # افزودن پاداش به کیف پول معرف
            cursor.execute("""
                INSERT INTO wallet (telegram_id, balance, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(telegram_id) DO UPDATE SET balance = balance + ?, updated_at = ?
            """, (referrer_id, reward_amount, now, now, reward_amount, now))
            
            conn.commit()
            return {"success": True, "referrer_id": referrer_id, "reward_amount": reward_amount}
        except Exception as e:
            logger.error(f"Error completing referral for {referred_id}: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()


    # ═══════════════════════════════════════════════════════════════
    # مدیریت اعلان‌ها
    # ═══════════════════════════════════════════════════════════════

    def save_notification(self, telegram_id, notification_type, subscription_id=None):
        """ذخیره اعلان ارسال شده"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("""
                INSERT INTO sent_notifications (telegram_id, notification_type, subscription_id, sent_at)
                VALUES (?, ?, ?, ?)
            """, (telegram_id, notification_type, subscription_id, now))
            conn.commit()
            return {"success": True}
        except Exception as e:
            logger.error(f"Error saving notification: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def was_notification_sent(self, telegram_id, notification_type, subscription_id=None):
        """بررسی ارسال شدن اعلان"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            if subscription_id:
                cursor.execute("""SELECT * FROM sent_notifications 
                    WHERE telegram_id = ? AND notification_type = ? AND subscription_id = ?""", 
                    (telegram_id, notification_type, subscription_id))
            else:
                cursor.execute("""SELECT * FROM sent_notifications 
                    WHERE telegram_id = ? AND notification_type = ?""", 
                    (telegram_id, notification_type))
            return cursor.fetchone() is not None
        except Exception as e:
            logger.error(f"Error checking notification: {e}")
            return False
        finally:
            conn.close()

    # ═══════════════════════════════════════════════════════════════
    # آمار پیشرفته
    # ═══════════════════════════════════════════════════════════════

    def get_advanced_stats(self):
        """دریافت آمار پیشرفته"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            stats = {}
            
            # آمار کلی
            cursor.execute("SELECT COUNT(*) as count FROM users")
            stats["total_users"] = cursor.fetchone()["count"]
            
            cursor.execute("SELECT COUNT(*) as count FROM subscriptions WHERE status = 'active'")
            stats["active_subscriptions"] = cursor.fetchone()["count"]
            
            cursor.execute("SELECT COUNT(*) as count FROM subscriptions WHERE status = 'expired'")
            stats["expired_subscriptions"] = cursor.fetchone()["count"]
            
            # درآمد ماهانه
            cursor.execute("""SELECT COALESCE(SUM(amount), 0) as total FROM transactions 
                WHERE status = 'completed' AND created_at >= date('now', '-30 days')""")
            stats["monthly_revenue"] = cursor.fetchone()["total"]
            
            # درآمد امروز
            cursor.execute("""SELECT COALESCE(SUM(amount), 0) as total FROM transactions 
                WHERE status = 'completed' AND date(created_at) = date('now')""")
            stats["today_revenue"] = cursor.fetchone()["total"]
            
            # کاربران جدید امروز
            cursor.execute("SELECT COUNT(*) as count FROM users WHERE date(created_at) = date('now')")
            stats["today_new_users"] = cursor.fetchone()["count"]
            
            # تیکت‌های باز
            cursor.execute("SELECT COUNT(*) as count FROM support_tickets WHERE status = 'open'")
            stats["open_tickets"] = cursor.fetchone()["count"]
            
            # کاربران بلاک شده
            cursor.execute("SELECT COUNT(*) as count FROM blocked_users")
            stats["blocked_users"] = cursor.fetchone()["count"]
            
            # محبوب‌ترین پلن
            cursor.execute("""SELECT plan_name, COUNT(*) as count FROM subscriptions 
                GROUP BY plan_name ORDER BY count DESC LIMIT 5""")
            stats["popular_plans"] = [dict(row) for row in cursor.fetchall()]
            
            return stats
        except Exception as e:
            logger.error(f"Error getting advanced stats: {e}")
            return {}
        finally:
            conn.close()

    # ═══════════════════════════════════════════════════════════════
    # آمار
    # ═══════════════════════════════════════════════════════════════

    def get_stats(self):
        """دریافت آمار دقیق دیتابیس"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            stats = {}

            # تعداد کاربران
            cursor.execute("SELECT COUNT(*) as count FROM users")
            stats["total_users"] = cursor.fetchone()["count"]

            # تعداد تراکنش‌ها
            cursor.execute("SELECT COUNT(*) as count FROM transactions")
            stats["total_transactions"] = cursor.fetchone()["count"]

            # تراکنش‌های در انتظار
            cursor.execute("SELECT COUNT(*) as count FROM transactions WHERE status = 'pending'")
            stats["pending_transactions"] = cursor.fetchone()["count"]

            # تراکنش‌های تایید شده
            cursor.execute("SELECT COUNT(*) as count FROM transactions WHERE status IN ('approved', 'completed')")
            stats["completed_transactions"] = cursor.fetchone()["count"]

            # تراکنش‌های رد شده
            cursor.execute("SELECT COUNT(*) as count FROM transactions WHERE status = 'rejected'")
            stats["rejected_transactions"] = cursor.fetchone()["count"]

            # درآمد کل
            cursor.execute("SELECT COALESCE(SUM(amount), 0) as total FROM transactions WHERE status IN ('approved', 'completed')")
            stats["total_revenue"] = cursor.fetchone()["total"]

            # تعداد پشتیبان‌ها
            cursor.execute("SELECT COUNT(*) as count FROM backups")
            stats["total_backups"] = cursor.fetchone()["count"]

            # تعداد اشتراک‌ها
            cursor.execute("SELECT COUNT(*) as count FROM subscriptions")
            stats["total_subscriptions"] = cursor.fetchone()["count"]

            cursor.execute("SELECT COUNT(*) as count FROM subscriptions WHERE status = 'active'")
            stats["active_subscriptions"] = cursor.fetchone()["count"]

            # کارت‌های فعال بانکی
            cursor.execute("SELECT COUNT(*) as count FROM bank_cards WHERE is_active = 1")
            stats["active_cards"] = cursor.fetchone()["count"]

            return stats
        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            return {}
        finally:
            conn.close()

    def save_subscription_history(self, subscription_id: int, telegram_id: int, hidify_uuid: str,
                                account_name: str, plan_name: str, previous_usage_gb: float,
                                previous_limit_gb: float, period_days: int, renewal_type: str = "replace",
                                reseller_id: int = None) -> bool:
        """ثبت تاریخچه و میزان مصرف دوره قبلی هنگام تمدید اشتراک"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO subscription_history (
                    subscription_id, telegram_id, hidify_uuid, account_name, plan_name,
                    previous_usage_gb, previous_limit_gb, period_days, renewal_type,
                    renewed_at, reseller_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                subscription_id, telegram_id, hidify_uuid, account_name, plan_name,
                float(previous_usage_gb or 0), float(previous_limit_gb or 0),
                int(period_days or 30), renewal_type, get_now_iso(), reseller_id
            ))
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error saving subscription history: {e}")
            return False
        finally:
            conn.close()

    def get_subscription_history(self, subscription_id: int = None, telegram_id: int = None,
                                reseller_id: int = None, limit: int = 50) -> list:
        """دریافت سوابق مصرف دوره‌های قبلی اشتراک‌ها"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            query = "SELECT * FROM subscription_history WHERE 1=1"
            params = []
            if subscription_id:
                query += " AND subscription_id = ?"
                params.append(subscription_id)
            if telegram_id:
                query += " AND telegram_id = ?"
                params.append(telegram_id)
            if reseller_id:
                query += " AND reseller_id = ?"
                params.append(reseller_id)
            query += " ORDER BY renewed_at DESC LIMIT ?"
            params.append(limit)

            cursor.execute(query, params)
            return [dict(r) for r in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting subscription history: {e}")
            return []
        finally:
            conn.close()

    def get_advanced_analytics(self, reseller_id: int = None) -> dict:
        """گزارشات و تحلیل‌های پیشرفته هوش مالی و عملکردی برای مدیر و نمایندگان"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        res = {}
        
        try:
            # ۱. محبوب‌ترین پلن‌ها (پرفروش‌ترین)
            if reseller_id:
                cursor.execute("""
                    SELECT plan_name, COUNT(*) as count, SUM(amount) as revenue 
                    FROM reseller_transactions 
                    WHERE reseller_id = ? AND type = 'purchase' AND plan_name IS NOT NULL
                    GROUP BY plan_name 
                    ORDER BY count DESC LIMIT 8
                """, (reseller_id,))
            else:
                cursor.execute("""
                    SELECT plan_name, COUNT(*) as count, SUM(amount) as revenue 
                    FROM transactions 
                    WHERE status IN ('approved', 'completed') AND plan_name IS NOT NULL
                    GROUP BY plan_name 
                    ORDER BY count DESC LIMIT 8
                """)
            res["popular_plans"] = [dict(r) for r in cursor.fetchall()]

            # ۲. برترین کاربران ماه جاری (Top users of the month)
            current_month = now[:7]
            if reseller_id:
                cursor.execute("""
                    SELECT account_name as username, 0 as telegram_id, SUM(amount) as total_spent, COUNT(*) as tx_count
                    FROM reseller_transactions
                    WHERE reseller_id = ? AND type = 'purchase' AND created_at LIKE ?
                    GROUP BY account_name
                    ORDER BY total_spent DESC LIMIT 5
                """, (reseller_id, f"{current_month}%"))
            else:
                cursor.execute("""
                    SELECT user_id as telegram_id, username, SUM(amount) as total_spent, COUNT(*) as tx_count
                    FROM transactions
                    WHERE status IN ('approved', 'completed') AND created_at LIKE ?
                    GROUP BY user_id
                    ORDER BY total_spent DESC LIMIT 5
                """, (f"{current_month}%",))
            res["top_users_month"] = [dict(r) for r in cursor.fetchall()]

            # ۳. برترین کاربران سال جاری (Top users of the year)
            current_year = now[:4]
            if reseller_id:
                cursor.execute("""
                    SELECT account_name as username, 0 as telegram_id, SUM(amount) as total_spent, COUNT(*) as tx_count
                    FROM reseller_transactions
                    WHERE reseller_id = ? AND type = 'purchase' AND created_at LIKE ?
                    GROUP BY account_name
                    ORDER BY total_spent DESC LIMIT 5
                """, (reseller_id, f"{current_year}%"))
            else:
                cursor.execute("""
                    SELECT user_id as telegram_id, username, SUM(amount) as total_spent, COUNT(*) as tx_count
                    FROM transactions
                    WHERE status IN ('approved', 'completed') AND created_at LIKE ?
                    GROUP BY user_id
                    ORDER BY total_spent DESC LIMIT 5
                """, (f"{current_year}%",))
            res["top_users_year"] = [dict(r) for r in cursor.fetchall()]

            # ۴. فعال‌ترین کاربران از نظر مصرف گیگابایت (Most active users)
            if reseller_id:
                cursor.execute("""
                    SELECT account_name, plan_name, data_used, data_limit, duration, status, created_at
                    FROM subscriptions
                    WHERE reseller_id = ?
                    ORDER BY data_used DESC LIMIT 6
                """, (reseller_id,))
            else:
                cursor.execute("""
                    SELECT s.telegram_id, s.account_name, s.plan_name, s.data_used, s.data_limit, s.duration, s.status, s.created_at, u.username
                    FROM subscriptions s
                    LEFT JOIN users u ON s.telegram_id = u.telegram_id
                    ORDER BY s.data_used DESC LIMIT 6
                """)
            res["most_active_users"] = [dict(r) for r in cursor.fetchall()]

            # ۵. گزارش مصرف دوره‌های گذشته (Previous periods usage history)
            if reseller_id:
                cursor.execute("""
                    SELECT * FROM subscription_history
                    WHERE reseller_id = ?
                    ORDER BY renewed_at DESC LIMIT 15
                """, (reseller_id,))
            else:
                cursor.execute("""
                    SELECT * FROM subscription_history
                    ORDER BY renewed_at DESC LIMIT 15
                """)
            res["usage_history"] = [dict(r) for r in cursor.fetchall()]

            # ۶. آخرین تمدیدها و خریدها به همراه تاریخ عضویت و آخرین بروزرسانی
            if reseller_id:
                cursor.execute("""
                    SELECT s.*, r.name as reseller_name
                    FROM subscriptions s
                    LEFT JOIN resellers r ON s.reseller_id = r.id
                    WHERE s.reseller_id = ?
                    ORDER BY s.updated_at DESC LIMIT 10
                """, (reseller_id,))
            else:
                cursor.execute("""
                    SELECT s.*, u.created_at as user_registered_at, u.username
                    FROM subscriptions s
                    LEFT JOIN users u ON s.telegram_id = u.telegram_id
                    ORDER BY s.updated_at DESC LIMIT 10
                """)
            res["timeline_subscriptions"] = [dict(r) for r in cursor.fetchall()]

            return res
        except Exception as e:
            logger.error(f"Error in get_advanced_analytics: {e}")
            return {
                "popular_plans": [],
                "top_users_month": [],
                "top_users_year": [],
                "most_active_users": [],
                "usage_history": [],
                "timeline_subscriptions": []
            }
        finally:
            conn.close()

    # ═══════════════════════════════════════════════════════════════
    # مهاجرت از JSON به دیتابیس
    # ═══════════════════════════════════════════════════════════════

    def migrate_from_json(self):
        """مهاجرت اطلاعات از فایل‌های JSON به دیتابیس"""
        data_dir = Path("data")
        migrated = 0

        # مهاجرت کاربران
        for user_file in data_dir.glob("*.json"):
            if user_file.name in ["transactions.json", "cards.json", "plans.json"]:
                continue

            try:
                with open(user_file, "r", encoding="utf-8") as f:
                    user_data = json.load(f)

                telegram_id = int(user_file.stem)
                self.save_user(
                    telegram_id=telegram_id,
                    username=user_data.get("username", f"tg_{telegram_id}"),
                    hidify_uuid=user_data.get("hidify_uuid", ""),
                    plan_id=user_data.get("plan", ""),
                    data_limit=user_data.get("data_limit", 0),
                    expire_at=user_data.get("expire_at"),
                )
                migrated += 1
                logger.info(f"Migrated user {telegram_id}")
            except Exception as e:
                logger.error(f"Error migrating {user_file}: {e}")

        # مهاجرت تراکنش‌ها
        transactions_file = data_dir / "transactions.json"
        if transactions_file.exists():
            try:
                with open(transactions_file, "r", encoding="utf-8") as f:
                    transactions = json.load(f)

                for order_id, trans in transactions.items():
                    self.save_transaction(
                        order_id=order_id,
                        user_id=trans.get("user_id", 0),
                        username=trans.get("username", ""),
                        plan_name=trans.get("plan_name", ""),
                        amount=trans.get("amount", 0),
                        gateway=trans.get("gateway", ""),
                        tracking_code=trans.get("tracking_code", ""),
                        status=trans.get("status", "pending"),
                    )
                    migrated += 1
                logger.info(f"Migrated {len(transactions)} transactions")
            except Exception as e:
                logger.error(f"Error migrating transactions: {e}")

        logger.info(f"Migration complete: {migrated} records migrated")
        return {"success": True, "migrated": migrated}

    # ═══════════════════════════════════════════════════════════════
    # مهاجرت خودکار در شروع
    # ═══════════════════════════════════════════════════════════════

    def auto_migrate_on_startup(self):
        """مهاجرت خودکار اگر دیتابیس خالی باشد و فایل‌های JSON وجود داشته باشد"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            # بررسی آیا دیتابیس خالی است
            cursor.execute("SELECT COUNT(*) as count FROM users")
            user_count = cursor.fetchone()["count"]

            if user_count > 0:
                logger.info(f"Database has {user_count} users, skipping auto-migration")
                return {"success": True, "skipped": True, "reason": "database_not_empty"}

            # بررسی وجود فایل‌های JSON
            data_dir = Path("data")
            json_files = list(data_dir.glob("*.json"))
            if not json_files:
                logger.info("No JSON files found, skipping auto-migration")
                return {"success": True, "skipped": True, "reason": "no_json_files"}

            # اجرای مهاجرت
            logger.info(f"Found {len(json_files)} JSON files, starting auto-migration...")
            result = self.migrate_from_json()
            logger.info(f"Auto-migration completed: {result.get('migrated', 0)} records migrated")
            return result

        except Exception as e:
            logger.error(f"Error in auto-migration: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def migrate_add_columns(self):
        """اضافه کردن ستون‌های جدید به جداول قدیمی"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            # بررسی وجود ستون‌ها در subscriptions
            cursor.execute("PRAGMA table_info(subscriptions)")
            columns = [row[1] for row in cursor.fetchall()]
            if "account_name" not in columns:
                cursor.execute("ALTER TABLE subscriptions ADD COLUMN account_name TEXT")
                logger.info("Added account_name column to subscriptions")
            if "account_comment" not in columns:
                cursor.execute("ALTER TABLE subscriptions ADD COLUMN account_comment TEXT")
                logger.info("Added account_comment column to subscriptions")

            # بررسی وجود ستون language در users
            cursor.execute("PRAGMA table_info(users)")
            u_cols = [row[1] for row in cursor.fetchall()]
            if "language" not in u_cols:
                cursor.execute("ALTER TABLE users ADD COLUMN language TEXT DEFAULT 'fa'")
                logger.info("Added language column to users")

            conn.commit()
            return {"success": True}
        except Exception as e:
            logger.error(f"Error migrating columns: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def get_user_language(self, telegram_id: int) -> str:
        """دریافت زبان انتخابی کاربر"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT language FROM users WHERE telegram_id = ?", (telegram_id,))
            row = cursor.fetchone()
            if row and row["language"]:
                return str(row["language"])
            return "fa"
        except Exception as e:
            logger.error(f"Error getting user language: {e}")
            return "fa"
        finally:
            conn.close()

    def set_user_language(self, telegram_id: int, language: str) -> bool:
        """تنظیم و ذخیره زبان انتخابی کاربر"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            now = get_now_iso()
            # مطمئن شویم کاربر در جدول وجود دارد
            cursor.execute("SELECT id FROM users WHERE telegram_id = ?", (telegram_id,))
            if cursor.fetchone():
                cursor.execute("""
                    UPDATE users SET language = ?, updated_at = ? WHERE telegram_id = ?
                """, (language, now, telegram_id))
            else:
                cursor.execute("""
                    INSERT INTO users (telegram_id, language, created_at, updated_at)
                    VALUES (?, ?, ?, ?)
                """, (telegram_id, language, now, now))
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error setting user language: {e}")
            return False
        finally:
            conn.close()

    # ═══════════════════════════════════════════════════════════════
    # خروجی گرفتن از دیتابیس
    # ═══════════════════════════════════════════════════════════════

    def export_to_json(self, export_dir=None):
        """خروجی گرفتن از دیتابیس به فایل‌های JSON"""
        if export_dir is None:
            export_dir = Path("data/export")
        else:
            export_dir = Path(export_dir)
        export_dir.mkdir(parents=True, exist_ok=True)

        try:
            # خروجی کاربران
            users = self.get_all_users()
            for user in users:
                user_file = export_dir / f"user_{user['telegram_id']}.json"
                with open(user_file, "w", encoding="utf-8") as f:
                    json.dump(user, f, ensure_ascii=False, indent=2)

            # خروجی تراکنش‌ها
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM transactions")
            transactions = {row["order_id"]: dict(row) for row in cursor.fetchall()}
            conn.close()

            trans_file = export_dir / "transactions.json"
            with open(trans_file, "w", encoding="utf-8") as f:
                json.dump(transactions, f, ensure_ascii=False, indent=2)

            # خروجی اشتراک‌ها
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM subscriptions")
            subscriptions = [dict(row) for row in cursor.fetchall()]
            conn.close()

            subs_file = export_dir / "subscriptions.json"
            with open(subs_file, "w", encoding="utf-8") as f:
                json.dump(subscriptions, f, ensure_ascii=False, indent=2)

            # خروجی تنظیمات
            settings = self.get_all_settings()
            settings_file = export_dir / "settings.json"
            with open(settings_file, "w", encoding="utf-8") as f:
                json.dump(settings, f, ensure_ascii=False, indent=2)

            logger.info(f"Export completed to {export_dir}")
            return {
                "success": True,
                "export_dir": str(export_dir),
                "users": len(users),
                "transactions": len(transactions),
                "subscriptions": len(subscriptions),
            }

        except Exception as e:
            logger.error(f"Error exporting data: {e}")
            return {"success": False, "error": str(e)}

    # ═══════════════════════════════════════════════════════════════
    # ورودی گرفتن به دیتابیس
    # ═══════════════════════════════════════════════════════════════

    def import_from_json(self, import_dir=None):
        """ورودی گرفتن از فایل‌های JSON به دیتابیس"""
        if import_dir is None:
            import_dir = Path("data/export")
        else:
            import_dir = Path(import_dir)

        if not import_dir.exists():
            return {"success": False, "error": "Import directory not found"}

        imported = 0

        try:
            # ورودی کاربران
            for user_file in import_dir.glob("user_*.json"):
                try:
                    with open(user_file, "r", encoding="utf-8") as f:
                        user = json.load(f)
                    self.save_user(
                        telegram_id=user.get("telegram_id"),
                        username=user.get("username", ""),
                        hidify_uuid=user.get("hidify_uuid", ""),
                        plan_id=user.get("plan_id", user.get("plan", "")),
                        data_limit=user.get("data_limit", 0),
                        expire_at=user.get("expire_at"),
                    )
                    imported += 1
                except Exception as e:
                    logger.error(f"Error importing {user_file}: {e}")

            # ورودی تراکنش‌ها
            trans_file = import_dir / "transactions.json"
            if trans_file.exists():
                with open(trans_file, "r", encoding="utf-8") as f:
                    transactions = json.load(f)
                for order_id, trans in transactions.items():
                    self.save_transaction(
                        order_id=order_id,
                        user_id=trans.get("user_id", 0),
                        username=trans.get("username", ""),
                        plan_name=trans.get("plan_name", ""),
                        amount=trans.get("amount", 0),
                        gateway=trans.get("gateway", ""),
                        tracking_code=trans.get("tracking_code", ""),
                        status=trans.get("status", "pending"),
                    )
                    imported += 1

            # ورودی اشتراک‌ها
            subs_file = import_dir / "subscriptions.json"
            if subs_file.exists():
                with open(subs_file, "r", encoding="utf-8") as f:
                    subscriptions = json.load(f)
                for sub in subscriptions:
                    conn = self.get_connection()
                    cursor = conn.cursor()
                    try:
                        cursor.execute("""
                            INSERT OR REPLACE INTO subscriptions
                            (telegram_id, hidify_uuid, plan_id, plan_name, data_limit, data_used,
                             duration, start_date, expire_date, status, created_at, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            sub.get("telegram_id"),
                            sub.get("hidify_uuid", ""),
                            sub.get("plan_id", ""),
                            sub.get("plan_name", ""),
                            sub.get("data_limit", 0),
                            sub.get("data_used", 0),
                            sub.get("duration", 30),
                            sub.get("start_date"),
                            sub.get("expire_date"),
                            sub.get("status", "active"),
                            sub.get("created_at"),
                            sub.get("updated_at"),
                        ))
                        conn.commit()
                        imported += 1
                    except Exception as e:
                        logger.error(f"Error importing subscription: {e}")
                    finally:
                        conn.close()

            logger.info(f"Import completed: {imported} records imported")
            return {"success": True, "imported": imported}

        except Exception as e:
            logger.error(f"Error importing data: {e}")
            return {"success": False, "error": str(e)}

    # ═══════════════════════════════════════════════════════════════════════
    # متدهای مدیریت نمایندگان و همکاران فروش (Reseller System)
    # ═══════════════════════════════════════════════════════════════════════

    @staticmethod
    def hash_password(password: str) -> str:
        import hashlib
        return hashlib.sha256(password.encode("utf-8")).hexdigest()

    def create_reseller(self, username: str, password: str, name: str,
                        telegram_id: int = None, discount_percent: int = 20, initial_balance: int = 0) -> dict:
        """ایجاد نماینده جدید"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        password_hash = self.hash_password(password)
        try:
            cursor.execute("""
                INSERT INTO resellers (username, password_hash, name, telegram_id, balance, discount_percent, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?)
            """, (username.strip().lower(), password_hash, name.strip(), telegram_id, initial_balance, discount_percent, now, now))
            reseller_id = cursor.lastrowid
            
            if initial_balance > 0:
                cursor.execute("""
                    INSERT INTO reseller_transactions (reseller_id, type, amount, description, created_at)
                    VALUES (?, 'deposit', ?, 'شارژ اولیه حساب', ?)
                """, (reseller_id, initial_balance, now))

            conn.commit()
            return {"success": True, "reseller_id": reseller_id}
        except sqlite3.IntegrityError:
            return {"success": False, "error": "این نام کاربری قبلاً ثبت شده است."}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def authenticate_reseller(self, username: str, password: str):
        """احراز هویت نماینده"""
        conn = self.get_connection()
        cursor = conn.cursor()
        password_hash = self.hash_password(password)
        cursor.execute("SELECT * FROM resellers WHERE username=? AND password_hash=? AND status='active'",
                       (username.strip().lower(), password_hash))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    def get_all_resellers(self):
        """لیست همه نمایندگان"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT r.*,
                   (SELECT COUNT(*) FROM subscriptions WHERE reseller_id=r.id) as total_users,
                   (SELECT COUNT(*) FROM subscriptions WHERE reseller_id=r.id AND status='active') as active_users,
                   (SELECT COALESCE(SUM(amount), 0) FROM reseller_transactions WHERE reseller_id=r.id AND type='purchase') as total_spent
            FROM resellers r
            ORDER BY r.created_at DESC
        """)
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_reseller(self, reseller_id: int):
        """دریافت اطلاعات یک نماینده"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM resellers WHERE id=?", (reseller_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    def update_reseller(self, reseller_id: int, **kwargs):
        """ویرایش مشخصات نماینده"""
        conn = self.get_connection()
        cursor = conn.cursor()
        kwargs["updated_at"] = get_now_iso()
        
        if "password" in kwargs and kwargs["password"]:
            kwargs["password_hash"] = self.hash_password(kwargs.pop("password"))

        fields = ", ".join([f"{k}=?" for k in kwargs.keys()])
        values = list(kwargs.values()) + [reseller_id]
        cursor.execute(f"UPDATE resellers SET {fields} WHERE id=?", values)
        conn.commit()
        conn.close()
        try:
            self.export_full_backup_json()
        except Exception:
            pass
        return {"success": True}

    def toggle_reseller_status(self, reseller_id: int, is_active: bool = None):
        """فعال یا غیرفعال کردن نماینده"""
        conn = self.get_connection()
        cursor = conn.cursor()
        if is_active is None:
            cursor.execute("SELECT status FROM resellers WHERE id=?", (reseller_id,))
            row = cursor.fetchone()
            current_status = row["status"] if row else "active"
            new_status = "inactive" if current_status == "active" else "active"
        else:
            new_status = "active" if is_active else "inactive"
        
        cursor.execute("UPDATE resellers SET status=?, updated_at=? WHERE id=?", (new_status, get_now_iso(), reseller_id))
        conn.commit()
        conn.close()
        try:
            self.export_full_backup_json()
        except Exception:
            pass
        return {"success": True, "status": new_status}

    def delete_reseller(self, reseller_id: int):
        """حذف نماینده فروش"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM reseller_transactions WHERE reseller_id=?", (reseller_id,))
        cursor.execute("DELETE FROM resellers WHERE id=?", (reseller_id,))
        conn.commit()
        conn.close()
        try:
            self.export_full_backup_json()
        except Exception:
            pass
        return {"success": True}

    def add_reseller_balance(self, reseller_id: int, amount: int, description: str = "شارژ کیف پول توسط مدیریت"):
        """افزایش موجودی کیف پول نماینده"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("UPDATE resellers SET balance = balance + ?, updated_at=? WHERE id=?", (amount, now, reseller_id))
            cursor.execute("""
                INSERT INTO reseller_transactions (reseller_id, type, amount, description, created_at)
                VALUES (?, 'deposit', ?, ?, ?)
            """, (reseller_id, amount, description, now))
            conn.commit()
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def deduct_reseller_balance(self, reseller_id: int, amount: int, plan_name: str, account_name: str):
        """کسر موجودی نماینده هنگام خرید اکانت"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("SELECT balance FROM resellers WHERE id=?", (reseller_id,))
            row = cursor.fetchone()
            if not row or row["balance"] < amount:
                return {"success": False, "error": "موجودی کیف پول نماینده کافی نیست."}

            cursor.execute("UPDATE resellers SET balance = balance - ?, updated_at=? WHERE id=?", (amount, now, reseller_id))
            cursor.execute("""
                INSERT INTO reseller_transactions (reseller_id, type, amount, plan_name, account_name, description, created_at)
                VALUES (?, 'purchase', ?, ?, ?, 'خرید اشتراک برای مشتری', ?)
            """, (reseller_id, amount, plan_name, account_name, now))
            conn.commit()
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def get_reseller_transactions(self, reseller_id: int, limit: int = 100):
        """لیست تراکنش‌های یک نماینده"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM reseller_transactions WHERE reseller_id=? ORDER BY created_at DESC LIMIT ?", (reseller_id, limit))
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_reseller_subscriptions(self, reseller_id: int):
        """لیست کاربران و اشتراک‌های یک نماینده"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM subscriptions WHERE reseller_id=? ORDER BY created_at DESC", (reseller_id,))
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_reseller_stats(self, reseller_id: int):
        """آمار و شاخص‌های نماینده"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT balance, discount_percent FROM resellers WHERE id=?", (reseller_id,))
        res = cursor.fetchone()
        balance = res["balance"] if res else 0
        discount = res["discount_percent"] if res else 0
        
        cursor.execute("SELECT COUNT(*) FROM subscriptions WHERE reseller_id=?", (reseller_id,))
        total_users = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM subscriptions WHERE reseller_id=? AND status='active'", (reseller_id,))
        active_users = cursor.fetchone()[0]
        
        # مجموع خریدهای واقعی (کسر مبالغ مرجوعی/خطا در صورت وجود)
        cursor.execute("""
            SELECT COALESCE(
                (SELECT SUM(amount) FROM reseller_transactions WHERE reseller_id=? AND type='purchase'), 0
            ) - COALESCE(
                (SELECT SUM(amount) FROM reseller_transactions WHERE reseller_id=? AND (type='refund' OR description LIKE '%برگشت%')), 0
            )
        """, (reseller_id, reseller_id))
        total_purchases_val = cursor.fetchone()[0] or 0
        total_purchases = max(0, total_purchases_val)

        cursor.execute("SELECT COALESCE(SUM(data_used), 0), COALESCE(SUM(data_limit), 0) FROM subscriptions WHERE reseller_id=?", (reseller_id,))
        traffic_row = cursor.fetchone()
        total_used_gb = traffic_row[0] or 0
        total_limit_gb = traffic_row[1] or 0

        conn.close()
        return {
            "balance": balance,
            "discount_percent": discount,
            "total_users": total_users,
            "active_users": active_users,
            "total_purchases": total_purchases,
            "total_used_gb": round(total_used_gb, 2),
            "total_limit_gb": round(total_limit_gb, 2),
        }

    # ═══════════════════════════════════════════════════════════════════════
    # ارسال پیام هدفمند به دسته‌های کاربری (Broadcast Engine)
    # ═══════════════════════════════════════════════════════════════════════

    def get_target_broadcast_users(self, group_type: str = "all") -> list:
        """استخراج لیست تلگرام آیدی کاربران بر اساس فیلتر هدفمند"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        if group_type == "all":
            cursor.execute("SELECT DISTINCT telegram_id FROM users WHERE telegram_id IS NOT NULL AND telegram_id != 0")
        elif group_type == "active":
            cursor.execute("SELECT DISTINCT telegram_id FROM subscriptions WHERE status='active'")
        elif group_type == "expired":
            cursor.execute("""
                SELECT DISTINCT telegram_id FROM subscriptions 
                WHERE status='expired' OR (expire_date IS NOT NULL AND expire_date < datetime('now'))
            """)
        elif group_type == "test_only":
            cursor.execute("""
                SELECT DISTINCT telegram_id FROM subscriptions WHERE plan_id='test'
                EXCEPT
                SELECT DISTINCT telegram_id FROM subscriptions WHERE plan_id != 'test'
            """)
        elif group_type == "expiring_soon":
            cursor.execute("""
                SELECT DISTINCT telegram_id FROM subscriptions 
                WHERE status='active' AND expire_date IS NOT NULL 
                  AND expire_date BETWEEN datetime('now') AND datetime('now', '+3 days')
            """)
        else:
            cursor.execute("SELECT DISTINCT telegram_id FROM users WHERE telegram_id IS NOT NULL")
            
        rows = cursor.fetchall()
        conn.close()
        return [r[0] for r in rows if r[0]]

    # ═══════════════════════════════════════════════════════════════════════
    # مدیریت کارت‌های بانکی مقصد (Smart Card Rotator)
    # ═══════════════════════════════════════════════════════════════════════

    def get_all_bank_cards(self):
        """لیست تمام کارت‌های بانکی"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM bank_cards ORDER BY created_at DESC")
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def add_bank_card(self, card_number: str, card_holder: str, bank_name: str, daily_limit: int = 50000000):
        """افزودن کارت بانکی جدید"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        cursor.execute("""
            INSERT INTO bank_cards (card_number, card_holder, bank_name, daily_limit, is_active, created_at)
            VALUES (?, ?, ?, ?, 1, ?)
        """, (card_number.strip(), card_holder.strip(), bank_name.strip(), daily_limit, now))
        conn.commit()
        conn.close()
        try:
            self.export_full_backup_json()
        except Exception:
            pass
        return {"success": True}

    def toggle_bank_card(self, card_id: int, is_active: bool):
        """فعال یا غیرفعال کردن کارت"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE bank_cards SET is_active=? WHERE id=?", (1 if is_active else 0, card_id))
        conn.commit()
        conn.close()
        try:
            self.export_full_backup_json()
        except Exception:
            pass
        return {"success": True}

    def delete_bank_card(self, card_id: int):
        """حذف کارت بانکی"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM bank_cards WHERE id=?", (card_id,))
        conn.commit()
        conn.close()
        try:
            self.export_full_backup_json()
        except Exception:
            pass
        return {"success": True}

    # ═══════════════════════════════════════════════════════════════
    # سیستم حسابداری و مدیریت مالی پیشرفته (Accounting & Profit/Loss)
    # ═══════════════════════════════════════════════════════════════

    def add_accounting_record(self, type: str, category: str, title: str, amount: int,
                              source: str = "manual", ref_type: str = None, ref_id: str = None,
                              description: str = None, date: str = None) -> dict:
        """ثبت سند جدید درآمد یا هزینه در حسابداری"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now_iso = get_now_iso()
        record_date = date.strip() if date else now_iso[:10]
        try:
            cursor.execute("""
                INSERT INTO accounting_records 
                (type, category, title, amount, source, ref_type, ref_id, description, date, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                type.strip().lower(), category.strip(), title.strip(),
                int(amount), source, ref_type, ref_id, description,
                record_date, now_iso
            ))
            record_id = cursor.lastrowid
            conn.commit()
            try:
                self.export_full_backup_json()
            except Exception:
                pass
            return {"success": True, "record_id": record_id}
        except Exception as e:
            logger.error(f"Error adding accounting record: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def update_accounting_record(self, record_id: int, **kwargs) -> dict:
        """ویرایش سند حسابداری"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            allowed = ["type", "category", "title", "amount", "description", "date"]
            updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
            if not updates:
                return {"success": False, "error": "داده‌ای برای بروزرسانی ارسال نشده است."}

            fields = ", ".join([f"{k}=?" for k in updates.keys()])
            values = list(updates.values()) + [record_id]
            cursor.execute(f"UPDATE accounting_records SET {fields} WHERE id=?", values)
            conn.commit()
            try:
                self.export_full_backup_json()
            except Exception:
                pass
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def delete_accounting_record(self, record_id: int) -> dict:
        """حذف سند حسابداری"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("DELETE FROM accounting_records WHERE id=?", (record_id,))
            conn.commit()
            try:
                self.export_full_backup_json()
            except Exception:
                pass
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def get_accounting_records(self, limit: int = 300, type_filter: str = "all",
                               category_filter: str = "all", period: str = "all",
                               search: str = None) -> list:
        """دریافت لیست اسناد حسابداری با فیلترهای پیشرفته"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            query = "SELECT * FROM accounting_records WHERE 1=1"
            params = []

            if type_filter and type_filter != "all":
                query += " AND type = ?"
                params.append(type_filter)

            if category_filter and category_filter != "all":
                query += " AND category = ?"
                params.append(category_filter)

            if period == "today":
                query += " AND date = DATE('now')"
            elif period == "week":
                query += " AND date >= DATE('now', '-7 days')"
            elif period == "month":
                query += " AND date >= DATE('now', 'start of month')"
            elif period == "year":
                query += " AND date >= DATE('now', 'start of year')"

            if search and search.strip():
                query += " AND (title LIKE ? OR description LIKE ? OR category LIKE ?)"
                kw = f"%{search.strip()}%"
                params.extend([kw, kw, kw])

            query += " ORDER BY date DESC, id DESC LIMIT ?"
            params.append(limit)

            cursor.execute(query, params)
            rows = cursor.fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"Error in get_accounting_records: {e}")
            return []
        finally:
            conn.close()

    def get_accounting_summary(self) -> dict:
        """محاسبه شاخص‌های جامع مالی، درآمد کل، مخارج، سود خالص و حاشیه سودآوری"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            # ۱. درآمدهای خودکار از اشتراک‌های تایید شده کاربران
            cursor.execute("SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE status IN ('approved', 'completed')")
            auto_tx_income = cursor.fetchone()[0] or 0

            # ۲. درآمدهای خودکار از شارژ نمایندگان
            cursor.execute("SELECT COALESCE(SUM(amount), 0) FROM reseller_transactions WHERE type='deposit'")
            auto_reseller_income = cursor.fetchone()[0] or 0

            # ۳. درآمدهای دستی ثبت شده در سیستم حسابداری
            cursor.execute("SELECT COALESCE(SUM(amount), 0) FROM accounting_records WHERE type='income'")
            manual_income = cursor.fetchone()[0] or 0

            # کل درآمد ناخالص
            total_income = auto_tx_income + auto_reseller_income + manual_income

            # ۴. کل مخارج و هزینه‌ها
            cursor.execute("SELECT COALESCE(SUM(amount), 0) FROM accounting_records WHERE type='expense'")
            total_expense = cursor.fetchone()[0] or 0

            # ۵. سود خالص و حاشیه سود
            net_profit = total_income - total_expense
            profit_margin = round((net_profit / total_income * 100), 1) if total_income > 0 else 0.0

            # ۶. آمار ماه جاری
            current_month = get_now_naive().strftime("%Y-%m")
            cursor.execute("""
                SELECT COALESCE(SUM(amount), 0) FROM transactions 
                WHERE status IN ('approved', 'completed') AND created_at LIKE ?
            """, (f"{current_month}%",))
            month_auto_income = cursor.fetchone()[0] or 0

            cursor.execute("SELECT COALESCE(SUM(amount), 0) FROM accounting_records WHERE type='income' AND date LIKE ?", (f"{current_month}%",))
            month_manual_income = cursor.fetchone()[0] or 0
            month_total_income = month_auto_income + month_manual_income

            cursor.execute("SELECT COALESCE(SUM(amount), 0) FROM accounting_records WHERE type='expense' AND date LIKE ?", (f"{current_month}%",))
            month_total_expense = cursor.fetchone()[0] or 0
            month_net_profit = month_total_income - month_total_expense

            # ۷. تفکیک مخارج بر اساس دسته‌بندی
            cursor.execute("""
                SELECT category, SUM(amount) as total, COUNT(*) as count
                FROM accounting_records
                WHERE type='expense'
                GROUP BY category
                ORDER BY total DESC
            """)
            expense_categories = [dict(r) for r in cursor.fetchall()]

            # ۸. روند ماهانه سود و مخارج (۶ ماه گذشته)
            cursor.execute("""
                SELECT strftime('%Y-%m', date) as month,
                       SUM(CASE WHEN type='income' THEN amount ELSE 0 END) as manual_inc,
                       SUM(CASE WHEN type='expense' THEN amount ELSE 0 END) as exp
                FROM accounting_records
                GROUP BY strftime('%Y-%m', date)
                ORDER BY month DESC LIMIT 6
            """)
            monthly_trend = [dict(r) for r in cursor.fetchall()]

            return {
                "total_income": total_income,
                "auto_tx_income": auto_tx_income,
                "auto_reseller_income": auto_reseller_income,
                "manual_income": manual_income,
                "total_expense": total_expense,
                "net_profit": net_profit,
                "profit_margin": profit_margin,
                "month_total_income": month_total_income,
                "month_total_expense": month_total_expense,
                "month_net_profit": month_net_profit,
                "expense_categories": expense_categories,
                "monthly_trend": monthly_trend,
            }
        except Exception as e:
            logger.error(f"Error in get_accounting_summary: {e}")
            return {
                "total_income": 0, "auto_tx_income": 0, "auto_reseller_income": 0, "manual_income": 0,
                "total_expense": 0, "net_profit": 0, "profit_margin": 0.0,
                "month_total_income": 0, "month_total_expense": 0, "month_net_profit": 0,
                "expense_categories": [], "monthly_trend": []
            }
        finally:
            conn.close()

    # ═══════════════════════════════════════════════════════════════════════
    # سیستم مدیریت مدیران و سطوح دسترسی (Admin Management & RBAC)
    # ═══════════════════════════════════════════════════════════════════════

    def authenticate_admin(self, username: str, password: str):
        """احراز هویت مدیران از جدول admin_users"""
        conn = self.get_connection()
        cursor = conn.cursor()
        password_hash = self.hash_password(password)
        now = get_now_iso()
        cursor.execute("SELECT * FROM admin_users WHERE username=? AND (password_hash=? OR password_hash=?) AND is_active=1",
                       (username.strip(), password_hash, password.strip()))
        row = cursor.fetchone()
        if row:
            admin_dict = dict(row)
            cursor.execute("UPDATE admin_users SET last_login=? WHERE id=?", (now, admin_dict["id"]))
            conn.commit()
            conn.close()
            return admin_dict
        conn.close()
        return None

    def get_admin_users(self):
        """لیست تمام مدیران سیستم"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM admin_users ORDER BY id ASC")
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_admin_user(self, admin_id: int):
        """دریافت اطلاعات یک مدیر"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM admin_users WHERE id=?", (admin_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    def create_admin_user(self, username: str, password: str, display_name: str,
                          role: str = "super_admin", permissions: str = "*", is_active: bool = True,
                          telegram_id: int = None) -> dict:
        """افزودن مدیر جدید با نقش و دسترسی‌های مشخص و آیدی تلگرام"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        password_hash = self.hash_password(password)
        try:
            cursor.execute("""
                INSERT INTO admin_users (username, password_hash, display_name, role, permissions, is_active, created_at, telegram_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (username.strip(), password_hash, display_name.strip(), role, permissions, 1 if is_active else 0, now, telegram_id))
            admin_id = cursor.lastrowid
            conn.commit()
            return {"success": True, "admin_id": admin_id}
        except sqlite3.IntegrityError:
            return {"success": False, "error": "این نام کاربری قبلاً برای مدیر دیگری ثبت شده است."}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def update_admin_user(self, admin_id: int, **kwargs) -> dict:
        """ویرایش اطلاعات و دسترسی‌های یک مدیر"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            fields = []
            params = []
            for key, val in kwargs.items():
                if key == "password" and val:
                    fields.append("password_hash=?")
                    params.append(self.hash_password(val))
                elif key in ["username", "display_name", "role", "permissions", "is_active", "telegram_id"]:
                    fields.append(f"{key}=?")
                    params.append(val)

            if not fields:
                return {"success": True}

            params.append(admin_id)
            query = f"UPDATE admin_users SET {', '.join(fields)} WHERE id=?"
            cursor.execute(query, params)
            conn.commit()
            return {"success": True}
        except sqlite3.IntegrityError:
            return {"success": False, "error": "این نام کاربری تکراری است."}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def toggle_admin_user(self, admin_id: int) -> dict:
        """تغییر وضعیت فعال/غیرفعال مدیر"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT is_active FROM admin_users WHERE id=?", (admin_id,))
            row = cursor.fetchone()
            if not row:
                return {"success": False, "error": "مدیر یافت نشد."}
            new_status = 0 if row["is_active"] else 1
            cursor.execute("UPDATE admin_users SET is_active=? WHERE id=?", (new_status, admin_id))
            conn.commit()
            return {"success": True, "is_active": new_status}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def delete_admin_user(self, admin_id: int) -> dict:
        """حذف مدیر"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("DELETE FROM admin_users WHERE id=?", (admin_id,))
            conn.commit()
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def update_admin_profile(self, admin_id: int, username: str, password: str = None, display_name: str = None, telegram_id: int = None) -> dict:
        """تغییر مشخصات فردی، یوزرنیم، آیدی تلگرام و پسورد مدیر فعال"""
        kwargs = {"username": username}
        if display_name:
            kwargs["display_name"] = display_name
        if telegram_id is not None:
            kwargs["telegram_id"] = telegram_id
        if password and len(password.strip()) > 0:
            kwargs["password"] = password.strip()
        return self.update_admin_user(admin_id, **kwargs)

    # ═══════════════════════════════════════════════════════════════════════
    # پروفایل و مشخصات کاربری نماینده (Reseller Profile)
    # ═══════════════════════════════════════════════════════════════════════

    def update_reseller_profile(self, reseller_id: int, **kwargs) -> dict:
        """ویرایش مشخصات فردی، اطلاعات تماس، حساب بانکی و تغییر رمز عبور توسط خود نماینده"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            fields = ["updated_at=?"]
            params = [now]
            for key, val in kwargs.items():
                if key == "password" and val:
                    fields.append("password_hash=?")
                    params.append(self.hash_password(val))
                elif key in ["username", "name", "phone", "email", "telegram_id", "bank_card", "notes"]:
                    fields.append(f"{key}=?")
                    params.append(val)

            params.append(reseller_id)
            query = f"UPDATE resellers SET {', '.join(fields)} WHERE id=?"
            cursor.execute(query, params)
            conn.commit()
            return {"success": True}
        except sqlite3.IntegrityError:
            return {"success": False, "error": "این نام کاربری قبلاً ثبت شده است."}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            conn.close()


# نمونه singleton
db = Database()

