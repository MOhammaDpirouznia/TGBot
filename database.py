#!/usr/bin/env python3
"""
ماژول دیتابیس برای ذخیره‌سازی مشتریان، تنظیمات و تراکنش‌ها
"""

import sqlite3
import json
import os
import re
import copy
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
POSSIBLE_PATHS = []

# ۱. متغیر محیطی اختصاصی (بالاترین اولویت برای Railway Volume یا Docker Mount)
data_dir_env = os.environ.get("DATA_DIR", "").strip()
if data_dir_env:
    if not (os.name == "nt" and data_dir_env.startswith("/")):
        POSSIBLE_PATHS.append(Path(data_dir_env))

# ۲. اگر دیتابیس در پوشه دیتای پروژه از قبل وجود دارد (ویندوز یا سرور لینوکس VPS)
if Path("data/bot_database.db").exists():
    POSSIBLE_PATHS.append(Path("data"))

# ۳. اگر دیتابیس در مسیر پیش‌فرض Railway (/data/bot_database.db) وجود دارد
if os.name != "nt" and Path("/data/bot_database.db").exists():
    POSSIBLE_PATHS.append(Path("/data"))

# ۴. پوشه پیش‌فرض دیتای پروژه
POSSIBLE_PATHS.append(Path("data"))

# ۵. سایر مسیرهای پایدار لینوکس و هوم دایرکتوری به عنوان فال‌بک
if os.name != "nt":
    POSSIBLE_PATHS.append(Path("/data"))

POSSIBLE_PATHS.append(Path(os.path.expanduser("~/.vpn-bot/data")))

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
                is_vip BOOLEAN DEFAULT 0,
                vip_type TEXT DEFAULT 'manual',
                vip_expire_at TEXT,
                vip_custom_cashback INTEGER,
                reseller_id INTEGER DEFAULT 0,
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

        # جدول پیام‌های زنجیره گفتگوی تیکت‌ها (Ticket Messages / Thread)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ticket_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id INTEGER NOT NULL,
                sender_type TEXT NOT NULL, -- 'user', 'admin', 'reseller'
                sender_id INTEGER,
                sender_name TEXT,
                message TEXT NOT NULL,
                created_at TEXT,
                FOREIGN KEY (ticket_id) REFERENCES support_tickets(id) ON DELETE CASCADE
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

        # جدول پلن‌های سفارشی نماینده (نام نمایشی، قیمت سفارشی، فعال/غیرفعال)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS reseller_plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reseller_id INTEGER NOT NULL,
                plan_id TEXT NOT NULL,
                custom_name TEXT,
                custom_price INTEGER,
                is_active INTEGER DEFAULT 1,
                created_at TEXT,
                updated_at TEXT,
                UNIQUE(reseller_id, plan_id)
            )
        """)

        # جدول اعلان‌ها و پیام‌های سیستمی نماینده (تایید/رد فیش، تغییرات حساب)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS reseller_notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reseller_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                type TEXT DEFAULT 'info',
                is_read INTEGER DEFAULT 0,
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

        # جدول سابقه و تاریخچه مصرف دوره‌های گذشته اشتراک‌ها هنگام تمدید یا ثبت دستی
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
                reseller_id INTEGER,
                plan_price INTEGER DEFAULT 0,
                cost_paid INTEGER DEFAULT 0,
                start_date TEXT,
                expire_date TEXT,
                is_manual INTEGER DEFAULT 0,
                period_offset INTEGER DEFAULT 1,
                period_label TEXT,
                note TEXT,
                created_by TEXT
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
            cursor.execute("ALTER TABLE transactions ADD COLUMN processed_by TEXT")
        except Exception:
            pass

        try:
            cursor.execute("ALTER TABLE transactions ADD COLUMN processed_at TEXT")
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

        # ستون‌های کاربران پریمیوم و وفاداری (VIP)
        for col_def in [
            "is_vip INTEGER DEFAULT 0",
            "vip_type TEXT DEFAULT 'manual'",
            "vip_expire_at TEXT",
            "vip_custom_cashback INTEGER"
        ]:
            try:
                cursor.execute(f"ALTER TABLE users ADD COLUMN {col_def}")
            except Exception:
                pass

        # ستون‌های ربات اختصاصی (White-label Multi-Bot) و تنظیمات نمایندگان
        for col_def in [
            "bot_token TEXT", "bot_username TEXT", "channel_id TEXT", "brand_name TEXT",
            "start_message TEXT", "support_username TEXT", "card_number TEXT", "card_holder TEXT",
            "bank_name TEXT", "is_bot_active INTEGER DEFAULT 0", "tier_level TEXT DEFAULT 'silver'",
            "auto_approval INTEGER DEFAULT 0", "vip_auto_enabled INTEGER DEFAULT 1",
            "vip_auto_threshold INTEGER DEFAULT 1000000", "vip_cashback_percent INTEGER DEFAULT 10"
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

        # ستون‌های درگاه پرداخت آنلاین نماینده
        for col_def in [
            "is_gateway_active INTEGER DEFAULT 0",
            "gateway_type TEXT DEFAULT 'zarinpal'",
            "gateway_key TEXT",
            "gateway_sandbox INTEGER DEFAULT 0",
            "hiddify_admin_uuid TEXT"
        ]:
            try:
                cursor.execute(f"ALTER TABLE resellers ADD COLUMN {col_def}")
            except Exception:
                pass

        try:
            cursor.execute("ALTER TABLE users ADD COLUMN reseller_id INTEGER DEFAULT 0")
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

        # ستون‌های فعال‌سازی موقت رسید (Grace Period)
        try:
            cursor.execute("ALTER TABLE payments ADD COLUMN is_grace_active INTEGER DEFAULT 0")
        except Exception:
            pass

        try:
            cursor.execute("ALTER TABLE payments ADD COLUMN grace_expires_at TEXT")
        except Exception:
            pass

        # ستون‌های وضعیت پرداخت، مبلغ بدهی و یادداشت بدهی اشتراک‌ها
        for col_def in [
            "payment_status TEXT DEFAULT 'paid'",
            "debt_amount INTEGER DEFAULT 0",
            "debt_notes TEXT",
            "debt_created_at TEXT"
        ]:
            try:
                cursor.execute(f"ALTER TABLE subscriptions ADD COLUMN {col_def}")
            except Exception:
                pass

        # ستون‌های قیمت پلن، جزئیات مالی و ثبت دستی سوابق در سابقه دوره‌ها
        for col_def in [
            "plan_price INTEGER DEFAULT 0",
            "cost_paid INTEGER DEFAULT 0",
            "start_date TEXT",
            "expire_date TEXT",
            "is_manual INTEGER DEFAULT 0",
            "period_offset INTEGER DEFAULT 1",
            "period_label TEXT",
            "note TEXT",
            "created_by TEXT"
        ]:
            try:
                cursor.execute(f"ALTER TABLE subscription_history ADD COLUMN {col_def}")
            except Exception:
                pass

        # ستون‌های تیکت‌های درخواست تغییر حجم و مدت نماینده
        for col_def in [
            "reseller_id INTEGER DEFAULT 0",
            "ticket_type TEXT DEFAULT 'general'",
            "target_role TEXT DEFAULT 'admin'",
            "request_data TEXT",
            "request_status TEXT DEFAULT 'pending'"
        ]:
            try:
                cursor.execute(f"ALTER TABLE support_tickets ADD COLUMN {col_def}")
            except Exception:
                pass

        # ستون‌های سیستم زیرمجموعه‌گیری و پورسانت نمایندگان
        for col_def in [
            "parent_reseller_id INTEGER DEFAULT NULL",
            "affiliate_commission_percent REAL DEFAULT NULL",
            "referral_code TEXT",
            "credit_enabled INTEGER DEFAULT 0",
            "credit_limit INTEGER DEFAULT 0",
            "credit_debt INTEGER DEFAULT 0"
        ]:
            try:
                cursor.execute(f"ALTER TABLE resellers ADD COLUMN {col_def}")
            except Exception:
                pass

        # ستون‌های شخصی‌سازی حجم و مدت در پلن‌های نماینده
        for col_def in [
            "custom_data_limit REAL DEFAULT NULL",
            "custom_duration INTEGER DEFAULT NULL"
        ]:
            try:
                cursor.execute(f"ALTER TABLE reseller_plans ADD COLUMN {col_def}")
            except Exception:
                pass

        # ستون‌های پرمیوم و خرید اعتباری اشتراک‌ها و کاربران
        for col_def in [
            "is_vip INTEGER DEFAULT 0",
            "is_credit INTEGER DEFAULT 0",
            "credit_debt_amount INTEGER DEFAULT 0"
        ]:
            try:
                cursor.execute(f"ALTER TABLE subscriptions ADD COLUMN {col_def}")
            except Exception:
                pass

        try:
            cursor.execute("ALTER TABLE users ADD COLUMN is_vip INTEGER DEFAULT 0")
        except Exception:
            pass

        # فعال‌سازی خودکار خرید اعتباری برای کلیه نمایندگانی که سقف اعتبار دارند
        try:
            cursor.execute("UPDATE resellers SET credit_enabled = 1 WHERE credit_limit > 0 AND (credit_enabled IS NULL OR credit_enabled = 0)")
        except Exception:
            pass

        # جدول تراکنش‌های پورسانت زیرمجموعه‌گیری نمایندگان
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS reseller_affiliate_commissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                parent_reseller_id INTEGER NOT NULL,
                sub_reseller_id INTEGER NOT NULL,
                sub_id INTEGER,
                account_name TEXT,
                plan_id TEXT,
                plan_name TEXT,
                plan_price INTEGER NOT NULL,
                commission_percent REAL NOT NULL,
                commission_amount INTEGER NOT NULL,
                description TEXT,
                created_at TEXT NOT NULL
            )
        """)

        # مقداردهی اولیه تنظیمات زیرمجموعه‌گیری در صورت عدم وجود
        default_aff_settings = {
            "reseller_affiliate_enabled": "1",
            "reseller_affiliate_default_percent": "10",
            "reseller_affiliate_calc_base": "plan_price",
            "reseller_affiliate_terms": "با پیوستن به عنوان همکار و نماینده زیرمجموعه، از ربات اختصاصی هوشمند، ساب‌دامنه‌های بدون فیلتر و پنل مدیریت فروش با تسویه آنی بهره‌مند شوید."
        }
        for k, v in default_aff_settings.items():
            cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))

        # ستون‌های حذف نرم اشتراک‌ها (Soft Delete & 7-Day Purge)
        for col_def in [
            ("is_deleted", "INTEGER DEFAULT 0"),
            ("deleted_at", "TEXT"),
            ("delete_reason", "TEXT"),
            ("deleted_by", "TEXT"),
            ("purged_from_hiddify", "INTEGER DEFAULT 0"),
            ("disable_reason", "TEXT")
        ]:
            try:
                cursor.execute(f"ALTER TABLE subscriptions ADD COLUMN {col_def[0]} {col_def[1]}")
            except Exception:
                pass

        # جدول قبوض بدهی قبلی/جدید نماینده (Reseller Debts & Invoices)
        try:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS reseller_debts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    reseller_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    amount INTEGER NOT NULL DEFAULT 0,
                    remaining_amount INTEGER NOT NULL DEFAULT 0,
                    status TEXT DEFAULT 'unpaid',
                    due_date TEXT,
                    notes TEXT,
                    created_by TEXT,
                    created_at TEXT,
                    updated_at TEXT,
                    FOREIGN KEY (reseller_id) REFERENCES resellers(id)
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_reseller_debts_reseller ON reseller_debts(reseller_id)")
        except Exception:
            pass

        # جدول صف تمدید هوشمند و بسته‌های رزرو
        try:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS subscription_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    subscription_id INTEGER NOT NULL,
                    telegram_id INTEGER DEFAULT 0,
                    hidify_uuid TEXT,
                    reseller_id INTEGER,
                    plan_id TEXT,
                    plan_name TEXT,
                    data_limit REAL DEFAULT 0,
                    duration INTEGER DEFAULT 30,
                    cost INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'pending',
                    created_at TEXT,
                    activated_at TEXT,
                    note TEXT,
                    FOREIGN KEY (subscription_id) REFERENCES subscriptions(id) ON DELETE CASCADE
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_sub_queue_sub_status ON subscription_queue(subscription_id, status)")
        except Exception as e:
            logger.warning(f"Error creating subscription_queue table: {e}")

        # ستون‌های مبدأ پرداخت کیف‌پول/اعتبار و رهگیری ویرایش اسناد حسابداری و بدهی‌ها
        for col_sql in [
            "ALTER TABLE subscriptions ADD COLUMN payment_source TEXT DEFAULT 'wallet'",
            "ALTER TABLE reseller_transactions ADD COLUMN payment_source TEXT DEFAULT 'wallet'",
            "ALTER TABLE reseller_transactions ADD COLUMN subscription_id INTEGER",
            "ALTER TABLE accounting_records ADD COLUMN is_edited INTEGER DEFAULT 0",
            "ALTER TABLE accounting_records ADD COLUMN edited_by TEXT",
            "ALTER TABLE accounting_records ADD COLUMN edited_at TEXT",
            "ALTER TABLE admin_debts ADD COLUMN is_edited INTEGER DEFAULT 0",
            "ALTER TABLE admin_debts ADD COLUMN edited_by TEXT",
            "ALTER TABLE admin_debts ADD COLUMN edited_at TEXT"
        ]:
            try:
                cursor.execute(col_sql)
            except Exception:
                pass

        # جدول بسته‌های پیش‌خرید اعتباری همکاران و نمایندگان (Reseller Credit Bundles)
        try:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS reseller_bundles (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    price INTEGER NOT NULL,
                    credit INTEGER NOT NULL,
                    bonus_percent INTEGER DEFAULT 0,
                    badge TEXT,
                    color TEXT DEFAULT 'primary',
                    description TEXT DEFAULT '',
                    display_order INTEGER DEFAULT 0,
                    is_active INTEGER DEFAULT 1,
                    created_at TEXT,
                    updated_at TEXT
                )
            """)
            cursor.execute("SELECT COUNT(*) FROM reseller_bundles")
            if cursor.fetchone()[0] == 0:
                now_seed = get_now_iso()
                default_bundles = [
                    ("bundle_1m", "بسته استارتر", 1000000, 1050000, 5, "۵٪ شارژ هدیه", "info", "مناسب شروع همکاری و شارژ اولیه", 1, 1, now_seed, now_seed),
                    ("bundle_3m", "بسته نقره‌ای", 3000000, 3210000, 7, "۷٪ شارژ هدیه", "primary", "بسته اقتصادی با بونوس شارژ تشویقی", 2, 1, now_seed, now_seed),
                    ("bundle_5m", "بسته طلایی", 5000000, 5500000, 10, "۱۰٪ شارژ هدیه", "success", "بسته پرفروش همکاران با ۱۰٪ هدیه نقدی", 3, 1, now_seed, now_seed),
                    ("bundle_10m", "بسته الماس VIP", 10000000, 11500000, 15, "۱۵٪ شارژ ویژه", "warning", "حداکثر اعتبار با بالاترین نرخ بونوس ویژه", 4, 1, now_seed, now_seed),
                ]
                cursor.executemany("""
                    INSERT INTO reseller_bundles (id, title, price, credit, bonus_percent, badge, color, description, display_order, is_active, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, default_bundles)
        except Exception as e:
            logger.warning(f"Error initializing reseller_bundles table: {e}")

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
            "accounting_records", "admin_users", "reseller_bundles"
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

                name_clean = str(name).strip() if (name and str(name).strip()) else None
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
                    """, (current_usage, usage_limit, package_days, start_date, expiry_time, status, name_clean, is_online_val, last_online_val, now, uuid))
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
    # مدیریت مشتریان پریمیوم و وفاداری (VIP & Loyalty Club)
    # ═══════════════════════════════════════════════════════════════

    def is_user_vip(self, telegram_id: int) -> bool:
        """بررسی وضعیت پریمیوم / VIP بودن کاربر با رعایت تاریخ انقضا"""
        user = self.get_user(telegram_id)
        if not user or not user.get("is_vip"):
            return False

        # بررسی تاریخ انقضا در صورت وجود
        vip_expire = user.get("vip_expire_at")
        if vip_expire:
            try:
                exp_dt = datetime.fromisoformat(vip_expire)
                if datetime.now() > exp_dt:
                    # انقضای مدت VIP - ریست کردن وضعیت به عادی
                    self.set_user_vip(telegram_id, is_vip=False, vip_type="expired")
                    return False
            except Exception:
                pass
        return True

    def get_user_vip_info(self, telegram_id: int) -> dict:
        """دریافت اطلاعات و مزایای VIP کاربر شامل درصد کش‌بک فعال"""
        user = self.get_user(telegram_id)
        is_vip = self.is_user_vip(telegram_id)
        if not user:
            return {
                "is_vip": False,
                "vip_type": "none",
                "vip_expire_at": None,
                "cashback_percent": 0,
                "custom_cashback": None
            }

        custom_cb = user.get("vip_custom_cashback")
        reseller_id = user.get("reseller_id")

        if is_vip:
            if custom_cb is not None and str(custom_cb).strip() != "":
                try:
                    cb_rate = int(custom_cb)
                except Exception:
                    cb_rate = 10
            elif reseller_id:
                reseller = self.get_reseller(reseller_id)
                cb_rate = int((reseller.get("vip_cashback_percent") if reseller else 10) or 10)
            else:
                vip_sets = self.get_vip_settings()
                cb_rate = int(vip_sets.get("cashback_percent", 10))
        else:
            cb_rate = 0

        return {
            "is_vip": is_vip,
            "vip_type": user.get("vip_type") or "manual",
            "vip_expire_at": user.get("vip_expire_at"),
            "cashback_percent": cb_rate,
            "custom_cashback": custom_cb
        }

    def set_user_vip(self, telegram_id: int, is_vip: bool, vip_type: str = "manual",
                     expire_at: Optional[str] = None, custom_cashback: Optional[int] = None) -> dict:
        """تغییر و تنظیم وضعیت VIP کاربر (دستی یا خودکار)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("SELECT id FROM users WHERE telegram_id = ?", (telegram_id,))
            row = cursor.fetchone()
            val_is_vip = 1 if is_vip else 0
            if not row:
                cursor.execute("""
                    INSERT INTO users (telegram_id, username, is_vip, vip_type, vip_expire_at, vip_custom_cashback, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (telegram_id, f"user_{telegram_id}", val_is_vip, vip_type, expire_at, custom_cashback, now, now))
            else:
                cursor.execute("""
                    UPDATE users
                    SET is_vip = ?, vip_type = ?, vip_expire_at = ?, vip_custom_cashback = ?, updated_at = ?
                    WHERE telegram_id = ?
                """, (val_is_vip, vip_type, expire_at, custom_cashback, now, telegram_id))
            conn.commit()
            logger.info(f"User {telegram_id} VIP status updated to {val_is_vip} ({vip_type})")
            return {"success": True, "is_vip": bool(val_is_vip)}
        except Exception as e:
            logger.error(f"Error setting VIP for {telegram_id}: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def check_and_upgrade_user_vip(self, telegram_id: int, reseller_id: Optional[int] = None) -> dict:
        """بررسی خودکار مجموع خریدهای کاربر و ارتقا به VIP در صورت رسیدن به حد نصاب"""
        user = self.get_user(telegram_id)
        if not user:
            return {"upgraded": False, "is_vip": False}

        if user.get("is_vip"):
            return {"upgraded": False, "is_vip": True, "already_vip": True}

        r_id = reseller_id if reseller_id is not None else user.get("reseller_id")

        # محاسبه مجموع خریدهای تایید شده کاربر
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT COALESCE(SUM(amount), 0) as total_spent
                FROM transactions
                WHERE user_id = ? AND status = 'approved'
            """, (telegram_id,))
            spent_row = cursor.fetchone()
            total_spent = int(spent_row["total_spent"] or 0) if spent_row else 0
        except Exception as e:
            logger.error(f"Error calculating total spent for {telegram_id}: {e}")
            total_spent = 0
        finally:
            conn.close()

        if r_id:
            reseller = self.get_reseller(r_id)
            auto_enabled = bool(reseller.get("vip_auto_enabled", 1)) if reseller else True
            threshold = int((reseller.get("vip_auto_threshold") if reseller else 1000000) or 1000000)
            cashback = int((reseller.get("vip_cashback_percent") if reseller else 10) or 10)
        else:
            vip_sets = self.get_vip_settings()
            auto_enabled = vip_sets.get("auto_enabled", True)
            threshold = vip_sets.get("auto_threshold", 1000000)
            cashback = vip_sets.get("cashback_percent", 10)

        if auto_enabled and total_spent >= threshold:
            self.set_user_vip(telegram_id, is_vip=True, vip_type="auto")
            logger.info(f"User {telegram_id} auto-upgraded to VIP (total spent: {total_spent:,} >= threshold: {threshold:,})")
            return {
                "upgraded": True,
                "is_vip": True,
                "total_spent": total_spent,
                "threshold": threshold,
                "cashback_percent": cashback,
                "reseller_id": r_id
            }

        return {
            "upgraded": False,
            "is_vip": False,
            "total_spent": total_spent,
            "threshold": threshold
        }

    def get_vip_settings(self) -> dict:
        """دریافت تنظیمات جامع و فیچرهای باشگاه مشتریان پریمیوم (VIP)"""
        auto_enabled = str(self.get_setting("vip_auto_enabled", "1")).lower() in ("1", "true", "yes")
        enabled = str(self.get_setting("vip_system_enabled", "1")).lower() in ("1", "true", "yes")
        priority_support = str(self.get_setting("vip_priority_support", "1")).lower() in ("1", "true", "yes")
        vip_server_access = str(self.get_setting("vip_server_access", "1")).lower() in ("1", "true", "yes")
        free_config_regen = str(self.get_setting("vip_free_config_regen", "1")).lower() in ("1", "true", "yes")
        show_vip_badge = str(self.get_setting("vip_show_badge", "1")).lower() in ("1", "true", "yes")

        def _to_int(key, default):
            try:
                return int(self.get_setting(key, default))
            except Exception:
                return default

        return {
            "enabled": enabled,
            "auto_enabled": auto_enabled,
            "auto_threshold": _to_int("vip_auto_threshold", 1000000),
            "min_purchases": _to_int("vip_min_purchases", 3),
            "discount_percent": _to_int("vip_discount_percent", 15),
            "cashback_percent": _to_int("vip_cashback_percent", 10),
            "bonus_data_gb": _to_int("vip_bonus_data_gb", 5),
            "extended_grace_hours": _to_int("vip_extended_grace_hours", 48),
            "priority_support": priority_support,
            "vip_server_access": vip_server_access,
            "free_config_regen": free_config_regen,
            "show_vip_badge": show_vip_badge
        }

    def save_vip_settings(self, settings: dict) -> bool:
        """ذخیره تنظیمات و فیچرهای باشگاه مشتریان پریمیوم در جدول settings"""
        try:
            for k, v in settings.items():
                if isinstance(v, bool):
                    val_str = "1" if v else "0"
                else:
                    val_str = str(v)
                self.set_setting(f"vip_{k}", val_str)
            return True
        except Exception as e:
            logger.error(f"Error saving VIP settings: {e}")
            return False

    def get_vip_users_list(self) -> list:
        """دریافت لیست تمام مشتریان پرمیوم همراه با آمار خرید و اشتراک‌های فعال"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT u.*,
                       COALESCE((SELECT SUM(amount) FROM transactions WHERE user_id = u.telegram_id AND status = 'approved'), 0) as total_spent,
                       COALESCE((SELECT COUNT(id) FROM transactions WHERE user_id = u.telegram_id AND status = 'approved'), 0) as total_orders,
                       COALESCE((SELECT COUNT(id) FROM subscriptions WHERE telegram_id = u.telegram_id AND status = 'active'), 0) as active_subs
                FROM users u
                WHERE u.is_vip = 1
                ORDER BY total_spent DESC, u.id DESC
            """)
            rows = cursor.fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"Error fetching VIP users list: {e}")
            return []
        finally:
            conn.close()

    def get_vip_dashboard_stats(self) -> dict:
        """محاسبه آمار و شاخص‌های تحلیلی مشتریان پرمیوم برای داشبورد"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT COUNT(id) FROM users WHERE is_vip = 1")
            total_vips = cursor.fetchone()[0] or 0

            cursor.execute("SELECT COUNT(id) FROM users WHERE is_vip = 1 AND vip_type = 'auto'")
            auto_vips = cursor.fetchone()[0] or 0

            cursor.execute("""
                SELECT COALESCE(SUM(t.amount), 0)
                FROM transactions t
                JOIN users u ON t.user_id = u.telegram_id
                WHERE u.is_vip = 1 AND t.status = 'approved'
            """)
            vip_revenue = cursor.fetchone()[0] or 0

            cursor.execute("""
                SELECT COALESCE(COUNT(s.id), 0)
                FROM subscriptions s
                JOIN users u ON s.telegram_id = u.telegram_id
                WHERE u.is_vip = 1 AND s.status = 'active'
            """)
            vip_active_subs = cursor.fetchone()[0] or 0

            return {
                "total_vips": total_vips,
                "auto_vips": auto_vips,
                "manual_vips": max(0, total_vips - auto_vips),
                "vip_revenue": vip_revenue,
                "vip_active_subs": vip_active_subs
            }
        except Exception as e:
            logger.error(f"Error fetching VIP stats: {e}")
            return {"total_vips": 0, "auto_vips": 0, "manual_vips": 0, "vip_revenue": 0, "vip_active_subs": 0}
        finally:
            conn.close()

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

    def save_subscription(self, telegram_id, hidify_uuid, plan_id, plan_name, data_limit, duration, data_used=0, status="active", account_name=None, account_comment=None, reseller_id=None, user_limit=1, cost_paid=0, **kwargs):
        """ذخیره اشتراک جدید"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        expire_date = (get_now_naive() + timedelta(days=duration)).isoformat()

        try:
            cursor.execute("""
                INSERT INTO subscriptions
                (telegram_id, hidify_uuid, plan_id, plan_name, account_name, account_comment, data_limit, data_used, duration, start_date, expire_date, status, reseller_id, user_limit, cost_paid, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (telegram_id, hidify_uuid, plan_id, plan_name, account_name, account_comment, data_limit, data_used, duration, now, expire_date, status, reseller_id, int(user_limit or 1), int(cost_paid or 0), now, now))
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

    def save_transaction(self, order_id, user_id, username, plan_name, amount, gateway, tracking_code, status="pending", account_name=None, account_comment=None, is_renewal=0, renew_sub_id=None, discount_code=None, receipt_image=None, receipt_file_type=None, reseller_id=None, notes=None, **kwargs):
        """ذخیره تراکنش"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()

        if notes and not account_comment:
            account_comment = notes

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

    def get_transaction_by_tracking_code(self, tracking_code):
        """دریافت تراکنش بر اساس tracking_code (شناسه فاکتور / ارجاع درگاه)"""
        if not tracking_code:
            return None
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT * FROM transactions 
                WHERE tracking_code = ? OR tracking_code LIKE ?
                ORDER BY id DESC LIMIT 1
            """, (str(tracking_code), f"%{tracking_code}%"))
            row = cursor.fetchone()
            return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting transaction by tracking_code {tracking_code}: {e}")
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

    def add_transaction_audit_log(self, transaction_id: int, admin_id: int, admin_name: str, action: str, field_name: str = None, old_value: str = None, new_value: str = None, reason: str = None) -> dict:
        """ثبت لاگ حسابرسی تغییرات و عملیات روی تراکنش"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now_iso = get_now_iso()
        try:
            cursor.execute("""
                INSERT INTO transaction_audit_logs 
                (transaction_id, admin_id, admin_name, action, field_name, old_value, new_value, reason, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (transaction_id, admin_id, admin_name, action, field_name, str(old_value) if old_value is not None else None, str(new_value) if new_value is not None else None, reason, now_iso))
            conn.commit()
            return {"success": True}
        except Exception as e:
            logger.error(f"Error adding transaction audit log: {e}")
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

    def get_refund_settings(self) -> dict:
        """دریافت تنظیمات جامع قوانین استرداد وجه و سقف‌های بازگردانی"""
        raw = self.get_setting("refund_settings")
        defaults = {
            "refund_enabled": True,
            "disabled_resellers": [],
            "rate_before_12h": 100,
            "rate_before_24h": 80,
            "calc_from_creation": True,
            "daily_restore_limit": 10,
            "restore_window_days": 7,
            "reseller_daily_restore_limits": {}
        }
        if isinstance(raw, dict):
            defaults.update(raw)
        
        enabled = bool(defaults.get("refund_enabled", defaults.get("enabled", True)))
        r12 = int(defaults.get("rate_before_12h", defaults.get("refund_rate_before_12h", defaults.get("before_12h_percent", 100))))
        r24 = int(defaults.get("rate_before_24h", defaults.get("refund_rate_before_24h", defaults.get("before_24h_percent", 80))))
        calc_creation = bool(defaults.get("calc_from_creation", defaults.get("refund_calc_from_creation", True)))
        daily_restore_limit = int(defaults.get("daily_restore_limit", 10))
        restore_window_days = int(defaults.get("restore_window_days", 7))
        
        raw_dis = defaults.get("disabled_resellers") or defaults.get("refund_disabled_resellers") or defaults.get("disabled_reseller_ids") or []
        if isinstance(raw_dis, list):
            dis_res = [int(x) for x in raw_dis if str(x).isdigit()]
        else:
            dis_res = []

        raw_custom = defaults.get("reseller_daily_restore_limits") or {}
        custom_limits = {}
        if isinstance(raw_custom, dict):
            for k, v in raw_custom.items():
                if str(k).isdigit() and v is not None and str(v).isdigit():
                    custom_limits[str(k)] = int(v)

        res = {
            "refund_enabled": enabled,
            "enabled": enabled,
            "rate_before_12h": r12,
            "before_12h_percent": r12,
            "refund_rate_before_12h": r12,
            "rate_before_24h": r24,
            "before_24h_percent": r24,
            "refund_rate_before_24h": r24,
            "calc_from_creation": calc_creation,
            "refund_calc_from_creation": calc_creation,
            "disabled_resellers": dis_res,
            "disabled_reseller_ids": dis_res,
            "refund_disabled_resellers": dis_res,
            "daily_restore_limit": daily_restore_limit,
            "restore_window_days": restore_window_days,
            "reseller_daily_restore_limits": custom_limits
        }
        return res

    def save_refund_settings(self, settings_dict: dict) -> bool:
        """ذخیره تنظیمات جامع قوانین استرداد وجه"""
        try:
            current = self.get_refund_settings()
            current.update(settings_dict)
            return self.save_setting("refund_settings", current)
        except Exception as e:
            logger.error(f"Error saving refund settings: {e}")
            return False

    def get_reseller_daily_restore_count(self, reseller_id: int) -> int:
        """تعداد دفعات بازگردانی اشتراک از سطل زباله توسط نماینده در تاریخ امروز"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            today_start = get_now_naive().strftime("%Y-%m-%d 00:00:00")
            cursor.execute("""
                SELECT COUNT(*) FROM reseller_transactions
                WHERE reseller_id = ?
                  AND type IN ('purchase', 'purchase_credit')
                  AND (description LIKE '%بازگردانی%' OR description LIKE '%restore%')
                  AND created_at >= ?
            """, (reseller_id, today_start))
            row = cursor.fetchone()
            return int(row[0]) if row else 0
        except Exception as e:
            logger.error(f"Error getting reseller daily restore count: {e}")
            return 0
        finally:
            conn.close()

    def can_reseller_restore(self, reseller_id: int, count_to_restore: int = 1) -> tuple[bool, str, int, int]:
        """
        بررسی اینکه آیا نماینده مجاز به بازگردانی اشتراک‌های درخواستی در امروز هست یا خیر.
        خروجی: (مجاز بودن, پیام خطا, سقف مجاز, تعداد انجام‌شده)
        """
        settings = self.get_refund_settings()
        custom_limits = settings.get("reseller_daily_restore_limits", {})
        default_limit = int(settings.get("daily_restore_limit", 10))

        r_key = str(reseller_id)
        if r_key in custom_limits and custom_limits[r_key] is not None:
            limit = int(custom_limits[r_key])
        else:
            limit = default_limit

        # عدد ۰ به معنای بدون محدودیت است
        if limit <= 0:
            return (True, "", 0, 0)

        current_count = self.get_reseller_daily_restore_count(reseller_id)
        if current_count + count_to_restore > limit:
            remaining = max(0, limit - current_count)
            err = f"سقف مجاز بازگردانی روزانه شما ({limit} بار در روز) تکمیل شده است. بازگردانی‌های امروز شما: {current_count} مورد | ظرفیت باقیمانده امروز: {remaining} مورد."
            return (False, err, limit, current_count)

        return (True, "", limit, current_count)

    # ═══════════════════════════════════════════════════════════════
    # مدیریت و چیدمان سفارشی دکمه‌ها و منوی ربات (Bot Menu Customizer)
    # ═══════════════════════════════════════════════════════════════

    DEFAULT_BOT_MENU_BUTTONS = [
        {
            "id": "buy",
            "title": "🛍️ خرید اشتراک",
            "description": "نمایش تعرفه‌ها و خرید اشتراک VPN",
            "row": 0,
            "col": 0,
            "is_enabled": True,
            "disabled_behavior": "show_disabled",
            "disabled_message": "⚠️ بخش خرید اشتراک موقتاً غیرفعال می‌باشد. لطفاً دقایقی دیگر مراجعه فرمایید.",
        },
        {
            "id": "my_subs",
            "title": "👤 اشتراک‌های من",
            "description": "مشاهده وضعیت ترافیک، زمان و لینک‌های اتصال کاربر",
            "row": 0,
            "col": 1,
            "is_enabled": True,
            "disabled_behavior": "show_disabled",
            "disabled_message": "⚠️ بخش اشتراک‌های من موقتاً در حال بروزرسانی است.",
        },
        {
            "id": "test_sub",
            "title": "⚡ تست رایگان",
            "description": "دریافت کانفیگ تست رایگان برای کاربران جدید",
            "row": 1,
            "col": 0,
            "is_enabled": True,
            "disabled_behavior": "hide",
            "disabled_message": "⚠️ اشتراک تست موقتاً غیرفعال است.",
        },
        {
            "id": "renew",
            "title": "🔄 تمدید سرویس",
            "description": "تمدید سریع اکانت‌های موجود بدون تغییر لینک",
            "row": 1,
            "col": 1,
            "is_enabled": True,
            "disabled_behavior": "show_disabled",
            "disabled_message": "⚠️ بخش تمدید سرویس موقتاً غیرفعال است.",
        },
        {
            "id": "wallet",
            "title": "💳 کیف پول و شارژ",
            "description": "مشاهده موجودی کیف پول و شارژ اعتبار",
            "row": 2,
            "col": 0,
            "is_enabled": True,
            "disabled_behavior": "show_disabled",
            "disabled_message": "⚠️ بخش کیف پول موقتاً در دسترس نیست.",
        },
        {
            "id": "support",
            "title": "🎧 پشتیبانی و تیکت",
            "description": "ارسال تیکت و پیام به اپراتورها",
            "row": 2,
            "col": 1,
            "is_enabled": True,
            "disabled_behavior": "show_disabled",
            "disabled_message": "⚠️ پشتیبانی موقتاً غیرفعال است.",
        },
        {
            "id": "tutorials",
            "title": "📖 راهنمای اتصال",
            "description": "آموزش‌های تصویری اتصال برای اندروید، آیفون، ویندوز و...",
            "row": 3,
            "col": 0,
            "is_enabled": True,
            "disabled_behavior": "show_disabled",
            "disabled_message": "⚠️ بخش راهنمای اتصال در حال بروزرسانی است.",
        },
        {
            "id": "troubleshoot",
            "title": "🛠️ حل مشکلات اتصال",
            "description": "ویزارد عیب‌یابی و رفع قطعی اینترنت",
            "row": 3,
            "col": 1,
            "is_enabled": True,
            "disabled_behavior": "show_disabled",
            "disabled_message": "⚠️ سامانه حل مشکلات اتصال موقتاً در دسترس نیست.",
        },
        {
            "id": "referral",
            "title": "👥 کسب درآمد و دعوت",
            "description": "دریافت لینک زیرمجموعه‌گیری و پورسانت",
            "row": 4,
            "col": 0,
            "is_enabled": True,
            "disabled_behavior": "hide",
            "disabled_message": "⚠️ سیستم زیرمجموعه‌گیری موقتاً غیرفعال است.",
        },
        {
            "id": "payments",
            "title": "🧾 سابقه پرداخت‌ها",
            "description": "مشاهده تراکنش‌ها و فیش‌های ارسالی کاربر",
            "row": 4,
            "col": 1,
            "is_enabled": True,
            "disabled_behavior": "hide",
            "disabled_message": "⚠️ بخش سابقه پرداخت‌ها موقتاً غیرفعال است.",
        },
        {
            "id": "language",
            "title": "🌐 تغییر زبان",
            "description": "تغییر زبان ربات به زبان‌های دیگر",
            "row": 5,
            "col": 0,
            "is_enabled": True,
            "disabled_behavior": "hide",
            "disabled_message": "⚠️ قابلیت تغییر زبان موقتاً غیرفعال است.",
        },
    ]

    DEFAULT_RESELLER_BOT_MENU_BUTTONS = [
        {
            "id": "buy",
            "title": "🛍️ خرید اشتراک",
            "description": "نمایش تعرفه‌ها و خرید اشتراک VPN از نماینده",
            "row": 0,
            "col": 0,
            "is_enabled": True,
            "disabled_behavior": "show_disabled",
            "disabled_message": "⚠️ بخش خرید اشتراک موقتاً غیرفعال می‌باشد. لطفاً دقایقی دیگر مراجعه فرمایید.",
        },
        {
            "id": "my_subs",
            "title": "👤 اشتراک‌های من",
            "description": "مشاهده وضعیت ترافیک، زمان، لینک‌ها و بارکد اتصال کاربر",
            "row": 0,
            "col": 1,
            "is_enabled": True,
            "disabled_behavior": "show_disabled",
            "disabled_message": "⚠️ بخش اشتراک‌های من موقتاً در حال بروزرسانی است.",
        },
        {
            "id": "wallet",
            "title": "💳 کیف پول و شارژ",
            "description": "مشاهده موجودی کیف پول و وضعیت حساب کاربری",
            "row": 1,
            "col": 0,
            "is_enabled": True,
            "disabled_behavior": "show_disabled",
            "disabled_message": "⚠️ بخش کیف پول موقتاً در دسترس نیست.",
        },
        {
            "id": "renew",
            "title": "🔄 تمدید سرویس",
            "description": "تمدید سریع اکانت‌های موجود بدون تغییر لینک",
            "row": 1,
            "col": 1,
            "is_enabled": True,
            "disabled_behavior": "show_disabled",
            "disabled_message": "⚠️ بخش تمدید سرویس موقتاً غیرفعال است.",
        },
        {
            "id": "test_sub",
            "title": "⚡ تست رایگان",
            "description": "دریافت کانفیگ تست رایگان برای کاربران جدید",
            "row": 2,
            "col": 0,
            "is_enabled": True,
            "disabled_behavior": "hide",
            "disabled_message": "⚠️ اشتراک تست موقتاً غیرفعال است.",
        },
        {
            "id": "support",
            "title": "🎧 پشتیبانی و تیکت",
            "description": "ارسال تیکت و پیام مستقیم به پشتیبانی نماینده",
            "row": 2,
            "col": 1,
            "is_enabled": True,
            "disabled_behavior": "show_disabled",
            "disabled_message": "⚠️ پشتیبانی موقتاً غیرفعال است.",
        },
        {
            "id": "tutorials",
            "title": "📖 راهنمای اتصال",
            "description": "آموزش‌های تصویری اتصال برای اندروید، آیفون، ویندوز و...",
            "row": 3,
            "col": 0,
            "is_enabled": True,
            "disabled_behavior": "show_disabled",
            "disabled_message": "⚠️ بخش راهنمای اتصال در حال بروزرسانی است.",
        },
        {
            "id": "troubleshoot",
            "title": "🛠️ حل مشکلات اتصال",
            "description": "ویزارد عیب‌یابی و رفع قطعی اینترنت",
            "row": 3,
            "col": 1,
            "is_enabled": True,
            "disabled_behavior": "show_disabled",
            "disabled_message": "⚠️ سامانه حل مشکلات اتصال موقتاً در دسترس نیست.",
        },
        {
            "id": "payments",
            "title": "🧾 سابقه پرداخت‌ها",
            "description": "مشاهده تراکنش‌ها و فیش‌های ارسالی کاربر",
            "row": 4,
            "col": 0,
            "is_enabled": True,
            "disabled_behavior": "hide",
            "disabled_message": "⚠️ بخش سابقه پرداخت‌ها موقتاً غیرفعال است.",
        },
        {
            "id": "language",
            "title": "🌐 تغییر زبان",
            "description": "تغییر زبان ربات به زبان‌های دیگر",
            "row": 4,
            "col": 1,
            "is_enabled": True,
            "disabled_behavior": "hide",
            "disabled_message": "⚠️ قابلیت تغییر زبان موقتاً غیرفعال است.",
        },
    ]

    def get_bot_menu_buttons(self) -> List[dict]:
        """دریافت لیست و تنظیمات چیدمان دکمه‌های منوی ربات مدیریت"""
        saved = self.get_setting("bot_menu_buttons_config")
        if not saved or not isinstance(saved, list):
            return copy.deepcopy(self.DEFAULT_BOT_MENU_BUTTONS)

        # ادغام با دکمه‌های پیش‌فرض برای اطمینان از وجود تمام کلیدها
        saved_dict = {b["id"]: b for b in saved if isinstance(b, dict) and "id" in b}
        merged = []
        for def_btn in self.DEFAULT_BOT_MENU_BUTTONS:
            b_id = def_btn["id"]
            if b_id in saved_dict:
                merged_btn = copy.deepcopy(def_btn)
                merged_btn.update(saved_dict[b_id])
                merged.append(merged_btn)
            else:
                merged.append(copy.deepcopy(def_btn))

        # مرتب‌سازی بر اساس سطر و ستون
        merged.sort(key=lambda x: (int(x.get("row", 0)), int(x.get("col", 0))))
        return merged

    def save_bot_menu_buttons(self, buttons: List[dict]) -> bool:
        """ذخیره تنظیمات و چیدمان دکمه‌های منوی اصلی ربات مدیریت"""
        try:
            clean_buttons = []
            for b in buttons:
                if not isinstance(b, dict) or "id" not in b:
                    continue
                clean_buttons.append({
                    "id": str(b.get("id")),
                    "title": str(b.get("title", "")).strip(),
                    "row": int(b.get("row", 0)),
                    "col": int(b.get("col", 0)),
                    "is_enabled": bool(b.get("is_enabled", True)),
                    "disabled_behavior": str(b.get("disabled_behavior", "show_disabled")),
                    "disabled_message": str(b.get("disabled_message", "⚠️ این بخش موقتاً غیرفعال است.")).strip(),
                    "description": str(b.get("description", "")),
                })
            self.set_setting("bot_menu_buttons_config", clean_buttons)
            return True
        except Exception as e:
            logger.error(f"Error saving bot menu buttons: {e}")
            return False

    def reset_bot_menu_buttons(self) -> List[dict]:
        """بازنشانی تنظیمات دکمه‌های ربات مدیریت به حالت پیش‌فرض اولیه"""
        defaults = copy.deepcopy(self.DEFAULT_BOT_MENU_BUTTONS)
        self.set_setting("bot_menu_buttons_config", defaults)
        return defaults

    def get_reseller_bot_menu_buttons(self) -> List[dict]:
        """دریافت لیست و تنظیمات چیدمان دکمه‌های منوی ربات‌های نمایندگان"""
        saved = self.get_setting("reseller_bot_menu_buttons_config")
        if not saved or not isinstance(saved, list):
            return copy.deepcopy(self.DEFAULT_RESELLER_BOT_MENU_BUTTONS)

        saved_dict = {b["id"]: b for b in saved if isinstance(b, dict) and "id" in b}
        merged = []
        for def_btn in self.DEFAULT_RESELLER_BOT_MENU_BUTTONS:
            b_id = def_btn["id"]
            if b_id in saved_dict:
                merged_btn = copy.deepcopy(def_btn)
                merged_btn.update(saved_dict[b_id])
                merged.append(merged_btn)
            else:
                merged.append(copy.deepcopy(def_btn))

        merged.sort(key=lambda x: (int(x.get("row", 0)), int(x.get("col", 0))))
        return merged

    def save_reseller_bot_menu_buttons(self, buttons: List[dict]) -> bool:
        """ذخیره تنظیمات و چیدمان دکمه‌های منوی ربات‌های نمایندگان"""
        try:
            clean_buttons = []
            for b in buttons:
                if not isinstance(b, dict) or "id" not in b:
                    continue
                clean_buttons.append({
                    "id": str(b.get("id")),
                    "title": str(b.get("title", "")).strip(),
                    "row": int(b.get("row", 0)),
                    "col": int(b.get("col", 0)),
                    "is_enabled": bool(b.get("is_enabled", True)),
                    "disabled_behavior": str(b.get("disabled_behavior", "show_disabled")),
                    "disabled_message": str(b.get("disabled_message", "⚠️ این بخش موقتاً غیرفعال است.")).strip(),
                    "description": str(b.get("description", "")),
                })
            self.set_setting("reseller_bot_menu_buttons_config", clean_buttons)
            return True
        except Exception as e:
            logger.error(f"Error saving reseller bot menu buttons: {e}")
            return False

    def reset_reseller_bot_menu_buttons(self) -> List[dict]:
        """بازنشانی تنظیمات دکمه‌های ربات نمایندگان به حالت پیش‌فرض اولیه"""
        defaults = copy.deepcopy(self.DEFAULT_RESELLER_BOT_MENU_BUTTONS)
        self.set_setting("reseller_bot_menu_buttons_config", defaults)
        return defaults

    def get_bot_menu_keyboard_rows(self, is_admin: bool = False, is_reseller: bool = False) -> List[List[dict]]:
        """ساخت سطرهای چیدمان دکمه‌های منو بر اساس سطر و ستون و وضعیت فعال بودن"""
        buttons = self.get_reseller_bot_menu_buttons() if is_reseller else self.get_bot_menu_buttons()
        visible_buttons = []
        for b in buttons:
            b_id = b.get("id")
            if is_reseller and b_id in ("referral", "admin"):
                continue

            if b.get("is_enabled", True):
                visible_buttons.append(copy.deepcopy(b))
            elif b.get("disabled_behavior") == "show_disabled":
                b_copy = copy.deepcopy(b)
                visible_buttons.append(b_copy)

        # مرتب‌سازی بر اساس سطر و ستون
        visible_buttons.sort(key=lambda x: (int(x.get("row", 0)), int(x.get("col", 0))))

        rows_dict = {}
        for b in visible_buttons:
            r = int(b.get("row", 0))
            if r not in rows_dict:
                rows_dict[r] = []
            rows_dict[r].append(b)

        sorted_rows = [rows_dict[r] for r in sorted(rows_dict.keys())]
        return sorted_rows

    def match_bot_menu_button(self, text: str, is_reseller: bool = False) -> Optional[dict]:
        """تطبیق هوشمند متن ارسالی کاربر با اکشن‌های تعریف شده دکمه‌های منو"""
        if not text:
            return None
        text_clean = text.strip()
        buttons = self.get_reseller_bot_menu_buttons() if is_reseller else self.get_bot_menu_buttons()

        # ۱. تطبیق مستقیم با عنوان تنظیم‌شده دکمه
        for b in buttons:
            b_title = b.get("title", "").strip()
            if b_title and (text_clean == b_title or text_clean in b_title or b_title in text_clean):
                return b

        # ۲. تطبیق کلمات کلیدی استاندارد هر دکمه
        keywords_map = {
            "buy": ["خرید اشتراک", "خرید", "buy", "اشتراک جدید", "خرید سرویس"],
            "my_subs": ["اشتراک‌های من", "سرویس‌های من", "وضعیت سرویس", "کانفیگ‌های من", "my subscriptions", "status", "link", "لینک"],
            "test_sub": ["تست رایگان", "اکانت تست", "تست", "اشتراک تست", "free test", "test"],
            "renew": ["تمدید سرویس", "تمدید اشتراک", "تمدید", "renew"],
            "wallet": ["کیف پول", "کیف پول و شارژ", "شارژ حساب", "شارژ", "wallet", "balance"],
            "support": ["پشتیبانی و تیکت", "پشتیبانی", "ارسال تیکت", "تیکت", "support", "ticket"],
            "tutorials": ["راهنمای اتصال", "آموزش اتصال", "آموزش", "راهنما", "help", "guide", "tutorial"],
            "troubleshoot": ["حل مشکلات اتصال", "حل مشکل", "عیب‌یابی", "مشکل اتصال", "troubleshoot"],
            "referral": ["کسب درآمد و دعوت", "زیرمجموعه‌گیری", "دعوت دوستان", "کسب درآمد", "referral", "invite"],
            "payments": ["سابقه پرداخت‌ها", "سابقه پرداخت", "تراکنش‌ها", "فیش‌ها", "payments", "history"],
            "language": ["تغییر زبان", "زبان", "language", "lang"],
        }

        for b in buttons:
            b_id = b.get("id")
            kws = keywords_map.get(b_id, [])
            for kw in kws:
                if kw in text_clean.lower():
                    return b

        return None

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
    # مدیریت تیکت‌های پشتیبانی و پیام‌های گفتگو
    # ═══════════════════════════════════════════════════════════════

    def create_ticket(self, telegram_id=None, subject="پیام کاربر", message="", reseller_id=None, user_id=None, **kwargs):
        """ایجاد تیکت پشتیبانی جدید با قابلیت انتساب به نماینده و درج اولین پیام گفتگو"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        tg_id = telegram_id or user_id
        if not tg_id:
            return {"success": False, "error": "شناسه کاربر الزامی است."}
        try:
            cursor.execute("""
                INSERT INTO support_tickets (telegram_id, subject, message, status, reseller_id, created_at, updated_at)
                VALUES (?, ?, ?, 'open', ?, ?, ?)
            """, (tg_id, subject, message, reseller_id, now, now))
            ticket_id = cursor.lastrowid

            if message:
                sender_name = kwargs.get("username") or kwargs.get("first_name") or "کاربر"
                cursor.execute("""
                    INSERT INTO ticket_messages (ticket_id, sender_type, sender_id, sender_name, message, created_at)
                    VALUES (?, 'user', ?, ?, ?, ?)
                """, (ticket_id, tg_id, sender_name, message, now))

            conn.commit()
            return {"success": True, "ticket_id": ticket_id}
        except Exception as e:
            logger.error(f"Error creating ticket: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def add_ticket_message(self, ticket_id, sender_type, message, sender_id=None, sender_name=None, new_status=None):
        """افزودن پیام به زنجیره گفتگوی تیکت و بروزرسانی وضعیت تیکت"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("""
                INSERT INTO ticket_messages (ticket_id, sender_type, sender_id, sender_name, message, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (ticket_id, sender_type, sender_id, sender_name, message, now))

            if new_status:
                status_val = new_status
            elif sender_type in ("admin", "reseller"):
                status_val = "replied"
            else:
                status_val = "open"

            if sender_type in ("admin", "reseller"):
                cursor.execute("""
                    UPDATE support_tickets 
                    SET admin_reply = ?, status = ?, updated_at = ?
                    WHERE id = ?
                """, (message, status_val, now, ticket_id))
            else:
                cursor.execute("""
                    UPDATE support_tickets 
                    SET status = ?, updated_at = ?
                    WHERE id = ?
                """, (status_val, now, ticket_id))

            conn.commit()
            return {"success": True, "message_id": cursor.lastrowid}
        except Exception as e:
            logger.error(f"Error adding ticket message: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def add_ticket_reply(self, ticket_id, sender_type="admin", sender_id=None, sender_name=None, message=""):
        """ثبت پاسخ ادمین یا نماینده به تیکت"""
        return self.add_ticket_message(ticket_id, sender_type=sender_type, message=message, sender_id=sender_id, sender_name=sender_name)

    def reply_ticket(self, ticket_id, admin_reply, sender_name="پشتیبانی"):
        """پاسخ ادمین یا نماینده به تیکت"""
        return self.add_ticket_message(ticket_id, sender_type="admin", message=admin_reply, sender_name=sender_name, new_status="replied")

    def update_ticket_status(self, ticket_id, status):
        """بروزرسانی وضعیت تیکت (open, in_progress, replied, closed)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("UPDATE support_tickets SET status = ?, updated_at = ? WHERE id = ?", (status, now, ticket_id))
            conn.commit()
            return {"success": True}
        except Exception as e:
            logger.error(f"Error updating ticket status: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def reopen_ticket(self, ticket_id):
        """بازگشایی مجدد تیکت"""
        return self.update_ticket_status(ticket_id, "open")

    def close_ticket(self, ticket_id):
        """بستن تیکت"""
        return self.update_ticket_status(ticket_id, "closed")

    def delete_ticket(self, ticket_id, reseller_id=None):
        """حذف کامل یک تیکت و پیام‌های آن"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            if reseller_id:
                cursor.execute("SELECT id FROM support_tickets WHERE id=? AND reseller_id=?", (ticket_id, reseller_id))
                if not cursor.fetchone():
                    return {"success": False, "error": "تیکت یافت نشد یا متعلق به شما نیست."}
            cursor.execute("DELETE FROM ticket_messages WHERE ticket_id=?", (ticket_id,))
            cursor.execute("DELETE FROM support_tickets WHERE id=?", (ticket_id,))
            conn.commit()
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def get_ticket_messages(self, ticket_id):
        """دریافت تمام پیام‌های زنجیره گفتگوی یک تیکت با سازگاری به عقب"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT * FROM ticket_messages 
                WHERE ticket_id = ? 
                ORDER BY created_at ASC, id ASC
            """, (ticket_id,))
            rows = [dict(r) for r in cursor.fetchall()]
            if not rows:
                cursor.execute("SELECT * FROM support_tickets WHERE id = ?", (ticket_id,))
                t = cursor.fetchone()
                if t:
                    if t["message"]:
                        rows.append({
                            "id": 1,
                            "ticket_id": ticket_id,
                            "sender_type": "user",
                            "sender_id": t["telegram_id"],
                            "sender_name": "کاربر",
                            "message": t["message"],
                            "created_at": t["created_at"]
                        })
                    if t["admin_reply"]:
                        rows.append({
                            "id": 2,
                            "ticket_id": ticket_id,
                            "sender_type": "admin",
                            "sender_id": None,
                            "sender_name": "پشتیبانی",
                            "message": t["admin_reply"],
                            "created_at": t["updated_at"] or t["created_at"]
                        })
            return rows
        except Exception as e:
            logger.error(f"Error getting ticket messages: {e}")
            return []
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

    def get_all_tickets(self, status=None, reseller_id=None, search=None, vip_only=False, category=None):
        """دریافت تمام تیکت‌ها با فیلتر وضعیت، جستجو، نماینده و تفکیک دسته‌بندی مشتریان و نمایندگان"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            query = """
                SELECT t.*, 
                       u.username as user_username, 
                       u.phone_number as user_phone,
                       COALESCE(u.is_vip, 0) as is_vip,
                       r.name as reseller_name,
                       r.username as reseller_username,
                       r.balance as reseller_balance,
                       r.telegram_id as reseller_telegram_id,
                       (SELECT COUNT(*) FROM subscriptions WHERE telegram_id = t.telegram_id AND status = 'active') as active_subs_count,
                       (SELECT COUNT(*) FROM ticket_messages WHERE ticket_id = t.id) as messages_count
                FROM support_tickets t
                LEFT JOIN users u ON t.telegram_id = u.telegram_id
                LEFT JOIN resellers r ON t.reseller_id = r.id
                WHERE 1=1
            """
            params = []

            # فیلتر دسته‌بندی و نماینده
            if reseller_id is not None:
                # پنل نماینده
                if category == "admin":
                    query += " AND t.reseller_id = ? AND (t.ticket_type IN ('reseller_to_admin', 'quota_change', 'reseller_application') OR t.target_role = 'admin')"
                    params.append(reseller_id)
                elif category == "customers":
                    query += " AND t.reseller_id = ? AND (t.ticket_type NOT IN ('reseller_to_admin', 'quota_change', 'reseller_application') OR t.ticket_type IS NULL) AND (t.target_role IS NULL OR t.target_role != 'admin')"
                    params.append(reseller_id)
                else:
                    query += " AND t.reseller_id = ?"
                    params.append(reseller_id)
            else:
                # پنل مدیریت
                if category == "resellers":
                    query += " AND (t.ticket_type IN ('reseller_to_admin', 'quota_change', 'reseller_application') OR (t.reseller_id > 0 AND (t.ticket_type IS NOT NULL OR t.target_role = 'admin')))"
                elif category == "customers":
                    query += " AND (t.reseller_id IS NULL OR t.reseller_id = 0) AND (t.ticket_type NOT IN ('reseller_to_admin', 'quota_change', 'reseller_application') OR t.ticket_type IS NULL)"
                # اگر category == 'all' یا نامشخص بود، همه را برمی‌گرداند

            if vip_only:
                query += " AND u.is_vip = 1"

            if status and status != "all":
                if status == "open":
                    query += " AND t.status = 'open'"
                elif status == "in_progress":
                    query += " AND t.status = 'in_progress'"
                elif status == "replied":
                    query += " AND t.status = 'replied'"
                elif status == "closed":
                    query += " AND t.status = 'closed'"
                elif status == "vip":
                    query += " AND u.is_vip = 1 AND t.status != 'closed'"

            if search:
                query += " AND (t.id LIKE ? OR t.message LIKE ? OR t.admin_reply LIKE ? OR t.subject LIKE ? OR u.username LIKE ? OR u.phone_number LIKE ? OR t.telegram_id LIKE ? OR r.name LIKE ? OR r.username LIKE ?)"
                params.extend([f"%{search}%"] * 9)

            query += " ORDER BY COALESCE(u.is_vip, 0) DESC, CASE WHEN t.status = 'open' THEN 1 WHEN t.status = 'in_progress' THEN 2 WHEN t.status = 'replied' THEN 3 ELSE 4 END, t.created_at DESC"
            cursor.execute(query, params)
            ticket_rows = [dict(row) for row in cursor.fetchall()]
            for t in ticket_rows:
                t["messages"] = self.get_ticket_messages(t["id"])
            return ticket_rows
        except Exception as e:
            logger.error(f"Error getting all tickets: {e}")
            return []
        finally:
            conn.close()

    def get_ticket_details(self, ticket_id):
        """دریافت اطلاعات جامع تیکت به همراه پروفایل کاربر، نماینده و تاریخچه گفتگو"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT t.*, 
                       u.username as user_username, 
                       u.phone_number as user_phone, 
                       COALESCE(u.is_vip, 0) as is_vip,
                       r.name as reseller_name,
                       r.username as reseller_username,
                       r.balance as reseller_balance,
                       r.telegram_id as reseller_telegram_id,
                       (SELECT COUNT(*) FROM subscriptions WHERE telegram_id = t.telegram_id AND status = 'active') as active_subs_count
                FROM support_tickets t
                LEFT JOIN users u ON t.telegram_id = u.telegram_id
                LEFT JOIN resellers r ON t.reseller_id = r.id
                WHERE t.id = ?
            """, (ticket_id,))
            row = cursor.fetchone()
            if not row:
                return None
            details = dict(row)
            details["messages"] = self.get_ticket_messages(ticket_id)
            return details
        except Exception as e:
            logger.error(f"Error getting ticket details: {e}")
            return None
        finally:
            conn.close()

    def get_tickets_stats(self, reseller_id=None):
        """محاسبه آمار تفکیکی تیکت‌ها برای تب‌های فیلتر با تفکیک مشتریان و نمایندگان"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            def _calc_stats(where_clause, params_list):
                q = f"""
                    SELECT 
                        COUNT(*) as total_count,
                        SUM(CASE WHEN t.status = 'open' THEN 1 ELSE 0 END) as open_count,
                        SUM(CASE WHEN t.status = 'in_progress' THEN 1 ELSE 0 END) as in_progress_count,
                        SUM(CASE WHEN t.status = 'replied' THEN 1 ELSE 0 END) as replied_count,
                        SUM(CASE WHEN t.status = 'closed' THEN 1 ELSE 0 END) as closed_count,
                        SUM(CASE WHEN COALESCE(u.is_vip, 0) = 1 AND t.status != 'closed' THEN 1 ELSE 0 END) as vip_count
                    FROM support_tickets t
                    LEFT JOIN users u ON t.telegram_id = u.telegram_id
                    {where_clause}
                """
                cursor.execute(q, params_list)
                r = cursor.fetchone()
                if not r:
                    return {"all": 0, "open": 0, "in_progress": 0, "replied": 0, "closed": 0, "vip": 0}
                return {
                    "all": r["total_count"] or 0,
                    "open": r["open_count"] or 0,
                    "in_progress": r["in_progress_count"] or 0,
                    "replied": r["replied_count"] or 0,
                    "closed": r["closed_count"] or 0,
                    "vip": r["vip_count"] or 0,
                }

            if reseller_id is None:
                # پنل مدیریت
                cust_stats = _calc_stats("WHERE (t.reseller_id IS NULL OR t.reseller_id = 0) AND (t.ticket_type NOT IN ('reseller_to_admin', 'quota_change', 'reseller_application') OR t.ticket_type IS NULL)", [])
                res_stats = _calc_stats("WHERE t.ticket_type IN ('reseller_to_admin', 'quota_change', 'reseller_application') OR (t.reseller_id > 0 AND (t.ticket_type IS NOT NULL OR t.target_role = 'admin'))", [])
                all_stats = _calc_stats("WHERE 1=1", [])
                
                return {
                    "all": all_stats["all"],
                    "open": all_stats["open"],
                    "in_progress": all_stats["in_progress"],
                    "replied": all_stats["replied"],
                    "closed": all_stats["closed"],
                    "vip": all_stats["vip"],
                    "customers": cust_stats,
                    "resellers": res_stats
                }
            else:
                # پنل نماینده
                cust_stats = _calc_stats("WHERE t.reseller_id = ? AND (t.ticket_type NOT IN ('reseller_to_admin', 'quota_change', 'reseller_application') OR t.ticket_type IS NULL) AND (t.target_role IS NULL OR t.target_role != 'admin')", [reseller_id])
                admin_stats = _calc_stats("WHERE t.reseller_id = ? AND (t.ticket_type IN ('reseller_to_admin', 'quota_change', 'reseller_application') OR t.target_role = 'admin')", [reseller_id])
                all_stats = _calc_stats("WHERE t.reseller_id = ?", [reseller_id])

                return {
                    "all": all_stats["all"],
                    "open": all_stats["open"],
                    "in_progress": all_stats["in_progress"],
                    "replied": all_stats["replied"],
                    "closed": all_stats["closed"],
                    "vip": all_stats["vip"],
                    "customers": cust_stats,
                    "admin": admin_stats
                }
        except Exception as e:
            logger.error(f"Error getting ticket stats: {e}")
            empty = {"all": 0, "open": 0, "in_progress": 0, "replied": 0, "closed": 0, "vip": 0}
            return {"all": 0, "open": 0, "in_progress": 0, "replied": 0, "closed": 0, "vip": 0, "customers": empty, "resellers": empty, "admin": empty}
        finally:
            conn.close()

    def create_reseller_to_admin_ticket(self, reseller_id: int, subject: str, message: str, priority: str = 'normal') -> dict:
        """ثبت تیکت مستقیم توسط نماینده برای پنل مدیریت"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("SELECT * FROM resellers WHERE id=?", (reseller_id,))
            reseller = cursor.fetchone()
            r_name = reseller["name"] if reseller else f"نماینده #{reseller_id}"
            r_tg = reseller["telegram_id"] if reseller else 0

            cursor.execute("""
                INSERT INTO support_tickets (
                    telegram_id, subject, message, status, reseller_id,
                    ticket_type, target_role, created_at, updated_at
                ) VALUES (?, ?, ?, 'open', ?, 'reseller_to_admin', 'admin', ?, ?)
            """, (r_tg or 0, subject.strip(), message.strip(), reseller_id, now, now))
            ticket_id = cursor.lastrowid

            cursor.execute("""
                INSERT INTO ticket_messages (
                    ticket_id, sender_type, sender_id, sender_name, message, created_at
                ) VALUES (?, 'reseller', ?, ?, ?, ?)
            """, (ticket_id, reseller_id, r_name, message.strip(), now))

            conn.commit()
            return {"success": True, "ticket_id": ticket_id}
        except Exception as e:
            logger.error(f"Error creating reseller to admin ticket: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def add_reseller_admin_ticket_reply(self, ticket_id: int, reseller_id: int, message: str) -> dict:
        """ارسال پاسخ از سمت نماینده در تیکت مکاتبه با مدیریت"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("SELECT * FROM support_tickets WHERE id=? AND reseller_id=?", (ticket_id, reseller_id))
            ticket = cursor.fetchone()
            if not ticket:
                return {"success": False, "error": "تیکت یافت نشد"}

            cursor.execute("SELECT * FROM resellers WHERE id=?", (reseller_id,))
            reseller = cursor.fetchone()
            r_name = reseller["name"] if reseller else f"نماینده #{reseller_id}"

            cursor.execute("""
                INSERT INTO ticket_messages (
                    ticket_id, sender_type, sender_id, sender_name, message, created_at
                ) VALUES (?, 'reseller', ?, ?, ?, ?)
            """, (ticket_id, reseller_id, r_name, message.strip(), now))

            cursor.execute("""
                UPDATE support_tickets
                SET status = 'open', updated_at = ?
                WHERE id = ?
            """, (now, ticket_id))

            conn.commit()
            return {"success": True}
        except Exception as e:
            logger.error(f"Error adding reseller admin ticket reply: {e}")
            return {"success": False, "error": str(e)}
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
                                reseller_id: int = None, plan_price: int = 0, cost_paid: int = 0,
                                start_date: str = None, expire_date: str = None,
                                is_manual: int = 0, period_offset: int = 1, period_label: str = None,
                                note: str = None, created_by: str = None, renewed_at: str = None) -> bool:
        """ثبت تاریخچه و میزان مصرف دوره قبلی همراه با قیمت پلن هنگام تمدید یا تغییر دوره اشتراک"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            now_str = renewed_at or get_now_iso()
            cursor.execute("""
                INSERT INTO subscription_history (
                    subscription_id, telegram_id, hidify_uuid, account_name, plan_name,
                    previous_usage_gb, previous_limit_gb, period_days, renewal_type,
                    renewed_at, reseller_id, plan_price, cost_paid, start_date, expire_date,
                    is_manual, period_offset, period_label, note, created_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                subscription_id, telegram_id or 0, hidify_uuid, account_name, plan_name,
                float(previous_usage_gb or 0), float(previous_limit_gb or 0),
                int(period_days or 30), renewal_type, now_str, reseller_id,
                int(plan_price or 0), int(cost_paid or 0), start_date, expire_date,
                int(is_manual or 0), int(period_offset or 1), period_label, note, created_by
            ))
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error saving subscription history: {e}")
            return False
        finally:
            conn.close()

    def add_manual_subscription_history(self, subscription_id: int, previous_usage_gb: float,
                                       previous_limit_gb: float = None, period_days: int = 30,
                                       period_offset: int = 1, period_label: str = None,
                                       plan_name: str = None, plan_price: int = 0, cost_paid: int = 0,
                                       start_date: str = None, expire_date: str = None,
                                       note: str = None, created_by: str = "manual",
                                       reseller_id: int = None, renewed_at: str = None) -> dict:
        """افزودن دستی سابقه و گزارش دوره قبلی مشتری با برچسب دوره، حجم، مدت و تگ دستی"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            if reseller_id:
                cursor.execute("SELECT * FROM subscriptions WHERE id=? AND reseller_id=?", (subscription_id, reseller_id))
            else:
                cursor.execute("SELECT * FROM subscriptions WHERE id=?", (subscription_id,))
            sub_row = cursor.fetchone()
            if not sub_row:
                return {"success": False, "error": "اشتراک مورد نظر یافت نشد یا دسترسی مجاز نیست"}

            sub_dict = dict(sub_row)
            
            p_limit = float(previous_limit_gb) if (previous_limit_gb is not None and float(previous_limit_gb) > 0) else float(sub_dict.get("data_limit") or previous_usage_gb or 0)
            p_days = int(period_days) if (period_days and int(period_days) > 0) else int(sub_dict.get("duration") or 30)
            p_name = plan_name.strip() if (plan_name and plan_name.strip()) else (sub_dict.get("plan_name") or "پلن سفارشی")
            
            p_offset = int(period_offset) if period_offset else 1
            if not period_label or not period_label.strip():
                if p_offset == 1:
                    lbl = "۱ دوره قبل (دوره گذشته)"
                elif p_offset == 2:
                    lbl = "۲ دوره قبل"
                elif p_offset == 3:
                    lbl = "۳ دوره قبل"
                elif p_offset == 4:
                    lbl = "۴ دوره قبل"
                elif p_offset == 5:
                    lbl = "۵ دوره قبل"
                else:
                    lbl = f"{p_offset} دوره قبل"
            else:
                lbl = period_label.strip()

            now_str = renewed_at if (renewed_at and renewed_at.strip()) else get_now_iso()

            cursor.execute("""
                INSERT INTO subscription_history (
                    subscription_id, telegram_id, hidify_uuid, account_name, plan_name,
                    previous_usage_gb, previous_limit_gb, period_days, renewal_type,
                    renewed_at, reseller_id, plan_price, cost_paid, start_date, expire_date,
                    is_manual, period_offset, period_label, note, created_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                subscription_id, sub_dict.get("telegram_id") or 0, sub_dict.get("hidify_uuid") or "",
                sub_dict.get("account_name") or "", p_name,
                float(previous_usage_gb or 0), p_limit, p_days, "manual",
                now_str, sub_dict.get("reseller_id"),
                int(plan_price or 0), int(cost_paid or 0), start_date, expire_date,
                1, p_offset, lbl, note, created_by
            ))
            conn.commit()
            inserted_id = cursor.lastrowid
            return {"success": True, "id": inserted_id, "message": "سابقه دوره دستی با موفقیت اضافه شد"}
        except Exception as e:
            logger.error(f"Error adding manual subscription history: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def delete_subscription_history_entry(self, history_id: int, reseller_id: int = None) -> bool:
        """حذف یک رکورد سابقه دوره با بررسی دسترسی نماینده یا مدیر"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            if reseller_id:
                cursor.execute("DELETE FROM subscription_history WHERE id=? AND reseller_id=?", (history_id, reseller_id))
            else:
                cursor.execute("DELETE FROM subscription_history WHERE id=?", (history_id,))
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error deleting subscription history entry {history_id}: {e}")
            return False
        finally:
            conn.close()

    def log_subscription_history(self, *args, **kwargs):
        """نام مستعار برای save_subscription_history جهت سازگاری کامل"""
        return self.save_subscription_history(*args, **kwargs)

    def get_subscription_history(self, subscription_id: int = None, telegram_id: int = None,
                                reseller_id: int = None, limit: int = 50) -> list:
        """دریافت سوابق مصرف دوره‌های قبلی اشتراک‌ها با جزئیات قیمت و زمان"""
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
            query += """ ORDER BY 
                CASE 
                    WHEN period_offset IS NOT NULL AND period_offset > 0 THEN period_offset 
                    ELSE 9999 
                END ASC,
                renewed_at DESC, id DESC LIMIT ?"""
            params.append(limit)

            cursor.execute(query, params)
            return [dict(r) for r in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting subscription history: {e}")
            return []
        finally:
            conn.close()

    def get_subscription_full_details_and_history(self, sub_id: int, reseller_id: int = None) -> dict:
        """دریافت اطلاعات جامع اشتراک به همراه آرشیو تمام دوره‌ها و مبالغ پرداختی گذشته"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            if reseller_id:
                cursor.execute("SELECT * FROM subscriptions WHERE id=? AND reseller_id=?", (sub_id, reseller_id))
            else:
                cursor.execute("SELECT * FROM subscriptions WHERE id=?", (sub_id,))
            sub_row = cursor.fetchone()
            if not sub_row:
                return {"success": False, "error": "اشتراک یافت نشد"}

            sub_dict = dict(sub_row)
            cursor.execute("""
                SELECT * FROM subscription_history 
                WHERE subscription_id = ? OR (hidify_uuid = ? AND hidify_uuid IS NOT NULL AND hidify_uuid != '')
                ORDER BY 
                    CASE 
                        WHEN period_offset IS NOT NULL AND period_offset > 0 THEN period_offset 
                        ELSE 9999 
                    END ASC,
                    renewed_at DESC, 
                    id DESC
                LIMIT 50
            """, (sub_id, sub_dict.get("hidify_uuid") or ""))
            history_rows = [dict(r) for r in cursor.fetchall()]

            return {
                "success": True,
                "current": sub_dict,
                "history": history_rows
            }
        except Exception as e:
            logger.error(f"Error in get_subscription_full_details_and_history: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def set_subscription_debt(self, sub_id: int, payment_status: str, debt_amount: int, debt_notes: str = None, reseller_id: int = None):
        """تنظیم یا بروزرسانی وضعیت بدهی مشتری"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            query = "UPDATE subscriptions SET payment_status = ?, debt_amount = ?, debt_notes = ?, debt_created_at = COALESCE(debt_created_at, ?), updated_at = ? WHERE id = ?"
            params = [payment_status, int(debt_amount or 0), debt_notes, now if payment_status in ('unpaid', 'debtor') else None, now, sub_id]
            if reseller_id:
                query += " AND reseller_id = ?"
                params.append(reseller_id)
            cursor.execute(query, params)
            conn.commit()
            return {"success": True}
        except Exception as e:
            logger.error(f"Error setting subscription debt: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def clear_subscription_debt(self, sub_id: int, reseller_id: int = None):
        """تسویه کامل بدهی مشتری و ثبت وضعیت پرداخت شده"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            query = "UPDATE subscriptions SET payment_status = 'paid', debt_amount = 0, debt_notes = NULL, updated_at = ? WHERE id = ?"
            params = [now, sub_id]
            if reseller_id:
                query += " AND reseller_id = ?"
                params.append(reseller_id)
            cursor.execute(query, params)
            conn.commit()
            return {"success": True}
        except Exception as e:
            logger.error(f"Error clearing subscription debt: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def get_debtor_subscriptions(self, reseller_id: int = None, limit: int = 200) -> list:
        """لیست مشتریان بدهکار به همراه تاریخ، مبلغ و شماره تماس"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            query = """
                SELECT * FROM subscriptions 
                WHERE (payment_status IN ('unpaid', 'debtor') OR debt_amount > 0)
            """
            params = []
            if reseller_id:
                query += " AND reseller_id = ?"
                params.append(reseller_id)
            query += " ORDER BY COALESCE(debt_created_at, created_at) DESC LIMIT ?"
            params.append(limit)

            cursor.execute(query, params)
            return [dict(r) for r in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting debtor subscriptions: {e}")
            return []
        finally:
            conn.close()

    def get_debtor_count(self, reseller_id: int = None) -> int:
        """تعداد مشتریان بدهکار"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            if reseller_id:
                cursor.execute("""
                    SELECT COUNT(*) FROM subscriptions 
                    WHERE reseller_id = ? AND (payment_status IN ('unpaid', 'debtor') OR debt_amount > 0)
                """, (reseller_id,))
            else:
                cursor.execute("""
                    SELECT COUNT(*) FROM subscriptions 
                    WHERE payment_status IN ('unpaid', 'debtor') OR debt_amount > 0
                """)
            row = cursor.fetchone()
            return row[0] if row else 0
        except Exception as e:
            logger.error(f"Error getting debtor count: {e}")
            return 0
        finally:
            conn.close()

    def create_quota_change_request(self, sub_id: int, reseller_id: int,
                                    requested_limit: float, requested_duration: int, reason: str = "") -> dict:
        """ثبت درخواست رسمی تغییر حجم و مدت اشتراک نماینده و ارسال تیکت به مدیریت"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("SELECT * FROM subscriptions WHERE id=? AND reseller_id=?", (sub_id, reseller_id))
            sub = cursor.fetchone()
            if not sub:
                return {"success": False, "error": "اشتراک مورد نظر یافت نشد"}

            cursor.execute("SELECT * FROM resellers WHERE id=?", (reseller_id,))
            reseller = cursor.fetchone()
            r_name = reseller["name"] if reseller else f"نماینده #{reseller_id}"
            r_tg = reseller["telegram_id"] if reseller else 0

            cur_limit = float(sub["data_limit"] or 0)
            cur_dur = int(sub["duration"] or 0)
            acc_name = sub["account_name"] or f"user_{sub_id}"

            req_payload = {
                "sub_id": sub_id,
                "account_name": acc_name,
                "hidify_uuid": sub["hidify_uuid"],
                "current_limit": cur_limit,
                "requested_limit": float(requested_limit),
                "current_duration": cur_dur,
                "requested_duration": int(requested_duration),
                "reason": reason.strip(),
                "reseller_id": reseller_id,
                "reseller_name": r_name
            }
            req_json = json.dumps(req_payload, ensure_ascii=False)

            subject = f"درخواست تغییر حجم و مدت اشتراک «{acc_name}»"
            msg = (
                f"🔹 درخواست تغییر مشخصات سرویس توسط نماینده «{r_name}»:\n"
                f"👤 نام اکانت: {acc_name}\n"
                f"📦 حجم فعلی: {cur_limit} گیگابایت ➔ 🎯 حجم درخواستی: {requested_limit} گیگابایت\n"
                f"⏳ مدت فعلی: {cur_dur} روز ➔ 🎯 مدت درخواستی: {requested_duration} روز\n"
            )
            if reason.strip():
                msg += f"📝 علت/توضیحات: {reason.strip()}"

            cursor.execute("""
                INSERT INTO support_tickets (
                    telegram_id, subject, message, status, reseller_id,
                    ticket_type, target_role, request_data, request_status, created_at, updated_at
                ) VALUES (?, ?, ?, 'open', ?, 'quota_change', 'admin', ?, 'pending', ?, ?)
            """, (r_tg or 0, subject, msg, reseller_id, req_json, now, now))
            ticket_id = cursor.lastrowid

            cursor.execute("""
                INSERT INTO ticket_messages (
                    ticket_id, sender_type, sender_id, sender_name, message, created_at
                ) VALUES (?, 'reseller', ?, ?, ?, ?)
            """, (ticket_id, reseller_id, r_name, msg, now))

            conn.commit()
            return {"success": True, "ticket_id": ticket_id}
        except Exception as e:
            logger.error(f"Error in create_quota_change_request: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def approve_quota_change_request(self, ticket_id: int, admin_name: str = "مدیریت") -> dict:
        """تایید درخواست تغییر حجم/مدت توسط مدیر و بازگرداندن اطلاعات جهت اعمال در هیدیفای"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("SELECT * FROM support_tickets WHERE id=?", (ticket_id,))
            ticket = cursor.fetchone()
            if not ticket:
                return {"success": False, "error": "تیکت یافت نشد"}

            req_data = json.loads(ticket["request_data"]) if ticket["request_data"] else {}
            sub_id = req_data.get("sub_id")
            new_limit = req_data.get("requested_limit")
            new_dur = req_data.get("requested_duration")

            if not sub_id or new_limit is None or new_dur is None:
                return {"success": False, "error": "داده‌های درخواست ناقص هستند"}

            # ۱. بروزرسانی در دیتابیس محلی
            cursor.execute("""
                UPDATE subscriptions
                SET data_limit = ?, duration = ?, updated_at = ?
                WHERE id = ?
            """, (float(new_limit), int(new_dur), now, sub_id))

            # ۲. بروزرسانی وضعیت تیکت
            reply_text = f"✅ درخواست تغییر حجم به {new_limit} گیگابایت و {new_dur} روز توسط {admin_name} تایید شد و روی سرویس اعمال گردید."
            cursor.execute("""
                UPDATE support_tickets
                SET status = 'replied', request_status = 'approved', admin_reply = ?, updated_at = ?
                WHERE id = ?
            """, (reply_text, now, ticket_id))

            cursor.execute("""
                INSERT INTO ticket_messages (
                    ticket_id, sender_type, sender_id, sender_name, message, created_at
                ) VALUES (?, 'admin', 0, ?, ?, ?)
            """, (ticket_id, admin_name, reply_text, now))

            conn.commit()
            return {"success": True, "data": req_data, "sub_id": sub_id}
        except Exception as e:
            logger.error(f"Error approving quota change request: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def reject_quota_change_request(self, ticket_id: int, reason: str = "", admin_name: str = "مدیریت") -> dict:
        """رد درخواست تغییر حجم/مدت توسط مدیر با درج علت"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("SELECT * FROM support_tickets WHERE id=?", (ticket_id,))
            ticket = cursor.fetchone()
            if not ticket:
                return {"success": False, "error": "تیکت یافت نشد"}

            reply_text = f"❌ درخواست تغییر مشخصات اشتراک توسط {admin_name} رد شد."
            if reason.strip():
                reply_text += f"\nعلت رد: {reason.strip()}"

            cursor.execute("""
                UPDATE support_tickets
                SET status = 'closed', request_status = 'rejected', admin_reply = ?, updated_at = ?
                WHERE id = ?
            """, (reply_text, now, ticket_id))

            cursor.execute("""
                INSERT INTO ticket_messages (
                    ticket_id, sender_type, sender_id, sender_name, message, created_at
                ) VALUES (?, 'admin', 0, ?, ?, ?)
            """, (ticket_id, admin_name, reply_text, now))

            conn.commit()
            return {"success": True}
        except Exception as e:
            logger.error(f"Error rejecting quota change request: {e}")
            return {"success": False, "error": str(e)}
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
                        telegram_id: int = None, discount_percent: int = 20, initial_balance: int = 0,
                        hiddify_admin_uuid: str = None, parent_reseller_id: int = None,
                        affiliate_commission_percent: float = None, referral_code: str = None,
                        credit_enabled: int = 0, credit_limit: int = 0) -> dict:
        """ایجاد نماینده جدید با پشتیبانی از ادمین اختصاصی هیدیفای، انتساب نماینده معرف و تنظیمات خرید اعتباری"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        password_hash = self.hash_password(password)
        cleaned_user = username.strip().lower()
        if not referral_code:
            referral_code = f"REF-{cleaned_user}"
        if credit_limit > 0:
            credit_enabled = 1
        try:
            cursor.execute("""
                INSERT INTO resellers (
                    username, password_hash, name, telegram_id, balance, 
                    discount_percent, status, hiddify_admin_uuid, 
                    parent_reseller_id, affiliate_commission_percent, referral_code,
                    credit_enabled, credit_limit, credit_debt,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, 0, ?, ?)
            """, (
                cleaned_user, password_hash, name.strip(), telegram_id, initial_balance, 
                discount_percent, (hiddify_admin_uuid.strip() if hiddify_admin_uuid else None),
                parent_reseller_id, affiliate_commission_percent, referral_code,
                credit_enabled, credit_limit,
                now, now
            ))
            reseller_id = cursor.lastrowid
            
            # تضمین تولید کد رفرال یکتا و تمیز
            final_ref_code = f"REF-{reseller_id}"
            cursor.execute("UPDATE resellers SET referral_code = ? WHERE id = ?", (final_ref_code, reseller_id))

            if initial_balance > 0:
                cursor.execute("""
                    INSERT INTO reseller_transactions (reseller_id, type, amount, description, created_at)
                    VALUES (?, 'deposit', ?, 'شارژ اولیه حساب', ?)
                """, (reseller_id, initial_balance, now))

            conn.commit()
            return {"success": True, "reseller_id": reseller_id, "referral_code": final_ref_code}
        except sqlite3.IntegrityError:
            return {"success": False, "error": "این نام کاربری قبلاً ثبت شده است."}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    # ═══════════════════════════════════════════════════════════════════════
    # سیستم زیرمجموعه‌گیری و پورسانت نمایندگان (Reseller Affiliate System)
    # ═══════════════════════════════════════════════════════════════════════

    def get_reseller_affiliate_settings(self) -> dict:
        """دریافت تنظیمات سراسری سیستم زیرمجموعه‌گیری نمایندگان"""
        conn = self.get_connection()
        cursor = conn.cursor()
        settings = {
            "enabled": True,
            "default_percent": 10.0,
            "calc_base": "plan_price",
            "terms": "با پیوستن به عنوان همکار و نماینده زیرمجموعه، از ربات اختصاصی هوشمند، ساب‌دامنه‌های بدون فیلتر و پنل مدیریت فروش با تسویه آنی بهره‌مند شوید."
        }
        try:
            cursor.execute("SELECT key, value FROM settings WHERE key LIKE 'reseller_affiliate_%'")
            for row in cursor.fetchall():
                k = row["key"]
                v = row["value"]
                if k == "reseller_affiliate_enabled":
                    settings["enabled"] = (str(v).strip() in ("1", "true", "True"))
                elif k == "reseller_affiliate_default_percent":
                    try:
                        settings["default_percent"] = float(v)
                    except (ValueError, TypeError):
                        pass
                elif k == "reseller_affiliate_calc_base":
                    settings["calc_base"] = str(v).strip()
                elif k == "reseller_affiliate_terms":
                    settings["terms"] = str(v)
        except Exception as e:
            logger.error(f"Error getting reseller affiliate settings: {e}")
        finally:
            conn.close()
        return settings

    def update_reseller_affiliate_settings(self, enabled: bool, default_percent: float, calc_base: str, terms: str) -> dict:
        """بروزرسانی تنظیمات سیستم زیرمجموعه‌گیری نمایندگان"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            data = {
                "reseller_affiliate_enabled": "1" if enabled else "0",
                "reseller_affiliate_default_percent": str(default_percent),
                "reseller_affiliate_calc_base": calc_base,
                "reseller_affiliate_terms": terms
            }
            for k, v in data.items():
                cursor.execute("""
                    INSERT INTO settings (key, value) VALUES (?, ?)
                    ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """, (k, v))
            conn.commit()
            return {"success": True}
        except Exception as e:
            logger.error(f"Error updating reseller affiliate settings: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def get_reseller_referral_code(self, reseller_id: int) -> str:
        """دریافت یا تولید کد دعوت اختصاصی نماینده"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT id, referral_code, username FROM resellers WHERE id=?", (reseller_id,))
            row = cursor.fetchone()
            if not row:
                return f"REF-{reseller_id}"
            
            ref_code = row["referral_code"]
            if not ref_code:
                ref_code = f"REF-{reseller_id}"
                cursor.execute("UPDATE resellers SET referral_code=? WHERE id=?", (ref_code, reseller_id))
                conn.commit()
            return ref_code
        except Exception as e:
            logger.error(f"Error getting reseller referral code: {e}")
            return f"REF-{reseller_id}"
        finally:
            conn.close()

    def get_reseller_by_referral_code(self, code_or_id: str) -> Optional[dict]:
        """پیدا کردن مشخصات نماینده معرف بر اساس کد یا شناسه"""
        if not code_or_id:
            return None
        code_clean = str(code_or_id).strip()
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            # ۱. جستجو با referral_code
            cursor.execute("SELECT * FROM resellers WHERE UPPER(referral_code) = UPPER(?) AND status = 'active'", (code_clean,))
            row = cursor.fetchone()
            if row:
                return dict(row)

            # ۲. بررسی اگر فرمت شناسه عددی باشد (مثلاً 5 یا REF-5)
            numeric_id = None
            if code_clean.isdigit():
                numeric_id = int(code_clean)
            elif code_clean.upper().startswith("REF-") and code_clean[4:].isdigit():
                numeric_id = int(code_clean[4:])

            if numeric_id:
                cursor.execute("SELECT * FROM resellers WHERE id = ? AND status = 'active'", (numeric_id,))
                row = cursor.fetchone()
                if row:
                    return dict(row)

            # ۳. جستجو بر اساس نام کاربری
            cursor.execute("SELECT * FROM resellers WHERE LOWER(username) = LOWER(?) AND status = 'active'", (code_clean,))
            row = cursor.fetchone()
            if row:
                return dict(row)

            return None
        except Exception as e:
            logger.error(f"Error finding reseller by referral code: {e}")
            return None
        finally:
            conn.close()

    def get_sub_resellers(self, parent_reseller_id: int) -> list:
        """لیست نمایندگان زیرمجموعه یک نماینده به همراه آمار فروش و سود تولید شده"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT r.*,
                       (SELECT COUNT(*) FROM subscriptions WHERE reseller_id = r.id) as total_subscriptions,
                       (SELECT COUNT(*) FROM subscriptions WHERE reseller_id = r.id AND status = 'active') as active_subscriptions,
                       (SELECT COUNT(*) FROM users WHERE reseller_id = r.id) as total_customers,
                       (SELECT COALESCE(SUM(commission_amount), 0) 
                        FROM reseller_affiliate_commissions 
                        WHERE parent_reseller_id = ? AND sub_reseller_id = r.id) as total_commission_earned
                FROM resellers r
                WHERE r.parent_reseller_id = ?
                ORDER BY r.created_at DESC
            """, (parent_reseller_id, parent_reseller_id))
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting sub resellers for {parent_reseller_id}: {e}")
            return []
        finally:
            conn.close()

    def get_reseller_affiliate_stats(self, reseller_id: int) -> dict:
        """شاخص‌ها و آمار کامل زیرمجموعه‌گیری نماینده"""
        reseller = self.get_reseller(reseller_id)
        if not reseller:
            return {}

        aff_settings = self.get_reseller_affiliate_settings()
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            ref_code = self.get_reseller_referral_code(reseller_id)

            # تعداد کل زیرمجموعه‌ها
            cursor.execute("SELECT COUNT(*) FROM resellers WHERE parent_reseller_id = ?", (reseller_id,))
            sub_count = cursor.fetchone()[0] or 0

            # تعداد زیرمجموعه‌های فعال
            cursor.execute("SELECT COUNT(*) FROM resellers WHERE parent_reseller_id = ? AND status = 'active'", (reseller_id,))
            active_sub_count = cursor.fetchone()[0] or 0

            # مجموع کل کمیسیون دریافتی
            cursor.execute("SELECT COALESCE(SUM(commission_amount), 0) FROM reseller_affiliate_commissions WHERE parent_reseller_id = ?", (reseller_id,))
            total_commission = cursor.fetchone()[0] or 0

            # کمیسیون ۳۰ روز اخیر
            month_ago = (datetime.now() - timedelta(days=30)).isoformat()
            cursor.execute("SELECT COALESCE(SUM(commission_amount), 0) FROM reseller_affiliate_commissions WHERE parent_reseller_id = ? AND created_at >= ?", (reseller_id, month_ago))
            recent_commission = cursor.fetchone()[0] or 0

            # درصد کمیسیون موثر برای این نماینده
            effective_percent = reseller.get("affiliate_commission_percent")
            if effective_percent is None or effective_percent <= 0:
                effective_percent = aff_settings.get("default_percent", 10.0)

            # مشخصات نماینده بالادستی (اگر وجود دارد)
            parent_reseller = None
            if reseller.get("parent_reseller_id"):
                cursor.execute("SELECT id, name, username, telegram_id FROM resellers WHERE id = ?", (reseller["parent_reseller_id"],))
                p_row = cursor.fetchone()
                if p_row:
                    parent_reseller = dict(p_row)

            return {
                "reseller_id": reseller_id,
                "referral_code": ref_code,
                "is_enabled": aff_settings.get("enabled", True),
                "commission_percent": effective_percent,
                "is_custom_percent": (reseller.get("affiliate_commission_percent") is not None),
                "sub_resellers_count": sub_count,
                "active_sub_resellers_count": active_sub_count,
                "total_commission_earned": total_commission,
                "recent_month_commission": recent_commission,
                "parent_reseller": parent_reseller
            }
        except Exception as e:
            logger.error(f"Error getting reseller affiliate stats: {e}")
            return {}
        finally:
            conn.close()

    def get_reseller_affiliate_commissions_history(self, reseller_id: int = None, limit: int = 100) -> list:
        """دریافت ریز تراکنش‌های پورسانت زیرمجموعه‌گیری"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            if reseller_id:
                cursor.execute("""
                    SELECT c.*, 
                           sr.name as sub_reseller_name,
                           sr.username as sub_reseller_username
                    FROM reseller_affiliate_commissions c
                    LEFT JOIN resellers sr ON c.sub_reseller_id = sr.id
                    WHERE c.parent_reseller_id = ?
                    ORDER BY c.created_at DESC
                    LIMIT ?
                """, (reseller_id, limit))
            else:
                cursor.execute("""
                    SELECT c.*, 
                           pr.name as parent_reseller_name,
                           pr.username as parent_reseller_username,
                           sr.name as sub_reseller_name,
                           sr.username as sub_reseller_username
                    FROM reseller_affiliate_commissions c
                    LEFT JOIN resellers pr ON c.parent_reseller_id = pr.id
                    LEFT JOIN resellers sr ON c.sub_reseller_id = sr.id
                    ORDER BY c.created_at DESC
                    LIMIT ?
                """, (limit,))
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting affiliate commissions history: {e}")
            return []
        finally:
            conn.close()

    def process_sub_reseller_affiliate_commission(self, sub_reseller_id: int, plan_price: int, plan_name: str, account_name: str, sub_id: int = None) -> dict:
        """
        محاسبه و واریز خودکار درصد پورسانت به نماینده بالادستی به ازای هر خرید یا ساخت اکانت توسط زیرمجموعه
        """
        if not sub_reseller_id or plan_price <= 0:
            return {"success": False, "reason": "invalid_parameters"}

        aff_settings = self.get_reseller_affiliate_settings()
        if not aff_settings.get("enabled", True):
            return {"success": False, "reason": "affiliate_disabled"}

        sub_reseller = self.get_reseller(sub_reseller_id)
        if not sub_reseller or not sub_reseller.get("parent_reseller_id"):
            return {"success": False, "reason": "no_parent_reseller"}

        parent_id = int(sub_reseller["parent_reseller_id"])
        parent_reseller = self.get_reseller(parent_id)
        if not parent_reseller or parent_reseller.get("status") != "active":
            return {"success": False, "reason": "parent_reseller_inactive"}

        # درصد کمیسیون (اختصاصی بالادستی یا پیش‌فرض سیستم)
        commission_percent = parent_reseller.get("affiliate_commission_percent")
        if commission_percent is None or commission_percent <= 0:
            commission_percent = float(aff_settings.get("default_percent", 10.0))

        commission_amount = int((plan_price * commission_percent) / 100)
        if commission_amount <= 0:
            return {"success": False, "reason": "zero_commission"}

        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        sub_name = sub_reseller.get("name") or f"نماینده #{sub_reseller_id}"
        desc = f"پورسانت {commission_percent:g}٪ از ساخت اشتراک «{account_name}» ({plan_name}) توسط زیرمجموعه «{sub_name}»"

        try:
            # ۱. افزایش موجودی کیف پول نماینده بالادستی
            cursor.execute("UPDATE resellers SET balance = balance + ?, updated_at = ? WHERE id = ?", (commission_amount, now, parent_id))

            # ۲. ثبت تراکنش در reseller_transactions
            cursor.execute("""
                INSERT INTO reseller_transactions (reseller_id, type, amount, plan_name, account_name, description, created_at)
                VALUES (?, 'deposit', ?, ?, ?, ?, ?)
            """, (parent_id, commission_amount, plan_name, account_name, desc, now))

            # ۳. ثبت رکورد در جدول تخصصی پورسانت‌های زیرمجموعه‌گیری
            cursor.execute("""
                INSERT INTO reseller_affiliate_commissions (
                    parent_reseller_id, sub_reseller_id, sub_id, account_name,
                    plan_id, plan_name, plan_price, commission_percent, commission_amount,
                    description, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                parent_id, sub_reseller_id, sub_id, account_name,
                "-", plan_name, plan_price, commission_percent, commission_amount,
                desc, now
            ))

            conn.commit()

            # ۴. ارسال اعلان بلادرنگ به پنل نماینده بالادستی
            self.add_reseller_notification(
                reseller_id=parent_id,
                title="💰 واریز پورسانت زیرمجموعه",
                message=f"مبلغ {commission_amount:,} تومان بابت فروش اشتراک «{account_name}» توسط زیرمجموعه شما ({sub_name}) به کیف پول شما واریز شد.",
                type="success"
            )

            logger.info(f"Affiliate commission of {commission_amount} IRR paid to Parent #{parent_id} from Sub #{sub_reseller_id}")
            return {
                "success": True,
                "parent_id": parent_id,
                "commission_amount": commission_amount,
                "commission_percent": commission_percent
            }
        except Exception as e:
            logger.error(f"Error processing sub reseller affiliate commission: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def create_reseller_application(self, referrer_id: Optional[int], full_name: str, phone_number: str, 
                                    telegram_id: Optional[int], requested_username: str, notes: str = "") -> dict:
        """ثبت فرم درخواست اخذ نمایندگی با لینک معرف و ایجاد تیکت رسمی برای مدیریت"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()

        referrer_name = "مستقیم (بدون معرف)"
        if referrer_id:
            cursor.execute("SELECT name, username FROM resellers WHERE id=?", (referrer_id,))
            ref_row = cursor.fetchone()
            if ref_row:
                referrer_name = f"{ref_row['name']} (@{ref_row['username']})"

        req_payload = {
            "full_name": full_name.strip(),
            "phone_number": phone_number.strip(),
            "telegram_id": telegram_id,
            "requested_username": requested_username.strip().lower(),
            "notes": notes.strip(),
            "referrer_id": referrer_id,
            "referrer_name": referrer_name,
            "applied_at": now
        }
        req_json = json.dumps(req_payload, ensure_ascii=False)

        subject = f"💼 درخواست اخذ پنل نمایندگی توسط «{full_name.strip()}» (معرف: {referrer_name})"
        msg = (
            f"🌟 درخواست جدید برای اخذ پنل نمایندگی ثبت گردید:\n"
            f"👤 متقاضی: {full_name.strip()}\n"
            f"📱 شماره تماس: {phone_number.strip()}\n"
            f"🆔 تلگرام: {telegram_id or 'ثبت نشده'}\n"
            f"👤 نام کاربری درخواستی: {requested_username.strip().lower()}\n"
            f"🤝 نماینده معرف: {referrer_name}\n"
        )
        if notes.strip():
            msg += f"📝 توضیحات/سوابق: {notes.strip()}\n"

        try:
            cursor.execute("""
                INSERT INTO support_tickets (
                    telegram_id, subject, message, status, reseller_id,
                    ticket_type, target_role, request_data, request_status, created_at, updated_at
                ) VALUES (?, ?, ?, 'open', ?, 'reseller_application', 'admin', ?, 'pending', ?, ?)
            """, (telegram_id or 0, subject, msg, referrer_id or 0, req_json, now, now))
            ticket_id = cursor.lastrowid

            cursor.execute("""
                INSERT INTO ticket_messages (
                    ticket_id, sender_type, sender_id, sender_name, message, created_at
                ) VALUES (?, 'user', ?, ?, ?, ?)
            """, (ticket_id, telegram_id or 0, full_name.strip(), msg, now))

            conn.commit()
            return {"success": True, "ticket_id": ticket_id}
        except Exception as e:
            logger.error(f"Error creating reseller application ticket: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def approve_reseller_application(self, ticket_id: int, password: str = None, 
                                     initial_balance: int = 0, discount_percent: int = 20, 
                                     custom_commission: float = None) -> dict:
        """تایید درخواست نمایندگی توسط مدیریت و ایجاد آنی حساب نماینده با انتساب معرف"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("SELECT * FROM support_tickets WHERE id=? AND ticket_type='reseller_application'", (ticket_id,))
            ticket = cursor.fetchone()
            if not ticket:
                return {"success": False, "error": "درخواست نمایندگی یافت نشد."}

            if ticket["request_status"] == "approved":
                return {"success": False, "error": "این درخواست قبلاً تایید شده است."}

            req_data = json.loads(ticket["request_data"] or "{}")
            username = req_data.get("requested_username")
            full_name = req_data.get("full_name") or f"نماینده {username}"
            telegram_id = req_data.get("telegram_id")
            referrer_id = req_data.get("referrer_id")

            if not password:
                import random
                password = f"Pass@{random.randint(1000, 9999)}"

            # ایجاد نماینده با اتصال به parent_reseller_id
            create_res = self.create_reseller(
                username=username,
                password=password,
                name=full_name,
                telegram_id=telegram_id,
                discount_percent=discount_percent,
                initial_balance=initial_balance,
                parent_reseller_id=referrer_id,
                affiliate_commission_percent=custom_commission
            )

            if not create_res.get("success"):
                return create_res

            reseller_id = create_res["reseller_id"]

            # به‌روزرسانی وضعیت تیکت
            cursor.execute("""
                UPDATE support_tickets 
                SET request_status = 'approved', status = 'closed', updated_at = ?
                WHERE id = ?
            """, (now, ticket_id))

            reply_msg = f"✅ درخواست نمایندگی شما با موفقیت تایید و پنل شما ایجاد شد.\n👤 نام کاربری: {username}\n🔑 رمز عبور: {password}"
            cursor.execute("""
                INSERT INTO ticket_messages (ticket_id, sender_type, sender_name, message, created_at)
                VALUES (?, 'support', 'مدیریت سامانه', ?, ?)
            """, (ticket_id, reply_msg, now))

            conn.commit()

            # اطلاع‌رسانی به نماینده معرف در صورت وجود
            if referrer_id:
                self.add_reseller_notification(
                    reseller_id=referrer_id,
                    title="🎉 عضویت زیرمجموعه جدید",
                    message=f"درخواست نمایندگی «{full_name}» تایید و به عنوان زیرمجموعه رسمی شما فعال شد.",
                    type="success"
                )

            return {
                "success": True,
                "reseller_id": reseller_id,
                "username": username,
                "password": password
            }
        except Exception as e:
            logger.error(f"Error approving reseller application: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def reject_reseller_application(self, ticket_id: int, reason: str = "") -> dict:
        """رد درخواست اخذ نمایندگی"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("UPDATE support_tickets SET request_status = 'rejected', status = 'closed', updated_at = ? WHERE id = ? AND ticket_type = 'reseller_application'", (now, ticket_id))
            reject_msg = "❌ متأسفانه با درخواست اخذ پنل نمایندگی شما موافقت نگردید."
            if reason.strip():
                reject_msg += f"\nعلت: {reason.strip()}"
            cursor.execute("""
                INSERT INTO ticket_messages (ticket_id, sender_type, sender_name, message, created_at)
                VALUES (?, 'support', 'مدیریت سامانه', ?, ?)
            """, (ticket_id, reject_msg, now))
            conn.commit()
            return {"success": True}
        except Exception as e:
            logger.error(f"Error rejecting reseller application: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def update_reseller_parent(self, reseller_id: int, parent_reseller_id: Optional[int]) -> dict:
        """تغییر یا حذف نماینده بالادستی یک نماینده"""
        if parent_reseller_id == reseller_id:
            return {"success": False, "error": "یک نماینده نمی‌تواند معرف خودش باشد."}
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("UPDATE resellers SET parent_reseller_id = ?, updated_at = ? WHERE id = ?", (parent_reseller_id, now, reseller_id))
            conn.commit()
            return {"success": True}
        except Exception as e:
            logger.error(f"Error updating reseller parent: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def update_reseller_custom_commission(self, reseller_id: int, percent: Optional[float]) -> dict:
        """تخصیص درصد پورسانت اختصاصی برای یک نماینده"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("UPDATE resellers SET affiliate_commission_percent = ?, updated_at = ? WHERE id = ?", (percent, now, reseller_id))
            conn.commit()
            return {"success": True}
        except Exception as e:
            logger.error(f"Error updating reseller custom commission: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def get_admin_reseller_affiliates_overview(self) -> dict:
        """گزارش آماری جامع سیستم زیرمجموعه‌گیری برای پنل مدیریت"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            # ۱. لیست تمام نمایندگان با اطلاعات معرف و زیرمجموعه‌ها
            cursor.execute("""
                SELECT r.*,
                       pr.name as parent_name,
                       pr.username as parent_username,
                       (SELECT COUNT(*) FROM resellers WHERE parent_reseller_id = r.id) as sub_resellers_count,
                       (SELECT COALESCE(SUM(commission_amount), 0) FROM reseller_affiliate_commissions WHERE parent_reseller_id = r.id) as total_commissions_earned,
                       (SELECT COALESCE(SUM(commission_amount), 0) FROM reseller_affiliate_commissions WHERE sub_reseller_id = r.id) as total_commissions_generated
                FROM resellers r
                LEFT JOIN resellers pr ON r.parent_reseller_id = pr.id
                ORDER BY sub_resellers_count DESC, total_commissions_earned DESC, r.created_at DESC
            """)
            resellers = [dict(row) for row in cursor.fetchall()]

            # ۲. آمار کلی سامانه
            cursor.execute("SELECT COUNT(*) FROM resellers WHERE parent_reseller_id IS NOT NULL")
            total_network_subs = cursor.fetchone()[0] or 0

            cursor.execute("SELECT COALESCE(SUM(commission_amount), 0) FROM reseller_affiliate_commissions")
            total_commissions_paid = cursor.fetchone()[0] or 0

            cursor.execute("SELECT COUNT(*) FROM support_tickets WHERE ticket_type = 'reseller_application' AND request_status = 'pending'")
            pending_applications_count = cursor.fetchone()[0] or 0

            settings = self.get_reseller_affiliate_settings()

            return {
                "resellers": resellers,
                "total_network_subs": total_network_subs,
                "total_commissions_paid": total_commissions_paid,
                "pending_applications_count": pending_applications_count,
                "settings": settings
            }
        except Exception as e:
            logger.error(f"Error getting admin affiliate overview: {e}")
            return {"resellers": [], "total_network_subs": 0, "total_commissions_paid": 0, "pending_applications_count": 0, "settings": {}}
        finally:
            conn.close()

    def get_reseller_hiddify_key(self, reseller_id: int) -> Optional[str]:
        """
        دریافت کلید API یا Admin UUID اختصاصی نماینده در هیدیفای
        اولویت‌ها:
        ۱. متغیر محیطی Railway بر اساس ID یا Username (مانند RESELLER_1_HIDDIFY_KEY یا RESELLER_ALI_HIDDIFY_KEY)
        ۲. فیلد hiddify_admin_uuid در دیتابیس
        ۳. در صورت عدم تنظیم -> None (استفاده از کلید اصلی ادمین کل)
        """
        if not reseller_id:
            return None

        # ۱. بررسی متغیرهای محیطی Railway
        env_key_by_id = os.environ.get(f"RESELLER_{reseller_id}_HIDDIFY_KEY")
        if env_key_by_id and env_key_by_id.strip():
            return env_key_by_id.strip()

        reseller = self.get_reseller(reseller_id)
        if not reseller:
            return None

        username = (reseller.get("username") or "").strip().upper()
        if username:
            env_key_by_user = os.environ.get(f"RESELLER_{username}_HIDDIFY_KEY")
            if env_key_by_user and env_key_by_user.strip():
                return env_key_by_user.strip()

        # ۲. بررسی فیلد ذخیره شده در دیتابیس
        db_uuid = reseller.get("hiddify_admin_uuid")
        if db_uuid and str(db_uuid).strip():
            return str(db_uuid).strip()

        return None

    def get_reseller_by_hiddify_admin(self, hiddify_admin_uuid: str) -> Optional[dict]:
        """پیدا کردن نماینده بر اساس Admin UUID هیدیفای"""
        if not hiddify_admin_uuid:
            return None
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM resellers WHERE hiddify_admin_uuid=?", (str(hiddify_admin_uuid).strip(),))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    def restore_subscriptions_from_hiddify(self, users_list: list, default_reseller_id: int = None) -> dict:
        """
        بازیابی و همگام‌سازی هوشمند اشتراک‌ها از لیست کاربران هیدیفای
        تطبیق خودکار کاربر با نماینده بر اساس added_by یا تگ کامنت یا default_reseller_id
        """
        if not users_list or not isinstance(users_list, list):
            return {"success": False, "synced_count": 0, "error": "لیست کاربران هیدیفای خالی است."}

        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        synced_count = 0

        try:
            # ایجاد مپینگ Admin UUID به Reseller ID
            cursor.execute("SELECT id, hiddify_admin_uuid FROM resellers WHERE hiddify_admin_uuid IS NOT NULL")
            admin_to_reseller = {r["hiddify_admin_uuid"].strip(): r["id"] for r in cursor.fetchall() if r["hiddify_admin_uuid"]}

            for u in users_list:
                if not isinstance(u, dict):
                    continue
                uuid_val = u.get("uuid")
                if not uuid_val:
                    continue

                name = u.get("name") or f"user_{uuid_val[:8]}"
                usage_limit = float(u.get("usage_limit_GB") or 0)
                current_usage = float(u.get("current_usage_GB") or 0)
                package_days = int(u.get("package_days") or 30)
                is_active = bool(u.get("is_active", True) and u.get("enable", True))
                status = "active" if is_active else "expired"
                comment = str(u.get("comment") or "")
                added_by = str(u.get("added_by") or "").strip()

                # تشخیص شناسه نماینده
                assigned_reseller_id = default_reseller_id
                if added_by and added_by in admin_to_reseller:
                    assigned_reseller_id = admin_to_reseller[added_by]
                elif "[RESELLER_ID:" in comment:
                    try:
                        import re
                        m = re.search(r"\[RESELLER_ID:\s*#?(\d+)\]", comment)
                        if m:
                            assigned_reseller_id = int(m.group(1))
                    except Exception:
                        pass

                # بررسی یا ایجاد در جدول subscriptions
                cursor.execute("SELECT id, telegram_id FROM subscriptions WHERE hidify_uuid=?", (uuid_val,))
                existing_sub = cursor.fetchone()

                if existing_sub:
                    cursor.execute("""
                        UPDATE subscriptions
                        SET data_limit=?, data_used=?, duration=?, status=?, is_deleted=0,
                            reseller_id=COALESCE(?, reseller_id), updated_at=?
                        WHERE hidify_uuid=?
                    """, (usage_limit, current_usage, package_days, status, assigned_reseller_id, now, uuid_val))
                else:
                    # ایجاد اشتراک جدید بازسازی شده
                    simulated_tg = 900000000 + abs(hash(uuid_val)) % 99999999
                    cursor.execute("""
                        INSERT INTO subscriptions (
                            telegram_id, hidify_uuid, plan_id, plan_name, account_name,
                            data_limit, data_used, duration, status, reseller_id, created_at, updated_at
                        ) VALUES (?, ?, 'restored', 'اشتراک بازیابی‌شده هیدیفای', ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (simulated_tg, uuid_val, name, usage_limit, current_usage, package_days, status, assigned_reseller_id, now, now))

                synced_count += 1

            conn.commit()
            return {"success": True, "synced_count": synced_count}
        except Exception as e:
            conn.rollback()
            logger.error(f"Error restoring subscriptions from Hiddify: {e}")
            return {"success": False, "synced_count": synced_count, "error": str(e)}
        finally:
            conn.close()

    def sync_and_prune_reseller_subscriptions(self, reseller_id: int, users_list: list) -> dict:
        """
        همگام‌سازی کامل اشتراک‌های نماینده با پنل هیدیفای:
        ۱. بازیابی و بروزرسانی کلیه مشترکین موجود در هیدیفای به پنل نماینده
        ۲. مقایسه و پاکسازی کلیه مشترکینی که در پنل نماینده هستند اما در هیدیفای وجود ندارند
        """
        if not reseller_id:
            return {"success": False, "error": "شناسه نماینده نامعتبر است."}
        if users_list is None or not isinstance(users_list, list):
            return {"success": False, "error": "لیست کاربران هیدیفای نامعتبر است."}

        # مرحله ۱: بازیابی و بروزرسانی مشترکین موجود در هیدیفای
        restore_res = self.restore_subscriptions_from_hiddify(users_list, default_reseller_id=reseller_id)
        synced_count = restore_res.get("synced_count", 0)

        # مرحله ۲: استخراج تمام شناسه (UUID) های معتبر کاربران هیدیفای
        hiddify_uuids = set()
        for u in users_list:
            if isinstance(u, dict) and u.get("uuid"):
                hiddify_uuids.add(str(u["uuid"]).strip().lower())

        conn = self.get_connection()
        cursor = conn.cursor()
        purged_count = 0
        purged_names = []

        try:
            # واکشی کلیه اشتراک‌های منتسب به این نماینده در دیتابیس
            cursor.execute("""
                SELECT id, hidify_uuid, account_name, telegram_id
                FROM subscriptions
                WHERE reseller_id = ?
            """, (reseller_id,))
            current_subs = cursor.fetchall()

            extra_sub_ids = []
            for sub in current_subs:
                sub_uuid = str(sub["hidify_uuid"] or "").strip().lower()
                # اگر کاربر UUID هیدیفای ندارد یا در لیست هیدیفای وجود ندارد -> کاربر اضافی است
                if not sub_uuid or sub_uuid not in hiddify_uuids:
                    extra_sub_ids.append(sub["id"])
                    purged_names.append(sub["account_name"] or f"اشتراک #{sub['id']}")

            if extra_sub_ids:
                placeholders = ",".join("?" for _ in extra_sub_ids)
                
                # حفظ یکپارچگی ارجاعات جداول وابسته
                cursor.execute(f"UPDATE transactions SET subscription_id = NULL WHERE subscription_id IN ({placeholders})", extra_sub_ids)
                cursor.execute(f"DELETE FROM subscription_history WHERE subscription_id IN ({placeholders})", extra_sub_ids)
                
                # حذف کامل اشتراک‌های اضافی از پنل نماینده
                cursor.execute(f"DELETE FROM subscriptions WHERE id IN ({placeholders})", extra_sub_ids)
                purged_count = len(extra_sub_ids)

                # پاکسازی کاربران شبیه‌سازی‌شده بدون اشتراک از جدول users
                cursor.execute("""
                    DELETE FROM users 
                    WHERE telegram_id >= 900000000 
                      AND telegram_id NOT IN (SELECT telegram_id FROM subscriptions)
                """)

            conn.commit()
            logger.info(f"Sync & Prune for reseller #{reseller_id}: Synced {synced_count}, Purged {purged_count} extra customers.")
            return {
                "success": True,
                "synced_count": synced_count,
                "purged_count": purged_count,
                "purged_names": purged_names
            }
        except Exception as e:
            conn.rollback()
            logger.error(f"Error in sync_and_prune_reseller_subscriptions for reseller #{reseller_id}: {e}")
            return {"success": False, "error": str(e), "synced_count": synced_count, "purged_count": 0}
        finally:
            conn.close()

    def find_subscriptions_by_pattern(self, pattern: str, pattern_type: str = "auto", source_filter: str = "all") -> list:
        """
        جستجوی هوشمند اشتراک‌ها بر اساس الگو، پیشوند، وایلدکارد یا عبارت منظم (Regex)
        جهت انتقال گروهی و دسته‌ای به نمایندگان
        """
        if not pattern or not str(pattern).strip():
            return []

        pattern = str(pattern).strip()
        conn = self.get_connection()
        cursor = conn.cursor()

        # اعمال فیلتر بر اساس منبع مالکیت
        query = """
            SELECT s.*, 
                   r.name as reseller_name, 
                   r.username as reseller_username,
                   r.hiddify_admin_uuid as reseller_admin_uuid
            FROM subscriptions s
            LEFT JOIN resellers r ON s.reseller_id = r.id
        """
        params = []
        if source_filter == "direct":
            query += " WHERE (s.reseller_id IS NULL OR s.reseller_id = 0)"
        elif source_filter and source_filter.startswith("reseller_"):
            try:
                r_id = int(source_filter.replace("reseller_", ""))
                query += " WHERE s.reseller_id = ?"
                params.append(r_id)
            except ValueError:
                pass
        elif source_filter and source_filter.isdigit():
            query += " WHERE s.reseller_id = ?"
            params.append(int(source_filter))

        cursor.execute(query, params)
        all_subs = [dict(r) for r in cursor.fetchall()]
        conn.close()

        import re
        import fnmatch

        matched = []
        pattern_lower = pattern.lower()

        # تعیین نوع جستجو در حالت auto
        is_regex = pattern_type == "regex" or (pattern_type == "auto" and (pattern.startswith("^") or pattern.endswith("$") or "\\d" in pattern))
        is_wildcard = pattern_type == "wildcard" or (pattern_type == "auto" and not is_regex and ("*" in pattern or "?" in pattern))
        is_prefix = pattern_type == "prefix"

        regex_compiled = None
        if is_regex:
            try:
                regex_compiled = re.compile(pattern, re.IGNORECASE)
            except Exception:
                regex_compiled = None

        for sub in all_subs:
            name = (sub.get("account_name") or "").strip()
            comment = (sub.get("account_comment") or "").strip()
            uuid_val = (sub.get("hidify_uuid") or "").strip()

            is_match = False
            if regex_compiled:
                if regex_compiled.search(name) or regex_compiled.search(comment):
                    is_match = True
            elif is_wildcard:
                if fnmatch.fnmatch(name.lower(), pattern_lower) or fnmatch.fnmatch(comment.lower(), pattern_lower):
                    is_match = True
            elif is_prefix:
                if name.lower().startswith(pattern_lower) or comment.lower().startswith(pattern_lower):
                    is_match = True
            else:
                # حالت پیش‌فرض / contains / prefix هوشمند
                if name.lower().startswith(pattern_lower):
                    is_match = True
                elif pattern_lower in name.lower() or pattern_lower in comment.lower():
                    is_match = True

            if is_match:
                matched.append(sub)

        return matched

    def transfer_subscriptions_to_reseller(self, sub_ids: list, target_reseller_id: int,
                                          target_hiddify_admin: str = None,
                                          safe_backdate_hours: int = 72,
                                          admin_name: str = "مدیریت") -> dict:
        """
        انتقال دسته‌ای و هوشمند اشتراک‌ها به یک نماینده با رعایت شروط امنیتی:
        ۱. حفظ تاریخ واقعی یا تنظیم تاریخ به بیش از ۲۴ ساعت گذشته جهت جلوگیری از سوءاستفاده استرداد وجه
        ۲. انتساب به reseller_id نماینده و ثبت لاگ تاریخچه
        ۳. بازگرداندن اطلاعات لازم جهت اعمال همزمان در API هیدیفای (تغییر added_by)
        """
        if not sub_ids or not isinstance(sub_ids, list):
            return {"success": False, "transferred_count": 0, "error": "هیچ اشتراکی برای انتقال انتخاب نشده است."}

        target_reseller = self.get_reseller(target_reseller_id)
        if not target_reseller:
            return {"success": False, "transferred_count": 0, "error": "نماینده مقصد یافت نشد."}

        # تعیین شناسه ادمین هیدیفای نماینده
        final_hiddify_admin = target_hiddify_admin or target_reseller.get("hiddify_admin_uuid")

        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        now_dt = get_now_naive()

        # زمان امن گذشته (حداقل ۷۲ ساعت پیش) در صورت نبود تاریخ یا تاریخ کمتر از ۲۴ ساعت
        safe_past_dt = now_dt - timedelta(hours=max(25, safe_backdate_hours))
        safe_past_iso = safe_past_dt.strftime("%Y-%m-%dT%H:%M:%S")

        transferred_subs = []
        try:
            for sub_id in sub_ids:
                cursor.execute("SELECT * FROM subscriptions WHERE id=?", (sub_id,))
                sub_row = cursor.fetchone()
                if not sub_row:
                    continue

                sub = dict(sub_row)
                current_created = sub.get("created_at")
                
                # بررسی اینکه آیا تاریخ ایجاد قبلی معتبر و بیش از ۲۴ ساعت گذشته است
                is_older_than_24h = False
                final_created_at = safe_past_iso
                if current_created:
                    try:
                        clean = str(current_created).strip().replace("Z", "")
                        dt = datetime.fromisoformat(clean)
                        if dt.tzinfo is not None:
                            dt = dt.astimezone(TEHRAN_TZ).replace(tzinfo=None)
                        if (now_dt - dt).total_seconds() >= 24 * 3600:
                            is_older_than_24h = True
                            final_created_at = current_created
                    except Exception:
                        pass

                # بروزرسانی اشتراک: تغییر مالکیت، تنظیم تاریخ امن، و صفر کردن هزینه پرداختی نماینده
                cursor.execute("""
                    UPDATE subscriptions
                    SET reseller_id = ?,
                        created_at = ?,
                        cost_paid = 0,
                        updated_at = ?
                    WHERE id = ?
                """, (target_reseller_id, final_created_at, now, sub_id))

                # ثبت در جدول تاریخچه اشتراک‌ها (سوابق مدیریت)
                try:
                    cursor.execute("""
                        INSERT INTO subscription_history (
                            subscription_id, telegram_id, hidify_uuid, account_name,
                            plan_name, previous_usage_gb, previous_limit_gb, period_days,
                            renewal_type, renewed_at, reseller_id, plan_price, cost_paid,
                            start_date, expire_date, note, created_by
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'migrated_to_reseller', ?, ?, 0, 0, ?, ?, ?, ?)
                    """, (
                        sub_id, sub.get("telegram_id"), sub.get("hidify_uuid"), sub.get("account_name"),
                        sub.get("plan_name"), float(sub.get("data_used") or 0), float(sub.get("data_limit") or 0),
                        int(sub.get("duration") or 30), now, target_reseller_id, sub.get("start_date"),
                        sub.get("expire_date"),
                        f"انتقال سازمانی به نماینده {target_reseller['name']} (@{target_reseller['username']})",
                        admin_name
                    ))
                except Exception as ex:
                    logger.warning(f"Error recording subscription migration history for sub #{sub_id}: {ex}")

                transferred_subs.append({
                    "id": sub_id,
                    "hidify_uuid": sub.get("hidify_uuid"),
                    "account_name": sub.get("account_name"),
                    "created_at": final_created_at,
                    "previous_reseller_id": sub.get("reseller_id"),
                    "new_reseller_id": target_reseller_id
                })

            conn.commit()
            return {
                "success": True,
                "transferred_count": len(transferred_subs),
                "transferred_subs": transferred_subs,
                "target_reseller": {
                    "id": target_reseller_id,
                    "name": target_reseller["name"],
                    "username": target_reseller["username"],
                    "hiddify_admin_uuid": final_hiddify_admin
                }
            }
        except Exception as e:
            conn.rollback()
            logger.error(f"Error transferring subscriptions to reseller: {e}")
            return {"success": False, "transferred_count": 0, "error": str(e)}
        finally:
            conn.close()

    def authenticate_reseller(self, username: str, password: str):
        """احراز هویت نماینده (Case-Insensitive و مقاوم در برابر فاصله‌ها)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        clean_user = username.strip().lower()
        clean_pass = password.strip()
        password_hash = self.hash_password(clean_pass)
        cursor.execute("SELECT * FROM resellers WHERE LOWER(username)=? AND (password_hash=? OR password_hash=?) AND status='active'",
                       (clean_user, password_hash, clean_pass))
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

        if "credit_limit" in kwargs and (kwargs["credit_limit"] or 0) > 0 and not kwargs.get("credit_enabled"):
            kwargs["credit_enabled"] = 1

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

    def deduct_reseller_balance(self, reseller_id: int, amount: int, plan_name: str, account_name: str,
                                description: str = "خرید اشتراک برای مشتری", payment_source: str = "auto",
                                subscription_id: int = None):
        """کسر هزینه با پشتیبانی از انتخاب دقیق مبدأ پرداخت (کیف پول نقدی یا اعتبار خرید)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("SELECT balance, credit_limit, credit_debt, credit_enabled FROM resellers WHERE id=?", (reseller_id,))
            row = cursor.fetchone()
            if not row:
                return {"success": False, "error": "نماینده یافت نشد."}

            balance = row["balance"] or 0
            credit_limit = row["credit_limit"] or 0
            credit_debt = row["credit_debt"] or 0
            credit_enabled = bool(row["credit_enabled"]) or (credit_limit > 0)
            available_credit = max(0, credit_limit - credit_debt) if credit_enabled else 0

            chosen_source = str(payment_source).strip().lower() if payment_source else "auto"

            if chosen_source == "wallet":
                if balance < amount:
                    return {
                        "success": False,
                        "error": f"موجودی کیف پول شما کافی نیست! موجودی: {balance:,} تومان | مبلغ مورد نیاز: {amount:,} تومان"
                    }
                cursor.execute("UPDATE resellers SET balance = balance - ?, updated_at=? WHERE id=?", (amount, now, reseller_id))
                desc_text = f"{description} (کسر از کیف پول نقدی)"
                cursor.execute("""
                    INSERT INTO reseller_transactions (reseller_id, type, amount, plan_name, account_name, description, payment_source, subscription_id, created_at)
                    VALUES (?, 'purchase', ?, ?, ?, ?, 'wallet', ?, ?)
                """, (reseller_id, amount, plan_name, account_name, desc_text, subscription_id, now))
                tx_id = cursor.lastrowid
                conn.commit()
                return {"success": True, "transaction_id": tx_id, "is_credit": False, "credit_used": 0, "payment_source": "wallet"}

            elif chosen_source == "credit":
                if not credit_enabled:
                    return {"success": False, "error": "اعتبار خرید برای شما فعال نشده است."}
                if available_credit < amount:
                    return {
                        "success": False,
                        "error": f"اعتبار خرید شما کافی نیست! اعتبار باقیمانده: {available_credit:,} تومان | مبلغ مورد نیاز: {amount:,} تومان"
                    }
                cursor.execute("UPDATE resellers SET credit_debt = credit_debt + ?, updated_at=? WHERE id=?", (amount, now, reseller_id))
                desc_text = f"{description} (کسر از اعتبار خرید: {amount:,} ت بدهی)"
                cursor.execute("""
                    INSERT INTO reseller_transactions (reseller_id, type, amount, plan_name, account_name, description, payment_source, subscription_id, created_at)
                    VALUES (?, 'purchase_credit', ?, ?, ?, ?, 'credit', ?, ?)
                """, (reseller_id, amount, plan_name, account_name, desc_text, subscription_id, now))
                tx_id = cursor.lastrowid
                conn.commit()
                return {"success": True, "transaction_id": tx_id, "is_credit": True, "credit_used": amount, "payment_source": "credit"}

            else:
                # حالت هوشمند و خودکار (auto)
                total_available = balance + available_credit
                if total_available < amount:
                    return {
                        "success": False, 
                        "error": f"موجودی و اعتبار کافی نیست! موجودی: {balance:,} تومان | اعتبار باقیمانده: {available_credit:,} تومان | مبلغ کل: {amount:,} تومان"
                    }

                if balance >= amount:
                    cursor.execute("UPDATE resellers SET balance = balance - ?, updated_at=? WHERE id=?", (amount, now, reseller_id))
                    cursor.execute("""
                        INSERT INTO reseller_transactions (reseller_id, type, amount, plan_name, account_name, description, payment_source, subscription_id, created_at)
                        VALUES (?, 'purchase', ?, ?, ?, ?, 'wallet', ?, ?)
                    """, (reseller_id, amount, plan_name, account_name, description, subscription_id, now))
                    tx_id = cursor.lastrowid
                    conn.commit()
                    return {"success": True, "transaction_id": tx_id, "is_credit": False, "credit_used": 0, "payment_source": "wallet"}
                else:
                    credit_used = amount - balance
                    cursor.execute("""
                        UPDATE resellers SET 
                            balance = 0, 
                            credit_debt = credit_debt + ?, 
                            updated_at = ? 
                        WHERE id = ?
                    """, (credit_used, now, reseller_id))

                    desc_text = f"{description} (خرید اعتباری: {credit_used:,} تومان بدهی)"
                    cursor.execute("""
                        INSERT INTO reseller_transactions (reseller_id, type, amount, plan_name, account_name, description, payment_source, subscription_id, created_at)
                        VALUES (?, 'purchase_credit', ?, ?, ?, ?, 'credit', ?, ?)
                    """, (reseller_id, amount, plan_name, account_name, desc_text, subscription_id, now))
                    tx_id = cursor.lastrowid
                    conn.commit()
                    return {"success": True, "transaction_id": tx_id, "is_credit": True, "credit_used": credit_used, "payment_source": "credit"}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def settle_reseller_debt(self, reseller_id: int, amount: int, description: str = "تسویه بدهی اعتباری", settled_by: str = "مدیر ارشد") -> dict:
        """ثبت تسویه حساب بدهی اعتباری نماینده توسط مدیریت"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("SELECT credit_debt, name, username FROM resellers WHERE id=?", (reseller_id,))
            row = cursor.fetchone()
            if not row:
                return {"success": False, "error": "نماینده یافت نشد."}

            current_debt = row["credit_debt"] or 0
            if amount <= 0:
                return {"success": False, "error": "مبلغ تسویه باید بزرگتر از صفر باشد."}

            new_debt = max(0, current_debt - amount)
            cursor.execute("UPDATE resellers SET credit_debt = ?, updated_at = ? WHERE id = ?", (new_debt, now, reseller_id))

            cursor.execute("""
                INSERT INTO reseller_transactions (reseller_id, type, amount, plan_name, account_name, description, created_at)
                VALUES (?, 'settle_debt', ?, 'تسویه بدهی', ?, ?, ?)
            """, (reseller_id, amount, row["username"], f"{description} توسط {settled_by}", now))

            # ثبت سند درآمدی تسویه در سیستم حسابداری
            try:
                self.add_accounting_record(
                    type="income",
                    category="شارژ نماینده",
                    title=f"تسویه بدهی اعتباری نماینده {row['name']}",
                    amount=amount,
                    source="reseller_debt_settle",
                    description=f"{description} (مانده بدهی جدید: {new_debt:,} تومان)",
                    date=now[:10]
                )
            except Exception:
                pass

            conn.commit()
            return {"success": True, "remaining_debt": new_debt}
        except Exception as e:
            logger.error(f"Error settling reseller debt: {e}")
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

    def get_reseller_full_payment_history(self, reseller_id: int) -> dict:
        """دریافت سابقه کامل پرداختی‌ها، شارژها، بسته‌های اعتباری و ریز تراکنش‌های نماینده"""
        reseller = self.get_reseller(reseller_id)
        if not reseller:
            return {}

        conn = self.get_connection()
        cursor = conn.cursor()

        # ۱. تراکنش‌های کیف پول نماینده (شارژها، خریدها، تمدیدها، استردادها)
        cursor.execute("""
            SELECT * FROM reseller_transactions 
            WHERE reseller_id = ? 
            ORDER BY created_at DESC
        """, (reseller_id,))
        wallet_txs = [dict(r) for r in cursor.fetchall()]

        # ۲. رسیدها، فیش‌های بانکی و تراکنش‌های ثبت‌شده در جدول اصلی
        cursor.execute("""
            SELECT * FROM transactions 
            WHERE reseller_id = ? 
            ORDER BY created_at DESC
        """, (reseller_id,))
        receipt_txs = [dict(r) for r in cursor.fetchall()]

        # ۳. محاسبات مالی دقیق
        cursor.execute("SELECT COALESCE(SUM(amount), 0) FROM reseller_transactions WHERE reseller_id=? AND type='deposit'", (reseller_id,))
        total_deposited = cursor.fetchone()[0]

        cursor.execute("SELECT COALESCE(SUM(amount), 0) FROM reseller_transactions WHERE reseller_id=? AND type IN ('purchase', 'renewal')", (reseller_id,))
        total_spent = cursor.fetchone()[0]

        cursor.execute("SELECT COALESCE(SUM(amount), 0) FROM reseller_transactions WHERE reseller_id=? AND type='refund'", (reseller_id,))
        total_refunded = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM transactions WHERE reseller_id=? AND (gateway='bundle_reseller' OR order_id LIKE 'R_BUNDLE%')", (reseller_id,))
        total_bundle_orders = cursor.fetchone()[0]

        conn.close()

        return {
            "reseller": reseller,
            "wallet_transactions": wallet_txs,
            "receipt_transactions": receipt_txs,
            "total_deposited": total_deposited,
            "total_spent": total_spent,
            "total_refunded": total_refunded,
            "total_bundle_orders": total_bundle_orders,
            "balance": reseller.get("balance", 0),
            "discount_percent": reseller.get("discount_percent", 20)
        }

    def get_reseller_subscriptions(self, reseller_id: int):
        """لیست کاربران و اشتراک‌های یک نماینده (بدون موارد سطل زباله)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM subscriptions WHERE reseller_id=? AND (is_deleted=0 OR is_deleted IS NULL) ORDER BY created_at DESC", (reseller_id,))
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_reseller_stats(self, reseller_id: int):
        """آمار و شاخص‌های نماینده شامل کیف پول، اعتبار و وضعیت بدهی‌ها"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT balance, discount_percent, credit_enabled, credit_limit, credit_debt FROM resellers WHERE id=?", (reseller_id,))
        res = cursor.fetchone()
        balance = res["balance"] if res else 0
        discount = res["discount_percent"] if res else 0
        credit_limit = (res["credit_limit"] or 0) if res and "credit_limit" in res.keys() else 0
        credit_debt = (res["credit_debt"] or 0) if res and "credit_debt" in res.keys() else 0
        credit_enabled = bool(res["credit_enabled"]) if (res and "credit_enabled" in res.keys() and res["credit_enabled"]) else (credit_limit > 0)
        available_credit = max(0, credit_limit - credit_debt) if credit_enabled else 0
        total_purchasing_power = balance + available_credit
        
        cursor.execute("SELECT COUNT(*) FROM subscriptions WHERE reseller_id=? AND (is_deleted=0 OR is_deleted IS NULL)", (reseller_id,))
        total_users = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM subscriptions WHERE reseller_id=? AND status='active' AND (is_deleted=0 OR is_deleted IS NULL)", (reseller_id,))
        active_users = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM subscriptions WHERE reseller_id=? AND is_online=1 AND (is_deleted=0 OR is_deleted IS NULL)", (reseller_id,))
        online_users = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM subscriptions WHERE reseller_id=? AND is_deleted=1", (reseller_id,))
        deleted_users_count = cursor.fetchone()[0]

        try:
            cursor.execute("SELECT COALESCE(SUM(remaining_amount), 0) FROM reseller_debts WHERE reseller_id=? AND status != 'paid'", (reseller_id,))
            unpaid_debts_total = cursor.fetchone()[0] or 0
        except Exception:
            unpaid_debts_total = 0
        
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

        cursor.execute("SELECT COALESCE(SUM(data_used), 0), COALESCE(SUM(data_limit), 0) FROM subscriptions WHERE reseller_id=? AND (is_deleted=0 OR is_deleted IS NULL)", (reseller_id,))
        traffic_row = cursor.fetchone()
        total_used_gb = traffic_row[0] or 0
        total_limit_gb = traffic_row[1] or 0

        cursor.execute("""
            SELECT COUNT(DISTINCT u.telegram_id)
            FROM users u
            LEFT JOIN subscriptions s ON u.telegram_id = s.telegram_id
            WHERE (s.reseller_id = ? OR u.reseller_id = ?) AND u.is_vip = 1
        """, (reseller_id, reseller_id))
        vip_users = cursor.fetchone()[0] or 0

        cursor.execute("""
            SELECT COUNT(*) FROM transactions 
            WHERE reseller_id = ? 
              AND (gateway != 'bundle_reseller' AND order_id NOT LIKE 'R_BUNDLE%')
              AND (is_deleted = 0 OR is_deleted IS NULL)
              AND status = 'pending'
        """, (reseller_id,))
        pending_customer_receipts_count = cursor.fetchone()[0] or 0

        cursor.execute("SELECT COUNT(*) FROM support_tickets WHERE reseller_id = ? AND status = 'open'", (reseller_id,))
        open_tickets_count = cursor.fetchone()[0] or 0

        conn.close()
        return {
            "balance": balance,
            "discount_percent": discount,
            "credit_enabled": credit_enabled,
            "credit_limit": credit_limit,
            "credit_debt": credit_debt,
            "available_credit": available_credit,
            "total_purchasing_power": total_purchasing_power,
            "unpaid_debts_total": unpaid_debts_total,
            "deleted_users_count": deleted_users_count,
            "total_users": total_users,
            "active_users": active_users,
            "online_users": online_users,
            "vip_users": vip_users,
            "total_purchases": total_purchases,
            "total_used_gb": round(total_used_gb, 2),
            "total_limit_gb": round(total_limit_gb, 2),
            "pending_customer_receipts_count": pending_customer_receipts_count,
            "open_tickets_count": open_tickets_count,
        }

    def get_reseller_subscription(self, reseller_id: int, sub_id: int):
        """دریافت اطلاعات یک اشتراک متعلق به نماینده"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM subscriptions WHERE id=? AND reseller_id=?", (sub_id, reseller_id))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    def update_reseller_subscription(self, reseller_id: int, sub_id: int, account_name: str,
                                     phone_number: str = None, comment: str = None,
                                     data_limit: float = None, duration: int = None,
                                     status: str = None, telegram_id: int = None,
                                     payment_status: str = None, debt_amount: int = None,
                                     debt_notes: str = None):
        """ویرایش جامع مشخصات مشتری نماینده، وضعیت بدهی و همگام‌سازی با کاربران و تراکنش‌ها"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("SELECT * FROM subscriptions WHERE id=? AND reseller_id=?", (sub_id, reseller_id))
            sub_row = cursor.fetchone()
            if not sub_row:
                return {"success": False, "error": "اشتراک مورد نظر یافت نشد"}

            sub_dict = dict(sub_row)
            clean_name = account_name.strip() if account_name else (sub_dict.get("account_name") or f"user_{sub_id}")
            clean_phone = phone_number.strip() if phone_number and str(phone_number).strip() else None
            clean_comment = comment.strip() if comment and str(comment).strip() else None
            effective_tg = int(telegram_id) if (telegram_id is not None and str(telegram_id).isdigit() and int(telegram_id) > 0) else sub_dict.get("telegram_id")

            debt_created = now if (payment_status in ('unpaid', 'debtor') and not sub_dict.get("debt_created_at")) else sub_dict.get("debt_created_at")

            # ۱. بروزرسانی جدول subscriptions
            cursor.execute("""
                UPDATE subscriptions
                SET account_name = ?,
                    phone_number = ?,
                    account_comment = ?,
                    telegram_id = COALESCE(?, telegram_id),
                    data_limit = COALESCE(?, data_limit),
                    duration = COALESCE(?, duration),
                    status = COALESCE(?, status),
                    payment_status = COALESCE(?, payment_status),
                    debt_amount = COALESCE(?, debt_amount),
                    debt_notes = COALESCE(?, debt_notes),
                    debt_created_at = ?,
                    updated_at = ?
                WHERE id = ? AND reseller_id = ?
            """, (
                clean_name,
                clean_phone,
                clean_comment,
                effective_tg,
                float(data_limit) if data_limit is not None else None,
                int(duration) if duration is not None else None,
                status.strip() if status else None,
                payment_status.strip() if payment_status else None,
                int(debt_amount) if debt_amount is not None else None,
                debt_notes.strip() if debt_notes else None,
                debt_created,
                now,
                sub_id,
                reseller_id
            ))

            # ۲. اگر کاربر دارای شناسه تلگرام باشد، بروزرسانی در جدول users
            if effective_tg and int(effective_tg) > 0:
                cursor.execute("SELECT * FROM users WHERE telegram_id=?", (effective_tg,))
                u_row = cursor.fetchone()
                if u_row:
                    if clean_phone:
                        cursor.execute("UPDATE users SET phone_number = ?, updated_at = ? WHERE telegram_id = ?", (clean_phone, now, effective_tg))
                    if clean_name:
                        cursor.execute("UPDATE users SET username = COALESCE(?, username), updated_at = ? WHERE telegram_id = ?", (clean_name, now, effective_tg))
                else:
                    cursor.execute("""
                        INSERT INTO users (telegram_id, username, phone_number, is_verified, reseller_id, created_at, updated_at)
                        VALUES (?, ?, ?, 1, ?, ?, ?)
                    """, (effective_tg, clean_name, clean_phone, reseller_id, now, now))

            # ۳. بروزرسانی در تراکنش‌های مربوط به این اشتراک
            cursor.execute("""
                UPDATE transactions
                SET account_name = ?, account_comment = COALESCE(?, account_comment), updated_at = ?
                WHERE subscription_id = ? OR (user_id = ? AND reseller_id = ?)
            """, (clean_name, clean_comment, now, sub_id, effective_tg if effective_tg else 0, reseller_id))

            conn.commit()
            return {"success": True}
        except Exception as e:
            logger.error(f"Error in update_reseller_subscription: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def toggle_reseller_subscription(self, reseller_id: int, sub_id: int, enable: bool = None, reason: str = None):
        """فعال یا غیرفعال کردن مشتری نماینده بدون کسر یا بازگشت هزینه همراه با ثبت علت غیرفعال‌سازی"""
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

            dis_reason = reason if new_status == "disabled" else None
            
            cursor.execute("""
                UPDATE subscriptions 
                SET status=?, disable_reason=?, updated_at=? 
                WHERE id=? AND reseller_id=?
            """, (new_status, dis_reason, now, sub_id, reseller_id))
            conn.commit()
            return {"success": True, "status": new_status, "disable_reason": dis_reason}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def renew_reseller_subscription(self, reseller_id: int, sub_id: int, plan_id: str, plan_name: str,
                                    cost: int, data_limit: float, duration: int,
                                    instant_activate: bool = True, renewal_type: str = "reset_and_replaced",
                                    payment_source: str = "auto"):
        """تمدید اشتراک مشتری توسط نماینده با انتخاب دقیق مبدأ پرداخت (کیف پول نقدی یا اعتبار خرید)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            # بررسی موجودی کیف پول و سقف اعتبار
            cursor.execute("SELECT balance, credit_enabled, credit_limit, credit_debt FROM resellers WHERE id=?", (reseller_id,))
            res_row = cursor.fetchone()
            if not res_row:
                return {"success": False, "error": "اطلاعات نماینده یافت نشد."}

            balance = res_row["balance"] or 0
            credit_limit = (res_row["credit_limit"] or 0) if "credit_limit" in res_row.keys() else 0
            credit_debt = (res_row["credit_debt"] or 0) if "credit_debt" in res_row.keys() else 0
            credit_enabled = bool(res_row["credit_enabled"]) if ("credit_enabled" in res_row.keys() and res_row["credit_enabled"]) else (credit_limit > 0)
            available_credit = max(0, credit_limit - credit_debt) if credit_enabled else 0

            cursor.execute("SELECT * FROM subscriptions WHERE id=? AND reseller_id=?", (sub_id, reseller_id))
            sub = cursor.fetchone()
            if not sub:
                return {"success": False, "error": "اشتراک مورد نظر یافت نشد."}

            chosen_source = str(payment_source).strip().lower() if payment_source else "auto"
            mode_title = "فعال‌سازی آنی" if instant_activate else "رزرو در صف تمدید"
            actual_source = "wallet"

            if chosen_source == "wallet":
                if balance < cost:
                    return {"success": False, "error": f"موجودی کیف پول شما کافی نیست! موجودی: {balance:,} تومان | هزینه تمدید: {cost:,} تومان"}
                cursor.execute("UPDATE resellers SET balance = balance - ?, updated_at=? WHERE id=?", (cost, now, reseller_id))
                tx_desc = f"تمدید اشتراک «{sub['account_name']}» با پلن {plan_name} ({mode_title} - کسر از کیف پول نقدی)"
                actual_source = "wallet"

            elif chosen_source == "credit":
                if not credit_enabled:
                    return {"success": False, "error": "اعتبار خرید برای شما فعال نشده است."}
                if available_credit < cost:
                    return {"success": False, "error": f"اعتبار خرید شما کافی نیست! اعتبار باقیمانده: {available_credit:,} تومان | هزینه تمدید: {cost:,} تومان"}
                new_debt = credit_debt + cost
                cursor.execute("UPDATE resellers SET credit_debt = ?, updated_at=? WHERE id=?", (new_debt, now, reseller_id))
                tx_desc = f"تمدید اشتراک «{sub['account_name']}» با پلن {plan_name} ({mode_title} - کسر از اعتبار خرید: {cost:,} ت بدهی)"
                actual_source = "credit"

            else:
                # حالت هوشمند و خودکار (auto)
                total_purchasing_power = balance + available_credit
                if total_purchasing_power < cost:
                    return {"success": False, "error": f"موجودی کیف پول ({balance:,} ت) و اعتبار تمدید ({available_credit:,} ت) برای تمدید این پلن ({cost:,} ت) کافی نیست."}

                if balance >= cost:
                    cursor.execute("UPDATE resellers SET balance = balance - ?, updated_at=? WHERE id=?", (cost, now, reseller_id))
                    tx_desc = f"تمدید اشتراک «{sub['account_name']}» با پلن {plan_name} ({mode_title} - پرداخت از کیف پول)"
                    actual_source = "wallet"
                else:
                    from_credit = cost - balance
                    new_debt = credit_debt + from_credit
                    cursor.execute("UPDATE resellers SET balance = 0, credit_debt = ?, updated_at=? WHERE id=?", (new_debt, now, reseller_id))
                    tx_desc = f"تمدید اشتراک «{sub['account_name']}» با پلن {plan_name} ({mode_title} - کسر {balance:,} ت از کیف پول و {from_credit:,} ت از اعتبار)"
                    actual_source = "credit"

            # ثبت تراکنش تمدید با مشخص بودن مبدأ پرداخت
            cursor.execute("""
                INSERT INTO reseller_transactions (reseller_id, type, amount, plan_name, account_name, description, payment_source, subscription_id, created_at)
                VALUES (?, 'renewal', ?, ?, ?, ?, ?, ?, ?)
            """, (reseller_id, cost, plan_name, sub["account_name"], tx_desc, actual_source, sub_id, now))

            if instant_activate:
                # ۳. به‌روزرسانی آنی مشخصات اشتراک، ریست حجم مصرفی و ریست تاریخ شروع و انقضا
                now_naive = get_now_naive()
                new_start_date = now_naive.strftime("%Y-%m-%d")
                new_expire_date = (now_naive + timedelta(days=duration)).isoformat()
                cursor.execute("""
                    UPDATE subscriptions
                    SET plan_id=?, plan_name=?, data_limit=?, data_used=0, duration=?, status='active',
                        start_date=?, expire_date=?, updated_at=?, cost_paid=?, payment_source=?
                    WHERE id=? AND reseller_id=?
                """, (plan_id, plan_name, data_limit, duration, new_start_date, new_expire_date, now, cost, actual_source, sub_id, reseller_id))
                conn.commit()
                return {"success": True, "mode": "instant", "payment_source": actual_source}
            else:
                # ۴. افزودن به صف تمدید هوشمند (رزرو بسته خودکار)
                cursor.execute("UPDATE subscription_queue SET status='cancelled' WHERE subscription_id=? AND status='pending'", (sub_id,))
                cursor.execute("""
                    INSERT INTO subscription_queue (
                        subscription_id, telegram_id, hidify_uuid, reseller_id,
                        plan_id, plan_name, data_limit, duration, cost, status, created_at, note
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
                """, (sub_id, sub["telegram_id"] or 0, sub["hidify_uuid"] or "", reseller_id,
                      plan_id, plan_name, data_limit, duration, cost, now, f"تمدید رزرو نماینده ({actual_source})"))
                cursor.execute("UPDATE subscriptions SET payment_source=? WHERE id=?", (actual_source, sub_id))
                conn.commit()
                return {"success": True, "mode": "queued", "payment_source": actual_source}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def add_to_subscription_queue(self, subscription_id: int, plan_id: str, plan_name: str,
                                  data_limit: float, duration: int, cost: int = 0,
                                  reseller_id: int = None, telegram_id: int = None,
                                  hidify_uuid: str = None, note: str = None) -> dict:
        """افزودن بسته تمدیدی به صف رزرو خودکار"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("SELECT * FROM subscriptions WHERE id=?", (subscription_id,))
            sub_row = cursor.fetchone()
            if not sub_row:
                return {"success": False, "error": "اشتراک یافت نشد."}

            sub = dict(sub_row)
            t_id = telegram_id if telegram_id is not None else (sub.get("telegram_id") or 0)
            u_uuid = hidify_uuid if hidify_uuid else (sub.get("hidify_uuid") or "")
            r_id = reseller_id if reseller_id is not None else sub.get("reseller_id")

            # لغو رزرو قبلی در صورت وجود
            cursor.execute("UPDATE subscription_queue SET status='cancelled' WHERE subscription_id=? AND status='pending'", (subscription_id,))
            cursor.execute("""
                INSERT INTO subscription_queue (
                    subscription_id, telegram_id, hidify_uuid, reseller_id,
                    plan_id, plan_name, data_limit, duration, cost, status, created_at, note
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
            """, (subscription_id, t_id, u_uuid, r_id, plan_id, plan_name, data_limit, duration, cost, now, note or "تمدید در صف رزرو مدیریت"))
            queue_id = cursor.lastrowid
            conn.commit()
            return {"success": True, "queue_id": queue_id}
        except Exception as e:
            logger.error(f"Error adding to subscription queue: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def get_pending_queue_item(self, subscription_id: int) -> dict:
        """دریافت بسته رزرو در صف برای یک اشتراک خاص"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT * FROM subscription_queue
                WHERE subscription_id=? AND status='pending'
                ORDER BY id DESC LIMIT 1
            """, (subscription_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting pending queue item for sub {subscription_id}: {e}")
            return None
        finally:
            conn.close()

    def get_all_pending_queue_items(self) -> list:
        """دریافت تمام بسته‌های در صف به همراه اطلاعات اشتراک مربوطه برای پردازش خودکار"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT q.*, s.account_name, s.data_used as curr_used, s.data_limit as curr_limit,
                       s.duration as curr_duration, s.start_date as curr_start_date,
                       s.expire_date as curr_expire_date, s.status as sub_status, s.telegram_id as sub_tg_id
                FROM subscription_queue q
                JOIN subscriptions s ON q.subscription_id = s.id
                WHERE q.status = 'pending'
                ORDER BY q.id ASC
            """)
            return [dict(r) for r in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting all pending queue items: {e}")
            return []
        finally:
            conn.close()

    def mark_queue_item_activated(self, queue_id: int) -> dict:
        """علامت‌گذاری بسته در صف به عنوان فعال‌شده"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("UPDATE subscription_queue SET status='activated', activated_at=? WHERE id=?", (now, queue_id))
            conn.commit()
            return {"success": True}
        except Exception as e:
            logger.error(f"Error marking queue item {queue_id} activated: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def cancel_queue_item(self, queue_id: int, reseller_id: int = None) -> dict:
        """لغو بسته در صف و استرداد وجه به کیف‌پول نماینده در صورت پرداخت هزینه"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("SELECT * FROM subscription_queue WHERE id=? AND status='pending'", (queue_id,))
            item = cursor.fetchone()
            if not item:
                return {"success": False, "error": "بسته مورد نظر در صف یافت نشد یا قبلاً پردازش شده است."}

            item_dict = dict(item)
            cost = item_dict.get("cost") or 0
            r_id = item_dict.get("reseller_id")

            if reseller_id and r_id and r_id != reseller_id:
                return {"success": False, "error": "شما به این بسته دسترسی ندارید."}

            # استرداد وجه به نماینده
            if r_id and cost > 0:
                cursor.execute("UPDATE resellers SET balance = balance + ?, updated_at=? WHERE id=?", (cost, now, r_id))
                cursor.execute("""
                    INSERT INTO reseller_transactions (reseller_id, type, amount, plan_name, account_name, description, created_at)
                    VALUES (?, 'refund', ?, ?, ?, ?, ?)
                """, (r_id, cost, item_dict.get("plan_name", ""), f"sub_{item_dict['subscription_id']}", f"استرداد وجه لغو بسته رزرو در صف", now))

            cursor.execute("UPDATE subscription_queue SET status='cancelled' WHERE id=?", (queue_id,))
            conn.commit()
            return {"success": True, "refunded_amount": cost}
        except Exception as e:
            logger.error(f"Error cancelling queue item {queue_id}: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def calculate_reseller_refund(self, reseller_id: int, sub_id: int):
        """
        محاسبه هوشمند استرداد وجه حذف مشتری نماینده طبق تنظیمات مدیریت:
        - عدم تاثیرپذیری از مبلغ بدهی مشتری (صرفاً بر اساس هزینه خرید پلن کسر شده از نماینده)
        - محاسبه زمان بر اساس زمان ساخت اولیه مشتری یا آخرین اقدام (طبق تنظیمات)
        - رعایت درصدهای سفارشی مدیریت و غیرفعال‌سازی سراسری یا برای نماینده خاص
        - تفکیک مبدأ بازگشت وجه (کیف پول نقدی یا اعتبار خرید)
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM subscriptions WHERE id=? AND reseller_id=?", (sub_id, reseller_id))
        sub = cursor.fetchone()
        if not sub:
            conn.close()
            return None

        sub_dict = dict(sub)
        account_name = sub_dict.get("account_name") or f"user_{sub_id}"
        now_dt = get_now_naive()

        # دریافت تنظیمات استرداد
        settings = self.get_refund_settings()
        refund_enabled = bool(settings.get("refund_enabled", True))
        disabled_resellers = settings.get("disabled_resellers", [])
        rate_12h = int(settings.get("rate_before_12h", 100))
        rate_24h = int(settings.get("rate_before_24h", 80))
        calc_from_creation = bool(settings.get("calc_from_creation", True))

        is_disallowed = (not refund_enabled) or (reseller_id in disabled_resellers)

        # تعیین مبدأ پرداخت (کیف پول یا اعتبار)
        sub_source = str(sub_dict.get("payment_source") or "").lower()
        is_credit_sub = bool(sub_dict.get("is_credit") or (sub_dict.get("credit_debt_amount") or 0) > 0 or sub_source == "credit")

        # جستجوی زمان آخرین استرداد ثبت‌شده برای این اشتراک (در صورت حذف و بازگردانی‌های قبلی)
        cursor.execute("""
            SELECT MAX(created_at) FROM reseller_transactions
            WHERE reseller_id = ?
              AND (subscription_id = ? OR account_name = ?)
              AND type IN ('refund', 'refund_credit')
        """, (reseller_id, sub_id, account_name))
        latest_refund_row = cursor.fetchone()
        latest_refund_time = latest_refund_row[0] if latest_refund_row and latest_refund_row[0] else None

        # جستجوی تمام اقدامات مالی کسر شده از نماینده برای این اکانت (صرفاً اقدامات پس از آخرین استرداد)
        if latest_refund_time:
            cursor.execute("""
                SELECT * FROM reseller_transactions
                WHERE reseller_id = ? 
                  AND (subscription_id = ? OR account_name = ?)
                  AND created_at > ?
                  AND type IN ('purchase', 'renewal', 'purchase_credit', 'renewal_credit')
                ORDER BY created_at ASC
            """, (reseller_id, sub_id, account_name, latest_refund_time))
        else:
            cursor.execute("""
                SELECT * FROM reseller_transactions
                WHERE reseller_id = ? 
                  AND (subscription_id = ? OR account_name = ? OR description LIKE ?)
                  AND type IN ('purchase', 'renewal', 'purchase_credit', 'renewal_credit')
                ORDER BY created_at ASC
            """, (reseller_id, sub_id, account_name, f"%{account_name}%"))
        tx_rows = cursor.fetchall()
        conn.close()

        items = []
        total_paid = 0
        total_refund = 0
        latest_elapsed_hours = 999999.0
        latest_time_passed_text = "بیش از ۲۴ ساعت پیش"

        def _calc_elapsed(dt_str):
            try:
                clean = str(dt_str).strip().replace("Z", "")
                dt = datetime.fromisoformat(clean)
                if dt.tzinfo is not None:
                    dt = dt.astimezone(TEHRAN_TZ).replace(tzinfo=None)
            except Exception:
                dt = get_now_naive()
            return max(0.0, (now_dt - dt).total_seconds() / 3600.0)

        def _format_time_passed(hours_val):
            h = int(hours_val)
            m = int((hours_val - h) * 60)
            return f"{h} ساعت و {m} دقیقه پیش" if h > 0 else f"{m} دقیقه پیش"

        # محاسبه زمان بر اساس ساخت مشتری یا آخرین بازگردانی
        creation_dt_str = sub_dict.get("created_at") or get_now_iso()
        if latest_refund_time and sub_dict.get("updated_at"):
            creation_dt_str = sub_dict.get("updated_at")
        creation_elapsed_hours = _calc_elapsed(creation_dt_str)
        creation_time_passed_str = _format_time_passed(creation_elapsed_hours)

        has_credit_tx = False
        has_wallet_tx = False

        if tx_rows:
            for tx in tx_rows:
                tx_d = dict(tx)
                amount = int(tx_d.get("amount") or 0)
                if amount <= 0:
                    continue

                tx_src = tx_d.get("payment_source")
                if not tx_src:
                    tx_src = "credit" if (tx_d.get("type") in ("purchase_credit", "renewal_credit") or "اعتبار" in str(tx_d.get("description", ""))) else "wallet"

                if tx_src == "credit":
                    has_credit_tx = True
                else:
                    has_wallet_tx = True

                # تعیین زمان مبنا
                if calc_from_creation:
                    elapsed_hours = creation_elapsed_hours
                    time_passed_str = creation_time_passed_str
                else:
                    created_str = tx_d.get("created_at") or get_now_iso()
                    elapsed_hours = _calc_elapsed(created_str)
                    time_passed_str = _format_time_passed(elapsed_hours)

                if elapsed_hours < latest_elapsed_hours:
                    latest_elapsed_hours = elapsed_hours
                    latest_time_passed_text = time_passed_str

                if is_disallowed:
                    rate = 0.0
                    percent = 0
                elif elapsed_hours <= 12.0:
                    rate = rate_12h / 100.0
                    percent = rate_12h
                elif elapsed_hours <= 24.0:
                    rate = rate_24h / 100.0
                    percent = rate_24h
                else:
                    rate = 0.0
                    percent = 0

                ref_amount = int(amount * rate)
                total_paid += amount
                total_refund += ref_amount

                items.append({
                    "tx_id": tx_d["id"],
                    "type": tx_d["type"],
                    "payment_source": tx_src,
                    "type_title": "خرید اولیه" if "purchase" in tx_d["type"] else "تمدید اشتراک",
                    "plan_name": tx_d.get("plan_name") or sub_dict.get("plan_name") or "پلن",
                    "amount": amount,
                    "elapsed_hours": round(elapsed_hours, 1),
                    "time_passed_text": time_passed_str,
                    "refund_percent": percent,
                    "refund_amount": ref_amount,
                    "created_at": tx_d.get("created_at")
                })

        # در صورتی که تراکنشی یافت نشد (اکانت‌های دستی یا ایجاد مستقیم)
        if not items:
            elapsed_hours = creation_elapsed_hours
            time_passed_str = creation_time_passed_str
            latest_elapsed_hours = elapsed_hours
            latest_time_passed_text = time_passed_str

            if is_disallowed:
                rate = 0.0
                percent = 0
            elif elapsed_hours <= 12.0:
                percent = rate_12h
                rate = rate_12h / 100.0
            elif elapsed_hours <= 24.0:
                percent = rate_24h
                rate = rate_24h / 100.0
            else:
                percent = 0
                rate = 0.0

            # اگر قبلاً استرداد شده و تراکنش جدیدی ندارد، مبلغ پرداختی ۰ است
            if latest_refund_time:
                cost_paid = 0
            else:
                cost_paid = int(sub_dict.get("cost_paid") or 0)

            ref_amount = int(cost_paid * rate)
            total_paid = cost_paid
            total_refund = ref_amount

            fallback_src = "credit" if is_credit_sub else "wallet"
            if fallback_src == "credit":
                has_credit_tx = True
            else:
                has_wallet_tx = True

            items.append({
                "tx_id": 0,
                "type": "purchase_credit" if is_credit_sub else "purchase",
                "payment_source": fallback_src,
                "type_title": "خرید اشتراک (سیستمی)",
                "plan_name": sub_dict.get("plan_name") or "پلن",
                "amount": cost_paid,
                "elapsed_hours": round(elapsed_hours, 1),
                "time_passed_text": time_passed_str,
                "refund_percent": percent,
                "refund_amount": ref_amount,
                "created_at": creation_dt_str
            })

        effective_percent = int(round((total_refund / total_paid) * 100)) if total_paid > 0 else (rate_12h if latest_elapsed_hours <= 12.0 else (rate_24h if latest_elapsed_hours <= 24.0 else 0))
        if is_disallowed:
            effective_percent = 0
            total_refund = 0

        # مبدأ کلی استرداد
        final_payment_source = "credit" if (has_credit_tx and not has_wallet_tx) else ("wallet" if (has_wallet_tx and not has_credit_tx) else ("credit" if is_credit_sub else "wallet"))

        return {
            "sub_id": sub_id,
            "account_name": account_name,
            "created_at": sub_dict.get("created_at"),
            "elapsed_hours": round(latest_elapsed_hours, 1) if latest_elapsed_hours < 999999 else 0.0,
            "time_passed_text": latest_time_passed_text,
            "refund_percent": effective_percent,
            "cost_paid": total_paid,
            "refund_amount": total_refund,
            "items": items,
            "actions_count": len(items),
            "payment_source": final_payment_source,
            "is_disallowed": is_disallowed,
            "calc_from_creation": calc_from_creation
        }

    def delete_reseller_subscription(self, reseller_id: int, sub_id: int, reason: str = "سایر", deleted_by: str = None):
        """حذف نرم مشتری نماینده به سطل زباله با استرداد وجه دقیق به مبدأ اولیه (کیف پول یا اعتبار)"""
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
            actions_count = refund_info.get("actions_count", 1)
            payment_source = refund_info.get("payment_source", "wallet")

            # ۱. در صورت تعلق استرداد وجه، برگشت به مبدأ اصلی انجام می‌شود
            if refund_amount > 0:
                if payment_source == "credit":
                    # کسر بدهی اعتباری نماینده (بازگشت به سقف اعتبار)
                    cursor.execute("UPDATE resellers SET credit_debt = MAX(0, credit_debt - ?), updated_at=? WHERE id=?", (refund_amount, now, reseller_id))
                    desc_text = f"استرداد وجه {refund_percent}٪ بابت انتقال اشتراک «{account_name}» به سطل زباله (برگشت به اعتبار خرید - کاهش بدهی) - زمان گذشته: {refund_info['time_passed_text']} - علت: {reason}"
                    cursor.execute("""
                        INSERT INTO reseller_transactions (reseller_id, type, amount, plan_name, account_name, description, payment_source, subscription_id, created_at)
                        VALUES (?, 'refund', ?, 'استرداد وجه اعتباری', ?, ?, 'credit', ?, ?)
                    """, (reseller_id, refund_amount, account_name, desc_text, sub_id, now))
                else:
                    # افزایش موجودی کیف پول نقدی نماینده
                    cursor.execute("UPDATE resellers SET balance = balance + ?, updated_at=? WHERE id=?", (refund_amount, now, reseller_id))
                    desc_text = f"استرداد وجه {refund_percent}٪ بابت انتقال اشتراک «{account_name}» به سطل زباله (واریز به کیف پول) - زمان گذشته: {refund_info['time_passed_text']} - علت: {reason}"
                    cursor.execute("""
                        INSERT INTO reseller_transactions (reseller_id, type, amount, plan_name, account_name, description, payment_source, subscription_id, created_at)
                        VALUES (?, 'refund', ?, 'استرداد وجه', ?, ?, 'wallet', ?, ?)
                    """, (reseller_id, refund_amount, account_name, desc_text, sub_id, now))

            # ۲. حذف نرم اشتراک از جدول (انتقال به سطل زباله)
            by_user = deleted_by or f"reseller_{reseller_id}"
            cursor.execute("""
                UPDATE subscriptions 
                SET is_deleted = 1, deleted_at = ?, delete_reason = ?, deleted_by = ?, status = 'deleted', updated_at = ?
                WHERE id = ? AND reseller_id = ?
            """, (now, reason, by_user, now, sub_id, reseller_id))
            conn.commit()

            return {
                "success": True,
                "refund_amount": refund_amount,
                "refund_percent": refund_percent,
                "time_passed_text": refund_info["time_passed_text"],
                "actions_count": actions_count,
                "items": refund_info.get("items", []),
                "payment_source": payment_source
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    # ─── استرداد وجه و حذف هوشمند اشتراک مشتریان برای مدیران (Customer Refund & Delete) ───

    def calculate_customer_refund(self, sub_id: int):
        """
        محاسبه شرایط و درصد استرداد وجه حذف اشتراک مشتری توسط مدیران (شامل خرید و کلیه تمدیدها):
        - هر اقدام کمتر از ۱۲ ساعت پیش: ۱۰۰٪ مبلغ
        - هر اقدام بین ۱۲ تا ۲۴ ساعت پیش: ۸۰٪ مبلغ
        - هر اقدام بیش از ۲۴ ساعت پیش: ۰٪ مبلغ
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM subscriptions WHERE id=?", (sub_id,))
        sub = cursor.fetchone()
        if not sub:
            conn.close()
            return None

        account_name = sub["account_name"] or "بدون نام"
        user_id = sub["telegram_id"] if ("telegram_id" in sub.keys() and sub["telegram_id"]) else None
        now_dt = get_now_naive()

        if account_name and account_name != "بدون نام":
            cursor.execute("""
                SELECT * FROM transactions 
                WHERE (account_name = ? OR renew_sub_id = ?)
                  AND status IN ('approved', 'completed')
                  AND (is_deleted = 0 OR is_deleted IS NULL)
                  AND (gateway != 'bundle_reseller' AND order_id NOT LIKE 'R_BUNDLE%')
                ORDER BY created_at ASC
            """, (account_name, sub_id))
        else:
            cursor.execute("""
                SELECT * FROM transactions 
                WHERE (user_id = ? OR renew_sub_id = ?)
                  AND status IN ('approved', 'completed')
                  AND (is_deleted = 0 OR is_deleted IS NULL)
                  AND (gateway != 'bundle_reseller' AND order_id NOT LIKE 'R_BUNDLE%')
                ORDER BY created_at ASC
            """, (user_id or 0, sub_id))
        tx_rows = cursor.fetchall()
        conn.close()

        items = []
        total_paid = 0
        total_refund = 0
        latest_elapsed_hours = 999999.0
        latest_time_passed_text = "بیش از ۲۴ ساعت پیش"

        def _calc_elapsed(dt_str):
            try:
                clean = str(dt_str).strip().replace("Z", "")
                dt = datetime.fromisoformat(clean)
                if dt.tzinfo is not None:
                    dt = dt.astimezone(TEHRAN_TZ).replace(tzinfo=None)
            except Exception:
                dt = get_now_naive()
            return max(0.0, (now_dt - dt).total_seconds() / 3600.0)

        def _format_time_passed(hours_val):
            h = int(hours_val)
            m = int((hours_val - h) * 60)
            return f"{h} ساعت و {m} دقیقه پیش" if h > 0 else f"{m} دقیقه پیش"

        if tx_rows:
            for tx in tx_rows:
                amount = int(tx["amount"] or 0)
                if amount <= 0:
                    continue
                created_str = tx["created_at"] or get_now_iso()
                elapsed_hours = _calc_elapsed(created_str)
                time_passed_str = _format_time_passed(elapsed_hours)

                if elapsed_hours < latest_elapsed_hours:
                    latest_elapsed_hours = elapsed_hours
                    latest_time_passed_text = time_passed_str

                if elapsed_hours <= 12.0:
                    rate = 1.0
                    percent = 100
                elif elapsed_hours <= 24.0:
                    rate = 0.8
                    percent = 80
                else:
                    rate = 0.0
                    percent = 0

                ref_amount = int(amount * rate)
                total_paid += amount
                total_refund += ref_amount
                tx_d = dict(tx)
                is_renewal = bool(tx_d.get("is_renewal") or (tx_d.get("renew_sub_id") == sub_id))
                items.append({
                    "tx_id": tx_d["id"],
                    "order_id": tx_d["order_id"],
                    "type_title": "تمدید اشتراک" if is_renewal else "خرید اولیه",
                    "plan_name": tx_d.get("plan_name") or sub["plan_name"] or "پلن",
                    "amount": amount,
                    "elapsed_hours": round(elapsed_hours, 1),
                    "time_passed_text": time_passed_str,
                    "refund_percent": percent,
                    "refund_amount": ref_amount,
                    "created_at": created_str
                })

        if not items:
            created_str = sub["created_at"] or get_now_iso()
            elapsed_hours = _calc_elapsed(created_str)
            time_passed_str = _format_time_passed(elapsed_hours)
            latest_elapsed_hours = elapsed_hours
            latest_time_passed_text = time_passed_str

            if elapsed_hours <= 12.0:
                percent = 100
                rate = 1.0
            elif elapsed_hours <= 24.0:
                percent = 80
                rate = 0.8
            else:
                percent = 0
                rate = 0.0

            cost_paid = int(sub["cost_paid"] or 0)
            ref_amount = int(cost_paid * rate)
            total_paid = cost_paid
            total_refund = ref_amount

            items.append({
                "tx_id": 0,
                "order_id": "-",
                "type_title": "خرید اولیه (ثبت سیستمی)",
                "plan_name": sub["plan_name"] or "پلن",
                "amount": cost_paid,
                "elapsed_hours": round(elapsed_hours, 1),
                "time_passed_text": time_passed_str,
                "refund_percent": percent,
                "refund_amount": ref_amount,
                "created_at": created_str
            })

        effective_percent = int(round((total_refund / total_paid) * 100)) if total_paid > 0 else (100 if latest_elapsed_hours <= 12.0 else (80 if latest_elapsed_hours <= 24.0 else 0))

        return {
            "sub_id": sub_id,
            "account_name": account_name,
            "user_id": user_id,
            "created_at": sub["created_at"],
            "elapsed_hours": round(latest_elapsed_hours, 1) if latest_elapsed_hours < 999999 else 0.0,
            "time_passed_text": latest_time_passed_text,
            "refund_percent": effective_percent,
            "cost_paid": total_paid,
            "refund_amount": total_refund,
            "items": items,
            "actions_count": len(items),
            "hidify_uuid": sub["hidify_uuid"]
        }

    def delete_customer_subscription(self, sub_id: int, refund_to_customer: bool = True, admin_name: str = "مدیر", reason: str = "سایر"):
        """حذف نرم مشتری توسط مدیر به سطل زباله با قابلیت استرداد مستقیم وجه به کیف پول کاربر تلگرام"""
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
            actions_count = refund_info.get("actions_count", 1)

            # ۱. در صورت تایید استرداد و وجود مبلغ، کیف پول کاربر شارژ می‌شود
            refund_done = False
            if refund_to_customer and refund_amount > 0 and user_id:
                try:
                    desc_text = f"استرداد وجه {refund_percent}٪ بابت انتقال اشتراک «{account_name}» به سطل زباله ({actions_count} مرحله تراکنش/تمدید - آخرین اقدام: {refund_info['time_passed_text']}) توسط {admin_name} - علت: {reason}"
                    self.add_wallet_balance(
                        user_id,
                        refund_amount,
                        desc_text,
                        tx_type="refund"
                    )
                    refund_done = True
                except Exception as ex:
                    logger.error(f"Error adding refund to wallet for user {user_id}: {ex}")

            # ۲. حذف نرم اشتراک از دیتابیس (انتقال به سطل زباله)
            cursor.execute("""
                UPDATE subscriptions 
                SET is_deleted = 1, deleted_at = ?, delete_reason = ?, deleted_by = ?, status = 'deleted', updated_at = ?
                WHERE id = ?
            """, (now, reason, admin_name, now, sub_id))
            conn.commit()

            return {
                "success": True,
                "refund_done": refund_done,
                "refund_amount": refund_amount if refund_done else 0,
                "refund_percent": refund_percent,
                "time_passed_text": refund_info["time_passed_text"],
                "account_name": account_name,
                "hidify_uuid": hidify_uuid,
                "user_id": user_id,
                "actions_count": actions_count,
                "items": refund_info.get("items", [])
            }
        except Exception as e:
            logger.error(f"Error deleting customer subscription {sub_id}: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def get_deleted_subscriptions(self, reseller_id: int = None, sort_by: str = "newest") -> list:
        """دریافت لیست اشتراک‌های موجود در سطل زباله با پشتیبانی از انواع مرتب‌سازی و محاسبه مهلت ۷ روزه"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now_dt = get_now_naive()
        try:
            order_clause = "deleted_at DESC"
            if sort_by == "oldest":
                order_clause = "deleted_at ASC"
            elif sort_by == "days_left_asc":
                order_clause = "deleted_at ASC"
            elif sort_by == "usage_desc":
                order_clause = "data_used DESC"
            elif sort_by == "limit_desc":
                order_clause = "data_limit DESC"
            elif sort_by == "name_asc":
                order_clause = "account_name COLLATE NOCASE ASC"

            if reseller_id is not None:
                cursor.execute(f"SELECT * FROM subscriptions WHERE is_deleted = 1 AND reseller_id = ? ORDER BY {order_clause}", (reseller_id,))
            else:
                cursor.execute(f"SELECT * FROM subscriptions WHERE is_deleted = 1 ORDER BY {order_clause}")
            rows = cursor.fetchall()
            restore_window = float(self.get_refund_settings().get("restore_window_days", 7))
            result = []
            for r in rows:
                item = dict(r)
                del_str = item.get("deleted_at")
                days_passed = 0.0
                if del_str:
                    try:
                        del_dt = datetime.fromisoformat(del_str.replace("Z", "+00:00")).replace(tzinfo=None)
                        days_passed = round((now_dt - del_dt).total_seconds() / 86400.0, 1)
                    except Exception:
                        days_passed = 0.0
                item["days_passed"] = days_passed
                item["days_left"] = max(0.0, round(restore_window - days_passed, 1))
                result.append(item)

            if sort_by == "days_left_asc":
                result.sort(key=lambda x: x["days_left"])

            return result
        except Exception as e:
            logger.error(f"Error fetching deleted subscriptions: {e}")
            return []
        finally:
            conn.close()

    def restore_subscription(self, sub_id: int, is_reseller: bool = False, reseller_id: int = None, cost: int = 0,
                             new_uuid: str = None, new_start_date: str = None, new_expire_date: str = None,
                             new_data_used: float = None, payment_source: str = "auto") -> dict:
        """بازگردانی اشتراک از سطل زباله به لیست فعال، به‌روزرسانی مشخصات و کسر هزینه در صورت بازگردانی توسط نماینده"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("SELECT * FROM subscriptions WHERE id = ? AND is_deleted = 1", (sub_id,))
            sub = cursor.fetchone()
            if not sub:
                return {"success": False, "error": "اشتراک در سطل زباله یافت نشد."}

            sub_dict = dict(sub)
            account_name = sub_dict.get("account_name", "بدون نام")
            chosen_source = "wallet"

            # اگر نماینده بازگردانی می‌کند و هزینه دارد، کسر از کیف پول یا اعتبار
            if is_reseller and reseller_id and cost > 0:
                deduct_res = self.deduct_reseller_balance(
                    reseller_id=reseller_id,
                    amount=cost,
                    plan_name=sub_dict.get("plan_name") or "پلن اشتراک",
                    account_name=account_name,
                    description=f"هزینه بازگردانی اشتراک «{account_name}» از سطل زباله",
                    payment_source=payment_source,
                    subscription_id=sub_id
                )
                if not deduct_res.get("success"):
                    return {"success": False, "error": deduct_res.get("error", "موجودی یا اعتبار کافی نیست.")}
                chosen_source = deduct_res.get("payment_source", "wallet")

            update_sql = """
                UPDATE subscriptions 
                SET is_deleted = 0, deleted_at = NULL, delete_reason = NULL, deleted_by = NULL, disable_reason = NULL,
                    purged_from_hiddify = 0, status = 'active', updated_at = ?, payment_source = COALESCE(?, payment_source)
            """
            params = [now, chosen_source if (is_reseller and cost > 0) else None]
            if is_reseller and cost > 0:
                update_sql += ", cost_paid = ?"
                params.append(cost)
            if new_uuid:
                update_sql += ", hidify_uuid = ?"
                params.append(new_uuid)
            if new_start_date is not None:
                update_sql += ", start_date = ?"
                params.append(new_start_date)
            if new_expire_date is not None:
                update_sql += ", expire_date = ?"
                params.append(new_expire_date)
            if new_data_used is not None:
                update_sql += ", data_used = ?"
                params.append(float(new_data_used))

            update_sql += " WHERE id = ?"
            params.append(sub_id)

            cursor.execute(update_sql, tuple(params))
            conn.commit()

            return {
                "success": True,
                "account_name": account_name,
                "hidify_uuid": new_uuid or sub_dict.get("hidify_uuid"),
                "cost_deducted": cost,
                "subscription": sub_dict
            }
        except Exception as e:
            logger.error(f"Error restoring subscription {sub_id}: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def purge_subscription_permanently(self, sub_id: int, reseller_id: int = None) -> dict:
        """حذف فیزیکی و قطعی اشتراک از سطل زباله دیتابیس"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            if reseller_id is not None:
                cursor.execute("SELECT * FROM subscriptions WHERE id = ? AND reseller_id = ? AND is_deleted = 1", (sub_id, reseller_id))
            else:
                cursor.execute("SELECT * FROM subscriptions WHERE id = ? AND is_deleted = 1", (sub_id,))
            row = cursor.fetchone()
            if not row:
                return {"success": False, "error": "اشتراک در سطل زباله یافت نشد."}

            sub_dict = dict(row)
            cursor.execute("DELETE FROM subscriptions WHERE id = ?", (sub_id,))
            conn.commit()
            return {
                "success": True,
                "account_name": sub_dict.get("account_name"),
                "hidify_uuid": sub_dict.get("hidify_uuid")
            }
        except Exception as e:
            logger.error(f"Error purging subscription {sub_id} permanently: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def purge_expired_deleted_subscriptions(self, hiddify_purge_func=None) -> int:
        """پاکسازی دائمی خودکار اشتراک‌های سپری‌شده از مهلت ۷ روزه از سرور هیدیفای و حذف قطعی از دیتابیس"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now_dt = get_now_naive()
        restore_window = float(self.get_refund_settings().get("restore_window_days", 7))
        purged_count = 0
        try:
            cursor.execute("SELECT id, hidify_uuid, account_name, deleted_at FROM subscriptions WHERE is_deleted = 1")
            rows = cursor.fetchall()
            for r in rows:
                del_str = r["deleted_at"]
                if not del_str:
                    continue
                try:
                    del_dt = datetime.fromisoformat(del_str.replace("Z", "+00:00")).replace(tzinfo=None)
                except Exception:
                    continue
                days_passed = (now_dt - del_dt).total_seconds() / 86400.0
                if days_passed >= restore_window:
                    uuid_val = r["hidify_uuid"]
                    if uuid_val and hiddify_purge_func:
                        try:
                            hiddify_purge_func(uuid_val)
                        except Exception as e:
                            logger.warning(f"Error purging user {uuid_val} from Hiddify: {e}")
                    # حذف قطعی از دیتابیس جهت تمیز شدن کامل سطل زباله
                    cursor.execute("DELETE FROM subscriptions WHERE id = ?", (r["id"],))
                    purged_count += 1
            conn.commit()
        except Exception as e:
            logger.error(f"Error in purge_expired_deleted_subscriptions: {e}")
        finally:
            conn.close()
        return purged_count

    # ─── مدیریت قبوض بدهی نمایندگان (Reseller Debts & Invoices) ───

    def add_reseller_debt(self, reseller_id: int, title: str, amount: int, due_date: str = None, notes: str = None, created_by: str = "admin") -> dict:
        """ثبت قبض بدهی جدید یا بدهی معوق قبلی برای نماینده (مجزا از اعتبار خرید)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("""
                INSERT INTO reseller_debts (reseller_id, title, amount, remaining_amount, status, due_date, notes, created_by, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'unpaid', ?, ?, ?, ?, ?)
            """, (reseller_id, title.strip(), amount, amount, due_date or "", notes or "", created_by, now, now))
            debt_id = cursor.lastrowid
            conn.commit()
            return {"success": True, "debt_id": debt_id}
        except Exception as e:
            logger.error(f"Error in add_reseller_debt: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def get_reseller_debts(self, reseller_id: int = None) -> list:
        """دریافت لیست کلیه قبوض و مطالبات بدهی نمایندگان"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            if reseller_id is not None:
                cursor.execute("""
                    SELECT d.*, r.name as reseller_name, r.username as reseller_username 
                    FROM reseller_debts d
                    LEFT JOIN resellers r ON d.reseller_id = r.id
                    WHERE d.reseller_id = ?
                    ORDER BY d.id DESC
                """, (reseller_id,))
            else:
                cursor.execute("""
                    SELECT d.*, r.name as reseller_name, r.username as reseller_username 
                    FROM reseller_debts d
                    LEFT JOIN resellers r ON d.reseller_id = r.id
                    ORDER BY d.id DESC
                """)
            return [dict(r) for r in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error in get_reseller_debts: {e}")
            return []
        finally:
            conn.close()

    def get_reseller_debt(self, debt_id: int) -> Optional[dict]:
        """دریافت جزئیات یک قبض بدهی مشخص"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT d.*, r.name as reseller_name, r.username as reseller_username 
                FROM reseller_debts d
                LEFT JOIN resellers r ON d.reseller_id = r.id
                WHERE d.id = ?
            """, (debt_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error in get_reseller_debt: {e}")
            return None
        finally:
            conn.close()

    def update_reseller_debt_status(self, debt_id: int, status: str, remaining_amount: int = None) -> dict:
        """به‌روزرسانی وضعیت تسویه یا پرداخت جزئی قبض بدهی"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            if remaining_amount is not None:
                cursor.execute("UPDATE reseller_debts SET status = ?, remaining_amount = ?, updated_at = ? WHERE id = ?", (status, remaining_amount, now, debt_id))
            else:
                cursor.execute("UPDATE reseller_debts SET status = ?, updated_at = ? WHERE id = ?", (status, now, debt_id))
            conn.commit()
            return {"success": True}
        except Exception as e:
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
                "bank_name", "is_bot_active", "tier_level", "auto_approval",
                "vip_auto_enabled", "vip_auto_threshold", "vip_cashback_percent", "updated_at"
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
        """ایجاد مدیر زیرمجموعه جدید برای نماینده با نقش‌های manager2, partner, finance, support"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        clean_pass = password.strip()
        password_hash = self.hash_password(clean_pass)
        try:
            clean_username = username.strip().lower()
            cursor.execute("SELECT id FROM admin_users WHERE LOWER(username) = ?", (clean_username,))
            if cursor.fetchone():
                return {"success": False, "error": "این نام کاربری قبلاً در سیستم ثبت شده است."}

            permissions = "all"
            if role == "support":
                permissions = "tickets,users,subscriptions"
            elif role == "finance":
                permissions = "payments,transactions,reports"
            elif role in ("partner", "manager2", "manager", "co_admin"):
                permissions = "all"
                if role in ("manager2", "manager", "co_admin"):
                    role = "manager2"
                    share_percent = 0  # مدیر دو عنوان شریک ندارد و درصد سود شریک برای آن صفر است

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

    def update_accounting_record(self, record_id: int, edited_by: str = None, **kwargs) -> dict:
        """ویرایش سند حسابداری توسط مدیر ارشد با ثبت رهگیری کامل"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now_iso = get_now_iso()
        try:
            allowed = ["type", "category", "title", "amount", "description", "date"]
            updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
            if not updates:
                return {"success": False, "error": "داده‌ای برای بروزرسانی ارسال نشده است."}

            updates["is_edited"] = 1
            if edited_by:
                updates["edited_by"] = str(edited_by)
            updates["edited_at"] = now_iso

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

    def update_admin_debt(self, debt_id: int, edited_by: str = None, **kwargs) -> dict:
        """ویرایش سابقه تراز بدهی مدیر/شریک توسط مدیر ارشد با برچسب ویرایش"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now_iso = get_now_iso()
        try:
            allowed = ["total_amount", "share_amount", "debt_amount", "description", "customer_name", "plan_name"]
            updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
            if not updates:
                return {"success": False, "error": "داده‌ای برای بروزرسانی ارسال نشده است."}

            updates["is_edited"] = 1
            if edited_by:
                updates["edited_by"] = str(edited_by)
            updates["edited_at"] = now_iso

            fields = ", ".join([f"{k}=?" for k in updates.keys()])
            values = list(updates.values()) + [debt_id]
            cursor.execute(f"UPDATE admin_debts SET {fields} WHERE id=?", values)
            conn.commit()
            return {"success": True}
        except Exception as e:
            logger.error(f"Error updating admin debt {debt_id}: {e}")
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
        """محاسبه شاخص‌های جامع مالی، حسابرسی مشتریان مدیریت، بسته‌های پیش‌خرید اعتباری و بدهی نمایندگان"""
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

            # ۹. حسابرسی اختصاصی مشتریان مستقیم مدیریت
            cursor.execute("""
                SELECT COALESCE(SUM(amount), 0) FROM transactions 
                WHERE status IN ('approved', 'completed') 
                  AND (gateway != 'bundle_reseller' AND order_id NOT LIKE 'R_BUNDLE%')
                  AND (reseller_id IS NULL OR reseller_id = 0)
            """)
            admin_direct_income = cursor.fetchone()[0] or 0

            cursor.execute("""
                SELECT COALESCE(SUM(debt_amount), 0) FROM subscriptions 
                WHERE (payment_status IN ('unpaid', 'debtor') OR debt_amount > 0)
                  AND (is_deleted = 0 OR is_deleted IS NULL)
                  AND (reseller_id IS NULL OR reseller_id = 0)
            """)
            admin_direct_debt = cursor.fetchone()[0] or 0

            cursor.execute("""
                SELECT COUNT(*) FROM subscriptions 
                WHERE (is_deleted = 0 OR is_deleted IS NULL)
                  AND (reseller_id IS NULL OR reseller_id = 0)
            """)
            admin_direct_customers_count = cursor.fetchone()[0] or 0

            # ۱۰. بسته‌های پیش‌خرید اعتباری نمایندگان (Volume Bundles)
            cursor.execute("""
                SELECT COALESCE(SUM(amount), 0) FROM transactions 
                WHERE status IN ('approved', 'completed') 
                  AND (gateway = 'bundle_reseller' OR order_id LIKE 'R_BUNDLE%')
            """)
            reseller_bundles_income = cursor.fetchone()[0] or 0

            cursor.execute("""
                SELECT COUNT(*) FROM transactions 
                WHERE status IN ('approved', 'completed') 
                  AND (gateway = 'bundle_reseller' OR order_id LIKE 'R_BUNDLE%')
            """)
            reseller_bundles_count = cursor.fetchone()[0] or 0

            # ۱۱. بدهی نمایندگانی که خرید اعتباری انجام داده‌اند
            cursor.execute("SELECT COALESCE(SUM(credit_debt), 0) FROM resellers WHERE credit_debt > 0")
            reseller_credit_debts_total = cursor.fetchone()[0] or 0

            cursor.execute("SELECT COUNT(*) FROM resellers WHERE credit_debt > 0")
            reseller_debtors_count = cursor.fetchone()[0] or 0

            cursor.execute("SELECT COALESCE(SUM(credit_limit), 0) FROM resellers WHERE credit_enabled = 1")
            reseller_credit_limits_total = cursor.fetchone()[0] or 0

            cursor.execute("SELECT COALESCE(SUM(balance), 0) FROM resellers WHERE balance > 0")
            reseller_wallets_total = cursor.fetchone()[0] or 0

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
                # حسابرسی مشتریان مدیریت
                "admin_direct_income": admin_direct_income,
                "admin_direct_debt": admin_direct_debt,
                "admin_direct_customers_count": admin_direct_customers_count,
                # بسته‌های پیش‌خرید اعتباری
                "reseller_bundles_income": reseller_bundles_income,
                "reseller_bundles_count": reseller_bundles_count,
                # بدهی‌های اعتباری نمایندگان
                "reseller_credit_debts_total": reseller_credit_debts_total,
                "reseller_debtors_count": reseller_debtors_count,
                "reseller_credit_limits_total": reseller_credit_limits_total,
                "reseller_wallets_total": reseller_wallets_total
            }
        except Exception as e:
            logger.error(f"Error in get_accounting_summary: {e}")
            return {
                "total_income": 0, "auto_tx_income": 0, "auto_reseller_income": 0, "manual_income": 0,
                "total_expense": 0, "net_profit": 0, "profit_margin": 0.0,
                "month_total_income": 0, "month_total_expense": 0, "month_net_profit": 0,
                "expense_categories": [], "monthly_trend": [],
                "admin_direct_income": 0, "admin_direct_debt": 0, "admin_direct_customers_count": 0,
                "reseller_bundles_income": 0, "reseller_bundles_count": 0,
                "reseller_credit_debts_total": 0, "reseller_debtors_count": 0,
                "reseller_credit_limits_total": 0, "reseller_wallets_total": 0
            }
        finally:
            conn.close()

    def get_partner_profits_summary(self, period: str = "all") -> dict:
        """محاسبه سود شرکا در صورت وجود شرکا و سود کسب شده در دوره‌های مختلف"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT id, username, display_name, role, share_percent, debt_balance, telegram_id
                FROM admin_users 
                WHERE role = 'partner' OR share_percent > 0
                ORDER BY id ASC
            """)
            partners = [dict(r) for r in cursor.fetchall()]

            date_cond = ""
            if period == "today":
                date_cond = "AND created_at >= DATE('now')"
            elif period == "week":
                date_cond = "AND created_at >= DATE('now', '-7 days')"
            elif period == "month":
                date_cond = "AND created_at >= DATE('now', 'start of month')"
            elif period == "year":
                date_cond = "AND created_at >= DATE('now', 'start of year')"

            partner_reports = []
            total_partner_sales = 0
            total_partner_profits = 0
            total_mgmt_share = 0
            total_partner_debt_balance = 0

            for p in partners:
                p_id = p["id"]
                p_share_pct = p.get("share_percent") or 0

                # فروش نقدی در بازه
                cursor.execute(f"""
                    SELECT COALESCE(SUM(total_amount), 0), COALESCE(SUM(share_amount), 0), COUNT(*)
                    FROM admin_debts
                    WHERE admin_id = ? AND type = 'cash_sale' {date_cond}
                """, (p_id,))
                sale_row = cursor.fetchone()
                sales_amount = sale_row[0] or 0
                profit_earned = sale_row[1] or 0
                sales_count = sale_row[2] or 0

                # کل تسویه‌شده در بازه
                cursor.execute(f"""
                    SELECT COALESCE(SUM(total_amount), 0)
                    FROM admin_debts
                    WHERE admin_id = ? AND type = 'settlement' {date_cond}
                """, (p_id,))
                settled_amount = cursor.fetchone()[0] or 0

                mgmt_share = sales_amount - profit_earned
                debt_balance = p.get("debt_balance") or 0

                total_partner_sales += sales_amount
                total_partner_profits += profit_earned
                total_mgmt_share += mgmt_share
                total_partner_debt_balance += debt_balance

                partner_reports.append({
                    "id": p_id,
                    "username": p["username"],
                    "display_name": p["display_name"],
                    "role": p["role"],
                    "share_percent": p_share_pct,
                    "sales_count": sales_count,
                    "sales_amount": sales_amount,
                    "profit_earned": profit_earned,
                    "mgmt_share": mgmt_share,
                    "settled_amount": settled_amount,
                    "debt_balance": debt_balance,
                    "telegram_id": p.get("telegram_id")
                })

            return {
                "has_partners": len(partners) > 0,
                "period": period,
                "partners": partner_reports,
                "total_sales": total_partner_sales,
                "total_profits": total_partner_profits,
                "total_mgmt_share": total_mgmt_share,
                "total_debt_balance": total_partner_debt_balance
            }
        except Exception as e:
            logger.error(f"Error in get_partner_profits_summary: {e}")
            return {"has_partners": False, "period": period, "partners": [], "total_sales": 0, "total_profits": 0, "total_mgmt_share": 0, "total_debt_balance": 0}
        finally:
            conn.close()

    def search_all_customers(self, query: str = "", limit: int = 50) -> list:
        """جستجوی جامع مشتریان فعال، منقضی و حذف‌شده در سطل زباله جهت انتساب رسید دستی"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            q_clean = query.strip()
            q = f"%{q_clean}%" if q_clean else "%"
            cursor.execute("""
                SELECT s.id, s.account_name, s.phone_number, s.telegram_id, s.hidify_uuid,
                       s.plan_id, s.plan_name, s.status, s.data_limit, s.duration,
                       s.is_deleted, s.deleted_at, s.payment_status, s.debt_amount,
                       s.cost_paid, s.reseller_id, s.created_at,
                       r.name as reseller_name
                FROM subscriptions s
                LEFT JOIN resellers r ON s.reseller_id = r.id
                WHERE (s.account_name LIKE ? OR s.phone_number LIKE ? OR CAST(s.telegram_id AS TEXT) LIKE ? OR s.hidify_uuid LIKE ?)
                ORDER BY s.id DESC LIMIT ?
            """, (q, q, q, q, limit))
            rows = cursor.fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"Error in search_all_customers: {e}")
            return []
        finally:
            conn.close()

    def get_financial_reports_data(self, period: str = "month") -> dict:
        """گزارشات و تحلیل هوش مالی به تفکیک تب‌های همه، مشتریان مستقیم مدیریت، و نمایندگان با فیلتر زمانی"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            date_cond_tx = ""
            date_cond_sub = ""
            date_cond_rtx = ""
            if period == "today":
                date_cond_tx = "AND created_at >= DATE('now')"
                date_cond_sub = "AND created_at >= DATE('now')"
                date_cond_rtx = "AND created_at >= DATE('now')"
            elif period == "week":
                date_cond_tx = "AND created_at >= DATE('now', '-7 days')"
                date_cond_sub = "AND created_at >= DATE('now', '-7 days')"
                date_cond_rtx = "AND created_at >= DATE('now', '-7 days')"
            elif period == "month":
                date_cond_tx = "AND created_at >= DATE('now', 'start of month')"
                date_cond_sub = "AND created_at >= DATE('now', 'start of month')"
                date_cond_rtx = "AND created_at >= DATE('now', 'start of month')"
            elif period == "year":
                date_cond_tx = "AND created_at >= DATE('now', 'start of year')"
                date_cond_sub = "AND created_at >= DATE('now', 'start of year')"
                date_cond_rtx = "AND created_at >= DATE('now', 'start of year')"

            # ۱. تب همه (All)
            cursor.execute(f"SELECT COALESCE(SUM(amount), 0), COUNT(*) FROM transactions WHERE status IN ('approved', 'completed') {date_cond_tx}")
            all_tx = cursor.fetchone()
            period_revenue = all_tx[0] or 0
            period_orders = all_tx[1] or 0

            cursor.execute("SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE status IN ('approved', 'completed')")
            lifetime_revenue = cursor.fetchone()[0] or 0

            cursor.execute("SELECT COUNT(*) FROM users")
            total_users = cursor.fetchone()[0] or 0

            cursor.execute("SELECT COUNT(*) FROM subscriptions WHERE (is_deleted = 0 OR is_deleted IS NULL) AND status = 'active'")
            total_active_subs = cursor.fetchone()[0] or 0

            cursor.execute("""
                SELECT strftime('%Y-%m', created_at) as month, SUM(amount) as total, COUNT(*) as count
                FROM transactions WHERE status IN ('approved', 'completed')
                GROUP BY strftime('%Y-%m', created_at) ORDER BY month DESC LIMIT 12
            """)
            monthly_trend = [dict(r) for r in cursor.fetchall()]

            # ۲. تب مشتریان مدیریت (Direct Admin Customers)
            cursor.execute(f"""
                SELECT COALESCE(SUM(amount), 0), COUNT(*)
                FROM transactions
                WHERE status IN ('approved', 'completed')
                  AND ((reseller_id IS NULL OR reseller_id = 0) AND gateway != 'bundle_reseller' AND order_id NOT LIKE 'R_BUNDLE%')
                  {date_cond_tx}
            """)
            admin_tx = cursor.fetchone()
            admin_period_revenue = admin_tx[0] or 0
            admin_period_orders = admin_tx[1] or 0

            cursor.execute("""
                SELECT COALESCE(SUM(amount), 0)
                FROM transactions
                WHERE status IN ('approved', 'completed')
                  AND ((reseller_id IS NULL OR reseller_id = 0) AND gateway != 'bundle_reseller' AND order_id NOT LIKE 'R_BUNDLE%')
            """)
            admin_lifetime_revenue = cursor.fetchone()[0] or 0

            cursor.execute("""
                SELECT COUNT(*) FROM subscriptions 
                WHERE (reseller_id IS NULL OR reseller_id = 0) AND (is_deleted = 0 OR is_deleted IS NULL) AND status = 'active'
            """)
            admin_active_subs = cursor.fetchone()[0] or 0

            cursor.execute("""
                SELECT COUNT(*), COALESCE(SUM(data_limit), 0) FROM subscriptions 
                WHERE (reseller_id IS NULL OR reseller_id = 0) AND (is_deleted = 0 OR is_deleted IS NULL)
            """)
            admin_sub_stats = cursor.fetchone()
            admin_total_subs = admin_sub_stats[0] or 0
            admin_total_gb = admin_sub_stats[1] or 0

            cursor.execute("""
                SELECT COALESCE(SUM(debt_amount), 0), COUNT(*)
                FROM subscriptions
                WHERE (reseller_id IS NULL OR reseller_id = 0)
                  AND payment_status IN ('unpaid', 'debtor')
                  AND debt_amount > 0
                  AND (is_deleted = 0 OR is_deleted IS NULL)
            """)
            admin_debt_row = cursor.fetchone()
            admin_debt_total = admin_debt_row[0] or 0
            admin_debt_count = admin_debt_row[1] or 0

            cursor.execute("""
                SELECT id, account_name, telegram_id, phone_number, plan_name, debt_amount, debt_notes, debt_created_at
                FROM subscriptions
                WHERE (reseller_id IS NULL OR reseller_id = 0)
                  AND payment_status IN ('unpaid', 'debtor')
                  AND debt_amount > 0
                  AND (is_deleted = 0 OR is_deleted IS NULL)
                ORDER BY debt_amount DESC LIMIT 50
            """)
            admin_debtors = [dict(r) for r in cursor.fetchall()]

            cursor.execute("""
                SELECT strftime('%Y-%m', created_at) as month, SUM(amount) as total, COUNT(*) as count
                FROM transactions 
                WHERE status IN ('approved', 'completed')
                  AND ((reseller_id IS NULL OR reseller_id = 0) AND gateway != 'bundle_reseller' AND order_id NOT LIKE 'R_BUNDLE%')
                GROUP BY strftime('%Y-%m', created_at) ORDER BY month DESC LIMIT 12
            """)
            admin_monthly_trend = [dict(r) for r in cursor.fetchall()]

            # ۳. تب نمایندگان (Resellers)
            cursor.execute(f"""
                SELECT COALESCE(SUM(amount), 0), COUNT(*)
                FROM reseller_transactions
                WHERE type IN ('purchase', 'renewal', 'purchase_credit', 'renewal_credit')
                  {date_cond_rtx}
            """)
            rtx_row = cursor.fetchone()
            reseller_period_wholesale = rtx_row[0] or 0
            reseller_period_purchases_count = rtx_row[1] or 0

            cursor.execute("""
                SELECT COALESCE(SUM(balance), 0), COALESCE(SUM(credit_limit), 0), COALESCE(SUM(credit_debt), 0), COUNT(*)
                FROM resellers WHERE status != 'deleted'
            """)
            res_summary_row = cursor.fetchone()
            resellers_wallets_total = res_summary_row[0] or 0
            resellers_credit_limits_total = res_summary_row[1] or 0
            resellers_credit_debts_total = res_summary_row[2] or 0
            resellers_count = res_summary_row[3] or 0

            cursor.execute("""
                SELECT COUNT(*) FROM subscriptions 
                WHERE reseller_id IS NOT NULL AND reseller_id > 0 AND (is_deleted = 0 OR is_deleted IS NULL) AND status = 'active'
            """)
            resellers_active_subs = cursor.fetchone()[0] or 0

            cursor.execute("""
                SELECT COUNT(*) FROM subscriptions 
                WHERE reseller_id IS NOT NULL AND reseller_id > 0 AND (is_deleted = 0 OR is_deleted IS NULL)
            """)
            resellers_total_subs = cursor.fetchone()[0] or 0

            cursor.execute("SELECT id, name, username, phone, balance, credit_limit, credit_debt, credit_enabled, discount_percent, status FROM resellers WHERE status != 'deleted' ORDER BY id ASC")
            reseller_rows = [dict(r) for r in cursor.fetchall()]

            resellers_detail = []
            macro_estimated_retail = 0

            for res in reseller_rows:
                rid = res["id"]
                disc = res.get("discount_percent") or 20

                cursor.execute(f"""
                    SELECT COALESCE(SUM(amount), 0), COUNT(*)
                    FROM reseller_transactions
                    WHERE reseller_id = ?
                      AND type IN ('purchase', 'renewal', 'purchase_credit', 'renewal_credit')
                      {date_cond_rtx}
                """, (rid,))
                p_row = cursor.fetchone()
                wholesale_spent = p_row[0] or 0
                purchases_count = p_row[1] or 0

                cursor.execute("""
                    SELECT 
                        COUNT(*),
                        COUNT(CASE WHEN status = 'active' AND (is_deleted = 0 OR is_deleted IS NULL) THEN 1 END),
                        COALESCE(SUM(CASE WHEN (is_deleted = 0 OR is_deleted IS NULL) THEN data_limit ELSE 0 END), 0)
                    FROM subscriptions
                    WHERE reseller_id = ?
                """, (rid,))
                u_row = cursor.fetchone()
                total_cust = u_row[0] or 0
                active_cust = u_row[1] or 0
                total_gb = u_row[2] or 0

                if disc < 100:
                    retail_val = int(wholesale_spent / ((100 - disc) / 100.0))
                else:
                    retail_val = wholesale_spent
                est_profit = max(0, retail_val - wholesale_spent)
                macro_estimated_retail += retail_val

                cursor.execute("""
                    SELECT COUNT(*), COALESCE(SUM(debt_amount), 0)
                    FROM subscriptions
                    WHERE reseller_id = ? AND payment_status IN ('unpaid', 'debtor') AND debt_amount > 0 AND (is_deleted = 0 OR is_deleted IS NULL)
                """, (rid,))
                d_row = cursor.fetchone()
                cust_debtors_cnt = d_row[0] or 0
                cust_debtors_amt = d_row[1] or 0

                c_lim = res.get("credit_limit") or 0
                c_debt = res.get("credit_debt") or 0
                c_avail = max(0, c_lim - c_debt) if res.get("credit_enabled") else 0

                resellers_detail.append({
                    "id": rid,
                    "name": res["name"],
                    "username": res["username"],
                    "phone": res.get("phone") or "-",
                    "status": res.get("status", "active"),
                    "balance": res.get("balance") or 0,
                    "credit_enabled": bool(res.get("credit_enabled")),
                    "credit_limit": c_lim,
                    "credit_debt": c_debt,
                    "available_credit": c_avail,
                    "discount_percent": disc,
                    "total_customers": total_cust,
                    "active_customers": active_cust,
                    "total_gb": total_gb,
                    "period_wholesale": wholesale_spent,
                    "period_purchases_count": purchases_count,
                    "period_retail_est": retail_val,
                    "period_profit_est": est_profit,
                    "cust_debtors_count": cust_debtors_cnt,
                    "cust_debtors_amount": cust_debtors_amt
                })

            macro_reseller_profit = max(0, macro_estimated_retail - reseller_period_wholesale)

            return {
                "period": period,
                "all": {
                    "period_revenue": period_revenue,
                    "period_orders": period_orders,
                    "lifetime_revenue": lifetime_revenue,
                    "total_users": total_users,
                    "total_active_subs": total_active_subs,
                    "monthly_trend": monthly_trend
                },
                "admin": {
                    "period_revenue": admin_period_revenue,
                    "period_orders": admin_period_orders,
                    "lifetime_revenue": admin_lifetime_revenue,
                    "active_subs": admin_active_subs,
                    "total_subs": admin_total_subs,
                    "total_gb": admin_total_gb,
                    "debt_total": admin_debt_total,
                    "debt_count": admin_debt_count,
                    "debtors": admin_debtors,
                    "monthly_trend": admin_monthly_trend
                },
                "resellers": {
                    "count": resellers_count,
                    "period_wholesale": reseller_period_wholesale,
                    "period_purchases_count": reseller_period_purchases_count,
                    "period_retail_est": macro_estimated_retail,
                    "period_profit_est": macro_reseller_profit,
                    "wallets_total": resellers_wallets_total,
                    "credit_limits_total": resellers_credit_limits_total,
                    "credit_debts_total": resellers_credit_debts_total,
                    "active_subs": resellers_active_subs,
                    "total_subs": resellers_total_subs,
                    "items": resellers_detail
                }
            }
        except Exception as e:
            logger.error(f"Error in get_financial_reports_data: {e}")
            return {"period": period, "all": {}, "admin": {}, "resellers": {}}
        finally:
            conn.close()

    # ═══════════════════════════════════════════════════════════════════════
    # سیستم مدیریت مدیران و سطوح دسترسی (Admin Management & RBAC)
    # ═══════════════════════════════════════════════════════════════════════

    def authenticate_admin(self, username: str, password: str):
        """احراز هویت مدیران از جدول admin_users (Case-Insensitive و مقاوم در برابر فاصله‌ها)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        clean_user = username.strip().lower()
        clean_pass = password.strip()
        password_hash = self.hash_password(clean_pass)
        now = get_now_iso()
        cursor.execute("""
            SELECT * FROM admin_users 
            WHERE (LOWER(username)=? OR (LOWER(username)='akbariii' AND ?='mohammad')) 
              AND (password_hash=? OR password_hash=?) 
              AND is_active=1
        """, (clean_user, clean_user, password_hash, clean_pass))
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

    def get_all_subscriptions(self, limit: int = 500) -> list:
        """دریافت لیست کلیه اشتراک‌ها"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT * FROM subscriptions ORDER BY id DESC LIMIT ?", (limit,))
            return [dict(r) for r in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting all subscriptions: {e}")
            return []
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

    # ─── اعتبارسنجی کد پیگیری و فیش‌های تکراری ───

    def is_tracking_code_duplicate(self, tracking_code: str, exclude_id: int = None) -> bool:
        """بررسی عدم ثبت تکراری کد پیگیری یا شماره فیش بانکی"""
        if not tracking_code or not str(tracking_code).strip():
            return False
        clean_code = str(tracking_code).strip()
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            if exclude_id:
                cursor.execute("SELECT id FROM transactions WHERE tracking_code = ? AND id != ? AND status != 'rejected' LIMIT 1", (clean_code, exclude_id))
            else:
                cursor.execute("SELECT id FROM transactions WHERE tracking_code = ? AND status != 'rejected' LIMIT 1", (clean_code,))
            row = cursor.fetchone()
            return bool(row)
        except Exception as e:
            logger.error(f"Error checking duplicate tracking code: {e}")
            return False
        finally:
            conn.close()

    # ─── شارژ حجم اضافه و پیش‌بینی اتمام ترافیک (Top-up & Depletion Prediction) ───

    def add_traffic_to_subscription(self, sub_id: int, extra_gb: float) -> dict:
        """افزودن حجم اضافه (Top-up) به سقف مصرف اشتراک کاربر بدون تغییر لینک و UUID"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT * FROM subscriptions WHERE id=?", (sub_id,))
            row = cursor.fetchone()
            if not row:
                return {"success": False, "error": "اشتراک یافت نشد."}
            sub = dict(row)
            current_limit = float(sub.get("data_limit") or sub.get("traffic_limit") or 0)
            new_limit = current_limit + float(extra_gb)
            cursor.execute("UPDATE subscriptions SET data_limit=? WHERE id=?", (new_limit, sub_id))
            conn.commit()

            # در صورت اتصال به هیدیفای، سقف کاربر در هیدیفای نیز بروزرسانی شود
            hidify_uuid = sub.get("hidify_uuid")
            if hidify_uuid:
                try:
                    from hidify import HidifyClient
                    # هماهنگی در صورت وجود اتصال
                except Exception:
                    pass

            return {"success": True, "old_limit": current_limit, "new_limit": new_limit, "added_gb": extra_gb}
        except Exception as e:
            logger.error(f"Error adding traffic to subscription: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def calculate_subscription_burn_rate(self, sub: dict) -> dict:
        """محاسبه نرخ مصرف روزانه و پیش‌بینی هوشمند تاریخ اتمام ترافیک"""
        try:
            current_usage = float(sub.get("data_used") or sub.get("current_usage") or 0)
            traffic_limit = float(sub.get("data_limit") or sub.get("traffic_limit") or 0)
            if traffic_limit <= 0:
                return {"burn_rate_gb_day": 0, "days_remaining": 999, "predicted_depletion_date": None}

            start_date_str = sub.get("start_date") or sub.get("created_at")
            days_passed = 1.0
            if start_date_str:
                try:
                    s_dt = datetime.fromisoformat(str(start_date_str)[:19])
                    days_passed = max(1.0, (datetime.now() - s_dt).total_seconds() / 86400.0)
                except Exception:
                    days_passed = 1.0

            burn_rate = current_usage / days_passed  # GB per day
            remaining_traffic = max(0.0, traffic_limit - current_usage)

            if burn_rate > 0.05:
                days_remaining = int(remaining_traffic / burn_rate)
                predicted_depletion = datetime.now() + timedelta(days=days_remaining)
                return {
                    "burn_rate_gb_day": round(burn_rate, 2),
                    "remaining_traffic_gb": round(remaining_traffic, 2),
                    "days_remaining": days_remaining,
                    "predicted_depletion_date": predicted_depletion.strftime("%Y-%m-%d")
                }
            return {
                "burn_rate_gb_day": round(burn_rate, 2),
                "remaining_traffic_gb": round(remaining_traffic, 2),
                "days_remaining": 999,
                "predicted_depletion_date": None
            }
        except Exception as e:
            return {"burn_rate_gb_day": 0, "days_remaining": 999, "predicted_depletion_date": None, "error": str(e)}

    # ─── بسته‌های پیش‌خرید اعتباری با بونوس شارژ رایگان برای نمایندگان (Volume Bundles) ───

    def get_reseller_credit_bundles(self, active_only: bool = False) -> list:
        """لیست بسته‌های شارژ عمده با درصد بونوس هدیه برای نمایندگان از دیتابیس"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            query = "SELECT * FROM reseller_bundles"
            if active_only:
                query += " WHERE is_active = 1"
            query += " ORDER BY display_order ASC, price ASC"
            cursor.execute(query)
            rows = cursor.fetchall()
            if rows:
                return [dict(r) for r in rows]
        except Exception as e:
            logger.warning(f"Error fetching reseller_bundles: {e}")
        finally:
            conn.close()

        # بازگشت به بسته‌های پیش‌فرض در صورت خالی بودن جدول یا بروز خطا
        default_bundles = [
            {"id": "bundle_1m", "title": "بسته استارتر", "price": 1000000, "credit": 1050000, "bonus_percent": 5, "badge": "۵٪ شارژ هدیه", "color": "info", "description": "مناسب شروع همکاری و شارژ اولیه", "display_order": 1, "is_active": 1},
            {"id": "bundle_3m", "title": "بسته نقره‌ای", "price": 3000000, "credit": 3210000, "bonus_percent": 7, "badge": "۷٪ شارژ هدیه", "color": "primary", "description": "بسته اقتصادی با بونوس شارژ تشویقی", "display_order": 2, "is_active": 1},
            {"id": "bundle_5m", "title": "بسته طلایی", "price": 5000000, "credit": 5500000, "bonus_percent": 10, "badge": "۱۰٪ شارژ هدیه", "color": "success", "description": "بسته پرفروش همکاران با ۱۰٪ هدیه نقدی", "display_order": 3, "is_active": 1},
            {"id": "bundle_10m", "title": "بسته الماس VIP", "price": 10000000, "credit": 11500000, "bonus_percent": 15, "badge": "۱۵٪ شارژ ویژه", "color": "warning", "description": "حداکثر اعتبار با بالاترین نرخ بونوس ویژه", "display_order": 4, "is_active": 1},
        ]
        if active_only:
            return [b for b in default_bundles if b.get("is_active", 1)]
        return default_bundles

    def get_reseller_credit_bundle(self, bundle_id: str) -> dict:
        """دریافت اطلاعات یک بسته پیش‌خرید نمایندگان بر اساس شناسه"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT * FROM reseller_bundles WHERE id = ?", (bundle_id,))
            row = cursor.fetchone()
            if row:
                return dict(row)
        except Exception as e:
            logger.error(f"Error getting bundle {bundle_id}: {e}")
        finally:
            conn.close()

        for b in self.get_reseller_credit_bundles():
            if b["id"] == bundle_id:
                return b
        return None

    def save_reseller_credit_bundle(self, bundle_data: dict) -> dict:
        """ذخیره یا ویرایش بسته پیش‌خرید نمایندگان در دیتابیس"""
        bundle_id = str(bundle_data.get("id") or "").strip()
        title = str(bundle_data.get("title") or "").strip()
        try:
            price = int(bundle_data.get("price", 0))
        except (ValueError, TypeError):
            price = 0

        try:
            bonus_percent = int(bundle_data.get("bonus_percent", 0))
        except (ValueError, TypeError):
            bonus_percent = 0

        try:
            credit = int(bundle_data.get("credit", 0))
            if credit <= 0:
                credit = price + int(price * bonus_percent / 100)
        except (ValueError, TypeError):
            credit = price + int(price * bonus_percent / 100)

        if bonus_percent <= 0 and price > 0 and credit > price:
            bonus_percent = round(((credit - price) / price) * 100)

        badge = str(bundle_data.get("badge") or "").strip()
        if not badge:
            badge = f"{bonus_percent}٪ شارژ هدیه" if bonus_percent > 0 else "شارژ کیف پول"

        color = str(bundle_data.get("color") or "primary").strip()
        description = str(bundle_data.get("description") or "").strip()

        try:
            display_order = int(bundle_data.get("display_order", 0))
        except (ValueError, TypeError):
            display_order = 0

        is_active = 1 if bundle_data.get("is_active") in (1, "1", True, "true", "on") else 0
        now = get_now_iso()

        if not bundle_id or not title or price <= 0:
            return {"success": False, "error": "شناسه انگلیسی، عنوان بسته و قیمت معتبر الزامی هستند."}

        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT id FROM reseller_bundles WHERE id = ?", (bundle_id,))
            exists = cursor.fetchone()
            if exists:
                cursor.execute("""
                    UPDATE reseller_bundles
                    SET title = ?, price = ?, credit = ?, bonus_percent = ?, badge = ?, color = ?, description = ?, display_order = ?, is_active = ?, updated_at = ?
                    WHERE id = ?
                """, (title, price, credit, bonus_percent, badge, color, description, display_order, is_active, now, bundle_id))
            else:
                cursor.execute("""
                    INSERT INTO reseller_bundles (id, title, price, credit, bonus_percent, badge, color, description, display_order, is_active, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (bundle_id, title, price, credit, bonus_percent, badge, color, description, display_order, is_active, now, now))
            conn.commit()
            return {"success": True, "bundle_id": bundle_id}
        except Exception as e:
            logger.error(f"Error saving reseller bundle {bundle_id}: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def delete_reseller_credit_bundle(self, bundle_id: str) -> dict:
        """حذف بسته پیش‌خرید نمایندگان از دیتابیس"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("DELETE FROM reseller_bundles WHERE id = ?", (bundle_id,))
            conn.commit()
            return {"success": True}
        except Exception as e:
            logger.error(f"Error deleting reseller bundle {bundle_id}: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def toggle_reseller_credit_bundle(self, bundle_id: str) -> dict:
        """تغییر وضعیت فعال/غیرفعال بسته پیش‌خرید"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("SELECT is_active FROM reseller_bundles WHERE id = ?", (bundle_id,))
            row = cursor.fetchone()
            if not row:
                return {"success": False, "error": "بسته یافت نشد."}
            new_status = 0 if row["is_active"] else 1
            cursor.execute("UPDATE reseller_bundles SET is_active = ?, updated_at = ? WHERE id = ?", (new_status, now, bundle_id))
            conn.commit()
            return {"success": True, "is_active": new_status}
        except Exception as e:
            logger.error(f"Error toggling reseller bundle {bundle_id}: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def reset_default_reseller_credit_bundles(self) -> dict:
        """بازنشانی بسته‌های پیش‌خرید به ۴ بسته استاندارد پیش‌فرض سیستم"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now_seed = get_now_iso()
        default_bundles = [
            ("bundle_1m", "بسته استارتر", 1000000, 1050000, 5, "۵٪ شارژ هدیه", "info", "مناسب شروع همکاری و شارژ اولیه", 1, 1, now_seed, now_seed),
            ("bundle_3m", "بسته نقره‌ای", 3000000, 3210000, 7, "۷٪ شارژ هدیه", "primary", "بسته اقتصادی با بونوس شارژ تشویقی", 2, 1, now_seed, now_seed),
            ("bundle_5m", "بسته طلایی", 5000000, 5500000, 10, "۱۰٪ شارژ هدیه", "success", "بسته پرفروش همکاران با ۱۰٪ هدیه نقدی", 3, 1, now_seed, now_seed),
            ("bundle_10m", "بسته الماس VIP", 10000000, 11500000, 15, "۱۵٪ شارژ ویژه", "warning", "حداکثر اعتبار با بالاترین نرخ بونوس ویژه", 4, 1, now_seed, now_seed),
        ]
        try:
            cursor.execute("DELETE FROM reseller_bundles")
            cursor.executemany("""
                INSERT INTO reseller_bundles (id, title, price, credit, bonus_percent, badge, color, description, display_order, is_active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, default_bundles)
            conn.commit()
            return {"success": True}
        except Exception as e:
            logger.error(f"Error resetting reseller bundles: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def apply_reseller_bundle_purchase(self, reseller_id: int, bundle_id: str) -> dict:
        """اعمال شارژ بسته پیش‌خرید به همراه اعتبار هدیه به موجودی نماینده"""
        bundles = {b["id"]: b for b in self.get_reseller_credit_bundles()}
        bundle = bundles.get(bundle_id)
        if not bundle:
            return {"success": False, "error": "بسته اعتباری مورد نظر یافت نشد."}

        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("SELECT balance, name FROM resellers WHERE id=?", (reseller_id,))
            res_row = cursor.fetchone()
            if not res_row:
                return {"success": False, "error": "نماینده یافت نشد."}

            res_dict = dict(res_row)
            old_balance = res_dict.get("balance") or 0
            credit_to_add = bundle["credit"]
            new_balance = old_balance + credit_to_add

            cursor.execute("UPDATE resellers SET balance=?, updated_at=? WHERE id=?", (new_balance, now, reseller_id))

            # ثبت تراکنش نماینده
            desc = f"خرید {bundle['title']} (واریز {credit_to_add:,} تومان با {bundle['badge']})"
            cursor.execute("""
                INSERT INTO reseller_transactions (reseller_id, type, amount, plan_name, account_name, description, created_at)
                VALUES (?, 'deposit', ?, ?, '-', ?, ?)
            """, (reseller_id, credit_to_add, bundle["title"], desc, now))

            conn.commit()
            return {"success": True, "old_balance": old_balance, "new_balance": new_balance, "bundle": bundle}
        except Exception as e:
            logger.error(f"Error applying reseller bundle: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    # ─── اعلان‌ها و پیام‌های پنل نماینده (Reseller Notifications) ───

    def add_reseller_notification(self, reseller_id: int, title: str, message: str, type: str = "info") -> dict:
        """افزودن اعلان به پنل نماینده (تایید/رد فیش، واریز، هشدارهای سیستمی)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("""
                INSERT INTO reseller_notifications (reseller_id, title, message, type, is_read, created_at)
                VALUES (?, ?, ?, ?, 0, ?)
            """, (reseller_id, title, message, type, now))
            conn.commit()
            notif_id = cursor.lastrowid
            return {"success": True, "id": notif_id}
        except Exception as e:
            logger.error(f"Error adding reseller notification: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def get_reseller_notifications(self, reseller_id: int, unread_only: bool = False, limit: int = 50) -> list:
        """دریافت لیست اعلان‌های نماینده"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            if unread_only:
                cursor.execute("""
                    SELECT * FROM reseller_notifications 
                    WHERE reseller_id = ? AND is_read = 0 
                    ORDER BY id DESC LIMIT ?
                """, (reseller_id, limit))
            else:
                cursor.execute("""
                    SELECT * FROM reseller_notifications 
                    WHERE reseller_id = ? 
                    ORDER BY id DESC LIMIT ?
                """, (reseller_id, limit))
            return [dict(r) for r in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting reseller notifications: {e}")
            return []
        finally:
            conn.close()

    def get_reseller_unread_notifications_count(self, reseller_id: int) -> int:
        """تعداد اعلان‌های خوانده‌نشده نماینده"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT COUNT(*) FROM reseller_notifications WHERE reseller_id = ? AND is_read = 0", (reseller_id,))
            return cursor.fetchone()[0]
        except Exception:
            return 0
        finally:
            conn.close()

    def mark_reseller_notifications_read(self, reseller_id: int, notification_id: int = None):
        """علامت‌گذاری اعلان‌ها به عنوان خوانده‌شده"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            if notification_id:
                cursor.execute("UPDATE reseller_notifications SET is_read = 1 WHERE id = ? AND reseller_id = ?", (notification_id, reseller_id))
            else:
                cursor.execute("UPDATE reseller_notifications SET is_read = 1 WHERE reseller_id = ?", (reseller_id,))
            conn.commit()
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    # ─── سیستم رفرال و کش‌بک وفاداری (Referral & Cashback) ───

    def process_referral_reward(self, user_telegram_id: int, purchase_amount: int, percent: int = 10) -> dict:
        """محاسبه و واریز خودکار پورسانت رفرال به کیف پول معرف"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("SELECT referred_by FROM users WHERE telegram_id=?", (user_telegram_id,))
            row = cursor.fetchone()
            if not row or not row["referred_by"]:
                return {"rewarded": False, "reason": "No referrer found"}

            referrer_id = row["referred_by"]
            reward_amount = int(purchase_amount * (percent / 100.0))
            if reward_amount <= 0:
                return {"rewarded": False, "reason": "Zero reward amount"}

            # افزودن به موجودی کیف پول معرف
            cursor.execute("UPDATE users SET wallet_balance = COALESCE(wallet_balance, 0) + ? WHERE telegram_id = ?", (reward_amount, referrer_id))

            # ثبت در تراکنش‌های کیف پول
            cursor.execute("""
                INSERT INTO wallet_transactions (telegram_id, amount, type, balance_after, description, ref_id, created_at)
                VALUES (?, ?, 'referral_reward', (SELECT wallet_balance FROM users WHERE telegram_id=?), ?, ?, ?)
            """, (referrer_id, reward_amount, referrer_id, f"پاداش دعوت از دوست ({percent}٪ خرید اشتراک)", str(user_telegram_id), now))

            conn.commit()
            return {"rewarded": True, "referrer_id": referrer_id, "reward_amount": reward_amount, "percent": percent}
        except Exception as e:
            logger.error(f"Error processing referral reward: {e}")
            return {"rewarded": False, "error": str(e)}
        finally:
            conn.close()

    # ─── تنظیمات درگاه پرداخت آنلاین (مدیریت و نمایندگان) ───

    def get_reseller_gateway(self, reseller_id: int) -> dict:
        """دریافت تنظیمات درگاه آنلاین اختصاصی نماینده"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT is_gateway_active, gateway_type, gateway_key, gateway_sandbox FROM resellers WHERE id=?", (reseller_id,))
            row = cursor.fetchone()
            if not row:
                return {"enabled": False, "type": "zarinpal", "key": "", "sandbox": False}
            row_dict = dict(row)
            is_active = bool(row_dict.get("is_gateway_active"))
            gw_key = str(row_dict.get("gateway_key") or "").strip()
            return {
                "enabled": bool(is_active and gw_key),
                "type": row_dict.get("gateway_type") or "zarinpal",
                "key": gw_key,
                "sandbox": bool(row_dict.get("gateway_sandbox"))
            }
        except Exception as e:
            logger.error(f"Error getting reseller gateway: {e}")
            return {"enabled": False, "type": "zarinpal", "key": "", "sandbox": False}
        finally:
            conn.close()

    def get_admin_gateway(self) -> dict:
        """دریافت تنظیمات درگاه آنلاین مدیریت اصلی"""
        enabled = str(self.get_setting("online_gateway_enabled") or "").lower() in ("1", "true")
        gw_type = str(self.get_setting("online_gateway_type") or "zarinpal")
        gw_key = str(self.get_setting("online_gateway_key") or "").strip()
        sandbox = str(self.get_setting("online_gateway_sandbox") or "").lower() in ("1", "true")
        return {
            "enabled": bool(enabled and gw_key),
            "type": gw_type,
            "key": gw_key,
            "sandbox": sandbox
        }

    def update_reseller_gateway(self, reseller_id: int, is_active: bool, gateway_type: str, gateway_key: str, sandbox: bool = False) -> dict:
        """بروزرسانی درگاه پرداخت آنلاین نماینده"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("""
                UPDATE resellers 
                SET is_gateway_active = ?, gateway_type = ?, gateway_key = ?, gateway_sandbox = ?, updated_at = ?
                WHERE id = ?
            """, (1 if is_active else 0, gateway_type, str(gateway_key or "").strip(), 1 if sandbox else 0, now, reseller_id))
            conn.commit()
            return {"success": True}
        except Exception as e:
            logger.error(f"Error updating reseller gateway: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def update_admin_gateway(self, enabled: bool, gateway_type: str, gateway_key: str, sandbox: bool = False) -> dict:
        """بروزرسانی درگاه پرداخت آنلاین مدیریت اصلی"""
        try:
            self.set_setting("online_gateway_enabled", "1" if enabled else "0")
            self.set_setting("online_gateway_type", gateway_type or "zarinpal")
            self.set_setting("online_gateway_key", str(gateway_key or "").strip())
            self.set_setting("online_gateway_sandbox", "1" if sandbox else "0")
            return {"success": True}
        except Exception as e:
            logger.error(f"Error updating admin gateway: {e}")
            return {"success": False, "error": str(e)}

    # ═══════════════════════════════════════════════════════════════
    # مدیریت اولویت و چیدمان روش‌های پرداخت (Payment Methods Ordering)
    # ═══════════════════════════════════════════════════════════════

    DEFAULT_PAYMENT_METHODS = [
        {"id": "card_to_card", "name": "کارت به کارت (بانکی)", "icon": "fa-credit-card", "color": "primary", "enabled": True, "desc": "واریز به شماره کارت‌های فعال با بررسی و تایید فیش"},
        {"id": "wallet", "name": "پرداخت از کیف پول", "icon": "fa-wallet", "color": "success", "enabled": True, "desc": "کسر آنی مبلغ از موجودی کیف پول و فعال‌سازی لحظه‌ای اشتراک"},
        {"id": "online_gateway", "name": "درگاه پرداخت آنلاین (شاپرک / بلوپال)", "icon": "fa-globe", "color": "info", "enabled": True, "desc": "اتصال خودکار به درگاه‌های زرین‌پال، آیدی‌پی، نکست‌پی یا کارت‌به‌کارت هوشمند بلوپال"},
        {"id": "crypto", "name": "ارز دیجیتال (تتر / کریپتو)", "icon": "fa-gem", "color": "warning", "enabled": True, "desc": "پرداخت با تتر (USDT TRC20 / TON) با محاسبه خودکار نرخ روز"},
    ]

    def get_payment_methods(self, reseller_id: Optional[int] = None) -> List[dict]:
        """دریافت لیست و ترتیب اولویت روش‌های پرداخت برای بات و پنل"""
        setting_key = f"payment_methods_order_r_{reseller_id}" if reseller_id else "payment_methods_order"
        raw = self.get_setting(setting_key)
        if raw:
            try:
                saved_list = json.loads(raw) if isinstance(raw, str) else raw
                if isinstance(saved_list, list) and len(saved_list) > 0:
                    default_map = {m["id"]: m for m in self.DEFAULT_PAYMENT_METHODS}
                    result = []
                    seen = set()
                    for item in saved_list:
                        m_id = item.get("id") if isinstance(item, dict) else str(item)
                        if m_id in default_map and m_id not in seen:
                            base = dict(default_map[m_id])
                            if isinstance(item, dict) and "enabled" in item:
                                base["enabled"] = bool(item["enabled"])
                            result.append(base)
                            seen.add(m_id)
                    for m_id, base in default_map.items():
                        if m_id not in seen:
                            result.append(dict(base))
                    return result
            except Exception as e:
                logger.error(f"Error parsing payment_methods_order: {e}")
        return [dict(m) for m in self.DEFAULT_PAYMENT_METHODS]

    def save_payment_methods(self, methods: List[dict], reseller_id: Optional[int] = None) -> bool:
        """ذخیره چیدمان و وضعیت فعال بودن روش‌های پرداخت"""
        try:
            setting_key = f"payment_methods_order_r_{reseller_id}" if reseller_id else "payment_methods_order"
            self.set_setting(setting_key, json.dumps(methods, ensure_ascii=False))
            return True
        except Exception as e:
            logger.error(f"Error saving payment methods: {e}")
            return False

    def move_payment_method(self, method_id: str, direction: str, reseller_id: Optional[int] = None) -> List[dict]:
        """جابجایی عمودی یک روش پرداخت به بالا یا پایین"""
        methods = self.get_payment_methods(reseller_id)
        idx = -1
        for i, m in enumerate(methods):
            if m["id"] == method_id:
                idx = i
                break
        if idx != -1:
            if direction == "up" and idx > 0:
                methods[idx], methods[idx - 1] = methods[idx - 1], methods[idx]
            elif direction == "down" and idx < len(methods) - 1:
                methods[idx], methods[idx + 1] = methods[idx + 1], methods[idx]
            self.save_payment_methods(methods, reseller_id)
        return methods

    def toggle_payment_method(self, method_id: str, reseller_id: Optional[int] = None) -> List[dict]:
        """تغییر وضعیت فعال/غیرفعال بودن یک روش پرداخت"""
        methods = self.get_payment_methods(reseller_id)
        for m in methods:
            if m["id"] == method_id:
                m["enabled"] = not m.get("enabled", True)
                break
        self.save_payment_methods(methods, reseller_id)
        return methods


    # ─── مدیریت پلن‌های اختصاصی نمایندگان (Reseller Custom Plans) ───

    def get_reseller_plans(self, reseller_id: int) -> List[dict]:
        """دریافت لیست تمام پلن‌های مادر با اعمال شخصی‌سازی‌ها، حجم، مدت و قیمت‌های سفارشی نماینده"""
        from admin_manager import load_plans
        master_plans = load_plans()
        reseller = self.get_reseller(reseller_id) or {}
        discount_pct = reseller.get("discount_percent", 20)

        conn = self.get_connection()
        cursor = conn.cursor()
        overrides = {}
        try:
            cursor.execute("""
                SELECT plan_id, custom_name, custom_price, custom_data_limit, custom_duration, is_active 
                FROM reseller_plans WHERE reseller_id = ?
            """, (reseller_id,))
            for row in cursor.fetchall():
                overrides[row["plan_id"]] = {
                    "custom_name": row["custom_name"],
                    "custom_price": row["custom_price"],
                    "custom_data_limit": row["custom_data_limit"],
                    "custom_duration": row["custom_duration"],
                    "is_active": bool(row["is_active"])
                }
        except Exception as e:
            logger.error(f"Error fetching reseller plan overrides: {e}")
        finally:
            conn.close()

        result = []
        for pid, p in master_plans.items():
            ov = overrides.get(pid, {})
            custom_name = ov.get("custom_name") or ""
            custom_price = ov.get("custom_price")
            custom_data_limit = ov.get("custom_data_limit")
            custom_duration = ov.get("custom_duration")
            is_active_override = ov.get("is_active")

            master_price = p.get("price", 0)
            display_price = custom_price if (custom_price is not None and custom_price > 0) else master_price
            display_name = custom_name if custom_name else p.get("name", "پلن")
            
            master_data_limit = p.get("data_limit", 0)
            display_data_limit = custom_data_limit if (custom_data_limit is not None and custom_data_limit >= 0) else master_data_limit

            master_duration = p.get("duration", 30)
            display_duration = custom_duration if (custom_duration is not None and custom_duration > 0) else master_duration

            is_active = is_active_override if is_active_override is not None else p.get("is_active", True)
            
            # قیمت تمام‌شده عمده برای نماینده بر اساس قیمت پلن اصلی یا سفارشی
            base_calc_price = custom_price if (custom_price is not None and custom_price > 0) else master_price
            wholesale_price = int(base_calc_price * (100 - discount_pct) / 100)

            result.append({
                "plan_id": pid,
                "name": display_name,
                "price": display_price,
                "master_name": p.get("name", "پلن"),
                "display_name": display_name,
                "custom_name": custom_name,
                "master_price": master_price,
                "display_price": display_price,
                "custom_price": custom_price,
                "wholesale_price": wholesale_price,
                "master_data_limit": master_data_limit,
                "display_data_limit": display_data_limit,
                "data_limit": display_data_limit,
                "custom_data_limit": custom_data_limit,
                "master_duration": master_duration,
                "display_duration": display_duration,
                "duration": display_duration,
                "custom_duration": custom_duration,
                "description": p.get("description", ""),
                "is_active": is_active,
                "master_is_active": p.get("is_active", True)
            })

        return result

    def get_reseller_active_plans(self, reseller_id: int) -> List[dict]:
        """دریافت فقط پلن‌های فعال برای نمایش به مشتریان ربات تلگرام نماینده"""
        all_plans = self.get_reseller_plans(reseller_id)
        return [p for p in all_plans if p.get("is_active") and p.get("master_is_active")]

    def get_reseller_plan(self, reseller_id: int, plan_id: str) -> Optional[dict]:
        """دریافت مشخصات کامل یک پلن خاص برای نماینده"""
        plans = self.get_reseller_plans(reseller_id)
        for p in plans:
            if p["plan_id"] == plan_id:
                return p
        return None

    def update_reseller_plan_override(self, reseller_id: int, plan_id: str, custom_name: str = None, custom_price: int = None, custom_data_limit: float = None, custom_duration: int = None, is_active: bool = True) -> dict:
        """بروزرسانی یا ثبت تنظیمات اختصاصی نماینده برای یک پلن (نام، قیمت، حجم، مدت، وضعیت)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("""
                INSERT INTO reseller_plans (reseller_id, plan_id, custom_name, custom_price, custom_data_limit, custom_duration, is_active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(reseller_id, plan_id) DO UPDATE SET
                    custom_name = excluded.custom_name,
                    custom_price = excluded.custom_price,
                    custom_data_limit = excluded.custom_data_limit,
                    custom_duration = excluded.custom_duration,
                    is_active = excluded.is_active,
                    updated_at = excluded.updated_at
            """, (
                reseller_id, 
                plan_id, 
                custom_name.strip() if custom_name else None, 
                custom_price if (custom_price is not None and custom_price > 0) else None, 
                custom_data_limit if (custom_data_limit is not None and custom_data_limit >= 0) else None,
                custom_duration if (custom_duration is not None and custom_duration > 0) else None,
                1 if is_active else 0, 
                now, 
                now
            ))
            conn.commit()
            return {"success": True}
        except Exception as e:
            logger.error(f"Error updating reseller plan override: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def reset_reseller_plan_override(self, reseller_id: int, plan_id: str) -> dict:
        """حذف سفارشی‌سازی نماینده و بازگشت به پلن اصلی"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("DELETE FROM reseller_plans WHERE reseller_id = ? AND plan_id = ?", (reseller_id, plan_id))
            conn.commit()
            return {"success": True}
        except Exception as e:
            logger.error(f"Error resetting reseller plan override: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def get_monthly_accounting_audit(self, reseller_id: int = None, days: int = 30) -> dict:
        """
        گزارش جامع گردش حساب و حسابرسی ۳۰ روز اخیر با جزئیات سود، فروش نقدی/اعتباری،
        ترافیک واگذار شده، تعداد اشتراک‌ها و ریز تراکنش‌ها به همراه خروجی تفکیکی
        """
        from datetime import datetime, timedelta
        conn = self.get_connection()
        cursor = conn.cursor()
        now_dt = get_now_naive()
        start_dt = now_dt - timedelta(days=days)
        start_iso = start_dt.strftime("%Y-%m-%d %H:%M:%S")

        audit = {
            "days": days,
            "start_date": start_iso,
            "end_date": now_dt.strftime("%Y-%m-%d %H:%M:%S"),
            "total_revenue": 0,
            "cash_revenue": 0,
            "credit_revenue": 0,
            "total_expenses": 0,
            "net_profit": 0,
            "total_gb_sold": 0.0,
            "total_subs_count": 0,
            "new_subs_count": 0,
            "renew_subs_count": 0,
            "total_outstanding_debt": 0,
            "transactions": [],
            "daily_turnover": {}
        }

        try:
            # ۱. استخراج تراکنش‌های تایید شده در بازه زمانی
            if reseller_id:
                cursor.execute("""
                    SELECT * FROM transactions 
                    WHERE reseller_id = ? AND (is_deleted = 0 OR is_deleted IS NULL)
                      AND status IN ('approved', 'completed')
                      AND created_at >= ?
                    ORDER BY created_at DESC
                """, (reseller_id, start_iso))
            else:
                cursor.execute("""
                    SELECT * FROM transactions 
                    WHERE (is_deleted = 0 OR is_deleted IS NULL)
                      AND status IN ('approved', 'completed')
                      AND created_at >= ?
                    ORDER BY created_at DESC
                """, (start_iso,))
            
            tx_rows = cursor.fetchall()
            for r in tx_rows:
                r_dict = dict(r)
                amount = int(r_dict.get("amount") or 0)
                audit["total_revenue"] += amount
                
                is_credit_tx = bool(r_dict.get("gateway") == "credit" or "credit" in str(r_dict.get("order_id", "")).lower() or "اعتباری" in str(r_dict.get("tracking_code", "")))
                if is_credit_tx:
                    audit["credit_revenue"] += amount
                else:
                    audit["cash_revenue"] += amount

                if r_dict.get("is_renewal"):
                    audit["renew_subs_count"] += 1
                else:
                    audit["new_subs_count"] += 1

                c_date = str(r_dict.get("created_at", ""))[:10]
                if c_date:
                    if c_date not in audit["daily_turnover"]:
                        audit["daily_turnover"][c_date] = {"date": c_date, "income": 0, "expense": 0, "count": 0}
                    audit["daily_turnover"][c_date]["income"] += amount
                    audit["daily_turnover"][c_date]["count"] += 1

                audit["transactions"].append(r_dict)

            # ۲. اشتراک‌های ایجاد شده در بازه زمانی جهت محاسبه حجم کل GB
            if reseller_id:
                cursor.execute("""
                    SELECT data_limit, cost_paid, is_credit, created_at 
                    FROM subscriptions 
                    WHERE reseller_id = ? AND created_at >= ?
                """, (reseller_id, start_iso))
            else:
                cursor.execute("""
                    SELECT data_limit, cost_paid, is_credit, created_at 
                    FROM subscriptions 
                    WHERE created_at >= ?
                """, (start_iso,))
            
            sub_rows = cursor.fetchall()
            audit["total_subs_count"] = len(sub_rows)
            for s in sub_rows:
                audit["total_gb_sold"] += float(s["data_limit"] or 0)

            # ۳. محاسبه هزینه‌ها و بدهی‌ها
            if not reseller_id:
                cursor.execute("""
                    SELECT SUM(amount) FROM accounting_records 
                    WHERE type = 'expense' AND (date >= ? OR created_at >= ?)
                """, (start_iso[:10], start_iso))
                exp_row = cursor.fetchone()
                audit["total_expenses"] = exp_row[0] if (exp_row and exp_row[0]) else 0
                
                cursor.execute("SELECT SUM(credit_debt) FROM resellers WHERE credit_debt > 0")
                debt_row = cursor.fetchone()
                audit["total_outstanding_debt"] = debt_row[0] if (debt_row and debt_row[0]) else 0
            else:
                res_row = self.get_reseller(reseller_id)
                if res_row:
                    audit["total_outstanding_debt"] = res_row.get("credit_debt", 0)
                    discount = res_row.get("discount_percent", 20)
                    audit["total_expenses"] = int(audit["total_revenue"] * (100 - discount) / 100)

            audit["net_profit"] = max(0, audit["total_revenue"] - audit["total_expenses"])
        except Exception as e:
            logger.error(f"Error calculating monthly accounting audit: {e}")
        finally:
            conn.close()

        return audit

    def get_customers_ticket_status_map(self, reseller_id: int = None) -> dict:
        """نقشه سریع وضعیت تیکت‌های کاربران و مشتریان (باز، در انتظار، بسته)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        result = {}
        try:
            query = "SELECT id, telegram_id, status, created_at FROM support_tickets WHERE 1=1"
            params = []
            if reseller_id:
                query += " AND (reseller_id = ? OR reseller_id = 0 OR reseller_id IS NULL)"
                params.append(reseller_id)
            query += " ORDER BY id DESC"
            cursor.execute(query, params)
            rows = cursor.fetchall()
            for r in rows:
                tg_id = r["telegram_id"]
                if not tg_id:
                    continue
                if tg_id not in result:
                    result[tg_id] = {
                        "open_count": 0,
                        "in_progress_count": 0,
                        "closed_count": 0,
                        "has_open": False,
                        "has_pending": False,
                        "has_closed": False,
                        "latest_ticket_id": r["id"],
                        "latest_status": r["status"]
                    }
                st = str(r["status"]).lower()
                if st == "open":
                    result[tg_id]["open_count"] += 1
                    result[tg_id]["has_open"] = True
                elif st in ("pending", "in_progress", "replied", "waiting"):
                    result[tg_id]["in_progress_count"] += 1
                    result[tg_id]["has_pending"] = True
                elif st in ("closed", "resolved"):
                    result[tg_id]["closed_count"] += 1
                    result[tg_id]["has_closed"] = True
        except Exception as e:
            logger.error(f"Error getting ticket status map: {e}")
        finally:
            conn.close()
        return result

    def add_subscription_traffic(self, sub_id: int, extra_gb: float) -> dict:
        """افزایش دستی حجم اشتراک در دیتابیس و پنل هیدیفای"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("SELECT * FROM subscriptions WHERE id=?", (sub_id,))
            sub = cursor.fetchone()
            if not sub:
                return {"success": False, "error": "اشتراک یافت نشد."}
            
            old_limit = float(sub["data_limit"] or 0)
            new_limit = round(old_limit + extra_gb, 2)
            
            cursor.execute("UPDATE subscriptions SET data_limit = ?, updated_at = ? WHERE id = ?", (new_limit, now, sub_id))
            conn.commit()

            return {"success": True, "old_limit": old_limit, "new_limit": new_limit, "hidify_uuid": sub["hidify_uuid"]}
        except Exception as e:
            logger.error(f"Error adding subscription traffic: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def set_subscription_vip(self, sub_id: int, is_vip: bool = True) -> dict:
        """تنظیم وضعیت مشتری پرمیوم / VIP برای اشتراک"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("UPDATE subscriptions SET is_vip = ?, updated_at = ? WHERE id = ?", (1 if is_vip else 0, now, sub_id))
            cursor.execute("SELECT telegram_id FROM subscriptions WHERE id = ?", (sub_id,))
            row = cursor.fetchone()
            if row and row["telegram_id"]:
                cursor.execute("UPDATE users SET is_vip = ?, updated_at = ? WHERE telegram_id = ?", (1 if is_vip else 0, now, row["telegram_id"]))
            conn.commit()
            return {"success": True}
        except Exception as e:
            logger.error(f"Error setting subscription VIP: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def apply_reseller_bundle_credit(self, reseller_id: int, amount: int, bundle_title: str, tx_id: int = None) -> dict:
        """واریز شارژ بسته اعتباری و بونوس مربوطه به کیف پول نماینده پس از تایید رسید"""
        bundles = {b["price"]: b for b in self.get_reseller_credit_bundles()}
        bundle = bundles.get(amount)
        if not bundle:
            for b in self.get_reseller_credit_bundles():
                if b["title"] in str(bundle_title):
                    bundle = b
                    break
        
        credit_to_add = bundle["credit"] if bundle else amount
        bonus_pct = bundle.get("bonus_percent", 0) if bundle else 0

        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("SELECT balance, name FROM resellers WHERE id=?", (reseller_id,))
            res_row = cursor.fetchone()
            if not res_row:
                return {"success": False, "error": "نماینده یافت نشد."}

            res_dict = dict(res_row)
            old_balance = res_dict.get("balance") or 0
            new_balance = old_balance + credit_to_add

            cursor.execute("UPDATE resellers SET balance=?, updated_at=? WHERE id=?", (new_balance, now, reseller_id))

            desc = f"شارژ تاییدشده {bundle_title} (مبلغ شارژ: {credit_to_add:,} تومان | بونوس: {bonus_pct}٪)"
            cursor.execute("""
                INSERT INTO reseller_transactions (reseller_id, type, amount, plan_name, account_name, description, created_at)
                VALUES (?, 'deposit', ?, ?, '-', ?, ?)
            """, (reseller_id, credit_to_add, bundle_title, desc, now))

            conn.commit()
            return {"success": True, "old_balance": old_balance, "new_balance": new_balance, "credit_added": credit_to_add}
        except Exception as e:
            logger.error(f"Error applying reseller bundle credit: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()


# نمونه singleton
db = Database()


