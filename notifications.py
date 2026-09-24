#!/usr/bin/env python3
"""
سیستم اعلان‌های خودکار ربات
- اعلان منقضی شدن اشتراک (۳ روز قبل)
- اعلان نزدیک شدن حجم (۸۰٪)
- یادآوری تمدید روزانه
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta
from database import db
from utils import (
    get_now,
    get_now_tehran,
    get_now_naive,
    get_now_iso,
    gregorian_to_shamsi_full,
    parse_to_tehran_dt,
    is_tehran_hour,
    is_in_quiet_hours,
    TEHRAN_TZ,
)
from sms_service import send_sms
from telegram import InlineKeyboardMarkup, InlineKeyboardButton

logger = logging.getLogger(__name__)


class NotificationScheduler:
    """برنامه‌ریز اعلان‌های خودکار با پشتیبانی از ساعت رسمی تهران"""
    
    def __init__(self, bot=None, hidify=None):
        self.bot = bot
        self.hidify = hidify
        self.running = False
        self.task = None
        self.last_daily_reminder_date = None
    
    def set_bot(self, bot):
        """تنظیم ربات"""
        self.bot = bot

    def set_hidify(self, hidify):
        """تنظیم کلاینت هیدیفای برای استعلام مصرف زنده"""
        self.hidify = hidify
    
    async def start(self):
        """شروع برنامه‌ریز"""
        if self.running:
            return
        self.running = True
        self.task = asyncio.create_task(self._run_loop())
        self.queue_task = asyncio.create_task(self._run_queue_check_loop())
        logger.info("Notification scheduler and queue check worker started")
    
    async def stop(self):
        """توقف برنامه‌ریز"""
        self.running = False
        for t in [self.task, getattr(self, "queue_task", None)]:
            if t:
                t.cancel()
                try:
                    await t
                except asyncio.CancelledError:
                    pass
        logger.info("Notification scheduler stopped")
    
    async def _run_queue_check_loop(self):
        """حلقه اختصاصی بررسی بلادرنگ صف تمدید هر ۶۰ ثانیه"""
        await asyncio.sleep(10)
        while self.running:
            try:
                from dashboard import process_subscription_queue
                await asyncio.to_thread(process_subscription_queue)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in queue check loop: {e}")
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                break

    async def _run_loop(self):
        """حلقه اصلی بررسی اعلان‌ها منطبق با ساعت تهران (بررسی هر ۱۵ دقیقه)"""
        await asyncio.sleep(10)
        while self.running:
            try:
                await self._check_all_notifications()
                # بررسی هر ۱۵ دقیقه جهت تطبیق دقیق با ساعت یادآوری تهران
                await asyncio.sleep(900)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in notification loop: {e}")
                await asyncio.sleep(120)
    
    async def _check_all_notifications(self):
        """بررسی تمام اعلان‌ها با ساعت رسمی تهران و همگام‌سازی مصرف زنده هیدیفای"""
        if not self.bot:
            return
        
        try:
            # ۱. دریافت آخرین اطلاعات مصرف و وضعیت زنده از سرور هیدیفای
            if self.hidify:
                try:
                    h_users = await self.hidify.get_users()
                    if h_users and isinstance(h_users, list):
                        db.sync_from_hidify(h_users)
                        logger.info(f"Live Hiddify usage synced before notification check ({len(h_users)} users)")

                    # بررسی و فعال‌سازی خودکار بسته‌های در صف تمدید
                    try:
                        from dashboard import process_subscription_queue
                        await asyncio.to_thread(process_subscription_queue)
                    except Exception as e_q:
                        logger.warning(f"Error checking subscription queue in notifications: {e_q}")
                except Exception as e:
                    logger.warning(f"Could not live sync Hiddify users for notifications: {e}")

            # ۲. بررسی زمان‌بندی ساعت یادآوری و وضعیت ساعات سکوت به وقت تهران
            now_tehran = get_now()
            today_tehran_str = now_tehran.strftime("%Y-%m-%d")
            current_tehran_hour = now_tehran.hour

            reminder_settings = db.get_reminder_settings()
            reminder_enabled = reminder_settings.get("reminder_notification_enabled", True)
            target_reminder_hour = int(reminder_settings.get("reminder_notification_hour", 12))
            quiet_enabled = reminder_settings.get("reminder_quiet_hours_enabled", True)
            quiet_start = int(reminder_settings.get("reminder_quiet_start", 23))
            quiet_end = int(reminder_settings.get("reminder_quiet_end", 9))

            in_quiet = False
            if quiet_enabled:
                in_quiet = is_in_quiet_hours(quiet_start, quiet_end)

            # آیا زمان اجرای چرخه یادآوری روزانه است؟
            # اگر یادآوری فعال است، در ساعات سکوت نیستیم، ساعت تهران >= ساعت هدف است، و امروز هنوز اجرا نشده است:
            is_daily_reminder_time = False
            if reminder_enabled and not in_quiet:
                if current_tehran_hour >= target_reminder_hour and self.last_daily_reminder_date != today_tehran_str:
                    is_daily_reminder_time = True
                    logger.info(f"Triggering daily reminder cycle at Tehran hour {current_tehran_hour} (target: {target_reminder_hour}:00)")

            # ۳. دریافت تمام کاربران فعال
            users = db.get_all_users()
            
            for user in users:
                telegram_id = user.get("telegram_id")
                if not telegram_id:
                    continue
                
                # دریافت اشتراک‌های فعال
                subscriptions = db.get_user_subscriptions(telegram_id, status="active")
                
                for sub in subscriptions:
                    # بررسی انقضا در ساعت یادآوری روزانه
                    if is_daily_reminder_time:
                        await self._check_expiration(telegram_id, sub)
                    # بررسی مصرف حجم (پیوسته در هر چرخه با توجه به ساعات سکوت)
                    await self._check_usage(telegram_id, sub, in_quiet=in_quiet)
                
                # بررسی اشتراک‌های منقضی شده برای یادآوری روزانه تمدید در ساعت یادآوری تهران
                if is_daily_reminder_time:
                    expired_subs = db.get_user_subscriptions(telegram_id, status="expired")
                    if expired_subs:
                        await self._send_renewal_reminder(telegram_id, expired_subs)

            # ۴. بررسی اشتراک‌های حضوری و فاقد تلگرام (ارسال پیامک با لینک اختصاصی تمدید)
            try:
                conn = db.get_connection()
                offline_subs = conn.execute("""
                    SELECT * FROM subscriptions 
                    WHERE status='active' AND (telegram_id IS NULL OR telegram_id=0) AND phone_number IS NOT NULL AND phone_number != ''
                """).fetchall()
                conn.close()

                for o_sub in offline_subs:
                    await self._check_offline_subscription(
                        dict(o_sub),
                        check_expiration=is_daily_reminder_time,
                        check_usage=True,
                        in_quiet=in_quiet
                    )
            except Exception as e_off:
                logger.error(f"Error checking offline subscriptions: {e_off}")
            
            # در صورت اجرای موفق یادآوری روزانه، تاریخ امروز به وقت تهران ثبت شود
            if is_daily_reminder_time:
                self.last_daily_reminder_date = today_tehran_str
                logger.info(f"Daily reminder cycle finished successfully for Tehran date: {today_tehran_str}")

            # ۵. بررسی هشدارهای سررسید و ترافیک مدیریت با ساعت تهران
            await self._check_admin_reminders()
            
            logger.info("Notifications checked successfully")
        except Exception as e:
            logger.error(f"Error checking notifications: {e}")

    def _build_portal_url(self, subscription: dict) -> str:
        """ساخت آدرس پورتال دائمی و اختصاصی مشتری بر اساس UUID یا شناسه اشتراک"""
        reseller_id = subscription.get("reseller_id")
        domain = ""
        if reseller_id:
            try:
                r_info = db.get_reseller(reseller_id) or {}
                domain = r_info.get("domain")
            except Exception:
                domain = ""
        if not domain:
            domain = db.get_setting("custom_domain") or os.getenv("PANEL_DOMAIN", "")
        token = subscription.get("hidify_uuid") or subscription.get("id")
        if domain and token:
            return f"https://{domain}/user/{token}"
        return ""

    async def _send_notification_message(self, telegram_id: int, text: str, reply_markup=None, reseller_id=None) -> bool:
        """ارسال هوشمند پیام اعلان از طریق ربات مربوطه (ربات نماینده یا ربات اصلی مدیریت)"""
        r_id = int(reseller_id) if reseller_id else 0
        if r_id > 0:
            # ۱. اولویت اول: ارسال مستقیم از نمونه فعال ربات در multibot_manager
            try:
                from multibot_manager import multibot_manager
                inst = multibot_manager.instances.get(r_id)
                if inst and inst.is_running and inst.application and inst.application.bot:
                    await inst.application.bot.send_message(
                        chat_id=telegram_id,
                        text=text,
                        parse_mode="HTML",
                        reply_markup=reply_markup
                    )
                    return True
            except Exception as ex_mb:
                logger.debug(f"Direct multibot instance send failed for reseller {r_id}: {ex_mb}")

            # ۲. اولویت دوم: ارسال با توکن ربات نماینده
            try:
                from dashboard import send_telegram_msg
                r_info = db.get_reseller(r_id) or {}
                r_tok = r_info.get("bot_token")
                if r_tok:
                    rm_dict = reply_markup.to_dict() if hasattr(reply_markup, "to_dict") else reply_markup
                    if send_telegram_msg(telegram_id, text, reply_markup=rm_dict, bot_token=r_tok):
                        return True
            except Exception as ex_tok:
                logger.debug(f"Token send failed for reseller {r_id}: {ex_tok}")

        # ۳. ارسال از طریق ربات اصلی مدیریت (برای اشتراک‌های مدیریت یا در صورت در دسترس نبودن ربات نماینده)
        if self.bot:
            try:
                await self.bot.send_message(
                    chat_id=telegram_id,
                    text=text,
                    parse_mode="HTML",
                    reply_markup=reply_markup
                )
                return True
            except Exception as e:
                logger.error(f"Error sending message via admin bot to {telegram_id}: {e}")
                return False
        return False

    async def _check_expiration(self, telegram_id, subscription):
        """بررسی منقضی شدن اشتراک بر اساس تاریخ انقضا و ساعت تهران"""
        try:
            start_date_str = subscription.get("start_date")
            duration = subscription.get("duration", 30)
            expire_date_str = subscription.get("expire_date")
            
            expire_dt = None
            if expire_date_str:
                expire_dt = parse_to_tehran_dt(expire_date_str)

            if not expire_dt and start_date_str:
                start_dt = parse_to_tehran_dt(start_date_str) or get_now()
                expire_dt = start_dt + timedelta(days=duration)

            if not expire_dt:
                return

            now = get_now()
            days_left = (expire_dt.date() - now.date()).days
            
            # اعلان ۳ روز قبل
            if 0 < days_left <= 3:
                sub_id = subscription.get("id")
                notif_type = f"expiring_{sub_id}_{days_left}d"
                
                if not db.was_notification_sent(telegram_id, notif_type, sub_id):
                    plan_name = subscription.get("plan_name", "نامشخص")
                    expire_shamsi = gregorian_to_shamsi_full(expire_dt.isoformat())
                    
                    text = f"""
⚠️ <b>هشدار انقضای اشتراک ({days_left} روز باقیمانده)</b>

📋 نام بسته: <b>{plan_name}</b>
📅 تاریخ انقضا: <b>{expire_shamsi}</b>
⏰ مهلت باقیمانده: <b>{days_left} روز</b>

💡 <i>جهت جلوگیری از قطع اتصال اینترنت، لطفاً پیش از موعد نسبت به تمدید اقدام فرمایید.</i>
"""
                    portal_url = self._build_portal_url(subscription)
                    reseller_id = subscription.get("reseller_id")

                    buttons = []
                    if reseller_id and int(reseller_id) > 0:
                        buttons.append([InlineKeyboardButton("🔄 تمدید سریع در ربات", callback_data=f"r_renew_{sub_id}")])
                    else:
                        buttons.append([InlineKeyboardButton("🔄 تمدید سریع در ربات", callback_data=f"renew_sub_{sub_id}")])

                    if portal_url:
                        buttons.append([InlineKeyboardButton("🌐 پورتال تمدید آنلاین (بدون فیلتر)", url=portal_url)])
                    else:
                        buttons.append([InlineKeyboardButton("📱 باز کردن پنل هوشمند (Mini App)", callback_data=f"open_sub_{sub_id}")])

                    reply_markup = InlineKeyboardMarkup(buttons)
                    try:
                        sent = await self._send_notification_message(telegram_id, text, reply_markup, reseller_id=reseller_id)
                        if sent:
                            db.save_notification(telegram_id, notif_type, sub_id)
                            logger.info(f"Expiration notification ({days_left}d) sent to Telegram {telegram_id} for tenant {reseller_id or 0}")
                    except Exception as e:
                        logger.error(f"Error sending expiration notification: {e}")

                    # ارسال پیامک هشدار به شماره کاربر (در صورت وجود)
                    user_phone = subscription.get("phone_number")
                    if not user_phone:
                        user_obj = db.get_user(telegram_id)
                        if user_obj:
                            user_phone = user_obj.get("phone_number")
                    if user_phone:
                        try:
                            if portal_url:
                                sms_text = f"کاربر گرامی، کمتر از {days_left} روز از مهلت اشتراک شما باقی مانده است. جهت تمدید آنلاین اشتراک به لینک زیر مراجعه فرمایید:\n{portal_url}"
                            else:
                                sms_text = f"کاربر گرامی، کمتر از {days_left} روز از مهلت اشتراک شما باقی مانده است. جهت تمدید به ربات مراجعه نمایید."
                            send_sms(user_phone, sms_text, db_instance=db)
                        except Exception as e:
                            logger.error(f"Error sending expiration SMS: {e}")
            
            # اعلان روز منقضی شدن
            elif days_left == 0:
                sub_id = subscription.get("id")
                notif_type = f"expired_{sub_id}"
                
                if not db.was_notification_sent(telegram_id, notif_type, sub_id):
                    plan_name = subscription.get("plan_name", "نامشخص")
                    portal_url = self._build_portal_url(subscription)
                    reseller_id = subscription.get("reseller_id")
                    
                    text = f"""
🔴 <b>اشتراک شما منقضی شد!</b>

📋 بسته: <b>{plan_name}</b>
📅 تاریخ انقضا: <b>امروز</b>

⚠️ سرویس اتصال شما موقتاً قطع شده است.
🔄 با تمدید یا خرید اشتراک، اتصال شما بلافاصله برقرار خواهد شد.
"""
                    exp_buttons = []
                    if reseller_id and int(reseller_id) > 0:
                        exp_buttons.append([InlineKeyboardButton("🔄 تمدید آنی در ربات", callback_data=f"r_renew_{sub_id}")])
                    else:
                        exp_buttons.append([InlineKeyboardButton("🔄 تمدید آنی در ربات", callback_data=f"renew_sub_{sub_id}")])
                    if portal_url:
                        exp_buttons.append([InlineKeyboardButton("🌐 تمدید آنلاین از پورتال", url=portal_url)])
                    reply_markup = InlineKeyboardMarkup(exp_buttons)
                    try:
                        sent = await self._send_notification_message(telegram_id, text, reply_markup, reseller_id=reseller_id)
                        if sent:
                            db.save_notification(telegram_id, notif_type, sub_id)
                            db.update_subscription(sub_id, status="expired")
                            logger.info(f"Expired notification sent to {telegram_id} for tenant {reseller_id or 0}")
                    except Exception as e:
                        logger.error(f"Error sending expired notification: {e}")

                    # ارسال پیامک انقضا
                    user_phone = subscription.get("phone_number")
                    if not user_phone:
                        user_obj = db.get_user(telegram_id)
                        if user_obj:
                            user_phone = user_obj.get("phone_number")
                    if user_phone:
                        try:
                            if portal_url:
                                sms_text = f"اشتراک شما ({plan_name}) منقضی شد. جهت تمدید آنلاین:\n{portal_url}"
                            else:
                                sms_text = f"اشتراک شما ({plan_name}) منقضی شد. جهت تمدید و اتصال مجدد به ربات مراجعه کنید."
                            send_sms(user_phone, sms_text, db_instance=db)
                        except Exception as e:
                            logger.error(f"Error sending expired SMS: {e}")
        
        except Exception as e:
            logger.error(f"Error in _check_expiration: {e}")
    
    async def _check_usage(self, telegram_id, subscription, in_quiet: bool = False):
        """بررسی مصرف حجم (۸۰٪ و ۹۵٪ اضطراری) با رعایت ساعات سکوت برای هشدارهای غیراضطراری"""
        try:
            data_limit = subscription.get("data_limit", 0)
            data_used = subscription.get("data_used", 0)
            
            if data_limit <= 0:
                return  # حجم نامحدود
            
            usage_percent = (data_used / data_limit) * 100
            sub_id = subscription.get("id")
            plan_name = subscription.get("plan_name", "نامشخص")
            remaining = data_limit - data_used
            portal_url = self._build_portal_url(subscription)

            # اعلان ۹۵٪ مصرف (هشدار اضطراری) - بدون محدودیت ساعت سکوت
            if usage_percent >= 95:
                notif_type = f"usage_95_{sub_id}"
                if not db.was_notification_sent(telegram_id, notif_type, sub_id):
                    text = f"""
🚨 <b>هشدار اضطراری: حجم اشتراک رو به اتمام است!</b>

📋 بسته: <b>{plan_name}</b>
📊 مصرف: <b>{data_used:.1f} از {data_limit:.1f} گیگابایت</b> ({usage_percent:.1f}%)
💾 ترافیک باقیمانده: <b>{remaining:.1f} گیگابایت</b>

⛔ <i>تنها ۵٪ از ترافیک اشتراک شما باقی مانده است. جهت تداوم اتصال تمدید فرمایید.</i>
"""
                    reseller_id = subscription.get("reseller_id")
                    u_buttons = []
                    if reseller_id and int(reseller_id) > 0:
                        u_buttons.append([InlineKeyboardButton("⚡ تمدید فوری در ربات", callback_data=f"r_renew_{sub_id}")])
                    else:
                        u_buttons.append([InlineKeyboardButton("⚡ تمدید فوری در ربات", callback_data=f"renew_sub_{sub_id}")])
                    if portal_url:
                        u_buttons.append([InlineKeyboardButton("🌐 تمدید آنلاین از پورتال", url=portal_url)])
                    reply_markup = InlineKeyboardMarkup(u_buttons)
                    try:
                        sent = await self._send_notification_message(telegram_id, text, reply_markup, reseller_id=reseller_id)
                        if sent:
                            db.save_notification(telegram_id, notif_type, sub_id)
                            logger.info(f"Critical 95% usage notification sent to {telegram_id} for tenant {reseller_id or 0}")
                    except Exception as e:
                        logger.error(f"Error sending critical usage notification: {e}")

                    user_phone = subscription.get("phone_number")
                    if not user_phone:
                        user_obj = db.get_user(telegram_id)
                        if user_obj:
                            user_phone = user_obj.get("phone_number")
                    if user_phone:
                        try:
                            sms_text = f"هشدار! بیش از ۹۵٪ از حجم اشتراک ({plan_name}) مصرف شده است. تمدید آنلاین:\n{portal_url}" if portal_url else f"هشدار! بیش از ۹۵٪ از حجم اشتراک شما مصرف شده است."
                            send_sms(user_phone, sms_text, db_instance=db)
                        except Exception as e:
                            logger.error(f"Error sending 95% usage SMS: {e}")

            # اعلان ۸۰٪ مصرف (در ساعات سکوت شبانه ارسال نمی‌شود)
            elif usage_percent >= 80:
                if in_quiet:
                    return
                notif_type = f"usage_80_{sub_id}"
                if not db.was_notification_sent(telegram_id, notif_type, sub_id):
                    text = f"""
📊 <b>هشدار مصرف حجم (۸۰٪ مصرف شده)</b>

📋 بسته: <b>{plan_name}</b>
📊 مصرف: <b>{data_used:.1f} از {data_limit:.1f} گیگابایت</b> ({usage_percent:.1f}%)
💾 حجم باقیمانده: <b>{remaining:.1f} گیگابایت</b>

💡 <i>بیش از ۸۰٪ حجم اشتراک شما مصرف شده است.</i>
"""
                    reseller_id = subscription.get("reseller_id")
                    u_buttons = []
                    if reseller_id and int(reseller_id) > 0:
                        u_buttons.append([InlineKeyboardButton("🔄 تمدید اشتراک در ربات", callback_data=f"r_renew_{sub_id}")])
                    else:
                        u_buttons.append([InlineKeyboardButton("🔄 تمدید اشتراک در ربات", callback_data=f"renew_sub_{sub_id}")])
                    if portal_url:
                        u_buttons.append([InlineKeyboardButton("🌐 تمدید آنلاین از پورتال", url=portal_url)])
                    reply_markup = InlineKeyboardMarkup(u_buttons)
                    try:
                        sent = await self._send_notification_message(telegram_id, text, reply_markup, reseller_id=reseller_id)
                        if sent:
                            db.save_notification(telegram_id, notif_type, sub_id)
                            logger.info(f"Usage 80% notification sent to {telegram_id} for tenant {reseller_id or 0}")
                    except Exception as e:
                        logger.error(f"Error sending usage notification: {e}")

                    user_phone = subscription.get("phone_number")
                    if not user_phone:
                        user_obj = db.get_user(telegram_id)
                        if user_obj:
                            user_phone = user_obj.get("phone_number")
                    if user_phone:
                        try:
                            if portal_url:
                                sms_text = f"کاربر گرامی، کمتر از ۲۰٪ از حجم بسته شما باقی مانده است. جهت تمدید آنلاین اشتراک به لینک زیر مراجعه فرمایید:\n{portal_url}"
                            else:
                                sms_text = f"کاربر گرامی، کمتر از ۲۰٪ از حجم بسته شما باقی مانده است. جهت تمدید به ربات مراجعه نمایید."
                            send_sms(user_phone, sms_text, db_instance=db)
                        except Exception as e:
                            logger.error(f"Error sending 80% usage SMS: {e}")
        
        except Exception as e:
            logger.error(f"Error in _check_usage: {e}")

    async def _check_offline_subscription(self, subscription, check_expiration: bool = True, check_usage: bool = True, in_quiet: bool = False):
        """بررسی اشتراک‌های حضوری و فاقد تلگرام و ارسال پیامک تمدید با لینک اختصاصی به وقت تهران"""
        try:
            phone = subscription.get("phone_number")
            if not phone:
                return

            sub_id = subscription.get("id")
            plan_name = subscription.get("plan_name", "اشتراک")
            portal_url = self._build_portal_url(subscription)

            # ۱. بررسی تاریخ انقضا در ساعت یادآوری روزانه تهران (۳ روز مانده)
            if check_expiration:
                expire_date_str = subscription.get("expire_date")
                if expire_date_str:
                    try:
                        exp_dt = parse_to_tehran_dt(expire_date_str)
                        if exp_dt:
                            days_left = (exp_dt.date() - get_now().date()).days
                            if 0 < days_left <= 3:
                                notif_type = f"offline_expiring_{sub_id}_{days_left}d"
                                if not db.was_notification_sent(0, notif_type, sub_id):
                                    sms_text = f"کاربر گرامی، کمتر از {days_left} روز از مهلت اشتراک شما باقی مانده است. جهت تمدید آنلاین اشتراک به لینک زیر مراجعه فرمایید:\n{portal_url}"
                                    send_sms(phone, sms_text, db_instance=db)
                                    db.save_notification(0, notif_type, sub_id)
                                    logger.info(f"Offline expiration SMS ({days_left}d) sent to {phone} at Tehran time")
                    except Exception as e:
                        logger.debug(f"Error parsing offline expire date: {e}")

            # ۲. بررسی مصرف حجم (۸۰٪ مصرف) با رعایت ساعات سکوت شبانه
            if check_usage and not in_quiet:
                data_limit = float(subscription.get("data_limit") or 0)
                data_used = float(subscription.get("data_used") or 0)
                if data_limit > 0:
                    usage_percent = (data_used / data_limit) * 100
                    if usage_percent >= 80:
                        notif_type = f"offline_usage_80_{sub_id}"
                        if not db.was_notification_sent(0, notif_type, sub_id):
                            sms_text = f"کاربر گرامی، کمتر از ۲۰٪ از حجم بسته شما باقی مانده است. جهت تمدید آنلاین اشتراک به لینک زیر مراجعه فرمایید:\n{portal_url}"
                            send_sms(phone, sms_text, db_instance=db)
                            db.save_notification(0, notif_type, sub_id)
                            logger.info(f"Offline usage 80% SMS sent to {phone}")
        except Exception as ex:
            logger.error(f"Error in _check_offline_subscription: {ex}")
    
    async def _send_renewal_reminder(self, telegram_id, expired_subs=None):
        """ارسال یادآوری روزانه تمدید در ساعت تعیین‌شده تهران با تفکیک مدیریت و نمایندگان"""
        try:
            today_str = get_now().strftime("%Y%m%d")

            subs_by_reseller = {}
            if expired_subs and isinstance(expired_subs, list):
                for s in expired_subs:
                    rid = s.get("reseller_id") or 0
                    subs_by_reseller.setdefault(rid, []).append(s)
            else:
                subs_by_reseller[0] = []

            for r_id, subs in subs_by_reseller.items():
                notif_type = f"daily_renewal_{today_str}_res_{r_id}" if r_id else f"daily_renewal_{today_str}"
                if db.was_notification_sent(telegram_id, notif_type):
                    continue

                portal_url = ""
                buttons = []
                if subs:
                    first_sub = subs[0]
                    portal_url = self._build_portal_url(first_sub)
                    sub_id = first_sub.get("id")
                    if r_id > 0:
                        buttons.append([InlineKeyboardButton("🔄 تمدید اشتراک در ربات", callback_data=f"r_renew_{sub_id}")])
                    else:
                        buttons.append([InlineKeyboardButton("🔄 تمدید اشتراک در ربات", callback_data=f"renew_sub_{sub_id}")])
                else:
                    if r_id > 0:
                        buttons.append([InlineKeyboardButton("🛒 خرید اشتراک جدید", callback_data="r_plans")])
                    else:
                        buttons.append([InlineKeyboardButton("🛒 خرید اشتراک جدید", callback_data="buy_service")])

                if portal_url:
                    buttons.append([InlineKeyboardButton("🌐 پورتال تمدید آنلاین (بدون فیلتر)", url=portal_url)])

                reply_markup = InlineKeyboardMarkup(buttons)
                
                text = """
💡 <b>یادآوری تمدید اشتراک</b>

اشتراک شما منقضی شده است.
جهت اتصال مجدد به شبکه و تداوم سرویس، لطفاً نسبت به تمدید یا خرید بسته جدید اقدام فرمایید.

⏰ <i>این یادآوری روزانه بر اساس ساعت رسمی تهران ارسال گردیده است.</i>
"""
                sent = await self._send_notification_message(telegram_id, text, reply_markup, reseller_id=r_id)
                if sent:
                    db.save_notification(telegram_id, notif_type)
                    logger.info(f"Renewal reminder ({today_str}) sent to {telegram_id} for tenant {r_id}")
        
        except Exception as e:
            logger.error(f"Error in _send_renewal_reminder: {e}")
    
    async def send_manual_notification(self, telegram_id, message):
        """ارسال اعلان دستی"""
        try:
            if self.bot:
                await self.bot.send_message(
                    chat_id=telegram_id,
                    text=message,
                    parse_mode="HTML"
                )
                return True
            return False
        except Exception as e:
            logger.error(f"Error sending manual notification: {e}")
            return False

    async def _check_admin_reminders(self):
        """بررسی هشدارهای سررسید و ترافیک مدیریت با ساعت رسمی تهران و ارسال به تلگرام/پیامک"""
        from bot import ADMIN_ID
        if not self.bot:
            return
            
        try:
            conn = db.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM admin_reminders WHERE is_active = 1 AND is_done = 0")
            reminders = [dict(r) for r in cursor.fetchall()]
            
            now_tehran = get_now()
            now_iso = now_tehran.isoformat()
            one_day_ago = now_tehran - timedelta(days=1)
            
            import sms_service
            
            for r in reminders:
                trigger = False
                msg = ""
                if r['type'] == 'date':
                    target_dt = parse_to_tehran_dt(r.get('target_date'))
                    if target_dt and target_dt <= now_tehran:
                        last_notified = parse_to_tehran_dt(r.get('last_notified_at'))
                        if not last_notified or last_notified < one_day_ago:
                            trigger = True
                            target_shamsi = gregorian_to_shamsi_full(target_dt)
                            msg = f"🔔 <b>یادآوری سررسید (به وقت تهران):</b> {r['title']}\n📅 موعد سررسید: <b>{target_shamsi}</b>\nتوضیحات: {r.get('description') or ''}"
                elif r['type'] == 'traffic':
                    c = conn.cursor()
                    c.execute("SELECT SUM(data_used) as total_used FROM subscriptions")
                    row = c.fetchone()
                    total_used = row['total_used'] or 0
                    
                    baseline = r.get('baseline_traffic') or 0
                    manual = r.get('manual_consumed_traffic') or 0
                    current_traffic = max(0, (total_used - baseline) + manual)
                    
                    limit = r.get('target_traffic') or 0
                    threshold = r.get('threshold_percent') or 100
                    
                    if limit > 0 and (current_traffic / limit) * 100 >= threshold:
                        last_notified = parse_to_tehran_dt(r.get('last_notified_at'))
                        if not last_notified or last_notified < one_day_ago:
                            trigger = True
                            msg = f"⚠️ <b>یادآوری ترافیک:</b> {r['title']}\nترافیک مصرفی: {current_traffic:.2f} GB از {limit:.2f} GB (بیش از {threshold}%)\nتوضیحات: {r.get('description') or ''}"
                
                if trigger:
                    keyboard = InlineKeyboardMarkup([
                        [
                            InlineKeyboardButton("✅ انجام شد", callback_data=f"remind_done_{r['id']}"),
                            InlineKeyboardButton("🔄 تکرار (1 روز بعد)", callback_data=f"remind_snooze_{r['id']}")
                        ]
                    ])
                    
                    # انتخاب گیرندگان تلگرام
                    target_ids = []
                    if r.get('send_telegram', 1):
                        tt = r.get('telegram_target', 'main_admin')
                        if tt == 'main_admin':
                            if ADMIN_ID: target_ids.append(ADMIN_ID)
                        elif tt == 'all_admins':
                            c = conn.cursor()
                            c.execute("SELECT telegram_id FROM admin_users")
                            for ar in c.fetchall():
                                if ar['telegram_id']:
                                    target_ids.append(ar['telegram_id'])
                            if ADMIN_ID: target_ids.append(ADMIN_ID)
                        elif tt == 'specific':
                            if r.get('specific_telegram_id'):
                                try:
                                    target_ids.append(int(r.get('specific_telegram_id')))
                                except:
                                    pass
                    
                    target_ids = list(set(target_ids))
                    success_send = False
                    
                    for tid in target_ids:
                        try:
                            await self.bot.send_message(
                                chat_id=tid,
                                text=msg,
                                parse_mode="HTML",
                                reply_markup=keyboard
                            )
                            success_send = True
                        except Exception as ex:
                            logger.error(f"Failed to send admin reminder to {tid}: {ex}")
                            
                    # SMS target
                    if r.get('send_sms') and r.get('sms_number'):
                        try:
                            clean_msg = msg.replace('<b>', '').replace('</b>', '')
                            # send_sms is synchronous
                            sms_success, sms_result = sms_service.send_sms(r.get('sms_number'), clean_msg, db_instance=db)
                            if sms_success:
                                success_send = True
                            else:
                                logger.error(f"Failed to send admin reminder SMS: {sms_result}")
                        except Exception as e:
                            logger.error(f"Error calling SMS service for admin reminder: {e}")

                    if success_send:
                        cursor.execute("UPDATE admin_reminders SET last_notified_at = ? WHERE id = ?", (now_iso, r['id']))
                        conn.commit()
                        
            conn.close()
        except Exception as e:
            logger.error(f"Error in _check_admin_reminders: {e}")

# نمونه singleton
notification_scheduler = NotificationScheduler()
