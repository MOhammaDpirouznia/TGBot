#!/usr/bin/env python3
import os
import sys
import unittest
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from database import Database

class TestProfileIsolationAndSafety(unittest.TestCase):
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

    def test_init_db_never_propagates_phone_to_zero_telegram_id(self):
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            INSERT INTO users (telegram_id, username, phone_number, is_verified, created_at, updated_at)
            VALUES (99999, 'user_99999', '09121111111', 1, '2026-09-22', '2026-09-22')
        ''')

        cursor.execute('''
            INSERT INTO subscriptions (telegram_id, hidify_uuid, account_name, status, created_at, updated_at)
            VALUES (0, 'uuid-manual-1', 'res_manual_1', 'active', '2026-09-22', '2026-09-22')
        ''')
        cursor.execute('''
            INSERT INTO subscriptions (telegram_id, hidify_uuid, account_name, status, created_at, updated_at)
            VALUES (0, 'uuid-manual-2', 'res_manual_2', 'active', '2026-09-22', '2026-09-22')
        ''')
        conn.commit()
        conn.close()

        self.db.init_db()

        conn = self.db.get_connection()
        c = conn.cursor()
        c.execute('SELECT id, phone_number FROM subscriptions WHERE telegram_id = 0')
        subs = c.fetchall()
        conn.close()

        for s in subs:
            self.assertIsNone(s['phone_number'])

    def test_update_customer_profile_isolation(self):
        res1 = self.db.save_subscription(
            telegram_id=0,
            hidify_uuid='uuid-cust-1',
            plan_id='plan1',
            plan_name='پایه',
            account_name='customer_one',
            data_limit=30,
            duration=30,
            status='active'
        )
        sub1_id = res1['subscription_id']

        res2 = self.db.save_subscription(
            telegram_id=0,
            hidify_uuid='uuid-cust-2',
            plan_id='plan1',
            plan_name='پایه',
            account_name='customer_two',
            data_limit=30,
            duration=30,
            status='active'
        )
        sub2_id = res2['subscription_id']

        up1 = self.db.update_customer_profile(
            sub_id=sub1_id,
            account_name='customer_one',
            full_name='زهرا خادملو',
            phone_number='09118620259',
            birthday='1345/09/15',
            primary_isp='MCI',
            secondary_isp='MTN',
            telegram_username='sinan'
        )
        self.assertTrue(up1['success'])

        dossier2 = self.db.get_subscription_full_details_and_history(sub2_id)
        self.assertTrue(dossier2['success'])
        user2 = dossier2['user']
        cur2 = dossier2['current']

        self.assertEqual(cur2['account_name'], 'customer_two')
        self.assertFalse(user2.get('full_name') == 'زهرا خادملو')
        self.assertFalse(user2.get('phone_number') == '09118620259')
        self.assertFalse(user2.get('birthday') == '1345/09/15')
        self.assertEqual(len(dossier2['user_subscriptions']), 1)

    def test_set_user_phone_rejects_zero_telegram_id(self):
        res = self.db.set_user_phone(0, '09129999999')
        self.assertFalse(res)

if __name__ == '__main__':
    unittest.main()
