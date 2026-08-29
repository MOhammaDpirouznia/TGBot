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
                [KeyboardButton("📖 راهنمای اتصال")]
            ], resize_keyboard=True)

            await update.message.reply_text(welcome, reply_markup=main_kb, parse_mode="Markdown")

        async def plans_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
            """نمایش پلن‌های فروش برای مشتری نماینده"""
            plans = get_all_plans()
            if not plans:
                await update.message.reply_text("❌ در حال حاضر پلن فعالی تعریف نشده است.")
                return

            brand = self.reseller_data.get("brand_name") or "ما"
            text = f"📦 **تعرفه‌های اشتراک {brand}:**\n\nلطفاً پلن مورد نظر خود را انتخاب کنید:\n"

            buttons = []
            for p in plans:
                pid = p.get("id") or p.get("plan_id")
                pname = p.get("name", "پلن")
                price = p.get("price", 0)
                vol = p.get("traffic", p.get("volume_gb", 0))
                days = p.get("duration_days", p.get("days", 30))

                btn_text = f"⚡ {pname} | {vol}GB - {days} روز ({price:,} تومان)"
                buttons.append([InlineKeyboardButton(btn_text, callback_data=f"r_buy_{pid}")])

            kb = InlineKeyboardMarkup(buttons)
            await update.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")

        async def buy_plan_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
            """پردازش انتخاب پلن و ارائه اطلاعات پرداخت"""
            query = update.callback_query
            await query.answer()

            plan_id = query.data.replace("r_buy_", "")
            plans = load_plans()
            plan = plans.get(plan_id)
            if not plan:
                await query.edit_message_text("❌ پلن مورد نظر یافت نشد.")
                return

            price = plan.get("price", 0)
            pname = plan.get("name", "پلن")
            vol = plan.get("traffic", plan.get("volume_gb", 0))
            days = plan.get("duration_days", plan.get("days", 30))

            card_num = self.reseller_data.get("card_number") or ""
            card_holder = self.reseller_data.get("card_holder") or ""
            bank_name = self.reseller_data.get("bank_name") or ""

            context.user_data["buying_plan_id"] = plan_id
            context.user_data["buying_price"] = price

            msg = f"🛒 **پیش‌فاکتور خرید اشتراک**\n\n"
            msg += f"📦 پلن: **{pname}**\n"
            msg += f"📊 حجم: **{vol} گیگابایت** | ⏳ مدت: **{days} روز**\n"
            msg += f"💰 مبلغ قابل پرداخت: **{price:,} تومان**\n\n"

            if card_num:
                msg += "💳 **اطلاعات کارت جهت واریز:**\n"
                msg += f"شماره کارت: `{card_num}`\n"
                if card_holder:
                    msg += f"به نام: **{card_holder}**\n"
                if bank_name:
                    msg += f"بانک: {bank_name}\n"
                msg += "\n📸 لطفاً پس از واریز، **عکس فیش واریزی** خود را در همین گفتگو ارسال نمایید."
            else:
                msg += "💳 جهت پرداخت و دریافت شماره کارت، با پشتیبانی تماس حاصل فرمایید."

            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ انصراف", callback_data="r_cancel_buy")]
            ])
            await query.edit_message_text(msg, reply_markup=kb, parse_mode="Markdown")

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
                receipt_image=photo_file_id,
                receipt_file_type="photo",
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

                plans = load_plans()
                plan = plans.get(plan_id, {})
                pname = plan.get("name", "اشتراک")
                vol = plan.get("traffic", plan.get("volume_gb", 30))
                days = plan.get("duration_days", plan.get("days", 30))
                price = plan.get("price", 0)

                # محاسبه کسر موجودی عمده از کیف پول نماینده
                discount_pct = self.reseller_data.get("discount_percent", 20)
                wholesale_cost = price - int((price * discount_pct) / 100)

                # کسر موجودی از کیف پول نماینده
                account_name = f"r{r_id}_u{target_uid}_{int(datetime.now().timestamp()) % 10000}"
                deduct_res = db.deduct_reseller_balance(r_id, wholesale_cost, pname, account_name)

                if not deduct_res.get("success"):
                    await query.edit_message_caption(
                        caption=f"❌ **خطا در تایید:** موجودی کیف پول نماینده کافی نیست!\n"
                                f"مبلغ مورد نیاز با احتساب تخفیف: {wholesale_cost:,} تومان\n"
                                f"لطفاً ابتدا کیف پول خود را در پنل وب شارژ کنید.",
                        parse_mode="Markdown"
                    )
                    return

                # ساخت در هیدیفای
                h_res = None
                try:
                    h_res = await hidify_client.create_user(
                        name=account_name,
                        package_days=int(days),
                        usage_limit_GB=float(vol),
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

                # ویرایش پیام نماینده
                await query.edit_message_caption(
                    caption=f"✅ **پرداخت تایید شد و اشتراک با موفقیت تحویل مشتری گردید.**\n"
                            f"📦 پلن: {pname} | 💰 هزینه عمده کسر شده: {wholesale_cost:,} تومان\n"
                            f"👤 نام اشتراک: `{account_name}`",
                    parse_mode="Markdown"
                )

                # ارسال لینک اشتراک برای مشتری در ربات
                try:
                    brand = self.reseller_data.get("brand_name") or "ما"
                    cust_msg = f"🎉 **پرداخت شما تایید شد! اشتراک {brand} آماده است:**\n\n"
                    cust_msg += f"📦 پلن: **{pname}**\n"
                    cust_msg += f"📊 حجم: **{vol} گیگابایت** | ⏳ مدت: **{days} روز**\n\n"
                    cust_msg += f"🔗 **لینک اتصال اختصاصی شما:**\n`{sub_url}`\n\n"
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

            text = "📋 **لیست اشتراک‌های شما:**\n\n"
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
            if sup_user:
                sup_clean = sup_user.replace("@", "")
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("💬 ارتباط مستقیم در تلگرام", url=f"https://t.me/{sup_clean}")]
                ])
                await update.message.reply_text(f"🎧 جهت ارتباط با واحد پشتیبانی **{brand}** روی دکمه زیر کلیک کنید:", reply_markup=kb)
            else:
                await update.message.reply_text("🎧 جهت ثبت پیام پشتیبانی، پیام خود را در همین بخش ارسال نمایید تا به همکاران ما ارجاع داده شود.")

        async def guide_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
            """راهنمای اتصال"""
            guide_text = (
                "📖 **راهنمای استفاده و اتصال:**\n\n"
                "۱. نرم‌افزار متناسب با سیستم‌عامل خود را نصب کنید:\n"
                "• اندروید: v2rayNG / Hiddify Next / Happ\n"
                "• آیفون (iOS): Streisand / FoXray / V2Box / Shadowrocket\n"
                "• ویندوز: Hiddify Next / v2rayN / Nekoray\n\n"
                "۲. لینک دریافتی را کپی کرده و در برنامه Import / Add Config from Clipboard را بزنید.\n"
                "۳. دکمه اتصال (Connect) را روشن نمایید."
            )
            await update.message.reply_text(guide_text, parse_mode="Markdown")

        async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
            """مسیریابی دکمه‌های ریپلای کیبورد"""
            text = update.message.text or ""
            if "خرید اشتراک" in text:
                await plans_handler(update, context)
            elif "اشتراک‌های من" in text:
                await my_subs_handler(update, context)
            elif "کیف پول" in text:
                user = update.effective_user
                bal = db.get_user_wallet_balance(user.id)
                await update.message.reply_text(f"💳 موجودی کیف پول شما: **{bal:,} تومان**", parse_mode="Markdown")
            elif "پشتیبانی" in text:
                await support_handler(update, context)
            elif "راهنما" in text:
                await guide_handler(update, context)
            else:
                # پاسخ عمومی
                await update.message.reply_text("لطفاً از دکمه‌های منو استفاده فرمایید.")

        # ثبت هندلرها
        app.add_handler(CommandHandler("start", start_handler))
        app.add_handler(CommandHandler("plans", plans_handler))
        app.add_handler(CommandHandler("help", guide_handler))
        app.add_handler(CallbackQueryHandler(buy_plan_callback, pattern="^r_buy_"))
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
