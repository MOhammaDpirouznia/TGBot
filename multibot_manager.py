#!/usr/bin/env python3
"""
ماژول مدیریت ربات‌های چندگانه نمایندگان فروش (White-Label Multi-Bot Manager)
این ماژول امکان اجرای همزمان و مستقل چندین ربات تلگرام اختصاصی برای هر نماینده را
با برند اختصاصی، کانال جوین اجباری، کارت بانکی مجزا و تایید آنی فیش توسط خود نماینده فراهم می‌کند.
"""

import os
import sys
import json
import logging
import asyncio
import threading
import json
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

from dotenv import load_dotenv
load_dotenv()

from database import db
from utils import (
    get_now_iso, get_now_naive, get_single_link_template, format_single_link,
    generate_qr_code_bytes, gregorian_to_shamsi, days_remaining_shamsi
)
from admin_manager import load_plans, get_all_plans
from hidify import HidifyClient

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

        async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
            user = update.effective_user
            if not user:
                return

            # ۱. ذخیره کاربر با برچسب این نماینده
            db.save_user(
                telegram_id=user.id,
                username=user.username or user.first_name,
                reseller_id=r_id
            )

            # ۲. بررسی عضویت در کانال اجباری نماینده (در صورت تعریف)
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
                        await update.message.reply_text(
                            "⚠️ جهت استفاده از ربات، لطفاً ابتدا در کانال ما عضو شوید:",
                            reply_markup=kb
                        )
                        return
                except Exception as e:
                    logger.warning(f"Could not check channel membership for reseller {r_id}: {e}")

            brand = self.reseller_data.get("brand_name") or self.reseller_data.get("name") or "سرویس VPN"
            custom_msg = self.reseller_data.get("start_message") or ""
            
            welcome = f"🌟 به ربات اختصاصی **{brand}** خوش آمدید!\n\n"
            if custom_msg:
                welcome += f"{custom_msg}\n\n"
            else:
                welcome += "🚀 اتصال پرسرعت، امن و بدون قطعی با سرورهای قدرتمند\n\n"
            
            welcome += "جهت شروع یکی از گزینه‌های زیر را انتخاب نمایید:"

            main_kb = ReplyKeyboardMarkup([
                [KeyboardButton("🛍️ خرید اشتراک"), KeyboardButton("👤 اشتراک‌های من")],
                [KeyboardButton("💳 کیف پول"), KeyboardButton("🎧 پشتیبانی و تیکت")],
                [KeyboardButton("📖 راهنمای اتصال"), KeyboardButton("🛠️ حل مشکلات اتصال")]
            ], resize_keyboard=True)

            await update.message.reply_text(welcome, reply_markup=main_kb, parse_mode="Markdown")

        async def plans_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
            """نمایش پلن‌های فروش برای مشتری نماینده (با اعمال نام و قیمت سفارشی نماینده)"""
            plans = db.get_reseller_active_plans(r_id)
            if not plans:
                await update.message.reply_text("❌ در حال حاضر پلن فعالی در فروشگاه تعریف نشده است.")
                return

            brand = self.reseller_data.get("brand_name") or "ما"
            text = f"📦 **تعرفه‌های اشتراک {brand}:**\n\nلطفاً پلن مورد نظر خود را انتخاب فرمایید:\n"

            buttons = []
            for p in plans:
                pid = p["plan_id"]
                pname = p.get("display_name") or p.get("master_name", "پلن")
                price = p.get("display_price", 0)
                vol = p.get("data_limit", 0)
                days = p.get("duration", 30)
                vol_str = f"{vol} گیگابایت" if vol > 0 else "نامحدود"

                btn_text = f"⚡ {pname} | {vol_str} - {days} روز ({price:,} تومان)"
                buttons.append([InlineKeyboardButton(btn_text, callback_data=f"r_buy_{pid}")])

            kb = InlineKeyboardMarkup(buttons)
            await update.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")

        async def buy_plan_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
            """انتخاب پلن و نمایش صفحه جامع انتخاب روش پرداخت (کیف پول، درگاه آنلاین، کارت به کارت)"""
            query = update.callback_query
            await query.answer()

            plan_id = query.data.replace("r_buy_", "")
            plan = db.get_reseller_plan(r_id, plan_id)
            if not plan:
                await query.edit_message_text("❌ پلن مورد نظر یافت نشد.")
                return

            price = plan.get("display_price", 0)
            pname = plan.get("display_name") or plan.get("master_name", "پلن")
            vol = plan.get("data_limit", 0)
            days = plan.get("duration", 30)
            vol_str = f"{vol} گیگابایت" if vol > 0 else "نامحدود"

            user = update.effective_user
            user_wallet = db.get_user_wallet_balance(user.id)
            gw_cfg = db.get_reseller_gateway(r_id)

            context.user_data["buying_plan_id"] = plan_id
            context.user_data["buying_price"] = price

            msg = f"🛒 **پیش‌فاکتور خرید اشتراک**\n\n"
            msg += f"📦 پلن: **{pname}**\n"
            msg += f"📊 حجم: **{vol_str}** | ⏳ مدت: **{days} روز**\n"
            msg += f"💰 مبلغ قابل پرداخت: **{price:,} تومان**\n"
            msg += f"💳 موجودی کیف پول شما: **{user_wallet:,} تومان**\n\n"
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
                        gw_label = "زرین‌پال" if gw_cfg.get("type") == "zarinpal" else ("آیدی‌پی" if gw_cfg.get("type") == "idpay" else "آنلاین")
                        buttons.append([InlineKeyboardButton(f"💳 درگاه پرداخت آنلاین ({gw_label})", callback_data=f"r_ponl_{plan_id}")])
                    else:
                        buttons.append([InlineKeyboardButton("💳 درگاه آنلاین (بزودی)", callback_data="r_ponl_soon")])
                elif m_id == "card_to_card":
                    buttons.append([InlineKeyboardButton("💵 کارت به کارت (بانکی)", callback_data=f"r_pcard_{plan_id}")])

            # انصراف
            buttons.append([InlineKeyboardButton("❌ انصراف", callback_data="r_cancel_buy")])

            kb = InlineKeyboardMarkup(buttons)
            await query.edit_message_text(msg, reply_markup=kb, parse_mode="Markdown")

        async def pay_card_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
            """نمایش اطلاعات کارت بانکی فعال نماینده با دکمه‌های کپی هوشمند شماره کارت و مبلغ"""
            query = update.callback_query
            await query.answer()

            plan_id = query.data.replace("r_pcard_", "")
            plan = db.get_reseller_plan(r_id, plan_id)
            if not plan:
                await query.edit_message_text("❌ پلن یافت نشد.")
                return

            price = plan.get("display_price", 0)
            pname = plan.get("display_name") or plan.get("master_name", "پلن")
            vol = plan.get("data_limit", 0)
            days = plan.get("duration", 30)
            vol_str = f"{vol} گیگابایت" if vol > 0 else "نامحدود"

            # دریافت کارت بانکی فعال نماینده
            active_card = db.get_active_reseller_card(r_id)
            if active_card:
                raw_card = active_card.get("card_number") or ""
                card_holder = active_card.get("card_holder") or ""
                bank_name = active_card.get("bank_name") or ""
            else:
                raw_card = self.reseller_data.get("card_number") or ""
                card_holder = self.reseller_data.get("card_holder") or ""
                bank_name = self.reseller_data.get("bank_name") or ""

            card_num = re.sub(r"\D", "", str(raw_card))
            rial_price = price * 10
            rial_fmt = f"{rial_price:,}"
            toman_fmt = f"{price:,}"

            context.user_data["buying_plan_id"] = plan_id
            context.user_data["buying_price"] = price

            msg = f"💵 **پرداخت کارت به کارت**\n\n"
            msg += f"📦 پلن: **{pname}**\n"
            msg += f"📊 حجم: **{vol_str}** | ⏳ مدت: **{days} روز**\n\n"
            msg += f"💰 **مبلغ قابل واریز:**\n"
            msg += f"• به ریال (جهت همراه بانک / عابربانک):\n`{rial_price}` ریال (**{rial_fmt} ریال**)\n"
            msg += f"• به تومان:\n`{price}` تومان (**{toman_fmt} تومان**)\n\n"

            if card_num:
                msg += "💳 **اطلاعات کارت جهت واریز:**\n"
                msg += f"شماره کارت:\n`{card_num}`\n"
                if card_holder:
                    msg += f"به نام: **{card_holder}**\n"
                if bank_name:
                    msg += f"بانک: **{bank_name}**\n"
                msg += "\n⚠️ **نکات مهم:**\n"
                msg += "• برای کپی با یک لمس، روی **شماره کارت** یا **مبلغ به ریال** بالا یا دکمه‌های زیر بزنید.\n"
                msg += "• پس از واریز، **عکس فیش واریزی** خود را در همین گفتگو ارسال فرمایید."

                buttons = [
                    [InlineKeyboardButton("📋 کپی شماره کارت", callback_data=f"r_copy_card_{card_num}")],
                    [InlineKeyboardButton(f"💰 کپی مبلغ به ریال ({rial_fmt} ریال)", callback_data=f"r_copy_rial_{rial_price}")],
                    [InlineKeyboardButton(f"💵 کپی مبلغ به تومان ({toman_fmt} ت)", callback_data=f"r_copy_amt_{price}")],
                    [InlineKeyboardButton("◀️ بازگشت", callback_data=f"r_buy_{plan_id}"), InlineKeyboardButton("❌ انصراف", callback_data="r_cancel_buy")]
                ]
            else:
                msg += "💳 جهت پرداخت و دریافت شماره کارت، با پشتیبانی تماس حاصل فرمایید."
                buttons = [
                    [InlineKeyboardButton("◀️ بازگشت", callback_data=f"r_buy_{plan_id}"), InlineKeyboardButton("❌ انصراف", callback_data="r_cancel_buy")]
                ]

            kb = InlineKeyboardMarkup(buttons)
            await query.edit_message_text(msg, reply_markup=kb, parse_mode="Markdown")

        async def copy_action_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
            """پاسخ به دکمه‌های کپی شماره کارت و مبلغ در ربات نماینده با ارسال پیام کپی ۱ لمسی"""
            query = update.callback_query
            data = query.data
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
                    logger.warning(f"Error sending copy amount msg in reseller bot: {e}")
            elif data == "r_pwal_insuf":
                user = update.effective_user
                user_wallet = db.get_user_wallet_balance(user.id)
                await query.answer(f"❌ موجودی کیف پول شما ({user_wallet:,} ت) برای این پلن کافی نیست. لطفاً از کارت به کارت استفاده کنید.", show_alert=True)
            elif data == "r_ponl_soon":
                await query.answer("💳 درگاه پرداخت آنلاین به زودی فعال خواهد شد. لطفاً از روش کارت به کارت استفاده فرمایید.", show_alert=True)
            elif data == "r_cancel_buy":
                await query.edit_message_text("❌ عملیات خرید لغو شد.")

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

            # بررسی موجودی عمده نماینده
            r_info = db.get_reseller(r_id) or {}
            r_balance = r_info.get("balance", 0)
            if r_balance < wholesale_cost:
                await query.answer("⚠️ اعتبار فروشگاه موقتاً نیازمند شارژ است. لطفاً به پشتیبانی اطلاع دهید.", show_alert=True)
                return

            # کسر از موجودی کیف پول مشتری
            deduct_res = db.deduct_wallet_balance(user.id, price, f"خرید آنی اشتراک {plan.get('display_name')}")
            if not deduct_res.get("success"):
                await query.answer("❌ خطا در کسر موجودی: " + str(deduct_res.get("error")), show_alert=True)
                return

            pname = plan.get("display_name") or plan.get("master_name", "اشتراک")
            vol = plan.get("data_limit", 30)
            days = plan.get("duration", 30)
            account_name = f"r{r_id}_u{user.id}_{int(datetime.now().timestamp()) % 10000}"

            # کسر هزینه عمده از حساب نماینده
            db.deduct_reseller_balance(r_id, wholesale_cost, pname, account_name)

            await query.edit_message_text("⏳ در حال ساخت و فعال‌سازی آنی اشتراک شما...")

            # ساخت اشتراک در هیدیفای
            created = await hidify_client.create_user(
                name=account_name,
                usage_limit_gb=vol if vol > 0 else None,
                package_days=days,
                enable=True,
                comment=f"Reseller #{r_id} | User {user.id}"
            )

            uuid_val = created.get("uuid") if created else None
            sub_url = f"{HIDIFY_PANEL_URL}/{HIDIFY_PROXY_PATH}/{uuid_val}/" if uuid_val else ""

            # ذخیره در دیتابیس
            db.save_subscription(
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
            cust_msg = f"🎉 **اشتراک {brand} با موفقیت فعال شد:**\n\n"
            cust_msg += f"📦 پلن: **{pname}**\n"
            cust_msg += f"📊 حجم: **{vol if vol > 0 else 'نامحدود'} گیگابایت** | ⏳ مدت: **{days} روز**\n"
            cust_msg += f"💰 مبلغ پرداختی: **{price:,} تومان**\n\n"
            cust_msg += f"🔗 **لینک اتصال اختصاصی شما:**\n`{sub_url}`\n\n"
            cust_msg += "💡 لینک بالا را در اپلیکیشن v2rayNG / Hiddify / Streisand وارد فرمایید."

            await query.edit_message_text(cust_msg, parse_mode="Markdown")

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
            if gw_type == "zarinpal":
                from payment import ZarinPal
                zp = ZarinPal(merchant_id=gw_key, sandbox=sandbox)
                res = zp.create_payment(amount=price, description=f"خرید {pname}", callback_url=callback_url)
                if res.get("success"):
                    pay_url = res.get("payment_url")
            elif gw_type == "idpay":
                from payment import IDPay
                idp = IDPay(api_key=gw_key, sandbox=sandbox)
                res = idp.create_payment(amount=price, name=user.full_name or "کاربر", description=f"خرید {pname}", callback_url=callback_url, order_id=order_id)
                if res.get("success"):
                    pay_url = res.get("payment_url")

            if pay_url:
                db.save_transaction(
                    order_id=order_id,
                    user_id=user.id,
                    username=user.username or user.first_name,
                    plan_name=pname,
                    amount=price,
                    gateway=f"{gw_type}_reseller_{r_id}",
                    tracking_code=order_id,
                    status="pending",
                    reseller_id=r_id
                )
                msg = f"💳 **درگاه پرداخت آنلاین شاپرک**\n\n"
                msg += f"📦 پلن: **{pname}**\n"
                msg += f"💰 مبلغ: **`{price:,}` تومان**\n"
                msg += f"🔢 شناسه سفارش: `{order_id}`\n\n"
                msg += "جهت پرداخت روی دکمه زیر کلیک کنید. پس از پرداخت آنلاین، اشتراک شما به صورت خودکار فعال می‌گردد:"

                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🌐 ورود به درگاه پرداخت شاپرک", url=pay_url)],
                    [InlineKeyboardButton("◀️ بازگشت", callback_data=f"r_buy_{plan_id}")]
                ])
                await query.edit_message_text(msg, reply_markup=kb, parse_mode="Markdown")
            else:
                await query.answer("❌ خطا در اتصال به درگاه بانکی. لطفاً از کارت به کارت استفاده فرمایید.", show_alert=True)

        async def receipt_photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
            """دریافت تصویر فیش از مشتری و ارسال به تلگرام خود نماینده جهت تایید"""
            user = update.effective_user
            if not update.message.photo:
                return

            plan_id = context.user_data.get("buying_plan_id")
            price = context.user_data.get("buying_price", 0)

            if not plan_id:
                await update.message.reply_text("⚠️ لطفاً ابتدا از بخش «🛍️ خرید اشتراک» یک پلن را انتخاب کرده و سپس فیش واریزی را ارسال کنید.")
                return

            photo = update.message.photo[-1]
            photo_file_id = photo.file_id
            order_id = f"R{r_id}_{int(datetime.now().timestamp())}_{user.id % 1000}"

            # دانلود و ذخیره مستقیم تصویر فیش روی دیسک
            saved_receipt_filename = None
            try:
                receipts_dir = Path("data/receipts")
                receipts_dir.mkdir(parents=True, exist_ok=True)
                tg_file = await photo.get_file()
                saved_receipt_filename = f"receipt_{order_id}.jpg"
                await tg_file.download_to_drive(receipts_dir / saved_receipt_filename)
            except Exception as e:
                logger.warning(f"Could not download receipt photo for order {order_id}: {e}")

            plans = load_plans()
            plan = plans.get(plan_id, {})
            pname = plan.get("name", "پلن انتخابی")

            # ذخیره تراکنش در دیتابیس با برچسب این نماینده
            db.save_transaction(
                order_id=order_id,
                user_id=user.id,
                username=user.username or user.first_name,
                plan_name=pname,
                amount=price,
                gateway="card_reseller",
                tracking_code=f"Receipt_{order_id}",
                status="pending",
                receipt_image=saved_receipt_filename or photo_file_id,
                receipt_file_type="web_upload" if saved_receipt_filename else "photo",
                reseller_id=r_id
            )

            await update.message.reply_text(
                "✅ **فیش واریزی شما با موفقیت دریافت شد.**\n\n"
                "درخواست شما به مدیریت ارسال شد و پس از بررسی و تایید، کانفیگ به صورت خودکار برای شما ارسال خواهد شد. سپاس از شکیبایی شما.",
                parse_mode="Markdown"
            )

            # ارسال نوتیفیکیشن برای خود نماینده در تلگرام
            reseller_tg = self.reseller_data.get("telegram_id")
            if reseller_tg:
                try:
                    notif_text = f"🔔 **فیش واریزی جدید در ربات شما!**\n\n"
                    notif_text += f"👤 مشتری: [{user.first_name}](tg://user?id={user.id}) (ID: `{user.id}`)\n"
                    notif_text += f"📦 پلن: **{pname}**\n"
                    notif_text += f"💰 مبلغ: **{price:,} تومان**\n"
                    notif_text += f"🔖 کد سفارش: `{order_id}`\n\n"
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
                        parse_mode="Markdown"
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

                # کسر موجودی از کیف پول نماینده
                account_name = f"r{r_id}_u{target_uid}_{int(datetime.now().timestamp()) % 10000}"
                deduct_res = db.deduct_reseller_balance(r_id, wholesale_cost, pname, account_name)

                if not deduct_res.get("success"):
                    await query.edit_message_caption(
                        caption=f"❌ **خطا در تایید:** موجودی کیف پول نماینده کافی نیست!\n"
                                f"مبلغ عمده مورد نیاز: {wholesale_cost:,} تومان\n"
                                f"لطفاً ابتدا کیف پول خود را در پنل وب شارژ فرمایید.",
                        parse_mode="Markdown"
                    )
                    return

                # ساخت در هیدیفای
                h_res = None
                try:
                    h_res = await hidify_client.create_user(
                        name=account_name,
                        package_days=int(days),
                        usage_limit_gb=float(vol) if vol > 0 else None,
                        comment=f"Reseller #{r_id} Bot | TG: {target_uid}"
                    )
                except Exception as e:
                    logger.error(f"Hiddify creation error: {e}")

                uuid_val = h_res.get("uuid") if h_res else None
                sub_url = ""
                if uuid_val:
                    sub_url = f"{HIDIFY_PANEL_URL}/{HIDIFY_PROXY_PATH}/{uuid_val}/"
                else:
                    sub_url = f"https://vpn.service/sub/{account_name}"

                # ذخیره اشتراک
                db.save_subscription(
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

                # بروزرسانی تراکنش
                db.update_transaction(order_id, status="approved")

                # محاسبه کش‌بک و ارتقای VIP مشتری نماینده
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

                # ویرایش پیام نماینده
                await query.edit_message_caption(
                    caption=f"✅ **پرداخت تایید شد و اشتراک با موفقیت تحویل مشتری گردید.**\n"
                            f"📦 پلن: {pname} | 💰 هزینه عمده کسر شده: {wholesale_cost:,} تومان\n"
                            f"👤 نام اشتراک: `{account_name}`",
                    parse_mode="Markdown"
                )

                # ارسال لینک اشتراک برای مشتری در ربات
                try:
                    cust_msg = f"🎉 **پرداخت شما تایید شد! اشتراک {brand} آماده است:**\n\n"
                    cust_msg += f"📦 پلن: **{pname}**\n"
                    cust_msg += f"📊 حجم: **{vol} گیگابایت** | ⏳ مدت: **{days} روز**\n\n"
                    cust_msg += f"🔗 **لینک اتصال اختصاصی شما:**\n`{sub_url}`{cashback_note}\n\n"
                    cust_msg += "💡 جهت اتصال، لینک بالا را کپی کرده و در نرم‌افزار v2rayNG / Streisand / Hiddify وارد نمایید."

                    await context.bot.send_message(
                        chat_id=target_uid,
                        text=cust_msg,
                        parse_mode="Markdown"
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
            """نمایش لیست اشتراک‌های کاربر در ربات نماینده"""
            user = update.effective_user
            subs = db.get_user_subscriptions(user.id)
            if not subs:
                await update.message.reply_text("ℹ️ شما در حال حاضر هیچ اشتراک فعالی ندارید.")
                return

            vip_info = db.get_user_vip_info(user.id)
            vip_header = ""
            if vip_info.get("is_vip"):
                cb = vip_info.get("cashback_percent", 10)
                vip_header = f"👑 **سطح عضویت: مشتری ویژه (⭐️ VIP)**\n🎁 **پاداش فعال:** {cb}٪ کش‌بک در هر خرید\n\n"

            text = f"{vip_header}📋 **لیست اشتراک‌های شما:**\n\n"
            for s in subs:
                name = s.get("account_name", "اشتراک")
                status = "🟢 فعال" if s.get("status") == "active" else "🔴 غیرفعال"
                limit = s.get("data_limit", 0)
                used = s.get("data_used", 0)
                rem = max(0, limit - used)
                uuid_val = s.get("hidify_uuid")
                link = f"{HIDIFY_PANEL_URL}/{HIDIFY_PROXY_PATH}/{uuid_val}/" if uuid_val else "در دسترس نیست"

                text += f"🔹 **{name}** ({status})\n"
                text += f"📊 باقیمانده حجم: {rem:.2f} GB از {limit:.2f} GB\n"
                text += f"🔗 لینک: `{link}`\n\n"

            await update.message.reply_text(text, parse_mode="Markdown")

        async def support_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
            """ارسال پیام پشتیبانی یا آیدی پشتیبان"""
            sup_user = self.reseller_data.get("support_username") or ""
            brand = self.reseller_data.get("brand_name") or "پشتیبانی"
            buttons = []
            if sup_user:
                sup_clean = sup_user.replace("@", "")
                buttons.append([InlineKeyboardButton("💬 ارتباط مستقیم در تلگرام", url=f"https://t.me/{sup_clean}")])

            msg = f"🎧 **واحد پشتیبانی {brand}**\n\n"
            msg += "جهت ارسال پیام برای تیم پشتیبانی، پیام خود را با فرمت زیر ارسال کنید:\n"
            msg += "`تیکت: متن پیام شما`\n\n"
            msg += "کارشناسان ما در اسرع وقت پاسخ شما را در همین ربات ارسال خواهند کرد."
            kb = InlineKeyboardMarkup(buttons) if buttons else None
            await update.message.reply_text(msg, reply_markup=kb, parse_mode="Markdown")

        async def guide_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
            """راهنمای اتصال و لینک آموزش‌های تصویری اختصاصی نماینده"""
            r_info = db.get_reseller(r_id) or {}
            brand_name = r_info.get("brand_title") or r_info.get("brand_name") or r_info.get("name") or "فروشگاه"
            
            # آدرس پورتال آموزش‌ها برای نماینده
            if r_info.get("tutorial_domain"):
                tutorial_url = f"https://{r_info['tutorial_domain']}/help"
            elif r_info.get("custom_domain"):
                tutorial_url = f"https://{r_info['custom_domain']}/help"
            else:
                dashboard_url = os.getenv("DASHBOARD_URL", "").rstrip("/")
                tutorial_url = f"{dashboard_url}/help?r={r_id}" if dashboard_url else f"http://127.0.0.1:5000/help?r={r_id}"

            troubleshoot_url = f"{tutorial_url.split('?')[0].rstrip('/')}/troubleshoot"
            if "?r=" in tutorial_url:
                troubleshoot_url += f"?r={r_id}"

            guide_text = (
                f"📖 **مرکز آموزش تصویری و راهنمای اتصال {brand_name}**\n\n"
                "برای مشاهده آموزش‌های مرحله‌به‌مرحله تصویری برای تمام دستگاه‌ها (اندروید، آیفون، ویندوز، مک، تلویزیون هوشمند و مودم) و رفع سریع هرگونه مشکل در اتصال، روی دکمه‌های زیر کلیک نمایید:"
            )
            buttons = [
                [InlineKeyboardButton("🌐 مشاهده آموزش‌های تصویری تمام دستگاه‌ها", url=tutorial_url)],
                [InlineKeyboardButton("🛠️ عیب‌یابی و حل مشکلات اتصال", url=troubleshoot_url)]
            ]
            kb = InlineKeyboardMarkup(buttons)
            await update.message.reply_text(guide_text, reply_markup=kb, parse_mode="Markdown")

        async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
            """مسیریابی دکمه‌های ریپلای کیبورد"""
            text = update.message.text or ""
            if "خرید اشتراک" in text or "خرید" in text:
                await plans_handler(update, context)
            elif "اشتراک‌های من" in text or "سرویس‌های من" in text or "اشتراک" in text:
                await my_subs_handler(update, context)
            elif "کیف پول" in text or "شارژ" in text:
                user = update.effective_user
                bal = db.get_user_wallet_balance(user.id)
                vip_info = db.get_user_vip_info(user.id)
                vip_txt = ""
                if vip_info.get("is_vip"):
                    cb = vip_info.get("cashback_percent", 10)
                    vip_txt = f"\n👑 **سطح حساب:** مشتری طلایی (⭐️ VIP)\n🎁 **پاداش کش‌بک:** {cb}٪ بازگشت وجه در هر خرید\n"
                await update.message.reply_text(f"💳 **موجودی کیف پول شما:** `{bal:,}` تومان{vip_txt}", parse_mode="Markdown")
            elif "پشتیبانی" in text:
                await support_handler(update, context)
            elif "راهنما" in text or "آموزش" in text or "حل مشکل" in text or "عیب‌یابی" in text:
                await guide_handler(update, context)
            elif text.startswith("تیکت:") or text.startswith("تیکت ") or text.startswith("/ticket"):
                user = update.effective_user
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
                    await update.message.reply_text(f"✅ **پیام و تیکت پشتیبانی شما با شماره #{t_id} ثبت شد.**\nپاسخ کارشناسان در همین ربات برای شما ارسال خواهد شد.", parse_mode="Markdown")

                    # ارسال نوتیفیکیشن فوری به تلگرام نماینده
                    reseller_tg = self.reseller_data.get("telegram_id")
                    if reseller_tg:
                        try:
                            vip_alert = "🚨 ⭐️ **[تیکت فوری - مشتری ویژه VIP]**" if is_vip else "📨 **تیکت پشتیبانی جدید**"
                            notif_msg = (
                                f"{vip_alert}\n\n"
                                f"👤 مشتری: {user.first_name} (ID: `{user.id}`)\n"
                                f"💬 یوزرنیم: @{user.username or 'ندارد'}\n"
                                f"📝 متن پیام:\n{content}\n\n"
                                f"🔖 شماره تیکت: #{t_id}"
                            )
                            await context.bot.send_message(chat_id=reseller_tg, text=notif_msg, parse_mode="Markdown")
                        except Exception as e_notif:
                            logger.error(f"Error notifying reseller of ticket: {e_notif}")
                else:
                    await update.message.reply_text("⚠️ لطفاً متن پیام خود را بعد از عبارت `تیکت:` بنویسید.")
            else:
                # پاسخ عمومی
                await update.message.reply_text("لطفاً از دکمه‌های منو استفاده فرمایید.")

        # ثبت هندلرها
        app.add_handler(CommandHandler("start", start_handler))
        app.add_handler(CommandHandler("plans", plans_handler))
        app.add_handler(CommandHandler("help", guide_handler))
        app.add_handler(CallbackQueryHandler(buy_plan_callback, pattern="^r_buy_"))
        app.add_handler(CallbackQueryHandler(pay_card_callback, pattern="^r_pcard_"))
        app.add_handler(CallbackQueryHandler(pay_wallet_callback, pattern="^r_pwal_"))
        app.add_handler(CallbackQueryHandler(pay_online_callback, pattern="^r_ponl_"))
        app.add_handler(CallbackQueryHandler(copy_action_callback, pattern="^(r_copy_card_|r_copy_rial_|r_copy_amt_|r_pwal_insuf|r_ponl_soon|r_cancel_buy)"))
        app.add_handler(CallbackQueryHandler(start_handler, pattern="^r_check_sub$"))
        app.add_handler(CallbackQueryHandler(reseller_approve_callback, pattern="^rapprove_|^rreject_"))
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
