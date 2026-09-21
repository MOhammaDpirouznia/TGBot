import unittest
import sqlite3
import tempfile
import os
from datetime import datetime, timedelta, timezone

from database import Database


class TestLuckyWheelIsolatedSystem(unittest.TestCase):
    def setUp(self):
        self.temp_db_fd, self.temp_db_path = tempfile.mkstemp(suffix=".db")
        self.db = Database(db_path=self.temp_db_path)
        # Clear seeded prizes for clean isolated test assertions
        conn = self.db.get_connection()
        conn.execute("DELETE FROM lucky_wheel_prizes")
        conn.commit()
        conn.close()

    def tearDown(self):
        try:
            os.close(self.temp_db_fd)
            os.remove(self.temp_db_path)
        except Exception:
            pass

    def test_schema_has_daily_limit(self):
        """Check that lucky_wheel_prizes table has daily_limit column."""
        conn = self.db.get_connection()
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(lucky_wheel_prizes)")
        columns = [row["name"] for row in cur.fetchall()]
        conn.close()
        self.assertIn("daily_limit", columns)
        self.assertIn("target_audience", columns)
        self.assertIn("chance_weight", columns)

    def test_chance_percent_calculation(self):
        """Check dynamic calculation of chance_percent based on total active weights."""
        # Add 2 admin prizes with weights 25 and 75
        self.db.add_lucky_wheel_prize(
            reseller_id=0,
            title="جایزه ۱ گیگ",
            prize_type="traffic",
            prize_value="1",
            chance_weight=25,
            target_audience="all",
            daily_limit=10,
            is_active=1
        )
        self.db.add_lucky_wheel_prize(
            reseller_id=0,
            title="جایزه تخفیف",
            prize_type="discount",
            prize_value="20",
            chance_weight=75,
            target_audience="active_only",
            daily_limit=0,
            is_active=1
        )

        prizes = self.db.get_lucky_wheel_prizes(reseller_id=0, active_only=True)
        self.assertEqual(len(prizes), 2)
        
        p1 = next(p for p in prizes if p["title"] == "جایزه ۱ گیگ")
        p2 = next(p for p in prizes if p["title"] == "جایزه تخفیف")
        
        self.assertEqual(p1["chance_percent"], 25.0)
        self.assertEqual(p2["chance_percent"], 75.0)
        self.assertEqual(p1["daily_limit"], 10)
        self.assertEqual(p2["daily_limit"], 0)
        self.assertEqual(p2["target_audience"], "active_only")

    def test_reseller_isolation_and_fallback(self):
        """Check strict isolation between admin and resellers, and fallback behavior."""
        # Admin defines prizes
        self.db.add_lucky_wheel_prize(
            reseller_id=0,
            title="جایزه مدیریت",
            prize_type="traffic",
            prize_value="1",
            chance_weight=10,
            target_audience="all"
        )

        # Reseller 1 has no prizes defined -> fallback to admin prizes
        reseller_1_prizes = self.db.get_lucky_wheel_prizes(reseller_id=1, include_fallback=True)
        self.assertEqual(len(reseller_1_prizes), 1)
        self.assertEqual(reseller_1_prizes[0]["title"], "جایزه مدیریت")

        # But without fallback (e.g. in reseller branding page), it should return empty
        reseller_1_custom_only = self.db.get_lucky_wheel_prizes(reseller_id=1, include_fallback=False)
        self.assertEqual(len(reseller_1_custom_only), 0)

        # Now Reseller 1 defines their own prize
        self.db.add_lucky_wheel_prize(
            reseller_id=1,
            title="جایزه اختصاصی نماینده ۱",
            prize_type="wallet",
            prize_value="50000",
            chance_weight=50,
            target_audience="active_only"
        )

        # Reseller 1 now gets ONLY their prize (no admin prize)
        reseller_1_prizes_after = self.db.get_lucky_wheel_prizes(reseller_id=1, include_fallback=True)
        self.assertEqual(len(reseller_1_prizes_after), 1)
        self.assertEqual(reseller_1_prizes_after[0]["title"], "جایزه اختصاصی نماینده ۱")
        self.assertEqual(reseller_1_prizes_after[0]["reseller_id"], 1)

        # Admin still gets ONLY admin prize
        admin_prizes = self.db.get_lucky_wheel_prizes(reseller_id=0)
        self.assertEqual(len(admin_prizes), 1)
        self.assertEqual(admin_prizes[0]["title"], "جایزه مدیریت")

        # Reseller 2 still falls back to admin prizes
        reseller_2_prizes = self.db.get_lucky_wheel_prizes(reseller_id=2, include_fallback=True)
        self.assertEqual(len(reseller_2_prizes), 1)
        self.assertEqual(reseller_2_prizes[0]["title"], "جایزه مدیریت")

    def test_custom_cooldown_hours(self):
        """Check that can_user_spin_wheel respects custom cooldown_hours."""
        user_ident = "customer_uuid_12345"
        # User has never spun
        can_spin, rem_str, rem_sec = self.db.can_user_spin_wheel(user_ident=user_ident, cooldown_hours=12)
        self.assertTrue(can_spin)
        self.assertEqual(rem_sec, 0)

        # Record a spin 10 hours ago
        ten_hours_ago = (datetime.now(timezone.utc) - timedelta(hours=10)).isoformat()
        conn = self.db.get_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO lucky_wheel_spins (user_ident, reseller_id, prize_id, prize_title, prize_type, prize_value, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (user_ident, 0, 1, "test", "traffic", "1", ten_hours_ago))
        conn.commit()
        conn.close()

        # Under 24h cooldown, user CANNOT spin (needs ~14 more hours)
        can_spin_24, _, rem_sec_24 = self.db.can_user_spin_wheel(user_ident=user_ident, cooldown_hours=24)
        self.assertFalse(can_spin_24)
        self.assertGreater(rem_sec_24, 3600 * 13)

        # Under 12h cooldown, user CANNOT spin yet (needs ~2 hours)
        can_spin_12, _, rem_sec_12 = self.db.can_user_spin_wheel(user_ident=user_ident, cooldown_hours=12)
        self.assertFalse(can_spin_12)
        self.assertLess(rem_sec_12, 3600 * 3)

        # Under 6h cooldown, user CAN spin (10h > 6h)
        can_spin_6, _, rem_sec_6 = self.db.can_user_spin_wheel(user_ident=user_ident, cooldown_hours=6)
        self.assertTrue(can_spin_6)
        self.assertEqual(rem_sec_6, 0)

    def test_prize_update(self):
        """Check updating a prize including daily_limit and target_audience."""
        add_res = self.db.add_lucky_wheel_prize(
            reseller_id=0,
            title="جایزه اولیه",
            prize_type="traffic",
            prize_value="1",
            chance_weight=10,
            target_audience="all",
            daily_limit=0
        )
        prize_id = add_res["prize_id"]

        update_res = self.db.update_lucky_wheel_prize(
            prize_id=prize_id,
            reseller_id=0,
            title="جایزه آپدیت شده",
            prize_type="plan",
            prize_value="اشتراک یک‌ماهه",
            chance_weight=20,
            target_audience="active_only",
            daily_limit=5,
            is_active=1
        )
        self.assertTrue(update_res["success"])

        prizes = self.db.get_lucky_wheel_prizes(reseller_id=0)
        p = next(x for x in prizes if x["id"] == prize_id)
        self.assertEqual(p["title"], "جایزه آپدیت شده")
        self.assertEqual(p["prize_type"], "plan")
        self.assertEqual(p["chance_weight"], 20)
        self.assertEqual(p["target_audience"], "active_only")
        self.assertEqual(p["daily_limit"], 5)


if __name__ == "__main__":
    unittest.main()
