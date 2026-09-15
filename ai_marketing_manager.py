"""
ماژول پیشرفته هوش مصنوعی و بازاریابی (AI Marketing & Content Generation Engine)
پشتیبانی از انواع موتورهای هوش مصنوعی:
- Google Gemini (Gemini 1.5 Flash / Pro)
- OpenAI (ChatGPT / GPT-4o / GPT-4o-mini)
- DeepSeek AI (deepseek-chat / deepseek-reasoner)
- Custom / Local API (Ollama, LM Studio, vLLM, OpenRouter)
- موتور بومی آفلاین هوشمند (Smart Local Fallback) بدون نیاز به اینترنت و کلید

قابلیت‌ها:
۱. تولید پست‌های جذاب تلگرام با نکات فنی، اخبار آزادی اینترنت و نگارش حرفه‌ای.
۲. طراحی نظرسنجی‌های تعاملی برای کانال تلگرام.
۳. تولید پکیج کامل اینستاگرام شامل کپشن، ایده استوری و هشتگ‌های ترند.
۴. تحلیل تعاملی بازخورد کاربران و ساخت هوشمند کمپین‌های کد تخفیف.
۵. دستیار گفتگوی هوشمند جهت ایده پردازی و استراتژی فروش.
"""

import json
import logging
import os
import random
import re
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class AIMarketingManager:
    """مدیریت یکپارچه تولید محتوا و اتوماسیون بازاریابی با هوش مصنوعی"""

    TONES = {
        "friendly": "صمیمانه، خودمانی و پرانرژی با لحنی همدلانه",
        "informative": "آموزشی، تخصصی، مستند و راهنمای کاربردی",
        "urgent": "فوری، هشداردهنده، اخباری و متمرکز بر دور زدن اختلالات",
        "promo": "تبلیغاتی، تشویقی، وسوسه‌انگیز و دارای آفر و تخفیف ویژه"
    }

    DEFAULT_TOPICS = [
        "راهنمای رفع کندی و قطعی فیلترشکن در ساعات اوج مصرف",
        "آموزش تنظیم پروتکل‌های جدید V2Ray و Sing-box برای عبور از فیلترینگ شدید",
        "نکات امنیتی جلوگیری از لو رفتن هویت در اینترنت و حفظ حریم خصوصی",
        "معرفی قابلیت‌های اشتراک VIP، لوکیشن‌های اختصاصی و پینگ پایین گیمینگ",
        "چرا استفاده از فیلترشکن‌های رایگان و ناامن خطرناک است؟"
    ]

    def __init__(self):
        pass

    def _extract_settings(self, custom_settings: Optional[Dict[str, Any]] = None, **kwargs) -> Dict[str, Any]:
        """استخراج پارامترهای موتور هوش مصنوعی با اولویت‌بندی تنظیمات اختصاصی"""
        s = custom_settings or {}
        provider = kwargs.get("provider") or s.get("provider") or os.getenv("AI_PROVIDER", "gemini").lower()
        api_key = kwargs.get("api_key") or s.get("api_key") or os.getenv("GEMINI_API_KEY") or os.getenv("OPENAI_API_KEY", "")
        api_url = kwargs.get("api_url") or s.get("custom_base_url") or os.getenv("AI_BASE_URL", "")
        model = kwargs.get("model") or kwargs.get("model_name") or s.get("model_name") or ""
        brand_name = kwargs.get("brand_name") or s.get("brand_name") or "HiddiBot"
        channel_username = kwargs.get("channel_username") or kwargs.get("target_channel") or s.get("target_channel", "")
        instagram_handle = kwargs.get("instagram_handle") or kwargs.get("instagram_page") or s.get("instagram_page", "")
        signature = kwargs.get("signature") or s.get("signature", "")

        if not model:
            if provider == "gemini":
                model = "gemini-1.5-flash"
            elif provider == "openai":
                model = "gpt-4o-mini"
            elif provider == "deepseek":
                model = "deepseek-chat"
            elif provider == "custom":
                model = "llama3:latest"
            else:
                model = "smart-offline"

        return {
            "provider": provider,
            "api_key": api_key,
            "api_url": api_url,
            "model": model,
            "brand_name": brand_name,
            "channel_username": channel_username,
            "instagram_handle": instagram_handle,
            "signature": signature
        }

    # ═══════════════════════════════════════════════════════════════
    # هسته ارتباط با API هوش مصنوعی
    # ═══════════════════════════════════════════════════════════════

    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        provider: str = "gemini",
        api_key: str = "",
        api_url: str = "",
        model: str = "",
        temperature: float = 0.7,
        max_tokens: int = 1500
    ) -> Optional[str]:
        """ارسال درخواست به ارائه‌دهنده انتخابی هوش مصنوعی بر اساس فرمت استاندارد Chat Completions"""
        if provider == "offline" or not api_key:
            return None

        # تعیین آدرس Endpoint بر اساس ارائه‌دهنده
        if provider == "openai":
            url = api_url.rstrip("/") + "/v1/chat/completions" if api_url else "https://api.openai.com/v1/chat/completions"
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}"
            }
        elif provider == "gemini":
            url = api_url.rstrip("/") + "/v1beta/openai/chat/completions" if api_url else "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}"
            }
        elif provider == "deepseek":
            url = api_url.rstrip("/") + "/v1/chat/completions" if api_url else "https://api.deepseek.com/v1/chat/completions"
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}"
            }
        elif provider == "custom":
            base = api_url.rstrip("/") if api_url else "http://localhost:11434/v1"
            url = base + "/chat/completions" if not base.endswith("/chat/completions") else base
            headers = {
                "Content-Type": "application/json"
            }
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
        else:
            return None

        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens
        }

        try:
            req_data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(url, data=req_data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=30) as resp:
                if resp.status == 200:
                    resp_json = json.loads(resp.read().decode("utf-8"))
                    choices = resp_json.get("choices", [])
                    if choices:
                        return choices[0].get("message", {}).get("content", "").strip()
        except Exception as e:
            logger.warning(f"AI chat_completion failed via {provider}: {e}")
            return None

        return None

    # ═══════════════════════════════════════════════════════════════
    # ۱. تولید پست کانال تلگرام
    # ═══════════════════════════════════════════════════════════════

    def generate_channel_post(
        self,
        topic: str = "",
        tone: str = "friendly",
        custom_settings: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """تولید پست جذاب تلگرامی مناسب کانال همراه با ایموجی، نکات فنی و کال تو اکشن"""
        cfg = self._extract_settings(custom_settings, **kwargs)
        topic = topic or random.choice(self.DEFAULT_TOPICS)
        tone_desc = self.TONES.get(tone, self.TONES["friendly"])
        brand = cfg["brand_name"]
        channel_username = cfg["channel_username"]
        sig = cfg["signature"]

        system_prompt = (
            "شما یک کپی‌رایتر حرفه‌ای و مدیر کانال تلگرام متخصص در حوزه اینترنت آزاد، شبکه، پروکسی و فیلترشکن هستید. "
            "وظیفه شما نگارش یک پست تلگرامی بسیار جذاب، خوانا و کاربردی به زبان فارسی است. "
            f"لحن نگارش: {tone_desc}.\n"
            "اصول نگارش:\n"
            "۱. استفاده از تیتر جذاب و ایموجی‌های مرتبط در ابتدای هر بخش.\n"
            "۲. متن باید آموزنده، مفید و بدون حاشیه‌گویی باشد (حدود ۳ تا ۵ پاراگراف کوتاه).\n"
            "۳. در انتهای پست هشتگ‌های پربازدید و ترند مرتبط قرار دهید.\n"
            f"۴. نام برند: {brand}.\n"
            "۵. در انتها یک دعوت به اقدام (Call to Action) برای خرید اشتراک، تست رایگان یا عضویت قرار دهید."
        )

        user_prompt = f"لطفاً یک پست کامل و آماده انتشار در کانال تلگرام در رابطه با موضوع زیر بنویسید:\nموضوع: {topic}"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        ai_text = self.chat_completion(
            messages, provider=cfg["provider"], api_key=cfg["api_key"], api_url=cfg["api_url"], model=cfg["model"]
        )

        if not ai_text:
            ai_text = self._fallback_channel_post(topic, brand, channel_username, sig)
        elif sig and sig not in ai_text:
            ai_text += f"\n\n{sig}"

        title = f"📢 {topic[:50]}"
        return {
            "title": title,
            "content": ai_text,
            "post_text": ai_text,
            "topic": topic,
            "type": "post",
            "platform": "telegram_channel"
        }

    # ═══════════════════════════════════════════════════════════════
    # ۲. تولید نظرسنجی کانال تلگرام (Telegram Poll)
    # ═══════════════════════════════════════════════════════════════

    def generate_channel_poll(
        self,
        topic: str = "",
        custom_settings: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """تولید یک نظرسنجی تعاملی و هوشمند برای کانال تلگرام"""
        cfg = self._extract_settings(custom_settings, **kwargs)
        topic = topic or "بررسی پایداری و کیفیت اتصال سرورها"

        system_prompt = (
            "شما متخصص تعامل و مدیریت کامیونیتی تلگرام هستید. "
            "یک نظرسنجی تلگرامی بسیار جذاب، کوتاه و تعاملی در خصوص موضوع داده شده طراحی کنید. "
            "خروجی شما باید منحصراً یک ساختار JSON معتبر و بدون هیچ متن اضافه‌ای باشد:\n"
            "{\n"
            '  "question": "متن سوال نظرسنجی با ایموجی (حداکثر ۲۵۰ کاراکتر)",\n'
            '  "options": ["گزینه ۱", "گزینه ۲", "گزینه ۳", "گزینه ۴"],\n'
            '  "is_anonymous": true,\n'
            '  "allows_multiple_answers": false\n'
            "}\n"
            "تعداد گزینه‌ها بین ۲ تا ۵ گزینه باشد و شامل گزینه‌های متداول کاربران باشد."
        )

        user_prompt = f"موضوع نظرسنجی: {topic}"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        ai_res = self.chat_completion(
            messages, provider=cfg["provider"], api_key=cfg["api_key"], api_url=cfg["api_url"], model=cfg["model"]
        )

        poll_data = None
        if ai_res:
            try:
                match = re.search(r"\{.*\}", ai_res, re.DOTALL)
                if match:
                    poll_data = json.loads(match.group(0))
            except Exception:
                poll_data = None

        if not poll_data or "question" not in poll_data or "options" not in poll_data:
            poll_data = self._fallback_channel_poll(topic)

        options_str = "\n".join([f"- {o}" for o in poll_data.get("options", [])])
        return {
            "title": f"📊 نظرسنجی: {poll_data['question'][:40]}...",
            "content": f"📊 {poll_data['question']}\n\nگزینه‌ها:\n{options_str}",
            "question": poll_data["question"],
            "options": poll_data["options"],
            "is_anonymous": poll_data.get("is_anonymous", True),
            "allows_multiple_answers": poll_data.get("allows_multiple_answers", False),
            "poll_data": poll_data,
            "type": "poll",
            "platform": "telegram_channel"
        }

    # ═══════════════════════════════════════════════════════════════
    # ۳. تولید پکیج محتوای اینستاگرام (کپشن، استوری و هشتگ‌ها)
    # ═══════════════════════════════════════════════════════════════

    def generate_instagram_package(
        self,
        topic: str = "",
        tone: str = "friendly",
        custom_settings: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """تولید پکیج اختصاصی اینستاگرام شامل هوک اول، متن کپشن، کال تو اکشن، استوری و هشتگ"""
        cfg = self._extract_settings(custom_settings, **kwargs)
        topic = topic or random.choice(self.DEFAULT_TOPICS)
        tone_desc = self.TONES.get(tone, self.TONES["friendly"])
        brand = cfg["brand_name"]
        handle = cfg["instagram_handle"] or f"@{brand}"

        system_prompt = (
            "شما یک ادمین و استراتژیست ارشد اینستاگرام هستید. "
            "برای موضوع ارائه شده، یک بسته محتوای کامل شامل موارد زیر آماده کنید:\n"
            "۱. هوک (قلاب قلاب جذب مخاطب در خط اول).\n"
            "۲. متن کامل کپشن (شامل ارزش آموزشی یا خبری و نکات کاربردی).\n"
            "۳. دعوت به اقدام (CTA) جهت دایرکت، بیو و یا استوری.\n"
            "۴. یک ایده سناریوی استوری تعاملی همراه با استیکر نظرسنجی یا کوییز اینستاگرام.\n"
            "۵. لیست ۱۰ تا ۱۵ هشتگ پربازدید فارسی مرتبط.\n"
            f"پیج برند: {handle}\n"
            f"لحن: {tone_desc}."
        )

        user_prompt = f"موضوع پست اینستاگرام: {topic}"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        ai_text = self.chat_completion(
            messages, provider=cfg["provider"], api_key=cfg["api_key"], api_url=cfg["api_url"], model=cfg["model"]
        )

        caption = ""
        story_idea = ""
        hashtags = []

        if not ai_text:
            ai_text = self._fallback_instagram_package(topic, brand, handle)
            caption = ai_text
            story_idea = f"یک استوری با متن «آیا اینترنت شما هم قطع است؟» به همراه استیکر نظرسنجی بله/خیر و لینک به بایو پیج {handle}."
            hashtags = ["#فیلترشکن", "#v2rayng", "#singbox", "#اینترنت_آزاد", "#وی_پی_ان"]
        else:
            caption = ai_text
            hashtags = re.findall(r"#[\w\_]+", ai_text) or ["#فیلترشکن", "#اینترنت_آزاد", "#v2ray"]
            story_idea = f"استوری تعاملی با موضوع «{topic[:30]}» و ارجاع به پیج {handle} جهت دریافت کانفیگ تست."

        return {
            "title": f"📸 اینستاگرام: {topic[:50]}",
            "content": ai_text,
            "caption": caption,
            "story_idea": story_idea,
            "hashtags": hashtags,
            "topic": topic,
            "type": "story",
            "platform": "instagram"
        }

    # ═══════════════════════════════════════════════════════════════
    # ۴. ساخت کمپین هوشمند کد تخفیف بر اساس بازخورد مشتریان
    # ═══════════════════════════════════════════════════════════════

    def generate_feedback_discount_campaign(
        self,
        feedback_context: str = "",
        discount_code: str = "",
        discount_percent: int = 20,
        max_uses: int = 50,
        duration_days: int = 3,
        custom_settings: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """تحلیل بازخورد مشتریان و تدوین پیام جذاب کمپین تخفیف به همراه کد اختصاصی"""
        cfg = self._extract_settings(custom_settings, **kwargs)
        brand = cfg["brand_name"]
        prefix_words = ["GIFT", "SPECIAL", "VIP", "OFF", "SPRING", "TURBO", "THANKS"]
        code = discount_code or f"{random.choice(prefix_words)}{discount_percent}_{random.randint(10, 99)}"

        system_prompt = (
            "شما مدیر روابط با مشتری (CRM) و بازاریابی هستید. "
            "بر اساس بازخورد، نظرسنجی یا جهت قدردانی از مشتریان، یک متن فوق‌العاده صمیمانه و هیجان‌انگیز "
            "برای اعلام کد تخفیف ویژه به مشتریان آماده کنید. "
            f"کد تخفیف: {code}\n"
            f"میزان تخفیف: {discount_percent} درصد\n"
            f"مهلت استفاده: {duration_days} روز\n"
            "متن باید شامل ایموجی، کد تخفیف در بلاک کد، آموزش نحوه استفاده در ربات و تشکر صمیمانه از همراهی باشد."
        )

        user_prompt = f"بازخورد یا هدف کمپین: {feedback_context or 'قدردانی از همراهی و بهبود پایداری سرورها'}"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        ai_text = self.chat_completion(
            messages, provider=cfg["provider"], api_key=cfg["api_key"], api_url=cfg["api_url"], model=cfg["model"]
        )

        if not ai_text:
            ai_text = (
                f"🎁 **هدیه ویژه قدردانی از همراهی شما!**\n\n"
                f"همراهان گرامی، به پاس اعتماد و بازخوردهای ارزشمند شما، یک کد تخفیف اختصاصی **{discount_percent} درصدی** فعال گردید:\n\n"
                f"🎟️ کد تخفیف: `{code}`\n"
                f"⏰ مهلت اعتبار: فقط تا **{duration_days} روز آینده**\n"
                f"👥 سقف استفاده: **{max_uses} نفر اول**\n\n"
                f"💡 **نحوه استفاده:** در منوی ربات، هنگام ثبت سفارش خرید یا تمدید اشتراک، دکمه «ثبت کد تخفیف» را لمس کرده و کد بالا را وارد نمایید.\n\n"
                f"✨ سپاس از این که در کنار ما هستید!"
            )

        banner_text = f"🔥 کد تخفیف ویژه {discount_percent}٪ با کد: {code} (مهلت محدود)"

        return {
            "title": f"🎁 کمپین تخفیف {discount_percent}٪ ({code})",
            "content": ai_text,
            "post_text": ai_text,
            "banner_text": banner_text,
            "discount_code": code,
            "discount_percent": discount_percent,
            "max_uses": max_uses,
            "type": "discount_promo",
            "platform": "telegram_channel"
        }

    # ═══════════════════════════════════════════════════════════════
    # ۵. گفتگوی تعاملی و مشاوره با هوش مصنوعی (AI Chat Assistant)
    # ═══════════════════════════════════════════════════════════════

    def ai_chat_reply(
        self,
        message: str = "",
        user_message: str = "",
        chat_history: List[Dict[str, str]] = None,
        conversation_history: List[Dict[str, str]] = None,
        custom_settings: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> str:
        """پاسخگویی به چت آزاد مدیر یا نماینده جهت مشاوره محتوا، فروش و تدوین کمپین"""
        cfg = self._extract_settings(custom_settings, **kwargs)
        history = chat_history or conversation_history or []
        user_msg = message or user_message or ""
        role = kwargs.get("role", "admin")
        brand = cfg["brand_name"]

        system_prompt = (
            f"شما دستیار ارشد هوش مصنوعی و مشاور بازاریابی و فروش سامانه {brand} هستید. "
            f"مخاطب شما {('مدیر ارشد سیستم' if role == 'admin' else 'نماینده فروش و همکار')} است. "
            "شما در زمینه موارد زیر تخصص دارید:\n"
            "۱. نگارش و پیشنهاد انواع پست‌های تلگرام، استوری‌ها و کپشن‌های اینستاگرام.\n"
            "۲. طراحی نظرسنجی‌ها و استراتژی‌های تعامل با مشترکین.\n"
            "۳. پیشنهاد کمپین‌های تخفیف و جشنواره‌های مناسبتی جهت افزایش فروش.\n"
            "۴. راهنمایی در مورد آموزش پروتکل‌های V2Ray، رفع اختلالات و تکنیک‌های اتصال.\n"
            "پاسخ‌های شما باید کاربردی، دقیق، به زبان فارسی روان و شکیل با ساختار منظم ارائه شوند."
        )

        messages = [{"role": "system", "content": system_prompt}]
        for m in history[-6:]:
            messages.append(m)
        messages.append({"role": "user", "content": user_msg})

        ai_res = self.chat_completion(
            messages, provider=cfg["provider"], api_key=cfg["api_key"], api_url=cfg["api_url"], model=cfg["model"]
        )

        if ai_res:
            return ai_res

        # پاسخ هوشمند بومی در صورت قطعی اینترنت خارجی یا نبود کلید
        return self._fallback_chat_reply(user_msg)

    # ═══════════════════════════════════════════════════════════════
    # موتور محلی هوشمند (Smart Local Fallback Engines)
    # ═══════════════════════════════════════════════════════════════

    def _fallback_channel_post(self, topic: str, brand: str, channel: str, signature: str = "") -> str:
        chan_label = channel if channel else "@Channel"
        sig_text_1 = signature if signature else f"📢 کانال ما: {chan_label}\n🤖 ربات خرید و تمدید آنلاین: @Bot"
        sig_text_2 = signature if signature else f"🔹 عضویت در کانال اطلاع‌رسانی: {chan_label}"

        templates = [
            (
                f"🚀 **راهنمای جامع و اختصاصی | {brand}**\n\n"
                f"📌 **موضوع:** {topic}\n\n"
                "🔹 **نکات کلیدی برای اتصال پایدار:**\n"
                "۱. کلاینت خود را همیشه به آخرین نسخه پایدار (v2rayNG یا Sing-box یا Streisand) بروزرسانی کنید.\n"
                "۲. در بخش تنظیمات برنامه، حالت DNS را روی Cloudflare یا Google قرار دهید.\n"
                "۳. در صورت بروز هرگونه کندی، با یک‌بار خاموش و روشن کردن حالت پرواز (Airplane Mode)، آی‌پی محلی خود را نوسازی کنید.\n\n"
                "🛡️ تمامی سرورهای ما با جدیدترین متدهای ضد فیلتر و پروتکل‌های Reality و Vless بصورت لحظه‌ای پایش می‌شوند.\n\n"
                f"{sig_text_1}\n\n"
                "#اینترنت_آزاد #فیلترشکن #v2ray #امنیت_شبکه #پروکسی"
            ),
            (
                f"⚡ **اطلاعیه مهم و ترفند کاربردی | {brand}**\n\n"
                f"💡 {topic}\n\n"
                "همراهان گرامی، به اطلاع می‌رساند زیرساخت‌های سرور با موفقیت به پروتکل‌های فوق‌سریع ارتقا یافتند. برای تجربه بهترین کیفیت:\n\n"
                "✅ اشتراک خود را یک‌بار در برنامه آپدیت نمایید (Update Subscription).\n"
                "✅ در کلاینت‌های آیفون استفاده از اپلیکیشن Sing-box یا FoXray بیشترین سرعت را به همراه دارد.\n"
                "✅ در صورت استفاده از اینترنت خانگی، پروتکل‌های مبتنی بر gRPC پایداری بهتری ارائه می‌دهند.\n\n"
                "💬 رضایت و دسترسی آزاد شما به اطلاعات، بالاترین اولویت ماست.\n\n"
                f"{sig_text_2}\n\n"
                "#آموزش #singbox #فیلترینگ #سرعت_بالا"
            )
        ]
        return random.choice(templates)

    def _fallback_channel_poll(self, topic: str) -> Dict[str, Any]:
        return {
            "question": f"📊 کاربران گرامی، وضعیت پایداری و سرعت اتصال شما در حال حاضر چگونه است؟",
            "options": [
                "🟢 عالی و بسیار پرسرعت (بدون قطعی)",
                "🟡 خوب و قابل قبول (گاهی افت سرعت)",
                "🔴 ضعیف یا با تاخیر بالا",
                "⚪ اتصال روی برخی اپراتورها برقرار نیست"
            ],
            "is_anonymous": True,
            "allows_multiple_answers": False
        }

    def _fallback_instagram_package(self, topic: str, brand: str, handle: str) -> str:
        return (
            f"🎯 **قلاب اول (Hook):** آیا می‌دونستید با این ترفند ساده، سرعت اتصالتون ۲ برابر میشه؟ 🚀\n\n"
            f"📌 **کپشن:**\n"
            f"سلام رفقا! توی این پست می‌خوایم به موضوع مهم «{topic}» بپردازیم.\n\n"
            "خیلی از کاربرا سوال می‌پرسن که چطور بدون قطعی در اپراتورهای همراه اول و ایرانسل وصل بمونن؟ جواب در انتخاب پروتکل بهینه و استفاده از DNS امنه!\n\n"
            f"تیم {brand} همیشه آخرین فناوری‌های اتصال رو در اختیارتون قرار میده تا همیشه آنلاین باشید.\n\n"
            f"👉 برای دریافت تست رایگان همین الان کلمه «تست» رو دایرکت کن یا روی لینک بایو کلیک کن: {handle}\n\n"
            "💡 **ایده استوری:**\n"
            "یک ویدیوی ۵ ثانیه‌ای از تست پینگ پایین سرورها با استیکر شمارش معکوس تخفیف و باکس سوال: «شما از کدوم اپراتور وصل میشید؟»\n\n"
            "#فیلترشکن #آموزش_اینترنت #vpn_ایران #v2rayng #اینستاگرام #تکنولوژی"
        )

    def _fallback_chat_reply(self, query: str) -> str:
        q = query.lower()
        if "تخفیف" in q or "کمپین" in q:
            return (
                "💡 **پیشنهاد کمپین تخفیف:**\n"
                "بهترین راهکار برای افزایش فروش سریع، برگزاری یک کمپین ۲۴ ساعته با عنوان «جشنواره پایداری سرورها» است. "
                "می‌توانید یک کد تخفیف ۲۰ یا ۲۵ درصدی با سقف استفاده محدود (مثلا ۵۰ نفر) ایجاد کرده و متن اعلام آن را "
                "در کانال تلگرام و استوری اینستاگرام همراه با لینک مستقیم خرید در ربات منتشر کنید."
            )
        elif "پست" in q or "محتوا" in q:
            return (
                "📢 **پیشنهاد موضوع برای پست کانال:**\n"
                "۱. آموزش تصویری نحوه فعال‌سازی Split Tunneling برای باز ماندن برنامه‌های بانکی داخلی هنگام روشن بودن VPN.\n"
                "۲. معرفی اپلیکیشن‌های جدید جایگزین مانند Sing-box برای اندروید و V2Box برای iOS.\n"
                "۳. انتشار نتایج تست سرعت و رضایت مشترکین در ساعات شلوغی شبانه."
            )
        elif "نظرسنجی" in q:
            return (
                "📊 **ایده نظرسنجی کاربردی:**\n"
                "یک نظرسنجی با موضوع «بیشترین زمان استفاده شما از اینترنت در کدام ساعات شبانه‌روز است؟» یا "
                "«کدام اپراتور اینترنت در منطقه شما قطعی کمتری دارد؟» ایجاد کنید. این نظرسنجی هم تعامل کانال را بالا می‌برد "
                "و هم دیتای ارزشمندی برای زمان‌بندی پیام‌های فروش در اختیارتان می‌گذارد."
            )
        else:
            return (
                "سلام! در خدمت شما هستم. می‌توانید از من در مورد:\n"
                "🔹 نگارش پست‌های کانال تلگرام در زمینه رفع اختلالات و آموزش‌ها\n"
                "🔹 تدوین سناریوهای استوری و کپشن اینستاگرام\n"
                "🔹 ایجاد کدهای تخفیف تعاملی بر اساس نظرات کاربران\n"
                "🔹 بررسی استراتژی‌های افزایش مشتری و حفظ وفاداری مشترکین\n"
                "راهنمایی بخواهید."
            )


# شیء تک‌نمونه جهت استفاده آسان در سراسر سیستم
ai_marketing = AIMarketingManager()
