#!/usr/bin/env python3
"""
سیستم اعلان‌های خودکار ربات
- اعلان منقضی شدن اشتراک (۳ روز قبل)
- اعلان نزدیک شدن حجم (۸۰٪)
- یادآوری تمدید روزانه
"""

import asyncio
import logging
from datetime import datetime, timedelta
from database import db
from utils import get_now_naive, get_now_iso, gregorian_to_shamsi_full
from sms_service import send_sms
from telegram import InlineKeyboardMarkup, InlineKeyboardButton

logger = logging.getLogger(__name__)


class NotificationScheduler:
    """برنامه‌ریز اعلان‌های خودکار"""
    
    def __init__(self, bot=None, hidify=None):
        self.bot = bot
        self.hidify = hidify
        self.running = False
        self.task = None
    
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
        """حلقه اصلی بررسی اعلان‌ها"""
        while self.running:
            try:
                await self._check_all_notifications()
                # هر ۱ ساعت بررسی کن
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in notification loop: {e}")
                await asyncio.sleep(300)
    
    async def _check_all_notifications(self):
        """بررسی تمام اعلان‌ها با همگام‌سازی مصرف زنده هیدیفای"""
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

            # ۲. دریافت تمام کاربران فعال
            users = db.get_all_users()
            
            for user in users:
                telegram_id = user.get("telegram_id")
                if not telegram_id:
                    continue
                
                # دریافت اشتراک‌های فعال
                subscriptions = db.get_user_subscriptions(telegram_id, status="active")
                
                for sub in subscriptions:
                    await self._check_expiration(telegram_id, sub)
                    await self._check_usage(telegram_id, sub)
                
                # بررسی اشتراک‌های منقضی شده برای یادآوری
                expired_subs = db.get_user_subscriptions(telegram_id, status="expired")
                if expired_subs:
                    await self._send_renewal_reminder(telegram_id)

            # ۳. بررسی اشتراک‌های حضوری و فاقد تلگرام (ارسال پیامک با لینک اختصاصی تمدید)
            try:
                conn = db.get_connection()
                offline_subs = conn.execute("""
                    SELECT * FROM subscriptions 
                    WHERE status='active' AND (telegram_id IS NULL OR telegram_id=0) AND phone_number IS NOT NULL AND phone_number != ''
                """).fetchall()
                conn.close()

                for o_sub in offline_subs:
                    await self._check_offline_subscription(dict(o_sub))
            except Exception as e_off:
                logger.error(f"Error checking offline subscriptions: {e_off}")
            
            # Check Admin Reminders
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

    async def _check_expiration(self, telegram_id, subscription):
        """بررسی منقضی شدن اشتراک بر اساس تاریخ دقیق انقضا"""
        try:
            start_date_str = subscription.get("start_date")
            duration = subscription.get("duration", 30)
            expire_date_str = subscription.get("expire_date")
            
            expire_dt = None
            if expire_date_str:
                try:
                    expire_dt = datetime.fromisoformat(expire_date_str)
                except Exception:
                    try:
                        expire_dt = datetime.strptime(str(expire_date_str)[:10], "%Y-%m-%d")
                    except Exception:
                        pass

            if not expire_dt and start_date_str:
                try:
                    start_dt = datetime.fromisoformat(start_date_str)
                except Exception:
                    try:
                        start_dt = datetime.strptime(str(start_date_str)[:10], "%Y-%m-%d")
                    except Exception:
                        start_dt = get_now_naive()
                expire_dt = start_dt + timedelta(days=duration)

            if not expire_dt:
                return

            now = get_now_naive()
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

📋 نام پلن: <b>{plan_name}</b>
📅 تاریخ انقضا: <b>{expire_shamsi}</b>
⏰ مهلت باقیمانده: <b>{days_left} روز</b>

💡 <i>جهت جلوگیری از قطع اتصال اینترنت، لطفاً پیش از موعد نسبت به تمدید اقدام فرمایید.</i>
"""
                    portal_url = self._build_portal_url(subscription)

                    buttons = [
                        [InlineKeyboardButton("🔄 تمدید سریع در ربات", callback_data=f"renew_{sub_id}")],
                    ]
                    if portal_url:
                        buttons.append([InlineKeyboardButton("🌐 پورتال تمدید آنلاین (بدون فیلتر)", url=portal_url)])
                    else:
                        buttons.append([InlineKeyboardButton("📱 باز کردن پنل هوشمند (Mini App)", callback_data=f"open_sub_{sub_id}")])

                    reply_markup = InlineKeyboardMarkup(buttons)
                    try:
                        await self.bot.send_message(
                            chat_id=telegram_id,
                            text=text,
                            parse_mode="HTML",
                            reply_markup=reply_markup
                        )
                        db.save_notification(telegram_id, notif_type, sub_id)
                        logger.info(f"Expiration notification ({days_left}d) sent to Telegram {telegram_id}")
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
                    
                    text = f"""
🔴 <b>اشتراک شما منقضی شد!</b>

📋 پلن: <b>{plan_name}</b>
📅 تاریخ انقضا: <b>امروز</b>

⚠️ سرویس اتصال شما موقتاً قطع شده است.
🔄 با تمدید یا خرید اشتراک جدید، اتصال شما بلافاصله برقرار خواهد شد.
"""
                    exp_buttons = [
                        [InlineKeyboardButton("🔄 تمدید آنی در ربات", callback_data=f"renew_{sub_id}")],
                    ]
                    if portal_url:
                        exp_buttons.append([InlineKeyboardButton("🌐 تمدید آنلاین از پورتال", url=portal_url)])
                    reply_markup = InlineKeyboardMarkup(exp_buttons)
                    try:
                        await self.bot.send_message(
                            chat_id=telegram_id,
                            text=text,
                            parse_mode="HTML",
                            reply_markup=reply_markup
                        )
                        db.save_notification(telegram_id, notif_type, sub_id)
                        db.update_subscription(sub_id, status="expired")
                        logger.info(f"Expired notification sent to {telegram_id}")
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
    
    async def _check_usage(self, telegram_id, subscription):
        """بررسی مصرف حجم (۸۰٪ و ۹۵٪ اضطراری)"""
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

            # اعلان ۹۵٪ مصرف (هشدار اضطراری)
            if usage_percent >= 95:
                notif_type = f"usage_95_{sub_id}"
                if not db.was_notification_sent(telegram_id, notif_type, sub_id):
                    text = f"""
🚨 <b>هشدار اضطراری: حجم اشتراک رو به اتمام است!</b>

📋 پلن: <b>{plan_name}</b>
📊 مصرف: <b>{data_used:.1f} از {data_limit:.1f} گیگابایت</b> ({usage_percent:.1f}%)
💾 ترافیک باقیمانده: <b>{remaining:.1f} گیگابایت</b>

⛔ <i>تنها ۵٪ از ترافیک اشتراک شما باقی مانده است. جهت تداوم اتصال تمدید فرمایید.</i>
"""
                    u_buttons = [
                        [InlineKeyboardButton("⚡ تمدید فوری در ربات", callback_data=f"renew_{sub_id}")],
                    ]
                    if portal_url:
                        u_buttons.append([InlineKeyboardButton("🌐 تمدید آنلاین از پورتال", url=portal_url)])
                    reply_markup = InlineKeyboardMarkup(u_buttons)
                    try:
                        await self.bot.send_message(
                            chat_id=telegram_id,
                            text=text,
                            parse_mode="HTML",
                            reply_markup=reply_markup
                        )
                        db.save_notification(telegram_id, notif_type, sub_id)
                        logger.info(f"Critical 95% usage notification sent to {telegram_id}")
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

            # اعلان ۸۰٪ مصرف
            elif usage_percent >= 80:
                notif_type = f"usage_80_{sub_id}"
                if not db.was_notification_sent(telegram_id, notif_type, sub_id):
                    text = f"""
📊 <b>هشدار مصرف حجم (۸۰٪ مصرف شده)</b>

📋 پلن: <b>{plan_name}</b>
📊 مصرف: <b>{data_used:.1f} از {data_limit:.1f} گیگابایت</b> ({usage_percent:.1f}%)
💾 حجم باقیمانده: <b>{remaining:.1f} گیگابایت</b>

💡 <i>بیش از ۸۰٪ حجم اشتراک شما مصرف شده است.</i>
"""
                    u_buttons = [
                        [InlineKeyboardButton("🔄 تمدید اشتراک در ربات", callback_data=f"renew_{sub_id}")],
                    ]
                    if portal_url:
                        u_buttons.append([InlineKeyboardButton("🌐 تمدید آنلاین از پورتال", url=portal_url)])
                    reply_markup = InlineKeyboardMarkup(u_buttons)
                    try:
                        await self.bot.send_message(
                            chat_id=telegram_id,
                            text=text,
                            parse_mode="HTML",
                            reply_markup=reply_markup
                        )
                        db.save_notification(telegram_id, notif_type, sub_id)
                        logger.info(f"Usage 80% notification sent to {telegram_id}")
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

    async def _check_offline_subscription(self, subscription):
        """بررسی اشتراک‌های حضوری و فاقد تلگرام و ارسال پیامک تمدید با لینک اختصاصی"""
        try:
            phone = subscription.get("phone_number")
            if not phone:
                return

            sub_id = subscription.get("id")
            plan_name = subscription.get("plan_name", "اشتراک")
            portal_url = self._build_portal_url(subscription)

            # ۱. بررسی تاریخ انقضا (۳ روز مانده)
            expire_date_str = subscription.get("expire_date")
            if expire_date_str:
                try:
                    exp_dt = datetime.fromisoformat(expire_date_str)
                    days_left = max(0, (exp_dt.date() - get_now_naive().date()).days)
                    if 0 < days_left <= 3:
                        notif_type = f"offline_expiring_{sub_id}_{days_left}d"
                        if not db.was_notification_sent(0, notif_type, sub_id):
                            sms_text = f"کاربر گرامی، کمتر از {days_left} روز از مهلت اشتراک شما باقی مانده است. جهت تمدید آنلاین اشتراک به لینک زیر مراجعه فرمایید:\n{portal_url}"
                            send_sms(phone, sms_text, db_instance=db)
                            db.save_notification(0, notif_type, sub_id)
                            logger.info(f"Offline expiration SMS ({days_left}d) sent to {phone}")
                except Exception as e:
                    logger.debug(f"Error parsing offline expire date: {e}")

            # ۲. بررسی مصرف حجم (۸۰٪ مصرف)
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
    
    async def _send_renewal_reminder(self, telegram_id):
        """ارسال یادآوری تمدید"""
        try:
            # بررسی اینکه آیا قبلاً یادآوری ارسال شده
            notif_type = "daily_renewal_reminder"
            if db.was_notification_sent(telegram_id, notif_type):
                return
            
            text = """
💡 <b>یادآوری تمدید اشتراک</b>

اشتراک شما منقضی شده است.
برای استفاده مجدد از سرویس VPN، لطفاً اشتراک جدید خریداری کنید.

🛒 برای خرید، روی دکمه «🛒 خرید اشتراک» کلیک کنید.
"""
            try:
                await self.bot.send_message(
                    chat_id=telegram_id,
                    text=text,
                    parse_mode="HTML"
                )
                db.save_notification(telegram_id, notif_type)
                logger.info(f"Renewal reminder sent to {telegram_id}")
            except Exception as e:
                logger.error(f"Error sending renewal reminder: {e}")
        
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
        """Check admin reminders and send telegram notification if triggered."""
        from bot import ADMIN_ID
        if not self.bot:
            return
            
        try:
            conn = db.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM admin_reminders WHERE is_active = 1 AND is_done = 0")
            reminders = [dict(r) for r in cursor.fetchall()]
            
            now_iso = get_now_iso()
            
            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
            import sms_service
            
            for r in reminders:
                trigger = False
                msg = ""
                if r['type'] == 'date':
                    if r['target_date'] and r['target_date'] <= now_iso:
                        if not r['last_notified_at'] or r['last_notified_at'] < (datetime.utcnow() - timedelta(days=1)).isoformat() + "Z":
                            trigger = True
                            msg = f"🔔 <b>یادآوری سررسید:</b> {r['title']}\nتوضیحات: {r['description']}"
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
                        if not r['last_notified_at'] or r['last_notified_at'] < (datetime.utcnow() - timedelta(days=1)).isoformat() + "Z":
                            trigger = True
                            msg = f"⚠️ <b>یادآوری ترافیک:</b> {r['title']}\nترافیک مصرفی: {current_traffic:.2f} GB از {limit:.2f} GB (بیش از {threshold}%)\nتوضیحات: {r['description']}"
                
                if trigger:
                    keyboard = InlineKeyboardMarkup(inline_keyboard=[
                        [
                            InlineKeyboardButton(text="✅ انجام شد", callback_data=f"remind_done_{r['id']}"),
                            InlineKeyboardButton(text="🔄 تکرار (1 روز بعد)", callback_data=f"remind_snooze_{r['id']}")
                        ]
                    ])
                    
                    # Target selection for Telegram
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
