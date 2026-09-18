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

# ─── تنظیمات پیش‌فرض سیستم محدودیت بدهی ───
DEFAULT_DEBT_RESTRICTION_SETTINGS: Dict[str, Any] = {
    "enabled": False,                       # فعال‌سازی کلی سیستم محدودیت
    "time_limit_hours": 3.0,               # سقف استفاده مداوم (ساعت) - ۰ به معنی غیرفعال
    "traffic_limit_mb": 500,               # سقف مصرف در نشست جاری (مگابایت) - ۰ به معنی غیرفعال
    "penalty_duration_minutes": 15,        # مدت زمان غیرفعال‌سازی موقت در هیدیفای (دقیقه)
    "cooldown_minutes": 30,                # فاصله تنفس بین محدودیت‌ها پس از فعال‌سازی مجدد (دقیقه)
    "notify_telegram": True,               # چک‌باکس: ارسال به تلگرام
    "notify_sms": True,                    # چک‌باکس: ارسال به پیامک
    "notify_on_start": True,               # چک‌باکس: ارسال پیام در زمان شروع محدودیت
    "notify_on_end": True,                 # چک‌باکس: ارسال پیام در زمان پایان محدودیت و اتصال مجدد
    "start_message_template": (
        "⚠️ <b>کاربر گرامی، با سلام و احترام</b>\n\n"
        "اشتراک «{account_name}» به دلیل بدهی پرداخت‌نشده ({debt_amount} تومان) موقتاً به مدت <b>{penalty_minutes} دقیقه</b> غیرفعال گردید.\n"
        "علت محدودیت: {trigger_reason}\n\n"
        "💳 جهت رفع دائم محدودیت و برقراری دائم سرویس، لطفاً نسبت به تسویه بدهی اقدام نمایید."
    ),
    "end_message_template": (
        "✅ <b>کاربر گرامی، با سلام و احترام</b>\n\n"
        "دوره محدودیت موقت اشتراک «{account_name}» به پایان رسید و اتصال شما مجدداً برقرار گردید.\n"
        "🙏 لطفاً جهت جلوگیری از اعمال مجدد محدودیت، در اسرع وقت نسبت به تسویه بدهی خود اقدام فرمایید."
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
    penalty_mins = int(settings.get("penalty_duration_minutes") or 15)
    portal_url = get_portal_url(sub, db_instance)

    msg = template
    msg = msg.replace("{account_name}", acc_name)
    msg = msg.replace("{debt_amount}", debt_formatted)
    msg = msg.replace("{penalty_minutes}", str(penalty_mins))
    msg = msg.replace("{trigger_reason}", trigger_reason or "عدم تسویه بدهی")
    msg = msg.replace("{portal_url}", portal_url)
    return msg


def send_debt_restriction_notification(
    sub: dict,
    event_type: str,  # 'start' or 'end'
    trigger_reason: str,
    settings: dict,
    db_instance
):
    """ارسال هوشمند اعلان شروع یا پایان محدودیت به تلگرام و پیامک بر اساس تنظیمات"""
    # بررسی آیا اعلان برای این رویداد فعال است
    if event_type == "start" and not settings.get("notify_on_start", True):
        return
    if event_type == "end" and not settings.get("notify_on_end", True):
        return

    # انتخاب قالب پیام
    if event_type == "start":
        raw_tpl = settings.get("start_message_template") or DEFAULT_DEBT_RESTRICTION_SETTINGS["start_message_template"]
    else:
        raw_tpl = settings.get("end_message_template") or DEFAULT_DEBT_RESTRICTION_SETTINGS["end_message_template"]

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

    # ۱. ارسال تلگرام (در صورت تیک خوردن چک‌باکس و وجود شناسه تلگرام)
    if settings.get("notify_telegram", True) and telegram_id and int(telegram_id) > 0:
        try:
            from dashboard import send_telegram_msg
            bot_token = None
            if reseller_id and hasattr(db_instance, "get_reseller"):
                r_row = db_instance.get_reseller(reseller_id) or {}
                bot_token = r_row.get("bot_token")
            send_telegram_msg(chat_id=int(telegram_id), text=msg_html, parse_mode="HTML", bot_token=bot_token)
            logger.info(f"Sent debt restriction {event_type} Telegram msg to {telegram_id} for sub {sub.get('id')}")
        except Exception as e_tg:
            logger.warning(f"Failed to send debt restriction Telegram to {telegram_id}: {e_tg}")

    # ۲. ارسال پیامک (در صورت تیک خوردن چک‌باکس و وجود شماره تلفن همراه)
    if settings.get("notify_sms", True) and phone_number:
        try:
            import re
            from sms_service import send_sms
            # تبدیل تگ‌های HTML به متن ساده برای پیامک
            clean_sms_text = re.sub(r"<[^>]+>", "", msg_html)
            send_sms(to_phone=phone_number, message=clean_sms_text, db_instance=db_instance, reseller_id=reseller_id)
            logger.info(f"Sent debt restriction {event_type} SMS to {phone_number} for sub {sub.get('id')}")
        except Exception as e_sms:
            logger.warning(f"Failed to send debt restriction SMS to {phone_number}: {e_sms}")


def re_enable_if_restricted(sub_id: int, db_instance, hidify_update_func=None) -> bool:
    """
    در صورت تسویه بدهی یا خروج دستی از گروه محدودیت، اگر اشتراک مسدود بود
    بلافاصله در هیدیفای فعال شده و محدودیت موقت لغو می‌گردد.
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
        was_restricted = bool(sub.get("debt_restricted_until"))

        cursor.execute("""
            UPDATE subscriptions SET
                in_debt_restriction = 0,
                debt_restricted_until = NULL,
                debt_restriction_session_start = NULL,
                status = CASE WHEN status = 'disabled' AND debt_restricted_until IS NOT NULL THEN 'active' ELSE status END,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (sub_id,))
        conn.commit()
        conn.close()

        # فعال‌سازی فوری در هیدیفای اگر بابت بدهی قطع بوده باشد
        if was_restricted and hidify_update_func and sub.get("hidify_uuid"):
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
                    trigger_reason="پایان دوره محدودیت زمانی",
                    settings=settings,
                    db_instance=db_instance
                )
                stats["re_enabled"] += 1
                logger.info(f"Sub #{sub_id} ({sub.get('account_name')}) temporary debt restriction ended. Re-enabled.")
    except Exception as e1:
        logger.error(f"Error in phase 1 (re-enabling debt restrictions): {e1}")

    # ════════════════════════════════════════════════════════════════════
    # فاز ۲: بررسی مشتریان بدهکار فعال عضو گروه محدودیت و اعمال جریمه در صورت تخلف
    # ════════════════════════════════════════════════════════════════════
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

            # الف) بررسی بازه تنفس (Cooldown) پس از اتمام محدودیت قبلی
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

            is_online = bool(sub.get("is_online"))
            current_used = float(sub.get("data_used") or 0.0)

            # ب) مقداردهی اولیه نشست مصرف اگر قبلاً ثبت نشده باشد
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

            # اگر کاربر آنلاین است ولی زمان شروع نشست ثبت نشده، زمان فعلی را به عنوان شروع نشست در نظر می‌گیریم
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
                sub["debt_restriction_session_usage"] = current_used

            # اگر کاربر آفلاین است و بیش از ۲۰ دقیقه از آخرین فعالیت گذشته، می‌توان نشست اتصال را ریست کرد
            if not is_online and sess_start_str:
                last_online_str = sub.get("last_online")
                if last_online_str:
                    try:
                        last_on_dt = datetime.fromisoformat(last_online_str)
                        if (now - last_on_dt).total_seconds() > 1200:  # 20 minutes offline
                            cursor.execute("""
                                UPDATE subscriptions SET
                                    debt_restriction_session_start = NULL,
                                    debt_restriction_session_usage = ?
                                WHERE id = ?
                            """, (current_used, sub_id))
                            conn.commit()
                            continue
                    except Exception:
                        pass

            # ج) سنجش شروط محدودیت:
            should_restrict = False
            trigger_reason = ""

            # شرط ۱: سقف زمانی اتصال مداوم (time_limit_hours)
            time_limit_hrs = float(settings.get("time_limit_hours") or 0.0)
            if is_online and time_limit_hrs > 0 and sess_start_str:
                try:
                    s_dt = datetime.fromisoformat(sess_start_str)
                    elapsed_hours = (now - s_dt).total_seconds() / 3600.0
                    if elapsed_hours >= time_limit_hrs:
                        should_restrict = True
                        trigger_reason = f"اتصال مداوم بیش از {time_limit_hrs:g} ساعت ({int(elapsed_hours * 60)} دقیقه)"
                except Exception:
                    pass

            # شرط ۲: سقف ترافیک مصرفی در این نشست/دوره (traffic_limit_mb)
            traffic_limit_mb = float(settings.get("traffic_limit_mb") or 0.0)
            if not should_restrict and traffic_limit_mb > 0:
                base_gb = float(sub.get("debt_restriction_session_usage") or 0.0)
                used_diff_mb = max(0.0, (current_used - base_gb) * 1024.0)
                if used_diff_mb >= traffic_limit_mb:
                    should_restrict = True
                    trigger_reason = f"مصرف بیش از {traffic_limit_mb:g} مگابایت ترافیک ({int(used_diff_mb)} MB)"

            # د) اعمال جریمه در صورت نقض هر یک از شروط
            if should_restrict:
                penalty_mins = int(settings.get("penalty_duration_minutes") or 15)
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
                    db_instance.add_system_log(
                        category="debt",
                        action="restrict",
                        title=f"اعمال محدودیت موقت بدهی روی اشتراک «{acc_name}»",
                        description=f"اشتراک «{acc_name}» به علت {trigger_reason} و داشتن بدهی {debt_amt:,} ت به مدت {penalty_mins} دقیقه موقتاً قطع شد.",
                        actor_type="system",
                        actor_id=0,
                        actor_name="DebtRestrictionService",
                        details={
                            "sub_id": sub_id,
                            "account_name": acc_name,
                            "debt_amount": debt_amt,
                            "trigger_reason": trigger_reason,
                            "penalty_duration_minutes": penalty_mins,
                            "restricted_until": restricted_until
                        }
                    )
                except Exception:
                    pass

                # ارسال پیامک و تلگرام شروع محدودیت
                send_debt_restriction_notification(
                    sub=sub,
                    event_type="start",
                    trigger_reason=trigger_reason,
                    settings=settings,
                    db_instance=db_instance
                )

                stats["restricted"] += 1
                logger.info(f"Sub #{sub_id} ({sub.get('account_name')}) temporarily restricted for {penalty_mins}m due to: {trigger_reason}")
    except Exception as e2:
        logger.error(f"Error in phase 2 (triggering debt restrictions): {e2}")
    finally:
        conn.close()

    return stats
