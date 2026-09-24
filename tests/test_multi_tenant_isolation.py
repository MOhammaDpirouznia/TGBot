#!/usr/bin/env python3
"""
Unit tests for multi-tenant isolation
"""
import unittest
import os
import tempfile
import sqlite3

from database import Database, get_now_iso


class TestMultiTenantIsolation(unittest.TestCase):
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

        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO resellers (id, username, password_hash, name, balance, status)
            VALUES (1, 'reseller_one', 'hash1', 'نماینده یک', 500000, 'active')
        """)
        cursor.execute("""
            INSERT INTO resellers (id, username, password_hash, name, balance, status)
            VALUES (2, 'reseller_two', 'hash2', 'نماینده دو', 500000, 'active')
        """)
        conn.commit()
        conn.close()

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

    def test_wallet_balance_and_deposit_deduct_isolation(self):
        """تست تفکیک کامل موجودی کیف پول و واریز/برداشت بین مدیریت و نمایندگان"""
        tg_id = 77889900
        self.db.save_user(telegram_id=tg_id, username="tenant_user")

        # ۱. واریز به کیف پول مدیریت (reseller_id=0)
        res_admin = self.db.add_wallet_balance(tg_id, 100000, description="شارژ کیف پول اصلی مدیریت", reseller_id=0)
        self.assertTrue(res_admin.get("success"))

        # ۲. واریز به کیف پول نماینده ۱ (reseller_id=1)
        res_r1 = self.db.add_wallet_balance(tg_id, 50000, description="شارژ کیف پول نماینده ۱", reseller_id=1)
        self.assertTrue(res_r1.get("success"))

        # ۳. واریز به کیف پول نماینده ۲ (reseller_id=2)
        res_r2 = self.db.add_wallet_balance(tg_id, 20000, description="شارژ کیف پول نماینده ۲", reseller_id=2)
        self.assertTrue(res_r2.get("success"))

        # بررسی موجودی‌ها
        bal_admin = self.db.get_user_wallet_balance(tg_id, reseller_id=0)
        bal_r1 = self.db.get_user_wallet_balance(tg_id, reseller_id=1)
        bal_r2 = self.db.get_user_wallet_balance(tg_id, reseller_id=2)

        self.assertEqual(bal_admin, 100000, "موجودی مدیریت باید ۱۰۰,۰۰۰ باشد")
        self.assertEqual(bal_r1, 50000, "موجودی نماینده ۱ باید ۵۰,۰۰۰ باشد")
        self.assertEqual(bal_r2, 20000, "موجودی نماینده ۲ باید ۲۰,۰۰۰ باشد")

        # ۴. کسر از کیف پول نماینده ۱
        deduct_res = self.db.deduct_wallet_balance(tg_id, 15000, description="خرید از نماینده ۱", reseller_id=1)
        self.assertTrue(deduct_res.get("success"))

        # اطمینان از عدم تغییر کیف پول مدیریت و نماینده ۲
        self.assertEqual(self.db.get_user_wallet_balance(tg_id, reseller_id=1), 35000)
        self.assertEqual(self.db.get_user_wallet_balance(tg_id, reseller_id=0), 100000)
        self.assertEqual(self.db.get_user_wallet_balance(tg_id, reseller_id=2), 20000)

        # ۵. بررسی تفکیک در get_wallet_transactions
        wtx_admin = self.db.get_wallet_transactions(tg_id, reseller_id=0)
        wtx_r1 = self.db.get_wallet_transactions(tg_id, reseller_id=1)
        wtx_r2 = self.db.get_wallet_transactions(tg_id, reseller_id=2)

        self.assertEqual(len(wtx_admin), 1)
        self.assertEqual(wtx_admin[0]["amount"], 100000)

        self.assertEqual(len(wtx_r1), 2)  # واریز ۵۰۰۰۰ و کسر ۱۵۰۰۰
        self.assertEqual(len(wtx_r2), 1)  # واریز ۲۰۰۰۰

    def test_transaction_history_isolation(self):
        """تست تفکیک کامل تاریخچه تراکنش‌های پرداختی میان مدیریت و هر نماینده"""
        tg_id = 77889901
        self.db.save_user(telegram_id=tg_id, username="tx_user")

        # ثبت تراکنش مدیریت (reseller_id=None / 0)
        self.db.save_transaction(
            order_id="ORD-ADMIN-01",
            user_id=tg_id,
            username="tx_user",
            plan_name="پلن مدیریت",
            amount=100000,
            gateway="card",
            tracking_code="TRK-ADM-01",
            reseller_id=None
        )

        # ثبت تراکنش نماینده ۱ (reseller_id=1)
        self.db.save_transaction(
            order_id="ORD-R1-01",
            user_id=tg_id,
            username="tx_user",
            plan_name="پلن نماینده ۱",
            amount=50000,
            gateway="card",
            tracking_code="TRK-R1-01",
            reseller_id=1
        )

        txs_admin = self.db.get_user_transactions(tg_id, reseller_id=0)
        txs_r1 = self.db.get_user_transactions(tg_id, reseller_id=1)
        txs_r2 = self.db.get_user_transactions(tg_id, reseller_id=2)

        self.assertEqual(len(txs_admin), 1)
        self.assertEqual(txs_admin[0]["order_id"], "ORD-ADMIN-01")

        self.assertEqual(len(txs_r1), 1)
        self.assertEqual(txs_r1[0]["order_id"], "ORD-R1-01")

        self.assertEqual(len(txs_r2), 0)

    def test_subscription_retrieval_and_ownership_isolation(self):
        """تست عدم دسترسی متقابل به اشتراک‌ها میان مدیریت و نمایندگان"""
        tg_id = 77889902
        self.db.save_user(telegram_id=tg_id, username="sub_user")

        sub_admin_res = self.db.save_subscription(
            telegram_id=tg_id,
            hidify_uuid="uuid-admin-tenant",
            plan_id="p_admin",
            plan_name="پلن مدیریت",
            account_name="acc_admin",
            data_limit=50.0,
            duration=30,
            cost_paid=100000,
            reseller_id=None,
            status="active"
        )
        self.assertTrue(sub_admin_res.get("success"))
        sub_admin_id = sub_admin_res["subscription_id"]

        sub_r1_res = self.db.save_subscription(
            telegram_id=tg_id,
            hidify_uuid="uuid-r1-tenant",
            plan_id="p_r1",
            plan_name="پلن نماینده یک",
            account_name="acc_r1",
            data_limit=30.0,
            duration=30,
            cost_paid=60000,
            reseller_id=1,
            status="active"
        )
        self.assertTrue(sub_r1_res.get("success"))
        sub_r1_id = sub_r1_res["subscription_id"]

        # کوئری مدیریت فقط اشتراک مدیریت را برمی‌گرداند
        admin_subs = self.db.get_user_subscriptions(tg_id, is_admin_bot=True)
        self.assertEqual(len(admin_subs), 1)
        self.assertEqual(admin_subs[0]["id"], sub_admin_id)

        # کوئری نماینده ۱ فقط اشتراک نماینده ۱ را برمی‌گرداند
        r1_subs = self.db.get_user_subscriptions(tg_id, reseller_id=1)
        self.assertEqual(len(r1_subs), 1)
        self.assertEqual(r1_subs[0]["id"], sub_r1_id)

        # کوئری نماینده ۲ هیچ اشتراکی برنمی‌گرداند
        r2_subs = self.db.get_user_subscriptions(tg_id, reseller_id=2)
        self.assertEqual(len(r2_subs), 0)

        # مالکیت اشتراک
        self.assertIsNone(self.db.get_reseller_subscription(1, sub_admin_id))
        self.assertIsNone(self.db.get_reseller_subscription(2, sub_r1_id))
        self.assertIsNotNone(self.db.get_reseller_subscription(1, sub_r1_id))

    def test_referral_reward_tenant_isolation(self):
        """تست اعتبار پاداش زیرمجموعه‌گیری به کیف پول همان نماینده نه مدیریت"""
        inviter_tg = 77889903
        referred_tg = 77889904

        self.db.save_user(telegram_id=inviter_tg, username="inviter_usr")
        self.db.save_user(telegram_id=referred_tg, username="referred_usr")

        # فعال‌سازی تنظیمات رفرال برای نماینده ۱
        self.db.save_customer_referral_config(1, {
            "is_enabled": True,
            "reward_type": "fixed",
            "reward_amount": 10000,
            "min_purchase_amount": 50000,
            "max_daily_rewards": 5,
            "reward_condition": "first_purchase"
        })

        add_res = self.db.add_customer_referral(referrer_id=inviter_tg, referred_id=referred_tg, reseller_id=1)
        self.assertTrue(add_res.get("success"))

        res = self.db.complete_customer_referral(referred_id=referred_tg, order_amount=100000, reseller_id=1)
        self.assertTrue(res.get("success"))

        r1_bal = self.db.get_user_wallet_balance(inviter_tg, reseller_id=1)
        self.assertEqual(r1_bal, 10000, "پاداش باید دقیقاً ۱۰,۰۰۰ تومان در کیف پول نماینده ۱ واریز شده باشد")

        admin_bal = self.db.get_user_wallet_balance(inviter_tg, reseller_id=0)
        self.assertEqual(admin_bal, 0, "کیف پول مدیریت نباید دستخوش پاداش نماینده شود")

    def test_customer_refund_tenant_isolation(self):
        """تست برگشت وجه حذف اشتراک نماینده به کیف پول همان نماینده"""
        tg_id = 77889905
        self.db.save_user(telegram_id=tg_id, username="refund_user")

        sub_res = self.db.save_subscription(
            telegram_id=tg_id,
            hidify_uuid="uuid-refund-test",
            plan_id="p_test",
            plan_name="پلن آزمایشی",
            account_name="acc_refund",
            data_limit=20.0,
            duration=30,
            cost_paid=80000,
            reseller_id=1,
            status="active"
        )
        sub_id = sub_res["subscription_id"]

        del_res = self.db.delete_customer_subscription(sub_id, refund_to_customer=True)
        self.assertTrue(del_res.get("success"))

        r1_bal = self.db.get_user_wallet_balance(tg_id, reseller_id=1)
        self.assertGreater(r1_bal, 0, "مبلغ استرداد باید به کیف پول نماینده ۱ واریز شود")

        admin_bal = self.db.get_user_wallet_balance(tg_id, reseller_id=0)
        self.assertEqual(admin_bal, 0, "کیف پول مدیریت نباید برای حذف اشتراک نماینده شارژ شود")


if __name__ == "__main__":
    unittest.main()
