#!/usr/bin/env python3
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import utils
from database import db
from notifications import NotificationScheduler


class TestTehranReminders(unittest.TestCase):

    def setUp(self):
        self.orig_settings = db.get_reminder_settings()

    def tearDown(self):
        db.save_reminder_settings(
            hour=self.orig_settings.get('reminder_notification_hour', 12),
            enabled=self.orig_settings.get('reminder_notification_enabled', True),
            quiet_enabled=self.orig_settings.get('reminder_quiet_hours_enabled', True),
            quiet_start=self.orig_settings.get('reminder_quiet_start', 23),
            quiet_end=self.orig_settings.get('reminder_quiet_end', 9)
        )

    def test_01_tehran_timezone_offset(self):
        now_tehran = utils.get_now()
        self.assertIsNotNone(now_tehran.tzinfo)
        offset = now_tehran.utcoffset()
        self.assertEqual(offset, timedelta(hours=3, minutes=30))
        self.assertEqual(now_tehran.hour, utils.get_now_tehran().hour)

    def test_02_parse_to_tehran_dt(self):
        dt_utc = utils.parse_to_tehran_dt('2026-09-20T10:00:00Z')
        self.assertIsNotNone(dt_utc)
        self.assertEqual(dt_utc.utcoffset(), timedelta(hours=3, minutes=30))
        self.assertEqual(dt_utc.hour, 13)
        self.assertEqual(dt_utc.minute, 30)

        dt_tehran = utils.parse_to_tehran_dt('2026-09-20T13:30:00+03:30')
        self.assertEqual(dt_utc, dt_tehran)

        dt_naive = utils.parse_to_tehran_dt('2026-09-20 14:00:00')
        self.assertIsNotNone(dt_naive)
        self.assertEqual(dt_naive.hour, 14)
        self.assertEqual(dt_naive.utcoffset(), timedelta(hours=3, minutes=30))

        self.assertIsNone(utils.parse_to_tehran_dt(''))
        self.assertIsNone(utils.parse_to_tehran_dt(None))

    def test_03_is_in_quiet_hours(self):
        with patch.object(utils, 'get_now') as mock_now:
            mock_now.return_value = datetime(2026, 9, 20, 2, 0, 0, tzinfo=utils.TEHRAN_TZ)
            self.assertTrue(utils.is_in_quiet_hours(23, 9))

            mock_now.return_value = datetime(2026, 9, 20, 23, 30, 0, tzinfo=utils.TEHRAN_TZ)
            self.assertTrue(utils.is_in_quiet_hours(23, 9))

            mock_now.return_value = datetime(2026, 9, 20, 12, 0, 0, tzinfo=utils.TEHRAN_TZ)
            self.assertFalse(utils.is_in_quiet_hours(23, 9))

            mock_now.return_value = datetime(2026, 9, 20, 10, 0, 0, tzinfo=utils.TEHRAN_TZ)
            self.assertFalse(utils.is_in_quiet_hours(23, 9))

    def test_04_database_reminder_settings_persistence(self):
        ok = db.save_reminder_settings(
            hour=14,
            enabled=True,
            quiet_enabled=False,
            quiet_start=22,
            quiet_end=8
        )
        self.assertTrue(ok)
        s = db.get_reminder_settings()
        self.assertEqual(s['reminder_notification_hour'], 14)
        self.assertTrue(s['reminder_notification_enabled'])
        self.assertFalse(s['reminder_quiet_hours_enabled'])
        self.assertEqual(s['reminder_quiet_start'], 22)
        self.assertEqual(s['reminder_quiet_end'], 8)

    def test_05_admin_reminder_date_comparison(self):
        now_tehran = utils.get_now()
        past_date = (now_tehran - timedelta(hours=2)).isoformat()
        future_date = (now_tehran + timedelta(hours=2)).isoformat()

        dt_past = utils.parse_to_tehran_dt(past_date)
        dt_future = utils.parse_to_tehran_dt(future_date)

        self.assertTrue(dt_past <= now_tehran)
        self.assertFalse(dt_future <= now_tehran)

    def test_06_no_forbidden_word_in_notifications(self):
        with open('notifications.py', 'r', encoding='utf-8') as f:
            content = f.read()

        import re
        matches = re.findall(r'[؀-ۿ\s]پلن[؀-ۿ\s]', content)
        self.assertEqual(len(matches), 0, f'Forbidden word found: {matches}')


if __name__ == '__main__':
    unittest.main()
