import unittest
import time
import threading
from datetime import datetime, timedelta
from services.renewal_guard import RenewalGuard

class TestRenewalGuard(unittest.TestCase):
    def setUp(self):
        RenewalGuard.clear_all()

    def tearDown(self):
        RenewalGuard.clear_all()

    def test_token_lifecycle(self):
        # 1. Generate token
        token = RenewalGuard.generate_token()
        self.assertTrue(bool(token))
        self.assertIsInstance(token, str)

        # 2. First consumption should succeed
        valid, msg = RenewalGuard.validate_and_consume_token(token)
        self.assertTrue(valid)
        self.assertEqual(msg, "OK")

        # 3. Second consumption (e.g. browser refresh) MUST fail
        valid2, msg2 = RenewalGuard.validate_and_consume_token(token)
        self.assertFalse(valid2)
        self.assertIn("قبلاً ارسال و پردازش شده", msg2)

    def test_token_missing_or_optional(self):
        # When token is None or empty, it returns True with NO_TOKEN for backward compatibility
        valid, msg = RenewalGuard.validate_and_consume_token(None)
        self.assertTrue(valid)
        self.assertEqual(msg, "NO_TOKEN")

    def test_in_flight_lock_single_thread(self):
        sub_id = 9991
        # Acquire
        self.assertTrue(RenewalGuard.acquire_lock(sub_id))
        # Re-acquire before release should fail
        self.assertFalse(RenewalGuard.acquire_lock(sub_id))
        # Release
        RenewalGuard.release_lock(sub_id)
        # Should be able to acquire again
        self.assertTrue(RenewalGuard.acquire_lock(sub_id))
        RenewalGuard.release_lock(sub_id)

    def test_in_flight_lock_multithreading(self):
        sub_id = 9992
        results = []

        def worker():
            got_lock = RenewalGuard.acquire_lock(sub_id)
            results.append(got_lock)
            if got_lock:
                time.sleep(0.1)
                RenewalGuard.release_lock(sub_id)

        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)

        t1.start()
        time.sleep(0.01)  # ensure t1 runs first
        t2.start()

        t1.join()
        t2.join()

        # Exactly one thread should have acquired the lock
        self.assertEqual(results.count(True), 1)
        self.assertEqual(results.count(False), 1)

    def test_cooldown_detection(self):
        sub_id = 9993
        # Initially not in cooldown
        is_cool, rem, msg = RenewalGuard.check_cooldown(sub_id, None, cooldown_seconds=30)
        self.assertFalse(is_cool)
        self.assertEqual(rem, 0)

        # Record successful renewal
        RenewalGuard.record_successful_renewal(sub_id)

        # Now should be in cooldown
        is_cool2, rem2, msg2 = RenewalGuard.check_cooldown(sub_id, None, cooldown_seconds=30)
        self.assertTrue(is_cool2)
        self.assertGreater(rem2, 0)
        self.assertIn("ثانیه", msg2)

    def test_cooldown_with_db_timestamp(self):
        sub_id = 9994
        now = datetime.now()
        recent_iso = (now - timedelta(seconds=10)).isoformat()
        old_iso = (now - timedelta(seconds=60)).isoformat()

        # Check with recent timestamp (10s ago, cooldown 30s) -> should be blocked
        is_cool, rem, msg = RenewalGuard.check_cooldown(sub_id, recent_iso, cooldown_seconds=30)
        self.assertTrue(is_cool)
        self.assertGreater(rem, 15)

        # Check with old timestamp (60s ago, cooldown 30s) -> should be allowed
        is_cool_old, rem_old, msg_old = RenewalGuard.check_cooldown(sub_id, old_iso, cooldown_seconds=30)
        self.assertFalse(is_cool_old)
        self.assertEqual(rem_old, 0)

if __name__ == '__main__':
    unittest.main()
