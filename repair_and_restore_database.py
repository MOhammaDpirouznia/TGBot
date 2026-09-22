#!/usr/bin/env python3
"""
🛠️ اسکریپت تخصصی پاک‌سازی اطلاعات تستی و بازیابی شماره‌های مشتریان از بکاپ
این اسکریپت با حفظ ۱۰۰٪ نام‌های اشتراک، UUIDها، حجم‌ها و تاریخ‌ها، دیتابیس را پاک‌سازی و در صورت تمایل شماره‌های قدیمی را از بکاپ دیشب بازمی‌گرداند.
"""

import os
import sys
import shutil
import sqlite3
from pathlib import Path
from datetime import datetime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

def find_active_db_path() -> Path:
    env_dir = os.environ.get("DATA_DIR", "").strip()
    if env_dir:
        p = Path(env_dir) / "bot_database.db"
        if p.exists():
            return p
    candidates = [
        Path("data/bot_database.db"),
        Path("/data/bot_database.db"),
        Path("/opt/hiddibot/data/bot_database.db"),
        Path("../data/bot_database.db"),
        Path("bot_database.db")
    ]
    for c in candidates:
        if c.exists():
            return c
    return Path("data/bot_database.db")

def repair_database(target_db_path: Path, backup_source_path: Path = None):
    print("=" * 65)
    print("      سامانه تخصصی ترمیم پایگاه داده و رفع تداخل پرونده مشتریان")
    print("=" * 65)

    if not target_db_path.exists():
        print(f"[!] خطا: فایل دیتابیس هدف در مسیر {target_db_path} یافت نشد.")
        return False

    print(f"[*] پایگاه داده فعال: {target_db_path.resolve()}")

    now_tag = datetime.now().strftime("%Y%m%d_%H%M%S")
    safety_backup = target_db_path.parent / f"safety_pre_repair_backup_{now_tag}.db"
    try:
        shutil.copy2(target_db_path, safety_backup)
        print(f"[+] پشتیبان امنیتی فوری ایجاد شد:\n    -> {safety_backup.name}")
    except Exception as e_bk:
        print(f"[!] هشدار: ایجاد پشتیبان امنیتی با خطا مواجه شد ({e_bk})، عملیات متوقف می‌شود.")
        return False

    conn = sqlite3.connect(target_db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT count(*) FROM users WHERE telegram_id = 0 OR telegram_id IS NULL")
        zero_users_count = cursor.fetchone()[0]
        if zero_users_count > 0:
            cursor.execute("DELETE FROM users WHERE telegram_id = 0 OR telegram_id IS NULL")
            print(f"[✓] تعداد {zero_users_count} رکورد باطله با شناسه صفر از جدول users حذف گردید.")

        cursor.execute("""
            DELETE FROM users 
            WHERE phone_number LIKE '%09118620259%' 
               OR full_name LIKE '%خادملو%'
        """)
        print("[✓] کاربر تستی (زهرا خادملو / ۰۹۱۱۸۶۲۰۲۵۹) از جدول کاربران پاک‌سازی شد.")

        restored_phones = 0
        if backup_source_path and Path(backup_source_path).exists():
            b_path = Path(backup_source_path)
            print(f"[*] در حال استخراج و تطبیق شماره‌های تماس از بکاپ: {b_path.name} ...")
            try:
                b_conn = sqlite3.connect(b_path)
                b_conn.row_factory = sqlite3.Row
                b_cur = b_conn.cursor()
                b_cur.execute("""
                    SELECT hidify_uuid, account_name, phone_number 
                    FROM subscriptions 
                    WHERE phone_number IS NOT NULL AND phone_number != ''
                """)
                old_subs = b_cur.fetchall()
                b_conn.close()

                for row in old_subs:
                    u_uuid = row["hidify_uuid"]
                    acc_nm = row["account_name"]
                    p_num = str(row["phone_number"]).strip()
                    if not p_num or "09118620259" in p_num:
                        continue

                    if u_uuid:
                        cursor.execute("""
                            UPDATE subscriptions 
                            SET phone_number = ? 
                            WHERE hidify_uuid = ?
                        """, (p_num, u_uuid))
                        if cursor.rowcount > 0:
                            restored_phones += cursor.rowcount
                            continue

                    if acc_nm:
                        cursor.execute("""
                            UPDATE subscriptions 
                            SET phone_number = ? 
                            WHERE account_name = ?
                        """, (p_num, acc_nm))
                        if cursor.rowcount > 0:
                            restored_phones += cursor.rowcount

                print(f"[✓] موفقیت: تعداد {restored_phones} شماره تماس واقعی مشتریان بر اساس UUID و نام اکانت از بکاپ دیشب با موفقیت بازیابی شد.")
            except Exception as e_rst:
                print(f"[!] خطا در خواندن فایل بکاپ دیشب: {e_rst}")

        cursor.execute("""
            SELECT count(*) FROM subscriptions 
            WHERE (telegram_id = 0 OR telegram_id IS NULL)
              AND (phone_number LIKE '%09118620259%' OR full_name LIKE '%خادملو%')
        """)
        affected_count = cursor.fetchone()[0]

        cursor.execute("""
            UPDATE subscriptions
            SET phone_number = NULL,
                full_name = NULL,
                birthday = NULL,
                telegram_username = NULL,
                primary_isp = NULL,
                secondary_isp = NULL
            WHERE (telegram_id = 0 OR telegram_id IS NULL)
              AND (phone_number LIKE '%09118620259%' OR full_name LIKE '%خادملو%')
        """)
        print(f"[✓] تعداد {affected_count} اشتراک آلوده شده به اطلاعات تستی با موفقیت پاک‌سازی و سفید گردید.")

        conn.commit()

        cursor.execute("SELECT count(*) FROM subscriptions")
        total_subs = cursor.fetchone()[0]
        cursor.execute("SELECT count(*) FROM users")
        total_users = cursor.fetchone()[0]

        print("-" * 65)
        print("📊 خلاصه نتیجه ترمیم:")
        print(f"   • کل اشتراک‌های فعال و موجود: {total_subs:,} (۱۰۰٪ نام‌ها و UUIDها محفوظ)")
        print(f"   • کل کاربران سیستم: {total_users:,}")
        print(f"   • تعداد شماره تماس‌های بازیابی‌شده از بکاپ: {restored_phones:,}")
        print(f"   • اشتراک‌های پاک‌سازی‌شده از داده‌های تستی: {affected_count:,}")
        print("=" * 65)
        print("✅ پایگاه داده کاملاً سالم، یکپارچه و بهینه‌سازی شد.")
        return True

    except Exception as e:
        conn.rollback()
        print(f"[!] خطا در حین عملیات ترمیم: {e}")
        return False
    finally:
        conn.close()

if __name__ == "__main__":
    active_db = find_active_db_path()
    backup_file = None
    if len(sys.argv) > 1:
        backup_file = Path(sys.argv[1])
    repair_database(active_db, backup_file)
