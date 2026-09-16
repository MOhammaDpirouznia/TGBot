#!/usr/bin/env python3
"""
🚀 ربات فروش بسته نمایندگی (Reseller Bundle Sales Bot)
ربات اختصاصی مدیریت و فروش بسته‌های شارژ و اعتبار برای نمایندگان فروش:
- منوی اختصاصی نمایندگان: خرید بسته، شارژ با بونوس هدیه، ثبت فیش، درگاه آنلاین، کریپتو
- پنل مدیریت پیشرفته برای مدیران: بررسی و تایید آنی فیش‌ها، آمار بسته‌ها، شارژ مستقیم، پیام همگانی، کدهای تخفیف
"""

import os
import sys
import json
import html
import re
import random
import logging
import asyncio
import threading
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Tuple
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
    Bot,
    CopyTextButton
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)

from database import db
from utils import get_now_iso, get_now_naive, gregorian_to_shamsi
from admin_bot_admin import (
    get_admin_advanced_stats_text,
    get_admin_advanced_keyboard,
    get_admin_discounts_payload,
    get_admin_payments_payload,
    get_admin_reports_payload,
    get_admin_settings_overview_payload
)

logger = logging.getLogger("bundle_sales_bot")
logger.setLevel(logging.INFO)

ADMIN_ID = int(os.getenv("ADMIN_ID", "0") or 0)


def is_user_super_admin(user_id: int) -> bool:
    """بررسی دسترسی مدیریت ارشد و مدیران دارای مجوز ربات فروش بسته"""
    admin_tid = db.get_setting("admin_telegram_id")
    if ADMIN_ID and user_id == ADMIN_ID:
        return True
    if admin_tid and str(user_id) == str(admin_tid):
        return True
    try:
        mgr = db.get_admin_manager_by_telegram_id_for_bundle(user_id)
        if mgr:
            return True
    except Exception as e:
        logger.error(f"Error checking bundle manager for user {user_id}: {e}")
    return False


def get_reseller_for_user(user_id: int) -> Optional[dict]:
    """یافتن نماینده متصل به این شناسه تلگرام"""
    reseller = db.get_reseller_by_telegram_id(user_id)
    if reseller:
        return reseller
    # بررسی در ادمین‌های ربات‌های نمایندگان
    is_r_adm, r_id, _ = db.is_telegram_user_any_reseller_admin(user_id)
    if is_r_adm and r_id:
        return db.get_reseller(r_id)
    return None


def get_bundle_sales_main_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """کیبورد اصلی صفحه اول برای نماینده با چیدمان و رنگ‌های داینامیک از پنل مدیریت"""
    is_admin = is_user_super_admin(user_id)
    try:
        menu_rows = db.get_bundle_bot_menu_keyboard_rows(is_admin=is_admin)
    except Exception:
        menu_rows = None

    keyboard = []
    if menu_rows:
        cb_map = {
            "bsb_bundles": "bsb_bundles",
            "bsb_wallet": "bsb_wallet",
            "bsb_history": "bsb_history",
            "bsb_discount": "bsb_discount",
            "bsb_support": "bsb_support",
            "bsb_admin_menu": "bsb_admin_menu",
        }
        for row in menu_rows:
            row_btns = []
            for b in row:
                b_id = b.get("id")
                title = b.get("title")
                cb = cb_map.get(b_id, b_id)
                b_style = b.get("style")
                style_arg = b_style if b_style in ("primary", "success", "danger") else None
                btn_kwargs = {}
                if style_arg:
                    btn_kwargs["style"] = style_arg
                row_btns.append(InlineKeyboardButton(title, callback_data=cb, **btn_kwargs))
            if row_btns:
                keyboard.append(row_btns)

    if not keyboard:
        keyboard = [
            [InlineKeyboardButton("📦 مشاهده و خرید بسته‌های اعتباری", callback_data="bsb_bundles", style="success")],
            [
                InlineKeyboardButton("💼 وضعیت موجودی و کیف پول", callback_data="bsb_wallet", style="primary"),
                InlineKeyboardButton("🧾 سوابق خریدهای من", callback_data="bsb_history")
            ],
            [
                InlineKeyboardButton("🎟️ ثبت کد تخفیف بسته", callback_data="bsb_discount"),
                InlineKeyboardButton("🎧 ارتباط و پشتیبانی مدیریت", callback_data="bsb_support")
            ]
        ]
        if is_admin:
            keyboard.append([InlineKeyboardButton("🔧 ورود به پنل مدیریت فروش بسته‌ها", callback_data="bsb_admin_menu", style="danger")])
    return InlineKeyboardMarkup(keyboard)


# ═══════════════════════════════════════════════════════════════
# سیستم بررسی عضویت اجباری در کانال‌ها برای ربات فروش بسته
# ═══════════════════════════════════════════════════════════════

async def check_bundle_channel_membership(user_id: int, bot: Bot) -> Tuple[bool, List[dict]]:
    """بررسی عضویت کاربر در کانال‌های اجباری ربات فروش بسته"""
    channels = db.get_mandatory_channels("bundle")
    if not channels:
        return True, []

    not_joined = []
    for ch in channels:
        if not ch.get("is_active", True):
            continue
        cid = ch.get("channel_id")
        if not cid:
            continue
        try:
            chat_id = int(cid) if str(cid).lstrip("-").isdigit() else str(cid)
            member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
            if member.status not in ["member", "administrator", "creator"]:
                not_joined.append(ch)
        except Exception as e:
            logger.warning(f"Bundle bot membership check failed for {cid}: {e}")
            pass
    return len(not_joined) == 0, not_joined


async def show_bundle_join_channels_message(update: Update, context: ContextTypes.DEFAULT_TYPE, not_joined: List[dict]):
    """نمایش پیام شیک عضویت در کانال‌های اجباری برای ربات فروش بسته"""
    text = "🔒 **همکار گرامی، جهت استفاده از خدمات ربات فروش بسته‌های نمایندگی، لطفاً در کانال‌های زیر عضو شوید:**\n\n"
    keyboard = []
    for i, ch in enumerate(not_joined, 1):
        cid = ch["channel_id"]
        title = ch.get("title") or f"کانال {i}"
        link = ch.get("invite_link") or ""
        if not link and str(cid).startswith("@"):
            link = f"https://t.me/{str(cid).lstrip('@')}"
        elif not link:
            link = "https://t.me"

        text += f"{i}. **{title}**\n"
        keyboard.append([InlineKeyboardButton(f"📢 عضویت در {title}", url=link)])

    text += "\n✅ پس از عضویت در تمامی کانال‌ها، روی دکمه **«بررسی عضویت»** کلیک فرمایید."
    keyboard.append([InlineKeyboardButton("🔄 بررسی عضویت و ورود", callback_data="bsb_check_membership")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
        except Exception:
            await update.callback_query.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")


# ═══════════════════════════════════════════════════════════════
# هندلرهای اصلی ربات فروش بسته نمایندگی
# ═══════════════════════════════════════════════════════════════

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """فرمان /start در ربات فروش بسته نمایندگی"""
    user = update.effective_user
    brand = db.get_setting("bundle_brand_name") or "سامانه فروش بسته نمایندگی"

    # بررسی دسترسی ادمین کل
    if is_user_super_admin(user.id):
        text = f"""👑 **سلام مدیر محترم!**
به پنل اختصاصی **«ربات فروش بسته نمایندگی»** ({brand}) خوش آمدید.

از این بخش می‌توانید بسته‌های اعتباری نمایندگان را مدیریت کرده، فیش‌های واریزی را تایید فرمایید یا به نمایندگان پیام همگانی ارسال کنید:
"""
        reply_markup = get_admin_advanced_keyboard(is_bundle_bot=True)
        if update.callback_query:
            await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
        else:
            await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")
        return

    # بررسی عضویت اجباری در کانال‌ها برای کاربران غیرادمین
    is_member, not_joined = await check_bundle_channel_membership(user.id, context.bot)
    if not is_member:
        await show_bundle_join_channels_message(update, context, not_joined)
        return

    # بررسی هویت نماینده
    reseller = get_reseller_for_user(user.id)
    if not reseller:
        text = f"""👋 **سلام {html.escape(user.first_name or 'همکار گرامی')}!**
به **ربات رسمی فروش بسته‌های شارژ و اعتبار نمایندگی** خوش آمدید.

⚠️ **حساب نمایندگی متصل نشد:**
اکانت تلگرام شما هنوز به پنل هیچ نماینده‌ای متصل نشده است.

🔑 **نحوه فعال‌سازی:**
لطفاً **نام کاربری نمایندگی** یا **شماره تماس ثبت‌شده** خود در پنل را همینجا ارسال فرمایید تا احراز هویت شما انجام گیرد.
"""
        buttons = [
            [InlineKeyboardButton("🎧 تماس با مدیریت جهت راه‌اندازی", url=f"https://t.me/{db.get_setting('admin_support_username') or 'support'}")]
        ]
        if update.callback_query:
            await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")
        else:
            await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")
        return


    # نماینده مجاز
    r_id = reseller["id"]
    r_name = reseller.get("name") or reseller.get("username") or f"نماینده #{r_id}"
    stats = db.get_reseller_stats(r_id) or {}
    balance = stats.get("balance", 0)
    purchasing_power = stats.get("total_purchasing_power", balance)
    custom_start = db.get_setting("bundle_start_message")

    text = custom_start or f"""🤝 **سلام نماینده گرامی، {r_name}!**
به **«ربات فروش بسته نمایندگی»** خوش آمدید.

💼 **وضعیت کیف پول و پنل شما:**
• شناسه نمایندگی: `{r_id}`
• موجودی نقدی کیف پول: **{balance:,} تومان**
• کل توان خرید (با اعتبار): **{purchasing_power:,} تومان**

🎁 با خرید بسته‌های پیش‌خرید اعتباری زیر، از **شارژ هدیه تا ۱۵٪ بونوس** بهره‌مند شوید:
"""
    reply_markup = get_bundle_sales_main_keyboard(user.id)
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")


async def bsb_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش کلیک روی دکمه‌های اینلاین ربات فروش بسته"""
    query = update.callback_query
    await query.answer()
    data = query.data
    user = update.effective_user

    if data == "bsb_main_menu":
        return await start_command(update, context)

    if data == "bsb_check_membership":
        is_member, not_joined = await check_bundle_channel_membership(user.id, context.bot)
        if is_member:
            await query.answer("✅ عضویت شما تایید شد.", show_alert=False)
            return await start_command(update, context)
        else:
            await query.answer("❌ شما هنوز در تمام کانال‌های اعلام‌شده عضو نشده‌اید!", show_alert=True)
            return await show_bundle_join_channels_message(update, context, not_joined)


    # ─── بسته‌های اعتباری نماینده ───
    if data == "bsb_bundles":
        reseller = get_reseller_for_user(user.id)
        r_id = reseller["id"] if reseller else 0
        bundles = db.get_reseller_credit_bundles(active_only=True)
        if not bundles:
            await query.edit_message_text(
                "❌ در حال حاضر بسته‌ای برای فروش تعریف نشده است. لطفاً بعداً مراجعه فرمایید.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="bsb_main_menu")]])
            )
            return

        text = "📦 **لیست بسته‌های شارژ و اعتبار نمایندگی:**\n\nبرای مشاهده جزئیات پرداخت روی بسته مورد نظر کلیک نمایید:\n"
        sub_cfg = db.get_sub_menu_config("bundle", "bundle_packages")
        sub_dict = {it.get("id"): it for it in sub_cfg if isinstance(it, dict)}

        row_map = {}
        for b in bundles:
            b_id = b.get("id")
            item_id = str(b_id) if str(b_id).startswith("bundle_") else f"bundle_{b_id}"
            cfg_it = sub_dict.get(item_id, {})
            if not cfg_it.get("enabled", True):
                continue

            st = cfg_it.get("style")
            st_arg = st if st in ("primary", "success", "danger") else None
            kw = {"style": st_arg} if st_arg else {}

            if cfg_it.get("title"):
                btn_txt = cfg_it["title"]
            else:
                title = b.get("title", "بسته اعتباری")
                price = b.get("price", 0)
                credit = b.get("credit", price)
                bonus = b.get("bonus_percent", 0)
                bonus_badge = f" (+{bonus}٪ هدیه)" if bonus > 0 else ""
                btn_txt = f"💎 {title}: {price:,} ت ⬅️ {credit:,} ت اعتبار{bonus_badge}"

            r = cfg_it.get("row", len(row_map))
            c = cfg_it.get("col", 0)
            if r not in row_map:
                row_map[r] = []
            row_map[r].append((c, InlineKeyboardButton(btn_txt, callback_data=f"bsb_buy_bdl_{b_id}", **kw)))

        back_it = sub_dict.get("back_to_main", {})
        if back_it.get("enabled", True):
            b_st = back_it.get("style", "danger")
            b_st_arg = b_st if b_st in ("primary", "success", "danger") else None
            b_kw = {"style": b_st_arg} if b_st_arg else {}
            b_title = back_it.get("title") or "🔙 بازگشت به منوی اصلی"
            r_back = back_it.get("row", 99)
            c_back = back_it.get("col", 0)
            if r_back not in row_map:
                row_map[r_back] = []
            row_map[r_back].append((c_back, InlineKeyboardButton(b_title, callback_data="bsb_main_menu", **b_kw)))

        buttons = []
        for r in sorted(row_map.keys()):
            row_btns = [btn for _, btn in sorted(row_map[r], key=lambda x: x[0])]
            if row_btns:
                buttons.append(row_btns)

        if not buttons:
            buttons = [[InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="bsb_main_menu")]]

        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")
        return

    # ─── انتخاب یک بسته خاص و روش‌های پرداخت ───
    if data.startswith("bsb_buy_bdl_"):
        bundle_id = data.replace("bsb_buy_bdl_", "")
        bundle = db.get_reseller_credit_bundle(bundle_id)
        if not bundle:
            await query.answer("❌ بسته یافت نشد!", show_alert=True)
            return

        price = bundle.get("price", 0)
        credit = bundle.get("credit", price)
        title = bundle.get("title", "بسته اعتباری")
        bonus = bundle.get("bonus_percent", 0)

        # دریافت کارت فعال مدیریت
        admin_cards = db.get_active_bank_cards()
        p_card = admin_cards[0] if admin_cards else {
            "card_number": db.get_setting("admin_card_number") or "0000000000000000",
            "card_holder": db.get_setting("admin_card_holder") or "مدیریت",
            "bank_name": db.get_setting("admin_bank_name") or "بانک"
        }
        raw_card = re.sub(r"\D", "", str(p_card.get("card_number") or ""))

        text = f"""💳 **مشخصات خرید {title}**

💰 مبلغ پرداختی: **{price:,} تومان**
🎁 اعتبار شارژ شده در کیف پول: **{credit:,} تومان** ({bonus}٪ بونوس هدیه)

💳 **اطلاعات کارت جهت واریز کارت‌به‌کارت:**
شماره کارت: `{raw_card}`
صاحب حساب: **{p_card.get('card_holder')}** ({p_card.get('bank_name')})

📸 **نحوه تکمیل خرید:**
پس از انتقال وجه به شماره کارت بالا، دکمه **«📸 ارسال تصویر فیش»** را لمس نموده و عکس رسید خود را ارسال نمایید.
"""
        context.user_data["pending_bundle_id"] = bundle_id

        copy_style = db.get_sub_menu_item_style("bundle", "bundle_payment", "copy_card", default="primary")
        receipt_style = db.get_sub_menu_item_style("bundle", "bundle_payment", "submit_receipt", default="success")
        cancel_style = db.get_sub_menu_item_style("bundle", "bundle_payment", "cancel", default="danger")

        b_cfg = db.get_sub_menu_dict("bundle", "bundle_payment")
        copy_title = b_cfg.get("copy_card", {}).get("title") or "📋 کپی شماره کارت"
        receipt_title = b_cfg.get("submit_receipt", {}).get("title") or "📸 ارسال تصویر فیش واریزی"
        cancel_title = b_cfg.get("cancel", {}).get("title") or "🔙 بازگشت به لیست بسته‌ها"

        btn_copy_kwargs = {"style": copy_style} if copy_style else {}
        btn_receipt_kwargs = {"style": receipt_style} if receipt_style else {}
        btn_cancel_kwargs = {"style": cancel_style} if cancel_style else {}

        buttons = [
            [InlineKeyboardButton(copy_title, copy_text=CopyTextButton(raw_card), **btn_copy_kwargs)],
            [InlineKeyboardButton(receipt_title, callback_data=f"bsb_submit_receipt_{bundle_id}", **btn_receipt_kwargs)],
            [InlineKeyboardButton(cancel_title, callback_data="bsb_bundles", **btn_cancel_kwargs)]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")
        return

    # ─── درخواست ارسال فیش ───
    if data.startswith("bsb_submit_receipt_"):
        bundle_id = data.replace("bsb_submit_receipt_", "")
        context.user_data["awaiting_bundle_receipt"] = bundle_id
        await query.edit_message_text(
            "📸 **لطفاً تصویر فیش واریزی یا شماره پیگیری خود را ارسال فرمایید:**\n\n(عکس یا متن حاوی کد پیگیری را در چت بفرستید)",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ انصراف", callback_data="bsb_bundles", style="danger")]])
        )
        return

    # ─── وضعیت کیف پول نماینده ───
    if data == "bsb_wallet":
        reseller = get_reseller_for_user(user.id)
        if not reseller:
            await query.answer("اطلاعات نماینده یافت نشد.", show_alert=True)
            return
        r_id = reseller["id"]
        stats = db.get_reseller_stats(r_id) or {}
        bal = stats.get("balance", 0)
        c_limit = stats.get("credit_limit", 0)
        c_debt = stats.get("credit_debt", 0)
        avail_c = max(0, c_limit - c_debt)

        text = f"""💼 **وضعیت کیف پول و توان خرید شما**

💰 **موجودی نقد:** **{bal:,} تومان**
💳 **اعتبار مجاز:** **{avail_c:,} تومان** (از کل سقف {c_limit:,} ت)
⚡ **کل توان خرید:** **{(bal + avail_c):,} تومان**

برای افزایش موجودی و دریافت بونوس هدیه، روی خرید بسته‌های اعتباری کلیک نمایید.
"""
        wal_cfg = db.get_sub_menu_dict("bundle", "bundle_wallet")
        buy_it = wal_cfg.get("buy_bundle", {})
        back_it = wal_cfg.get("back_to_main", {})

        buy_st = buy_it.get("style")
        buy_kw = {"style": buy_st} if buy_st in ("primary", "success", "danger") else {}
        buy_title = buy_it.get("title") or "📦 خرید و شارژ بسته"

        back_st = back_it.get("style")
        back_kw = {"style": back_st} if back_st in ("primary", "success", "danger") else {}
        back_title = back_it.get("title") or "🔙 بازگشت به منوی اصلی"

        buttons = []
        if buy_it.get("enabled", True):
            buttons.append([InlineKeyboardButton(buy_title, callback_data="bsb_bundles", **buy_kw)])
        if back_it.get("enabled", True):
            buttons.append([InlineKeyboardButton(back_title, callback_data="bsb_main_menu", **back_kw)])
        if not buttons:
            buttons = [[InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="bsb_main_menu")]]

        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")
        return

    # ─── سوابق خریدهای نماینده ───
    if data == "bsb_history":
        reseller = get_reseller_for_user(user.id)
        if not reseller:
            await query.answer("اطلاعات نماینده یافت نشد.", show_alert=True)
            return
        r_id = reseller["id"]
        conn = db.get_connection()
        rows = conn.execute("""
            SELECT * FROM transactions 
            WHERE reseller_id = ? AND (gateway = 'bundle_reseller' OR order_id LIKE 'R_BUNDLE%')
            ORDER BY id DESC LIMIT 6
        """, (r_id,)).fetchall()
        conn.close()

        if not rows:
            await query.edit_message_text(
                "🧾 هنوز هیچ فیش یا بسته‌ای توسط شما ثبت نشده است.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="bsb_main_menu")]])
            )
            return

        text = f"🧾 **سوابق خریدهای اخیر بسته‌های شما ({len(rows)} سفارش):**\n\n"
        for r in rows:
            p_name = r["plan_name"] or "بسته اعتباری"
            amt = r["amount"] or 0
            st = r["status"]
            st_badge = "🟢 تایید و شارژ شد" if st in ("approved", "completed") else ("⏳ در حال بررسی" if st == "pending" else "❌ رد شده")
            date_str = r.get("created_at", "")[:10]
            text += f"• **{p_name}** | {amt:,} ت | {st_badge} ({date_str})\n"

        buttons = [
            [InlineKeyboardButton("📦 خرید بسته جدید", callback_data="bsb_bundles")],
            [InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="bsb_main_menu")]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")
        return

    # ─── پشتیبانی ───
    if data == "bsb_support":
        supp_user = db.get_setting("bundle_support_username") or db.get_setting("admin_support_username") or "support"
        text = f"""🎧 **پشتیبانی و ارتباط مستقیم با مدیریت**

جهت پیگیری سفارشات، هماهنگی واریز مبالغ بالا یا دریافت راهنمایی می‌توانید مستقیماً با مدیریت در ارتباط باشید:
"""
        adm_chat_style = db.get_sub_menu_item_style("bundle", "bundle_support", "admin_chat", default="primary")
        back_style = db.get_sub_menu_item_style("bundle", "bundle_support", "back", default=None)
        bsup_cfg = db.get_sub_menu_dict("bundle", "bundle_support")
        adm_chat_title = bsup_cfg.get("admin_chat", {}).get("title") or "💬 پیام مستقیم به مدیریت"
        back_title = bsup_cfg.get("back", {}).get("title") or "🔙 بازگشت به منوی اصلی"

        btn_chat_kw = {"style": adm_chat_style} if adm_chat_style else {}
        btn_back_kw = {"style": back_style} if back_style else {}

        buttons = [
            [InlineKeyboardButton(adm_chat_title, url=f"https://t.me/{supp_user.lstrip('@')}", **btn_chat_kw)],
            [InlineKeyboardButton(back_title, callback_data="bsb_main_menu", **btn_back_kw)]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")
        return

    # ═══════════════════════════════════════════════════════════
    # بخش‌های پنل مدیریت پیشرفته در ربات فروش بسته
    # ═══════════════════════════════════════════════════════════
    if not is_user_super_admin(user.id):
        return

    if data in ("bsb_admin_menu", "adm_adv_menu"):
        text = "🔧 **پنل مدیریت ارشد ربات فروش بسته نمایندگی**\n\nلطفاً یکی از بخش‌های مدیریتی زیر را انتخاب فرمایید:"
        await query.edit_message_text(text, reply_markup=get_admin_advanced_keyboard(is_bundle_bot=True), parse_mode="Markdown")
        return

    if data == "adm_ai_menu" or data.startswith("ai_"):
        from ai_bot_handlers import handle_ai_bot_callback
        handled = await handle_ai_bot_callback(update, context, bot_type="bundle_sales", owner_id=0)
        if handled:
            return

    if data == "adm_adv_stats":
        stats_text = get_admin_advanced_stats_text()
        buttons = [
            [InlineKeyboardButton("🔄 بروزرسانی آمار", callback_data="adm_adv_stats")],
            [InlineKeyboardButton("🔙 بازگشت به منوی مدیریت", callback_data="bsb_admin_menu")]
        ]
        await query.edit_message_text(stats_text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")
        return

    if data == "adm_adv_discounts":
        text, markup = get_admin_discounts_payload()
        await query.edit_message_text(text, reply_markup=markup, parse_mode="Markdown")
        return

    if data == "adm_adv_reports":
        text, markup = get_admin_reports_payload()
        await query.edit_message_text(text, reply_markup=markup, parse_mode="Markdown")
        return

    if data == "adm_adv_settings":
        text, markup = get_admin_settings_overview_payload()
        await query.edit_message_text(text, reply_markup=markup, parse_mode="Markdown")
        return

    if data == "adm_adv_bundles":
        bundles = db.get_reseller_credit_bundles()
        text = "📦 **بسته‌های شارژ نمایندگی در سیستم:**\n\n"
        for b in bundles:
            title = b.get("title")
            price = b.get("price", 0)
            credit = b.get("credit", price)
            bonus = b.get("bonus_percent", 0)
            st = "🟢 فعال" if b.get("is_active", 1) else "⚪️ غیرفعال"
            text += f"• **{title}**: قیمت {price:,} ت | اعتبار {credit:,} ت (+{bonus}٪) [{st}]\n"
        buttons = [
            [InlineKeyboardButton("🔙 بازگشت به منوی مدیریت", callback_data="bsb_admin_menu")]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")
        return

    # ─── تایید یا رد فیش‌های بسته نماینده توسط مدیر ───
    if data.startswith("adm_b_app_"):
        tx_id = int(data.replace("adm_b_app_", ""))
        conn = db.get_connection()
        tx = conn.execute("SELECT * FROM transactions WHERE id = ?", (tx_id,)).fetchone()
        conn.close()
        if not tx:
            await query.answer("❌ تراکنش یافت نشد.", show_alert=True)
            return

        reseller_id = tx["reseller_id"]
        amount = tx["amount"]
        order_id = tx["order_id"]
        # پیدا کردن میزان اعتبار بسته
        bundle_id = tx.get("plan_name")
        bundle = db.get_reseller_credit_bundle(bundle_id)
        credit_amount = bundle.get("credit", amount) if bundle else amount

        # شارژ کیف پول نماینده
        db.charge_reseller_balance(reseller_id, credit_amount, reason=f"تایید فیش خرید بسته #{tx_id}")
        db.update_transaction_status(order_id, "approved")

        # ثبت در کارت پیش‌فرض یا صندوق
        default_acc = db.get_customer_default_account("admin", 0)
        if default_acc and default_acc.get("id"):
            try:
                db.add_card_transaction(
                    card_id=default_acc["id"],
                    owner_type="admin",
                    amount=amount,
                    tx_type="deposit",
                    category="فروش بسته نمایندگی",
                    title=f"واریز فیش بسته نماینده #{reseller_id}",
                    ref_type="bundle_sale",
                    ref_id=str(tx_id),
                    actor=str(user.id)
                )
            except Exception as e_c:
                logger.error(f"Error depositing to card on bundle approve: {e_c}")

        await query.edit_message_text(f"✅ فیش شماره #{tx_id} تایید شد و مبلغ {credit_amount:,} تومان به کیف پول نماینده افزوده گردید!")
        return

    if data.startswith("adm_b_rej_"):
        tx_id = int(data.replace("adm_b_rej_", ""))
        conn = db.get_connection()
        tx = conn.execute("SELECT * FROM transactions WHERE id = ?", (tx_id,)).fetchone()
        conn.close()
        if tx:
            db.update_transaction_status(tx["order_id"], "rejected")
        await query.edit_message_text(f"❌ فیش شماره #{tx_id} رد شد.")
        return


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش پیام‌های ارسالی کاربران و رسیدهای بانکی"""
    user = update.effective_user
    msg = update.message

    # اگر کاربر در حال ارسال تصویر فیش برای یک بسته باشد
    awaiting_bundle = context.user_data.get("awaiting_bundle_receipt")
    if awaiting_bundle:
        reseller = get_reseller_for_user(user.id)
        if not reseller:
            await msg.reply_text("❌ حساب نمایندگی شما یافت نشد.")
            context.user_data.pop("awaiting_bundle_receipt", None)
            return

        r_id = reseller["id"]
        bundle = db.get_reseller_credit_bundle(awaiting_bundle)
        price = bundle.get("price", 0) if bundle else 0
        bundle_title = bundle.get("title", awaiting_bundle) if bundle else awaiting_bundle
        order_id = f"R_BUNDLE_{r_id}_{get_now_naive().strftime('%Y%m%d%H%M%S')}"

        photo_id = None
        local_saved_fn = None
        receipts_dir = Path("data/receipts")
        receipts_dir.mkdir(parents=True, exist_ok=True)

        if msg.photo:
            photo_id = msg.photo[-1].file_id
            try:
                tg_file = await msg.photo[-1].get_file()
                saved_filename = f"receipt_{order_id}.jpg"
                save_dest = receipts_dir / saved_filename
                await tg_file.download_to_drive(custom_path=save_dest)
                local_saved_fn = saved_filename
            except Exception as e_dl:
                logger.warning(f"Error downloading bundle receipt photo to disk: {e_dl}")

        caption_text = msg.caption or msg.text or ""
        actor_name = f"{user.full_name or user.first_name}"
        if user.username:
            actor_name += f" (@{user.username})"
        actor_title = f"{actor_name} [شناسه {user.id}] (ربات تلگرام بسته‌ها)"

        # ثبت در جدول تراکنش‌ها
        db.save_transaction(
            order_id=order_id,
            user_id=user.id,
            username=reseller.get("name") or reseller.get("username") or f"نماینده #{r_id}",
            plan_name=bundle_title,
            amount=price,
            gateway="bundle_reseller",
            receipt_image=local_saved_fn or photo_id or "text_tracking",
            receipt_photo_id=photo_id,
            tracking_code=caption_text[:50] if caption_text else f"BUNDLE_{r_id}",
            status="pending",
            account_name=reseller.get("username"),
            source="bundle_sales_bot",
            reseller_id=r_id,
            created_by=actor_title,
            receipt_file_type="web_upload" if local_saved_fn else "telegram_photo"
        )

        context.user_data.pop("awaiting_bundle_receipt", None)

        conn = db.get_connection()
        last_tx = conn.execute("SELECT id FROM transactions WHERE order_id = ?", (order_id,)).fetchone()
        conn.close()
        tx_row_id = last_tx[0] if last_tx else 0

        # استخراج خودکار متن فیش (OCR) در پس‌زمینه در صورت وجود فایل محلی
        if local_saved_fn and tx_row_id:
            def _async_ocr_task(fn_str, t_id):
                try:
                    db.extract_receipt_text_ai(fn_str, tx_id=t_id)
                except Exception as ex_ocr:
                    logger.warning(f"Bundle receipt OCR error: {ex_ocr}")
            threading.Thread(target=_async_ocr_task, args=(local_saved_fn, tx_row_id), daemon=True).start()

        await msg.reply_text(
            f"✅ **فیش واریزی بسته «{bundle_title}» با موفقیت ثبت گردید.**\n"
            f"پس از بررسی و تایید توسط مدیریت، اعتبار به موجودی کیف پول شما واریز خواهد شد.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="bsb_main_menu")]]),
            parse_mode="Markdown"
        )

        # ارسال اعلان و عکس فیش به کلیه مدیران مجاز ربات بسته‌ها
        bundle_admins = db.get_bundle_bot_admins()
        target_admin_ids = set()
        if ADMIN_ID:
            target_admin_ids.add(int(ADMIN_ID))
        admin_tid_setting = db.get_setting("admin_telegram_id")
        if admin_tid_setting and str(admin_tid_setting).isdigit():
            target_admin_ids.add(int(admin_tid_setting))
        for adm in bundle_admins:
            if adm.get("telegram_id"):
                target_admin_ids.add(int(adm["telegram_id"]))

        admin_kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ تایید و شارژ آنی کیف پول", callback_data=f"adm_b_app_{tx_row_id}"),
                InlineKeyboardButton("❌ رد فیش", callback_data=f"adm_b_rej_{tx_row_id}")
            ]
        ])

        for target_id in target_admin_ids:
            try:
                if photo_id:
                    await context.bot.send_photo(chat_id=target_id, photo=photo_id, caption=admin_notif, reply_markup=admin_kb, parse_mode="Markdown")
                else:
                    await context.bot.send_message(chat_id=target_id, text=admin_notif, reply_markup=admin_kb, parse_mode="Markdown")
            except Exception as e_notif:
                logger.error(f"Error notifying admin {target_id} for bundle receipt: {e_notif}")
        return

    # بررسی متن برای اتصال حساب نماینده
    if not is_user_super_admin(user.id) and not get_reseller_for_user(user.id):
        text_input = (msg.text or "").strip()
        conn = db.get_connection()
        reseller_row = conn.execute(
            "SELECT * FROM resellers WHERE username = ? OR phone_number LIKE ? LIMIT 1",
            (text_input, f"%{text_input}%")
        ).fetchone()
        conn.close()

        if reseller_row:
            r_dict = dict(reseller_row)
            db.update_reseller(r_dict["id"], telegram_id=user.id)
            await msg.reply_text(
                f"🎉 **احراز هویت انجام شد!**\nحساب تلگرام شما با موفقیت به نمایندگی **{r_dict.get('name')}** متصل گردید.",
                reply_markup=get_bundle_sales_main_keyboard(user.id),
                parse_mode="Markdown"
            )
            return


class BundleSalesBotRunner:
    """کلاس مدیریت چرخه حیات ربات فروش بسته نمایندگی"""
    _instance = None
    _thread = None
    _loop = None
    _app = None
    _is_running = False

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def is_running(self) -> bool:
        return self._is_running

    def start(self):
        """راه‌اندازی ربات در یک ترد پس‌زمینه مستقل"""
        token = db.get_setting("bundle_bot_token")
        if not token:
            logger.warning("Bundle bot token not configured.")
            return False

        if self._is_running:
            logger.info("Bundle sales bot is already running.")
            return True

        self._thread = threading.Thread(target=self._run_loop, args=(token,), daemon=True, name="BundleSalesBotThread")
        self._thread.start()
        self._is_running = True
        return True

    def _run_loop(self, token: str):
        """حلقه رویداد asyncio اختصاصی برای ربات فروش بسته"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop

        async def _main_async():
            app = Application.builder().token(token).build()
            self._app = app
            app.add_handler(CommandHandler("start", start_command))
            app.add_handler(CommandHandler("admin", start_command))
            app.add_handler(CallbackQueryHandler(bsb_callback_handler))
            app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, message_handler))

            await app.initialize()
            await app.start()
            logger.info("Bundle Sales Bot polling started successfully!")
            await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)

            while self._is_running:
                await asyncio.sleep(1)

            await app.updater.stop()
            await app.stop()
            await app.shutdown()

        try:
            loop.run_until_complete(_main_async())
        except Exception as e:
            logger.error(f"Bundle Sales Bot run error: {e}")
        finally:
            self._is_running = False
            loop.close()

    def stop(self):
        """متوقف‌سازی ربات فروش بسته"""
        self._is_running = False


bundle_sales_bot_runner = BundleSalesBotRunner.get_instance()

if __name__ == "__main__":
    bundle_sales_bot_runner.start()
    try:
        while True:
            import time
            time.sleep(1)
    except KeyboardInterrupt:
        bundle_sales_bot_runner.stop()
