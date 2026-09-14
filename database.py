#!/usr/bin/env python3
"""
Ù…Ø§Ú˜ÙˆÙ„ Ø¯ÛŒØªØ§Ø¨ÛŒØ³ Ø¨Ø±Ø§ÛŒ Ø°Ø®ÛŒØ±Ù‡â€ŒØ³Ø§Ø²ÛŒ Ù…Ø´ØªØ±ÛŒØ§Ù†ØŒ ØªÙ†Ø¸ÛŒÙ…Ø§Øª Ùˆ ØªØ±Ø§Ú©Ù†Ø´â€ŒÙ‡Ø§
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

# Ù…Ø³ÛŒØ± Ø¯ÛŒØªØ§Ø¨ÛŒØ³ - Ø§Ø² Railway persistent storage ÛŒØ§ Ù…ØªØºÛŒØ± Ù…Ø­ÛŒØ·ÛŒ Ø§Ø³ØªÙØ§Ø¯Ù‡ Ù…ÛŒÚ©Ù†Ù‡
# Railway: Ø§Ú¯Ø± Volume Ø¯Ø§Ø±ÛŒØ¯ØŒ DATA_DIR=/data ØªÙ†Ø¸ÛŒÙ… Ú©Ù†ÛŒØ¯
# Ø¯Ø± ØºÛŒØ± Ø§ÛŒÙ† ØµÙˆØ±ØªØŒ Ø¯ÛŒØªØ§Ø¨ÛŒØ³ Ø¯Ø± Ù…Ø³ÛŒØ± Ù¾Ø±ÙˆÚ˜Ù‡ Ø°Ø®ÛŒØ±Ù‡ Ù…ÛŒØ´Ù‡
POSSIBLE_PATHS = []

# Û±. Ù…ØªØºÛŒØ± Ù…Ø­ÛŒØ·ÛŒ Ø§Ø®ØªØµØ§ØµÛŒ (Ø¨Ø§Ù„Ø§ØªØ±ÛŒÙ† Ø§ÙˆÙ„ÙˆÛŒØª Ø¨Ø±Ø§ÛŒ Railway Volume ÛŒØ§ Docker Mount)
data_dir_env = os.environ.get("DATA_DIR", "").strip()
if data_dir_env:
    if not (os.name == "nt" and data_dir_env.startswith("/")):
        POSSIBLE_PATHS.append(Path(data_dir_env))

# Û². Ø§Ú¯Ø± Ø¯ÛŒØªØ§Ø¨ÛŒØ³ Ø¯Ø± Ù¾ÙˆØ´Ù‡ Ø¯ÛŒØªØ§ÛŒ Ù¾Ø±ÙˆÚ˜Ù‡ Ø§Ø² Ù‚Ø¨Ù„ ÙˆØ¬ÙˆØ¯ Ø¯Ø§Ø±Ø¯ (ÙˆÛŒÙ†Ø¯ÙˆØ² ÛŒØ§ Ø³Ø±ÙˆØ± Ù„ÛŒÙ†ÙˆÚ©Ø³ VPS)
if Path("data/bot_database.db").exists():
    POSSIBLE_PATHS.append(Path("data"))

# Û³. Ø§Ú¯Ø± Ø¯ÛŒØªØ§Ø¨ÛŒØ³ Ø¯Ø± Ù…Ø³ÛŒØ± Ù¾ÛŒØ´â€ŒÙØ±Ø¶ Railway (/data/bot_database.db) ÙˆØ¬ÙˆØ¯ Ø¯Ø§Ø±Ø¯
if os.name != "nt" and Path("/data/bot_database.db").exists():
    POSSIBLE_PATHS.append(Path("/data"))

# Û´. Ù¾ÙˆØ´Ù‡ Ù¾ÛŒØ´â€ŒÙØ±Ø¶ Ø¯ÛŒØªØ§ÛŒ Ù¾Ø±ÙˆÚ˜Ù‡
POSSIBLE_PATHS.append(Path("data"))

# Ûµ. Ø³Ø§ÛŒØ± Ù…Ø³ÛŒØ±Ù‡Ø§ÛŒ Ù¾Ø§ÛŒØ¯Ø§Ø± Ù„ÛŒÙ†ÙˆÚ©Ø³ Ùˆ Ù‡ÙˆÙ… Ø¯Ø§ÛŒØ±Ú©ØªÙˆØ±ÛŒ Ø¨Ù‡ Ø¹Ù†ÙˆØ§Ù† ÙØ§Ù„â€ŒØ¨Ú©
if os.name != "nt":
    POSSIBLE_PATHS.append(Path("/data"))

POSSIBLE_PATHS.append(Path(os.path.expanduser("~/.vpn-bot/data")))

DB_DIR = None
for path in POSSIBLE_PATHS:
    if path and path != Path(""):
        try:
            path.mkdir(parents=True, exist_ok=True)
            # ØªØ³Øª Ù†ÙˆØ´ØªÙ†
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
    """Ú©Ù„Ø§Ø³ Ù…Ø¯ÛŒØ±ÛŒØª Ø¯ÛŒØªØ§Ø¨ÛŒØ³"""

    def __init__(self, db_path=None):
        self.db_dir = DB_DIR
        self.db_path = db_path or DB_PATH
        self.init_db()
        self.migrate_add_columns()

    def get_connection(self):
        """Ø¯Ø±ÛŒØ§ÙØª Ø§ØªØµØ§Ù„ Ø¯ÛŒØªØ§Ø¨ÛŒØ³"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def init_db(self):
        """Ø§ÛŒØ¬Ø§Ø¯ Ø¬Ø¯Ø§ÙˆÙ„ Ø¯ÛŒØªØ§Ø¨ÛŒØ³"""
        conn = self.get_connection()
        cursor = conn.cursor()

        # Ø¬Ø¯ÙˆÙ„ Ù…Ø´ØªØ±ÛŒØ§Ù†
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

        # Ø¬Ø¯ÙˆÙ„ Ø§Ø´ØªØ±Ø§Ú©â€ŒÙ‡Ø§
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

        # Ø¬Ø¯ÙˆÙ„ ØªØ±Ø§Ú©Ù†Ø´â€ŒÙ‡Ø§
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

        # Ø¬Ø¯ÙˆÙ„ ØªÙ†Ø¸ÛŒÙ…Ø§Øª
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TEXT
            )
        """)

        # Ø¬Ø¯ÙˆÙ„ Ù¾Ø´ØªÛŒØ¨Ø§Ù†â€ŒÙ‡Ø§
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS backups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                backup_file TEXT,
                backup_size INTEGER,
                created_at TEXT,
                uploaded BOOLEAN DEFAULT 0
            )
        """)

        # Ø¬Ø¯ÙˆÙ„ Ú©ÛŒÙ Ù¾ÙˆÙ„
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

        # Ø¬Ø¯ÙˆÙ„ Ú©Ø¯Ù‡Ø§ÛŒ ØªØ®ÙÛŒÙ
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

        # Ø¬Ø¯ÙˆÙ„ Ø¨Ù„Ø§Ú© Ù„ÛŒØ³Øª
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS blocked_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE NOT NULL,
                reason TEXT,
                blocked_by INTEGER,
                created_at TEXT
            )
        """)

        # Ø¬Ø¯ÙˆÙ„ ØªÛŒÚ©Øªâ€ŒÙ‡Ø§ÛŒ Ù¾Ø´ØªÛŒØ¨Ø§Ù†ÛŒ
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

        # Ø¬Ø¯ÙˆÙ„ Ù¾ÛŒØ§Ù…â€ŒÙ‡Ø§ÛŒ Ø²Ù†Ø¬ÛŒØ±Ù‡ Ú¯ÙØªÚ¯ÙˆÛŒ ØªÛŒÚ©Øªâ€ŒÙ‡Ø§ (Ticket Messages / Thread)
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

        # Ø¬Ø¯ÙˆÙ„ Ø§Ø¹Ù„Ø§Ù†â€ŒÙ‡Ø§ÛŒ Ø§Ø±Ø³Ø§Ù„ Ø´Ø¯Ù‡
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

        # Ø¬Ø¯ÙˆÙ„ Ø±ÙØ±Ø§Ù„ Ùˆ Ù…Ø¹Ø±ÙÛŒ
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

        # Ø¬Ø¯ÙˆÙ„ Ù‡Ù…Ú©Ø§Ø±Ø§Ù† Ùˆ Ù†Ù…Ø§ÛŒÙ†Ø¯Ú¯Ø§Ù† ÙØ±ÙˆØ´ (Resellers)
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

        # Ø¬Ø¯ÙˆÙ„ ØªØ±Ø§Ú©Ù†Ø´â€ŒÙ‡Ø§ÛŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ú¯Ø§Ù†
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

        # Ø¬Ø¯ÙˆÙ„ Ù¾Ù„Ù†â€ŒÙ‡Ø§ÛŒ Ø³ÙØ§Ø±Ø´ÛŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ (Ù†Ø§Ù… Ù†Ù…Ø§ÛŒØ´ÛŒØŒ Ù‚ÛŒÙ…Øª Ø³ÙØ§Ø±Ø´ÛŒØŒ ÙØ¹Ø§Ù„/ØºÛŒØ±ÙØ¹Ø§Ù„)
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

        # Ø¬Ø¯ÙˆÙ„ Ø§Ø¹Ù„Ø§Ù†â€ŒÙ‡Ø§ Ùˆ Ù¾ÛŒØ§Ù…â€ŒÙ‡Ø§ÛŒ Ø³ÛŒØ³ØªÙ…ÛŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ (ØªØ§ÛŒÛŒØ¯/Ø±Ø¯ ÙÛŒØ´ØŒ ØªØºÛŒÛŒØ±Ø§Øª Ø­Ø³Ø§Ø¨)
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

        # Ø¬Ø¯ÙˆÙ„ Ú©Ø§Ø±Øªâ€ŒÙ‡Ø§ÛŒ Ø¨Ø§Ù†Ú©ÛŒ Ù…Ù‚ØµØ¯
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

        # Ø¬Ø¯ÙˆÙ„ Ø³Ø§Ø¨Ù‚Ù‡ Ùˆ ØªØ§Ø±ÛŒØ®Ú†Ù‡ Ù…ØµØ±Ù Ø¯ÙˆØ±Ù‡â€ŒÙ‡Ø§ÛŒ Ú¯Ø°Ø´ØªÙ‡ Ø§Ø´ØªØ±Ø§Ú©â€ŒÙ‡Ø§ Ù‡Ù†Ú¯Ø§Ù… ØªÙ…Ø¯ÛŒØ¯ ÛŒØ§ Ø«Ø¨Øª Ø¯Ø³ØªÛŒ
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

        # Ø¬Ø¯ÙˆÙ„ Ø§Ø³Ù†Ø§Ø¯ Ø­Ø³Ø§Ø¨Ø¯Ø§Ø±ÛŒ Ùˆ Ù…Ø¯ÛŒØ±ÛŒØª Ù…Ø§Ù„ÛŒ Ù¾ÛŒØ´Ø±ÙØªÙ‡ (Ø¯Ø±Ø¢Ù…Ø¯Ù‡Ø§ Ùˆ Ù…Ø®Ø§Ø±Ø¬)
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

        # Ø¬Ø¯ÙˆÙ„ Ù…Ø¯ÛŒØ±Ø§Ù† Ù¾Ù†Ù„ Ùˆ Ø³Ø·ÙˆØ­ Ø¯Ø³ØªØ±Ø³ÛŒ (RBAC)
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

        # Ø¬Ø¯ÙˆÙ„ Ù„Ø§Ú¯ Ø­Ø³Ø§Ø¨Ø±Ø³ÛŒ Ùˆ Ø±Ø¯Ù¾Ø§ÛŒ ØªØºÛŒÛŒØ±Ø§Øª ØªØ±Ø§Ú©Ù†Ø´â€ŒÙ‡Ø§ (Audit Logs)
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

        # Ø¬Ø¯ÙˆÙ„ Ù„Ø§Ú¯ ÙˆØ±ÙˆØ¯ØŒ Ø®Ø±ÙˆØ¬ØŒ Ù†Ø´Ø³Øªâ€ŒÙ‡Ø§ÛŒ ÙØ¹Ø§Ù„ Ùˆ Ø§Ù…Ù†ÛŒØª (Login & Security Logs)
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

        # Ø¬Ø¯ÙˆÙ„ Ø«Ø¨Øª ÙˆÙ‚Ø§ÛŒØ¹ Ùˆ Ø­Ø³Ø§Ø¨Ø±Ø³ÛŒ Ø¬Ø§Ù…Ø¹ Ø³ÛŒØ³ØªÙ… (System Activity & Audit Logs)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS system_activity_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,          -- 'system', 'admin', 'reseller', 'user_bot', 'security'
                action TEXT NOT NULL,            -- 'purge', 'delete', 'restore', 'create', 'update', 'renew', 'sync', 'sync_diff', 'login', 'backup', 'settings_change', 'bulk_action', 'status_change', etc.
                title TEXT NOT NULL,             -- Ø®Ù„Ø§ØµÙ‡ Ø¹Ù†ÙˆØ§Ù† Ø¹Ù…Ù„ÛŒØ§Øª
                description TEXT,                -- Ø´Ø±Ø­ ØªÙØµÛŒÙ„ÛŒ Ø±ÙˆÛŒØ¯Ø§Ø¯
                actor_type TEXT NOT NULL,        -- 'system', 'admin', 'reseller', 'bot', 'user'
                actor_id INTEGER,               -- Ø´Ù†Ø§Ø³Ù‡ Ø¹Ø§Ù…Ù„
                actor_name TEXT,                 -- Ù†Ø§Ù… ÛŒØ§ Ù†Ø§Ù… Ú©Ø§Ø±Ø¨Ø±ÛŒ Ø¹Ø§Ù…Ù„
                target_type TEXT,                -- Ù…ÙˆØ¬ÙˆØ¯ÛŒØª Ù‡Ø¯Ù: 'subscription', 'user', 'reseller', 'setting', 'payment', 'system'
                target_id INTEGER,               -- Ø´Ù†Ø§Ø³Ù‡ Ù‡Ø¯Ù (Ù…Ø«Ù„ sub_id)
                target_name TEXT,                -- Ø¹Ù†ÙˆØ§Ù† ÛŒØ§ Ù†Ø§Ù… Ù‡Ø¯Ù (Ù…Ø«Ù„ account_name ÛŒØ§ UUID)
                details TEXT,                    -- Ø§Ø·Ù„Ø§Ø¹Ø§Øª Ø¬Ø²Ø¦ÛŒ Ø¨Ø§ ÙØ±Ù…Øª JSON
                level TEXT DEFAULT 'info',       -- 'info', 'success', 'warning', 'danger'
                ip_address TEXT,                 -- Ø¢Ø¯Ø±Ø³ IP Ø¹Ø§Ù…Ù„ Ø¯Ø± ØµÙˆØ±Øª ÙˆØ¬ÙˆØ¯
                created_at TEXT NOT NULL         -- Ø²Ù…Ø§Ù† Ø§ÛŒØ²Ùˆ ØªÙ‡Ø±Ø§Ù†
            )
        """)

        # Ù…Ø§ÛŒÚ¯Ø±ÛŒØ´Ù† Ø®ÙˆØ¯Ú©Ø§Ø± Ø§ÛŒÙ†Ø¯Ú©Ø³â€ŒÙ‡Ø§ Ùˆ Ø³ØªÙˆÙ†â€ŒÙ‡Ø§ÛŒ Ø¬Ø¯ÛŒØ¯
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

        # ØªØµØ­ÛŒØ­ Ùˆ Ù‡Ù…Ú¯Ø§Ù…â€ŒØ³Ø§Ø²ÛŒ Ø®ÙˆØ¯Ú©Ø§Ø± Ù…Ø¨Ø¯Ø£ Ùˆ Ù†Ø§Ù… Ù…Ø´ØªØ±ÛŒ Ø¨Ø±Ø§ÛŒ ØªØ±Ø§Ú©Ù†Ø´â€ŒÙ‡Ø§ÛŒ Ù¾ÛŒØ´ÛŒÙ†
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
                WHERE (username IS NULL OR username = '' OR username = 'Ú©Ø§Ø±Ø¨Ø±') 
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

        # Ø³ØªÙˆÙ†â€ŒÙ‡Ø§ÛŒ Ù¾Ø±ÙˆÙØ§ÛŒÙ„ Ùˆ Ù…Ø´Ø®ØµØ§Øª ÙØ±Ø¯ÛŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ú¯Ø§Ù†
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

        # Ø³ØªÙˆÙ†â€ŒÙ‡Ø§ÛŒ Ú©Ø§Ø±Ø¨Ø±Ø§Ù† Ù¾Ø±ÛŒÙ…ÛŒÙˆÙ… Ùˆ ÙˆÙØ§Ø¯Ø§Ø±ÛŒ (VIP)
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

        # Ø³ØªÙˆÙ†â€ŒÙ‡Ø§ÛŒ Ø±Ø¨Ø§Øª Ø§Ø®ØªØµØ§ØµÛŒ (White-label Multi-Bot) Ùˆ ØªÙ†Ø¸ÛŒÙ…Ø§Øª Ù†Ù…Ø§ÛŒÙ†Ø¯Ú¯Ø§Ù†
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

        # Ø³ØªÙˆÙ†â€ŒÙ‡Ø§ÛŒ Ø¨Ø±Ù†Ø¯ÛŒÙ†Ú¯ØŒ Ø¯Ø§Ù…Ù†Ù‡ Ùˆ Ø¢Ù…ÙˆØ²Ø´â€ŒÙ‡Ø§ÛŒ Ø§Ø®ØªØµØ§ØµÛŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡
        for col_def in [
            "custom_domain TEXT", "tutorial_domain TEXT", "logo_url TEXT", "favicon_url TEXT",
            "brand_title TEXT", "primary_color TEXT", "footer_text TEXT",
            "portal_layout TEXT DEFAULT ''", "portal_plan_style TEXT DEFAULT ''"
        ]:
            try:
                cursor.execute(f"ALTER TABLE resellers ADD COLUMN {col_def}")
            except Exception:
                pass

        # Ø³ØªÙˆÙ†â€ŒÙ‡Ø§ÛŒ Ø¯Ø±Ú¯Ø§Ù‡ Ù¾Ø±Ø¯Ø§Ø®Øª Ø¢Ù†Ù„Ø§ÛŒÙ† Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡
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

        # Ù¾Ø§Ú©â€ŒØ³Ø§Ø²ÛŒ Ù…Ù‚Ø§Ø¯ÛŒØ± Ø®Ø§Ù„ÛŒ Ø¯Ø§Ù…Ù†Ù‡â€ŒÙ‡Ø§ Ø¬Ù‡Øª Ø¬Ù„ÙˆÚ¯ÛŒØ±ÛŒ Ø§Ø² ØªØ¯Ø§Ø®Ù„ Ø§ÛŒÙ†Ø¯Ú©Ø³ ÛŒÙˆÙ†ÛŒÚ©
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

        # Ø³ØªÙˆÙ†â€ŒÙ‡Ø§ÛŒ Ø§Ù†ØªØ³Ø§Ø¨ Ù…Ø¯ÛŒØ± Ø¨Ù‡ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ Ø¬Ù‡Øª Ø³Ø§Ø®Øª Ø²ÛŒØ±Ù…Ø¯ÛŒØ±Ø§Ù† (Sub-Admins)
        try:
            cursor.execute("ALTER TABLE admin_users ADD COLUMN reseller_id INTEGER")
        except Exception:
            pass

        try:
            cursor.execute("ALTER TABLE admin_users ADD COLUMN parent_admin_id INTEGER")
        except Exception:
            pass

        # Ø¬Ø¯ÙˆÙ„ Ú©Ø§Ø±Øªâ€ŒÙ‡Ø§ÛŒ Ø¨Ø§Ù†Ú©ÛŒ Ø§Ø®ØªØµØ§ØµÛŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡
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

        # Ø¬Ø¯ÙˆÙ„ Ú©Ø¯Ù‡Ø§ÛŒ ØªØ®ÙÛŒÙ Ø§Ø®ØªØµØ§ØµÛŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡
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

        # Ø¬Ø¯ÙˆÙ„ Ù„Ø§Ú¯ Ù¾ÛŒØ§Ù…Ú©â€ŒÙ‡Ø§ÛŒ ÙˆØ§Ø±ÛŒØ²ÛŒ Ø¨Ø§Ù†Ú©
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

        # Ø¬Ø¯ÙˆÙ„ ÙØ§Ú©ØªÙˆØ±Ù‡Ø§ÛŒ Ù‡ÙˆØ´Ù…Ù†Ø¯ Ø¨Ø§ Ø§Ø±Ù‚Ø§Ù… ØªØµØ§Ø¯ÙÛŒ Ø®Ø±Ø¯ Ø¬Ù‡Øª ØªØ§ÛŒÛŒØ¯ Ø®ÙˆØ¯Ú©Ø§Ø± Ú©Ø§Ø±Øª Ø¨Ù‡ Ú©Ø§Ø±Øª
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

        # Ø¬Ø¯ÙˆÙ„ Ø³ÙˆØ§Ø¨Ù‚ Ùˆ Ø±Ø³ÛŒØ¯Ù‡Ø§ÛŒ Ø¨Ø¯Ù‡ÛŒ Ù…Ø´ØªØ±ÛŒØ§Ù† (ØªÙÚ©ÛŒÚ© Ø¨Ù‡ Ø§Ø²Ø§ÛŒ Ù‡Ø± Ø®Ø±ÛŒØ¯ ÛŒØ§ ØªÙ…Ø¯ÛŒØ¯)
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

        # Ù…Ø§ÛŒÚ¯Ø±ÛŒØ´Ù† Ø³ØªÙˆÙ†â€ŒÙ‡Ø§ÛŒ Ù¾ÙˆØ±ØªØ§Ù„ Ù…Ø´ØªØ±ÛŒ Ø¨Ø±Ø§ÛŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ú¯Ø§Ù† Ùˆ ÙØ§Ú©ØªÙˆØ±Ù‡Ø§
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

        # Ø³ØªÙˆÙ† ØªØ¹Ø¯Ø§Ø¯ Ú©Ø§Ø±Ø¨Ø± Ù…Ø¬Ø§Ø² Ùˆ Ø¬Ø¯ÙˆÙ„ Ù†Ø´Ø³Øªâ€ŒÙ‡Ø§ (Device/User Limit & Sessions)
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

        # Ø³ØªÙˆÙ†â€ŒÙ‡Ø§ÛŒ ÙØ¹Ø§Ù„â€ŒØ³Ø§Ø²ÛŒ Ù…ÙˆÙ‚Øª Ø±Ø³ÛŒØ¯ (Grace Period)
        try:
            cursor.execute("ALTER TABLE payments ADD COLUMN is_grace_active INTEGER DEFAULT 0")
        except Exception:
            pass

        try:
            cursor.execute("ALTER TABLE payments ADD COLUMN grace_expires_at TEXT")
        except Exception:
            pass

        # Ø³ØªÙˆÙ†â€ŒÙ‡Ø§ÛŒ ÙˆØ¶Ø¹ÛŒØª Ù¾Ø±Ø¯Ø§Ø®ØªØŒ Ù…Ø¨Ù„Øº Ø¨Ø¯Ù‡ÛŒ Ùˆ ÛŒØ§Ø¯Ø¯Ø§Ø´Øª Ø¨Ø¯Ù‡ÛŒ Ø§Ø´ØªØ±Ø§Ú©â€ŒÙ‡Ø§
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

        # Ø³ØªÙˆÙ†â€ŒÙ‡Ø§ÛŒ Ù‚ÛŒÙ…Øª Ù¾Ù„Ù†ØŒ Ø¬Ø²Ø¦ÛŒØ§Øª Ù…Ø§Ù„ÛŒ Ùˆ Ø«Ø¨Øª Ø¯Ø³ØªÛŒ Ø³ÙˆØ§Ø¨Ù‚ Ø¯Ø± Ø³Ø§Ø¨Ù‚Ù‡ Ø¯ÙˆØ±Ù‡â€ŒÙ‡Ø§
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

        # Ø³ØªÙˆÙ†â€ŒÙ‡Ø§ÛŒ ØªÛŒÚ©Øªâ€ŒÙ‡Ø§ÛŒ Ø¯Ø±Ø®ÙˆØ§Ø³Øª ØªØºÛŒÛŒØ± Ø­Ø¬Ù… Ùˆ Ù…Ø¯Øª Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ Ùˆ Ú†Øª Ù¾ÙˆØ±ØªØ§Ù„ Ù…Ø´ØªØ±ÛŒ
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

        # Ø³ØªÙˆÙ†â€ŒÙ‡Ø§ÛŒ Ø³ÛŒØ³ØªÙ… Ø²ÛŒØ±Ù…Ø¬Ù…ÙˆØ¹Ù‡â€ŒÚ¯ÛŒØ±ÛŒ Ùˆ Ù¾ÙˆØ±Ø³Ø§Ù†Øª Ù†Ù…Ø§ÛŒÙ†Ø¯Ú¯Ø§Ù†
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

        # Ø³ØªÙˆÙ†â€ŒÙ‡Ø§ÛŒ Ø´Ø®ØµÛŒâ€ŒØ³Ø§Ø²ÛŒ Ø­Ø¬Ù…ØŒ Ù…Ø¯ØªØŒ Ø¯Ø±ØµØ¯ ØªØ®ÙÛŒÙ Ùˆ Ù‚ÛŒÙ…Øª Ø¹Ù…Ø¯Ù‡ Ø¯Ø± Ù¾Ù„Ù†â€ŒÙ‡Ø§ÛŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡
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

        # Ø³ØªÙˆÙ†â€ŒÙ‡Ø§ÛŒ Ù¾Ø±Ù…ÛŒÙˆÙ… Ùˆ Ø®Ø±ÛŒØ¯ Ø§Ø¹ØªØ¨Ø§Ø±ÛŒ Ø§Ø´ØªØ±Ø§Ú©â€ŒÙ‡Ø§ Ùˆ Ú©Ø§Ø±Ø¨Ø±Ø§Ù†
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

        # ÙØ¹Ø§Ù„â€ŒØ³Ø§Ø²ÛŒ Ø®ÙˆØ¯Ú©Ø§Ø± Ø®Ø±ÛŒØ¯ Ø§Ø¹ØªØ¨Ø§Ø±ÛŒ Ø¨Ø±Ø§ÛŒ Ú©Ù„ÛŒÙ‡ Ù†Ù…Ø§ÛŒÙ†Ø¯Ú¯Ø§Ù†ÛŒ Ú©Ù‡ Ø³Ù‚Ù Ø§Ø¹ØªØ¨Ø§Ø± Ø¯Ø§Ø±Ù†Ø¯
        try:
            cursor.execute("UPDATE resellers SET credit_enabled = 1 WHERE credit_limit > 0 AND (credit_enabled IS NULL OR credit_enabled = 0)")
        except Exception:
            pass

        # Ø¬Ø¯ÙˆÙ„ ØªØ±Ø§Ú©Ù†Ø´â€ŒÙ‡Ø§ÛŒ Ù¾ÙˆØ±Ø³Ø§Ù†Øª Ø²ÛŒØ±Ù…Ø¬Ù…ÙˆØ¹Ù‡â€ŒÚ¯ÛŒØ±ÛŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ú¯Ø§Ù†
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

        # Ù…Ù‚Ø¯Ø§Ø±Ø¯Ù‡ÛŒ Ø§ÙˆÙ„ÛŒÙ‡ ØªÙ†Ø¸ÛŒÙ…Ø§Øª Ø²ÛŒØ±Ù…Ø¬Ù…ÙˆØ¹Ù‡â€ŒÚ¯ÛŒØ±ÛŒ Ø¯Ø± ØµÙˆØ±Øª Ø¹Ø¯Ù… ÙˆØ¬ÙˆØ¯
        default_aff_settings = {
            "reseller_affiliate_enabled": "1",
            "reseller_affiliate_default_percent": "10",
            "reseller_affiliate_calc_base": "plan_price",
            "reseller_affiliate_terms": "Ø¨Ø§ Ù¾ÛŒÙˆØ³ØªÙ† Ø¨Ù‡ Ø¹Ù†ÙˆØ§Ù† Ù‡Ù…Ú©Ø§Ø± Ùˆ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ Ø²ÛŒØ±Ù…Ø¬Ù…ÙˆØ¹Ù‡ØŒ Ø§Ø² Ø±Ø¨Ø§Øª Ø§Ø®ØªØµØ§ØµÛŒ Ù‡ÙˆØ´Ù…Ù†Ø¯ØŒ Ø³Ø§Ø¨â€ŒØ¯Ø§Ù…Ù†Ù‡â€ŒÙ‡Ø§ÛŒ Ø¨Ø¯ÙˆÙ† ÙÛŒÙ„ØªØ± Ùˆ Ù¾Ù†Ù„ Ù…Ø¯ÛŒØ±ÛŒØª ÙØ±ÙˆØ´ Ø¨Ø§ ØªØ³ÙˆÛŒÙ‡ Ø¢Ù†ÛŒ Ø¨Ù‡Ø±Ù‡â€ŒÙ…Ù†Ø¯ Ø´ÙˆÛŒØ¯."
        }
        for k, v in default_aff_settings.items():
            cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))

        # Ø³ØªÙˆÙ†â€ŒÙ‡Ø§ÛŒ Ø­Ø°Ù Ù†Ø±Ù… Ø§Ø´ØªØ±Ø§Ú©â€ŒÙ‡Ø§ (Soft Delete & 7-Day Purge)
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

        # ØªØµØ­ÛŒØ­ Ø®ÙˆØ¯Ú©Ø§Ø± Ø´Ù†Ø§Ø³Ù‡ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ Ø¨Ø±Ø§ÛŒ Ø§Ø´ØªØ±Ø§Ú©â€ŒÙ‡Ø§ÛŒ Ù‚Ø¯ÛŒÙ…ÛŒ Ú©Ù‡ ØªÚ¯ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ Ø¯Ø± Ú©Ø§Ù…Ù†Øª Ø¯Ø§Ø±Ù†Ø¯ Ø§Ù…Ø§ reseller_id Ø¢Ù†â€ŒÙ‡Ø§ Ø®Ø§Ù„ÛŒ Ø§Ø³Øª
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

        # Ø¬Ø¯ÙˆÙ„ Ù‚Ø¨ÙˆØ¶ Ø¨Ø¯Ù‡ÛŒ Ù‚Ø¨Ù„ÛŒ/Ø¬Ø¯ÛŒØ¯ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ (Reseller Debts & Invoices)
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

        # Ø¬Ø¯ÙˆÙ„ ØµÙ ØªÙ…Ø¯ÛŒØ¯ Ù‡ÙˆØ´Ù…Ù†Ø¯ Ùˆ Ø¨Ø³ØªÙ‡â€ŒÙ‡Ø§ÛŒ Ø±Ø²Ø±Ùˆ
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

        # Ø³ØªÙˆÙ†â€ŒÙ‡Ø§ÛŒ Ù…Ø¨Ø¯Ø£ Ù¾Ø±Ø¯Ø§Ø®Øª Ú©ÛŒÙâ€ŒÙ¾ÙˆÙ„/Ø§Ø¹ØªØ¨Ø§Ø± Ùˆ Ø±Ù‡Ú¯ÛŒØ±ÛŒ ÙˆÛŒØ±Ø§ÛŒØ´ Ø§Ø³Ù†Ø§Ø¯ Ø­Ø³Ø§Ø¨Ø¯Ø§Ø±ÛŒ Ùˆ Ø¨Ø¯Ù‡ÛŒâ€ŒÙ‡Ø§
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
            # Ø³ØªÙˆÙ†â€ŒÙ‡Ø§ÛŒ Ø§Ø±ØªÙ‚Ø§ÛŒ Ø³ÛŒØ³ØªÙ… Ù…Ø¯ÛŒØ±ÛŒØª Ú©Ø§Ø±Øªâ€ŒÙ‡Ø§ Ùˆ Ø­Ø³Ø§Ø¨Ø¯Ø§Ø±ÛŒ Ø´Ù†Ø§ÙˆØ±
            "ALTER TABLE bank_cards ADD COLUMN is_default INTEGER DEFAULT 0",
            "ALTER TABLE bank_cards ADD COLUMN is_backup INTEGER DEFAULT 0",
            "ALTER TABLE bank_cards ADD COLUMN profit_percent INTEGER DEFAULT 0",
            "ALTER TABLE bank_cards ADD COLUMN assigned_to TEXT DEFAULT NULL",
            "ALTER TABLE bank_cards ADD COLUMN account_type TEXT DEFAULT 'bank_card'",
            "ALTER TABLE reseller_cards ADD COLUMN account_type TEXT DEFAULT 'bank_card'",
            "ALTER TABLE reseller_cards ADD COLUMN profit_percent INTEGER DEFAULT 0",
            "ALTER TABLE reseller_cards ADD COLUMN assigned_to TEXT DEFAULT NULL",
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

        # Ø¬Ø¯ÙˆÙ„ Ø¯ÙØªØ± Ø±ÛŒØ²ØªØ±Ø§Ú©Ù†Ø´â€ŒÙ‡Ø§ÛŒ ØªÙÚ©ÛŒÚ©ÛŒ Ú©Ø§Ø±Øªâ€ŒÙ‡Ø§ÛŒ Ø¨Ø§Ù†Ú©ÛŒ (Ù…Ø¯ÛŒØ±ÛŒØª Ùˆ Ù†Ù…Ø§ÛŒÙ†Ø¯Ú¯Ø§Ù†)
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

        # Ø¬Ø¯ÙˆÙ„ ØµÙ†Ø¯ÙˆÙ‚ Ù†Ù‚Ø¯ÛŒ Ùˆ Ø¯ÙØªØ± ØªØ³ÙˆÛŒÙ‡ Ù†Ù‚Ø¯ÛŒ Ù…Ø¯ÛŒØ±ÛŒØª Ùˆ Ù†Ù…Ø§ÛŒÙ†Ø¯Ú¯Ø§Ù†
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

        # Ø¬Ø¯ÙˆÙ„ Ø¨Ø³ØªÙ‡â€ŒÙ‡Ø§ÛŒ Ù¾ÛŒØ´â€ŒØ®Ø±ÛŒØ¯ Ø§Ø¹ØªØ¨Ø§Ø±ÛŒ Ù‡Ù…Ú©Ø§Ø±Ø§Ù† Ùˆ Ù†Ù…Ø§ÛŒÙ†Ø¯Ú¯Ø§Ù† (Reseller Credit Bundles)
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
                    ("bundle_1m", "Ø¨Ø³ØªÙ‡ Ø§Ø³ØªØ§Ø±ØªØ±", 1000000, 1050000, 5, "ÛµÙª Ø´Ø§Ø±Ú˜ Ù‡Ø¯ÛŒÙ‡", "info", "Ù…Ù†Ø§Ø³Ø¨ Ø´Ø±ÙˆØ¹ Ù‡Ù…Ú©Ø§Ø±ÛŒ Ùˆ Ø´Ø§Ø±Ú˜ Ø§ÙˆÙ„ÛŒÙ‡", 1, 1, now_seed, now_seed),
                    ("bundle_3m", "Ø¨Ø³ØªÙ‡ Ù†Ù‚Ø±Ù‡â€ŒØ§ÛŒ", 3000000, 3210000, 7, "Û·Ùª Ø´Ø§Ø±Ú˜ Ù‡Ø¯ÛŒÙ‡", "primary", "Ø¨Ø³ØªÙ‡ Ø§Ù‚ØªØµØ§Ø¯ÛŒ Ø¨Ø§ Ø¨ÙˆÙ†ÙˆØ³ Ø´Ø§Ø±Ú˜ ØªØ´ÙˆÛŒÙ‚ÛŒ", 2, 1, now_seed, now_seed),
                    ("bundle_5m", "Ø¨Ø³ØªÙ‡ Ø·Ù„Ø§ÛŒÛŒ", 5000000, 5500000, 10, "Û±Û°Ùª Ø´Ø§Ø±Ú˜ Ù‡Ø¯ÛŒÙ‡", "success", "Ø¨Ø³ØªÙ‡ Ù¾Ø±ÙØ±ÙˆØ´ Ù‡Ù…Ú©Ø§Ø±Ø§Ù† Ø¨Ø§ Û±Û°Ùª Ù‡Ø¯ÛŒÙ‡ Ù†Ù‚Ø¯ÛŒ", 3, 1, now_seed, now_seed),
                    ("bundle_10m", "Ø¨Ø³ØªÙ‡ Ø§Ù„Ù…Ø§Ø³ VIP", 10000000, 11500000, 15, "Û±ÛµÙª Ø´Ø§Ø±Ú˜ ÙˆÛŒÚ˜Ù‡", "warning", "Ø­Ø¯Ø§Ú©Ø«Ø± Ø§Ø¹ØªØ¨Ø§Ø± Ø¨Ø§ Ø¨Ø§Ù„Ø§ØªØ±ÛŒÙ† Ù†Ø±Ø® Ø¨ÙˆÙ†ÙˆØ³ ÙˆÛŒÚ˜Ù‡", 4, 1, now_seed, now_seed),
                ]
                cursor.executemany("""
                    INSERT INTO reseller_bundles (id, title, price, credit, bonus_percent, badge, color, description, display_order, is_active, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, default_bundles)
        except Exception as e:
            logger.warning(f"Error initializing reseller_bundles table: {e}")

        # Ø§ØµÙ„Ø§Ø­ Ø¯Ø³ØªÙ‡â€ŒØ¨Ù†Ø¯ÛŒ ØªÛŒÚ©Øªâ€ŒÙ‡Ø§ÛŒ Ù…Ø´ØªØ±ÛŒØ§Ù† Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ Ø¨Ù‡ target_role='reseller'
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

        # Ø¨Ø§Ø²ÛŒØ§Ø¨ÛŒ Ø¬Ø§Ù…Ø¹ Ø§Ø·Ù„Ø§Ø¹Ø§Øª Ø¯Ø± ØµÙˆØ±Øª Ø®Ø§Ù„ÛŒ Ø¨ÙˆØ¯Ù† Ø¯ÛŒØªØ§Ø¨ÛŒØ³ Ù¾Ø³ Ø§Ø² Ø¯ÛŒÙ¾Ù„ÙˆÛŒ
        try:
            self.auto_restore_full()
        except Exception as e:
            logger.warning(f"Initial auto_restore_full check: {e}")

        # Ø®ÙˆØ¯ØªØ±Ù…ÛŒÙ…ÛŒ Ùˆ Ø§ØµÙ„Ø§Ø­ Ø®ÙˆØ¯Ú©Ø§Ø± Ù‡Ø±Ú¯ÙˆÙ†Ù‡ Ø§Ù†Ø­Ø±Ø§Ù ÛŒØ§ Ø®Ø·Ø§ÛŒ Ù…Ø­Ø§Ø³Ø¨Ø§ØªÛŒ Ø¯Ø± Ø±Ø³ÛŒØ¯Ù‡Ø§ Ùˆ Ø¨Ø¯Ù‡ÛŒâ€ŒÙ‡Ø§
        try:
            self.repair_customer_debt_records()
        except Exception as e:
            logger.warning(f"Initial repair_customer_debt_records check: {e}")

    def export_full_backup_json(self) -> dict:
        """Ù¾Ø´ØªÛŒØ¨Ø§Ù†â€ŒÚ¯ÛŒØ±ÛŒ Ú©Ø§Ù…Ù„ Ø§Ø² ØªÙ…Ø§Ù… Ø¬Ø¯Ø§ÙˆÙ„ØŒ Ú©Ø§Ø±Ø¨Ø±Ø§Ù†ØŒ Ù¾Ù„Ù†â€ŒÙ‡Ø§ØŒ Ú©Ø§Ø±Øªâ€ŒÙ‡Ø§ØŒ ØªÙ†Ø¸ÛŒÙ…Ø§ØªØŒ ØªØ®ÙÛŒÙâ€ŒÙ‡Ø§ Ùˆ Ù†Ù…Ø§ÛŒÙ†Ø¯Ú¯Ø§Ù† Ø¯Ø± Ù‚Ø§Ù„Ø¨ ÛŒÚ© ÙØ§ÛŒÙ„ JSON Ù¾Ø§ÛŒØ¯Ø§Ø±"""
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
        
        # Ø°Ø®ÛŒØ±Ù‡ Ø¯Ø± ÙØ§ÛŒÙ„â€ŒÙ‡Ø§ÛŒ Ù¾Ø´ØªÛŒØ¨Ø§Ù† Ù¾Ø§ÛŒØ¯Ø§Ø±
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
        """Ø¨Ø§Ø²ÛŒØ§Ø¨ÛŒ Ø¬Ø§Ù…Ø¹ Ø§Ø·Ù„Ø§Ø¹Ø§Øª ØªÙ…Ø§Ù… Ø¬Ø¯Ø§ÙˆÙ„ (Ú©Ø§Ø±Ø¨Ø±Ø§Ù†ØŒ Ú©Ø§Ø±Øªâ€ŒÙ‡Ø§ØŒ Ù¾Ù„Ù†â€ŒÙ‡Ø§ØŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ú¯Ø§Ù†ØŒ Ú©Ø¯ ØªØ®ÙÛŒÙ Ùˆ ØªÙ†Ø¸ÛŒÙ…Ø§Øª) Ù¾Ø³ Ø§Ø² Ø¯ÛŒÙ¾Ù„ÙˆÛŒ"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            # Ø¨Ø±Ø±Ø³ÛŒ Ø®Ø§Ù„ÛŒ Ø¨ÙˆØ¯Ù† Ø¬Ø¯Ø§ÙˆÙ„ Ú©Ù„ÛŒØ¯ÛŒ
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
            
            # Ø¬Ø³ØªØ¬ÙˆÛŒ ÙØ§ÛŒÙ„ JSON ÙÙˆÙ„ Ø¨Ú©â€ŒØ¢Ù¾
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
                # ØªÙ„Ø§Ø´ Ø¨Ø±Ø§ÛŒ Ø¨Ø§Ø²ÛŒØ§Ø¨ÛŒ Ø§Ø² ÙØ§ÛŒÙ„â€ŒÙ‡Ø§ÛŒ .db
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
        """Ø¨Ø§Ø²ÛŒØ§Ø¨ÛŒ Ø®ÙˆØ¯Ú©Ø§Ø± Ø§Ø² Ø¢Ø®Ø±ÛŒÙ† Ù¾Ø´ØªÛŒØ¨Ø§Ù† Ø§Ú¯Ø± Ø¯ÛŒØªØ§Ø¨ÛŒØ³ Ø®Ø§Ù„ÛŒ Ø¨Ø§Ø´Ø¯"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            # Ø¨Ø±Ø±Ø³ÛŒ ØªØ¹Ø¯Ø§Ø¯ Ú©Ø§Ø±Ø¨Ø±Ø§Ù†
            cursor.execute("SELECT COUNT(*) FROM users")
            count = cursor.fetchone()[0]
            conn.close()
            
            if count > 0:
                logger.info(f"Database has {count} users, no restore needed")
                return {"restored": False, "reason": "database_not_empty"}
            
            logger.info("Database is empty, looking for backups...")
            
            # Ø¬Ø³ØªØ¬Ùˆ Ø¨Ø±Ø§ÛŒ ÙØ§ÛŒÙ„â€ŒÙ‡Ø§ÛŒ Ù¾Ø´ØªÛŒØ¨Ø§Ù†
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
            
            # Ù…Ø±ØªØ¨â€ŒØ³Ø§Ø²ÛŒ Ø¨Ø± Ø§Ø³Ø§Ø³ ØªØ§Ø±ÛŒØ® (Ø¬Ø¯ÛŒØ¯ØªØ±ÛŒÙ† Ø§ÙˆÙ„)
            all_backups.sort(key=lambda x: x.stat().st_mtime, reverse=True)
            latest_backup = all_backups[0]
            
            logger.info(f"Restoring from backup: {latest_backup.name}")
            
            # Ú©Ù¾ÛŒ Ù¾Ø´ØªÛŒØ¨Ø§Ù† Ø¨Ù‡ Ù…Ø³ÛŒØ± Ø¯ÛŒØªØ§Ø¨ÛŒØ³ ÙØ¹Ù„ÛŒ
            import shutil
            shutil.copy2(latest_backup, self.db_path)
            
            # Ø¨Ø±Ø±Ø³ÛŒ Ù†ØªÛŒØ¬Ù‡
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
        ØªØ´Ø®ÛŒØµ Ø¢Ù†Ù„Ø§ÛŒÙ† Ø¨ÙˆØ¯Ù† Ùˆ Ø§Ø³ØªØ®Ø±Ø§Ø¬ Ø¢Ø®Ø±ÛŒÙ† Ø§ØªØµØ§Ù„ Ø§Ø² Ø¢Ø¨Ø¬Ú©Øª Ú©Ø§Ø±Ø¨Ø± Ø¯Ø± Ù‡ÛŒØ¯ÛŒÙØ§ÛŒ (Ø±ÙˆØ´ ÙÙˆÙ‚â€ŒØ¨Ù‡ÛŒÙ†Ù‡ Ø¨Ø± Ù¾Ø§ÛŒÙ‡ Timestamp)
        Ø®Ø±ÙˆØ¬ÛŒ: (is_online: 1|0, last_online_str)
        """
        if not u or not isinstance(u, dict):
            return 0, None

        # Ø§Ú¯Ø± Ú©Ø§Ø±Ø¨Ø± Ø¯Ø± Ù‡ÛŒØ¯ÛŒÙØ§ÛŒ ØºÛŒØ±ÙØ¹Ø§Ù„ ÛŒØ§ Ù…Ù†Ù‚Ø¶ÛŒ Ø¨Ø§Ø´Ø¯ØŒ Ø¨Ù‡ Ù‡ÛŒÚ† ÙˆØ¬Ù‡ Ø¢Ù†Ù„Ø§ÛŒÙ† Ù†ÛŒØ³Øª
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
                # Ø¨Ø±Ø±Ø³ÛŒ ÙØ§ØµÙ„Ù‡ Ø²Ù…Ø§Ù†ÛŒ Ø¢Ø®Ø±ÛŒÙ† Ø§ØªØµØ§Ù„ (Ø³Ø±ÙˆØ± Ù‡ÛŒØ¯ÛŒÙØ§ÛŒ Ø¨Ø± Ù¾Ø§ÛŒÙ‡ UTC Ø§Ø³Øª)
                dt = datetime.strptime(clean_str[:19], "%Y-%m-%d %H:%M:%S")
                now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
                now_tehran = get_now_naive()
                diff_utc = (now_utc - dt).total_seconds()
                diff_tehran = (now_tehran - dt).total_seconds()
                
                # Ú©Ø§Ø±Ø¨Ø± ÙÙ‚Ø· Ø¯Ø± ØµÙˆØ±ØªÛŒ Ø¢Ù†Ù„Ø§ÛŒÙ† Ø§Ø³Øª Ú©Ù‡ Ø§ØªØµØ§Ù„ ÙˆØ§Ù‚Ø¹ÛŒ Ø¯Ø± Ûµ Ø¯Ù‚ÛŒÙ‚Ù‡ (Û³Û°Û° Ø«Ø§Ù†ÛŒÙ‡) Ø§Ø®ÛŒØ± Ø±Ø® Ø¯Ø§Ø¯Ù‡ Ø¨Ø§Ø´Ø¯
                if (0 <= diff_utc <= 300) or (0 <= diff_tehran <= 300):
                    is_online = 1
                else:
                    is_online = 0
            except Exception:
                last_online_str = str(last_online_raw)

        return is_online, last_online_str

    def sync_from_hidify(self, hidify_users: list) -> dict:
        """Ù‡Ù…Ú¯Ø§Ù…â€ŒØ³Ø§Ø²ÛŒ Ùˆ Ø¨Ø§Ø²ÛŒØ§Ø¨ÛŒ Ø®ÙˆØ¯Ú©Ø§Ø± ØªÙ…Ø§Ù…ÛŒ Ú©Ø§Ø±Ø¨Ø±Ø§Ù† Ùˆ Ø§Ø´ØªØ±Ø§Ú©â€ŒÙ‡Ø§ Ø¨Ù‡ Ù‡Ù…Ø±Ø§Ù‡ ÙˆØ¶Ø¹ÛŒØª Ø¢Ù†Ù„Ø§ÛŒÙ† Ø¨ÙˆØ¯Ù† Ø§Ø² Ù¾Ù†Ù„ Ù‡ÛŒØ¯ÛŒÙØ§ÛŒ"""
        if not hidify_users or not isinstance(hidify_users, list):
            return {"success": False, "count": 0, "error": "Ù„ÛŒØ³Øª Ú©Ø§Ø±Ø¨Ø±Ø§Ù† Ù‡ÛŒØ¯ÛŒÙØ§ÛŒ Ø®Ø§Ù„ÛŒ ÛŒØ§ Ù†Ø§Ù…Ø¹ØªØ¨Ø± Ø§Ø³Øª"}

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

                # ØªØ´Ø®ÛŒØµ ÙˆØ¶Ø¹ÛŒØª Ø¢Ù†Ù„Ø§ÛŒÙ† Ø¨ÙˆØ¯Ù†
                is_online_val, last_online_val = self._parse_hiddify_user_online(u)
                if is_online_val:
                    total_online += 1

                # Ø§Ø³ØªØ®Ø±Ø§Ø¬ telegram_id Ø§Ø² Ú©Ø§Ù…Ù†Øª ÛŒØ§ Ù†Ø§Ù… Ú©Ø§Ø±Ø¨Ø±ÛŒ
                telegram_id = 0
                if comment.isdigit() and len(comment) >= 5:
                    telegram_id = int(comment)
                elif name.startswith("tg_") and name.replace("tg_", "").isdigit():
                    telegram_id = int(name.replace("tg_", ""))

                # Û±. Ø«Ø¨Øª ÛŒØ§ Ø¨Ø±ÙˆØ²Ø±Ø³Ø§Ù†ÛŒ Ø¯Ø± Ø¬Ø¯ÙˆÙ„ users
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

                    # Ø§ÛŒØ¬Ø§Ø¯ Ú©ÛŒÙ Ù¾ÙˆÙ„ Ø¯Ø± ØµÙˆØ±Øª Ø¹Ø¯Ù… ÙˆØ¬ÙˆØ¯
                    cursor.execute("SELECT id FROM wallet WHERE telegram_id = ?", (telegram_id,))
                    if not cursor.fetchone():
                        cursor.execute("""
                            INSERT INTO wallet (telegram_id, balance, created_at, updated_at)
                            VALUES (?, 0, ?, ?)
                        """, (telegram_id, now, now))

                # Û². Ø«Ø¨Øª ÛŒØ§ Ø¨Ø±ÙˆØ²Ø±Ø³Ø§Ù†ÛŒ Ø¯Ø± Ø¬Ø¯ÙˆÙ„ subscriptions
                cursor.execute("SELECT id FROM subscriptions WHERE hidify_uuid = ?", (uuid,))
                existing_sub = cursor.fetchone()

                plan_name = f"{usage_limit} Ú¯ÛŒÚ¯ {package_days} Ø±ÙˆØ²Ù‡" if usage_limit > 0 else f"{package_days} Ø±ÙˆØ²Ù‡"
                if "test" in name.lower() or (usage_limit > 0 and usage_limit <= 0.5):
                    plan_id = "test"
                    plan_name = "Ø§Ø´ØªØ±Ø§Ú© ØªØ³Øª"
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
                    # Ø¨Ø±ÙˆØ²Ø±Ø³Ø§Ù†ÛŒ Ù…ØµØ±ÙØŒ Ø³Ù‚Ù Ø­Ø¬Ù…ØŒ ØªØ¹Ø¯Ø§Ø¯ Ø±ÙˆØ²Ù‡Ø§ (duration / package_days)ØŒ ØªØ§Ø±ÛŒØ®â€ŒÙ‡Ø§ Ùˆ ÙˆØ¶Ø¹ÛŒØª
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
                    # Ø¯Ø±Ø¬ Ø§Ø´ØªØ±Ø§Ú© Ø¬Ø¯ÛŒØ¯ Ø¨Ø§Ø²ÛŒØ§Ø¨ÛŒ Ø´Ø¯Ù‡
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
        Ø¨Ø±ÙˆØ²Ø±Ø³Ø§Ù†ÛŒ Ùˆ ØªØµØ­ÛŒØ­ Ù‡ÙˆØ´Ù…Ù†Ø¯ Ùˆ Ø¯ÙˆØ±Ù‡â€ŒØ§ÛŒ ÙˆØ¶Ø¹ÛŒØª Ø§Ø´ØªØ±Ø§Ú©â€ŒÙ‡Ø§:
        Û±. ØµÙØ± Ú©Ø±Ø¯Ù† Ø¢Ù†Ù„Ø§ÛŒÙ† Ø¨ÙˆØ¯Ù† Ø¨Ø±Ø§ÛŒ Ø§Ø´ØªØ±Ø§Ú©â€ŒÙ‡Ø§ÛŒÛŒ Ú©Ù‡ Ø§ØªØµØ§Ù„ Ø§Ø®ÛŒØ± (Ø¨ÛŒØ´ Ø§Ø² Û±Û° Ø¯Ù‚ÛŒÙ‚Ù‡) Ù†Ø¯Ø§Ø´ØªÙ‡â€ŒØ§Ù†Ø¯
        Û². Ø¨Ø±ÙˆØ²Ø±Ø³Ø§Ù†ÛŒ ÙˆØ¶Ø¹ÛŒØª Ø§Ø´ØªØ±Ø§Ú©â€ŒÙ‡Ø§ÛŒ Ù…Ù†Ù‚Ø¶ÛŒâ€ŒØ´Ø¯Ù‡ Ø¨Ø± Ø§Ø³Ø§Ø³ ØªØ§Ø±ÛŒØ® Ø§Ù†Ù‚Ø¶Ø§ ÛŒØ§ Ø­Ø¬Ù… Ù…ØµØ±ÙÛŒ
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        updated_online = 0
        updated_expired = 0
        now_dt = get_now_naive()
        now_iso = get_now_iso()

        try:
            # Û±. Ø¨Ø§Ø²ÛŒØ§Ø¨ÛŒ Ú©Ù„ÛŒÙ‡ Ø§Ø´ØªØ±Ø§Ú©â€ŒÙ‡Ø§ÛŒ Ø¯Ø§Ø±Ø§ÛŒ ÙˆØ¶Ø¹ÛŒØª Ø¢Ù†Ù„Ø§ÛŒÙ† Ø¬Ù‡Øª Ø§Ø¹ØªØ¨Ø§Ø±Ø³Ù†Ø¬ÛŒ Ù…Ø¬Ø¯Ø¯
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

                # Ø§Ú¯Ø± ÙˆØ¶Ø¹ÛŒØª ÙØ¹Ø§Ù„ Ù†ÛŒØ³ØªØŒ Ø¨Ù‡ Ù‡ÛŒÚ† ÙˆØ¬Ù‡ Ø¢Ù†Ù„Ø§ÛŒÙ† Ù†ÛŒØ³Øª
                if r["status"] in ("expired", "disabled", "inactive"):
                    is_still_online = False

                # Ø§Ú¯Ø± Ø­Ø¬Ù… Ø¨Ù‡ Ù¾Ø§ÛŒØ§Ù† Ø±Ø³ÛŒØ¯Ù‡ØŒ Ø¢Ù†Ù„Ø§ÛŒÙ† Ù†ÛŒØ³Øª
                d_limit = float(r["data_limit"] or 0)
                d_used = float(r["data_used"] or 0)
                if d_limit > 0 and d_used >= d_limit:
                    is_still_online = False

                if not is_still_online:
                    cursor.execute("UPDATE subscriptions SET is_online = 0, updated_at = ? WHERE id = ?", (now_iso, sub_id))
                    updated_online += 1

            # Û². Ø¨Ø±ÙˆØ²Ø±Ø³Ø§Ù†ÛŒ Ø®ÙˆØ¯Ú©Ø§Ø± Ø§Ø´ØªØ±Ø§Ú©â€ŒÙ‡Ø§ÛŒÛŒ Ú©Ù‡ Ù…ÙˆØ¹Ø¯ Ø§Ù†Ù‚Ø¶Ø§ÛŒ Ø¢Ù†â€ŒÙ‡Ø§ Ø³Ù¾Ø±ÛŒ Ø´Ø¯Ù‡ Ø§Ù…Ø§ Ù‡Ù†ÙˆØ² active Ù‡Ø³ØªÙ†Ø¯
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
        """Ø¢Ù…Ø§Ø± ØªØ¹Ø¯Ø§Ø¯ Ú©Ù„ Ú©Ø§Ø±Ø¨Ø±Ø§Ù† Ùˆ Ù…Ø´ØªØ±ÛŒØ§Ù† Ø¢Ù†Ù„Ø§ÛŒÙ† Ø¨Ø±Ø§ÛŒ Ø§Ø¯Ù…ÛŒÙ† ÛŒØ§ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡"""
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
        """Ø¯Ø±ÛŒØ§ÙØª Ù„ÛŒØ³Øª Ø§Ø´ØªØ±Ø§Ú©â€ŒÙ‡Ø§ÛŒ Ø¢Ù†Ù„Ø§ÛŒÙ†"""
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

    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    # Ù…Ø¯ÛŒØ±ÛŒØª Ù…Ø´ØªØ±ÛŒØ§Ù†
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

    def save_user(self, telegram_id, username=None, hidify_uuid=None, plan_id=None, data_limit=None, expire_at=None, reseller_id=None):
        """Ø°Ø®ÛŒØ±Ù‡ ÛŒØ§ Ø¨Ø±ÙˆØ²Ø±Ø³Ø§Ù†ÛŒ Ø§Ø·Ù„Ø§Ø¹Ø§Øª Ú©Ø§Ø±Ø¨Ø±"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()

        try:
            # Ø¨Ø±Ø±Ø³ÛŒ ÙˆØ¬ÙˆØ¯ Ú©Ø§Ø±Ø¨Ø±
            cursor.execute("SELECT id, reseller_id FROM users WHERE telegram_id = ?", (telegram_id,))
            existing = cursor.fetchone()

            if existing:
                # Ø¨Ø±ÙˆØ²Ø±Ø³Ø§Ù†ÛŒ Ø¨Ø§ Ø­ÙØ¸ ÙÛŒÙ„Ø¯Ù‡Ø§ÛŒ Ù‚Ø¨Ù„ÛŒ Ø¯Ø± ØµÙˆØ±Øª None Ø¨ÙˆØ¯Ù†
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
                # Ø¯Ø±Ø¬ Ø¬Ø¯ÛŒØ¯
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
        """Ø¯Ø±ÛŒØ§ÙØª Ø§Ø·Ù„Ø§Ø¹Ø§Øª Ú©Ø§Ø±Ø¨Ø±"""
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
        """Ø«Ø¨Øª Ùˆ ØªØ§ÛŒÛŒØ¯ Ø´Ù…Ø§Ø±Ù‡ ØªÙ…Ø§Ø³ ØªÙ„Ú¯Ø±Ø§Ù… Ú©Ø§Ø±Ø¨Ø±"""
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
        """Ø¨Ø±Ø±Ø³ÛŒ Ø§Ø­Ø±Ø§Ø² Ù‡ÙˆÛŒØª Ø´Ù…Ø§Ø±Ù‡ ØªÙ„ÙÙ† Ú©Ø§Ø±Ø¨Ø±"""
        user = self.get_user(telegram_id)
        if not user:
            return False
        phone = user.get("phone_number")
        return bool(phone and str(phone).strip())

    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    # Ù…Ø¯ÛŒØ±ÛŒØª Ù…Ø´ØªØ±ÛŒØ§Ù† Ù¾Ø±ÛŒÙ…ÛŒÙˆÙ… Ùˆ ÙˆÙØ§Ø¯Ø§Ø±ÛŒ (VIP & Loyalty Club)
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

    def is_user_vip(self, telegram_id: int) -> bool:
        """Ø¨Ø±Ø±Ø³ÛŒ ÙˆØ¶Ø¹ÛŒØª Ù¾Ø±ÛŒÙ…ÛŒÙˆÙ… / VIP Ø¨ÙˆØ¯Ù† Ú©Ø§Ø±Ø¨Ø± Ø¨Ø§ Ø±Ø¹Ø§ÛŒØª ØªØ§Ø±ÛŒØ® Ø§Ù†Ù‚Ø¶Ø§"""
        user = self.get_user(telegram_id)
        if not user or not user.get("is_vip"):
            return False

        # Ø¨Ø±Ø±Ø³ÛŒ ØªØ§Ø±ÛŒØ® Ø§Ù†Ù‚Ø¶Ø§ Ø¯Ø± ØµÙˆØ±Øª ÙˆØ¬ÙˆØ¯
        vip_expire = user.get("vip_expire_at")
        if vip_expire:
            try:
                exp_dt = datetime.fromisoformat(vip_expire)
                if datetime.now() > exp_dt:
                    # Ø§Ù†Ù‚Ø¶Ø§ÛŒ Ù…Ø¯Øª VIP - Ø±ÛŒØ³Øª Ú©Ø±Ø¯Ù† ÙˆØ¶Ø¹ÛŒØª Ø¨Ù‡ Ø¹Ø§Ø¯ÛŒ
                    self.set_user_vip(telegram_id, is_vip=False, vip_type="expired")
                    return False
            except Exception:
                pass
        return True

    def get_user_vip_info(self, telegram_id: int) -> dict:
        """Ø¯Ø±ÛŒØ§ÙØª Ø§Ø·Ù„Ø§Ø¹Ø§Øª Ùˆ Ù…Ø²Ø§ÛŒØ§ÛŒ VIP Ú©Ø§Ø±Ø¨Ø± Ø´Ø§Ù…Ù„ Ø¯Ø±ØµØ¯ Ú©Ø´â€ŒØ¨Ú© ÙØ¹Ø§Ù„"""
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
        """ØªØºÛŒÛŒØ± Ùˆ ØªÙ†Ø¸ÛŒÙ… ÙˆØ¶Ø¹ÛŒØª VIP Ú©Ø§Ø±Ø¨Ø± (Ø¯Ø³ØªÛŒ ÛŒØ§ Ø®ÙˆØ¯Ú©Ø§Ø±)"""
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
        """Ø¨Ø±Ø±Ø³ÛŒ Ø®ÙˆØ¯Ú©Ø§Ø± Ù…Ø¬Ù…ÙˆØ¹ Ø®Ø±ÛŒØ¯Ù‡Ø§ÛŒ Ú©Ø§Ø±Ø¨Ø± Ùˆ Ø§Ø±ØªÙ‚Ø§ Ø¨Ù‡ VIP Ø¯Ø± ØµÙˆØ±Øª Ø±Ø³ÛŒØ¯Ù† Ø¨Ù‡ Ø­Ø¯ Ù†ØµØ§Ø¨"""
        user = self.get_user(telegram_id)
        if not user:
            return {"upgraded": False, "is_vip": False}

        if user.get("is_vip"):
            return {"upgraded": False, "is_vip": True, "already_vip": True}

        r_id = reseller_id if reseller_id is not None else user.get("reseller_id")

        # Ù…Ø­Ø§Ø³Ø¨Ù‡ Ù…Ø¬Ù…ÙˆØ¹ Ø®Ø±ÛŒØ¯Ù‡Ø§ÛŒ ØªØ§ÛŒÛŒØ¯ Ø´Ø¯Ù‡ Ú©Ø§Ø±Ø¨Ø±
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
        """Ø¯Ø±ÛŒØ§ÙØª ØªÙ†Ø¸ÛŒÙ…Ø§Øª Ø¬Ø§Ù…Ø¹ Ùˆ ÙÛŒÚ†Ø±Ù‡Ø§ÛŒ Ø¨Ø§Ø´Ú¯Ø§Ù‡ Ù…Ø´ØªØ±ÛŒØ§Ù† Ù¾Ø±ÛŒÙ…ÛŒÙˆÙ… (VIP)"""
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
        """Ø°Ø®ÛŒØ±Ù‡ ØªÙ†Ø¸ÛŒÙ…Ø§Øª Ùˆ ÙÛŒÚ†Ø±Ù‡Ø§ÛŒ Ø¨Ø§Ø´Ú¯Ø§Ù‡ Ù…Ø´ØªØ±ÛŒØ§Ù† Ù¾Ø±ÛŒÙ…ÛŒÙˆÙ… Ø¯Ø± Ø¬Ø¯ÙˆÙ„ settings"""
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
        """Ø¯Ø±ÛŒØ§ÙØª Ù„ÛŒØ³Øª ØªÙ…Ø§Ù… Ù…Ø´ØªØ±ÛŒØ§Ù† Ù¾Ø±Ù…ÛŒÙˆÙ… Ù‡Ù…Ø±Ø§Ù‡ Ø¨Ø§ Ø¢Ù…Ø§Ø± Ø®Ø±ÛŒØ¯ Ùˆ Ø§Ø´ØªØ±Ø§Ú©â€ŒÙ‡Ø§ÛŒ ÙØ¹Ø§Ù„"""
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
        """Ù…Ø­Ø§Ø³Ø¨Ù‡ Ø¢Ù…Ø§Ø± Ùˆ Ø´Ø§Ø®Øµâ€ŒÙ‡Ø§ÛŒ ØªØ­Ù„ÛŒÙ„ÛŒ Ù…Ø´ØªØ±ÛŒØ§Ù† Ù¾Ø±Ù…ÛŒÙˆÙ… Ø¨Ø±Ø§ÛŒ Ø¯Ø§Ø´Ø¨ÙˆØ±Ø¯"""
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

    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    # Ù…Ø¯ÛŒØ±ÛŒØª Ú©ÛŒÙ Ù¾ÙˆÙ„ Ú©Ø§Ø±Ø¨Ø± (User In-App Wallet)
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

    def get_user_wallet_balance(self, telegram_id: int) -> int:
        """Ø¯Ø±ÛŒØ§ÙØª Ù…ÙˆØ¬ÙˆØ¯ÛŒ Ú©ÛŒÙ Ù¾ÙˆÙ„ Ú©Ø§Ø±Ø¨Ø± (Ø¨Ù‡ ØªÙˆÙ…Ø§Ù†)"""
        user = self.get_user(telegram_id)
        if not user:
            return 0
        return int(user.get("wallet_balance") or 0)

    def add_wallet_balance(self, telegram_id: int, amount: int, description: str, ref_id: str = None, tx_type: str = "deposit") -> dict:
        """Ø§ÙØ²Ø§ÛŒØ´ Ù…ÙˆØ¬ÙˆØ¯ÛŒ Ú©ÛŒÙ Ù¾ÙˆÙ„ Ú©Ø§Ø±Ø¨Ø± Ùˆ Ø«Ø¨Øª ØªØ±Ø§Ú©Ù†Ø´"""
        if amount <= 0:
            return {"success": False, "error": "Ù…Ø¨Ù„Øº Ø¨Ø§ÛŒØ¯ Ø¨ÛŒØ´ØªØ± Ø§Ø² ØµÙØ± Ø¨Ø§Ø´Ø¯."}
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
        """Ú©Ø³Ø± Ø§Ø² Ù…ÙˆØ¬ÙˆØ¯ÛŒ Ú©ÛŒÙ Ù¾ÙˆÙ„ Ú©Ø§Ø±Ø¨Ø± Ø¬Ù‡Øª Ø®Ø±ÛŒØ¯ ÛŒØ§ ØªÙ…Ø¯ÛŒØ¯ Ù¾Ù„Ù†"""
        if amount <= 0:
            return {"success": False, "error": "Ù…Ø¨Ù„Øº Ù†Ø§Ù…Ø¹ØªØ¨Ø± Ø§Ø³Øª."}
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("SELECT id, wallet_balance FROM users WHERE telegram_id = ?", (telegram_id,))
            row = cursor.fetchone()
            if not row:
                return {"success": False, "error": "Ú©Ø§Ø±Ø¨Ø± ÛŒØ§ÙØª Ù†Ø´Ø¯."}

            current_bal = int(row["wallet_balance"] or 0)
            if current_bal < amount:
                return {"success": False, "error": "Ù…ÙˆØ¬ÙˆØ¯ÛŒ Ú©ÛŒÙ Ù¾ÙˆÙ„ Ø´Ù…Ø§ Ú©Ø§ÙÛŒ Ù†ÛŒØ³Øª.", "balance": current_bal, "required": amount}

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
        """Ø¯Ø±ÛŒØ§ÙØª Ù„ÛŒØ³Øª ØªØ§Ø±ÛŒØ®Ú†Ù‡ ØªØ±Ø§Ú©Ù†Ø´â€ŒÙ‡Ø§ÛŒ Ú©ÛŒÙ Ù¾ÙˆÙ„ Ú©Ø§Ø±Ø¨Ø±"""
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
        """ÛŒØ§ÙØªÙ† Ø¢ÛŒØ¯ÛŒ ØªÙ„Ú¯Ø±Ø§Ù… Ú©Ø§Ø±Ø¨Ø± Ø§Ø² Ø±ÙˆÛŒ Ø´Ù…Ø§Ø±Ù‡ ØªÙ„ÙÙ† Ø«Ø¨Øªâ€ŒØ´Ø¯Ù‡ Ø¯Ø± Ø¬Ø¯ÙˆÙ„ Ú©Ø§Ø±Ø¨Ø±Ø§Ù†"""
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
        """Ø¯Ø±ÛŒØ§ÙØª ØªÙ…Ø§Ù… Ú©Ø§Ø±Ø¨Ø±Ø§Ù†"""
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
        """Ø­Ø°Ù Ú©Ø§Ø±Ø¨Ø±"""
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

    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    # Ù…Ø¯ÛŒØ±ÛŒØª Ø§Ø´ØªØ±Ø§Ú©â€ŒÙ‡Ø§
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

    def save_subscription(self, telegram_id, hidify_uuid, plan_id, plan_name, data_limit, duration, data_used=0, status="active", account_name=None, account_comment=None, reseller_id=None, user_limit=1, cost_paid=0, created_by=None, **kwargs):
        """Ø°Ø®ÛŒØ±Ù‡ Ø§Ø´ØªØ±Ø§Ú© Ø¬Ø¯ÛŒØ¯"""
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
        """Ø¯Ø±ÛŒØ§ÙØª Ø§Ø´ØªØ±Ø§Ú©â€ŒÙ‡Ø§ÛŒ Ú©Ø§Ø±Ø¨Ø± Ø¨Ø§ Ù‚Ø§Ø¨Ù„ÛŒØª Ø§ÛŒØ²ÙˆÙ„Ø§Ø³ÛŒÙˆÙ† Ø¨Ø± Ø§Ø³Ø§Ø³ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ ÛŒØ§ Ù…Ø¯ÛŒØ±ÛŒØª"""
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
        """Ø¯Ø±ÛŒØ§ÙØª Ø§Ø´ØªØ±Ø§Ú© ÙØ¹Ø§Ù„ Ú©Ø§Ø±Ø¨Ø± Ø¨Ø§ Ù‚Ø§Ø¨Ù„ÛŒØª Ø§ÛŒØ²ÙˆÙ„Ø§Ø³ÛŒÙˆÙ† Ø¨Ø± Ø§Ø³Ø§Ø³ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ ÛŒØ§ Ù…Ø¯ÛŒØ±ÛŒØª"""
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
        """Ø¨Ø±ÙˆØ²Ø±Ø³Ø§Ù†ÛŒ Ø§Ø´ØªØ±Ø§Ú©"""
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
        """Ù„ØºÙˆ Ø§Ø´ØªØ±Ø§Ú©"""
        return self.update_subscription(subscription_id, status="cancelled")

    def update_subscription_by_uuid(self, hidify_uuid, **kwargs):
        """Ø¨Ø±ÙˆØ²Ø±Ø³Ø§Ù†ÛŒ Ø§Ø´ØªØ±Ø§Ú© Ø¨Ø± Ø§Ø³Ø§Ø³ hidify_uuid"""
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

    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    # Ù…Ø¯ÛŒØ±ÛŒØª ØªØ±Ø§Ú©Ù†Ø´â€ŒÙ‡Ø§
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

    def save_transaction(self, order_id, user_id, username, plan_name, amount, gateway, tracking_code, status="pending", account_name=None, account_comment=None, is_renewal=0, renew_sub_id=None, discount_code=None, receipt_image=None, receipt_file_type=None, reseller_id=None, notes=None, source="telegram", **kwargs):
        """Ø°Ø®ÛŒØ±Ù‡ ØªØ±Ø§Ú©Ù†Ø´"""
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
            
            # Ø°Ø®ÛŒØ±Ù‡ Ø¨Ú©â€ŒØ¢Ù¾ ÙÙˆØ±ÛŒ
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
        """Ø¨Ø±ÙˆØ²Ø±Ø³Ø§Ù†ÛŒ ÙˆØ¶Ø¹ÛŒØª Ùˆ Ù…Ø´Ø®ØµØ§Øª ØªØ±Ø§Ú©Ù†Ø´ (Ù…Ù†Ø¹Ø·Ù Ùˆ Ø¬Ø§Ù…Ø¹)"""
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
        """Ø¯Ø±ÛŒØ§ÙØª ØªØ±Ø§Ú©Ù†Ø´â€ŒÙ‡Ø§ÛŒ Ú©Ø§Ø±Ø¨Ø±"""
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
        """Ø¯Ø±ÛŒØ§ÙØª ØªØ±Ø§Ú©Ù†Ø´ Ø¨Ø± Ø§Ø³Ø§Ø³ order_id"""
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
        """Ø¯Ø±ÛŒØ§ÙØª ØªØ±Ø§Ú©Ù†Ø´ Ø¨Ø± Ø§Ø³Ø§Ø³ tracking_code (Ø´Ù†Ø§Ø³Ù‡ ÙØ§Ú©ØªÙˆØ± / Ø§Ø±Ø¬Ø§Ø¹ Ø¯Ø±Ú¯Ø§Ù‡)"""
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
        """Ø¯Ø±ÛŒØ§ÙØª ØªØ±Ø§Ú©Ù†Ø´â€ŒÙ‡Ø§ÛŒ Ø¯Ø± Ø§Ù†ØªØ¸Ø§Ø±"""
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
        Ø§Ø¨Ø·Ø§Ù„ ØªØ±Ø§Ú©Ù†Ø´ ØªÙˆØ³Ø· Ù…Ø¯ÛŒØ± Ø§Ø±Ø´Ø¯ Ø¨Ø§ Ø«Ø¨Øª ØªØ§Ø±ÛŒØ®Ú†Ù‡ØŒ Ú©Ø³Ø± Ø§Ø² Ø¯Ø±Ø¢Ù…Ø¯ØŒ Ø§ØµÙ„Ø§Ø­ ØªØ±Ø§Ø² Ù…Ø§Ù„ÛŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ Ùˆ Ø§Ù…Ú©Ø§Ù† Ø±ÙˆÙ„â€ŒØ¨Ú© Ø§Ø´ØªØ±Ø§Ú©
        rollback_sub_action: 'keep', 'disable', 'delete'
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            tx = cursor.execute("SELECT * FROM transactions WHERE id=?", (tx_id,)).fetchone()
            if not tx:
                return {"success": False, "error": "ØªØ±Ø§Ú©Ù†Ø´ ÛŒØ§ÙØª Ù†Ø´Ø¯."}

            tx = dict(tx)
            if tx["status"] == "revoked":
                return {"success": False, "error": "Ø§ÛŒÙ† ØªØ±Ø§Ú©Ù†Ø´ Ù‚Ø¨Ù„Ø§Ù‹ Ø¨Ø§Ø·Ù„ Ø´Ø¯Ù‡ Ø§Ø³Øª."}

            old_status = tx["status"]
            now_iso = get_now_iso()

            # Û±. ØªØºÛŒÛŒØ± ÙˆØ¶Ø¹ÛŒØª ØªØ±Ø§Ú©Ù†Ø´ Ø¨Ù‡ revoked
            cursor.execute("""
                UPDATE transactions
                SET status='revoked', revoked_at=?, revoked_by=?, revoke_reason=?, updated_at=?
                WHERE id=?
            """, (now_iso, admin_name, reason, now_iso, tx_id))

            # Û². Ø«Ø¨Øª Ù„Ø§Ú¯ Ø­Ø³Ø§Ø¨Ø±Ø³ÛŒ
            cursor.execute("""
                INSERT INTO transaction_audit_logs 
                (transaction_id, admin_id, admin_name, action, field_name, old_value, new_value, reason, created_at)
                VALUES (?, ?, ?, 'revoke', 'status', ?, 'revoked', ?, ?)
            """, (tx_id, admin_id, admin_name, old_status, reason, now_iso))

            # Û³. Ø¯Ø± ØµÙˆØ±Øª ØªØ§ÛŒÛŒØ¯ Ù‚Ø¨Ù„ÛŒ ÙÛŒØ´ØŒ Ø§ØµÙ„Ø§Ø­ Ùˆ Ø¨Ø§Ø²Ù†Ú¯Ø±ÛŒ Ø¯Ø± Ø³ÛŒØ³ØªÙ… Ù…Ø§Ù„ÛŒ:
            if old_status in ("approved", "completed"):
                r_id = tx["reseller_id"]
                is_bundle = (tx.get("gateway") == "bundle_reseller" or str(tx.get("order_id") or "").startswith("R_BUNDLE"))
                if r_id and is_bundle:
                    # ÛŒØ§ÙØªÙ† ØªØ±Ø§Ú©Ù†Ø´ ÙˆØ§Ø±ÛŒØ² Ø¨Ø³ØªÙ‡ Ø§Ø¹ØªØ¨Ø§Ø±ÛŒ
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

                # Ø§Ø¨Ø·Ø§Ù„ ÛŒØ§ Ø®Ù†Ø«ÛŒâ€ŒØ³Ø§Ø²ÛŒ Ø³Ù†Ø¯ Ø¯Ø± Ø³ÛŒØ³ØªÙ… Ø­Ø³Ø§Ø¨Ø¯Ø§Ø±ÛŒ
                try:
                    cursor.execute("""
                        UPDATE accounting_records
                        SET amount = 0, is_edited = 1, edited_by = ?, edited_at = ?,
                            description = COALESCE(description, '') || ' [Ø¨Ø§Ø·Ù„ Ø´Ø¯Ù‡ ØªÙˆØ³Ø· Ù…Ø¯ÛŒØ±ÛŒØª]'
                        WHERE (ref_type = 'transaction' AND ref_id = ?)
                           OR title LIKE ?
                    """, (admin_name, now_iso, str(tx_id), f"%{tx['order_id']}%"))
                except Exception:
                    pass

            # Û´. ÛŒØ§ÙØªÙ† Ø§Ø´ØªØ±Ø§Ú© Ù…Ø±ØªØ¨Ø·
            sub_id = tx["subscription_id"]
            associated_sub = None
            if sub_id:
                associated_sub = cursor.execute("SELECT * FROM subscriptions WHERE id=?", (sub_id,)).fetchone()
            elif tx["user_id"] and tx["account_name"]:
                # Ø¬Ø³ØªØ¬ÙˆÛŒ Ø§Ø´ØªØ±Ø§Ú© Ø¨Ø± Ø§Ø³Ø§Ø³ user_id Ùˆ account_name
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
        """ÙˆÛŒØ±Ø§ÛŒØ´ Ù…Ø´Ø®ØµØ§Øª ÙÛŒØ´ Ø¨Ø§ Ø«Ø¨Øª Ø¯Ù‚ÛŒÙ‚ Ù„Ø§Ú¯ Ø­Ø³Ø§Ø¨Ø±Ø³ÛŒ (Ù‚Ø¨Ù„ Ùˆ Ø¨Ø¹Ø¯)ØŒ Ø¨Ø±Ú†Ø³Ø¨ ÙˆÛŒØ±Ø§ÛŒØ´ØŒ Ùˆ Ø§Ø¹Ù…Ø§Ù„ ØªØºÛŒÛŒØ±Ø§Øª Ù…Ø§Ù„ÛŒ"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            tx = cursor.execute("SELECT * FROM transactions WHERE id=?", (tx_id,)).fetchone()
            if not tx:
                return {"success": False, "error": "ØªØ±Ø§Ú©Ù†Ø´ ÛŒØ§ÙØª Ù†Ø´Ø¯."}

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
                return {"success": True, "message": "Ù‡ÛŒÚ† ØªØºÛŒÛŒØ±ÛŒ Ø§Ø¹Ù…Ø§Ù„ Ù†Ø´Ø¯."}

            fields_to_update["is_edited"] = 1
            fields_to_update["edited_by"] = admin_name
            fields_to_update["edited_at"] = now_iso
            fields_to_update["edit_reason"] = reason
            fields_to_update["updated_at"] = now_iso

            set_clause = ", ".join([f"{k}=?" for k in fields_to_update.keys()])
            values = list(fields_to_update.values()) + [tx_id]

            cursor.execute(f"UPDATE transactions SET {set_clause} WHERE id=?", values)

            # Ø¯Ø± ØµÙˆØ±Øª ØªØºÛŒÛŒØ± Ù…Ø¨Ù„Øº ÙÛŒØ´â€ŒÙ‡Ø§ÛŒ ØªØ§ÛŒÛŒØ¯ Ø´Ø¯Ù‡ØŒ Ø§Ø¹Ù…Ø§Ù„ ØªØ±Ø§Ø² Ø¯Ø± Ø­Ø³Ø§Ø¨Ø¯Ø§Ø±ÛŒ Ùˆ ØªØ±Ø§Ø² Ú©ÛŒÙ Ù¾ÙˆÙ„ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡
            if int_amt is not None and tx["status"] in ("approved", "completed"):
                delta = int_amt - tx["amount"]
                r_id = tx["reseller_id"]
                is_bundle = (tx.get("gateway") == "bundle_reseller" or str(tx.get("order_id") or "").startswith("R_BUNDLE"))
                if r_id and is_bundle and delta != 0:
                    cursor.execute("UPDATE resellers SET balance = balance + ?, updated_at=? WHERE id=?", (delta, now_iso, r_id))
                    t_type = "deposit" if delta > 0 else "refund"
                    t_desc = f"ØªØ¹Ø¯ÛŒÙ„ Ù…ÙˆØ¬ÙˆØ¯ÛŒ Ø¨Ù‡ Ø¹Ù„Øª ÙˆÛŒØ±Ø§ÛŒØ´ Ù…Ø¨Ù„Øº Ø³ÙØ§Ø±Ø´ #{tx['order_id']} ØªÙˆØ³Ø· Ù…Ø¯ÛŒØ±ÛŒØª ({delta:+,} ØªÙˆÙ…Ø§Ù†)"
                    cursor.execute("""
                        INSERT INTO reseller_transactions (reseller_id, type, amount, plan_name, account_name, description, created_at)
                        VALUES (?, ?, ?, ?, '-', ?, ?)
                    """, (r_id, t_type, abs(delta), tx.get("plan_name"), t_desc, now_iso))

                # Ø¨Ù‡â€ŒØ±ÙˆØ²Ø±Ø³Ø§Ù†ÛŒ Ø³Ù†Ø¯ Ø¯Ø± Ø­Ø³Ø§Ø¨Ø¯Ø§Ø±ÛŒ
                try:
                    cursor.execute("""
                        UPDATE accounting_records
                        SET amount = ?, is_edited = 1, edited_by = ?, edited_at = ?
                        WHERE (ref_type = 'transaction' AND ref_id = ?)
                           OR title LIKE ?
                    """, (int_amt, admin_name, now_iso, str(tx_id), f"%{tx['order_id']}%"))
                except Exception:
                    pass

            # Ø«Ø¨Øª Ù„Ø§Ú¯ Ø­Ø³Ø§Ø¨Ø±Ø³ÛŒ Ø¨Ø±Ø§ÛŒ Ù‡Ø± ØªØºÛŒÛŒØ±
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
        """Ø­Ø°Ù Ù†Ø±Ù… ØªØ±Ø§Ú©Ù†Ø´ (Ø¢Ø±Ø´ÛŒÙˆ) Ø¨Ø§ Ø«Ø¨Øª Ù„Ø§Ú¯"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            tx = cursor.execute("SELECT * FROM transactions WHERE id=?", (tx_id,)).fetchone()
            if not tx:
                return {"success": False, "error": "ØªØ±Ø§Ú©Ù†Ø´ ÛŒØ§ÙØª Ù†Ø´Ø¯."}

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
        """Ø«Ø¨Øª Ù„Ø§Ú¯ Ø­Ø³Ø§Ø¨Ø±Ø³ÛŒ ØªØºÛŒÛŒØ±Ø§Øª Ùˆ Ø¹Ù…Ù„ÛŒØ§Øª Ø±ÙˆÛŒ ØªØ±Ø§Ú©Ù†Ø´"""
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
        """Ø¯Ø±ÛŒØ§ÙØª Ù„ÛŒØ³Øª Ù„Ø§Ú¯â€ŒÙ‡Ø§ÛŒ Ø­Ø³Ø§Ø¨Ø±Ø³ÛŒ ÛŒÚ© ØªØ±Ø§Ú©Ù†Ø´"""
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
        """ÙˆÛŒØ±Ø§ÛŒØ´ ØªØ±Ø§Ú©Ù†Ø´ Ú©ÛŒÙ Ù¾ÙˆÙ„ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ Ø¨Ø§ ØªØ¹Ø¯ÛŒÙ„ ØªØ±Ø§Ø² Ù…Ø§Ù„ÛŒ Ùˆ Ø«Ø¨Øª Ù„Ø§Ú¯ Ù‚Ø¨Ù„ Ùˆ Ø¨Ø¹Ø¯"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now_iso = get_now_iso()
        try:
            rtx = cursor.execute("SELECT * FROM reseller_transactions WHERE id=?", (rtx_id,)).fetchone()
            if not rtx:
                return {"success": False, "error": "ØªØ±Ø§Ú©Ù†Ø´ Ú©ÛŒÙ Ù¾ÙˆÙ„ ÛŒØ§ÙØª Ù†Ø´Ø¯."}

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

                        # ØªØ¹Ø¯ÛŒÙ„ Ù…ÙˆØ¬ÙˆØ¯ÛŒ Ú©ÛŒÙ Ù¾ÙˆÙ„ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ Ø¨Ø± Ø§Ø³Ø§Ø³ Ù†ÙˆØ¹ ØªØ±Ø§Ú©Ù†Ø´
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
                return {"success": True, "message": "Ù‡ÛŒÚ† ØªØºÛŒÛŒØ±ÛŒ Ø§Ø¹Ù…Ø§Ù„ Ù†Ø´Ø¯.", "reseller_id": reseller_id}

            updates["is_edited"] = 1
            updates["edited_by"] = admin_name
            updates["edited_at"] = now_iso
            updates["edit_reason"] = reason

            set_clause = ", ".join([f"{k}=?" for k in updates.keys()])
            values = list(updates.values()) + [rtx_id]
            cursor.execute(f"UPDATE reseller_transactions SET {set_clause} WHERE id=?", values)

            # Ø«Ø¨Øª Ø¯Ø± Ù„Ø§Ú¯ Ø­Ø³Ø§Ø¨Ø±Ø³ÛŒ
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
        """Ø§Ø¨Ø·Ø§Ù„ ØªØ±Ø§Ú©Ù†Ø´ Ú©ÛŒÙ Ù¾ÙˆÙ„ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ Ø¨Ø§ Ú©Ø³Ø±/Ø§Ø³ØªØ±Ø¯Ø§Ø¯ Ø®ÙˆØ¯Ú©Ø§Ø± Ø§Ø² ØªØ±Ø§Ø² Ù…Ø§Ù„ÛŒ Ú©ÛŒÙ Ù¾ÙˆÙ„"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now_iso = get_now_iso()
        try:
            rtx = cursor.execute("SELECT * FROM reseller_transactions WHERE id=?", (rtx_id,)).fetchone()
            if not rtx:
                return {"success": False, "error": "ØªØ±Ø§Ú©Ù†Ø´ Ú©ÛŒÙ Ù¾ÙˆÙ„ ÛŒØ§ÙØª Ù†Ø´Ø¯."}

            rtx_dict = dict(rtx)
            if rtx_dict.get("status") == "revoked" or rtx_dict.get("is_revoked"):
                return {"success": False, "error": "Ø§ÛŒÙ† ØªØ±Ø§Ú©Ù†Ø´ Ù‚Ø¨Ù„Ø§Ù‹ Ø¨Ø§Ø·Ù„ Ø´Ø¯Ù‡ Ø§Ø³Øª."}

            reseller_id = rtx_dict["reseller_id"]
            amount = rtx_dict["amount"] or 0
            ttype = rtx_dict["type"]

            # Û±. Ú©Ø³Ø± ÛŒØ§ Ø¨Ø§Ø²Ú¯Ø´Øª Ù…Ø¨Ù„Øº Ø¨Ù‡ Ù…ÙˆØ¬ÙˆØ¯ÛŒ Ú©ÛŒÙ Ù¾ÙˆÙ„ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡
            if ttype == "deposit":
                cursor.execute("UPDATE resellers SET balance = balance - ?, updated_at=? WHERE id=?", (amount, now_iso, reseller_id))
            elif ttype in ("purchase", "renewal"):
                cursor.execute("UPDATE resellers SET balance = balance + ?, updated_at=? WHERE id=?", (amount, now_iso, reseller_id))
            elif ttype == "refund":
                cursor.execute("UPDATE resellers SET balance = balance - ?, updated_at=? WHERE id=?", (amount, now_iso, reseller_id))

            # Û². Ø¹Ù„Ø§Ù…Øªâ€ŒÚ¯Ø°Ø§Ø±ÛŒ ØªØ±Ø§Ú©Ù†Ø´ Ø¨Ù‡ Ø¹Ù†ÙˆØ§Ù† Ø¨Ø§Ø·Ù„â€ŒØ´Ø¯Ù‡
            cursor.execute("""
                UPDATE reseller_transactions
                SET status='revoked', is_revoked=1, revoked_by=?, revoked_at=?, revoke_reason=?
                WHERE id=?
            """, (admin_name, now_iso, reason, rtx_id))

            # Û³. Ø«Ø¨Øª Ù„Ø§Ú¯ Ø­Ø³Ø§Ø¨Ø±Ø³ÛŒ
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
        """Ø¯Ø±ÛŒØ§ÙØª Ù„Ø§Ú¯â€ŒÙ‡Ø§ÛŒ Ø­Ø³Ø§Ø¨Ø±Ø³ÛŒ ÛŒÚ© ØªØ±Ø§Ú©Ù†Ø´ Ú©ÛŒÙ Ù¾ÙˆÙ„ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡"""
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

    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    # Ù…Ø¯ÛŒØ±ÛŒØª Ù„Ø§Ú¯â€ŒÙ‡Ø§ÛŒ ÙˆØ±ÙˆØ¯ØŒ Ø®Ø±ÙˆØ¬ Ùˆ Ø§Ù…Ù†ÛŒØª Ù†Ø´Ø³Øªâ€ŒÙ‡Ø§ (Login & Session Logs)
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

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
        """Ø«Ø¨Øª ØªÙ„Ø§Ø´ ÙˆØ±ÙˆØ¯ Ø¨Ù‡ Ø³ÛŒØ³ØªÙ… (Ù…ÙˆÙÙ‚ ÛŒØ§ Ù†Ø§Ù…ÙˆÙÙ‚)"""
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
        """Ø«Ø¨Øª Ø®Ø±ÙˆØ¬ Ø§Ø² Ø­Ø³Ø§Ø¨ Ùˆ ØºÛŒØ±ÙØ¹Ø§Ù„â€ŒØ³Ø§Ø²ÛŒ Ù†Ø´Ø³Øª"""
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
        """Ø¨Ø±ÙˆØ²Ø±Ø³Ø§Ù†ÛŒ Ø²Ù…Ø§Ù† Ø¢Ø®Ø±ÛŒÙ† ÙØ¹Ø§Ù„ÛŒØª Ù†Ø´Ø³Øª ÙØ¹Ø§Ù„"""
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
        """Ø¯Ø±ÛŒØ§ÙØª Ø³ÙˆØ§Ø¨Ù‚ ÙˆØ±ÙˆØ¯ Ùˆ Ù†Ø´Ø³Øªâ€ŒÙ‡Ø§ÛŒ ÛŒÚ© Ú©Ø§Ø±Ø¨Ø± ÛŒØ§ Ù…Ø¯ÛŒØ±"""
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
        """Ø¯Ø±ÛŒØ§ÙØª Ø³ÙˆØ§Ø¨Ù‚ Ú©Ø§Ù…Ù„ Ù†Ø´Ø³Øªâ€ŒÙ‡Ø§ Ùˆ ÙˆØ±ÙˆØ¯Ù‡Ø§ÛŒ Ù†Ø§Ù…ÙˆÙÙ‚ ÛŒÚ© Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            # Û±. Ù†Ø´Ø³Øªâ€ŒÙ‡Ø§ÛŒ Ù…ÙˆÙÙ‚
            cursor.execute("""
                SELECT * FROM login_logs
                WHERE user_type = 'reseller' AND user_id = ? AND status = 'success'
                ORDER BY id DESC LIMIT 20
            """, (reseller_id,))
            sessions = [dict(r) for r in cursor.fetchall()]

            # Û². ØªÙ„Ø§Ø´â€ŒÙ‡Ø§ÛŒ Ù†Ø§Ù…ÙˆÙÙ‚ Ø¨Ø§ Ø§ÛŒÙ† Ù†Ø§Ù… Ú©Ø§Ø±Ø¨Ø±ÛŒ
            cursor.execute("""
                SELECT * FROM login_logs
                WHERE username = ? AND status = 'failed'
                ORDER BY id DESC LIMIT 20
            """, (username,))
            failed_attempts = [dict(r) for r in cursor.fetchall()]

            # Û³. ÙˆØ¶Ø¹ÛŒØª Ø¢Ù†Ù„Ø§ÛŒÙ† Ø¨ÙˆØ¯Ù†
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
        """Ø¨Ø±Ø±Ø³ÛŒ Ø¢Ù†Ù„Ø§ÛŒÙ† Ø¨ÙˆØ¯Ù† Ú©Ø§Ø±Ø¨Ø±ØŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ ÛŒØ§ Ø²ÛŒØ±Ù…Ø¯ÛŒØ± Ø¨Ø± Ø§Ø³Ø§Ø³ Ø¢Ø®Ø±ÛŒÙ† ÙØ¹Ø§Ù„ÛŒØª Ø¯Ø± Ú†Ù†Ø¯ Ø¯Ù‚ÛŒÙ‚Ù‡ Ú¯Ø°Ø´ØªÙ‡"""
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
        """Ø¨Ø±Ø±Ø³ÛŒ Ø¢Ù†Ù„Ø§ÛŒÙ† Ø¨ÙˆØ¯Ù† Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ ÙØ±ÙˆØ´"""
        return self.is_user_online("reseller", reseller_id, threshold_minutes)

    def is_subadmin_online(self, admin_id: int, threshold_minutes: int = 15) -> bool:
        """Ø¨Ø±Ø±Ø³ÛŒ Ø¢Ù†Ù„Ø§ÛŒÙ† Ø¨ÙˆØ¯Ù† Ù…Ø¯ÛŒØ± Ú©Ù…Ú©ÛŒ ÛŒØ§ Ù¾Ø´ØªÛŒØ¨Ø§Ù† Ø²ÛŒØ±Ù…Ø¬Ù…ÙˆØ¹Ù‡ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡"""
        return self.is_user_online("reseller_subadmin", admin_id, threshold_minutes)

    def is_session_active(self, session_token: str) -> bool:
        """Ø¨Ø±Ø±Ø³ÛŒ ÙØ¹Ø§Ù„ Ø¨ÙˆØ¯Ù† Ù†Ø´Ø³Øª Ø¨Ø± Ø§Ø³Ø§Ø³ ØªÙˆÚ©Ù† Ù†Ø´Ø³Øª Ø¯Ø± Ù„Ø§Ú¯â€ŒÙ‡Ø§"""
        if not session_token:
            return False
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT is_active FROM login_logs WHERE session_token = ? ORDER BY id DESC LIMIT 1", (session_token,))
            row = cursor.fetchone()
            if not row:
                return True  # Ø¯Ø± ØµÙˆØ±Øª Ø¹Ø¯Ù… ÙˆØ¬ÙˆØ¯ Ù„Ø§Ú¯ Ù‚Ø¯ÛŒÙ…ÛŒ Ø¬Ù‡Øª Ø¬Ù„ÙˆÚ¯ÛŒØ±ÛŒ Ø§Ø² Ø®Ø±ÙˆØ¬ Ù†Ø§Ú¯Ù‡Ø§Ù†ÛŒ
            return bool(row["is_active"])
        except Exception:
            return True
        finally:
            conn.close()

    def terminate_session(self, session_id: int) -> bool:
        """Ø®Ø§ØªÙ…Ù‡ Ùˆ Ù‚Ø·Ø¹ ÙÙˆØ±ÛŒ ÛŒÚ© Ù†Ø´Ø³Øª ÙØ¹Ø§Ù„ Ø¨Ø± Ø§Ø³Ø§Ø³ Ø´Ù†Ø§Ø³Ù‡ Ù„Ø§Ú¯"""
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
        """Ø®Ø§ØªÙ…Ù‡ Ù†Ø´Ø³Øª ÙØ¹Ø§Ù„ Ø¨Ø± Ø§Ø³Ø§Ø³ ØªÙˆÚ©Ù†"""
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
        """Ø®Ø§ØªÙ…Ù‡ ØªÙ…Ø§Ù… Ù†Ø´Ø³Øªâ€ŒÙ‡Ø§ÛŒ ÙØ¹Ø§Ù„ ÛŒÚ© Ú©Ø§Ø±Ø¨Ø±ØŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ ÛŒØ§ Ø²ÛŒØ±Ù…Ø¯ÛŒØ± (Ø¨Ø§ Ø§Ù…Ú©Ø§Ù† Ù…Ø³ØªØ«Ù†ÛŒ Ú©Ø±Ø¯Ù† Ù†Ø´Ø³Øª ÙØ¹Ù„ÛŒ)"""
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
        """Ø®Ø§ØªÙ…Ù‡ Ú©Ù„ÛŒÙ‡ Ù†Ø´Ø³Øªâ€ŒÙ‡Ø§ÛŒ ÙØ¹Ø§Ù„ ÛŒÚ© Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ Ùˆ ØªÙ…Ø§Ù…ÛŒ Ø§Ø¹Ø¶Ø§ÛŒ ØªÛŒÙ… Ø²ÛŒØ±Ù…Ø¬Ù…ÙˆØ¹Ù‡ ÙˆÛŒ"""
        count = self.terminate_all_user_sessions("reseller", reseller_id)
        team_members = self.get_reseller_team_members(reseller_id)
        for m in team_members:
            count += self.terminate_all_user_sessions("reseller_subadmin", m["id"])
        return count

    def get_all_failed_login_logs(self, limit: int = 50) -> list:
        """Ø¯Ø±ÛŒØ§ÙØª ØªÙ…Ø§Ù… ØªÙ„Ø§Ø´â€ŒÙ‡Ø§ÛŒ Ù†Ø§Ù…ÙˆÙÙ‚ ÙˆØ±ÙˆØ¯ Ø¨Ù‡ Ø³ÛŒØ³ØªÙ… Ø¨Ø±Ø§ÛŒ Ù…Ø§Ù†ÛŒØªÙˆØ±ÛŒÙ†Ú¯ Ø§Ù…Ù†ÛŒØªÛŒ Ù…Ø¯ÛŒØ± Ú©Ù„"""
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

    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    # Ø³Ø§Ù…Ø§Ù†Ù‡ Ø«Ø¨Øª ÙˆÙ‚Ø§ÛŒØ¹ Ùˆ Ø­Ø³Ø§Ø¨Ø±Ø³ÛŒ ÙØ¹Ø§Ù„ÛŒØªâ€ŒÙ‡Ø§ÛŒ Ø³ÛŒØ³ØªÙ… (System Activity & Audit Logs)
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

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
        Ø«Ø¨Øª ÛŒÚ© Ø±ÙˆÛŒØ¯Ø§Ø¯ Ø¯Ø± Ø³Ø§Ù…Ø§Ù†Ù‡ Ù„Ø§Ú¯ Ùˆ Ø­Ø³Ø§Ø¨Ø±Ø³ÛŒ Ø³ÛŒØ³ØªÙ…
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
        Ø¯Ø±ÛŒØ§ÙØª Ù„ÛŒØ³Øª Ù„Ø§Ú¯â€ŒÙ‡Ø§ÛŒ Ø³ÛŒØ³ØªÙ… Ø¨Ø§ ÙÛŒÙ„ØªØ±Ù‡Ø§ÛŒ Ú†Ù†Ø¯Ú¯Ø§Ù†Ù‡ Ùˆ ØµÙØ­Ù‡â€ŒØ¨Ù†Ø¯ÛŒ
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
        """Ù…Ø­Ø§Ø³Ø¨Ù‡ Ø¢Ù…Ø§Ø± Ú©Ù„Ø§Ù† Ù„Ø§Ú¯â€ŒÙ‡Ø§ Ø¨Ø±Ø§ÛŒ Ú©Ø§Ø±Øªâ€ŒÙ‡Ø§ÛŒ Ø´Ø§Ø®Øµ (KPI)"""
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
        """Ù¾Ø§Ú©Ø³Ø§Ø²ÛŒ Ù„Ø§Ú¯â€ŒÙ‡Ø§ÛŒ Ù‚Ø¯ÛŒÙ…ÛŒâ€ŒØªØ± Ø§Ø² ØªØ¹Ø¯Ø§Ø¯ Ø±ÙˆØ² Ù…Ø´Ø®Øµ Ø´Ø¯Ù‡"""
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

    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    # Ù…Ø¯ÛŒØ±ÛŒØª ØªÙ†Ø¸ÛŒÙ…Ø§Øª
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

    def save_setting(self, key, value):
        """Ø°Ø®ÛŒØ±Ù‡ ØªÙ†Ø¸ÛŒÙ…"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()

        try:
            # ØªØ¨Ø¯ÛŒÙ„ dict/list Ø¨Ù‡ JSON
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
        """Ù†Ø§Ù… Ù…Ø³ØªØ¹Ø§Ø± Ø¨Ø±Ø§ÛŒ save_setting"""
        return self.save_setting(key, value)

    def get_setting(self, key, default=None):
        """Ø¯Ø±ÛŒØ§ÙØª ØªÙ†Ø¸ÛŒÙ…"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
            row = cursor.fetchone()
            if row:
                value = row["value"]
                # ØªÙ„Ø§Ø´ Ø¨Ø±Ø§ÛŒ ØªØ¨Ø¯ÛŒÙ„ Ø§Ø² JSON
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
        """Ø¯Ø±ÛŒØ§ÙØª ØªÙ…Ø§Ù… ØªÙ†Ø¸ÛŒÙ…Ø§Øª"""
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
        """Ø¯Ø±ÛŒØ§ÙØª ØªÙ†Ø¸ÛŒÙ…Ø§Øª Ø¬Ø§Ù…Ø¹ Ù‚ÙˆØ§Ù†ÛŒÙ† Ø§Ø³ØªØ±Ø¯Ø§Ø¯ ÙˆØ¬Ù‡ Ùˆ Ø³Ù‚Ùâ€ŒÙ‡Ø§ÛŒ Ø¨Ø§Ø²Ú¯Ø±Ø¯Ø§Ù†ÛŒ"""
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
        """Ø°Ø®ÛŒØ±Ù‡ ØªÙ†Ø¸ÛŒÙ…Ø§Øª Ø¬Ø§Ù…Ø¹ Ù‚ÙˆØ§Ù†ÛŒÙ† Ø§Ø³ØªØ±Ø¯Ø§Ø¯ ÙˆØ¬Ù‡"""
        try:
            current = self.get_refund_settings()
            current.update(settings_dict)
            return self.save_setting("refund_settings", current)
        except Exception as e:
            logger.error(f"Error saving refund settings: {e}")
            return False

    def get_reseller_daily_restore_count(self, reseller_id: int) -> int:
        """ØªØ¹Ø¯Ø§Ø¯ Ø¯ÙØ¹Ø§Øª Ø¨Ø§Ø²Ú¯Ø±Ø¯Ø§Ù†ÛŒ Ø§Ø´ØªØ±Ø§Ú© Ø§Ø² Ø³Ø·Ù„ Ø²Ø¨Ø§Ù„Ù‡ ØªÙˆØ³Ø· Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ Ø¯Ø± ØªØ§Ø±ÛŒØ® Ø§Ù…Ø±ÙˆØ²"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            today_start = get_now_naive().strftime("%Y-%m-%d 00:00:00")
            cursor.execute("""
                SELECT COUNT(*) FROM reseller_transactions
                WHERE reseller_id = ?
                  AND type IN ('purchase', 'purchase_credit')
                  AND (description LIKE '%Ø¨Ø§Ø²Ú¯Ø±Ø¯Ø§Ù†ÛŒ%' OR description LIKE '%restore%')
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
        Ø¨Ø±Ø±Ø³ÛŒ Ø§ÛŒÙ†Ú©Ù‡ Ø¢ÛŒØ§ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ Ù…Ø¬Ø§Ø² Ø¨Ù‡ Ø¨Ø§Ø²Ú¯Ø±Ø¯Ø§Ù†ÛŒ Ø§Ø´ØªØ±Ø§Ú©â€ŒÙ‡Ø§ÛŒ Ø¯Ø±Ø®ÙˆØ§Ø³ØªÛŒ Ø¯Ø± Ø§Ù…Ø±ÙˆØ² Ù‡Ø³Øª ÛŒØ§ Ø®ÛŒØ±.
        Ø®Ø±ÙˆØ¬ÛŒ: (Ù…Ø¬Ø§Ø² Ø¨ÙˆØ¯Ù†, Ù¾ÛŒØ§Ù… Ø®Ø·Ø§, Ø³Ù‚Ù Ù…Ø¬Ø§Ø², ØªØ¹Ø¯Ø§Ø¯ Ø§Ù†Ø¬Ø§Ù…â€ŒØ´Ø¯Ù‡)
        """
        settings = self.get_refund_settings()
        custom_limits = settings.get("reseller_daily_restore_limits", {})
        default_limit = int(settings.get("daily_restore_limit", 10))

        r_key = str(reseller_id)
        if r_key in custom_limits and custom_limits[r_key] is not None:
            limit = int(custom_limits[r_key])
        else:
            limit = default_limit

        # Ø¹Ø¯Ø¯ Û° Ø¨Ù‡ Ù…Ø¹Ù†Ø§ÛŒ Ø¨Ø¯ÙˆÙ† Ù…Ø­Ø¯ÙˆØ¯ÛŒØª Ø§Ø³Øª
        if limit <= 0:
            return (True, "", 0, 0)

        current_count = self.get_reseller_daily_restore_count(reseller_id)
        if current_count + count_to_restore > limit:
            remaining = max(0, limit - current_count)
            err = f"Ø³Ù‚Ù Ù…Ø¬Ø§Ø² Ø¨Ø§Ø²Ú¯Ø±Ø¯Ø§Ù†ÛŒ Ø±ÙˆØ²Ø§Ù†Ù‡ Ø´Ù…Ø§ ({limit} Ø¨Ø§Ø± Ø¯Ø± Ø±ÙˆØ²) ØªÚ©Ù…ÛŒÙ„ Ø´Ø¯Ù‡ Ø§Ø³Øª. Ø¨Ø§Ø²Ú¯Ø±Ø¯Ø§Ù†ÛŒâ€ŒÙ‡Ø§ÛŒ Ø§Ù…Ø±ÙˆØ² Ø´Ù…Ø§: {current_count} Ù…ÙˆØ±Ø¯ | Ø¸Ø±ÙÛŒØª Ø¨Ø§Ù‚ÛŒÙ…Ø§Ù†Ø¯Ù‡ Ø§Ù…Ø±ÙˆØ²: {remaining} Ù…ÙˆØ±Ø¯."
            return (False, err, limit, current_count)

        return (True, "", limit, current_count)

    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    # Ù…Ø¯ÛŒØ±ÛŒØª Ùˆ Ú†ÛŒØ¯Ù…Ø§Ù† Ø³ÙØ§Ø±Ø´ÛŒ Ø¯Ú©Ù…Ù‡â€ŒÙ‡Ø§ Ùˆ Ù…Ù†ÙˆÛŒ Ø±Ø¨Ø§Øª (Bot Menu Customizer)
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

    DEFAULT_BOT_MENU_BUTTONS = [
        {
            "id": "buy",
            "title": "ðŸ›ï¸ Ø®Ø±ÛŒØ¯ Ø§Ø´ØªØ±Ø§Ú©",
            "description": "Ù†Ù…Ø§ÛŒØ´ ØªØ¹Ø±ÙÙ‡â€ŒÙ‡Ø§ Ùˆ Ø®Ø±ÛŒØ¯ Ø§Ø´ØªØ±Ø§Ú© VPN",
            "row": 0,
            "col": 0,
            "is_enabled": True,
            "disabled_behavior": "show_disabled",
            "disabled_message": "âš ï¸ Ø¨Ø®Ø´ Ø®Ø±ÛŒØ¯ Ø§Ø´ØªØ±Ø§Ú© Ù…ÙˆÙ‚ØªØ§Ù‹ ØºÛŒØ±ÙØ¹Ø§Ù„ Ù…ÛŒâ€ŒØ¨Ø§Ø´Ø¯. Ù„Ø·ÙØ§Ù‹ Ø¯Ù‚Ø§ÛŒÙ‚ÛŒ Ø¯ÛŒÚ¯Ø± Ù…Ø±Ø§Ø¬Ø¹Ù‡ ÙØ±Ù…Ø§ÛŒÛŒØ¯.",
        },
        {
            "id": "my_subs",
            "title": "ðŸ‘¤ Ø§Ø´ØªØ±Ø§Ú©â€ŒÙ‡Ø§ÛŒ Ù…Ù†",
            "description": "Ù…Ø´Ø§Ù‡Ø¯Ù‡ ÙˆØ¶Ø¹ÛŒØª ØªØ±Ø§ÙÛŒÚ©ØŒ Ø²Ù…Ø§Ù† Ùˆ Ù„ÛŒÙ†Ú©â€ŒÙ‡Ø§ÛŒ Ø§ØªØµØ§Ù„ Ú©Ø§Ø±Ø¨Ø±",
            "row": 0,
            "col": 1,
            "is_enabled": True,
            "disabled_behavior": "show_disabled",
            "disabled_message": "âš ï¸ Ø¨Ø®Ø´ Ø§Ø´ØªØ±Ø§Ú©â€ŒÙ‡Ø§ÛŒ Ù…Ù† Ù…ÙˆÙ‚ØªØ§Ù‹ Ø¯Ø± Ø­Ø§Ù„ Ø¨Ø±ÙˆØ²Ø±Ø³Ø§Ù†ÛŒ Ø§Ø³Øª.",
        },
        {
            "id": "test_sub",
            "title": "âš¡ ØªØ³Øª Ø±Ø§ÛŒÚ¯Ø§Ù†",
            "description": "Ø¯Ø±ÛŒØ§ÙØª Ú©Ø§Ù†ÙÛŒÚ¯ ØªØ³Øª Ø±Ø§ÛŒÚ¯Ø§Ù† Ø¨Ø±Ø§ÛŒ Ú©Ø§Ø±Ø¨Ø±Ø§Ù† Ø¬Ø¯ÛŒØ¯",
            "row": 1,
            "col": 0,
            "is_enabled": True,
            "disabled_behavior": "hide",
            "disabled_message": "âš ï¸ Ø§Ø´ØªØ±Ø§Ú© ØªØ³Øª Ù…ÙˆÙ‚ØªØ§Ù‹ ØºÛŒØ±ÙØ¹Ø§Ù„ Ø§Ø³Øª.",
        },
        {
            "id": "renew",
            "title": "ðŸ”„ ØªÙ…Ø¯ÛŒØ¯ Ø³Ø±ÙˆÛŒØ³",
            "description": "ØªÙ…Ø¯ÛŒØ¯ Ø³Ø±ÛŒØ¹ Ø§Ú©Ø§Ù†Øªâ€ŒÙ‡Ø§ÛŒ Ù…ÙˆØ¬ÙˆØ¯ Ø¨Ø¯ÙˆÙ† ØªØºÛŒÛŒØ± Ù„ÛŒÙ†Ú©",
            "row": 1,
            "col": 1,
            "is_enabled": True,
            "disabled_behavior": "show_disabled",
            "disabled_message": "âš ï¸ Ø¨Ø®Ø´ ØªÙ…Ø¯ÛŒØ¯ Ø³Ø±ÙˆÛŒØ³ Ù…ÙˆÙ‚ØªØ§Ù‹ ØºÛŒØ±ÙØ¹Ø§Ù„ Ø§Ø³Øª.",
        },
        {
            "id": "wallet",
            "title": "ðŸ’³ Ú©ÛŒÙ Ù¾ÙˆÙ„ Ùˆ Ø´Ø§Ø±Ú˜",
            "description": "Ù…Ø´Ø§Ù‡Ø¯Ù‡ Ù…ÙˆØ¬ÙˆØ¯ÛŒ Ú©ÛŒÙ Ù¾ÙˆÙ„ Ùˆ Ø´Ø§Ø±Ú˜ Ø§Ø¹ØªØ¨Ø§Ø±",
            "row": 2,
            "col": 0,
            "is_enabled": True,
            "disabled_behavior": "show_disabled",
            "disabled_message": "âš ï¸ Ø¨Ø®Ø´ Ú©ÛŒÙ Ù¾ÙˆÙ„ Ù…ÙˆÙ‚ØªØ§Ù‹ Ø¯Ø± Ø¯Ø³ØªØ±Ø³ Ù†ÛŒØ³Øª.",
        },
        {
            "id": "support",
            "title": "ðŸŽ§ Ù¾Ø´ØªÛŒØ¨Ø§Ù†ÛŒ Ùˆ ØªÛŒÚ©Øª",
            "description": "Ø§Ø±Ø³Ø§Ù„ ØªÛŒÚ©Øª Ùˆ Ù¾ÛŒØ§Ù… Ø¨Ù‡ Ø§Ù¾Ø±Ø§ØªÙˆØ±Ù‡Ø§",
            "row": 2,
            "col": 1,
            "is_enabled": True,
            "disabled_behavior": "show_disabled",
            "disabled_message": "âš ï¸ Ù¾Ø´ØªÛŒØ¨Ø§Ù†ÛŒ Ù…ÙˆÙ‚ØªØ§Ù‹ ØºÛŒØ±ÙØ¹Ø§Ù„ Ø§Ø³Øª.",
        },
        {
            "id": "tutorials",
            "title": "ðŸ“– Ø±Ø§Ù‡Ù†Ù…Ø§ÛŒ Ø§ØªØµØ§Ù„",
            "description": "Ø¢Ù…ÙˆØ²Ø´â€ŒÙ‡Ø§ÛŒ ØªØµÙˆÛŒØ±ÛŒ Ø§ØªØµØ§Ù„ Ø¨Ø±Ø§ÛŒ Ø§Ù†Ø¯Ø±ÙˆÛŒØ¯ØŒ Ø¢ÛŒÙÙˆÙ†ØŒ ÙˆÛŒÙ†Ø¯ÙˆØ² Ùˆ...",
            "row": 3,
            "col": 0,
            "is_enabled": True,
            "disabled_behavior": "show_disabled",
            "disabled_message": "âš ï¸ Ø¨Ø®Ø´ Ø±Ø§Ù‡Ù†Ù…Ø§ÛŒ Ø§ØªØµØ§Ù„ Ø¯Ø± Ø­Ø§Ù„ Ø¨Ø±ÙˆØ²Ø±Ø³Ø§Ù†ÛŒ Ø§Ø³Øª.",
        },
        {
            "id": "troubleshoot",
            "title": "ðŸ› ï¸ Ø­Ù„ Ù…Ø´Ú©Ù„Ø§Øª Ø§ØªØµØ§Ù„",
            "description": "ÙˆÛŒØ²Ø§Ø±Ø¯ Ø¹ÛŒØ¨â€ŒÛŒØ§Ø¨ÛŒ Ùˆ Ø±ÙØ¹ Ù‚Ø·Ø¹ÛŒ Ø§ÛŒÙ†ØªØ±Ù†Øª",
            "row": 3,
            "col": 1,
            "is_enabled": True,
            "disabled_behavior": "show_disabled",
            "disabled_message": "âš ï¸ Ø³Ø§Ù…Ø§Ù†Ù‡ Ø­Ù„ Ù…Ø´Ú©Ù„Ø§Øª Ø§ØªØµØ§Ù„ Ù…ÙˆÙ‚ØªØ§Ù‹ Ø¯Ø± Ø¯Ø³ØªØ±Ø³ Ù†ÛŒØ³Øª.",
        },
        {
            "id": "referral",
            "title": "ðŸ‘¥ Ú©Ø³Ø¨ Ø¯Ø±Ø¢Ù…Ø¯ Ùˆ Ø¯Ø¹ÙˆØª",
            "description": "Ø¯Ø±ÛŒØ§ÙØª Ù„ÛŒÙ†Ú© Ø²ÛŒØ±Ù…Ø¬Ù…ÙˆØ¹Ù‡â€ŒÚ¯ÛŒØ±ÛŒ Ùˆ Ù¾ÙˆØ±Ø³Ø§Ù†Øª",
            "row": 4,
            "col": 0,
            "is_enabled": True,
            "disabled_behavior": "hide",
            "disabled_message": "âš ï¸ Ø³ÛŒØ³ØªÙ… Ø²ÛŒØ±Ù…Ø¬Ù…ÙˆØ¹Ù‡â€ŒÚ¯ÛŒØ±ÛŒ Ù…ÙˆÙ‚ØªØ§Ù‹ ØºÛŒØ±ÙØ¹Ø§Ù„ Ø§Ø³Øª.",
        },
        {
            "id": "payments",
            "title": "ðŸ§¾ Ø³Ø§Ø¨Ù‚Ù‡ Ù¾Ø±Ø¯Ø§Ø®Øªâ€ŒÙ‡Ø§",
            "description": "Ù…Ø´Ø§Ù‡Ø¯Ù‡ ØªØ±Ø§Ú©Ù†Ø´â€ŒÙ‡Ø§ Ùˆ ÙÛŒØ´â€ŒÙ‡Ø§ÛŒ Ø§Ø±Ø³Ø§Ù„ÛŒ Ú©Ø§Ø±Ø¨Ø±",
            "row": 4,
            "col": 1,
            "is_enabled": True,
            "disabled_behavior": "hide",
            "disabled_message": "âš ï¸ Ø¨Ø®Ø´ Ø³Ø§Ø¨Ù‚Ù‡ Ù¾Ø±Ø¯Ø§Ø®Øªâ€ŒÙ‡Ø§ Ù…ÙˆÙ‚ØªØ§Ù‹ ØºÛŒØ±ÙØ¹Ø§Ù„ Ø§Ø³Øª.",
        },
        {
            "id": "language",
            "title": "ðŸŒ ØªØºÛŒÛŒØ± Ø²Ø¨Ø§Ù†",
            "description": "ØªØºÛŒÛŒØ± Ø²Ø¨Ø§Ù† Ø±Ø¨Ø§Øª Ø¨Ù‡ Ø²Ø¨Ø§Ù†â€ŒÙ‡Ø§ÛŒ Ø¯ÛŒÚ¯Ø±",
            "row": 5,
            "col": 0,
            "is_enabled": True,
            "disabled_behavior": "hide",
            "disabled_message": "âš ï¸ Ù‚Ø§Ø¨Ù„ÛŒØª ØªØºÛŒÛŒØ± Ø²Ø¨Ø§Ù† Ù…ÙˆÙ‚ØªØ§Ù‹ ØºÛŒØ±ÙØ¹Ø§Ù„ Ø§Ø³Øª.",
        },
    ]

    DEFAULT_RESELLER_BOT_MENU_BUTTONS = [
        {
            "id": "buy",
            "title": "ðŸ›ï¸ Ø®Ø±ÛŒØ¯ Ø§Ø´ØªØ±Ø§Ú©",
            "description": "Ù†Ù…Ø§ÛŒØ´ ØªØ¹Ø±ÙÙ‡â€ŒÙ‡Ø§ Ùˆ Ø®Ø±ÛŒØ¯ Ø§Ø´ØªØ±Ø§Ú© VPN Ø§Ø² Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡",
            "row": 0,
            "col": 0,
            "is_enabled": True,
            "disabled_behavior": "show_disabled",
            "disabled_message": "âš ï¸ Ø¨Ø®Ø´ Ø®Ø±ÛŒØ¯ Ø§Ø´ØªØ±Ø§Ú© Ù…ÙˆÙ‚ØªØ§Ù‹ ØºÛŒØ±ÙØ¹Ø§Ù„ Ù…ÛŒâ€ŒØ¨Ø§Ø´Ø¯. Ù„Ø·ÙØ§Ù‹ Ø¯Ù‚Ø§ÛŒÙ‚ÛŒ Ø¯ÛŒÚ¯Ø± Ù…Ø±Ø§Ø¬Ø¹Ù‡ ÙØ±Ù…Ø§ÛŒÛŒØ¯.",
        },
        {
            "id": "my_subs",
            "title": "ðŸ‘¤ Ø§Ø´ØªØ±Ø§Ú©â€ŒÙ‡Ø§ÛŒ Ù…Ù†",
            "description": "Ù…Ø´Ø§Ù‡Ø¯Ù‡ ÙˆØ¶Ø¹ÛŒØª ØªØ±Ø§ÙÛŒÚ©ØŒ Ø²Ù…Ø§Ù†ØŒ Ù„ÛŒÙ†Ú©â€ŒÙ‡Ø§ Ùˆ Ø¨Ø§Ø±Ú©Ø¯ Ø§ØªØµØ§Ù„ Ú©Ø§Ø±Ø¨Ø±",
            "row": 0,
            "col": 1,
            "is_enabled": True,
            "disabled_behavior": "show_disabled",
            "disabled_message": "âš ï¸ Ø¨Ø®Ø´ Ø§Ø´ØªØ±Ø§Ú©â€ŒÙ‡Ø§ÛŒ Ù…Ù† Ù…ÙˆÙ‚ØªØ§Ù‹ Ø¯Ø± Ø­Ø§Ù„ Ø¨Ø±ÙˆØ²Ø±Ø³Ø§Ù†ÛŒ Ø§Ø³Øª.",
        },
        {
            "id": "wallet",
            "title": "ðŸ’³ Ú©ÛŒÙ Ù¾ÙˆÙ„ Ùˆ Ø´Ø§Ø±Ú˜",
            "description": "Ù…Ø´Ø§Ù‡Ø¯Ù‡ Ù…ÙˆØ¬ÙˆØ¯ÛŒ Ú©ÛŒÙ Ù¾ÙˆÙ„ Ùˆ ÙˆØ¶Ø¹ÛŒØª Ø­Ø³Ø§Ø¨ Ú©Ø§Ø±Ø¨Ø±ÛŒ",
            "row": 1,
            "col": 0,
            "is_enabled": True,
            "disabled_behavior": "show_disabled",
            "disabled_message": "âš ï¸ Ø¨Ø®Ø´ Ú©ÛŒÙ Ù¾ÙˆÙ„ Ù…ÙˆÙ‚ØªØ§Ù‹ Ø¯Ø± Ø¯Ø³ØªØ±Ø³ Ù†ÛŒØ³Øª.",
        },
        {
            "id": "renew",
            "title": "ðŸ”„ ØªÙ…Ø¯ÛŒØ¯ Ø³Ø±ÙˆÛŒØ³",
            "description": "ØªÙ…Ø¯ÛŒØ¯ Ø³Ø±ÛŒØ¹ Ø§Ú©Ø§Ù†Øªâ€ŒÙ‡Ø§ÛŒ Ù…ÙˆØ¬ÙˆØ¯ Ø¨Ø¯ÙˆÙ† ØªØºÛŒÛŒØ± Ù„ÛŒÙ†Ú©",
            "row": 1,
            "col": 1,
            "is_enabled": True,
            "disabled_behavior": "show_disabled",
            "disabled_message": "âš ï¸ Ø¨Ø®Ø´ ØªÙ…Ø¯ÛŒØ¯ Ø³Ø±ÙˆÛŒØ³ Ù…ÙˆÙ‚ØªØ§Ù‹ ØºÛŒØ±ÙØ¹Ø§Ù„ Ø§Ø³Øª.",
        },
        {
            "id": "test_sub",
            "title": "âš¡ ØªØ³Øª Ø±Ø§ÛŒÚ¯Ø§Ù†",
            "description": "Ø¯Ø±ÛŒØ§ÙØª Ú©Ø§Ù†ÙÛŒÚ¯ ØªØ³Øª Ø±Ø§ÛŒÚ¯Ø§Ù† Ø¨Ø±Ø§ÛŒ Ú©Ø§Ø±Ø¨Ø±Ø§Ù† Ø¬Ø¯ÛŒØ¯",
            "row": 2,
            "col": 0,
            "is_enabled": True,
            "disabled_behavior": "hide",
            "disabled_message": "âš ï¸ Ø§Ø´ØªØ±Ø§Ú© ØªØ³Øª Ù…ÙˆÙ‚ØªØ§Ù‹ ØºÛŒØ±ÙØ¹Ø§Ù„ Ø§Ø³Øª.",
        },
        {
            "id": "support",
            "title": "ðŸŽ§ Ù¾Ø´ØªÛŒØ¨Ø§Ù†ÛŒ Ùˆ ØªÛŒÚ©Øª",
            "description": "Ø§Ø±Ø³Ø§Ù„ ØªÛŒÚ©Øª Ùˆ Ù¾ÛŒØ§Ù… Ù…Ø³ØªÙ‚ÛŒÙ… Ø¨Ù‡ Ù¾Ø´ØªÛŒØ¨Ø§Ù†ÛŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡",
            "row": 2,
            "col": 1,
            "is_enabled": True,
            "disabled_behavior": "show_disabled",
            "disabled_message": "âš ï¸ Ù¾Ø´ØªÛŒØ¨Ø§Ù†ÛŒ Ù…ÙˆÙ‚ØªØ§Ù‹ ØºÛŒØ±ÙØ¹Ø§Ù„ Ø§Ø³Øª.",
        },
        {
            "id": "tutorials",
            "title": "ðŸ“– Ø±Ø§Ù‡Ù†Ù…Ø§ÛŒ Ø§ØªØµØ§Ù„",
            "description": "Ø¢Ù…ÙˆØ²Ø´â€ŒÙ‡Ø§ÛŒ ØªØµÙˆÛŒØ±ÛŒ Ø§ØªØµØ§Ù„ Ø¨Ø±Ø§ÛŒ Ø§Ù†Ø¯Ø±ÙˆÛŒØ¯ØŒ Ø¢ÛŒÙÙˆÙ†ØŒ ÙˆÛŒÙ†Ø¯ÙˆØ² Ùˆ...",
            "row": 3,
            "col": 0,
            "is_enabled": True,
            "disabled_behavior": "show_disabled",
            "disabled_message": "âš ï¸ Ø¨Ø®Ø´ Ø±Ø§Ù‡Ù†Ù…Ø§ÛŒ Ø§ØªØµØ§Ù„ Ø¯Ø± Ø­Ø§Ù„ Ø¨Ø±ÙˆØ²Ø±Ø³Ø§Ù†ÛŒ Ø§Ø³Øª.",
        },
        {
            "id": "troubleshoot",
            "title": "ðŸ› ï¸ Ø­Ù„ Ù…Ø´Ú©Ù„Ø§Øª Ø§ØªØµØ§Ù„",
            "description": "ÙˆÛŒØ²Ø§Ø±Ø¯ Ø¹ÛŒØ¨â€ŒÛŒØ§Ø¨ÛŒ Ùˆ Ø±ÙØ¹ Ù‚Ø·Ø¹ÛŒ Ø§ÛŒÙ†ØªØ±Ù†Øª",
            "row": 3,
            "col": 1,
            "is_enabled": True,
            "disabled_behavior": "show_disabled",
            "disabled_message": "âš ï¸ Ø³Ø§Ù…Ø§Ù†Ù‡ Ø­Ù„ Ù…Ø´Ú©Ù„Ø§Øª Ø§ØªØµØ§Ù„ Ù…ÙˆÙ‚ØªØ§Ù‹ Ø¯Ø± Ø¯Ø³ØªØ±Ø³ Ù†ÛŒØ³Øª.",
        },
        {
            "id": "payments",
            "title": "ðŸ§¾ Ø³Ø§Ø¨Ù‚Ù‡ Ù¾Ø±Ø¯Ø§Ø®Øªâ€ŒÙ‡Ø§",
            "description": "Ù…Ø´Ø§Ù‡Ø¯Ù‡ ØªØ±Ø§Ú©Ù†Ø´â€ŒÙ‡Ø§ Ùˆ ÙÛŒØ´â€ŒÙ‡Ø§ÛŒ Ø§Ø±Ø³Ø§Ù„ÛŒ Ú©Ø§Ø±Ø¨Ø±",
            "row": 4,
            "col": 0,
            "is_enabled": True,
            "disabled_behavior": "hide",
            "disabled_message": "âš ï¸ Ø¨Ø®Ø´ Ø³Ø§Ø¨Ù‚Ù‡ Ù¾Ø±Ø¯Ø§Ø®Øªâ€ŒÙ‡Ø§ Ù…ÙˆÙ‚ØªØ§Ù‹ ØºÛŒØ±ÙØ¹Ø§Ù„ Ø§Ø³Øª.",
        },
        {
            "id": "language",
            "title": "ðŸŒ ØªØºÛŒÛŒØ± Ø²Ø¨Ø§Ù†",
            "description": "ØªØºÛŒÛŒØ± Ø²Ø¨Ø§Ù† Ø±Ø¨Ø§Øª Ø¨Ù‡ Ø²Ø¨Ø§Ù†â€ŒÙ‡Ø§ÛŒ Ø¯ÛŒÚ¯Ø±",
            "row": 4,
            "col": 1,
            "is_enabled": True,
            "disabled_behavior": "hide",
            "disabled_message": "âš ï¸ Ù‚Ø§Ø¨Ù„ÛŒØª ØªØºÛŒÛŒØ± Ø²Ø¨Ø§Ù† Ù…ÙˆÙ‚ØªØ§Ù‹ ØºÛŒØ±ÙØ¹Ø§Ù„ Ø§Ø³Øª.",
        },
    ]

    def get_bot_menu_buttons(self) -> List[dict]:
        """Ø¯Ø±ÛŒØ§ÙØª Ù„ÛŒØ³Øª Ùˆ ØªÙ†Ø¸ÛŒÙ…Ø§Øª Ú†ÛŒØ¯Ù…Ø§Ù† Ø¯Ú©Ù…Ù‡â€ŒÙ‡Ø§ÛŒ Ù…Ù†ÙˆÛŒ Ø±Ø¨Ø§Øª Ù…Ø¯ÛŒØ±ÛŒØª"""
        saved = self.get_setting("bot_menu_buttons_config")
        if not saved or not isinstance(saved, list):
            return copy.deepcopy(self.DEFAULT_BOT_MENU_BUTTONS)

        # Ø§Ø¯ØºØ§Ù… Ø¨Ø§ Ø¯Ú©Ù…Ù‡â€ŒÙ‡Ø§ÛŒ Ù¾ÛŒØ´â€ŒÙØ±Ø¶ Ø¨Ø±Ø§ÛŒ Ø§Ø·Ù…ÛŒÙ†Ø§Ù† Ø§Ø² ÙˆØ¬ÙˆØ¯ ØªÙ…Ø§Ù… Ú©Ù„ÛŒØ¯Ù‡Ø§
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

        # Ù…Ø±ØªØ¨â€ŒØ³Ø§Ø²ÛŒ Ø¨Ø± Ø§Ø³Ø§Ø³ Ø³Ø·Ø± Ùˆ Ø³ØªÙˆÙ†
        merged.sort(key=lambda x: (int(x.get("row", 0)), int(x.get("col", 0))))
        return merged

    def save_bot_menu_buttons(self, buttons: List[dict]) -> bool:
        """Ø°Ø®ÛŒØ±Ù‡ ØªÙ†Ø¸ÛŒÙ…Ø§Øª Ùˆ Ú†ÛŒØ¯Ù…Ø§Ù† Ø¯Ú©Ù…Ù‡â€ŒÙ‡Ø§ÛŒ Ù…Ù†ÙˆÛŒ Ø§ØµÙ„ÛŒ Ø±Ø¨Ø§Øª Ù…Ø¯ÛŒØ±ÛŒØª"""
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
                    "disabled_message": str(b.get("disabled_message", "âš ï¸ Ø§ÛŒÙ† Ø¨Ø®Ø´ Ù…ÙˆÙ‚ØªØ§Ù‹ ØºÛŒØ±ÙØ¹Ø§Ù„ Ø§Ø³Øª.")).strip(),
                    "description": str(b.get("description", "")),
                })
            self.set_setting("bot_menu_buttons_config", clean_buttons)
            return True
        except Exception as e:
            logger.error(f"Error saving bot menu buttons: {e}")
            return False

    def reset_bot_menu_buttons(self) -> List[dict]:
        """Ø¨Ø§Ø²Ù†Ø´Ø§Ù†ÛŒ ØªÙ†Ø¸ÛŒÙ…Ø§Øª Ø¯Ú©Ù…Ù‡â€ŒÙ‡Ø§ÛŒ Ø±Ø¨Ø§Øª Ù…Ø¯ÛŒØ±ÛŒØª Ø¨Ù‡ Ø­Ø§Ù„Øª Ù¾ÛŒØ´â€ŒÙØ±Ø¶ Ø§ÙˆÙ„ÛŒÙ‡"""
        defaults = copy.deepcopy(self.DEFAULT_BOT_MENU_BUTTONS)
        self.set_setting("bot_menu_buttons_config", defaults)
        return defaults

    def get_reseller_bot_menu_buttons(self) -> List[dict]:
        """Ø¯Ø±ÛŒØ§ÙØª Ù„ÛŒØ³Øª Ùˆ ØªÙ†Ø¸ÛŒÙ…Ø§Øª Ú†ÛŒØ¯Ù…Ø§Ù† Ø¯Ú©Ù…Ù‡â€ŒÙ‡Ø§ÛŒ Ù…Ù†ÙˆÛŒ Ø±Ø¨Ø§Øªâ€ŒÙ‡Ø§ÛŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ú¯Ø§Ù†"""
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
        """Ø°Ø®ÛŒØ±Ù‡ ØªÙ†Ø¸ÛŒÙ…Ø§Øª Ùˆ Ú†ÛŒØ¯Ù…Ø§Ù† Ø¯Ú©Ù…Ù‡â€ŒÙ‡Ø§ÛŒ Ù…Ù†ÙˆÛŒ Ø±Ø¨Ø§Øªâ€ŒÙ‡Ø§ÛŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ú¯Ø§Ù†"""
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
                    "disabled_message": str(b.get("disabled_message", "âš ï¸ Ø§ÛŒÙ† Ø¨Ø®Ø´ Ù…ÙˆÙ‚ØªØ§Ù‹ ØºÛŒØ±ÙØ¹Ø§Ù„ Ø§Ø³Øª.")).strip(),
                    "description": str(b.get("description", "")),
                })
            self.set_setting("reseller_bot_menu_buttons_config", clean_buttons)
            return True
        except Exception as e:
            logger.error(f"Error saving reseller bot menu buttons: {e}")
            return False

    def reset_reseller_bot_menu_buttons(self) -> List[dict]:
        """Ø¨Ø§Ø²Ù†Ø´Ø§Ù†ÛŒ ØªÙ†Ø¸ÛŒÙ…Ø§Øª Ø¯Ú©Ù…Ù‡â€ŒÙ‡Ø§ÛŒ Ø±Ø¨Ø§Øª Ù†Ù…Ø§ÛŒÙ†Ø¯Ú¯Ø§Ù† Ø¨Ù‡ Ø­Ø§Ù„Øª Ù¾ÛŒØ´â€ŒÙØ±Ø¶ Ø§ÙˆÙ„ÛŒÙ‡"""
        defaults = copy.deepcopy(self.DEFAULT_RESELLER_BOT_MENU_BUTTONS)
        self.set_setting("reseller_bot_menu_buttons_config", defaults)
        return defaults

    def get_bot_menu_keyboard_rows(self, is_admin: bool = False, is_reseller: bool = False) -> List[List[dict]]:
        """Ø³Ø§Ø®Øª Ø³Ø·Ø±Ù‡Ø§ÛŒ Ú†ÛŒØ¯Ù…Ø§Ù† Ø¯Ú©Ù…Ù‡â€ŒÙ‡Ø§ÛŒ Ù…Ù†Ùˆ Ø¨Ø± Ø§Ø³Ø§Ø³ Ø³Ø·Ø± Ùˆ Ø³ØªÙˆÙ† Ùˆ ÙˆØ¶Ø¹ÛŒØª ÙØ¹Ø§Ù„ Ø¨ÙˆØ¯Ù†"""
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

        # Ù…Ø±ØªØ¨â€ŒØ³Ø§Ø²ÛŒ Ø¨Ø± Ø§Ø³Ø§Ø³ Ø³Ø·Ø± Ùˆ Ø³ØªÙˆÙ†
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
        """ØªØ·Ø¨ÛŒÙ‚ Ù‡ÙˆØ´Ù…Ù†Ø¯ Ù…ØªÙ† Ø§Ø±Ø³Ø§Ù„ÛŒ Ú©Ø§Ø±Ø¨Ø± Ø¨Ø§ Ø§Ú©Ø´Ù†â€ŒÙ‡Ø§ÛŒ ØªØ¹Ø±ÛŒÙ Ø´Ø¯Ù‡ Ø¯Ú©Ù…Ù‡â€ŒÙ‡Ø§ÛŒ Ù…Ù†Ùˆ"""
        if not text:
            return None
        text_clean = text.strip()
        buttons = self.get_reseller_bot_menu_buttons() if is_reseller else self.get_bot_menu_buttons()

        # Û±. ØªØ·Ø¨ÛŒÙ‚ Ù…Ø³ØªÙ‚ÛŒÙ… Ø¨Ø§ Ø¹Ù†ÙˆØ§Ù† ØªÙ†Ø¸ÛŒÙ…â€ŒØ´Ø¯Ù‡ Ø¯Ú©Ù…Ù‡
        for b in buttons:
            b_title = b.get("title", "").strip()
            if b_title and (text_clean == b_title or text_clean in b_title or b_title in text_clean):
                return b

        # Û². ØªØ·Ø¨ÛŒÙ‚ Ú©Ù„Ù…Ø§Øª Ú©Ù„ÛŒØ¯ÛŒ Ø§Ø³ØªØ§Ù†Ø¯Ø§Ø±Ø¯ Ù‡Ø± Ø¯Ú©Ù…Ù‡
        keywords_map = {
            "buy": ["Ø®Ø±ÛŒØ¯ Ø§Ø´ØªØ±Ø§Ú©", "Ø®Ø±ÛŒØ¯", "buy", "Ø§Ø´ØªØ±Ø§Ú© Ø¬Ø¯ÛŒØ¯", "Ø®Ø±ÛŒØ¯ Ø³Ø±ÙˆÛŒØ³"],
            "my_subs": ["Ø§Ø´ØªØ±Ø§Ú©â€ŒÙ‡Ø§ÛŒ Ù…Ù†", "Ø³Ø±ÙˆÛŒØ³â€ŒÙ‡Ø§ÛŒ Ù…Ù†", "ÙˆØ¶Ø¹ÛŒØª Ø³Ø±ÙˆÛŒØ³", "Ú©Ø§Ù†ÙÛŒÚ¯â€ŒÙ‡Ø§ÛŒ Ù…Ù†", "my subscriptions", "status", "link", "Ù„ÛŒÙ†Ú©"],
            "test_sub": ["ØªØ³Øª Ø±Ø§ÛŒÚ¯Ø§Ù†", "Ø§Ú©Ø§Ù†Øª ØªØ³Øª", "ØªØ³Øª", "Ø§Ø´ØªØ±Ø§Ú© ØªØ³Øª", "free test", "test"],
            "renew": ["ØªÙ…Ø¯ÛŒØ¯ Ø³Ø±ÙˆÛŒØ³", "ØªÙ…Ø¯ÛŒØ¯ Ø§Ø´ØªØ±Ø§Ú©", "ØªÙ…Ø¯ÛŒØ¯", "renew"],
            "wallet": ["Ú©ÛŒÙ Ù¾ÙˆÙ„", "Ú©ÛŒÙ Ù¾ÙˆÙ„ Ùˆ Ø´Ø§Ø±Ú˜", "Ø´Ø§Ø±Ú˜ Ø­Ø³Ø§Ø¨", "Ø´Ø§Ø±Ú˜", "wallet", "balance"],
            "support": ["Ù¾Ø´ØªÛŒØ¨Ø§Ù†ÛŒ Ùˆ ØªÛŒÚ©Øª", "Ù¾Ø´ØªÛŒØ¨Ø§Ù†ÛŒ", "Ø§Ø±Ø³Ø§Ù„ ØªÛŒÚ©Øª", "ØªÛŒÚ©Øª", "support", "ticket"],
            "tutorials": ["Ø±Ø§Ù‡Ù†Ù…Ø§ÛŒ Ø§ØªØµØ§Ù„", "Ø¢Ù…ÙˆØ²Ø´ Ø§ØªØµØ§Ù„", "Ø¢Ù…ÙˆØ²Ø´", "Ø±Ø§Ù‡Ù†Ù…Ø§", "help", "guide", "tutorial"],
            "troubleshoot": ["Ø­Ù„ Ù…Ø´Ú©Ù„Ø§Øª Ø§ØªØµØ§Ù„", "Ø­Ù„ Ù…Ø´Ú©Ù„", "Ø¹ÛŒØ¨â€ŒÛŒØ§Ø¨ÛŒ", "Ù…Ø´Ú©Ù„ Ø§ØªØµØ§Ù„", "troubleshoot"],
            "referral": ["Ú©Ø³Ø¨ Ø¯Ø±Ø¢Ù…Ø¯ Ùˆ Ø¯Ø¹ÙˆØª", "Ø²ÛŒØ±Ù…Ø¬Ù…ÙˆØ¹Ù‡â€ŒÚ¯ÛŒØ±ÛŒ", "Ø¯Ø¹ÙˆØª Ø¯ÙˆØ³ØªØ§Ù†", "Ú©Ø³Ø¨ Ø¯Ø±Ø¢Ù…Ø¯", "referral", "invite"],
            "payments": ["Ø³Ø§Ø¨Ù‚Ù‡ Ù¾Ø±Ø¯Ø§Ø®Øªâ€ŒÙ‡Ø§", "Ø³Ø§Ø¨Ù‚Ù‡ Ù¾Ø±Ø¯Ø§Ø®Øª", "ØªØ±Ø§Ú©Ù†Ø´â€ŒÙ‡Ø§", "ÙÛŒØ´â€ŒÙ‡Ø§", "payments", "history"],
            "language": ["ØªØºÛŒÛŒØ± Ø²Ø¨Ø§Ù†", "Ø²Ø¨Ø§Ù†", "language", "lang"],
        }

        for b in buttons:
            b_id = b.get("id")
            kws = keywords_map.get(b_id, [])
            for kw in kws:
                if kw in text_clean.lower():
                    return b

        return None

    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    # Ù…Ø¯ÛŒØ±ÛŒØª Ù¾Ø´ØªÛŒØ¨Ø§Ù†â€ŒÙ‡Ø§
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

    def save_backup_record(self, backup_file, backup_size):
        """Ø°Ø®ÛŒØ±Ù‡ Ø±Ú©ÙˆØ±Ø¯ Ù¾Ø´ØªÛŒØ¨Ø§Ù†"""
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
        """Ø¹Ù„Ø§Ù…Øªâ€ŒÚ¯Ø°Ø§Ø±ÛŒ Ù¾Ø´ØªÛŒØ¨Ø§Ù† Ø¨Ù‡ Ø¹Ù†ÙˆØ§Ù† Ø¢Ù¾Ù„ÙˆØ¯ Ø´Ø¯Ù‡"""
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
        """Ø¯Ø±ÛŒØ§ÙØª Ù„ÛŒØ³Øª Ù¾Ø´ØªÛŒØ¨Ø§Ù†â€ŒÙ‡Ø§"""
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

    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    # Ù…Ø¯ÛŒØ±ÛŒØª Ú©ÛŒÙ Ù¾ÙˆÙ„
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

    def get_wallet(self, telegram_id):
        """Ø¯Ø±ÛŒØ§ÙØª Ù…ÙˆØ¬ÙˆØ¯ÛŒ Ú©ÛŒÙ Ù¾ÙˆÙ„"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT * FROM wallet WHERE telegram_id = ?", (telegram_id,))
            row = cursor.fetchone()
            if row:
                return dict(row)
            # Ø§ÛŒØ¬Ø§Ø¯ Ú©ÛŒÙ Ù¾ÙˆÙ„ Ø¬Ø¯ÛŒØ¯
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
        """Ø¨Ø±ÙˆØ²Ø±Ø³Ø§Ù†ÛŒ Ù…ÙˆØ¬ÙˆØ¯ÛŒ Ú©ÛŒÙ Ù¾ÙˆÙ„"""
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
            # Ø¯Ø±ÛŒØ§ÙØª Ù…ÙˆØ¬ÙˆØ¯ÛŒ Ø¬Ø¯ÛŒØ¯
            cursor.execute("SELECT balance FROM wallet WHERE telegram_id = ?", (telegram_id,))
            row = cursor.fetchone()
            return {"success": True, "balance": row["balance"] if row else 0}
        except Exception as e:
            logger.error(f"Error updating wallet for {telegram_id}: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def get_all_wallets(self):
        """Ø¯Ø±ÛŒØ§ÙØª ØªÙ…Ø§Ù… Ú©ÛŒÙ Ù¾ÙˆÙ„â€ŒÙ‡Ø§"""
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

    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    # Ù…Ø¯ÛŒØ±ÛŒØª Ú©Ø¯Ù‡Ø§ÛŒ ØªØ®ÙÛŒÙ
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

    def create_discount_code(self, code, discount_percent=0, discount_amount=0, max_uses=0, valid_until=None):
        """Ø§ÛŒØ¬Ø§Ø¯ Ú©Ø¯ ØªØ®ÙÛŒÙ Ø¬Ø¯ÛŒØ¯"""
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
        """Ø§Ø³ØªÙØ§Ø¯Ù‡ Ø§Ø² Ú©Ø¯ ØªØ®ÙÛŒÙ"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("SELECT * FROM discount_codes WHERE code = ? AND is_active = 1", (code.upper(),))
            row = cursor.fetchone()
            if not row:
                return {"success": False, "error": "Ú©Ø¯ ØªØ®ÙÛŒÙ ÛŒØ§ÙØª Ù†Ø´Ø¯"}
            
            discount = dict(row)
            
            # Ø¨Ø±Ø±Ø³ÛŒ ØªØ§Ø±ÛŒØ® Ø§Ø¹ØªØ¨Ø§Ø±
            if discount["valid_until"]:
                valid_until = datetime.fromisoformat(discount["valid_until"])
                if get_now_naive() > valid_until:
                    return {"success": False, "error": "Ú©Ø¯ ØªØ®ÙÛŒÙ Ù…Ù†Ù‚Ø¶ÛŒ Ø´Ø¯Ù‡"}
            
            # Ø¨Ø±Ø±Ø³ÛŒ ØªØ¹Ø¯Ø§Ø¯ Ø§Ø³ØªÙØ§Ø¯Ù‡
            if discount["max_uses"] > 0 and discount["used_count"] >= discount["max_uses"]:
                return {"success": False, "error": "Ú©Ø¯ ØªØ®ÙÛŒÙ Ø¨Ù‡ Ø­Ø¯Ø§Ú©Ø«Ø± Ø§Ø³ØªÙØ§Ø¯Ù‡ Ø±Ø³ÛŒØ¯Ù‡"}
            
            # Ø¨Ø±ÙˆØ²Ø±Ø³Ø§Ù†ÛŒ ØªØ¹Ø¯Ø§Ø¯ Ø§Ø³ØªÙØ§Ø¯Ù‡
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
        """Ø§Ø¹ØªØ¨Ø§Ø±Ø³Ù†Ø¬ÛŒ Ùˆ Ù…Ø­Ø§Ø³Ø¨Ù‡ ØªØ®ÙÛŒÙ Ú©Ø¯Ù‡Ø§ÛŒ Ø§Ø¯Ù…ÛŒÙ† (Ø¨Ø¯ÙˆÙ† Ø§ÙØ²Ø§ÛŒØ´ ØªØ¹Ø¯Ø§Ø¯ Ù…ØµØ±Ù)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT * FROM discount_codes WHERE code = ? AND is_active = 1", (code.strip().upper(),))
            row = cursor.fetchone()
            if not row:
                return {"valid": False, "error": "Ú©Ø¯ ØªØ®ÙÛŒÙ Ù†Ø§Ù…Ø¹ØªØ¨Ø± Ø§Ø³Øª."}
            
            d = dict(row)
            if d.get("max_uses", 0) > 0 and d.get("used_count", 0) >= d.get("max_uses"):
                return {"valid": False, "error": "Ø¸Ø±ÙÛŒØª Ø§Ø³ØªÙØ§Ø¯Ù‡ Ø§Ø² Ø§ÛŒÙ† Ú©Ø¯ ØªØ®ÙÛŒÙ Ø¨Ù‡ Ù¾Ø§ÛŒØ§Ù† Ø±Ø³ÛŒØ¯Ù‡ Ø§Ø³Øª."}

            if d.get("valid_until"):
                try:
                    exp = datetime.fromisoformat(d["valid_until"])
                    if get_now_naive() > exp:
                        return {"valid": False, "error": "Ù…Ù‡Ù„Øª Ø§Ø³ØªÙØ§Ø¯Ù‡ Ø§Ø² Ø§ÛŒÙ† Ú©Ø¯ ØªØ®ÙÛŒÙ Ù…Ù†Ù‚Ø¶ÛŒ Ø´Ø¯Ù‡ Ø§Ø³Øª."}
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
        Ø§Ø¹ØªØ¨Ø§Ø±Ø³Ù†Ø¬ÛŒ Ø§ÛŒØ²ÙˆÙ„Ù‡ Ú©Ø¯ ØªØ®ÙÛŒÙ Ù…Ø´ØªØ±ÛŒ:
        - Ø§Ú¯Ø± Ù…Ø´ØªØ±ÛŒ Ù…ØªØ¹Ù„Ù‚ Ø¨Ù‡ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ Ø¨Ø§Ø´Ø¯: ØµØ±ÙØ§Ù‹ Ú©Ø¯Ù‡Ø§ÛŒ Ù‡Ù…Ø§Ù† Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ Ù…Ø¹ØªØ¨Ø± Ø§Ø³Øª (Ú©Ø¯Ù‡Ø§ÛŒ Ø§Ø¯Ù…ÛŒÙ† Ùˆ Ø³Ø§ÛŒØ± Ù†Ù…Ø§ÛŒÙ†Ø¯Ú¯Ø§Ù† Ù†Ø§Ù…Ø¹ØªØ¨Ø±Ù†Ø¯).
        - Ø§Ú¯Ø± Ù…Ø´ØªØ±ÛŒ Ù…Ø³ØªÙ‚ÛŒÙ… Ø§Ø¯Ù…ÛŒÙ† Ø¨Ø§Ø´Ø¯: ØµØ±ÙØ§Ù‹ Ú©Ø¯Ù‡Ø§ÛŒ Ø§Ø¯Ù…ÛŒÙ† Ù…Ø¹ØªØ¨Ø± Ø§Ø³Øª (Ú©Ø¯Ù‡Ø§ÛŒ Ù‡ÛŒÚ† Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡â€ŒØ§ÛŒ Ù…Ø¹ØªØ¨Ø± Ù†ÛŒØ³Øª).
        """
        if not code:
            return {"valid": False, "error": "Ù„Ø·ÙØ§Ù‹ Ú©Ø¯ ØªØ®ÙÛŒÙ Ø±Ø§ ÙˆØ§Ø±Ø¯ Ú©Ù†ÛŒØ¯."}

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
            # ÙÙ‚Ø· Ùˆ ÙÙ‚Ø· Ú©Ø¯Ù‡Ø§ÛŒ Ø§ÛŒÙ† Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ Ø®Ø§Øµ
            return self.validate_reseller_discount_code(reseller_id, code, order_amount)
        else:
            # ÙÙ‚Ø· Ùˆ ÙÙ‚Ø· Ú©Ø¯Ù‡Ø§ÛŒ Ù…Ø¯ÛŒØ±ÛŒØª
            return self.validate_admin_discount_code(code, order_amount)

    def apply_customer_discount(self, sub_row_or_id, code: str) -> bool:
        """Ø§ÙØ²Ø§ÛŒØ´ Ø´Ù…Ø§Ø±Ù†Ø¯Ù‡ Ø§Ø³ØªÙØ§Ø¯Ù‡ Ø§Ø² Ú©Ø¯ ØªØ®ÙÛŒÙ Ø¯Ø± Ø¬Ø¯ÙˆÙ„ Ù…Ø±Ø¨ÙˆØ·Ù‡ Ø¨Ø± Ø§Ø³Ø§Ø³ Ø§ÛŒØ²ÙˆÙ„Ø§Ø³ÛŒÙˆÙ† Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ ÛŒØ§ Ø§Ø¯Ù…ÛŒÙ†"""
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
        """Ø¯Ø±ÛŒØ§ÙØª ØªÙ…Ø§Ù… Ú©Ø¯Ù‡Ø§ÛŒ ØªØ®ÙÛŒÙ"""
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
        """Ø­Ø°Ù Ú©Ø¯ ØªØ®ÙÛŒÙ"""
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

    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    # Ù…Ø¯ÛŒØ±ÛŒØª Ø¨Ù„Ø§Ú© Ù„ÛŒØ³Øª
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

    def block_user(self, telegram_id, reason=None, blocked_by=None):
        """Ø¨Ù„Ø§Ú© Ú©Ø±Ø¯Ù† Ú©Ø§Ø±Ø¨Ø±"""
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
        """Ø¢Ù†Ø¨Ù„Ø§Ú© Ú©Ø±Ø¯Ù† Ú©Ø§Ø±Ø¨Ø±"""
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
        """Ø¨Ø±Ø±Ø³ÛŒ Ø¨Ù„Ø§Ú© Ø¨ÙˆØ¯Ù† Ú©Ø§Ø±Ø¨Ø±"""
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
        """Ø¯Ø±ÛŒØ§ÙØª Ù„ÛŒØ³Øª Ú©Ø§Ø±Ø¨Ø±Ø§Ù† Ø¨Ù„Ø§Ú© Ø´Ø¯Ù‡"""
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

    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    # Ù…Ø¯ÛŒØ±ÛŒØª ØªÛŒÚ©Øªâ€ŒÙ‡Ø§ÛŒ Ù¾Ø´ØªÛŒØ¨Ø§Ù†ÛŒ Ùˆ Ù¾ÛŒØ§Ù…â€ŒÙ‡Ø§ÛŒ Ú¯ÙØªÚ¯Ùˆ
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

    def create_ticket(self, telegram_id=None, subject="Ù¾ÛŒØ§Ù… Ú©Ø§Ø±Ø¨Ø±", message="", reseller_id=None, user_id=None, **kwargs):
        """Ø§ÛŒØ¬Ø§Ø¯ ØªÛŒÚ©Øª Ù¾Ø´ØªÛŒØ¨Ø§Ù†ÛŒ Ø¬Ø¯ÛŒØ¯ Ø¨Ø§ Ù‚Ø§Ø¨Ù„ÛŒØª Ø§Ù†ØªØ³Ø§Ø¨ Ø¨Ù‡ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ Ùˆ Ø¯Ø±Ø¬ Ø§ÙˆÙ„ÛŒÙ† Ù¾ÛŒØ§Ù… Ú¯ÙØªÚ¯Ùˆ"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        tg_id = telegram_id or user_id
        if not tg_id:
            return {"success": False, "error": "Ø´Ù†Ø§Ø³Ù‡ Ú©Ø§Ø±Ø¨Ø± Ø§Ù„Ø²Ø§Ù…ÛŒ Ø§Ø³Øª."}
        try:
            target_role = kwargs.get("target_role") or ('reseller' if reseller_id and int(reseller_id) > 0 else 'admin')
            ticket_type = kwargs.get("ticket_type") or "general"
            cursor.execute("""
                INSERT INTO support_tickets (telegram_id, subject, message, status, reseller_id, target_role, ticket_type, created_at, updated_at)
                VALUES (?, ?, ?, 'open', ?, ?, ?, ?, ?)
            """, (tg_id, subject, message, reseller_id, target_role, ticket_type, now, now))
            ticket_id = cursor.lastrowid

            if message:
                sender_name = kwargs.get("username") or kwargs.get("first_name") or "Ú©Ø§Ø±Ø¨Ø±"
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
        """Ø§ÙØ²ÙˆØ¯Ù† Ù¾ÛŒØ§Ù… Ø¨Ù‡ Ø²Ù†Ø¬ÛŒØ±Ù‡ Ú¯ÙØªÚ¯ÙˆÛŒ ØªÛŒÚ©Øª Ùˆ Ø¨Ø±ÙˆØ²Ø±Ø³Ø§Ù†ÛŒ ÙˆØ¶Ø¹ÛŒØª ØªÛŒÚ©Øª"""
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
        """Ø«Ø¨Øª Ù¾Ø§Ø³Ø® Ø§Ø¯Ù…ÛŒÙ† ÛŒØ§ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ Ø¨Ù‡ ØªÛŒÚ©Øª"""
        return self.add_ticket_message(ticket_id, sender_type=sender_type, message=message, sender_id=sender_id, sender_name=sender_name)

    def reply_ticket(self, ticket_id, admin_reply, sender_name="Ù¾Ø´ØªÛŒØ¨Ø§Ù†ÛŒ"):
        """Ù¾Ø§Ø³Ø® Ø§Ø¯Ù…ÛŒÙ† ÛŒØ§ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ Ø¨Ù‡ ØªÛŒÚ©Øª"""
        return self.add_ticket_message(ticket_id, sender_type="admin", message=admin_reply, sender_name=sender_name, new_status="replied")

    def update_ticket_status(self, ticket_id, status):
        """Ø¨Ø±ÙˆØ²Ø±Ø³Ø§Ù†ÛŒ ÙˆØ¶Ø¹ÛŒØª ØªÛŒÚ©Øª (open, in_progress, replied, closed)"""
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
        """Ø¨Ø§Ø²Ú¯Ø´Ø§ÛŒÛŒ Ù…Ø¬Ø¯Ø¯ ØªÛŒÚ©Øª"""
        return self.update_ticket_status(ticket_id, "open")

    def close_ticket(self, ticket_id):
        """Ø¨Ø³ØªÙ† ØªÛŒÚ©Øª"""
        return self.update_ticket_status(ticket_id, "closed")

    def delete_ticket(self, ticket_id, reseller_id=None):
        """Ø­Ø°Ù Ú©Ø§Ù…Ù„ ÛŒÚ© ØªÛŒÚ©Øª Ùˆ Ù¾ÛŒØ§Ù…â€ŒÙ‡Ø§ÛŒ Ø¢Ù†"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            if reseller_id:
                cursor.execute("SELECT id FROM support_tickets WHERE id=? AND reseller_id=?", (ticket_id, reseller_id))
                if not cursor.fetchone():
                    return {"success": False, "error": "ØªÛŒÚ©Øª ÛŒØ§ÙØª Ù†Ø´Ø¯ ÛŒØ§ Ù…ØªØ¹Ù„Ù‚ Ø¨Ù‡ Ø´Ù…Ø§ Ù†ÛŒØ³Øª."}
            cursor.execute("DELETE FROM ticket_messages WHERE ticket_id=?", (ticket_id,))
            cursor.execute("DELETE FROM support_tickets WHERE id=?", (ticket_id,))
            conn.commit()
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def get_ticket_messages(self, ticket_id):
        """Ø¯Ø±ÛŒØ§ÙØª ØªÙ…Ø§Ù… Ù¾ÛŒØ§Ù…â€ŒÙ‡Ø§ÛŒ Ø²Ù†Ø¬ÛŒØ±Ù‡ Ú¯ÙØªÚ¯ÙˆÛŒ ÛŒÚ© ØªÛŒÚ©Øª Ø¨Ø§ Ø³Ø§Ø²Ú¯Ø§Ø±ÛŒ Ø¨Ù‡ Ø¹Ù‚Ø¨"""
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
                            "sender_name": "Ú©Ø§Ø±Ø¨Ø±",
                            "message": t["message"],
                            "created_at": t["created_at"]
                        })
                    if t["admin_reply"]:
                        rows.append({
                            "id": 2,
                            "ticket_id": ticket_id,
                            "sender_type": "admin",
                            "sender_id": None,
                            "sender_name": "Ù¾Ø´ØªÛŒØ¨Ø§Ù†ÛŒ",
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
        """Ø¯Ø±ÛŒØ§ÙØª ØªÛŒÚ©Øªâ€ŒÙ‡Ø§ÛŒ Ú©Ø§Ø±Ø¨Ø±"""
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
        """Ø§ÛŒØ¬Ø§Ø¯ ØªÛŒÚ©Øª Ú¯ÙØªÚ¯ÙˆÛŒ Ø¢Ù†Ù„Ø§ÛŒÙ† Ù…Ø´ØªØ±ÛŒ Ø§Ø² Ù¾ÙˆØ±ØªØ§Ù„ ÙˆØ¨ Ø¨Ø§ Ø«Ø¨Øª Ù…Ø´Ø®ØµØ§Øª Ùˆ Ù¾ÛŒØ§Ù… Ø§ÙˆÙ„ÛŒÙ‡"""
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
                """, (ticket_id, tg_id, customer_name or "Ù…Ø´ØªØ±ÛŒ", initial_message, now))

            conn.commit()
            return {"success": True, "ticket_id": ticket_id}
        except Exception as e:
            logger.error(f"Error creating portal chat ticket: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def get_portal_chat_history(self, subscription_id: int, telegram_id: int = None, portal_token: str = None):
        """Ø¯Ø±ÛŒØ§ÙØª Ø³ÙˆØ§Ø¨Ù‚ ØªÙ…Ø§Ù…ÛŒ Ú¯ÙØªÚ¯ÙˆÙ‡Ø§ÛŒ Ø¢Ù†Ù„Ø§ÛŒÙ† Ù…Ø±ØªØ¨Ø· Ø¨Ø§ Ø§ÛŒÙ† Ø§Ø´ØªØ±Ø§Ú©"""
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
        """Ø¨Ø±Ø±Ø³ÛŒ Ù…Ø¬Ø§Ø² Ø¨ÙˆØ¯Ù† Ùˆ Ø¯Ø±ÛŒØ§ÙØª Ø§Ø·Ù„Ø§Ø¹Ø§Øª ØªÛŒÚ©Øª Ù¾ÙˆØ±ØªØ§Ù„"""
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
        """Ø§ÙØ²ÙˆØ¯Ù† Ù¾ÛŒØ§Ù… Ø¬Ø¯ÛŒØ¯ Ù…Ø´ØªØ±ÛŒ Ø¨Ù‡ Ú¯ÙØªÚ¯ÙˆÛŒ Ø¢Ù†Ù„Ø§ÛŒÙ† Ùˆ ØªØºÛŒÛŒØ± ÙˆØ¶Ø¹ÛŒØª ØªÛŒÚ©Øª Ø¨Ù‡ open"""
        t = self.get_portal_ticket(ticket_id, subscription_id=subscription_id)
        if not t:
            return {"success": False, "error": "Ú¯ÙØªÚ¯ÙˆÛŒ Ù…ÙˆØ±Ø¯ Ù†Ø¸Ø± ÛŒØ§ÙØª Ù†Ø´Ø¯ ÛŒØ§ Ø¯Ø³ØªØ±Ø³ÛŒ Ù†Ø§Ù…Ø¹ØªØ¨Ø± Ø§Ø³Øª."}

        sender_name = customer_name or t.get("customer_name") or "Ù…Ø´ØªØ±ÛŒ"
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
        """Ø¨Ø±Ø±Ø³ÛŒ Ù¾ÛŒØ§Ù…â€ŒÙ‡Ø§ÛŒ Ø¬Ø¯ÛŒØ¯ Ø¯Ø±ÛŒØ§ÙØªÛŒ Ø§Ø² Ø³Ù…Øª Ù¾Ø´ØªÛŒØ¨Ø§Ù†ÛŒ Ùˆ ÙˆØ¶Ø¹ÛŒØª Ø®ÙˆØ§Ù†Ø¯Ù‡â€ŒÙ†Ø´Ø¯Ù‡"""
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
        """Ø¨Ø±Ø±Ø³ÛŒ Ø§ÛŒÙ†Ú©Ù‡ Ø¢ÛŒØ§ Ù¾Ø´ØªÛŒØ¨Ø§Ù† Ø§Ù†Ø³Ø§Ù†ÛŒ (Ø§Ø¯Ù…ÛŒÙ† ÛŒØ§ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡) Ø¯Ø± Ø§ÛŒÙ† ØªÛŒÚ©Øª Ù¾Ø§Ø³Ø® Ø¯Ø§Ø¯Ù‡ Ø§Ø³Øª ÛŒØ§ Ø®ÛŒØ±"""
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
        """ØªØ´Ø®ÛŒØµ ÙˆØ¶Ø¹ÛŒØª Ø¢Ù†Ù„Ø§ÛŒÙ† ÛŒØ§ Ø¢ÙÙ„Ø§ÛŒÙ† Ø¨ÙˆØ¯Ù† Ù¾Ø´ØªÛŒØ¨Ø§Ù† Ø¨Ø±Ø§ÛŒ ÛŒÚ© Ø§Ø´ØªØ±Ø§Ú© Ø®Ø§Øµ (Ù¾Ø´ØªÛŒØ¨Ø§Ù†ÛŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ ÛŒØ§ Ù…Ø¯ÛŒØ±)"""
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

        # Ø§Ø³ØªØ®Ø±Ø§Ø¬ Ù†Ø§Ù… Ùˆ Ù‡ÙˆÛŒØª Ù¾Ø´ØªÛŒØ¨Ø§Ù†
        support_name = "Ù¾Ø´ØªÛŒØ¨Ø§Ù†ÛŒ"
        if reseller_id and int(reseller_id) > 0:
            r = self.get_reseller(reseller_id)
            if r:
                support_name = r.get("brand_name") or r.get("brand_title") or r.get("name") or f"Ù¾Ø´ØªÛŒØ¨Ø§Ù†ÛŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ ({r.get('username')})"
        else:
            support_name = self.get_setting("portal_title") or self.get_setting("store_name") or "Ù¾Ø´ØªÛŒØ¨Ø§Ù†ÛŒ Ù…Ø±Ú©Ø²ÛŒ"

        # Û±. Ø¨Ø±Ø±Ø³ÛŒ Ø­Ø§Ù„Øª Ø¢Ù†Ù„Ø§ÛŒÙ† Ø³Ø§Ø®ØªÚ¯ÛŒ (Fake Online)
        if mode == "always_all":
            return {
                "is_online": True,
                "status": "online",
                "support_name": support_name,
                "status_text": "Ø¢Ù†Ù„Ø§ÛŒÙ† Ùˆ Ù¾Ø§Ø³Ø®Ú¯Ùˆ",
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
                    "status_text": "Ø¢Ù†Ù„Ø§ÛŒÙ† Ùˆ Ù¾Ø§Ø³Ø®Ú¯Ùˆ",
                    "mode": "fake"
                }

        # Û². Ø¨Ø±Ø±Ø³ÛŒ ÙˆØ¶Ø¹ÛŒØª ÙˆØ§Ù‚Ø¹ÛŒ (Real Online Status)
        is_online = False
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            now_tehran = datetime.now(TEHRAN_TZ)

            if reseller_id and int(reseller_id) > 0:
                # Ø¨Ø±Ø±Ø³ÛŒ Ù„Ø§Ú¯ÛŒÙ† Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ ÛŒØ§ Ø²ÛŒØ±Ù…Ø¯ÛŒØ±Ø§Ù† ÙØ¹Ø§Ù„ Ø§Ùˆ
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

                # Ø¨Ø±Ø±Ø³ÛŒ Ø§Ø±Ø³Ø§Ù„ Ù¾ÛŒØ§Ù… Ø§Ø®ÛŒØ± ØªÛŒÚ©Øª ØªÙˆØ³Ø· Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡
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
                # Ø¨Ø±Ø±Ø³ÛŒ Ø§Ø¯Ù…ÛŒÙ† Ø§ØµÙ„ÛŒ Ùˆ Ø³Ø§ÛŒØ± Ù…Ø¯ÛŒØ±Ø§Ù† Ù¾Ù†Ù„
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

                # Ø¨Ø±Ø±Ø³ÛŒ Ø§Ø±Ø³Ø§Ù„ Ù¾ÛŒØ§Ù… Ø§Ø®ÛŒØ± ØªÙˆØ³Ø· Ø§Ø¯Ù…ÛŒÙ†
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
            "status_text": "Ø¢Ù†Ù„Ø§ÛŒÙ† Ùˆ Ù¾Ø§Ø³Ø®Ú¯Ùˆ" if is_online else "Ø¢ÙÙ„Ø§ÛŒÙ† (Ø«Ø¨Øª Ù¾ÛŒØ§Ù… Ø¨Ø±Ø§ÛŒ Ø¨Ø±Ø±Ø³ÛŒ)",
            "mode": "real"
        }

    def get_chat_settings(self) -> dict:
        """Ø¯Ø±ÛŒØ§ÙØª ØªÙ†Ø¸ÛŒÙ…Ø§Øª Ø¬Ø§Ù…Ø¹ Ú¯ÙØªÚ¯ÙˆÛŒ Ø¢Ù†Ù„Ø§ÛŒÙ† Ù¾ÙˆØ±ØªØ§Ù„ Ù…Ø´ØªØ±ÛŒØŒ Ø§Ø³ØªØ§ÛŒÙ„ Ø¯Ú©Ù…Ù‡ Ùˆ Ù‡ÙˆØ´ Ù…ØµÙ†ÙˆØ¹ÛŒ"""
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
            "chat_button_text": self.get_setting("chat_button_text", "Ú¯ÙØªÚ¯ÙˆÛŒ Ø¢Ù†Ù„Ø§ÛŒÙ†"),
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
        """Ø°Ø®ÛŒØ±Ù‡ ØªÙ†Ø¸ÛŒÙ…Ø§Øª Ú¯ÙØªÚ¯ÙˆÛŒ Ø¢Ù†Ù„Ø§ÛŒÙ† Ø¯Ø± Ø¯ÛŒØªØ§Ø¨ÛŒØ³"""
        for k, v in settings.items():
            if isinstance(v, (list, dict)):
                self.save_setting(k, json.dumps(v, ensure_ascii=False))
            elif isinstance(v, bool):
                self.save_setting(k, "1" if v else "0")
            else:
                self.save_setting(k, str(v) if v is not None else "")

    def generate_ai_chat_reply(self, ticket_id: int, customer_message: str, sub_info: dict = None) -> Optional[str]:
        """Ù¾Ø§Ø³Ø®Ú¯ÙˆÛŒÛŒ Ù‡ÙˆØ´Ù…Ù†Ø¯ Ú†ØªØ¨Ø§Øª Ù‡ÙˆØ´ Ù…ØµÙ†ÙˆØ¹ÛŒ Ø¨Ù‡ Ù¾ÛŒØ§Ù… Ù…Ø´ØªØ±ÛŒ Ø¨Ø§ Ø±Ø¹Ø§ÛŒØª ØªÙˆÙ‚Ù Ø¯Ø± ØµÙˆØ±Øª Ù¾Ø§Ø³Ø® Ù¾Ø´ØªÛŒØ¨Ø§Ù† Ø§Ù†Ø³Ø§Ù†ÛŒ"""
        # Û±. Ø¨Ø±Ø±Ø³ÛŒ Ø§ÛŒÙ†Ú©Ù‡ Ø¢ÛŒØ§ Ù¾Ø´ØªÛŒØ¨Ø§Ù† Ø§Ù†Ø³Ø§Ù†ÛŒ Ù‚Ø¨Ù„Ø§Ù‹ Ø¯Ø± Ø§ÛŒÙ† Ú¯ÙØªÚ¯Ùˆ Ù¾Ø§Ø³Ø® Ø¯Ø§Ø¯Ù‡ Ø§Ø³Øª ÛŒØ§ Ø®ÛŒØ±
        if self.has_human_support_replied(ticket_id):
            return None

        # Û². Ø¨Ø±Ø±Ø³ÛŒ ÙØ¹Ø§Ù„ Ø¨ÙˆØ¯Ù† Ù‡ÙˆØ´ Ù…ØµÙ†ÙˆØ¹ÛŒ
        ai_enabled = str(self.get_setting("chat_ai_enabled", "1")).lower() in ("1", "true")
        if not ai_enabled:
            return None

        text = (customer_message or "").strip().lower()
        if not text:
            return None

        # Û³. Ø­Ø§Ù„Øªâ€ŒÙ‡Ø§ÛŒ Ù…Ø®ØªÙ„Ù Ù¾ÛŒØ§Ù… Ù…Ø´ØªØ±ÛŒ:
        # Ø§Ù„Ù) Ø§Ø¹Ù„Ø§Ù… Ø¢Ù…Ø§Ø¯Ú¯ÛŒ Ùˆ ØªØ§ÛŒÛŒØ¯ Ø¬Ù‡Øª Ø­Ù„ Ù…Ø´Ú©Ù„
        affirmative_words = ["Ø¨Ù„Ù‡", "Ø§Ø±Ù‡", "Ø¢Ø±Ù‡", "Ù…ÙˆØ§ÙÙ‚Ù…", "Ù…Ù…Ù†ÙˆÙ†", "Ø­Ù„ Ú©Ù†", "Ù…ÛŒØ®ÙˆØ§Ù…", "Ø§ÙˆÚ©ÛŒ", "Ø¨Ø§Ø´Ù‡", "Ù…Ø±Ø³ÛŒ", "Ù„Ø·ÙØ§", "Ù„Ø·ÙØ§Ù‹"]
        if any(w == text or text.startswith(w + " ") or text.endswith(" " + w) for w in affirmative_words) and len(text) <= 25:
            return (
                "Ø¨Ø§ Ú©Ù…Ø§Ù„ Ù…ÛŒÙ„! ðŸŒ¸ Ù…Ù† Ù‡ÙˆØ´ Ù…ØµÙ†ÙˆØ¹ÛŒ Ù‡Ø³ØªÙ… Ùˆ Ø¢Ù…Ø§Ø¯Ù‡â€ŒØ§Ù… Ù…Ø´Ú©Ù„â€ŒØªØ§Ù† Ø±Ø§ Ø¨Ø±Ø±Ø³ÛŒ Ùˆ Ø­Ù„ Ú©Ù†Ù….\n\n"
                "Ù„Ø·ÙØ§Ù‹ Ø¨ÙØ±Ù…Ø§ÛŒÛŒØ¯ Ø¯Ù‚ÛŒÙ‚Ø§Ù‹ Ú†Ù‡ Ù…Ø´Ú©Ù„ÛŒ Ù¾ÛŒØ´ Ø¢Ù…Ø¯Ù‡ Ø§Ø³ØªØŸ\n"
                "â€¢ Ù…Ø´Ú©Ù„ Ø¯Ø± Ø§ØªØµØ§Ù„ Ùˆ Ù¾ÛŒÙ†Ú¯ØŸ\n"
                "â€¢ Ù†ÛŒØ§Ø² Ø¨Ù‡ Ù†Ø±Ù…â€ŒØ§ÙØ²Ø§Ø± Ù…Ù†Ø§Ø³Ø¨ (Ø§Ù†Ø¯Ø±ÙˆÛŒØ¯ØŒ Ø¢ÛŒÙÙˆÙ†ØŒ ÙˆÛŒÙ†Ø¯ÙˆØ²)ØŸ\n"
                "â€¢ Ø³ÙˆØ§Ù„ Ø¯Ø± Ù…ÙˆØ±Ø¯ ØªÙ…Ø¯ÛŒØ¯ ÛŒØ§ Ø¯Ø±ÛŒØ§ÙØª Ù„ÛŒÙ†Ú© Ø§Ø´ØªØ±Ø§Ú©ØŸ"
            )

        # Ø¨) Ù…Ø´Ú©Ù„Ø§Øª Ø§ØªØµØ§Ù„ØŒ Ù‚Ø·Ø¹ÛŒØŒ Ú©Ø§Ø± Ù†Ú©Ø±Ø¯Ù† ÛŒØ§ Ù¾ÛŒÙ†Ú¯ Ø¨Ø§Ù„Ø§
        if any(w in text for w in ["ÙˆØµÙ„ Ù†Ù…ÛŒØ´Ù‡", "Ù‚Ø·Ø¹", "Ú©Ø§Ø± Ù†Ù…ÛŒÚ©Ù†Ù‡", "Ù¾ÛŒÙ†Ú¯", "Ø³Ø±Ø¹Øª", "Ú©Ù†Ø¯ÛŒ", "ØªØ§ÛŒÙ… Ø§ÙˆØª", "timeout", "ÙÛŒÙ„ØªØ±", "Ø¨Ø³ØªÙ‡ Ø´Ø¯Ù‡", "ÙˆØµÙ„ Ù†ÛŒØ³Øª"]):
            return (
                "Ø¨Ø±Ø§ÛŒ Ø±ÙØ¹ Ø³Ø±ÛŒØ¹ Ù…Ø´Ú©Ù„ Ø§ØªØµØ§Ù„ Ùˆ Ù‚Ø·Ø¹ÛŒØŒ Ù„Ø·ÙØ§Ù‹ Ø§ÛŒÙ† Ù…Ø±Ø§Ø­Ù„ Ù¾ÛŒØ´Ù†Ù‡Ø§Ø¯ÛŒ Ø±Ø§ Ø¨Ù‡ ØªØ±ØªÛŒØ¨ Ø§Ù†Ø¬Ø§Ù… Ø¯Ù‡ÛŒØ¯:\n\n"
                "Û±- **Ø­Ø§Ù„Øª Ù¾Ø±ÙˆØ§Ø² (Airplane Mode)** Ú¯ÙˆØ´ÛŒ Ø®ÙˆØ¯ Ø±Ø§ Ø¨Ù‡ Ù…Ø¯Øª Ûµ Ø«Ø§Ù†ÛŒÙ‡ Ø±ÙˆØ´Ù† Ùˆ Ø³Ù¾Ø³ Ø®Ø§Ù…ÙˆØ´ Ú©Ù†ÛŒØ¯ ØªØ§ IP Ø´Ø¨Ú©Ù‡ Ø´Ù…Ø§ Ù†Ùˆ Ø´ÙˆØ¯.\n"
                "Û²- Ø¯Ø± Ù†Ø±Ù…â€ŒØ§ÙØ²Ø§Ø± Ø®ÙˆØ¯ØŒ Ú¯Ø²ÛŒÙ†Ù‡ **Ø¨Ø±ÙˆØ²Ø±Ø³Ø§Ù†ÛŒ Ø§Ø´ØªØ±Ø§Ú© (Update Subscription)** Ø±Ø§ Ø¨Ø²Ù†ÛŒØ¯ ØªØ§ Ù„ÛŒØ³Øª Ø¬Ø¯ÛŒØ¯ØªØ±ÛŒÙ† Ø³Ø±ÙˆØ±Ù‡Ø§ Ø¯Ø±ÛŒØ§ÙØª Ø´ÙˆØ¯.\n"
                "Û³- Ø¯Ø± ØµÙˆØ±Øª Ø§Ø³ØªÙØ§Ø¯Ù‡ Ø§Ø² v2rayNG ÛŒØ§ StreisandØŒ Ù‚Ø§Ø¨Ù„ÛŒØª **Fragment** Ø±Ø§ Ø¯Ø± ØªÙ†Ø¸ÛŒÙ…Ø§Øª ÙØ¹Ø§Ù„ Ú©Ù†ÛŒØ¯Ø› Ø§ÛŒÙ† Ú©Ø§Ø± Ø§Ø®ØªÙ„Ø§Ù„ Ø§Ù¾Ø±Ø§ØªÙˆØ± Ø±Ø§ Ø¯ÙˆØ± Ù…ÛŒâ€ŒØ²Ù†Ø¯.\n"
                "Û´- Ø¯Ø± ØµÙˆØ±Øª Ø§Ù…Ú©Ø§Ù†ØŒ ÛŒÚ©â€ŒØ¨Ø§Ø± Ø§ÛŒÙ†ØªØ±Ù†Øª Ø®ÙˆØ¯ Ø±Ø§ Ø¨ÛŒÙ† Ù‡Ù…Ø±Ø§Ù‡ Ø§ÙˆÙ„ØŒ Ø§ÛŒØ±Ø§Ù†Ø³Ù„ ÛŒØ§ ÙˆØ§ÛŒâ€ŒÙØ§ÛŒ Ø³ÙˆÛŒÛŒÚ† Ú©Ù†ÛŒØ¯.\n\n"
                "Ù¾ÛŒØ§Ù… Ø´Ù…Ø§ Ø¨Ù‡ Ù¾Ø´ØªÛŒØ¨Ø§Ù† Ø§Ù†Ø³Ø§Ù†ÛŒ Ù†ÛŒØ² Ø§Ø±Ø¬Ø§Ø¹ Ø´Ø¯Ù‡ Ø§Ø³Øª Ùˆ Ø¯Ø± ØµÙˆØ±Øª Ø¹Ø¯Ù… Ø±ÙØ¹ Ù…Ø´Ú©Ù„ Ø¨Ù‡ Ø²ÙˆØ¯ÛŒ Ù¾Ø§Ø³Ø® Ø®ÙˆØ§Ù‡Ù†Ø¯ Ø¯Ø§Ø¯."
            )

        # Ø¬) Ø³ÛŒØ³ØªÙ…â€ŒØ¹Ø§Ù…Ù„ Ø¢ÛŒÙÙˆÙ† Ùˆ iOS
        if any(w in text for w in ["Ø¢ÛŒÙÙˆÙ†", "Ø§ÛŒÙÙˆÙ†", "iphone", "ios", "Ø§Ù¾Ù„", "apple"]):
            return (
                "Ø¨Ø±Ø§ÛŒ Ø¯Ø³ØªÚ¯Ø§Ù‡â€ŒÙ‡Ø§ÛŒ **iOS (Ø¢ÛŒÙÙˆÙ† Ùˆ Ø¢ÛŒÙ¾Ø¯)**ØŒ Ø¨Ù‡ØªØ±ÛŒÙ† Ùˆ Ø³Ø§Ø²Ú¯Ø§Ø±ØªØ±ÛŒÙ† Ù†Ø±Ù…â€ŒØ§ÙØ²Ø§Ø±Ù‡Ø§ Ø¹Ø¨Ø§Ø±ØªÙ†Ø¯ Ø§Ø²:\n\n"
                "ðŸ“± **Streisand** (Ù¾ÛŒØ´Ù†Ù‡Ø§Ø¯ Ø§ÙˆÙ„ - Ù¾Ø±Ø³Ø±Ø¹Øª Ùˆ Ù¾Ø§ÛŒØ¯Ø§Ø± Ø¯Ø± Ø§Ù¾â€ŒØ§Ø³ØªÙˆØ±)\n"
                "ðŸ“± **FoXray** (Ø¨Ø³ÛŒØ§Ø± Ù‚ÙˆÛŒ Ùˆ Ø³Ø§Ø²Ú¯Ø§Ø± Ø¨Ø§ Ø§Ù†ÙˆØ§Ø¹ Ú©Ø§Ù†ÙÛŒÚ¯â€ŒÙ‡Ø§)\n"
                "ðŸ“± **V2Box** (Ø±Ø§ÛŒÚ¯Ø§Ù† Ø¨Ø§ Ú©Ø§Ø±Ø¨Ø±ÛŒ Ø³Ø§Ø¯Ù‡)\n\n"
                "Ú©Ø§ÙÛŒØ³Øª Ù„ÛŒÙ†Ú© Ù‡ÙˆØ´Ù…Ù†Ø¯ Ø§Ø´ØªØ±Ø§Ú© Ø®ÙˆØ¯ Ø±Ø§ Ø§Ø² Ù‡Ù…ÛŒÙ† ØµÙØ­Ù‡ Ú©Ù¾ÛŒ Ù†Ù…ÙˆØ¯Ù‡ Ùˆ Ø¯Ø± Ù†Ø±Ù…â€ŒØ§ÙØ²Ø§Ø± Ù…Ø±Ø¨ÙˆØ·Ù‡ Ø§Ø¶Ø§ÙÙ‡ Ù†Ù…Ø§ÛŒÛŒØ¯."
            )

        # Ø¯) Ø³ÛŒØ³ØªÙ…â€ŒØ¹Ø§Ù…Ù„ Ø§Ù†Ø¯Ø±ÙˆÛŒØ¯
        if any(w in text for w in ["Ø§Ù†Ø¯Ø±ÙˆÛŒØ¯", "android", "Ø³Ø§Ù…Ø³ÙˆÙ†Ú¯", "Ø´ÛŒØ§Ø¦ÙˆÙ…ÛŒ"]):
            return (
                "Ø¨Ø±Ø§ÛŒ Ø¯Ø³ØªÚ¯Ø§Ù‡â€ŒÙ‡Ø§ÛŒ **Ø§Ù†Ø¯Ø±ÙˆÛŒØ¯**ØŒ Ù†Ø±Ù…â€ŒØ§ÙØ²Ø§Ø±Ù‡Ø§ÛŒ Ø§Ø³ØªØ§Ù†Ø¯Ø§Ø±Ø¯ Ø²ÛŒØ± Ù¾ÛŒØ´Ù†Ù‡Ø§Ø¯ Ù…ÛŒâ€ŒØ´ÙˆÙ†Ø¯:\n\n"
                "ðŸ¤– **v2rayNG** (Ù†Ø³Ø®Ù‡ Û±.Û¸.Û²Ûµ Ø¨Ù‡ Ø¨Ø§Ù„Ø§ Ø¨Ø§ Ù¾Ø´ØªÛŒØ¨Ø§Ù†ÛŒ Ø¹Ø§Ù„ÛŒ Ø§Ø² Fragment)\n"
                "ðŸ¤– **Hiddify Next** ÛŒØ§ **Sing-box**\n\n"
                "Ú©Ø§ÙÛŒ Ø§Ø³Øª Ù„ÛŒÙ†Ú© Ø³Ø§Ø¨ Ø±Ø§ Ø§Ø² Ø¯Ú©Ù…Ù‡ Ú©Ù¾ÛŒ Ù„ÛŒÙ†Ú© Ø¯Ø± Ù¾ÙˆØ±ØªØ§Ù„ Ú©Ù¾ÛŒ Ú©Ø±Ø¯Ù‡ Ùˆ Ø¯Ø± Ø¨Ø±Ù†Ø§Ù…Ù‡ ÙˆØ§Ø±Ø¯ ÙØ±Ù…Ø§ÛŒÛŒØ¯."
            )

        # Ù‡) Ø³ÙˆØ§Ù„Ø§Øª ØªÙ…Ø¯ÛŒØ¯ØŒ Ø´Ø§Ø±Ú˜ Ùˆ ÙØ§Ú©ØªÙˆØ±
        if any(w in text for w in ["ØªÙ…Ø¯ÛŒØ¯", "Ø®Ø±ÛŒØ¯", "ÙØ§Ú©ØªÙˆØ±", "Ù¾Ø±Ø¯Ø§Ø®Øª", "Ú©Ø§Ø±Øª", "ÙˆØ§Ø±ÛŒØ²", "Ù¾Ù„Ù†", "Ù‚ÛŒÙ…Øª"]):
            return (
                "Ø¬Ù‡Øª **ØªÙ…Ø¯ÛŒØ¯ Ø§Ø´ØªØ±Ø§Ú© ÛŒØ§ Ø®Ø±ÛŒØ¯ Ø­Ø¬Ù… Ø§Ø¶Ø§ÙÙ‡**:\n\n"
                "Ù…ÛŒâ€ŒØªÙˆØ§Ù†ÛŒØ¯ Ù…Ø³ØªÙ‚ÛŒÙ…Ø§Ù‹ Ø¯Ø± Ù‡Ù…ÛŒÙ† ØµÙØ­Ù‡ Ù¾ÙˆØ±ØªØ§Ù„ØŒ Ø§Ø² Ø¨Ø®Ø´ **Ù¾Ù„Ù†â€ŒÙ‡Ø§ÛŒ ØªÙ…Ø¯ÛŒØ¯**ØŒ Ù¾Ù„Ù† Ù…ÙˆØ±Ø¯ Ù†Ø¸Ø± Ø®ÙˆØ¯ Ø±Ø§ Ø§Ù†ØªØ®Ø§Ø¨ Ú©Ø±Ø¯Ù‡ Ùˆ Ø¨Ù‡ ØµÙˆØ±Øª Ø¢Ù†Ù„Ø§ÛŒÙ† ÛŒØ§ Ú©Ø§Ø±Øªâ€ŒØ¨Ù‡â€ŒÚ©Ø§Ø±Øª ÙˆØ§Ø±ÛŒØ² ÙØ±Ù…Ø§ÛŒÛŒØ¯. Ù¾Ø³ Ø§Ø² ÙˆØ§Ø±ÛŒØ² ÛŒØ§ ØªØ§ÛŒÛŒØ¯ ÙÛŒØ´ØŒ Ø§Ø´ØªØ±Ø§Ú© Ø´Ù…Ø§ Ø¨Ù‡ Ø·ÙˆØ± Ø®ÙˆØ¯Ú©Ø§Ø± Ø´Ø§Ø±Ú˜ Ùˆ ÙØ¹Ø§Ù„ Ù…ÛŒâ€ŒÚ¯Ø±Ø¯Ø¯."
            )

        # Ùˆ) Ø¨Ø±Ø±Ø³ÛŒ Ø¯Ø± ØµÙˆØ±Øª Ø§ØªØµØ§Ù„ Ø¨Ù‡ API Ø®Ø§Ø±Ø¬ÛŒ (OpenAI/Gemini/ØºÛŒØ±Ù‡)
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

        # Ù¾Ø§Ø³Ø® Ù¾ÛŒØ´â€ŒÙØ±Ø¶ Ù‡ÙˆØ´Ù…Ù†Ø¯ Ùˆ Ø®ÙˆØ´â€ŒØ¢Ù…Ø¯Ú¯ÙˆÛŒÛŒ
        return (
            "Ù¾ÛŒØ§Ù… Ø´Ù…Ø§ Ø¨Ø§ Ù…ÙˆÙÙ‚ÛŒØª Ø«Ø¨Øª Ùˆ Ø¨Ø±Ø±Ø³ÛŒ Ø´Ø¯. ðŸ¤–\n\n"
            "Ù…Ù† Ù‡ÙˆØ´ Ù…ØµÙ†ÙˆØ¹ÛŒ Ù¾Ø´ØªÛŒØ¨Ø§Ù†ÛŒ Ù‡Ø³ØªÙ…Ø› Ù¾ÛŒØ§Ù…â€ŒØªØ§Ù† Ù‡Ù…Ø²Ù…Ø§Ù† Ø¨Ø±Ø§ÛŒ Ú©Ø§Ø±Ø´Ù†Ø§Ø³Ø§Ù† Ù¾Ø´ØªÛŒØ¨Ø§Ù†ÛŒ Ø§Ø±Ø³Ø§Ù„ Ø´Ø¯Ù‡ Ùˆ Ø¯Ø± ØµÙˆØ±Øª Ù†ÛŒØ§Ø² Ø¨Ù‡ Ø²ÙˆØ¯ÛŒ Ø¨Ù‡ Ø´Ù…Ø§ Ù¾Ø§Ø³Ø® Ø®ÙˆØ§Ù‡Ù†Ø¯ Ø¯Ø§Ø¯.\n"
            "Ø§Ú¯Ø± Ø¯Ø± Ø®ØµÙˆØµ Ø§ØªØµØ§Ù„ØŒ Ù†Ø±Ù…â€ŒØ§ÙØ²Ø§Ø±Ù‡Ø§ ÛŒØ§ ØªÙ…Ø¯ÛŒØ¯ Ø³ÙˆØ§Ù„ÛŒ Ø¯Ø§Ø±ÛŒØ¯ØŒ Ø¨ÙØ±Ù…Ø§ÛŒÛŒØ¯ ØªØ§ Ø±Ø§Ù‡Ù†Ù…Ø§ÛŒÛŒâ€ŒØªØ§Ù† Ú©Ù†Ù…."
        )

    def get_all_tickets(self, status=None, reseller_id=None, search=None, vip_only=False, category=None):
        """Ø¯Ø±ÛŒØ§ÙØª ØªÙ…Ø§Ù… ØªÛŒÚ©Øªâ€ŒÙ‡Ø§ Ø¨Ø§ ÙÛŒÙ„ØªØ± ÙˆØ¶Ø¹ÛŒØªØŒ Ø¬Ø³ØªØ¬ÙˆØŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ Ùˆ ØªÙÚ©ÛŒÚ© Ø¯Ø³ØªÙ‡â€ŒØ¨Ù†Ø¯ÛŒ Ù…Ø´ØªØ±ÛŒØ§Ù† Ùˆ Ù†Ù…Ø§ÛŒÙ†Ø¯Ú¯Ø§Ù†"""
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

            # ÙÛŒÙ„ØªØ± Ø¯Ø³ØªÙ‡â€ŒØ¨Ù†Ø¯ÛŒ Ùˆ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡
            if reseller_id is not None:
                # Ù¾Ù†Ù„ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡
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
                # Ù¾Ù†Ù„ Ù…Ø¯ÛŒØ±ÛŒØª
                if category == "resellers":
                    query += " AND t.ticket_type IN ('reseller_to_admin', 'quota_change', 'reseller_application')"
                elif category == "customers":
                    query += " AND (t.reseller_id IS NULL OR t.reseller_id = 0) AND (t.ticket_type NOT IN ('reseller_to_admin', 'quota_change', 'reseller_application') OR t.ticket_type IS NULL)"
                # Ø§Ú¯Ø± category == 'all' ÛŒØ§ Ù†Ø§Ù…Ø´Ø®Øµ Ø¨ÙˆØ¯ØŒ Ù‡Ù…Ù‡ Ø±Ø§ Ø¨Ø±Ù…ÛŒâ€ŒÚ¯Ø±Ø¯Ø§Ù†Ø¯

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
        """Ø¯Ø±ÛŒØ§ÙØª Ø§Ø·Ù„Ø§Ø¹Ø§Øª Ø¬Ø§Ù…Ø¹ ØªÛŒÚ©Øª Ø¨Ù‡ Ù‡Ù…Ø±Ø§Ù‡ Ù¾Ø±ÙˆÙØ§ÛŒÙ„ Ú©Ø§Ø±Ø¨Ø±ØŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ Ùˆ ØªØ§Ø±ÛŒØ®Ú†Ù‡ Ú¯ÙØªÚ¯Ùˆ"""
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
        """Ù…Ø­Ø§Ø³Ø¨Ù‡ Ø¢Ù…Ø§Ø± ØªÙÚ©ÛŒÚ©ÛŒ ØªÛŒÚ©Øªâ€ŒÙ‡Ø§ Ø¨Ø±Ø§ÛŒ ØªØ¨â€ŒÙ‡Ø§ÛŒ ÙÛŒÙ„ØªØ± Ø¨Ø§ ØªÙÚ©ÛŒÚ© Ù…Ø´ØªØ±ÛŒØ§Ù† Ùˆ Ù†Ù…Ø§ÛŒÙ†Ø¯Ú¯Ø§Ù†"""
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
                # Ù¾Ù†Ù„ Ù…Ø¯ÛŒØ±ÛŒØª
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
                # Ù¾Ù†Ù„ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡
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
        """Ø«Ø¨Øª ØªÛŒÚ©Øª Ù…Ø³ØªÙ‚ÛŒÙ… ØªÙˆØ³Ø· Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ Ø¨Ø±Ø§ÛŒ Ù¾Ù†Ù„ Ù…Ø¯ÛŒØ±ÛŒØª"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("SELECT * FROM resellers WHERE id=?", (reseller_id,))
            reseller = cursor.fetchone()
            r_name = reseller["name"] if reseller else f"Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ #{reseller_id}"
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
        """Ø§Ø±Ø³Ø§Ù„ Ù¾Ø§Ø³Ø® Ø§Ø² Ø³Ù…Øª Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ Ø¯Ø± ØªÛŒÚ©Øª Ù…Ú©Ø§ØªØ¨Ù‡ Ø¨Ø§ Ù…Ø¯ÛŒØ±ÛŒØª"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("SELECT * FROM support_tickets WHERE id=? AND reseller_id=?", (ticket_id, reseller_id))
            ticket = cursor.fetchone()
            if not ticket:
                return {"success": False, "error": "ØªÛŒÚ©Øª ÛŒØ§ÙØª Ù†Ø´Ø¯"}

            cursor.execute("SELECT * FROM resellers WHERE id=?", (reseller_id,))
            reseller = cursor.fetchone()
            r_name = reseller["name"] if reseller else f"Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ #{reseller_id}"

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
        """Ø¯Ø±ÛŒØ§ÙØª ÛŒÚ© ØªÛŒÚ©Øª Ø¨Ø± Ø§Ø³Ø§Ø³ Ø´Ù†Ø§Ø³Ù‡"""
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

    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    # Ù…Ø¯ÛŒØ±ÛŒØª Ø±ÙØ±Ø§Ù„ Ùˆ Ø²ÛŒØ±Ù…Ø¬Ù…ÙˆØ¹Ù‡â€ŒÚ¯ÛŒØ±ÛŒ
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

    def add_referral(self, referrer_id, referred_id):
        """Ø«Ø¨Øª Ú©Ø§Ø±Ø¨Ø± Ù…Ø¹Ø±ÙÛŒ Ø´Ø¯Ù‡"""
        if referrer_id == referred_id:
            return {"success": False, "error": "self_referral"}
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            # Ø«Ø¨Øª Ø¯Ø± Ø¬Ø¯ÙˆÙ„ referrals
            cursor.execute("""
                INSERT OR IGNORE INTO referrals (referrer_id, referred_id, reward_amount, status, created_at, updated_at)
                VALUES (?, ?, 0, 'pending', ?, ?)
            """, (referrer_id, referred_id, now, now))
            # Ø«Ø¨Øª Ù…Ø¹Ø±Ù Ø¯Ø± Ø¬Ø¯ÙˆÙ„ users
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
        """Ø¯Ø±ÛŒØ§ÙØª Ø¢Ù…Ø§Ø± Ø±ÙØ±Ø§Ù„ Ú©Ø§Ø±Ø¨Ø±"""
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
        """ØªÚ©Ù…ÛŒÙ„ Ù¾Ø§Ø¯Ø§Ø´ Ø±ÙØ±Ø§Ù„ Ù¾Ø³ Ø§Ø² Ø®Ø±ÛŒØ¯ Ú©Ø§Ø±Ø¨Ø±"""
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
            
            # Ø§ÙØ²ÙˆØ¯Ù† Ù¾Ø§Ø¯Ø§Ø´ Ø¨Ù‡ Ú©ÛŒÙ Ù¾ÙˆÙ„ Ù…Ø¹Ø±Ù
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


    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    # Ù…Ø¯ÛŒØ±ÛŒØª Ø§Ø¹Ù„Ø§Ù†â€ŒÙ‡Ø§
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

    def save_notification(self, telegram_id, notification_type, subscription_id=None):
        """Ø°Ø®ÛŒØ±Ù‡ Ø§Ø¹Ù„Ø§Ù† Ø§Ø±Ø³Ø§Ù„ Ø´Ø¯Ù‡"""
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
        """Ø¨Ø±Ø±Ø³ÛŒ Ø§Ø±Ø³Ø§Ù„ Ø´Ø¯Ù† Ø§Ø¹Ù„Ø§Ù†"""
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

    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    # Ø¢Ù…Ø§Ø± Ù¾ÛŒØ´Ø±ÙØªÙ‡
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

    def get_advanced_stats(self):
        """Ø¯Ø±ÛŒØ§ÙØª Ø¢Ù…Ø§Ø± Ù¾ÛŒØ´Ø±ÙØªÙ‡"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            stats = {}
            
            # Ø¢Ù…Ø§Ø± Ú©Ù„ÛŒ
            cursor.execute("SELECT COUNT(*) as count FROM users")
            stats["total_users"] = cursor.fetchone()["count"]
            
            cursor.execute("SELECT COUNT(*) as count FROM subscriptions WHERE status = 'active'")
            stats["active_subscriptions"] = cursor.fetchone()["count"]
            
            cursor.execute("SELECT COUNT(*) as count FROM subscriptions WHERE status = 'expired'")
            stats["expired_subscriptions"] = cursor.fetchone()["count"]
            
            # Ø¯Ø±Ø¢Ù…Ø¯ Ù…Ø§Ù‡Ø§Ù†Ù‡
            cursor.execute("""SELECT COALESCE(SUM(amount), 0) as total FROM transactions 
                WHERE status IN ('approved', 'completed') AND (is_deleted = 0 OR is_deleted IS NULL) AND created_at >= date('now', '-30 days')""")
            stats["monthly_revenue"] = cursor.fetchone()["total"]
            
            # Ø¯Ø±Ø¢Ù…Ø¯ Ø§Ù…Ø±ÙˆØ²
            cursor.execute("""SELECT COALESCE(SUM(amount), 0) as total FROM transactions 
                WHERE status IN ('approved', 'completed') AND (is_deleted = 0 OR is_deleted IS NULL) AND date(created_at) = date('now')""")
            stats["today_revenue"] = cursor.fetchone()["total"]
            
            # Ú©Ø§Ø±Ø¨Ø±Ø§Ù† Ø¬Ø¯ÛŒØ¯ Ø§Ù…Ø±ÙˆØ²
            cursor.execute("SELECT COUNT(*) as count FROM users WHERE date(created_at) = date('now')")
            stats["today_new_users"] = cursor.fetchone()["count"]
            
            # ØªÛŒÚ©Øªâ€ŒÙ‡Ø§ÛŒ Ø¨Ø§Ø²
            cursor.execute("SELECT COUNT(*) as count FROM support_tickets WHERE status = 'open'")
            stats["open_tickets"] = cursor.fetchone()["count"]
            
            # Ú©Ø§Ø±Ø¨Ø±Ø§Ù† Ø¨Ù„Ø§Ú© Ø´Ø¯Ù‡
            cursor.execute("SELECT COUNT(*) as count FROM blocked_users")
            stats["blocked_users"] = cursor.fetchone()["count"]
            
            # Ù…Ø­Ø¨ÙˆØ¨â€ŒØªØ±ÛŒÙ† Ù¾Ù„Ù†
            cursor.execute("""SELECT plan_name, COUNT(*) as count FROM subscriptions 
                GROUP BY plan_name ORDER BY count DESC LIMIT 5""")
            stats["popular_plans"] = [dict(row) for row in cursor.fetchall()]
            
            return stats
        except Exception as e:
            logger.error(f"Error getting advanced stats: {e}")
            return {}
        finally:
            conn.close()

    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    # Ø¢Ù…Ø§Ø±
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

    def get_stats(self):
        """Ø¯Ø±ÛŒØ§ÙØª Ø¢Ù…Ø§Ø± Ø¯Ù‚ÛŒÙ‚ Ø¯ÛŒØªØ§Ø¨ÛŒØ³"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            stats = {}

            # ØªØ¹Ø¯Ø§Ø¯ Ú©Ø§Ø±Ø¨Ø±Ø§Ù†
            cursor.execute("SELECT COUNT(*) as count FROM users")
            stats["total_users"] = cursor.fetchone()["count"]

            # ØªØ¹Ø¯Ø§Ø¯ ØªØ±Ø§Ú©Ù†Ø´â€ŒÙ‡Ø§
            cursor.execute("SELECT COUNT(*) as count FROM transactions")
            stats["total_transactions"] = cursor.fetchone()["count"]

            # ØªØ±Ø§Ú©Ù†Ø´â€ŒÙ‡Ø§ÛŒ Ø¯Ø± Ø§Ù†ØªØ¸Ø§Ø±
            cursor.execute("SELECT COUNT(*) as count FROM transactions WHERE status = 'pending'")
            stats["pending_transactions"] = cursor.fetchone()["count"]

            # ØªØ±Ø§Ú©Ù†Ø´â€ŒÙ‡Ø§ÛŒ ØªØ§ÛŒÛŒØ¯ Ø´Ø¯Ù‡
            cursor.execute("SELECT COUNT(*) as count FROM transactions WHERE status IN ('approved', 'completed')")
            stats["completed_transactions"] = cursor.fetchone()["count"]

            # ØªØ±Ø§Ú©Ù†Ø´â€ŒÙ‡Ø§ÛŒ Ø±Ø¯ Ø´Ø¯Ù‡
            cursor.execute("SELECT COUNT(*) as count FROM transactions WHERE status = 'rejected'")
            stats["rejected_transactions"] = cursor.fetchone()["count"]

            # Ø¯Ø±Ø¢Ù…Ø¯ Ú©Ù„
            cursor.execute("SELECT COALESCE(SUM(amount), 0) as total FROM transactions WHERE status IN ('approved', 'completed') AND (is_deleted = 0 OR is_deleted IS NULL)")
            stats["total_revenue"] = cursor.fetchone()["total"]

            # ØªØ¹Ø¯Ø§Ø¯ Ù¾Ø´ØªÛŒØ¨Ø§Ù†â€ŒÙ‡Ø§
            cursor.execute("SELECT COUNT(*) as count FROM backups")
            stats["total_backups"] = cursor.fetchone()["count"]

            # ØªØ¹Ø¯Ø§Ø¯ Ø§Ø´ØªØ±Ø§Ú©â€ŒÙ‡Ø§
            cursor.execute("SELECT COUNT(*) as count FROM subscriptions")
            stats["total_subscriptions"] = cursor.fetchone()["count"]

            cursor.execute("SELECT COUNT(*) as count FROM subscriptions WHERE status = 'active'")
            stats["active_subscriptions"] = cursor.fetchone()["count"]

            # Ú©Ø§Ø±Øªâ€ŒÙ‡Ø§ÛŒ ÙØ¹Ø§Ù„ Ø¨Ø§Ù†Ú©ÛŒ
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
        """Ø«Ø¨Øª ØªØ§Ø±ÛŒØ®Ú†Ù‡ Ùˆ Ù…ÛŒØ²Ø§Ù† Ù…ØµØ±Ù Ø¯ÙˆØ±Ù‡ Ù‚Ø¨Ù„ÛŒ Ù‡Ù…Ø±Ø§Ù‡ Ø¨Ø§ Ù‚ÛŒÙ…Øª Ù¾Ù„Ù† Ù‡Ù†Ú¯Ø§Ù… ØªÙ…Ø¯ÛŒØ¯ ÛŒØ§ ØªØºÛŒÛŒØ± Ø¯ÙˆØ±Ù‡ Ø§Ø´ØªØ±Ø§Ú©"""
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
        """Ø§ÙØ²ÙˆØ¯Ù† Ø¯Ø³ØªÛŒ Ø³Ø§Ø¨Ù‚Ù‡ Ùˆ Ú¯Ø²Ø§Ø±Ø´ Ø¯ÙˆØ±Ù‡ Ù‚Ø¨Ù„ÛŒ Ù…Ø´ØªØ±ÛŒ Ø¨Ø§ Ø¨Ø±Ú†Ø³Ø¨ Ø¯ÙˆØ±Ù‡ØŒ Ø­Ø¬Ù…ØŒ Ù…Ø¯Øª Ùˆ ØªÚ¯ Ø¯Ø³ØªÛŒ"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            if reseller_id:
                cursor.execute("SELECT * FROM subscriptions WHERE id=? AND reseller_id=?", (subscription_id, reseller_id))
            else:
                cursor.execute("SELECT * FROM subscriptions WHERE id=?", (subscription_id,))
            sub_row = cursor.fetchone()
            if not sub_row:
                return {"success": False, "error": "Ø§Ø´ØªØ±Ø§Ú© Ù…ÙˆØ±Ø¯ Ù†Ø¸Ø± ÛŒØ§ÙØª Ù†Ø´Ø¯ ÛŒØ§ Ø¯Ø³ØªØ±Ø³ÛŒ Ù…Ø¬Ø§Ø² Ù†ÛŒØ³Øª"}

            sub_dict = dict(sub_row)
            
            p_limit = float(previous_limit_gb) if (previous_limit_gb is not None and float(previous_limit_gb) > 0) else float(sub_dict.get("data_limit") or previous_usage_gb or 0)
            p_days = int(period_days) if (period_days and int(period_days) > 0) else int(sub_dict.get("duration") or 30)
            p_name = plan_name.strip() if (plan_name and plan_name.strip()) else (sub_dict.get("plan_name") or "Ù¾Ù„Ù† Ø³ÙØ§Ø±Ø´ÛŒ")
            
            p_offset = int(period_offset) if period_offset else 1
            if not period_label or not period_label.strip():
                if p_offset == 1:
                    lbl = "Û± Ø¯ÙˆØ±Ù‡ Ù‚Ø¨Ù„ (Ø¯ÙˆØ±Ù‡ Ú¯Ø°Ø´ØªÙ‡)"
                elif p_offset == 2:
                    lbl = "Û² Ø¯ÙˆØ±Ù‡ Ù‚Ø¨Ù„"
                elif p_offset == 3:
                    lbl = "Û³ Ø¯ÙˆØ±Ù‡ Ù‚Ø¨Ù„"
                elif p_offset == 4:
                    lbl = "Û´ Ø¯ÙˆØ±Ù‡ Ù‚Ø¨Ù„"
                elif p_offset == 5:
                    lbl = "Ûµ Ø¯ÙˆØ±Ù‡ Ù‚Ø¨Ù„"
                else:
                    lbl = f"{p_offset} Ø¯ÙˆØ±Ù‡ Ù‚Ø¨Ù„"
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
            return {"success": True, "id": inserted_id, "message": "Ø³Ø§Ø¨Ù‚Ù‡ Ø¯ÙˆØ±Ù‡ Ø¯Ø³ØªÛŒ Ø¨Ø§ Ù…ÙˆÙÙ‚ÛŒØª Ø§Ø¶Ø§ÙÙ‡ Ø´Ø¯"}
        except Exception as e:
            logger.error(f"Error adding manual subscription history: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def delete_subscription_history_entry(self, history_id: int, reseller_id: int = None) -> bool:
        """Ø­Ø°Ù ÛŒÚ© Ø±Ú©ÙˆØ±Ø¯ Ø³Ø§Ø¨Ù‚Ù‡ Ø¯ÙˆØ±Ù‡ Ø¨Ø§ Ø¨Ø±Ø±Ø³ÛŒ Ø¯Ø³ØªØ±Ø³ÛŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ ÛŒØ§ Ù…Ø¯ÛŒØ±"""
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
        """Ù†Ø§Ù… Ù…Ø³ØªØ¹Ø§Ø± Ø¨Ø±Ø§ÛŒ save_subscription_history Ø¬Ù‡Øª Ø³Ø§Ø²Ú¯Ø§Ø±ÛŒ Ú©Ø§Ù…Ù„"""
        return self.save_subscription_history(*args, **kwargs)

    def get_subscription_history(self, subscription_id: int = None, telegram_id: int = None,
                                reseller_id: int = None, limit: int = 50) -> list:
        """Ø¯Ø±ÛŒØ§ÙØª Ø³ÙˆØ§Ø¨Ù‚ Ù…ØµØ±Ù Ø¯ÙˆØ±Ù‡â€ŒÙ‡Ø§ÛŒ Ù‚Ø¨Ù„ÛŒ Ø§Ø´ØªØ±Ø§Ú©â€ŒÙ‡Ø§ Ø¨Ø§ Ø¬Ø²Ø¦ÛŒØ§Øª Ù‚ÛŒÙ…Øª Ùˆ Ø²Ù…Ø§Ù†"""
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
        """Ø¯Ø±ÛŒØ§ÙØª Ø§Ø·Ù„Ø§Ø¹Ø§Øª Ø¬Ø§Ù…Ø¹ Ø§Ø´ØªØ±Ø§Ú© Ø¨Ù‡ Ù‡Ù…Ø±Ø§Ù‡ Ø¢Ø±Ø´ÛŒÙˆ ØªÙ…Ø§Ù… Ø¯ÙˆØ±Ù‡â€ŒÙ‡Ø§ Ùˆ Ù…Ø¨Ø§Ù„Øº Ù¾Ø±Ø¯Ø§Ø®ØªÛŒ Ú¯Ø°Ø´ØªÙ‡"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            if reseller_id:
                cursor.execute("SELECT * FROM subscriptions WHERE id=? AND reseller_id=?", (sub_id, reseller_id))
            else:
                cursor.execute("SELECT * FROM subscriptions WHERE id=?", (sub_id,))
            sub_row = cursor.fetchone()
            if not sub_row:
                return {"success": False, "error": "Ø§Ø´ØªØ±Ø§Ú© ÛŒØ§ÙØª Ù†Ø´Ø¯"}

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
        """ØªÙ†Ø¸ÛŒÙ… ÛŒØ§ Ø¨Ø±ÙˆØ²Ø±Ø³Ø§Ù†ÛŒ ÙˆØ¶Ø¹ÛŒØª Ø¨Ø¯Ù‡ÛŒ Ù…Ø´ØªØ±ÛŒ"""
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
        Ø«Ø¨Øª Ø±Ø³ÛŒØ¯ Ø¨Ø¯Ù‡ÛŒ Ø§Ø®ØªØµØ§ØµÛŒ Ø¨Ø±Ø§ÛŒ Ø®Ø±ÛŒØ¯ ÛŒØ§ ØªÙ…Ø¯ÛŒØ¯ Ù…Ø´ØªØ±ÛŒ Ø¨Ù‡ Ù‡Ù…Ø±Ø§Ù‡ ØªØ¬Ù…ÛŒØ¹ Ø®ÙˆØ¯Ú©Ø§Ø± Ùˆ Ø¯Ù‚ÛŒÙ‚ Ø¨Ø§ Ø¨Ø¯Ù‡ÛŒ Ù‚Ø¨Ù„ÛŒ
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("SELECT * FROM subscriptions WHERE id = ?", (subscription_id,))
            sub_row = cursor.fetchone()
            if not sub_row:
                return {"success": False, "error": "Ø§Ø´ØªØ±Ø§Ú© ÛŒØ§ÙØª Ù†Ø´Ø¯"}

            sub = dict(sub_row)
            added_amount = int(amount or 0)

            # Ù…Ø­Ø§Ø³Ø¨Ù‡ Ø¯Ù‚ÛŒÙ‚ Ø¨Ø¯Ù‡ÛŒ Ù‚Ø¨Ù„ÛŒ
            if previous_debt is not None:
                prev_debt = max(0, int(previous_debt))
            elif action_type == "create":
                # Ø¯Ø± Ø²Ù…Ø§Ù† Ø³Ø§Ø®Øª Ø§ÙˆÙ„ÛŒÙ‡ Ø§Ø´ØªØ±Ø§Ú©ØŒ Ø¨Ø¯Ù‡ÛŒ Ù‚Ø¨Ù„ÛŒ Ù‚Ø·Ø¹Ø§Ù‹ ØµÙØ± Ø§Ø³Øª
                prev_debt = 0
            else:
                # Ù…Ø­Ø§Ø³Ø¨Ù‡ Ø¨Ø± Ø§Ø³Ø§Ø³ Ù…Ø¬Ù…ÙˆØ¹ ÙØ§Ú©ØªÙˆØ±Ù‡Ø§ÛŒ Ø¨Ø§Ø² Ø«Ø¨Øªâ€ŒØ´Ø¯Ù‡ Ù‚Ø¨Ù„ÛŒ
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

            # Ø¨Ø±ÙˆØ²Ø±Ø³Ø§Ù†ÛŒ Ø§Ø´ØªØ±Ø§Ú© Ø¨Ù‡ ÙˆØ¶Ø¹ÛŒØª Ø¨Ø¯Ù‡Ú©Ø§Ø± Ùˆ Ø«Ø¨Øª Ù…Ø¬Ù…ÙˆØ¹ ØªØ¬Ù…Ø¹ÛŒ ØµØ­ÛŒØ­ Ø¨Ø¯Ù‡ÛŒ
            cursor.execute("""
                UPDATE subscriptions
                SET payment_status = 'unpaid',
                    debt_amount = ?,
                    debt_notes = COALESCE(?, debt_notes),
                    debt_created_at = COALESCE(debt_created_at, ?),
                    updated_at = ?
                WHERE id = ?
            """, (total_debt, notes, now, now, subscription_id))

            # Ø«Ø¨Øª Ø±Ú©ÙˆØ±Ø¯ Ù…Ø¬Ø²Ø§ Ø¯Ø± Ø¬Ø¯ÙˆÙ„ customer_debt_records
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
        Ø¨Ø±Ø±Ø³ÛŒ Ùˆ Ø®ÙˆØ¯ØªØ±Ù…ÛŒÙ…ÛŒ Ø¬Ø§Ù…Ø¹ Ø²Ù†Ø¬ÛŒØ±Ù‡ Ù…Ø­Ø§Ø³Ø¨Ø§ØªÛŒ Ø¨Ø¯Ù‡ÛŒâ€ŒÙ‡Ø§ Ùˆ Ø±Ø³ÛŒØ¯Ù‡Ø§:
        - Ø§ØµÙ„Ø§Ø­ previous_debt Ùˆ total_debt Ø¨Ø± Ø§Ø³Ø§Ø³ ØªØ§Ø±ÛŒØ®Ú†Ù‡ Ø²Ù…Ø§Ù†ÛŒ Ùˆ Ù…Ø¨Ø§Ù„Øº ÙˆØ§Ù‚Ø¹ÛŒ
        - Ù‡Ù…Ú¯Ø§Ù…â€ŒØ³Ø§Ø²ÛŒ subscriptions.debt_amount Ùˆ payment_status Ø¨Ø§ Ø¬Ù…Ø¹ ÙØ§Ú©ØªÙˆØ±Ù‡Ø§ÛŒ Ø¨Ø§Ø²
        - ØªØµØ­ÛŒØ­ ÛŒØ§Ø¯Ø¯Ø§Ø´Øªâ€ŒÙ‡Ø§ÛŒ Ú©Ù¾ÛŒâ€ŒØ´Ø¯Ù‡ Ù…Ø±Ø¨ÙˆØ· Ø¨Ù‡ Ø³Ø§Ø®Øª Ø§Ø´ØªØ±Ø§Ú© Ø±ÙˆÛŒ Ø±Ú©ÙˆØ±Ø¯Ù‡Ø§ÛŒ ØªÙ…Ø¯ÛŒØ¯
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

                    # Ø§ØµÙ„Ø§Ø­ ÛŒØ§Ø¯Ø¯Ø§Ø´Øªâ€ŒÙ‡Ø§ÛŒÛŒ Ú©Ù‡ Ù…ØªÙ† Ø³Ø§Ø®Øª Ø§Ø´ØªØ±Ø§Ú© Ø±Ø§ Ø±ÙˆÛŒ ØªÙ…Ø¯ÛŒØ¯ Ú©Ù¾ÛŒ Ú©Ø±Ø¯Ù‡ Ø¨ÙˆØ¯Ù†Ø¯
                    new_notes = notes
                    if act_type == "renew" and "Ø³Ø§Ø®Øª Ø§Ø´ØªØ±Ø§Ú©" in str(notes):
                        new_notes = str(notes).replace("Ø³Ø§Ø®Øª Ø§Ø´ØªØ±Ø§Ú©", "ØªÙ…Ø¯ÛŒØ¯ Ø§Ø´ØªØ±Ø§Ú©")

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

                # Ù…Ø­Ø§Ø³Ø¨Ù‡ Ø¬Ù…Ø¹ ÙˆØ§Ù‚Ø¹ÛŒ Ø±Ø³ÛŒØ¯Ù‡Ø§ÛŒ Ø¨Ø§Ø² Ùˆ Ù‡Ù…Ú¯Ø§Ù…â€ŒØ³Ø§Ø²ÛŒ Ø§Ø´ØªØ±Ø§Ú©
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
        Ø¯Ø±ÛŒØ§ÙØª Ú¯Ø²Ø§Ø±Ø´ Ø¬Ø§Ù…Ø¹ Ø¨Ø¯Ù‡ÛŒâ€ŒÙ‡Ø§ÛŒ ÛŒÚ© Ù…Ø´ØªØ±ÛŒ Ø´Ø§Ù…Ù„ Ø¬Ù…Ø¹ Ú©Ù„ØŒ Ø¨Ø¯Ù‡ÛŒ ÙØ¹Ù„ÛŒ Ùˆ Ù„ÛŒØ³Øª Ø±Ø³ÛŒØ¯Ù‡Ø§ Ø¨Ù‡ Ù‡Ù…Ø±Ø§Ù‡ Ø®ÙˆØ¯ØªØ±Ù…ÛŒÙ…ÛŒ Ø®ÙˆØ¯Ú©Ø§Ø±
        """
        # Ø§Ø¨ØªØ¯Ø§ Ø®ÙˆØ¯ØªØ±Ù…ÛŒÙ…ÛŒ Ø§Ø¬Ø±Ø§ Ù…ÛŒâ€ŒØ´ÙˆØ¯ ØªØ§ Ù‡Ø±Ú¯ÙˆÙ†Ù‡ Ø§Ù†Ø­Ø±Ø§Ù Ø¯Ø± Ø¯ÛŒØªØ§Ø¨ÛŒØ³ Ø®ÙˆØ¯Ø¨Ù‡â€ŒØ®ÙˆØ¯ Ø§ØµÙ„Ø§Ø­ Ø´ÙˆØ¯
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
                return {"success": False, "error": "Ø§Ø´ØªØ±Ø§Ú© ÛŒØ§ÙØª Ù†Ø´Ø¯"}

            sub = dict(sub_row)
            cursor.execute("""
                SELECT * FROM customer_debt_records 
                WHERE subscription_id = ? 
                ORDER BY created_at DESC, id DESC
            """, (subscription_id,))
            rows = cursor.fetchall()
            records = [dict(r) for r in rows]

            current_debt = int(sub.get("debt_amount") or 0)

            # Ø§Ú¯Ø± Ø±Ú©ÙˆØ±Ø¯ÛŒ Ù‡Ù†ÙˆØ² Ø¯Ø± Ø¬Ø¯ÙˆÙ„ Ø¬Ø¯ÛŒØ¯ Ø«Ø¨Øª Ù†Ø´Ø¯Ù‡ ÙˆÙ„ÛŒ Ø¯Ø± Ø³Ø§Ø¨Ø³Ú©Ø±ÛŒÙ¾Ø´Ù† Ø¨Ø¯Ù‡ÛŒ ÙˆØ¬ÙˆØ¯ Ø¯Ø§Ø±Ø¯ØŒ Ø±Ú©ÙˆØ±Ø¯ Ø¢ØºØ§Ø²ÛŒÙ† Ø¯Ø±Ø¬ Ú©Ù†ÛŒÙ…
            if not records and current_debt > 0:
                now = get_now_iso()
                notes = sub.get("debt_notes") or "Ø¨Ø¯Ù‡ÛŒ Ù‚Ø¨Ù„ÛŒ Ø«Ø¨Øªâ€ŒØ´Ø¯Ù‡ Ø¯Ø± Ø³ÛŒØ³ØªÙ…"
                cursor.execute("""
                    INSERT INTO customer_debt_records
                    (subscription_id, account_name, telegram_id, reseller_id, action_type, plan_name,
                     amount, previous_debt, total_debt, status, notes, created_by, created_at, updated_at)
                    VALUES (?, ?, ?, ?, 'initial', ?, ?, 0, ?, 'unpaid', ?, ?, ?, ?)
                """, (
                    subscription_id, sub.get("account_name") or "", sub.get("telegram_id") or 0,
                    sub.get("reseller_id"), sub.get("plan_name") or "Ø§Ø´ØªØ±Ø§Ú©",
                    current_debt, current_debt, notes, sub.get("created_by") or "Ø³ÛŒØ³ØªÙ…",
                    sub.get("debt_created_at") or now, now
                ))
                conn.commit()
                cursor.execute("SELECT * FROM customer_debt_records WHERE subscription_id = ? ORDER BY id DESC", (subscription_id,))
                records = [dict(r) for r in cursor.fetchall()]

            total_debts_sum = sum(int(r.get("amount") or 0) for r in records if r.get("action_type") in ("create", "renew", "manual", "initial"))
            total_settled_sum = sum(int(r.get("amount") or 0) for r in records if r.get("status") == "paid" and r.get("action_type") != "settle")
            unpaid_count = sum(1 for r in records if r.get("status") == "unpaid" and r.get("action_type") != "settle")

            # Ù…Ø­Ø§Ø³Ø¨Ù‡ Ù‚Ø·Ø¹ÛŒ Ø¨Ø¯Ù‡ÛŒ Ù…Ø¹ÙˆÙ‚Ù‡ Ø¨Ø± Ø§Ø³Ø§Ø³ Ø¬Ù…Ø¹ ÙØ§Ú©ØªÙˆØ±Ù‡Ø§ÛŒ Ø¨Ø§Ø²
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
                                    amount: int = None, settled_by: str = "Ù…Ø¯ÛŒØ±ÛŒØª",
                                    order_id: str = None) -> dict:
        """
        ØªØ³ÙˆÛŒÙ‡ ÛŒÚ© Ø±Ø³ÛŒØ¯ Ø¨Ø¯Ù‡ÛŒ Ø®Ø§Øµ ÛŒØ§ ØªØ³ÙˆÛŒÙ‡ Ø¨Ø®Ø´ÛŒ Ø§Ø² Ø¨Ø¯Ù‡ÛŒ Ù…Ø´ØªØ±ÛŒ Ø¨Ø§ Ù…Ø­Ø§Ø³Ø¨Ù‡ Ø¯Ù‚ÛŒÙ‚ Ù…Ø§Ù†Ø¯Ù‡
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("SELECT * FROM subscriptions WHERE id = ?", (subscription_id,))
            sub_row = cursor.fetchone()
            if not sub_row:
                return {"success": False, "error": "Ø§Ø´ØªØ±Ø§Ú© ÛŒØ§ÙØª Ù†Ø´Ø¯"}

            sub = dict(sub_row)
            current_debt = int(sub.get("debt_amount") or 0)

            if record_id:
                cursor.execute("SELECT * FROM customer_debt_records WHERE id = ? AND subscription_id = ?", (record_id, subscription_id))
                rec = cursor.fetchone()
                if not rec:
                    return {"success": False, "error": "Ø±Ø³ÛŒØ¯ Ø¨Ø¯Ù‡ÛŒ ÛŒØ§ÙØª Ù†Ø´Ø¯"}
                rec_dict = dict(rec)
                rec_amt = int(rec_dict.get("amount") or 0)
                cursor.execute("""
                    UPDATE customer_debt_records 
                    SET status = 'paid', paid_at = ?, settled_by = ?, settle_order_id = ?, updated_at = ?
                    WHERE id = ?
                """, (now, settled_by, order_id, now, record_id))

                # Ù…Ø­Ø§Ø³Ø¨Ù‡ Ø¯Ù‚ÛŒÙ‚ Ø¨Ø¯Ù‡ÛŒ Ø¬Ø¯ÛŒØ¯ Ø¨Ø± Ø§Ø³Ø§Ø³ ÙØ§Ú©ØªÙˆØ±Ù‡Ø§ÛŒ Ø¨Ø§Ø² Ø¨Ø§Ù‚ÛŒÙ…Ø§Ù†Ø¯Ù‡
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
                    VALUES (?, ?, ?, ?, 'settle', 'ØªØ³ÙˆÛŒÙ‡ Ø¨Ø¯Ù‡ÛŒ', ?, ?, ?, 'paid', ?, ?, ?, ?, ?, ?, ?)
                """, (
                    subscription_id, sub.get("account_name"), sub.get("telegram_id") or 0,
                    sub.get("reseller_id"), int(amount), current_debt, new_debt,
                    f"ØªØ³ÙˆÛŒÙ‡ Ù…Ø¨Ù„Øº {amount:,} ØªÙˆÙ…Ø§Ù† ØªÙˆØ³Ø· {settled_by}", settled_by, now, settled_by, order_id, now, now
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

    def clear_subscription_debt(self, sub_id: int, reseller_id: int = None, settled_by: str = "Ù…Ø¯ÛŒØ±ÛŒØª", order_id: str = None):
        """ØªØ³ÙˆÛŒÙ‡ Ú©Ø§Ù…Ù„ Ø¨Ø¯Ù‡ÛŒ Ù…Ø´ØªØ±ÛŒ Ùˆ Ø«Ø¨Øª ÙˆØ¶Ø¹ÛŒØª Ù¾Ø±Ø¯Ø§Ø®Øª Ø´Ø¯Ù‡ Ø¯Ø± Ø§Ø´ØªØ±Ø§Ú© Ùˆ Ø±Ø³ÛŒØ¯Ù‡Ø§"""
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

            # Ø¨Ø±ÙˆØ²Ø±Ø³Ø§Ù†ÛŒ ØªÙ…Ø§Ù…ÛŒ Ø±Ú©ÙˆØ±Ø¯Ù‡Ø§ÛŒ Ø¨Ø§Ø² Ø¯Ø± Ø¬Ø¯ÙˆÙ„ Ø±Ø³ÛŒØ¯Ù‡Ø§ÛŒ Ø¨Ø¯Ù‡ÛŒ
            cursor.execute("""
                UPDATE customer_debt_records 
                SET status = 'paid', paid_at = ?, settled_by = ?, settle_order_id = ?, updated_at = ?
                WHERE subscription_id = ? AND status = 'unpaid'
            """, (now, settled_by or "Ù…Ø¯ÛŒØ±ÛŒØª", order_id, now, sub_id))

            conn.commit()
            return {"success": True}
        except Exception as e:
            logger.error(f"Error clearing subscription debt: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def get_debtor_subscriptions(self, reseller_id: int = None, limit: int = 200) -> list:
        """Ù„ÛŒØ³Øª Ù…Ø´ØªØ±ÛŒØ§Ù† Ø¨Ø¯Ù‡Ú©Ø§Ø± Ø¨Ù‡ Ù‡Ù…Ø±Ø§Ù‡ ØªØ§Ø±ÛŒØ®ØŒ Ù…Ø¨Ù„Øº Ùˆ Ø´Ù…Ø§Ø±Ù‡ ØªÙ…Ø§Ø³"""
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
        """ØªØ¹Ø¯Ø§Ø¯ Ù…Ø´ØªØ±ÛŒØ§Ù† Ø¨Ø¯Ù‡Ú©Ø§Ø±"""
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
        """Ø«Ø¨Øª Ø¯Ø±Ø®ÙˆØ§Ø³Øª Ø±Ø³Ù…ÛŒ ØªØºÛŒÛŒØ± Ø­Ø¬Ù… Ùˆ Ù…Ø¯Øª Ø§Ø´ØªØ±Ø§Ú© Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ Ùˆ Ø§Ø±Ø³Ø§Ù„ ØªÛŒÚ©Øª Ø¨Ù‡ Ù…Ø¯ÛŒØ±ÛŒØª"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("SELECT * FROM subscriptions WHERE id=? AND reseller_id=?", (sub_id, reseller_id))
            sub = cursor.fetchone()
            if not sub:
                return {"success": False, "error": "Ø§Ø´ØªØ±Ø§Ú© Ù…ÙˆØ±Ø¯ Ù†Ø¸Ø± ÛŒØ§ÙØª Ù†Ø´Ø¯"}

            cursor.execute("SELECT * FROM resellers WHERE id=?", (reseller_id,))
            reseller = cursor.fetchone()
            r_name = reseller["name"] if reseller else f"Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ #{reseller_id}"
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

            subject = f"Ø¯Ø±Ø®ÙˆØ§Ø³Øª ØªØºÛŒÛŒØ± Ø­Ø¬Ù… Ùˆ Ù…Ø¯Øª Ø§Ø´ØªØ±Ø§Ú© Â«{acc_name}Â»"
            msg = (
                f"ðŸ”¹ Ø¯Ø±Ø®ÙˆØ§Ø³Øª ØªØºÛŒÛŒØ± Ù…Ø´Ø®ØµØ§Øª Ø³Ø±ÙˆÛŒØ³ ØªÙˆØ³Ø· Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ Â«{r_name}Â»:\n"
                f"ðŸ‘¤ Ù†Ø§Ù… Ø§Ú©Ø§Ù†Øª: {acc_name}\n"
                f"ðŸ“¦ Ø­Ø¬Ù… ÙØ¹Ù„ÛŒ: {cur_limit} Ú¯ÛŒÚ¯Ø§Ø¨Ø§ÛŒØª âž” ðŸŽ¯ Ø­Ø¬Ù… Ø¯Ø±Ø®ÙˆØ§Ø³ØªÛŒ: {requested_limit} Ú¯ÛŒÚ¯Ø§Ø¨Ø§ÛŒØª\n"
                f"â³ Ù…Ø¯Øª ÙØ¹Ù„ÛŒ: {cur_dur} Ø±ÙˆØ² âž” ðŸŽ¯ Ù…Ø¯Øª Ø¯Ø±Ø®ÙˆØ§Ø³ØªÛŒ: {requested_duration} Ø±ÙˆØ²\n"
            )
            if reason.strip():
                msg += f"ðŸ“ Ø¹Ù„Øª/ØªÙˆØ¶ÛŒØ­Ø§Øª: {reason.strip()}"

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

    def approve_quota_change_request(self, ticket_id: int, admin_name: str = "Ù…Ø¯ÛŒØ±ÛŒØª") -> dict:
        """ØªØ§ÛŒÛŒØ¯ Ø¯Ø±Ø®ÙˆØ§Ø³Øª ØªØºÛŒÛŒØ± Ø­Ø¬Ù…/Ù…Ø¯Øª ØªÙˆØ³Ø· Ù…Ø¯ÛŒØ± Ùˆ Ø¨Ø§Ø²Ú¯Ø±Ø¯Ø§Ù†Ø¯Ù† Ø§Ø·Ù„Ø§Ø¹Ø§Øª Ø¬Ù‡Øª Ø§Ø¹Ù…Ø§Ù„ Ø¯Ø± Ù‡ÛŒØ¯ÛŒÙØ§ÛŒ"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("SELECT * FROM support_tickets WHERE id=?", (ticket_id,))
            ticket = cursor.fetchone()
            if not ticket:
                return {"success": False, "error": "ØªÛŒÚ©Øª ÛŒØ§ÙØª Ù†Ø´Ø¯"}

            req_data = json.loads(ticket["request_data"]) if ticket["request_data"] else {}
            sub_id = req_data.get("sub_id")
            new_limit = req_data.get("requested_limit")
            new_dur = req_data.get("requested_duration")

            if not sub_id or new_limit is None or new_dur is None:
                return {"success": False, "error": "Ø¯Ø§Ø¯Ù‡â€ŒÙ‡Ø§ÛŒ Ø¯Ø±Ø®ÙˆØ§Ø³Øª Ù†Ø§Ù‚Øµ Ù‡Ø³ØªÙ†Ø¯"}

            # Û±. Ø¨Ø±ÙˆØ²Ø±Ø³Ø§Ù†ÛŒ Ø¯Ø± Ø¯ÛŒØªØ§Ø¨ÛŒØ³ Ù…Ø­Ù„ÛŒ
            cursor.execute("""
                UPDATE subscriptions
                SET data_limit = ?, duration = ?, updated_at = ?
                WHERE id = ?
            """, (float(new_limit), int(new_dur), now, sub_id))

            # Û². Ø¨Ø±ÙˆØ²Ø±Ø³Ø§Ù†ÛŒ ÙˆØ¶Ø¹ÛŒØª ØªÛŒÚ©Øª
            reply_text = f"âœ… Ø¯Ø±Ø®ÙˆØ§Ø³Øª ØªØºÛŒÛŒØ± Ø­Ø¬Ù… Ø¨Ù‡ {new_limit} Ú¯ÛŒÚ¯Ø§Ø¨Ø§ÛŒØª Ùˆ {new_dur} Ø±ÙˆØ² ØªÙˆØ³Ø· {admin_name} ØªØ§ÛŒÛŒØ¯ Ø´Ø¯ Ùˆ Ø±ÙˆÛŒ Ø³Ø±ÙˆÛŒØ³ Ø§Ø¹Ù…Ø§Ù„ Ú¯Ø±Ø¯ÛŒØ¯."
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

    def reject_quota_change_request(self, ticket_id: int, reason: str = "", admin_name: str = "Ù…Ø¯ÛŒØ±ÛŒØª") -> dict:
        """Ø±Ø¯ Ø¯Ø±Ø®ÙˆØ§Ø³Øª ØªØºÛŒÛŒØ± Ø­Ø¬Ù…/Ù…Ø¯Øª ØªÙˆØ³Ø· Ù…Ø¯ÛŒØ± Ø¨Ø§ Ø¯Ø±Ø¬ Ø¹Ù„Øª"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("SELECT * FROM support_tickets WHERE id=?", (ticket_id,))
            ticket = cursor.fetchone()
            if not ticket:
                return {"success": False, "error": "ØªÛŒÚ©Øª ÛŒØ§ÙØª Ù†Ø´Ø¯"}

            reply_text = f"âŒ Ø¯Ø±Ø®ÙˆØ§Ø³Øª ØªØºÛŒÛŒØ± Ù…Ø´Ø®ØµØ§Øª Ø§Ø´ØªØ±Ø§Ú© ØªÙˆØ³Ø· {admin_name} Ø±Ø¯ Ø´Ø¯."
            if reason.strip():
                reply_text += f"\nØ¹Ù„Øª Ø±Ø¯: {reason.strip()}"

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
        """Ú¯Ø²Ø§Ø±Ø´Ø§Øª Ùˆ ØªØ­Ù„ÛŒÙ„â€ŒÙ‡Ø§ÛŒ Ù¾ÛŒØ´Ø±ÙØªÙ‡ Ù‡ÙˆØ´ Ù…Ø§Ù„ÛŒ Ùˆ Ø¹Ù…Ù„Ú©Ø±Ø¯ÛŒ Ø¨Ø±Ø§ÛŒ Ù…Ø¯ÛŒØ± Ùˆ Ù†Ù…Ø§ÛŒÙ†Ø¯Ú¯Ø§Ù†"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        res = {}
        
        try:
            # Û±. Ù…Ø­Ø¨ÙˆØ¨â€ŒØªØ±ÛŒÙ† Ù¾Ù„Ù†â€ŒÙ‡Ø§ (Ù¾Ø±ÙØ±ÙˆØ´â€ŒØªØ±ÛŒÙ†)
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

            # Û². Ø¨Ø±ØªØ±ÛŒÙ† Ú©Ø§Ø±Ø¨Ø±Ø§Ù† Ù…Ø§Ù‡ Ø¬Ø§Ø±ÛŒ (Top users of the month)
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

            # Û³. Ø¨Ø±ØªØ±ÛŒÙ† Ú©Ø§Ø±Ø¨Ø±Ø§Ù† Ø³Ø§Ù„ Ø¬Ø§Ø±ÛŒ (Top users of the year)
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

            # Û´. ÙØ¹Ø§Ù„â€ŒØªØ±ÛŒÙ† Ú©Ø§Ø±Ø¨Ø±Ø§Ù† Ø§Ø² Ù†Ø¸Ø± Ù…ØµØ±Ù Ú¯ÛŒÚ¯Ø§Ø¨Ø§ÛŒØª (Most active users)
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

            # Ûµ. Ú¯Ø²Ø§Ø±Ø´ Ù…ØµØ±Ù Ø¯ÙˆØ±Ù‡â€ŒÙ‡Ø§ÛŒ Ú¯Ø°Ø´ØªÙ‡ (Previous periods usage history)
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

            # Û¶. Ø¢Ø®Ø±ÛŒÙ† ØªÙ…Ø¯ÛŒØ¯Ù‡Ø§ Ùˆ Ø®Ø±ÛŒØ¯Ù‡Ø§ Ø¨Ù‡ Ù‡Ù…Ø±Ø§Ù‡ ØªØ§Ø±ÛŒØ® Ø¹Ø¶ÙˆÛŒØª Ùˆ Ø¢Ø®Ø±ÛŒÙ† Ø¨Ø±ÙˆØ²Ø±Ø³Ø§Ù†ÛŒ (ØªØ§ÛŒÙ…â€ŒÙ„Ø§ÛŒÙ† Ø±ÙˆÛŒØ¯Ø§Ø¯Ù‡Ø§ÛŒ Ø²Ù†Ø¯Ù‡ Û³Û° ØªØ§ÛŒÛŒ)
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

    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    # Ù…Ù‡Ø§Ø¬Ø±Øª Ø§Ø² JSON Ø¨Ù‡ Ø¯ÛŒØªØ§Ø¨ÛŒØ³
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

    def migrate_from_json(self):
        """Ù…Ù‡Ø§Ø¬Ø±Øª Ø§Ø·Ù„Ø§Ø¹Ø§Øª Ø§Ø² ÙØ§ÛŒÙ„â€ŒÙ‡Ø§ÛŒ JSON Ø¨Ù‡ Ø¯ÛŒØªØ§Ø¨ÛŒØ³"""
        data_dir = Path("data")
        migrated = 0

        # Ù…Ù‡Ø§Ø¬Ø±Øª Ú©Ø§Ø±Ø¨Ø±Ø§Ù†
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

        # Ù…Ù‡Ø§Ø¬Ø±Øª ØªØ±Ø§Ú©Ù†Ø´â€ŒÙ‡Ø§
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

    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    # Ù…Ù‡Ø§Ø¬Ø±Øª Ø®ÙˆØ¯Ú©Ø§Ø± Ø¯Ø± Ø´Ø±ÙˆØ¹
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

    def auto_migrate_on_startup(self):
        """Ù…Ù‡Ø§Ø¬Ø±Øª Ø®ÙˆØ¯Ú©Ø§Ø± Ø§Ú¯Ø± Ø¯ÛŒØªØ§Ø¨ÛŒØ³ Ø®Ø§Ù„ÛŒ Ø¨Ø§Ø´Ø¯ Ùˆ ÙØ§ÛŒÙ„â€ŒÙ‡Ø§ÛŒ JSON ÙˆØ¬ÙˆØ¯ Ø¯Ø§Ø´ØªÙ‡ Ø¨Ø§Ø´Ø¯"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            # Ø¨Ø±Ø±Ø³ÛŒ Ø¢ÛŒØ§ Ø¯ÛŒØªØ§Ø¨ÛŒØ³ Ø®Ø§Ù„ÛŒ Ø§Ø³Øª
            cursor.execute("SELECT COUNT(*) as count FROM users")
            user_count = cursor.fetchone()["count"]

            if user_count > 0:
                logger.info(f"Database has {user_count} users, skipping auto-migration")
                return {"success": True, "skipped": True, "reason": "database_not_empty"}

            # Ø¨Ø±Ø±Ø³ÛŒ ÙˆØ¬ÙˆØ¯ ÙØ§ÛŒÙ„â€ŒÙ‡Ø§ÛŒ JSON
            data_dir = Path("data")
            json_files = list(data_dir.glob("*.json"))
            if not json_files:
                logger.info("No JSON files found, skipping auto-migration")
                return {"success": True, "skipped": True, "reason": "no_json_files"}

            # Ø§Ø¬Ø±Ø§ÛŒ Ù…Ù‡Ø§Ø¬Ø±Øª
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
        """Ø§Ø¶Ø§ÙÙ‡ Ú©Ø±Ø¯Ù† Ø³ØªÙˆÙ†â€ŒÙ‡Ø§ÛŒ Ø¬Ø¯ÛŒØ¯ Ø¨Ù‡ Ø¬Ø¯Ø§ÙˆÙ„ Ù‚Ø¯ÛŒÙ…ÛŒ"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            # Ø¨Ø±Ø±Ø³ÛŒ ÙˆØ¬ÙˆØ¯ Ø³ØªÙˆÙ†â€ŒÙ‡Ø§ Ø¯Ø± subscriptions
            cursor.execute("PRAGMA table_info(subscriptions)")
            columns = [row[1] for row in cursor.fetchall()]
            if "account_name" not in columns:
                cursor.execute("ALTER TABLE subscriptions ADD COLUMN account_name TEXT")
                logger.info("Added account_name column to subscriptions")
            if "account_comment" not in columns:
                cursor.execute("ALTER TABLE subscriptions ADD COLUMN account_comment TEXT")
                logger.info("Added account_comment column to subscriptions")

            # Ø¨Ø±Ø±Ø³ÛŒ ÙˆØ¬ÙˆØ¯ Ø³ØªÙˆÙ† language Ø¯Ø± users
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
        """Ø¯Ø±ÛŒØ§ÙØª Ø²Ø¨Ø§Ù† Ø§Ù†ØªØ®Ø§Ø¨ÛŒ Ú©Ø§Ø±Ø¨Ø±"""
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
        """ØªÙ†Ø¸ÛŒÙ… Ùˆ Ø°Ø®ÛŒØ±Ù‡ Ø²Ø¨Ø§Ù† Ø§Ù†ØªØ®Ø§Ø¨ÛŒ Ú©Ø§Ø±Ø¨Ø±"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            now = get_now_iso()
            # Ù…Ø·Ù…Ø¦Ù† Ø´ÙˆÛŒÙ… Ú©Ø§Ø±Ø¨Ø± Ø¯Ø± Ø¬Ø¯ÙˆÙ„ ÙˆØ¬ÙˆØ¯ Ø¯Ø§Ø±Ø¯
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

    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    # Ø®Ø±ÙˆØ¬ÛŒ Ú¯Ø±ÙØªÙ† Ø§Ø² Ø¯ÛŒØªØ§Ø¨ÛŒØ³
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

    def export_to_json(self, export_dir=None):
        """Ø®Ø±ÙˆØ¬ÛŒ Ú¯Ø±ÙØªÙ† Ø§Ø² Ø¯ÛŒØªØ§Ø¨ÛŒØ³ Ø¨Ù‡ ÙØ§ÛŒÙ„â€ŒÙ‡Ø§ÛŒ JSON"""
        if export_dir is None:
            export_dir = Path("data/export")
        else:
            export_dir = Path(export_dir)
        export_dir.mkdir(parents=True, exist_ok=True)

        try:
            # Ø®Ø±ÙˆØ¬ÛŒ Ú©Ø§Ø±Ø¨Ø±Ø§Ù†
            users = self.get_all_users()
            for user in users:
                user_file = export_dir / f"user_{user['telegram_id']}.json"
                with open(user_file, "w", encoding="utf-8") as f:
                    json.dump(user, f, ensure_ascii=False, indent=2)

            # Ø®Ø±ÙˆØ¬ÛŒ ØªØ±Ø§Ú©Ù†Ø´â€ŒÙ‡Ø§
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM transactions")
            transactions = {row["order_id"]: dict(row) for row in cursor.fetchall()}
            conn.close()

            trans_file = export_dir / "transactions.json"
            with open(trans_file, "w", encoding="utf-8") as f:
                json.dump(transactions, f, ensure_ascii=False, indent=2)

            # Ø®Ø±ÙˆØ¬ÛŒ Ø§Ø´ØªØ±Ø§Ú©â€ŒÙ‡Ø§
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM subscriptions")
            subscriptions = [dict(row) for row in cursor.fetchall()]
            conn.close()

            subs_file = export_dir / "subscriptions.json"
            with open(subs_file, "w", encoding="utf-8") as f:
                json.dump(subscriptions, f, ensure_ascii=False, indent=2)

            # Ø®Ø±ÙˆØ¬ÛŒ ØªÙ†Ø¸ÛŒÙ…Ø§Øª
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

    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    # ÙˆØ±ÙˆØ¯ÛŒ Ú¯Ø±ÙØªÙ† Ø¨Ù‡ Ø¯ÛŒØªØ§Ø¨ÛŒØ³
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

    def import_from_json(self, import_dir=None):
        """ÙˆØ±ÙˆØ¯ÛŒ Ú¯Ø±ÙØªÙ† Ø§Ø² ÙØ§ÛŒÙ„â€ŒÙ‡Ø§ÛŒ JSON Ø¨Ù‡ Ø¯ÛŒØªØ§Ø¨ÛŒØ³"""
        if import_dir is None:
            import_dir = Path("data/export")
        else:
            import_dir = Path(import_dir)

        if not import_dir.exists():
            return {"success": False, "error": "Import directory not found"}

        imported = 0

        try:
            # ÙˆØ±ÙˆØ¯ÛŒ Ú©Ø§Ø±Ø¨Ø±Ø§Ù†
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

            # ÙˆØ±ÙˆØ¯ÛŒ ØªØ±Ø§Ú©Ù†Ø´â€ŒÙ‡Ø§
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

            # ÙˆØ±ÙˆØ¯ÛŒ Ø§Ø´ØªØ±Ø§Ú©â€ŒÙ‡Ø§
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

    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    # Ù…ØªØ¯Ù‡Ø§ÛŒ Ù…Ø¯ÛŒØ±ÛŒØª Ù†Ù…Ø§ÛŒÙ†Ø¯Ú¯Ø§Ù† Ùˆ Ù‡Ù…Ú©Ø§Ø±Ø§Ù† ÙØ±ÙˆØ´ (Reseller System)
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

    @staticmethod
    def hash_password(password: str) -> str:
        import hashlib
        return hashlib.sha256(password.encode("utf-8")).hexdigest()

    def create_reseller(self, username: str, password: str, name: str,
                        telegram_id: int = None, discount_percent: int = 20, initial_balance: int = 0,
                        hiddify_admin_uuid: str = None, parent_reseller_id: int = None,
                        affiliate_commission_percent: float = None, referral_code: str = None,
                        credit_enabled: int = 0, credit_limit: int = 0, can_gift_traffic: int = 0,
                        is_partner: int = 0) -> dict:
        """ایجاد نماینده جدید با پشتیبانی از سیستم همکاری درفروش، سقف اعتبار و قابلیت کادو ترافیک"""
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
                    credit_enabled, credit_limit, can_gift_traffic,
                    created_at, updated_at, is_partner
                ) VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                cleaned_user, password_hash, name.strip(), telegram_id, initial_balance, 
                discount_percent, hiddify_admin_uuid, 
                parent_reseller_id, affiliate_commission_percent, referral_code,
                credit_enabled, credit_limit, can_gift_traffic,
                now, now, is_partner
            ))
            reseller_id = cursor.lastrowid
            
            # ØªØ¶Ù…ÛŒÙ† ØªÙˆÙ„ÛŒØ¯ Ú©Ø¯ Ø±Ù Ø±Ø§Ù„ ÛŒÚ©ØªØ§ Ùˆ ØªÙ…ÛŒØ²
            final_ref_code = f"REF-{reseller_id}"
            cursor.execute("UPDATE resellers SET referral_code = ? WHERE id = ?", (final_ref_code, reseller_id))

            if initial_balance > 0:
                cursor.execute("""
                    INSERT INTO reseller_transactions (reseller_id, type, amount, description, created_at)
                    VALUES (?, 'deposit', ?, 'Ø´Ø§Ø±Ú˜ Ø§ÙˆÙ„ÛŒÙ‡ Ø­Ø³Ø§Ø¨', ?)
                """, (reseller_id, initial_balance, now))

            conn.commit()
            return {"success": True, "reseller_id": reseller_id, "referral_code": final_ref_code}
        except sqlite3.IntegrityError:
            return {"success": False, "error": "Ø§ÛŒÙ† Ù†Ø§Ù… Ú©Ø§Ø±Ø¨Ø±ÛŒ Ù‚Ø¨Ù„Ø§Ù‹ Ø«Ø¨Øª Ø´Ø¯Ù‡ Ø§Ø³Øª."}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    # Ø³ÛŒØ³ØªÙ… Ø²ÛŒØ±Ù…Ø¬Ù…ÙˆØ¹Ù‡â€ŒÚ¯ÛŒØ±ÛŒ Ùˆ Ù¾ÙˆØ±Ø³Ø§Ù†Øª Ù†Ù…Ø§ÛŒÙ†Ø¯Ú¯Ø§Ù† (Reseller Affiliate System)
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

    def get_reseller_affiliate_settings(self) -> dict:
        """Ø¯Ø±ÛŒØ§ÙØª ØªÙ†Ø¸ÛŒÙ…Ø§Øª Ø³Ø±Ø§Ø³Ø±ÛŒ Ø³ÛŒØ³ØªÙ… Ø²ÛŒØ±Ù…Ø¬Ù…ÙˆØ¹Ù‡â€ŒÚ¯ÛŒØ±ÛŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ú¯Ø§Ù†"""
        conn = self.get_connection()
        cursor = conn.cursor()
        settings = {
            "enabled": True,
            "default_percent": 10.0,
            "calc_base": "plan_price",
            "terms": "Ø¨Ø§ Ù¾ÛŒÙˆØ³ØªÙ† Ø¨Ù‡ Ø¹Ù†ÙˆØ§Ù† Ù‡Ù…Ú©Ø§Ø± Ùˆ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ Ø²ÛŒØ±Ù…Ø¬Ù…ÙˆØ¹Ù‡ØŒ Ø§Ø² Ø±Ø¨Ø§Øª Ø§Ø®ØªØµØ§ØµÛŒ Ù‡ÙˆØ´Ù…Ù†Ø¯ØŒ Ø³Ø§Ø¨â€ŒØ¯Ø§Ù…Ù†Ù‡â€ŒÙ‡Ø§ÛŒ Ø¨Ø¯ÙˆÙ† ÙÛŒÙ„ØªØ± Ùˆ Ù¾Ù†Ù„ Ù…Ø¯ÛŒØ±ÛŒØª ÙØ±ÙˆØ´ Ø¨Ø§ ØªØ³ÙˆÛŒÙ‡ Ø¢Ù†ÛŒ Ø¨Ù‡Ø±Ù‡â€ŒÙ…Ù†Ø¯ Ø´ÙˆÛŒØ¯."
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
        """Ø¨Ø±ÙˆØ²Ø±Ø³Ø§Ù†ÛŒ ØªÙ†Ø¸ÛŒÙ…Ø§Øª Ø³ÛŒØ³ØªÙ… Ø²ÛŒØ±Ù…Ø¬Ù…ÙˆØ¹Ù‡â€ŒÚ¯ÛŒØ±ÛŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ú¯Ø§Ù†"""
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
        """Ø¯Ø±ÛŒØ§ÙØª ÛŒØ§ ØªÙˆÙ„ÛŒØ¯ Ú©Ø¯ Ø¯Ø¹ÙˆØª Ø§Ø®ØªØµØ§ØµÛŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡"""
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
        """Ù¾ÛŒØ¯Ø§ Ú©Ø±Ø¯Ù† Ù…Ø´Ø®ØµØ§Øª Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ Ù…Ø¹Ø±Ù Ø¨Ø± Ø§Ø³Ø§Ø³ Ú©Ø¯ ÛŒØ§ Ø´Ù†Ø§Ø³Ù‡"""
        if not code_or_id:
            return None
        code_clean = str(code_or_id).strip()
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            # Û±. Ø¬Ø³ØªØ¬Ùˆ Ø¨Ø§ referral_code
            cursor.execute("SELECT * FROM resellers WHERE UPPER(referral_code) = UPPER(?) AND status = 'active'", (code_clean,))
            row = cursor.fetchone()
            if row:
                return dict(row)

            # Û². Ø¨Ø±Ø±Ø³ÛŒ Ø§Ú¯Ø± ÙØ±Ù…Øª Ø´Ù†Ø§Ø³Ù‡ Ø¹Ø¯Ø¯ÛŒ Ø¨Ø§Ø´Ø¯ (Ù…Ø«Ù„Ø§Ù‹ 5 ÛŒØ§ REF-5)
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

            # Û³. Ø¬Ø³ØªØ¬Ùˆ Ø¨Ø± Ø§Ø³Ø§Ø³ Ù†Ø§Ù… Ú©Ø§Ø±Ø¨Ø±ÛŒ
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
        """Ù„ÛŒØ³Øª Ù†Ù…Ø§ÛŒÙ†Ø¯Ú¯Ø§Ù† Ø²ÛŒØ±Ù…Ø¬Ù…ÙˆØ¹Ù‡ ÛŒÚ© Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ Ø¨Ù‡ Ù‡Ù…Ø±Ø§Ù‡ Ø¢Ù…Ø§Ø± ÙØ±ÙˆØ´ Ùˆ Ø³ÙˆØ¯ ØªÙˆÙ„ÛŒØ¯ Ø´Ø¯Ù‡"""
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
        """Ø´Ø§Ø®Øµâ€ŒÙ‡Ø§ Ùˆ Ø¢Ù…Ø§Ø± Ú©Ø§Ù…Ù„ Ø²ÛŒØ±Ù…Ø¬Ù…ÙˆØ¹Ù‡â€ŒÚ¯ÛŒØ±ÛŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡"""
        reseller = self.get_reseller(reseller_id)
        if not reseller:
            return {}

        aff_settings = self.get_reseller_affiliate_settings()
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            ref_code = self.get_reseller_referral_code(reseller_id)

            # ØªØ¹Ø¯Ø§Ø¯ Ú©Ù„ Ø²ÛŒØ±Ù…Ø¬Ù…ÙˆØ¹Ù‡â€ŒÙ‡Ø§
            cursor.execute("SELECT COUNT(*) FROM resellers WHERE parent_reseller_id = ?", (reseller_id,))
            sub_count = cursor.fetchone()[0] or 0

            # ØªØ¹Ø¯Ø§Ø¯ Ø²ÛŒØ±Ù…Ø¬Ù…ÙˆØ¹Ù‡â€ŒÙ‡Ø§ÛŒ ÙØ¹Ø§Ù„
            cursor.execute("SELECT COUNT(*) FROM resellers WHERE parent_reseller_id = ? AND status = 'active'", (reseller_id,))
            active_sub_count = cursor.fetchone()[0] or 0

            # Ù…Ø¬Ù…ÙˆØ¹ Ú©Ù„ Ú©Ù…ÛŒØ³ÛŒÙˆÙ† Ø¯Ø±ÛŒØ§ÙØªÛŒ
            cursor.execute("SELECT COALESCE(SUM(commission_amount), 0) FROM reseller_affiliate_commissions WHERE parent_reseller_id = ?", (reseller_id,))
            total_commission = cursor.fetchone()[0] or 0

            # Ú©Ù…ÛŒØ³ÛŒÙˆÙ† Û³Û° Ø±ÙˆØ² Ø§Ø®ÛŒØ±
            month_ago = (datetime.now() - timedelta(days=30)).isoformat()
            cursor.execute("SELECT COALESCE(SUM(commission_amount), 0) FROM reseller_affiliate_commissions WHERE parent_reseller_id = ? AND created_at >= ?", (reseller_id, month_ago))
            recent_commission = cursor.fetchone()[0] or 0

            # Ø¯Ø±ØµØ¯ Ú©Ù…ÛŒØ³ÛŒÙˆÙ† Ù…ÙˆØ«Ø± Ø¨Ø±Ø§ÛŒ Ø§ÛŒÙ† Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡
            effective_percent = reseller.get("affiliate_commission_percent")
            if effective_percent is None or effective_percent <= 0:
                effective_percent = aff_settings.get("default_percent", 10.0)

            # Ù…Ø´Ø®ØµØ§Øª Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ Ø¨Ø§Ù„Ø§Ø¯Ø³ØªÛŒ (Ø§Ú¯Ø± ÙˆØ¬ÙˆØ¯ Ø¯Ø§Ø±Ø¯)
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
        """Ø¯Ø±ÛŒØ§ÙØª Ø±ÛŒØ² ØªØ±Ø§Ú©Ù†Ø´â€ŒÙ‡Ø§ÛŒ Ù¾ÙˆØ±Ø³Ø§Ù†Øª Ø²ÛŒØ±Ù…Ø¬Ù…ÙˆØ¹Ù‡â€ŒÚ¯ÛŒØ±ÛŒ"""
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
        Ù…Ø­Ø§Ø³Ø¨Ù‡ Ùˆ ÙˆØ§Ø±ÛŒØ² Ø®ÙˆØ¯Ú©Ø§Ø± Ø¯Ø±ØµØ¯ Ù¾ÙˆØ±Ø³Ø§Ù†Øª Ø¨Ù‡ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ Ø¨Ø§Ù„Ø§Ø¯Ø³ØªÛŒ Ø¨Ù‡ Ø§Ø²Ø§ÛŒ Ù‡Ø± Ø®Ø±ÛŒØ¯ ÛŒØ§ Ø³Ø§Ø®Øª Ø§Ú©Ø§Ù†Øª ØªÙˆØ³Ø· Ø²ÛŒØ±Ù…Ø¬Ù…ÙˆØ¹Ù‡
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

        # Ø¯Ø±ØµØ¯ Ú©Ù…ÛŒØ³ÛŒÙˆÙ† (Ø§Ø®ØªØµØ§ØµÛŒ Ø¨Ø§Ù„Ø§Ø¯Ø³ØªÛŒ ÛŒØ§ Ù¾ÛŒØ´â€ŒÙØ±Ø¶ Ø³ÛŒØ³ØªÙ…)
        commission_percent = parent_reseller.get("affiliate_commission_percent")
        if commission_percent is None or commission_percent <= 0:
            commission_percent = float(aff_settings.get("default_percent", 10.0))

        commission_amount = int((plan_price * commission_percent) / 100)
        if commission_amount <= 0:
            return {"success": False, "reason": "zero_commission"}

        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        sub_name = sub_reseller.get("name") or f"Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ #{sub_reseller_id}"
        desc = f"Ù¾ÙˆØ±Ø³Ø§Ù†Øª {commission_percent:g}Ùª Ø§Ø² Ø³Ø§Ø®Øª Ø§Ø´ØªØ±Ø§Ú© Â«{account_name}Â» ({plan_name}) ØªÙˆØ³Ø· Ø²ÛŒØ±Ù…Ø¬Ù…ÙˆØ¹Ù‡ Â«{sub_name}Â»"

        try:
            # Û±. Ø§ÙØ²Ø§ÛŒØ´ Ù…ÙˆØ¬ÙˆØ¯ÛŒ Ú©ÛŒÙ Ù¾ÙˆÙ„ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ Ø¨Ø§Ù„Ø§Ø¯Ø³ØªÛŒ
            cursor.execute("UPDATE resellers SET balance = balance + ?, updated_at = ? WHERE id = ?", (commission_amount, now, parent_id))

            # Û². Ø«Ø¨Øª ØªØ±Ø§Ú©Ù†Ø´ Ø¯Ø± reseller_transactions
            cursor.execute("""
                INSERT INTO reseller_transactions (reseller_id, type, amount, plan_name, account_name, description, created_at)
                VALUES (?, 'deposit', ?, ?, ?, ?, ?)
            """, (parent_id, commission_amount, plan_name, account_name, desc, now))

            # Û³. Ø«Ø¨Øª Ø±Ú©ÙˆØ±Ø¯ Ø¯Ø± Ø¬Ø¯ÙˆÙ„ ØªØ®ØµØµÛŒ Ù¾ÙˆØ±Ø³Ø§Ù†Øªâ€ŒÙ‡Ø§ÛŒ Ø²ÛŒØ±Ù…Ø¬Ù…ÙˆØ¹Ù‡â€ŒÚ¯ÛŒØ±ÛŒ
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

            # Û´. Ø§Ø±Ø³Ø§Ù„ Ø§Ø¹Ù„Ø§Ù† Ø¨Ù„Ø§Ø¯Ø±Ù†Ú¯ Ø¨Ù‡ Ù¾Ù†Ù„ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ Ø¨Ø§Ù„Ø§Ø¯Ø³ØªÛŒ
            self.add_reseller_notification(
                reseller_id=parent_id,
                title="ðŸ’° ÙˆØ§Ø±ÛŒØ² Ù¾ÙˆØ±Ø³Ø§Ù†Øª Ø²ÛŒØ±Ù…Ø¬Ù…ÙˆØ¹Ù‡",
                message=f"Ù…Ø¨Ù„Øº {commission_amount:,} ØªÙˆÙ…Ø§Ù† Ø¨Ø§Ø¨Øª ÙØ±ÙˆØ´ Ø§Ø´ØªØ±Ø§Ú© Â«{account_name}Â» ØªÙˆØ³Ø· Ø²ÛŒØ±Ù…Ø¬Ù…ÙˆØ¹Ù‡ Ø´Ù…Ø§ ({sub_name}) Ø¨Ù‡ Ú©ÛŒÙ Ù¾ÙˆÙ„ Ø´Ù…Ø§ ÙˆØ§Ø±ÛŒØ² Ø´Ø¯.",
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
        """Ø«Ø¨Øª ÙØ±Ù… Ø¯Ø±Ø®ÙˆØ§Ø³Øª Ø§Ø®Ø° Ù†Ù…Ø§ÛŒÙ†Ø¯Ú¯ÛŒ Ø¨Ø§ Ù„ÛŒÙ†Ú© Ù…Ø¹Ø±Ù Ùˆ Ø§ÛŒØ¬Ø§Ø¯ ØªÛŒÚ©Øª Ø±Ø³Ù…ÛŒ Ø¨Ø±Ø§ÛŒ Ù…Ø¯ÛŒØ±ÛŒØª"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()

        referrer_name = "Ù…Ø³ØªÙ‚ÛŒÙ… (Ø¨Ø¯ÙˆÙ† Ù…Ø¹Ø±Ù)"
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

        subject = f"ðŸ’¼ Ø¯Ø±Ø®ÙˆØ§Ø³Øª Ø§Ø®Ø° Ù¾Ù†Ù„ Ù†Ù…Ø§ÛŒÙ†Ø¯Ú¯ÛŒ ØªÙˆØ³Ø· Â«{full_name.strip()}Â» (Ù…Ø¹Ø±Ù: {referrer_name})"
        msg = (
            f"ðŸŒŸ Ø¯Ø±Ø®ÙˆØ§Ø³Øª Ø¬Ø¯ÛŒØ¯ Ø¨Ø±Ø§ÛŒ Ø§Ø®Ø° Ù¾Ù†Ù„ Ù†Ù…Ø§ÛŒÙ†Ø¯Ú¯ÛŒ Ø«Ø¨Øª Ú¯Ø±Ø¯ÛŒØ¯:\n"
            f"ðŸ‘¤ Ù…ØªÙ‚Ø§Ø¶ÛŒ: {full_name.strip()}\n"
            f"ðŸ“± Ø´Ù…Ø§Ø±Ù‡ ØªÙ…Ø§Ø³: {phone_number.strip()}\n"
            f"ðŸ†” ØªÙ„Ú¯Ø±Ø§Ù…: {telegram_id or 'Ø«Ø¨Øª Ù†Ø´Ø¯Ù‡'}\n"
            f"ðŸ‘¤ Ù†Ø§Ù… Ú©Ø§Ø±Ø¨Ø±ÛŒ Ø¯Ø±Ø®ÙˆØ§Ø³ØªÛŒ: {requested_username.strip().lower()}\n"
            f"ðŸ¤ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ Ù…Ø¹Ø±Ù: {referrer_name}\n"
        )
        if notes.strip():
            msg += f"ðŸ“ ØªÙˆØ¶ÛŒØ­Ø§Øª/Ø³ÙˆØ§Ø¨Ù‚: {notes.strip()}\n"

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
        """ØªØ§ÛŒÛŒØ¯ Ø¯Ø±Ø®ÙˆØ§Ø³Øª Ù†Ù…Ø§ÛŒÙ†Ø¯Ú¯ÛŒ ØªÙˆØ³Ø· Ù…Ø¯ÛŒØ±ÛŒØª Ùˆ Ø§ÛŒØ¬Ø§Ø¯ Ø¢Ù†ÛŒ Ø­Ø³Ø§Ø¨ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ Ø¨Ø§ Ø§Ù†ØªØ³Ø§Ø¨ Ù…Ø¹Ø±Ù"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("SELECT * FROM support_tickets WHERE id=? AND ticket_type='reseller_application'", (ticket_id,))
            ticket = cursor.fetchone()
            if not ticket:
                return {"success": False, "error": "Ø¯Ø±Ø®ÙˆØ§Ø³Øª Ù†Ù…Ø§ÛŒÙ†Ø¯Ú¯ÛŒ ÛŒØ§ÙØª Ù†Ø´Ø¯."}

            if ticket["request_status"] == "approved":
                return {"success": False, "error": "Ø§ÛŒÙ† Ø¯Ø±Ø®ÙˆØ§Ø³Øª Ù‚Ø¨Ù„Ø§Ù‹ ØªØ§ÛŒÛŒØ¯ Ø´Ø¯Ù‡ Ø§Ø³Øª."}

            req_data = json.loads(ticket["request_data"] or "{}")
            username = req_data.get("requested_username")
            full_name = req_data.get("full_name") or f"Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ {username}"
            telegram_id = req_data.get("telegram_id")
            referrer_id = req_data.get("referrer_id")

            if not password:
                import random
                password = f"Pass@{random.randint(1000, 9999)}"

            # Ø§ÛŒØ¬Ø§Ø¯ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ Ø¨Ø§ Ø§ØªØµØ§Ù„ Ø¨Ù‡ parent_reseller_id
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

            # Ø¨Ù‡â€ŒØ±ÙˆØ²Ø±Ø³Ø§Ù†ÛŒ ÙˆØ¶Ø¹ÛŒØª ØªÛŒÚ©Øª
            cursor.execute("""
                UPDATE support_tickets 
                SET request_status = 'approved', status = 'closed', updated_at = ?
                WHERE id = ?
            """, (now, ticket_id))

            reply_msg = f"âœ… Ø¯Ø±Ø®ÙˆØ§Ø³Øª Ù†Ù…Ø§ÛŒÙ†Ø¯Ú¯ÛŒ Ø´Ù…Ø§ Ø¨Ø§ Ù…ÙˆÙÙ‚ÛŒØª ØªØ§ÛŒÛŒØ¯ Ùˆ Ù¾Ù†Ù„ Ø´Ù…Ø§ Ø§ÛŒØ¬Ø§Ø¯ Ø´Ø¯.\nðŸ‘¤ Ù†Ø§Ù… Ú©Ø§Ø±Ø¨Ø±ÛŒ: {username}\nðŸ”‘ Ø±Ù…Ø² Ø¹Ø¨ÙˆØ±: {password}"
            cursor.execute("""
                INSERT INTO ticket_messages (ticket_id, sender_type, sender_name, message, created_at)
                VALUES (?, 'support', 'Ù…Ø¯ÛŒØ±ÛŒØª Ø³Ø§Ù…Ø§Ù†Ù‡', ?, ?)
            """, (ticket_id, reply_msg, now))

            conn.commit()

            # Ø§Ø·Ù„Ø§Ø¹â€ŒØ±Ø³Ø§Ù†ÛŒ Ø¨Ù‡ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ Ù…Ø¹Ø±Ù Ø¯Ø± ØµÙˆØ±Øª ÙˆØ¬ÙˆØ¯
            if referrer_id:
                self.add_reseller_notification(
                    reseller_id=referrer_id,
                    title="ðŸŽ‰ Ø¹Ø¶ÙˆÛŒØª Ø²ÛŒØ±Ù…Ø¬Ù…ÙˆØ¹Ù‡ Ø¬Ø¯ÛŒØ¯",
                    message=f"Ø¯Ø±Ø®ÙˆØ§Ø³Øª Ù†Ù…Ø§ÛŒÙ†Ø¯Ú¯ÛŒ Â«{full_name}Â» ØªØ§ÛŒÛŒØ¯ Ùˆ Ø¨Ù‡ Ø¹Ù†ÙˆØ§Ù† Ø²ÛŒØ±Ù…Ø¬Ù…ÙˆØ¹Ù‡ Ø±Ø³Ù…ÛŒ Ø´Ù…Ø§ ÙØ¹Ø§Ù„ Ø´Ø¯.",
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
        """Ø±Ø¯ Ø¯Ø±Ø®ÙˆØ§Ø³Øª Ø§Ø®Ø° Ù†Ù…Ø§ÛŒÙ†Ø¯Ú¯ÛŒ"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("UPDATE support_tickets SET request_status = 'rejected', status = 'closed', updated_at = ? WHERE id = ? AND ticket_type = 'reseller_application'", (now, ticket_id))
            reject_msg = "âŒ Ù…ØªØ£Ø³ÙØ§Ù†Ù‡ Ø¨Ø§ Ø¯Ø±Ø®ÙˆØ§Ø³Øª Ø§Ø®Ø° Ù¾Ù†Ù„ Ù†Ù…Ø§ÛŒÙ†Ø¯Ú¯ÛŒ Ø´Ù…Ø§ Ù…ÙˆØ§ÙÙ‚Øª Ù†Ú¯Ø±Ø¯ÛŒØ¯."
            if reason.strip():
                reject_msg += f"\nØ¹Ù„Øª: {reason.strip()}"
            cursor.execute("""
                INSERT INTO ticket_messages (ticket_id, sender_type, sender_name, message, created_at)
                VALUES (?, 'support', 'Ù…Ø¯ÛŒØ±ÛŒØª Ø³Ø§Ù…Ø§Ù†Ù‡', ?, ?)
            """, (ticket_id, reject_msg, now))
            conn.commit()
            return {"success": True}
        except Exception as e:
            logger.error(f"Error rejecting reseller application: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def update_reseller_parent(self, reseller_id: int, parent_reseller_id: Optional[int]) -> dict:
        """ØªØºÛŒÛŒØ± ÛŒØ§ Ø­Ø°Ù Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ Ø¨Ø§Ù„Ø§Ø¯Ø³ØªÛŒ ÛŒÚ© Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡"""
        if parent_reseller_id == reseller_id:
            return {"success": False, "error": "ÛŒÚ© Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ Ù†Ù…ÛŒâ€ŒØªÙˆØ§Ù†Ø¯ Ù…Ø¹Ø±Ù Ø®ÙˆØ¯Ø´ Ø¨Ø§Ø´Ø¯."}
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
        """ØªØ®ØµÛŒØµ Ø¯Ø±ØµØ¯ Ù¾ÙˆØ±Ø³Ø§Ù†Øª Ø§Ø®ØªØµØ§ØµÛŒ Ø¨Ø±Ø§ÛŒ ÛŒÚ© Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡"""
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
        """Ú¯Ø²Ø§Ø±Ø´ Ø¢Ù…Ø§Ø±ÛŒ Ø¬Ø§Ù…Ø¹ Ø³ÛŒØ³ØªÙ… Ø²ÛŒØ±Ù…Ø¬Ù…ÙˆØ¹Ù‡â€ŒÚ¯ÛŒØ±ÛŒ Ø¨Ø±Ø§ÛŒ Ù¾Ù†Ù„ Ù…Ø¯ÛŒØ±ÛŒØª"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            # Û±. Ù„ÛŒØ³Øª ØªÙ…Ø§Ù… Ù†Ù…Ø§ÛŒÙ†Ø¯Ú¯Ø§Ù† Ø¨Ø§ Ø§Ø·Ù„Ø§Ø¹Ø§Øª Ù…Ø¹Ø±Ù Ùˆ Ø²ÛŒØ±Ù…Ø¬Ù…ÙˆØ¹Ù‡â€ŒÙ‡Ø§
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

            # Û². Ø¢Ù…Ø§Ø± Ú©Ù„ÛŒ Ø³Ø§Ù…Ø§Ù†Ù‡
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
        Ø¯Ø±ÛŒØ§ÙØª Ú©Ù„ÛŒØ¯ API ÛŒØ§ Admin UUID Ø§Ø®ØªØµØ§ØµÛŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ Ø¯Ø± Ù‡ÛŒØ¯ÛŒÙØ§ÛŒ
        Ø§ÙˆÙ„ÙˆÛŒØªâ€ŒÙ‡Ø§:
        Û±. Ù…ØªØºÛŒØ± Ù…Ø­ÛŒØ·ÛŒ Railway Ø¨Ø± Ø§Ø³Ø§Ø³ ID ÛŒØ§ Username (Ù…Ø§Ù†Ù†Ø¯ RESELLER_1_HIDDIFY_KEY ÛŒØ§ RESELLER_ALI_HIDDIFY_KEY)
        Û². ÙÛŒÙ„Ø¯ hiddify_admin_uuid Ø¯Ø± Ø¯ÛŒØªØ§Ø¨ÛŒØ³
        Û³. Ø¯Ø± ØµÙˆØ±Øª Ø¹Ø¯Ù… ØªÙ†Ø¸ÛŒÙ… -> None (Ø§Ø³ØªÙØ§Ø¯Ù‡ Ø§Ø² Ú©Ù„ÛŒØ¯ Ø§ØµÙ„ÛŒ Ø§Ø¯Ù…ÛŒÙ† Ú©Ù„)
        """
        if not reseller_id:
            return None

        # Û±. Ø¨Ø±Ø±Ø³ÛŒ Ù…ØªØºÛŒØ±Ù‡Ø§ÛŒ Ù…Ø­ÛŒØ·ÛŒ Railway
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

        # Û². Ø¨Ø±Ø±Ø³ÛŒ ÙÛŒÙ„Ø¯ Ø°Ø®ÛŒØ±Ù‡ Ø´Ø¯Ù‡ Ø¯Ø± Ø¯ÛŒØªØ§Ø¨ÛŒØ³
        db_uuid = reseller.get("hiddify_admin_uuid")
        if db_uuid and str(db_uuid).strip():
            return str(db_uuid).strip()

        return None

    def get_reseller_by_hiddify_admin(self, hiddify_admin_uuid: str) -> Optional[dict]:
        """Ù¾ÛŒØ¯Ø§ Ú©Ø±Ø¯Ù† Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ Ø¨Ø± Ø§Ø³Ø§Ø³ Admin UUID Ù‡ÛŒØ¯ÛŒÙØ§ÛŒ"""
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
        Ø¨Ø§Ø²ÛŒØ§Ø¨ÛŒ Ùˆ Ù‡Ù…Ú¯Ø§Ù…â€ŒØ³Ø§Ø²ÛŒ Ù‡ÙˆØ´Ù…Ù†Ø¯ Ø§Ø´ØªØ±Ø§Ú©â€ŒÙ‡Ø§ Ø§Ø² Ù„ÛŒØ³Øª Ú©Ø§Ø±Ø¨Ø±Ø§Ù† Ù‡ÛŒØ¯ÛŒÙØ§ÛŒ
        ØªØ·Ø¨ÛŒÙ‚ Ø®ÙˆØ¯Ú©Ø§Ø± Ú©Ø§Ø±Ø¨Ø± Ø¨Ø§ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ Ø¨Ø± Ø§Ø³Ø§Ø³ added_by ÛŒØ§ ØªÚ¯ Ú©Ø§Ù…Ù†Øª ÛŒØ§ default_reseller_id
        """
        if not users_list or not isinstance(users_list, list):
            return {"success": False, "synced_count": 0, "error": "Ù„ÛŒØ³Øª Ú©Ø§Ø±Ø¨Ø±Ø§Ù† Ù‡ÛŒØ¯ÛŒÙØ§ÛŒ Ø®Ø§Ù„ÛŒ Ø§Ø³Øª."}

        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        synced_count = 0

        try:
            # Ø§ÛŒØ¬Ø§Ø¯ Ù…Ù¾ÛŒÙ†Ú¯ Admin UUID Ø¨Ù‡ Reseller ID
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

                # ØªØ´Ø®ÛŒØµ Ø´Ù†Ø§Ø³Ù‡ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡
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

                # Ø¨Ø±Ø±Ø³ÛŒ ÛŒØ§ Ø§ÛŒØ¬Ø§Ø¯ Ø¯Ø± Ø¬Ø¯ÙˆÙ„ subscriptions
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
                    # Ø§ÛŒØ¬Ø§Ø¯ Ø§Ø´ØªØ±Ø§Ú© Ø¬Ø¯ÛŒØ¯ Ø¨Ø§Ø²Ø³Ø§Ø²ÛŒ Ø´Ø¯Ù‡
                    simulated_tg = 900000000 + abs(hash(uuid_val)) % 99999999
                    cursor.execute("""
                        INSERT INTO subscriptions (
                            telegram_id, hidify_uuid, plan_id, plan_name, account_name,
                            data_limit, data_used, duration, status, reseller_id, created_at, updated_at
                        ) VALUES (?, ?, 'restored', 'Ø§Ø´ØªØ±Ø§Ú© Ø¨Ø§Ø²ÛŒØ§Ø¨ÛŒâ€ŒØ´Ø¯Ù‡ Ù‡ÛŒØ¯ÛŒÙØ§ÛŒ', ?, ?, ?, ?, ?, ?, ?, ?)
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
        Ù‡Ù…Ú¯Ø§Ù…â€ŒØ³Ø§Ø²ÛŒ Ú©Ø§Ù…Ù„ Ø§Ø´ØªØ±Ø§Ú©â€ŒÙ‡Ø§ÛŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ Ø¨Ø§ Ù¾Ù†Ù„ Ù‡ÛŒØ¯ÛŒÙØ§ÛŒ:
        Û±. Ø¨Ø§Ø²ÛŒØ§Ø¨ÛŒ Ùˆ Ø¨Ø±ÙˆØ²Ø±Ø³Ø§Ù†ÛŒ Ú©Ù„ÛŒÙ‡ Ù…Ø´ØªØ±Ú©ÛŒÙ† Ù…ÙˆØ¬ÙˆØ¯ Ø¯Ø± Ù‡ÛŒØ¯ÛŒÙØ§ÛŒ Ø¨Ù‡ Ù¾Ù†Ù„ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡
        Û². Ù…Ù‚Ø§ÛŒØ³Ù‡ Ùˆ Ù¾Ø§Ú©Ø³Ø§Ø²ÛŒ Ú©Ù„ÛŒÙ‡ Ù…Ø´ØªØ±Ú©ÛŒÙ†ÛŒ Ú©Ù‡ Ø¯Ø± Ù¾Ù†Ù„ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ Ù‡Ø³ØªÙ†Ø¯ Ø§Ù…Ø§ Ø¯Ø± Ù‡ÛŒØ¯ÛŒÙØ§ÛŒ ÙˆØ¬ÙˆØ¯ Ù†Ø¯Ø§Ø±Ù†Ø¯
        """
        if not reseller_id:
            return {"success": False, "error": "Ø´Ù†Ø§Ø³Ù‡ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ Ù†Ø§Ù…Ø¹ØªØ¨Ø± Ø§Ø³Øª."}
        if users_list is None or not isinstance(users_list, list):
            return {"success": False, "error": "Ù„ÛŒØ³Øª Ú©Ø§Ø±Ø¨Ø±Ø§Ù† Ù‡ÛŒØ¯ÛŒÙØ§ÛŒ Ù†Ø§Ù…Ø¹ØªØ¨Ø± Ø§Ø³Øª."}

        # Ù…Ø±Ø­Ù„Ù‡ Û±: Ø¨Ø§Ø²ÛŒØ§Ø¨ÛŒ Ùˆ Ø¨Ø±ÙˆØ²Ø±Ø³Ø§Ù†ÛŒ Ù…Ø´ØªØ±Ú©ÛŒÙ† Ù…ÙˆØ¬ÙˆØ¯ Ø¯Ø± Ù‡ÛŒØ¯ÛŒÙØ§ÛŒ
        restore_res = self.restore_subscriptions_from_hiddify(users_list, default_reseller_id=reseller_id)
        synced_count = restore_res.get("synced_count", 0)

        # Ù…Ø±Ø­Ù„Ù‡ Û²: Ø§Ø³ØªØ®Ø±Ø§Ø¬ ØªÙ…Ø§Ù… Ø´Ù†Ø§Ø³Ù‡ (UUID) Ù‡Ø§ÛŒ Ù…Ø¹ØªØ¨Ø± Ú©Ø§Ø±Ø¨Ø±Ø§Ù† Ù‡ÛŒØ¯ÛŒÙØ§ÛŒ
        hiddify_uuids = set()
        for u in users_list:
            if isinstance(u, dict) and u.get("uuid"):
                hiddify_uuids.add(str(u["uuid"]).strip().lower())

        conn = self.get_connection()
        cursor = conn.cursor()
        purged_count = 0
        purged_names = []

        try:
            # ÙˆØ§Ú©Ø´ÛŒ Ú©Ù„ÛŒÙ‡ Ø§Ø´ØªØ±Ø§Ú©â€ŒÙ‡Ø§ÛŒ Ù…Ù†ØªØ³Ø¨ Ø¨Ù‡ Ø§ÛŒÙ† Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ Ø¯Ø± Ø¯ÛŒØªØ§Ø¨ÛŒØ³
            cursor.execute("""
                SELECT id, hidify_uuid, account_name, telegram_id
                FROM subscriptions
                WHERE reseller_id = ?
            """, (reseller_id,))
            current_subs = cursor.fetchall()

            extra_sub_ids = []
            for sub in current_subs:
                sub_uuid = str(sub["hidify_uuid"] or "").strip().lower()
                # Ø§Ú¯Ø± Ú©Ø§Ø±Ø¨Ø± UUID Ù‡ÛŒØ¯ÛŒÙØ§ÛŒ Ù†Ø¯Ø§Ø±Ø¯ ÛŒØ§ Ø¯Ø± Ù„ÛŒØ³Øª Ù‡ÛŒØ¯ÛŒÙØ§ÛŒ ÙˆØ¬ÙˆØ¯ Ù†Ø¯Ø§Ø±Ø¯ -> Ú©Ø§Ø±Ø¨Ø± Ø§Ø¶Ø§ÙÛŒ Ø§Ø³Øª
                if not sub_uuid or sub_uuid not in hiddify_uuids:
                    extra_sub_ids.append(sub["id"])
                    purged_names.append(sub["account_name"] or f"Ø§Ø´ØªØ±Ø§Ú© #{sub['id']}")

            if extra_sub_ids:
                placeholders = ",".join("?" for _ in extra_sub_ids)
                
                # Ø­ÙØ¸ ÛŒÚ©Ù¾Ø§Ø±Ú†Ú¯ÛŒ Ø§Ø±Ø¬Ø§Ø¹Ø§Øª Ø¬Ø¯Ø§ÙˆÙ„ ÙˆØ§Ø¨Ø³ØªÙ‡
                cursor.execute(f"UPDATE transactions SET subscription_id = NULL WHERE subscription_id IN ({placeholders})", extra_sub_ids)
                cursor.execute(f"DELETE FROM subscription_history WHERE subscription_id IN ({placeholders})", extra_sub_ids)
                
                # Ø­Ø°Ù Ú©Ø§Ù…Ù„ Ø§Ø´ØªØ±Ø§Ú©â€ŒÙ‡Ø§ÛŒ Ø§Ø¶Ø§ÙÛŒ Ø§Ø² Ù¾Ù†Ù„ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡
                cursor.execute(f"DELETE FROM subscriptions WHERE id IN ({placeholders})", extra_sub_ids)
                purged_count = len(extra_sub_ids)

                # Ù¾Ø§Ú©Ø³Ø§Ø²ÛŒ Ú©Ø§Ø±Ø¨Ø±Ø§Ù† Ø´Ø¨ÛŒÙ‡â€ŒØ³Ø§Ø²ÛŒâ€ŒØ´Ø¯Ù‡ Ø¨Ø¯ÙˆÙ† Ø§Ø´ØªØ±Ø§Ú© Ø§Ø² Ø¬Ø¯ÙˆÙ„ users
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
        """ÙˆØ§Ú©Ø´ÛŒ Ø§Ø´ØªØ±Ø§Ú©â€ŒÙ‡Ø§ÛŒ ÙØ¹Ø§Ù„ Ø¬Ù‡Øª Ù¾ÛŒØ´â€ŒÙ†Ù…Ø§ÛŒØ´ Ùˆ Ù‡Ù…Ú¯Ø§Ù…â€ŒØ³Ø§Ø²ÛŒ Ø¨Ø§ Ù‡ÛŒØ¯ÛŒÙØ§ÛŒ"""
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
        """Ø¨Ø±Ø±Ø³ÛŒ Ùˆ ØªÙˆÙ„ÛŒØ¯ Ø´Ù†Ø§Ø³Ù‡ UUID Ø¯Ø± ØµÙˆØ±Øª Ø®Ø§Ù„ÛŒ Ø¨ÙˆØ¯Ù† Ø¨Ø±Ø§ÛŒ Ø§Ø´ØªØ±Ø§Ú© Ù…Ø­Ù„ÛŒ"""
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
        """Ø­Ø°Ù Ø§ÛŒÙ…Ù† Ø§Ø´ØªØ±Ø§Ú©â€ŒÙ‡Ø§ÛŒ Ø§Ù†ØªØ®Ø§Ø¨â€ŒØ´Ø¯Ù‡ Ù…Ø­Ù„ÛŒ Ø¨Ø§ Ù¾Ø§Ú©Ø³Ø§Ø²ÛŒ ÙˆØ§Ø¨Ø³ØªÚ¯ÛŒâ€ŒÙ‡Ø§"""
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

            # Ù¾Ø§Ú©Ø³Ø§Ø²ÛŒ Ø§Ø±Ø¬Ø§Ø¹Ø§Øª
            cursor.execute(f"UPDATE transactions SET subscription_id = NULL WHERE subscription_id IN ({placeholders})", valid_ids)
            cursor.execute(f"DELETE FROM subscription_history WHERE subscription_id IN ({placeholders})", valid_ids)
            cursor.execute(f"DELETE FROM subscriptions WHERE id IN ({placeholders})", valid_ids)
            
            # Ù¾Ø§Ú©Ø³Ø§Ø²ÛŒ Ú©Ø§Ø±Ø¨Ø±Ø§Ù† Ø´Ø¨ÛŒÙ‡â€ŒØ³Ø§Ø²ÛŒâ€ŒØ´Ø¯Ù‡ Ø¨Ø¯ÙˆÙ† Ø§Ø´ØªØ±Ø§Ú©
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
        Ø¬Ø³ØªØ¬ÙˆÛŒ Ù‡ÙˆØ´Ù…Ù†Ø¯ Ø§Ø´ØªØ±Ø§Ú©â€ŒÙ‡Ø§ Ø¨Ø± Ø§Ø³Ø§Ø³ Ø§Ù„Ú¯ÙˆØŒ Ù¾ÛŒØ´ÙˆÙ†Ø¯ØŒ ÙˆØ§ÛŒÙ„Ø¯Ú©Ø§Ø±Ø¯ ÛŒØ§ Ø¹Ø¨Ø§Ø±Øª Ù…Ù†Ø¸Ù… (Regex)
        Ø¬Ù‡Øª Ø§Ù†ØªÙ‚Ø§Ù„ Ú¯Ø±ÙˆÙ‡ÛŒ Ùˆ Ø¯Ø³ØªÙ‡â€ŒØ§ÛŒ Ø¨Ù‡ Ù†Ù…Ø§ÛŒÙ†Ø¯Ú¯Ø§Ù†
        """
        if not pattern or not str(pattern).strip():
            return []

        pattern = str(pattern).strip()
        conn = self.get_connection()
        cursor = conn.cursor()

        # Ø§Ø¹Ù…Ø§Ù„ ÙÛŒÙ„ØªØ± Ø¨Ø± Ø§Ø³Ø§Ø³ Ù…Ù†Ø¨Ø¹ Ù…Ø§Ù„Ú©ÛŒØª
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

        # ØªØ¹ÛŒÛŒÙ† Ù†ÙˆØ¹ Ø¬Ø³ØªØ¬Ùˆ Ø¯Ø± Ø­Ø§Ù„Øª auto
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
                # Ø­Ø§Ù„Øª Ù¾ÛŒØ´â€ŒÙØ±Ø¶ / contains / prefix Ù‡ÙˆØ´Ù…Ù†Ø¯
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
                                          admin_name: str = "Ù…Ø¯ÛŒØ±ÛŒØª") -> dict:
        """
        Ø§Ù†ØªÙ‚Ø§Ù„ Ø¯Ø³ØªÙ‡â€ŒØ§ÛŒ Ùˆ Ù‡ÙˆØ´Ù…Ù†Ø¯ Ø§Ø´ØªØ±Ø§Ú©â€ŒÙ‡Ø§ Ø¨Ù‡ ÛŒÚ© Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ Ø¨Ø§ Ø±Ø¹Ø§ÛŒØª Ø´Ø±ÙˆØ· Ø§Ù…Ù†ÛŒØªÛŒ:
        Û±. Ø­ÙØ¸ ØªØ§Ø±ÛŒØ® ÙˆØ§Ù‚Ø¹ÛŒ ÛŒØ§ ØªÙ†Ø¸ÛŒÙ… ØªØ§Ø±ÛŒØ® Ø¨Ù‡ Ø¨ÛŒØ´ Ø§Ø² Û²Û´ Ø³Ø§Ø¹Øª Ú¯Ø°Ø´ØªÙ‡ Ø¬Ù‡Øª Ø¬Ù„ÙˆÚ¯ÛŒØ±ÛŒ Ø§Ø² Ø³ÙˆØ¡Ø§Ø³ØªÙØ§Ø¯Ù‡ Ø§Ø³ØªØ±Ø¯Ø§Ø¯ ÙˆØ¬Ù‡
        Û². Ø§Ù†ØªØ³Ø§Ø¨ Ø¨Ù‡ reseller_id Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ Ùˆ Ø«Ø¨Øª Ù„Ø§Ú¯ ØªØ§Ø±ÛŒØ®Ú†Ù‡
        Û³. Ø¨Ø§Ø²Ú¯Ø±Ø¯Ø§Ù†Ø¯Ù† Ø§Ø·Ù„Ø§Ø¹Ø§Øª Ù„Ø§Ø²Ù… Ø¬Ù‡Øª Ø§Ø¹Ù…Ø§Ù„ Ù‡Ù…Ø²Ù…Ø§Ù† Ø¯Ø± API Ù‡ÛŒØ¯ÛŒÙØ§ÛŒ (ØªØºÛŒÛŒØ± added_by)
        """
        if not sub_ids or not isinstance(sub_ids, list):
            return {"success": False, "transferred_count": 0, "error": "Ù‡ÛŒÚ† Ø§Ø´ØªØ±Ø§Ú©ÛŒ Ø¨Ø±Ø§ÛŒ Ø§Ù†ØªÙ‚Ø§Ù„ Ø§Ù†ØªØ®Ø§Ø¨ Ù†Ø´Ø¯Ù‡ Ø§Ø³Øª."}

        target_reseller = self.get_reseller(target_reseller_id)
        if not target_reseller:
            return {"success": False, "transferred_count": 0, "error": "Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ Ù…Ù‚ØµØ¯ ÛŒØ§ÙØª Ù†Ø´Ø¯."}

        # ØªØ¹ÛŒÛŒÙ† Ø´Ù†Ø§Ø³Ù‡ Ø§Ø¯Ù…ÛŒÙ† Ù‡ÛŒØ¯ÛŒÙØ§ÛŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡
        final_hiddify_admin = target_hiddify_admin or target_reseller.get("hiddify_admin_uuid")

        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        now_dt = get_now_naive()

        # Ø²Ù…Ø§Ù† Ø§Ù…Ù† Ú¯Ø°Ø´ØªÙ‡ (Ø­Ø¯Ø§Ù‚Ù„ Û·Û² Ø³Ø§Ø¹Øª Ù¾ÛŒØ´) Ø¯Ø± ØµÙˆØ±Øª Ù†Ø¨ÙˆØ¯ ØªØ§Ø±ÛŒØ® ÛŒØ§ ØªØ§Ø±ÛŒØ® Ú©Ù…ØªØ± Ø§Ø² Û²Û´ Ø³Ø§Ø¹Øª
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
                
                # Ø¨Ø±Ø±Ø³ÛŒ Ø§ÛŒÙ†Ú©Ù‡ Ø¢ÛŒØ§ ØªØ§Ø±ÛŒØ® Ø§ÛŒØ¬Ø§Ø¯ Ù‚Ø¨Ù„ÛŒ Ù…Ø¹ØªØ¨Ø± Ùˆ Ø¨ÛŒØ´ Ø§Ø² Û²Û´ Ø³Ø§Ø¹Øª Ú¯Ø°Ø´ØªÙ‡ Ø§Ø³Øª
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

                # Ø¨Ø±ÙˆØ²Ø±Ø³Ø§Ù†ÛŒ Ø§Ø´ØªØ±Ø§Ú©: ØªØºÛŒÛŒØ± Ù…Ø§Ù„Ú©ÛŒØªØŒ ØªÙ†Ø¸ÛŒÙ… ØªØ§Ø±ÛŒØ® Ø§Ù…Ù†ØŒ Ùˆ ØµÙØ± Ú©Ø±Ø¯Ù† Ù‡Ø²ÛŒÙ†Ù‡ Ù¾Ø±Ø¯Ø§Ø®ØªÛŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡
                cursor.execute("""
                    UPDATE subscriptions
                    SET reseller_id = ?,
                        created_at = ?,
                        cost_paid = 0,
                        updated_at = ?
                    WHERE id = ?
                """, (target_reseller_id, final_created_at, now, sub_id))

                # Ø«Ø¨Øª Ø¯Ø± Ø¬Ø¯ÙˆÙ„ ØªØ§Ø±ÛŒØ®Ú†Ù‡ Ø§Ø´ØªØ±Ø§Ú©â€ŒÙ‡Ø§ (Ø³ÙˆØ§Ø¨Ù‚ Ù…Ø¯ÛŒØ±ÛŒØª)
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
                        f"Ø§Ù†ØªÙ‚Ø§Ù„ Ø³Ø§Ø²Ù…Ø§Ù†ÛŒ Ø¨Ù‡ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ {target_reseller['name']} (@{target_reseller['username']})",
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
        """Ø§Ø­Ø±Ø§Ø² Ù‡ÙˆÛŒØª Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ (Case-Insensitive Ùˆ Ù…Ù‚Ø§ÙˆÙ… Ø¯Ø± Ø¨Ø±Ø§Ø¨Ø± ÙØ§ØµÙ„Ù‡â€ŒÙ‡Ø§)"""
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
        """Ù„ÛŒØ³Øª Ù‡Ù…Ù‡ Ù†Ù…Ø§ÛŒÙ†Ø¯Ú¯Ø§Ù†"""
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
        """Ø¯Ø±ÛŒØ§ÙØª Ø§Ø·Ù„Ø§Ø¹Ø§Øª ÛŒÚ© Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM resellers WHERE id=?", (reseller_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    def update_reseller(self, reseller_id: int, **kwargs):
        """ÙˆÛŒØ±Ø§ÛŒØ´ Ù…Ø´Ø®ØµØ§Øª Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡"""
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
        """ÙØ¹Ø§Ù„ ÛŒØ§ ØºÛŒØ±ÙØ¹Ø§Ù„ Ú©Ø±Ø¯Ù† Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡"""
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
        """Ø­Ø°Ù Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ ÙØ±ÙˆØ´"""
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

    def add_reseller_balance(self, reseller_id: int, amount: int, description: str = "Ø´Ø§Ø±Ú˜ Ú©ÛŒÙ Ù¾ÙˆÙ„ ØªÙˆØ³Ø· Ù…Ø¯ÛŒØ±ÛŒØª"):
        """Ø§ÙØ²Ø§ÛŒØ´ Ù…ÙˆØ¬ÙˆØ¯ÛŒ Ú©ÛŒÙ Ù¾ÙˆÙ„ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡"""
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
                                description: str = "Ø®Ø±ÛŒØ¯ Ø§Ø´ØªØ±Ø§Ú© Ø¨Ø±Ø§ÛŒ Ù…Ø´ØªØ±ÛŒ", payment_source: str = "auto",
                                subscription_id: int = None, selling_price: int = None, profit_margin: int = None,
                                created_by: str = None):
        """کسر هزینه با پشتیبانی از انتخاب دقیق مبدأ پرداخت (کیف پول نقدی یا اعتبار خرید)، ثبت صادرکننده و ثبت حاشیه سود"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("SELECT balance, credit_limit, credit_debt, credit_enabled, discount_percent, is_partner FROM resellers WHERE id=?", (reseller_id,))
            row = cursor.fetchone()
            if not row:
                return {"success": False, "error": "نماینده یافت نشد."}

            balance = row["balance"] or 0
            credit_limit = row["credit_limit"] or 0
            credit_debt = row["credit_debt"] or 0
            credit_enabled = bool(row["credit_enabled"]) or (credit_limit > 0)
            available_credit = max(0, credit_limit - credit_debt) if credit_enabled else 0
            discount_pct = row["discount_percent"] if ("discount_percent" in row.keys() and row["discount_percent"] is not None) else 20
            is_partner = bool(row["is_partner"]) if "is_partner" in row.keys() else False

            chosen_source = str(payment_source).strip().lower() if payment_source else "auto"
            if selling_price is not None and int(selling_price) > 0:
                selling_val = int(selling_price)
            else:
                selling_val = int(amount * 100 / (100 - discount_pct)) if discount_pct < 100 else int(amount)
            profit_val = int(profit_margin) if profit_margin is not None else max(0, selling_val - int(amount))
            creator_val = str(created_by).strip() if created_by else None

            if is_partner:
                profit_val = selling_val
                desc_text = f"{description} (شریک سیستم - معاف از هزینه)"
                cursor.execute("""
                    INSERT INTO reseller_transactions (reseller_id, type, amount, selling_price, profit_margin, plan_name, account_name, description, payment_source, subscription_id, created_by, created_at)
                    VALUES (?, 'purchase', 0, ?, ?, ?, ?, ?, 'partner', ?, ?, ?)
                """, (reseller_id, selling_val, profit_val, plan_name, account_name, desc_text, subscription_id, creator_val, now))
                tx_id = cursor.lastrowid
                conn.commit()
                return {"success": True, "transaction_id": tx_id, "is_credit": False, "credit_used": 0, "payment_source": "partner"}

            if chosen_source == "wallet":
                if balance < amount:
                    return {
                        "success": False,
                        "error": f"Ù…ÙˆØ¬ÙˆØ¯ÛŒ Ú©ÛŒÙ  Ù¾ÙˆÙ„ Ø´Ù…Ø§ Ú©Ø§Ù ÛŒ Ù†ÛŒØ³Øª! Ù…ÙˆØ¬ÙˆØ¯ÛŒ: {balance:,} ØªÙˆÙ…Ø§Ù† | Ù…Ø¨Ù„Øº Ù…ÙˆØ±Ø¯ Ù†ÛŒØ§Ø²: {amount:,} ØªÙˆÙ…Ø§Ù†"
                    }
                cursor.execute("UPDATE resellers SET balance = balance - ?, updated_at=? WHERE id=?", (amount, now, reseller_id))
                desc_text = f"{description} (Ú©Ø³Ø± Ø§Ø² Ú©ÛŒÙ  Ù¾ÙˆÙ„ Ù†Ù‚Ø¯ÛŒ)"
                cursor.execute("""
                    INSERT INTO reseller_transactions (reseller_id, type, amount, selling_price, profit_margin, plan_name, account_name, description, payment_source, subscription_id, created_by, created_at)
                    VALUES (?, 'purchase', ?, ?, ?, ?, ?, ?, 'wallet', ?, ?, ?)
                """, (reseller_id, amount, selling_val, profit_val, plan_name, account_name, desc_text, subscription_id, creator_val, now))
                tx_id = cursor.lastrowid
                conn.commit()
                return {"success": True, "transaction_id": tx_id, "is_credit": False, "credit_used": 0, "payment_source": "wallet"}

            elif chosen_source == "credit":
                if not credit_enabled:
                    return {"success": False, "error": "Ø§Ø¹ØªØ¨Ø§Ø± Ø®Ø±ÛŒØ¯ Ø¨Ø±Ø§ÛŒ Ø´Ù…Ø§ Ù Ø¹Ø§Ù„ Ù†Ø´Ø¯Ù‡ Ø§Ø³Øª."}
                if available_credit < amount:
                    return {
                        "success": False,
                        "error": f"Ø§Ø¹ØªØ¨Ø§Ø± Ø®Ø±ÛŒØ¯ Ø´Ù…Ø§ Ú©Ø§ÙÛŒ Ù†ÛŒØ³Øª! Ø§Ø¹ØªØ¨Ø§Ø± Ø¨Ø§Ù‚ÛŒÙ…Ø§Ù†Ø¯Ù‡: {available_credit:,} ØªÙˆÙ…Ø§Ù† | Ù…Ø¨Ù„Øº Ù…ÙˆØ±Ø¯ Ù†ÛŒØ§Ø²: {amount:,} ØªÙˆÙ…Ø§Ù†"
                    }
                cursor.execute("UPDATE resellers SET credit_debt = credit_debt + ?, updated_at=? WHERE id=?", (amount, now, reseller_id))
                desc_text = f"{description} (Ú©Ø³Ø± Ø§Ø² Ø§Ø¹ØªØ¨Ø§Ø± Ø®Ø±ÛŒØ¯: {amount:,} Øª Ø¨Ø¯Ù‡ÛŒ)"
                cursor.execute("""
                    INSERT INTO reseller_transactions (reseller_id, type, amount, selling_price, profit_margin, plan_name, account_name, description, payment_source, subscription_id, created_by, created_at)
                    VALUES (?, 'purchase_credit', ?, ?, ?, ?, ?, ?, 'credit', ?, ?, ?)
                """, (reseller_id, amount, selling_val, profit_val, plan_name, account_name, desc_text, subscription_id, creator_val, now))
                tx_id = cursor.lastrowid
                conn.commit()
                return {"success": True, "transaction_id": tx_id, "is_credit": True, "credit_used": amount, "payment_source": "credit"}

            else:
                # Ø­Ø§Ù„Øª Ù‡ÙˆØ´Ù…Ù†Ø¯ Ùˆ Ø®ÙˆØ¯Ú©Ø§Ø± (auto)
                total_available = balance + available_credit
                if total_available < amount:
                    return {
                        "success": False, 
                        "error": f"Ù…ÙˆØ¬ÙˆØ¯ÛŒ Ùˆ Ø§Ø¹ØªØ¨Ø§Ø± Ú©Ø§ÙÛŒ Ù†ÛŒØ³Øª! Ù…ÙˆØ¬ÙˆØ¯ÛŒ: {balance:,} ØªÙˆÙ…Ø§Ù† | Ø§Ø¹ØªØ¨Ø§Ø± Ø¨Ø§Ù‚ÛŒÙ…Ø§Ù†Ø¯Ù‡: {available_credit:,} ØªÙˆÙ…Ø§Ù† | Ù…Ø¨Ù„Øº Ú©Ù„: {amount:,} ØªÙˆÙ…Ø§Ù†"
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

                    desc_text = f"{description} (Ø®Ø±ÛŒØ¯ Ø§Ø¹ØªØ¨Ø§Ø±ÛŒ: {credit_used:,} ØªÙˆÙ…Ø§Ù† Ø¨Ø¯Ù‡ÛŒ)"
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

    def settle_reseller_debt(self, reseller_id: int, amount: int, description: str = "ØªØ³ÙˆÛŒÙ‡ Ø¨Ø¯Ù‡ÛŒ Ø§Ø¹ØªØ¨Ø§Ø±ÛŒ", settled_by: str = "Ù…Ø¯ÛŒØ± Ø§Ø±Ø´Ø¯") -> dict:
        """Ø«Ø¨Øª ØªØ³ÙˆÛŒÙ‡ Ø­Ø³Ø§Ø¨ Ø¨Ø¯Ù‡ÛŒ Ø§Ø¹ØªØ¨Ø§Ø±ÛŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ ØªÙˆØ³Ø· Ù…Ø¯ÛŒØ±ÛŒØª"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("SELECT credit_debt, name, username FROM resellers WHERE id=?", (reseller_id,))
            row = cursor.fetchone()
            if not row:
                return {"success": False, "error": "Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ ÛŒØ§ÙØª Ù†Ø´Ø¯."}

            current_debt = row["credit_debt"] or 0
            if amount <= 0:
                return {"success": False, "error": "Ù…Ø¨Ù„Øº ØªØ³ÙˆÛŒÙ‡ Ø¨Ø§ÛŒØ¯ Ø¨Ø²Ø±Ú¯ØªØ± Ø§Ø² ØµÙØ± Ø¨Ø§Ø´Ø¯."}

            new_debt = max(0, current_debt - amount)
            cursor.execute("UPDATE resellers SET credit_debt = ?, updated_at = ? WHERE id = ?", (new_debt, now, reseller_id))

            cursor.execute("""
                INSERT INTO reseller_transactions (reseller_id, type, amount, plan_name, account_name, description, created_at)
                VALUES (?, 'settle_debt', ?, 'ØªØ³ÙˆÛŒÙ‡ Ø¨Ø¯Ù‡ÛŒ', ?, ?, ?)
            """, (reseller_id, amount, row["username"], f"{description} ØªÙˆØ³Ø· {settled_by}", now))

            # Ø«Ø¨Øª Ø³Ù†Ø¯ Ø¯Ø±Ø¢Ù…Ø¯ÛŒ ØªØ³ÙˆÛŒÙ‡ Ø¯Ø± Ø³ÛŒØ³ØªÙ… Ø­Ø³Ø§Ø¨Ø¯Ø§Ø±ÛŒ
            try:
                self.add_accounting_record(
                    type="income",
                    category="Ø´Ø§Ø±Ú˜ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡",
                    title=f"ØªØ³ÙˆÛŒÙ‡ Ø¨Ø¯Ù‡ÛŒ Ø§Ø¹ØªØ¨Ø§Ø±ÛŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ {row['name']}",
                    amount=amount,
                    source="reseller_debt_settle",
                    description=f"{description} (Ù…Ø§Ù†Ø¯Ù‡ Ø¨Ø¯Ù‡ÛŒ Ø¬Ø¯ÛŒØ¯: {new_debt:,} ØªÙˆÙ…Ø§Ù†)",
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
        """Ù„ÛŒØ³Øª ØªØ±Ø§Ú©Ù†Ø´â€ŒÙ‡Ø§ÛŒ ÛŒÚ© Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ Ø¨Ù‡ Ù‡Ù…Ø±Ø§Ù‡ ØµØ§Ø¯Ø±Ú©Ù†Ù†Ø¯Ù‡ØŒ Ù†ÙˆØ¹ ÙØ±ÙˆØ´ Ùˆ Ø­Ø§Ø´ÛŒÙ‡ Ø³ÙˆØ¯ Ø¯Ù‚ÛŒÙ‚"""
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

            # Ù…Ø­Ø§Ø³Ø¨Ù‡ Ù¾Ø´ØªÛŒØ¨Ø§Ù† Ø­Ø§Ø´ÛŒÙ‡ Ø³ÙˆØ¯ Ùˆ Ù‚ÛŒÙ…Øª ÙØ±ÙˆØ´ Ø¯Ø± ØµÙˆØ±Øª Ø«Ø¨Øª Ù†Ø´Ø¯Ù† Ø¯Ø± Ø³ÙˆØ§Ø¨Ù‚
            if profit <= 0 and selling <= 0 and amount > 0 and ttype in ("purchase", "purchase_credit", "renewal", "renew"):
                selling = int(amount * 100 / (100 - discount_pct)) if discount_pct < 100 else amount
                profit = max(0, selling - amount)
            elif profit <= 0 and selling > amount:
                profit = max(0, selling - amount)

            tx["selling_price"] = selling
            tx["profit_margin"] = profit

            # ØªØ¹ÛŒÛŒÙ† Ø¹Ù†ÙˆØ§Ù† ÙØ§Ø±Ø³ÛŒ Ù†ÙˆØ¹ ÙØ±ÙˆØ´
            if ttype in ("purchase", "purchase_credit"):
                tx["sale_type_title"] = "ÙØ±ÙˆØ´ Ø¬Ø¯ÛŒØ¯"
                tx["sale_type_class"] = "primary"
            elif ttype in ("renewal", "renew", "renew_credit"):
                tx["sale_type_title"] = "ØªÙ…Ø¯ÛŒØ¯"
                tx["sale_type_class"] = "warning"
            elif ttype == "deposit":
                tx["sale_type_title"] = "Ø´Ø§Ø±Ú˜ Ú©ÛŒÙ Ù¾ÙˆÙ„"
                tx["sale_type_class"] = "success"
            elif ttype == "refund":
                tx["sale_type_title"] = "Ø§Ø³ØªØ±Ø¯Ø§Ø¯ ÙˆØ¬Ù‡"
                tx["sale_type_class"] = "info"
            else:
                tx["sale_type_title"] = "-"
                tx["sale_type_class"] = "secondary"

            # ØµØ§Ø¯Ø±Ú©Ù†Ù†Ø¯Ù‡
            raw_c = tx.get("created_by") or tx.get("sub_creator") or ""
            comment = tx.get("sub_comment") or tx.get("description") or ""
            if raw_c in ("bot", "robot", "Ø±Ø¨Ø§Øª") or "bot" in str(raw_c).lower() or "bot" in str(comment).lower() or "Ø±Ø¨Ø§Øª" in str(comment):
                tx["issuer"] = "Ø±Ø¨Ø§Øª"
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
        ØªØ§ÛŒÙ…â€ŒÙ„Ø§ÛŒÙ† Ù‡ÙˆØ´Ù…Ù†Ø¯ Ùˆ Ø¬Ø§Ù…Ø¹ Ø±ÙˆÛŒØ¯Ø§Ø¯Ù‡Ø§ÛŒ Ø²Ù†Ø¯Ù‡ ÙØ¹Ø§Ù„ÛŒØª Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡:
        - Ù…Ø±ØªØ¨â€ŒØ³Ø§Ø²ÛŒ Ù†Ø²ÙˆÙ„ÛŒ Ø¨Ø± Ø§Ø³Ø§Ø³ Ø²Ù…Ø§Ù† Ø¢Ø®Ø±ÛŒÙ† ÙØ¹Ø§Ù„ÛŒØª (Ø¬Ø¯ÛŒØ¯ØªØ±ÛŒÙ† Ø¯Ø± ØµØ¯Ø± Ù„ÛŒØ³Øª)
        - ØªÙÚ©ÛŒÚ© Ú©Ø§Ù…Ù„ ÙØ¹Ø§Ù„ÛŒØªâ€ŒÙ‡Ø§: Ø®Ø±ÛŒØ¯ Ø±Ø¨Ø§ØªØŒ ØªÙ…Ø¯ÛŒØ¯ Ø§Ø´ØªØ±Ø§Ú©â€ŒÙ‡Ø§ØŒ Ø³Ø§Ø®Øª Ù…Ø´ØªØ±ÛŒ Ø¯Ø³ØªÛŒ ØªÙˆØ³Ø· Ù…Ø¯ÛŒØ±Ø§Ù† Ùˆ Ø´Ø§Ø±Ú˜ Ú©ÛŒÙ Ù¾ÙˆÙ„
        - Ø«Ø¨Øª ØµØ§Ø¯Ø±Ú©Ù†Ù†Ø¯Ù‡ (Ù†Ø§Ù… Ú©Ø§Ø±Ø¨Ø±ÛŒ Ù…Ø¯ÛŒØ± ÛŒØ§ Ø¹Ù†ÙˆØ§Ù† 'Ø±Ø¨Ø§Øª')
        - Ø¨Ø±Ú¯Ø±Ø¯Ø§Ù†Ø¯Ù† Û³Û° Ø±ÙˆÛŒØ¯Ø§Ø¯ Ø§Ø®ÛŒØ± Ø¨Ø§ Ù‚Ø§Ø¨Ù„ÛŒØª ØµÙØ­Ù‡â€ŒØ¨Ù†Ø¯ÛŒ
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        res_info = self.get_reseller(reseller_id) or {}
        reseller_uname = res_info.get("username") or f"reseller_{reseller_id}"
        discount_pct = res_info.get("discount_percent") if res_info.get("discount_percent") is not None else 20

        activities = []

        # Û±. Ø§Ø³ØªØ®Ø±Ø§Ø¬ ØªØ±Ø§Ú©Ù†Ø´â€ŒÙ‡Ø§ÛŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ (Ø®Ø±ÛŒØ¯ØŒ ØªÙ…Ø¯ÛŒØ¯ØŒ Ø´Ø§Ø±Ú˜ Ùˆ ...)
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

                # ØªØ´Ø®ÛŒØµ ØµØ§Ø¯Ø±Ú©Ù†Ù†Ø¯Ù‡
                if raw_creator in ("bot", "robot", "Ø±Ø¨Ø§Øª") or "bot" in str(raw_creator).lower() or "bot" in str(comment).lower() or "Ø±Ø¨Ø§Øª" in str(comment):
                    issuer = "Ø±Ø¨Ø§Øª"
                    issuer_type = "bot"
                elif raw_creator:
                    issuer = raw_creator
                    issuer_type = "user"
                else:
                    issuer = reseller_uname
                    issuer_type = "reseller"

                # ØªØ¹ÛŒÛŒÙ† Ù†ÙˆØ¹ ÙØ¹Ø§Ù„ÛŒØª
                if ttype in ("renewal", "renew", "renew_credit"):
                    act_type = "renewal"
                    act_title = "ØªÙ…Ø¯ÛŒØ¯ Ø§Ø´ØªØ±Ø§Ú©"
                    badge_class = "warning"
                elif ttype in ("purchase", "purchase_credit"):
                    act_type = "new_sale"
                    act_title = "ÙØ±ÙˆØ´ Ø¬Ø¯ÛŒØ¯ (Ø³Ø§Ø®Øª Ù…Ø´ØªØ±ÛŒ)"
                    badge_class = "primary"
                elif ttype == "deposit":
                    act_type = "deposit"
                    act_title = "Ø´Ø§Ø±Ú˜ Ú©ÛŒÙ Ù¾ÙˆÙ„"
                    badge_class = "success"
                elif ttype == "refund":
                    act_type = "refund"
                    act_title = "Ø§Ø³ØªØ±Ø¯Ø§Ø¯ ÙˆØ¬Ù‡"
                    badge_class = "info"
                else:
                    act_type = "activity"
                    act_title = "ØªØ±Ø§Ú©Ù†Ø´"
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

        # Û². Ø§Ø¶Ø§ÙÙ‡ Ú©Ø±Ø¯Ù† Ø§Ø´ØªØ±Ø§Ú©â€ŒÙ‡Ø§ÛŒÛŒ Ú©Ù‡ Ø§Ø­ÛŒØ§Ù†Ø§Ù‹ Ø¯Ø± reseller_transactions Ø«Ø¨Øª Ù†Ø´Ø¯Ù‡â€ŒØ§Ù†Ø¯
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
                if raw_creator in ("bot", "robot", "Ø±Ø¨Ø§Øª") or "bot" in str(raw_creator).lower() or "bot" in str(comment).lower():
                    issuer = "Ø±Ø¨Ø§Øª"
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
                    "activity_title": "ØªÙ…Ø¯ÛŒØ¯ Ø§Ø´ØªØ±Ø§Ú©" if is_renewed else "ÙØ±ÙˆØ´ Ø¬Ø¯ÛŒØ¯ (Ø³Ø§Ø®Øª Ù…Ø´ØªØ±ÛŒ)",
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

        # Û³. Ù…Ø±ØªØ¨â€ŒØ³Ø§Ø²ÛŒ Ù†Ø²ÙˆÙ„ÛŒ Ø¨Ø± Ø§Ø³Ø§Ø³ Ø²Ù…Ø§Ù† Ø¯Ù‚ÛŒÙ‚ (Ø¬Ø¯ÛŒØ¯ØªØ±ÛŒÙ† ÙØ¹Ø§Ù„ÛŒØª Ø¯Ø± ØµØ¯Ø± Ù„ÛŒØ³Øª)
        activities.sort(key=lambda x: str(x.get("created_at") or ""), reverse=True)
        return activities[:limit]

    def get_reseller_full_payment_history(self, reseller_id: int) -> dict:
        """Ø¯Ø±ÛŒØ§ÙØª Ø³Ø§Ø¨Ù‚Ù‡ Ú©Ø§Ù…Ù„ Ù¾Ø±Ø¯Ø§Ø®ØªÛŒâ€ŒÙ‡Ø§ØŒ Ø´Ø§Ø±Ú˜Ù‡Ø§ØŒ Ø¨Ø³ØªÙ‡â€ŒÙ‡Ø§ÛŒ Ø§Ø¹ØªØ¨Ø§Ø±ÛŒ Ùˆ Ø±ÛŒØ² ØªØ±Ø§Ú©Ù†Ø´â€ŒÙ‡Ø§ÛŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡"""
        reseller = self.get_reseller(reseller_id)
        if not reseller:
            return {}

        conn = self.get_connection()
        cursor = conn.cursor()

        # Û±. ØªØ±Ø§Ú©Ù†Ø´â€ŒÙ‡Ø§ÛŒ Ú©ÛŒÙ Ù¾ÙˆÙ„ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ (Ø´Ø§Ø±Ú˜Ù‡Ø§ØŒ Ø®Ø±ÛŒØ¯Ù‡Ø§ØŒ ØªÙ…Ø¯ÛŒØ¯Ù‡Ø§ØŒ Ø§Ø³ØªØ±Ø¯Ø§Ø¯Ù‡Ø§)
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

        # Û². Ø±Ø³ÛŒØ¯Ù‡Ø§ØŒ ÙÛŒØ´â€ŒÙ‡Ø§ÛŒ Ø¨Ø§Ù†Ú©ÛŒ Ùˆ ØªØ±Ø§Ú©Ù†Ø´â€ŒÙ‡Ø§ÛŒ Ø«Ø¨Øªâ€ŒØ´Ø¯Ù‡ Ø¯Ø± Ø¬Ø¯ÙˆÙ„ Ø§ØµÙ„ÛŒ
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

        # Û³. Ù…Ø­Ø§Ø³Ø¨Ø§Øª Ù…Ø§Ù„ÛŒ Ø¯Ù‚ÛŒÙ‚ (Ø¨Ø§ Ø­Ø°Ù Ú©Ø§Ù…Ù„ ØªØ±Ø§Ú©Ù†Ø´â€ŒÙ‡Ø§ÛŒ Ø¨Ø§Ø·Ù„â€ŒØ´Ø¯Ù‡)
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
        """Ù„ÛŒØ³Øª Ú©Ø§Ø±Ø¨Ø±Ø§Ù† Ùˆ Ø§Ø´ØªØ±Ø§Ú©â€ŒÙ‡Ø§ÛŒ ÛŒÚ© Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ (Ø¨Ø¯ÙˆÙ† Ù…ÙˆØ§Ø±Ø¯ Ø³Ø·Ù„ Ø²Ø¨Ø§Ù„Ù‡)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM subscriptions WHERE reseller_id=? AND (is_deleted=0 OR is_deleted IS NULL) ORDER BY created_at DESC", (reseller_id,))
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_reseller_stats(self, reseller_id: int):
        """Ø¢Ù…Ø§Ø± Ùˆ Ø´Ø§Ø®Øµâ€ŒÙ‡Ø§ÛŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ Ø´Ø§Ù…Ù„ Ú©ÛŒÙ Ù¾ÙˆÙ„ØŒ Ø§Ø¹ØªØ¨Ø§Ø± Ùˆ ÙˆØ¶Ø¹ÛŒØª Ø¨Ø¯Ù‡ÛŒâ€ŒÙ‡Ø§"""
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
        
        # Ù…Ø¬Ù…ÙˆØ¹ Ø®Ø±ÛŒØ¯Ù‡Ø§ÛŒ ÙˆØ§Ù‚Ø¹ÛŒ (Ú©Ø³Ø± Ù…Ø¨Ø§Ù„Øº Ù…Ø±Ø¬ÙˆØ¹ÛŒ/Ø®Ø·Ø§ Ø¯Ø± ØµÙˆØ±Øª ÙˆØ¬ÙˆØ¯)
        cursor.execute("""
            SELECT COALESCE(
                (SELECT SUM(amount) FROM reseller_transactions WHERE reseller_id=? AND type='purchase'), 0
            ) - COALESCE(
                (SELECT SUM(amount) FROM reseller_transactions WHERE reseller_id=? AND (type='refund' OR description LIKE '%Ø¨Ø±Ú¯Ø´Øª%')), 0
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
        """Ù…Ø­Ø§Ø³Ø¨Ù‡ Ø®Ù„Ø§ØµÙ‡ Ø¬Ø§Ù…Ø¹ ÙˆØ¶Ø¹ÛŒØª Ø§Ø³ØªÙØ§Ø¯Ù‡ Ùˆ Ø¹Ù…Ù„Ú©Ø±Ø¯ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ (Ø§Ù…Ø±ÙˆØ²ØŒ Ø¯ÛŒØ±ÙˆØ²ØŒ Ù…Ø§Ù‡Ø§Ù†Ù‡ØŒ Ù…ÛŒØ§Ù†Ú¯ÛŒÙ† Ø±ÙˆØ²Ø§Ù†Ù‡ Ùˆ ØªØ±Ø§ÙÛŒÚ©)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now_tehran = datetime.now(TEHRAN_TZ)
        today_date = now_tehran.strftime("%Y-%m-%d")
        yesterday_date = (now_tehran - timedelta(days=1)).strftime("%Y-%m-%d")
        month_ago_date = (now_tehran - timedelta(days=30)).strftime("%Y-%m-%d")

        try:
            # Û±. Ø§Ø·Ù„Ø§Ø¹Ø§Øª Ù¾Ø§ÛŒÙ‡ Ùˆ Ù…Ø§Ù„ÛŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡
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

            # Û². Ø§Ø³ØªÙØ§Ø¯Ù‡ Ø§Ù…Ø±ÙˆØ² (Today's Usage)
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

            # Û³. Ø§Ø³ØªÙØ§Ø¯Ù‡ Ø¯ÛŒØ±ÙˆØ² (Yesterday's Usage)
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

            # Û´. Ø§Ø³ØªÙØ§Ø¯Ù‡ Ù…Ø§Ù‡Ø§Ù†Ù‡ (Û³Û° Ø±ÙˆØ² Ø§Ø®ÛŒØ± / Monthly Usage)
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

            # Ù…ÛŒØ§Ù†Ú¯ÛŒÙ† Ù…ØµØ±Ù Ø±ÙˆØ²Ø§Ù†Ù‡ (Ø¨Ø± Ù…Ø¨Ù†Ø§ÛŒ Û³Û° Ø±ÙˆØ²)
            daily_average = int(month_spent / 30) if month_spent > 0 else 0

            # Ûµ. ÙˆØ¶Ø¹ÛŒØª ØªØ±Ø§ÙÛŒÚ© Ù…ØµØ±ÙÛŒ Ù…Ø´ØªØ±Ú©ÛŒÙ† (Traffic stats)
            cursor.execute("""
                SELECT COALESCE(SUM(data_used), 0), COALESCE(SUM(data_limit), 0)
                FROM subscriptions
                WHERE reseller_id = ? AND (is_deleted = 0 OR is_deleted IS NULL)
            """, (reseller_id,))
            traffic_row = cursor.fetchone()
            total_used_gb = round(float(traffic_row[0] or 0), 2)
            total_limit_gb = round(float(traffic_row[1] or 0), 2)
            usage_percent = round((total_used_gb / total_limit_gb * 100), 1) if total_limit_gb > 0 else 0

            # Û¶. Ø¢Ù…Ø§Ø± ÙˆØ¶Ø¹ÛŒØª Ú©Ø§Ø±Ø¨Ø±Ø§Ù†
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

            # Û·. Ø¢Ù…Ø§Ø± Ø§Ø¹Ø¶Ø§ÛŒ ØªÛŒÙ… Ø²ÛŒØ±Ù…Ø¬Ù…ÙˆØ¹Ù‡
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
        Ù…Ø­Ø§Ø³Ø¨Ù‡ Ø±ÙˆÙ†Ø¯ Ø¯Ø±Ø¢Ù…Ø¯ Ùˆ ÙØ±ÙˆØ´ Û· Ø±ÙˆØ² Ú¯Ø°Ø´ØªÙ‡ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ (Ø´Ø§Ù…Ù„ Ù¾Ø±Ø¯Ø§Ø®Øªâ€ŒÙ‡Ø§ÛŒ Ø±Ø¨Ø§Øª Ùˆ ÙØ±ÙˆØ´ Ù…Ø³ØªÙ‚ÛŒÙ… Ù¾Ù†Ù„)
        Ø¨Ù‡ Ù‡Ù…Ø±Ø§Ù‡ ØªØ§Ø±ÛŒØ®â€ŒÙ‡Ø§ÛŒ Ø´Ù…Ø³ÛŒØŒ Ù†Ø§Ù… Ø±ÙˆØ² Ù‡ÙØªÙ‡ØŒ ØªØ¹Ø¯Ø§Ø¯ Ø³ÙØ§Ø±Ø´Ø§ØªØŒ Ù…ÛŒØ§Ù†Ú¯ÛŒÙ† ÙØ±ÙˆØ´ Ùˆ Ø³ÙˆØ¯ Ø¨Ø±Ø¢ÙˆØ±Ø¯ Ø´Ø¯Ù‡
        """
        import datetime
        from utils import get_now_naive, gregorian_to_shamsi

        conn = self.get_connection()
        cursor = conn.cursor()
        now_dt = get_now_naive()
        today = now_dt.date()

        PERSIAN_WEEKDAYS = {
            0: "Ø¯ÙˆØ´Ù†Ø¨Ù‡",
            1: "Ø³Ù‡â€ŒØ´Ù†Ø¨Ù‡",
            2: "Ú†Ù‡Ø§Ø±Ø´Ù†Ø¨Ù‡",
            3: "Ù¾Ù†Ø¬â€ŒØ´Ù†Ø¨Ù‡",
            4: "Ø¬Ù…Ø¹Ù‡",
            5: "Ø´Ù†Ø¨Ù‡",
            6: "ÛŒÚ©Ø´Ù†Ø¨Ù‡"
        }

        # Ø¯Ø±ØµØ¯ ØªØ®ÙÛŒÙ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ Ø¬Ù‡Øª ØªØ®Ù…ÛŒÙ† Ø³ÙˆØ¯ Ø­Ø§ØµÙ„Ù‡
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
            # Ø§Ø³ØªØ®Ø±Ø§Ø¬ Ø¯Ø§Ø¯Ù‡â€ŒÙ‡Ø§ÛŒ Û· Ø±ÙˆØ² Ø§Ø®ÛŒØ± (Ø§Ø² Û¶ Ø±ÙˆØ² Ù‚Ø¨Ù„ ØªØ§ Ø§Ù…Ø±ÙˆØ² Ø¨Ù‡ ØªØ±ØªÛŒØ¨ Ø²Ù…Ø§Ù†ÛŒ)
            for i in range(6, -1, -1):
                cur_date = today - datetime.timedelta(days=i)
                date_str = cur_date.strftime("%Y-%m-%d")
                weekday_name = PERSIAN_WEEKDAYS[cur_date.weekday()]

                if i == 0:
                    day_label = f"Ø§Ù…Ø±ÙˆØ² ({weekday_name})"
                elif i == 1:
                    day_label = f"Ø¯ÛŒØ±ÙˆØ² ({weekday_name})"
                else:
                    day_label = weekday_name

                jalali_str = gregorian_to_shamsi(date_str, fmt="%Y/%m/%d")

                # Û±. Ù¾Ø±Ø¯Ø§Ø®Øªâ€ŒÙ‡Ø§ÛŒ ØªØ§ÛŒÛŒØ¯ Ø´Ø¯Ù‡ Ø±Ø¨Ø§Øª ØªÙ„Ú¯Ø±Ø§Ù… Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡
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

                # Û². Ø®Ø±ÛŒØ¯Ù‡Ø§ÛŒ Ù…Ø³ØªÙ‚ÛŒÙ… Ùˆ ØªÙ…Ø¯ÛŒØ¯Ù‡Ø§ÛŒ Ø«Ø¨Øª Ø´Ø¯Ù‡ Ø¯Ø± Ù¾Ù†Ù„ ÙˆØ¨ ØªÙˆØ³Ø· Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ (Ù…Ø­Ø§Ø³Ø¨Ù‡ Ø¨Ù‡ Ø¹Ù†ÙˆØ§Ù† Ø¯Ø±Ø¢Ù…Ø¯ Ø¨Ø§ Ù‚ÛŒÙ…Øª ÙØ±ÙˆØ´ Ùˆ Ø³ÙˆØ¯)
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
        """Ø¯Ø±ÛŒØ§ÙØª Ø§Ø·Ù„Ø§Ø¹Ø§Øª ÛŒÚ© Ø§Ø´ØªØ±Ø§Ú© Ù…ØªØ¹Ù„Ù‚ Ø¨Ù‡ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡"""
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
        """ÙˆÛŒØ±Ø§ÛŒØ´ Ø¬Ø§Ù…Ø¹ Ù…Ø´Ø®ØµØ§Øª Ù…Ø´ØªØ±ÛŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ØŒ ÙˆØ¶Ø¹ÛŒØª Ø¨Ø¯Ù‡ÛŒ Ùˆ Ù‡Ù…Ú¯Ø§Ù…â€ŒØ³Ø§Ø²ÛŒ Ø¨Ø§ Ú©Ø§Ø±Ø¨Ø±Ø§Ù† Ùˆ ØªØ±Ø§Ú©Ù†Ø´â€ŒÙ‡Ø§"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("SELECT * FROM subscriptions WHERE id=? AND reseller_id=?", (sub_id, reseller_id))
            sub_row = cursor.fetchone()
            if not sub_row:
                return {"success": False, "error": "Ø§Ø´ØªØ±Ø§Ú© Ù…ÙˆØ±Ø¯ Ù†Ø¸Ø± ÛŒØ§ÙØª Ù†Ø´Ø¯"}

            sub_dict = dict(sub_row)
            clean_name = account_name.strip() if account_name else (sub_dict.get("account_name") or f"user_{sub_id}")
            clean_phone = phone_number.strip() if phone_number and str(phone_number).strip() else None
            clean_comment = comment.strip() if comment and str(comment).strip() else None
            effective_tg = int(telegram_id) if (telegram_id is not None and str(telegram_id).isdigit() and int(telegram_id) > 0) else sub_dict.get("telegram_id")

            debt_created = now if (payment_status in ('unpaid', 'debtor') and not sub_dict.get("debt_created_at")) else sub_dict.get("debt_created_at")

            # Û±. Ø¨Ø±ÙˆØ²Ø±Ø³Ø§Ù†ÛŒ Ø¬Ø¯ÙˆÙ„ subscriptions
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

            # Ø¯Ø± ØµÙˆØ±Øª ØªØ³ÙˆÛŒÙ‡ Ø¨Ø¯Ù‡ÛŒ ÛŒØ§ ØªÙ†Ø¸ÛŒÙ… Ù…Ø¨Ù„Øº Û°ØŒ Ø¨Ø³ØªÙ† ÙØ§Ú©ØªÙˆØ±Ù‡Ø§ÛŒ Ø¨Ø§Ø²
            if payment_status == 'paid' or (debt_amount is not None and int(debt_amount) == 0):
                cursor.execute("""
                    UPDATE customer_debt_records
                    SET status = 'paid', paid_at = ?, settled_by = ?, updated_at = ?
                    WHERE subscription_id = ? AND status = 'unpaid'
                """, (now, f"reseller_{reseller_id}", now, sub_id))

            # Û². Ø§Ú¯Ø± Ú©Ø§Ø±Ø¨Ø± Ø¯Ø§Ø±Ø§ÛŒ Ø´Ù†Ø§Ø³Ù‡ ØªÙ„Ú¯Ø±Ø§Ù… Ø¨Ø§Ø´Ø¯ØŒ Ø¨Ø±ÙˆØ²Ø±Ø³Ø§Ù†ÛŒ Ø¯Ø± Ø¬Ø¯ÙˆÙ„ users
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

            # Û³. Ø¨Ø±ÙˆØ²Ø±Ø³Ø§Ù†ÛŒ Ø¯Ø± ØªØ±Ø§Ú©Ù†Ø´â€ŒÙ‡Ø§ÛŒ Ù…Ø±Ø¨ÙˆØ· Ø¨Ù‡ Ø§ÛŒÙ† Ø§Ø´ØªØ±Ø§Ú©
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
        """ÙØ¹Ø§Ù„ ÛŒØ§ ØºÛŒØ±ÙØ¹Ø§Ù„ Ú©Ø±Ø¯Ù† Ù…Ø´ØªØ±ÛŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ Ø¨Ø¯ÙˆÙ† Ú©Ø³Ø± ÛŒØ§ Ø¨Ø§Ø²Ú¯Ø´Øª Ù‡Ø²ÛŒÙ†Ù‡ Ù‡Ù…Ø±Ø§Ù‡ Ø¨Ø§ Ø«Ø¨Øª Ø¹Ù„Øª ØºÛŒØ±ÙØ¹Ø§Ù„â€ŒØ³Ø§Ø²ÛŒ"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("SELECT status FROM subscriptions WHERE id=? AND reseller_id=?", (sub_id, reseller_id))
            row = cursor.fetchone()
            if not row:
                return {"success": False, "error": "Ø§Ø´ØªØ±Ø§Ú© ÛŒØ§ÙØª Ù†Ø´Ø¯."}
            
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
        """ØªÙ…Ø¯ÛŒØ¯ Ø§Ø´ØªØ±Ø§Ú© Ù…Ø´ØªØ±ÛŒ ØªÙˆØ³Ø· Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ Ø¨Ø§ Ø§Ù†ØªØ®Ø§Ø¨ Ø¯Ù‚ÛŒÙ‚ Ù…Ø¨Ø¯Ø£ Ù¾Ø±Ø¯Ø§Ø®ØªØŒ Ø«Ø¨Øª ØµØ§Ø¯Ø±Ú©Ù†Ù†Ø¯Ù‡ Ùˆ Ø«Ø¨Øª Ø­Ø§Ø´ÛŒÙ‡ Ø³ÙˆØ¯"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            # Ø¨Ø±Ø±Ø³ÛŒ Ù…ÙˆØ¬ÙˆØ¯ÛŒ Ú©ÛŒÙ Ù¾ÙˆÙ„ Ùˆ Ø³Ù‚Ù Ø§Ø¹ØªØ¨Ø§Ø±
            cursor.execute("SELECT balance, credit_enabled, credit_limit, credit_debt, discount_percent FROM resellers WHERE id=?", (reseller_id,))
            res_row = cursor.fetchone()
            if not res_row:
                return {"success": False, "error": "Ø§Ø·Ù„Ø§Ø¹Ø§Øª Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ ÛŒØ§ÙØª Ù†Ø´Ø¯."}

            balance = res_row["balance"] or 0
            credit_limit = (res_row["credit_limit"] or 0) if "credit_limit" in res_row.keys() else 0
            credit_debt = (res_row["credit_debt"] or 0) if "credit_debt" in res_row.keys() else 0
            credit_enabled = bool(res_row["credit_enabled"]) if ("credit_enabled" in res_row.keys() and res_row["credit_enabled"]) else (credit_limit > 0)
            available_credit = max(0, credit_limit - credit_debt) if credit_enabled else 0
            discount_pct = res_row["discount_percent"] if ("discount_percent" in res_row.keys() and res_row["discount_percent"] is not None) else 20

            cursor.execute("SELECT * FROM subscriptions WHERE id=? AND reseller_id=?", (sub_id, reseller_id))
            sub = cursor.fetchone()
            if not sub:
                return {"success": False, "error": "Ø§Ø´ØªØ±Ø§Ú© Ù…ÙˆØ±Ø¯ Ù†Ø¸Ø± ÛŒØ§ÙØª Ù†Ø´Ø¯."}

            chosen_source = str(payment_source).strip().lower() if payment_source else "auto"
            mode_title = "ÙØ¹Ø§Ù„â€ŒØ³Ø§Ø²ÛŒ Ø¢Ù†ÛŒ" if instant_activate else "Ø±Ø²Ø±Ùˆ Ø¯Ø± ØµÙ ØªÙ…Ø¯ÛŒØ¯"
            actual_source = "wallet"

            if selling_price is not None and int(selling_price) > 0:
                selling_val = int(selling_price)
            else:
                selling_val = int(cost * 100 / (100 - discount_pct)) if discount_pct < 100 else int(cost)
            profit_val = int(profit_margin) if profit_margin is not None else max(0, selling_val - int(cost))
            creator_val = str(created_by).strip() if created_by else None

            if chosen_source == "wallet":
                if balance < cost:
                    return {"success": False, "error": f"Ù…ÙˆØ¬ÙˆØ¯ÛŒ Ú©ÛŒÙ Ù¾ÙˆÙ„ Ø´Ù…Ø§ Ú©Ø§ÙÛŒ Ù†ÛŒØ³Øª! Ù…ÙˆØ¬ÙˆØ¯ÛŒ: {balance:,} ØªÙˆÙ…Ø§Ù† | Ù‡Ø²ÛŒÙ†Ù‡ ØªÙ…Ø¯ÛŒØ¯: {cost:,} ØªÙˆÙ…Ø§Ù†"}
                cursor.execute("UPDATE resellers SET balance = balance - ?, updated_at=? WHERE id=?", (cost, now, reseller_id))
                tx_desc = f"ØªÙ…Ø¯ÛŒØ¯ Ø§Ø´ØªØ±Ø§Ú© Â«{sub['account_name']}Â» Ø¨Ø§ Ù¾Ù„Ù† {plan_name} ({mode_title} - Ú©Ø³Ø± Ø§Ø² Ú©ÛŒÙ Ù¾ÙˆÙ„ Ù†Ù‚Ø¯ÛŒ)"
                actual_source = "wallet"

            elif chosen_source == "credit":
                if not credit_enabled:
                    return {"success": False, "error": "Ø§Ø¹ØªØ¨Ø§Ø± Ø®Ø±ÛŒØ¯ Ø¨Ø±Ø§ÛŒ Ø´Ù…Ø§ ÙØ¹Ø§Ù„ Ù†Ø´Ø¯Ù‡ Ø§Ø³Øª."}
                if available_credit < cost:
                    return {"success": False, "error": f"Ø§Ø¹ØªØ¨Ø§Ø± Ø®Ø±ÛŒØ¯ Ø´Ù…Ø§ Ú©Ø§ÙÛŒ Ù†ÛŒØ³Øª! Ø§Ø¹ØªØ¨Ø§Ø± Ø¨Ø§Ù‚ÛŒÙ…Ø§Ù†Ø¯Ù‡: {available_credit:,} ØªÙˆÙ…Ø§Ù† | Ù‡Ø²ÛŒÙ†Ù‡ ØªÙ…Ø¯ÛŒØ¯: {cost:,} ØªÙˆÙ…Ø§Ù†"}
                new_debt = credit_debt + cost
                cursor.execute("UPDATE resellers SET credit_debt = ?, updated_at=? WHERE id=?", (new_debt, now, reseller_id))
                tx_desc = f"ØªÙ…Ø¯ÛŒØ¯ Ø§Ø´ØªØ±Ø§Ú© Â«{sub['account_name']}Â» Ø¨Ø§ Ù¾Ù„Ù† {plan_name} ({mode_title} - Ú©Ø³Ø± Ø§Ø² Ø§Ø¹ØªØ¨Ø§Ø± Ø®Ø±ÛŒØ¯: {cost:,} Øª Ø¨Ø¯Ù‡ÛŒ)"
                actual_source = "credit"

            else:
                # Ø­Ø§Ù„Øª Ù‡ÙˆØ´Ù…Ù†Ø¯ Ùˆ Ø®ÙˆØ¯Ú©Ø§Ø± (auto)
                total_purchasing_power = balance + available_credit
                if total_purchasing_power < cost:
                    return {"success": False, "error": f"Ù…ÙˆØ¬ÙˆØ¯ÛŒ Ú©ÛŒÙ Ù¾ÙˆÙ„ ({balance:,} Øª) Ùˆ Ø§Ø¹ØªØ¨Ø§Ø± ØªÙ…Ø¯ÛŒØ¯ ({available_credit:,} Øª) Ø¨Ø±Ø§ÛŒ ØªÙ…Ø¯ÛŒØ¯ Ø§ÛŒÙ† Ù¾Ù„Ù† ({cost:,} Øª) Ú©Ø§ÙÛŒ Ù†ÛŒØ³Øª."}

                if balance >= cost:
                    cursor.execute("UPDATE resellers SET balance = balance - ?, updated_at=? WHERE id=?", (cost, now, reseller_id))
                    tx_desc = f"ØªÙ…Ø¯ÛŒØ¯ Ø§Ø´ØªØ±Ø§Ú© Â«{sub['account_name']}Â» Ø¨Ø§ Ù¾Ù„Ù† {plan_name} ({mode_title} - Ù¾Ø±Ø¯Ø§Ø®Øª Ø§Ø² Ú©ÛŒÙ Ù¾ÙˆÙ„)"
                    actual_source = "wallet"
                else:
                    from_credit = cost - balance
                    new_debt = credit_debt + from_credit
                    cursor.execute("UPDATE resellers SET balance = 0, credit_debt = ?, updated_at=? WHERE id=?", (new_debt, now, reseller_id))
                    tx_desc = f"ØªÙ…Ø¯ÛŒØ¯ Ø§Ø´ØªØ±Ø§Ú© Â«{sub['account_name']}Â» Ø¨Ø§ Ù¾Ù„Ù† {plan_name} ({mode_title} - Ú©Ø³Ø± {balance:,} Øª Ø§Ø² Ú©ÛŒÙ Ù¾ÙˆÙ„ Ùˆ {from_credit:,} Øª Ø§Ø² Ø§Ø¹ØªØ¨Ø§Ø±)"
                    actual_source = "credit"

            # Ø«Ø¨Øª ØªØ±Ø§Ú©Ù†Ø´ ØªÙ…Ø¯ÛŒØ¯ Ø¨Ø§ Ù…Ø´Ø®Øµ Ø¨ÙˆØ¯Ù† Ù…Ø¨Ø¯Ø£ Ù¾Ø±Ø¯Ø§Ø®ØªØŒ ØµØ§Ø¯Ø±Ú©Ù†Ù†Ø¯Ù‡ Ùˆ Ø­Ø§Ø´ÛŒÙ‡ Ø³ÙˆØ¯
            cursor.execute("""
                INSERT INTO reseller_transactions (reseller_id, type, amount, selling_price, profit_margin, plan_name, account_name, description, payment_source, subscription_id, created_by, created_at)
                VALUES (?, 'renewal', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (reseller_id, cost, selling_val, profit_val, plan_name, sub["account_name"], tx_desc, actual_source, sub_id, creator_val, now))

            if instant_activate:
                # Û³. Ø¨Ù‡â€ŒØ±ÙˆØ²Ø±Ø³Ø§Ù†ÛŒ Ø¢Ù†ÛŒ Ù…Ø´Ø®ØµØ§Øª Ø§Ø´ØªØ±Ø§Ú©ØŒ Ø±ÛŒØ³Øª Ø­Ø¬Ù… Ù…ØµØ±ÙÛŒ Ùˆ Ø±ÛŒØ³Øª ØªØ§Ø±ÛŒØ® Ø´Ø±ÙˆØ¹ Ùˆ Ø§Ù†Ù‚Ø¶Ø§
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
                # Û´. Ø§ÙØ²ÙˆØ¯Ù† Ø¨Ù‡ ØµÙ ØªÙ…Ø¯ÛŒØ¯ Ù‡ÙˆØ´Ù…Ù†Ø¯ (Ø±Ø²Ø±Ùˆ Ø¨Ø³ØªÙ‡ Ø®ÙˆØ¯Ú©Ø§Ø± Ø¨Ø¯ÙˆÙ† Ù„ØºÙˆ Ø¨Ø³ØªÙ‡â€ŒÙ‡Ø§ÛŒ Ù‚Ø¨Ù„ÛŒ)
                cursor.execute("SELECT COALESCE(MAX(queue_order), 0) + 1 FROM subscription_queue WHERE subscription_id=? AND status='pending'", (sub_id,))
                next_order_row = cursor.fetchone()
                next_order = next_order_row[0] if next_order_row else 1
                cursor.execute("""
                    INSERT INTO subscription_queue (
                        subscription_id, telegram_id, hidify_uuid, reseller_id,
                        plan_id, plan_name, data_limit, duration, cost, status, created_at, note, queue_order
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)
                """, (sub_id, sub["telegram_id"] or 0, sub["hidify_uuid"] or "", reseller_id,
                      plan_id, plan_name, data_limit, duration, cost, now, f"ØªÙ…Ø¯ÛŒØ¯ Ø±Ø²Ø±Ùˆ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ ({actual_source})", next_order))
                cursor.execute("UPDATE subscriptions SET payment_source=? WHERE id=?", (actual_source, sub_id))
                conn.commit()
                return {"success": True, "mode": "queued", "payment_source": actual_source, "queue_order": next_order}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def _normalize_subscription_queue_orders(self, cursor, subscription_id: int):
        """Ù…Ø±ØªØ¨â€ŒØ³Ø§Ø²ÛŒ Ùˆ Ø§ØµÙ„Ø§Ø­ Ù…Ø¬Ø¯Ø¯ Ø´Ù…Ø§Ø±Ù‡ Ù†ÙˆØ¨Øª Ø¨Ø³ØªÙ‡â€ŒÙ‡Ø§ÛŒ Ù…Ø¹Ù„Ù‚ Ø¯Ø± ØµÙ ÛŒÚ© Ø§Ø´ØªØ±Ø§Ú© (1, 2, 3...)"""
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
        """Ø§ÙØ²ÙˆØ¯Ù† Ø¨Ø³ØªÙ‡ ØªÙ…Ø¯ÛŒØ¯ÛŒ Ø¨Ù‡ ØµÙ Ø±Ø²Ø±Ùˆ Ø®ÙˆØ¯Ú©Ø§Ø± (Ø¨Ø¯ÙˆÙ† Ù„ØºÙˆ Ø¨Ø³ØªÙ‡â€ŒÙ‡Ø§ÛŒ Ù‚Ø¨Ù„ÛŒ Ùˆ Ø¨Ø§ ØªØ¹ÛŒÛŒÙ† Ø´Ù…Ø§Ø±Ù‡ Ù†ÙˆØ¨Øª)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("SELECT * FROM subscriptions WHERE id=?", (subscription_id,))
            sub_row = cursor.fetchone()
            if not sub_row:
                return {"success": False, "error": "Ø§Ø´ØªØ±Ø§Ú© ÛŒØ§ÙØª Ù†Ø´Ø¯."}

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
            """, (subscription_id, t_id, u_uuid, r_id, plan_id, plan_name, data_limit, duration, cost, now, note or "ØªÙ…Ø¯ÛŒØ¯ Ø¯Ø± ØµÙ Ø±Ø²Ø±Ùˆ Ù…Ø¯ÛŒØ±ÛŒØª", next_order))
            queue_id = cursor.lastrowid
            conn.commit()
            return {"success": True, "queue_id": queue_id, "queue_order": next_order}
        except Exception as e:
            logger.error(f"Error adding to subscription queue: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def get_pending_queue_items(self, subscription_id: int) -> list:
        """Ø¯Ø±ÛŒØ§ÙØª ØªÙ…Ø§Ù… Ø¨Ø³ØªÙ‡â€ŒÙ‡Ø§ÛŒ Ø¯Ø± ØµÙ ÛŒÚ© Ø§Ø´ØªØ±Ø§Ú© Ø¨Ù‡ ØªØ±ØªÛŒØ¨ Ù†ÙˆØ¨Øª ØªÙ…Ø¯ÛŒØ¯"""
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
        """Ø¯Ø±ÛŒØ§ÙØª Ø§ÙˆÙ„ÛŒÙ† Ø¨Ø³ØªÙ‡ Ø¯Ø± Ù†ÙˆØ¨Øª ØµÙ Ø¨Ø±Ø§ÛŒ ÛŒÚ© Ø§Ø´ØªØ±Ø§Ú© Ø®Ø§Øµ"""
        items = self.get_pending_queue_items(subscription_id)
        return items[0] if items else None

    def reorder_subscription_queue(self, subscription_id: int, queue_id: int, direction: str) -> dict:
        """
        ØªØºÛŒÛŒØ± Ù†ÙˆØ¨Øª ÛŒÚ© Ø¨Ø³ØªÙ‡ Ø¯Ø± ØµÙ ØªÙ…Ø¯ÛŒØ¯ (direction: 'up', 'down', 'top')
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
                return {"success": False, "error": "Ø¨Ø³ØªÙ‡ Ø¯Ø± ØµÙ ÛŒØ§ÙØª Ù†Ø´Ø¯."}

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
                return {"success": False, "error": "Ø¬Ù‡Øª Ø¬Ø§Ø¨Ø¬Ø§ÛŒÛŒ Ù†Ø§Ù…Ø¹ØªØ¨Ø± Ø§Ø³Øª."}

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
        """Ø¯Ø±ÛŒØ§ÙØª ØªÙ…Ø§Ù… Ø¨Ø³ØªÙ‡â€ŒÙ‡Ø§ÛŒ Ø¯Ø± ØµÙ Ø¨Ù‡ Ù‡Ù…Ø±Ø§Ù‡ Ø§Ø·Ù„Ø§Ø¹Ø§Øª Ø§Ø´ØªØ±Ø§Ú© Ù…Ø±Ø¨ÙˆØ·Ù‡ Ø¨Ù‡ ØªØ±ØªÛŒØ¨ Ù†ÙˆØ¨Øª Ø¨Ø±Ø§ÛŒ Ù¾Ø±Ø¯Ø§Ø²Ø´ Ø®ÙˆØ¯Ú©Ø§Ø± Ùˆ Ù†Ù…Ø§ÛŒØ´ Ø¯Ø± Ù¾Ù†Ù„"""
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
        """Ø¯Ø±ÛŒØ§ÙØª ØªØ¹Ø¯Ø§Ø¯ Ú©Ù„ Ø¨Ø³ØªÙ‡â€ŒÙ‡Ø§ÛŒ Ø¯Ø± Ø§Ù†ØªØ¸Ø§Ø± ØµÙ ØªÙ…Ø¯ÛŒØ¯"""
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
        """Ø¯Ø±ÛŒØ§ÙØª ØªØ§Ø±ÛŒØ®Ú†Ù‡ Ùˆ ÙˆØ¶Ø¹ÛŒØª Ø¨Ø³ØªÙ‡â€ŒÙ‡Ø§ÛŒ Ø¯Ø± ØµÙ ÛŒÚ© Ø§Ø´ØªØ±Ø§Ú© Ø®Ø§Øµ"""
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
        """Ø¹Ù„Ø§Ù…Øªâ€ŒÚ¯Ø°Ø§Ø±ÛŒ Ø¨Ø³ØªÙ‡ Ø¯Ø± ØµÙ Ø¨Ù‡ Ø¹Ù†ÙˆØ§Ù† ÙØ¹Ø§Ù„â€ŒØ´Ø¯Ù‡ Ùˆ Ø¨Ù‡â€ŒØ±ÙˆØ²Ø±Ø³Ø§Ù†ÛŒ Ù†ÙˆØ¨Øª Ø¨Ø³ØªÙ‡â€ŒÙ‡Ø§ÛŒ Ø¨Ø§Ù‚ÛŒÙ…Ø§Ù†Ø¯Ù‡"""
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
        """Ù„ØºÙˆ Ø¨Ø³ØªÙ‡ Ø¯Ø± ØµÙ Ùˆ Ø§Ø³ØªØ±Ø¯Ø§Ø¯ ÙˆØ¬Ù‡ Ø¨Ù‡ Ú©ÛŒÙâ€ŒÙ¾ÙˆÙ„ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ ÛŒØ§ Ú©Ø§Ø±Ø¨Ø± Ø¯Ø± ØµÙˆØ±Øª Ù¾Ø±Ø¯Ø§Ø®Øª Ù‡Ø²ÛŒÙ†Ù‡"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("SELECT * FROM subscription_queue WHERE id=? AND status='pending'", (queue_id,))
            item = cursor.fetchone()
            if not item:
                return {"success": False, "error": "Ø¨Ø³ØªÙ‡ Ù…ÙˆØ±Ø¯ Ù†Ø¸Ø± Ø¯Ø± ØµÙ ÛŒØ§ÙØª Ù†Ø´Ø¯ ÛŒØ§ Ù‚Ø¨Ù„Ø§Ù‹ Ù¾Ø±Ø¯Ø§Ø²Ø´ Ø´Ø¯Ù‡ Ø§Ø³Øª."}

            item_dict = dict(item)
            cost = item_dict.get("cost") or 0
            r_id = item_dict.get("reseller_id")
            sub_id = item_dict.get("subscription_id")

            if reseller_id and r_id and r_id != reseller_id:
                return {"success": False, "error": "Ø´Ù…Ø§ Ø¨Ù‡ Ø§ÛŒÙ† Ø¨Ø³ØªÙ‡ Ø¯Ø³ØªØ±Ø³ÛŒ Ù†Ø¯Ø§Ø±ÛŒØ¯."}

            cursor.execute("SELECT * FROM subscriptions WHERE id=?", (sub_id,))
            sub_row = cursor.fetchone()
            sub_dict = dict(sub_row) if sub_row else {}
            account_name = sub_dict.get("account_name") or f"user_{sub_id}"

            # Ø§Ø³ØªØ±Ø¯Ø§Ø¯ ÙˆØ¬Ù‡ Ø¨Ù‡ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡
            if r_id and cost > 0:
                # Ø¨Ø±Ø±Ø³ÛŒ Ù…Ù†Ø¨Ø¹ Ù¾Ø±Ø¯Ø§Ø®Øª ØªÙ…Ø¯ÛŒØ¯ Ùˆ Ø¹Ù„Ø§Ù…Øªâ€ŒÚ¯Ø°Ø§Ø±ÛŒ ØªØ±Ø§Ú©Ù†Ø´ ØªÙ…Ø¯ÛŒØ¯ Ø¨Ù‡ Ù„ØºÙˆ Ø´Ø¯Ù‡
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
                        SET type = 'renewal_cancelled', description = description || ' [Ù„ØºÙˆ Ø´Ø¯Ù‡ Ø§Ø² ØµÙ ØªÙ…Ø¯ÛŒØ¯]'
                        WHERE id = ?
                    """, (renew_tx_id,))

                if renew_source == "credit":
                    cursor.execute("UPDATE resellers SET credit_debt = MAX(0, credit_debt - ?), updated_at=? WHERE id=?", (cost, now, r_id))
                    cursor.execute("""
                        INSERT INTO reseller_transactions (reseller_id, type, amount, plan_name, account_name, description, payment_source, subscription_id, created_at)
                        VALUES (?, 'refund_credit', ?, ?, ?, ?, 'credit', ?, ?)
                    """, (r_id, cost, item_dict.get("plan_name", ""), account_name, "Ø§Ø³ØªØ±Ø¯Ø§Ø¯ ÙˆØ¬Ù‡ Ù„ØºÙˆ Ø¨Ø³ØªÙ‡ Ø±Ø²Ø±Ùˆ Ø¯Ø± ØµÙ (Ú©Ø§Ù‡Ø´ Ø¨Ø¯Ù‡ÛŒ Ø§Ø¹ØªØ¨Ø§Ø±)", sub_id, now))
                else:
                    cursor.execute("UPDATE resellers SET balance = balance + ?, updated_at=? WHERE id=?", (cost, now, r_id))
                    cursor.execute("""
                        INSERT INTO reseller_transactions (reseller_id, type, amount, plan_name, account_name, description, payment_source, subscription_id, created_at)
                        VALUES (?, 'refund', ?, ?, ?, ?, 'wallet', ?, ?)
                    """, (r_id, cost, item_dict.get("plan_name", ""), account_name, "Ø§Ø³ØªØ±Ø¯Ø§Ø¯ ÙˆØ¬Ù‡ Ù„ØºÙˆ Ø¨Ø³ØªÙ‡ Ø±Ø²Ø±Ùˆ Ø¯Ø± ØµÙ (ÙˆØ§Ø±ÛŒØ² Ø¨Ù‡ Ú©ÛŒÙ Ù¾ÙˆÙ„)", sub_id, now))
            elif not r_id and cost > 0:
                # Ø§Ø³ØªØ±Ø¯Ø§Ø¯ ÙˆØ¬Ù‡ Ø¨Ø±Ø§ÛŒ Ù…Ø´ØªØ±ÛŒØ§Ù† Ù…Ø³ØªÙ‚ÛŒÙ… Ø§Ø¯Ù…ÛŒÙ†
                tg_id = item_dict.get("telegram_id") or sub_dict.get("telegram_id")
                if tg_id:
                    try:
                        self.add_wallet_balance(
                            tg_id,
                            cost,
                            f"Ø§Ø³ØªØ±Ø¯Ø§Ø¯ ÙˆØ¬Ù‡ Ø¨Ø§Ø¨Øª Ù„ØºÙˆ Ø¨Ø³ØªÙ‡ Ø¯Ø± ØµÙ ØªÙ…Ø¯ÛŒØ¯ Ø¨Ø±Ø§ÛŒ Ø§Ø´ØªØ±Ø§Ú© Â«{account_name}Â»",
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

            cursor.execute("UPDATE subscription_queue SET status='cancelled', note='Ù„ØºÙˆ ØªÙˆØ³Ø· Ú©Ø§Ø±Ø¨Ø±/Ù…Ø¯ÛŒØ± Ùˆ Ø§Ø³ØªØ±Ø¯Ø§Ø¯ ÙˆØ¬Ù‡' WHERE id=?", (queue_id,))
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
        Ù…Ø­Ø§Ø³Ø¨Ù‡ Ù‡ÙˆØ´Ù…Ù†Ø¯ Ø§Ø³ØªØ±Ø¯Ø§Ø¯ ÙˆØ¬Ù‡ Ø­Ø°Ù Ù…Ø´ØªØ±ÛŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ Ø·Ø¨Ù‚ ØªÙ†Ø¸ÛŒÙ…Ø§Øª Ù…Ø¯ÛŒØ±ÛŒØª:
        - Ø¹Ø¯Ù… ØªØ§Ø«ÛŒØ±Ù¾Ø°ÛŒØ±ÛŒ Ø§Ø² Ù…Ø¨Ù„Øº Ø¨Ø¯Ù‡ÛŒ Ù…Ø´ØªØ±ÛŒ (ØµØ±ÙØ§Ù‹ Ø¨Ø± Ø§Ø³Ø§Ø³ Ù‡Ø²ÛŒÙ†Ù‡ Ø®Ø±ÛŒØ¯ Ù¾Ù„Ù† Ú©Ø³Ø± Ø´Ø¯Ù‡ Ø§Ø² Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡)
        - Ù…Ø­Ø§Ø³Ø¨Ù‡ Ø²Ù…Ø§Ù† Ø¨Ø± Ø§Ø³Ø§Ø³ Ø²Ù…Ø§Ù† Ø³Ø§Ø®Øª Ø§ÙˆÙ„ÛŒÙ‡ Ù…Ø´ØªØ±ÛŒ ÛŒØ§ Ø¢Ø®Ø±ÛŒÙ† Ø§Ù‚Ø¯Ø§Ù… (Ø·Ø¨Ù‚ ØªÙ†Ø¸ÛŒÙ…Ø§Øª)
        - Ø±Ø¹Ø§ÛŒØª Ø¯Ø±ØµØ¯Ù‡Ø§ÛŒ Ø³ÙØ§Ø±Ø´ÛŒ Ù…Ø¯ÛŒØ±ÛŒØª Ùˆ ØºÛŒØ±ÙØ¹Ø§Ù„â€ŒØ³Ø§Ø²ÛŒ Ø³Ø±Ø§Ø³Ø±ÛŒ ÛŒØ§ Ø¨Ø±Ø§ÛŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ Ø®Ø§Øµ
        - ØªÙÚ©ÛŒÚ© Ù…Ø¨Ø¯Ø£ Ø¨Ø§Ø²Ú¯Ø´Øª ÙˆØ¬Ù‡ (Ú©ÛŒÙ Ù¾ÙˆÙ„ Ù†Ù‚Ø¯ÛŒ ÛŒØ§ Ø§Ø¹ØªØ¨Ø§Ø± Ø®Ø±ÛŒØ¯)
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

        # Ø¯Ø±ÛŒØ§ÙØª ØªÙ†Ø¸ÛŒÙ…Ø§Øª Ø§Ø³ØªØ±Ø¯Ø§Ø¯
        settings = self.get_refund_settings()
        refund_enabled = bool(settings.get("refund_enabled", True))
        disabled_resellers = settings.get("disabled_resellers", [])
        rate_12h = int(settings.get("rate_before_12h", 100))
        rate_24h = int(settings.get("rate_before_24h", 80))
        calc_from_creation = bool(settings.get("calc_from_creation", True))

        is_disallowed = (not refund_enabled) or (reseller_id in disabled_resellers)

        # ØªØ¹ÛŒÛŒÙ† Ù…Ø¨Ø¯Ø£ Ù¾Ø±Ø¯Ø§Ø®Øª (Ú©ÛŒÙ Ù¾ÙˆÙ„ ÛŒØ§ Ø§Ø¹ØªØ¨Ø§Ø±)
        sub_source = str(sub_dict.get("payment_source") or "").lower()
        is_credit_sub = bool(sub_dict.get("is_credit") or (sub_dict.get("credit_debt_amount") or 0) > 0 or sub_source == "credit")

        # Ø¬Ø³ØªØ¬ÙˆÛŒ Ø²Ù…Ø§Ù† Ø¢Ø®Ø±ÛŒÙ† Ø§Ø³ØªØ±Ø¯Ø§Ø¯ Ø«Ø¨Øªâ€ŒØ´Ø¯Ù‡ Ø¨Ø±Ø§ÛŒ Ø§ÛŒÙ† Ø§Ø´ØªØ±Ø§Ú© Ø¯Ø± Ø³Ø·Ù„ Ø²Ø¨Ø§Ù„Ù‡ (Ø¬Ù‡Øª ØªÙÚ©ÛŒÚ© Ø­Ø°Ù Ùˆ Ø¨Ø§Ø²Ú¯Ø±Ø¯Ø§Ù†ÛŒâ€ŒÙ‡Ø§ÛŒ Ù‚Ø¨Ù„ÛŒ Ø§Ø² Ù„ØºÙˆ ØµÙ)
        cursor.execute("""
            SELECT MAX(created_at) FROM reseller_transactions
            WHERE reseller_id = ?
              AND (subscription_id = ? OR account_name = ?)
              AND type IN ('refund', 'refund_credit')
              AND (description LIKE '%Ø³Ø·Ù„ Ø²Ø¨Ø§Ù„Ù‡%' OR description LIKE '%Ø­Ø°Ù Ø§Ø´ØªØ±Ø§Ú©%')
        """, (reseller_id, sub_id, account_name))
        latest_refund_row = cursor.fetchone()
        latest_refund_time = latest_refund_row[0] if latest_refund_row and latest_refund_row[0] else None

        # Ø¬Ø³ØªØ¬ÙˆÛŒ ØªÙ…Ø§Ù… Ø§Ù‚Ø¯Ø§Ù…Ø§Øª Ù…Ø§Ù„ÛŒ Ú©Ø³Ø± Ø´Ø¯Ù‡ Ø§Ø² Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ Ø¨Ø±Ø§ÛŒ Ø§ÛŒÙ† Ø§Ú©Ø§Ù†Øª (ØµØ±ÙØ§Ù‹ Ø§Ù‚Ø¯Ø§Ù…Ø§Øª Ù¾Ø³ Ø§Ø² Ø¢Ø®Ø±ÛŒÙ† Ø§Ø³ØªØ±Ø¯Ø§Ø¯ Ø³Ø·Ù„ Ø²Ø¨Ø§Ù„Ù‡)
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
        latest_time_passed_text = "Ø¨ÛŒØ´ Ø§Ø² Û²Û´ Ø³Ø§Ø¹Øª Ù¾ÛŒØ´"

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
            return f"{h} Ø³Ø§Ø¹Øª Ùˆ {m} Ø¯Ù‚ÛŒÙ‚Ù‡ Ù¾ÛŒØ´" if h > 0 else f"{m} Ø¯Ù‚ÛŒÙ‚Ù‡ Ù¾ÛŒØ´"

        # Ù…Ø­Ø§Ø³Ø¨Ù‡ Ø²Ù…Ø§Ù† Ø¨Ø± Ø§Ø³Ø§Ø³ Ø³Ø§Ø®Øª Ù…Ø´ØªØ±ÛŒ ÛŒØ§ Ø¢Ø®Ø±ÛŒÙ† Ø¨Ø§Ø²Ú¯Ø±Ø¯Ø§Ù†ÛŒ
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
                    tx_src = "credit" if (tx_d.get("type") in ("purchase_credit", "renewal_credit") or "Ø§Ø¹ØªØ¨Ø§Ø±" in str(tx_d.get("description", ""))) else "wallet"

                if tx_src == "credit":
                    has_credit_tx = True
                else:
                    has_wallet_tx = True

                # ØªØ¹ÛŒÛŒÙ† Ø²Ù…Ø§Ù† Ù…Ø¨Ù†Ø§: Ø¨Ø±Ø§ÛŒ Ø®Ø±ÛŒØ¯ Ø§ÙˆÙ„ÛŒÙ‡ Ø·Ø¨Ù‚ ØªÙ†Ø¸ÛŒÙ…Ø§ØªØŒ Ø§Ù…Ø§ Ø¨Ø±Ø§ÛŒ ØªÙ…Ø¯ÛŒØ¯Ù‡Ø§ Ø­ØªÙ…Ø§Ù‹ Ø¨Ø± Ø§Ø³Ø§Ø³ Ø²Ù…Ø§Ù† Ø®ÙˆØ¯ Ø§Ù‚Ø¯Ø§Ù… ØªÙ…Ø¯ÛŒØ¯
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
                    "type_title": "Ø®Ø±ÛŒØ¯ Ø§ÙˆÙ„ÛŒÙ‡" if "purchase" in tx_d["type"] else "ØªÙ…Ø¯ÛŒØ¯ Ø§Ø´ØªØ±Ø§Ú©",
                    "plan_name": tx_d.get("plan_name") or sub_dict.get("plan_name") or "Ù¾Ù„Ù†",
                    "amount": amount,
                    "elapsed_hours": round(elapsed_hours, 1),
                    "time_passed_text": time_passed_str,
                    "refund_percent": percent,
                    "refund_amount": ref_amount,
                    "created_at": tx_d.get("created_at")
                })

        # Ø¯Ø± ØµÙˆØ±ØªÛŒ Ú©Ù‡ ØªØ±Ø§Ú©Ù†Ø´ÛŒ ÛŒØ§ÙØª Ù†Ø´Ø¯ (Ø§Ú©Ø§Ù†Øªâ€ŒÙ‡Ø§ÛŒ Ø¯Ø³ØªÛŒ ÛŒØ§ Ø§ÛŒØ¬Ø§Ø¯ Ù…Ø³ØªÙ‚ÛŒÙ…)
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

            # Ø§Ú¯Ø± Ù‚Ø¨Ù„Ø§Ù‹ Ø§Ø³ØªØ±Ø¯Ø§Ø¯ Ø´Ø¯Ù‡ Ùˆ ØªØ±Ø§Ú©Ù†Ø´ Ø¬Ø¯ÛŒØ¯ÛŒ Ù†Ø¯Ø§Ø±Ø¯ØŒ Ù…Ø¨Ù„Øº Ù¾Ø±Ø¯Ø§Ø®ØªÛŒ Û° Ø§Ø³Øª
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
                "type_title": "Ø®Ø±ÛŒØ¯ Ø§Ø´ØªØ±Ø§Ú© (Ø³ÛŒØ³ØªÙ…ÛŒ)",
                "plan_name": sub_dict.get("plan_name") or "Ù¾Ù„Ù†",
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

        # Ù…Ø¨Ø¯Ø£ Ú©Ù„ÛŒ Ø§Ø³ØªØ±Ø¯Ø§Ø¯
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

    def delete_reseller_subscription(self, reseller_id: int, sub_id: int, reason: str = "Ø³Ø§ÛŒØ±", deleted_by: str = None):
        """Ø­Ø°Ù Ù†Ø±Ù… Ù…Ø´ØªØ±ÛŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ Ø¨Ù‡ Ø³Ø·Ù„ Ø²Ø¨Ø§Ù„Ù‡ Ø¨Ø§ Ø§Ø³ØªØ±Ø¯Ø§Ø¯ ÙˆØ¬Ù‡ Ø¯Ù‚ÛŒÙ‚ Ø¨Ù‡ Ù…Ø¨Ø¯Ø£ Ø§ÙˆÙ„ÛŒÙ‡ (Ú©ÛŒÙ Ù¾ÙˆÙ„ ÛŒØ§ Ø§Ø¹ØªØ¨Ø§Ø±)"""
        refund_info = self.calculate_reseller_refund(reseller_id, sub_id)
        if not refund_info:
            return {"success": False, "error": "Ø§Ø´ØªØ±Ø§Ú© Ù…ÙˆØ±Ø¯ Ù†Ø¸Ø± ÛŒØ§ÙØª Ù†Ø´Ø¯."}

        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            refund_amount = refund_info["refund_amount"]
            refund_percent = refund_info["refund_percent"]
            account_name = refund_info["account_name"]
            actions_count = refund_info.get("actions_count", 1)
            payment_source = refund_info.get("payment_source", "wallet")

            # Û±. Ø¯Ø± ØµÙˆØ±Øª ØªØ¹Ù„Ù‚ Ø§Ø³ØªØ±Ø¯Ø§Ø¯ ÙˆØ¬Ù‡ØŒ Ø¨Ø±Ú¯Ø´Øª Ø¨Ù‡ Ù…Ø¨Ø¯Ø£ Ø§ØµÙ„ÛŒ Ø§Ù†Ø¬Ø§Ù… Ù…ÛŒâ€ŒØ´ÙˆØ¯
            if refund_amount > 0:
                if payment_source == "credit":
                    # Ú©Ø³Ø± Ø¨Ø¯Ù‡ÛŒ Ø§Ø¹ØªØ¨Ø§Ø±ÛŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ (Ø¨Ø§Ø²Ú¯Ø´Øª Ø¨Ù‡ Ø³Ù‚Ù Ø§Ø¹ØªØ¨Ø§Ø±)
                    cursor.execute("UPDATE resellers SET credit_debt = MAX(0, credit_debt - ?), updated_at=? WHERE id=?", (refund_amount, now, reseller_id))
                    desc_text = f"Ø§Ø³ØªØ±Ø¯Ø§Ø¯ ÙˆØ¬Ù‡ {refund_percent}Ùª Ø¨Ø§Ø¨Øª Ø§Ù†ØªÙ‚Ø§Ù„ Ø§Ø´ØªØ±Ø§Ú© Â«{account_name}Â» Ø¨Ù‡ Ø³Ø·Ù„ Ø²Ø¨Ø§Ù„Ù‡ (Ø¨Ø±Ú¯Ø´Øª Ø¨Ù‡ Ø§Ø¹ØªØ¨Ø§Ø± Ø®Ø±ÛŒØ¯ - Ú©Ø§Ù‡Ø´ Ø¨Ø¯Ù‡ÛŒ) - Ø²Ù…Ø§Ù† Ú¯Ø°Ø´ØªÙ‡: {refund_info['time_passed_text']} - Ø¹Ù„Øª: {reason}"
                    cursor.execute("""
                        INSERT INTO reseller_transactions (reseller_id, type, amount, plan_name, account_name, description, payment_source, subscription_id, created_at)
                        VALUES (?, 'refund', ?, 'Ø§Ø³ØªØ±Ø¯Ø§Ø¯ ÙˆØ¬Ù‡ Ø§Ø¹ØªØ¨Ø§Ø±ÛŒ', ?, ?, 'credit', ?, ?)
                    """, (reseller_id, refund_amount, account_name, desc_text, sub_id, now))
                else:
                    # Ø§ÙØ²Ø§ÛŒØ´ Ù…ÙˆØ¬ÙˆØ¯ÛŒ Ú©ÛŒÙ Ù¾ÙˆÙ„ Ù†Ù‚Ø¯ÛŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡
                    cursor.execute("UPDATE resellers SET balance = balance + ?, updated_at=? WHERE id=?", (refund_amount, now, reseller_id))
                    desc_text = f"Ø§Ø³ØªØ±Ø¯Ø§Ø¯ ÙˆØ¬Ù‡ {refund_percent}Ùª Ø¨Ø§Ø¨Øª Ø§Ù†ØªÙ‚Ø§Ù„ Ø§Ø´ØªØ±Ø§Ú© Â«{account_name}Â» Ø¨Ù‡ Ø³Ø·Ù„ Ø²Ø¨Ø§Ù„Ù‡ (ÙˆØ§Ø±ÛŒØ² Ø¨Ù‡ Ú©ÛŒÙ Ù¾ÙˆÙ„) - Ø²Ù…Ø§Ù† Ú¯Ø°Ø´ØªÙ‡: {refund_info['time_passed_text']} - Ø¹Ù„Øª: {reason}"
                    cursor.execute("""
                        INSERT INTO reseller_transactions (reseller_id, type, amount, plan_name, account_name, description, payment_source, subscription_id, created_at)
                        VALUES (?, 'refund', ?, 'Ø§Ø³ØªØ±Ø¯Ø§Ø¯ ÙˆØ¬Ù‡', ?, ?, 'wallet', ?, ?)
                    """, (reseller_id, refund_amount, account_name, desc_text, sub_id, now))

            # Û². Ù„ØºÙˆ Ø®ÙˆØ¯Ú©Ø§Ø± Ø¨Ø³ØªÙ‡â€ŒÙ‡Ø§ÛŒ Ù…Ø¹Ù„Ù‚ Ø¯Ø± ØµÙ ØªÙ…Ø¯ÛŒØ¯ Ø§ÛŒÙ† Ø§Ø´ØªØ±Ø§Ú© ØªØ§ Ø¯Ø± ØµÙ Ù…Ø¹Ù„Ù‚ Ù†Ù…Ø§Ù†Ù†Ø¯ Ùˆ Ù¾Ø³ Ø§Ø² Ø¨Ø§Ø²Ú¯Ø±Ø¯Ø§Ù†ÛŒ Ø¯ÙˆØ¨Ù„Ù‡ Ø§Ø³ØªØ±Ø¯Ø§Ø¯ Ù†Ø´ÙˆÙ†Ø¯
            cursor.execute("""
                UPDATE subscription_queue 
                SET status = 'cancelled', note = 'Ù„ØºÙˆ Ø¨Ù‡ Ø¹Ù„Øª Ø­Ø°Ù Ø§Ø´ØªØ±Ø§Ú© Ùˆ Ø§Ù†ØªÙ‚Ø§Ù„ Ø¨Ù‡ Ø³Ø·Ù„ Ø²Ø¨Ø§Ù„Ù‡'
                WHERE subscription_id = ? AND status = 'pending'
            """, (sub_id,))

            # Û³. Ø­Ø°Ù Ù†Ø±Ù… Ø§Ø´ØªØ±Ø§Ú© Ø§Ø² Ø¬Ø¯ÙˆÙ„ (Ø§Ù†ØªÙ‚Ø§Ù„ Ø¨Ù‡ Ø³Ø·Ù„ Ø²Ø¨Ø§Ù„Ù‡)
            by_user = deleted_by or f"reseller_{reseller_id}"
            cursor.execute("""
                UPDATE subscriptions 
                SET is_deleted = 1, deleted_at = ?, delete_reason = ?, deleted_by = ?, status = 'deleted', updated_at = ?
                WHERE id = ? AND reseller_id = ?
            """, (now, reason, by_user, now, sub_id, reseller_id))
            conn.commit()

            # Ø«Ø¨Øª Ù„Ø§Ú¯ Ø§Ù†ØªÙ‚Ø§Ù„ Ø¨Ù‡ Ø³Ø·Ù„ Ø²Ø¨Ø§Ù„Ù‡ ØªÙˆØ³Ø· Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡
            try:
                self.add_system_log(
                    category="reseller",
                    action="delete",
                    title=f"Ø§Ù†ØªÙ‚Ø§Ù„ Ø§Ø´ØªØ±Ø§Ú© Â«{account_name}Â» Ø¨Ù‡ Ø³Ø·Ù„ Ø²Ø¨Ø§Ù„Ù‡",
                    description=f"Ø§Ø´ØªØ±Ø§Ú© Â«{account_name}Â» ØªÙˆØ³Ø· Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ ({by_user}) Ø¨Ø§ Ø¹Ù„Øª Â«{reason}Â» Ø¨Ù‡ Ø³Ø·Ù„ Ø²Ø¨Ø§Ù„Ù‡ Ù…Ù†ØªÙ‚Ù„ Ú¯Ø±Ø¯ÛŒØ¯." + (f" (Ø§Ø³ØªØ±Ø¯Ø§Ø¯ ÙˆØ¬Ù‡: {refund_amount:,} ØªÙˆÙ…Ø§Ù† Ø¨Ù‡ {payment_source})" if refund_amount > 0 else ""),
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

    # â”€â”€â”€ Ø§Ø³ØªØ±Ø¯Ø§Ø¯ ÙˆØ¬Ù‡ Ùˆ Ø­Ø°Ù Ù‡ÙˆØ´Ù…Ù†Ø¯ Ø§Ø´ØªØ±Ø§Ú© Ù…Ø´ØªØ±ÛŒØ§Ù† Ø¨Ø±Ø§ÛŒ Ù…Ø¯ÛŒØ±Ø§Ù† (Customer Refund & Delete) â”€â”€â”€

    def calculate_customer_refund(self, sub_id: int):
        """
        Ù…Ø­Ø§Ø³Ø¨Ù‡ Ø´Ø±Ø§ÛŒØ· Ùˆ Ø¯Ø±ØµØ¯ Ø§Ø³ØªØ±Ø¯Ø§Ø¯ ÙˆØ¬Ù‡ Ø­Ø°Ù Ø§Ø´ØªØ±Ø§Ú© Ù…Ø´ØªØ±ÛŒ ØªÙˆØ³Ø· Ù…Ø¯ÛŒØ±Ø§Ù† (Ø´Ø§Ù…Ù„ Ø®Ø±ÛŒØ¯ Ùˆ Ú©Ù„ÛŒÙ‡ ØªÙ…Ø¯ÛŒØ¯Ù‡Ø§):
        - Ù‡Ø± Ø§Ù‚Ø¯Ø§Ù… Ú©Ù…ØªØ± Ø§Ø² Û±Û² Ø³Ø§Ø¹Øª Ù¾ÛŒØ´: Û±Û°Û°Ùª Ù…Ø¨Ù„Øº
        - Ù‡Ø± Ø§Ù‚Ø¯Ø§Ù… Ø¨ÛŒÙ† Û±Û² ØªØ§ Û²Û´ Ø³Ø§Ø¹Øª Ù¾ÛŒØ´: Û¸Û°Ùª Ù…Ø¨Ù„Øº
        - Ù‡Ø± Ø§Ù‚Ø¯Ø§Ù… Ø¨ÛŒØ´ Ø§Ø² Û²Û´ Ø³Ø§Ø¹Øª Ù¾ÛŒØ´: Û°Ùª Ù…Ø¨Ù„Øº
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM subscriptions WHERE id=?", (sub_id,))
        sub = cursor.fetchone()
        if not sub:
            conn.close()
            return None

        account_name = sub["account_name"] or "Ø¨Ø¯ÙˆÙ† Ù†Ø§Ù…"
        user_id = sub["telegram_id"] if ("telegram_id" in sub.keys() and sub["telegram_id"]) else None
        now_dt = get_now_naive()

        if account_name and account_name != "Ø¨Ø¯ÙˆÙ† Ù†Ø§Ù…":
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
        latest_time_passed_text = "Ø¨ÛŒØ´ Ø§Ø² Û²Û´ Ø³Ø§Ø¹Øª Ù¾ÛŒØ´"

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
            return f"{h} Ø³Ø§Ø¹Øª Ùˆ {m} Ø¯Ù‚ÛŒÙ‚Ù‡ Ù¾ÛŒØ´" if h > 0 else f"{m} Ø¯Ù‚ÛŒÙ‚Ù‡ Ù¾ÛŒØ´"

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
                    "type_title": "ØªÙ…Ø¯ÛŒØ¯ Ø§Ø´ØªØ±Ø§Ú©" if is_renewal else "Ø®Ø±ÛŒØ¯ Ø§ÙˆÙ„ÛŒÙ‡",
                    "plan_name": tx_d.get("plan_name") or sub["plan_name"] or "Ù¾Ù„Ù†",
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
                "type_title": "Ø®Ø±ÛŒØ¯ Ø§ÙˆÙ„ÛŒÙ‡ (Ø«Ø¨Øª Ø³ÛŒØ³ØªÙ…ÛŒ)",
                "plan_name": sub["plan_name"] or "Ù¾Ù„Ù†",
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

    def delete_customer_subscription(self, sub_id: int, refund_to_customer: bool = True, admin_name: str = "Ù…Ø¯ÛŒØ±", reason: str = "Ø³Ø§ÛŒØ±"):
        """Ø­Ø°Ù Ù†Ø±Ù… Ù…Ø´ØªØ±ÛŒ ØªÙˆØ³Ø· Ù…Ø¯ÛŒØ± Ø¨Ù‡ Ø³Ø·Ù„ Ø²Ø¨Ø§Ù„Ù‡ Ø¨Ø§ Ù‚Ø§Ø¨Ù„ÛŒØª Ø§Ø³ØªØ±Ø¯Ø§Ø¯ Ù…Ø³ØªÙ‚ÛŒÙ… ÙˆØ¬Ù‡ Ø¨Ù‡ Ú©ÛŒÙ Ù¾ÙˆÙ„ Ú©Ø§Ø±Ø¨Ø± ØªÙ„Ú¯Ø±Ø§Ù…"""
        refund_info = self.calculate_customer_refund(sub_id)
        if not refund_info:
            return {"success": False, "error": "Ø§Ø´ØªØ±Ø§Ú© Ù…ÙˆØ±Ø¯ Ù†Ø¸Ø± ÛŒØ§ÙØª Ù†Ø´Ø¯."}

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

            # Û±. Ø¯Ø± ØµÙˆØ±Øª ØªØ§ÛŒÛŒØ¯ Ø§Ø³ØªØ±Ø¯Ø§Ø¯ Ùˆ ÙˆØ¬ÙˆØ¯ Ù…Ø¨Ù„ØºØŒ Ú©ÛŒÙ Ù¾ÙˆÙ„ Ú©Ø§Ø±Ø¨Ø± Ø´Ø§Ø±Ú˜ Ù…ÛŒâ€ŒØ´ÙˆØ¯
            refund_done = False
            if refund_to_customer and refund_amount > 0 and user_id:
                try:
                    desc_text = f"Ø§Ø³ØªØ±Ø¯Ø§Ø¯ ÙˆØ¬Ù‡ {refund_percent}Ùª Ø¨Ø§Ø¨Øª Ø§Ù†ØªÙ‚Ø§Ù„ Ø§Ø´ØªØ±Ø§Ú© Â«{account_name}Â» Ø¨Ù‡ Ø³Ø·Ù„ Ø²Ø¨Ø§Ù„Ù‡ ({actions_count} Ù…Ø±Ø­Ù„Ù‡ ØªØ±Ø§Ú©Ù†Ø´/ØªÙ…Ø¯ÛŒØ¯ - Ø¢Ø®Ø±ÛŒÙ† Ø§Ù‚Ø¯Ø§Ù…: {refund_info['time_passed_text']}) ØªÙˆØ³Ø· {admin_name} - Ø¹Ù„Øª: {reason}"
                    self.add_wallet_balance(
                        user_id,
                        refund_amount,
                        desc_text,
                        tx_type="refund"
                    )
                    refund_done = True
                except Exception as ex:
                    logger.error(f"Error adding refund to wallet for user {user_id}: {ex}")

            # Û². Ù„ØºÙˆ Ø®ÙˆØ¯Ú©Ø§Ø± Ø¨Ø³ØªÙ‡â€ŒÙ‡Ø§ÛŒ Ù…Ø¹Ù„Ù‚ Ø¯Ø± ØµÙ ØªÙ…Ø¯ÛŒØ¯ Ø§ÛŒÙ† Ø§Ø´ØªØ±Ø§Ú©
            cursor.execute("""
                UPDATE subscription_queue 
                SET status = 'cancelled', note = 'Ù„ØºÙˆ Ø¨Ù‡ Ø¹Ù„Øª Ø­Ø°Ù Ø§Ø´ØªØ±Ø§Ú© Ùˆ Ø§Ù†ØªÙ‚Ø§Ù„ Ø¨Ù‡ Ø³Ø·Ù„ Ø²Ø¨Ø§Ù„Ù‡'
                WHERE subscription_id = ? AND status = 'pending'
            """, (sub_id,))

            # Û³. Ø­Ø°Ù Ù†Ø±Ù… Ø§Ø´ØªØ±Ø§Ú© Ø§Ø² Ø¯ÛŒØªØ§Ø¨ÛŒØ³ (Ø§Ù†ØªÙ‚Ø§Ù„ Ø¨Ù‡ Ø³Ø·Ù„ Ø²Ø¨Ø§Ù„Ù‡)
            cursor.execute("""
                UPDATE subscriptions 
                SET is_deleted = 1, deleted_at = ?, delete_reason = ?, deleted_by = ?, status = 'deleted', updated_at = ?
                WHERE id = ?
            """, (now, reason, admin_name, now, sub_id))
            conn.commit()

            # Ø«Ø¨Øª Ù„Ø§Ú¯ Ø§Ù†ØªÙ‚Ø§Ù„ Ø¨Ù‡ Ø³Ø·Ù„ Ø²Ø¨Ø§Ù„Ù‡ ØªÙˆØ³Ø· Ù…Ø¯ÛŒØ±
            try:
                self.add_system_log(
                    category="admin",
                    action="delete",
                    title=f"Ø§Ù†ØªÙ‚Ø§Ù„ Ø§Ø´ØªØ±Ø§Ú© Â«{account_name}Â» Ø¨Ù‡ Ø³Ø·Ù„ Ø²Ø¨Ø§Ù„Ù‡",
                    description=f"Ø§Ø´ØªØ±Ø§Ú© Â«{account_name}Â» ØªÙˆØ³Ø· {admin_name} Ø¨Ø§ Ø¹Ù„Øª Â«{reason}Â» Ø¨Ù‡ Ø³Ø·Ù„ Ø²Ø¨Ø§Ù„Ù‡ Ù…Ù†ØªÙ‚Ù„ Ú¯Ø±Ø¯ÛŒØ¯." + (f" (Ø§Ø³ØªØ±Ø¯Ø§Ø¯ ÙˆØ¬Ù‡: {refund_amount:,} ØªÙˆÙ…Ø§Ù† Ø¨Ù‡ Ú©ÛŒÙ Ù¾ÙˆÙ„ Ú©Ø§Ø±Ø¨Ø±)" if (refund_done and refund_amount > 0) else ""),
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
        """Ø¯Ø±ÛŒØ§ÙØª Ù„ÛŒØ³Øª Ø§Ø´ØªØ±Ø§Ú©â€ŒÙ‡Ø§ÛŒ Ù…ÙˆØ¬ÙˆØ¯ Ø¯Ø± Ø³Ø·Ù„ Ø²Ø¨Ø§Ù„Ù‡ Ø¨Ø§ Ù¾Ø´ØªÛŒØ¨Ø§Ù†ÛŒ Ø§Ø² Ø§Ù†ÙˆØ§Ø¹ Ù…Ø±ØªØ¨â€ŒØ³Ø§Ø²ÛŒ Ùˆ Ù…Ø­Ø§Ø³Ø¨Ù‡ Ù…Ù‡Ù„Øª Û· Ø±ÙˆØ²Ù‡"""
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
        """Ø¨Ø§Ø²Ú¯Ø±Ø¯Ø§Ù†ÛŒ Ø§Ø´ØªØ±Ø§Ú© Ø§Ø² Ø³Ø·Ù„ Ø²Ø¨Ø§Ù„Ù‡ Ø¨Ù‡ Ù„ÛŒØ³Øª ÙØ¹Ø§Ù„ØŒ Ø¨Ù‡â€ŒØ±ÙˆØ²Ø±Ø³Ø§Ù†ÛŒ Ù…Ø´Ø®ØµØ§Øª Ùˆ Ú©Ø³Ø± Ù‡Ø²ÛŒÙ†Ù‡ Ø¯Ø± ØµÙˆØ±Øª Ø¨Ø§Ø²Ú¯Ø±Ø¯Ø§Ù†ÛŒ ØªÙˆØ³Ø· Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("SELECT * FROM subscriptions WHERE id = ? AND is_deleted = 1", (sub_id,))
            sub = cursor.fetchone()
            if not sub:
                return {"success": False, "error": "Ø§Ø´ØªØ±Ø§Ú© Ø¯Ø± Ø³Ø·Ù„ Ø²Ø¨Ø§Ù„Ù‡ ÛŒØ§ÙØª Ù†Ø´Ø¯."}

            sub_dict = dict(sub)
            account_name = sub_dict.get("account_name", "Ø¨Ø¯ÙˆÙ† Ù†Ø§Ù…")
            chosen_source = "wallet"

            # Ø§Ú¯Ø± Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ Ø¨Ø§Ø²Ú¯Ø±Ø¯Ø§Ù†ÛŒ Ù…ÛŒâ€ŒÚ©Ù†Ø¯ Ùˆ Ù‡Ø²ÛŒÙ†Ù‡ Ø¯Ø§Ø±Ø¯ØŒ Ú©Ø³Ø± Ø§Ø² Ú©ÛŒÙ Ù¾ÙˆÙ„ ÛŒØ§ Ø§Ø¹ØªØ¨Ø§Ø±
            if is_reseller and reseller_id and cost > 0:
                deduct_res = self.deduct_reseller_balance(
                    reseller_id=reseller_id,
                    amount=cost,
                    plan_name=sub_dict.get("plan_name") or "Ù¾Ù„Ù† Ø§Ø´ØªØ±Ø§Ú©",
                    account_name=account_name,
                    description=f"Ù‡Ø²ÛŒÙ†Ù‡ Ø¨Ø§Ø²Ú¯Ø±Ø¯Ø§Ù†ÛŒ Ø§Ø´ØªØ±Ø§Ú© Â«{account_name}Â» Ø§Ø² Ø³Ø·Ù„ Ø²Ø¨Ø§Ù„Ù‡",
                    payment_source=payment_source,
                    subscription_id=sub_id
                )
                if not deduct_res.get("success"):
                    return {"success": False, "error": deduct_res.get("error", "Ù…ÙˆØ¬ÙˆØ¯ÛŒ ÛŒØ§ Ø§Ø¹ØªØ¨Ø§Ø± Ú©Ø§ÙÛŒ Ù†ÛŒØ³Øª.")}
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

            # Ø«Ø¨Øª Ù„Ø§Ú¯ Ø¨Ø§Ø²Ú¯Ø±Ø¯Ø§Ù†ÛŒ
            try:
                self.add_system_log(
                    category="admin" if not is_reseller else "reseller",
                    action="restore",
                    title=f"Ø¨Ø§Ø²Ú¯Ø±Ø¯Ø§Ù†ÛŒ Ø§Ø´ØªØ±Ø§Ú© Â«{account_name}Â» Ø§Ø² Ø³Ø·Ù„ Ø²Ø¨Ø§Ù„Ù‡",
                    description=f"Ø§Ø´ØªØ±Ø§Ú© Â«{account_name}Â» Ø§Ø² Ø³Ø·Ù„ Ø²Ø¨Ø§Ù„Ù‡ Ø¨Ø§Ø²ÛŒØ§Ø¨ÛŒ Ùˆ Ù…Ø¬Ø¯Ø¯Ø§Ù‹ Ø¯Ø± Ù¾Ù†Ù„ Ù‡ÛŒØ¯ÛŒÙØ§ÛŒ ÙØ¹Ø§Ù„ Ú¯Ø±Ø¯ÛŒØ¯." + (f" (Ù‡Ø²ÛŒÙ†Ù‡ Ú©Ø³Ø± Ø´Ø¯Ù‡: {cost:,} ØªÙˆÙ…Ø§Ù†)" if cost > 0 else ""),
                    actor_type="admin" if not is_reseller else "reseller",
                    actor_id=reseller_id if is_reseller else None,
                    actor_name=f"Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ #{reseller_id}" if is_reseller else "Ù…Ø¯ÛŒØ± Ø³ÛŒØ³ØªÙ…",
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
        """Ø­Ø°Ù ÙÛŒØ²ÛŒÚ©ÛŒ Ùˆ Ù‚Ø·Ø¹ÛŒ Ø§Ø´ØªØ±Ø§Ú© Ø§Ø² Ø³Ø·Ù„ Ø²Ø¨Ø§Ù„Ù‡ Ø¯ÛŒØªØ§Ø¨ÛŒØ³"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            if reseller_id is not None:
                cursor.execute("SELECT * FROM subscriptions WHERE id = ? AND reseller_id = ? AND is_deleted = 1", (sub_id, reseller_id))
            else:
                cursor.execute("SELECT * FROM subscriptions WHERE id = ? AND is_deleted = 1", (sub_id,))
            row = cursor.fetchone()
            if not row:
                return {"success": False, "error": "Ø§Ø´ØªØ±Ø§Ú© Ø¯Ø± Ø³Ø·Ù„ Ø²Ø¨Ø§Ù„Ù‡ ÛŒØ§ÙØª Ù†Ø´Ø¯."}

            sub_dict = dict(row)
            sub_name = sub_dict.get("account_name") or f"Sub #{sub_id}"
            cursor.execute("DELETE FROM subscriptions WHERE id = ?", (sub_id,))
            conn.commit()

            # Ø«Ø¨Øª Ù„Ø§Ú¯ Ø­Ø°Ù Ø¯Ø§Ø¦Ù…ÛŒ Ø¯Ø³ØªÛŒ
            try:
                self.add_system_log(
                    category="admin" if not reseller_id else "reseller",
                    action="purge",
                    title=f"Ø­Ø°Ù Ø¯Ø§Ø¦Ù…ÛŒ Ø§Ø´ØªØ±Ø§Ú© Â«{sub_name}Â» Ø§Ø² Ø³Ø·Ù„ Ø²Ø¨Ø§Ù„Ù‡",
                    description=f"Ø§Ø´ØªØ±Ø§Ú© Â«{sub_name}Â» Ø¨Ù‡ ØµÙˆØ±Øª Ø¯Ø³ØªÛŒ Ø¨Ø±Ø§ÛŒ Ù‡Ù…ÛŒØ´Ù‡ Ø§Ø² Ø³Ø·Ù„ Ø²Ø¨Ø§Ù„Ù‡ Ø¯ÛŒØªØ§Ø¨ÛŒØ³ Ùˆ Ù¾Ù†Ù„ Ù‡ÛŒØ¯ÛŒÙØ§ÛŒ Ø­Ø°Ù Ú¯Ø±Ø¯ÛŒØ¯.",
                    actor_type="admin" if not reseller_id else "reseller",
                    actor_id=reseller_id,
                    actor_name=f"Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ #{reseller_id}" if reseller_id else "Ù…Ø¯ÛŒØ± Ø³ÛŒØ³ØªÙ…",
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
        """Ù¾Ø§Ú©Ø³Ø§Ø²ÛŒ Ø¯Ø§Ø¦Ù…ÛŒ Ø®ÙˆØ¯Ú©Ø§Ø± Ø§Ø´ØªØ±Ø§Ú©â€ŒÙ‡Ø§ÛŒ Ø³Ù¾Ø±ÛŒâ€ŒØ´Ø¯Ù‡ Ø§Ø² Ù…Ù‡Ù„Øª Û· Ø±ÙˆØ²Ù‡ Ø§Ø² Ø³Ø±ÙˆØ± Ù‡ÛŒØ¯ÛŒÙØ§ÛŒ Ùˆ Ø­Ø°Ù Ù‚Ø·Ø¹ÛŒ Ø§Ø² Ø¯ÛŒØªØ§Ø¨ÛŒØ³"""
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
                    # Ø­Ø°Ù Ù‚Ø·Ø¹ÛŒ Ø§Ø² Ø¯ÛŒØªØ§Ø¨ÛŒØ³ Ø¬Ù‡Øª ØªÙ…ÛŒØ² Ø´Ø¯Ù† Ú©Ø§Ù…Ù„ Ø³Ø·Ù„ Ø²Ø¨Ø§Ù„Ù‡
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

            # Ø«Ø¨Øª Ù„Ø§Ú¯ Ø¯Ù‚ÛŒÙ‚ Ø®ÙˆØ¯Ú©Ø§Ø± Ø³ÛŒØ³ØªÙ… Ø¯Ø± ØµÙˆØ±Øª Ù¾Ø§Ú©Ø³Ø§Ø²ÛŒ Ø§Ø´ØªØ±Ø§Ú©â€ŒÙ‡Ø§
            if purged_count > 0:
                try:
                    self.add_system_log(
                        category="system",
                        action="purge",
                        title=f"Ù¾Ø§Ú©Ø³Ø§Ø²ÛŒ Ø®ÙˆØ¯Ú©Ø§Ø± {purged_count} Ø§Ø´ØªØ±Ø§Ú© Ø§Ø² Ø³Ø±ÙˆØ± Ù‡ÛŒØ¯ÛŒÙØ§ÛŒ",
                        description=f"ØªØ¹Ø¯Ø§Ø¯ {purged_count} Ø§Ø´ØªØ±Ø§Ú© Ø¨Ù‡ Ø¹Ù„Øª Ø§Ù†Ù‚Ø¶Ø§ÛŒ Ù…Ù‡Ù„Øª {restore_window} Ø±ÙˆØ²Ù‡ Ø³Ø·Ù„ Ø²Ø¨Ø§Ù„Ù‡ØŒ Ø¨Ù‡ ØµÙˆØ±Øª Ø®ÙˆØ¯Ú©Ø§Ø± ØªÙˆØ³Ø· Ù¾Ø±Ø¯Ø§Ø²Ø´ Ù¾Ø³â€ŒØ²Ù…ÛŒÙ†Ù‡ Ø³ÛŒØ³ØªÙ… Ø§Ø² Ù¾Ù†Ù„ Ù‡ÛŒØ¯ÛŒÙØ§ÛŒ Ùˆ Ø¯ÛŒØªØ§Ø¨ÛŒØ³ Ø­Ø°Ù Ø¯Ø§Ø¦Ù…ÛŒ Ø´Ø¯Ù†Ø¯.",
                        actor_type="system",
                        actor_name="Ø³ÛŒØ³ØªÙ… (Ù¾Ø§Ú©Ø³Ø§Ø²ÛŒ Ø®ÙˆØ¯Ú©Ø§Ø± Û· Ø±ÙˆØ²Ù‡)",
                        target_type="subscription",
                        target_name=f"{purged_count} Ø§Ø´ØªØ±Ø§Ú© Ø³Ø·Ù„ Ø²Ø¨Ø§Ù„Ù‡",
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

    # â”€â”€â”€ Ù…Ø¯ÛŒØ±ÛŒØª Ù‚Ø¨ÙˆØ¶ Ø¨Ø¯Ù‡ÛŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ú¯Ø§Ù† (Reseller Debts & Invoices) â”€â”€â”€

    def add_reseller_debt(self, reseller_id: int, title: str, amount: int, due_date: str = None, notes: str = None, created_by: str = "admin") -> dict:
        """Ø«Ø¨Øª Ù‚Ø¨Ø¶ Ø¨Ø¯Ù‡ÛŒ Ø¬Ø¯ÛŒØ¯ ÛŒØ§ Ø¨Ø¯Ù‡ÛŒ Ù…Ø¹ÙˆÙ‚ Ù‚Ø¨Ù„ÛŒ Ø¨Ø±Ø§ÛŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ (Ù…Ø¬Ø²Ø§ Ø§Ø² Ø§Ø¹ØªØ¨Ø§Ø± Ø®Ø±ÛŒØ¯)"""
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
        """Ø¯Ø±ÛŒØ§ÙØª Ù„ÛŒØ³Øª Ú©Ù„ÛŒÙ‡ Ù‚Ø¨ÙˆØ¶ Ùˆ Ù…Ø·Ø§Ù„Ø¨Ø§Øª Ø¨Ø¯Ù‡ÛŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ú¯Ø§Ù†"""
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
        """Ø¯Ø±ÛŒØ§ÙØª Ø¬Ø²Ø¦ÛŒØ§Øª ÛŒÚ© Ù‚Ø¨Ø¶ Ø¨Ø¯Ù‡ÛŒ Ù…Ø´Ø®Øµ"""
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
        """Ø¨Ù‡â€ŒØ±ÙˆØ²Ø±Ø³Ø§Ù†ÛŒ ÙˆØ¶Ø¹ÛŒØª ØªØ³ÙˆÛŒÙ‡ ÛŒØ§ Ù¾Ø±Ø¯Ø§Ø®Øª Ø¬Ø²Ø¦ÛŒ Ù‚Ø¨Ø¶ Ø¨Ø¯Ù‡ÛŒ"""
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

    # â”€â”€â”€ Ù…ØªØ¯Ù‡Ø§ÛŒ ØªÚ©Ù…ÛŒÙ„ÛŒ Ø±Ø¨Ø§Øª Ø§Ø®ØªØµØ§ØµÛŒ Ùˆ Ù‡ÙˆØ´ Ù…Ø§Ù„ÛŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ (White-Label & Multi-Bot) â”€â”€â”€

    def get_active_reseller_bots(self) -> list:
        """Ù„ÛŒØ³Øª ØªÙ…Ø§Ù… Ù†Ù…Ø§ÛŒÙ†Ø¯Ú¯Ø§Ù† Ø¯Ø§Ø±Ø§ÛŒ Ø±Ø¨Ø§Øª ÙØ¹Ø§Ù„ Ùˆ ØªÙˆÚ©Ù† Ù…Ø¹ØªØ¨Ø±"""
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
        """Ø¬Ø³ØªØ¬ÙˆÛŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ Ø¨Ø± Ø§Ø³Ø§Ø³ ØªÙˆÚ©Ù† Ø±Ø¨Ø§Øª"""
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
        """Ø¬Ø³ØªØ¬ÙˆÛŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ Ø¨Ø± Ø§Ø³Ø§Ø³ ØªÙ„Ú¯Ø±Ø§Ù… Ø¢ÛŒØ¯ÛŒ"""
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
        """Ø¨Ø±ÙˆØ²Ø±Ø³Ø§Ù†ÛŒ Ù…Ø´Ø®ØµØ§Øª Ùˆ ØªÙ†Ø¸ÛŒÙ…Ø§Øª Ø±Ø¨Ø§Øª Ø§Ø®ØªØµØ§ØµÛŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡"""
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
        """Ø¯Ø±ÛŒØ§ÙØª Ù„ÛŒØ³Øª Ø§Ø¯Ù…ÛŒÙ†â€ŒÙ‡Ø§ÛŒ Ø±Ø¨Ø§Øª ØªÙ„Ú¯Ø±Ø§Ù… Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ Ø¨Ø§ ØªÙÚ©ÛŒÚ© Ù†Ù‚Ø´â€ŒÙ‡Ø§"""
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

            # Ø§Ú¯Ø± Ø§Ø¯Ù…ÛŒÙ†â€ŒÙ‡Ø§ÛŒ Ø°Ø®ÛŒØ±Ù‡â€ŒØ´Ø¯Ù‡ Ø®Ø§Ù„ÛŒ Ø¨ÙˆØ¯ Ø§Ù…Ø§ telegram_id Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ ÙˆØ¬ÙˆØ¯ Ø¯Ø§Ø´Øª
            main_tg = row["telegram_id"]
            if main_tg and not any(str(a.get("telegram_id")) == str(main_tg) for a in admins):
                admins.insert(0, {
                    "telegram_id": main_tg,
                    "role": "main",
                    "title": "Ø§Ø¯Ù…ÛŒÙ† Ø§ØµÙ„ÛŒ (Ù¾Ø±ÙˆÙØ§ÛŒÙ„)"
                })
            return admins
        except Exception as e:
            logger.error(f"Error getting reseller bot admins: {e}")
            return []
        finally:
            conn.close()

    def is_reseller_bot_admin(self, reseller_id: int, telegram_id: int) -> tuple:
        """
        Ø¨Ø±Ø±Ø³ÛŒ Ø¢ÛŒØ§ Ú©Ø§Ø±Ø¨Ø± Ø§Ø¯Ù…ÛŒÙ† Ø±Ø¨Ø§Øª Ø§ÛŒÙ† Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ Ø§Ø³Øª ÛŒØ§ Ø®ÛŒØ±ØŸ
        Ø¨Ø§Ø²Ú¯Ø´Øª: (is_admin: bool, role: str)
        Ù†Ù‚Ø´â€ŒÙ‡Ø§: main (Ø§Ø¯Ù…ÛŒÙ† Ø§ØµÙ„ÛŒ), finance (Ù…Ø¯ÛŒØ± Ù…Ø§Ù„ÛŒ), support (Ù¾Ø´ØªÛŒØ¨Ø§Ù†), sales (ÙØ±ÙˆØ´)
        """
        if not telegram_id or not reseller_id:
            return False, ""

        admins = self.get_reseller_bot_admins(reseller_id)
        tg_str = str(telegram_id).strip()
        for a in admins:
            if str(a.get("telegram_id", "")).strip() == tg_str:
                return True, a.get("role", "main")

        # Ø¨Ø±Ø±Ø³ÛŒ ÙÛŒÙ„Ø¯ Ù…Ø³ØªÙ‚ÛŒÙ… telegram_id Ø¯Ø± resellers
        reseller = self.get_reseller(reseller_id)
        if reseller and reseller.get("telegram_id") and str(reseller["telegram_id"]).strip() == tg_str:
            return True, "main"

        return False, ""

    def is_telegram_user_any_reseller_admin(self, telegram_id: int) -> tuple:
        """Ø¨Ø±Ø±Ø³ÛŒ Ø¢ÛŒØ§ Ú©Ø§Ø±Ø¨Ø± ØªÙ„Ú¯Ø±Ø§Ù… Ø§Ø¯Ù…ÛŒÙ† Ø±Ø¨Ø§Øª Ù‡Ø± Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡â€ŒØ§ÛŒ Ø¯Ø± Ø³ÛŒØ³ØªÙ… Ù‡Ø³Øª ÛŒØ§ Ù†Ù‡"""
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
        """Ø¯Ø±ÛŒØ§ÙØª Ù„ÛŒØ³Øª Ú©Ø§Ø±Ø¨Ø±Ø§Ù† Ø§Ø®ØªØµØ§ØµÛŒ Ø«Ø¨Øªâ€ŒÙ†Ø§Ù… Ø´Ø¯Ù‡ Ø§Ø² Ø±Ø¨Ø§Øª ÛŒØ§ Ú©Ø§Ù†Ø§Ù„ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡"""
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
        """Ù…Ø­Ø§Ø³Ø¨Ù‡ Ø¯Ù‚ÛŒÙ‚ Ø³ÙˆØ¯ Ùˆ ØªØ±Ø§Ø² Ù…Ø§Ù„ÛŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ (Ø³ÙˆØ¯ Ø­Ø§ØµÙ„ Ø§Ø² ØªØ®ÙÛŒÙ Ù‡Ù…Ú©Ø§Ø±ÛŒ Ù†Ø³Ø¨Øª Ø¨Ù‡ ÙØ±ÙˆØ´ Ø®Ø±Ø¯)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            # Û±. Ù…Ø¬Ù…ÙˆØ¹ Ø®Ø±ÛŒØ¯Ù‡Ø§ÛŒ Ø¹Ù…Ø¯Ù‡ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡
            cursor.execute("""
                SELECT COALESCE(SUM(amount), 0) FROM reseller_transactions 
                WHERE reseller_id = ? AND type IN ('purchase', 'purchase_credit', 'renewal', 'renew', 'renew_credit')
            """, (reseller_id,))
            total_wholesale_cost = cursor.fetchone()[0] or 0

            # Û². Ù…Ø¬Ù…ÙˆØ¹ ÙˆØ§Ø±ÛŒØ²ÛŒâ€ŒÙ‡Ø§ / Ø´Ø§Ø±Ú˜ Ú©ÛŒÙâ€ŒÙ¾ÙˆÙ„
            cursor.execute("""
                SELECT COALESCE(SUM(amount), 0) FROM reseller_transactions 
                WHERE reseller_id = ? AND type = 'deposit'
            """, (reseller_id,))
            total_deposited = cursor.fetchone()[0] or 0

            # Û³. ØªØ®ÙÛŒÙ Ùˆ Ù…ÙˆØ¬ÙˆØ¯ÛŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡
            cursor.execute("SELECT discount_percent, balance, name, username FROM resellers WHERE id = ?", (reseller_id,))
            r_info = cursor.fetchone()
            discount_pct = r_info["discount_percent"] if (r_info and r_info["discount_percent"] is not None) else 20
            current_balance = r_info["balance"] if r_info else 0
            reseller_name = r_info["name"] if r_info else "Ù‡Ù…Ú©Ø§Ø±"
            reseller_uname = r_info["username"] if r_info else None

            # Û´. Ù…Ø­Ø§Ø³Ø¨Ù‡ Ø³ÙˆØ¯ Ùˆ Ø§Ø±Ø²Ø´ Ø±ÛŒØ§Ù„ÛŒ ÙØ±ÙˆØ´ (Ø¨Ø± Ø§Ø³Ø§Ø³ Ø­Ø§Ø´ÛŒÙ‡ Ø³ÙˆØ¯ Ø«Ø¨Øªâ€ŒØ´Ø¯Ù‡ ÛŒØ§ ØªØ®Ù…ÛŒÙ† ØªØ®ÙÛŒÙ)
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
        """ÛŒØ§ÙØªÙ† Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ Ø¨Ø± Ø§Ø³Ø§Ø³ Ø¯Ø§Ù…Ù†Ù‡ Ø§Ø®ØªØµØ§ØµÛŒ Ù¾Ù†Ù„ ÛŒØ§ Ø¯Ø§Ù…Ù†Ù‡ Ø§Ø®ØªØµØ§ØµÛŒ Ø¢Ù…ÙˆØ²Ø´â€ŒÙ‡Ø§"""
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
        """Ø¨Ø±ÙˆØ²Ø±Ø³Ø§Ù†ÛŒ Ù…Ø´Ø®ØµØ§Øª Ù‡ÙˆÛŒØª Ø¨ØµØ±ÛŒØŒ Ù„ÙˆÚ¯ÙˆØŒ Ø¯Ø§Ù…Ù†Ù‡ Ùˆ Ø¹Ù†ÙˆØ§Ù† ÙØ±ÙˆØ´Ú¯Ø§Ù‡ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡"""
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
                    # Ø¯Ø§Ù…Ù†Ù‡â€ŒÙ‡Ø§ Ø¯Ø± ØµÙˆØ±Øª Ø®Ø§Ù„ÛŒ Ø¨ÙˆØ¯Ù† Ø¨Ø§ÛŒØ¯ None (Ù…Ø¹Ø§Ø¯Ù„ NULL Ø¯Ø± Ø¯ÛŒØªØ§Ø¨ÛŒØ³) Ø°Ø®ÛŒØ±Ù‡ Ø´ÙˆÙ†Ø¯ ØªØ§ ØªØ¯Ø§Ø®Ù„ Ø§ÛŒÙ†Ø¯Ú©Ø³ ÛŒÙˆÙ†ÛŒÚ© Ø±Ø® Ù†Ø¯Ù‡Ø¯
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
                return {"success": False, "error": "Ø§ÛŒÙ† Ø¯Ø§Ù…Ù†Ù‡ Ù‚Ø¨Ù„Ø§Ù‹ ØªÙˆØ³Ø· Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ Ø¯ÛŒÚ¯Ø±ÛŒ Ø«Ø¨Øª Ø´Ø¯Ù‡ Ø§Ø³Øª."}
            return {"success": False, "error": f"Ø®Ø·Ø§ÛŒ ÛŒÚ©ØªØ§ÛŒÛŒ Ø§Ø·Ù„Ø§Ø¹Ø§Øª: {e}"}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    # â”€â”€â”€ Ù…Ø¯ÛŒØ±ÛŒØª Ú©Ø§Ø±Øªâ€ŒÙ‡Ø§ÛŒ Ø¨Ø§Ù†Ú©ÛŒ Ø§Ø®ØªØµØ§ØµÛŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ (Reseller Cards) â”€â”€â”€

    def get_reseller_cards(self, reseller_id: int) -> list:
        """Ù„ÛŒØ³Øª ØªÙ…Ø§Ù… Ú©Ø§Ø±Øªâ€ŒÙ‡Ø§ÛŒ Ø¨Ø§Ù†Ú©ÛŒ Ø«Ø¨Øªâ€ŒØ´Ø¯Ù‡ ØªÙˆØ³Ø· Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡"""
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
        """Ø¯Ø±ÛŒØ§ÙØª Ú©Ø§Ø±Øª Ø¨Ø§Ù†Ú©ÛŒ ÙØ¹Ø§Ù„ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ Ø¬Ù‡Øª Ù¾Ø±Ø¯Ø§Ø®Øª Ø¨Ø§ Ø±ÙˆØªØ§ØªÙˆØ± Ù‡ÙˆØ´Ù…Ù†Ø¯ Ù¾ÛŒØ´â€ŒÙØ±Ø¶ Ùˆ Ù¾Ø´ØªÛŒØ¨Ø§Ù† Ø¨Ø± Ø§Ø³Ø§Ø³ Ø³Ù‚Ù Ø±ÙˆØ²Ø§Ù†Ù‡"""
        best = self.get_best_active_card(owner_type="reseller", reseller_id=reseller_id, incoming_amount=incoming_amount)
        if best:
            return best

        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            # Ø¨Ø§Ø²Ú¯Ø´Øª Ø¨Ù‡ Ú©Ø§Ø±Øª Ø«Ø¨Øªâ€ŒØ´Ø¯Ù‡ Ø¯Ø± Ù¾Ø±ÙˆÙØ§ÛŒÙ„ Ø§ØµÙ„ÛŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡
            cursor.execute("SELECT card_number, card_holder, bank_name FROM resellers WHERE id = ?", (reseller_id,))
            r_row = cursor.fetchone()
            if r_row and r_row["card_number"]:
                return {
                    "id": 0,
                    "card_number": r_row["card_number"],
                    "card_holder": r_row.get("card_holder") or "",
                    "bank_name": r_row.get("bank_name") or "Ø¨Ø§Ù†Ú©",
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
                          account_number: str = None, notes: str = None,
                          account_type: str = "bank_card", profit_percent: int = 0, assigned_to: str = None) -> dict:
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
                    initial_balance, shaba_number, account_number, notes, account_type, profit_percent, assigned_to
                ) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                reseller_id, card_number.strip(), card_holder.strip(), bank_name.strip(),
                daily_limit, now, def_val, back_val, init_bal, init_bal,
                shaba_number.strip() if shaba_number else None,
                account_number.strip() if account_number else None,
                notes.strip() if notes else None,
                account_type, int(profit_percent or 0), assigned_to.strip() if assigned_to else None
            ))
            card_id = cursor.lastrowid

            # Ø¯Ø± ØµÙˆØ±Øª ÙˆØ¬ÙˆØ¯ Ù…ÙˆØ¬ÙˆØ¯ÛŒ Ø§ÙˆÙ„ÛŒÙ‡ØŒ Ø«Ø¨Øª Ø³Ù†Ø¯ Ø§Ù ØªØªØ§Ø­ÛŒÙ‡ Ø¯Ø± Ø¯Ù ØªØ± Ø±ÛŒØ²ØªØ±Ø§Ú©Ù†Ø´â€ŒÙ‡Ø§
            if init_bal > 0:
                cursor.execute("""
                    INSERT INTO card_transactions (
                        card_id, owner_type, reseller_id, type, amount, balance_after,
                        category, title, description, tracking_code, ref_type, created_by, created_at
                    ) VALUES (?, 'reseller', ?, 'deposit', ?, ?, 'manual_deposit', 'Ø«Ø¨Øª Ù…ÙˆØ¬ÙˆØ¯ÛŒ Ø§ÙˆÙ„ÛŒÙ‡ Ú©Ø§Ø±Øª', 'Ø§ÙØªØªØ§Ø­ Ùˆ ØªØ¹ÛŒÛŒÙ† Ù…ÙˆØ¬ÙˆØ¯ÛŒ Ø§ÙˆÙ„ÛŒÙ‡ Ú©Ø§Ø±Øª Ø¨Ø§Ù†Ú©ÛŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡', 'INIT', 'card_init', 'system', ?)
                """, (card_id, reseller_id, init_bal, init_bal, now))

            conn.commit()
            return {"success": True, "card_id": card_id}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def delete_reseller_card(self, card_id: int, reseller_id: int) -> dict:
        """Ø­Ø°Ù Ú©Ø§Ø±Øª Ø¨Ø§Ù†Ú©ÛŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡"""
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
        """ÙØ¹Ø§Ù„ ÛŒØ§ ØºÛŒØ±ÙØ¹Ø§Ù„ Ú©Ø±Ø¯Ù† Ú©Ø§Ø±Øª Ø¨Ø§Ù†Ú©ÛŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT is_active FROM reseller_cards WHERE id = ? AND reseller_id = ?", (card_id, reseller_id))
            row = cursor.fetchone()
            if not row:
                return {"success": False, "error": "Ú©Ø§Ø±Øª ÛŒØ§ÙØª Ù†Ø´Ø¯."}
            new_st = 0 if row["is_active"] else 1
            cursor.execute("UPDATE reseller_cards SET is_active = ? WHERE id = ? AND reseller_id = ?", (new_st, card_id, reseller_id))
            conn.commit()
            return {"success": True, "is_active": new_st}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    # â”€â”€â”€ Ù…Ø¯ÛŒØ±ÛŒØª Ú©Ø¯Ù‡Ø§ÛŒ ØªØ®ÙÛŒÙ Ø§Ø®ØªØµØ§ØµÛŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ (Reseller Discount Codes) â”€â”€â”€

    def get_reseller_discount_codes(self, reseller_id: int) -> list:
        """Ù„ÛŒØ³Øª Ú©Ø¯Ù‡Ø§ÛŒ ØªØ®ÙÛŒÙ ØªØ¹Ø±ÛŒÙâ€ŒØ´Ø¯Ù‡ ØªÙˆØ³Ø· Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡"""
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
        """Ø§ÛŒØ¬Ø§Ø¯ Ú©Ø¯ ØªØ®ÙÛŒÙ Ø¬Ø¯ÛŒØ¯ Ø¨Ø±Ø§ÛŒ Ù…Ø´ØªØ±ÛŒØ§Ù† Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            clean_code = code.strip().upper()
            cursor.execute("SELECT id FROM reseller_discount_codes WHERE reseller_id = ? AND code = ?", (reseller_id, clean_code))
            if cursor.fetchone():
                return {"success": False, "error": "Ø§ÛŒÙ† Ú©Ø¯ ØªØ®ÙÛŒÙ Ù‚Ø¨Ù„Ø§Ù‹ Ø¨Ø±Ø§ÛŒ Ø´Ù…Ø§ Ø«Ø¨Øª Ø´Ø¯Ù‡ Ø§Ø³Øª."}

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
        """Ø§Ø¹ØªØ¨Ø§Ø±Ø³Ù†Ø¬ÛŒ Ùˆ Ù…Ø­Ø§Ø³Ø¨Ù‡ ØªØ®ÙÛŒÙ Ø¨Ø±Ø§ÛŒ Ù…Ø´ØªØ±ÛŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT * FROM reseller_discount_codes 
                WHERE reseller_id = ? AND code = ? AND is_active = 1
            """, (reseller_id, code.strip().upper()))
            row = cursor.fetchone()
            if not row:
                return {"valid": False, "error": "Ú©Ø¯ ØªØ®ÙÛŒÙ Ù†Ø§Ù…Ø¹ØªØ¨Ø± Ø§Ø³Øª."}

            d = dict(row)
            if d.get("max_uses", 0) > 0 and d.get("used_count", 0) >= d.get("max_uses"):
                return {"valid": False, "error": "Ø¸Ø±ÙÛŒØª Ø§Ø³ØªÙØ§Ø¯Ù‡ Ø§Ø² Ø§ÛŒÙ† Ú©Ø¯ ØªØ®ÙÛŒÙ Ø¨Ù‡ Ù¾Ø§ÛŒØ§Ù† Ø±Ø³ÛŒØ¯Ù‡ Ø§Ø³Øª."}

            if d.get("valid_until"):
                try:
                    exp = datetime.fromisoformat(d["valid_until"])
                    if datetime.now() > exp:
                        return {"valid": False, "error": "Ù…Ù‡Ù„Øª Ø§Ø³ØªÙØ§Ø¯Ù‡ Ø§Ø² Ø§ÛŒÙ† Ú©Ø¯ ØªØ®ÙÛŒÙ Ù…Ù†Ù‚Ø¶ÛŒ Ø´Ø¯Ù‡ Ø§Ø³Øª."}
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
        """Ø­Ø°Ù Ú©Ø¯ ØªØ®ÙÛŒÙ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡"""
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
        """ÙØ¹Ø§Ù„ ÛŒØ§ ØºÛŒØ±ÙØ¹Ø§Ù„ Ú©Ø±Ø¯Ù† Ú©Ø¯ ØªØ®ÙÛŒÙ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT is_active FROM reseller_discount_codes WHERE id = ? AND reseller_id = ?", (code_id, reseller_id))
            row = cursor.fetchone()
            if not row:
                return {"success": False, "error": "Ú©Ø¯ ØªØ®ÙÛŒÙ ÛŒØ§ÙØª Ù†Ø´Ø¯."}
            new_st = 0 if row["is_active"] else 1
            cursor.execute("UPDATE reseller_discount_codes SET is_active = ? WHERE id = ? AND reseller_id = ?", (new_st, code_id, reseller_id))
            conn.commit()
            return {"success": True, "is_active": new_st}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    # â”€â”€â”€ Ù…Ø¯ÛŒØ±ÛŒØª ØªÛŒÙ… Ùˆ Ø²ÛŒØ±Ù…Ø¯ÛŒØ±Ø§Ù† Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ (Reseller Team & Sub-Admins) â”€â”€â”€

    def get_reseller_team_members(self, reseller_id: int) -> list:
        """Ù„ÛŒØ³Øª Ù…Ø¯ÛŒØ±Ø§Ù† Ùˆ Ú©Ø§Ø±Ù…Ù†Ø¯Ø§Ù† Ø²ÛŒØ±Ù…Ø¬Ù…ÙˆØ¹Ù‡ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡"""
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
        """Ù„ÛŒØ³Øª Ú©Ø§Ø¯Ø± Ùˆ Ø²ÛŒØ±Ù…Ø¯ÛŒØ±Ø§Ù† Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ Ø¨Ù‡ Ù‡Ù…Ø±Ø§Ù‡ ÙˆØ¶Ø¹ÛŒØª Ø¢Ù†Ù„Ø§ÛŒÙ†ØŒ Ø¢Ø®Ø±ÛŒÙ† ÙˆØ±ÙˆØ¯ Ùˆ Ù†Ø´Ø³Øªâ€ŒÙ‡Ø§ÛŒ ÙØ¹Ø§Ù„"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT * FROM admin_users WHERE reseller_id = ? ORDER BY id ASC", (reseller_id,))
            members = [dict(r) for r in cursor.fetchall()]
            
            for m in members:
                m_id = m["id"]
                # ÙˆØ¶Ø¹ÛŒØª Ø²Ù†Ø¯Ù‡ Ø¢Ù†Ù„Ø§ÛŒÙ† Ø¨ÙˆØ¯Ù†
                m["is_online"] = self.is_user_online("reseller_subadmin", m_id)
                
                # Ø¯Ø±ÛŒØ§ÙØª Ø³ÙˆØ§Ø¨Ù‚ ÙˆØ±ÙˆØ¯ Ùˆ Ù†Ø´Ø³Øªâ€ŒÙ‡Ø§ÛŒ Ø§ÛŒÙ† Ú©Ø§Ø±Ø¨Ø±
                cursor.execute("""
                    SELECT * FROM login_logs 
                    WHERE user_type = 'reseller_subadmin' AND user_id = ? 
                    ORDER BY id DESC LIMIT 15
                """, (m_id,))
                logs = [dict(r) for r in cursor.fetchall()]
                m["login_logs"] = logs
                
                # ØªÙÚ©ÛŒÚ© Ù†Ø´Ø³Øªâ€ŒÙ‡Ø§ÛŒ ÙØ¹Ø§Ù„ Ø¬Ø§Ø±ÛŒ
                m["active_sessions"] = [l for l in logs if l.get("is_active")]
                m["active_sessions_count"] = len(m["active_sessions"])
                
                # Ø§Ø·Ù„Ø§Ø¹Ø§Øª Ø¢Ø®Ø±ÛŒÙ† Ù†Ø´Ø³Øª / ÙØ¹Ø§Ù„ÛŒØª
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
        """Ø§ÛŒØ¬Ø§Ø¯ Ù…Ø¯ÛŒØ± Ø²ÛŒØ±Ù…Ø¬Ù…ÙˆØ¹Ù‡ Ø¬Ø¯ÛŒØ¯ Ø¨Ø±Ø§ÛŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ Ø¨Ø§ Ù†Ù‚Ø´â€ŒÙ‡Ø§ÛŒ manager2, partner, finance, support"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        clean_pass = password.strip()
        password_hash = self.hash_password(clean_pass)
        try:
            clean_username = username.strip().lower()
            cursor.execute("SELECT id FROM admin_users WHERE LOWER(username) = ?", (clean_username,))
            if cursor.fetchone():
                return {"success": False, "error": "Ø§ÛŒÙ† Ù†Ø§Ù… Ú©Ø§Ø±Ø¨Ø±ÛŒ Ù‚Ø¨Ù„Ø§Ù‹ Ø¯Ø± Ø³ÛŒØ³ØªÙ… Ø«Ø¨Øª Ø´Ø¯Ù‡ Ø§Ø³Øª."}

            permissions = "all"
            if role == "support":
                permissions = "tickets,users,subscriptions"
            elif role == "finance":
                permissions = "payments,transactions,reports"
            elif role in ("partner", "manager2", "manager", "co_admin"):
                permissions = "all"
                if role in ("manager2", "manager", "co_admin"):
                    role = "manager2"
                    share_percent = 0  # Ù…Ø¯ÛŒØ± Ø¯Ùˆ Ø¹Ù†ÙˆØ§Ù† Ø´Ø±ÛŒÚ© Ù†Ø¯Ø§Ø±Ø¯ Ùˆ Ø¯Ø±ØµØ¯ Ø³ÙˆØ¯ Ø´Ø±ÛŒÚ© Ø¨Ø±Ø§ÛŒ Ø¢Ù† ØµÙØ± Ø§Ø³Øª

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
        """ÙˆÛŒØ±Ø§ÛŒØ´ Ù…Ø´Ø®ØµØ§Øª Ù…Ø¯ÛŒØ± Ø²ÛŒØ±Ù…Ø¬Ù…ÙˆØ¹Ù‡ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡"""
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
        """Ø­Ø°Ù Ù…Ø¯ÛŒØ± Ø²ÛŒØ±Ù…Ø¬Ù…ÙˆØ¹Ù‡ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡"""
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
        """ØªØºÛŒÛŒØ± ÙˆØ¶Ø¹ÛŒØª ÙØ¹Ø§Ù„/ØºÛŒØ±ÙØ¹Ø§Ù„ Ù…Ø¯ÛŒØ± Ø²ÛŒØ±Ù…Ø¬Ù…ÙˆØ¹Ù‡ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT is_active FROM admin_users WHERE id = ? AND reseller_id = ?", (member_id, reseller_id))
            row = cursor.fetchone()
            if not row:
                return {"success": False, "error": "Ù…Ø¯ÛŒØ± ÛŒØ§ÙØª Ù†Ø´Ø¯."}
            new_st = 0 if row["is_active"] else 1
            cursor.execute("UPDATE admin_users SET is_active = ? WHERE id = ? AND reseller_id = ?", (new_st, member_id, reseller_id))
            conn.commit()
            return {"success": True, "is_active": new_st}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    # Ø§Ø±Ø³Ø§Ù„ Ù¾ÛŒØ§Ù… Ù‡Ø¯ÙÙ…Ù†Ø¯ Ø¨Ù‡ Ø¯Ø³ØªÙ‡â€ŒÙ‡Ø§ÛŒ Ú©Ø§Ø±Ø¨Ø±ÛŒ (Broadcast Engine)
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

    def get_target_broadcast_users(self, group_type: str = "all") -> list:
        """Ø§Ø³ØªØ®Ø±Ø§Ø¬ Ù„ÛŒØ³Øª ØªÙ„Ú¯Ø±Ø§Ù… Ø¢ÛŒØ¯ÛŒ Ú©Ø§Ø±Ø¨Ø±Ø§Ù† Ø¨Ø± Ø§Ø³Ø§Ø³ ÙÛŒÙ„ØªØ± Ù‡Ø¯ÙÙ…Ù†Ø¯"""
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

    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    # Ù…Ø¯ÛŒØ±ÛŒØª Ú©Ø§Ø±Øªâ€ŒÙ‡Ø§ÛŒ Ø¨Ø§Ù†Ú©ÛŒ Ù…Ù‚ØµØ¯ (Smart Card Rotator)
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

    def get_all_bank_cards(self):
        """Ù„ÛŒØ³Øª ØªÙ…Ø§Ù… Ú©Ø§Ø±Øªâ€ŒÙ‡Ø§ÛŒ Ø¨Ø§Ù†Ú©ÛŒ Ù…Ø¯ÛŒØ±ÛŒØª Ù…Ø±ØªØ¨â€ŒØ´Ø¯Ù‡ Ø¨Ø± Ø§Ø³Ø§Ø³ Ø§ÙˆÙ„ÙˆÛŒØª Ù¾ÛŒØ´â€ŒÙØ±Ø¶ Ùˆ Ù¾Ø´ØªÛŒØ¨Ø§Ù†"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM bank_cards ORDER BY is_default DESC, is_backup DESC, id DESC")
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_active_bank_cards(self):
        """Ù„ÛŒØ³Øª Ú©Ø§Ø±Øªâ€ŒÙ‡Ø§ÛŒ Ø¨Ø§Ù†Ú©ÛŒ ÙØ¹Ø§Ù„ Ù…Ø¯ÛŒØ±ÛŒØª"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM bank_cards WHERE is_active=1 ORDER BY is_default DESC, is_backup DESC, id DESC")
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def add_bank_card(self, card_number: str, card_holder: str, bank_name: str,
                      daily_limit: int = 50000000, is_default: int = 0, is_backup: int = 0,
                      initial_balance: int = 0, shaba_number: str = None,
                      account_number: str = None, notes: str = None,
                      account_type: str = "bank_card", profit_percent: int = 0, assigned_to: str = None):
        """افزودن کارت بانکی ادمین"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            init_bal = max(0, int(initial_balance or 0))
            def_val = 1 if is_default else 0
            back_val = 1 if (is_backup and not def_val) else 0

            # اگر کارت جدÛŒد پÛŒشâ€Œفرض باشد، کارتâ€Œهای قبلÛŒ را از پÛŒشâ€Œفرض خارج میâ€ŒکنÛŒم
            if def_val:
                cursor.execute("UPDATE bank_cards SET is_default = 0")
            elif back_val:
                cursor.execute("UPDATE bank_cards SET is_backup = 0")

            cursor.execute("""
                INSERT INTO bank_cards (
                    card_number, card_holder, bank_name, daily_limit, is_active,
                    created_at, is_default, is_backup, balance, initial_balance,
                    shaba_number, account_number, notes, account_type, profit_percent, assigned_to
                ) VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                card_number.strip(), card_holder.strip(), bank_name.strip(),
                daily_limit, now, def_val, back_val, init_bal, init_bal,
                shaba_number.strip() if shaba_number else None,
                account_number.strip() if account_number else None,
                notes.strip() if notes else None,
                account_type, int(profit_percent or 0), assigned_to.strip() if assigned_to else None
            ))
            card_id = cursor.lastrowid

            # Ø«Ø¨Øª Ø³Ù†Ø¯ Ø§ÙØªØªØ§Ø­ÛŒÙ‡ Ø¯Ø± ØµÙˆØ±Øª ÙˆØ¬ÙˆØ¯ Ù…ÙˆØ¬ÙˆØ¯ÛŒ Ø§ÙˆÙ„ÛŒÙ‡
            if init_bal > 0:
                cursor.execute("""
                    INSERT INTO card_transactions (
                        card_id, owner_type, reseller_id, type, amount, balance_after,
                        category, title, description, tracking_code, ref_type, created_by, created_at
                    ) VALUES (?, 'admin', 0, 'deposit', ?, ?, 'manual_deposit', 'Ø«Ø¨Øª Ù…ÙˆØ¬ÙˆØ¯ÛŒ Ø§ÙˆÙ„ÛŒÙ‡ Ú©Ø§Ø±Øª', 'Ø§ÙØªØªØ§Ø­ Ùˆ ØªØ¹ÛŒÛŒÙ† Ù…ÙˆØ¬ÙˆØ¯ÛŒ Ø§ÙˆÙ„ÛŒÙ‡ Ú©Ø§Ø±Øª Ø¨Ø§Ù†Ú©ÛŒ Ù…Ø¯ÛŒØ±ÛŒØª', 'INIT', 'card_init', 'system', ?)
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
        """ÙØ¹Ø§Ù„ ÛŒØ§ ØºÛŒØ±ÙØ¹Ø§Ù„ Ú©Ø±Ø¯Ù† Ú©Ø§Ø±Øª"""
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
        """Ø­Ø°Ù Ú©Ø§Ø±Øª Ø¨Ø§Ù†Ú©ÛŒ"""
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

    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    # Ø³ÛŒØ³ØªÙ… Ø¬Ø§Ù…Ø¹ Ø­Ø³Ø§Ø¨Ø¯Ø§Ø±ÛŒ Ø´Ù†Ø§ÙˆØ± Ùˆ Ø±ÙˆØªØ§ØªÙˆØ± Ù‡ÙˆØ´Ù…Ù†Ø¯ Ú©Ø§Ø±Øªâ€ŒÙ‡Ø§ (Card Rotator & Ledger)
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

    def get_card_daily_volume(self, card_id: int, owner_type: str = "admin", date_str: str = None,
                               owner_id: int = 0, reseller_id: int = 0, **kwargs) -> int:
        """Ù…Ø­Ø§Ø³Ø¨Ù‡ Ù…Ø¬Ù…ÙˆØ¹ ÙˆØ§Ø±ÛŒØ²ÛŒâ€ŒÙ‡Ø§ÛŒ ÛŒÚ© Ú©Ø§Ø±Øª Ø¯Ø± Ø±ÙˆØ² Ø¬Ø§Ø±ÛŒ Ø¬Ù‡Øª Ú©Ù†ØªØ±Ù„ Ø³Ù‚Ù Ø±ÙˆØ²Ø§Ù†Ù‡"""
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
        Ø§Ù†ØªØ®Ø§Ø¨ Ù‡ÙˆØ´Ù…Ù†Ø¯ Ú©Ø§Ø±Øª Ø¨Ø§Ù†Ú©ÛŒ Ø¬Ù‡Øª Ø§Ø±Ø³Ø§Ù„ Ø¨Ù‡ Ù…Ø´ØªØ±ÛŒ:
        Û±. Ø§ÙˆÙ„ÙˆÛŒØª Ø§ÙˆÙ„: Ú©Ø§Ø±Øª Ù¾ÛŒØ´â€ŒÙØ±Ø¶ (Ø¯Ø± ØµÙˆØ±Øª Ø¯Ø§Ø´ØªÙ† Ø¸Ø±ÙÛŒØª Ø³Ù‚Ù Ø±ÙˆØ²Ø§Ù†Ù‡)
        Û². Ø§ÙˆÙ„ÙˆÛŒØª Ø¯ÙˆÙ…: Ú©Ø§Ø±Øª Ù¾Ø´ØªÛŒØ¨Ø§Ù† (Ø¯Ø± ØµÙˆØ±Øª Ù¾Ø± Ø´Ø¯Ù† Ø³Ù‚Ù Ú©Ø§Ø±Øª Ù¾ÛŒØ´â€ŒÙØ±Ø¶)
        Û³. Ø§ÙˆÙ„ÙˆÛŒØª Ø³ÙˆÙ…: Ø³Ø§ÛŒØ± Ú©Ø§Ø±Øªâ€ŒÙ‡Ø§ÛŒ ÙØ¹Ø§Ù„ Ø¨Ø§ Ø¸Ø±ÙÛŒØª Ø¨Ø§Ù‚ÛŒÙ…Ø§Ù†Ø¯Ù‡
        Û´. Ø¨Ø±Ú¯Ø´Øª Ø¨Ù‡ Ú©Ø§Ø±Øª Ù¾ÛŒØ´â€ŒÙØ±Ø¶/Ù¾Ø´ØªÛŒØ¨Ø§Ù† Ø¯Ø± ØµÙˆØ±Øª Ù¾Ø± Ø¨ÙˆØ¯Ù† ØªÙ…Ø§Ù… Ø³Ù‚Ùâ€ŒÙ‡Ø§
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
                            "bank_name": r_row.get("bank_name") or "Ø¨Ø§Ù†Ú©",
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

            # Û±. Ø¨Ø±Ø±Ø³ÛŒ Ú©Ø§Ø±Øª Ù¾ÛŒØ´â€ŒÙØ±Ø¶
            if default_card:
                def_limit = default_card.get("daily_limit") or 50000000
                if (default_card["daily_volume_today"] + incoming_amount) <= def_limit:
                    return default_card

            # Û². Ø¨Ø±Ø±Ø³ÛŒ Ú©Ø§Ø±Øª Ù¾Ø´ØªÛŒØ¨Ø§Ù† (Ú†ÙˆÙ† Ù¾ÛŒØ´â€ŒÙØ±Ø¶ Ù¾Ø± Ø´Ø¯Ù‡ ÛŒØ§ ØªØ¹Ø±ÛŒÙ Ù†Ø´Ø¯Ù‡)
            if backup_card:
                back_limit = backup_card.get("daily_limit") or 50000000
                if (backup_card["daily_volume_today"] + incoming_amount) <= back_limit:
                    return backup_card

            # Û³. Ø³Ø§ÛŒØ± Ú©Ø§Ø±Øªâ€ŒÙ‡Ø§ÛŒ ÙØ¹Ø§Ù„ Ø¨Ø§ Ø¸Ø±ÙÛŒØª Ø¢Ø²Ø§Ø¯
            if other_eligible_cards:
                return other_eligible_cards[0]

            # Û´. Ø¯Ø± ØµÙˆØ±Øª Ù¾Ø± Ø¨ÙˆØ¯Ù† ØªÙ…Ø§Ù… Ú©Ø§Ø±Øªâ€ŒÙ‡Ø§ØŒ Ú©Ø§Ø±Øª Ù¾ÛŒØ´â€ŒÙØ±Ø¶ ÛŒØ§ Ø§ÙˆÙ„ÛŒÙ† Ú©Ø§Ø±Øª ÙØ¹Ø§Ù„ Ø±Ø§ Ø¨Ø±Ú¯Ø´Øª Ù…ÛŒâ€ŒØ¯Ù‡ÛŒÙ…
            return default_card or backup_card or rows[0]
        finally:
            conn.close()

    def set_card_role(self, card_id: int, role: str, owner_type: str = "admin", reseller_id: int = 0) -> dict:
        """
        ØªÙ†Ø¸ÛŒÙ… Ù†Ù‚Ø´ Ú©Ø§Ø±Øª (Ù¾ÛŒØ´â€ŒÙØ±Ø¶ØŒ Ù¾Ø´ØªÛŒØ¨Ø§Ù†ØŒ Ø¹Ø§Ø¯ÛŒ)
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
        """ÙˆÛŒØ±Ø§ÛŒØ´ Ù…Ø´Ø®ØµØ§ØªØŒ Ø§Ø·Ù„Ø§Ø¹Ø§Øª Ø´Ø¨Ø§ Ùˆ ØªÙ†Ø¸ÛŒÙ… Ù…Ø§Ù†Ø¯Ù‡ Ø­Ø³Ø§Ø¨ Ú©Ø§Ø±Øª"""
        table = "bank_cards" if owner_type == "admin" else "reseller_cards"
        allowed = ["card_number", "card_holder", "bank_name", "daily_limit", "shaba_number", "account_number", "notes", "initial_balance", "balance", "account_type", "profit_percent", "assigned_to"]
        updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
        if not updates:
            return {"success": False, "error": "Ù ÛŒÙ„Ø¯ÛŒ Ø¨Ø±Ø§ÛŒ Ø¨Ù‡â€ŒØ±ÙˆØ²Ø±Ø³Ø§Ù†ÛŒ Ø§Ø±Ø³Ø§Ù„ Ù†Ø´Ø¯Ù‡ Ø§Ø³Øª."}

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
                             reseller_id: int = 0, owner_id: int = None, actor: str = None, **kwargs) -> dict:
        """
        Ø«Ø¨Øª ØªØ±Ø§Ú©Ù†Ø´ ÙˆØ§Ø±ÛŒØ²/Ø¨Ø±Ø¯Ø§Ø´Øª Ùˆ Ø¨Ù‡â€ŒØ±ÙˆØ²Ø±Ø³Ø§Ù†ÛŒ Ø¢Ù†ÛŒ Ù…Ø§Ù†Ø¯Ù‡ Ø­Ø³Ø§Ø¨ Ø´Ù†Ø§ÙˆØ± Ú©Ø§Ø±Øª
        """
        if not card_id or int(card_id) <= 0:
            return {"success": False, "error": "Ø´Ù†Ø§Ø³Ù‡ Ú©Ø§Ø±Øª Ù†Ø§Ù…Ø¹ØªØ¨Ø± Ø§Ø³Øª."}

        effective_reseller_id = owner_id if owner_id is not None else reseller_id
        effective_created_by = actor or created_by or "system"

        table = "bank_cards" if owner_type == "admin" else "reseller_cards"
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        amt = abs(int(amount or 0))

        try:
            cursor.execute(f"SELECT * FROM {table} WHERE id = ?", (card_id,))
            card_row = cursor.fetchone()
            if not card_row:
                return {"success": False, "error": "Ú©Ø§Ø±Øª Ø¨Ø§Ù†Ú©ÛŒ Ù…ÙˆØ±Ø¯ Ù†Ø¸Ø± ÛŒØ§ÙØª Ù†Ø´Ø¯."}

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
                card_id, owner_type, effective_reseller_id or card.get("reseller_id", 0),
                tx_type, amt, new_balance, category,
                title.strip() if title else ("ÙˆØ§Ø±ÛŒØ² Ø¨Ù‡ Ú©Ø§Ø±Øª" if tx_type == "deposit" else "Ø¨Ø±Ø¯Ø§Ø´Øª Ø§Ø² Ú©Ø§Ø±Øª"),
                description.strip() if description else None,
                tracking_code.strip() if tracking_code else None,
                ref_type, str(ref_id) if ref_id else None,
                effective_created_by, now
            ))
            tx_id = cursor.lastrowid

            # Ù‡Ù…Ú¯Ø§Ù…â€ŒØ³Ø§Ø²ÛŒ Ø¨Ø§ Ø³ÛŒØ³ØªÙ… Ø­Ø³Ø§Ø¨Ø¯Ø§Ø±ÛŒ Ú©Ù„ (accounting_records) Ø¨Ø±Ø§ÛŒ Ù…Ø¯ÛŒØ±ÛŒØª
            if owner_type == "admin":
                cat_map = {
                    "salary": "Ø­Ù‚ÙˆÙ‚ Ùˆ Ø¯Ø³ØªÙ…Ø²Ø¯",
                    "server_cost": "Ø³Ø±ÙˆØ± Ùˆ Ø²ÛŒØ±Ø³Ø§Ø®Øª",
                    "bank_fee": "Ú©Ø§Ø±Ù…Ø²Ø¯ Ø¨Ø§Ù†Ú©ÛŒ",
                    "withdrawal": "Ø¨Ø±Ø¯Ø§Ø´Øª Ø³ÙˆØ¯ Ø´Ø®ØµÛŒ",
                    "manual_deposit": "ÙˆØ§Ø±ÛŒØ² Ù…ØªÙØ±Ù‚Ù‡",
                    "other": "Ø³Ø§ÛŒØ± Ù‡Ø²ÛŒÙ†Ù‡â€ŒÙ‡Ø§"
                }
                if tx_type == "withdrawal" and category in cat_map:
                    try:
                        cursor.execute("""
                            INSERT INTO accounting_records 
                            (type, category, title, amount, source, ref_type, ref_id, description, date, created_at)
                            VALUES ('expense', ?, ?, ?, ?, 'card_tx', ?, ?, ?, ?)
                        """, (cat_map[category], title or cat_map[category], amt, f"card_{card_id}", str(tx_id), description or f"Ú©Ø³Ø± Ø§Ø² Ú©Ø§Ø±Øª {card.get('bank_name')} ({card.get('card_number')[-4:]})", now[:10], now))
                    except Exception as e_acc:
                        logger.error(f"Error syncing card withdrawal to accounting: {e_acc}")
                elif tx_type == "deposit" and category == "manual_deposit":
                    try:
                        cursor.execute("""
                            INSERT INTO accounting_records 
                            (type, category, title, amount, source, ref_type, ref_id, description, date, created_at)
                            VALUES ('income', 'ÙˆØ§Ø±ÛŒØ² Ø¯Ø³ØªÛŒ/Ù…ØªÙØ±Ù‚Ù‡', ?, ?, ?, 'card_tx', ?, ?, ?, ?)
                        """, (title or "ÙˆØ§Ø±ÛŒØ² Ø¨Ù‡ Ø­Ø³Ø§Ø¨", amt, f"card_{card_id}", str(tx_id), description, now[:10], now))
                    except Exception as e_acc:
                        logger.error(f"Error syncing card deposit to accounting: {e_acc}")

            conn.commit()
            return {"success": True, "transaction_id": tx_id, "new_balance": new_balance}
        except Exception as e:
            logger.error(f"Error adding card transaction: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def get_card_details_and_transactions(self, card_id: int, owner_type: str = "admin", limit: int = 150,
                                           category: str = None, tx_type: str = None,
                                           owner_id: int = 0, reseller_id: int = 0, **kwargs) -> dict:
        """Ø¯Ø±ÛŒØ§ÙØª Ø¬Ø²ÛŒÛŒØ§Øª Ú©Ø§Ø±ØªØŒ Ù…Ø§Ù†Ø¯Ù‡ Ø´Ù†Ø§ÙˆØ±ØŒ Ú¯Ø±Ø¯Ø´ Ø±ÙˆØ² Ùˆ Ø±ÛŒØ²ØªØ±Ø§Ú©Ù†Ø´â€ŒÙ‡Ø§ÛŒ ØªÙÚ©ÛŒÚ©ÛŒ"""
        table = "bank_cards" if owner_type == "admin" else "reseller_cards"
        effective_reseller_id = owner_id or reseller_id
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            if owner_type == "reseller" and effective_reseller_id:
                cursor.execute(f"SELECT * FROM {table} WHERE id = ? AND reseller_id = ?", (card_id, effective_reseller_id))
            else:
                cursor.execute(f"SELECT * FROM {table} WHERE id = ?", (card_id,))
            card_row = cursor.fetchone()
            if not card_row:
                return {"success": False, "error": "Ú©Ø§Ø±Øª ÛŒØ§ÙØª Ù†Ø´Ø¯."}
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

    def get_cards_financial_summary(self, owner_type: str = "admin", reseller_id: int = 0,
                                    owner_id: int = None, **kwargs) -> dict:
        """Ù…Ø­Ø§Ø³Ø¨Ù‡ Ø´Ø§Ø®Øµâ€ŒÙ‡Ø§ÛŒ Ù…Ø§Ù„ÛŒ Ù…Ø§Ù†Ø¯Ù‡ Ø´Ù†Ø§ÙˆØ±ØŒ Ú©Ù„ ÙˆØ§Ø±ÛŒØ²Ù‡Ø§ØŒ Ù…Ø®Ø§Ø±Ø¬ Ùˆ ØµÙ†Ø¯ÙˆÙ‚ Ù†Ù‚Ø¯"""
        effective_reseller_id = owner_id if owner_id is not None else reseller_id
        table = "bank_cards" if owner_type == "admin" else "reseller_cards"
        owner_filter = "" if owner_type == "admin" else " WHERE reseller_id = ?"
        params = [effective_reseller_id] if owner_type == "reseller" else []
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
            cursor.execute(q_dep, (owner_type, effective_reseller_id, effective_reseller_id, f"{month_str}%"))
            month_deposits = cursor.fetchone()[0] or 0

            q_with = """
                SELECT COALESCE(SUM(amount), 0) FROM card_transactions 
                WHERE owner_type = ? AND (reseller_id = ? OR ? = 0) AND type = 'withdrawal' AND created_at LIKE ?
            """
            cursor.execute(q_with, (owner_type, effective_reseller_id, effective_reseller_id, f"{month_str}%"))
            month_withdrawals = cursor.fetchone()[0] or 0

            q_today = """
                SELECT COALESCE(SUM(amount), 0) FROM card_transactions 
                WHERE owner_type = ? AND (reseller_id = ? OR ? = 0) AND type = 'deposit' AND created_at LIKE ?
            """
            cursor.execute(q_today, (owner_type, effective_reseller_id, effective_reseller_id, f"{today_str}%"))
            today_deposits = cursor.fetchone()[0] or 0

            cursor.execute("""
                SELECT COALESCE(SUM(amount), 0) FROM cash_desk_logs 
                WHERE owner_type = ? AND (owner_id = ? OR ? = 0) AND is_settled = 0 AND type = 'income'
            """, (owner_type, effective_reseller_id, effective_reseller_id))
            unsettled_cash = cursor.fetchone()[0] or 0

            net_floating_balance = total_cards_balance + unsettled_cash

            return {
                "total_cards_balance": total_cards_balance,
                "total_balance": total_cards_balance,
                "total_deposits": month_deposits,
                "total_withdrawals": month_withdrawals,
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
        """Ø«Ø¨Øª Ø¯Ø±ÛŒØ§ÙØª Ù†Ù‚Ø¯ÛŒ Ø¯Ø± ØµÙ†Ø¯ÙˆÙ‚ Ø¬Ù‡Øª ØªØ³ÙˆÛŒÙ‡ Ø¨Ø¹Ø¯ÛŒ Ø¨Ø§ Ù…Ø¯ÛŒØ±ÛŒØª/Ù¾Ù†Ù„"""
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

    def get_cash_desk_logs(self, owner_type: str = "admin", owner_id: int = 0, limit: int = 100,
                           status: str = "all", as_dict: bool = False, **kwargs):
        """Ù„ÛŒØ³Øª Ø¯Ø±ÛŒØ§ÙØªÛŒâ€ŒÙ‡Ø§ÛŒ Ù†Ù‚Ø¯ÛŒ Ùˆ Ù…Ø§Ù†Ø¯Ù‡ ØªØ³ÙˆÛŒÙ‡ Ù†Ø´Ø¯Ù‡ ØµÙ†Ø¯ÙˆÙ‚ Ù†Ù‚Ø¯"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            status_cond = ""
            params = [owner_type, owner_id, owner_id]
            if status == "settled":
                status_cond = " AND is_settled = 1"
            elif status in ("unsettled", "pending"):
                status_cond = " AND is_settled = 0"
            params.append(limit)

            cursor.execute(f"""
                SELECT * FROM cash_desk_logs 
                WHERE owner_type = ? AND (owner_id = ? OR ? = 0){status_cond}
                ORDER BY id DESC LIMIT ?
            """, params)
            raw_logs = [dict(r) for r in cursor.fetchall()]

            logs = []
            for r in raw_logs:
                r_dict = dict(r)
                if "status" not in r_dict:
                    r_dict["status"] = "settled" if r_dict.get("is_settled") else "pending"
                if "source" not in r_dict:
                    r_dict["source"] = r_dict.get("description") or r_dict.get("plan_name") or "Ø¯Ø±ÛŒØ§ÙØª Ù†Ù‚Ø¯ÛŒ"
                logs.append(r_dict)

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

            if as_dict:
                return {
                    "logs": logs,
                    "unsettled_total": unsettled_total,
                    "settled_total": settled_total
                }
            return logs
        except Exception as e:
            logger.error(f"Error getting cash desk logs: {e}")
            return [] if not as_dict else {"logs": [], "unsettled_total": 0, "settled_total": 0}
        finally:
            conn.close()

    def settle_cash_desk_log(self, log_id: int, settled_by: str = None, owner_type: str = "admin",
                            owner_id: int = 0, target_card_id: int = None, note: str = None,
                            actor: str = None) -> dict:
        """ØªØ³ÙˆÛŒÙ‡ Ø³Ù†Ø¯ Ø¯Ø±ÛŒØ§ÙØª Ù†Ù‚Ø¯ÛŒ Ùˆ ÙˆØ§Ø±ÛŒØ² Ø¨Ù‡ Ú©Ø§Ø±Øª Ù…Ù‚ØµØ¯ Ø¯Ø± ØµÙˆØ±Øª Ø§Ù†ØªØ®Ø§Ø¨"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        effective_actor = actor or settled_by or "admin"
        try:
            cursor.execute("SELECT * FROM cash_desk_logs WHERE id = ?", (log_id,))
            row = cursor.fetchone()
            if not row:
                return {"success": False, "error": "Ø³Ù†Ø¯ ØµÙ†Ø¯ÙˆÙ‚ Ù†Ù‚Ø¯ÛŒ ÛŒØ§ÙØª Ù†Ø´Ø¯."}
            log_data = dict(row)
            if log_data.get("is_settled"):
                return {"success": False, "error": "Ø§ÛŒÙ† Ø³Ù†Ø¯ Ù‚Ø¨Ù„Ø§Ù‹ ØªØ³ÙˆÛŒÙ‡ Ø´Ø¯Ù‡ Ø§Ø³Øª."}

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

            # Ø§Ú¯Ø± Ú©Ø§Ø±Øª Ù…Ù‚ØµØ¯ Ø§Ù†ØªØ®Ø§Ø¨ Ø´Ø¯Ù‡ Ø¨Ø§Ø´Ø¯ØŒ Ù…Ø¨Ù„Øº Ù†Ù‚Ø¯ÛŒ Ø¨Ù‡ Ù…ÙˆØ¬ÙˆØ¯ÛŒ Ú©Ø§Ø±Øª ÙˆØ§Ø±ÛŒØ² Ù…ÛŒâ€ŒØ´ÙˆØ¯
            if target_card_id:
                try:
                    self.add_card_transaction(
                        card_id=target_card_id,
                        owner_type=row_owner_type,
                        amount=amount,
                        tx_type="deposit",
                        category="ØªØ³ÙˆÛŒÙ‡ ØµÙ†Ø¯ÙˆÙ‚ Ù†Ù‚Ø¯ÛŒ",
                        title=f"ÙˆØ§Ø±ÛŒØ² ØªØ³ÙˆÛŒÙ‡ Ù†Ù‚Ø¯ÛŒ ({cust_name})" if cust_name else "ÙˆØ§Ø±ÛŒØ² ØªØ³ÙˆÛŒÙ‡ ØµÙ†Ø¯ÙˆÙ‚ Ù†Ù‚Ø¯ÛŒ",
                        description=note or f"ØªØ³ÙˆÛŒÙ‡ Ø³Ù†Ø¯ Ù†Ù‚Ø¯ÛŒ Ø´Ù…Ø§Ø±Ù‡ #{log_id}",
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

    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    # Ø³ÛŒØ³ØªÙ… Ø­Ø³Ø§Ø¨Ø¯Ø§Ø±ÛŒ Ùˆ Ù…Ø¯ÛŒØ±ÛŒØª Ù…Ø§Ù„ÛŒ Ù¾ÛŒØ´Ø±ÙØªÙ‡ (Accounting & Profit/Loss)
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

    def add_accounting_record(self, type: str, category: str, title: str, amount: int,
                              source: str = "manual", ref_type: str = None, ref_id: str = None,
                              description: str = None, date: str = None) -> dict:
        """Ø«Ø¨Øª Ø³Ù†Ø¯ Ø¬Ø¯ÛŒØ¯ Ø¯Ø±Ø¢Ù…Ø¯ ÛŒØ§ Ù‡Ø²ÛŒÙ†Ù‡ Ø¯Ø± Ø­Ø³Ø§Ø¨Ø¯Ø§Ø±ÛŒ"""
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
        """ÙˆÛŒØ±Ø§ÛŒØ´ Ø³Ù†Ø¯ Ø­Ø³Ø§Ø¨Ø¯Ø§Ø±ÛŒ ØªÙˆØ³Ø· Ù…Ø¯ÛŒØ± Ø§Ø±Ø´Ø¯ Ø¨Ø§ Ø«Ø¨Øª Ø±Ù‡Ú¯ÛŒØ±ÛŒ Ú©Ø§Ù…Ù„"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now_iso = get_now_iso()
        try:
            allowed = ["type", "category", "title", "amount", "description", "date"]
            updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
            if not updates:
                return {"success": False, "error": "Ø¯Ø§Ø¯Ù‡â€ŒØ§ÛŒ Ø¨Ø±Ø§ÛŒ Ø¨Ø±ÙˆØ²Ø±Ø³Ø§Ù†ÛŒ Ø§Ø±Ø³Ø§Ù„ Ù†Ø´Ø¯Ù‡ Ø§Ø³Øª."}

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
        """ÙˆÛŒØ±Ø§ÛŒØ´ Ø³Ø§Ø¨Ù‚Ù‡ ØªØ±Ø§Ø² Ø¨Ø¯Ù‡ÛŒ Ù…Ø¯ÛŒØ±/Ø´Ø±ÛŒÚ© ØªÙˆØ³Ø· Ù…Ø¯ÛŒØ± Ø§Ø±Ø´Ø¯ Ø¨Ø§ Ø¨Ø±Ú†Ø³Ø¨ ÙˆÛŒØ±Ø§ÛŒØ´"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now_iso = get_now_iso()
        try:
            allowed = ["total_amount", "share_amount", "debt_amount", "description", "customer_name", "plan_name"]
            updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
            if not updates:
                return {"success": False, "error": "Ø¯Ø§Ø¯Ù‡â€ŒØ§ÛŒ Ø¨Ø±Ø§ÛŒ Ø¨Ø±ÙˆØ²Ø±Ø³Ø§Ù†ÛŒ Ø§Ø±Ø³Ø§Ù„ Ù†Ø´Ø¯Ù‡ Ø§Ø³Øª."}

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
        """Ø­Ø°Ù Ø³Ù†Ø¯ Ø­Ø³Ø§Ø¨Ø¯Ø§Ø±ÛŒ"""
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
        """Ø¯Ø±ÛŒØ§ÙØª Ù„ÛŒØ³Øª Ø§Ø³Ù†Ø§Ø¯ Ø­Ø³Ø§Ø¨Ø¯Ø§Ø±ÛŒ Ø¨Ø§ ÙÛŒÙ„ØªØ±Ù‡Ø§ÛŒ Ù¾ÛŒØ´Ø±ÙØªÙ‡"""
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

    def get_jalali_monthly_accounting(self, year: int = None) -> list:
        "گزارش مالی ماه‌های سال جلالی"
        import jdatetime
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            if not year:
                year = jdatetime.datetime.now().year
            
            # Create a list for the 12 months
            months = [
                {'month': i, 'name': jdatetime.date.j_months_fa[i-1], 'income': 0, 'expense': 0, 'net': 0}
                for i in range(1, 13)
            ]

            # 1. Income from manual records
            cursor.execute("SELECT amount, date FROM accounting_records WHERE type='income'")
            for row in cursor.fetchall():
                try:
                    dt = jdatetime.datetime.strptime(row['date'][:10].replace('/', '-'), '%Y-%m-%d')
                except:
                    continue
                if dt.year == year:
                    months[dt.month - 1]['income'] += row['amount']

            # 2. Income from auto tx
            cursor.execute("SELECT amount, created_at FROM transactions WHERE status IN ('approved', 'completed')")
            for row in cursor.fetchall():
                try:
                    dt = jdatetime.datetime.fromgregorian(datetime=datetime.strptime(row['created_at'][:19], '%Y-%m-%d %H:%M:%S'))
                except:
                    continue
                if dt.year == year:
                    months[dt.month - 1]['income'] += row['amount']

            # 3. Income from reseller deposits
            cursor.execute("SELECT amount, created_at FROM reseller_transactions WHERE type='deposit'")
            for row in cursor.fetchall():
                try:
                    dt = jdatetime.datetime.fromgregorian(datetime=datetime.strptime(row['created_at'][:19], '%Y-%m-%d %H:%M:%S'))
                except:
                    continue
                if dt.year == year:
                    months[dt.month - 1]['income'] += row['amount']
                    
            # 4. Income from partner sales
            cursor.execute("SELECT selling_price as amount, created_at FROM reseller_transactions WHERE type='purchase' AND payment_source='partner'")
            for row in cursor.fetchall():
                try:
                    dt = jdatetime.datetime.fromgregorian(datetime=datetime.strptime(row['created_at'][:19], '%Y-%m-%d %H:%M:%S'))
                except:
                    continue
                if dt.year == year:
                    months[dt.month - 1]['income'] += row['amount']

            # 5. Expenses
            cursor.execute("SELECT amount, date FROM accounting_records WHERE type='expense'")
            for row in cursor.fetchall():
                try:
                    dt = jdatetime.datetime.strptime(row['date'][:10].replace('/', '-'), '%Y-%m-%d')
                except:
                    continue
                if dt.year == year:
                    months[dt.month - 1]['expense'] += row['amount']

            # Calculate Net
            for m in months:
                m['net'] = m['income'] - m['expense']

            return months
        except Exception as e:
            logger.error(f"Error in get_jalali_monthly_accounting: {e}")
            return []
        finally:
            conn.close()

    def get_accounting_partners_data(self) -> dict:
        "اطلاعات شرکا و سهم آن‌ها"
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            # ۱. محاسبه کل درآمد و هزینه‌ها برای تعیین سود خالص کل
            cursor.execute("SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE status IN ('approved', 'completed')")
            auto_tx_income = cursor.fetchone()[0] or 0

            cursor.execute("SELECT COALESCE(SUM(amount), 0) FROM reseller_transactions WHERE type='deposit'")
            auto_reseller_income = cursor.fetchone()[0] or 0

            cursor.execute("SELECT COALESCE(SUM(selling_price), 0) FROM reseller_transactions WHERE type='purchase' AND payment_source='partner'")
            partner_income = cursor.fetchone()[0] or 0

            cursor.execute("SELECT COALESCE(SUM(amount), 0) FROM accounting_records WHERE type='income'")
            manual_income = cursor.fetchone()[0] or 0

            total_income = auto_tx_income + auto_reseller_income + partner_income + manual_income

            cursor.execute("SELECT COALESCE(SUM(amount), 0) FROM accounting_records WHERE type='expense'")
            total_expense = cursor.fetchone()[0] or 0

            net_profit = total_income - total_expense

            # ۲. دریافت کارت‌های صندوق شرکا
            cursor.execute("SELECT * FROM bank_cards WHERE account_type='partner_savings'")
            partner_cards = [dict(r) for r in cursor.fetchall()]

            # دریافت کارت‌های صندوق شرکا از نمایندگان
            cursor.execute("SELECT * FROM reseller_cards WHERE account_type='partner_savings'")
            partner_cards.extend([dict(r) for r in cursor.fetchall()])

            partners_data = []
            total_partner_shares = 0
            total_partner_paid = 0

            for card in partner_cards:
                assigned_to = card.get('assigned_to') or card.get('card_holder') or 'نامشخص'
                profit_pct = card.get('profit_percent') or 0
                
                # محاسبه سهم این شریک
                share_amount = (net_profit * profit_pct) / 100
                total_partner_shares += share_amount
                
                # کل دریافتی این شریک (از طریق این کارت)
                # در بخش کارت‌ها، واریز به کارت نشان‌دهنده پرداخت سود به شریک است (افزایش موجودی صندوق شریک)
                table_name = 'bank_cards' if 'reseller_id' not in card else 'reseller_cards'
                card_id = card['id']
                cursor.execute("SELECT COALESCE(SUM(amount), 0) FROM card_transactions WHERE card_id=? AND type='deposit'", (card_id,))
                total_paid = cursor.fetchone()[0] or 0
                
                # همچنین برداشت از کارت شریک به معنی پس دادن به سیستم است؟
                # معمولاً سود شریک به کارت او واریز می‌شود. پس total_paid همین deposits است.
                total_partner_paid += total_paid

                partners_data.append({
                    'id': card_id,
                    'is_reseller_card': 'reseller_id' in card,
                    'name': assigned_to,
                    'percent': profit_pct,
                    'share_amount': share_amount,
                    'paid_amount': total_paid,
                    'remaining_amount': share_amount - total_paid,
                    'card_number': card.get('card_number')
                })

            return {
                'total_income': total_income,
                'total_expense': total_expense,
                'net_profit': net_profit,
                'total_partner_shares': total_partner_shares,
                'total_partner_paid': total_partner_paid,
                'distributable_profit': net_profit - total_partner_shares,
                'partners': partners_data
            }
        except Exception as e:
            logger.error(f"Error in get_accounting_partners_data: {e}")
            return {}
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

            # درآمدهای شرکا (فروش‌هایی که هزینه کسر نکردند ولی پولش دست شریک است)
            cursor.execute("SELECT COALESCE(SUM(selling_price), 0) FROM reseller_transactions WHERE type='purchase' AND payment_source='partner'")
            partner_income = cursor.fetchone()[0] or 0

            # ۳. درآمدهای دستی ثبت شده در سیستم حسابداری
            cursor.execute("SELECT COALESCE(SUM(amount), 0) FROM accounting_records WHERE type='income'")
            manual_income = cursor.fetchone()[0] or 0

            # کل درآمد ناخالص
            total_income = auto_tx_income + auto_reseller_income + partner_income + manual_income

            # ۴. کل مخارج و هزینه‌ها
            cursor.execute("SELECT COALESCE(SUM(amount), 0) FROM accounting_records WHERE type='expense'")
            total_expense = cursor.fetchone()[0] or 0

            # Ûµ. Ø³ÙˆØ¯ Ø®Ø§Ù„Øµ Ùˆ Ø­Ø§Ø´ÛŒÙ‡ Ø³ÙˆØ¯
            net_profit = total_income - total_expense
            profit_margin = round((net_profit / total_income * 100), 1) if total_income > 0 else 0.0

            # Û¶. Ø¢Ù…Ø§Ø± Ù…Ø§Ù‡ Ø¬Ø§Ø±ÛŒ
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

            # Û·. ØªÙÚ©ÛŒÚ© Ù…Ø®Ø§Ø±Ø¬ Ø¨Ø± Ø§Ø³Ø§Ø³ Ø¯Ø³ØªÙ‡â€ŒØ¨Ù†Ø¯ÛŒ
            cursor.execute("""
                SELECT category, SUM(amount) as total, COUNT(*) as count
                FROM accounting_records
                WHERE type='expense'
                GROUP BY category
                ORDER BY total DESC
            """)
            expense_categories = [dict(r) for r in cursor.fetchall()]

            # Û¸. Ø±ÙˆÙ†Ø¯ Ù…Ø§Ù‡Ø§Ù†Ù‡ Ø³ÙˆØ¯ Ùˆ Ù…Ø®Ø§Ø±Ø¬ (Û¶ Ù…Ø§Ù‡ Ú¯Ø°Ø´ØªÙ‡)
            cursor.execute("""
                SELECT strftime('%Y-%m', date) as month,
                       SUM(CASE WHEN type='income' THEN amount ELSE 0 END) as manual_inc,
                       SUM(CASE WHEN type='expense' THEN amount ELSE 0 END) as exp
                FROM accounting_records
                GROUP BY strftime('%Y-%m', date)
                ORDER BY month DESC LIMIT 6
            """)
            monthly_trend = [dict(r) for r in cursor.fetchall()]

            # Û¹. Ø­Ø³Ø§Ø¨Ø±Ø³ÛŒ Ø§Ø®ØªØµØ§ØµÛŒ Ù…Ø´ØªØ±ÛŒØ§Ù† Ù…Ø³ØªÙ‚ÛŒÙ… Ù…Ø¯ÛŒØ±ÛŒØª
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

            # Û±Û°. Ø¨Ø³ØªÙ‡â€ŒÙ‡Ø§ÛŒ Ù¾ÛŒØ´â€ŒØ®Ø±ÛŒØ¯ Ø§Ø¹ØªØ¨Ø§Ø±ÛŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ú¯Ø§Ù† (Volume Bundles)
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

            # Û±Û±. Ø¨Ø¯Ù‡ÛŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ú¯Ø§Ù†ÛŒ Ú©Ù‡ Ø®Ø±ÛŒØ¯ Ø§Ø¹ØªØ¨Ø§Ø±ÛŒ Ø§Ù†Ø¬Ø§Ù… Ø¯Ø§Ø¯Ù‡â€ŒØ§Ù†Ø¯
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
                # Ø­Ø³Ø§Ø¨Ø±Ø³ÛŒ Ù…Ø´ØªØ±ÛŒØ§Ù† Ù…Ø¯ÛŒØ±ÛŒØª
                "admin_direct_income": admin_direct_income,
                "admin_direct_debt": admin_direct_debt,
                "admin_direct_customers_count": admin_direct_customers_count,
                # Ø¨Ø³ØªÙ‡â€ŒÙ‡Ø§ÛŒ Ù¾ÛŒØ´â€ŒØ®Ø±ÛŒØ¯ Ø§Ø¹ØªØ¨Ø§Ø±ÛŒ
                "reseller_bundles_income": reseller_bundles_income,
                "reseller_bundles_count": reseller_bundles_count,
                # Ø¨Ø¯Ù‡ÛŒâ€ŒÙ‡Ø§ÛŒ Ø§Ø¹ØªØ¨Ø§Ø±ÛŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ú¯Ø§Ù†
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
        """Ù…Ø­Ø§Ø³Ø¨Ù‡ Ø³ÙˆØ¯ Ø´Ø±Ú©Ø§ Ø¯Ø± ØµÙˆØ±Øª ÙˆØ¬ÙˆØ¯ Ø´Ø±Ú©Ø§ Ùˆ Ø³ÙˆØ¯ Ú©Ø³Ø¨ Ø´Ø¯Ù‡ Ø¯Ø± Ø¯ÙˆØ±Ù‡â€ŒÙ‡Ø§ÛŒ Ù…Ø®ØªÙ„Ù"""
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

                # ÙØ±ÙˆØ´ Ù†Ù‚Ø¯ÛŒ Ø¯Ø± Ø¨Ø§Ø²Ù‡
                cursor.execute(f"""
                    SELECT COALESCE(SUM(total_amount), 0), COALESCE(SUM(share_amount), 0), COUNT(*)
                    FROM admin_debts
                    WHERE admin_id = ? AND type = 'cash_sale' {date_cond}
                """, (p_id,))
                sale_row = cursor.fetchone()
                sales_amount = sale_row[0] or 0
                profit_earned = sale_row[1] or 0
                sales_count = sale_row[2] or 0

                # Ú©Ù„ ØªØ³ÙˆÛŒÙ‡â€ŒØ´Ø¯Ù‡ Ø¯Ø± Ø¨Ø§Ø²Ù‡
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
        """Ø¬Ø³ØªØ¬ÙˆÛŒ Ø¬Ø§Ù…Ø¹ Ù…Ø´ØªØ±ÛŒØ§Ù† ÙØ¹Ø§Ù„ØŒ Ù…Ù†Ù‚Ø¶ÛŒ Ùˆ Ø­Ø°Ùâ€ŒØ´Ø¯Ù‡ Ø¯Ø± Ø³Ø·Ù„ Ø²Ø¨Ø§Ù„Ù‡ Ø¬Ù‡Øª Ø§Ù†ØªØ³Ø§Ø¨ Ø±Ø³ÛŒØ¯ Ø¯Ø³ØªÛŒ"""
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
        """Ú¯Ø²Ø§Ø±Ø´Ø§Øª Ùˆ ØªØ­Ù„ÛŒÙ„ Ù‡ÙˆØ´ Ù…Ø§Ù„ÛŒ Ø¨Ù‡ ØªÙÚ©ÛŒÚ© ØªØ¨â€ŒÙ‡Ø§ÛŒ Ù‡Ù…Ù‡ØŒ Ù…Ø´ØªØ±ÛŒØ§Ù† Ù…Ø³ØªÙ‚ÛŒÙ… Ù…Ø¯ÛŒØ±ÛŒØªØŒ Ùˆ Ù†Ù…Ø§ÛŒÙ†Ø¯Ú¯Ø§Ù† Ø¨Ø§ ÙÛŒÙ„ØªØ± Ø²Ù…Ø§Ù†ÛŒ"""
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

            # Û±. ØªØ¨ Ù‡Ù…Ù‡ (All)
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

            # Û². ØªØ¨ Ù…Ø´ØªØ±ÛŒØ§Ù† Ù…Ø¯ÛŒØ±ÛŒØª (Direct Admin Customers)
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

            # Û³. ØªØ¨ Ù†Ù…Ø§ÛŒÙ†Ø¯Ú¯Ø§Ù† (Resellers)
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

    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    # Ø³ÛŒØ³ØªÙ… Ù…Ø¯ÛŒØ±ÛŒØª Ù…Ø¯ÛŒØ±Ø§Ù† Ùˆ Ø³Ø·ÙˆØ­ Ø¯Ø³ØªØ±Ø³ÛŒ (Admin Management & RBAC)
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

    def authenticate_admin(self, username: str, password: str):
        """Ø§Ø­Ø±Ø§Ø² Ù‡ÙˆÛŒØª Ù…Ø¯ÛŒØ±Ø§Ù† Ø§Ø² Ø¬Ø¯ÙˆÙ„ admin_users (Case-Insensitive Ùˆ Ù…Ù‚Ø§ÙˆÙ… Ø¯Ø± Ø¨Ø±Ø§Ø¨Ø± ÙØ§ØµÙ„Ù‡â€ŒÙ‡Ø§)"""
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
        """Ù„ÛŒØ³Øª ØªÙ…Ø§Ù… Ù…Ø¯ÛŒØ±Ø§Ù† Ø³ÛŒØ³ØªÙ…"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM admin_users ORDER BY id ASC")
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_admin_user(self, admin_id: int):
        """Ø¯Ø±ÛŒØ§ÙØª Ø§Ø·Ù„Ø§Ø¹Ø§Øª ÛŒÚ© Ù…Ø¯ÛŒØ±"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM admin_users WHERE id=?", (admin_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    def create_admin_user(self, username: str, password: str, display_name: str,
                          role: str = "super_admin", permissions: str = "*", is_active: bool = True,
                          telegram_id: int = None, phone: str = None, share_percent: int = 0) -> dict:
        """Ø§ÙØ²ÙˆØ¯Ù† Ù…Ø¯ÛŒØ± Ø¬Ø¯ÛŒØ¯ Ø¨Ø§ Ù†Ù‚Ø´ Ùˆ Ø¯Ø³ØªØ±Ø³ÛŒâ€ŒÙ‡Ø§ÛŒ Ù…Ø´Ø®ØµØŒ Ø¢ÛŒØ¯ÛŒ ØªÙ„Ú¯Ø±Ø§Ù…ØŒ Ø´Ù…Ø§Ø±Ù‡ ØªÙ…Ø§Ø³ Ùˆ Ø¯Ø±ØµØ¯ Ø´Ø±Ø§Ú©Øª"""
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
            return {"success": False, "error": "Ø§ÛŒÙ† Ù†Ø§Ù… Ú©Ø§Ø±Ø¨Ø±ÛŒ Ù‚Ø¨Ù„Ø§Ù‹ Ø¨Ø±Ø§ÛŒ Ù…Ø¯ÛŒØ± Ø¯ÛŒÚ¯Ø±ÛŒ Ø«Ø¨Øª Ø´Ø¯Ù‡ Ø§Ø³Øª."}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def update_admin_user(self, admin_id: int, **kwargs) -> dict:
        """ÙˆÛŒØ±Ø§ÛŒØ´ Ø§Ø·Ù„Ø§Ø¹Ø§ØªØŒ Ù†Ù‚Ø´ØŒ Ø¯Ø³ØªØ±Ø³ÛŒâ€ŒÙ‡Ø§ Ùˆ Ø¯Ø±ØµØ¯ Ø´Ø±Ø§Ú©Øª ÛŒÚ© Ù…Ø¯ÛŒØ±"""
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
            return {"success": False, "error": "Ø§ÛŒÙ† Ù†Ø§Ù… Ú©Ø§Ø±Ø¨Ø±ÛŒ ØªÚ©Ø±Ø§Ø±ÛŒ Ø§Ø³Øª."}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def toggle_admin_user(self, admin_id: int) -> dict:
        """ØªØºÛŒÛŒØ± ÙˆØ¶Ø¹ÛŒØª ÙØ¹Ø§Ù„/ØºÛŒØ±ÙØ¹Ø§Ù„ Ù…Ø¯ÛŒØ±"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT is_active FROM admin_users WHERE id=?", (admin_id,))
            row = cursor.fetchone()
            if not row:
                return {"success": False, "error": "Ù…Ø¯ÛŒØ± ÛŒØ§ÙØª Ù†Ø´Ø¯."}
            new_status = 0 if row["is_active"] else 1
            cursor.execute("UPDATE admin_users SET is_active=? WHERE id=?", (new_status, admin_id))
            conn.commit()
            return {"success": True, "is_active": new_status}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def delete_admin_user(self, admin_id: int) -> dict:
        """Ø­Ø°Ù Ù…Ø¯ÛŒØ±"""
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
        """ØªØºÛŒÛŒØ± Ù…Ø´Ø®ØµØ§Øª ÙØ±Ø¯ÛŒØŒ ÛŒÙˆØ²Ø±Ù†ÛŒÙ…ØŒ Ø¢ÛŒØ¯ÛŒ ØªÙ„Ú¯Ø±Ø§Ù…ØŒ Ø´Ù…Ø§Ø±Ù‡ ØªÙ…Ø§Ø³ Ùˆ Ù¾Ø³ÙˆØ±Ø¯ Ù…Ø¯ÛŒØ± ÙØ¹Ø§Ù„"""
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

    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    # Ø­Ø³Ø§Ø¨Ø¯Ø§Ø±ÛŒ Ø¨Ø¯Ù‡ÛŒ Ù…Ø¯ÛŒØ±Ø§Ù† Ùˆ Ø´Ø±Ú©Ø§ÛŒ ØªØ¬Ø§Ø±ÛŒ (Admin & Partner Debts & Ledger)
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

    def record_admin_cash_sale(self, admin_id: int, customer_name: str, plan_name: str, total_amount: int, share_percent: int = 0, created_by: int = None, description: str = "") -> dict:
        """Ø«Ø¨Øª ÙØ±ÙˆØ´ Ù†Ù‚Ø¯ÛŒ ØªÙˆØ³Ø· Ù…Ø¯ÛŒØ±/Ø´Ø±ÛŒÚ©ØŒ Ù…Ø­Ø§Ø³Ø¨Ù‡ Ø¯Ø±ØµØ¯ Ø³Ù‡Ù… Ø´Ø±Ø§Ú©Øª Ùˆ Ø«Ø¨Øª Ø¨Ø¯Ù‡ÛŒ Ø¨Ù‡ Ù…Ø¯ÛŒØ±ÛŒØª"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            # Ø¯Ø±ÛŒØ§ÙØª Ø§Ø·Ù„Ø§Ø¹Ø§Øª Ù…Ø¯ÛŒØ±
            cursor.execute("SELECT username, display_name, role, share_percent, debt_balance FROM admin_users WHERE id=?", (admin_id,))
            admin_row = cursor.fetchone()
            if not admin_row:
                return {"success": False, "error": "Ù…Ø¯ÛŒØ± ÛŒØ§ÙØª Ù†Ø´Ø¯."}

            admin_dict = dict(admin_row)
            username = admin_dict.get("username", f"admin_{admin_id}")
            effective_share_percent = int(share_percent if share_percent is not None else admin_dict.get("share_percent", 0))
            
            # Ù…Ø­Ø§Ø³Ø¨Ù‡ Ø³Ù‡Ù… Ø´Ø±Ø§Ú©Øª Ùˆ Ù…Ø¨Ù„Øº Ø¨Ø¯Ù‡ÛŒ Ø¨Ù‡ Ù…Ø¯ÛŒØ±ÛŒØª
            share_amount = int(total_amount * (effective_share_percent / 100)) if effective_share_percent > 0 else 0
            debt_amount = total_amount - share_amount

            # Ø«Ø¨Øª Ø¯Ø± Ø¬Ø¯ÙˆÙ„ Ù„Ø§Ú¯ Ø¨Ø¯Ù‡ÛŒ
            cursor.execute("""
                INSERT INTO admin_debts (admin_id, admin_username, customer_name, plan_name, total_amount, share_percent, share_amount, debt_amount, type, description, created_by, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'cash_sale', ?, ?, ?)
            """, (admin_id, username, customer_name, plan_name, total_amount, effective_share_percent, share_amount, debt_amount, description, created_by or admin_id, now))

            # Ø§ÙØ²Ø§ÛŒØ´ Ù…Ø§Ù†Ø¯Ù‡ Ø¨Ø¯Ù‡ÛŒ Ù…Ø¯ÛŒØ±
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
        """Ø«Ø¨Øª ØªØ³ÙˆÛŒÙ‡ Ø­Ø³Ø§Ø¨ Ù†Ù‚Ø¯ÛŒ ÛŒØ§ ÙˆØ§Ø±ÛŒØ²ÛŒ Ù…Ø¯ÛŒØ±/Ø´Ø±ÛŒÚ© Ùˆ Ú©Ø§Ù‡Ø´ Ø¨Ø¯Ù‡ÛŒ"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("SELECT username, debt_balance FROM admin_users WHERE id=?", (admin_id,))
            admin_row = cursor.fetchone()
            if not admin_row:
                return {"success": False, "error": "Ù…Ø¯ÛŒØ± ÛŒØ§ÙØª Ù†Ø´Ø¯."}

            admin_dict = dict(admin_row)
            username = admin_dict.get("username", f"admin_{admin_id}")
            current_debt = admin_dict.get("debt_balance") or 0
            settle_amount = int(amount)

            # Ø«Ø¨Øª ØªØ±Ø§Ú©Ù†Ø´ ØªØ³ÙˆÛŒÙ‡ Ø¯Ø± Ø¬Ø¯ÙˆÙ„ Ø¨Ø¯Ù‡ÛŒâ€ŒÙ‡Ø§
            cursor.execute("""
                INSERT INTO admin_debts (admin_id, admin_username, customer_name, plan_name, total_amount, share_percent, share_amount, debt_amount, type, description, created_by, created_at)
                VALUES (?, ?, '-', 'ØªØ³ÙˆÛŒÙ‡ Ø­Ø³Ø§Ø¨ Ø¨Ø¯Ù‡ÛŒ', ?, 0, 0, ?, 'settlement', ?, ?, ?)
            """, (admin_id, username, settle_amount, -settle_amount, description, settled_by, now))

            # Ú©Ø§Ù‡Ø´ Ù…Ø§Ù†Ø¯Ù‡ Ø¨Ø¯Ù‡ÛŒ
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
        """Ø¯Ø±ÛŒØ§ÙØª Ø³ÙˆØ§Ø¨Ù‚ ÙØ±ÙˆØ´â€ŒÙ‡Ø§ÛŒ Ù†Ù‚Ø¯ÛŒØŒ Ø³Ù‡Ù… Ø´Ø±Ø§Ú©Øª Ùˆ ØªØ³ÙˆÛŒÙ‡â€ŒØ­Ø³Ø§Ø¨â€ŒÙ‡Ø§ÛŒ Ù…Ø¯ÛŒØ±Ø§Ù†"""
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
        """Ú¯Ø²Ø§Ø±Ø´ ØªØ±Ø§Ø² Ù…Ø§Ù„ÛŒ Ùˆ Ø®Ù„Ø§ØµÙ‡ ÙˆØ¶Ø¹ÛŒØª ÙØ±ÙˆØ´ Ùˆ Ø¨Ø¯Ù‡ÛŒ Ù…Ø¯ÛŒØ±Ø§Ù† Ùˆ Ø´Ø±Ú©Ø§"""
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
        """ÛŒØ§ÙØªÙ† Ù…Ø´Ø®ØµØ§Øª Ùˆ Ø§Ø·Ù„Ø§Ø¹Ø§Øª ØªÙ…Ø§Ø³ Ù…Ø¯ÛŒØ± ÛŒØ§ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ Ø¨Ø± Ø§Ø³Ø§Ø³ Ù†Ø§Ù… Ú©Ø§Ø±Ø¨Ø±ÛŒ"""
        if not username:
            return None
        clean_user = username.strip().lower()
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            # Û±. Ø¬Ø³ØªØ¬Ùˆ Ø¯Ø± Ø¬Ø¯ÙˆÙ„ Ù…Ø¯ÛŒØ±Ø§Ù† (Admin Users)
            cursor.execute("SELECT id, username, display_name, telegram_id, phone, role FROM admin_users WHERE LOWER(username)=?", (clean_user,))
            row = cursor.fetchone()
            if row:
                admin_row = dict(row)
                return {
                    "user_type": "admin",
                    "user_id": admin_row["id"],
                    "username": admin_row["username"],
                    "name": admin_row.get("display_name") or "Ù…Ø¯ÛŒØ± Ø³ÛŒØ³ØªÙ…",
                    "telegram_id": admin_row.get("telegram_id"),
                    "phone": admin_row.get("phone"),
                    "role": admin_row.get("role", "super_admin")
                }

            # Û². Ø¬Ø³ØªØ¬Ùˆ Ø¯Ø± Ø¬Ø¯ÙˆÙ„ Ù†Ù…Ø§ÛŒÙ†Ø¯Ú¯Ø§Ù† (Resellers)
            cursor.execute("SELECT id, username, name, telegram_id, phone, status FROM resellers WHERE LOWER(username)=?", (clean_user,))
            row = cursor.fetchone()
            if row:
                res_row = dict(row)
                return {
                    "user_type": "reseller",
                    "user_id": res_row["id"],
                    "username": res_row["username"],
                    "name": res_row.get("name") or "Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ ÙØ±ÙˆØ´",
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

    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    # Ù¾Ø±ÙˆÙØ§ÛŒÙ„ Ùˆ Ù…Ø´Ø®ØµØ§Øª Ú©Ø§Ø±Ø¨Ø±ÛŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ (Reseller Profile)
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

    def update_reseller_profile(self, reseller_id: int, **kwargs) -> dict:
        """ÙˆÛŒØ±Ø§ÛŒØ´ Ù…Ø´Ø®ØµØ§Øª ÙØ±Ø¯ÛŒØŒ Ø§Ø·Ù„Ø§Ø¹Ø§Øª ØªÙ…Ø§Ø³ØŒ Ø­Ø³Ø§Ø¨ Ø¨Ø§Ù†Ú©ÛŒ Ùˆ ØªØºÛŒÛŒØ± Ø±Ù…Ø² Ø¹Ø¨ÙˆØ± ØªÙˆØ³Ø· Ø®ÙˆØ¯ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡"""
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
            return {"success": False, "error": "Ø§ÛŒÙ† Ù†Ø§Ù… Ú©Ø§Ø±Ø¨Ø±ÛŒ Ù‚Ø¨Ù„Ø§Ù‹ Ø«Ø¨Øª Ø´Ø¯Ù‡ Ø§Ø³Øª."}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def update_subscription_avatar(self, sub_id: int, custom_avatar: str) -> bool:
        """Ø¨Ø±ÙˆØ²Ø±Ø³Ø§Ù†ÛŒ Ø¢ÙˆØ§ØªØ§Ø± Ø§Ø®ØªØµØ§ØµÛŒ Ø§Ø´ØªØ±Ø§Ú© Ù…Ø´ØªØ±ÛŒ"""
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
        """ÛŒØ§ÙØªÙ† Ø¢ÙˆØ§ØªØ§Ø± Ø§Ø®ØªØµØ§ØµÛŒ Ø¨Ø± Ø§Ø³Ø§Ø³ Ø´Ù†Ø§Ø³Ù‡ Ø§Ø´ØªØ±Ø§Ú©ØŒ Ù†Ø§Ù… Ø§Ú©Ø§Ù†Øª ÛŒØ§ Ø´Ù…Ø§Ø±Ù‡ ØªÙ„ÙÙ†"""
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
        """Ø«Ø¨Øª ÛŒØ§ Ø¨Ø±ÙˆØ²Ø±Ø³Ø§Ù†ÛŒ Ù†Ø´Ø³Øª Ùˆ Ø§Ø·Ù„Ø§Ø¹Ø§Øª Ú©Ù„Ø§ÛŒÙ†Øª Ù…ØªØµÙ„"""
        if not sub_id and not hidify_uuid:
            return None
        now = get_now_iso()
        last_seen = last_seen or now
        parsed = parse_user_agent_details(user_agent, client_ip=ip_address)
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            # Ø¨Ø±Ø±Ø³ÛŒ Ø¢ÛŒØ§ Ù†Ø´Ø³ØªÛŒ Ø¨Ø§ Ù‡Ù…ÛŒÙ† IP Ùˆ Ø¨Ø±Ù†Ø§Ù…Ù‡ Ø¨Ø±Ø§ÛŒ Ø§ÛŒÙ† Ø§Ø´ØªØ±Ø§Ú© ÙˆØ¬ÙˆØ¯ Ø¯Ø§Ø±Ø¯ØŸ
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
        """ÛŒØ§ÙØªÙ† Ø§Ø´ØªØ±Ø§Ú© Ø¨Ø± Ø§Ø³Ø§Ø³ UUID Ù‡ÛŒØ¯ÛŒÙØ§ÛŒ"""
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
        """ÛŒØ§ÙØªÙ† Ø§Ø´ØªØ±Ø§Ú© Ø¨Ø± Ø§Ø³Ø§Ø³ Ø´Ù†Ø§Ø³Ù‡ id"""
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
        """Ø¯Ø±ÛŒØ§ÙØª Ù„ÛŒØ³Øª Ú©Ù„ÛŒÙ‡ Ø§Ø´ØªØ±Ø§Ú©â€ŒÙ‡Ø§"""
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
        """Ø¯Ø±ÛŒØ§ÙØª Ù„ÛŒØ³Øª Ù†Ø´Ø³Øªâ€ŒÙ‡Ø§ÛŒ ÙØ¹Ø§Ù„ Ùˆ ØªØ§Ø±ÛŒØ®Ú†Ù‡ Ø¯Ø³ØªÚ¯Ø§Ù‡â€ŒÙ‡Ø§ÛŒ Ù…ØªØµÙ„ Ø¨Ù‡ Ø§Ø´ØªØ±Ø§Ú©"""
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

    # â”€â”€â”€ Ø§Ø¹ØªØ¨Ø§Ø±Ø³Ù†Ø¬ÛŒ Ú©Ø¯ Ù¾ÛŒÚ¯ÛŒØ±ÛŒ Ùˆ ÙÛŒØ´â€ŒÙ‡Ø§ÛŒ ØªÚ©Ø±Ø§Ø±ÛŒ â”€â”€â”€

    def is_tracking_code_duplicate(self, tracking_code: str, exclude_id: int = None) -> bool:
        """Ø¨Ø±Ø±Ø³ÛŒ Ø¹Ø¯Ù… Ø«Ø¨Øª ØªÚ©Ø±Ø§Ø±ÛŒ Ú©Ø¯ Ù¾ÛŒÚ¯ÛŒØ±ÛŒ ÛŒØ§ Ø´Ù…Ø§Ø±Ù‡ ÙÛŒØ´ Ø¨Ø§Ù†Ú©ÛŒ"""
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

    # â”€â”€â”€ Ø´Ø§Ø±Ú˜ Ø­Ø¬Ù… Ø§Ø¶Ø§ÙÙ‡ Ùˆ Ù¾ÛŒØ´â€ŒØ¨ÛŒÙ†ÛŒ Ø§ØªÙ…Ø§Ù… ØªØ±Ø§ÙÛŒÚ© (Top-up & Depletion Prediction) â”€â”€â”€

    def add_traffic_to_subscription(self, sub_id: int, extra_gb: float) -> dict:
        """Ø§ÙØ²ÙˆØ¯Ù† Ø­Ø¬Ù… Ø§Ø¶Ø§ÙÙ‡ (Top-up) Ø¨Ù‡ Ø³Ù‚Ù Ù…ØµØ±Ù Ø§Ø´ØªØ±Ø§Ú© Ú©Ø§Ø±Ø¨Ø± Ø¨Ø¯ÙˆÙ† ØªØºÛŒÛŒØ± Ù„ÛŒÙ†Ú© Ùˆ UUID"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT * FROM subscriptions WHERE id=?", (sub_id,))
            row = cursor.fetchone()
            if not row:
                return {"success": False, "error": "Ø§Ø´ØªØ±Ø§Ú© ÛŒØ§ÙØª Ù†Ø´Ø¯."}
            sub = dict(row)
            current_limit = float(sub.get("data_limit") or sub.get("traffic_limit") or 0)
            new_limit = current_limit + float(extra_gb)
            cursor.execute("UPDATE subscriptions SET data_limit=? WHERE id=?", (new_limit, sub_id))
            conn.commit()

            # Ø¯Ø± ØµÙˆØ±Øª Ø§ØªØµØ§Ù„ Ø¨Ù‡ Ù‡ÛŒØ¯ÛŒÙØ§ÛŒØŒ Ø³Ù‚Ù Ú©Ø§Ø±Ø¨Ø± Ø¯Ø± Ù‡ÛŒØ¯ÛŒÙØ§ÛŒ Ù†ÛŒØ² Ø¨Ø±ÙˆØ²Ø±Ø³Ø§Ù†ÛŒ Ø´ÙˆØ¯
            hidify_uuid = sub.get("hidify_uuid")
            if hidify_uuid:
                try:
                    from hidify import HidifyClient
                    # Ù‡Ù…Ø§Ù‡Ù†Ú¯ÛŒ Ø¯Ø± ØµÙˆØ±Øª ÙˆØ¬ÙˆØ¯ Ø§ØªØµØ§Ù„
                except Exception:
                    pass

            return {"success": True, "old_limit": current_limit, "new_limit": new_limit, "added_gb": extra_gb}
        except Exception as e:
            logger.error(f"Error adding traffic to subscription: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def calculate_subscription_burn_rate(self, sub: dict) -> dict:
        """Ù…Ø­Ø§Ø³Ø¨Ù‡ Ù†Ø±Ø® Ù…ØµØ±Ù Ø±ÙˆØ²Ø§Ù†Ù‡ Ùˆ Ù¾ÛŒØ´â€ŒØ¨ÛŒÙ†ÛŒ Ù‡ÙˆØ´Ù…Ù†Ø¯ ØªØ§Ø±ÛŒØ® Ø§ØªÙ…Ø§Ù… ØªØ±Ø§ÙÛŒÚ©"""
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

    # â”€â”€â”€ Ø¨Ø³ØªÙ‡â€ŒÙ‡Ø§ÛŒ Ù¾ÛŒØ´â€ŒØ®Ø±ÛŒØ¯ Ø§Ø¹ØªØ¨Ø§Ø±ÛŒ Ø¨Ø§ Ø¨ÙˆÙ†ÙˆØ³ Ø´Ø§Ø±Ú˜ Ø±Ø§ÛŒÚ¯Ø§Ù† Ø¨Ø±Ø§ÛŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ú¯Ø§Ù† (Volume Bundles) â”€â”€â”€

    def get_reseller_credit_bundles(self, active_only: bool = False) -> list:
        """Ù„ÛŒØ³Øª Ø¨Ø³ØªÙ‡â€ŒÙ‡Ø§ÛŒ Ø´Ø§Ø±Ú˜ Ø¹Ù…Ø¯Ù‡ Ø¨Ø§ Ø¯Ø±ØµØ¯ Ø¨ÙˆÙ†ÙˆØ³ Ù‡Ø¯ÛŒÙ‡ Ø¨Ø±Ø§ÛŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ú¯Ø§Ù† Ø§Ø² Ø¯ÛŒØªØ§Ø¨ÛŒØ³"""
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

        # Ø¨Ø§Ø²Ú¯Ø´Øª Ø¨Ù‡ Ø¨Ø³ØªÙ‡â€ŒÙ‡Ø§ÛŒ Ù¾ÛŒØ´â€ŒÙØ±Ø¶ Ø¯Ø± ØµÙˆØ±Øª Ø®Ø§Ù„ÛŒ Ø¨ÙˆØ¯Ù† Ø¬Ø¯ÙˆÙ„ ÛŒØ§ Ø¨Ø±ÙˆØ² Ø®Ø·Ø§
        default_bundles = [
            {"id": "bundle_1m", "title": "Ø¨Ø³ØªÙ‡ Ø§Ø³ØªØ§Ø±ØªØ±", "price": 1000000, "credit": 1050000, "bonus_percent": 5, "badge": "ÛµÙª Ø´Ø§Ø±Ú˜ Ù‡Ø¯ÛŒÙ‡", "color": "info", "description": "Ù…Ù†Ø§Ø³Ø¨ Ø´Ø±ÙˆØ¹ Ù‡Ù…Ú©Ø§Ø±ÛŒ Ùˆ Ø´Ø§Ø±Ú˜ Ø§ÙˆÙ„ÛŒÙ‡", "display_order": 1, "is_active": 1},
            {"id": "bundle_3m", "title": "Ø¨Ø³ØªÙ‡ Ù†Ù‚Ø±Ù‡â€ŒØ§ÛŒ", "price": 3000000, "credit": 3210000, "bonus_percent": 7, "badge": "Û·Ùª Ø´Ø§Ø±Ú˜ Ù‡Ø¯ÛŒÙ‡", "color": "primary", "description": "Ø¨Ø³ØªÙ‡ Ø§Ù‚ØªØµØ§Ø¯ÛŒ Ø¨Ø§ Ø¨ÙˆÙ†ÙˆØ³ Ø´Ø§Ø±Ú˜ ØªØ´ÙˆÛŒÙ‚ÛŒ", "display_order": 2, "is_active": 1},
            {"id": "bundle_5m", "title": "Ø¨Ø³ØªÙ‡ Ø·Ù„Ø§ÛŒÛŒ", "price": 5000000, "credit": 5500000, "bonus_percent": 10, "badge": "Û±Û°Ùª Ø´Ø§Ø±Ú˜ Ù‡Ø¯ÛŒÙ‡", "color": "success", "description": "Ø¨Ø³ØªÙ‡ Ù¾Ø±ÙØ±ÙˆØ´ Ù‡Ù…Ú©Ø§Ø±Ø§Ù† Ø¨Ø§ Û±Û°Ùª Ù‡Ø¯ÛŒÙ‡ Ù†Ù‚Ø¯ÛŒ", "display_order": 3, "is_active": 1},
            {"id": "bundle_10m", "title": "Ø¨Ø³ØªÙ‡ Ø§Ù„Ù…Ø§Ø³ VIP", "price": 10000000, "credit": 11500000, "bonus_percent": 15, "badge": "Û±ÛµÙª Ø´Ø§Ø±Ú˜ ÙˆÛŒÚ˜Ù‡", "color": "warning", "description": "Ø­Ø¯Ø§Ú©Ø«Ø± Ø§Ø¹ØªØ¨Ø§Ø± Ø¨Ø§ Ø¨Ø§Ù„Ø§ØªØ±ÛŒÙ† Ù†Ø±Ø® Ø¨ÙˆÙ†ÙˆØ³ ÙˆÛŒÚ˜Ù‡", "display_order": 4, "is_active": 1},
        ]
        if active_only:
            return [b for b in default_bundles if b.get("is_active", 1)]
        return default_bundles

    def get_reseller_credit_bundle(self, bundle_id: str) -> dict:
        """Ø¯Ø±ÛŒØ§ÙØª Ø§Ø·Ù„Ø§Ø¹Ø§Øª ÛŒÚ© Ø¨Ø³ØªÙ‡ Ù¾ÛŒØ´â€ŒØ®Ø±ÛŒØ¯ Ù†Ù…Ø§ÛŒÙ†Ø¯Ú¯Ø§Ù† Ø¨Ø± Ø§Ø³Ø§Ø³ Ø´Ù†Ø§Ø³Ù‡"""
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
        """Ø°Ø®ÛŒØ±Ù‡ ÛŒØ§ ÙˆÛŒØ±Ø§ÛŒØ´ Ø¨Ø³ØªÙ‡ Ù¾ÛŒØ´â€ŒØ®Ø±ÛŒØ¯ Ù†Ù…Ø§ÛŒÙ†Ø¯Ú¯Ø§Ù† Ø¯Ø± Ø¯ÛŒØªØ§Ø¨ÛŒØ³"""
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
            badge = f"{bonus_percent}Ùª Ø´Ø§Ø±Ú˜ Ù‡Ø¯ÛŒÙ‡" if bonus_percent > 0 else "Ø´Ø§Ø±Ú˜ Ú©ÛŒÙ Ù¾ÙˆÙ„"

        color = str(bundle_data.get("color") or "primary").strip()
        description = str(bundle_data.get("description") or "").strip()

        try:
            display_order = int(bundle_data.get("display_order", 0))
        except (ValueError, TypeError):
            display_order = 0

        is_active = 1 if bundle_data.get("is_active") in (1, "1", True, "true", "on") else 0
        now = get_now_iso()

        if not bundle_id or not title or price <= 0:
            return {"success": False, "error": "Ø´Ù†Ø§Ø³Ù‡ Ø§Ù†Ú¯Ù„ÛŒØ³ÛŒØŒ Ø¹Ù†ÙˆØ§Ù† Ø¨Ø³ØªÙ‡ Ùˆ Ù‚ÛŒÙ…Øª Ù…Ø¹ØªØ¨Ø± Ø§Ù„Ø²Ø§Ù…ÛŒ Ù‡Ø³ØªÙ†Ø¯."}

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
        """Ø­Ø°Ù Ø¨Ø³ØªÙ‡ Ù¾ÛŒØ´â€ŒØ®Ø±ÛŒØ¯ Ù†Ù…Ø§ÛŒÙ†Ø¯Ú¯Ø§Ù† Ø§Ø² Ø¯ÛŒØªØ§Ø¨ÛŒØ³"""
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
        """ØªØºÛŒÛŒØ± ÙˆØ¶Ø¹ÛŒØª ÙØ¹Ø§Ù„/ØºÛŒØ±ÙØ¹Ø§Ù„ Ø¨Ø³ØªÙ‡ Ù¾ÛŒØ´â€ŒØ®Ø±ÛŒØ¯"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("SELECT is_active FROM reseller_bundles WHERE id = ?", (bundle_id,))
            row = cursor.fetchone()
            if not row:
                return {"success": False, "error": "Ø¨Ø³ØªÙ‡ ÛŒØ§ÙØª Ù†Ø´Ø¯."}
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
        """Ø¨Ø§Ø²Ù†Ø´Ø§Ù†ÛŒ Ø¨Ø³ØªÙ‡â€ŒÙ‡Ø§ÛŒ Ù¾ÛŒØ´â€ŒØ®Ø±ÛŒØ¯ Ø¨Ù‡ Û´ Ø¨Ø³ØªÙ‡ Ø§Ø³ØªØ§Ù†Ø¯Ø§Ø±Ø¯ Ù¾ÛŒØ´â€ŒÙØ±Ø¶ Ø³ÛŒØ³ØªÙ…"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now_seed = get_now_iso()
        default_bundles = [
            ("bundle_1m", "Ø¨Ø³ØªÙ‡ Ø§Ø³ØªØ§Ø±ØªØ±", 1000000, 1050000, 5, "ÛµÙª Ø´Ø§Ø±Ú˜ Ù‡Ø¯ÛŒÙ‡", "info", "Ù…Ù†Ø§Ø³Ø¨ Ø´Ø±ÙˆØ¹ Ù‡Ù…Ú©Ø§Ø±ÛŒ Ùˆ Ø´Ø§Ø±Ú˜ Ø§ÙˆÙ„ÛŒÙ‡", 1, 1, now_seed, now_seed),
            ("bundle_3m", "Ø¨Ø³ØªÙ‡ Ù†Ù‚Ø±Ù‡â€ŒØ§ÛŒ", 3000000, 3210000, 7, "Û·Ùª Ø´Ø§Ø±Ú˜ Ù‡Ø¯ÛŒÙ‡", "primary", "Ø¨Ø³ØªÙ‡ Ø§Ù‚ØªØµØ§Ø¯ÛŒ Ø¨Ø§ Ø¨ÙˆÙ†ÙˆØ³ Ø´Ø§Ø±Ú˜ ØªØ´ÙˆÛŒÙ‚ÛŒ", 2, 1, now_seed, now_seed),
            ("bundle_5m", "Ø¨Ø³ØªÙ‡ Ø·Ù„Ø§ÛŒÛŒ", 5000000, 5500000, 10, "Û±Û°Ùª Ø´Ø§Ø±Ú˜ Ù‡Ø¯ÛŒÙ‡", "success", "Ø¨Ø³ØªÙ‡ Ù¾Ø±ÙØ±ÙˆØ´ Ù‡Ù…Ú©Ø§Ø±Ø§Ù† Ø¨Ø§ Û±Û°Ùª Ù‡Ø¯ÛŒÙ‡ Ù†Ù‚Ø¯ÛŒ", 3, 1, now_seed, now_seed),
            ("bundle_10m", "Ø¨Ø³ØªÙ‡ Ø§Ù„Ù…Ø§Ø³ VIP", 10000000, 11500000, 15, "Û±ÛµÙª Ø´Ø§Ø±Ú˜ ÙˆÛŒÚ˜Ù‡", "warning", "Ø­Ø¯Ø§Ú©Ø«Ø± Ø§Ø¹ØªØ¨Ø§Ø± Ø¨Ø§ Ø¨Ø§Ù„Ø§ØªØ±ÛŒÙ† Ù†Ø±Ø® Ø¨ÙˆÙ†ÙˆØ³ ÙˆÛŒÚ˜Ù‡", 4, 1, now_seed, now_seed),
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
        """Ø§Ø¹Ù…Ø§Ù„ Ø´Ø§Ø±Ú˜ Ø¨Ø³ØªÙ‡ Ù¾ÛŒØ´â€ŒØ®Ø±ÛŒØ¯ Ø¨Ù‡ Ù‡Ù…Ø±Ø§Ù‡ Ø§Ø¹ØªØ¨Ø§Ø± Ù‡Ø¯ÛŒÙ‡ Ø¨Ù‡ Ù…ÙˆØ¬ÙˆØ¯ÛŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡"""
        bundles = {b["id"]: b for b in self.get_reseller_credit_bundles()}
        bundle = bundles.get(bundle_id)
        if not bundle:
            return {"success": False, "error": "Ø¨Ø³ØªÙ‡ Ø§Ø¹ØªØ¨Ø§Ø±ÛŒ Ù…ÙˆØ±Ø¯ Ù†Ø¸Ø± ÛŒØ§ÙØª Ù†Ø´Ø¯."}

        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("SELECT balance, name FROM resellers WHERE id=?", (reseller_id,))
            res_row = cursor.fetchone()
            if not res_row:
                return {"success": False, "error": "Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ ÛŒØ§ÙØª Ù†Ø´Ø¯."}

            res_dict = dict(res_row)
            old_balance = res_dict.get("balance") or 0
            credit_to_add = bundle["credit"]
            new_balance = old_balance + credit_to_add

            cursor.execute("UPDATE resellers SET balance=?, updated_at=? WHERE id=?", (new_balance, now, reseller_id))

            # Ø«Ø¨Øª ØªØ±Ø§Ú©Ù†Ø´ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡
            desc = f"Ø®Ø±ÛŒØ¯ {bundle['title']} (ÙˆØ§Ø±ÛŒØ² {credit_to_add:,} ØªÙˆÙ…Ø§Ù† Ø¨Ø§ {bundle['badge']})"
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

    # â”€â”€â”€ Ø§Ø¹Ù„Ø§Ù†â€ŒÙ‡Ø§ Ùˆ Ù¾ÛŒØ§Ù…â€ŒÙ‡Ø§ÛŒ Ù¾Ù†Ù„ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ (Reseller Notifications) â”€â”€â”€

    def add_reseller_notification(self, reseller_id: int, title: str, message: str, type: str = "info") -> dict:
        """Ø§ÙØ²ÙˆØ¯Ù† Ø§Ø¹Ù„Ø§Ù† Ø¨Ù‡ Ù¾Ù†Ù„ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ (ØªØ§ÛŒÛŒØ¯/Ø±Ø¯ ÙÛŒØ´ØŒ ÙˆØ§Ø±ÛŒØ²ØŒ Ù‡Ø´Ø¯Ø§Ø±Ù‡Ø§ÛŒ Ø³ÛŒØ³ØªÙ…ÛŒ)"""
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
        """Ø¯Ø±ÛŒØ§ÙØª Ù„ÛŒØ³Øª Ø§Ø¹Ù„Ø§Ù†â€ŒÙ‡Ø§ÛŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡"""
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
        """ØªØ¹Ø¯Ø§Ø¯ Ø§Ø¹Ù„Ø§Ù†â€ŒÙ‡Ø§ÛŒ Ø®ÙˆØ§Ù†Ø¯Ù‡â€ŒÙ†Ø´Ø¯Ù‡ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡"""
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
        """Ø¹Ù„Ø§Ù…Øªâ€ŒÚ¯Ø°Ø§Ø±ÛŒ Ø§Ø¹Ù„Ø§Ù†â€ŒÙ‡Ø§ Ø¨Ù‡ Ø¹Ù†ÙˆØ§Ù† Ø®ÙˆØ§Ù†Ø¯Ù‡â€ŒØ´Ø¯Ù‡"""
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

    # â”€â”€â”€ Ø³ÛŒØ³ØªÙ… Ø±ÙØ±Ø§Ù„ Ùˆ Ú©Ø´â€ŒØ¨Ú© ÙˆÙØ§Ø¯Ø§Ø±ÛŒ (Referral & Cashback) â”€â”€â”€

    def process_referral_reward(self, user_telegram_id: int, purchase_amount: int, percent: int = 10) -> dict:
        """Ù…Ø­Ø§Ø³Ø¨Ù‡ Ùˆ ÙˆØ§Ø±ÛŒØ² Ø®ÙˆØ¯Ú©Ø§Ø± Ù¾ÙˆØ±Ø³Ø§Ù†Øª Ø±ÙØ±Ø§Ù„ Ø¨Ù‡ Ú©ÛŒÙ Ù¾ÙˆÙ„ Ù…Ø¹Ø±Ù"""
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

            # Ø§ÙØ²ÙˆØ¯Ù† Ø¨Ù‡ Ù…ÙˆØ¬ÙˆØ¯ÛŒ Ú©ÛŒÙ Ù¾ÙˆÙ„ Ù…Ø¹Ø±Ù
            cursor.execute("UPDATE users SET wallet_balance = COALESCE(wallet_balance, 0) + ? WHERE telegram_id = ?", (reward_amount, referrer_id))

            # Ø«Ø¨Øª Ø¯Ø± ØªØ±Ø§Ú©Ù†Ø´â€ŒÙ‡Ø§ÛŒ Ú©ÛŒÙ Ù¾ÙˆÙ„
            cursor.execute("""
                INSERT INTO wallet_transactions (telegram_id, amount, type, balance_after, description, ref_id, created_at)
                VALUES (?, ?, 'referral_reward', (SELECT wallet_balance FROM users WHERE telegram_id=?), ?, ?, ?)
            """, (referrer_id, reward_amount, referrer_id, f"Ù¾Ø§Ø¯Ø§Ø´ Ø¯Ø¹ÙˆØª Ø§Ø² Ø¯ÙˆØ³Øª ({percent}Ùª Ø®Ø±ÛŒØ¯ Ø§Ø´ØªØ±Ø§Ú©)", str(user_telegram_id), now))

            conn.commit()
            return {"rewarded": True, "referrer_id": referrer_id, "reward_amount": reward_amount, "percent": percent}
        except Exception as e:
            logger.error(f"Error processing referral reward: {e}")
            return {"rewarded": False, "error": str(e)}
        finally:
            conn.close()

    # â”€â”€â”€ ØªÙ†Ø¸ÛŒÙ…Ø§Øª Ø¯Ø±Ú¯Ø§Ù‡ Ù¾Ø±Ø¯Ø§Ø®Øª Ø¢Ù†Ù„Ø§ÛŒÙ† (Ù…Ø¯ÛŒØ±ÛŒØª Ùˆ Ù†Ù…Ø§ÛŒÙ†Ø¯Ú¯Ø§Ù†) â”€â”€â”€

    def get_reseller_gateway(self, reseller_id: int) -> dict:
        """Ø¯Ø±ÛŒØ§ÙØª ØªÙ†Ø¸ÛŒÙ…Ø§Øª Ø¯Ø±Ú¯Ø§Ù‡ Ø¢Ù†Ù„Ø§ÛŒÙ† Ø§Ø®ØªØµØ§ØµÛŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡"""
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
        """Ø¯Ø±ÛŒØ§ÙØª ØªÙ†Ø¸ÛŒÙ…Ø§Øª Ø¯Ø±Ú¯Ø§Ù‡ Ø¢Ù†Ù„Ø§ÛŒÙ† Ù…Ø¯ÛŒØ±ÛŒØª Ø§ØµÙ„ÛŒ"""
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
        """Ø¨Ø±ÙˆØ²Ø±Ø³Ø§Ù†ÛŒ Ø¯Ø±Ú¯Ø§Ù‡ Ù¾Ø±Ø¯Ø§Ø®Øª Ø¢Ù†Ù„Ø§ÛŒÙ† Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡"""
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
        """Ø¨Ø±ÙˆØ²Ø±Ø³Ø§Ù†ÛŒ Ø¯Ø±Ú¯Ø§Ù‡ Ù¾Ø±Ø¯Ø§Ø®Øª Ø¢Ù†Ù„Ø§ÛŒÙ† Ù…Ø¯ÛŒØ±ÛŒØª Ø§ØµÙ„ÛŒ"""
        try:
            self.set_setting("online_gateway_enabled", "1" if enabled else "0")
            self.set_setting("online_gateway_type", gateway_type or "zarinpal")
            self.set_setting("online_gateway_key", str(gateway_key or "").strip())
            self.set_setting("online_gateway_sandbox", "1" if sandbox else "0")
            return {"success": True}
        except Exception as e:
            logger.error(f"Error updating admin gateway: {e}")
            return {"success": False, "error": str(e)}

    # â”€â”€â”€ ØªÙ†Ø¸ÛŒÙ…Ø§Øª Ù¾Ø±Ø¯Ø§Ø®Øª Ø§Ø±Ø²ÛŒ Ùˆ Ú©Ø±ÛŒÙ¾ØªÙˆ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ (Reseller Crypto Settings) â”€â”€â”€

    def get_reseller_crypto_config(self, reseller_id: int) -> dict:
        """Ø¯Ø±ÛŒØ§ÙØª ØªÙ†Ø¸ÛŒÙ…Ø§Øª Ù¾Ø±Ø¯Ø§Ø®Øª Ø§Ø±Ø²ÛŒ Ùˆ Ú©Ø±ÛŒÙ¾ØªÙˆ Ø§Ø®ØªØµØ§ØµÛŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡"""
        enabled_val = self.get_setting(f"crypto_enabled_r_{reseller_id}", "0")
        wallet_addr = str(self.get_setting(f"crypto_wallet_r_{reseller_id}", "") or "").strip()
        usdt_rate_val = self.get_setting(f"crypto_rate_r_{reseller_id}", "")
        if not usdt_rate_val or not str(usdt_rate_val).isdigit():
            # ÙØ§Ù„â€ŒØ¨Ú© Ø¨Ù‡ Ù†Ø±Ø® Ø¯Ø±Ú¯Ø§Ù‡ Ú©Ø±ÛŒÙ¾ØªÙˆ Ø³Ø±Ø§Ø³Ø±ÛŒ
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
        """Ø°Ø®ÛŒØ±Ù‡ ØªÙ†Ø¸ÛŒÙ…Ø§Øª Ù¾Ø±Ø¯Ø§Ø®Øª Ø§Ø±Ø²ÛŒ Ùˆ Ú©Ø±ÛŒÙ¾ØªÙˆ Ø§Ø®ØªØµØ§ØµÛŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡"""
        try:
            self.set_setting(f"crypto_enabled_r_{reseller_id}", "1" if enabled else "0")
            self.set_setting(f"crypto_wallet_r_{reseller_id}", str(wallet_address or "").strip())
            if usdt_rate and int(usdt_rate) > 0:
                self.set_setting(f"crypto_rate_r_{reseller_id}", str(int(usdt_rate)))
            return {"success": True}
        except Exception as e:
            logger.error(f"Error saving reseller crypto config: {e}")
            return {"success": False, "error": str(e)}

    # â”€â”€â”€ ØªÙ†Ø¸ÛŒÙ…Ø§Øª ØªØ§ÛŒÛŒØ¯ Ø®ÙˆØ¯Ú©Ø§Ø± Ú©Ø§Ø±Øª Ø¨Ù‡ Ú©Ø§Ø±Øª Ø¨Ø§ Ù¾ÛŒØ§Ù…Ú© Ø¨Ø§Ù†Ú© (Smart Bank SMS) â”€â”€â”€

    def get_admin_bank_sms_config(self) -> dict:
        """Ø¯Ø±ÛŒØ§ÙØª ØªÙ†Ø¸ÛŒÙ…Ø§Øª ØªØ§ÛŒÛŒØ¯ Ø®ÙˆØ¯Ú©Ø§Ø± Ø¨Ø§ Ù¾ÛŒØ§Ù…Ú© Ø¨Ø§Ù†Ú© Ø¨Ø±Ø§ÛŒ Ù…Ø¯ÛŒØ±ÛŒØª Ø§ØµÙ„ÛŒ"""
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
        """Ø°Ø®ÛŒØ±Ù‡ ØªÙ†Ø¸ÛŒÙ…Ø§Øª ØªØ§ÛŒÛŒØ¯ Ø®ÙˆØ¯Ú©Ø§Ø± Ø¨Ø§ Ù¾ÛŒØ§Ù…Ú© Ø¨Ø§Ù†Ú© Ø¨Ø±Ø§ÛŒ Ù…Ø¯ÛŒØ±ÛŒØª Ø§ØµÙ„ÛŒ"""
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
        """Ø¯Ø±ÛŒØ§ÙØª ØªÙ†Ø¸ÛŒÙ…Ø§Øª ØªØ§ÛŒÛŒØ¯ Ø®ÙˆØ¯Ú©Ø§Ø± Ø¨Ø§ Ù¾ÛŒØ§Ù…Ú© Ø¨Ø§Ù†Ú© Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡"""
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
        """Ø°Ø®ÛŒØ±Ù‡ ØªÙ†Ø¸ÛŒÙ…Ø§Øª ØªØ§ÛŒÛŒØ¯ Ø®ÙˆØ¯Ú©Ø§Ø± Ø¨Ø§ Ù¾ÛŒØ§Ù…Ú© Ø¨Ø§Ù†Ú© Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡"""
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
        """Ù¾ÛŒØ¯Ø§ Ú©Ø±Ø¯Ù† ØµØ§Ø­Ø¨ ØªÙˆÚ©Ù† ÙˆØ¨â€ŒÙ‡ÙˆÚ© (Ø§Ø¯Ù…ÛŒÙ† ÛŒØ§ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡)"""
        if not token:
            return None
        token = str(token).strip()
        # Ø¨Ø±Ø±Ø³ÛŒ Ø§Ø¯Ù…ÛŒÙ†
        admin_token = self.get_setting("admin_bank_sms_token")
        if admin_token and admin_token == token:
            return {"type": "admin", "id": 0}
        
        # Ø¨Ø±Ø±Ø³ÛŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ú¯Ø§Ù†
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
        """Ø«Ø¨Øª Ù„Ø§Ú¯ Ù¾ÛŒØ§Ù…Ú© Ø¯Ø±ÛŒØ§ÙØªÛŒ Ø§Ø² ÙÙˆØ±ÙˆØ§Ø±Ø¯Ø±"""
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
        """Ø¯Ø±ÛŒØ§ÙØª Ø¢Ø®Ø±ÛŒÙ† Ù„Ø§Ú¯â€ŒÙ‡Ø§ÛŒ Ù¾ÛŒØ§Ù…Ú© Ø¨Ø§Ù†Ú©ÛŒ"""
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
        ØªÙˆÙ„ÛŒØ¯ ÙØ§Ú©ØªÙˆØ± ØªÙ…Ø¯ÛŒØ¯ Ù‡ÙˆØ´Ù…Ù†Ø¯ Ø¨Ø§ Ø§Ø±Ù‚Ø§Ù… ØªØµØ§Ø¯ÙÛŒ Ø®Ø±Ø¯ Ø¬Ù‡Øª ØªØ§ÛŒÛŒØ¯ Ø§ØªÙˆÙ…Ø§ØªÛŒÚ© Ø¨Ø§ Ù¾ÛŒØ§Ù…Ú© Ø¨Ø§Ù†Ú©
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        now_dt = get_now_naive()
        now_str = now_dt.isoformat()
        expires_dt = now_dt + timedelta(minutes=max(5, timeout_minutes))
        expires_str = expires_dt.isoformat()

        # Ø§Ø±Ù‚Ø§Ù… Ø®Ø±Ø¯ ØªØµØ§Ø¯ÙÛŒ
        min_suffix = 100 if digits == 3 else 1000
        max_suffix = 999 if digits == 3 else 9999

        # Ø±Ù†Ø¯ Ú©Ø±Ø¯Ù† Ø¨ÛŒØ³ Ø¨Ù‡ Ù‡Ø²Ø§Ø±Ú¯Ø§Ù†
        base_clean = (int(base_amount) // 1000) * 1000

        # Ù¾ÛŒØ¯Ø§ Ú©Ø±Ø¯Ù† Ù…Ø¨Ø§Ù„Øº Ø¯Ø± Ø­Ø§Ù„ Ø§Ø³ØªÙØ§Ø¯Ù‡ Ø¯Ø± ÙØ§Ú©ØªÙˆØ±Ù‡Ø§ÛŒ Ù…Ø¹Ù„Ù‚ Ø§ÛŒÙ† Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡/Ø§Ø¯Ù…ÛŒÙ† Ø¨Ø±Ø§ÛŒ Ø¬Ù„ÙˆÚ¯ÛŒØ±ÛŒ Ø§Ø² ØªØ¯Ø§Ø®Ù„
        cursor.execute("""
            SELECT final_amount FROM smart_invoices 
            WHERE reseller_id=? AND status='pending' AND expires_at > ?
        """, (reseller_id, now_str))
        active_amounts = {r["final_amount"] for r in cursor.fetchall()}

        # Ø§Ù†ØªØ®Ø§Ø¨ ÛŒÚ© Ø¹Ø¯Ø¯ Ø±Ù†Ø¯ÙˆÙ… Ú©Ù‡ ØªØ¯Ø§Ø®Ù„ Ù†Ø¯Ø§Ø´ØªÙ‡ Ø¨Ø§Ø´Ø¯
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
        """Ø¯Ø±ÛŒØ§ÙØª ÙØ§Ú©ØªÙˆØ± Ø¨Ø§ ØªÙˆÚ©Ù† Ø§Ù…Ù†"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT * FROM smart_invoices WHERE token=?", (token,))
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_smart_invoice_by_order_id(self, order_id: str) -> Optional[dict]:
        """Ø¯Ø±ÛŒØ§ÙØª ÙØ§Ú©ØªÙˆØ± Ø¨Ø§ Ø´Ù†Ø§Ø³Ù‡ Ø³ÙØ§Ø±Ø´"""
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
        ØªØ·Ø¨ÛŒÙ‚ Ù…Ø¨Ù„Øº Ù¾ÛŒØ§Ù…Ú© Ø¨Ø§Ù†Ú©ÛŒ Ø¨Ø§ ÙØ§Ú©ØªÙˆØ±Ù‡Ø§ÛŒ Ø¨Ø§Ø² Ø¯Ø± Ø§Ù†ØªØ¸Ø§Ø± Ù¾Ø±Ø¯Ø§Ø®Øª
        """
        if not amount_toman or amount_toman <= 0:
            return None

        reseller_id = owner_id if owner_type == "reseller" else 0
        now_str = get_now_naive().isoformat()

        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            # Û±. Ø¬Ø³ØªØ¬ÙˆÛŒ ÙØ§Ú©ØªÙˆØ± Ù…Ø¹Ù„Ù‚ Ù…Ù†Ù‚Ø¶ÛŒâ€ŒÙ†Ø´Ø¯Ù‡ Ø¨Ø§ Ø§ÛŒÙ† Ù…Ø¨Ù„Øº Ø¯Ù‚ÛŒÙ‚ Ø¨Ø±Ø§ÛŒ Ù‡Ù…ÛŒÙ† Ù…Ø§Ù„Ú©
            cursor.execute("""
                SELECT * FROM smart_invoices 
                WHERE reseller_id=? AND final_amount=? AND status='pending' AND expires_at >= ?
                ORDER BY id DESC LIMIT 1
            """, (reseller_id, amount_toman, now_str))
            row = cursor.fetchone()
            if row:
                return dict(row)

            # Û². Ø§Ú¯Ø± Ù…Ø§Ù„Ú© Ø§Ø¯Ù…ÛŒÙ† Ø§Ø³ØªØŒ ÙØ§Ú©ØªÙˆØ±Ù‡Ø§ÛŒ Ù…Ø´ØªØ±ÛŒØ§Ù† Ù†Ù…Ø§ÛŒÙ†Ø¯Ú¯Ø§Ù† Ú©Ù‡ Ø¨Ù‡ Ú©Ø§Ø±Øªâ€ŒÙ‡Ø§ÛŒ Ø§Ø¯Ù…ÛŒÙ† ÙˆØ§Ø±ÛŒØ² Ù…ÛŒâ€ŒÚ©Ù†Ù†Ø¯ Ù†ÛŒØ² Ø¨Ø±Ø±Ø³ÛŒ Ø´ÙˆØ¯
            if owner_type == "admin":
                cursor.execute("""
                    SELECT * FROM smart_invoices 
                    WHERE final_amount=? AND status='pending' AND expires_at >= ?
                    ORDER BY id DESC LIMIT 1
                """, (amount_toman, now_str))
                row_adm = cursor.fetchone()
                if row_adm:
                    return dict(row_adm)

            # Û³. Ø¨Ø±Ø±Ø³ÛŒ Ø¨Ø§Ø²Ù‡ Û¶Û° Ø¯Ù‚ÛŒÙ‚Ù‡ Ø§Ø®ÛŒØ± Ø¨Ø±Ø§ÛŒ ÙˆØ§Ø±ÛŒØ²Ù‡Ø§ÛŒÛŒ Ú©Ù‡ Ø¨Ø§ ØªØ§Ø®ÛŒØ± Ø§Ù†Ø¬Ø§Ù… Ø´Ø¯Ù†Ø¯
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
        """Ø«Ø¨Øª ÙˆØ¶Ø¹ÛŒØª Ù¾Ø±Ø¯Ø§Ø®Øª Ù…ÙˆÙÙ‚ Ø¨Ø±Ø§ÛŒ ÙØ§Ú©ØªÙˆØ± Ù‡ÙˆØ´Ù…Ù†Ø¯"""
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
        """Ù„ØºÙˆ ÙØ§Ú©ØªÙˆØ± Ù‡ÙˆØ´Ù…Ù†Ø¯ Ù…Ø¹Ù„Ù‚ ØªÙˆØ³Ø· Ù…Ø´ØªØ±ÛŒ ÛŒØ§ Ù…Ø¯ÛŒØ±"""
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

    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    # Ù…Ø¯ÛŒØ±ÛŒØª Ø§ÙˆÙ„ÙˆÛŒØª Ùˆ Ú†ÛŒØ¯Ù…Ø§Ù† Ø±ÙˆØ´â€ŒÙ‡Ø§ÛŒ Ù¾Ø±Ø¯Ø§Ø®Øª (Payment Methods Ordering)
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

    DEFAULT_PAYMENT_METHODS = [
        {"id": "card_to_card", "name": "Ú©Ø§Ø±Øª Ø¨Ù‡ Ú©Ø§Ø±Øª (Ø¨Ø§Ù†Ú©ÛŒ)", "icon": "fa-credit-card", "color": "primary", "enabled": True, "desc": "ÙˆØ§Ø±ÛŒØ² Ø¨Ù‡ Ø´Ù…Ø§Ø±Ù‡ Ú©Ø§Ø±Øªâ€ŒÙ‡Ø§ÛŒ ÙØ¹Ø§Ù„ Ø¨Ø§ Ø¨Ø±Ø±Ø³ÛŒ Ùˆ ØªØ§ÛŒÛŒØ¯ ÙÛŒØ´"},
        {"id": "wallet", "name": "Ù¾Ø±Ø¯Ø§Ø®Øª Ø§Ø² Ú©ÛŒÙ Ù¾ÙˆÙ„", "icon": "fa-wallet", "color": "success", "enabled": True, "desc": "Ú©Ø³Ø± Ø¢Ù†ÛŒ Ù…Ø¨Ù„Øº Ø§Ø² Ù…ÙˆØ¬ÙˆØ¯ÛŒ Ú©ÛŒÙ Ù¾ÙˆÙ„ Ùˆ ÙØ¹Ø§Ù„â€ŒØ³Ø§Ø²ÛŒ Ù„Ø­Ø¸Ù‡â€ŒØ§ÛŒ Ø§Ø´ØªØ±Ø§Ú©"},
        {"id": "online_gateway", "name": "Ø¯Ø±Ú¯Ø§Ù‡ Ù¾Ø±Ø¯Ø§Ø®Øª Ø¢Ù†Ù„Ø§ÛŒÙ† (Ø´Ø§Ù¾Ø±Ú© / Ø¨Ù„ÙˆÙ¾Ø§Ù„)", "icon": "fa-globe", "color": "info", "enabled": True, "desc": "Ø§ØªØµØ§Ù„ Ø®ÙˆØ¯Ú©Ø§Ø± Ø¨Ù‡ Ø¯Ø±Ú¯Ø§Ù‡â€ŒÙ‡Ø§ÛŒ Ø²Ø±ÛŒÙ†â€ŒÙ¾Ø§Ù„ØŒ Ø¢ÛŒØ¯ÛŒâ€ŒÙ¾ÛŒØŒ Ù†Ú©Ø³Øªâ€ŒÙ¾ÛŒ ÛŒØ§ Ú©Ø§Ø±Øªâ€ŒØ¨Ù‡â€ŒÚ©Ø§Ø±Øª Ù‡ÙˆØ´Ù…Ù†Ø¯ Ø¨Ù„ÙˆÙ¾Ø§Ù„"},
        {"id": "crypto", "name": "Ø§Ø±Ø² Ø¯ÛŒØ¬ÛŒØªØ§Ù„ (ØªØªØ± / Ú©Ø±ÛŒÙ¾ØªÙˆ)", "icon": "fa-gem", "color": "warning", "enabled": True, "desc": "Ù¾Ø±Ø¯Ø§Ø®Øª Ø¨Ø§ ØªØªØ± (USDT TRC20 / TON) Ø¨Ø§ Ù…Ø­Ø§Ø³Ø¨Ù‡ Ø®ÙˆØ¯Ú©Ø§Ø± Ù†Ø±Ø® Ø±ÙˆØ²"},
    ]

    def get_payment_methods(self, reseller_id: Optional[int] = None) -> List[dict]:
        """Ø¯Ø±ÛŒØ§ÙØª Ù„ÛŒØ³Øª Ùˆ ØªØ±ØªÛŒØ¨ Ø§ÙˆÙ„ÙˆÛŒØª Ø±ÙˆØ´â€ŒÙ‡Ø§ÛŒ Ù¾Ø±Ø¯Ø§Ø®Øª Ø¨Ø±Ø§ÛŒ Ø¨Ø§Øª Ùˆ Ù¾Ù†Ù„"""
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
        """Ø°Ø®ÛŒØ±Ù‡ Ú†ÛŒØ¯Ù…Ø§Ù† Ùˆ ÙˆØ¶Ø¹ÛŒØª ÙØ¹Ø§Ù„ Ø¨ÙˆØ¯Ù† Ø±ÙˆØ´â€ŒÙ‡Ø§ÛŒ Ù¾Ø±Ø¯Ø§Ø®Øª"""
        try:
            setting_key = f"payment_methods_order_r_{reseller_id}" if reseller_id else "payment_methods_order"
            self.set_setting(setting_key, json.dumps(methods, ensure_ascii=False))
            return True
        except Exception as e:
            logger.error(f"Error saving payment methods: {e}")
            return False

    def move_payment_method(self, method_id: str, direction: str, reseller_id: Optional[int] = None) -> List[dict]:
        """Ø¬Ø§Ø¨Ø¬Ø§ÛŒÛŒ Ø¹Ù…ÙˆØ¯ÛŒ ÛŒÚ© Ø±ÙˆØ´ Ù¾Ø±Ø¯Ø§Ø®Øª Ø¨Ù‡ Ø¨Ø§Ù„Ø§ ÛŒØ§ Ù¾Ø§ÛŒÛŒÙ†"""
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
        """ØªØºÛŒÛŒØ± ÙˆØ¶Ø¹ÛŒØª ÙØ¹Ø§Ù„/ØºÛŒØ±ÙØ¹Ø§Ù„ Ø¨ÙˆØ¯Ù† ÛŒÚ© Ø±ÙˆØ´ Ù¾Ø±Ø¯Ø§Ø®Øª"""
        methods = self.get_payment_methods(reseller_id)
        for m in methods:
            if m["id"] == method_id:
                m["enabled"] = not m.get("enabled", True)
                break
        self.save_payment_methods(methods, reseller_id)
        return methods


    # â”€â”€â”€ Ù…Ø¯ÛŒØ±ÛŒØª Ù¾Ù„Ù†â€ŒÙ‡Ø§ÛŒ Ø§Ø®ØªØµØ§ØµÛŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ú¯Ø§Ù† (Reseller Custom Plans) â”€â”€â”€

    def get_reseller_plans(self, reseller_id: int) -> List[dict]:
        """Ø¯Ø±ÛŒØ§ÙØª Ù„ÛŒØ³Øª ØªÙ…Ø§Ù… Ù¾Ù„Ù†â€ŒÙ‡Ø§ÛŒ Ù…Ø§Ø¯Ø± Ø¨Ø§ Ø§Ø¹Ù…Ø§Ù„ Ø´Ø®ØµÛŒâ€ŒØ³Ø§Ø²ÛŒâ€ŒÙ‡Ø§ØŒ Ø­Ø¬Ù…ØŒ Ù…Ø¯Øª Ùˆ Ù‚ÛŒÙ…Øªâ€ŒÙ‡Ø§ÛŒ Ø³ÙØ§Ø±Ø´ÛŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ (Ø¨Ø§ ÙÛŒÙ„ØªØ± Ù‚Ø·Ø¹ÛŒ Ù¾Ù„Ù†â€ŒÙ‡Ø§ÛŒ Ø§Ø®ØªØµØ§ØµÛŒ)"""
        from admin_manager import load_plans
        raw_master_plans = load_plans()
        
        # ÙÛŒÙ„ØªØ± Ù‡ÙˆØ´Ù…Ù†Ø¯ Ù¾Ù„Ù†â€ŒÙ‡Ø§:
        # Û±. Ù¾Ù„Ù†â€ŒÙ‡Ø§ÛŒ Ø§Ø®ØªØµØ§ØµÛŒ Ù…Ø¯ÛŒØ±ÛŒØª Ø§Ø±Ø´Ø¯ Ú©Ø§Ù…Ù„Ø§Ù‹ Ù…Ø®ÙÛŒ Ù‡Ø³ØªÙ†Ø¯
        # Û². Ù¾Ù„Ù†â€ŒÙ‡Ø§ÛŒ Ø§Ø®ØªØµØ§ØµÛŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ú¯Ø§Ù† (Ø¯Ø§Ø±Ø§ÛŒ allowed_resellers) ÙÙ‚Ø· Ø¨Ù‡ Ù†Ù…Ø§ÛŒÙ†Ø¯Ú¯Ø§Ù† Ù…Ø¬Ø§Ø² ØªØ®ØµÛŒØµ Ø¯Ø§Ø¯Ù‡ Ù…ÛŒâ€ŒØ´ÙˆÙ†Ø¯
        # Û³. Ø³Ø§ÛŒØ± Ù†Ù…Ø§ÛŒÙ†Ø¯Ú¯Ø§Ù† ÛŒØ§ Ú©Ø§Ø±Ø¨Ø±Ø§Ù† Ø¹Ø§Ø¯ÛŒ Ø¨Ù‡ Ù‡ÛŒÚ† Ø¹Ù†ÙˆØ§Ù† Ù¾Ù„Ù†â€ŒÙ‡Ø§ÛŒ Ø§Ø®ØªØµØ§ØµÛŒ Ø±Ø§ Ø¯Ø±ÛŒØ§ÙØª Ù†Ø®ÙˆØ§Ù‡Ù†Ø¯ Ú©Ø±Ø¯
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
            admin_name = admin_custom_name if admin_custom_name else p.get("name", "Ù¾Ù„Ù†")

            # Ø§Ú¯Ø± Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ Ù‚ÛŒÙ…Øª ÛŒØ§ Ù†Ø§Ù… Ø§Ø®ØªØµØ§ØµÛŒ Ø¯Ø§Ø¯Ù‡ Ø¨Ø§Ø´Ø¯ Ùˆ ÙÙ„Ú¯ ØªØºÛŒÛŒØ± Ø®ÙˆØ±Ø¯Ù‡ Ø¨Ø§Ø´Ø¯
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
            
            # Ù‚ÛŒÙ…Øª ØªÙ…Ø§Ù…â€ŒØ´Ø¯Ù‡ Ø®Ø±ÛŒØ¯ Ø¹Ù…Ø¯Ù‡ Ø¨Ø±Ø§ÛŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ Ù‡Ù…ÛŒØ´Ù‡ Ø¨Ø± Ù…Ø¨Ù†Ø§ÛŒ Ù‚ÛŒÙ…Øª Ù¾Ø§ÛŒÙ‡ ØªØ¹ÛŒÛŒÙ† Ø´Ø¯Ù‡ ØªÙˆØ³Ø· Ù…Ø¯ÛŒØ± (admin_price) Ù…Ø­Ø§Ø³Ø¨Ù‡ Ù…ÛŒâ€ŒØ´ÙˆØ¯
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
                "master_name": p.get("name", "Ù¾Ù„Ù†"),
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
                display_name = reseller_custom_name if (is_reseller_modified and reseller_custom_name) else (admin_custom_name or p_meta.get("name", "Ù¾Ù„Ù†"))

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
        """Ø¯Ø±ÛŒØ§ÙØª Ø¯ÛŒÚ©Ø´Ù†Ø±ÛŒ Ù¾Ù„Ù†â€ŒÙ‡Ø§ÛŒ Ø§Ø®ØªØµØ§ØµÛŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ Ø¨Ø± Ø§Ø³Ø§Ø³ plan_id Ø¨Ø§ ØªÙ…Ø§Ù… Ø´Ø®ØµÛŒâ€ŒØ³Ø§Ø²ÛŒâ€ŒÙ‡Ø§"""
        plans = self.get_reseller_plans(reseller_id)
        return {str(p["plan_id"]): p for p in plans}

    def get_reseller_active_plans(self, reseller_id: int) -> List[dict]:
        """Ø¯Ø±ÛŒØ§ÙØª ÙÙ‚Ø· Ù¾Ù„Ù†â€ŒÙ‡Ø§ÛŒ ÙØ¹Ø§Ù„ Ø¨Ø±Ø§ÛŒ Ù†Ù…Ø§ÛŒØ´ Ø¨Ù‡ Ù…Ø´ØªØ±ÛŒØ§Ù† Ø±Ø¨Ø§Øª ØªÙ„Ú¯Ø±Ø§Ù… Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡"""
        all_plans = self.get_reseller_plans(reseller_id)
        return [p for p in all_plans if p.get("is_active") and p.get("master_is_active")]

    def get_reseller_plan(self, reseller_id: int, plan_id: str) -> Optional[dict]:
        """Ø¯Ø±ÛŒØ§ÙØª Ù…Ø´Ø®ØµØ§Øª Ú©Ø§Ù…Ù„ ÛŒÚ© Ù¾Ù„Ù† Ø®Ø§Øµ Ø¨Ø±Ø§ÛŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡"""
        plans = self.get_reseller_plans(reseller_id)
        for p in plans:
            if str(p["plan_id"]) == str(plan_id):
                return p
        return None

    def update_reseller_plan_override(self, reseller_id: int, plan_id: str, custom_name: str = None, custom_price: int = None, custom_data_limit: float = None, custom_duration: int = None, custom_discount_percent: float = None, custom_wholesale_price: int = None, is_active: bool = True, preserve_specs: bool = False, is_reseller: bool = False) -> dict:
        """Ø¨Ø±ÙˆØ²Ø±Ø³Ø§Ù†ÛŒ ÛŒØ§ Ø«Ø¨Øª ØªÙ†Ø¸ÛŒÙ…Ø§Øª Ø§Ø®ØªØµØ§ØµÛŒ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ Ø¨Ø±Ø§ÛŒ ÛŒÚ© Ù¾Ù„Ù† (Ù†Ø§Ù…ØŒ Ù‚ÛŒÙ…ØªØŒ Ø­Ø¬Ù…ØŒ Ù…Ø¯ØªØŒ ØªØ®ÙÛŒÙØŒ Ù‚ÛŒÙ…Øª Ø¹Ù…Ø¯Ù‡ØŒ ÙˆØ¶Ø¹ÛŒØª)"""
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
        """Ø¨Ø§Ø²Ù†Ø´Ø§Ù†ÛŒ ØªÙ†Ø¸ÛŒÙ…Ø§Øª Ù¾Ù„Ù† Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡Ø› Ø¯Ø± ØµÙˆØ±Øª Ø¨Ø§Ø²Ù†Ø´Ø§Ù†ÛŒ ØªÙˆØ³Ø· Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ØŒ Ø¯Ø±ØµØ¯ ØªØ®ÙÛŒÙ Ùˆ Ù‚ÛŒÙ…Øª Ø¹Ù…Ø¯Ù‡ Ù…Ø¯ÛŒØ± Ø­ÙØ¸ Ù…ÛŒâ€ŒØ´ÙˆØ¯"""
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
        Ú¯Ø²Ø§Ø±Ø´ Ø¬Ø§Ù…Ø¹ Ú¯Ø±Ø¯Ø´ Ø­Ø³Ø§Ø¨ Ùˆ Ø­Ø³Ø§Ø¨Ø±Ø³ÛŒ Û³Û° Ø±ÙˆØ² Ø§Ø®ÛŒØ± Ø¨Ø§ Ø¬Ø²Ø¦ÛŒØ§Øª Ø³ÙˆØ¯ØŒ ÙØ±ÙˆØ´ Ù†Ù‚Ø¯ÛŒ/Ø§Ø¹ØªØ¨Ø§Ø±ÛŒØŒ
        ØªØ±Ø§ÙÛŒÚ© ÙˆØ§Ú¯Ø°Ø§Ø± Ø´Ø¯Ù‡ØŒ ØªØ¹Ø¯Ø§Ø¯ Ø§Ø´ØªØ±Ø§Ú©â€ŒÙ‡Ø§ Ùˆ Ø±ÛŒØ² ØªØ±Ø§Ú©Ù†Ø´â€ŒÙ‡Ø§ Ø¨Ù‡ Ù‡Ù…Ø±Ø§Ù‡ Ø®Ø±ÙˆØ¬ÛŒ ØªÙÚ©ÛŒÚ©ÛŒ
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

            # Û±. Ø§Ø³ØªØ®Ø±Ø§Ø¬ ØªØ±Ø§Ú©Ù†Ø´â€ŒÙ‡Ø§ÛŒ ØªØ§ÛŒÛŒØ¯ Ø´Ø¯Ù‡ Ø¯Ø± Ø¨Ø§Ø²Ù‡ Ø²Ù…Ø§Ù†ÛŒ
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
                
                is_credit_tx = bool(r_dict.get("gateway") == "credit" or "credit" in str(r_dict.get("order_id", "")).lower() or "Ø§Ø¹ØªØ¨Ø§Ø±ÛŒ" in str(r_dict.get("tracking_code", "")))
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

            # Û±.Û². Ø§Ø¶Ø§ÙÙ‡ Ú©Ø±Ø¯Ù† Ø®Ø±ÛŒØ¯Ù‡Ø§ÛŒ Ù…Ø³ØªÙ‚ÛŒÙ… Ùˆ ØªÙ…Ø¯ÛŒØ¯Ù‡Ø§ÛŒ Ù¾Ù†Ù„ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ Ø¨Ù‡ Ø¹Ù†ÙˆØ§Ù† Ø¯Ø±Ø¢Ù…Ø¯ Ùˆ Ø³ÙˆØ¯
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
                        norm_tx["gateway"] = "Ú©ÛŒÙ Ù¾ÙˆÙ„" if norm_tx.get("payment_source") == "wallet" else "Ø§Ø¹ØªØ¨Ø§Ø± Ø®Ø±ÛŒØ¯"
                    audit["transactions"].append(norm_tx)

            # Û². Ø§Ø´ØªØ±Ø§Ú©â€ŒÙ‡Ø§ÛŒ Ø§ÛŒØ¬Ø§Ø¯ Ø´Ø¯Ù‡ Ø¯Ø± Ø¨Ø§Ø²Ù‡ Ø²Ù…Ø§Ù†ÛŒ Ø¬Ù‡Øª Ù…Ø­Ø§Ø³Ø¨Ù‡ Ø­Ø¬Ù… Ú©Ù„ GB Ùˆ ØªÙÚ©ÛŒÚ© Ø±ÙˆØ²Ø´Ù…Ø§Ø±
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

                    gw = "Ø§Ø¹ØªØ¨Ø§Ø± Ø®Ø±ÛŒØ¯" if (s_dict.get("is_credit") or s_dict.get("payment_source") == "credit") else ("Ú©ÛŒÙ Ù¾ÙˆÙ„" if c_paid > 0 else "Ø³ÙØ§Ø±Ø´ Ù…Ø³ØªÙ‚ÛŒÙ…")
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

            # Û³. Ù…Ø­Ø§Ø³Ø¨Ù‡ Ù‡Ø²ÛŒÙ†Ù‡â€ŒÙ‡Ø§ Ùˆ Ø¨Ø¯Ù‡ÛŒâ€ŒÙ‡Ø§
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

            # Û´. Ù…Ø±ØªØ¨â€ŒØ³Ø§Ø²ÛŒ Ø±ÙˆØ²Ø´Ù…Ø§Ø± Û³Û° Ø±ÙˆØ²Ù‡ Ø¨Ø± Ø§Ø³Ø§Ø³ ØªØ§Ø±ÛŒØ® Ø¨Ù‡ ØµÙˆØ±Øª Ù†Ø²ÙˆÙ„ÛŒ
            sorted_daily = []
            for d_key in sorted(daily_map.keys(), reverse=True):
                sorted_daily.append(daily_map[d_key])

            audit["daily_stats"] = sorted_daily
            audit["daily_turnover"] = daily_map

            # Ûµ. Ø¯ÛŒÚ©Ø´Ù†Ø±ÛŒ summary Ù‡Ù…Ø§Ù‡Ù†Ú¯ Ø¨Ø§ Ù‚Ø§Ù„Ø¨â€ŒÙ‡Ø§ÛŒ jinja2
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
        """Ù†Ù‚Ø´Ù‡ Ø³Ø±ÛŒØ¹ ÙˆØ¶Ø¹ÛŒØª ØªÛŒÚ©Øªâ€ŒÙ‡Ø§ÛŒ Ú©Ø§Ø±Ø¨Ø±Ø§Ù† Ùˆ Ù…Ø´ØªØ±ÛŒØ§Ù† (Ø¨Ø§Ø²ØŒ Ø¯Ø± Ø§Ù†ØªØ¸Ø§Ø±ØŒ Ø¨Ø³ØªÙ‡)"""
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
        """Ø§ÙØ²Ø§ÛŒØ´ Ø¯Ø³ØªÛŒ Ø­Ø¬Ù… Ø§Ø´ØªØ±Ø§Ú© Ø¯Ø± Ø¯ÛŒØªØ§Ø¨ÛŒØ³ Ùˆ Ù¾Ù†Ù„ Ù‡ÛŒØ¯ÛŒÙØ§ÛŒ"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = get_now_iso()
        try:
            cursor.execute("SELECT * FROM subscriptions WHERE id=?", (sub_id,))
            sub = cursor.fetchone()
            if not sub:
                return {"success": False, "error": "Ø§Ø´ØªØ±Ø§Ú© ÛŒØ§ÙØª Ù†Ø´Ø¯."}
            
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
        """ØªÙ†Ø¸ÛŒÙ… ÙˆØ¶Ø¹ÛŒØª Ù…Ø´ØªØ±ÛŒ Ù¾Ø±Ù…ÛŒÙˆÙ… / VIP Ø¨Ø±Ø§ÛŒ Ø§Ø´ØªØ±Ø§Ú©"""
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
        """ÙˆØ§Ø±ÛŒØ² Ø´Ø§Ø±Ú˜ Ø¨Ø³ØªÙ‡ Ø§Ø¹ØªØ¨Ø§Ø±ÛŒ Ùˆ Ø¨ÙˆÙ†ÙˆØ³ Ù…Ø±Ø¨ÙˆØ·Ù‡ Ø¨Ù‡ Ú©ÛŒÙ Ù¾ÙˆÙ„ Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ Ù¾Ø³ Ø§Ø² ØªØ§ÛŒÛŒØ¯ Ø±Ø³ÛŒØ¯"""
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
                return {"success": False, "error": "Ù†Ù…Ø§ÛŒÙ†Ø¯Ù‡ ÛŒØ§ÙØª Ù†Ø´Ø¯."}

            res_dict = dict(res_row)
            old_balance = res_dict.get("balance") or 0
            new_balance = old_balance + credit_to_add

            cursor.execute("UPDATE resellers SET balance=?, updated_at=? WHERE id=?", (new_balance, now, reseller_id))

            desc = f"Ø´Ø§Ø±Ú˜ ØªØ§ÛŒÛŒØ¯Ø´Ø¯Ù‡ {bundle_title} (Ù…Ø¨Ù„Øº Ø´Ø§Ø±Ú˜: {credit_to_add:,} ØªÙˆÙ…Ø§Ù† | Ø¨ÙˆÙ†ÙˆØ³: {bonus_pct}Ùª)"
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


# Ù†Ù…ÙˆÙ†Ù‡ singleton
db = Database()







