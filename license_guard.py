#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
🛡️ Nexus License Guard (Client Edition) - TGBot Protection Core
=============================================================================
ماژول امنیتی و اعتبارسنجی لایسنس سمت کلاینت:
- تولید اثر انگشت پایدار سخت‌افزاری (Machine ID) برای لینوکس و ویندوز
- پشتیبانی از حالت مستر (Master Mode) جهت کارکرد مادام‌العمر سرور شخصی بدون وابستگی
- اعتبارسنجی آنلاین و ارسال ضربان سلامت (Heartbeat) به سرور لایسنس
- تاب‌آوری شبکه در شرایط فیلترینگ و قطعی موقت (Grace Period 72h)
- مدیریت ماژولار دسترسی‌ها (Feature Flags)
- مکانیزم واکنش به فرمان‌های تعلیق و تخریب از راه دور (Kill-Switch)
=============================================================================
"""

import os
import sys
import time
import json
import uuid
import hmac
import hashlib
import platform
import threading
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


# کتابخانه درخواست شبکه (استفاده از httpx در صورت وجود، یا urllib به عنوان فالبک)
try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False
    import urllib.request
    import urllib.error

# ریشه‌ها و مسیرهای پایه
BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"
STATE_FILE = BASE_DIR / ".license_cache.dat"

# بارگذاری خودکار فایل .env
try:
    from dotenv import load_dotenv
    if ENV_FILE.exists():
        load_dotenv(ENV_FILE)
except ImportError:
    pass

# تنظیمات پیش‌فرض
PRODUCT_CODE = "TGBOT"
CLIENT_VERSION = "v3.28"
DEFAULT_SERVER_URL = "http://127.0.0.1:8890"  # آدرس سرور لایسنس شما
GRACE_PERIOD_SECONDS = 72 * 3600  # ۷۲ ساعت مهلت در صورت قطعی اینترنت
SHARED_SALT = b"NexusLicenseGuard_2026_SecureSalt"



class LicenseGuard:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(LicenseGuard, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        # بارگذاری تنظیمات از محیط
        self.license_key = os.getenv("LICENSE_KEY", "").strip()
        self.server_url = os.getenv("LICENSE_SERVER_URL", DEFAULT_SERVER_URL).rstrip("/")
        self.master_key = os.getenv("LICENSE_MASTER_OVERRIDE", "").strip().upper()

        # بازیابی از دیتابیس در صورت عدم تعریف در متغیرهای محیطی
        if not self.license_key:
            try:
                from database import db
                db_key = db.get_setting("license_key")
                if db_key and str(db_key).strip():
                    self.license_key = str(db_key).strip()
            except Exception:
                pass

        # اثر انگشت اختصاصی سخت‌افزار
        self.machine_id = self._generate_machine_id()

        # وضعیت لایسنس
        self.is_valid = False
        self.status = "UNINITIALIZED"  # ACTIVE, EXPIRED, SUSPENDED, GRACE, MASTER
        self.customer_name = ""
        self.expires_at = ""
        self.enabled_features = []
        self.last_check_time = 0
        self.watchdog_thread = None

        # بررسی اولیه حالت مستر
        if self._is_master_mode():
            self._activate_master_mode()

    # ─────────────────────────────────────────────────────────────────────────
    # ۱. تولید اثر انگشت یکتای سخت‌افزاری (Hardware Fingerprinting)
    # ─────────────────────────────────────────────────────────────────────────
    def _generate_machine_id(self) -> str:
        """تولید شناسه یونیک و پایدار بر اساس مشخصات سخت‌افزاری سرور"""
        hw_parts = []
        system = platform.system().lower()

        # ۱. مک‌آدرس کارت شبکه اصلی
        try:
            raw_mac = hex(uuid.getnode())[2:].zfill(12)
            hw_parts.append(f"mac:{raw_mac}")
        except Exception:
            hw_parts.append("mac:unknown")

        # ۲. شناسه سیستم‌عامل و پردازنده
        hw_parts.append(f"arch:{platform.machine()}")
        hw_parts.append(f"proc:{platform.processor()}")

        # ۳. شناسه اختصاصی مادربورد / سرور مجازی
        if system == "linux":
            for path in [
                "/sys/class/dmi/id/product_uuid",
                "/etc/machine-id",
                "/var/lib/dbus/machine-id"
            ]:
                p = Path(path)
                if p.exists() and p.is_file():
                    try:
                        content = p.read_text(encoding="utf-8").strip()
                        if content:
                            hw_parts.append(f"uuid:{content}")
                            break
                    except Exception:
                        pass
        elif system == "windows":
            try:
                # خواندن MachineGuid از رجیستری ویندوز
                import winreg
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography") as key:
                    guid, _ = winreg.QueryValueEx(key, "MachineGuid")
                    if guid:
                        hw_parts.append(f"guid:{guid}")
            except Exception:
                pass

        # ۴. ترکیب و هش کردن پایدار
        raw_combined = "|".join(hw_parts).encode("utf-8")
        h = hashlib.sha256(raw_combined + SHARED_SALT).hexdigest().upper()

        # ساخت فرمت خروجی زیبا: TGBOT-XXXX-YYYY-ZZZZ-WWWW
        return f"{PRODUCT_CODE}-{h[0:4]}-{h[4:8]}-{h[8:12]}-{h[12:16]}"

    # ─────────────────────────────────────────────────────────────────────────
    # ۲. مدیریت حالت مستر (Master Mode - بدون وابستگی به سرور برای خودتان)
    # ─────────────────────────────────────────────────────────────────────────
    def _is_master_mode(self) -> bool:
        """بررسی آیا این سرور متعلق به مدیر اصلی است یا خیر"""
        # ۱. اگر متغیر مستر در محیط تنظیم شده باشد یا لایسنس ویژه مستر باشد
        if self.master_key in ["TRUE", "YES", "1", "ENABLE", "ENABLED"]:
            return True
        if self.license_key and "MASTER_UNLIMITED" in self.license_key.upper():
            return True

        # ۲. سرور کلود شخصی ریلوی، داکر یا متغیر توسعه‌دهنده
        if os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("RAILWAY_PROJECT_ID") or os.getenv("DEVELOPER_MODE") == "1":
            return True

        # ۳. در صورتی که فایل پایتون به صورت سورس کد آزاد (غیر باینری کامپایل‌شده Nuitka) اجرا می‌شود
        # کامپایل به باینری Native با build_nuitka.py برای توزیع تجاری به مشتریان طراحی شده است
        is_compiled = hasattr(sys, "__compiled__") or getattr(sys, "frozen", False) or not __file__.endswith(".py")
        strict_mode = os.getenv("LICENSE_GUARD_STRICT", "0").lower() in ("1", "true")
        if not is_compiled and not strict_mode:
            return True

        return False

    def _activate_master_mode(self):
        """فعال‌سازی حالت مستر (دسترسی نامحدود، بدون چک شبکه، ضد تخریب)"""
        self.is_valid = True
        self.status = "MASTER"
        self.customer_name = "سرور شخصی مدیریت (صاحب اثر)"
        self.expires_at = "مادام‌العمر (بدون انقضا)"
        self.enabled_features = ["all", "reseller_panel", "ai_bot", "multi_bot", "auto_backup"]
        print(f"[LicenseGuard-Master] سرور با لایسنس مستر فعال است ({self.machine_id}).")


    # ─────────────────────────────────────────────────────────────────────────
    # ۳. استعلام و اعتبارسنجی آنلاین لایسنس (Online Verification)
    # ─────────────────────────────────────────────────────────────────────────
    def verify(self, force_online: bool = False) -> Dict[str, Any]:
        """
        اعتبارسنجی وضعیت لایسنس:
        - در حالت مستر: فوراً تایید می‌شود.
        - در حالت عادی: ارسال اطلاعات سرور به لایسنس‌سرور و بررسی اعتبار.
        """
        if self._is_master_mode():
            self._activate_master_mode()
            return self._build_status_dict(True, "حالت مستر فعال است.")

        if not self.license_key:
            self.is_valid = False
            self.status = "MISSING_KEY"
            return self._build_status_dict(False, "کلید لایسنس در فایل .env تعریف نشده است.")

        # ارسال رکوئست آنلاین به سرور لایسنس
        payload = {
            "product_code": PRODUCT_CODE,
            "license_key": self.license_key,
            "machine_id": self.machine_id,
            "client_version": CLIENT_VERSION,
            "timestamp": int(time.time()),
            "system_info": {
                "os": platform.system(),
                "node": platform.node(),
                "python": platform.python_version()
            }
        }

        try:
            resp_data = self._send_request(f"{self.server_url}/api/v1/verify", payload)
            return self._process_server_response(resp_data)
        except Exception as e:
            # در صورت عدم دسترسی به سرور لایسنس (قطعی اینترنت یا فیلترینگ)
            return self._handle_network_failure(str(e))

    def _send_request(self, url: str, data: dict) -> dict:
        """ارسال درخواست HTTP امن با تایم‌اوت مشخص"""
        json_bytes = json.dumps(data).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "User-Agent": f"NexusGuardClient/{CLIENT_VERSION}"
        }

        if HAS_HTTPX:
            with httpx.Client(timeout=10.0) as client:
                res = client.post(url, json=data, headers=headers)
                if res.status_code != 200:
                    raise Exception(f"Server returned HTTP {res.status_code}")
                return res.json()
        else:
            req = urllib.request.Request(url, data=json_bytes, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=10.0) as response:
                if response.status != 200:
                    raise Exception(f"Server returned HTTP {response.status}")
                return json.loads(response.read().decode("utf-8"))

    def _process_server_response(self, data: dict) -> Dict[str, Any]:
        """پردازش پاسخ دریافتی از لایسنس‌سرور"""
        status = data.get("status", "INVALID").upper()
        command = data.get("command", "").upper()

        # ۱. بررسی فرمان اضطراری تخریب (Kill-Switch)
        if command in ["KILL", "SELF_DESTRUCT", "WIPE"]:
            self._execute_kill_switch(data.get("command_reason", "دستور اضطراری لایسنس‌سرور"))
            sys.exit(1)

        # ۲. بررسی وضعیت لایسنس
        if status == "ACTIVE":
            self.is_valid = True
            self.status = "ACTIVE"
            self.customer_name = data.get("customer_name", "مشتری رسمی")
            self.expires_at = data.get("expires_at", "")
            self.enabled_features = data.get("features", ["all"])
            self.last_check_time = time.time()
            self._save_cache(data)
            return self._build_status_dict(True, "لایسنس با موفقیت فعال و تایید شد.")

        elif status in ["SUSPENDED", "EXPIRED", "REVOKED"]:
            self.is_valid = False
            self.status = status
            self._clear_cache()
            return self._build_status_dict(False, f"لایسنس در وضعیت {status} قرار دارد.")

        else:
            self.is_valid = False
            self.status = "INVALID"
            return self._build_status_dict(False, data.get("message", "لایسنس نامعتبر است."))

    # ─────────────────────────────────────────────────────────────────────────
    # ۴. مدیریت قطعی اینترنت و مهلت تنفس (Grace Period & Offline Resilience)
    # ─────────────────────────────────────────────────────────────────────────
    def _handle_network_failure(self, error_msg: str) -> Dict[str, Any]:
        """مدیریت زمانی که سرور لایسنس موقتاً از دسترس خارج است"""
        cached = self._load_cache()
        if cached:
            cached_time = cached.get("cached_at", 0)
            elapsed = time.time() - cached_time

            if elapsed < GRACE_PERIOD_SECONDS:
                remaining_hours = int((GRACE_PERIOD_SECONDS - elapsed) / 3600)
                self.is_valid = True
                self.status = "GRACE_PERIOD"
                self.customer_name = cached.get("customer_name", "")
                self.expires_at = cached.get("expires_at", "")
                self.enabled_features = cached.get("features", ["all"])
                return self._build_status_dict(
                    True,
                    f"ارتباط با سرور برقرار نشد؛ استفاده از کش موقت ({remaining_hours} ساعت مهلت باقی‌مانده)."
                )

        self.is_valid = False
        self.status = "NETWORK_ERROR"
        return self._build_status_dict(False, f"عدم برقراری ارتباط با سرور لایسنس: {error_msg}")

    # ─────────────────────────────────────────────────────────────────────────
    # ۵. کش امن و محلی آخرین وضعیت تایید شده
    # ─────────────────────────────────────────────────────────────────────────
    def _save_cache(self, data: dict):
        try:
            cache_payload = {
                "machine_id": self.machine_id,
                "license_key": self.license_key,
                "cached_at": time.time(),
                "customer_name": data.get("customer_name"),
                "expires_at": data.get("expires_at"),
                "features": data.get("features", [])
            }
            raw = json.dumps(cache_payload).encode("utf-8")
            # امضا با هش امنیتی محلی
            sig = hmac.new(SHARED_SALT, raw, hashlib.sha256).hexdigest()
            final_obj = {"sig": sig, "payload": raw.hex()}
            STATE_FILE.write_text(json.dumps(final_obj), encoding="utf-8")
        except Exception:
            pass

    def _load_cache(self) -> Optional[dict]:
        try:
            if not STATE_FILE.exists():
                return None
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            sig = data.get("sig")
            raw = bytes.fromhex(data.get("payload", ""))

            # اعتبارسنجی امضا برای جلوگیری از دستکاری دستی فایل کش
            expected_sig = hmac.new(SHARED_SALT, raw, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(sig, expected_sig):
                return None

            payload = json.loads(raw.decode("utf-8"))
            if payload.get("machine_id") != self.machine_id or payload.get("license_key") != self.license_key:
                return None

            return payload
        except Exception:
            return None

    def _clear_cache(self):
        try:
            if STATE_FILE.exists():
                STATE_FILE.unlink()
        except Exception:
            pass

    # ─────────────────────────────────────────────────────────────────────────
    # ۶. مکانیزم تخریب خودکار اضطراری (Self-Destruct / Kill-Switch)
    # ─────────────────────────────────────────────────────────────────────────
    def _execute_kill_switch(self, reason: str):
        """اجرای فرمان تخریب در صورت دستور صریح لایسنس‌سرور"""
        if self._is_master_mode():
            print("⚠️ [LicenseGuard] فرمان تخریب بر روی سرور مستر مسدود شد.")
            return

        print(f"🚨 [LicenseGuard] فرمان تخریب اضطراری دریافت شد: {reason}")

        # ۱. تخریب و بازنویسی دیتابیس‌ها
        for db_file in BASE_DIR.glob("*.db"):
            try:
                size = db_file.stat().st_size
                with open(db_file, "wb") as f:
                    f.write(os.urandom(min(size, 1024 * 1024)))  # بازنویسی با دیتای تصادفی
                db_file.unlink()
            except Exception:
                pass

        # ۲. پاک‌سازی فایل تنظیمات .env
        try:
            if ENV_FILE.exists():
                ENV_FILE.unlink()
        except Exception:
            pass

        # ۳. پاک‌سازی کش
        self._clear_cache()
        print("💥 [LicenseGuard] عملیات پاک‌سازی پروژه با موفقیت خاتمه یافت.")

    # ─────────────────────────────────────────────────────────────────────────
    # ۷. متدهای کمکی و بررسی فیچرها (Feature Flags)
    # ─────────────────────────────────────────────────────────────────────────
    def is_feature_active(self, feature_name: str) -> bool:
        """بررسی آیا یک قابلیت خاص در لایسنس خریدار فعال است یا خیر"""
        if self._is_master_mode():
            return True
        if not self.is_valid:
            return False
        if "all" in self.enabled_features:
            return True
        return feature_name.lower() in [f.lower() for f in self.enabled_features]

    def _build_status_dict(self, success: bool, message: str) -> Dict[str, Any]:
        return {
            "valid": success,
            "status": self.status,
            "machine_id": self.machine_id,
            "customer": self.customer_name,
            "expires_at": self.expires_at,
            "features": self.enabled_features,
            "message": message
        }

    # ─────────────────────────────────────────────────────────────────────────
    # ۸. سگ نگهبان پس‌زمینه (Background Watchdog)
    # ─────────────────────────────────────────────────────────────────────────
    def start_watchdog(self, interval_minutes: int = 30):
        """اجرای چکر پس‌زمینه برای اعتبارسنجی دوره‌ای لایسنس بدون افت سرعت ربات"""
        if self._is_master_mode():
            return  # نیازی به چکر در سرور مستر نیست

        def _loop():
            while True:
                time.sleep(interval_minutes * 60)
                res = self.verify()
                if not res["valid"]:
                    print(f"⛔ [LicenseGuard] لایسنس معلق یا منقضی شد: {res['message']}")
                    # خاموشی نرم
                    os._exit(1)

        self.watchdog_thread = threading.Thread(target=_loop, daemon=True)
        self.watchdog_thread.start()


# آبجکت منفرد سراسری
guard = LicenseGuard()

if __name__ == "__main__":
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    print("=" * 65)
    print("🛡️ Nexus License Guard (Client Diagnostics)")
    print("=" * 65)
    print(f"🖥️ شناسه سخت‌افزاری سرور (Machine ID): {guard.machine_id}")
    print(f"🔑 کلید لایسنس فعلی: {guard.license_key or '(تعریف نشده)'}")
    print(f"👑 وضعیت Master Mode: {'فعال' if guard._is_master_mode() else 'غیرفعال'}")
    
    result = guard.verify()
    print("-" * 65)
    print(f"📊 وضعیت اعتبار: {'✅ معتبر' if result['valid'] else '❌ نامعتبر'}")
    print(f"📌 پیام سیستم: {result['message']}")
    print(f"📦 قابلیت‌ها: {', '.join(result['features']) if result['features'] else 'هیچ'}")
    print("=" * 65)
