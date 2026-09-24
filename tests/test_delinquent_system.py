import unittest
import os
import tempfile
import sqlite3
import json
from datetime import datetime, timedelta

from database import Database, get_now_iso
from services.debt_restriction_service import (
    DEFAULT_DEBT_RESTRICTION_SETTINGS,
    format_notification_text,
    process_debt_restrictions
)

class TestDelinquentSystem(unittest.TestCase):
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

    def test_settings_admin_and_reseller_isolation(self):
        # Admin settings default
        admin_settings = self.db.get_debt_restriction_settings(reseller_id=None)
        self.assertFalse(admin_settings["enabled"])
        self.assertEqual(admin_settings["traffic_limit_mb"], 500)

        # Modify and save admin settings
        admin_settings["enabled"] = True
        admin_settings["traffic_limit_mb"] = 750
        self.db.save_debt_restriction_settings(admin_settings, reseller_id=None)

        # Verify admin settings updated
        saved_admin = self.db.get_debt_restriction_settings(reseller_id=None)
        self.assertTrue(saved_admin["enabled"])
        self.assertEqual(saved_admin["traffic_limit_mb"], 750)

        # Verify reseller settings are independent and still default
        reseller_settings = self.db.get_debt_restriction_settings(reseller_id=42)
        self.assertFalse(reseller_settings["enabled"])
        self.assertEqual(reseller_settings["traffic_limit_mb"], 500)

        # Modify reseller settings
        reseller_settings["enabled"] = True
        reseller_settings["continuous_usage_minutes"] = 15
        self.db.save_debt_restriction_settings(reseller_settings, reseller_id=42)

        # Check reseller saved
        saved_reseller = self.db.get_debt_restriction_settings(reseller_id=42)
        self.assertTrue(saved_reseller["enabled"])
        self.assertEqual(saved_reseller["continuous_usage_minutes"], 15)

        # Admin settings should still be 750
        saved_admin2 = self.db.get_debt_restriction_settings(reseller_id=None)
        self.assertEqual(saved_admin2["traffic_limit_mb"], 750)

    def test_toggle_and_bulk_delinquent(self):
        # Create dummy subscription
        conn = self.db.get_connection()
        c = conn.cursor()
        now = get_now_iso()
        c.execute("""
            INSERT INTO subscriptions (
                id, telegram_id, account_name, hidify_uuid, status, payment_status, debt_amount, 
                in_debt_restriction, created_at, updated_at
            ) VALUES (1, 1001, 'TestUser1', 'uuid-1', 'active', 'unpaid', 50000, 0, ?, ?)
        """, (now, now))
        c.execute("""
            INSERT INTO subscriptions (
                id, telegram_id, account_name, hidify_uuid, status, payment_status, debt_amount, 
                in_debt_restriction, created_at, updated_at
            ) VALUES (2, 1002, 'TestUser2', 'uuid-2', 'active', 'unpaid', 80000, 0, ?, ?)
        """, (now, now))
        conn.commit()
        conn.close()

        # Initially delinquent count should be 0
        self.assertEqual(self.db.get_delinquent_count(), 0)

        # Toggle sub 1
        res1 = self.db.toggle_subscription_delinquent(1)
        self.assertTrue(res1["success"])
        self.assertTrue(res1["is_delinquent"])
        self.assertEqual(self.db.get_delinquent_count(), 1)

        # Toggle sub 1 again to unmark
        res2 = self.db.toggle_subscription_delinquent(1)
        self.assertTrue(res2["success"])
        self.assertFalse(res2["is_delinquent"])
        self.assertEqual(self.db.get_delinquent_count(), 0)

        # Bulk mark both sub 1 and 2
        bulk_res = self.db.set_subscriptions_delinquent_bulk([1, 2], is_delinquent=True)
        self.assertEqual(bulk_res, 2)
        self.assertEqual(self.db.get_delinquent_count(), 2)

        # Bulk unmark
        hiddify_calls = []
        def dummy_hidify_update(uuid, enable, is_active, reseller_id=None):
            hiddify_calls.append((uuid, enable, is_active))

        bulk_unmark = self.db.set_subscriptions_delinquent_bulk([1, 2], is_delinquent=False, hidify_update_func=dummy_hidify_update)
        self.assertEqual(bulk_unmark, 2)
        self.assertEqual(self.db.get_delinquent_count(), 0)

    def test_notification_formatting(self):
        settings = dict(DEFAULT_DEBT_RESTRICTION_SETTINGS)
        sub = {
            "id": 99,
            "account_name": "علی احمدی",
            "debt_amount": 120000,
            "hidify_uuid": "abc-123"
        }
        msg = format_notification_text(
            settings["template_start_traffic"],
            sub,
            settings,
            trigger_reason="سقف مصرف ترافیک چرخه (500 مگابایت)",
            db_instance=self.db
        )
        self.assertIn("علی احمدی", msg)
        self.assertIn("120,000", msg)
    def test_process_debt_restrictions_cycle(self):
        # 1. Enable settings
        settings = dict(DEFAULT_DEBT_RESTRICTION_SETTINGS)
        settings["enabled"] = True
        settings["continuous_usage_minutes"] = 5
        settings["penalty_duration_minutes"] = 60
        self.db.save_debt_restriction_settings(settings, reseller_id=None)

        conn = self.db.get_connection()
        c = conn.cursor()
        now = datetime.now()
        now_iso = get_now_iso()
        # Session started 10 minutes ago, online now
        past_session = (now - timedelta(minutes=10)).isoformat()
        c.execute("""
            INSERT INTO subscriptions (
                id, telegram_id, account_name, hidify_uuid, status, payment_status, debt_amount, 
                in_debt_restriction, is_online, debt_restriction_session_start, created_at, updated_at
            ) VALUES (10, 2001, 'ThrottledUser', 'uuid-10', 'active', 'unpaid', 60000, 1, 1, ?, ?, ?)
        """, (past_session, now_iso, now_iso))
        conn.commit()
        conn.close()

        hidify_updates = []
        def dummy_hidify_update(uuid, enable, is_active, reseller_id=None):
            hidify_updates.append((uuid, enable, is_active))

        # Disable external notifications for unit test
        settings["notify_telegram"] = False
        settings["notify_sms"] = False
        self.db.save_debt_restriction_settings(settings, reseller_id=None)

        # Process restrictions
        actions = process_debt_restrictions(self.db, hidify_update_func=dummy_hidify_update)
        self.assertEqual(actions.get("restricted"), 1)
        self.assertEqual(len(hidify_updates), 1)
        self.assertEqual(hidify_updates[0], ('uuid-10', False, False))

        # Verify DB updated
        sub = self.db.get_subscription(10)
        self.assertIsNotNone(sub.get("debt_restricted_until"))

        # 2. Simulate penalty expiration
        conn = self.db.get_connection()
        c = conn.cursor()
        expired_until = (now - timedelta(minutes=5)).isoformat()
        c.execute("UPDATE subscriptions SET debt_restricted_until = ? WHERE id = 10", (expired_until,))
        conn.commit()
        conn.close()

        hidify_updates.clear()
        # Process again -> should restore connection
        actions2 = process_debt_restrictions(self.db, hidify_update_func=dummy_hidify_update)
        self.assertEqual(actions2.get("re_enabled"), 1)
        self.assertEqual(len(hidify_updates), 1)
        self.assertEqual(hidify_updates[0], ('uuid-10', True, True))

        # Verify sub is restored
        sub_restored = self.db.get_subscription(10)
        self.assertIsNone(sub_restored.get("debt_restricted_until"))

    def test_flask_routes_exist(self):
        from dashboard import app
        rules = [rule.rule for rule in app.url_map.iter_rules()]
        endpoints = [rule.endpoint for rule in app.url_map.iter_rules()]

        self.assertIn("/admin/delinquent-settings", rules)
        self.assertIn("admin_delinquent_settings", endpoints)

        self.assertIn("/reseller/delinquent-settings", rules)
        self.assertIn("reseller_delinquent_settings", endpoints)

        self.assertIn("/api/subscriptions/<int:sub_id>/toggle-delinquent", rules)
        self.assertIn("api_admin_toggle_delinquent", endpoints)

        self.assertIn("/api/reseller/subscriptions/<int:sub_id>/toggle-delinquent", rules)
        self.assertIn("api_reseller_toggle_delinquent", endpoints)

    def test_debt_auto_disable_deadline_processing(self):
        from utils import calculate_debt_auto_disable_at
        from services.debt_restriction_service import process_debt_auto_disable_deadlines, re_enable_if_restricted

        base_dt = datetime(2026, 9, 23, 14, 30, 15)

        # 1. Test calculation preservation of hour, minute, second
        iso_3_days = calculate_debt_auto_disable_at(days_val=3, base_dt=base_dt)
        dt_3_days = datetime.fromisoformat(iso_3_days)
        self.assertEqual(dt_3_days.hour, 14)
        self.assertEqual(dt_3_days.minute, 30)
        self.assertEqual(dt_3_days.second, 15)
        self.assertEqual((dt_3_days - base_dt).days, 3)

        # 2. Test shamsi date calculation
        iso_shamsi = calculate_debt_auto_disable_at(shamsi_date_str="1405/07/10", base_dt=base_dt)
        dt_shamsi = datetime.fromisoformat(iso_shamsi)
        self.assertEqual(dt_shamsi.hour, 14)
        self.assertEqual(dt_shamsi.minute, 30)
        self.assertEqual(dt_shamsi.second, 15)

        # 3. Setup test subscriptions
        conn = self.db.get_connection()
        c = conn.cursor()
        # Sub 101: expired deadline and unpaid debt -> MUST be disabled
        past_iso = (datetime.now() - timedelta(minutes=10)).isoformat()
        c.execute("""
            INSERT INTO subscriptions (id, telegram_id, account_name, hidify_uuid, status, payment_status, debt_amount, debt_auto_disable_at)
            VALUES (101, 1001, 'debtor_expired', 'uuid-101', 'active', 'unpaid', 50000, ?)
        """, (past_iso,))

        # Sub 102: future deadline and unpaid debt -> MUST stay active
        future_iso = (datetime.now() + timedelta(days=2)).isoformat()
        c.execute("""
            INSERT INTO subscriptions (id, telegram_id, account_name, hidify_uuid, status, payment_status, debt_amount, debt_auto_disable_at)
            VALUES (102, 1002, 'debtor_future', 'uuid-102', 'active', 'unpaid', 50000, ?)
        """, (future_iso,))

        # Sub 103: past deadline but paid -> MUST NOT be touched
        c.execute("""
            INSERT INTO subscriptions (id, telegram_id, account_name, hidify_uuid, status, payment_status, debt_amount, debt_auto_disable_at)
            VALUES (103, 1003, 'debtor_settled', 'uuid-103', 'active', 'paid', 0, ?)
        """, (past_iso,))
        conn.commit()
        conn.close()

        # Mock Hiddify update tracking
        hidify_updates = []
        def dummy_hidify_update(uuid, enable=True, is_active=True, **kwargs):
            hidify_updates.append((uuid, enable, is_active))
            return {"success": True}

        # Run deadline processor
        stats = process_debt_auto_disable_deadlines(self.db, hidify_update_func=dummy_hidify_update)
        self.assertEqual(stats["disabled"], 1)
        self.assertEqual(len(hidify_updates), 1)
        self.assertEqual(hidify_updates[0], ('uuid-101', False, False))

        # Check sub 101 in DB
        sub101 = self.db.get_subscription(101)
        self.assertEqual(sub101.get("status"), "disabled")
        self.assertIn("بدهی", str(sub101.get("disable_reason")))

        # Check sub 102 in DB
        sub102 = self.db.get_subscription(102)
        self.assertEqual(sub102.get("status"), "active")

        # 4. Settle debt for sub 101 -> must restore active and clear debt_auto_disable_at
        hidify_updates.clear()
        res_clear = self.db.clear_subscription_debt(101, settled_by="تست خودکار")
        self.assertTrue(res_clear.get("success"))

        sub101_after = self.db.get_subscription(101)
        self.assertEqual(sub101_after.get("status"), "active")
        self.assertIsNone(sub101_after.get("debt_auto_disable_at"))
        self.assertEqual(sub101_after.get("debt_amount"), 0)
        self.assertEqual(sub101_after.get("payment_status"), "paid")

        # Re-enable on Hiddify when debt cleared
        re_enable_if_restricted(101, self.db, hidify_update_func=dummy_hidify_update)
        self.assertEqual(len(hidify_updates), 1)
        self.assertEqual(hidify_updates[0], ('uuid-101', True, True))


if __name__ == "__main__":
    unittest.main()

