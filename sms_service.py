#!/usr/bin/env python3
"""
ماژول اختصاصی سرویس پیامک (SMS Service Gateway)
پشتیبانی از پنل‌های پیامکی برتر ایران:
1. IPPanel / FarazSMS / MaxSMS (ارسال با وب‌سرویس و الگو/پترن خدماتی)
2. Kavenegar (کاوه‌نگار - ارسال عادی و وریفای/پترن)
3. MeliPayamak (ملی پیامک)
4. Ghasedak (قاصدک)
5. Generic Webhook (درگاه وب‌هوک دلخواه)
"""

import os
import json
import re
import urllib.request
import urllib.parse
import urllib.error
import logging
from typing import Optional, Tuple, Dict, Any

logger = logging.getLogger(__name__)


def format_iranian_phone(phone: str) -> Optional[str]:
    """فرمت‌بندی و استانداردسازی شماره همراه ایران به فرمت 09xxxxxxxxx"""
    if not phone:
        return None
    cleaned = re.sub(r"[^\d+]", "", str(phone).strip())
    if cleaned.startswith("+98"):
        cleaned = "0" + cleaned[3:]
    elif cleaned.startswith("0098"):
        cleaned = "0" + cleaned[4:]
    elif cleaned.startswith("98"):
        cleaned = "0" + cleaned[2:]
    elif len(cleaned) == 10 and cleaned.startswith("9"):
        cleaned = "0" + cleaned

    if len(cleaned) == 11 and cleaned.startswith("09"):
        return cleaned
    return None


def get_sms_config(db_instance=None) -> Dict[str, Any]:
    """دریافت تنظیمات فعال پنل پیامکی از دیتابیس یا فایل .env"""
    cfg = {
        "enabled": False,
        "provider": "ippanel",
        "api_key": "",
        "originator": "",
        "url": "",
        "pattern_login": "",
        "pattern_failed": "",
        "pattern_logout": "",
    }

    # اولویت اول: خواندن از تنظیمات ذخیره‌شده در دیتابیس
    if db_instance and hasattr(db_instance, "get_setting"):
        try:
            db_enabled = db_instance.get_setting("sms_enabled", None)
            if db_enabled is not None:
                cfg["enabled"] = str(db_enabled).lower() in ("true", "1", "yes")
                cfg["provider"] = str(db_instance.get_setting("sms_provider", "ippanel")).lower()
                cfg["api_key"] = str(db_instance.get_setting("sms_api_key", ""))
                cfg["originator"] = str(db_instance.get_setting("sms_originator", ""))
                cfg["url"] = str(db_instance.get_setting("sms_url", "") or db_instance.get_setting("sms_generic_url", ""))
                cfg["pattern_login"] = str(db_instance.get_setting("sms_pattern_login", ""))
                cfg["pattern_failed"] = str(db_instance.get_setting("sms_pattern_failed", ""))
                cfg["pattern_logout"] = str(db_instance.get_setting("sms_pattern_logout", ""))
                return cfg
        except Exception as e:
            logger.warning(f"Failed to read sms config from db: {e}")

    # اولویت دوم: متغیرهای محیطی (.env)
    env_enabled = os.getenv("SMS_ENABLED", "false").lower() in ("true", "1", "yes")
    cfg["enabled"] = env_enabled
    cfg["provider"] = os.getenv("SMS_PROVIDER", "ippanel").lower()
    cfg["api_key"] = os.getenv("SMS_API_KEY", "")
    cfg["originator"] = os.getenv("SMS_ORIGINATOR", os.getenv("SMS_SENDER", ""))
    cfg["url"] = os.getenv("SMS_URL", os.getenv("SMS_GENERIC_URL", ""))
    cfg["pattern_login"] = os.getenv("SMS_PATTERN_LOGIN", "")
    cfg["pattern_failed"] = os.getenv("SMS_PATTERN_FAILED", "")
    cfg["pattern_logout"] = os.getenv("SMS_PATTERN_LOGOUT", "")

    return cfg


def send_sms(
    receptor: str,
    message: str,
    pattern_code: str = None,
    pattern_data: dict = None,
    db_instance=None
) -> Tuple[bool, str]:
    """
    ارسال پیامک به شماره همراه مشخص شده
    
    Args:
        receptor: شماره همراه مقصد
        message: متن پیامک (برای ارسال ساده)
        pattern_code: کد الگو / پترن خدماتی (در صورت فعال بودن در پنل پیامک)
        pattern_data: دیکشنری مقادیر متغیرهای پترن (مانند {'name': 'علی', 'code': '1234'})
        db_instance: شیء دیتابیس برای خواندن تنظیمات
        
    Returns:
        tuple (موفق بودن عملیات, پیام نتیجه یا خطا)
    """
    formatted_phone = format_iranian_phone(receptor)
    if not formatted_phone:
        return False, f"شماره همراه «{receptor}» نامعتبر است."

    config = get_sms_config(db_instance)
    if not config["enabled"]:
        return False, "ارسال پیامک در تنظیمات سیستم غیرفعال است."

    provider = config["provider"]
    api_key = config.get("api_key", "")
    if not api_key and provider != "generic":
        return False, "کلید API پنل پیامکی (SMS_API_KEY) تنظیم نشده است."

    try:
        # ۱. پنل فراز اس ام اس / IPPanel / MaxSMS
        if provider in ("ippanel", "farazsms", "maxsms"):
            base_url = (config.get("url") or "http://rest.ippanel.com").rstrip("/")
            if pattern_code and pattern_data:
                # ارسال بر اساس پترن (عبور از بلک‌لیست مخابرات)
                url = f"{base_url}/v1/messages/patterns/send"
                payload = {
                    "pattern_code": pattern_code,
                    "originator": config["originator"] or "+983000505",
                    "recipient": formatted_phone,
                    "values": pattern_data
                }
                headers = {
                    "Authorization": f"AccessKey {api_key}",
                    "Content-Type": "application/json"
                }
                req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers)
                with urllib.request.urlopen(req, timeout=10) as resp:
                    res_body = resp.read().decode("utf-8")
                    return True, f"پیامک با پترن با موفقیت ارسال شد: {res_body}"
            else:
                # ارسال پیامک متنی ساده
                url = f"{base_url}/v1/messages"
                payload = {
                    "originator": config["originator"] or "+983000505",
                    "recipients": [formatted_phone],
                    "message": message
                }
                headers = {
                    "Authorization": f"AccessKey {api_key}",
                    "Content-Type": "application/json"
                }
                req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers)
                with urllib.request.urlopen(req, timeout=10) as resp:
                    res_body = resp.read().decode("utf-8")
                    return True, f"پیامک با موفقیت ارسال شد: {res_body}"

        # ۲. پنل کاوه‌نگار (Kavenegar)
        elif provider == "kavenegar":
            base_url = (config.get("url") or "https://api.kavenegar.com").rstrip("/")
            if pattern_code and pattern_data:
                # ارسال اعتبارسنجی / پترن کاوه‌نگار
                params = {
                    "receptor": formatted_phone,
                    "template": pattern_code,
                }
                # کاوه‌نگار از token, token2, token3 استفاده می‌کند
                token_keys = ["token", "token2", "token3", "token10", "token20"]
                for i, (k, v) in enumerate(pattern_data.items()):
                    if i < len(token_keys):
                        params[token_keys[i]] = str(v)
                
                url = f"{base_url}/v1/{api_key}/verify/lookup.json?{urllib.parse.urlencode(params)}"
                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=10) as resp:
                    res_body = resp.read().decode("utf-8")
                    return True, f"پیامک با پترن کاوه‌نگار ارسال شد: {res_body}"
            else:
                # ارسال متنی ساده
                params = {
                    "receptor": formatted_phone,
                    "sender": config["originator"],
                    "message": message
                }
                url = f"{base_url}/v1/{api_key}/sms/send.json"
                data = urllib.parse.urlencode(params).encode("utf-8")
                req = urllib.request.Request(url, data=data)
                with urllib.request.urlopen(req, timeout=10) as resp:
                    res_body = resp.read().decode("utf-8")
                    return True, f"پیامک کاوه‌نگار ارسال شد: {res_body}"

        # ۳. پنل ملی پیامک (MeliPayamak)
        elif provider == "melipayamak":
            base_url = (config.get("url") or "https://rest.melipayamak.com").rstrip("/")
            url = f"{base_url}/api/send/simple/{api_key}"
            payload = {
                "from": config["originator"],
                "to": formatted_phone,
                "text": message
            }
            headers = {"Content-Type": "application/json"}
            req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                res_body = resp.read().decode("utf-8")
                return True, f"پیامک ملی‌پیامک ارسال شد: {res_body}"

        # ۴. پنل قاصدک (Ghasedak)
        elif provider == "ghasedak":
            base_url = (config.get("url") or "https://api.ghasedak.me").rstrip("/")
            url = f"{base_url}/v2/sms/send/simple"
            params = {
                "receptor": formatted_phone,
                "linenumber": config["originator"],
                "message": message
            }
            headers = {
                "apikey": api_key,
                "Content-Type": "application/x-www-form-urlencoded"
            }
            data = urllib.parse.urlencode(params).encode("utf-8")
            req = urllib.request.Request(url, data=data, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                res_body = resp.read().decode("utf-8")
                return True, f"پیامک قاصدک ارسال شد: {res_body}"

        # ۵. وب‌سرویس سامانه SMS.ir (نسخه جدید API v1/v3)
        elif provider in ("smsir", "sms.ir"):
            base_url = (config.get("url") or "https://api.sms.ir").rstrip("/")
            headers = {
                "x-api-key": api_key,
                "Content-Type": "application/json",
                "Accept": "text/plain"
            }
            if pattern_code and pattern_data:
                # ارسال بر اساس پترن / قالب تایید شده (Verify)
                url = f"{base_url}/v1/send/verify"
                parameters = [{"name": str(k), "value": str(v)} for k, v in pattern_data.items()]
                payload = {
                    "mobile": formatted_phone,
                    "templateId": int(pattern_code) if str(pattern_code).isdigit() else pattern_code,
                    "parameters": parameters
                }
            else:
                # ارسال متنی مستقیم / انبوه (Bulk)
                url = f"{base_url}/v1/send/bulk"
                originator = config.get("originator") or ""
                line_num = int(originator) if originator.isdigit() else originator
                payload = {
                    "lineNumber": line_num,
                    "messageText": message,
                    "mobiles": [formatted_phone]
                }

            req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                res_body = resp.read().decode("utf-8")
                try:
                    res_json = json.loads(res_body)
                    if res_json.get("status") == 1:
                        return True, f"پیامک SMS.ir با موفقیت ارسال شد: {res_json.get('message', 'موفق')}"
                    else:
                        return False, f"خطای SMS.ir: {res_json.get('message', res_body)}"
                except Exception:
                    return True, f"پیامک SMS.ir با موفقیت ارسال شد: {res_body}"

        # ۶. درگاه وب‌هوک دلخواه / سفارشی (Generic API Webhook)
        elif provider == "generic":
            raw_url = config.get("url") or os.getenv("SMS_GENERIC_URL", "")
            if not raw_url:
                return False, "آدرس URL وب‌هوک پیامک تنظیم نشده است. لطفاً در فرم تنظیمات، فیلد آدرس URL را تکمیل کنید."
            
            target_url = raw_url.replace("{api_key}", urllib.parse.quote(api_key or ""))\
                                .replace("{phone}", urllib.parse.quote(formatted_phone))\
                                .replace("{message}", urllib.parse.quote(message))\
                                .replace("{sender}", urllib.parse.quote(config.get("originator", "")))\
                                .replace("{originator}", urllib.parse.quote(config.get("originator", "")))
            
            headers = {"User-Agent": "HiddiBot-SMS/1.0"}
            req = urllib.request.Request(target_url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                return True, f"پیامک از درگاه وب‌هوک با موفقیت ارسال شد (کد وضعیت: {resp.status})"

        else:
            return False, f"ارائه‌دهنده پیامک ناشناخته است: {provider}"

    except urllib.error.HTTPError as e:
        err_msg = ""
        try:
            raw_err = e.read().decode("utf-8", errors="ignore") if hasattr(e, "read") else ""
            if raw_err:
                try:
                    err_json = json.loads(raw_err)
                    err_msg = err_json.get("message") or err_json.get("errorMessage") or raw_err
                except Exception:
                    err_msg = raw_err
        except Exception:
            err_msg = str(e)
        if not err_msg:
            err_msg = str(e)
        logger.error(f"HTTP Error sending SMS via {provider}: {e.code} - {err_msg}")
        return False, f"خطای وب‌سرویس پیامک ({e.code}): {err_msg}"
    except Exception as e:
        logger.error(f"Error sending SMS to {formatted_phone}: {e}")
        return False, f"خطا در ارسال پیامک: {str(e)}"


def send_auth_sms_notification(
    phone: str,
    name: str,
    event_type: str,
    ip: str,
    time_str: str,
    device_os: str = None,
    browser: str = None,
    attempted_password: str = None,
    failure_reason: str = None,
    db_instance=None
) -> Tuple[bool, str]:
    """
    ارسال پیامک اطلاع‌رسانی رویدادهای احراز هویت (ورود، خروج، ورود ناموفق) به شماره همراه کاربر
    """
    if not phone:
        return False, "شماره تلفنی برای این حساب ثبت نشده است."

    config = get_sms_config(db_instance)
    if not config["enabled"]:
        return False, "ارسال پیامک غیرفعال است."

    name_clean = name or "کاربر گرامی"

    if event_type == "login":
        pattern = config.get("pattern_login")
        message = (
            f"سلام {name_clean}،\n"
            f"ورود موفق به پنل کاربری شما ثبت شد.\n"
            f"آی‌پی: {ip}\n"
            f"زمان: {time_str}\n"
            f"در صورت عدم اطلاع، سریعاً رمز عبور را تغییر دهید."
        )
        pattern_data = {
            "name": name_clean,
            "ip": ip,
            "time": time_str
        }
        return send_sms(phone, message, pattern_code=pattern if pattern else None, pattern_data=pattern_data, db_instance=db_instance)

    elif event_type == "logout":
        pattern = config.get("pattern_logout")
        message = (
            f"سلام {name_clean}،\n"
            f"خروج از حساب کاربری شما با موفقیت ثبت شد.\n"
            f"زمان: {time_str}"
        )
        pattern_data = {
            "name": name_clean,
            "time": time_str
        }
        return send_sms(phone, message, pattern_code=pattern if pattern else None, pattern_data=pattern_data, db_instance=db_instance)

    elif event_type == "failed":
        pattern = config.get("pattern_failed")
        message = (
            f"هشدار امنیتی!\n"
            f"تلاش ناموفق برای ورود به حساب شما ({name_clean}) ثبت شد.\n"
            f"آی‌پی: {ip}\n"
            f"رمز آزموده شده: {attempted_password or '-'}\n"
            f"زمان: {time_str}"
        )
        pattern_data = {
            "name": name_clean,
            "ip": ip,
            "pass": str(attempted_password or '-'),
            "time": time_str
        }
        return send_sms(phone, message, pattern_code=pattern if pattern else None, pattern_data=pattern_data, db_instance=db_instance)

    return False, "نوع رویداد نامعتبر است."
