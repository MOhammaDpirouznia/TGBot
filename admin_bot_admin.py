#!/usr/bin/env python3
"""
ماژول اختصاصی پنل مدیریت پیشرفته ربات تلگرام برای مدیران (Admin Bot Manager)
قابل استفاده در هر دو ربات:
۱. ربات مدیریت اصلی (bot.py)
۲. ربات فروش بسته نمایندگی (bundle_sales_bot.py)

ارائه‌دهنده:
- آمار جامع ۳۶۰ درجه سامانه و درآمد
- مدیریت پرداخت‌ها و فیش‌های در انتظار با امکان تایید و واریز به کارت/صندوق
- ساخت آنی مشتری و اشتراک جدید با انتخاب حساب مقصد
- تمدید مشتری با جستجو
- مدیریت کدهای تخفیف (مشاهده، ساخت و حذف کد)
- گزارشات کاربردی (فروش روز/ماه، مشترکین رو به انقضا، پرمصرف‌ترین‌ها)
- پیام همگانی به کاربران یا نمایندگان
- تنظیمات و وضعیت حساب‌ها، درگاه‌ها و تایید خودکار پیامک
"""

import os
import re
import html
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Tuple

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, CopyTextButton

from database import db
from utils import get_now_shamsi, get_now_iso, get_now_naive, generate_qr_code_bytes

logger = logging.getLogger("admin_bot_mgr")


def get_admin_advanced_stats_text() -> str:
    """تولید متن آمار جامع و لحظه‌ای سامانه برای مدیریت"""
    conn = db.get_connection()
    cursor = conn.cursor()

    # کاربران تلگرام
    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0] or 0

    # اشتراک‌ها
    cursor.execute("SELECT COUNT(*) FROM subscriptions WHERE is_deleted = 0 OR is_deleted IS NULL")
    total_subs = cursor.fetchone()[0] or 0

    cursor.execute("SELECT COUNT(*) FROM subscriptions WHERE status = 'active' AND (is_deleted = 0 OR is_deleted IS NULL)")
    active_subs = cursor.fetchone()[0] or 0

    cursor.execute("SELECT COUNT(*) FROM subscriptions WHERE is_online = 1 AND (is_deleted = 0 OR is_deleted IS NULL)")
    online_subs = cursor.fetchone()[0] or 0

    # ترافیک مصرفی
    cursor.execute("SELECT COALESCE(SUM(data_used), 0), COALESCE(SUM(data_limit), 0) FROM subscriptions WHERE is_deleted = 0 OR is_deleted IS NULL")
    t_row = cursor.fetchone()
    total_used_gb = round(t_row[0] or 0, 2)
    total_limit_gb = round(t_row[1] or 0, 2)

    # پرداخت‌ها و فیش‌ها
    cursor.execute("SELECT COUNT(*) FROM transactions WHERE status = 'pending' AND (is_deleted = 0 OR is_deleted IS NULL)")
    pending_tx = cursor.fetchone()[0] or 0

    cursor.execute("SELECT COUNT(*), COALESCE(SUM(amount), 0) FROM transactions WHERE status IN ('approved', 'completed') AND (is_deleted = 0 OR is_deleted IS NULL)")
    app_row = cursor.fetchone()
    completed_tx = app_row[0] or 0
    total_revenue = app_row[1] or 0

    # فروش امروز
    today_str = get_now_naive().strftime("%Y-%m-%d")
    cursor.execute("SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE status IN ('approved', 'completed') AND created_at LIKE ? AND (is_deleted = 0 OR is_deleted IS NULL)", (f"{today_str}%",))
    today_rev = cursor.fetchone()[0] or 0

    # نمایندگان و بسته‌ها
    cursor.execute("SELECT COUNT(*) FROM resellers WHERE status = 'active'")
    active_resellers = cursor.fetchone()[0] or 0

    # تیکت‌های باز
    cursor.execute("SELECT COUNT(*) FROM support_tickets WHERE status = 'open'")
    open_tickets = cursor.fetchone()[0] or 0

    conn.close()

    # خلاصه‌وضعیت مالی حساب‌ها
    fin_summary = db.get_financial_accounts_summary("admin", 0)
    total_cards_bal = fin_summary.get("total_balance", 0)
    unsettled_cash = fin_summary.get("unsettled_cash", 0)
    net_bal = fin_summary.get("net_floating_balance", 0)

    # تایید خودکار پیامک بانک
    sms_cfg = db.get_bank_sms_config(owner_type="admin", owner_id=0)
    sms_status = "🟢 فعال (با ارقام خرد هوشمند)" if sms_cfg.get("enabled") else "⚪️ غیرفعال"

    tot_rev_fmt = f"{total_revenue:,}".replace(",", "،")
    today_rev_fmt = f"{today_rev:,}".replace(",", "،")
    net_bal_fmt = f"{net_bal:,}".replace(",", "،")
    cards_bal_fmt = f"{total_cards_bal:,}".replace(",", "،")

    return f"""📊 **آمار ۳۶۰ درجه و وضعیت لحظه‌ای سامانه**

👑 **مدیریت ارشد:**
👥 کل کاربران تلگرام: **{total_users:,}** نفر
🛡 اشتراک‌های فعال: **{active_subs:,}** (از کل {total_subs:,})
🌐 مشترکین آنلاین: **{online_subs:,}** نفر
📊 کل حجم مصرفی: **{total_used_gb} GB** از {total_limit_gb} GB

💰 **وضعیت درآمد و فروش:**
• 💵 فروش امروز: **{today_rev_fmt} تومان**
• 📈 کل درآمد ثبت‌شده: **{tot_rev_fmt} تومان**
• ⏳ فیش‌های در انتظار بررسی: **{pending_tx}** فیش
• ✅ پرداخت‌های تاییدشده: **{completed_tx:,}** عدد

💼 **کیف پول، حساب‌ها و دارایی‌ها:**
• 💳 موجودی کل حساب‌ها و کارت‌ها: **{cards_bal_fmt} تومان**
• 💵 صندوق نقد تسویه‌نشده: **{unsettled_cash:,} تومان**
• 💎 **خالص نقدینگی و دارایی‌ها:** **{net_bal_fmt} تومان**

🤝 **نمایندگان و همکاران:**
• تعداد نمایندگان فعال: **{active_resellers}** نماینده
• تایید خودکار پیامک بانکی: {sms_status}
• تیکت‌های باز پشتیبانی: **{open_tickets}** تیکت
"""


def get_admin_advanced_keyboard(is_bundle_bot: bool = False) -> InlineKeyboardMarkup:
    """تولید کیبورد اصلی مدیریت پیشرفته تلگرام برای مدیران"""
    back_cb = "adm_bundle_close" if is_bundle_bot else "admin_back"
    
    if is_bundle_bot:
        keyboard = [
            [InlineKeyboardButton("📊 آمار ۳۶۰ درجه سامانه و بسته‌ها", callback_data="adm_adv_stats")],
            [
                InlineKeyboardButton("💳 فیش‌های بسته‌ها (در انتظار)", callback_data="adm_adv_payments"),
                InlineKeyboardButton("📦 بسته‌های شارژ نمایندگی", callback_data="adm_adv_bundles"),
            ],
            [
                InlineKeyboardButton("👥 شارژ مستقیم کیف پول نماینده", callback_data="adm_adv_resellers"),
                InlineKeyboardButton("🎁 کدهای تخفیف بسته‌ها", callback_data="adm_adv_discounts"),
            ],
            [
                InlineKeyboardButton("👤 ساخت اشتراک دستی", callback_data="adm_adv_create_user"),
                InlineKeyboardButton("🔄 تمدید مشتری (جستجو)", callback_data="adm_adv_renew_user"),
            ],
            [
                InlineKeyboardButton("📈 گزارشات مالی و فروش", callback_data="adm_adv_reports"),
                InlineKeyboardButton("📢 پیام همگانی به نمایندگان", callback_data="adm_adv_broadcast"),
            ],
            [
                InlineKeyboardButton("⚙️ وضعیت حساب‌ها و درگاه‌ها", callback_data="adm_adv_settings"),
            ],
            [
                InlineKeyboardButton("🔙 بازگشت به منوی کاربری", callback_data=back_cb)
            ]
        ]
    else:
        keyboard = [
            [InlineKeyboardButton("📊 آمار دقیق و جامع سامانه", callback_data="adm_adv_stats")],
            [
                InlineKeyboardButton("💳 مدیریت پرداخت‌ها و فیش‌ها", callback_data="adm_adv_payments"),
                InlineKeyboardButton("📨 تیکت‌های پشتیبانی", callback_data="adm_adv_tickets"),
            ],
            [
                InlineKeyboardButton("👤 ساخت مشتری جدید", callback_data="adm_adv_create_user"),
                InlineKeyboardButton("🔄 تمدید مشتری (جستجو)", callback_data="adm_adv_renew_user"),
            ],
            [
                InlineKeyboardButton("🎁 کدهای تخفیف", callback_data="adm_adv_discounts"),
                InlineKeyboardButton("📈 گزارشات کاربردی", callback_data="adm_adv_reports"),
            ],
            [
                InlineKeyboardButton("📢 ارسال پیام همگانی", callback_data="adm_adv_broadcast"),
                InlineKeyboardButton("⚙️ وضعیت درگاه‌ها و حساب‌ها", callback_data="adm_adv_settings"),
            ],
            [
                InlineKeyboardButton("💳 مدیریت کارت‌ها", callback_data="admin_cards"),
                InlineKeyboardButton("📦 مدیریت پلن‌ها", callback_data="admin_plans"),
            ],
            [
                InlineKeyboardButton("🔙 بازگشت به منوی کاربری", callback_data=back_cb)
            ]
        ]
    return InlineKeyboardMarkup(keyboard)


def get_admin_discounts_payload() -> Tuple[str, InlineKeyboardMarkup]:
    """دریافت و نمایش کدهای تخفیف در ربات مدیریت"""
    discounts = db.get_discount_codes()
    if not discounts:
        text = "🎁 **مدیریت کدهای تخفیف**\n\nهنوز هیچ کد تخفیفی در سیستم ثبت نشده است.\nجهت ایجاد کد تخفیف جدید دکمه زیر را لمس نمایید:"
        buttons = [
            [InlineKeyboardButton("➕ ایجاد کد تخفیف جدید", callback_data="adm_disc_create")],
            [InlineKeyboardButton("🔙 بازگشت به پنل مدیریت", callback_data="adm_adv_menu")]
        ]
        return text, InlineKeyboardMarkup(buttons)

    text = f"🎁 **لیست کدهای تخفیف فعال ({len(discounts)} کد):**\n\n"
    for d in discounts[:8]:
        code = d.get("code")
        pct = d.get("discount_percent", 0)
        amt = d.get("discount_amount", 0)
        used = d.get("used_count", 0)
        max_u = d.get("max_uses", 0)
        max_str = f"از {max_u}" if max_u > 0 else "نامحدود"
        val_str = f"{pct}٪" if pct > 0 else f"{amt:,} ت"
        st = "🟢 فعال" if d.get("is_active", 1) else "⚪️ غیرفعال"
        text += f"• کد: `{code}` | تخفیف: **{val_str}** | مصرف: {used} {max_str} ({st})\n"

    buttons = [
        [InlineKeyboardButton("➕ ایجاد کد تخفیف جدید", callback_data="adm_disc_create")],
    ]
    for d in discounts[:4]:
        c_code = d.get("code")
        buttons.append([InlineKeyboardButton(f"🗑️ حذف کد {c_code}", callback_data=f"adm_disc_del_{c_code}")])

    buttons.append([InlineKeyboardButton("🔙 بازگشت به پنل مدیریت", callback_data="adm_adv_menu")])
    return text, InlineKeyboardMarkup(buttons)


def get_admin_payments_payload(filter_type: str = "pending", page: int = 1) -> Tuple[str, InlineKeyboardMarkup]:
    """نمایش فیش‌ها و پرداخت‌های مشتریان برای مدیریت"""
    conn = db.get_connection()
    cursor = conn.cursor()

    if filter_type == "pending":
        cursor.execute("SELECT * FROM transactions WHERE status = 'pending' AND (is_deleted = 0 OR is_deleted IS NULL) ORDER BY id DESC LIMIT 8")
        title = "⏳ فیش‌ها و پرداخت‌های در انتظار تایید"
    else:
        cursor.execute("SELECT * FROM transactions WHERE status IN ('approved', 'completed') AND (is_deleted = 0 OR is_deleted IS NULL) ORDER BY id DESC LIMIT 8")
        title = "✅ سوابق پرداخت‌های تاییدشده اخیر"

    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    if not rows:
        text = f"💳 **{title}**\n\nهیچ تراکنشی در این وضعیت یافت نشد."
        buttons = [
            [
                InlineKeyboardButton("⏳ در انتظار بررسی", callback_data="adm_pay_flt_pending"),
                InlineKeyboardButton("✅ تاییدشده‌ها", callback_data="adm_pay_flt_approved")
            ],
            [InlineKeyboardButton("🔙 بازگشت به پنل مدیریت", callback_data="adm_adv_menu")]
        ]
        return text, InlineKeyboardMarkup(buttons)

    text = f"💳 **{title} ({len(rows)} مورد):**\n\nروی هر سفارش کلیک کنید تا جزئیات و دکمه‌های تایید/رد نمایش داده شود:\n"
    buttons = []
    for r in rows:
        order_id = r.get("order_id")
        amount = r.get("amount", 0)
        u_name = r.get("username") or r.get("user_id") or "کاربر"
        plan = r.get("plan_name") or "اشتراک"
        btn_txt = f"💰 {amount:,} ت | {u_name} ({plan[:15]})"
        buttons.append([InlineKeyboardButton(btn_txt, callback_data=f"adm_pay_dtl_{order_id}")])

    buttons.append([
        InlineKeyboardButton("⏳ در انتظار بررسی", callback_data="adm_pay_flt_pending"),
        InlineKeyboardButton("✅ تاییدشده‌ها", callback_data="adm_pay_flt_approved")
    ])
    buttons.append([InlineKeyboardButton("🔙 بازگشت به پنل مدیریت", callback_data="adm_adv_menu")])
    return text, InlineKeyboardMarkup(buttons)


def get_admin_reports_payload() -> Tuple[str, InlineKeyboardMarkup]:
    """گزارشات مدیریتی شامل فروش روز/ماه و مشترکین رو به انقضا"""
    conn = db.get_connection()
    cursor = conn.cursor()

    today_str = get_now_naive().strftime("%Y-%m-%d")
    month_str = get_now_naive().strftime("%Y-%m")

    # فروش امروز
    cursor.execute("SELECT COUNT(*), COALESCE(SUM(amount), 0) FROM transactions WHERE status IN ('approved', 'completed') AND created_at LIKE ?", (f"{today_str}%",))
    t_cnt, t_amt = cursor.fetchone()

    # فروش این ماه
    cursor.execute("SELECT COUNT(*), COALESCE(SUM(amount), 0) FROM transactions WHERE status IN ('approved', 'completed') AND created_at LIKE ?", (f"{month_str}%",))
    m_cnt, m_amt = cursor.fetchone()

    # مشترکین رو به انقضا (کمتر از ۳ روز)
    soon_expire_date = (get_now_naive() + timedelta(days=3)).isoformat()
    cursor.execute("SELECT COUNT(*) FROM subscriptions WHERE status = 'active' AND expire_date <= ? AND expire_date >= ? AND (is_deleted = 0 OR is_deleted IS NULL)", (soon_expire_date, get_now_iso()))
    expiring_soon = cursor.fetchone()[0] or 0

    # پرمصرف‌ترین مشترکین
    cursor.execute("SELECT account_name, data_used, data_limit FROM subscriptions WHERE (is_deleted = 0 OR is_deleted IS NULL) ORDER BY data_used DESC LIMIT 3")
    top_consumers = [dict(r) for r in cursor.fetchall()]
    conn.close()

    text = f"""📈 **گزارشات کاربردی و هوش فروش**

📅 **فروش امروز ({today_str}):**
• تعداد سفارشات: **{t_cnt or 0}**
• مبلغ درآمد: **{(t_amt or 0):,} تومان**

🗓️ **فروش ماه جاری ({month_str}):**
• تعداد سفارشات: **{m_cnt or 0}**
• مبلغ درآمد: **{(m_amt or 0):,} تومان**

⏳ **مشترکین رو به اتمام (کمتر از ۳ روز):** **{expiring_soon}** کاربر
(می‌توانید با پیام همگانی یا یادآوری به تمدید این مشترکین اقدام کنید)

🔥 **پرمصرف‌ترین مشترکین فعلی:**
"""
    for tc in top_consumers:
        name = tc.get("account_name") or "بی‌نام"
        used = tc.get("data_used", 0)
        lim = tc.get("data_limit", 0)
        text += f"• `{name}`: مصرف {round(used, 1)} GB از {round(lim, 1)} GB\n"

    buttons = [
        [InlineKeyboardButton("🔄 بروزرسانی گزارش", callback_data="adm_adv_reports")],
        [InlineKeyboardButton("🔙 بازگشت به پنل مدیریت", callback_data="adm_adv_menu")]
    ]
    return text, InlineKeyboardMarkup(buttons)


def get_admin_settings_overview_payload() -> Tuple[str, InlineKeyboardMarkup]:
    """گزارش وضعیت تنظیمات حساب‌ها، درگاه‌ها و تایید خودکار"""
    summary = db.get_financial_accounts_summary("admin", 0)
    accounts = summary.get("accounts", [])
    sms_cfg = db.get_bank_sms_config(owner_type="admin", owner_id=0)
    sms_st = "🟢 فعال (ارقام خرد هوشمند)" if sms_cfg.get("enabled") else "⚪️ غیرفعال"

    text = f"""⚙️ **وضعیت حساب‌ها، درگاه‌ها و تایید خودکار**

⚡ **سرویس تایید خودکار پیامک بانک:** {sms_st}
💵 **کل دارایی و مانده شناور:** **{summary.get('net_floating_balance', 0):,} تومان**
💳 **تعداد کارت‌ها و حساب‌های ثبت‌شده:** {len(accounts)} مورد

📋 **حساب‌ها و کارت‌های فعال:**
"""
    for acc in accounts[:6]:
        num = acc.get("card_number") or "-"
        clean_num = num[-4:] if len(num) >= 4 else num
        name = acc.get("bank_name") or acc.get("card_holder") or "حساب"
        bal = acc.get("balance", 0)
        t_label = acc.get("type_label", "کارت")
        def_tag = " [⭐ پیش‌فرض]" if acc.get("is_default_customer") or acc.get("is_default") else ""
        text += f"• {name} (..{clean_num}) | **{t_label}**{def_tag}: {bal:,} ت\n"

    buttons = [
        [InlineKeyboardButton("🔄 بروزرسانی وضعیت", callback_data="adm_adv_settings")],
        [InlineKeyboardButton("🔙 بازگشت به پنل مدیریت", callback_data="adm_adv_menu")]
    ]
    return text, InlineKeyboardMarkup(buttons)
