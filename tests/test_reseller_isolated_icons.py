import unittest
import sqlite3
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

from database import Database
from admin_manager import get_plan_icon, get_plan_telegram_emoji, ICON_TO_TELEGRAM_EMOJI


class TestResellerIsolatedIcons(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_isolated_icons.db"
        self.db = Database()
        
        # Override connection to use temporary isolated test DB
        self.orig_get_conn = self.db.get_connection
        def _get_test_conn():
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            return conn
        self.db.get_connection = _get_test_conn

        conn = self.db.get_connection()
        cur = conn.cursor()
        
        # Create minimal required tables
        cur.execute("""
            CREATE TABLE IF NOT EXISTS resellers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                telegram_id INTEGER,
                discount_percent REAL DEFAULT 20,
                status TEXT DEFAULT 'active'
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS reseller_plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reseller_id INTEGER NOT NULL,
                plan_id TEXT NOT NULL,
                custom_name TEXT,
                custom_price INTEGER,
                custom_data_limit REAL DEFAULT NULL,
                custom_duration INTEGER DEFAULT NULL,
                custom_discount_percent REAL DEFAULT NULL,
                custom_wholesale_price INTEGER DEFAULT NULL,
                custom_icon TEXT DEFAULT NULL,
                reseller_custom_icon TEXT DEFAULT NULL,
                reseller_custom_name TEXT DEFAULT NULL,
                reseller_custom_price INTEGER DEFAULT NULL,
                reseller_is_active INTEGER DEFAULT NULL,
                is_reseller_modified INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                created_at TEXT,
                updated_at TEXT,
                UNIQUE(reseller_id, plan_id)
            )
        """)
        
        # Seed test resellers
        cur.execute("INSERT INTO resellers (id, username, name) VALUES (1, 'reseller_one', 'نماینده یک')")
        cur.execute("INSERT INTO resellers (id, username, name) VALUES (2, 'reseller_two', 'نماینده دو')")
        conn.commit()
        conn.close()

        try:
            from cache_manager import cache
            cache.delete("plans:reseller:1")
            cache.delete("plans:reseller:2")
        except Exception:
            pass

        # Dummy master plans for test
        self.mock_master_plans = {
            "p_vip": {
                "id": "p_vip",
                "plan_id": "p_vip",
                "name": "بسته ویژه طلایی",
                "price": 500000,
                "data_limit": 50,
                "duration": 30,
                "plan_icon": "fas fa-shield-halved",  # Master icon is shield
                "is_active": True,
                "show_in_reseller_bot": True,
                "show_in_reseller_panel": True,
            },
            "p_basic": {
                "id": "p_basic",
                "plan_id": "p_basic",
                "name": "بسته پایه اقتصادی",
                "price": 100000,
                "data_limit": 10,
                "duration": 30,
                "plan_icon": "fas fa-cube",
                "is_active": True,
                "show_in_reseller_bot": True,
                "show_in_reseller_panel": True,
            }
        }

    def tearDown(self):
        try:
            from cache_manager import cache
            cache.delete("plans:reseller:1")
            cache.delete("plans:reseller:2")
        except Exception:
            pass
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch("admin_manager.load_plans")
    def test_reseller_custom_icon_isolated(self, mock_load):
        mock_load.return_value = self.mock_master_plans

        # 1. Before change: Both resellers should get master plan icon "fas fa-shield-halved"
        r1_plans = self.db.get_reseller_plans(1)
        r2_plans = self.db.get_reseller_plans(2)
        
        p1 = next(p for p in r1_plans if p["plan_id"] == "p_vip")
        p2 = next(p for p in r2_plans if p["plan_id"] == "p_vip")
        self.assertEqual(p1["plan_icon"], "fas fa-shield-halved")
        self.assertEqual(p2["plan_icon"], "fas fa-shield-halved")

        # 2. Reseller 1 sets a custom icon to "fas fa-crown"
        res = self.db.update_reseller_plan_override(
            reseller_id=1,
            plan_id="p_vip",
            custom_name="بسته پادشاهی من",
            custom_price=600000,
            is_reseller=True,
            preserve_specs=True,
            custom_icon="fas fa-crown"
        )
        self.assertTrue(res.get("success"))

        # 3. Reseller 1 must now see the custom icon "fas fa-crown"
        r1_plans_after = self.db.get_reseller_plans(1)
        p1_after = next(p for p in r1_plans_after if p["plan_id"] == "p_vip")
        self.assertEqual(p1_after["plan_icon"], "fas fa-crown")
        self.assertEqual(p1_after["reseller_custom_icon"], "fas fa-crown")
        self.assertEqual(p1_after["master_plan_icon"], "fas fa-shield-halved")
        self.assertTrue(p1_after["is_reseller_modified"])

        # 4. CRITICAL ISOLATION CHECK:
        # Master plans (Admin panel) must remain 100% untouched!
        self.assertEqual(self.mock_master_plans["p_vip"]["plan_icon"], "fas fa-shield-halved")

        # 5. Other resellers (Reseller 2) must still see the master icon "fas fa-shield-halved"!
        r2_plans_after = self.db.get_reseller_plans(2)
        p2_after = next(p for p in r2_plans_after if p["plan_id"] == "p_vip")
        self.assertEqual(p2_after["plan_icon"], "fas fa-shield-halved")
        self.assertIsNone(p2_after.get("reseller_custom_icon"))

    @patch("admin_manager.load_plans")
    def test_get_plan_icon_resolution_priority(self, mock_load):
        mock_load.return_value = self.mock_master_plans

        # Setting custom icon for reseller 1
        self.db.update_reseller_plan_override(
            reseller_id=1,
            plan_id="p_vip",
            custom_name="بسته رویال",
            custom_price=700000,
            is_reseller=True,
            preserve_specs=True,
            custom_icon="fas fa-trophy"
        )

        r1_plans = self.db.get_reseller_plans(1)
        r2_plans = self.db.get_reseller_plans(2)
        p1 = next(p for p in r1_plans if p["plan_id"] == "p_vip")
        p2 = next(p for p in r2_plans if p["plan_id"] == "p_vip")

        # In Reseller 1's context (bot, portal, panel):
        icon_info_1 = get_plan_icon(p1, "p_vip")
        self.assertEqual(icon_info_1["icon"], "fas fa-trophy")
        self.assertEqual(icon_info_1["emoji"], "🏆")
        self.assertEqual(get_plan_telegram_emoji(p1, "p_vip"), "🏆")

        # In Reseller 2's context:
        icon_info_2 = get_plan_icon(p2, "p_vip")
        self.assertEqual(icon_info_2["icon"], "fas fa-shield-halved")
        self.assertEqual(icon_info_2["emoji"], "🛡️")
        self.assertEqual(get_plan_telegram_emoji(p2, "p_vip"), "🛡️")

        # In Admin panel context (reading master plan directly):
        icon_info_admin = get_plan_icon(self.mock_master_plans["p_vip"], "p_vip")
        self.assertEqual(icon_info_admin["icon"], "fas fa-shield-halved")

    @patch("admin_manager.load_plans")
    def test_reset_override_restores_master_icon(self, mock_load):
        mock_load.return_value = self.mock_master_plans

        # Reseller 1 sets custom icon
        self.db.update_reseller_plan_override(
            reseller_id=1,
            plan_id="p_vip",
            is_reseller=True,
            preserve_specs=True,
            custom_icon="fas fa-star"
        )
        p1 = next(p for p in self.db.get_reseller_plans(1) if p["plan_id"] == "p_vip")
        self.assertEqual(p1["plan_icon"], "fas fa-star")

        # Now Reseller 1 resets
        res = self.db.reset_reseller_plan_override(reseller_id=1, plan_id="p_vip", by_reseller=True)
        self.assertTrue(res.get("success"))

        p1_reset = next(p for p in self.db.get_reseller_plans(1) if p["plan_id"] == "p_vip")
        self.assertEqual(p1_reset["plan_icon"], "fas fa-shield-halved")
        self.assertIsNone(p1_reset.get("reseller_custom_icon"))

    def test_new_emoji_mappings(self):
        # Verify newly added emojis in ICON_TO_TELEGRAM_EMOJI
        self.assertEqual(ICON_TO_TELEGRAM_EMOJI.get("coins"), "🪙")
        self.assertEqual(ICON_TO_TELEGRAM_EMOJI.get("sack-dollar"), "💰")
        self.assertEqual(ICON_TO_TELEGRAM_EMOJI.get("scroll"), "📜")
        self.assertEqual(ICON_TO_TELEGRAM_EMOJI.get("feather"), "🪽")
        self.assertEqual(ICON_TO_TELEGRAM_EMOJI.get("sun"), "☀️")
        self.assertEqual(ICON_TO_TELEGRAM_EMOJI.get("crown"), "👑")
        self.assertEqual(ICON_TO_TELEGRAM_EMOJI.get("trophy"), "🏆")
        self.assertEqual(ICON_TO_TELEGRAM_EMOJI.get("star"), "⭐")


if __name__ == "__main__":
    unittest.main()
