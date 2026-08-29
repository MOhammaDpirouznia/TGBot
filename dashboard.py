#!/usr/bin/env python3
"""
پنل مدیریت جامع تحت وب و سامانه اختصاصی نمایندگی (Reseller Portal)
"""

import os
import csv
import io
import json
import time
import hashlib
import re
import urllib.request
import urllib.parse
import urllib.error
import functools
import logging
import httpx
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from flask import (
    Flask, render_template, request, redirect, url_for, session,
    jsonify, flash, Response, send_file
)

from dotenv import load_dotenv
load_dotenv()

from database import db
from utils import generate_qr_code_bytes, get_now_iso, get_now_naive, get_single_link_template, format_single_link, TEHRAN_TZ
from admin_manager import get_all_plans, add_plan, update_plan, delete_plan, move_plan_up, move_plan_down
from sms_service import send_auth_sms_notification, send_sms, get_sms_config, format_iranian_phone

logger = logging.getLogger(__name__)

# ─── تنظیمات Flask ───
app = Flask(__name__)
app.secret_key = os.getenv("DASHBOARD_SECRET", "hiddibot-super-secret-key-2026")


# ─── توابع داینامیک خواندن تنظیمات محیطی ───

def get_admin_username() -> str:
    return os.getenv("DASHBOARD_USERNAME", "admin")

def get_admin_password() -> str:
    return os.getenv("DASHBOARD_PASSWORD", "admin123")

def get_bot_token() -> str:
    return os.getenv("BOT_TOKEN", "")

def get_admin_id() -> int:
    return int(os.getenv("ADMIN_ID", 0))

def get_hiddify_url() -> str:
    return os.getenv("HIDIFY_PANEL_URL", "").rstrip("/")

def get_hiddify_key() -> str:
    return os.getenv("HIDIFY_API_KEY", "")

def get_hiddify_proxy() -> str:
    return os.getenv("HIDIFY_PROXY_PATH", "").strip("/")

def get_user_proxy() -> str:
    return os.getenv("USER_PROXY_PATH", "user").strip("/")


@app.template_filter("format_single_link")
def jinja_format_single_link(sub, template=None):
    """تولید لینک تکی استاندارد VMess یا URI برای اشتراک"""
    if not template:
        template = get_single_link_template(db)
    uuid = sub["hidify_uuid"] if isinstance(sub, dict) or hasattr(sub, "__getitem__") else ""
    try:
        name = sub["account_name"] or f"tg_{sub['telegram_id']}"
    except Exception:
        name = "User"
    return format_single_link(template, uuid=uuid, name=name)


# ─── سرویس هوشمند آواتار سه‌بعدی و پروفایل تلگرام (Smart 3D & Telegram Avatar Service) ───

AVATAR_CACHE_DIR = Path("data/avatars")
AVATAR_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def generate_fallback_avatar_svg(identifier: str) -> str:
    """تولید آواتار وکتور گرادیان مدرن محلی در صورت عدم دسترسی به اینترنت"""
    name_clean = str(identifier).lstrip("@").strip()
    # اگر شماره تلفن بود، از آخرین رقم‌ها یا شناسه برای گرادیان استفاده شود
    initial = name_clean[0].upper() if name_clean else "U"
    colors = [
        ("#4f46e5", "#7c3aed"),
        ("#0284c7", "#0ea5e9"),
        ("#059669", "#10b981"),
        ("#d97706", "#f59e0b"),
        ("#e11d48", "#f43f5e"),
        ("#7c2d12", "#c2410c"),
        ("#0891b2", "#06b6d4"),
        ("#9333ea", "#c084fc"),
    ]
    idx = sum(ord(c) for c in name_clean) % len(colors)
    c1, c2 = colors[idx]

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="100" height="100">
        <defs>
            <linearGradient id="grad_{idx}" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" stop-color="{c1}" />
                <stop offset="100%" stop-color="{c2}" />
            </linearGradient>
        </defs>
        <circle cx="50" cy="50" r="50" fill="url(#grad_{idx})" />
        <text x="50%" y="54%" text-anchor="middle" dominant-baseline="middle" fill="#ffffff" font-size="42" font-family="Segoe UI, Vazirmatn, Tahoma, sans-serif" font-weight="bold">{initial}</text>
    </svg>"""


def fetch_smart_avatar_bytes(identifier: str) -> tuple[bytes, str]:
    """
    دریافت هوشمند تصویر پروفایل:
    ۱. بررسی آیا شماره تلفن به کاربری در تلگرام متصل است؟ (استخراج خودکار telegram_id)
    ۲. تلاش برای دریافت عکس واقعی پروفایل تلگرام از Bot API یا t.me
    ۳. در صورت عدم وجود، تولید آواتار سه‌بعدی و کارتونی یونیک بر اساس شماره/شناسه با DiceBear
    ۴. کش محلی خودکار جهت افزایش سرعت لود و کارکرد بدون وقفه
    """
    if not identifier:
        identifier = "Customer"

    raw_ident = str(identifier).strip()
    clean_ident = raw_ident.lstrip("@").strip()

    # ۱. بررسی شماره همراه و جستجوی telegram_id مرتبط در دیتابیس
    matched_tg_id = None
    is_phone = bool(re.match(r"^(\+98|0098|98|0)?9\d{9}$", clean_ident))
    if is_phone:
        try:
            matched_tg_id = db.find_telegram_id_by_phone(clean_ident)
        except Exception:
            pass

    # ۲. تلاش برای دریافت عکس واقعی تلگرام (در صورت داشتن telegram_id)
    target_tg_id = matched_tg_id
    if not target_tg_id and clean_ident.isdigit() and not is_phone:
        target_tg_id = int(clean_ident)

    if target_tg_id and target_tg_id > 0:
        cache_file_tg = AVATAR_CACHE_DIR / f"tg_{target_tg_id}.jpg"
        if cache_file_tg.exists() and (time.time() - cache_file_tg.stat().st_mtime < 86400 * 3):
            return cache_file_tg.read_bytes(), "image/jpeg"

        bot_token = get_bot_token()
        if bot_token:
            try:
                url = f"https://api.telegram.org/bot{bot_token}/getUserProfilePhotos?user_id={target_tg_id}&limit=1"
                with httpx.Client(timeout=3.0) as client:
                    resp = client.get(url)
                    if resp.status_code == 200:
                        data = resp.json()
                        photos = data.get("result", {}).get("photos", [])
                        if photos and len(photos) > 0 and len(photos[0]) > 0:
                            file_id = photos[0][-1].get("file_id") or photos[0][0].get("file_id")
                            file_info_resp = client.get(f"https://api.telegram.org/bot{bot_token}/getFile?file_id={file_id}")
                            if file_info_resp.status_code == 200:
                                file_path = file_info_resp.json().get("result", {}).get("file_path")
                                if file_path:
                                    img_url = f"https://api.telegram.org/file/bot{bot_token}/{file_path}"
                                    img_resp = client.get(img_url)
                                    if img_resp.status_code == 200 and len(img_resp.content) > 100:
                                        cache_file_tg.write_bytes(img_resp.content)
                                        return img_resp.content, "image/jpeg"
            except Exception as e:
                logger.debug(f"Error fetching telegram photo for {target_tg_id}: {e}")

    # ۳. بررسی یوزرنیم تلگرام (اگر با @ شروع شده یا کاراکترهای حروفی داشت)
    if raw_ident.startswith("@") or (not clean_ident.isdigit() and len(clean_ident) > 3 and not is_phone):
        cache_file_u = AVATAR_CACHE_DIR / f"user_{clean_ident}.jpg"
        if cache_file_u.exists() and (time.time() - cache_file_u.stat().st_mtime < 86400 * 3):
            return cache_file_u.read_bytes(), "image/jpeg"
        try:
            with httpx.Client(timeout=2.5, follow_redirects=True) as client:
                resp = client.get(f"https://t.me/i/userpic/320/{clean_ident}.jpg")
                if resp.status_code == 200 and len(resp.content) > 500:
                    cache_file_u.write_bytes(resp.content)
                    return resp.content, "image/jpeg"
        except Exception:
            pass

    # ۴. تولید آواتار سه‌بعدی و یونیک با DiceBear بر اساس شماره همراه یا شناسه کاربر
    safe_seed = urllib.parse.quote(clean_ident)
    hash_key = hashlib.md5(clean_ident.encode("utf-8")).hexdigest()[:12]
    cache_file_3d = AVATAR_CACHE_DIR / f"smart3d_{hash_key}.svg"

    if cache_file_3d.exists() and (time.time() - cache_file_3d.stat().st_mtime < 86400 * 15):
        return cache_file_3d.read_bytes(), "image/svg+xml"

    # استایل مدرن ربات‌ها و کاراکترهای سه‌بعدی DiceBear با پالت‌های رنگی جذاب
    dicebear_url = (
        f"https://api.dicebear.com/9.x/bottts-neutral/svg?seed={safe_seed}"
        f"&backgroundColor=b6e3f4,c0aede,d1d4f9,ffd5dc,ffdfbf,c1f4c5,ffecb3,e1bee7"
    )
    try:
        with httpx.Client(timeout=3.0) as client:
            resp = client.get(dicebear_url, headers={"User-Agent": "Mozilla/5.0 HiddiBot/1.0"})
            if resp.status_code == 200 and len(resp.content) > 100:
                cache_file_3d.write_bytes(resp.content)
                return resp.content, "image/svg+xml"
    except Exception as e:
        logger.debug(f"DiceBear avatar fetch fallback: {e}")

    # ۵. در صورت آفلاین بودن سرور یا عدم پاسخ‌دهی، استفاده از وکتور گرادیان آفلاین
    svg_code = generate_fallback_avatar_svg(clean_ident)
    return svg_code.encode("utf-8"), "image/svg+xml"


@app.route("/avatar/", defaults={"identifier": "User"})
@app.route("/avatar/<identifier>")
def telegram_avatar(identifier="User"):
    """ارائه تصویر آواتار هوشمند با هدر کش ۳ روزه"""
    if not identifier:
        identifier = "User"
    img_bytes, mime_type = fetch_smart_avatar_bytes(str(identifier))
    resp = Response(img_bytes, mimetype=mime_type)
    resp.headers["Cache-Control"] = "public, max-age=259200"
    return resp


@app.template_filter("avatar_url")
@app.template_global("avatar_url")
def avatar_url_helper(identifier=None):
    """هلپر امن برای تولید آدرس آواتار در تمامی قالب‌ها بدون خطای BuildError"""
    if not identifier:
        identifier = "User"
    return url_for("telegram_avatar", identifier=str(identifier))


# ─── هلپرهای ارتباط همگام با تلگرام و هیدیفای (Sync Helpers) ───

def send_telegram_msg(chat_id: int, text: str, reply_markup=None, parse_mode: str = "HTML") -> bool:
    """ارسال پیام تلگرام به صورت همگام از پنل وب"""
    bot_token = get_bot_token()
    if not bot_token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as e:
        logger.error(f"Error sending telegram msg to {chat_id}: {e}")
        return False


def parse_client_info(req) -> dict:
    """استخراج هوشمند آدرس آی‌پی، نام مرورگر، سیستم‌عامل و نوع دستگاه کاربر"""
    # ۱. استخراج آی‌پی (با پشتیبانی از CDN و پروکسی‌های معکوس)
    ip = "127.0.0.1"
    if req.headers.get("CF-Connecting-IP"):
        ip = req.headers.get("CF-Connecting-IP").strip()
    elif req.headers.get("X-Forwarded-For"):
        ip = req.headers.get("X-Forwarded-For").split(",")[0].strip()
    elif req.headers.get("X-Real-IP"):
        ip = req.headers.get("X-Real-IP").strip()
    elif req.remote_addr:
        ip = req.remote_addr.strip()

    ua = req.headers.get("User-Agent", "")

    # ۲. تشخیص سیستم‌عامل و دستگاه
    os_name = "💻 نامشخص"
    ua_lower = ua.lower()

    if "windows nt 10.0" in ua_lower:
        os_name = "💻 ویندوز (Windows 10/11)"
    elif "windows nt 6.3" in ua_lower or "windows nt 6.2" in ua_lower:
        os_name = "💻 ویندوز (Windows 8/8.1)"
    elif "windows nt 6.1" in ua_lower:
        os_name = "💻 ویندوز (Windows 7)"
    elif "windows" in ua_lower:
        os_name = "💻 ویندوز (Windows)"
    elif "android" in ua_lower:
        os_name = "📱 اندروید (Android)"
    elif "iphone" in ua_lower:
        os_name = "📱 آیفون (iOS / iPhone)"
    elif "ipad" in ua_lower:
        os_name = "📱 آیپد (iPadOS)"
    elif "macintosh" in ua_lower or "mac os x" in ua_lower:
        os_name = "💻 مک (macOS)"
    elif "linux" in ua_lower:
        os_name = "💻 لینوکس (Linux)"

    # ۳. تشخیص مرورگر
    browser = "🌐 نامشخص"
    if "edg/" in ua_lower:
        browser = "🌐 Microsoft Edge"
    elif "samsungbrowser/" in ua_lower:
        browser = "🌐 Samsung Internet"
    elif "telegram" in ua_lower:
        browser = "✈️ Telegram In-App"
    elif "chrome/" in ua_lower or "crios/" in ua_lower:
        browser = "🌐 Google Chrome"
    elif "firefox/" in ua_lower or "fxios/" in ua_lower:
        browser = "🦊 Mozilla Firefox"
    elif "safari/" in ua_lower and "chrome" not in ua_lower:
        browser = "🧭 Apple Safari"
    elif "opera" in ua_lower or "opr/" in ua_lower:
        browser = "🔴 Opera"
    elif "postman" in ua_lower or "curl" in ua_lower:
        browser = "⚡ API Tool"

    return {
        "ip": ip,
        "user_agent": ua,
        "browser": browser,
        "device_os": os_name
    }


def send_failed_login_telegram_alert(username: str, password: str, ip: str, browser: str, device_os: str, failure_reason: str):
    """ارسال هشدار آنی تلاش ناموفق ورود به تلگرام مدیر کل"""
    admin_id = get_admin_id()
    if not admin_id:
        return

    now_str = datetime.now(TEHRAN_TZ).strftime("%Y-%m-%d %H:%M:%S")
    # ایمن‌سازی نمایش رمز و متون برای HTML تلگرام
    safe_username = str(username).replace("<", "&lt;").replace(">", "&gt;")
    safe_password = str(password).replace("<", "&lt;").replace(">", "&gt;")
    safe_reason = str(failure_reason).replace("<", "&lt;").replace(">", "&gt;")

    alert_text = (
        f"🚨 <b>هشدار امنیتی: تلاش برای ورود ناموفق به پنل!</b>\n\n"
        f"👤 <b>نام کاربری وارد شده:</b> <code>{safe_username}</code>\n"
        f"🔑 <b>رمز عبور وارد شده:</b> <code>{safe_password}</code>\n"
        f"🌐 <b>آدرس آی‌پی (IP):</b> <code>{ip}</code>\n"
        f"💻 <b>دستگاه و سیستم‌عامل:</b> {device_os}\n"
        f"🌐 <b>مرورگر:</b> {browser}\n"
        f"⚠️ <b>علت خطا:</b> <i>{safe_reason}</i>\n"
        f"⏰ <b>زمان رویداد:</b> <code>{now_str}</code>\n\n"
        f"🛡 <i>این هشدار به صورت هوشمند توسط سامانه امنیت پنل مدیریت ارسال شده است.</i>"
    )

    try:
        send_telegram_msg(admin_id, alert_text)
    except Exception as e:
        logger.error(f"Error sending failed login telegram alert: {e}")


def notify_auth_event(event_type: str, username: str, contact_info: dict, ip: str, device_os: str, browser: str, attempted_password: str = None, failure_reason: str = None):
    """ارسال اطلاع‌رسانی ورود، خروج و ورود ناموفق به تلگرام و پیامک صاحب حساب کاربری"""
    if not contact_info:
        return

    now_str = datetime.now(TEHRAN_TZ).strftime("%Y-%m-%d %H:%M:%S")
    name = contact_info.get("name") or username
    telegram_id = contact_info.get("telegram_id")
    phone = contact_info.get("phone")

    # ۱. ارسال پیام تلگرام به صاحب حساب (در صورت ثبت بودن آیدی تلگرام)
    if telegram_id:
        tg_text = ""
        if event_type == "login":
            tg_text = (
                f"🔔 <b>اطلاعیه امنیتی: ورود به حساب کاربری</b>\n\n"
                f"سلام <b>{name}</b> عزیز،\n"
                f"لحظاتی پیش یک ورود موفق به پنل کاربری شما با مشخصات زیر انجام شد:\n\n"
                f"🌐 <b>آدرس آی‌پی:</b> <code>{ip}</code>\n"
                f"💻 <b>دستگاه و سیستم‌عامل:</b> {device_os}\n"
                f"🌐 <b>مرورگر:</b> {browser}\n"
                f"⏰ <b>زمان ورود:</b> <code>{now_str}</code>\n\n"
                f"⚠️ <i>چنانچه این ورود توسط شما انجام نشده است، بلافاصله نسبت به تغییر رمز عبور حساب خود اقدام نمایید.</i>"
            )
        elif event_type == "logout":
            tg_text = (
                f"🚪 <b>اطلاعیه خروج از حساب کاربری</b>\n\n"
                f"سلام <b>{name}</b> عزیز،\n"
                f"خروج از حساب کاربری شما در پنل با موفقیت ثبت شد:\n\n"
                f"🌐 <b>آدرس آی‌پی:</b> <code>{ip}</code>\n"
                f"⏰ <b>زمان خروج:</b> <code>{now_str}</code>"
            )
        elif event_type == "failed":
            safe_password = str(attempted_password or '-').replace("<", "&lt;").replace(">", "&gt;")
            safe_reason = str(failure_reason or 'نامعتبر').replace("<", "&lt;").replace(">", "&gt;")
            tg_text = (
                f"🚨 <b>هشدار امنیتی: تلاش ناموفق برای ورود به حساب شما!</b>\n\n"
                f"سلام <b>{name}</b> عزیز،\n"
                f"یک تلاش ناموفق برای ورود به حساب شما در سامانه ثبت گردید:\n\n"
                f"🔑 <b>رمز عبور تست شده:</b> <code>{safe_password}</code>\n"
                f"🌐 <b>آدرس آی‌پی:</b> <code>{ip}</code>\n"
                f"💻 <b>دستگاه و سیستم‌عامل:</b> {device_os}\n"
                f"🌐 <b>مرورگر:</b> {browser}\n"
                f"⚠️ <b>علت رد ورود:</b> <i>{safe_reason}</i>\n"
                f"⏰ <b>زمان رویداد:</b> <code>{now_str}</code>\n\n"
                f"🛡 <i>چنانچه این تلاش توسط شخص دیگری انجام شده، جهت حفظ امنیت فوراً رمز عبور خود را تغییر دهید.</i>"
            )

        if tg_text:
            try:
                send_telegram_msg(int(telegram_id), tg_text)
            except Exception as e:
                logger.error(f"Error notifying user {username} on telegram {telegram_id}: {e}")

    # ۲. ارسال پیامک به شماره همراه صاحب حساب (در صورت فعال بودن پنل پیامکی)
    if phone:
        try:
            send_auth_sms_notification(
                phone=phone,
                name=name,
                event_type=event_type,
                ip=ip,
                time_str=now_str,
                device_os=device_os,
                browser=browser,
                attempted_password=attempted_password,
                failure_reason=failure_reason,
                db_instance=db
            )
        except Exception as e:
            logger.error(f"Error sending auth SMS notification to {phone}: {e}")


def send_subscription_card_sync(chat_id: int, sub_url: str, title: str, details: str):
    """ارسال کارت اشتراک همراه با بارکد QR و دکمه‌های اتصال مستقیم از وب به کاربر"""
    bot_token = get_bot_token()
    clean_sub_url = sub_url.strip()
    qr_bytes = generate_qr_code_bytes(clean_sub_url)

    inline_keyboard = {
        "inline_keyboard": [
            [{"text": "🌐 صفحه کاربری و اتصال سریع", "url": clean_sub_url}],
            [{"text": "📋 کپی لینک", "callback_data": "copy_link"}],
        ]
    }

    caption = (
        f"{title}\n\n"
        f"{details}\n\n"
        f"🔗 <b>لینک اتصال شما (برای کپی لمس کنید):</b>\n"
        f"<code>{clean_sub_url}</code>\n\n"
        f"💡 <b>راهنمای اتصال:</b>\n"
        f"1️⃣ کادر لینک بالا را لمس کنید تا کپی شود.\n"
        f"2️⃣ در اپلیکیشن (Hiddify / v2rayNG / Streisand) دکمه افزودن کانفیگ از کلیپ‌بورد را بزنید.\n"
        f"3️⃣ یا از دکمه «🌐 صفحه کاربری و اتصال سریع» استفاده نمایید."
    )

    if qr_bytes and bot_token:
        try:
            boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
            body = bytearray()
            # chat_id
            body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"chat_id\"\r\n\r\n{chat_id}\r\n".encode())
            # caption
            body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"caption\"\r\n\r\n{caption}\r\n".encode())
            # parse_mode
            body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"parse_mode\"\r\n\r\nHTML\r\n".encode())
            # reply_markup
            body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"reply_markup\"\r\n\r\n{json.dumps(inline_keyboard)}\r\n".encode())
            # photo file
            body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"photo\"; filename=\"qr.png\"\r\nContent-Type: image/png\r\n\r\n".encode())
            body.extend(qr_bytes)
            body.extend(f"\r\n--{boundary}--\r\n".encode())

            req = urllib.request.Request(
                f"https://api.telegram.org/bot{bot_token}/sendPhoto",
                data=bytes(body),
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}
            )
            with urllib.request.urlopen(req, timeout=12) as resp:
                if resp.status == 200:
                    return True
        except Exception as e:
            logger.error(f"Error sending photo card via sync web: {e}")

    # Fallback به ارسال متنی
    return send_telegram_msg(chat_id, caption, reply_markup=inline_keyboard)


def hidify_sync_request(method: str, endpoint: str, data: dict = None):
    """درخواست همگام به API پنل هیدیفای با استفاده از httpx"""
    panel_url = get_hiddify_url()
    api_key = get_hiddify_key()
    proxy_path = get_hiddify_proxy()

    if not panel_url or not api_key:
        return {"error": "اطلاعات پنل هیدیفای (HIDIFY_PANEL_URL / HIDIFY_API_KEY) تنظیم نشده است"}

    base_api = f"{panel_url}/{proxy_path}/api/v2"
    url = f"{base_api}{endpoint}"
    headers = {
        "Hiddify-API-Key": api_key,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    try:
        with httpx.Client(verify=False, follow_redirects=True, timeout=15.0) as client:
            m = method.upper()
            if m == "GET":
                resp = client.get(url, headers=headers, params=data)
            elif m == "POST":
                resp = client.post(url, headers=headers, json=data)
            elif m == "PATCH":
                resp = client.patch(url, headers=headers, json=data)
            elif m == "PUT":
                resp = client.put(url, headers=headers, json=data)
            elif m == "DELETE":
                resp = client.delete(url, headers=headers)
            else:
                return {"error": "Invalid HTTP method"}

            logger.info(f"Hidify sync API: {method} {url} -> {resp.status_code}")
            if resp.status_code in (200, 201):
                return resp.json()
            elif resp.status_code == 204:
                return {"success": True}
            else:
                err_text = resp.text[:200]
                logger.error(f"Hidify sync API error {resp.status_code}: {err_text}")
                return {"error": f"HTTP {resp.status_code}: {err_text}"}
    except httpx.TimeoutException:
        logger.error(f"Hidify sync timeout: {url}")
        return {"error": "Timeout: زمان پاسخگویی سرور هیدیفای بیش از حد طول کشید"}
    except httpx.ConnectError as e:
        logger.error(f"Hidify sync connect error: {e}")
        return {"error": f"خطا در برقراری اتصال به سرور: {e}"}
    except Exception as e:
        logger.error(f"Hidify sync request error: {e}")
        return {"error": str(e)}


def hidify_sync_create_user(name: str, usage_limit_gb: float = None, package_days: int = None, comment: str = None) -> dict:
    """ساخت کاربر در هیدیفای با پشتیبانی کامل از نام‌های فارسی، انگلیسی و یونیکد"""
    raw_name = str(name or "").strip()
    if not raw_name:
        raw_name = f"user_{int(time.time())}"

    payload = {
        "name": raw_name,
        "enable": True,
        "is_active": True,
    }
    if usage_limit_gb is not None:
        try:
            val_gb = float(usage_limit_gb)
            if val_gb > 0:
                payload["usage_limit_GB"] = val_gb
        except Exception:
            pass

    if package_days is not None:
        try:
            val_days = int(package_days)
            if val_days > 0:
                payload["package_days"] = val_days
        except Exception:
            pass

    if comment:
        payload["comment"] = str(comment)[:200]

    # ارسال درخواست ساخت به هیدیفای
    res = hidify_sync_request("POST", "/admin/user/", payload)

    # در صورت بروز خطای 400، با حداقل فیلدهای استاندارد مجدداً تلاش می‌کنیم
    if "error" in res and ("400" in str(res.get("error")) or "invalid" in str(res.get("error")).lower()):
        logger.warning(f"Standard create_user failed ({res.get('error')}), trying fallback minimal payload...")
        minimal_payload = {
            "name": raw_name,
            "enable": True
        }
        if "usage_limit_GB" in payload:
            minimal_payload["usage_limit_GB"] = payload["usage_limit_GB"]
        if "package_days" in payload:
            minimal_payload["package_days"] = payload["package_days"]
        if "comment" in payload:
            minimal_payload["comment"] = payload["comment"]
        res = hidify_sync_request("POST", "/admin/user/", minimal_payload)

    return res


def hidify_sync_update_user(uuid: str, **kwargs) -> dict:
    """بروزرسانی کاربر در هیدیفای"""
    res = hidify_sync_request("PATCH", f"/admin/user/{uuid}/", kwargs)
    if "error" in res:
        # Fallback به دریافت کاربر و ارسال کامل PUT
        user_obj = hidify_sync_request("GET", f"/admin/user/{uuid}/")
        if "error" not in user_obj:
            user_obj.update(kwargs)
            res = hidify_sync_request("PUT", f"/admin/user/{uuid}/", user_obj)
    return res


def hidify_sync_renew_user(uuid: str, new_limit_gb: float, new_duration_days: int) -> dict:
    """
    تمدید هوشمند کاربر در هیدیفای با رعایت ۲ حالت:
    حالت اول: اگر زمان یا حجم اشتراک تمام شده باشد -> جایگزینی حجم و روز با مقادیر پلن جدید + ریست حجم مصرفی و ریست زمان شروع
    حالت دوم: اگر زمان یا حجم اشتراک هنوز تمام نشده باشد -> فقط اضافه کردن حجم و روز به مقادیر قبلی
    """
    try:
        user_info = hidify_sync_request("GET", f"/admin/user/{uuid}/")
        if not user_info or "error" in user_info or not isinstance(user_info, dict):
            res = hidify_sync_update_user(
                uuid,
                usage_limit_GB=new_limit_gb,
                package_days=new_duration_days,
                current_usage_GB=0,
                start_date=None,
                enable=True,
                is_active=True
            )
            return {"renewal_type": "reset_and_replaced", "new_limit": new_limit_gb, "new_days": new_duration_days, "res": res}

        current_usage = float(user_info.get("current_usage_GB") or 0)
        curr_limit = float(user_info.get("usage_limit_GB") or 0)
        curr_days = int(user_info.get("package_days") or 0)
        is_active = user_info.get("is_active", True)
        enable = user_info.get("enable", True)

        # بررسی اتمام حجم یا زمان اشتراک
        is_traffic_finished = (curr_limit > 0 and current_usage >= curr_limit)
        is_expired = (not is_active or not enable or is_traffic_finished)

        if is_expired:
            # حالت اول: زمان یا حجم تمام شده -> جایگزینی مقادیر و ریست حجم مصرفی و زمان شروع
            logger.info(f"Sync Renew {uuid}: Expired/Finished -> Resetting usage and replacing plan ({new_limit_gb} GB, {new_duration_days} days)")
            payload = {
                "usage_limit_GB": new_limit_gb,
                "package_days": new_duration_days,
                "current_usage_GB": 0,
                "start_date": None,
                "enable": True,
                "is_active": True
            }
            res = hidify_sync_update_user(uuid, **payload)
            return {"renewal_type": "reset_and_replaced", "new_limit": new_limit_gb, "new_days": new_duration_days, "res": res}
        else:
            # حالت دوم: هنوز حجم یا زمان باقی مانده -> اضافه کردن حجم و روز به مقادیر قبلی
            combined_limit = (curr_limit + new_limit_gb) if curr_limit > 0 and new_limit_gb > 0 else (new_limit_gb if new_limit_gb > 0 else 0)
            combined_days = curr_days + new_duration_days
            logger.info(f"Sync Renew {uuid}: Active -> Appending volume & days ({curr_limit}+{new_limit_gb}={combined_limit} GB, {curr_days}+{new_duration_days}={combined_days} days)")
            payload = {
                "usage_limit_GB": combined_limit,
                "package_days": combined_days,
                "enable": True,
                "is_active": True
            }
            res = hidify_sync_update_user(uuid, **payload)
            return {"renewal_type": "appended", "new_limit": combined_limit, "new_days": combined_days, "res": res}
    except Exception as e:
        logger.error(f"Error in hidify_sync_renew_user for {uuid}: {e}")
        res = hidify_sync_update_user(uuid, usage_limit_GB=new_limit_gb, package_days=new_duration_days, enable=True, is_active=True)
        return {"renewal_type": "fallback", "new_limit": new_limit_gb, "new_days": new_duration_days, "res": res}


def hidify_sync_delete_user(uuid: str) -> dict:
    """حذف کاربر از سرور هیدیفای"""
    if not uuid:
        return {"error": "UUID نامعتبر است."}
    return hidify_sync_request("DELETE", f"/admin/user/{uuid}/")


def hidify_sync_ping() -> dict:
    """تست اتصال و پینگ سرور هیدیفای"""
    panel_url = get_hiddify_url()
    if not panel_url:
        return {"online": False, "latency": 0, "error": "آدرس سرور تنظیم نشده"}
    start_t = time.time()
    try:
        res = hidify_sync_request("GET", "/admin/user/")
        latency = int((time.time() - start_t) * 1000)
        if "error" in res:
            return {"online": False, "latency": latency, "error": res["error"]}
        return {"online": True, "latency": latency, "users_count": len(res) if isinstance(res, list) else 0}
    except Exception as e:
        latency = int((time.time() - start_t) * 1000)
        return {"online": False, "latency": latency, "error": str(e)}


def get_plans_dict():
    """دریافت لیست پلن‌ها به صورت داینامیک"""
    try:
        plans = get_all_plans()
        if plans:
            return plans
    except Exception as e:
        logger.error(f"Error loading plans in get_plans_dict: {e}")
    return {
        "basic": {"name": "پایه", "price": 250000, "data_limit": 30, "duration": 30, "is_active": True},
        "standard": {"name": "استاندارد", "price": 400000, "data_limit": 60, "duration": 30, "is_active": True},
        "premium": {"name": "پریمیوم", "price": 600000, "data_limit": 100, "duration": 30, "is_active": True},
        "gem": {"name": "الماس", "price": 990000, "data_limit": 180, "duration": 30, "is_active": True},
    }


# ─── دکوریتورهای احراز هویت (Auth Decorators) ───

@app.before_request
def update_user_session_activity():
    if session.get("logged_in") and session.get("session_token"):
        try:
            db.update_session_activity(session.get("session_token"))
        except Exception:
            pass


def login_required(f):
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function


def admin_required(f):
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("logged_in") or session.get("role") != "admin":
            flash("دسترسی به این صفحه فقط برای مدیران مجاز است.", "danger")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function


def super_admin_required(f):
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("logged_in") or session.get("role") != "admin":
            flash("دسترسی به این صفحه فقط برای مدیران مجاز است.", "danger")
            return redirect(url_for("login"))
        if session.get("admin_role") != "super_admin":
            flash("دسترسی به این عملیات حساس فقط برای مدیر ارشد (Super Admin) مجاز است.", "danger")
            return redirect(url_for("payments"))
        return f(*args, **kwargs)
    return decorated_function


def reseller_required(f):
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("logged_in") or session.get("role") != "reseller":
            flash("دسترسی به این صفحه فقط برای نمایندگان مجاز است.", "danger")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function


import random

def generate_svg_captcha() -> tuple[str, str]:
    """تولید کپچای تصویری امن SVG با نویز و کاراکترهای چرخانده شده بدون نیاز به کتابخانه جانبی"""
    chars = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
    code = "".join(random.choices(chars, k=5))
    width, height = 150, 48
    
    # خطوط نویز
    lines_svg = []
    palette = ["#4f46e5", "#0ea5e9", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6"]
    for _ in range(5):
        x1, y1 = random.randint(5, width - 5), random.randint(5, height - 5)
        x2, y2 = random.randint(5, width - 5), random.randint(5, height - 5)
        stroke = random.choice(palette)
        lines_svg.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{stroke}" stroke-width="{random.choice([1, 2])}" opacity="0.45" />')
        
    # نقاط نویز
    dots_svg = []
    for _ in range(25):
        cx, cy = random.randint(2, width - 2), random.randint(2, height - 2)
        r = random.uniform(1.0, 2.2)
        color = random.choice(palette)
        dots_svg.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{color}" opacity="0.35" />')
        
    # حروف با زاویه و استایل
    chars_svg = []
    for i, ch in enumerate(code):
        x = 16 + (i * 25) + random.randint(-2, 2)
        y = 33 + random.randint(-3, 3)
        angle = random.randint(-22, 22)
        color = random.choice(["#0f172a", "#1e1b4b", "#0369a1", "#047857", "#b91c1c", "#4338ca"])
        chars_svg.append(
            f'<text x="{x}" y="{y}" font-family="Verdana, Tahoma, sans-serif" font-size="25" font-weight="bold" fill="{color}" transform="rotate({angle}, {x}, {y})">{ch}</text>'
        )
        
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
        <rect width="100%" height="100%" fill="#f1f5f9" rx="8" />
        {''.join(dots_svg)}
        {''.join(lines_svg)}
        {''.join(chars_svg)}
    </svg>"""
    return code, svg


@app.route("/captcha-image")
def captcha_image():
    """ارائه تصویر کپچا برای اعتبارسنجی فرم ورود"""
    code, svg = generate_svg_captcha()
    session["captcha_code"] = code
    resp = Response(svg, mimetype="image/svg+xml")
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


@app.context_processor
def inject_permissions():
    """تزریق دسترسی‌ها به قالب‌های Jinja"""
    def has_permission(perm):
        if not session.get("logged_in") or session.get("role") != "admin":
            return False
        admin_role = session.get("admin_role", "super_admin")
        if admin_role == "super_admin":
            return True
        perms = session.get("permissions", "")
        if perms == "*" or perm in perms.split(","):
            return True
        return False
    return dict(has_permission=has_permission)


# ─── مسیرهای احراز هویت (Authentication) ───

@app.route("/login", methods=["GET", "POST"])
def login():
    """صفحه ورود با پشتیبانی از چند مدیر، نقش‌های دسترسی (RBAC) و نمایندگان فروش به همراه ثبت لاگ نشست و کپچا"""
    if session.get("logged_in"):
        if session.get("role") == "reseller":
            return redirect(url_for("reseller_dashboard"))
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        client_info = parse_client_info(request)
        ip = client_info["ip"]
        ua = client_info["user_agent"]
        browser = client_info["browser"]
        device_os = client_info["device_os"]

        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        captcha_input = request.form.get("captcha", "").strip().upper()

        real_captcha = str(session.get("captcha_code", "")).upper()
        if not real_captcha or captcha_input != real_captcha:
            # ثبت لاگ تلاش ناموفق به دلیل کپچا
            db.record_login_attempt(
                user_type="unknown",
                user_id=None,
                username=username,
                attempted_password=password,
                status="failed",
                failure_reason="کد امنیتی (کپچا) نادرست یا منقضی شده",
                ip_address=ip,
                user_agent=ua,
                browser=browser,
                device_os=device_os
            )
            # اطلاع‌رسانی به صاحب نام کاربری (تلگرام / پیامک) و مدیر کل
            target_user = db.find_user_contact_info(username)
            notify_auth_event("failed", username, target_user, ip, device_os, browser, attempted_password=password, failure_reason="کد امنیتی (کپچا) نادرست یا منقضی شده")
            send_failed_login_telegram_alert(username, password, ip, browser, device_os, "کد امنیتی (کپچا) نادرست یا منقضی شده")
            flash("کد امنیتی (کپچا) وارد شده نادرست یا منقضی شده است!", "danger")
            return render_template("login.html")

        # مصرف کد کپچا
        session.pop("captcha_code", None)

        # ۱. بررسی جدول مدیران سیستم (RBAC)
        admin_user = db.authenticate_admin(username, password)
        if admin_user:
            session_token = str(uuid.uuid4())
            session["logged_in"] = True
            session["role"] = "admin"
            session["admin_id"] = admin_user["id"]
            session["username"] = admin_user["username"]
            session["name"] = admin_user.get("display_name") or "مدیر"
            session["admin_role"] = admin_user.get("role", "super_admin")
            session["permissions"] = admin_user.get("permissions", "*")
            session["telegram_id"] = admin_user.get("telegram_id") or get_admin_id()
            session["phone"] = admin_user.get("phone")
            session["session_token"] = session_token

            # ثبت لاگ نشست موفق مدیر
            db.record_login_attempt(
                user_type="admin",
                user_id=admin_user["id"],
                username=username,
                status="success",
                ip_address=ip,
                user_agent=ua,
                browser=browser,
                device_os=device_os,
                session_token=session_token
            )

            # اطلاع‌رسانی ورود به مدیر (تلگرام و پیامک)
            admin_contact = {
                "user_type": "admin",
                "user_id": admin_user["id"],
                "username": username,
                "name": admin_user.get("display_name") or "مدیر",
                "telegram_id": admin_user.get("telegram_id"),
                "phone": admin_user.get("phone")
            }
            notify_auth_event("login", username, admin_contact, ip, device_os, browser)

            flash(f"خوش آمدید {session['name']}! ورود به پنل مدیریت با موفقیت انجام شد.", "success")
            return redirect(url_for("dashboard"))

        # بررسی حساب پیش‌فرض محیطی (Fallback / Initial Setup)
        if username == get_admin_username() and password == get_admin_password():
            res_admin = db.create_admin_user(username, password, "مدیر ارشد", role="super_admin", permissions="*", telegram_id=get_admin_id())
            admin_id = res_admin.get("admin_id") if res_admin.get("success") else 1
            session_token = str(uuid.uuid4())
            session["logged_in"] = True
            session["role"] = "admin"
            session["admin_id"] = admin_id
            session["username"] = username
            session["name"] = "مدیر ارشد"
            session["admin_role"] = "super_admin"
            session["permissions"] = "*"
            session["telegram_id"] = get_admin_id()
            session["session_token"] = session_token

            # ثبت لاگ نشست موفق مدیر پیش‌فرض
            db.record_login_attempt(
                user_type="admin",
                user_id=admin_id,
                username=username,
                status="success",
                ip_address=ip,
                user_agent=ua,
                browser=browser,
                device_os=device_os,
                session_token=session_token
            )

            # اطلاع‌رسانی ورود به مدیر ارشد
            admin_contact = {
                "user_type": "admin",
                "user_id": admin_id,
                "username": username,
                "name": "مدیر ارشد",
                "telegram_id": get_admin_id(),
                "phone": None
            }
            notify_auth_event("login", username, admin_contact, ip, device_os, browser)

            flash("خوش آمدید! ورود به عنوان مدیر کل انجام شد.", "success")
            return redirect(url_for("dashboard"))

        # ۲. بررسی نماینده فروش (Reseller)
        reseller = db.authenticate_reseller(username, password)
        if reseller:
            session_token = str(uuid.uuid4())
            session["logged_in"] = True
            session["role"] = "reseller"
            session["reseller_id"] = reseller["id"]
            session["username"] = reseller["username"]
            session["name"] = reseller["name"]
            session["balance"] = reseller["balance"]
            session["telegram_id"] = reseller.get("telegram_id")
            session["phone"] = reseller.get("phone")
            session["session_token"] = session_token

            # ثبت لاگ نشست موفق نماینده
            db.record_login_attempt(
                user_type="reseller",
                user_id=reseller["id"],
                username=username,
                status="success",
                ip_address=ip,
                user_agent=ua,
                browser=browser,
                device_os=device_os,
                session_token=session_token
            )

            # اطلاع‌رسانی ورود موفق به نماینده (تلگرام و پیامک)
            reseller_contact = {
                "user_type": "reseller",
                "user_id": reseller["id"],
                "username": username,
                "name": reseller["name"],
                "telegram_id": reseller.get("telegram_id"),
                "phone": reseller.get("phone")
            }
            notify_auth_event("login", username, reseller_contact, ip, device_os, browser)

            flash(f"سلام {reseller['name']}! ورود به پنل نمایندگی با موفقیت انجام شد.", "success")
            return redirect(url_for("reseller_dashboard"))

        # ۳. ورود ناموفق: ثبت لاگ با پسورد وارد شده و ارسال هشدار به صاحب نام کاربری و مدیر کل
        db.record_login_attempt(
            user_type="unknown",
            user_id=None,
            username=username,
            attempted_password=password,
            status="failed",
            failure_reason="نام کاربری یا رمز عبور نامعتبر است",
            ip_address=ip,
            user_agent=ua,
            browser=browser,
            device_os=device_os
        )

        target_user = db.find_user_contact_info(username)
        notify_auth_event("failed", username, target_user, ip, device_os, browser, attempted_password=password, failure_reason="نام کاربری یا رمز عبور نامعتبر است")
        send_failed_login_telegram_alert(username, password, ip, browser, device_os, "نام کاربری یا رمز عبور نامعتبر است")

        flash("نام کاربری یا رمز عبور اشتباه است!", "danger")

    return render_template("login.html")


@app.route("/logout")
def logout():
    username = session.get("username")
    session_token = session.get("session_token")
    if session_token:
        db.record_logout(session_token)

    # اطلاع‌رسانی خروج به صاحب حساب
    if username:
        try:
            client_info = parse_client_info(request)
            contact_info = db.find_user_contact_info(username)
            if contact_info:
                notify_auth_event("logout", username, contact_info, client_info["ip"], client_info["device_os"], client_info["browser"])
        except Exception as e:
            logger.error(f"Error notifying logout event: {e}")

    session.clear()
    flash("با موفقیت از سیستم خارج شدید.", "info")
    return redirect(url_for("login"))


# ═══════════════════════════════════════════════════════════════════════
# مسیرهای داشبورد مدیر کل (Super Admin Routes)
# ═══════════════════════════════════════════════════════════════════════

@app.route("/")
@app.route("/dashboard")
@admin_required
def dashboard():
    """داشبورد اصلی مدیر کل"""
    conn = db.get_connection()

    total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    total_subscriptions = conn.execute("SELECT COUNT(*) FROM subscriptions").fetchone()[0]
    active_subscriptions = conn.execute("SELECT COUNT(*) FROM subscriptions WHERE status='active'").fetchone()[0]
    total_revenue = conn.execute("SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE status IN ('approved', 'completed')").fetchone()[0]
    pending_payments = conn.execute("SELECT COUNT(*) FROM transactions WHERE status='pending'").fetchone()[0]
    open_tickets = conn.execute("SELECT COUNT(*) FROM support_tickets WHERE status='open'").fetchone()[0]
    total_resellers = conn.execute("SELECT COUNT(*) FROM resellers").fetchone()[0]

    recent_transactions = conn.execute("""
        SELECT * FROM transactions ORDER BY created_at DESC LIMIT 8
    """).fetchall()

    daily_revenue = conn.execute("""
        SELECT DATE(created_at) as date, SUM(amount) as total
        FROM transactions 
        WHERE status IN ('approved', 'completed') AND created_at >= DATE('now', '-7 days')
        GROUP BY DATE(created_at)
        ORDER BY date ASC
    """).fetchall()

    conn.close()

    server_health = hidify_sync_ping()
    analytics = db.get_advanced_analytics()

    return render_template(
        "dashboard.html",
        total_users=total_users,
        total_subscriptions=total_subscriptions,
        active_subscriptions=active_subscriptions,
        total_revenue=total_revenue,
        pending_payments=pending_payments,
        open_tickets=open_tickets,
        total_resellers=total_resellers,
        recent_transactions=recent_transactions,
        daily_revenue=daily_revenue,
        server_health=server_health,
        analytics=analytics
    )


@app.route("/users")
@admin_required
def users():
    """مدیریت کاربران تلگرام"""
    conn = db.get_connection()
    search = request.args.get("search", "").strip()

    if search:
        user_list = conn.execute("""
            SELECT u.*, 
                   (SELECT COUNT(*) FROM subscriptions WHERE telegram_id=u.telegram_id) as subs_count
            FROM users u
            WHERE u.username LIKE ? OR u.telegram_id LIKE ? OR u.phone_number LIKE ?
            ORDER BY u.created_at DESC
        """, (f"%{search}%", f"%{search}%", f"%{search}%")).fetchall()
    else:
        user_list = conn.execute("""
            SELECT u.*, 
                   (SELECT COUNT(*) FROM subscriptions WHERE telegram_id=u.telegram_id) as subs_count
            FROM users u
            ORDER BY u.created_at DESC LIMIT 100
        """).fetchall()

    conn.close()
    single_link_template = get_single_link_template(db)
    return render_template(
        "users.html",
        users=user_list,
        search=search,
        panel_url=get_hiddify_url(),
        user_proxy=get_user_proxy(),
        single_link_template=single_link_template
    )


@app.route("/user/<int:telegram_id>")
@admin_required
def user_detail(telegram_id):
    """جزئیات کاربر ۳۶۰ درجه"""
    conn = db.get_connection()
    user_row = conn.execute("SELECT * FROM users WHERE telegram_id=?", (telegram_id,)).fetchone()
    subs_rows = conn.execute("SELECT * FROM subscriptions WHERE telegram_id=? ORDER BY created_at DESC", (telegram_id,)).fetchall()
    tx_rows = conn.execute("SELECT * FROM transactions WHERE user_id=? ORDER BY created_at DESC", (telegram_id,)).fetchall()
    ticket_rows = conn.execute("SELECT * FROM support_tickets WHERE telegram_id=? ORDER BY created_at DESC", (telegram_id,)).fetchall()
    conn.close()

    user = dict(user_row) if user_row else None
    subscriptions = [dict(r) for r in subs_rows]
    transactions = [dict(r) for r in tx_rows]
    tickets = [dict(r) for r in ticket_rows]

    single_link_template = get_single_link_template(db)
    return render_template(
        "user_detail.html",
        telegram_id=telegram_id,
        user=user,
        subscriptions=subscriptions,
        transactions=transactions,
        tickets=tickets,
        panel_url=get_hiddify_url(),
        user_proxy=get_user_proxy(),
        single_link_template=single_link_template
    )


@app.route("/payments")
@admin_required
def payments():
    """کارتابل مدیریت و تایید فیش‌های پرداخت"""
    conn = db.get_connection()
    status_filter = request.args.get("status", "all")
    search = request.args.get("search", "").strip()

    query = "SELECT * FROM transactions WHERE 1=1"
    params = []

    if status_filter == "deleted":
        query += " AND is_deleted=1"
    else:
        query += " AND (is_deleted=0 OR is_deleted IS NULL)"
        if status_filter != "all":
            query += " AND status=?"
            params.append(status_filter)

    if search:
        query += " AND (tracking_code LIKE ? OR username LIKE ? OR user_id LIKE ? OR order_id LIKE ? OR account_name LIKE ?)"
        params.extend([f"%{search}%", f"%{search}%", f"%{search}%", f"%{search}%", f"%{search}%"])

    query += " ORDER BY created_at DESC LIMIT 200"
    raw_payment_list = conn.execute(query, params).fetchall()

    # شمارنده‌های آماری برای تب‌ها
    pending_count = conn.execute("SELECT COUNT(*) FROM transactions WHERE (is_deleted=0 OR is_deleted IS NULL) AND status='pending'").fetchone()[0]
    approved_count = conn.execute("SELECT COUNT(*) FROM transactions WHERE (is_deleted=0 OR is_deleted IS NULL) AND status IN ('approved', 'completed')").fetchone()[0]
    rejected_count = conn.execute("SELECT COUNT(*) FROM transactions WHERE (is_deleted=0 OR is_deleted IS NULL) AND status='rejected'").fetchone()[0]
    revoked_count = conn.execute("SELECT COUNT(*) FROM transactions WHERE (is_deleted=0 OR is_deleted IS NULL) AND status='revoked'").fetchone()[0]
    deleted_count = conn.execute("SELECT COUNT(*) FROM transactions WHERE is_deleted=1").fetchone()[0]

    # اضافه کردن لاگ‌های حسابرسی برای هر تراکنش
    payment_list = []
    for p in raw_payment_list:
        p_dict = dict(p)
        p_dict["audit_logs"] = db.get_transaction_audit_logs(p["id"])
        payment_list.append(p_dict)

    conn.close()

    cards = db.get_active_bank_cards()
    return render_template(
        "payments.html",
        payments=payment_list,
        status_filter=status_filter,
        search=search,
        cards=cards,
        counts={
            "pending": pending_count,
            "approved": approved_count,
            "rejected": rejected_count,
            "revoked": revoked_count,
            "deleted": deleted_count,
            "total": pending_count + approved_count + rejected_count + revoked_count
        }
    )


@app.route("/payment/approve/<int:payment_id>")
@admin_required
def approve_payment(payment_id):
    """تایید پرداخت در وب و صدور خودکار اکانت در هیدیفای + ارسال به تلگرام"""
    conn = db.get_connection()
    tx = conn.execute("SELECT * FROM transactions WHERE id=?", (payment_id,)).fetchone()
    conn.close()

    if not tx:
        flash("تراکنش یافت نشد.", "danger")
        return redirect(url_for("payments"))

    if tx["status"] == "approved":
        flash("این تراکنش قبلاً تایید شده است.", "warning")
        return redirect(url_for("payments"))

    user_id = tx["user_id"]
    is_renewal = bool(tx["is_renewal"])
    renew_sub_id = tx["renew_sub_id"]
    plan_name = tx["plan_name"]

    # یافتن مشخصات پلن
    plans = get_plans_dict()
    selected_plan = next((p for p in plans.values() if p["name"] == plan_name), None)
    data_limit = selected_plan["data_limit"] if selected_plan else 30
    duration = selected_plan["duration"] if selected_plan else 30

    account_name = tx["account_name"] or f"tg_{user_id}"
    user_uuid = ""

    if is_renewal and renew_sub_id:
        user_subs = db.get_user_subscriptions(user_id)
        target_sub = next((s for s in user_subs if s["id"] == renew_sub_id), None)
        if target_sub:
            user_uuid = target_sub.get("hidify_uuid", "")
            old_limit = float(target_sub.get("data_limit") or 0)
            old_used = float(target_sub.get("data_used") or 0)
            old_plan_name = target_sub.get("plan_name") or ""

            # تمدید هوشمند هیدیفای با رعایت ۲ حالت منقضی یا فعال
            renew_res = hidify_sync_renew_user(user_uuid, float(data_limit), int(duration))
            final_limit = renew_res.get("new_limit", data_limit)
            final_days = renew_res.get("new_days", duration)
            renewal_type = renew_res.get("renewal_type", "fallback")

            # تعیین نام پلن: اگر منقضی بود نام پلن جدید، اگر فعال بود نام پلنی که بیشترین حجم را دارد
            if renewal_type == "reset_and_replaced":
                final_plan_name = plan_name
                final_used = 0
            else:
                final_plan_name = old_plan_name if old_limit > float(data_limit) else plan_name
                final_used = old_used

            # ثبت مصرف دوره گذشته در تاریخچه
            db.save_subscription_history(
                subscription_id=renew_sub_id,
                telegram_id=user_id,
                hidify_uuid=user_uuid,
                account_name=target_sub.get("account_name") or account_name,
                plan_name=old_plan_name or plan_name,
                previous_usage_gb=old_used,
                previous_limit_gb=old_limit,
                period_days=target_sub.get("duration") or duration,
                renewal_type=renewal_type,
                reseller_id=target_sub.get("reseller_id")
            )

            db.update_subscription(
                renew_sub_id,
                plan_name=final_plan_name,
                data_limit=final_limit,
                duration=final_days,
                data_used=final_used,
                status="active"
            )
    else:
        # خرید جدید
        res = hidify_sync_create_user(name=account_name, usage_limit_gb=data_limit, package_days=duration, comment=str(user_id))
        user_uuid = res.get("uuid", "")
        if user_uuid:
            db.save_subscription(
                telegram_id=user_id,
                hidify_uuid=user_uuid,
                plan_id="custom",
                plan_name=plan_name,
                data_limit=data_limit,
                duration=duration,
                status="active",
                account_name=account_name
            )

    # بروزرسانی وضعیت تراکنش در دیتابیس
    conn = db.get_connection()
    conn.execute("UPDATE transactions SET status='approved', updated_at=? WHERE id=?", (get_now_iso(), payment_id))
    conn.commit()
    conn.close()

    # پاداش رفرال
    db.complete_referral(user_id)

    # ارسال کارت و بارکد به تلگرام مشتری
    h_url = get_hiddify_url()
    u_proxy = get_user_proxy()
    if user_uuid and h_url:
        sub_url = f"{h_url}/{u_proxy}/{user_uuid}/"
        card_title = "🎉 **اشتراک شما تایید و فعال شد!**" if not is_renewal else "🔄 **اشتراک شما با موفقیت تمدید شد!**"
        card_details = f"📋 پلن: **{plan_name}**\n📊 حجم: **{data_limit} گیگابایت**\n⏰ مدت: **{duration} روز**"
        send_subscription_card_sync(user_id, sub_url, card_title, card_details)

    flash(f"پرداخت #{payment_id} تایید شد و اشتراک در هیدیفای فعال گردید!", "success")
    return redirect(url_for("payments"))


@app.route("/payment/reject/<int:payment_id>", methods=["GET", "POST"])
@admin_required
def reject_payment(payment_id):
    """رد فیش پرداخت با ثبت دلیل و ارسال پیام به کاربر"""
    reason = request.form.get("reason") or request.args.get("reason") or "عدم تطابق فیش واریزی یا نامعتبر بودن رسید"
    conn = db.get_connection()
    tx = conn.execute("SELECT * FROM transactions WHERE id=?", (payment_id,)).fetchone()

    if tx:
        conn.execute("UPDATE transactions SET status='rejected', rejection_reason=?, updated_at=? WHERE id=?", (reason, get_now_iso(), payment_id))
        conn.commit()

        # ارسال پیام رد به تلگرام
        user_id = tx["user_id"]
        msg = f"❌ <b>پرداخت شما تایید نشد.</b>\n\n📝 <b>علت رد:</b> {reason}\n\nدر صورت وجود سوال، با بخش «💬 پشتیبانی» تماس بگیرید."
        send_telegram_msg(user_id, msg)

    conn.close()
    flash(f"پرداخت #{payment_id} رد شد و به کاربر اطلاع داده شد.", "warning")
    return redirect(url_for("payments"))


@app.route("/payment/<int:payment_id>/revoke", methods=["POST"])
@super_admin_required
def revoke_payment(payment_id):
    """ابطال تراکنش تاییدشده توسط مدیر ارشد به همراه مدیریت وضعیت اشتراک هیدیفای"""
    reason = request.form.get("reason", "").strip() or "ابطال توسط مدیر ارشد"
    rollback_sub_action = request.form.get("rollback_sub_action", "keep")  # keep, disable, delete
    admin_name = session.get("name") or session.get("username") or "مدیر ارشد"
    admin_id = session.get("admin_id")

    res = db.revoke_transaction(
        tx_id=payment_id,
        admin_name=admin_name,
        admin_id=admin_id,
        reason=reason,
        rollback_sub_action=rollback_sub_action
    )

    if not res.get("success"):
        flash(f"خطا در ابطال تراکنش: {res.get('error')}", "danger")
        return redirect(url_for("payments"))

    sub = res.get("sub")
    if sub and sub.get("hidify_uuid"):
        uuid = sub["hidify_uuid"]
        sub_id = sub["id"]
        if rollback_sub_action == "disable":
            # غیرفعال‌سازی در هیدیفای و دیتابیس
            hidify_sync_update_user(uuid, enable=False)
            db.update_subscription(sub_id, status="disabled")
            flash(f"تراکنش #{payment_id} با موفقیت باطل شد و اکانت هیدیفای «{sub.get('account_name')}» غیرفعال گردید.", "warning")
        elif rollback_sub_action == "delete":
            # حذف کامل از هیدیفای و دیتابیس
            hidify_sync_delete_user(uuid)
            db.delete_subscription(sub_id)
            flash(f"تراکنش #{payment_id} با موفقیت باطل شد و اکانت هیدیفای «{sub.get('account_name')}» به طور کامل حذف گردید.", "warning")
        else:
            flash(f"تراکنش #{payment_id} با موفقیت باطل شد (اشتراک بدون تغییر باقی ماند).", "success")
    else:
        flash(f"تراکنش #{payment_id} با موفقیت باطل شد.", "success")

    return redirect(url_for("payments"))


@app.route("/payment/<int:payment_id>/edit", methods=["POST"])
@super_admin_required
def edit_payment(payment_id):
    """ویرایش مشخصات فیش واریزی توسط مدیر ارشد با ثبت لاگ حسابرسی"""
    amount = request.form.get("amount", "").strip()
    tracking_code = request.form.get("tracking_code", "").strip()
    card_number = request.form.get("card_number", "").strip()
    notes = request.form.get("notes", "").strip()
    reason = request.form.get("reason", "").strip() or "ویرایش توسط مدیر ارشد"

    admin_name = session.get("name") or session.get("username") or "مدیر ارشد"
    admin_id = session.get("admin_id")

    res = db.update_transaction_details(
        tx_id=payment_id,
        admin_id=admin_id,
        admin_name=admin_name,
        amount=int(amount) if amount.isdigit() else None,
        tracking_code=tracking_code,
        card_number=card_number,
        notes=notes,
        reason=reason
    )

    if res.get("success"):
        flash(f"اطلاعات فیش #{payment_id} با موفقیت ویرایش و لاگ حسابرسی ثبت شد.", "success")
    else:
        flash(f"خطا در ویرایش فیش: {res.get('error')}", "danger")

    return redirect(url_for("payments"))


@app.route("/payment/<int:payment_id>/delete", methods=["POST"])
@super_admin_required
def delete_payment(payment_id):
    """حذف نرم (آرشیو) فیش با ثبت لاگ"""
    reason = request.form.get("reason", "").strip() or "حذف نرم توسط مدیر ارشد"
    admin_name = session.get("name") or session.get("username") or "مدیر ارشد"
    admin_id = session.get("admin_id")

    res = db.soft_delete_transaction(payment_id, admin_id, admin_name, reason)
    if res.get("success"):
        flash(f"فیش #{payment_id} با موفقیت به سطل زباله / آرشیو منتقل شد.", "info")
    else:
        flash(f"خطا در حذف فیش: {res.get('error')}", "danger")

    return redirect(url_for("payments"))


@app.route("/payment/<int:payment_id>/audit-logs")
@admin_required
def get_payment_audit_logs(payment_id):
    """دریافت لیست لاگ‌های حسابرسی یک فیش به صورت JSON"""
    logs = db.get_transaction_audit_logs(payment_id)
    return jsonify({"success": True, "logs": logs})


RECEIPTS_DIR = Path("data/receipts")
RECEIPTS_DIR.mkdir(parents=True, exist_ok=True)


def prune_receipt_cache(max_files: int = 50):
    """مدیریت فضای ذخیره‌سازی: نگهداری فقط ۵۰ تصویر آخر رسیدها و حذف فایل‌های قدیمی‌تر"""
    try:
        files = [f for f in RECEIPTS_DIR.glob("receipt_*.*") if f.is_file()]
        if len(files) > max_files:
            # مرتب‌سازی بر اساس تاریخ ویرایش/ساخت نزولی (جدیدترین اول)
            files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
            # حذف فایل‌های قدیمی‌تر از ۵۰ مورد
            for old_file in files[max_files:]:
                try:
                    old_file.unlink()
                except Exception:
                    pass
    except Exception as e:
        logger.warning(f"Error pruning receipt cache: {e}")


@app.route("/admin/payment-receipt/<int:payment_id>")
@admin_required
def admin_payment_receipt(payment_id):
    """دانلود و نمایش مستقیم تصویر رسید پرداخت کارت‌به‌کارت با کش محلی پرسرعت (حداکثر ۵۰ فایل آخر)"""
    # ۱. بررسی کش محلی
    for ext, mtype in [(".jpg", "image/jpeg"), (".png", "image/png"), (".pdf", "application/pdf")]:
        cached_file = RECEIPTS_DIR / f"receipt_{payment_id}{ext}"
        if cached_file.exists():
            try:
                with open(cached_file, "rb") as f:
                    content = f.read()
                resp = Response(content, mimetype=mtype)
                resp.headers["Cache-Control"] = "public, max-age=86400"
                return resp
            except Exception:
                pass

    conn = db.get_connection()
    tx = conn.execute("SELECT * FROM transactions WHERE id=?", (payment_id,)).fetchone()
    conn.close()

    if not tx:
        return Response("تراکنش یافت نشد", status=404)

    file_id = None
    if "receipt_image" in tx.keys() and tx["receipt_image"]:
        file_id = tx["receipt_image"]
    elif "receipt_photo_id" in tx.keys() and tx["receipt_photo_id"]:
        file_id = tx["receipt_photo_id"]

    if not file_id:
        return Response("تصویر رسیدی برای این پرداخت ثبت نشده است", status=404)

    bot_token = get_bot_token()
    if not bot_token:
        return Response("توکن ربات تلگرام تنظیم نشده است", status=500)

    try:
        get_file_url = f"https://api.telegram.org/bot{bot_token}/getFile?file_id={file_id}"
        with httpx.Client(timeout=12.0) as client:
            resp = client.get(get_file_url)
            if resp.status_code != 200:
                return Response("خطا در دریافت مسیر فایل از تلگرام", status=502)

            file_info = resp.json()
            file_path = file_info.get("result", {}).get("file_path")
            if not file_path:
                return Response("مسیر فایل یافت نشد", status=404)

            download_url = f"https://api.telegram.org/file/bot{bot_token}/{file_path}"
            dl_resp = client.get(download_url)
            if dl_resp.status_code != 200:
                return Response("خطا در دانلود تصویر رسید از تلگرام", status=502)

            content_type = "image/jpeg"
            ext = ".jpg"
            if file_path.lower().endswith(".png"):
                content_type = "image/png"
                ext = ".png"
            elif file_path.lower().endswith(".pdf"):
                content_type = "application/pdf"
                ext = ".pdf"

            # ذخیره در کش محلی دیسک برای لود فوری دفعات بعد
            try:
                with open(RECEIPTS_DIR / f"receipt_{payment_id}{ext}", "wb") as f:
                    f.write(dl_resp.content)
                # پاکسازی هوشمند و نگهداری حداکثر ۵۰ تصویر آخر
                prune_receipt_cache(50)
            except Exception:
                pass

            response = Response(dl_resp.content, mimetype=content_type)
            response.headers["Cache-Control"] = "public, max-age=86400"
            return response
    except Exception as e:
        logger.error(f"Error serving payment receipt {payment_id}: {e}")
        return Response(f"خطا در دریافت تصویر رسید: {str(e)}", status=500)


@app.route("/api/admin/notifications-check")
@admin_required
def api_admin_notifications_check():
    """بررسی لحظه‌ای اعلان‌های جدید (پرداخت‌های معلق و تیکت‌های باز) برای پخش صدا و هشدار وب"""
    conn = db.get_connection()
    pending_payments = conn.execute("""
        SELECT id, user_id, username, amount, plan_name, tracking_code, created_at 
        FROM transactions 
        WHERE status='pending' 
        ORDER BY created_at DESC LIMIT 10
    """).fetchall()

    open_tickets = conn.execute("""
        SELECT id, telegram_id, subject, message, created_at 
        FROM support_tickets 
        WHERE status='open' 
        ORDER BY created_at DESC LIMIT 10
    """).fetchall()
    conn.close()

    pending_list = [dict(p) for p in pending_payments]
    ticket_list = [dict(t) for t in open_tickets]

    return jsonify({
        "pending_payments_count": len(pending_list),
        "open_tickets_count": len(ticket_list),
        "total_alerts": len(pending_list) + len(ticket_list),
        "pending_payments": pending_list,
        "open_tickets": ticket_list
    })


@app.route("/subscriptions")
@admin_required
def subscriptions():
    """لیست اشتراک‌های هیدیفای"""
    conn = db.get_connection()
    status_filter = request.args.get("status", "all")
    if status_filter == "all":
        sub_list = conn.execute("SELECT * FROM subscriptions ORDER BY created_at DESC LIMIT 150").fetchall()
    else:
        sub_list = conn.execute("SELECT * FROM subscriptions WHERE status=? ORDER BY created_at DESC LIMIT 150", (status_filter,)).fetchall()
    conn.close()
    single_link_template = get_single_link_template(db)
    return render_template("subscriptions.html", subscriptions=sub_list, status_filter=status_filter, panel_url=get_hiddify_url(), user_proxy=get_user_proxy(), single_link_template=single_link_template)


# ═══════════════════════════════════════════════════════════════════════
# بخش مدیریت نمایندگان فروش (Resellers Management - Admin)
# ═══════════════════════════════════════════════════════════════════════

@app.route("/admin/resellers", methods=["GET", "POST"])
@admin_required
def admin_resellers():
    """صفحه مدیریت همکاران و نمایندگان فروش"""
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        name = request.form.get("name")
        telegram_id = int(request.form.get("telegram_id")) if request.form.get("telegram_id") else None
        discount_percent = int(request.form.get("discount_percent", 20))
        initial_balance = int(request.form.get("initial_balance", 0))

        res = db.create_reseller(username, password, name, telegram_id, discount_percent, initial_balance)
        if res.get("success"):
            flash(f"نماینده جدید «{name}» با موفقیت افزوده شد!", "success")
        else:
            flash(f"خطا در ایجاد نماینده: {res.get('error')}", "danger")
        return redirect(url_for("admin_resellers"))

    raw_reseller_list = db.get_all_resellers()
    reseller_list = []
    for r in raw_reseller_list:
        r_dict = dict(r)
        r_dict["is_online"] = db.is_reseller_online(r["id"])
        r_dict["security_logs"] = db.get_reseller_security_logs(r["id"], r["username"])
        reseller_list.append(r_dict)

    all_failed_logins = db.get_all_failed_login_logs(limit=50)
    return render_template("resellers.html", resellers=reseller_list, all_failed_logins=all_failed_logins)


@app.route("/admin/reseller/<int:reseller_id>/add-balance", methods=["POST"])
@admin_required
def admin_reseller_add_balance(reseller_id):
    """افزایش اعتبار نماینده توسط ادمین"""
    amount = int(request.form.get("amount", 0))
    desc = request.form.get("description", "شارژ کیف پول توسط ادمین")
    if amount > 0:
        db.add_reseller_balance(reseller_id, amount, desc)
        flash(f"مبلغ {amount:,} تومان به کیف پول نماینده افزوده شد.", "success")
    return redirect(url_for("admin_resellers"))


@app.route("/admin/reseller/<int:reseller_id>/edit", methods=["POST"])
@admin_required
def admin_reseller_edit(reseller_id):
    """ویرایش اطلاعات و مشخصات نماینده فروش"""
    r = db.get_reseller(reseller_id)
    if not r:
        flash("نماینده یافت نشد.", "danger")
        return redirect(url_for("admin_resellers"))

    name = request.form.get("name", "").strip()
    username = request.form.get("username", "").strip().lower()
    telegram_id = int(request.form.get("telegram_id")) if request.form.get("telegram_id") else None
    discount_percent = int(request.form.get("discount_percent", 20))
    status = request.form.get("status", "active")
    new_password = request.form.get("new_password", "").strip()

    updates = {
        "name": name or r["name"],
        "username": username or r["username"],
        "telegram_id": telegram_id,
        "discount_percent": discount_percent,
        "status": status,
    }
    if new_password:
        updates["password"] = new_password

    res = db.update_reseller(reseller_id, **updates)
    if res.get("success"):
        flash(f"اطلاعات نماینده «{updates['name']}» با موفقیت ویرایش شد.", "success")
    else:
        flash(f"خطا در ویرایش نماینده: {res.get('error')}", "danger")
    return redirect(url_for("admin_resellers"))


@app.route("/admin/reseller/<int:reseller_id>/toggle")
@admin_required
def admin_reseller_toggle(reseller_id):
    """تغییر وضعیت فعال / غیرفعال نماینده"""
    r = db.get_reseller(reseller_id)
    if not r:
        flash("نماینده یافت نشد.", "danger")
        return redirect(url_for("admin_resellers"))

    res = db.toggle_reseller_status(reseller_id)
    new_st = res.get("status", "inactive")
    status_label = "فعال" if new_st == "active" else "غیرفعال"
    flash(f"وضعیت نماینده «{r['name']}» به «{status_label}» تغییر یافت.", "info")
    return redirect(url_for("admin_resellers"))


@app.route("/admin/reseller/<int:reseller_id>/delete")
@admin_required
def admin_reseller_delete(reseller_id):
    """حذف کامل نماینده فروش"""
    r = db.get_reseller(reseller_id)
    if not r:
        flash("نماینده یافت نشد.", "danger")
        return redirect(url_for("admin_resellers"))

    db.delete_reseller(reseller_id)
    flash(f"نماینده «{r['name']}» با موفقیت حذف شد.", "success")
    return redirect(url_for("admin_resellers"))


# ═══════════════════════════════════════════════════════════════════════
# بخش حسابداری پیشرفته و مدیریت سود و زیان (Accounting & Profit Desk)
# ═══════════════════════════════════════════════════════════════════════

@app.route("/accounting", methods=["GET"])
@admin_required
def accounting():
    """داشبورد حسابداری و مدیریت مالی، هزینه‌ها، سود خالص و اسناد مالی"""
    type_filter = request.args.get("type", "all")
    category_filter = request.args.get("category", "all")
    period = request.args.get("period", "all")
    search = request.args.get("search", "")

    summary = db.get_accounting_summary()
    records = db.get_accounting_records(
        limit=250,
        type_filter=type_filter,
        category_filter=category_filter,
        period=period,
        search=search
    )

    categories = [
        "هزینه سرور",
        "هزینه ترافیک هیدیفای",
        "دامنه و CDN",
        "تبلیغات و بازاریابی",
        "دستمزد و پشتیبانی",
        "فروش اشتراک",
        "شارژ نماینده",
        "متفرقه"
    ]

    return render_template(
        "accounting.html",
        summary=summary,
        records=records,
        categories=categories,
        current_type=type_filter,
        current_category=category_filter,
        current_period=period,
        search=search
    )


@app.route("/accounting/record/add", methods=["POST"])
@admin_required
def accounting_add_record():
    """ثبت سند جدید درآمد یا مخارج در سیستم حسابداری"""
    rec_type = request.form.get("type", "expense").strip()
    category = request.form.get("category", "متفرقه").strip()
    title = request.form.get("title", "").strip()
    amount = int(request.form.get("amount", 0))
    date = request.form.get("date", "").strip()
    description = request.form.get("description", "").strip()

    if not title or amount <= 0:
        flash("لطفاً عنوان سند و مبلغ معتبر وارد کنید.", "warning")
        return redirect(url_for("accounting"))

    res = db.add_accounting_record(
        type=rec_type,
        category=category,
        title=title,
        amount=amount,
        source="manual",
        description=description,
        date=date
    )

    if res.get("success"):
        label = "درآمد" if rec_type == "income" else "هزینه/مخارج"
        flash(f"سند {label} «{title}» با مبلغ {amount:,} تومان با موفقیت ثبت شد.", "success")
    else:
        flash(f"خطا در ثبت سند: {res.get('error')}", "danger")

    return redirect(url_for("accounting"))


@app.route("/accounting/record/delete/<int:record_id>")
@admin_required
def accounting_delete_record(record_id):
    """حذف سند حسابداری"""
    db.delete_accounting_record(record_id)
    flash("سند حسابداری با موفقیت حذف شد.", "success")
    return redirect(url_for("accounting"))


@app.route("/export/accounting")
@admin_required
def export_accounting():
    """خروجی اکسل و CSV استاندارد از دفتر کل حسابداری با فرمت UTF-8 BOM"""
    records = db.get_accounting_records(limit=1000)
    summary = db.get_accounting_summary()

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow(["شناسه سند", "نوع (درآمد/هزینه)", "دسته‌بندی", "عنوان سند", "مبلغ (تومان)", "منبع", "تاریخ", "توضیحات"])
    for r in records:
        type_fa = "درآمد" if r.get("type") == "income" else "هزینه"
        source_fa = "خودکار" if r.get("source") == "auto" else "دستی"
        writer.writerow([
            r.get("id"),
            type_fa,
            r.get("category") or "",
            r.get("title") or "",
            r.get("amount") or 0,
            source_fa,
            r.get("date") or "",
            r.get("description") or ""
        ])

    csv_data = "\ufeff" + output.getvalue()
    return Response(
        csv_data.encode("utf-8-sig"),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment;filename=accounting_ledger_export.csv"}
    )


# ═══════════════════════════════════════════════════════════════════════
# بخش پیام همگانی و برودکست (Targeted Broadcast Engine)
# ═══════════════════════════════════════════════════════════════════════

@app.route("/broadcast", methods=["GET", "POST"])
@admin_required
def broadcast():
    """ارسال پیام انبوه هدفمند به کاربران تلگرام"""
    if request.method == "POST":
        target_group = request.form.get("target_group", "all")
        message_text = request.form.get("message", "").strip()
        btn_text = request.form.get("btn_text", "").strip()
        btn_url = request.form.get("btn_url", "").strip()

        if not message_text:
            flash("متن پیام نمی‌تواند خالی باشد!", "danger")
            return redirect(url_for("broadcast"))

        user_ids = db.get_target_broadcast_users(target_group)
        if not user_ids:
            flash("هیچ کاربری در گروه هدف انتخاب شده یافت نشد.", "warning")
            return redirect(url_for("broadcast"))

        reply_markup = None
        if btn_text and btn_url:
            reply_markup = {"inline_keyboard": [[{"text": btn_text, "url": btn_url}]]}

        success_count = 0
        fail_count = 0
        for uid in user_ids:
            ok = send_telegram_msg(uid, message_text, reply_markup=reply_markup)
            if ok:
                success_count += 1
            else:
                fail_count += 1

        flash(f"پیام به {success_count} کاربر ارسال شد. (خطا: {fail_count})", "success")
        return redirect(url_for("broadcast"))

    return render_template("broadcast.html")


# ═══════════════════════════════════════════════════════════════════════
# بخش پشتیبانی و تیکتینگ تحت وب (Web Support Desk)
# ═══════════════════════════════════════════════════════════════════════

@app.route("/tickets")
@admin_required
def tickets():
    """لیست تیکت‌های پشتیبانی"""
    conn = db.get_connection()
    ticket_list = conn.execute("""
        SELECT t.*, u.username
        FROM support_tickets t
        LEFT JOIN users u ON t.telegram_id = u.telegram_id
        ORDER BY t.created_at DESC
    """).fetchall()
    conn.close()
    return render_template("tickets.html", tickets=ticket_list)


@app.route("/ticket/reply/<int:ticket_id>", methods=["POST"])
@admin_required
def ticket_reply(ticket_id):
    """ارسال پاسخ به تیکت از پنل وب مستقیم به تلگرام کاربر"""
    reply_text = request.form.get("reply", "").strip()
    if not reply_text:
        flash("متن پاسخ نمی‌تواند خالی باشد.", "danger")
        return redirect(url_for("tickets"))

    ticket = db.get_ticket(ticket_id)
    if ticket:
        db.reply_ticket(ticket_id, reply_text)
        user_id = ticket["telegram_id"]
        msg = f"🔔 <b>پاسخ پشتیبانی به تیکت #{ticket_id}:</b>\n\n{reply_text}\n\n──────────────\nدر صورت نیاز به پیام مجدد از دکمه «💬 پشتیبانی» استفاده فرمایید."
        send_telegram_msg(user_id, msg)
        flash(f"پاسخ به تیکت #{ticket_id} با موفقیت به تلگرام کاربر ارسال شد!", "success")

    return redirect(url_for("tickets"))


# ═══════════════════════════════════════════════════════════════════════
# مدیریت کارت‌های بانکی مقصد (Bank Card Rotator)
# ═══════════════════════════════════════════════════════════════════════

@app.route("/cards", methods=["GET", "POST"])
@admin_required
def cards():
    """مدیریت کارت‌های بانکی و سقف تراکنش"""
    if request.method == "POST":
        card_num = request.form.get("card_number")
        holder = request.form.get("card_holder")
        bank = request.form.get("bank_name")
        limit = int(request.form.get("daily_limit", 50000000))
        db.add_bank_card(card_num, holder, bank, limit)
        flash("کارت بانکی جدید افزوده شد.", "success")
        return redirect(url_for("cards"))

    cards_list = db.get_all_bank_cards()
    return render_template("cards.html", cards=cards_list)


@app.route("/card/toggle/<int:card_id>")
@admin_required
def card_toggle(card_id):
    """فعال/غیرفعال کردن کارت"""
    cards_list = db.get_all_bank_cards()
    target = next((c for c in cards_list if c["id"] == card_id), None)
    if target:
        db.toggle_bank_card(card_id, not bool(target["is_active"]))
    return redirect(url_for("cards"))


@app.route("/card/delete/<int:card_id>")
@admin_required
def card_delete(card_id):
    """حذف کارت"""
    db.delete_bank_card(card_id)
    flash("کارت بانکی حذف شد.", "info")
    return redirect(url_for("cards"))


# ═══════════════════════════════════════════════════════════════════════
# مدیریت و ویرایش کامل پلن‌های فروش
# ═══════════════════════════════════════════════════════════════════════

@app.route("/plans", methods=["GET", "POST"])
@admin_required
def admin_plans_page():
    """مدیریت و ویرایش کامل پلن‌ها"""
    if request.method == "POST":
        action = request.form.get("action")
        if action == "add":
            name = request.form.get("name", "").strip()
            price = int(request.form.get("price", 0))
            data_limit = int(request.form.get("data_limit", 0))
            duration = int(request.form.get("duration", 30))
            res = add_plan(name, price, data_limit, duration)
            if res.get("success"):
                flash("پلن جدید با موفقیت افزوده شد.", "success")
            else:
                flash(f"خطا در افزودن پلن: {res.get('error')}", "danger")
        return redirect(url_for("admin_plans_page"))

    plans = get_all_plans()
    return render_template("plans.html", plans=plans)


@app.route("/plans/edit/<plan_id>", methods=["POST"])
@admin_required
def admin_plan_edit(plan_id):
    """ویرایش کامل مشخصات پلن و تغییر شناسه"""
    new_plan_id = request.form.get("new_plan_id", "").strip().lower().replace(" ", "_")
    name = request.form.get("name", "").strip()
    price = int(request.form.get("price", 0))
    data_limit = int(request.form.get("data_limit", 0))
    duration = int(request.form.get("duration", 30))
    is_active = request.form.get("is_active") == "1"

    update_kwargs = {
        "name": name,
        "price": price,
        "data_limit": data_limit,
        "duration": duration,
        "is_active": is_active,
    }
    if new_plan_id and new_plan_id != plan_id:
        update_kwargs["new_plan_id"] = new_plan_id

    res = update_plan(plan_id, **update_kwargs)
    if res.get("success"):
        flash("پلن با موفقیت بروزرسانی شد.", "success")
    else:
        flash(f"خطا در ویرایش پلن: {res.get('error')}", "danger")
    return redirect(url_for("admin_plans_page"))


@app.route("/plans/toggle/<plan_id>")
@admin_required
def admin_plan_toggle(plan_id):
    """فعال/غیرفعال کردن پلن"""
    plans = get_all_plans()
    if plan_id in plans:
        current = plans[plan_id].get("is_active", False)
        update_plan(plan_id, is_active=not current)
        flash("وضعیت پلن تغییر یافت.", "info")
    return redirect(url_for("admin_plans_page"))


@app.route("/plans/delete/<plan_id>")
@admin_required
def admin_plan_delete(plan_id):
    """حذف پلن"""
    res = delete_plan(plan_id)
    if res.get("success"):
        flash("پلن حذف شد.", "warning")
    else:
        flash(f"خطا در حذف پلن: {res.get('error')}", "danger")
    return redirect(url_for("admin_plans_page"))


@app.route("/plans/move-up/<plan_id>")
@admin_required
def admin_plan_move_up(plan_id):
    """انتقال پلن به بالا در ترتیب عمودی"""
    res = move_plan_up(plan_id)
    if res.get("success"):
        flash("ترتیب پلن با موفقیت به سمت بالا تغییر یافت.", "success")
    else:
        flash(f"خطا: {res.get('error', 'امکان جابجایی وجود ندارد')}", "warning")
    return redirect(url_for("admin_plans_page"))


@app.route("/plans/move-down/<plan_id>")
@admin_required
def admin_plan_move_down(plan_id):
    """انتقال پلن به پایین در ترتیب عمودی"""
    res = move_plan_down(plan_id)
    if res.get("success"):
        flash("ترتیب پلن با موفقیت به سمت پایین تغییر یافت.", "success")
    else:
        flash(f"خطا: {res.get('error', 'امکان جابجایی وجود ندارد')}", "warning")
    return redirect(url_for("admin_plans_page"))


# ═══════════════════════════════════════════════════════════════════════
# مدیریت کدهای تخفیف
# ═══════════════════════════════════════════════════════════════════════

@app.route("/discounts", methods=["GET", "POST"])
@admin_required
def admin_discounts_page():
    """مشاهده و ایجاد کدهای تخفیف"""
    if request.method == "POST":
        code = request.form.get("code", "").strip().upper()
        percent = int(request.form.get("discount_percent") or 0)
        amount = int(request.form.get("discount_amount") or 0)
        max_uses = int(request.form.get("max_uses") or 0)
        valid_days = request.form.get("valid_days")

        valid_until = None
        if valid_days and int(valid_days) > 0:
            valid_until = (get_now_naive() + timedelta(days=int(valid_days))).isoformat()

        if code and (percent > 0 or amount > 0):
            res = db.create_discount_code(code, discount_percent=percent, discount_amount=amount, max_uses=max_uses, valid_until=valid_until)
            if res.get("success"):
                flash(f"کد تخفیف {code} با موفقیت ایجاد شد.", "success")
            else:
                flash(f"خطا در ایجاد کد تخفیف: {res.get('error')}", "danger")
        else:
            flash("لطفاً کد تخفیف و درصد یا مبلغ تخفیف را وارد کنید.", "warning")
        return redirect(url_for("admin_discounts_page"))

    discounts = db.get_all_discount_codes()
    return render_template("discounts.html", discounts=discounts)


@app.route("/discounts/delete/<code>")
@admin_required
def admin_discount_delete(code):
    """حذف کد تخفیف"""
    res = db.delete_discount_code(code)
    if res.get("success"):
        flash(f"کد تخفیف {code} حذف شد.", "info")
    else:
        flash("خطا در حذف کد تخفیف.", "danger")
    return redirect(url_for("admin_discounts_page"))


# ═══════════════════════════════════════════════════════════════════════
# مانیتورینگ سلامت، لاگ‌ها و گزارشات مالی
# ═══════════════════════════════════════════════════════════════════════

@app.route("/reports")
@admin_required
def reports():
    """گزارشات آماری و هوش مالی پیشرفته مدیر کل"""
    conn = db.get_connection()
    total_revenue = conn.execute("SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE status IN ('approved', 'completed')").fetchone()[0]
    total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    active_subs = conn.execute("SELECT COUNT(*) FROM subscriptions WHERE status='active'").fetchone()[0]
    monthly_revenue = conn.execute("""
        SELECT strftime('%Y-%m', created_at) as month, SUM(amount) as total, COUNT(*) as count
        FROM transactions WHERE status IN ('approved', 'completed')
        GROUP BY strftime('%Y-%m', created_at) ORDER BY month DESC LIMIT 12
    """).fetchall()
    conn.close()

    analytics = db.get_advanced_analytics()

    return render_template(
        "reports.html",
        total_revenue=total_revenue,
        total_users=total_users,
        active_subs=active_subs,
        monthly_revenue=monthly_revenue,
        popular_plans=analytics.get("popular_plans", []),
        top_users_month=analytics.get("top_users_month", []),
        top_users_year=analytics.get("top_users_year", []),
        most_active_users=analytics.get("most_active_users", []),
        usage_history=analytics.get("usage_history", []),
        timeline_subscriptions=analytics.get("timeline_subscriptions", [])
    )


@app.route("/export/transactions")
@admin_required
def export_transactions():
    """خروجی اکسل/CSV استاندارد با پشتیبانی کامل از زبان فارسی (UTF-8 BOM)"""
    conn = db.get_connection()
    rows = conn.execute("""
        SELECT id, order_id, user_id, username, plan_name, amount, gateway, tracking_code, 
               CASE 
                   WHEN status IN ('approved', 'completed') THEN 'تایید شده'
                   WHEN status = 'pending' THEN 'در انتظار بررسی'
                   WHEN status = 'rejected' THEN 'رد شده'
                   ELSE status 
               END as status_fa,
               created_at 
        FROM transactions 
        ORDER BY created_at DESC
    """).fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["شناسه", "شماره سفارش", "آیدی عددی تلگرام", "نام کاربری", "نام پلن", "مبلغ (تومان)", "درگاه پرداخت", "کد پیگیری / فیش", "وضعیت", "تاریخ ثبت"])
    for r in rows:
        writer.writerow([
            r["id"],
            r["order_id"] or "",
            r["user_id"] or "",
            r["username"] or "",
            r["plan_name"] or "",
            r["amount"] or 0,
            r["gateway"] or "",
            r["tracking_code"] or "",
            r["status_fa"] or "",
            r["created_at"] or ""
        ])

    csv_data = "\ufeff" + output.getvalue()
    return Response(
        csv_data.encode("utf-8-sig"),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment;filename=transactions_export.csv"}
    )


@app.route("/admin/logs")
@app.route("/logs")
@admin_required
def admin_logs():
    """مشاهده لاگ‌های زنده سرور"""
    health = hidify_sync_ping()
    return render_template("logs.html", health=health)


@app.route("/settings", methods=["GET", "POST"])
@admin_required
def settings():
    """تنظیمات کلی سیستم، قالب لینک اتصال تکی و سامانه پیامک"""
    if request.method == "POST":
        action = request.form.get("action")
        if action == "save_single_link_template":
            tpl = request.form.get("single_link_template", "").strip()
            db.save_setting("single_link_template", tpl)
            flash("قالب آماده لینک اتصال تکی با موفقیت ذخیره شد.", "success")
            return redirect(url_for("settings"))
        elif action == "save_sms_settings":
            sms_enabled = "true" if request.form.get("sms_enabled") == "on" else "false"
            sms_provider = request.form.get("sms_provider", "ippanel").strip().lower()
            sms_api_key = request.form.get("sms_api_key", "").strip()
            sms_originator = request.form.get("sms_originator", "").strip()
            sms_pattern_login = request.form.get("sms_pattern_login", "").strip()
            sms_pattern_failed = request.form.get("sms_pattern_failed", "").strip()
            sms_pattern_logout = request.form.get("sms_pattern_logout", "").strip()

            db.save_setting("sms_enabled", sms_enabled)
            db.save_setting("sms_provider", sms_provider)
            if sms_api_key:
                db.save_setting("sms_api_key", sms_api_key)
            db.save_setting("sms_originator", sms_originator)
            db.save_setting("sms_pattern_login", sms_pattern_login)
            db.save_setting("sms_pattern_failed", sms_pattern_failed)
            db.save_setting("sms_pattern_logout", sms_pattern_logout)

            flash("تنظیمات درگاه پیامک با موفقیت ذخیره شد.", "success")
            return redirect(url_for("settings"))

    conn = db.get_connection()
    settings_list = conn.execute("SELECT * FROM settings").fetchall()
    conn.close()
    single_link_template = get_single_link_template(db)
    sms_config = get_sms_config(db)
    return render_template("settings.html", settings=settings_list, single_link_template=single_link_template, sms_config=sms_config)


@app.route("/admin/sms/test", methods=["POST"])
@admin_required
def admin_sms_test():
    """ارسال پیامک آزمایشی جهت تست صحت اتصال به درگاه پیامکی"""
    test_phone = request.form.get("test_phone", "").strip()
    if not test_phone:
        return jsonify({"success": False, "error": "لطفاً شماره تلفن همراه را وارد نمایید."})

    success, msg = send_sms(
        receptor=test_phone,
        message="✅ تست اتصال به درگاه پیامکی سامانه HiddiBot با موفقیت انجام شد.",
        db_instance=db
    )
    if success:
        return jsonify({"success": True, "message": f"پیامک آزمایشی با موفقیت به شماره {test_phone} ارسال شد."})
    else:
        return jsonify({"success": False, "error": msg})


@app.route("/admin/sync-hidify", methods=["GET", "POST"])
@admin_required
def admin_sync_hidify():
    """همگام‌سازی و بازیابی کاربران از پنل هیدیفای"""
    try:
        users = hidify_sync_request("GET", "/admin/user/")
        if isinstance(users, list):
            res = db.sync_from_hidify(users)
            if res.get("success"):
                flash(f"همگام‌سازی با موفقیت انجام شد! {res.get('total_hiddify', 0)} کاربر از هیدیفای بررسی و دیتابیس بروزرسانی شد.", "success")
            else:
                flash(f"خطا در ثبت دیتابیس: {res.get('error')}", "danger")
        else:
            flash(f"خطا در دریافت اطلاعات از هیدیفای: {users.get('error', 'پاسخ نامعتبر')}", "danger")
    except Exception as e:
        flash(f"خطا: {str(e)}", "danger")
    return redirect(url_for("dashboard"))


@app.route("/admin/backup/download")
@admin_required
def download_backup():
    """دانلود فایل دیتابیس SQLite"""
    if db.db_path.exists():
        timestamp = get_now_naive().strftime("%Y%m%d_%H%M%S")
        return send_file(
            str(db.db_path),
            as_attachment=True,
            download_name=f"bot_database_{timestamp}.db",
            mimetype="application/x-sqlite3"
        )
    flash("فایل دیتابیس یافت نشد!", "danger")
    return redirect(url_for("dashboard"))


@app.route("/admin/backup/upload", methods=["POST"])
@admin_required
def upload_backup():
    """آپلود و بازیابی فایل دیتابیس SQLite"""
    file = request.files.get("backup_file")
    if not file or not file.filename.endswith(".db"):
        flash("لطفاً یک فایل دیتابیس با پسوند .db انتخاب کنید.", "warning")
        return redirect(url_for("settings"))

    try:
        from backup import BackupManager
        bm = BackupManager()
        temp_path = db.db_dir / f"uploaded_{get_now_naive().strftime('%Y%m%d_%H%M%S')}.db"
        file.save(temp_path)
        res = bm.restore_backup(str(temp_path))
        if res.get("success"):
            flash("دیتابیس با موفقیت از فایل آپلود شده بازیابی شد!", "success")
        else:
            flash(f"خطا در بازیابی دیتابیس: {res.get('error')}", "danger")
    except Exception as e:
        flash(f"خطا در پردازش فایل: {str(e)}", "danger")

    return redirect(url_for("settings"))


# ═══════════════════════════════════════════════════════════════════════
# پنل اختصاصی نمایندگان و همکاران فروش (Reseller Portal Routes)
# ═══════════════════════════════════════════════════════════════════════

@app.route("/reseller/dashboard")
@reseller_required
def reseller_dashboard():
    """داشبورد اصلی نماینده فروش به همراه هوش مالی و خلاصه وضعیت"""
    reseller_id = session.get("reseller_id")
    stats = db.get_reseller_stats(reseller_id)
    session["balance"] = stats["balance"]
    recent_transactions = db.get_reseller_transactions(reseller_id, limit=6)
    analytics = db.get_advanced_analytics(reseller_id=reseller_id)
    return render_template(
        "reseller_dashboard.html",
        stats=stats,
        recent_transactions=recent_transactions,
        analytics=analytics
    )


@app.route("/reseller/create-user", methods=["GET", "POST"])
@reseller_required
def reseller_create_user():
    """ساخت آنی اشتراک مشتری توسط نماینده با کسر اعتبار عمده‌فروشی"""
    reseller_id = session.get("reseller_id")
    stats = db.get_reseller_stats(reseller_id)
    discount = stats["discount_percent"]
    plans = get_plans_dict()

    if request.method == "POST":
        plan_key = request.form.get("plan_id")
        account_name = request.form.get("account_name", "").strip()
        phone_number = request.form.get("phone_number", "").strip()

        if plan_key not in plans:
            flash("پلن انتخابی نامعتبر است.", "danger")
            return redirect(url_for("reseller_create_user"))

        plan = plans[plan_key]
        original_price = plan["price"]
        discount_amount = int((original_price * discount) / 100)
        final_price = original_price - discount_amount

        if stats["balance"] < final_price:
            flash(f"اعتبار کیف پول شما کافی نیست! موجودی: {stats['balance']:,} تومان | مبلغ مورد نیاز: {final_price:,} تومان", "danger")
            return redirect(url_for("reseller_create_user"))

        if not account_name:
            account_name = f"res_{reseller_id}_{int(time.time()) % 10000}"

        user_comment = f"Reseller #{reseller_id} ({session.get('name')})"
        if phone_number:
            user_comment += f" | Phone: {phone_number}"

        # ۱. ابتدا ساخت کاربر در سرور هیدیفای انجام می‌شود
        h_res = hidify_sync_create_user(
            name=account_name,
            usage_limit_gb=plan["data_limit"],
            package_days=plan["duration"],
            comment=user_comment
        )

        user_uuid = h_res.get("uuid", "")
        if not user_uuid:
            err_msg = h_res.get("error", "پاسخ نامعتبر از سرور")
            flash(f"خطا در ساخت اکانت روی سرور هیدیفای: {err_msg}", "danger")
            return redirect(url_for("reseller_create_user"))

        # ۲. پس از تایید ۱۰۰٪ ساخت در هیدیفای، موجودی کسر و تراکنش خرید ثبت می‌گردد
        deduct_res = db.deduct_reseller_balance(reseller_id, final_price, plan["name"], account_name)
        if not deduct_res.get("success"):
            logger.error(f"Failed to deduct balance after user creation: {deduct_res.get('error')}")

        # ۳. ثبت اشتراک با شناسه نماینده، شماره تلفن و هزینه پرداخت‌شده در دیتابیس
        conn = db.get_connection()
        conn.execute("""
            INSERT INTO subscriptions 
            (telegram_id, hidify_uuid, plan_id, plan_name, account_name, phone_number, data_limit, duration, status, reseller_id, cost_paid, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?)
        """, (
            0, user_uuid, plan_key, plan["name"], account_name, phone_number or None,
            plan["data_limit"], plan["duration"], reseller_id, final_price, get_now_iso(), get_now_iso()
        ))
        conn.commit()
        conn.close()

        subscription_url = f"{get_hiddify_url()}/{get_user_proxy()}/{user_uuid}/"
        single_link_template = get_single_link_template(db)
        single_url = format_single_link(single_link_template, uuid=user_uuid, name=account_name)
        flash(f"اشتراک «{account_name}» با موفقیت ساخته شد و مبلغ {final_price:,} تومان از کیف پول شما کسر گردید.", "success")

        return render_template(
            "reseller_created_success.html",
            account_name=account_name,
            plan=plan,
            sub_url=subscription_url,
            single_url=single_url,
            final_price=final_price
        )

    return render_template("reseller_create_user.html", plans=plans, discount=discount, balance=stats["balance"])


@app.route("/reseller/users")
@reseller_required
def reseller_users():
    """لیست مشتریان نماینده به همراه آمار و دسترسی به ویرایش، تمدید و حذف"""
    reseller_id = session.get("reseller_id")
    stats = db.get_reseller_stats(reseller_id)
    discount = stats["discount_percent"]
    plans = get_plans_dict()
    
    raw_subs = db.get_reseller_subscriptions(reseller_id)
    subs = []
    for s in raw_subs:
        item = dict(s)
        refund_calc = db.calculate_reseller_refund(reseller_id, item["id"])
        item["refund_info"] = refund_calc
        subs.append(item)

    single_link_template = get_single_link_template(db)
    return render_template(
        "reseller_users.html",
        subscriptions=subs,
        plans=plans,
        discount=discount,
        balance=stats["balance"],
        panel_url=get_hiddify_url(),
        user_proxy=get_user_proxy(),
        single_link_template=single_link_template
    )


@app.route("/reseller/subscription/<int:sub_id>/edit", methods=["POST"])
@reseller_required
def reseller_edit_user(sub_id: int):
    """ویرایش مشخصات مشتری نماینده"""
    reseller_id = session.get("reseller_id")
    sub = db.get_reseller_subscription(reseller_id, sub_id)
    if not sub:
        flash("اشتراک مورد نظر یافت نشد.", "danger")
        return redirect(url_for("reseller_users"))

    account_name = request.form.get("account_name", "").strip() or sub["account_name"]
    phone_number = request.form.get("phone_number", "").strip()
    comment = request.form.get("comment", "").strip()

    # ۱. بروزرسانی در دیتابیس محلی
    db.update_reseller_subscription(reseller_id, sub_id, account_name, phone_number, comment)

    # ۲. بروزرسانی در هیدیفای
    if sub.get("hidify_uuid"):
        full_comment = f"Reseller #{reseller_id} ({session.get('name')})"
        if phone_number:
            full_comment += f" | Phone: {phone_number}"
        if comment:
            full_comment += f" | {comment}"
        hidify_sync_update_user(sub["hidify_uuid"], name=account_name, comment=full_comment[:200])

    flash(f"مشخصات اشتراک «{account_name}» با موفقیت بروزرسانی شد.", "success")
    return redirect(url_for("reseller_users"))


@app.route("/reseller/subscription/<int:sub_id>/toggle", methods=["POST"])
@reseller_required
def reseller_toggle_user(sub_id: int):
    """فعال یا غیرفعال کردن مشتری نماینده (بدون کسر یا استرداد هزینه)"""
    reseller_id = session.get("reseller_id")
    sub = db.get_reseller_subscription(reseller_id, sub_id)
    if not sub:
        flash("اشتراک مورد نظر یافت نشد.", "danger")
        return redirect(url_for("reseller_users"))

    res = db.toggle_reseller_subscription(reseller_id, sub_id)
    if res.get("success"):
        new_status = res.get("status")
        is_active = (new_status == "active")
        if sub.get("hidify_uuid"):
            hidify_sync_update_user(sub["hidify_uuid"], enable=is_active, is_active=is_active)
        
        status_fa = "فعال" if is_active else "غیرفعال"
        flash(f"وضعیت اشتراک «{sub['account_name']}» به حالت «{status_fa}» تغییر یافت. (هیچ مبلغی کسر یا اضافه نشد)", "info")
    else:
        flash(f"خطا در تغییر وضعیت: {res.get('error')}", "danger")

    return redirect(url_for("reseller_users"))


@app.route("/reseller/subscription/<int:sub_id>/renew", methods=["POST"])
@reseller_required
def reseller_renew_user(sub_id: int):
    """تمدید اشتراک مشتری با کسر اعتبار تخفیف‌دار نماینده"""
    reseller_id = session.get("reseller_id")
    sub = db.get_reseller_subscription(reseller_id, sub_id)
    if not sub:
        flash("اشتراک مورد نظر یافت نشد.", "danger")
        return redirect(url_for("reseller_users"))

    plan_key = request.form.get("plan_id")
    plans = get_plans_dict()
    if plan_key not in plans:
        flash("پلن انتخابی نامعتبر است.", "danger")
        return redirect(url_for("reseller_users"))

    plan = plans[plan_key]
    stats = db.get_reseller_stats(reseller_id)
    discount = stats["discount_percent"]
    original_price = plan["price"]
    discount_amount = int((original_price * discount) / 100)
    final_price = original_price - discount_amount

    if stats["balance"] < final_price:
        flash(f"موجودی کیف پول شما برای تمدید این پلن کافی نیست! موجودی: {stats['balance']:,} ت | هزینه تمدید: {final_price:,} ت", "danger")
        return redirect(url_for("reseller_users"))

    # ۱. تمدید هوشمند در هیدیفای
    renewal_res = {"renewal_type": "reset_and_replaced"}
    if sub.get("hidify_uuid"):
        renewal_res = hidify_sync_renew_user(sub["hidify_uuid"], plan["data_limit"], plan["duration"])

    # ۲. ثبت در دیتابیس و کسر موجودی
    renew_db = db.renew_reseller_subscription(
        reseller_id=reseller_id,
        sub_id=sub_id,
        plan_id=plan_key,
        plan_name=plan["name"],
        cost=final_price,
        data_limit=plan["data_limit"],
        duration=plan["duration"],
        renewal_type=renewal_res.get("renewal_type", "reset_and_replaced")
    )

    if renew_db.get("success"):
        # ثبت در تاریخچه سوابق مصرف دوره‌های گذشته
        try:
            db.log_subscription_history(
                subscription_id=sub_id,
                telegram_id=sub.get("telegram_id") or 0,
                hidify_uuid=sub.get("hidify_uuid") or "",
                account_name=sub["account_name"],
                plan_name=plan["name"],
                previous_usage_gb=sub.get("data_used") or 0,
                previous_limit_gb=sub.get("data_limit") or 0,
                period_days=plan["duration"],
                renewal_type=renewal_res.get("renewal_type", "reset_and_replaced"),
                reseller_id=reseller_id
            )
        except Exception as e:
            logger.warning(f"Failed to log subscription history on reseller renew: {e}")

        flash(f"اشتراک «{sub['account_name']}» با پلن «{plan['name']}» با موفقیت تمدید شد و مبلغ {final_price:,} تومان از کیف پول شما کسر گردید.", "success")
    else:
        flash(f"خطا در تمدید اشتراک: {renew_db.get('error')}", "danger")

    return redirect(url_for("reseller_users"))


@app.route("/reseller/subscription/<int:sub_id>/delete", methods=["POST"])
@reseller_required
def reseller_delete_user(sub_id: int):
    """حذف اشتراک مشتری توسط نماینده با استرداد وجه طبق قوانین بازه ۱۲ و ۲۴ ساعته"""
    reseller_id = session.get("reseller_id")
    sub = db.get_reseller_subscription(reseller_id, sub_id)
    if not sub:
        flash("اشتراک مورد نظر یافت نشد.", "danger")
        return redirect(url_for("reseller_users"))

    # ۱. حذف کاربر از سرور هیدیفای
    if sub.get("hidify_uuid"):
        try:
            hidify_sync_delete_user(sub["hidify_uuid"])
        except Exception as e:
            logger.warning(f"Error deleting user {sub['hidify_uuid']} from Hiddify: {e}")

    # ۲. اجرای حذف در دیتابیس با محاسبه استرداد وجه
    del_res = db.delete_reseller_subscription(reseller_id, sub_id)
    if del_res.get("success"):
        refund_amount = del_res.get("refund_amount", 0)
        refund_percent = del_res.get("refund_percent", 0)
        time_passed = del_res.get("time_passed_text", "")

        if refund_amount > 0:
            flash(f"اشتراک «{sub['account_name']}» با موفقیت حذف گردید و مبلغ {refund_amount:,} تومان ({refund_percent}٪ استرداد - مدت زمان گذشته: {time_passed}) به کیف پول شما بازگردانده شد.", "success")
        else:
            flash(f"اشتراک «{sub['account_name']}» با موفقیت حذف گردید. (به دلیل سپری شدن بیش از ۲۴ ساعت از زمان ساخت، استرداد وجه تعلق نگرفت)", "warning")
    else:
        flash(f"خطا در حذف اشتراک: {del_res.get('error')}", "danger")

    return redirect(url_for("reseller_users"))


@app.route("/reseller/transactions")
@reseller_required
def reseller_transactions():
    """لیست تراکنش‌ها و شارژ کیف پول نماینده"""
    reseller_id = session.get("reseller_id")
    tx_list = db.get_reseller_transactions(reseller_id)
    stats = db.get_reseller_stats(reseller_id)
    return render_template("reseller_transactions.html", transactions=tx_list, stats=stats)


@app.route("/reseller/reports")
@reseller_required
def reseller_reports():
    """گزارشات و هوش مالی پیشرفته نماینده فروش"""
    reseller_id = session.get("reseller_id")
    stats = db.get_reseller_stats(reseller_id)
    analytics = db.get_advanced_analytics(reseller_id=reseller_id)
    
    return render_template(
        "reseller_reports.html",
        stats=stats,
        popular_plans=analytics.get("popular_plans", []),
        top_users_month=analytics.get("top_users_month", []),
        top_users_year=analytics.get("top_users_year", []),
        most_active_users=analytics.get("most_active_users", []),
        usage_history=analytics.get("usage_history", []),
        timeline_subscriptions=analytics.get("timeline_subscriptions", [])
    )


@app.route("/reseller/export/transactions")
@reseller_required
def reseller_export_transactions():
    """خروجی اکسل/CSV تراکنش‌های نماینده با پشتیبانی کامل از فونت فارسی (UTF-8 BOM)"""
    reseller_id = session.get("reseller_id")
    tx_list = db.get_reseller_transactions(reseller_id, limit=500)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["شناسه", "نوع تراکنش", "مبلغ (تومان)", "نام پلن", "نام کاربری اشتراک", "توضیحات", "تاریخ ثبت"])
    for t in tx_list:
        ttype = "شارژ کیف پول" if t.get("type") == "deposit" else "خرید اشتراک"
        writer.writerow([
            t.get("id"),
            ttype,
            t.get("amount") or 0,
            t.get("plan_name") or "",
            t.get("account_name") or "",
            t.get("description") or "",
            t.get("created_at") or ""
        ])

    csv_data = "\ufeff" + output.getvalue()
    return Response(
        csv_data.encode("utf-8-sig"),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment;filename=reseller_transactions_export.csv"}
    )


# ═══════════════════════════════════════════════════════════════════════
# مدیریت مدیران و سطوح دسترسی (Admin Management & RBAC)
# ═══════════════════════════════════════════════════════════════════════

@app.route("/admin/managers", methods=["GET", "POST"])
@admin_required
def admin_managers():
    """لیست و افزودن مدیران با سطوح دسترسی مختلف"""
    if request.method == "POST":
        display_name = request.form.get("display_name", "").strip()
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        role = request.form.get("role", "support").strip()

        # نقشه‌برداری دسترسی‌ها بر اساس نقش
        perms_map = {
            "super_admin": "*",
            "finance": "dashboard,payments,accounting,cards,reports",
            "support": "dashboard,users,subs,tickets,broadcast",
            "viewer": "dashboard,users,subs,reports,logs",
        }
        permissions = perms_map.get(role, "*")

        telegram_id_raw = request.form.get("telegram_id", "").strip()
        telegram_id = int(telegram_id_raw) if telegram_id_raw.isdigit() else None

        if username and password and display_name:
            res = db.create_admin_user(username, password, display_name, role=role, permissions=permissions, telegram_id=telegram_id)
            if res.get("success"):
                flash(f"مدیر جدید «{display_name}» با موفقیت افزوده شد.", "success")
            else:
                flash(f"خطا در ایجاد مدیر: {res.get('error')}", "danger")
        else:
            flash("لطفاً تمامی فیلدهای الزامی را تکمیل نمایید.", "warning")
        return redirect(url_for("admin_managers"))

    managers_list = db.get_admin_users()
    return render_template("managers.html", managers=managers_list)


@app.route("/admin/manager/<int:admin_id>/edit", methods=["POST"])
@admin_required
def admin_manager_edit(admin_id):
    """ویرایش اطلاعات و دسترسی‌های مدیر"""
    display_name = request.form.get("display_name", "").strip()
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()
    role = request.form.get("role", "support").strip()
    telegram_id_raw = request.form.get("telegram_id", "").strip()
    telegram_id = int(telegram_id_raw) if telegram_id_raw.isdigit() else None

    perms_map = {
        "super_admin": "*",
        "finance": "dashboard,payments,accounting,cards,reports",
        "support": "dashboard,users,subs,tickets,broadcast",
        "viewer": "dashboard,users,subs,reports,logs",
    }
    permissions = perms_map.get(role, "*")

    update_kwargs = {
        "display_name": display_name,
        "username": username,
        "role": role,
        "permissions": permissions,
        "telegram_id": telegram_id,
    }
    if password and len(password) > 0:
        update_kwargs["password"] = password

    res = db.update_admin_user(admin_id, **update_kwargs)
    if res.get("success"):
        flash("مشخصات مدیر با موفقیت بروزرسانی شد.", "success")
    else:
        flash(f"خطا در ویرایش مدیر: {res.get('error')}", "danger")
    return redirect(url_for("admin_managers"))


@app.route("/admin/manager/<int:admin_id>/toggle")
@admin_required
def admin_manager_toggle(admin_id):
    """تغییر وضعیت فعال/غیرفعال مدیر"""
    if admin_id == session.get("admin_id"):
        flash("شما نمی‌توانید حساب کاربری خودتان را غیرفعال کنید!", "warning")
        return redirect(url_for("admin_managers"))

    res = db.toggle_admin_user(admin_id)
    if res.get("success"):
        flash("وضعیت مدیر با موفقیت تغییر یافت.", "info")
    else:
        flash(f"خطا: {res.get('error')}", "danger")
    return redirect(url_for("admin_managers"))


@app.route("/admin/manager/<int:admin_id>/delete")
@admin_required
def admin_manager_delete(admin_id):
    """حذف مدیر"""
    if admin_id == session.get("admin_id"):
        flash("شما نمی‌توانید حساب کاربری خودتان را حذف کنید!", "danger")
        return redirect(url_for("admin_managers"))

    res = db.delete_admin_user(admin_id)
    if res.get("success"):
        flash("حساب مدیر با موفقیت حذف شد.", "warning")
    else:
        flash(f"خطا در حذف مدیر: {res.get('error')}", "danger")
    return redirect(url_for("admin_managers"))


@app.route("/admin/profile", methods=["GET", "POST"])
@admin_required
def admin_profile():
    """مشاهده و ویرایش مشخصات، نام کاربری و رمز عبور مدیر فعال"""
    admin_id = session.get("admin_id")
    admin_user = db.get_admin_user(admin_id) if admin_id else None
    if not admin_user:
        admins = db.get_admin_users()
        admin_user = admins[0] if admins else {
            "id": 1,
            "username": session.get("username", "admin"),
            "display_name": session.get("name", "مدیر سیستم"),
            "role": session.get("admin_role", "super_admin"),
            "telegram_id": get_admin_id(),
            "created_at": get_now_iso(),
            "last_login": get_now_iso()
        }

    if request.method == "POST":
        display_name = request.form.get("display_name", "").strip()
        username = request.form.get("username", "").strip()
        telegram_id_raw = request.form.get("telegram_id", "").strip()
        telegram_id = int(telegram_id_raw) if telegram_id_raw.isdigit() else None
        new_password = request.form.get("new_password", "").strip()
        confirm_password = request.form.get("confirm_password", "").strip()

        if new_password:
            if new_password != confirm_password:
                flash("رمز عبور جدید با تکرار آن مطابقت ندارد!", "danger")
                return render_template("admin_profile.html", admin=admin_user)
            if len(new_password) < 6:
                flash("رمز عبور باید حداقل ۶ کاراکتر باشد.", "warning")
                return render_template("admin_profile.html", admin=admin_user)

        res = db.update_admin_profile(
            admin_user["id"],
            username=username,
            password=new_password if new_password else None,
            display_name=display_name,
            telegram_id=telegram_id
        )
        if res.get("success"):
            session["username"] = username
            session["name"] = display_name
            if telegram_id:
                session["telegram_id"] = telegram_id
            flash("مشخصات حساب کاربری و رمز عبور شما با موفقیت بروزرسانی شد.", "success")
            return redirect(url_for("admin_profile"))
        else:
            flash(f"خطا در ذخیره مشخصات: {res.get('error')}", "danger")

    login_history = db.get_user_login_history("admin", admin_user["id"], limit=20)
    current_token = session.get("session_token", "")
    return render_template("admin_profile.html", admin=admin_user, login_history=login_history, current_token=current_token)


# ═══════════════════════════════════════════════════════════════════════
# پروفایل و مشخصات کاربری نماینده (Reseller Profile)
# ═══════════════════════════════════════════════════════════════════════

@app.route("/reseller/profile", methods=["GET", "POST"])
@reseller_required
def reseller_profile():
    """مشاهده و ویرایش مشخصات فردی، بانکی و تغییر رمز عبور توسط نماینده"""
    reseller_id = session.get("reseller_id")
    reseller = db.get_reseller(reseller_id)
    if not reseller:
        flash("اطلاعات نماینده یافت نشد!", "danger")
        return redirect(url_for("reseller_dashboard"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        username = request.form.get("username", "").strip()
        phone = request.form.get("phone", "").strip()
        email = request.form.get("email", "").strip()
        telegram_id = request.form.get("telegram_id", "").strip()
        bank_card = request.form.get("bank_card", "").strip()
        notes = request.form.get("notes", "").strip()
        new_password = request.form.get("new_password", "").strip()
        confirm_password = request.form.get("confirm_password", "").strip()

        if new_password:
            if new_password != confirm_password:
                flash("رمز عبور جدید با تکرار آن همخوانی ندارد!", "danger")
                return render_template("reseller_profile.html", reseller=reseller)
            if len(new_password) < 6:
                flash("رمز عبور باید حداقل ۶ کاراکتر باشد.", "warning")
                return render_template("reseller_profile.html", reseller=reseller)

        res = db.update_reseller_profile(
            reseller_id,
            name=name,
            username=username,
            phone=phone,
            email=email,
            telegram_id=telegram_id,
            bank_card=bank_card,
            notes=notes,
            password=new_password if new_password else None
        )
        if res.get("success"):
            session["name"] = name
            session["username"] = username
            flash("مشخصات حساب کاربری و اطلاعات تماس شما با موفقیت بروزرسانی شد.", "success")
            return redirect(url_for("reseller_profile"))
        else:
            flash(f"خطا در بروزرسانی حساب: {res.get('error')}", "danger")

    login_history = db.get_user_login_history("reseller", reseller_id, limit=20)
    current_token = session.get("session_token", "")
    return render_template("reseller_profile.html", reseller=reseller, login_history=login_history, current_token=current_token)


# ─── راه‌اندازی سرور وب ───

def run_dashboard(host="0.0.0.0", port=None, debug=False):
    if port is None:
        port = int(os.getenv("PORT", 5000))
    print(f"🌐 Modern Web Dashboard running at http://{host}:{port}")
    app.run(host=host, port=port, debug=debug, use_reloader=False)


def start_dashboard_thread():
    """اجرای داشبورد در thread جداگانه هنگام استارت بات"""
    import threading
    t = threading.Thread(target=run_dashboard, daemon=True)
    t.start()
    return t


if __name__ == "__main__":
    run_dashboard(debug=True)
