#!/usr/bin/env python3
"""
ربات تلگرام مدیریت VPN با اتصال به Hidify
"""

import os
import re
import json
import html
import logging
import uuid
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Tuple, Dict, List, Any, Union

from dotenv import load_dotenv
load_dotenv()

from hidify import HidifyClient
import threading
from dashboard import run_dashboard, start_dashboard_thread
from payment import PaymentManager, CryptoPaymentGateway
from utils import (
    gregorian_to_shamsi, gregorian_to_shamsi_full, 
    get_now_shamsi, days_remaining_shamsi, is_expired,
    get_now, get_now_naive, get_now_iso, get_now_timestamp,
    generate_qr_code_bytes, get_single_link_template, format_single_link
)
from admin_manager import (
    load_cards, add_card, update_card, delete_card, get_active_card, get_all_cards,
    load_plans, add_plan, update_plan, delete_plan, get_active_plans, get_all_plans, get_plan,
    get_plan_icon, get_plan_telegram_emoji,
)
from database import db
from backup import BackupManager, AutoBackupScheduler, send_backup_to_admin
from notifications import NotificationScheduler
from i18n import (
    t, get_language_keyboard, get_main_keyboard, get_contact_keyboard, get_all_lang_regex, SUPPORTED_LANGUAGES
)
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
    WebAppInfo,
    CopyTextButton,
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
    ADMIN_EDIT_PLAN_VALUE,
    ADMIN_RESTORE_FILE,
    SELECTING_NAME_TYPE,
    ENTERING_CUSTOM_NAME,
    RENEWING,
    ENTERING_DISCOUNT_CODE,
    ENTERING_TICKET_MESSAGE,
    ADMIN_REPLYING_TICKET,
    ENTERING_IMPORT_SUB,
) = range(26)


async def edit_admin_message_safe(query, text, reply_markup=None, parse_mode="Markdown"):
    """ویرایش امن پیام ادمین چه متن باشد چه تصویر یا داکیومنت"""
    try:
        if query.message.photo or query.message.document:
            await query.edit_message_caption(caption=text, reply_markup=reply_markup, parse_mode=parse_mode)
        else:
            await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception as e:
        logger.warning(f"Error in edit_admin_message_safe with parse_mode: {e}")
        try:
            if query.message.photo or query.message.document:
                await query.edit_message_caption(caption=text, reply_markup=reply_markup)
            else:
                await query.edit_message_text(text=text, reply_markup=reply_markup)
        except Exception as e2:
            logger.error(f"Fallback edit_admin_message_safe failed: {e2}")


async def send_subscription_card(bot, chat_id: int, sub_url: str, title: str, details: str = "", lang: str = None, uuid: str = "", account_name: str = ""):
    """ارسال کارت اشتراک همراه با QR Code و دکمه‌های استاندارد اتصال و دکمه تبدیل به لینک تکی"""
    import re
    clean_sub_url = sub_url.strip()
    if not lang:
        try:
            lang = db.get_user_language(chat_id)
        except Exception:
            lang = "fa"

    # استخراج خودکار UUID
    target_uuid = uuid
    if not target_uuid:
        match = re.search(r"([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})", clean_sub_url, re.IGNORECASE)
        if match:
            target_uuid = match.group(1)

    import html
    safe_clean_url = html.escape(str(clean_sub_url))
    caption = (
        f"{title}\n\n"
        f"{details}\n\n"
        f"🔗 <b>{t('link_card_title', lang).replace('**', '').replace('🔗', '').strip()}</b>\n"
        f"<code>{safe_clean_url}</code>\n\n"
        f"{t('link_card_hint', lang).replace('**', '')}"
    )

    keyboard = [
        [
            InlineKeyboardButton(t("btn_quick_connect", lang), url=clean_sub_url),
        ],
    ]

    if target_uuid:
        keyboard.append([
            InlineKeyboardButton(t("btn_single_link", lang), callback_data=f"single_link_{target_uuid}"),
        ])

    keyboard.append([
        InlineKeyboardButton(t("btn_copy_help", lang), callback_data="copy_link"),
    ])
    reply_markup = InlineKeyboardMarkup(keyboard)

    qr_bytes = generate_qr_code_bytes(clean_sub_url)
    if qr_bytes:
        try:
            await bot.send_photo(
                chat_id=chat_id,
                photo=qr_bytes,
                caption=caption,
                reply_markup=reply_markup,
                parse_mode="HTML",
            )
            return
        except Exception as e:
            logger.warning(f"Error sending QR Code photo HTML: {e}")
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
            parse_mode="HTML",
        )
    except Exception as e:
        logger.warning(f"Error sending subscription text HTML: {e}")
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=caption,
                reply_markup=reply_markup,
            )
        except Exception as e2:
            logger.error(f"Error sending subscription text plain: {e2}")


async def single_link_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تولید و ارسال کانفیگ / لینک تکی مستقیم با جایگذاری خودکار UUID و نام مشتری در قالب آماده با قالب‌بندی استاندارد و رفع بهم‌ریختگی BiDi"""
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    uuid = query.data.replace("single_link_", "").strip()

    user_lang = context.user_data.get("lang") or db.get_user_language(user.id)

    # دریافت اطلاعات اکانت و نام مشتری
    account_name = f"tg_{user.id}"
    subs = db.get_user_subscriptions(user.id, is_admin_bot=True)
    for s in subs:
        if s.get("hidify_uuid") == uuid:
            if s.get("account_name"):
                account_name = s.get("account_name")
            break

    template = get_single_link_template(db)
    single_direct_link = format_single_link(template, uuid=uuid, name=account_name)

    import html
    safe_account_name = html.escape(str(account_name))
    safe_uuid = html.escape(str(uuid))
    safe_link = html.escape(str(single_direct_link))

    if user_lang == "en":
        title_text = "⚡ <b>Single Direct Connection Link:</b>"
        account_label = "Account Name"
        uuid_label = "UUID"
        link_label = "🔗 <b>Your Single Link (tap to copy):</b>"
        hint_text = "💡 <b>Single Link Guide:</b>\n• This is a direct configuration link containing your credentials.\n• Copy the link above and import it into your VPN client."
    elif user_lang == "ru":
        title_text = "⚡ <b>Прямая ссылка для подключения (Single):</b>"
        account_label = "Имя аккаунта"
        uuid_label = "UUID"
        link_label = "🔗 <b>Ваша прямая ссылка (нажмите для копирования):</b>"
        hint_text = "💡 <b>Инструкция:</b>\n• Это прямая ссылка с вашей персональной конфигурацией.\n• Скопируйте ссылку выше и импортируйте в приложение."
    elif user_lang == "zh":
        title_text = "⚡ <b>单节点直接连接配置：</b>"
        account_label = "账户名称"
        uuid_label = "UUID"
        link_label = "🔗 <b>您的直连节点链接（点击复制）：</b>"
        hint_text = "💡 <b>使用说明：</b>\n• 此链接为包含您专属配置的直连节点。\n• 复制上方链接后直接导入客户端即可。"
    else:
        title_text = "⚡ <b>لینک اتصال مستقیم (تکی):</b>"
        account_label = "نام اکانت"
        uuid_label = "شناسه (UUID)"
        link_label = "🔗 <b>لینک تکی شما (برای کپی لمس کنید):</b>"
        hint_text = "💡 <b>راهنمای استفاده از لینک تکی:</b>\n• این لینک به صورت مستقیم کانفیگ اتصال اختصاصی شما را در بر دارد.\n• لینک بالا را کپی کرده و در نرم‌افزار خود Import نمایید."

    caption = (
        f"{title_text}\n\n"
        f"📋 {account_label}: <code>{safe_account_name}</code>\n"
        f"🆔 {uuid_label}: <code>\u200e{safe_uuid}</code>\n\n"
        f"{link_label}\n"
        f"<code>{safe_link}</code>\n\n"
        f"{hint_text}"
    )

    keyboard = [
        [InlineKeyboardButton(t("btn_copy_help", user_lang), callback_data="copy_link")],
        [InlineKeyboardButton("🏠 " + t("btn_back", user_lang), callback_data="back_to_menu")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    qr_bytes = generate_qr_code_bytes(single_direct_link)
    if qr_bytes:
        try:
            await context.bot.send_photo(
                chat_id=user.id,
                photo=qr_bytes,
                caption=caption,
                reply_markup=reply_markup,
                parse_mode="HTML",
            )
            return
        except Exception as e:
            logger.warning(f"Error sending single link QR Code photo HTML: {e}")
            try:
                await context.bot.send_photo(
                    chat_id=user.id,
                    photo=qr_bytes,
                    caption=caption,
                    reply_markup=reply_markup,
                )
                return
            except Exception as e2:
                logger.warning(f"Error sending single link QR Code photo plain: {e2}")

    try:
        await context.bot.send_message(
            chat_id=user.id,
            text=caption,
            reply_markup=reply_markup,
            parse_mode="HTML",
        )
    except Exception as e:
        logger.warning(f"Error sending single link text: {e}")
        await context.bot.send_message(
            chat_id=user.id,
            text=caption,
            reply_markup=reply_markup,
        )


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

async def ensure_user_verified(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """بررسی احراز هویت شماره تلفن کاربر. اگر تایید نشده باشد پیام درخواست شماره با کیبورد ارسال می‌شود."""
    user = update.effective_user
    if user.id == ADMIN_ID:
        return True
    if db.is_user_verified(user.id):
        return True

    lang = context.user_data.get("lang") or db.get_user_language(user.id) or "fa"
    contact_markup = get_contact_keyboard(lang)
    warning_text = f"{t('contact_auth_required', lang)}\n\n{t('contact_auth_prompt', lang)}"

    if update.callback_query:
        try:
            await update.callback_query.answer(t("contact_auth_required", lang), show_alert=True)
        except Exception:
            pass
        await context.bot.send_message(
            chat_id=user.id,
            text=warning_text,
            reply_markup=contact_markup,
            parse_mode="Markdown"
        )
    elif update.message:
        await update.message.reply_text(
            warning_text,
            reply_markup=contact_markup,
            parse_mode="Markdown"
        )
    return False


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دستور /start - شروع ربات همراه با انتخاب زبان و احراز هویت شماره تلفن"""
    user = update.effective_user
    
    # تنظیم دکمه ثابت مینی‌اپ تلگرام برای این کاربر
    try:
        from telegram_menu_helper import setup_telegram_chat_menu_button
        await setup_telegram_chat_menu_button(context.bot, chat_id=user.id, user_id=user.id, reseller_id=0)
    except Exception as e_btn:
        logger.debug(f"Could not setup menu button for user {user.id}: {e_btn}")

    # ثبت کاربر در دیتابیس
    db.save_user(telegram_id=user.id, username=user.username or user.first_name)

    # پردازش کد معرف / رفرال و نگهداری در سشن
    if context.args and len(context.args) > 0:
        arg = context.args[0].strip()
        if arg.startswith("ref_"):
            context.user_data["pending_ref"] = arg.replace("ref_", "")

    # بررسی بلاک بودن کاربر
    if db.is_blocked(user.id) and user.id != ADMIN_ID:
        await update.message.reply_text(
            "⛔ شما بلاک شده‌اید!\n\n"
            "برای رفع بلاک با پشتیبانی تماس بگیرید."
        )
        return CHOOSING

    # اگر کاربر قبلاً زبان انتخاب کرده و احراز هویت نشده است، دکمه شماره تماس را بفرست
    if user.id != ADMIN_ID and not db.is_user_verified(user.id):
        user_lang = db.get_user_language(user.id)
        if user_lang:
            context.user_data["lang"] = user_lang
            if REQUIRED_CHANNELS:
                is_member = await check_channel_membership(user.id, context)
                if not is_member:
                    await show_join_channels_message(update, context)
                    return CHOOSING

            contact_markup = get_contact_keyboard(user_lang)
            auth_msg = t("contact_auth_prompt", user_lang)
            await update.message.reply_text(
                auth_msg,
                reply_markup=contact_markup,
                parse_mode="Markdown"
            )
            return CHOOSING

    # ارسال منوی انتخاب زبان برای ورود اولیه
    prompt = t("lang_select_prompt", "fa")
    await update.message.reply_text(
        prompt,
        reply_markup=get_language_keyboard()
    )
    return CHOOSING


async def select_language_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ثبت زبان انتخابی کاربر و بررسی احراز هویت شماره تلفن یا نمایش منوی اصلی"""
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    lang = query.data.replace("lang_", "")
    if lang not in SUPPORTED_LANGUAGES:
        lang = "fa"

    # ذخیره در دیتابیس و حافظه سشن
    db.set_user_language(user.id, lang)
    context.user_data["lang"] = lang

    # پردازش رفرال در صورت وجود
    if context.user_data.get("pending_ref"):
        try:
            ref_id = int(context.user_data.pop("pending_ref"))
            if ref_id != user.id:
                db.add_referral(ref_id, user.id)
        except Exception as e:
            logger.warning(f"Error saving referral on language select: {e}")

    # بررسی عضویت در کانال‌ها
    if REQUIRED_CHANNELS:
        is_member = await check_channel_membership(user.id, context)
        if not is_member:
            await show_join_channels_message(update, context)
            return CHOOSING

    # احراز هویت با شماره تلفن تلگرام برای کاربران تایید نشده
    if user.id != ADMIN_ID and not db.is_user_verified(user.id):
        contact_markup = get_contact_keyboard(lang)
        auth_msg = t("contact_auth_prompt", lang)
        try:
            await query.edit_message_text(f"{t('lang_changed', lang)}\n\n{auth_msg}", parse_mode="Markdown")
        except Exception:
            pass
        await context.bot.send_message(
            chat_id=user.id,
            text=auth_msg,
            reply_markup=contact_markup,
            parse_mode="Markdown"
        )
        return CHOOSING

    reply_markup = get_main_keyboard(user.id, ADMIN_ID, lang)
    welcome_text = t("welcome_msg", lang, name=user.first_name)
    if user.id == ADMIN_ID:
        welcome_text += f"• {t('btn_admin', lang)}\n"
    welcome_text += f"\n{t('choose_option', lang)}"

    try:
        await query.edit_message_text(f"{t('lang_changed', lang)}\n\n{welcome_text}", parse_mode="Markdown")
    except Exception:
        pass

    await context.bot.send_message(
        chat_id=user.id,
        text=t("choose_option", lang),
        reply_markup=reply_markup
    )

    try:
        from telegram_menu_helper import setup_telegram_chat_menu_button
        await setup_telegram_chat_menu_button(context.bot, chat_id=user.id, user_id=user.id, reseller_id=0)
    except Exception:
        pass

    return CHOOSING


async def handle_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دریافت شماره تلفن ارسالی کاربر از طریق دکمه تلگرام و ثبت در دیتابیس"""
    message = update.message
    user = update.effective_user
    lang = context.user_data.get("lang") or db.get_user_language(user.id) or "fa"

    if not message.contact:
        return CHOOSING

    contact = message.contact

    # اعتبارسنجی امنیتی: شماره باید متعلق به اکانت خود کاربر باشد
    if contact.user_id and contact.user_id != user.id:
        await message.reply_text(
            t("contact_auth_invalid", lang),
            reply_markup=get_contact_keyboard(lang)
        )
        return CHOOSING

    phone_number = contact.phone_number
    db.set_user_phone(user.id, phone_number)
    logger.info(f"User {user.id} ({user.username}) successfully authenticated with phone: {phone_number}")

    # ارسال پیام موفقیت و کیبورد منوی اصلی
    reply_markup = get_main_keyboard(user.id, ADMIN_ID, lang)
    success_text = t("contact_auth_success", lang, phone=phone_number)
    welcome_text = t("welcome_msg", lang, name=user.first_name)
    if user.id == ADMIN_ID:
        welcome_text += f"• {t('btn_admin', lang)}\n"

    full_msg = f"{success_text}\n\n{welcome_text}\n{t('choose_option', lang)}"
    await message.reply_text(
        full_msg,
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )
    return CHOOSING


async def change_language_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """منوی تغییر زبان"""
    user = update.effective_user
    user_lang = context.user_data.get("lang") or db.get_user_language(user.id)
    prompt = t("lang_select_prompt", user_lang)
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(prompt, reply_markup=get_language_keyboard())
    else:
        await update.message.reply_text(prompt, reply_markup=get_language_keyboard())
    return CHOOSING


def get_payment_selection_payload(user_id: int, plan: dict, reseller_id: Optional[int] = None) -> Tuple[str, InlineKeyboardMarkup]:
    """تولید پیام و کیبورد استاندارد انتخاب روش پرداخت با چیدمان و اولویت داینامیک"""
    price = plan.get("price", 0)
    price_formatted = f"{price:,}".replace(",", "،")
    user_wallet = db.get_user_wallet_balance(user_id)
    usdt_price = CryptoPaymentGateway.toman_to_usdt(price, db)
    crypto_cfg = CryptoPaymentGateway.get_crypto_config(db)

    if reseller_id:
        gw_cfg = db.get_reseller_gateway(reseller_id)
    else:
        gw_cfg = db.get_admin_gateway()

    text = f"""
💳 <b>انتخاب روش پرداخت</b>

📋 پلن انتخابی: <b>{plan.get('name', 'نامشخص')}</b>
💰 مبلغ قابل پرداخت: <b>{price_formatted} تومان</b> (~ {usdt_price} USDT)
💳 موجودی کیف پول شما: <b>{user_wallet:,} تومان</b>

لطفاً نحوه پرداخت را انتخاب کنید:
"""
    keyboard = []
    
    # دریافت ترتیب و وضعیت فعال بودن روش‌های پرداخت به صورت پویا از دیتابیس
    ordered_methods = db.get_payment_methods(reseller_id=reseller_id)
    
    for m in ordered_methods:
        m_id = m.get("id")
        if not m.get("enabled", True):
            continue
            
        if m_id == "card_to_card":
            keyboard.append([InlineKeyboardButton("💵 کارت به کارت (بانکی)", callback_data="pay_card")])
            
        elif m_id == "wallet":
            if user_wallet >= price:
                keyboard.append([InlineKeyboardButton(f"⚡ پرداخت آنی از کیف پول ({user_wallet:,} ت)", callback_data="pay_wallet")])
            else:
                keyboard.append([InlineKeyboardButton(f"💰 پرداخت از کیف پول (کسری: {price - user_wallet:,} ت)", callback_data="pay_wallet_insufficient")])
                
        elif m_id == "online_gateway":
            if gw_cfg.get("enabled") and gw_cfg.get("key"):
                if gw_cfg.get("type") == "blupal":
                    gw_btn_text = "💳 پرداخت کارت به کارت هوشمند (بلوپال)"
                else:
                    gw_label = "زرین‌پال" if gw_cfg.get("type") == "zarinpal" else ("آیدی‌پی" if gw_cfg.get("type") == "idpay" else "آنلاین")
                    gw_btn_text = f"💳 درگاه پرداخت آنلاین ({gw_label})"
                keyboard.append([InlineKeyboardButton(gw_btn_text, callback_data="pay_online_gateway")])
            else:
                keyboard.append([InlineKeyboardButton("💳 درگاه آنلاین (بزودی)", callback_data="coming_soon_gateway")])
                
        elif m_id == "crypto":
            if crypto_cfg.get("enabled"):
                keyboard.append([InlineKeyboardButton(f"💎 پرداخت با تتر / کریپتو ({usdt_price} USDT)", callback_data="pay_crypto")])

    # دکمه‌های بازگشت و انصراف
    keyboard.append([
        InlineKeyboardButton("◀️ بازگشت", callback_data="back_to_confirm_purchase"),
        InlineKeyboardButton("❌ انصراف", callback_data="cancel")
    ])

    return text, InlineKeyboardMarkup(keyboard)


async def back_to_select_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بازگشت به انتخاب روش پرداخت با تمام گزینه‌ها"""
    query = update.callback_query
    await query.answer()
    
    plan_id = context.user_data.get("selected_plan")
    plans = get_plans()
    if not plan_id or plan_id not in plans:
        return await back_to_menu(update, context)
    
    plan = plans[plan_id]
    user_id = query.from_user.id
    text, reply_markup = get_payment_selection_payload(user_id, plan)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")
    return SELECTING_PAYMENT


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """لغو مکالمه"""
    user = update.effective_user
    user_lang = context.user_data.get("lang") or db.get_user_language(user.id)
    msg = t("op_cancelled", user_lang)
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(msg)
    else:
        await update.message.reply_text(msg)
    return ConversationHandler.END


async def timeout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ timeout مکالمه """
    user = update.effective_user
    user_lang = context.user_data.get("lang") or db.get_user_language(user.id)
    await update.message.reply_text(
        "⏰ " + t("op_cancelled", user_lang)
    )
    return ConversationHandler.END


async def back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بازگشت به منوی اصلی با زبان کاربر"""
    query = update.callback_query
    if query:
        await query.answer()
    
    context.user_data.pop("is_waiting_ticket", None)
    context.user_data.pop("replying_ticket_id", None)
    
    user = update.effective_user
    user_lang = context.user_data.get("lang") or db.get_user_language(user.id)
    reply_markup = get_main_keyboard(user.id, ADMIN_ID, user_lang)
    try:
        await query.edit_message_text("🏠 " + t("choose_option", user_lang))
    except Exception:
        pass
    await context.bot.send_message(
        chat_id=user.id,
        text=t("choose_option", user_lang),
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
    emoji = get_plan_telegram_emoji(plan, plan_id)
    text = f"""
{emoji} **انتخاب پلن:** {plan['name']}

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
    emoji = get_plan_telegram_emoji(plan, plan_id)
    text = f"""
💳 **انتخاب روش پرداخت**

{emoji} پلن: {plan['name']}
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
    
    # دریافت هوشمند کارت فعال با توجه به سقف روزانه و اولویت پیش‌فرض/پشتیبان
    active_card = get_active_card(incoming_amount=plan.get('price', 0))
    card_number = active_card.get("card_number", CARD_NUMBER)
    card_holder = active_card.get("card_holder", CARD_HOLDER)
    bank_name = active_card.get("bank_name", BANK_NAME)

    rial_amount = plan.get('price', 0) * 10
    rial_fmt = f"{rial_amount:,}"
    card_number_clean = re.sub(r"\D", "", str(card_number))

    text = f"""
💵 <b>پرداخت کارت به کارت</b>

📋 پلن: <b>{plan.get('name', 'نامشخص')}</b>

💰 <b>مبلغ قابل واریز:</b>
• به ریال (جهت همراه بانک / عابربانک):
<code>{rial_amount}</code> ریال (<b>{rial_fmt} ریال</b>)
• به تومان:
<code>{plan.get('price', 0)}</code> تومان (<b>{price_formatted} تومان</b>)

📌 <b>اطلاعات کارت جهت واریز:</b>
💳 شماره کارت:
<code>{card_number_clean}</code>

👤 <b>نام صاحب حساب:</b> {card_holder}
🏦 <b>بانک:</b> {bank_name}

⚠️ <b>نکات مهم:</b>
• برای کپی با یک لمس، روی <b>شماره کارت</b> یا <b>مبلغ به ریال</b> بالا یا دکمه‌های زیر بزنید.
• پس از واریز، شماره پیگیری یا اسکرین‌شات رسید را ارسال نمایید.
"""
    keyboard = [
        [InlineKeyboardButton("📋 کپی شماره کارت", callback_data=f"copy_card_{card_number_clean}")],
        [InlineKeyboardButton(f"💰 کپی مبلغ به ریال ({rial_fmt} ریال)", callback_data=f"copy_rial_{rial_amount}")],
        [InlineKeyboardButton(f"💵 کپی مبلغ به تومان ({price_formatted} ت)", callback_data=f"copy_amount_{plan.get('price', 0)}")],
        [InlineKeyboardButton("◀️ بازگشت", callback_data="back_to_select_payment"), InlineKeyboardButton("❌ انصراف", callback_data="cancel")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")
    return ENTERING_TRACKING_CODE


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دستور /help - راهنما، ویزارد قدم‌به‌قدم و پورتال آموزش‌های تصویری اتصال"""
    custom_tutorial = db.get_setting("tutorial_domain")
    custom_troubleshoot = db.get_setting("troubleshoot_domain")
    dashboard_url = os.getenv("DASHBOARD_URL", "").rstrip("/")

    if custom_tutorial:
        tutorial_url = f"https://{custom_tutorial}" if not str(custom_tutorial).startswith("http") else str(custom_tutorial)
    elif dashboard_url:
        tutorial_url = f"{dashboard_url}/help"
    else:
        tutorial_url = "http://127.0.0.1:5000/help"

    if custom_troubleshoot:
        troubleshoot_url = f"https://{custom_troubleshoot}" if not str(custom_troubleshoot).startswith("http") else str(custom_troubleshoot)
    else:
        troubleshoot_url = f"{tutorial_url.rstrip('/')}/troubleshoot"

    help_text = (
        "📖 <b>مرکز آموزش و راهنمای جامع اتصال</b>\n\n"
        "برای اتصال آسان یا رفع هرگونه اختلال و قطعی، روش مورد نظر خود را انتخاب نمایید:\n\n"
        "📱 <b>اندروید:</b> v2rayNG, Hiddify, Happ, NekoBox\n"
        "🍏 <b>آیفون و آیپد:</b> Streisand, FoXray, V2Box, Shadowrocket\n"
        "💻 <b>ویندوز و مک:</b> v2rayN, Hiddify, Nekoray\n"
        "📺 <b>تلویزیون هوشمند:</b> Android TV, Spark\n"
        "🌐 <b>مودم و روتر:</b> OpenWrt, MikroTik"
    )
    keyboard = [
        [InlineKeyboardButton("🧭 راهنمای قدم‌به‌قدم حل مشکل (داخل تلگرام)", callback_data="wiz_tb_start")],
        [InlineKeyboardButton("🚀 راهنمای قدم‌به‌قدم اتصال (داخل تلگرام)", callback_data="wiz_conn_start")],
        [InlineKeyboardButton("🌐 مشاهده آموزش‌های تصویری جامع (وب)", url=tutorial_url)],
        [InlineKeyboardButton("🛠️ سامانه آنلاین عیب‌یابی هوشمند (وب)", url=troubleshoot_url)]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    if update.message:
        await update.message.reply_text(help_text, reply_markup=reply_markup, parse_mode="HTML")
    elif update.callback_query:
        await update.callback_query.message.reply_text(help_text, reply_markup=reply_markup, parse_mode="HTML")


async def wizard_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت ویزاردهای تعاملی قدم‌به‌قدم عیب‌یابی و راهنمای اتصال درون تلگرام"""
    query = update.callback_query
    await query.answer()
    data = query.data

    custom_tutorial = db.get_setting("tutorial_domain")
    custom_troubleshoot = db.get_setting("troubleshoot_domain")
    dashboard_url = os.getenv("DASHBOARD_URL", "").rstrip("/")
    if custom_tutorial:
        tutorial_url = f"https://{custom_tutorial}" if not str(custom_tutorial).startswith("http") else str(custom_tutorial)
    elif dashboard_url:
        tutorial_url = f"{dashboard_url}/help"
    else:
        tutorial_url = "http://127.0.0.1:5000/help"

    if custom_troubleshoot:
        troubleshoot_url = f"https://{custom_troubleshoot}" if not str(custom_troubleshoot).startswith("http") else str(custom_troubleshoot)
    else:
        troubleshoot_url = f"{tutorial_url.rstrip('/')}/troubleshoot"

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

    # ─── ویزارد حل مشکلات اتصال (Troubleshoot) ───
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
        dev_names = {"android": "اندروید", "ios": "آیفون/آیپد", "windows": "ویندوز", "macos": "مک", "tv": "تلویزیون"}
        dev_title = dev_names.get(device, "دستگاه شما")

        text = (
            f"📶 <b>بررسی بسته اینترنت ({dev_title} - گام ۲ از ۶)</b>\n\n"
            "گاهی با نزدیک شدن به اتمام حجم بسته یا اتمام اعتبار زمانی، اپراتورها پکت‌های اینترنت را به صفحه خرید شارژ هدایت می‌کنند که مانع اتصال VPN می‌شود.\n\n"
            "📌 <b>کدهای استعلام بسته:</b>\n"
            "• همراه اول: <code>*100*10#</code>\n"
            "• ایرانسل: <code>*555*1*4#</code>\n"
            "• رایتل: <code>*144#</code>\n\n"
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
            "لطفاً ابتدا بسته اینترنت جدید برای سیم‌کارت یا مودم خود خریداری فرمایید. پس از فعال‌سازی بسته، یک بار دستگاه را به مدت ۱۰ ثانیه روی <b>حالت پرواز (Airplane Mode)</b> قرار داده و خارج نمایید تا اتصال تازه شود."
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
            "اطمینان حاصل کنید که حجم گیگابایتی یا مهلت روزهای اشتراک شما تمام نشده باشد.\n\n"
            "💡 با بازگشت به منوی ربات و زدن دکمه <b>«اشتراک‌های من»</b> یا باز کردن لینک اشتراک در مرورگر، می‌توانید حجم مصرفی و تاریخ انقضا را مشاهده فرمایید.\n\n"
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
            "سرویس شما به پایان رسیده است. جهت تمدید، می‌توانید از منوی اصلی ربات دکمه <b>«تمدید اشتراک»</b> یا خرید اشتراک جدید را انتخاب کنید تا سرویس شما فوراً متصل گردد."
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
            "پروتکل‌های نسل جدید (VLESS, VMess, Reality) بر پایه زمان استاندارد جهانی کار می‌کنند. اختلاف حتی ۶۰ ثانیه‌ای ساعت دستگاه باعث خطای invalid user یا عدم اتصال می‌شود!\n\n"
            "🔧 <b>راهنما:</b>\n"
            "• <b>اندروید:</b> وارد Settings > Date and time شوید و <code>Set Automatically</code> را یک بار خاموش و روشن کنید.\n"
            "• <b>آیفون:</b> وارد Settings > General > Date & Time شوید و <code>Set Automatically</code> را روشن کنید.\n"
            "• <b>ویندوز:</b> روی ساعت راست‌کلیک کرده، Adjust Date/Time را بزنید و روی <b>Sync now</b> کلیک کنید."
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
            "این دو اپراتور پکت‌های TLS را فیلتر می‌کنند. برای دور زدن آن:\n\n"
            "• در <b>v2rayNG:</b> وارد Settings شوید > بخش <b>Fragment</b> را روشن کنید و packets را روی <code>1-3</code> و length را روی <code>10-20</code> بگذارید.\n"
            "• در <b>Hiddify:</b> در تنظیمات، دور زدن فیلترینگ (Fragment) را روی <code>TLS Hello</code> بگذارید.\n"
            "• در <b>Streisand:</b> در Settings گزینه <code>Fragment</code> را روشن کنید."
        )
        buttons = [
            [InlineKeyboardButton("تنظیمات Fragment را اعمال کردم 🛡️", callback_data=f"wiz_tb_done_{device}")],
            [InlineKeyboardButton("◀️ مرحله قبل", callback_data=f"wiz_tb_time_ok_{device}")]
        ]
        return await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="HTML")

    if data.startswith("wiz_tb_op_wifi_"):
        device = data.replace("wiz_tb_op_wifi_", "")
        text = (
            "🌐 <b>تنظیم DNS و IPv6 برای اینترنت خانگی و مودم:</b>\n\n"
            "در اینترنت مخابرات، شاتل و آسیاتک تداخل IPv6 شایع است:\n\n"
            "۱. در تنظیمات برنامه VPN گزینه <b>Enable IPv6</b> را خاموش کنید.\n"
            "۲. بخش <b>Remote DNS</b> را روی <code>https://1.1.1.1/dns-query</code> یا <code>https://dns.google/dns-query</code> قرار دهید."
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
            "گوشی را ۱۰ ثانیه روی حالت پرواز (Airplane Mode) قرار دهید تا آی‌پی رنج جدید دریافت شود."
        )
        buttons = [
            [InlineKeyboardButton("انجام دادم و آماده تستم ✈️", callback_data=f"wiz_tb_done_{device}")],
            [InlineKeyboardButton("◀️ مرحله قبل", callback_data=f"wiz_tb_time_ok_{device}")]
        ]
        return await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="HTML")

    if data.startswith("wiz_tb_done_"):
        text = (
            "🔄 <b>به‌روزرسانی سرورها و تست پینگ (گام ۶ از ۶)</b>\n\n"
            "۱. در نرم‌افزار خود گزینه <b>Update subscription</b> را بزنید (یا در آیفون صفحه را به پایین بکشید).\n"
            "۲. تست پینگ بگیرید و سرور با پینگ سبز رنگ را انتخاب کنید.\n"
            "۳. دکمه اتصال را روشن فرمایید.\n\n"
            "آیا اتصال شما با موفقیت برقرار شد؟"
        )
        buttons = [
            [InlineKeyboardButton("مشکل حل شد و با موفقیت متصلم! 🎉", callback_data="wiz_tb_solved")],
            [InlineKeyboardButton("هنوز متصل نیستم / پیام به پشتیبانی 🎧", callback_data="wiz_tb_support")],
            [InlineKeyboardButton("◀️ شروع مجدد عیب‌یابی", callback_data="wiz_tb_start")]
        ]
        return await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="HTML")

    if data == "wiz_tb_solved":
        text = (
            "🎉 <b>بسیار عالی!</b>\n\n"
            "خوشحالیم که مشکل اتصال شما با موفقیت برطرف گردید.\n"
            "هر زمان که نیاز به راهنمایی داشتید مجدداً در خدمت شما هستیم."
        )
        buttons = [[InlineKeyboardButton("بازگشت به منوی اصلی", callback_data="back_to_menu")]]
        return await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="HTML")

    if data == "wiz_tb_support":
        support_username = db.get_setting("support_username", "")
        sup_txt = f"@{support_username.lstrip('@')}" if support_username else "پشتیبانی ربات"
        text = (
            f"🎧 <b>ارتباط با پشتیبانی ({sup_txt})</b>\n\n"
            "اگر پس از انجام تمام مراحل بالا موفق به اتصال نشدید، لطفاً به پشتیبانی پیام دهید و نام کاربری یا لینک اشتراک خود را به همراه نوع اپراتور اینترنت ارسال فرمایید."
        )
        buttons = []
        if support_username:
            buttons.append([InlineKeyboardButton("ارسال پیام به پشتیبانی تلگرام", url=f"https://t.me/{support_username.lstrip('@')}")])
        buttons.append([InlineKeyboardButton("بازگشت به منوی اصلی", callback_data="back_to_menu")])
        return await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="HTML")

    # ─── ویزارد راهنمای اتصال (Connection) ───
    if data == "wiz_conn_start":
        text = (
            "🚀 <b>راهنمای گام‌به‌گام راه‌اندازی و اتصال (گام ۱ از ۵)</b>\n\n"
            "سیستم‌عامل یا دستگاه خود را انتخاب فرمایید:"
        )
        buttons = [
            [InlineKeyboardButton("📱 اندروید (Samsung, Xiaomi, ...)", callback_data="wiz_conn_dev_android")],
            [InlineKeyboardButton("🍏 آیفون یا آیپد (iOS)", callback_data="wiz_conn_dev_ios")],
            [InlineKeyboardButton("💻 کامپیوتر ویندوز", callback_data="wiz_conn_dev_windows")],
            [InlineKeyboardButton("🖥️ مک‌بوک (macOS)", callback_data="wiz_conn_dev_macos")],
            [InlineKeyboardButton("📺 تلویزیون هوشمند", callback_data="wiz_conn_dev_tv")],
            [InlineKeyboardButton("◀️ بازگشت", callback_data="wiz_menu")]
        ]
        return await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="HTML")

    if data.startswith("wiz_conn_dev_"):
        device = data.replace("wiz_conn_dev_", "")
        if device == "android":
            app_name = "v2rayNG"
            dl_url = "https://github.com/2dust/v2rayNG/releases/latest"
        elif device == "ios":
            app_name = "Streisand"
            dl_url = "https://apps.apple.com/app/streisand/id6450534064"
        elif device == "windows":
            app_name = "v2rayN"
            dl_url = "https://github.com/2dust/v2rayN/releases/latest"
        elif device == "macos":
            app_name = "FoXray"
            dl_url = "https://apps.apple.com/app/foxray/id6448898396"
        else:
            app_name = "v2rayNG TV"
            dl_url = "https://github.com/2dust/v2rayNG/releases/latest"

        text = (
            f"📲 <b>دانلود و نصب نرم‌افزار {app_name} (گام ۲ از ۵)</b>\n\n"
            f"بهترین و پایدارترین نرم‌افزار برای دستگاه شما اپلیکیشن <b>{app_name}</b> می‌باشد.\n\n"
            "لطفاً نرم‌افزار را از لینک زیر دانلود و روی دستگاه خود نصب فرمایید:"
        )
        buttons = [
            [InlineKeyboardButton(f"دانلود {app_name}", url=dl_url)],
            [InlineKeyboardButton("برنامه را نصب کردم، مرحله بعد 📲", callback_data=f"wiz_conn_imp_{device}")],
            [InlineKeyboardButton("◀️ مرحله قبل", callback_data="wiz_conn_start")]
        ]
        return await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="HTML")

    if data.startswith("wiz_conn_imp_"):
        device = data.replace("wiz_conn_imp_", "")
        text = (
            "📥 <b>وارد کردن لینک اشتراک در نرم‌افزار (گام ۳ از ۵)</b>\n\n"
            "۱. ابتدا در ربات تلگرام روی لینک اشتراک خود کلیک کنید تا کپی شود.\n"
            "۲. نرم‌افزار را باز کرده و علامت مثبت (<b>+</b>) بالای صفحه را بزنید.\n"
            "۳. گزینه <b>Import from clipboard</b> (وارد کردن از کلیپ‌بورد) را انتخاب نمایید تا کلیه سرورها اضافه شوند."
        )
        buttons = [
            [InlineKeyboardButton("لینک را وارد کردم، مرحله بعد 📥", callback_data=f"wiz_conn_upd_{device}")],
            [InlineKeyboardButton("◀️ مرحله قبل", callback_data=f"wiz_conn_dev_{device}")]
        ]
        return await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="HTML")

    if data.startswith("wiz_conn_upd_"):
        device = data.replace("wiz_conn_upd_", "")
        text = (
            "🔄 <b>به‌روزرسانی سرورها و تست پینگ (گام ۴ از ۵)</b>\n\n"
            "۱. در نرم‌افزار گزینه <b>Update subscription</b> را لمس کنید (یا در آیفون صفحه را به پایین بکشید).\n"
            "۲. گزینه <b>Real delay test</b> را بزنید تا پینگ سرورها با رنگ سبز ظاهر شوند.\n"
            "۳. سروری که کمترین عدد پینگ سبز را دارد لمس کنید."
        )
        buttons = [
            [InlineKeyboardButton("سرورها آپدیت شدند و پینگ سبز دیدم 🔄", callback_data=f"wiz_conn_con_{device}")],
            [InlineKeyboardButton("◀️ مرحله قبل", callback_data=f"wiz_conn_imp_{device}")]
        ]
        return await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="HTML")

    if data.startswith("wiz_conn_con_"):
        text = (
            "🚀 <b>اتصال و فعال‌سازی اینترنت آزاد (گام ۵ از ۵)</b>\n\n"
            "روی دکمه اتصال در نرم‌افزار کلیک کنید. در اولین اتصال پیامی از طرف گوشی مبنی بر اجازه ساخت پروفایل VPN ظاهر می‌شود که حتماً روی OK یا Allow بزنید.\n\n"
            "با سبز شدن دکمه یا ظاهر شدن کلید بالای گوشی، اینترنت بدون فیلتر فعال است!"
        )
        buttons = [
            [InlineKeyboardButton("با موفقیت متصل شدم! 🎉", callback_data="wiz_tb_solved")],
            [InlineKeyboardButton("متصل نشد، رفتن به عیب‌یابی 🛠️", callback_data="wiz_tb_start")],
            [InlineKeyboardButton("◀️ شروع مجدد راهنما", callback_data="wiz_conn_start")]
        ]
        return await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="HTML")


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
    if not await ensure_user_verified(update, context):
        return CHOOSING

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
        emoji = get_plan_telegram_emoji(plan, plan_id)
        keyboard.append([
            InlineKeyboardButton(
                f"{emoji} {plan['name']} - {plan['description']} - {price_formatted} تومان",
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

    raw_data = query.data
    extracted_id = raw_data.removeprefix("plan_") if raw_data.startswith("plan_") else raw_data

    plans = get_plans()
    if extracted_id in plans:
        plan_id = extracted_id
    elif raw_data in plans:
        plan_id = raw_data
    elif f"plan_{extracted_id}" in plans:
        plan_id = f"plan_{extracted_id}"
    else:
        matched_id = next((k for k in plans.keys() if k.lower() in [extracted_id.lower(), raw_data.lower()]), None)
        if matched_id:
            plan_id = matched_id
        else:
            await query.edit_message_text("❌ پلن نامعتبر!")
            return CHOOSING

    plan = plans[plan_id]
    context.user_data["selected_plan"] = plan_id

    price_formatted = f"{plan['price']:,}".replace(",", "،")
    emoji = get_plan_telegram_emoji(plan, plan_id)
    text = (
        f"{emoji} پلن انتخاب شده: {plan['name']}\n\n"
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
    user_id = query.from_user.id
    text, reply_markup = get_payment_selection_payload(user_id, plan)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")
    return SELECTING_PAYMENT


async def copy_card_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پاسخ به کلیک روی دکمه کپی شماره کارت"""
    query = update.callback_query
    raw_num = query.data.replace("copy_card_", "").strip()
    c_num = re.sub(r"\D", "", raw_num)
    await query.answer(f"📋 شماره کارت:\n{c_num}\n(در کلیپ‌بورد کپی شد)", show_alert=False)
    try:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"📋 <b>شماره کارت مقصد (جهت واریز):</b>\n<code>{c_num}</code>\n\n<i>👆 روی شماره کارت بالا بزنید تا با یک لمس کپی شود.</i>",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.warning(f"Failed to send copy card msg: {e}")


async def copy_rial_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پاسخ به کلیک روی دکمه کپی مبلغ به ریال (جهت همراه بانک)"""
    query = update.callback_query
    raw_amt = query.data.replace("copy_rial_", "").strip()
    clean_amt = re.sub(r"\D", "", raw_amt)
    try:
        rial_fmt = f"{int(clean_amt):,}"
    except Exception:
        rial_fmt = clean_amt
    await query.answer(f"💰 مبلغ به ریال:\n{rial_fmt} ریال\n(در کلیپ‌بورد کپی شد)", show_alert=False)
    try:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"💰 <b>مبلغ به ریال (جهت همراه بانک / عابربانک):</b>\n<code>{clean_amt}</code>\n\n<i>👆 روی عدد بالا بزنید تا با یک لمس کپی شود ({rial_fmt} ریال).</i>",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.warning(f"Failed to send copy rial msg: {e}")


async def copy_amount_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پاسخ به کلیک روی دکمه کپی مبلغ به تومان"""
    query = update.callback_query
    raw_amt = query.data.replace("copy_amount_", "").strip()
    clean_amt = re.sub(r"\D", "", raw_amt)
    try:
        toman_fmt = f"{int(clean_amt):,}"
    except Exception:
        toman_fmt = clean_amt
    await query.answer(f"💵 مبلغ به تومان:\n{toman_fmt} تومان\n(در کلیپ‌بورد کپی شد)", show_alert=False)
    try:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"💵 <b>مبلغ به تومان:</b>\n<code>{clean_amt}</code>\n\n<i>👆 روی عدد بالا بزنید تا با یک لمس کپی شود ({toman_fmt} تومان).</i>",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.warning(f"Failed to send copy amount msg: {e}")


async def handle_payment_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش انتخاب روش پرداخت (کیف پول، درگاه آنلاین، کارت بانکی، کریپتو) با پایداری کامل"""
    query = update.callback_query
    user = update.effective_user

    # مدیریت دکمه‌های کپی
    if query.data.startswith("copy_card_"):
        return await copy_card_callback(update, context)
    if query.data.startswith("copy_rial_"):
        return await copy_rial_callback(update, context)
    if query.data.startswith("copy_amount_"):
        return await copy_amount_callback(update, context)

    if query.data == "back_to_confirm_purchase":
        try:
            await query.answer()
        except Exception:
            pass
        return await back_to_confirm_purchase(update, context)

    if query.data == "cancel":
        try:
            await query.answer()
            await query.edit_message_text("❌ عملیات لغو شد.")
        except Exception:
            pass
        return CHOOSING

    if query.data in ("coming_soon_gateway", "coming_soon"):
        try:
            await query.answer("💳 درگاه پرداخت آنلاین شاپرک به زودی فعال خواهد شد. لطفاً از کارت به کارت یا کیف پول استفاده فرمایید.", show_alert=True)
        except Exception:
            pass
        return SELECTING_PAYMENT

    plan_id = context.user_data.get("selected_plan")
    plans = get_plans()
    plan = plans.get(str(plan_id), {}) if plans else {}
    if not plan and plans:
        # جستجو بر اساس کلید عددی یا رشته‌ای
        for k, v in plans.items():
            if str(k) == str(plan_id):
                plan = v
                break

    price = plan.get("price", 0)
    price_formatted = f"{price:,}".replace(",", "،")

    if query.data == "back_to_select_payment":
        try:
            await query.answer()
            text, reply_markup = get_payment_selection_payload(user.id, plan)
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")
        except Exception as e:
            logger.warning(f"Error returning to payment selection: {e}")
        return SELECTING_PAYMENT

    if query.data == "pay_wallet_insufficient":
        try:
            user_wallet = db.get_user_wallet_balance(user.id)
            await query.answer(f"❌ موجودی کیف پول شما ({user_wallet:,} ت) برای این پلن کافی نیست. ابتدا کیف پول را شارژ کنید یا کارت به کارت نمایید.", show_alert=True)
        except Exception:
            pass
        return SELECTING_PAYMENT

    elif query.data == "pay_wallet":
        try:
            await query.answer()
        except Exception:
            pass

        # پرداخت ۱۰۰٪ آنی و خودکار از موجودی کیف پول!
        user_wallet = db.get_user_wallet_balance(user.id)
        if user_wallet < price:
            try:
                await query.answer("❌ موجودی کیف پول کافی نیست!", show_alert=True)
            except Exception:
                pass
            return SELECTING_PAYMENT

        # کسر از موجودی کیف پول
        deduct_res = db.deduct_wallet_balance(user.id, price, f"خرید آنی اشتراک {plan.get('name')}")
        if not deduct_res.get("success"):
            try:
                await query.answer("❌ خطا در کسر موجودی: " + str(deduct_res.get("error")), show_alert=True)
            except Exception:
                pass
            return SELECTING_PAYMENT

        try:
            await query.edit_message_text("⏳ در حال ساخت و فعال‌سازی آنی اشتراک شما در هیدیفای...")
        except Exception:
            pass

        # ساخت اکانت در هیدیفای
        username = f"tg_{user.id}"
        try:
            result = await hidify.create_user(
                name=username,
                usage_limit_gb=plan.get("data_limit") if plan.get("data_limit", 0) > 0 else None,
                package_days=plan.get("duration", 30),
                enable=True,
                comment=str(user.id)
            )
            user_uuid = result.get("uuid", "")
            if not user_uuid:
                raise Exception("UUID received empty from Hiddify")

            db.save_subscription(
                telegram_id=user.id,
                hidify_uuid=user_uuid,
                plan_id=plan_id,
                plan_name=plan.get("name", "نامشخص"),
                data_limit=plan.get("data_limit", 0),
                duration=plan.get("duration", 30),
                status="active",
                account_name=username,
                account_comment=str(user.id),
                created_by="admin_bot",
            )

            # اطلاع به ادمین
            try:
                await context.bot.send_message(
                    chat_id=ADMIN_ID,
                    text=f"⚡ <b>خرید آنی از کیف پول</b>\n\n👤 کاربر: <code>{user.id}</code> (@{user.username})\n📋 پلن: <b>{plan.get('name')}</b>\n💵 مبلغ: <b>{price_formatted} تومان</b>\n💳 موجودی پس از کسر: <b>{deduct_res.get('new_balance'):,} تومان</b>",
                    parse_mode="HTML"
                )
            except Exception:
                pass

            # ارسال لینک به کاربر
            base_url = (HIDIFY_PANEL_URL or "").rstrip("/")
            proxy_path = (USER_PROXY_PATH or HIDIFY_PROXY_PATH or "").strip("/")
            subscription_url = f"{base_url}/{proxy_path}/{user_uuid}/"

            details = (
                f"✅ مبلغ <b>{price_formatted} تومان</b> از کیف پول شما کسر و اشتراک فوراً فعال شد!\n\n"
                f"📋 پلن: <b>{plan.get('name')}</b>\n"
                f"📊 حجم: <b>{plan.get('data_limit', 'نامحدود')} گیگابایت</b>\n"
                f"⏰ مدت اعتبار: <b>{plan.get('duration', 30)} روز</b>\n"
                f"💳 مانده موجودی کیف پول: <b>{deduct_res.get('new_balance'):,} تومان</b>"
            )
            await send_subscription_card(
                context.bot,
                chat_id=user.id,
                sub_url=subscription_url,
                title="🎉 <b>اشتراک شما با موفقیت فعال شد!</b>",
                details=details
            )
            return CHOOSING

        except Exception as e:
            logger.error(f"Error activating sub from wallet: {e}")
            # بازگشت وجه در صورت خطا
            db.add_wallet_balance(user.id, price, "بازگشت وجه به دلیل خطای سرور هیدیفای", tx_type="refund")
            try:
                await query.edit_message_text(f"❌ خطایی در فعال‌سازی اشتراک رخ داد و مبلغ به کیف پول شما برگشت داده شد:\n{str(e)[:150]}")
            except Exception:
                pass
            return CHOOSING

    elif query.data == "pay_online_gateway":
        try:
            await query.answer()
        except Exception:
            pass

        # پرداخت مستقیم از طریق درگاه پرداخت آنلاین شاپرک
        gw_cfg = db.get_admin_gateway()
        gw_type = gw_cfg.get("type", "zarinpal")
        gw_key = gw_cfg.get("key", "")
        sandbox = gw_cfg.get("sandbox", False)

        order_id = f"ONL_{int(datetime.now().timestamp())}_{user.id % 10000}"
        domain = db.get_setting("custom_domain") or os.getenv("PANEL_DOMAIN", "http://localhost:5000")
        if not str(domain).startswith("http"):
            domain = f"https://{domain}"
        callback_url = f"{str(domain).rstrip('/')}/payment/callback/{order_id}"

        pay_url = None
        try:
            if gw_type == "zarinpal":
                from payment import ZarinPal
                zp = ZarinPal(merchant_id=gw_key, sandbox=sandbox)
                res = zp.create_payment(amount=price, description=f"خرید اشتراک {plan.get('name')}", callback_url=callback_url)
                if res.get("success"):
                    pay_url = res.get("payment_url")
                    db.save_transaction(
                        order_id=order_id,
                        user_id=user.id,
                        username=user.username or user.first_name,
                        plan_name=plan.get("name"),
                        amount=price,
                        gateway="zarinpal",
                        tracking_code=res.get("authority", ""),
                        status="pending"
                    )
            elif gw_type == "idpay":
                from payment import IDPay
                idp = IDPay(api_key=gw_key, sandbox=sandbox)
                res = idp.create_payment(amount=price, name=user.full_name or "کاربر", description=f"خرید اشتراک {plan.get('name')}", callback_url=callback_url, order_id=order_id)
                if res.get("success"):
                    pay_url = res.get("payment_url")
                    db.save_transaction(
                        order_id=order_id,
                        user_id=user.id,
                        username=user.username or user.first_name,
                        plan_name=plan.get("name"),
                        amount=price,
                        gateway="idpay",
                        tracking_code=res.get("payment_id", ""),
                        status="pending"
                    )
            elif gw_type == "blupal":
                from payment import BluPal
                bp = BluPal(api_key=gw_key, sandbox=sandbox)
                res = bp.create_payment(amount=price, order_id=order_id, description=f"خرید اشتراک {plan.get('name')}")
                if res.get("success"):
                    pay_url = res.get("payment_url") or res.get("payment_link")
                    invoice_id = res.get("invoice_id")
                    db.save_transaction(
                        order_id=order_id,
                        user_id=user.id,
                        username=user.username or user.first_name,
                        plan_name=plan.get("name"),
                        amount=price,
                        gateway="blupal",
                        tracking_code=str(invoice_id or order_id),
                        status="pending"
                    )
        except Exception as e:
            logger.error(f"Error creating online gateway payment: {e}")

        if pay_url:
            gw_title = "کارت به کارت هوشمند بلوپال" if gw_type == "blupal" else "درگاه پرداخت آنلاین شاپرک"
            btn_title = "🌐 ورود به درگاه پرداخت هوشمند بلوپال" if gw_type == "blupal" else "🌐 ورود به درگاه پرداخت شاپرک"
            text = f"""
💳 <b>{gw_title}</b>

📋 پلن: <b>{html.escape(str(plan.get('name', '')))}</b>
💰 مبلغ: <b><code>{price_formatted}</code> تومان</b>
🔢 شناسه سفارش: <code>{order_id}</code>

برای پرداخت روی دکمه زیر کلیک کنید. پس از تکمیل تراکنش، اشتراک شما به صورت آنی و خودکار فعال می‌گردد:
"""
            keyboard = [
                [InlineKeyboardButton(btn_title, url=pay_url)],
                [InlineKeyboardButton("◀️ بازگشت", callback_data="back_to_select_payment")]
            ]
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
            return SELECTING_PAYMENT
        else:
            try:
                await query.answer("❌ خطا در اتصال به درگاه بانکی. لطفاً از کارت به کارت استفاده فرمایید.", show_alert=True)
            except Exception:
                pass
            return SELECTING_PAYMENT

    elif query.data == "pay_crypto":
        try:
            await query.answer()
        except Exception:
            pass

        # پرداخت با ارز دیجیتال / تتر
        try:
            crypto_res = CryptoPaymentGateway.create_payment(price, user.id, plan.get('name', 'نامشخص'), db_instance=db)
            usdt_amt = crypto_res.get("usdt_amount", 0)
            wallet_addr = crypto_res.get("wallet_address", "")
            pay_url = crypto_res.get("payment_url", "")

            keyboard = []
            if pay_url:
                keyboard.append([InlineKeyboardButton("🌐 ورود به درگاه آنلاین کریپتو", url=pay_url)])
                text = f"""
💎 <b>پرداخت ارزی با کریپتو (تتر / رمزارز)</b>

📋 پلن: <b>{html.escape(str(plan.get('name', '')))}</b>
💰 معادل تتر: <b>{usdt_amt} USDT</b>

لطفاً روی دکمه زیر کلیک کرده و پرداخت خود را انجام دهید. اشتراک شما پس از واریز به صورت خودکار فعال خواهد شد.
"""
            else:
                text = f"""
💎 <b>پرداخت مستقیم با تتر (USDT TRC20 / TON)</b>

📋 پلن: <b>{html.escape(str(plan.get('name', '')))}</b>
💰 مبلغ قابل انتقال: <b><code>{usdt_amt}</code> USDT</b>

📌 <b>آدرس ولت دریافت:</b>
<code>{wallet_addr}</code>

⚠️ لطفاً پس از انتقال، کد رهگیری هش (TXID) یا تصویر رسید را به عنوان پیام ارسال فرمایید.
"""
                keyboard.append([InlineKeyboardButton("📝 ارسال کد هش یا رسید", callback_data="pay_card")])

            keyboard.append([InlineKeyboardButton("◀️ بازگشت", callback_data="back_to_select_payment")])
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")
            return ENTERING_TRACKING_CODE
        except Exception as e:
            logger.error(f"Error in pay_crypto: {e}")
            try:
                await query.answer("❌ خطا در بارگذاری اطلاعات پرداخت ارزی.", show_alert=True)
            except Exception:
                pass
            return SELECTING_PAYMENT

    elif query.data == "pay_card":
        try:
            await query.answer()
        except Exception:
            pass

        try:
            # دریافت هوشمند کارت فعال مستقیماً از تنظیمات دیتابیس پنل مدیریت بر اساس سقف روزانه و اولویت
            active_card = get_active_card(incoming_amount=plan.get('price', 0)) or {}
            raw_card = active_card.get("card_number") or ""
            card_holder = html.escape(str(active_card.get("card_holder") or ""))
            bank_name = html.escape(str(active_card.get("bank_name") or ""))
            card_number = re.sub(r"\D", "", str(raw_card))

            if not card_number:
                await query.edit_message_text("❌ شماره کارت فعالی در تنظیمات مدیریت سامانه ثبت نشده است. لطفاً به پشتیبانی پیام دهید.")
                return SELECTING_PAYMENT

            pname = html.escape(str(plan.get('name', 'نامشخص')))

            # استفاده از سیستم خودکار کارت به کارت (Smart Invoice با ارقام خرد یکتا)
            sms_cfg = db.get_admin_bank_sms_config() if hasattr(db, "get_admin_bank_sms_config") else {}
            digits = sms_cfg.get("digits", 3) if isinstance(sms_cfg, dict) else 3
            timeout = sms_cfg.get("timeout", 15) if isinstance(sms_cfg, dict) else 15
            sub_id = context.user_data.get("renew_sub_id") or 0

            invoice = db.create_smart_invoice(
                sub_id=sub_id,
                plan_id=plan_id,
                reseller_id=0,
                base_amount=price,
                target_card=active_card,
                digits=digits,
                timeout_minutes=timeout,
                instant_activation=True
            )
            final_amount_toman = invoice["final_amount"]
            rial_amount = final_amount_toman * 10
            rial_fmt = f"{rial_amount:,}"
            toman_fmt = f"{final_amount_toman:,}"

            context.user_data["pending_order_id"] = invoice["order_id"]
            context.user_data["smart_final_amount"] = final_amount_toman

            text = f"""
💳 <b>پرداخت خودکار کارت به کارت</b>

📋 پلن انتخابی: <b>{pname}</b>

💰 <b>مبلغ دقیق قابل واریز (به ریال):</b>
<code>{rial_amount}</code> ریال (<b>{rial_fmt} ریال</b>)
<i>معادل: {toman_fmt} تومان</i>

📌 <b>اطلاعات کارت بانکی مقصد:</b>
💳 شماره کارت:
<code>{card_number}</code>
"""
            if card_holder:
                text += f"\n👤 <b>نام صاحب حساب:</b> {card_holder}"
            if bank_name:
                text += f"\n🏦 <b>بانک:</b> {bank_name}"

            text += f"""

⚠️ <b>نکته بسیار مهم درباره مبلغ و کپی:</b>
سیستم مجهز به <b>تایید و فعال‌سازی خودکار با پیامک بانکی</b> است. به دلیل وجود <b>ارقام خرد تصادفی</b> در مبلغ جهت شناسایی خودکار واریزی شما، لطفاً مبلغ را دقیقاً با دکمه <b>«کپی مبلغ به ریال»</b> بردارید و در همراه بانک پیست نمایید تا اشتباهی در انتقال رخ ندهد و اشتراک شما فوراً تایید گردد.

⚠️ <b>بعد از پرداخت، متن رسید یا تصویر رسید را ارسال کنید.</b>
"""
            keyboard = [
                [InlineKeyboardButton("📋 کپی شماره کارت", copy_text=CopyTextButton(card_number))],
                [InlineKeyboardButton(f"💰 کپی مبلغ به ریال ({rial_fmt} ریال)", copy_text=CopyTextButton(str(rial_amount)))],
                [InlineKeyboardButton("◀️ بازگشت", callback_data="back_to_select_payment"), InlineKeyboardButton("❌ انصراف", callback_data="cancel")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")
            return ENTERING_TRACKING_CODE
        except Exception as e:
            logger.error(f"Error in pay_card in bot.py: {e}")
            try:
                await query.edit_message_text(f"❌ خطا در بارگذاری اطلاعات کارت: {e}")
            except Exception:
                pass
            return SELECTING_PAYMENT

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


async def enter_tracking_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دریافت فایل رسید پرداخت (تصویر یا PDF ارسالی بصورت فایل)"""
    user = update.effective_user
    plan_id = context.user_data.get("selected_plan")
    plans = get_plans()
    plan = plans.get(plan_id, {})
    price_formatted = f"{plan.get('price', 0):,}".replace(",", "،")

    doc = update.message.document
    if not doc:
        await update.message.reply_text("❌ لطفاً فایل یا تصویر رسید را ارسال کنید.")
        return ENTERING_TRACKING_CODE

    file_id = doc.file_id
    file_name = doc.file_name or "رسید فایل"

    # ذخیره اطلاعات
    context.user_data["tracking_code"] = f"فایل رسید ({file_name})"
    context.user_data["receipt_photo"] = file_id
    context.user_data["receipt_is_document"] = True

    # تایید اطلاعات
    text = (
        f"✅ **تایید پرداخت کارت به کارت**\n\n"
        f"📋 پلن: **{plan.get('name', 'نامشخص')}**\n"
        f"💰 مبلغ: **{price_formatted}** تومان\n"
        f"📁 رسید: `{file_name}` دریافت شد\n\n"
        f"آیا اطلاعات برای بررسی ادمین ارسال شود؟"
    )
    keyboard = [
        [InlineKeyboardButton("✅ تایید و ارسال", callback_data="confirm_card_payment")],
        [InlineKeyboardButton("◀️ بازگشت", callback_data="back_to_enter_tracking"), InlineKeyboardButton("❌ انصراف", callback_data="cancel")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")
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
        if "smart_final_amount" in context.user_data:
            final_price = context.user_data["smart_final_amount"]
        else:
            final_price = max(0, original_price - discount_amount)
        price_formatted = f"{final_price:,}".replace(",", "،")

        # ذخیره تراکنش کارت به کارت
        order_id = context.user_data.get("pending_order_id") or f"card_{user.id}_{get_now_timestamp()}"
        account_name = context.user_data.get("account_name", f"tg_{user.id}")
        account_comment = context.user_data.get("account_comment")

        receipt_photo = context.user_data.get("receipt_photo")
        receipt_is_doc = context.user_data.get("receipt_is_document", False)
        receipt_type = "document" if receipt_is_doc else ("photo" if receipt_photo else None)

        saved_receipt_filename = None
        if receipt_photo:
            try:
                receipts_dir = Path("data/receipts")
                receipts_dir.mkdir(parents=True, exist_ok=True)
                ext = ".pdf" if receipt_is_doc else ".jpg"
                tg_file = await context.bot.get_file(receipt_photo)
                saved_receipt_filename = f"receipt_{order_id}{ext}"
                await tg_file.download_to_drive(receipts_dir / saved_receipt_filename)
            except Exception as dl_err:
                logger.warning(f"Could not download telegram receipt to disk: {dl_err}")

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
            receipt_image=saved_receipt_filename or receipt_photo,
            receipt_file_type="web_upload" if saved_receipt_filename else receipt_type
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
            is_doc = context.user_data.get("receipt_is_document", False)
            if receipt_photo:
                if is_doc:
                    await context.bot.send_document(
                        chat_id=ADMIN_ID,
                        document=receipt_photo,
                        caption=admin_text,
                        reply_markup=reply_markup,
                        parse_mode="HTML",
                    )
                else:
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
            f"🧾 **شماره سفارش:** `{order_id}`\n"
            f"📋 **پلن:** {plan.get('name', 'نامشخص')}\n"
            f"💰 **مبلغ:** {price_formatted} تومان\n"
            f"🔢 **شماره پیگیری / فیش:** `{tracking_code}`\n\n"
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
    """نمایش وضعیت تمام اشتراک‌ها با استعلام مصرف و روزهای مانده زنده از سرور هیدیفای"""
    if not await ensure_user_verified(update, context):
        return CHOOSING

    user = update.effective_user
    try:
        subscriptions = db.get_user_subscriptions(user.id, is_admin_bot=True)
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

    status_msg = await update.message.reply_text("⏳ در حال استعلام لحظه‌ای حجم و روزهای مانده از سرور...")

    vip_info = db.get_user_vip_info(user.id)
    if vip_info.get("is_vip"):
        cb_val = vip_info.get("cashback_percent", 10)
        text = f"👑 <b>سطح حساب شما: کاربر طلایی (⭐️ VIP)</b>\n🎁 <b>پاداش فعال:</b> {cb_val}٪ کش‌بک در هر خرید\n\n📊 <b>وضعیت لحظه‌ای اشتراک‌های شما:</b>\n\n"
    else:
        text = "📊 <b>وضعیت لحظه‌ای اشتراک‌های شما:</b>\n\n"

    for i, sub in enumerate(subscriptions, 1):
        uuid = sub.get("hidify_uuid")
        plan_name = sub.get("plan_name", "نامشخص")
        data_limit = float(sub.get("data_limit") or 0)
        data_used = float(sub.get("data_used") or 0)
        start_date = sub.get("start_date")
        duration = int(sub.get("duration") or 30)
        expire_date = sub.get("expire_date")
        status = sub.get("status", "active")
        account_name = sub.get("account_name") or f"tg_{user.id}"

        # استعلام مستقیم و زنده از سرور هیدیفای
        if uuid:
            try:
                h_user = await hidify.get_user(uuid)
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

                    # بروزرسانی در دیتابیس محلی
                    db.update_subscription_by_uuid(
                        uuid,
                        data_used=data_used,
                        data_limit=data_limit,
                        status=status,
                        start_date=start_date,
                        duration=duration
                    )
            except Exception as e:
                logger.warning(f"Error fetching live user {uuid} from Hiddify: {e}")

        # وضعیت اشتراک
        if status == "active":
            status_icon = "🟢 فعال"
        elif status == "expired":
            status_icon = "🔴 منقضی"
        else:
            status_icon = "⚪ غیرفعال"

        # محاسبه حجم با نوار پیشرفت
        if data_limit > 0:
            remaining_gb = max(0.0, round(data_limit - data_used, 2))
            usage_percent = min((data_used / data_limit) * 100, 100.0)

            bar_length = 10
            filled = min(10, int(usage_percent / 10))
            bar = "█" * filled + "░" * (bar_length - filled)

            if usage_percent >= 90:
                status_emoji = "🔴"
            elif usage_percent >= 70:
                status_emoji = "🟡"
            else:
                status_emoji = "🟢"

            data_text = (
                f"📊 مصرف: **{data_used}** از **{data_limit}** گیگ\n"
                f"   {status_emoji} `{bar}` {usage_percent:.1f}%\n"
                f"   💾 باقیمانده: **{remaining_gb}** گیگابایت"
            )
        else:
            data_text = f"📊 مصرف: **{data_used}** گیگابایت (حجم نامحدود)"

        # محاسبه تاریخ شروع و روزهای باقیمانده
        start_fmt = gregorian_to_shamsi(start_date) if start_date else "نامشخص"
        
        # محاسبه دقیق روزهای مانده
        remaining_days = None
        if start_date and duration:
            try:
                st = datetime.fromisoformat(start_date) if "T" in str(start_date) else datetime.strptime(str(start_date)[:10], "%Y-%m-%d")
                exp = st + timedelta(days=duration)
                expire_fmt = gregorian_to_shamsi(exp.isoformat())
                remaining_days = max(0, (exp.date() - get_now_naive().date()).days)
            except Exception:
                expire_fmt = gregorian_to_shamsi(expire_date) if expire_date else "نامشخص"
                remaining_days = days_remaining_shamsi(expire_date)
        else:
            expire_fmt = gregorian_to_shamsi(expire_date) if expire_date else "نامشخص"
            remaining_days = days_remaining_shamsi(expire_date)

        remaining_text = f" (⏰ **{remaining_days} روز مانده**)" if remaining_days is not None else ""

        # بررسی وجود بسته تمدیدی رزرو در صف
        queue_text = ""
        try:
            queued_items = db.get_pending_queue_items(sub.get("id"))
            if queued_items:
                if len(queued_items) == 1:
                    q = queued_items[0]
                    queue_text = (
                        f"   ⏳ **بسته رزرو (در صف فعال‌سازی خودکار):**\n"
                        f"      📦 پلن: {q.get('plan_name')} ({q.get('data_limit')} گیگ - {q.get('duration')} روز)\n"
                        f"      🔄 زمان فعال‌سازی: پس از مصرف ۹۹٪ حجم یا در روز پایانی اشتراک فعلی\n"
                    )
                else:
                    q_lines = [
                        f"      🔹 **نوبت {idx}:** {q.get('plan_name')} ({q.get('data_limit')} گیگ - {q.get('duration')} روز)"
                        for idx, q in enumerate(queued_items, 1)
                    ]
                    queue_text = (
                        f"   ⏳ **بسته‌های رزرو (در صف فعال‌سازی خودکار - {len(queued_items)} بسته به نوبت):**\n"
                        + "\n".join(q_lines) + "\n"
                        f"      🔄 زمان فعال‌سازی: به ترتیب نوبت پس از اتمام ۹۹٪ حجم یا روز پایانی هر بسته\n"
                    )
        except Exception as e_q:
            logger.debug(f"Error checking pending queue for sub {sub.get('id')}: {e_q}")

        text += (
            f"**{i}. {plan_name}** - {status_icon}\n"
            f"   📝 نام اکانت: `{account_name}`\n"
            f"   {data_text}\n"
            f"   📅 شروع: {start_fmt} | انقضا: {expire_fmt}{remaining_text}\n"
            f"{queue_text}\n"
        )

    try:
        await status_msg.edit_text(text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error sending status: {e}")
        try:
            await update.message.reply_text(text, parse_mode="Markdown")
        except:
            pass
    return CHOOSING


async def show_payments_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش سوابق و گزارش پرداخت‌های مشتری"""
    if not await ensure_user_verified(update, context):
        return CHOOSING

    user = update.effective_user
    try:
        transactions = db.get_user_transactions(user.id)
    except Exception as e:
        logger.error(f"Error getting user transactions: {e}")
        await update.message.reply_text("❌ خطا در دریافت سوابق پرداخت.")
        return CHOOSING

    if not transactions:
        text = (
            "🧾 <b>سوابق و گزارش پرداخت‌ها:</b>\n\n"
            "شما تاکنون هیچ پرداخت یا تراکنشی در ربات ثبت نکرده‌اید.\n\n"
            "💡 برای خرید اشتراک جدید، از دکمه «🛒 خرید اشتراک» استفاده فرمایید."
        )
        if update.callback_query:
            await update.callback_query.edit_message_text(text, parse_mode="HTML")
        else:
            await update.message.reply_text(text, parse_mode="HTML")
        return CHOOSING

    text = f"🧾 <b>سوابق و گزارش پرداخت‌های شما ({len(transactions)} تراکنش):</b>\n\n"

    for i, tx in enumerate(transactions[:10], 1):
        status = tx.get("status", "pending")
        if status in ("approved", "completed"):
            status_badge = "🟢 تایید شده"
        elif status == "pending":
            status_badge = "🟡 در انتظار بررسی"
        elif status == "rejected":
            status_badge = "🔴 رد شده"
        else:
            status_badge = f"⚪ {status}"

        plan_name = tx.get("plan_name") or "خرید اشتراک"
        amount = tx.get("amount", 0)
        try:
            amount_fmt = f"{int(amount):,}"
        except Exception:
            amount_fmt = str(amount)

        order_id = tx.get("order_id") or "---"
        tracking_code = tx.get("tracking_code") or "---"
        gateway = tx.get("gateway", "card_to_card")
        gw_text = "کارت به کارت" if gateway == "card_to_card" else ("درگاه پرداخت" if gateway == "gateway" else gateway)
        created_at = tx.get("created_at", "")
        shamsi_date = gregorian_to_shamsi(created_at) if created_at else "نامشخص"

        text += f"<b>{i}. {plan_name}</b> | {status_badge}\n"
        text += f"   🧾 شماره سفارش: <code>{order_id}</code>\n"
        text += f"   💰 مبلغ: <b>{amount_fmt} تومان</b>\n"
        text += f"   💳 روش: {gw_text}\n"
        if tracking_code and tracking_code != "---":
            text += f"   🔢 کد پیگیری: <code>{tracking_code}</code>\n"
        text += f"   📅 تاریخ: {shamsi_date}\n\n"

    if len(transactions) > 10:
        text += "💡 <i>۱۰ تراکنش اخیر نمایش داده شده است.</i>"

    if update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode="HTML")
    else:
        await update.message.reply_text(text, parse_mode="HTML")
    return CHOOSING


async def get_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دریافت لینک اشتراک‌ها همراه با QR Code و دکمه‌های اتصال مستقیم"""
    if not await ensure_user_verified(update, context):
        return CHOOSING

    user = update.effective_user
    try:
        subscriptions = db.get_user_subscriptions(user.id, is_admin_bot=True)
    except Exception as e:
        logger.error(f"Error getting subscriptions: {e}")
        await update.message.reply_text("❌ خطا در دریافت اطلاعات اشتراک!")
        return CHOOSING

    import_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ افزودن اشتراک قدیمی / قبلی", callback_data="btn_import_sub")]
    ])

    if not subscriptions:
        await update.message.reply_text(
            "❌ شما هنوز اشتراکی ندارید!\n\n"
            "💡 اگر قبلاً خارج از ربات اشتراک تهیه کرده‌اید، می‌توانید با زدن دکمه زیر آن را به حساب خود متصل کنید:",
            reply_markup=import_keyboard
        )
        return CHOOSING

    active_subs = [s for s in subscriptions if s.get("hidify_uuid")]
    if not active_subs:
        await update.message.reply_text(
            "❌ اشتراک فعالی یافت نشد.\n\n"
            "💡 برای اتصال اشتراک‌های قبلی، دکمه زیر را لمس کنید:",
            reply_markup=import_keyboard
        )
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

    # ارسال دکمه افزودن اشتراک قدیمی در انتهای لیست
    await update.message.reply_text(
        "➕ برای افزودن سایر اشتراک‌های خریداری‌شده قبلی، دکمه زیر را لمس کنید:",
        reply_markup=import_keyboard
    )

    return CHOOSING


async def import_sub_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """شروع فرآیند افزودن اشتراک قدیمی خریداری‌شده قبل از ربات"""
    query = update.callback_query
    if query:
        await query.answer()
    
    text = (
        "➕ **افزودن اشتراک خریداری‌شده قبلی**\n\n"
        "لطفاً **لینک سابسکریپشن**، **لینک کانفیگ (VMess / VLESS / Trojan)** یا **کد ۳۶ کاراکتری UUID** اشتراک خود را ارسال نمایید:\n\n"
        "💡 *ربات وجود این اشتراک را در سرور هیدیفای بررسی کرده و در صورت صحت، آن را به حساب شما متصل می‌کند تا بتوانید مشخصات آن را مشاهده یا تمدید نمایید.*"
    )
    keyboard = [[InlineKeyboardButton("◀️ انصراف و بازگشت", callback_data="cancel_import_sub")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if query:
        await query.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")

    return ENTERING_IMPORT_SUB


async def handle_import_sub_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش متن یا لینک ارسالی کاربر برای اتصال اشتراک به حساب"""
    user = update.effective_user
    raw_text = update.message.text.strip() if update.message.text else ""

    if not raw_text:
        await update.message.reply_text("❌ لطفاً لینک یا کد UUID اشتراک را ارسال فرمایید.")
        return ENTERING_IMPORT_SUB

    import re
    import base64
    import json

    extracted_uuid = ""
    # ۱. جستجوی الگوی استاندارد UUID
    uuid_match = re.search(r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}', raw_text)
    if uuid_match:
        extracted_uuid = uuid_match.group(0).lower()
    elif raw_text.startswith("vmess://"):
        try:
            b64_part = raw_text.replace("vmess://", "").strip()
            padded = b64_part + "=" * ((4 - len(b64_part) % 4) % 4)
            obj = json.loads(base64.b64decode(padded).decode("utf-8"))
            if "id" in obj:
                extracted_uuid = str(obj["id"]).strip().lower()
        except Exception:
            pass

    if not extracted_uuid:
        keyboard = [[InlineKeyboardButton("◀️ انصراف", callback_data="cancel_import_sub")]]
        await update.message.reply_text(
            "❌ **شناسه UUID معتبری در متن ارسالی یافت نشد!**\n\n"
            "لطفاً لینک کامل اتصال یا کد ۳۶ کاراکتری UUID را با دقت ارسال فرمایید.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return ENTERING_IMPORT_SUB

    await update.message.reply_text("⏳ در حال استعلام و اعتبارسنجی اشتراک از سرور هیدیفای...")

    # ۲. استعلام از سرور هیدیفای
    try:
        h_user = await hidify.get_user(extracted_uuid)
    except Exception as e:
        logger.error(f"Error checking user in Hiddify: {e}")
        h_user = {"error": str(e)}

    if not h_user or "error" in h_user or not isinstance(h_user, dict) or not h_user.get("uuid"):
        keyboard = [[InlineKeyboardButton("◀️ بازگشت به منو", callback_data="cancel_import_sub")]]
        await update.message.reply_text(
            "❌ **اشتراکی با این مشخصات در سرور هیدیفای یافت نشد!**\n\n"
            "ممکن است این اشتراک حذف یا منقضی شده باشد. لطفاً لینک معتبر ارسال کنید.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return CHOOSING

    # ۳. ثبت و اتصال اشتراک به حساب کاربر
    account_name = h_user.get("name") or f"user_{user.id}"
    data_limit = h_user.get("usage_limit_GB") or 30
    duration = h_user.get("package_days") or 30
    current_usage = h_user.get("current_usage_GB") or 0
    is_active = h_user.get("is_active", True)
    status_str = "active" if is_active else "expired"

    # بررسی و بروزرسانی در دیتابیس
    conn = db.get_connection()
    existing_sub = conn.execute("SELECT * FROM subscriptions WHERE hidify_uuid=?", (extracted_uuid,)).fetchone()
    
    if existing_sub:
        conn.execute("""
            UPDATE subscriptions 
            SET telegram_id=?, account_name=?, data_limit=?, data_used=?, duration=?, status=?, updated_at=?
            WHERE hidify_uuid=?
        """, (user.id, account_name, data_limit, current_usage, duration, status_str, get_now_iso(), extracted_uuid))
    else:
        conn.execute("""
            INSERT INTO subscriptions 
            (telegram_id, hidify_uuid, plan_id, plan_name, account_name, data_limit, data_used, duration, status, created_at, updated_at)
            VALUES (?, ?, 'imported', 'اشتراک متصل‌شده', ?, ?, ?, ?, ?, ?, ?)
        """, (user.id, extracted_uuid, account_name, data_limit, current_usage, duration, status_str, get_now_iso(), get_now_iso()))
    
    conn.commit()
    conn.close()

    # ۴. ارسال کارت اشتراک به مشتری
    sub_url = f"{HIDIFY_PANEL_URL.rstrip('/')}/{USER_PROXY_PATH.strip('/')}/{extracted_uuid}/"
    details = (
        f"✅ **اشتراک با موفقیت به حساب شما متصل شد!**\n\n"
        f"📝 نام اکانت: `{account_name}`\n"
        f"📊 مصرف: {current_usage:.1f} از {data_limit} گیگابایت\n"
        f"⏳ مدت زمان: {duration} روز\n\n"
        f"از این پس می‌توانید این اشتراک را از منوی «🔗 لینک اتصال» دریافت کرده یا از منوی «🔄 تمدید اشتراک» آن را تمدید فرمایید."
    )
    await send_subscription_card(
        context.bot,
        chat_id=user.id,
        sub_url=sub_url,
        title="🎉 **اشتراک شما با موفقیت فعال شد:**",
        details=details
    )

    return CHOOSING


async def renew_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تمدید اشتراک - نمایش اشتراک‌های موجود"""
    if not await ensure_user_verified(update, context):
        return CHOOSING

    user = update.effective_user
    
    # دریافت اشتراک‌های کاربر از دیتابیس
    subscriptions = db.get_user_subscriptions(user.id, is_admin_bot=True)
    
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
            emoji = get_plan_telegram_emoji(plan, plan_id)
            keyboard.append([
                InlineKeyboardButton(
                    f"{emoji} {plan['name']} - {plan['description']} - {price_formatted} تومان",
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
            emoji = get_plan_telegram_emoji(plan, plan_id)
            keyboard.append([
                InlineKeyboardButton(
                    f"{emoji} {plan['name']} - {plan['description']} - {price_formatted} تومان",
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
    
    raw_data = query.data
    extracted_id = raw_data.removeprefix("renew_plan_") if raw_data.startswith("renew_plan_") else raw_data

    plans = get_plans()
    if extracted_id in plans:
        plan_id = extracted_id
    elif raw_data in plans:
        plan_id = raw_data
    elif f"plan_{extracted_id}" in plans:
        plan_id = f"plan_{extracted_id}"
    else:
        matched_id = next((k for k in plans.keys() if k.lower() in [extracted_id.lower(), raw_data.lower()]), None)
        if matched_id:
            plan_id = matched_id
        else:
            await query.edit_message_text("❌ پلن نامعتبر!")
            return CHOOSING
    
    plan = plans[plan_id]
    user = update.effective_user
    sub_id = context.user_data.get("renew_subscription_id")
    
    target_sub = None
    if sub_id:
        user_subscriptions = db.get_user_subscriptions(user.id, is_admin_bot=True)
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
    emoji = get_plan_telegram_emoji(plan, plan_id)

    text = f"""
🔄 **پیش‌فاکتور تمدید اشتراک**

👤 اکانت: `{account_title}`
{emoji} پلن تمدید: **{plan['name']}**
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
            created_by="admin_bot",
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
    if not await ensure_user_verified(update, context):
        return CHOOSING

    user = update.effective_user

    # بررسی آیا قبلاً اشتراک تست گرفته
    user_subscriptions = db.get_user_subscriptions(user.id, is_admin_bot=True)
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
        created_by="admin_bot",
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
    """نمایش داشبورد کیف پول هوشمند کاربر و تراکنش‌ها"""
    user = update.effective_user
    balance = db.get_user_wallet_balance(user.id)
    usdt_equiv = CryptoPaymentGateway.toman_to_usdt(balance, db)
    txs = db.get_wallet_transactions(user.id, limit=5)
    
    tx_lines = ""
    if txs:
        for t_item in txs:
            amt = t_item.get("amount", 0)
            sign = "+" if amt > 0 else ""
            desc = t_item.get("description", "تراکنش")
            date_str = str(t_item.get("created_at", ""))[:10]
            tx_lines += f"• {date_str}: <b>{desc}</b> ({sign}{amt:,} تومان)\n"
    else:
        tx_lines = "<i>هنوز تراکنشی ثبت نشده است.</i>\n"

    webapp_url = db.get_setting("webapp_url", "") or os.getenv("DASHBOARD_URL", "")
    if not webapp_url and os.getenv("RAILWAY_PUBLIC_DOMAIN"):
        webapp_url = f"https://{os.getenv('RAILWAY_PUBLIC_DOMAIN')}"

    vip_info = db.get_user_vip_info(user.id)
    vip_line = ""
    if vip_info.get("is_vip"):
        cb_val = vip_info.get("cashback_percent", 10)
        vip_line = f"👑 سطح عضویت: <b>کاربر طلایی (⭐️ VIP)</b>\n🎁 پاداش کش‌بک: <b>{cb_val}٪</b> بازگشت خودکار در هر خرید\n\n"

    text = f"""
💰 <b>کیف پول و حساب کاربری شما</b>

{vip_line}💳 موجودی ریالی: <b>{balance:,} تومان</b>
💎 معادل تتر (USDT): <b>{usdt_equiv} دلار</b>

📜 <b>آخرین تراکنش‌های شما:</b>
{tx_lines}
💡 <i>با داشتن موجودی در کیف پول، می‌توانید تمام پلن‌ها را در ۱ ثانیه و به صورت آنی فعال کنید.</i>
"""
    
    keyboard = []
    if webapp_url:
        full_app_url = f"{webapp_url.rstrip('/')}/webapp?tg_id={user.id}&r=0"
        keyboard.append([InlineKeyboardButton("📱 باز کردن پنل هوشمند (Mini App)", web_app=WebAppInfo(url=full_app_url))])

    crypto_cfg = CryptoPaymentGateway.get_crypto_config(db)
    charge_row = [InlineKeyboardButton("💳 افزایش موجودی (کارت بانکی)", callback_data="charge_wallet_card")]
    if crypto_cfg.get("enabled"):
        charge_row.append(InlineKeyboardButton("💎 شارژ با تتر/کریپتو", callback_data="charge_wallet_crypto"))
    keyboard.append(charge_row)
    keyboard.append([InlineKeyboardButton("🛒 خرید پلن جدید", callback_data="buy_plan_from_wallet")])
    keyboard.append([InlineKeyboardButton("◀️ بازگشت به منوی اصلی", callback_data="back_to_menu")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        if update.callback_query:
            await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")
        else:
            await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Error showing wallet: {e}")
    return CHOOSING


async def show_webapp_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ارسال دکمه و لینک ورود به مینی‌اپ اختصاصی کاربر"""
    user = update.effective_user
    webapp_url = db.get_setting("webapp_url", "") or os.getenv("DASHBOARD_URL", "")
    if not webapp_url and os.getenv("RAILWAY_PUBLIC_DOMAIN"):
        webapp_url = f"https://{os.getenv('RAILWAY_PUBLIC_DOMAIN')}"

    keyboard = []
    if webapp_url:
        full_app_url = f"{webapp_url.rstrip('/')}/webapp?tg_id={user.id}&r=0"
        keyboard.append([InlineKeyboardButton("📱 ورود به پنل هوشمند (Mini App)", web_app=WebAppInfo(url=full_app_url))])
        keyboard.append([InlineKeyboardButton("🌐 باز کردن در مرورگر", url=full_app_url)])
        text = (
            "📱 <b>پنل کاربری هوشمند (Telegram Mini App)</b>\n\n"
            "با ورود به پنل هوشمند، می‌توانید به امکانات زیر دسترسی داشته باشید:\n\n"
            "• 📊 <b>نمودار زنده مصرف حجم</b> به صورت گیگابایت دقیق\n"
            "• ⏳ <b>روزشمار انقضای اشتراک</b> و وضعیت اتصال\n"
            "• 🚀 <b>دکمه‌های اتصال ۱-کلیکه مستقیم</b> به V2RayNG، Streisand، V2Box و Hiddify\n"
            "• 💰 <b>موجودی کیف پول</b> و تمدید سریع اشتراک"
        )
    else:
        text = "📱 برای استفاده از مینی‌اپ، آدرس دامنه سرور را در پنل وب ثبت نمایید."

    keyboard.append([InlineKeyboardButton("◀️ بازگشت به منوی اصلی", callback_data="back_to_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        if update.callback_query:
            await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")
        else:
            await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Error showing webapp message: {e}")
    return CHOOSING


async def charge_wallet_card_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """راهنمای افزایش موجودی با کارت بانکی"""
    query = update.callback_query
    await query.answer()
    active_card = get_active_card()
    card_number = active_card.get("card_number", CARD_NUMBER)
    card_holder = active_card.get("card_holder", CARD_HOLDER)
    bank_name = active_card.get("bank_name", BANK_NAME)

    text = f"""
💳 <b>افزایش موجودی کیف پول با کارت بانکی</b>

برای شارژ حساب، مبلغ دلخواه خود را به شماره کارت زیر واریز فرمایید:

📌 <b>شماره کارت:</b>
<code>{card_number}</code>
👤 <b>صاحب کارت:</b> {card_holder}
🏦 <b>بانک:</b> {bank_name}

⚠️ <i>پس از واریز، شماره پیگیری یا تصویر رسید را به همراه شناسه کاربری (<code>{query.from_user.id}</code>) به پشتیبانی ارسال فرمایید تا شارژ اعمال شود.</i>
"""
    keyboard = [
        [InlineKeyboardButton("📋 کپی شماره کارت", callback_data=f"copy_card_{card_number}")],
        [InlineKeyboardButton("✍️ ارسال فیش به پشتیبانی", callback_data="ticket_new")],
        [InlineKeyboardButton("◀️ بازگشت به کیف پول", callback_data="back_to_wallet")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")
    return CHOOSING


async def charge_wallet_crypto_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """راهنمای افزایش موجودی با کریپتو / تتر"""
    query = update.callback_query
    await query.answer()
    crypto_cfg = CryptoPaymentGateway.get_crypto_config(db)
    wallet_addr = crypto_cfg.get("wallet_address") or "آدرس ولت تنظیم نشده است"
    usdt_rate = crypto_cfg.get("usdt_rate", 90000)

    text = f"""
💎 <b>افزایش موجودی با ارز دیجیتال (USDT TRC20 / TON)</b>

💵 <b>نرخ محاسبه:</b> هر ۱ تتر = <b>{usdt_rate:,} تومان</b>

📌 <b>آدرس کیف پول تتر TRC20 / TON:</b>
<code>{wallet_addr}</code>

⚠️ <i>پس از واریز، شناسه هش تراکنش (TXID) را به همراه شناسه کاربری (<code>{query.from_user.id}</code>) به پشتیبانی ارسال فرمایید.</i>
"""
    keyboard = [
        [InlineKeyboardButton("✍️ ثبت هش در پشتیبانی", callback_data="ticket_new")],
        [InlineKeyboardButton("◀️ بازگشت به کیف پول", callback_data="back_to_wallet")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")
    return CHOOSING


# ═══════════════════════════════════════════════════════════════════════
# سیستم پشتیبانی
# ═══════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════
# سیستم زیرمجموعه‌گیری و رفرال
# ═══════════════════════════════════════════════════════════════════════

async def referral_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """منوی زیرمجموعه‌گیری و کسب درآمد"""
    if not await ensure_user_verified(update, context):
        return CHOOSING

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
    """منوی پشتیبانی و ارتباط مستقیم با ادمین"""
    if not await ensure_user_verified(update, context):
        return CHOOSING

    text = (
        "💬 <b>مرکز پشتیبانی و ارتباط با مدیریت</b>\n\n"
        "در صورتی که سوال، مشکل در اتصال، نیاز به کانفیگ اختصاصی یا راهنمایی دارید، می‌توانید تیکت ثبت کنید یا مستقیماً با مدیریت در ارتباط باشید:"
    )
    keyboard = [
        [InlineKeyboardButton("✍️ ارسال پیام به پشتیبانی (ثبت تیکت)", callback_data="ticket_new")],
    ]
    if ADMIN_ID and ADMIN_ID != 0:
        keyboard.append([InlineKeyboardButton("💬 گفتگو مستقیم با ادمین", url=f"tg://user?id={ADMIN_ID}")])
    keyboard.append([InlineKeyboardButton("📋 تیکت‌های قبلی من", callback_data="ticket_list")])
    keyboard.append([InlineKeyboardButton("◀️ بازگشت", callback_data="back_to_menu")])

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
        is_vip = db.is_user_vip(user.id)
        header_title = f"🚨 ⭐️ <b>تیکت فوری - کاربر ویژه VIP (#{ticket_id})</b>" if is_vip else f"📨 <b>تیکت پشتیبانی جدید (#{ticket_id})</b>"
        vip_line = "👑 <b>سطح کاربر:</b> ⭐️ کاربر طلایی (VIP) - اولویت پاسخگویی ویژه\n" if is_vip else ""

        admin_text = (
            f"{header_title}\n\n"
            f"{vip_line}"
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

    admin_name = db.get_setting("admin_display_name") or (update.effective_user.first_name if update.effective_user else None) or "مدیریت"
    db.reply_ticket(ticket_id, reply_text, sender_name=admin_name)

    user_id = ticket.get("telegram_id") or ticket.get("user_id")
    try:
        user_msg = (
            f"🔔 <b>پاسخ پشتیبانی به تیکت #{ticket_id}:</b>\n\n"
            f"{reply_text}\n\n"
            f"──────────────\n"
            f"در صورت نیاز به پیام مجدد، از دکمه «💬 پشتیبانی» استفاده کنید."
        )
        if user_id and int(user_id) > 0:
            await context.bot.send_message(chat_id=int(user_id), text=user_msg, parse_mode="HTML")
        await update.message.reply_text(f"✅ پاسخ با موفقیت برای تیکت #{ticket_id} ثبت و ارسال شد.")
    except Exception as e:
        logger.error(f"Error sending ticket reply to user {user_id}: {e}")
        await update.message.reply_text(f"⚠️ پاسخ در دیتابیس ثبت شد اما ارسال به تلگرام با خطا مواجه شد: {e}")

    return CHOOSING


async def admin_ticket_action_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت پاسخ متنی، پاسخ‌های آماده و بستن تیکت از تلگرام برای مدیریت و نماینده"""
    query = update.callback_query
    await query.answer()
    data = query.data
    user = update.effective_user
    is_admin = (user.id == ADMIN_ID or str(user.id) == str(db.get_setting("admin_telegram_id")))
    reseller = db.get_reseller_by_telegram_id(user.id)
    if not is_admin and not reseller:
        await query.answer("⛔ شما دسترسی لازم برای این عملیات را ندارید.", show_alert=True)
        return

    if data.startswith("adm_reply_tkt_") or data.startswith("res_reply_tkt_"):
        prefix = "adm_reply_tkt_" if data.startswith("adm_reply_tkt_") else "res_reply_tkt_"
        ticket_id = int(data.replace(prefix, ""))
        context.user_data["replying_ticket_id"] = ticket_id
        await query.message.reply_text(
            f"✍️ لطفاً متن پاسخ خود برای تیکت <b>#{ticket_id}</b> را ارسال کنید:\n"
            f"(برای انصراف /cancel یا از دستور <code>/reply_ticket {ticket_id} متن پاسخ</code> استفاده نمایید)",
            parse_mode="HTML"
        )
        return ADMIN_REPLYING_TICKET

    elif data.startswith("adm_canned_tkt_") or data.startswith("res_canned_tkt_"):
        is_adm = data.startswith("adm_canned_tkt_")
        prefix = "adm_canned_tkt_" if is_adm else "res_canned_tkt_"
        ticket_id = int(data.replace(prefix, ""))
        
        if is_adm:
            canned_options = [
                (1, "✅ درخواست شما بررسی و تایید شد."),
                (2, "🔄 تغییرات مدنظر بر روی سرورها اعمال گردید."),
                (3, "ℹ️ لطفاً جزئیات و اطلاعات بیشتری ارسال فرمایید."),
                (4, "🛠 اختلال گزارش‌شده در دست بررسی تیم فنی است."),
                (5, "💳 واریزی شما تایید و اعمال گردید.")
            ]
            send_prefix = f"adm_canned_send_{ticket_id}_"
            cancel_cb = f"adm_canned_cancel_{ticket_id}"
        else:
            canned_options = [
                (1, "✅ مشکل شما بررسی و رفع شد."),
                (2, "💳 واریز تمدید شما تایید و اشتراک فعال گردید."),
                (3, "🔄 لطفاً نرم‌افزار را بروز کرده و کانفیگ را آپدیت نمایید."),
                (4, "📊 اشتراک شما بررسی شد و فعال و معتبر است."),
                (5, "⏳ پیام شما در دست بررسی است، به زودی رفع می‌شود.")
            ]
            send_prefix = f"res_canned_send_{ticket_id}_"
            cancel_cb = f"res_canned_cancel_{ticket_id}"

        kb_rows = []
        for idx, text in canned_options:
            kb_rows.append([InlineKeyboardButton(text, callback_data=f"{send_prefix}{idx}")])
        kb_rows.append([InlineKeyboardButton("◀️ انصراف", callback_data=cancel_cb)])
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(kb_rows))

    elif data.startswith("adm_canned_send_") or data.startswith("res_canned_send_"):
        is_adm = data.startswith("adm_canned_send_")
        parts = data.split("_")
        ticket_id = int(parts[3])
        idx = int(parts[4])

        if is_adm:
            canned_map = {
                1: "✅ درخواست شما بررسی و تایید شد.",
                2: "🔄 تغییرات مدنظر بر روی سرورها اعمال گردید.",
                3: "ℹ️ لطفاً جزئیات و اطلاعات بیشتری ارسال فرمایید.",
                4: "🛠 اختلال گزارش‌شده در دست بررسی تیم فنی است.",
                5: "💳 واریزی شما تایید و اعمال گردید."
            }
            sender_type = "admin"
            sender_name = "مدیریت"
            sender_id = 0
        else:
            canned_map = {
                1: "✅ مشکل شما بررسی و رفع شد.",
                2: "💳 واریز تمدید شما تایید و اشتراک فعال گردید.",
                3: "🔄 لطفاً نرم‌افزار را بروز کرده و کانفیگ را آپدیت نمایید.",
                4: "📊 اشتراک شما بررسی شد و فعال و معتبر است.",
                5: "⏳ پیام شما در دست بررسی است، به زودی رفع می‌شود."
            }
            sender_type = "reseller"
            sender_name = (reseller.get("name") if reseller else "پشتیبانی")
            sender_id = (reseller.get("id") if reseller else 0)

        chosen_text = canned_map.get(idx, "پیام بررسی شد.")
        db.add_ticket_message(
            ticket_id=ticket_id,
            sender_type=sender_type,
            message=chosen_text,
            sender_id=sender_id,
            sender_name=sender_name,
            new_status="replied"
        )
        ticket = db.get_ticket(ticket_id)
        cust_tg = ticket.get("telegram_id") or ticket.get("user_id") if ticket else None
        if cust_tg and int(cust_tg) > 0:
            try:
                notif = (
                    f"🔔 <b>پاسخ {sender_name} به تیکت #{ticket_id}:</b>\n\n"
                    f"{chosen_text}\n\n"
                    f"──────────────\n"
                    f"در صورت نیاز به پیام مجدد از بخش پشتیبانی استفاده نمایید."
                )
                await context.bot.send_message(chat_id=int(cust_tg), text=notif, parse_mode="HTML")
            except Exception as e_s:
                logger.error(f"Error sending canned reply: {e_s}")

        orig_text = query.message.text_html or query.message.caption_html or query.message.text or ""
        done_text = f"{orig_text}\n\n✅ <b>پاسخ آماده ارسال شد:</b>\n«{chosen_text}»"
        await edit_admin_message_safe(query, done_text, reply_markup=None, parse_mode="HTML")

    elif data.startswith("adm_canned_cancel_") or data.startswith("res_canned_cancel_"):
        is_adm = data.startswith("adm_canned_cancel_")
        ticket_id = int(data.replace("adm_canned_cancel_" if is_adm else "res_canned_cancel_", ""))
        prefix = "adm" if is_adm else "res"
        orig_kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✍️ پاسخ متنی", callback_data=f"{prefix}_reply_tkt_{ticket_id}"),
                InlineKeyboardButton("⚡ پاسخ‌های آماده", callback_data=f"{prefix}_canned_tkt_{ticket_id}")
            ],
            [
                InlineKeyboardButton("🔒 بستن تیکت", callback_data=f"{prefix}_close_tkt_{ticket_id}")
            ]
        ])
        await query.edit_message_reply_markup(reply_markup=orig_kb)

    elif data.startswith("adm_close_tkt_") or data.startswith("res_close_tkt_"):
        is_adm = data.startswith("adm_close_tkt_")
        ticket_id = int(data.replace("adm_close_tkt_" if is_adm else "res_close_tkt_", ""))
        db.close_ticket(ticket_id)
        orig_text = query.message.text_html or query.message.caption_html or query.message.text or ""
        done_text = f"{orig_text}\n\n🔒 <b>این تیکت با موفقیت بسته شد.</b>"
        await edit_admin_message_safe(query, done_text, reply_markup=None, parse_mode="HTML")


async def admin_quota_action_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تایید یا رد درخواست تغییر سهمیه اشتراک نماینده توسط مدیریت کل در تلگرام"""
    query = update.callback_query
    await query.answer()
    data = query.data
    user = update.effective_user
    if user.id != ADMIN_ID and str(user.id) != str(db.get_setting("admin_telegram_id")):
        await query.answer("❌ شما دسترسی ادمین ندارید!", show_alert=True)
        return

    orig_text = query.message.text_html or query.message.caption_html or query.message.text or ""

    if data.startswith("adm_quota_app_"):
        ticket_id = int(data.replace("adm_quota_app_", ""))
        res = db.approve_quota_change_request(ticket_id, admin_name="مدیریت (تلگرام)")
        if not res.get("success"):
            await query.answer(f"خطا: {res.get('error', 'درخواست قبلاً بررسی شده')}", show_alert=True)
            return

        req_data = res.get("data", {})
        sub_id = res.get("sub_id")
        req_limit = req_data.get("requested_limit")
        req_duration = req_data.get("requested_duration")
        acc_name = req_data.get("account_name", f"user_{sub_id}")
        h_uuid = req_data.get("hidify_uuid")

        if h_uuid:
            try:
                await hidify.update_user(
                    uuid=h_uuid,
                    usage_limit_gb=float(req_limit) if req_limit else None,
                    package_days=int(req_duration) if req_duration else None
                )
            except Exception as e_h:
                logger.error(f"Error updating Hiddify in quota approve callback: {e_h}")

        done_text = f"{orig_text}\n\n✅ <b>درخواست تغییر مشخصات تایید و روی هیدیفای اعمال شد.</b>"
        await edit_admin_message_safe(query, done_text, reply_markup=None, parse_mode="HTML")

        # ارسال پیام به تلگرام نماینده
        ticket = db.get_ticket(ticket_id)
        if ticket and ticket.get("reseller_id"):
            r_info = db.get_reseller(ticket["reseller_id"])
            if r_info and r_info.get("telegram_id"):
                try:
                    await context.bot.send_message(
                        chat_id=r_info["telegram_id"],
                        text=f"✅ <b>درخواست تغییر مشخصات اشتراک شما تایید شد!</b>\n\n"
                             f"📦 اکانت: <code>{acc_name}</code>\n"
                             f"📊 حجم جدید: <b>{req_limit} GB</b>\n"
                             f"⏳ مدت جدید: <b>{req_duration} روز</b>\n"
                             f"🎫 تیکت پیگیری: #{ticket_id}",
                        parse_mode="HTML"
                    )
                except Exception as e_r:
                    logger.error(f"Failed to notify reseller of quota approval: {e_r}")

    elif data.startswith("adm_quota_rej_"):
        ticket_id = int(data.replace("adm_quota_rej_", ""))
        res = db.reject_quota_change_request(ticket_id, reason="رد شده توسط مدیریت از طریق تلگرام", admin_name="مدیریت (تلگرام)")
        done_text = f"{orig_text}\n\n❌ <b>درخواست تغییر مشخصات اشتراک رد شد.</b>"
        await edit_admin_message_safe(query, done_text, reply_markup=None, parse_mode="HTML")

        ticket = db.get_ticket(ticket_id)
        if ticket and ticket.get("reseller_id"):
            r_info = db.get_reseller(ticket["reseller_id"])
            if r_info and r_info.get("telegram_id"):
                try:
                    await context.bot.send_message(
                        chat_id=r_info["telegram_id"],
                        text=f"❌ <b>درخواست تغییر مشخصات اشتراک رد شد.</b>\n\n"
                             f"🎫 تیکت پیگیری: #{ticket_id}\n"
                             f"علت: رد شده توسط مدیریت",
                        parse_mode="HTML"
                    )
                except Exception as e_r:
                    logger.error(f"Failed to notify reseller of quota rejection: {e_r}")


async def admin_order_pay_action_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تایید یا رد آنی پرداخت‌های هوشمند، فیش‌های واریزی و بسته‌های اعتباری توسط مدیریت یا نماینده"""
    query = update.callback_query
    await query.answer()
    data = query.data
    user = update.effective_user
    is_admin = (user.id == ADMIN_ID or str(user.id) == str(db.get_setting("admin_telegram_id")))
    reseller = db.get_reseller_by_telegram_id(user.id)

    if not is_admin and not reseller:
        await query.answer("❌ شما دسترسی لازم برای این عملیات را ندارید!", show_alert=True)
        return

    orig_text = query.message.text_html or query.message.caption_html or query.message.text or ""

    if data.startswith("adm_pay_app_") or data.startswith("res_pay_app_"):
        is_adm = data.startswith("adm_pay_app_")
        order_id = data.replace("adm_pay_app_" if is_adm else "res_pay_app_", "")

        conn = db.get_connection()
        tx_row = conn.execute("SELECT * FROM transactions WHERE order_id=? OR id=?", (order_id, order_id)).fetchone()
        conn.close()

        if not tx_row:
            await query.answer("❌ تراکنش یافت نشد.", show_alert=True)
            return

        tx = dict(tx_row)
        if tx.get("status") == "approved":
            await query.answer("⚠️ این تراکنش قبلاً تایید شده است.", show_alert=True)
            done_text = f"{orig_text}\n\n✅ <b>این تراکنش قبلاً تایید و فعال شده است.</b>"
            await edit_admin_message_safe(query, done_text, reply_markup=None, parse_mode="HTML")
            return

        # ۱. تایید بسته اعتباری نماینده (مخصوص مدیریت)
        if tx.get("gateway") == "bundle_reseller" or str(order_id).startswith("R_BUNDLE"):
            r_id = tx.get("reseller_id")
            amount = tx.get("amount", 0)
            pname = tx.get("plan_name", "بسته اعتباری")
            res_b = db.apply_reseller_bundle_credit(r_id, amount, pname, tx.get("id"))
            db.update_transaction(order_id, status="approved")

            credit_added = res_b.get("credit_added", amount) if isinstance(res_b, dict) else amount
            new_balance = res_b.get("new_balance", 0) if isinstance(res_b, dict) else 0

            if r_id:
                db.add_reseller_notification(
                    reseller_id=r_id,
                    title="تایید رسید خرید بسته اعتباری",
                    message=f"رسید پرداخت شما برای «{pname}» تایید شد و مبلغ {credit_added:,} تومان به کیف پول شما واریز گردید.",
                    type="success"
                )
                r_info = db.get_reseller(r_id)
                if r_info and r_info.get("telegram_id"):
                    try:
                        await context.bot.send_message(
                            chat_id=r_info["telegram_id"],
                            text=(
                                f"✅ <b>فیش واریزی شما تایید شد!</b>\n\n"
                                f"📦 بسته: {pname}\n"
                                f"💳 مبلغ: {amount:,} تومان\n"
                                f"🎁 شارژ شده با بونوس: {credit_added:,} تومان\n"
                                f"💰 موجودی جدید: {new_balance:,} تومان"
                            ),
                            parse_mode="HTML"
                        )
                    except Exception as e_tg:
                        logger.error(f"Error sending msg to reseller {r_id}: {e_tg}")

            done_text = f"{orig_text}\n\n✅ <b>بسته اعتباری نماینده تایید و کیف پول شارژ شد.</b>"
            await edit_admin_message_safe(query, done_text, reply_markup=None, parse_mode="HTML")
            return

        # ۲. تایید خرید یا تمدید اشتراک عادی
        user_id = tx.get("user_id") or 0
        is_renewal = bool(tx.get("is_renewal"))
        renew_sub_id = tx.get("renew_sub_id")
        plan_name = tx.get("plan_name", "پلن")
        plans = get_plans()
        selected_plan = next((p for p in plans.values() if p.get("name") == plan_name), None)
        data_limit = selected_plan.get("data_limit", 30) if selected_plan else 30
        duration = selected_plan.get("duration", 30) if selected_plan else 30

        account_name = tx.get("account_name") or (f"tg_{user_id}" if user_id else f"order_{order_id}")
        sub_url = ""

        # اگر نماینده است، هزینه عمده از کیف پولش کسر شود
        r_id = tx.get("reseller_id")
        if r_id and not is_adm:
            r_stats = db.get_reseller_stats(r_id)
            r_plans = db.get_reseller_plans(r_id)
            r_sel_plan = next((p for p in r_plans if p.get("name") == plan_name or p.get("display_name") == plan_name), None)
            orig_p = r_sel_plan.get("display_price") or tx.get("amount", 0) if r_sel_plan else tx.get("amount", 0)
            master_p = (r_sel_plan.get("master_price") or orig_p) if r_sel_plan else orig_p
            r_discount = r_stats.get("discount_percent", 20)
            wh_p = r_sel_plan.get("wholesale_price") if r_sel_plan and r_sel_plan.get("wholesale_price") else int(master_p * (100 - r_discount) / 100)
            if r_stats["balance"] < wh_p:
                await query.answer(f"❌ موجودی کیف پول کافی نیست! نیاز: {wh_p:,} تومان", show_alert=True)
                return
            db.deduct_reseller_balance(r_id, wh_p, plan_name, account_name, selling_price=orig_p, profit_margin=max(0, orig_p - wh_p), created_by="Telegram Bot")

        if is_renewal and renew_sub_id:
            target_sub = db.get_subscription(renew_sub_id)
            if target_sub:
                user_uuid = target_sub.get("hidify_uuid", "")
                old_limit = float(target_sub.get("data_limit") or 0)
                old_used = float(target_sub.get("data_used") or 0)
                try:
                    await hidify.update_user(
                        uuid=user_uuid,
                        usage_limit_gb=float(data_limit),
                        package_days=int(duration),
                        enable=True
                    )
                except Exception as e_ren:
                    logger.error(f"Error renewing user in Hiddify: {e_ren}")

                db.save_subscription_history(
                    subscription_id=renew_sub_id,
                    telegram_id=user_id or target_sub.get("telegram_id") or 0,
                    hidify_uuid=user_uuid,
                    account_name=account_name,
                    plan_name=plan_name,
                    previous_usage_gb=old_used,
                    previous_limit_gb=old_limit,
                    period_days=duration,
                    renewal_type="direct",
                    reseller_id=target_sub.get("reseller_id")
                )
                db.update_subscription(
                    renew_sub_id,
                    plan_name=plan_name,
                    data_limit=data_limit,
                    duration=duration,
                    data_used=0,
                    status="active"
                )
                if user_uuid:
                    h_url = db.get_setting("hiddify_url") or ""
                    u_proxy = db.get_setting("user_proxy_path") or ""
                    sub_url = f"{h_url}/{u_proxy}/{user_uuid}/"
        else:
            try:
                res_create = await hidify.create_user(
                    name=account_name,
                    usage_limit_gb=float(data_limit) if data_limit > 0 else None,
                    package_days=int(duration),
                    enable=True,
                    comment=str(user_id or f"TG:{order_id}")
                )
                user_uuid = res_create.get("uuid", "")
                sub_url = res_create.get("subscription_url", "")
                if user_uuid:
                    db.save_subscription(
                        telegram_id=user_id,
                        hidify_uuid=user_uuid,
                        plan_id="custom",
                        plan_name=plan_name,
                        data_limit=data_limit,
                        duration=duration,
                        status="active",
                        account_name=account_name,
                        reseller_id=r_id
                    )
            except Exception as e_cr:
                logger.error(f"Error creating user in Hiddify: {e_cr}")

        now_iso = get_now_iso()
        proc_title = "مدیریت (تلگرام)" if is_adm else f"نماینده #{r_id} (تلگرام)"
        conn = db.get_connection()
        conn.execute(
            "UPDATE transactions SET status='approved', processed_by=?, processed_at=?, updated_at=? WHERE order_id=? OR id=?",
            (proc_title, now_iso, now_iso, order_id, order_id)
        )
        conn.commit()
        conn.close()

        if str(order_id).startswith("INV"):
            try:
                db.mark_smart_invoice_paid(order_id, tracking_code=str(tx.get("tracking_code") or order_id))
            except Exception:
                pass

        if user_id and int(user_id) > 0:
            try:
                c_msg = (
                    f"🎉 <b>پرداخت شما تایید شد و اشتراک فعال گردید!</b>\n\n"
                    f"📦 پلن: <b>{plan_name}</b>\n"
                    f"📊 حجم: <b>{data_limit} گیگابایت</b> | ⏳ مدت: <b>{duration} روز</b>\n"
                    + (f"🔗 لینک اشتراک شما:\n<code>{sub_url}</code>\n" if sub_url else "")
                )
                await context.bot.send_message(chat_id=int(user_id), text=c_msg, parse_mode="HTML")
            except Exception as e_not:
                logger.error(f"Failed to notify user of payment approval: {e_not}")

        done_text = f"{orig_text}\n\n✅ <b>پرداخت سفارش {order_id} تایید و اشتراک فعال شد.</b>"
        await edit_admin_message_safe(query, done_text, reply_markup=None, parse_mode="HTML")

    elif data.startswith("adm_pay_rej_") or data.startswith("res_pay_rej_"):
        is_adm = data.startswith("adm_pay_rej_")
        order_id = data.replace("adm_pay_rej_" if is_adm else "res_pay_rej_", "")
        now_iso = get_now_iso()
        proc_title = "مدیریت (تلگرام)" if is_adm else "نماینده (تلگرام)"
        conn = db.get_connection()
        conn.execute(
            "UPDATE transactions SET status='rejected', processed_by=?, processed_at=?, updated_at=? WHERE order_id=? OR id=?",
            (proc_title, now_iso, now_iso, order_id, order_id)
        )
        conn.commit()
        conn.close()

        done_text = f"{orig_text}\n\n❌ <b>پرداخت سفارش {order_id} رد شد.</b>"
        await edit_admin_message_safe(query, done_text, reply_markup=None, parse_mode="HTML")


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
        
        admin_name = db.get_setting("admin_display_name") or (update.effective_user.first_name if update.effective_user else None) or "مدیریت"
        result = db.reply_ticket(ticket_id, reply_text, sender_name=admin_name)
        
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
    if text == "🛒 خرید اشتراک" or "خرید" in text:
        return await show_plans(update, context)
    elif text == "🔄 تمدید اشتراک" or "تمدید" in text:
        return await renew_subscription(update, context)
    elif text == "📊 وضعیت اشتراک" or "وضعیت" in text:
        return await show_status(update, context)
    elif text == "🔗 لینک اتصال" or "لینک" in text:
        return await get_link(update, context)
    elif "کیف پول" in text or text == "💰 کیف پول و موجودی":
        return await show_wallet(update, context)
    elif "پنل هوشمند" in text or "Mini App" in text or "مینی اپ" in text or "مینی‌اپ" in text:
        return await show_webapp_message(update, context)
    elif text == "👥 زیرمجموعه‌گیری" or "زیرمجموعه" in text:
        return await referral_menu(update, context)
    elif text == "💬 پشتیبانی" or "پشتیبانی" in text:
        return await support_menu(update, context)
    elif text == "❓ راهنمای ربات" or text == "📚 آموزش‌ها (بزودی)" or "آموزش" in text or "راهنما" in text:
        return await help_command(update, context)
    elif text == "🧪 اشتراک تست":
        return await handle_test_subscription(update, context)

    is_r_adm, r_id_found, r_role = db.is_telegram_user_any_reseller_admin(user.id)
    reseller = db.get_reseller_by_telegram_id(user.id)
    if not reseller and is_r_adm:
        reseller = db.get_reseller(r_id_found)

    if text == "🔧 پنل مدیریت" and (update.effective_user.id == ADMIN_ID or str(update.effective_user.id) == str(db.get_setting("admin_telegram_id")) or reseller):
        return await admin_panel(update, context)

    # ─── پردازش عملیات متنی مدیریت ارشد (تمدید با جستجو، ساخت اشتراک، کد تخفیف، پیام همگانی) ───
    is_super_admin = (update.effective_user.id == ADMIN_ID or str(update.effective_user.id) == str(db.get_setting("admin_telegram_id")))
    if is_super_admin:
        if context.user_data.get("waiting_adm_search_sub"):
            context.user_data["waiting_adm_search_sub"] = False
            conn = db.get_connection()
            cursor = conn.cursor()
            q = f"%{text.strip()}%"
            cursor.execute("SELECT id, account_name, data_used, data_limit, status FROM subscriptions WHERE (account_name LIKE ? OR phone_number LIKE ? OR telegram_id LIKE ? OR hidify_uuid LIKE ?) AND (is_deleted = 0 OR is_deleted IS NULL) LIMIT 8", (q, q, q, q))
            subs = [dict(r) for r in cursor.fetchall()]
            conn.close()
            if not subs:
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔍 جستجوی مجدد", callback_data="adm_adv_renew_user")],
                    [InlineKeyboardButton("🔙 بازگشت به پنل مدیریت", callback_data="adm_adv_menu")]
                ])
                await update.message.reply_text(f"❌ هیچ اشتراکی با عبارت «{text}» در سامانه یافت نشد.", reply_markup=kb)
                return ADMIN_MENU

            p_msg = f"🔍 **نتایج جستجو برای «{text}» ({len(subs)} مورد):**\n\nجهت انتخاب اشتراک و تمدید روی آن کلیک فرمایید:\n"
            buttons = []
            for s in subs:
                s_id = s["id"]
                s_name = s.get("account_name") or f"sub_{s_id}"
                st_icon = "🟢" if s.get("status") == "active" else "🔴"
                u_gb = round(s.get("data_used", 0), 1)
                l_gb = round(s.get("data_limit", 0), 1)
                buttons.append([InlineKeyboardButton(f"{st_icon} {s_name} ({u_gb}/{l_gb}GB)", callback_data=f"adm_adv_rsub_{s_id}")])
            buttons.append([InlineKeyboardButton("🔙 بازگشت به پنل مدیریت", callback_data="adm_adv_menu")])
            await update.message.reply_text(p_msg, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")
            return ADMIN_MENU

        if context.user_data.get("adm_create_plan_id"):
            plan_id = context.user_data.pop("adm_create_plan_id")
            chosen_name = text.strip()
            if chosen_name.lower() == "auto":
                chosen_name = f"user_{int(datetime.now().timestamp()) % 100000}"
            clean_name = re.sub(r"[^a-zA-Z0-9_\-]", "", chosen_name)
            if not clean_name:
                clean_name = f"user_{int(datetime.now().timestamp()) % 100000}"

            plans = get_all_plans()
            plan = next((p for p in plans if str(p.get("id", "")) == str(plan_id) or str(p.get("plan_id", "")) == str(plan_id)), None)
            if not plan:
                await update.message.reply_text("❌ پلن یافت نشد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="adm_adv_create_user")]]))
                return ADMIN_MENU

            pname = plan.get("name") or plan.get("title", "اشتراک")
            vol = plan.get("data_limit", 30)
            days = plan.get("duration", 30)
            price = plan.get("price", 0)

            uuid_val = None
            try:
                h_res = await hidify_client.create_user(name=clean_name, package_days=int(days), usage_limit_gb=float(vol) if vol > 0 else None, comment=f"[ADMIN_BOT] {clean_name}")
                uuid_val = h_res.get("uuid") if h_res else None
            except Exception as e_h:
                logger.error(f"Error creating user in hidify for admin: {e_h}")

            sub_url = f"{HIDIFY_PANEL_URL}/{HIDIFY_PROXY_PATH}/{uuid_val}/" if uuid_val else f"https://vpn.service/sub/{clean_name}"
            sub_id = db.save_subscription(
                telegram_id=0,
                hidify_uuid=uuid_val,
                plan_id=plan_id,
                plan_name=pname,
                data_limit=float(vol),
                duration=int(days),
                status="active",
                account_name=clean_name,
                account_comment="Created by Admin Bot",
                reseller_id=None,
                created_by="admin_bot"
            )

            def_acc = db.get_customer_default_account("admin", 0)
            if def_acc and price > 0:
                try:
                    db.add_card_transaction(card_id=def_acc['id'], owner_type="admin", tx_type="deposit", amount=price, category="فروش اشتراک", title=f"فروش {clean_name} ({pname}) در ربات", ref_type="subscription", ref_id=str(sub_id), actor="admin_bot")
                except Exception:
                    pass

            qr_bytes = generate_qr_code_bytes(sub_url)
            success_caption = (
                f"🎉 **اشتراک جدید مشتری با موفقیت صادر شد!**\n\n"
                f"👤 نام اکانت: `{clean_name}`\n"
                f"📦 پلن: **{pname}**\n"
                f"📊 حجم: **{vol} گیگابایت** | ⏳ مدت: **{days} روز**\n"
                f"💰 مبلغ پلن: **{price:,} تومان**\n\n"
                f"🔗 **لینک اتصال مشتری (جهت کپی لمس کنید):**\n"
                f"`{sub_url}`"
            )
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("📋 کپی لینک اتصال", copy_text=CopyTextButton(sub_url))],
                [InlineKeyboardButton("🔙 بازگشت به پنل مدیریت", callback_data="adm_adv_menu")]
            ])
            if qr_bytes:
                await update.message.reply_photo(photo=qr_bytes, caption=success_caption, reply_markup=kb, parse_mode="Markdown")
            else:
                await update.message.reply_text(success_caption, reply_markup=kb, parse_mode="Markdown")
            return ADMIN_MENU

        if context.user_data.get("waiting_adm_new_discount_code"):
            context.user_data["waiting_adm_new_discount_code"] = False
            code_text = re.sub(r"[^a-zA-Z0-9_\-]", "", text).upper()
            if not code_text:
                await update.message.reply_text("❌ کد تخفیف باید انگلیسی باشد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="adm_adv_discounts")]]))
                return ADMIN_MENU
            context.user_data["adm_new_discount_name"] = code_text
            context.user_data["waiting_adm_new_discount_pct"] = True
            await update.message.reply_text(
                f"🎁 کد تخفیف: `{code_text}`\n\n"
                f"لطفاً **درصد تخفیف** را به عدد وارد فرمایید (مثلاً `20` برای ۲۰٪):\n"
                f"(برای انصراف /cancel ارسال کنید)",
                parse_mode="Markdown"
            )
            return ADMIN_MENU

        if context.user_data.get("waiting_adm_new_discount_pct"):
            context.user_data["waiting_adm_new_discount_pct"] = False
            code_name = context.user_data.pop("adm_new_discount_name", "OFF")
            try:
                pct = int(re.sub(r"\D", "", text))
            except Exception:
                pct = 10
            pct = max(1, min(100, pct))
            db.create_discount_code(code=code_name, discount_percent=pct, max_uses=0)
            await update.message.reply_text(
                f"✅ **کد تخفیف «{code_name}» با {pct}٪ تخفیف با موفقیت ایجاد و فعال شد.**",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به کدهای تخفیف", callback_data="adm_adv_discounts")]]),
                parse_mode="Markdown"
            )
            return ADMIN_MENU

        if context.user_data.get("waiting_adm_broadcast"):
            context.user_data["waiting_adm_broadcast"] = False
            conn = db.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT telegram_id FROM users WHERE telegram_id > 0")
            user_rows = cursor.fetchall()
            conn.close()

            sent_cnt = 0
            fail_cnt = 0
            for row in user_rows:
                tg_id = row[0]
                try:
                    await context.bot.send_message(chat_id=tg_id, text=text, parse_mode="HTML")
                    sent_cnt += 1
                except Exception:
                    fail_cnt += 1
            await update.message.reply_text(
                f"📢 **نتیجه ارسال پیام همگانی مدیریت:**\n\n"
                f"✅ ارسال موفق به: **{sent_cnt} نفر**\n"
                f"❌ ناموفق (بلاک یا خطا): **{fail_cnt} نفر**",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به پنل مدیریت", callback_data="adm_adv_menu")]]),
                parse_mode="Markdown"
            )
            return ADMIN_MENU

    # پردازش عملیات متنی نمایندگان (تمدید با جستجو، ساخت نام مشتری، کد تخفیف، پیام همگانی و فیش شارژ)
    if reseller:
        r_id = reseller["id"]
        # ۱. جستجوی مشتری جهت تمدید
        if context.user_data.get("waiting_reseller_search_sub"):
            context.user_data["waiting_reseller_search_sub"] = False
            from reseller_bot_admin import search_reseller_subscriptions
            subs = search_reseller_subscriptions(r_id, text)
            if not subs:
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔍 جستجوی مجدد", callback_data="res_adm_renew_user")],
                    [InlineKeyboardButton("🔙 بازگشت به پنل مدیریت", callback_data="res_adm_menu")]
                ])
                await update.message.reply_text(f"❌ هیچ اشتراکی با عبارت «{text}» در پنل شما یافت نشد.", reply_markup=kb)
                return ADMIN_MENU
            
            p_msg = f"🔍 **نتایج جستجو برای «{text}» ({len(subs)} مورد):**\n\nجهت انتخاب اشتراک و تمدید روی آن کلیک فرمایید:\n"
            buttons = []
            for s in subs:
                s_id = s["id"]
                s_name = s.get("account_name") or f"sub_{s_id}"
                st_icon = "🟢" if s.get("status") == "active" else "🔴"
                u_gb = round(s.get("data_used", 0), 1)
                l_gb = round(s.get("data_limit", 0), 1)
                btn_t = f"{st_icon} {s_name} ({u_gb}/{l_gb}GB)"
                buttons.append([InlineKeyboardButton(btn_t, callback_data=f"res_adm_rsub_{s_id}")])
            buttons.append([InlineKeyboardButton("🔙 بازگشت به پنل", callback_data="res_adm_menu")])
            await update.message.reply_text(p_msg, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")
            return ADMIN_MENU

        # ۲. نام دلخواه برای مشتری جدید
        if context.user_data.get("res_create_plan_id"):
            plan_id = context.user_data.pop("res_create_plan_id")
            chosen_name = text.strip()
            if chosen_name.lower() == "auto":
                chosen_name = f"r{r_id}_u{int(datetime.now().timestamp()) % 10000}"
            clean_name = re.sub(r"[^a-zA-Z0-9_\-]", "", chosen_name)
            if not clean_name:
                clean_name = f"r{r_id}_user_{int(datetime.now().timestamp()) % 10000}"
            
            plans_dict = db.get_reseller_plans_dict(r_id)
            plan = plans_dict.get(plan_id)
            if not plan:
                await update.message.reply_text("❌ پلن یافت نشد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="res_adm_create_user")]]))
                return ADMIN_MENU

            wholesale_cost = plan.get("wholesale_price", 0)
            r_stats = db.get_reseller_stats(r_id) or {}
            power = r_stats.get("total_purchasing_power", 0)
            if power < wholesale_cost:
                await update.message.reply_text(
                    f"❌ موجودی و توان خرید شما کافی نیست!\n"
                    f"مبلغ مورد نیاز: {wholesale_cost:,} تومان | توان خرید شما: {power:,} تومان\n"
                    f"لطفاً ابتدا پنل خود را شارژ فرمایید.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💰 خرید شارژ پنل", callback_data="res_adm_bundles")]])
                )
                return ADMIN_MENU

            # کسر هزینه و صدور در هیدیفای
            pname = plan.get("display_name") or plan.get("master_name", "اشتراک")
            vol = plan.get("data_limit", 30)
            days = plan.get("duration", 30)
            
            db.deduct_reseller_balance(r_id, wholesale_cost, pname, clean_name)
            
            # ساخت در هیدیفای
            uuid_val = None
            try:
                from multibot_manager import get_reseller_hidify_client
                r_client = get_reseller_hidify_client(r_id)
                h_res = await r_client.create_user(name=clean_name, package_days=int(days), usage_limit_gb=float(vol) if vol > 0 else None, comment=f"[RESELLER_ID: #{r_id}] {clean_name}")
                uuid_val = h_res.get("uuid") if h_res else None
            except Exception as e_h:
                logger.error(f"Error creating user in hidify for reseller: {e_h}")
                
            sub_url = f"{HIDIFY_PANEL_URL}/{HIDIFY_PROXY_PATH}/{uuid_val}/" if uuid_val else f"https://vpn.service/sub/{clean_name}"
            sub_id = db.save_subscription(
                telegram_id=0,
                hidify_uuid=uuid_val,
                plan_id=plan_id,
                plan_name=pname,
                data_limit=float(vol),
                duration=int(days),
                status="active",
                account_name=clean_name,
                account_comment=f"Reseller #{r_id}",
                reseller_id=r_id,
                created_by="bot_admin"
            )
            
            qr_bytes = generate_qr_code_bytes(sub_url)
            success_caption = (
                f"🎉 **اشتراک مشتری با موفقیت صادر شد!**\n\n"
                f"👤 نام اکانت: `{clean_name}`\n"
                f"📦 پلن: **{pname}**\n"
                f"📊 حجم: **{vol} گیگابایت** | ⏳ مدت: **{days} روز**\n"
                f"💰 هزینه کسر شده از کیف پول شما: **{wholesale_cost:,} تومان**\n\n"
                f"🔗 **لینک اتصال مشتری (جهت کپی لمس کنید):**\n"
                f"`{sub_url}`"
            )
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("📋 کپی لینک اتصال", copy_text=CopyTextButton(sub_url))],
                [InlineKeyboardButton("🔙 بازگشت به پنل مدیریت", callback_data="res_adm_menu")]
            ])
            if qr_bytes:
                await update.message.reply_photo(photo=qr_bytes, caption=success_caption, reply_markup=kb, parse_mode="Markdown")
            else:
                await update.message.reply_text(success_caption, reply_markup=kb, parse_mode="Markdown")
            return ADMIN_MENU

        # ۳. ایجاد کد تخفیف جدید
        if context.user_data.get("waiting_reseller_new_discount_code"):
            context.user_data["waiting_reseller_new_discount_code"] = False
            code_text = re.sub(r"[^a-zA-Z0-9_\-]", "", text).upper()
            if not code_text:
                await update.message.reply_text("❌ کد تخفیف باید انگلیسی باشد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="res_adm_discounts")]]))
                return ADMIN_MENU
            context.user_data["res_new_discount_name"] = code_text
            context.user_data["waiting_reseller_new_discount_pct"] = True
            await update.message.reply_text(
                f"🎁 کد: `{code_text}`\n\n"
                f"لطفاً **درصد تخفیف** را به عدد وارد فرمایید (مثلاً `20` برای ۲۰٪):\n"
                f"(برای انصراف /cancel ارسال کنید)",
                parse_mode="Markdown"
            )
            return ADMIN_MENU

        if context.user_data.get("waiting_reseller_new_discount_pct"):
            context.user_data["waiting_reseller_new_discount_pct"] = False
            code_name = context.user_data.pop("res_new_discount_name", "OFF")
            try:
                pct = int(re.sub(r"\D", "", text))
            except Exception:
                pct = 10
            pct = max(1, min(100, pct))
            db.create_reseller_discount_code(r_id, code_name, discount_percent=pct, max_uses=0)
            await update.message.reply_text(
                f"✅ **کد تخفیف «{code_name}» با {pct}٪ تخفیف با موفقیت ایجاد و فعال شد.**",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به کدهای تخفیف", callback_data="res_adm_discounts")]]),
                parse_mode="Markdown"
            )
            return ADMIN_MENU

        # ۴. پیام همگانی به کاربران
        if context.user_data.get("waiting_reseller_broadcast"):
            context.user_data["waiting_reseller_broadcast"] = False
            conn = db.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT telegram_id FROM users WHERE reseller_id = ? AND telegram_id > 0", (r_id,))
            user_rows = cursor.fetchall()
            conn.close()
            
            sent_cnt = 0
            fail_cnt = 0
            for row in user_rows:
                tg_id = row[0]
                try:
                    await context.bot.send_message(chat_id=tg_id, text=text, parse_mode="HTML")
                    sent_cnt += 1
                except Exception:
                    fail_cnt += 1
            await update.message.reply_text(
                f"📢 **نتیجه ارسال پیام همگانی:**\n\n"
                f"✅ ارسال موفق به: **{sent_cnt} نفر**\n"
                f"❌ ناموفق (بلاک یا خطا): **{fail_cnt} نفر**",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به پنل", callback_data="res_adm_menu")]]),
                parse_mode="Markdown"
            )
            return ADMIN_MENU

        # ۵. ارسال فیش شارژ پنل
        if context.user_data.get("waiting_reseller_bundle_receipt"):
            bundle_id = context.user_data.pop("waiting_reseller_bundle_receipt")
            bundle = db.get_reseller_credit_bundle(bundle_id) or {}
            pname = bundle.get("title", "بسته اعتباری")
            amount = bundle.get("price", 0)
            credit = bundle.get("credit", amount)
            import random
            order_id = f"R_BUNDLE_CARD_{r_id}_{int(datetime.now().timestamp())}_{random.randint(100, 999)}"
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
            
            # اطلاع‌رسانی به ادمین کل
            admin_tg = db.get_setting("admin_telegram_id") or ADMIN_ID
            if admin_tg:
                adm_kb = InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("✅ تایید و شارژ کیف پول", callback_data=f"adm_pay_app_{order_id}"),
                        InlineKeyboardButton("❌ رد فیش", callback_data=f"adm_pay_rej_{order_id}")
                    ]
                ])
                adm_msg = (
                    f"📦 **درخواست شارژ پنل نماینده (کارت به کارت)**\n\n"
                    f"👤 نماینده: **{reseller.get('name') or user.first_name}** (کد #{r_id})\n"
                    f"📋 بسته: **{pname}**\n"
                    f"💰 مبلغ پرداختی: **{amount:,} تومان**\n"
                    f"🎁 اعتبار شارژ: **{credit:,} تومان**\n"
                    f"🔢 فیش / متن: `{text}`\n"
                    f"🆔 کد سفارش: `{order_id}`"
                )
                try:
                    await context.bot.send_message(chat_id=int(admin_tg), text=adm_msg, reply_markup=adm_kb, parse_mode="Markdown")
                except Exception as e_adm:
                    logger.error(f"Failed to notify admin of reseller bundle receipt: {e_adm}")

            await update.message.reply_text(
                f"✅ **رسید پرداخت شما برای بسته «{pname}» با موفقیت ثبت شد.**\n"
                f"پس از بررسی و تایید مدیریت، کیف پول پنل شما به مبلغ **{credit:,} تومان** شارژ خواهد شد.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به پنل مدیریت", callback_data="res_adm_menu")]]),
                parse_mode="Markdown"
            )
            return ADMIN_MENU

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
        await edit_admin_message_safe(query, "❌ داده نامعتبر!")
        return

    user_id = int(parts[0])
    plan_id = parts[1]

    plans = get_plans()
    plan = plans.get(plan_id, {})
    if not plan:
        all_p = get_all_plans()
        plan = all_p.get(plan_id, {})

    # ۱. بررسی تراکنش برای جلوگیری از تایید تکراری (Idempotency / Double-Click Lock)
    user_transactions = db.get_user_transactions(user_id)
    target_tx = None
    for tx in user_transactions:
        if tx.get("status") == "pending" or str(tx.get("plan_id")) == str(plan_id):
            target_tx = tx
            break
    if not target_tx and user_transactions:
        target_tx = user_transactions[0]

    if target_tx and target_tx.get("status") == "approved":
        await query.answer("⚠️ این تراکنش قبلاً تایید و اشتراک آن ساخته شده است!", show_alert=True)
        price_fmt = f"{plan.get('price', 0):,}".replace(",", "،")
        admin_done_text = (
            f"✅ **این اشتراک قبلاً تایید و فعال شده است.**\n\n"
            f"👤 کاربر: `{user_id}`\n"
            f"📋 پلن: {plan.get('name', 'نامشخص')}\n"
            f"💰 مبلغ: {price_fmt} تومان"
        )
        await edit_admin_message_safe(query, admin_done_text)
        return

    username = target_tx.get("account_name") if target_tx and target_tx.get("account_name") else f"tg_{user_id}"
    account_comment = target_tx.get("account_comment") if target_tx else str(user_id)

    # ۲. ساخت اشتراک در Hidify
    try:
        result = await hidify.create_user(
            name=username,
            usage_limit_gb=plan.get("data_limit") if plan.get("data_limit", 0) > 0 else None,
            package_days=plan.get("duration", 30),
            enable=True,
            comment=str(account_comment or user_id)
        )
    except Exception as e:
        logger.error(f"Error creating user in Hiddify: {e}")
        await edit_admin_message_safe(query, f"❌ خطا در ساخت اشتراک:\n{str(e)[:200]}")
        return

    if "error" in result:
        await edit_admin_message_safe(query, f"❌ خطا در ساخت اشتراک در هیدیفای:\n{result['error'][:200]}")
        return

    user_uuid = result.get("uuid", "")
    if not user_uuid:
        await edit_admin_message_safe(query, "❌ خطا: UUID اشتراک از سرور دریافت نشد.")
        return

    # ۳. ذخیره اطلاعات کاربر و اشتراک در دیتابیس
    try:
        user_data = {
            "telegram_id": user_id,
            "username": username,
            "hidify_uuid": user_uuid,
            "plan": plan_id,
            "created_at": get_now_iso(),
            "data_limit": plan.get("data_limit", 0),
        }
        save_user_data(user_id, user_data)

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
            created_by="admin_bot",
        )

        # بروزرسانی وضعیت تراکنش به approved
        if target_tx and target_tx.get("order_id"):
            db.update_transaction(target_tx["order_id"], "approved")
        else:
            pending = db.get_pending_transactions()
            for trans in pending:
                if trans.get("user_id") == user_id:
                    db.update_transaction(trans["order_id"], "approved")
                    break
    except Exception as e:
        logger.error(f"Error saving user/sub in DB: {e}")

    # ۴. پاداش رفرال به معرف در صورت وجود
    try:
        ref_res = db.complete_referral(user_id)
        if ref_res.get("success"):
            ref_id = ref_res["referrer_id"]
            try:
                await context.bot.send_message(
                    chat_id=ref_id,
                    text="🎁 **تبریک!** کاربر معرفی شده توسط شما خرید انجام داد و مبلغ به کیف پول شما واریز شد!",
                    parse_mode="Markdown"
                )
            except Exception:
                pass
    except Exception:
        pass

    # ۵. ویرایش امن پیام ادمین
    price_formatted = f"{plan.get('price', 0):,}".replace(",", "،")
    admin_success_text = (
        f"✅ **اشتراک جدید با موفقیت تایید و فعال شد!**\n\n"
        f"👤 کاربر: `{user_id}`\n"
        f"📋 پلن: {plan.get('name', 'نامشخص')}\n"
        f"📊 حجم: {plan.get('data_limit', 0) if plan.get('data_limit', 0) > 0 else 'نامحدود'} گیگ\n"
        f"💰 مبلغ: {price_formatted} تومان\n"
        f"⏰ مدت: {plan.get('duration', 30)} روز"
    )
    await edit_admin_message_safe(query, admin_success_text)

    # ۶. پیام به کاربر + ارسال کارت اشتراک و QR Code
    plan_data_limit = plan.get('data_limit', 0)
    plan_duration = plan.get('duration', 30)
    data_text = str(plan_data_limit) if plan_data_limit > 0 else 'نامحدود'
    base_url = (HIDIFY_PANEL_URL or "").rstrip("/")
    proxy_path = (USER_PROXY_PATH or HIDIFY_PROXY_PATH or "").strip("/")
    subscription_url = f"{base_url}/{proxy_path}/{user_uuid}/"

    details = (
        f"✅ پرداخت شما تایید شد و اشتراک با موفقیت فعال گردید!\n\n"
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
        await edit_admin_message_safe(query, "❌ داده نامعتبر!")
        return

    user_id = int(parts[0])
    plan_id = parts[1]
    sub_id = int(parts[2])

    plans = get_plans()
    plan = plans.get(plan_id, {})
    if not plan:
        all_p = get_all_plans()
        plan = all_p.get(plan_id, {})
    if not plan:
        await edit_admin_message_safe(query, "❌ پلن مورد نظر یافت نشد!")
        return

    # ۱. بررسی وضعیت تراکنش در دیتابیس برای جلوگیری از تایید تکراری (Idempotency)
    user_transactions = db.get_user_transactions(user_id)
    target_tx = None
    for tx in user_transactions:
        if tx.get("status") == "pending" or tx.get("is_renewal"):
            target_tx = tx
            break
    if not target_tx and user_transactions:
        target_tx = user_transactions[0]

    if target_tx and target_tx.get("status") == "approved":
        await query.answer("⚠️ این تمدید قبلاً تایید و اعمال شده است!", show_alert=True)
        admin_done_text = (
            f"✅ **این تمدید قبلاً تایید و اعمال شده است.**\n\n"
            f"👤 کاربر: `{user_id}`\n"
            f"📋 پلن: {plan.get('name', 'نامشخص')}"
        )
        await edit_admin_message_safe(query, admin_done_text)
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
        await edit_admin_message_safe(query, "❌ UUID اشتراک یافت نشد!")
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
        new_plan_name = plan["name"]
        new_data_limit = plan["data_limit"] if plan["data_limit"] > 0 else None
        new_duration = plan["duration"]
        new_data_used = 0
        new_start_date = get_now_naive().strftime("%Y-%m-%d")
        new_expire_date = (get_now_naive() + timedelta(days=plan["duration"])).isoformat()
        renewal_type = "replace"
    else:
        new_plan_name = (target_sub.get("plan_name") if target_sub and old_data_limit > plan["data_limit"] else plan["name"])
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

    # ثبت در تاریخچه مصرف دوره‌های گذشته
    if target_sub:
        db.save_subscription_history(
            subscription_id=sub_id,
            telegram_id=user_id,
            hidify_uuid=user_uuid,
            account_name=target_sub.get("account_name") or f"tg_{user_id}",
            plan_name=target_sub.get("plan_name") or plan["name"],
            previous_usage_gb=old_data_used,
            previous_limit_gb=old_data_limit,
            period_days=target_sub.get("duration") or plan["duration"],
            renewal_type=renewal_type,
            reseller_id=target_sub.get("reseller_id")
        )

    # ۲. بروزرسانی در Hiddify
    update_payload = {}
    if new_data_limit is not None:
        update_payload["usage_limit_GB"] = new_data_limit
    update_payload["package_days"] = new_duration
    if renewal_type == "replace":
        update_payload["current_usage_GB"] = 0
        if new_start_date:
            update_payload["start_date"] = new_start_date

    try:
        res = await hidify.update_user(user_uuid, **update_payload)
        if "error" in res:
            logger.warning(f"Hidify update user error: {res['error']}")
    except Exception as e:
        logger.error(f"Error updating user in hidify: {e}")
        await edit_admin_message_safe(query, f"❌ خطا در اتصال به هیدیفای:\n{str(e)[:200]}")
        return

    # ۳. بروزرسانی اشتراک در دیتابیس
    if sub_id and target_sub:
        update_fields = {
            "plan_id": plan_id,
            "plan_name": new_plan_name,
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
            plan_name=new_plan_name,
            data_limit=new_data_limit if new_data_limit else 0,
            duration=new_duration,
            data_used=new_data_used,
            status="active",
            account_name=target_sub.get("account_name") if target_sub else f"tg_{user_id}",
            account_comment=target_sub.get("account_comment") if target_sub else None,
            created_by="admin_bot",
        )

    # ۴. بروزرسانی وضعیت تراکنش
    try:
        if target_tx and target_tx.get("order_id"):
            db.update_transaction(target_tx["order_id"], "approved")
        else:
            pending = db.get_pending_transactions()
            for trans in pending:
                if trans.get("user_id") == user_id:
                    db.update_transaction(trans["order_id"], "approved")
                    break
    except Exception as e:
        logger.error(f"Error updating transaction: {e}")

    # ۵. پاداش رفرال به معرف در صورت وجود
    try:
        ref_res = db.complete_referral(user_id)
        if ref_res.get("success"):
            ref_id = ref_res["referrer_id"]
            try:
                await context.bot.send_message(
                    chat_id=ref_id,
                    text="🎁 **تبریک!** کاربر معرفی شده توسط شما تمدید انجام داد و مبلغ به کیف پول شما واریز شد!",
                    parse_mode="Markdown"
                )
            except Exception:
                pass
    except Exception:
        pass

    # ۶. ویرایش امن پیام ادمین
    price_formatted = f"{plan.get('price', 0):,}".replace(",", "،")
    renew_type_fa = "ریست حجم و تمدید مجدد" if renewal_type == "replace" else "افزایش حجم و تمدید مدت"
    admin_success_text = (
        f"✅ **تمدید اشتراک با موفقیت تایید شد!**\n\n"
        f"👤 کاربر: `{user_id}`\n"
        f"📋 پلن: {plan.get('name', 'نامشخص')}\n"
        f"💰 مبلغ: {price_formatted} تومان\n"
        f"🔄 نوع تمدید: {renew_type_fa}"
    )
    await edit_admin_message_safe(query, admin_success_text)

    # ۷. پیام و کارت اشتراک به کاربر
    base_url = (HIDIFY_PANEL_URL or "").rstrip("/")
    proxy_path = (USER_PROXY_PATH or HIDIFY_PROXY_PATH or "").strip("/")
    subscription_url = f"{base_url}/{proxy_path}/{user_uuid}/"
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
        user_transactions = db.get_user_transactions(user_id)
        for trans in user_transactions:
            if trans.get("status") == "pending":
                db.update_transaction(trans["order_id"], "rejected")
                break
    except Exception as e:
        logger.error(f"Error updating transaction: {e}")

    # پیام به ادمین
    await edit_admin_message_safe(
        query,
        f"❌ **تراکنش کاربر `{user_id}` رد شد.**"
    )

    # پیام به کاربر
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text="❌ **رسید پرداخت شما تایید نشد!**\n\n"
                 "💡 در صورت وجود هرگونه مغایرت، از دکمه «💬 پشتیبانی» با ما در ارتباط باشید.",
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.error(f"Error sending reject message to user: {e}")


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
    """پنل مدیریت ادمین کل و نماینده فروش"""
    user = update.effective_user
    is_super_admin = (user.id == ADMIN_ID or str(user.id) == str(db.get_setting("admin_telegram_id")))
    is_r_adm, r_id_found, role = db.is_telegram_user_any_reseller_admin(user.id)
    reseller = db.get_reseller_by_telegram_id(user.id)
    if not reseller and is_r_adm:
        reseller = db.get_reseller(r_id_found)

    if not is_super_admin and not reseller:
        if update.callback_query:
            await update.callback_query.answer("❌ شما دسترسی ادمین یا نمایندگی ندارید!", show_alert=True)
        else:
            await update.message.reply_text("❌ شما دسترسی ادمین یا نمایندگی ندارید!")
        return ConversationHandler.END

    if is_super_admin:
        from admin_bot_admin import get_admin_advanced_keyboard
        text = """👑 **پنل مدیریت ارشد سامانه**

از منوی زیر می‌توانید کلیه امور مدیریتی، مالی، فیش‌های واریزی، کدهای تخفیف، گزارشات و سرور را مدیریت فرمایید:
"""
        reply_markup = get_admin_advanced_keyboard(is_bundle_bot=False)
        if update.callback_query:
            await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
        else:
            await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")
        return ADMIN_MENU

    # ─── پنل اختصاصی مدیریت ربات نماینده (Reseller Admin) ───
    # دکمه‌های پشتیبان‌گیری، بازیابی، مدیریت کارت‌ها و پلن‌ها حذف شده‌اند
    from reseller_bot_admin import get_reseller_admin_keyboard
    r_id = reseller["id"]
    r_name = reseller.get("name") or reseller.get("username") or f"نماینده #{r_id}"
    role_title_map = {
        "main": "ادمین اصلی (دسترسی کامل)",
        "finance": "مدیر مالی و فیش‌ها",
        "support": "پشتیبانی و تیکت‌ها",
        "sales": "کارشناس فروش و اشتراک‌ها"
    }
    role_badge = role_title_map.get(role, "ادمین")
    text = f"""🏢 **پنل مدیریت ربات اختصاصی نماینده**
👤 نماینده: **{r_name}** (شناسه: `{r_id}`)
🎖️ نقش شما: **{role_badge}**

از منوی زیر می‌توانید کلیه امور مدیریتی، مالی و پشتیبانی ربات خود را مدیریت فرمایید:
"""
    reply_markup = get_reseller_admin_keyboard(is_multibot=False, role=role)
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    return ADMIN_MENU


async def admin_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش منوی ادمین و پنل اختصاصی نماینده"""
    query = update.callback_query
    await query.answer()
    data = query.data
    user = update.effective_user
    is_super_admin = (user.id == ADMIN_ID or str(user.id) == str(db.get_setting("admin_telegram_id")))
    is_r_adm, r_id_found, _ = db.is_telegram_user_any_reseller_admin(user.id)
    reseller = db.get_reseller_by_telegram_id(user.id)
    if not reseller and is_r_adm:
        reseller = db.get_reseller(r_id_found)

    if data == "admin_back":
        await query.edit_message_text("❌ پنل مدیریت بسته شد.")
        return ConversationHandler.END

    if data in ("admin_back_menu", "res_adm_menu", "adm_adv_menu"):
        return await admin_panel(update, context)

    # ─── بررسی دسترسی امنیتی دکمه‌های غیرفعال برای نمایندگان ───
    if data in ("admin_cards", "admin_plans", "admin_backup", "admin_restore"):
        if not is_super_admin:
            await query.answer("⛔ این بخش فقط برای مدیریت کل سامانه در دسترس است. تنظیمات کارت‌ها و پلن‌های شما در پنل وب انجام می‌شود.", show_alert=True)
            return ADMIN_MENU

    if data == "admin_cards":
        return await show_cards_menu(update, context)

    if data == "admin_plans":
        return await show_plans_menu(update, context)

    if data in ("admin_stats_btn", "res_adm_stats"):
        return await admin_stats(update, context)

    if data == "admin_backup":
        return await admin_backup_handler(update, context)

    if data == "admin_restore":
        return await admin_restore_handler(update, context)

    # ─── هندلرهای مدیریت پیشرفته ارشد سامانه ───
    if is_super_admin:
        if data == "adm_adv_stats":
            from admin_bot_admin import get_admin_advanced_stats_text
            txt = get_admin_advanced_stats_text()
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به پنل مدیریت", callback_data="adm_adv_menu")]])
            await query.edit_message_text(txt, reply_markup=kb, parse_mode="Markdown")
            return ADMIN_MENU

        elif data in ("adm_adv_payments", "adm_pay_flt_pending", "adm_pay_flt_approved"):
            from admin_bot_admin import get_admin_payments_payload
            flt = "approved" if data == "adm_pay_flt_approved" else "pending"
            txt, kb = get_admin_payments_payload(flt)
            await query.edit_message_text(txt, reply_markup=kb, parse_mode="Markdown")
            return ADMIN_MENU

        elif data.startswith("adm_pay_dtl_"):
            order_id = data.replace("adm_pay_dtl_", "")
            conn = db.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM transactions WHERE order_id=? OR id=?", (order_id, order_id))
            tx_row = cursor.fetchone()
            conn.close()
            if not tx_row:
                await query.answer("❌ سفارش یافت نشد.", show_alert=True)
                return ADMIN_MENU
            tx = dict(tx_row)
            p_text = f"🧾 **جزئیات پرداخت سفارش #{tx.get('id')}**\n\n"
            p_text += f"👤 مشتری: `{tx.get('user_id')}` (@{tx.get('username') or 'ندارد'})\n"
            p_text += f"📦 پلن: **{tx.get('plan_name')}**\n"
            p_text += f"💰 مبلغ: **{tx.get('amount', 0):,} تومان**\n"
            p_text += f"🔢 کد پیگیری/فیش: `{tx.get('tracking_code') or 'ثبت فیش'}`\n"
            p_text += f"📅 تاریخ: {tx.get('created_at', '')[:16].replace('T', ' ')}\n"
            o_id = tx.get("order_id")
            kb = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ تایید فیش و فعال‌سازی", callback_data=f"adm_pay_app_{o_id}"),
                    InlineKeyboardButton("❌ رد فیش پرداخت", callback_data=f"adm_pay_rej_{o_id}"),
                ],
                [InlineKeyboardButton("🔙 بازگشت به پرداخت‌ها", callback_data="adm_adv_payments")]
            ])
            await query.edit_message_text(p_text, reply_markup=kb, parse_mode="Markdown")
            return ADMIN_MENU

        elif data.startswith("adm_pay_app_"):
            order_id = data.replace("adm_pay_app_", "")
            conn = db.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM transactions WHERE order_id=? OR id=?", (order_id, order_id))
            tx_row = cursor.fetchone()
            if tx_row:
                tx = dict(tx_row)
                cursor.execute("UPDATE transactions SET status='approved', updated_at=? WHERE id=?", (get_now_iso(), tx['id']))
                conn.commit()
                def_acc = db.get_customer_default_account("admin", 0)
                if def_acc:
                    try:
                        db.add_card_transaction(card_id=def_acc['id'], owner_type="admin", tx_type="deposit", amount=tx.get('amount', 0), category="فروش اشتراک", title=f"تایید فیش سفارش {order_id}", actor="super_admin")
                    except Exception:
                        pass
                conn.close()
                if tx.get("user_id") and int(tx["user_id"]) > 0:
                    try:
                        await context.bot.send_message(chat_id=int(tx["user_id"]), text=f"✅ فیش پرداخت سفارش شما به مبلغ {tx.get('amount', 0):,} تومان تایید شد.")
                    except Exception:
                        pass
                await query.answer("✅ فیش پرداخت با موفقیت تایید و به موجودی حساب افزوده شد.", show_alert=True)
                from admin_bot_admin import get_admin_payments_payload
                txt, kb = get_admin_payments_payload("pending")
                await query.edit_message_text(txt, reply_markup=kb, parse_mode="Markdown")
            else:
                conn.close()
                await query.answer("❌ سفارش یافت نشد.", show_alert=True)
            return ADMIN_MENU

        elif data.startswith("adm_pay_rej_"):
            order_id = data.replace("adm_pay_rej_", "")
            conn = db.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM transactions WHERE order_id=? OR id=?", (order_id, order_id))
            tx_row = cursor.fetchone()
            if tx_row:
                tx = dict(tx_row)
                cursor.execute("UPDATE transactions SET status='rejected', updated_at=? WHERE id=?", (get_now_iso(), tx['id']))
                conn.commit()
                conn.close()
                if tx.get("user_id") and int(tx["user_id"]) > 0:
                    try:
                        await context.bot.send_message(chat_id=int(tx["user_id"]), text=f"❌ متاسفانه فیش پرداخت سفارش #{order_id} تایید نشد.")
                    except Exception:
                        pass
                await query.answer("❌ فیش پرداخت رد شد.", show_alert=True)
                from admin_bot_admin import get_admin_payments_payload
                txt, kb = get_admin_payments_payload("pending")
                await query.edit_message_text(txt, reply_markup=kb, parse_mode="Markdown")
            else:
                conn.close()
                await query.answer("❌ سفارش یافت نشد.", show_alert=True)
            return ADMIN_MENU

        elif data == "adm_adv_discounts":
            from admin_bot_admin import get_admin_discounts_payload
            txt, kb = get_admin_discounts_payload()
            await query.edit_message_text(txt, reply_markup=kb, parse_mode="Markdown")
            return ADMIN_MENU

        elif data == "adm_disc_create":
            context.user_data["waiting_adm_new_discount_code"] = True
            await query.edit_message_text(
                "🎁 **ایجاد کد تخفیف جدید**\n\n"
                "لطفاً متن کد تخفیف مدنظر خود را با حروف انگلیسی ارسال فرمایید (مثال: `OFF20`):\n"
                "(برای انصراف /cancel ارسال کنید)",
                parse_mode="Markdown"
            )
            return ADMIN_MENU

        elif data.startswith("adm_disc_del_"):
            c_code = data.replace("adm_disc_del_", "")
            db.delete_discount_code(c_code)
            await query.answer(f"🗑️ کد تخفیف {c_code} حذف شد.", show_alert=True)
            from admin_bot_admin import get_admin_discounts_payload
            txt, kb = get_admin_discounts_payload()
            await query.edit_message_text(txt, reply_markup=kb, parse_mode="Markdown")
            return ADMIN_MENU

        elif data == "adm_adv_reports":
            from admin_bot_admin import get_admin_reports_payload
            txt, kb = get_admin_reports_payload()
            await query.edit_message_text(txt, reply_markup=kb, parse_mode="Markdown")
            return ADMIN_MENU

        elif data == "adm_adv_settings":
            from admin_bot_admin import get_admin_settings_overview_payload
            txt, kb = get_admin_settings_overview_payload()
            await query.edit_message_text(txt, reply_markup=kb, parse_mode="Markdown")
            return ADMIN_MENU

        elif data == "adm_adv_broadcast":
            context.user_data["waiting_adm_broadcast"] = True
            await query.edit_message_text(
                "📢 **ارسال پیام همگانی به کلیه کاربران سامانه**\n\n"
                "لطفاً متن پیام مورد نظر را ارسال فرمایید:\n"
                "(برای انصراف /cancel ارسال نمایید)",
                parse_mode="Markdown"
            )
            return ADMIN_MENU

        elif data == "adm_adv_create_user":
            plans = get_all_plans()
            if not plans:
                await query.answer("❌ هیچ پلنی تعریف نشده است.", show_alert=True)
                return ADMIN_MENU
            p_text = "👤 **ساخت اشتراک مشتری جدید**\n\nلطفاً پلن مورد نظر را انتخاب فرمایید:"
            btns = []
            for p in plans:
                pid = p.get("id") or p.get("plan_id")
                pname = p.get("name") or p.get("title") or pid
                price = p.get("price", 0)
                btns.append([InlineKeyboardButton(f"📦 {pname} ({price:,} ت)", callback_data=f"adm_adv_cplan_{pid}")])
            btns.append([InlineKeyboardButton("🔙 بازگشت به پنل مدیریت", callback_data="adm_adv_menu")])
            await query.edit_message_text(p_text, reply_markup=InlineKeyboardMarkup(btns), parse_mode="Markdown")
            return ADMIN_MENU

        elif data.startswith("adm_adv_cplan_"):
            plan_id = data.replace("adm_adv_cplan_", "")
            context.user_data["adm_create_plan_id"] = plan_id
            await query.edit_message_text(
                f"👤 **تنظیم نام اکانت مشتری جدید**\n\n"
                f"لطفاً نام انگلیسی دلخواه برای اکانت مشتری را ارسال فرمایید:\n"
                f"مثال: `client_reza`\n\n"
                f"(برای تولید خودکار نام عبارت `auto` را ارسال کنید یا /cancel برای انصراف)",
                parse_mode="Markdown"
            )
            return ADMIN_MENU

        elif data == "adm_adv_renew_user":
            context.user_data["waiting_adm_search_sub"] = True
            await query.edit_message_text(
                "🔍 **تمدید اشتراک با جستجوی مشتری**\n\n"
                "لطفاً نام اکانت (Account Name)، شماره تلفن، یا آیدی تلگرام مشتری را ارسال فرمایید:\n"
                "(برای انصراف /cancel ارسال نمایید)",
                parse_mode="Markdown"
            )
            return ADMIN_MENU

        elif data.startswith("adm_adv_rsub_"):
            sub_id = int(data.replace("adm_adv_rsub_", ""))
            sub = db.get_subscription(sub_id)
            if not sub:
                await query.answer("❌ اشتراک یافت نشد.", show_alert=True)
                return ADMIN_MENU
            plans = get_all_plans()
            r_name = sub.get("account_name") or f"sub_{sub_id}"
            u_gb = round(sub.get("data_used", 0), 1)
            l_gb = round(sub.get("data_limit", 0), 1)
            p_text = f"🔄 **تمدید اشتراک «{r_name}»**\n\n"
            p_text += f"📊 مصرف فعلی: **{u_gb}GB** از **{l_gb}GB**\n"
            p_text += f"⏰ مدت فعلی: **{sub.get('duration', 30)} روز**\n\n"
            p_text += "لطفاً پلن مورد نظر برای تمدید را انتخاب فرمایید:"
            btns = []
            for p in plans:
                pid = p.get("id") or p.get("plan_id")
                pname = p.get("name") or p.get("title") or pid
                price = p.get("price", 0)
                btns.append([InlineKeyboardButton(f"📦 {pname} ({price:,} ت)", callback_data=f"adm_adv_rnw_{sub_id}_{pid}")])
            btns.append([InlineKeyboardButton("🔙 بازگشت به پنل مدیریت", callback_data="adm_adv_menu")])
            await query.edit_message_text(p_text, reply_markup=InlineKeyboardMarkup(btns), parse_mode="Markdown")
            return ADMIN_MENU

        elif data.startswith("adm_adv_rnw_"):
            parts = data.replace("adm_adv_rnw_", "").split("_", 1)
            sub_id = int(parts[0])
            plan_id = parts[1]
            sub = db.get_subscription(sub_id)
            plans = get_all_plans()
            plan = next((p for p in plans if str(p.get("id", "")) == str(plan_id) or str(p.get("plan_id", "")) == str(plan_id)), None)
            if not sub or not plan:
                await query.answer("❌ اشتراک یا پلن نامعتبر است.", show_alert=True)
                return ADMIN_MENU

            vol = plan.get("data_limit", 30)
            days = plan.get("duration", 30)
            pname = plan.get("name") or plan.get("title", "اشتراک")
            acct_name = sub.get("account_name") or f"sub_{sub_id}"
            price = plan.get("price", 0)

            if sub.get("hidify_uuid"):
                try:
                    await hidify_client.update_user(
                        uuid=sub["hidify_uuid"],
                        package_days=int(days),
                        usage_limit_gb=float(vol) if vol > 0 else None,
                        reset_usage=True
                    )
                except Exception as e_ren:
                    logger.error(f"Error renewing sub in hidify for admin: {e_ren}")

            db.update_subscription(
                sub_id,
                plan_id=plan_id,
                plan_name=pname,
                data_limit=float(vol),
                duration=int(days),
                data_used=0.0,
                status="active"
            )

            def_acc = db.get_customer_default_account("admin", 0)
            if def_acc and price > 0:
                try:
                    db.add_card_transaction(card_id=def_acc['id'], owner_type="admin", tx_type="deposit", amount=price, category="تمدید اشتراک", title=f"تمدید {acct_name} ({pname}) در ربات", ref_type="subscription", ref_id=str(sub_id), actor="admin_bot")
                except Exception:
                    pass

            await query.edit_message_text(
                f"✅ **اشتراک «{acct_name}» با موفقیت تمدید شد!**\n\n"
                f"📦 پلن: **{pname}** ({vol}GB - {days} روز)\n"
                f"🔄 ترافیک مصرفی ریست شد و اعتبار جدید اعمال گردید.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به پنل مدیریت", callback_data="adm_adv_menu")]]),
                parse_mode="Markdown"
            )
            return ADMIN_MENU

    # ─── هندلرهای اختصاصی ابزارهای نماینده در ربات ───
    if reseller:
        r_id = reseller["id"]
        from reseller_bot_admin import (
            get_reseller_bundles_payload,
            get_bundle_payment_details_payload,
            get_reseller_tickets_payload,
            get_reseller_ticket_detail_payload,
            get_reseller_payments_payload,
            get_reseller_create_user_plans_payload,
            get_reseller_discounts_payload,
            get_reseller_reports_payload,
            get_reseller_settings_payload,
        )

        if data == "res_adm_bundles":
            txt, kb = get_reseller_bundles_payload(r_id)
            await query.edit_message_text(txt, reply_markup=kb, parse_mode="Markdown")
            return ADMIN_MENU

        elif data.startswith("res_adm_bdl_"):
            bundle_id = data.replace("res_adm_bdl_", "")
            txt, kb = get_bundle_payment_details_payload(bundle_id, r_id)
            await query.edit_message_text(txt, reply_markup=kb, parse_mode="Markdown")
            return ADMIN_MENU

        elif data.startswith("res_adm_send_rcpt_"):
            bundle_id = data.replace("res_adm_send_rcpt_", "")
            context.user_data["waiting_reseller_bundle_receipt"] = bundle_id
            await query.edit_message_text(
                "📸 **ارسال فیش واریزی شارژ پنل**\n\n"
                "لطفاً تصویر فیش یا متن حاوی کد پیگیری واریز خود را ارسال فرمایید تا جهت تایید برای مدیریت ارشد ارسال گردد:\n"
                "(برای انصراف /cancel ارسال کنید)",
                parse_mode="Markdown"
            )
            return ADMIN_MENU

        elif data == "res_adm_tickets":
            txt, kb = get_reseller_tickets_payload(r_id)
            await query.edit_message_text(txt, reply_markup=kb, parse_mode="Markdown")
            return ADMIN_MENU

        elif data.startswith("res_adm_tkt_"):
            t_id = int(data.replace("res_adm_tkt_", ""))
            txt, kb = get_reseller_ticket_detail_payload(t_id, r_id)
            await query.edit_message_text(txt, reply_markup=kb, parse_mode="Markdown")
            return ADMIN_MENU

        elif data == "res_adm_payments":
            txt, kb = get_reseller_payments_payload(r_id)
            await query.edit_message_text(txt, reply_markup=kb, parse_mode="Markdown")
            return ADMIN_MENU

        elif data.startswith("res_adm_pdetail_"):
            order_id = data.replace("res_adm_pdetail_", "")
            conn = db.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM transactions WHERE order_id=? OR id=?", (order_id, order_id))
            tx_row = cursor.fetchone()
            conn.close()
            if not tx_row:
                await query.answer("❌ سفارش یافت نشد.", show_alert=True)
                return ADMIN_MENU
            tx = dict(tx_row)
            p_text = f"🧾 **جزئیات پرداخت سفارش #{tx.get('id')}**\n\n"
            p_text += f"👤 مشتری: `{tx.get('user_id')}` (@{tx.get('username') or 'ندارد'})\n"
            p_text += f"📦 پلن: **{tx.get('plan_name')}**\n"
            p_text += f"💰 مبلغ: **{tx.get('amount', 0):,} تومان**\n"
            p_text += f"🔢 کد پیگیری/فیش: `{tx.get('tracking_code') or 'ثبت فیش'}`\n"
            p_text += f"📅 تاریخ: {tx.get('created_at', '')[:16].replace('T', ' ')}\n"
            t_uid = tx.get("user_id") or 0
            p_id = tx.get("plan_id") or "plan"
            o_id = tx.get("order_id")
            kb = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ تایید فیش و فعال‌سازی", callback_data=f"res_pay_app_{o_id}"),
                    InlineKeyboardButton("❌ رد فیش پرداخت", callback_data=f"res_pay_rej_{o_id}"),
                ],
                [InlineKeyboardButton("🔙 بازگشت به پرداخت‌ها", callback_data="res_adm_payments")]
            ])
            await query.edit_message_text(p_text, reply_markup=kb, parse_mode="Markdown")
            return ADMIN_MENU

        elif data == "res_adm_create_user":
            txt, kb = get_reseller_create_user_plans_payload(r_id)
            await query.edit_message_text(txt, reply_markup=kb, parse_mode="Markdown")
            return ADMIN_MENU

        elif data.startswith("res_adm_cplan_"):
            plan_id = data.replace("res_adm_cplan_", "")
            context.user_data["res_create_plan_id"] = plan_id
            await query.edit_message_text(
                f"👤 **تنظیم نام اکانت مشتری جدید**\n\n"
                f"لطفاً نام انگلیسی دلخواه برای اکانت مشتری (حروف و اعداد انگلیسی، بدون فاصله) را ارسال فرمایید:\n"
                f"مثال: `user_ahmad`\n\n"
                f"(برای تولید خودکار نام، عبارت `auto` را ارسال کنید یا /cancel برای انصراف)",
                parse_mode="Markdown"
            )
            return ADMIN_MENU

        elif data == "res_adm_renew_user":
            context.user_data["waiting_reseller_search_sub"] = True
            await query.edit_message_text(
                "🔍 **تمدید اشتراک با جستجوی مشتری**\n\n"
                "لطفاً نام اکانت (Account Name)، شماره تلفن یا آیدی تلگرام مشتری را ارسال فرمایید:\n"
                "(برای انصراف /cancel ارسال نمایید)",
                parse_mode="Markdown"
            )
            return ADMIN_MENU

        elif data == "res_adm_discounts":
            txt, kb = get_reseller_discounts_payload(r_id)
            await query.edit_message_text(txt, reply_markup=kb, parse_mode="Markdown")
            return ADMIN_MENU

        elif data.startswith("res_adm_disctog_"):
            d_id = int(data.replace("res_adm_disctog_", ""))
            db.toggle_reseller_discount_code(d_id, r_id)
            txt, kb = get_reseller_discounts_payload(r_id)
            await query.edit_message_text(txt, reply_markup=kb, parse_mode="Markdown")
            return ADMIN_MENU

        elif data.startswith("res_adm_discdel_"):
            d_id = int(data.replace("res_adm_discdel_", ""))
            db.delete_reseller_discount_code(d_id, r_id)
            txt, kb = get_reseller_discounts_payload(r_id)
            await query.edit_message_text(txt, reply_markup=kb, parse_mode="Markdown")
            return ADMIN_MENU

        elif data == "res_adm_disc_new":
            context.user_data["waiting_reseller_new_discount_code"] = True
            await query.edit_message_text(
                "🎁 **ایجاد کد تخفیف جدید**\n\n"
                "لطفاً متن کد تخفیف مدنظر خود را به حروف انگلیسی ارسال فرمایید (مثال: `OFF20`):\n"
                "(برای انصراف /cancel ارسال کنید)",
                parse_mode="Markdown"
            )
            return ADMIN_MENU

        elif data == "res_adm_reports":
            txt, kb = get_reseller_reports_payload(r_id, "menu")
            await query.edit_message_text(txt, reply_markup=kb, parse_mode="Markdown")
            return ADMIN_MENU

        elif data == "res_adm_rep_sales":
            txt, kb = get_reseller_reports_payload(r_id, "sales")
            await query.edit_message_text(txt, reply_markup=kb, parse_mode="Markdown")
            return ADMIN_MENU

        elif data == "res_adm_rep_expiring":
            txt, kb = get_reseller_reports_payload(r_id, "expiring")
            await query.edit_message_text(txt, reply_markup=kb, parse_mode="Markdown")
            return ADMIN_MENU

        elif data == "res_adm_rep_top":
            txt, kb = get_reseller_reports_payload(r_id, "top")
            await query.edit_message_text(txt, reply_markup=kb, parse_mode="Markdown")
            return ADMIN_MENU

        elif data == "res_adm_settings":
            txt, kb = get_reseller_settings_payload(r_id)
            await query.edit_message_text(txt, reply_markup=kb, parse_mode="Markdown")
            return ADMIN_MENU

        elif data.startswith("res_adm_rsub_"):
            sub_id = int(data.replace("res_adm_rsub_", ""))
            sub = db.get_subscription(sub_id)
            if not sub or int(sub.get("reseller_id") or 0) != int(r_id):
                await query.answer("❌ اشتراک یافت نشد یا متعلق به شما نیست.", show_alert=True)
                return ADMIN_MENU
            
            plans = db.get_reseller_plans(r_id)
            r_name = sub.get("account_name") or f"sub_{sub_id}"
            u_gb = round(sub.get("data_used", 0), 1)
            l_gb = round(sub.get("data_limit", 0), 1)
            
            p_text = f"🔄 **تمدید اشتراک «{r_name}»**\n\n"
            p_text += f"📊 مصرف فعلی: **{u_gb}GB** از **{l_gb}GB**\n"
            p_text += f"⏰ مدت فعلی: **{sub.get('duration', 30)} روز**\n\n"
            p_text += "لطفاً پلن مورد نظر برای تمدید را انتخاب فرمایید:"
            
            buttons = []
            for p in plans:
                pid = p["plan_id"]
                pname = p.get("display_name") or p.get("master_name", "پلن")
                vol = p.get("data_limit", 30)
                days = p.get("duration", 30)
                w_price = p.get("wholesale_price", 0)
                vol_str = f"{vol}GB" if vol > 0 else "نامحدود"
                btn_txt = f"📦 {pname} ({vol_str} - {days}روز) | 💰 {w_price:,} ت"
                buttons.append([InlineKeyboardButton(btn_txt, callback_data=f"res_adm_cfren_{sub_id}_{pid}")])
            buttons.append([InlineKeyboardButton("🔙 بازگشت به منوی مدیریت", callback_data="res_adm_menu")])
            await query.edit_message_text(p_text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")
            return ADMIN_MENU

        elif data.startswith("res_adm_cfren_"):
            parts = data.replace("res_adm_cfren_", "").split("_")
            sub_id = int(parts[0])
            plan_id = parts[1]
            sub = db.get_subscription(sub_id)
            if not sub or int(sub.get("reseller_id") or 0) != int(r_id):
                await query.answer("❌ اشتراک نامعتبر است.", show_alert=True)
                return ADMIN_MENU

            plans_dict = db.get_reseller_plans_dict(r_id)
            plan = plans_dict.get(plan_id)
            if not plan:
                await query.answer("❌ پلن یافت نشد.", show_alert=True)
                return ADMIN_MENU

            wholesale_cost = plan.get("wholesale_price", 0)
            r_stats = db.get_reseller_stats(r_id) or {}
            power = r_stats.get("total_purchasing_power", 0)
            if power < wholesale_cost:
                await query.answer(f"❌ توان خرید کافی نیست! مورد نیاز: {wholesale_cost:,} ت", show_alert=True)
                return ADMIN_MENU

            # کسر هزینه و تمدید در هیدیفای
            vol = plan.get("data_limit", 30)
            days = plan.get("duration", 30)
            pname = plan.get("display_name") or plan.get("master_name", "اشتراک")
            acct_name = sub.get("account_name") or f"sub_{sub_id}"
            
            db.deduct_reseller_balance(r_id, wholesale_cost, pname, acct_name)
            
            if sub.get("hidify_uuid"):
                try:
                    from multibot_manager import get_reseller_hidify_client
                    r_client = get_reseller_hidify_client(r_id)
                    await r_client.update_user(
                        uuid=sub["hidify_uuid"],
                        package_days=int(days),
                        usage_limit_gb=float(vol) if vol > 0 else None,
                        reset_usage=True
                    )
                except Exception as e_ren:
                    logger.error(f"Error renewing sub in hidify: {e_ren}")

            db.update_subscription(
                sub_id,
                plan_id=plan_id,
                plan_name=pname,
                data_limit=float(vol),
                duration=int(days),
                data_used=0.0,
                status="active"
            )

            # اطلاع‌رسانی به مشتری اگر تلگرام دارد
            if sub.get("telegram_id") and int(sub["telegram_id"]) > 0:
                try:
                    cust_msg = (
                        f"🎉 **اشتراک شما با موفقیت تمدید شد!**\n\n"
                        f"📦 پلن جدید: **{pname}**\n"
                        f"📊 حجم تمدید شده: **{vol} گیگابایت**\n"
                        f"⏰ اعتبار زمانی: **{days} روز**\n\n"
                        f"اتصال شما مجدداً فعال گردید. سپاس از همراهی شما! 🌹"
                    )
                    await context.bot.send_message(chat_id=int(sub["telegram_id"]), text=cust_msg, parse_mode="Markdown")
                except Exception:
                    pass

            await query.edit_message_text(
                f"✅ **اشتراک «{acct_name}» با موفقیت تمدید شد!**\n\n"
                f"📦 پلن: **{pname}** ({vol}GB - {days} روز)\n"
                f"💰 هزینه کسر شده از موجودی پنل: **{wholesale_cost:,} تومان**\n"
                f"🔄 ترافیک مصرفی ریست شد و اعتبار جدید اعمال گردید.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به پنل مدیریت", callback_data="res_adm_menu")]]),
                parse_mode="Markdown"
            )
            return ADMIN_MENU

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
            emoji = get_plan_telegram_emoji(plan, plan_id)
            status = "🟢" if plan.get("is_active") else "🔴"
            price_formatted = f"{plan['price']:,}".replace(",", "،")
            text += f"{status} `{plan_id}`\n"
            text += f"  {emoji} {plan['name']}\n"
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
            status_text = "🟢 فعال" if plan.get("is_active") else "🔴 غیرفعال"
            data_text = f"{plan.get('data_limit', 0)} گیگ" if plan.get('data_limit', 0) > 0 else "نامحدود"
            text = (
                f"⚙️ **مدیریت و ویرایش پلن:**\n\n"
                f"🆔 شناسه: `{plan_id}`\n"
                f"📋 نام پلن: **{plan['name']}**\n"
                f"💰 قیمت: **{price_formatted}** تومان\n"
                f"📊 حجم: **{data_text}**\n"
                f"⏰ مدت: **{plan.get('duration', 30)}** روز\n"
                f"📌 وضعیت: {status_text}\n\n"
                f"برای ویرایش هر بخش، دکمه مربوطه را لمس کنید:"
            )
            keyboard = [
                [
                    InlineKeyboardButton("🆔 ویرایش شناسه", callback_data=f"plan_field_id_{plan_id}"),
                    InlineKeyboardButton("✏️ ویرایش نام", callback_data=f"plan_field_name_{plan_id}"),
                ],
                [
                    InlineKeyboardButton("💰 ویرایش قیمت", callback_data=f"plan_field_price_{plan_id}"),
                    InlineKeyboardButton("📊 ویرایش حجم", callback_data=f"plan_field_data_{plan_id}"),
                ],
                [
                    InlineKeyboardButton("⏰ ویرایش مدت", callback_data=f"plan_field_duration_{plan_id}"),
                    InlineKeyboardButton("🔄 فعال / غیرفعال", callback_data=f"toggle_plan_{plan_id}"),
                ],
                [
                    InlineKeyboardButton("🗑️ حذف پلن", callback_data=f"del_plan_{plan_id}"),
                    InlineKeyboardButton("🔙 بازگشت به لیست", callback_data="admin_plans"),
                ],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
        return ADMIN_PLANS_MENU

    if query.data.startswith("plan_field_"):
        data = query.data.replace("plan_field_", "")
        parts = data.split("_", 1)
        if len(parts) < 2:
            return ADMIN_PLANS_MENU
        field_type = parts[0]
        plan_id = parts[1]
        plans = get_all_plans()
        if plan_id not in plans:
            await query.answer("❌ پلن یافت نشد!", show_alert=True)
            return ADMIN_PLANS_MENU

        context.user_data["editing_plan_id"] = plan_id
        context.user_data["editing_plan_field"] = field_type

        prompts = {
            "id": "🆔 **شناسه جدید پلن را وارد کنید (انگلیسی بدون فاصله):**\n\nمثال: `vip_100gb_1m` یا `plan_30days`",
            "name": "✏️ **نام جدید پلن را وارد کنید:**\n\nمثال: `پلن ۱ ماهه ۱۰۰ گیگ VIP`",
            "price": "💰 **قیمت جدید پلن (به تومان) را وارد کنید:**\n\nمثال: `150000` (برای رایگان عدد `0` وارد کنید)",
            "data": "📊 **حجم جدید پلن (به گیگابایت) را وارد کنید:**\n\nمثال: `50` (برای نامحدود عدد `0` وارد کنید)",
            "duration": "⏰ **مدت زمان جدید پلن (تعداد روز) را وارد کنید:**\n\nمثال: `30` یا `60` یا `365`",
        }
        prompt_text = prompts.get(field_type, "لطفاً مقدار جدید را وارد کنید:")
        keyboard = [[InlineKeyboardButton("◀️ انصراف و بازگشت", callback_data=f"edit_plan_{plan_id}")]]
        await query.edit_message_text(prompt_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        return ADMIN_EDIT_PLAN_VALUE

    if query.data.startswith("toggle_plan_"):
        plan_id = query.data.replace("toggle_plan_", "")
        plans = get_all_plans()
        if plan_id in plans:
            current_status = plans[plan_id].get("is_active", False)
            update_plan(plan_id, is_active=not current_status)
            status = "فعال" if not current_status else "غیرفعال"
            await query.answer(f"پلن {status} شد! ✅", show_alert=True)
            # نمایش مجدد کارت همان پلن
            return await plans_menu_handler_show_card(query, plan_id)
        return await show_plans_menu(update, context)

    if query.data.startswith("del_plan_"):
        plan_id = query.data.replace("del_plan_", "")
        result = delete_plan(plan_id)
        if result.get("success"):
            await query.answer("پلن با موفقیت حذف شد! 🗑️", show_alert=True)
        else:
            await query.answer(f"خطا: {result.get('error')}", show_alert=True)
        return await show_plans_menu(update, context)

    return ADMIN_PLANS_MENU


async def plans_menu_handler_show_card(query, plan_id: str):
    """نمایش مجدد کارت ویرایش پلن"""
    plans = get_all_plans()
    if plan_id in plans:
        plan = plans[plan_id]
        price_formatted = f"{plan['price']:,}".replace(",", "،")
        status_text = "🟢 فعال" if plan.get("is_active") else "🔴 غیرفعال"
        data_text = f"{plan.get('data_limit', 0)} گیگ" if plan.get('data_limit', 0) > 0 else "نامحدود"
        text = (
            f"⚙️ **مدیریت و ویرایش پلن:**\n\n"
            f"🆔 شناسه: `{plan_id}`\n"
            f"📋 نام پلن: **{plan['name']}**\n"
            f"💰 قیمت: **{price_formatted}** تومان\n"
            f"📊 حجم: **{data_text}**\n"
            f"⏰ مدت: **{plan.get('duration', 30)}** روز\n"
            f"📌 وضعیت: {status_text}\n\n"
            f"برای ویرایش هر بخش، دکمه مربوطه را لمس کنید:"
        )
        keyboard = [
            [
                InlineKeyboardButton("🆔 ویرایش شناسه", callback_data=f"plan_field_id_{plan_id}"),
                InlineKeyboardButton("✏️ ویرایش نام", callback_data=f"plan_field_name_{plan_id}"),
            ],
            [
                InlineKeyboardButton("💰 ویرایش قیمت", callback_data=f"plan_field_price_{plan_id}"),
                InlineKeyboardButton("📊 ویرایش حجم", callback_data=f"plan_field_data_{plan_id}"),
            ],
            [
                InlineKeyboardButton("⏰ ویرایش مدت", callback_data=f"plan_field_duration_{plan_id}"),
                InlineKeyboardButton("🔄 فعال / غیرفعال", callback_data=f"toggle_plan_{plan_id}"),
            ],
            [
                InlineKeyboardButton("🗑️ حذف پلن", callback_data=f"del_plan_{plan_id}"),
                InlineKeyboardButton("🔙 بازگشت به لیست", callback_data="admin_plans"),
            ],
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    return ADMIN_PLANS_MENU


async def edit_plan_value_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دریافت و ذخیره مقدار جدید برای فیلدهای پلن (شناسه، نام، قیمت، حجم، مدت)"""
    text_val = update.message.text.strip()
    plan_id = context.user_data.get("editing_plan_id")
    field = context.user_data.get("editing_plan_field")

    if not plan_id or not field:
        await update.message.reply_text("❌ خطایی رخ داد. لطفاً از پنل مدیریت دوباره اقدام کنید.")
        return ADMIN_MENU

    plans = get_all_plans()
    if plan_id not in plans:
        await update.message.reply_text("❌ پلن مورد نظر یافت نشد.")
        return ADMIN_MENU

    update_kwargs = {}
    if field == "id":
        new_id = text_val.strip().lower().replace(" ", "_")
        import re
        if not re.match(r"^[a-zA-Z0-9_-]+$", new_id):
            await update.message.reply_text("❌ شناسه باید فقط شامل حروف انگلیسی، اعداد و خط فاصله/آندرلاین باشد. دوباره وارد کنید:")
            return ADMIN_EDIT_PLAN_VALUE
        if new_id != plan_id and new_id in plans:
            await update.message.reply_text("❌ این شناسه پلن قبلاً ثبت شده است! شناسه دیگری وارد کنید:")
            return ADMIN_EDIT_PLAN_VALUE
        update_kwargs["new_plan_id"] = new_id

    elif field == "name":
        if len(text_val) < 2:
            await update.message.reply_text("❌ نام پلن باید حداقل ۲ حرف باشد. لطفاً دوباره ارسال کنید:")
            return ADMIN_EDIT_PLAN_VALUE
        update_kwargs["name"] = text_val

    elif field == "price":
        try:
            val = int(text_val.replace(",", "").replace("،", ""))
            if val < 0:
                raise ValueError()
            update_kwargs["price"] = val
        except Exception:
            await update.message.reply_text("❌ قیمت نامعتبر است! لطفاً یک عدد صحیح به تومان وارد کنید:")
            return ADMIN_EDIT_PLAN_VALUE

    elif field == "data":
        try:
            val = int(text_val)
            if val < 0:
                raise ValueError()
            update_kwargs["data_limit"] = val
        except Exception:
            await update.message.reply_text("❌ حجم نامعتبر است! لطفاً عدد گیگابایت (مثلاً 50 یا 0 برای نامحدود) وارد کنید:")
            return ADMIN_EDIT_PLAN_VALUE

    elif field == "duration":
        try:
            val = int(text_val)
            if val < 1:
                raise ValueError()
            update_kwargs["duration"] = val
        except Exception:
            await update.message.reply_text("❌ مدت زمان نامعتبر است! لطفاً تعداد روز (مثلاً 30) را وارد کنید:")
            return ADMIN_EDIT_PLAN_VALUE

    res = update_plan(plan_id, **update_kwargs)
    if res.get("success"):
        current_plan_id = res.get("plan_id", plan_id)
        plans = get_all_plans()
        plan = plans[current_plan_id]
        price_formatted = f"{plan['price']:,}".replace(",", "،")
        status_text = "🟢 فعال" if plan.get("is_active") else "🔴 غیرفعال"
        data_text = f"{plan.get('data_limit', 0)} گیگ" if plan.get('data_limit', 0) > 0 else "نامحدود"

        msg_text = (
            f"✅ **پلن با موفقیت بروزرسانی شد!**\n\n"
            f"🆔 شناسه: `{current_plan_id}`\n"
            f"📋 نام: **{plan['name']}**\n"
            f"💰 قیمت: **{price_formatted}** تومان\n"
            f"📊 حجم: **{data_text}**\n"
            f"⏰ مدت: **{plan.get('duration', 30)}** روز\n"
            f"📌 وضعیت: {status_text}"
        )
        keyboard = [
            [
                InlineKeyboardButton("🆔 ویرایش شناسه", callback_data=f"plan_field_id_{current_plan_id}"),
                InlineKeyboardButton("✏️ ویرایش نام", callback_data=f"plan_field_name_{current_plan_id}"),
            ],
            [
                InlineKeyboardButton("💰 ویرایش قیمت", callback_data=f"plan_field_price_{current_plan_id}"),
                InlineKeyboardButton("📊 ویرایش حجم", callback_data=f"plan_field_data_{current_plan_id}"),
            ],
            [
                InlineKeyboardButton("⏰ ویرایش مدت", callback_data=f"plan_field_duration_{current_plan_id}"),
                InlineKeyboardButton("🔄 فعال / غیرفعال", callback_data=f"toggle_plan_{current_plan_id}"),
            ],
            [
                InlineKeyboardButton("🗑️ حذف پلن", callback_data=f"del_plan_{current_plan_id}"),
                InlineKeyboardButton("🔙 بازگشت به لیست", callback_data="admin_plans"),
            ],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(msg_text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await update.message.reply_text(f"❌ خطا در بروزرسانی پلن: {res.get('error')}")

    context.user_data.pop("editing_plan_id", None)
    context.user_data.pop("editing_plan_field", None)
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
    """آمار ربات برای ادمین کل و نماینده"""
    user = update.effective_user
    is_super_admin = (user.id == ADMIN_ID or str(user.id) == str(db.get_setting("admin_telegram_id")))
    reseller = db.get_reseller_by_telegram_id(user.id)

    if not is_super_admin and not reseller:
        if update.callback_query:
            await update.callback_query.answer("❌ شما دسترسی ادمین ندارید!", show_alert=True)
        else:
            await update.message.reply_text("❌ شما دسترسی ادمین ندارید!")
        return

    # ─── آمار اختصاصی نماینده فروش (بدون بکاپ‌ها و کاملاً ایزوله) ───
    if reseller and not is_super_admin:
        from reseller_bot_admin import get_reseller_stats_text
        text = get_reseller_stats_text(reseller["id"])
        keyboard = [[InlineKeyboardButton("🔙 بازگشت به پنل مدیریت", callback_data="admin_back_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        if update.callback_query:
            await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
        else:
            await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")
        return ADMIN_MENU

    # دریافت آمار کل سامانه از دیتابیس (برای مدیریت ارشد)
    stats = db.get_stats()
    total_users = stats.get("total_users", 0)
    total_subs = stats.get("total_subscriptions", 0)
    active_subs = stats.get("active_subscriptions", 0)
    pending = stats.get("pending_transactions", 0)
    completed = stats.get("completed_transactions", 0)
    rejected = stats.get("rejected_transactions", 0)
    total_revenue = stats.get("total_revenue", 0)

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
        if active_cards == 0:
            db_cards = db.get_all_bank_cards()
            active_cards = len([c for c in db_cards if c.get("is_active")])
    except:
        active_plans = active_cards = 0

    revenue_formatted = f"{total_revenue:,}".replace(",", "،")
    # سطر تعداد بکاپ‌ها طبق درخواست حذف شد
    text = f"""
📊 **آمار دقیق سامانه و ربات**

👥 **کاربران تلگرام:** {total_users}
🌐 **کاربران سرور هیدیفای:** {hidify_users}
🛡 **اشتراک‌های فعال:** {active_subs} (از کل {total_subs})

📦 **پلن‌های فعال:** {active_plans} پلن
💳 **کارت‌های بانکی فعال:** {active_cards} کارت

💰 **وضعیت تراکنش‌ها:**
• ⏳ در انتظار تایید: {pending}
• ✅ تایید شده: {completed}
• ❌ رد شده: {rejected}

💵 **مجموع درآمد:** {revenue_formatted} تومان
"""

    keyboard = [[InlineKeyboardButton("🔙 بازگشت به پنل مدیریت", callback_data="admin_back_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # ارسال پاسخ (چه از دکمه چه از دستور)
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    return ADMIN_MENU


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


async def sync_hidify_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """همگام‌سازی و بازیابی خودکار کاربران و اشتراک‌ها از پنل هیدیفای"""
    user = update.effective_user
    if user.id != ADMIN_ID:
        await update.message.reply_text("❌ شما ادمین نیستید!")
        return

    msg = await update.message.reply_text("⏳ در حال دریافت اطلاعات کاربران از پنل هیدیفای...")
    try:
        h_users = await hidify.get_users()
        if not h_users or not isinstance(h_users, list):
            err = h_users.get("error") if isinstance(h_users, dict) else "خطای دریافت لیست کاربران"
            await msg.edit_text(f"❌ خطا در اتصال به هیدیفای:\n{err}")
            return

        res = db.sync_from_hidify(h_users)
        if res.get("success"):
            await msg.edit_text(
                f"✅ **همگام‌سازی با هیدیفای با موفقیت انجام شد!**\n\n"
                f"📊 کل کاربران در هیدیفای: **{res.get('total_hiddify', 0)}**\n"
                f"👥 کاربران جدید بازیابی‌شده: **{res.get('restored_users', 0)}**\n"
                f"📋 اشتراک‌های جدید/بروزرسانی‌شده: **{res.get('restored_subs', 0)}**\n\n"
                f"اطلاعات دیتابیس با موفقیت بروزرسانی شد.",
                parse_mode="Markdown"
            )
        else:
            await msg.edit_text(f"❌ خطا در ثبت اطلاعات دیتابیس:\n{res.get('error')}")
    except Exception as e:
        logger.error(f"Error in sync_hidify_command: {e}")
        await msg.edit_text(f"❌ خطا در پردازش:\n{str(e)}")


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


async def dynamic_main_menu_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مسیریابی هوشمند و داینامیک تمام کلیدهای منوی اصلی بر اساس تنظیمات پنل مدیریت"""
    if not update.message or not update.message.text:
        return CHOOSING
    text = update.message.text.strip()
    user = update.effective_user

    # بررسی پنل ادمین
    if user.id == ADMIN_ID and ("مدیریت" in text or "admin" in text.lower() or "پنل" in text):
        return await admin_panel(update, context)

    btn = db.match_bot_menu_button(text)
    if btn:
        b_id = btn.get("id")
        is_enabled = btn.get("is_enabled", True)
        if not is_enabled:
            dis_msg = btn.get("disabled_message") or "⚠️ این بخش موقتاً غیرفعال می‌باشد."
            await update.message.reply_text(dis_msg)
            return CHOOSING

        if b_id == "buy":
            return await show_plans(update, context)
        elif b_id == "my_subs":
            return await show_status(update, context)
        elif b_id == "test_sub":
            return await handle_test_subscription(update, context)
        elif b_id == "renew":
            return await renew_subscription(update, context)
        elif b_id == "wallet":
            bal = db.get_user_wallet_balance(user.id)
            vip_info = db.get_user_vip_info(user.id)
            vip_txt = ""
            if vip_info.get("is_vip"):
                cb = vip_info.get("cashback_percent", 10)
                vip_txt = f"\n👑 <b>سطح حساب:</b> مشتری طلایی (⭐️ VIP)\n🎁 <b>پاداش کش‌بک:</b> {cb}٪ بازگشت وجه در هر خرید\n"
            await update.message.reply_text(f"💳 <b>موجودی کیف پول شما:</b> <code>{bal:,}</code> تومان{vip_txt}", parse_mode="HTML")
            return CHOOSING
        elif b_id == "support":
            return await support_menu(update, context)
        elif b_id in ("tutorials", "troubleshoot"):
            custom_tutorial = db.get_setting("tutorial_domain")
            custom_troubleshoot = db.get_setting("troubleshoot_domain")
            dashboard_url = os.getenv("DASHBOARD_URL", "").rstrip("/")

            if custom_tutorial:
                tutorial_url = f"https://{custom_tutorial}" if not str(custom_tutorial).startswith("http") else str(custom_tutorial)
            elif dashboard_url:
                tutorial_url = f"{dashboard_url}/help"
            else:
                tutorial_url = "http://127.0.0.1:5000/help"

            if custom_troubleshoot:
                troubleshoot_url = f"https://{custom_troubleshoot}" if not str(custom_troubleshoot).startswith("http") else str(custom_troubleshoot)
            else:
                troubleshoot_url = f"{tutorial_url.rstrip('/')}/troubleshoot"

            guide_text = (
                "📖 <b>مرکز آموزش و راهنمای جامع اتصال</b>\n\n"
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
            await update.message.reply_text(guide_text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="HTML")
            return CHOOSING
        elif b_id == "referral":
            return await referral_menu(update, context)
        elif b_id == "payments":
            return await show_payments_history(update, context)
        elif b_id == "language":
            return await change_language_prompt(update, context)

    return CHOOSING


def main():
    """راه‌اندازی ربات"""
    # بررسی متغیرهای محیطی
    if not check_env_variables():
        logger.error("Bot cannot start due to missing environment variables!")
        print("ERROR: Missing environment variables. Check .env file.")
        return
    
    # بازیابی خودکار جامع دیتابیس (جداول، تنظیمات، کارت‌ها و پلن‌ها)
    restore_result = db.auto_restore_full()
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

    # هندلرهای دکمه‌های منوی اصلی (Keyboard) با پشتیبانی از ۴ زبان
    main_menu_handlers = [
        MessageHandler(filters.CONTACT, handle_contact),
        MessageHandler(filters.Regex(get_all_lang_regex("btn_buy")), show_plans),
        MessageHandler(filters.Regex(get_all_lang_regex("btn_test")), handle_test_subscription),
        MessageHandler(filters.Regex(get_all_lang_regex("btn_renew")), renew_subscription),
        MessageHandler(filters.Regex(get_all_lang_regex("btn_status")), show_status),
        MessageHandler(filters.Regex(get_all_lang_regex("btn_link")), get_link),
        MessageHandler(filters.Regex(get_all_lang_regex("btn_payments")), show_payments_history),
        MessageHandler(filters.Regex(get_all_lang_regex("btn_referral")), referral_menu),
        MessageHandler(filters.Regex(get_all_lang_regex("btn_support")), support_menu),
        MessageHandler(filters.Regex(get_all_lang_regex("btn_language")), change_language_prompt),
        MessageHandler(filters.Regex(get_all_lang_regex("btn_admin")), admin_panel),
        MessageHandler(filters.TEXT & ~filters.COMMAND, dynamic_main_menu_router),
    ]

    # Conversation Handler برای فرآیند خرید، تمدید، پشتیبانی و پنل ادمین
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CommandHandler("language", change_language_prompt),
            CommandHandler("lang", change_language_prompt),
            CommandHandler("admin_panel", admin_panel),
            CommandHandler("renew", renew_subscription),
            CommandHandler("status", show_status),
            CommandHandler("link", get_link),
            CommandHandler("payments", show_payments_history),
            CallbackQueryHandler(select_language_callback, pattern="^lang_"),
            CallbackQueryHandler(ticket_new_prompt, pattern="^ticket_new$"),
            CallbackQueryHandler(ticket_list, pattern="^ticket_list$"),
            CallbackQueryHandler(import_sub_start, pattern="^btn_import_sub$"),
            CallbackQueryHandler(handle_renew, pattern="^renew_"),
            CallbackQueryHandler(admin_reply_ticket_callback, pattern="^admin_reply_ticket_"),
            CallbackQueryHandler(admin_ticket_action_callback, pattern="^(adm_reply_tkt_|adm_canned_tkt_|adm_canned_send_|adm_canned_cancel_|adm_close_tkt_|res_reply_tkt_|res_canned_tkt_|res_canned_send_|res_canned_cancel_|res_close_tkt_)"),
            CallbackQueryHandler(admin_quota_action_callback, pattern="^(adm_quota_app_|adm_quota_rej_)"),
            CallbackQueryHandler(admin_order_pay_action_callback, pattern="^(adm_pay_app_|adm_pay_rej_|res_pay_app_|res_pay_rej_)"),
        ] + main_menu_handlers,
        states={
            CHOOSING: [
                CallbackQueryHandler(select_language_callback, pattern="^lang_"),
                CallbackQueryHandler(single_link_callback, pattern="^single_link_"),
                CallbackQueryHandler(ticket_new_prompt, pattern="^ticket_new$"),
                CallbackQueryHandler(ticket_list, pattern="^ticket_list$"),
                CallbackQueryHandler(import_sub_start, pattern="^btn_import_sub$"),
                CallbackQueryHandler(handle_renew, pattern="^renew_"),
                CallbackQueryHandler(back_to_menu, pattern="^back_to_menu$"),
                CallbackQueryHandler(admin_reply_ticket_callback, pattern="^admin_reply_ticket_"),
                CallbackQueryHandler(admin_ticket_action_callback, pattern="^(adm_reply_tkt_|adm_canned_tkt_|adm_canned_send_|adm_canned_cancel_|adm_close_tkt_|res_reply_tkt_|res_canned_tkt_|res_canned_send_|res_canned_cancel_|res_close_tkt_)"),
                CallbackQueryHandler(admin_quota_action_callback, pattern="^(adm_quota_app_|adm_quota_rej_)"),
                CallbackQueryHandler(admin_order_pay_action_callback, pattern="^(adm_pay_app_|adm_pay_rej_|res_pay_app_|res_pay_rej_)"),
                CallbackQueryHandler(copy_link_callback, pattern="^copy_link$"),
                CallbackQueryHandler(wizard_callback_handler, pattern="^wiz_"),
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
                CallbackQueryHandler(handle_payment_method, pattern="^(pay_card|pay_wallet|pay_wallet_insufficient|pay_crypto|pay_online|pay_online_gateway|coming_soon|coming_soon_gateway|copy_card_.*|copy_rial_.*|copy_amount_.*|back_to_confirm_purchase|back_to_select_payment|cancel)$"),
                CallbackQueryHandler(back_to_confirm_purchase, pattern="^back_to_confirm_purchase$"),
                CallbackQueryHandler(back_to_menu, pattern="^back_to_menu$"),
                CallbackQueryHandler(cancel, pattern="^cancel$"),
            ] + main_menu_handlers,
            ENTERING_TRACKING_CODE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, enter_tracking_code),
                MessageHandler(filters.PHOTO, enter_tracking_photo),
                MessageHandler(filters.Document.ALL, enter_tracking_document),
                CallbackQueryHandler(copy_card_callback, pattern="^copy_card_"),
                CallbackQueryHandler(copy_rial_callback, pattern="^copy_rial_"),
                CallbackQueryHandler(copy_amount_callback, pattern="^copy_amount_"),
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
            ENTERING_IMPORT_SUB: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_import_sub_text),
                CallbackQueryHandler(back_to_menu, pattern="^(cancel_import_sub|back_to_menu|cancel)$"),
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
            ADMIN_EDIT_PLAN_VALUE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_plan_value_handler),
                CallbackQueryHandler(plans_menu_handler),
                CallbackQueryHandler(back_to_menu, pattern="^back_to_menu$"),
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
    application.add_handler(CommandHandler("payments", show_payments_history))
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
    application.add_handler(CommandHandler("sync_hidify", sync_hidify_command))
    application.add_handler(CommandHandler("sync", sync_hidify_command))

    # هندلر دریافت مستقیم فایل دیتابیس از ادمین برای بازیابی
    application.add_handler(MessageHandler(filters.Document.ALL & filters.User(ADMIN_ID), handle_restore_file))

    # هندلر بررسی عضویت کانال
    async def handle_check_membership(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        user = update.effective_user
        
        is_member = await check_channel_membership(user.id, context)
        if is_member:
            user_lang = db.get_user_language(user.id)
            await query.edit_message_text("✅ " + t("choose_option", user_lang))
            reply_markup = get_main_keyboard(user.id, ADMIN_ID, user_lang)
            welcome_text = t("welcome_msg", user_lang, name=user.first_name)
            if user.id == ADMIN_ID:
                welcome_text += f"• {t('btn_admin', user_lang)}\n"
            welcome_text += f"\n{t('choose_option', user_lang)}"
            await context.bot.send_message(
                chat_id=user.id,
                text=welcome_text,
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
        else:
            await show_join_channels_message(update, context)
    
    application.add_handler(CallbackQueryHandler(handle_check_membership, pattern="^check_membership$"))
    application.add_handler(CommandHandler("language", change_language_prompt))
    application.add_handler(CommandHandler("lang", change_language_prompt))
    application.add_handler(CallbackQueryHandler(select_language_callback, pattern="^lang_"))
    application.add_handler(CallbackQueryHandler(single_link_callback, pattern="^single_link_"))
    application.add_handler(CallbackQueryHandler(copy_link_callback, pattern="^copy_link$"))

    # دکمه‌های کیف پول و مینی‌اپ
    application.add_handler(CallbackQueryHandler(show_wallet, pattern="^back_to_wallet$"))
    application.add_handler(CallbackQueryHandler(charge_wallet_card_callback, pattern="^charge_wallet_card$"))
    application.add_handler(CallbackQueryHandler(charge_wallet_crypto_callback, pattern="^charge_wallet_crypto$"))
    application.add_handler(CallbackQueryHandler(show_plans, pattern="^buy_plan_from_wallet$"))
    application.add_handler(CallbackQueryHandler(show_webapp_message, pattern="^open_sub_"))

    # دکمه‌های اینلاین پشتیبانی
    application.add_handler(CallbackQueryHandler(ticket_new_prompt, pattern="^ticket_new$"))
    application.add_handler(CallbackQueryHandler(ticket_list, pattern="^ticket_list$"))
    application.add_handler(CallbackQueryHandler(admin_reply_ticket_callback, pattern="^admin_reply_ticket_"))
    application.add_handler(CallbackQueryHandler(admin_ticket_action_callback, pattern="^(adm_reply_tkt_|adm_canned_tkt_|adm_canned_send_|adm_canned_cancel_|adm_close_tkt_|res_reply_tkt_|res_canned_tkt_|res_canned_send_|res_canned_cancel_|res_close_tkt_)"))
    application.add_handler(CallbackQueryHandler(admin_quota_action_callback, pattern="^(adm_quota_app_|adm_quota_rej_)"))
    application.add_handler(CallbackQueryHandler(admin_order_pay_action_callback, pattern="^(adm_pay_app_|adm_pay_rej_|res_pay_app_|res_pay_rej_)"))

    # هندلرهای تایید و رد پرداخت ادمین
    application.add_handler(CallbackQueryHandler(admin_approve_renew, pattern="^admin_approve_renew_"))
    application.add_handler(CallbackQueryHandler(admin_approve_payment, pattern="^admin_approve_"))
    application.add_handler(CallbackQueryHandler(admin_reject_payment, pattern="^admin_reject_"))

    # ویزارد تعاملی قدم‌به‌قدم عیب‌یابی و آموزش اتصال
    application.add_handler(CallbackQueryHandler(wizard_callback_handler, pattern="^wiz_"))

    # هندلر پیام‌های متنی
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # ─── راه‌اندازی پشتیبان‌گیری خودکار ───
    backup_scheduler = AutoBackupScheduler(admin_id=ADMIN_ID)
    
    # ─── راه‌اندازی سیستم اعلان‌ها ───
    notif_scheduler = NotificationScheduler(hidify=hidify)
    
    async def post_init(application):
        """تنظیمات بعد از شروع application"""
        try:
            me = await application.bot.get_me()
            if me and me.username:
                db.set_setting("bot_username", me.username.lstrip("@"))
                logger.info(f"Admin Bot username detected and saved: @{me.username}")
        except Exception as e_me:
            logger.warning(f"Could not fetch bot username in post_init: {e_me}")

        backup_scheduler.set_bot(application.bot)
        await backup_scheduler.start()
        logger.info("Auto backup scheduler started")
        
        # شروع سیستم اعلان‌ها
        notif_scheduler.set_bot(application.bot)
        await notif_scheduler.start()
        logger.info("Notification scheduler started")

        # راه‌اندازی دکمه ثابت مینی‌اپ تلگرام (MenuButtonWebApp)
        try:
            from telegram_menu_helper import setup_telegram_chat_menu_button
            await setup_telegram_chat_menu_button(application.bot, reseller_id=0)
            logger.info("Admin bot Telegram Mini App menu button configured in post_init.")
        except Exception as e_menu:
            logger.warning(f"Could not setup menu button in post_init: {e_menu}")

        # همگام‌سازی و بازیابی خودکار کاربران از پنل هیدیفای در زمان استارت
        try:
            logger.info("Syncing users and subscriptions from Hiddify panel on startup...")
            h_users = await hidify.get_users()
            if h_users and isinstance(h_users, list):
                res = db.sync_from_hidify(h_users)
                logger.info(f"Startup Hiddify sync result: {res}")
            else:
                logger.warning(f"Could not fetch users from Hiddify on startup: {h_users}")
        except Exception as e:
            logger.warning(f"Could not auto-sync from Hiddify on startup: {e}")
    
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
