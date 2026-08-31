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
import threading
import random
from typing import Optional, Dict, List, Any, Tuple, Union
from datetime import datetime, timedelta
import math
from pathlib import Path
from flask import (
    Flask, render_template, request, redirect, url_for, session,
    jsonify, flash, Response, send_file, g
)

from dotenv import load_dotenv
load_dotenv()

from database import db
from utils import (
    generate_qr_code_bytes, get_now_iso, get_now_naive, get_single_link_template, 
    format_single_link, gregorian_to_shamsi, gregorian_to_shamsi_full, get_now_shamsi, TEHRAN_TZ
)
from admin_manager import get_all_plans, add_plan, update_plan, delete_plan, move_plan_up, move_plan_down
from sms_service import send_auth_sms_notification, send_sms, get_sms_config, format_iranian_phone
from payment import CryptoPaymentGateway
import avatar_generator
from multibot_manager import multibot_manager, ResellerBotInstance
from tutorials_data import PLATFORMS, TUTORIALS, TROUBLESHOOTING_GUIDES

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
    """تولید آواتار سه‌بعدی و مدرن محلی و ۱۰۰٪ آفلاین"""
    return avatar_generator.generate_procedural_avatar_svg(str(identifier))


def fetch_smart_avatar_bytes(identifier: str) -> tuple[bytes, str]:
    """
    دریافت هوشمند تصویر پروفایل:
    ۱. بررسی تصویر اختصاصی آپلود شده یا تنظیم شده در پایگاه داده
    ۲. تلاش برای دریافت عکس واقعی پروفایل تلگرام
    ۳. تولید آواتار سه‌بعدی و مدرن محلی و بدون نیاز به اینترنت (Procedural SVG)
    ۴. کش محلی خودکار جهت افزایش سرعت لود و عملکرد بلادرنگ
    """
    if not identifier:
        identifier = "Customer"

    raw_ident = str(identifier).strip()
    clean_ident = raw_ident.lstrip("@").strip()

    # ۰۰. بررسی مستقیم نام فایل در پوشه کش آواتارها و لوگوهای آپلود شده
    direct_file = AVATAR_CACHE_DIR / clean_ident
    if direct_file.exists() and direct_file.is_file() and direct_file.stat().st_size > 0:
        ext = direct_file.suffix.lower()
        mime = "image/svg+xml" if ext == ".svg" else ("image/png" if ext == ".png" else ("image/webp" if ext == ".webp" else "image/jpeg"))
        return direct_file.read_bytes(), mime

    # ۰. بررسی اولویت اول: تصویر اختصاصی آپلود شده یا تنظیم شده
    custom_candidates = [
        AVATAR_CACHE_DIR / f"custom_{clean_ident}.svg",
        AVATAR_CACHE_DIR / f"custom_{clean_ident}.jpg",
        AVATAR_CACHE_DIR / f"custom_{clean_ident}.png",
        AVATAR_CACHE_DIR / f"custom_{clean_ident}.webp",
        AVATAR_CACHE_DIR / f"custom_admin_{clean_ident}.svg",
        AVATAR_CACHE_DIR / f"custom_admin_{clean_ident}.jpg",
        AVATAR_CACHE_DIR / f"custom_reseller_{clean_ident}.svg",
        AVATAR_CACHE_DIR / f"custom_reseller_{clean_ident}.jpg",
    ]
    for c_file in custom_candidates:
        if c_file.exists() and c_file.stat().st_size > 0:
            ext = c_file.suffix.lower()
            mime = "image/svg+xml" if ext == ".svg" else ("image/png" if ext == ".png" else ("image/webp" if ext == ".webp" else "image/jpeg"))
            return c_file.read_bytes(), mime

    try:
        # جستجو در جدول اشتراک‌ها
        sub_custom = db.find_subscription_avatar(clean_ident)
        if sub_custom:
            c_f = AVATAR_CACHE_DIR / sub_custom
            if c_f.exists() and c_f.stat().st_size > 0:
                ext = c_f.suffix.lower()
                mime = "image/svg+xml" if ext == ".svg" else ("image/png" if ext == ".png" else "image/jpeg")
                return c_f.read_bytes(), mime
    except Exception:
        pass

    try:
        # جستجو در مشخصات مدیر یا نماینده
        contact_info = db.find_user_contact_info(clean_ident)
        if contact_info:
            u_type = contact_info.get("user_type")
            u_id = contact_info.get("user_id")
            for c_f in [
                AVATAR_CACHE_DIR / f"custom_{u_type}_{u_id}.svg",
                AVATAR_CACHE_DIR / f"custom_{u_type}_{u_id}.jpg",
                AVATAR_CACHE_DIR / f"custom_{u_type}_{u_id}.png"
            ]:
                if c_f.exists() and c_f.stat().st_size > 0:
                    ext = c_f.suffix.lower()
                    mime = "image/svg+xml" if ext == ".svg" else ("image/png" if ext == ".png" else "image/jpeg")
                    return c_f.read_bytes(), mime
    except Exception:
        pass

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
        if cache_file_tg.exists() and (time.time() - cache_file_tg.stat().st_mtime < 86400 * 7):
            return cache_file_tg.read_bytes(), "image/jpeg"

        bot_token = get_bot_token()
        if bot_token:
            try:
                url = f"https://api.telegram.org/bot{bot_token}/getUserProfilePhotos?user_id={target_tg_id}&limit=1"
                with httpx.Client(timeout=2.0) as client:
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
                logger.debug(f"Telegram photo fetch error for {target_tg_id}: {e}")

    # ۳. بررسی یوزرنیم تلگرام
    if raw_ident.startswith("@") or (not clean_ident.isdigit() and len(clean_ident) > 3 and not is_phone):
        cache_file_u = AVATAR_CACHE_DIR / f"user_{clean_ident}.jpg"
        if cache_file_u.exists() and (time.time() - cache_file_u.stat().st_mtime < 86400 * 7):
            return cache_file_u.read_bytes(), "image/jpeg"
        try:
            with httpx.Client(timeout=1.8, follow_redirects=True) as client:
                resp = client.get(f"https://t.me/i/userpic/320/{clean_ident}.jpg")
                if resp.status_code == 200 and len(resp.content) > 500:
                    cache_file_u.write_bytes(resp.content)
                    return resp.content, "image/jpeg"
        except Exception:
            pass

    # ۴. تولید آواتار سه‌بعدی و مدرن به صورت محلی و کاملاً آفلاین
    hash_key = hashlib.md5(clean_ident.encode("utf-8")).hexdigest()[:12]
    cache_file_3d = AVATAR_CACHE_DIR / f"smart3d_{hash_key}.svg"

    if cache_file_3d.exists() and (time.time() - cache_file_3d.stat().st_mtime < 86400 * 30):
        return cache_file_3d.read_bytes(), "image/svg+xml"

    svg_code = avatar_generator.generate_procedural_avatar_svg(clean_ident)
    svg_bytes = svg_code.encode("utf-8")
    try:
        cache_file_3d.write_bytes(svg_bytes)
    except Exception:
        pass

    return svg_bytes, "image/svg+xml"


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


@app.route("/avatar/preset/<preset_id>")
def preset_avatar_img(preset_id: str):
    """نمایش آواتار پریست با موتور محلی و آفلاین بدون نیاز به سایت‌های خارجی"""
    seed = request.args.get("seed", preset_id)
    svg_code = avatar_generator.generate_procedural_avatar_svg(seed, preset_id=preset_id)
    resp = Response(svg_code.encode("utf-8"), mimetype="image/svg+xml")
    resp.headers["Cache-Control"] = "public, max-age=604800"
    return resp


@app.template_filter("avatar_url")
@app.template_global("avatar_url")
def avatar_url_helper(identifier=None):
    """هلپر امن برای تولید آدرس آواتار در تمامی قالب‌ها بدون خطای BuildError"""
    if not identifier:
        identifier = "User"
    return url_for("telegram_avatar", identifier=str(identifier))


@app.template_filter("gateway_name")
@app.template_global("format_gateway_name")
def filter_gateway_name(gateway):
    """تبدیل شناسه انگلیسی درگاه به نام فارسی روان و استاندارد"""
    if not gateway or str(gateway).strip() in ["", "None", "null"]:
        return "کارت به کارت"
    g = str(gateway).strip().lower()
    
    if g in ("cash_admin", "card_admin", "manual_cash", "cash", "c2c_admin") or g.startswith("cash_"):
        return "کارت به کارت (مدیریت)"
    elif g in ("card_reseller", "c2c_reseller") or g.startswith("card_reseller_") or g.startswith("cash_reseller_"):
        return "کارت به کارت (نماینده)"
    elif g == "bundle_reseller" or g.startswith("r_bundle"):
        return "شارژ بسته اعتباری نماینده"
    elif g in ("card_to_card", "card", "kart", "c2c"):
        return "کارت به کارت"
    elif g in ("wallet", "wal", "pwal", "wallet_balance"):
        return "کیف پول هوشمند"
    elif g in ("zarinpal", "zarin_pal") or g.startswith("zarinpal_"):
        return "درگاه آنلاین شاپرک (زرین‌پال)"
    elif g in ("idpay", "id_pay") or g.startswith("idpay_"):
        return "درگاه آنلاین شاپرک (آیدی‌پی)"
    elif g in ("nextpay", "next_pay") or g.startswith("nextpay_"):
        return "درگاه آنلاین شاپرک (نکست‌پی)"
    elif g in ("gateway", "online", "online_gateway", "shaparak") or g.startswith("online_"):
        return "درگاه پرداخت آنلاین شاپرک"
    elif g in ("crypto", "nowpayments", "usdt", "oxapay"):
        return "ارز دیجیتال (تتر / کریپتو)"
    elif g in ("perfect_money", "perfectmoney", "pm"):
        return "پرفکت مانی"
    elif g in ("admin_manual", "manual"):
        return "ثبت دستی مدیریت"
    elif g in ("cashback", "vip_cashback"):
        return "پاداش کش‌بک VIP"
    elif g in ("free", "gift", "trial"):
        return "تست رایگان / هدیه"
    return gateway


@app.template_filter("shamsi_date")
@app.template_global("format_shamsi_date")
def filter_shamsi_date(date_str, fmt="%Y/%m/%d %H:%M"):
    """تبدیل ایمن رشته تاریخ میلادی/ایزو به شمسی زیبا"""
    if not date_str or str(date_str).strip() in ["", "None", "null", "-"]:
        return "-"
    try:
        return gregorian_to_shamsi(str(date_str), fmt=fmt)
    except Exception:
        return str(date_str)[:16].replace("T", " ")


@app.template_filter("gregorian_clean")
@app.template_global("format_gregorian_clean")
def filter_gregorian_clean(date_str, with_seconds=False):
    """پاکسازی و فرمت‌بندی خوانا برای تاریخ میلادی (حذف T و میکروثانیه)"""
    if not date_str or str(date_str).strip() in ["", "None", "null", "-"]:
        return "-"
    try:
        clean = str(date_str).strip().replace("Z", "")
        if "T" in clean:
            clean = clean.split("+")[0]  # حذف آفست تایم‌زون
            dt = datetime.fromisoformat(clean)
            if with_seconds:
                return dt.strftime("%Y-%m-%d %H:%M:%S")
            return dt.strftime("%Y-%m-%d %H:%M")
        return str(date_str)[:19].replace("T", " ")
    except Exception:
        return str(date_str)[:19].replace("T", " ")


@app.template_filter("diff_time")
@app.template_global("format_diff_time")
def filter_diff_time(start_str, end_str):
    """محاسبه و نمایش فاصله زمانی پردازش به فارسی"""
    if not start_str or not end_str:
        return ""
    try:
        clean_start = str(start_str).strip().replace("Z", "").split("+")[0]
        clean_end = str(end_str).strip().replace("Z", "").split("+")[0]
        dt_start = datetime.fromisoformat(clean_start)
        dt_end = datetime.fromisoformat(clean_end)
        diff_sec = max(0, int((dt_end - dt_start).total_seconds()))
        
        if diff_sec < 60:
            return f"{diff_sec} ثانیه"
        elif diff_sec < 3600:
            mins = diff_sec // 60
            return f"{mins} دقیقه"
        elif diff_sec < 86400:
            hrs = diff_sec // 3600
            mins = (diff_sec % 3600) // 60
            if mins > 0:
                return f"{hrs} ساعت و {mins} دقیقه"
            return f"{hrs} ساعت"
        else:
            days = diff_sec // 86400
            hrs = (diff_sec % 86400) // 3600
            if hrs > 0:
                return f"{days} روز و {hrs} ساعت"
            return f"{days} روز"
    except Exception:
        return ""


# ─── مسیرهای مینی‌اپ تلگرام (Telegram WebApp / Mini App Routes) ───

@app.route("/webapp")
@app.route("/webapp/user/<int:telegram_id>")
@app.route("/webapp/sub/<sub_uuid>")
def telegram_webapp(telegram_id=None, sub_uuid=None):
    """رابط کاربری مدرن و واکنش‌گرای مینی‌اپ تلگرام جهت استعلام آنی حجم، زمان و اتصال سریع با Deep Link"""
    tg_id_arg = request.args.get("tg_id") or request.args.get("id")
    if tg_id_arg and str(tg_id_arg).isdigit():
        telegram_id = int(tg_id_arg)

    if sub_uuid:
        sub = db.get_subscription_by_uuid(sub_uuid)
        if sub and sub.get("telegram_id"):
            telegram_id = sub["telegram_id"]

    user = None
    raw_subscriptions = []
    wallet_balance = 0
    expire_shamsi = None

    if telegram_id:
        user = db.get_user(telegram_id)
        raw_subscriptions = db.get_user_subscriptions(telegram_id, status="active")
        if not raw_subscriptions:
            raw_subscriptions = db.get_user_subscriptions(telegram_id)
        wallet_balance = db.get_user_wallet_balance(telegram_id)

    if not user:
        all_users = db.get_all_users()
        user = all_users[0] if all_users else {"telegram_id": 123456789, "username": "کاربر مهمان"}
        raw_subscriptions = db.get_user_subscriptions(user["telegram_id"])
        wallet_balance = db.get_user_wallet_balance(user["telegram_id"])

    panel_url = get_hiddify_url()
    user_proxy = get_user_proxy()
    single_link_template = get_single_link_template(db)

    subscriptions = []
    for s in raw_subscriptions:
        item = enrich_subscription_details(s)
        uuid_val = item.get("hidify_uuid") or ""
        acc_name = item.get("account_name") or "Account"
        item["sub_url"] = f"{panel_url}/{user_proxy}/{uuid_val}/" if uuid_val else ""
        item["single_url"] = format_single_link(single_link_template, uuid_val, acc_name) if (single_link_template and uuid_val) else ""
        subscriptions.append(item)

    if subscriptions:
        first_sub = subscriptions[0]
        exp_date = first_sub.get("expire_date")
        if exp_date:
            try:
                expire_shamsi = gregorian_to_shamsi_full(exp_date)
            except Exception:
                pass

    bot_username = os.getenv("BOT_USERNAME", "hiddify_shop_bot").lstrip("@")
    
    # دریافت دامنه آموزش
    tutorial_domain = db.get_setting("tutorial_domain", "").strip()
    if tutorial_domain:
        if not tutorial_domain.startswith("http://") and not tutorial_domain.startswith("https://"):
            tutorial_url = f"https://{tutorial_domain}"
        else:
            tutorial_url = tutorial_domain
    else:
        tutorial_url = url_for("tutorials_portal")

    return render_template(
        "webapp.html",
        user=user,
        subscriptions=subscriptions,
        wallet_balance=wallet_balance,
        expire_shamsi=expire_shamsi,
        bot_username=bot_username,
        tutorial_url=tutorial_url
    )


@app.route("/api/webapp/user_data")
def api_webapp_user_data():
    """وب‌سرویس JSON برای دریافت اطلاعات مصرف زنده کاربر درون مینی‌اپ"""
    tg_id = request.args.get("tg_id")
    if not tg_id or not tg_id.isdigit():
        return jsonify({"success": False, "error": "شناسه کاربر نامعتبر است."})
    
    telegram_id = int(tg_id)
    user = db.get_user(telegram_id)
    subscriptions = db.get_user_subscriptions(telegram_id)
    wallet_balance = db.get_user_wallet_balance(telegram_id)
    
    return jsonify({
        "success": True,
        "user": user,
        "subscriptions": subscriptions,
        "wallet_balance": wallet_balance
    })


@app.route("/sub/<sub_uuid>", defaults={"sub_path": ""}, strict_slashes=False, methods=["GET"])
@app.route("/sub/<sub_uuid>/<path:sub_path>", strict_slashes=False, methods=["GET"])
def smart_subscription_proxy(sub_uuid: str, sub_path: str = ""):
    """
    دریافت هوشمند اشتراک توسط کلاینت‌ها (Hiddify, Happ, Streisand, v2rayNG, Sing-box و...)
    ثبت بلادرنگ مشخصات واقعی دستگاه، سیستم‌عامل، برنامه کلاینت و IP اینترنت کاربر
    """
    ua = request.headers.get("User-Agent", "")
    client_ip = request.headers.get("CF-Connecting-IP") or request.headers.get("X-Real-IP") or request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip()
    
    # ثبت مشخصات نشست در دیتابیس
    sub = db.get_subscription_by_uuid(sub_uuid)
    if sub:
        db.record_subscription_session(sub["id"], sub_uuid, client_ip, ua, is_active=1)

    # واکشی مستقیم محتوای کانفیگ از سرور هیدیفای
    hiddify_url = get_hiddify_url()
    proxy_path = get_user_proxy()
    target_url = f"{hiddify_url}/{proxy_path}/{sub_uuid}/"
    if sub_path:
        target_url = f"{hiddify_url}/{proxy_path}/{sub_uuid}/{sub_path}"

    try:
        req_headers = {k: v for k, v in request.headers if k.lower() not in ["host", "content-length"]}
        with httpx.Client(verify=False, follow_redirects=True, timeout=10.0) as client:
            resp = client.get(target_url, headers=req_headers)
            excluded_headers = ["content-encoding", "content-length", "transfer-encoding", "connection"]
            resp_headers = [(k, v) for k, v in resp.headers.items() if k.lower() not in excluded_headers]
            return Response(resp.content, status=resp.status_code, headers=resp_headers)
    except Exception as e:
        logger.error(f"Error proxying subscription for {sub_uuid}: {e}")
        return Response("Error fetching subscription configs from server", status=502, mimetype="text/plain")


# ─── هلپرهای ارتباط همگام با تلگرام و هیدیفای (Sync Helpers) ───

def send_telegram_msg(chat_id: int, text: str, reply_markup=None, parse_mode: str = "HTML", bot_token: str = None) -> bool:
    """ارسال پیام تلگرام به صورت همگام از پنل وب با پشتیبانی از ربات اصلی یا ربات اختصاصی نماینده"""
    active_token = bot_token or get_bot_token()
    if not active_token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{active_token}/sendMessage"
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


_last_online_sync_time = 0
_online_sync_lock = threading.Lock()

def sync_hiddify_online_users(force: bool = False):
    """
    همگام‌سازی بلادرنگ وضعیت آنلاین بودن و اطلاعات اشتراک‌ها از API هیدیفای
    دارای محافظ نرخ درخواست و کش هوشمند (حداقل فاصله ۵ ثانیه)
    """
    global _last_online_sync_time
    now = time.time()
    if not force and (now - _last_online_sync_time < 5):
        return

    with _online_sync_lock:
        if not force and (now - _last_online_sync_time < 5):
            return
        _last_online_sync_time = now

    try:
        users = hidify_sync_request("GET", "/admin/user/")
        if isinstance(users, list) and users:
            db.sync_from_hidify(users)
    except Exception as e:
        logger.error(f"Error in sync_hiddify_online_users: {e}")


def enrich_subscription_details(sub: dict) -> dict:
    """
    محاسبه شاخص‌های زنده اشتراک: روزهای مانده، وضعیت شروع، درصد مصرف
    نکته مهم: در هیدیفای زمان تمامی اشتراک‌ها پس از اولین اتصال کاربر محاسبه و آغاز می‌شود.
    """
    item = dict(sub)
    duration = int(item.get("duration") or 30)
    data_limit = float(item.get("data_limit") or 0)
    data_used = float(item.get("data_used") or 0)

    start_date_str = item.get("start_date")
    expire_date_str = item.get("expire_date")

    now_dt = get_now_naive()
    is_started = False
    remaining_days = duration

    if expire_date_str and str(expire_date_str).strip() not in ["None", "null", ""]:
        try:
            clean_exp = str(expire_date_str).strip().replace("Z", "")
            exp_dt = datetime.fromisoformat(clean_exp)
            if exp_dt.tzinfo is not None:
                exp_dt = exp_dt.astimezone(TEHRAN_TZ).replace(tzinfo=None)
            diff_seconds = (exp_dt - now_dt).total_seconds()
            remaining_days = max(0, int(math.ceil(diff_seconds / 86400.0)))
            is_started = True
        except Exception:
            pass
    elif start_date_str and str(start_date_str).strip() not in ["None", "null", ""]:
        try:
            clean_start = str(start_date_str).strip().replace("Z", "")
            start_dt = datetime.fromisoformat(clean_start)
            if start_dt.tzinfo is not None:
                start_dt = start_dt.astimezone(TEHRAN_TZ).replace(tzinfo=None)
            exp_dt = start_dt + timedelta(days=duration)
            diff_seconds = (exp_dt - now_dt).total_seconds()
            remaining_days = max(0, int(math.ceil(diff_seconds / 86400.0)))
            is_started = True
        except Exception:
            pass

    usage_pct = int((data_used / data_limit * 100)) if data_limit > 0 else 0
    remaining_gb = max(0.0, data_limit - data_used) if data_limit > 0 else 0.0

    tg_id = item.get("telegram_id")
    if tg_id:
        try:
            item["is_vip"] = db.is_user_vip(int(tg_id))
        except Exception:
            item["is_vip"] = False
    else:
        item["is_vip"] = False

    item["duration"] = duration
    item["is_started"] = is_started
    item["remaining_days"] = remaining_days
    item["remaining_gb"] = round(remaining_gb, 2)
    item["usage_pct"] = min(100, usage_pct)

    return item


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


ROLE_PERMISSIONS = {
    "super_admin": {"*"},
    "partner": {
        "dashboard", "users", "users_view", "user_manage", "subscriptions", "subscriptions_view", 
        "sub_manage", "create_customer", "plans", "tickets", "payments_view", "reports", 
        "servers_view", "accounting", "accounting_view_self", "profile"
    },
    "finance": {
        "dashboard", "payments", "payments_view", "verify_payments", "discounts", "cards", 
        "accounting", "settle_debts", "reports", "users_view", "profile"
    },
    "support": {
        "dashboard", "tickets", "users_view", "subscriptions_view", "servers_view", "broadcast", "profile"
    },
    "viewer": {
        "dashboard", "reports", "users_view", "subscriptions_view", "servers_view", "payments_view", "profile"
    }
}


def has_permission(perm: str) -> bool:
    """بررسی اعتبارسنجی سطح دسترسی مدیر فعلی بر اساس ماتریس RBAC"""
    if not session.get("logged_in") or session.get("role") != "admin":
        return False
    admin_role = session.get("admin_role", "super_admin")
    allowed_perms = ROLE_PERMISSIONS.get(admin_role, set())
    if "*" in allowed_perms or perm in allowed_perms:
        return True
    perms = session.get("permissions", "")
    if perms == "*" or perm in perms.split(","):
        return True
    return False


def permission_required(perm: str):
    """دکوریتور اعمال دقیق دسترسی‌ها روی روت‌های پنل مدیریت"""
    def decorator(f):
        @functools.wraps(f)
        def decorated_function(*args, **kwargs):
            if not session.get("logged_in") or session.get("role") != "admin":
                flash("دسترسی به این صفحه فقط برای مدیران مجاز است.", "danger")
                return redirect(url_for("login"))
            if not has_permission(perm):
                flash("⛔ دسترسی غیرمجاز: نقش شما مجوز استفاده از این بخش را ندارد.", "danger")
                if has_permission("dashboard"):
                    return redirect(url_for("dashboard"))
                elif has_permission("tickets"):
                    return redirect(url_for("tickets"))
                elif has_permission("payments_view"):
                    return redirect(url_for("payments"))
                return redirect(url_for("admin_profile"))
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def admin_required(f):
    """احراز هویت عمومی مدیر (هر نقشی از مدیران)"""
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("logged_in") or session.get("role") != "admin":
            flash("دسترسی به این صفحه فقط برای مدیران مجاز است.", "danger")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function


def super_admin_required(f):
    """دسترسی انحصاری فقط برای مدیر ارشد (Super Admin)"""
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("logged_in") or session.get("role") != "admin":
            flash("دسترسی به این صفحه فقط برای مدیران مجاز است.", "danger")
            return redirect(url_for("login"))
        if session.get("admin_role") != "super_admin":
            flash("⛔ این عملیات حساس و کلیدی فقط توسط مدیر ارشد (Super Admin) قابل انجام است.", "danger")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return decorated_function


def reseller_required(f):
    """دسترسی اختصاصی نمایندگان و همکاران فروش"""
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


@app.before_request
def check_custom_domain():
    """تشخیص دامنه اختصاصی پنل یا آموزش‌های نماینده از روی هدر Host و بارگذاری هویت بصری اختصاصی"""
    host = request.host
    reseller = db.get_reseller_by_domain(host)
    if reseller:
        g.custom_reseller = reseller
        g.brand_title = reseller.get("brand_title") or reseller.get("name") or "فروشگاه اشتراک"
        g.logo_url = reseller.get("logo_url")
        g.favicon_url = reseller.get("favicon_url")
        g.primary_color = reseller.get("primary_color")
        g.footer_text = reseller.get("footer_text")
        g.support_username = reseller.get("support_username")
        g.bot_username = reseller.get("bot_username")
    else:
        g.custom_reseller = None
        g.brand_title = None
        g.logo_url = None
        g.favicon_url = None
        g.primary_color = None
        g.footer_text = None
        g.support_username = None
        g.bot_username = None


@app.context_processor
def inject_global_branding():
    """تزریق متغیرهای هویت بصری، برندینگ، دامنه اختصاصی و دسترسی‌ها به قالب‌های Jinja"""
    active_reseller_id = session.get("reseller_id")
    branding = {}
    if active_reseller_id:
        r_data = db.get_reseller(active_reseller_id)
        if r_data:
            branding = {
                "brand_title": r_data.get("brand_title") or r_data.get("name") or "پنل نمایندگی",
                "logo_url": r_data.get("logo_url"),
                "favicon_url": r_data.get("favicon_url"),
                "primary_color": r_data.get("primary_color"),
                "footer_text": r_data.get("footer_text"),
                "custom_domain": r_data.get("custom_domain"),
                "tutorial_domain": r_data.get("tutorial_domain"),
                "support_username": r_data.get("support_username"),
                "bot_username": r_data.get("bot_username")
            }
    elif getattr(g, "custom_reseller", None):
        r_data = g.custom_reseller
        branding = {
            "brand_title": r_data.get("brand_title") or r_data.get("name"),
            "logo_url": r_data.get("logo_url"),
            "favicon_url": r_data.get("favicon_url"),
            "primary_color": r_data.get("primary_color"),
            "footer_text": r_data.get("footer_text"),
            "custom_domain": r_data.get("custom_domain"),
            "tutorial_domain": r_data.get("tutorial_domain"),
            "support_username": r_data.get("support_username"),
            "bot_username": r_data.get("bot_username")
        }
    else:
        # تنظیمات برند پیش‌فرض سیستم برای ادمین
        admin_tutorial_title = db.get_setting("tutorial_title", "راهنما و آموزش اتصال")
        admin_tutorial_domain = db.get_setting("tutorial_domain", "")
        branding = {
            "brand_title": admin_tutorial_title,
            "tutorial_domain": admin_tutorial_domain
        }

    return dict(
        has_permission=has_permission,
        branding=branding,
        sub_role=session.get("sub_role")
    )


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

        # ۱. بررسی جدول مدیران سیستم (RBAC & Sub-Admins)
        admin_user = db.authenticate_admin(username, password)
        if admin_user:
            session_token = str(uuid.uuid4())
            reseller_id = admin_user.get("reseller_id")

            if reseller_id:
                # ورود زیرمدیر یا شریک نماینده (Sub-Admin / Partner / Finance / Support)
                reseller_info = db.get_reseller(reseller_id)
                session["logged_in"] = True
                session["role"] = "reseller"
                session["reseller_id"] = reseller_id
                session["sub_role"] = admin_user.get("role", "support")
                session["admin_id"] = admin_user["id"]
                session["username"] = admin_user["username"]
                session["name"] = admin_user.get("display_name") or "همکار"
                session["share_percent"] = admin_user.get("share_percent", 0)
                session["balance"] = reseller_info.get("balance", 0) if reseller_info else 0
                session["discount"] = reseller_info.get("discount_percent", 20) if reseller_info else 20
                session["session_token"] = session_token

                db.record_login_attempt(
                    user_type="reseller_subadmin",
                    user_id=admin_user["id"],
                    username=username,
                    status="success",
                    ip_address=ip,
                    user_agent=ua,
                    browser=browser,
                    device_os=device_os,
                    session_token=session_token
                )
                flash(f"خوش آمدید {session['name']}! ورود به پورتال نمایندگی با موفقیت انجام شد.", "success")
                return redirect(url_for("reseller_dashboard"))

            # مدیر کل سیستم (Super Admin یا ادمین اصلی)
            session["logged_in"] = True
            session["role"] = "admin"
            session["admin_id"] = admin_user["id"]
            session["username"] = admin_user["username"]
            session["name"] = admin_user.get("display_name") or "مدیر"
            session["admin_role"] = admin_user.get("role", "super_admin")
            session["permissions"] = admin_user.get("permissions", "*")
            session["share_percent"] = admin_user.get("share_percent", 0)
            session["debt_balance"] = admin_user.get("debt_balance", 0)
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
# پورتال جامع آموزش‌های چندسکویی و عیب‌یابی هوشمند (Tutorials & Troubleshooting)
# ═══════════════════════════════════════════════════════════════════════

@app.route("/help")
@app.route("/tutorials")
def tutorials_portal():
    """صفحه اصلی پورتال آموزش‌های چندسکویی با انتخاب گرافیکی سیستم‌عامل و جستجو"""
    active_platform = request.args.get("platform", "android").lower()
    if active_platform not in PLATFORMS:
        active_platform = "android"

    # تعیین هویت نماینده در صورت فراخوانی با پارامتر r
    reseller_param = request.args.get("r")
    if reseller_param and not getattr(g, "custom_reseller", None):
        try:
            r_info = db.get_reseller(int(reseller_param))
            if r_info:
                g.custom_reseller = r_info
        except Exception:
            pass

    return render_template(
        "tutorials_portal.html",
        platforms=PLATFORMS,
        tutorials=TUTORIALS,
        troubleshooting=TROUBLESHOOTING_GUIDES,
        active_platform=active_platform
    )


@app.route("/help/<platform>")
@app.route("/tutorials/<platform>")
def tutorials_platform(platform):
    """مشاهده لیست نرم‌افزارها و آموزش‌های یک سیستم‌عامل خاص"""
    platform_key = platform.lower()
    if platform_key not in PLATFORMS:
        flash("سیستم‌عامل انتخاب شده معتبر نمی‌باشد.", "warning")
        return redirect(url_for("tutorials_portal"))

    reseller_param = request.args.get("r")
    if reseller_param and not getattr(g, "custom_reseller", None):
        try:
            r_info = db.get_reseller(int(reseller_param))
            if r_info:
                g.custom_reseller = r_info
        except Exception:
            pass

    return render_template(
        "tutorials_portal.html",
        platforms=PLATFORMS,
        tutorials=TUTORIALS,
        troubleshooting=TROUBLESHOOTING_GUIDES,
        active_platform=platform_key
    )


@app.route("/help/<platform>/<app_slug>")
@app.route("/tutorials/<platform>/<app_slug>")
def tutorial_view(platform, app_slug):
    """صفحه آموزش اختصاصی گام‌به‌گام و تصویری یک نرم‌افزار با دکمه‌های دانلود"""
    app_key = app_slug.lower()
    tutorial = TUTORIALS.get(app_key)
    if not tutorial:
        flash("آموزش نرم‌افزار مورد نظر یافت نشد.", "warning")
        return redirect(url_for("tutorials_portal", platform=platform))

    reseller_param = request.args.get("r")
    if reseller_param and not getattr(g, "custom_reseller", None):
        try:
            r_info = db.get_reseller(int(reseller_param))
            if r_info:
                g.custom_reseller = r_info
        except Exception:
            pass

    platform_info = PLATFORMS.get(tutorial["platform"], {})
    return render_template(
        "tutorial_view.html",
        tutorial=tutorial,
        platform_info=platform_info,
        platforms=PLATFORMS,
        tutorials=TUTORIALS
    )


@app.route("/help/troubleshoot")
@app.route("/tutorials/troubleshoot")
def troubleshoot_wizard():
    """سامانه ویزارد عیب‌یابی هوشمند و راهنمای حل مشکلات اتصال"""
    active_slug = request.args.get("issue")
    active_issue = None
    if active_slug:
        active_issue = next((g for g in TROUBLESHOOTING_GUIDES if g["slug"] == active_slug), None)

    reseller_param = request.args.get("r")
    if reseller_param and not getattr(g, "custom_reseller", None):
        try:
            r_info = db.get_reseller(int(reseller_param))
            if r_info:
                g.custom_reseller = r_info
        except Exception:
            pass

    return render_template(
        "troubleshoot_wizard.html",
        guides=TROUBLESHOOTING_GUIDES,
        active_issue=active_issue
    )


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

    sync_hiddify_online_users()
    server_health = hidify_sync_ping()
    analytics = db.get_advanced_analytics()
    online_stats = db.get_online_users_stats()

    return render_template(
        "dashboard.html",
        total_users=total_users,
        total_subscriptions=total_subscriptions,
        active_subscriptions=active_subscriptions,
        online_users_count=online_stats["online_count"],
        online_stats=online_stats,
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
    """مدیریت کاربران تلگرام با فیلتر VIP"""
    conn = db.get_connection()
    search = request.args.get("search", "").strip()
    filter_vip = request.args.get("vip", "").strip()

    query = """
        SELECT u.*, 
               (SELECT COUNT(*) FROM subscriptions WHERE telegram_id=u.telegram_id) as subs_count
        FROM users u
        WHERE (u.reseller_id IS NULL OR u.reseller_id = 0)
    """
    params = []
    if search:
        query += " AND (u.username LIKE ? OR u.telegram_id LIKE ? OR u.phone_number LIKE ?)"
        params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])
    if filter_vip == "1":
        query += " AND u.is_vip = 1"
    elif filter_vip == "0":
        query += " AND (u.is_vip = 0 OR u.is_vip IS NULL)"

    query += " ORDER BY COALESCE(u.is_vip, 0) DESC, u.created_at DESC"
    if not search and not filter_vip:
        query += " LIMIT 150"

    user_list = conn.execute(query, params).fetchall()
    
    # آمار سریع کاربران
    total_users_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    vip_users_count = conn.execute("SELECT COUNT(*) FROM users WHERE is_vip=1").fetchone()[0]
    conn.close()

    single_link_template = get_single_link_template(db)
    return render_template(
        "users.html",
        users=user_list,
        search=search,
        filter_vip=filter_vip,
        total_count=total_users_count,
        vip_count=vip_users_count,
        panel_url=get_hiddify_url(),
        user_proxy=get_user_proxy(),
        single_link_template=single_link_template
    )


@app.route("/admin/user/<int:telegram_id>/set-vip", methods=["POST"])
@admin_required
def admin_set_user_vip(telegram_id):
    """تنظیم وضعیت پریمیوم / VIP کاربر توسط ادمین کل"""
    action = request.form.get("action", "toggle")
    
    if action == "toggle":
        curr_vip = db.is_user_vip(telegram_id)
        new_vip = not curr_vip
        db.set_user_vip(telegram_id, is_vip=new_vip, vip_type="manual")
        msg = "کاربر با موفقیت به سطح ویژه (⭐️ VIP) ارتقا یافت." if new_vip else "وضعیت ویژه (VIP) کاربر لغو گردید."
        flash(msg, "success")
    elif action == "update":
        is_vip = request.form.get("is_vip") == "1"
        days_str = request.form.get("vip_days", "").strip()
        custom_cb_str = request.form.get("custom_cashback", "").strip()
        
        expire_at = None
        if is_vip and days_str and days_str.isdigit() and int(days_str) > 0:
            expire_at = (datetime.now() + timedelta(days=int(days_str))).isoformat()
            
        custom_cb = int(custom_cb_str) if custom_cb_str and custom_cb_str.isdigit() else None
        
        db.set_user_vip(telegram_id, is_vip=is_vip, vip_type="manual", expire_at=expire_at, custom_cashback=custom_cb)
        flash("تنظیمات کاربری VIP با موفقیت ذخیره شد.", "success")

    next_url = request.form.get("next") or request.referrer or url_for("user_detail", telegram_id=telegram_id)
    return redirect(next_url)


@app.route("/admin/vip-settings", methods=["GET", "POST"])
@app.route("/admin/premium-settings", methods=["GET", "POST"])
@admin_required
def vip_settings():
    """تنظیمات و مدیریت مشتریان پرمیوم و باشگاه مشتریان VIP"""
    if request.method == "POST":
        settings_data = {
            "system_enabled": request.form.get("system_enabled") == "1",
            "auto_enabled": request.form.get("auto_enabled") == "1",
            "auto_threshold": int(request.form.get("auto_threshold") or 1000000),
            "min_purchases": int(request.form.get("min_purchases") or 3),
            "discount_percent": int(request.form.get("discount_percent") or 15),
            "cashback_percent": int(request.form.get("cashback_percent") or 10),
            "bonus_data_gb": int(request.form.get("bonus_data_gb") or 5),
            "extended_grace_hours": int(request.form.get("extended_grace_hours") or 48),
            "priority_support": request.form.get("priority_support") == "1",
            "vip_server_access": request.form.get("vip_server_access") == "1",
            "free_config_regen": request.form.get("free_config_regen") == "1",
            "show_badge": request.form.get("show_badge") == "1"
        }
        db.save_vip_settings(settings_data)
        flash("تنظیمات و مزایای مشتریان پرمیوم با موفقیت ذخیره شد.", "success")
        return redirect(url_for("vip_settings"))

    vip_sets = db.get_vip_settings()
    vip_stats = db.get_vip_dashboard_stats()
    vip_users = db.get_vip_users_list()
    return render_template(
        "vip_settings.html",
        vip_settings=vip_sets,
        vip_stats=vip_stats,
        vip_users=vip_users
    )


@app.route("/admin/vip-user/add", methods=["POST"])
@admin_required
def admin_vip_user_add():
    """افزودن مستقیم کاربر به لیست مشتریان پرمیوم (VIP)"""
    user_input = request.form.get("user_identifier", "").strip()
    days_str = request.form.get("vip_days", "").strip()
    custom_cb_str = request.form.get("custom_cashback", "").strip()

    if not user_input:
        flash("لطفاً آیدی عددی یا نام کاربری کاربر را وارد کنید.", "danger")
        return redirect(url_for("vip_settings"))

    # جستجوی کاربر
    conn = db.get_connection()
    cursor = conn.cursor()
    if user_input.isdigit():
        cursor.execute("SELECT telegram_id, username FROM users WHERE telegram_id = ?", (int(user_input),))
    else:
        clean_uname = user_input.replace("@", "").strip()
        cursor.execute("SELECT telegram_id, username FROM users WHERE username = ? COLLATE NOCASE", (clean_uname,))
    user_row = cursor.fetchone()
    conn.close()

    if not user_row:
        if user_input.isdigit():
            tg_id = int(user_input)
        else:
            flash(f"کاربری با شناسه «{user_input}» در سیستم یافت نشد.", "danger")
            return redirect(url_for("vip_settings"))
    else:
        tg_id = user_row["telegram_id"]

    expire_at = None
    if days_str and days_str.isdigit() and int(days_str) > 0:
        expire_at = (datetime.now() + timedelta(days=int(days_str))).isoformat()

    custom_cb = int(custom_cb_str) if custom_cb_str and custom_cb_str.isdigit() else None

    db.set_user_vip(tg_id, is_vip=True, vip_type="manual", expire_at=expire_at, custom_cashback=custom_cb)
    flash(f"کاربر {tg_id} با موفقیت به لیست مشتریان پرمیوم (VIP) افزوده شد.", "success")
    return redirect(url_for("vip_settings"))


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
    vip_info = db.get_user_vip_info(telegram_id)

    single_link_template = get_single_link_template(db)
    return render_template(
        "user_detail.html",
        telegram_id=telegram_id,
        user=user,
        vip_info=vip_info,
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

    query = "SELECT * FROM transactions WHERE (reseller_id IS NULL OR reseller_id = 0)"
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

    # شمارنده‌های آماری برای تب‌ها (مخصوص ربات اصلی مدیریت)
    pending_count = conn.execute("SELECT COUNT(*) FROM transactions WHERE (is_deleted=0 OR is_deleted IS NULL) AND status='pending' AND (reseller_id IS NULL OR reseller_id = 0)").fetchone()[0]
    approved_count = conn.execute("SELECT COUNT(*) FROM transactions WHERE (is_deleted=0 OR is_deleted IS NULL) AND status IN ('approved', 'completed') AND (reseller_id IS NULL OR reseller_id = 0)").fetchone()[0]
    rejected_count = conn.execute("SELECT COUNT(*) FROM transactions WHERE (is_deleted=0 OR is_deleted IS NULL) AND status='rejected' AND (reseller_id IS NULL OR reseller_id = 0)").fetchone()[0]
    revoked_count = conn.execute("SELECT COUNT(*) FROM transactions WHERE (is_deleted=0 OR is_deleted IS NULL) AND status='revoked' AND (reseller_id IS NULL OR reseller_id = 0)").fetchone()[0]
    deleted_count = conn.execute("SELECT COUNT(*) FROM transactions WHERE is_deleted=1 AND (reseller_id IS NULL OR reseller_id = 0)").fetchone()[0]

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
    tx_row = conn.execute("SELECT * FROM transactions WHERE id=?", (payment_id,)).fetchone()
    conn.close()

    if not tx_row:
        flash("تراکنش یافت نشد.", "danger")
        return redirect(url_for("payments"))

    tx = dict(tx_row)

    if tx.get("status") == "approved":
        flash("این تراکنش قبلاً تایید شده است.", "warning")
        return redirect(url_for("payments"))

    if tx.get("gateway") == "bundle_reseller" or str(tx.get("order_id", "")).startswith("R_BUNDLE"):
        # تایید خرید بسته پیش‌خرید اعتباری نماینده
        r_id = tx.get("reseller_id")
        amount = tx.get("amount", 0)
        pname = tx.get("plan_name", "بسته اعتباری")
        res = db.apply_reseller_bundle_credit(r_id, amount, pname, tx.get("id"))
        db.update_transaction(tx["order_id"], status="approved")
        
        credit_added = res.get("credit_added", amount) if isinstance(res, dict) else amount
        new_balance = res.get("new_balance", 0) if isinstance(res, dict) else 0

        # ۱. ثبت اعلان در پنل نماینده
        if r_id:
            db.add_reseller_notification(
                reseller_id=r_id,
                title="تایید رسید خرید بسته اعتباری",
                message=f"رسید پرداخت شما برای «{pname}» به مبلغ {amount:,} تومان تایید شد و مبلغ {credit_added:,} تومان به کیف پول شما واریز گردید.",
                type="success"
            )

        # ۲. ارسال پیام تلگرام به نماینده
        reseller = db.get_reseller(r_id) if r_id else None
        if reseller and reseller.get("telegram_id"):
            tg_msg = (
                f"✅ <b>فیش واریزی شما تایید شد!</b>\n\n"
                f"📦 <b>عنوان بسته:</b> {pname}\n"
                f"💳 <b>مبلغ پرداختی:</b> {amount:,} تومان\n"
                f"🎁 <b>مبلغ شارژ شده با بونوس:</b> {credit_added:,} تومان\n"
                f"💰 <b>موجودی جدید کیف پول:</b> {new_balance:,} تومان\n"
                f"🆔 <b>کد سفارش:</b> <code>{tx.get('order_id')}</code>"
            )
            try:
                send_telegram_msg(reseller["telegram_id"], tg_msg)
            except Exception as e:
                logger.error(f"Error sending telegram msg to reseller {r_id}: {e}")

        # ۳. لاگ حسابرسی
        admin_id = session.get("admin_id")
        admin_name = session.get("username")
        db.add_transaction_audit_log(
            tx["id"], admin_id, admin_name,
            action="approve_reseller_bundle",
            field_name="status",
            old_value="pending",
            new_value="approved",
            reason=f"تایید شارژ بسته اعتباری نماینده (مبلغ: {amount:,} تومان)"
        )
        
        flash(f"✅ بسته اعتباری نماینده با موفقیت تایید شد و مبلغ {credit_added:,} تومان به کیف پول نماینده افزوده شد.", "success")
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
    admin_name = session.get("name") or session.get("username") or "مدیر ارشد"
    admin_id = session.get("admin_id")
    now_iso = get_now_iso()

    conn = db.get_connection()
    conn.execute(
        "UPDATE transactions SET status='approved', processed_by=?, processed_at=?, updated_at=? WHERE id=?", 
        (admin_name, now_iso, now_iso, payment_id)
    )
    conn.commit()
    conn.close()

    # ثبت لاگ حسابرسی
    db.add_transaction_audit_log(
        transaction_id=payment_id,
        admin_id=admin_id,
        admin_name=admin_name,
        action="approve_payment",
        field_name="status",
        old_value=tx.get("status", "pending"),
        new_value="approved",
        reason=f"تایید فیش پرداخت و صدور اشتراک {plan_name}"
    )

    # پاداش رفرال
    db.complete_referral(user_id)

    # پردازش و واریز کش‌بک کاربران VIP
    try:
        vip_info = db.get_user_vip_info(user_id)
        if vip_info.get("is_vip") and vip_info.get("cashback_percent", 0) > 0:
            paid_amount = int(tx.get("amount") or 0)
            cb_rate = vip_info.get("cashback_percent", 10)
            cashback_val = int((paid_amount * cb_rate) / 100)
            if cashback_val > 0:
                cb_res = db.add_wallet_balance(
                    user_id,
                    cashback_val,
                    f"هدیه کش‌بک خرید ویژه VIP ({cb_rate}%)",
                    ref_id=str(tx.get("order_id") or payment_id),
                    tx_type="cashback"
                )
                new_w_bal = cb_res.get("new_balance", 0)
                cb_msg = (
                    f"🎁 <b>هدیه کش‌بک VIP واریز شد!</b>\n\n"
                    f"💎 به عنوان کاربر ویژه، <b>{cb_rate}٪</b> از مبلغ خرید شما معادل <b>{cashback_val:,} تومان</b> به کیف پول شما بازگشت داده شد.\n"
                    f"💰 <b>موجودی جدید کیف پول:</b> {new_w_bal:,} تومان"
                )
                try:
                    send_telegram_msg(user_id, cb_msg)
                except Exception as e_tg:
                    logger.error(f"Error sending cashback msg to {user_id}: {e_tg}")
    except Exception as e_cb:
        logger.error(f"Error processing VIP cashback for {user_id}: {e_cb}")

    # بررسی ارتقای خودکار کاربر به VIP بر اساس مجموع خریدهای تایید شده
    try:
        upgrade_res = db.check_and_upgrade_user_vip(user_id)
        if upgrade_res.get("upgraded"):
            t_spent = upgrade_res.get("total_spent", 0)
            cb_percent = upgrade_res.get("cashback_percent", 10)
            upgrade_msg = (
                f"🎉 <b>تبریک! شما به کاربر طلایی (⭐️ VIP) ارتقا یافتید!</b>\n\n"
                f"✨ با رسیدن مجموع خریدهای شما به <b>{t_spent:,} تومان</b>، سطح حساب شما ارتقا یافت.\n\n"
                f"👑 <b>مزایای اختصاصی شما:</b>\n"
                f"• 💰 <b>{cb_percent}٪ کش‌بک نقدی</b> در تمام خریدهای بعدی\n"
                f"• 🎧 <b>اولویت اول</b> در صف پاسخگویی تیکت‌های پشتیبانی\n"
                f"• 💎 <b>نشان طلایی VIP</b> در پروفایل ربات\n\n"
                f"از همراهی و اعتماد شما بی‌نهایت سپاسگزاریم! 🌹"
            )
            try:
                send_telegram_msg(user_id, upgrade_msg)
            except Exception as e_ug:
                logger.error(f"Error sending VIP upgrade msg to {user_id}: {e_ug}")
    except Exception as e_up:
        logger.error(f"Error checking VIP auto-upgrade for {user_id}: {e_up}")

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
    """رد فیش پرداخت با ثبت دلیل و ارسال پیام به کاربر/نماینده"""
    reason = request.form.get("reason") or request.args.get("reason") or "عدم تطابق فیش واریزی یا نامعتبر بودن رسید"
    conn = db.get_connection()
    tx_row = conn.execute("SELECT * FROM transactions WHERE id=?", (payment_id,)).fetchone()

    if tx_row:
        tx = dict(tx_row)
        admin_name = session.get("name") or session.get("username") or "مدیر ارشد"
        admin_id = session.get("admin_id")
        now_iso = get_now_iso()

        conn.execute(
            "UPDATE transactions SET status='rejected', rejection_reason=?, processed_by=?, processed_at=?, updated_at=? WHERE id=?", 
            (reason, admin_name, now_iso, now_iso, payment_id)
        )
        conn.commit()

        # ثبت لاگ حسابرسی
        db.add_transaction_audit_log(
            transaction_id=payment_id,
            admin_id=admin_id,
            admin_name=admin_name,
            action="reject_payment",
            field_name="status",
            old_value=tx.get("status", "pending"),
            new_value="rejected",
            reason=reason
        )

        # اگر تراکنش مربوط به نماینده است:
        r_id = tx.get("reseller_id")
        if r_id or tx.get("gateway") == "bundle_reseller":
            # ۱. ثبت اعلان در پنل نماینده
            if r_id:
                db.add_reseller_notification(
                    reseller_id=r_id,
                    title="رد فیش واریزی توسط مدیریت",
                    message=f"فیش واریزی شما برای «{tx.get('plan_name', 'بسته اعتباری')}» به مبلغ {tx.get('amount', 0):,} تومان تایید نشد. علت رد: {reason}",
                    type="danger"
                )

            # ۲. ارسال پیام تلگرام به نماینده
            reseller = db.get_reseller(r_id) if r_id else None
            if reseller and reseller.get("telegram_id"):
                tg_msg = (
                    f"❌ <b>رسید پرداخت شما تایید نشد.</b>\n\n"
                    f"📦 <b>سفارش:</b> {tx.get('plan_name', 'بسته اعتباری')}\n"
                    f"💳 <b>مبلغ:</b> {tx.get('amount', 0):,} تومان\n"
                    f"📝 <b>علت رد:</b> {reason}\n"
                    f"🆔 <b>کد سفارش:</b> <code>{tx.get('order_id')}</code>\n\n"
                    f"در صورت نیاز به راهنمایی با مدیریت در ارتباط باشید."
                )
                try:
                    send_telegram_msg(reseller["telegram_id"], tg_msg)
                except Exception as e:
                    logger.error(f"Error sending telegram reject msg to reseller {r_id}: {e}")
        else:
            # ارسال پیام رد به کاربر عادی
            user_id = tx.get("user_id")
            if user_id:
                msg = f"❌ <b>پرداخت شما تایید نشد.</b>\n\n📝 <b>علت رد:</b> {reason}\n\nدر صورت وجود سوال، با بخش «💬 پشتیبانی» تماس بگیرید."
                try:
                    send_telegram_msg(user_id, msg)
                except Exception as e:
                    logger.error(f"Error sending telegram reject msg to user {user_id}: {e}")

    conn.close()
    flash(f"پرداخت #{payment_id} رد شد و به کاربر/نماینده اطلاع داده شد.", "warning")
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


def get_receipt_placeholder_svg(order_id: str = "", plan_name: str = "", amount: int = 0, tracking_code: str = "") -> str:
    """تولید یک تصویر SVG زیبا و استاندارد برای حالاتی که فایل فیزیکی تصویر فیش در دسترس نیست"""
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="460" height="260" viewBox="0 0 460 260" dir="rtl">
  <defs>
    <linearGradient id="gradBg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" style="stop-color:#1e293b;stop-opacity:1" />
      <stop offset="100%" style="stop-color:#0f172a;stop-opacity:1" />
    </linearGradient>
  </defs>
  <rect width="100%" height="100%" rx="16" fill="url(#gradBg)" stroke="#334155" stroke-width="2"/>
  
  <g transform="translate(230, 60)">
    <circle cx="0" cy="0" r="32" fill="#0284c7" fill-opacity="0.2" stroke="#38bdf8" stroke-width="2"/>
    <path d="M-10 -12 h20 a2 2 0 0 1 2 2 v20 a2 2 0 0 1 -2 2 h-20 a2 2 0 0 1 -2 -2 v-20 a2 2 0 0 1 2 -2 z M-6 -4 h12 M-6 2 h12 M-6 8 h8" stroke="#38bdf8" stroke-width="2.2" stroke-linecap="round" fill="none"/>
  </g>
  
  <text x="230" y="120" fill="#f8fafc" font-size="16" font-weight="bold" font-family="Vazirmatn, Tahoma, sans-serif" text-anchor="middle">رسید پرداخت کارت به کارت</text>
  <text x="230" y="148" fill="#94a3b8" font-size="13" font-family="Vazirmatn, Tahoma, sans-serif" text-anchor="middle">{f'سفارش: {order_id} • {plan_name}' if order_id else 'رسید ثبت‌شده در سامانه'}</text>
  
  <rect x="50" y="165" width="360" height="42" rx="8" fill="#1e293b" stroke="#475569" stroke-width="1"/>
  <text x="230" y="191" fill="#38bdf8" font-size="13" font-weight="bold" font-family="Vazirmatn, Tahoma, sans-serif" text-anchor="middle">{f'کد رهگیری: {tracking_code}' if tracking_code else 'کد پیگیری در مشخصات سفارش ثبت شده است'}</text>
  
  <text x="230" y="235" fill="#64748b" font-size="11" font-family="Vazirmatn, Tahoma, sans-serif" text-anchor="middle">فایل تصویر فیزیکی موجود نیست یا بصورت متنی ثبت شده است</text>
</svg>"""


@app.route("/admin/payment-receipt/<int:payment_id>")
@app.route("/reseller/payment-receipt/<int:payment_id>")
def admin_payment_receipt(payment_id):
    """دانلود و نمایش مستقیم تصویر رسید پرداخت کارت‌به‌کارت با کش محلی پرسرعت (پشتیبانی از ادمین و نماینده)"""
    conn = db.get_connection()
    tx_row = conn.execute("SELECT * FROM transactions WHERE id=?", (payment_id,)).fetchone()
    conn.close()

    if not tx_row:
        return Response(get_receipt_placeholder_svg(f"#{payment_id}", "تراکنش یافت نشد"), mimetype="image/svg+xml")

    tx = dict(tx_row)
    order_id = tx.get("order_id", "")
    plan_name = tx.get("plan_name", "")
    amount = tx.get("amount", 0)
    tracking_code = tx.get("tracking_code", "")

    # ۱. بررسی کش محلی دیسک
    possible_names = []
    if tx.get("receipt_image"):
        possible_names.append(tx["receipt_image"])
        possible_names.append(Path(tx["receipt_image"]).name)
    
    possible_names.extend([
        f"receipt_{payment_id}.jpg", f"receipt_{payment_id}.png", f"receipt_{payment_id}.jpeg", f"receipt_{payment_id}.pdf",
        f"receipt_{order_id}.jpg", f"receipt_{order_id}.png", f"receipt_{order_id}.jpeg", f"receipt_{order_id}.pdf",
        f"{order_id}.jpg", f"{order_id}.png"
    ])

    for fname in possible_names:
        p = RECEIPTS_DIR / fname
        if p.exists() and p.is_file():
            ext = p.suffix.lower()
            mtype = "image/jpeg"
            if ext == ".png":
                mtype = "image/png"
            elif ext == ".pdf":
                mtype = "application/pdf"
            elif ext == ".webp":
                mtype = "image/webp"
            with open(p, "rb") as f:
                content = f.read()
            resp = Response(content, mimetype=mtype)
            resp.headers["Cache-Control"] = "public, max-age=86400"
            return resp

    # ۲. در صورتی که فایل محلی نبود و مقدار receipt_image مانند file_id تلگرام است:
    file_id = tx.get("receipt_image") or tx.get("receipt_photo_id")
    if file_id and not ("." in str(file_id) or "/" in str(file_id) or "\\" in str(file_id)):
        # تعیین توکن ربات
        bot_token = None
        if tx.get("reseller_id"):
            r_info = db.get_reseller(tx["reseller_id"])
            if r_info and r_info.get("bot_token"):
                bot_token = r_info["bot_token"]
        if not bot_token:
            bot_token = get_bot_token()

        if bot_token:
            try:
                get_file_url = f"https://api.telegram.org/bot{bot_token}/getFile?file_id={file_id}"
                with httpx.Client(timeout=8.0) as client:
                    resp = client.get(get_file_url)
                    if resp.status_code == 200:
                        file_info = resp.json()
                        file_path = file_info.get("result", {}).get("file_path")
                        if file_path:
                            download_url = f"https://api.telegram.org/file/bot{bot_token}/{file_path}"
                            dl_resp = client.get(download_url)
                            if dl_resp.status_code == 200:
                                ext = ".png" if file_path.lower().endswith(".png") else (".pdf" if file_path.lower().endswith(".pdf") else ".jpg")
                                content_type = "image/png" if ext == ".png" else ("application/pdf" if ext == ".pdf" else "image/jpeg")
                                save_dest = RECEIPTS_DIR / f"receipt_{payment_id}{ext}"
                                try:
                                    with open(save_dest, "wb") as f:
                                        f.write(dl_resp.content)
                                except Exception:
                                    pass
                                resp = Response(dl_resp.content, mimetype=content_type)
                                resp.headers["Cache-Control"] = "public, max-age=86400"
                                return resp
            except Exception as e:
                logger.warning(f"Failed to fetch receipt from telegram: {e}")

    # ۳. در صورتی که فایل تصویر فیزیکی نبود، بازگرداندن SVG با کیفیت بالا (Status 200)
    svg = get_receipt_placeholder_svg(order_id, plan_name, amount, tracking_code)
    return Response(svg, mimetype="image/svg+xml")


@app.route("/data/receipts/<path:filename>")
def serve_receipt_file(filename):
    """سرو مستقیم فایل‌های رسید از پوشه data/receipts"""
    base_name = Path(filename).name
    p = RECEIPTS_DIR / base_name
    if p.exists() and p.is_file():
        ext = p.suffix.lower()
        mtype = "image/jpeg"
        if ext == ".png":
            mtype = "image/png"
        elif ext == ".pdf":
            mtype = "application/pdf"
        elif ext == ".webp":
            mtype = "image/webp"
        with open(p, "rb") as f:
            return Response(f.read(), mimetype=mtype)
    
    svg = get_receipt_placeholder_svg(base_name)
    return Response(svg, mimetype="image/svg+xml")


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


@app.route("/api/online_status")
def api_online_status():
    """دریافت بلادرنگ وضعیت آنلاین بودن کاربران برای ادمین و نماینده"""
    if not session.get("logged_in"):
        return jsonify({"error": "unauthorized"}), 401
    
    sync_hiddify_online_users()
    
    if session.get("role") == "reseller":
        reseller_id = session.get("reseller_id")
        stats = db.get_online_users_stats(reseller_id=reseller_id)
        online_subs = db.get_online_subscriptions(reseller_id=reseller_id)
    else:
        stats = db.get_online_users_stats()
        online_subs = db.get_online_subscriptions()

    return jsonify({
        "success": True,
        "online_count": stats["online_count"],
        "total_subs": stats["total_subs"],
        "active_subs": stats["active_subs"],
        "online_uuids": [s["hidify_uuid"] for s in online_subs if s.get("hidify_uuid")],
        "online_sub_ids": [s["id"] for s in online_subs]
    })


@app.route("/api/subscription/<int:sub_id>/sessions")
def api_subscription_sessions(sub_id: int):
    """دریافت لیست نشست‌ها، آی‌پی‌ها، سیستم‌عامل و برنامه‌های کلاینت متصل به یک اشتراک"""
    if not session.get("logged_in"):
        return jsonify({"error": "unauthorized"}), 401

    is_admin = (session.get("role") == "admin")
    reseller_id = session.get("reseller_id") if session.get("role") == "reseller" else None

    if reseller_id:
        sub = db.get_reseller_subscription(reseller_id, sub_id)
        if not sub:
            return jsonify({"error": "Subscription not found"}), 404

    sessions_data = db.get_subscription_sessions(sub_id)
    return jsonify(sessions_data)


@app.route("/subscriptions")
@permission_required("subscriptions_view")
def subscriptions():
    """لیست اشتراک‌های هیدیفای همراه با وضعیت آنلاین بودن و اطلاعات استرداد وجه"""
    sync_hiddify_online_users()
    conn = db.get_connection()
    status_filter = request.args.get("status", "all")
    if status_filter == "online":
        sub_list = conn.execute("SELECT * FROM subscriptions WHERE is_online=1 ORDER BY updated_at DESC LIMIT 150").fetchall()
    elif status_filter == "all":
        sub_list = conn.execute("SELECT * FROM subscriptions ORDER BY created_at DESC LIMIT 150").fetchall()
    else:
        sub_list = conn.execute("SELECT * FROM subscriptions WHERE status=? ORDER BY created_at DESC LIMIT 150", (status_filter,)).fetchall()
    conn.close()

    subscriptions_with_refund = []
    for s in sub_list:
        s_dict = enrich_subscription_details(s)
        s_dict["refund_info"] = db.calculate_customer_refund(s["id"])
        subscriptions_with_refund.append(s_dict)
    
    online_stats = db.get_online_users_stats()
    single_link_template = get_single_link_template(db)
    return render_template(
        "subscriptions.html",
        subscriptions=subscriptions_with_refund,
        status_filter=status_filter,
        online_count=online_stats["online_count"],
        online_stats=online_stats,
        panel_url=get_hiddify_url(),
        user_proxy=get_user_proxy(),
        single_link_template=single_link_template
    )


@app.route("/admin/subscription/<int:sub_id>/edit", methods=["POST"])
@permission_required("sub_manage")
def admin_subscription_edit(sub_id):
    """ویرایش مشخصات اشتراک هیدیفای توسط مدیر ارشد و مدیر پشتیبانی با فیلد روزهای اعتبار"""
    conn = db.get_connection()
    sub_row = conn.execute("SELECT * FROM subscriptions WHERE id=?", (sub_id,)).fetchone()
    conn.close()
    if not sub_row:
        flash("اشتراک یافت نشد.", "danger")
        return redirect(url_for("subscriptions"))

    sub = dict(sub_row)
    account_name = request.form.get("account_name", "").strip() or sub["account_name"]
    data_limit = float(request.form.get("data_limit", sub.get("data_limit") or 30))
    duration = int(request.form.get("duration", sub.get("duration") or 30))
    status = request.form.get("status", sub.get("status") or "active")

    # بروزرسانی در سرور هیدیفای
    if sub.get("hidify_uuid"):
        h_update = {
            "name": account_name,
            "usage_limit_GB": data_limit,
            "package_days": duration
        }
        if status == "disabled":
            h_update["enable"] = False
            h_update["is_active"] = False
        elif status == "active":
            h_update["enable"] = True
            h_update["is_active"] = True

        hidify_sync_update_user(sub["hidify_uuid"], **h_update)

    # بروزرسانی در پایگاه‌داده
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE subscriptions 
        SET account_name = ?, data_limit = ?, duration = ?, status = ?, updated_at = ?
        WHERE id = ?
    """, (account_name, data_limit, duration, status, get_now_iso(), sub_id))
    conn.commit()
    conn.close()

    # همگام‌سازی فوری
    sync_hiddify_online_users(force=True)

    flash(f"مشخصات اشتراک «{account_name}» (حجم: {data_limit} گیگابایت | مدت: {duration} روز) با موفقیت ویرایش و در هیدیفای اعمال شد.", "success")
    return redirect(url_for("subscriptions"))


@app.route("/admin/subscription/<int:sub_id>/toggle", methods=["POST"])
@permission_required("sub_manage")
def admin_subscription_toggle(sub_id):
    """فعال یا غیرفعال‌سازی آنی اشتراک هیدیفای توسط مدیر ارشد و پشتیبانی"""
    conn = db.get_connection()
    sub_row = conn.execute("SELECT * FROM subscriptions WHERE id=?", (sub_id,)).fetchone()
    conn.close()
    if not sub_row:
        flash("اشتراک یافت نشد.", "danger")
        return redirect(url_for("subscriptions"))

    sub = dict(sub_row)
    current_status = sub.get("status", "active")
    new_status = "disabled" if current_status == "active" else "active"
    is_enable = (new_status == "active")

    if sub.get("hidify_uuid"):
        hidify_sync_update_user(sub["hidify_uuid"], enable=is_enable, is_active=is_enable)

    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE subscriptions SET status = ?, updated_at = ? WHERE id = ?", (new_status, get_now_iso(), sub_id))
    conn.commit()
    conn.close()

    action_fa = "فعال" if is_enable else "غیرفعال"
    flash(f"اشتراک «{sub.get('account_name')}» با موفقیت {action_fa} شد.", "info")
    return redirect(url_for("subscriptions"))


@app.route("/admin/subscription/<int:sub_id>/delete", methods=["POST"])
@permission_required("sub_delete")
def admin_subscription_delete(sub_id):
    """حذف اشتراک مشتری با محاسبه زمان‌دار و استرداد مستقیم وجه به کیف پول مشتری"""
    admin_role = session.get("admin_role", "support")
    admin_name = session.get("name") or session.get("username") or "مدیر"
    
    # دکمه تعیین استرداد وجه فقط برای مدیر ارشد قابل تغییر است
    if admin_role == "super_admin":
        refund_to_customer = (request.form.get("refund_to_customer") == "on" or request.form.get("refund_to_customer") == "1")
    else:
        # برای مدیر پشتیبانی، استرداد طبق روال پیش‌فرض سیستمی انجام می‌شود
        refund_to_customer = True

    conn = db.get_connection()
    sub_row = conn.execute("SELECT * FROM subscriptions WHERE id=?", (sub_id,)).fetchone()
    conn.close()
    if not sub_row:
        flash("اشتراک یافت نشد.", "danger")
        return redirect(url_for("subscriptions"))

    sub = dict(sub_row)
    uuid_val = sub.get("hidify_uuid")

    # حذف از سرور هیدیفای
    if uuid_val:
        try:
            hidify_sync_delete_user(uuid_val)
        except Exception as ex:
            logger.error(f"Error deleting user {uuid_val} from Hiddify: {ex}")

    # حذف و استرداد مستقیم وجه به مشتری در دیتابیس
    del_res = db.delete_customer_subscription(sub_id, refund_to_customer=refund_to_customer, admin_name=admin_name)
    if del_res.get("success"):
        if del_res.get("refund_done") and del_res.get("refund_amount", 0) > 0:
            # ارسال پیامک یا نوتیف تلگرام به کاربر
            u_id = del_res.get("user_id")
            if u_id:
                try:
                    refund_msg = (
                        f"💰 **استرداد وجه به کیف پول شما**\n\n"
                        f"اشتراک «{del_res['account_name']}» حذف گردید و مبلغ **{del_res['refund_amount']:,} تومان** "
                        f"({del_res['refund_percent']}٪ استرداد - زمان گذشته: {del_res['time_passed_text']}) "
                        f"به موجودی کیف پول شما در ربات افزوده شد."
                    )
                    send_telegram_msg(u_id, refund_msg)
                except Exception:
                    pass
            flash(f"اشتراک «{del_res['account_name']}» حذف شد و مبلغ {del_res['refund_amount']:,} تومان ({del_res['refund_percent']}٪ استرداد) مستقیماً به کیف پول مشتری بازگردانده شد.", "success")
        else:
            flash(f"اشتراک «{del_res['account_name']}» با موفقیت حذف گردید (بدون استرداد وجه خودکار).", "info")
    else:
        flash(f"خطا در حذف اشتراک: {del_res.get('error')}", "danger")

    return redirect(url_for("subscriptions"))


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
        r_dict["bot_status"] = multibot_manager.get_bot_status(r["id"])
        r_dict["payment_history"] = db.get_reseller_full_payment_history(r["id"])
        reseller_list.append(r_dict)

    all_failed_logins = db.get_all_failed_login_logs(limit=50)
    return render_template("resellers.html", resellers=reseller_list, all_failed_logins=all_failed_logins)


@app.route("/admin/reseller/<int:reseller_id>/payments")
@admin_required
def admin_reseller_payments(reseller_id):
    """مشاهده سوابق مالی و جزئیات پرداخت‌های یک نماینده خاص"""
    reseller = db.get_reseller(reseller_id)
    if not reseller:
        flash("نماینده مورد نظر یافت نشد.", "danger")
        return redirect(url_for("admin_resellers"))

    history = db.get_reseller_full_payment_history(reseller_id)
    return render_template(
        "admin_reseller_payments.html",
        reseller=reseller,
        history=history
    )


@app.route("/admin/reseller/<int:reseller_id>/export-payments")
@admin_required
def admin_reseller_export_payments(reseller_id):
    """خروجی فایل اکسل/CSV از سوابق پرداختی نماینده با فرمت UTF-8 BOM"""
    reseller = db.get_reseller(reseller_id)
    if not reseller:
        flash("نماینده مورد نظر یافت نشد.", "danger")
        return redirect(url_for("admin_resellers"))

    history = db.get_reseller_full_payment_history(reseller_id)
    wallet_txs = history.get("wallet_transactions", [])
    receipt_txs = history.get("receipt_transactions", [])

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["گزارش سوابق پرداخت‌ها و تراکنش‌های نماینده:", reseller.get("name"), f"(@{reseller.get('username')})"])
    writer.writerow(["موجودی کیف پول فعلی (تومان):", f"{reseller.get('balance', 0):,}"])
    writer.writerow(["مجموع شارژها (تومان):", f"{history.get('total_deposited', 0):,}"])
    writer.writerow(["مجموع مصرفی خریدها (تومان):", f"{history.get('total_spent', 0):,}"])
    writer.writerow([])
    writer.writerow(["--- تراکنش‌های کیف پول ---"])
    writer.writerow(["شناسه", "نوع تراکنش", "مبلغ (تومان)", "پلن / نام کاربری", "توضیحات", "تاریخ ثبت"])
    for t in wallet_txs:
        ttype = "شارژ کیف پول" if t.get("type") == "deposit" else ("استرداد وجه" if t.get("type") == "refund" else ("تمدید اشتراک" if t.get("type") == "renewal" else "خرید اشتراک"))
        writer.writerow([
            t.get("id"),
            ttype,
            t.get("amount") or 0,
            t.get("plan_name") or t.get("account_name") or "",
            t.get("description") or "",
            t.get("created_at") or ""
        ])

    writer.writerow([])
    writer.writerow(["--- بسته‌ها و فیش‌های ثبت‌شده ---"])
    writer.writerow(["کد سفارش", "عنوان بسته / پلن", "مبلغ (تومان)", "روش پرداخت", "کد پیگیری", "وضعیت", "تاریخ ثبت"])
    for r in receipt_txs:
        status_text = "تایید شده" if r.get("status") in ["approved", "completed"] else ("در انتظار" if r.get("status") == "pending" else "رد شده")
        writer.writerow([
            r.get("order_id"),
            r.get("plan_name") or "",
            r.get("amount") or 0,
            r.get("gateway") or "",
            r.get("tracking_code") or "",
            status_text,
            r.get("created_at") or ""
        ])

    csv_data = "\ufeff" + output.getvalue()
    filename = f"reseller_{reseller_id}_{reseller.get('username')}_payments.csv"
    return Response(
        csv_data.encode("utf-8-sig"),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment;filename={filename}"}
    )


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


@app.route("/admin/reseller/<int:reseller_id>/bot-toggle", methods=["POST"])
@admin_required
def admin_reseller_bot_toggle(reseller_id):
    """تغییر وضعیت ربات اختصاصی نماینده توسط مدیریت کل"""
    bot_info = multibot_manager.get_bot_status(reseller_id)
    if bot_info.get("is_running"):
        multibot_manager.stop_reseller_bot(reseller_id)
        flash(f"ربات نماینده #{reseller_id} با موفقیت متوقف شد.", "info")
    else:
        res = multibot_manager.start_reseller_bot(reseller_id)
        if res.get("success"):
            flash(f"ربات نماینده #{reseller_id} (@{res.get('bot_username')}) با موفقیت راه‌اندازی شد.", "success")
        else:
            flash(f"خطا در راه‌اندازی ربات: {res.get('error')}", "danger")
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
@permission_required("accounting")
def accounting():
    """داشبورد حسابداری و مدیریت مالی، هزینه‌ها، سود خالص، اسناد مالی و تراز بدهی مدیران و شرکا"""
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

    admin_role = session.get("admin_role", "super_admin")
    admin_id = session.get("admin_id")
    target_admin_id = admin_id if admin_role == "partner" else None

    admin_debts_summary = db.get_admins_accounting_summary(admin_id=target_admin_id)
    admin_debts_logs = db.get_admin_debts(admin_id=target_admin_id, limit=100)

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
        search=search,
        admin_debts_summary=admin_debts_summary,
        admin_debts_logs=admin_debts_logs
    )


@app.route("/admin/accounting/settle", methods=["POST"])
@permission_required("settle_debts")
def admin_accounting_settle():
    """ثبت تسویه حساب بدهی مدیر یا شریک تجاری توسط مدیر ارشد یا مالی"""
    admin_id = int(request.form.get("admin_id", 0))
    amount = int(request.form.get("amount", 0))
    description = request.form.get("description", "تسویه حساب نقدی").strip()

    if admin_id <= 0 or amount <= 0:
        flash("شناسه مدیر و مبلغ تسویه باید معتبر باشند.", "warning")
        return redirect(url_for("accounting"))

    settler_id = session.get("admin_id", 1)
    res = db.settle_admin_debt(admin_id, amount, description, settled_by=settler_id)
    if res.get("success"):
        flash(f"تسویه حساب به مبلغ {amount:,} تومان با موفقیت ثبت شد. مانده بدهی فعلی: {res.get('remaining_debt', 0):,} تومان", "success")
    else:
        flash(f"خطا در ثبت تسویه حساب: {res.get('error')}", "danger")

    return redirect(url_for("accounting"))


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
@permission_required("broadcast")
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
@permission_required("tickets")
def tickets():
    """لیست و میز کار تیکت‌های پشتیبانی با تب‌های وضعیت، گفتگوها و آمار"""
    status_filter = request.args.get("status", "all")
    search = request.args.get("search", "").strip()

    ticket_list = db.get_all_tickets(status=status_filter, reseller_id=None, search=search)
    stats = db.get_tickets_stats(reseller_id=None)

    return render_template(
        "tickets.html",
        tickets=ticket_list,
        status_filter=status_filter,
        search=search,
        stats=stats
    )


@app.route("/ticket/reply/<int:ticket_id>", methods=["POST"])
@permission_required("tickets")
def ticket_reply(ticket_id):
    """ارسال پاسخ به تیکت از پنل وب مستقیم به تلگرام کاربر و درج در زنجیره گفتگو"""
    reply_text = request.form.get("reply", "").strip()
    close_ticket = bool(request.form.get("close_ticket"))
    new_status = "closed" if close_ticket else request.form.get("status", "replied")

    if not reply_text:
        flash("متن پاسخ نمی‌تواند خالی باشد.", "danger")
        return redirect(url_for("tickets"))

    ticket = db.get_ticket(ticket_id)
    if ticket:
        sender_name = session.get("username") or session.get("name") or "پشتیبانی"
        db.add_ticket_message(
            ticket_id=ticket_id,
            sender_type="admin",
            message=reply_text,
            sender_id=session.get("admin_id", 0),
            sender_name=sender_name,
            new_status=new_status
        )
        user_id = ticket.get("telegram_id") or ticket.get("user_id")
        msg = f"🔔 <b>پاسخ پشتیبانی به تیکت #{ticket_id}:</b>\n\n{reply_text}\n\n──────────────\nدر صورت نیاز به پیام مجدد از دکمه «💬 پشتیبانی» استفاده فرمایید."
        send_telegram_msg(user_id, msg)
        status_msg = " و تیکت بسته شد" if new_status == "closed" else ""
        flash(f"پاسخ به تیکت #{ticket_id} با موفقیت به تلگرام کاربر ارسال شد{status_msg}!", "success")

    return redirect(url_for("tickets"))


@app.route("/ticket/status/<int:ticket_id>", methods=["POST"])
@permission_required("tickets")
def ticket_status(ticket_id):
    """تغییر سریع وضعیت تیکت (open, in_progress, replied, closed)"""
    new_status = request.form.get("status", "open")
    valid_statuses = {"open": "باز", "in_progress": "در حال بررسی", "replied": "پاسخ‌داده‌شده", "closed": "بسته"}
    if new_status in valid_statuses:
        db.update_ticket_status(ticket_id, new_status)
        flash(f"وضعیت تیکت #{ticket_id} به «{valid_statuses[new_status]}» تغییر یافت.", "info")
    return redirect(url_for("tickets"))


@app.route("/ticket/close/<int:ticket_id>", methods=["POST"])
@permission_required("tickets")
def ticket_close(ticket_id):
    """بستن سریع تیکت توسط ادمین"""
    db.close_ticket(ticket_id)
    flash(f"تیکت #{ticket_id} با موفقیت بسته شد.", "info")
    return redirect(url_for("tickets"))


@app.route("/ticket/reopen/<int:ticket_id>", methods=["POST"])
@permission_required("tickets")
def ticket_reopen(ticket_id):
    """بازگشایی مجدد تیکت توسط ادمین"""
    db.reopen_ticket(ticket_id)
    flash(f"تیکت #{ticket_id} مجدداً بازگشایی شد.", "success")
    return redirect(url_for("tickets"))


# ═══════════════════════════════════════════════════════════════════════
# مدیریت کارت‌های بانکی مقصد (Bank Card Rotator)
# ═══════════════════════════════════════════════════════════════════════

@app.route("/cards", methods=["GET", "POST"])
@permission_required("cards")
def cards():
    """مدیریت جامع روش‌ها، درگاه‌ها و کارت‌های بانکی مقصد"""
    if request.method == "POST":
        action = request.form.get("action", "add_card")
        if action == "add_card":
            card_num = request.form.get("card_number")
            holder = request.form.get("card_holder")
            bank = request.form.get("bank_name")
            limit = int(request.form.get("daily_limit", 50000000))
            db.add_bank_card(card_num, holder, bank, limit)
            flash("کارت بانکی جدید با موفقیت افزوده شد.", "success")
        elif action == "save_online_gateway":
            enabled = bool(request.form.get("online_gateway_enabled"))
            gw_type = request.form.get("online_gateway_type", "zarinpal")
            gw_key = request.form.get("online_gateway_key", "").strip()
            sandbox = bool(request.form.get("online_gateway_sandbox"))
            db.update_admin_gateway(enabled, gw_type, gw_key, sandbox)
            flash("تنظیمات درگاه پرداخت آنلاین با موفقیت ذخیره شد.", "success")
        elif action == "save_crypto_gateway":
            enabled = bool(request.form.get("crypto_gateway_enabled"))
            wallet_address = request.form.get("crypto_wallet_address", "").strip()
            usdt_rate = int(request.form.get("crypto_usdt_rate", 90000))
            CryptoPaymentGateway.save_crypto_config(
                enabled=enabled,
                wallet_address=wallet_address,
                usdt_rate=usdt_rate,
                db_instance=db
            )
            flash("تنظیمات درگاه کریپتو / تتر با موفقیت بروزرسانی شد.", "success")

        return redirect(url_for("cards"))

    cards_list = db.get_all_bank_cards()
    payment_methods = db.get_payment_methods()
    admin_gateway = db.get_admin_gateway()
    crypto_config = CryptoPaymentGateway.get_crypto_config(db)

    return render_template(
        "cards.html",
        cards=cards_list,
        payment_methods=payment_methods,
        admin_gateway=admin_gateway,
        crypto_config=crypto_config
    )


@app.route("/admin/payment_methods/move/<method_id>/<direction>", methods=["GET", "POST"])
@permission_required("cards")
def admin_payment_method_move(method_id, direction):
    """جابجایی عمودی اولویت روش پرداخت برای مدیریت اصلی"""
    db.move_payment_method(method_id, direction)
    flash("اولویت نمایش روش پرداخت در ربات تلگرام با موفقیت تغییر کرد.", "success")
    return redirect(url_for("cards"))


@app.route("/admin/payment_methods/toggle/<method_id>", methods=["GET", "POST"])
@permission_required("cards")
def admin_payment_method_toggle(method_id):
    """فعال یا غیرفعال‌سازی روش پرداخت برای مدیریت اصلی"""
    db.toggle_payment_method(method_id)
    flash("وضعیت فعال بودن روش پرداخت در ربات تلگرام تغییر کرد.", "info")
    return redirect(url_for("cards"))


@app.route("/card/toggle/<int:card_id>")
@permission_required("cards")
def card_toggle(card_id):
    """فعال/غیرفعال کردن کارت"""
    cards_list = db.get_all_bank_cards()
    target = next((c for c in cards_list if c["id"] == card_id), None)
    if target:
        db.toggle_bank_card(card_id, not bool(target["is_active"]))
    return redirect(url_for("cards"))


@app.route("/card/delete/<int:card_id>")
@permission_required("cards")
def card_delete(card_id):
    """حذف کارت"""
    db.delete_bank_card(card_id)
    flash("کارت بانکی حذف شد.", "info")
    return redirect(url_for("cards"))


# ═══════════════════════════════════════════════════════════════════════
# مدیریت و ویرایش کامل پلن‌های فروش
# ═══════════════════════════════════════════════════════════════════════

@app.route("/plans", methods=["GET", "POST"])
@permission_required("plans")
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
@permission_required("plans_manage")
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
@permission_required("plans_manage")
def admin_plan_toggle(plan_id):
    """فعال/غیرفعال کردن پلن"""
    plans = get_all_plans()
    if plan_id in plans:
        current = plans[plan_id].get("is_active", False)
        update_plan(plan_id, is_active=not current)
        flash("وضعیت پلن تغییر یافت.", "info")
    return redirect(url_for("admin_plans_page"))


@app.route("/plans/delete/<plan_id>")
@permission_required("plans_manage")
def admin_plan_delete(plan_id):
    """حذف پلن"""
    res = delete_plan(plan_id)
    if res.get("success"):
        flash("پلن حذف شد.", "warning")
    else:
        flash(f"خطا در حذف پلن: {res.get('error')}", "danger")
    return redirect(url_for("admin_plans_page"))


@app.route("/plans/move-up/<plan_id>")
@permission_required("plans_manage")
def admin_plan_move_up(plan_id):
    """انتقال پلن به بالا در ترتیب عمودی"""
    res = move_plan_up(plan_id)
    if res.get("success"):
        flash("ترتیب پلن با موفقیت به سمت بالا تغییر یافت.", "success")
    else:
        flash(f"خطا: {res.get('error', 'امکان جابجایی وجود ندارد')}", "warning")
    return redirect(url_for("admin_plans_page"))


@app.route("/plans/move-down/<plan_id>")
@permission_required("plans_manage")
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
@permission_required("discounts")
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
@permission_required("discounts")
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
@permission_required("reports")
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
                   WHEN status = 'revoked' THEN 'ابطال‌شده'
                   ELSE status 
               END as status_fa,
               processed_by,
               processed_at,
               created_at 
        FROM transactions 
        ORDER BY created_at DESC
    """).fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "شناسه", "شماره سفارش", "آیدی عددی تلگرام", "نام کاربری", "نام پلن", 
        "مبلغ (تومان)", "روش پرداخت / درگاه", "کد پیگیری / فیش", "وضعیت", 
        "تایید/بررسی‌کننده", "تاریخ ثبت (شمسی)", "تاریخ ثبت (میلادی)", "تاریخ پردازش (شمسی)"
    ])
    for r in rows:
        c_at = r["created_at"] or ""
        p_at = r["processed_at"] or ""
        shamsi_created = filter_shamsi_date(c_at) if c_at else ""
        greg_created = filter_gregorian_clean(c_at) if c_at else ""
        shamsi_proc = filter_shamsi_date(p_at) if p_at else ""
        gw_persian = filter_gateway_name(r["gateway"])

        writer.writerow([
            r["id"],
            r["order_id"] or "",
            r["user_id"] or "",
            r["username"] or "",
            r["plan_name"] or "",
            r["amount"] or 0,
            gw_persian,
            r["tracking_code"] or "",
            r["status_fa"] or "",
            r["processed_by"] or "",
            shamsi_created,
            greg_created,
            shamsi_proc
        ])

    csv_data = "\ufeff" + output.getvalue()
    return Response(
        csv_data.encode("utf-8-sig"),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment;filename=transactions_export.csv"}
    )


@app.route("/admin/logs")
@app.route("/logs")
@permission_required("servers_view")
def admin_logs():
    """مشاهده لاگ‌های زنده سرور"""
    health = hidify_sync_ping()
    return render_template("logs.html", health=health)


@app.route("/settings", methods=["GET", "POST"])
@super_admin_required
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
        elif action == "save_crypto_settings":
            crypto_enabled = "true" if request.form.get("crypto_enabled") == "on" else "false"
            crypto_provider = request.form.get("crypto_provider", "oxapay").strip().lower()
            crypto_api_key = request.form.get("crypto_api_key", "").strip()
            crypto_wallet_address = request.form.get("crypto_wallet_address", "").strip()
            crypto_usdt_rate = request.form.get("crypto_usdt_rate", "90000").strip()

            db.save_setting("crypto_enabled", crypto_enabled)
            db.save_setting("crypto_provider", crypto_provider)
            if crypto_api_key:
                db.save_setting("crypto_api_key", crypto_api_key)
            db.save_setting("crypto_wallet_address", crypto_wallet_address)
            db.save_setting("crypto_usdt_rate", crypto_usdt_rate)

            flash("تنظیمات درگاه پرداخت ارزی و کریپتو با موفقیت ذخیره شد.", "success")
            return redirect(url_for("settings"))
        elif action == "save_tutorial_settings":
            tutorial_domain = request.form.get("tutorial_domain", "").strip().lower()
            tutorial_title = request.form.get("tutorial_title", "").strip()
            db.save_setting("tutorial_domain", tutorial_domain)
            db.save_setting("tutorial_title", tutorial_title)
            flash("تنظیمات دامنه و عنوان پورتال آموزش‌ها با موفقیت ذخیره شد.", "success")
            return redirect(url_for("settings"))
        elif action == "save_online_gateway_settings":
            gw_enabled = request.form.get("online_gateway_enabled") == "on"
            gw_type = request.form.get("online_gateway_type", "zarinpal").strip().lower()
            gw_key = request.form.get("online_gateway_key", "").strip()
            gw_sandbox = request.form.get("online_gateway_sandbox") == "on"

            db.update_admin_gateway(gw_enabled, gw_type, gw_key, gw_sandbox)
            flash("تنظیمات درگاه پرداخت آنلاین شاپرک با موفقیت ذخیره شد.", "success")
            return redirect(url_for("settings"))
        elif action == "save_vip_settings":
            vip_enabled = request.form.get("vip_auto_enabled") == "on"
            vip_threshold = int(request.form.get("vip_auto_threshold", 1000000) or 1000000)
            vip_cashback = int(request.form.get("vip_cashback_percent", 10) or 10)
            db.save_vip_settings(vip_enabled, vip_threshold, vip_cashback)
            flash("تنظیمات باشگاه مشتریان پریمیوم (VIP) و کش‌بک با موفقیت ذخیره شد.", "success")
            return redirect(url_for("settings"))

    conn = db.get_connection()
    settings_list = conn.execute("SELECT * FROM settings").fetchall()
    conn.close()
    single_link_template = get_single_link_template(db)
    sms_config = get_sms_config(db)
    crypto_config = CryptoPaymentGateway.get_crypto_config(db)
    admin_gateway = db.get_admin_gateway()
    tutorial_domain = db.get_setting("tutorial_domain", "")
    tutorial_title = db.get_setting("tutorial_title", "راهنما و آموزش اتصال")
    vip_settings = db.get_vip_settings()
    return render_template(
        "settings.html",
        settings=settings_list,
        single_link_template=single_link_template,
        sms_config=sms_config,
        crypto_config=crypto_config,
        admin_gateway=admin_gateway,
        tutorial_domain=tutorial_domain,
        tutorial_title=tutorial_title,
        vip_settings=vip_settings
    )


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
@super_admin_required
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
@super_admin_required
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
    sync_hiddify_online_users()
    reseller_id = session.get("reseller_id")
    stats = db.get_reseller_stats(reseller_id)
    session["balance"] = stats["balance"]
    recent_transactions = db.get_reseller_transactions(reseller_id, limit=6)
    analytics = db.get_advanced_analytics(reseller_id=reseller_id)
    bot_status = multibot_manager.get_bot_status(reseller_id)
    fin_summary = db.get_reseller_financial_summary(reseller_id)
    return render_template(
        "reseller_dashboard.html",
        stats=stats,
        recent_transactions=recent_transactions,
        analytics=analytics,
        bot_status=bot_status,
        fin_summary=fin_summary
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
        user_limit = int(request.form.get("user_limit", 1))

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

        # ۳. ثبت اشتراک با شناسه نماینده، شماره تلفن، تعداد مجاز کاربر و هزینه پرداخت‌شده در دیتابیس
        conn = db.get_connection()
        conn.execute("""
            INSERT INTO subscriptions 
            (telegram_id, hidify_uuid, plan_id, plan_name, account_name, phone_number, data_limit, duration, status, reseller_id, user_limit, cost_paid, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?)
        """, (
            0, user_uuid, plan_key, plan["name"], account_name, phone_number or None,
            plan["data_limit"], plan["duration"], reseller_id, user_limit, final_price, get_now_iso(), get_now_iso()
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
    """لیست مشتریان نماینده به همراه آمار، وضعیت آنلاین، فیلتر VIP و دسترسی به ویرایش، تمدید و حذف"""
    sync_hiddify_online_users()
    reseller_id = session.get("reseller_id")
    stats = db.get_reseller_stats(reseller_id)
    discount = stats["discount_percent"]
    plans = get_plans_dict()
    status_filter = request.args.get("status", "all")
    
    raw_subs = db.get_reseller_subscriptions(reseller_id)
    subs = []
    for s in raw_subs:
        item = enrich_subscription_details(s)
        if status_filter == "online" and not item.get("is_online"):
            continue
        elif status_filter == "active" and item.get("status") != "active":
            continue
        elif status_filter == "expired" and item.get("status") != "expired":
            continue
        elif status_filter == "vip" and not item.get("is_vip"):
            continue

        refund_calc = db.calculate_reseller_refund(reseller_id, item["id"])
        item["refund_info"] = refund_calc
        subs.append(item)

    single_link_template = get_single_link_template(db)
    return render_template(
        "reseller_users.html",
        subscriptions=subs,
        status_filter=status_filter,
        plans=plans,
        discount=discount,
        stats=stats,
        balance=stats["balance"],
        panel_url=get_hiddify_url(),
        user_proxy=get_user_proxy(),
        single_link_template=single_link_template
    )


@app.route("/reseller/user/<int:telegram_id>/set-vip", methods=["POST"])
@reseller_required
def reseller_set_user_vip(telegram_id):
    """تنظیم وضعیت پریمیوم / VIP مشتری توسط نماینده"""
    reseller_id = session.get("reseller_id")
    user = db.get_user(telegram_id)
    
    # اگر کاربر مستقیم ثبت نشده باشد، بررسی مالکیت اشتراک
    if not user:
        subs = db.get_user_subscriptions(telegram_id)
        if subs and subs[0].get("reseller_id") == reseller_id:
            db.save_user(telegram_id=telegram_id, reseller_id=reseller_id)
            user = db.get_user(telegram_id)
    
    if not user or (user.get("reseller_id") and user.get("reseller_id") != reseller_id):
        flash("کاربر یافت نشد یا متعلق به پنل شما نیست.", "danger")
        return redirect(url_for("reseller_users"))

    action = request.form.get("action", "toggle")
    if action == "toggle":
        curr_vip = db.is_user_vip(telegram_id)
        new_vip = not curr_vip
        db.set_user_vip(telegram_id, is_vip=new_vip, vip_type="manual")
        msg = f"مشتری {telegram_id} با موفقیت به عنوان مشتری ویژه (⭐️ VIP) علامت‌گذاری شد." if new_vip else f"وضعیت VIP مشتری {telegram_id} لغو شد."
        flash(msg, "success")
    elif action == "update":
        is_vip = request.form.get("is_vip") == "1"
        days_str = request.form.get("vip_days", "").strip()
        custom_cb_str = request.form.get("custom_cashback", "").strip()
        expire_at = None
        if is_vip and days_str and days_str.isdigit() and int(days_str) > 0:
            expire_at = (datetime.now() + timedelta(days=int(days_str))).isoformat()
        custom_cb = int(custom_cb_str) if custom_cb_str and custom_cb_str.isdigit() else None
        db.set_user_vip(telegram_id, is_vip=is_vip, vip_type="manual", expire_at=expire_at, custom_cashback=custom_cb)
        flash("تنظیمات VIP مشتری با موفقیت ذخیره گردید.", "success")

    next_url = request.form.get("next") or request.referrer or url_for("reseller_users")
    return redirect(next_url)


@app.route("/reseller/subscription/<int:sub_id>/edit", methods=["POST"])
@reseller_required
def reseller_edit_user(sub_id: int):
    """ویرایش مشخصات و آواتار مشتری نماینده"""
    reseller_id = session.get("reseller_id")
    sub = db.get_reseller_subscription(reseller_id, sub_id)
    if not sub:
        flash("اشتراک مورد نظر یافت نشد.", "danger")
        return redirect(url_for("reseller_users"))

    account_name = request.form.get("account_name", "").strip() or sub["account_name"]
    phone_number = request.form.get("phone_number", "").strip()
    comment = request.form.get("comment", "").strip()
    avatar_preset = request.form.get("avatar_preset", "").strip()

    # ۱. بروزرسانی در دیتابیس محلی
    db.update_reseller_subscription(reseller_id, sub_id, account_name, phone_number, comment)

    # ۲. بروزرسانی یا اعمال آواتار اختصاصی مشتری
    if avatar_preset:
        try:
            svg_code = avatar_generator.generate_procedural_avatar_svg(account_name, preset_id=avatar_preset)
            AVATAR_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            custom_fn = f"custom_{account_name}.svg"
            (AVATAR_CACHE_DIR / custom_fn).write_bytes(svg_code.encode("utf-8"))
            if phone_number:
                (AVATAR_CACHE_DIR / f"custom_{phone_number}.svg").write_bytes(svg_code.encode("utf-8"))
            db.update_subscription_avatar(sub_id, custom_fn)
        except Exception as e:
            logger.error(f"Error setting customer preset avatar: {e}")

    # در صورت آپلود فایل تصویر برای مشتری
    if "avatar_file" in request.files:
        file = request.files["avatar_file"]
        if file and file.filename:
            ext = Path(file.filename).suffix.lower()
            if ext in ALLOWED_AVATAR_EXTENSIONS or ext == ".svg":
                file_bytes = file.read()
                if len(file_bytes) <= 5 * 1024 * 1024:
                    custom_fn = f"custom_{account_name}{ext}"
                    AVATAR_CACHE_DIR.mkdir(parents=True, exist_ok=True)
                    (AVATAR_CACHE_DIR / custom_fn).write_bytes(file_bytes)
                    if phone_number:
                        (AVATAR_CACHE_DIR / f"custom_{phone_number}{ext}").write_bytes(file_bytes)
                    db.update_subscription_avatar(sub_id, custom_fn)

    # ۳. بروزرسانی در هیدیفای
    if sub.get("hidify_uuid"):
        full_comment = f"Reseller #{reseller_id} ({session.get('name')})"
        if phone_number:
            full_comment += f" | Phone: {phone_number}"
        if comment:
            full_comment += f" | {comment}"
        hidify_sync_update_user(sub["hidify_uuid"], name=account_name, comment=full_comment[:200])

    flash(f"مشخصات و آواتار اشتراک «{account_name}» با موفقیت بروزرسانی شد.", "success")
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
    bundles = db.get_reseller_credit_bundles()
    admin_cards = db.get_active_bank_cards()
    admin_gateway = db.get_admin_gateway()
    return render_template(
        "reseller_transactions.html",
        transactions=tx_list,
        stats=stats,
        bundles=bundles,
        admin_cards=admin_cards,
        admin_gateway=admin_gateway
    )


@app.route("/reseller/plans", methods=["GET", "POST"])
@reseller_required
def reseller_plans():
    """مدیریت پلن‌های اختصاصی، نام نمایشی و قیمت‌گذاری برای مشتریان ربات نماینده"""
    reseller_id = session.get("reseller_id")
    reseller = db.get_reseller(reseller_id)
    if not reseller:
        flash("اطلاعات نماینده یافت نشد.", "danger")
        return redirect(url_for("reseller_dashboard"))

    if request.method == "POST":
        action = request.form.get("action")
        plan_id = request.form.get("plan_id")
        if action == "update_override" and plan_id:
            custom_name = request.form.get("custom_name", "").strip()
            custom_price_str = request.form.get("custom_price", "").strip()
            is_active = request.form.get("is_active") in ("on", "1", "true")

            try:
                custom_price = int(custom_price_str) if custom_price_str else None
            except ValueError:
                custom_price = None

            res = db.update_reseller_plan_override(
                reseller_id=reseller_id,
                plan_id=plan_id,
                custom_name=custom_name,
                custom_price=custom_price,
                is_active=is_active
            )
            if res.get("success"):
                flash("تنظیمات پلن با موفقیت ذخیره شد.", "success")
            else:
                flash(f"خطا در ذخیره پلن: {res.get('error')}", "danger")
            return redirect(url_for("reseller_plans"))

        elif action == "reset_override" and plan_id:
            db.reset_reseller_plan_override(reseller_id, plan_id)
            flash("پلن به حالت پیش‌فرض پنل مدیریت بازگردانی شد.", "info")
            return redirect(url_for("reseller_plans"))

    plans = db.get_reseller_plans(reseller_id)
    return render_template("reseller_plans.html", reseller=reseller, plans=plans)


@app.route("/reseller/bundles/submit_receipt", methods=["POST"])
@reseller_required
def reseller_bundles_submit_receipt():
    """ثبت فیش واریز کارت به کارت برای خرید بسته پیش‌خرید اعتباری"""
    reseller_id = session.get("reseller_id")
    bundle_id = request.form.get("bundle_id")
    tracking_code = request.form.get("tracking_code", "").strip()
    notes = request.form.get("notes", "").strip()

    bundles = {b["id"]: b for b in db.get_reseller_credit_bundles()}
    bundle = bundles.get(bundle_id)
    if not bundle:
        flash("بسته اعتباری مورد نظر یافت نشد.", "danger")
        return redirect(url_for("reseller_transactions"))

    import random
    order_id = f"R_BUNDLE_CARD_{reseller_id}_{int(datetime.now().timestamp() * 1000)}_{random.randint(100, 999)}"
    reseller = db.get_reseller(reseller_id) or {}
    username = reseller.get("username", f"reseller_{reseller_id}")

    receipt_file_path = None
    receipt_file = request.files.get("receipt_image")
    if receipt_file and receipt_file.filename:
        from werkzeug.utils import secure_filename
        sec_fn = secure_filename(receipt_file.filename)
        ext = os.path.splitext(sec_fn)[1] or ".jpg"
        fn = f"receipt_{order_id}{ext}"
        RECEIPTS_DIR.mkdir(parents=True, exist_ok=True)
        save_path = RECEIPTS_DIR / fn
        receipt_file.save(save_path)
        receipt_file_path = fn

    db.save_transaction(
        order_id=order_id,
        user_id=reseller.get("telegram_id") or reseller_id,
        username=username,
        plan_name=f"بسته {bundle['title']}",
        amount=bundle["price"],
        gateway="bundle_reseller",
        tracking_code=tracking_code or order_id,
        status="pending",
        receipt_image=receipt_file_path or tracking_code,
        receipt_file_type="web_upload" if receipt_file_path else "tracking_code",
        account_comment=notes,
        notes=notes,
        reseller_id=reseller_id
    )

    flash(f"✅ رسید پرداخت برای «{bundle['title']}» با موفقیت ثبت شد. پس از بررسی و تایید مدیریت، مبلغ {bundle['credit']:,} تومان (با {bundle['badge']}) به کیف پول شما اضافه خواهد شد.", "success")
    return redirect(url_for("reseller_transactions"))


@app.route("/reseller/bundles/online_pay/<bundle_id>")
@reseller_required
def reseller_bundles_online_pay(bundle_id: str):
    """پرداخت آنلاین بسته پیش‌خرید اعتباری نماینده از طریق درگاه مدیریت کل"""
    reseller_id = session.get("reseller_id")
    bundles = {b["id"]: b for b in db.get_reseller_credit_bundles()}
    bundle = bundles.get(bundle_id)
    if not bundle:
        flash("بسته اعتباری مورد نظر یافت نشد.", "danger")
        return redirect(url_for("reseller_transactions"))

    gw_cfg = db.get_admin_gateway()
    if not gw_cfg.get("enabled") or not gw_cfg.get("key"):
        flash("درگاه پرداخت آنلاین مدیریت در حال حاضر غیرفعال است. لطفاً از گزینه کارت به کارت استفاده فرمایید.", "warning")
        return redirect(url_for("reseller_transactions"))

    gw_type = gw_cfg.get("type", "zarinpal")
    gw_key = gw_cfg.get("key", "")
    sandbox = gw_cfg.get("sandbox", False)
    price = bundle["price"]

    order_id = f"R_BUNDLE_ONL_{reseller_id}_{int(datetime.now().timestamp())}"
    domain = db.get_setting("custom_domain") or os.getenv("PANEL_DOMAIN", "http://localhost:5000")
    if not str(domain).startswith("http"):
        domain = f"https://{domain}"
    callback_url = f"{str(domain).rstrip('/')}/payment/callback/{order_id}"

    reseller = db.get_reseller(reseller_id) or {}
    username = reseller.get("username", f"reseller_{reseller_id}")

    pay_url = None
    if gw_type == "zarinpal":
        from payment import ZarinPal
        zp = ZarinPal(merchant_id=gw_key, sandbox=sandbox)
        res = zp.create_payment(amount=price, description=f"خرید بسته اعتباری {bundle['title']}", callback_url=callback_url)
        if res.get("success"):
            pay_url = res.get("payment_url")
    elif gw_type == "idpay":
        from payment import IDPay
        idp = IDPay(api_key=gw_key, sandbox=sandbox)
        res = idp.create_payment(amount=price, name=reseller.get("name") or username, description=f"خرید بسته {bundle['title']}", callback_url=callback_url, order_id=order_id)
        if res.get("success"):
            pay_url = res.get("payment_url")

    if pay_url:
        db.save_transaction(
            order_id=order_id,
            user_id=reseller.get("telegram_id") or reseller_id,
            username=username,
            plan_name=f"بسته {bundle['title']}",
            amount=price,
            gateway=f"{gw_type}_admin",
            tracking_code=order_id,
            status="pending",
            reseller_id=reseller_id
        )
        return redirect(pay_url)
    else:
        flash("خطا در اتصال به درگاه بانکی. لطفاً از پرداخت کارت به کارت استفاده نمایید.", "danger")
        return redirect(url_for("reseller_transactions"))


@app.route("/reseller/reports")
@reseller_required
def reseller_reports():
    """گزارشات و هوش مالی پیشرفته نماینده فروش"""
    reseller_id = session.get("reseller_id")
    stats = db.get_reseller_stats(reseller_id)
    analytics = db.get_advanced_analytics(reseller_id=reseller_id)
    
    fin_summary = db.get_reseller_financial_summary(reseller_id)
    return render_template(
        "reseller_reports.html",
        stats=stats,
        fin_summary=fin_summary,
        popular_plans=analytics.get("popular_plans", []),
        top_users_month=analytics.get("top_users_month", []),
        top_users_year=analytics.get("top_users_year", []),
        most_active_users=analytics.get("most_active_users", []),
        usage_history=analytics.get("usage_history", []),
        timeline_subscriptions=analytics.get("timeline_subscriptions", [])
    )


@app.route("/reseller/payments")
@reseller_required
def reseller_payments():
    """صفحه اختصاصی سوابق پرداخت‌ها، فیش‌های ارسالی و تراکنش‌های نماینده"""
    reseller_id = session.get("reseller_id")
    reseller = db.get_reseller(reseller_id)
    if not reseller:
        flash("اطلاعات نماینده یافت نشد.", "danger")
        return redirect(url_for("reseller_dashboard"))

    history = db.get_reseller_full_payment_history(reseller_id)
    notifications = db.get_reseller_notifications(reseller_id, limit=20)
    unread_count = db.get_reseller_unread_notifications_count(reseller_id)
    
    return render_template(
        "reseller_payments.html",
        reseller=reseller,
        history=history,
        notifications=notifications,
        unread_count=unread_count
    )


@app.route("/reseller/payments/export")
@reseller_required
def reseller_payments_export():
    """خروجی اکسل/CSV کامل پرداخت‌ها و تراکنش‌های نماینده با فرمت UTF-8 BOM"""
    reseller_id = session.get("reseller_id")
    reseller = db.get_reseller(reseller_id)
    if not reseller:
        flash("اطلاعات نماینده یافت نشد.", "danger")
        return redirect(url_for("reseller_payments"))

    history = db.get_reseller_full_payment_history(reseller_id)
    wallet_txs = history.get("wallet_transactions", [])
    receipt_txs = history.get("receipt_transactions", [])

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["گزارش جامع سوابق مالی و پرداخت‌های نماینده:", reseller.get("name"), f"(@{reseller.get('username')})"])
    writer.writerow(["موجودی کیف پول فعلی (تومان):", f"{reseller.get('balance', 0):,}"])
    writer.writerow(["مجموع شارژها و واریزی‌ها (تومان):", f"{history.get('total_deposited', 0):,}"])
    writer.writerow(["مجموع خریدهای اشتراک (تومان):", f"{history.get('total_spent', 0):,}"])
    writer.writerow([])
    writer.writerow(["--- فیش‌ها و بسته‌های ثبت‌شده جهت تایید مدیریت ---"])
    writer.writerow(["کد سفارش", "عنوان بسته / پلن", "مبلغ (تومان)", "روش پرداخت", "کد پیگیری", "وضعیت", "علت رد (در صورت عدم تایید)", "تاریخ ثبت"])
    for r in receipt_txs:
        status_text = "تایید شده" if r.get("status") in ["approved", "completed"] else ("در انتظار بررسی" if r.get("status") == "pending" else "رد شده")
        writer.writerow([
            r.get("order_id"),
            r.get("plan_name") or "",
            r.get("amount") or 0,
            r.get("gateway") or "",
            r.get("tracking_code") or "",
            status_text,
            r.get("rejection_reason") or "",
            r.get("created_at") or ""
        ])

    writer.writerow([])
    writer.writerow(["--- کلیه تراکنش‌های کیف پول ---"])
    writer.writerow(["شناسه", "نوع تراکنش", "مبلغ (تومان)", "پلن / کاربر", "توضیحات", "تاریخ ثبت"])
    for t in wallet_txs:
        ttype = "شارژ کیف پول" if t.get("type") == "deposit" else ("استرداد وجه" if t.get("type") == "refund" else ("تمدید اشتراک" if t.get("type") == "renewal" else "خرید اشتراک"))
        writer.writerow([
            t.get("id"),
            ttype,
            t.get("amount") or 0,
            t.get("plan_name") or t.get("account_name") or "",
            t.get("description") or "",
            t.get("created_at") or ""
        ])

    csv_data = "\ufeff" + output.getvalue()
    filename = f"my_payments_{reseller.get('username')}_{datetime.now().strftime('%Y%m%d')}.csv"
    return Response(
        csv_data.encode("utf-8-sig"),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment;filename={filename}"}
    )


@app.route("/api/reseller/notifications/poll")
@reseller_required
def api_reseller_notifications_poll():
    """پایش بلادرنگ اعلان‌ها و تغییر وضعیت فیش‌های پرداخت برای نماینده"""
    reseller_id = session.get("reseller_id")
    unread_notifs = db.get_reseller_notifications(reseller_id, unread_only=True, limit=10)
    
    # دریافت آخرین فیش‌های اخیر جهت آگاهی از تغییر وضعیت
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, order_id, plan_name, amount, status, rejection_reason, updated_at 
        FROM transactions 
        WHERE reseller_id = ? 
        ORDER BY updated_at DESC LIMIT 5
    """, (reseller_id,))
    recent_txs = [dict(r) for r in cursor.fetchall()]
    conn.close()

    reseller = db.get_reseller(reseller_id) or {}

    return jsonify({
        "success": True,
        "unread_count": len(unread_notifs),
        "notifications": unread_notifs,
        "recent_txs": recent_txs,
        "current_balance": reseller.get("balance", 0)
    })


@app.route("/api/reseller/notifications/mark-read", methods=["POST"])
@reseller_required
def api_reseller_notifications_mark_read():
    """علامت‌گذاری اعلان‌ها به عنوان خوانده‌شده"""
    reseller_id = session.get("reseller_id")
    notif_id = request.json.get("notification_id") if request.is_json else request.form.get("notification_id")
    db.mark_reseller_notifications_read(reseller_id, int(notif_id) if notif_id else None)
    return jsonify({"success": True})


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


@app.route("/reseller/export/users")
@reseller_required
def reseller_export_users():
    """خروجی اکسل/CSV کاربران ثبت‌شده در ربات نماینده با پشتیبانی از فونت فارسی (UTF-8 BOM)"""
    reseller_id = session.get("reseller_id")
    users_list = db.get_reseller_users(reseller_id)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["شناسه عددی تلگرام", "نام کاربری / نام", "تعداد اشتراک‌ها", "تاریخ عضویت"])
    for u in users_list:
        writer.writerow([
            u.get("telegram_id"),
            u.get("username") or "",
            u.get("sub_count") or 0,
            u.get("created_at") or ""
        ])

    csv_data = "\ufeff" + output.getvalue()
    return Response(
        csv_data.encode("utf-8-sig"),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment;filename=reseller_users_export.csv"}
    )


@app.route("/reseller/export/analytics")
@reseller_required
def reseller_export_analytics():
    """خروجی اکسل تراز مالی و سود نماینده"""
    reseller_id = session.get("reseller_id")
    fin_summary = db.get_reseller_financial_summary(reseller_id)
    stats = db.get_reseller_stats(reseller_id)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["شاخص مالی", "مقدار"])
    writer.writerow(["نام نماینده", fin_summary.get("reseller_name")])
    writer.writerow(["موجودی کیف پول فعلی (تومان)", f"{fin_summary.get('current_balance', 0):,}"])
    writer.writerow(["درصد تخفیف همکاری", f"{fin_summary.get('discount_percent', 0)}%"])
    writer.writerow(["مجموع خریدهای عمده از سیستم (تومان)", f"{fin_summary.get('total_wholesale_cost', 0):,}"])
    writer.writerow(["ارزش تخمینی فروش به مشتریان (تومان)", f"{fin_summary.get('estimated_retail_value', 0):,}"])
    writer.writerow(["سود خالص تخمینی نماینده (تومان)", f"{fin_summary.get('estimated_profit', 0):,}"])
    writer.writerow(["تعداد کل کاربران", stats.get("total_users", 0)])
    writer.writerow(["تعداد اشتراک‌های فعال", stats.get("active_users", 0)])

    csv_data = "\ufeff" + output.getvalue()
    return Response(
        csv_data.encode("utf-8-sig"),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment;filename=reseller_financial_report.csv"}
    )


@app.route("/reseller/bot-settings", methods=["GET", "POST"])
@reseller_required
def reseller_bot_settings():
    """تنظیمات و مدیریت ربات تلگرام اختصاصی نماینده (White-Label Multi-Bot)"""
    reseller_id = session.get("reseller_id")
    reseller = db.get_reseller(reseller_id)
    if not reseller:
        flash("اطلاعات نماینده یافت نشد.", "danger")
        return redirect(url_for("reseller_dashboard"))

    if request.method == "POST":
        bot_token = request.form.get("bot_token", "").strip()
        channel_id = request.form.get("channel_id", "").strip()
        brand_name = request.form.get("brand_name", "").strip()
        start_message = request.form.get("start_message", "").strip()
        support_username = request.form.get("support_username", "").strip()
        card_number = request.form.get("card_number", "").strip()
        card_holder = request.form.get("card_holder", "").strip()
        bank_name = request.form.get("bank_name", "").strip()

        # اگر توکن تغییر کرده، اعتبار سنجی می‌شود
        bot_username = reseller.get("bot_username", "")
        if bot_token:
            t_test = ResellerBotInstance.test_token(bot_token)
            if t_test.get("valid"):
                bot_username = t_test.get("username", "")
            else:
                flash(f"هشدار در مورد توکن: {t_test.get('error')}", "warning")

        # تنظیمات باشگاه مشتریان VIP نماینده
        vip_auto_enabled = 1 if request.form.get("vip_auto_enabled") in ("on", "1") else 0
        try:
            vip_auto_threshold = int(request.form.get("vip_auto_threshold", 1000000) or 1000000)
        except Exception:
            vip_auto_threshold = 1000000
        try:
            vip_cashback_percent = int(request.form.get("vip_cashback_percent", 10) or 10)
        except Exception:
            vip_cashback_percent = 10

        db.update_reseller_bot_settings(
            reseller_id,
            bot_token=bot_token,
            bot_username=bot_username,
            channel_id=channel_id,
            brand_name=brand_name,
            start_message=start_message,
            support_username=support_username,
            card_number=card_number,
            card_holder=card_holder,
            bank_name=bank_name,
            vip_auto_enabled=vip_auto_enabled,
            vip_auto_threshold=vip_auto_threshold,
            vip_cashback_percent=vip_cashback_percent
        )

        # تنظیمات درگاه پرداخت آنلاین اختصاصی نماینده
        is_gw_active = request.form.get("is_gateway_active") in ("on", "1")
        gw_type = request.form.get("gateway_type", "zarinpal").strip().lower()
        gw_key = request.form.get("gateway_key", "").strip()
        gw_sandbox = request.form.get("gateway_sandbox") in ("on", "1")
        db.update_reseller_gateway(reseller_id, is_gw_active, gw_type, gw_key, gw_sandbox)

        flash("تنظیمات ربات اختصاصی، باشگاه VIP و درگاه پرداخت با موفقیت ذخیره شد.", "success")
        return redirect(url_for("reseller_bot_settings"))

    bot_status = multibot_manager.get_bot_status(reseller_id)
    reseller_gateway = db.get_reseller_gateway(reseller_id)
    return render_template("reseller_bot_settings.html", reseller=reseller, bot_status=bot_status, reseller_gateway=reseller_gateway)


@app.route("/reseller/bot/test-token", methods=["POST"])
@reseller_required
def reseller_bot_test_token():
    """بررسی و اعتبارسنجی آنلاین توکن ربات نماینده"""
    token = request.form.get("bot_token", "").strip()
    res = ResellerBotInstance.test_token(token)
    return jsonify(res)


@app.route("/reseller/bot/toggle", methods=["POST"])
@reseller_required
def reseller_bot_toggle():
    """روشن یا خاموش کردن ربات توسط نماینده"""
    reseller_id = session.get("reseller_id")
    action = request.form.get("action", "toggle")
    status_info = multibot_manager.get_bot_status(reseller_id)

    if action == "start" or (action == "toggle" and not status_info.get("is_running")):
        res = multibot_manager.start_reseller_bot(reseller_id)
        if res.get("success"):
            flash(f"ربات اختصاصی شما (@{res.get('bot_username')}) با موفقیت فعال و روشن شد!", "success")
        else:
            flash(f"خطا در راه‌اندازی ربات: {res.get('error')}", "danger")
    else:
        res = multibot_manager.stop_reseller_bot(reseller_id)
        flash("ربات اختصاصی شما با موفقیت متوقف شد.", "info")

    return redirect(url_for("reseller_bot_settings"))


# ─── ۱. مدیریت و تایید فیش‌های پرداخت مشتریان در پورتال نماینده (Customer Receipts) ───

@app.route("/reseller/customer-payments")
@reseller_required
def reseller_customer_payments():
    """لیست و تایید فیش‌های واریزی مشتریان ربات نماینده"""
    reseller_id = session.get("reseller_id")
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM transactions 
        WHERE reseller_id = ? AND (gateway != 'bundle_reseller' AND order_id NOT LIKE 'R_BUNDLE%') AND (is_deleted = 0 OR is_deleted IS NULL)
        ORDER BY CASE WHEN status = 'pending' THEN 0 ELSE 1 END, id DESC
    """, (reseller_id,))
    transactions = [dict(r) for r in cursor.fetchall()]
    conn.close()
    
    stats = db.get_reseller_stats(reseller_id)
    return render_template("reseller_customer_payments.html", transactions=transactions, stats=stats)


@app.route("/reseller/payment/<int:payment_id>/approve", methods=["POST"])
@reseller_required
def reseller_payment_approve(payment_id):
    """تایید فیش پرداخت مشتری توسط نماینده در وب، کسر از کیف پول و صدور اشتراک"""
    reseller_id = session.get("reseller_id")
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM transactions WHERE id = ? AND reseller_id = ?", (payment_id, reseller_id))
    tx_row = cursor.fetchone()
    conn.close()

    if not tx_row:
        flash("تراکنش یافت نشد یا متعلق به شما نیست.", "danger")
        return redirect(url_for("reseller_customer_payments"))

    tx = dict(tx_row)
    if tx["status"] == "approved":
        flash("این تراکنش قبلاً تایید شده است.", "warning")
        return redirect(url_for("reseller_customer_payments"))

    user_id = tx["user_id"]
    plan_name = tx["plan_name"]
    plans = get_plans_dict()
    selected_plan = next((p for p in plans.values() if p["name"] == plan_name), None)
    if not selected_plan and plans:
        selected_plan = list(plans.values())[0]

    data_limit = selected_plan["data_limit"] if selected_plan else 30
    duration = selected_plan["duration"] if selected_plan else 30
    original_price = selected_plan["price"] if selected_plan else tx.get("amount", 0)

    # محاسبه هزینه خرید عمده نماینده با تخفیف
    stats = db.get_reseller_stats(reseller_id)
    discount = stats["discount_percent"]
    discount_amount = int((original_price * discount) / 100)
    wholesale_price = original_price - discount_amount

    if stats["balance"] < wholesale_price:
        flash(f"موجودی کیف پول شما کافی نیست! موجودی: {stats['balance']:,} ت | مبلغ کسر: {wholesale_price:,} ت", "danger")
        return redirect(url_for("reseller_payments"))

    account_name = tx.get("account_name") or f"r_{reseller_id}_{user_id}_{int(time.time()) % 10000}"
    user_comment = f"Reseller #{reseller_id} ({session.get('name')}) via Web"

    # ساخت اکانت در هیدیفای
    h_res = hidify_sync_create_user(
        name=account_name,
        usage_limit_gb=data_limit,
        package_days=duration,
        comment=user_comment
    )

    if not h_res.get("success"):
        flash(f"خطا در ایجاد اشتراک در سرور: {h_res.get('error')}", "danger")
        return redirect(url_for("reseller_payments"))

    uuid_val = h_res.get("uuid", "")
    sub_link = h_res.get("subscription_url", "")

    # کسر از کیف پول نماینده
    db.deduct_reseller_balance(reseller_id, wholesale_price, f"خرید اشتراک {plan_name} برای کاربر {user_id}", account_name=account_name, plan_name=plan_name)

    # ثبت اشتراک برای کاربر
    db.save_subscription(
        user_id=user_id,
        plan_name=plan_name,
        data_limit=data_limit,
        data_used=0.0,
        expire_date=(datetime.now() + timedelta(days=duration)).strftime("%Y-%m-%d"),
        hiddify_uuid=uuid_val,
        status="active",
        subscription_url=sub_link,
        reseller_id=reseller_id
    )

    # بروزرسانی وضعیت تراکنش
    reseller_name = session.get("name") or session.get("username") or f"نماینده #{reseller_id}"
    now_iso = get_now_iso()
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE transactions SET status = 'approved', processed_by = ?, processed_at = ?, updated_at = ? WHERE id = ?", 
        (f"{reseller_name} (نماینده #{reseller_id})", now_iso, now_iso, payment_id)
    )
    conn.commit()
    conn.close()

    reseller_data = db.get_reseller(reseller_id)
    bot_tok = reseller_data.get("bot_token") if reseller_data else None
    brand_title = reseller_data.get("brand_name") or "فروشگاه"
    cashback_note = ""

    # پردازش کش‌بک مشتریان VIP نماینده
    try:
        vip_info = db.get_user_vip_info(user_id)
        if vip_info.get("is_vip") and vip_info.get("cashback_percent", 0) > 0:
            paid_amount = int(tx.get("amount") or 0)
            cb_rate = vip_info.get("cashback_percent", 10)
            cashback_val = int((paid_amount * cb_rate) / 100)
            if cashback_val > 0:
                cb_res = db.add_wallet_balance(
                    user_id,
                    cashback_val,
                    f"هدیه کش‌بک خرید VIP ({cb_rate}%) از {brand_title}",
                    ref_id=str(tx.get("order_id") or payment_id),
                    tx_type="cashback"
                )
                new_w_bal = cb_res.get("new_balance", 0)
                cashback_note += f"\n\n🎁 **هدیه کش‌بک VIP:** مبلغ {cashback_val:,} تومان ({cb_rate}٪) به کیف پول شما واریز گردید.\n💰 موجودی کیف پول: {new_w_bal:,} تومان"
    except Exception as e_cb:
        logger.error(f"Error processing reseller VIP cashback for {user_id}: {e_cb}")

    # بررسی ارتقای خودکار به VIP برای مشتری نماینده
    try:
        upgrade_res = db.check_and_upgrade_user_vip(user_id, reseller_id=reseller_id)
        if upgrade_res.get("upgraded"):
            cb_rate = upgrade_res.get("cashback_percent", 10)
            t_spent = upgrade_res.get("total_spent", 0)
            upgrade_extra = f"\n\n🎉 **تبریک! شما به عنوان مشتری ویژه (⭐️ VIP) فروشگاه {brand_title} ارتقا یافتید!**\nبا رسیدن مجموع خریدهای شما به {t_spent:,} تومان، از این پس از {cb_rate}٪ کش‌بک در هر خرید و پشتیبانی در اولویت بهره‌مند خواهید بود. 🌹"
            cashback_note += upgrade_extra
    except Exception as e_ug:
        logger.error(f"Error checking reseller VIP auto upgrade for {user_id}: {e_ug}")

    # ارسال لینک برای کاربر در تلگرام
    msg_to_user = f"🎉 **پرداخت شما تایید شد!**\n\n"
    msg_to_user += f"📦 پلن: **{plan_name}** ({data_limit}GB - {duration} روزه)\n"
    msg_to_user += f"🔗 لینک اشتراک شما:\n`{sub_link}`{cashback_note}\n\n"
    msg_to_user += f"از خرید شما در **{brand_title}** متشکریم!"

    if bot_tok:
        send_telegram_msg(user_id, msg_to_user, bot_token=bot_tok)
    else:
        send_telegram_msg(user_id, msg_to_user)

    flash(f"پرداخت سفارش #{payment_id} با موفقیت تایید و کانفیگ برای مشتری ارسال شد.", "success")
    return redirect(url_for("reseller_customer_payments"))


@app.route("/reseller/payment/<int:payment_id>/reject", methods=["POST"])
@reseller_required
def reseller_payment_reject(payment_id):
    """رد فیش پرداخت مشتری توسط نماینده"""
    reseller_id = session.get("reseller_id")
    reason = request.form.get("reason", "عدم تطابق فیش واریزی یا اطلاعات نامعتبر").strip()

    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM transactions WHERE id = ? AND reseller_id = ?", (payment_id, reseller_id))
    tx_row = cursor.fetchone()
    if not tx_row:
        conn.close()
        flash("تراکنش یافت نشد.", "danger")
        return redirect(url_for("reseller_customer_payments"))

    tx = dict(tx_row)
    reseller_name = session.get("name") or session.get("username") or f"نماینده #{reseller_id}"
    now_iso = get_now_iso()
    cursor.execute(
        "UPDATE transactions SET status = 'rejected', rejection_reason = ?, description = ?, processed_by = ?, processed_at = ?, updated_at = ? WHERE id = ?", 
        (reason, reason, f"{reseller_name} (نماینده #{reseller_id})", now_iso, now_iso, payment_id)
    )
    conn.commit()
    conn.close()

    # اطلاع به کاربر
    reseller_data = db.get_reseller(reseller_id)
    bot_tok = reseller_data.get("bot_token") if reseller_data else None
    msg_to_user = f"❌ **پرداخت سفارش شما تایید نشد.**\n\nعلت: {reason}\nدر صورت داشتن هرگونه سوال با پشتیبانی تماس بگیرید."
    if bot_tok:
        send_telegram_msg(tx["user_id"], msg_to_user, bot_token=bot_tok)
    else:
        send_telegram_msg(tx["user_id"], msg_to_user)

    flash("فیش پرداخت با موفقیت رد شد و به مشتری اطلاع داده شد.", "info")
    return redirect(url_for("reseller_customer_payments"))


# ─── ۲. مدیریت کارت‌های بانکی نماینده (Reseller Cards) ───

@app.route("/reseller/cards", methods=["GET", "POST"])
@reseller_required
def reseller_cards():
    """مدیریت جامع روش‌ها، درگاه‌ها و کارت‌های بانکی مقصد نماینده"""
    reseller_id = session.get("reseller_id")
    if request.method == "POST":
        action = request.form.get("action", "add_card")
        if action == "add_card":
            card_number = request.form.get("card_number", "").strip()
            card_holder = request.form.get("card_holder", "").strip()
            bank_name = request.form.get("bank_name", "").strip()
            daily_limit = int(request.form.get("daily_limit", 50000000))

            if not card_number or not card_holder:
                flash("شماره کارت و نام صاحب حساب الزامی است.", "warning")
            else:
                res = db.add_reseller_card(reseller_id, card_number, card_holder, bank_name, daily_limit)
                if res.get("success"):
                    flash("کارت بانکی جدید با موفقیت اضافه شد.", "success")
                else:
                    flash(f"خطا در ثبت کارت: {res.get('error')}", "danger")
        elif action == "save_reseller_gateway":
            enabled = bool(request.form.get("gateway_enabled"))
            gw_type = request.form.get("gateway_type", "zarinpal")
            gw_key = request.form.get("gateway_key", "").strip()
            sandbox = bool(request.form.get("gateway_sandbox"))
            db.update_reseller_gateway(reseller_id, enabled, gw_type, gw_key, sandbox)
            flash("تنظیمات درگاه آنلاین اختصاصی نماینده با موفقیت ذخیره شد.", "success")

        return redirect(url_for("reseller_cards"))

    cards = db.get_reseller_cards(reseller_id)
    payment_methods = db.get_payment_methods(reseller_id=reseller_id)
    reseller_gateway = db.get_reseller_gateway(reseller_id)

    return render_template(
        "reseller_cards.html",
        cards=cards,
        payment_methods=payment_methods,
        reseller_gateway=reseller_gateway
    )


@app.route("/reseller/payment_methods/move/<method_id>/<direction>", methods=["GET", "POST"])
@reseller_required
def reseller_payment_method_move(method_id, direction):
    """جابجایی عمودی اولویت روش پرداخت برای ربات اختصاصی نماینده"""
    reseller_id = session.get("reseller_id")
    db.move_payment_method(method_id, direction, reseller_id=reseller_id)
    flash("اولویت نمایش روش پرداخت در ربات اختصاصی شما با موفقیت تغییر کرد.", "success")
    return redirect(url_for("reseller_cards"))


@app.route("/reseller/payment_methods/toggle/<method_id>", methods=["GET", "POST"])
@reseller_required
def reseller_payment_method_toggle(method_id):
    """فعال یا غیرفعال‌سازی روش پرداخت در ربات اختصاصی نماینده"""
    reseller_id = session.get("reseller_id")
    db.toggle_payment_method(method_id, reseller_id=reseller_id)
    flash("وضعیت فعال بودن روش پرداخت در ربات اختصاصی شما تغییر کرد.", "info")
    return redirect(url_for("reseller_cards"))


@app.route("/reseller/card/<int:card_id>/toggle", methods=["POST"])
@reseller_required
def reseller_card_toggle(card_id):
    """فعال/غیرفعال‌سازی کارت بانکی"""
    reseller_id = session.get("reseller_id")
    db.toggle_reseller_card(card_id, reseller_id)
    flash("وضعیت کارت بانکی با موفقیت بروزرسانی شد.", "info")
    return redirect(url_for("reseller_cards"))


@app.route("/reseller/card/<int:card_id>/delete", methods=["POST"])
@reseller_required
def reseller_card_delete(card_id):
    """حذف کارت بانکی نماینده"""
    reseller_id = session.get("reseller_id")
    db.delete_reseller_card(card_id, reseller_id)
    flash("کارت بانکی حذف شد.", "info")
    return redirect(url_for("reseller_cards"))


# ─── ۳. سیستم تیکتینگ اختصاصی نماینده (Reseller Tickets) ───

@app.route("/reseller/tickets")
@reseller_required
def reseller_tickets():
    """مشاهده و مدیریت تیکت‌های پشتیبانی مشتریان ربات نماینده با تب‌های وضعیت، گفتگوها و آمار"""
    reseller_id = session.get("reseller_id")
    status_filter = request.args.get("status", "all")
    search = request.args.get("search", "").strip()

    ticket_list = db.get_all_tickets(status=status_filter, reseller_id=reseller_id, search=search)
    stats = db.get_tickets_stats(reseller_id=reseller_id)

    return render_template(
        "reseller_tickets.html",
        tickets=ticket_list,
        status_filter=status_filter,
        search=search,
        stats=stats
    )


@app.route("/reseller/ticket/<int:ticket_id>/reply", methods=["POST"])
@reseller_required
def reseller_ticket_reply(ticket_id):
    """ارسال پاسخ به تیکت مشتری توسط نماینده، درج در زنجیره گفتگو و ارسال در تلگرام"""
    reseller_id = session.get("reseller_id")
    reply_msg = request.form.get("reply_message", "").strip()
    close_after = bool(request.form.get("close_ticket"))
    new_status = "closed" if close_after else request.form.get("status", "replied")

    if not reply_msg:
        flash("متن پاسخ نمی‌تواند خالی باشد.", "warning")
        return redirect(url_for("reseller_tickets"))

    sender_name = session.get("username") or session.get("name") or "پشتیبانی نماینده"
    db.add_ticket_message(
        ticket_id=ticket_id,
        sender_type="reseller",
        message=reply_msg,
        sender_id=reseller_id,
        sender_name=sender_name,
        new_status=new_status
    )

    # ارسال پاسخ در تلگرام برای مشتری با توکن ربات اختصاصی نماینده
    ticket_info = db.get_ticket(ticket_id)
    user_tg = ticket_info.get("telegram_id") or ticket_info.get("user_id") if ticket_info else None
    if ticket_info and user_tg:
        reseller_data = db.get_reseller(reseller_id)
        bot_tok = reseller_data.get("bot_token") if reseller_data else None
        brand = (reseller_data.get("brand_name") if reseller_data else None) or "پشتیبانی"

        notif = f"💬 **پاسخ پشتیبانی {brand} به تیکت #{ticket_id}:**\n\n"
        notif += f"{reply_msg}\n\n"
        notif += "──────────────\nجهت ارسال پاسخ مجدد، پیام خود را با `تیکت: متن پیام` ارسال کنید."

        if bot_tok:
            send_telegram_msg(user_tg, notif, bot_token=bot_tok)
        else:
            send_telegram_msg(user_tg, notif)

    status_msg = " و تیکت بسته شد" if new_status == "closed" else ""
    flash(f"پاسخ تیکت با موفقیت ثبت و برای مشتری در تلگرام ارسال شد{status_msg}.", "success")
    return redirect(url_for("reseller_tickets"))


@app.route("/reseller/ticket/<int:ticket_id>/status", methods=["POST"])
@reseller_required
def reseller_ticket_status(ticket_id):
    """تغییر وضعیت تیکت توسط نماینده"""
    reseller_id = session.get("reseller_id")
    ticket = db.get_ticket(ticket_id)
    if ticket and ticket.get("reseller_id") == reseller_id:
        new_status = request.form.get("status", "open")
        valid_statuses = {"open": "باز", "in_progress": "در حال بررسی", "replied": "پاسخ‌داده‌شده", "closed": "بسته"}
        if new_status in valid_statuses:
            db.update_ticket_status(ticket_id, new_status)
            flash(f"وضعیت تیکت #{ticket_id} به «{valid_statuses[new_status]}» تغییر یافت.", "info")
    return redirect(url_for("reseller_tickets"))


@app.route("/reseller/ticket/<int:ticket_id>/close", methods=["POST"])
@reseller_required
def reseller_ticket_close(ticket_id):
    """بستن سریع تیکت پشتیبانی توسط نماینده"""
    reseller_id = session.get("reseller_id")
    ticket = db.get_ticket(ticket_id)
    if ticket and ticket.get("reseller_id") == reseller_id:
        db.close_ticket(ticket_id)
        flash("تیکت بسته شد.", "info")
    return redirect(url_for("reseller_tickets"))


@app.route("/reseller/ticket/<int:ticket_id>/reopen", methods=["POST"])
@reseller_required
def reseller_ticket_reopen(ticket_id):
    """بازگشایی مجدد تیکت توسط نماینده"""
    reseller_id = session.get("reseller_id")
    ticket = db.get_ticket(ticket_id)
    if ticket and ticket.get("reseller_id") == reseller_id:
        db.reopen_ticket(ticket_id)
        flash("تیکت مجدداً بازگشایی شد.", "success")
    return redirect(url_for("reseller_tickets"))


# ─── ۴. مدیریت کدهای تخفیف اختصاصی نماینده (Reseller Discount Codes) ───

@app.route("/reseller/discounts", methods=["GET", "POST"])
@reseller_required
def reseller_discounts():
    """تعریف و مدیریت کدهای تخفیف نماینده (کسر از سهم سود نماینده)"""
    reseller_id = session.get("reseller_id")
    if request.method == "POST":
        code = request.form.get("code", "").strip()
        discount_percent = int(request.form.get("discount_percent", 0))
        discount_amount = int(request.form.get("discount_amount", 0))
        max_uses = int(request.form.get("max_uses", 0))
        valid_until = request.form.get("valid_until", "").strip() or None

        if not code:
            flash("کد تخفیف الزامی است.", "warning")
        elif discount_percent <= 0 and discount_amount <= 0:
            flash("درصد تخفیف یا مبلغ تخفیف باید تعیین شود.", "warning")
        else:
            res = db.create_reseller_discount_code(reseller_id, code, discount_percent, discount_amount, max_uses, valid_until)
            if res.get("success"):
                flash(f"کد تخفیف «{code.upper()}» با موفقیت ایجاد شد.", "success")
            else:
                flash(f"خطا: {res.get('error')}", "danger")
        return redirect(url_for("reseller_discounts"))

    discounts = db.get_reseller_discount_codes(reseller_id)
    return render_template("reseller_discounts.html", discounts=discounts)


@app.route("/reseller/discount/<int:discount_id>/toggle", methods=["POST"])
@reseller_required
def reseller_discount_toggle(discount_id):
    """فعال/غیرفعال‌سازی کد تخفیف"""
    reseller_id = session.get("reseller_id")
    db.toggle_reseller_discount_code(discount_id, reseller_id)
    flash("وضعیت کد تخفیف بروزرسانی شد.", "info")
    return redirect(url_for("reseller_discounts"))


@app.route("/reseller/discount/<int:discount_id>/delete", methods=["POST"])
@reseller_required
def reseller_discount_delete(discount_id):
    """حذف کد تخفیف"""
    reseller_id = session.get("reseller_id")
    db.delete_reseller_discount_code(discount_id, reseller_id)
    flash("کد تخفیف حذف شد.", "info")
    return redirect(url_for("reseller_discounts"))


# ─── ۵. مدیریت تیم و کارمندان نماینده (Reseller Team & Sub-Admins) ───

@app.route("/reseller/team", methods=["GET", "POST"])
@reseller_required
def reseller_team():
    """مدیریت تیم و کارمندان زیرمجموعه نماینده (شریک، مالی، پشتیبانی)"""
    reseller_id = session.get("reseller_id")
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        display_name = request.form.get("display_name", "").strip()
        role = request.form.get("role", "support").strip()
        phone = request.form.get("phone", "").strip()
        share_percent = int(request.form.get("share_percent", 0))

        if not username or not password or not display_name:
            flash("نام کاربری، رمز عبور و نام نمایشی الزامی هستند.", "warning")
        else:
            res = db.create_reseller_team_member(reseller_id, username, password, display_name, role, phone, share_percent)
            if res.get("success"):
                flash(f"عضو جدید «{display_name}» با نقش {role} افزوده شد.", "success")
            else:
                flash(f"خطا: {res.get('error')}", "danger")
        return redirect(url_for("reseller_team"))

    team_members = db.get_reseller_team_members(reseller_id)
    return render_template("reseller_team.html", team_members=team_members)


@app.route("/reseller/team/<int:member_id>/toggle", methods=["POST"])
@reseller_required
def reseller_team_toggle(member_id):
    """فعال/غیرفعال‌سازی کارمند نماینده"""
    reseller_id = session.get("reseller_id")
    db.toggle_reseller_team_member(member_id, reseller_id)
    flash("وضعیت دسترسی کارمند تغییر یافت.", "info")
    return redirect(url_for("reseller_team"))


@app.route("/reseller/team/<int:member_id>/delete", methods=["POST"])
@reseller_required
def reseller_team_delete(member_id):
    """حذف کارمند نماینده"""
    reseller_id = session.get("reseller_id")
    db.delete_reseller_team_member(member_id, reseller_id)
    flash("کارمند از تیم شما حذف شد.", "info")
    return redirect(url_for("reseller_team"))


# ─── ۶. هویت بصری، لوگو و دامنه اختصاصی نماینده (Branding & Custom Domain) ───

@app.route("/reseller/branding", methods=["GET", "POST"])
@reseller_required
def reseller_branding():
    """تنظیمات هویت بصری، لوگو، رنگ‌بندی، عنوان و دامنه اختصاصی نماینده"""
    reseller_id = session.get("reseller_id")
    reseller = db.get_reseller(reseller_id)

    if request.method == "POST":
        custom_domain = request.form.get("custom_domain", "").strip().lower()
        tutorial_domain = request.form.get("tutorial_domain", "").strip().lower()
        brand_title = request.form.get("brand_title", "").strip()
        logo_url = request.form.get("logo_url", "").strip()
        favicon_url = request.form.get("favicon_url", "").strip()
        primary_color = request.form.get("primary_color", "").strip()
        footer_text = request.form.get("footer_text", "").strip()

        # بررسی آپلود مستقیم لوگو در صورت ارسال فایل
        if "logo_file" in request.files:
            file = request.files["logo_file"]
            if file and file.filename:
                ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else "png"
                fn = f"reseller_{reseller_id}_logo_{int(time.time())}.{ext}"
                fp = AVATAR_CACHE_DIR / fn
                file.save(fp)
                logo_url = url_for("telegram_avatar", identifier=fn)

        if not logo_url and reseller and reseller.get("logo_url"):
            logo_url = reseller["logo_url"]

        res = db.update_reseller_branding(
            reseller_id,
            custom_domain=custom_domain,
            tutorial_domain=tutorial_domain,
            brand_title=brand_title,
            logo_url=logo_url,
            favicon_url=favicon_url,
            primary_color=primary_color,
            footer_text=footer_text
        )
        if res.get("success"):
            flash("تنظیمات هویت بصری، دامنه‌ها و آموزش‌های اختصاصی شما با موفقیت ذخیره شد.", "success")
        else:
            flash(f"خطا در ذخیره‌سازی: {res.get('error')}", "danger")
        return redirect(url_for("reseller_branding"))

    return render_template("reseller_branding.html", reseller=reseller)


# ═══════════════════════════════════════════════════════════════════════
# افزودن و ایجاد دستی مشتری و اشتراک (Create Customer & Partner Cash Sale)
# ═══════════════════════════════════════════════════════════════════════

@app.route("/admin/create_customer", methods=["GET", "POST"])
@permission_required("create_customer")
def admin_create_customer():
    """افزودن و ایجاد دستی مشتری توسط مدیر/شریک همراه با ثبت بدهی نقدی و محاسبه درصد شراکت"""
    plans = get_plans_dict()
    admin_id = session.get("admin_id")
    admin_user = db.get_admin_user(admin_id) if admin_id else None
    admin_role = session.get("admin_role", "super_admin")
    share_percent = admin_user.get("share_percent", 0) if admin_user else 0

    if request.method == "POST":
        account_name = request.form.get("name", "").strip()
        telegram_id_raw = request.form.get("telegram_id", "").strip()
        phone_number = request.form.get("phone", "").strip()
        plan_id = request.form.get("plan_id", "").strip()
        payment_method = request.form.get("payment_method", "cash").strip() # 'cash', 'free', 'wallet'
        comment = request.form.get("comment", "").strip()
        user_limit = int(request.form.get("user_limit", 1))

        if not account_name:
            flash("لطفاً نام یا شناسه مشتری را وارد نمایید.", "warning")
            return redirect(url_for("admin_create_customer"))

        # محاسبه حجم، مدت و قیمت پلن
        selected_plan = plans.get(plan_id)
        if selected_plan:
            plan_name = selected_plan["name"]
            data_limit = float(selected_plan["data_limit"])
            duration = int(selected_plan["duration"])
            price = int(selected_plan["price"])
        else:
            try:
                data_limit = float(request.form.get("custom_data", 30))
                duration = int(request.form.get("custom_duration", 30))
                price = int(request.form.get("custom_price", 0))
                plan_name = f"پلن دستی {data_limit}GB ({duration} روزه)"
            except Exception:
                flash("اطلاعات پلن یا قیمت نامعتبر است.", "danger")
                return redirect(url_for("admin_create_customer"))

        telegram_id = int(telegram_id_raw) if telegram_id_raw.isdigit() else None

        # بررسی موجودی کیف پول در صورت پرداخت از کیف پول
        if payment_method == "wallet" and telegram_id:
            wallet_bal = db.get_user_wallet_balance(telegram_id)
            if wallet_bal < price:
                flash(f"موجودی کیف پول کاربر ({wallet_bal:,} تومان) کمتر از قیمت پلن ({price:,} تومان) است.", "danger")
                return redirect(url_for("admin_create_customer"))
            db.deduct_wallet_balance(telegram_id, price, f"خرید اشتراک {plan_name} توسط مدیریت")

        # ایجاد کاربر در سرور هیدیفای
        h_comment = f"Admin:{session.get('username')}|{telegram_id or ''}"
        h_res = hidify_sync_create_user(name=account_name, usage_limit_gb=data_limit, package_days=duration, comment=h_comment)
        user_uuid = h_res.get("uuid", "")
        if not user_uuid:
            flash(f"خطا در ایجاد اکانت در سرور هیدیفای: {h_res.get('error')}", "danger")
            return redirect(url_for("admin_create_customer"))

        # ذخیره در دیتابیس
        sub_id = db.save_subscription(
            telegram_id=telegram_id or 0,
            hidify_uuid=user_uuid,
            plan_id=plan_id or "custom_admin",
            plan_name=plan_name,
            data_limit=data_limit,
            duration=duration,
            status="active",
            account_name=account_name,
            user_limit=user_limit
        )

        # ثبت کاربر در جدول users
        if telegram_id:
            db.save_user(telegram_id, account_name, None, None, 0, phone_number)
            if phone_number:
                db.set_user_phone(telegram_id, phone_number)

        # ثبت تراکنش و حسابداری بدهی نقدی مدیر
        debt_info_text = ""
        if payment_method == "cash" and price > 0:
            order_id = f"ADM_{get_now_naive().strftime('%Y%m%d%H%M%S')}_{random.randint(100, 999)}"
            db.save_transaction(
                order_id=order_id,
                user_id=telegram_id or 0,
                username=account_name,
                plan_name=plan_name,
                amount=price,
                gateway="cash_admin",
                tracking_code=f"CASH_{session.get('username')}",
                status="approved",
                account_name=account_name
            )

            if admin_role == "super_admin":
                debt_info_text = " (مبلغ نقدی به صندوق اصلی ثبت شد)"
            else:
                debt_res = db.record_admin_cash_sale(
                    admin_id=admin_id or 1,
                    customer_name=account_name,
                    plan_name=plan_name,
                    total_amount=price,
                    share_percent=share_percent,
                    created_by=admin_id,
                    description=f"دریافت نقدی اشتراک {account_name} توسط {session.get('username')}"
                )
                
                if admin_role == "partner" and share_percent > 0:
                    debt_info_text = f" (سهم شراکت شما: {debt_res.get('share_amount', 0):,} تومان | بدهی به مدیریت: {debt_res.get('debt_amount', 0):,} تومان)"
                else:
                    debt_info_text = f" (مبلغ {price:,} تومان به عنوان بدهی نقدی در حساب شما ثبت گردید)"

        # ارسال خودکار کارت اشتراک به تلگرام
        h_url = get_hiddify_url()
        u_proxy = get_user_proxy()
        sub_url = f"{h_url}/{u_proxy}/{user_uuid}/" if user_uuid and h_url else ""
        if telegram_id and sub_url:
            send_subscription_card_sync(
                telegram_id,
                sub_url,
                "🎉 **اشتراک جدید شما آماده شد!**",
                f"📋 پلن: **{plan_name}**\n📊 حجم: **{data_limit} گیگابایت**\n⏰ مدت: **{duration} روز**"
            )

        flash(f"✅ اشتراک «{account_name}» با موفقیت ایجاد شد!{debt_info_text}", "success")
        return render_template("admin_customer_created.html", sub_url=sub_url, account_name=account_name, plan_name=plan_name, data_limit=data_limit, duration=duration, user_uuid=user_uuid, debt_info=debt_info_text)

    return render_template("admin_create_customer.html", plans=plans, admin_role=admin_role, share_percent=share_percent)


# ═══════════════════════════════════════════════════════════════════════
# مدیریت مدیران و سطوح دسترسی (Admin Management & RBAC)
# ═══════════════════════════════════════════════════════════════════════

@app.route("/admin/managers", methods=["GET", "POST"])
@super_admin_required
def admin_managers():
    """لیست و افزودن مدیران با سطوح دسترسی مختلف"""
    if request.method == "POST":
        display_name = request.form.get("display_name", "").strip()
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        role = request.form.get("role", "support").strip()
        share_percent_raw = request.form.get("share_percent", "0").strip()
        share_percent = int(share_percent_raw) if share_percent_raw.isdigit() else 0

        # نقشه‌برداری دسترسی‌ها بر اساس نقش
        perms_map = {
            "super_admin": "*",
            "partner": "dashboard,users,subs,plans,tickets,reports,create_customer,accounting",
            "finance": "dashboard,payments,accounting,cards,reports,create_customer",
            "support": "dashboard,users,subs,tickets,broadcast,create_customer",
            "viewer": "dashboard,users,subs,reports,logs",
        }
        permissions = perms_map.get(role, "*")

        telegram_id_raw = request.form.get("telegram_id", "").strip()
        telegram_id = int(telegram_id_raw) if telegram_id_raw.isdigit() else None
        phone = request.form.get("phone", "").strip()

        if username and password and display_name:
            res = db.create_admin_user(
                username=username,
                password=password,
                display_name=display_name,
                role=role,
                permissions=permissions,
                telegram_id=telegram_id,
                phone=phone,
                share_percent=share_percent
            )
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
@super_admin_required
def admin_manager_edit(admin_id):
    """ویرایش اطلاعات و دسترسی‌های مدیر"""
    display_name = request.form.get("display_name", "").strip()
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()
    role = request.form.get("role", "support").strip()
    share_percent_raw = request.form.get("share_percent", "0").strip()
    share_percent = int(share_percent_raw) if share_percent_raw.isdigit() else 0
    telegram_id_raw = request.form.get("telegram_id", "").strip()
    telegram_id = int(telegram_id_raw) if telegram_id_raw.isdigit() else None
    phone = request.form.get("phone", "").strip()

    perms_map = {
        "super_admin": "*",
        "partner": "dashboard,users,subs,plans,tickets,reports,create_customer,accounting",
        "finance": "dashboard,payments,accounting,cards,reports,create_customer",
        "support": "dashboard,users,subs,tickets,broadcast,create_customer",
        "viewer": "dashboard,users,subs,reports,logs",
    }
    permissions = perms_map.get(role, "*")

    update_kwargs = {
        "display_name": display_name,
        "username": username,
        "role": role,
        "permissions": permissions,
        "telegram_id": telegram_id,
        "phone": phone,
        "share_percent": share_percent,
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
@super_admin_required
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
@super_admin_required
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


# ═══════════════════════════════════════════════════════════════════════
# مسیرهای آپلود و مدیریت آواتار مدیر و نماینده (Profile Avatar Management)
# ═══════════════════════════════════════════════════════════════════════

ALLOWED_AVATAR_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


@app.route("/admin/avatar/upload", methods=["POST"])
@admin_required
def admin_avatar_upload():
    """آپلود و تنظیم تصویر پروفایل اختصاصی برای مدیر"""
    admin_id = session.get("admin_id")
    admin_user = db.get_admin_user(admin_id) if admin_id else None
    username = session.get("username", "admin")
    if admin_user:
        username = admin_user.get("username", username)
        admin_id = admin_user.get("id", admin_id)

    if "avatar_file" not in request.files:
        flash("هیچ فایلی برای آپلود انتخاب نشده است.", "warning")
        return redirect(url_for("admin_profile"))

    file = request.files["avatar_file"]
    if not file or not file.filename:
        flash("لطفاً یک فایل تصویر معتبر انتخاب فرمایید.", "warning")
        return redirect(url_for("admin_profile"))

    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_AVATAR_EXTENSIONS and ext != ".svg":
        flash("فرمت فایل نامعتبر است! فقط فرمت‌های JPG, PNG, WEBP, SVG مجاز هستند.", "danger")
        return redirect(url_for("admin_profile"))

    file_bytes = file.read()
    if len(file_bytes) > 5 * 1024 * 1024:
        flash("حجم فایل نباید بیش از ۵ مگابایت باشد.", "danger")
        return redirect(url_for("admin_profile"))

    AVATAR_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    custom_name = f"custom_admin_{admin_id}{ext}"
    (AVATAR_CACHE_DIR / custom_name).write_bytes(file_bytes)
    (AVATAR_CACHE_DIR / f"custom_{username}{ext}").write_bytes(file_bytes)
    if admin_user and admin_user.get("telegram_id"):
        (AVATAR_CACHE_DIR / f"custom_{admin_user['telegram_id']}{ext}").write_bytes(file_bytes)

    if admin_user:
        db.update_admin_user(admin_id, custom_avatar=custom_name)

    flash("تصویر پروفایل شما با موفقیت بروزرسانی شد.", "success")
    return redirect(url_for("admin_profile"))


@app.route("/admin/avatar/preset", methods=["POST"])
@admin_required
def admin_avatar_preset():
    """انتخاب آواتار از میان کاراکترهای سه‌بعدی جذاب برای مدیر با موتور محلی"""
    admin_id = session.get("admin_id")
    admin_user = db.get_admin_user(admin_id) if admin_id else None
    username = session.get("username", "admin")
    if admin_user:
        username = admin_user.get("username", username)
        admin_id = admin_user.get("id", admin_id)

    seed = request.form.get("seed", f"{username}_{admin_id}")
    style = request.form.get("style", "cyber_bot")

    try:
        svg_code = avatar_generator.generate_procedural_avatar_svg(seed, preset_id=style)
        AVATAR_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        svg_bytes = svg_code.encode("utf-8")
        custom_name = f"custom_admin_{admin_id}.svg"
        (AVATAR_CACHE_DIR / custom_name).write_bytes(svg_bytes)
        (AVATAR_CACHE_DIR / f"custom_{username}.svg").write_bytes(svg_bytes)
        if admin_user and admin_user.get("telegram_id"):
            (AVATAR_CACHE_DIR / f"custom_{admin_user['telegram_id']}.svg").write_bytes(svg_bytes)

        if admin_user:
            db.update_admin_user(admin_id, custom_avatar=custom_name)
        flash("آواتار سه‌بعدی جدید با موفقیت اعمال شد.", "success")
        return redirect(url_for("admin_profile"))
    except Exception as e:
        logger.error(f"Error setting preset avatar: {e}")
        flash(f"خطا در اعمال آواتار: {e}", "danger")
        return redirect(url_for("admin_profile"))


@app.route("/admin/avatar/delete", methods=["POST"])
@admin_required
def admin_avatar_delete():
    """حذف تصویر سفارشی و بازگشت به آواتار هوشمند پیش‌فرض مدیر"""
    admin_id = session.get("admin_id")
    admin_user = db.get_admin_user(admin_id) if admin_id else None
    username = session.get("username", "admin")
    if admin_user:
        username = admin_user.get("username", username)
        admin_id = admin_user.get("id", admin_id)

    tg_id = admin_user.get("telegram_id") if admin_user else None
    for fn in [
        f"custom_admin_{admin_id}.svg", f"custom_admin_{admin_id}.jpg", f"custom_admin_{admin_id}.png",
        f"custom_{username}.svg", f"custom_{username}.jpg", f"custom_{username}.png",
        f"custom_{tg_id}.svg" if tg_id else None, f"custom_{tg_id}.jpg" if tg_id else None
    ]:
        if fn:
            p = AVATAR_CACHE_DIR / fn
            if p.exists():
                try:
                    p.unlink()
                except Exception:
                    pass

    if admin_user:
        db.update_admin_user(admin_id, custom_avatar="")

    flash("تصویر اختصاصی حذف شد و به حالت پیش‌فرض بازگشت.", "info")
    return redirect(url_for("admin_profile"))


@app.route("/reseller/avatar/upload", methods=["POST"])
@reseller_required
def reseller_avatar_upload():
    """آپلود و تنظیم تصویر پروفایل اختصاصی برای نماینده"""
    reseller_id = session.get("reseller_id")
    reseller = db.get_reseller(reseller_id)
    if not reseller:
        flash("نماینده یافت نشد!", "danger")
        return redirect(url_for("reseller_dashboard"))

    username = reseller.get("username", f"reseller_{reseller_id}")

    if "avatar_file" not in request.files:
        flash("هیچ فایلی برای آپلود انتخاب نشده است.", "warning")
        return redirect(url_for("reseller_profile"))

    file = request.files["avatar_file"]
    if not file or not file.filename:
        flash("لطفاً یک فایل تصویر انتخاب فرمایید.", "warning")
        return redirect(url_for("reseller_profile"))

    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_AVATAR_EXTENSIONS and ext != ".svg":
        flash("فرمت فایل نامعتبر است! فقط JPG, PNG, WEBP, SVG مجاز هستند.", "danger")
        return redirect(url_for("reseller_profile"))

    file_bytes = file.read()
    if len(file_bytes) > 5 * 1024 * 1024:
        flash("حجم فایل نباید بیش از ۵ مگابایت باشد.", "danger")
        return redirect(url_for("reseller_profile"))

    AVATAR_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    custom_name = f"custom_reseller_{reseller_id}{ext}"
    (AVATAR_CACHE_DIR / custom_name).write_bytes(file_bytes)
    (AVATAR_CACHE_DIR / f"custom_{username}{ext}").write_bytes(file_bytes)
    if reseller and reseller.get("telegram_id"):
        (AVATAR_CACHE_DIR / f"custom_{reseller['telegram_id']}{ext}").write_bytes(file_bytes)

    db.update_reseller_profile(reseller_id, custom_avatar=custom_name)

    flash("تصویر پروفایل شما با موفقیت بروزرسانی شد.", "success")
    return redirect(url_for("reseller_profile"))


@app.route("/reseller/avatar/preset", methods=["POST"])
@reseller_required
def reseller_avatar_preset():
    """انتخاب آواتار از میان کاراکترهای سه‌بعدی برای نماینده با موتور محلی"""
    reseller_id = session.get("reseller_id")
    reseller = db.get_reseller(reseller_id)
    if not reseller:
        flash("نماینده یافت نشد!", "danger")
        return redirect(url_for("reseller_dashboard"))

    username = reseller.get("username", f"reseller_{reseller_id}")
    seed = request.form.get("seed", f"{username}_{reseller_id}")
    style = request.form.get("style", "cyber_bot")

    try:
        svg_code = avatar_generator.generate_procedural_avatar_svg(seed, preset_id=style)
        AVATAR_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        svg_bytes = svg_code.encode("utf-8")
        custom_name = f"custom_reseller_{reseller_id}.svg"
        (AVATAR_CACHE_DIR / custom_name).write_bytes(svg_bytes)
        (AVATAR_CACHE_DIR / f"custom_{username}.svg").write_bytes(svg_bytes)
        if reseller and reseller.get("telegram_id"):
            (AVATAR_CACHE_DIR / f"custom_{reseller['telegram_id']}.svg").write_bytes(svg_bytes)

        db.update_reseller_profile(reseller_id, custom_avatar=custom_name)
        flash("آواتار سه‌بعدی با موفقیت اعمال شد.", "success")
        return redirect(url_for("reseller_profile"))
    except Exception as e:
        logger.error(f"Error setting preset avatar for reseller: {e}")
        flash(f"خطا در اعمال آواتار: {e}", "danger")
        return redirect(url_for("reseller_profile"))


@app.route("/reseller/avatar/delete", methods=["POST"])
@reseller_required
def reseller_avatar_delete():
    """حذف تصویر سفارشی نماینده و بازگشت به حالت پیش‌فرض"""
    reseller_id = session.get("reseller_id")
    reseller = db.get_reseller(reseller_id)
    username = reseller.get("username", "") if reseller else ""

    tg_id = reseller.get("telegram_id") if reseller else None
    for fn in [
        f"custom_reseller_{reseller_id}.svg", f"custom_reseller_{reseller_id}.jpg", f"custom_reseller_{reseller_id}.png",
        f"custom_{username}.svg", f"custom_{username}.jpg", f"custom_{username}.png",
        f"custom_{tg_id}.svg" if tg_id else None, f"custom_{tg_id}.jpg" if tg_id else None
    ]:
        if fn:
            p = AVATAR_CACHE_DIR / fn
            if p.exists():
                try:
                    p.unlink()
                except Exception:
                    pass

    if reseller_id:
        db.update_reseller_profile(reseller_id, custom_avatar="")

    flash("تصویر اختصاصی حذف شد و به حالت پیش‌فرض بازگشت.", "info")
    return redirect(url_for("reseller_profile"))


# ═══════════════════════════════════════════════════════════════════════
# فاکتور دیجیتال، بسته‌های اعتباری، پیش‌بینی مصرف و یادآوری هوشمند
# ═══════════════════════════════════════════════════════════════════════

@app.route("/invoice/<int:sub_id>")
def view_invoice(sub_id: int):
    """نمایش فاکتور رسمی دیجیتال با امکان چاپ، بارکد QR و اطلاعات تکمیلی اشتراک"""
    sub = db.get_subscription(sub_id)
    if not sub:
        flash("اشتراک مورد نظر یافت نشد.", "danger")
        return redirect(url_for("dashboard"))

    # دریافت برندینگ بر اساس اینکه اشتراک متعلق به نماینده است یا مدیریت اصلی
    branding = {}
    if sub.get("reseller_id"):
        reseller = db.get_reseller(sub["reseller_id"])
        if reseller:
            branding = {
                "brand_title": reseller.get("brand_title") or reseller.get("name"),
                "logo_url": reseller.get("logo_url"),
                "footer_text": reseller.get("footer_text"),
                "primary_color": reseller.get("primary_color") or "#4f46e5"
            }
    if not branding:
        branding = {
            "brand_title": db.get_setting("brand_title") or "سامانه هوشمند VPN",
            "logo_url": db.get_setting("logo_url") or "",
            "footer_text": "کلیه حقوق برای سامانه محفوظ است.",
            "primary_color": "#4f46e5"
        }

    single_link_template = get_single_link_template(db)
    sub_url = format_single_link(single_link_template, uuid=sub.get("hidify_uuid") or "", name=sub.get("account_name") or "")

    return render_template("invoice.html", sub=sub, branding=branding, sub_url=sub_url)


@app.route("/api/sub/<int:sub_id>/prediction")
def api_sub_prediction(sub_id: int):
    """محاسبه نرخ مصرف روزانه و پیش‌بینی هوشمند تاریخ اتمام حجم"""
    if not session.get("logged_in"):
        return jsonify({"error": "unauthorized"}), 401
    sub = db.get_subscription(sub_id)
    if not sub:
        return jsonify({"error": "اشتراک یافت نشد"}), 404
    pred = db.calculate_subscription_burn_rate(sub)
    return jsonify({"success": True, "prediction": pred})


@app.route("/admin/sub/<int:sub_id>/add_traffic", methods=["POST"])
@admin_required
def admin_sub_add_traffic(sub_id: int):
    """افزودن ترافیک اضافه (Top-up) به اشتراک کاربر بدون تغییر لینک"""
    extra_gb = request.form.get("extra_gb", 0)
    try:
        extra_gb = float(extra_gb)
    except Exception:
        extra_gb = 0.0

    if extra_gb <= 0:
        flash("مقدار حجم افزایشی نامعتبر است.", "warning")
        return redirect(request.referrer or url_for("subscriptions"))

    res = db.add_traffic_to_subscription(sub_id, extra_gb)
    if res.get("success"):
        flash(f"✅ مقدار {extra_gb} گیگابایت به سقف مصرف اشتراک افزوده شد (سقف جدید: {res['new_limit']} GB).", "success")
    else:
        flash(f"خطا در افزودن حجم: {res.get('error')}", "danger")

    return redirect(request.referrer or url_for("subscriptions"))


@app.route("/admin/debt/settle_partial", methods=["POST"])
@admin_required
def admin_debt_settle_partial():
    """ثبت پرداخت و تسویه اقساطی/پاره‌وقت بدهی مدیر یا شریک"""
    admin_id = request.form.get("admin_id", type=int)
    amount = request.form.get("amount", type=int)
    note = request.form.get("note", "").strip() or "تسویه حساب اقساطی"
    settled_by = session.get("admin_id") or 1

    if not admin_id or not amount or amount <= 0:
        flash("مبلغ یا شناسه مدیر نامعتبر است.", "warning")
        return redirect(url_for("accounting"))

    res = db.settle_admin_debt(admin_id, amount, note, settled_by)
    if res.get("success"):
        flash(f"✅ مبلغ {amount:,} تومان از بدهی تسویه شد. (مانده بدهی: {res.get('remaining_debt', 0):,} تومان)", "success")
    else:
        flash(f"خطا در تسویه بدهی: {res.get('error')}", "danger")

    return redirect(url_for("accounting"))


@app.route("/admin/debt/<int:admin_id>/reminder", methods=["POST"])
@admin_required
def admin_debt_reminder(admin_id: int):
    """ارسال پیام یادآوری بدهی به تلگرام مدیر یا شریک تجاری"""
    admin_user = db.get_admin_user(admin_id)
    if not admin_user:
        flash("مدیر یافت نشد.", "danger")
        return redirect(url_for("accounting"))

    debt = admin_user.get("debt_balance") or 0
    if debt <= 0:
        flash("این مدیر بدهی تسویه‌نشده‌ای ندارد.", "info")
        return redirect(url_for("accounting"))

    tg_id = admin_user.get("telegram_id")
    msg_text = (
        f"🔔 *یادآوری تسویه حساب مالی*\n\n"
        f"همکار گرامی جناب {admin_user.get('display_name') or admin_user.get('username')}،\n"
        f"مبلغ بدهی جاری شما بابت فروش‌های نقدی: *{debt:,} تومان* می‌باشد.\n\n"
        f"لطفاً جهت تسویه حساب به بخش امور مالی مراجعه فرمایید. با تشکر."
    )

    sent = False
    if tg_id and tg_id > 0:
        try:
            from bot import bot
            import asyncio
            asyncio.run(bot.send_message(chat_id=tg_id, text=msg_text, parse_mode="Markdown"))
            sent = True
        except Exception as e:
            logger.warning(f"Could not send telegram reminder to {tg_id}: {e}")

    if sent:
        flash(f"✅ پیام یادآوری بدهی ({debt:,} تومان) با موفقیت به تلگرام ارسال شد.", "success")
    else:
        flash(f"پیام یادآوری ثبت شد (شناسه تلگرام {tg_id or 'نامشخص'} بود).", "info")

    return redirect(url_for("accounting"))


@app.route("/reseller/bundles/buy", methods=["POST"])
@reseller_required
def reseller_bundles_buy():
    """خرید و فعال‌سازی آنی بسته شارژ عمده با اعتبار هدیه"""
    reseller_id = session.get("reseller_id")
    bundle_id = request.form.get("bundle_id")
    res = db.apply_reseller_bundle_purchase(reseller_id, bundle_id)
    if res.get("success"):
        b = res.get("bundle", {})
        flash(f"🎉 تبریک! {b.get('title')} با موفقیت فعال شد و مبلغ {b.get('credit'):,} تومان به موجودی شما افزوده شد.", "success")
    else:
        flash(f"خطا در خرید بسته: {res.get('error')}", "danger")
    return redirect(url_for("reseller_transactions"))


@app.route("/payment/callback/<order_id>", methods=["GET", "POST"])
def payment_callback(order_id: str):
    """پردازش بازگشت از درگاه پرداخت آنلاین شاپرک (زرین‌پال / آیدی‌پی)"""
    authority = request.args.get("Authority") or request.form.get("Authority")
    status = request.args.get("Status") or request.form.get("Status")
    idpay_id = request.args.get("id") or request.form.get("id")
    idpay_status = request.args.get("status") or request.form.get("status")

    trans = db.get_transaction_by_order_id(order_id)
    if not trans:
        return render_template("payment_result.html", success=False, message="تراکنش یافت نشد.")

    amount = trans.get("amount", 0)
    user_id = trans.get("user_id")
    plan_name = trans.get("plan_name", "")
    reseller_id = trans.get("reseller_id")

    if reseller_id:
        gw_cfg = db.get_reseller_gateway(reseller_id)
    else:
        gw_cfg = db.get_admin_gateway()

    gw_type = gw_cfg.get("type", "zarinpal")
    gw_key = gw_cfg.get("key", "")
    sandbox = gw_cfg.get("sandbox", False)

    verified = False
    ref_id = None

    if authority and status == "OK":
        from payment import ZarinPal
        zp = ZarinPal(merchant_id=gw_key, sandbox=sandbox)
        res = zp.verify_payment(authority=authority, amount=amount)
        if res.get("success"):
            verified = True
            ref_id = res.get("ref_id")
    elif idpay_id and str(idpay_status) in ("100", "10", "101"):
        from payment import IDPay
        idp = IDPay(api_key=gw_key, sandbox=sandbox)
        res = idp.verify_payment(payment_id=idpay_id, order_id=order_id)
        if res.get("success"):
            verified = True
            ref_id = res.get("ref_id")

    if verified:
        db.update_transaction(order_id, status="approved", ref_id=str(ref_id or authority or idpay_id))
        return render_template("payment_result.html", success=True, order_id=order_id, amount=amount, ref_id=ref_id, plan_name=plan_name)
    else:
        db.update_transaction(order_id, status="failed")
        return render_template("payment_result.html", success=False, order_id=order_id, amount=amount, message="پرداخت ناموفق بود یا توسط کاربر لغو گردید.")


# ─── راه‌اندازی سرور وب ───

def run_dashboard(host="0.0.0.0", port=None, debug=False):
    if port is None:
        port = int(os.getenv("PORT", 5000))
    print(f"🌐 Modern Web Dashboard running at http://{host}:{port}")

    # راه‌اندازی خودکار کلیه ربات‌های فعال نمایندگان در پس‌زمینه
    try:
        threading.Thread(target=multibot_manager.start_all_active_bots, daemon=True, name="MultiBotAutoStart").start()
    except Exception as e:
        logger.error(f"Error launching active reseller bots: {e}")

    app.run(host=host, port=port, debug=debug, use_reloader=False)


def start_dashboard_thread():
    """اجرای داشبورد در thread جداگانه هنگام استارت بات"""
    import threading
    t = threading.Thread(target=run_dashboard, daemon=True)
    t.start()
    return t


if __name__ == "__main__":
    run_dashboard(debug=True)
