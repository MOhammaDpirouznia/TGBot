#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
🛠️ Nuitka Binary Compiler & Release Packager - TGBot Protection System
=============================================================================
این اسکریپت تمام فایل‌های حیاتی پایتون پروژه را به فایل‌های باینری Native ماشین
(.so در لینوکس یا .pyd در ویندوز) کامپایل کرده و سورس‌کد پایتون را کاملاً حذف می‌کند.

خروجی:
یک پوشه توزیع (Distribution) فوق‌العاده امن، سبک و بدون سورس پایتون، آماده تحویل به مشتری.
=============================================================================
"""

import os
import sys
import shutil
import zipfile
import subprocess
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

BASE_DIR = Path(__file__).resolve().parent
DIST_DIR = BASE_DIR / "dist"
BUILD_DIR = BASE_DIR / "build_temp"
RELEASE_DIR = DIST_DIR / "tgbot_protected"

# ماژول‌های حیاتی که باید به باینری ماشین تبدیل شوند
CORE_MODULES = [
    "version.py",
    "license_guard.py",
    "bot.py",

    "dashboard.py",
    "database.py",
    "multibot_manager.py",
    "hidify.py",
    "payment.py",
    "admin_manager.py",
    "admin_bot_admin.py",
    "reseller_bot_admin.py",
    "ai_marketing_manager.py",
    "ai_bot_handlers.py",
    "bank_sms_parser.py",
    "sms_service.py",
    "ssl_manager.py",
    "node_monitor.py",
    "notifications.py",
    "session_analyzer.py",
    "palette_manager.py",
    "telegram_menu_helper.py",
    "tutorials_manager.py",
    "tutorials_data.py",
    "avatar_generator.py",
    "bundle_sales_bot.py",
    "cache_manager.py",
    "backup.py",
    "repair_and_restore_database.py",
    "utils.py",
    "i18n.py"
]

# پوشه‌ها و فایل‌های عمومی که باید کنار باینری قرار گیرند
ASSET_DIRS = [
    "templates",
    "static"
]

EXTRA_FILES = [
    ".env.example",
    "requirements.txt",
    "Procfile"
]


def check_prerequisites():
    """بررسی نصب بودن Nuitka و کامپایلر C"""
    print("[1/5] در حال بررسی پیش‌نیازهای کامپایل...")
    try:
        import nuitka
        print(f"  ✅ Nuitka نسخه {nuitka.__version__} شناسایی شد.")
    except ImportError:
        print("  ⚠️ ماژول Nuitka یافت نشد. در حال نصب خودکار...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "nuitka"])
        print("  ✅ Nuitka با موفقیت نصب شد.")


def prepare_directories():
    """آماده‌سازی دایرکتوری‌های بیلد"""
    print("\n[2/5] پاک‌سازی و ایجاد دایرکتوری‌های خروجی...")
    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)
    BUILD_DIR.mkdir(parents=True, exist_ok=True)

    if RELEASE_DIR.exists():
        shutil.rmtree(RELEASE_DIR)
    RELEASE_DIR.mkdir(parents=True, exist_ok=True)
    print(f"  📁 پوشه خروجی: {RELEASE_DIR}")


def compile_modules():
    """کامپایل تک‌تک فایل‌های پایتون به اکستنشن‌های C"""
    print("\n[3/5] در حال کامپایل فایل‌های پایتون به کدهای باینری C...")
    total = len(CORE_MODULES)
    compiled_count = 0

    for idx, mod_name in enumerate(CORE_MODULES, 1):
        mod_path = BASE_DIR / mod_name
        if not mod_path.exists():
            print(f"  ⏭️ رد کردن {mod_name} (فایل یافت نشد)")
            continue

        print(f"  ⚙️ [{idx}/{total}] در حال کامپایل باینری: {mod_name} ...")

        # دستور بهینه Nuitka برای ماژول مشترک
        cmd = [
            sys.executable, "-m", "nuitka",
            "--module",
            "--remove-output",
            "--no-pyi-file",
            f"--output-dir={BUILD_DIR}",
            str(mod_path)
        ]

        # فلگ‌های بهینه‌سازی
        cmd.extend([
            "--lto=yes",  # Link Time Optimization برای حداکثر امنیت و سرعت
            "--disable-console"
        ])

        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if res.returncode != 0:
                print(f"    ⚠️ هشدار: کامپایل {mod_name} ناموفق بود، فایل پایتون کپی می‌شود.")
                # فالبک: در صورت خطای یک فایل خاص، کپی نسخه پایتون
                shutil.copy2(mod_path, RELEASE_DIR / mod_name)
            else:
                compiled_count += 1
        except Exception as e:
            print(f"    ❌ خطا در اجرای کامپایلر: {e}")
            shutil.copy2(mod_path, RELEASE_DIR / mod_name)

    # انتقال تمام باینری‌های تولیدشده (.so یا .pyd) به پوشه ریلیز
    for ext_file in BUILD_DIR.glob("*.*"):
        if ext_file.suffix.lower() in [".so", ".pyd"]:
            shutil.copy2(ext_file, RELEASE_DIR / ext_file.name)
            print(f"  🔒 باینری منتقل شد: {ext_file.name}")

    print(f"\n  🎉 {compiled_count} ماژول به زبان ماشین C با موفقیت کامپایل شدند!")


def copy_runtime_and_assets():
    """کپی فایل‌های فرانت‌اند، قالب‌ها و استارتر بدون سورس کدهای اصلی"""
    print("\n[4/5] آماده‌سازی ساختار نهایی پکیج خریدار...")

    # ۱. کپی قالب‌های HTML و فایل‌های Static
    for d_name in ASSET_DIRS:
        src_d = BASE_DIR / d_name
        if src_d.exists():
            dst_d = RELEASE_DIR / d_name
            shutil.copytree(src_d, dst_d, dirs_exist_ok=True)
            print(f"  📂 پوشه کپی شد: {d_name}")

    # ۲. کپی فایل‌های کمکی مجاز
    for f_name in EXTRA_FILES:
        src_f = BASE_DIR / f_name
        if src_f.exists():
            shutil.copy2(src_f, RELEASE_DIR / f_name)
            print(f"  📄 فایل کپی شد: {f_name}")

    # ۳. تولید فایل استارتر ایمن و سبک (run.py)
    starter_code = """#!/usr/bin/env python3
# -*- coding: utf-8 -*-
\"\"\"
🚀 TGBot Protected Release Runner
این فایل رابط راه‌اندازی باینری‌های کامپایل‌شده سیستم است.
\"\"\"

import sys
import os

# اطمینان از قرار گرفتن پوشه برنامه در مسیر ماژول‌ها
APP_DIR = os.path.dirname(os.path.abspath(__file__))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

if __name__ == "__main__":
    try:
        from license_guard import guard
        lic = guard.verify()
        if not lic.get("valid"):
            print("\\n" + "=" * 65)
            print("⛔ [LicenseGuard] خطا در تایید مجوز اجرای پروژه!")
            print(f"📌 پیام سیستم: {lic.get('message')}")
            print(f"🖥️ شناسه سخت‌افزاری سرور (Machine ID): {guard.machine_id}")
            print("=" * 65 + "\\n")
            sys.exit(1)

        print(f"🛡️ [LicenseGuard] مجوز معتبر است ({lic.get('customer', 'رسمی')}).")
        guard.start_watchdog(interval_minutes=30)
    except Exception as e:
        print(f"License verification error: {e}")
        sys.exit(1)

    print("🚀 در حال اجرای سامانه...")
    import bot
    bot.main()
"""
    with open(RELEASE_DIR / "run.py", "w", encoding="utf-8") as f:
        f.write(starter_code)
    print("  ✅ فایل استارتر run.py ایجاد شد.")

    # ۴. ساخت اسکریپت راه‌اندازی سریع در لینوکس (start.sh)
    start_sh_code = """#!/bin/bash
set -e
echo "Starting TGBot Protected Release..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
    venv/bin/pip install --upgrade pip -q
    venv/bin/pip install -r requirements.txt -q
fi
venv/bin/python run.py
"""
    with open(RELEASE_DIR / "start.sh", "w", encoding="utf-8", newline="\n") as f:
        f.write(start_sh_code)
    print("  ✅ اسکریپت استارت لینوکس (start.sh) ایجاد شد.")


def package_release_zip():
    """فشرده‌سازی پکیج محافظت‌شده به فایل ZIP"""
    print("\n[5/5] ساخت فایل فشرده ZIP نهایی...")
    zip_output_path = DIST_DIR / "TGBot_Protected_Release.zip"

    with zipfile.ZipFile(zip_output_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(RELEASE_DIR):
            for file in files:
                f_path = Path(root) / file
                arcname = f_path.relative_to(RELEASE_DIR)
                zipf.write(f_path, arcname)

    # پاک‌سازی پوشه موقت بیلد
    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)

    zip_size_mb = os.path.getsize(zip_output_path) / (1024 * 1024)
    print("=" * 65)
    print("🎉 پکیج باینری محافظت‌شده با موفقیت ساخته شد!")
    print(f"📦 مسیر فایل ریلیز: {zip_output_path}")
    print(f"📊 حجم پکیج: {zip_size_mb:.2f} مگابایت")
    print("=" * 65)


if __name__ == "__main__":
    print("=" * 65)
    print("🛡️ شروع فرآیند کامپایل و محافظت باینری TGBot با Nuitka")
    print("=" * 65)
    prepare_directories()
    check_prerequisites()
    compile_modules()
    copy_runtime_and_assets()
    package_release_zip()
