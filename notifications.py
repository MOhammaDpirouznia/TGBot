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
        logger.info("Notification scheduler started")
    
    async def stop(self):
        """توقف برنامه‌ریز"""
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        logger.info("Notification scheduler stopped")
    
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
            
            logger.info("Notifications checked successfully")
        except Exception as e:
            logger.error(f"Error checking notifications: {e}")
    
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
⚠️ <b>اشتراک شما در حال منقضی شدن است!</b>

📋 پلن: <b>{plan_name}</b>
📅 تاریخ انقضا: <b>{expire_shamsi}</b>
⏰ زمان باقیمانده: <b>{days_left} روز</b>

💡 برای جلوگیری از قطع اتصال اینترنت، اشتراک خود را تمدید فرمایید.

🔄 برای تمدید، روی دکمه «🔄 تمدید اشتراک» در منوی ربات کلیک کنید.
"""
                    try:
                        await self.bot.send_message(
                            chat_id=telegram_id,
                            text=text,
                            parse_mode="HTML"
                        )
                        db.save_notification(telegram_id, notif_type, sub_id)
                        logger.info(f"Expiration notification ({days_left}d) sent to {telegram_id}")
                    except Exception as e:
                        logger.error(f"Error sending expiration notification: {e}")
            
            # اعلان روز منقضی شدن
            elif days_left == 0:
                sub_id = subscription.get("id")
                notif_type = f"expired_{sub_id}"
                
                if not db.was_notification_sent(telegram_id, notif_type, sub_id):
                    plan_name = subscription.get("plan_name", "نامشخص")
                    
                    text = f"""
🔴 <b>اشتراک شما منقضی شد!</b>

📋 پلن: {plan_name}
📅 تاریخ انقضا: امروز

⚠️ سرویس VPN شما قطع شده است.

🔄 برای فعال‌سازی مجدد، اشتراک جدید خریداری کنید.
"""
                    try:
                        await self.bot.send_message(
                            chat_id=telegram_id,
                            text=text,
                            parse_mode="HTML"
                        )
                        db.save_notification(telegram_id, notif_type, sub_id)
                        # تغییر وضعیت اشتراک به منقضی شده
                        db.update_subscription(sub_id, status="expired")
                        logger.info(f"Expired notification sent to {telegram_id}")
                    except Exception as e:
                        logger.error(f"Error sending expired notification: {e}")
        
        except Exception as e:
            logger.error(f"Error in _check_expiration: {e}")
    
    async def _check_usage(self, telegram_id, subscription):
        """بررسی مصرف حجم"""
        try:
            data_limit = subscription.get("data_limit", 0)
            data_used = subscription.get("data_used", 0)
            
            if data_limit <= 0:
                return  # حجم نامحدود
            
            usage_percent = (data_used / data_limit) * 100
            
            # اعلان ۸۰٪ مصرف
            if usage_percent >= 80:
                sub_id = subscription.get("id")
                notif_type = f"usage_80_{sub_id}"
                
                if not db.was_notification_sent(telegram_id, notif_type, sub_id):
                    plan_name = subscription.get("plan_name", "نامشخص")
                    remaining = data_limit - data_used
                    
                    text = f"""
📊 <b>هشدار مصرف حجم!</b>

📋 پلن: {plan_name}
📊 مصرف: {data_used:.1f} از {data_limit:.1f} گیگابایت
📈 درصد مصرف: {usage_percent:.1f}%
💾 باقیمانده: {remaining:.1f} گیگابایت

⚠️ بیش از ۸۰٪ حجم شما مصرف شده است!

💡 برای استفاده بیشتر، اشتراک خود را تمدید کنید.
"""
                    try:
                        await self.bot.send_message(
                            chat_id=telegram_id,
                            text=text,
                            parse_mode="HTML"
                        )
                        db.save_notification(telegram_id, notif_type, sub_id)
                        logger.info(f"Usage notification sent to {telegram_id}")
                    except Exception as e:
                        logger.error(f"Error sending usage notification: {e}")
            
            # اعلان ۹۵٪ مصرف (هشدار جدی)
            if usage_percent >= 95:
                sub_id = subscription.get("id")
                notif_type = f"usage_95_{sub_id}"
                
                if not db.was_notification_sent(telegram_id, notif_type, sub_id):
                    plan_name = subscription.get("plan_name", "نامشخص")
                    remaining = data_limit - data_used
                    
                    text = f"""
🚨 <b>هشدار جدی: حجم تقریباً تمام شده!</b>

📋 پلن: {plan_name}
📊 مصرف: {data_used:.1f} از {data_limit:.1f} گیگابایت
📈 درصد مصرف: {usage_percent:.1f}%
💾 باقیمانده: {remaining:.1f} گیگابایت

⛔ سرویس شما به زودی قطع خواهد شد!

🔄 همین الان اشتراک خود را تمدید کنید!
"""
                    try:
                        await self.bot.send_message(
                            chat_id=telegram_id,
                            text=text,
                            parse_mode="HTML"
                        )
                        db.save_notification(telegram_id, notif_type, sub_id)
                        logger.info(f"Critical usage notification sent to {telegram_id}")
                    except Exception as e:
                        logger.error(f"Error sending critical usage notification: {e}")
        
        except Exception as e:
            logger.error(f"Error in _check_usage: {e}")
    
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


# نمونه singleton
notification_scheduler = NotificationScheduler()
