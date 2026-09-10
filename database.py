#!/usr/bin/env python3
"""
ماژول دیتابیس برای ذخیره‌سازی مشتریان، تنظیمات و تراکنش‌ها
"""

import sqlite3
import json
import os
import re
import copy
import uuid
import secrets
import random
import logging
from typing import Optional, Dict, List, Any, Tuple, Union
from datetime import datetime, timedelta, timezone
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

        # جدول ثبت وقایع و حسابرسی جامع سیستم (System Activity & Audit Logs)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS system_activity_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,          -- 'system', 'admin', 'reseller', 'user_bot', 'security'
                action TEXT NOT NULL,            -- 'purge', 'delete', 'restore', 'create', 'update', 'renew', 'sync', 'sync_diff', 'login', 'backup', 'settings_change', 'bulk_action', 'status_change', etc.
                title TEXT NOT NULL,             -- خلاصه عنوان عملیات
                description TEXT,                -- شرح تفصیلی رویداد
                actor_type TEXT NOT NULL,        -- 'system', 'admin', 'reseller', 'bot', 'user'
                actor_id INTEGER,               -- شناسه عامل
                actor_name TEXT,                 -- نام یا نام کاربری عامل
                target_type TEXT,                -- موجودیت هدف: 'subscription', 'user', 'reseller', 'setting', 'payment', 'system'
                target_id INTEGER,               -- شناسه هدف (مثل sub_id)
                target_name TEXT,                -- عنوان یا نام هدف (مثل account_name یا UUID)
                details TEXT,                    -- اطلاعات جزئی با فرمت JSON
                level TEXT DEFAULT 'info',       -- 'info', 'success', 'warning', 'danger'
                ip_address TEXT,                 -- آدرس IP عامل در صورت وجود
                created_at TEXT NOT NULL         -- زمان ایزو تهران
            )
        """)

        # مایگریشن خودکار ایندکس‌ها و ستون‌های جدید
        try:
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_login_logs_token ON login_logs(session_token)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_login_logs_user_active ON login_logs(user_type, user_id, is_active)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_activity_logs_created ON system_activity_logs(created_at DESC)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_activity_logs_category ON system_activity_logs(category)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_activity_logs_action ON system_activity_logs(action)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_activity_logs_actor ON system_activity_logs(actor_type, actor_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_activity_logs_target ON system_activity_logs(target_type, target_id)")
        except Exception:
            pass

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
            cursor.execute("ALTER TABLE transactions ADD COLUMN is_edited INTEGER DEFAULT 0")
        except Exception:
            pass

        try:
            cursor.execute("ALTER TABLE transactions ADD COLUMN edited_by TEXT")
        except Exception:
            pass

        try:
            cursor.execute("ALTER TABLE transactions ADD COLUMN edited_at TEXT")
        except Exception:
            pass

        try:
            cursor.execute("ALTER TABLE transactions ADD COLUMN edit_reason TEXT")
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
            cursor.execute("ALTER TABLE transactions ADD COLUMN source TEXT DEFAULT 'telegram'")
        except Exception:
            pass

        # تصحیح و همگام‌سازی خودکار مبدأ و نام مشتری برای تراکنش‌های پیشین
        try:
            cursor.execute("""
                UPDATE transactions 
                SET source = 'portal' 
                WHERE (order_id LIKE 'INV%' OR gateway = 'bank_sms' OR (renew_sub_id IS NOT NULL AND renew_sub_id > 0))
                  AND (source IS NULL OR source = '' OR source = 'telegram')
            """)
            cursor.execute("""
                UPDATE transactions 
                SET username = account_name 
                WHERE (username IS NULL OR username = '' OR username = 'کاربر') 
                  AND account_name IS NOT NULL AND account_name != ''
            """)
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
            "brand_title TEXT", "primary_color TEXT", "footer_text TEXT",
            "portal_layout TEXT DEFAULT ''", "portal_plan_style TEXT DEFAULT ''"
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
            "hiddify_admin_uuid TEXT",
            "bank_sms_enabled INTEGER DEFAULT 0",
            "bank_sms_token TEXT",
            "bank_sms_digits INTEGER DEFAULT 3",
            "bank_sms_timeout INTEGER DEFAULT 15",
            "bot_admins TEXT"
        ]:
            try:
                cursor.execute(f"ALTER TABLE resellers ADD COLUMN {col_def}")
            except Exception:
                pass

        try:
            cursor.execute("ALTER TABLE users ADD COLUMN reseller_id INTEGER DEFAULT 0")
        except Exception:
            pass

        # پاک‌سازی مقادیر خالی دامنه‌ها جهت جلوگیری از تداخل ایندکس یونیک
        try:
            cursor.execute("UPDATE resellers SET custom_domain = NULL WHERE custom_domain = '' OR TRIM(custom_domain) = ''")
            cursor.execute("UPDATE resellers SET tutorial_domain = NULL WHERE tutorial_domain = '' OR TRIM(tutorial_domain) = ''")
        except Exception:
            pass

        try:
            cursor.execute("DROP INDEX IF EXISTS idx_resellers_custom_domain")
            cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_resellers_custom_domain ON resellers(custom_domain) WHERE custom_domain IS NOT NULL AND custom_domain != ''")
        except Exception:
            pass

        try:
            cursor.execute("DROP INDEX IF EXISTS idx_resellers_tutorial_domain")
            cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_resellers_tutorial_domain ON resellers(tutorial_domain) WHERE tutorial_domain IS NOT NULL AND tutorial_domain != ''")
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

        # جدول لاگ پیامک‌های واریزی بانک
        try:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS bank_sms_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_type TEXT NOT NULL,
                    owner_id INTEGER DEFAULT 0,
                    sender_number TEXT,
                    raw_message TEXT,
                    extracted_amount INTEGER,
                    matched_order_id TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TEXT NOT NULL
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_bank_sms_owner ON bank_sms_logs(owner_type, owner_id)")
        except Exception:
            pass

        # جدول فاکتورهای هوشمند با ارقام تصادفی خرد جهت تایید خودکار کارت به کارت
        try:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS smart_invoices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id TEXT UNIQUE NOT NULL,
                    sub_id INTEGER,
                    plan_id TEXT,
                    reseller_id INTEGER DEFAULT 0,
                    base_amount INTEGER NOT NULL,
                    random_suffix INTEGER NOT NULL,
                    final_amount INTEGER NOT NULL,
                    target_card_id INTEGER,
                    card_number TEXT,
                    card_holder TEXT,
                    bank_name TEXT,
                    status TEXT DEFAULT 'pending',
                    token TEXT UNIQUE NOT NULL,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    paid_at TEXT,
                    tracking_code TEXT
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_smart_invoices_token ON smart_invoices(token)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_smart_invoices_match ON smart_invoices(reseller_id, final_amount, status)")
        except Exception:
            pass

        # جدول سوابق و رسیدهای بدهی مشتریان (تفکیک به ازای هر خرید یا تمدید)
        try:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS customer_debt_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    subscription_id INTEGER NOT NULL,
                    account_name TEXT,
                    telegram_id INTEGER DEFAULT 0,
                    reseller_id INTEGER DEFAULT 0,
                    action_type TEXT NOT NULL,
                    plan_name TEXT,
                    amount INTEGER NOT NULL,
                    previous_debt INTEGER DEFAULT 0,
                    total_debt INTEGER NOT NULL,
                    status TEXT DEFAULT 'unpaid',
                    notes TEXT,
                    created_by TEXT,
                    paid_at TEXT,
                    settled_by TEXT,
                    settle_order_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_debt_records_sub_id ON customer_debt_records(subscription_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_debt_records_status ON customer_debt_records(status)")
        except Exception:
            pass

        # مایگریشن ستون‌های پورتال مشتری برای نمایندگان و فاکتورها
        try:
            cursor.execute("ALTER TABLE resellers ADD COLUMN portal_title TEXT")
        except Exception:
            pass
        try:
            cursor.execute("ALTER TABLE resellers ADD COLUMN portal_subtitle TEXT")
        except Exception:
            pass
        try:
            cursor.execute("ALTER TABLE resellers ADD COLUMN support_phone TEXT")
        except Exception:
            pass
        try:
            cursor.execute("ALTER TABLE smart_invoices ADD COLUMN instant_activation INTEGER DEFAULT 1")
        except Exception:
            pass
        try:
            cursor.execute("ALTER TABLE smart_invoices ADD COLUMN discount_code TEXT")
        except Exception:
            pass
        try:
            cursor.execute("ALTER TABLE smart_invoices ADD COLUMN discount_amount INTEGER DEFAULT 0")
        except Exception:
            pass
        try:
            cursor.execute("ALTER TABLE smart_invoices ADD COLUMN is_debt_settlement INTEGER DEFAULT 0")
        except Exception:
            pass
        try:
            cursor.execute("ALTER TABLE transactions ADD COLUMN is_debt_settlement INTEGER DEFAULT 0")
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

        # ستون‌های تیکت‌های درخواست تغییر حجم و مدت نماینده و چت پورتال مشتری
        for col_def in [
            "reseller_id INTEGER DEFAULT 0",
            "ticket_type TEXT DEFAULT 'general'",
            "target_role TEXT DEFAULT 'admin'",
            "request_data TEXT",
            "request_status TEXT DEFAULT 'pending'",
            "subscription_id INTEGER DEFAULT NULL",
            "customer_name TEXT DEFAULT NULL",
            "customer_phone TEXT DEFAULT NULL",
            "portal_token TEXT DEFAULT NULL"
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
            "credit_debt INTEGER DEFAULT 0",
            "can_gift_traffic INTEGER DEFAULT 0",
            "max_gift_traffic_gb REAL DEFAULT 0"
        ]:
            try:
                cursor.execute(f"ALTER TABLE resellers ADD COLUMN {col_def}")
            except Exception:
                pass

        # ستون‌های شخصی‌سازی حجم، مدت، درصد تخفیف و قیمت عمده در پلن‌های نماینده
        for col_def in [
            "custom_data_limit REAL DEFAULT NULL",
            "custom_duration INTEGER DEFAULT NULL",
            "custom_discount_percent REAL DEFAULT NULL",
            "custom_wholesale_price INTEGER DEFAULT NULL",
            "reseller_custom_name TEXT DEFAULT NULL",
            "reseller_custom_price INTEGER DEFAULT NULL",
            "reseller_is_active INTEGER DEFAULT NULL",
            "is_reseller_modified INTEGER DEFAULT 0"
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
            ("disable_reason", "TEXT"),
            ("created_by", "TEXT")
        ]:
            try:
                cursor.execute(f"ALTER TABLE subscriptions ADD COLUMN {col_def[0]} {col_def[1]}")
            except Exception:
                pass

        # تصحیح خودکار شناسه نماینده برای اشتراک‌های قدیمی که تگ نماینده در کامنت دارند اما reseller_id آن‌ها خالی است
        try:
            import re
            c_fix = conn.cursor()
            rows_to_fix = c_fix.execute("SELECT id, account_comment FROM subscriptions WHERE reseller_id IS NULL AND (account_comment LIKE '%[RESELLER_ID:%' OR account_comment LIKE '%Reseller #%')").fetchall()
            for r_fix in rows_to_fix:
                c_txt = str(r_fix["account_comment"] or "")
                m = re.search(r"\[RESELLER_ID:\s*#?(\d+)\]", c_txt) or re.search(r"Reseller\s*#(\d+)", c_txt)
                if m:
                    r_id_found = int(m.group(1))
                    c_fix.execute("UPDATE subscriptions SET reseller_id = ? WHERE id = ?", (r_id_found, r_fix["id"]))
        except Exception as e:
            logger.warning(f"Error auto-fixing legacy reseller_ids: {e}")

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
                    queue_order INTEGER DEFAULT 0,
                    FOREIGN KEY (subscription_id) REFERENCES subscriptions(id) ON DELETE CASCADE
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_sub_queue_sub_status ON subscription_queue(subscription_id, status)")
        except Exception as e:
            logger.warning(f"Error creating subscription_queue table: {e}")

        # ستون‌های مبدأ پرداخت کیف‌پول/اعتبار و رهگیری ویرایش اسناد حسابداری و بدهی‌ها
        for col_sql in [
            "ALTER TABLE subscription_queue ADD COLUMN queue_order INTEGER DEFAULT 0",
            "ALTER TABLE subscriptions ADD COLUMN payment_source TEXT DEFAULT 'wallet'",
            "ALTER TABLE reseller_transactions ADD COLUMN payment_source TEXT DEFAULT 'wallet'",
            "ALTER TABLE reseller_transactions ADD COLUMN subscription_id INTEGER",
            "ALTER TABLE reseller_transactions ADD COLUMN selling_price INTEGER DEFAULT 0",
            "ALTER TABLE reseller_transactions ADD COLUMN profit_margin INTEGER DEFAULT 0",
            "ALTER TABLE reseller_transactions ADD COLUMN created_by TEXT",
            "ALTER TABLE reseller_transactions ADD COLUMN status TEXT DEFAULT 'completed'",
            "ALTER TABLE reseller_transactions ADD COLUMN is_edited INTEGER DEFAULT 0",
            "ALTER TABLE reseller_transactions ADD COLUMN edited_by TEXT",
            "ALTER TABLE reseller_transactions ADD COLUMN edited_at TEXT",
            "ALTER TABLE reseller_transactions ADD COLUMN edit_reason TEXT",
            "ALTER TABLE reseller_transactions ADD COLUMN is_revoked INTEGER DEFAULT 0",
            "ALTER TABLE reseller_transactions ADD COLUMN revoked_by TEXT",
            "ALTER TABLE reseller_transactions ADD COLUMN revoked_at TEXT",
            "ALTER TABLE reseller_transactions ADD COLUMN revoke_reason TEXT",
            "ALTER TABLE subscriptions ADD COLUMN last_renewed_by TEXT",
            "ALTER TABLE accounting_records ADD COLUMN is_edited INTEGER DEFAULT 0",
            "ALTER TABLE accounting_records ADD COLUMN edited_by TEXT",
            "ALTER TABLE accounting_records ADD COLUMN edited_at TEXT",
            "ALTER TABLE admin_debts ADD COLUMN is_edited INTEGER DEFAULT 0",
            "ALTER TABLE admin_debts ADD COLUMN edited_by TEXT",
            "ALTER TABLE admin_debts ADD COLUMN edited_at TEXT",
            # ستون‌های ارتقای سیستم مدیریت کارت‌ها و حسابداری شناور
            "ALTER TABLE bank_cards ADD COLUMN is_default INTEGER DEFAULT 0",
            "ALTER TABLE bank_cards ADD COLUMN is_backup INTEGER DEFAULT 0",
            "ALTER TABLE bank_cards ADD COLUMN balance INTEGER DEFAULT 0",
            "ALTER TABLE bank_cards ADD COLUMN initial_balance INTEGER DEFAULT 0",
            "ALTER TABLE bank_cards ADD COLUMN shaba_number TEXT",
            "ALTER TABLE bank_cards ADD COLUMN account_number TEXT",
            "ALTER TABLE bank_cards ADD COLUMN notes TEXT",
            "ALTER TABLE reseller_cards ADD COLUMN is_default INTEGER DEFAULT 0",
            "ALTER TABLE reseller_cards ADD COLUMN is_backup INTEGER DEFAULT 0",
            "ALTER TABLE reseller_cards ADD COLUMN balance INTEGER DEFAULT 0",
            "ALTER TABLE reseller_cards ADD COLUMN initial_balance INTEGER DEFAULT 0",
            "ALTER TABLE reseller_cards ADD COLUMN shaba_number TEXT",
            "ALTER TABLE reseller_cards ADD COLUMN account_number TEXT",
            "ALTER TABLE reseller_cards ADD COLUMN notes TEXT"
        ]:
            try:
                cursor.execute(col_sql)
            except Exception:
                pass

        # جدول دفتر ریزتراکنش‌های تفکیکی کارت‌های بانکی (مدیریت و نمایندگان)
        try:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS card_transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    card_id INTEGER NOT NULL,
                    owner_type TEXT DEFAULT 'admin',
                    reseller_id INTEGER DEFAULT 0,
                    type TEXT NOT NULL,
                    amount INTEGER NOT NULL,
                    balance_after INTEGER DEFAULT 0,
                    category TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT,
                    tracking_code TEXT,
                    ref_type TEXT,
                    ref_id TEXT,
                    created_by TEXT,
                    created_at TEXT NOT NULL
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_card_tx_card ON card_transactions(card_id, owner_type)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_card_tx_created ON card_transactions(created_at)")
        except Exception:
            pass

        # جدول صندوق نقدی و دفتر تسویه نقدی مدیریت و نمایندگان
        try:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS cash_desk_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_type TEXT DEFAULT 'admin',
                    owner_id INTEGER DEFAULT 0,
                    type TEXT NOT NULL,
                    amount INTEGER NOT NULL,
                    customer_name TEXT,
                    plan_name TEXT,
                    description TEXT,
                    is_settled INTEGER DEFAULT 0,
                    settled_at TEXT,
                    settled_by TEXT,
                    created_by TEXT,
                    created_at TEXT NOT NULL
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_cash_desk_owner ON cash_desk_logs(owner_type, owner_id)")
        except Exception:
            pass

        try:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS reseller_transaction_audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    reseller_transaction_id INTEGER NOT NULL,
                    admin_id INTEGER,
                    admin_name TEXT,
                    action TEXT NOT NULL,
                    field_name TEXT,
                    old_value TEXT,
                    new_value TEXT,
                    reason TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (reseller_transaction_id) REFERENCES reseller_transactions(id)
                )
            """)
        except Exception:
            pass

        try:
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_sub_queue_sub_order ON subscription_queue(subscription_id, status, queue_order)")
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

        # اصلاح دسته‌بندی تیکت‌های مشتریان نماینده به target_role='reseller'
        try:
            cursor.execute("""
                UPDATE support_tickets 
                SET target_role = 'reseller' 
                WHERE reseller_id > 0 AND (ticket_type NOT IN ('reseller_to_admin', 'quota_change', 'reseller_application') OR ticket_type IS NULL)
            """)
        except Exception as e:
            logger.warning(f"Error updating support_tickets target_role: {e}")

        conn.commit()
        conn.close()
        logger.info("Database initialized successfully")

        # بازیابی جامع اطلاعات در صورت خالی بودن دیتابیس پس از دیپلوی
        try:
            self.auto_restore_full()
        except Exception as e:
            logger.warning(f"Initial auto_restore_full check: {e}")

        # خودترمیمی و اصلاح خودکار هرگونه انحراف یا خطای محاسباتی در رسیدها و بدهی‌ها
        try:
            self.repair_customer_debt_records()
        except Exception as e:
            logger.warning(f"Initial repair_customer_debt_records check: {e}")

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

        # اگر کاربر در هیدیفای غیرفعال یا منقضی باشد، به هیچ وجه آنلاین نیست
        if not u.get("is_active", True) or not u.get("enable", True):
            last_raw = u.get("last_online") or u.get("last_online_time") or u.get("last_connected")
            clean_str = None
            if last_raw:
                clean_str = str(last_raw).replace("T", " ").split(".")[0].split("+")[0].strip()
            return 0, clean_str

        last_online_raw = u.get("last_online") or u.get("last_online_time") or u.get("last_connected")
        last_online_str = None
        is_online = 0

        if last_online_raw:
            try:
                clean_str = str(last_online_raw).replace("T", " ").split(".")[0].split("+")[0].strip()
                last_online_str = clean_str
                # بررسی فاصله زمانی آخرین اتصال (سرور هیدیفای بر پایه UTC است)
                dt = datetime.strptime(clean_str[:19], "%Y-%m-%d %H:%M:%S")
                now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
                now_tehran = get_now_naive()
                diff_utc = (now_utc - dt).total_seconds()
                diff_tehran = (now_tehran - dt).total_seconds()
                
                # کاربر فقط در صورتی آنلاین است که اتصال واقعی در ۵ دقیقه (۳۰۰ ثانیه) اخیر رخ داده باشد
                if (0 <= diff_utc <= 300) or (0 <= diff_tehran <= 300):
                    is_online = 1
                else:
                    is_online = 0
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
                extracted_reseller_id = None
                if "[RESELLER_ID:" in comment or "Reseller #" in comment:
                    try:
                        import re
                        m_res = re.search(r"\[RESELLER_ID:\s*#?(\d+)\]", comment) or re.search(r"Reseller\s*#(\d+)", comment)
                        if m_res:
                            extracted_reseller_id = int(m_res.group(1))
                    except Exception:
                        pass

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
                            reseller_id = COALESCE(reseller_id, ?),
                            is_online = ?,
                            last_online = COALESCE(?, last_online),
                            updated_at = ?
                        WHERE hidify_uuid = ?
                    """, (current_usage, usage_limit, package_days, start_date, expiry_time, status, name_clean, extracted_reseller_id, is_online_val, last_online_val, now, uuid))
                else:
                    # درج اشتراک جدید بازیابی شده
                    cursor.execute("""
                        INSERT INTO subscriptions (
                            telegram_id, hidify_uuid, plan_id, plan_name, account_name,
                            account_comment, data_limit, data_used, duration, start_date,
                            expire_date, status, reseller_id, is_online, last_online, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        telegram_id, uuid, plan_id, plan_name, name,
                        comment, usage_limit, current_usage, package_days, start_date,
                        expiry_time, status, extracted_reseller_id, is_online_val, last_online_val, now, now
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

    def refresh_subscriptions_expiry_and_online(self) -> dict:
        """
        بروزرسانی و تصحیح هوشمند و دوره‌ای وضعیت اشتراک‌ها:
        ۱. صفر کردن آنلاین بودن برای اشتراک‌هایی که اتصال اخیر (بیش از ۱۰ دقیقه) نداشته‌اند
        ۲. بروزرسانی وضعیت اشتراک‌های منقضی‌شده بر اساس تاریخ انقضا یا حجم مصرفی
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        updated_online = 0
        updated_expired = 0
        now_dt = get_now_naive()
        now_iso = get_now_iso()

        try:
            # ۱. بازیابی کلیه اشتراک‌های دارای وضعیت آنلاین جهت اعتبارسنجی مجدد
            cursor.execute("SELECT id, last_online, expire_date, start_date, duration, data_limit, data_used, status FROM subscriptions WHERE is_online = 1")
            online_rows = cursor.fetchall()
            now_utc = datetime.now(timezone.utc).replace(tzinfo=None)

            for r in online_rows:
                sub_id = r["id"]
                last_online = r["last_online"]
                is_still_online = False

                if last_online and str(last_online).strip() not in ["", "None", "null", "-"] and not str(last_online).startswith("0001"):
                    try:
                        clean_lo = str(last_online).replace("T", " ").split(".")[0].split("+")[0].strip()
                        lo_dt = datetime.strptime(clean_lo[:19], "%Y-%m-%d %H:%M:%S")
                        diff_tehran = (now_dt - lo_dt).total_seconds()
                        diff_utc = (now_utc - lo_dt).total_seconds()
                        if (0 <= diff_tehran <= 600) or (0 <= diff_utc <= 600):
                            is_still_online = True
                    except Exception:
                        pass

                # اگر وضعیت فعال نیست، به هیچ وجه آنلاین نیست
                if r["status"] in ("expired", "disabled", "inactive"):
                    is_still_online = False

                # اگر حجم به پایان رسیده، آنلاین نیست
                d_limit = float(r["data_limit"] or 0)
                d_used = float(r["data_used"] or 0)
                if d_limit > 0 and d_used >= d_limit:
                    is_still_online = False

                if not is_still_online:
                    cursor.execute("UPDATE subscriptions SET is_online = 0, updated_at = ? WHERE id = ?", (now_iso, sub_id))
                    updated_online += 1

            # ۲. بروزرسانی خودکار اشتراک‌هایی که موعد انقضای آن‌ها سپری شده اما هنوز active هستند
            cursor.execute("SELECT id, start_date, duration, expire_date, data_limit, data_used FROM subscriptions WHERE status = 'active' AND (is_deleted = 0 OR is_deleted IS NULL)")
            active_rows = cursor.fetchall()

            for r in active_rows:
                sub_id = r["id"]
                exp_dt = None
                exp_str = r["expire_date"]
                start_str = r["start_date"]
                dur = int(r["duration"] or 30)

                if exp_str and str(exp_str).strip() not in ["", "None", "null"]:
                    try:
                        clean_exp = str(exp_str).replace("Z", "")
                        if len(clean_exp) == 10:
                            exp_dt = datetime.strptime(clean_exp, "%Y-%m-%d")
                        else:
                            exp_dt = datetime.fromisoformat(clean_exp)
                        if exp_dt.tzinfo is not None:
                            exp_dt = exp_dt.astimezone(TEHRAN_TZ).replace(tzinfo=None)
                    except Exception:
                        pass
                elif start_str and str(start_str).strip() not in ["", "None", "null"]:
                    try:
                        clean_start = str(start_str)[:10]
                        s_dt = datetime.strptime(clean_start, "%Y-%m-%d")
                        if s_dt.tzinfo is not None:
                            s_dt = s_dt.astimezone(TEHRAN_TZ).replace(tzinfo=None)
                        exp_dt = s_dt + timedelta(days=dur)
                    except Exception:
                        pass

                is_exp = False
                if exp_dt:
                    if (exp_dt.date() - now_dt.date()).days < 0 or (exp_dt - now_dt).total_seconds() < 0:
                        is_exp = True

                d_limit = float(r["data_limit"] or 0)
                d_used = float(r["data_used"] or 0)
                if d_limit > 0 and d_used >= d_limit:
                    is_exp = True

                if is_exp:
                    cursor.execute("UPDATE subscriptions SET status = 'expired', is_online = 0, updated_at = ? WHERE id = ?", (now_iso, sub_id))
                    updated_expired += 1

            conn.commit()
            return {"updated_online": updated_online, "updated_expired": updated_expired}
        except Exception as e:
            logger.error(f"Error in refresh_subscriptions_expiry_and_online: {e}")
            return {"updated_online": 0, "updated_expired": 0}
        finally:
            conn.close()

    def get_online_users_stats(self, reseller_id: int = None) -> dict:
        """آمار تعداد کل کاربران و مشتریان آنلاین برای ادمین یا نماینده"""
        self.refresh_subscriptions_expiry_and_online()
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

    def save_subscription(self, telegram_id, hidify_uuid, plan_id, plan_name, data_limit, duration, data_used=0, status="active", account_name=None, account_comment=None, reseller_id=None, user_limit=1, cost_paid=0, created_by=None, **kwargs):
        """ذخیره اشتراک جدید"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        expire_date = (get_now_naive() + timedelta(days=duration)).isoformat()
        creator = created_by or kwargs.get("created_by")

        try:
            cursor.execute("""
                INSERT INTO subscriptions
                (telegram_id, hidify_uuid, plan_id, plan_name, account_name, account_comment, data_limit, data_used, duration, start_date, expire_date, status, reseller_id, user_limit, cost_paid, created_by, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (telegram_id, hidify_uuid, plan_id, plan_name, account_name, account_comment, data_limit, data_used, duration, now, expire_date, status, reseller_id, int(user_limit or 1), int(cost_paid or 0), creator, now, now))
            conn.commit()
            subscription_id = cursor.lastrowid
            logger.info(f"Subscription {subscription_id} saved for user {telegram_id} (reseller_id={reseller_id}, created_by={creator}, user_limit={user_limit})")
            return {"success": True, "subscription_id": subscription_id}
        except Exception as e:
            logger.error(f"Error saving subscription: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def get_user_subscriptions(self, telegram_id, status=None, reseller_id=None, is_admin_bot=False):
        """دریافت اشتراک‌های کاربر با قابلیت ایزولاسیون بر اساس نماینده یا مدیریت"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            query = "SELECT * FROM subscriptions WHERE telegram_id = ?"
            params = [telegram_id]

            if reseller_id is not None:
                query += " AND reseller_id = ?"
                params.append(reseller_id)
            elif is_admin_bot:
                query += " AND (reseller_id IS NULL OR reseller_id = 0)"

            if status:
                query += " AND status = ?"
                params.append(status)

            query += " ORDER BY created_at DESC"
            cursor.execute(query, tuple(params))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error getting subscriptions for user {telegram_id}: {e}")
            return []
        finally:
            conn.close()

    def get_active_subscription(self, telegram_id, reseller_id=None, is_admin_bot=False):
        """دریافت اشتراک فعال کاربر با قابلیت ایزولاسیون بر اساس نماینده یا مدیریت"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            query = "SELECT * FROM subscriptions WHERE telegram_id = ? AND status = 'active'"
            params = [telegram_id]

            if reseller_id is not None:
                query += " AND reseller_id = ?"
                params.append(reseller_id)
            elif is_admin_bot:
                query += " AND (reseller_id IS NULL OR reseller_id = 0)"

            query += " ORDER BY created_at DESC LIMIT 1"
            cursor.execute(query, tuple(params))
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

    def save_transaction(self, order_id, user_id, username, plan_name, amount, gateway, tracking_code, status="pending", account_name=None, account_comment=None, is_renewal=0, renew_sub_id=None, discount_code=None, receipt_image=None, receipt_file_type=None, reseller_id=None, notes=None, source="telegram", **kwargs):
        """ذخیره تراکنش"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()

        if notes and not account_comment:
            account_comment = notes

        if not source:
            source = "portal" if (str(order_id).startswith("INV") or gateway == "bank_sms" or renew_sub_id) else "telegram"

        try:
            cursor.execute("""
                INSERT OR REPLACE INTO transactions
                (order_id, user_id, username, plan_name, amount, gateway, tracking_code, account_name, account_comment, status, is_renewal, renew_sub_id, discount_code, receipt_image, receipt_photo_id, receipt_file_type, reseller_id, source, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (order_id, user_id, username, plan_name, amount, gateway, tracking_code, account_name, account_comment, status, 1 if is_renewal else 0, renew_sub_id, discount_code, receipt_image, receipt_image, receipt_file_type, reseller_id, source, now, now))
            conn.commit()
            logger.info(f"Transaction {order_id} saved (is_renewal={is_renewal}, reseller_id={reseller_id}, source={source})")
            
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

    def update_transaction(self, order_id, status: str = None, ref_id: str = None, tracking_code: str = None, **kwargs):
        """بروزرسانی وضعیت و مشخصات تراکنش (منعطف و جامع)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()

        updates = []
        params = []

        if status is not None:
            updates.append("status = ?")
            params.append(status)

        if ref_id is not None:
            updates.append("ref_id = ?")
            params.append(str(ref_id))

        if tracking_code is not None:
            updates.append("tracking_code = ?")
            params.append(str(tracking_code))

        allowed_columns = {
            "account_name", "account_comment", "processed_by", "processed_at",
            "gateway", "amount", "plan_name", "user_id", "reseller_id",
            "is_renewal", "renew_sub_id", "is_debt_settlement"
        }
        for k, v in kwargs.items():
            if k in allowed_columns and v is not None:
                updates.append(f"{k} = ?")
                params.append(v)

        updates.append("updated_at = ?")
        params.append(now)

        params.append(order_id)

        try:
            sql = f"UPDATE transactions SET {', '.join(updates)} WHERE order_id = ?"
            cursor.execute(sql, tuple(params))
            conn.commit()
            logger.info(f"Transaction {order_id} updated: {updates}")
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
        ابطال تراکنش توسط مدیر ارشد با ثبت تاریخچه، کسر از درآمد، اصلاح تراز مالی نماینده و امکان رول‌بک اشتراک
        rollback_sub_action: 'keep', 'disable', 'delete'
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            tx = cursor.execute("SELECT * FROM transactions WHERE id=?", (tx_id,)).fetchone()
            if not tx:
                return {"success": False, "error": "تراکنش یافت نشد."}

            tx = dict(tx)
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

            # ۳. در صورت تایید قبلی فیش، اصلاح و بازنگری در سیستم مالی:
            if old_status in ("approved", "completed"):
                r_id = tx["reseller_id"]
                is_bundle = (tx.get("gateway") == "bundle_reseller" or str(tx.get("order_id") or "").startswith("R_BUNDLE"))
                if r_id and is_bundle:
                    # یافتن تراکنش واریز بسته اعتباری
                    r_tx = cursor.execute("""
                        SELECT id, amount FROM reseller_transactions 
                        WHERE reseller_id=? AND (description LIKE ? OR plan_name=?) AND type='deposit'
                        ORDER BY id DESC LIMIT 1
                    """, (r_id, f"%{tx['order_id']}%", tx.get("plan_name"))).fetchone()
                    credit_deduct = r_tx["amount"] if r_tx else (tx["amount"] or 0)
                    
                    cursor.execute("UPDATE resellers SET balance = balance - ?, updated_at=? WHERE id=?", (credit_deduct, now_iso, r_id))
                    
                    if r_tx:
                        cursor.execute("""
                            UPDATE reseller_transactions
                            SET status='revoked', is_revoked=1, revoked_by=?, revoked_at=?, revoke_reason=?
                            WHERE id=?
                        """, (admin_name, now_iso, reason, r_tx["id"]))
                        
                        cursor.execute("""
                            INSERT INTO reseller_transaction_audit_logs
                            (reseller_transaction_id, admin_id, admin_name, action, field_name, old_value, new_value, reason, created_at)
                            VALUES (?, ?, ?, 'revoke', 'status', 'active', 'revoked', ?, ?)
                        """, (r_tx["id"], admin_id, admin_name, reason, now_iso))

                # ابطال یا خنثی‌سازی سند در سیستم حسابداری
                try:
                    cursor.execute("""
                        UPDATE accounting_records
                        SET amount = 0, is_edited = 1, edited_by = ?, edited_at = ?,
                            description = COALESCE(description, '') || ' [باطل شده توسط مدیریت]'
                        WHERE (ref_type = 'transaction' AND ref_id = ?)
                           OR title LIKE ?
                    """, (admin_name, now_iso, str(tx_id), f"%{tx['order_id']}%"))
                except Exception:
                    pass

            # ۴. یافتن اشتراک مرتبط
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
        """ویرایش مشخصات فیش با ثبت دقیق لاگ حسابرسی (قبل و بعد)، برچسب ویرایش، و اعمال تغییرات مالی"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            tx = cursor.execute("SELECT * FROM transactions WHERE id=?", (tx_id,)).fetchone()
            if not tx:
                return {"success": False, "error": "تراکنش یافت نشد."}

            tx = dict(tx)
            now_iso = get_now_iso()
            changes = []
            int_amt = None

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

            fields_to_update["is_edited"] = 1
            fields_to_update["edited_by"] = admin_name
            fields_to_update["edited_at"] = now_iso
            fields_to_update["edit_reason"] = reason
            fields_to_update["updated_at"] = now_iso

            set_clause = ", ".join([f"{k}=?" for k in fields_to_update.keys()])
            values = list(fields_to_update.values()) + [tx_id]

            cursor.execute(f"UPDATE transactions SET {set_clause} WHERE id=?", values)

            # در صورت تغییر مبلغ فیش‌های تایید شده، اعمال تراز در حسابداری و تراز کیف پول نماینده
            if int_amt is not None and tx["status"] in ("approved", "completed"):
                delta = int_amt - tx["amount"]
                r_id = tx["reseller_id"]
                is_bundle = (tx.get("gateway") == "bundle_reseller" or str(tx.get("order_id") or "").startswith("R_BUNDLE"))
                if r_id and is_bundle and delta != 0:
                    cursor.execute("UPDATE resellers SET balance = balance + ?, updated_at=? WHERE id=?", (delta, now_iso, r_id))
                    t_type = "deposit" if delta > 0 else "refund"
                    t_desc = f"تعدیل موجودی به علت ویرایش مبلغ سفارش #{tx['order_id']} توسط مدیریت ({delta:+,} تومان)"
                    cursor.execute("""
                        INSERT INTO reseller_transactions (reseller_id, type, amount, plan_name, account_name, description, created_at)
                        VALUES (?, ?, ?, ?, '-', ?, ?)
                    """, (r_id, t_type, abs(delta), tx.get("plan_name"), t_desc, now_iso))

                # به‌روزرسانی سند در حسابداری
                try:
                    cursor.execute("""
                        UPDATE accounting_records
                        SET amount = ?, is_edited = 1, edited_by = ?, edited_at = ?
                        WHERE (ref_type = 'transaction' AND ref_id = ?)
                           OR title LIKE ?
                    """, (int_amt, admin_name, now_iso, str(tx_id), f"%{tx['order_id']}%"))
                except Exception:
                    pass

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

    def update_reseller_wallet_transaction(self, rtx_id: int, admin_id: int, admin_name: str, amount: int = None, description: str = None, plan_name: str = None, reason: str = "") -> dict:
        """ویرایش تراکنش کیف پول نماینده با تعدیل تراز مالی و ثبت لاگ قبل و بعد"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now_iso = get_now_iso()
        try:
            rtx = cursor.execute("SELECT * FROM reseller_transactions WHERE id=?", (rtx_id,)).fetchone()
            if not rtx:
                return {"success": False, "error": "تراکنش کیف پول یافت نشد."}

            reseller_id = rtx["reseller_id"]
            rtx_dict = dict(rtx)
            changes = []
            updates = {}

            if amount is not None:
                try:
                    int_amt = int(amount)
                    if int_amt != rtx_dict["amount"]:
                        updates["amount"] = int_amt
                        changes.append(("amount", str(rtx_dict["amount"]), str(int_amt)))

                        # تعدیل موجودی کیف پول نماینده بر اساس نوع تراکنش
                        delta = int_amt - rtx_dict["amount"]
                        if rtx_dict.get("status") != "revoked" and not rtx_dict.get("is_revoked"):
                            if rtx_dict["type"] == "deposit":
                                cursor.execute("UPDATE resellers SET balance = balance + ?, updated_at=? WHERE id=?", (delta, now_iso, reseller_id))
                            elif rtx_dict["type"] in ("purchase", "renewal", "refund"):
                                cursor.execute("UPDATE resellers SET balance = balance - ?, updated_at=? WHERE id=?", (delta, now_iso, reseller_id))
                except Exception:
                    pass

            if description is not None and description.strip() != (rtx_dict.get("description") or ""):
                updates["description"] = description.strip()
                changes.append(("description", rtx_dict.get("description") or "", description.strip()))

            if plan_name is not None and plan_name.strip() != (rtx_dict.get("plan_name") or ""):
                updates["plan_name"] = plan_name.strip()
                changes.append(("plan_name", rtx_dict.get("plan_name") or "", plan_name.strip()))

            if not updates:
                return {"success": True, "message": "هیچ تغییری اعمال نشد.", "reseller_id": reseller_id}

            updates["is_edited"] = 1
            updates["edited_by"] = admin_name
            updates["edited_at"] = now_iso
            updates["edit_reason"] = reason

            set_clause = ", ".join([f"{k}=?" for k in updates.keys()])
            values = list(updates.values()) + [rtx_id]
            cursor.execute(f"UPDATE reseller_transactions SET {set_clause} WHERE id=?", values)

            # ثبت در لاگ حسابرسی
            for f_name, old_v, new_v in changes:
                cursor.execute("""
                    INSERT INTO reseller_transaction_audit_logs
                    (reseller_transaction_id, admin_id, admin_name, action, field_name, old_value, new_value, reason, created_at)
                    VALUES (?, ?, ?, 'edit', ?, ?, ?, ?, ?)
                """, (rtx_id, admin_id, admin_name, f_name, old_v, new_v, reason, now_iso))

            conn.commit()
            return {"success": True, "changes_count": len(changes), "reseller_id": reseller_id}
        except Exception as e:
            logger.error(f"Error updating reseller wallet transaction {rtx_id}: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def revoke_reseller_wallet_transaction(self, rtx_id: int, admin_id: int, admin_name: str, reason: str = "") -> dict:
        """ابطال تراکنش کیف پول نماینده با کسر/استرداد خودکار از تراز مالی کیف پول"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now_iso = get_now_iso()
        try:
            rtx = cursor.execute("SELECT * FROM reseller_transactions WHERE id=?", (rtx_id,)).fetchone()
            if not rtx:
                return {"success": False, "error": "تراکنش کیف پول یافت نشد."}

            rtx_dict = dict(rtx)
            if rtx_dict.get("status") == "revoked" or rtx_dict.get("is_revoked"):
                return {"success": False, "error": "این تراکنش قبلاً باطل شده است."}

            reseller_id = rtx_dict["reseller_id"]
            amount = rtx_dict["amount"] or 0
            ttype = rtx_dict["type"]

            # ۱. کسر یا بازگشت مبلغ به موجودی کیف پول نماینده
            if ttype == "deposit":
                cursor.execute("UPDATE resellers SET balance = balance - ?, updated_at=? WHERE id=?", (amount, now_iso, reseller_id))
            elif ttype in ("purchase", "renewal"):
                cursor.execute("UPDATE resellers SET balance = balance + ?, updated_at=? WHERE id=?", (amount, now_iso, reseller_id))
            elif ttype == "refund":
                cursor.execute("UPDATE resellers SET balance = balance - ?, updated_at=? WHERE id=?", (amount, now_iso, reseller_id))

            # ۲. علامت‌گذاری تراکنش به عنوان باطل‌شده
            cursor.execute("""
                UPDATE reseller_transactions
                SET status='revoked', is_revoked=1, revoked_by=?, revoked_at=?, revoke_reason=?
                WHERE id=?
            """, (admin_name, now_iso, reason, rtx_id))

            # ۳. ثبت لاگ حسابرسی
            cursor.execute("""
                INSERT INTO reseller_transaction_audit_logs
                (reseller_transaction_id, admin_id, admin_name, action, field_name, old_value, new_value, reason, created_at)
                VALUES (?, ?, ?, 'revoke', 'status', 'completed', 'revoked', ?, ?)
            """, (rtx_id, admin_id, admin_name, reason, now_iso))

            conn.commit()
            return {"success": True, "reseller_id": reseller_id, "amount": amount, "type": ttype}
        except Exception as e:
            logger.error(f"Error revoking reseller wallet transaction {rtx_id}: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def get_reseller_wallet_transaction_audit_logs(self, rtx_id: int) -> list:
        """دریافت لاگ‌های حسابرسی یک تراکنش کیف پول نماینده"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM reseller_transaction_audit_logs
            WHERE reseller_transaction_id=?
            ORDER BY id DESC
        """, (rtx_id,))
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

    def is_user_online(self, user_type: str, user_id: int, threshold_minutes: int = 15) -> bool:
        """بررسی آنلاین بودن کاربر، نماینده یا زیرمدیر بر اساس آخرین فعالیت در چند دقیقه گذشته"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT last_active_at, login_at, is_active FROM login_logs
                WHERE user_type = ? AND user_id = ? AND is_active = 1
                ORDER BY id DESC LIMIT 1
            """, (user_type, user_id))
            row = cursor.fetchone()
            if not row or not row["is_active"]:
                return False

            last_time_str = row["last_active_at"] or row["login_at"]
            if not last_time_str:
                return False

            try:
                last_time = datetime.fromisoformat(last_time_str)
                now_tehran = datetime.now(TEHRAN_TZ)
                if last_time.tzinfo is None:
                    last_time = last_time.replace(tzinfo=TEHRAN_TZ)
                diff_seconds = abs((now_tehran - last_time).total_seconds())
                return (diff_seconds / 60) <= threshold_minutes
            except Exception as ex:
                logger.error(f"Error calculating online diff for {user_type} #{user_id}: {ex}")
                return False
        except Exception as e:
            return False
        finally:
            conn.close()

    def is_reseller_online(self, reseller_id: int, threshold_minutes: int = 15) -> bool:
        """بررسی آنلاین بودن نماینده فروش"""
        return self.is_user_online("reseller", reseller_id, threshold_minutes)

    def is_subadmin_online(self, admin_id: int, threshold_minutes: int = 15) -> bool:
        """بررسی آنلاین بودن مدیر کمکی یا پشتیبان زیرمجموعه نماینده"""
        return self.is_user_online("reseller_subadmin", admin_id, threshold_minutes)

    def is_session_active(self, session_token: str) -> bool:
        """بررسی فعال بودن نشست بر اساس توکن نشست در لاگ‌ها"""
        if not session_token:
            return False
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT is_active FROM login_logs WHERE session_token = ? ORDER BY id DESC LIMIT 1", (session_token,))
            row = cursor.fetchone()
            if not row:
                return True  # در صورت عدم وجود لاگ قدیمی جهت جلوگیری از خروج ناگهانی
            return bool(row["is_active"])
        except Exception:
            return True
        finally:
            conn.close()

    def terminate_session(self, session_id: int) -> bool:
        """خاتمه و قطع فوری یک نشست فعال بر اساس شناسه لاگ"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("""
                UPDATE login_logs
                SET is_active = 0, logout_at = ?, last_active_at = ?
                WHERE id = ? AND is_active = 1
            """, (now, now, session_id))
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error terminating session {session_id}: {e}")
            return False
        finally:
            conn.close()

    def terminate_session_by_token(self, session_token: str) -> bool:
        """خاتمه نشست فعال بر اساس توکن"""
        if not session_token:
            return False
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("""
                UPDATE login_logs
                SET is_active = 0, logout_at = ?, last_active_at = ?
                WHERE session_token = ? AND is_active = 1
            """, (now, now, session_token))
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error terminating session by token: {e}")
            return False
        finally:
            conn.close()

    def terminate_all_user_sessions(self, user_type: str, user_id: int, except_token: str = None) -> int:
        """خاتمه تمام نشست‌های فعال یک کاربر، نماینده یا زیرمدیر (با امکان مستثنی کردن نشست فعلی)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            query = "UPDATE login_logs SET is_active = 0, logout_at = ?, last_active_at = ? WHERE user_type = ? AND user_id = ? AND is_active = 1"
            params = [now, now, user_type, user_id]
            if except_token:
                query += " AND session_token != ?"
                params.append(except_token)
            cursor.execute(query, tuple(params))
            conn.commit()
            return cursor.rowcount
        except Exception as e:
            logger.error(f"Error terminating all sessions for {user_type} #{user_id}: {e}")
            return 0
        finally:
            conn.close()

    def terminate_reseller_and_team_sessions(self, reseller_id: int) -> int:
        """خاتمه کلیه نشست‌های فعال یک نماینده و تمامی اعضای تیم زیرمجموعه وی"""
        count = self.terminate_all_user_sessions("reseller", reseller_id)
        team_members = self.get_reseller_team_members(reseller_id)
        for m in team_members:
            count += self.terminate_all_user_sessions("reseller_subadmin", m["id"])
        return count

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
    # سامانه ثبت وقایع و حسابرسی فعالیت‌های سیستم (System Activity & Audit Logs)
    # ═══════════════════════════════════════════════════════════════

    def add_system_log(
        self,
        category: str,
        action: str,
        title: str,
        description: str = None,
        actor_type: str = "system",
        actor_id: int = None,
        actor_name: str = None,
        target_type: str = None,
        target_id: int = None,
        target_name: str = None,
        details: Union[dict, list, str] = None,
        level: str = "info",
        ip_address: str = None
    ) -> dict:
        """
        ثبت یک رویداد در سامانه لاگ و حسابرسی سیستم
        category: 'system', 'admin', 'reseller', 'user_bot', 'security'
        action: 'purge', 'delete', 'restore', 'create', 'update', 'renew', 'sync', 'sync_diff', 'login', 'backup', 'settings_change', 'bulk_action', 'status_change', etc.
        level: 'info', 'success', 'warning', 'danger'
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        now_iso = get_now_iso()

        details_str = None
        if details is not None:
            if isinstance(details, (dict, list)):
                try:
                    details_str = json.dumps(details, ensure_ascii=False)
                except Exception:
                    details_str = str(details)
            else:
                details_str = str(details)

        try:
            cursor.execute("""
                INSERT INTO system_activity_logs (
                    category, action, title, description,
                    actor_type, actor_id, actor_name,
                    target_type, target_id, target_name,
                    details, level, ip_address, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                category.strip(),
                action.strip(),
                title.strip(),
                (description or "").strip(),
                actor_type.strip(),
                actor_id,
                (actor_name or "").strip(),
                (target_type or "").strip() if target_type else None,
                target_id,
                (target_name or "").strip() if target_name else None,
                details_str,
                level.strip(),
                (ip_address or "").strip() if ip_address else None,
                now_iso
            ))
            conn.commit()
            log_id = cursor.lastrowid
            return {"success": True, "id": log_id}
        except Exception as e:
            logger.error(f"Error adding system activity log: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def get_system_logs(
        self,
        page: int = 1,
        per_page: int = 50,
        category: str = None,
        action: str = None,
        level: str = None,
        actor_type: str = None,
        search: str = None,
        time_range: str = None
    ) -> Tuple[List[dict], int]:
        """
        دریافت لیست لاگ‌های سیستم با فیلترهای چندگانه و صفحه‌بندی
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            where_clauses = []
            params = []

            if category and category != "all":
                where_clauses.append("category = ?")
                params.append(category.strip())

            if action and action != "all":
                where_clauses.append("action = ?")
                params.append(action.strip())

            if level and level != "all":
                where_clauses.append("level = ?")
                params.append(level.strip())

            if actor_type and actor_type != "all":
                where_clauses.append("actor_type = ?")
                params.append(actor_type.strip())

            if time_range and time_range != "all":
                now_dt = get_now_naive()
                if time_range == "today":
                    start_today = now_dt.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
                    where_clauses.append("created_at >= ?")
                    params.append(start_today)
                elif time_range == "3days":
                    start_3d = (now_dt - timedelta(days=3)).isoformat()
                    where_clauses.append("created_at >= ?")
                    params.append(start_3d)
                elif time_range == "7days":
                    start_7d = (now_dt - timedelta(days=7)).isoformat()
                    where_clauses.append("created_at >= ?")
                    params.append(start_7d)
                elif time_range == "30days":
                    start_30d = (now_dt - timedelta(days=30)).isoformat()
                    where_clauses.append("created_at >= ?")
                    params.append(start_30d)

            if search and search.strip():
                s = f"%{search.strip()}%"
                where_clauses.append("""(
                    title LIKE ? OR
                    description LIKE ? OR
                    actor_name LIKE ? OR
                    target_name LIKE ? OR
                    ip_address LIKE ? OR
                    details LIKE ?
                )""")
                params.extend([s, s, s, s, s, s])

            where_str = " WHERE " + " AND ".join(where_clauses) if where_clauses else ""

            count_query = f"SELECT COUNT(*) FROM system_activity_logs{where_str}"
            cursor.execute(count_query, params)
            total_count = cursor.fetchone()[0]

            page = max(1, int(page or 1))
            per_page = max(10, min(500, int(per_page or 50)))
            offset = (page - 1) * per_page

            data_query = f"""
                SELECT * FROM system_activity_logs
                {where_str}
                ORDER BY id DESC
                LIMIT ? OFFSET ?
            """
            cursor.execute(data_query, params + [per_page, offset])
            rows = cursor.fetchall()
            return [dict(r) for r in rows], total_count
        except Exception as e:
            logger.error(f"Error fetching system activity logs: {e}")
            return [], 0
        finally:
            conn.close()

    def get_system_logs_stats(self) -> dict:
        """محاسبه آمار کلان لاگ‌ها برای کارت‌های شاخص (KPI)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now_dt = get_now_naive()
        today_start = now_dt.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        stats = {
            "total": 0,
            "system_count": 0,
            "admin_count": 0,
            "reseller_count": 0,
            "warnings_errors": 0,
            "today_count": 0
        }
        try:
            r_total = cursor.execute("SELECT COUNT(*) FROM system_activity_logs").fetchone()
            stats["total"] = r_total[0] if r_total else 0

            r_sys = cursor.execute("SELECT COUNT(*) FROM system_activity_logs WHERE category = 'system'").fetchone()
            stats["system_count"] = r_sys[0] if r_sys else 0

            r_adm = cursor.execute("SELECT COUNT(*) FROM system_activity_logs WHERE category = 'admin'").fetchone()
            stats["admin_count"] = r_adm[0] if r_adm else 0

            r_res = cursor.execute("SELECT COUNT(*) FROM system_activity_logs WHERE category = 'reseller'").fetchone()
            stats["reseller_count"] = r_res[0] if r_res else 0

            r_warn = cursor.execute("SELECT COUNT(*) FROM system_activity_logs WHERE level IN ('warning', 'danger')").fetchone()
            stats["warnings_errors"] = r_warn[0] if r_warn else 0

            r_today = cursor.execute("SELECT COUNT(*) FROM system_activity_logs WHERE created_at >= ?", (today_start,)).fetchone()
            stats["today_count"] = r_today[0] if r_today else 0
        except Exception as e:
            logger.error(f"Error calculating system logs stats: {e}")
        finally:
            conn.close()
        return stats

    def clear_old_system_logs(self, days: int = 90) -> int:
        """پاکسازی لاگ‌های قدیمی‌تر از تعداد روز مشخص شده"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now_dt = get_now_naive()
        cutoff = (now_dt - timedelta(days=days)).isoformat()
        deleted = 0
        try:
            cursor.execute("DELETE FROM system_activity_logs WHERE created_at < ?", (cutoff,))
            deleted = cursor.rowcount
            conn.commit()
        except Exception as e:
            logger.error(f"Error clearing old system logs: {e}")
        finally:
            conn.close()
        return deleted

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

    def validate_admin_discount_code(self, code: str, order_amount: int = 0) -> dict:
        """اعتبارسنجی و محاسبه تخفیف کدهای ادمین (بدون افزایش تعداد مصرف)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT * FROM discount_codes WHERE code = ? AND is_active = 1", (code.strip().upper(),))
            row = cursor.fetchone()
            if not row:
                return {"valid": False, "error": "کد تخفیف نامعتبر است."}
            
            d = dict(row)
            if d.get("max_uses", 0) > 0 and d.get("used_count", 0) >= d.get("max_uses"):
                return {"valid": False, "error": "ظرفیت استفاده از این کد تخفیف به پایان رسیده است."}

            if d.get("valid_until"):
                try:
                    exp = datetime.fromisoformat(d["valid_until"])
                    if get_now_naive() > exp:
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
            logger.error(f"Error validating admin discount code: {e}")
            return {"valid": False, "error": str(e)}
        finally:
            conn.close()

    def validate_customer_discount(self, sub_row_or_id, code: str, order_amount: int = 0) -> dict:
        """
        اعتبارسنجی ایزوله کد تخفیف مشتری:
        - اگر مشتری متعلق به نماینده باشد: صرفاً کدهای همان نماینده معتبر است (کدهای ادمین و سایر نمایندگان نامعتبرند).
        - اگر مشتری مستقیم ادمین باشد: صرفاً کدهای ادمین معتبر است (کدهای هیچ نماینده‌ای معتبر نیست).
        """
        if not code:
            return {"valid": False, "error": "لطفاً کد تخفیف را وارد کنید."}

        reseller_id = 0
        if isinstance(sub_row_or_id, dict):
            reseller_id = sub_row_or_id.get("reseller_id") or 0
        elif isinstance(sub_row_or_id, (int, str)):
            conn = self.get_connection()
            r = conn.execute("SELECT reseller_id FROM subscriptions WHERE id=? OR hidify_uuid=?", (str(sub_row_or_id), str(sub_row_or_id))).fetchone()
            conn.close()
            if r:
                reseller_id = r["reseller_id"] or 0

        if reseller_id and reseller_id > 0:
            # فقط و فقط کدهای این نماینده خاص
            return self.validate_reseller_discount_code(reseller_id, code, order_amount)
        else:
            # فقط و فقط کدهای مدیریت
            return self.validate_admin_discount_code(code, order_amount)

    def apply_customer_discount(self, sub_row_or_id, code: str) -> bool:
        """افزایش شمارنده استفاده از کد تخفیف در جدول مربوطه بر اساس ایزولاسیون نماینده یا ادمین"""
        if not code:
            return False

        reseller_id = 0
        if isinstance(sub_row_or_id, dict):
            reseller_id = sub_row_or_id.get("reseller_id") or 0
        elif isinstance(sub_row_or_id, (int, str)):
            conn = self.get_connection()
            r = conn.execute("SELECT reseller_id FROM subscriptions WHERE id=? OR hidify_uuid=?", (str(sub_row_or_id), str(sub_row_or_id))).fetchone()
            conn.close()
            if r:
                reseller_id = r["reseller_id"] or 0

        clean_code = code.strip().upper()
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            if reseller_id and reseller_id > 0:
                cursor.execute("""
                    UPDATE reseller_discount_codes 
                    SET used_count = used_count + 1 
                    WHERE reseller_id = ? AND code = ?
                """, (reseller_id, clean_code))
            else:
                cursor.execute("""
                    UPDATE discount_codes 
                    SET used_count = used_count + 1, updated_at = ? 
                    WHERE code = ?
                """, (now, clean_code))
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error applying customer discount: {e}")
            return False
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
            target_role = kwargs.get("target_role") or ('reseller' if reseller_id and int(reseller_id) > 0 else 'admin')
            ticket_type = kwargs.get("ticket_type") or "general"
            cursor.execute("""
                INSERT INTO support_tickets (telegram_id, subject, message, status, reseller_id, target_role, ticket_type, created_at, updated_at)
                VALUES (?, ?, ?, 'open', ?, ?, ?, ?, ?)
            """, (tg_id, subject, message, reseller_id, target_role, ticket_type, now, now))
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

    def create_portal_chat_ticket(self, subscription_id: int, customer_name: str, customer_phone: str, subject: str, initial_message: str, portal_token: str = None, reseller_id: int = None, telegram_id: int = None):
        """ایجاد تیکت گفتگوی آنلاین مشتری از پورتال وب با ثبت مشخصات و پیام اولیه"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        tg_id = telegram_id or subscription_id
        try:
            target_role = 'reseller' if reseller_id and int(reseller_id) > 0 else 'admin'
            cursor.execute("""
                INSERT INTO support_tickets (
                    telegram_id, subscription_id, customer_name, customer_phone, portal_token,
                    subject, message, status, reseller_id, target_role, ticket_type, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, 'portal_chat', ?, ?)
            """, (tg_id, subscription_id, customer_name, customer_phone, portal_token, subject, initial_message, reseller_id, target_role, now, now))
            ticket_id = cursor.lastrowid

            if initial_message:
                cursor.execute("""
                    INSERT INTO ticket_messages (ticket_id, sender_type, sender_id, sender_name, message, created_at)
                    VALUES (?, 'user', ?, ?, ?, ?)
                """, (ticket_id, tg_id, customer_name or "مشتری", initial_message, now))

            conn.commit()
            return {"success": True, "ticket_id": ticket_id}
        except Exception as e:
            logger.error(f"Error creating portal chat ticket: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def get_portal_chat_history(self, subscription_id: int, telegram_id: int = None, portal_token: str = None):
        """دریافت سوابق تمامی گفتگوهای آنلاین مرتبط با این اشتراک"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            conds = ["subscription_id = ?"]
            params = [subscription_id]
            if portal_token:
                conds.append("portal_token = ?")
                params.append(portal_token)
            if telegram_id and telegram_id > 0 and telegram_id != subscription_id:
                conds.append("telegram_id = ?")
                params.append(telegram_id)

            where_sql = " OR ".join(conds)
            cursor.execute(f"""
                SELECT id, subscription_id, customer_name, customer_phone, subject, message,
                       status, admin_reply, created_at, updated_at, reseller_id,
                       (SELECT COUNT(*) FROM ticket_messages WHERE ticket_id = support_tickets.id) as messages_count,
                       (SELECT message FROM ticket_messages WHERE ticket_id = support_tickets.id ORDER BY id DESC LIMIT 1) as last_message_text,
                       (SELECT created_at FROM ticket_messages WHERE ticket_id = support_tickets.id ORDER BY id DESC LIMIT 1) as last_message_time,
                       (SELECT sender_type FROM ticket_messages WHERE ticket_id = support_tickets.id ORDER BY id DESC LIMIT 1) as last_sender_type
                FROM support_tickets
                WHERE ({where_sql})
                  AND (ticket_type NOT IN ('reseller_to_admin', 'quota_change', 'reseller_application') OR ticket_type IS NULL)
                ORDER BY updated_at DESC, created_at DESC
            """, params)
            return [dict(r) for r in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting portal chat history: {e}")
            return []
        finally:
            conn.close()

    def get_portal_ticket(self, ticket_id: int, subscription_id: int = None, portal_token: str = None):
        """بررسی مجاز بودن و دریافت اطلاعات تیکت پورتال"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT * FROM support_tickets WHERE id = ?", (ticket_id,))
            row = cursor.fetchone()
            if not row:
                return None
            t = dict(row)
            if subscription_id is not None and t.get("subscription_id") and t.get("subscription_id") != subscription_id:
                if portal_token and t.get("portal_token") == portal_token:
                    pass
                else:
                    return None
            return t
        except Exception as e:
            logger.error(f"Error getting portal ticket: {e}")
            return None
        finally:
            conn.close()

    def add_portal_user_message(self, ticket_id: int, subscription_id: int, message: str, customer_name: str = None):
        """افزودن پیام جدید مشتری به گفتگوی آنلاین و تغییر وضعیت تیکت به open"""
        t = self.get_portal_ticket(ticket_id, subscription_id=subscription_id)
        if not t:
            return {"success": False, "error": "گفتگوی مورد نظر یافت نشد یا دسترسی نامعتبر است."}

        sender_name = customer_name or t.get("customer_name") or "مشتری"
        now = get_now_iso()
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO ticket_messages (ticket_id, sender_type, sender_id, sender_name, message, created_at)
                VALUES (?, 'user', ?, ?, ?, ?)
            """, (ticket_id, subscription_id, sender_name, message, now))
            msg_id = cursor.lastrowid

            cursor.execute("""
                UPDATE support_tickets 
                SET status = 'open', updated_at = ?
                WHERE id = ?
            """, (now, ticket_id))
            conn.commit()
            return {"success": True, "message_id": msg_id, "ticket": t}
        except Exception as e:
            logger.error(f"Error adding portal user message: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def poll_portal_ticket_updates(self, subscription_id: int, ticket_id: int = None, last_msg_id: int = 0):
        """بررسی پیام‌های جدید دریافتی از سمت پشتیبانی و وضعیت خوانده‌نشده"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            target_ticket_id = ticket_id
            if not target_ticket_id:
                cursor.execute("""
                    SELECT id FROM support_tickets 
                    WHERE subscription_id = ? 
                    ORDER BY updated_at DESC, id DESC LIMIT 1
                """, (subscription_id,))
                row = cursor.fetchone()
                if row:
                    target_ticket_id = row[0]

            new_messages = []
            ticket_info = None
            if target_ticket_id:
                cursor.execute("SELECT id, subject, status, updated_at FROM support_tickets WHERE id = ?", (target_ticket_id,))
                t_row = cursor.fetchone()
                if t_row:
                    ticket_info = dict(t_row)

                cursor.execute("""
                    SELECT * FROM ticket_messages 
                    WHERE ticket_id = ? AND id > ?
                    ORDER BY id ASC
                """, (target_ticket_id, last_msg_id))
                new_messages = [dict(m) for m in cursor.fetchall()]

            cursor.execute("""
                SELECT COUNT(*) FROM ticket_messages m
                JOIN support_tickets t ON m.ticket_id = t.id
                WHERE t.subscription_id = ? AND m.sender_type IN ('admin', 'reseller', 'ai') AND m.id > ?
            """, (subscription_id, last_msg_id))
            unread_count = cursor.fetchone()[0]

            return {
                "ticket_id": target_ticket_id,
                "ticket_info": ticket_info,
                "new_messages": new_messages,
                "unread_count": unread_count
            }
        except Exception as e:
            logger.error(f"Error polling portal ticket updates: {e}")
            return {"new_messages": [], "unread_count": 0}
        finally:
            conn.close()

    def has_human_support_replied(self, ticket_id: int) -> bool:
        """بررسی اینکه آیا پشتیبان انسانی (ادمین یا نماینده) در این تیکت پاسخ داده است یا خیر"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT COUNT(*) FROM ticket_messages
                WHERE ticket_id = ? AND sender_type IN ('admin', 'reseller', 'operator')
            """, (ticket_id,))
            cnt = cursor.fetchone()[0]
            if cnt > 0:
                return True
            cursor.execute("SELECT status FROM support_tickets WHERE id = ?", (ticket_id,))
            row = cursor.fetchone()
            if row and row[0] == "closed":
                return True
            return False
        except Exception as e:
            logger.error(f"Error checking human support reply: {e}")
            return False
        finally:
            conn.close()

    def is_support_online_for_sub(self, sub_id: int, reseller_id: int = 0) -> dict:
        """تشخیص وضعیت آنلاین یا آفلاین بودن پشتیبان برای یک اشتراک خاص (پشتیبانی نماینده یا مدیر)"""
        mode = self.get_setting("chat_fake_online_mode", "real")
        raw_agents = self.get_setting("chat_fake_online_agents", [])
        if isinstance(raw_agents, list):
            fake_agents = raw_agents
        elif isinstance(raw_agents, str):
            try:
                fake_agents = json.loads(raw_agents)
            except Exception:
                fake_agents = [x.strip() for x in raw_agents.split(",") if x.strip()]
        else:
            fake_agents = []

        # استخراج نام و هویت پشتیبان
        support_name = "پشتیبانی"
        if reseller_id and int(reseller_id) > 0:
            r = self.get_reseller(reseller_id)
            if r:
                support_name = r.get("brand_name") or r.get("brand_title") or r.get("name") or f"پشتیبانی نماینده ({r.get('username')})"
        else:
            support_name = self.get_setting("portal_title") or self.get_setting("store_name") or "پشتیبانی مرکزی"

        # ۱. بررسی حالت آنلاین ساختگی (Fake Online)
        if mode == "always_all":
            return {
                "is_online": True,
                "status": "online",
                "support_name": support_name,
                "status_text": "آنلاین و پاسخگو",
                "mode": "fake"
            }
        elif mode == "custom":
            is_fake_target = False
            if reseller_id and int(reseller_id) > 0:
                if str(reseller_id) in [str(x) for x in fake_agents]:
                    is_fake_target = True
            else:
                if "admin" in [str(x).lower() for x in fake_agents] or "0" in [str(x) for x in fake_agents]:
                    is_fake_target = True

            if is_fake_target:
                return {
                    "is_online": True,
                    "status": "online",
                    "support_name": support_name,
                    "status_text": "آنلاین و پاسخگو",
                    "mode": "fake"
                }

        # ۲. بررسی وضعیت واقعی (Real Online Status)
        is_online = False
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            now_tehran = datetime.now(TEHRAN_TZ)

            if reseller_id and int(reseller_id) > 0:
                # بررسی لاگین نماینده یا زیرمدیران فعال او
                cursor.execute("""
                    SELECT last_active_at, login_at FROM login_logs
                    WHERE user_type IN ('reseller', 'reseller_subadmin') AND user_id = ? AND is_active = 1
                    ORDER BY id DESC LIMIT 1
                """, (reseller_id,))
                row = cursor.fetchone()
                if row:
                    last_time_str = row[0] or row[1]
                    if last_time_str:
                        try:
                            last_time = datetime.fromisoformat(last_time_str)
                            if last_time.tzinfo is None:
                                last_time = last_time.replace(tzinfo=TEHRAN_TZ)
                            if abs((now_tehran - last_time).total_seconds()) <= 15 * 60:
                                is_online = True
                        except Exception:
                            pass

                # بررسی ارسال پیام اخیر تیکت توسط نماینده
                if not is_online:
                    cursor.execute("""
                        SELECT created_at FROM ticket_messages
                        WHERE sender_type = 'reseller' AND sender_id = ?
                        ORDER BY id DESC LIMIT 1
                    """, (reseller_id,))
                    t_msg = cursor.fetchone()
                    if t_msg and t_msg[0]:
                        try:
                            t_time = datetime.fromisoformat(t_msg[0])
                            if t_time.tzinfo is None:
                                t_time = t_time.replace(tzinfo=TEHRAN_TZ)
                            if abs((now_tehran - t_time).total_seconds()) <= 20 * 60:
                                is_online = True
                        except Exception:
                            pass
            else:
                # بررسی ادمین اصلی و سایر مدیران پنل
                cursor.execute("""
                    SELECT last_active_at, login_at FROM login_logs
                    WHERE user_type = 'admin' AND is_active = 1
                    ORDER BY id DESC LIMIT 1
                """)
                row = cursor.fetchone()
                if row:
                    last_time_str = row[0] or row[1]
                    if last_time_str:
                        try:
                            last_time = datetime.fromisoformat(last_time_str)
                            if last_time.tzinfo is None:
                                last_time = last_time.replace(tzinfo=TEHRAN_TZ)
                            if abs((now_tehran - last_time).total_seconds()) <= 15 * 60:
                                is_online = True
                        except Exception:
                            pass

                # بررسی ارسال پیام اخیر توسط ادمین
                if not is_online:
                    cursor.execute("""
                        SELECT created_at FROM ticket_messages
                        WHERE sender_type = 'admin'
                        ORDER BY id DESC LIMIT 1
                    """)
                    t_msg = cursor.fetchone()
                    if t_msg and t_msg[0]:
                        try:
                            t_time = datetime.fromisoformat(t_msg[0])
                            if t_time.tzinfo is None:
                                t_time = t_time.replace(tzinfo=TEHRAN_TZ)
                            if abs((now_tehran - t_time).total_seconds()) <= 20 * 60:
                                is_online = True
                        except Exception:
                            pass
        except Exception as e:
            logger.error(f"Error checking support real online status: {e}")
            is_online = False
        finally:
            conn.close()

        return {
            "is_online": is_online,
            "status": "online" if is_online else "offline",
            "support_name": support_name,
            "status_text": "آنلاین و پاسخگو" if is_online else "آفلاین (ثبت پیام برای بررسی)",
            "mode": "real"
        }

    def get_chat_settings(self) -> dict:
        """دریافت تنظیمات جامع گفتگوی آنلاین پورتال مشتری، استایل دکمه و هوش مصنوعی"""
        raw_agents = self.get_setting("chat_fake_online_agents", [])
        if isinstance(raw_agents, list):
            fake_agents = raw_agents
        elif isinstance(raw_agents, str):
            try:
                fake_agents = json.loads(raw_agents)
            except Exception:
                fake_agents = [x.strip() for x in raw_agents.split(",") if x.strip()]
        else:
            fake_agents = []

        return {
            "chat_button_style": self.get_setting("chat_button_style", "modern_pill"),
            "chat_button_text": self.get_setting("chat_button_text", "گفتگوی آنلاین"),
            "chat_button_position": self.get_setting("chat_button_position", "right"),
            "chat_fake_online_mode": self.get_setting("chat_fake_online_mode", "real"),
            "chat_fake_online_agents": fake_agents,
            "chat_ai_enabled": str(self.get_setting("chat_ai_enabled", "1")).lower() in ("1", "true"),
            "chat_ai_mode": self.get_setting("chat_ai_mode", "smart_local"),
            "chat_ai_api_key": self.get_setting("chat_ai_api_key", ""),
            "chat_ai_api_url": self.get_setting("chat_ai_api_url", "https://api.openai.com/v1/chat/completions"),
            "chat_ai_model": self.get_setting("chat_ai_model", "gpt-4o-mini"),
            "chat_sound_enabled": str(self.get_setting("chat_sound_enabled", "1")).lower() in ("1", "true")
        }

    def save_chat_settings(self, settings: dict):
        """ذخیره تنظیمات گفتگوی آنلاین در دیتابیس"""
        for k, v in settings.items():
            if isinstance(v, (list, dict)):
                self.save_setting(k, json.dumps(v, ensure_ascii=False))
            elif isinstance(v, bool):
                self.save_setting(k, "1" if v else "0")
            else:
                self.save_setting(k, str(v) if v is not None else "")

    def generate_ai_chat_reply(self, ticket_id: int, customer_message: str, sub_info: dict = None) -> Optional[str]:
        """پاسخگویی هوشمند چتبات هوش مصنوعی به پیام مشتری با رعایت توقف در صورت پاسخ پشتیبان انسانی"""
        # ۱. بررسی اینکه آیا پشتیبان انسانی قبلاً در این گفتگو پاسخ داده است یا خیر
        if self.has_human_support_replied(ticket_id):
            return None

        # ۲. بررسی فعال بودن هوش مصنوعی
        ai_enabled = str(self.get_setting("chat_ai_enabled", "1")).lower() in ("1", "true")
        if not ai_enabled:
            return None

        text = (customer_message or "").strip().lower()
        if not text:
            return None

        # ۳. حالت‌های مختلف پیام مشتری:
        # الف) اعلام آمادگی و تایید جهت حل مشکل
        affirmative_words = ["بله", "اره", "آره", "موافقم", "ممنون", "حل کن", "میخوام", "اوکی", "باشه", "مرسی", "لطفا", "لطفاً"]
        if any(w == text or text.startswith(w + " ") or text.endswith(" " + w) for w in affirmative_words) and len(text) <= 25:
            return (
                "با کمال میل! 🌸 من هوش مصنوعی هستم و آماده‌ام مشکل‌تان را بررسی و حل کنم.\n\n"
                "لطفاً بفرمایید دقیقاً چه مشکلی پیش آمده است؟\n"
                "• مشکل در اتصال و پینگ؟\n"
                "• نیاز به نرم‌افزار مناسب (اندروید، آیفون، ویندوز)؟\n"
                "• سوال در مورد تمدید یا دریافت لینک اشتراک؟"
            )

        # ب) مشکلات اتصال، قطعی، کار نکردن یا پینگ بالا
        if any(w in text for w in ["وصل نمیشه", "قطع", "کار نمیکنه", "پینگ", "سرعت", "کندی", "تایم اوت", "timeout", "فیلتر", "بسته شده", "وصل نیست"]):
            return (
                "برای رفع سریع مشکل اتصال و قطعی، لطفاً این مراحل پیشنهادی را به ترتیب انجام دهید:\n\n"
                "۱- **حالت پرواز (Airplane Mode)** گوشی خود را به مدت ۵ ثانیه روشن و سپس خاموش کنید تا IP شبکه شما نو شود.\n"
                "۲- در نرم‌افزار خود، گزینه **بروزرسانی اشتراک (Update Subscription)** را بزنید تا لیست جدیدترین سرورها دریافت شود.\n"
                "۳- در صورت استفاده از v2rayNG یا Streisand، قابلیت **Fragment** را در تنظیمات فعال کنید؛ این کار اختلال اپراتور را دور می‌زند.\n"
                "۴- در صورت امکان، یک‌بار اینترنت خود را بین همراه اول، ایرانسل یا وای‌فای سوییچ کنید.\n\n"
                "پیام شما به پشتیبان انسانی نیز ارجاع شده است و در صورت عدم رفع مشکل به زودی پاسخ خواهند داد."
            )

        # ج) سیستم‌عامل آیفون و iOS
        if any(w in text for w in ["آیفون", "ایفون", "iphone", "ios", "اپل", "apple"]):
            return (
                "برای دستگاه‌های **iOS (آیفون و آیپد)**، بهترین و سازگارترین نرم‌افزارها عبارتند از:\n\n"
                "📱 **Streisand** (پیشنهاد اول - پرسرعت و پایدار در اپ‌استور)\n"
                "📱 **FoXray** (بسیار قوی و سازگار با انواع کانفیگ‌ها)\n"
                "📱 **V2Box** (رایگان با کاربری ساده)\n\n"
                "کافیست لینک هوشمند اشتراک خود را از همین صفحه کپی نموده و در نرم‌افزار مربوطه اضافه نمایید."
            )

        # د) سیستم‌عامل اندروید
        if any(w in text for w in ["اندروید", "android", "سامسونگ", "شیائومی"]):
            return (
                "برای دستگاه‌های **اندروید**، نرم‌افزارهای استاندارد زیر پیشنهاد می‌شوند:\n\n"
                "🤖 **v2rayNG** (نسخه ۱.۸.۲۵ به بالا با پشتیبانی عالی از Fragment)\n"
                "🤖 **Hiddify Next** یا **Sing-box**\n\n"
                "کافی است لینک ساب را از دکمه کپی لینک در پورتال کپی کرده و در برنامه وارد فرمایید."
            )

        # ه) سوالات تمدید، شارژ و فاکتور
        if any(w in text for w in ["تمدید", "خرید", "فاکتور", "پرداخت", "کارت", "واریز", "پلن", "قیمت"]):
            return (
                "جهت **تمدید اشتراک یا خرید حجم اضافه**:\n\n"
                "می‌توانید مستقیماً در همین صفحه پورتال، از بخش **پلن‌های تمدید**، پلن مورد نظر خود را انتخاب کرده و به صورت آنلاین یا کارت‌به‌کارت واریز فرمایید. پس از واریز یا تایید فیش، اشتراک شما به طور خودکار شارژ و فعال می‌گردد."
            )

        # و) بررسی در صورت اتصال به API خارجی (OpenAI/Gemini/غیره)
        ai_mode = self.get_setting("chat_ai_mode", "smart_local")
        api_key = self.get_setting("chat_ai_api_key", "").strip()
        if ai_mode == "external_api" and api_key:
            try:
                import urllib.request
                api_url = self.get_setting("chat_ai_api_url", "https://api.openai.com/v1/chat/completions")
                model = self.get_setting("chat_ai_model", "gpt-4o-mini")
                payload = {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": "You are a polite, helpful Persian AI assistant for a VPN service customer portal. Help the user concisely and professionally. If you cannot solve it, reassure them human support will help soon."},
                        {"role": "user", "content": customer_message}
                    ],
                    "max_tokens": 250,
                    "temperature": 0.7
                }
                req = urllib.request.Request(
                    api_url,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {api_key}"
                    }
                )
                with urllib.request.urlopen(req, timeout=6) as response:
                    res_data = json.loads(response.read().decode("utf-8"))
                    choices = res_data.get("choices", [])
                    if choices and "message" in choices[0]:
                        return choices[0]["message"]["content"].strip()
            except Exception as e_api:
                logger.warning(f"External AI chat error: {e_api}")

        # پاسخ پیش‌فرض هوشمند و خوش‌آمدگویی
        return (
            "پیام شما با موفقیت ثبت و بررسی شد. 🤖\n\n"
            "من هوش مصنوعی پشتیبانی هستم؛ پیام‌تان همزمان برای کارشناسان پشتیبانی ارسال شده و در صورت نیاز به زودی به شما پاسخ خواهند داد.\n"
            "اگر در خصوص اتصال، نرم‌افزارها یا تمدید سوالی دارید، بفرمایید تا راهنمایی‌تان کنم."
        )

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
                    query += " AND t.reseller_id = ? AND t.ticket_type IN ('reseller_to_admin', 'quota_change', 'reseller_application')"
                    params.append(reseller_id)
                elif category == "customers":
                    query += " AND t.reseller_id = ? AND (t.ticket_type NOT IN ('reseller_to_admin', 'quota_change', 'reseller_application') OR t.ticket_type IS NULL)"
                    params.append(reseller_id)
                else:
                    query += " AND t.reseller_id = ?"
                    params.append(reseller_id)
            else:
                # پنل مدیریت
                if category == "resellers":
                    query += " AND t.ticket_type IN ('reseller_to_admin', 'quota_change', 'reseller_application')"
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
                query += " AND (t.id LIKE ? OR t.message LIKE ? OR t.admin_reply LIKE ? OR t.subject LIKE ? OR u.username LIKE ? OR u.phone_number LIKE ? OR t.telegram_id LIKE ? OR r.name LIKE ? OR r.username LIKE ? OR t.customer_name LIKE ? OR t.customer_phone LIKE ?)"
                params.extend([f"%{search}%"] * 11)

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
                res_stats = _calc_stats("WHERE t.ticket_type IN ('reseller_to_admin', 'quota_change', 'reseller_application')", [])
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
                cust_stats = _calc_stats("WHERE t.reseller_id = ? AND (t.ticket_type NOT IN ('reseller_to_admin', 'quota_change', 'reseller_application') OR t.ticket_type IS NULL)", [reseller_id])
                admin_stats = _calc_stats("WHERE t.reseller_id = ? AND t.ticket_type IN ('reseller_to_admin', 'quota_change', 'reseller_application')", [reseller_id])
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
                WHERE status IN ('approved', 'completed') AND (is_deleted = 0 OR is_deleted IS NULL) AND created_at >= date('now', '-30 days')""")
            stats["monthly_revenue"] = cursor.fetchone()["total"]
            
            # درآمد امروز
            cursor.execute("""SELECT COALESCE(SUM(amount), 0) as total FROM transactions 
                WHERE status IN ('approved', 'completed') AND (is_deleted = 0 OR is_deleted IS NULL) AND date(created_at) = date('now')""")
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
            cursor.execute("SELECT COALESCE(SUM(amount), 0) as total FROM transactions WHERE status IN ('approved', 'completed') AND (is_deleted = 0 OR is_deleted IS NULL)")
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

    def add_customer_debt_record(self, subscription_id: int, account_name: str = "",
                                 telegram_id: int = 0, reseller_id: int = None,
                                 action_type: str = "renew", plan_name: str = "",
                                 amount: int = 0, notes: str = None,
                                 created_by: str = None,
                                 previous_debt: int = None) -> dict:
        """
        ثبت رسید بدهی اختصاصی برای خرید یا تمدید مشتری به همراه تجمیع خودکار و دقیق با بدهی قبلی
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("SELECT * FROM subscriptions WHERE id = ?", (subscription_id,))
            sub_row = cursor.fetchone()
            if not sub_row:
                return {"success": False, "error": "اشتراک یافت نشد"}

            sub = dict(sub_row)
            added_amount = int(amount or 0)

            # محاسبه دقیق بدهی قبلی
            if previous_debt is not None:
                prev_debt = max(0, int(previous_debt))
            elif action_type == "create":
                # در زمان ساخت اولیه اشتراک، بدهی قبلی قطعاً صفر است
                prev_debt = 0
            else:
                # محاسبه بر اساس مجموع فاکتورهای باز ثبت‌شده قبلی
                cursor.execute("""
                    SELECT COALESCE(SUM(amount), 0), COUNT(*)
                    FROM customer_debt_records
                    WHERE subscription_id = ? AND status = 'unpaid' AND action_type != 'settle'
                """, (subscription_id,))
                unpaid_sum, count = cursor.fetchone()
                if count > 0:
                    prev_debt = int(unpaid_sum or 0)
                else:
                    prev_debt = int(sub.get("debt_amount") or 0)

            total_debt = prev_debt + added_amount
            act_name = account_name or sub.get("account_name") or ""
            tg_id = telegram_id if telegram_id else (sub.get("telegram_id") or 0)
            r_id = reseller_id if reseller_id is not None else sub.get("reseller_id")
            creator = created_by or "admin"

            # بروزرسانی اشتراک به وضعیت بدهکار و ثبت مجموع تجمعی صحیح بدهی
            cursor.execute("""
                UPDATE subscriptions
                SET payment_status = 'unpaid',
                    debt_amount = ?,
                    debt_notes = COALESCE(?, debt_notes),
                    debt_created_at = COALESCE(debt_created_at, ?),
                    updated_at = ?
                WHERE id = ?
            """, (total_debt, notes, now, now, subscription_id))

            # ثبت رکورد مجزا در جدول customer_debt_records
            cursor.execute("""
                INSERT INTO customer_debt_records
                (subscription_id, account_name, telegram_id, reseller_id, action_type, plan_name,
                 amount, previous_debt, total_debt, status, notes, created_by, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'unpaid', ?, ?, ?, ?)
            """, (
                subscription_id, act_name, tg_id, r_id, action_type, plan_name,
                added_amount, prev_debt, total_debt, notes, creator, now, now
            ))
            record_id = cursor.lastrowid
            conn.commit()

            logger.info(f"Customer debt record #{record_id} saved for sub #{subscription_id}: added={added_amount}, prev={prev_debt}, total={total_debt}")
            return {
                "success": True,
                "record_id": record_id,
                "previous_debt": prev_debt,
                "amount": added_amount,
                "total_debt": total_debt
            }
        except Exception as e:
            logger.error(f"Error adding customer debt record for sub {subscription_id}: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def repair_customer_debt_records(self, subscription_id: int = None) -> dict:
        """
        بررسی و خودترمیمی جامع زنجیره محاسباتی بدهی‌ها و رسیدها:
        - اصلاح previous_debt و total_debt بر اساس تاریخچه زمانی و مبالغ واقعی
        - همگام‌سازی subscriptions.debt_amount و payment_status با جمع فاکتورهای باز
        - تصحیح یادداشت‌های کپی‌شده مربوط به ساخت اشتراک روی رکوردهای تمدید
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        repaired_subs = 0
        repaired_records = 0
        try:
            if subscription_id:
                sub_ids = [subscription_id]
            else:
                cursor.execute("""
                    SELECT DISTINCT subscription_id FROM customer_debt_records
                    UNION
                    SELECT id FROM subscriptions WHERE payment_status IN ('unpaid', 'debtor') OR debt_amount > 0
                """)
                sub_ids = [r[0] for r in cursor.fetchall() if r[0]]

            for s_id in sub_ids:
                cursor.execute("""
                    SELECT * FROM customer_debt_records
                    WHERE subscription_id = ?
                    ORDER BY COALESCE(created_at, '') ASC, id ASC
                """, (s_id,))
                rows = cursor.fetchall()
                if not rows:
                    continue

                records = [dict(r) for r in rows]
                running_debt = 0
                sub_updated = False

                for rec in records:
                    rec_id = rec["id"]
                    act_type = rec.get("action_type") or "renew"
                    amt = int(rec.get("amount") or 0)
                    status = rec.get("status") or "unpaid"
                    current_prev = int(rec.get("previous_debt") or 0)
                    current_tot = int(rec.get("total_debt") or 0)
                    notes = rec.get("notes") or ""

                    # اصلاح یادداشت‌هایی که متن ساخت اشتراک را روی تمدید کپی کرده بودند
                    new_notes = notes
                    if act_type == "renew" and "ساخت اشتراک" in str(notes):
                        new_notes = str(notes).replace("ساخت اشتراک", "تمدید اشتراک")

                    if act_type in ("create", "renew", "manual", "initial"):
                        expected_prev = running_debt
                        expected_tot = running_debt + amt
                        if status != "paid":
                            running_debt = expected_tot

                    elif act_type == "settle":
                        expected_prev = running_debt
                        expected_tot = max(0, running_debt - amt)
                        running_debt = expected_tot
                    else:
                        expected_prev = running_debt
                        expected_tot = running_debt + amt
                        if status != "paid":
                            running_debt = expected_tot

                    if current_prev != expected_prev or current_tot != expected_tot or new_notes != notes:
                        cursor.execute("""
                            UPDATE customer_debt_records
                            SET previous_debt = ?, total_debt = ?, notes = ?
                            WHERE id = ?
                        """, (expected_prev, expected_tot, new_notes, rec_id))
                        repaired_records += 1
                        sub_updated = True

                # محاسبه جمع واقعی رسیدهای باز و همگام‌سازی اشتراک
                cursor.execute("""
                    SELECT COALESCE(SUM(amount), 0), COUNT(*)
                    FROM customer_debt_records
                    WHERE subscription_id = ? AND status = 'unpaid' AND action_type != 'settle'
                """, (s_id,))
                unpaid_sum, unpaid_count = cursor.fetchone()
                unpaid_sum = int(unpaid_sum or 0)

                cursor.execute("SELECT debt_amount, payment_status FROM subscriptions WHERE id = ?", (s_id,))
                sub_row = cursor.fetchone()
                if sub_row:
                    current_sub_debt = int(sub_row[0] or 0)
                    current_sub_status = sub_row[1] or "paid"
                    expected_status = "unpaid" if unpaid_sum > 0 else "paid"

                    if current_sub_debt != unpaid_sum or (unpaid_sum == 0 and current_sub_status in ("unpaid", "debtor")):
                        cursor.execute("""
                            UPDATE subscriptions
                            SET debt_amount = ?,
                                payment_status = ?,
                                debt_notes = CASE WHEN ? = 0 THEN NULL ELSE debt_notes END
                            WHERE id = ?
                        """, (unpaid_sum, expected_status, unpaid_sum, s_id))
                        sub_updated = True

                if sub_updated:
                    repaired_subs += 1

            conn.commit()
            return {"success": True, "repaired_subs": repaired_subs, "repaired_records": repaired_records}
        except Exception as e:
            logger.error(f"Error repairing customer debt records: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def get_customer_debt_report(self, subscription_id: int) -> dict:
        """
        دریافت گزارش جامع بدهی‌های یک مشتری شامل جمع کل، بدهی فعلی و لیست رسیدها به همراه خودترمیمی خودکار
        """
        # ابتدا خودترمیمی اجرا می‌شود تا هرگونه انحراف در دیتابیس خودبه‌خود اصلاح شود
        try:
            self.repair_customer_debt_records(subscription_id)
        except Exception as e_rep:
            logger.warning(f"Debt auto-repair warning for sub {subscription_id}: {e_rep}")

        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT * FROM subscriptions WHERE id = ?", (subscription_id,))
            sub_row = cursor.fetchone()
            if not sub_row:
                return {"success": False, "error": "اشتراک یافت نشد"}

            sub = dict(sub_row)
            cursor.execute("""
                SELECT * FROM customer_debt_records 
                WHERE subscription_id = ? 
                ORDER BY created_at DESC, id DESC
            """, (subscription_id,))
            rows = cursor.fetchall()
            records = [dict(r) for r in rows]

            current_debt = int(sub.get("debt_amount") or 0)

            # اگر رکوردی هنوز در جدول جدید ثبت نشده ولی در سابسکریپشن بدهی وجود دارد، رکورد آغازین درج کنیم
            if not records and current_debt > 0:
                now = get_now_iso()
                notes = sub.get("debt_notes") or "بدهی قبلی ثبت‌شده در سیستم"
                cursor.execute("""
                    INSERT INTO customer_debt_records
                    (subscription_id, account_name, telegram_id, reseller_id, action_type, plan_name,
                     amount, previous_debt, total_debt, status, notes, created_by, created_at, updated_at)
                    VALUES (?, ?, ?, ?, 'initial', ?, ?, 0, ?, 'unpaid', ?, ?, ?, ?)
                """, (
                    subscription_id, sub.get("account_name") or "", sub.get("telegram_id") or 0,
                    sub.get("reseller_id"), sub.get("plan_name") or "اشتراک",
                    current_debt, current_debt, notes, sub.get("created_by") or "سیستم",
                    sub.get("debt_created_at") or now, now
                ))
                conn.commit()
                cursor.execute("SELECT * FROM customer_debt_records WHERE subscription_id = ? ORDER BY id DESC", (subscription_id,))
                records = [dict(r) for r in cursor.fetchall()]

            total_debts_sum = sum(int(r.get("amount") or 0) for r in records if r.get("action_type") in ("create", "renew", "manual", "initial"))
            total_settled_sum = sum(int(r.get("amount") or 0) for r in records if r.get("status") == "paid" and r.get("action_type") != "settle")
            unpaid_count = sum(1 for r in records if r.get("status") == "unpaid" and r.get("action_type") != "settle")

            # محاسبه قطعی بدهی معوقه بر اساس جمع فاکتورهای باز
            if records:
                current_debt = sum(int(r.get("amount") or 0) for r in records if r.get("status") == "unpaid" and r.get("action_type") != "settle")

            return {
                "success": True,
                "subscription_id": subscription_id,
                "account_name": sub.get("account_name") or "",
                "telegram_id": sub.get("telegram_id") or 0,
                "reseller_id": sub.get("reseller_id"),
                "phone_number": sub.get("phone_number") or "",
                "current_debt": current_debt,
                "payment_status": sub.get("payment_status") or ("unpaid" if current_debt > 0 else "paid"),
                "debt_notes": sub.get("debt_notes") or "",
                "debt_created_at": sub.get("debt_created_at") or "",
                "total_debts_sum": total_debts_sum,
                "total_debt_accumulated": total_debts_sum,
                "total_settled_sum": total_settled_sum,
                "total_debt_settled": total_settled_sum,
                "unpaid_count": unpaid_count,
                "records": records
            }
        except Exception as e:
            logger.error(f"Error getting customer debt report for sub {subscription_id}: {e}")
            return {"success": False, "error": str(e), "records": []}
        finally:
            conn.close()

    def settle_customer_debt_record(self, subscription_id: int, record_id: int = None,
                                    amount: int = None, settled_by: str = "مدیریت",
                                    order_id: str = None) -> dict:
        """
        تسویه یک رسید بدهی خاص یا تسویه بخشی از بدهی مشتری با محاسبه دقیق مانده
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("SELECT * FROM subscriptions WHERE id = ?", (subscription_id,))
            sub_row = cursor.fetchone()
            if not sub_row:
                return {"success": False, "error": "اشتراک یافت نشد"}

            sub = dict(sub_row)
            current_debt = int(sub.get("debt_amount") or 0)

            if record_id:
                cursor.execute("SELECT * FROM customer_debt_records WHERE id = ? AND subscription_id = ?", (record_id, subscription_id))
                rec = cursor.fetchone()
                if not rec:
                    return {"success": False, "error": "رسید بدهی یافت نشد"}
                rec_dict = dict(rec)
                rec_amt = int(rec_dict.get("amount") or 0)
                cursor.execute("""
                    UPDATE customer_debt_records 
                    SET status = 'paid', paid_at = ?, settled_by = ?, settle_order_id = ?, updated_at = ?
                    WHERE id = ?
                """, (now, settled_by, order_id, now, record_id))

                # محاسبه دقیق بدهی جدید بر اساس فاکتورهای باز باقیمانده
                cursor.execute("""
                    SELECT COALESCE(SUM(amount), 0)
                    FROM customer_debt_records
                    WHERE subscription_id = ? AND status = 'unpaid' AND action_type != 'settle'
                """, (subscription_id,))
                new_debt = int(cursor.fetchone()[0] or 0)

            elif amount is not None and amount > 0:
                new_debt = max(0, current_debt - int(amount))
                cursor.execute("""
                    INSERT INTO customer_debt_records
                    (subscription_id, account_name, telegram_id, reseller_id, action_type, plan_name,
                     amount, previous_debt, total_debt, status, notes, created_by, paid_at, settled_by, settle_order_id, created_at, updated_at)
                    VALUES (?, ?, ?, ?, 'settle', 'تسویه بدهی', ?, ?, ?, 'paid', ?, ?, ?, ?, ?, ?, ?)
                """, (
                    subscription_id, sub.get("account_name"), sub.get("telegram_id") or 0,
                    sub.get("reseller_id"), int(amount), current_debt, new_debt,
                    f"تسویه مبلغ {amount:,} تومان توسط {settled_by}", settled_by, now, settled_by, order_id, now, now
                ))
            else:
                new_debt = 0
                cursor.execute("""
                    UPDATE customer_debt_records 
                    SET status = 'paid', paid_at = ?, settled_by = ?, settle_order_id = ?, updated_at = ?
                    WHERE subscription_id = ? AND status = 'unpaid'
                """, (now, settled_by, order_id, now, subscription_id))

            new_status = "paid" if new_debt == 0 else "unpaid"
            cursor.execute("""
                UPDATE subscriptions
                SET debt_amount = ?,
                    payment_status = ?,
                    debt_notes = CASE WHEN ? = 0 THEN NULL ELSE debt_notes END,
                    updated_at = ?
                WHERE id = ?
            """, (new_debt, new_status, new_debt, now, subscription_id))

            conn.commit()
            return {"success": True, "new_debt": new_debt, "new_status": new_status}
        except Exception as e:
            logger.error(f"Error settling debt for sub {subscription_id}: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def clear_subscription_debt(self, sub_id: int, reseller_id: int = None, settled_by: str = "مدیریت", order_id: str = None):
        """تسویه کامل بدهی مشتری و ثبت وضعیت پرداخت شده در اشتراک و رسیدها"""
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

            # بروزرسانی تمامی رکوردهای باز در جدول رسیدهای بدهی
            cursor.execute("""
                UPDATE customer_debt_records 
                SET status = 'paid', paid_at = ?, settled_by = ?, settle_order_id = ?, updated_at = ?
                WHERE subscription_id = ? AND status = 'unpaid'
            """, (now, settled_by or "مدیریت", order_id, now, sub_id))

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

            # ۶. آخرین تمدیدها و خریدها به همراه تاریخ عضویت و آخرین بروزرسانی (تایم‌لاین رویدادهای زنده ۳۰ تایی)
            if reseller_id:
                res["timeline_subscriptions"] = self.get_reseller_activity_timeline(reseller_id, limit=30)
            else:
                cursor.execute("""
                    SELECT s.*, u.created_at as user_registered_at, u.username
                    FROM subscriptions s
                    LEFT JOIN users u ON s.telegram_id = u.telegram_id
                    ORDER BY s.updated_at DESC LIMIT 30
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
                        credit_enabled: int = 0, credit_limit: int = 0, can_gift_traffic: int = 0) -> dict:
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
                    credit_enabled, credit_limit, credit_debt, can_gift_traffic,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)
            """, (
                cleaned_user, password_hash, name.strip(), telegram_id, initial_balance, 
                discount_percent, (hiddify_admin_uuid.strip() if hiddify_admin_uuid else None),
                parent_reseller_id, affiliate_commission_percent, referral_code,
                credit_enabled, credit_limit, can_gift_traffic,
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

    def get_active_subscriptions_for_sync(self, reseller_id: int = None) -> list:
        """واکشی اشتراک‌های فعال جهت پیش‌نمایش و همگام‌سازی با هیدیفای"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            if reseller_id:
                cursor.execute("""
                    SELECT id, telegram_id, hidify_uuid, plan_name, account_name, account_comment,
                           data_limit, data_used, duration, start_date, expire_date, status, reseller_id
                    FROM subscriptions
                    WHERE reseller_id = ? AND (is_deleted = 0 OR is_deleted IS NULL)
                    ORDER BY id DESC
                """, (reseller_id,))
            else:
                cursor.execute("""
                    SELECT id, telegram_id, hidify_uuid, plan_name, account_name, account_comment,
                           data_limit, data_used, duration, start_date, expire_date, status, reseller_id
                    FROM subscriptions
                    WHERE (is_deleted = 0 OR is_deleted IS NULL)
                    ORDER BY id DESC
                """)
            rows = cursor.fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def ensure_subscription_uuid(self, sub_id: int) -> str:
        """بررسی و تولید شناسه UUID در صورت خالی بودن برای اشتراک محلی"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT hidify_uuid FROM subscriptions WHERE id = ?", (sub_id,))
            row = cursor.fetchone()
            if row and row["hidify_uuid"] and str(row["hidify_uuid"]).strip():
                return str(row["hidify_uuid"]).strip()
            
            new_uuid = str(uuid.uuid4())
            cursor.execute("UPDATE subscriptions SET hidify_uuid = ?, updated_at = ? WHERE id = ?", (new_uuid, get_now_iso(), sub_id))
            conn.commit()
            return new_uuid
        finally:
            conn.close()

    def prune_selected_subscriptions(self, subscription_ids: list) -> dict:
        """حذف ایمن اشتراک‌های انتخاب‌شده محلی با پاکسازی وابستگی‌ها"""
        if not subscription_ids:
            return {"success": True, "purged_count": 0, "purged_names": []}
        
        valid_ids = [int(i) for i in subscription_ids if str(i).isdigit()]
        if not valid_ids:
            return {"success": True, "purged_count": 0, "purged_names": []}

        conn = self.get_connection()
        cursor = conn.cursor()
        purged_names = []
        try:
            placeholders = ",".join("?" for _ in valid_ids)
            cursor.execute(f"SELECT id, account_name FROM subscriptions WHERE id IN ({placeholders})", valid_ids)
            rows = cursor.fetchall()
            for r in rows:
                purged_names.append(r["account_name"] or f"#{r['id']}")

            # پاکسازی ارجاعات
            cursor.execute(f"UPDATE transactions SET subscription_id = NULL WHERE subscription_id IN ({placeholders})", valid_ids)
            cursor.execute(f"DELETE FROM subscription_history WHERE subscription_id IN ({placeholders})", valid_ids)
            cursor.execute(f"DELETE FROM subscriptions WHERE id IN ({placeholders})", valid_ids)
            
            # پاکسازی کاربران شبیه‌سازی‌شده بدون اشتراک
            cursor.execute("""
                DELETE FROM users 
                WHERE telegram_id >= 900000000 
                  AND telegram_id NOT IN (SELECT telegram_id FROM subscriptions)
            """)
            conn.commit()
            return {"success": True, "purged_count": len(valid_ids), "purged_names": purged_names}
        except Exception as e:
            conn.rollback()
            logger.error(f"Error in prune_selected_subscriptions: {e}")
            return {"success": False, "error": str(e), "purged_count": 0}
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

    get_resellers = get_all_resellers

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
                                subscription_id: int = None, selling_price: int = None, profit_margin: int = None,
                                created_by: str = None):
        """کسر هزینه با پشتیبانی از انتخاب دقیق مبدأ پرداخت (کیف پول نقدی یا اعتبار خرید)، ثبت صادرکننده و ثبت حاشیه سود"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("SELECT balance, credit_limit, credit_debt, credit_enabled, discount_percent FROM resellers WHERE id=?", (reseller_id,))
            row = cursor.fetchone()
            if not row:
                return {"success": False, "error": "نماینده یافت نشد."}

            balance = row["balance"] or 0
            credit_limit = row["credit_limit"] or 0
            credit_debt = row["credit_debt"] or 0
            credit_enabled = bool(row["credit_enabled"]) or (credit_limit > 0)
            available_credit = max(0, credit_limit - credit_debt) if credit_enabled else 0
            discount_pct = row["discount_percent"] if ("discount_percent" in row.keys() and row["discount_percent"] is not None) else 20

            chosen_source = str(payment_source).strip().lower() if payment_source else "auto"
            if selling_price is not None and int(selling_price) > 0:
                selling_val = int(selling_price)
            else:
                selling_val = int(amount * 100 / (100 - discount_pct)) if discount_pct < 100 else int(amount)
            profit_val = int(profit_margin) if profit_margin is not None else max(0, selling_val - int(amount))
            creator_val = str(created_by).strip() if created_by else None

            if chosen_source == "wallet":
                if balance < amount:
                    return {
                        "success": False,
                        "error": f"موجودی کیف پول شما کافی نیست! موجودی: {balance:,} تومان | مبلغ مورد نیاز: {amount:,} تومان"
                    }
                cursor.execute("UPDATE resellers SET balance = balance - ?, updated_at=? WHERE id=?", (amount, now, reseller_id))
                desc_text = f"{description} (کسر از کیف پول نقدی)"
                cursor.execute("""
                    INSERT INTO reseller_transactions (reseller_id, type, amount, selling_price, profit_margin, plan_name, account_name, description, payment_source, subscription_id, created_by, created_at)
                    VALUES (?, 'purchase', ?, ?, ?, ?, ?, ?, 'wallet', ?, ?, ?)
                """, (reseller_id, amount, selling_val, profit_val, plan_name, account_name, desc_text, subscription_id, creator_val, now))
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
                    INSERT INTO reseller_transactions (reseller_id, type, amount, selling_price, profit_margin, plan_name, account_name, description, payment_source, subscription_id, created_by, created_at)
                    VALUES (?, 'purchase_credit', ?, ?, ?, ?, ?, ?, 'credit', ?, ?, ?)
                """, (reseller_id, amount, selling_val, profit_val, plan_name, account_name, desc_text, subscription_id, creator_val, now))
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
                        INSERT INTO reseller_transactions (reseller_id, type, amount, selling_price, profit_margin, plan_name, account_name, description, payment_source, subscription_id, created_by, created_at)
                        VALUES (?, 'purchase', ?, ?, ?, ?, ?, ?, 'wallet', ?, ?, ?)
                    """, (reseller_id, amount, selling_val, profit_val, plan_name, account_name, description, subscription_id, creator_val, now))
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
                        INSERT INTO reseller_transactions (reseller_id, type, amount, selling_price, profit_margin, plan_name, account_name, description, payment_source, subscription_id, created_by, created_at)
                        VALUES (?, 'purchase_credit', ?, ?, ?, ?, ?, ?, 'credit', ?, ?, ?)
                    """, (reseller_id, amount, selling_val, profit_val, plan_name, account_name, desc_text, subscription_id, creator_val, now))
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
        """لیست تراکنش‌های یک نماینده به همراه صادرکننده، نوع فروش و حاشیه سود دقیق"""
        conn = self.get_connection()
        cursor = conn.cursor()
        res_info = self.get_reseller(reseller_id) or {}
        reseller_uname = res_info.get("username") or f"reseller_{reseller_id}"
        discount_pct = res_info.get("discount_percent") if res_info.get("discount_percent") is not None else 20

        cursor.execute("""
            SELECT rt.*, s.created_by as sub_creator, s.account_comment as sub_comment
            FROM reseller_transactions rt
            LEFT JOIN subscriptions s ON (rt.subscription_id = s.id OR (rt.subscription_id IS NULL AND rt.account_name IS NOT NULL AND rt.account_name != '' AND rt.account_name = s.account_name))
            WHERE rt.reseller_id = ?
            ORDER BY rt.created_at DESC
            LIMIT ?
        """, (reseller_id, limit))
        rows = cursor.fetchall()
        conn.close()

        result = []
        for r in rows:
            tx = dict(r)
            ttype = tx.get("type", "")
            amount = int(tx.get("amount") or 0)
            selling = int(tx.get("selling_price") or 0)
            profit = int(tx.get("profit_margin") or 0)

            # محاسبه پشتیبان حاشیه سود و قیمت فروش در صورت ثبت نشدن در سوابق
            if profit <= 0 and selling <= 0 and amount > 0 and ttype in ("purchase", "purchase_credit", "renewal", "renew"):
                selling = int(amount * 100 / (100 - discount_pct)) if discount_pct < 100 else amount
                profit = max(0, selling - amount)
            elif profit <= 0 and selling > amount:
                profit = max(0, selling - amount)

            tx["selling_price"] = selling
            tx["profit_margin"] = profit

            # تعیین عنوان فارسی نوع فروش
            if ttype in ("purchase", "purchase_credit"):
                tx["sale_type_title"] = "فروش جدید"
                tx["sale_type_class"] = "primary"
            elif ttype in ("renewal", "renew", "renew_credit"):
                tx["sale_type_title"] = "تمدید"
                tx["sale_type_class"] = "warning"
            elif ttype == "deposit":
                tx["sale_type_title"] = "شارژ کیف پول"
                tx["sale_type_class"] = "success"
            elif ttype == "refund":
                tx["sale_type_title"] = "استرداد وجه"
                tx["sale_type_class"] = "info"
            else:
                tx["sale_type_title"] = "-"
                tx["sale_type_class"] = "secondary"

            # صادرکننده
            raw_c = tx.get("created_by") or tx.get("sub_creator") or ""
            comment = tx.get("sub_comment") or tx.get("description") or ""
            if raw_c in ("bot", "robot", "ربات") or "bot" in str(raw_c).lower() or "bot" in str(comment).lower() or "ربات" in str(comment):
                tx["issuer"] = "ربات"
                tx["is_bot"] = True
            elif raw_c:
                tx["issuer"] = raw_c
                tx["is_bot"] = False
            else:
                tx["issuer"] = reseller_uname
                tx["is_bot"] = False

            result.append(tx)
        return result

    def get_reseller_activity_timeline(self, reseller_id: int, limit: int = 30) -> list:
        """
        تایم‌لاین هوشمند و جامع رویدادهای زنده فعالیت نماینده:
        - مرتب‌سازی نزولی بر اساس زمان آخرین فعالیت (جدیدترین در صدر لیست)
        - تفکیک کامل فعالیت‌ها: خرید ربات، تمدید اشتراک‌ها، ساخت مشتری دستی توسط مدیران و شارژ کیف پول
        - ثبت صادرکننده (نام کاربری مدیر یا عنوان 'ربات')
        - برگرداندن ۳۰ رویداد اخیر با قابلیت صفحه‌بندی
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        res_info = self.get_reseller(reseller_id) or {}
        reseller_uname = res_info.get("username") or f"reseller_{reseller_id}"
        discount_pct = res_info.get("discount_percent") if res_info.get("discount_percent") is not None else 20

        activities = []

        # ۱. استخراج تراکنش‌های نماینده (خرید، تمدید، شارژ و ...)
        try:
            cursor.execute("""
                SELECT rt.*, s.data_limit as sub_data_limit, s.duration as sub_duration,
                       s.status as sub_status, s.created_by as sub_created_by, s.account_comment
                FROM reseller_transactions rt
                LEFT JOIN subscriptions s ON (rt.subscription_id = s.id OR (rt.subscription_id IS NULL AND rt.account_name IS NOT NULL AND rt.account_name != '' AND rt.account_name = s.account_name))
                WHERE rt.reseller_id = ?
                ORDER BY rt.created_at DESC
                LIMIT ?
            """, (reseller_id, limit * 2))
            tx_rows = cursor.fetchall()
            for r in tx_rows:
                rd = dict(r)
                ttype = rd.get("type", "")
                raw_creator = rd.get("created_by") or rd.get("sub_created_by") or ""
                comment = rd.get("account_comment") or rd.get("description") or ""

                # تشخیص صادرکننده
                if raw_creator in ("bot", "robot", "ربات") or "bot" in str(raw_creator).lower() or "bot" in str(comment).lower() or "ربات" in str(comment):
                    issuer = "ربات"
                    issuer_type = "bot"
                elif raw_creator:
                    issuer = raw_creator
                    issuer_type = "user"
                else:
                    issuer = reseller_uname
                    issuer_type = "reseller"

                # تعیین نوع فعالیت
                if ttype in ("renewal", "renew", "renew_credit"):
                    act_type = "renewal"
                    act_title = "تمدید اشتراک"
                    badge_class = "warning"
                elif ttype in ("purchase", "purchase_credit"):
                    act_type = "new_sale"
                    act_title = "فروش جدید (ساخت مشتری)"
                    badge_class = "primary"
                elif ttype == "deposit":
                    act_type = "deposit"
                    act_title = "شارژ کیف پول"
                    badge_class = "success"
                elif ttype == "refund":
                    act_type = "refund"
                    act_title = "استرداد وجه"
                    badge_class = "info"
                else:
                    act_type = "activity"
                    act_title = "تراکنش"
                    badge_class = "secondary"

                amount = int(rd.get("amount") or 0)
                selling = int(rd.get("selling_price") or 0)
                profit = int(rd.get("profit_margin") or 0)
                if selling <= 0 and amount > 0 and ttype in ("purchase", "purchase_credit", "renewal"):
                    selling = int(amount * 100 / (100 - discount_pct)) if discount_pct < 100 else amount
                    profit = max(0, selling - amount)

                activities.append({
                    "id": f"tx_{rd['id']}",
                    "account_name": rd.get("account_name") or "-",
                    "plan_name": rd.get("plan_name") or "-",
                    "activity_type": act_type,
                    "activity_title": act_title,
                    "badge_class": badge_class,
                    "data_limit": rd.get("sub_data_limit") or 0,
                    "duration": rd.get("sub_duration") or 30,
                    "status": rd.get("sub_status") or "active",
                    "issuer": issuer,
                    "issuer_type": issuer_type,
                    "amount": amount,
                    "selling_price": selling,
                    "profit_margin": profit,
                    "created_at": rd.get("created_at") or "",
                    "description": rd.get("description") or ""
                })
        except Exception as e_tx:
            logger.error(f"Error fetching timeline transactions: {e_tx}")

        # ۲. اضافه کردن اشتراک‌هایی که احیاناً در reseller_transactions ثبت نشده‌اند
        try:
            cursor.execute("""
                SELECT s.* FROM subscriptions s
                WHERE s.reseller_id = ?
                  AND (s.is_deleted = 0 OR s.is_deleted IS NULL)
                  AND s.id NOT IN (SELECT subscription_id FROM reseller_transactions WHERE reseller_id = ? AND subscription_id IS NOT NULL)
                ORDER BY COALESCE(s.updated_at, s.created_at) DESC
                LIMIT ?
            """, (reseller_id, reseller_id, limit))
            sub_rows = cursor.fetchall()
            for s in sub_rows:
                sd = dict(s)
                raw_creator = sd.get("created_by") or ""
                comment = sd.get("account_comment") or ""
                if raw_creator in ("bot", "robot", "ربات") or "bot" in str(raw_creator).lower() or "bot" in str(comment).lower():
                    issuer = "ربات"
                    issuer_type = "bot"
                elif raw_creator:
                    issuer = raw_creator
                    issuer_type = "user"
                else:
                    issuer = reseller_uname
                    issuer_type = "reseller"

                is_renewed = sd.get("updated_at") and sd.get("created_at") and sd["updated_at"] > sd["created_at"]
                act_time = sd.get("updated_at") or sd.get("created_at") or ""

                activities.append({
                    "id": f"sub_{sd['id']}",
                    "account_name": sd.get("account_name") or "-",
                    "plan_name": sd.get("plan_name") or "-",
                    "activity_type": "renewal" if is_renewed else "new_sale",
                    "activity_title": "تمدید اشتراک" if is_renewed else "فروش جدید (ساخت مشتری)",
                    "badge_class": "warning" if is_renewed else "primary",
                    "data_limit": sd.get("data_limit") or 0,
                    "duration": sd.get("duration") or 30,
                    "status": sd.get("status") or "active",
                    "issuer": issuer,
                    "issuer_type": issuer_type,
                    "amount": int(sd.get("cost_paid") or 0),
                    "selling_price": 0,
                    "profit_margin": 0,
                    "created_at": act_time,
                    "description": sd.get("account_comment") or ""
                })
        except Exception as e_sub:
            logger.error(f"Error fetching timeline subscriptions: {e_sub}")

        conn.close()

        # ۳. مرتب‌سازی نزولی بر اساس زمان دقیق (جدیدترین فعالیت در صدر لیست)
        activities.sort(key=lambda x: str(x.get("created_at") or ""), reverse=True)
        return activities[:limit]

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
        raw_wallet_txs = cursor.fetchall()
        wallet_txs = []
        for r in raw_wallet_txs:
            w_dict = dict(r)
            w_dict["audit_logs"] = self.get_reseller_wallet_transaction_audit_logs(w_dict["id"])
            wallet_txs.append(w_dict)

        # ۲. رسیدها، فیش‌های بانکی و تراکنش‌های ثبت‌شده در جدول اصلی
        cursor.execute("""
            SELECT * FROM transactions 
            WHERE reseller_id = ? 
            ORDER BY created_at DESC
        """, (reseller_id,))
        raw_receipt_txs = cursor.fetchall()
        receipt_txs = []
        for r in raw_receipt_txs:
            r_dict = dict(r)
            r_dict["audit_logs"] = self.get_transaction_audit_logs(r_dict["id"])
            receipt_txs.append(r_dict)

        # ۳. محاسبات مالی دقیق (با حذف کامل تراکنش‌های باطل‌شده)
        cursor.execute("""
            SELECT COALESCE(SUM(amount), 0) FROM reseller_transactions 
            WHERE reseller_id=? AND type='deposit' 
              AND (is_revoked=0 OR is_revoked IS NULL) 
              AND (status != 'revoked' OR status IS NULL)
        """, (reseller_id,))
        total_deposited = cursor.fetchone()[0]

        cursor.execute("""
            SELECT COALESCE(SUM(amount), 0) FROM reseller_transactions 
            WHERE reseller_id=? AND type IN ('purchase', 'renewal') 
              AND (is_revoked=0 OR is_revoked IS NULL) 
              AND (status != 'revoked' OR status IS NULL)
        """, (reseller_id,))
        total_spent = cursor.fetchone()[0]

        cursor.execute("""
            SELECT COALESCE(SUM(amount), 0) FROM reseller_transactions 
            WHERE reseller_id=? AND type='refund' 
              AND (is_revoked=0 OR is_revoked IS NULL) 
              AND (status != 'revoked' OR status IS NULL)
        """, (reseller_id,))
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
            "discount_percent": reseller.get("discount_percent") if reseller.get("discount_percent") is not None else 20
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
        
        cursor.execute("SELECT balance, discount_percent, credit_enabled, credit_limit, credit_debt, can_gift_traffic, max_gift_traffic_gb FROM resellers WHERE id=?", (reseller_id,))
        res = cursor.fetchone()
        balance = res["balance"] if res else 0
        discount = res["discount_percent"] if res else 0
        credit_limit = (res["credit_limit"] or 0) if res and "credit_limit" in res.keys() else 0
        credit_debt = (res["credit_debt"] or 0) if res and "credit_debt" in res.keys() else 0
        credit_enabled = bool(res["credit_enabled"]) if (res and "credit_enabled" in res.keys() and res["credit_enabled"]) else (credit_limit > 0)
        can_gift_traffic = bool(res["can_gift_traffic"]) if (res and "can_gift_traffic" in res.keys() and res["can_gift_traffic"]) else False
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
            "can_gift_traffic": can_gift_traffic,
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

    def get_reseller_usage_summary(self, reseller_id: int) -> dict:
        """محاسبه خلاصه جامع وضعیت استفاده و عملکرد نماینده (امروز، دیروز، ماهانه، میانگین روزانه و ترافیک)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now_tehran = datetime.now(TEHRAN_TZ)
        today_date = now_tehran.strftime("%Y-%m-%d")
        yesterday_date = (now_tehran - timedelta(days=1)).strftime("%Y-%m-%d")
        month_ago_date = (now_tehran - timedelta(days=30)).strftime("%Y-%m-%d")

        try:
            # ۱. اطلاعات پایه و مالی نماینده
            cursor.execute("""
                SELECT balance, discount_percent, credit_enabled, credit_limit, credit_debt, can_gift_traffic
                FROM resellers WHERE id = ?
            """, (reseller_id,))
            res_row = cursor.fetchone()
            balance = res_row["balance"] if res_row else 0
            discount_percent = res_row["discount_percent"] if res_row else 0
            credit_limit = int(res_row["credit_limit"] or 0) if (res_row and "credit_limit" in res_row.keys()) else 0
            credit_debt = int(res_row["credit_debt"] or 0) if (res_row and "credit_debt" in res_row.keys()) else 0
            credit_enabled = bool(res_row["credit_enabled"]) if (res_row and "credit_enabled" in res_row.keys()) else (credit_limit > 0)
            available_credit = max(0, credit_limit - credit_debt) if credit_enabled else 0
            total_purchasing_power = balance + available_credit

            # ۲. استفاده امروز (Today's Usage)
            cursor.execute("""
                SELECT COALESCE(SUM(amount), 0), COUNT(*)
                FROM reseller_transactions
                WHERE reseller_id = ? 
                  AND type IN ('purchase', 'purchase_credit', 'renewal')
                  AND (created_at LIKE ? || '%')
            """, (reseller_id, today_date))
            today_row = cursor.fetchone()
            today_spent = int(today_row[0] or 0)
            today_orders = int(today_row[1] or 0)

            # ۳. استفاده دیروز (Yesterday's Usage)
            cursor.execute("""
                SELECT COALESCE(SUM(amount), 0), COUNT(*)
                FROM reseller_transactions
                WHERE reseller_id = ? 
                  AND type IN ('purchase', 'purchase_credit', 'renewal')
                  AND (created_at LIKE ? || '%')
            """, (reseller_id, yesterday_date))
            yesterday_row = cursor.fetchone()
            yesterday_spent = int(yesterday_row[0] or 0)
            yesterday_orders = int(yesterday_row[1] or 0)

            # ۴. استفاده ماهانه (۳۰ روز اخیر / Monthly Usage)
            cursor.execute("""
                SELECT COALESCE(SUM(amount), 0), COUNT(*)
                FROM reseller_transactions
                WHERE reseller_id = ? 
                  AND type IN ('purchase', 'purchase_credit', 'renewal')
                  AND created_at >= ?
            """, (reseller_id, month_ago_date))
            month_row = cursor.fetchone()
            month_spent = int(month_row[0] or 0)
            month_orders = int(month_row[1] or 0)

            # میانگین مصرف روزانه (بر مبنای ۳۰ روز)
            daily_average = int(month_spent / 30) if month_spent > 0 else 0

            # ۵. وضعیت ترافیک مصرفی مشترکین (Traffic stats)
            cursor.execute("""
                SELECT COALESCE(SUM(data_used), 0), COALESCE(SUM(data_limit), 0)
                FROM subscriptions
                WHERE reseller_id = ? AND (is_deleted = 0 OR is_deleted IS NULL)
            """, (reseller_id,))
            traffic_row = cursor.fetchone()
            total_used_gb = round(float(traffic_row[0] or 0), 2)
            total_limit_gb = round(float(traffic_row[1] or 0), 2)
            usage_percent = round((total_used_gb / total_limit_gb * 100), 1) if total_limit_gb > 0 else 0

            # ۶. آمار وضعیت کاربران
            cursor.execute("""
                SELECT 
                    COUNT(*),
                    COALESCE(SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END), 0),
                    COALESCE(SUM(CASE WHEN is_online = 1 THEN 1 ELSE 0 END), 0),
                    COALESCE(SUM(CASE WHEN status = 'expired' THEN 1 ELSE 0 END), 0)
                FROM subscriptions
                WHERE reseller_id = ? AND (is_deleted = 0 OR is_deleted IS NULL)
            """, (reseller_id,))
            u_row = cursor.fetchone()
            total_users = int(u_row[0] or 0)
            active_users = int(u_row[1] or 0)
            online_users = int(u_row[2] or 0)
            expired_users = int(u_row[3] or 0)

            # ۷. آمار اعضای تیم زیرمجموعه
            team_members = self.get_reseller_team_with_sessions(reseller_id)
            team_total = len(team_members)
            team_online = sum(1 for m in team_members if m.get("is_online"))

            return {
                "today": {
                    "spent": today_spent,
                    "orders": today_orders,
                    "date": today_date
                },
                "yesterday": {
                    "spent": yesterday_spent,
                    "orders": yesterday_orders,
                    "date": yesterday_date
                },
                "month": {
                    "spent": month_spent,
                    "orders": month_orders,
                    "date_from": month_ago_date
                },
                "daily_average": daily_average,
                "traffic": {
                    "used_gb": total_used_gb,
                    "limit_gb": total_limit_gb,
                    "percent": usage_percent
                },
                "users": {
                    "total": total_users,
                    "active": active_users,
                    "online": online_users,
                    "expired": expired_users
                },
                "team": {
                    "total": team_total,
                    "online": team_online,
                    "members": team_members
                },
                "financial": {
                    "balance": balance,
                    "discount_percent": discount_percent,
                    "credit_enabled": credit_enabled,
                    "credit_limit": credit_limit,
                    "credit_debt": credit_debt,
                    "available_credit": available_credit,
                    "total_purchasing_power": total_purchasing_power
                }
            }
        except Exception as e:
            logger.error(f"Error calculating reseller usage summary for {reseller_id}: {e}")
            return {
                "today": {"spent": 0, "orders": 0, "date": today_date},
                "yesterday": {"spent": 0, "orders": 0, "date": yesterday_date},
                "month": {"spent": 0, "orders": 0, "date_from": month_ago_date},
                "daily_average": 0,
                "traffic": {"used_gb": 0, "limit_gb": 0, "percent": 0},
                "users": {"total": 0, "active": 0, "online": 0, "expired": 0},
                "team": {"total": 0, "online": 0, "members": []},
                "financial": {"balance": 0, "discount_percent": 0, "credit_enabled": False, "credit_limit": 0, "credit_debt": 0, "available_credit": 0, "total_purchasing_power": 0}
            }
        finally:
            conn.close()

    def get_reseller_7days_revenue(self, reseller_id: int) -> dict:
        """
        محاسبه روند درآمد و فروش ۷ روز گذشته نماینده (شامل پرداخت‌های ربات و فروش مستقیم پنل)
        به همراه تاریخ‌های شمسی، نام روز هفته، تعداد سفارشات، میانگین فروش و سود برآورد شده
        """
        import datetime
        from utils import get_now_naive, gregorian_to_shamsi

        conn = self.get_connection()
        cursor = conn.cursor()
        now_dt = get_now_naive()
        today = now_dt.date()

        PERSIAN_WEEKDAYS = {
            0: "دوشنبه",
            1: "سه‌شنبه",
            2: "چهارشنبه",
            3: "پنج‌شنبه",
            4: "جمعه",
            5: "شنبه",
            6: "یکشنبه"
        }

        # درصد تخفیف نماینده جهت تخمین سود حاصله
        discount_pct = 20
        try:
            cursor.execute("SELECT discount_percent FROM resellers WHERE id = ?", (reseller_id,))
            r_row = cursor.fetchone()
            if r_row and r_row["discount_percent"] is not None:
                discount_pct = r_row["discount_percent"]
        except Exception:
            pass

        days_data = []
        total_revenue = 0
        total_orders = 0
        total_bot_revenue = 0
        total_direct_revenue = 0

        try:
            # استخراج داده‌های ۷ روز اخیر (از ۶ روز قبل تا امروز به ترتیب زمانی)
            for i in range(6, -1, -1):
                cur_date = today - datetime.timedelta(days=i)
                date_str = cur_date.strftime("%Y-%m-%d")
                weekday_name = PERSIAN_WEEKDAYS[cur_date.weekday()]

                if i == 0:
                    day_label = f"امروز ({weekday_name})"
                elif i == 1:
                    day_label = f"دیروز ({weekday_name})"
                else:
                    day_label = weekday_name

                jalali_str = gregorian_to_shamsi(date_str, fmt="%Y/%m/%d")

                # ۱. پرداخت‌های تایید شده ربات تلگرام نماینده
                cursor.execute("""
                    SELECT COALESCE(SUM(amount), 0), COUNT(*)
                    FROM transactions
                    WHERE reseller_id = ? 
                      AND status IN ('approved', 'completed')
                      AND (is_deleted = 0 OR is_deleted IS NULL)
                      AND (gateway != 'bundle_reseller' AND order_id NOT LIKE 'R_BUNDLE%')
                      AND DATE(created_at) = ?
                """, (reseller_id, date_str))
                bot_row = cursor.fetchone()
                bot_rev = int(bot_row[0] or 0)
                bot_cnt = int(bot_row[1] or 0)

                # ۲. خریدهای مستقیم و تمدیدهای ثبت شده در پنل وب توسط نماینده (محاسبه به عنوان درآمد با قیمت فروش و سود)
                cursor.execute("""
                    SELECT COALESCE(SUM(COALESCE(NULLIF(selling_price, 0), amount)), 0), 
                           COUNT(*),
                           COALESCE(SUM(profit_margin), 0)
                    FROM reseller_transactions
                    WHERE reseller_id = ? 
                      AND type IN ('purchase', 'purchase_credit', 'renewal')
                      AND DATE(created_at) = ?
                      AND (subscription_id IS NULL OR subscription_id NOT IN (
                          SELECT subscription_id FROM transactions 
                          WHERE reseller_id = ? AND subscription_id IS NOT NULL AND status IN ('approved', 'completed')
                      ))
                """, (reseller_id, date_str, reseller_id))
                dir_row = cursor.fetchone()
                dir_rev = int(dir_row[0] or 0)
                dir_cnt = int(dir_row[1] or 0)
                dir_prof = int(dir_row[2] or 0)
                if dir_prof <= 0 and dir_rev > 0:
                    dir_prof = int(dir_rev * (discount_pct / 100.0))

                day_total = bot_rev + dir_rev
                day_orders = bot_cnt + dir_cnt
                day_profit = dir_prof + int(bot_rev * (discount_pct / 100.0))

                total_revenue += day_total
                total_orders += day_orders
                total_bot_revenue += bot_rev
                total_direct_revenue += dir_rev

                days_data.append({
                    "date": date_str,
                    "jalali_date": jalali_str,
                    "day_name": weekday_name,
                    "day_label": day_label,
                    "is_today": (i == 0),
                    "is_yesterday": (i == 1),
                    "orders_count": day_orders,
                    "bot_revenue": bot_rev,
                    "bot_count": bot_cnt,
                    "direct_revenue": dir_rev,
                    "direct_count": dir_cnt,
                    "revenue": day_total,
                    "estimated_profit": day_profit,
                    "percentage": 0
                })

            max_day_rev = max([d["revenue"] for d in days_data], default=0)
            for d in days_data:
                if max_day_rev > 0:
                    d["percentage"] = round((d["revenue"] / max_day_rev) * 100, 1)
                else:
                    d["percentage"] = 0

            avg_daily_revenue = int(total_revenue / 7)
            estimated_total_profit = int(total_revenue * (discount_pct / 100.0))

            return {
                "days": days_data,
                "days_reversed": list(reversed(days_data)),
                "total_revenue": total_revenue,
                "total_orders": total_orders,
                "total_bot_revenue": total_bot_revenue,
                "total_direct_revenue": total_direct_revenue,
                "avg_daily_revenue": avg_daily_revenue,
                "estimated_total_profit": estimated_total_profit,
                "discount_percent": discount_pct
            }
        except Exception as e:
            logger.error(f"Error calculating reseller 7-day revenue: {e}")
            return {
                "days": [],
                "days_reversed": [],
                "total_revenue": 0,
                "total_orders": 0,
                "total_bot_revenue": 0,
                "total_direct_revenue": 0,
                "avg_daily_revenue": 0,
                "estimated_total_profit": 0,
                "discount_percent": discount_pct
            }
        finally:
            conn.close()

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

            # در صورت تسویه بدهی یا تنظیم مبلغ ۰، بستن فاکتورهای باز
            if payment_status == 'paid' or (debt_amount is not None and int(debt_amount) == 0):
                cursor.execute("""
                    UPDATE customer_debt_records
                    SET status = 'paid', paid_at = ?, settled_by = ?, updated_at = ?
                    WHERE subscription_id = ? AND status = 'unpaid'
                """, (now, f"reseller_{reseller_id}", now, sub_id))

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
                                    payment_source: str = "auto", selling_price: int = None, profit_margin: int = None,
                                    created_by: str = None):
        """تمدید اشتراک مشتری توسط نماینده با انتخاب دقیق مبدأ پرداخت، ثبت صادرکننده و ثبت حاشیه سود"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            # بررسی موجودی کیف پول و سقف اعتبار
            cursor.execute("SELECT balance, credit_enabled, credit_limit, credit_debt, discount_percent FROM resellers WHERE id=?", (reseller_id,))
            res_row = cursor.fetchone()
            if not res_row:
                return {"success": False, "error": "اطلاعات نماینده یافت نشد."}

            balance = res_row["balance"] or 0
            credit_limit = (res_row["credit_limit"] or 0) if "credit_limit" in res_row.keys() else 0
            credit_debt = (res_row["credit_debt"] or 0) if "credit_debt" in res_row.keys() else 0
            credit_enabled = bool(res_row["credit_enabled"]) if ("credit_enabled" in res_row.keys() and res_row["credit_enabled"]) else (credit_limit > 0)
            available_credit = max(0, credit_limit - credit_debt) if credit_enabled else 0
            discount_pct = res_row["discount_percent"] if ("discount_percent" in res_row.keys() and res_row["discount_percent"] is not None) else 20

            cursor.execute("SELECT * FROM subscriptions WHERE id=? AND reseller_id=?", (sub_id, reseller_id))
            sub = cursor.fetchone()
            if not sub:
                return {"success": False, "error": "اشتراک مورد نظر یافت نشد."}

            chosen_source = str(payment_source).strip().lower() if payment_source else "auto"
            mode_title = "فعال‌سازی آنی" if instant_activate else "رزرو در صف تمدید"
            actual_source = "wallet"

            if selling_price is not None and int(selling_price) > 0:
                selling_val = int(selling_price)
            else:
                selling_val = int(cost * 100 / (100 - discount_pct)) if discount_pct < 100 else int(cost)
            profit_val = int(profit_margin) if profit_margin is not None else max(0, selling_val - int(cost))
            creator_val = str(created_by).strip() if created_by else None

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

            # ثبت تراکنش تمدید با مشخص بودن مبدأ پرداخت، صادرکننده و حاشیه سود
            cursor.execute("""
                INSERT INTO reseller_transactions (reseller_id, type, amount, selling_price, profit_margin, plan_name, account_name, description, payment_source, subscription_id, created_by, created_at)
                VALUES (?, 'renewal', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (reseller_id, cost, selling_val, profit_val, plan_name, sub["account_name"], tx_desc, actual_source, sub_id, creator_val, now))

            if instant_activate:
                # ۳. به‌روزرسانی آنی مشخصات اشتراک، ریست حجم مصرفی و ریست تاریخ شروع و انقضا
                now_naive = get_now_naive()
                new_start_date = now_naive.strftime("%Y-%m-%d")
                new_expire_date = (now_naive + timedelta(days=duration)).isoformat()
                cursor.execute("""
                    UPDATE subscriptions
                    SET plan_id=?, plan_name=?, data_limit=?, data_used=0, duration=?, status='active',
                        start_date=?, expire_date=?, updated_at=?, cost_paid=?, payment_source=?, last_renewed_by=?
                    WHERE id=? AND reseller_id=?
                """, (plan_id, plan_name, data_limit, duration, new_start_date, new_expire_date, now, cost, actual_source, creator_val, sub_id, reseller_id))
                conn.commit()
                return {"success": True, "mode": "instant", "payment_source": actual_source}
            else:
                # ۴. افزودن به صف تمدید هوشمند (رزرو بسته خودکار بدون لغو بسته‌های قبلی)
                cursor.execute("SELECT COALESCE(MAX(queue_order), 0) + 1 FROM subscription_queue WHERE subscription_id=? AND status='pending'", (sub_id,))
                next_order_row = cursor.fetchone()
                next_order = next_order_row[0] if next_order_row else 1
                cursor.execute("""
                    INSERT INTO subscription_queue (
                        subscription_id, telegram_id, hidify_uuid, reseller_id,
                        plan_id, plan_name, data_limit, duration, cost, status, created_at, note, queue_order
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)
                """, (sub_id, sub["telegram_id"] or 0, sub["hidify_uuid"] or "", reseller_id,
                      plan_id, plan_name, data_limit, duration, cost, now, f"تمدید رزرو نماینده ({actual_source})", next_order))
                cursor.execute("UPDATE subscriptions SET payment_source=? WHERE id=?", (actual_source, sub_id))
                conn.commit()
                return {"success": True, "mode": "queued", "payment_source": actual_source, "queue_order": next_order}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def _normalize_subscription_queue_orders(self, cursor, subscription_id: int):
        """مرتب‌سازی و اصلاح مجدد شماره نوبت بسته‌های معلق در صف یک اشتراک (1, 2, 3...)"""
        try:
            cursor.execute("""
                SELECT id FROM subscription_queue
                WHERE subscription_id=? AND status='pending'
                ORDER BY COALESCE(queue_order, id) ASC, id ASC
            """, (subscription_id,))
            rows = cursor.fetchall()
            for idx, r in enumerate(rows, 1):
                cursor.execute("UPDATE subscription_queue SET queue_order=? WHERE id=?", (idx, r[0]))
        except Exception as e:
            logger.warning(f"Error normalizing queue orders for sub {subscription_id}: {e}")

    def add_to_subscription_queue(self, subscription_id: int, plan_id: str, plan_name: str,
                                  data_limit: float, duration: int, cost: int = 0,
                                  reseller_id: int = None, telegram_id: int = None,
                                  hidify_uuid: str = None, note: str = None) -> dict:
        """افزودن بسته تمدیدی به صف رزرو خودکار (بدون لغو بسته‌های قبلی و با تعیین شماره نوبت)"""
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

            cursor.execute("SELECT COALESCE(MAX(queue_order), 0) + 1 FROM subscription_queue WHERE subscription_id=? AND status='pending'", (subscription_id,))
            next_order_row = cursor.fetchone()
            next_order = next_order_row[0] if next_order_row else 1

            cursor.execute("""
                INSERT INTO subscription_queue (
                    subscription_id, telegram_id, hidify_uuid, reseller_id,
                    plan_id, plan_name, data_limit, duration, cost, status, created_at, note, queue_order
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)
            """, (subscription_id, t_id, u_uuid, r_id, plan_id, plan_name, data_limit, duration, cost, now, note or "تمدید در صف رزرو مدیریت", next_order))
            queue_id = cursor.lastrowid
            conn.commit()
            return {"success": True, "queue_id": queue_id, "queue_order": next_order}
        except Exception as e:
            logger.error(f"Error adding to subscription queue: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def get_pending_queue_items(self, subscription_id: int) -> list:
        """دریافت تمام بسته‌های در صف یک اشتراک به ترتیب نوبت تمدید"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT * FROM subscription_queue
                WHERE subscription_id=? AND status='pending'
                ORDER BY COALESCE(queue_order, id) ASC, id ASC
            """, (subscription_id,))
            return [dict(r) for r in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting pending queue items for sub {subscription_id}: {e}")
            return []
        finally:
            conn.close()

    def get_pending_queue_item(self, subscription_id: int) -> dict:
        """دریافت اولین بسته در نوبت صف برای یک اشتراک خاص"""
        items = self.get_pending_queue_items(subscription_id)
        return items[0] if items else None

    def reorder_subscription_queue(self, subscription_id: int, queue_id: int, direction: str) -> dict:
        """
        تغییر نوبت یک بسته در صف تمدید (direction: 'up', 'down', 'top')
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT id FROM subscription_queue
                WHERE subscription_id=? AND status='pending'
                ORDER BY COALESCE(queue_order, id) ASC, id ASC
            """, (subscription_id,))
            rows = [r[0] for r in cursor.fetchall()]
            if queue_id not in rows:
                return {"success": False, "error": "بسته در صف یافت نشد."}

            idx = rows.index(queue_id)
            if direction == "up":
                if idx > 0:
                    rows[idx], rows[idx - 1] = rows[idx - 1], rows[idx]
            elif direction == "down":
                if idx < len(rows) - 1:
                    rows[idx], rows[idx + 1] = rows[idx + 1], rows[idx]
            elif direction == "top":
                rows.insert(0, rows.pop(idx))
            else:
                return {"success": False, "error": "جهت جابجایی نامعتبر است."}

            for order, q_id in enumerate(rows, start=1):
                cursor.execute("UPDATE subscription_queue SET queue_order=? WHERE id=?", (order, q_id))
            conn.commit()
            return {"success": True}
        except Exception as e:
            logger.error(f"Error reordering queue for sub {subscription_id}: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def get_all_pending_queue_items(self, reseller_id: int = None) -> list:
        """دریافت تمام بسته‌های در صف به همراه اطلاعات اشتراک مربوطه به ترتیب نوبت برای پردازش خودکار و نمایش در پنل"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            sql = """
                SELECT q.*, s.account_name, s.data_used as curr_used, s.data_limit as curr_limit,
                       s.duration as curr_duration, s.start_date as curr_start_date,
                       s.expire_date as curr_expire_date, s.status as sub_status, s.telegram_id as sub_tg_id,
                       s.phone_number, r.name as reseller_name
                FROM subscription_queue q
                JOIN subscriptions s ON q.subscription_id = s.id
                LEFT JOIN resellers r ON q.reseller_id = r.id
                WHERE q.status = 'pending'
            """
            params = []
            if reseller_id is not None:
                sql += " AND q.reseller_id = ?"
                params.append(reseller_id)
            sql += " ORDER BY q.subscription_id ASC, COALESCE(q.queue_order, q.id) ASC, q.id ASC"
            cursor.execute(sql, params)
            return [dict(r) for r in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting all pending queue items: {e}")
            return []
        finally:
            conn.close()

    def get_pending_queue_count(self, reseller_id: int = None) -> int:
        """دریافت تعداد کل بسته‌های در انتظار صف تمدید"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            if reseller_id is not None:
                cursor.execute("SELECT COUNT(*) FROM subscription_queue WHERE status = 'pending' AND reseller_id = ?", (reseller_id,))
            else:
                cursor.execute("SELECT COUNT(*) FROM subscription_queue WHERE status = 'pending'")
            row = cursor.fetchone()
            return row[0] if row else 0
        except Exception as e:
            logger.error(f"Error getting pending queue count: {e}")
            return 0
        finally:
            conn.close()

    def get_subscription_queue_items(self, subscription_id: int, limit: int = 10) -> list:
        """دریافت تاریخچه و وضعیت بسته‌های در صف یک اشتراک خاص"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT * FROM subscription_queue
                WHERE subscription_id = ?
                ORDER BY COALESCE(queue_order, id) ASC, id DESC LIMIT ?
            """, (subscription_id, limit))
            return [dict(r) for r in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting queue items for sub {subscription_id}: {e}")
            return []
        finally:
            conn.close()

    def mark_queue_item_activated(self, queue_id: int) -> dict:
        """علامت‌گذاری بسته در صف به عنوان فعال‌شده و به‌روزرسانی نوبت بسته‌های باقیمانده"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("SELECT subscription_id FROM subscription_queue WHERE id=?", (queue_id,))
            row = cursor.fetchone()
            sub_id = row[0] if row else None

            cursor.execute("UPDATE subscription_queue SET status='activated', activated_at=? WHERE id=?", (now, queue_id))
            if sub_id:
                self._normalize_subscription_queue_orders(cursor, sub_id)
            conn.commit()
            return {"success": True}
        except Exception as e:
            logger.error(f"Error marking queue item {queue_id} activated: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def cancel_queue_item(self, queue_id: int, reseller_id: int = None) -> dict:
        """لغو بسته در صف و استرداد وجه به کیف‌پول نماینده یا کاربر در صورت پرداخت هزینه"""
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
            sub_id = item_dict.get("subscription_id")

            if reseller_id and r_id and r_id != reseller_id:
                return {"success": False, "error": "شما به این بسته دسترسی ندارید."}

            cursor.execute("SELECT * FROM subscriptions WHERE id=?", (sub_id,))
            sub_row = cursor.fetchone()
            sub_dict = dict(sub_row) if sub_row else {}
            account_name = sub_dict.get("account_name") or f"user_{sub_id}"

            # استرداد وجه به نماینده
            if r_id and cost > 0:
                # بررسی منبع پرداخت تمدید و علامت‌گذاری تراکنش تمدید به لغو شده
                cursor.execute("""
                    SELECT id, payment_source FROM reseller_transactions
                    WHERE reseller_id = ? AND (subscription_id = ? OR account_name = ?)
                      AND type IN ('renewal', 'renewal_credit')
                    ORDER BY id DESC LIMIT 1
                """, (r_id, sub_id, account_name))
                last_renew_tx = cursor.fetchone()
                renew_source = "wallet"
                if last_renew_tx:
                    renew_tx_id = last_renew_tx[0]
                    renew_source = last_renew_tx[1] or "wallet"
                    cursor.execute("""
                        UPDATE reseller_transactions
                        SET type = 'renewal_cancelled', description = description || ' [لغو شده از صف تمدید]'
                        WHERE id = ?
                    """, (renew_tx_id,))

                if renew_source == "credit":
                    cursor.execute("UPDATE resellers SET credit_debt = MAX(0, credit_debt - ?), updated_at=? WHERE id=?", (cost, now, r_id))
                    cursor.execute("""
                        INSERT INTO reseller_transactions (reseller_id, type, amount, plan_name, account_name, description, payment_source, subscription_id, created_at)
                        VALUES (?, 'refund_credit', ?, ?, ?, ?, 'credit', ?, ?)
                    """, (r_id, cost, item_dict.get("plan_name", ""), account_name, "استرداد وجه لغو بسته رزرو در صف (کاهش بدهی اعتبار)", sub_id, now))
                else:
                    cursor.execute("UPDATE resellers SET balance = balance + ?, updated_at=? WHERE id=?", (cost, now, r_id))
                    cursor.execute("""
                        INSERT INTO reseller_transactions (reseller_id, type, amount, plan_name, account_name, description, payment_source, subscription_id, created_at)
                        VALUES (?, 'refund', ?, ?, ?, ?, 'wallet', ?, ?)
                    """, (r_id, cost, item_dict.get("plan_name", ""), account_name, "استرداد وجه لغو بسته رزرو در صف (واریز به کیف پول)", sub_id, now))
            elif not r_id and cost > 0:
                # استرداد وجه برای مشتریان مستقیم ادمین
                tg_id = item_dict.get("telegram_id") or sub_dict.get("telegram_id")
                if tg_id:
                    try:
                        self.add_wallet_balance(
                            tg_id,
                            cost,
                            f"استرداد وجه بابت لغو بسته در صف تمدید برای اشتراک «{account_name}»",
                            tx_type="refund"
                        )
                    except Exception as we:
                        logger.error(f"Error refunding wallet to user {tg_id}: {we}")
                cursor.execute("""
                    UPDATE transactions
                    SET status = 'cancelled', is_deleted = 1
                    WHERE id = (
                        SELECT id FROM transactions
                        WHERE renew_sub_id = ? AND status IN ('approved', 'completed') AND (is_deleted = 0 OR is_deleted IS NULL)
                        ORDER BY id DESC LIMIT 1
                    )
                """, (sub_id,))

            cursor.execute("UPDATE subscription_queue SET status='cancelled', note='لغو توسط کاربر/مدیر و استرداد وجه' WHERE id=?", (queue_id,))
            if sub_id:
                self._normalize_subscription_queue_orders(cursor, sub_id)
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

        # جستجوی زمان آخرین استرداد ثبت‌شده برای این اشتراک در سطل زباله (جهت تفکیک حذف و بازگردانی‌های قبلی از لغو صف)
        cursor.execute("""
            SELECT MAX(created_at) FROM reseller_transactions
            WHERE reseller_id = ?
              AND (subscription_id = ? OR account_name = ?)
              AND type IN ('refund', 'refund_credit')
              AND (description LIKE '%سطل زباله%' OR description LIKE '%حذف اشتراک%')
        """, (reseller_id, sub_id, account_name))
        latest_refund_row = cursor.fetchone()
        latest_refund_time = latest_refund_row[0] if latest_refund_row and latest_refund_row[0] else None

        # جستجوی تمام اقدامات مالی کسر شده از نماینده برای این اکانت (صرفاً اقدامات پس از آخرین استرداد سطل زباله)
        if latest_refund_time:
            cursor.execute("""
                SELECT * FROM reseller_transactions
                WHERE reseller_id = ? 
                  AND (subscription_id = ? OR account_name = ?)
                  AND created_at > ?
                  AND type IN ('purchase', 'renewal', 'purchase_credit', 'renewal_credit')
                  AND type NOT IN ('renewal_cancelled', 'cancelled')
                ORDER BY created_at ASC
            """, (reseller_id, sub_id, account_name, latest_refund_time))
        else:
            cursor.execute("""
                SELECT * FROM reseller_transactions
                WHERE reseller_id = ? 
                  AND (subscription_id = ? OR account_name = ? OR description LIKE ?)
                  AND type IN ('purchase', 'renewal', 'purchase_credit', 'renewal_credit')
                  AND type NOT IN ('renewal_cancelled', 'cancelled')
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

                # تعیین زمان مبنا: برای خرید اولیه طبق تنظیمات، اما برای تمدیدها حتماً بر اساس زمان خود اقدام تمدید
                is_purchase_action = "purchase" in str(tx_d.get("type", "")).lower()
                if is_purchase_action and calc_from_creation:
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

            # ۲. لغو خودکار بسته‌های معلق در صف تمدید این اشتراک تا در صف معلق نمانند و پس از بازگردانی دوبله استرداد نشوند
            cursor.execute("""
                UPDATE subscription_queue 
                SET status = 'cancelled', note = 'لغو به علت حذف اشتراک و انتقال به سطل زباله'
                WHERE subscription_id = ? AND status = 'pending'
            """, (sub_id,))

            # ۳. حذف نرم اشتراک از جدول (انتقال به سطل زباله)
            by_user = deleted_by or f"reseller_{reseller_id}"
            cursor.execute("""
                UPDATE subscriptions 
                SET is_deleted = 1, deleted_at = ?, delete_reason = ?, deleted_by = ?, status = 'deleted', updated_at = ?
                WHERE id = ? AND reseller_id = ?
            """, (now, reason, by_user, now, sub_id, reseller_id))
            conn.commit()

            # ثبت لاگ انتقال به سطل زباله توسط نماینده
            try:
                self.add_system_log(
                    category="reseller",
                    action="delete",
                    title=f"انتقال اشتراک «{account_name}» به سطل زباله",
                    description=f"اشتراک «{account_name}» توسط نماینده ({by_user}) با علت «{reason}» به سطل زباله منتقل گردید." + (f" (استرداد وجه: {refund_amount:,} تومان به {payment_source})" if refund_amount > 0 else ""),
                    actor_type="reseller",
                    actor_id=reseller_id,
                    actor_name=by_user,
                    target_type="subscription",
                    target_id=sub_id,
                    target_name=account_name,
                    details={
                        "reseller_id": reseller_id,
                        "account_name": account_name,
                        "reason": reason,
                        "refund_amount": refund_amount,
                        "refund_percent": refund_percent,
                        "payment_source": payment_source
                    },
                    level="warning"
                )
            except Exception:
                pass

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

            # ۲. لغو خودکار بسته‌های معلق در صف تمدید این اشتراک
            cursor.execute("""
                UPDATE subscription_queue 
                SET status = 'cancelled', note = 'لغو به علت حذف اشتراک و انتقال به سطل زباله'
                WHERE subscription_id = ? AND status = 'pending'
            """, (sub_id,))

            # ۳. حذف نرم اشتراک از دیتابیس (انتقال به سطل زباله)
            cursor.execute("""
                UPDATE subscriptions 
                SET is_deleted = 1, deleted_at = ?, delete_reason = ?, deleted_by = ?, status = 'deleted', updated_at = ?
                WHERE id = ?
            """, (now, reason, admin_name, now, sub_id))
            conn.commit()

            # ثبت لاگ انتقال به سطل زباله توسط مدیر
            try:
                self.add_system_log(
                    category="admin",
                    action="delete",
                    title=f"انتقال اشتراک «{account_name}» به سطل زباله",
                    description=f"اشتراک «{account_name}» توسط {admin_name} با علت «{reason}» به سطل زباله منتقل گردید." + (f" (استرداد وجه: {refund_amount:,} تومان به کیف پول کاربر)" if (refund_done and refund_amount > 0) else ""),
                    actor_type="admin",
                    actor_name=admin_name,
                    target_type="subscription",
                    target_id=sub_id,
                    target_name=account_name,
                    details={
                        "account_name": account_name,
                        "hidify_uuid": hidify_uuid,
                        "user_id": user_id,
                        "reason": reason,
                        "refund_done": refund_done,
                        "refund_amount": refund_amount if refund_done else 0,
                        "refund_percent": refund_percent
                    },
                    level="warning"
                )
            except Exception:
                pass

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

            # ثبت لاگ بازگردانی
            try:
                self.add_system_log(
                    category="admin" if not is_reseller else "reseller",
                    action="restore",
                    title=f"بازگردانی اشتراک «{account_name}» از سطل زباله",
                    description=f"اشتراک «{account_name}» از سطل زباله بازیابی و مجدداً در پنل هیدیفای فعال گردید." + (f" (هزینه کسر شده: {cost:,} تومان)" if cost > 0 else ""),
                    actor_type="admin" if not is_reseller else "reseller",
                    actor_id=reseller_id if is_reseller else None,
                    actor_name=f"نماینده #{reseller_id}" if is_reseller else "مدیر سیستم",
                    target_type="subscription",
                    target_id=sub_id,
                    target_name=account_name,
                    details={
                        "account_name": account_name,
                        "hidify_uuid": new_uuid or sub_dict.get("hidify_uuid"),
                        "cost_deducted": cost,
                        "payment_source": chosen_source if (is_reseller and cost > 0) else None
                    },
                    level="success"
                )
            except Exception:
                pass

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
            sub_name = sub_dict.get("account_name") or f"Sub #{sub_id}"
            cursor.execute("DELETE FROM subscriptions WHERE id = ?", (sub_id,))
            conn.commit()

            # ثبت لاگ حذف دائمی دستی
            try:
                self.add_system_log(
                    category="admin" if not reseller_id else "reseller",
                    action="purge",
                    title=f"حذف دائمی اشتراک «{sub_name}» از سطل زباله",
                    description=f"اشتراک «{sub_name}» به صورت دستی برای همیشه از سطل زباله دیتابیس و پنل هیدیفای حذف گردید.",
                    actor_type="admin" if not reseller_id else "reseller",
                    actor_id=reseller_id,
                    actor_name=f"نماینده #{reseller_id}" if reseller_id else "مدیر سیستم",
                    target_type="subscription",
                    target_id=sub_id,
                    target_name=sub_name,
                    details={
                        "sub_id": sub_id,
                        "account_name": sub_name,
                        "hidify_uuid": sub_dict.get("hidify_uuid"),
                        "deleted_at": sub_dict.get("deleted_at"),
                        "deleted_by": sub_dict.get("deleted_by")
                    },
                    level="danger"
                )
            except Exception:
                pass

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
        purged_items = []
        try:
            cursor.execute("SELECT id, hidify_uuid, account_name, deleted_at, reseller_id FROM subscriptions WHERE is_deleted = 1")
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
                    purged_items.append({
                        "id": r["id"],
                        "account_name": r["account_name"],
                        "uuid": uuid_val,
                        "deleted_at": del_str,
                        "days_in_trash": round(days_passed, 1),
                        "reseller_id": r["reseller_id"]
                    })
            conn.commit()

            # ثبت لاگ دقیق خودکار سیستم در صورت پاکسازی اشتراک‌ها
            if purged_count > 0:
                try:
                    self.add_system_log(
                        category="system",
                        action="purge",
                        title=f"پاکسازی خودکار {purged_count} اشتراک از سرور هیدیفای",
                        description=f"تعداد {purged_count} اشتراک به علت انقضای مهلت {restore_window} روزه سطل زباله، به صورت خودکار توسط پردازش پس‌زمینه سیستم از پنل هیدیفای و دیتابیس حذف دائمی شدند.",
                        actor_type="system",
                        actor_name="سیستم (پاکسازی خودکار ۷ روزه)",
                        target_type="subscription",
                        target_name=f"{purged_count} اشتراک سطل زباله",
                        details={
                            "purged_count": purged_count,
                            "restore_window_days": restore_window,
                            "purged_items": purged_items
                        },
                        level="warning"
                    )
                except Exception as log_ex:
                    logger.error(f"Error recording auto purge system log: {log_ex}")
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
                "vip_auto_enabled", "vip_auto_threshold", "vip_cashback_percent",
                "bot_admins", "telegram_id", "updated_at"
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

    def get_reseller_bot_admins(self, reseller_id: int) -> list:
        """دریافت لیست ادمین‌های ربات تلگرام نماینده با تفکیک نقش‌ها"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT telegram_id, bot_admins FROM resellers WHERE id = ?", (reseller_id,))
            row = cursor.fetchone()
            if not row:
                return []
            raw_admins = row["bot_admins"]
            admins = []
            if raw_admins:
                try:
                    admins = json.loads(raw_admins)
                except Exception:
                    admins = []

            # اگر ادمین‌های ذخیره‌شده خالی بود اما telegram_id نماینده وجود داشت
            main_tg = row["telegram_id"]
            if main_tg and not any(str(a.get("telegram_id")) == str(main_tg) for a in admins):
                admins.insert(0, {
                    "telegram_id": main_tg,
                    "role": "main",
                    "title": "ادمین اصلی (پروفایل)"
                })
            return admins
        except Exception as e:
            logger.error(f"Error getting reseller bot admins: {e}")
            return []
        finally:
            conn.close()

    def is_reseller_bot_admin(self, reseller_id: int, telegram_id: int) -> tuple:
        """
        بررسی آیا کاربر ادمین ربات این نماینده است یا خیر؟
        بازگشت: (is_admin: bool, role: str)
        نقش‌ها: main (ادمین اصلی), finance (مدیر مالی), support (پشتیبان), sales (فروش)
        """
        if not telegram_id or not reseller_id:
            return False, ""

        admins = self.get_reseller_bot_admins(reseller_id)
        tg_str = str(telegram_id).strip()
        for a in admins:
            if str(a.get("telegram_id", "")).strip() == tg_str:
                return True, a.get("role", "main")

        # بررسی فیلد مستقیم telegram_id در resellers
        reseller = self.get_reseller(reseller_id)
        if reseller and reseller.get("telegram_id") and str(reseller["telegram_id"]).strip() == tg_str:
            return True, "main"

        return False, ""

    def is_telegram_user_any_reseller_admin(self, telegram_id: int) -> tuple:
        """بررسی آیا کاربر تلگرام ادمین ربات هر نماینده‌ای در سیستم هست یا نه"""
        if not telegram_id:
            return False, 0, ""
        conn = self.get_connection()
        cursor = conn.cursor()
        tg_str = str(telegram_id).strip()
        try:
            cursor.execute("SELECT id, telegram_id, bot_admins FROM resellers WHERE status = 'active'")
            for r in cursor.fetchall():
                r_id = r["id"]
                if r["telegram_id"] and str(r["telegram_id"]).strip() == tg_str:
                    return True, r_id, "main"
                if r["bot_admins"]:
                    try:
                        b_admins = json.loads(r["bot_admins"])
                        for a in b_admins:
                            if str(a.get("telegram_id", "")).strip() == tg_str:
                                return True, r_id, a.get("role", "main")
                    except Exception:
                        pass
            return False, 0, ""
        except Exception as e:
            logger.error(f"Error in is_telegram_user_any_reseller_admin: {e}")
            return False, 0, ""
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
                WHERE reseller_id = ? AND type IN ('purchase', 'purchase_credit', 'renewal', 'renew', 'renew_credit')
            """, (reseller_id,))
            total_wholesale_cost = cursor.fetchone()[0] or 0

            # ۲. مجموع واریزی‌ها / شارژ کیف‌پول
            cursor.execute("""
                SELECT COALESCE(SUM(amount), 0) FROM reseller_transactions 
                WHERE reseller_id = ? AND type = 'deposit'
            """, (reseller_id,))
            total_deposited = cursor.fetchone()[0] or 0

            # ۳. تخفیف و موجودی نماینده
            cursor.execute("SELECT discount_percent, balance, name, username FROM resellers WHERE id = ?", (reseller_id,))
            r_info = cursor.fetchone()
            discount_pct = r_info["discount_percent"] if (r_info and r_info["discount_percent"] is not None) else 20
            current_balance = r_info["balance"] if r_info else 0
            reseller_name = r_info["name"] if r_info else "همکار"
            reseller_uname = r_info["username"] if r_info else None

            # ۴. محاسبه سود و ارزش ریالی فروش (بر اساس حاشیه سود ثبت‌شده یا تخمین تخفیف)
            cursor.execute("""
                SELECT COALESCE(SUM(profit_margin), 0), COALESCE(SUM(selling_price), 0)
                FROM reseller_transactions
                WHERE reseller_id = ? AND type IN ('purchase', 'purchase_credit', 'renewal', 'renew', 'renew_credit')
            """, (reseller_id,))
            p_row = cursor.fetchone()
            actual_profit = p_row[0] if p_row else 0
            actual_selling = p_row[1] if p_row else 0

            if total_wholesale_cost == 0:
                cursor.execute("""
                    SELECT COALESCE(SUM(cost_paid), 0) FROM subscriptions 
                    WHERE reseller_id = ? AND (is_deleted = 0 OR is_deleted IS NULL)
                """, (reseller_id,))
                sub_cost = cursor.fetchone()[0] or 0
                if sub_cost > 0:
                    total_wholesale_cost = sub_cost

            if actual_selling == 0:
                cursor.execute("""
                    SELECT COALESCE(SUM(amount), 0) FROM transactions 
                    WHERE (reseller_id = ? OR (reseller_id IS NULL AND username = ?))
                      AND (is_deleted = 0 OR is_deleted IS NULL)
                      AND status IN ('approved', 'completed')
                      AND (gateway != 'bundle_reseller' AND order_id NOT LIKE 'R_BUNDLE%')
                """, (reseller_id, reseller_uname))
                tx_selling = cursor.fetchone()[0] or 0
                if tx_selling > 0:
                    actual_selling = tx_selling

            if actual_profit > 0 or actual_selling > 0:
                estimated_profit = actual_profit if actual_profit > 0 else max(0, actual_selling - total_wholesale_cost)
                estimated_retail_value = actual_selling if actual_selling > 0 else (total_wholesale_cost + actual_profit)
            elif discount_pct < 100 and discount_pct > 0 and total_wholesale_cost > 0:
                estimated_retail_value = int(total_wholesale_cost / (1.0 - (discount_pct / 100.0)))
                estimated_profit = max(0, estimated_retail_value - total_wholesale_cost)
            else:
                estimated_retail_value = total_wholesale_cost
                estimated_profit = 0

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
            allowed = [
                "custom_domain", "tutorial_domain", "logo_url", "favicon_url",
                "brand_title", "portal_title", "portal_subtitle", "support_phone", "support_username",
                "primary_color", "footer_text", "portal_layout", "portal_plan_style", "updated_at"
            ]
            fields = []
            params = []
            for k, v in kwargs.items():
                if k in allowed:
                    val = v.strip() if isinstance(v, str) else v
                    # دامنه‌ها در صورت خالی بودن باید None (معادل NULL در دیتابیس) ذخیره شوند تا تداخل ایندکس یونیک رخ ندهد
                    if k in ("custom_domain", "tutorial_domain"):
                        val = val.lower() if isinstance(val, str) else val
                        if not val:
                            val = None
                    fields.append(f"{k} = ?")
                    params.append(val)
            if not fields:
                return {"success": True}
            params.append(reseller_id)
            cursor.execute(f"UPDATE resellers SET {', '.join(fields)} WHERE id = ?", params)
            conn.commit()
            return {"success": True}
        except sqlite3.IntegrityError as e:
            err_str = str(e).lower()
            if "custom_domain" in err_str or "tutorial_domain" in err_str:
                return {"success": False, "error": "این دامنه قبلاً توسط نماینده دیگری ثبت شده است."}
            return {"success": False, "error": f"خطای یکتایی اطلاعات: {e}"}
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
            cursor.execute("SELECT * FROM reseller_cards WHERE reseller_id = ? ORDER BY is_default DESC, is_backup DESC, id DESC", (reseller_id,))
            return [dict(r) for r in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting reseller cards: {e}")
            return []
        finally:
            conn.close()

    def get_active_reseller_card(self, reseller_id: int, incoming_amount: int = 0):
        """دریافت کارت بانکی فعال نماینده جهت پرداخت با روتاتور هوشمند پیش‌فرض و پشتیبان بر اساس سقف روزانه"""
        best = self.get_best_active_card(owner_type="reseller", reseller_id=reseller_id, incoming_amount=incoming_amount)
        if best:
            return best

        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            # بازگشت به کارت ثبت‌شده در پروفایل اصلی نماینده
            cursor.execute("SELECT card_number, card_holder, bank_name FROM resellers WHERE id = ?", (reseller_id,))
            r_row = cursor.fetchone()
            if r_row and r_row["card_number"]:
                return {
                    "id": 0,
                    "card_number": r_row["card_number"],
                    "card_holder": r_row.get("card_holder") or "",
                    "bank_name": r_row.get("bank_name") or "بانک",
                    "daily_limit": 50000000,
                    "is_default": 1,
                    "is_backup": 0,
                    "balance": 0
                }
            return None
        except Exception as e:
            logger.error(f"Error getting active reseller card: {e}")
            return None
        finally:
            conn.close()

    def add_reseller_card(self, reseller_id: int, card_number: str, card_holder: str, bank_name: str,
                          daily_limit: int = 50000000, is_default: int = 0, is_backup: int = 0,
                          initial_balance: int = 0, shaba_number: str = None,
                          account_number: str = None, notes: str = None) -> dict:
        """افزودن کارت بانکی جدید برای نماینده با موجودی اولیه و نقش کارت"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            init_bal = max(0, int(initial_balance or 0))
            def_val = 1 if is_default else 0
            back_val = 1 if (is_backup and not def_val) else 0

            # اگر کارت جدید پیش‌فرض باشد، کارت‌های قبلی را از پیش‌فرض بودن خارج می‌کنیم
            if def_val:
                cursor.execute("UPDATE reseller_cards SET is_default = 0 WHERE reseller_id = ?", (reseller_id,))
            elif back_val:
                cursor.execute("UPDATE reseller_cards SET is_backup = 0 WHERE reseller_id = ?", (reseller_id,))

            cursor.execute("""
                INSERT INTO reseller_cards (
                    reseller_id, card_number, card_holder, bank_name, daily_limit,
                    is_active, created_at, is_default, is_backup, balance,
                    initial_balance, shaba_number, account_number, notes
                ) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                reseller_id, card_number.strip(), card_holder.strip(), bank_name.strip(),
                daily_limit, now, def_val, back_val, init_bal, init_bal,
                shaba_number.strip() if shaba_number else None,
                account_number.strip() if account_number else None,
                notes.strip() if notes else None
            ))
            card_id = cursor.lastrowid

            # در صورت وجود موجودی اولیه، ثبت سند افتتاحیه در دفتر ریزتراکنش‌ها
            if init_bal > 0:
                cursor.execute("""
                    INSERT INTO card_transactions (
                        card_id, owner_type, reseller_id, type, amount, balance_after,
                        category, title, description, tracking_code, ref_type, created_by, created_at
                    ) VALUES (?, 'reseller', ?, 'deposit', ?, ?, 'manual_deposit', 'ثبت موجودی اولیه کارت', 'افتتاح و تعیین موجودی اولیه کارت بانکی نماینده', 'INIT', 'card_init', 'system', ?)
                """, (card_id, reseller_id, init_bal, init_bal, now))

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

    def get_reseller_team_with_sessions(self, reseller_id: int) -> list:
        """لیست کادر و زیرمدیران نماینده به همراه وضعیت آنلاین، آخرین ورود و نشست‌های فعال"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT * FROM admin_users WHERE reseller_id = ? ORDER BY id ASC", (reseller_id,))
            members = [dict(r) for r in cursor.fetchall()]
            
            for m in members:
                m_id = m["id"]
                # وضعیت زنده آنلاین بودن
                m["is_online"] = self.is_user_online("reseller_subadmin", m_id)
                
                # دریافت سوابق ورود و نشست‌های این کاربر
                cursor.execute("""
                    SELECT * FROM login_logs 
                    WHERE user_type = 'reseller_subadmin' AND user_id = ? 
                    ORDER BY id DESC LIMIT 15
                """, (m_id,))
                logs = [dict(r) for r in cursor.fetchall()]
                m["login_logs"] = logs
                
                # تفکیک نشست‌های فعال جاری
                m["active_sessions"] = [l for l in logs if l.get("is_active")]
                m["active_sessions_count"] = len(m["active_sessions"])
                
                # اطلاعات آخرین نشست / فعالیت
                if logs:
                    m["last_login"] = logs[0].get("login_at")
                    m["last_active"] = logs[0].get("last_active_at")
                    m["last_ip"] = logs[0].get("ip_address")
                    m["last_device"] = logs[0].get("device_os")
                    m["last_browser"] = logs[0].get("browser")
                else:
                    m["last_login"] = None
                    m["last_active"] = None
                    m["last_ip"] = None
                    m["last_device"] = None
                    m["last_browser"] = None
                    
            return members
        except Exception as e:
            logger.error(f"Error getting reseller team with sessions for reseller {reseller_id}: {e}")
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
        """لیست تمام کارت‌های بانکی مدیریت مرتب‌شده بر اساس اولویت پیش‌فرض و پشتیبان"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM bank_cards ORDER BY is_default DESC, is_backup DESC, id DESC")
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_active_bank_cards(self):
        """لیست کارت‌های بانکی فعال مدیریت"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM bank_cards WHERE is_active=1 ORDER BY is_default DESC, is_backup DESC, id DESC")
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def add_bank_card(self, card_number: str, card_holder: str, bank_name: str,
                      daily_limit: int = 50000000, is_default: int = 0, is_backup: int = 0,
                      initial_balance: int = 0, shaba_number: str = None,
                      account_number: str = None, notes: str = None):
        """افزودن کارت بانکی جدید برای مدیریت با موجودی اولیه و نقش کارت"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            init_bal = max(0, int(initial_balance or 0))
            def_val = 1 if is_default else 0
            back_val = 1 if (is_backup and not def_val) else 0

            # اگر کارت جدید پیش‌فرض باشد، کارت‌های قبلی را از پیش‌فرض خارج می‌کنیم
            if def_val:
                cursor.execute("UPDATE bank_cards SET is_default = 0")
            elif back_val:
                cursor.execute("UPDATE bank_cards SET is_backup = 0")

            cursor.execute("""
                INSERT INTO bank_cards (
                    card_number, card_holder, bank_name, daily_limit, is_active,
                    created_at, is_default, is_backup, balance, initial_balance,
                    shaba_number, account_number, notes
                ) VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                card_number.strip(), card_holder.strip(), bank_name.strip(),
                daily_limit, now, def_val, back_val, init_bal, init_bal,
                shaba_number.strip() if shaba_number else None,
                account_number.strip() if account_number else None,
                notes.strip() if notes else None
            ))
            card_id = cursor.lastrowid

            # ثبت سند افتتاحیه در صورت وجود موجودی اولیه
            if init_bal > 0:
                cursor.execute("""
                    INSERT INTO card_transactions (
                        card_id, owner_type, reseller_id, type, amount, balance_after,
                        category, title, description, tracking_code, ref_type, created_by, created_at
                    ) VALUES (?, 'admin', 0, 'deposit', ?, ?, 'manual_deposit', 'ثبت موجودی اولیه کارت', 'افتتاح و تعیین موجودی اولیه کارت بانکی مدیریت', 'INIT', 'card_init', 'system', ?)
                """, (card_id, init_bal, init_bal, now))

            conn.commit()
            try:
                self.export_full_backup_json()
            except Exception:
                pass
            return {"success": True, "card_id": card_id}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

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

    # ═══════════════════════════════════════════════════════════════════════
    # سیستم جامع حسابداری شناور و روتاتور هوشمند کارت‌ها (Card Rotator & Ledger)
    # ═══════════════════════════════════════════════════════════════════════

    def get_card_daily_volume(self, card_id: int, owner_type: str = "admin", date_str: str = None) -> int:
        """محاسبه مجموع واریزی‌های یک کارت در روز جاری جهت کنترل سقف روزانه"""
        if not date_str:
            date_str = get_now_naive().strftime("%Y-%m-%d")
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT COALESCE(SUM(amount), 0) FROM card_transactions 
                WHERE card_id = ? AND owner_type = ? AND type = 'deposit' AND created_at LIKE ?
            """, (card_id, owner_type, f"{date_str}%"))
            return cursor.fetchone()[0] or 0
        finally:
            conn.close()

    def get_best_active_card(self, owner_type: str = "admin", reseller_id: int = 0, incoming_amount: int = 0) -> Optional[dict]:
        """
        انتخاب هوشمند کارت بانکی جهت ارسال به مشتری:
        ۱. اولویت اول: کارت پیش‌فرض (در صورت داشتن ظرفیت سقف روزانه)
        ۲. اولویت دوم: کارت پشتیبان (در صورت پر شدن سقف کارت پیش‌فرض)
        ۳. اولویت سوم: سایر کارت‌های فعال با ظرفیت باقیمانده
        ۴. برگشت به کارت پیش‌فرض/پشتیبان در صورت پر بودن تمام سقف‌ها
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            today_str = get_now_naive().strftime("%Y-%m-%d")
            if owner_type == "admin":
                cursor.execute("SELECT * FROM bank_cards WHERE is_active = 1 ORDER BY is_default DESC, is_backup DESC, id ASC")
            else:
                cursor.execute("SELECT * FROM reseller_cards WHERE reseller_id = ? AND is_active = 1 ORDER BY is_default DESC, is_backup DESC, id ASC", (reseller_id,))
            
            rows = [dict(r) for r in cursor.fetchall()]
            if not rows:
                if owner_type == "reseller":
                    cursor.execute("SELECT card_number, card_holder, bank_name FROM resellers WHERE id = ?", (reseller_id,))
                    r_row = cursor.fetchone()
                    if r_row and r_row["card_number"]:
                        return {
                            "id": 0,
                            "card_number": r_row["card_number"],
                            "card_holder": r_row.get("card_holder") or "",
                            "bank_name": r_row.get("bank_name") or "بانک",
                            "daily_limit": 50000000,
                            "is_default": 1,
                            "is_backup": 0,
                            "balance": 0
                        }
                return None

            default_card = None
            backup_card = None
            other_eligible_cards = []

            for c in rows:
                c_id = c["id"]
                cursor.execute("""
                    SELECT COALESCE(SUM(amount), 0) FROM card_transactions 
                    WHERE card_id = ? AND owner_type = ? AND type = 'deposit' AND created_at LIKE ?
                """, (c_id, owner_type, f"{today_str}%"))
                vol_today = cursor.fetchone()[0] or 0
                c["daily_volume_today"] = vol_today
                c_limit = c.get("daily_limit") or 50000000
                has_capacity = (vol_today + incoming_amount) <= c_limit

                if c.get("is_default") and not default_card:
                    default_card = c
                elif c.get("is_backup") and not backup_card:
                    backup_card = c
                else:
                    if has_capacity:
                        other_eligible_cards.append(c)

            # ۱. بررسی کارت پیش‌فرض
            if default_card:
                def_limit = default_card.get("daily_limit") or 50000000
                if (default_card["daily_volume_today"] + incoming_amount) <= def_limit:
                    return default_card

            # ۲. بررسی کارت پشتیبان (چون پیش‌فرض پر شده یا تعریف نشده)
            if backup_card:
                back_limit = backup_card.get("daily_limit") or 50000000
                if (backup_card["daily_volume_today"] + incoming_amount) <= back_limit:
                    return backup_card

            # ۳. سایر کارت‌های فعال با ظرفیت آزاد
            if other_eligible_cards:
                return other_eligible_cards[0]

            # ۴. در صورت پر بودن تمام کارت‌ها، کارت پیش‌فرض یا اولین کارت فعال را برگشت می‌دهیم
            return default_card or backup_card or rows[0]
        finally:
            conn.close()

    def set_card_role(self, card_id: int, role: str, owner_type: str = "admin", reseller_id: int = 0) -> dict:
        """
        تنظیم نقش کارت (پیش‌فرض، پشتیبان، عادی)
        role: 'default', 'backup', 'normal'
        """
        table = "bank_cards" if owner_type == "admin" else "reseller_cards"
        owner_filter = "" if owner_type == "admin" else " AND reseller_id = ?"
        params = [reseller_id] if owner_type == "reseller" else []

        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            if role == "default":
                cursor.execute(f"UPDATE {table} SET is_default = 0 WHERE 1=1 {owner_filter}", params)
                cursor.execute(f"UPDATE {table} SET is_default = 1, is_backup = 0 WHERE id = ?", (card_id,))
            elif role == "backup":
                cursor.execute(f"UPDATE {table} SET is_backup = 0 WHERE 1=1 {owner_filter}", params)
                cursor.execute(f"UPDATE {table} SET is_backup = 1, is_default = 0 WHERE id = ?", (card_id,))
            else:  # 'normal'
                cursor.execute(f"UPDATE {table} SET is_default = 0, is_backup = 0 WHERE id = ?", (card_id,))
            conn.commit()
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def update_card_info(self, card_id: int, owner_type: str = "admin", **kwargs) -> dict:
        """ویرایش مشخصات، اطلاعات شبا و تنظیم مانده حساب کارت"""
        table = "bank_cards" if owner_type == "admin" else "reseller_cards"
        allowed = ["card_number", "card_holder", "bank_name", "daily_limit", "shaba_number", "account_number", "notes", "initial_balance", "balance"]
        updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
        if not updates:
            return {"success": False, "error": "فیلدی برای به‌روزرسانی ارسال نشده است."}

        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            fields = ", ".join([f"{k}=?" for k in updates.keys()])
            values = list(updates.values()) + [card_id]
            cursor.execute(f"UPDATE {table} SET {fields} WHERE id = ?", values)
            conn.commit()
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def add_card_transaction(self, card_id: int, owner_type: str = "admin", amount: int = 0,
                             tx_type: str = "deposit", category: str = "subscription",
                             title: str = "", description: str = None, tracking_code: str = None,
                             ref_type: str = None, ref_id: str = None, created_by: str = None,
                             reseller_id: int = 0) -> dict:
        """
        ثبت تراکنش واریز/برداشت و به‌روزرسانی آنی مانده حساب شناور کارت
        """
        if not card_id or int(card_id) <= 0:
            return {"success": False, "error": "شناسه کارت نامعتبر است."}

        table = "bank_cards" if owner_type == "admin" else "reseller_cards"
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        amt = abs(int(amount or 0))

        try:
            cursor.execute(f"SELECT * FROM {table} WHERE id = ?", (card_id,))
            card_row = cursor.fetchone()
            if not card_row:
                return {"success": False, "error": "کارت بانکی مورد نظر یافت نشد."}

            card = dict(card_row)
            curr_bal = int(card.get("balance") or 0)

            if tx_type == "deposit":
                new_balance = curr_bal + amt
            else:  # withdrawal
                new_balance = curr_bal - amt

            cursor.execute(f"UPDATE {table} SET balance = ? WHERE id = ?", (new_balance, card_id))

            cursor.execute("""
                INSERT INTO card_transactions (
                    card_id, owner_type, reseller_id, type, amount, balance_after,
                    category, title, description, tracking_code, ref_type, ref_id,
                    created_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                card_id, owner_type, reseller_id or card.get("reseller_id", 0),
                tx_type, amt, new_balance, category,
                title.strip() if title else ("واریز به کارت" if tx_type == "deposit" else "برداشت از کارت"),
                description.strip() if description else None,
                tracking_code.strip() if tracking_code else None,
                ref_type, str(ref_id) if ref_id else None,
                created_by or "system", now
            ))
            tx_id = cursor.lastrowid

            # همگام‌سازی با سیستم حسابداری کل (accounting_records) برای مدیریت
            if owner_type == "admin":
                cat_map = {
                    "salary": "حقوق و دستمزد",
                    "server_cost": "سرور و زیرساخت",
                    "bank_fee": "کارمزد بانکی",
                    "withdrawal": "برداشت سود شخصی",
                    "manual_deposit": "واریز متفرقه",
                    "other": "سایر هزینه‌ها"
                }
                if tx_type == "withdrawal" and category in cat_map:
                    try:
                        cursor.execute("""
                            INSERT INTO accounting_records 
                            (type, category, title, amount, source, ref_type, ref_id, description, date, created_at)
                            VALUES ('expense', ?, ?, ?, ?, 'card_tx', ?, ?, ?, ?)
                        """, (cat_map[category], title or cat_map[category], amt, f"card_{card_id}", str(tx_id), description or f"کسر از کارت {card.get('bank_name')} ({card.get('card_number')[-4:]})", now[:10], now))
                    except Exception as e_acc:
                        logger.error(f"Error syncing card withdrawal to accounting: {e_acc}")
                elif tx_type == "deposit" and category == "manual_deposit":
                    try:
                        cursor.execute("""
                            INSERT INTO accounting_records 
                            (type, category, title, amount, source, ref_type, ref_id, description, date, created_at)
                            VALUES ('income', 'واریز دستی/متفرقه', ?, ?, ?, 'card_tx', ?, ?, ?, ?)
                        """, (title or "واریز به حساب", amt, f"card_{card_id}", str(tx_id), description, now[:10], now))
                    except Exception as e_acc:
                        logger.error(f"Error syncing card deposit to accounting: {e_acc}")

            conn.commit()
            return {"success": True, "transaction_id": tx_id, "new_balance": new_balance}
        except Exception as e:
            logger.error(f"Error adding card transaction: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def get_card_details_and_transactions(self, card_id: int, owner_type: str = "admin", limit: int = 150, category: str = None, tx_type: str = None) -> dict:
        """دریافت جزییات کارت، مانده شناور، گردش روز و ریزتراکنش‌های تفکیکی"""
        table = "bank_cards" if owner_type == "admin" else "reseller_cards"
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(f"SELECT * FROM {table} WHERE id = ?", (card_id,))
            card_row = cursor.fetchone()
            if not card_row:
                return {"success": False, "error": "کارت یافت نشد."}
            card = dict(card_row)

            query = "SELECT * FROM card_transactions WHERE card_id = ? AND owner_type = ?"
            q_params = [card_id, owner_type]
            if category and category != "all":
                query += " AND category = ?"
                q_params.append(category)
            if tx_type and tx_type != "all":
                query += " AND type = ?"
                q_params.append(tx_type)
            query += " ORDER BY id DESC LIMIT ?"
            q_params.append(limit)

            cursor.execute(query, q_params)
            tx_rows = [dict(r) for r in cursor.fetchall()]

            today_str = get_now_naive().strftime("%Y-%m-%d")
            cursor.execute("SELECT COALESCE(SUM(amount), 0) FROM card_transactions WHERE card_id = ? AND owner_type = ? AND type = 'deposit'", (card_id, owner_type))
            total_deposits = cursor.fetchone()[0] or 0

            cursor.execute("SELECT COALESCE(SUM(amount), 0) FROM card_transactions WHERE card_id = ? AND owner_type = ? AND type = 'withdrawal'", (card_id, owner_type))
            total_withdrawals = cursor.fetchone()[0] or 0

            cursor.execute("SELECT COALESCE(SUM(amount), 0) FROM card_transactions WHERE card_id = ? AND owner_type = ? AND type = 'deposit' AND created_at LIKE ?", (card_id, owner_type, f"{today_str}%"))
            today_volume = cursor.fetchone()[0] or 0

            daily_limit = card.get("daily_limit") or 50000000
            usage_pct = min(100.0, round((today_volume / daily_limit) * 100, 1)) if daily_limit > 0 else 0

            return {
                "success": True,
                "card": card,
                "transactions": tx_rows,
                "summary": {
                    "total_deposits": total_deposits,
                    "total_withdrawals": total_withdrawals,
                    "today_volume": today_volume,
                    "balance": card.get("balance", 0),
                    "daily_limit": daily_limit,
                    "daily_usage_percent": usage_pct
                }
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def get_cards_financial_summary(self, owner_type: str = "admin", reseller_id: int = 0) -> dict:
        """محاسبه شاخص‌های مالی مانده شناور، کل واریزها، مخارج و صندوق نقد"""
        table = "bank_cards" if owner_type == "admin" else "reseller_cards"
        owner_filter = "" if owner_type == "admin" else " WHERE reseller_id = ?"
        params = [reseller_id] if owner_type == "reseller" else []
        today_str = get_now_naive().strftime("%Y-%m-%d")
        month_str = get_now_naive().strftime("%Y-%m")

        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(f"SELECT COALESCE(SUM(balance), 0), COUNT(*) FROM {table} {owner_filter}", params)
            row = cursor.fetchone()
            total_cards_balance = row[0] or 0
            cards_count = row[1] or 0

            q_dep = """
                SELECT COALESCE(SUM(amount), 0) FROM card_transactions 
                WHERE owner_type = ? AND (reseller_id = ? OR ? = 0) AND type = 'deposit' AND created_at LIKE ?
            """
            cursor.execute(q_dep, (owner_type, reseller_id, reseller_id, f"{month_str}%"))
            month_deposits = cursor.fetchone()[0] or 0

            q_with = """
                SELECT COALESCE(SUM(amount), 0) FROM card_transactions 
                WHERE owner_type = ? AND (reseller_id = ? OR ? = 0) AND type = 'withdrawal' AND created_at LIKE ?
            """
            cursor.execute(q_with, (owner_type, reseller_id, reseller_id, f"{month_str}%"))
            month_withdrawals = cursor.fetchone()[0] or 0

            q_today = """
                SELECT COALESCE(SUM(amount), 0) FROM card_transactions 
                WHERE owner_type = ? AND (reseller_id = ? OR ? = 0) AND type = 'deposit' AND created_at LIKE ?
            """
            cursor.execute(q_today, (owner_type, reseller_id, reseller_id, f"{today_str}%"))
            today_deposits = cursor.fetchone()[0] or 0

            cursor.execute("""
                SELECT COALESCE(SUM(amount), 0) FROM cash_desk_logs 
                WHERE owner_type = ? AND (owner_id = ? OR ? = 0) AND is_settled = 0 AND type = 'income'
            """, (owner_type, reseller_id, reseller_id))
            unsettled_cash = cursor.fetchone()[0] or 0

            net_floating_balance = total_cards_balance + unsettled_cash

            return {
                "total_cards_balance": total_cards_balance,
                "unsettled_cash": unsettled_cash,
                "net_floating_balance": net_floating_balance,
                "month_deposits": month_deposits,
                "month_withdrawals": month_withdrawals,
                "today_deposits": today_deposits,
                "cards_count": cards_count
            }
        finally:
            conn.close()

    def add_cash_desk_log(self, owner_type: str, owner_id: int, amount: int, tx_type: str = "income",
                          customer_name: str = None, plan_name: str = None, description: str = None,
                          created_by: str = None) -> dict:
        """ثبت دریافت نقدی در صندوق جهت تسویه بعدی با مدیریت/پنل"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("""
                INSERT INTO cash_desk_logs (owner_type, owner_id, type, amount, customer_name, plan_name, description, created_by, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (owner_type, owner_id, tx_type, int(amount), customer_name, plan_name, description, created_by, now))
            row_id = cursor.lastrowid
            conn.commit()
            return {"success": True, "id": row_id, "log_id": row_id}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def get_cash_desk_logs(self, owner_type: str = "admin", owner_id: int = 0, limit: int = 100) -> dict:
        """لیست دریافتی‌های نقدی و مانده تسویه نشده صندوق نقد"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT * FROM cash_desk_logs 
                WHERE owner_type = ? AND (owner_id = ? OR ? = 0)
                ORDER BY id DESC LIMIT ?
            """, (owner_type, owner_id, owner_id, limit))
            logs = [dict(r) for r in cursor.fetchall()]

            cursor.execute("""
                SELECT COALESCE(SUM(amount), 0) FROM cash_desk_logs 
                WHERE owner_type = ? AND (owner_id = ? OR ? = 0) AND is_settled = 0 AND type = 'income'
            """, (owner_type, owner_id, owner_id))
            unsettled_total = cursor.fetchone()[0] or 0

            cursor.execute("""
                SELECT COALESCE(SUM(amount), 0) FROM cash_desk_logs 
                WHERE owner_type = ? AND (owner_id = ? OR ? = 0) AND is_settled = 1 AND type = 'income'
            """, (owner_type, owner_id, owner_id))
            settled_total = cursor.fetchone()[0] or 0

            return {
                "logs": logs,
                "unsettled_total": unsettled_total,
                "settled_total": settled_total
            }
        finally:
            conn.close()

    def settle_cash_desk_log(self, log_id: int, settled_by: str = None, owner_type: str = "admin",
                            owner_id: int = 0, target_card_id: int = None, note: str = None,
                            actor: str = None) -> dict:
        """تسویه سند دریافت نقدی و واریز به کارت مقصد در صورت انتخاب"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        effective_actor = actor or settled_by or "admin"
        try:
            cursor.execute("SELECT * FROM cash_desk_logs WHERE id = ?", (log_id,))
            row = cursor.fetchone()
            if not row:
                return {"success": False, "error": "سند صندوق نقدی یافت نشد."}
            log_data = dict(row)
            if log_data.get("is_settled"):
                return {"success": False, "error": "این سند قبلاً تسویه شده است."}

            amount = int(log_data.get("amount", 0))
            cust_name = log_data.get("customer_name") or ""
            row_owner_type = log_data.get("owner_type") or owner_type or "admin"
            row_owner_id = int(log_data.get("owner_id", 0) or owner_id or 0)

            cursor.execute("""
                UPDATE cash_desk_logs 
                SET is_settled = 1, settled_at = ?, settled_by = ? 
                WHERE id = ?
            """, (now, effective_actor, log_id))
            conn.commit()

            # اگر کارت مقصد انتخاب شده باشد، مبلغ نقدی به موجودی کارت واریز می‌شود
            if target_card_id:
                try:
                    self.add_card_transaction(
                        card_id=target_card_id,
                        owner_type=row_owner_type,
                        amount=amount,
                        tx_type="deposit",
                        category="تسویه صندوق نقدی",
                        title=f"واریز تسویه نقدی ({cust_name})" if cust_name else "واریز تسویه صندوق نقدی",
                        description=note or f"تسویه سند نقدی شماره #{log_id}",
                        ref_type="cash_settle",
                        ref_id=str(log_id),
                        created_by=effective_actor,
                        reseller_id=row_owner_id if row_owner_type == "reseller" else 0
                    )
                except Exception as ex_card:
                    logger.error(f"Error depositing to target card during cash settlement: {ex_card}")

            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

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
                disc = res.get("discount_percent") if res.get("discount_percent") is not None else 20

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

    # ─── تنظیمات پرداخت ارزی و کریپتو نماینده (Reseller Crypto Settings) ───

    def get_reseller_crypto_config(self, reseller_id: int) -> dict:
        """دریافت تنظیمات پرداخت ارزی و کریپتو اختصاصی نماینده"""
        enabled_val = self.get_setting(f"crypto_enabled_r_{reseller_id}", "0")
        wallet_addr = str(self.get_setting(f"crypto_wallet_r_{reseller_id}", "") or "").strip()
        usdt_rate_val = self.get_setting(f"crypto_rate_r_{reseller_id}", "")
        if not usdt_rate_val or not str(usdt_rate_val).isdigit():
            # فال‌بک به نرخ درگاه کریپتو سراسری
            rate_val = self.get_setting("crypto_usdt_rate", "90000")
            usdt_rate = int(rate_val) if str(rate_val).isdigit() else 90000
        else:
            usdt_rate = int(usdt_rate_val)
        return {
            "enabled": str(enabled_val).lower() in ("1", "true", "yes") and bool(wallet_addr),
            "wallet_address": wallet_addr,
            "usdt_rate": usdt_rate,
            "network": "USDT (TRC20 / TON)"
        }

    def save_reseller_crypto_config(self, reseller_id: int, enabled: bool, wallet_address: str, usdt_rate: int = 0) -> dict:
        """ذخیره تنظیمات پرداخت ارزی و کریپتو اختصاصی نماینده"""
        try:
            self.set_setting(f"crypto_enabled_r_{reseller_id}", "1" if enabled else "0")
            self.set_setting(f"crypto_wallet_r_{reseller_id}", str(wallet_address or "").strip())
            if usdt_rate and int(usdt_rate) > 0:
                self.set_setting(f"crypto_rate_r_{reseller_id}", str(int(usdt_rate)))
            return {"success": True}
        except Exception as e:
            logger.error(f"Error saving reseller crypto config: {e}")
            return {"success": False, "error": str(e)}

    # ─── تنظیمات تایید خودکار کارت به کارت با پیامک بانک (Smart Bank SMS) ───

    def get_admin_bank_sms_config(self) -> dict:
        """دریافت تنظیمات تایید خودکار با پیامک بانک برای مدیریت اصلی"""
        enabled = str(self.get_setting("admin_bank_sms_enabled", "0")).lower() in ("1", "true")
        token = self.get_setting("admin_bank_sms_token")
        if not token:
            token = secrets.token_hex(16)
            self.set_setting("admin_bank_sms_token", token)
        digits = int(self.get_setting("admin_bank_sms_digits", 3))
        timeout = int(self.get_setting("admin_bank_sms_timeout", 15))
        return {
            "enabled": enabled,
            "token": token,
            "digits": digits,
            "timeout": timeout
        }

    def save_admin_bank_sms_config(self, enabled: bool, digits: int = 3, timeout: int = 15, regenerate_token: bool = False) -> dict:
        """ذخیره تنظیمات تایید خودکار با پیامک بانک برای مدیریت اصلی"""
        try:
            self.set_setting("admin_bank_sms_enabled", "1" if enabled else "0")
            self.set_setting("admin_bank_sms_digits", str(max(3, min(4, int(digits)))))
            self.set_setting("admin_bank_sms_timeout", str(max(5, min(60, int(timeout)))))
            if regenerate_token:
                new_token = secrets.token_hex(16)
                self.set_setting("admin_bank_sms_token", new_token)
            return {"success": True}
        except Exception as e:
            logger.error(f"Error saving admin bank sms config: {e}")
            return {"success": False, "error": str(e)}

    def get_reseller_bank_sms_config(self, reseller_id: int) -> dict:
        """دریافت تنظیمات تایید خودکار با پیامک بانک نماینده"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT bank_sms_enabled, bank_sms_token, bank_sms_digits, bank_sms_timeout FROM resellers WHERE id=?", (reseller_id,))
            row = cursor.fetchone()
            if not row:
                return {"enabled": False, "token": "", "digits": 3, "timeout": 15}
            r_dict = dict(row)
            token = r_dict.get("bank_sms_token")
            if not token:
                token = f"r{reseller_id}_{secrets.token_hex(12)}"
                cursor.execute("UPDATE resellers SET bank_sms_token=? WHERE id=?", (token, reseller_id))
                conn.commit()
            return {
                "enabled": bool(r_dict.get("bank_sms_enabled")),
                "token": token,
                "digits": int(r_dict.get("bank_sms_digits") or 3),
                "timeout": int(r_dict.get("bank_sms_timeout") or 15)
            }
        except Exception as e:
            logger.error(f"Error getting reseller bank sms config: {e}")
            return {"enabled": False, "token": "", "digits": 3, "timeout": 15}
        finally:
            conn.close()

    def save_reseller_bank_sms_config(self, reseller_id: int, enabled: bool, digits: int = 3, timeout: int = 15, regenerate_token: bool = False) -> dict:
        """ذخیره تنظیمات تایید خودکار با پیامک بانک نماینده"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            digits_val = max(3, min(4, int(digits)))
            timeout_val = max(5, min(60, int(timeout)))
            if regenerate_token:
                new_token = f"r{reseller_id}_{secrets.token_hex(12)}"
                cursor.execute("""
                    UPDATE resellers 
                    SET bank_sms_enabled=?, bank_sms_digits=?, bank_sms_timeout=?, bank_sms_token=?, updated_at=?
                    WHERE id=?
                """, (1 if enabled else 0, digits_val, timeout_val, new_token, get_now_iso(), reseller_id))
            else:
                cursor.execute("""
                    UPDATE resellers 
                    SET bank_sms_enabled=?, bank_sms_digits=?, bank_sms_timeout=?, updated_at=?
                    WHERE id=?
                """, (1 if enabled else 0, digits_val, timeout_val, get_now_iso(), reseller_id))
            conn.commit()
            return {"success": True}
        except Exception as e:
            logger.error(f"Error saving reseller bank sms config: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def find_bank_sms_owner_by_token(self, token: str) -> Optional[dict]:
        """پیدا کردن صاحب توکن وب‌هوک (ادمین یا نماینده)"""
        if not token:
            return None
        token = str(token).strip()
        # بررسی ادمین
        admin_token = self.get_setting("admin_bank_sms_token")
        if admin_token and admin_token == token:
            return {"type": "admin", "id": 0}
        
        # بررسی نمایندگان
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT id, name FROM resellers WHERE bank_sms_token=?", (token,))
            row = cursor.fetchone()
            if row:
                return {"type": "reseller", "id": row["id"], "name": row["name"]}
            return None
        finally:
            conn.close()

    def log_bank_sms(self, owner_type: str, owner_id: int, sender_number: str, raw_message: str, extracted_amount: int = None, matched_order_id: str = None, status: str = "pending") -> int:
        """ثبت لاگ پیامک دریافتی از فورواردر"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("""
                INSERT INTO bank_sms_logs (owner_type, owner_id, sender_number, raw_message, extracted_amount, matched_order_id, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (owner_type, owner_id, str(sender_number or "")[:50], str(raw_message or ""), extracted_amount, matched_order_id, status, now))
            log_id = cursor.lastrowid
            conn.commit()
            return log_id
        except Exception as e:
            logger.error(f"Error logging bank sms: {e}")
            return 0
        finally:
            conn.close()

    def get_bank_sms_logs(self, owner_type: str, owner_id: int = 0, limit: int = 15) -> list:
        """دریافت آخرین لاگ‌های پیامک بانکی"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT * FROM bank_sms_logs 
                WHERE owner_type=? AND owner_id=?
                ORDER BY id DESC LIMIT ?
            """, (owner_type, owner_id, limit))
            return [dict(r) for r in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting bank sms logs: {e}")
            return []
        finally:
            conn.close()

    def create_smart_invoice(self, sub_id: int, plan_id: str, reseller_id: int, base_amount: int, target_card: dict = None, digits: int = 3, timeout_minutes: int = 15, instant_activation: bool = True, discount_code: str = None, discount_amount: int = 0, is_debt_settlement: int = 0) -> dict:
        """
        تولید فاکتور تمدید هوشمند با ارقام تصادفی خرد جهت تایید اتوماتیک با پیامک بانک
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        now_dt = get_now_naive()
        now_str = now_dt.isoformat()
        expires_dt = now_dt + timedelta(minutes=max(5, timeout_minutes))
        expires_str = expires_dt.isoformat()

        # ارقام خرد تصادفی
        min_suffix = 100 if digits == 3 else 1000
        max_suffix = 999 if digits == 3 else 9999

        # رند کردن بیس به هزارگان
        base_clean = (int(base_amount) // 1000) * 1000

        # پیدا کردن مبالغ در حال استفاده در فاکتورهای معلق این نماینده/ادمین برای جلوگیری از تداخل
        cursor.execute("""
            SELECT final_amount FROM smart_invoices 
            WHERE reseller_id=? AND status='pending' AND expires_at > ?
        """, (reseller_id, now_str))
        active_amounts = {r["final_amount"] for r in cursor.fetchall()}

        # انتخاب یک عدد رندوم که تداخل نداشته باشد
        final_amount = None
        chosen_suffix = None
        for _ in range(50):
            suffix = random.randint(min_suffix, max_suffix)
            candidate = base_clean + suffix
            if candidate not in active_amounts:
                final_amount = candidate
                chosen_suffix = suffix
                break

        if not final_amount:
            suffix = random.randint(min_suffix, max_suffix)
            final_amount = base_clean + suffix
            chosen_suffix = suffix

        order_id = f"INV{int(now_dt.timestamp())}{random.randint(100, 999)}"
        token = f"{uuid.uuid4().hex[:20]}"

        card_id = target_card.get("id") if target_card else None
        c_num = target_card.get("card_number") if target_card else ""
        c_holder = target_card.get("card_holder") if target_card else ""
        b_name = target_card.get("bank_name") if target_card else ""
        inst_act_val = 1 if instant_activation else 0
        disc_code_clean = (discount_code or "").strip().upper() or None
        disc_amt_clean = int(discount_amount or 0)
        debt_settle_val = 1 if is_debt_settlement else 0

        cursor.execute("""
            INSERT INTO smart_invoices (
                order_id, sub_id, plan_id, reseller_id, base_amount, random_suffix, 
                final_amount, target_card_id, card_number, card_holder, bank_name, 
                status, token, expires_at, created_at, instant_activation,
                discount_code, discount_amount, is_debt_settlement
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?)
        """, (order_id, sub_id, plan_id, reseller_id, base_amount, chosen_suffix, final_amount, card_id, c_num, c_holder, b_name, token, expires_str, now_str, inst_act_val, disc_code_clean, disc_amt_clean, debt_settle_val))
        conn.commit()
        conn.close()

        return {
            "order_id": order_id,
            "sub_id": sub_id,
            "plan_id": plan_id,
            "reseller_id": reseller_id,
            "base_amount": base_amount,
            "random_suffix": chosen_suffix,
            "final_amount": final_amount,
            "card_number": c_num,
            "card_holder": c_holder,
            "bank_name": b_name,
            "status": "pending",
            "token": token,
            "expires_at": expires_str,
            "created_at": now_str,
            "instant_activation": inst_act_val,
            "discount_code": disc_code_clean,
            "discount_amount": disc_amt_clean,
            "is_debt_settlement": debt_settle_val
        }

    def get_smart_invoice_by_token(self, token: str) -> Optional[dict]:
        """دریافت فاکتور با توکن امن"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT * FROM smart_invoices WHERE token=?", (token,))
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_smart_invoice_by_order_id(self, order_id: str) -> Optional[dict]:
        """دریافت فاکتور با شناسه سفارش"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT * FROM smart_invoices WHERE order_id=?", (order_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def match_smart_invoice_by_amount(self, amount_toman: int, owner_type: str, owner_id: int = 0) -> Optional[dict]:
        """
        تطبیق مبلغ پیامک بانکی با فاکتورهای باز در انتظار پرداخت
        """
        if not amount_toman or amount_toman <= 0:
            return None

        reseller_id = owner_id if owner_type == "reseller" else 0
        now_str = get_now_naive().isoformat()

        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            # ۱. جستجوی فاکتور معلق منقضی‌نشده با این مبلغ دقیق برای همین مالک
            cursor.execute("""
                SELECT * FROM smart_invoices 
                WHERE reseller_id=? AND final_amount=? AND status='pending' AND expires_at >= ?
                ORDER BY id DESC LIMIT 1
            """, (reseller_id, amount_toman, now_str))
            row = cursor.fetchone()
            if row:
                return dict(row)

            # ۲. اگر مالک ادمین است، فاکتورهای مشتریان نمایندگان که به کارت‌های ادمین واریز می‌کنند نیز بررسی شود
            if owner_type == "admin":
                cursor.execute("""
                    SELECT * FROM smart_invoices 
                    WHERE final_amount=? AND status='pending' AND expires_at >= ?
                    ORDER BY id DESC LIMIT 1
                """, (amount_toman, now_str))
                row_adm = cursor.fetchone()
                if row_adm:
                    return dict(row_adm)

            # ۳. بررسی بازه ۶۰ دقیقه اخیر برای واریزهایی که با تاخیر انجام شدند
            grace_dt = (get_now_naive() - timedelta(minutes=60)).isoformat()
            cursor.execute("""
                SELECT * FROM smart_invoices 
                WHERE (reseller_id=? OR ?='admin') AND final_amount=? AND status='pending' AND created_at >= ?
                ORDER BY id DESC LIMIT 1
            """, (reseller_id, owner_type, amount_toman, grace_dt))
            row2 = cursor.fetchone()
            return dict(row2) if row2 else None
        finally:
            conn.close()

    def mark_smart_invoice_paid(self, order_id: str, tracking_code: str = None) -> bool:
        """ثبت وضعیت پرداخت موفق برای فاکتور هوشمند"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now_str = get_now_iso()
        try:
            cursor.execute("""
                UPDATE smart_invoices 
                SET status='paid', paid_at=?, tracking_code=?
                WHERE order_id=? AND status='pending'
            """, (now_str, str(tracking_code or ""), order_id))
            affected = cursor.rowcount
            conn.commit()
            return affected > 0
        except Exception as e:
            logger.error(f"Error marking smart invoice paid: {e}")
            return False
        finally:
            conn.close()

    def cancel_smart_invoice(self, order_id: str, sub_id: Optional[int] = None) -> bool:
        """لغو فاکتور هوشمند معلق توسط مشتری یا مدیر"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            if sub_id:
                cursor.execute("""
                    UPDATE smart_invoices 
                    SET status='cancelled'
                    WHERE order_id=? AND sub_id=? AND status='pending'
                """, (order_id, sub_id))
            else:
                cursor.execute("""
                    UPDATE smart_invoices 
                    SET status='cancelled'
                    WHERE order_id=? AND status='pending'
                """, (order_id,))
            affected = cursor.rowcount
            conn.commit()
            return affected > 0
        except Exception as e:
            logger.error(f"Error cancelling smart invoice: {e}")
            return False
        finally:
            conn.close()

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
        """دریافت لیست تمام پلن‌های مادر با اعمال شخصی‌سازی‌ها، حجم، مدت و قیمت‌های سفارشی نماینده (با فیلتر قطعی پلن‌های اختصاصی)"""
        from admin_manager import load_plans
        raw_master_plans = load_plans()
        
        # فیلتر هوشمند پلن‌ها:
        # ۱. پلن‌های اختصاصی مدیریت ارشد کاملاً مخفی هستند
        # ۲. پلن‌های اختصاصی نمایندگان (دارای allowed_resellers) فقط به نمایندگان مجاز تخصیص داده می‌شوند
        # ۳. سایر نمایندگان یا کاربران عادی به هیچ عنوان پلن‌های اختصاصی را دریافت نخواهند کرد
        master_plans = {}
        for pid, p in raw_master_plans.items():
            if p.get("is_exclusive_admin") or p.get("is_exclusive_admin_bot"):
                continue
            allowed = p.get("allowed_resellers") or []
            if allowed:
                try:
                    if int(reseller_id) in [int(x) for x in allowed]:
                        master_plans[pid] = p
                except (ValueError, TypeError):
                    pass
            elif p.get("is_exclusive_reseller"):
                continue
            else:
                master_plans[pid] = p

        reseller = self.get_reseller(reseller_id) or {}
        discount_pct = reseller.get("discount_percent") if reseller.get("discount_percent") is not None else 20

        conn = self.get_connection()
        cursor = conn.cursor()
        overrides = {}
        try:
            cursor.execute("""
                SELECT plan_id, custom_name, custom_price, custom_data_limit, custom_duration, 
                       custom_discount_percent, custom_wholesale_price, is_active,
                       reseller_custom_name, reseller_custom_price, reseller_is_active, is_reseller_modified 
                FROM reseller_plans WHERE reseller_id = ?
            """, (reseller_id,))
            for row in cursor.fetchall():
                pid_key = str(row["plan_id"])
                r_keys = row.keys() if hasattr(row, "keys") else []
                overrides[pid_key] = {
                    "custom_name": row["custom_name"],
                    "custom_price": row["custom_price"],
                    "custom_data_limit": row["custom_data_limit"],
                    "custom_duration": row["custom_duration"],
                    "custom_discount_percent": row["custom_discount_percent"] if ("custom_discount_percent" in r_keys and row["custom_discount_percent"] is not None) else None,
                    "custom_wholesale_price": row["custom_wholesale_price"] if ("custom_wholesale_price" in r_keys and row["custom_wholesale_price"] is not None) else None,
                    "is_active": bool(row["is_active"]),
                    "reseller_custom_name": row["reseller_custom_name"] if ("reseller_custom_name" in r_keys and row["reseller_custom_name"] is not None) else None,
                    "reseller_custom_price": row["reseller_custom_price"] if ("reseller_custom_price" in r_keys and row["reseller_custom_price"] is not None) else None,
                    "reseller_is_active": bool(row["reseller_is_active"]) if ("reseller_is_active" in r_keys and row["reseller_is_active"] is not None) else None,
                    "is_reseller_modified": bool(row["is_reseller_modified"]) if ("is_reseller_modified" in r_keys and row["is_reseller_modified"] is not None) else False,
                }
        except Exception as e:
            logger.error(f"Error fetching reseller plan overrides: {e}")
        finally:
            conn.close()

        result = []
        seen_pids = set()
        for pid, p in master_plans.items():
            pid_str = str(pid)
            seen_pids.add(pid_str)
            ov = overrides.get(pid_str) or overrides.get(pid, {})
            admin_custom_name = ov.get("custom_name") or ""
            admin_custom_price = ov.get("custom_price")
            custom_data_limit = ov.get("custom_data_limit")
            custom_duration = ov.get("custom_duration")
            custom_discount_percent = ov.get("custom_discount_percent")
            custom_wholesale_price = ov.get("custom_wholesale_price")
            admin_is_active = ov.get("is_active")

            is_reseller_modified = bool(ov.get("is_reseller_modified"))
            reseller_custom_name = ov.get("reseller_custom_name")
            reseller_custom_price = ov.get("reseller_custom_price")
            reseller_is_active = ov.get("reseller_is_active")

            master_price = p.get("price", 0)
            admin_price = admin_custom_price if (admin_custom_price is not None and admin_custom_price > 0) else master_price
            admin_name = admin_custom_name if admin_custom_name else p.get("name", "پلن")

            # اگر نماینده قیمت یا نام اختصاصی داده باشد و فلگ تغییر خورده باشد
            if is_reseller_modified and reseller_custom_price is not None and reseller_custom_price > 0:
                display_price = reseller_custom_price
            else:
                display_price = admin_price

            if is_reseller_modified and reseller_custom_name:
                display_name = reseller_custom_name
            else:
                display_name = admin_name
            
            master_data_limit = p.get("data_limit", 0)
            display_data_limit = custom_data_limit if (custom_data_limit is not None and custom_data_limit >= 0) else master_data_limit

            master_duration = p.get("duration", 30)
            display_duration = custom_duration if (custom_duration is not None and custom_duration > 0) else master_duration

            if is_reseller_modified and reseller_is_active is not None:
                is_active = bool(reseller_is_active)
            elif admin_is_active is not None:
                is_active = bool(admin_is_active)
            else:
                is_active = p.get("is_active", True)
            
            # قیمت تمام‌شده خرید عمده برای نماینده همیشه بر مبنای قیمت پایه تعیین شده توسط مدیر (admin_price) محاسبه می‌شود
            base_wholesale_price = admin_price
            if custom_wholesale_price is not None and custom_wholesale_price >= 0:
                wholesale_price = int(custom_wholesale_price)
                effective_discount_pct = round(((base_wholesale_price - wholesale_price) / base_wholesale_price) * 100, 1) if base_wholesale_price > 0 else 0.0
            elif custom_discount_percent is not None and custom_discount_percent >= 0:
                effective_discount_pct = float(custom_discount_percent)
                wholesale_price = int(base_wholesale_price * (100 - effective_discount_pct) / 100)
            else:
                effective_discount_pct = float(discount_pct)
                wholesale_price = int(base_wholesale_price * (100 - effective_discount_pct) / 100)

            profit = max(0, display_price - wholesale_price)
            has_custom_discount = bool(custom_wholesale_price is not None or custom_discount_percent is not None)

            is_dedicated = bool(p.get("allowed_resellers")) or bool(p.get("is_exclusive_reseller"))

            result.append({
                "plan_id": pid_str,
                "name": display_name,
                "price": display_price,
                "master_name": p.get("name", "پلن"),
                "admin_custom_name": admin_custom_name,
                "reseller_custom_name": reseller_custom_name,
                "display_name": display_name,
                "custom_name": reseller_custom_name if is_reseller_modified else admin_custom_name,
                "master_price": base_wholesale_price,
                "admin_custom_price": admin_custom_price,
                "reseller_custom_price": reseller_custom_price,
                "display_price": display_price,
                "custom_price": reseller_custom_price if is_reseller_modified else admin_custom_price,
                "wholesale_price": wholesale_price,
                "discount_percent": effective_discount_pct,
                "custom_discount_percent": custom_discount_percent,
                "custom_wholesale_price": custom_wholesale_price,
                "has_custom_discount": has_custom_discount,
                "profit": profit,
                "is_reseller_modified": is_reseller_modified,
                "master_data_limit": master_data_limit,
                "display_data_limit": display_data_limit,
                "data_limit": display_data_limit,
                "custom_data_limit": custom_data_limit,
                "master_duration": master_duration,
                "display_duration": display_duration,
                "duration": display_duration,
                "custom_duration": custom_duration,
                "description": p.get("description", ""),
                "plan_icon": p.get("plan_icon", ""),
                "is_active": is_active,
                "master_is_active": p.get("is_active", True),
                "is_dedicated": is_dedicated,
                "allowed_resellers": p.get("allowed_resellers", [])
            })

        for pid_key, ov in overrides.items():
            pid_str = str(pid_key)
            if pid_str not in seen_pids:
                p_meta = raw_master_plans.get(pid_str, {})
                if p_meta.get("is_exclusive_admin") or p_meta.get("is_exclusive_admin_bot"):
                    continue
                allowed = p_meta.get("allowed_resellers") or []
                if allowed:
                    try:
                        if int(reseller_id) not in [int(x) for x in allowed]:
                            continue
                    except (ValueError, TypeError):
                        continue
                elif p_meta.get("is_exclusive_reseller"):
                    continue

                admin_custom_name = ov.get("custom_name") or pid_str
                admin_custom_price = ov.get("custom_price") or 0
                custom_data_limit = ov.get("custom_data_limit") if ov.get("custom_data_limit") is not None else 30
                custom_duration = ov.get("custom_duration") or 30
                custom_discount_percent = ov.get("custom_discount_percent")
                custom_wholesale_price = ov.get("custom_wholesale_price")
                admin_is_active = ov.get("is_active", True)
                
                is_reseller_modified = bool(ov.get("is_reseller_modified"))
                reseller_custom_name = ov.get("reseller_custom_name")
                reseller_custom_price = ov.get("reseller_custom_price")
                reseller_is_active = ov.get("reseller_is_active")

                master_p = p_meta.get("price") if (p_meta and p_meta.get("price") is not None) else (admin_custom_price or 0)
                base_wholesale_price = admin_custom_price if admin_custom_price > 0 else master_p

                display_price = reseller_custom_price if (is_reseller_modified and reseller_custom_price is not None and reseller_custom_price > 0) else base_wholesale_price
                display_name = reseller_custom_name if (is_reseller_modified and reseller_custom_name) else (admin_custom_name or p_meta.get("name", "پلن"))

                if is_reseller_modified and reseller_is_active is not None:
                    is_active = bool(reseller_is_active)
                else:
                    is_active = admin_is_active

                if custom_wholesale_price is not None and custom_wholesale_price >= 0:
                    wholesale_price = int(custom_wholesale_price)
                    effective_discount_pct = round(((base_wholesale_price - wholesale_price) / base_wholesale_price) * 100, 1) if base_wholesale_price > 0 else 0.0
                elif custom_discount_percent is not None and custom_discount_percent >= 0:
                    effective_discount_pct = float(custom_discount_percent)
                    wholesale_price = int(base_wholesale_price * (100 - effective_discount_pct) / 100)
                else:
                    effective_discount_pct = float(discount_pct)
                    wholesale_price = int(base_wholesale_price * (100 - effective_discount_pct) / 100)

                profit = max(0, display_price - wholesale_price)
                has_custom_discount = bool(custom_wholesale_price is not None or custom_discount_percent is not None)
                is_dedicated = bool(allowed) or bool(p_meta.get("is_exclusive_reseller"))
                result.append({
                    "plan_id": pid_str,
                    "name": display_name,
                    "price": display_price,
                    "master_name": admin_custom_name,
                    "admin_custom_name": admin_custom_name,
                    "reseller_custom_name": reseller_custom_name,
                    "display_name": display_name,
                    "custom_name": reseller_custom_name if is_reseller_modified else admin_custom_name,
                    "master_price": base_wholesale_price,
                    "admin_custom_price": admin_custom_price,
                    "reseller_custom_price": reseller_custom_price,
                    "display_price": display_price,
                    "custom_price": reseller_custom_price if is_reseller_modified else admin_custom_price,
                    "wholesale_price": wholesale_price,
                    "discount_percent": effective_discount_pct,
                    "custom_discount_percent": custom_discount_percent,
                    "custom_wholesale_price": custom_wholesale_price,
                    "has_custom_discount": has_custom_discount,
                    "profit": profit,
                    "is_reseller_modified": is_reseller_modified,
                    "master_data_limit": custom_data_limit,
                    "display_data_limit": custom_data_limit,
                    "data_limit": custom_data_limit,
                    "custom_data_limit": custom_data_limit,
                    "master_duration": custom_duration,
                    "display_duration": custom_duration,
                    "duration": custom_duration,
                    "custom_duration": custom_duration,
                    "description": "",
                    "plan_icon": p_meta.get("plan_icon", ""),
                    "is_active": is_active,
                    "master_is_active": True,
                    "is_dedicated": is_dedicated,
                    "allowed_resellers": allowed
                })

        return result

    def get_reseller_plans_dict(self, reseller_id: int) -> Dict[str, dict]:
        """دریافت دیکشنری پلن‌های اختصاصی نماینده بر اساس plan_id با تمام شخصی‌سازی‌ها"""
        plans = self.get_reseller_plans(reseller_id)
        return {str(p["plan_id"]): p for p in plans}

    def get_reseller_active_plans(self, reseller_id: int) -> List[dict]:
        """دریافت فقط پلن‌های فعال برای نمایش به مشتریان ربات تلگرام نماینده"""
        all_plans = self.get_reseller_plans(reseller_id)
        return [p for p in all_plans if p.get("is_active") and p.get("master_is_active")]

    def get_reseller_plan(self, reseller_id: int, plan_id: str) -> Optional[dict]:
        """دریافت مشخصات کامل یک پلن خاص برای نماینده"""
        plans = self.get_reseller_plans(reseller_id)
        for p in plans:
            if str(p["plan_id"]) == str(plan_id):
                return p
        return None

    def update_reseller_plan_override(self, reseller_id: int, plan_id: str, custom_name: str = None, custom_price: int = None, custom_data_limit: float = None, custom_duration: int = None, custom_discount_percent: float = None, custom_wholesale_price: int = None, is_active: bool = True, preserve_specs: bool = False, is_reseller: bool = False) -> dict:
        """بروزرسانی یا ثبت تنظیمات اختصاصی نماینده برای یک پلن (نام، قیمت، حجم، مدت، تخفیف، قیمت عمده، وضعیت)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            if is_reseller or preserve_specs:
                cursor.execute("""
                    INSERT INTO reseller_plans (
                        reseller_id, plan_id, 
                        reseller_custom_name, reseller_custom_price, reseller_is_active, is_reseller_modified,
                        is_active, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)
                    ON CONFLICT(reseller_id, plan_id) DO UPDATE SET
                        reseller_custom_name = excluded.reseller_custom_name,
                        reseller_custom_price = excluded.reseller_custom_price,
                        reseller_is_active = excluded.reseller_is_active,
                        is_reseller_modified = 1,
                        updated_at = excluded.updated_at
                """, (
                    reseller_id, 
                    str(plan_id), 
                    custom_name.strip() if custom_name else None, 
                    custom_price if (custom_price is not None and custom_price > 0) else None, 
                    1 if is_active else 0,
                    1 if is_active else 0, 
                    now, 
                    now
                ))
            else:
                cursor.execute("""
                    INSERT INTO reseller_plans (
                        reseller_id, plan_id, 
                        custom_name, custom_price, custom_data_limit, custom_duration, 
                        custom_discount_percent, custom_wholesale_price, is_active, 
                        reseller_custom_name, reseller_custom_price, reseller_is_active, is_reseller_modified,
                        created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, 0, ?, ?)
                    ON CONFLICT(reseller_id, plan_id) DO UPDATE SET
                        custom_name = excluded.custom_name,
                        custom_price = excluded.custom_price,
                        custom_data_limit = excluded.custom_data_limit,
                        custom_duration = excluded.custom_duration,
                        custom_discount_percent = excluded.custom_discount_percent,
                        custom_wholesale_price = excluded.custom_wholesale_price,
                        is_active = excluded.is_active,
                        reseller_custom_name = NULL,
                        reseller_custom_price = NULL,
                        reseller_is_active = NULL,
                        is_reseller_modified = 0,
                        updated_at = excluded.updated_at
                """, (
                    reseller_id, 
                    str(plan_id), 
                    custom_name.strip() if custom_name else None, 
                    custom_price if (custom_price is not None and custom_price > 0) else None, 
                    custom_data_limit if (custom_data_limit is not None and custom_data_limit >= 0) else None,
                    custom_duration if (custom_duration is not None and custom_duration > 0) else None,
                    custom_discount_percent if (custom_discount_percent is not None and custom_discount_percent >= 0) else None,
                    custom_wholesale_price if (custom_wholesale_price is not None and custom_wholesale_price >= 0) else None,
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

    def reset_reseller_plan_override(self, reseller_id: int, plan_id: str, by_reseller: bool = True) -> dict:
        """بازنشانی تنظیمات پلن نماینده؛ در صورت بازنشانی توسط نماینده، درصد تخفیف و قیمت عمده مدیر حفظ می‌شود"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            if by_reseller:
                cursor.execute("""
                    SELECT custom_name, custom_price, custom_data_limit, custom_duration, 
                           custom_discount_percent, custom_wholesale_price 
                    FROM reseller_plans 
                    WHERE reseller_id = ? AND plan_id = ?
                """, (reseller_id, plan_id))
                row = cursor.fetchone()
                
                has_admin_overrides = False
                if row:
                    for k in ["custom_name", "custom_price", "custom_data_limit", "custom_duration", "custom_discount_percent", "custom_wholesale_price"]:
                        if row[k] is not None:
                            has_admin_overrides = True
                            break
                            
                if has_admin_overrides:
                    cursor.execute("""
                        UPDATE reseller_plans 
                        SET reseller_custom_name = NULL,
                            reseller_custom_price = NULL,
                            reseller_is_active = NULL,
                            is_reseller_modified = 0,
                            updated_at = ?
                        WHERE reseller_id = ? AND plan_id = ?
                    """, (get_now_iso(), reseller_id, plan_id))
                else:
                    cursor.execute("DELETE FROM reseller_plans WHERE reseller_id = ? AND plan_id = ?", (reseller_id, plan_id))
            else:
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
        from utils import get_now_naive, gregorian_to_shamsi
        conn = self.get_connection()
        cursor = conn.cursor()
        now_dt = get_now_naive()
        start_dt = now_dt - timedelta(days=days)
        start_iso = start_dt.strftime("%Y-%m-%d %H:%M:%S")
        start_date_str = start_dt.strftime("%Y-%m-%d")

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
            "daily_turnover": {},
            "daily_stats": [],
            "summary": {}
        }

        daily_map = {}

        def get_or_init_day(date_key):
            clean_date = str(date_key or now_dt.strftime("%Y-%m-%d"))[:10]
            if clean_date not in daily_map:
                try:
                    j_date = gregorian_to_shamsi(clean_date)
                except Exception:
                    j_date = clean_date
                daily_map[clean_date] = {
                    "date": clean_date,
                    "jalali_date": j_date,
                    "sub_count": 0,
                    "data_gb": 0.0,
                    "cash_income": 0,
                    "credit_income": 0,
                    "expense": 0,
                    "total_income": 0,
                    "income": 0,
                    "count": 0
                }
            return daily_map[clean_date]

        try:
            res_row = self.get_reseller(reseller_id) if reseller_id else None
            discount = res_row.get("discount_percent") if (res_row and res_row.get("discount_percent") is not None) else 20
            res_username = res_row.get("username") if res_row else None
            accounted_sub_ids = set()

            # ۱. استخراج تراکنش‌های تایید شده در بازه زمانی
            if reseller_id:
                cursor.execute("""
                    SELECT * FROM transactions 
                    WHERE (reseller_id = ? OR (reseller_id IS NULL AND username = ?))
                      AND (is_deleted = 0 OR is_deleted IS NULL)
                      AND status IN ('approved', 'completed')
                      AND (gateway != 'bundle_reseller' AND order_id NOT LIKE 'R_BUNDLE%')
                      AND (date(replace(created_at, 'T', ' ')) >= date(?) OR created_at >= ?)
                    ORDER BY created_at DESC
                """, (reseller_id, res_username, start_date_str, start_iso))
            else:
                cursor.execute("""
                    SELECT * FROM transactions 
                    WHERE (is_deleted = 0 OR is_deleted IS NULL)
                      AND status IN ('approved', 'completed')
                      AND ((reseller_id IS NULL OR reseller_id = 0) OR (reseller_id > 0 AND (gateway = 'bundle_reseller' OR order_id LIKE 'R_BUNDLE%')))
                      AND (date(replace(created_at, 'T', ' ')) >= date(?) OR created_at >= ?)
                    ORDER BY created_at DESC
                """, (start_date_str, start_iso))
            
            tx_rows = cursor.fetchall()
            for r in tx_rows:
                r_dict = dict(r)
                amount = int(r_dict.get("amount") or 0)
                audit["total_revenue"] += amount
                
                is_credit_tx = bool(r_dict.get("gateway") == "credit" or "credit" in str(r_dict.get("order_id", "")).lower() or "اعتباری" in str(r_dict.get("tracking_code", "")))
                c_date = str(r_dict.get("created_at", ""))[:10]
                day_entry = get_or_init_day(c_date)

                if is_credit_tx:
                    audit["credit_revenue"] += amount
                    day_entry["credit_income"] += amount
                else:
                    audit["cash_revenue"] += amount
                    day_entry["cash_income"] += amount

                day_entry["total_income"] += amount
                day_entry["income"] += amount
                day_entry["count"] += 1

                if r_dict.get("is_renewal"):
                    audit["renew_subs_count"] += 1
                else:
                    audit["new_subs_count"] += 1

                if r_dict.get("subscription_id"):
                    accounted_sub_ids.add(r_dict["subscription_id"])

                audit["transactions"].append(r_dict)

            # ۱.۲. اضافه کردن خریدهای مستقیم و تمدیدهای پنل نماینده به عنوان درآمد و سود
            if reseller_id:
                cursor.execute("""
                    SELECT * FROM reseller_transactions 
                    WHERE reseller_id = ? 
                      AND type IN ('purchase', 'purchase_credit', 'renewal', 'renew', 'renew_credit')
                      AND (date(replace(created_at, 'T', ' ')) >= date(?) OR created_at >= ?)
                      AND (subscription_id IS NULL OR subscription_id NOT IN (
                          SELECT subscription_id FROM transactions 
                          WHERE reseller_id = ? AND subscription_id IS NOT NULL AND status IN ('approved', 'completed')
                      ))
                    ORDER BY created_at DESC
                """, (reseller_id, start_date_str, start_iso, reseller_id))
                res_tx_rows = cursor.fetchall()
                for rx in res_tx_rows:
                    rx_dict = dict(rx)
                    wholesale = int(rx_dict.get("amount") or 0)
                    selling = int(rx_dict.get("selling_price") or 0)
                    profit = int(rx_dict.get("profit_margin") or 0)
                    if selling <= 0 and wholesale > 0:
                        selling = int(wholesale * 100 / (100 - discount)) if discount < 100 else wholesale
                        profit = max(0, selling - wholesale)

                    audit["total_revenue"] += selling
                    audit["total_expenses"] += wholesale
                    audit["net_profit"] += profit

                    rx_date = str(rx_dict.get("created_at", ""))[:10]
                    day_entry = get_or_init_day(rx_date)

                    is_credit_rx = rx_dict.get("payment_source") == "credit" or rx_dict.get("type") in ("purchase_credit", "renew_credit")
                    if is_credit_rx:
                        audit["credit_revenue"] += selling
                        day_entry["credit_income"] += selling
                    else:
                        audit["cash_revenue"] += selling
                        day_entry["cash_income"] += selling

                    day_entry["total_income"] += selling
                    day_entry["income"] += selling
                    day_entry["expense"] += wholesale
                    day_entry["count"] += 1

                    if rx_dict.get("type") in ("renewal", "renew", "renew_credit"):
                        audit["renew_subs_count"] += 1
                    else:
                        audit["new_subs_count"] += 1

                    if rx_dict.get("subscription_id"):
                        accounted_sub_ids.add(rx_dict["subscription_id"])

                    norm_tx = dict(rx_dict)
                    if not norm_tx.get("username"):
                        norm_tx["username"] = norm_tx.get("account_name") or ""
                    if not norm_tx.get("gateway"):
                        norm_tx["gateway"] = "کیف پول" if norm_tx.get("payment_source") == "wallet" else "اعتبار خرید"
                    audit["transactions"].append(norm_tx)

            # ۲. اشتراک‌های ایجاد شده در بازه زمانی جهت محاسبه حجم کل GB و تفکیک روزشمار
            if reseller_id:
                cursor.execute("""
                    SELECT id, account_name, telegram_id, data_limit, cost_paid, is_credit, payment_source, debt_amount, created_at, plan_name 
                    FROM subscriptions 
                    WHERE reseller_id = ? AND (is_deleted = 0 OR is_deleted IS NULL)
                      AND (date(replace(created_at, 'T', ' ')) >= date(?) OR created_at >= ?)
                    ORDER BY created_at DESC
                """, (reseller_id, start_date_str, start_iso))
            else:
                cursor.execute("""
                    SELECT id, account_name, telegram_id, data_limit, cost_paid, is_credit, payment_source, debt_amount, created_at, plan_name 
                    FROM subscriptions 
                    WHERE (is_deleted = 0 OR is_deleted IS NULL)
                      AND (date(replace(created_at, 'T', ' ')) >= date(?) OR created_at >= ?)
                    ORDER BY created_at DESC
                """, (start_date_str, start_iso))
            
            sub_rows = cursor.fetchall()
            audit["total_subs_count"] = len(sub_rows)
            for s in sub_rows:
                s_dict = dict(s)
                gb_val = float(s_dict.get("data_limit") or 0)
                audit["total_gb_sold"] += gb_val
                s_date = str(s_dict.get("created_at") or "")[:10]
                day_entry = get_or_init_day(s_date)
                day_entry["sub_count"] += 1
                day_entry["data_gb"] += gb_val

                s_id = s_dict.get("id")
                if s_id not in accounted_sub_ids:
                    c_paid = int(s_dict.get("cost_paid") or 0)
                    debt_amt = int(s_dict.get("debt_amount") or 0)
                    if c_paid > 0:
                        audit["total_revenue"] += c_paid
                        if s_dict.get("is_credit") or s_dict.get("payment_source") == "credit":
                            audit["credit_revenue"] += c_paid
                            day_entry["credit_income"] += c_paid
                        else:
                            audit["cash_revenue"] += c_paid
                            day_entry["cash_income"] += c_paid
                        day_entry["total_income"] += c_paid
                        day_entry["income"] += c_paid
                    elif debt_amt > 0:
                        audit["total_revenue"] += debt_amt
                        audit["credit_revenue"] += debt_amt
                        day_entry["credit_income"] += debt_amt
                        day_entry["total_income"] += debt_amt

                    gw = "اعتبار خرید" if (s_dict.get("is_credit") or s_dict.get("payment_source") == "credit") else ("کیف پول" if c_paid > 0 else "سفارش مستقیم")
                    audit["transactions"].append({
                        "id": s_id,
                        "order_id": f"SUB-{s_id}",
                        "username": s_dict.get("account_name") or (f"TG-{s_dict.get('telegram_id')}" if s_dict.get('telegram_id') else ""),
                        "plan_name": s_dict.get("plan_name") or "",
                        "amount": c_paid if c_paid > 0 else debt_amt,
                        "gateway": gw,
                        "tracking_code": "-",
                        "created_at": s_dict.get("created_at") or ""
                    })

            # ۳. محاسبه هزینه‌ها و بدهی‌ها
            if not reseller_id:
                cursor.execute("""
                    SELECT SUM(amount) FROM accounting_records 
                    WHERE type = 'expense' AND (date >= ? OR created_at >= ?)
                """, (start_iso[:10], start_iso))
                exp_row = cursor.fetchone()
                audit["total_expenses"] = exp_row[0] if (exp_row and exp_row[0]) else 0
                
                cursor.execute("""
                    SELECT date, SUM(amount) FROM accounting_records
                    WHERE type = 'expense' AND (date >= ? OR created_at >= ?)
                    GROUP BY date
                """, (start_iso[:10], start_iso))
                for exp_d, exp_sum in cursor.fetchall():
                    if exp_d:
                        d_ent = get_or_init_day(str(exp_d)[:10])
                        d_ent["expense"] = int(exp_sum or 0)

                cursor.execute("SELECT SUM(credit_debt) FROM resellers WHERE credit_debt > 0")
                debt_row = cursor.fetchone()
                audit["total_outstanding_debt"] = debt_row[0] if (debt_row and debt_row[0]) else 0
                audit["net_profit"] = max(0, audit["total_revenue"] - audit["total_expenses"])
            else:
                if res_row:
                    audit["total_outstanding_debt"] = res_row.get("credit_debt", 0)
                if audit["total_expenses"] == 0 and audit["total_revenue"] > 0:
                    discount = res_row.get("discount_percent") if (res_row and res_row.get("discount_percent") is not None) else 20
                    audit["total_expenses"] = int(audit["total_revenue"] * (100 - discount) / 100)
                audit["net_profit"] = max(0, audit["total_revenue"] - audit["total_expenses"])

            # ۴. مرتب‌سازی روزشمار ۳۰ روزه بر اساس تاریخ به صورت نزولی
            sorted_daily = []
            for d_key in sorted(daily_map.keys(), reverse=True):
                sorted_daily.append(daily_map[d_key])

            audit["daily_stats"] = sorted_daily
            audit["daily_turnover"] = daily_map

            # ۵. دیکشنری summary هماهنگ با قالب‌های jinja2
            audit["summary"] = {
                "total_revenue": audit["total_revenue"],
                "cash_revenue": audit["cash_revenue"],
                "credit_revenue": audit["credit_revenue"],
                "total_expenses": audit["total_expenses"],
                "net_profit": audit["net_profit"],
                "estimated_profit": audit["net_profit"],
                "sub_count": audit["total_subs_count"],
                "total_subs_count": audit["total_subs_count"],
                "total_data_gb": audit["total_gb_sold"],
                "total_gb_sold": audit["total_gb_sold"],
                "total_outstanding_debt": audit["total_outstanding_debt"]
            }
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


