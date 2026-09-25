import os
import tempfile
import unittest
from datetime import datetime

from database import Database
from dashboard import enrich_subscription_details


class TestLoyaltyPanelSync(unittest.TestCase):
    def setUp(self):
        self.temp_db_fd, self.temp_db_path = tempfile.mkstemp(suffix=".db")
        self.db = Database(db_path=self.temp_db_path)

        # Base VIP Settings: Bronze 30GB / 300k, Silver 80GB / 800k, Gold 150GB / 1.5M
        self.db.save_vip_settings({
            "system_enabled": True,
            "auto_enabled": True,
            "bronze_threshold_tomans": 300000,
            "bronze_threshold_gb": 30,
            "bronze_discount_percent": 5,
            "bronze_cashback_percent": 5,
            "silver_threshold_tomans": 800000,
            "silver_threshold_gb": 80,
            "silver_discount_percent": 10,
            "silver_cashback_percent": 10,
            "gold_threshold_tomans": 1500000,
            "gold_threshold_gb": 150,
            "gold_discount_percent": 15,
            "gold_cashback_percent": 15,
        })

    def tearDown(self):
        try:
            os.close(self.temp_db_fd)
            os.remove(self.temp_db_path)
        except Exception:
            pass

    def test_loyalty_tier_visual_attributes(self):
        """Test that get_user_loyalty_tier returns color, border_color, glow and badge_class."""
        # User with 0 usage -> none
        loyalty_none = self.db.get_user_loyalty_tier(telegram_id=999999)
        self.assertEqual(loyalty_none["tier"], "none")
        self.assertEqual(loyalty_none["color"], "#64748b")
        self.assertEqual(loyalty_none["border_color"], "#cbd5e1")
        self.assertEqual(loyalty_none["glow"], "transparent")
        self.assertEqual(loyalty_none["badge_class"], "badge-normal")

    def test_farshid0513_threshold_change_scenario(self):
        """
        Simulate user's exact case:
        Farshid0513 has 42.5 GB usage / 60 GB limit.
        At 30 GB threshold -> Bronze (#cd7f32).
        When threshold is raised to 100 GB -> Normal (#64748b).
        """
        tg_id = 79823232
        conn = self.db.get_connection()
        conn.execute("""
            INSERT INTO users (telegram_id, username, full_name, created_at)
            VALUES (?, 'Farshid0513', 'Farshid', ?)
        """, (tg_id, datetime.now().isoformat()))
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO subscriptions (telegram_id, account_name, duration, data_limit, data_used, phone_number, reseller_id, status)
            VALUES (?, 'Farshid0513', 30, 60.0, 42.5, '09120000000', 0, 'active')
        """, (tg_id,))
        sub_id = cur.lastrowid
        conn.commit()
        conn.close()

        # 1. At 30 GB threshold, 60 GB data_limit qualifies for Bronze
        loyalty = self.db.get_user_loyalty_tier(telegram_id=tg_id)
        self.assertEqual(loyalty["tier"], "bronze")
        self.assertEqual(loyalty["title"], "برنزی")
        self.assertEqual(loyalty["color"], "#cd7f32")
        self.assertIn("سطح برنزی", loyalty["badge_html"])

        # Check full history dossier returned to modal
        dossier = self.db.get_subscription_full_details_and_history(sub_id)
        self.assertTrue(dossier["success"])
        self.assertEqual(dossier["loyalty"]["tier"], "bronze")
        self.assertEqual(dossier["loyalty"]["color"], "#cd7f32")
        self.assertEqual(dossier["user"]["loyalty_tier"], "bronze")
        self.assertEqual(dossier["user"]["loyalty_color"], "#cd7f32")

        # Check enrichment for subscription list row
        sub_record = self.db.get_subscription(sub_id)
        enriched = enrich_subscription_details(sub_record, db_instance=self.db)
        self.assertEqual(enriched["loyalty_tier"], "bronze")
        self.assertEqual(enriched["loyalty_color"], "#cd7f32")
        self.assertEqual(enriched["loyalty_border"], "#cd7f32")

        # 2. Admin raises Bronze threshold to 100 GB
        self.db.save_vip_settings({
            "bronze_threshold_gb": 100
        })

        # Now 60 GB is less than 100 GB -> becomes 'none' (Normal customer)
        loyalty_after = self.db.get_user_loyalty_tier(telegram_id=tg_id)
        self.assertEqual(loyalty_after["tier"], "none")
        self.assertEqual(loyalty_after["title"], "عادی")
        self.assertEqual(loyalty_after["color"], "#64748b")

        # Dossier and enrichment immediately reflect 'none'
        dossier_after = self.db.get_subscription_full_details_and_history(sub_id)
        self.assertEqual(dossier_after["loyalty"]["tier"], "none")
        self.assertEqual(dossier_after["user"]["loyalty_tier"], "none")

        enriched_after = enrich_subscription_details(sub_record, db_instance=self.db)
        self.assertEqual(enriched_after["loyalty_tier"], "none")
        self.assertEqual(enriched_after["loyalty_color"], "#64748b")

    def test_sync_all_users_vip_tiers(self):
        """Test sync_all_users_vip_tiers updates the DB users table."""
        tg_id = 888888
        conn = self.db.get_connection()
        conn.execute("""
            INSERT INTO users (telegram_id, username, full_name, created_at, vip_tier, is_vip)
            VALUES (?, 'GoldUser', 'Gold User', ?, 'none', 0)
        """, (tg_id, datetime.now().isoformat()))
        conn.execute("""
            INSERT INTO subscriptions (telegram_id, account_name, duration, data_limit, data_used, reseller_id, status)
            VALUES (?, 'GoldUser', 30, 200.0, 50.0, 0, 'active')
        """, (tg_id,))
        conn.commit()
        conn.close()

        # Run sync
        count = self.db.sync_all_users_vip_tiers(reseller_id=0)
        self.assertGreaterEqual(count, 1)

        user_db = self.db.get_user(tg_id)
        self.assertEqual(user_db["vip_tier"], "gold")
        self.assertEqual(user_db["is_vip"], 1)


if __name__ == "__main__":
    unittest.main()
