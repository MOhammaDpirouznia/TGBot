#!/usr/bin/env python3
"""
ماژول اختصاصی پنل مدیریت ربات تلگرام نمایندگان (Reseller Bot Admin Manager)
ارائه‌دهنده توابع، کیبوردها و پردازش‌های مدیریتی برای نمایندگان فروش:
- آمار ربات اختصاصی هر نماینده (بدون تعداد بکاپ‌ها)
- حذف و غیرفعال‌سازی گزینه‌های غیرمجاز (پشتیبان‌گیری، مدیریت کارت‌ها، مدیریت پلن‌ها)
- اتصال مستقیم به کارت‌ها، درگاه‌ها و تایید خودکار کارت به کارت اختصاصی نماینده
- خرید شارژ و بسته برای پنل نمایندگی
- مدیریت تیکت‌ها و ارسال پاسخ
- مدیریت پرداخت‌ها و تایید/رد آنی فیش‌ها
- ساخت آنی مشتری و اشتراک جدید
- تمدید مشتری با جستجوی نام کاربری یا شناسه
- مدیریت کدهای تخفیف
- گزارشات کاربردی (فروش، مشترکین رو به انقضا، پرمصرف‌ترین‌ها)
- پیام همگانی و وضعیت تنظیمات پرداخت
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

logger = logging.getLogger("reseller_admin")


def get_reseller_stats_text(reseller_id: int) -> str:
    """
    تولید متن آمار اختصاصی ربات نماینده
    تنها شامل کاربران، مشتریان، ترافیک و تراکنش‌های متعلق به همین نماینده
    عنوان تعداد بکاپ‌ها به طور کامل حذف شده است.
    """
    reseller = db.get_reseller(reseller_id) or {}
    r_name = reseller.get("name") or reseller.get("username") or f"نماینده #{reseller_id}"
    
    conn = db.get_connection()
    cursor = conn.cursor()
    
    # تعداد کاربران تلگرام ثبت‌شده برای این نماینده
    cursor.execute("SELECT COUNT(*) FROM users WHERE reseller_id = ?", (reseller_id,))
    total_users = cursor.fetchone()[0] or 0
    
    # تعداد کل اشتراک‌های غیرحذف‌شده
    cursor.execute("SELECT COUNT(*) FROM subscriptions WHERE reseller_id = ? AND (is_deleted = 0 OR is_deleted IS NULL)", (reseller_id,))
    total_subs = cursor.fetchone()[0] or 0
    
    # اشتراک‌های فعال
    cursor.execute("SELECT COUNT(*) FROM subscriptions WHERE reseller_id = ? AND status = 'active' AND (is_deleted = 0 OR is_deleted IS NULL)", (reseller_id,))
    active_subs = cursor.fetchone()[0] or 0
    
    # کاربران آنلاین
    cursor.execute("SELECT COUNT(*) FROM subscriptions WHERE reseller_id = ? AND is_online = 1 AND (is_deleted = 0 OR is_deleted IS NULL)", (reseller_id,))
    online_subs = cursor.fetchone()[0] or 0
    
    # ترافیک مصرفی
    cursor.execute("SELECT COALESCE(SUM(data_used), 0), COALESCE(SUM(data_limit), 0) FROM subscriptions WHERE reseller_id = ? AND (is_deleted = 0 OR is_deleted IS NULL)", (reseller_id,))
    t_row = cursor.fetchone()
    total_used_gb = round(t_row[0] or 0, 2)
    total_limit_gb = round(t_row[1] or 0, 2)
    
    # تراکنش‌های مشتریان
    cursor.execute("""
        SELECT COUNT(*) FROM transactions 
        WHERE reseller_id = ? AND status = 'pending'
          AND (gateway != 'bundle_reseller' AND order_id NOT LIKE 'R_BUNDLE%')
          AND (is_deleted = 0 OR is_deleted IS NULL)
    """, (reseller_id,))
    pending_tx = cursor.fetchone()[0] or 0
    
    cursor.execute("""
        SELECT COUNT(*), COALESCE(SUM(amount), 0) FROM transactions 
        WHERE reseller_id = ? AND status IN ('approved', 'completed')
          AND (gateway != 'bundle_reseller' AND order_id NOT LIKE 'R_BUNDLE%')
          AND (is_deleted = 0 OR is_deleted IS NULL)
    """, (reseller_id,))
    app_row = cursor.fetchone()
    completed_tx = app_row[0] or 0
    total_revenue = app_row[1] or 0
    
    cursor.execute("""
        SELECT COUNT(*) FROM transactions 
        WHERE reseller_id = ? AND status = 'rejected'
          AND (gateway != 'bundle_reseller' AND order_id NOT LIKE 'R_BUNDLE%')
          AND (is_deleted = 0 OR is_deleted IS NULL)
    """, (reseller_id,))
    rejected_tx = cursor.fetchone()[0] or 0
    
    # تیکت‌های باز
    cursor.execute("SELECT COUNT(*) FROM support_tickets WHERE reseller_id = ? AND status = 'open'", (reseller_id,))
    open_tickets = cursor.fetchone()[0] or 0
    
    conn.close()
    
    # کارت‌های فعال
    rcards = db.get_reseller_cards(reseller_id)
    active_cards_count = len([c for c in rcards if c.get("is_active")])
    if active_cards_count == 0 and reseller.get("card_number"):
        active_cards_count = 1
        
    # پلن‌های فعال
    rplans = db.get_reseller_plans(reseller_id)
    active_plans_count = len(rplans)
    
    # وضعیت مالی پنل نماینده
    r_stats = db.get_reseller_stats(reseller_id) or {}
    balance = r_stats.get("balance", 0)
    purchasing_power = r_stats.get("total_purchasing_power", balance)
    discount = r_stats.get("discount_percent", 20)
    
    # تایید خودکار پیامک بانک
    sms_cfg = db.get_reseller_bank_sms_config(reseller_id)
    sms_status = "🟢 فعال (هوشمند با ارقام خرد)" if sms_cfg.get("enabled") else "⚪️ غیرفعال"
    
    rev_fmt = f"{total_revenue:,}".replace(",", "،")
    bal_fmt = f"{balance:,}".replace(",", "،")
    pow_fmt = f"{purchasing_power:,}".replace(",", "،")
    
    return f"""📊 **آمار دقیق و اختصاصی ربات شما**

👤 **نماینده:** {r_name} (شناسه: `{reseller_id}`)

👥 **کاربران تلگرام:** {total_users} نفر
🛡 **اشتراک‌های فعال:** {active_subs} (از کل {total_subs})
🌐 **کاربران آنلاین:** {online_subs} نفر
📊 **مصرف ترافیک:** {total_used_gb} GB از {total_limit_gb} GB

📦 **پلن‌های فعال شما:** {active_plans_count} پلن
💳 **کارت‌های بانکی فعال:** {active_cards_count} کارت
⚡ **تایید خودکار کارت به کارت:** {sms_status}

💰 **وضعیت پرداخت‌های مشتریان شما:**
• ⏳ در انتظار تایید و بررسی: {pending_tx}
• ✅ تایید شده و موفق: {completed_tx}
• ❌ رد شده: {rejected_tx}
💵 **مجموع فروش ربات:** {rev_fmt} تومان

💼 **وضعیت پنل نمایندگی:**
• موجودی کیف پول: {bal_fmt} تومان
• توان خرید کل (با اعتبار): {pow_fmt} تومان
• تخفیف خرید عمده: {discount}٪
📨 **تیکت‌های باز پشتیبانی:** {open_tickets} تیکت
"""


def get_reseller_admin_keyboard(is_multibot: bool = False, role: str = "main") -> InlineKeyboardMarkup:
    """
    تولید کیبورد منوی اصلی پنل ادمین ربات نمایندگان با پشتیبانی از نقش‌های مختلف
    (دکمه‌های پشتیبان‌گیری، بازیابی پشتیبان، مدیریت کارت‌ها و مدیریت پلن‌ها حذف شده‌اند)
    """
    back_callback = "res_adm_close" if is_multibot else "admin_back"
    
    if role == "finance":
        keyboard = [
            [InlineKeyboardButton("📊 آمار فروش و ربات", callback_data="res_adm_stats")],
            [InlineKeyboardButton("💳 مدیریت پرداخت‌ها و فیش‌ها", callback_data="res_adm_payments")],
            [InlineKeyboardButton("💰 خرید شارژ و بسته پنل", callback_data="res_adm_bundles")],
            [InlineKeyboardButton("📈 گزارشات مالی و فروش", callback_data="res_adm_reports")],
            [InlineKeyboardButton("🔙 بازگشت به منوی کاربری", callback_data=back_callback)]
        ]
    elif role == "support":
        keyboard = [
            [InlineKeyboardButton("📨 مدیریت تیکت‌ها و پیام‌ها", callback_data="res_adm_tickets")],
            [InlineKeyboardButton("📊 آمار ربات", callback_data="res_adm_stats")],
            [InlineKeyboardButton("🔙 بازگشت به منوی کاربری", callback_data=back_callback)]
        ]
    elif role == "sales":
        keyboard = [
            [InlineKeyboardButton("👤 ساخت مشتری جدید", callback_data="res_adm_create_user")],
            [InlineKeyboardButton("🔄 تمدید مشتری (جستجو)", callback_data="res_adm_renew_user")],
            [InlineKeyboardButton("🎁 کدهای تخفیف", callback_data="res_adm_discounts")],
            [InlineKeyboardButton("📊 آمار مشترکین", callback_data="res_adm_stats")],
            [InlineKeyboardButton("🔙 بازگشت به منوی کاربری", callback_data=back_callback)]
        ]
    else: # main / full admin
        keyboard = [
            [InlineKeyboardButton("📊 آمار دقیق ربات شما", callback_data="res_adm_stats")],
            [
                InlineKeyboardButton("💰 خرید شارژ و بسته پنل", callback_data="res_adm_bundles"),
                InlineKeyboardButton("📨 مدیریت تیکت‌ها", callback_data="res_adm_tickets"),
            ],
            [
                InlineKeyboardButton("💳 مدیریت پرداخت‌ها و فیش‌ها", callback_data="res_adm_payments"),
                InlineKeyboardButton("👤 ساخت مشتری جدید", callback_data="res_adm_create_user"),
            ],
            [
                InlineKeyboardButton("🔄 تمدید مشتری (جستجو)", callback_data="res_adm_renew_user"),
                InlineKeyboardButton("🎁 کدهای تخفیف", callback_data="res_adm_discounts"),
            ],
            [
                InlineKeyboardButton("📈 گزارشات کاربردی", callback_data="res_adm_reports"),
                InlineKeyboardButton("📢 ارسال پیام همگانی", callback_data="res_adm_broadcast"),
            ],
            [
                InlineKeyboardButton("⚙️ وضعیت درگاه‌ها و تایید خودکار", callback_data="res_adm_settings"),
            ],
            [
                InlineKeyboardButton("🔙 بازگشت به منوی کاربری", callback_data=back_callback),
            ]
        ]
    return InlineKeyboardMarkup(keyboard)


def get_reseller_bundles_payload(reseller_id: int) -> Tuple[str, InlineKeyboardMarkup]:
    """نمایش بسته‌های شارژ و اعتبار عمده برای پنل نمایندگی"""
    r_stats = db.get_reseller_stats(reseller_id) or {}
    balance = r_stats.get("balance", 0)
    bundles = db.get_reseller_credit_bundles(active_only=True)
    
    text = (
        f"💰 **خرید شارژ و بسته اعتباری پنل نمایندگی**\n\n"
        f"💼 موجودی فعلی کیف پول شما: **{balance:,} تومان**\n\n"
        f"با خرید بسته‌های اعتباری زیر از **درصد بونوس شارژ هدیه** بهره‌مند شوید. "
        f"پس از انتخاب بسته، شماره کارت بانکی مدیریت به شما نمایش داده می‌شود تا فیش واریزی خود را ثبت فرمایید:\n"
    )
    
    buttons = []
    for b in bundles:
        b_id = b["id"]
        title = b.get("title", "بسته اعتباری")
        price = b.get("price", 0)
        credit = b.get("credit", price)
        bonus = b.get("bonus_percent", 0)
        badge = f" (+{bonus}٪ هدیه)" if bonus > 0 else ""
        btn_txt = f"📦 {title}: {price:,} ت ⬅️ {credit:,} ت اعتبار{badge}"
        buttons.append([InlineKeyboardButton(btn_txt, callback_data=f"res_adm_bdl_{b_id}")])
        
    buttons.append([InlineKeyboardButton("🔙 بازگشت به پنل مدیریت", callback_data="res_adm_menu")])
    return text, InlineKeyboardMarkup(buttons)


def get_bundle_payment_methods_payload(bundle_id: str, reseller_id: int) -> Tuple[str, InlineKeyboardMarkup]:
    """نمایش منوی انتخاب روش پرداخت فعال برای بسته شارژ نماینده (آنلاین، کارت هوشمند پیامکی، کارت دستی)"""
    bundle = db.get_reseller_credit_bundle(bundle_id)
    if not bundle:
        bundles = {b["id"]: b for b in db.get_reseller_credit_bundles()}
        bundle = bundles.get(bundle_id)
        
    if not bundle:
        return "❌ بسته مورد نظر یافت نشد.", InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="res_adm_bundles")]])
        
    price = bundle.get("price", 0)
    credit = bundle.get("credit", price)
    title = bundle.get("title", "بسته اعتباری")
    bonus = bundle.get("bonus_percent", 0)
    bonus_txt = f" (+{bonus}٪ شارژ هدیه)" if bonus > 0 else ""

    admin_gw = db.get_admin_gateway()
    has_online = bool(admin_gw.get("enabled") and admin_gw.get("key"))
    gw_name = "بلوپال" if admin_gw.get("type") == "blupal" else ("زرین‌پال" if admin_gw.get("type") == "zarinpal" else "درگاه آنلاین شتابی")

    admin_sms_cfg = db.get_admin_bank_sms_config()
    admin_cards = db.get_active_bank_cards()
    has_sms = bool(admin_sms_cfg.get("enabled") and admin_cards)

    text = f"""💰 **انتخاب روش پرداخت برای شارژ پنل نمایندگی**

📦 **بسته انتخابی:** {title}
💵 **مبلغ قابل پرداخت:** **{price:,} تومان**
🎁 **اعتبار دریافتی در پنل:** **{credit:,} تومان**{bonus_txt}

لطفاً یکی از روش‌های پرداخت فعال زیر را جهت شارژ پنل انتخاب فرمایید:
"""
    buttons = []
    if has_online:
        buttons.append([InlineKeyboardButton(f"💳 پرداخت آنلاین شتابی ({gw_name})", callback_data=f"res_adm_bdl_onl_{bundle_id}")])
    if has_sms:
        buttons.append([InlineKeyboardButton("⚡ کارت‌به‌کارت هوشمند (تایید خودکار با پیامک)", callback_data=f"res_adm_bdl_sms_{bundle_id}")])
    buttons.append([InlineKeyboardButton("📝 کارت‌به‌کارت سنتی (ارسال فیش واریزی)", callback_data=f"res_adm_bdl_card_{bundle_id}")])
    buttons.append([InlineKeyboardButton("🔙 بازگشت به لیست بسته‌ها", callback_data="res_adm_bundles")])

    return text, InlineKeyboardMarkup(buttons)


def get_bundle_smart_sms_payload(bundle_id: str, reseller_id: int) -> Tuple[str, InlineKeyboardMarkup]:
    """صدور فاکتور هوشمند با ارقام خرد و تایید خودکار پیامک بانک برای بسته شارژ نماینده"""
    bundle = db.get_reseller_credit_bundle(bundle_id)
    if not bundle:
        bundles = {b["id"]: b for b in db.get_reseller_credit_bundles()}
        bundle = bundles.get(bundle_id)
        
    if not bundle:
        return "❌ بسته مورد نظر یافت نشد.", InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="res_adm_bundles")]])
        
    admin_cards = db.get_active_bank_cards()
    if not admin_cards:
        return "❌ در حال حاضر هیچ کارت بانکی فعالی برای مدیریت ثبت نشده است.", InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data=f"res_adm_bdl_{bundle_id}")]])

    target_card = admin_cards[0]
    price = bundle["price"]
    sms_cfg = db.get_admin_bank_sms_config()
    digits = sms_cfg.get("digits", 3) if isinstance(sms_cfg, dict) else 3
    timeout = sms_cfg.get("timeout", 20) if isinstance(sms_cfg, dict) else 20

    invoice = db.create_smart_invoice(
        sub_id=0,
        plan_id=bundle_id,
        reseller_id=0,
        base_amount=price,
        target_card=target_card,
        digits=digits,
        timeout_minutes=timeout,
        instant_activation=True
    )

    now_iso = get_now_iso()
    reseller = db.get_reseller(reseller_id) or {}
    username = reseller.get("username", f"reseller_{reseller_id}")

    conn = db.get_connection()
    conn.execute("""
        INSERT OR REPLACE INTO transactions (
            order_id, user_id, username, plan_name, amount, status, gateway,
            tracking_code, reseller_id, is_renewal, account_name, source, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, 'pending', 'bundle_reseller', ?, ?, 0, ?, 'reseller_bot', ?, ?)
    """, (
        invoice["order_id"], reseller.get("telegram_id") or reseller_id, username,
        f"بسته {bundle['title']}", invoice["final_amount"],
        f"کارت {target_card.get('card_number', '')}", reseller_id,
        username, now_iso, now_iso
    ))
    conn.commit()
    conn.close()

    raw_c = re.sub(r"\D", "", str(target_card.get("card_number") or ""))
    holder = target_card.get("card_holder") or "مدیریت"
    bank = target_card.get("bank_name") or "بانک"
    final_amt = invoice["final_amount"]

    text = f"""⚡ **کارت‌به‌کارت هوشمند با تایید خودکار (پیامک بانک)**

📦 **بسته:** {bundle.get('title')}
💰 **مبلغ دقیق واریزی (شامل ارقام خرد هوشمند):**
👉 **`{final_amt:,}` تومان** 👈

💳 **شماره کارت مقصد (مدیریت):**
`{raw_c}`
👤 به نام: **{holder}** | بانک: **{bank}**
⏳ مهلت واریز: **{timeout} دقیقه**

⚠️ **نکات بسیار مهم:**
۱. حتماً مبلغ را **دقیقاً به میزان `{final_amt:,}` تومان** (با ارقام خرد انتهایی) انتقال دهید.
۲. سامانه به محض دریافت پیامک واریز از بانک مقصد، **به صورت خودکار و در لحظه** کیف پول پنل شما را شارژ خواهد نمود و نیازی به ارسال فیش نیست!
"""
    buttons = [
        [InlineKeyboardButton("📋 کپی شماره کارت", copy_text=CopyTextButton(raw_c))],
        [InlineKeyboardButton("📋 کپی مبلغ دقیق", copy_text=CopyTextButton(str(final_amt)))],
        [InlineKeyboardButton("🔄 استعلام وضعیت شارژ", callback_data="res_adm_menu")],
        [InlineKeyboardButton("🔙 بازگشت به روش‌های پرداخت", callback_data=f"res_adm_bdl_{bundle_id}")]
    ]
    return text, InlineKeyboardMarkup(buttons)


def get_bundle_payment_details_payload(bundle_id: str, reseller_id: int) -> Tuple[str, InlineKeyboardMarkup]:
    """نمایش مشخصات پرداخت کارت به کارت دستی برای بسته شارژ نماینده"""
    bundle = db.get_reseller_credit_bundle(bundle_id)
    if not bundle:
        bundles = {b["id"]: b for b in db.get_reseller_credit_bundles()}
        bundle = bundles.get(bundle_id)
        
    if not bundle:
        return "❌ بسته مورد نظر یافت نشد.", InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="res_adm_bundles")]])
        
    price = bundle.get("price", 0)
    credit = bundle.get("credit", price)
    title = bundle.get("title", "بسته اعتباری")
    bonus = bundle.get("bonus_percent", 0)
    
    # کارت فعال مدیریت
    admin_cards = db.get_active_bank_cards()
    if not admin_cards:
        primary_card = {
            "card_number": db.get_setting("admin_card_number") or "در حال حاضر ثبت نشده",
            "card_holder": db.get_setting("admin_card_holder") or "مدیریت",
            "bank_name": db.get_setting("admin_bank_name") or "بانک"
        }
    else:
        primary_card = admin_cards[0]
        
    raw_c = re.sub(r"\D", "", str(primary_card.get("card_number") or ""))
    holder = primary_card.get("card_holder") or "مدیریت"
    bank = primary_card.get("bank_name") or "بانک"
    
    text = f"""📝 **اطلاعات واریز کارت‌به‌کارت دستی جهت شارژ پنل نمایندگی**

📦 **بسته انتخابی:** {title}
💰 **مبلغ قابل واریز:** **{price:,} تومان**
🎁 **اعتبار دریافتی در پنل:** **{credit:,} تومان** ({bonus}٪ شارژ هدیه)

💳 **شماره کارت مقصد (مدیریت):**
`{raw_c}`
👤 به نام: **{holder}**
🏦 بانک: **{bank}**

⚠️ **راهنمای ثبت پرداخت:**
۱. مبلغ دقیق را به شماره کارت بالا واریز فرمایید.
۲. سپس دکمه **«📸 ارسال تصویر فیش واریزی»** را بزنید و عکس یا کد رهگیری را بفرستید.
به محض بررسی و تایید توسط مدیریت، کیف پول پنل شما شارژ خواهد شد.
"""
    buttons = [
        [InlineKeyboardButton("📋 کپی شماره کارت", copy_text=CopyTextButton(raw_c))],
        [InlineKeyboardButton("📸 ارسال تصویر فیش واریزی", callback_data=f"res_adm_send_rcpt_{bundle_id}")],
        [InlineKeyboardButton("🔙 بازگشت به روش‌های پرداخت", callback_data=f"res_adm_bdl_{bundle_id}")]
    ]
    return text, InlineKeyboardMarkup(buttons)


def get_reseller_tickets_payload(reseller_id: int) -> Tuple[str, InlineKeyboardMarkup]:
    """نمایش لیست تیکت‌های باز مشتریان نماینده"""
    tickets = db.get_tickets(reseller_id=reseller_id, category="customers", status="open")
    if not tickets:
        text = "📨 **مدیریت تیکت‌های پشتیبانی**\n\n✅ در حال حاضر هیچ تیکت باز یا در انتظاری از مشتریان شما وجود ندارد."
        buttons = [
            [InlineKeyboardButton("📋 تیکت‌های پاسخ‌داده‌شده", callback_data="res_adm_tkts_replied")],
            [InlineKeyboardButton("🔙 بازگشت به پنل مدیریت", callback_data="res_adm_menu")]
        ]
        return text, InlineKeyboardMarkup(buttons)
        
    text = f"📨 **تیکت‌های باز مشتریان ({len(tickets)} تیکت):**\n\nبرای مشاهده پیام و ارسال پاسخ روی تیکت کلیک نمایید:\n"
    buttons = []
    for t in tickets[:10]:
        t_id = t["id"]
        subj = t.get("subject") or "بدون عنوان"
        u_name = t.get("user_username") or t.get("telegram_id") or "کاربر"
        vip_tag = "⭐️ " if t.get("is_vip") else ""
        btn_txt = f"{vip_tag}#{t_id} | {u_name}: {subj[:25]}"
        buttons.append([InlineKeyboardButton(btn_txt, callback_data=f"res_adm_tkt_{t_id}")])
        
    buttons.append([InlineKeyboardButton("🔙 بازگشت به پنل مدیریت", callback_data="res_adm_menu")])
    return text, InlineKeyboardMarkup(buttons)


def get_reseller_ticket_detail_payload(ticket_id: int, reseller_id: int) -> Tuple[str, InlineKeyboardMarkup]:
    """نمایش جزئیات یک تیکت و پیام‌های ردوبدل شده"""
    ticket = db.get_ticket(ticket_id)
    if not ticket or int(ticket.get("reseller_id") or 0) != int(reseller_id):
        return "❌ تیکت یافت نشد یا متعلق به شما نیست.", InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="res_adm_tickets")]])
        
    messages = db.get_ticket_messages(ticket_id)
    u_id = ticket.get("telegram_id") or ticket.get("user_id")
    subj = ticket.get("subject") or "تیکت"
    st = ticket.get("status")
    st_fa = "🟢 باز" if st == "open" else ("🟡 پاسخ داده شده" if st == "replied" else "🔒 بسته")
    
    text = f"📨 **تیکت شماره #{ticket_id}**\n"
    text += f"👤 مشتری: `{u_id}` | وضعیت: {st_fa}\n"
    text += f"🔖 موضوع: **{subj}**\n"
    text += "────────────────────\n\n"
    
    for m in messages[-6:]:
        sender = "👤 مشتری" if m.get("sender_type") == "user" else "🎧 شما (پشتیبانی)"
        msg_txt = html.escape(str(m.get("message") or ""))
        text += f"**{sender}:**\n{msg_txt}\n\n"
        
    buttons = [
        [
            InlineKeyboardButton("✍️ ارسال پاسخ متنی", callback_data=f"res_reply_tkt_{ticket_id}"),
            InlineKeyboardButton("⚡ پاسخ‌های آماده", callback_data=f"res_canned_tkt_{ticket_id}")
        ],
        [
            InlineKeyboardButton("🔒 بستن تیکت", callback_data=f"res_close_tkt_{ticket_id}"),
            InlineKeyboardButton("🔙 بازگشت به لیست", callback_data="res_adm_tickets")
        ]
    ]
    return text, InlineKeyboardMarkup(buttons)


def get_reseller_payments_payload(reseller_id: int) -> Tuple[str, InlineKeyboardMarkup]:
    """نمایش فیش‌ها و پرداخت‌های معلق مشتریان برای تایید توسط نماینده"""
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM transactions 
        WHERE reseller_id = ? AND status = 'pending'
          AND (gateway != 'bundle_reseller' AND order_id NOT LIKE 'R_BUNDLE%')
          AND (is_deleted = 0 OR is_deleted IS NULL)
        ORDER BY id DESC LIMIT 10
    """, (reseller_id,))
    pending_txs = [dict(r) for r in cursor.fetchall()]
    conn.close()
    
    if not pending_txs:
        text = (
            "💳 **مدیریت پرداخت‌ها و فیش‌های مشتریان**\n\n"
            "✅ در حال حاضر هیچ فیش واریزی در انتظار بررسی وجود ندارد.\n"
            "پرداخت‌های آنلاین یا کارت به کارت هوشمند (پیامکی) به صورت خودکار تایید و فعال می‌شوند."
        )
        buttons = [
            [InlineKeyboardButton("📋 سوابق آخرین پرداخت‌های موفق", callback_data="res_adm_pay_recents")],
            [InlineKeyboardButton("🔙 بازگشت به پنل مدیریت", callback_data="res_adm_menu")]
        ]
        return text, InlineKeyboardMarkup(buttons)
        
    text = f"💳 **فیش‌های در انتظار بررسی ({len(pending_txs)} پرداخت):**\n\nروی هر سفارش کلیک کنید تا مشخصات و تصویر فیش را بررسی و تایید فرمایید:\n"
    buttons = []
    for tx in pending_txs:
        o_id = tx.get("order_id") or tx.get("id")
        pname = tx.get("plan_name") or "اشتراک"
        amt = tx.get("amount", 0)
        u_name = tx.get("username") or tx.get("user_id") or "مشتری"
        btn_txt = f"⏳ سفارش #{tx.get('id')} | {u_name} | {amt:,} ت"
        buttons.append([InlineKeyboardButton(btn_txt, callback_data=f"res_adm_pdetail_{o_id}")])
        
    buttons.append([InlineKeyboardButton("🔙 بازگشت به پنل مدیریت", callback_data="res_adm_menu")])
    return text, InlineKeyboardMarkup(buttons)


def get_reseller_create_user_plans_payload(reseller_id: int) -> Tuple[str, InlineKeyboardMarkup]:
    """انتخاب پلن جهت ساخت مشتری جدید توسط نماینده"""
    r_stats = db.get_reseller_stats(reseller_id) or {}
    balance = r_stats.get("balance", 0)
    power = r_stats.get("total_purchasing_power", balance)
    discount = r_stats.get("discount_percent", 20)
    
    plans = db.get_reseller_plans(reseller_id)
    if not plans:
        return "⚠️ پلن فعالی در پنل شما یافت نشد.", InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="res_adm_menu")]])
        
    text = f"""👤 **ساخت و صدور آنی اشتراک مشتری**

💼 موجودی کیف پول: **{balance:,} تومان**
📊 توان خرید با اعتبار: **{power:,} تومان**
🎁 نرخ تخفیف شما: **{discount}٪**

جهت ساخت اکانت، لطفاً یکی از پلن‌های زیر را انتخاب فرمایید (مبلغ عمده از کیف پول شما کسر خواهد شد):
"""
    buttons = []
    for p in plans:
        pid = p["plan_id"]
        pname = p.get("display_name") or p.get("master_name", "پلن")
        vol = p.get("data_limit", 30)
        days = p.get("duration", 30)
        w_price = p.get("wholesale_price", 0)
        vol_str = f"{vol}GB" if vol > 0 else "نامحدود"
        btn_txt = f"📦 {pname} ({vol_str} - {days}روز) 💰 عمده: {w_price:,} ت"
        buttons.append([InlineKeyboardButton(btn_txt, callback_data=f"res_adm_cplan_{pid}")])
        
    buttons.append([InlineKeyboardButton("🔙 بازگشت به پنل مدیریت", callback_data="res_adm_menu")])
    return text, InlineKeyboardMarkup(buttons)


def get_reseller_discounts_payload(reseller_id: int) -> Tuple[str, InlineKeyboardMarkup]:
    """نمایش و مدیریت کدهای تخفیف نماینده"""
    discounts = db.get_reseller_discount_codes(reseller_id)
    
    text = "🎁 **مدیریت کدهای تخفیف اختصاصی شما**\n\n"
    if not discounts:
        text += "شما هنوز هیچ کد تخفیفی ایجاد نکرده‌اید. با دکمه زیر می‌توانید کد تخفیف جدید برای مشتریان خود تعریف کنید:\n"
    else:
        text += "لیست کدهای تخفیف فعال شما:\n"
        for d in discounts[:8]:
            st = "🟢 فعال" if d.get("is_active") else "🔴 غیرفعال"
            pct = d.get("discount_percent", 0)
            amt = d.get("discount_amount", 0)
            val_txt = f"{pct}٪" if pct > 0 else f"{amt:,} ت"
            used = d.get("used_count", 0)
            max_u = d.get("max_uses", 0)
            max_txt = f"{max_u}" if max_u > 0 else "نامحدود"
            text += f"• کد: `{d.get('code')}` ({val_txt}) | استفاده: {used}/{max_txt} | {st}\n"
        text += "\n"
        
    buttons = [
        [InlineKeyboardButton("➕ ایجاد کد تخفیف جدید", callback_data="res_adm_disc_new")]
    ]
    
    # دکمه‌های خاموش/روشن کدهای موجود
    for d in discounts[:4]:
        d_id = d["id"]
        st_icon = "🔴 غیرفعال‌سازی" if d.get("is_active") else "🟢 فعال‌سازی"
        buttons.append([
            InlineKeyboardButton(f"{st_icon} {d.get('code')}", callback_data=f"res_adm_disctog_{d_id}"),
            InlineKeyboardButton("🗑 حذف", callback_data=f"res_adm_discdel_{d_id}")
        ])
        
    buttons.append([InlineKeyboardButton("🔙 بازگشت به پنل مدیریت", callback_data="res_adm_menu")])
    return text, InlineKeyboardMarkup(buttons)


def get_reseller_reports_payload(reseller_id: int, report_type: str = "menu") -> Tuple[str, InlineKeyboardMarkup]:
    """تولید گزارشات کاربردی برای نماینده"""
    conn = db.get_connection()
    cursor = conn.cursor()
    
    if report_type == "sales":
        now_dt = get_now_naive()
        today_str = now_dt.strftime("%Y-%m-%d")
        yesterday_str = (now_dt - timedelta(days=1)).strftime("%Y-%m-%d")
        month_ago_str = (now_dt - timedelta(days=30)).strftime("%Y-%m-%d")
        
        # فروش امروز
        cursor.execute("""
            SELECT COUNT(*), COALESCE(SUM(amount), 0) FROM transactions
            WHERE reseller_id = ? AND status IN ('approved', 'completed')
              AND created_at LIKE ? AND (gateway != 'bundle_reseller' AND order_id NOT LIKE 'R_BUNDLE%')
        """, (reseller_id, f"{today_str}%"))
        t_today = cursor.fetchone()
        
        # فروش دیروز
        cursor.execute("""
            SELECT COUNT(*), COALESCE(SUM(amount), 0) FROM transactions
            WHERE reseller_id = ? AND status IN ('approved', 'completed')
              AND created_at LIKE ? AND (gateway != 'bundle_reseller' AND order_id NOT LIKE 'R_BUNDLE%')
        """, (reseller_id, f"{yesterday_str}%"))
        t_yest = cursor.fetchone()
        
        # فروش ۳۰ روز اخیر
        cursor.execute("""
            SELECT COUNT(*), COALESCE(SUM(amount), 0) FROM transactions
            WHERE reseller_id = ? AND status IN ('approved', 'completed')
              AND created_at >= ? AND (gateway != 'bundle_reseller' AND order_id NOT LIKE 'R_BUNDLE%')
        """, (reseller_id, month_ago_str))
        t_month = cursor.fetchone()
        conn.close()
        
        text = f"""📊 **گزارش جامع فروش و درآمد شما**

📅 **فروش امروز ({today_str}):**
• تعداد فروش: **{t_today[0] or 0} عدد**
• مبلغ کل فروش: **{(t_today[1] or 0):,} تومان**

📅 **فروش دیروز ({yesterday_str}):**
• تعداد فروش: **{t_yest[0] or 0} عدد**
• مبلغ کل: **{(t_yest[1] or 0):,} تومان**

📈 **فروش ۳۰ روز اخیر:**
• تعداد کل: **{t_month[0] or 0} اشتراک**
• مجموع فروش ناخالص: **{(t_month[1] or 0):,} تومان**
"""
        buttons = [
            [InlineKeyboardButton("⏳ گزارش مشترکین رو به انقضا", callback_data="res_adm_rep_expiring")],
            [InlineKeyboardButton("📈 گزارش پرمصرف‌ترین مشترکین", callback_data="res_adm_rep_top")],
            [InlineKeyboardButton("🔙 بازگشت به منوی گزارشات", callback_data="res_adm_reports")]
        ]
        return text, InlineKeyboardMarkup(buttons)
        
    elif report_type == "expiring":
        # مشترکینی که کمتر از ۳ روز یا کمتر از ۲ گیگ دارند
        cursor.execute("""
            SELECT id, account_name, telegram_id, data_limit, data_used, duration, expire_date, status
            FROM subscriptions 
            WHERE reseller_id = ? AND status = 'active'
              AND (is_deleted = 0 OR is_deleted IS NULL)
            ORDER BY data_limit - data_used ASC LIMIT 8
        """, (reseller_id,))
        subs = cursor.fetchall()
        conn.close()
        
        text = "⏳ **مشترکین در آستانه اتمام حجم یا زمان (جهت تمدید):**\n\n"
        buttons = []
        if not subs:
            text += "✅ در حال حاضر هیچ اشتراکی در وضعیت اضطراری قرار ندارد."
        else:
            for s in subs:
                s_id = s["id"]
                name = s.get("account_name") or f"sub_{s_id}"
                used = round(s.get("data_used", 0), 1)
                lim = round(s.get("data_limit", 0), 1)
                rem = max(0.0, round(lim - used, 1))
                text += f"• **{name}**: باقیمانده {rem}GB از {lim}GB\n"
                buttons.append([InlineKeyboardButton(f"🔄 تمدید سریع «{name}»", callback_data=f"res_adm_rsub_{s_id}")])
                
        buttons.append([InlineKeyboardButton("🔙 بازگشت به منوی گزارشات", callback_data="res_adm_reports")])
        return text, InlineKeyboardMarkup(buttons)
        
    elif report_type == "top":
        # پرمصرف‌ترین مشترکین
        cursor.execute("""
            SELECT id, account_name, data_used, data_limit, status
            FROM subscriptions
            WHERE reseller_id = ? AND (is_deleted = 0 OR is_deleted IS NULL)
            ORDER BY data_used DESC LIMIT 6
        """, (reseller_id,))
        subs = cursor.fetchall()
        conn.close()
        
        text = "📈 **پرمصرف‌ترین مشترکین شما (بیشترین حجم مصرفی):**\n\n"
        for i, s in enumerate(subs, 1):
            name = s.get("account_name") or f"sub_{s['id']}"
            used = round(s.get("data_used", 0), 1)
            lim = round(s.get("data_limit", 0), 1)
            pct = int((used / lim) * 100) if lim > 0 else 0
            text += f"{i}. **{name}**: {used} GB ({pct}٪ از {lim} GB)\n"
            
        buttons = [
            [InlineKeyboardButton("📊 گزارش فروش و درآمد", callback_data="res_adm_rep_sales")],
            [InlineKeyboardButton("🔙 بازگشت به منوی گزارشات", callback_data="res_adm_reports")]
        ]
        return text, InlineKeyboardMarkup(buttons)
        
    else:
        conn.close()
        text = """📈 **مرکز گزارشات تحلیلی و کاربردی نماینده**

لطفاً نوع گزارش مدنظر خود را انتخاب فرمایید:
"""
        buttons = [
            [InlineKeyboardButton("📊 گزارش فروش و درآمد (امروز/ماه)", callback_data="res_adm_rep_sales")],
            [InlineKeyboardButton("⏳ مشترکین رو به انقضا (نیاز به تمدید)", callback_data="res_adm_rep_expiring")],
            [InlineKeyboardButton("📈 پرمصرف‌ترین مشتریان شما", callback_data="res_adm_rep_top")],
            [InlineKeyboardButton("🔙 بازگشت به پنل مدیریت", callback_data="res_adm_menu")]
        ]
        return text, InlineKeyboardMarkup(buttons)


def get_reseller_settings_payload(reseller_id: int) -> Tuple[str, InlineKeyboardMarkup]:
    """نمایش وضعیت تنظیمات پرداخت، کارت‌ها، درگاه آنلاین و تایید خودکار پیامکی نماینده"""
    cards = db.get_reseller_cards(reseller_id)
    active_cards = [c for c in cards if c.get("is_active")]
    gw = db.get_reseller_gateway(reseller_id)
    sms_cfg = db.get_reseller_bank_sms_config(reseller_id)
    r_info = db.get_reseller(reseller_id) or {}
    
    domain = r_info.get("custom_domain") or db.get_setting("custom_domain") or os.getenv("PANEL_DOMAIN", "http://localhost:5000")
    if not str(domain).startswith("http"):
        domain = f"https://{domain}"
    webhook_url = f"{str(domain).rstrip('/')}/api/bank-sms/webhook?token={sms_cfg['token']}"
    
    c_txt = ""
    if not active_cards:
        if r_info.get("card_number"):
            c_txt = f"• `{r_info.get('card_number')}` ({r_info.get('card_holder') or ''} - {r_info.get('bank_name') or ''})\n"
        else:
            c_txt = "⚠️ هیچ کارت بانکی فعالی ثبت نشده است.\n"
    else:
        for c in active_cards:
            c_txt += f"• `{c.get('card_number')}` ({c.get('card_holder')} - {c.get('bank_name')})\n"
            
    gw_status = "🟢 فعال" if (gw.get("enabled") and gw.get("key")) else "⚪️ غیرفعال"
    gw_type = gw.get("type", "zarinpal").upper()
    
    sms_st = "🟢 فعال (آماده دریافت پیامک و تایید آنی)" if sms_cfg.get("enabled") else "⚪️ غیرفعال"
    
    text = f"""⚙️ **وضعیت تنظیمات پرداخت و ربات شما**

💳 **کارت‌های بانکی مقصد شما:**
{c_txt}
🌐 **درگاه پرداخت آنلاین اختصاصی:**
• وضعیت: {gw_status} | نوع: {gw_type}

⚡ **تایید خودکار کارت به کارت (پیامک بانک):**
• وضعیت: {sms_st}
• ارقام خرد یکتا: **{sms_cfg.get('digits', 3)} رقمی**
• مهلت پرداخت فاکتور: **{sms_cfg.get('timeout', 15)} دقیقه**

🔗 **آدرس وب‌هوک پیامک اختصاصی شما:**
`{webhook_url}`

💡 **نحوه مدیریت و ویرایش:**
کلیه تنظیمات کارت‌ها، درگاه آنلاین، ارقام خرد و توکن پیامک بانک از طریق بخش **«تنظیمات پرداخت»** در پنل وب شما قابل ویرایش است. ربات شما به صورت مستقیم به تنظیمات پنل متصل بوده و آخرین تغییرات را دریافت می‌کند.
"""
    buttons = [
        [InlineKeyboardButton("📋 کپی آدرس وب‌هوک پیامک", copy_text=CopyTextButton(webhook_url))],
        [InlineKeyboardButton("🔙 بازگشت به پنل مدیریت", callback_data="res_adm_menu")]
    ]
    return text, InlineKeyboardMarkup(buttons)


def search_reseller_subscriptions(reseller_id: int, query_text: str) -> List[dict]:
    """جستجوی اشتراک‌های مشتریان نماینده بر اساس نام، تلفن، آیدی تلگرام یا شناسه"""
    q = query_text.strip()
    if not q:
        return []
        
    conn = db.get_connection()
    cursor = conn.cursor()
    try:
        like_q = f"%{q}%"
        is_digit = q.isdigit()
        sub_id_val = int(q) if is_digit else 0
        
        cursor.execute("""
            SELECT id, account_name, telegram_id, phone_number, plan_name, data_limit, data_used, duration, status, expire_date
            FROM subscriptions 
            WHERE reseller_id = ? 
              AND (account_name LIKE ? OR phone_number LIKE ? OR telegram_id LIKE ? OR id = ?)
              AND (is_deleted = 0 OR is_deleted IS NULL)
            ORDER BY id DESC LIMIT 8
        """, (reseller_id, like_q, like_q, like_q, sub_id_val))
        return [dict(r) for r in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Error searching reseller subscriptions: {e}")
        return []
    finally:
        conn.close()
