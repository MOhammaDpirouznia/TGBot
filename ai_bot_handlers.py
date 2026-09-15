"""
ماژول مشترک هندلرهای بات تلگرام برای استودیو هوش مصنوعی، اتوماسیون محتوا و صف بررسی
(AI Bot Handlers for Admin Bot, Reseller Bots, and Bundle Sales Bot)
"""

import html
import json
import logging
from typing import Tuple, Optional, Dict, Any, List

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from database import db
from ai_marketing_manager import ai_marketing
from utils import get_now_iso

logger = logging.getLogger("ai_bot_handlers")


def get_ai_studio_main_text(bot_type: str = "admin", owner_id: int = 0) -> str:
    """متن منوی اصلی استودیو هوش مصنوعی برای بات تلگرام"""
    settings = db.get_ai_marketing_settings(bot_type=bot_type, owner_id=owner_id)
    queue = db.get_ai_content_queue(bot_type=bot_type, owner_id=owner_id, status="pending_approval")
    pending_count = len(queue)

    provider = settings.get("provider", "gemini")
    model = settings.get("model_name", "gemini-1.5-flash")
    channel = settings.get("target_channel") or "تنظیم نشده"
    insta = settings.get("instagram_page") or "تنظیم نشده"

    return f"""🤖 **استودیو و دستیار محتوای هوش مصنوعی (AI Studio)**

🧠 **موتور فعال:** `{provider}` ({model})
📢 **کانال مقصد:** `{channel}`
📸 **پیج اینستاگرام:** `{insta}`
⏳ **اقلام در صف بررسی و تایید:** **{pending_count}** مورد

💡 **ویژگی نظارت و بازبینی:**
تمامی مطالب و نظرسنجی‌های تولید شده، ابتدا در **صف بررسی** ذخیره می‌شوند تا بتوانید قبل از ارسال به کانال، متن آن‌ها را چک کرده یا موارد ناخواسته را حذف نمایید.

لطفاً یکی از گزینه‌های زیر را انتخاب کنید:"""


def get_ai_studio_keyboard(bot_type: str = "admin", owner_id: int = 0) -> InlineKeyboardMarkup:
    """کیبورد اصلی استودیو هوش مصنوعی در بات تلگرام"""
    queue = db.get_ai_content_queue(bot_type=bot_type, owner_id=owner_id, status="pending_approval")
    q_count = len(queue)
    back_cb = "adm_adv_menu" if bot_type == "admin" else "res_adm_menu"

    keyboard = [
        [
            InlineKeyboardButton("📢 تولید پست کانال (تلگرام)", callback_data="ai_m_post"),
            InlineKeyboardButton("📊 ساخت نظرسنجی کانال", callback_data="ai_m_poll"),
        ],
        [
            InlineKeyboardButton("📸 پکیج اینستاگرام (کپشن+استوری)", callback_data="ai_m_insta"),
            InlineKeyboardButton("🎁 کمپین تخفیف تعاملی", callback_data="ai_m_disc"),
        ],
        [
            InlineKeyboardButton(f"📋 صف بررسی و تایید محتوا ({q_count} مورد)", callback_data="ai_m_queue"),
        ],
        [
            InlineKeyboardButton("⚙️ تنظیمات هوش مصنوعی و کانال", callback_data="ai_m_settings"),
            InlineKeyboardButton("🔙 بازگشت به منوی مدیریت", callback_data=back_cb),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_ai_queue_payload(bot_type: str = "admin", owner_id: int = 0) -> Tuple[str, InlineKeyboardMarkup]:
    """دریافت لیست اقلام صف بررسی در بات تلگرام همراه با دکمه‌های تایید و حذف"""
    queue = db.get_ai_content_queue(bot_type=bot_type, owner_id=owner_id, status="pending_approval")
    back_cb = "adm_ai_menu" if bot_type == "admin" else "res_ai_menu"

    if not queue:
        text = """📋 **صف بررسی و نظارت محتوا (Approval Queue)**

✅ در حال حاضر هیچ محتوایی در انتظار تایید وجود ندارد!

از منوی استودیو می‌توانید پست، نظرسنجی یا کمپین تخفیف جدید تولید کنید."""
        keyboard = [
            [InlineKeyboardButton("✍️ تولید محتوای جدید", callback_data="ai_m_post")],
            [InlineKeyboardButton("🔙 بازگشت به استودیو هوش مصنوعی", callback_data=back_cb)]
        ]
        return text, InlineKeyboardMarkup(keyboard)

    text = f"📋 **صف بررسی و تایید محتوا ({len(queue)} مورد در انتظار):**\n\n"
    keyboard = []

    for item in queue[:5]:
        i_id = item["id"]
        c_type = item.get("content_type", "post")
        type_icon = "📢 پست" if c_type == "post" else ("📊 نظرسنجی" if c_type == "poll" else "🎁 تخفیف")
        title = item.get("title") or "بدون عنوان"
        snippet = (item.get("content_text") or "")[:90].replace("\n", " ")
        dest = item.get("target_destination") or "کانال پیش‌فرض"

        text += f"🔹 **#{i_id}** [{type_icon}] {title}\n"
        text += f"🎯 مقصد: `{dest}`\n"
        text += f"📝 خلاصه: _{snippet}..._\n\n"

        keyboard.append([
            InlineKeyboardButton(f"✅ تایید و ارسال فوری #{i_id}", callback_data=f"ai_q_app_{i_id}"),
            InlineKeyboardButton(f"❌ حذف #{i_id}", callback_data=f"ai_q_del_{i_id}")
        ])

    keyboard.append([InlineKeyboardButton("🔙 بازگشت به استودیو هوش مصنوعی", callback_data=back_cb)])
    return text, InlineKeyboardMarkup(keyboard)


def get_ai_post_topics_keyboard(bot_type: str = "admin") -> InlineKeyboardMarkup:
    """کیبورد موضوعات آماده برای تولید سریع پست کانال"""
    back_cb = "adm_ai_menu" if bot_type == "admin" else "res_ai_menu"
    keyboard = [
        [InlineKeyboardButton("⚡ راهنمای رفع قطعی و کندی V2Ray", callback_data="ai_tp_v2ray")],
        [InlineKeyboardButton("🛡️ آموزش پروتکل Reality و Sing-box", callback_data="ai_tp_reality")],
        [InlineKeyboardButton("🔒 نکات امنیت حریم خصوصی و ضد فیلتر", callback_data="ai_tp_security")],
        [InlineKeyboardButton("🌐 معرفی لوکیشن‌های جدید و پینگ گیمینگ", callback_data="ai_tp_gaming")],
        [InlineKeyboardButton("🔙 بازگشت به استودیو", callback_data=back_cb)]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_ai_discount_presets_keyboard(bot_type: str = "admin") -> InlineKeyboardMarkup:
    """کیبورد کمپین‌های تخفیف آماده تعاملی"""
    back_cb = "adm_ai_menu" if bot_type == "admin" else "res_ai_menu"
    keyboard = [
        [InlineKeyboardButton("🎁 تخفیف ۲۰٪ قدردانی و رفع اختلالات", callback_data="ai_dc_20")],
        [InlineKeyboardButton("🔥 تخفیف ۳۰٪ جشنواره وفاداری مشترکین", callback_data="ai_dc_30")],
        [InlineKeyboardButton("⚡ تخفیف ۱۵٪ تمدید سریع اشتراک‌ها", callback_data="ai_dc_15")],
        [InlineKeyboardButton("🔙 بازگشت به استودیو", callback_data=back_cb)]
    ]
    return InlineKeyboardMarkup(keyboard)


async def handle_ai_bot_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    bot_type: str = "admin",
    owner_id: int = 0
) -> bool:
    """
    پردازشگر جامع کال‌بک‌های استودیو هوش مصنوعی در بات تلگرام
    خروجی: True در صورت پردازش، False در صورتی که دیتای کال‌بک مربوط به این بخش نباشد.
    """
    query = update.callback_query
    if not query or not query.data:
        return False

    data = query.data
    back_menu_cb = "adm_ai_menu" if bot_type == "admin" else "res_ai_menu"

    # منوی اصلی استودیو هوش مصنوعی
    if data in ("adm_ai_menu", "res_ai_menu"):
        text = get_ai_studio_main_text(bot_type=bot_type, owner_id=owner_id)
        kb = get_ai_studio_keyboard(bot_type=bot_type, owner_id=owner_id)
        await query.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
        return True

    # صفحه صف بررسی
    if data == "ai_m_queue":
        text, kb = get_ai_queue_payload(bot_type=bot_type, owner_id=owner_id)
        await query.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
        return True

    # منوی انتخاب موضوع پست
    if data == "ai_m_post":
        text = """📢 **تولید پست آموزشی و تحلیلی برای کانال تلگرام**

لطفاً یکی از موضوعات آماده زیر را انتخاب کنید تا هوش مصنوعی بلافاصله پست آماده همراه با نکات فنی و هشتگ‌ها را تدوین و در **صف بررسی** قرار دهد:"""
        kb = get_ai_post_topics_keyboard(bot_type=bot_type)
        await query.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
        return True

    # تولید بر اساس موضوع انتخابی
    if data.startswith("ai_tp_"):
        topic_key = data.replace("ai_tp_", "")
        topic_titles = {
            "v2ray": "راهنمای رفع قطعی و تنظیم کلاینت v2rayNG در ساعات شلوغی",
            "reality": "آموزش تنظیم پروتکل‌های نوین Reality و Sing-box ضد اختلال",
            "security": "نکات امنیتی جلوگیری از نشت اطلاعات و حفظ امنیت فردی در وب",
            "gaming": "معرفی سرورهای اختصاصی گیمینگ با حداقل پینگ و UDP پایدار"
        }
        topic = topic_titles.get(topic_key, "راهنمای عبور از محدودیت‌های اینترنتی")

        await query.answer("⏳ هوش مصنوعی در حال نگارش پست است...", show_alert=False)
        settings = db.get_ai_marketing_settings(bot_type=bot_type, owner_id=owner_id)
        target = settings.get("target_channel") or ""

        res = ai_marketing.generate_channel_post(
            topic=topic,
            tone=settings.get("default_tone", "informative"),
            target_channel=target,
            signature=settings.get("signature", ""),
            custom_settings=settings
        )

        item_id = db.create_ai_content_item(
            bot_type=bot_type,
            owner_id=owner_id,
            content_type="post",
            platform="telegram_channel",
            target_destination=target,
            title=res.get("title", topic),
            content_text=res.get("post_text", ""),
            status="pending_approval",
            created_by="telegram_bot"
        )

        preview_text = f"""✅ **پست با موفقیت تولید و در صف بررسی ذخیره شد (#{item_id})**

📌 **موضوع:** {topic}
🎯 **مقصد:** `{target or 'تنظیم نشده'}`

📝 **پیش‌نمایش متن:**
{res.get('post_text', '')[:600]}...

شما می‌توانید هم‌اکنون پست را تایید و ارسال کنید یا در صف نگه دارید:"""

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🚀 تایید و ارسال فوری به کانال", callback_data=f"ai_q_app_{item_id}")],
            [InlineKeyboardButton("🗑️ حذف از صف", callback_data=f"ai_q_del_{item_id}")],
            [InlineKeyboardButton("🔙 بازگشت به استودیو", callback_data=back_menu_cb)]
        ])
        await query.edit_message_text(preview_text, reply_markup=kb, parse_mode="Markdown")
        return True

    # ساخت نظرسنجی کانال
    if data == "ai_m_poll":
        await query.answer("⏳ در حال طراحی نظرسنجی تعاملی...", show_alert=False)
        settings = db.get_ai_marketing_settings(bot_type=bot_type, owner_id=owner_id)
        target = settings.get("target_channel") or ""

        poll_res = ai_marketing.generate_channel_poll(
            topic="میزان رضایت، کیفیت پایداری و سرعت اتصال در شبکه",
            custom_settings=settings
        )

        poll_dict = {
            "question": poll_res.get("question", ""),
            "options": poll_res.get("options", []),
            "is_anonymous": poll_res.get("is_anonymous", True),
            "allows_multiple_answers": poll_res.get("allows_multiple_answers", False)
        }

        item_id = db.create_ai_content_item(
            bot_type=bot_type,
            owner_id=owner_id,
            content_type="poll",
            platform="telegram_channel",
            target_destination=target,
            title=poll_res.get("question", "نظرسنجی کیفیت"),
            content_text=poll_res.get("content", ""),
            poll_data=poll_dict,
            status="pending_approval",
            created_by="telegram_bot"
        )

        opts_list = "\n".join([f"• {o}" for o in poll_res.get("options", [])])
        preview_text = f"""📊 **نظرسنجی با موفقیت در صف بررسی ثبت شد (#{item_id})**

❓ **سوال:** {poll_res.get('question')}
📋 **گزینه‌ها:**
{opts_list}

🎯 **کانال مقصد:** `{target or 'تنظیم نشده'}`"""

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🚀 تایید و ارسال به کانال", callback_data=f"ai_q_app_{item_id}")],
            [InlineKeyboardButton("🗑️ حذف از صف", callback_data=f"ai_q_del_{item_id}")],
            [InlineKeyboardButton("🔙 بازگشت به استودیو", callback_data=back_menu_cb)]
        ])
        await query.edit_message_text(preview_text, reply_markup=kb, parse_mode="Markdown")
        return True

    # ساخت پکیج اینستاگرام
    if data == "ai_m_insta":
        await query.answer("⏳ در حال تدوین پکیج اینستاگرام...", show_alert=False)
        settings = db.get_ai_marketing_settings(bot_type=bot_type, owner_id=owner_id)
        page = settings.get("instagram_page") or "@MyVPNPage"

        insta_res = ai_marketing.generate_instagram_package(
            topic="آموزش اتصال سریع آیفون و اندروید به نرم‌افزار Sing-box",
            instagram_handle=page,
            custom_settings=settings
        )

        item_id = db.create_ai_content_item(
            bot_type=bot_type,
            owner_id=owner_id,
            content_type="instagram",
            platform="instagram",
            target_destination=page,
            title="پکیج اینستاگرام آموزش Singbox",
            content_text=insta_res.get("content", ""),
            status="pending_approval",
            created_by="telegram_bot"
        )

        tags = " ".join(insta_res.get("hashtags", [])[:8])
        preview_text = f"""📸 **پکیج اینستاگرام در صف بررسی ذخیره شد (#{item_id})**

📌 **پیج:** `{page}`
💡 **ایده استوری:** {insta_res.get('story_idea', '')}
🏷️ **هشتگ‌ها:** {tags}

📝 **پیش‌نمایش کپشن:**
{insta_res.get('caption', '')[:500]}..."""

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🗑️ حذف از صف", callback_data=f"ai_q_del_{item_id}")],
            [InlineKeyboardButton("🔙 بازگشت به استودیو", callback_data=back_menu_cb)]
        ])
        await query.edit_message_text(preview_text, reply_markup=kb, parse_mode="Markdown")
        return True

    # منوی انتخاب درصد کمپین تخفیف تعاملی
    if data == "ai_m_disc":
        text = """🎁 **ساخت کمپین تخفیف تعاملی و پروموشن با هوش مصنوعی**

هوش مصنوعی علاوه بر نگارش متن هیجان‌انگیز، یک **کد تخفیف واقعی در دیتابیس ربات** ثبت می‌کند و پیام آن را در صف بررسی قرار می‌دهد.

میزان تخفیف مورد نظر خود را انتخاب کنید:"""
        kb = get_ai_discount_presets_keyboard(bot_type=bot_type)
        await query.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
        return True

    # تولید کمپین تخفیف با درصد مشخص
    if data.startswith("ai_dc_"):
        pct = int(data.replace("ai_dc_", ""))
        await query.answer(f"⏳ در حال ساخت کد و تدوین کمپین {pct}٪...", show_alert=False)

        settings = db.get_ai_marketing_settings(bot_type=bot_type, owner_id=owner_id)
        target = settings.get("target_channel") or ""

        import time
        code = f"GIFT{pct}_{int(time.time()) % 10000}"

        # ایجاد واقعی کد تخفیف در دیتابیس
        if bot_type == "reseller":
            db.create_reseller_discount_code(
                reseller_id=owner_id,
                code=code,
                discount_percent=pct,
                max_uses=50
            )
        else:
            db.create_discount_code(
                code=code,
                discount_percent=pct,
                max_uses=50
            )

        disc_res = ai_marketing.generate_feedback_discount_campaign(
            feedback_context=f"قدردانی از همراهی و ارائه تخفیف فوق‌العاده {pct} درصدی",
            discount_code=code,
            discount_percent=pct,
            bot_username=target,
            custom_settings=settings
        )

        item_id = db.create_ai_content_item(
            bot_type=bot_type,
            owner_id=owner_id,
            content_type="discount_promo",
            platform="telegram_channel",
            target_destination=target,
            title=f"کمپین تخفیف {pct}٪ ({code})",
            content_text=disc_res.get("post_text", ""),
            discount_data={"code": code, "percent": pct, "max_uses": 50},
            status="pending_approval",
            created_by="telegram_bot"
        )

        preview_text = f"""🎁 **کد تخفیف در سیستم فعال و پیام آن در صف قرار گرفت (#{item_id})**

🎟️ **کد ساخته شده:** `{code}`
📊 **میزان تخفیف:** **{pct}٪** (سقف ۵۰ نفر)
🎯 **مقصد انتشار:** `{target or 'کانال پیش‌فرض'}`

📝 **پیش‌نمایش پیام:**
{disc_res.get('post_text', '')[:500]}..."""

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🚀 تایید و انتشار فوری در کانال", callback_data=f"ai_q_app_{item_id}")],
            [InlineKeyboardButton("🗑️ حذف از صف", callback_data=f"ai_q_del_{item_id}")],
            [InlineKeyboardButton("🔙 بازگشت به استودیو", callback_data=back_menu_cb)]
        ])
        await query.edit_message_text(preview_text, reply_markup=kb, parse_mode="Markdown")
        return True

    # تایید و ارسال فوری آیتم از صف به کانال تلگرام
    if data.startswith("ai_q_app_"):
        item_id = int(data.replace("ai_q_app_", ""))
        item = db.get_ai_content_item(item_id)
        if not item:
            await query.answer("❌ این مورد یافت نشد یا قبلاً حذف شده است.", show_alert=True)
            return True

        settings = db.get_ai_marketing_settings(bot_type=bot_type, owner_id=owner_id)
        dest = item.get("target_destination") or settings.get("target_channel") or ""

        if not dest:
            await query.answer("❌ آدرس کانال مقصد مشخص نیست! لطفاً در تنظیمات کانال را وارد کنید.", show_alert=True)
            return True

        try:
            if item.get("content_type") == "poll" and item.get("poll_data"):
                p_info = item["poll_data"]
                await context.bot.send_poll(
                    chat_id=dest,
                    question=p_info.get("question", item.get("title", ""))[:300],
                    options=p_info.get("options", [])[:10],
                    is_anonymous=p_info.get("is_anonymous", True),
                    allows_multiple_answers=p_info.get("allows_multiple_answers", False)
                )
            else:
                await context.bot.send_message(
                    chat_id=dest,
                    text=item.get("content_text", ""),
                    parse_mode="Markdown"
                )

            db.update_ai_content_item(item_id, status="published", published_at=get_now_iso())
            await query.answer("✅ با موفقیت در کانال منتشر شد!", show_alert=True)

            text, kb = get_ai_queue_payload(bot_type=bot_type, owner_id=owner_id)
            await query.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
            return True

        except Exception as e:
            logger.error(f"Error publishing to {dest}: {e}")
            await query.answer(f"❌ خطا در ارسال به کانال: {e}", show_alert=True)
            return True

    # حذف آیتم از صف بررسی
    if data.startswith("ai_q_del_"):
        item_id = int(data.replace("ai_q_del_", ""))
        db.delete_ai_content_item(item_id)
        await query.answer("🗑️ مورد از صف بررسی حذف شد.", show_alert=False)

        text, kb = get_ai_queue_payload(bot_type=bot_type, owner_id=owner_id)
        await query.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
        return True

    # تنظیمات هوش مصنوعی
    if data == "ai_m_settings":
        settings = db.get_ai_marketing_settings(bot_type=bot_type, owner_id=owner_id)
        text = f"""⚙️ **تنظیمات هوش مصنوعی و کانال‌ها**

🧠 **سرویس‌دهنده:** `{settings.get('provider', 'gemini')}`
🏷️ **نام مدل:** `{settings.get('model_name', 'gemini-1.5-flash')}`
📢 **کانال تلگرام:** `{settings.get('target_channel') or 'تنظیم نشده'}`
📸 **پیج اینستاگرام:** `{settings.get('instagram_page') or 'تنظیم نشده'}`
🔑 **وضعیت کلید:** {'🟢 ثبت شده' if settings.get('api_key') else '⚪️ ثبت نشده (حالت آفلاین)'}

💡 برای تغییر کلیدها، مدل‌ها و تنظیمات عمیق‌تر می‌توانید از **پنل وب > استودیو هوش مصنوعی** استفاده کنید."""
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 بازگشت به استودیو", callback_data=back_menu_cb)]
        ])
        await query.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
        return True

    return False
