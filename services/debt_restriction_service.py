#!/usr/bin/env python3
"""
ماژول اختصاصی مدیریت و اعمال محدودیت هوشمند در استفاده بابت بدهی (Debt Restriction Throttling Service)
پایش دوره‌ای کاربران بدهکار عضو گروه محدودیت، اعمال قطع موقت در هیدیفای بر اساس سقف زمان و حجم،
ارسال اعلان‌های دوطرفه (پیامک و تلگرام) و فعال‌سازی مجدد خودکار پس از پایان مهلت جریمه.
"""

import logging
import json
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

# ─── تنظیمات پیش‌فرض سیستم محدودیت مشتریان بدحساب ───
DEFAULT_DEBT_RESTRICTION_SETTINGS: Dict[str, Any] = {
    "enabled": False,                       # فعال‌سازی کلی سیستم محدودیت بدحسابی
    "traffic_limit_mb": 500,               # سقف مصرف در هر چرخه (مگابایت) - ۰ یعنی غیرفعال
    "continuous_usage_minutes": 10,        # سقف اتصال مداوم (دقیقه) - ۰ یعنی غیرفعال
    "penalty_duration_minutes": 120,       # مدت زمان غیرفعال‌سازی موقت در هیدیفای (دقیقه) - پیش‌فرض ۲ ساعت
    "cooldown_minutes": 30,                # فاصله تنفس بین چرخه‌ها پس از فعال‌سازی مجدد (دقیقه)
    "daily_restriction_limit": 5,          # حداکثر دفعات قطع در طول روز (۰ یعنی نامحدود)
    "daily_traffic_limit_mb": 2048,        # سقف کل ترافیک مجاز روزانه برای بدحساب‌ها (مگابایت) - ۰ یعنی نامحدود
    "min_debt_threshold": 0,               # حداقل مبلغ بدهی (تومان) برای شمول محدودیت
    "peak_hours_enabled": False,           # فعال‌سازی محدودیت در ساعات اوج مصرف
    "peak_start_hour": 18,                 # شروع ساعات اوج (مثلاً ۱۸ عصر)
    "peak_end_hour": 24,                   # پایان ساعات اوج (مثلاً ۲۴ شب)
    "notify_telegram": True,               # ارسال به تلگرام
    "notify_sms": True,                    # ارسال با پیامک
    "notify_on_start": True,               # ارسال پیام در زمان شروع قطع
    "notify_on_end": True,                 # ارسال پیام در زمان پایان مهلت و اتصال مجدد
    "template_start_traffic": (
        "مشترک گرامی، با سلام و احترام\n\n"
        "با توجه به وجود صورتحساب پرداخت‌نشده به مبلغ {debt_amount} تومان، اشتراک «{account_name}» طبق سیاست مدیریت مصرف موقتاً به مدت {penalty_duration} دقیقه وارد وقفه گردید.\n\n"
        "⏱️ پس از پایان این مدت، سرویس به صورت خودکار مجدداً فعال خواهد شد.\n"
        "💳 جهت رفع همیشگی محدودیت و اتصال پیوسته و بدون دغدغه، خواهشمند است نسبت به پرداخت فاکتور خود از لینک زیر اقدام فرمایید:\n"
        "{portal_url}\n\n"
        "با سپاس از صبوری و همراهی ارزشمند شما 🙏"
    ),
    "template_start_continuous": (
        "مشترک گرامی، با سلام و احترام\n\n"
        "اشتراک «{account_name}» به دلیل اتصال مداوم و داشتن صورتحساب معوق ({debt_amount} تومان)، جهت مدیریت منابع موقتاً به مدت {penalty_duration} دقیقه در وضعیت استراحت قرار گرفت.\n\n"
        "⏱️ پس از پایان این بازه، سرویس شما مجدداً به صورت خودکار متصل خواهد شد.\n"
        "💳 برای رفع دائمی محدودیت‌ها و بهره‌مندی از اتصال نامحدود، لطفاً نسبت به تسویه فاکتور خود اقدام فرمایید:\n"
        "{portal_url}\n\n"
        "از درک و همراهی شما سپاسگزاریم 🙏"
    ),
    "template_start_daily": (
        "مشترک گرامی، با سلام و احترام\n\n"
        "اشتراک «{account_name}» به سقف مجاز مصرف روزانه برای حساب‌های معوق رسیده است و دسترسی تا پایان ساعات روز موقتاً غیرفعال گردید.\n\n"
        "💳 جهت رفع فوری و بازگشت کامل ترافیک و سرعت بدون محدودیت، لطفاً از طریق لینک زیر فاکتور خود را تسویه نمایید:\n"
        "{portal_url}\n\n"
        "با تشکر از همکاری صمیمانه شما 🙏"
    ),
    "template_start_peak": (
        "مشترک گرامی، با سلام و احترام\n\n"
        "به دلیل قرار داشتن در ساعات اوج مصرف شبکه و وجود صورتحساب معوق ({debt_amount} تومان)، اتصال اشتراک «{account_name}» موقتاً متوقف گردید.\n\n"
        "💳 جهت رفع محدودیت و استفاده بدون وقفه در کلیه ساعات شبانه‌روز، لطفاً فاکتور خود را تسویه فرمایید:\n"
        "{portal_url}\n\n"
        "از صبوری شما متشکریم 🙏"
    ),
    "template_end": (
        "مشترک گرامی، با سلام و احترام\n\n"
        "دوره وقفه موقت اشتراک «{account_name}» به پایان رسید و اتصال شما هم‌اکنون با موفقیت مجدداً فعال گردید. ✅\n\n"
        "🙏 جهت جلوگیری از تکرار چرخه‌های محدودیت و استمرار اتصال باکیفیت، خواهشمند است در فرصت مناسب نسبت به پرداخت بدهی خود اقدام فرمایید:\n"
        "{portal_url}\n\n"
        "همواره همراه شما هستیم 🌟"
    ),
    "template_deadline_expired": (
        "مشترک گرامی، با سلام و احترام\n\n"
        "مهلت زمانی در نظر گرفته شده جهت تسویه صورتحساب اشتراک «{account_name}» به مبلغ {debt_amount} تومان به پایان رسیده و سرویس شما موقتاً غیرفعال گردید.\n\n"
        "💳 جهت پرداخت بدهی و اتصال و فعال‌سازی فوری و خودکار اشتراک، لطفاً از لینک زیر اقدام فرمایید:\n"
        "{portal_url}\n\n"
        "با تشکر از همراهی و صبوری شما 🙏"
    )
}


def get_portal_url(subscription: dict, db_instance) -> str:
    """تولید لینک مستقیم به پورتال آنلاین مشتری جهت پرداخت بدهی"""
    try:
        reseller_id = subscription.get("reseller_id")
        domain = ""
        if reseller_id and hasattr(db_instance, "get_reseller"):
            r_info = db_instance.get_reseller(reseller_id) or {}
            domain = r_info.get("domain") or ""
        if not domain and hasattr(db_instance, "get_setting"):
            domain = db_instance.get_setting("custom_domain") or ""
        token = subscription.get("hidify_uuid") or subscription.get("id")
        if domain and token:
            return f"https://{domain}/user/{token}"
    except Exception:
        pass
    return ""


def format_notification_text(template: str, sub: dict, settings: dict, trigger_reason: str, db_instance) -> str:
    """قالب‌بندی متن پیامک یا تلگرام با جایگذاری توکن‌های داینامیک"""
    if not template:
        return ""

    acc_name = sub.get("account_name") or f"sub_{sub.get('id')}"
    debt_amt = int(sub.get("debt_amount") or 0)
    debt_formatted = f"{debt_amt:,}"
    penalty_mins = int(settings.get("penalty_duration_minutes") or 120)
    cooldown_mins = int(settings.get("cooldown_minutes") or 30)
    portal_url = get_portal_url(sub, db_instance)
    traffic_limit_mb = float(settings.get("traffic_limit_mb") or 500)

    msg = template
    msg = msg.replace("{account_name}", acc_name)
    msg = msg.replace("{debt_amount}", debt_formatted)
    msg = msg.replace("{penalty_duration}", str(penalty_mins))
    msg = msg.replace("{penalty_minutes}", str(penalty_mins))
    msg = msg.replace("{cooldown_minutes}", str(cooldown_mins))
    msg = msg.replace("{trigger_reason}", trigger_reason or "مدیریت حساب‌های معوق")
    msg = msg.replace("{portal_url}", portal_url or "پورتال کاربری")
    msg = msg.replace("{traffic_limit_mb}", str(int(traffic_limit_mb)))
    return msg


def send_debt_restriction_notification(
    sub: dict,
    event_type: str,  # 'start' or 'end'
    reason_code: str = "traffic",  # 'traffic', 'continuous', 'daily', 'peak', 'end'
    trigger_reason: str = "",
    settings: dict = None,
    db_instance = None
):
    """ارسال هوشمند اعلان شروع یا پایان محدودیت به تلگرام و پیامک بر اساس نوع رویداد و قالب اختصاصی"""
    if not settings or not db_instance:
        return
    if event_type == "start" and not settings.get("notify_on_start", True):
        return
    if event_type == "end" and not settings.get("notify_on_end", True):
        return

    # انتخاب قالب پیام بر اساس نوع رویداد و دلیل محدودیت
    if event_type == "start":
        if reason_code == "deadline":
            raw_tpl = settings.get("template_deadline_expired") or DEFAULT_DEBT_RESTRICTION_SETTINGS["template_deadline_expired"]
        elif reason_code == "continuous":
            raw_tpl = settings.get("template_start_continuous") or settings.get("start_message_template") or DEFAULT_DEBT_RESTRICTION_SETTINGS["template_start_continuous"]
        elif reason_code == "daily":
            raw_tpl = settings.get("template_start_daily") or settings.get("start_message_template") or DEFAULT_DEBT_RESTRICTION_SETTINGS["template_start_daily"]
        elif reason_code == "peak":
            raw_tpl = settings.get("template_start_peak") or settings.get("start_message_template") or DEFAULT_DEBT_RESTRICTION_SETTINGS["template_start_peak"]
        else:
            raw_tpl = settings.get("template_start_traffic") or settings.get("start_message_template") or DEFAULT_DEBT_RESTRICTION_SETTINGS["template_start_traffic"]
    else:
        raw_tpl = settings.get("template_end") or settings.get("end_message_template") or DEFAULT_DEBT_RESTRICTION_SETTINGS["template_end"]

    msg_html = format_notification_text(raw_tpl, sub, settings, trigger_reason, db_instance)
    if not msg_html:
        return

    # استخراج اطلاعات ارتباطی مشتری
    telegram_id = sub.get("telegram_id")
    phone_number = sub.get("phone_number")
    if not phone_number and telegram_id and hasattr(db_instance, "get_user"):
        u_row = db_instance.get_user(telegram_id)
        if u_row:
            phone_number = u_row.get("phone_number")

    reseller_id = sub.get("reseller_id")

    # ۱. ارسال تلگرام (در صورت فعال بودن و وجود شناسه تلگرام)
    if settings.get("notify_telegram", True) and telegram_id and int(telegram_id) > 0:
        try:
            from dashboard import send_telegram_msg
            bot_token = None
            if reseller_id and hasattr(db_instance, "get_reseller"):
                r_row = db_instance.get_reseller(reseller_id) or {}
                bot_token = r_row.get("bot_token")
            send_telegram_msg(chat_id=int(telegram_id), text=msg_html, parse_mode="HTML", bot_token=bot_token)
            logger.info(f"Sent debt restriction {event_type} ({reason_code}) Telegram msg to {telegram_id} for sub {sub.get('id')}")
        except Exception as e_tg:
            logger.warning(f"Failed to send debt restriction Telegram to {telegram_id}: {e_tg}")

    # ۲. ارسال پیامک (در صورت فعال بودن و وجود شماره موبایل)
    if settings.get("notify_sms", True) and phone_number:
        try:
            import re
            from sms_service import send_sms
            clean_sms_text = re.sub(r"<[^>]+>", "", msg_html)
            send_sms(to_phone=phone_number, message=clean_sms_text, db_instance=db_instance, reseller_id=reseller_id)
            logger.info(f"Sent debt restriction {event_type} ({reason_code}) SMS to {phone_number} for sub {sub.get('id')}")
        except Exception as e_sms:
            logger.warning(f"Failed to send debt restriction SMS to {phone_number}: {e_sms}")


def re_enable_if_restricted(sub_id: int, db_instance, hidify_update_func=None) -> bool:
    """
    در صورت تسویه بدهی یا خروج دستی از گروه محدودیت، اگر اشتراک مسدود بود
    بلافاصله در هیدیفای فعال شده و محدودیت موقت یا قطعی مهلت بدهی لغو می‌گردد.
    """
    try:
        conn = db_instance.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM subscriptions WHERE id = ?", (sub_id,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return False

        sub = dict(row)
        was_debt_disabled = bool(sub.get("debt_restricted_until")) or (sub.get("status") == "disabled" and "بدهی" in str(sub.get("disable_reason") or ""))

        cursor.execute("""
            UPDATE subscriptions SET
                in_debt_restriction = 0,
                debt_restricted_until = NULL,
                debt_restriction_session_start = NULL,
                debt_auto_disable_at = NULL,
                status = CASE WHEN status = 'disabled' AND (debt_restricted_until IS NOT NULL OR disable_reason LIKE '%بدهی%') THEN 'active' ELSE status END,
                disable_reason = CASE WHEN disable_reason LIKE '%بدهی%' THEN NULL ELSE disable_reason END,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (sub_id,))
        conn.commit()
        conn.close()

        # فعال‌سازی فوری در هیدیفای اگر بابت بدهی قطع بوده باشد یا اشتراک فعال است
        if (was_debt_disabled or sub.get("status") == "active") and hidify_update_func and sub.get("hidify_uuid"):
            try:
                hidify_update_func(
                    uuid=sub["hidify_uuid"],
                    enable=True,
                    is_active=True,
                    reseller_id=sub.get("reseller_id")
                )
                logger.info(f"Sub #{sub_id} ({sub.get('account_name')}) un-restricted and re-enabled on Hiddify immediately.")
            except Exception as ex:
                logger.warning(f"Error re-enabling sub #{sub_id} on Hiddify after debt clear: {ex}")
        return True
    except Exception as e:
        logger.error(f"Error in re_enable_if_restricted for sub #{sub_id}: {e}")
        return False


def process_debt_auto_disable_deadlines(db_instance, hidify_update_func=None) -> Dict[str, int]:
    """
    بررسی و اعمال قطع خودکار اشتراک‌های بدهکاری که مهلت تسویه آن‌ها منقضی شده است:
    اگر debt_auto_disable_at <= now و اشتراک هنوز بدهکار است و هنوز فعال است:
    - غیرفعال‌سازی در پنل هیدیفای (enable=False, is_active=False)
    - تغییر وضعیت اشتراک در پایگاه داده به disabled با ذکر دلیل
    - ارسال پیامک و تلگرام محترمانه اطلاع‌رسانی قطع موقت و لینک پرداخت مستقیم
    - ثبت در تاریخچه/لاگ
    """
    stats = {"disabled": 0, "errors": 0}
    now = datetime.now()
    now_iso = now.isoformat()

    conn = db_instance.get_connection()
    cursor = conn.cursor()

    try:
        # استخراج اشتراک‌های فعال با بدهی پرداخت‌نشده که مهلت زمانی آن‌ها سررسیده است
        cursor.execute("""
            SELECT * FROM subscriptions 
            WHERE debt_auto_disable_at IS NOT NULL
              AND debt_auto_disable_at <= ?
              AND (debt_amount > 0 OR payment_status IN ('unpaid', 'debtor'))
              AND status = 'active'
              AND (is_deleted = 0 OR is_deleted IS NULL)
        """, (now_iso,))
        expired_subs = [dict(r) for r in cursor.fetchall()]

        for sub in expired_subs:
            sub_id = sub["id"]
            acc_name = sub.get("account_name") or f"sub_{sub_id}"
            try:
                # ۱. غیرفعال‌سازی در پنل هیدیفای
                if hidify_update_func and sub.get("hidify_uuid"):
                    try:
                        hidify_update_func(
                            uuid=sub["hidify_uuid"],
                            enable=False,
                            is_active=False,
                            reseller_id=sub.get("reseller_id")
                        )
                        logger.info(f"Sub #{sub_id} ({acc_name}) disabled in Hiddify due to unpaid debt deadline.")
                    except Exception as eh:
                        logger.warning(f"Error disabling user {sub['hidify_uuid']} on Hiddify for debt deadline: {eh}")

                # ۲. به‌روزرسانی وضعیت اشتراک در پایگاه داده
                cursor.execute("""
                    UPDATE subscriptions SET
                        status = 'disabled',
                        disable_reason = 'عدم تسویه بدهی در مهلت مقرر',
                        updated_at = ?
                    WHERE id = ?
                """, (now_iso, sub_id))
                conn.commit()

                # ۳. ارسال اعلان محترمانه به تلگرام و پیامک
                reseller_id = sub.get("reseller_id")
                settings = db_instance.get_debt_restriction_settings(reseller_id=reseller_id) or DEFAULT_DEBT_RESTRICTION_SETTINGS
                send_debt_restriction_notification(
                    sub=sub,
                    event_type="start",
                    reason_code="deadline",
                    trigger_reason="اتمام مهلت تسویه بدهی",
                    settings=settings,
                    db_instance=db_instance
                )

                # ۴. ثبت در تاریخچه اشتراک
                if hasattr(db_instance, "save_subscription_history"):
                    try:
                        db_instance.save_subscription_history(
                            subscription_id=sub_id,
                            telegram_id=sub.get("telegram_id") or 0,
                            hidify_uuid=sub.get("hidify_uuid") or "",
                            account_name=acc_name,
                            plan_name=f"{sub.get('plan_name') or ''} (قطع خودکار به دلیل عدم تسویه بدهی)",
                            previous_usage_gb=float(sub.get("data_used") or 0),
                            previous_limit_gb=float(sub.get("data_limit") or 0.0),
                            period_days=int(sub.get("duration") or 30),
                            cost_paid=0,
                            plan_price=int(sub.get("plan_price") or 0),
                            start_date=sub.get("start_date") or "",
                            expire_date=sub.get("expire_date") or "",
                            is_manual=1
                        )
                    except Exception as ehist:
                        logger.warning(f"Error saving history for debt auto disable #{sub_id}: {ehist}")

                stats["disabled"] += 1
                logger.info(f"Sub #{sub_id} ({acc_name}) auto-disabled successfully due to debt deadline.")
            except Exception as esub:
                stats["errors"] += 1
                logger.error(f"Error processing debt deadline for sub #{sub_id}: {esub}")
    except Exception as e:
        logger.error(f"Error querying debt auto disable deadlines: {e}")
    finally:
        conn.close()

    return stats


def process_debt_restrictions(db_instance, hidify_update_func=None) -> Dict[str, int]:
    """
    هسته اصلی و گرداننده پردازش دوره‌ای محدودیت‌های بدهکاران:
    ۱. بررسی و فعال‌سازی مجدد کاربرانی که مهلت جریمه ۱۵ دقیقه‌ای آن‌ها منقضی شده است.
    ۲. بررسی کاربران فعال عضو گروه محدودیت و اعمال جریمه در صورت عبور از سقف ساعت یا ترافیک.
    """
    stats = {"re_enabled": 0, "restricted": 0, "skipped_cooldown": 0}
    now = datetime.now()
    now_iso = now.isoformat()

    conn = db_instance.get_connection()
    cursor = conn.cursor()

    # ════════════════════════════════════════════════════════════════════
    # فاز ۱: آزادسازی و فعال‌سازی مجدد کاربرانی که دوره جریمه آن‌ها به پایان رسیده است
    # ════════════════════════════════════════════════════════════════════
    try:
        cursor.execute("""
            SELECT * FROM subscriptions 
            WHERE debt_restricted_until IS NOT NULL
        """)
        suspended_subs = [dict(r) for r in cursor.fetchall()]

        for sub in suspended_subs:
            until_str = sub.get("debt_restricted_until")
            if not until_str:
                continue

            try:
                until_dt = datetime.fromisoformat(until_str)
            except Exception:
                try:
                    until_dt = datetime.strptime(str(until_str)[:19], "%Y-%m-%d %H:%M:%S")
                except Exception:
                    until_dt = now

            # اگر زمان پایان جریمه فرارسیده است
            if now >= until_dt:
                sub_id = sub["id"]
                current_used = float(sub.get("data_used") or 0.0)

                # ۱.۱ فعال‌سازی در پنل هیدیفای
                if hidify_update_func and sub.get("hidify_uuid"):
                    try:
                        hidify_update_func(
                            uuid=sub["hidify_uuid"],
                            enable=True,
                            is_active=True,
                            reseller_id=sub.get("reseller_id")
                        )
                    except Exception as eh:
                        logger.warning(f"Error re-enabling user {sub['hidify_uuid']} on Hiddify: {eh}")

                # ۱.۲ بروزرسانی پایگاه داده
                cursor.execute("""
                    UPDATE subscriptions SET
                        status = 'active',
                        debt_restricted_until = NULL,
                        last_debt_restriction_ended_at = ?,
                        debt_restriction_session_start = NULL,
                        debt_restriction_session_usage = ?,
                        updated_at = ?
                    WHERE id = ?
                """, (now_iso, current_used, now_iso, sub_id))
                conn.commit()

                # ۱.۳ ارسال اعلان پایان محدودیت
                reseller_id = sub.get("reseller_id")
                settings = db_instance.get_debt_restriction_settings(reseller_id=reseller_id)
                send_debt_restriction_notification(
                    sub=sub,
                    event_type="end",
                    reason_code="end",
                    trigger_reason="پایان دوره وقفه موقت",
                    settings=settings,
                    db_instance=db_instance
                )
                stats["re_enabled"] += 1
                logger.info(f"Sub #{sub_id} ({sub.get('account_name')}) temporary debt restriction ended. Re-enabled.")
    except Exception as e1:
        logger.error(f"Error in phase 1 (re-enabling debt restrictions): {e1}")

    # ════════════════════════════════════════════════════════════════════
    # فاز ۲: بررسی مشتریان بدحساب فعال و اعمال جریمه در صورت تخلف
    # ════════════════════════════════════════════════════════════════════
    today_str = now.strftime("%Y-%m-%d")
    try:
        cursor.execute("""
            SELECT * FROM subscriptions 
            WHERE in_debt_restriction = 1
              AND (debt_amount > 0 OR payment_status IN ('unpaid', 'debtor'))
              AND (is_deleted = 0 OR is_deleted IS NULL)
              AND debt_restricted_until IS NULL
              AND status = 'active'
        """)
        eligible_subs = [dict(r) for r in cursor.fetchall()]

        for sub in eligible_subs:
            sub_id = sub["id"]
            reseller_id = sub.get("reseller_id")
            settings = db_instance.get_debt_restriction_settings(reseller_id=reseller_id)

            # اگر قابلیت برای این نماینده یا کل سیستم غیرفعال باشد
            if not settings.get("enabled", False):
                continue

            # الف) بررسی حداقل مبلغ بدهی
            min_debt = float(settings.get("min_debt_threshold") or 0.0)
            if min_debt > 0 and float(sub.get("debt_amount") or 0.0) < min_debt:
                continue

            # ب) بررسی بازه تنفس (Cooldown) پس از اتمام محدودیت قبلی
            cooldown_mins = int(settings.get("cooldown_minutes") or 30)
            last_ended_str = sub.get("last_debt_restriction_ended_at")
            if last_ended_str and cooldown_mins > 0:
                try:
                    last_ended_dt = datetime.fromisoformat(last_ended_str)
                    if (now - last_ended_dt).total_seconds() < (cooldown_mins * 60):
                        stats["skipped_cooldown"] += 1
                        continue
                except Exception:
                    pass

            # ج) بررسی سقف دفعات قطع در روز
            daily_limit = int(settings.get("daily_restriction_limit") or 0)
            if daily_limit > 0 and last_ended_str and str(last_ended_str)[:10] == today_str:
                restrictions_count = int(sub.get("debt_restrictions_count") or 0)
                if restrictions_count >= daily_limit:
                    continue

            is_online = bool(sub.get("is_online"))
            current_used = float(sub.get("data_used") or 0.0)

            # د) مقداردهی اولیه نشست مصرف اگر قبلاً ثبت نشده باشد
            sess_start_str = sub.get("debt_restriction_session_start")
            sess_base_usage = sub.get("debt_restriction_session_usage")

            if sess_base_usage is None:
                sess_base_usage = current_used
                cursor.execute("""
                    UPDATE subscriptions SET
                        debt_restriction_session_usage = ?
                    WHERE id = ?
                """, (sess_base_usage, sub_id))
                conn.commit()
                sub["debt_restriction_session_usage"] = sess_base_usage

            # اگر کاربر آنلاین است ولی زمان شروع نشست ثبت نشده، زمان فعلی را شروع نشست قرار می‌دهیم
            if is_online and not sess_start_str:
                sess_start_str = now_iso
                cursor.execute("""
                    UPDATE subscriptions SET
                        debt_restriction_session_start = ?,
                        debt_restriction_session_usage = ?
                    WHERE id = ?
                """, (sess_start_str, current_used, sub_id))
                conn.commit()
                sub["debt_restriction_session_start"] = sess_start_str

            # اگر کاربر آفلاین است، نشست مداوم آنلاین ریست می‌شود تا تنها اتصال مداوم مشمول قطع گردد
            if not is_online and sess_start_str:
                cursor.execute("""
                    UPDATE subscriptions SET
                        debt_restriction_session_start = NULL
                    WHERE id = ?
                """, (sub_id,))
                conn.commit()
                sub["debt_restriction_session_start"] = None
                sess_start_str = None

            # هـ) سنجش شروط محدودیت:
            should_restrict = False
            trigger_reason = ""
            reason_code = "traffic"

            # شرط ۱: سقف اتصال مداوم (continuous_usage_minutes یا time_limit_hours)
            cont_mins = float(settings.get("continuous_usage_minutes") or 0.0)
            if cont_mins <= 0 and float(settings.get("time_limit_hours") or 0.0) > 0:
                cont_mins = float(settings["time_limit_hours"]) * 60.0

            if is_online and cont_mins > 0 and sess_start_str:
                try:
                    s_dt = datetime.fromisoformat(sess_start_str)
                    elapsed_mins = (now - s_dt).total_seconds() / 60.0
                    if elapsed_mins >= cont_mins:
                        should_restrict = True
                        reason_code = "continuous"
                        trigger_reason = f"اتصال پیوسته بیش از {int(cont_mins)} دقیقه ({int(elapsed_mins)} دقیقه آنلاین)"
                except Exception:
                    pass

            # شرط ۲: سقف ترافیک مصرفی در این چرخه (traffic_limit_mb)
            traffic_limit_mb = float(settings.get("traffic_limit_mb") or 0.0)
            if not should_restrict and traffic_limit_mb > 0:
                base_gb = float(sub.get("debt_restriction_session_usage") or 0.0)
                used_diff_mb = max(0.0, (current_used - base_gb) * 1024.0)
                if used_diff_mb >= traffic_limit_mb:
                    should_restrict = True
                    reason_code = "traffic"
                    trigger_reason = f"مصرف بیش از {traffic_limit_mb:g} مگابایت در چرخه جاری ({int(used_diff_mb)} MB)"

            # شرط ۳: محدودیت در ساعات اوج مصرف (Peak Hours)
            if not should_restrict and settings.get("peak_hours_enabled"):
                p_start = int(settings.get("peak_start_hour") or 18)
                p_end = int(settings.get("peak_end_hour") or 24)
                cur_hour = now.hour
                if p_start <= cur_hour < p_end:
                    should_restrict = True
                    reason_code = "peak"
                    trigger_reason = f"قرار داشتن در ساعات اوج مصرف شبکه ({p_start}:00 الی {p_end}:00)"

            # شرط ۴: سقف کل مصرف روزانه (daily_traffic_limit_mb)
            daily_traffic_mb = float(settings.get("daily_traffic_limit_mb") or 0.0)
            if not should_restrict and daily_traffic_mb > 0:
                base_gb = float(sub.get("debt_restriction_session_usage") or 0.0)
                used_diff_mb = max(0.0, (current_used - base_gb) * 1024.0)
                if used_diff_mb >= daily_traffic_mb:
                    should_restrict = True
                    reason_code = "daily"
                    trigger_reason = f"رسیدن به سقف مجاز مصرف روزانه ({int(daily_traffic_mb)} MB)"

            # و) اعمال جریمه در صورت نقض هر یک از شروط
            if should_restrict:
                penalty_mins = int(settings.get("penalty_duration_minutes") or 120)
                restricted_until = (now + timedelta(minutes=penalty_mins)).isoformat()

                # قطع موقت در هیدیفای
                if hidify_update_func and sub.get("hidify_uuid"):
                    try:
                        hidify_update_func(
                            uuid=sub["hidify_uuid"],
                            enable=False,
                            is_active=False,
                            reseller_id=sub.get("reseller_id")
                        )
                    except Exception as e_dis:
                        logger.warning(f"Error disabling user {sub['hidify_uuid']} on Hiddify: {e_dis}")

                cursor.execute("""
                    UPDATE subscriptions SET
                        status = 'disabled',
                        debt_restricted_until = ?,
                        debt_restrictions_count = COALESCE(debt_restrictions_count, 0) + 1,
                        debt_restriction_session_start = NULL,
                        updated_at = ?
                    WHERE id = ?
                """, (restricted_until, now_iso, sub_id))
                conn.commit()

                # ثبت در لاگ سیستم
                try:
                    acc_name = sub.get("account_name") or f"sub_{sub_id}"
                    debt_amt = int(sub.get("debt_amount") or 0)
                    if hasattr(db_instance, "add_system_log"):
                        db_instance.add_system_log(
                            category="debt",
                            action="restrict",
                            title=f"اعمال وقفه موقت روی اشتراک «{acc_name}»",
                            description=f"اشتراک «{acc_name}» به علت {trigger_reason} و داشتن بدهی {debt_amt:,} ت به مدت {penalty_mins} دقیقه موقتاً متوقف شد.",
                            actor_type="system",
                            actor_id=0,
                            actor_name="DebtRestrictionService",
                            details={
                                "sub_id": sub_id,
                                "account_name": acc_name,
                                "debt_amount": debt_amt,
                                "trigger_reason": trigger_reason,
                                "reason_code": reason_code,
                                "penalty_duration_minutes": penalty_mins,
                                "restricted_until": restricted_until
                            }
                        )
                except Exception:
                    pass

                # ارسال پیامک و تلگرام شروع محدودیت با قالب متناسب
                send_debt_restriction_notification(
                    sub=sub,
                    event_type="start",
                    reason_code=reason_code,
                    trigger_reason=trigger_reason,
                    settings=settings,
                    db_instance=db_instance
                )

                stats["restricted"] += 1
                logger.info(f"Sub #{sub_id} ({sub.get('account_name')}) restricted for {penalty_mins}m due to: {trigger_reason}")
    except Exception as e2:
        logger.error(f"Error in phase 2 (triggering debt restrictions): {e2}")
    finally:
        conn.close()

    # ════════════════════════════════════════════════════════════════════
    # فاز ۳: بررسی اشتراک‌های منقضی‌شده بر اساس مهلت تسویه بدهی (Auto-Disable Deadline)
    # ════════════════════════════════════════════════════════════════════
    try:
        deadline_stats = process_debt_auto_disable_deadlines(db_instance, hidify_update_func)
        stats["deadline_disabled"] = deadline_stats.get("disabled", 0)
    except Exception as ed:
        logger.error(f"Error in phase 3 (debt auto-disable deadlines): {ed}")

    return stats
