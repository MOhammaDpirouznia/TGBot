#!/usr/bin/env python3
import unittest
import tempfile
import os
from datetime import datetime, timedelta
from database import Database
from utils import get_now_iso, get_now_naive

class TestResellerRefundOrigins(unittest.TestCase):
    def setUp(self):
        self.temp_db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self.temp_db.close()
        self.db = Database(db_path=self.temp_db.name)

        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO resellers (username, password_hash, name, balance, credit_enabled, credit_limit, credit_debt, discount_percent, status)
            VALUES ('test_reseller', 'hash', 'Test Reseller', 100000, 1, 500000, 0, 20, 'active')
        """)
        self.reseller_id = cursor.lastrowid
        conn.commit()
        conn.close()

    def tearDown(self):
        try:
            os.remove(self.temp_db.name)
        except Exception:
            pass

    def test_wallet_only_refund(self):
        """خرید از کیف پول: استرداد باید ۱۰۰٪ به کیف پول برگردد و بدهی اعتبار تغییر نکند"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO subscriptions (account_name, reseller_id, telegram_id, cost_paid, payment_source, status, created_at, updated_at)
            VALUES ('sub_wallet_only', ?, 123456, 50000, 'wallet', 'active', ?, ?)
        """, (self.reseller_id, get_now_iso(), get_now_iso()))
        sub_id = cursor.lastrowid
        cursor.execute("UPDATE resellers SET balance = balance - 50000 WHERE id = ?", (self.reseller_id,))
        cursor.execute("""
            INSERT INTO reseller_transactions (reseller_id, type, amount, balance_after, plan_name, account_name, description, payment_source, subscription_id, created_at)
            VALUES (?, 'purchase', 50000, 50000, 'پلن تست', 'sub_wallet_only', 'خرید پلن از کیف پول', 'wallet', ?, ?)
        """, (self.reseller_id, sub_id, get_now_iso()))
        conn.commit()
        conn.close()

        refund_info = self.db.calculate_reseller_refund(self.reseller_id, sub_id)
        self.assertIsNotNone(refund_info)
        self.assertEqual(refund_info["refund_amount"], 50000)
        self.assertEqual(refund_info["wallet_refund"], 50000)
        self.assertEqual(refund_info["credit_refund"], 0)
        self.assertEqual(refund_info["payment_source"], "wallet")

        del_res = self.db.delete_reseller_subscription(self.reseller_id, sub_id, reason="انصراف کاربر")
        self.assertTrue(del_res["success"])
        self.assertEqual(del_res["wallet_refund"], 50000)
        self.assertEqual(del_res["credit_refund"], 0)

        reseller = self.db.get_reseller(self.reseller_id)
        self.assertEqual(reseller["balance"], 100000)
        self.assertEqual(reseller["credit_debt"], 0)

    def test_credit_only_refund(self):
        """خرید از اعتبار: استرداد باید ۱۰۰٪ از بدهی اعتباری کسر شود و کیف پول زیاد نشود"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO subscriptions (account_name, reseller_id, telegram_id, cost_paid, payment_source, is_credit, status, created_at, updated_at)
            VALUES ('sub_credit_only', ?, 123456, 60000, 'credit', 1, 'active', ?, ?)
        """, (self.reseller_id, get_now_iso(), get_now_iso()))
        sub_id = cursor.lastrowid
        cursor.execute("UPDATE resellers SET credit_debt = credit_debt + 60000 WHERE id = ?", (self.reseller_id,))
        cursor.execute("""
            INSERT INTO reseller_transactions (reseller_id, type, amount, balance_after, plan_name, account_name, description, payment_source, subscription_id, created_at)
            VALUES (?, 'purchase_credit', 60000, 100000, 'پلن اعتباری', 'sub_credit_only', 'خرید پلن از اعتبار', 'credit', ?, ?)
        """, (self.reseller_id, sub_id, get_now_iso()))
        conn.commit()
        conn.close()

        refund_info = self.db.calculate_reseller_refund(self.reseller_id, sub_id)
        self.assertIsNotNone(refund_info)
        self.assertEqual(refund_info["refund_amount"], 60000)
        self.assertEqual(refund_info["wallet_refund"], 0)
        self.assertEqual(refund_info["credit_refund"], 60000)
        self.assertEqual(refund_info["payment_source"], "credit")

        del_res = self.db.delete_reseller_subscription(self.reseller_id, sub_id, reason="عدم نیاز")
        self.assertTrue(del_res["success"])
        self.assertEqual(del_res["wallet_refund"], 0)
        self.assertEqual(del_res["credit_refund"], 60000)

        reseller = self.db.get_reseller(self.reseller_id)
        self.assertEqual(reseller["balance"], 100000)
        self.assertEqual(reseller["credit_debt"], 0)

    def test_wallet_creation_plus_credit_queued_renewal(self):
        """
        ساخت از کیف پول (۵۰,۰۰۰ ت) + رزرو تمدید در صف از اعتبار (۶۰,۰۰۰ ت)
        هنگام حذف باید ۵۰,۰۰۰ ت به کیف پول و ۶۰,۰۰۰ ت به اعتبار برگردد و صف تمدید لغو شود.
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO subscriptions (account_name, reseller_id, telegram_id, cost_paid, payment_source, status, created_at, updated_at)
            VALUES ('sub_mixed_1', ?, 123456, 50000, 'wallet', 'active', ?, ?)
        """, (self.reseller_id, get_now_iso(), get_now_iso()))
        sub_id = cursor.lastrowid
        cursor.execute("UPDATE resellers SET balance = balance - 50000 WHERE id = ?", (self.reseller_id,))
        cursor.execute("""
            INSERT INTO reseller_transactions (reseller_id, type, amount, balance_after, plan_name, account_name, description, payment_source, subscription_id, created_at)
            VALUES (?, 'purchase', 50000, 50000, 'پلن پایه', 'sub_mixed_1', 'خرید اولیه از کیف پول', 'wallet', ?, ?)
        """, (self.reseller_id, sub_id, get_now_iso()))

        cursor.execute("UPDATE resellers SET credit_debt = credit_debt + 60000 WHERE id = ?", (self.reseller_id,))
        cursor.execute("""
            INSERT INTO reseller_transactions (reseller_id, type, amount, balance_after, plan_name, account_name, description, payment_source, subscription_id, created_at)
            VALUES (?, 'renewal', 60000, 50000, 'پلن تمدیدی', 'sub_mixed_1', 'تمدید اشتراک «sub_mixed_1» با پلن تمدیدی (رزرو در صف تمدید - کسر از اعتبار)', 'credit', ?, ?)
        """, (self.reseller_id, sub_id, get_now_iso()))
        cursor.execute("""
            INSERT INTO subscription_queue (subscription_id, reseller_id, plan_id, plan_name, data_limit, duration, cost, status, created_at, queue_order, payment_source)
            VALUES (?, ?, 'plan_renew', 'پلن تمدیدی', 30.0, 30, 60000, 'pending', ?, 1, 'credit')
        """, (sub_id, self.reseller_id, get_now_iso()))
        conn.commit()
        conn.close()

        r_before = self.db.get_reseller(self.reseller_id)
        self.assertEqual(r_before["balance"], 50000)
        self.assertEqual(r_before["credit_debt"], 60000)

        refund_info = self.db.calculate_reseller_refund(self.reseller_id, sub_id)
        self.assertIsNotNone(refund_info)
        self.assertEqual(refund_info["cost_paid"], 110000)
        self.assertEqual(refund_info["refund_amount"], 110000)
        self.assertEqual(refund_info["wallet_refund"], 50000)
        self.assertEqual(refund_info["credit_refund"], 60000)
        self.assertEqual(refund_info["payment_source"], "mixed")

        del_res = self.db.delete_reseller_subscription(self.reseller_id, sub_id, reason="تست ترکیبی")
        self.assertTrue(del_res["success"])
        self.assertEqual(del_res["wallet_refund"], 50000)
        self.assertEqual(del_res["credit_refund"], 60000)

        r_after = self.db.get_reseller(self.reseller_id)
        self.assertEqual(r_after["balance"], 100000)
        self.assertEqual(r_after["credit_debt"], 0)

        conn = self.db.get_connection()
        q_row = conn.execute("SELECT status FROM subscription_queue WHERE subscription_id = ?", (sub_id,)).fetchone()
        conn.close()
        self.assertEqual(q_row[0], "cancelled")

    def test_credit_creation_plus_wallet_queued_renewal(self):
        """
        ساخت از اعتبار (۷۰,۰۰۰ ت) + رزرو تمدید در صف از کیف پول (۴۰,۰۰۰ ت)
        هنگام حذف باید ۷۰,۰۰۰ ت به اعتبار (کاهش بدهی) و ۴۰,۰۰۰ ت به کیف پول واریز شود.
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO subscriptions (account_name, reseller_id, telegram_id, cost_paid, payment_source, is_credit, status, created_at, updated_at)
            VALUES ('sub_mixed_2', ?, 123456, 70000, 'credit', 1, 'active', ?, ?)
        """, (self.reseller_id, get_now_iso(), get_now_iso()))
        sub_id = cursor.lastrowid
        cursor.execute("UPDATE resellers SET credit_debt = credit_debt + 70000 WHERE id = ?", (self.reseller_id,))
        cursor.execute("""
            INSERT INTO reseller_transactions (reseller_id, type, amount, balance_after, plan_name, account_name, description, payment_source, subscription_id, created_at)
            VALUES (?, 'purchase_credit', 70000, 100000, 'پلن اعتباری', 'sub_mixed_2', 'خرید اولیه از اعتبار', 'credit', ?, ?)
        """, (self.reseller_id, sub_id, get_now_iso()))

        cursor.execute("UPDATE resellers SET balance = balance - 40000 WHERE id = ?", (self.reseller_id,))
        cursor.execute("""
            INSERT INTO reseller_transactions (reseller_id, type, amount, balance_after, plan_name, account_name, description, payment_source, subscription_id, created_at)
            VALUES (?, 'renewal', 40000, 60000, 'پلن تمدیدی', 'sub_mixed_2', 'تمدید اشتراک «sub_mixed_2» با پلن تمدیدی (رزرو در صف تمدید - کسر از کیف پول)', 'wallet', ?, ?)
        """, (self.reseller_id, sub_id, get_now_iso()))
        cursor.execute("""
            INSERT INTO subscription_queue (subscription_id, reseller_id, plan_id, plan_name, data_limit, duration, cost, status, created_at, queue_order, payment_source)
            VALUES (?, ?, 'plan_renew', 'پلن تمدیدی', 20.0, 30, 40000, 'pending', ?, 1, 'wallet')
        """, (sub_id, self.reseller_id, get_now_iso()))
        conn.commit()
        conn.close()

        refund_info = self.db.calculate_reseller_refund(self.reseller_id, sub_id)
        self.assertEqual(refund_info["wallet_refund"], 40000)
        self.assertEqual(refund_info["credit_refund"], 70000)

        del_res = self.db.delete_reseller_subscription(self.reseller_id, sub_id)
        self.assertTrue(del_res["success"])

        r_after = self.db.get_reseller(self.reseller_id)
        self.assertEqual(r_after["balance"], 100000)
        self.assertEqual(r_after["credit_debt"], 0)

    def test_expired_creation_with_fresh_queued_renewal(self):
        """
        اشتراک منقضی‌شده (> 24 ساعت) با یک بسته تازه در صف تمدید:
        خرید اولیه ۳ روز پیش بوده (استرداد ۰٪)، اما بسته در صف رزرو دست‌نخورده است (استرداد ۱۰۰٪ به اعتبار)
        """
        old_time = (datetime.now() - timedelta(days=3)).isoformat()
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO subscriptions (account_name, reseller_id, telegram_id, cost_paid, payment_source, status, created_at, updated_at)
            VALUES ('sub_old', ?, 123456, 50000, 'wallet', 'active', ?, ?)
        """, (self.reseller_id, old_time, old_time))
        sub_id = cursor.lastrowid
        cursor.execute("UPDATE resellers SET balance = balance - 50000 WHERE id = ?", (self.reseller_id,))
        cursor.execute("""
            INSERT INTO reseller_transactions (reseller_id, type, amount, balance_after, plan_name, account_name, description, payment_source, subscription_id, created_at)
            VALUES (?, 'purchase', 50000, 50000, 'پلن قدیمی', 'sub_old', 'خرید اولیه ۳ روز پیش', 'wallet', ?, ?)
        """, (self.reseller_id, sub_id, old_time))

        cursor.execute("UPDATE resellers SET credit_debt = credit_debt + 60000 WHERE id = ?", (self.reseller_id,))
        cursor.execute("""
            INSERT INTO reseller_transactions (reseller_id, type, amount, balance_after, plan_name, account_name, description, payment_source, subscription_id, created_at)
            VALUES (?, 'renewal', 60000, 50000, 'پلن صف', 'sub_old', 'رزرو در صف تمدید - کسر از اعتبار', 'credit', ?, ?)
        """, (self.reseller_id, sub_id, get_now_iso()))
        cursor.execute("""
            INSERT INTO subscription_queue (subscription_id, reseller_id, plan_id, plan_name, data_limit, duration, cost, status, created_at, queue_order, payment_source)
            VALUES (?, ?, 'plan_q', 'پلن صف', 50.0, 30, 60000, 'pending', ?, 1, 'credit')
        """, (sub_id, self.reseller_id, get_now_iso()))
        conn.commit()
        conn.close()

        refund_info = self.db.calculate_reseller_refund(self.reseller_id, sub_id)
        self.assertEqual(refund_info["wallet_paid"], 50000)
        self.assertEqual(refund_info["wallet_refund"], 0) # گذشته از ۲۴ ساعت
        self.assertEqual(refund_info["credit_paid"], 60000)
        self.assertEqual(refund_info["credit_refund"], 60000) # ۱۰۰٪ بسته صف
        self.assertEqual(refund_info["refund_amount"], 60000)

        del_res = self.db.delete_reseller_subscription(self.reseller_id, sub_id)
        self.assertTrue(del_res["success"])

        r_after = self.db.get_reseller(self.reseller_id)
        self.assertEqual(r_after["balance"], 50000)
        self.assertEqual(r_after["credit_debt"], 0)

    def test_multiple_queued_renewals_mixed(self):
        """
        تست چندین بسته در صف تمدید با منابع مختلف (کیف پول و اعتبار)
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO subscriptions (account_name, reseller_id, telegram_id, cost_paid, payment_source, status, created_at, updated_at)
            VALUES ('sub_multi', ?, 123456, 30000, 'wallet', 'active', ?, ?)
        """, (self.reseller_id, get_now_iso(), get_now_iso()))
        sub_id = cursor.lastrowid
        cursor.execute("UPDATE resellers SET balance = balance - 30000 WHERE id = ?", (self.reseller_id,))
        cursor.execute("""
            INSERT INTO reseller_transactions (reseller_id, type, amount, balance_after, plan_name, account_name, description, payment_source, subscription_id, created_at)
            VALUES (?, 'purchase', 30000, 70000, 'پلن ۱', 'sub_multi', 'خرید اولیه', 'wallet', ?, ?)
        """, (self.reseller_id, sub_id, get_now_iso()))

        # صف ۱: اعتبار (۴۰,۰۰۰ ت)
        cursor.execute("UPDATE resellers SET credit_debt = credit_debt + 40000 WHERE id = ?", (self.reseller_id,))
        cursor.execute("""
            INSERT INTO reseller_transactions (reseller_id, type, amount, balance_after, plan_name, account_name, description, payment_source, subscription_id, created_at)
            VALUES (?, 'renewal', 40000, 70000, 'صف ۱', 'sub_multi', 'رزرو در صف تمدید - اعتبار', 'credit', ?, ?)
        """, (self.reseller_id, sub_id, get_now_iso()))
        cursor.execute("""
            INSERT INTO subscription_queue (subscription_id, reseller_id, plan_id, plan_name, data_limit, duration, cost, status, created_at, queue_order, payment_source)
            VALUES (?, ?, 'p1', 'صف ۱', 10.0, 30, 40000, 'pending', ?, 1, 'credit')
        """, (sub_id, self.reseller_id, get_now_iso()))

        # صف ۲: کیف پول (۵۰,۰۰۰ ت)
        cursor.execute("UPDATE resellers SET balance = balance - 50000 WHERE id = ?", (self.reseller_id,))
        cursor.execute("""
            INSERT INTO reseller_transactions (reseller_id, type, amount, balance_after, plan_name, account_name, description, payment_source, subscription_id, created_at)
            VALUES (?, 'renewal', 50000, 20000, 'صف ۲', 'sub_multi', 'رزرو در صف تمدید - کیف پول', 'wallet', ?, ?)
        """, (self.reseller_id, sub_id, get_now_iso()))
        cursor.execute("""
            INSERT INTO subscription_queue (subscription_id, reseller_id, plan_id, plan_name, data_limit, duration, cost, status, created_at, queue_order, payment_source)
            VALUES (?, ?, 'p2', 'صف ۲', 20.0, 30, 50000, 'pending', ?, 2, 'wallet')
        """, (sub_id, self.reseller_id, get_now_iso()))

        # صف ۳: اعتبار (۳۵,۰۰۰ ت)
        cursor.execute("UPDATE resellers SET credit_debt = credit_debt + 35000 WHERE id = ?", (self.reseller_id,))
        cursor.execute("""
            INSERT INTO reseller_transactions (reseller_id, type, amount, balance_after, plan_name, account_name, description, payment_source, subscription_id, created_at)
            VALUES (?, 'renewal', 35000, 20000, 'صف ۳', 'sub_multi', 'رزرو در صف تمدید - اعتبار', 'credit', ?, ?)
        """, (self.reseller_id, sub_id, get_now_iso()))
        cursor.execute("""
            INSERT INTO subscription_queue (subscription_id, reseller_id, plan_id, plan_name, data_limit, duration, cost, status, created_at, queue_order, payment_source)
            VALUES (?, ?, 'p3', 'صف ۳', 30.0, 30, 35000, 'pending', ?, 3, 'credit')
        """, (sub_id, self.reseller_id, get_now_iso()))
        conn.commit()
        conn.close()

        refund_info = self.db.calculate_reseller_refund(self.reseller_id, sub_id)
        self.assertEqual(refund_info["wallet_refund"], 80000)
        self.assertEqual(refund_info["credit_refund"], 75000)
        self.assertEqual(refund_info["refund_amount"], 155000)

        del_res = self.db.delete_reseller_subscription(self.reseller_id, sub_id)
        self.assertTrue(del_res["success"])

        r_after = self.db.get_reseller(self.reseller_id)
        self.assertEqual(r_after["balance"], 100000)
        self.assertEqual(r_after["credit_debt"], 0)

        conn = self.db.get_connection()
        cancelled_count = conn.execute("SELECT COUNT(*) FROM subscription_queue WHERE subscription_id = ? AND status = 'cancelled'", (sub_id,)).fetchone()[0]
        conn.close()
        self.assertEqual(cancelled_count, 3)

    def test_calculate_refund_includes_customer_receipt_details(self):
        """بررسی استخراج اطلاعات فیش مشتری و پیشنهاد هوشمند تیک در calculate_reseller_refund"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO subscriptions (account_name, reseller_id, telegram_id, cost_paid, payment_source, data_used, data_limit, status, created_at, updated_at)
            VALUES ('sub_test_cr', ?, 123456, 50000, 'wallet', 0.2, 30.0, 'active', ?, ?)
        """, (self.reseller_id, get_now_iso(), get_now_iso()))
        sub_id = cursor.lastrowid

        cursor.execute("""
            INSERT INTO transactions (order_id, user_id, amount, status, reseller_id, subscription_id, account_name, created_at, updated_at)
            VALUES ('ORD_TEST_101', 123456, 120000, 'approved', ?, ?, 'sub_test_cr', ?, ?)
        """, (self.reseller_id, sub_id, get_now_iso(), get_now_iso()))
        tx_id = cursor.lastrowid
        conn.commit()
        conn.close()

        ref = self.db.calculate_reseller_refund(self.reseller_id, sub_id)
        self.assertIsNotNone(ref)
        cr = ref.get("customer_receipt")
        self.assertIsNotNone(cr)
        self.assertTrue(cr["has_receipt"])
        self.assertEqual(cr["tx_id"], tx_id)
        self.assertEqual(cr["amount"], 120000)
        self.assertEqual(cr["order_id"], "ORD_TEST_101")
        self.assertTrue(cr["is_within_24h"])
        self.assertTrue(cr["auto_check_recommended"])

    def test_delete_reseller_subscription_voids_customer_receipt_and_card_balance(self):
        """حذف با تیک ابطال فیش: فیش باطل شده، از کارت بانکی کسر می‌شود اما اعتبار عمده دوبل پس داده نمی‌شود"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO reseller_cards (reseller_id, bank_name, card_number, card_holder, balance, is_active, created_at)
            VALUES (?, 'بلوبانک', '6219861011112222', 'تست', 500000, 1, ?)
        """, (self.reseller_id, get_now_iso()))
        card_id = cursor.lastrowid

        cursor.execute("""
            INSERT INTO subscriptions (account_name, reseller_id, telegram_id, cost_paid, payment_source, status, created_at, updated_at)
            VALUES ('sub_void_receipt', ?, 123456, 50000, 'wallet', 'active', ?, ?)
        """, (self.reseller_id, get_now_iso(), get_now_iso()))
        sub_id = cursor.lastrowid
        cursor.execute("UPDATE resellers SET balance = balance - 50000 WHERE id = ?", (self.reseller_id,))
        cursor.execute("""
            INSERT INTO reseller_transactions (reseller_id, type, amount, balance_after, plan_name, account_name, description, payment_source, subscription_id, created_at)
            VALUES (?, 'purchase', 50000, 50000, 'پلن تست', 'sub_void_receipt', 'خرید پلن', 'wallet', ?, ?)
        """, (self.reseller_id, sub_id, get_now_iso()))

        cursor.execute("""
            INSERT INTO transactions (order_id, user_id, amount, status, reseller_id, subscription_id, account_name, created_at, updated_at)
            VALUES ('ORD_CUST_999', 123456, 120000, 'approved', ?, ?, 'sub_void_receipt', ?, ?)
        """, (self.reseller_id, sub_id, get_now_iso(), get_now_iso()))
        tx_id = cursor.lastrowid

        cursor.execute("""
            INSERT INTO card_transactions (card_id, owner_type, reseller_id, type, amount, category, title, ref_type, ref_id, is_revoked, created_at)
            VALUES (?, 'reseller', ?, 'deposit', 120000, 'فروش اشتراک', 'فروش sub_void_receipt', 'transaction', ?, 0, ?)
        """, (card_id, self.reseller_id, str(tx_id), get_now_iso()))
        cursor.execute("UPDATE reseller_cards SET balance = balance + 120000 WHERE id = ?", (card_id,))
        conn.commit()
        conn.close()

        conn = self.db.get_connection()
        card_before = conn.execute("SELECT balance FROM reseller_cards WHERE id = ?", (card_id,)).fetchone()[0]
        self.assertEqual(card_before, 620000)
        conn.close()

        del_res = self.db.delete_reseller_subscription(self.reseller_id, sub_id, reason="کنسلی توسط مشتری", void_customer_receipt=True)
        self.assertTrue(del_res["success"])
        self.assertEqual(del_res["wallet_refund"], 50000)
        vr = del_res.get("voided_receipt")
        self.assertIsNotNone(vr)
        self.assertEqual(vr["tx_id"], tx_id)
        self.assertEqual(vr["amount"], 120000)
        self.assertTrue(vr["card_deducted"])

        conn = self.db.get_connection()
        card_after = conn.execute("SELECT balance FROM reseller_cards WHERE id = ?", (card_id,)).fetchone()[0]
        self.assertEqual(card_after, 500000)

        c_tx = conn.execute("SELECT is_revoked, revoke_reason FROM card_transactions WHERE ref_id = ?", (str(tx_id),)).fetchone()
        self.assertEqual(c_tx[0], 1)

        tx_row = conn.execute("SELECT status, revoke_reason FROM transactions WHERE id = ?", (tx_id,)).fetchone()
        self.assertEqual(tx_row[0], "revoked")

        r_after = self.db.get_reseller(self.reseller_id)
        self.assertEqual(r_after["balance"], 100000)
        conn.close()

    def test_delete_reseller_subscription_keeps_customer_receipt_when_unchecked(self):
        """حذف بدون تیک ابطال فیش: فیش مشتری تایید شده می‌ماند و کارت بانکی دست نمی‌خورد"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO reseller_cards (reseller_id, bank_name, card_number, card_holder, balance, is_active, created_at)
            VALUES (?, 'بلوبانک', '6219861011112222', 'تست', 500000, 1, ?)
        """, (self.reseller_id, get_now_iso()))
        card_id = cursor.lastrowid

        cursor.execute("""
            INSERT INTO subscriptions (account_name, reseller_id, telegram_id, cost_paid, payment_source, status, created_at, updated_at)
            VALUES ('sub_keep_receipt', ?, 123456, 50000, 'wallet', 'active', ?, ?)
        """, (self.reseller_id, get_now_iso(), get_now_iso()))
        sub_id = cursor.lastrowid
        cursor.execute("""
            INSERT INTO transactions (order_id, user_id, amount, status, reseller_id, subscription_id, account_name, created_at, updated_at)
            VALUES ('ORD_CUST_KEEP', 123456, 120000, 'approved', ?, ?, 'sub_keep_receipt', ?, ?)
        """, (self.reseller_id, sub_id, get_now_iso(), get_now_iso()))
        tx_id = cursor.lastrowid
        cursor.execute("""
            INSERT INTO card_transactions (card_id, owner_type, reseller_id, type, amount, category, title, ref_type, ref_id, is_revoked, created_at)
            VALUES (?, 'reseller', ?, 'deposit', 120000, 'فروش اشتراک', 'فروش sub_keep_receipt', 'transaction', ?, 0, ?)
        """, (card_id, self.reseller_id, str(tx_id), get_now_iso()))
        cursor.execute("UPDATE reseller_cards SET balance = balance + 120000 WHERE id = ?", (card_id,))
        conn.commit()
        conn.close()

        del_res = self.db.delete_reseller_subscription(self.reseller_id, sub_id, reason="اتمام حجم", void_customer_receipt=False)
        self.assertTrue(del_res["success"])
        self.assertIsNone(del_res.get("voided_receipt"))

        conn = self.db.get_connection()
        card_after = conn.execute("SELECT balance FROM reseller_cards WHERE id = ?", (card_id,)).fetchone()[0]
        self.assertEqual(card_after, 620000)

        tx_row = conn.execute("SELECT status FROM transactions WHERE id = ?", (tx_id,)).fetchone()
        self.assertEqual(tx_row[0], "approved")
        conn.close()

    def test_calculate_refund_high_usage_warning(self):
        """اشتراک با مصرف بالا (مثلاً ۷۰٪): تیک خودکار نباید فعال باشد و هشدار مصرف نمایش یابد"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO subscriptions (account_name, reseller_id, telegram_id, cost_paid, payment_source, data_used, data_limit, status, created_at, updated_at)
            VALUES ('sub_high_usage', ?, 123456, 50000, 'wallet', 21.0, 30.0, 'active', ?, ?)
        """, (self.reseller_id, get_now_iso(), get_now_iso()))
        sub_id = cursor.lastrowid

        cursor.execute("""
            INSERT INTO transactions (order_id, user_id, amount, status, reseller_id, subscription_id, account_name, created_at, updated_at)
            VALUES ('ORD_HIGH_USAGE', 123456, 120000, 'approved', ?, ?, 'sub_high_usage', ?, ?)
        """, (self.reseller_id, sub_id, get_now_iso(), get_now_iso()))
        conn.commit()
        conn.close()

        ref = self.db.calculate_reseller_refund(self.reseller_id, sub_id)
        cr = ref.get("customer_receipt")
        self.assertIsNotNone(cr)
        self.assertEqual(cr["usage_percent"], 70.0)
        self.assertFalse(cr["auto_check_recommended"])
        self.assertIsNotNone(cr["usage_warning"])

if __name__ == '__main__':
    unittest.main()
