#!/usr/bin/env python3
"""
آزمون‌های جامع سیستم کسب درآمد و دعوت از دوستان برای مشتریان
و سپرهای ضد تقلب زیرمجموعه‌گیری همکاران
"""

import os
import sys
import unittest
import tempfile
import sqlite3

# افزودن روت پروژه به مسیر
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from database import Database, db


class TestCustomerAndResellerReferrals(unittest.TestCase):
    def setUp(self):
        # ساخت دیتابیس موقت در حافظه برای تست ایزوله
        self.temp_db_fd, self.temp_db_path = tempfile.mkstemp(suffix=".db")
        self.test_db = Database(db_path=self.temp_db_path)

    def tearDown(self):
        # بستن و حذف فایل موقت دیتابیس
        try:
            os.close(self.temp_db_fd)
            os.remove(self.temp_db_path)
        except Exception:
            pass

    def test_customer_referral_config_isolation(self):
        """تست تفکیک و ایزولاسیون تنظیمات بین مدیریت و نمایندگان"""
        # تنظیمات پیش‌فرض ادمین (reseller_id=0)
        admin_cfg = self.test_db.get_customer_referral_config(reseller_id=0)
        self.assertIsNotNone(admin_cfg)
        self.assertTrue(admin_cfg["is_enabled"])

        # تغییر تنظیمات ادمین
        self.test_db.save_customer_referral_config(0, {
            "is_enabled": True,
            "reward_type": "fixed",
            "reward_amount": 15000,
            "min_purchase_amount": 60000,
            "max_daily_rewards": 10,
            "reward_condition": "first_purchase",
            "custom_text": "پاداش مدیریت"
        })

        # تنظیمات نماینده ۱ (reseller_id=1)
        self.test_db.save_customer_referral_config(1, {
            "is_enabled": False,
            "reward_type": "percent",
            "reward_amount": 25,
            "min_purchase_amount": 100000,
            "max_daily_rewards": 3,
            "reward_condition": "all_purchases",
            "custom_text": "پاداش نماینده ۱"
        })

        # اعتبارسنجی ایزولاسیون کامل
        cfg0 = self.test_db.get_customer_referral_config(0)
        cfg1 = self.test_db.get_customer_referral_config(1)

        self.assertEqual(cfg0["reward_amount"], 15000)
        self.assertEqual(cfg0["min_purchase_amount"], 60000)
        self.assertTrue(cfg0["is_enabled"])
        self.assertEqual(cfg0["custom_text"], "پاداش مدیریت")

        self.assertEqual(cfg1["reward_amount"], 25)
        self.assertEqual(cfg1["reward_type"], "percent")
        self.assertEqual(cfg1["min_purchase_amount"], 100000)
        self.assertFalse(cfg1["is_enabled"])
        self.assertEqual(cfg1["custom_text"], "پاداش نماینده ۱")

    def test_customer_anti_fraud_self_referral(self):
        """سپر ضد تقلب ۱: جلوگیری از خود-دعوتی (Self-Referral)"""
        res = self.test_db.add_customer_referral(referrer_id=1001, referred_id=1001, reseller_id=0)
        self.assertFalse(res["success"])
        self.assertEqual(res["error"], "self_referral")

    def test_customer_referral_disabled(self):
        """سپر ضد تقلب ۲: مسدود شدن ثبت رفرال هنگام غیرفعال بودن سیستم در آن قلمرو"""
        self.test_db.save_customer_referral_config(2, {"is_enabled": False})
        res = self.test_db.add_customer_referral(referrer_id=1001, referred_id=1002, reseller_id=2)
        self.assertFalse(res["success"])
        self.assertEqual(res["error"], "referral_disabled")

    def test_customer_anti_fraud_circular_referral(self):
        """سپر ضد تقلب ۳: جلوگیری از دعوت چرخه‌ای (A دعوت B و B دعوت A)"""
        # A دعوت B را انجام می‌دهد
        res1 = self.test_db.add_customer_referral(referrer_id=2001, referred_id=2002, reseller_id=0)
        self.assertTrue(res1["success"])

        # B تلاش می‌کند A را دعوت کند -> باید رد شود
        res2 = self.test_db.add_customer_referral(referrer_id=2002, referred_id=2001, reseller_id=0)
        self.assertFalse(res2["success"])
        self.assertEqual(res2["error"], "circular_referral")

    def test_customer_anti_fraud_already_referred(self):
        """سپر ضد تقلب ۴: قفل یک‌باره معرف (کاربر فقط یک‌بار می‌تواند معرف داشته باشد)"""
        # معرف ۱ کاربر B را دعوت می‌کند
        res1 = self.test_db.add_customer_referral(referrer_id=3001, referred_id=3002, reseller_id=0)
        self.assertTrue(res1["success"])

        # معرف ۲ تلاش می‌کند کاربر B را مجدداً دعوت کند -> باید رد شود
        res2 = self.test_db.add_customer_referral(referrer_id=3003, referred_id=3002, reseller_id=0)
        self.assertFalse(res2["success"])
        self.assertEqual(res2["error"], "already_referred")

    def test_customer_anti_fraud_already_customer(self):
        """سپر ضد تقلب ۵: کاربر قدیمی با اشتراک قبلی نمی‌تواند به عنوان کاربر جدید معرفی شود"""
        # فعال‌سازی رفرال برای نماینده ۵
        self.test_db.save_customer_referral_config(5, {"is_enabled": True})

        # ثبت یک اشتراک قبلی برای کاربر ۴۰۰۲ در قلمرو نماینده ۵
        self.test_db.save_subscription(
            telegram_id=4002,
            hidify_uuid="uuid-test-4002",
            plan_id="p1",
            plan_name="بسته تستی",
            data_limit=10,
            duration=30,
            reseller_id=5,
            created_by="test"
        )

        # تلاش برای ثبت معرف برای این کاربر در قلمرو نماینده ۵ -> باید رد شود
        res = self.test_db.add_customer_referral(referrer_id=4001, referred_id=4002, reseller_id=5)
        self.assertFalse(res["success"])
        self.assertEqual(res["error"], "already_customer")

    def test_customer_referral_reward_completion_and_min_amount(self):
        """تست اعطای پاداش رفرال با بررسی شرط حداقل خرید بسته و شارژ کیف پول"""
        # تنظیم حداقل خرید ۵۰,۰۰۰ تومان و پاداش ثابت ۱۰,۰۰۰ تومان برای ادمین
        self.test_db.save_customer_referral_config(0, {
            "is_enabled": True,
            "reward_type": "fixed",
            "reward_amount": 10000,
            "min_purchase_amount": 50000,
            "max_daily_rewards": 5,
            "reward_condition": "first_purchase"
        })

        # ثبت رفرال
        add_res = self.test_db.add_customer_referral(referrer_id=5001, referred_id=5002, reseller_id=0)
        self.assertTrue(add_res["success"])

        # تلاش ۱: خرید بسته با مبلغ کمتر از حداقل (مثلاً اکانت تست یا ۲۰,۰۰۰ تومان) -> پاداش تعلق نمی‌گیرد
        comp_fail = self.test_db.complete_customer_referral(referred_id=5002, order_amount=20000, reseller_id=0)
        self.assertFalse(comp_fail["success"])
        self.assertEqual(comp_fail["reason"], "order_amount_below_minimum")

        # کیف پول معرف باید همچنان صفر باشد
        bal1 = self.test_db.get_user_wallet_balance(5001)
        self.assertEqual(bal1, 0)

        # تلاش ۲: خرید بسته معتبر با مبلغ ۷۵,۰۰۰ تومان -> پاداش با موفقیت پرداخت می‌شود
        comp_ok = self.test_db.complete_customer_referral(referred_id=5002, order_amount=75000, reseller_id=0)
        self.assertTrue(comp_ok["success"])
        self.assertEqual(comp_ok["reward_amount"], 10000)

        # موجودی کیف پول معرف باید به ۱۰,۰۰۰ تومان افزایش یافته باشد
        bal2 = self.test_db.get_user_wallet_balance(5001)
        self.assertEqual(bal2, 10000)

        # آمار رفرال معرف
        stats = self.test_db.get_customer_referral_stats(user_id=5001, reseller_id=0)
        self.assertEqual(stats["total_referred"], 1)
        self.assertEqual(stats["completed_referrals"], 1)
        self.assertEqual(stats["total_earnings"], 10000)
        self.assertEqual(stats["wallet_balance"], 10000)

    def test_customer_referral_rate_limit(self):
        """سپر ضد تقلب ۶: سقف روزانه پاداش (Rate Limiting)"""
        # تنظیم سقف روزانه حداکثر ۲ پاداش در ۲۴ ساعت
        self.test_db.save_customer_referral_config(0, {
            "is_enabled": True,
            "reward_type": "fixed",
            "reward_amount": 5000,
            "min_purchase_amount": 10000,
            "max_daily_rewards": 2,
            "reward_condition": "all_purchases"
        })

        # معرفی ۳ کاربر توسط معرف ۶۰۰۱
        self.test_db.add_customer_referral(6001, 6002, reseller_id=0)
        self.test_db.add_customer_referral(6001, 6003, reseller_id=0)
        self.test_db.add_customer_referral(6001, 6004, reseller_id=0)

        # خرید کاربر ۱ -> پاداش اول (موفق)
        c1 = self.test_db.complete_customer_referral(6002, order_amount=30000, reseller_id=0)
        self.assertTrue(c1["success"])

        # خرید کاربر ۲ -> پاداش دوم (موفق)
        c2 = self.test_db.complete_customer_referral(6003, order_amount=30000, reseller_id=0)
        self.assertTrue(c2["success"])

        # خرید کاربر ۳ -> رسیدن به سقف ۲ پاداش در روز -> باید رد شود
        c3 = self.test_db.complete_customer_referral(6004, order_amount=30000, reseller_id=0)
        self.assertFalse(c3["success"])
        self.assertEqual(c3["reason"], "daily_limit_reached")

    def test_reseller_sub_affiliate_anti_fraud(self):
        """سپرهای ضد تقلب همکاران و نمایندگان: تشخیص سوءاستفاده چندپنلی (Self-Reselling)"""
        # ساخت نماینده مادر با مشخصات معین
        res_info = self.test_db.create_reseller(
            username="reseller_boss",
            password="pwd",
            name="نماینده اصلی",
            telegram_id=990011
        )
        parent_id = res_info["reseller_id"]
        # افزودن اطلاعات تماس و کارت برای نماینده مادر
        conn = self.test_db.get_connection()
        conn.execute(
            "UPDATE resellers SET phone = ?, bank_card = ? WHERE id = ?",
            ("09121112233", "6037991812345678", parent_id)
        )
        conn.commit()
        conn.close()

        # متقاضی ۱: شماره کارت بانکی یکسان دارد -> تقلب
        fraud_card = self.test_db.check_reseller_self_affiliate_fraud(
            parent_id=parent_id,
            sub_data_or_id={"card_number": "6037-9918-1234-5678", "phone": "09359998877", "telegram_id": 990022}
        )
        self.assertTrue(fraud_card["fraud_detected"])
        self.assertIn("bank_card", fraud_card["matched_fields"])

        # متقاضی ۲: شماره تماس یکسان دارد -> تقلب
        fraud_phone = self.test_db.check_reseller_self_affiliate_fraud(
            parent_id=parent_id,
            sub_data_or_id={"card_number": "5892101234567890", "phone": "+989121112233", "telegram_id": 990033}
        )
        self.assertTrue(fraud_phone["fraud_detected"])
        self.assertIn("phone", fraud_phone["matched_fields"])

        # متقاضی ۳: آیدی تلگرام یکسان دارد -> تقلب
        fraud_tg = self.test_db.check_reseller_self_affiliate_fraud(
            parent_id=parent_id,
            sub_data_or_id={"card_number": "5892101234567890", "phone": "09351234567", "telegram_id": 990011}
        )
        self.assertTrue(fraud_tg["fraud_detected"])
        self.assertIn("telegram_id", fraud_tg["matched_fields"])

        # متقاضی ۴: مشخصات کاملاً مستقل و متفاوت دارد -> معتبر
        clean_applicant = self.test_db.check_reseller_self_affiliate_fraud(
            parent_id=parent_id,
            sub_data_or_id={"card_number": "5022291012345678", "phone": "09367778899", "telegram_id": 880055}
        )
        self.assertFalse(clean_applicant["fraud_detected"])

    def test_reseller_affiliate_quota_and_commission(self):
        """تست سهمیه فعالیت ماهانه و پرداخت پورسانت زیرمجموعه‌گیری همکاران"""
        # ایجاد نماینده بالادست و زیرمجموعه
        parent = self.test_db.create_reseller(username="parent_res", password="p", name="بالادست")
        parent_id = parent["reseller_id"]

        sub = self.test_db.create_reseller(
            username="sub_res", password="p", name="زیرمجموعه",
            parent_reseller_id=parent_id
        )
        sub_id = sub["reseller_id"]

        # ۱. تنظیم سهمیه ماهانه: حداقل ۵ فروش یا ۵۰۰,۰۰۰ تومان گردش مالی ۳۰ روزه
        self.test_db.update_reseller_affiliate_settings(
            enabled=True,
            default_percent=10.0,
            calc_base="selling_price",
            terms="شرایط همکاری",
            anti_fraud_enabled=True,
            min_monthly_sales=5,
            min_monthly_turnover=500000
        )

        # بدون داشتن فروش کافی توسط نماینده بالادست -> پورسانت رد می‌شود
        comm_fail = self.test_db.process_sub_reseller_affiliate_commission(
            sub_reseller_id=sub_id,
            plan_price=100000,
            plan_name="بسته ویژه",
            account_name="acc1"
        )
        self.assertFalse(comm_fail["success"])
        self.assertEqual(comm_fail["reason"], "parent_quota_not_met")

        # ۲. حال سهمیه را غیرفعال یا صفر می‌کنیم (پیش‌فرض)
        self.test_db.update_reseller_affiliate_settings(
            enabled=True,
            default_percent=15.0,
            calc_base="selling_price",
            terms="شرایط همکاری",
            anti_fraud_enabled=True,
            min_monthly_sales=0,
            min_monthly_turnover=0
        )

        # پورسانت باید با موفقیت ۱۵٪ از ۱۰۰,۰۰۰ = ۱۵,۰۰۰ تومان پرداخت شود
        comm_ok = self.test_db.process_sub_reseller_affiliate_commission(
            sub_reseller_id=sub_id,
            plan_price=100000,
            plan_name="بسته ویژه",
            account_name="acc2"
        )
        self.assertTrue(comm_ok["success"])
        self.assertEqual(comm_ok["commission_amount"], 15000)

        # موجودی نماینده بالادست باید ۱۵,۰۰۰ تومان افزایش یافته باشد
        parent_after = self.test_db.get_reseller(parent_id)
        self.assertEqual(parent_after["balance"], 15000)


if __name__ == "__main__":
    unittest.main()
