# -*- coding: utf-8 -*-
import unittest
import database
import dashboard


class TestBentoWeeklyCharts(unittest.TestCase):
    def setUp(self):
        self.db = database.Database()
        self.app = dashboard.app
        self.client = self.app.test_client()

    def test_build_weekly_sparkline_chart_with_usage(self):
        # ۷ روز گذشته با مقادیر مشخص مصرف
        days_7 = [
            {"day_name": "شنبه", "jalali_date": "28 شهریور", "usage_mb": 512.0, "usage_gb": 0.5, "is_today": False},
            {"day_name": "یک‌شنبه", "jalali_date": "29 شهریور", "usage_mb": 1024.0, "usage_gb": 1.0, "is_today": False},
            {"day_name": "دوشنبه", "jalali_date": "30 شهریور", "usage_mb": 2048.0, "usage_gb": 2.0, "is_today": False},
            {"day_name": "سه‌شنبه", "jalali_date": "31 شهریور", "usage_mb": 3072.0, "usage_gb": 3.0, "is_today": False},
            {"day_name": "چهارشنبه", "jalali_date": "1 مهر", "usage_mb": 4096.0, "usage_gb": 4.0, "is_today": False},
            {"day_name": "پنج‌شنبه", "jalali_date": "2 مهر", "usage_mb": 1536.0, "usage_gb": 1.5, "is_today": False},
            {"day_name": "جمعه", "jalali_date": "3 مهر", "usage_mb": 2560.0, "usage_gb": 2.5, "is_today": True},
        ]
        wc = self.db._build_weekly_sparkline_chart(days_7)
        self.assertTrue(wc["has_usage"])
        self.assertEqual(wc["peak_day_name"], "چهارشنبه")
        self.assertIn("4.0", wc["peak_text"])
        self.assertIn("اوج: 4.0 GB", wc["peak_text_formatted"])

        # بررسی ساختار بنتو ۱ (ارتفاع ۶۰)
        b1 = wc["bento1"]
        self.assertTrue(b1["path"].startswith("M "))
        self.assertIn(" C ", b1["path"])
        self.assertTrue(b1["area"].endswith(" L 200.0,60 L 0.0,60 Z"))
        self.assertEqual(len(b1["points"]), 7)

        # در چیدمان RTL: چهارشنبه (شاخص ۴ در days_7) در rev_days شاخص ۲ است: x = (2/6)*200 = 66.7
        self.assertEqual(b1["peak_x"], 66.7)
        self.assertEqual(b1["peak_y"], 12.0)  # در اوج مصرف y = min_y = 12

        # بررسی ساختار بنتو ۳ (ارتفاع ۷۰)
        b3 = wc["bento3"]
        self.assertTrue(b3["path"].startswith("M "))
        self.assertIn(" C ", b3["path"])
        self.assertTrue(b3["area"].endswith(" L 200.0,70 L 0.0,70 Z"))
        self.assertEqual(b3["peak_x"], 66.7)
        self.assertEqual(b3["peak_y"], 12.0)

    def test_build_weekly_sparkline_chart_zero_usage(self):
        # ۷ روز بدون هیچ‌گونه مصرف
        days_7 = [
            {"day_name": f"روز {i}", "jalali_date": f"{i}", "usage_mb": 0.0, "usage_gb": 0.0, "is_today": (i == 6)}
            for i in range(7)
        ]
        wc = self.db._build_weekly_sparkline_chart(days_7)
        self.assertFalse(wc["has_usage"])
        self.assertEqual(wc["peak_text"], "بدون مصرف")
        self.assertEqual(wc["peak_text_formatted"], "بدون مصرف در هفته اخیر")

        # نباید خط افقی ساده باشد؛ باید انحنا و امواج ملایم بزیه داشته باشد
        b3 = wc["bento3"]
        self.assertIn(" C ", b3["path"])
        # بررسی اینکه مقادیر y ثابت نیستند
        y_values = [p["y"] for p in b3["points"]]
        self.assertTrue(len(set(y_values)) > 1, "Zero usage chart should have gentle undulations to prevent flat horizontal line")

    def test_get_subscription_traffic_analytics_includes_weekly_chart(self):
        res = self.db.get_subscription_traffic_analytics(46)
        self.assertIn("weekly_chart", res)
        wc = res["weekly_chart"]
        self.assertIn("bento1", wc)
        self.assertIn("bento3", wc)
        self.assertIn("peak_text_formatted", wc)
        self.assertEqual(len(wc["bento1"]["points"]), 7)
        self.assertEqual(len(wc["bento3"]["points"]), 7)

    def test_portal_rendering_bento_grid_1_and_3(self):
        # بررسی رندر بدون خطا در طرح بنتو گرید ۱
        self.db.set_setting("portal_layout", "bento_grid_1")
        with self.app.test_request_context("/sub/46"):
            html1 = dashboard._handle_customer_portal_view("46")
            self.assertIn("bento1SparkSvg", html1)
            self.assertIn("bento1SparkLine", html1)
            self.assertIn("bento1SparkArea", html1)
            self.assertIn("bento1PeakDot", html1)
            self.assertIn("bento1PeakLabel", html1)
            self.assertIn("شروع دوره", html1)
            self.assertIn("امروز", html1)

        # بررسی رندر بدون خطا در طرح بنتو گرید ۳
        self.db.set_setting("portal_layout", "bento_grid_3")
        with self.app.test_request_context("/sub/46"):
            html3 = dashboard._handle_customer_portal_view("46")
            self.assertIn("bento3WaveSvg", html3)
            self.assertIn("bento3WaveLine", html3)
            self.assertIn("bento3WaveArea", html3)
            self.assertIn("bento3PeakDot", html3)
            self.assertIn("bento3PeakLabel", html3)
            self.assertIn("شروع دوره", html3)
            self.assertIn("امروز", html3)

    def test_portal_rendering_with_phone_number(self):
        # بررسی رندر بدون خطای NameError در صورت وجود شماره تماس در اشتراک
        conn = self.db.get_connection()
        conn.execute("""
            INSERT OR REPLACE INTO subscriptions (id, hidify_uuid, telegram_id, phone_number, plan_id, status, is_deleted)
            VALUES (99998, 'test_phone_sub_uuid', 0, '09129998877', 'test_plan', 'active', 0)
        """)
        conn.commit()
        conn.close()

        try:
            with self.app.test_request_context("/sub/test_phone_sub_uuid"):
                html = dashboard._handle_customer_portal_view("test_phone_sub_uuid")
                self.assertIsNotNone(html)
        finally:
            conn = self.db.get_connection()
            conn.execute("DELETE FROM subscriptions WHERE id=99998")
            conn.commit()
            conn.close()


if __name__ == "__main__":
    unittest.main()
