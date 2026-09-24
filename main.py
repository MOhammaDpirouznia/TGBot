#!/usr/bin/env python3
"""
🚀 TGBot Entry Point Compatibility Wrapper
این فایل جهت سازگاری کامل با سرویس‌ها، اسکریپت‌ها یا فرآیندهای قدیمی که main.py را فراخوانی می‌کنند ایجاد شده است
و اجرای پروژه را به run.py هدایت می‌کند.
"""

import runpy
import sys

if __name__ == "__main__":
    runpy.run_module("run", run_name="__main__")
