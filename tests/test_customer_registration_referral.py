#!/usr/bin/env python3
"""
آزمون‌های جامع ثبت‌نام مشتری جدید با کادر معرف و لینک کسب درآمد بر اساس دامنه
"""

import os
import sys
import unittest
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from database import Database, normalize_phone_number


class TestCustomerRegistrationReferral(unittest.TestCase):
    def setUp(self):
        self.temp_db_fd, self.temp_db_path = tempfile.mkstemp(suffix=".db")
        self.test_db = Database(db_path=self.temp_db_path)

    def tearDown(self):
        try:
            os.close(self.temp_db_fd)
            os.remove(self.temp_db_path)
        except Exception:
            pass

    def test_phone_number_normalization(self):
        """تست نرمال‌سازی انواع فرمت‌های شماره تلفن همراه (فارسی، عربی، بین‌المللی)"""
        # شماره استاندارد ۱۱ رقمی
        self.assertEqual(normalize_phone_number("09121234567"), "09121234567")
        # با پیش‌شماره بین‌المللی +98
        self.assertEqual(normalize_phone_number("+989121234567"), "09121234567")
        # با پیش‌شماره 0098
        self.assertEqual(normalize_phone_number("00989121234567"), "09121234567")
        # با پیش‌شماره 98
        self.assertEqual(normalize_phone_number("989121234567"), "09121234567")
        # بدون صفر اول (۱۰ رقمی)
        self.assertEqual(normalize_phone_number("9121234567"), "09121234567")
        # با ارقام فارسی
        self.assertEqual(normalize_phone_number("۰۹۱۲۱۲۳۴۵۶۷"), "09121234567")
        # با ارقام عربی
        self.assertEqual(normalize_phone_number("٠٩١٢١٢٣٤٥٦٧"), "09121234567")
        # با خط فاصله و فاصله
        self.assertEqual(normalize_phone_number("0912-123-4567"), "09121234567")
        self.assertEqual(normalize_phone_number(" 0912 123 4567 "), "09121234567")
        # شماره‌های نامعتبر
        self.assertIsNone(normalize_phone_number("02188888888"))
        self.assertIsNone(normalize_phone_number("12345"))
        self.assertIsNone(normalize_phone_number("invalid_phone"))
        self.assertIsNone(normalize_phone_number(""))

    def test_customer_registration_without_referrer(self):
        """تست ثبت‌نام عادی مشتری بدون معرف"""
        res = self.test_db.register_customer_user(
            phone="09121111111",
            username="ali_reza",
            password="secure_password_123",
            reseller_id=0
        )
        self.assertTrue(res["success"])
        self.assertFalse(res["has_referrer"])
        self.assertEqual(res["phone_number"], "09121111111")
        self.assertTrue(res["telegram_id"] < 0)  # شناسه منفی یکتا برای وب

        # بررسی بازیابی کاربر
        user = self.test_db.get_customer_user_by_phone("09121111111")
        self.assertIsNotNone(user)
        self.assertEqual(user["username"], "ali_reza")
        self.assertEqual(user["telegram_id"], res["telegram_id"])

        # احراز هویت
        auth = self.test_db.authenticate_customer_user("09121111111", "secure_password_123")
        self.assertTrue(auth["success"])

        # رمز اشتباه
        auth_bad = self.test_db.authenticate_customer_user("09121111111", "wrong_pass")
        self.assertFalse(auth_bad["success"])

    def test_customer_registration_duplicate_phone_prevention(self):
        """جلوگیری از ثبت‌نام شماره تکراری در همان قلمرو"""
        res1 = self.test_db.register_customer_user(
            phone="09122222222",
            username="user_one",
            password="pass"
        )
        self.assertTrue(res1["success"])

        res2 = self.test_db.register_customer_user(
            phone="09122222222",
            username="user_two",
            password="pass"
        )
        self.assertFalse(res2["success"])
        self.assertEqual(res2["error"], "already_registered")

    def test_customer_registration_with_referrer_and_reward(self):
        """تست ثبت‌نام با معرف شماره موبایل و دریافت پاداش در کیف پول"""
        # ۱. ایجاد کاربر معرف
        ref_user = self.test_db.register_customer_user(
            phone="09123333333",
            username="mohammad_ref",
            password="pass",
            reseller_id=0
        )
        self.assertTrue(ref_user["success"])

        # فعال‌سازی سیستم رفرال ادمین
        self.test_db.save_customer_referral_config(0, {
            "is_enabled": True,
            "reward_type": "percent",
            "reward_amount": 10,
            "min_purchase_amount": 50000,
            "max_daily_rewards": 5
        })

        # ۲. ثبت‌نام کاربر جدید با شماره معرف
        new_cust = self.test_db.register_customer_user(
            phone="09124444444",
            username="new_friend",
            password="pass",
            referrer_phone="09123333333",
            reseller_id=0
        )
        self.assertTrue(new_cust["success"])
        self.assertTrue(new_cust["has_referrer"])

        # آمار رفرال معرف قبل از خرید: ۱ دعوت ثبت‌شده، ۰ پاداش
        stats_before = self.test_db.get_customer_referral_stats(ref_user["telegram_id"], reseller_id=0)
        self.assertEqual(stats_before["total_invites"], 1)
        self.assertEqual(stats_before["rewarded_invites"], 0)
        self.assertEqual(stats_before["wallet_balance"], 0)

        # ۳. خرید بسته توسط کاربر جدید به مبلغ ۱۰۰ هزار تومان
        comp_res = self.test_db.complete_customer_referral(
            referred_id=new_cust["telegram_id"],
            order_amount=100000,
            reseller_id=0
        )
        self.assertTrue(comp_res["success"])
        self.assertEqual(comp_res["reward_amount"], 10000)  # ۱۰ درصد ۱۰۰ هزار تومان

        # ۴. بررسی موجودی کیف پول و آمار معرف پس از پاداش
        stats_after = self.test_db.get_customer_referral_stats(ref_user["telegram_id"], reseller_id=0)
        self.assertEqual(stats_after["total_invites"], 1)
        self.assertEqual(stats_after["rewarded_invites"], 1)
        self.assertEqual(stats_after["total_reward"], 10000)
        self.assertEqual(stats_after["wallet_balance"], 10000)

    def test_collision_dilemma_resolution(self):
        """
        حل چالش برخورد شماره معرف در لیست ۲ نماینده مختلف:
        - اگر ثبت‌نام در دامنه اختصاصی نماینده A انجام شود -> به نماینده A تعلق می‌گیرد
        - اگر ثبت‌نام در دامنه اختصاصی نماینده B انجام شود -> به نماینده B تعلق می‌گیرد
        - اگر ثبت‌نام روی دامنه عمومی بدون نماینده انجام شود -> اولویت با اشتراک فعال و جدیدتر
        """
        shared_phone = "09129999999"

        # ایجاد اشتراک منقضی در نماینده ۱ (reseller_id=1)
        conn = self.test_db.get_connection()
        conn.execute("""
            INSERT INTO subscriptions (hidify_uuid, account_name, phone_number, reseller_id, status, telegram_id, is_deleted, created_at, updated_at)
            VALUES ('uuid-res-1', 'کاربر نماینده ۱', ?, 1, 'expired', 11111, 0, '2026-01-01', '2026-01-01')
        """, (shared_phone,))

        # ایجاد اشتراک فعال در نماینده ۲ (reseller_id=2)
        conn.execute("""
            INSERT INTO subscriptions (hidify_uuid, account_name, phone_number, reseller_id, status, telegram_id, is_deleted, created_at, updated_at)
            VALUES ('uuid-res-2', 'کاربر نماینده ۲', ?, 2, 'active', 22222, 0, '2026-02-01', '2026-02-01')
        """, (shared_phone,))
        conn.commit()
        conn.close()

        # تست لایه ۱: دامنه اختصاصی نماینده ۱
        ref_res1 = self.test_db.lookup_customer_referrer_by_phone(shared_phone, domain_reseller_id=1)
        self.assertIsNotNone(ref_res1)
        self.assertEqual(ref_res1["reseller_id"], 1)
        self.assertEqual(ref_res1["account_name"], "کاربر نماینده ۱")

        # تست لایه ۱: دامنه اختصاصی نماینده ۲
        ref_res2 = self.test_db.lookup_customer_referrer_by_phone(shared_phone, domain_reseller_id=2)
        self.assertIsNotNone(ref_res2)
        self.assertEqual(ref_res2["reseller_id"], 2)
        self.assertEqual(ref_res2["account_name"], "کاربر نماینده ۲")

        # تست لایه ۲ و ۳: دامنه عمومی بدون نماینده (اولویت با اشتراک فعال) -> باید نماینده ۲ را انتخاب کند
        ref_general = self.test_db.lookup_customer_referrer_by_phone(shared_phone, domain_reseller_id=None)
        self.assertIsNotNone(ref_general)
        self.assertEqual(ref_general["reseller_id"], 2)
        self.assertEqual(ref_general["status"], "active")

    def test_anti_fraud_self_referral(self):
        """سپر ضد تقلب: عدم امکان معرفی شماره خود به عنوان معرف"""
        res = self.test_db.register_customer_user(
            phone="09125555555",
            username="self_hacker",
            password="pass",
            referrer_phone="09125555555"
        )
        self.assertFalse(res["success"])
        self.assertEqual(res["error"], "self_referral")

    def test_flask_routes_registration_and_referral(self):
        """تست روت‌های فلسک: ثبت‌نام وب، استعلام معرف، و تولید لینک پورتال"""
        from dashboard import app
        app.config["TESTING"] = True
        app.config["SECRET_KEY"] = "test-secret-key"
        client = app.test_client()

        # ۱. تست صفحه ثبت‌نام با پارامترهای ref و r
        res_get = client.get("/register?ref=09121234567&r=0")
        self.assertEqual(res_get.status_code, 200)
        html_get = res_get.get_data(as_text=True)
        self.assertIn("09121234567", html_get)
        self.assertIn("ثبت‌نام مشتری جدید", html_get)

        # ۲. تست وب‌سرویس استعلام آنلاین معرف با شماره نامعتبر
        res_api_none = client.get("/api/customer/lookup-referrer?phone=09990000000")
        self.assertEqual(res_api_none.status_code, 200)
        json_none = res_api_none.get_json()
        self.assertTrue(json_none["success"])
        self.assertFalse(json_none["found"])

        # ۳. ثبت‌نام یک معرف آزمایشی با مشخصات یکتا جهت جلوگیری از تداخل در اجراهای مجدد
        import random
        rnd1 = random.randint(1000000, 9999999)
        rnd2 = random.randint(1000000, 9999999)
        ref_phone = f"0912{rnd1}"
        new_cust_phone = f"0919{rnd2}"
        ref_user = f"ref_usr_{rnd1}"
        new_user = f"new_usr_{rnd2}"

        from database import db as live_db
        live_db.register_customer_user(
            phone=ref_phone,
            username=ref_user,
            password="pass123",
            reseller_id=0
        )

        # ۴. تست استعلام آنلاین معرف با شماره ثبت‌شده
        res_api_found = client.get(f"/api/customer/lookup-referrer?phone={ref_phone}")
        self.assertEqual(res_api_found.status_code, 200)
        json_found = res_api_found.get_json()
        self.assertTrue(json_found["success"])
        self.assertTrue(json_found["found"])
        self.assertIn(ref_user, json_found["referrer_name"])

        # ۵. تست ثبت‌نام کاربر جدید از طریق POST فرم /register
        res_post = client.post("/register", data={
            "username": new_user,
            "phone": new_cust_phone,
            "password": "mypassword",
            "referrer_phone": ref_phone,
            "reseller_id": "0"
        }, follow_redirects=False)
        self.assertEqual(res_post.status_code, 302)
        self.assertIn("/portal", res_post.headers["Location"])

        # ۶. تست باز شدن پورتال مشتری با آیدی کاربر وب و نمایش لینک‌های کسب درآمد
        portal_res = client.get(res_post.headers["Location"])
        self.assertEqual(portal_res.status_code, 200)
        portal_html = portal_res.get_data(as_text=True)
        self.assertIn("customerWebRefLinkInput", portal_html)
        self.assertIn("customerRefCodeInput", portal_html)
        self.assertIn(new_cust_phone, portal_html)

    def test_telegram_auth_direct_flow(self):
        """تست احراز هویت مستقیم تلگرام بدون نیاز به OAuth و بدون وابستگی به دامین"""
        from dashboard import app

        token = "test_token_1234567890abcdef"
        created = self.test_db.create_telegram_auth_session(
            token=token,
            reseller_id=0,
            referrer="09129999999",
            origin_host="https://i.gotel.ir"
        )
        self.assertTrue(created)

        # بررسی جلسه در حالت انتظار
        sess = self.test_db.get_telegram_auth_session(token)
        self.assertIsNotNone(sess)
        self.assertEqual(sess["status"], "pending")
        self.assertEqual(sess["referrer"], "09129999999")
        self.assertEqual(sess["origin_host"], "https://i.gotel.ir")

        # تست endpointهای dashboard
        app.config["TESTING"] = True
        client = app.test_client()

        # ۱. تست init
        init_res = client.post("/api/customer/telegram-auth/init", json={
            "reseller_id": 0,
            "ref": "09129999999",
            "origin_host": "https://i.gotel.ir"
        })
        self.assertEqual(init_res.status_code, 200)
        init_data = init_res.get_json()
        self.assertTrue(init_data["success"])
        self.assertIn("token", init_data)
        self.assertIn("tg_url", init_data)
        new_token = init_data["token"]

        # ۲. تست check در حالت pending
        chk_res = client.get(f"/api/customer/telegram-auth/check?token={new_token}")
        self.assertEqual(chk_res.status_code, 200)
        chk_data = chk_res.get_json()
        self.assertEqual(chk_data["status"], "pending")

        # ۳. تایید نشست توسط ربات
        from database import db as live_db
        approved = live_db.approve_telegram_auth_session(
            token=new_token,
            telegram_id=987654321,
            first_name="Test User",
            username="testuser"
        )
        self.assertTrue(approved)

        # ۴. تست check بعد از تایید (باید approved و redirect_url بدهد)
        chk_res2 = client.get(f"/api/customer/telegram-auth/check?token={new_token}")
        self.assertEqual(chk_res2.status_code, 200)
        chk_data2 = chk_res2.get_json()
        self.assertEqual(chk_data2["status"], "approved")
        self.assertIn("/portal", chk_data2["redirect_url"])


if __name__ == "__main__":
    unittest.main()

