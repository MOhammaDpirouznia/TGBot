import unittest
import sqlite3
import tempfile
import os
from datetime import datetime, timedelta, timezone

from database import Database


class TestVipTiersAndSocialTasks(unittest.TestCase):
    def setUp(self):
        self.temp_db_fd, self.temp_db_path = tempfile.mkstemp(suffix=".db")
        self.db = Database(db_path=self.temp_db_path)

        # Configure VIP settings
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
            "birthday_reward_enabled": True,
            "birthday_reward_type": "traffic",
            "birthday_reward_val": "5",
            "anniversary_reward_enabled": True,
            "anniversary_reward_type": "wallet",
            "anniversary_reward_val": "50000"
        })

    def tearDown(self):
        try:
            os.close(self.temp_db_fd)
            os.remove(self.temp_db_path)
        except Exception:
            pass

    def _create_user(self, telegram_id, username="test_user", full_name="Test User", created_at=None, birthday=None, wallet_balance=0):
        conn = self.db.get_connection()
        conn.execute("""
            INSERT INTO users (telegram_id, username, full_name, created_at, birthday, wallet_balance)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (telegram_id, username, full_name, created_at or datetime.now().isoformat(), birthday, wallet_balance))
        conn.commit()
        conn.close()

    def test_schema_has_vip_columns_and_social_tables(self):
        """Verify new schema columns and social tasks tables exist."""
        conn = self.db.get_connection()
        cur = conn.cursor()

        cur.execute("PRAGMA table_info(users)")
        user_cols = [r["name"] for r in cur.fetchall()]
        self.assertIn("vip_tier", user_cols)
        self.assertIn("birthday", user_cols)
        self.assertIn("last_birthday_reward_year", user_cols)
        self.assertIn("last_anniversary_reward_year", user_cols)

        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r["name"] for r in cur.fetchall()]
        self.assertIn("social_tasks", tables)
        self.assertIn("user_social_tasks", tables)
        conn.close()

    def test_loyalty_tier_determination(self):
        """Verify automatic tier calculation based on spending and traffic."""
        user_id = 999111
        self._create_user(user_id, username="tier_user")

        # 1. New user with 0 spent -> none
        tier_info = self.db.get_user_loyalty_tier(user_id)
        self.assertEqual(tier_info["tier"], "none")
        self.assertEqual(tier_info["discount_percent"], 0)
        self.assertEqual(tier_info["next_tier"], "bronze")
        self.assertEqual(tier_info["remaining_tomans"], 300000)

        # 2. User spends 350,000 Tomans -> bronze (5% discount)
        conn = self.db.get_connection()
        conn.execute("""
            INSERT INTO transactions (user_id, order_id, amount, status, created_at)
            VALUES (?, 'ORD-1', ?, 'approved', ?)
        """, (user_id, 350000, datetime.now().isoformat()))
        conn.commit()
        conn.close()

        tier_info = self.db.get_user_loyalty_tier(user_id)
        self.assertEqual(tier_info["tier"], "bronze")
        self.assertEqual(tier_info["discount_percent"], 5)
        self.assertEqual(tier_info["cashback_percent"], 5)
        self.assertEqual(tier_info["next_tier"], "silver")
        self.assertEqual(tier_info["remaining_tomans"], 450000)

        # 3. User spends another 600,000 Tomans (total 950,000) -> silver (10% discount)
        conn = self.db.get_connection()
        conn.execute("""
            INSERT INTO transactions (user_id, order_id, amount, status, created_at)
            VALUES (?, 'ORD-2', ?, 'approved', ?)
        """, (user_id, 600000, datetime.now().isoformat()))
        conn.commit()
        conn.close()

        tier_info = self.db.get_user_loyalty_tier(user_id)
        self.assertEqual(tier_info["tier"], "silver")
        self.assertEqual(tier_info["discount_percent"], 10)
        self.assertEqual(tier_info["cashback_percent"], 10)
        self.assertEqual(tier_info["next_tier"], "gold")
        self.assertEqual(tier_info["remaining_tomans"], 550000)

        # 4. User spends another 600,000 Tomans (total 1,550,000) -> gold (15% discount)
        conn = self.db.get_connection()
        conn.execute("""
            INSERT INTO transactions (user_id, order_id, amount, status, created_at)
            VALUES (?, 'ORD-3', ?, 'approved', ?)
        """, (user_id, 600000, datetime.now().isoformat()))
        conn.commit()
        conn.close()

        tier_info = self.db.get_user_loyalty_tier(user_id)
        self.assertEqual(tier_info["tier"], "gold")
        self.assertEqual(tier_info["discount_percent"], 15)
        self.assertEqual(tier_info["cashback_percent"], 15)
        self.assertIsNone(tier_info["next_tier"])
        self.assertEqual(tier_info["progress_percent"], 100)

    def test_manual_vip_tier_override(self):
        """Admin can manually set an exact tier."""
        user_id = 999222
        self._create_user(user_id, username="manual_vip")

        self.db.set_user_vip(user_id, is_vip=True, vip_type="manual", vip_tier="silver")
        tier_info = self.db.get_user_loyalty_tier(user_id)
        self.assertEqual(tier_info["tier"], "silver")
        self.assertEqual(tier_info["discount_percent"], 10)

    def test_birthday_and_anniversary_rewards_yearly_lock(self):
        """Verify birthday and anniversary rewards are credited and locked per year."""
        user_id = 999333
        now_dt = datetime.now()
        # Set created_at to 1 year ago so anniversary triggers
        past_anniv = (now_dt - timedelta(days=365)).strftime("%Y-%m-%d %H:%M:%S")

        self._create_user(user_id, username="bday_user", created_at=past_anniv, birthday=now_dt.strftime("%m-%d"))

        # Also create a subscription for traffic credit
        conn = self.db.get_connection()
        conn.execute("""
            INSERT INTO subscriptions (telegram_id, account_name, data_limit, data_used, status)
            VALUES (?, 'Sub1', 50, 10, 'active')
        """, (user_id,))
        conn.commit()
        conn.close()

        # First execution -> should reward both birthday and anniversary
        rewards = self.db.process_vip_anniversary_and_birthday_rewards(user_id)
        self.assertTrue(len(rewards) > 0)
        self.assertTrue(any("هدیه" in r.get("note", "") for r in rewards))

        # Check DB that year locks are recorded
        u = self.db.get_user(user_id)
        self.assertTrue(u["last_birthday_reward_year"] > 0 or u["last_anniversary_reward_year"] > 0)

        # Second execution in same year -> no new rewards
        rewards2 = self.db.process_vip_anniversary_and_birthday_rewards(user_id)
        self.assertEqual(len(rewards2), 0)

    def test_social_tasks_crud(self):
        """Test adding, updating, toggling, and deleting social tasks."""
        task_id = self.db.add_social_task(
            title="تست عضویت",
            description="عضویت در کانال آزمایشی",
            task_type="telegram_channel",
            target_count=1,
            target_link="https://t.me/testchannel",
            reward_type="traffic",
            reward_value="2",
            is_active=1
        )
        self.assertIsInstance(task_id, int)

        task = self.db.get_social_task(task_id)
        self.assertIsNotNone(task)
        self.assertEqual(task["title"], "تست عضویت")
        self.assertEqual(task["reward_value"], "2")

        # Update task
        self.db.update_social_task(task_id, title="تست عضویت ویرایش شده", reward_value="3")
        task_updated = self.db.get_social_task(task_id)
        self.assertEqual(task_updated["title"], "تست عضویت ویرایش شده")
        self.assertEqual(task_updated["reward_value"], "3")

        # Toggle task
        self.db.toggle_social_task(task_id)
        task_disabled = self.db.get_social_task(task_id)
        self.assertEqual(task_disabled["is_active"], 0)

        # Delete task
        self.db.delete_social_task(task_id)
        self.assertIsNone(self.db.get_social_task(task_id))

    def test_referral_task_progress_and_claim_anti_fraud(self):
        """Test referral task verification: requires exact referral count and blocks duplicates."""
        user_id = 999444
        self._create_user(user_id, username="ref_master")

        # Create active subscription to receive traffic reward
        conn = self.db.get_connection()
        conn.execute("""
            INSERT INTO subscriptions (telegram_id, account_name, data_limit, data_used, status)
            VALUES (?, 'RefSub', 20, 5, 'active')
        """, (user_id,))
        conn.commit()
        conn.close()

        # Add invite 5 friends task
        task_id = self.db.add_social_task(
            title="دعوت ۵ دوست",
            description="۵ نفر از دوستان خود را دعوت کنید",
            task_type="invite_friends",
            target_count=5,
            reward_type="traffic",
            reward_value="5",
            is_active=1
        )

        # User currently has 0 referrals -> progress 0/5
        progress_list = self.db.get_user_social_tasks_progress(user_id)
        task_prog = next(t for t in progress_list if t["id"] == task_id)
        self.assertEqual(task_prog["progress_count"], 0)

        # Attempt claim with 0 referrals -> anti-fraud fails
        claim_res = self.db.verify_and_claim_social_task(user_id, task_id)
        self.assertFalse(claim_res["success"])
        self.assertIn("دعوت", claim_res["error"])

        # Add 5 valid referrals
        conn = self.db.get_connection()
        for i in range(5):
            conn.execute("""
                INSERT INTO referrals (referrer_id, referred_id, status, created_at)
                VALUES (?, ?, 'completed', ?)
            """, (user_id, 8000 + i, datetime.now().isoformat()))
        conn.commit()
        conn.close()

        # Progress should now be 5/5
        progress_list = self.db.get_user_social_tasks_progress(user_id)
        task_prog = next(t for t in progress_list if t["id"] == task_id)
        self.assertEqual(task_prog["progress_count"], 5)
        self.assertEqual(task_prog["progress_percent"], 100)

        # Claim should succeed
        claim_res = self.db.verify_and_claim_social_task(user_id, task_id)
        self.assertTrue(claim_res["success"])
        self.assertIn("5 گیگابایت", claim_res["message"])

        # Check that subscription traffic increased from 20 to 25
        conn = self.db.get_connection()
        sub = conn.execute("SELECT data_limit FROM subscriptions WHERE telegram_id = ?", (user_id,)).fetchone()
        conn.close()
        self.assertEqual(sub["data_limit"], 25)

        # Attempt to claim again -> anti-fraud prevents duplicate claim
        dup_claim = self.db.verify_and_claim_social_task(user_id, task_id)
        self.assertFalse(dup_claim["success"])
        self.assertIn("قبلاً", dup_claim["error"])

    def test_vip_loyalty_permanent_discount_applied(self):
        """Verify that loyalty tiers provide their exact discount percent."""
        # 1. Bronze user (5% discount)
        u_bronze = 999555
        self._create_user(u_bronze, username="bronze_user")
        self.db.set_user_vip(u_bronze, is_vip=True, vip_type="manual", vip_tier="bronze")
        tier_b = self.db.get_user_loyalty_tier(u_bronze)
        self.assertEqual(tier_b["discount_percent"], 5)
        price = 200000
        disc_amount = int(round((price * tier_b["discount_percent"]) / 100))
        self.assertEqual(price - disc_amount, 190000)

        # 2. Gold user (15% discount)
        u_gold = 999666
        self._create_user(u_gold, username="gold_user")
        self.db.set_user_vip(u_gold, is_vip=True, vip_type="manual", vip_tier="gold")
        tier_g = self.db.get_user_loyalty_tier(u_gold)
        self.assertEqual(tier_g["discount_percent"], 15)
        disc_amount_g = int(round((price * tier_g["discount_percent"]) / 100))
        self.assertEqual(price - disc_amount_g, 170000)

    def test_reseller_vip_settings_isolation(self):
        """Verify that reseller VIP settings are isolated per reseller and fall back cleanly."""
        reseller_id_1 = 101
        reseller_id_2 = 102

        # Reseller 1 saves custom VIP settings (e.g. Bronze threshold = 200,000, 8% discount)
        self.db.save_vip_settings({
            "bronze_threshold_tomans": 200000,
            "bronze_discount_percent": 8,
            "gold_threshold_tomans": 1200000,
            "gold_discount_percent": 20
        }, reseller_id=reseller_id_1)

        # Reseller 1 settings should reflect custom values
        r1_sets = self.db.get_vip_settings(reseller_id=reseller_id_1)
        self.assertEqual(r1_sets["bronze_threshold_tomans"], 200000)
        self.assertEqual(r1_sets["bronze_discount_percent"], 8)
        self.assertEqual(r1_sets["gold_threshold_tomans"], 1200000)
        self.assertEqual(r1_sets["gold_discount_percent"], 20)

        # Global admin settings should remain intact
        admin_sets = self.db.get_vip_settings(reseller_id=0)
        self.assertEqual(admin_sets["bronze_threshold_tomans"], 300000)
        self.assertEqual(admin_sets["bronze_discount_percent"], 5)

        # Reseller 2 has no custom settings -> falls back to admin defaults
        r2_sets = self.db.get_vip_settings(reseller_id=reseller_id_2)
        self.assertEqual(r2_sets["bronze_threshold_tomans"], 300000)
        self.assertEqual(r2_sets["bronze_discount_percent"], 5)

    def test_reseller_social_tasks_isolation(self):
        """Verify that social tasks are strictly isolated between resellers."""
        r1_id = 201
        r2_id = 202

        t1 = self.db.add_social_task("R1 Mission", "custom", "traffic", "2", reseller_id=r1_id)
        t2 = self.db.add_social_task("R2 Mission", "custom", "wallet", "15000", reseller_id=r2_id)

        # Strict reseller query for R1 should only return R1 tasks
        r1_tasks = self.db.get_social_tasks(reseller_id=r1_id, active_only=False, strict_reseller=True)
        r1_ids = [t["id"] for t in r1_tasks]
        self.assertIn(t1, r1_ids)
        self.assertNotIn(t2, r1_ids)

        # Strict reseller query for R2 should only return R2 tasks
        r2_tasks = self.db.get_social_tasks(reseller_id=r2_id, active_only=False, strict_reseller=True)
        r2_ids = [t["id"] for t in r2_tasks]
        self.assertIn(t2, r2_ids)
        self.assertNotIn(t1, r2_ids)

    def test_reseller_vip_dashboard_stats_and_user_ownership(self):
        """Verify reseller-specific VIP dashboard stats and ownership check."""
        r_id = 301
        u_owned = 888111
        u_other = 888222

        conn = self.db.get_connection()
        conn.execute("INSERT INTO users (telegram_id, username, reseller_id, is_vip, vip_tier) VALUES (?, 'r_user', ?, 1, 'gold')", (u_owned, r_id))
        conn.execute("INSERT INTO users (telegram_id, username, reseller_id, is_vip, vip_tier) VALUES (?, 'other_user', 999, 1, 'gold')", (u_other,))
        conn.execute("INSERT INTO transactions (order_id, user_id, amount, status, reseller_id) VALUES ('ORD-R301', ?, 100000, 'approved', ?)", (u_owned, r_id))
        conn.execute("INSERT INTO subscriptions (telegram_id, reseller_id, status) VALUES (?, ?, 'active')", (u_owned, r_id))
        conn.commit()
        conn.close()

        # Ownership test
        self.assertTrue(self.db.is_user_owned_by_reseller(r_id, u_owned))
        self.assertFalse(self.db.is_user_owned_by_reseller(r_id, u_other))

        # Stats test
        stats = self.db.get_vip_dashboard_stats(reseller_id=r_id)
        self.assertEqual(stats["total_vips"], 1)
        self.assertEqual(stats["vip_revenue"], 100000)
        self.assertEqual(stats["vip_active_subs"], 1)

        # Users list test
        vip_list = self.db.get_vip_users_list(reseller_id=r_id)
        self.assertEqual(len(vip_list), 1)
        self.assertEqual(vip_list[0]["telegram_id"], u_owned)


if __name__ == "__main__":
    unittest.main()

