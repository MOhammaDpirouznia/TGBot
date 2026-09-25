import unittest
import os
import sys
import tempfile
import sqlite3
import subprocess
from datetime import datetime, timezone, timedelta
from jinja2 import Environment, FileSystemLoader
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from database import Database, get_now_iso, get_now_naive
import dashboard


class TestFullRoadmapVerification(unittest.TestCase):
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

    # ─── Task 3: Terminology & Modals ───
    def test_task3_terminology_cleanup(self):
        """Verify no user-facing Hiddify occurrences in updated templates"""
        templates_to_check = [
            'templates/subscriptions.html',
            'templates/reseller_customer_payments.html',
            'templates/setup_wizard.html'
        ]
        for tpl_path in templates_to_check:
            with open(tpl_path, 'r', encoding='utf-8') as f:
                content = f.read()
            self.assertNotIn('هیدیفای', content, f"Found 'هیدیفای' in {tpl_path}")
            self.assertNotIn('هيديفاي', content, f"Found Arabic 'هيديفاي' in {tpl_path}")

    def test_task3_modal_triggers(self):
        """Verify modal triggers and modal elements exist in subscriptions and reseller_users"""
        with open('templates/subscriptions.html', 'r', encoding='utf-8') as f:
            sub_content = f.read()
        self.assertIn('data-bs-target="#createCustomerModal"', sub_content)
        self.assertIn('id="createCustomerModal"', sub_content)
        self.assertIn("admin_create_customer", sub_content)

        with open('templates/reseller_users.html', 'r', encoding='utf-8') as f:
            res_content = f.read()
        self.assertIn('data-bs-target="#resellerCreateUserModal"', res_content)
        self.assertIn('id="resellerCreateUserModal"', res_content)

    # ─── Task 4: Financial Purge & Time-Based Refund & Two-Way Sync ───
    def test_task4_get_reseller_transactions_excludes_deleted(self):
        """Verify get_reseller_transactions excludes soft-deleted records"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO resellers (username, password_hash, name, balance, status)
            VALUES ('test_res_purge', 'pass', 'Reseller Purge', 100000, 'active')
        """)
        reseller_id = cursor.lastrowid

        now = get_now_iso()
        cursor.execute("""
            INSERT INTO reseller_transactions (reseller_id, type, amount, balance_after, description, is_deleted, created_at)
            VALUES (?, 'purchase', 50000, 50000, 'Active Tx', 0, ?)
        """, (reseller_id, now))
        tx1 = cursor.lastrowid

        cursor.execute("""
            INSERT INTO reseller_transactions (reseller_id, type, amount, balance_after, description, is_deleted, created_at)
            VALUES (?, 'purchase', 30000, 20000, 'Deleted Tx', 1, ?)
        """, (reseller_id, now))
        tx2 = cursor.lastrowid
        conn.commit()
        conn.close()

        txs = self.db.get_reseller_transactions(reseller_id)
        tx_ids = [t['id'] for t in txs]
        self.assertIn(tx1, tx_ids)
        self.assertNotIn(tx2, tx_ids, "Soft deleted transaction was not excluded!")

    def test_task4_time_based_refund_calculation(self):
        """Verify <=12h gives 100%, <=24h gives 50%, >24h gives 0% refund"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO resellers (username, password_hash, name, balance, discount_percent, status)
            VALUES ('test_res_refund', 'pass', 'Reseller Refund', 0, 20, 'active')
        """)
        reseller_id = cursor.lastrowid

        now_naive = get_now_naive()

        # 1. <= 12 hours ago (e.g. 2h ago) -> 100% refund
        created_2h = (now_naive - timedelta(hours=2)).isoformat()
        cursor.execute("""
            INSERT INTO transactions (order_id, user_id, username, plan_name, amount, status, reseller_id, created_at, updated_at)
            VALUES ('ORD100', 1, 'cust1', 'Plan 1', 100000, 'approved', ?, ?, ?)
        """, (reseller_id, created_2h, created_2h))
        tx_100 = cursor.lastrowid

        # 2. >12h and <= 24 hours ago (e.g. 18h ago) -> 50% refund
        created_18h = (now_naive - timedelta(hours=18)).isoformat()
        cursor.execute("""
            INSERT INTO transactions (order_id, user_id, username, plan_name, amount, status, reseller_id, created_at, updated_at)
            VALUES ('ORD50', 2, 'cust2', 'Plan 2', 80000, 'approved', ?, ?, ?)
        """, (reseller_id, created_18h, created_18h))
        tx_50 = cursor.lastrowid

        # 3. > 24 hours ago (e.g. 30h ago) -> 0% refund
        created_30h = (now_naive - timedelta(hours=30)).isoformat()
        cursor.execute("""
            INSERT INTO transactions (order_id, user_id, username, plan_name, amount, status, reseller_id, created_at, updated_at)
            VALUES ('ORD0', 3, 'cust3', 'Plan 3', 50000, 'approved', ?, ?, ?)
        """, (reseller_id, created_30h, created_30h))
        tx_0 = cursor.lastrowid

        conn.commit()
        conn.close()

        # Test 1: 2h ago -> 100%
        res1 = self.db.reseller_revoke_transaction(tx_100, reseller_id=reseller_id, reseller_name="Reseller")
        self.assertTrue(res1['success'])
        self.assertEqual(res1['refund_percent'], 100)
        self.assertGreater(res1['refund_amount'], 0)

        # Test 2: 18h ago -> 50%
        res2 = self.db.reseller_revoke_transaction(tx_50, reseller_id=reseller_id, reseller_name="Reseller")
        self.assertTrue(res2['success'])
        self.assertEqual(res2['refund_percent'], 50)
        self.assertGreater(res2['refund_amount'], 0)

        # Test 3: 30h ago -> 0%
        res3 = self.db.reseller_revoke_transaction(tx_0, reseller_id=reseller_id, reseller_name="Reseller")
        self.assertTrue(res3['success'])
        self.assertEqual(res3['refund_percent'], 0)
        self.assertEqual(res3['refund_amount'], 0)

    def test_task4_two_way_sync_delete_and_restore(self):
        """Verify soft-delete revokes payment and restore re-approves payment"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO resellers (username, password_hash, name, balance, discount_percent, status)
            VALUES ('test_sync', 'pass', 'Reseller Sync', 500000, 20, 'active')
        """)
        reseller_id = cursor.lastrowid
        now = get_now_iso()

        # Insert subscription
        cursor.execute("""
            INSERT INTO subscriptions (account_name, reseller_id, telegram_id, cost_paid, payment_source, status, created_at, updated_at)
            VALUES ('sync_cust_1', ?, 123456, 100000, 'wallet', 'active', ?, ?)
        """, (reseller_id, now, now))
        sub_id = cursor.lastrowid

        # Insert purchase transaction in reseller_transactions so refund calculation finds it
        cursor.execute("""
            INSERT INTO reseller_transactions (reseller_id, type, amount, balance_after, plan_name, account_name, description, payment_source, subscription_id, created_at)
            VALUES (?, 'purchase', 100000, 400000, 'پلن تست', 'sync_cust_1', 'خرید پلن', 'wallet', ?, ?)
        """, (reseller_id, sub_id, now))

        # Insert approved customer payment transaction in transactions table
        cursor.execute("""
            INSERT INTO transactions (order_id, user_id, username, plan_name, amount, status, reseller_id, subscription_id, account_name, created_at, updated_at)
            VALUES ('ORD_SYNC_1', 1, 'sync_cust_1', 'پلن تست', 100000, 'approved', ?, ?, 'sync_cust_1', ?, ?)
        """, (reseller_id, sub_id, now, now))
        tx_id = cursor.lastrowid
        conn.commit()
        conn.close()

        # 1. Soft-delete subscription
        del_res = self.db.delete_reseller_subscription(reseller_id, sub_id, reason="انصراف", void_customer_receipt=True)
        self.assertTrue(del_res["success"])

        # Verify transaction status in transactions was automatically revoked
        conn = self.db.get_connection()
        tx_row = conn.execute("SELECT status FROM transactions WHERE id=?", (tx_id,)).fetchone()
        conn.close()
        self.assertEqual(tx_row['status'], 'revoked')

        # 2. Restore subscription
        restore_res = self.db.restore_subscription(sub_id, is_reseller=True, reseller_id=reseller_id, cost=0)
        self.assertTrue(restore_res["success"])

        # Verify transaction status was automatically re-approved
        conn = self.db.get_connection()
        tx_row = conn.execute("SELECT status FROM transactions WHERE id=?", (tx_id,)).fetchone()
        conn.close()
        self.assertEqual(tx_row['status'], 'approved')

    # ─── Task 5: Avatar & Profile Fetch ───
    def test_task5_find_subscription_avatar_telegram_id(self):
        """Verify find_subscription_avatar matches by telegram_id"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO subscriptions (account_name, telegram_id, hidify_uuid, custom_avatar, status)
            VALUES ('avatar_sub_1', 777888999, 'sub-uuid-12345', 'sub_avatar_777.jpg', 'active')
        """)
        conn.commit()
        conn.close()

        # Querying by telegram_id matches via telegram_id=? on subscriptions table
        avatar_result = self.db.find_subscription_avatar("777888999")
        self.assertEqual(avatar_result, "sub_avatar_777.jpg")

    def test_task5_invalidate_avatar_cache(self):
        """Verify invalidate_avatar_cache removes cache files"""
        dashboard.AVATAR_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        test_file = dashboard.AVATAR_CACHE_DIR / "tg_998877.jpg"
        test_file.write_text("dummy avatar")
        test_flag = dashboard.AVATAR_CACHE_DIR / "tg_none_998877.flag"
        test_flag.write_text("none")

        dashboard.invalidate_avatar_cache(telegram_id=998877)
        self.assertFalse(test_file.exists(), "Cache file tg_998877.jpg was not deleted")
        self.assertFalse(test_flag.exists(), "Cache flag tg_none_998877.flag was not deleted")

    # ─── Task 6: Multilingual Support ───
    def test_task6_setup_wizard_template_multilingual(self):
        """Verify setup_wizard.html renders cleanly and includes i18n keys for all 4 languages"""
        env = Environment(loader=FileSystemLoader(['templates', '.']))
        template = env.get_template('setup_wizard.html')
        rendered = template.render(
            config={
                'admin_username': 'admin',
                'admin_id': 123456,
                'bot_token': '123:ABC',
                'hidify_panel_url': 'https://example.com',
                'hidify_api_key': 'key',
                'hidify_proxy_path': 'proxy',
                'user_proxy_path': 'user',
                'custom_domain': 'bot.example.com',
                'panel_port': 5000,
                'server_public_ip': '1.2.3.4',
                'ssl_status': 'Active',
                'system_lang': 'fa'
            },
            branding={},
            session={},
            url_for=lambda endpoint, **kwargs: f"/{endpoint}",
            force=False,
            get_flashed_messages=lambda **kwargs: []
        )
        self.assertIn('changeSetupLanguage', rendered)
        self.assertIn('I18N_TEXTS', rendered)
        self.assertIn('wizardSystemLangInput', rendered)
        self.assertIn('fa:', rendered)
        self.assertIn('en:', rendered)
        self.assertIn('ru:', rendered)
        self.assertIn('zh:', rendered)

    def test_task6_install_script_syntax_and_languages(self):
        """Verify install.sh includes all 4 languages and has valid bash syntax"""
        with open('install.sh', 'r', encoding='utf-8') as f:
            script_content = f.read()

        self.assertIn('1) فارسی (Persian)', script_content)
        self.assertIn('2) English', script_content)
        self.assertIn('3) Русский (Russian)', script_content)
        self.assertIn('4) 中文 (Chinese)', script_content)
        self.assertIn('SYSTEM_LANG', script_content)
        self.assertIn('DEFAULT_LANGUAGE', script_content)

        # Run bash syntax check if git bash is available
        git_bash = Path("C:/Program Files/Git/bin/bash.exe")
        if git_bash.exists():
            res = subprocess.run([str(git_bash), "-n", "install.sh"], capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, f"install.sh syntax error: {res.stderr}")


if __name__ == '__main__':
    unittest.main()
