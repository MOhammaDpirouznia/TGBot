#!/usr/bin/env python3
"""
Cache Manager - موتور مدیریت کش سریع درون‌حافظه‌ای با انقضا (TTL) و پاکسازی هوشمند
جهت ارتقای چشمگیر سرعت پاسخ‌دهی ربات‌ها و کاهش کوئری‌های سنگین دیتابیس
"""

import time
import threading
import logging
from functools import wraps
from typing import Any, Optional, Callable, Dict, List

logger = logging.getLogger(__name__)


class CacheItem:
    __slots__ = ('value', 'expires_at')

    def __init__(self, value: Any, ttl: Optional[float] = None):
        self.value = value
        self.expires_at = (time.time() + ttl) if ttl is not None else None

    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at


class CacheManager:
    """مدیریت کش درون‌حافظه‌ای نخ‌امن با پشتیبانی از TTL و ابطال هوشمند کلیدها"""

    def __init__(self):
        self._cache: Dict[str, CacheItem] = {}
        self._lock = threading.RLock()

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            item = self._cache.get(key)
            if item is None:
                return default
            if item.is_expired():
                del self._cache[key]
                return default
            return item.value

    def set(self, key: str, value: Any, ttl: Optional[float] = 300):
        """ذخیره مقدار در کش با زمان انقضا (پیش‌فرض ۵ دقیقه)"""
        with self._lock:
            self._cache[key] = CacheItem(value, ttl)

    def delete(self, key: str) -> bool:
        """حذف یک کلید از کش"""
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False

    def delete_prefix(self, prefix: str) -> int:
        """حذف تمام کلیدهایی که با پیشوند خاص شروع می‌شوند (مثلاً 'setting:')"""
        with self._lock:
            keys_to_del = [k for k in self._cache if k.startswith(prefix)]
            for k in keys_to_del:
                del self._cache[k]
            return len(keys_to_del)

    def clear(self):
        """پاکسازی کامل کش"""
        with self._lock:
            self._cache.clear()

    def get_or_set(self, key: str, default_factory: Callable[[], Any], ttl: Optional[float] = 300) -> Any:
        """دریافت مقدار و در صورت عدم وجود، محاسبه و کش کردن آن"""
        with self._lock:
            item = self._cache.get(key)
            if item is not None and not item.is_expired():
                return item.value

            val = default_factory()
            self._cache[key] = CacheItem(val, ttl)
            return val

    def invalidate_settings(self, key: Optional[str] = None):
        """ابطال کش تنظیمات (یک کلید خاص یا کلیه تنظیمات)"""
        if key:
            self.delete(f"setting:{key}")
        else:
            self.delete_prefix("setting:")
            self.delete("all_settings")

    def invalidate_plans(self):
        """ابطال کش پلن‌های اشتراک"""
        self.delete_prefix("plans:")
        self.delete("plans_all")
        self.delete("setting:plans_config")

    def invalidate_reseller_admins(self):
        """ابطال کش اعضای تیم و مدیران نمایندگان"""
        self.delete_prefix("reseller_admin:")
        self.delete("reseller_admins_all")
        self.delete_prefix("reseller_by_tg:")


# نمونه یکتا (Singleton) سراسری
cache = CacheManager()


def cached(ttl: float = 300, prefix: str = ""):
    """دکوراتور ذخیره‌سازی نتایج توابع در کش"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            arg_str = ":".join(str(a) for a in args)
            kwarg_str = ":".join(f"{k}={v}" for k, v in sorted(kwargs.items()))
            key = f"{prefix or func.__name__}:{arg_str}:{kwarg_str}"

            cached_val = cache.get(key)
            if cached_val is not None:
                return cached_val

            result = func(*args, **kwargs)
            cache.set(key, result, ttl=ttl)
            return result
        return wrapper
    return decorator
