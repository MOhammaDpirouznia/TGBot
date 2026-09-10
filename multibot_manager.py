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
from typing import Dict, Any, Optional, List, Tuple

import secrets
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from database import db
from utils import (
    get_now_iso, get_now_naive, get_single_link_template, format_single_link,
    generate_qr_code_bytes, gregorian_to_shamsi, days_remaining_shamsi
)
from admin_manager import load_plans, get_all_plans, get_plan_telegram_emoji
from hidify import HidifyClient
from i18n import (
    get_language_keyboard, get_contact_keyboard, get_main_keyboard, t, SUPPORTED_LANGUAGES
)
from reseller_bot_admin import (
    get_reseller_stats_text,
    get_reseller_admin_keyboard,
    get_reseller_bundles_payload,
    get_bundle_payment_details_payload,
    get_reseller_tickets_payload,
    get_reseller_ticket_detail_payload,
    get_reseller_payments_payload,
    get_reseller_create_user_plans_payload,
    get_reseller_discounts_payload,
    get_reseller_reports_payload,
    get_reseller_settings_payload,
    search_reseller_subscriptions
)

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
    Bot,
    CopyTextButton,
    WebAppInfo
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
ADMIN_ID = int(os.getenv("ADMIN_ID", "0") or 0)


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

        def check_admin_access(user_id: int) -> Tuple[bool, str]:
            """بررسی دسترسی ادمین ربات نماینده با پشتیبانی از چند ادمین و نقش‌های مختلف"""
            is_adm, role = db.is_reseller_bot_admin(r_id, user_id)
            if not is_adm:
                reseller_tg = self.reseller_data.get("telegram_id")
                if reseller_tg and user_id == reseller_tg:
                    return True, "main"
                return False, ""
            return True, role

        async def notify_reseller_admins(bot, roles: list, text: str, photo=None, reply_markup=None):
            """ارسال اعلان هوشمند به مدیران مرتبط با نقش‌های اعلام‌شده"""
            admins = db.get_reseller_bot_admins(r_id)
            target_ids = set()
            for adm in admins:
                r_role = adm.get("role") or "main"
                if r_role in roles or "main" in roles or r_role == "main":
                    try:
                        target_ids.add(int(adm.get("telegram_id")))
                    except (ValueError, TypeError):
                        pass
            reseller_tg = self.reseller_data.get("telegram_id")
            if reseller_tg:
                try:
                    target_ids.add(int(reseller_tg))
                except (ValueError, TypeError):
                    pass

            for tid in target_ids:
                try:
                    if photo:
                        await bot.send_photo(chat_id=tid, photo=photo, caption=text, reply_markup=reply_markup, parse_mode="HTML")
                    else:
                        await bot.send_message(chat_id=tid, text=text, reply_markup=reply_markup, parse_mode="HTML")
                except Exception as ex:
                    logger.debug(f"Failed to notify reseller admin {tid}: {ex}")

        def get_reseller_main_keyboard(lang: str = "fa", is_reseller_admin: bool = False, user_id: int = None) -> ReplyKeyboardMarkup:
            """ساخت کیبورد اصلی ربات نماینده مطابق با چیدمان ذخیره شده در پنل مدیریت با اتصال مینی‌اپ اختصاصی نماینده"""
            menu_rows = db.get_bot_menu_keyboard_rows(is_reseller=True)
            kb_list = []
            webapp_url = db.get_setting("webapp_url", "") or os.getenv("DASHBOARD_URL", "")
            if not webapp_url and os.getenv("RAILWAY_PUBLIC_DOMAIN"):
                webapp_url = f"https://{os.getenv('RAILWAY_PUBLIC_DOMAIN')}"

            for r in menu_rows:
                row_btns = []
                for b in r:
                    b_id = b.get("id")
                    b_title = b.get("title") or t(f"btn_{b_id}", lang)
                    if b_id in ("mini_app", "webapp"):
                        if webapp_url:
                            uid_param = f"tg_id={user_id}&" if user_id else ""
                            full_app_url = f"{webapp_url.rstrip('/')}/webapp?{uid_param}r={r_id}"
                            row_btns.append(KeyboardButton(b_title, web_app=WebAppInfo(url=full_app_url)))
                        else:
                            row_btns.append(KeyboardButton(b_title))
                    else:
                        row_btns.append(KeyboardButton(b_title))
                if row_btns:
                    kb_list.append(row_btns)
            if not kb_list:
                kb_list = [
                    [KeyboardButton("🛍️ خرید اشتراک"), KeyboardButton("👤 اشتراک‌های من")],
                    [KeyboardButton("💳 کیف پول و شارژ"), KeyboardButton("🎧 پشتیبانی و تیکت")],
                    [KeyboardButton("📖 راهنمای اتصال"), KeyboardButton("🛠️ حل مشکلات اتصال")]
                ]
            if is_reseller_admin:
                kb_list.append([KeyboardButton("🔧 پنل مدیریت نماینده")])
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

            is_adm, _ = check_admin_access(user.id)
            main_kb = get_reseller_main_keyboard(lang, is_reseller_admin=is_adm, user_id=user.id)
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
            is_adm, _ = check_admin_access(user.id)
            await context.bot.send_message(chat_id=user.id, text=t("choose_option", lang), reply_markup=get_reseller_main_keyboard(lang, is_reseller_admin=is_adm, user_id=user.id))

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

            is_adm, _ = check_admin_access(user.id)
            brand = self.reseller_data.get("brand_name") or self.reseller_data.get("name") or "سرویس VPN"
            success_text = t("contact_auth_success", lang, phone=phone_number)
            welcome = f"🌟 به ربات اختصاصی <b>{html.escape(str(brand))}</b> خوش آمدید!\n\nجهت شروع یکی از گزینه‌های زیر را انتخاب فرمایید:"
            full_msg = f"{success_text}\n\n{welcome}"
            await message.reply_text(full_msg, reply_markup=get_reseller_main_keyboard(lang, is_reseller_admin=is_adm, user_id=user.id), parse_mode="HTML")

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
                    emoji = get_plan_telegram_emoji(p, pid)

                    btn_text = f"{emoji} {pname} | {vol_str} - {days} روز ({price:,} تومان)"
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
                if not plan or not plan.get("show_in_reseller_bot", True):
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
            if not plan or not plan.get("show_in_reseller_bot", True):
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
            """نمایش صفحه روش‌های پرداخت پس از تایید نام اشتراک با پشتیبانی از کد تخفیف"""
            query = update.callback_query
            try:
                await query.answer()
            except Exception:
                pass

            try:
                plan_id = query.data.replace("r_conf_", "")
                plan = db.get_reseller_plan(r_id, plan_id)
                if not plan or not plan.get("show_in_reseller_bot", True):
                    await query.edit_message_text("❌ پلن مورد نظر یافت نشد.")
                    return

                base_price = plan.get("display_price", 0)
                pname = html.escape(str(plan.get("display_name") or plan.get("master_name", "پلن")))
                vol = plan.get("data_limit", 0)
                days = plan.get("duration", 30)
                vol_str = f"{vol} گیگابایت" if vol > 0 else "نامحدود"
                account_name = context.user_data.get("buying_account_name") or f"tg_{update.effective_user.id}"

                applied_code = context.user_data.get("applied_discount_code")
                disc_amount = context.user_data.get("applied_discount_amount", 0) if applied_code else 0
                price = max(0, base_price - disc_amount)

                user = update.effective_user
                user_wallet = db.get_user_wallet_balance(user.id)
                gw_cfg = db.get_reseller_gateway(r_id)

                context.user_data["buying_plan_id"] = plan_id
                context.user_data["buying_price"] = price

                msg = f"🛒 <b>پیش‌فاکتور خرید اشتراک</b>\n\n"
                msg += f"📦 پلن: <b>{pname}</b>\n"
                msg += f"👤 نام اکانت: <code>{html.escape(account_name)}</code>\n"
                msg += f"📊 حجم: <b>{vol_str}</b> | ⏳ مدت: <b>{days} روز</b>\n"
                if disc_amount > 0:
                    msg += f"💵 مبلغ اصلی: <s>{base_price:,}</s> تومان\n"
                    msg += f"🎟️ کد تخفیف ({applied_code}): <b>{disc_amount:,}- تومان</b>\n"
                msg += f"💰 مبلغ قابل پرداخت: <b>{price:,} تومان</b>\n"
                msg += f"💳 موجودی کیف پول شما: <b>{user_wallet:,} تومان</b>\n\n"
                msg += "لطفاً نحوه پرداخت را انتخاب فرمایید:"

                ordered_methods = db.get_payment_methods(reseller_id=r_id)
                buttons = []

                # دکمه اعمال کد تخفیف
                if not applied_code:
                    buttons.append([InlineKeyboardButton("🎟️ اعمال کد تخفیف", callback_data=f"r_apply_disc_{plan_id}")])
                else:
                    buttons.append([InlineKeyboardButton(f"✅ کد تخفیف اعمال شد: {applied_code} (-{disc_amount:,} ت)", callback_data="noop")])

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

        async def apply_discount_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
            """درخواست وارد کردن کد تخفیف از کاربر"""
            query = update.callback_query
            await query.answer()
            plan_id = query.data.replace("r_apply_disc_", "")
            context.user_data["waiting_discount_code_plan"] = plan_id

            msg = (
                "🎟️ <b>اعمال کد تخفیف</b>\n\n"
                "لطفاً کد تخفیف اختصاصی خود را ارسال نمایید:"
            )
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ بازگشت به فاکتور", callback_data=f"r_conf_{plan_id}")]
            ])
            await query.edit_message_text(msg, reply_markup=kb, parse_mode="HTML")

        async def pay_card_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
            """نمایش اطلاعات کارت بانکی فعال نماینده با اتصال به تنظیمات پیامک بانک و دکمه‌های کپی هوشمند"""
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

                base_price = plan.get("display_price", 0)
                pname = html.escape(str(plan.get("display_name") or plan.get("master_name", "پلن")))
                vol = plan.get("data_limit", 0)
                days = plan.get("duration", 30)
                vol_str = f"{vol} گیگابایت" if vol > 0 else "نامحدود"
                account_name = context.user_data.get("buying_account_name") or f"tg_{update.effective_user.id}"

                applied_code = context.user_data.get("applied_discount_code")
                disc_amount = context.user_data.get("applied_discount_amount", 0) if applied_code else 0
                price = max(0, base_price - disc_amount)

                active_card = db.get_active_reseller_card(r_id, incoming_amount=price)
                if not active_card:
                    all_rcards = db.get_reseller_cards(r_id)
                    if all_rcards:
                        active_card = all_rcards[0]

                if active_card:
                    raw_card = active_card.get("card_number") or ""
                    card_holder = html.escape(str(active_card.get("card_holder") or ""))
                    bank_name = html.escape(str(active_card.get("bank_name") or ""))
                else:
                    raw_card = self.reseller_data.get("card_number") or self.reseller_data.get("bank_card") or ""
                    card_holder = html.escape(str(self.reseller_data.get("card_holder") or ""))
                    bank_name = html.escape(str(self.reseller_data.get("bank_name") or ""))

                card_num = re.sub(r"\D", "", str(raw_card))

                if not card_num:
                    msg = "💳 جهت پرداخت و دریافت شماره کارت، با پشتیبانی تماس حاصل فرمایید."
                    buttons = [
                        [InlineKeyboardButton("◀️ بازگشت", callback_data=f"r_conf_{plan_id}"), InlineKeyboardButton("❌ انصراف", callback_data="r_cancel_buy")]
                    ]
                    kb = InlineKeyboardMarkup(buttons)
                    await query.edit_message_text(msg, reply_markup=kb, parse_mode="HTML")
                    return

                # صدور فاکتور هوشمند با ارقام خرد یکتا برای تایید آنی با پیامک بانک اختصاصی نماینده
                sms_cfg = db.get_reseller_bank_sms_config(r_id)
                digits = sms_cfg.get("digits", 3) or 3
                timeout = sms_cfg.get("timeout", 15) or 15
                target_c = active_card or {"card_number": card_num, "card_holder": card_holder, "bank_name": bank_name}

                invoice = db.create_smart_invoice(
                    sub_id=0,
                    plan_id=plan_id,
                    reseller_id=r_id,
                    base_amount=price,
                    target_card=target_c,
                    digits=digits,
                    timeout_minutes=timeout,
                    instant_activation=True
                )
                final_amount_toman = invoice["final_amount"]
                rial_price = final_amount_toman * 10
                rial_fmt = f"{rial_price:,}"
                toman_fmt = f"{final_amount_toman:,}"

                context.user_data["buying_plan_id"] = plan_id
                context.user_data["buying_price"] = final_amount_toman
                context.user_data["buying_order_id"] = invoice["order_id"]
                context.user_data["waiting_for_card_receipt"] = True
                context.user_data["pending_card_invoice"] = {
                    "order_id": invoice["order_id"],
                    "plan_id": plan_id,
                    "plan_name": pname,
                    "amount": final_amount_toman,
                    "account_name": account_name,
                    "card_num": card_num,
                    "reseller_id": r_id
                }

                msg = f"💳 <b>پرداخت خودکار کارت به کارت</b>\n\n"
                msg += f"📦 پلن: <b>{pname}</b>\n"
                msg += f"👤 نام اکانت: <code>{html.escape(account_name)}</code>\n"
                msg += f"📊 حجم: <b>{vol_str}</b> | ⏳ مدت: <b>{days} روز</b>\n\n"
                msg += f"💰 <b>مبلغ دقیق قابل واریز (به ریال):</b>\n"
                msg += f"<code>{rial_price}</code> ریال (<b>{rial_fmt} ریال</b>)\n"
                msg += f"<i>معادل: {toman_fmt} تومان</i>\n\n"

                msg += "💳 <b>اطلاعات کارت جهت واریز:</b>\n"
                msg += f"شماره کارت:\n<code>{card_num}</code>\n"
                if card_holder:
                    msg += f"به نام: <b>{card_holder}</b>\n"
                if bank_name:
                    msg += f"بانک: <b>{bank_name}</b>\n"
                msg += "\n⚡ <b>نکته بسیار مهم درباره تایید خودکار:</b>\n"
                msg += "سیستم مجهز به <b>تایید خودکار با پیامک بانکی اختصاصی نماینده</b> است. به دلیل وجود <b>ارقام خرد تصادفی</b> در مبلغ جهت شناسایی واریزی شما، لطفاً مبلغ را با دکمه <b>«کپی مبلغ به ریال»</b> بردارید و در همراه بانک پیست فرمایید تا اشتباهی رخ ندهد.\n\n"
                msg += "⚠️ <b>بعد از پرداخت، متن رسید یا تصویر رسید را ارسال کنید.</b>"

                buttons = [
                    [InlineKeyboardButton("📋 کپی شماره کارت", copy_text=CopyTextButton(card_num))],
                    [InlineKeyboardButton(f"💰 کپی مبلغ به ریال ({rial_fmt} ریال)", copy_text=CopyTextButton(str(rial_price)))],
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

            bot_profit = max(0, price - wholesale_cost)
            db.deduct_reseller_balance(
                r_id, wholesale_cost, pname, account_name,
                selling_price=price, profit_margin=bot_profit, created_by="bot"
            )

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
                reseller_id=r_id,
                created_by="bot"
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
            """دریافت تصویر فیش از مشتری و یا فیش شارژ پنل توسط خود نماینده"""
            user = update.effective_user
            if not update.message.photo:
                return

            # فیش خرید شارژ/بسته توسط نماینده
            if context.user_data.get("waiting_reseller_bundle_receipt"):
                bundle_id = context.user_data.pop("waiting_reseller_bundle_receipt")
                bundle = db.get_reseller_credit_bundle(bundle_id) or {}
                pname = bundle.get("title", "بسته اعتباری")
                amount = bundle.get("price", 0)
                credit = bundle.get("credit", amount)
                import random
                order_id = f"R_BUNDLE_PHOTO_{r_id}_{int(datetime.now().timestamp())}_{random.randint(100, 999)}"
                now_iso = get_now_iso()

                photo = update.message.photo[-1]
                photo_file_id = photo.file_id

                saved_receipt_filename = None
                try:
                    receipts_dir = Path("data/receipts")
                    receipts_dir.mkdir(parents=True, exist_ok=True)
                    tg_file = await photo.get_file()
                    saved_receipt_filename = f"receipt_{order_id}.jpg"
                    await tg_file.download_to_drive(receipts_dir / saved_receipt_filename)
                except Exception as e:
                    logger.warning(f"Could not download bundle receipt photo: {e}")

                conn = db.get_connection()
                conn.execute("""
                    INSERT OR REPLACE INTO transactions (
                        order_id, user_id, username, plan_name, amount, status, gateway,
                        tracking_code, reseller_id, is_renewal, account_name, source, receipt_image, receipt_file_type, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, 'pending', 'bundle_reseller', ?, ?, 0, ?, 'reseller_panel_topup', ?, ?, ?, ?)
                """, (
                    order_id, user.id, user.username or str(user.id), f"بسته {pname}",
                    amount, f"فیش عکس {order_id}", r_id, f"شارژ {credit:,} تومان",
                    saved_receipt_filename or photo_file_id, "photo", now_iso, now_iso
                ))
                conn.commit()
                conn.close()

                admin_tg = db.get_setting("admin_telegram_id") or ADMIN_ID
                if admin_tg:
                    adm_kb = InlineKeyboardMarkup([
                        [
                            InlineKeyboardButton("✅ تایید و شارژ کیف پول", callback_data=f"adm_pay_app_{order_id}"),
                            InlineKeyboardButton("❌ رد فیش", callback_data=f"adm_pay_rej_{order_id}")
                        ]
                    ])
                    adm_msg = (
                        f"📦 <b>درخواست شارژ پنل نماینده (فیش بانکی)</b>\n\n"
                        f"👤 نماینده: <b>{html.escape(str(self.reseller_data.get('name') or user.first_name))}</b> (کد #{r_id})\n"
                        f"📋 بسته: <b>{html.escape(str(pname))}</b>\n"
                        f"💰 مبلغ پرداختی: <b>{amount:,} تومان</b>\n"
                        f"🎁 اعتبار شارژ: <b>{credit:,} تومان</b>\n"
                        f"🆔 کد سفارش: <code>{order_id}</code>"
                    )
                    try:
                        await context.bot.send_photo(chat_id=int(admin_tg), photo=photo_file_id, caption=adm_msg, reply_markup=adm_kb, parse_mode="HTML")
                    except Exception as e_adm:
                        logger.error(f"Failed to notify admin of reseller bundle receipt photo: {e_adm}")

                await update.message.reply_text(
                    f"✅ <b>رسید پرداخت شما برای بسته «{pname}» با موفقیت دریافت شد.</b>\n"
                    f"پس از بررسی و تایید مدیریت، کیف پول پنل شما به مبلغ <b>{credit:,} تومان</b> شارژ خواهد شد.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به پنل مدیریت", callback_data="res_adm_menu")]]),
                    parse_mode="HTML"
                )
                return

            p_inv = context.user_data.pop("pending_card_invoice", None) or {}
            context.user_data.pop("waiting_for_card_receipt", None)

            plan_id = p_inv.get("plan_id") or context.user_data.get("buying_plan_id")
            price = p_inv.get("amount") or context.user_data.get("buying_price", 0)
            account_name = p_inv.get("account_name") or context.user_data.get("buying_account_name") or f"r{r_id}_u{user.id}"

            if not plan_id:
                await update.message.reply_text("⚠️ لطفاً ابتدا از بخش «🛍️ خرید اشتراک» یک پلن را انتخاب کرده و سپس فیش واریزی را ارسال کنید.")
                return

            photo = update.message.photo[-1]
            photo_file_id = photo.file_id
            order_id = p_inv.get("order_id") or context.user_data.get("buying_order_id") or f"R{r_id}_{int(datetime.now().timestamp())}_{user.id % 1000}"

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

            now_iso = get_now_iso()
            conn = db.get_connection()
            conn.execute("""
                INSERT OR REPLACE INTO transactions (
                    order_id, user_id, username, plan_name, amount, status, gateway,
                    tracking_code, reseller_id, is_renewal, account_name, source,
                    receipt_image, receipt_file_type, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'pending', 'card_reseller', ?, ?, 0, ?, 'reseller_bot', ?, ?, ?, ?)
            """, (
                order_id, user.id, user.username or user.first_name, pname,
                price, f"فیش عکس {order_id}", r_id, account_name,
                saved_receipt_filename or photo_file_id, "photo", now_iso, now_iso
            ))
            conn.commit()
            conn.close()

            await update.message.reply_text(
                "✅ <b>فیش واریزی شما با موفقیت دریافت شد.</b>\n\n"
                "فیش واریزی جهت بررسی و تایید برای پشتیبانی ارسال گردید و پس از تایید، اشتراک به صورت خودکار برای شما فعال و ارسال خواهد شد. سپاس از صبوری شما.",
                parse_mode="HTML"
            )

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
            await notify_reseller_admins(context.bot, ["main", "finance"], notif_text, photo=photo_file_id, reply_markup=app_kb)

        async def reseller_approve_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
            """تایید پرداخت توسط نماینده و ساخت خودکار اکانت در هیدیفای"""
            query = update.callback_query
            await query.answer()

            caller_id = update.effective_user.id
            is_adm, role = check_admin_access(caller_id)
            if not is_adm or role not in ("main", "finance"):
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
                    reseller_id=r_id,
                    created_by="bot"
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

            elif data.startswith("res_pay_app_"):
                order_id = data.replace("res_pay_app_", "")
                conn = db.get_connection()
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM transactions WHERE (order_id=? OR id=?) AND reseller_id=?", (order_id, order_id, r_id))
                tx_row = cursor.fetchone()
                conn.close()

                if not tx_row:
                    await query.answer("❌ تراکنش یافت نشد یا متعلق به شما نیست.", show_alert=True)
                    return

                tx_data = dict(tx_row)
                if tx_data.get("status") == "approved":
                    await query.answer("⚠️ این تراکنش قبلاً تایید شده است.", show_alert=True)
                    return

                user_id = tx_data.get("user_id") or 0
                plan_name = tx_data.get("plan_name", "اشتراک")
                plans = db.get_reseller_plans(r_id)
                selected_plan = next((p for p in plans if p.get("name") == plan_name or p.get("display_name") == plan_name or p.get("master_name") == plan_name or str(p.get("id")) == str(tx_data.get("plan_id"))), None)
                if not selected_plan and plans:
                    selected_plan = plans[0]

                vol = selected_plan.get("display_data_limit") if selected_plan and selected_plan.get("display_data_limit") is not None else (selected_plan.get("data_limit") if selected_plan else 30)
                days = selected_plan.get("display_duration") if selected_plan and selected_plan.get("display_duration") is not None else (selected_plan.get("duration") if selected_plan else 30)
                original_price = selected_plan.get("display_price") or selected_plan.get("price") if selected_plan else tx_data.get("amount", 0)

                stats = db.get_reseller_stats(r_id)
                master_base = (selected_plan.get("master_price") or original_price) if selected_plan else original_price
                wholesale_cost = selected_plan.get("wholesale_price") if selected_plan and selected_plan.get("wholesale_price") is not None else (master_base - int((master_base * discount) / 100))

                if stats["balance"] < wholesale_cost:
                    await query.answer(f"❌ موجودی کیف پول شما کافی نیست!\nموجودی: {stats['balance']:,} تومان | نیاز: {wholesale_cost:,} تومان", show_alert=True)
                    return

                is_renewal = bool(tx_data.get("is_renewal"))
                renew_sub_id = tx_data.get("renew_sub_id")
                target_sub = None
                if is_renewal and renew_sub_id:
                    target_sub = db.get_reseller_subscription(r_id, renew_sub_id) or db.get_subscription(renew_sub_id)

                res_profit = max(0, original_price - wholesale_cost)
                account_name = tx_data.get("account_name") or (target_sub.get("account_name") if target_sub else f"r{r_id}_u{user_id}_{int(datetime.now().timestamp()) % 10000}")
                sub_url = ""

                db.deduct_reseller_balance(r_id, wholesale_cost, plan_name, account_name, selling_price=original_price, profit_margin=res_profit, created_by="Telegram Bot (نماینده)")

                if target_sub:
                    smart_inv = db.get_smart_invoice_by_order_id(order_id)
                    instant_act = bool(smart_inv.get("instant_activation", 1)) if smart_inv else True
                    if instant_act and target_sub.get("hidify_uuid"):
                        try:
                            r_client = get_reseller_hidify_client(r_id)
                            await r_client.update_user(
                                uuid=target_sub["hidify_uuid"],
                                usage_limit_gb=float(vol) if vol > 0 else None,
                                package_days=int(days),
                                enable=True
                            )
                        except Exception as e_ren:
                            logger.error(f"Error renewing user in Hiddify: {e_ren}")

                    plan_id_val = str(selected_plan.get("id") or 1) if selected_plan else "1"
                    db.renew_reseller_subscription(
                        reseller_id=r_id,
                        sub_id=target_sub["id"],
                        plan_id=plan_id_val,
                        cost=wholesale_cost,
                        instant_activate=instant_act,
                        payment_source="wallet",
                        selling_price=original_price,
                        profit_margin=res_profit,
                        creator="Telegram Bot (نماینده)"
                    )
                    sub_uuid = target_sub.get("hidify_uuid") or str(target_sub["id"])
                    if HIDIFY_PANEL_URL and sub_uuid:
                        sub_url = f"{HIDIFY_PANEL_URL}/{HIDIFY_PROXY_PATH}/{sub_uuid}/"
                else:
                    h_res = None
                    try:
                        r_client = get_reseller_hidify_client(r_id)
                        h_res = await r_client.create_user(
                            name=account_name,
                            package_days=int(days),
                            usage_limit_gb=float(vol) if vol > 0 else None,
                            comment=f"[RESELLER_ID: #{r_id}] TG: {user_id} | {account_name}"
                        )
                    except Exception as e:
                        logger.error(f"Hiddify creation error: {e}")

                    uuid_val = h_res.get("uuid") if h_res else None
                    if uuid_val and HIDIFY_PANEL_URL:
                        sub_url = f"{HIDIFY_PANEL_URL}/{HIDIFY_PROXY_PATH}/{uuid_val}/"
                    else:
                        sub_url = f"https://vpn.service/sub/{account_name}"

                    plan_id_val = str(selected_plan.get("id") or 1) if selected_plan else "1"
                    db.save_subscription(
                        telegram_id=user_id,
                        hidify_uuid=uuid_val,
                        plan_id=plan_id_val,
                        plan_name=plan_name,
                        data_limit=float(vol),
                        duration=int(days),
                        status="active",
                        account_name=account_name,
                        account_comment=f"Reseller #{r_id} Bot",
                        reseller_id=r_id,
                        created_by="bot"
                    )

                now_iso = get_now_iso()
                conn = db.get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE transactions SET status='approved', processed_by=?, processed_at=?, updated_at=? WHERE (order_id=? OR id=?) AND reseller_id=?",
                    (f"Telegram Bot (نماینده #{r_id})", now_iso, now_iso, order_id, order_id, r_id)
                )
                conn.commit()
                conn.close()

                if str(order_id).startswith("INV"):
                    try:
                        db.mark_smart_invoice_paid(order_id, tracking_code=str(tx_data.get("tracking_code") or order_id))
                    except Exception:
                        pass

                brand = self.reseller_data.get("brand_name") or "پشتیبانی"
                if user_id and int(user_id) > 0:
                    try:
                        c_msg = (
                            f"🎉 <b>پرداخت شما تایید شد! اشتراک {brand} فعال گردید:</b>\n\n"
                            f"📦 پلن: <b>{plan_name}</b>\n"
                            f"👤 نام اکانت: <code>{html.escape(str(account_name))}</code>\n"
                            f"📊 حجم: <b>{vol} گیگابایت</b> | ⏳ مدت: <b>{days} روز</b>\n"
                            + (f"🔗 لینک اتصال:\n<code>{sub_url}</code>\n" if sub_url else "")
                        )
                        await context.bot.send_message(chat_id=int(user_id), text=c_msg, parse_mode="HTML")
                    except Exception as e_u:
                        logger.error(f"Failed to notify customer in res_pay_app: {e_u}")

                msg_text = query.message.text_html or query.message.caption_html or query.message.text or ""
                done_msg = f"{msg_text}\n\n✅ <b>پرداخت سفارش {order_id} تایید شد و اشتراک فعال گردید.</b>"
                if query.message.photo or query.message.document:
                    await query.edit_message_caption(caption=done_msg, parse_mode="HTML")
                else:
                    await query.edit_message_text(text=done_msg, parse_mode="HTML")

            elif data.startswith("res_pay_rej_"):
                order_id = data.replace("res_pay_rej_", "")
                now_iso = get_now_iso()
                conn = db.get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE transactions SET status='rejected', processed_by=?, processed_at=?, updated_at=? WHERE (order_id=? OR id=?) AND reseller_id=?",
                    (f"Telegram Bot (نماینده #{r_id})", now_iso, now_iso, order_id, order_id, r_id)
                )
                conn.commit()
                conn.close()

                tx_data = db.get_transaction_by_order_id(order_id)
                user_id = tx_data.get("user_id") if tx_data else None
                if user_id and int(user_id) > 0:
                    try:
                        await context.bot.send_message(
                            chat_id=int(user_id),
                            text=f"❌ متأسفانه واریزی شما برای سفارش {order_id} تایید نشد. جهت راهنمایی با پشتیبانی تماس بگیرید."
                        )
                    except Exception:
                        pass

                msg_text = query.message.text_html or query.message.caption_html or query.message.text or ""
                done_msg = f"{msg_text}\n\n❌ <b>پرداخت سفارش {order_id} توسط شما رد شد.</b>"
                if query.message.photo or query.message.document:
                    await query.edit_message_caption(caption=done_msg, parse_mode="HTML")
                else:
                    await query.edit_message_text(text=done_msg, parse_mode="HTML")

        async def reseller_ticket_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
            """پاسخگویی سریع، ارسال پاسخ‌های آماده و بستن تیکت توسط نماینده از تلگرام"""
            query = update.callback_query
            await query.answer()
            data = query.data
            user = update.effective_user
            is_adm, role = check_admin_access(user.id)
            if not is_adm or role not in ("main", "support"):
                await query.answer("⛔ شما دسترسی مدیریت این تیکت را ندارید.", show_alert=True)
                return

            if data.startswith("res_reply_tkt_"):
                ticket_id = int(data.replace("res_reply_tkt_", ""))
                context.user_data["reseller_replying_ticket_id"] = ticket_id
                await query.message.reply_text(
                    f"✍️ لطفاً متن پاسخ خود برای تیکت <b>#{ticket_id}</b> را ارسال فرمایید:\n"
                    f"(یا از دستور <code>/reply_ticket {ticket_id} متن پاسخ</code> استفاده نمایید)",
                    parse_mode="HTML"
                )

            elif data.startswith("res_canned_tkt_"):
                ticket_id = int(data.replace("res_canned_tkt_", ""))
                canned_options = [
                    (1, "✅ مشکل شما بررسی و رفع شد."),
                    (2, "💳 واریز تمدید شما تایید و اشتراک فعال گردید."),
                    (3, "🔄 لطفاً نرم‌افزار را بروز کرده و کانفیگ را آپدیت نمایید."),
                    (4, "📊 اشتراک شما بررسی شد و فعال و معتبر است."),
                    (5, "⏳ پیام شما در دست بررسی است، به زودی رفع می‌شود.")
                ]
                kb_rows = []
                for idx, text in canned_options:
                    kb_rows.append([InlineKeyboardButton(text, callback_data=f"res_canned_send_{ticket_id}_{idx}")])
                kb_rows.append([InlineKeyboardButton("◀️ انصراف", callback_data=f"res_canned_cancel_{ticket_id}")])
                await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(kb_rows))

            elif data.startswith("res_canned_send_"):
                parts = data.split("_")
                ticket_id = int(parts[3])
                idx = int(parts[4])
                canned_map = {
                    1: "✅ مشکل شما بررسی و رفع شد.",
                    2: "💳 واریز تمدید شما تایید و اشتراک فعال گردید.",
                    3: "🔄 لطفاً نرم‌افزار را بروز کرده و کانفیگ را آپدیت نمایید.",
                    4: "📊 اشتراک شما بررسی شد و فعال و معتبر است.",
                    5: "⏳ پیام شما در دست بررسی است، به زودی رفع می‌شود."
                }
                chosen_text = canned_map.get(idx, "پیام بررسی شد.")
                reseller_info = db.get_reseller(r_id) if r_id else None
                s_name = (reseller_info.get("name") if reseller_info else None) or "پشتیبانی"
                db.add_ticket_message(
                    ticket_id=ticket_id,
                    sender_type="reseller",
                    message=chosen_text,
                    sender_id=r_id,
                    sender_name=s_name,
                    new_status="replied"
                )
                ticket = db.get_ticket(ticket_id)
                cust_tg = ticket.get("telegram_id") or ticket.get("user_id") if ticket else None
                if cust_tg and int(cust_tg) > 0:
                    try:
                        cust_msg = (
                            f"💬 <b>پاسخ پشتیبانی به تیکت #{ticket_id}:</b>\n\n"
                            f"{chosen_text}\n\n"
                            f"──────────────\n"
                            f"جهت ارسال پیام مجدد از پرتال یا ربات استفاده نمایید."
                        )
                        await context.bot.send_message(chat_id=int(cust_tg), text=cust_msg, parse_mode="HTML")
                    except Exception as e_c:
                        logger.error(f"Error sending canned reply to customer {cust_tg}: {e_c}")
                
                orig_text = query.message.text_html or query.message.caption_html or query.message.text or ""
                done_msg = f"{orig_text}\n\n✅ <b>پاسخ آماده برای تیکت #{ticket_id} ارسال شد:</b>\n«{chosen_text}»"
                if query.message.photo or query.message.document:
                    await query.edit_message_caption(caption=done_msg, parse_mode="HTML")
                else:
                    await query.edit_message_text(text=done_msg, parse_mode="HTML")

            elif data.startswith("res_canned_cancel_"):
                ticket_id = int(data.replace("res_canned_cancel_", ""))
                r_kb = InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("✍️ پاسخ متنی", callback_data=f"res_reply_tkt_{ticket_id}"),
                        InlineKeyboardButton("⚡ پاسخ‌های آماده", callback_data=f"res_canned_tkt_{ticket_id}")
                    ],
                    [
                        InlineKeyboardButton("🔒 بستن تیکت", callback_data=f"res_close_tkt_{ticket_id}")
                    ]
                ])
                await query.edit_message_reply_markup(reply_markup=r_kb)

            elif data.startswith("res_close_tkt_"):
                ticket_id = int(data.replace("res_close_tkt_", ""))
                db.close_ticket(ticket_id)
                orig_text = query.message.text_html or query.message.caption_html or query.message.text or ""
                done_msg = f"{orig_text}\n\n🔒 <b>تیکت #{ticket_id} با موفقیت بسته شد.</b>"
                if query.message.photo or query.message.document:
                    await query.edit_message_caption(caption=done_msg, parse_mode="HTML")
                else:
                    await query.edit_message_text(text=done_msg, parse_mode="HTML")

        async def reseller_reply_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
            """دستور ارسال پاسخ تیکت: /reply_ticket [شماره تیکت] [متن پاسخ]"""
            user = update.effective_user
            is_adm, role = check_admin_access(user.id)
            if not is_adm or role not in ("main", "support"):
                return
            args = context.args
            if not args or len(args) < 2:
                await update.message.reply_text("💡 فرمت دستور:\n<code>/reply_ticket [شماره تیکت] [متن پاسخ]</code>", parse_mode="HTML")
                return
            try:
                ticket_id = int(args[0])
            except ValueError:
                await update.message.reply_text("❌ شماره تیکت باید عدد باشد.")
                return
            reply_text = " ".join(args[1:])
            reseller_info = db.get_reseller(r_id) if r_id else None
            s_name = (reseller_info.get("name") if reseller_info else None) or "پشتیبانی"
            db.add_ticket_message(
                ticket_id=ticket_id,
                sender_type="reseller",
                message=reply_text,
                sender_id=r_id,
                sender_name=s_name,
                new_status="replied"
            )
            ticket = db.get_ticket(ticket_id)
            cust_tg = ticket.get("telegram_id") or ticket.get("user_id") if ticket else None
            if cust_tg and int(cust_tg) > 0:
                try:
                    cust_msg = (
                        f"💬 <b>پاسخ پشتیبانی به تیکت #{ticket_id}:</b>\n\n"
                        f"{html.escape(reply_text)}\n\n"
                        f"──────────────\n"
                        f"جهت ارسال پیام مجدد، پیام خود را با <code>تیکت: متن پیام</code> ارسال کنید."
                    )
                    await context.bot.send_message(chat_id=int(cust_tg), text=cust_msg, parse_mode="HTML")
                except Exception as e_c:
                    logger.error(f"Error sending reply to customer {cust_tg}: {e_c}")
            await update.message.reply_text(f"✅ پاسخ شما به تیکت #{ticket_id} با موفقیت ثبت و ارسال شد.")

        async def my_subs_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
            """نمایش کامل وضعیت اشتراک‌های کاربر با استعلام زنده از سرور هیدیفای نماینده"""
            user = update.effective_user
            if not user:
                return

            try:
                subs = db.get_user_subscriptions(user.id, reseller_id=r_id)
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
                user_subs = db.get_user_subscriptions(update.effective_user.id, reseller_id=r_id)
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
                user_subs = db.get_user_subscriptions(update.effective_user.id, reseller_id=r_id)
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
                    emoji = get_plan_telegram_emoji(p, pid)

                    btn_text = f"{emoji} {pname} | {vol_str} - {days} روز ({price:,} تومان)"
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
                f"📖 <b>مرکز آموزش و راهنمای جامع اتصال {brand_name}</b>\n\n"
                "برای اتصال آسان یا رفع هرگونه اختلال و قطعی، روش مورد نظر خود را انتخاب نمایید:\n\n"
                "📱 <b>اندروید:</b> v2rayNG, Hiddify, Happ, NekoBox\n"
                "🍏 <b>آیفون و آیپد:</b> Streisand, FoXray, V2Box, Shadowrocket\n"
                "💻 <b>ویندوز و مک:</b> v2rayN, Hiddify, Nekoray\n"
                "📺 <b>تلویزیون هوشمند:</b> Android TV, Spark\n"
                "🌐 <b>مودم و روتر:</b> OpenWrt, MikroTik"
            )
            buttons = [
                [InlineKeyboardButton("🧭 راهنمای قدم‌به‌قدم حل مشکل (داخل تلگرام)", callback_data="wiz_tb_start")],
                [InlineKeyboardButton("🚀 راهنمای قدم‌به‌قدم اتصال (داخل تلگرام)", callback_data="wiz_conn_start")],
                [InlineKeyboardButton("🌐 مشاهده آموزش‌های تصویری تمام دستگاه‌ها (وب)", url=tutorial_url)],
                [InlineKeyboardButton("🛠️ سامانه آنلاین عیب‌یابی هوشمند (وب)", url=troubleshoot_url)]
            ]
            kb = InlineKeyboardMarkup(buttons)
            await update.message.reply_text(guide_text, reply_markup=kb, parse_mode="HTML")

        async def reseller_wizard_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
            """مدیریت ویزاردهای تعاملی قدم‌به‌قدم عیب‌یابی و اتصال در ربات نماینده"""
            query = update.callback_query
            await query.answer()
            data = query.data

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

            if data == "wiz_menu":
                help_text = (
                    "📖 <b>مرکز آموزش تصویری و راهنمای اتصال</b>\n\n"
                    "برای مشاهده آموزش مرحله‌به‌مرحله و رفع سریع هرگونه مشکل، روش مورد نظر خود را انتخاب نمایید:"
                )
                buttons = [
                    [InlineKeyboardButton("🧭 راهنمای قدم‌به‌قدم حل مشکل (داخل تلگرام)", callback_data="wiz_tb_start")],
                    [InlineKeyboardButton("🚀 راهنمای قدم‌به‌قدم اتصال (داخل تلگرام)", callback_data="wiz_conn_start")],
                    [InlineKeyboardButton("🌐 مشاهده آموزش‌های تصویری جامع (وب)", url=tutorial_url)],
                    [InlineKeyboardButton("🛠️ سامانه آنلاین عیب‌یابی هوشمند (وب)", url=troubleshoot_url)]
                ]
                return await query.edit_message_text(help_text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="HTML")

            if data == "wiz_tb_start":
                text = (
                    "🧭 <b>سامانه هوشمند عیب‌یابی اتصال (گام ۱ از ۶)</b>\n\n"
                    "لطفاً دستگاهی که در اتصال آن مشکل دارید را انتخاب فرمایید:"
                )
                buttons = [
                    [InlineKeyboardButton("📱 گوشی اندروید (Samsung, Xiaomi, ...)", callback_data="wiz_tb_dev_android")],
                    [InlineKeyboardButton("🍏 آیفون یا آیپد (iOS)", callback_data="wiz_tb_dev_ios")],
                    [InlineKeyboardButton("💻 کامپیوتر یا لپ‌تاپ ویندوز", callback_data="wiz_tb_dev_windows")],
                    [InlineKeyboardButton("🖥️ مک‌بوک و مک (macOS)", callback_data="wiz_tb_dev_macos")],
                    [InlineKeyboardButton("📺 تلویزیون هوشمند (Android TV)", callback_data="wiz_tb_dev_tv")],
                    [InlineKeyboardButton("◀️ بازگشت", callback_data="wiz_menu")]
                ]
                return await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="HTML")

            if data.startswith("wiz_tb_dev_"):
                device = data.replace("wiz_tb_dev_", "")
                text = (
                    "📶 <b>بررسی بسته اینترنت (گام ۲ از ۶)</b>\n\n"
                    "گاهی با نزدیک شدن به اتمام حجم بسته، اپراتورها پکت‌های اینترنت را به صفحه خرید شارژ هدایت می‌کنند که مانع اتصال VPN می‌شود.\n\n"
                    "کدهای استعلام: همراه اول `#10*100*` | ایرانسل `#4*1*555*` | رایتل `#144*`\n\n"
                    "وضعیت بسته اینترنت خود را مشخص کنید:"
                )
                buttons = [
                    [InlineKeyboardButton("بسته اینترنت من فعال است و حجم دارد 🟢", callback_data=f"wiz_tb_pkg_ok_{device}")],
                    [InlineKeyboardButton("بسته‌ام تمام شده / نیاز به شارژ دارم 🔴", callback_data=f"wiz_tb_pkg_empty_{device}")],
                    [InlineKeyboardButton("◀️ مرحله قبل", callback_data="wiz_tb_start")]
                ]
                return await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="HTML")

            if data.startswith("wiz_tb_pkg_empty_"):
                device = data.replace("wiz_tb_pkg_empty_", "")
                text = (
                    "⚠️ <b>علت مشکل: اتمام بسته اینترنت</b>\n\n"
                    "لطفاً ابتدا بسته اینترنت جدید خریداری فرمایید. سپس دستگاه را ۱۰ ثانیه روی <b>حالت پرواز (Airplane Mode)</b> قرار داده و خارج نمایید."
                )
                buttons = [
                    [InlineKeyboardButton("بسته را شارژ کردم، ادامه عیب‌یابی 🔄", callback_data=f"wiz_tb_pkg_ok_{device}")],
                    [InlineKeyboardButton("◀️ مرحله قبل", callback_data=f"wiz_tb_dev_{device}")]
                ]
                return await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="HTML")

            if data.startswith("wiz_tb_pkg_ok_"):
                device = data.replace("wiz_tb_pkg_ok_", "")
                text = (
                    "🛡️ <b>بررسی اعتبار و حجم اشتراک VPN (گام ۳ از ۶)</b>\n\n"
                    "با دکمه «اشتراک‌های من» یا باز کردن لینک اشتراک، مطمئن شوید حجم گیگابایتی یا مهلت روزهای اشتراک شما تمام نشده باشد.\n\n"
                    "وضعیت اشتراک شما:"
                )
                buttons = [
                    [InlineKeyboardButton("اشتراکم معتبر است و زمان و حجم دارد ✅", callback_data=f"wiz_tb_sub_ok_{device}")],
                    [InlineKeyboardButton("حجم یا زمان اشتراکم به پایان رسیده 🔄", callback_data=f"wiz_tb_sub_empty_{device}")],
                    [InlineKeyboardButton("◀️ مرحله قبل", callback_data=f"wiz_tb_dev_{device}")]
                ]
                return await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="HTML")

            if data.startswith("wiz_tb_sub_empty_"):
                device = data.replace("wiz_tb_sub_empty_", "")
                text = (
                    "🔄 <b>اتمام اعتبار اشتراک VPN</b>\n\n"
                    "سرویس شما به پایان رسیده است. جهت تمدید، می‌توانید از منوی اصلی ربات دکمه تمدید اشتراک یا خرید اشتراک جدید را انتخاب کنید."
                )
                buttons = [
                    [InlineKeyboardButton("اشتراک را تمدید کردم، ادامه عیب‌یابی 🔄", callback_data=f"wiz_tb_sub_ok_{device}")],
                    [InlineKeyboardButton("◀️ مرحله قبل", callback_data=f"wiz_tb_pkg_ok_{device}")]
                ]
                return await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="HTML")

            if data.startswith("wiz_tb_sub_ok_"):
                device = data.replace("wiz_tb_sub_ok_", "")
                text = (
                    "⏱️ <b>تنظیم ساعت و تاریخ سیستم (گام ۴ از ۶)</b>\n\n"
                    "پروتکل‌های نسل جدید بر پایه زمان استاندارد جهانی کار می‌کنند. اختلاف حتی ۶۰ ثانیه‌ای ساعت باعث عدم اتصال می‌شود!\n\n"
                    "در تنظیمات تاریخ و ساعت دستگاه گزینه <code>Set Automatically</code> را خاموش و مجدداً روشن فرمایید (در ویندوز دکمه Sync now را بزنید)."
                )
                buttons = [
                    [InlineKeyboardButton("ساعت و تاریخ دقیقاً با ساعت رسمی همگام است ⏱️", callback_data=f"wiz_tb_time_ok_{device}")],
                    [InlineKeyboardButton("◀️ مرحله قبل", callback_data=f"wiz_tb_pkg_ok_{device}")]
                ]
                return await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="HTML")

            if data.startswith("wiz_tb_time_ok_"):
                device = data.replace("wiz_tb_time_ok_", "")
                text = (
                    "📡 <b>انتخاب اپراتور اینترنت (گام ۵ از ۶)</b>\n\n"
                    "در حال حاضر به کدام شبکه اینترنت متصل هستید؟"
                )
                buttons = [
                    [InlineKeyboardButton("همراه اول یا ایرانسل (سیم‌کارت) 📶", callback_data=f"wiz_tb_op_mci_{device}")],
                    [InlineKeyboardButton("اینترنت خانگی / وای‌فای (مخابرات، شاتل و...) 🌐", callback_data=f"wiz_tb_op_wifi_{device}")],
                    [InlineKeyboardButton("رایتل یا سایرین 📱", callback_data=f"wiz_tb_op_other_{device}")],
                    [InlineKeyboardButton("◀️ مرحله قبل", callback_data=f"wiz_tb_sub_ok_{device}")]
                ]
                return await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="HTML")

            if data.startswith("wiz_tb_op_mci_"):
                device = data.replace("wiz_tb_op_mci_", "")
                text = (
                    "🛡️ <b>تنظیم ضروری Fragment برای همراه اول و ایرانسل:</b>\n\n"
                    "در تنظیمات نرم‌افزار خود بخش <b>Fragment</b> را روشن کنید و مقادیر packets را روی <code>1-3</code> و length را روی <code>10-20</code> بگذارید."
                )
                buttons = [
                    [InlineKeyboardButton("تنظیمات Fragment را اعمال کردم 🛡️", callback_data=f"wiz_tb_done_{device}")],
                    [InlineKeyboardButton("◀️ مرحله قبل", callback_data=f"wiz_tb_time_ok_{device}")]
                ]
                return await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="HTML")

            if data.startswith("wiz_tb_op_wifi_"):
                device = data.replace("wiz_tb_op_wifi_", "")
                text = (
                    "🌐 <b>تنظیم DNS و IPv6 برای اینترنت خانگی:</b>\n\n"
                    "در تنظیمات برنامه VPN گزینه <b>Enable IPv6</b> را خاموش کنید و Remote DNS را روی <code>https://1.1.1.1/dns-query</code> قرار دهید."
                )
                buttons = [
                    [InlineKeyboardButton("تنظیمات DNS و IPv6 را اعمال کردم 🌐", callback_data=f"wiz_tb_done_{device}")],
                    [InlineKeyboardButton("◀️ مرحله قبل", callback_data=f"wiz_tb_time_ok_{device}")]
                ]
                return await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="HTML")

            if data.startswith("wiz_tb_op_other_"):
                device = data.replace("wiz_tb_op_other_", "")
                text = (
                    "✈️ <b>دریافت آی‌پی تازه با حالت پرواز:</b>\n\n"
                    "گوشی را ۱۰ ثانیه روی حالت پرواز قرار دهید و سپس متصل شوید."
                )
                buttons = [
                    [InlineKeyboardButton("انجام دادم و آماده تستم ✈️", callback_data=f"wiz_tb_done_{device}")],
                    [InlineKeyboardButton("◀️ مرحله قبل", callback_data=f"wiz_tb_time_ok_{device}")]
                ]
                return await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="HTML")

            if data.startswith("wiz_tb_done_"):
                text = (
                    "🔄 <b>به‌روزرسانی سرورها و تست پینگ (گام ۶ از ۶)</b>\n\n"
                    "۱. در نرم‌افزار خود گزینه Update subscription را بزنید.\n"
                    "۲. تست پینگ بگیرید و سرور با پینگ سبز را انتخاب فرمایید.\n"
                    "۳. دکمه اتصال را روشن کنید.\n\n"
                    "آیا اتصال با موفقیت برقرار شد؟"
                )
                buttons = [
                    [InlineKeyboardButton("مشکل حل شد و با موفقیت متصلم! 🎉", callback_data="wiz_tb_solved")],
                    [InlineKeyboardButton("هنوز متصل نیستم / پشتیبانی 🎧", callback_data="wiz_tb_support")],
                    [InlineKeyboardButton("◀️ شروع مجدد عیب‌یابی", callback_data="wiz_tb_start")]
                ]
                return await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="HTML")

            if data == "wiz_tb_solved":
                text = "🎉 <b>بسیار عالی!</b>\n\nخوشحالیم که مشکل اتصال شما برطرف گردید."
                buttons = [[InlineKeyboardButton("بازگشت به منوی اصلی", callback_data="r_back_plans")]]
                return await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="HTML")

            if data == "wiz_tb_support":
                sup_user = r_info.get("support_username") or db.get_setting("support_username", "")
                text = "🎧 <b>ارتباط با واحد پشتیبانی:</b>\nجهت بررسی اختصاصی، نام کاربری اشتراک و نوع خط اینترنت خود را به پشتیبانی ارسال فرمایید."
                buttons = []
                if sup_user:
                    buttons.append([InlineKeyboardButton("ارسال پیام به پشتیبانی تلگرام", url=f"https://t.me/{sup_user.lstrip('@')}")])
                buttons.append([InlineKeyboardButton("بازگشت به منوی اصلی", callback_data="r_back_plans")])
                return await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="HTML")

            # ─── ویزارد اتصال ───
            if data == "wiz_conn_start":
                text = "🚀 <b>راهنمای گام‌به‌گام راه‌اندازی و اتصال (گام ۱ از ۵)</b>\n\nسیستم‌عامل یا دستگاه خود را انتخاب فرمایید:"
                buttons = [
                    [InlineKeyboardButton("📱 اندروید", callback_data="wiz_conn_dev_android")],
                    [InlineKeyboardButton("🍏 آیفون یا آیپد", callback_data="wiz_conn_dev_ios")],
                    [InlineKeyboardButton("💻 ویندوز", callback_data="wiz_conn_dev_windows")],
                    [InlineKeyboardButton("🖥️ مک‌بوک", callback_data="wiz_conn_dev_macos")],
                    [InlineKeyboardButton("📺 تلویزیون هوشمند", callback_data="wiz_conn_dev_tv")],
                    [InlineKeyboardButton("◀️ بازگشت", callback_data="wiz_menu")]
                ]
                return await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="HTML")

            if data.startswith("wiz_conn_dev_"):
                device = data.replace("wiz_conn_dev_", "")
                app_map = {"android": ("v2rayNG", "https://github.com/2dust/v2rayNG/releases/latest"),
                           "ios": ("Streisand", "https://apps.apple.com/app/streisand/id6450534064"),
                           "windows": ("v2rayN", "https://github.com/2dust/v2rayN/releases/latest"),
                           "macos": ("FoXray", "https://apps.apple.com/app/foxray/id6448898396"),
                           "tv": ("v2rayNG TV", "https://github.com/2dust/v2rayNG/releases/latest")}
                app_name, dl_url = app_map.get(device, ("v2rayNG", "https://github.com/2dust/v2rayNG/releases/latest"))
                text = f"📲 <b>دانلود و نصب نرم‌افزار {app_name} (گام ۲ از ۵)</b>\n\nنرم‌افزار رسمی را از لینک زیر دانلود و روی دستگاه باز کنید:"
                buttons = [
                    [InlineKeyboardButton(f"دانلود {app_name}", url=dl_url)],
                    [InlineKeyboardButton("برنامه را نصب کردم، مرحله بعد 📲", callback_data=f"wiz_conn_imp_{device}")],
                    [InlineKeyboardButton("◀️ مرحله قبل", callback_data="wiz_conn_start")]
                ]
                return await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="HTML")

            if data.startswith("wiz_conn_imp_"):
                device = data.replace("wiz_conn_imp_", "")
                text = "📥 <b>وارد کردن لینک اشتراک (گام ۳ از ۵)</b>\n\n۱. لینک اشتراک خود را کپی کنید.\n۲. نرم‌افزار را باز کرده و علامت (+) بالای صفحه را بزنید.\n۳. گزینه <b>Import from clipboard</b> را لمس نمایید."
                buttons = [
                    [InlineKeyboardButton("لینک را وارد کردم، مرحله بعد 📥", callback_data=f"wiz_conn_upd_{device}")],
                    [InlineKeyboardButton("◀️ مرحله قبل", callback_data=f"wiz_conn_dev_{device}")]
                ]
                return await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="HTML")

            if data.startswith("wiz_conn_upd_"):
                device = data.replace("wiz_conn_upd_", "")
                text = "🔄 <b>به‌روزرسانی سرورها و پینگ (گام ۴ از ۵)</b>\n\n۱. در نرم‌افزار گزینه <b>Update subscription</b> را بزنید.\n۲. گزینه <b>Real delay test</b> را بزنید تا پینگ‌ها سبز شوند.\n۳. سرور با کمترین پینگ سبز را انتخاب فرمایید."
                buttons = [
                    [InlineKeyboardButton("سرورها آپدیت شدند و پینگ سبز دیدم 🔄", callback_data=f"wiz_conn_con_{device}")],
                    [InlineKeyboardButton("◀️ مرحله قبل", callback_data=f"wiz_conn_imp_{device}")]
                ]
                return await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="HTML")

            if data.startswith("wiz_conn_con_"):
                text = "🚀 <b>اتصال و استارت (گام ۵ از ۵)</b>\n\nروی دکمه اتصال کلیک فرمایید و در پنجره امنیتی OK یا Allow بزنید تا اینترنت آزاد متصل شود!"
                buttons = [
                    [InlineKeyboardButton("با موفقیت متصل شدم! 🎉", callback_data="wiz_tb_solved")],
                    [InlineKeyboardButton("متصل نشد، رفتن به عیب‌یابی 🛠️", callback_data="wiz_tb_start")],
                    [InlineKeyboardButton("◀️ شروع مجدد راهنما", callback_data="wiz_conn_start")]
                ]
                return await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="HTML")

        async def reseller_admin_panel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
            """نمایش پنل مدیریت اختصاصی نماینده در ربات اختصاصی خود"""
            user = update.effective_user
            is_adm, role = check_admin_access(user.id)
            if not is_adm:
                if update.message:
                    await update.message.reply_text("⛔ شما دسترسی مدیریت این ربات را ندارید.")
                elif update.callback_query:
                    await update.callback_query.answer("⛔ شما دسترسی مدیریت این ربات را ندارید.", show_alert=True)
                return

            reseller = db.get_reseller(r_id) or self.reseller_data
            balance = reseller.get("balance", 0)
            name = reseller.get("name") or reseller.get("brand_name") or "نماینده"
            role_title_map = {
                "main": "ادمین اصلی (دسترسی کامل)",
                "finance": "مدیر مالی و فیش‌ها",
                "support": "پشتیبانی و تیکت‌ها",
                "sales": "کارشناس فروش و اشتراک‌ها"
            }
            role_badge = role_title_map.get(role, "ادمین")

            text = (
                f"👑 <b>پنل مدیریت اختصاصی نماینده</b>\n\n"
                f"👤 نماینده: <b>{html.escape(str(name))}</b> (کد #{r_id})\n"
                f"🎖️ نقش شما: <b>{role_badge}</b>\n"
                f"💼 موجودی کیف پول پنل: <b>{balance:,} تومان</b>\n\n"
                f"لطفاً یکی از بخش‌های زیر را جهت مدیریت انتخاب فرمایید:"
            )
            kb = get_reseller_admin_keyboard(is_multibot=True, role=role)
            if update.message:
                await update.message.reply_text(text, reply_markup=kb, parse_mode="HTML")
            elif update.callback_query:
                try:
                    await update.callback_query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")
                except Exception:
                    await update.callback_query.message.reply_text(text, reply_markup=kb, parse_mode="HTML")

        async def reseller_admin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
            """مدیریت تمام رویدادها و کلیک‌های پنل ادمین اختصاصی نماینده"""
            query = update.callback_query
            try:
                await query.answer()
            except Exception:
                pass

            user = update.effective_user
            is_adm, role = check_admin_access(user.id)
            if not is_adm:
                await query.edit_message_text("⛔ شما دسترسی مدیریت این بخش را ندارید.")
                return

            data = query.data

            if data == "res_adm_menu":
                return await reseller_admin_panel_handler(update, context)

            elif data == "res_adm_stats":
                txt = get_reseller_stats_text(r_id)
                kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به پنل مدیریت", callback_data="res_adm_menu")]])
                await query.edit_message_text(txt, reply_markup=kb, parse_mode="Markdown")

            elif data == "res_adm_bundles":
                txt, kb = get_reseller_bundles_payload(r_id)
                await query.edit_message_text(txt, reply_markup=kb, parse_mode="Markdown")

            elif data.startswith("res_adm_bdl_"):
                bdl_id = data.replace("res_adm_bdl_", "")
                txt, kb = get_bundle_payment_details_payload(bdl_id, r_id)
                await query.edit_message_text(txt, reply_markup=kb, parse_mode="Markdown")

            elif data.startswith("res_adm_send_rcpt_"):
                bdl_id = data.replace("res_adm_send_rcpt_", "")
                context.user_data["waiting_reseller_bundle_receipt"] = bdl_id
                msg = (
                    "📸 <b>ارسال فیش واریزی بسته اعتباری</b>\n\n"
                    "لطفاً تصویر فیش واریزی یا شماره پیگیری / متن رسید خود را ارسال فرمایید:"
                )
                kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ انصراف", callback_data="res_adm_bundles")]])
                await query.edit_message_text(msg, reply_markup=kb, parse_mode="HTML")

            elif data == "res_adm_tickets":
                txt, kb = get_reseller_tickets_payload(r_id)
                await query.edit_message_text(txt, reply_markup=kb, parse_mode="Markdown")

            elif data.startswith("res_adm_tkt_"):
                t_id = int(data.replace("res_adm_tkt_", ""))
                txt, kb = get_reseller_ticket_detail_payload(t_id)
                await query.edit_message_text(txt, reply_markup=kb, parse_mode="Markdown")

            elif data.startswith("res_adm_trep_"):
                t_id = int(data.replace("res_adm_trep_", ""))
                context.user_data["reseller_replying_ticket_id"] = t_id
                await query.edit_message_text(
                    f"✍️ لطفاً متن پاسخ خود برای تیکت #{t_id} را تایپ و ارسال فرمایید:",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ انصراف", callback_data=f"res_adm_tkt_{t_id}")]])
                )

            elif data.startswith("res_adm_tcls_"):
                t_id = int(data.replace("res_adm_tcls_", ""))
                db.close_ticket(t_id)
                await query.edit_message_text(
                    f"🔒 تیکت #{t_id} با موفقیت بسته شد.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 لیست تیکت‌ها", callback_data="res_adm_tickets")]])
                )

            elif data == "res_adm_payments":
                txt, kb = get_reseller_payments_payload(r_id)
                await query.edit_message_text(txt, reply_markup=kb, parse_mode="Markdown")

            elif data.startswith("res_adm_pdetail_"):
                o_id = data.replace("res_adm_pdetail_", "")
                conn = db.get_connection()
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM transactions WHERE (order_id = ? OR id = ?) AND reseller_id = ?", (o_id, o_id, r_id))
                tx = cursor.fetchone()
                conn.close()
                if not tx:
                    await query.edit_message_text("❌ تراکنش یافت نشد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="res_adm_payments")]]))
                    return

                t_dict = dict(tx)
                pname = t_dict.get("plan_name", "اشتراک")
                amt = t_dict.get("amount", 0)
                u_name = t_dict.get("username") or t_dict.get("user_id")
                u_id = t_dict.get("user_id")
                pl_id = t_dict.get("plan_id") or ""
                ord_id = t_dict.get("order_id") or t_dict.get("id")

                txt = (
                    f"🔍 <b>بررسی فیش پرداختی #{t_dict.get('id')}</b>\n\n"
                    f"👤 مشتری: <b>{u_name}</b> (ID: <code>{u_id}</code>)\n"
                    f"📦 پلن: <b>{pname}</b>\n"
                    f"💰 مبلغ: <b>{amt:,} تومان</b>\n"
                    f"🆔 کد سفارش: <code>{ord_id}</code>\n"
                    f"📅 تاریخ: {t_dict.get('created_at', '')[:16].replace('T', ' ')}\n\n"
                    f"جهت تایید یا رد سفارش از گزینه‌های زیر استفاده فرمایید:"
                )
                kb = InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("✅ تایید و تحویل آنی", callback_data=f"rapprove_{ord_id}_{u_id}_{pl_id}"),
                        InlineKeyboardButton("❌ رد فیش", callback_data=f"rreject_{ord_id}_{u_id}")
                    ],
                    [InlineKeyboardButton("🔙 بازگشت به لیست فیش‌ها", callback_data="res_adm_payments")]
                ])

                rcpt_img = t_dict.get("receipt_image")
                if rcpt_img:
                    rcpt_path = Path("data/receipts") / rcpt_img
                    if rcpt_path.exists():
                        try:
                            with open(rcpt_path, "rb") as f_img:
                                await context.bot.send_photo(chat_id=user.id, photo=f_img, caption=txt, reply_markup=kb, parse_mode="HTML")
                            return
                        except Exception as e_im:
                            logger.error(f"Error sending receipt photo: {e_im}")
                await query.edit_message_text(txt, reply_markup=kb, parse_mode="HTML")

            elif data == "res_adm_create_user":
                txt, kb = get_reseller_create_user_plans_payload(r_id)
                await query.edit_message_text(txt, reply_markup=kb, parse_mode="Markdown")

            elif data.startswith("res_adm_cplan_"):
                pid = data.replace("res_adm_cplan_", "")
                context.user_data["res_create_plan_id"] = pid
                plan = db.get_reseller_plan(r_id, pid)
                pname = plan.get("display_name") or plan.get("master_name", "پلن") if plan else pid
                w_price = plan.get("wholesale_price", 0) if plan else 0
                msg = (
                    f"👤 <b>ساخت کاربر جدید با پلن «{pname}»</b>\n\n"
                    f"💰 هزینه کسر از موجودی کیف پول شما: <b>{w_price:,} تومان</b>\n\n"
                    f"لطفاً <b>نام کاربری (لاتین)</b> مدنظر برای این مشتری را ارسال فرمایید (یا <code>auto</code> را ارسال کنید تا خودکار ایجاد شود):"
                )
                kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ انصراف", callback_data="res_adm_create_user")]])
                await query.edit_message_text(msg, reply_markup=kb, parse_mode="HTML")

            elif data == "res_adm_renew_user":
                context.user_data["waiting_reseller_search_sub"] = True
                msg = (
                    "🔍 <b>تمدید اشتراک مشتری</b>\n\n"
                    "لطفاً <b>نام اکانت</b>، <b>شماره تلفن</b> یا <b>شناسه اشتراک</b> مشتری مورد نظر را ارسال فرمایید:"
                )
                kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ انصراف", callback_data="res_adm_menu")]])
                await query.edit_message_text(msg, reply_markup=kb, parse_mode="HTML")

            elif data.startswith("res_adm_rsub_"):
                sub_id = int(data.replace("res_adm_rsub_", ""))
                sub = db.get_subscription(sub_id)
                if not sub or sub.get("reseller_id") != r_id:
                    await query.edit_message_text("❌ اشتراک یافت نشد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="res_adm_menu")]]))
                    return

                plans = db.get_reseller_plans(r_id)
                acc = sub.get("account_name") or f"sub_{sub_id}"
                msg = f"🔄 <b>تمدید اشتراک «{acc}»</b>\n\nلطفاً پلن مدنظر جهت تمدید را انتخاب فرمایید:"
                btns = []
                for p in plans:
                    pid = p["plan_id"]
                    pn = p.get("display_name") or p.get("master_name", "پلن")
                    w_price = p.get("wholesale_price", 0)
                    btns.append([InlineKeyboardButton(f"📦 {pn} ({w_price:,} ت)", callback_data=f"res_adm_dorenew_{sub_id}_{pid}")])
                btns.append([InlineKeyboardButton("🔙 بازگشت", callback_data="res_adm_menu")])
                await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(btns), parse_mode="HTML")

            elif data.startswith("res_adm_dorenew_"):
                parts = data.replace("res_adm_dorenew_", "").split("_")
                if len(parts) >= 2:
                    s_id = int(parts[0])
                    p_id = parts[1]
                    plan = db.get_reseller_plan(r_id, p_id)
                    if not plan:
                        await query.edit_message_text("❌ پلن یافت نشد.")
                        return

                    w_price = plan.get("wholesale_price", 0)
                    days = plan.get("duration", 30)
                    vol = plan.get("data_limit", 0)
                    pname = plan.get("display_name") or plan.get("master_name", "پلن")

                    res = db.renew_reseller_subscription(
                        sub_id=s_id,
                        reseller_id=r_id,
                        plan_id=p_id,
                        plan_name=pname,
                        data_limit=vol,
                        duration=days,
                        cost=w_price,
                        instant_activate=True
                    )
                    if res.get("success"):
                        # به‌روزرسانی در هیدیفای
                        sub = db.get_subscription(s_id)
                        uuid_val = sub.get("hidify_uuid")
                        if uuid_val:
                            try:
                                r_client = get_reseller_hidify_client(r_id)
                                await r_client.update_user(
                                    uuid_val,
                                    usage_limit_gb=vol if vol > 0 else None,
                                    package_days=days,
                                    reset_usage=True
                                )
                            except Exception as e_h:
                                logger.error(f"Error updating hidify on renew: {e_h}")

                        await query.edit_message_text(
                            f"✅ <b>اشتراک «{sub.get('account_name')}» با موفقیت تمدید شد.</b>\n"
                            f"📦 پلن جدید: <b>{pname}</b>\n"
                            f"💰 مبلغ کسر شده: <b>{w_price:,} تومان</b>",
                            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به پنل مدیریت", callback_data="res_adm_menu")]]),
                            parse_mode="HTML"
                        )
                    else:
                        await query.edit_message_text(
                            f"❌ <b>خطا در تمدید اشتراک:</b>\n{res.get('error')}",
                            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="res_adm_menu")]]),
                            parse_mode="HTML"
                        )

            elif data == "res_adm_discounts":
                txt, kb = get_reseller_discounts_payload(r_id)
                await query.edit_message_text(txt, reply_markup=kb, parse_mode="Markdown")

            elif data == "res_adm_disc_new":
                context.user_data["waiting_reseller_new_discount"] = True
                msg = (
                    "➕ <b>ایجاد کد تخفیف جدید</b>\n\n"
                    "لطفاً کد تخفیف و درصد یا مبلغ آن را به یکی از فرمت‌های زیر ارسال فرمایید:\n\n"
                    "• درصدی: <code>YALDA 20%</code>\n"
                    "• مبلغ ثابت: <code>NOWRUZ 50000</code>"
                )
                kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ انصراف", callback_data="res_adm_discounts")]])
                await query.edit_message_text(msg, reply_markup=kb, parse_mode="HTML")

            elif data.startswith("res_adm_disctog_"):
                c_id = int(data.replace("res_adm_disctog_", ""))
                db.toggle_reseller_discount_code(r_id, c_id)
                txt, kb = get_reseller_discounts_payload(r_id)
                await query.edit_message_text(txt, reply_markup=kb, parse_mode="Markdown")

            elif data.startswith("res_adm_discdel_"):
                c_id = int(data.replace("res_adm_discdel_", ""))
                db.delete_reseller_discount_code(r_id, c_id)
                txt, kb = get_reseller_discounts_payload(r_id)
                await query.edit_message_text(txt, reply_markup=kb, parse_mode="Markdown")

            elif data == "res_adm_reports":
                txt, kb = get_reseller_reports_payload(r_id, "menu")
                await query.edit_message_text(txt, reply_markup=kb, parse_mode="Markdown")

            elif data == "res_adm_rep_sales":
                txt, kb = get_reseller_reports_payload(r_id, "sales")
                await query.edit_message_text(txt, reply_markup=kb, parse_mode="Markdown")

            elif data == "res_adm_rep_expiring":
                txt, kb = get_reseller_reports_payload(r_id, "expiring")
                await query.edit_message_text(txt, reply_markup=kb, parse_mode="Markdown")

            elif data == "res_adm_rep_top":
                txt, kb = get_reseller_reports_payload(r_id, "top")
                await query.edit_message_text(txt, reply_markup=kb, parse_mode="Markdown")

            elif data == "res_adm_settings":
                txt, kb = get_reseller_settings_payload(r_id)
                await query.edit_message_text(txt, reply_markup=kb, parse_mode="Markdown")

            elif data == "res_adm_broadcast":
                context.user_data["waiting_reseller_broadcast"] = True
                msg = (
                    "📢 <b>ارسال پیام همگانی به کاربران ربات شما</b>\n\n"
                    "لطفاً متن پیام خود را تایپ و ارسال فرمایید تا برای تمامی مشترکین ثبت‌شده در ربات اختصاصی شما ارسال شود:"
                )
                kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ انصراف", callback_data="res_adm_menu")]])
                await query.edit_message_text(msg, reply_markup=kb, parse_mode="HTML")

            elif data == "res_adm_close":
                try:
                    await query.message.delete()
                except Exception:
                    pass

        async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
            """مسیریابی هوشمند تمام کلیدهای منوی اصلی ربات نماینده"""
            text = (update.message.text or "").strip()
            if not text:
                return

            user = update.effective_user
            is_adm, role = check_admin_access(user.id)

            # ۰. بررسی پاسخ مستقیم نماینده به تیکت مشتری
            if is_adm and role in ("main", "support") and context.user_data.get("reseller_replying_ticket_id"):
                ticket_id = context.user_data.pop("reseller_replying_ticket_id")
                reseller_info = db.get_reseller(r_id) if r_id else None
                s_name = (reseller_info.get("name") if reseller_info else None) or "پشتیبانی"
                db.add_ticket_message(
                    ticket_id=ticket_id,
                    sender_type="reseller",
                    message=text,
                    sender_id=r_id,
                    sender_name=s_name,
                    new_status="replied"
                )
                ticket = db.get_ticket(ticket_id)
                cust_tg = ticket.get("telegram_id") or ticket.get("user_id") if ticket else None
                if cust_tg and int(cust_tg) > 0:
                    try:
                        cust_msg = (
                            f"💬 <b>پاسخ پشتیبانی به تیکت #{ticket_id}:</b>\n\n"
                            f"{html.escape(text)}\n\n"
                            f"──────────────\n"
                            f"جهت ارسال پیام مجدد، پیام خود را با <code>تیکت: متن پیام</code> ارسال کنید."
                        )
                        await context.bot.send_message(chat_id=int(cust_tg), text=cust_msg, parse_mode="HTML")
                    except Exception as e_c:
                        logger.error(f"Error sending reply to customer {cust_tg}: {e_c}")
                await update.message.reply_text(f"✅ پاسخ شما به تیکت #{ticket_id} با موفقیت ثبت و ارسال شد.")
                return

            # ۰.۱. دسترسی به پنل مدیریت نماینده
            if text in ("🔧 پنل مدیریت نماینده", "مدیریت نماینده", "/admin", "/manage", "/panel"):
                if is_adm:
                    return await reseller_admin_panel_handler(update, context)

            # ۰.۲. ارسال پیام همگانی توسط نماینده
            if context.user_data.get("waiting_reseller_broadcast"):
                if is_adm and role == "main":
                    context.user_data.pop("waiting_reseller_broadcast")
                    conn = db.get_connection()
                    cursor = conn.cursor()
                    cursor.execute("SELECT DISTINCT telegram_id FROM users WHERE reseller_id = ?", (r_id,))
                    u_rows = cursor.fetchall()
                    conn.close()

                    user_ids = [r[0] for r in u_rows if r[0]]
                    sent_count = 0
                    failed_count = 0
                    await update.message.reply_text(f"⏳ در حال ارسال پیام به {len(user_ids)} کاربر...")
                    for uid in user_ids:
                        try:
                            await context.bot.send_message(chat_id=uid, text=text)
                            sent_count += 1
                            await asyncio.sleep(0.05)
                        except Exception:
                            failed_count += 1

                    await update.message.reply_text(
                        f"📢 <b>ارسال پیام همگانی به پایان رسید:</b>\n\n"
                        f"✅ ارسال موفق: <b>{sent_count}</b>\n"
                        f"❌ ناموفق: <b>{failed_count}</b>",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به پنل مدیریت", callback_data="res_adm_menu")]]),
                        parse_mode="HTML"
                    )
                    return

            # ۰.۳. جستجوی اشتراک مشتری جهت تمدید
            if context.user_data.get("waiting_reseller_search_sub"):
                if is_adm and role in ("main", "sales"):
                    context.user_data.pop("waiting_reseller_search_sub")
                    subs = search_reseller_subscriptions(r_id, text)
                    if not subs:
                        await update.message.reply_text(
                            f"❌ هیچ اشتراکی مطابق با عبارت «{text}» یافت نشد.",
                            reply_markup=InlineKeyboardMarkup([
                                [InlineKeyboardButton("🔍 جستجوی مجدد", callback_data="res_adm_renew_user")],
                                [InlineKeyboardButton("🔙 بازگشت به پنل مدیریت", callback_data="res_adm_menu")]
                            ])
                        )
                        return

                    msg = f"🔍 <b>نتایج جستجو برای «{text}» ({len(subs)} نتیجه):</b>\n\n"
                    btns = []
                    for s in subs:
                        s_id = s["id"]
                        acc = s.get("account_name") or f"sub_{s_id}"
                        pn = s.get("plan_name") or "پلن"
                        st = s.get("status", "active")
                        st_icon = "🟢" if st == "active" else "🔴"
                        msg += f"{st_icon} <b>{acc}</b> (#{s_id}) | پلن: {pn}\n"
                        btns.append([InlineKeyboardButton(f"🔄 تمدید «{acc}»", callback_data=f"res_adm_rsub_{s_id}")])
                    btns.append([InlineKeyboardButton("🔙 بازگشت به پنل مدیریت", callback_data="res_adm_menu")])
                    await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(btns), parse_mode="HTML")
                    return

            # ۰.۴. ساخت دستی اشتراک مشتری توسط نماینده
            if context.user_data.get("res_create_plan_id"):
                if is_adm and role in ("main", "sales"):
                    pid = context.user_data.pop("res_create_plan_id")
                    plan = db.get_reseller_plan(r_id, pid)
                    if not plan:
                        await update.message.reply_text("❌ پلن یافت نشد.")
                        return

                    desired_name = text.strip()
                    if desired_name.lower() == "auto" or not desired_name:
                        desired_name = f"c{r_id}_{secrets.token_hex(3)}"
                    else:
                        desired_name = re.sub(r"[^a-zA-Z0-9_\-]", "", desired_name)
                        if not desired_name:
                            desired_name = f"c{r_id}_{secrets.token_hex(3)}"

                    w_price = plan.get("wholesale_price", 0)
                    days = plan.get("duration", 30)
                    vol = plan.get("data_limit", 0)
                    pname = plan.get("display_name") or plan.get("master_name", "پلن")

                    r_stats = db.get_reseller_stats(r_id) or {}
                    power = r_stats.get("total_purchasing_power", 0)
                    if power < w_price:
                        await update.message.reply_text(
                            f"❌ موجودی و اعتبار پنل شما کافی نیست!\nموجودی/اعتبار: {power:,} ت | هزینه عمده: {w_price:,} ت",
                            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💰 خرید شارژ پنل", callback_data="res_adm_bundles")]])
                        )
                        return

                    await update.message.reply_text("⏳ در حال صدور آنی اکانت در سرور هیدیفای...")
                    r_client = get_reseller_hidify_client(r_id)
                    h_res = await r_client.create_user(
                        name=desired_name,
                        usage_limit_gb=vol if vol > 0 else None,
                        package_days=days,
                        enable=True,
                        comment=f"[RESELLER_MANUAL: #{r_id}] {desired_name}"
                    )
                    uuid_val = h_res.get("uuid") if h_res else None
                    if not uuid_val:
                        await update.message.reply_text("❌ خطا در برقراری ارتباط با پنل هیدیفای. لطفاً مجدداً تلاش فرمایید.")
                        return

                    # کسر هزینه از کیف پول نماینده
                    db.deduct_reseller_balance(r_id, w_price, f"ساخت دستی کاربر {desired_name} با پلن {pname}")
                    sub_url = f"{HIDIFY_PANEL_URL}/{HIDIFY_PROXY_PATH}/{uuid_val}/"

                    sub_id = db.save_subscription(
                        telegram_id=user.id,
                        hidify_uuid=uuid_val,
                        plan_id=pid,
                        plan_name=pname,
                        data_limit=vol,
                        duration=days,
                        status="active",
                        account_name=desired_name,
                        account_comment=f"Created by Reseller #{r_id}",
                        reseller_id=r_id,
                        created_by="reseller_admin"
                    )

                    succ_txt = (
                        f"🎉 <b>اکانت جدید با موفقیت ساخته شد:</b>\n\n"
                        f"👤 نام اکانت: <code>{desired_name}</code>\n"
                        f"📦 پلن: <b>{pname}</b>\n"
                        f"📊 حجم: <b>{vol if vol > 0 else 'نامحدود'} گیگابایت</b> | ⏳ مدت: <b>{days} روز</b>\n"
                        f"💰 هزینه کسر شده: <b>{w_price:,} تومان</b>\n\n"
                        f"🔗 <b>لینک اتصال:</b>\n<code>{sub_url}</code>"
                    )
                    kb = InlineKeyboardMarkup([
                        [InlineKeyboardButton("📋 کپی لینک اتصال", copy_text=CopyTextButton(sub_url))],
                        [InlineKeyboardButton("🔙 بازگشت به پنل مدیریت", callback_data="res_adm_menu")]
                    ])
                    qr_bytes = generate_qr_code_bytes(sub_url)
                    if qr_bytes:
                        await update.message.reply_photo(photo=qr_bytes, caption=succ_txt, reply_markup=kb, parse_mode="HTML")
                    else:
                        await update.message.reply_text(succ_txt, reply_markup=kb, parse_mode="HTML")
                    return

            # ۰.۵. ساخت کد تخفیف جدید توسط نماینده
            if context.user_data.get("waiting_reseller_new_discount"):
                if is_adm and role in ("main", "sales"):
                    context.user_data.pop("waiting_reseller_new_discount")
                    parts = text.split()
                    if len(parts) >= 2:
                        d_code = parts[0].strip().upper()
                        val_str = parts[1].strip()
                        pct = 0
                        amt = 0
                        if "%" in val_str or "٪" in val_str:
                            clean_pct = re.sub(r"\D", "", val_str)
                            pct = int(clean_pct) if clean_pct else 10
                        else:
                            clean_amt = re.sub(r"\D", "", val_str)
                            amt = int(clean_amt) if clean_amt else 10000

                        db.create_reseller_discount_code(
                            reseller_id=r_id,
                            code=d_code,
                            discount_percent=pct,
                            discount_amount=amt,
                            max_uses=100
                        )
                        await update.message.reply_text(
                            f"✅ کد تخفیف <code>{d_code}</code> با موفقیت ایجاد شد.",
                            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 لیست کدهای تخفیف", callback_data="res_adm_discounts")]]),
                            parse_mode="HTML"
                        )
                    else:
                        await update.message.reply_text(
                            "❌ فرمت نامعتبر است. نمونه: <code>OFF20 20%</code> یا <code>VIP10 10000</code>",
                            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="res_adm_discounts")]]),
                            parse_mode="HTML"
                        )
                    return

            # ۰.۶. ارسال شماره پیگیری یا فیش متنی شارژ بسته توسط نماینده
            if context.user_data.get("waiting_reseller_bundle_receipt"):
                if is_adm and role in ("main", "finance"):
                    bundle_id = context.user_data.pop("waiting_reseller_bundle_receipt")
                    bundle = db.get_reseller_credit_bundle(bundle_id) or {}
                    pname = bundle.get("title", "بسته اعتباری")
                    amount = bundle.get("price", 0)
                    credit = bundle.get("credit", amount)
                    import random
                    order_id = f"R_BUNDLE_TXT_{r_id}_{int(datetime.now().timestamp())}_{random.randint(100, 999)}"
                    now_iso = get_now_iso()

                    conn = db.get_connection()
                    conn.execute("""
                        INSERT OR REPLACE INTO transactions (
                            order_id, user_id, username, plan_name, amount, status, gateway,
                            tracking_code, reseller_id, is_renewal, account_name, source, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, 'pending', 'bundle_reseller', ?, ?, 0, ?, 'reseller_panel_topup', ?, ?)
                    """, (
                        order_id, user.id, user.username or str(user.id), f"بسته {pname}",
                        amount, text[:50], r_id, f"شارژ {credit:,} تومان", now_iso, now_iso
                    ))
                    conn.commit()
                    conn.close()

                    admin_tg = db.get_setting("admin_telegram_id") or ADMIN_ID
                    if admin_tg:
                        adm_kb = InlineKeyboardMarkup([
                            [
                                InlineKeyboardButton("✅ تایید و شارژ کیف پول", callback_data=f"adm_pay_app_{order_id}"),
                                InlineKeyboardButton("❌ رد فیش", callback_data=f"adm_pay_rej_{order_id}")
                            ]
                        ])
                        adm_msg = (
                            f"📦 <b>درخواست شارژ پنل نماینده (شماره پیگیری/متن)</b>\n\n"
                            f"👤 نماینده: <b>{html.escape(str(self.reseller_data.get('name') or user.first_name))}</b> (کد #{r_id})\n"
                            f"📋 بسته: <b>{html.escape(str(pname))}</b>\n"
                            f"💰 مبلغ پرداختی: <b>{amount:,} تومان</b>\n"
                            f"🎁 اعتبار شارژ: <b>{credit:,} تومان</b>\n"
                            f"🔢 کد/متن پیگیری: <code>{html.escape(text)}</code>\n"
                            f"🆔 کد سفارش: <code>{order_id}</code>"
                        )
                        try:
                            await context.bot.send_message(chat_id=int(admin_tg), text=adm_msg, reply_markup=adm_kb, parse_mode="HTML")
                        except Exception as e_adm:
                            logger.error(f"Failed to notify admin of reseller bundle receipt text: {e_adm}")

                    await update.message.reply_text(
                        f"✅ <b>اطلاعات پرداخت شما برای بسته «{pname}» با موفقیت ثبت شد.</b>\n"
                        f"پس از تایید مدیریت، کیف پول پنل شما به مبلغ <b>{credit:,} تومان</b> شارژ خواهد شد.",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به پنل مدیریت", callback_data="res_adm_menu")]]),
                        parse_mode="HTML"
                    )
                    return

            # ۰.۶۵. دریافت شماره پیگیری یا متن رسید واریز کارت به کارت از مشتری
            if context.user_data.get("waiting_for_card_receipt"):
                btn_match = db.match_bot_menu_button(text, is_reseller=True)
                if not text.startswith("/") and not btn_match:
                    p_inv = context.user_data.pop("pending_card_invoice", None) or {}
                    context.user_data.pop("waiting_for_card_receipt", None)
                    plan_id = p_inv.get("plan_id") or context.user_data.get("buying_plan_id")
                    price = p_inv.get("amount") or context.user_data.get("buying_price", 0)
                    account_name = p_inv.get("account_name") or context.user_data.get("buying_account_name") or f"r{r_id}_u{user.id}"
                    order_id = p_inv.get("order_id") or context.user_data.get("buying_order_id") or f"R{r_id}_{int(datetime.now().timestamp())}_{user.id % 1000}"

                    r_plan = db.get_reseller_plan(r_id, plan_id)
                    if r_plan:
                        pname = r_plan.get("display_name") or r_plan.get("name") or r_plan.get("master_name", "پلن انتخابی")
                    else:
                        plans = load_plans()
                        plan = plans.get(plan_id, {})
                        pname = plan.get("name", "پلن انتخابی")

                    now_iso = get_now_iso()
                    conn = db.get_connection()
                    conn.execute("""
                        INSERT OR REPLACE INTO transactions (
                            order_id, user_id, username, plan_name, amount, status, gateway,
                            tracking_code, reseller_id, is_renewal, account_name, source, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, 'pending', 'card_reseller', ?, ?, 0, ?, 'reseller_bot', ?, ?)
                    """, (
                        order_id, user.id, user.username or user.first_name, pname,
                        price, text[:100], r_id, account_name, now_iso, now_iso
                    ))
                    conn.commit()
                    conn.close()

                    await update.message.reply_text(
                        f"✅ <b>متن رسید و مشخصات واریزی شما با موفقیت ثبت شد:</b>\n"
                        f"🔢 شماره پیگیری/مشخصات: <code>{html.escape(text)}</code>\n\n"
                        f"اطلاعات جهت بررسی و تایید به پشتیبانی ارسال گردید و پس از تایید، اشتراک به صورت خودکار برای شما فعال و تحویل داده خواهد شد.",
                        parse_mode="HTML"
                    )

                    notif_text = (
                        f"🔔 <b>رسید متنی واریز جدید در ربات شما!</b>\n\n"
                        f"👤 مشتری: {html.escape(str(user.first_name))} (ID: <code>{user.id}</code>)\n"
                        f"📦 پلن: <b>{html.escape(str(pname))}</b>\n"
                        f"👤 نام اکانت انتخابی: <code>{html.escape(str(account_name))}</code>\n"
                        f"💰 مبلغ: <b>{price:,} تومان</b>\n"
                        f"🔢 کد/متن پیگیری: <code>{html.escape(text)}</code>\n"
                        f"🔖 کد سفارش: <code>{order_id}</code>\n\n"
                        f"جهت تایید یا رد پرداخت از دکمه‌های زیر استفاده کنید:"
                    )
                    app_kb = InlineKeyboardMarkup([
                        [
                            InlineKeyboardButton("✅ تایید و تحویل کانفیگ", callback_data=f"rapprove_{order_id}_{user.id}_{plan_id}"),
                            InlineKeyboardButton("❌ رد پرداخت", callback_data=f"rreject_{order_id}_{user.id}")
                        ]
                    ])
                    await notify_reseller_admins(context.bot, ["main", "finance"], notif_text, reply_markup=app_kb)
                    return

            # ۰.۷. بررسی اعمال کد تخفیف توسط مشتری
            if context.user_data.get("waiting_discount_code_plan"):
                plan_id = context.user_data.pop("waiting_discount_code_plan")
                plan = db.get_reseller_plan(r_id, plan_id)
                base_price = plan.get("display_price", 0) if plan else 0
                val_res = db.validate_reseller_discount_code(r_id, text, base_price)
                if val_res.get("valid"):
                    context.user_data["applied_discount_code"] = val_res["discount_code"]
                    context.user_data["applied_discount_amount"] = val_res["discount_amount"]
                    disc_amt = val_res["discount_amount"]
                    f_amt = val_res["final_amount"]
                    await update.message.reply_text(
                        f"✅ <b>کد تخفیف «{val_res['discount_code']}» با موفقیت اعمال شد!</b>\n\n"
                        f"🎁 تخفیف: <b>{disc_amt:,} تومان</b>\n"
                        f"💰 مبلغ نهایی: <b>{f_amt:,} تومان</b>",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("💳 ادامه و پرداخت فاکتور", callback_data=f"r_conf_{plan_id}")]
                        ]),
                        parse_mode="HTML"
                    )
                else:
                    err = val_res.get("error") or "کد تخفیف نامعتبر یا منقضی است."
                    await update.message.reply_text(
                        f"❌ {err}",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("🔄 امتحان مجدد", callback_data=f"r_apply_disc_{plan_id}")],
                            [InlineKeyboardButton("◀️ بازگشت به پیش‌فاکتور", callback_data=f"r_conf_{plan_id}")]
                        ])
                    )
                return

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

                    vip_alert = "🚨 ⭐️ <b>[تیکت فوری - مشتری ویژه VIP]</b>" if is_vip else "📨 <b>تیکت پشتیبانی جدید</b>"
                    notif_msg = (
                        f"{vip_alert}\n\n"
                        f"👤 مشتری: {html.escape(str(user.first_name))} (ID: <code>{user.id}</code>)\n"
                        f"💬 یوزرنیم: @{user.username or 'ندارد'}\n"
                        f"📝 متن پیام:\n{html.escape(content)}\n\n"
                        f"🔖 شماره تیکت: #{t_id}"
                    )
                    r_kb = InlineKeyboardMarkup([
                        [
                            InlineKeyboardButton("✍️ پاسخ متنی", callback_data=f"res_reply_tkt_{t_id}"),
                            InlineKeyboardButton("⚡ پاسخ‌های آماده", callback_data=f"res_canned_tkt_{t_id}")
                        ],
                        [
                            InlineKeyboardButton("🔒 بستن تیکت", callback_data=f"res_close_tkt_{t_id}")
                        ]
                    ])
                    await notify_reseller_admins(context.bot, ["main", "support"], notif_msg, reply_markup=r_kb)
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

                if b_id in ("mini_app", "webapp"):
                    webapp_url = db.get_setting("webapp_url", "") or os.getenv("DASHBOARD_URL", "")
                    if not webapp_url and os.getenv("RAILWAY_PUBLIC_DOMAIN"):
                        webapp_url = f"https://{os.getenv('RAILWAY_PUBLIC_DOMAIN')}"
                    if webapp_url:
                        full_app_url = f"{webapp_url.rstrip('/')}/webapp?tg_id={user.id}&r={r_id}"
                        kb = InlineKeyboardMarkup([
                            [InlineKeyboardButton("📱 ورود به پنل کاربری هوشمند (Mini App)", web_app=WebAppInfo(url=full_app_url))]
                        ])
                        await update.message.reply_text(
                            "📱 <b>پنل کاربری و پورتال اختصاصی (Telegram Mini App)</b>\n\n"
                            "جهت مشاهده وضعیت سرویس، بارکد اتصال، تمدید و خرید اشتراک روی دکمه زیر بزنید:",
                            reply_markup=kb,
                            parse_mode="HTML"
                        )
                    else:
                        await update.message.reply_text("⚠️ آدرس وب‌اپ تنظیم نشده است.")
                    return
                elif b_id == "buy":
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
        app.add_handler(CommandHandler(["admin", "admin_panel", "manage", "panel"], reseller_admin_panel_handler))
        app.add_handler(CommandHandler("plans", plans_handler))
        app.add_handler(CommandHandler("help", guide_handler))
        app.add_handler(CommandHandler(["reply_ticket", "reply"], reseller_reply_command_handler))
        app.add_handler(CallbackQueryHandler(select_language_callback, pattern="^(r_lang_|lang_)"))
        app.add_handler(CallbackQueryHandler(plans_handler, pattern="^r_back_plans$"))
        app.add_handler(CallbackQueryHandler(plan_naming_callback, pattern="^r_buy_"))
        app.add_handler(CallbackQueryHandler(name_choice_callback, pattern="^r_name_"))
        app.add_handler(CallbackQueryHandler(buy_plan_confirm_callback, pattern="^r_conf_"))
        app.add_handler(CallbackQueryHandler(apply_discount_callback, pattern="^r_apply_disc_"))
        app.add_handler(CallbackQueryHandler(pay_card_callback, pattern="^r_pcard_"))
        app.add_handler(CallbackQueryHandler(pay_wallet_callback, pattern="^r_pwal_"))
        app.add_handler(CallbackQueryHandler(pay_online_callback, pattern="^r_ponl_"))
        app.add_handler(CallbackQueryHandler(copy_action_callback, pattern="^(r_copy_card_|r_copy_rial_|r_copy_amt_|r_pwal_insuf|r_ponl_soon|r_cancel_buy)"))
        app.add_handler(CallbackQueryHandler(sub_qr_callback, pattern="^r_sub_qr_"))
        app.add_handler(CallbackQueryHandler(sub_renew_callback, pattern="^r_renew_"))
        app.add_handler(CallbackQueryHandler(start_handler, pattern="^r_check_sub$"))
        app.add_handler(CallbackQueryHandler(reseller_ticket_callbacks, pattern="^(res_reply_tkt_|res_canned_tkt_|res_canned_send_|res_canned_cancel_|res_close_tkt_)"))
        app.add_handler(CallbackQueryHandler(reseller_approve_callback, pattern="^(rapprove_|rreject_|res_pay_app_|res_pay_rej_)"))
        app.add_handler(CallbackQueryHandler(reseller_admin_callback_handler, pattern="^res_adm_"))
        app.add_handler(CallbackQueryHandler(reseller_wizard_callback_handler, pattern="^wiz_"))
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

        # راه‌اندازی خودکار «ربات فروش بسته نمایندگی» در صورت فعال بودن
        try:
            if db.get_setting("bundle_bot_active") == "1" and db.get_setting("bundle_bot_token"):
                from bundle_sales_bot import bundle_sales_bot_runner
                ok = bundle_sales_bot_runner.start()
                logger.info(f"Auto-start bundle sales bot status: {ok}")
        except Exception as ex_b:
            logger.error(f"Error auto-starting bundle sales bot: {ex_b}")


# ساخت نمونه تکین (Singleton) برای کل پروژه
multibot_manager = MultiBotManager()
