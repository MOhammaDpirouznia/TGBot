#!/usr/bin/env python3
"""
ماژول دیتابیس برای ذخیره‌سازی مشتریان، تنظیمات و تراکنش‌ها
"""

import sqlite3
import json
import os
import re
import logging
from typing import Optional, Dict, List, Any, Tuple, Union
from datetime import datetime, timedelta
from utils import get_now_naive, get_now_iso, TEHRAN_TZ
from pathlib import Path
from session_analyzer import parse_user_agent_details

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

        # جدول لاگ حسابرسی و ردپای تغییرات تراکنش‌ها (Audit Logs)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS transaction_audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                transaction_id INTEGER NOT NULL,
                admin_id INTEGER,
                admin_name TEXT,
                action TEXT NOT NULL,
                field_name TEXT,
                old_value TEXT,
                new_value TEXT,
                reason TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (transaction_id) REFERENCES transactions(id)
            )
        """)

        # جدول لاگ ورود، خروج، نشست‌های فعال و امنیت (Login & Security Logs)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS login_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_type TEXT NOT NULL,
                user_id INTEGER,
                username TEXT NOT NULL,
                attempted_password TEXT,
                status TEXT NOT NULL,
                failure_reason TEXT,
                ip_address TEXT NOT NULL,
                user_agent TEXT,
                browser TEXT,
                device_os TEXT,
                session_token TEXT,
                login_at TEXT NOT NULL,
                last_active_at TEXT,
                logout_at TEXT,
                is_active INTEGER DEFAULT 1
            )
        """)

        # مایگریشن خودکار ستون‌های جدید
        try:
            cursor.execute("ALTER TABLE transactions ADD COLUMN is_deleted INTEGER DEFAULT 0")
        except Exception:
            pass

        try:
            cursor.execute("ALTER TABLE transactions ADD COLUMN revoked_at TEXT")
        except Exception:
            pass

        try:
            cursor.execute("ALTER TABLE transactions ADD COLUMN revoked_by TEXT")
        except Exception:
            pass

        try:
            cursor.execute("ALTER TABLE transactions ADD COLUMN revoke_reason TEXT")
        except Exception:
            pass

        try:
            cursor.execute("ALTER TABLE transactions ADD COLUMN card_number TEXT")
        except Exception:
            pass

        try:
            cursor.execute("ALTER TABLE admin_users ADD COLUMN telegram_id INTEGER")
        except Exception:
            pass
        try:
            cursor.execute("ALTER TABLE admin_users ADD COLUMN phone TEXT")
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

        try:
            cursor.execute("ALTER TABLE subscriptions ADD COLUMN phone_number TEXT")
        except Exception:
            pass

        try:
            cursor.execute("ALTER TABLE subscriptions ADD COLUMN cost_paid INTEGER DEFAULT 0")
        except Exception:
            pass

        try:
            cursor.execute("ALTER TABLE subscriptions ADD COLUMN is_online INTEGER DEFAULT 0")
        except Exception:
            pass

        try:
            cursor.execute("ALTER TABLE subscriptions ADD COLUMN last_online TEXT")
        except Exception:
            pass

        try:
            cursor.execute("ALTER TABLE users ADD COLUMN is_online INTEGER DEFAULT 0")
        except Exception:
            pass

        try:
            cursor.execute("ALTER TABLE users ADD COLUMN last_online TEXT")
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

        try:
            cursor.execute("ALTER TABLE users ADD COLUMN wallet_balance INTEGER DEFAULT 0")
        except Exception:
            pass

        try:
            cursor.execute("ALTER TABLE admin_users ADD COLUMN custom_avatar TEXT")
        except Exception:
            pass

        try:
            cursor.execute("ALTER TABLE admin_users ADD COLUMN share_percent INTEGER DEFAULT 0")
        except Exception:
            pass

        try:
            cursor.execute("ALTER TABLE admin_users ADD COLUMN debt_balance INTEGER DEFAULT 0")
        except Exception:
            pass

        try:
            cursor.execute("ALTER TABLE resellers ADD COLUMN custom_avatar TEXT")
        except Exception:
            pass

        try:
            cursor.execute("ALTER TABLE subscriptions ADD COLUMN custom_avatar TEXT")
        except Exception:
            pass

        try:
            cursor.execute("ALTER TABLE users ADD COLUMN custom_avatar TEXT")
        except Exception:
            pass

        # ستون‌های ربات اختصاصی (White-label Multi-Bot) و تنظیمات نمایندگان
        for col_def in [
            "bot_token TEXT", "bot_username TEXT", "channel_id TEXT", "brand_name TEXT",
            "start_message TEXT", "support_username TEXT", "card_number TEXT", "card_holder TEXT",
            "bank_name TEXT", "is_bot_active INTEGER DEFAULT 0", "tier_level TEXT DEFAULT 'silver'",
            "auto_approval INTEGER DEFAULT 0"
        ]:
            try:
                cursor.execute(f"ALTER TABLE resellers ADD COLUMN {col_def}")
            except Exception:
                pass

        # ستون‌های برندینگ، دامنه و آموزش‌های اختصاصی نماینده
        for col_def in [
            "custom_domain TEXT", "tutorial_domain TEXT", "logo_url TEXT", "favicon_url TEXT",
            "brand_title TEXT", "primary_color TEXT", "footer_text TEXT"
        ]:
            try:
                cursor.execute(f"ALTER TABLE resellers ADD COLUMN {col_def}")
            except Exception:
                pass

        try:
            cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_resellers_custom_domain ON resellers(custom_domain)")
        except Exception:
            pass

        try:
            cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_resellers_tutorial_domain ON resellers(tutorial_domain)")
        except Exception:
            pass

        # ستون‌های انتساب مدیر به نماینده جهت ساخت زیرمدیران (Sub-Admins)
        try:
            cursor.execute("ALTER TABLE admin_users ADD COLUMN reseller_id INTEGER")
        except Exception:
            pass

        try:
            cursor.execute("ALTER TABLE admin_users ADD COLUMN parent_admin_id INTEGER")
        except Exception:
            pass

        # جدول کارت‌های بانکی اختصاصی نماینده
        try:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS reseller_cards (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    reseller_id INTEGER NOT NULL,
                    card_number TEXT NOT NULL,
                    card_holder TEXT NOT NULL,
                    bank_name TEXT NOT NULL,
                    daily_limit INTEGER DEFAULT 50000000,
                    is_active BOOLEAN DEFAULT 1,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (reseller_id) REFERENCES resellers(id)
                )
            """)
        except Exception:
            pass

        # جدول کدهای تخفیف اختصاصی نماینده
        try:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS reseller_discount_codes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    reseller_id INTEGER NOT NULL,
                    code TEXT NOT NULL,
                    discount_percent INTEGER DEFAULT 0,
                    discount_amount INTEGER DEFAULT 0,
                    max_uses INTEGER DEFAULT 0,
                    used_count INTEGER DEFAULT 0,
                    valid_until TEXT,
                    is_active BOOLEAN DEFAULT 1,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (reseller_id) REFERENCES resellers(id)
                )
            """)
        except Exception:
            pass

        try:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS wallet_transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER NOT NULL,
                    amount INTEGER NOT NULL,
                    type TEXT NOT NULL,
                    balance_after INTEGER NOT NULL,
                    description TEXT,
                    ref_id TEXT,
                    created_at TEXT NOT NULL
                )
            """)
        except Exception:
            pass

        try:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS admin_debts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    admin_id INTEGER NOT NULL,
                    admin_username TEXT NOT NULL,
                    customer_name TEXT,
                    plan_name TEXT,
                    total_amount INTEGER NOT NULL,
                    share_percent INTEGER DEFAULT 0,
                    share_amount INTEGER DEFAULT 0,
                    debt_amount INTEGER NOT NULL,
                    type TEXT NOT NULL,
                    description TEXT,
                    created_by INTEGER,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (admin_id) REFERENCES admin_users(id)
                )
            """)
        except Exception:
            pass

        # ستون تعداد کاربر مجاز و جدول نشست‌ها (Device/User Limit & Sessions)
        try:
            cursor.execute("ALTER TABLE subscriptions ADD COLUMN user_limit INTEGER DEFAULT 1")
        except Exception:
            pass

        try:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS subscription_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sub_id INTEGER,
                    hidify_uuid TEXT,
                    ip_address TEXT,
                    device_name TEXT,
                    os_name TEXT,
                    os_icon TEXT,
                    client_app TEXT,
                    client_version TEXT,
                    app_icon TEXT,
                    isp_name TEXT,
                    user_agent TEXT,
                    last_seen TEXT,
                    is_active INTEGER DEFAULT 1,
                    created_at TEXT
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_sub_sessions_sub_id ON subscription_sessions(sub_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_sub_sessions_uuid ON subscription_sessions(hidify_uuid)")
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

    def _parse_hiddify_user_online(self, u: dict) -> tuple[int, str]:
        """
        تشخیص آنلاین بودن و استخراج آخرین اتصال از آبجکت کاربر در هیدیفای (روش فوق‌بهینه بر پایه Timestamp)
        خروجی: (is_online: 1|0, last_online_str)
        """
        if not u or not isinstance(u, dict):
            return 0, None

        is_online = 0
        if u.get("is_online") in (True, 1, "true", "True") or u.get("online") in (True, 1, "true", "True"):
            is_online = 1

        last_online_raw = u.get("last_online") or u.get("last_online_time") or u.get("last_connected")
        last_online_str = None

        if last_online_raw:
            try:
                clean_str = str(last_online_raw).replace("T", " ").split(".")[0].split("+")[0].strip()
                last_online_str = clean_str
                # بررسی فاصله زمانی آخرین اتصال
                dt = datetime.strptime(clean_str, "%Y-%m-%d %H:%M:%S")
                # مقایسه همزمان با ساعت تهران و UTC جهت رفع کامل خطای اختلاف منطقه زمانی سرور
                now_tehran = get_now_naive()
                now_utc = datetime.utcnow()
                diff_tehran = abs((now_tehran - dt).total_seconds())
                diff_utc = abs((now_utc - dt).total_seconds())
                min_diff = min(diff_tehran, diff_utc)
                # استاندارد پنل هیدیفای: اتصال در ۱۵ دقیقه (۹۰۰ ثانیه) اخیر = آنلاین
                if min_diff <= 900:
                    is_online = 1
            except Exception:
                last_online_str = str(last_online_raw)

        return is_online, last_online_str

    def sync_from_hidify(self, hidify_users: list) -> dict:
        """همگام‌سازی و بازیابی خودکار تمامی کاربران و اشتراک‌ها به همراه وضعیت آنلاین بودن از پنل هیدیفای"""
        if not hidify_users or not isinstance(hidify_users, list):
            return {"success": False, "count": 0, "error": "لیست کاربران هیدیفای خالی یا نامعتبر است"}

        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        restored_users = 0
        restored_subs = 0
        total_online = 0

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
                
                raw_start = u.get("start_date")
                start_date = str(raw_start).strip() if (raw_start and str(raw_start).strip() not in ["None", "null", ""]) else None
                
                raw_expiry = u.get("expiry_time") or u.get("expire_date") or u.get("expire")
                expiry_time = str(raw_expiry).strip() if (raw_expiry and str(raw_expiry).strip() not in ["None", "null", ""]) else None
                
                status = "active" if (is_active and enable) else ("disabled" if not enable else "expired")

                # تشخیص وضعیت آنلاین بودن
                is_online_val, last_online_val = self._parse_hiddify_user_online(u)
                if is_online_val:
                    total_online += 1

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
                            INSERT INTO users (telegram_id, username, hidify_uuid, plan_id, data_limit, is_online, last_online, created_at, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (telegram_id, name, uuid, "custom", usage_limit, is_online_val, last_online_val, now, now))
                        restored_users += 1
                    else:
                        cursor.execute("""
                            UPDATE users SET
                                username = COALESCE(?, username),
                                hidify_uuid = COALESCE(?, hidify_uuid),
                                data_limit = ?,
                                is_online = ?,
                                last_online = COALESCE(?, last_online),
                                updated_at = ?
                            WHERE telegram_id = ?
                        """, (name, uuid, usage_limit, is_online_val, last_online_val, now, telegram_id))

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
                    # بروزرسانی مصرف، سقف حجم، تعداد روزها (duration / package_days)، تاریخ‌ها و وضعیت
                    cursor.execute("""
                        UPDATE subscriptions SET
                            data_used = ?,
                            data_limit = ?,
                            duration = ?,
                            start_date = ?,
                            expire_date = ?,
                            status = ?,
                            account_name = COALESCE(?, account_name),
                            is_online = ?,
                            last_online = COALESCE(?, last_online),
                            updated_at = ?
                        WHERE hidify_uuid = ?
                    """, (current_usage, usage_limit, package_days, start_date, expiry_time, status, name, is_online_val, last_online_val, now, uuid))
                else:
                    # درج اشتراک جدید بازیابی شده
                    cursor.execute("""
                        INSERT INTO subscriptions (
                            telegram_id, hidify_uuid, plan_id, plan_name, account_name,
                            account_comment, data_limit, data_used, duration, start_date,
                            expire_date, status, is_online, last_online, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        telegram_id, uuid, plan_id, plan_name, name,
                        comment, usage_limit, current_usage, package_days, start_date,
                        expiry_time, status, is_online_val, last_online_val, now, now
                    ))
                    restored_subs += 1

            conn.commit()
            logger.info(f"Hiddify sync complete: {restored_users} users, {restored_subs} subscriptions, {total_online} online.")
            return {
                "success": True,
                "restored_users": restored_users,
                "restored_subs": restored_subs,
                "total_online": total_online,
                "total_hiddify": len(hidify_users)
            }
        except Exception as e:
            logger.error(f"Error syncing from Hiddify: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def get_online_users_stats(self, reseller_id: int = None) -> dict:
        """آمار تعداد کل کاربران و مشتریان آنلاین برای ادمین یا نماینده"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            if reseller_id:
                cursor.execute("SELECT COUNT(*) FROM subscriptions WHERE reseller_id = ? AND is_online = 1", (reseller_id,))
                online_count = cursor.fetchone()[0]
                cursor.execute("SELECT COUNT(*) FROM subscriptions WHERE reseller_id = ?", (reseller_id,))
                total_subs = cursor.fetchone()[0]
                cursor.execute("SELECT COUNT(*) FROM subscriptions WHERE reseller_id = ? AND status = 'active'", (reseller_id,))
                active_subs = cursor.fetchone()[0]
            else:
                cursor.execute("SELECT COUNT(*) FROM subscriptions WHERE is_online = 1")
                online_count = cursor.fetchone()[0]
                cursor.execute("SELECT COUNT(*) FROM subscriptions")
                total_subs = cursor.fetchone()[0]
                cursor.execute("SELECT COUNT(*) FROM subscriptions WHERE status = 'active'")
                active_subs = cursor.fetchone()[0]
            return {
                "online_count": online_count,
                "total_subs": total_subs,
                "active_subs": active_subs,
                "offline_count": max(0, active_subs - online_count)
            }
        except Exception as e:
            logger.error(f"Error in get_online_users_stats: {e}")
            return {"online_count": 0, "total_subs": 0, "active_subs": 0, "offline_count": 0}
        finally:
            conn.close()

    def get_online_subscriptions(self, reseller_id: int = None) -> list:
        """دریافت لیست اشتراک‌های آنلاین"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            if reseller_id:
                cursor.execute("SELECT * FROM subscriptions WHERE reseller_id = ? AND is_online = 1 ORDER BY updated_at DESC", (reseller_id,))
            else:
                cursor.execute("SELECT * FROM subscriptions WHERE is_online = 1 ORDER BY updated_at DESC")
            rows = cursor.fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"Error in get_online_subscriptions: {e}")
            return []
        finally:
            conn.close()

    # ═══════════════════════════════════════════════════════════════
    # مدیریت مشتریان
    # ═══════════════════════════════════════════════════════════════

    def save_user(self, telegram_id, username=None, hidify_uuid=None, plan_id=None, data_limit=None, expire_at=None, reseller_id=None):
        """ذخیره یا بروزرسانی اطلاعات کاربر"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()

        try:
            # بررسی وجود کاربر
            cursor.execute("SELECT id, reseller_id FROM users WHERE telegram_id = ?", (telegram_id,))
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
                        reseller_id = COALESCE(?, reseller_id),
                        updated_at = ?
                    WHERE telegram_id = ?
                """, (username, hidify_uuid, plan_id, data_limit, expire_at, reseller_id, now, telegram_id))
            else:
                # درج جدید
                cursor.execute("""
                    INSERT INTO users (telegram_id, username, hidify_uuid, plan_id, data_limit, expire_at, reseller_id, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (telegram_id, username or f"user_{telegram_id}", hidify_uuid, plan_id, data_limit or 0, expire_at, reseller_id, now, now))

            conn.commit()
            logger.info(f"User {telegram_id} saved successfully (reseller_id={reseller_id})")
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

    # ═══════════════════════════════════════════════════════════════
    # مدیریت کیف پول کاربر (User In-App Wallet)
    # ═══════════════════════════════════════════════════════════════

    def get_user_wallet_balance(self, telegram_id: int) -> int:
        """دریافت موجودی کیف پول کاربر (به تومان)"""
        user = self.get_user(telegram_id)
        if not user:
            return 0
        return int(user.get("wallet_balance") or 0)

    def add_wallet_balance(self, telegram_id: int, amount: int, description: str, ref_id: str = None, tx_type: str = "deposit") -> dict:
        """افزایش موجودی کیف پول کاربر و ثبت تراکنش"""
        if amount <= 0:
            return {"success": False, "error": "مبلغ باید بیشتر از صفر باشد."}
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("SELECT id, wallet_balance FROM users WHERE telegram_id = ?", (telegram_id,))
            row = cursor.fetchone()
            if not row:
                cursor.execute("""
                    INSERT INTO users (telegram_id, username, wallet_balance, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                """, (telegram_id, f"user_{telegram_id}", amount, now, now))
                new_balance = amount
            else:
                current_bal = int(row["wallet_balance"] or 0)
                new_balance = current_bal + amount
                cursor.execute("UPDATE users SET wallet_balance = ?, updated_at = ? WHERE telegram_id = ?", (new_balance, now, telegram_id))

            cursor.execute("""
                INSERT INTO wallet_transactions (telegram_id, amount, type, balance_after, description, ref_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (telegram_id, amount, tx_type, new_balance, description, ref_id, now))

            conn.commit()
            return {"success": True, "new_balance": new_balance}
        except Exception as e:
            logger.error(f"Error adding wallet balance for {telegram_id}: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def deduct_wallet_balance(self, telegram_id: int, amount: int, description: str, ref_id: str = None) -> dict:
        """کسر از موجودی کیف پول کاربر جهت خرید یا تمدید پلن"""
        if amount <= 0:
            return {"success": False, "error": "مبلغ نامعتبر است."}
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("SELECT id, wallet_balance FROM users WHERE telegram_id = ?", (telegram_id,))
            row = cursor.fetchone()
            if not row:
                return {"success": False, "error": "کاربر یافت نشد."}

            current_bal = int(row["wallet_balance"] or 0)
            if current_bal < amount:
                return {"success": False, "error": "موجودی کیف پول شما کافی نیست.", "balance": current_bal, "required": amount}

            new_balance = current_bal - amount
            cursor.execute("UPDATE users SET wallet_balance = ?, updated_at = ? WHERE telegram_id = ?", (new_balance, now, telegram_id))

            cursor.execute("""
                INSERT INTO wallet_transactions (telegram_id, amount, type, balance_after, description, ref_id, created_at)
                VALUES (?, ?, 'purchase', ?, ?, ?, ?)
            """, (telegram_id, -amount, new_balance, description, ref_id, now))

            conn.commit()
            return {"success": True, "new_balance": new_balance}
        except Exception as e:
            logger.error(f"Error deducting wallet balance for {telegram_id}: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def get_wallet_transactions(self, telegram_id: int, limit: int = 20) -> list:
        """دریافت لیست تاریخچه تراکنش‌های کیف پول کاربر"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT * FROM wallet_transactions 
                WHERE telegram_id = ? 
                ORDER BY created_at DESC 
                LIMIT ?
            """, (telegram_id, limit))
            rows = cursor.fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"Error getting wallet transactions for {telegram_id}: {e}")
            return []
        finally:
            conn.close()

    def find_telegram_id_by_phone(self, phone_number: str) -> Optional[int]:
        """یافتن آیدی تلگرام کاربر از روی شماره تلفن ثبت‌شده در جدول کاربران"""
        if not phone_number:
            return None
        clean = re.sub(r"[^\d+]", "", str(phone_number).strip())
        if not clean:
            return None
        last_9 = clean[-9:] if len(clean) >= 9 else clean
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT telegram_id FROM users 
                WHERE phone_number = ? OR phone_number LIKE ?
                LIMIT 1
            """, (phone_number, f"%{last_9}%"))
            row = cursor.fetchone()
            if row and row["telegram_id"]:
                return int(row["telegram_id"])
            return None
        except Exception as e:
            logger.error(f"Error finding telegram_id by phone: {e}")
            return None
        finally:
            conn.close()

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

    def save_subscription(self, telegram_id, hidify_uuid, plan_id, plan_name, data_limit, duration, data_used=0, status="active", account_name=None, account_comment=None, reseller_id=None, user_limit=1):
        """ذخیره اشتراک جدید"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        expire_date = (get_now_naive() + timedelta(days=duration)).isoformat()

        try:
            cursor.execute("""
                INSERT INTO subscriptions
                (telegram_id, hidify_uuid, plan_id, plan_name, account_name, account_comment, data_limit, data_used, duration, start_date, expire_date, status, reseller_id, user_limit, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (telegram_id, hidify_uuid, plan_id, plan_name, account_name, account_comment, data_limit, data_used, duration, now, expire_date, status, reseller_id, int(user_limit or 1), now, now))
            conn.commit()
            subscription_id = cursor.lastrowid
            logger.info(f"Subscription {subscription_id} saved for user {telegram_id} (reseller_id={reseller_id}, user_limit={user_limit})")
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

    def save_transaction(self, order_id, user_id, username, plan_name, amount, gateway, tracking_code, status="pending", account_name=None, account_comment=None, is_renewal=0, renew_sub_id=None, discount_code=None, receipt_image=None, receipt_file_type=None, reseller_id=None):
        """ذخیره تراکنش"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()

        try:
            cursor.execute("""
                INSERT OR REPLACE INTO transactions
                (order_id, user_id, username, plan_name, amount, gateway, tracking_code, account_name, account_comment, status, is_renewal, renew_sub_id, discount_code, receipt_image, receipt_photo_id, receipt_file_type, reseller_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (order_id, user_id, username, plan_name, amount, gateway, tracking_code, account_name, account_comment, status, 1 if is_renewal else 0, renew_sub_id, discount_code, receipt_image, receipt_image, receipt_file_type, reseller_id, now, now))
            conn.commit()
            logger.info(f"Transaction {order_id} saved (is_renewal={is_renewal}, reseller_id={reseller_id})")
            
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

    def revoke_transaction(self, tx_id: int, admin_name: str, admin_id: int = None, reason: str = "", rollback_sub_action: str = "keep") -> dict:
        """
        ابطال تراکنش توسط مدیر ارشد با ثبت تاریخچه و امکان رول‌بک اشتراک
        rollback_sub_action: 'keep', 'disable', 'delete'
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            tx = cursor.execute("SELECT * FROM transactions WHERE id=?", (tx_id,)).fetchone()
            if not tx:
                return {"success": False, "error": "تراکنش یافت نشد."}

            if tx["status"] == "revoked":
                return {"success": False, "error": "این تراکنش قبلاً باطل شده است."}

            old_status = tx["status"]
            now_iso = get_now_iso()

            # ۱. تغییر وضعیت تراکنش به revoked
            cursor.execute("""
                UPDATE transactions
                SET status='revoked', revoked_at=?, revoked_by=?, revoke_reason=?, updated_at=?
                WHERE id=?
            """, (now_iso, admin_name, reason, now_iso, tx_id))

            # ۲. ثبت لاگ حسابرسی
            cursor.execute("""
                INSERT INTO transaction_audit_logs 
                (transaction_id, admin_id, admin_name, action, field_name, old_value, new_value, reason, created_at)
                VALUES (?, ?, ?, 'revoke', 'status', ?, 'revoked', ?, ?)
            """, (tx_id, admin_id, admin_name, old_status, reason, now_iso))

            # ۳. یافتن اشتراک مرتبط
            sub_id = tx["subscription_id"]
            associated_sub = None
            if sub_id:
                associated_sub = cursor.execute("SELECT * FROM subscriptions WHERE id=?", (sub_id,)).fetchone()
            elif tx["user_id"] and tx["account_name"]:
                # جستجوی اشتراک بر اساس user_id و account_name
                associated_sub = cursor.execute(
                    "SELECT * FROM subscriptions WHERE telegram_id=? AND account_name=? ORDER BY id DESC LIMIT 1",
                    (tx["user_id"], tx["account_name"])
                ).fetchone()

            conn.commit()

            return {
                "success": True,
                "tx": dict(tx),
                "sub": dict(associated_sub) if associated_sub else None,
                "rollback_sub_action": rollback_sub_action
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def update_transaction_details(self, tx_id: int, admin_id: int, admin_name: str, amount: int = None, tracking_code: str = None, card_number: str = None, notes: str = None, reason: str = "") -> dict:
        """ویرایش مشخصات فیش با ثبت دقیق لاگ حسابرسی برای هر فیلد تغییر یافته"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            tx = cursor.execute("SELECT * FROM transactions WHERE id=?", (tx_id,)).fetchone()
            if not tx:
                return {"success": False, "error": "تراکنش یافت نشد."}

            now_iso = get_now_iso()
            changes = []

            fields_to_update = {}
            if amount is not None:
                try:
                    int_amt = int(amount)
                    if int_amt != tx["amount"]:
                        fields_to_update["amount"] = int_amt
                        changes.append(("amount", str(tx["amount"]), str(int_amt)))
                except Exception:
                    pass

            if tracking_code is not None and tracking_code.strip() != (tx["tracking_code"] or ""):
                fields_to_update["tracking_code"] = tracking_code.strip()
                changes.append(("tracking_code", tx["tracking_code"] or "", tracking_code.strip()))

            if card_number is not None and card_number.strip() != (tx["card_number"] or ""):
                fields_to_update["card_number"] = card_number.strip()
                changes.append(("card_number", tx["card_number"] or "", card_number.strip()))

            if notes is not None and notes.strip() != (tx["account_comment"] or ""):
                fields_to_update["account_comment"] = notes.strip()
                changes.append(("account_comment", tx["account_comment"] or "", notes.strip()))

            if not fields_to_update:
                return {"success": True, "message": "هیچ تغییری اعمال نشد."}

            fields_to_update["updated_at"] = now_iso
            set_clause = ", ".join([f"{k}=?" for k in fields_to_update.keys()])
            values = list(fields_to_update.values()) + [tx_id]

            cursor.execute(f"UPDATE transactions SET {set_clause} WHERE id=?", values)

            # ثبت لاگ حسابرسی برای هر تغییر
            for field, old_val, new_val in changes:
                cursor.execute("""
                    INSERT INTO transaction_audit_logs 
                    (transaction_id, admin_id, admin_name, action, field_name, old_value, new_value, reason, created_at)
                    VALUES (?, ?, ?, 'edit', ?, ?, ?, ?, ?)
                """, (tx_id, admin_id, admin_name, field, old_val, new_val, reason, now_iso))

            conn.commit()
            return {"success": True, "changes_count": len(changes)}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def soft_delete_transaction(self, tx_id: int, admin_id: int, admin_name: str, reason: str = "") -> dict:
        """حذف نرم تراکنش (آرشیو) با ثبت لاگ"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            tx = cursor.execute("SELECT * FROM transactions WHERE id=?", (tx_id,)).fetchone()
            if not tx:
                return {"success": False, "error": "تراکنش یافت نشد."}

            now_iso = get_now_iso()
            cursor.execute("UPDATE transactions SET is_deleted=1, updated_at=? WHERE id=?", (now_iso, tx_id))

            cursor.execute("""
                INSERT INTO transaction_audit_logs 
                (transaction_id, admin_id, admin_name, action, field_name, old_value, new_value, reason, created_at)
                VALUES (?, ?, ?, 'soft_delete', 'is_deleted', '0', '1', ?, ?)
            """, (tx_id, admin_id, admin_name, reason, now_iso))

            conn.commit()
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def get_transaction_audit_logs(self, tx_id: int) -> list:
        """دریافت لیست لاگ‌های حسابرسی یک تراکنش"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM transaction_audit_logs
            WHERE transaction_id=?
            ORDER BY id DESC
        """, (tx_id,))
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    # ═══════════════════════════════════════════════════════════════
    # مدیریت لاگ‌های ورود، خروج و امنیت نشست‌ها (Login & Session Logs)
    # ═══════════════════════════════════════════════════════════════

    def record_login_attempt(
        self,
        user_type: str,
        user_id: int,
        username: str,
        attempted_password: str = None,
        status: str = "success",
        failure_reason: str = None,
        ip_address: str = "127.0.0.1",
        user_agent: str = "",
        browser: str = "",
        device_os: str = "",
        session_token: str = ""
    ) -> int:
        """ثبت تلاش ورود به سیستم (موفق یا ناموفق)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("""
                INSERT INTO login_logs (
                    user_type, user_id, username, attempted_password, status, failure_reason,
                    ip_address, user_agent, browser, device_os, session_token,
                    login_at, last_active_at, is_active
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                user_type, user_id, username, attempted_password, status, failure_reason,
                ip_address, user_agent, browser, device_os, session_token,
                now, now, 1 if status == "success" else 0
            ))
            log_id = cursor.lastrowid
            conn.commit()
            return log_id
        except Exception as e:
            logger.error(f"Error recording login attempt: {e}")
            return 0
        finally:
            conn.close()

    def record_logout(self, session_token: str):
        """ثبت خروج از حساب و غیرفعال‌سازی نشست"""
        if not session_token:
            return
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("""
                UPDATE login_logs
                SET logout_at = ?, last_active_at = ?, is_active = 0
                WHERE session_token = ? AND is_active = 1
            """, (now, now, session_token))
            conn.commit()
        except Exception as e:
            logger.error(f"Error recording logout: {e}")
        finally:
            conn.close()

    def update_session_activity(self, session_token: str):
        """بروزرسانی زمان آخرین فعالیت نشست فعال"""
        if not session_token:
            return
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("""
                UPDATE login_logs
                SET last_active_at = ?
                WHERE session_token = ? AND is_active = 1
            """, (now, session_token))
            conn.commit()
        except Exception as e:
            pass
        finally:
            conn.close()

    def get_user_login_history(self, user_type: str, user_id: int, limit: int = 30) -> list:
        """دریافت سوابق ورود و نشست‌های یک کاربر یا مدیر"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT * FROM login_logs
                WHERE user_type = ? AND user_id = ?
                ORDER BY id DESC
                LIMIT ?
            """, (user_type, user_id, limit))
            rows = cursor.fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"Error getting user login history: {e}")
            return []
        finally:
            conn.close()

    def get_reseller_security_logs(self, reseller_id: int, username: str) -> dict:
        """دریافت سوابق کامل نشست‌ها و ورودهای ناموفق یک نماینده"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            # ۱. نشست‌های موفق
            cursor.execute("""
                SELECT * FROM login_logs
                WHERE user_type = 'reseller' AND user_id = ? AND status = 'success'
                ORDER BY id DESC LIMIT 20
            """, (reseller_id,))
            sessions = [dict(r) for r in cursor.fetchall()]

            # ۲. تلاش‌های ناموفق با این نام کاربری
            cursor.execute("""
                SELECT * FROM login_logs
                WHERE username = ? AND status = 'failed'
                ORDER BY id DESC LIMIT 20
            """, (username,))
            failed_attempts = [dict(r) for r in cursor.fetchall()]

            # ۳. وضعیت آنلاین بودن
            is_online = self.is_reseller_online(reseller_id)

            return {
                "sessions": sessions,
                "failed_attempts": failed_attempts,
                "is_online": is_online
            }
        except Exception as e:
            logger.error(f"Error getting reseller security logs: {e}")
            return {"sessions": [], "failed_attempts": [], "is_online": False}
        finally:
            conn.close()

    def is_reseller_online(self, reseller_id: int, threshold_minutes: int = 15) -> bool:
        """بررسی آنلاین بودن نماینده بر اساس آخرین فعالیت در چند دقیقه گذشته"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT last_active_at, login_at, is_active FROM login_logs
                WHERE user_type = 'reseller' AND user_id = ? AND is_active = 1
                ORDER BY id DESC LIMIT 1
            """, (reseller_id,))
            row = cursor.fetchone()
            if not row:
                return False

            last_time_str = row["last_active_at"] or row["login_at"]
            if not last_time_str:
                return False

            # محاسبه اختلاف زمانی با در نظر گرفتن منطقه زمانی تهران
            try:
                last_time = datetime.fromisoformat(last_time_str)
                now_tehran = datetime.now(TEHRAN_TZ)
                if last_time.tzinfo is None:
                    last_time = last_time.replace(tzinfo=TEHRAN_TZ)
                diff_seconds = abs((now_tehran - last_time).total_seconds())
                return (diff_seconds / 60) <= threshold_minutes
            except Exception as ex:
                logger.error(f"Error calculating reseller online diff: {ex}")
                return False
        except Exception as e:
            return False
        finally:
            conn.close()

    def get_all_failed_login_logs(self, limit: int = 50) -> list:
        """دریافت تمام تلاش‌های ناموفق ورود به سیستم برای مانیتورینگ امنیتی مدیر کل"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT * FROM login_logs
                WHERE status = 'failed'
                ORDER BY id DESC
                LIMIT ?
            """, (limit,))
            rows = cursor.fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"Error getting all failed login logs: {e}")
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

    def create_ticket(self, telegram_id, subject, message, reseller_id=None):
        """ایجاد تیکت پشتیبانی جدید با قابلیت انتساب به نماینده"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("""
                INSERT INTO support_tickets (telegram_id, subject, message, status, reseller_id, created_at, updated_at)
                VALUES (?, ?, ?, 'open', ?, ?, ?)
            """, (telegram_id, subject, message, reseller_id, now, now))
            conn.commit()
            return {"success": True, "ticket_id": cursor.lastrowid}
        except Exception as e:
            logger.error(f"Error creating ticket: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def reply_ticket(self, ticket_id, admin_reply):
        """پاسخ ادمین یا نماینده به تیکت"""
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

    def get_all_tickets(self, status=None, reseller_id=None):
        """دریافت تمام تیکت‌ها با فیلتر وضعیت و نماینده"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            query = "SELECT * FROM support_tickets WHERE 1=1"
            params = []
            if status:
                query += " AND status = ?"
                params.append(status)
            if reseller_id is not None:
                query += " AND reseller_id = ?"
                params.append(reseller_id)
            query += " ORDER BY created_at DESC"
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting all tickets: {e}")
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

        cursor.execute("SELECT COUNT(*) FROM subscriptions WHERE reseller_id=? AND is_online=1", (reseller_id,))
        online_users = cursor.fetchone()[0]
        
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
            "online_users": online_users,
            "total_purchases": total_purchases,
            "total_used_gb": round(total_used_gb, 2),
            "total_limit_gb": round(total_limit_gb, 2),
        }

    def get_reseller_subscription(self, reseller_id: int, sub_id: int):
        """دریافت اطلاعات یک اشتراک متعلق به نماینده"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM subscriptions WHERE id=? AND reseller_id=?", (sub_id, reseller_id))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    def update_reseller_subscription(self, reseller_id: int, sub_id: int, account_name: str, phone_number: str = None, comment: str = None):
        """ویرایش مشخصات مشتری نماینده"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("""
                UPDATE subscriptions
                SET account_name=?, phone_number=?, account_comment=?, updated_at=?
                WHERE id=? AND reseller_id=?
            """, (account_name.strip(), phone_number.strip() if phone_number else None, comment.strip() if comment else None, now, sub_id, reseller_id))
            conn.commit()
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def toggle_reseller_subscription(self, reseller_id: int, sub_id: int, enable: bool = None):
        """فعال یا غیرفعال کردن مشتری نماینده بدون کسر یا بازگشت هزینه"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("SELECT status FROM subscriptions WHERE id=? AND reseller_id=?", (sub_id, reseller_id))
            row = cursor.fetchone()
            if not row:
                return {"success": False, "error": "اشتراک یافت نشد."}
            
            if enable is None:
                new_status = "disabled" if row["status"] == "active" else "active"
            else:
                new_status = "active" if enable else "disabled"
            
            cursor.execute("UPDATE subscriptions SET status=?, updated_at=? WHERE id=? AND reseller_id=?",
                           (new_status, now, sub_id, reseller_id))
            conn.commit()
            return {"success": True, "status": new_status}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def renew_reseller_subscription(self, reseller_id: int, sub_id: int, plan_id: str, plan_name: str,
                                    cost: int, data_limit: float, duration: int, renewal_type: str = "reset_and_replaced"):
        """تمدید اشتراک مشتری توسط نماینده با کسر هزینه از کیف پول"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            # بررسی موجودی
            cursor.execute("SELECT balance FROM resellers WHERE id=?", (reseller_id,))
            res_row = cursor.fetchone()
            if not res_row or res_row["balance"] < cost:
                return {"success": False, "error": "موجودی کیف پول نماینده برای تمدید این پلن کافی نیست."}

            cursor.execute("SELECT * FROM subscriptions WHERE id=? AND reseller_id=?", (sub_id, reseller_id))
            sub = cursor.fetchone()
            if not sub:
                return {"success": False, "error": "اشتراک مورد نظر یافت نشد."}

            # ۱. کسر هزینه از کیف پول
            cursor.execute("UPDATE resellers SET balance = balance - ?, updated_at=? WHERE id=?", (cost, now, reseller_id))

            # ۲. ثبت تراکنش تمدید در تاریخچه مالی نماینده
            cursor.execute("""
                INSERT INTO reseller_transactions (reseller_id, type, amount, plan_name, account_name, description, created_at)
                VALUES (?, 'renewal', ?, ?, ?, ?, ?)
            """, (reseller_id, cost, plan_name, sub["account_name"], f"تمدید اشتراک «{sub['account_name']}» با پلن {plan_name}", now))

            # ۳. به‌روزرسانی مشخصات اشتراک
            cursor.execute("""
                UPDATE subscriptions
                SET plan_id=?, plan_name=?, data_limit=?, duration=?, status='active', updated_at=?, cost_paid=?
                WHERE id=? AND reseller_id=?
            """, (plan_id, plan_name, data_limit, duration, now, cost, sub_id, reseller_id))

            conn.commit()
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def calculate_reseller_refund(self, reseller_id: int, sub_id: int):
        """
        محاسبه شرایط و درصد استرداد وجه حذف مشتری بر اساس قوانین:
        - تا ۱۲ ساعت پس از ساخت: ۱۰۰٪ مبلغ
        - بین ۱۲ تا ۲۴ ساعت پس از ساخت: ۹۰٪ مبلغ
        - بیش از ۲۴ ساعت پس از ساخت: ۰٪ مبلغ
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM subscriptions WHERE id=? AND reseller_id=?", (sub_id, reseller_id))
        sub = cursor.fetchone()
        conn.close()

        if not sub:
            return None

        created_str = sub["created_at"] or get_now_iso()
        try:
            clean = str(created_str).strip().replace("Z", "")
            created_dt = datetime.fromisoformat(clean)
            if created_dt.tzinfo is not None:
                created_dt = created_dt.astimezone(TEHRAN_TZ).replace(tzinfo=None)
        except Exception:
            created_dt = get_now_naive()

        now_dt = get_now_naive()
        elapsed_seconds = max(0.0, (now_dt - created_dt).total_seconds())
        elapsed_hours = elapsed_seconds / 3600.0

        if elapsed_hours <= 12.0:
            refund_percent = 100
        elif elapsed_hours <= 24.0:
            refund_percent = 90
        else:
            refund_percent = 0

        cost_paid = sub["cost_paid"] or 0
        if cost_paid <= 0:
            # در صورتی که فیلد هزینه در نسخه‌های قدیمی ثبت نشده بود، از پلن اولیه بازیابی شود
            try:
                plan_price = 0
                if sub["plan_id"]:
                    p_id = sub["plan_id"]
                    # تلاش برای پیدا کردن قیمت
                    res_row = cursor.execute("SELECT discount_percent FROM resellers WHERE id=?", (reseller_id,)).fetchone()
                    disc = res_row["discount_percent"] if res_row else 20
                    # تخمین هزینه پرداختی
                    cost_paid = 0
            except Exception:
                pass

        refund_amount = int((cost_paid * refund_percent) / 100)

        hours_int = int(elapsed_hours)
        minutes_int = int((elapsed_hours - hours_int) * 60)
        time_passed_text = f"{hours_int} ساعت و {minutes_int} دقیقه پیش" if hours_int > 0 else f"{minutes_int} دقیقه پیش"

        return {
            "sub_id": sub_id,
            "account_name": sub["account_name"] or "بدون نام",
            "created_at": created_str,
            "elapsed_hours": round(elapsed_hours, 1),
            "time_passed_text": time_passed_text,
            "refund_percent": refund_percent,
            "cost_paid": cost_paid,
            "refund_amount": refund_amount,
        }

    def delete_reseller_subscription(self, reseller_id: int, sub_id: int):
        """حذف مشتری نماینده با استرداد هوشمند وجه طبق قوانین ۱۲ و ۲۴ ساعته"""
        refund_info = self.calculate_reseller_refund(reseller_id, sub_id)
        if not refund_info:
            return {"success": False, "error": "اشتراک مورد نظر یافت نشد."}

        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            refund_amount = refund_info["refund_amount"]
            refund_percent = refund_info["refund_percent"]
            account_name = refund_info["account_name"]

            # ۱. در صورت تعلق استرداد وجه، موجودی نماینده افزایش یافته و تراکنش ثبت می‌شود
            if refund_amount > 0:
                cursor.execute("UPDATE resellers SET balance = balance + ?, updated_at=? WHERE id=?", (refund_amount, now, reseller_id))
                cursor.execute("""
                    INSERT INTO reseller_transactions (reseller_id, type, amount, plan_name, account_name, description, created_at)
                    VALUES (?, 'refund', ?, 'استرداد وجه', ?, ?, ?)
                """, (reseller_id, refund_amount, account_name, f"استرداد وجه {refund_percent}٪ بابت حذف اشتراک «{account_name}» ({refund_info['time_passed_text']})", now))

            # ۲. حذف فیزیکی اشتراک از جدول محلی
            cursor.execute("DELETE FROM subscriptions WHERE id=? AND reseller_id=?", (sub_id, reseller_id))
            conn.commit()

            return {
                "success": True,
                "refund_amount": refund_amount,
                "refund_percent": refund_percent,
                "time_passed_text": refund_info["time_passed_text"]
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    # ─── استرداد وجه و حذف هوشمند اشتراک مشتریان برای مدیران (Customer Refund & Delete) ───

    def calculate_customer_refund(self, sub_id: int):
        """
        محاسبه شرایط و درصد استرداد وجه حذف اشتراک مشتری توسط مدیران:
        - تا ۱۲ ساعت پس از ساخت: ۱۰۰٪ مبلغ
        - بین ۱۲ تا ۲۴ ساعت پس از ساخت: ۹۰٪ مبلغ
        - بیش از ۲۴ ساعت پس از ساخت: ۰٪ مبلغ
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM subscriptions WHERE id=?", (sub_id,))
        sub = cursor.fetchone()
        if not sub:
            conn.close()
            return None

        created_str = sub["created_at"] or get_now_iso()
        try:
            clean = str(created_str).strip().replace("Z", "")
            created_dt = datetime.fromisoformat(clean)
            if created_dt.tzinfo is not None:
                created_dt = created_dt.astimezone(TEHRAN_TZ).replace(tzinfo=None)
        except Exception:
            created_dt = get_now_naive()

        now_dt = get_now_naive()
        elapsed_seconds = max(0.0, (now_dt - created_dt).total_seconds())
        elapsed_hours = elapsed_seconds / 3600.0

        if elapsed_hours <= 12.0:
            refund_percent = 100
        elif elapsed_hours <= 24.0:
            refund_percent = 90
        else:
            refund_percent = 0

        cost_paid = sub["cost_paid"] or 0
        user_id = sub["telegram_id"] if ("telegram_id" in sub.keys() and sub["telegram_id"]) else None
        account_name = sub["account_name"] or "بدون نام"

        if cost_paid <= 0:
            # بررسی مبلغ از آخرین تراکنش موفق کاربر
            tx = cursor.execute("""
                SELECT amount FROM transactions 
                WHERE (account_name=? OR user_id=?) AND status IN ('approved', 'completed') 
                ORDER BY id DESC LIMIT 1
            """, (account_name, user_id)).fetchone()
            if tx and tx["amount"]:
                cost_paid = tx["amount"]

        conn.close()

        refund_amount = int((cost_paid * refund_percent) / 100)

        hours_int = int(elapsed_hours)
        minutes_int = int((elapsed_hours - hours_int) * 60)
        time_passed_text = f"{hours_int} ساعت و {minutes_int} دقیقه پیش" if hours_int > 0 else f"{minutes_int} دقیقه پیش"

        return {
            "sub_id": sub_id,
            "account_name": account_name,
            "user_id": user_id,
            "created_at": created_str,
            "elapsed_hours": round(elapsed_hours, 1),
            "time_passed_text": time_passed_text,
            "refund_percent": refund_percent,
            "cost_paid": cost_paid,
            "refund_amount": refund_amount,
            "hidify_uuid": sub["hidify_uuid"]
        }

    def delete_customer_subscription(self, sub_id: int, refund_to_customer: bool = True, admin_name: str = "مدیر"):
        """حذف مشتری توسط مدیر با قابلیت استرداد مستقیم وجه به کیف پول کاربر تلگرام"""
        refund_info = self.calculate_customer_refund(sub_id)
        if not refund_info:
            return {"success": False, "error": "اشتراک مورد نظر یافت نشد."}

        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            refund_amount = refund_info["refund_amount"]
            refund_percent = refund_info["refund_percent"]
            account_name = refund_info["account_name"]
            user_id = refund_info["user_id"]
            hidify_uuid = refund_info["hidify_uuid"]

            # ۱. در صورت تایید استرداد و وجود مبلغ، کیف پول کاربر شارژ می‌شود
            refund_done = False
            if refund_to_customer and refund_amount > 0 and user_id:
                try:
                    self.add_wallet_balance(
                        user_id,
                        refund_amount,
                        f"استرداد وجه {refund_percent}٪ بابت حذف اشتراک «{account_name}» ({refund_info['time_passed_text']}) توسط {admin_name}",
                        tx_type="refund"
                    )
                    refund_done = True
                except Exception as ex:
                    logger.error(f"Error adding refund to wallet for user {user_id}: {ex}")

            # ۲. حذف فیزیکی اشتراک از دیتابیس
            cursor.execute("DELETE FROM subscriptions WHERE id=?", (sub_id,))
            conn.commit()

            return {
                "success": True,
                "refund_done": refund_done,
                "refund_amount": refund_amount if refund_done else 0,
                "refund_percent": refund_percent,
                "time_passed_text": refund_info["time_passed_text"],
                "account_name": account_name,
                "hidify_uuid": hidify_uuid,
                "user_id": user_id
            }
        except Exception as e:
            logger.error(f"Error deleting customer subscription {sub_id}: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    # ─── متدهای تکمیلی ربات اختصاصی و هوش مالی نماینده (White-Label & Multi-Bot) ───

    def get_active_reseller_bots(self) -> list:
        """لیست تمام نمایندگان دارای ربات فعال و توکن معتبر"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT * FROM resellers 
                WHERE bot_token IS NOT NULL AND TRIM(bot_token) != '' 
                  AND is_bot_active = 1 AND status = 'active'
                ORDER BY id ASC
            """)
            rows = cursor.fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"Error fetching active reseller bots: {e}")
            return []
        finally:
            conn.close()

    def get_reseller_by_bot_token(self, bot_token: str):
        """جستجوی نماینده بر اساس توکن ربات"""
        if not bot_token:
            return None
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT * FROM resellers WHERE bot_token = ?", (bot_token.strip(),))
            row = cursor.fetchone()
            return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error finding reseller by bot token: {e}")
            return None
        finally:
            conn.close()

    def get_reseller_by_telegram_id(self, telegram_id: int):
        """جستجوی نماینده بر اساس تلگرام آیدی"""
        if not telegram_id:
            return None
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT * FROM resellers WHERE telegram_id = ?", (int(telegram_id),))
            row = cursor.fetchone()
            return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error finding reseller by telegram id: {e}")
            return None
        finally:
            conn.close()

    def update_reseller_bot_settings(self, reseller_id: int, **kwargs) -> dict:
        """بروزرسانی مشخصات و تنظیمات ربات اختصاصی نماینده"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        kwargs["updated_at"] = now
        try:
            allowed_fields = [
                "bot_token", "bot_username", "channel_id", "brand_name",
                "start_message", "support_username", "card_number", "card_holder",
                "bank_name", "is_bot_active", "tier_level", "auto_approval", "updated_at"
            ]
            fields = []
            params = []
            for k, v in kwargs.items():
                if k in allowed_fields:
                    fields.append(f"{k} = ?")
                    params.append(v)
            if not fields:
                return {"success": True}
            params.append(reseller_id)
            cursor.execute(f"UPDATE resellers SET {', '.join(fields)} WHERE id = ?", params)
            conn.commit()
            return {"success": True}
        except Exception as e:
            logger.error(f"Error updating reseller bot settings: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def get_reseller_users(self, reseller_id: int) -> list:
        """دریافت لیست کاربران اختصاصی ثبت‌نام شده از ربات یا کانال نماینده"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT u.*, 
                       (SELECT COUNT(*) FROM subscriptions WHERE telegram_id = u.telegram_id AND reseller_id = ?) as sub_count
                FROM users u
                WHERE u.reseller_id = ?
                ORDER BY u.created_at DESC
            """, (reseller_id, reseller_id))
            rows = cursor.fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"Error getting reseller users: {e}")
            return []
        finally:
            conn.close()

    def get_reseller_financial_summary(self, reseller_id: int) -> dict:
        """محاسبه دقیق سود و تراز مالی نماینده (سود حاصل از تخفیف همکاری نسبت به فروش خرد)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            # ۱. مجموع خریدهای عمده نماینده
            cursor.execute("""
                SELECT COALESCE(SUM(amount), 0) FROM reseller_transactions 
                WHERE reseller_id = ? AND type = 'purchase'
            """, (reseller_id,))
            total_wholesale_cost = cursor.fetchone()[0] or 0

            # ۲. مجموع واریزی‌ها / شارژ کیف‌پول
            cursor.execute("""
                SELECT COALESCE(SUM(amount), 0) FROM reseller_transactions 
                WHERE reseller_id = ? AND type = 'deposit'
            """, (reseller_id,))
            total_deposited = cursor.fetchone()[0] or 0

            # ۳. تخفیف و موجودی نماینده
            cursor.execute("SELECT discount_percent, balance, name FROM resellers WHERE id = ?", (reseller_id,))
            r_info = cursor.fetchone()
            discount_pct = r_info["discount_percent"] if r_info else 20
            current_balance = r_info["balance"] if r_info else 0
            reseller_name = r_info["name"] if r_info else "همکار"

            # ۴. تخمین ارزش ریالی قیمت خرده‌فروشی
            if discount_pct < 100 and discount_pct > 0:
                estimated_retail_value = int(total_wholesale_cost / (1.0 - (discount_pct / 100.0)))
            else:
                estimated_retail_value = total_wholesale_cost
            estimated_profit = max(0, estimated_retail_value - total_wholesale_cost)

            return {
                "reseller_name": reseller_name,
                "total_wholesale_cost": total_wholesale_cost,
                "total_deposited": total_deposited,
                "estimated_retail_value": estimated_retail_value,
                "estimated_profit": estimated_profit,
                "discount_percent": discount_pct,
                "current_balance": current_balance,
            }
        except Exception as e:
            logger.error(f"Error calculating reseller financial summary: {e}")
            return {
                "reseller_name": "",
                "total_wholesale_cost": 0,
                "total_deposited": 0,
                "estimated_retail_value": 0,
                "estimated_profit": 0,
                "discount_percent": 0,
                "current_balance": 0,
            }
        finally:
            conn.close()

    # ─── مدیریت دامنه و برندینگ نماینده (Custom Domain & Branding) ───

    def get_reseller_by_domain(self, domain: str):
        """یافتن نماینده بر اساس دامنه اختصاصی پنل یا دامنه اختصاصی آموزش‌ها"""
        if not domain:
            return None
        clean_domain = domain.split(":")[0].strip().lower()
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT * FROM resellers 
                WHERE (LOWER(custom_domain) = ? OR LOWER(tutorial_domain) = ?) AND status = 'active'
            """, (clean_domain, clean_domain))
            row = cursor.fetchone()
            return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error fetching reseller by domain: {e}")
            return None
        finally:
            conn.close()

    def update_reseller_branding(self, reseller_id: int, **kwargs) -> dict:
        """بروزرسانی مشخصات هویت بصری، لوگو، دامنه و عنوان فروشگاه نماینده"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        kwargs["updated_at"] = now
        try:
            allowed = ["custom_domain", "tutorial_domain", "logo_url", "favicon_url", "brand_title", "primary_color", "footer_text", "updated_at"]
            fields = []
            params = []
            for k, v in kwargs.items():
                if k in allowed:
                    fields.append(f"{k} = ?")
                    params.append(v.strip() if isinstance(v, str) else v)
            if not fields:
                return {"success": True}
            params.append(reseller_id)
            cursor.execute(f"UPDATE resellers SET {', '.join(fields)} WHERE id = ?", params)
            conn.commit()
            return {"success": True}
        except sqlite3.IntegrityError:
            return {"success": False, "error": "این دامنه قبلاً توسط نماینده دیگری ثبت شده است."}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    # ─── مدیریت کارت‌های بانکی اختصاصی نماینده (Reseller Cards) ───

    def get_reseller_cards(self, reseller_id: int) -> list:
        """لیست تمام کارت‌های بانکی ثبت‌شده توسط نماینده"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT * FROM reseller_cards WHERE reseller_id = ? ORDER BY id DESC", (reseller_id,))
            return [dict(r) for r in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting reseller cards: {e}")
            return []
        finally:
            conn.close()

    def get_active_reseller_card(self, reseller_id: int):
        """دریافت کارت بانکی فعال نماینده جهت پرداخت"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT * FROM reseller_cards WHERE reseller_id = ? AND is_active = 1 ORDER BY id DESC LIMIT 1", (reseller_id,))
            row = cursor.fetchone()
            if row:
                return dict(row)
            # بازگشت به کارت ثبت‌شده در پروفایل اصلی
            cursor.execute("SELECT card_number, card_holder, bank_name FROM resellers WHERE id = ?", (reseller_id,))
            r_row = cursor.fetchone()
            if r_row and r_row["card_number"]:
                return {
                    "card_number": r_row["card_number"],
                    "card_holder": r_row.get("card_holder") or "",
                    "bank_name": r_row.get("bank_name") or "بانک"
                }
            return None
        except Exception as e:
            logger.error(f"Error getting active reseller card: {e}")
            return None
        finally:
            conn.close()

    def add_reseller_card(self, reseller_id: int, card_number: str, card_holder: str, bank_name: str, daily_limit: int = 50000000) -> dict:
        """افزودن کارت بانکی جدید برای نماینده"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("""
                INSERT INTO reseller_cards (reseller_id, card_number, card_holder, bank_name, daily_limit, is_active, created_at)
                VALUES (?, ?, ?, ?, ?, 1, ?)
            """, (reseller_id, card_number.strip(), card_holder.strip(), bank_name.strip(), daily_limit, now))
            card_id = cursor.lastrowid
            conn.commit()
            return {"success": True, "card_id": card_id}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def delete_reseller_card(self, card_id: int, reseller_id: int) -> dict:
        """حذف کارت بانکی نماینده"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("DELETE FROM reseller_cards WHERE id = ? AND reseller_id = ?", (card_id, reseller_id))
            conn.commit()
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def toggle_reseller_card(self, card_id: int, reseller_id: int) -> dict:
        """فعال یا غیرفعال کردن کارت بانکی نماینده"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT is_active FROM reseller_cards WHERE id = ? AND reseller_id = ?", (card_id, reseller_id))
            row = cursor.fetchone()
            if not row:
                return {"success": False, "error": "کارت یافت نشد."}
            new_st = 0 if row["is_active"] else 1
            cursor.execute("UPDATE reseller_cards SET is_active = ? WHERE id = ? AND reseller_id = ?", (new_st, card_id, reseller_id))
            conn.commit()
            return {"success": True, "is_active": new_st}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    # ─── مدیریت کدهای تخفیف اختصاصی نماینده (Reseller Discount Codes) ───

    def get_reseller_discount_codes(self, reseller_id: int) -> list:
        """لیست کدهای تخفیف تعریف‌شده توسط نماینده"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT * FROM reseller_discount_codes WHERE reseller_id = ? ORDER BY id DESC", (reseller_id,))
            return [dict(r) for r in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error fetching reseller discount codes: {e}")
            return []
        finally:
            conn.close()

    def create_reseller_discount_code(self, reseller_id: int, code: str, discount_percent: int = 0,
                                      discount_amount: int = 0, max_uses: int = 0, valid_until: str = None) -> dict:
        """ایجاد کد تخفیف جدید برای مشتریان نماینده"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            clean_code = code.strip().upper()
            cursor.execute("SELECT id FROM reseller_discount_codes WHERE reseller_id = ? AND code = ?", (reseller_id, clean_code))
            if cursor.fetchone():
                return {"success": False, "error": "این کد تخفیف قبلاً برای شما ثبت شده است."}

            cursor.execute("""
                INSERT INTO reseller_discount_codes 
                (reseller_id, code, discount_percent, discount_amount, max_uses, used_count, valid_until, is_active, created_at)
                VALUES (?, ?, ?, ?, ?, 0, ?, 1, ?)
            """, (reseller_id, clean_code, int(discount_percent or 0), int(discount_amount or 0), int(max_uses or 0), valid_until, now))
            code_id = cursor.lastrowid
            conn.commit()
            return {"success": True, "code_id": code_id}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def validate_reseller_discount_code(self, reseller_id: int, code: str, order_amount: int = 0) -> dict:
        """اعتبارسنجی و محاسبه تخفیف برای مشتری نماینده"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT * FROM reseller_discount_codes 
                WHERE reseller_id = ? AND code = ? AND is_active = 1
            """, (reseller_id, code.strip().upper()))
            row = cursor.fetchone()
            if not row:
                return {"valid": False, "error": "کد تخفیف نامعتبر است."}

            d = dict(row)
            if d.get("max_uses", 0) > 0 and d.get("used_count", 0) >= d.get("max_uses"):
                return {"valid": False, "error": "ظرفیت استفاده از این کد تخفیف به پایان رسیده است."}

            if d.get("valid_until"):
                try:
                    exp = datetime.fromisoformat(d["valid_until"])
                    if datetime.now() > exp:
                        return {"valid": False, "error": "مهلت استفاده از این کد تخفیف منقضی شده است."}
                except Exception:
                    pass

            pct = d.get("discount_percent", 0)
            fix_amt = d.get("discount_amount", 0)
            calculated_discount = 0
            if pct > 0:
                calculated_discount = int((order_amount * pct) / 100)
            elif fix_amt > 0:
                calculated_discount = min(order_amount, fix_amt)

            return {
                "valid": True,
                "discount_code": d["code"],
                "discount_amount": calculated_discount,
                "final_amount": max(0, order_amount - calculated_discount)
            }
        except Exception as e:
            return {"valid": False, "error": str(e)}
        finally:
            conn.close()

    def delete_reseller_discount_code(self, code_id: int, reseller_id: int) -> dict:
        """حذف کد تخفیف نماینده"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("DELETE FROM reseller_discount_codes WHERE id = ? AND reseller_id = ?", (code_id, reseller_id))
            conn.commit()
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def toggle_reseller_discount_code(self, code_id: int, reseller_id: int) -> dict:
        """فعال یا غیرفعال کردن کد تخفیف نماینده"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT is_active FROM reseller_discount_codes WHERE id = ? AND reseller_id = ?", (code_id, reseller_id))
            row = cursor.fetchone()
            if not row:
                return {"success": False, "error": "کد تخفیف یافت نشد."}
            new_st = 0 if row["is_active"] else 1
            cursor.execute("UPDATE reseller_discount_codes SET is_active = ? WHERE id = ? AND reseller_id = ?", (new_st, code_id, reseller_id))
            conn.commit()
            return {"success": True, "is_active": new_st}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    # ─── مدیریت تیم و زیرمدیران نماینده (Reseller Team & Sub-Admins) ───

    def get_reseller_team_members(self, reseller_id: int) -> list:
        """لیست مدیران و کارمندان زیرمجموعه نماینده"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT * FROM admin_users WHERE reseller_id = ? ORDER BY id ASC", (reseller_id,))
            return [dict(r) for r in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting reseller team members: {e}")
            return []
        finally:
            conn.close()

    def create_reseller_team_member(self, reseller_id: int, username: str, password: str,
                                    display_name: str, role: str = "support", phone: str = None,
                                    share_percent: int = 0) -> dict:
        """ایجاد مدیر زیرمجموعه جدید برای نماینده با نقش‌های partner, finance, support"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        password_hash = self.hash_password(password)
        try:
            clean_username = username.strip().lower()
            cursor.execute("SELECT id FROM admin_users WHERE username = ?", (clean_username,))
            if cursor.fetchone():
                return {"success": False, "error": "این نام کاربری قبلاً در سیستم ثبت شده است."}

            permissions = "all"
            if role == "support":
                permissions = "tickets,users,subscriptions"
            elif role == "finance":
                permissions = "payments,transactions,reports"
            elif role == "partner":
                permissions = "all"

            cursor.execute("""
                INSERT INTO admin_users 
                (username, password_hash, display_name, role, permissions, is_active, created_at, phone, share_percent, reseller_id)
                VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
            """, (clean_username, password_hash, display_name.strip(), role, permissions, now, phone.strip() if phone else None, int(share_percent or 0), reseller_id))
            member_id = cursor.lastrowid
            conn.commit()
            return {"success": True, "member_id": member_id}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def update_reseller_team_member(self, member_id: int, reseller_id: int, **kwargs) -> dict:
        """ویرایش مشخصات مدیر زیرمجموعه نماینده"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            allowed = ["display_name", "role", "phone", "share_percent", "is_active"]
            fields = []
            params = []
            for k, v in kwargs.items():
                if k == "password" and v:
                    fields.append("password_hash = ?")
                    params.append(self.hash_password(v))
                elif k in allowed:
                    fields.append(f"{k} = ?")
                    params.append(v)
            if not fields:
                return {"success": True}
            params.extend([member_id, reseller_id])
            cursor.execute(f"UPDATE admin_users SET {', '.join(fields)} WHERE id = ? AND reseller_id = ?", params)
            conn.commit()
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def delete_reseller_team_member(self, member_id: int, reseller_id: int) -> dict:
        """حذف مدیر زیرمجموعه نماینده"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("DELETE FROM admin_users WHERE id = ? AND reseller_id = ?", (member_id, reseller_id))
            conn.commit()
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def toggle_reseller_team_member(self, member_id: int, reseller_id: int) -> dict:
        """تغییر وضعیت فعال/غیرفعال مدیر زیرمجموعه نماینده"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT is_active FROM admin_users WHERE id = ? AND reseller_id = ?", (member_id, reseller_id))
            row = cursor.fetchone()
            if not row:
                return {"success": False, "error": "مدیر یافت نشد."}
            new_st = 0 if row["is_active"] else 1
            cursor.execute("UPDATE admin_users SET is_active = ? WHERE id = ? AND reseller_id = ?", (new_st, member_id, reseller_id))
            conn.commit()
            return {"success": True, "is_active": new_st}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

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

    def get_active_bank_cards(self):
        """لیست کارت‌های بانکی فعال"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM bank_cards WHERE is_active=1 ORDER BY created_at DESC")
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
                          telegram_id: int = None, phone: str = None, share_percent: int = 0) -> dict:
        """افزودن مدیر جدید با نقش و دسترسی‌های مشخص، آیدی تلگرام، شماره تماس و درصد شراکت"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        password_hash = self.hash_password(password)
        try:
            cursor.execute("""
                INSERT INTO admin_users (username, password_hash, display_name, role, permissions, is_active, created_at, telegram_id, phone, share_percent, debt_balance)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """, (username.strip(), password_hash, display_name.strip(), role, permissions, 1 if is_active else 0, now, telegram_id, phone.strip() if phone else None, int(share_percent or 0)))
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
        """ویرایش اطلاعات، نقش، دسترسی‌ها و درصد شراکت یک مدیر"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            fields = []
            params = []
            for key, val in kwargs.items():
                if key == "password" and val:
                    fields.append("password_hash=?")
                    params.append(self.hash_password(val))
                elif key in ["username", "display_name", "role", "permissions", "is_active", "telegram_id", "phone", "custom_avatar", "share_percent", "debt_balance"]:
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

    def update_admin_profile(self, admin_id: int, username: str, password: str = None, display_name: str = None, telegram_id: int = None, phone: str = None) -> dict:
        """تغییر مشخصات فردی، یوزرنیم، آیدی تلگرام، شماره تماس و پسورد مدیر فعال"""
        kwargs = {"username": username}
        if display_name:
            kwargs["display_name"] = display_name
        if telegram_id is not None:
            kwargs["telegram_id"] = telegram_id
        if phone is not None:
            kwargs["phone"] = phone
        if password and len(password.strip()) > 0:
            kwargs["password"] = password.strip()
        return self.update_admin_user(admin_id, **kwargs)

    # ═══════════════════════════════════════════════════════════════════════
    # حسابداری بدهی مدیران و شرکای تجاری (Admin & Partner Debts & Ledger)
    # ═══════════════════════════════════════════════════════════════════════

    def record_admin_cash_sale(self, admin_id: int, customer_name: str, plan_name: str, total_amount: int, share_percent: int = 0, created_by: int = None, description: str = "") -> dict:
        """ثبت فروش نقدی توسط مدیر/شریک، محاسبه درصد سهم شراکت و ثبت بدهی به مدیریت"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            # دریافت اطلاعات مدیر
            cursor.execute("SELECT username, display_name, role, share_percent, debt_balance FROM admin_users WHERE id=?", (admin_id,))
            admin_row = cursor.fetchone()
            if not admin_row:
                return {"success": False, "error": "مدیر یافت نشد."}

            admin_dict = dict(admin_row)
            username = admin_dict.get("username", f"admin_{admin_id}")
            effective_share_percent = int(share_percent if share_percent is not None else admin_dict.get("share_percent", 0))
            
            # محاسبه سهم شراکت و مبلغ بدهی به مدیریت
            share_amount = int(total_amount * (effective_share_percent / 100)) if effective_share_percent > 0 else 0
            debt_amount = total_amount - share_amount

            # ثبت در جدول لاگ بدهی
            cursor.execute("""
                INSERT INTO admin_debts (admin_id, admin_username, customer_name, plan_name, total_amount, share_percent, share_amount, debt_amount, type, description, created_by, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'cash_sale', ?, ?, ?)
            """, (admin_id, username, customer_name, plan_name, total_amount, effective_share_percent, share_amount, debt_amount, description, created_by or admin_id, now))

            # افزایش مانده بدهی مدیر
            new_debt_balance = (admin_dict.get("debt_balance") or 0) + debt_amount
            cursor.execute("UPDATE admin_users SET debt_balance=? WHERE id=?", (new_debt_balance, admin_id))
            conn.commit()

            return {
                "success": True,
                "total_amount": total_amount,
                "share_percent": effective_share_percent,
                "share_amount": share_amount,
                "debt_amount": debt_amount,
                "new_debt_balance": new_debt_balance
            }
        except Exception as e:
            logger.error(f"Error recording admin cash sale: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def settle_admin_debt(self, admin_id: int, amount: int, description: str, settled_by: int) -> dict:
        """ثبت تسویه حساب نقدی یا واریزی مدیر/شریک و کاهش بدهی"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("SELECT username, debt_balance FROM admin_users WHERE id=?", (admin_id,))
            admin_row = cursor.fetchone()
            if not admin_row:
                return {"success": False, "error": "مدیر یافت نشد."}

            admin_dict = dict(admin_row)
            username = admin_dict.get("username", f"admin_{admin_id}")
            current_debt = admin_dict.get("debt_balance") or 0
            settle_amount = int(amount)

            # ثبت تراکنش تسویه در جدول بدهی‌ها
            cursor.execute("""
                INSERT INTO admin_debts (admin_id, admin_username, customer_name, plan_name, total_amount, share_percent, share_amount, debt_amount, type, description, created_by, created_at)
                VALUES (?, ?, '-', 'تسویه حساب بدهی', ?, 0, 0, ?, 'settlement', ?, ?, ?)
            """, (admin_id, username, settle_amount, -settle_amount, description, settled_by, now))

            # کاهش مانده بدهی
            new_debt = max(0, current_debt - settle_amount)
            cursor.execute("UPDATE admin_users SET debt_balance=? WHERE id=?", (new_debt, admin_id))
            conn.commit()

            return {"success": True, "settled_amount": settle_amount, "remaining_debt": new_debt}
        except Exception as e:
            logger.error(f"Error settling admin debt: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def get_admin_debts(self, admin_id: int = None, limit: int = 100) -> list:
        """دریافت سوابق فروش‌های نقدی، سهم شراکت و تسویه‌حساب‌های مدیران"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            if admin_id:
                cursor.execute("""
                    SELECT d.*, u.display_name as admin_name, u.role as admin_role
                    FROM admin_debts d
                    LEFT JOIN admin_users u ON d.admin_id = u.id
                    WHERE d.admin_id=?
                    ORDER BY d.id DESC LIMIT ?
                """, (admin_id, limit))
            else:
                cursor.execute("""
                    SELECT d.*, u.display_name as admin_name, u.role as admin_role
                    FROM admin_debts d
                    LEFT JOIN admin_users u ON d.admin_id = u.id
                    ORDER BY d.id DESC LIMIT ?
                """, (limit,))
            rows = cursor.fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"Error getting admin debts: {e}")
            return []
        finally:
            conn.close()

    def get_admins_accounting_summary(self, admin_id: int = None) -> list:
        """گزارش تراز مالی و خلاصه وضعیت فروش و بدهی مدیران و شرکا"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            if admin_id:
                cursor.execute("""
                    SELECT u.id, u.username, u.display_name, u.role, u.share_percent, u.debt_balance, u.telegram_id, u.phone,
                           COALESCE((SELECT COUNT(*) FROM admin_debts WHERE admin_id=u.id AND type='cash_sale'), 0) as total_sales_count,
                           COALESCE((SELECT SUM(total_amount) FROM admin_debts WHERE admin_id=u.id AND type='cash_sale'), 0) as total_cash_collected,
                           COALESCE((SELECT SUM(share_amount) FROM admin_debts WHERE admin_id=u.id AND type='cash_sale'), 0) as total_share_earned,
                           COALESCE((SELECT SUM(total_amount) FROM admin_debts WHERE admin_id=u.id AND type='settlement'), 0) as total_settled_amount
                    FROM admin_users u
                    WHERE u.id=?
                """, (admin_id,))
            else:
                cursor.execute("""
                    SELECT u.id, u.username, u.display_name, u.role, u.share_percent, u.debt_balance, u.telegram_id, u.phone,
                           COALESCE((SELECT COUNT(*) FROM admin_debts WHERE admin_id=u.id AND type='cash_sale'), 0) as total_sales_count,
                           COALESCE((SELECT SUM(total_amount) FROM admin_debts WHERE admin_id=u.id AND type='cash_sale'), 0) as total_cash_collected,
                           COALESCE((SELECT SUM(share_amount) FROM admin_debts WHERE admin_id=u.id AND type='cash_sale'), 0) as total_share_earned,
                           COALESCE((SELECT SUM(total_amount) FROM admin_debts WHERE admin_id=u.id AND type='settlement'), 0) as total_settled_amount
                    FROM admin_users u
                    ORDER BY u.id ASC
                """)
            rows = cursor.fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"Error getting admins accounting summary: {e}")
            return []
        finally:
            conn.close()

    def find_user_contact_info(self, username: str) -> dict:
        """یافتن مشخصات و اطلاعات تماس مدیر یا نماینده بر اساس نام کاربری"""
        if not username:
            return None
        clean_user = username.strip().lower()
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            # ۱. جستجو در جدول مدیران (Admin Users)
            cursor.execute("SELECT id, username, display_name, telegram_id, phone, role FROM admin_users WHERE LOWER(username)=?", (clean_user,))
            row = cursor.fetchone()
            if row:
                admin_row = dict(row)
                return {
                    "user_type": "admin",
                    "user_id": admin_row["id"],
                    "username": admin_row["username"],
                    "name": admin_row.get("display_name") or "مدیر سیستم",
                    "telegram_id": admin_row.get("telegram_id"),
                    "phone": admin_row.get("phone"),
                    "role": admin_row.get("role", "super_admin")
                }

            # ۲. جستجو در جدول نمایندگان (Resellers)
            cursor.execute("SELECT id, username, name, telegram_id, phone, status FROM resellers WHERE LOWER(username)=?", (clean_user,))
            row = cursor.fetchone()
            if row:
                res_row = dict(row)
                return {
                    "user_type": "reseller",
                    "user_id": res_row["id"],
                    "username": res_row["username"],
                    "name": res_row.get("name") or "نماینده فروش",
                    "telegram_id": res_row.get("telegram_id"),
                    "phone": res_row.get("phone"),
                    "status": res_row.get("status", "active")
                }

            return None
        except Exception as e:
            logger.error(f"Error finding user contact info: {e}")
            return None
        finally:
            conn.close()

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
                elif key in ["username", "name", "phone", "email", "telegram_id", "bank_card", "notes", "custom_avatar"]:
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

    def update_subscription_avatar(self, sub_id: int, custom_avatar: str) -> bool:
        """بروزرسانی آواتار اختصاصی اشتراک مشتری"""
        conn = self.get_connection()
        try:
            conn.execute("UPDATE subscriptions SET custom_avatar=?, updated_at=? WHERE id=?", (custom_avatar, get_now_iso(), sub_id))
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error in update_subscription_avatar: {e}")
            return False
        finally:
            conn.close()

    def find_subscription_avatar(self, identifier: str) -> Optional[str]:
        """یافتن آواتار اختصاصی بر اساس شناسه اشتراک، نام اکانت یا شماره تلفن"""
        if not identifier:
            return None
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT custom_avatar FROM subscriptions 
                WHERE (account_name=? OR phone_number=? OR hidify_uuid=?) AND custom_avatar IS NOT NULL AND custom_avatar != ''
                ORDER BY id DESC LIMIT 1
            """, (str(identifier), str(identifier), str(identifier)))
            row = cursor.fetchone()
            if row and row["custom_avatar"]:
                return row["custom_avatar"]
            return None
        except Exception:
            return None
        finally:
            conn.close()

    def record_subscription_session(self, sub_id: int, hidify_uuid: str, ip_address: str, user_agent: str, last_seen: str = None, is_active: int = 1):
        """ثبت یا بروزرسانی نشست و اطلاعات کلاینت متصل"""
        if not sub_id and not hidify_uuid:
            return None
        now = get_now_iso()
        last_seen = last_seen or now
        parsed = parse_user_agent_details(user_agent, client_ip=ip_address)
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            # بررسی آیا نشستی با همین IP و برنامه برای این اشتراک وجود دارد؟
            cursor.execute("""
                SELECT id FROM subscription_sessions
                WHERE (sub_id=? OR hidify_uuid=?) AND ip_address=? AND client_app=?
                ORDER BY id DESC LIMIT 1
            """, (sub_id, hidify_uuid, parsed["ip_address"], parsed["client_app"]))
            row = cursor.fetchone()
            if row:
                cursor.execute("""
                    UPDATE subscription_sessions
                    SET device_name=?, os_name=?, os_icon=?, client_version=?, app_icon=?, isp_name=?, user_agent=?, last_seen=?, is_active=?
                    WHERE id=?
                """, (
                    parsed["device_name"], parsed["os_name"], parsed["os_icon"],
                    parsed["client_version"], parsed["app_icon"], parsed["isp_name"],
                    parsed["user_agent"], last_seen, is_active, row["id"]
                ))
            else:
                cursor.execute("""
                    INSERT INTO subscription_sessions (
                        sub_id, hidify_uuid, ip_address, device_name, os_name, os_icon,
                        client_app, client_version, app_icon, isp_name, user_agent, last_seen, is_active, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    sub_id, hidify_uuid, parsed["ip_address"], parsed["device_name"],
                    parsed["os_name"], parsed["os_icon"], parsed["client_app"],
                    parsed["client_version"], parsed["app_icon"], parsed["isp_name"],
                    parsed["user_agent"], last_seen, is_active, now
                ))
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error in record_subscription_session: {e}")
            return False
        finally:
            conn.close()

    def get_subscription_by_uuid(self, uuid: str) -> Optional[dict]:
        """یافتن اشتراک بر اساس UUID هیدیفای"""
        if not uuid:
            return None
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM subscriptions WHERE hidify_uuid=? ORDER BY id DESC LIMIT 1", (str(uuid),))
            row = cursor.fetchone()
            return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error in get_subscription_by_uuid: {e}")
            return None
        finally:
            conn.close()

    def get_subscription(self, sub_id: int) -> Optional[dict]:
        """یافتن اشتراک بر اساس شناسه id"""
        if not sub_id:
            return None
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM subscriptions WHERE id=?", (sub_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error in get_subscription: {e}")
            return None
        finally:
            conn.close()

    def get_subscription_sessions(self, sub_id: int) -> dict:
        """دریافت لیست نشست‌های فعال و تاریخچه دستگاه‌های متصل به اشتراک"""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM subscriptions WHERE id=?", (sub_id,))
            sub = cursor.fetchone()
            if not sub:
                return {"sessions": [], "active_devices": 0, "user_limit": 1}

            user_limit = sub["user_limit"] if "user_limit" in sub.keys() and sub["user_limit"] else 1
            is_online = bool(sub["is_online"]) if "is_online" in sub.keys() else False

            cursor.execute("""
                SELECT * FROM subscription_sessions
                WHERE sub_id=? OR (hidify_uuid=? AND hidify_uuid IS NOT NULL AND hidify_uuid != '')
                ORDER BY last_seen DESC LIMIT 10
            """, (sub_id, sub["hidify_uuid"]))
            rows = [dict(r) for r in cursor.fetchall()]

            active_devices = len(set(r["ip_address"] for r in rows if r.get("is_active"))) if rows else (1 if is_online else 0)

            return {
                "sub_id": sub_id,
                "account_name": sub["account_name"],
                "is_online": is_online,
                "user_limit": user_limit,
                "active_devices": max(active_devices, 1 if is_online else 0),
                "sessions": rows
            }
        except Exception as e:
            logger.error(f"Error in get_subscription_sessions: {e}")
            return {"sessions": [], "active_devices": 0, "user_limit": 1, "error": str(e)}
        finally:
            conn.close()


# نمونه singleton
db = Database()


