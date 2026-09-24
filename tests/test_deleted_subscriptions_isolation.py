import unittest
import os
import tempfile
import sqlite3
from datetime import datetime, timezone

from database import Database, get_now_iso

class TestDeletedSubscriptionsIsolation(unittest.TestCase):
    def setUp(self):
        try:
            from cache_manager import cache
            cache.clear()
        except Exception:
            pass
        self.temp_db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self.temp_db.close()
        self.db_path = self.temp_db.name
        self.db = Database(self.db_path)

    def tearDown(self):
        try:
            from cache_manager import cache
            cache.clear()
        except Exception:
            pass
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except Exception:
                pass

    def test_admin_customer_deleted_sub_isolation_and_record_preservation(self):
        # 1. ساخت مشتری ادمین با ۲ اشتراک
        tg_id = 99887766
        self.db.save_user(telegram_id=tg_id, username="admin_cust")
        conn = self.db.get_connection()
        conn.execute("UPDATE users SET phone_number='09121112233' WHERE telegram_id=?", (tg_id,))
        conn.commit()
        conn.close()

        now_str = get_now_iso()
        # اشتراک ۱
        sub1_res = self.db.save_subscription(
            telegram_id=tg_id,
            hidify_uuid="uuid-admin-sub-1",
            plan_id="plan_30gb",
            plan_name="پلن ۳۰ گیگ",
            account_name="admin_sub_1",
            data_limit=30.0,
            duration=30,
            cost_paid=150000,
            reseller_id=None,
            status="active"
        )
        self.assertTrue(sub1_res.get("success"))
        sub1_id = sub1_res["subscription_id"]

        # اشتراک ۲
        sub2_res = self.db.save_subscription(
            telegram_id=tg_id,
            hidify_uuid="uuid-admin-sub-2",
            plan_id="plan_50gb",
            plan_name="پلن ۵۰ گیگ",
            account_name="admin_sub_2",
            data_limit=50.0,
            duration=30,
            cost_paid=220000,
            reseller_id=None,
            status="active"
        )
        self.assertTrue(sub2_res.get("success"))
        sub2_id = sub2_res["subscription_id"]

        # ثبت تراکنش‌ها و سوابق مصرف برای هر دو اشتراک
        conn = self.db.get_connection()
        conn.execute("""
            INSERT INTO transactions (order_id, user_id, username, subscription_id, renew_sub_id, amount, status, created_at, gateway)
            VALUES (?, ?, ?, ?, ?, ?, 'approved', ?, 'card')
        """, ("ORD_SUB1", tg_id, "admin_sub_1", sub1_id, sub1_id, 150000, now_str))

        conn.execute("""
            INSERT INTO transactions (order_id, user_id, username, subscription_id, renew_sub_id, amount, status, created_at, gateway)
            VALUES (?, ?, ?, ?, ?, ?, 'approved', ?, 'card')
        """, ("ORD_SUB2", tg_id, "admin_sub_2", sub2_id, sub2_id, 220000, now_str))

        conn.execute("""
            INSERT INTO subscription_history (subscription_id, telegram_id, account_name, plan_name, previous_usage_gb, previous_limit_gb, period_days, renewal_type, renewed_at)
            VALUES (?, ?, ?, 'پلن ۳۰ گیگ', 28.5, 30.0, 30, 'new_subscription', ?)
        """, (sub1_id, tg_id, "admin_sub_1", now_str))

        conn.execute("""
            INSERT INTO subscription_history (subscription_id, telegram_id, account_name, plan_name, previous_usage_gb, previous_limit_gb, period_days, renewal_type, renewed_at)
            VALUES (?, ?, ?, 'پلن ۵۰ گیگ', 12.0, 50.0, 30, 'new_subscription', ?)
        """, (sub2_id, tg_id, "admin_sub_2", now_str))
        conn.commit()
        conn.close()

        # قبل از حذف: هر دو اشتراک باید در get_user_subscriptions بازگردند
        subs_before = self.db.get_user_subscriptions(tg_id, is_admin_bot=True)
        self.assertEqual(len(subs_before), 2)

        # 2. حذف اشتراک ۱ توسط ادمین
        del_res = self.db.delete_customer_subscription(sub1_id, refund_to_customer=False, admin_name="مدیر کل", reason="درخواست کاربر")
        self.assertTrue(del_res.get("success"))

        # 3. بررسی عدم نمایش اشتراک حذف شده در لیست اشتراک‌های کاربر
        subs_after = self.db.get_user_subscriptions(tg_id, is_admin_bot=True)
        self.assertEqual(len(subs_after), 1)
        self.assertEqual(subs_after[0]["id"], sub2_id)
        self.assertEqual(subs_after[0]["account_name"], "admin_sub_2")

        # اشتراک فعال کاربر باید اشتراک ۲ باشد
        active_sub = self.db.get_active_subscription(tg_id, is_admin_bot=True)
        self.assertIsNotNone(active_sub)
        self.assertEqual(active_sub["id"], sub2_id)

        # 4. تضمین بقای سوابق تراکنش‌ها و پرداخت‌ها
        conn = self.db.get_connection()
        tx1 = conn.execute("SELECT * FROM transactions WHERE order_id='ORD_SUB1'").fetchone()
        self.assertIsNotNone(tx1, "تراکنش اشتراک ۱ نباید حذف شود")
        self.assertEqual(tx1["amount"], 150000)

        tx2 = conn.execute("SELECT * FROM transactions WHERE order_id='ORD_SUB2'").fetchone()
        self.assertIsNotNone(tx2, "تراکنش اشتراک ۲ نباید حذف شود")
        self.assertEqual(tx2["amount"], 220000)

        # 5. تضمین بقای سوابق دوره‌ها و مصرف در subscription_history
        hist1 = conn.execute("SELECT * FROM subscription_history WHERE subscription_id=?", (sub1_id,)).fetchone()
        self.assertIsNotNone(hist1, "سوابق دوره اشتراک ۱ نباید حذف شود")
        self.assertAlmostEqual(hist1["previous_usage_gb"], 28.5)

        hist2 = conn.execute("SELECT * FROM subscription_history WHERE subscription_id=?", (sub2_id,)).fetchone()
        self.assertIsNotNone(hist2, "سوابق دوره اشتراک ۲ نباید حذف شود")

        # 6. تضمین بقای پروفایل مشتری در دیتابیس
        u_row = conn.execute("SELECT * FROM users WHERE telegram_id=?", (tg_id,)).fetchone()
        self.assertIsNotNone(u_row, "پروفایل مشتری نباید بهم بریزد یا حذف شود")
        self.assertEqual(u_row["username"], "admin_cust")
        conn.close()

    def test_reseller_customer_deleted_sub_isolation_and_record_preservation(self):
        # 1. ساخت نماینده و مشتری نماینده با ۲ اشتراک
        r_id = 7
        conn = self.db.get_connection()
        conn.execute("INSERT OR IGNORE INTO resellers (id, name, username, balance) VALUES (?, 'نماینده تست', 'reseller_test', 500000)", (r_id,))
        conn.commit()
        conn.close()

        tg_id = 88776655
        self.db.save_user(telegram_id=tg_id, username="reseller_cust", reseller_id=r_id)

        now_str = get_now_iso()
        sub1_res = self.db.save_subscription(
            telegram_id=tg_id,
            hidify_uuid="uuid-reseller-sub-1",
            plan_id="r_plan_20",
            plan_name="پلن ۲۰ گیگ نماینده",
            account_name="reseller_sub_1",
            data_limit=20.0,
            duration=30,
            cost_paid=100000,
            reseller_id=r_id,
            status="active"
        )
        self.assertTrue(sub1_res.get("success"))
        sub1_id = sub1_res["subscription_id"]

        sub2_res = self.db.save_subscription(
            telegram_id=tg_id,
            hidify_uuid="uuid-reseller-sub-2",
            plan_id="r_plan_40",
            plan_name="پلن ۴۰ گیگ نماینده",
            account_name="reseller_sub_2",
            data_limit=40.0,
            duration=30,
            cost_paid=180000,
            reseller_id=r_id,
            status="active"
        )
        self.assertTrue(sub2_res.get("success"))
        sub2_id = sub2_res["subscription_id"]

        # ثبت تراکنش‌ها و دوره‌ها
        conn = self.db.get_connection()
        conn.execute("""
            INSERT INTO transactions (order_id, user_id, username, subscription_id, renew_sub_id, amount, status, created_at, reseller_id)
            VALUES (?, ?, ?, ?, ?, ?, 'approved', ?, ?)
        """, ("R_ORD_1", tg_id, "reseller_sub_1", sub1_id, sub1_id, 100000, now_str, r_id))

        conn.execute("""
            INSERT INTO subscription_history (subscription_id, telegram_id, account_name, plan_name, previous_usage_gb, previous_limit_gb, period_days, renewal_type, renewed_at, reseller_id)
            VALUES (?, ?, ?, 'پلن ۲۰ گیگ نماینده', 18.0, 20.0, 30, 'new_subscription', ?, ?)
        """, (sub1_id, tg_id, "reseller_sub_1", now_str, r_id))
        conn.commit()
        conn.close()

        # 2. حذف اشتراک ۱ توسط نماینده
        del_res = self.db.delete_reseller_subscription(r_id, sub1_id, reason="انتقال به سطل زباله")
        self.assertTrue(del_res.get("success"))

        # 3. بررسی لیست اشتراک‌های کاربر نماینده
        subs_after = self.db.get_user_subscriptions(tg_id, reseller_id=r_id)
        self.assertEqual(len(subs_after), 1)
        self.assertEqual(subs_after[0]["id"], sub2_id)
        self.assertEqual(subs_after[0]["account_name"], "reseller_sub_2")

        # 4. تضمین بقای تراکنش و سوابق دوره
        conn = self.db.get_connection()
        tx = conn.execute("SELECT * FROM transactions WHERE order_id='R_ORD_1'").fetchone()
        self.assertIsNotNone(tx)
        self.assertEqual(tx["amount"], 100000)

        hist = conn.execute("SELECT * FROM subscription_history WHERE subscription_id=?", (sub1_id,)).fetchone()
        self.assertIsNotNone(hist)
        self.assertAlmostEqual(hist["previous_usage_gb"], 18.0)
        conn.close()

    def test_single_subscription_customer_deleted_state(self):
        # مشتری با تنها ۱ اشتراک، که آن هم حذف شده است
        tg_id = 77665544
        self.db.save_user(telegram_id=tg_id, username="single_sub_user")

        sub_res = self.db.save_subscription(
            telegram_id=tg_id,
            hidify_uuid="uuid-single-sub",
            plan_id="p1",
            plan_name="پلن تک",
            account_name="single_sub_acc",
            data_limit=10.0,
            duration=30,
            cost_paid=50000,
            reseller_id=None,
            status="active"
        )
        sub_id = sub_res["subscription_id"]

        # حذف اشتراک
        self.db.delete_customer_subscription(sub_id, refund_to_customer=False)

        # باید لیست اشتراک‌های فعال خالی باشد
        subs = self.db.get_user_subscriptions(tg_id, is_admin_bot=True)
        self.assertEqual(len(subs), 0)

        # active subscription باید None باشد
        active = self.db.get_active_subscription(tg_id, is_admin_bot=True)
        self.assertIsNone(active)

        # اگر پارامتر include_deleted=True فرستاده شود، در صورت نیاز مدیریتی نمایش داده شود
        all_subs = self.db.get_user_subscriptions(tg_id, is_admin_bot=True, include_deleted=True)
        self.assertEqual(len(all_subs), 1)
        self.assertEqual(all_subs[0]["status"], "deleted")
        self.assertEqual(all_subs[0]["is_deleted"], 1)

if __name__ == "__main__":
    unittest.main()
