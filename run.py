#!/usr/bin/env python3
"""
🚀 راه‌انداز یکپارچه ربات تلگرام و پنل مدیریت تحت وب HiddiBot
"""

import sys
from license_guard import guard

if __name__ == "__main__":
    # بررسی اولیه لایسنس قبل از لود ماژول‌های سنگین
    lic = guard.verify()
    if not lic.get("valid"):
        print("\n" + "=" * 65)
        print("⛔ [LicenseGuard] مجوز اجرای پروژه یافت نشد یا معتبر نیست!")
        print(f"📌 پیام سیستم: {lic.get('message')}")
        print(f"🖥️ شناسه سخت‌افزاری سرور (Machine ID): {guard.machine_id}")
        print("=" * 65 + "\n")
        sys.exit(1)

    print(f"🛡️ [LicenseGuard] وضعیت لایسنس تایید شد ({lic.get('customer', 'معتبر')}).")
    print("🚀 در حال اجرای همزمان ربات تلگرام و پنل تحت وب...")
    import bot
    bot.main()

