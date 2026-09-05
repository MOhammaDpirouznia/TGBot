#!/usr/bin/env python3
"""
ماژول مدیریت ربات‌های چندگانه نمایندگان فروش (White-Label Multi-Bot Manager)
این ماژول امکان اجرای همزمان و مستقل چندین ربات تلگرام اختصاصی برای هر نماینده را
با برند اختصاصی، کانال جوین اجباری، کارت بانکی مجزا و تایید آنی فیش توسط خود نماینده فراهم می‌کند.
"""

import os
import sys
import json
import html
import re
import logging
import asyncio
import threading
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List

import secrets
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from database import db
from utils import (
    get_now_iso, get_now_naive, get_single_link_template, format_single_link,
    generate_qr_code_bytes, gregorian_to_shamsi, days_remaining_shamsi
)
from admin_manager import load_plans, get_all_plans
from hidify import HidifyClient
from i18n import (
    get_language_keyboard, get_contact_keyboard, get_main_keyboard, t, SUPPORTED_LANGUAGES
)

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
    Bot
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)

logger = logging.getLogger("multibot")
logger.setLevel(logging.INFO)

# سرویس اتصال به پنل هیدیفای
HIDIFY_PANEL_URL = os.getenv("HIDIFY_PANEL_URL", "")
HIDIFY_API_KEY = os.getenv("HIDIFY_API_KEY", "")
HIDIFY_PROXY_PATH = os.getenv("HIDIFY_PROXY_PATH", "")
hidify_client = HidifyClient(HIDIFY_PANEL_URL, HIDIFY_API_KEY, HIDIFY_PROXY_PATH)


def get_reseller_hidify_client(reseller_id: int) -> HidifyClient:
    """دریافت کلاینت هیدیفای متصل به ادمین اختصاصی نماینده یا کلاینت عمومی"""
    reseller_key = db.get_reseller_hiddify_key(reseller_id)
    if reseller_key and reseller_key != HIDIFY_API_KEY:
        return HidifyClient(HIDIFY_PANEL_URL, reseller_key, HIDIFY_PROXY_PATH)
    return hidify_client


class ResellerBotInstance:
    """کلاس نگهداری و مدیریت چرخه حیات یک ربات اختصاصی نماینده"""

    def __init__(self, reseller_id: int):
        self.reseller_id = reseller_id
        self.reseller_data: Dict[str, Any] = {}
        self.application: Optional[Application] = None
        self.thread: Optional[threading.Thread] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.is_running = False
        self.error_message: Optional[str] = None
        self.bot_info: Dict[str, Any] = {}

    def reload_config(self) -> bool:
        """بارگذاری مجدد تنظیمات نماینده از دیتابیس"""
        res = db.get_reseller(self.reseller_id)
        if not res:
            self.error_message = "نماینده در سیستم یافت نشد."
            return False
        self.reseller_data = res
        return True

    @staticmethod
    def test_token(token: str) -> Dict[str, Any]:
        """اعتبارسنجی توکن تلگرام با فراخوانی مستقیم API"""
        if not token or not token.strip():
            return {"valid": False, "error": "توکن نمی‌تواند خالی باشد."}
        try:
            url = f"https://api.telegram.org/bot{token.strip()}/getMe"
            req = urllib.request.Request(url, headers={"User-Agent": "HiddiBot-MultiBot"})
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode("utf-8"))
            if data.get("ok"):
                res = data.get("result", {})
                return {
                    "valid": True,
                    "id": res.get("id"),
                    "username": res.get("username"),
                    "first_name": res.get("first_name"),
                    "can_join_groups": res.get("can_join_groups", False),
                }
            return {"valid": False, "error": data.get("description", "توکن نامعتبر است.")}
        except urllib.error.HTTPError as e:
            try:
                err_data = json.loads(e.read().decode("utf-8"))
                return {"valid": False, "error": err_data.get("description", str(e))}
            except Exception:
                return {"valid": False, "error": f"خطای سرور تلگرام: {e.code}"}
        except Exception as e:
            return {"valid": False, "error": f"خطا در برقراری ارتباط با سرور تلگرام: {str(e)}"}

    def build_application(self) -> Optional[Application]:
        """ساخت Application اختصاصی با هندلرهای مجزا و ایزوله برای این نماینده"""
        token = (self.reseller_data.get("bot_token") or "").strip()
        if not token:
            self.error_message = "توکن ربات ثبت نشده است."
            return None

        # اعتبارسنجی اولیه
        token_check = self.test_token(token)
        if not token_check["valid"]:
            self.error_message = token_check["error"]
            return None

        self.bot_info = token_check
        app = Application.builder().token(token).build()

        r_id = self.reseller_id

        # ─── هندلرهای اختصاصی ربات نماینده ───

        def get_reseller_main_keyboard(lang: str = "fa") -> ReplyKeyboardMarkup:
            """ساخت کیبورد اصلی ربات نماینده مطابق با چیدمان ذخیره شده در پنل مدیریت"""
            menu_rows = db.get_bot_menu_keyboard_rows(is_reseller=True)
            kb_list = []
            for r in menu_rows:
                row_btns = []
                for b in r:
                    b_id = b.get("id")
                    b_title = b.get("title") or t(f"btn_{b_id}", lang)
                    row_btns.append(KeyboardButton(b_title))
                if row_btns:
                    kb_list.append(row_btns)
            if not kb_list:
                kb_list = [
                    [KeyboardButton("🛍️ خرید اشتراک"), KeyboardButton("👤 اشتراک‌های من")],
                    [KeyboardButton("💳 کیف پول و شارژ"), KeyboardButton("🎧 پشتیبانی و تیکت")],
                    [KeyboardButton("📖 راهنمای اتصال"), KeyboardButton("🛠️ حل مشکلات اتصال")]
                ]
            return ReplyKeyboardMarkup(kb_list, resize_keyboard=True)

        async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
            """هندلر شروع و دستور /start در ربات نماینده"""
            user = update.effective_user
            if not user:
                return

            if db.is_blocked(user.id):
                msg = "⛔ شما بلاک شده‌اید!\n\nبرای رفع بلاک با پشتیبانی تماس بگیرید."
                if update.message:
                    await update.message.reply_text(msg)
                elif update.callback_query:
                    await update.callback_query.message.reply_text(msg)
                return

            # ذخیره کاربر با شناسه این نماینده
            db.save_user(
                telegram_id=user.id,
                username=user.username or user.first_name,
                reseller_id=r_id
            )

            # بررسی عضویت در کانال اجباری نماینده (در صورت تعریف)
            channel_id = (self.reseller_data.get("channel_id") or "").strip()
            if channel_id:
                try:
                    member = await context.bot.get_chat_member(chat_id=channel_id, user_id=user.id)
                    if member.status in ["left", "kicked"]:
                        ch_link = channel_id if channel_id.startswith("http") else f"https://t.me/{channel_id.replace('@', '')}"
                        kb = InlineKeyboardMarkup([
                            [InlineKeyboardButton("📢 عضویت در کانال", url=ch_link)],
                            [InlineKeyboardButton("✅ بررسی عضویت", callback_data="r_check_sub")]
                        ])
                        msg_text = "⚠️ جهت استفاده از ربات، لطفاً ابتدا در کانال ما عضو شوید:"
                        if update.message:
                            await update.message.reply_text(msg_text, reply_markup=kb)
                        elif update.callback_query:
                            await update.callback_query.message.reply_text(msg_text, reply_markup=kb)
                        return
                except Exception as e:
                    logger.warning(f"Could not check channel membership for reseller {r_id}: {e}")

            # احراز هویت و انتخاب زبان
            user_lang = db.get_user_language(user.id)
            is_verified = db.is_user_verified(user.id)

            if not is_verified:
                if user_lang:
                    context.user_data["lang"] = user_lang
                    contact_markup = get_contact_keyboard(user_lang)
                    auth_msg = t("contact_auth_prompt", user_lang)
                    if update.message:
                        await update.message.reply_text(auth_msg, reply_markup=contact_markup, parse_mode="Markdown")
                    elif update.callback_query:
                        await update.callback_query.message.reply_text(auth_msg, reply_markup=contact_markup, parse_mode="Markdown")
                    return
                else:
                    prompt = t("lang_select_prompt", "fa")
                    if update.message:
                        await update.message.reply_text(prompt, reply_markup=get_language_keyboard())
                    elif update.callback_query:
                        await update.callback_query.message.reply_text(prompt, reply_markup=get_language_keyboard())
                    return

            lang = user_lang or "fa"
            brand = self.reseller_data.get("brand_name") or self.reseller_data.get("name") or "سرویس VPN"
            custom_msg = self.reseller_data.get("start_message") or ""

            welcome = f"🌟 به ربات اختصاصی <b>{html.escape(str(brand))}</b> خوش آمدید!\n\n"
            if custom_msg:
                welcome += f"{html.escape(str(custom_msg))}\n\n"
            else:
                welcome += "🚀 اتصال پرسرعت، امن و بدون قطعی با سرورهای قدرتمند\n\n"
            welcome += "جهت شروع یکی از گزینه‌های زیر را انتخاب فرمایید:"

            main_kb = get_reseller_main_keyboard(lang)
            if update.message:
                await update.message.reply_text(welcome, reply_markup=main_kb, parse_mode="HTML")
            elif update.callback_query:
                await update.callback_query.message.reply_text(welcome, reply_markup=main_kb, parse_mode="HTML")

        async def select_language_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
            """تغییر و ذخیره زبان کاربر در ربات نماینده"""
            query = update.callback_query
            await query.answer()
            user = update.effective_user
            data = query.data
            lang = data.replace("r_lang_", "").replace("lang_", "")
            if lang not in SUPPORTED_LANGUAGES:
                lang = "fa"

            db.set_user_language(user.id, lang)
            context.user_data["lang"] = lang

            if not db.is_user_verified(user.id):
                contact_markup = get_contact_keyboard(lang)
                auth_msg = t("contact_auth_prompt", lang)
                try:
                    await query.edit_message_text(f"{t('lang_changed', lang)}\n\n{auth_msg}", parse_mode="Markdown")
                except Exception:
                    pass
                await context.bot.send_message(chat_id=user.id, text=auth_msg, reply_markup=contact_markup, parse_mode="Markdown")
                return

            brand = self.reseller_data.get("brand_name") or self.reseller_data.get("name") or "سرویس VPN"
            welcome = f"🌟 به ربات اختصاصی <b>{html.escape(str(brand))}</b> خوش آمدید!\n\nجهت شروع یکی از گزینه‌های زیر را انتخاب فرمایید:"
            try:
                await query.edit_message_text(f"{t('lang_changed', lang)}\n\n{welcome}", parse_mode="HTML")
            except Exception:
                pass
            await context.bot.send_message(chat_id=user.id, text=t("choose_option", lang), reply_markup=get_reseller_main_keyboard(lang))

        async def contact_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
            """دریافت شماره تماس و احراز هویت خودکار کاربر"""
            message = update.message
            user = update.effective_user
            lang = context.user_data.get("lang") or db.get_user_language(user.id) or "fa"

            if not message or not message.contact:
                return

            contact = message.contact
            if contact.user_id and contact.user_id != user.id:
                await message.reply_text(t("contact_auth_invalid", lang), reply_markup=get_contact_keyboard(lang))
                return

            phone_number = contact.phone_number
            db.set_user_phone(user.id, phone_number)
            db.save_user(telegram_id=user.id, username=user.username or user.first_name, reseller_id=r_id)

            brand = self.reseller_data.get("brand_name") or self.reseller_data.get("name") or "سرویس VPN"
            success_text = t("contact_auth_success", lang, phone=phone_number)
            welcome = f"🌟 به ربات اختصاصی <b>{html.escape(str(brand))}</b> خوش آمدید!\n\nجهت شروع یکی از گزینه‌های زیر را انتخاب فرمایید:"
            full_msg = f"{success_text}\n\n{welcome}"
            await message.reply_text(full_msg, reply_markup=get_reseller_main_keyboard(lang), parse_mode="HTML")

        async def plans_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
            """نمایش پلن‌های فروش برای مشتری نماینده (با اعمال نام و قیمت سفارشی نماینده)"""
            try:
                plans = db.get_reseller_active_plans(r_id)
                if not plans:
                    msg = "❌ در حال حاضر پلن فعالی در فروشگاه تعریف نشده است."
                    if update.callback_query:
                        await update.callback_query.answer()
                        await update.callback_query.edit_message_text(msg)
                    else:
                        await update.message.reply_text(msg)
                    return

                brand = html.escape(str(self.reseller_data.get("brand_name") or "ما"))
                text = f"📦 <b>تعرفه‌های اشتراک {brand}:</b>\n\nلطفاً پلن مورد نظر خود را انتخاب فرمایید:\n"

                buttons = []
                for p in plans:
                    pid = p["plan_id"]
                    pname = html.escape(str(p.get("display_name") or p.get("master_name", "پلن")))
                    price = p.get("display_price", 0)
                    vol = p.get("data_limit", 0)
                    days = p.get("duration", 30)
                    vol_str = f"{vol} گیگابایت" if vol > 0 else "نامحدود"

                    btn_text = f"⚡ {pname} | {vol_str} - {days} روز ({price:,} تومان)"
                    buttons.append([InlineKeyboardButton(btn_text, callback_data=f"r_buy_{pid}")])

                kb = InlineKeyboardMarkup(buttons)
                if update.callback_query:
                    await update.callback_query.answer()
                    await update.callback_query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")
                else:
                    await update.message.reply_text(text, reply_markup=kb, parse_mode="HTML")
            except Exception as e:
                logger.error(f"Error in plans_handler reseller {r_id}: {e}")

        async def plan_naming_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
            """انتخاب پلن و نمایش گزینه‌های تعیین نام اشتراک (آیدی تلگرام، نام هوشمند، نام دلخواه)"""
            query = update.callback_query
            try:
                await query.answer()
            except Exception:
                pass

            try:
                plan_id = query.data.replace("r_buy_", "")
                plan = db.get_reseller_plan(r_id, plan_id)
                if not plan:
                    await query.edit_message_text("❌ پلن مورد نظر یافت نشد.")
                    return

                price = plan.get("display_price", 0)
                pname = html.escape(str(plan.get("display_name") or plan.get("master_name", "پلن")))
                vol = plan.get("data_limit", 0)
                days = plan.get("duration", 30)
                vol_str = f"{vol} گیگابایت" if vol > 0 else "نامحدود"

                context.user_data["buying_plan_id"] = plan_id
                context.user_data["buying_price"] = price

                text = (
                    f"🛒 <b>انتخاب نحوه نام‌گذاری اکانت</b>\n\n"
                    f"📦 پلن انتخابی: <b>{pname}</b>\n"
                    f"📊 حجم: <b>{vol_str}</b> | ⏳ مدت: <b>{days} روز</b>\n"
                    f"💰 مبلغ: <b>{price:,} تومان</b>\n\n"
                    f"لطفاً مشخص کنید تمایل دارید نام اشتراک شما چگونه ایجاد شود:"
                )

                buttons = [
                    [InlineKeyboardButton("🔄 انتخاب خودکار (آیدی تلگرام)", callback_data=f"r_name_tg_{plan_id}")],
                    [InlineKeyboardButton("🧠 نام هوشمند / تصادفی", callback_data=f"r_name_smart_{plan_id}")],
                    [InlineKeyboardButton("✏️ نام دلخواه", callback_data=f"r_name_custom_{plan_id}")],
                    [InlineKeyboardButton("◀️ بازگشت به لیست پلن‌ها", callback_data="r_back_plans")]
                ]

                await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="HTML")
            except Exception as e:
                logger.error(f"Error in plan_naming_callback reseller {r_id}: {e}")

        async def name_choice_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
            """پردازش انتخاب نام اکانت و نمایش پیش‌نمایش تایید قبل از پرداخت"""
            query = update.callback_query
            await query.answer()
            user = update.effective_user
            data = query.data

            if data.startswith("r_name_tg_"):
                plan_id = data.replace("r_name_tg_", "")
                account_name = f"tg_{user.id}"
                context.user_data["buying_account_name"] = account_name
                context.user_data["buying_plan_id"] = plan_id
                await show_order_confirm(query, context, plan_id, account_name)
            elif data.startswith("r_name_smart_"):
                plan_id = data.replace("r_name_smart_", "")
                account_name = f"smart_{user.id % 10000}_{secrets.token_hex(2)}"
                context.user_data["buying_account_name"] = account_name
                context.user_data["buying_plan_id"] = plan_id
                await show_order_confirm(query, context, plan_id, account_name)
            elif data.startswith("r_name_custom_"):
                plan_id = data.replace("r_name_custom_", "")
                context.user_data["buying_plan_id"] = plan_id
                context.user_data["waiting_custom_name"] = True
                prompt_text = (
                    "✏️ <b>لطفاً نام دلخواه خود را تایپ و ارسال نمایید:</b>\n\n"
                    "• نام باید به حروف انگلیسی و اعداد باشد (مثال: <code>ali_vpn</code> یا <code>reza12</code>)."
                )
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("◀️ انصراف و بازگشت", callback_data=f"r_buy_{plan_id}")]
                ])
                await query.edit_message_text(prompt_text, reply_markup=kb, parse_mode="HTML")

        async def show_order_confirm(query, context, plan_id: str, account_name: str):
            """نمایش پیش‌فاکتور تایید نام و هدایت به روش‌های پرداخت"""
            plan = db.get_reseller_plan(r_id, plan_id)
            if not plan:
                await query.edit_message_text("❌ پلن یافت نشد.")
                return

            price = plan.get("display_price", 0)
            pname = html.escape(str(plan.get("display_name") or plan.get("master_name", "پلن")))
            vol = plan.get("data_limit", 0)
            days = plan.get("duration", 30)
            vol_str = f"{vol} گیگابایت" if vol > 0 else "نامحدود"

            context.user_data["buying_plan_id"] = plan_id
            context.user_data["buying_price"] = price
            context.user_data["buying_account_name"] = account_name

            text = (
                f"🧾 <b>تایید نهایی مشخصات اشتراک</b>\n\n"
                f"📦 پلن: <b>{pname}</b>\n"
                f"📊 حجم: <b>{vol_str}</b> | ⏳ مدت: <b>{days} روز</b>\n"
                f"👤 نام اکانت انتخابی: <code>{html.escape(account_name)}</code>\n"
                f"💰 مبلغ قابل پرداخت: <b>{price:,} تومان</b>\n\n"
                f"جهت انتخاب روش پرداخت روی دکمه زیر کلیک نمایید:"
            )

            buttons = [
                [InlineKeyboardButton("✅ تایید و انتخاب روش پرداخت", callback_data=f"r_conf_{plan_id}")],
                [InlineKeyboardButton("◀️ تغییر نام اکانت", callback_data=f"r_buy_{plan_id}")],
                [InlineKeyboardButton("❌ انصراف", callback_data="r_cancel_buy")]
            ]

            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="HTML")

        async def buy_plan_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
            """نمایش صفحه روش‌های پرداخت پس از تایید نام اشتراک"""
            query = update.callback_query
            try:
                await query.answer()
            except Exception:
                pass

            try:
                plan_id = query.data.replace("r_conf_", "")
                plan = db.get_reseller_plan(r_id, plan_id)
                if not plan:
                    await query.edit_message_text("❌ پلن مورد نظر یافت نشد.")
                    return

                price = plan.get("display_price", 0)
                pname = html.escape(str(plan.get("display_name") or plan.get("master_name", "پلن")))
                vol = plan.get("data_limit", 0)
                days = plan.get("duration", 30)
                vol_str = f"{vol} گیگابایت" if vol > 0 else "نامحدود"
                account_name = context.user_data.get("buying_account_name") or f"tg_{update.effective_user.id}"

                user = update.effective_user
                user_wallet = db.get_user_wallet_balance(user.id)
                gw_cfg = db.get_reseller_gateway(r_id)

                context.user_data["buying_plan_id"] = plan_id
                context.user_data["buying_price"] = price

                msg = f"🛒 <b>پیش‌فاکتور خرید اشتراک</b>\n\n"
                msg += f"📦 پلن: <b>{pname}</b>\n"
                msg += f"👤 نام اکانت: <code>{html.escape(account_name)}</code>\n"
                msg += f"📊 حجم: <b>{vol_str}</b> | ⏳ مدت: <b>{days} روز</b>\n"
                msg += f"💰 مبلغ قابل پرداخت: <b>{price:,} تومان</b>\n"
                msg += f"💳 موجودی کیف پول شما: <b>{user_wallet:,} تومان</b>\n\n"
                msg += "لطفاً نحوه پرداخت را انتخاب فرمایید:"

                ordered_methods = db.get_payment_methods(reseller_id=r_id)
                buttons = []
                for m in ordered_methods:
                    m_id = m.get("id")
                    if not m.get("enabled", True):
                        continue
                    if m_id == "wallet":
                        if user_wallet >= price:
                            buttons.append([InlineKeyboardButton(f"⚡ پرداخت آنی از کیف پول ({user_wallet:,} ت)", callback_data=f"r_pwal_{plan_id}")])
                        else:
                            buttons.append([InlineKeyboardButton(f"💰 پرداخت از کیف پول (کسری: {price - user_wallet:,} ت)", callback_data="r_pwal_insuf")])
                    elif m_id == "online_gateway":
                        if gw_cfg.get("enabled") and gw_cfg.get("key"):
                            if gw_cfg.get("type") == "blupal":
                                gw_btn_text = "💳 پرداخت کارت به کارت هوشمند (بلوپال)"
                            else:
                                gw_label = "زرین‌پال" if gw_cfg.get("type") == "zarinpal" else ("آیدی‌پی" if gw_cfg.get("type") == "idpay" else "آنلاین")
                                gw_btn_text = f"💳 درگاه پرداخت آنلاین ({gw_label})"
                            buttons.append([InlineKeyboardButton(gw_btn_text, callback_data=f"r_ponl_{plan_id}")])
                        else:
                            buttons.append([InlineKeyboardButton("💳 درگاه آنلاین (بزودی)", callback_data="r_ponl_soon")])
                    elif m_id == "card_to_card":
                        buttons.append([InlineKeyboardButton("💵 کارت به کارت (بانکی)", callback_data=f"r_pcard_{plan_id}")])

                # تغییر نام یا انصراف
                buttons.append([InlineKeyboardButton("◀️ تغییر نام اکانت", callback_data=f"r_buy_{plan_id}"), InlineKeyboardButton("❌ انصراف", callback_data="r_cancel_buy")])

                kb = InlineKeyboardMarkup(buttons)
                await query.edit_message_text(msg, reply_markup=kb, parse_mode="HTML")
            except Exception as e:
                logger.error(f"Error in buy_plan_confirm_callback reseller {r_id}: {e}")

        async def pay_card_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
            """نمایش اطلاعات کارت بانکی فعال نماینده با دکمه‌های کپی هوشمند شماره کارت و مبلغ"""
            query = update.callback_query
            try:
                await query.answer()
            except Exception:
                pass

            try:
                plan_id = query.data.replace("r_pcard_", "")
                plan = db.get_reseller_plan(r_id, plan_id)
                if not plan:
                    await query.edit_message_text("❌ پلن یافت نشد.")
                    return

                price = plan.get("display_price", 0)
                pname = html.escape(str(plan.get("display_name") or plan.get("master_name", "پلن")))
                vol = plan.get("data_limit", 0)
                days = plan.get("duration", 30)
                vol_str = f"{vol} گیگابایت" if vol > 0 else "نامحدود"
                account_name = context.user_data.get("buying_account_name") or f"tg_{update.effective_user.id}"

                active_card = db.get_active_reseller_card(r_id)
                if active_card:
                    raw_card = active_card.get("card_number") or ""
                    card_holder = html.escape(str(active_card.get("card_holder") or ""))
                    bank_name = html.escape(str(active_card.get("bank_name") or ""))
                else:
                    raw_card = self.reseller_data.get("card_number") or ""
                    card_holder = html.escape(str(self.reseller_data.get("card_holder") or ""))
                    bank_name = html.escape(str(self.reseller_data.get("bank_name") or ""))

                card_num = re.sub(r"\D", "", str(raw_card))
                rial_price = price * 10
                rial_fmt = f"{rial_price:,}"
                toman_fmt = f"{price:,}"

                context.user_data["buying_plan_id"] = plan_id
                context.user_data["buying_price"] = price

                msg = f"💵 <b>پرداخت کارت به کارت</b>\n\n"
                msg += f"📦 پلن: <b>{pname}</b>\n"
                msg += f"👤 نام اکانت: <code>{html.escape(account_name)}</code>\n"
                msg += f"📊 حجم: <b>{vol_str}</b> | ⏳ مدت: <b>{days} روز</b>\n\n"
                msg += f"💰 <b>مبلغ قابل واریز:</b>\n"
                msg += f"• به ریال (جهت همراه بانک / عابربانک):\n<code>{rial_price}</code> ریال (<b>{rial_fmt} ریال</b>)\n"
                msg += f"• به تومان:\n<code>{price}</code> تومان (<b>{toman_fmt} تومان</b>)\n\n"

                if card_num:
                    msg += "💳 <b>اطلاعات کارت جهت واریز:</b>\n"
                    msg += f"شماره کارت:\n<code>{card_num}</code>\n"
                    if card_holder:
                        msg += f"به نام: <b>{card_holder}</b>\n"
                    if bank_name:
                        msg += f"بانک: <b>{bank_name}</b>\n"
                    msg += "\n⚠️ <b>نکات مهم:</b>\n"
                    msg += "• برای کپی با یک لمس، روی <b>شماره کارت</b> یا <b>مبلغ به ریال</b> بالا یا دکمه‌های زیر بزنید.\n"
                    msg += "• پس از واریز، <b>عکس فیش واریزی</b> خود را در همین گفتگو ارسال فرمایید."

                    buttons = [
                        [InlineKeyboardButton("📋 کپی شماره کارت", callback_data=f"r_copy_card_{card_num}")],
                        [InlineKeyboardButton(f"💰 کپی مبلغ به ریال ({rial_fmt} ریال)", callback_data=f"r_copy_rial_{rial_price}")],
                        [InlineKeyboardButton(f"💵 کپی مبلغ به تومان ({toman_fmt} ت)", callback_data=f"r_copy_amt_{price}")],
                        [InlineKeyboardButton("◀️ بازگشت", callback_data=f"r_conf_{plan_id}"), InlineKeyboardButton("❌ انصراف", callback_data="r_cancel_buy")]
                    ]
                else:
                    msg += "💳 جهت پرداخت و دریافت شماره کارت، با پشتیبانی تماس حاصل فرمایید."
                    buttons = [
                        [InlineKeyboardButton("◀️ بازگشت", callback_data=f"r_conf_{plan_id}"), InlineKeyboardButton("❌ انصراف", callback_data="r_cancel_buy")]
                    ]

                kb = InlineKeyboardMarkup(buttons)
                await query.edit_message_text(msg, reply_markup=kb, parse_mode="HTML")
            except Exception as e:
                logger.error(f"Error in pay_card_callback reseller {r_id}: {e}")

        async def copy_action_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
            """پاسخ به دکمه‌های کپی شماره کارت و مبلغ در ربات نماینده با ارسال پیام کپی ۱ لمسی"""
            query = update.callback_query
            data = query.data
            try:
                if data.startswith("r_copy_card_"):
                    raw_c = data.replace("r_copy_card_", "").strip()
                    c_num = re.sub(r"\D", "", raw_c)
                    await query.answer(f"📋 شماره کارت:\n{c_num}\n(کپی شد)", show_alert=False)
                    try:
                        await context.bot.send_message(
                            chat_id=update.effective_chat.id,
                            text=f"📋 <b>شماره کارت مقصد (جهت واریز):</b>\n<code>{c_num}</code>\n\n<i>👆 روی شماره کارت بالا بزنید تا با یک لمس کپی شود.</i>",
                            parse_mode="HTML"
                        )
                    except Exception as e:
                        logger.warning(f"Error sending copy card msg in reseller bot: {e}")
                elif data.startswith("r_copy_rial_"):
                    raw_amt = data.replace("r_copy_rial_", "").strip()
                    clean_amt = re.sub(r"\D", "", raw_amt)
                    try:
                        rial_f = f"{int(clean_amt):,}"
                    except Exception:
                        rial_f = clean_amt
                    await query.answer(f"💰 مبلغ به ریال:\n{rial_f} ریال\n(کپی شد)", show_alert=False)
                    try:
                        await context.bot.send_message(
                            chat_id=update.effective_chat.id,
                            text=f"💰 <b>مبلغ به ریال (جهت همراه بانک / عابربانک):</b>\n<code>{clean_amt}</code>\n\n<i>👆 روی عدد بالا بزنید تا با یک لمس کپی شود ({rial_f} ریال).</i>",
                            parse_mode="HTML"
                        )
                    except Exception as e:
                        logger.warning(f"Error sending copy rial msg in reseller bot: {e}")
                elif data.startswith("r_copy_amt_"):
                    raw_amt = data.replace("r_copy_amt_", "").strip()
                    clean_amt = re.sub(r"\D", "", raw_amt)
                    try:
                        amt_fmt = f"{int(clean_amt):,}"
                    except Exception:
                        amt_fmt = clean_amt
                    await query.answer(f"💵 مبلغ به تومان:\n{amt_fmt} تومان\n(کپی شد)", show_alert=False)
                    try:
                        await context.bot.send_message(
                            chat_id=update.effective_chat.id,
                            text=f"💵 <b>مبلغ به تومان:</b>\n<code>{clean_amt}</code>\n\n<i>👆 روی عدد بالا بزنید تا با یک لمس کپی شود ({amt_fmt} تومان).</i>",
                            parse_mode="HTML"
                        )
                    except Exception as e:
                        logger.warning(f"Error sending copy amt msg in reseller bot: {e}")
                elif data == "r_pwal_insuf":
                    user = update.effective_user
                    user_wallet = db.get_user_wallet_balance(user.id)
                    await query.answer(f"❌ موجودی کیف پول شما ({user_wallet:,} ت) برای این پلن کافی نیست. لطفاً از کارت به کارت استفاده کنید.", show_alert=True)
                elif data == "r_ponl_soon":
                    await query.answer("💳 درگاه پرداخت آنلاین به زودی فعال خواهد شد. لطفاً از روش کارت به کارت استفاده فرمایید.", show_alert=True)
                elif data == "r_cancel_buy":
                    await query.answer()
                    await query.edit_message_text("❌ عملیات خرید لغو شد.")
            except Exception as e:
                logger.error(f"Error in copy_action_callback in reseller bot: {e}")

        async def pay_wallet_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
            """پرداخت و ساخت آنی اشتراک از کیف پول مشتری در ربات نماینده"""
            query = update.callback_query
            await query.answer()

            plan_id = query.data.replace("r_pwal_", "")
            plan = db.get_reseller_plan(r_id, plan_id)
            if not plan:
                await query.edit_message_text("❌ پلن یافت نشد.")
                return

            price = plan.get("display_price", 0)
            wholesale_cost = plan.get("wholesale_price", price)
            user = update.effective_user
            user_wallet = db.get_user_wallet_balance(user.id)

            if user_wallet < price:
                await query.answer("❌ موجودی کیف پول کافی نیست!", show_alert=True)
                return

            r_info = db.get_reseller(r_id) or {}
            r_balance = r_info.get("balance", 0)
            if r_balance < wholesale_cost:
                await query.answer("⚠️ اعتبار فروشگاه موقتاً نیازمند شارژ است. لطفاً به پشتیبانی اطلاع دهید.", show_alert=True)
                return

            deduct_res = db.deduct_wallet_balance(user.id, price, f"خرید آنی اشتراک {plan.get('display_name')}")
            if not deduct_res.get("success"):
                await query.answer("❌ خطا در کسر موجودی: " + str(deduct_res.get("error")), show_alert=True)
                return

            pname = plan.get("display_name") or plan.get("master_name", "اشتراک")
            vol = plan.get("data_limit", 30)
            days = plan.get("duration", 30)
            account_name = context.user_data.get("buying_account_name") or f"r{r_id}_u{user.id}_{int(datetime.now().timestamp()) % 10000}"

            db.deduct_reseller_balance(r_id, wholesale_cost, pname, account_name)

            await query.edit_message_text("⏳ در حال ساخت و فعال‌سازی آنی اشتراک شما...")

            r_client = get_reseller_hidify_client(r_id)
            created = await r_client.create_user(
                name=account_name,
                usage_limit_gb=vol if vol > 0 else None,
                package_days=days,
                enable=True,
                comment=f"[RESELLER_ID: #{r_id}] User {user.id} | {account_name}"
            )

            uuid_val = created.get("uuid") if created else None
            sub_url = f"{HIDIFY_PANEL_URL}/{HIDIFY_PROXY_PATH}/{uuid_val}/" if uuid_val else ""

            sub_id = db.save_subscription(
                telegram_id=user.id,
                hidify_uuid=uuid_val,
                plan_id=plan_id,
                plan_name=pname,
                data_limit=vol,
                duration=days,
                status="active",
                account_name=account_name,
                account_comment=f"Wallet Purchase | Reseller #{r_id}",
                reseller_id=r_id
            )

            brand = self.reseller_data.get("brand_name") or "ما"
            cust_msg = f"🎉 <b>اشتراک {brand} با موفقیت فعال شد:</b>\n\n"
            cust_msg += f"📦 پلن: <b>{pname}</b>\n"
            cust_msg += f"👤 نام اکانت: <code>{html.escape(account_name)}</code>\n"
            cust_msg += f"📊 حجم: <b>{vol if vol > 0 else 'نامحدود'} گیگابایت</b> | ⏳ مدت: <b>{days} روز</b>\n"
            cust_msg += f"💰 مبلغ پرداختی: <b>{price:,} تومان</b>\n\n"
            cust_msg += f"🔗 <b>لینک اتصال اختصاصی شما:</b>\n<code>{sub_url}</code>\n\n"
            cust_msg += "💡 لینک بالا را در اپلیکیشن v2rayNG / Hiddify / Streisand وارد فرمایید."

            kb_btns = []
            if sub_id:
                kb_btns.append([InlineKeyboardButton("📱 دریافت بارکد QR", callback_data=f"r_sub_qr_{sub_id}")])
            await query.edit_message_text(cust_msg, reply_markup=InlineKeyboardMarkup(kb_btns) if kb_btns else None, parse_mode="HTML")

        async def pay_online_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
            """هدایت به درگاه پرداخت آنلاین اختصاصی نماینده"""
            query = update.callback_query
            await query.answer()

            plan_id = query.data.replace("r_ponl_", "")
            plan = db.get_reseller_plan(r_id, plan_id)
            if not plan:
                await query.edit_message_text("❌ پلن یافت نشد.")
                return

            price = plan.get("display_price", 0)
            pname = plan.get("display_name") or plan.get("master_name", "پلن")
            account_name = context.user_data.get("buying_account_name") or f"tg_{update.effective_user.id}"
            user = update.effective_user
            gw_cfg = db.get_reseller_gateway(r_id)
            gw_type = gw_cfg.get("type", "zarinpal")
            gw_key = gw_cfg.get("key", "")
            sandbox = gw_cfg.get("sandbox", False)

            order_id = f"R{r_id}_ONL_{int(datetime.now().timestamp())}_{user.id % 1000}"
            r_info = db.get_reseller(r_id) or {}
            domain = r_info.get("custom_domain") or os.getenv("PANEL_DOMAIN", "http://localhost:5000")
            if not str(domain).startswith("http"):
                domain = f"https://{domain}"
            callback_url = f"{str(domain).rstrip('/')}/payment/callback/{order_id}"

            pay_url = None
            invoice_id = None
            if gw_type == "zarinpal":
                from payment import ZarinPal
                zp = ZarinPal(merchant_id=gw_key, sandbox=sandbox)
                res = zp.create_payment(amount=price, description=f"خرید {pname}", callback_url=callback_url)
                if res.get("success"):
                    pay_url = res.get("payment_url")
                    invoice_id = res.get("authority")
            elif gw_type == "idpay":
                from payment import IDPay
                idp = IDPay(api_key=gw_key, sandbox=sandbox)
                res = idp.create_payment(amount=price, name=user.full_name or "کاربر", description=f"خرید {pname}", callback_url=callback_url, order_id=order_id)
                if res.get("success"):
                    pay_url = res.get("payment_url")
                    invoice_id = res.get("payment_id")
            elif gw_type == "blupal":
                from payment import BluPal
                bp = BluPal(api_key=gw_key, sandbox=sandbox)
                res = bp.create_payment(amount=price, order_id=order_id, description=f"خرید {pname}")
                if res.get("success"):
                    pay_url = res.get("payment_url") or res.get("payment_link")
                    invoice_id = res.get("invoice_id")

            if pay_url:
                db.save_transaction(
                    order_id=order_id,
                    user_id=user.id,
                    username=user.username or user.first_name,
                    plan_name=pname,
                    amount=price,
                    gateway=f"{gw_type}_reseller_{r_id}",
                    tracking_code=str(invoice_id or order_id),
                    status="pending",
                    account_name=account_name,
                    reseller_id=r_id
                )
                gw_title = "کارت به کارت هوشمند بلوپال" if gw_type == "blupal" else "درگاه پرداخت آنلاین شاپرک"
                btn_title = "🌐 ورود به درگاه پرداخت هوشمند بلوپال" if gw_type == "blupal" else "🌐 ورود به درگاه پرداخت شاپرک"
                msg = f"💳 <b>{gw_title}</b>\n\n"
                msg += f"📦 پلن: <b>{pname}</b>\n"
                msg += f"👤 نام اکانت: <code>{html.escape(account_name)}</code>\n"
                msg += f"💰 مبلغ: <b>`{price:,}` تومان</b>\n"
                msg += f"🔢 شناسه سفارش: `{order_id}`\n\n"
                msg += "جهت پرداخت روی دکمه زیر کلیک کنید. پس از پرداخت آنلاین، اشتراک شما به صورت خودکار فعال می‌گردد:"

                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton(btn_title, url=pay_url)],
                    [InlineKeyboardButton("◀️ بازگشت", callback_data=f"r_conf_{plan_id}")]
                ])
                await query.edit_message_text(msg, reply_markup=kb, parse_mode="HTML")
            else:
                await query.answer("❌ خطا در اتصال به درگاه بانکی. لطفاً از کارت به کارت استفاده فرمایید.", show_alert=True)

        async def receipt_photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
            """دریافت تصویر فیش از مشتری و ارسال به تلگرام خود نماینده جهت تایید"""
            user = update.effective_user
            if not update.message.photo:
                return

            plan_id = context.user_data.get("buying_plan_id")
            price = context.user_data.get("buying_price", 0)
            account_name = context.user_data.get("buying_account_name") or f"r{r_id}_u{user.id}"

            if not plan_id:
                await update.message.reply_text("⚠️ لطفاً ابتدا از بخش «🛍️ خرید اشتراک» یک پلن را انتخاب کرده و سپس فیش واریزی را ارسال کنید.")
                return

            photo = update.message.photo[-1]
            photo_file_id = photo.file_id
            order_id = f"R{r_id}_{int(datetime.now().timestamp())}_{user.id % 1000}"

            saved_receipt_filename = None
            try:
                receipts_dir = Path("data/receipts")
                receipts_dir.mkdir(parents=True, exist_ok=True)
                tg_file = await photo.get_file()
                saved_receipt_filename = f"receipt_{order_id}.jpg"
                await tg_file.download_to_drive(receipts_dir / saved_receipt_filename)
            except Exception as e:
                logger.warning(f"Could not download receipt photo for order {order_id}: {e}")

            r_plan = db.get_reseller_plan(r_id, plan_id)
            if r_plan:
                pname = r_plan.get("display_name") or r_plan.get("name") or r_plan.get("master_name", "پلن انتخابی")
            else:
                plans = load_plans()
                plan = plans.get(plan_id, {})
                pname = plan.get("name", "پلن انتخابی")

            db.save_transaction(
                order_id=order_id,
                user_id=user.id,
                username=user.username or user.first_name,
                plan_name=pname,
                amount=price,
                gateway="card_reseller",
                tracking_code=f"Receipt_{order_id}",
                status="pending",
                account_name=account_name,
                receipt_image=saved_receipt_filename or photo_file_id,
                receipt_file_type="web_upload" if saved_receipt_filename else "photo",
                reseller_id=r_id
            )

            await update.message.reply_text(
                "✅ <b>فیش واریزی شما با موفقیت دریافت شد.</b>\n\n"
                "فیش واریزی جهت بررسی و تایید برای پشتیبانی ارسال گردید و پس از تایید، اشتراک به صورت خودکار برای شما فعال و ارسال خواهد شد. سپاس از صبوری شما.",
                parse_mode="HTML"
            )

            reseller_tg = self.reseller_data.get("telegram_id")
            if reseller_tg:
                try:
                    notif_text = f"🔔 <b>فیش واریزی جدید در ربات شما!</b>\n\n"
                    notif_text += f"👤 مشتری: {html.escape(str(user.first_name))} (ID: <code>{user.id}</code>)\n"
                    notif_text += f"📦 پلن: <b>{html.escape(str(pname))}</b>\n"
                    notif_text += f"👤 نام اکانت انتخابی: <code>{html.escape(str(account_name))}</code>\n"
                    notif_text += f"💰 مبلغ: <b>{price:,} تومان</b>\n"
                    notif_text += f"🔖 کد سفارش: <code>{order_id}</code>\n\n"
                    notif_text += "جهت تایید یا رد پرداخت از دکمه‌های زیر استفاده کنید:"

                    app_kb = InlineKeyboardMarkup([
                        [
                            InlineKeyboardButton("✅ تایید و تحویل کانفیگ", callback_data=f"rapprove_{order_id}_{user.id}_{plan_id}"),
                            InlineKeyboardButton("❌ رد پرداخت", callback_data=f"rreject_{order_id}_{user.id}")
                        ]
                    ])
                    await context.bot.send_photo(
                        chat_id=reseller_tg,
                        photo=photo_file_id,
                        caption=notif_text,
                        reply_markup=app_kb,
                        parse_mode="HTML"
                    )
                except Exception as e:
                    logger.error(f"Failed to notify reseller {r_id} telegram: {e}")

        async def reseller_approve_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
            """تایید پرداخت توسط نماینده و ساخت خودکار اکانت در هیدیفای"""
            query = update.callback_query
            await query.answer()

            caller_id = update.effective_user.id
            reseller_tg = self.reseller_data.get("telegram_id")
            if not reseller_tg or caller_id != reseller_tg:
                await query.answer("⛔ شما دسترسی تایید این پرداخت را ندارید.", show_alert=True)
                return

            data = query.data
            if data.startswith("rapprove_"):
                parts = data.split("_")
                order_id = parts[1]
                target_uid = int(parts[2])
                plan_id = parts[3]

                plan = db.get_reseller_plan(r_id, plan_id) or {}
                pname = plan.get("display_name") or plan.get("master_name", "اشتراک")
                vol = plan.get("data_limit", 30)
                days = plan.get("duration", 30)
                price = plan.get("display_price", 0)
                wholesale_cost = plan.get("wholesale_price", price)

                tx_data = db.get_transaction_by_order_id(order_id) or {}
                account_name = tx_data.get("account_name") or f"r{r_id}_u{target_uid}_{int(datetime.now().timestamp()) % 10000}"

                deduct_res = db.deduct_reseller_balance(r_id, wholesale_cost, pname, account_name)

                if not deduct_res.get("success"):
                    await query.edit_message_caption(
                        caption=f"❌ **خطا در تایید:** موجودی کیف پول نماینده کافی نیست!\n"
                                f"مبلغ عمده مورد نیاز: {wholesale_cost:,} تومان\n"
                                f"لطفاً ابتدا کیف پول خود را در پنل وب شارژ فرمایید.",
                        parse_mode="Markdown"
                    )
                    return

                h_res = None
                try:
                    r_client = get_reseller_hidify_client(r_id)
                    h_res = await r_client.create_user(
                        name=account_name,
                        package_days=int(days),
                        usage_limit_gb=float(vol) if vol > 0 else None,
                        comment=f"[RESELLER_ID: #{r_id}] TG: {target_uid} | {account_name}"
                    )
                except Exception as e:
                    logger.error(f"Hiddify creation error: {e}")

                uuid_val = h_res.get("uuid") if h_res else None
                sub_url = ""
                if uuid_val:
                    sub_url = f"{HIDIFY_PANEL_URL}/{HIDIFY_PROXY_PATH}/{uuid_val}/"
                else:
                    sub_url = f"https://vpn.service/sub/{account_name}"

                sub_id = db.save_subscription(
                    telegram_id=target_uid,
                    hidify_uuid=uuid_val,
                    plan_id=plan_id,
                    plan_name=pname,
                    data_limit=float(vol),
                    duration=int(days),
                    status="active",
                    account_name=account_name,
                    account_comment=f"Reseller #{r_id} Bot",
                    reseller_id=r_id
                )

                db.update_transaction(order_id, status="approved")

                brand = self.reseller_data.get("brand_name") or "ما"
                cashback_note = ""
                try:
                    vip_info = db.get_user_vip_info(target_uid)
                    if vip_info.get("is_vip") and vip_info.get("cashback_percent", 0) > 0:
                        cb_pct = vip_info.get("cashback_percent", 10)
                        cb_amount = int((price * cb_pct) / 100)
                        if cb_amount > 0:
                            cb_res = db.add_wallet_balance(
                                target_uid,
                                cb_amount,
                                f"هدیه کش‌بک خرید VIP ({cb_pct}%) از {brand}",
                                ref_id=str(order_id),
                                tx_type="cashback"
                            )
                            new_b = cb_res.get("new_balance", 0)
                            cashback_note += f"\n\n🎁 **هدیه کش‌بک VIP:** مبلغ {cb_amount:,} تومان ({cb_pct}٪) به کیف پول شما واریز شد.\n💰 موجودی کیف پول: {new_b:,} تومان"
                except Exception as e_cb:
                    logger.error(f"Error in reseller bot VIP cashback: {e_cb}")

                try:
                    ug_res = db.check_and_upgrade_user_vip(target_uid, reseller_id=r_id)
                    if ug_res.get("upgraded"):
                        cb_rate = ug_res.get("cashback_percent", 10)
                        t_sp = ug_res.get("total_spent", 0)
                        cashback_note += f"\n\n🎉 **تبریک! شما به عنوان مشتری طلایی (⭐️ VIP) فروشگاه {brand} ارتقا یافتید!**\nبا رسیدن مجموع خرید شما به {t_sp:,} تومان، از این پس از {cb_rate}٪ کش‌بک در هر خرید و اولویت در پشتیبانی برخوردار خواهید بود. 🌹"
                except Exception as e_ug:
                    logger.error(f"Error checking reseller bot VIP auto upgrade: {e_ug}")

                await query.edit_message_caption(
                    caption=f"✅ **پرداخت تایید شد و اشتراک با موفقیت تحویل مشتری گردید.**\n"
                            f"📦 پلن: {pname} | 💰 هزینه عمده کسر شده: {wholesale_cost:,} تومان\n"
                            f"👤 نام اشتراک: `{account_name}`",
                    parse_mode="Markdown"
                )

                try:
                    cust_msg = f"🎉 <b>پرداخت شما تایید شد! اشتراک {brand} آماده است:</b>\n\n"
                    cust_msg += f"📦 پلن: <b>{pname}</b>\n"
                    cust_msg += f"👤 نام اکانت: <code>{html.escape(str(account_name))}</code>\n"
                    cust_msg += f"📊 حجم: <b>{vol} گیگابایت</b> | ⏳ مدت: <b>{days} روز</b>\n\n"
                    cust_msg += f"🔗 <b>لینک اتصال اختصاصی شما:</b>\n<code>{sub_url}</code>{cashback_note}\n\n"
                    cust_msg += "💡 جهت اتصال، لینک بالا را کپی کرده و در نرم‌افزار v2rayNG / Streisand / Hiddify وارد نمایید."

                    kb_btns = []
                    if sub_id:
                        kb_btns.append([InlineKeyboardButton("📱 دریافت بارکد QR", callback_data=f"r_sub_qr_{sub_id}")])

                    await context.bot.send_message(
                        chat_id=target_uid,
                        text=cust_msg,
                        reply_markup=InlineKeyboardMarkup(kb_btns) if kb_btns else None,
                        parse_mode="HTML"
                    )
                except Exception as e:
                    logger.error(f"Failed to deliver config to customer {target_uid}: {e}")

            elif data.startswith("rreject_"):
                parts = data.split("_")
                order_id = parts[1]
                target_uid = int(parts[2])

                db.update_transaction(order_id, status="rejected")
                await query.edit_message_caption(caption="❌ **پرداخت توسط شما رد شد.**")

                try:
                    await context.bot.send_message(
                        chat_id=target_uid,
                        text="❌ متأسفانه فیش ارسالی شما توسط مدیریت تایید نشد. در صورت بروز هرگونه ابهام، با پشتیبانی در ارتباط باشید."
                    )
                except Exception:
                    pass

        async def my_subs_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
            """نمایش کامل وضعیت اشتراک‌های کاربر با استعلام زنده از سرور هیدیفای نماینده"""
            user = update.effective_user
            if not user:
                return

            try:
                subs = db.get_user_subscriptions(user.id)
            except Exception as e:
                logger.error(f"Error getting subscriptions for reseller bot user {user.id}: {e}")
                subs = []

            if not subs:
                no_sub_msg = (
                    "ℹ️ <b>شما در حال حاضر هیچ اشتراک فعالی در این فروشگاه ندارید.</b>\n\n"
                    "جهت مشاهده تعرفه‌ها و خرید سرویس پرسرعت، روی دکمه «🛍️ خرید اشتراک» بزنید."
                )
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🛍️ خرید اشتراک جدید", callback_data="r_back_plans")]
                ])
                if update.callback_query:
                    await update.callback_query.answer()
                    await update.callback_query.message.reply_text(no_sub_msg, reply_markup=kb, parse_mode="HTML")
                else:
                    await update.message.reply_text(no_sub_msg, reply_markup=kb, parse_mode="HTML")
                return

            status_msg = None
            if update.message:
                status_msg = await update.message.reply_text("⏳ در حال استعلام آخرین وضعیت و مصرف از سرور...")

            vip_info = db.get_user_vip_info(user.id)
            vip_header = ""
            if vip_info.get("is_vip"):
                cb = vip_info.get("cashback_percent", 10)
                vip_header = f"👑 <b>سطح عضویت: مشتری طلایی (⭐️ VIP)</b>\n🎁 <b>پاداش فعال:</b> {cb}٪ کش‌بک در هر خرید\n\n"

            r_info = db.get_reseller(r_id) or {}
            custom_tutorial = r_info.get("tutorial_domain") or db.get_setting("tutorial_domain")
            custom_troubleshoot = r_info.get("troubleshoot_domain") or db.get_setting("troubleshoot_domain")
            dashboard_url = os.getenv("DASHBOARD_URL", "").rstrip("/")

            if custom_tutorial:
                tutorial_url = f"https://{custom_tutorial}" if not str(custom_tutorial).startswith("http") else str(custom_tutorial)
            elif dashboard_url:
                tutorial_url = f"{dashboard_url}/help?r={r_id}"
            else:
                tutorial_url = f"http://127.0.0.1:5000/help?r={r_id}"

            if custom_troubleshoot:
                troubleshoot_url = f"https://{custom_troubleshoot}" if not str(custom_troubleshoot).startswith("http") else str(custom_troubleshoot)
            else:
                troubleshoot_url = f"{tutorial_url.split('?')[0].rstrip('/')}/troubleshoot"

            r_client = get_reseller_hidify_client(r_id)

            for i, sub in enumerate(subs, 1):
                uuid_val = sub.get("hidify_uuid")
                pname = html.escape(str(sub.get("plan_name") or "پلن اختصاصی"))
                account_name = html.escape(str(sub.get("account_name") or f"tg_{user.id}"))
                data_limit = float(sub.get("data_limit") or 0)
                data_used = float(sub.get("data_used") or 0)
                duration = int(sub.get("duration") or 30)
                start_date = sub.get("start_date")
                status = sub.get("status", "active")
                sub_db_id = sub.get("id")

                # استعلام زنده از سرور هیدیفای نماینده
                if uuid_val:
                    try:
                        h_user = await r_client.get_user(uuid_val)
                        if isinstance(h_user, dict) and "error" not in h_user:
                            data_used = round(float(h_user.get("current_usage_GB") or 0), 2)
                            h_limit = float(h_user.get("usage_limit_GB") or 0)
                            if h_limit > 0:
                                data_limit = round(h_limit, 2)
                            h_days = h_user.get("package_days")
                            if h_days:
                                duration = int(h_days)
                            if h_user.get("start_date"):
                                start_date = h_user.get("start_date")
                            is_active = h_user.get("is_active", True)
                            enable = h_user.get("enable", True)
                            status = "active" if (is_active and enable) else "expired"

                            db.update_subscription_by_uuid(
                                uuid_val,
                                data_used=data_used,
                                data_limit=data_limit,
                                status=status,
                                start_date=start_date,
                                duration=duration
                            )
                    except Exception as e_live:
                        logger.warning(f"Error fetching live user {uuid_val} in reseller {r_id}: {e_live}")

                status_badge = "🟢 فعال" if status == "active" else "🔴 منقضی"

                if data_limit > 0:
                    remaining_gb = max(0.0, round(data_limit - data_used, 2))
                    usage_pct = min((data_used / data_limit) * 100, 100.0)
                    bar_len = 10
                    filled = min(10, int(usage_pct / 10))
                    bar = "█" * filled + "░" * (bar_len - filled)
                    bar_emoji = "🔴" if usage_pct >= 90 else ("🟡" if usage_pct >= 70 else "🟢")
                    usage_str = (
                        f"📊 مصرف: <b>{data_used:.2f}</b> از <b>{data_limit:.2f} GB</b>\n"
                        f"   {bar_emoji} <code>{bar}</code> <b>{usage_pct:.1f}%</b>\n"
                        f"   💾 حجم باقیمانده: <b>{remaining_gb:.2f} گیگابایت</b>"
                    )
                else:
                    usage_str = f"📊 مصرف: <b>{data_used:.2f} GB</b> (حجم نامحدود)"

                start_fmt = gregorian_to_shamsi(start_date) if start_date else "نامشخص"
                remaining_days = None
                expire_fmt = "نامشخص"
                if start_date and duration:
                    try:
                        st = datetime.fromisoformat(start_date) if "T" in str(start_date) else datetime.strptime(str(start_date)[:10], "%Y-%m-%d")
                        exp = st + timedelta(days=duration)
                        expire_fmt = gregorian_to_shamsi(exp.isoformat())
                        remaining_days = max(0, (exp.date() - get_now_naive().date()).days)
                    except Exception:
                        pass

                rem_days_str = f" (⏰ <b>{remaining_days} روز مانده</b>)" if remaining_days is not None else ""

                sub_url = f"{HIDIFY_PANEL_URL}/{HIDIFY_PROXY_PATH}/{uuid_val}/" if uuid_val else "در دسترس نیست"

                sub_card = (
                    f"🔹 <b>اشتراک #{i}: {pname}</b> ({status_badge})\n"
                    f"📝 نام اکانت: <code>{account_name}</code>\n"
                    f"{usage_str}\n"
                    f"📅 شروع: <b>{start_fmt}</b> | انقضا: <b>{expire_fmt}</b>{rem_days_str}\n\n"
                    f"🔗 <b>لینک اتصال:</b>\n<code>{sub_url}</code>"
                )

                sub_buttons = [
                    [
                        InlineKeyboardButton("📱 دریافت بارکد QR", callback_data=f"r_sub_qr_{sub_db_id}"),
                        InlineKeyboardButton("🔄 تمدید اشتراک", callback_data=f"r_renew_{sub_db_id}")
                    ],
                    [
                        InlineKeyboardButton("📖 راهنمای اتصال", url=tutorial_url),
                        InlineKeyboardButton("🛠️ عیب‌یابی", url=troubleshoot_url)
                    ]
                ]

                if update.message:
                    await update.message.reply_text(sub_card, reply_markup=InlineKeyboardMarkup(sub_buttons), parse_mode="HTML")
                elif update.callback_query:
                    await update.callback_query.message.reply_text(sub_card, reply_markup=InlineKeyboardMarkup(sub_buttons), parse_mode="HTML")

            if status_msg:
                try:
                    await status_msg.delete()
                except Exception:
                    pass

        async def sub_qr_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
            """ارسال تصویر بارکد QR اشتراک کاربر"""
            query = update.callback_query
            await query.answer()
            try:
                sub_id = int(query.data.replace("r_sub_qr_", ""))
                user_subs = db.get_user_subscriptions(update.effective_user.id)
                target_sub = next((s for s in user_subs if s["id"] == sub_id), None)
                if not target_sub or not target_sub.get("hidify_uuid"):
                    await query.answer("❌ اشتراک یا لینک یافت نشد.", show_alert=True)
                    return

                uuid_val = target_sub["hidify_uuid"]
                sub_url = f"{HIDIFY_PANEL_URL}/{HIDIFY_PROXY_PATH}/{uuid_val}/"
                qr_bytes = generate_qr_code_bytes(sub_url)

                caption = (
                    f"📱 <b>بارکد QR اختصاصی اشتراک:</b>\n"
                    f"👤 نام اکانت: <code>{html.escape(str(target_sub.get('account_name') or 'اشتراک'))}</code>\n\n"
                    f"<code>{sub_url}</code>\n\n"
                    f"💡 این بارکد را با دوربین اپلیکیشن VPN خود اسکن نمایید."
                )

                await context.bot.send_photo(
                    chat_id=update.effective_chat.id,
                    photo=qr_bytes,
                    caption=caption,
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.error(f"Error generating QR code in reseller bot: {e}")
                await query.answer("❌ خطا در تولید بارکد QR", show_alert=True)

        async def sub_renew_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
            """فرآیند تمدید اشتراک انتخابی در ربات نماینده"""
            query = update.callback_query
            await query.answer()
            try:
                sub_id = int(query.data.replace("r_renew_", ""))
                user_subs = db.get_user_subscriptions(update.effective_user.id)
                target_sub = next((s for s in user_subs if s["id"] == sub_id), None)
                if not target_sub:
                    await query.answer("❌ اشتراک مورد نظر یافت نشد.", show_alert=True)
                    return

                context.user_data["renew_sub_id"] = sub_id
                context.user_data["is_renewal"] = True
                context.user_data["buying_account_name"] = target_sub.get("account_name")

                plans = db.get_reseller_active_plans(r_id)
                if not plans:
                    await query.edit_message_text("❌ در حال حاضر پلن فعالی برای تمدید وجود ندارد.")
                    return

                acc_title = html.escape(str(target_sub.get("account_name") or "اشتراک"))
                text = f"🔄 <b>تمدید اشتراک «{acc_title}»:</b>\n\nلطفاً پلن مد نظر خود را جهت تمدید انتخاب فرمایید:\n"

                buttons = []
                for p in plans:
                    pid = p["plan_id"]
                    pname = html.escape(str(p.get("display_name") or p.get("master_name", "پلن")))
                    price = p.get("display_price", 0)
                    vol = p.get("data_limit", 0)
                    days = p.get("duration", 30)
                    vol_str = f"{vol} گیگابایت" if vol > 0 else "نامحدود"

                    btn_text = f"⚡ {pname} | {vol_str} - {days} روز ({price:,} تومان)"
                    buttons.append([InlineKeyboardButton(btn_text, callback_data=f"r_conf_{pid}")])

                buttons.append([InlineKeyboardButton("◀️ انصراف", callback_data="r_cancel_buy")])

                await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="HTML")
            except Exception as e:
                logger.error(f"Error in sub_renew_callback reseller {r_id}: {e}")

        async def support_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
            """ارسال پیام پشتیبانی یا آیدی پشتیبان"""
            sup_user = self.reseller_data.get("support_username") or ""
            brand = self.reseller_data.get("brand_name") or "پشتیبانی"
            buttons = []
            if sup_user:
                sup_clean = sup_user.replace("@", "")
                buttons.append([InlineKeyboardButton("💬 ارتباط مستقیم در تلگرام", url=f"https://t.me/{sup_clean}")])

            msg = f"🎧 <b>واحد پشتیبانی {brand}</b>\n\n"
            msg += "جهت ارسال پیام برای تیم پشتیبانی، پیام خود را با فرمت زیر ارسال کنید:\n"
            msg += "<code>تیکت: متن پیام شما</code>\n\n"
            msg += "کارشناسان ما در اسرع وقت پاسخ شما را در همین ربات ارسال خواهند کرد."
            kb = InlineKeyboardMarkup(buttons) if buttons else None
            await update.message.reply_text(msg, reply_markup=kb, parse_mode="HTML")

        async def guide_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
            """راهنمای اتصال و لینک آموزش‌های تصویری و حل مشکلات اتصال"""
            r_info = db.get_reseller(r_id) or {}
            brand_name = r_info.get("brand_title") or r_info.get("brand_name") or r_info.get("name") or "فروشگاه"

            custom_tutorial = r_info.get("tutorial_domain") or db.get_setting("tutorial_domain")
            custom_troubleshoot = r_info.get("troubleshoot_domain") or db.get_setting("troubleshoot_domain")
            dashboard_url = os.getenv("DASHBOARD_URL", "").rstrip("/")

            if custom_tutorial:
                tutorial_url = f"https://{custom_tutorial}" if not str(custom_tutorial).startswith("http") else str(custom_tutorial)
            elif dashboard_url:
                tutorial_url = f"{dashboard_url}/help?r={r_id}"
            else:
                tutorial_url = f"http://127.0.0.1:5000/help?r={r_id}"

            if custom_troubleshoot:
                troubleshoot_url = f"https://{custom_troubleshoot}" if not str(custom_troubleshoot).startswith("http") else str(custom_troubleshoot)
            else:
                troubleshoot_url = f"{tutorial_url.split('?')[0].rstrip('/')}/troubleshoot"

            guide_text = (
                f"📖 <b>مرکز آموزش تصویری و راهنمای اتصال {brand_name}</b>\n\n"
                "برای مشاهده آموزش‌های مرحله‌به‌مرحله تصویری برای تمام دستگاه‌ها (اندروید، آیفون، ویندوز، مک، تلویزیون هوشمند و مودم) و رفع سریع هرگونه مشکل در اتصال، روی دکمه‌های زیر کلیک نمایید:"
            )
            buttons = [
                [InlineKeyboardButton("🌐 مشاهده آموزش‌های تصویری تمام دستگاه‌ها", url=tutorial_url)],
                [InlineKeyboardButton("🛠️ عیب‌یابی و حل مشکلات اتصال", url=troubleshoot_url)]
            ]
            kb = InlineKeyboardMarkup(buttons)
            await update.message.reply_text(guide_text, reply_markup=kb, parse_mode="HTML")

        async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
            """مسیریابی هوشمند تمام کلیدهای منوی اصلی ربات نماینده"""
            text = (update.message.text or "").strip()
            if not text:
                return

            user = update.effective_user

            # ۱. بررسی دریافت نام دلخواه اکانت
            if context.user_data.get("waiting_custom_name"):
                clean_name = re.sub(r"[^a-zA-Z0-9_\-]", "", text)
                if not clean_name:
                    clean_name = f"user_{user.id}"
                context.user_data["waiting_custom_name"] = False
                context.user_data["buying_account_name"] = clean_name
                plan_id = context.user_data.get("buying_plan_id")
                if plan_id:
                    plan = db.get_reseller_plan(r_id, plan_id)
                    price = plan.get("display_price", 0) if plan else 0
                    pname = plan.get("display_name", "پلن") if plan else "پلن"
                    confirm_msg = (
                        f"✅ <b>نام اکانت شما تنظیم شد:</b> <code>{html.escape(clean_name)}</code>\n\n"
                        f"📦 پلن: <b>{pname}</b>\n"
                        f"💰 مبلغ: <b>{price:,} تومان</b>\n\n"
                        f"جهت انتخاب روش پرداخت روی دکمه زیر بزنید:"
                    )
                    kb = InlineKeyboardMarkup([
                        [InlineKeyboardButton("✅ تایید و انتخاب روش پرداخت", callback_data=f"r_conf_{plan_id}")],
                        [InlineKeyboardButton("◀️ تغییر نام اکانت", callback_data=f"r_buy_{plan_id}")]
                    ])
                    await update.message.reply_text(confirm_msg, reply_markup=kb, parse_mode="HTML")
                    return

            # ۲. پردازش تیکت مستقیم متنی
            if text.startswith("تیکت:") or text.startswith("تیکت ") or text.startswith("/ticket"):
                content = text.replace("تیکت:", "").replace("تیکت", "").replace("/ticket", "").strip()
                if content:
                    is_vip = db.is_user_vip(user.id)
                    subj = "⭐️ تیکت مشتری VIP" if is_vip else "پیام مشتری از ربات"
                    t_res = db.create_ticket(
                        user_id=user.id,
                        username=user.username or user.first_name,
                        subject=subj,
                        message=content,
                        reseller_id=r_id
                    )
                    t_id = t_res.get("ticket_id", 0)
                    await update.message.reply_text(f"✅ <b>پیام و تیکت پشتیبانی شما با شماره #{t_id} ثبت شد.</b>\nپاسخ کارشناسان در همین ربات برای شما ارسال خواهد شد.", parse_mode="HTML")

                    reseller_tg = self.reseller_data.get("telegram_id")
                    if reseller_tg:
                        try:
                            vip_alert = "🚨 ⭐️ <b>[تیکت فوری - مشتری ویژه VIP]</b>" if is_vip else "📨 <b>تیکت پشتیبانی جدید</b>"
                            notif_msg = (
                                f"{vip_alert}\n\n"
                                f"👤 مشتری: {html.escape(str(user.first_name))} (ID: <code>{user.id}</code>)\n"
                                f"💬 یوزرنیم: @{user.username or 'ندارد'}\n"
                                f"📝 متن پیام:\n{html.escape(content)}\n\n"
                                f"🔖 شماره تیکت: #{t_id}"
                            )
                            await context.bot.send_message(chat_id=reseller_tg, text=notif_msg, parse_mode="HTML")
                        except Exception as e_notif:
                            logger.error(f"Error notifying reseller of ticket: {e_notif}")
                else:
                    await update.message.reply_text("⚠️ لطفاً متن پیام خود را بعد از عبارت <code>تیکت:</code> بنویسید.", parse_mode="HTML")
                return

            # ۳. بررسی تطابق با دکمه‌های منوی ربات نماینده
            btn = db.match_bot_menu_button(text, is_reseller=True)
            if btn:
                b_id = btn.get("id")
                is_enabled = btn.get("is_enabled", True)
                if not is_enabled:
                    dis_msg = btn.get("disabled_message") or "⚠️ این بخش موقتاً غیرفعال می‌باشد."
                    await update.message.reply_text(dis_msg)
                    return

                if b_id == "buy":
                    return await plans_handler(update, context)
                elif b_id in ("my_subs", "renew"):
                    return await my_subs_handler(update, context)
                elif b_id == "wallet":
                    bal = db.get_user_wallet_balance(user.id)
                    vip_info = db.get_user_vip_info(user.id)
                    vip_txt = ""
                    if vip_info.get("is_vip"):
                        cb = vip_info.get("cashback_percent", 10)
                        vip_txt = f"\n👑 <b>سطح حساب:</b> مشتری طلایی (⭐️ VIP)\n🎁 <b>پاداش کش‌بک:</b> {cb}٪ بازگشت وجه در هر خرید\n"
                    await update.message.reply_text(f"💳 <b>موجودی کیف پول شما:</b> <code>{bal:,}</code> تومان{vip_txt}", parse_mode="HTML")
                    return
                elif b_id == "support":
                    return await support_handler(update, context)
                elif b_id in ("tutorials", "troubleshoot"):
                    return await guide_handler(update, context)
                elif b_id == "language":
                    prompt = t("lang_select_prompt", "fa")
                    await update.message.reply_text(prompt, reply_markup=get_language_keyboard())
                    return
                elif b_id == "payments":
                    conn = db.get_connection()
                    cursor = conn.cursor()
                    cursor.execute("""
                        SELECT id, amount, gateway, status, created_at, plan_name 
                        FROM transactions 
                        WHERE user_id = ? AND (reseller_id = ? OR reseller_id IS NULL)
                        ORDER BY id DESC LIMIT 5
                    """, (user.id, r_id))
                    txs = cursor.fetchall()
                    conn.close()
                    if not txs:
                        await update.message.reply_text("🧾 شما تاکنون پرداختی در این ربات ثبت نکرده‌اید.")
                        return
                    p_text = "🧾 <b>آخرین سوابق پرداخت شما:</b>\n\n"
                    for tx in txs:
                        st = "✅ تایید شده" if tx["status"] in ("approved", "completed") else ("⏳ در حال بررسی" if tx["status"] == "pending" else "❌ رد شده")
                        p_text += f"• سفارش #{tx['id']} | {html.escape(str(tx['plan_name'] or 'پلن'))}\n  💰 {tx['amount']:,} ت ({st})\n  📅 {tx['created_at'][:16].replace('T', ' ')}\n\n"
                    await update.message.reply_text(p_text, parse_mode="HTML")
                    return
                elif b_id == "test_sub":
                    await update.message.reply_text("⚡ جهت دریافت اکانت تست رایگان، لطفاً با پشتیبانی در ارتباط باشید.")
                    return

            # ۴. پاسخ پیش‌فرض
            await update.message.reply_text("لطفاً از دکمه‌های منو استفاده فرمایید.")

        # ثبت هندلرها
        app.add_handler(CommandHandler("start", start_handler))
        app.add_handler(CommandHandler("plans", plans_handler))
        app.add_handler(CommandHandler("help", guide_handler))
        app.add_handler(CallbackQueryHandler(select_language_callback, pattern="^(r_lang_|lang_)"))
        app.add_handler(CallbackQueryHandler(plans_handler, pattern="^r_back_plans$"))
        app.add_handler(CallbackQueryHandler(plan_naming_callback, pattern="^r_buy_"))
        app.add_handler(CallbackQueryHandler(name_choice_callback, pattern="^r_name_"))
        app.add_handler(CallbackQueryHandler(buy_plan_confirm_callback, pattern="^r_conf_"))
        app.add_handler(CallbackQueryHandler(pay_card_callback, pattern="^r_pcard_"))
        app.add_handler(CallbackQueryHandler(pay_wallet_callback, pattern="^r_pwal_"))
        app.add_handler(CallbackQueryHandler(pay_online_callback, pattern="^r_ponl_"))
        app.add_handler(CallbackQueryHandler(copy_action_callback, pattern="^(r_copy_card_|r_copy_rial_|r_copy_amt_|r_pwal_insuf|r_ponl_soon|r_cancel_buy)"))
        app.add_handler(CallbackQueryHandler(sub_qr_callback, pattern="^r_sub_qr_"))
        app.add_handler(CallbackQueryHandler(sub_renew_callback, pattern="^r_renew_"))
        app.add_handler(CallbackQueryHandler(start_handler, pattern="^r_check_sub$"))
        app.add_handler(CallbackQueryHandler(reseller_approve_callback, pattern="^rapprove_|^rreject_"))
        app.add_handler(MessageHandler(filters.CONTACT, contact_handler))
        app.add_handler(MessageHandler(filters.PHOTO, receipt_photo_handler))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))

        return app

    def _run_loop(self):
        """اجرای حلقه رویداد در ترد مجزا"""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self.application.initialize())
            self.loop.run_until_complete(self.application.start())
            self.loop.run_until_complete(self.application.updater.start_polling(allowed_updates=Update.ALL_TYPES))
            self.is_running = True
            logger.info(f"Reseller bot #{self.reseller_id} (@{self.bot_info.get('username')}) started successfully.")
            self.loop.run_forever()
        except Exception as e:
            self.is_running = False
            self.error_message = str(e)
            logger.error(f"Error in reseller bot #{self.reseller_id}: {e}")
        finally:
            try:
                if self.application and self.application.updater.running:
                    self.loop.run_until_complete(self.application.updater.stop())
                if self.application and self.application.running:
                    self.loop.run_until_complete(self.application.stop())
                    self.loop.run_until_complete(self.application.shutdown())
            except Exception:
                pass
            self.is_running = False

    def start(self) -> bool:
        """راه‌اندازی ربات در پس‌زمینه"""
        if self.is_running:
            return True
        if not self.reload_config():
            return False

        self.application = self.build_application()
        if not self.application:
            return False

        self.thread = threading.Thread(target=self._run_loop, name=f"ResellerBot-{self.reseller_id}", daemon=True)
        self.thread.start()
        return True

    def stop(self) -> bool:
        """توقف امن ربات"""
        if not self.is_running and not self.loop:
            return True
        try:
            if self.loop and self.loop.is_running():
                self.loop.call_soon_threadsafe(self.loop.stop)
            if self.thread and self.thread.is_alive():
                self.thread.join(timeout=3.0)
            self.is_running = False
            logger.info(f"Reseller bot #{self.reseller_id} stopped.")
            return True
        except Exception as e:
            logger.error(f"Error stopping reseller bot #{self.reseller_id}: {e}")
            return False


class MultiBotManager:
    """مدیریت مرکزی کلیه ربات‌های نمایندگان در سامانه"""

    def __init__(self):
        self.instances: Dict[int, ResellerBotInstance] = {}
        self._lock = threading.Lock()

    def start_reseller_bot(self, reseller_id: int) -> Dict[str, Any]:
        """روشن کردن ربات یک نماینده"""
        with self._lock:
            if reseller_id in self.instances and self.instances[reseller_id].is_running:
                return {"success": True, "message": "ربات در حال اجرا است.", "status": "running"}

            inst = ResellerBotInstance(reseller_id)
            ok = inst.start()
            if ok:
                self.instances[reseller_id] = inst
                db.update_reseller_bot_settings(reseller_id, is_bot_active=1)
                return {
                    "success": True,
                    "message": "ربات اختصاصی با موفقیت راه‌اندازی شد.",
                    "status": "running",
                    "bot_username": inst.bot_info.get("username")
                }
            else:
                return {
                    "success": False,
                    "error": inst.error_message or "خطای ناشناخته در شروع ربات.",
                    "status": "error"
                }

    def stop_reseller_bot(self, reseller_id: int) -> Dict[str, Any]:
        """خاموش کردن ربات نماینده"""
        with self._lock:
            if reseller_id not in self.instances:
                db.update_reseller_bot_settings(reseller_id, is_bot_active=0)
                return {"success": True, "message": "ربات متوقف است.", "status": "stopped"}

            inst = self.instances[reseller_id]
            inst.stop()
            del self.instances[reseller_id]
            db.update_reseller_bot_settings(reseller_id, is_bot_active=0)
            return {"success": True, "message": "ربات با موفقیت متوقف شد.", "status": "stopped"}

    def restart_reseller_bot(self, reseller_id: int) -> Dict[str, Any]:
        """راه‌اندازی مجدد ربات نماینده"""
        self.stop_reseller_bot(reseller_id)
        return self.start_reseller_bot(reseller_id)

    def get_bot_status(self, reseller_id: int) -> Dict[str, Any]:
        """استعلام آخرین وضعیت زنده ربات نماینده"""
        with self._lock:
            res = db.get_reseller(reseller_id)
            if not res:
                return {"status": "not_found", "is_running": False}

            has_token = bool((res.get("bot_token") or "").strip())
            is_active_db = bool(res.get("is_bot_active"))

            inst = self.instances.get(reseller_id)
            is_alive = bool(inst and inst.is_running)

            return {
                "has_token": has_token,
                "is_bot_active": is_active_db,
                "is_running": is_alive,
                "bot_username": res.get("bot_username") or (inst.bot_info.get("username") if inst else None),
                "brand_name": res.get("brand_name") or res.get("name"),
                "error": inst.error_message if (inst and not is_alive and is_active_db) else None
            }

    def start_all_active_bots(self):
        """راه‌اندازی خودکار تمام ربات‌های فعال هنگام اجرای سیستم"""
        try:
            active_list = db.get_active_reseller_bots()
            logger.info(f"Found {len(active_list)} active reseller bots to launch.")
            for r in active_list:
                rid = r["id"]
                res = self.start_reseller_bot(rid)
                logger.info(f"Auto-start reseller bot #{rid} (@{r.get('bot_username', 'unnamed')}): {res}")
        except Exception as e:
            logger.error(f"Error auto-starting reseller bots: {e}")


# ساخت نمونه تکین (Singleton) برای کل پروژه
multibot_manager = MultiBotManager()
