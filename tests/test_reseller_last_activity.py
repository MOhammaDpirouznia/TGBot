import unittest
import sqlite3
import os
import shutil
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from utils import (
    TEHRAN_TZ, to_persian_digits, format_activity_time, get_now_tehran
)
from database import Database


class TestResellerLastActivity(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_reseller_act.db"
        self.db = Database()
        # Override connection to use temporary isolated test DB
        self.orig_get_conn = self.db.get_connection
        self.db.get_connection = lambda: sqlite3.connect(str(self.db_path))
        self.db.get_connection().row_factory = sqlite3.Row

        conn = self.db.get_connection()
        cur = conn.cursor()
        # Create minimal required tables
        cur.execute("""
            CREATE TABLE IF NOT EXISTS resellers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                telegram_id INTEGER,
                status TEXT DEFAULT 'active'
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS login_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_type TEXT NOT NULL,
                user_id INTEGER,
                username TEXT NOT NULL,
                login_at TEXT NOT NULL,
                last_active_at TEXT,
                logout_at TEXT,
                is_active INTEGER DEFAULT 1
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS telegram_activity (
                telegram_id INTEGER PRIMARY KEY,
                role TEXT,
                reseller_id INTEGER,
                last_active_at TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reseller_id INTEGER,
                created_at TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS reseller_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reseller_id INTEGER,
                created_at TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ticket_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_type TEXT,
                sender_id INTEGER,
                created_at TEXT
            )
        """)
        conn.commit()
        conn.close()

    def tearDown(self):
        self.db.get_connection = self.orig_get_conn
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_to_persian_digits(self):
        self.assertEqual(to_persian_digits("0123456789"), "۰۱۲۳۴۵۶۷۸۹")
        self.assertEqual(to_persian_digits(123), "۱۲۳")
        self.assertEqual(to_persian_digits("15 دقیقه پیش"), "۱۵ دقیقه پیش")
        self.assertEqual(to_persian_digits(None), "")
        self.assertEqual(to_persian_digits(""), "")

    def test_format_activity_time_none_and_empty(self):
        res = format_activity_time(None)
        self.assertFalse(res["has_activity"])
        self.assertEqual(res["ago"], "بدون فعالیت")
        self.assertEqual(res["shamsi_full"], "-")

        res2 = format_activity_time("")
        self.assertFalse(res2["has_activity"])
        self.assertEqual(res2["ago"], "بدون فعالیت")

        res3 = format_activity_time("0001-01-01T00:00:00")
        self.assertFalse(res3["has_activity"])

    def test_format_activity_time_intervals(self):
        now_tehran = datetime.now(TEHRAN_TZ)

        # Less than 60 seconds
        dt_just_now = now_tehran - timedelta(seconds=20)
        res = format_activity_time(dt_just_now)
        self.assertTrue(res["has_activity"])
        self.assertEqual(res["ago"], "لحظاتی پیش")

        # 15 minutes
        dt_15m = now_tehran - timedelta(minutes=15)
        res = format_activity_time(dt_15m)
        self.assertEqual(res["ago"], "۱۵ دقیقه پیش")

        # 3 hours (same day)
        if now_tehran.hour >= 3:
            dt_3h = now_tehran - timedelta(hours=3)
            res = format_activity_time(dt_3h)
            self.assertIn("ساعت پیش", res["ago"])

        # 5 days
        dt_5d = now_tehran - timedelta(days=5)
        res = format_activity_time(dt_5d)
        self.assertEqual(res["ago"], "۵ روز پیش")

        # 2 months (65 days)
        dt_2m = now_tehran - timedelta(days=65)
        res = format_activity_time(dt_2m)
        self.assertEqual(res["ago"], "۲ ماه پیش")

        # Verify Shamsi format contains Persian digits and slash
        self.assertIn("/", res["shamsi_full"])
        self.assertIn("آخرین فعالیت", res["tooltip"])

    def test_get_all_resellers_last_activity_aggregation(self):
        conn = self.db.get_connection()
        cur = conn.cursor()

        # Insert 3 test resellers
        cur.execute("INSERT INTO resellers (id, username, name, telegram_id) VALUES (1, 'res1', 'نماینده یک', 111)")
        cur.execute("INSERT INTO resellers (id, username, name, telegram_id) VALUES (2, 'res2', 'نماینده دو', 222)")
        cur.execute("INSERT INTO resellers (id, username, name, telegram_id) VALUES (3, 'res3', 'نماینده سه', 333)")

        # Reseller 1: active in web login
        t1 = "2026-09-18T10:00:00+03:30"
        cur.execute("""
            INSERT INTO login_logs (user_type, user_id, username, login_at, last_active_at)
            VALUES ('reseller', 1, 'res1', '2026-09-18T09:00:00+03:30', ?)
        """, (t1,))

        # Reseller 2: older telegram activity, but more recent subscription
        t2_older = "2026-09-10T12:00:00+03:30"
        t2_newer = "2026-09-19T14:30:00+03:30"
        cur.execute("INSERT INTO telegram_activity (telegram_id, reseller_id, last_active_at) VALUES (222, 2, ?)", (t2_older,))
        cur.execute("INSERT INTO subscriptions (reseller_id, created_at) VALUES (2, ?)", (t2_newer,))

        # Reseller 3: ticket message
        t3 = "2026-09-17T08:15:00+03:30"
        cur.execute("INSERT INTO ticket_messages (sender_type, sender_id, created_at) VALUES ('reseller', 3, ?)", (t3,))

        conn.commit()
        conn.close()

        activity_map = self.db.get_all_resellers_last_activity()

        self.assertEqual(activity_map.get(1), t1)
        self.assertEqual(activity_map.get(2), t2_newer)
        self.assertEqual(activity_map.get(3), t3)

        # Single reseller fetch
        self.assertEqual(self.db.get_reseller_last_activity(1), t1)
        self.assertEqual(self.db.get_reseller_last_activity(2, telegram_id=222), t2_newer)
        self.assertIsNone(self.db.get_reseller_last_activity(999))

    def test_is_reseller_online_with_telegram_activity(self):
        conn = self.db.get_connection()
        cur = conn.cursor()
        now_tehran = datetime.now(TEHRAN_TZ)
        recent_time = (now_tehran - timedelta(minutes=5)).isoformat()
        old_time = (now_tehran - timedelta(minutes=30)).isoformat()

        cur.execute("INSERT INTO telegram_activity (telegram_id, reseller_id, last_active_at) VALUES (555, 50, ?)", (recent_time,))
        cur.execute("INSERT INTO telegram_activity (telegram_id, reseller_id, last_active_at) VALUES (666, 60, ?)", (old_time,))
        conn.commit()
        conn.close()

        self.assertTrue(self.db.is_reseller_online(50, threshold_minutes=15))
        self.assertFalse(self.db.is_reseller_online(60, threshold_minutes=15))

    def test_no_forbidden_plan_vocabulary(self):
        with open("utils.py", encoding="utf-8") as f:
            utils_content = f.read()
        self.assertIn("to_persian_digits", utils_content)
        self.assertIn("format_activity_time", utils_content)
        # Ensure our new functions don't use the forbidden word
        self.assertNotIn("پلن", utils_content[utils_content.find("def format_activity_time"):])


if __name__ == "__main__":
    unittest.main()
