#!/usr/bin/env python3
"""
ربات تلگرام مدیریت VPN با اتصال به Hidify
"""

import os
import json
import logging
import uuid
import asyncio
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from hidify import HidifyClient
import threading
from dashboard import run_dashboard, start_dashboard_thread
from payment import PaymentManager
from utils import (
    gregorian_to_shamsi, gregorian_to_shamsi_full, 
    get_now_shamsi, days_remaining_shamsi, is_expired,
    get_now, get_now_naive, get_now_iso, get_now_timestamp,
    generate_qr_code_bytes
)
from admin_manager import (
    load_cards, add_card, update_card, delete_card, get_active_card, get_all_cards,
    load_plans, add_plan, update_plan, delete_plan, get_active_plans, get_all_plans, get_plan,
)
from database import db
from backup import BackupManager, AutoBackupScheduler, send_backup_to_admin
from notifications import NotificationScheduler
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

# ─── بارگذاری متغیرهای محیطی ───
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
HIDIFY_PANEL_URL = os.getenv("HIDIFY_PANEL_URL")
HIDIFY_PANEL_URL_TEST = os.getenv("HIDIFY_PANEL_URL_TEST", HIDIFY_PANEL_URL)
HIDIFY_API_KEY = os.getenv("HIDIFY_API_KEY")
HIDIFY_PROXY_PATH = os.getenv("HIDIFY_PROXY_PATH")
USER_PROXY_PATH = os.getenv("USER_PROXY_PATH", HIDIFY_PROXY_PATH)
USER_PROXY_PATH_TEST = os.getenv("USER_PROXY_PATH_TEST", HIDIFY_PROXY_PATH)
PAYMENT_GATEWAY = os.getenv("PAYMENT_GATEWAY", "zarinpal")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
CARD_NUMBER = os.getenv("CARD_NUMBER", "")
CARD_HOLDER = os.getenv("CARD_HOLDER", "")
BANK_NAME = os.getenv("BANK_NAME", "")

# ─── کانال‌های اجباری ───
REQUIRED_CHANNELS = []
for i in range(1, 4):
    ch_id = os.getenv(f"CHANEL_TG_ID_{i}", "")
    if ch_id and ch_id.strip():
        REQUIRED_CHANNELS.append(ch_id.strip())

# ─── تنظیم لاگینگ ───
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─── مسیر ذخیره‌سازی اطلاعات کاربران ───
DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

# ─── وضعیت‌های مکالمه ───
(
    CHOOSING,
    SELECTING_PLAN,
    CONFIRMING_PURCHASE,
    SELECTING_PAYMENT,
    ENTERING_CARD_NUMBER,
    ENTERING_CARD_HOLDER,
    ENTERING_TRACKING_CODE,
    # وضعیت‌های مدیریت ادمین
    ADMIN_MENU,
    ADMIN_CARDS_MENU,
    ADMIN_ADD_CARD_NUMBER,
    ADMIN_ADD_CARD_HOLDER,
    ADMIN_ADD_CARD_BANK,
    ADMIN_PLANS_MENU,
    ADMIN_ADD_PLAN_NAME,
    ADMIN_ADD_PLAN_PRICE,
    ADMIN_ADD_PLAN_DATA,
    ADMIN_ADD_PLAN_DURATION,
    ADMIN_RESTORE_FILE,
    SELECTING_NAME_TYPE,
    ENTERING_CUSTOM_NAME,
    RENEWING,
    ENTERING_DISCOUNT_CODE,
    ENTERING_TICKET_MESSAGE,
    ADMIN_REPLYING_TICKET,
) = range(24)


async def send_subscription_card(bot, chat_id: int, sub_url: str, title: str, details: str = ""):
    """ارسال کارت اشتراک همراه با QR Code و دکمه‌های استاندارد اتصال"""
    clean_sub_url = sub_url.strip()
    caption = (
        f"{title}\n\n"
        f"{details}\n\n"
        f"🔗 **لینک اتصال شما (برای کپی لمس کنید):**\n"
        f"`{clean_sub_url}`\n\n"
        f"💡 **راهنمای اتصال سریع:**\n"
        f"• لینک بالا را لمس کنید تا در کلیپ‌بورد کپی شود.\n"
        f"• وارد نرم‌افزار (Hiddify / v2rayNG / Streisand) شوید و دکمه **+** یا **Import** را بزنید.\n"
        f"• یا از طریق دکمه «🌐 صفحه کاربری و اتصال سریع» وارد شوید."
    )

    keyboard = [
        [
            InlineKeyboardButton("🌐 صفحه کاربری و اتصال سریع", url=clean_sub_url),
        ],
        [
            InlineKeyboardButton("📋 راهنمای کپی لینک", callback_data="copy_link"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    qr_bytes = generate_qr_code_bytes(clean_sub_url)
    if qr_bytes:
        try:
            await bot.send_photo(
                chat_id=chat_id,
                photo=qr_bytes,
                caption=caption,
                reply_markup=reply_markup,
                parse_mode="Markdown",
            )
            return
        except Exception as e:
            logger.warning(f"Error sending QR Code photo markdown: {e}")
            try:
                await bot.send_photo(
                    chat_id=chat_id,
                    photo=qr_bytes,
                    caption=caption,
                    reply_markup=reply_markup,
                )
                return
            except Exception as e2:
                logger.warning(f"Error sending QR Code photo plain: {e2}")

    try:
        await bot.send_message(
            chat_id=chat_id,
            text=caption,
            reply_markup=reply_markup,
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.warning(f"Error sending subscription text markdown: {e}")
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=caption,
                reply_markup=reply_markup,
            )
        except Exception as e2:
            logger.error(f"Error sending subscription text message: {e2}")


# ─── دریافت پلن‌ها ───
def get_plans() -> dict:
    """دریافت پلن‌های فعال"""
    return get_active_plans()


# ─── بررسی عضویت در کانال‌ها ───
async def check_channel_membership(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    بررسی آیا کاربر در تمام کانال‌های اجباری عضو هست
    Returns: True اگر عضو باشد یا کانالی تنظیم نشده باشد
    """
    if not REQUIRED_CHANNELS:
        return True
    
    bot = context.bot
    not_joined = []
    
    for channel_id in REQUIRED_CHANNELS:
        try:
            member = await bot.get_chat_member(chat_id=channel_id, user_id=user_id)
            # بررسی وضعیت عضویت
            status = member.status
            if status not in ["member", "administrator", "creator"]:
                not_joined.append(channel_id)
        except Exception as e:
            logger.warning(f"Error checking membership for {channel_id}: {e}")
            # اگه خطا خورد، کانال رو نادیده بگیر (ممکنه ربات admin نباشه)
            pass
    
    return len(not_joined) == 0


async def show_join_channels_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    نمایش پیام اجباری عضویت در کانال‌ها
    """
    text = "🔒 برای استفاده از ربات، ابتدا در کانال‌های زیر عضو شوید:\n\n"
    
    keyboard = []
    for i, channel_id in enumerate(REQUIRED_CHANNELS, 1):
        try:
            chat = await context.bot.get_chat(chat_id=channel_id)
            chat_title = chat.title or f"کانال {i}"
            chat_username = chat.username
            
            if chat_username:
                link = f"https://t.me/{chat_username}"
            else:
                link = f"https://t.me/c/{str(channel_id)[4:]}" if str(channel_id).startswith("-100") else ""
            
            text += f"{i}. {chat_title}\n"
            if link:
                keyboard.append([InlineKeyboardButton(f"🔗 {chat_title}", url=link)])
        except Exception as e:
            logger.warning(f"Error getting chat info for {channel_id}: {e}")
            text += f"{i}. کانال {i}\n"
    
    text += "\n✅ پس از عضویت، دکمه «بررسی عضویت» را بزنید."
    
    keyboard.append([InlineKeyboardButton("✅ بررسی عضویت", callback_data="check_membership")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, reply_markup=reply_markup)


# ═══════════════════════════════════════════════════════════════════════
# ساخت نمونه کلاینت Hidify
# ═══════════════════════════════════════════════════════════════════════

hidify = HidifyClient(HIDIFY_PANEL_URL, HIDIFY_API_KEY, HIDIFY_PROXY_PATH)


# ═══════════════════════════════════════════════════════════════════════
# مدیریت اطلاعات کاربران ربات (دیتابیس)
# ═══════════════════════════════════════════════════════════════════════

def get_user_data(telegram_user_id: int) -> dict:
    """دریافت اطلاعات کاربر از دیتابیس"""
    user = db.get_user(telegram_user_id)
    if user:
        # تبدیل به فرمت قدیمی برای سازگاری
        return {
            "telegram_id": user.get("telegram_id"),
            "username": user.get("username"),
            "hidify_uuid": user.get("hidify_uuid"),
            "plan": user.get("plan_id"),
            "data_limit": user.get("data_limit", 0),
            "expire_at": user.get("expire_at"),
            "created_at": user.get("created_at"),
        }
    return {}


def save_user_data(telegram_user_id: int, data: dict):
    """ذخیره اطلاعات کاربر در دیتابیس"""
    db.save_user(
        telegram_id=telegram_user_id,
        username=data.get("username", f"tg_{telegram_user_id}"),
        hidify_uuid=data.get("hidify_uuid", ""),
        plan_id=data.get("plan", ""),
        data_limit=data.get("data_limit", 0),
        expire_at=data.get("expire_at"),
    )


# ═══════════════════════════════════════════════════════════════════════
# هندلرهای ربات
# ═══════════════════════════════════════════════════════════════════════

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دستور /start - شروع ربات"""
    user = update.effective_user
    
    # ثبت کاربر در دیتابیس
    db.save_user(telegram_id=user.id, username=user.username or user.first_name)

    # پردازش کد معرف / رفرال
    if context.args and len(context.args) > 0:
        arg = context.args[0].strip()
        if arg.startswith("ref_"):
            try:
                referrer_id = int(arg.replace("ref_", ""))
                if referrer_id != user.id:
                    db.add_referral(referrer_id, user.id)
            except Exception as e:
                logger.warning(f"Referral parsing error: {e}")

    # بررسی عضویت در کانال‌ها
    if REQUIRED_CHANNELS:
        is_member = await check_channel_membership(user.id, context)
        if not is_member:
            await show_join_channels_message(update, context)
            return CHOOSING
    
    # بررسی بلاک بودن کاربر
    if db.is_blocked(user.id) and user.id != ADMIN_ID:
        await update.message.reply_text(
            "⛔ شما بلاک شده‌اید!\n\n"
            "برای رفع بلاک با پشتیبانی تماس بگیرید."
        )
        return CHOOSING
    
    # منوی معمولی
    keyboard = [
        [KeyboardButton("🛒 خرید اشتراک"), KeyboardButton("🧪 اشتراک تست")],
        [KeyboardButton("🔄 تمدید اشتراک"), KeyboardButton("📊 وضعیت اشتراک")],
        [KeyboardButton("🔗 لینک اتصال"), KeyboardButton("💰 کیف پول")],
        [KeyboardButton("👥 زیرمجموعه‌گیری"), KeyboardButton("💬 پشتیبانی")],
        [KeyboardButton("❓ راهنمای ربات"), KeyboardButton("📚 آموزش‌ها (بزودی)")],
    ]
    
    # اضافه کردن دکمه ادمین
    if user.id == ADMIN_ID:
        keyboard.append([KeyboardButton("🔧 پنل مدیریت")])
    
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    welcome_text = f"""
سلام {user.first_name}! 👋

به ربات مدیریت و خرید VPN خوش آمدید!

از منوی زیر می‌توانید:
• 🛒 خرید اشتراک جدید
• 🧪 اشتراک تست (رایگان)
• 🔄 تمدید اشتراک
• 📊 مشاهده وضعیت اشتراک
• 🔗 دریافت لینک اتصال
• 💰 مشاهده کیف پول
• 👥 زیرمجموعه‌گیری و کسب درآمد
• 💬 پشتیبانی و ارسال تیکت
• ❓ راهنمای ربات
• 📚 آموزش‌ها (بزودی)
"""
    
    if user.id == ADMIN_ID:
        welcome_text += "• 🔧 پنل مدیریت\n"
    
    welcome_text += "\nلطفاً یکی از گزینه‌ها را انتخاب کنید:"
    
    await update.message.reply_text(welcome_text, reply_markup=reply_markup)
    return CHOOSING


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """لغو مکالمه"""
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(
            "❌ عملیات لغو شد.\n\n"
            "برای شروع مجدد، دکمه «🛒 خرید اشتراک» رو بزنید."
        )
    else:
        await update.message.reply_text(
            "❌ عملیات لغو شد.\n\n"
            "برای شروع مجدد، دکمه «🛒 خرید اشتراک» رو بزنید."
        )
    return ConversationHandler.END


async def timeout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ timeout مکالمه """
    await update.message.reply_text(
        "⏰ زمان مکالمه تمام شد.\n\n"
        "برای شروع مجدد، دکمه «🛒 خرید اشتراک» رو بزنید."
    )
    return ConversationHandler.END


async def back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بازگشت به منوی اصلی"""
    query = update.callback_query
    if query:
        await query.answer()
    
    context.user_data.pop("is_waiting_ticket", None)
    context.user_data.pop("replying_ticket_id", None)
    
    user = update.effective_user
    keyboard = [
        [KeyboardButton("🛒 خرید اشتراک"), KeyboardButton("🧪 اشتراک تست")],
        [KeyboardButton("🔄 تمدید اشتراک"), KeyboardButton("📊 وضعیت اشتراک")],
        [KeyboardButton("🔗 لینک اتصال"), KeyboardButton("💰 کیف پول")],
        [KeyboardButton("👥 زیرمجموعه‌گیری"), KeyboardButton("💬 پشتیبانی")],
        [KeyboardButton("❓ راهنمای ربات"), KeyboardButton("📚 آموزش‌ها (بزودی)")],
    ]
    if user.id == ADMIN_ID:
        keyboard.append([KeyboardButton("🔧 پنل مدیریت")])
    
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    try:
        await query.edit_message_text("🏠 منوی اصلی")
    except Exception:
        pass
    await context.bot.send_message(
        chat_id=user.id,
        text="لطفاً یکی از گزینه‌ها را انتخاب کنید:",
        reply_markup=reply_markup
    )
    return CHOOSING


async def back_to_select_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بازگشت به لیست پلن‌ها"""
    query = update.callback_query
    await query.answer()
    return await show_plans(update, context)


async def back_to_confirm_purchase(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بازگشت به صفحه تایید خرید"""
    query = update.callback_query
    await query.answer()
    
    plan_id = context.user_data.get("selected_plan")
    plans = get_plans()
    if not plan_id or plan_id not in plans:
        return await back_to_menu(update, context)
    
    plan = plans[plan_id]
    price_formatted = f"{plan['price']:,}".replace(",", "،")
    text = f"""
📋 **انتخاب پلن:** {plan['name']}

• حجم: {plan['data_limit'] if plan['data_limit'] > 0 else 'نامحدود'} گیگابایت
• مدت: {plan['duration']} روز
• قیمت: {price_formatted} تومان

آیا مایل به خرید این پلن هستید؟
"""
    keyboard = [
        [
            InlineKeyboardButton("✅ تایید خرید", callback_data="confirm_purchase"),
            InlineKeyboardButton("◀️ بازگشت", callback_data="back_to_select_plan"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    return CONFIRMING_PURCHASE


async def back_to_select_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بازگشت به انتخاب روش پرداخت"""
    query = update.callback_query
    await query.answer()
    
    plan_id = context.user_data.get("selected_plan")
    plans = get_plans()
    if not plan_id or plan_id not in plans:
        return await back_to_menu(update, context)
    
    plan = plans[plan_id]
    price_formatted = f"{plan['price']:,}".replace(",", "،")
    text = f"""
💳 **انتخاب روش پرداخت**

📋 پلن: {plan['name']}
💰 مبلغ: {price_formatted} تومان

لطفاً روش پرداخت را انتخاب کنید:
"""
    keyboard = [
        [InlineKeyboardButton("💳 درگاه آنلاین (بزودی)", callback_data="coming_soon")],
        [InlineKeyboardButton("💵 کارت به کارت", callback_data="pay_card")],
        [InlineKeyboardButton("◀️ بازگشت", callback_data="back_to_confirm_purchase"), InlineKeyboardButton("❌ انصراف", callback_data="cancel")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    return SELECTING_PAYMENT


async def back_to_enter_tracking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بازگشت به مرحله وارد کردن کد پیگیری"""
    query = update.callback_query
    await query.answer()
    
    plan_id = context.user_data.get("selected_plan")
    plans = get_plans()
    plan = plans.get(plan_id, {})
    price_formatted = f"{plan.get('price', 0):,}".replace(",", "،")
    
    # دریافت کارت فعال
    active_card = get_active_card()
    card_number = active_card.get("card_number", CARD_NUMBER)
    card_holder = active_card.get("card_holder", CARD_HOLDER)
    bank_name = active_card.get("bank_name", BANK_NAME)

    text = f"""
💵 **پرداخت کارت به کارت**

📋 پلن: {plan.get('name', 'نامشخص')}
💰 مبلغ: {price_formatted} تومان

📌 **اطلاعات کارت:**
```
{card_number}
```
👤 **نام صاحب کارت:** {card_holder}
🏦 **بانک:** {bank_name}

⚠️ **نکات مهم:**
• دقیقاً مبلغ بالا را واریز کنید
• بعد از واریز، رسید پرداخت را ارسال کنید
• رسید پرداخت برای ادمین ارسال میشود

لطفاً بعد از واریز:
• متن 📝 رسید یا اسکرین‌شات 📷 رسید را ارسال کنید
"""
    keyboard = [
        [InlineKeyboardButton("◀️ بازگشت", callback_data="back_to_select_payment"), InlineKeyboardButton("❌ انصراف", callback_data="cancel")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    return ENTERING_TRACKING_CODE


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دستور /help - راهنما"""
    help_text = """
📖 **راهنمای ربات VPN**

**🛒 خرید اشتراک:**
یکی از پلن‌های موجود را انتخاب کنید و پس از پرداخت، اشتراک شما فعال می‌شود.

**🔄 تمدید اشتراک:**
اشتراک فعلی خود را برای یک دوره دیگر تمدید کنید.

**📊 وضعیت اشتراک:**
اطلاعات کامل اشتراک شامل حجم مصرفی، تاریخ انقضا و ...

**🔗 لینک اتصال:**
لینک اشتراک خود را برای اتصال دریافت کنید.

⚠️ **نکات مهم:**
• لینک اشتراک را با کسی به اشتراک نگذارید
• در صورت بروز مشکل با پشتیبانی تماس بگیرید
"""
    await update.message.reply_text(help_text, parse_mode="Markdown")


# ─── پنل مدیریت وب ───
dashboard_thread = None

def start_dashboard_thread():
    """شروع پنل مدیریت در thread جداگانه"""
    global dashboard_thread
    if dashboard_thread is None or not dashboard_thread.is_alive():
        port = int(os.getenv("PORT", 5000))
        dashboard_thread = threading.Thread(
            target=run_dashboard,
            kwargs={"host": "0.0.0.0", "port": port, "debug": False},
            daemon=True
        )
        dashboard_thread.start()
        logger.info(f"Dashboard thread started on port {port}")


async def dashboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دستور /dashboard - نمایش اطلاعات پنل مدیریت وب"""
    user = update.effective_user
    
    if user.id != ADMIN_ID:
        await update.message.reply_text("❌ شما ادمین نیستید!")
        return
    
    port = int(os.getenv("PORT", 5000))
    dashboard_text = f"""
🌐 **پنل مدیریت وب**

پنل مدیریت خودکار فعال است!

**آدرس پنل:**
`http://localhost:{port}`

**نام کاربری:** `{ADMIN_USERNAME}`
**رمز عبور:** `{ADMIN_PASSWORD}`

⚠️ **نکته:** برای دسترسی از خارج سرور، آدرس IP سرور رو جایگزین localhost کنید.
"""
    
    await update.message.reply_text(dashboard_text, parse_mode="Markdown")


async def show_plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش پلن‌های اشتراک"""
    plans = get_plans()
    
    if not plans:
        await update.message.reply_text(
            "❌ هیچ پلن فعالی وجود ندارد!\n\n"
            "لطفاً با پشتیبانی تماس بگیرید."
        )
        return CHOOSING

    keyboard = []
    for plan_id, plan in plans.items():
        price_formatted = f"{plan['price']:,}".replace(",", "،")
        keyboard.append([
            InlineKeyboardButton(
                f"{plan['name']} - {plan['description']} - {price_formatted} تومان",
                callback_data=f"plan_{plan_id}",
            )
        ])
    keyboard.append([InlineKeyboardButton("◀️ بازگشت", callback_data="back_to_menu")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    text = "🛒 **پلن‌های اشتراک:**\n\nلطفاً یکی از پلن‌های زیر را انتخاب کنید:"
    if update.callback_query:
        await update.callback_query.edit_message_text(
            text,
            reply_markup=reply_markup,
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text(
            text,
            reply_markup=reply_markup,
            parse_mode="Markdown",
        )
    return SELECTING_PLAN


async def plan_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """انتخاب پلن"""
    query = update.callback_query
    await query.answer()

    # اگر دکمه بازگشت زده شده
    if query.data == "back_to_menu":
        return await back_to_menu(update, context)

    if query.data == "cancel":
        await query.edit_message_text("❌ عملیات لغو شد.")
        return CHOOSING

    plan_id = query.data.replace("plan_", "")
    plans = get_plans()
    if plan_id not in plans:
        await query.edit_message_text("❌ پلن نامعتبر!")
        return CHOOSING

    plan = plans[plan_id]
    context.user_data["selected_plan"] = plan_id

    price_formatted = f"{plan['price']:,}".replace(",", "،")
    text = (
        f"📋 پلن انتخاب شده: {plan['name']}\n\n"
        f"• حجم: {plan['data_limit'] if plan['data_limit'] > 0 else 'نامحدود'} گیگابایت\n"
        f"• مدت: {plan['duration']} روز\n"
        f"• قیمت: {price_formatted} تومان\n\n"
        f"📝 نام اکانت خود را انتخاب کنید:"
    )
    keyboard = [
        [InlineKeyboardButton("🔄 انتخاب خودکار(آیدی تلگرام)", callback_data="name_telegram_id")],
        [InlineKeyboardButton("✏️ نام دلخواه", callback_data="name_custom")],
        [InlineKeyboardButton("◀️ بازگشت", callback_data="back_to_select_plan")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup)
    return SELECTING_NAME_TYPE


async def select_name_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """انتخاب نوع نام اکانت"""
    query = update.callback_query
    await query.answer()

    if query.data == "back_to_select_plan":
        # بازگشت به لیست پلن‌ها
        return await back_to_select_plan(update, context)

    if query.data == "cancel":
        await query.edit_message_text("❌ عملیات لغو شد.")
        return CHOOSING

    user = update.effective_user
    plan_id = context.user_data.get("selected_plan")
    plans = get_plans()
    plan = plans.get(plan_id, {})
    price_formatted = f"{plan.get('price', 0):,}".replace(",", "،")

    if query.data == "name_telegram_id":
        # استفاده از آیدی تلگرام
        context.user_data["account_name"] = f"tg_{user.id}"
        context.user_data["account_comment"] = None

        text = (
            f"📋 پلن انتخاب شده: {plan.get('name', 'نامشخص')}\n\n"
            f"• حجم: {plan.get('data_limit', 0) if plan.get('data_limit', 0) > 0 else 'نامحدود'} گیگابایت\n"
            f"• مدت: {plan.get('duration', 0)} روز\n"
            f"• قیمت: {price_formatted} تومان\n\n"
            f"📝 نام اکانت: tg_{user.id}\n\n"
            f"آیا مایل به خرید این پلن هستید?"
        )
        keyboard = [
            [
                InlineKeyboardButton("✅ تایید خرید", callback_data="confirm_purchase"),
                InlineKeyboardButton("◀️ بازگشت", callback_data="back_to_name_selection"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup)
        return CONFIRMING_PURCHASE

    elif query.data == "name_custom":
        # نام دلخواه
        text = (
            "✏️ نام دلخواه خود را وارد کنید:\n\n"
            "⚠️ این نام در پنل Hidify نمایش داده خواهد شد.\n\n"
            "💡 نمونه: علی، محمد، user123"
        )
        keyboard = [
            [InlineKeyboardButton("◀️ بازگشت", callback_data="back_to_name_selection")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup)
        return ENTERING_CUSTOM_NAME

    return SELECTING_NAME_TYPE


async def enter_custom_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دریافت نام دلخواه"""
    user = update.effective_user
    custom_name = update.message.text.strip()

    if not custom_name:
        await update.message.reply_text("❌ لطفاً نامی وارد کنید.")
        return ENTERING_CUSTOM_NAME

    # ذخیره نام دلخواه
    context.user_data["account_name"] = custom_name
    context.user_data["account_comment"] = str(user.id)

    plan_id = context.user_data.get("selected_plan")
    plans = get_plans()
    plan = plans.get(plan_id, {})
    price_formatted = f"{plan.get('price', 0):,}".replace(",", "،")

    text = (
        f"📋 پلن انتخاب شده: {plan.get('name', 'نامشخص')}\n\n"
        f"• حجم: {plan.get('data_limit', 0) if plan.get('data_limit', 0) > 0 else 'نامحدود'} گیگابایت\n"
        f"• مدت: {plan.get('duration', 0)} روز\n"
        f"• قیمت: {price_formatted} تومان\n\n"
        f"📝 نام اکانت: {custom_name}\n"
        f"🆔 آیدی تلگرام: {user.id}\n\n"
        f"آیا مایل به خرید این پلن هستید?"
    )
    keyboard = [
        [
            InlineKeyboardButton("✅ تایید خرید", callback_data="confirm_purchase"),
            InlineKeyboardButton("◀️ بازگشت", callback_data="back_to_name_selection"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(text, reply_markup=reply_markup)
    return CONFIRMING_PURCHASE


async def back_to_name_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بازگشت به انتخاب نوع نام"""
    query = update.callback_query
    await query.answer()

    plan_id = context.user_data.get("selected_plan")
    plans = get_plans()
    plan = plans.get(plan_id, {})
    price_formatted = f"{plan.get('price', 0):,}".replace(",", "،")

    text = (
        f"📋 پلن انتخاب شده: {plan.get('name', 'نامشخص')}\n\n"
        f"• حجم: {plan.get('data_limit', 0) if plan.get('data_limit', 0) > 0 else 'نامحدود'} گیگابایت\n"
        f"• مدت: {plan.get('duration', 0)} روز\n"
        f"• قیمت: {price_formatted} تومان\n\n"
        f"📝 نام اکانت خود را انتخاب کنید:"
    )
    keyboard = [
        [InlineKeyboardButton("🔄 انتخاب خودکار(آیدی تلگرام)", callback_data="name_telegram_id")],
        [InlineKeyboardButton("✏️ نام دلخواه", callback_data="name_custom")],
        [InlineKeyboardButton("◀️ بازگشت", callback_data="back_to_select_plan")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup)
    return SELECTING_NAME_TYPE


async def select_payment_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """انتخاب روش پرداخت"""
    query = update.callback_query
    await query.answer()

    if query.data == "cancel":
        await query.edit_message_text("❌ عملیات لغو شد.")
        return CHOOSING

    if query.data != "confirm_purchase":
        return CONFIRMING_PURCHASE

    plan_id = context.user_data.get("selected_plan")
    plans = get_plans()
    if not plan_id or plan_id not in plans:
        await query.edit_message_text("❌ خطا در انتخاب پلن!")
        return CHOOSING

    plan = plans[plan_id]
    price_formatted = f"{plan['price']:,}".replace(",", "،")

    text = f"""
💳 **انتخاب روش پرداخت**

📋 پلن: {plan['name']}
💰 مبلغ: {price_formatted} تومان

لطفاً روش پرداخت را انتخاب کنید:
"""

    keyboard = [
        [InlineKeyboardButton("💳 درگاه آنلاین (بزودی)", callback_data="coming_soon")],
        [InlineKeyboardButton("💵 کارت به کارت", callback_data="pay_card")],
        [InlineKeyboardButton("◀️ بازگشت", callback_data="back_to_confirm_purchase"), InlineKeyboardButton("❌ انصراف", callback_data="cancel")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    return SELECTING_PAYMENT


async def handle_payment_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش انتخاب روش پرداخت"""
    query = update.callback_query
    await query.answer()

    if query.data == "back_to_confirm_purchase":
        return await back_to_confirm_purchase(update, context)

    if query.data == "cancel":
        await query.edit_message_text("❌ عملیات لغو شد.")
        return CHOOSING

    plan_id = context.user_data.get("selected_plan")
    plans = get_plans()
    plan = plans.get(plan_id, {})
    price_formatted = f"{plan.get('price', 0):,}".replace(",", "،")

    if query.data == "coming_soon":
        # درگاه آنلاین بزودی
        await query.answer("⏳ این قابلیت بزودی اضافه خواهد شد!", show_alert=True)
        return SELECTING_PAYMENT

    elif query.data == "pay_online":
        # پرداخت آنلاین
        return await confirm_purchase(update, context)

    elif query.data == "pay_card":
        # کارت به کارت
        # دریافت کارت فعال
        active_card = get_active_card()
        card_number = active_card.get("card_number", CARD_NUMBER)
        card_holder = active_card.get("card_holder", CARD_HOLDER)
        bank_name = active_card.get("bank_name", BANK_NAME)

        text = f"""
💵 **پرداخت کارت به کارت**

📋 پلن: {plan.get('name', 'نامشخص')}
💰 مبلغ: {price_formatted} تومان

📌 **اطلاعات کارت:**
```
{card_number}
```
👤 **نام صاحب کارت:** {card_holder}
🏦 **بانک:** {bank_name}

⚠️ **نکات مهم:**
• دقیقاً مبلغ بالا را واریز کنید
• بعد از واریز، رسید پرداخت را ارسال کنید
• رسید پرداخت برای ادمین ارسال میشود

لطفاً بعد از واریز:
• 📝 **شماره پیگیری** را وارد کنید
• یا 📷 **اسکرین‌شات رسید** را ارسال کنید:
"""
        keyboard = [
            [InlineKeyboardButton("◀️ بازگشت", callback_data="back_to_select_payment"), InlineKeyboardButton("❌ انصراف", callback_data="cancel")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
        return ENTERING_TRACKING_CODE

    return SELECTING_PAYMENT


async def enter_tracking_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دریافت شماره پیگیری"""
    tracking_code = update.message.text.strip()

    # بررسی اینکه کد خالی نباشد
    if not tracking_code:
        await update.message.reply_text(
            "❌ لطفاً شماره پیگیری را وارد کنید:"
        )
        return ENTERING_TRACKING_CODE

    context.user_data["tracking_code"] = tracking_code
    context.user_data.pop("receipt_photo", None)  # پاک کردن عکس قبلی
    user = update.effective_user
    plan_id = context.user_data.get("selected_plan")
    plans = get_plans()
    plan = plans.get(plan_id, {})
    price_formatted = f"{plan.get('price', 0):,}".replace(",", "،")

    # تایید اطلاعات
    text = (
        f"✅ تایید پرداخت کارت به کارت\n\n"
        f"📋 پلن: {plan.get('name', 'نامشخص')}\n"
        f"💰 مبلغ: {price_formatted} تومان\n"
        f"🔢 شماره پیگیری: {tracking_code}\n\n"
        f"آیا اطلاعات صحیح است?"
    )
    keyboard = [
        [InlineKeyboardButton("✅ تایید و ارسال", callback_data="confirm_card_payment")],
        [InlineKeyboardButton("◀️ بازگشت", callback_data="back_to_enter_tracking"), InlineKeyboardButton("❌ انصراف", callback_data="cancel")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(text, reply_markup=reply_markup)
    return CONFIRMING_PURCHASE


async def enter_tracking_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دریافت عکس رسید پرداخت"""
    user = update.effective_user
    plan_id = context.user_data.get("selected_plan")
    plans = get_plans()
    plan = plans.get(plan_id, {})
    price_formatted = f"{plan.get('price', 0):,}".replace(",", "،")

    # دریافت file_id عکس
    photo = update.message.photo[-1]  # بزرگترین سایز
    file_id = photo.file_id

    # ذخیره اطلاعات
    context.user_data["tracking_code"] = "اسکرین‌شات رسید"
    context.user_data["receipt_photo"] = file_id

    # تایید اطلاعات
    text = (
        f"✅ تایید پرداخت کارت به کارت\n\n"
        f"📋 پلن: {plan.get('name', 'نامشخص')}\n"
        f"💰 مبلغ: {price_formatted} تومان\n"
        f"📷 رسید: اسکرین‌شات ارسال شد\n\n"
        f"آیا اطلاعات صحیح است?"
    )
    keyboard = [
        [InlineKeyboardButton("✅ تایید و ارسال", callback_data="confirm_card_payment")],
        [InlineKeyboardButton("◀️ بازگشت", callback_data="back_to_enter_tracking"), InlineKeyboardButton("❌ انصراف", callback_data="cancel")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(text, reply_markup=reply_markup)
    return CONFIRMING_PURCHASE


async def apply_discount_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """درخواست ورود کد تخفیف"""
    query = update.callback_query
    await query.answer()
    text = (
        "🎟️ **ثبت کد تخفیف**\n\n"
        "لطفاً کد تخفیف خود را ارسال کنید:\n"
        "(برای بازگشت بدون تخفیف، روی دکمه زیر کلیک کنید)"
    )
    keyboard = [[InlineKeyboardButton("◀️ بازگشت به فاکتور", callback_data="back_to_confirm_purchase")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    return ENTERING_DISCOUNT_CODE


async def enter_discount_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بررسی و اعمال کد تخفیف"""
    code = update.message.text.strip().upper()
    plan_id = context.user_data.get("selected_plan")
    plans = get_plans()
    plan = plans.get(plan_id, {})
    original_price = plan.get("price", 0)

    res = db.use_discount_code(code)
    if not res.get("success"):
        await update.message.reply_text(
            "❌ کد تخفیف نامعتبر، منقضی شده یا ظرفیت استفاده از آن به اتمام رسیده است!\n"
            "لطفاً کد دیگری وارد کنید یا برای انصراف /cancel را بزنید:"
        )
        return ENTERING_DISCOUNT_CODE

    discount_percent = res.get("discount_percent", 0)
    discount_amount = res.get("discount_amount", 0)

    if discount_percent > 0:
        calculated_discount = int((original_price * discount_percent) / 100)
    else:
        calculated_discount = discount_amount

    final_price = max(0, original_price - calculated_discount)
    context.user_data["discount_code"] = code
    context.user_data["discount_amount"] = calculated_discount
    context.user_data["final_price"] = final_price

    price_formatted = f"{final_price:,}".replace(",", "،")
    discount_formatted = f"{calculated_discount:,}".replace(",", "،")

    is_renewal = context.user_data.get("is_renewal", False)
    title_prefix = "🔄 تمدید اشتراک" if is_renewal else "🛒 خرید اشتراک"

    text = f"""
✅ **کد تخفیف `{code}` با موفقیت اعمال شد!**

📋 **اطلاعات فاکتور ({title_prefix}):**
• پلن: **{plan.get('name', 'نامشخص')}**
• قیمت اصلی: {original_price:,} تومان
• 🎁 تخفیف: {discount_formatted} تومان
• 💰 **مبلغ قابل پرداخت نهایی: {price_formatted} تومان**

آیا مایل به ادامه فرآیند پرداخت هستید؟
"""
    keyboard = [
        [InlineKeyboardButton("💳 ادامه و پرداخت", callback_data="confirm_purchase")],
        [InlineKeyboardButton("◀️ بازگشت", callback_data="back_to_menu"), InlineKeyboardButton("❌ انصراف", callback_data="cancel")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    return CONFIRMING_PURCHASE


async def confirm_card_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تایید پرداخت کارت به کارت"""
    query = update.callback_query
    await query.answer()

    if query.data == "cancel":
        await query.edit_message_text("❌ عملیات لغو شد.")
        return CHOOSING

    if query.data != "confirm_card_payment":
        return CONFIRMING_PURCHASE

    try:
        user = update.effective_user
        plan_id = context.user_data.get("selected_plan")
        plans = get_plans()
        plan = plans.get(plan_id, {})
        tracking_code = context.user_data.get("tracking_code", "")

        is_renewal = context.user_data.get("is_renewal", False)
        renew_sub_id = context.user_data.get("renew_subscription_id")
        discount_code = context.user_data.get("discount_code")
        discount_amount = context.user_data.get("discount_amount", 0)

        original_price = plan.get("price", 0)
        final_price = max(0, original_price - discount_amount)
        price_formatted = f"{final_price:,}".replace(",", "،")

        # ذخیره تراکنش کارت به کارت
        order_id = f"card_{user.id}_{get_now_timestamp()}"
        account_name = context.user_data.get("account_name", f"tg_{user.id}")
        account_comment = context.user_data.get("account_comment")

        db.save_transaction(
            order_id=order_id,
            user_id=user.id,
            username=user.username or user.first_name,
            plan_name=plan.get("name", "نامشخص"),
            amount=final_price,
            gateway="card_to_card",
            tracking_code=tracking_code,
            status="pending",
            account_name=account_name,
            account_comment=account_comment,
            is_renewal=is_renewal,
            renew_sub_id=renew_sub_id,
            discount_code=discount_code,
        )

        logger.info(f"Transaction saved for user {user.id} (renewal={is_renewal})")
    except Exception as e:
        logger.error(f"Error saving transaction: {e}")
        try:
            await query.edit_message_text("❌ خطا در ثبت تراکنش. لطفاً دوباره تلاش کنید.")
        except:
            pass
        return CHOOSING

    # ارسال پیام به ادمین
    admin_sent = False
    if ADMIN_ID and ADMIN_ID != 0:
        try:
            type_title = "🔄 رسید تمدید اشتراک" if is_renewal else "🛒 رسید خرید اشتراک جدید"
            discount_info = f"\n🎟️ کد تخفیف: `{discount_code}` (-{discount_amount:,} تومان)" if discount_code else ""
            admin_text = (
                f"🔔 <b>{type_title}</b>\n\n"
                f"👤 کاربر: {user.first_name}\n"
                f"🆔 آیدی عددی: <code>{user.id}</code>\n"
                f"💬 یوزرنیم: @{user.username or 'ندارد'}\n\n"
                f"📋 پلن: <b>{plan.get('name', 'نامشخص')}</b>\n"
                f"💰 مبلغ پرداختی: <b>{price_formatted} تومان</b>{discount_info}\n"
                f"🔢 شماره پیگیری / فیش: <code>{tracking_code}</code>\n"
                f"📝 نام اکانت هیدیفای: <code>{account_name}</code>\n\n"
                f"⏰ زمان: {get_now_shamsi()}"
            )
            
            if is_renewal:
                approve_callback = f"admin_approve_renew_{user.id}_{plan_id}_{renew_sub_id or 0}"
                approve_button_text = "✅ تایید تمدید"
            else:
                approve_callback = f"admin_approve_{user.id}_{plan_id}"
                approve_button_text = "✅ تایید خرید"

            keyboard = [
                [InlineKeyboardButton(approve_button_text, callback_data=approve_callback)],
                [InlineKeyboardButton("❌ رد تراکنش", callback_data=f"admin_reject_{user.id}")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            receipt_photo = context.user_data.get("receipt_photo")
            if receipt_photo:
                await context.bot.send_photo(
                    chat_id=ADMIN_ID,
                    photo=receipt_photo,
                    caption=admin_text,
                    reply_markup=reply_markup,
                    parse_mode="HTML",
                )
            else:
                await context.bot.send_message(
                    chat_id=ADMIN_ID,
                    text=admin_text,
                    reply_markup=reply_markup,
                    parse_mode="HTML",
                )
            admin_sent = True
            logger.info(f"Admin notification sent to {ADMIN_ID}")
        except Exception as e:
            logger.error(f"Error sending to admin: {e}")
    else:
        logger.warning("ADMIN_ID not set, skipping admin notification")

    # پاسخ به کاربر
    try:
        await query.edit_message_text(
            f"✅ **رسید پرداخت شما با موفقیت ثبت شد!**\n\n"
            f"📋 پلن: {plan.get('name', 'نامشخص')}\n"
            f"💰 مبلغ: {price_formatted} تومان\n"
            f"🔢 پیگیری: {tracking_code}\n\n"
            f"⏳ فیش شما برای ادمین ارسال گردید و در حال بررسی است.\n"
            f"به محض تایید، اشتراک شما فعال/تمدید شده و لینک اتصال به صورت خودکار برای شما ارسال می‌شود.",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error editing user message: {e}")

    return CHOOSING


async def confirm_purchase(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تایید خرید و ارسال لینک پرداخت"""
    query = update.callback_query
    await query.answer()

    if query.data == "cancel":
        await query.edit_message_text("❌ عملیات لغو شد.")
        return CHOOSING

    if query.data != "confirm_purchase":
        return CONFIRMING_PURCHASE

    plan_id = context.user_data.get("selected_plan")
    plans = get_plans()
    if not plan_id or plan_id not in plans:
        await query.edit_message_text("❌ خطا در انتخاب پلن!")
        return CHOOSING

    plan = plans[plan_id]
    user = update.effective_user

    # ساخت درخواست پرداخت
    await query.edit_message_text("⏳ در حال ساخت درخواست پرداخت...")

    # آدرس بازگشت (وب‌سایت ربات)
    callback_url = f"https://t.me/{context.bot.username}"

    # ایجاد پرداخت
    payment = PaymentManager(PAYMENT_GATEWAY)
    payment_result = payment.create_payment(
        amount=plan["price"],
        user_id=user.id,
        plan_name=plan["name"],
        callback_url=callback_url,
    )

    if not payment_result.get("success"):
        await query.edit_message_text(
            f"❌ خطا در ساخت درخواست پرداخت:\n{payment_result.get('error', 'Unknown error')}"
        )
        return CHOOSING

    # ذخیره اطلاعات پرداخت
    order_id = payment_result.get("order_id", "")
    context.user_data["payment_order_id"] = order_id
    context.user_data["payment_amount"] = plan["price"]

    # ارسال لینک پرداخت
    pay_url = payment.get_pay_url(payment_result)
    price_formatted = f"{plan['price']:,}".replace(",", "،")

    keyboard = [
        [InlineKeyboardButton("💳 پرداخت", url=pay_url)],
        [InlineKeyboardButton("✅ پرداخت کردم", callback_data="verify_payment")],
        [InlineKeyboardButton("❌ انصراف", callback_data="cancel")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        f"💳 **درخواست پرداخت ساخته شد!**\n\n"
        f"📋 پلن: {plan['name']}\n"
        f"💰 مبلغ: {price_formatted} تومان\n\n"
        f"روی دکمه «💳 پرداخت» کلیک کنید و پرداخت رو انجام بدید.\n"
        f"بعد از پرداخت، روی «✅ پرداخت کردم» کلیک کنید.",
        reply_markup=reply_markup,
        parse_mode="Markdown",
    )
    return CONFIRMING_PURCHASE


async def show_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش وضعیت تمام اشتراک‌ها"""
    user = update.effective_user
    try:
        subscriptions = db.get_user_subscriptions(user.id)
    except Exception as e:
        logger.error(f"Error getting subscriptions: {e}")
        await update.message.reply_text("❌ خطا در دریافت اطلاعات اشتراک!")
        return CHOOSING

    if not subscriptions:
        await update.message.reply_text(
            "❌ شما هنوز اشتراکی ندارید!\n\n"
            "برای خرید اشتراک، روی «🛒 خرید اشتراک» کلیک کنید."
        )
        return CHOOSING

    text = "📊 وضعیت اشتراک‌های شما:\n\n"

    for i, sub in enumerate(subscriptions, 1):
        status = sub.get("status", "unknown")
        if status == "active":
            status_icon = "🟢 فعال"
        elif status == "expired":
            status_icon = "🔴 منقضی"
        else:
            status_icon = "⚪ لغو شده"

        plan_name = sub.get("plan_name", "نامشخص")
        data_limit = sub.get("data_limit", 0)
        data_used = sub.get("data_used", 0)
        start_date = sub.get("start_date", "نامشخص")
        expire_date = sub.get("expire_date", "نامشخص")

        # نمایش حجم با نوار پیشرفت
        if data_limit and data_limit > 0:
            remaining = round(data_limit - data_used, 2)
            usage_percent = min((data_used / data_limit) * 100, 100)
            
            # نوار پیشرفت
            bar_length = 10
            filled = int(usage_percent / 10)
            bar = "█" * filled + "░" * (bar_length - filled)
            
            # رنگ بر اساس درصد مصرف
            if usage_percent >= 90:
                status_emoji = "🔴"
            elif usage_percent >= 70:
                status_emoji = "🟡"
            else:
                status_emoji = "🟢"
            
            data_text = f"📊 حجم: {data_used} از {data_limit} گیگ\n"
            data_text += f"   {status_emoji} {bar} {usage_percent:.1f}%\n"
            data_text += f"   💾 باقیمانده: {remaining} گیگ"
        else:
            data_text = f"📊 حجم: {data_used} گیگ (نامحدود)"

        # نمایش تاریخ شروع و انقضا (شمسی)
        start_fmt = gregorian_to_shamsi(start_date) if start_date else "نامشخص"
        expire_fmt = gregorian_to_shamsi(expire_date) if expire_date else "نامشخص"
        
        # نمایش روزهای باقی‌مانده
        remaining_days = days_remaining_shamsi(expire_date)
        remaining_text = f" (باقیمانده: {remaining_days} روز)" if remaining_days is not None else ""

        account_name = sub.get("account_name") or f"tg_{user.id}"
        text += f"{i}. {plan_name} - {status_icon}\n"
        text += f"   📝 نام اکانت: {account_name}\n"
        text += f"   {data_text}\n"
        text += f"   📅 شروع: {start_fmt} | انقضا: {expire_fmt}{remaining_text}\n\n"

    try:
        await update.message.reply_text(text)
    except Exception as e:
        logger.error(f"Error sending status: {e}")
    return CHOOSING


async def get_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دریافت لینک اشتراک‌ها همراه با QR Code و دکمه‌های اتصال مستقیم"""
    user = update.effective_user
    try:
        subscriptions = db.get_user_subscriptions(user.id)
    except Exception as e:
        logger.error(f"Error getting subscriptions: {e}")
        await update.message.reply_text("❌ خطا در دریافت اطلاعات اشتراک!")
        return CHOOSING

    if not subscriptions:
        await update.message.reply_text(
            "❌ شما هنوز اشتراکی ندارید!\n\n"
            "برای خرید اشتراک، روی «🛒 خرید اشتراک» کلیک کنید."
        )
        return CHOOSING

    active_subs = [s for s in subscriptions if s.get("hidify_uuid")]
    if not active_subs:
        await update.message.reply_text("❌ اشتراک فعالی یافت نشد.")
        return CHOOSING

    for sub in active_subs:
        uuid = sub.get("hidify_uuid", "")
        plan_name = sub.get("plan_name", "نامشخص")
        status = sub.get("status", "unknown")
        account_name = sub.get("account_name") or f"tg_{user.id}"

        if sub.get("plan_id") == "test":
            proxy = USER_PROXY_PATH_TEST or USER_PROXY_PATH or HIDIFY_PROXY_PATH
            panel_url = HIDIFY_PANEL_URL_TEST or HIDIFY_PANEL_URL
        else:
            proxy = USER_PROXY_PATH or HIDIFY_PROXY_PATH
            panel_url = HIDIFY_PANEL_URL

        subscription_url = f"{panel_url.rstrip('/')}/{proxy.strip('/')}/{uuid}/"
        status_icon = "🟢 فعال" if status == "active" else "🔴 منقضی"

        details = f"📋 پلن: **{plan_name}**\n📝 اکانت: `{account_name}`\n📊 وضعیت: {status_icon}"
        await send_subscription_card(
            context.bot,
            chat_id=user.id,
            sub_url=subscription_url,
            title="🔗 **اطلاعات و لینک اتصال اشتراک:**",
            details=details
        )

    return CHOOSING


async def renew_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تمدید اشتراک - نمایش اشتراک‌های موجود"""
    user = update.effective_user
    
    # دریافت اشتراک‌های کاربر از دیتابیس
    subscriptions = db.get_user_subscriptions(user.id)
    
    if not subscriptions:
        # بررسی اطلاعات قدیمی
        user_data = get_user_data(user.id)
        if not user_data or not user_data.get("hidify_uuid"):
            await update.message.reply_text(
                "❌ شما هنوز اشتراکی ندارید!\n\n"
                "برای خرید اشتراک، روی «🛒 خرید اشتراک» کلیک کنید."
            )
            return CHOOSING
        # اگر فقط یک اشتراک قدیمی داره، مستقیم به انتخاب پلن بره
        keyboard = []
        plans = get_plans()
        for plan_id, plan in plans.items():
            price_formatted = f"{plan['price']:,}".replace(",", "،")
            keyboard.append([
                InlineKeyboardButton(
                    f"🔄 {plan['name']} - {plan['description']} - {price_formatted} تومان",
                    callback_data=f"renew_plan_{plan_id}",
                )
            ])
        keyboard.append([InlineKeyboardButton("◀️ بازگشت", callback_data="back_to_menu")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "🔄 تمدید اشتراک:\n\n"
            "پلن مورد نظر برای تمدید را انتخاب کنید:",
            reply_markup=reply_markup,
        )
        return RENEWING
    
    # اگر چند اشتراک داره، لیست اشتراک‌ها رو نشون بده (فقط غیرتست)
    keyboard = []
    for sub in subscriptions:
        # حذف اشتراک تست از لیست تمدید
        if sub.get("plan_id") == "test":
            continue
        # محاسبه وضعیت اشتراک
        status_emoji = "🟢" if sub["status"] == "active" else "🔴"
        status_text = "فعال" if sub["status"] == "active" else "منقضی"
        
        # محاسبه حجم باقیمانده
        data_limit = sub.get("data_limit", 0)
        data_used = sub.get("data_used", 0)
        if data_limit and data_limit > 0:
            data_info = f"📊 {data_limit - data_used:.1f} از {data_limit} گیگ باقیمانده"
        else:
            data_info = "📊 نامحدود"
        
        # تاریخ انقضا
        expire_date = sub.get("expire_date", "")
        if expire_date:
            try:
                expire_dt = datetime.fromisoformat(expire_date.strip().replace("Z", ""))
                if expire_dt < get_now_naive():
                    data_info = "🔴 منقضی شده"
            except:
                pass
        
        account_name = sub.get("account_name") or f"tg_{user.id}"
        button_text = f"{status_emoji} {sub['plan_name']} ({account_name})\n{data_info}"
        keyboard.append([
            InlineKeyboardButton(
                button_text,
                callback_data=f"renew_sub_{sub['id']}",
            )
        ])
    
    # اگر فقط اشتراک تست داره (یا اصلاً اشتراک غیرتست نداره)
    if not keyboard:
        await update.message.reply_text(
            "❌ شما اشتراک قابل تمدیدی ندارید!\n\n"
            "🧪 اشتراک تست قابل تمدید نیست.\n"
            "برای خرید اشتراک، روی «🛒 خرید اشتراک» کلیک کنید."
        )
        return CHOOSING

    keyboard.append([InlineKeyboardButton("◀️ بازگشت", callback_data="back_to_menu")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "🔄 تمدید اشتراک:\n\n"
        "کدام اشتراک را می‌خواهید تمدید کنید؟",
        reply_markup=reply_markup,
    )
    return RENEWING


async def handle_renew(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش درخواست تمدید و هدایت به پیش‌فاکتور و پرداخت"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "cancel":
        await query.edit_message_text("❌ عملیات لغو شد.")
        return CHOOSING
    
    # بازگشت به منوی اصلی
    if query.data == "back_to_menu":
        return await back_to_menu(update, context)
    
    # اگر اشتراک خاصی انتخاب شده (renew_sub_123)
    if query.data.startswith("renew_sub_"):
        sub_id = int(query.data.replace("renew_sub_", ""))
        context.user_data["renew_subscription_id"] = sub_id
        
        # نمایش پلن‌های تمدید
        plans = get_plans()
        keyboard = []
        for plan_id, plan in plans.items():
            price_formatted = f"{plan['price']:,}".replace(",", "،")
            keyboard.append([
                InlineKeyboardButton(
                    f"🔄 {plan['name']} - {plan['description']} - {price_formatted} تومان",
                    callback_data=f"renew_plan_{plan_id}",
                )
            ])
        keyboard.append([InlineKeyboardButton("◀️ بازگشت", callback_data="back_to_menu")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "🔄 **انتخاب پلن تمدید:**\n\n"
            "پلن مورد نظر برای تمدید را انتخاب کنید:",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        return RENEWING
    
    # اگر پلن انتخاب شده (renew_plan_123)
    if not query.data.startswith("renew_plan_"):
        return RENEWING
    
    plan_id = query.data.replace("renew_plan_", "")
    plans = get_plans()
    if plan_id not in plans:
        await query.edit_message_text("❌ پلن نامعتبر!")
        return CHOOSING
    
    plan = plans[plan_id]
    user = update.effective_user
    sub_id = context.user_data.get("renew_subscription_id")
    
    target_sub = None
    if sub_id:
        user_subscriptions = db.get_user_subscriptions(user.id)
        for s in user_subscriptions:
            if s["id"] == sub_id:
                target_sub = s
                break

    # تنظیم داده‌های تمدید در session کاربر برای مرحله پرداخت
    context.user_data["is_renewal"] = True
    context.user_data["selected_plan"] = plan_id
    context.user_data["renew_subscription_id"] = sub_id
    context.user_data["account_name"] = target_sub.get("account_name") if target_sub else f"tg_{user.id}"
    context.user_data["account_comment"] = target_sub.get("account_comment") if target_sub else None
    context.user_data.pop("discount_code", None)
    context.user_data.pop("discount_amount", None)

    price_formatted = f"{plan['price']:,}".replace(",", "،")
    data_text = f"{plan['data_limit']} گیگابایت" if plan['data_limit'] > 0 else "نامحدود"
    account_title = target_sub.get("account_name", f"tg_{user.id}") if target_sub else f"tg_{user.id}"

    text = f"""
🔄 **پیش‌فاکتور تمدید اشتراک**

👤 اکانت: `{account_title}`
📋 پلن تمدید: **{plan['name']}**
📊 حجم: **{data_text}**
⏰ مدت: **{plan['duration']} روز**
💰 مبلغ: **{price_formatted} تومان**

آیا مایل به تایید و ادامه فرآیند پرداخت هستید؟
"""
    keyboard = [
        [InlineKeyboardButton("💳 تایید و ادامه پرداخت", callback_data="confirm_purchase")],
        [InlineKeyboardButton("🎟️ ثبت کد تخفیف", callback_data="apply_discount")],
        [InlineKeyboardButton("◀️ بازگشت", callback_data="back_to_menu"), InlineKeyboardButton("❌ انصراف", callback_data="cancel")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    return CONFIRMING_PURCHASE


async def verify_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تایید پرداخت"""
    query = update.callback_query
    await query.answer()

    if query.data == "cancel":
        await query.edit_message_text("❌ عملیات لغو شد.")
        return CHOOSING

    if query.data != "verify_payment":
        return CONFIRMING_PURCHASE

    # بررسی آیا اشتراک قبلاً ساخته شده
    user = update.effective_user
    existing_data = get_user_data(user.id)
    if existing_data and existing_data.get("hidify_uuid"):
        await query.edit_message_text(
            "✅ اشتراک شما قبلاً فعال شده است!\n\n"
            "برای دریافت لینک اتصال، روی دکمه «🔗 لینک اتصال» کلیک کنید."
        )
        return CHOOSING

    await query.edit_message_text("⏳ در حال بررسی پرداخت...")

    order_id = context.user_data.get("payment_order_id", "")
    amount = context.user_data.get("payment_amount", 0)
    plan_id = context.user_data.get("selected_plan")

    if not order_id or not plan_id:
        await query.edit_message_text("❌ اطلاعات پرداخت یافت نشد!")
        return CHOOSING

    # تایید پرداخت
    payment = PaymentManager(PAYMENT_GATEWAY)
    verify_result = payment.verify_payment(
        authority=context.user_data.get("payment_authority"),
        amount=amount,
        payment_id=context.user_data.get("payment_id"),
        order_id=order_id,
    )

    if not verify_result.get("success"):
        keyboard = [
            [InlineKeyboardButton("🔄 تلاش مجدد", callback_data="confirm_purchase")],
            [InlineKeyboardButton("❌ انصراف", callback_data="cancel")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            f"❌ **پرداخت تایید نشد!**\n\n"
            f"دلیل: {verify_result.get('error', 'نامشخص')}\n\n"
            f"اگر پرداخت رو انجام دادید، دوباره تلاش کنید.",
            reply_markup=reply_markup,
            parse_mode="Markdown",
        )
        return CONFIRMING_PURCHASE

    # پرداخت موفق - ساخت اشتراک
    plans = get_plans()
    plan = plans[plan_id]
    
    # استفاده از نام انتخاب شده توسط کاربر
    username = context.user_data.get("account_name", f"tg_{user.id}")
    account_comment = context.user_data.get("account_comment")

    # نمایش پیام در حال ساخت
    try:
        await query.edit_message_text("⏳ در حال ساخت اشتراک...")
    except Exception as e:
        logger.error(f"Error editing message: {e}")

    # ساخت کاربر در Hidify
    try:
        result = await hidify.create_user(
            name=username,
            usage_limit_gb=plan["data_limit"] if plan["data_limit"] > 0 else None,
            package_days=plan["duration"],
            enable=True,
            comment=account_comment
        )
    except Exception as e:
        logger.error(f"Error creating user in Hidify: {e}")
        try:
            await query.edit_message_text(f"❌ خطا در ساخت اشتراک:\n{str(e)[:200]}")
        except:
            pass
        return CHOOSING

    if "error" in result:
        try:
            await query.edit_message_text(f"❌ خطا در ساخت اشتراک:\n{result['error'][:200]}")
        except:
            pass
        return CHOOSING

    # ذخیره اطلاعات کاربر و اشتراک
    try:
        user_uuid = result.get("uuid", "")

        # ذخیره اطلاعات کاربر
        user_data = {
            "telegram_id": user.id,
            "username": username,
            "hidify_uuid": user_uuid,
            "plan": plan_id,
            "created_at": get_now_iso(),
            "data_limit": plan["data_limit"],
        }
        save_user_data(user.id, user_data)

        # ذخیره اشتراک جدید
        db.save_subscription(
            telegram_id=user.id,
            hidify_uuid=user_uuid,
            plan_id=plan_id,
            plan_name=plan["name"],
            data_limit=plan["data_limit"],
            duration=plan["duration"],
            status="active",
            account_name=username,
            account_comment=account_comment,
        )
        logger.info(f"User data and subscription saved: {user.id} -> {user_uuid}")
    except Exception as e:
        logger.error(f"Error saving user data: {e}")
        # ادامه بده حتی اگه ذخیره نشد

    # بروزرسانی تراکنش
    try:
        db.update_transaction(
            order_id=order_id,
            status="completed",
            ref_id=verify_result.get("ref_id") or verify_result.get("track_id"),
        )
    except Exception as e:
        logger.error(f"Error updating transaction: {e}")
        # ادامه بده حتی اگه تراکنش آپدیت نشد

    # نمایش پیام موفقیت + لینک اتصال خودکار
    price_formatted = f"{plan['price']:,}".replace(",", "،")
    subscription_url = f"{HIDIFY_PANEL_URL}/{USER_PROXY_PATH}/{user_uuid}/"
    data_text = str(plan['data_limit']) if plan['data_limit'] > 0 else 'نامحدود'
    success_text = (
        f"✅ پرداخت موفق! اشتراک فعال شد!\n\n"
        f"📋 پلن: {plan['name']}\n"
        f"📊 حجم: {data_text} گیگابایت\n"
        f"⏰ مدت: {plan['duration']} روز\n"
        f"💰 قیمت: {price_formatted} تومان\n\n"
        f"🔗 لینک اتصال شما:\n"
        f"{subscription_url}\n\n"
        f"⚠️ این لینک را در اپلیکیشن VPN کپی کنید."
    )
    try:
        await query.edit_message_text(success_text)
    except Exception as e:
        logger.error(f"Error sending success message: {e}")
        try:
            await context.bot.send_message(chat_id=user.id, text=success_text)
        except:
            pass
    return CHOOSING


async def handle_test_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """اشتراک تست - فقط یکبار برای هر کاربر"""
    user = update.effective_user

    # بررسی آیا قبلاً اشتراک تست گرفته
    user_subscriptions = db.get_user_subscriptions(user.id)
    for sub in user_subscriptions:
        if sub.get("plan_id") == "test":
            existing_uuid = sub.get("hidify_uuid", "")
            if existing_uuid:
                p_url = (HIDIFY_PANEL_URL_TEST or HIDIFY_PANEL_URL).rstrip("/")
                u_path = (USER_PROXY_PATH_TEST or USER_PROXY_PATH or HIDIFY_PROXY_PATH).strip("/")
                existing_link = f"{p_url}/{u_path}/{existing_uuid}/"
                await send_subscription_card(
                    context.bot,
                    chat_id=user.id,
                    sub_url=existing_link,
                    title="⚠️ **شما قبلاً اشتراک تست دریافت کرده‌اید!**",
                    details="📋 پلن: **اشتراک تست رایگان**\n💡 برای خرید اشتراک دائمی، از منوی اصلی دکمه «🛒 خرید اشتراک» را لمس کنید."
                )
            else:
                await update.message.reply_text(
                    "⚠️ شما قبلاً اشتراک تست دریافت کرده‌اید!\n\n"
                    "برای دریافت اشتراک دائمی، «🛒 خرید اشتراک» را بزنید."
                )
            return CHOOSING

    # ایجاد اشتراک تست جدید
    status_msg = await update.message.reply_text("⏳ در حال ساخت اشتراک تست...")

    # نام اکانت = آیدی تلگرام
    username = f"tg_{user.id}"

    try:
        result = await asyncio.wait_for(
            hidify.create_user(
                name=username,
                usage_limit_gb=0.3,  # 0.3 گیگ حجم تست
                package_days=1,     # 1 روز مدت تست
                enable=True,
                comment=str(user.id),
            ),
            timeout=15.0,
        )
    except asyncio.TimeoutError:
        try:
            await status_msg.edit_text("❌ خطا: زمان اتصال به سرور تمام شد. لطفاً دوباره تلاش کنید.")
        except:
            await update.message.reply_text("❌ خطا: زمان اتصال به سرور تمام شد. لطفاً دوباره تلاش کنید.")
        return CHOOSING
    except Exception as e:
        logger.error(f"Error creating test user: {e}")
        try:
            await status_msg.edit_text(f"❌ خطا در ساخت اشتراک تست:\n{str(e)[:200]}")
        except:
            await update.message.reply_text(f"❌ خطا در ساخت اشتراک تست:\n{str(e)[:200]}")
        return CHOOSING

    if "error" in result:
        try:
            await status_msg.edit_text(f"❌ خطا در ساخت اشتراک تست:\n{result['error'][:200]}")
        except:
            await update.message.reply_text(f"❌ خطا در ساخت اشتراک تست:\n{result['error'][:200]}")
        return CHOOSING

    # ذخیره در دیتابیس
    user_uuid = result.get("uuid", "")
    db.save_subscription(
        telegram_id=user.id,
        hidify_uuid=user_uuid,
        plan_id="test",
        plan_name="اشتراک تست",
        data_limit=0.3,
        duration=1,
        status="active",
        account_name=username,
        account_comment=str(user.id),
    )

    # ذخیره اطلاعات کاربر
    save_user_data(user.id, {
        "telegram_id": user.id,
        "username": username,
        "hidify_uuid": user_uuid,
        "plan": "test",
        "created_at": get_now_iso(),
        "data_limit": 0.3,
    })

    # پاک کردن یا ویرایش پیام موقت در حال ساخت
    try:
        await status_msg.delete()
    except Exception:
        pass

    # ارسال کارت تست همراه با QR Code و دکمه‌های اتصال
    p_url = (HIDIFY_PANEL_URL_TEST or HIDIFY_PANEL_URL).rstrip("/")
    u_path = (USER_PROXY_PATH_TEST or USER_PROXY_PATH or HIDIFY_PROXY_PATH).strip("/")
    test_link = f"{p_url}/{u_path}/{user_uuid}/"
    details = "📋 پلن: **اشتراک تست رایگان**\n📊 حجم: **0.3 گیگابایت**\n⏰ مدت: **1 روز**"
    await send_subscription_card(
        context.bot,
        chat_id=user.id,
        sub_url=test_link,
        title="✅ **اشتراک تست شما با موفقیت ساخته شد!**",
        details=details
    )
    return CHOOSING


# ═══════════════════════════════════════════════════════════════════════
# سیستم کیف پول
# ═══════════════════════════════════════════════════════════════════════

async def show_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش کیف پول"""
    user = update.effective_user
    wallet = db.get_wallet(user.id)
    balance = wallet.get("balance", 0)
    
    text = f"""
💰 <b>کیف پول شما</b>

موجودی: {balance:,} تومان

💡 برای شارژ کیف پول، با پشتیبانی تماس بگیرید.
"""
    
    keyboard = [
        [InlineKeyboardButton("◀️ بازگشت", callback_data="back_to_menu")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        if update.callback_query:
            await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")
        else:
            await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Error showing wallet: {e}")
    return CHOOSING


# ═══════════════════════════════════════════════════════════════════════
# سیستم پشتیبانی
# ═══════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════
# سیستم زیرمجموعه‌گیری و رفرال
# ═══════════════════════════════════════════════════════════════════════

async def referral_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """منوی زیرمجموعه‌گیری و کسب درآمد"""
    user = update.effective_user
    bot_info = await context.bot.get_me()
    bot_username = bot_info.username

    ref_link = f"https://t.me/{bot_username}?start=ref_{user.id}"
    stats = db.get_referral_stats(user.id)
    wallet = db.get_wallet(user.id)
    balance = wallet.get("balance", 0)

    text = f"""
👥 <b>سیستم کسب درآمد و دعوت از دوستان</b>

با معرفی ربات به دوستان خود، به ازای هر خرید موفق آن‌ها <b>۱۰,۰۰۰ تومان</b> پاداش نقدی در کیف پول دریافت کنید!

🔗 <b>لینک دعوت اختصاصی شما:</b>
<code>{ref_link}</code>

📊 <b>آمار دعوت‌های شما:</b>
• 👥 کل افراد دعوت شده: <b>{stats['total_invites']}</b> نفر
• ✅ خریدهای موفق ثبت شده: <b>{stats['rewarded_invites']}</b> نفر
• 💰 مجموع پاداش کسب شده: <b>{stats['total_reward']:,}</b> تومان
• 💳 موجودی فعلی کیف پول: <b>{balance:,}</b> تومان

💡 موجودی کیف پول در خریدها و تمدیدهای بعدی شما قابل استفاده است.
"""
    keyboard = [
        [InlineKeyboardButton("📤 اشتراک‌گذاری لینک دعوت", url=f"https://t.me/share/url?url={ref_link}&text=خرید فیلترشکن پرسرعت و بدون قطعی")],
        [InlineKeyboardButton("◀️ بازگشت", callback_data="back_to_menu")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")
    return CHOOSING


# ═══════════════════════════════════════════════════════════════════════
# سیستم پشتیبانی و تیکتینگ
# ═══════════════════════════════════════════════════════════════════════

async def support_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """منوی پشتیبانی و تیکت"""
    text = """
💬 <b>مرکز پشتیبانی و ارتباط با مدیریت</b>

در صورتی که سوال، مشکل در اتصال، نیاز به کانفیگ اختصاصی یا راهنمایی دارید، می‌توانید از گزینه‌های زیر استفاده کنید:
"""
    keyboard = [
        [InlineKeyboardButton("✍️ ارسال پیام به پشتیبانی", callback_data="ticket_new")],
        [InlineKeyboardButton("📋 تیکت‌های قبلی من", callback_data="ticket_list")],
        [InlineKeyboardButton("◀️ بازگشت", callback_data="back_to_menu")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")
    return CHOOSING


async def ticket_new_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """درخواست ثبت متن تیکت"""
    query = update.callback_query
    await query.answer()
    context.user_data["is_waiting_ticket"] = True
    text = (
        "📝 **ارسال پیام به پشتیبانی**\n\n"
        "لطفاً پیام، سوال یا عکس مشکل خود را ارسال کنید:\n"
        "(پیام شما مستقیماً برای تیم پشتیبانی ارسال خواهد شد)"
    )
    keyboard = [[InlineKeyboardButton("◀️ بازگشت", callback_data="back_to_menu")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    return ENTERING_TICKET_MESSAGE


async def enter_ticket_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دریافت پیام تیکت از کاربر و ارسال به ادمین"""
    context.user_data.pop("is_waiting_ticket", None)
    user = update.effective_user
    msg_text = update.message.text or update.message.caption or "ارسال عکس بدون متن"

    res = db.create_ticket(user.id, subject="پیام کاربر", message=msg_text)
    ticket_id = res.get("ticket_id", 0)

    # اطلاع به کاربر
    await update.message.reply_text(
        f"✅ پیام شما با شماره تیکت <b>#{ticket_id}</b> با موفقیت برای پشتیبانی ارسال شد.\n"
        f"به محض بررسی و پاسخ ادمین، از طریق همین ربات مطلع خواهید شد.",
        parse_mode="HTML"
    )

    # ارسال به ادمین با دکمه پاسخ
    if ADMIN_ID and ADMIN_ID != 0:
        admin_text = (
            f"📨 <b>تیکت پشتیبانی جدید (#{ticket_id})</b>\n\n"
            f"👤 کاربر: {user.first_name}\n"
            f"🆔 آیدی عددی: <code>{user.id}</code>\n"
            f"💬 یوزرنیم: @{user.username or 'ندارد'}\n\n"
            f"📝 متن پیام:\n{msg_text}\n\n"
            f"⏰ زمان: {get_now_shamsi()}"
        )
        keyboard = [
            [InlineKeyboardButton("✍️ پاسخ به این تیکت", callback_data=f"admin_reply_ticket_{ticket_id}")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        if update.message.photo:
            photo_id = update.message.photo[-1].file_id
            await context.bot.send_photo(
                chat_id=ADMIN_ID,
                photo=photo_id,
                caption=admin_text,
                reply_markup=reply_markup,
                parse_mode="HTML"
            )
        else:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=admin_text,
                reply_markup=reply_markup,
                parse_mode="HTML"
            )

    return CHOOSING


async def ticket_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش لیست تیکت‌های کاربر"""
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    tickets = db.get_user_tickets(user.id)

    if not tickets:
        await query.edit_message_text(
            "📋 شما تا کنون تیکتی ثبت نکرده‌اید.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ بازگشت", callback_data="back_to_menu")]])
        )
        return CHOOSING

    text = "📋 <b>تاریخچه تیکت‌های شما:</b>\n\n"
    for t in tickets[:5]:
        status_badge = "🟢 پاسخ داده شده" if t.get("status") == "replied" else ("🟡 در حال بررسی" if t.get("status") == "open" else "⚪ بسته شده")
        text += f"🎫 <b>تیکت #{t['id']}</b> ({status_badge})\n"
        text += f"📝 پیام شما: {t.get('message', '')[:60]}...\n"
        if t.get("admin_reply"):
            text += f"💬 <b>پاسخ ادمین:</b> {t.get('admin_reply')}\n"
        text += "──────────────\n"

    keyboard = [
        [InlineKeyboardButton("✍️ ثبت تیکت جدید", callback_data="ticket_new")],
        [InlineKeyboardButton("◀️ بازگشت", callback_data="back_to_menu")],
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
    return CHOOSING


async def admin_reply_ticket_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """شروع پاسخ به تیکت توسط ادمین"""
    query = update.callback_query
    await query.answer()
    if update.effective_user.id != ADMIN_ID:
        await query.answer("❌ شما ادمین نیستید!", show_alert=True)
        return

    ticket_id = int(query.data.replace("admin_reply_ticket_", ""))
    context.user_data["replying_ticket_id"] = ticket_id

    await query.message.reply_text(
        f"✍️ لطفاً متن پاسخ خود برای تیکت <b>#{ticket_id}</b> را ارسال کنید:\n"
        f"(برای انصراف /cancel را بزنید)",
        parse_mode="HTML"
    )
    return ADMIN_REPLYING_TICKET


async def admin_send_ticket_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ارسال پاسخ ادمین به کاربر"""
    ticket_id = context.user_data.pop("replying_ticket_id", None)
    reply_text = update.message.text

    if not ticket_id or not reply_text:
        await update.message.reply_text("❌ تیکت معتبر یافت نشد.")
        return CHOOSING

    ticket = db.get_ticket(ticket_id)
    if not ticket:
        await update.message.reply_text("❌ تیکت یافت نشد.")
        return CHOOSING

    db.reply_ticket(ticket_id, reply_text)

    user_id = ticket["telegram_id"]
    try:
        user_msg = (
            f"🔔 <b>پاسخ پشتیبانی به تیکت #{ticket_id}:</b>\n\n"
            f"{reply_text}\n\n"
            f"──────────────\n"
            f"در صورت نیاز به پیام مجدد، از دکمه «💬 پشتیبانی» استفاده کنید."
        )
        await context.bot.send_message(chat_id=user_id, text=user_msg, parse_mode="HTML")
        await update.message.reply_text(f"✅ پاسخ با موفقیت برای کاربر {user_id} ارسال شد.")
    except Exception as e:
        logger.error(f"Error sending ticket reply to user {user_id}: {e}")
        await update.message.reply_text(f"⚠️ پاسخ در دیتابیس ثبت شد اما ارسال به تلگرام کاربر با خطا مواجه شد: {e}")

    return CHOOSING


# ─── دستورات ادمین برای کدهای تخفیف ───

async def admin_add_discount_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دستور ساخت کد تخفیف توسط ادمین: /add_discount CODE PERCENT [MAX_USES]"""
    if update.effective_user.id != ADMIN_ID:
        return
    args = context.args
    if not args or len(args) < 2:
        await update.message.reply_text(
            "📝 نحوه استفاده:\n"
            "`/add_discount [کد] [درصد] [حداکثر تعداد]`\n\n"
            "مثال برای ۲۰٪ تخفیف برای ۵۰ نفر:\n"
            "`/add_discount NOROOZ 20 50`",
            parse_mode="Markdown"
        )
        return
    code = args[0].strip().upper()
    try:
        percent = int(args[1])
    except ValueError:
        await update.message.reply_text("❌ درصد تخفیف باید عدد باشد!")
        return

    max_uses = int(args[2]) if len(args) > 2 and args[2].isdigit() else 0
    res = db.create_discount_code(code=code, discount_percent=percent, max_uses=max_uses)
    if res.get("success"):
        await update.message.reply_text(f"✅ کد تخفیف `{code}` با {percent}٪ تخفیف ساخته شد!", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"❌ خطا: {res.get('error')}")


async def admin_discounts_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """لیست کدهای تخفیف فعال: /discounts"""
    if update.effective_user.id != ADMIN_ID:
        return
    codes = db.get_all_discount_codes()
    if not codes:
        await update.message.reply_text("هیچ کد تخفیفی در دیتابیس وجود ندارد.")
        return
    text = "🎟️ **لیست کدهای تخفیف:**\n\n"
    for c in codes:
        status = "🟢 فعال" if c.get("is_active") else "🔴 غیرفعال"
        text += f"• `{c['code']}` | {c['discount_percent']}% تخفیف | استفاده: {c['used_count']}/{c['max_uses'] or 'نامحدود'} | {status}\n"
    await update.message.reply_text(text, parse_mode="Markdown")


# ═══════════════════════════════════════════════════════════════════════
# دستورات ادمین جدید
# ═══════════════════════════════════════════════════════════════════════

async def admin_block_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بلاک کردن کاربر توسط ادمین"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ شما ادمین نیستید!")
        return
    
    try:
        # دریافت آیدی کاربر از پیام
        args = context.args
        if not args:
            await update.message.reply_text(
                "📝 نحوه استفاده:\n"
                "/block [آیدی کاربر] [دلیل]\n\n"
                "مثال:\n"
                "/block 123456789 تخلف"
            )
            return
        
        target_id = int(args[0])
        reason = " ".join(args[1:]) if len(args) > 1 else "بدون دلیل"
        
        result = db.block_user(target_id, reason, ADMIN_ID)
        
        if result.get("success"):
            await update.message.reply_text(
                f"✅ کاربر {target_id} بلاک شد!\n"
                f"📝 دلیل: {reason}"
            )
        else:
            await update.message.reply_text("❌ خطا در بلاک کردن کاربر!")
    except Exception as e:
        await update.message.reply_text(f"❌ خطا: {str(e)}")


async def admin_unblock_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """آنبلاک کردن کاربر توسط ادمین"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ شما ادمین نیستید!")
        return
    
    try:
        args = context.args
        if not args:
            await update.message.reply_text(
                "📝 نحوه استفاده:\n"
                "/unblock [آیدی کاربر]\n\n"
                "مثال:\n"
                "/unblock 123456789"
            )
            return
        
        target_id = int(args[0])
        result = db.unblock_user(target_id)
        
        if result.get("success"):
            await update.message.reply_text(f"✅ کاربر {target_id} آنبلاک شد!")
        else:
            await update.message.reply_text("❌ خطا در آنبلاک کردن کاربر!")
    except Exception as e:
        await update.message.reply_text(f"❌ خطا: {str(e)}")


async def admin_list_blocked(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """لیست کاربران بلاک شده"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ شما ادمین نیستید!")
        return
    
    blocked = db.get_blocked_users()
    
    if not blocked:
        await update.message.reply_text("✅ هیچ کاربری بلاک نشده است.")
        return
    
    text = "🚫 لیست کاربران بلاک شده:\n\n"
    for i, user in enumerate(blocked, 1):
        text += f"{i}. آیدی: {user.get('telegram_id')}\n"
        text += f"   📝 دلیل: {user.get('reason', 'بدون دلیل')}\n"
        text += f"   📅 تاریخ: {user.get('created_at', 'نامشخص')}\n\n"
    
    await update.message.reply_text(text)


async def admin_create_discount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ایجاد کد تخفیف"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ شما ادمین نیستید!")
        return
    
    try:
        args = context.args
        if len(args) < 2:
            await update.message.reply_text(
                "📝 نحوه استفاده:\n"
                "/discount [کد] [درصد تخفیف] [حداکثر استفاده]\n\n"
                "مثال:\n"
                "/discount OFF50 50 10\n"
                "(کد OFF50 با ۵۰٪ تخفیف، حداکثر ۱۰ بار)"
            )
            return
        
        code = args[0].upper()
        discount_percent = int(args[1])
        max_uses = int(args[2]) if len(args) > 2 else 0
        
        result = db.create_discount_code(code, discount_percent=discount_percent, max_uses=max_uses)
        
        if result.get("success"):
            await update.message.reply_text(
                f"✅ کد تخفیف ایجاد شد!\n\n"
                f"🎟 کد: {code}\n"
                f"💰 تخفیف: {discount_percent}%\n"
                f"📊 حداکثر استفاده: {max_uses if max_uses > 0 else 'نامحدود'}"
            )
        else:
            await update.message.reply_text(f"❌ خطا: {result.get('error', 'خطای ناشناخته')}")
    except Exception as e:
        await update.message.reply_text(f"❌ خطا: {str(e)}")


async def admin_list_discounts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """لیست کدهای تخفیف"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ شما ادمین نیستید!")
        return
    
    codes = db.get_all_discount_codes()
    
    if not codes:
        await update.message.reply_text("❌ هیچ کد تخفیفی وجود ندارد.")
        return
    
    text = "🎟 لیست کدهای تخفیف:\n\n"
    for i, code in enumerate(codes, 1):
        status = "🟢 فعال" if code.get("is_active") else "🔴 غیرفعال"
        text += f"{i}. {code.get('code')} - {status}\n"
        text += f"   💰 تخفیف: {code.get('discount_percent', 0)}%\n"
        text += f"   📊 استفاده: {code.get('used_count', 0)}/{code.get('max_uses', 0) if code.get('max_uses', 0) > 0 else '∞'}\n\n"
    
    await update.message.reply_text(text)


async def admin_delete_discount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """حذف کد تخفیف"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ شما ادمین نیستید!")
        return
    
    try:
        args = context.args
        if not args:
            await update.message.reply_text(
                "📝 نحوه استفاده:\n"
                "/delete_discount [کد]\n\n"
                "مثال:\n"
                "/delete_discount OFF50"
            )
            return
        
        code = args[0].upper()
        result = db.delete_discount_code(code)
        
        if result.get("success"):
            await update.message.reply_text(f"✅ کد تخفیف {code} حذف شد!")
        else:
            await update.message.reply_text("❌ خطا در حذف کد تخفیف!")
    except Exception as e:
        await update.message.reply_text(f"❌ خطا: {str(e)}")


async def admin_wallet_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش موجودی کیف پول کاربران"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ شما ادمین نیستید!")
        return
    
    wallets = db.get_all_wallets()
    
    if not wallets:
        await update.message.reply_text("💰 هیچ کیف پولی وجود ندارد.")
        return
    
    text = "💰 موجودی کیف پول کاربران:\n\n"
    total = 0
    for wallet in wallets:
        balance = wallet.get("balance", 0)
        total += balance
        text += f"• آیدی {wallet.get('telegram_id')}: {balance:,} تومان\n"
    
    text += f"\n💰 جمع کل: {total:,} تومان"
    await update.message.reply_text(text)


async def admin_add_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """افزودن موجودی به کیف پول"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ شما ادمین نیستید!")
        return
    
    try:
        args = context.args
        if len(args) < 2:
            await update.message.reply_text(
                "📝 نحوه استفاده:\n"
                "/add_wallet [آیدی کاربر] [مبلغ]\n\n"
                "مثال:\n"
                "/add_wallet 123456789 50000"
            )
            return
        
        target_id = int(args[0])
        amount = int(args[1])
        
        result = db.update_wallet(target_id, amount)
        
        if result.get("success"):
            await update.message.reply_text(
                f"✅ {amount:,} تومان به کیف پول کاربر {target_id} اضافه شد!\n"
                f"💰 موجودی جدید: {result.get('balance', 0):,} تومان"
            )
        else:
            await update.message.reply_text("❌ خطا در افزودن موجودی!")
    except Exception as e:
        await update.message.reply_text(f"❌ خطا: {str(e)}")


async def admin_tickets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """لیست تیکت‌های پشتیبانی"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ شما ادمین نیستید!")
        return
    
    tickets = db.get_all_tickets(status="open")
    
    if not tickets:
        await update.message.reply_text("✅ هیچ تیکت بازی وجود ندارد.")
        return
    
    text = "🎫 تیکت‌های باز:\n\n"
    for ticket in tickets:
        text += f"🎫 #{ticket.get('id')}\n"
        text += f"👤 کاربر: {ticket.get('telegram_id')}\n"
        text += f"📝 موضوع: {ticket.get('subject')}\n"
        text += f"💬 پیام: {ticket.get('message')[:100]}...\n"
        text += f"📅 تاریخ: {ticket.get('created_at')}\n\n"
    
    await update.message.reply_text(text)


async def admin_reply_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پاسخ به تیکت"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ شما ادمین نیستید!")
        return
    
    try:
        args = context.args
        if len(args) < 2:
            await update.message.reply_text(
                "📝 نحوه استفاده:\n"
                "/reply_ticket [شماره تیکت] [پاسخ]\n\n"
                "مثال:\n"
                "/reply_ticket 1 سلام، مشکل شما حل شد."
            )
            return
        
        ticket_id = int(args[0])
        reply_text = " ".join(args[1:])
        
        result = db.reply_ticket(ticket_id, reply_text)
        
        if result.get("success"):
            # دریافت اطلاعات تیکت
            tickets = db.get_all_tickets()
            ticket = next((t for t in tickets if t.get("id") == ticket_id), None)
            
            if ticket:
                # ارسال پاسخ به کاربر
                try:
                    user_text = f"""
💬 <b>پاسخ پشتیبانی</b>

🎫 شماره تیکت: {ticket_id}
📝 موضوع: {ticket.get('subject')}

💬 پاسخ:\n{reply_text}
"""
                    await context.bot.send_message(
                        chat_id=ticket.get("telegram_id"),
                        text=user_text,
                        parse_mode="HTML"
                    )
                except Exception as e:
                    logger.error(f"Error sending reply to user: {e}")
            
            await update.message.reply_text(f"✅ پاسخ به تیکت #{ticket_id} ارسال شد!")
        else:
            await update.message.reply_text("❌ خطا در ارسال پاسخ!")
    except Exception as e:
        await update.message.reply_text(f"❌ خطا: {str(e)}")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش پیام‌های متنی"""
    user = update.effective_user
    text = update.message.text
    
    # بررسی عضویت در کانال‌ها (به جز ادمین)
    if REQUIRED_CHANNELS and user.id != ADMIN_ID:
        is_member = await check_channel_membership(user.id, context)
        if not is_member:
            await show_join_channels_message(update, context)
            return CHOOSING

    # اولویت به دکمه‌های منوی اصلی
    if text == "🛒 خرید اشتراک":
        return await show_plans(update, context)
    elif text == "🔄 تمدید اشتراک":
        return await renew_subscription(update, context)
    elif text == "📊 وضعیت اشتراک":
        return await show_status(update, context)
    elif text == "🔗 لینک اتصال":
        return await get_link(update, context)
    elif text == "💰 کیف پول":
        return await show_wallet(update, context)
    elif text == "👥 زیرمجموعه‌گیری":
        return await referral_menu(update, context)
    elif text == "💬 پشتیبانی":
        return await support_menu(update, context)
    elif text == "❓ راهنمای ربات":
        return await help_command(update, context)
    elif text == "🧪 اشتراک تست":
        return await handle_test_subscription(update, context)
    elif text == "📚 آموزش‌ها (بزودی)":
        await update.message.reply_text("⏳ این بخش بزودی اضافه خواهد شد!")
        return CHOOSING
    elif text == "🔧 پنل مدیریت" and update.effective_user.id == ADMIN_ID:
        return await admin_panel(update, context)
    
    # اگر کاربر در حال ارسال پیام پشتیبانی است
    if context.user_data.get("is_waiting_ticket"):
        return await enter_ticket_message(update, context)

    # اگر ادمین در حال پاسخ به تیکت است
    if context.user_data.get("replying_ticket_id") and user.id == ADMIN_ID:
        return await admin_send_ticket_reply(update, context)

    # پیام نامشخص
    await update.message.reply_text(
        "لطفاً از منوی زیر یکی از گزینه‌ها را انتخاب کنید:"
    )
    return CHOOSING


async def copy_link_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """کپی لینک"""
    query = update.callback_query
    await query.answer("لینک کپی شد! ✅", show_alert=True)


# ═══════════════════════════════════════════════════════════════════════
# هندلرهای ادمین
# ═══════════════════════════════════════════════════════════════════════

async def admin_approve_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تایید پرداخت توسط ادمین"""
    query = update.callback_query
    await query.answer()

    # بررسی ادمین بودن
    if update.effective_user.id != ADMIN_ID:
        await query.answer("❌ شما ادمین نیستید!", show_alert=True)
        return

    data = query.data.replace("admin_approve_", "")
    parts = data.split("_")
    if len(parts) < 2:
        await query.edit_message_text("❌ داده نامعتبر!")
        return

    user_id = int(parts[0])
    plan_id = parts[1]

    plans = get_plans()
    plan = plans.get(plan_id, {})
    
    # دریافت اطلاعات تراکنش برای نام اکانت
    user_transactions = db.get_user_transactions(user_id)
    latest_transaction = user_transactions[0] if user_transactions else None
    
    if latest_transaction and latest_transaction.get("account_name"):
        username = latest_transaction["account_name"]
        account_comment = latest_transaction.get("account_comment")
    else:
        username = f"tg_{user_id}"
        account_comment = None

    # ساخت اشتراک در Hidify
    try:
        result = await hidify.create_user(
            name=username,
            usage_limit_gb=plan.get("data_limit") if plan.get("data_limit", 0) > 0 else None,
            package_days=plan.get("duration", 30),
            enable=True,
            comment=account_comment
        )
    except Exception as e:
        logger.error(f"Error creating user: {e}")
        await query.edit_message_text(f"❌ خطا در ساخت اشتراک:\n{str(e)[:200]}")
        return

    if "error" in result:
        await query.edit_message_text(f"❌ خطا در ساخت اشتراک:\n{result['error'][:200]}")
        return

    # ذخیره اطلاعات کاربر و اشتراک
    try:
        user_uuid = result.get("uuid", "")
        user_data = {
            "telegram_id": user_id,
            "username": username,
            "hidify_uuid": user_uuid,
            "plan": plan_id,
            "created_at": get_now_iso(),
            "data_limit": plan.get("data_limit", 0),
        }
        save_user_data(user_id, user_data)

        # ذخیره اشتراک جدید در دیتابیس
        db.save_subscription(
            telegram_id=user_id,
            hidify_uuid=user_uuid,
            plan_id=plan_id,
            plan_name=plan.get("name", "نامشخص"),
            data_limit=plan.get("data_limit", 0),
            duration=plan.get("duration", 30),
            status="active",
            account_name=username,
            account_comment=account_comment,
        )
    except Exception as e:
        logger.error(f"Error saving user data: {e}")

    # بروزرسانی تراکنش
    try:
        # پیدا کردن تراکنش در انتظار کاربر
        pending = db.get_pending_transactions()
        for trans in pending:
            if trans.get("user_id") == user_id:
                db.update_transaction(trans["order_id"], "completed")
                break
    except Exception as e:
        logger.error(f"Error updating transaction: {e}")

    # پاداش رفرال به معرف در صورت وجود
    ref_res = db.complete_referral(user_id)
    if ref_res.get("success"):
        ref_id = ref_res["referrer_id"]
        try:
            await context.bot.send_message(
                chat_id=ref_id,
                text="🎁 **تبریک!** کاربر معرفی شده توسط شما خرید انجام داد و مبلغ ۱۰,۰۰۰ تومان به کیف پول شما واریز شد!",
                parse_mode="Markdown"
            )
        except Exception:
            pass

    # پیام به ادمین
    price_formatted = f"{plan.get('price', 0):,}".replace(",", "،")
    await query.edit_message_text(
        f"✅ **اشتراک جدید فعال شد!**\n\n"
        f"👤 کاربر: `{user_id}`\n"
        f"📋 پلن: {plan.get('name', 'نامشخص')}\n"
        f"📊 حجم: {plan.get('data_limit', 0) if plan.get('data_limit', 0) > 0 else 'نامحدود'} گیگ\n"
        f"💰 مبلغ: {price_formatted} تومان",
        parse_mode="Markdown",
    )

    # پیام به کاربر + ارسال کارت اشتراک و QR Code
    plan_data_limit = plan.get('data_limit', 0)
    plan_duration = plan.get('duration', 30)
    data_text = str(plan_data_limit) if plan_data_limit > 0 else 'نامحدود'
    subscription_url = f"{HIDIFY_PANEL_URL}/{USER_PROXY_PATH}/{user_uuid}/"

    details = (
        f"✅ پرداخت تایید شد و اشتراک شما با موفقیت فعال گردید!\n\n"
        f"📋 پلن: **{plan.get('name', 'نامشخص')}**\n"
        f"📊 حجم: **{data_text} گیگابایت**\n"
        f"⏰ مدت: **{plan_duration} روز**"
    )
    await send_subscription_card(
        context.bot,
        chat_id=user_id,
        sub_url=subscription_url,
        title="🎉 **اشتراک جدید شما آماده اتصال است!**",
        details=details
    )


async def admin_approve_renew(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تایید تمدید اشتراک توسط ادمین"""
    query = update.callback_query
    await query.answer()

    if update.effective_user.id != ADMIN_ID:
        await query.answer("❌ شما ادمین نیستید!", show_alert=True)
        return

    data = query.data.replace("admin_approve_renew_", "")
    parts = data.split("_")
    if len(parts) < 3:
        await query.edit_message_text("❌ داده نامعتبر!")
        return

    user_id = int(parts[0])
    plan_id = parts[1]
    sub_id = int(parts[2])

    plans = get_plans()
    plan = plans.get(plan_id, {})
    if not plan:
        await query.edit_message_text("❌ پلن مورد نظر یافت نشد!")
        return

    user_subscriptions = db.get_user_subscriptions(user_id)
    target_sub = next((s for s in user_subscriptions if s["id"] == sub_id), None)
    
    user_uuid = ""
    if target_sub:
        user_uuid = target_sub.get("hidify_uuid", "")
    else:
        user_data = get_user_data(user_id)
        if user_data:
            user_uuid = user_data.get("hidify_uuid", "")

    if not user_uuid:
        await query.edit_message_text("❌ UUID اشتراک یافت نشد!")
        return

    now_ts = get_now_timestamp()
    is_exp = False
    old_data_limit = target_sub.get("data_limit", 0) or 0 if target_sub else 0
    old_data_used = target_sub.get("data_used", 0) or 0 if target_sub else 0
    old_duration = target_sub.get("duration", 0) or 0 if target_sub else 0
    old_expire_ts = 0

    if target_sub:
        expire_date = target_sub.get("expire_date", "")
        if expire_date:
            try:
                expire_dt = datetime.fromisoformat(expire_date.strip().replace("Z", ""))
                old_expire_ts = int(expire_dt.timestamp())
                if expire_dt < get_now_naive():
                    is_exp = True
            except Exception:
                is_exp = True
        else:
            is_exp = True

        if old_data_limit > 0 and old_data_used >= old_data_limit:
            is_exp = True
    else:
        is_exp = True

    if is_exp:
        new_data_limit = plan["data_limit"] if plan["data_limit"] > 0 else None
        new_duration = plan["duration"]
        new_data_used = 0
        new_start_date = get_now_naive().strftime("%Y-%m-%d")
        new_expire_date = (get_now_naive() + timedelta(days=plan["duration"])).isoformat()
        renewal_type = "replace"
    else:
        new_data_limit = (old_data_limit + plan["data_limit"]) if plan["data_limit"] > 0 else None
        new_duration = old_duration + plan["duration"]
        new_data_used = old_data_used
        new_start_date = None
        if old_expire_ts > now_ts:
            new_expire_ts = old_expire_ts + (plan["duration"] * 86400)
        else:
            new_expire_ts = now_ts + (plan["duration"] * 86400)
        new_expire_date = datetime.fromtimestamp(new_expire_ts).isoformat()
        renewal_type = "extend"

    # بروزرسانی در Hiddify
    update_payload = {}
    if new_data_limit is not None:
        update_payload["usage_limit_GB"] = new_data_limit
    update_payload["package_days"] = new_duration
    if renewal_type == "replace":
        update_payload["current_usage_GB"] = 0
        update_payload["start_date"] = new_start_date

    try:
        res = await hidify.update_user(user_uuid, **update_payload)
        if "error" in res:
            logger.warning(f"Hidify update user error: {res['error']}")
    except Exception as e:
        logger.error(f"Error updating user in hidify: {e}")

    # بروزرسانی اشتراک در دیتابیس
    if sub_id and target_sub:
        update_fields = {
            "plan_id": plan_id,
            "plan_name": plan["name"],
            "data_limit": new_data_limit if new_data_limit else 0,
            "data_used": new_data_used,
            "duration": new_duration,
            "expire_date": new_expire_date,
            "status": "active",
        }
        if renewal_type == "replace":
            update_fields["start_date"] = new_start_date
        db.update_subscription(sub_id, **update_fields)
    else:
        db.save_subscription(
            telegram_id=user_id,
            hidify_uuid=user_uuid,
            plan_id=plan_id,
            plan_name=plan["name"],
            data_limit=new_data_limit if new_data_limit else 0,
            duration=new_duration,
            data_used=new_data_used,
            status="active",
            account_name=target_sub.get("account_name") if target_sub else f"tg_{user_id}",
            account_comment=target_sub.get("account_comment") if target_sub else None,
        )

    # بروزرسانی وضعیت تراکنش
    try:
        pending = db.get_pending_transactions()
        for trans in pending:
            if trans.get("user_id") == user_id:
                db.update_transaction(trans["order_id"], "completed")
                break
    except Exception as e:
        logger.error(f"Error updating transaction: {e}")

    # پاداش رفرال به معرف در صورت وجود
    ref_res = db.complete_referral(user_id)
    if ref_res.get("success"):
        ref_id = ref_res["referrer_id"]
        try:
            await context.bot.send_message(
                chat_id=ref_id,
                text="🎁 **تبریک!** کاربر معرفی شده توسط شما خرید/تمدید انجام داد و مبلغ ۱۰,۰۰۰ تومان به کیف پول شما واریز شد!",
                parse_mode="Markdown"
            )
        except Exception:
            pass

    # پیام به ادمین
    price_formatted = f"{plan.get('price', 0):,}".replace(",", "،")
    renew_type_fa = "جایگزین (ریست)" if renewal_type == "replace" else "افزایش حجم و مدت"
    await query.edit_message_text(
        f"✅ **تمدید اشتراک با موفقیت تایید شد!**\n\n"
        f"👤 کاربر: `{user_id}`\n"
        f"📋 پلن: {plan.get('name', 'نامشخص')}\n"
        f"💰 مبلغ: {price_formatted} تومان\n"
        f"🔄 نحوه تمدید: {renew_type_fa}",
        parse_mode="Markdown",
    )

    # پیام و کارت اشتراک به کاربر
    subscription_url = f"{HIDIFY_PANEL_URL}/{USER_PROXY_PATH}/{user_uuid}/"
    details = (
        f"✅ اشتراک شما با موفقیت تمدید شد!\n\n"
        f"📋 پلن: **{plan.get('name', 'نامشخص')}**\n"
        f"📊 حجم جدید: **{new_data_limit if new_data_limit else 'نامحدود'} گیگابایت**\n"
        f"⏰ مدت کل: **{new_duration} روز**"
    )
    await send_subscription_card(
        context.bot,
        chat_id=user_id,
        sub_url=subscription_url,
        title="🎉 **تمدید اشتراک شما انجام شد!**",
        details=details
    )


async def admin_reject_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """رد پرداخت توسط ادمین"""
    query = update.callback_query
    await query.answer()

    # بررسی ادمین بودن
    if update.effective_user.id != ADMIN_ID:
        await query.answer("❌ شما ادمین نیستید!", show_alert=True)
        return

    data = query.data.replace("admin_reject_", "")
    user_id = int(data)

    # بروزرسانی تراکنش
    try:
        # پیدا کردن تراکنش در انتظار کاربر
        pending = db.get_pending_transactions()
        for trans in pending:
            if trans.get("user_id") == user_id:
                db.update_transaction(trans["order_id"], "rejected")
                break
    except Exception as e:
        logger.error(f"Error updating transaction: {e}")

    # پیام به ادمین
    await query.edit_message_text(
        f"❌ **پرداخت رد شد**\n\n"
        f"👤 کاربر: `{user_id}`",
        parse_mode="Markdown",
    )

    # پیام به کاربر
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text="❌ **پرداخت شما تایید نشد!**\n\n"
                 "لطفاً با پشتیبانی تماس بگیرید.",
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.error(f"Error sending message to user: {e}")


async def admin_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تست اتصال ادمین"""
    user = update.effective_user

    if user.id != ADMIN_ID:
        await update.message.reply_text("❌ شما ادمین نیستید!")
        return

    await update.message.reply_text(
        f"✅ **اتصال ادمین فعال است!**\n\n"
        f"🆔 آیدی عددی شما: `{user.id}`\n"
        f"👤 نام: {user.first_name}\n"
        f"💬 یوزرنیم: @{user.username or 'ندارد'}\n\n"
        f"از این به بعد رسیدهای پرداخت کارت به کارت به اینجا ارسال میشود.",
        parse_mode="Markdown",
    )


async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پنل مدیریت ادمین"""
    user = update.effective_user

    if user.id != ADMIN_ID:
        await update.message.reply_text("❌ شما ادمین نیستید!")
        return

    text = """
🔧 **پنل مدیریت**

از منوی زیر می‌توانید تنظیمات ربات را مدیریت کنید:
"""

    keyboard = [
        [InlineKeyboardButton("💳 مدیریت کارت‌ها", callback_data="admin_cards")],
        [InlineKeyboardButton("📦 مدیریت پلن‌ها", callback_data="admin_plans")],
        [InlineKeyboardButton("📊 آمار ربات", callback_data="admin_stats_btn")],
        [InlineKeyboardButton("🔒 پشتیبان‌گیری", callback_data="admin_backup")],
        [InlineKeyboardButton("🔄 بازیابی پشتیبان", callback_data="admin_restore")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_back")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    return ADMIN_MENU


async def admin_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش منوی ادمین"""
    query = update.callback_query
    await query.answer()

    if query.data == "admin_back":
        await query.edit_message_text("❌ پنل مدیریت بسته شد.")
        return ConversationHandler.END

    if query.data == "admin_cards":
        return await show_cards_menu(update, context)

    if query.data == "admin_plans":
        return await show_plans_menu(update, context)

    if query.data == "admin_stats_btn":
        return await admin_stats(update, context)

    if query.data == "admin_backup":
        return await admin_backup_handler(update, context)

    if query.data == "admin_restore":
        return await admin_restore_handler(update, context)

    return ADMIN_MENU


# ═══════════════════════════════════════════════════════════════════════
# مدیریت کارت‌ها
# ═══════════════════════════════════════════════════════════════════════

async def show_cards_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش منوی مدیریت کارت‌ها"""
    query = update.callback_query
    await query.answer()

    cards = get_all_cards()

    if not cards:
        text = "💳 **مدیریت کارت‌ها**\n\n⚠️ هنوز کارتی اضافه نشده است.\n\nکارت جدید اضافه کنید:"
    else:
        text = "💳 **مدیریت کارت‌ها**\n\n"
        for card_id, card in cards.items():
            status = "🟢" if card.get("is_active") else "🔴"
            text += f"{status} `{card_id}`\n"
            text += f"  📌 {card['card_number']}\n"
            text += f"  👤 {card['card_holder']}\n"
            text += f"  🏦 {card['bank_name']}\n\n"

    keyboard = [
        [InlineKeyboardButton("➕ افزودن کارت", callback_data="add_card")],
    ]

    # اضافه کردن دکمه‌های مدیریت برای هر کارت
    for card_id in cards:
        keyboard.append([
            InlineKeyboardButton(f"✏️ ویرایش {card_id}", callback_data=f"edit_card_{card_id}"),
            InlineKeyboardButton(f"🗑 حذف {card_id}", callback_data=f"del_card_{card_id}"),
        ])

    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="admin_back_menu")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    return ADMIN_CARDS_MENU


async def cards_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش منوی کارت‌ها"""
    query = update.callback_query
    await query.answer()

    if query.data == "admin_back_menu":
        # بازگشت به پنل اصلی
        text = """
🔧 **پنل مدیریت**

از منوی زیر می‌توانید تنظیمات ربات را مدیریت کنید:
"""
        keyboard = [
            [InlineKeyboardButton("💳 مدیریت کارت‌ها", callback_data="admin_cards")],
            [InlineKeyboardButton("📦 مدیریت پلن‌ها", callback_data="admin_plans")],
            [InlineKeyboardButton("📊 آمار ربات", callback_data="admin_stats_btn")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_back")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
        return ADMIN_MENU

    if query.data == "add_card":
        await query.edit_message_text(
            "💳 **افزودن کارت جدید**\n\n"
            "شماره کارت (بدون خط تیره) را وارد کنید:\n"
            "مثال: `6104337912345678`"
        )
        return ADMIN_ADD_CARD_NUMBER

    if query.data.startswith("edit_card_"):
        card_id = query.data.replace("edit_card_", "")
        cards = get_all_cards()
        if card_id in cards:
            card = cards[card_id]
            text = f"""
✏️ **ویرایش کارت** `{card_id}`

📌 شماره: {card['card_number']}
👤 نام: {card['card_holder']}
🏦 بانک: {card['bank_name']}
{'🟢 فعال' if card.get('is_active') else '🔴 غیرفعال'}
"""
            keyboard = [
                [InlineKeyboardButton("🔄 تغییر وضعیت", callback_data=f"toggle_card_{card_id}")],
                [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_cards")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
        return ADMIN_CARDS_MENU

    if query.data.startswith("toggle_card_"):
        card_id = query.data.replace("toggle_card_", "")
        cards = get_all_cards()
        if card_id in cards:
            current_status = cards[card_id].get("is_active", False)
            update_card(card_id, is_active=not current_status)
            status = "فعال" if not current_status else "غیرفعال"
            await query.answer(f"کارت {status} شد!", show_alert=True)
        return await show_cards_menu(update, context)

    if query.data.startswith("del_card_"):
        card_id = query.data.replace("del_card_", "")
        result = delete_card(card_id)
        if result.get("success"):
            await query.answer("کارت حذف شد!", show_alert=True)
        else:
            await query.answer(f"خطا: {result.get('error')}", show_alert=True)
        return await show_cards_menu(update, context)

    return ADMIN_CARDS_MENU


async def add_card_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دریافت شماره کارت"""
    card_number = update.message.text.strip().replace("-", "")

    # بررسی شماره کارت
    if not card_number.isdigit() or len(card_number) < 16:
        await update.message.reply_text(
            "❌ شماره کارت نامعتبر است!\n\n"
            "لطفاً شماره ۱۶ رقمی کارت را وارد کنید:"
        )
        return ADMIN_ADD_CARD_NUMBER

    context.user_data["new_card_number"] = card_number
    await update.message.reply_text(
        "👤 **نام صاحب کارت را وارد کنید:**\n\n"
        "مثال: `علی رضایی`"
    )
    return ADMIN_ADD_CARD_HOLDER


async def add_card_holder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دریافت نام صاحب کارت"""
    card_holder = update.message.text.strip()

    if len(card_holder) < 3:
        await update.message.reply_text(
            "❌ نام نامعتبر است!\n\n"
            "لطفاً نام کامل صاحب کارت را وارد کنید:"
        )
        return ADMIN_ADD_CARD_HOLDER

    context.user_data["new_card_holder"] = card_holder
    await update.message.reply_text(
        "🏦 **نام بانک را وارد کنید:**\n\n"
        "مثال: `بانک ملت`\n"
        "یا: `سپه`، `صادرات`، `تجارت`، `ملی` و ..."
    )
    return ADMIN_ADD_CARD_BANK


async def add_card_bank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دریافت نام بانک"""
    bank_name = update.message.text.strip()

    card_number = context.user_data.get("new_card_number", "")
    card_holder = context.user_data.get("new_card_holder", "")

    # افزودن کارت
    result = add_card(card_number, card_holder, bank_name)

    if result.get("success"):
        await update.message.reply_text(
            f"✅ **کارت با موفقیت اضافه شد!**\n\n"
            f"📌 شماره: `{card_number}`\n"
            f"👤 نام: {card_holder}\n"
            f"🏦 بانک: {bank_name}\n\n"
            f"برای مدیریت کارت‌ها، از دستور /admin_panel استفاده کنید.",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text(
            f"❌ خطا در افزودن کارت:\n{result.get('error', 'نامشخص')}"
        )

    # پاک کردن اطلاعات موقت
    context.user_data.pop("new_card_number", None)
    context.user_data.pop("new_card_holder", None)

    return ConversationHandler.END


# ═══════════════════════════════════════════════════════════════════════
# مدیریت پلن‌ها
# ═══════════════════════════════════════════════════════════════════════

async def show_plans_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش منوی مدیریت پلن‌ها"""
    query = update.callback_query
    await query.answer()

    plans = get_all_plans()

    if not plans:
        text = "📦 **مدیریت پلن‌ها**\n\n⚠️ هنوز پلنی اضافه نشده است.\n\nپلن جدید اضافه کنید:"
    else:
        text = "📦 **مدیریت پلن‌ها**\n\n"
        for plan_id, plan in plans.items():
            status = "🟢" if plan.get("is_active") else "🔴"
            price_formatted = f"{plan['price']:,}".replace(",", "،")
            text += f"{status} `{plan_id}`\n"
            text += f"  📋 {plan['name']}\n"
            text += f"  💰 {price_formatted} تومان\n"
            text += f"  📊 {plan.get('description', '')}\n\n"

    keyboard = [
        [InlineKeyboardButton("➕ افزودن پلن", callback_data="add_plan")],
    ]

    # اضافه کردن دکمه‌های مدیریت برای هر پلن
    for plan_id in plans:
        keyboard.append([
            InlineKeyboardButton(f"✏️ ویرایش {plan_id}", callback_data=f"edit_plan_{plan_id}"),
            InlineKeyboardButton(f"🗑 حذف {plan_id}", callback_data=f"del_plan_{plan_id}"),
        ])

    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="admin_back_menu")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    return ADMIN_PLANS_MENU


async def plans_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش منوی پلن‌ها"""
    query = update.callback_query
    await query.answer()

    if query.data == "admin_back_menu":
        # بازگشت به پنل اصلی
        text = """
🔧 **پنل مدیریت**

از منوی زیر می‌توانید تنظیمات ربات را مدیریت کنید:
"""
        keyboard = [
            [InlineKeyboardButton("💳 مدیریت کارت‌ها", callback_data="admin_cards")],
            [InlineKeyboardButton("📦 مدیریت پلن‌ها", callback_data="admin_plans")],
            [InlineKeyboardButton("📊 آمار ربات", callback_data="admin_stats_btn")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_back")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
        return ADMIN_MENU

    if query.data == "add_plan":
        await query.edit_message_text(
            "📦 **افزودن پلن جدید**\n\n"
            "نام پلن را وارد کنید:\n"
            "مثال: ` Platinum `، ` VIP `، ` ویژه `"
        )
        return ADMIN_ADD_PLAN_NAME

    if query.data.startswith("edit_plan_"):
        plan_id = query.data.replace("edit_plan_", "")
        plans = get_all_plans()
        if plan_id in plans:
            plan = plans[plan_id]
            price_formatted = f"{plan['price']:,}".replace(",", "،")
            text = f"""
✏️ **ویرایش پلن** `{plan_id}`

📋 نام: {plan['name']}
💰 قیمت: {price_formatted} تومان
📊 حجم: {plan.get('data_limit', 0) if plan.get('data_limit', 0) > 0 else 'نامحدود'} گیگ
⏰ مدت: {plan.get('duration', 30)} روز
{'🟢 فعال' if plan.get('is_active') else '🔴 غیرفعال'}
"""
            keyboard = [
                [InlineKeyboardButton("🔄 تغییر وضعیت", callback_data=f"toggle_plan_{plan_id}")],
                [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_plans")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
        return ADMIN_PLANS_MENU

    if query.data.startswith("toggle_plan_"):
        plan_id = query.data.replace("toggle_plan_", "")
        plans = get_all_plans()
        if plan_id in plans:
            current_status = plans[plan_id].get("is_active", False)
            update_plan(plan_id, is_active=not current_status)
            status = "فعال" if not current_status else "غیرفعال"
            await query.answer(f"پلن {status} شد!", show_alert=True)
        return await show_plans_menu(update, context)

    if query.data.startswith("del_plan_"):
        plan_id = query.data.replace("del_plan_", "")
        result = delete_plan(plan_id)
        if result.get("success"):
            await query.answer("پلن حذف شد!", show_alert=True)
        else:
            await query.answer(f"خطا: {result.get('error')}", show_alert=True)
        return await show_plans_menu(update, context)

    return ADMIN_PLANS_MENU


async def add_plan_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دریافت نام پلن"""
    plan_name = update.message.text.strip()

    if len(plan_name) < 2:
        await update.message.reply_text(
            "❌ نام پلن نامعتبر است!\n\n"
            "لطفاً نام پلن را وارد کنید:"
        )
        return ADMIN_ADD_PLAN_NAME

    context.user_data["new_plan_name"] = plan_name
    await update.message.reply_text(
        "💰 **قیمت پلن (به تومان) را وارد کنید:**\n\n"
        "مثال: `50000`\n"
        "برای پلن رایگان، عدد `0` وارد کنید."
    )
    return ADMIN_ADD_PLAN_PRICE


async def add_plan_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دریافت قیمت پلن"""
    price_text = update.message.text.strip()

    try:
        price = int(price_text)
        if price < 0:
            raise ValueError()
    except:
        await update.message.reply_text(
            "❌ قیمت نامعتبر است!\n\n"
            "لطفاً عدد صحیح وارد کنید:"
        )
        return ADMIN_ADD_PLAN_PRICE

    context.user_data["new_plan_price"] = price
    await update.message.reply_text(
        "📊 **حجم پلن (به گیگابایت) را وارد کنید:**\n\n"
        "مثال: `30`\n"
        "برای پلن نامحدود، عدد `0` وارد کنید."
    )
    return ADMIN_ADD_PLAN_DATA


async def add_plan_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دریافت حجم پلن"""
    data_text = update.message.text.strip()

    try:
        data_limit = int(data_text)
        if data_limit < 0:
            raise ValueError()
    except:
        await update.message.reply_text(
            "❌ حجم نامعتبر است!\n\n"
            "لطفاً عدد صحیح وارد کنید:"
        )
        return ADMIN_ADD_PLAN_DATA

    context.user_data["new_plan_data"] = data_limit
    await update.message.reply_text(
        "⏰ **مدت پلن (به روز) را وارد کنید:**\n\n"
        "مثال: `30` (برای یک ماه)\n"
        "یا: `365` (برای یک سال)"
    )
    return ADMIN_ADD_PLAN_DURATION


async def add_plan_duration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دریافت مدت پلن"""
    duration_text = update.message.text.strip()

    try:
        duration = int(duration_text)
        if duration < 1:
            raise ValueError()
    except:
        await update.message.reply_text(
            "❌ مدت نامعتبر است!\n\n"
            "لطفاً عدد صحیح وارد کنید:"
        )
        return ADMIN_ADD_PLAN_DURATION

    plan_name = context.user_data.get("new_plan_name", "")
    price = context.user_data.get("new_plan_price", 0)
    data_limit = context.user_data.get("new_plan_data", 0)

    # افزودن پلن
    result = add_plan(plan_name, price, data_limit, duration)

    if result.get("success"):
        price_formatted = f"{price:,}".replace(",", "،")
        data_text = f"{data_limit} گیگ" if data_limit > 0 else "نامحدود"
        await update.message.reply_text(
            f"✅ **پلن با موفقیت اضافه شد!**\n\n"
            f"📋 نام: {plan_name}\n"
            f"💰 قیمت: {price_formatted} تومان\n"
            f"📊 حجم: {data_text}\n"
            f"⏰ مدت: {duration} روز\n\n"
            f"برای مدیریت پلن‌ها، از دستور /admin_panel استفاده کنید.",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text(
            f"❌ خطا در افزودن پلن:\n{result.get('error', 'نامشخص')}"
        )

    # پاک کردن اطلاعات موقت
    context.user_data.pop("new_plan_name", None)
    context.user_data.pop("new_plan_price", None)
    context.user_data.pop("new_plan_data", None)

    return ConversationHandler.END


async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """آمار ربات برای ادمین"""
    user = update.effective_user

    if user.id != ADMIN_ID:
        if update.callback_query:
            await update.callback_query.answer("❌ شما ادمین نیستید!", show_alert=True)
        else:
            await update.message.reply_text("❌ شما ادمین نیستید!")
        return

    # دریافت آمار از دیتابیس
    stats = db.get_stats()
    total_users = stats.get("total_users", 0)
    pending = stats.get("pending_transactions", 0)
    completed = stats.get("completed_transactions", 0)
    rejected = stats.get("rejected_transactions", 0)
    total_revenue = stats.get("total_revenue", 0)
    total_backups = stats.get("total_backups", 0)

    # دریافت اطلاعات Hidify
    try:
        users = await hidify.get_users()
        hidify_users = len(users) if isinstance(users, list) else 0
    except:
        hidify_users = 0

    # دریافت اطلاعات پلن‌ها و کارت‌ها
    try:
        plans = get_all_plans()
        active_plans = len([p for p in plans.values() if p.get("is_active")])
        cards = get_all_cards()
        active_cards = len([c for c in cards.values() if c.get("is_active")])
    except:
        active_plans = active_cards = 0

    revenue_formatted = f"{total_revenue:,}".replace(",", "،")
    text = f"""
📊 **آمار ربات**

👥 **کاربران ربات:** {total_users}
🌐 **کاربران Hidify:** {hidify_users}

📦 **پلن‌ها:** {active_plans} فعال
💳 **کارت‌ها:** {active_cards} فعال

💰 **تراکنش‌ها:**
• ⏳ در انتظار: {pending}
• ✅ تایید شده: {completed}
• ❌ رد شده: {rejected}

💵 **درآمد کل:** {revenue_formatted} تومان

🔒 **پشتیبان‌ها:** {total_backups} عدد
"""

    # ارسال پاسخ (چه از دکمه چه از دستور)
    if update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, parse_mode="Markdown")


# ═══════════════════════════════════════════════════════════════════════
# پشتیبان‌گیری و بازیابی از پنل مدیریت
# ═══════════════════════════════════════════════════════════════════════

async def admin_backup_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پشتیبان‌گیری از پنل مدیریت"""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("⏳ در حال ایجاد پشتیبان...")

    backup_mgr = BackupManager()
    result = backup_mgr.create_backup()

    if result.get("success"):
        backup_size = result["size"]
        backup_file = result["filename"]

        # ارسال فایل پشتیبان
        with open(result["file"], "rb") as f:
            await context.bot.send_document(
                chat_id=update.effective_user.id,
                document=f,
                caption=f"🔒 پشتیبان موفق!\n\n"
                        f"📁 فایل: {backup_file}\n"
                        f"📊 حجم: {backup_size:,} بایت\n"
                        f"📅 تاریخ: {get_now_shamsi()}\n\n"
                        f"برای بازیابی، فایل را ذخیره کرده و از منوی مدیریت گزینه بازیابی پشتیبان را انتخاب کنید.",
            )

        # نمایش پنل مدیریت دوباره
        keyboard = [
            [InlineKeyboardButton("💳 مدیریت کارت‌ها", callback_data="admin_cards")],
            [InlineKeyboardButton("📦 مدیریت پلن‌ها", callback_data="admin_plans")],
            [InlineKeyboardButton("📊 آمار ربات", callback_data="admin_stats_btn")],
            [InlineKeyboardButton("🔒 پشتیبان‌گیری", callback_data="admin_backup")],
            [InlineKeyboardButton("🔄 بازیابی پشتیبان", callback_data="admin_restore")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_back")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await context.bot.send_message(
            chat_id=update.effective_user.id,
            text="✅ پشتیبان با موفقیت ایجاد و ارسال شد!\n\n🔧 پنل مدیریت",
            reply_markup=reply_markup,
        )
    else:
        await context.bot.send_message(
            chat_id=update.effective_user.id,
            text=f"❌ خطا در ایجاد پشتیبان:\n{result.get('error', 'نامشخص')}\n\n🔧 پنل مدیریت",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_back_menu")],
            ]),
        )

    return ADMIN_MENU


# وضعیت برای بازیابی پشتیبان
ADMIN_RESTORE_FILE = 90


async def admin_restore_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """درخواست بازیابی پشتیبان"""
    query = update.callback_query
    await query.answer()

    text = (
        "🔄 بازیابی پشتیبان\n\n"
        "⚠️ نکته مهم:\n"
        "• فایل پشتیبان (.db) را ارسال کنید\n"
        "• اطلاعات فعلی بازنویسی خواهد شد\n"
        "• یک پشتیبان از وضعیت فعلی ایجاد میشود\n\n"
        "📎 فایل پشتیبان را ارسال کنید:"
    )

    keyboard = [
        [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_back_menu")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup)
    return ADMIN_RESTORE_FILE


async def handle_restore_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش فایل پشتیبان ارسال شده"""
    user = update.effective_user

    if user.id != ADMIN_ID:
        await update.message.reply_text("❌ شما ادمین نیستید!")
        return ConversationHandler.END

    document = update.message.document
    if not document:
        await update.message.reply_text("❌ لطفاً فایل پشتیبان (.db) را ارسال کنید.")
        return ADMIN_RESTORE_FILE

    # بررسی پسوند فایل
    if not document.file_name.endswith('.db'):
        await update.message.reply_text(
            "❌ فایل نامعتبر است!\n\n"
            "فقط فایل‌های با پسوند .db پذیرفته میشوند."
        )
        return ADMIN_RESTORE_FILE

    await update.message.reply_text("⏳ در حال بازیابی پشتیبان...")

    try:
        # دانلود فایل
        file = await document.get_file()
        backup_path = Path("backups") / f"restore_{get_now_naive().strftime('%Y%m%d_%H%M%S')}.db"
        backup_path.parent.mkdir(exist_ok=True)
        await file.download_to_drive(str(backup_path))

        # بازیابی
        backup_mgr = BackupManager()
        result = backup_mgr.restore_backup(str(backup_path))

        if result.get("success"):
            await update.message.reply_text(
                f"✅ بازیابی موفق!\n\n"
                f"📁 فایل بازیابی شده: {document.file_name}\n"
                f"💾 پشتیبان قبلی: {result.get('pre_restore_backup', 'نامشخص')}\n\n"
                f"🔄 ربات با تنظیمات جدید شروع به کار کرد."
            )
        else:
            await update.message.reply_text(
                f"❌ خطا در بازیابی:\n{result.get('error', 'نامشخص')}"
            )

    except Exception as e:
        logger.error(f"Error restoring backup: {e}")
        await update.message.reply_text(
            f"❌ خطا در پردازش فایل:\n{str(e)}"
        )

    # بازگشت به پنل مدیریت
    keyboard = [
        [InlineKeyboardButton("💳 مدیریت کارت‌ها", callback_data="admin_cards")],
        [InlineKeyboardButton("📦 مدیریت پلن‌ها", callback_data="admin_plans")],
        [InlineKeyboardButton("📊 آمار ربات", callback_data="admin_stats_btn")],
        [InlineKeyboardButton("🔒 پشتیبان‌گیری", callback_data="admin_backup")],
        [InlineKeyboardButton("🔄 بازیابی پشتیبان", callback_data="admin_restore")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_back")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "🔧 پنل مدیریت",
        reply_markup=reply_markup,
    )
    return ADMIN_MENU


# ═══════════════════════════════════════════════════════════════════════
# دستورات پشتیبان‌گیری
# ═══════════════════════════════════════════════════════════════════════

async def backup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دستور پشتیبان‌گیری دستی"""
    user = update.effective_user

    if user.id != ADMIN_ID:
        await update.message.reply_text("❌ شما ادمین نیستید!")
        return

    await update.message.reply_text("⏳ در حال ایجاد پشتیبان...")

    backup_mgr = BackupManager()
    result = backup_mgr.create_backup()

    if result.get("success"):
        backup_size = result["size"]
        backup_file = result["filename"]

        # ارسال فایل پشتیبان
        with open(result["file"], "rb") as f:
            await context.bot.send_document(
                chat_id=user.id,
                document=f,
                caption=f"🔒 **پشتیبان موفق!**\n\n"
                        f"📁 فایل: {backup_file}\n"
                        f"📊 حجم: {backup_size:,} بایت\n"
                        f"📅 تاریخ: {get_now_shamsi()}\n\n"
                        f"برای بازیابی، فایل را ذخیره کرده و دستور /restore استفاده کنید.",
                parse_mode="Markdown",
            )
    else:
        await update.message.reply_text(
            f"❌ خطا در ایجاد پشتیبان:\n{result.get('error', 'نامشخص')}"
        )


async def backups_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """لیست پشتیبان‌ها"""
    user = update.effective_user

    if user.id != ADMIN_ID:
        await update.message.reply_text("❌ شما ادمین نیستید!")
        return

    backup_mgr = BackupManager()
    backups = backup_mgr.list_backups()

    if not backups:
        await update.message.reply_text("📋 هنوز پشتیبانی ایجاد نشده است.")
        return

    text = "📋 **لیست پشتیبان‌ها:**\n\n"
    for i, backup in enumerate(backups[:10], 1):
        size = backup["size"]
        created = backup["created"][:19]
        text += f"{i}. 📁 {backup['filename']}\n"
        text += f"   📊 {size:,} بایت\n"
        text += f"   📅 {created}\n\n"

    await update.message.reply_text(text, parse_mode="Markdown")


async def migrate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مهاجرت از JSON به دیتابیس"""
    user = update.effective_user

    if user.id != ADMIN_ID:
        await update.message.reply_text("❌ شما ادمین نیستید!")
        return

    await update.message.reply_text("⏳ در حال مهاجرت اطلاعات...")

    result = db.migrate_from_json()

    if result.get("success"):
        migrated = result.get("migrated", 0)
        await update.message.reply_text(
            f"✅ **مهاجرت با موفقیت انجام شد!**\n\n"
            f"📊 تعداد رکوردهای مهاجرت شده: {migrated}\n\n"
            f"اطلاعات شما اکنون در دیتابیس ذخیره شده و دیگر پاک نمیشود.",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text(
            f"❌ خطا در مهاجرت:\n{result.get('error', 'نامشخص')}"
        )


async def export_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """خروجی گرفتن از دیتابیس"""
    user = update.effective_user

    if user.id != ADMIN_ID:
        await update.message.reply_text("❌ شما ادمین نیستید!")
        return

    await update.message.reply_text("⏳ در حال خروجی گرفتن از دیتابیس...")

    result = db.export_to_json()

    if result.get("success"):
        export_dir = result.get("export_dir", "data/export")
        users = result.get("users", 0)
        transactions = result.get("transactions", 0)
        subscriptions = result.get("subscriptions", 0)

        await update.message.reply_text(
            f"✅ **خروجی با موفقیت ایجاد شد!**\n\n"
            f"📁 مسیر: `{export_dir}`\n\n"
            f"📊 آمار:\n"
            f"• 👥 کاربران: {users}\n"
            f"• 💰 تراکنش‌ها: {transactions}\n"
            f"• 📋 اشتراک‌ها: {subscriptions}\n\n"
            f"⚠️ فایل‌های JSON در پوشه `data/export` ذخیره شدند.\n"
            f"این فایل‌ها را در جای امنی نگه دارید.",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text(
            f"❌ خطا در خروجی گرفتن:\n{result.get('error', 'نامشخص')}"
        )


async def import_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ورودی گرفتن به دیتابیس"""
    user = update.effective_user

    if user.id != ADMIN_ID:
        await update.message.reply_text("❌ شما ادمین نیستید!")
        return

    await update.message.reply_text("⏳ در حال ورودی گرفتن از فایل‌ها...")

    result = db.import_from_json()

    if result.get("success"):
        imported = result.get("imported", 0)
        await update.message.reply_text(
            f"✅ **ورودی با موفقیت انجام شد!**\n\n"
            f"📊 تعداد رکوردهای وارد شده: {imported}\n\n"
            f"اطلاعات با موفقیت به دیتابیس اضافه شد.",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text(
            f"❌ خطا در ورودی گرفتن:\n{result.get('error', 'نامشخص')}"
        )


# ═══════════════════════════════════════════════════════════════════════
# اجرای ربات
# ═══════════════════════════════════════════════════════════════════════

# بررسی متغیرهای محیطی
def check_env_variables():
    """بررسی متغیرهای محیطی ضروری"""
    missing = []
    if not BOT_TOKEN:
        missing.append("BOT_TOKEN")
    if not HIDIFY_PANEL_URL:
        missing.append("HIDIFY_PANEL_URL")
    if not HIDIFY_API_KEY:
        missing.append("HIDIFY_API_KEY")
    if not HIDIFY_PROXY_PATH:
        missing.append("HIDIFY_PROXY_PATH")
    
    if missing:
        logger.error(f"Missing environment variables: {', '.join(missing)}")
        return False
    return True


def main():
    """راه‌اندازی ربات"""
    # بررسی متغیرهای محیطی
    if not check_env_variables():
        logger.error("Bot cannot start due to missing environment variables!")
        print("ERROR: Missing environment variables. Check .env file.")
        return
    
    # بازیابی خودکار دیتابیس
    restore_result = db.auto_restore()
    if restore_result.get("restored"):
        logger.info(f"Database restored: {restore_result}")
    else:
        logger.info(f"Auto-restore skipped: {restore_result.get('reason', 'unknown')}")
    
    # مهاجرت ستون‌های جدید برای دیتابیس‌های قدیمی
    db.migrate_add_columns()
    
    if not ADMIN_ID or ADMIN_ID == 0:
        logger.warning("ADMIN_ID is not set! Admin features will not work.")
    
    # ساخت Application
    application = Application.builder().token(BOT_TOKEN).build()

    # هندلرهای دکمه‌های منوی اصلی (Keyboard)
    main_menu_handlers = [
        MessageHandler(filters.Regex("^🛒 خرید اشتراک$"), show_plans),
        MessageHandler(filters.Regex("^🔄 تمدید اشتراک$"), renew_subscription),
        MessageHandler(filters.Regex("^📊 وضعیت اشتراک$"), show_status),
        MessageHandler(filters.Regex("^🔗 لینک اتصال$"), get_link),
        MessageHandler(filters.Regex("^💰 کیف پول$"), show_wallet),
        MessageHandler(filters.Regex("^👥 زیرمجموعه‌گیری$"), referral_menu),
        MessageHandler(filters.Regex("^💬 پشتیبانی$"), support_menu),
        MessageHandler(filters.Regex("^🧪 اشتراک تست$"), handle_test_subscription),
        MessageHandler(filters.Regex("^❓ راهنمای ربات$"), help_command),
        MessageHandler(filters.Regex(r"^📚 آموزش\u200cها \(بزودی\)$"), help_command),
        MessageHandler(filters.Regex("^🔧 پنل مدیریت$"), admin_panel),
    ]

    # Conversation Handler برای فرآیند خرید، تمدید، پشتیبانی و پنل ادمین
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CommandHandler("admin_panel", admin_panel),
            CommandHandler("renew", renew_subscription),
            CommandHandler("status", show_status),
            CommandHandler("link", get_link),
            CommandHandler("wallet", show_wallet),
            CallbackQueryHandler(ticket_new_prompt, pattern="^ticket_new$"),
            CallbackQueryHandler(ticket_list, pattern="^ticket_list$"),
            CallbackQueryHandler(handle_renew, pattern="^renew_"),
            CallbackQueryHandler(back_to_menu, pattern="^back_to_menu$"),
            CallbackQueryHandler(admin_reply_ticket_callback, pattern="^admin_reply_ticket_"),
        ] + main_menu_handlers,
        states={
            CHOOSING: [
                CallbackQueryHandler(ticket_new_prompt, pattern="^ticket_new$"),
                CallbackQueryHandler(ticket_list, pattern="^ticket_list$"),
                CallbackQueryHandler(handle_renew, pattern="^renew_"),
                CallbackQueryHandler(back_to_menu, pattern="^back_to_menu$"),
                CallbackQueryHandler(admin_reply_ticket_callback, pattern="^admin_reply_ticket_"),
                CallbackQueryHandler(copy_link_callback, pattern="^copy_link$"),
            ] + main_menu_handlers,
            SELECTING_PLAN: [
                CallbackQueryHandler(plan_selected, pattern="^plan_"),
                CallbackQueryHandler(back_to_menu, pattern="^back_to_menu$"),
                CallbackQueryHandler(cancel, pattern="^cancel$"),
            ] + main_menu_handlers,
            SELECTING_NAME_TYPE: [
                CallbackQueryHandler(select_name_type, pattern="^(name_telegram_id|name_custom|back_to_select_plan|cancel)$"),
                CallbackQueryHandler(back_to_menu, pattern="^back_to_menu$"),
            ] + main_menu_handlers,
            ENTERING_CUSTOM_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, enter_custom_name),
                CallbackQueryHandler(back_to_name_selection, pattern="^back_to_name_selection$"),
                CallbackQueryHandler(back_to_menu, pattern="^back_to_menu$"),
                CallbackQueryHandler(cancel, pattern="^cancel$"),
            ] + main_menu_handlers,
            CONFIRMING_PURCHASE: [
                CallbackQueryHandler(apply_discount_prompt, pattern="^apply_discount$"),
                CallbackQueryHandler(select_payment_method, pattern="^(confirm_purchase|cancel)$"),
                CallbackQueryHandler(verify_payment_callback, pattern="^(verify_payment|cancel)$"),
                CallbackQueryHandler(confirm_card_payment, pattern="^(confirm_card_payment|cancel)$"),
                CallbackQueryHandler(back_to_menu, pattern="^back_to_menu$"),
                CallbackQueryHandler(back_to_select_plan, pattern="^back_to_select_plan$"),
                CallbackQueryHandler(back_to_name_selection, pattern="^back_to_name_selection$"),
                CallbackQueryHandler(back_to_enter_tracking, pattern="^back_to_enter_tracking$"),
            ] + main_menu_handlers,
            ENTERING_DISCOUNT_CODE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, enter_discount_code),
                CallbackQueryHandler(back_to_confirm_purchase, pattern="^back_to_confirm_purchase$"),
                CallbackQueryHandler(back_to_menu, pattern="^back_to_menu$"),
                CallbackQueryHandler(cancel, pattern="^cancel$"),
            ] + main_menu_handlers,
            SELECTING_PAYMENT: [
                CallbackQueryHandler(handle_payment_method, pattern="^(pay_card|pay_online|coming_soon|back_to_confirm_purchase|cancel)$"),
                CallbackQueryHandler(back_to_confirm_purchase, pattern="^back_to_confirm_purchase$"),
                CallbackQueryHandler(back_to_menu, pattern="^back_to_menu$"),
                CallbackQueryHandler(cancel, pattern="^cancel$"),
            ] + main_menu_handlers,
            ENTERING_TRACKING_CODE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, enter_tracking_code),
                MessageHandler(filters.PHOTO, enter_tracking_photo),
                CallbackQueryHandler(confirm_card_payment, pattern="^(confirm_card_payment|cancel)$"),
                CallbackQueryHandler(back_to_select_payment, pattern="^back_to_select_payment$"),
                CallbackQueryHandler(back_to_enter_tracking, pattern="^back_to_enter_tracking$"),
                CallbackQueryHandler(back_to_menu, pattern="^back_to_menu$"),
                CallbackQueryHandler(cancel, pattern="^cancel$"),
            ] + main_menu_handlers,
            RENEWING: [
                CallbackQueryHandler(handle_renew, pattern="^renew_"),
                CallbackQueryHandler(back_to_menu, pattern="^back_to_menu$"),
                CallbackQueryHandler(cancel, pattern="^cancel$"),
            ] + main_menu_handlers,
            ENTERING_TICKET_MESSAGE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, enter_ticket_message),
                MessageHandler(filters.PHOTO, enter_ticket_message),
                CallbackQueryHandler(back_to_menu, pattern="^back_to_menu$"),
                CallbackQueryHandler(cancel, pattern="^cancel$"),
            ] + main_menu_handlers,
            ADMIN_REPLYING_TICKET: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_send_ticket_reply),
                CommandHandler("cancel", cancel),
                CallbackQueryHandler(back_to_menu, pattern="^back_to_menu$"),
            ] + main_menu_handlers,
            # وضعیت‌های مدیریت ادمین
            ADMIN_MENU: [
                CallbackQueryHandler(admin_menu_handler),
                CallbackQueryHandler(back_to_menu, pattern="^back_to_menu$"),
            ] + main_menu_handlers,
            ADMIN_CARDS_MENU: [
                CallbackQueryHandler(cards_menu_handler),
                CallbackQueryHandler(back_to_menu, pattern="^back_to_menu$"),
            ] + main_menu_handlers,
            ADMIN_ADD_CARD_NUMBER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_card_number),
            ] + main_menu_handlers,
            ADMIN_ADD_CARD_HOLDER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_card_holder),
            ] + main_menu_handlers,
            ADMIN_ADD_CARD_BANK: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_card_bank),
            ] + main_menu_handlers,
            ADMIN_PLANS_MENU: [
                CallbackQueryHandler(plans_menu_handler),
                CallbackQueryHandler(back_to_menu, pattern="^back_to_menu$"),
            ] + main_menu_handlers,
            ADMIN_ADD_PLAN_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_plan_name),
            ] + main_menu_handlers,
            ADMIN_ADD_PLAN_PRICE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_plan_price),
            ] + main_menu_handlers,
            ADMIN_ADD_PLAN_DATA: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_plan_data),
            ] + main_menu_handlers,
            ADMIN_ADD_PLAN_DURATION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_plan_duration),
            ] + main_menu_handlers,
            ADMIN_RESTORE_FILE: [
                MessageHandler(filters.Document.ALL, handle_restore_file),
                CallbackQueryHandler(admin_menu_handler, pattern="^admin_back_menu$"),
                CallbackQueryHandler(back_to_menu, pattern="^back_to_menu$"),
            ] + main_menu_handlers,
        },
        fallbacks=[
            CommandHandler("start", start),
            CommandHandler("cancel", cancel),
            MessageHandler(filters.Regex("^❌ لغو$"), cancel),
            CallbackQueryHandler(back_to_menu, pattern="^back_to_menu$"),
            CallbackQueryHandler(cancel, pattern="^cancel$"),
        ] + main_menu_handlers,
        conversation_timeout=600,  # 10 دقیقه timeout
    )

    # اضافه کردن هندلرها
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("status", show_status))
    application.add_handler(CommandHandler("link", get_link))
    application.add_handler(CommandHandler("admin_stats", admin_stats))
    application.add_handler(CommandHandler("admin_test", admin_test))
    application.add_handler(CommandHandler("admin_panel", admin_panel))

    # دستورات پشتیبان‌گیری و مدیریت داده‌ها
    application.add_handler(CommandHandler("backup", backup_command))
    application.add_handler(CommandHandler("backups", backups_list))
    application.add_handler(CommandHandler("migrate", migrate_command))
    application.add_handler(CommandHandler("export", export_command))
    application.add_handler(CommandHandler("import", import_command))
    application.add_handler(CommandHandler("dashboard", dashboard_command))
    
    # دستورات جدید
    application.add_handler(CommandHandler("block", admin_block_user))
    application.add_handler(CommandHandler("unblock", admin_unblock_user))
    application.add_handler(CommandHandler("blocked", admin_list_blocked))
    application.add_handler(CommandHandler("discount", admin_create_discount))
    application.add_handler(CommandHandler("add_discount", admin_add_discount_cmd))
    application.add_handler(CommandHandler("discounts", admin_discounts_cmd))
    application.add_handler(CommandHandler("delete_discount", admin_delete_discount))
    application.add_handler(CommandHandler("wallet", admin_wallet_balance))
    application.add_handler(CommandHandler("add_wallet", admin_add_wallet))
    application.add_handler(CommandHandler("tickets", admin_tickets))
    application.add_handler(CommandHandler("reply_ticket", admin_reply_ticket))

    # هندلر بررسی عضویت کانال
    async def handle_check_membership(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        
        is_member = await check_channel_membership(user_id, context)
        if is_member:
            await query.edit_message_text("✅ عضویت شما تایید شد!\n\nحالا می‌توانید از ربات استفاده کنید.")
            user = update.effective_user
            keyboard = [
                [KeyboardButton("🛒 خرید اشتراک"), KeyboardButton("🧪 اشتراک تست")],
                [KeyboardButton("🔄 تمدید اشتراک"), KeyboardButton("📊 وضعیت اشتراک")],
                [KeyboardButton("🔗 لینک اتصال"), KeyboardButton("💰 کیف پول")],
                [KeyboardButton("👥 زیرمجموعه‌گیری"), KeyboardButton("💬 پشتیبانی")],
                [KeyboardButton("❓ راهنمای ربات"), KeyboardButton("📚 آموزش\u200cها (بزودی)")],
            ]
            if user.id == ADMIN_ID:
                keyboard.append([KeyboardButton("🔧 پنل مدیریت")])
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"سلام {user.first_name}! 👋\n\nاز منوی زیر یکی از گزینه‌ها را انتخاب کنید:",
                reply_markup=reply_markup
            )
        else:
            await show_join_channels_message(update, context)
    
    application.add_handler(CallbackQueryHandler(handle_check_membership, pattern="^check_membership$"))
    application.add_handler(CallbackQueryHandler(copy_link_callback, pattern="^copy_link$"))

    # دکمه‌های اینلاین پشتیبانی
    application.add_handler(CallbackQueryHandler(ticket_new_prompt, pattern="^ticket_new$"))
    application.add_handler(CallbackQueryHandler(ticket_list, pattern="^ticket_list$"))
    application.add_handler(CallbackQueryHandler(admin_reply_ticket_callback, pattern="^admin_reply_ticket_"))

    # هندلرهای تایید و رد پرداخت ادمین
    application.add_handler(CallbackQueryHandler(admin_approve_renew, pattern="^admin_approve_renew_"))
    application.add_handler(CallbackQueryHandler(admin_approve_payment, pattern="^admin_approve_"))
    application.add_handler(CallbackQueryHandler(admin_reject_payment, pattern="^admin_reject_"))

    # هندلر پیام‌های متنی
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # ─── راه‌اندازی پشتیبان‌گیری خودکار ───
    backup_scheduler = AutoBackupScheduler(admin_id=ADMIN_ID)
    
    # ─── راه‌اندازی سیستم اعلان‌ها ───
    notif_scheduler = NotificationScheduler()
    
    async def post_init(application):
        """تنظیمات بعد از شروع application"""
        backup_scheduler.set_bot(application.bot)
        await backup_scheduler.start()
        logger.info("Auto backup scheduler started")
        
        # شروع سیستم اعلان‌ها
        notif_scheduler.set_bot(application.bot)
        await notif_scheduler.start()
        logger.info("Notification scheduler started")
    
    async def post_shutdown(application):
        """توقف قبل از بسته شدن"""
        await hidify.close()
        await backup_scheduler.stop()
        await notif_scheduler.stop()
        logger.info("Schedulers stopped")

    application.post_init = post_init
    application.post_shutdown = post_shutdown

    # شروع خودکار پنل مدیریت وب
    port = int(os.getenv("PORT", 5000))
    start_dashboard_thread()
    logger.info(f"Dashboard auto-started on port {port}")

    # اجرا
    logger.info("Bot starting...")
    print("Bot is running...")
    print("Press Ctrl+C to stop.")

    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
