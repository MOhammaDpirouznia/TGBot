#!/usr/bin/env python3
"""
Renewal Guard Service - سرویس محافظت و جلوگیری از تمدید همزمان و تکراری
فراهم‌آورنده قفل همزمانی (Thread-Safe Lock)، بازه امنیتی تاخیر (Cooldown)،
توکن‌های یکبار مصرف ضد رفرش صفحه (Idempotency Token) و محافظت دیتابیس
"""

import time
import threading
import uuid
import logging
from datetime import datetime
from typing import Tuple, Optional, Dict
from utils import get_now_naive

logger = logging.getLogger("renewal_guard")


class LockResult(tuple):
    """
    نتیجه تلاش برای قفل همزمانی.
    هم به عنوان تاپل (success, message) قابل آنپک است و هم مستقیماً در شرط‌های if bool(result) کار می‌کند.
    """
    def __new__(cls, success: bool, message: str = ""):
        return super().__new__(cls, (success, message))

    @property
    def success(self) -> bool:
        return bool(self[0])

    @property
    def message(self) -> str:
        return str(self[1])

    def __bool__(self) -> bool:
        return bool(self[0])

    def __eq__(self, other):
        if isinstance(other, bool):
            return self.success == other
        return super().__eq__(other)

    def __hash__(self):
        return super().__hash__()


class RenewalGuard:
    """کلاس مدیریت و نظارت بر تمدید اشتراک‌ها جهت جلوگیری از تمدید تکراری"""

    _mutex = threading.Lock()
    _in_flight_subs: Dict[int, float] = {}       # sub_id -> timestamp
    _last_renewed_cache: Dict[int, float] = {}   # sub_id -> timestamp (زمان آخرین تمدید موفق)
    _issued_tokens: Dict[str, float] = {}        # token -> timestamp
    _consumed_tokens: Dict[str, float] = {}      # token -> timestamp

    DEFAULT_COOLDOWN_SECONDS = 30
    LOCK_TIMEOUT_SECONDS = 45
    TOKEN_EXPIRY_SECONDS = 1800  # 30 minutes

    @classmethod
    def clear_all(cls):
        """پاکسازی تمام داده‌ها و قفل‌ها (جهت تست و ریست)"""
        with cls._mutex:
            cls._in_flight_subs.clear()
            cls._last_renewed_cache.clear()
            cls._issued_tokens.clear()
            cls._consumed_tokens.clear()

    @classmethod
    def _clean_expired(cls, now: float):
        """پاک‌سازی رکوردهای منقضی شده در حافظه"""
        # پاک‌سازی قفل‌های گیر افتاده یا طولانی
        stale_locks = [s for s, t in cls._in_flight_subs.items() if now - t > cls.LOCK_TIMEOUT_SECONDS]
        for s in stale_locks:
            cls._in_flight_subs.pop(s, None)

        # پاک‌سازی کش تمدیدهای قدیمی‌تر از ۵ دقیقه
        stale_cache = [s for s, t in cls._last_renewed_cache.items() if now - t > 300]
        for s in stale_cache:
            cls._last_renewed_cache.pop(s, None)

        # پاک‌سازی توکن‌های قدیمی
        stale_issued = [tok for tok, t in cls._issued_tokens.items() if now - t > cls.TOKEN_EXPIRY_SECONDS]
        for tok in stale_issued:
            cls._issued_tokens.pop(tok, None)

        stale_consumed = [tok for tok, t in cls._consumed_tokens.items() if now - t > cls.TOKEN_EXPIRY_SECONDS]
        for tok in stale_consumed:
            cls._consumed_tokens.pop(tok, None)

    @classmethod
    def acquire_lock(cls, sub_id: int, timeout_seconds: int = LOCK_TIMEOUT_SECONDS) -> LockResult:
        """
        تلاش برای دریافت قفل همزمانی تمدید برای یک اشتراک خاص
        در صورت موفقیت LockResult(True, "OK") و در صورت قفل بودن LockResult(False, پیام خطا)
        """
        with cls._mutex:
            now = time.time()
            cls._clean_expired(now)

            if sub_id in cls._in_flight_subs:
                elapsed = int(now - cls._in_flight_subs[sub_id])
                logger.warning(f"Renewal lock collision for sub_id={sub_id} (in-flight for {elapsed}s)")
                return LockResult(False, f"یک عملیات تمدید برای این اشتراک هم‌اکنون در حال پردازش است ({elapsed} ثانیه پیش آغاز شده). لطفاً چند لحظه شکیبا باشید.")

            cls._in_flight_subs[sub_id] = now
            return LockResult(True, "OK")

    @classmethod
    def release_lock(cls, sub_id: int):
        """آزادسازی قفل همزمانی پس از اتمام پردازش (موفق یا با خطا)"""
        with cls._mutex:
            cls._in_flight_subs.pop(sub_id, None)

    @classmethod
    def parse_iso_datetime(cls, dt_str: Optional[str]) -> Optional[datetime]:
        """تبدیل رشته تاریخ به آبجکت datetime ساده"""
        if not dt_str:
            return None
        try:
            clean_str = str(dt_str).replace("Z", "").strip()
            if "T" in clean_str:
                return datetime.fromisoformat(clean_str)
            return datetime.strptime(clean_str[:19], "%Y-%m-%d %H:%M:%S")
        except Exception:
            try:
                return datetime.fromisoformat(str(dt_str)[:19])
            except Exception:
                return None

    @classmethod
    def check_cooldown(cls, sub_id: int, last_renewed_at_str: Optional[str],
                       cooldown_seconds: int = DEFAULT_COOLDOWN_SECONDS) -> Tuple[bool, int, str]:
        """
        بررسی بازه استراحت (Cooldown Window)
        خروجی: (is_in_cooldown, remaining_seconds, message)
        """
        now_ts = time.time()

        # ۱. بررسی سریع کش درون‌حافظه‌ای
        with cls._mutex:
            mem_ts = cls._last_renewed_cache.get(sub_id)
            if mem_ts:
                diff_mem = now_ts - mem_ts
                if 0 <= diff_mem < cooldown_seconds:
                    rem = int(cooldown_seconds - diff_mem)
                    return True, rem, f"این اشتراک {int(diff_mem)} ثانیه پیش تمدید شده است. جهت حفظ امنیت مالی و جلوگیری از تمدید تکراری، لطفاً {rem} ثانیه دیگر شکیبا باشید."

        # ۲. بررسی فیلد دیتابیس last_renewed_at
        if last_renewed_at_str:
            dt = cls.parse_iso_datetime(last_renewed_at_str)
            if dt:
                now_tehran = get_now_naive()
                if dt.tzinfo is not None:
                    dt = dt.replace(tzinfo=None)
                diff_seconds = (now_tehran - dt).total_seconds()

                if 0 <= diff_seconds < cooldown_seconds:
                    rem = int(cooldown_seconds - diff_seconds)
                    return True, rem, f"این اشتراک {int(diff_seconds)} ثانیه پیش با موفقیت تمدید شده است. جهت جلوگیری از تمدید ناخواسته، لطفاً {rem} ثانیه دیگر شکیبا باشید."

        return False, 0, ""

    @classmethod
    def record_successful_renewal(cls, sub_id: int):
        """ثبت زمان آخرین تمدید موفق در کش سریع درون‌حافظه‌ای"""
        with cls._mutex:
            cls._last_renewed_cache[sub_id] = time.time()
            cls._in_flight_subs.pop(sub_id, None)

    @classmethod
    def generate_token(cls) -> str:
        """تولید توکن یکبار مصرف تصادفی جهت قرارگیری در فرم‌های وب"""
        tok = uuid.uuid4().hex
        with cls._mutex:
            cls._issued_tokens[tok] = time.time()
        return tok

    @classmethod
    def validate_and_consume_token(cls, token: Optional[str]) -> Tuple[bool, str]:
        """
        بررسی و مصرف توکن یکبار مصرف
        در صورتی که توکن قبلاً مصرف شده باشد، False برمی‌گرداند تا رفرش صفحه جلوی تمدید مجدد را بگیرد.
        """
        if not token or not str(token).strip():
            return True, "NO_TOKEN"

        tok = str(token).strip()
        with cls._mutex:
            now = time.time()
            cls._clean_expired(now)

            if tok in cls._consumed_tokens:
                logger.warning(f"Re-submission blocked for consumed token: {tok}")
                return False, "این فرم قبلاً ارسال و پردازش شده است. جهت جلوگیری از تمدید مجدد با رفرش صفحه، درخواست متوقف شد."

            cls._consumed_tokens[tok] = now
            cls._issued_tokens.pop(tok, None)
            return True, "OK"
