#!/usr/bin/env python3
"""
🚀 راه‌انداز یکپارچه ربات تلگرام و پنل مدیریت تحت وب HiddiBot
"""

import sys
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import bot

if __name__ == "__main__":
    print("🚀 در حال اجرای همزمان ربات تلگرام و پنل تحت وب...")
    bot.main()
