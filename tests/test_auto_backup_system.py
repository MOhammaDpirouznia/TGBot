#!/usr/bin/env python3
"""
تست‌های جامع سیستم پشتیبان‌گیری خودکار
- تست ایجاد اسنپ‌شات و فشرده‌سازی دیتابیس
- تست متدهای دیتابیس (لاگ‌ها، تفکیک نوع، آمار، شاخص‌ها)
- تست زمان‌بند پشتیبان‌گیری و اعتبارسنجی بازه و ساعت‌ها
- تست غیرفعال بودن شیوه قدیمی ارسال به پی‌وی ادمین
"""

import os
import sys
import unittest
import tempfile
import json
import zipfile
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from database import Database
from backup import BackupManager, AutoBackupScheduler, send_backup_to_admin, format_file_size


class TestAutoBackupSystem(unittest.TestCase):
    def setUp(self):
        self.temp_db_fd, self.temp_db_path = tempfile.mkstemp(suffix=".db")
        self.db = Database(db_path=self.temp_db_path)
        self.db.init_db()

    def tearDown(self):
        try:
            os.close(self.temp_db_fd)
            os.remove(self.temp_db_path)
        except Exception:
            pass

    def test_database_backup_and_zip_compression(self):
        """تست اسنپ‌شات اتمیک و فشرده‌سازی زیپ دیتابیس"""
        bm = BackupManager()
        # مقداری دیتای ساختگی اضافه می‌کنیم
        conn = self.db.get_connection()
        c = conn.cursor()
        c.execute("""
            INSERT INTO subscriptions (telegram_id, hidify_uuid, account_name, status, created_at, updated_at)
            VALUES (1001, 'uuid-test-1', 'sub_test_1', 'active', '2026-09-22', '2026-09-22')
        """)
        c.execute("""
            INSERT INTO users (telegram_id, username, phone_number, created_at, updated_at)
            VALUES (1001, 'user_1001', '09120000000', '2026-09-22', '2026-09-22')
        """)
        conn.commit()
        conn.close()

        res = bm.create_database_backup(compress=True)
        self.assertTrue(res["success"])
        self.assertTrue(res["file"].endswith(".zip"))
        self.assertTrue(Path(res["file"]).exists())
        self.assertGreater(res["size"], 0)

        # بررسی محتویات فایل زیپ
        with zipfile.ZipFile(res["file"], "r") as zf:
            names = zf.namelist()
            self.assertTrue(any(n.endswith(".db") for n in names))
            self.assertIn("backup_metadata.json", names)
            meta = json.loads(zf.read("backup_metadata.json").decode("utf-8"))
            self.assertIn("metrics", meta)
            self.assertGreaterEqual(meta["metrics"]["total_subscriptions"], 1)

        # پاک‌سازی فایل تست
        try:
            Path(res["file"]).unlink()
        except Exception:
            pass

    def test_backup_records_and_type_separation(self):
        """تست ثبت رکوردها و تفکیک کامل پنل اصلی و هیدیفای"""
        r1 = self.db.save_backup_record(
            backup_file="backup_main_test.zip",
            backup_size=50000,
            backup_type="main_panel",
            status="success",
            target_chat="-100123456",
            details_json=json.dumps({"total_subscriptions": 150}),
            trigger_type="auto"
        )
        self.assertTrue(r1["success"])

        r2 = self.db.save_backup_record(
            backup_file="backup_hiddify_test.json",
            backup_size=12000,
            backup_type="hiddify",
            status="success",
            target_chat="-100123456",
            details_json=json.dumps({"users_count": 140}),
            trigger_type="manual"
        )
        self.assertTrue(r2["success"])

        # دریافت لاگ‌های پنل اصلی
        main_logs = self.db.get_backup_logs(backup_type="main_panel")
        self.assertTrue(any(l["backup_file"] == "backup_main_test.zip" for l in main_logs))
        self.assertFalse(any(l["backup_file"] == "backup_hiddify_test.json" for l in main_logs))

        # دریافت لاگ‌های هیدیفای
        hid_logs = self.db.get_backup_logs(backup_type="hiddify")
        self.assertTrue(any(l["backup_file"] == "backup_hiddify_test.json" for l in hid_logs))
        self.assertFalse(any(l["backup_file"] == "backup_main_test.zip" for l in hid_logs))

        # تست آمار خلاصه
        stats = self.db.get_backup_stats()
        self.assertIsNotNone(stats["last_main"])
        self.assertEqual(stats["last_main"]["backup_file"], "backup_main_test.zip")
        self.assertIsNotNone(stats["last_hiddify"])
        self.assertEqual(stats["last_hiddify"]["backup_file"], "backup_hiddify_test.json")

    def test_system_backup_metrics(self):
        """تست استخراج شاخص‌های سیستم جهت درج در گزارش"""
        conn = self.db.get_connection()
        c = conn.cursor()
        c.execute("INSERT INTO subscriptions (telegram_id, hidify_uuid, account_name, status, created_at, updated_at) VALUES (1, 'u1', 'a1', 'active', '2026-09-22', '2026-09-22')")
        c.execute("INSERT INTO subscriptions (telegram_id, hidify_uuid, account_name, status, created_at, updated_at) VALUES (2, 'u2', 'a2', 'expired', '2026-09-22', '2026-09-22')")
        c.execute("INSERT INTO users (telegram_id, username, created_at, updated_at) VALUES (1, 'user1', '2026-09-22', '2026-09-22')")
        conn.commit()
        conn.close()

        metrics = self.db.get_system_backup_metrics()
        self.assertGreaterEqual(metrics["total_subscriptions"], 2)
        self.assertGreaterEqual(metrics["active_subscriptions"], 1)
        self.assertGreaterEqual(metrics["total_users"], 1)
        self.assertIn("db_size_mb", metrics)

    def test_scheduler_fixed_hours_and_interval(self):
        """تست منطق زمان‌بندی ساعات مشخص و بازه ساعتی"""
        scheduler = AutoBackupScheduler()
        
        # تست ساعات مشخص
        self.assertTrue(scheduler._should_run_fixed_hours("00,06,12,18", 12))
        self.assertTrue(scheduler._should_run_fixed_hours("00,06,12,18", 0))
        self.assertFalse(scheduler._should_run_fixed_hours("00,06,12,18", 5))

        # تست بازه ساعتی
        now = datetime.now()
        four_hours_ago = now - timedelta(hours=4, minutes=5)
        two_hours_ago = now - timedelta(hours=2)

        # بازه ۳ ساعته: ۴ ساعت پیش باید اجرا شود، ۲ ساعت پیش نباید اجرا شود
        self.assertTrue(scheduler._should_run_interval(four_hours_ago, 3))
        self.assertFalse(scheduler._should_run_interval(two_hours_ago, 3))
        # در صورت نبود سابقه اجرا قبلی باید اجرا شود
        self.assertTrue(scheduler._should_run_interval(None, 3))

    def test_legacy_send_backup_to_admin_is_disabled(self):
        """تایید لغو ارسال به پی‌وی ادمین"""
        import asyncio
        res = asyncio.run(send_backup_to_admin())
        self.assertFalse(res["success"])
        self.assertIn("لغو شده است", res["error"])

    def test_format_file_size(self):
        self.assertEqual(format_file_size(500), "500 B")
        self.assertEqual(format_file_size(2048), "2.0 KB")
        self.assertEqual(format_file_size(2097152), "2.00 MB")


if __name__ == "__main__":
    unittest.main()
