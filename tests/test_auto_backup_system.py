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

    def test_telegram_chat_id_normalization(self):
        """تست نرمال‌سازی شناسه‌های تلگرام و پاک‌سازی فرمت‌های مختلف"""
        from backup import normalize_telegram_chat_id
        self.assertEqual(normalize_telegram_chat_id("-5362393523"), "-5362393523")
        self.assertEqual(normalize_telegram_chat_id("5362393523-"), "-5362393523")
        self.assertEqual(normalize_telegram_chat_id(" 5362393523- "), "-5362393523")
        self.assertEqual(normalize_telegram_chat_id("-۵۳۶۲۳۹۳۵۲۳"), "-5362393523")
        self.assertEqual(normalize_telegram_chat_id("@backup_channel"), "@backup_channel")
        self.assertEqual(normalize_telegram_chat_id("-1001234567890"), "-1001234567890")
        self.assertEqual(normalize_telegram_chat_id(""), "")
        self.assertEqual(normalize_telegram_chat_id(None), "")

    def test_is_setting_enabled_resilience(self):
        """تست مقاومت متد is_setting_enabled در برابر باگ Type Coercion ناشی از json.loads و خالی شدن کش در ریستارت"""
        from cache_manager import cache

        # ۱. ذخیره به عنوان رشته "1" و پاک‌سازی کش (شبیه‌سازی ریستارت کانتینر در ریلوی)
        self.db.save_setting("test_railway_deploy_key", "1")
        cache.delete("setting:test_railway_deploy_key")
        
        # مقدار دریافتی از json.loads باید عدد صحیح 1 باشد
        raw_val = self.db.get_setting("test_railway_deploy_key")
        self.assertIsInstance(raw_val, int)
        self.assertEqual(raw_val, 1)
        # در کد قدیمی 1 == "1" فالس می‌شد:
        self.assertFalse(raw_val == "1")
        # اما با متد جدید is_setting_enabled دقیقاً True برمی‌گرداند
        self.assertTrue(self.db.is_setting_enabled("test_railway_deploy_key"))

        # ۲. ذخیره مقدار "0"
        self.db.save_setting("test_railway_deploy_key", "0")
        cache.delete("setting:test_railway_deploy_key")
        self.assertFalse(self.db.is_setting_enabled("test_railway_deploy_key"))

        # ۳. انواع مقادیر متنی و بولین
        self.db.save_setting("test_true_str", "true")
        self.assertTrue(self.db.is_setting_enabled("test_true_str"))
        self.db.save_setting("test_false_str", "false")
        self.assertFalse(self.db.is_setting_enabled("test_false_str"))

        # ۴. کلید ناموجود با مقدار پیش‌فرض
        self.assertTrue(self.db.is_setting_enabled("non_existing_key", default=True))
        self.assertFalse(self.db.is_setting_enabled("non_existing_key", default=False))

    def test_scheduler_fixed_hours_tehran_timezone_and_daily_slots(self):
        """تست اجرای زمان‌بندی ساعات مشخص به وقت تهران و حل باگ اجرای روزهای بعد"""
        from utils import TEHRAN_TZ
        scheduler = AutoBackupScheduler()

        # زمان فرضی ساعت ۱۲:۰۵ به وقت تهران
        dt_day1_1205 = datetime(2026, 9, 23, 12, 5, tzinfo=TEHRAN_TZ)
        slot_empty = None
        last_run_none = None

        # بار اول در ساعت ۱۲ باید اجرا شود
        should_run = scheduler._should_run_fixed_hours("00,06,12,18", dt_day1_1205, slot_empty, last_run_none)
        self.assertTrue(should_run)

        # پس از اجرا، اسلات برای ساعت ۱۲ روز جاری ثبت می‌شود
        slot_day1_12 = (2026, 9, 23, 12)
        last_run_recent = dt_day1_1205

        # در دقایق بعدی همان ساعت ۱۲ (مثلاً ۱۲:۰۶) نباید مجدداً اجرا شود
        dt_day1_1206 = datetime(2026, 9, 23, 12, 6, tzinfo=TEHRAN_TZ)
        self.assertFalse(scheduler._should_run_fixed_hours("00,06,12,18", dt_day1_1206, slot_day1_12, last_run_recent))

        # اگر قبلاً در این اسلات اجرا شده، در دقایق بعدی (مثلاً ۱۲:۲۰) نباید مجدداً اجرا شود
        dt_day1_1220 = datetime(2026, 9, 23, 12, 20, tzinfo=TEHRAN_TZ)
        self.assertFalse(scheduler._should_run_fixed_hours("00,06,12,18", dt_day1_1220, slot_day1_12, last_run_recent))
        # اما اگر هنوز در این اسلات اجرا نشده بود، حتی بعد از دقیقه ۱۵ (مثلاً ۱۲:۲۰) باید اجرا شود
        self.assertTrue(scheduler._should_run_fixed_hours("00,06,12,18", dt_day1_1220, (2026, 9, 23, 6), None))

        # در ساعت غیرمجاز (مثلاً ساعت ۱۳) نباید اجرا شود
        dt_day1_1305 = datetime(2026, 9, 23, 13, 5, tzinfo=TEHRAN_TZ)
        self.assertFalse(scheduler._should_run_fixed_hours("00,06,12,18", dt_day1_1305, slot_day1_12, last_run_recent))

        # ساعت مقرر بعدی (ساعت ۱۸:۰۲) باید به درستی اجرا شود
        dt_day1_1802 = datetime(2026, 9, 23, 18, 2, tzinfo=TEHRAN_TZ)
        self.assertTrue(scheduler._should_run_fixed_hours("00,06,12,18", dt_day1_1802, slot_day1_12, last_run_recent))

        # روز بعد در همان ساعت ۱۲:۰۵ (رفع باگ روز بعد که قبلاً به خاطر last_checked_hour اجرا نمی‌شد):
        dt_day2_1205 = datetime(2026, 9, 24, 12, 5, tzinfo=TEHRAN_TZ)
        slot_day1_18 = (2026, 9, 23, 18)
        self.assertTrue(scheduler._should_run_fixed_hours("00,06,12,18", dt_day2_1205, slot_day1_18, last_run_recent))

    def test_scheduler_state_restoration_from_db(self):
        """تست بازخوانی موفقیت‌آمیز سابقه آخرین بکاپ از دیتابیس در زمان راه‌اندازی زمان‌بند"""
        from utils import get_now_iso
        now_iso = get_now_iso()

        # ذخیره یک رکورد بکاپ موفق در دیتابیس
        self.db.save_backup_record(
            backup_file="restore_test.zip",
            backup_size=1024,
            backup_type="main_panel",
            status="success",
            target_chat="-10099999"
        )

        # ساخت نمونه جدید زمان‌بند و بازخوانی سابقه با دیتابیس تست
        scheduler = AutoBackupScheduler(db_instance=self.db)
        self.assertIsNone(scheduler.last_main_run_time)
        scheduler._load_last_run_times_from_db()
        self.assertIsNotNone(scheduler.last_main_run_time)
        self.assertIsNotNone(scheduler.last_main_slot)

    def test_restore_backup_from_zip_and_db(self):
        """تست جامع بازیابی دیتابیس از فایل Zip، فایل db و حفاظت در برابر فایل‌های معیوب"""
        bm = BackupManager(db_instance=self.db)

        # ۱. درج دیتای اولیه
        conn = self.db.get_connection()
        c = conn.cursor()
        c.execute("INSERT INTO users (telegram_id, username, created_at, updated_at) VALUES (99999, 'user_to_backup', '2026-09-22', '2026-09-22')")
        conn.commit()
        conn.close()

        # ۲. ایجاد بکاپ زیپ
        backup_res = bm.create_database_backup(compress=True)
        self.assertTrue(backup_res["success"])
        zip_path = Path(backup_res["file"])
        self.assertTrue(zip_path.exists())

        # ۳. تغییر دیتای دیتابیس فعلی
        conn = self.db.get_connection()
        c = conn.cursor()
        c.execute("DELETE FROM users WHERE telegram_id = 99999")
        c.execute("INSERT INTO users (telegram_id, username, created_at, updated_at) VALUES (88888, 'temp_user', '2026-09-22', '2026-09-22')")
        conn.commit()
        conn.close()

        # اطمینان از اینکه دیتای فعلی تغییر کرده
        users = self.db.get_all_users()
        self.assertTrue(any(u["telegram_id"] == 88888 for u in users))
        self.assertFalse(any(u["telegram_id"] == 99999 for u in users))

        # ۴. بازیابی از فایل زیپ
        restore_res = bm.restore_backup(zip_path)
        self.assertTrue(restore_res["success"])

        # ۵. بررسی بازیابی موفقیت‌آمیز دیتای قبلی و عدم وجود دیتای تستی
        restored_users = self.db.get_all_users()
        self.assertTrue(any(u["telegram_id"] == 99999 for u in restored_users))
        self.assertFalse(any(u["telegram_id"] == 88888 for u in restored_users))

        # ۶. تست عدم پذیرش فایل خراب یا نامعتبر
        corrupt_file = zip_path.parent / "corrupt_test.db"
        corrupt_file.write_text("NOT A VALID SQLITE DATABASE CONTENT")
        bad_res = bm.restore_backup(corrupt_file)
        self.assertFalse(bad_res["success"])
        self.assertIn("معتبر", bad_res["error"])

        # پاک‌سازی فایل‌های موقت تست
        try:
            zip_path.unlink(missing_ok=True)
            corrupt_file.unlink(missing_ok=True)
        except Exception:
            pass


if __name__ == "__main__":
    unittest.main()

