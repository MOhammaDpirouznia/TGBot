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
    jsonify, flash, Response, send_file, g, abort
)
from werkzeug.utils import secure_filename

from dotenv import load_dotenv
load_dotenv()

from database import db
from utils import (
    generate_qr_code_bytes, get_now_iso, get_now_naive, get_single_link_template, 
    format_single_link, gregorian_to_shamsi, gregorian_to_shamsi_full, get_now_shamsi, TEHRAN_TZ
)
from admin_manager import (
    get_all_plans, add_plan, update_plan, delete_plan, move_plan_up, move_plan_down,
    get_plan_icon, get_bundle_icon, get_plan_telegram_emoji
)
from sms_service import send_auth_sms_notification, send_sms, get_sms_config, format_iranian_phone
from payment import CryptoPaymentGateway
import avatar_generator
from multibot_manager import multibot_manager, ResellerBotInstance
from tutorials_data import PLATFORMS, TUTORIALS, TROUBLESHOOTING_GUIDES
from palette_manager import (
    get_all_palettes, get_palette, get_active_palette_config, generate_palette_css
)

logger = logging.getLogger(__name__)

# ─── تنظیمات Flask ───
app = Flask(__name__)
app.secret_key = os.getenv("DASHBOARD_SECRET", "hiddibot-super-secret-key-2026")


# ─── بنرهای موقتی اطلاعیه پنل نمایندگان (In-Memory Temporary Banners) ───
RESELLER_PANEL_BANNERS: List[Dict[str, Any]] = []

def get_reseller_banners() -> List[Dict[str, Any]]:
    """دریافت بنرهای فعال و موقتی پنل نمایندگان متناسب با شناسه نماینده جاری"""
    if session.get("role") != "reseller":
        return []
    reseller_id = session.get("reseller_id")
    result = []
    for b in RESELLER_PANEL_BANNERS:
        t_id = b.get("target_reseller_id")
        if t_id is None or (reseller_id and int(t_id) == int(reseller_id)):
            result.append(b)
    return result


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
    try:
        db_proxy = db.get_setting("user_proxy_path") or db.get_setting("customer_proxy_path")
        if db_proxy and str(db_proxy).strip():
            return str(db_proxy).strip("/").strip()
    except Exception:
        pass
    return os.getenv("USER_PROXY_PATH", "user").strip("/")


def get_portal_proxy_path() -> str:
    """مسیر پروکسی پچ پورتال اختصاصی مشتریان (پیش‌فرض: renew)"""
    try:
        p = db.get_setting("portal_proxy_path")
        if p and str(p).strip():
            return str(p).strip("/").strip()
    except Exception:
        pass
    return "renew"


def get_customer_portal_url(token: str, _external: bool = True) -> str:
    """تولید آدرس اختصاصی پورتال مشتری با در نظر گرفتن پروکسی پچ تنظیمی"""
    token_clean = str(token).strip() if token else ""
    proxy = get_portal_proxy_path()
    if _external:
        try:
            base = request.host_url.rstrip("/") if request else ""
        except Exception:
            base = ""
        return f"{base}/{proxy}/{token_clean}" if base else f"/{proxy}/{token_clean}"
    return f"/{proxy}/{token_clean}"


def get_admin_login_proxy_path() -> str:
    """مسیر پروکسی پچ امنیتی ورود مدیریت و همکاران (پیش‌فرض: خالی)"""
    try:
        p = db.get_setting("admin_login_proxy_path")
        if p and str(p).strip():
            return str(p).strip("/").strip()
    except Exception:
        pass
    return ""


def get_login_url() -> str:
    """آدرس فعال ورود بر اساس وضعیت پروکسی پچ امنیتی"""
    proxy = get_admin_login_proxy_path()
    if proxy:
        return f"/{proxy}"
    try:
        return url_for("login")
    except Exception:
        return "/login"



def get_redirect_target(default_endpoint: str = "subscriptions", **fallback_kwargs) -> str:
    """
    بازگشت هوشمند به صفحه قبل با حفظ کامل پارامترهای جستجو، فیلتر و صفحه‌بندی
    ۱. بررسی فیلد فرم redirect_url یا return_url
    ۲. بررسی کوئری‌استرینگ redirect_url یا return_url
    ۳. بررسی request.referrer (آدرس دقیق ارجاع‌دهنده)
    ۴. در صورت عدم وجود یا نامعتبر بودن، بازگشت به default_endpoint
    """
    from urllib.parse import urlparse
    target = (
        request.form.get("redirect_url")
        or request.form.get("return_url")
        or request.args.get("redirect_url")
        or request.args.get("return_url")
        or request.referrer
    )
    if target:
        target = target.strip()
        try:
            ref_url = urlparse(target)
            req_url = urlparse(request.url)
            # اعتبارسنجی جهت جلوگیری از Open Redirect امنیتی و استخراج مسیر کامل با کوئری
            if not ref_url.netloc or ref_url.hostname == req_url.hostname:
                full_path = ref_url.path
                if ref_url.query:
                    full_path += "?" + ref_url.query
                if ref_url.fragment:
                    full_path += "#" + ref_url.fragment
                return full_path if full_path else target
        except Exception:
            pass
    return url_for(default_endpoint, **fallback_kwargs)


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

    # ۱. استخراج هوشمند telegram_id برای مدیر، نماینده یا مشتری
    target_tg_id = None
    if contact_info and contact_info.get("telegram_id"):
        target_tg_id = contact_info.get("telegram_id")

    is_phone = bool(re.match(r"^(\+98|0098|98|0)?9\d{9}$", clean_ident))
    if not target_tg_id:
        if clean_ident.isdigit() and not is_phone:
            # شاید مستقیماً آیدی عددی تلگرام ارسال شده باشد
            target_tg_id = int(clean_ident)
        elif is_phone:
            try:
                target_tg_id = db.find_telegram_id_by_phone(clean_ident)
            except Exception:
                pass

    # بررسی در جدول اشتراک‌ها (Subscriptions)
    if not target_tg_id:
        try:
            conn = db.get_connection()
            s_row = conn.execute("SELECT telegram_id FROM subscriptions WHERE account_name=? OR id=? OR hidify_uuid=? LIMIT 1", (clean_ident, clean_ident, clean_ident)).fetchone()
            if s_row and s_row["telegram_id"]:
                target_tg_id = s_row["telegram_id"]
            if not target_tg_id and clean_ident.isdigit():
                r_row = conn.execute("SELECT telegram_id FROM resellers WHERE id=?", (int(clean_ident),)).fetchone()
                if r_row and r_row["telegram_id"]:
                    target_tg_id = r_row["telegram_id"]
            conn.close()
        except Exception:
            pass

    # بررسی در جدول admin_users بر اساس نام یا نام نمایشی
    if not target_tg_id:
        try:
            conn = db.get_connection()
            a_row = conn.execute("SELECT telegram_id FROM admin_users WHERE LOWER(username)=? OR LOWER(display_name)=? LIMIT 1", (clean_ident.lower(), clean_ident.lower())).fetchone()
            if a_row and a_row["telegram_id"]:
                target_tg_id = a_row["telegram_id"]
            conn.close()
        except Exception:
            pass

    # بررسی در جدول users بر اساس username
    if not target_tg_id:
        try:
            conn = db.get_connection()
            u_row = conn.execute("SELECT telegram_id FROM users WHERE LOWER(username)=? LIMIT 1", (clean_ident.lower(),)).fetchone()
            if u_row and u_row["telegram_id"]:
                target_tg_id = u_row["telegram_id"]
            conn.close()
        except Exception:
            pass

    # ۲. دریافت عکس واقعی پروفایل تلگرام با Telegram ID واقعی
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

    # ۳. در صورت نداشتن آیدی تلگرام یا عدم وجود عکس در تلگرام: تولید آواتار تصادفی/مدرن محلی
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


@app.route("/avatars/<path:filename>")
def serve_avatar_static_file(filename):
    """سرویس‌دهی مستقیم و امن فایل‌های آواتار، لوگوها و فاویکون‌ها از پوشه کش"""
    p = AVATAR_CACHE_DIR / filename
    if p.exists() and p.is_file():
        ext = p.suffix.lower()
        mime = "image/svg+xml" if ext == ".svg" else ("image/png" if ext == ".png" else ("image/webp" if ext == ".webp" else ("image/x-icon" if ext == ".ico" else "image/jpeg")))
        resp = Response(p.read_bytes(), mimetype=mime)
        resp.headers["Cache-Control"] = "public, max-age=259200"
        return resp
    abort(404)


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
            return f"{days} روز"
    except Exception:
        return ""


@app.template_filter("field_display_name")
def filter_field_display_name(field_name):
    """ترجمه نام فیلدهای دیتابیس به عناوین خوانا و فارسی در سوابق تغییرات قبل و بعد"""
    translations = {
        "amount": "مبلغ (تومان)",
        "tracking_code": "کد پیگیری / ارجاع",
        "card_number": "شماره کارت مقصد",
        "account_comment": "یادداشت و توضیحات",
        "notes": "یادداشت و توضیحات",
        "description": "شرح / توضیحات",
        "plan_name": "نام پلن / بسته",
        "status": "وضعیت تراکنش",
        "is_deleted": "حذف نرم (سطل زباله)",
        "account_name": "نام کاربری / اکانت",
    }
    return translations.get(str(field_name).strip(), str(field_name))


@app.template_filter("format_audit_value")
def filter_format_audit_value(val, field_name=""):
    """قالب‌بندی خوانا و شکیل مقادیر در جدول مقایسه قبل و بعد"""
    if val is None or str(val).strip() in ("", "None", "null"):
        return "-"
    s_val = str(val).strip()
    if field_name == "amount":
        try:
            return f"{int(s_val):,} تومان"
        except Exception:
            return s_val
    elif field_name == "status":
        st_map = {
            "pending": "در انتظار",
            "approved": "تایید شده",
            "completed": "تکمیل شده",
            "rejected": "رد شده",
            "revoked": "ابطال‌شده",
        }
        return st_map.get(s_val, s_val)
    return s_val


@app.template_filter("from_json")
def filter_from_json(val):
    """تبدیل رشته JSON به دیکشنری در قالب‌های Jinja"""
    if not val:
        return {}
    if isinstance(val, dict):
        return val
    try:
        return json.loads(val)
    except Exception:
        return {}


@app.template_filter("last_connection_display")
@app.template_global("format_last_connection_display")
def filter_last_connection_display(date_str):
    """
    نمایش هوشمند وضعیت آخرین اتصال:
    - اگر متصل نشده باشد (null یا 0001-01-01): 'بدون اتصال'
    - اگر بیش از ۱ روز باشد: نمایش نسبی (مثلاً ۳ روز قبل یا ۱ روز قبل) + تاریخ و ساعت شمسی
    - اگر امروز باشد: 'امروز HH:MM' + تاریخ و ساعت شمسی
    """
    if not date_str or str(date_str).strip() in ["", "None", "null", "-", "0"] or str(date_str).startswith("0001"):
        return {
            "has_connected": False,
            "relative": "بدون اتصال",
            "relative_text": "بدون اتصال",
            "shamsi_datetime": "-",
            "shamsi_full": "بدون سابقه اتصال",
            "is_old": False,
            "is_past": False,
            "days_ago": 0,
            "time": "-",
            "badge_class": "bg-secondary-subtle text-secondary"
        }
    try:
        clean = str(date_str).replace("T", " ").split(".")[0].split("+")[0].strip()
        dt = datetime.strptime(clean[:19], "%Y-%m-%d %H:%M:%S")
        now_dt = get_now_naive()
        diff_sec = (now_dt - dt).total_seconds()
        days_ago = max(0, int(diff_sec // 86400))
        shamsi_dt = gregorian_to_shamsi(clean, fmt="%Y/%m/%d %H:%M")
        time_str = clean[11:16]

        diff_days = (now_dt.date() - dt.date()).days
        if diff_days > 0 or diff_sec >= 86400:
            effective_days = max(1, diff_days if diff_days > 0 else days_ago)
            rel_text = f"{effective_days} روز قبل"
            return {
                "has_connected": True,
                "relative": rel_text,
                "relative_text": rel_text,
                "shamsi_datetime": shamsi_dt,
                "shamsi_full": shamsi_dt,
                "is_old": True,
                "is_past": True,
                "days_ago": effective_days,
                "time": time_str,
                "badge_class": "bg-danger-subtle text-danger border border-danger" if effective_days >= 3 else "bg-warning-subtle text-dark border border-warning"
            }
        else:
            rel_text = f"امروز {time_str}"
            return {
                "has_connected": True,
                "relative": rel_text,
                "relative_text": rel_text,
                "shamsi_datetime": shamsi_dt,
                "shamsi_full": shamsi_dt,
                "is_old": False,
                "is_past": False,
                "days_ago": 0,
                "time": time_str,
                "badge_class": "bg-light text-secondary border"
            }
    except Exception:
        clean_fallback = str(date_str)[:16].replace("T", " ")
        return {
            "has_connected": True,
            "relative": clean_fallback,
            "relative_text": clean_fallback,
            "shamsi_datetime": clean_fallback,
            "shamsi_full": clean_fallback,
            "is_old": False,
            "is_past": False,
            "days_ago": 0,
            "time": "",
            "badge_class": "bg-light text-secondary border"
        }


_hiddify_traffic_cache = {}

def get_hiddify_dashboard_traffic_stats(api_key: str = None, reseller_id: int = None) -> dict:
    """
    دریافت و تحلیل هوشمند آمار مصرف ترافیک و کاربران آنلاین برای بلوک‌های رنگی داشبورد
    (امروز، دیروز، ماهانه، کل و شبکه) همراه با کش حافظه ۲۰ ثانیه‌ای و بازیابی در صورت قطعی
    """
    cache_key = f"{api_key or 'admin'}_{reseller_id or 0}"
    now_ts = time.time()
    cached = _hiddify_traffic_cache.get(cache_key)
    if cached and (now_ts - cached.get("ts", 0) < 20) and "today" in cached.get("data", {}):
        return cached.get("data", {})

    stats_db = db.get_online_users_stats(reseller_id=reseller_id)
    total_subs = stats_db.get("total_subs", 0)
    online_subs = stats_db.get("online_count", 0)

    blocks = {
        "today_gb": 0.0,
        "today_online": online_subs,
        "yesterday_gb": 0.0,
        "yesterday_online": max(0, int(online_subs * 0.9)),
        "monthly_gb": 0.0,
        "monthly_online": max(online_subs, int(total_subs * 0.65)),
        "total_gb": 0.0,
        "total_users": total_subs,
        "online_count": online_subs,
        "online_5m": online_subs,
        "net_up": "0.0",
        "net_down": "0.0",
        "net_cumulative": "0.0 GB",
        "today_pct": 20,
        "yesterday_pct": 40,
        "monthly_pct": 80,
    }

    try:
        raw_status = hidify_sync_request("GET", "/admin/server_status/", api_key=api_key)
        if isinstance(raw_status, dict) and "stats" in raw_status:
            sys_stats = raw_status.get("stats", {}).get("system", {})
            uhist = raw_status.get("usage_history", {})

            def _to_gb(val):
                try:
                    v = float(val or 0)
                    if v > 1000000:
                        return round(v / (1024 ** 3), 1)
                    return round(v, 1)
                except Exception:
                    return 0.0

            t_today = _to_gb(uhist.get("today", {}).get("usage", 0))
            t_yesterday = _to_gb(uhist.get("yesterday", {}).get("usage", 0))
            t_monthly = _to_gb(uhist.get("last_30_days", {}).get("usage", 0))
            t_total = _to_gb(uhist.get("total", {}).get("usage", 0))

            on_today = int(uhist.get("today", {}).get("online", 0)) or online_subs
            on_yesterday = int(uhist.get("yesterday", {}).get("online", 0)) or max(0, int(online_subs * 0.95))
            on_monthly = int(uhist.get("last_30_days", {}).get("online", 0)) or max(online_subs, int(total_subs * 0.65))
            u_total = int(uhist.get("total", {}).get("users", 0)) or total_subs

            bytes_sent = float(sys_stats.get("bytes_sent", 0))
            bytes_recv = float(sys_stats.get("bytes_recv", 0))
            mb_sent = round(bytes_sent / (1024 * 1024), 1)
            mb_recv = round(bytes_recv / (1024 * 1024), 1)
            net_total_gb = round(float(sys_stats.get("net_total_cumulative_GB", 0) or 0), 1)

            max_usage = max(t_monthly, t_total, 1.0)
            blocks.update({
                "today_gb": t_today,
                "today_online": on_today,
                "yesterday_gb": t_yesterday,
                "yesterday_online": on_yesterday,
                "monthly_gb": t_monthly,
                "monthly_online": on_monthly,
                "total_gb": t_total,
                "total_users": max(u_total, total_subs),
                "online_5m": int(uhist.get("m5", {}).get("online", 0)) or online_subs,
                "net_up": f"{mb_sent}",
                "net_down": f"{mb_recv}",
                "net_cumulative": f"{net_total_gb} GB" if net_total_gb > 0 else f"{t_total} GB",
                "today_pct": min(100, max(5, int((t_today / max_usage) * 100))) if max_usage > 0 else 15,
                "yesterday_pct": min(100, max(5, int((t_yesterday / max_usage) * 100))) if max_usage > 0 else 35,
                "monthly_pct": 100
            })
    except Exception as ex:
        logger.warning(f"Failed to fetch server_status from Hiddify: {ex}")

    if blocks["total_gb"] == 0:
        conn = db.get_connection()
        c = conn.cursor()
        if reseller_id:
            c.execute("SELECT COALESCE(SUM(data_used), 0) FROM subscriptions WHERE reseller_id=? AND (is_deleted=0 OR is_deleted IS NULL)", (reseller_id,))
        else:
            c.execute("SELECT COALESCE(SUM(data_used), 0) FROM subscriptions WHERE (is_deleted=0 OR is_deleted IS NULL)")
        total_used = round(float(c.fetchone()[0] or 0), 1)
        conn.close()
        blocks["total_gb"] = total_used
        blocks["monthly_gb"] = total_used
        blocks["today_gb"] = round(total_used * 0.12, 1)
        blocks["yesterday_gb"] = round(total_used * 0.28, 1)

    # ساختار متناظر برای تمپلیت‌های داشبورد اصلی و نماینده (dashboard.html & reseller_dashboard.html)
    blocks["today"] = {
        "usage_gb": float(blocks.get("today_gb", 0.0) or 0.0),
        "online_users": int(blocks.get("today_online", 0) or 0),
        "total_users": int(blocks.get("total_users", total_subs) or 0),
        "percent": int(blocks.get("today_pct", 20) or 20)
    }
    blocks["yesterday"] = {
        "usage_gb": float(blocks.get("yesterday_gb", 0.0) or 0.0),
        "online_users": int(blocks.get("yesterday_online", 0) or 0),
        "total_users": int(blocks.get("total_users", total_subs) or 0),
        "percent": int(blocks.get("yesterday_pct", 40) or 40)
    }
    blocks["month"] = {
        "usage_gb": float(blocks.get("monthly_gb", 0.0) or 0.0),
        "online_users": int(blocks.get("monthly_online", 0) or 0),
        "total_users": int(blocks.get("total_users", total_subs) or 0),
        "percent": int(blocks.get("monthly_pct", 100) or 100)
    }
    try:
        blocks["network_speed_down"] = float(blocks.get("net_down", 0) or 0.0)
    except Exception:
        blocks["network_speed_down"] = 0.0
    try:
        blocks["network_speed_up"] = float(blocks.get("net_up", 0) or 0.0)
    except Exception:
        blocks["network_speed_up"] = 0.0

    _hiddify_traffic_cache[cache_key] = {"ts": now_ts, "data": blocks}
    return blocks


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


@app.route("/api/qr-image", methods=["GET"])
def api_qr_image():
    """تولید تصویر بارکد QR به صورت کاملاً محلی و بدون وابستگی به اینترنت بین‌الملل"""
    text = request.args.get("text", "").strip()
    if not text:
        return "پارامتر متن بارکد الزامی است", 400
    try:
        qr_bytes = generate_qr_code_bytes(text)
        if not qr_bytes:
            return "خطا در تولید بارکد", 500
        return Response(
            qr_bytes,
            mimetype="image/png",
            headers={
                "Cache-Control": "public, max-age=86400",
                "Content-Disposition": "inline; filename=qr.png"
            }
        )
    except Exception as e:
        logger.error(f"Error in api_qr_image: {e}")
        return "خطای سرور", 500


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


def hidify_sync_request(method: str, endpoint: str, data: dict = None, api_key: str = None):
    """درخواست همگام به API پنل هیدیفای با استفاده از httpx با پشتیبانی از کلید ادمین اختصاصی نماینده"""
    panel_url = get_hiddify_url()
    active_key = (api_key.strip() if api_key else None) or get_hiddify_key()
    proxy_path = get_hiddify_proxy()

    if not panel_url or not active_key:
        return {"error": "اطلاعات پنل هیدیفای (HIDIFY_PANEL_URL / HIDIFY_API_KEY) تنظیم نشده است"}

    base_api = f"{panel_url}/{proxy_path}/api/v2"
    url = f"{base_api}{endpoint}"
    headers = {
        "Hiddify-API-Key": active_key,
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

            logger.info(f"Hidify sync API: {method} {url} (Key: {active_key[:8]}...) -> {resp.status_code}")
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


def hidify_sync_create_user(name: str, usage_limit_gb: float = None, package_days: int = None,
                           comment: str = None, api_key: str = None, reseller_id: int = None,
                           uuid: str = None, current_usage_gb: float = None,
                           start_date: str = None, expire_date: str = None,
                           enable: bool = True, is_active: bool = True) -> dict:
    """ساخت کاربر در هیدیفای با پشتیبانی از ادمین اختصاصی نماینده، UUID سفارشی، حجم مصرف‌شده اولیه و تاریخ‌ها"""
    active_api_key = api_key
    if not active_api_key and reseller_id:
        active_api_key = db.get_reseller_hiddify_key(reseller_id)

    raw_name = str(name or "").strip()
    if not raw_name:
        raw_name = f"user_{int(time.time())}"

    reseller_tag = f"[RESELLER_ID: #{reseller_id}] " if reseller_id else ""
    full_comment = f"{reseller_tag}{comment or ''}".strip()

    payload = {
        "name": raw_name,
        "enable": bool(enable),
        "is_active": bool(is_active),
    }
    if uuid:
        payload["uuid"] = str(uuid).strip()

    if usage_limit_gb is not None:
        try:
            val_gb = float(usage_limit_gb)
            if val_gb >= 0:
                payload["usage_limit_GB"] = val_gb
        except Exception:
            pass

    if current_usage_gb is not None:
        try:
            val_used = float(current_usage_gb)
            if val_used >= 0:
                payload["current_usage_GB"] = val_used
        except Exception:
            pass

    if package_days is not None:
        try:
            val_days = int(package_days)
            if val_days > 0:
                payload["package_days"] = val_days
        except Exception:
            pass

    if start_date and str(start_date).strip() not in ("None", "null", ""):
        payload["start_date"] = str(start_date).strip()
    if expire_date and str(expire_date).strip() not in ("None", "null", ""):
        payload["expire_date"] = str(expire_date).strip()

    if full_comment:
        payload["comment"] = str(full_comment)[:200]

    # ارسال درخواست ساخت به هیدیفای با کلید اختصاصی ادمین نماینده یا کلید اصلی
    res = hidify_sync_request("POST", "/admin/user/", payload, api_key=active_api_key)

    # در صورت بروز خطای 400 یا خطای فیلدها، با حداقل فیلدهای استاندارد مجدداً تلاش می‌کنیم
    if "error" in res and ("400" in str(res.get("error")) or "invalid" in str(res.get("error")).lower() or "unprocessable" in str(res.get("error")).lower()):
        logger.warning(f"Standard create_user failed ({res.get('error')}), trying fallback minimal payload...")
        minimal_payload = {
            "name": raw_name,
            "enable": bool(enable),
            "is_active": bool(is_active)
        }
        if "uuid" in payload:
            minimal_payload["uuid"] = payload["uuid"]
        if "usage_limit_GB" in payload:
            minimal_payload["usage_limit_GB"] = payload["usage_limit_GB"]
        if "package_days" in payload:
            minimal_payload["package_days"] = payload["package_days"]
        if "comment" in payload:
            minimal_payload["comment"] = payload["comment"]
        res = hidify_sync_request("POST", "/admin/user/", minimal_payload, api_key=active_api_key)

        # اگر با وجود UUID دستی باز هم با خطا مواجه شد، تلاش برای ساخت بدون UUID
        if "error" in res and "uuid" in minimal_payload:
            logger.warning("Fallback with UUID failed, trying create without manual UUID...")
            del minimal_payload["uuid"]
            res = hidify_sync_request("POST", "/admin/user/", minimal_payload, api_key=active_api_key)

    return res


def hidify_sync_create_admin(name: str, mode: str = "agent", comment: str = None,
                            can_add_admin: bool = False, lang: str = "fa",
                            max_users: int = None, max_usage_limit_gb: float = None,
                            admin_uuid: str = None) -> dict:
    """ساخت ادمین / نماینده مستقل در هیدیفای با ارسال شناسه UUID الزامی و بازیابی خودکار"""
    target_uuid = str(admin_uuid or uuid.uuid4())
    payload = {
        "uuid": target_uuid,
        "name": name,
        "mode": mode or "agent",
        "can_add_admin": bool(can_add_admin),
        "lang": lang or "fa"
    }
    if comment:
        payload["comment"] = str(comment)[:200]
    if max_users is not None and int(max_users) > 0:
        payload["max_users"] = int(max_users)
    if max_usage_limit_gb is not None and float(max_usage_limit_gb) > 0:
        payload["max_usage_limit_GB"] = float(max_usage_limit_gb)

    res = hidify_sync_request("POST", "/admin/admin_user/", payload)

    # اگر پاسخ مستقیماً موفقیت‌آمیز بود و حاوی UUID بود
    if isinstance(res, dict) and res.get("uuid"):
        return res

    # در صورت بروز خطای 500 یا عدم دریافت مستقیم UUID، استعلام و بازیابی خودکار انجام می‌دهیم
    try:
        # ۱. بررسی با شناسه یکتای ارسال‌شده
        check = hidify_sync_get_admin(target_uuid)
        if isinstance(check, dict) and check.get("uuid"):
            logger.info(f"Admin verified by UUID {target_uuid} on Hiddify")
            return check

        # ۲. جستجو در لیست کلیه ادمین‌ها بر اساس نام یا کامنت
        admins_list = hidify_sync_get_admins()
        if isinstance(admins_list, list):
            for adm in admins_list:
                if isinstance(adm, dict) and adm.get("uuid"):
                    adm_name = str(adm.get("name") or "").strip()
                    adm_comment = str(adm.get("comment") or "").strip()
                    if adm_name == str(name).strip() or (comment and adm_comment == str(comment).strip()):
                        logger.info(f"Admin recovered from Hiddify by name/comment: {adm.get('uuid')}")
                        return adm
    except Exception as e_rec:
        logger.warning(f"Error during admin sync recovery: {e_rec}")

    return res


def hidify_sync_get_admins() -> list:
    """دریافت لیست تمام ادمین‌ها و نمایندگان در هیدیفای"""
    res = hidify_sync_request("GET", "/admin/admin_user/")
    return res if isinstance(res, list) else []


def hidify_sync_get_admin(uuid: str) -> dict:
    """دریافت اطلاعات یک ادمین در هیدیفای"""
    return hidify_sync_request("GET", f"/admin/admin_user/{uuid}/")


def hidify_sync_delete_admin(uuid: str) -> dict:
    """حذف یک ادمین از هیدیفای"""
    return hidify_sync_request("DELETE", f"/admin/admin_user/{uuid}/")


def hidify_sync_update_admin(uuid: str, **kwargs) -> dict:
    """بروزرسانی اطلاعات یک ادمین در هیدیفای"""
    payload = {}
    if "name" in kwargs and kwargs["name"]:
        payload["name"] = str(kwargs["name"])
    if "comment" in kwargs:
        payload["comment"] = str(kwargs["comment"])[:200]
    if "mode" in kwargs and kwargs["mode"]:
        payload["mode"] = str(kwargs["mode"])
    if "can_add_admin" in kwargs:
        payload["can_add_admin"] = bool(kwargs["can_add_admin"])
    if "lang" in kwargs and kwargs["lang"]:
        payload["lang"] = str(kwargs["lang"])
    if "max_users" in kwargs and kwargs["max_users"] is not None:
        payload["max_users"] = int(kwargs["max_users"])
    if "max_usage_limit_gb" in kwargs and kwargs["max_usage_limit_gb"] is not None:
        payload["max_usage_limit_GB"] = float(kwargs["max_usage_limit_gb"])
    return hidify_sync_request("PATCH", f"/admin/admin_user/{uuid}/", payload)


def hidify_sync_update_user(uuid: str, api_key: str = None, reseller_id: int = None, **kwargs) -> dict:
    """
    بروزرسانی دقیق مشخصات کاربر در هیدیفای (نام، کامنت، حجم، روز، وضعیت و...)
    با پاکسازی هوشمند فیلدهای اضافی برای جلوگیری از خطای ۴۲۲ و پشتیبانی از کلیدهای اختصاصی و فال‌بک
    """
    if not uuid or not str(uuid).strip():
        return {"error": "UUID کاربر نامعتبر است"}

    clean_uuid = str(uuid).strip().strip("/")
    active_key = api_key
    if not active_key and reseller_id:
        active_key = db.get_reseller_hiddify_key(reseller_id)
    main_admin_key = get_hiddify_key()

    # نرمال‌سازی نام کلیدهای ورودی
    normalized_kwargs = {}
    for k, v in kwargs.items():
        if k in ("usage_limit_gb", "usage_limit_GB"):
            try:
                normalized_kwargs["usage_limit_GB"] = float(v)
            except Exception:
                pass
        elif k in ("current_usage_GB", "current_usage_gb", "current_usage"):
            try:
                normalized_kwargs["current_usage_GB"] = float(v)
            except Exception:
                pass
        elif k in ("package_days", "duration"):
            try:
                normalized_kwargs["package_days"] = int(v)
            except Exception:
                pass
        elif k == "name" and v is not None:
            normalized_kwargs["name"] = str(v).strip()
        elif k == "comment" and v is not None:
            normalized_kwargs["comment"] = str(v).strip()[:500]
        elif k in ("enable", "is_active"):
            normalized_kwargs[k] = bool(v)
        elif k in ("mode", "start_date", "expire_date", "expiry_time", "lang", "wg_pk", "wg_pub", "wg_psk", "telegram_id", "added_by", "added_by_uuid"):
            normalized_kwargs[k] = v

    # کلیدهایی که برای تلاش استفاده خواهند شد
    keys_to_try = []
    if active_key:
        keys_to_try.append(active_key)
    if main_admin_key and main_admin_key not in keys_to_try:
        keys_to_try.append(main_admin_key)

    last_res = {"error": "هیچ کلید معتبری برای اتصال به هیدیفای یافت نشد"}

    for k_val in keys_to_try:
        # ۱. روش اول: PATCH به /admin/user/{uuid}/ و /admin/user/{uuid}
        for ep in (f"/admin/user/{clean_uuid}/", f"/admin/user/{clean_uuid}"):
            res = hidify_sync_request("PATCH", ep, normalized_kwargs, api_key=k_val)
            if isinstance(res, dict) and "error" not in res:
                logger.info(f"Successfully updated user {clean_uuid} via PATCH on {ep}")
                return res
            last_res = res

        # ۲. روش دوم: GET اطلاعات فعلی کاربر و ارسال PUT پاکسازی‌شده
        for ep_get in (f"/admin/user/{clean_uuid}/", f"/admin/user/{clean_uuid}"):
            user_obj = hidify_sync_request("GET", ep_get, api_key=k_val)
            if isinstance(user_obj, dict) and "error" not in user_obj:
                # فیلدهای مجاز مدل Pydantic هیدیفای برای UserPutSchema / UserSchema
                allowed_hiddify_fields = {
                    "name", "usage_limit_GB", "current_usage_GB", "package_days", "comment", "mode",
                    "start_date", "expire_date", "enable", "is_active", "lang",
                    "added_by", "added_by_uuid", "wg_pk", "wg_pub", "wg_psk", "telegram_id"
                }
                clean_payload = {k: v for k, v in user_obj.items() if k in allowed_hiddify_fields}
                clean_payload.update(normalized_kwargs)

                # اطمینان از وجود فیلدهای اجباری در PUT
                if "name" not in clean_payload:
                    clean_payload["name"] = user_obj.get("name") or clean_uuid[:8]
                if "usage_limit_GB" not in clean_payload:
                    clean_payload["usage_limit_GB"] = float(user_obj.get("usage_limit_GB") or 0)
                if "package_days" not in clean_payload:
                    clean_payload["package_days"] = int(user_obj.get("package_days") or 30)

                for ep_put in (f"/admin/user/{clean_uuid}/", f"/admin/user/{clean_uuid}"):
                    res_put = hidify_sync_request("PUT", ep_put, clean_payload, api_key=k_val)
                    if isinstance(res_put, dict) and "error" not in res_put:
                        logger.info(f"Successfully updated user {clean_uuid} via PUT on {ep_put}")
                        return res_put
                    last_res = res_put

    return last_res


def hidify_sync_change_user_uuid(old_uuid: str, new_uuid: str, sub_fallback_data: dict = None) -> dict:
    """تغییر مطمئن شناسه UUID مشتری در پنل هیدیفای با پشتیبانی از PATCH و ساخت مجدد Fallback"""
    clean_old = str(old_uuid).strip().strip("/") if old_uuid else ""
    clean_new = str(new_uuid).strip().strip("/")
    if not clean_new:
        return {"error": "شناسه جدید نامعتبر است"}
    if clean_old == clean_new:
        return {"success": True, "uuid": clean_new}

    # کلیدهای معتبر برای اتصال
    active_key = session.get("reseller_uuid") if "reseller_uuid" in session else None
    main_admin_key = get_active_hiddify_admin_key()
    keys_to_try = []
    if active_key:
        keys_to_try.append(active_key)
    if main_admin_key and main_admin_key not in keys_to_try:
        keys_to_try.append(main_admin_key)

    for k_val in keys_to_try:
        # ۱. ابتدا تلاش با متد PATCH
        if clean_old:
            for ep in (f"/admin/user/{clean_old}/", f"/admin/user/{clean_old}"):
                res = hidify_sync_request("PATCH", ep, {"uuid": clean_new}, api_key=k_val)
                if isinstance(res, dict) and "error" not in res:
                    check = hidify_sync_request("GET", f"/admin/user/{clean_new}/", api_key=k_val)
                    if isinstance(check, dict) and check.get("name"):
                        logger.info(f"Successfully changed user UUID from {clean_old} to {clean_new} via PATCH")
                        return check

        # ۲. در صورت عدم تغییر با PATCH، استخراج مشخصات و ثبت مجدد با UUID جدید
        old_user = {}
        if clean_old:
            for ep_get in (f"/admin/user/{clean_old}/", f"/admin/user/{clean_old}"):
                resp = hidify_sync_request("GET", ep_get, api_key=k_val)
                if isinstance(resp, dict) and "error" not in resp and resp.get("name"):
                    old_user = resp
                    break

        # ساخت پیلود کاربر
        allowed_fields = {
            "name", "usage_limit_GB", "current_usage_GB", "package_days", "comment", "mode",
            "start_date", "expire_date", "enable", "is_active", "lang",
            "added_by", "wg_pk", "wg_pub", "wg_psk", "telegram_id"
        }
        payload = {k: v for k, v in old_user.items() if k in allowed_fields and v is not None}
        payload["uuid"] = clean_new

        # اگر اطلاعاتی از سرور هیدیفای برنگشت، از اطلاعات دیتابیس لوکال اشتراک استفاده می‌کنیم
        if not payload.get("name") and sub_fallback_data:
            payload["name"] = sub_fallback_data.get("account_name") or f"user_{clean_new[:8]}"
            payload["usage_limit_GB"] = float(sub_fallback_data.get("data_limit") or 30)
            payload["package_days"] = int(sub_fallback_data.get("duration") or 30)
            payload["enable"] = (sub_fallback_data.get("status") != "disabled")
            payload["is_active"] = True

        create_res = hidify_sync_request("POST", "/admin/user/", payload, api_key=k_val)
        if isinstance(create_res, dict) and "error" not in create_res:
            logger.info(f"User recreated with new UUID {clean_new}. Deleting old user {clean_old}...")
            if clean_old:
                hidify_sync_request("DELETE", f"/admin/user/{clean_old}/", api_key=k_val)
            return create_res

    return {"error": "خطا در برقراری ارتباط با سرور هیدیفای جهت تغییر UUID"}


def hidify_sync_renew_user(uuid: str, new_limit_gb: float, new_duration_days: int, force_instant: bool = True) -> dict:
    """
    تمدید هوشمند کاربر در هیدیفای با ریست کامل حجم و تاریخ شروع در حالت فعال‌سازی فوری:
    حالت اول (force_instant یا منقضی): جایگزینی کامل حجم و روز + ریست حجم مصرفی (0) و ریست زمان شروع (None / آغاز مجدد)
    حالت دوم (افزایشی): اضافه کردن حجم و روز به مقادیر قبلی
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

        # بررسی انقضای زمانی و انقضای حجمی
        is_time_expired = False
        start_date_val = user_info.get("start_date")
        if start_date_val and curr_days > 0:
            try:
                st_date = datetime.fromisoformat(str(start_date_val)[:10])
                if (datetime.now() - st_date).days >= curr_days:
                    is_time_expired = True
            except Exception:
                pass

        is_traffic_finished = (curr_limit > 0 and current_usage >= curr_limit)
        is_expired = (not is_active or not enable or is_traffic_finished or is_time_expired)

        if force_instant or is_expired:
            # جایگزینی مقادیر و ریست حجم مصرفی و زمان شروع
            logger.info(f"Sync Renew {uuid}: Reset & Replace -> Usage=0, limit={new_limit_gb} GB, days={new_duration_days}")
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
            # حالت دوم: اضافه کردن حجم و روز به مقادیر قبلی
            combined_limit = (curr_limit + new_limit_gb) if curr_limit > 0 and new_limit_gb > 0 else (new_limit_gb if new_limit_gb > 0 else 0)
            combined_days = curr_days + new_duration_days
            logger.info(f"Sync Renew {uuid}: Appending volume & days ({curr_limit}+{new_limit_gb}={combined_limit} GB, {curr_days}+{new_duration_days}={combined_days} days)")
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
        res = hidify_sync_update_user(uuid, usage_limit_GB=new_limit_gb, package_days=new_duration_days, current_usage_GB=0, enable=True, is_active=True)
        return {"renewal_type": "fallback", "new_limit": new_limit_gb, "new_days": new_duration_days, "res": res}


def process_subscription_queue() -> dict:
    """
    بررسی هوشمند و خودکار صف تمدید و فعال‌سازی بلادرنگ بسته‌های رزرو:
    شرایط فعال‌سازی:
    ۱. مصرف ۹۹٪ از سقف حجم بسته فعلی (data_used >= data_limit * 0.99)
    ۲. رسیدن به روز پایانی بسته فعلی (کمتر یا مساوی ۲۴ ساعت مانده به انقضا)
    هنگام فعال‌سازی: ریست کامل حجم (0) و روزها در هیدیفای، بروزرسانی دیتابیس، ثبت سابقه در آرشیو و ارسال نوتیفیکیشن
    """
    try:
        pending_items = db.get_all_pending_queue_items()
        if not pending_items:
            return {"processed": 0, "activated": 0}

        activated_count = 0
        now = get_now_naive()
        processed_sub_ids = set()

        for item in pending_items:
            sub_id = item["subscription_id"]
            if sub_id in processed_sub_ids:
                # برای هر اشتراک، صرفاً اولین بسته در نوبت صف (سر صف) بررسی و فعال می‌شود
                continue
            processed_sub_ids.add(sub_id)
            uuid = item.get("hidify_uuid")
            new_limit = float(item.get("data_limit") or 0)
            new_duration = int(item.get("duration") or 30)
            plan_name = item.get("plan_name") or f"{new_limit} گیگ"
            plan_id = item.get("plan_id") or "custom"

            curr_used = float(item.get("curr_used") or 0)
            curr_limit = float(item.get("curr_limit") or 0)
            curr_duration = int(item.get("curr_duration") or 30)
            curr_start = item.get("curr_start_date")
            curr_expire = item.get("curr_expire_date")

            # استعلام مصرف زنده کاربر در صورت وجود UUID
            if uuid:
                try:
                    u_info = hidify_sync_request("GET", f"/admin/user/{uuid}/")
                    if isinstance(u_info, dict) and "error" not in u_info:
                        curr_used = float(u_info.get("current_usage_GB") or 0)
                        h_limit = float(u_info.get("usage_limit_GB") or 0)
                        if h_limit > 0:
                            curr_limit = h_limit
                        if u_info.get("start_date"):
                            curr_start = u_info.get("start_date")
                        if u_info.get("package_days"):
                            curr_duration = int(u_info.get("package_days"))
                except Exception as ex:
                    logger.warning(f"Live queue check error for {uuid}: {ex}")

            # ۱. شرط اول: رسیدن به ۹۹٪ حجم
            is_volume_99 = (curr_limit > 0 and curr_used >= (curr_limit * 0.99))

            # ۲. شرط دوم: رسیدن به آخرین روز بسته فعلی (<= 1 روز مانده)
            is_last_day = False
            if curr_start and curr_duration:
                try:
                    st_date = datetime.fromisoformat(str(curr_start)[:10])
                    exp_date = st_date + timedelta(days=curr_duration)
                    days_left = (exp_date.date() - now.date()).days
                    if days_left <= 1:
                        is_last_day = True
                except Exception:
                    pass
            elif curr_expire:
                try:
                    exp_date = datetime.fromisoformat(str(curr_expire)[:10])
                    days_left = (exp_date.date() - now.date()).days
                    if days_left <= 1:
                        is_last_day = True
                except Exception:
                    pass

            if is_volume_99 or is_last_day:
                trigger_reason = "مصرف ۹۹٪ حجم بسته" if is_volume_99 else "رسیدن به روز پایانی بسته"
                logger.info(f"Auto-activating queued renewal for sub {sub_id} ({item.get('account_name')}): {trigger_reason}")

                # الف. فعال‌سازی در هیدیفای با ریست کامل حجم و روز
                if uuid:
                    try:
                        hidify_sync_renew_user(uuid, new_limit, new_duration, force_instant=True)
                    except Exception as e:
                        logger.error(f"Hiddify auto-activation error for {uuid}: {e}")

                # ب. به‌روزرسانی اشتراک در دیتابیس لوکال
                now_str = get_now_iso()
                new_start_str = now.strftime("%Y-%m-%d")
                new_expire_str = (now + timedelta(days=new_duration)).isoformat()

                conn = db.get_connection()
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE subscriptions
                    SET plan_id=?, plan_name=?, data_limit=?, data_used=0, duration=?, status='active',
                        start_date=?, expire_date=?, updated_at=?
                    WHERE id=?
                """, (plan_id, plan_name, new_limit, new_duration, new_start_str, new_expire_str, now_str, sub_id))
                conn.commit()
                conn.close()

                # ج. ثبت در سوابق مصرف دوره‌های گذشته
                try:
                    db.log_subscription_history(
                        subscription_id=sub_id,
                        telegram_id=item.get("telegram_id") or 0,
                        hidify_uuid=uuid or "",
                        account_name=item.get("account_name") or "",
                        plan_name=plan_name,
                        previous_usage_gb=curr_used,
                        previous_limit_gb=curr_limit,
                        period_days=curr_duration,
                        renewal_type="queued_auto_activated",
                        reseller_id=item.get("reseller_id"),
                        cost_paid=item.get("cost") or 0,
                        note=f"فعال‌سازی خودکار از صف رزرو ({trigger_reason})"
                    )
                except Exception as ex:
                    logger.warning(f"Error logging history for queue activation: {ex}")

                # د. علامت‌گذاری در جدول صف
                db.mark_queue_item_activated(item["id"])
                activated_count += 1

                # هـ. ارسال نوتیفیکیشن تلگرام
                tg_id = item.get("telegram_id") or item.get("sub_tg_id")
                if tg_id and int(tg_id) > 0:
                    try:
                        send_telegram_msg(
                            int(tg_id),
                            f"🎉 <b>اشتراک شما با موفقیت تمدید شد!</b>\n\n"
                            f"بسته رزرو شده «{plan_name}» به صورت خودکار برای اشتراک <b>{item.get('account_name')}</b> فعال گردید.\n\n"
                            f"📊 حجم جدید: <b>{new_limit} گیگابایت</b>\n"
                            f"⏱ مدت اعتبار: <b>{new_duration} روز</b>\n"
                            f"🔄 وضعیت: حجم مصرفی صفر شد و سرویس شما بدون قطعی ادامه دارد."
                        )
                    except Exception as ex:
                        logger.debug(f"Could not send telegram alert for queued renewal: {ex}")

        return {"processed": len(pending_items), "activated": activated_count}
    except Exception as e:
        logger.error(f"Error in process_subscription_queue: {e}")
        return {"processed": 0, "activated": 0, "error": str(e)}


def activate_single_queue_item(queue_id: int, triggered_by: str = "مدیریت") -> dict:
    """
    فعال‌سازی آنی و دستی یک بسته در صف تمدید:
    - ریست کامل مصرف در هیدیفای به صفر و جایگزینی حجم و مدت جدید
    - به‌روزرسانی وضعیت اشتراک در دیتابیس لوکال و ریست تاریخ شروع و انقضا
    - ثبت در سوابق دوره‌های مصرف
    - علامت‌گذاری به عنوان فعال‌شده در subscription_queue
    - ارسال پیام به تلگرام کاربر در صورت وجود
    """
    conn = db.get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM subscription_queue WHERE id=? AND status='pending'", (queue_id,))
        item = cursor.fetchone()
        if not item:
            return {"success": False, "error": "بسته مورد نظر در صف یافت نشد یا قبلاً فعال/لغو شده است."}
        item = dict(item)

        sub_id = item["subscription_id"]
        cursor.execute("SELECT * FROM subscriptions WHERE id=?", (sub_id,))
        sub_row = cursor.fetchone()
        if not sub_row:
            return {"success": False, "error": "اشتراک مربوط به این بسته یافت نشد."}
        sub = dict(sub_row)

        uuid = item.get("hidify_uuid") or sub.get("hidify_uuid")
        new_limit = float(item.get("data_limit") or 0)
        new_duration = int(item.get("duration") or 30)
        plan_name = item.get("plan_name") or f"{new_limit} گیگ"
        plan_id = item.get("plan_id") or "custom"

        # ۱. فعال‌سازی در هیدیفای با ریست کامل حجم و روز
        if uuid:
            try:
                hidify_sync_renew_user(uuid, new_limit, new_duration, force_instant=True)
            except Exception as e:
                logger.error(f"Hiddify manual queue activation error for {uuid}: {e}")

        # ۲. به‌روزرسانی اشتراک در دیتابیس لوکال
        now = get_now_naive()
        now_str = get_now_iso()
        new_start_str = now.strftime("%Y-%m-%d")
        new_expire_str = (now + timedelta(days=new_duration)).isoformat()

        cursor.execute("""
            UPDATE subscriptions
            SET plan_id=?, plan_name=?, data_limit=?, data_used=0, duration=?, status='active',
                start_date=?, expire_date=?, updated_at=?, last_renewed_by=?
            WHERE id=?
        """, (plan_id, plan_name, new_limit, new_duration, new_start_str, new_expire_str, now_str, triggered_by, sub_id))
        conn.commit()

        # ۳. ثبت در سوابق مصرف
        try:
            db.log_subscription_history(
                subscription_id=sub_id,
                telegram_id=item.get("telegram_id") or sub.get("telegram_id") or 0,
                hidify_uuid=uuid or "",
                account_name=sub.get("account_name") or "",
                plan_name=plan_name,
                previous_usage_gb=sub.get("data_used") or 0,
                previous_limit_gb=sub.get("data_limit") or 0,
                period_days=new_duration,
                renewal_type="queued_manual_activated",
                reseller_id=item.get("reseller_id"),
                cost_paid=item.get("cost") or 0,
                note=f"فعال‌سازی دستی از صف رزرو توسط {triggered_by}"
            )
        except Exception as ex:
            logger.warning(f"Error logging history for manual queue activation: {ex}")

        # ۴. علامت‌گذاری در جدول صف
        db.mark_queue_item_activated(queue_id)

        # ۵. ارسال نوتیفیکیشن تلگرام
        tg_id = item.get("telegram_id") or sub.get("telegram_id")
        if tg_id and int(tg_id) > 0:
            try:
                send_telegram_msg(
                    int(tg_id),
                    f"🎉 <b>اشتراک شما با موفقیت تمدید و فعال شد!</b>\n\n"
                    f"بسته رزرو شده «{plan_name}» هم‌اکنون برای اشتراک <b>{sub.get('account_name')}</b> فعال گردید.\n\n"
                    f"📊 حجم جدید: <b>{new_limit} گیگابایت</b>\n"
                    f"⏱ مدت اعتبار: <b>{new_duration} روز</b>\n"
                    f"🔄 وضعیت: حجم مصرفی صفر شد و سرویس شما فعال است."
                )
            except Exception as ex:
                logger.debug(f"Could not send telegram alert for manual queue activation: {ex}")

        return {"success": True, "account_name": sub.get("account_name"), "plan_name": plan_name}
    except Exception as e:
        logger.error(f"Error in activate_single_queue_item: {e}")
        return {"success": False, "error": str(e)}
    finally:
        conn.close()


def hidify_sync_delete_user(uuid: str) -> dict:
    """حذف کاربر از سرور هیدیفای"""
    if not uuid:
        return {"error": "UUID نامعتبر است."}
    return hidify_sync_request("DELETE", f"/admin/user/{uuid}/")


def hiddify_restore_or_recreate_subscription(sub: dict, reseller_id: int = None) -> dict:
    """
    بازگردانی هوشمند و ساخت مجدد اشتراک در پنل هیدیفای با حفظ کامل حجم مصرفی و ادامه زمان باقی‌مانده:
    ۱. استخراج و محاسبه زمان مصرف‌شده قبل از حذف و تنظیم تاریخ شروع مجدد (start_date) بر اساس روزهای باقیمانده
    ۲. بررسی زنده وجود داشتن یا نداشتن کاربر روی سرور هیدیفای (با کلید اختصاصی نماینده یا ادمین اصلی)
    ۳. اگر کاربر حذف شده باشد، ساخت مجدد با همان UUID قبلی (جهت حفظ لینک کانفیگ مشتری)، سقف حجم و روزها
    ۴. تنظیم و اعمال حجم مصرف‌شده (current_usage_GB) دقیقاً برابر با مقدار ذخیره‌شده تا صفر نشود
    ۵. فعال‌سازی مجدد اکانت (enable=True, is_active=True)
    """
    uuid_val = sub.get("hidify_uuid")
    if not uuid_val or not str(uuid_val).strip():
        uuid_val = str(uuid.uuid4())

    clean_uuid = str(uuid_val).strip().strip("/")
    account_name = sub.get("account_name") or f"user_{clean_uuid[:8]}"
    data_limit = float(sub.get("data_limit") or 0.0)
    data_used = float(sub.get("data_used") or 0.0)
    duration = int(sub.get("duration") or 30)
    r_id = reseller_id if reseller_id is not None else sub.get("reseller_id")

    active_api_key = db.get_reseller_hiddify_key(r_id) if r_id else None
    main_admin_key = get_hiddify_key()

    keys_to_try = []
    if active_api_key:
        keys_to_try.append(active_api_key)
    if main_admin_key and main_admin_key not in keys_to_try:
        keys_to_try.append(main_admin_key)

    # محاسبه روزهای مصرف‌شده و روزهای باقی‌مانده
    now_dt = get_now_naive()
    today = now_dt.date()

    start_date_str = sub.get("start_date")
    deleted_at_str = sub.get("deleted_at")
    
    has_started = False
    days_used = 0

    if start_date_str and str(start_date_str).strip() not in ("None", "null", ""):
        try:
            clean_start = str(start_date_str).strip().replace("Z", "")[:10]
            st_date = datetime.strptime(clean_start, "%Y-%m-%d").date()
            has_started = True

            if deleted_at_str and str(deleted_at_str).strip() not in ("None", "null", ""):
                clean_del = str(deleted_at_str).strip().replace("Z", "+00:00")
                del_dt = datetime.fromisoformat(clean_del).replace(tzinfo=None).date()
                days_used = max(0, (del_dt - st_date).days)
            else:
                days_used = max(0, (today - st_date).days)
        except Exception as ex:
            logger.warning(f"Error calculating days_used for sub {sub.get('id')}: {ex}")
            has_started = False
            days_used = 0

    if has_started:
        days_used = min(days_used, duration)
        remaining_days = max(1, duration - days_used) if duration > days_used else 0
        new_start_date = (today - timedelta(days=days_used)).strftime("%Y-%m-%d")
        new_expire_date = (today + timedelta(days=remaining_days)).strftime("%Y-%m-%d")
    else:
        remaining_days = duration
        new_start_date = None
        new_expire_date = None

    # کامنت اشتراک
    phone = sub.get("phone_number") or ""
    tg_id = sub.get("telegram_id") or ""
    orig_comment = sub.get("account_comment") or ""
    comment_parts = []
    if orig_comment:
        comment_parts.append(orig_comment)
    if phone and f"Phone: {phone}" not in orig_comment:
        comment_parts.append(f"Phone: {phone}")
    if tg_id and str(tg_id).isdigit() and int(tg_id) > 0 and f"TG: {tg_id}" not in orig_comment:
        comment_parts.append(f"TG: {tg_id}")
    comment_text = " | ".join(comment_parts)

    reseller_tag = f"[RESELLER_ID: #{r_id}] " if r_id else ""
    full_comment = f"{reseller_tag}{comment_text}".strip()[:200]

    # ۱. بررسی اینکه آیا کاربر روی هیدیفای وجود دارد یا خیر
    existing_user = None
    for k in keys_to_try:
        get_res = hidify_sync_request("GET", f"/admin/user/{clean_uuid}/", api_key=k)
        if isinstance(get_res, dict) and "error" not in get_res and get_res.get("name"):
            existing_user = get_res
            break

    recreated = False
    final_uuid = clean_uuid

    if not existing_user:
        # کاربر روی سرور هیدیفای یافت نشد -> ساخت مجدد
        logger.info(f"User {clean_uuid} not found in Hiddify. Recreating with usage={data_used} GB, start={new_start_date}...")
        recreated = True
        create_res = hidify_sync_create_user(
            name=account_name,
            usage_limit_gb=data_limit,
            package_days=duration,
            comment=full_comment,
            api_key=active_api_key,
            reseller_id=r_id,
            uuid=clean_uuid,
            current_usage_gb=data_used,
            start_date=new_start_date,
            expire_date=new_expire_date,
            enable=True,
            is_active=True
        )

        if isinstance(create_res, dict) and "error" in create_res:
            logger.error(f"Failed to recreate user {clean_uuid} in Hiddify: {create_res.get('error')}")
            return {
                "success": False,
                "error": f"عدم موفقیت در ساخت کاربر در پنل هیدیفای: {create_res.get('error')}"
            }

        if isinstance(create_res, dict) and create_res.get("uuid"):
            final_uuid = create_res.get("uuid")

    # ۲. به‌روزرسانی نهایی و تضمین ثبت current_usage_GB و تاریخ‌ها از طریق PATCH و PUT
    update_payload = {
        "name": account_name,
        "usage_limit_GB": data_limit,
        "current_usage_GB": data_used,
        "package_days": duration,
        "start_date": new_start_date,
        "expire_date": new_expire_date,
        "enable": True,
        "is_active": True,
        "comment": full_comment
    }

    upd_res = hidify_sync_update_user(
        final_uuid,
        api_key=active_api_key,
        reseller_id=r_id,
        **update_payload
    )
    logger.info(f"Updated restored user {final_uuid} in Hiddify: {upd_res}")

    # تضمین قطعی فعال‌سازی در هیدیفای با ارسال صریح فلگ enable
    for k in keys_to_try:
        try:
            hidify_sync_request("PATCH", f"/admin/user/{final_uuid}/", {"enable": True, "is_active": True}, api_key=k)
        except Exception:
            pass

    return {
        "success": True,
        "recreated": recreated,
        "uuid": final_uuid,
        "account_name": account_name,
        "data_used": data_used,
        "data_limit": data_limit,
        "duration": duration,
        "days_used": days_used,
        "remaining_days": remaining_days,
        "new_start_date": new_start_date,
        "new_expire_date": new_expire_date
    }


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
    همراه با پردازش هوشمند صف تمدید خودکار و اصلاح وضعیت‌های منقضی
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

        # همگام‌سازی کاربران نمایندگانی که کلید اختصاصی دارند
        try:
            resellers = db.get_all_resellers()
            for r in resellers:
                r_uuid = r.get("hiddify_admin_uuid")
                if r_uuid and str(r_uuid).strip():
                    try:
                        r_users = hidify_sync_request("GET", "/admin/user/", api_key=str(r_uuid).strip())
                        if isinstance(r_users, list) and r_users:
                            db.sync_from_hidify(r_users)
                    except Exception:
                        pass
        except Exception:
            pass

        # تصحیح و بروزرسانی بلادرنگ اشتراک‌های منقضی و رفع پرچم آنلاین کاذب
        db.refresh_subscriptions_expiry_and_online()
        
        # بررسی و فعال‌سازی خودکار بسته‌های در صف رزرو
        process_subscription_queue()
    except Exception as e:
        logger.error(f"Error in sync_hiddify_online_users: {e}")


def get_subscription_issuer_info(sub: dict, resellers_map: dict = None, admins_map: dict = None) -> dict:
    """
    تشخیص دقیق صادرکننده اشتراک:
    - برای شخص صادرکننده: نام‌کاربری (username) صادرکننده
    - برای ربات نماینده: نام و عنوان نماینده + ربات (مثلاً: ربات صابر رحمانی)
    - برای ربات مدیریت: ربات مدیریت
    """
    if not isinstance(sub, dict):
        return {
            "text": "مدیریت",
            "username": "admin",
            "is_bot": False,
            "badge_class": "bg-secondary-subtle text-secondary-emphasis border border-secondary-subtle shadow-sm font-monospace",
            "icon": "fa-user-shield",
            "title": "مدیریت"
        }

    if resellers_map is None:
        try:
            resellers_map = {r["id"]: r for r in db.get_all_resellers()}
        except Exception:
            resellers_map = {}
    if admins_map is None:
        try:
            admins_map = {a["username"].lower(): a for a in db.get_admin_users() if a.get("username")}
        except Exception:
            admins_map = {}

    created_by = str(sub.get("created_by") or "").strip()
    r_id = sub.get("reseller_id")
    comment = str(sub.get("account_comment") or "").strip()
    acct_name = str(sub.get("account_name") or "").strip()
    tg_id = sub.get("telegram_id") or 0

    # در صورتی که r_id خالی باشد اما در کامنت تگ نماینده وجود داشته باشد
    if not r_id and ("[RESELLER_ID:" in comment or "Reseller #" in comment):
        try:
            import re
            m = re.search(r"\[RESELLER_ID:\s*#?(\d+)\]", comment) or re.search(r"Reseller\s*#(\d+)", comment)
            if m:
                r_id = int(m.group(1))
        except Exception:
            pass

    # ۱. اشتراک مربوط به یک نماینده است
    if r_id:
        reseller = resellers_map.get(int(r_id)) or {}
        r_username = reseller.get("username") or f"reseller_{r_id}"
        r_name = reseller.get("name") or reseller.get("brand_name") or r_username

        is_reseller_bot = False
        if created_by in ("bot", "robot", "ربات") or created_by.startswith("bot_reseller_") or created_by.startswith("bot:"):
            is_reseller_bot = True
        elif any(k in comment.lower() for k in ["wallet purchase", "direct issue", "multibot"]):
            is_reseller_bot = True
        elif "[reseller_id:" in comment.lower() and ("user " in comment.lower() or "tg:" in comment.lower()):
            is_reseller_bot = True

        if is_reseller_bot:
            return {
                "text": "ربات",
                "username": "bot",
                "is_bot": True,
                "badge_class": "bg-secondary-subtle text-secondary-emphasis border border-secondary-subtle shadow-sm font-monospace",
                "icon": "fa-robot",
                "title": f"صادر شده توسط ربات نماینده {r_name} (@{r_username})"
            }
        else:
            # صادر شده توسط شخص مدیر/کاربر نماینده در وب‌پنل
            issuer_user = created_by if (created_by and not created_by.startswith("reseller_")) else r_username
            return {
                "text": issuer_user,
                "username": issuer_user,
                "is_bot": False,
                "badge_class": "bg-light text-dark border font-monospace shadow-sm",
                "icon": "fa-user-tie",
                "title": f"صادرکننده: {issuer_user}"
            }

    # ۲. اشتراک مربوط به مدیریت است
    # الف) صادر شده توسط ربات مدیریت اصلی
    if created_by == "admin_bot":
        return {
            "text": "ربات مدیریت",
            "username": "bot",
            "is_bot": True,
            "badge_class": "bg-primary-subtle text-primary border border-primary-subtle shadow-sm",
            "icon": "fa-robot",
            "title": "صادر شده توسط ربات تلگرام مدیریت"
        }

    # کاربر تلگرام خریداری کرده و پیشوند Admin: در کامنت ندارد
    if tg_id and int(tg_id) > 0 and not comment.startswith("Admin:") and (not comment or comment.isdigit() or acct_name.startswith("tg_")):
        return {
            "text": "ربات مدیریت",
            "username": "bot",
            "is_bot": True,
            "badge_class": "bg-primary-subtle text-primary border border-primary-subtle shadow-sm",
            "icon": "fa-robot",
            "title": "صادر شده توسط ربات تلگرام مدیریت"
        }

    # ب) صادر شده توسط شخص مدیر در پنل
    if "Admin:" in comment:
        try:
            admin_user_tag = comment.split("Admin:")[1].split("|")[0].strip()
            if admin_user_tag:
                a_obj = admins_map.get(admin_user_tag.lower())
                disp_title = a_obj.get("display_name", "") if a_obj else "مدیر"
                return {
                    "text": admin_user_tag,
                    "username": admin_user_tag,
                    "is_bot": False,
                    "badge_class": "bg-secondary-subtle text-secondary-emphasis border border-secondary-subtle shadow-sm font-monospace",
                    "icon": "fa-user-shield",
                    "title": f"مدیر سیستم: {disp_title} ({admin_user_tag})"
                }
        except Exception:
            pass

    if created_by and created_by.lower() in admins_map:
        a_obj = admins_map.get(created_by.lower())
        disp_title = a_obj.get("display_name", "") if a_obj else "مدیر"
        return {
            "text": created_by,
            "username": created_by,
            "is_bot": False,
            "badge_class": "bg-secondary-subtle text-secondary-emphasis border border-secondary-subtle shadow-sm font-monospace",
            "icon": "fa-user-shield",
            "title": f"مدیر سیستم: {disp_title} ({created_by})"
        }

    first_admin = next((a["username"] for a in admins_map.values() if a.get("role") == "super_admin"), "hECTOR")
    return {
        "text": first_admin,
        "username": first_admin,
        "is_bot": False,
        "badge_class": "bg-secondary-subtle text-secondary-emphasis border border-secondary-subtle shadow-sm font-monospace",
        "icon": "fa-user-shield",
        "title": f"مدیر سیستم: {first_admin}"
    }


def enrich_subscription_details(sub: dict, resellers_map: dict = None, admins_map: dict = None) -> dict:
    """
    محاسبه شاخص‌های زنده اشتراک: روزهای مانده یا گذشته از انقضا، وضعیت شروع، درصد مصرف و تشخیص صادرکننده
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
    is_expired = False
    remaining_days = duration
    expired_days = 0
    expiry_text = ""
    exp_dt = None

    if expire_date_str and str(expire_date_str).strip() not in ["None", "null", ""]:
        try:
            clean_exp = str(expire_date_str).strip().replace("Z", "")
            if len(clean_exp) == 10:
                exp_dt = datetime.strptime(clean_exp, "%Y-%m-%d")
            else:
                exp_dt = datetime.fromisoformat(clean_exp)
            if exp_dt.tzinfo is not None:
                exp_dt = exp_dt.astimezone(TEHRAN_TZ).replace(tzinfo=None)
            is_started = True
        except Exception:
            pass
    elif start_date_str and str(start_date_str).strip() not in ["None", "null", ""]:
        try:
            clean_start = str(start_date_str).strip().replace("Z", "")
            if len(clean_start) == 10:
                start_dt = datetime.strptime(clean_start, "%Y-%m-%d")
            else:
                start_dt = datetime.fromisoformat(clean_start)
            if start_dt.tzinfo is not None:
                start_dt = start_dt.astimezone(TEHRAN_TZ).replace(tzinfo=None)
            exp_dt = start_dt + timedelta(days=duration)
            is_started = True
        except Exception:
            pass

    if is_started and exp_dt:
        # تاریخ انقضا بر اساس روز تقویمی (دقیقاً مشابه پنل هیدیفای)
        diff_days = (exp_dt.date() - now_dt.date()).days
        diff_seconds = (exp_dt - now_dt).total_seconds()
        
        if diff_days < 0 or diff_seconds < 0:
            is_expired = True
            expired_days = max(1, abs(diff_days))
            remaining_days = -expired_days
            expiry_text = f"{expired_days} روز پیش"
        elif diff_days == 0:
            if diff_seconds <= 0:
                is_expired = True
                expired_days = 0
                remaining_days = 0
                expiry_text = "امروز منقضی شد"
            else:
                remaining_days = 0
                expiry_text = "امروز به پایان می‌رسد"
        else:
            remaining_days = diff_days
            expiry_text = f"{diff_days} روز دیگر"
    else:
        is_started = False
        remaining_days = duration
        expiry_text = f"{duration} روز"

    usage_pct = int((data_used / data_limit * 100)) if data_limit > 0 else 0
    remaining_gb = max(0.0, data_limit - data_used) if data_limit > 0 else 0.0
    is_traffic_expired = (data_limit > 0 and data_used >= data_limit)

    # اگر اشتراک منقضی شده، حجمش تمام شده یا غیرفعال باشد، آنلاین نخواهد بود
    if is_expired or is_traffic_expired:
        item["is_online"] = 0
        if item.get("status") == "active":
            item["status"] = "expired"

    if item.get("status") in ("expired", "disabled", "inactive"):
        item["is_online"] = 0

    # اعتبارسنجی مجدد زمان آخرین اتصال (اگر بیش از ۵ دقیقه قبل بوده، آفلاین است)
    last_online_val = item.get("last_online")
    if last_online_val and str(last_online_val).strip() not in ["", "None", "null", "-"] and not str(last_online_val).startswith("0001"):
        try:
            clean_lo = str(last_online_val).replace("T", " ").split(".")[0].split("+")[0].strip()
            lo_dt = datetime.strptime(clean_lo[:19], "%Y-%m-%d %H:%M:%S")
            now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
            diff_lo = (now_dt - lo_dt).total_seconds()
            diff_lo_utc = (now_utc - lo_dt).total_seconds()
            if not ((0 <= diff_lo <= 300) or (0 <= diff_lo_utc <= 300)):
                item["is_online"] = 0
        except Exception:
            pass

    tg_id = item.get("telegram_id")
    if tg_id:
        try:
            item["is_vip"] = db.is_user_vip(int(tg_id))
        except Exception:
            item["is_vip"] = False
    else:
        item["is_vip"] = False

    try:
        q_items = db.get_pending_queue_items(item.get("id"))
        item["pending_queues"] = q_items
        item["pending_queue"] = q_items[0] if q_items else None
        item["has_queue"] = bool(q_items)
        item["queue_count"] = len(q_items)
    except Exception:
        item["pending_queues"] = []
        item["pending_queue"] = None
        item["has_queue"] = False
        item["queue_count"] = 0

    item["duration"] = duration
    item["is_started"] = is_started
    item["is_expired"] = is_expired
    item["expired_days"] = expired_days
    item["expiry_text"] = expiry_text
    item["remaining_days"] = remaining_days
    item["remaining_gb"] = round(remaining_gb, 2)
    item["usage_pct"] = min(100, usage_pct)
    item["issuer_info"] = get_subscription_issuer_info(item, resellers_map=resellers_map, admins_map=admins_map)

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


def get_reseller_plans_dict(reseller_id: int) -> dict:
    """دریافت دیکشنری پلن‌های اختصاصی نماینده شامل تمام شخصی‌سازی‌های نام، قیمت، حجم و مدت اعمال‌شده توسط مدیریت"""
    try:
        return db.get_reseller_plans_dict(reseller_id)
    except Exception as e:
        logger.error(f"Error loading reseller plans dict for reseller {reseller_id}: {e}")
        return get_plans_dict()



# ─── دکوریتورهای احراز هویت (Auth Decorators) ───

@app.before_request
def update_user_session_activity():
    if session.get("logged_in") and session.get("session_token"):
        token = session.get("session_token")
        # بررسی اینکه آیا نشست توسط مدیر یا کاربر خاتمه داده شده است
        admin_proxy = get_admin_login_proxy_path()
        excluded_paths = {"/login", "/logout"}
        if admin_proxy:
            excluded_paths.add(f"/{admin_proxy}")
            excluded_paths.add(f"/{admin_proxy}/login")
        if not request.path.startswith("/static") and request.path not in excluded_paths:
            if not db.is_session_active(token):
                session.clear()
                flash("نشست کاربری شما پایان یافته است. لطفاً مجدداً وارد شوید.", "warning")
                return redirect(get_login_url())
        try:
            db.update_session_activity(token)
        except Exception:
            pass


def login_required(f):
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(get_login_url())
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
                return redirect(get_login_url())
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
            return redirect(get_login_url())
        return f(*args, **kwargs)
    return decorated_function


def super_admin_required(f):
    """دسترسی انحصاری فقط برای مدیر ارشد (Super Admin)"""
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("logged_in") or session.get("role") != "admin":
            flash("دسترسی به این صفحه فقط برای مدیران مجاز است.", "danger")
            return redirect(get_login_url())
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
            return redirect(get_login_url())
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


# ─── مدیریت نسخه هوشمند فروشگاه (Store Version) ───
_store_version_cache = {"version": None, "timestamp": 0}

def get_store_version() -> str:
    """دریافت نسخه فروشگاه به صورت دستی یا هوشمند از گیت‌هاب"""
    source = db.get_setting("store_version_source", "manual")
    manual_version = db.get_setting("store_version", "v0.0.1 Beta") or "v0.0.1 Beta"
    if source != "github":
        return manual_version

    now = time.time()
    if _store_version_cache.get("version") and (now - _store_version_cache.get("timestamp", 0) < 900):
        return _store_version_cache["version"]

    repo = (db.get_setting("store_github_repo", "") or "").strip()
    if not repo:
        return manual_version

    if "github.com/" in repo:
        repo = repo.split("github.com/")[-1].strip("/")

    try:
        import urllib.request
        url = f"https://api.github.com/repos/{repo}/releases/latest"
        req = urllib.request.Request(url, headers={"User-Agent": "HiddiBot-System"})
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            tag = data.get("tag_name") or data.get("name")
            if tag:
                _store_version_cache["version"] = tag
                _store_version_cache["timestamp"] = now
                return tag
    except Exception as e:
        logger.debug(f"Could not fetch github latest release for {repo}: {e}")

    try:
        import urllib.request
        url = f"https://api.github.com/repos/{repo}/tags"
        req = urllib.request.Request(url, headers={"User-Agent": "HiddiBot-System"})
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data and isinstance(data, list) and len(data) > 0:
                tag = data[0].get("name")
                if tag:
                    _store_version_cache["version"] = tag
                    _store_version_cache["timestamp"] = now
                    return tag
    except Exception:
        pass

    return manual_version


@app.context_processor
def inject_global_branding():
    """تزریق متغیرهای هویت بصری، برندینگ، دامنه اختصاصی، نسخه و دسترسی‌ها به قالب‌های Jinja"""
    active_reseller_id = session.get("reseller_id")
    
    # تنظیمات کلی سیستم و فروشگاه
    system_store_name = db.get_setting("store_name", "سامانه هوشمند اینترنت پرو")
    system_store_logo = db.get_setting("store_logo", "")
    system_store_favicon = db.get_setting("store_favicon", "")
    system_copyright = db.get_setting("store_copyright", "تمامی حقوق برای این سامانه محفوظ است © 2026")
    system_primary_color = db.get_setting("store_primary_color", "#4f46e5")
    system_brand_header_style = db.get_setting("brand_header_style", "style_glass")
    system_version_icon_type = db.get_setting("version_icon_type", "branch")
    system_version_custom_icon = db.get_setting("version_custom_icon", "")
    store_version = get_store_version()

    branding = {}
    if active_reseller_id:
        r_data = db.get_reseller(active_reseller_id)
        if r_data:
            session["balance"] = int(r_data.get("balance") or 0)
            credit_limit = int(r_data.get("credit_limit") or 0)
            credit_debt = int(r_data.get("credit_debt") or 0)
            credit_enabled = bool(r_data.get("credit_enabled")) or (credit_limit > 0)
            available_credit = max(0, credit_limit - credit_debt) if credit_enabled else 0
            session["credit_enabled"] = credit_enabled
            session["credit_limit"] = credit_limit
            session["credit_debt"] = credit_debt
            session["available_credit"] = available_credit
            session["total_purchasing_power"] = session["balance"] + available_credit

            reseller_custom_title = (r_data.get("brand_title") or "").strip()
            final_brand_title = reseller_custom_title if reseller_custom_title else system_store_name

            reseller_custom_logo = (r_data.get("logo_url") or "").strip()
            final_logo_url = reseller_custom_logo if reseller_custom_logo else system_store_logo

            branding = {
                "brand_title": final_brand_title,
                "logo_url": final_logo_url,
                "favicon_url": r_data.get("favicon_url") or system_store_favicon,
                "primary_color": r_data.get("primary_color") or system_primary_color,
                "footer_text": r_data.get("footer_text") or system_copyright,
                "store_version": store_version,
                "system_version": store_version,
                "brand_header_style": system_brand_header_style,
                "version_icon_type": system_version_icon_type,
                "version_custom_icon": system_version_custom_icon,
                "custom_domain": r_data.get("custom_domain"),
                "tutorial_domain": r_data.get("tutorial_domain"),
                "support_username": r_data.get("support_username"),
                "bot_username": r_data.get("bot_username")
            }
        else:
            session["balance"] = 0
            session["credit_enabled"] = False
            session["credit_limit"] = 0
            session["credit_debt"] = 0
            session["available_credit"] = 0
            session["total_purchasing_power"] = 0
    elif getattr(g, "custom_reseller", None):
        r_data = g.custom_reseller
        reseller_custom_title = (r_data.get("brand_title") or "").strip()
        final_brand_title = reseller_custom_title if reseller_custom_title else system_store_name

        reseller_custom_logo = (r_data.get("logo_url") or "").strip()
        final_logo_url = reseller_custom_logo if reseller_custom_logo else system_store_logo

        branding = {
            "brand_title": final_brand_title,
            "logo_url": final_logo_url,
            "favicon_url": r_data.get("favicon_url") or system_store_favicon,
            "primary_color": r_data.get("primary_color") or system_primary_color,
            "footer_text": r_data.get("footer_text") or system_copyright,
            "store_version": store_version,
            "system_version": store_version,
            "brand_header_style": system_brand_header_style,
            "version_icon_type": system_version_icon_type,
            "version_custom_icon": system_version_custom_icon,
            "custom_domain": r_data.get("custom_domain"),
            "tutorial_domain": r_data.get("tutorial_domain"),
            "support_username": r_data.get("support_username"),
            "bot_username": r_data.get("bot_username")
        }
    else:
        # تنظیمات برند پیش‌فرض سیستم برای ادمین و صفحات عمومی
        admin_tutorial_title = db.get_setting("tutorial_title", "راهنما و آموزش اتصال")
        admin_tutorial_domain = db.get_setting("tutorial_domain", "")
        branding = {
            "brand_title": system_store_name,
            "logo_url": system_store_logo,
            "favicon_url": system_store_favicon,
            "primary_color": system_primary_color,
            "footer_text": system_copyright,
            "store_version": store_version,
            "system_version": store_version,
            "brand_header_style": system_brand_header_style,
            "version_icon_type": system_version_icon_type,
            "version_custom_icon": system_version_custom_icon,
            "tutorial_domain": admin_tutorial_domain
        }

    reseller_has_credit = False
    reseller_available_credit = 0
    reseller_credit_limit = 0
    reseller_credit_debt = 0
    if active_reseller_id:
        reseller_has_credit = bool(session.get("credit_enabled")) or (session.get("credit_limit") or 0) > 0
        reseller_available_credit = session.get("available_credit", 0)
        reseller_credit_limit = session.get("credit_limit", 0)
        reseller_credit_debt = session.get("credit_debt", 0)

    # پالت اختصاصی و استایل‌های شیشه‌ای مات
    palette_config = get_active_palette_config(db, context="system")
    palette_css = generate_palette_css(palette_config)

    return dict(
        has_permission=has_permission,
        branding=branding,
        store_version=store_version,
        get_plan_icon=get_plan_icon,
        get_plan_telegram_emoji=get_plan_telegram_emoji,
        get_bundle_icon=get_bundle_icon,
        sub_role=session.get("sub_role"),
        has_reseller_credit=reseller_has_credit,
        has_credit=reseller_has_credit,
        global_credit_enabled=reseller_has_credit,
        global_available_credit=reseller_available_credit,
        global_credit_limit=reseller_credit_limit,
        global_credit_debt=reseller_credit_debt,
        palette_config=palette_config,
        palette_css=palette_css,
        available_palettes=get_all_palettes(),
        get_reseller_banners=get_reseller_banners,
        reseller_panel_banners=RESELLER_PANEL_BANNERS,
        get_customer_portal_url=get_customer_portal_url,
        get_portal_proxy_path=get_portal_proxy_path,
        get_admin_login_proxy_path=get_admin_login_proxy_path,
        get_login_url=get_login_url
    )


# ─── مسیرهای احراز هویت (Authentication) ───

def render_login_page():
    login_style = db.get_setting("login_style", "glass_aurora")
    login_page_title = db.get_setting("login_page_title", "")
    login_page_subtitle = db.get_setting("login_page_subtitle", "")
    login_bg_effect = str(db.get_setting("login_bg_effect", "1")).lower() in ("1", "true")
    return render_template(
        "login.html",
        login_style=login_style,
        login_page_title=login_page_title,
        login_page_subtitle=login_page_subtitle,
        login_bg_effect=login_bg_effect
    )


def _handle_login_flow():
    """منطق احراز هویت مشترک ورود با پشتیبانی از نقش‌های RBAC، نمایندگان و کپچا"""
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
            return render_login_page()

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
            credit_limit = int(reseller.get("credit_limit") or 0)
            credit_debt = int(reseller.get("credit_debt") or 0)
            credit_enabled = bool(reseller.get("credit_enabled")) or (credit_limit > 0)
            available_credit = max(0, credit_limit - credit_debt) if credit_enabled else 0
            session["credit_enabled"] = credit_enabled
            session["credit_limit"] = credit_limit
            session["credit_debt"] = credit_debt
            session["available_credit"] = available_credit
            session["total_purchasing_power"] = session["balance"] + available_credit
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

    return render_login_page()


@app.route("/login", methods=["GET", "POST"])
def login():
    """صفحه ورود پیش‌فرض (در صورت تنظیم پروکسی پچ ورود، این روت مسدود ۴۰۴ می‌شود)"""
    admin_proxy = get_admin_login_proxy_path()
    if admin_proxy:
        abort(404)
    return _handle_login_flow()


@app.route("/<path_proxy>", methods=["GET", "POST"])
def custom_login(path_proxy: str):
    """صفحه ورود از طریق پروکسی پچ اختصاصی تنظیم‌شده توسط مدیر"""
    admin_proxy = get_admin_login_proxy_path()
    if admin_proxy and path_proxy.strip("/") == admin_proxy:
        return _handle_login_flow()
    abort(404)


@app.route("/<path_proxy>/login", methods=["GET", "POST"])
def custom_login_subpath(path_proxy: str):
    """پشتیبانی از فرمت آدرس با پسوند login"""
    admin_proxy = get_admin_login_proxy_path()
    if admin_proxy and path_proxy.strip("/") == admin_proxy:
        return _handle_login_flow()
    abort(404)


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
    return redirect(get_login_url())


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
    total_revenue = conn.execute("SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE status IN ('approved', 'completed') AND ((reseller_id IS NULL OR reseller_id = 0) OR gateway = 'bundle_reseller' OR order_id LIKE 'R_BUNDLE%')").fetchone()[0]
    pending_payments = conn.execute("SELECT COUNT(*) FROM transactions WHERE status='pending' AND ((reseller_id IS NULL OR reseller_id = 0) OR gateway = 'bundle_reseller' OR order_id LIKE 'R_BUNDLE%')").fetchone()[0]
    open_tickets = conn.execute("SELECT COUNT(*) FROM support_tickets WHERE status='open' AND (reseller_id IS NULL OR reseller_id = 0)").fetchone()[0]
    total_resellers = conn.execute("SELECT COUNT(*) FROM resellers").fetchone()[0]

    recent_transactions = conn.execute("""
        SELECT * FROM transactions 
        WHERE ((reseller_id IS NULL OR reseller_id = 0) OR gateway = 'bundle_reseller' OR order_id LIKE 'R_BUNDLE%')
        ORDER BY created_at DESC LIMIT 8
    """).fetchall()

    daily_revenue = conn.execute("""
        SELECT DATE(created_at) as date, SUM(amount) as total
        FROM transactions 
        WHERE status IN ('approved', 'completed') 
          AND ((reseller_id IS NULL OR reseller_id = 0) OR gateway = 'bundle_reseller' OR order_id LIKE 'R_BUNDLE%')
          AND created_at >= DATE('now', '-7 days')
        GROUP BY DATE(created_at)
        ORDER BY date ASC
    """).fetchall()

    conn.close()

    sync_hiddify_online_users()
    server_health = hidify_sync_ping()
    analytics = db.get_advanced_analytics()
    online_stats = db.get_online_users_stats()
    traffic_blocks = get_hiddify_dashboard_traffic_stats()

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
        analytics=analytics,
        traffic_blocks=traffic_blocks
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

    user_list = [dict(u) for u in conn.execute(query, params).fetchall()]
    
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


@app.route("/admin/bot-menu", methods=["GET", "POST"])
@app.route("/admin/bot-settings", methods=["GET", "POST"])
@admin_required
def bot_menu_settings():
    """مدیریت و سفارشی‌سازی عناوین، فعال/غیرفعال بودن و چیدمان افقی و عمودی دکمه‌های منوی ربات مدیریت و ربات‌های نمایندگان"""
    active_tab = request.args.get("tab", "admin")

    if request.method == "POST":
        bot_type = request.form.get("bot_type", "admin").strip().lower()
        action = request.form.get("action", "").strip()

        if action == "save_domains" or bot_type == "domains":
            tutorial_domain = request.form.get("tutorial_domain", "").strip().lower()
            troubleshoot_domain = request.form.get("troubleshoot_domain", "").strip().lower()
            db.save_setting("tutorial_domain", tutorial_domain)
            db.save_setting("troubleshoot_domain", troubleshoot_domain)
            flash("دامنه‌های راهنمای اتصال و حل مشکلات اتصال با موفقیت ذخیره شدند.", "success")
            return redirect(url_for("bot_menu_settings", tab=request.form.get("active_tab", "admin")))

        if bot_type == "reseller":
            all_buttons = db.get_reseller_bot_menu_buttons()
            updated_list = []
            for btn in all_buttons:
                b_id = btn["id"]
                title = request.form.get(f"title_{b_id}", btn.get("title", ""))
                row = int(request.form.get(f"row_{b_id}", btn.get("row", 0)))
                col = int(request.form.get(f"col_{b_id}", btn.get("col", 0)))
                is_enabled = request.form.get(f"enabled_{b_id}") == "1"
                disabled_behavior = request.form.get(f"behavior_{b_id}", btn.get("disabled_behavior", "show_disabled"))
                disabled_msg = request.form.get(f"dis_msg_{b_id}", btn.get("disabled_message", ""))
                updated_list.append({
                    "id": b_id,
                    "title": title.strip(),
                    "row": row,
                    "col": col,
                    "is_enabled": is_enabled,
                    "disabled_behavior": disabled_behavior,
                    "disabled_message": disabled_msg.strip(),
                    "description": btn.get("description", ""),
                })
            db.save_reseller_bot_menu_buttons(updated_list)
            flash("تنظیمات و چیدمان دکمه‌های ربات نمایندگان با موفقیت ذخیره شد.", "success")
            return redirect(url_for("bot_menu_settings", tab="reseller"))
        else:
            all_buttons = db.get_bot_menu_buttons()
            updated_list = []
            for btn in all_buttons:
                b_id = btn["id"]
                title = request.form.get(f"title_{b_id}", btn.get("title", ""))
                row = int(request.form.get(f"row_{b_id}", btn.get("row", 0)))
                col = int(request.form.get(f"col_{b_id}", btn.get("col", 0)))
                is_enabled = request.form.get(f"enabled_{b_id}") == "1"
                disabled_behavior = request.form.get(f"behavior_{b_id}", btn.get("disabled_behavior", "show_disabled"))
                disabled_msg = request.form.get(f"dis_msg_{b_id}", btn.get("disabled_message", ""))
                updated_list.append({
                    "id": b_id,
                    "title": title.strip(),
                    "row": row,
                    "col": col,
                    "is_enabled": is_enabled,
                    "disabled_behavior": disabled_behavior,
                    "disabled_message": disabled_msg.strip(),
                    "description": btn.get("description", ""),
                })
            db.save_bot_menu_buttons(updated_list)
            flash("تنظیمات و چیدمان دکمه‌های ربات مدیریت با موفقیت ذخیره شد.", "success")
            return redirect(url_for("bot_menu_settings", tab="admin"))

    admin_buttons = db.get_bot_menu_buttons()
    admin_menu_rows = db.get_bot_menu_keyboard_rows(is_admin=True, is_reseller=False)
    reseller_buttons = db.get_reseller_bot_menu_buttons()
    reseller_menu_rows = db.get_bot_menu_keyboard_rows(is_reseller=True)
    tutorial_domain = db.get_setting("tutorial_domain", "")
    troubleshoot_domain = db.get_setting("troubleshoot_domain", "")

    return render_template(
        "bot_menu_settings.html",
        admin_buttons=admin_buttons,
        admin_menu_rows=admin_menu_rows,
        reseller_buttons=reseller_buttons,
        reseller_menu_rows=reseller_menu_rows,
        tutorial_domain=tutorial_domain,
        troubleshoot_domain=troubleshoot_domain,
        active_tab=active_tab,
        buttons=admin_buttons,
        menu_rows=admin_menu_rows
    )


@app.route("/admin/bot-menu/reset", methods=["POST"])
@admin_required
def admin_bot_menu_reset():
    """بازنشانی دکمه‌های منوی ربات به چیدمان و نام‌های پیش‌فرض"""
    reset_type = request.args.get("type") or request.form.get("type", "admin")
    if reset_type == "reseller":
        db.reset_reseller_bot_menu_buttons()
        flash("چیدمان و دکمه‌های منوی ربات نمایندگان با موفقیت به حالت پیش‌فرض بازنشانی شد.", "info")
        return redirect(url_for("bot_menu_settings", tab="reseller"))
    else:
        db.reset_bot_menu_buttons()
        flash("چیدمان و دکمه‌های منوی ربات مدیریت با موفقیت به حالت پیش‌فرض بازنشانی شد.", "info")
        return redirect(url_for("bot_menu_settings", tab="admin"))


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


def determine_transaction_origin(tx: dict) -> str:
    """
    تشخیص دقیق مبدأ فیش و تراکنش:
    - 'admin': پنل مدیریت (عملیات دستی مدیر، تمدید یا ساخت مشتری از پنل)
    - 'reseller': پنل نماینده (عملیات دستی نماینده در پنل)
    - 'bundle': بسته نماینده (شارژ بسته اعتباری یا کیف پول نماینده)
    - 'portal': پرتال مشتری (خرید، تمدید یا تسویه بدهی از طریق وب پرتال مشتری)
    - 'telegram': ربات تلگرام (خرید یا پرداخت توسط کاربر در ربات تلگرام اصلی یا ربات نماینده)
    """
    src = str(tx.get("source") or "").lower().strip()
    gateway = str(tx.get("gateway") or "").lower().strip()
    order_id = str(tx.get("order_id") or "").strip()
    tracking_code = str(tx.get("tracking_code") or "").strip()
    notes = str(tx.get("notes") or "").lower().strip()
    user_id = tx.get("user_id") or 0
    username = str(tx.get("username") or "")

    # ۰. پرچم‌های صریح
    if tx.get("is_admin_manual"):
        return "admin"
    if tx.get("is_portal"):
        return "portal"

    # ۱. بسته اعتباری یا کیف پول نماینده
    if gateway == "bundle_reseller" or order_id.startswith("R_BUNDLE") or src == "bundle":
        return "bundle"

    # ۲. پنل مدیریت (عملیات دستی ادمین، ثبت نقد، تمدید یا ثبت از پنل مدیریت)
    if (src in ("admin", "admin_panel") or
        gateway in ("cash_admin", "free_admin", "admin_manual") or
        order_id.startswith("ADM_") or order_id.startswith("RNW_") or
        tracking_code.startswith("RENEW_") or tracking_code.startswith("CASH_") or
        tracking_code.startswith("FREE_") or "رسید دستی" in tracking_code or
        "مدیریت" in notes or "توسط ادمین" in notes or "ثبت دستی" in notes):
        return "admin"

    # ۳. پنل نماینده (عملیات دستی نماینده در پنل)
    if (src in ("reseller", "reseller_panel") or
        gateway in ("cash_reseller", "free_reseller", "reseller_manual", "reseller_panel") or
        gateway.startswith("reseller_") or
        order_id.startswith("RES_") or tracking_code.startswith("RESELLER_") or
        "پنل نماینده" in notes):
        return "reseller"

    # ۴. وب پرتال اختصاصی مشتری
    if (src in ("portal", "web", "customer_portal") or
        gateway.startswith("portal") or "portal" in gateway or
        "پرتال" in notes or "portal" in notes or
        (order_id.startswith("INV") and user_id == 0 and not username.startswith("tg_"))):
        return "portal"

    # ۵. ربات تلگرام (ربات اصلی یا ربات‌های اختصاصی نمایندگان)
    if (src in ("telegram", "bot", "reseller_bot") or
        order_id.startswith("card_") or order_id.startswith("ONL_") or order_id.startswith("R1_") or
        gateway in ("card_to_card", "card_reseller") or
        "ربات" in notes or "telegram" in notes or
        user_id > 0 or username.startswith("tg_")):
        return "telegram"

    if tx.get("account_name") and user_id == 0:
        return "portal"
    return "telegram"


@app.route("/payments")
@admin_required
def payments():
    """کارتابل مدیریت و تایید فیش‌های پرداخت با تفکیک ۳ تب: مدیریت، نمایندگان و همه به همراه فیلتر نماینده"""
    conn = db.get_connection()
    status_filter = request.args.get("status", "all")
    source_tab = request.args.get("source", "all")  # 'all', 'admin', 'resellers' (پیش‌فرض: همه)
    reseller_filter_id = request.args.get("reseller_id", "")
    search = request.args.get("search", "").strip()

    base_conditions = []
    params = []

    if source_tab == "admin":
        # پرداخت‌های مستقیم مدیریت و ربات اصلی
        base_conditions.append("(reseller_id IS NULL OR reseller_id = 0)")
    elif source_tab == "resellers":
        # فقط رسیدهایی که نماینده برای کیف پول و بسته‌های خود ثبت کرده است
        base_conditions.append("(reseller_id IS NOT NULL AND reseller_id > 0 AND (gateway = 'bundle_reseller' OR order_id LIKE 'R_BUNDLE%'))")
        if reseller_filter_id and reseller_filter_id.isdigit():
            base_conditions.append("reseller_id = ?")
            params.append(int(reseller_filter_id))
    elif source_tab == "all":
        # همه پرداخت‌های مدیریت و شارژ کیف‌پول نمایندگان (حذف کامل فیش‌های ربات نماینده از دید ادمین)
        base_conditions.append("((reseller_id IS NULL OR reseller_id = 0) OR (reseller_id IS NOT NULL AND reseller_id > 0 AND (gateway = 'bundle_reseller' OR order_id LIKE 'R_BUNDLE%')))")
        if reseller_filter_id and reseller_filter_id.isdigit():
            base_conditions.append("reseller_id = ?")
            params.append(int(reseller_filter_id))

    if status_filter == "deleted":
        base_conditions.append("is_deleted = 1")
    else:
        base_conditions.append("(is_deleted = 0 OR is_deleted IS NULL)")
        if status_filter != "all":
            base_conditions.append("status = ?")
            params.append(status_filter)

    if search:
        base_conditions.append("(tracking_code LIKE ? OR username LIKE ? OR user_id LIKE ? OR order_id LIKE ? OR account_name LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%", f"%{search}%", f"%{search}%", f"%{search}%"])

    where_clause = " WHERE " + " AND ".join(base_conditions) if base_conditions else ""
    query = f"SELECT * FROM transactions {where_clause} ORDER BY created_at DESC LIMIT 300"
    raw_payment_list = conn.execute(query, params).fetchall()

    # شمارنده‌های آماری بر اساس تب منبع فعلی
    scope_cond = "((reseller_id IS NULL OR reseller_id = 0) OR (reseller_id IS NOT NULL AND reseller_id > 0 AND (gateway = 'bundle_reseller' OR order_id LIKE 'R_BUNDLE%')))"
    if source_tab == "admin":
        scope_cond = "(reseller_id IS NULL OR reseller_id = 0)"
    elif source_tab == "resellers":
        scope_cond = "(reseller_id IS NOT NULL AND reseller_id > 0 AND (gateway = 'bundle_reseller' OR order_id LIKE 'R_BUNDLE%'))"
        if reseller_filter_id and reseller_filter_id.isdigit():
            scope_cond += f" AND reseller_id = {int(reseller_filter_id)}"
    elif source_tab == "all":
        if reseller_filter_id and reseller_filter_id.isdigit():
            scope_cond = f"(reseller_id = {int(reseller_filter_id)} AND (gateway = 'bundle_reseller' OR order_id LIKE 'R_BUNDLE%'))"

    pending_count = conn.execute(f"SELECT COUNT(*) FROM transactions WHERE (is_deleted=0 OR is_deleted IS NULL) AND status='pending' AND {scope_cond}").fetchone()[0]
    approved_count = conn.execute(f"SELECT COUNT(*) FROM transactions WHERE (is_deleted=0 OR is_deleted IS NULL) AND status IN ('approved', 'completed') AND {scope_cond}").fetchone()[0]
    rejected_count = conn.execute(f"SELECT COUNT(*) FROM transactions WHERE (is_deleted=0 OR is_deleted IS NULL) AND status='rejected' AND {scope_cond}").fetchone()[0]
    revoked_count = conn.execute(f"SELECT COUNT(*) FROM transactions WHERE (is_deleted=0 OR is_deleted IS NULL) AND status='revoked' AND {scope_cond}").fetchone()[0]
    deleted_count = conn.execute(f"SELECT COUNT(*) FROM transactions WHERE is_deleted=1 AND {scope_cond}").fetchone()[0]

    # اضافه کردن لاگ‌های حسابرسی و غنی‌سازی مبدأ و نام مشتری برای هر تراکنش با تابع هوشمند
    payment_list = []
    for p in raw_payment_list:
        p_dict = dict(p)
        p_dict["audit_logs"] = db.get_transaction_audit_logs(p["id"])

        origin = determine_transaction_origin(p_dict)
        p_dict["source"] = origin

        renew_sub_id = p_dict.get("renew_sub_id")
        user_id = p_dict.get("user_id") or 0

        # استخراج نام و عنوان مشتری جهت نمایش
        if origin == "admin":
            cust_name = p_dict.get("account_name") or p_dict.get("username") or "مشتری پنل مدیریت"
            p_dict["customer_name"] = cust_name
        elif origin == "reseller":
            cust_name = p_dict.get("account_name") or p_dict.get("username") or f"مشتری نماینده #{p_dict.get('reseller_id') or '-'}"
            p_dict["customer_name"] = cust_name
        elif origin == "bundle":
            p_dict["customer_name"] = f"نماینده #{p_dict.get('reseller_id') or '-'}"
        elif origin == "portal":
            cust_name = p_dict.get("account_name") or p_dict.get("username")
            if not cust_name or cust_name in ("None", "null", "", "کاربر"):
                cust_name = f"مشتری پرتال #{renew_sub_id or p_dict['id']}"
            p_dict["customer_name"] = cust_name
        else:
            cust_name = p_dict.get("username")
            if not cust_name or cust_name in ("None", "null", "", "کاربر"):
                cust_name = f"کاربر {user_id}" if user_id else "کاربر تلگرام"
            p_dict["customer_name"] = cust_name

        payment_list.append(p_dict)

    conn.close()

    admin_count = sum(1 for p in payment_list if p.get("source") == "admin")
    portal_count = sum(1 for p in payment_list if p.get("source") == "portal")
    telegram_count = sum(1 for p in payment_list if p.get("source") == "telegram")
    bundle_count = sum(1 for p in payment_list if p.get("source") == "bundle")
    reseller_count = sum(1 for p in payment_list if p.get("source") == "reseller")

    resellers_list = db.get_all_resellers()
    cards = db.get_active_bank_cards()
    return render_template(
        "payments.html",
        payments=payment_list,
        status_filter=status_filter,
        source_tab=source_tab,
        reseller_filter_id=reseller_filter_id,
        resellers_list=resellers_list,
        search=search,
        cards=cards,
        admin_count=admin_count,
        portal_count=portal_count,
        telegram_count=telegram_count,
        bundle_count=bundle_count,
        reseller_count=reseller_count,
        counts={
            "pending": pending_count,
            "approved": approved_count,
            "rejected": rejected_count,
            "revoked": revoked_count,
            "deleted": deleted_count,
            "total": pending_count + approved_count + rejected_count + revoked_count
        }
    )


@app.route("/api/customers/search")
@admin_required
def api_customers_search():
    """جستجوی زنده مشتریان (شامل فعال، منقضی و سطل زباله) جهت انتساب رسید دستی"""
    q = request.args.get("q", "").strip()
    results = db.search_all_customers(query=q, limit=30)
    return jsonify({"success": True, "customers": results})


@app.route("/admin/payment/manual-add", methods=["POST"], endpoint="admin_payment_manual_add")
@app.route("/admin/payment/manual-add", methods=["POST"], endpoint="admin_add_manual_payment")
@admin_required
def admin_payment_manual_add():
    """ثبت رسید دستی پرداخت مشتری با قابلیت تسویه بدهی و آپلود تصویر فیش"""
    amount_raw = request.form.get("amount", "0").replace(",", "").strip()
    tracking_code = request.form.get("tracking_code", "").strip()
    card_number = request.form.get("card_number", "").strip()
    sub_id_raw = request.form.get("subscription_id", "").strip()
    customer_name = request.form.get("customer_name", "").strip()
    user_id_raw = request.form.get("user_id", "").strip()
    notes = request.form.get("notes", "").strip()
    date_str = request.form.get("payment_date", "").strip()
    settle_debt = request.form.get("settle_debt") == "on"
    p_status = request.form.get("status", "approved").strip()

    try:
        amount = int(amount_raw)
    except Exception:
        amount = 0

    if amount <= 0:
        flash("مبلغ پرداختی باید بزرگتر از صفر باشد.", "danger")
        return redirect(get_redirect_target(url_for("payments")))

    sub_id = int(sub_id_raw) if sub_id_raw.isdigit() else None
    user_id = int(user_id_raw) if user_id_raw.isdigit() else 0
    admin_name = session.get("admin_username") or session.get("username") or "مدیر"

    now = get_now_iso()
    created_at = date_str if date_str else now
    order_id = f"MANUAL-{int(time.time())}"

    # آپلود تصویر فیش
    receipt_file = request.files.get("receipt_image")
    receipt_image = None
    receipt_type = "manual_entry"
    if receipt_file and receipt_file.filename:
        try:
            sec_fn = secure_filename(receipt_file.filename)
            ext = Path(sec_fn).suffix.lower() or ".jpg"
            fn = f"receipt_{order_id}{ext}"
            RECEIPTS_DIR.mkdir(parents=True, exist_ok=True)
            save_path = RECEIPTS_DIR / fn
            receipt_file.save(save_path)
            receipt_image = fn
            receipt_type = "web_upload"
        except Exception as ex:
            logger.warning(f"Error saving manual receipt image: {ex}")

    plan_name = "ثبت دستی"
    reseller_id = None
    account_name = customer_name
    if sub_id:
        conn = db.get_connection()
        s_row = conn.execute("SELECT * FROM subscriptions WHERE id=?", (sub_id,)).fetchone()
        conn.close()
        if s_row:
            s_dict = dict(s_row)
            plan_name = s_dict.get("plan_name") or plan_name
            reseller_id = s_dict.get("reseller_id")
            account_name = s_dict.get("account_name") or account_name
            if not user_id:
                user_id = s_dict.get("telegram_id") or 0

            # تسویه بدهی اشتراک در صورت انتخاب
            if settle_debt and p_status in ("approved", "completed"):
                current_debt = s_dict.get("debt_amount") or 0
                new_debt = max(0, current_debt - amount)
                new_pstatus = "paid" if new_debt == 0 else "debtor"
                db.set_subscription_debt(sub_id, new_pstatus, new_debt, f"تسویه دستی با رسید {order_id} ({amount:,} تومان)")

    # ثبت در جدول transactions
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO transactions 
        (order_id, user_id, username, plan_name, amount, gateway, tracking_code, status, 
         receipt_image, receipt_photo_id, processed_by, processed_at, is_deleted, created_at, updated_at, reseller_id, account_name)
        VALUES (?, ?, ?, ?, ?, 'admin_manual', ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)
    """, (
        order_id, user_id, account_name or str(user_id), plan_name, amount,
        tracking_code or f"رسید دستی #{order_id}", p_status,
        receipt_image or "", receipt_type,
        admin_name, now if p_status in ('approved', 'completed') else None,
        created_at, now, reseller_id, account_name
    ))
    tx_id = cursor.lastrowid
    conn.commit()
    conn.close()

    # ثبت لاگ حسابرسی
    db.log_transaction_audit(tx_id, "ثبت رسید دستی", admin_name, f"مبلغ: {amount:,} ت | اشتراک #{sub_id or '-'} | تسویه بدهی: {'بله' if settle_debt else 'خیر'}")

    # ثبت سند در حسابداری
    if p_status in ("approved", "completed"):
        db.add_accounting_record(
            type="income",
            category="فروش اشتراک",
            title=f"رسید دستی: {account_name} ({order_id})",
            amount=amount,
            source="manual",
            description=f"ثبت دستی توسط {admin_name}. {notes}".strip(),
            date=created_at[:10]
        )

    flash(f"رسید دستی با شناسه {order_id} به مبلغ {amount:,} تومان با موفقیت ثبت شد.", "success")
    return redirect(get_redirect_target(url_for("payments")))


def fulfill_approved_transaction(order_id: str, ref_id: str = None, payer_info: dict = None, processed_by: str = "درگاه آنلاین (خودکار)") -> dict:
    """
    تایید و تحویل خودکار تراکنش پرداخت آنلاین و وب‌هوک (Idempotent)
    """
    conn = db.get_connection()
    tx_row = conn.execute("SELECT * FROM transactions WHERE order_id=?", (order_id,)).fetchone()
    conn.close()

    if not tx_row:
        # بررسی فاکتور هوشمند (در صورتی که پیامک بانک قبل از ارسال فیش ثبت شده باشد)
        inv = db.get_smart_invoice_by_order_id(order_id) if hasattr(db, "get_smart_invoice_by_order_id") else None
        if inv:
            now_iso = get_now_iso()
            sub_id = inv.get("sub_id") or 0
            plan_id = inv.get("plan_id")
            r_id = inv.get("reseller_id") or 0
            amt = inv.get("final_amount") or inv.get("base_amount") or 0
            plan = db.get_reseller_plan(r_id, plan_id) if r_id else None
            pname = plan.get("display_name") or plan.get("master_name", "پلن") if plan else "اشتراک"
            conn = db.get_connection()
            conn.execute("""
                INSERT OR REPLACE INTO transactions (
                    order_id, user_id, username, plan_name, amount, status, gateway,
                    tracking_code, reseller_id, is_renewal, renew_sub_id, account_name, source, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'pending', 'bank_sms', ?, ?, ?, ?, ?, 'bank_sms_auto', ?, ?)
            """, (
                order_id, 0, "مشتری بانکی", pname, amt,
                f"پیامک بانک {ref_id or ''}", r_id,
                1 if sub_id else 0, sub_id, f"sub_{sub_id}" if sub_id else "",
                now_iso, now_iso
            ))
            conn.commit()
            tx_row = conn.execute("SELECT * FROM transactions WHERE order_id=?", (order_id,)).fetchone()
            conn.close()

    if not tx_row:
        logger.warning(f"fulfill_approved_transaction: Transaction {order_id} not found.")
        return {"success": False, "error": "تراکنش یافت نشد."}

    tx = dict(tx_row)
    payment_id = tx["id"]

    # جلوگیری از تحویل تکراری (Idempotency)
    if tx.get("status") == "approved":
        return {"success": True, "already_approved": True, "tx": tx}

    now_iso = get_now_iso()
    amount = tx.get("amount", 0)
    pname = tx.get("plan_name", "اشتراک")
    r_id = tx.get("reseller_id")
    user_id = tx.get("user_id")

    # ۱. حالت خرید بسته پیش‌خرید اعتباری نماینده
    if tx.get("gateway") == "bundle_reseller" or str(tx.get("order_id", "")).startswith("R_BUNDLE"):
        res = db.apply_reseller_bundle_credit(r_id, amount, pname, payment_id)
        credit_added = res.get("credit_added", amount) if isinstance(res, dict) else amount
        new_balance = res.get("new_balance", 0) if isinstance(res, dict) else 0

        conn = db.get_connection()
        conn.execute(
            "UPDATE transactions SET status='approved', ref_id=?, processed_by=?, processed_at=?, updated_at=? WHERE id=?",
            (str(ref_id or order_id), processed_by, now_iso, now_iso, payment_id)
        )
        conn.commit()
        conn.close()

        if r_id:
            db.add_reseller_notification(
                reseller_id=r_id,
                title="تایید خودکار خرید بسته اعتباری (درگاه)",
                message=f"پرداخت آنلاین شما برای «{pname}» به مبلغ {amount:,} تومان با موفقیت تایید شد و مبلغ {credit_added:,} تومان به کیف پول شما واریز گردید.",
                type="success"
            )

        reseller = db.get_reseller(r_id) if r_id else None
        if reseller and reseller.get("telegram_id"):
            tg_msg = (
                f"✅ <b>پرداخت آنلاین شما با موفقیت تایید شد!</b>\n\n"
                f"📦 <b>عنوان بسته:</b> {pname}\n"
                f"💳 <b>مبلغ پرداختی:</b> {amount:,} تومان\n"
                f"🎁 <b>مبلغ شارژ شده:</b> {credit_added:,} تومان\n"
                f"💰 <b>موجودی جدید کیف پول:</b> {new_balance:,} تومان\n"
                f"🆔 <b>کد پیگیری / ارجاع:</b> <code>{ref_id or order_id}</code>"
            )
            try:
                send_telegram_msg(reseller["telegram_id"], tg_msg)
            except Exception as e:
                logger.error(f"Error sending telegram msg to reseller {r_id}: {e}")

        return {"success": True, "type": "reseller_bundle"}

    # ۲. حالت خرید، تمدید اشتراک یا تسویه بدهی توسط کاربر
    is_debt_settlement = bool(tx.get("is_debt_settlement")) or (smart_inv and bool(smart_inv.get("is_debt_settlement"))) or ("تسویه بدهی" in str(pname))
    is_renewal = bool(tx.get("is_renewal"))
    renew_sub_id = tx.get("renew_sub_id")
    plans = get_plans_dict()
    selected_plan = next((p for p in plans.values() if p["name"] == pname), None)
    data_limit = selected_plan["data_limit"] if selected_plan else 30
    duration = selected_plan["duration"] if selected_plan else 30
    account_name = tx.get("account_name") or f"tg_{user_id}"
    user_uuid = ""
    smart_inv = db.get_smart_invoice_by_order_id(order_id)
    instant_activation = True
    if smart_inv and smart_inv.get("instant_activation") is not None:
        instant_activation = bool(smart_inv["instant_activation"])

    if is_debt_settlement and renew_sub_id:
        target_sub = db.get_subscription(renew_sub_id)
        if target_sub:
            db.clear_subscription_debt(renew_sub_id, reseller_id=target_sub.get("reseller_id"), settled_by=f"درگاه خودکار ({processed_by})")
            logger.info(f"Debt settled for sub #{renew_sub_id} via approved transaction {order_id}")
    elif is_renewal and renew_sub_id:
        target_sub = db.get_subscription(renew_sub_id)
        if not target_sub and user_id:
            user_subs = db.get_user_subscriptions(user_id)
            target_sub = next((s for s in user_subs if s["id"] == renew_sub_id), None)

        if target_sub:
            user_uuid = target_sub.get("hidify_uuid", "")
            old_limit = float(target_sub.get("data_limit") or 0)
            old_used = float(target_sub.get("data_used") or 0)
            old_plan_name = target_sub.get("plan_name") or ""

            if not instant_activation:
                # بسته به صف رزرو اضافه می‌شود تا پس از اتمام بسته فعلی فعال شود
                db.add_to_subscription_queue(
                    subscription_id=renew_sub_id,
                    plan_id="renewal_plan",
                    plan_name=pname,
                    data_limit=float(data_limit),
                    duration=int(duration),
                    cost=amount,
                    reseller_id=target_sub.get("reseller_id") or r_id,
                    telegram_id=user_id or target_sub.get("telegram_id") or 0,
                    hidify_uuid=user_uuid,
                    note=f"رزرو شده از طریق پورتال تمدید مشتری (سفارش {order_id})"
                )
                logger.info(f"Subscription {renew_sub_id} renewal queued successfully (instant_activation=False).")
            else:
                renew_res = hidify_sync_renew_user(user_uuid, float(data_limit), int(duration))
                final_limit = renew_res.get("new_limit", data_limit)
                final_days = renew_res.get("new_days", duration)
                renewal_type = renew_res.get("renewal_type", "fallback")
                final_plan_name = pname if renewal_type == "reset_and_replaced" else (old_plan_name if old_limit > float(data_limit) else pname)
                final_used = 0 if renewal_type == "reset_and_replaced" else old_used

                db.save_subscription_history(
                    subscription_id=renew_sub_id,
                    telegram_id=user_id or target_sub.get("telegram_id") or 0,
                    hidify_uuid=user_uuid,
                    account_name=target_sub.get("account_name") or account_name,
                    plan_name=old_plan_name or pname,
                    previous_usage_gb=old_used,
                    previous_limit_gb=old_limit,
                    period_days=target_sub.get("duration") or duration,
                    renewal_type=renewal_type,
                    reseller_id=target_sub.get("reseller_id"),
                    plan_price=amount,
                    cost_paid=amount
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
        # ساخت اشتراک جدید
        res = hidify_sync_create_user(name=account_name, usage_limit_gb=data_limit, package_days=duration, comment=str(user_id))
        user_uuid = res.get("uuid", "")
        if user_uuid:
            db.save_subscription(
                telegram_id=user_id,
                hidify_uuid=user_uuid,
                plan_id="custom",
                plan_name=pname,
                data_limit=data_limit,
                duration=duration,
                status="active",
                account_name=account_name,
                reseller_id=r_id
            )

    conn = db.get_connection()
    conn.execute(
        "UPDATE transactions SET status='approved', ref_id=?, processed_by=?, processed_at=?, updated_at=? WHERE id=?",
        (str(ref_id or order_id), processed_by, now_iso, now_iso, payment_id)
    )
    conn.commit()
    conn.close()

    # پاداش رفرال
    if user_id:
        try:
            db.complete_referral(user_id)
        except Exception:
            pass

    # پردازش و واریز کش‌بک کاربران VIP
    if user_id:
        try:
            vip_info = db.get_user_vip_info(user_id)
            if vip_info.get("is_vip") and vip_info.get("cashback_percent", 0) > 0:
                paid_amount = int(amount or 0)
                cb_rate = vip_info.get("cashback_percent", 10)
                cashback_val = int((paid_amount * cb_rate) / 100)
                if cashback_val > 0:
                    cb_res = db.add_wallet_balance(
                        user_id,
                        cashback_val,
                        f"هدیه کش‌بک خرید ویژه VIP ({cb_rate}%)",
                        ref_id=str(order_id or payment_id),
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
                    except Exception:
                        pass
        except Exception as e_cb:
            logger.error(f"Error processing VIP cashback: {e_cb}")

    # بررسی ارتقای خودکار کاربر به VIP
    if user_id:
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
                except Exception:
                    pass
        except Exception as e_up:
            logger.error(f"Error checking VIP auto-upgrade: {e_up}")

    # ارسال کارت و بارکد اتصال به تلگرام مشتری
    h_url = get_hiddify_url()
    u_proxy = get_user_proxy()
    if user_uuid and h_url and user_id:
        sub_url = f"{h_url}/{u_proxy}/{user_uuid}/"
        card_title = "🎉 **پرداخت آنلاین تایید شد و اشتراک شما فعال گردید!**" if not is_renewal else "🔄 **اشتراک شما با موفقیت تمدید شد!**"
        card_details = f"📋 پلن: **{pname}**\n📊 حجم: **{data_limit} گیگابایت**\n⏰ مدت: **{duration} روز**"
        try:
            send_subscription_card_sync(user_id, sub_url, card_title, card_details)
        except Exception as e_card:
            logger.error(f"Error sending subscription card: {e_card}")

    return {"success": True, "type": "subscription", "uuid": user_uuid}


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

    account_name = tx["account_name"] or (f"tg_{user_id}" if user_id else f"web_{payment_id}")
    user_uuid = ""
    target_sub = None

    if is_renewal and renew_sub_id:
        target_sub = db.get_subscription(renew_sub_id)
        if not target_sub and user_id:
            user_subs = db.get_user_subscriptions(user_id)
            target_sub = next((s for s in user_subs if s["id"] == renew_sub_id), None)
        if target_sub:
            user_uuid = target_sub.get("hidify_uuid", "")
            old_limit = float(target_sub.get("data_limit") or 0)
            old_used = float(target_sub.get("data_used") or 0)
            old_plan_name = target_sub.get("plan_name") or ""
            target_account_name = target_sub.get("account_name") or tx.get("account_name") or account_name

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
                telegram_id=user_id or target_sub.get("telegram_id") or 0,
                hidify_uuid=user_uuid,
                account_name=target_account_name,
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
        account_name = tx["account_name"] or (f"tg_{user_id}" if user_id else f"web_{payment_id}")
        res = hidify_sync_create_user(name=account_name, usage_limit_gb=data_limit, package_days=duration, comment=str(user_id or f"WEB:{payment_id}"))
        user_uuid = res.get("uuid", "")
        if user_uuid:
            db.save_subscription(
                telegram_id=user_id or 0,
                hidify_uuid=user_uuid,
                plan_id="custom",
                plan_name=plan_name,
                data_limit=data_limit,
                duration=duration,
                status="active",
                account_name=account_name
            )

    # اگر فیش مربوط به پیش‌فاکتور هوشمند پرتال بود، وضعیت پیش‌فاکتور را پرداخت‌شده کنیم
    order_id = str(tx.get("order_id") or "")
    if order_id.startswith("INV"):
        try:
            db.mark_smart_invoice_paid(order_id, tracking_code=str(payment_id))
        except Exception as e_inv:
            logger.error(f"Error marking invoice {order_id} paid: {e_inv}")

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

    # پاداش رفرال و کش‌بک تنها برای کاربران دارای اکانت تلگرام (user_id > 0)
    if user_id and int(user_id) > 0:
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
            try:
                send_subscription_card_sync(user_id, sub_url, card_title, card_details)
            except Exception as e_card:
                logger.error(f"Error sending subscription card to {user_id}: {e_card}")

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

        # اگر فیش مربوط به پیش‌فاکتور هوشمند پرتال بود، وضعیت پیش‌فاکتور را رد شده کنیم
        order_id = str(tx.get("order_id") or "")
        if order_id.startswith("INV"):
            try:
                db.mark_smart_invoice_rejected(order_id, reason=reason)
            except Exception as e_inv:
                logger.error(f"Error marking invoice {order_id} rejected: {e_inv}")

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
            # ارسال پیام رد به کاربر عادی تلگرام
            user_id = tx.get("user_id")
            if user_id and int(user_id) > 0:
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

    return redirect(request.referrer or url_for("payments"))


@app.route("/admin/payments/bulk", methods=["POST"])
@admin_required
def admin_payments_bulk():
    """عملیات گروهی روی پرداخت‌ها و فیش‌های واریزی توسط مدیر (تایید، رد، حذف)"""
    action = request.form.get("bulk_action")
    raw_ids = request.form.getlist("selected_ids") or [x.strip() for x in request.form.get("selected_ids_str", "").split(",") if x.strip()]
    payment_ids = []
    for p_id in raw_ids:
        try:
            val = int(str(p_id).strip())
            if val > 0:
                payment_ids.append(val)
        except (ValueError, TypeError):
            continue

    if not payment_ids:
        flash("هیچ پرداختی برای انجام عملیات انتخاب نشده است.", "warning")
        return redirect(url_for("payments"))

    success_count = 0
    admin_name = session.get("name") or session.get("username") or "مدیر ارشد"
    admin_id = session.get("admin_id")

    for pid in payment_ids:
        if action == "approve":
            try:
                conn = db.get_connection()
                tx_row = conn.execute("SELECT * FROM transactions WHERE id=?", (pid,)).fetchone()
                conn.close()
                if tx_row and tx_row["status"] == "pending":
                    tx = dict(tx_row)
                    user_id = tx["user_id"] or 0
                    plan_name = tx["plan_name"]
                    is_renewal = bool(tx.get("is_renewal"))
                    renew_sub_id = tx.get("renew_sub_id")
                    plans = get_plans_dict()
                    selected_plan = next((p for p in plans.values() if p["name"] == plan_name), None)
                    if not selected_plan and plans:
                        selected_plan = list(plans.values())[0]

                    data_limit = selected_plan["data_limit"] if selected_plan else 30
                    duration = selected_plan["duration"] if selected_plan else 30

                    user_uuid = None
                    if is_renewal:
                        target_sub = db.get_subscription(renew_sub_id) if renew_sub_id else None
                        if not target_sub and user_id:
                            conn = db.get_connection()
                            sub_row = conn.execute("SELECT * FROM subscriptions WHERE user_id=? AND status='active' ORDER BY id DESC LIMIT 1", (user_id,)).fetchone()
                            conn.close()
                            if sub_row:
                                target_sub = dict(sub_row)
                        if target_sub and target_sub.get("hidify_uuid"):
                            user_uuid = target_sub["hidify_uuid"]
                            hidify_sync_renew_user(user_uuid, data_limit, duration)
                            db.update_subscription(target_sub["id"], status="active")
                    else:
                        account_name = tx.get("account_name") or (f"user_{user_id}_{int(time.time()) % 10000}" if user_id else f"web_{pid}")
                        h_res = hidify_sync_create_user(name=account_name, usage_limit_gb=data_limit, package_days=duration, comment=f"TG: {user_id}" if user_id else f"WEB:{pid}")
                        user_uuid = h_res.get("uuid") if h_res else None
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

                    # اگر پیش‌فاکتور هوشمند پرتال بود
                    order_id = str(tx.get("order_id") or "")
                    if order_id.startswith("INV"):
                        try:
                            db.mark_smart_invoice_paid(order_id, tracking_code=str(pid))
                        except Exception:
                            pass

                    now_iso = get_now_iso()
                    conn = db.get_connection()
                    conn.execute("UPDATE transactions SET status='approved', processed_by=?, processed_at=?, updated_at=? WHERE id=?", (admin_name, now_iso, now_iso, pid))
                    conn.commit()
                    conn.close()

                    if user_uuid and user_id and int(user_id) > 0:
                        h_url = get_hiddify_url()
                        u_proxy = get_user_proxy()
                        if h_url:
                            sub_url = f"{h_url}/{u_proxy}/{user_uuid}/"
                            card_title = "🎉 **اشتراک شما تایید و فعال شد!**"
                            card_details = f"📋 پلن: **{plan_name}**\n📊 حجم: **{data_limit} گیگابایت**\n⏰ مدت: **{duration} روز**"
                            try:
                                send_subscription_card_sync(user_id, sub_url, card_title, card_details)
                            except Exception:
                                pass
                    success_count += 1
            except Exception as e:
                logger.error(f"Error bulk approving payment {pid}: {e}")
        elif action == "reject":
            try:
                conn = db.get_connection()
                tx_row = conn.execute("SELECT * FROM transactions WHERE id=?", (pid,)).fetchone()
                if tx_row and str(tx_row["order_id"] or "").startswith("INV"):
                    try:
                        db.mark_smart_invoice_rejected(str(tx_row["order_id"]), reason="رد توسط مدیریت در عملیات گروهی")
                    except Exception:
                        pass
                now_iso = get_now_iso()
                conn.execute("UPDATE transactions SET status='rejected', rejection_reason='رد توسط مدیریت در عملیات گروهی', processed_by=?, processed_at=?, updated_at=? WHERE id=?", (admin_name, now_iso, now_iso, pid))
                conn.commit()
                conn.close()
                success_count += 1
            except Exception as e:
                logger.error(f"Error bulk rejecting payment {pid}: {e}")
        elif action == "delete":
            try:
                conn = db.get_connection()
                conn.execute("DELETE FROM transactions WHERE id=?", (pid,))
                conn.commit()
                conn.close()
                success_count += 1
            except Exception as e:
                logger.error(f"Error bulk deleting payment {pid}: {e}")

    if action == "approve":
        flash(f"✅ تعداد {success_count} پرداخت با موفقیت تایید و فعال‌سازی شدند.", "success")
    elif action == "reject":
        flash(f"✅ تعداد {success_count} فیش پرداخت رد شدند.", "info")
    elif action == "delete":
        flash(f"✅ تعداد {success_count} رکورد پرداخت با موفقیت حذف شدند.", "success")
    else:
        flash(f"عملیات برای {success_count} مورد انجام شد.", "info")

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

    return redirect(request.referrer or url_for("payments"))


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
    """بررسی لحظه‌ای اعلان‌های جدید (پرداخت‌های معلق و تفکیک تیکت‌های باز مشتریان و نمایندگان)"""
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, user_id, username, amount, plan_name, tracking_code, created_at 
        FROM transactions 
        WHERE status='pending' AND ((reseller_id IS NULL OR reseller_id = 0) OR gateway = 'bundle_reseller' OR order_id LIKE 'R_BUNDLE%')
        ORDER BY created_at DESC LIMIT 10
    """)
    pending_payments = [dict(p) for p in cursor.fetchall()]

    # تیکت‌های باز مشتریان
    cursor.execute("""
        SELECT id, telegram_id, subject, message, created_at 
        FROM support_tickets 
        WHERE status='open' AND (reseller_id IS NULL OR reseller_id = 0) AND (ticket_type NOT IN ('reseller_to_admin', 'quota_change') OR ticket_type IS NULL)
        ORDER BY created_at DESC LIMIT 10
    """)
    customer_tickets = [dict(t) for t in cursor.fetchall()]

    # تیکت‌های باز نمایندگان
    cursor.execute("""
        SELECT t.id, t.telegram_id, t.subject, t.message, t.reseller_id, t.ticket_type, t.created_at, r.name as reseller_name
        FROM support_tickets t
        LEFT JOIN resellers r ON t.reseller_id = r.id
        WHERE t.status='open' AND (t.ticket_type IN ('reseller_to_admin', 'quota_change') OR (t.reseller_id > 0 AND t.target_role = 'admin'))
        ORDER BY t.created_at DESC LIMIT 10
    """)
    reseller_tickets = [dict(t) for t in cursor.fetchall()]
    conn.close()

    return jsonify({
        "pending_payments_count": len(pending_payments),
        "open_customer_tickets_count": len(customer_tickets),
        "open_reseller_tickets_count": len(reseller_tickets),
        "open_tickets_count": len(customer_tickets) + len(reseller_tickets),
        "total_alerts": len(pending_payments) + len(customer_tickets) + len(reseller_tickets),
        "pending_payments": pending_payments,
        "customer_tickets": customer_tickets,
        "reseller_tickets": reseller_tickets
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
    """لیست مشتریان و اشتراک‌ها همراه با وضعیت آنلاین، تب بدهکاران، فیلتر نماینده و نشان وضعیت تیکت با صفحه‌بندی هوشمند"""
    sync_hiddify_online_users()
    conn = db.get_connection()
    status_filter = request.args.get("status", "all")
    reseller_filter_id = request.args.get("reseller_id", "")
    search = request.args.get("search", "").strip()

    # پارامترهای صفحه‌بندی
    try:
        page = max(1, int(request.args.get("page", 1)))
    except (ValueError, TypeError):
        page = 1

    per_page_param = request.args.get("per_page", "50").strip()
    if per_page_param.lower() in ("all", "همه", "0", "-1"):
        per_page = 0
        per_page_str = "all"
    else:
        try:
            per_page = max(1, int(per_page_param))
            per_page_str = str(per_page)
        except (ValueError, TypeError):
            per_page = 50
            per_page_str = "50"

    base_conditions = []
    params = []

    if status_filter == "deleted":
        base_conditions.append("is_deleted = 1")
    elif status_filter == "queue":
        base_conditions.append("(is_deleted = 0 OR is_deleted IS NULL)")
        base_conditions.append("id IN (SELECT subscription_id FROM subscription_queue WHERE status = 'pending')")
    else:
        base_conditions.append("(is_deleted = 0 OR is_deleted IS NULL)")

    if status_filter == "online":
        base_conditions.append("is_online = 1")
    elif status_filter == "vip":
        base_conditions.append("is_vip = 1")
    elif status_filter == "debtors":
        base_conditions.append("(payment_status IN ('unpaid', 'debtor') OR debt_amount > 0 OR is_credit = 1)")
    elif status_filter == "active":
        base_conditions.append("status = 'active'")
    elif status_filter == "expired":
        base_conditions.append("status != 'active'")
    elif status_filter == "direct":
        base_conditions.append("(reseller_id IS NULL OR reseller_id = 0)")
    elif status_filter == "resellers":
        base_conditions.append("(reseller_id IS NOT NULL AND reseller_id > 0)")

    if reseller_filter_id and reseller_filter_id.isdigit():
        base_conditions.append("reseller_id = ?")
        params.append(int(reseller_filter_id))

    if search:
        # تبدیل ارقام فارسی و عربی به انگلیسی برای جستجوی دقیق شماره‌ها و شناسه‌ها
        persian_digits = "۰۱۲۳۴۵۶۷۸۹"
        arabic_digits = "٠١٢٣٤٥٦٧٨٩"
        clean_search = search.strip()
        norm_search = clean_search
        for i in range(10):
            norm_search = norm_search.replace(persian_digits[i], str(i)).replace(arabic_digits[i], str(i))
        
        raw_pattern = f"%{clean_search}%"
        norm_pattern = f"%{norm_search}%"
        clean_no_hash = norm_search.lstrip("#")
        id_pattern = f"%{clean_no_hash}%"

        base_conditions.append("""(
            account_name LIKE ? 
            OR account_name LIKE ?
            OR hidify_uuid LIKE ? 
            OR phone_number LIKE ? 
            OR phone_number LIKE ?
            OR plan_name LIKE ? 
            OR CAST(telegram_id AS TEXT) LIKE ? 
            OR account_comment LIKE ? 
            OR debt_notes LIKE ? 
            OR CAST(id AS TEXT) LIKE ?
            OR telegram_id IN (SELECT telegram_id FROM users WHERE username LIKE ? OR username LIKE ? OR phone_number LIKE ?)
        )""")
        params.extend([
            raw_pattern, norm_pattern,
            norm_pattern,
            raw_pattern, norm_pattern,
            raw_pattern,
            norm_pattern,
            raw_pattern,
            raw_pattern,
            id_pattern,
            raw_pattern, f"%{clean_search.lstrip('@')}%", norm_pattern
        ])

    where_clause = " WHERE " + " AND ".join(base_conditions) if base_conditions else ""
    
    # محاسبه تعداد کل موارد
    count_query = f"SELECT COUNT(*) FROM subscriptions {where_clause}"
    total_count = conn.execute(count_query, params).fetchone()[0]

    sort_by = request.args.get("sort", "newest").strip()
    order_clause = "created_at DESC"
    if status_filter == "deleted":
        order_clause = "deleted_at DESC"
        if sort_by == "oldest":
            order_clause = "deleted_at ASC"
        elif sort_by == "days_left_asc":
            order_clause = "deleted_at ASC"
        elif sort_by == "usage_desc":
            order_clause = "data_used DESC"
        elif sort_by == "limit_desc":
            order_clause = "data_limit DESC"
        elif sort_by == "name_asc":
            order_clause = "account_name COLLATE NOCASE ASC"

    if per_page == 0 or per_page >= 100000:
        total_pages = 1
        page = 1
        query = f"SELECT * FROM subscriptions {where_clause} ORDER BY {order_clause}"
        sub_list = conn.execute(query, params).fetchall()
    else:
        total_pages = max(1, math.ceil(total_count / per_page)) if total_count > 0 else 1
        if page > total_pages:
            page = total_pages
        offset = (page - 1) * per_page
        query = f"SELECT * FROM subscriptions {where_clause} ORDER BY {order_clause} LIMIT ? OFFSET ?"
        sub_list = conn.execute(query, params + [per_page, offset]).fetchall()

    conn.close()

    tickets_map = db.get_customers_ticket_status_map()
    subscriptions_with_refund = []
    now_naive_val = get_now_naive()
    restore_window = float(db.get_refund_settings().get("restore_window_days", 7))
    resellers_list = db.get_all_resellers()
    resellers_map = {r["id"]: r for r in resellers_list}
    admins_map = {a["username"].lower(): a for a in db.get_admin_users() if a.get("username")}

    for s in sub_list:
        s_dict = enrich_subscription_details(s, resellers_map=resellers_map, admins_map=admins_map)
        s_dict["refund_info"] = db.calculate_customer_refund(s["id"])

        if status_filter == "deleted":
            del_str = s_dict.get("deleted_at")
            days_passed = 0.0
            if del_str:
                try:
                    del_dt = datetime.fromisoformat(del_str.replace("Z", "+00:00")).replace(tzinfo=None)
                    days_passed = round((now_naive_val - del_dt).total_seconds() / 86400.0, 1)
                except Exception:
                    days_passed = 0.0
            s_dict["days_passed"] = days_passed
            s_dict["days_left"] = max(0.0, round(restore_window - days_passed, 1))
        
        # وضعیت هوشمند تیکت مشتری
        tg_id = s_dict.get("telegram_id")
        s_dict["ticket_info"] = tickets_map.get(tg_id) if tg_id else None
        subscriptions_with_refund.append(s_dict)
    
    online_stats = db.get_online_users_stats()
    debtor_count = db.get_debtor_count()
    plans = get_plans_dict()
    single_link_template = get_single_link_template(db)

    start_item = ((page - 1) * per_page + 1) if (total_count > 0 and per_page > 0) else (1 if total_count > 0 else 0)
    end_item = min(page * per_page, total_count) if (total_count > 0 and per_page > 0) else total_count

    deleted_count = 0
    try:
        c_del = db.get_connection()
        deleted_count = c_del.execute("SELECT COUNT(*) FROM subscriptions WHERE is_deleted = 1").fetchone()[0]
        c_del.close()
    except Exception:
        pass

    queue_count = db.get_pending_queue_count()
    all_pending_queue = db.get_all_pending_queue_items()

    return render_template(
        "subscriptions.html",
        subscriptions=subscriptions_with_refund,
        status_filter=status_filter,
        reseller_filter_id=reseller_filter_id,
        resellers_list=resellers_list,
        plans=plans,
        search=search,
        sort_by=sort_by,
        total_count=total_count,
        page=page,
        per_page=per_page,
        per_page_str=per_page_str,
        total_pages=total_pages,
        start_item=start_item,
        end_item=end_item,
        online_count=online_stats["online_count"],
        online_stats=online_stats,
        debtor_count=debtor_count,
        deleted_count=deleted_count,
        queue_count=queue_count,
        all_pending_queue=all_pending_queue,
        panel_url=get_hiddify_url(),
        user_proxy=get_user_proxy(),
        single_link_template=single_link_template
    )


@app.route("/admin/subscription/<int:sub_id>/renew", methods=["POST"])
@permission_required("sub_manage")
def admin_subscription_renew(sub_id: int):
    """تمدید اشتراک مشتری توسط مدیریت با انتخاب پلن یا حجم/روز دلخواه"""
    conn = db.get_connection()
    sub_row = conn.execute("SELECT * FROM subscriptions WHERE id=?", (sub_id,)).fetchone()
    conn.close()
    if not sub_row:
        flash("اشتراک مورد نظر یافت نشد.", "danger")
        return redirect(get_redirect_target("subscriptions"))

    sub = dict(sub_row)
    plan_key = request.form.get("plan_id", "").strip()
    custom_limit_raw = request.form.get("custom_limit", "").strip()
    custom_duration_raw = request.form.get("custom_duration", "").strip()

    plans = get_plans_dict()
    if custom_limit_raw and custom_duration_raw:
        try:
            data_limit = float(custom_limit_raw)
            duration = int(custom_duration_raw)
            plan_name = f"{data_limit} گیگ {duration} روزه"
            plan_key = "custom"
            cost_paid = 0
        except ValueError:
            flash("مقادیر وارد شده برای حجم یا مدت نامعتبر است.", "danger")
            return redirect(get_redirect_target("subscriptions"))
    elif plan_key and plan_key in plans:
        plan = plans[plan_key]
        plan_name = plan.get("name", "تمدید اشتراک")
        data_limit = float(plan.get("data_limit", 30))
        duration = int(plan.get("duration", 30))
        cost_paid = int(plan.get("price", 0))
    else:
        data_limit = float(sub.get("data_limit") or 30)
        duration = int(sub.get("duration") or 30)
        plan_name = sub.get("plan_name") or f"{data_limit} گیگ {duration} روزه"
        plan_key = sub.get("plan_id") or "custom"
        cost_paid = 0

    # دریافت و افزودن حجم هدیه (Gift Traffic)
    gift_traffic = 0.0
    try:
        gift_traffic = max(0.0, float(request.form.get("gift_traffic_gb", 0) or 0))
    except (ValueError, TypeError):
        gift_traffic = 0.0

    if gift_traffic > 0:
        data_limit += gift_traffic
        plan_name += f" (+{gift_traffic}GB هدیه)"

    is_free = request.form.get("is_free") in ("on", "1", "true")
    if is_free:
        cost_paid = 0

    payment_status = request.form.get("payment_status", "paid").strip()
    debt_amount_raw = request.form.get("debt_amount", "").strip()
    renewal_notes = request.form.get("renewal_notes", "").strip()

    old_debt = int(sub.get("debt_amount") or 0)
    if payment_status in ("unpaid", "debtor"):
        this_period_debt = int(debt_amount_raw) if debt_amount_raw.isdigit() else cost_paid
        debt_status = "unpaid"
        total_debt = old_debt + this_period_debt
    else:
        this_period_debt = 0
        debt_status = "paid"
        total_debt = 0

    instant_activate = bool(request.form.get("instant_activate"))

    if instant_activate:
        # ۱. تمدید آنی در سرور هیدیفای با ریست کامل حجم (0) و روزها
        renewal_res = {"renewal_type": "reset_and_replaced"}
        if sub.get("hidify_uuid"):
            try:
                renewal_res = hidify_sync_renew_user(sub["hidify_uuid"], data_limit, duration, force_instant=True)
            except Exception as e:
                logger.error(f"Admin renew Hiddify error: {e}")

        # ۲. به‌روزرسانی آنی در دیتابیس (صفر کردن مصرف، تنظیم تاریخ‌ها و وضعیت مالی بدهی/تسویه)
        now = get_now_iso()
        now_naive = get_now_naive()
        new_start_date = now_naive.strftime("%Y-%m-%d")
        new_expire_date = (now_naive + timedelta(days=duration)).isoformat()
        debt_created = now if debt_status == "unpaid" else None

        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE subscriptions
            SET plan_id=?, plan_name=?, data_limit=?, data_used=0, duration=?,
                start_date=?, expire_date=?, status='active', updated_at=?, cost_paid=?,
                payment_status=?, debt_amount=?, debt_notes=?,
                debt_created_at = CASE WHEN ? = 'unpaid' THEN COALESCE(debt_created_at, ?) ELSE NULL END
            WHERE id=?
        """, (plan_key, plan_name, data_limit, duration, new_start_date, new_expire_date, now, 0 if debt_status == "unpaid" else cost_paid,
              debt_status, total_debt, renewal_notes or None, debt_status, debt_created, sub_id))
        conn.commit()
        conn.close()

        if debt_status == "unpaid":
            try:
                db.add_customer_debt_record(
                    subscription_id=sub_id,
                    account_name=sub.get("account_name"),
                    telegram_id=sub.get("telegram_id") or 0,
                    reseller_id=sub.get("reseller_id"),
                    action_type="renew",
                    plan_name=plan_name,
                    amount=this_period_debt,
                    notes=renewal_notes or "ثبت بدهی هنگام تمدید توسط مدیریت",
                    created_by=session.get("username") or "admin",
                    previous_debt=old_debt
                )
            except Exception as ex_rec:
                logger.error(f"Error recording debt record in admin renew: {ex_rec}")
        else:
            db.clear_subscription_debt(sub_id, settled_by=session.get('username') or 'admin')

        # ۳. ثبت در تاریخچه دوره‌های اشتراک
        try:
            db.log_subscription_history(
                subscription_id=sub_id,
                telegram_id=sub.get("telegram_id") or 0,
                hidify_uuid=sub.get("hidify_uuid") or "",
                account_name=sub.get("account_name") or "",
                plan_name=f"{plan_name} (تمدید رایگان)" if is_free else (f"{plan_name} (بدهکار)" if debt_status == "unpaid" else plan_name),
                previous_usage_gb=sub.get("data_used") or 0,
                previous_limit_gb=sub.get("data_limit") or 0,
                period_days=duration,
                renewal_type="reset_and_replaced",
                reseller_id=sub.get("reseller_id"),
                cost_paid=0 if debt_status == "unpaid" else cost_paid
            )
        except Exception as ex:
            logger.error(f"Error logging subscription history in admin renew: {ex}")

        free_tag = " (تمدید رایگان با مبلغ ۰ تومان)" if is_free else ""
        debt_tag = f" (مشتری بدهکار ثبت شد: {this_period_debt:,} ت | مجموع بدهی: {total_debt:,} ت)" if debt_status == "unpaid" else " (وضعیت مالی: تسویه شده)"
        flash(f"اشتراک «{sub.get('account_name')}» با موفقیت به صورت آنی تمدید شد ({data_limit} GB - {duration} روز){free_tag}{debt_tag} و حجم و روز آن ریست گردید.", "success")
    else:
        # ۴. قرار دادن در صف تمدید هوشمند (رزرو برای پس از اتمام بسته)
        if debt_status == "unpaid":
            try:
                db.add_customer_debt_record(
                    subscription_id=sub_id,
                    account_name=sub.get("account_name"),
                    telegram_id=sub.get("telegram_id") or 0,
                    reseller_id=sub.get("reseller_id"),
                    action_type="renew",
                    plan_name=plan_name,
                    amount=this_period_debt,
                    notes=renewal_notes or "ثبت بدهی تمدید در صف توسط مدیریت",
                    created_by=session.get("username") or "admin",
                    previous_debt=old_debt
                )
            except Exception as ex_rec:
                logger.error(f"Error recording debt record in queue renew: {ex_rec}")
        else:
            db.clear_subscription_debt(sub_id, settled_by=session.get('username') or 'admin')
            if renewal_notes:
                conn = db.get_connection()
                conn.execute("UPDATE subscriptions SET debt_notes=? WHERE id=?", (renewal_notes, sub_id))
                conn.commit()
                conn.close()
        q_res = db.add_to_subscription_queue(
            subscription_id=sub_id,
            plan_id=plan_key,
            plan_name=f"{plan_name} (رایگان)" if is_free else (f"{plan_name} (بدهکار)" if debt_status == "unpaid" else plan_name),
            data_limit=data_limit,
            duration=duration,
            cost=0 if debt_status == "unpaid" else cost_paid,
            reseller_id=sub.get("reseller_id"),
            telegram_id=sub.get("telegram_id") or 0,
            hidify_uuid=sub.get("hidify_uuid") or "",
            note="تمدید رایگان در صف توسط مدیریت" if is_free else ("تمدید بدهکار در صف توسط مدیریت" if debt_status == "unpaid" else "تمدید در صف توسط مدیریت")
        )
        if q_res.get("success"):
            free_tag = " (رایگان با مبلغ ۰ تومان)" if is_free else ""
            debt_tag = f" (مشتری بدهکار ثبت شد: {this_period_debt:,} ت | مجموع بدهی: {total_debt:,} ت)" if debt_status == "unpaid" else ""
            flash(f"بسته تمدیدی «{plan_name}» برای اشتراک «{sub.get('account_name')}»{free_tag}{debt_tag} در صف رزرو قرار گرفت و پس از مصرف ۹۹٪ یا رسیدن به روز پایانی به صورت خودکار فعال خواهد شد.", "info")
        else:
            flash(f"خطا در افزودن بسته به صف: {q_res.get('error')}", "danger")

    # ثبت تراکنش و سند حسابداری فقط در صورتی که مشتری بدهکار نباشد
    if debt_status != "unpaid":
        if cost_paid > 0:
            try:
                r_order_id = f"RNW_{get_now_naive().strftime('%Y%m%d%H%M%S')}_{random.randint(100, 999)}"
                db.save_transaction(
                    order_id=r_order_id,
                    user_id=sub.get("telegram_id") or 0,
                    username=sub.get("account_name") or "",
                    plan_name=plan_name,
                    amount=cost_paid,
                    gateway="cash_admin",
                    tracking_code=f"RENEW_{session.get('username') or 'admin'}",
                    status="approved",
                    account_name=sub.get("account_name") or "",
                    source="admin"
                )
                db.add_accounting_record(
                    type="income",
                    category="تمدید اشتراک",
                    title=f"تمدید اشتراک {sub.get('account_name')} ({plan_name})",
                    amount=cost_paid,
                    source="admin_panel",
                    ref_type="subscription",
                    ref_id=str(sub_id),
                    description=f"تمدید توسط مدیریت ({session.get('username') or 'admin'})",
                    date=get_now_iso()[:10]
                )
            except Exception as e_rev:
                logger.error(f"Error recording revenue for admin renew: {e_rev}")
        elif is_free:
            try:
                r_order_id = f"RNW_FREE_{get_now_naive().strftime('%Y%m%d%H%M%S')}_{random.randint(100, 999)}"
                db.save_transaction(
                    order_id=r_order_id,
                    user_id=sub.get("telegram_id") or 0,
                    username=sub.get("account_name") or "",
                    plan_name=f"{plan_name} (تمدید رایگان)",
                    amount=0,
                    gateway="free_admin",
                    tracking_code=f"FREE_{session.get('username') or 'admin'}",
                    status="approved",
                    account_name=sub.get("account_name") or "",
                    source="admin"
                )
                db.add_accounting_record(
                    type="income",
                    category="تمدید رایگان اشتراک",
                    title=f"تمدید رایگان اشتراک {sub.get('account_name')} ({plan_name})",
                    amount=0,
                    source="admin_panel",
                    ref_type="subscription",
                    ref_id=str(sub_id),
                    description=f"تمدید رایگان توسط مدیریت ارشد ({session.get('username') or 'admin'})",
                    date=get_now_iso()[:10]
                )
            except Exception as e_rev:
                logger.error(f"Error recording free renewal: {e_rev}")

    return redirect(get_redirect_target("subscriptions"))


@app.route("/admin/subscriptions/bulk-renew", methods=["POST"])
@permission_required("sub_manage")
def admin_subscriptions_bulk_renew():
    """تمدید گروهی اشتراک‌های انتخاب‌شده در پنل مدیریت (آنی یا در صف)"""
    selected_ids_str = request.form.get("selected_ids_str", "").strip()
    if not selected_ids_str:
        flash("هیچ اشتراکی برای تمدید گروهی انتخاب نشده است.", "warning")
        return redirect(url_for("subscriptions"))

    try:
        sub_ids = [int(x.strip()) for x in selected_ids_str.split(",") if x.strip().isdigit()]
    except Exception:
        flash("شناسه‌های ارسالی نامعتبر هستند.", "danger")
        return redirect(url_for("subscriptions"))

    if not sub_ids:
        flash("هیچ اشتراک معتبری یافت نشد.", "warning")
        return redirect(url_for("subscriptions"))

    plan_key = request.form.get("plan_id", "current").strip()
    instant_activate = bool(request.form.get("instant_activate"))
    is_free = request.form.get("is_free") in ("on", "1", "true")
    plans = get_plans_dict()

    success_count = 0
    now = get_now_iso()
    now_naive = get_now_naive()

    conn = db.get_connection()
    for s_id in sub_ids:
        sub_row = conn.execute("SELECT * FROM subscriptions WHERE id=?", (s_id,)).fetchone()
        if not sub_row:
            continue
        sub = dict(sub_row)

        if plan_key == "current" or plan_key not in plans:
            p_key = sub.get("plan_id") or "custom"
            p_limit = float(sub.get("data_limit") or 30)
            p_dur = int(sub.get("duration") or 30)
            p_name = sub.get("plan_name") or f"{p_limit} گیگ {p_dur} روزه"
            p_cost = int(sub.get("cost_paid") or 0)
        else:
            plan = plans[plan_key]
            p_key = plan_key
            p_limit = float(plan.get("data_limit", 30))
            p_dur = int(plan.get("duration", 30))
            p_name = plan.get("name", f"{p_limit} گیگ")
            p_cost = int(plan.get("price", 0))

        if is_free:
            p_cost = 0
            p_name = f"{p_name} (رایگان)"

        if instant_activate:
            if sub.get("hidify_uuid"):
                try:
                    hidify_sync_renew_user(sub["hidify_uuid"], p_limit, p_dur, force_instant=True)
                except Exception as e:
                    logger.error(f"Bulk renew Hiddify error for {sub.get('hidify_uuid')}: {e}")

            new_start_date = now_naive.strftime("%Y-%m-%d")
            new_expire_date = (now_naive + timedelta(days=p_dur)).isoformat()
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE subscriptions
                SET plan_id=?, plan_name=?, data_limit=?, data_used=0, duration=?,
                    start_date=?, expire_date=?, status='active', updated_at=?, cost_paid=?
                WHERE id=?
            """, (p_key, p_name, p_limit, p_dur, new_start_date, new_expire_date, now, p_cost, s_id))
            conn.commit()

            try:
                db.log_subscription_history(
                    subscription_id=s_id,
                    telegram_id=sub.get("telegram_id") or 0,
                    hidify_uuid=sub.get("hidify_uuid") or "",
                    account_name=sub.get("account_name") or "",
                    plan_name=p_name,
                    previous_usage_gb=sub.get("data_used") or 0,
                    previous_limit_gb=sub.get("data_limit") or 0,
                    period_days=p_dur,
                    renewal_type="reset_and_replaced",
                    reseller_id=sub.get("reseller_id"),
                    cost_paid=p_cost
                )
            except Exception:
                pass
            success_count += 1
        else:
            q_res = db.add_to_subscription_queue(
                subscription_id=s_id,
                plan_id=p_key,
                plan_name=p_name,
                data_limit=p_limit,
                duration=p_dur,
                cost=p_cost,
                reseller_id=sub.get("reseller_id"),
                telegram_id=sub.get("telegram_id") or 0,
                hidify_uuid=sub.get("hidify_uuid") or "",
                note="تمدید گروهی رایگان در صف" if is_free else "تمدید گروهی در صف"
            )
            if q_res.get("success"):
                success_count += 1

        is_sub_debtor = bool(sub.get("payment_status") in ("unpaid", "debtor") or (sub.get("debt_amount") or 0) > 0)
        if p_cost > 0 and not is_sub_debtor:
            try:
                b_order_id = f"RNW_{get_now_naive().strftime('%Y%m%d%H%M%S')}_{random.randint(100, 999)}"
                db.save_transaction(
                    order_id=b_order_id,
                    user_id=sub.get("telegram_id") or 0,
                    username=sub.get("account_name") or "",
                    plan_name=p_name,
                    amount=p_cost,
                    gateway="cash_admin",
                    tracking_code=f"BULK_RENEW_{session.get('username') or 'admin'}",
                    status="approved",
                    account_name=sub.get("account_name") or ""
                )
                db.add_accounting_record(
                    type="income",
                    category="تمدید اشتراک",
                    title=f"تمدید گروهی {sub.get('account_name')} ({p_name})",
                    amount=p_cost,
                    source="admin_panel",
                    ref_type="subscription",
                    ref_id=str(s_id),
                    description=f"تمدید گروهی توسط مدیریت ({session.get('username') or 'admin'})",
                    date=now[:10]
                )
            except Exception as e_prev:
                logger.error(f"Error recording revenue for bulk renew: {e_prev}")
        elif is_free:
            try:
                b_order_id = f"RNW_FREE_{get_now_naive().strftime('%Y%m%d%H%M%S')}_{random.randint(100, 999)}"
                db.save_transaction(
                    order_id=b_order_id,
                    user_id=sub.get("telegram_id") or 0,
                    username=sub.get("account_name") or "",
                    plan_name=p_name,
                    amount=0,
                    gateway="free_admin",
                    tracking_code=f"BULK_FREE_{session.get('username') or 'admin'}",
                    status="approved",
                    account_name=sub.get("account_name") or ""
                )
                db.add_accounting_record(
                    type="income",
                    category="تمدید رایگان اشتراک",
                    title=f"تمدید گروهی رایگان {sub.get('account_name')} ({p_name})",
                    amount=0,
                    source="admin_panel",
                    ref_type="subscription",
                    ref_id=str(s_id),
                    description=f"تمدید گروهی رایگان توسط مدیریت ارشد ({session.get('username') or 'admin'})",
                    date=now[:10]
                )
            except Exception as e_prev:
                logger.error(f"Error recording free revenue for bulk renew: {e_prev}")

    conn.close()
    mode_text = "به صورت آنی تمدید و ریست شدند" if instant_activate else "در صف تمدید رزرو قرار گرفتند"
    free_mode_text = " (به صورت رایگان با مبلغ ۰ تومان)" if is_free else ""
    flash(f"{success_count} اشتراک با موفقیت {mode_text}{free_mode_text}.", "success")
    return redirect(get_redirect_target("subscriptions"))


@app.route("/admin/subscription/<int:sub_id>/add-traffic", methods=["POST"])
@permission_required("sub_manage")
def admin_subscription_add_traffic(sub_id):
    """افزایش دستی سقف حجم ترافیک اشتراک و همگام‌سازی با هیدیفای"""
    extra_gb_raw = request.form.get("extra_gb", "0").strip()
    try:
        extra_gb = float(extra_gb_raw)
    except ValueError:
        extra_gb = 0

    if extra_gb <= 0:
        flash("مقدار حجم اضافه باید بزرگتر از صفر باشد.", "warning")
        return redirect(get_redirect_target("subscriptions"))

    res = db.add_subscription_traffic(sub_id, extra_gb)
    if res.get("success"):
        if res.get("hidify_uuid"):
            try:
                hidify_sync_update_user(res["hidify_uuid"], usage_limit_GB=res["new_limit"])
            except Exception as e:
                logger.error(f"Error syncing extra traffic with Hiddify: {e}")
        flash(f"سقف ترافیک با موفقیت {extra_gb} گیگابایت افزایش یافت (سقف جدید: {res['new_limit']} GB).", "success")
    else:
        flash(f"خطا در افزایش ترافیک: {res.get('error')}", "danger")
    return redirect(get_redirect_target("subscriptions"))


@app.route("/admin/queue/<int:queue_id>/activate", methods=["POST"])
@permission_required("sub_manage")
def admin_queue_activate(queue_id: int):
    """فعال‌سازی آنی بسته در صف تمدید توسط مدیریت"""
    username = session.get("username") or "مدیریت"
    res = activate_single_queue_item(queue_id, triggered_by=username)
    if res.get("success"):
        flash(f"بسته «{res.get('plan_name')}» برای اشتراک «{res.get('account_name')}» با موفقیت فعال شد و حجم و تاریخ آن ریست گردید.", "success")
    else:
        flash(f"خطا در فعال‌سازی بسته: {res.get('error')}", "danger")
    return redirect(get_redirect_target("subscriptions"))


@app.route("/admin/queue/<int:queue_id>/cancel", methods=["POST"])
@permission_required("sub_manage")
def admin_queue_cancel(queue_id: int):
    """لغو بسته در صف تمدید توسط مدیریت و استرداد وجه در صورت نیاز"""
    res = db.cancel_queue_item(queue_id)
    if res.get("success"):
        refund_txt = f" و مبلغ {res.get('refunded_amount'):,} تومان به حساب نماینده بازگردانده شد" if res.get('refunded_amount') else ""
        flash(f"بسته رزرو شده با موفقیت از صف تمدید لغو شد{refund_txt}.", "info")
    else:
        flash(f"خطا در لغو بسته: {res.get('error')}", "danger")
    return redirect(get_redirect_target("subscriptions"))


@app.route("/admin/queue/<int:queue_id>/move", methods=["POST"])
@permission_required("sub_manage")
def admin_queue_move(queue_id: int):
    """تغییر نوبت بسته در صف تمدید توسط مدیریت"""
    direction = request.form.get("direction") or request.args.get("direction", "up")
    if request.is_json:
        direction = (request.get_json(silent=True) or {}).get("direction") or direction
    conn = db.get_connection()
    q_row = conn.execute("SELECT subscription_id FROM subscription_queue WHERE id=?", (queue_id,)).fetchone()
    conn.close()
    if not q_row:
        if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.is_json:
            return jsonify({"success": False, "error": "بسته مورد نظر در صف یافت نشد."}), 404
        flash("بسته مورد نظر در صف یافت نشد.", "danger")
        return redirect(get_redirect_target("subscriptions"))
    sub_id = q_row[0]
    res = db.reorder_subscription_queue(sub_id, queue_id, direction)
    if res.get("success"):
        if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.is_json:
            return jsonify({"success": True, "message": "ترتیب بسته‌های در صف تمدید با موفقیت به‌روزرسانی شد."})
        flash("ترتیب بسته‌های در صف تمدید با موفقیت به‌روزرسانی شد.", "success")
    else:
        err = res.get("error", "خطا در جابجایی بسته")
        if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.is_json:
            return jsonify({"success": False, "error": err}), 400
        flash(f"خطا در جابجایی بسته: {err}", "danger")
    return redirect(get_redirect_target("subscriptions"))


@app.route("/admin/queue/process-now", methods=["POST"])
@permission_required("sub_manage")
def admin_queue_process_now():
    """پردازش فوری و بررسی شرایط فعال‌سازی بسته‌های صف تمدید"""
    res = process_subscription_queue()
    activated = res.get("activated", 0)
    processed = res.get("processed", 0)
    flash(f"پردازش صف تمدید انجام شد: تعداد {processed} بسته بررسی و {activated} بسته واجد شرایط (۹۹٪ مصرف یا روز پایانی) فعال شدند.", "info")
    return redirect(get_redirect_target("subscriptions"))


@app.route("/admin/subscription/<int:sub_id>/toggle-vip", methods=["POST"])
@permission_required("sub_manage")
def admin_subscription_toggle_vip(sub_id):
    """تنظیم وضعیت کاربر ویژه (VIP) برای مشتری"""
    is_vip = request.form.get("is_vip") == "1"
    res = db.set_subscription_vip(sub_id, is_vip=is_vip)
    if res.get("success"):
        label = "کاربر ویژه (VIP)" if is_vip else "کاربر عادی"
        flash(f"وضعیت اشتراک با موفقیت به «{label}» تغییر یافت.", "success")
    else:
        flash(f"خطا در تغییر وضعیت: {res.get('error')}", "danger")
    return redirect(get_redirect_target("subscriptions"))


@app.route("/admin/subscription/<int:sub_id>/edit", methods=["POST"])
@permission_required("sub_manage")
def admin_subscription_edit(sub_id):
    """ویرایش جامع مشخصات، حجم، روزها، آیدی تلگرام و وضعیت بدهی اشتراک هیدیفای توسط مدیر"""
    conn = db.get_connection()
    sub_row = conn.execute("SELECT * FROM subscriptions WHERE id=?", (sub_id,)).fetchone()
    conn.close()
    if not sub_row:
        flash("اشتراک یافت نشد.", "danger")
        return redirect(get_redirect_target("subscriptions"))

    sub = dict(sub_row)
    account_name = request.form.get("account_name", "").strip() or sub["account_name"]
    phone_number = request.form.get("phone_number", "").strip()
    comment = request.form.get("comment", "").strip()
    telegram_id_raw = request.form.get("telegram_id", "").strip()
    telegram_id = int(telegram_id_raw) if telegram_id_raw.isdigit() else (sub.get("telegram_id") or 0)

    data_limit = float(request.form.get("data_limit", sub.get("data_limit") or 30))
    duration = int(request.form.get("duration", sub.get("duration") or 30))
    status = request.form.get("status", sub.get("status") or "active")

    payment_status = request.form.get("payment_status", sub.get("payment_status") or "paid").strip()
    debt_amount_raw = request.form.get("debt_amount", "").strip()
    debt_notes = request.form.get("debt_notes", "").strip()
    debt_amount = int(debt_amount_raw) if debt_amount_raw.isdigit() else 0

    now = get_now_iso()
    debt_created = now if (payment_status in ('unpaid', 'debtor') and not sub.get("debt_created_at")) else sub.get("debt_created_at")

    # بررسی و تغییر شناسه اختصاصی (UUID) در صورت تغییر
    form_uuid = request.form.get("hidify_uuid", "").strip().lower()
    old_uuid = (sub.get("hidify_uuid") or "").strip().lower()
    final_uuid = old_uuid
    uuid_changed = False

    if form_uuid and form_uuid != old_uuid:
        try:
            val_uuid = str(uuid.UUID(form_uuid))
        except ValueError:
            flash("شناسه UUID وارد شده نامعتبر است. لطفاً فرمت استاندارد UUID را رعایت فرمایید.", "danger")
            return redirect(get_redirect_target("subscriptions"))

        change_res = hidify_sync_change_user_uuid(old_uuid, val_uuid, sub_fallback_data=sub)
        if isinstance(change_res, dict) and "error" in change_res:
            flash(f"خطا در تغییر شناسه UUID در پنل هیدیفای: {change_res.get('error')}", "danger")
            return redirect(get_redirect_target("subscriptions"))

        final_uuid = val_uuid
        uuid_changed = True

    # بروزرسانی در سرور هیدیفای
    if final_uuid:
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

        hidify_sync_update_user(final_uuid, **h_update)

    # بروزرسانی در پایگاه‌داده
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE subscriptions 
        SET account_name = ?,
            hidify_uuid = ?,
            data_limit = ?,
            duration = ?,
            status = ?,
            telegram_id = ?,
            phone_number = ?,
            account_comment = ?,
            payment_status = ?,
            debt_amount = ?,
            debt_notes = ?,
            debt_created_at = ?,
            updated_at = ?
        WHERE id = ?
    """, (
        account_name, final_uuid, data_limit, duration, status,
        telegram_id, phone_number or None, comment or None,
        payment_status, debt_amount, debt_notes or None,
        debt_created, now, sub_id
    ))

    # در صورت تسویه وضعیت مالی، بستن فاکتورهای باز
    if payment_status == 'paid' or debt_amount == 0:
        cursor.execute("""
            UPDATE customer_debt_records
            SET status = 'paid', paid_at = ?, settled_by = ?, updated_at = ?
            WHERE subscription_id = ? AND status = 'unpaid'
        """, (now, session.get("username") or "admin", now, sub_id))

    # اگر کاربر در جدول users باشد، بروزرسانی نام، شماره تلفن و UUID
    if telegram_id and telegram_id > 0:
        cursor.execute("SELECT * FROM users WHERE telegram_id=?", (telegram_id,))
        if cursor.fetchone():
            cursor.execute("UPDATE users SET phone_number=COALESCE(?, phone_number), username=COALESCE(?, username), hidify_uuid=COALESCE(?, hidify_uuid), updated_at=? WHERE telegram_id=?", (phone_number or None, account_name, final_uuid, now, telegram_id))
        else:
            cursor.execute("INSERT INTO users (telegram_id, username, phone_number, hidify_uuid, is_verified, created_at, updated_at) VALUES (?, ?, ?, ?, 1, ?, ?)", (telegram_id, account_name, phone_number or None, final_uuid, now, now))

    conn.commit()
    conn.close()

    # همگام‌سازی فوری
    sync_hiddify_online_users(force=True)

    if uuid_changed:
        flash(f"مشخصات اشتراک «{account_name}» و شناسه هیدیفای (UUID) با موفقیت در سیستم و پنل هیدیفای تغییر یافت. لینک‌های قبلی مشتری باطل گردیدند.", "success")
    else:
        flash(f"مشخصات اشتراک «{account_name}» با موفقیت ویرایش و در هیدیفای اعمال شد.", "success")
    return redirect(get_redirect_target("subscriptions"))


@app.route("/admin/subscription/<int:sub_id>/toggle", methods=["POST"])
@permission_required("sub_manage")
def admin_subscription_toggle(sub_id):
    """فعال یا غیرفعال‌سازی آنی اشتراک هیدیفای توسط مدیر ارشد و پشتیبانی"""
    conn = db.get_connection()
    sub_row = conn.execute("SELECT * FROM subscriptions WHERE id=?", (sub_id,)).fetchone()
    conn.close()
    if not sub_row:
        flash("اشتراک یافت نشد.", "danger")
        return redirect(get_redirect_target("subscriptions"))

    sub = dict(sub_row)
    current_status = sub.get("status", "active")
    new_status = "disabled" if current_status == "active" else "active"
    is_enable = (new_status == "active")

    reason = request.form.get("reason", "").strip()
    custom_reason = request.form.get("custom_reason", "").strip()
    final_reason = custom_reason if reason == "custom" and custom_reason else (reason or "سایر")
    dis_reason = final_reason if not is_enable else None

    if sub.get("hidify_uuid"):
        hidify_sync_update_user(sub["hidify_uuid"], enable=is_enable, is_active=is_enable)

    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE subscriptions SET status = ?, disable_reason = ?, updated_at = ? WHERE id = ?", (new_status, dis_reason, get_now_iso(), sub_id))
    conn.commit()
    conn.close()

    action_fa = "فعال" if is_enable else "غیرفعال"
    reason_fa = f" (علت: {dis_reason})" if dis_reason else ""
    flash(f"اشتراک «{sub.get('account_name')}» با موفقیت {action_fa} شد.{reason_fa}", "info")
    return redirect(get_redirect_target("subscriptions"))


@app.route("/admin/subscription/<int:sub_id>/delete", methods=["POST"])
@permission_required("sub_delete")
def admin_subscription_delete(sub_id):
    """انتقال اشتراک به سطل زباله توسط مدیر با ثبت علت و استرداد مستقیم وجه به مشتری"""
    admin_role = session.get("admin_role", "support")
    admin_name = session.get("name") or session.get("username") or "مدیر"
    preset_reason = request.form.get("reason", "").strip()
    custom_reason = request.form.get("custom_reason", "").strip()
    final_reason = custom_reason if preset_reason == "custom" and custom_reason else (preset_reason or "سایر")
    
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
        return redirect(get_redirect_target("subscriptions"))

    sub = dict(sub_row)
    uuid_val = sub.get("hidify_uuid")

    # بروزرسانی آخرین وضعیت مصرف و تاریخ‌ها از هیدیفای قبل از انتقال به سطل زباله
    if uuid_val:
        try:
            h_info = hidify_sync_request("GET", f"/admin/user/{uuid_val}/")
            if isinstance(h_info, dict) and "error" not in h_info:
                latest_used = float(h_info.get("current_usage_GB") or 0)
                latest_start = h_info.get("start_date")
                latest_exp = h_info.get("expiry_time") or h_info.get("expire_date")
                conn = db.get_connection()
                conn.execute("""
                    UPDATE subscriptions 
                    SET data_used = ?, 
                        start_date = COALESCE(?, start_date), 
                        expire_date = COALESCE(?, expire_date) 
                    WHERE id = ?
                """, (latest_used, latest_start, latest_exp, sub_id))
                conn.commit()
                conn.close()
                sub["data_used"] = latest_used
                if latest_start:
                    sub["start_date"] = latest_start
                if latest_exp:
                    sub["expire_date"] = latest_exp
        except Exception as ex:
            logger.warning(f"Error syncing usage before admin soft-delete: {ex}")

        # غیرفعال‌سازی در سرور هیدیفای به جای حذف قطعی
        try:
            hidify_sync_update_user(uuid_val, enable=False, is_active=False)
        except Exception as ex:
            logger.error(f"Error disabling user {uuid_val} in Hiddify on soft-delete: {ex}")

    # حذف نرم و استرداد مستقیم وجه به مشتری در دیتابیس
    del_res = db.delete_customer_subscription(sub_id, refund_to_customer=refund_to_customer, admin_name=admin_name, reason=final_reason)
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
            flash(f"اشتراک «{del_res['account_name']}» به سطل زباله منتقل شد و مبلغ {del_res['refund_amount']:,} تومان ({del_res['refund_percent']}٪ استرداد) مستقیماً به کیف پول مشتری بازگردانده شد. (علت: {final_reason})", "success")
        else:
            flash(f"اشتراک «{del_res['account_name']}» به سطل زباله منتقل شد. (علت: {final_reason})", "info")
    else:
        flash(f"خطا در حذف اشتراک: {del_res.get('error')}", "danger")

    return redirect(get_redirect_target("subscriptions"))


@app.route("/admin/subscription/<int:sub_id>/restore", methods=["POST"])
@permission_required("sub_delete")
def admin_subscription_restore(sub_id):
    """بازگردانی اشتراک از سطل زباله توسط مدیر و ساخت مجدد در هیدیفای با حفظ حجم و زمان"""
    conn = db.get_connection()
    sub_row = conn.execute("SELECT * FROM subscriptions WHERE id=? AND is_deleted=1", (sub_id,)).fetchone()
    conn.close()
    if not sub_row:
        flash("اشتراک حذف‌شده‌ای یافت نشد.", "danger")
        return redirect(get_redirect_target("subscriptions"))

    sub = dict(sub_row)
    reseller_id = sub.get("reseller_id")

    # ۱. بازگردانی یا ساخت مجدد کاربر روی سرور هیدیفای با حفظ حجم و زمان
    h_res = hiddify_restore_or_recreate_subscription(sub, reseller_id=reseller_id)
    if not h_res.get("success"):
        flash(f"خطا در ایجاد/فعال‌سازی کاربر در سرور هیدیفای: {h_res.get('error')}", "danger")
        return redirect(get_redirect_target("subscriptions"))

    # ۲. ثبت بازگردانی در دیتابیس
    res = db.restore_subscription(
        sub_id,
        is_reseller=False,
        new_uuid=h_res.get("uuid"),
        new_start_date=h_res.get("new_start_date"),
        new_expire_date=h_res.get("new_expire_date"),
        new_data_used=h_res.get("data_used")
    )
    if res.get("success"):
        recreated_text = "مجدداً در پنل هیدیفای ساخته شد" if h_res.get("recreated") else "در پنل هیدیفای فعال شد"
        used_gb = h_res.get("data_used", 0)
        rem_days = h_res.get("remaining_days", 0)
        flash(f"اشتراک «{res.get('account_name')}» با موفقیت {recreated_text} و از سطل زباله بازگردانی شد (حجم مصرفی: {used_gb} گیگ | زمان باقی‌مانده: {rem_days} روز لحاظ گردید).", "success")
    else:
        flash(f"خطا در بازگردانی اشتراک: {res.get('error')}", "danger")
    return redirect(get_redirect_target("subscriptions"))


@app.route("/admin/subscription/<int:sub_id>/purge", methods=["POST"])
@permission_required("sub_delete")
def admin_subscription_purge(sub_id):
    """حذف دائمی اشتراک از سطل زباله و سرور هیدیفای توسط مدیر"""
    conn = db.get_connection()
    sub_row = conn.execute("SELECT * FROM subscriptions WHERE id=? AND is_deleted=1", (sub_id,)).fetchone()
    conn.close()
    if not sub_row:
        flash("اشتراک حذف‌شده‌ای یافت نشد.", "danger")
        return redirect(url_for("subscriptions", status="deleted"))

    sub = dict(sub_row)
    uuid_val = sub.get("hidify_uuid")
    if uuid_val:
        try:
            hidify_sync_delete_user(uuid_val)
        except Exception as e:
            logger.warning(f"Error purging user {uuid_val} from Hiddify: {e}")

    res = db.purge_subscription_permanently(sub_id)
    if res.get("success"):
        flash(f"اشتراک «{sub.get('account_name')}» برای همیشه از سطل زباله و پنل هیدیفای حذف گردید.", "warning")
    else:
        flash(f"خطا در حذف دائمی اشتراک: {res.get('error')}", "danger")

    return redirect(url_for("subscriptions", status="deleted"))


@app.route("/admin/trash/bulk", methods=["POST"])
@permission_required("sub_delete")
def admin_trash_bulk():
    """عملیات گروهی در سطل زباله مدیریت (بازگردانی گروهی یا حذف دائمی گروهی)"""
    action = request.form.get("bulk_action")
    raw_ids = request.form.getlist("selected_ids") or [x.strip() for x in request.form.get("selected_ids_str", "").split(",") if x.strip()]
    sub_ids = []
    for s_id in raw_ids:
        try:
            val = int(str(s_id).strip())
            if val > 0:
                sub_ids.append(val)
        except (ValueError, TypeError):
            continue

    if not sub_ids:
        flash("هیچ اشتراکی انتخاب نشده است.", "warning")
        return redirect(url_for("subscriptions", status="deleted"))

    success_count = 0
    if action == "restore":
        for sub_id in sub_ids:
            conn = db.get_connection()
            sub_row = conn.execute("SELECT * FROM subscriptions WHERE id=? AND is_deleted=1", (sub_id,)).fetchone()
            conn.close()
            if not sub_row:
                continue
            sub = dict(sub_row)
            h_res = hiddify_restore_or_recreate_subscription(sub, reseller_id=sub.get("reseller_id"))
            if h_res.get("success"):
                db.restore_subscription(
                    sub_id,
                    is_reseller=False,
                    new_uuid=h_res.get("uuid"),
                    new_start_date=h_res.get("new_start_date"),
                    new_expire_date=h_res.get("new_expire_date"),
                    new_data_used=h_res.get("data_used")
                )
                success_count += 1
        db.add_system_log(
            category="admin",
            action="bulk_restore",
            title=f"بازگردانی گروهی {success_count} اشتراک از سطل زباله",
            description=f"تعداد {success_count} اشتراک به صورت گروهی توسط مدیر ({session.get('username')}) از سطل زباله بازیابی و در هیدیفای فعال شدند.",
            actor_type="admin",
            actor_name=session.get("username", "مدیر سیستم"),
            target_type="subscription",
            target_name=f"{success_count} اشتراک",
            details={"sub_ids": sub_ids, "success_count": success_count},
            level="success",
            ip_address=request.remote_addr
        )
        flash(f"{success_count} اشتراک با موفقیت از سطل زباله بازگردانی شدند و در هیدیفای فعال گردیدند.", "success")
    elif action == "purge":
        for sub_id in sub_ids:
            conn = db.get_connection()
            sub_row = conn.execute("SELECT * FROM subscriptions WHERE id=? AND is_deleted=1", (sub_id,)).fetchone()
            conn.close()
            if not sub_row:
                continue
            sub = dict(sub_row)
            if sub.get("hidify_uuid"):
                try:
                    hidify_sync_delete_user(sub["hidify_uuid"])
                except Exception as e:
                    logger.warning(f"Error purging user {sub['hidify_uuid']} from Hiddify: {e}")
            del_res = db.purge_subscription_permanently(sub_id)
            if del_res.get("success"):
                success_count += 1
        db.add_system_log(
            category="admin",
            action="bulk_purge",
            title=f"حذف دائمی گروهی {success_count} اشتراک از سطل زباله",
            description=f"تعداد {success_count} اشتراک به صورت گروهی توسط مدیر ({session.get('username')}) برای همیشه از هیدیفای و سطل زباله دیتابیس پاکسازی شدند.",
            actor_type="admin",
            actor_name=session.get("username", "مدیر سیستم"),
            target_type="subscription",
            target_name=f"{success_count} اشتراک",
            details={"sub_ids": sub_ids, "success_count": success_count},
            level="danger",
            ip_address=request.remote_addr
        )
        flash(f"{success_count} اشتراک برای همیشه از سطل زباله و پنل هیدیفای حذف گردیدند.", "warning")

    return redirect(url_for("subscriptions", status="deleted"))


# ═══════════════════════════════════════════════════════════════════════
# بخش مدیریت نمایندگان فروش (Resellers Management - Admin)
# ═══════════════════════════════════════════════════════════════════════

@app.route("/admin/resellers", methods=["GET", "POST"])
@admin_required
def admin_resellers():
    """صفحه مدیریت همکاران و نمایندگان فروش با پشتیبانی از ادمین اختصاصی هیدیفای"""
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        name = request.form.get("name")
        telegram_id = int(request.form.get("telegram_id")) if request.form.get("telegram_id") else None
        disc_raw = request.form.get("discount_percent")
        discount_percent = int(disc_raw) if (disc_raw is not None and str(disc_raw).strip() != "") else 20
        initial_balance = int(request.form.get("initial_balance", 0))
        auto_hiddify = bool(request.form.get("auto_create_hiddify_admin"))
        hiddify_admin_uuid = request.form.get("hiddify_admin_uuid", "").strip()

        if auto_hiddify and not hiddify_admin_uuid:
            # ایجاد خودکار ادمین در هیدیفای
            h_admin = hidify_sync_create_admin(
                name=f"Reseller: {name}",
                mode="agent",
                comment=f"Reseller #{username} - {name}"
            )
            if isinstance(h_admin, dict) and h_admin.get("uuid"):
                hiddify_admin_uuid = h_admin["uuid"]
                flash(f"ادمین اختصاصی هیدیفای با شناسه {hiddify_admin_uuid[:8]}... برای نماینده ساخته شد.", "info")
            elif isinstance(h_admin, dict) and h_admin.get("error"):
                logger.warning(f"Failed to auto-create Hiddify admin: {h_admin.get('error')}")
                flash(f"هشدار: ادمین هیدیفای خودکار ساخته نشد ({h_admin.get('error')})، اما حساب نماینده ایجاد گردید.", "warning")

        credit_limit = int(request.form.get("credit_limit", 0) or 0)
        credit_enabled = 1 if (request.form.get("credit_enabled") or credit_limit > 0) else 0
        can_gift_traffic = 1 if request.form.get("can_gift_traffic") in ("on", "1", "true") else 0

        res = db.create_reseller(
            username=username,
            password=password,
            name=name,
            telegram_id=telegram_id,
            discount_percent=discount_percent,
            initial_balance=initial_balance,
            hiddify_admin_uuid=hiddify_admin_uuid,
            credit_enabled=credit_enabled,
            credit_limit=credit_limit,
            can_gift_traffic=can_gift_traffic
        )
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
        r_dict["active_hiddify_key"] = db.get_reseller_hiddify_key(r["id"])
        r_dict["team_members"] = db.get_reseller_team_with_sessions(r["id"])
        r_dict["online_team_count"] = sum(1 for m in r_dict["team_members"] if m.get("is_online"))
        r_dict["usage_summary"] = db.get_reseller_usage_summary(r["id"])
        reseller_list.append(r_dict)

    all_failed_logins = db.get_all_failed_login_logs(limit=50)
    return render_template("resellers.html", resellers=reseller_list, all_failed_logins=all_failed_logins)


@app.route("/admin/session/<int:session_id>/terminate", methods=["POST"])
@admin_required
def admin_terminate_session(session_id):
    """خاتمه فوری یک نشست فعال توسط مدیر ارشد"""
    success = db.terminate_session(session_id)
    if success:
        flash("نشست فعال با موفقیت خاتمه یافت و دسترسی کاربر فوراً قطع شد.", "success")
    else:
        flash("خطا در خاتمه نشست یا این نشست از قبل غیرفعال بوده است.", "warning")
    return redirect(request.referrer or url_for("admin_resellers"))


@app.route("/admin/reseller/<int:reseller_id>/terminate-all-sessions", methods=["POST"])
@admin_required
def admin_terminate_all_reseller_sessions(reseller_id):
    """خاتمه تمامی نشست‌های فعال نماینده و کادر زیرمجموعه وی توسط مدیر کل"""
    count = db.terminate_reseller_and_team_sessions(reseller_id)
    flash(f"تعداد {count} نشست فعال مربوط به این نماینده و کادر وی خاتمه یافت.", "success")
    return redirect(request.referrer or url_for("admin_resellers"))


@app.route("/admin/team-member/<int:member_id>/terminate-sessions", methods=["POST"])
@admin_required
def admin_terminate_team_member_sessions(member_id):
    """خاتمه تمام نشست‌های فعال یک عضو تیم زیرمجموعه توسط مدیر کل"""
    count = db.terminate_all_user_sessions("reseller_subadmin", member_id)
    flash(f"تعداد {count} نشست فعال این عضو تیم با موفقیت خاتمه یافت.", "success")
    return redirect(request.referrer or url_for("admin_resellers"))


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


@app.route("/admin/reseller/wallet-tx/<int:rtx_id>/edit", methods=["POST"])
@super_admin_required
def admin_reseller_wallet_tx_edit(rtx_id):
    """ویرایش تراکنش کیف پول نماینده توسط مدیر ارشد با ثبت لاگ و تعدیل مالی"""
    amount = request.form.get("amount", "").strip()
    description = request.form.get("description", "").strip()
    plan_name = request.form.get("plan_name", "").strip()
    reason = request.form.get("reason", "").strip() or "ویرایش تراکنش کیف پول نماینده توسط مدیریت"

    admin_name = session.get("name") or session.get("username") or "مدیر ارشد"
    admin_id = session.get("admin_id")

    res = db.update_reseller_wallet_transaction(
        rtx_id=rtx_id,
        admin_id=admin_id,
        admin_name=admin_name,
        amount=int(amount) if amount.isdigit() else None,
        description=description,
        plan_name=plan_name,
        reason=reason
    )

    if res.get("success"):
        flash(f"تراکنش کیف پول #{rtx_id} با موفقیت ویرایش شد و مبالغ در سیستم مالی و موجودی نماینده تعدیل گردید.", "success")
    else:
        flash(f"خطا در ویرایش تراکنش کیف پول: {res.get('error')}", "danger")

    return redirect(request.referrer or url_for("admin_reseller_payments", reseller_id=res.get("reseller_id") or 1))


@app.route("/admin/reseller/wallet-tx/<int:rtx_id>/revoke", methods=["POST"])
@super_admin_required
def admin_reseller_wallet_tx_revoke(rtx_id):
    """ابطال تراکنش کیف پول نماینده توسط مدیر ارشد با کسر/استرداد خودکار از کیف پول"""
    reason = request.form.get("reason", "").strip() or "ابطال تراکنش کیف پول نماینده توسط مدیریت"
    admin_name = session.get("name") or session.get("username") or "مدیر ارشد"
    admin_id = session.get("admin_id")

    res = db.revoke_reseller_wallet_transaction(
        rtx_id=rtx_id,
        admin_id=admin_id,
        admin_name=admin_name,
        reason=reason
    )

    if res.get("success"):
        flash(f"تراکنش کیف پول #{rtx_id} با موفقیت باطل شد و اثر مالی آن روی موجودی کیف پول نماینده اعمال گردید.", "warning")
    else:
        flash(f"خطا در ابطال تراکنش کیف پول: {res.get('error')}", "danger")

    return redirect(request.referrer or url_for("admin_reseller_payments", reseller_id=res.get("reseller_id") or 1))


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
    disc_raw = request.form.get("discount_percent")
    discount_percent = int(disc_raw) if (disc_raw is not None and str(disc_raw).strip() != "") else 20
    status = request.form.get("status", "active")
    new_password = request.form.get("new_password", "").strip()
    hiddify_admin_uuid = request.form.get("hiddify_admin_uuid", "").strip()
    auto_hiddify = bool(request.form.get("auto_create_hiddify_admin"))

    if auto_hiddify and not hiddify_admin_uuid:
        h_admin = hidify_sync_create_admin(
            name=f"Reseller: {name or r['name']}",
            mode="agent",
            comment=f"Reseller #{username or r['username']}"
        )
        if isinstance(h_admin, dict) and h_admin.get("uuid"):
            hiddify_admin_uuid = h_admin["uuid"]
            flash(f"ادمین اختصاصی هیدیفای با شناسه {hiddify_admin_uuid[:8]}... برای نماینده ساخته شد.", "info")

    credit_limit = int(request.form.get("credit_limit", 0) or 0)
    credit_enabled = 1 if (request.form.get("credit_enabled") or credit_limit > 0) else 0
    can_gift_traffic = 1 if request.form.get("can_gift_traffic") in ("on", "1", "true") else 0

    updates = {
        "name": name or r["name"],
        "username": username or r["username"],
        "telegram_id": telegram_id,
        "discount_percent": discount_percent,
        "status": status,
        "hiddify_admin_uuid": hiddify_admin_uuid or None,
        "credit_enabled": credit_enabled,
        "credit_limit": credit_limit,
        "can_gift_traffic": can_gift_traffic
    }
    if new_password:
        updates["password"] = new_password

    res = db.update_reseller(reseller_id, **updates)
    if res.get("success"):
        flash(f"اطلاعات نماینده «{updates['name']}» با موفقیت ویرایش شد.", "success")
    else:
        flash(f"خطا در ویرایش نماینده: {res.get('error')}", "danger")
    return redirect(url_for("admin_resellers"))


@app.route("/admin/reseller/<int:reseller_id>/settle-debt", methods=["POST"])
@admin_required
def admin_reseller_settle_debt(reseller_id):
    """ثبت تسویه حساب بدهی اعتباری نماینده توسط مدیر"""
    amount = int(request.form.get("amount", 0))
    description = request.form.get("description", "تسویه بدهی اعتباری").strip()
    if amount <= 0:
        flash("مبلغ تسویه باید بزرگتر از صفر باشد.", "warning")
        return redirect(url_for("admin_resellers"))

    settler_name = session.get("name") or session.get("username") or "مدیر ارشد"
    res = db.settle_reseller_debt(reseller_id, amount, description, settled_by=settler_name)
    if res.get("success"):
        flash(f"تسویه بدهی به مبلغ {amount:,} تومان با موفقیت ثبت شد. مانده بدهی فعلی: {res.get('remaining_debt', 0):,} تومان", "success")
    else:
        flash(f"خطا در تسویه بدهی: {res.get('error')}", "danger")
    return redirect(url_for("admin_resellers"))


@app.route("/admin/reseller/<int:reseller_id>/add-debt", methods=["POST"])
@admin_required
def admin_reseller_add_debt(reseller_id):
    """ثبت قبض بدهی جدید یا معوق برای نماینده توسط مدیر (بدون کسر از سقف اعتبار)"""
    title = request.form.get("title", "").strip() or "قبض بدهی معوق"
    amount_raw = request.form.get("amount", "0").replace(",", "").strip()
    due_date = request.form.get("due_date", "").strip()
    notes = request.form.get("notes", "").strip()
    
    try:
        amount = int(amount_raw)
    except Exception:
        flash("مبلغ بدهی نامعتبر است.", "danger")
        return redirect(url_for("admin_resellers"))
        
    if amount <= 0:
        flash("مبلغ بدهی باید بزرگتر از صفر باشد.", "danger")
        return redirect(url_for("admin_resellers"))
        
    admin_name = session.get("name") or session.get("username") or "مدیر"
    res = db.add_reseller_debt(reseller_id, title=title, amount=amount, due_date=due_date, notes=notes, created_by=admin_name)
    if res.get("success"):
        flash(f"قبض بدهی به مبلغ {amount:,} تومان برای نماینده با موفقیت ثبت شد.", "success")
    else:
        flash(f"خطا در ثبت بدهی: {res.get('error')}", "danger")
        
    return redirect(url_for("admin_resellers"))


@app.route("/admin/reseller/<int:reseller_id>/create-hiddify-admin", methods=["POST"])
@admin_required
def admin_reseller_create_hiddify_admin(reseller_id):
    """ساخت آنی ادمین اختصاصی هیدیفای برای نماینده و اتصال به دیتابیس با قابلیت شناسایی هوشمند ادمین‌های موجود"""
    r = db.get_reseller(reseller_id)
    if not r:
        flash("نماینده یافت نشد.", "danger")
        return redirect(url_for("admin_resellers"))

    # ۱. ابتدا بررسی می‌کنیم آیا ادمینی برای این نماینده از قبل در هیدیفای ایجاد شده است
    try:
        admins = hidify_sync_get_admins()
        if isinstance(admins, list):
            target_name = f"Reseller: {r['name']}".strip()
            for adm in admins:
                if isinstance(adm, dict) and adm.get("uuid"):
                    aname = str(adm.get("name") or "").strip()
                    acomm = str(adm.get("comment") or "").strip()
                    if aname == target_name or (r['name'] and aname == str(r['name']).strip()) or (f"#{r['id']}" in acomm) or (r['username'] and f"({r['username']})" in acomm):
                        existing_uuid = adm["uuid"]
                        db.update_reseller(reseller_id, hiddify_admin_uuid=existing_uuid)
                        flash(f"ادمین هیدیفای با شناسه «{existing_uuid}» با موفقیت شناسایی و به نماینده «{r['name']}» متصل گردید.", "success")
                        return redirect(url_for("admin_resellers"))
    except Exception as e_chk:
        logger.warning(f"Error checking existing admins: {e_chk}")

    # ۲. ایجاد ادمین جدید در صورت عدم وجود
    h_admin = hidify_sync_create_admin(
        name=f"Reseller: {r['name']}",
        mode="agent",
        comment=f"Reseller #{r['id']} ({r['username']})",
        can_add_admin=False,
        lang="fa"
    )
    if isinstance(h_admin, dict) and h_admin.get("uuid"):
        uuid_val = h_admin["uuid"]
        db.update_reseller(reseller_id, hiddify_admin_uuid=uuid_val)
        flash(f"ادمین اختصاصی هیدیفای با شناسه «{uuid_val}» با موفقیت ساخته و به نماینده «{r['name']}» متصل گردید.", "success")
    else:
        err = h_admin.get("error") if isinstance(h_admin, dict) else "پاسخ نامعتبر از سرور هیدیفای"
        flash(f"خطا در ایجاد ادمین در هیدیفای: {err}", "danger")

    return redirect(url_for("admin_resellers"))


@app.route("/admin/reseller/<int:reseller_id>/sync-hiddify", methods=["POST"])
@admin_required
def admin_reseller_sync_hiddify(reseller_id):
    """فراخوانی، همگام‌سازی و بازیابی اشتراک‌های این نماینده از هیدیفای (بدون حذف مشتریان محلی)"""
    r = db.get_reseller(reseller_id)
    if not r:
        flash("نماینده یافت نشد.", "danger")
        return redirect(url_for("admin_resellers"))

    reseller_key = db.get_reseller_hiddify_key(reseller_id)
    users_resp = hidify_sync_request("GET", "/admin/user/", api_key=reseller_key)
    if isinstance(users_resp, list):
        restore_res = db.restore_subscriptions_from_hiddify(users_resp, default_reseller_id=reseller_id)
        count = restore_res.get("synced_count", 0)
        flash(f"تعداد {count} اشتراک متعلق به نماینده «{r['name']}» با موفقیت از هیدیفای فراخوانی و بازیابی شدند.", "success")
    else:
        err = users_resp.get("error") if isinstance(users_resp, dict) else "خطا در دریافت لیست کاربران"
        flash(f"خطا در ارتباط با هیدیفای: {err}", "danger")

    return redirect(url_for("admin_resellers"))


@app.route("/admin/reseller/<int:reseller_id>/prune-sync-hiddify", methods=["POST"])
@admin_required
def admin_reseller_prune_sync_hiddify(reseller_id):
    """همگام‌سازی قطعی با هیدیفای و حذف مشتریان اضافی که در پنل هیدیفای نماینده وجود ندارند"""
    r = db.get_reseller(reseller_id)
    if not r:
        flash("نماینده یافت نشد.", "danger")
        return redirect(url_for("admin_resellers"))

    reseller_key = db.get_reseller_hiddify_key(reseller_id)
    if not reseller_key:
        flash(f"کلید اتصال به هیدیفای برای نماینده «{r['name']}» یافت نشد. لطفاً ابتدا ادمین اختصاصی برای این نماینده تعریف کنید.", "warning")
        return redirect(url_for("admin_resellers"))

    users_resp = hidify_sync_request("GET", "/admin/user/", api_key=reseller_key)
    if not isinstance(users_resp, list):
        err = users_resp.get("error") if isinstance(users_resp, dict) else "خطا در دریافت لیست کاربران از هیدیفای"
        flash(f"خطا در ارتباط با هیدیفای: {err}", "danger")
        return redirect(url_for("admin_resellers"))

    sync_result = db.sync_and_prune_reseller_subscriptions(reseller_id, users_resp)
    if sync_result.get("success"):
        synced_count = sync_result.get("synced_count", 0)
        purged_count = sync_result.get("purged_count", 0)
        purged_names = sync_result.get("purged_names", [])

        if purged_count > 0:
            names_preview = "، ".join(purged_names[:5])
            if len(purged_names) > 5:
                names_preview += f" و {len(purged_names) - 5} اشتراک دیگر..."
            flash(
                f"همگام‌سازی کامل نماینده «{r['name']}» انجام شد: تعداد {synced_count} اشتراک موجود در هیدیفای بروزرسانی شدند و {purged_count} مشتری اضافی که در هیدیفای وجود نداشتند از پنل نماینده حذف گردیدند ({names_preview}).",
                "warning"
            )
        else:
            flash(
                f"همگام‌سازی کامل نماینده «{r['name']}» انجام شد: تعداد {synced_count} اشتراک با هیدیفای همگام شدند. هیچ مشتری اضافی در پنل نماینده وجود نداشت و لیست کاربران کاملاً با هیدیفای یکسان است.",
                "success"
            )
    else:
        flash(f"خطا در همگام‌سازی و پاکسازی: {sync_result.get('error')}", "danger")

    return redirect(url_for("admin_resellers"))


@app.route("/admin/hiddify/bulk-restore-resellers", methods=["POST"])
@admin_required
def admin_hiddify_bulk_restore_resellers():
    """بازیابی سراسری و تفکیک خودکار تمام اشتراک‌ها و اتصال ادمین‌های نمایندگان از سرور هیدیفای با پشتیبانی از پاکسازی اختیاری"""
    # ۱. شناسایی و اتصال خودکار ادمین‌های موجود هیدیفای به نمایندگان متناظر
    try:
        admins_resp = hidify_sync_get_admins()
        if isinstance(admins_resp, list):
            resellers = db.get_all_resellers()
            for r in resellers:
                if not r.get("hiddify_admin_uuid"):
                    r_name = str(r.get("name") or "").strip()
                    r_user = str(r.get("username") or "").strip()
                    r_id_str = f"#{r['id']}"
                    for adm in admins_resp:
                        if isinstance(adm, dict) and adm.get("uuid"):
                            aname = str(adm.get("name") or "").strip()
                            acomm = str(adm.get("comment") or "").strip()
                            if (r_name and aname == f"Reseller: {r_name}") or (r_name and aname == r_name) or (r_id_str in acomm) or (r_user and f"({r_user})" in acomm):
                                db.update_reseller(r["id"], hiddify_admin_uuid=adm["uuid"])
                                logger.info(f"Auto-linked Hiddify admin {adm['uuid']} to reseller #{r['id']}")
                                break
    except Exception as e_adm:
        logger.warning(f"Error auto-linking admins in bulk restore: {e_adm}")

    # ۲. بازیابی کاربران و اشتراک‌ها
    users_resp = hidify_sync_request("GET", "/admin/user/")
    if isinstance(users_resp, list):
        purge_missing = bool(request.form.get("purge_missing"))
        restore_res = db.restore_subscriptions_from_hiddify(users_resp)
        count = restore_res.get("synced_count", 0)

        purged_total = 0
        if purge_missing:
            # پاکسازی مشترکین اضافی برای نمایندگانی که ادمین اختصاصی در هیدیفای دارند
            resellers = db.get_all_resellers()
            for r in resellers:
                adm_uuid = str(r.get("hiddify_admin_uuid") or "").strip()
                if adm_uuid:
                    r_users = [
                        u for u in users_resp 
                        if isinstance(u, dict) and (
                            str(u.get("added_by") or "").strip() == adm_uuid 
                            or f"[RESELLER_ID: #{r['id']}]" in str(u.get("comment") or "")
                            or f"[RESELLER_ID: {r['id']}]" in str(u.get("comment") or "")
                        )
                    ]
                    p_res = db.sync_and_prune_reseller_subscriptions(r["id"], r_users)
                    purged_total += p_res.get("purged_count", 0)

        if purge_missing and purged_total > 0:
            flash(f"عملیات همگام‌سازی و بازیابی سراسری انجام شد: {count} اشتراک در دیتابیس همگام شدند و مجموعاً {purged_total} مشتری اضافی از پنل نمایندگان پاکسازی گردیدند.", "warning")
        else:
            flash(f"عملیات بازیابی سراسری انجام شد: {count} اشتراک در دیتابیس همگام‌سازی و بر اساس ادمین هر نماینده تفکیک شدند.", "success")
    else:
        err = users_resp.get("error") if isinstance(users_resp, dict) else "خطا در دریافت لیست کاربران"
        flash(f"خطا در ارتباط با هیدیفای: {err}", "danger")

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
    """داشبورد حسابداری و مدیریت مالی، هزینه‌ها، سود خالص، گردش حساب ۳۰ روز اخیر و تراز بدهی"""
    type_filter = request.args.get("type", "all")
    category_filter = request.args.get("category", "all")
    period = request.args.get("period", "all")
    search = request.args.get("search", "")
    reseller_audit_id = request.args.get("reseller_id", "")
    selected_reseller_id = int(reseller_audit_id) if reseller_audit_id.isdigit() else None

    summary = db.get_accounting_summary()
    records = db.get_accounting_records(
        limit=250,
        type_filter=type_filter,
        category_filter=category_filter,
        period=period,
        search=search
    )

    # گزارش حسابرسی جامع ۳۰ روز اخیر (کل سیستم یا اختصاصی یک نماینده)
    monthly_audit = db.get_monthly_accounting_audit(reseller_id=selected_reseller_id, days=30)
    resellers_list = db.get_all_resellers()
    selected_reseller = db.get_reseller(selected_reseller_id) if selected_reseller_id else None

    admin_role = session.get("admin_role", "super_admin")
    admin_id = session.get("admin_id")
    target_admin_id = admin_id if admin_role == "partner" else None

    admin_debts_summary = db.get_admins_accounting_summary(admin_id=target_admin_id)
    admin_debts_logs = db.get_admin_debts(admin_id=target_admin_id, limit=100)

    # سود و حسابرسی شرکای تجاری با فیلتر دوره
    partner_period = request.args.get("partner_period", "month").strip()
    if partner_period not in ("today", "week", "month", "year", "all"):
        partner_period = "month"
    partner_profits = db.get_partner_profits_summary(period=partner_period)

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
        monthly_audit=monthly_audit,
        resellers_list=resellers_list,
        selected_reseller_id=selected_reseller_id,
        selected_reseller=selected_reseller,
        admin_debts_summary=admin_debts_summary,
        admin_debts_logs=admin_debts_logs,
        partner_profits=partner_profits,
        partner_period=partner_period
    )


@app.route("/accounting/export/monthly-audit")
@permission_required("accounting")
def accounting_export_monthly_audit():
    """خروجی اکسل استاندارد با فرمت UTF-8 BOM از گردش حساب و حسابرسی ۳۰ روز اخیر"""
    reseller_audit_id = request.args.get("reseller_id", "")
    selected_reseller_id = int(reseller_audit_id) if reseller_audit_id.isdigit() else None
    audit = db.get_monthly_accounting_audit(reseller_id=selected_reseller_id, days=30)
    reseller = db.get_reseller(selected_reseller_id) if selected_reseller_id else None

    output = io.StringIO()
    writer = csv.writer(output)
    
    title_text = f"گزارش حسابرسی و گردش حساب ۳۰ روز اخیر ({reseller.get('name')})" if reseller else "گزارش حسابرسی و گردش حساب ۳۰ روز اخیر (کل سامانه)"
    writer.writerow([title_text])
    writer.writerow(["تاریخ تهیه گزارش:", filter_shamsi_date(get_now_iso())])
    writer.writerow([])
    writer.writerow(["--- شاخص‌های کلیدی مالی ---"])
    writer.writerow(["فروش کل (تومان)", "فروش نقدی (تومان)", "فروش اعتباری/تسویه نشده (تومان)", "هزینه‌ها و مخارج (تومان)", "سود خالص دوره (تومان)", "حجم واگذار شده (GB)", "تعداد کل اشتراک‌ها", "مانده کل بدهی اعتباری"])
    writer.writerow([
        f"{audit['total_revenue']:,}",
        f"{audit['cash_revenue']:,}",
        f"{audit['credit_revenue']:,}",
        f"{audit['total_expenses']:,}",
        f"{audit['net_profit']:,}",
        f"{audit['total_gb_sold']:.1f}",
        audit['total_subs_count'],
        f"{audit['total_outstanding_debt']:,}"
    ])
    writer.writerow([])
    writer.writerow(["--- ریز گردش حساب و تراکنش‌های دوره ---"])
    writer.writerow(["شناسه تراکنش", "کد سفارش", "کاربر / مشتری", "شرح پلن", "مبلغ (تومان)", "روش پرداخت", "کد پیگیری", "وضعیت", "تاریخ ثبت (شمسی)", "تاریخ ثبت (میلادی)"])
    
    for tx in audit.get("transactions", []):
        c_at = tx.get("created_at") or ""
        writer.writerow([
            tx.get("id"),
            tx.get("order_id") or "",
            tx.get("username") or tx.get("user_id") or "",
            tx.get("plan_name") or "",
            tx.get("amount") or 0,
            tx.get("gateway") or "",
            tx.get("tracking_code") or "",
            "تایید شده",
            filter_shamsi_date(c_at) if c_at else "",
            c_at
        ])

    csv_data = "\ufeff" + output.getvalue()
    filename = f"monthly_audit_{selected_reseller_id or 'all'}_{get_now_iso()[:10]}.csv"
    return Response(
        csv_data.encode("utf-8-sig"),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment;filename={filename}"}
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


@app.route("/accounting/record/edit/<int:record_id>", methods=["POST"])
@admin_required
def accounting_edit_record(record_id):
    """ویرایش سند حسابداری با درج تگ ویرایش شده و شخص ویرایش‌کننده"""
    if session.get("admin_role") not in ("super_admin", "admin"):
        flash("فقط مدیر ارشد دسترسی به ویرایش اسناد حسابداری دارد.", "danger")
        return redirect(url_for("accounting"))

    title = request.form.get("title", "").strip()
    category = request.form.get("category", "").strip()
    rec_type = request.form.get("type", "").strip()
    amount_raw = request.form.get("amount", "").replace(",", "").strip()
    description = request.form.get("description", "").strip()
    date = request.form.get("date", "").strip()
    amount = int(amount_raw) if amount_raw.isdigit() else None

    editor = session.get("admin_username") or session.get("username") or "مدیر ارشد"
    res = db.update_accounting_record(
        record_id=record_id,
        title=title or None,
        category=category or None,
        type=rec_type or None,
        amount=amount,
        description=description,
        date=date or None,
        edited_by=editor
    )
    if res.get("success"):
        flash("سند حسابداری با موفقیت ویرایش شد.", "success")
    else:
        flash(f"خطا در ویرایش سند: {res.get('error')}", "danger")
    return redirect(url_for("accounting"))


@app.route("/admin/accounting/debt/edit/<int:debt_id>", methods=["POST"])
@admin_required
def admin_accounting_debt_edit(debt_id):
    """ویرایش سابقه بدهی/تسویه مدیر یا نماینده توسط مدیر ارشد"""
    if session.get("admin_role") not in ("super_admin", "admin"):
        flash("فقط مدیر ارشد دسترسی به ویرایش دفاتر مالی دارد.", "danger")
        return redirect(url_for("accounting"))

    amount_raw = request.form.get("amount", "").replace(",", "").strip()
    amount = int(amount_raw) if amount_raw.isdigit() else None
    description = request.form.get("description", "").strip()

    editor = session.get("admin_username") or session.get("username") or "مدیر ارشد"
    res = db.update_admin_debt(
        debt_id=debt_id,
        amount=amount,
        description=description,
        edited_by=editor
    )
    if res.get("success"):
        flash("سند بدهی/تسویه با موفقیت ویرایش شد.", "success")
    else:
        flash(f"خطا در ویرایش رکورد بدهی: {res.get('error')}", "danger")
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
    """ارسال پیام انبوه هدفمند به کاربران تلگرام و بنر اطلاعیه اختصاصی پنل نمایندگان"""
    global RESELLER_PANEL_BANNERS
    if request.method == "POST":
        action_type = request.form.get("action_type")
        if action_type == "reseller_banner":
            target = request.form.get("target_reseller", "all")
            banner_message = request.form.get("banner_message", "").strip()
            banner_title = request.form.get("banner_title", "").strip()
            banner_level = request.form.get("banner_level", "info")
            if not banner_message:
                flash("متن بنر اطلاعیه نمی‌تواند خالی باشد.", "danger")
                return redirect(url_for("broadcast"))

            target_id = None
            target_name = "همه نمایندگان"
            if target != "all" and target.isdigit():
                target_id = int(target)
                r_info = db.get_reseller(target_id)
                target_name = (r_info.get("name") if r_info else None) or f"نماینده #{target_id}"

            banner_id = f"bnr_{int(time.time())}_{random.randint(100, 999)}"
            RESELLER_PANEL_BANNERS.append({
                "id": banner_id,
                "target_reseller_id": target_id,
                "target_name": target_name,
                "title": banner_title,
                "message": banner_message,
                "level": banner_level,
                "created_at": get_now_shamsi()
            })
            flash(f"✅ بنر اطلاعیه با موفقیت برای «{target_name}» در پنل نمایندگان فعال گردید.", "success")
            return redirect(url_for("broadcast"))

        elif action_type == "delete_banner":
            banner_id = request.form.get("banner_id")
            RESELLER_PANEL_BANNERS = [b for b in RESELLER_PANEL_BANNERS if b.get("id") != banner_id]
            flash("🗑️ بنر اطلاعیه با موفقیت از پنل نمایندگان حذف گردید.", "info")
            return redirect(url_for("broadcast"))

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

    resellers = db.get_all_resellers()
    return render_template("broadcast.html", resellers=resellers, active_banners=RESELLER_PANEL_BANNERS)


# ═══════════════════════════════════════════════════════════════════════
# بخش پشتیبانی و تیکتینگ تحت وب (Web Support Desk)
# ═══════════════════════════════════════════════════════════════════════

@app.route("/tickets")
@permission_required("tickets")
def tickets():
    """لیست و میز کار تیکت‌های پشتیبانی با تفکیک تب‌های مشتریان و نمایندگان، وضعیت‌ها و آمار"""
    category_filter = request.args.get("category", "all")
    status_filter = request.args.get("status", "all")
    search = request.args.get("search", "").strip()

    ticket_list = db.get_all_tickets(status=status_filter, reseller_id=None, search=search, category=category_filter)
    stats = db.get_tickets_stats(reseller_id=None)

    return render_template(
        "tickets.html",
        tickets=ticket_list,
        status_filter=status_filter,
        category_filter=category_filter,
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
        sender_name = session.get("display_name") or session.get("name") or session.get("username") or "پشتیبانی"
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


@app.route("/admin/tickets/bulk", methods=["POST"])
@permission_required("tickets")
def admin_tickets_bulk():
    """عملیات گروهی روی تیکت‌های پشتیبانی توسط ادمین (بستن، بازگشایی، حذف)"""
    action = request.form.get("bulk_action")
    raw_ids = request.form.getlist("selected_ids") or [x.strip() for x in request.form.get("selected_ids_str", "").split(",") if x.strip()]
    ticket_ids = []
    for t_id in raw_ids:
        try:
            val = int(str(t_id).strip())
            if val > 0:
                ticket_ids.append(val)
        except (ValueError, TypeError):
            continue

    if not ticket_ids:
        flash("هیچ تیکتی انتخاب نشده است.", "warning")
        return redirect(url_for("tickets"))

    success_count = 0
    for t_id in ticket_ids:
        if action == "close":
            db.close_ticket(t_id)
            success_count += 1
        elif action == "reopen":
            db.reopen_ticket(t_id)
            success_count += 1
        elif action == "delete":
            db.delete_ticket(t_id)
            success_count += 1

    if action == "close":
        flash(f"✅ تعداد {success_count} تیکت با موفقیت بسته شدند.", "info")
    elif action == "reopen":
        flash(f"✅ تعداد {success_count} تیکت با موفقیت بازگشایی شدند.", "success")
    elif action == "delete":
        flash(f"✅ تعداد {success_count} تیکت با موفقیت حذف شدند.", "success")
    else:
        flash(f"عملیات برای {success_count} تیکت انجام شد.", "info")

    return redirect(url_for("tickets"))


@app.route("/reseller/tickets/bulk", methods=["POST"])
@reseller_required
def reseller_tickets_bulk():
    """عملیات گروهی روی تیکت‌های نماینده (بستن، حذف)"""
    reseller_id = session.get("reseller_id")
    action = request.form.get("bulk_action")
    raw_ids = request.form.getlist("selected_ids") or [x.strip() for x in request.form.get("selected_ids_str", "").split(",") if x.strip()]
    ticket_ids = []
    for t_id in raw_ids:
        try:
            val = int(str(t_id).strip())
            if val > 0:
                ticket_ids.append(val)
        except (ValueError, TypeError):
            continue

    if not ticket_ids:
        flash("هیچ تیکتی انتخاب نشده است.", "warning")
        return redirect(url_for("reseller_tickets"))

    success_count = 0
    for t_id in ticket_ids:
        if action == "close":
            db.close_ticket(t_id)
            success_count += 1
        elif action == "delete":
            res = db.delete_ticket(t_id, reseller_id=reseller_id)
            if res.get("success"):
                success_count += 1

    if action == "close":
        flash(f"✅ تعداد {success_count} تیکت با موفقیت بسته شدند.", "info")
    elif action == "delete":
        flash(f"✅ تعداد {success_count} تیکت با موفقیت حذف شدند.", "success")
    else:
        flash(f"عملیات برای {success_count} تیکت انجام شد.", "info")

    return redirect(url_for("reseller_tickets"))


@app.route("/admin/ticket/<int:ticket_id>/approve-quota-change", methods=["POST"])
@permission_required("tickets")
def approve_quota_change(ticket_id):
    """تایید درخواست تغییر حجم و مدت اشتراک نماینده توسط مدیر و اعمال مستقیم در هیدیفای"""
    admin_name = session.get("username") or "مدیریت"
    res = db.approve_quota_change_request(ticket_id, admin_name=admin_name)
    if not res.get("success"):
        flash(f"خطا در تایید درخواست: {res.get('error')}", "danger")
        return redirect(url_for("tickets"))

    req_data = res.get("data", {})
    sub_id = res.get("sub_id")
    req_limit = req_data.get("requested_limit")
    req_duration = req_data.get("requested_duration")
    acc_name = req_data.get("account_name", f"اشتراک #{sub_id}")
    h_uuid = req_data.get("hidify_uuid")

    if h_uuid:
        h_res = hidify_sync_update_user(
            h_uuid,
            usage_limit_GB=req_limit,
            package_days=req_duration
        )
        if isinstance(h_res, dict) and "error" in h_res:
            logger.warning(f"Failed to update Hiddify on quota change approval: {h_res.get('error')}")

    try:
        sync_hiddify_online_users(force=True)
    except Exception as e_sync:
        logger.error(f"Error in sync after quota change approval: {e_sync}")

    flash(f"✅ درخواست تغییر مشخصات اشتراک «{acc_name}» به {req_limit} گیگابایت و {req_duration} روز با موفقیت تایید و روی سرور هیدیفای اعمال شد.", "success")
    return redirect(url_for("tickets"))


@app.route("/admin/ticket/<int:ticket_id>/reject-quota-change", methods=["POST"])
@permission_required("tickets")
def reject_quota_change(ticket_id):
    """رد درخواست تغییر حجم و مدت اشتراک نماینده با درج علت"""
    admin_name = session.get("username") or "مدیریت"
    reason = request.form.get("reason", "").strip()
    res = db.reject_quota_change_request(ticket_id, reason=reason, admin_name=admin_name)
    if res.get("success"):
        flash(f"درخواست تغییر مشخصات اشتراک رد شد.", "info")
    else:
        flash(f"خطا در رد درخواست: {res.get('error')}", "danger")
    return redirect(url_for("tickets"))


@app.route("/admin/subscription/<int:sub_id>/clear-debt", methods=["POST"])
@permission_required("sub_manage")
def admin_subscription_clear_debt(sub_id):
    """تسویه کامل و سریع بدهی اشتراک توسط مدیر"""
    settled_by = session.get("username") or "admin"
    db.clear_subscription_debt(sub_id, settled_by=settled_by)
    flash("تمام بدهی‌های مشتری با موفقیت تسویه شد و اشتراک به عنوان پرداخت شده علامت‌گذاری گردید.", "success")
    return redirect(request.form.get("next") or request.referrer or url_for("subscriptions"))


@app.route("/reseller/subscription/<int:sub_id>/clear-debt", methods=["POST"])
@reseller_required
def reseller_subscription_clear_debt(sub_id):
    """تسویه کامل و سریع بدهی مشتری توسط نماینده"""
    reseller_id = session.get("reseller_id")
    settled_by = session.get("username") or f"reseller_{reseller_id}"
    db.clear_subscription_debt(sub_id, reseller_id=reseller_id, settled_by=settled_by)
    flash("تمام بدهی‌های مشتری با موفقیت تسویه شد و وضعیت اشتراک به پرداخت شده تغییر یافت.", "success")
    return redirect(request.form.get("next") or request.referrer or url_for("reseller_users"))


@app.route("/api/subscription/<int:sub_id>/debt-report", methods=["GET"])
def api_customer_debt_report(sub_id: int):
    """دریافت گزارش تفصیلی بدهی‌ها و رسیدهای اشتراک جهت نمایش در مودال گزارش بدهی"""
    is_admin = bool(session.get("logged_in") and (session.get("role") in ("admin", "super_admin", "partner") or session.get("is_admin")))
    reseller_id = session.get("reseller_id")
    if not is_admin and not reseller_id:
        return jsonify({"success": False, "error": "دسترسی غیرمجاز"}), 403

    sub = db.get_subscription(sub_id)
    if not sub:
        return jsonify({"success": False, "error": "اشتراک یافت نشد"}), 404

    if not is_admin and reseller_id and sub.get("reseller_id") != reseller_id:
        return jsonify({"success": False, "error": "دسترسی غیرمجاز به این اشتراک"}), 403

    report = db.get_customer_debt_report(sub_id)
    return jsonify({
        "success": True,
        "subscription": {
            "id": sub["id"],
            "account_name": sub.get("account_name"),
            "debt_amount": sub.get("debt_amount", 0),
            "payment_status": sub.get("payment_status", "paid"),
            "debt_notes": sub.get("debt_notes")
        },
        "report": report
    })


@app.route("/admin/subscription/<int:sub_id>/settle-debt-record/<int:record_id>", methods=["POST"])
@permission_required("sub_manage")
def admin_settle_debt_record(sub_id: int, record_id: int):
    """تسویه یک رسید بدهی مشخص توسط مدیر"""
    sub = db.get_subscription(sub_id)
    if not sub:
        return jsonify({"success": False, "error": "اشتراک یافت نشد"}), 404

    settled_by = session.get("username") or "admin"
    res = db.settle_customer_debt_record(sub_id, record_id=record_id, settled_by=settled_by)
    if res.get("success"):
        return jsonify({"success": True, "message": "رسید بدهی با موفقیت تسویه شد.", "data": res})
    else:
        return jsonify({"success": False, "error": res.get("error", "خطا در تسویه بدهی")}), 400


@app.route("/reseller/subscription/<int:sub_id>/settle-debt-record/<int:record_id>", methods=["POST"])
@reseller_required
def reseller_settle_debt_record(sub_id: int, record_id: int):
    """تسویه یک رسید بدهی مشخص توسط نماینده"""
    reseller_id = session.get("reseller_id")
    sub = db.get_reseller_subscription(reseller_id, sub_id)
    if not sub:
        return jsonify({"success": False, "error": "اشتراک یافت نشد یا متعلق به شما نیست"}), 404

    settled_by = session.get("username") or f"reseller_{reseller_id}"
    res = db.settle_customer_debt_record(sub_id, record_id=record_id, settled_by=settled_by)
    if res.get("success"):
        return jsonify({"success": True, "message": "رسید بدهی با موفقیت تسویه شد.", "data": res})
    else:
        return jsonify({"success": False, "error": res.get("error", "خطا در تسویه بدهی")}), 400



@app.route("/subscription/<int:sub_id>/send-debt-reminder", methods=["POST"])
def subscription_send_debt_reminder(sub_id):
    """ارسال پیام یادآوری بدهی به تلگرام مشتری"""
    if not (session.get("logged_in") and (session.get("role") in ("admin", "super_admin", "partner") or session.get("reseller_id"))):
        flash("دسترسی غیرمجاز است.", "danger")
        return redirect(url_for("login"))

    reseller_id = session.get("reseller_id")
    conn = db.get_connection()
    if reseller_id:
        sub = conn.execute("SELECT * FROM subscriptions WHERE id=? AND reseller_id=?", (sub_id, reseller_id)).fetchone()
    else:
        sub = conn.execute("SELECT * FROM subscriptions WHERE id=?", (sub_id,)).fetchone()
    conn.close()

    if not sub:
        flash("اشتراک مورد نظر یافت نشد.", "danger")
        return redirect(request.referrer or url_for("subscriptions"))

    sub = dict(sub)
    tg_id = sub.get("telegram_id")
    debt_amount = sub.get("debt_amount") or 0

    if not tg_id or int(tg_id) <= 0:
        flash("برای این مشتری شناسه کاربری تلگرام ثبت نشده است.", "warning")
        return redirect(request.referrer or url_for("subscriptions"))

    card_number = db.get_setting("card_number") or ""
    card_holder = db.get_setting("card_holder") or ""
    bank_name = db.get_setting("bank_name") or ""
    
    sub_reseller_id = sub.get("reseller_id") or reseller_id
    r_info = db.get_reseller(sub_reseller_id) if sub_reseller_id else {}
    bot_token = None
    if r_info:
        if r_info.get("card_number"):
            card_number = r_info["card_number"]
            card_holder = r_info.get("card_holder", "")
            bank_name = r_info.get("bank_name", "")
        bot_token = r_info.get("bot_token")

    msg = (
        f"🌸 <b>کاربر گرامی، با سلام و احترام</b>\n\n"
        f"📋 <b>یادآوری صورت‌حساب اشتراک:</b> «{sub.get('account_name')}»\n"
        f"💰 <b>مبلغ بدهی / مانده پرداخت:</b> <code>{debt_amount:,}</code> تومان\n"
    )
    if sub.get("debt_notes"):
        msg += f"📝 <b>توضیحات:</b> {sub.get('debt_notes')}\n"
    if card_number:
        msg += f"\n💳 <b>شماره کارت جهت واریز:</b>\n<code>{card_number}</code>\n👤 بنام: {card_holder} ({bank_name})\n"
    msg += "\n🙏 لطفاً پس از واریز، تصویر فیش پرداخت خود را در همین بات ارسال فرمایید."

    try:
        ok = send_telegram_msg(tg_id, msg, bot_token=bot_token)
        if ok:
            flash(f"✅ پیام یادآوری بدهی با موفقیت به تلگرام مشتری «{sub.get('account_name')}» ارسال شد.", "success")
        else:
            flash(f"⚠️ ارسال پیام به تلگرام مشتری ناموفق بود (ممکن است کاربر ربات را مسدود کرده باشد).", "warning")
    except Exception as e:
        logger.error(f"Error sending debt reminder to tg {tg_id}: {e}")
        flash(f"خطا در ارسال پیام تلگرام: {e}", "danger")

    return redirect(request.referrer or (url_for("reseller_users") if reseller_id else url_for("subscriptions")))


@app.route("/admin/subscriptions/bulk", methods=["POST"])
@permission_required("sub_manage")
def admin_subscriptions_bulk():
    """عملیات گروهی روی تمام اشتراک‌ها توسط مدیر (غیرفعال، فعال، حذف، تسویه بدهی)"""
    action = request.form.get("bulk_action")
    raw_ids = request.form.getlist("selected_ids") or [x.strip() for x in request.form.get("selected_ids_str", "").split(",") if x.strip()]
    sub_ids = []
    for s_id in raw_ids:
        try:
            val = int(str(s_id).strip())
            if val > 0:
                sub_ids.append(val)
        except (ValueError, TypeError):
            continue

    if not sub_ids:
        flash("هیچ اشتراکی برای انجام عملیات گروهی انتخاب نشده است.", "warning")
        return redirect(url_for("subscriptions"))

    success_count = 0
    admin_name = session.get("name") or session.get("username") or "مدیریت"

    for sub_id in sub_ids:
        conn = db.get_connection()
        sub_row = conn.execute("SELECT * FROM subscriptions WHERE id=?", (sub_id,)).fetchone()
        conn.close()
        if not sub_row:
            continue
        sub = dict(sub_row)
        uuid_val = sub.get("hidify_uuid")

        preset_reason = request.form.get("reason", "").strip()
        custom_reason = request.form.get("custom_reason", "").strip()
        final_reason = custom_reason if preset_reason == "custom" and custom_reason else (preset_reason or "سایر")

        if action == "disable":
            dis_reason = final_reason if final_reason != "سایر" else "غیرفعال‌سازی توسط مدیریت"
            if uuid_val:
                hidify_sync_update_user(uuid_val, enable=False, is_active=False)
            db.update_subscription(sub_id, status="disabled", disable_reason=dis_reason)
            success_count += 1
        elif action == "enable":
            if uuid_val:
                hidify_sync_update_user(uuid_val, enable=True, is_active=True)
            db.update_subscription(sub_id, status="active", disable_reason=None)
            success_count += 1
        elif action == "delete":
            if uuid_val:
                try:
                    hidify_sync_delete_user(uuid_val)
                except Exception as ex:
                    logger.error(f"Error deleting user {uuid_val} from Hiddify: {ex}")
            del_res = db.delete_customer_subscription(sub_id, refund_to_customer=False, admin_name=admin_name, reason=final_reason)
            if del_res.get("success"):
                success_count += 1
        elif action == "clear_debt":
            db.clear_subscription_debt(sub_id)
            success_count += 1
        elif action == "transfer_reseller":
            pass

    if action == "transfer_reseller":
        target_reseller_id = request.form.get("target_reseller_id")
        target_hiddify_admin = request.form.get("target_hiddify_admin")
        if not target_reseller_id or not str(target_reseller_id).isdigit():
            flash("❌ لطفاً نماینده مقصد را مشخص کنید.", "danger")
            return redirect(url_for("subscriptions"))

        target_r_id = int(target_reseller_id)
        res = db.transfer_subscriptions_to_reseller(
            sub_ids, target_r_id,
            target_hiddify_admin=target_hiddify_admin,
            admin_name=admin_name
        )
        if res.get("success"):
            t_count = res.get("transferred_count", 0)
            h_admin = res.get("target_reseller", {}).get("hiddify_admin_uuid")
            h_success = 0
            for item in res.get("transferred_subs", []):
                h_uuid = item.get("hidify_uuid")
                if h_uuid and h_admin:
                    try:
                        h_res = hidify_sync_update_user(h_uuid, added_by_uuid=h_admin)
                        if isinstance(h_res, dict) and "error" not in h_res:
                            h_success += 1
                    except Exception as ex:
                        logger.error(f"Error syncing user {h_uuid} admin in Hiddify: {ex}")
            flash(f"✅ تعداد {t_count} مشتری با موفقیت به نماینده «{res['target_reseller']['name']}» منتقل شدند (سینک هیدیفای: {h_success} از {t_count}).", "success")
        else:
            flash(f"❌ خطا در انتقال اشتراک‌ها: {res.get('error', 'نامشخص')}", "danger")
        return redirect(url_for("subscriptions"))

    if action == "disable":
        flash(f"✅ تعداد {success_count} اشتراک با موفقیت غیرفعال شدند.", "info")
    elif action == "enable":
        flash(f"✅ تعداد {success_count} اشتراک با موفقیت فعال‌سازی مجدد شدند.", "success")
    elif action == "delete":
        flash(f"✅ تعداد {success_count} اشتراک با موفقیت به طور کامل حذف شدند.", "success")
    elif action == "clear_debt":
        flash(f"✅ بدهی {success_count} اشتراک با موفقیت تسویه گردید.", "success")
    else:
        flash(f"عملیات برای {success_count} اشتراک انجام شد.", "info")

    return redirect(url_for("subscriptions"))


@app.route("/api/admin/transfer-by-pattern/preview", methods=["POST"])
@permission_required("subscriptions_view")
def api_transfer_by_pattern_preview():
    """پیش‌نمایش مشتریان منطبق با الگو جهت انتقال گروهی"""
    data = request.get_json(silent=True) or request.form
    pattern = str(data.get("pattern") or "").strip()
    pattern_type = str(data.get("pattern_type") or "auto").strip()
    source_filter = str(data.get("source_filter") or "all").strip()

    if not pattern:
        return jsonify({"success": False, "error": "لطفاً الگو یا عبارت جستجو را وارد کنید."}), 400

    matched = db.find_subscriptions_by_pattern(pattern, pattern_type=pattern_type, source_filter=source_filter)
    
    results = []
    for s in matched:
        results.append({
            "id": s["id"],
            "account_name": s["account_name"] or "بدون نام",
            "hidify_uuid": s["hidify_uuid"],
            "plan_name": s["plan_name"] or "-",
            "data_limit": float(s.get("data_limit") or 0),
            "data_used": float(s.get("data_used") or 0),
            "status": s.get("status", "active"),
            "created_at": s.get("created_at") or "-",
            "reseller_id": s.get("reseller_id"),
            "reseller_name": s.get("reseller_name") or "مستقیم مدیریت"
        })

    return jsonify({
        "success": True,
        "count": len(results),
        "subscriptions": results
    })


@app.route("/api/admin/transfer-by-pattern/execute", methods=["POST"])
@permission_required("subscriptions_edit")
def api_transfer_by_pattern_execute():
    """اجرای قطعی انتقال گروهی مشتریان بر اساس الگو در هیدیفای و پنل مدیریت"""
    data = request.get_json(silent=True) or request.form
    pattern = str(data.get("pattern") or "").strip()
    pattern_type = str(data.get("pattern_type") or "auto").strip()
    source_filter = str(data.get("source_filter") or "all").strip()
    target_reseller_id = data.get("target_reseller_id")
    target_hiddify_admin = data.get("target_hiddify_admin")

    if not pattern:
        return jsonify({"success": False, "error": "الگو مشخص نشده است."}), 400
    if not target_reseller_id or not str(target_reseller_id).isdigit():
        return jsonify({"success": False, "error": "نماینده مقصد مشخص نشده است."}), 400

    target_reseller_id = int(target_reseller_id)
    matched = db.find_subscriptions_by_pattern(pattern, pattern_type=pattern_type, source_filter=source_filter)
    if not matched:
        return jsonify({"success": False, "error": "هیچ مشتری منطبق با این الگو یافت نشد."}), 404

    sub_ids = [s["id"] for s in matched]
    admin_name = session.get("name") or session.get("username") or "مدیریت"

    res = db.transfer_subscriptions_to_reseller(
        sub_ids, target_reseller_id,
        target_hiddify_admin=target_hiddify_admin,
        admin_name=admin_name
    )

    if not res.get("success"):
        return jsonify({"success": False, "error": res.get("error", "خطا در دیتابیس")}), 500

    t_count = res.get("transferred_count", 0)
    h_admin = res.get("target_reseller", {}).get("hiddify_admin_uuid")
    h_success = 0
    h_errors = []

    for item in res.get("transferred_subs", []):
        h_uuid = item.get("hidify_uuid")
        if h_uuid and h_admin:
            try:
                h_res = hidify_sync_update_user(h_uuid, added_by_uuid=h_admin)
                if isinstance(h_res, dict) and "error" not in h_res:
                    h_success += 1
                else:
                    h_errors.append(f"{item.get('account_name')}: {h_res.get('error', 'نامشخص')}")
            except Exception as ex:
                h_errors.append(f"{item.get('account_name')}: {str(ex)}")

    return jsonify({
        "success": True,
        "transferred_count": t_count,
        "hiddify_synced_count": h_success,
        "target_reseller": res.get("target_reseller"),
        "errors": h_errors
    })


@app.route("/api/admin/hiddify-admins", methods=["GET"])
@permission_required("subscriptions_view")
def api_hiddify_admins():
    """دریافت لیست ادمین‌های ثبت‌شده در پنل هیدیفای"""
    admins = hidify_sync_get_admins()
    return jsonify({"success": True, "admins": admins})


@app.route("/api/subscription/<int:sub_id>/history", methods=["GET"])
def api_subscription_history(sub_id):
    """وب‌سرویس دریافت سوابق و تاریخچه دوره‌های قبلی و مصرف یک اشتراک"""
    if not session.get("logged_in"):
        return jsonify({"success": False, "error": "احراز هویت لازم است"}), 401

    reseller_id = session.get("reseller_id") if session.get("role") == "reseller" else None
    data = db.get_subscription_full_details_and_history(sub_id, reseller_id=reseller_id)
    return jsonify(data)


@app.route("/api/subscription/<int:sub_id>/history/add", methods=["POST"])
def api_add_subscription_history(sub_id):
    """وب‌سرویس افزودن دستی سابقه دوره قبلی برای یک اشتراک (توسط مدیر یا نماینده)"""
    if not session.get("logged_in"):
        return jsonify({"success": False, "error": "احراز هویت لازم است"}), 401

    role = session.get("role")
    reseller_id = session.get("reseller_id") if role == "reseller" else None
    
    if role not in ["admin", "superadmin", "reseller", "manager"]:
        return jsonify({"success": False, "error": "عدم دسترسی کافی"}), 403

    payload = request.get_json(silent=True) or request.form.to_dict()
    if not payload:
        return jsonify({"success": False, "error": "داده‌های ارسالی نامعتبر است"}), 400
    
    try:
        usage_gb = float(payload.get("previous_usage_gb") or payload.get("usage_gb") or 0)
    except (ValueError, TypeError):
        return jsonify({"success": False, "error": "میزان حجم مصرفی معتبر نیست"}), 400

    limit_gb = None
    if payload.get("previous_limit_gb") or payload.get("limit_gb"):
        try:
            limit_gb = float(payload.get("previous_limit_gb") or payload.get("limit_gb"))
        except (ValueError, TypeError):
            limit_gb = None

    period_days = 30
    if payload.get("period_days"):
        try:
            period_days = int(payload.get("period_days"))
        except (ValueError, TypeError):
            period_days = 30

    period_offset = 1
    if payload.get("period_offset"):
        try:
            period_offset = int(payload.get("period_offset"))
        except (ValueError, TypeError):
            period_offset = 1

    period_label = payload.get("period_label") or payload.get("custom_label") or ""
    plan_name = payload.get("plan_name") or ""
    
    cost_paid = 0
    if payload.get("cost_paid") or payload.get("plan_price"):
        try:
            cost_paid = int(payload.get("cost_paid") or payload.get("plan_price"))
        except (ValueError, TypeError):
            cost_paid = 0

    note = payload.get("note") or payload.get("description") or ""
    renewed_at = payload.get("renewed_at") or None
    created_by = f"reseller_{reseller_id}" if reseller_id else (session.get("username") or "admin")

    res = db.add_manual_subscription_history(
        subscription_id=sub_id,
        previous_usage_gb=usage_gb,
        previous_limit_gb=limit_gb,
        period_days=period_days,
        period_offset=period_offset,
        period_label=period_label,
        plan_name=plan_name,
        plan_price=cost_paid,
        cost_paid=cost_paid,
        note=note,
        created_by=created_by,
        reseller_id=reseller_id,
        renewed_at=renewed_at
    )

    if res.get("success"):
        logger.info(f"Manual subscription history added for sub #{sub_id} by {created_by}: {usage_gb} GB, offset {period_offset}")
        return jsonify(res)
    else:
        return jsonify(res), 400


@app.route("/api/subscription/history/<int:history_id>/delete", methods=["POST"])
def api_delete_subscription_history(history_id):
    """وب‌سرویس حذف یک سابقه دوره دستی"""
    if not session.get("logged_in"):
        return jsonify({"success": False, "error": "احراز هویت لازم است"}), 401

    role = session.get("role")
    reseller_id = session.get("reseller_id") if role == "reseller" else None
    
    if role not in ["admin", "superadmin", "reseller", "manager"]:
        return jsonify({"success": False, "error": "عدم دسترسی کافی"}), 403

    ok = db.delete_subscription_history_entry(history_id, reseller_id=reseller_id)
    if ok:
        created_by = f"reseller_{reseller_id}" if reseller_id else (session.get("username") or "admin")
        logger.info(f"Subscription history #{history_id} deleted by {created_by}")
        return jsonify({"success": True, "message": "سابقه دوره با موفقیت حذف گردید"})
    else:
        return jsonify({"success": False, "error": "رکورد مورد نظر یافت نشد یا دسترسی حذف آن را ندارید"}), 400



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
        elif action == "save_admin_bank_sms":
            enabled = bool(request.form.get("bank_sms_enabled"))
            digits = int(request.form.get("bank_sms_digits", 3))
            timeout = int(request.form.get("bank_sms_timeout", 15))
            regenerate = bool(request.form.get("regenerate_token"))
            db.save_admin_bank_sms_config(enabled=enabled, digits=digits, timeout=timeout, regenerate_token=regenerate)
            flash("تنظیمات تایید خودکار کارت به کارت با پیامک بانک برای مدیریت با موفقیت ذخیره شد.", "success")

        return redirect(url_for("cards"))

    cards_list = db.get_all_bank_cards()
    payment_methods = db.get_payment_methods()
    admin_gateway = db.get_admin_gateway()
    crypto_config = CryptoPaymentGateway.get_crypto_config(db)

    domain = db.get_setting("custom_domain") or os.getenv("PANEL_DOMAIN", "http://localhost:5000")
    if not str(domain).startswith("http"):
        domain = f"https://{domain}"
    blupal_webhook_url = f"{str(domain).rstrip('/')}/payment/blupal/webhook"
    blupal_callback_url = f"{str(domain).rstrip('/')}/payment/blupal/callback"

    admin_bank_sms = db.get_admin_bank_sms_config()
    bank_sms_webhook_url = f"{str(domain).rstrip('/')}/api/bank-sms/webhook?token={admin_bank_sms['token']}"
    bank_sms_logs = db.get_bank_sms_logs(owner_type="admin", limit=15)

    return render_template(
        "cards.html",
        cards=cards_list,
        payment_methods=payment_methods,
        admin_gateway=admin_gateway,
        crypto_config=crypto_config,
        blupal_webhook_url=blupal_webhook_url,
        blupal_callback_url=blupal_callback_url,
        admin_bank_sms=admin_bank_sms,
        bank_sms_webhook_url=bank_sms_webhook_url,
        bank_sms_logs=bank_sms_logs
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
    """مدیریت و ویرایش کامل پلن‌ها با تفکیک پلن‌های مدیریت و پلن‌های نمایندگان"""
    current_tab = request.args.get("tab", "admin")  # 'admin' or 'resellers'
    reseller_id_param = request.args.get("reseller_id", "")
    selected_reseller_id = int(reseller_id_param) if reseller_id_param.isdigit() else None

    if request.method == "POST":
        action = request.form.get("action")
        if action == "add":
            name = request.form.get("name", "").strip()
            price = int(request.form.get("price", 0))
            data_limit = int(request.form.get("data_limit", 0))
            duration = int(request.form.get("duration", 30))
            plan_icon = request.form.get("plan_icon", "").strip()

            target_type = request.form.get("target_type", "all")
            allowed_resellers = []
            is_exclusive_admin = False
            is_exclusive_reseller = False

            if target_type == "admin":
                is_exclusive_admin = True
            elif target_type == "resellers":
                allowed_resellers = [int(x) for x in request.form.getlist("allowed_resellers") if str(x).isdigit()]
                is_exclusive_reseller = True
            else:
                # اگر سوییچ قدیمی فرستاده شده باشد
                if request.form.get("is_exclusive_admin") in ("on", "1", "true"):
                    is_exclusive_admin = True

            res = add_plan(
                name=name,
                price=price,
                data_limit=data_limit,
                duration=duration,
                is_exclusive_admin=is_exclusive_admin,
                plan_icon=plan_icon,
                allowed_resellers=allowed_resellers,
                is_exclusive_reseller=is_exclusive_reseller
            )
            if res.get("success"):
                flash("پلن جدید با موفقیت افزوده شد.", "success")
            else:
                flash(f"خطا در افزودن پلن: {res.get('error')}", "danger")
        return redirect(url_for("admin_plans_page", tab=current_tab, reseller_id=reseller_id_param if reseller_id_param else None))

    plans = get_all_plans()
    resellers_list = db.get_all_resellers()
    resellers_map = {r["id"]: r for r in resellers_list}
    selected_reseller = db.get_reseller(selected_reseller_id) if selected_reseller_id else None
    selected_reseller_plans = db.get_reseller_plans(selected_reseller_id) if selected_reseller_id else []

    # محاسبه پلن‌های پیش‌فرض نمایندگان با تخفیف پایه ۲۰ درصد (پلن‌های اختصاصی مدیریت و پلن‌های اختصاصی نمایندگان خاص حذف می‌شوند)
    default_reseller_plans = []
    for pid, p in plans.items():
        if p.get("is_exclusive_admin") or p.get("allowed_resellers") or p.get("is_exclusive_reseller"):
            continue
        base_price = p.get("price", 0)
        default_reseller_plans.append({
            "plan_id": pid,
            "name": p.get("name", "پلن"),
            "price": base_price,
            "wholesale_price": int(base_price * 0.8),
            "data_limit": p.get("data_limit", 0),
            "duration": p.get("duration", 30),
            "plan_icon": p.get("plan_icon", ""),
            "is_active": p.get("is_active", True)
        })

    # پلن‌های اختصاصی تعریف‌شده در کل سیستم برای نمایش در نمای کلی تب همکاران
    dedicated_reseller_plans = []
    for pid, p in plans.items():
        allowed = p.get("allowed_resellers") or []
        if allowed or p.get("is_exclusive_reseller"):
            r_names = [resellers_map.get(r_id, {}).get("name", f"نماینده #{r_id}") for r_id in allowed]
            dedicated_reseller_plans.append({
                "plan_id": pid,
                "name": p.get("name", "پلن"),
                "price": p.get("price", 0),
                "data_limit": p.get("data_limit", 0),
                "duration": p.get("duration", 30),
                "plan_icon": p.get("plan_icon", ""),
                "is_active": p.get("is_active", True),
                "allowed_resellers": allowed,
                "reseller_names": r_names
            })

    return render_template(
        "plans.html",
        plans=plans,
        current_tab=current_tab,
        resellers_list=resellers_list,
        resellers_map=resellers_map,
        selected_reseller_id=selected_reseller_id,
        selected_reseller=selected_reseller,
        selected_reseller_plans=selected_reseller_plans,
        default_reseller_plans=default_reseller_plans,
        dedicated_reseller_plans=dedicated_reseller_plans
    )


@app.route("/admin/reseller/plan/override", methods=["POST"])
@permission_required("plans_manage")
def admin_reseller_plan_override():
    """شخصی‌سازی پلن اختصاصی برای یک نماینده توسط مدیر (نام، قیمت، حجم، مدت، وضعیت)"""
    reseller_id = int(request.form.get("reseller_id", 0))
    plan_id = request.form.get("plan_id", "").strip()
    custom_name = request.form.get("custom_name", "").strip()
    custom_price = int(request.form.get("custom_price", 0)) if request.form.get("custom_price") else None
    
    custom_data_limit_raw = request.form.get("custom_data_limit", "").strip()
    custom_data_limit = float(custom_data_limit_raw) if custom_data_limit_raw else None
    
    custom_duration_raw = request.form.get("custom_duration", "").strip()
    custom_duration = int(custom_duration_raw) if custom_duration_raw else None
    
    is_active = request.form.get("is_active") == "1"

    if reseller_id <= 0 or not plan_id:
        flash("شناسه نماینده و پلن نامعتبر است.", "danger")
        return redirect(url_for("admin_plans_page", tab="resellers"))

    res = db.update_reseller_plan_override(
        reseller_id=reseller_id,
        plan_id=plan_id,
        custom_name=custom_name,
        custom_price=custom_price,
        custom_data_limit=custom_data_limit,
        custom_duration=custom_duration,
        is_active=is_active
    )
    if res.get("success"):
        flash("تنظیمات پلن اختصاصی نماینده با موفقیت ذخیره شد.", "success")
    else:
        flash(f"خطا در ثبت پلن: {res.get('error')}", "danger")
    return redirect(url_for("admin_plans_page", tab="resellers", reseller_id=reseller_id))


@app.route("/admin/reseller/plan/reset", methods=["POST"])
@permission_required("plans_manage")
def admin_reseller_plan_reset():
    """بازنشانی پلن سفارشی نماینده به حالت پیش‌فرض"""
    reseller_id = int(request.form.get("reseller_id", 0))
    plan_id = request.form.get("plan_id", "").strip()
    if reseller_id > 0 and plan_id:
        db.reset_reseller_plan_override(reseller_id, plan_id)
        flash("پلن نماینده با موفقیت به حالت پیش‌فرض بازگردانده شد.", "info")
    return redirect(url_for("admin_plans_page", tab="resellers", reseller_id=reseller_id))


@app.route("/admin/reseller/plan/add_dedicated", methods=["POST"])
@permission_required("plans_manage")
def admin_reseller_add_dedicated_plan():
    """افزودن مستقیم پلن اختصاصی برای یک نماینده از تب مدیریت پلن‌های نمایندگان"""
    primary_reseller_id = int(request.form.get("reseller_id", 0))
    name = request.form.get("name", "").strip()
    price = int(request.form.get("price", 0))
    data_limit = int(request.form.get("data_limit", 0))
    duration = int(request.form.get("duration", 30))
    plan_icon = request.form.get("plan_icon", "").strip()
    
    additional_resellers = request.form.getlist("additional_resellers")
    selected_resellers = set()
    if primary_reseller_id > 0:
        selected_resellers.add(primary_reseller_id)
    for r in additional_resellers:
        if str(r).isdigit() and int(r) > 0:
            selected_resellers.add(int(r))

    if not selected_resellers or not name or price < 0:
        flash("اطلاعات پلن اختصاصی نامعتبر است.", "danger")
        return redirect(url_for("admin_plans_page", tab="resellers", reseller_id=primary_reseller_id if primary_reseller_id else None))

    res = add_plan(
        name=name,
        price=price,
        data_limit=data_limit,
        duration=duration,
        is_exclusive_admin=False,
        plan_icon=plan_icon,
        allowed_resellers=list(selected_resellers),
        is_exclusive_reseller=True
    )
    if res.get("success"):
        flash("پلن اختصاصی جدید با موفقیت برای نماینده تعریف شد و از سایرین کاملاً مخفی خواهد بود.", "success")
    else:
        flash(f"خطا در ایجاد پلن اختصاصی: {res.get('error')}", "danger")

    return redirect(url_for("admin_plans_page", tab="resellers", reseller_id=primary_reseller_id if primary_reseller_id else None))


@app.route("/plans/edit/<plan_id>", methods=["POST"])
@permission_required("plans_manage")
def admin_plan_edit(plan_id):
    """ویرایش کامل مشخصات پلن و تغییر شناسه و سطح دسترسی"""
    new_plan_id = request.form.get("new_plan_id", "").strip().lower().replace(" ", "_")
    name = request.form.get("name", "").strip()
    price = int(request.form.get("price", 0))
    data_limit = int(request.form.get("data_limit", 0))
    duration = int(request.form.get("duration", 30))
    is_active = request.form.get("is_active") == "1"
    plan_icon = request.form.get("plan_icon", "").strip()

    target_type = request.form.get("target_type")
    is_exclusive_admin = False
    allowed_resellers = None
    is_exclusive_reseller = False

    if target_type == "admin":
        is_exclusive_admin = True
        allowed_resellers = []
        is_exclusive_reseller = False
    elif target_type == "resellers":
        is_exclusive_admin = False
        allowed_resellers = [int(x) for x in request.form.getlist("allowed_resellers") if str(x).isdigit()]
        is_exclusive_reseller = True
    elif target_type == "all":
        is_exclusive_admin = False
        allowed_resellers = []
        is_exclusive_reseller = False
    else:
        is_exclusive_admin = request.form.get("is_exclusive_admin") in ("on", "1", "true")
        allowed_resellers = None

    update_kwargs = {
        "name": name,
        "price": price,
        "data_limit": data_limit,
        "duration": duration,
        "is_active": is_active,
        "is_exclusive_admin": is_exclusive_admin,
        "plan_icon": plan_icon,
    }
    if allowed_resellers is not None:
        update_kwargs["allowed_resellers"] = allowed_resellers
        update_kwargs["is_exclusive_reseller"] = is_exclusive_reseller

    if new_plan_id and new_plan_id != plan_id:
        update_kwargs["new_plan_id"] = new_plan_id

    res = update_plan(plan_id, **update_kwargs)
    if res.get("success"):
        flash("پلن با موفقیت بروزرسانی شد.", "success")
    else:
        flash(f"خطا در ویرایش پلن: {res.get('error')}", "danger")

    return_tab = request.form.get("return_tab") or request.args.get("tab", "admin")
    reseller_id_param = request.form.get("reseller_id") or request.args.get("reseller_id", "")
    return redirect(url_for("admin_plans_page", tab=return_tab, reseller_id=reseller_id_param if reseller_id_param else None))


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
    tab = request.args.get("tab", "admin")
    reseller_id = request.args.get("reseller_id", "")
    res = delete_plan(plan_id)
    if res.get("success"):
        flash("پلن حذف شد.", "warning")
    else:
        flash(f"خطا در حذف پلن: {res.get('error')}", "danger")
    return redirect(url_for("admin_plans_page", tab=tab, reseller_id=reseller_id if reseller_id else None))


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
    """گزارشات آماری و هوش مالی پیشرفته مدیر کل با تفکیک ۳ تب: همه، مشتریان مدیریت و نمایندگان"""
    active_tab = request.args.get("tab", "all").strip()
    period = request.args.get("period", "month").strip()
    if period not in ("today", "week", "month", "year", "all"):
        period = "month"

    conn = db.get_connection()
    total_revenue = conn.execute("SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE status IN ('approved', 'completed')").fetchone()[0]
    total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    active_subs = conn.execute("SELECT COUNT(*) FROM subscriptions WHERE (is_deleted = 0 OR is_deleted IS NULL) AND status='active'").fetchone()[0]
    monthly_revenue = conn.execute("""
        SELECT strftime('%Y-%m', created_at) as month, SUM(amount) as total, COUNT(*) as count
        FROM transactions WHERE status IN ('approved', 'completed')
        GROUP BY strftime('%Y-%m', created_at) ORDER BY month DESC LIMIT 12
    """).fetchall()
    conn.close()

    analytics = db.get_advanced_analytics()
    financial_data = db.get_financial_reports_data(period=period)

    return render_template(
        "reports.html",
        active_tab=active_tab,
        period=period,
        financial_data=financial_data,
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
        WHERE ((reseller_id IS NULL OR reseller_id = 0) OR (reseller_id IS NOT NULL AND reseller_id > 0 AND (gateway = 'bundle_reseller' OR order_id LIKE 'R_BUNDLE%')))
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
    """مشاهده وضعیت سرورها، پایش عملکرد، تحلیل مغایرت‌ها و گزارش جامع لاگ‌های وقایع سیستم"""
    health = hidify_sync_ping()
    
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 50, type=int)
    category = request.args.get("category", "all").strip()
    action = request.args.get("action", "all").strip()
    level = request.args.get("level", "all").strip()
    time_range = request.args.get("time_range", "all").strip()
    search = request.args.get("search", "").strip()

    logs, total_count = db.get_system_logs(
        page=page,
        per_page=per_page,
        category=category,
        action=action,
        level=level,
        search=search,
        time_range=time_range
    )
    stats = db.get_system_logs_stats()
    total_pages = max(1, (total_count + per_page - 1) // per_page)
    
    # آمار تطبیقی دیتابیس محلی و سرور هیدیفای
    db_active_count = 0
    db_deleted_count = 0
    try:
        conn = db.get_connection()
        db_active_count = conn.execute("SELECT COUNT(*) FROM subscriptions WHERE is_deleted = 0").fetchone()[0]
        db_deleted_count = conn.execute("SELECT COUNT(*) FROM subscriptions WHERE is_deleted = 1").fetchone()[0]
        conn.close()
    except Exception:
        pass
        
    hiddify_count = health.get("users_count", 0) if health.get("online") else 0
    count_diff = db_active_count - hiddify_count

    return render_template(
        "logs.html",
        health=health,
        logs=logs,
        stats=stats,
        page=page,
        per_page=per_page,
        total_count=total_count,
        total_pages=total_pages,
        category=category,
        action=action,
        level=level,
        time_range=time_range,
        search=search,
        db_active_count=db_active_count,
        db_deleted_count=db_deleted_count,
        hiddify_count=hiddify_count,
        count_diff=count_diff
    )


@app.route("/admin/logs/audit-diff", methods=["GET", "POST"])
@permission_required("servers_view")
def admin_logs_audit_diff():
    """
    تحلیل هوشمند و کشف مغایرت‌های کاربران سرور هیدیفای با دیتابیس محلی
    شناسایی دقیق اکانت‌هایی که در دیتابیس فعال هستند اما در پنل هیدیفای مفقود شده‌اند (یا برعکس)
    """
    try:
        # ۱. دریافت لیست کاربران از سرور هیدیفای
        h_users = hidify_sync_request("GET", "/admin/user/")
        if isinstance(h_users, dict) and "error" in h_users:
            err_msg = f"خطا در ارتباط با هیدیفای: {h_users.get('error')}"
            if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.args.get("format") == "json":
                return jsonify({"success": False, "error": err_msg}), 500
            flash(err_msg, "danger")
            return redirect(url_for("admin_logs"))

        if not isinstance(h_users, list):
            h_users = []

        h_map = {}
        for u in h_users:
            u_uuid = str(u.get("uuid") or "").strip().lower()
            if u_uuid:
                h_map[u_uuid] = u

        # ۲. دریافت اشتراک‌های فعال از دیتابیس محلی
        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, account_name, hidify_uuid, status, duration, data_limit, data_used, reseller_id, created_at, expire_date FROM subscriptions WHERE is_deleted = 0")
        db_subs = [dict(r) for r in cursor.fetchall()]
        conn.close()

        db_map = {}
        missing_in_hiddify = []
        for s in db_subs:
            s_uuid = str(s.get("hidify_uuid") or "").strip().lower()
            if s_uuid:
                db_map[s_uuid] = s
                if s_uuid not in h_map:
                    missing_in_hiddify.append({
                        "id": s["id"],
                        "name": s.get("account_name"),
                        "uuid": s.get("hidify_uuid"),
                        "status": s.get("status"),
                        "expire_date": s.get("expire_date"),
                        "reseller_id": s.get("reseller_id")
                    })

        missing_in_db = []
        for u_uuid, u in h_map.items():
            if u_uuid not in db_map:
                missing_in_db.append({
                    "name": u.get("name"),
                    "uuid": u_uuid,
                    "usage_limit_gb": u.get("usage_limit_GB"),
                    "current_usage_gb": u.get("current_usage_GB"),
                    "enable": u.get("enable")
                })

        # ۳. ثبت لاگ حسابرسی
        log_title = f"تحلیل مغایرت: {len(missing_in_hiddify)} اشتراک مفقود در هیدیفای" if missing_in_hiddify else "تحلیل مغایرت: تطابق کامل هیدیفای و دیتابیس"
        log_level = "warning" if missing_in_hiddify else "success"
        log_desc = (
            f"بررسی مغایرت انجام شد. تعداد کل در دیتابیس: {len(db_subs):,} | "
            f"تعداد در هیدیفای: {len(h_map):,} | "
            f"مفقود در هیدیفای: {len(missing_in_hiddify):,} | "
            f"ناشناخته در هیدیفای: {len(missing_in_db):,}"
        )

        db.add_system_log(
            category="system",
            action="sync_diff",
            title=log_title,
            description=log_desc,
            actor_type="admin",
            actor_name=session.get("username", "مدیر سیستم"),
            target_type="system",
            target_name="هیدیفای vs دیتابیس",
            details={
                "db_active_count": len(db_subs),
                "hiddify_count": len(h_map),
                "missing_in_hiddify_count": len(missing_in_hiddify),
                "missing_in_db_count": len(missing_in_db),
                "missing_in_hiddify_sample": missing_in_hiddify[:50],
                "missing_in_db_sample": missing_in_db[:50]
            },
            level=log_level,
            ip_address=request.remote_addr
        )

        resp_data = {
            "success": True,
            "db_count": len(db_subs),
            "hiddify_count": len(h_map),
            "missing_in_hiddify_total": len(missing_in_hiddify),
            "missing_in_hiddify": missing_in_hiddify[:100],
            "missing_in_db_total": len(missing_in_db),
            "missing_in_db": missing_in_db[:100],
            "message": log_desc
        }

        if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.args.get("format") == "json":
            return jsonify(resp_data)

        flash(f"تحلیل مغایرت با موفقیت انجام شد: {len(missing_in_hiddify):,} کاربر دیتابیس در پنل هیدیفای یافت نشدند.", "warning" if missing_in_hiddify else "success")
        return redirect(url_for("admin_logs"))

    except Exception as e:
        logger.error(f"Error in admin_logs_audit_diff: {e}")
        if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.args.get("format") == "json":
            return jsonify({"success": False, "error": str(e)}), 500
        flash(f"خطا در تحلیل مغایرت: {e}", "danger")
        return redirect(url_for("admin_logs"))


@app.route("/admin/logs/export")
@permission_required("servers_view")
def admin_logs_export():
    """خروجی فایل اکسل/CSV از لاگ‌های فیلتر شده با کدگذاری استاندارد UTF-8 BOM"""
    category = request.args.get("category", "all").strip()
    action = request.args.get("action", "all").strip()
    level = request.args.get("level", "all").strip()
    time_range = request.args.get("time_range", "all").strip()
    search = request.args.get("search", "").strip()

    logs, _ = db.get_system_logs(
        page=1,
        per_page=10000,
        category=category,
        action=action,
        level=level,
        search=search,
        time_range=time_range
    )

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "شناسه",
        "تاریخ و ساعت شمسی",
        "تاریخ میلادی",
        "دسته‌بندی",
        "نوع عملیات",
        "سطح اهمیت",
        "نوع عامل",
        "نام عامل",
        "نوع هدف",
        "شناسه هدف",
        "نام هدف",
        "عنوان رویداد",
        "شرح کامل",
        "آدرس IP"
    ])

    cat_names = {
        "system": "سیستم و خودکار",
        "admin": "مدیران",
        "reseller": "نمایندگان",
        "user_bot": "کاربران و ربات",
        "security": "امنیت و دسترسی"
    }

    for lg in logs:
        c_at = lg.get("created_at") or ""
        shamsi_dt = gregorian_to_shamsi_full(c_at) if c_at else "-"
        writer.writerow([
            lg.get("id"),
            shamsi_dt,
            c_at[:19].replace("T", " "),
            cat_names.get(lg.get("category"), lg.get("category")),
            lg.get("action") or "-",
            lg.get("level") or "-",
            lg.get("actor_type") or "-",
            lg.get("actor_name") or "-",
            lg.get("target_type") or "-",
            lg.get("target_id") or "-",
            lg.get("target_name") or "-",
            lg.get("title") or "-",
            lg.get("description") or "-",
            lg.get("ip_address") or "-"
        ])

    csv_data = "\ufeff" + output.getvalue()
    return Response(
        csv_data.encode("utf-8-sig"),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment;filename=system_activity_logs.csv"}
    )


@app.route("/admin/logs/clear", methods=["POST"])
@super_admin_required
def admin_logs_clear():
    """پاکسازی لاگ‌های قدیمی سیستم توسط مدیر ارشد"""
    days = request.form.get("days", 90, type=int)
    deleted = db.clear_old_system_logs(days=days)
    db.add_system_log(
        category="system",
        action="purge_logs",
        title=f"پاکسازی {deleted} لاگ قدیمی سیستم",
        description=f"تعداد {deleted} رکورد لاگ قدیمی‌تر از {days} روز توسط مدیر ارشد ({session.get('username')}) پاکسازی گردید.",
        actor_type="admin",
        actor_name=session.get("username", "admin"),
        level="info",
        ip_address=request.remote_addr
    )
    flash(f"{deleted:,} لاگ قدیمی‌تر از {days} روز با موفقیت پاکسازی شد.", "success")
    return redirect(url_for("admin_logs"))


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
            sms_url = request.form.get("sms_url", "").strip()
            sms_pattern_login = request.form.get("sms_pattern_login", "").strip()
            sms_pattern_failed = request.form.get("sms_pattern_failed", "").strip()
            sms_pattern_logout = request.form.get("sms_pattern_logout", "").strip()

            db.save_setting("sms_enabled", sms_enabled)
            db.save_setting("sms_provider", sms_provider)
            if sms_api_key:
                db.save_setting("sms_api_key", sms_api_key)
            db.save_setting("sms_originator", sms_originator)
            db.save_setting("sms_url", sms_url)
            db.save_setting("sms_generic_url", sms_url)
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
            troubleshoot_domain = request.form.get("troubleshoot_domain", "").strip().lower()
            tutorial_title = request.form.get("tutorial_title", "").strip()
            db.save_setting("tutorial_domain", tutorial_domain)
            db.save_setting("troubleshoot_domain", troubleshoot_domain)
            db.save_setting("tutorial_title", tutorial_title)
            flash("تنظیمات دامنه‌ها و عنوان پورتال آموزش‌ها با موفقیت ذخیره شد.", "success")
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
        elif action == "save_refund_settings":
            refund_enabled = request.form.get("refund_enabled") == "on"
            rate_12h = int(request.form.get("refund_rate_before_12h") or request.form.get("refund_before_12h") or 100)
            rate_24h = int(request.form.get("refund_rate_before_24h") or request.form.get("refund_before_24h") or 80)
            calc_from_creation = request.form.get("refund_calc_from_creation") == "on"
            
            raw_dis = request.form.getlist("refund_disabled_resellers") or request.form.getlist("disabled_resellers")
            disabled_resellers = []
            for d in raw_dis:
                try:
                    disabled_resellers.append(int(d))
                except (ValueError, TypeError):
                    pass

            daily_restore_limit = int(request.form.get("daily_restore_limit") or 10)
            restore_window_days = int(request.form.get("restore_window_days") or 7)

            all_res = db.get_all_resellers()
            reseller_daily_restore_limits = {}
            for r in all_res:
                r_id = str(r["id"])
                val = request.form.get(f"reseller_restore_limit_{r_id}")
                if val is not None and val.strip() != "":
                    try:
                        reseller_daily_restore_limits[r_id] = int(val.strip())
                    except ValueError:
                        pass

            db.save_refund_settings({
                "refund_enabled": refund_enabled,
                "refund_rate_before_12h": rate_12h,
                "refund_rate_before_24h": rate_24h,
                "refund_calc_from_creation": calc_from_creation,
                "refund_disabled_resellers": disabled_resellers,
                "daily_restore_limit": daily_restore_limit,
                "restore_window_days": restore_window_days,
                "reseller_daily_restore_limits": reseller_daily_restore_limits
            })
            flash("تنظیمات هوشمند استرداد وجه و سطل زباله نمایندگان با موفقیت ذخیره شد.", "success")
            return redirect(url_for("settings"))
        elif action == "save_store_branding":
            store_name = request.form.get("store_name", "").strip()
            store_version = request.form.get("store_version", "").strip()
            store_version_source = request.form.get("store_version_source", "manual").strip()
            store_github_repo = request.form.get("store_github_repo", "").strip()
            store_copyright = request.form.get("store_copyright", "").strip()
            store_primary_color = request.form.get("store_primary_color", "#4f46e5").strip()
            existing_store_logo = db.get_setting("store_logo", "")
            store_logo_url = request.form.get("store_logo_url", existing_store_logo).strip()
            brand_header_style = request.form.get("brand_header_style", "style_glass").strip()
            version_icon_type = request.form.get("version_icon_type", "branch").strip()
            existing_version_icon = db.get_setting("version_custom_icon", "")
            version_custom_icon = request.form.get("version_custom_icon", existing_version_icon).strip()

            if request.form.get("clear_store_logo"):
                store_logo_url = ""
            elif "store_logo_file" in request.files:
                file = request.files["store_logo_file"]
                if file and file.filename:
                    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else "png"
                    fn = f"system_store_logo_{int(time.time())}.{ext}"
                    fp = AVATAR_CACHE_DIR / fn
                    file.save(fp)
                    store_logo_url = url_for("telegram_avatar", identifier=fn)

            if request.form.get("clear_version_custom_icon"):
                version_custom_icon = ""
            elif "version_icon_file" in request.files:
                v_file = request.files["version_icon_file"]
                if v_file and v_file.filename:
                    ext = v_file.filename.rsplit(".", 1)[-1].lower() if "." in v_file.filename else "svg"
                    fn = f"system_version_icon_{int(time.time())}.{ext}"
                    fp = AVATAR_CACHE_DIR / fn
                    v_file.save(fp)
                    version_custom_icon = url_for("telegram_avatar", identifier=fn)

            if store_name:
                db.save_setting("store_name", store_name)
            if store_version:
                db.save_setting("store_version", store_version)
            db.save_setting("store_version_source", store_version_source)
            db.save_setting("store_github_repo", store_github_repo)
            if store_copyright:
                db.save_setting("store_copyright", store_copyright)
            if store_primary_color:
                db.save_setting("store_primary_color", store_primary_color)
            db.save_setting("store_logo", store_logo_url)
            db.save_setting("brand_header_style", brand_header_style)
            db.save_setting("version_icon_type", version_icon_type)
            db.save_setting("version_custom_icon", version_custom_icon)

            _store_version_cache["version"] = None
            _store_version_cache["timestamp"] = 0

            flash("تنظیمات هویت بصری، استایل سربرگ، نسخه و لوگوی سیستم با موفقیت ذخیره شد.", "success")
            return redirect(url_for("settings"))
        elif action == "save_customer_portal_settings":
            portal_proxy_path = request.form.get("portal_proxy_path", "renew").strip("/").strip()
            if not portal_proxy_path:
                portal_proxy_path = "renew"
            portal_title = request.form.get("portal_title", "").strip()
            portal_subtitle = request.form.get("portal_subtitle", "").strip()
            support_phone = request.form.get("support_phone", "").strip()
            support_username = request.form.get("support_username", "").strip().lstrip("@")
            portal_enable_renewal = "1" if request.form.get("portal_enable_renewal") else "0"
            portal_show_troubleshoot = "1" if request.form.get("portal_show_troubleshoot") else "0"
            portal_layout = request.form.get("portal_layout", "classic").strip().lower()
            portal_plan_style = request.form.get("portal_plan_style", "glass_classic").strip().lower()

            db.save_setting("portal_proxy_path", portal_proxy_path)
            db.save_setting("portal_title", portal_title)
            db.save_setting("portal_subtitle", portal_subtitle)
            db.save_setting("support_phone", support_phone)
            db.save_setting("support_username", support_username)
            db.save_setting("portal_enable_renewal", portal_enable_renewal)
            db.save_setting("portal_show_troubleshoot", portal_show_troubleshoot)
            db.save_setting("portal_layout", portal_layout)
            db.save_setting("portal_plan_style", portal_plan_style)

            server_status_mode = request.form.get("server_status_mode", "smart").strip().lower()
            server_status_manual_state = request.form.get("server_status_manual_state", "operational").strip().lower()
            server_status_custom_text = request.form.get("server_status_custom_text", "").strip()

            db.save_setting("server_status_mode", server_status_mode)
            db.save_setting("server_status_manual_state", server_status_manual_state)
            db.save_setting("server_status_custom_text", server_status_custom_text)

            flash("تنظیمات پورتال اختصاصی مشتری، قالب ظاهری، استایل دکمه‌ها، پروکسی پچ و وضعیت سرورها با موفقیت ذخیره شد.", "success")
            return redirect(url_for("settings"))
        elif action == "save_login_appearance_settings":
            login_style = request.form.get("login_style", "glass_aurora").strip().lower()
            login_page_title = request.form.get("login_page_title", "").strip()
            login_page_subtitle = request.form.get("login_page_subtitle", "").strip()
            login_bg_effect = "1" if request.form.get("login_bg_effect") else "0"

            db.save_setting("login_style", login_style)
            db.save_setting("login_page_title", login_page_title)
            db.save_setting("login_page_subtitle", login_page_subtitle)
            db.save_setting("login_bg_effect", login_bg_effect)

            flash("تنظیمات ظاهر و استایل صفحه لاگین با موفقیت ذخیره شد.", "success")
            return redirect(url_for("settings"))
        elif action == "save_login_security_settings":
            admin_login_proxy_path = request.form.get("admin_login_proxy_path", "").strip("/").strip()
            db.save_setting("admin_login_proxy_path", admin_login_proxy_path)

            if "login_style" in request.form:
                login_style = request.form.get("login_style", "glass_aurora").strip().lower()
                login_page_title = request.form.get("login_page_title", "").strip()
                login_page_subtitle = request.form.get("login_page_subtitle", "").strip()
                login_bg_effect = "1" if request.form.get("login_bg_effect") else "0"

                db.save_setting("login_style", login_style)
                db.save_setting("login_page_title", login_page_title)
                db.save_setting("login_page_subtitle", login_page_subtitle)
                db.save_setting("login_bg_effect", login_bg_effect)

            flash("تنظیمات امنیت ورود، پروکسی پچ دسترسی و استایل صفحه لاگین با موفقیت ذخیره شد.", "success")
            return redirect(url_for("settings"))
        elif action == "save_palette_settings":
            active_palette = request.form.get("active_palette", "vps_aurora").strip()
            palette_intensity = request.form.get("palette_intensity", "normal").strip()
            palette_animation = request.form.get("palette_animation", "float").strip()
            portal_palette = request.form.get("portal_palette", "inherit").strip()

            db.save_setting("active_palette", active_palette)
            db.save_setting("palette_intensity", palette_intensity)
            db.save_setting("palette_animation", palette_animation)
            db.save_setting("portal_palette", portal_palette)

            # در صورت تیک زدن همگام‌سازی رنگ سازمانی، رنگ شاخص نیز مطابق پالت تنظیم شود
            sync_primary = request.form.get("sync_primary_color")
            if sync_primary:
                pal_data = get_palette(active_palette)
                db.save_setting("store_primary_color", pal_data["primary_color"])

            flash("تنظیمات پالت‌های رنگی، هاله‌های نوری و افکت شیشه‌ای مات با موفقیت ذخیره شد.", "success")
            return redirect(url_for("settings"))
        elif action == "save_chat_settings":
            chat_button_style = request.form.get("chat_button_style", "modern_pill").strip()
            chat_button_text = request.form.get("chat_button_text", "گفتگوی آنلاین").strip()
            chat_button_position = request.form.get("chat_button_position", "right").strip()
            chat_fake_online_mode = request.form.get("chat_fake_online_mode", "real").strip()
            chat_fake_online_agents = request.form.getlist("chat_fake_online_agents")
            chat_ai_enabled = "1" if request.form.get("chat_ai_enabled") else "0"
            chat_ai_mode = request.form.get("chat_ai_mode", "smart_local").strip()
            chat_ai_api_key = request.form.get("chat_ai_api_key", "").strip()
            chat_ai_api_url = request.form.get("chat_ai_api_url", "https://api.openai.com/v1/chat/completions").strip()
            chat_ai_model = request.form.get("chat_ai_model", "gpt-4o-mini").strip()
            chat_sound_enabled = "1" if request.form.get("chat_sound_enabled") else "0"

            db.save_chat_settings({
                "chat_button_style": chat_button_style,
                "chat_button_text": chat_button_text,
                "chat_button_position": chat_button_position,
                "chat_fake_online_mode": chat_fake_online_mode,
                "chat_fake_online_agents": chat_fake_online_agents,
                "chat_ai_enabled": chat_ai_enabled,
                "chat_ai_mode": chat_ai_mode,
                "chat_ai_api_key": chat_ai_api_key,
                "chat_ai_api_url": chat_ai_api_url,
                "chat_ai_model": chat_ai_model,
                "chat_sound_enabled": chat_sound_enabled
            })

            flash("تنظیمات ظاهر دکمه گفتگوی آنلاین، وضعیت ساختگی و چتبات هوش مصنوعی با موفقیت ذخیره شد.", "success")
            return redirect(url_for("settings"))

    conn = db.get_connection()
    settings_list = conn.execute("SELECT * FROM settings").fetchall()
    conn.close()
    single_link_template = get_single_link_template(db)
    sms_config = get_sms_config(db)
    crypto_config = CryptoPaymentGateway.get_crypto_config(db)
    admin_gateway = db.get_admin_gateway()
    tutorial_domain = db.get_setting("tutorial_domain", "")
    troubleshoot_domain = db.get_setting("troubleshoot_domain", "")
    tutorial_title = db.get_setting("tutorial_title", "راهنما و آموزش اتصال")
    vip_settings = db.get_vip_settings()
    refund_settings = db.get_refund_settings()
    all_resellers = db.get_all_resellers()
    store_branding_config = {
        "store_name": db.get_setting("store_name", "سامانه هوشمند اینترنت پرو"),
        "store_version": db.get_setting("store_version", "v0.0.1 Beta"),
        "store_version_source": db.get_setting("store_version_source", "manual"),
        "store_github_repo": db.get_setting("store_github_repo", ""),
        "store_copyright": db.get_setting("store_copyright", "تمامی حقوق برای این سامانه محفوظ است © 2026"),
        "store_primary_color": db.get_setting("store_primary_color", "#4f46e5"),
        "store_logo": db.get_setting("store_logo", ""),
        "logo_url": db.get_setting("store_logo", ""),
        "brand_header_style": db.get_setting("brand_header_style", "style_glass"),
        "version_icon_type": db.get_setting("version_icon_type", "branch"),
        "version_custom_icon": db.get_setting("version_custom_icon", ""),
        "current_active_version": get_store_version()
    }
    customer_portal_config = {
        "portal_proxy_path": get_portal_proxy_path(),
        "user_proxy_path": db.get_setting("user_proxy_path") or os.getenv("USER_PROXY_PATH", "user").strip("/"),
        "portal_title": db.get_setting("portal_title", "فروشگاه اینترنت آزاد"),
        "portal_subtitle": db.get_setting("portal_subtitle", "پورتال اختصاصی استعلام وضعیت و تمدید اشتراک"),
        "support_phone": db.get_setting("support_phone", ""),
        "support_username": db.get_setting("support_username", ""),
        "portal_enable_renewal": str(db.get_setting("portal_enable_renewal", "1")).lower() in ("1", "true"),
        "portal_show_troubleshoot": str(db.get_setting("portal_show_troubleshoot", "1")).lower() in ("1", "true"),
        "server_status_mode": db.get_setting("server_status_mode", "smart"),
        "server_status_manual_state": db.get_setting("server_status_manual_state", "operational"),
        "server_status_custom_text": db.get_setting("server_status_custom_text", ""),
        "portal_layout": db.get_setting("portal_layout", "classic"),
        "portal_plan_style": db.get_setting("portal_plan_style", "glass_classic")
    }
    login_security_config = {
        "admin_login_proxy_path": get_admin_login_proxy_path(),
        "login_style": db.get_setting("login_style", "glass_aurora"),
        "login_page_title": db.get_setting("login_page_title", ""),
        "login_page_subtitle": db.get_setting("login_page_subtitle", ""),
        "login_bg_effect": str(db.get_setting("login_bg_effect", "1")).lower() in ("1", "true"),
    }
    palette_settings = {
        "active_palette": db.get_setting("active_palette", "vps_aurora"),
        "palette_intensity": db.get_setting("palette_intensity", "normal"),
        "palette_animation": db.get_setting("palette_animation", "float"),
        "portal_palette": db.get_setting("portal_palette", "inherit")
    }
    chat_settings = db.get_chat_settings()

    return render_template(
        "settings.html",
        settings=settings_list,
        single_link_template=single_link_template,
        sms_config=sms_config,
        crypto_config=crypto_config,
        admin_gateway=admin_gateway,
        tutorial_domain=tutorial_domain,
        troubleshoot_domain=troubleshoot_domain,
        tutorial_title=tutorial_title,
        vip_settings=vip_settings,
        refund_settings=refund_settings,
        all_resellers=all_resellers,
        store_branding_config=store_branding_config,
        customer_portal_config=customer_portal_config,
        login_security_config=login_security_config,
        palette_settings=palette_settings,
        chat_settings=chat_settings,
        available_palettes=get_all_palettes()
    )


@app.route("/admin/sms/test", methods=["POST"])
@admin_required
def admin_sms_test():
    """ارسال پیامک آزمایشی جهت تست صحت اتصال به درگاه پیامکی"""
    test_phone = request.form.get("test_phone", "").strip()
    if not test_phone:
        return jsonify({"success": False, "error": "لطفاً شماره تلفن همراه را وارد نمایید."})

    cfg = get_sms_config(db)
    pattern = cfg.get("pattern_login")

    # چنانچه شماره خط اختصاصی تعریف نشده ولی پترن ورود تعریف شده، تست با پترن ارسال شود
    if not cfg.get("originator") and pattern and cfg.get("provider") in ("smsir", "sms.ir", "ippanel", "farazsms", "maxsms", "kavenegar"):
        pattern_data = {
            "name": "مدیر سیستم",
            "code": "123456",
            "ip": request.remote_addr or "127.0.0.1",
            "time": "اکنون"
        }
        success, msg = send_sms(
            receptor=test_phone,
            message="✅ تست اتصال به درگاه پیامکی سامانه HiddiBot با موفقیت انجام شد.",
            pattern_code=pattern,
            pattern_data=pattern_data,
            db_instance=db
        )
    else:
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
    """داشبورد اصلی نماینده فروش به همراه هوش مالی و خلاصه وضعیت اعتبار و بدهی"""
    sync_hiddify_online_users()
    reseller_id = session.get("reseller_id")
    reseller = db.get_reseller(reseller_id) or {}
    stats = db.get_reseller_stats(reseller_id)
    session["balance"] = stats["balance"]
    recent_transactions = db.get_reseller_transactions(reseller_id, limit=6)
    analytics = db.get_advanced_analytics(reseller_id=reseller_id)
    bot_status = multibot_manager.get_bot_status(reseller_id)
    fin_summary = db.get_reseller_financial_summary(reseller_id)
    revenue_7days = db.get_reseller_7days_revenue(reseller_id)
    traffic_blocks = get_hiddify_dashboard_traffic_stats(
        api_key=reseller.get("hiddify_admin_uuid"),
        reseller_id=reseller_id
    )
    return render_template(
        "reseller_dashboard.html",
        reseller=reseller,
        stats=stats,
        recent_transactions=recent_transactions,
        analytics=analytics,
        bot_status=bot_status,
        fin_summary=fin_summary,
        revenue_7days=revenue_7days,
        traffic_blocks=traffic_blocks
    )


@app.route("/reseller/create-user", methods=["GET", "POST"])
@reseller_required
def reseller_create_user():
    """ساخت آنی اشتراک مشتری توسط نماینده با کسر اعتبار عمده‌فروشی یا خرید اعتباری"""
    reseller_id = session.get("reseller_id")
    reseller = db.get_reseller(reseller_id) or {}
    stats = db.get_reseller_stats(reseller_id) or {}
    discount = stats.get("discount_percent", 20)
    
    # بارگذاری پلن‌های اختصاصی و فعال این نماینده
    plans = get_reseller_plans_dict(reseller_id)

    if request.method == "POST":
        plan_key = request.form.get("plan_id")
        account_name = request.form.get("account_name", "").strip()
        phone_number = request.form.get("phone_number", "").strip()
        telegram_id_raw = request.form.get("telegram_id", "").strip()
        user_limit = int(request.form.get("user_limit", 1))

        payment_status = request.form.get("payment_status", "paid").strip()
        debt_amount_raw = request.form.get("debt_amount", "").strip()
        debt_notes = request.form.get("debt_notes", "").strip()
        payment_source = request.form.get("payment_source", "auto").strip()

        if plan_key not in plans:
            flash("پلن انتخابی نامعتبر است.", "danger")
            return redirect(url_for("reseller_create_user"))

        plan = plans[plan_key]
        original_price = plan.get("display_price") or plan.get("price") or plan.get("master_price") or 0
        final_price = plan.get("wholesale_price") if plan.get("wholesale_price") is not None else int(original_price * (100 - discount) / 100)

        # بررسی موجودی نقدی + اعتبار مجاز برای خرید با توجه به منبع انتخابی
        credit_enabled = bool(reseller.get("credit_enabled")) or bool(stats.get("credit_enabled"))
        credit_limit = int(reseller.get("credit_limit") or stats.get("credit_limit") or 0)
        credit_debt = int(reseller.get("credit_debt") or stats.get("credit_debt") or 0)
        available_credit = max(0, credit_limit - credit_debt) if credit_enabled else 0
        current_balance = int(reseller.get("balance", stats.get("balance", 0)) or 0)
        total_purchasing_power = current_balance + available_credit

        if payment_source == "wallet" and current_balance < final_price:
            flash(f"موجودی کیف پول شما کافی نیست! موجودی کیف پول: {current_balance:,} ت | هزینه پلن: {final_price:,} ت (در صورت داشتن اعتبار، روش پرداخت را روی «اعتبار خرید» یا «خودکار» بگذارید)", "danger")
            return redirect(url_for("reseller_create_user"))
        elif payment_source == "credit":
            if not credit_enabled:
                flash("اعتبار خرید برای شما فعال نشده است.", "danger")
                return redirect(url_for("reseller_create_user"))
            if available_credit < final_price:
                flash(f"اعتبار باقیمانده شما کافی نیست! اعتبار مجاز: {available_credit:,} ت | هزینه پلن: {final_price:,} ت", "danger")
                return redirect(url_for("reseller_create_user"))
        elif total_purchasing_power < final_price:
            flash(f"موجودی کیف پول و سقف اعتبار شما کافی نیست! موجودی: {current_balance:,} ت | اعتبار باقیمانده: {available_credit:,} ت | مبلغ مورد نیاز: {final_price:,} ت", "danger")
            return redirect(url_for("reseller_create_user"))

        if not account_name:
            account_name = f"res_{reseller_id}_{int(time.time()) % 10000}"

        telegram_id = int(telegram_id_raw) if telegram_id_raw.isdigit() else 0
        if payment_status in ("unpaid", "debtor"):
            debt_amount = int(debt_amount_raw) if debt_amount_raw.isdigit() else original_price
        else:
            debt_amount = 0

        user_comment = f"Reseller #{reseller_id} ({session.get('name')})"
        if phone_number:
            user_comment += f" | Phone: {phone_number}"
        if telegram_id:
            user_comment += f" | TG: {telegram_id}"

        # ۱. ابتدا ساخت کاربر در سرور هیدیفای انجام می‌شود
        data_limit_gb = plan.get("display_data_limit") if plan.get("display_data_limit") is not None else plan.get("data_limit", 30)
        duration_days = plan.get("display_duration") if plan.get("display_duration") is not None else plan.get("duration", 30)

        can_gift = bool(reseller.get("can_gift_traffic"))
        gift_traffic = 0.0
        if can_gift:
            try:
                gift_traffic = max(0.0, float(request.form.get("gift_traffic_gb", 0) or 0))
            except (ValueError, TypeError):
                gift_traffic = 0.0

        effective_limit_gb = data_limit_gb + gift_traffic
        if gift_traffic > 0:
            user_comment += f" | +{gift_traffic}GB Gift"

        h_res = hidify_sync_create_user(
            name=account_name,
            usage_limit_gb=effective_limit_gb,
            package_days=duration_days,
            comment=user_comment,
            reseller_id=reseller_id
        )

        user_uuid = h_res.get("uuid", "")
        if not user_uuid:
            err_msg = h_res.get("error", "پاسخ نامعتبر از سرور")
            flash(f"خطا در ساخت اکانت روی سرور هیدیفای: {err_msg}", "danger")
            return redirect(url_for("reseller_create_user"))

        # ۲. پس از تایید ۱۰۰٪ ساخت در هیدیفای، موجودی/اعتبار کسر و تراکنش خرید ثبت می‌گردد
        base_plan_title = plan.get("display_name") or plan.get("name") or plan.get("master_name", "")
        plan_title = base_plan_title + (f" (+{gift_traffic}GB هدیه)" if gift_traffic > 0 else "")
        profit_margin = 0 if payment_status in ("unpaid", "debtor") else max(0, original_price - final_price)
        reseller_selling_price = 0 if payment_status in ("unpaid", "debtor") else original_price
        reseller_creator = session.get("username") or reseller.get("username") or f"reseller_{reseller_id}"
        deduct_res = db.deduct_reseller_balance(
            reseller_id, final_price, plan_title, account_name,
            payment_source=payment_source,
            selling_price=reseller_selling_price,
            profit_margin=profit_margin,
            created_by=reseller_creator
        )
        if not deduct_res.get("success"):
            logger.error(f"Failed to deduct balance after user creation: {deduct_res.get('error')}")

        # دریافت موجودی به‌روز پس از کسر وجه و به‌روزرسانی نشست
        r_after = db.get_reseller(reseller_id)
        current_reseller_balance = r_after.get("balance", 0) if r_after else 0
        session["balance"] = current_reseller_balance
        if r_after:
            c_debt = r_after.get("credit_debt", 0)
            c_lim = r_after.get("credit_limit", 0)
            session["credit_debt"] = c_debt
            session["credit_limit"] = c_lim
            session["available_credit"] = max(0, c_lim - c_debt)

        now = get_now_iso()
        debt_created = now if debt_amount > 0 else None
        is_credit_sub = 1 if deduct_res.get("is_credit") else 0
        credit_used_amount = deduct_res.get("credit_used", 0)
        actual_payment_source = deduct_res.get("payment_source", "wallet")

        # ۳. ثبت اشتراک با وضعیت بدهی، شناسه نماینده، شماره تلفن، هزینه و منبع پرداخت دقیق
        reseller_creator = session.get("username") or f"reseller_{reseller_id}"
        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO subscriptions 
            (telegram_id, hidify_uuid, plan_id, plan_name, account_name, phone_number,
             data_limit, duration, status, reseller_id, user_limit, cost_paid,
             payment_status, debt_amount, debt_notes, debt_created_at, is_credit, credit_debt_amount, payment_source, created_by, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            telegram_id, user_uuid, plan_key, plan_title, account_name, phone_number or None,
            effective_limit_gb, duration_days, reseller_id, user_limit, final_price,
            payment_status, debt_amount, debt_notes or None, debt_created, is_credit_sub, credit_used_amount,
            actual_payment_source, reseller_creator, now, now
        ))
        sub_id = cursor.lastrowid

        if deduct_res.get("transaction_id"):
            cursor.execute("UPDATE reseller_transactions SET subscription_id=? WHERE id=?", (sub_id, deduct_res["transaction_id"]))

        if telegram_id and telegram_id > 0:
            cursor.execute("SELECT * FROM users WHERE telegram_id=?", (telegram_id,))
            if not cursor.fetchone():
                cursor.execute("""
                    INSERT INTO users (telegram_id, username, phone_number, is_verified, reseller_id, created_at, updated_at)
                    VALUES (?, ?, ?, 1, ?, ?, ?)
                """, (telegram_id, account_name, phone_number or None, reseller_id, now, now))

        conn.commit()
        conn.close()

        # ثبت رسید بدهی در صورت بدهکار بودن مشتری
        if payment_status in ("unpaid", "debtor") and debt_amount > 0:
            try:
                db.add_customer_debt_record(
                    subscription_id=sub_id,
                    account_name=account_name,
                    telegram_id=telegram_id or 0,
                    reseller_id=reseller_id,
                    action_type="create",
                    plan_name=plan_title,
                    amount=debt_amount,
                    notes=debt_notes or "ثبت بدهی هنگام ساخت اشتراک توسط نماینده",
                    created_by=reseller_creator,
                    previous_debt=0
                )
            except Exception as e_rec:
                logger.error(f"Error logging customer debt record in reseller_create_user: {e_rec}")

        # ثبت فیش پرداخت و درآمد مشتری برای نماینده در صورت تسویه و عدم بدهکاری
        if payment_status not in ("unpaid", "debtor") and original_price > 0:
            try:
                tx_order_id = f"RES_{get_now_naive().strftime('%Y%m%d%H%M%S')}_{random.randint(100, 999)}"
                db.save_transaction(
                    order_id=tx_order_id,
                    user_id=telegram_id or 0,
                    username=account_name,
                    plan_name=plan_title,
                    amount=original_price,
                    gateway="cash_reseller",
                    tracking_code=f"CASH_{reseller_creator}",
                    status="approved",
                    account_name=account_name,
                    source="reseller",
                    reseller_id=reseller_id,
                    subscription_id=sub_id
                )
            except Exception as e_tx:
                logger.error(f"Error saving customer payment in reseller_create_user: {e_tx}")

        # ثبت سابقه دوره اولیه در تاریخچه
        db.save_subscription_history(
            subscription_id=sub_id,
            telegram_id=telegram_id,
            hidify_uuid=user_uuid,
            account_name=account_name,
            plan_name=plan_title,
            previous_usage_gb=0,
            previous_limit_gb=data_limit_gb,
            period_days=duration_days,
            renewal_type="new_subscription",
            reseller_id=reseller_id,
            plan_price=original_price,
            cost_paid=final_price,
            start_date=now
        )

        # محاسبه و واریز خودکار پورسانت به نماینده معرف (بالادستی)
        try:
            db.process_sub_reseller_affiliate_commission(
                sub_reseller_id=reseller_id,
                plan_price=original_price,
                plan_name=plan_title,
                account_name=account_name,
                sub_id=sub_id
            )
        except Exception as e:
            logger.error(f"Error processing affiliate commission: {e}")

        subscription_url = f"{get_hiddify_url()}/{get_user_proxy()}/{user_uuid}/"
        single_link_template = get_single_link_template(db)
        single_url = format_single_link(single_link_template, uuid=user_uuid, name=account_name)
        
        debt_msg = f" (مشتری بدهکار ثبت شد: {debt_amount:,} تومان)" if debt_amount > 0 else ""
        if actual_payment_source == "credit":
            source_msg = f"مبلغ {final_price:,} تومان از اعتبار خرید (نسیه) شما کسر و به بدهی اعتباری افزوده شد."
        elif actual_payment_source == "wallet":
            source_msg = f"مبلغ {final_price:,} تومان از کیف پول نقدی شما کسر گردید."
        else:
            source_msg = f"مبلغ {final_price:,} تومان کسر گردید."

        # ثبت رویداد در سامانه لاگ و حسابرسی
        try:
            db.add_system_log(
                category="reseller",
                action="create",
                title=f"ایجاد اشتراک «{account_name}» توسط نماینده",
                description=f"اشتراک «{account_name}» با بسته {plan_title} ({data_limit_gb}GB / {duration_days} روز) توسط نماینده ({reseller_creator}) صادر گردید. هزینه کسر شده: {final_price:,} تومان.{debt_msg}",
                actor_type="reseller",
                actor_id=reseller_id,
                actor_name=reseller_creator,
                target_type="subscription",
                target_id=sub_id,
                target_name=account_name,
                details={
                    "reseller_id": reseller_id,
                    "plan_title": plan_title,
                    "data_limit_gb": data_limit_gb,
                    "duration_days": duration_days,
                    "final_price": final_price,
                    "payment_source": actual_payment_source,
                    "hidify_uuid": user_uuid
                },
                level="success",
                ip_address=request.remote_addr
            )
        except Exception:
            pass

        flash(f"اشتراک «{account_name}» با موفقیت ساخته شد و {source_msg}{debt_msg}", "success")

        return render_template(
            "reseller_created_success.html",
            account_name=account_name,
            plan=plan,
            sub_id=sub_id,
            sub_url=subscription_url,
            single_url=single_url,
            final_price=final_price,
            current_reseller_balance=current_reseller_balance,
            payment_source=actual_payment_source,
            credit_used_amount=credit_used_amount,
            is_credit=is_credit_sub
        )

    credit_enabled = bool(reseller.get("credit_enabled")) or bool(stats.get("credit_enabled"))
    credit_limit = int(reseller.get("credit_limit") or stats.get("credit_limit") or 0)
    credit_debt = int(reseller.get("credit_debt") or stats.get("credit_debt") or 0)
    available_credit = max(0, credit_limit - credit_debt) if credit_enabled else 0
    balance = int(reseller.get("balance", stats.get("balance", 0)) or 0)
    total_purchasing_power = balance + available_credit

    return render_template(
        "reseller_create_user.html",
        plans=plans,
        discount=discount,
        balance=balance,
        reseller=reseller,
        stats=stats,
        credit_enabled=credit_enabled,
        credit_limit=credit_limit,
        credit_debt=credit_debt,
        available_credit=available_credit,
        total_purchasing_power=total_purchasing_power
    )


@app.route("/reseller/users")
@reseller_required
def reseller_users():
    """لیست مشتریان نماینده به همراه آمار، صفحه‌بندی، وضعیت آنلاین، تب بدهکاران و سطل زباله"""
    sync_hiddify_online_users()
    reseller_id = session.get("reseller_id")
    stats = db.get_reseller_stats(reseller_id)
    discount = stats["discount_percent"]
    plans = get_reseller_plans_dict(reseller_id)
    status_filter = request.args.get("status", "all")
    search_query = request.args.get("search", "").strip().lower()
    debtor_count = db.get_debtor_count(reseller_id)

    # پارامترهای صفحه‌بندی (Pagination: 25, 50, 100, all)
    try:
        page = max(1, int(request.args.get("page", 1)))
    except (ValueError, TypeError):
        page = 1

    per_page_param = request.args.get("per_page", "25").strip()
    if per_page_param.lower() in ("all", "همه", "0", "-1"):
        per_page = 999999
        per_page_str = "all"
    else:
        try:
            per_page = max(1, int(per_page_param))
            per_page_str = str(per_page)
        except (ValueError, TypeError):
            per_page = 25
            per_page_str = "25"
    
    sort_by = request.args.get("sort", "newest").strip()

    if status_filter == "deleted":
        subs = db.get_deleted_subscriptions(reseller_id, sort_by=sort_by)
    else:
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
            elif status_filter == "debtors" and not (item.get("payment_status") in ("unpaid", "debtor") or (item.get("debt_amount") or 0) > 0):
                continue
            elif status_filter == "queue" and not item.get("has_queue"):
                continue

            if search_query:
                acc_name = (item.get("account_name") or "").lower()
                p_num = (item.get("phone_number") or "").lower()
                p_name = (item.get("plan_name") or "").lower()
                c_text = (item.get("comment") or "").lower()
                if search_query not in acc_name and search_query not in p_num and search_query not in p_name and search_query not in c_text:
                    continue

            refund_calc = db.calculate_reseller_refund(reseller_id, item["id"])
            item["refund_info"] = refund_calc
            subs.append(item)

    total_count = len(subs)
    total_pages = max(1, (total_count + per_page - 1) // per_page)
    if page > total_pages:
        page = total_pages
    start_idx = (page - 1) * per_page
    end_idx = min(start_idx + per_page, total_count)
    paginated_subs = subs[start_idx:end_idx]

    queue_count = db.get_pending_queue_count(reseller_id=reseller_id)
    all_pending_queue = db.get_all_pending_queue_items(reseller_id=reseller_id)
    single_link_template = get_single_link_template(db)
    return render_template(
        "reseller_users.html",
        subscriptions=paginated_subs,
        status_filter=status_filter,
        plans=plans,
        discount=discount,
        stats=stats,
        debtor_count=debtor_count,
        queue_count=queue_count,
        all_pending_queue=all_pending_queue,
        balance=stats["balance"],
        available_credit=stats.get("available_credit", 0),
        credit_enabled=stats.get("credit_enabled", False),
        credit_limit=stats.get("credit_limit", 0),
        credit_debt=stats.get("credit_debt", 0),
        total_purchasing_power=stats.get("total_purchasing_power", stats["balance"]),
        unpaid_debts_total=stats.get("unpaid_debts_total", 0),
        page=page,
        per_page=per_page_str,
        total_pages=total_pages,
        total_count=total_count,
        display_start=start_idx + 1 if total_count > 0 else 0,
        display_end=end_idx,
        search=search_query,
        sort_by=sort_by,
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
    """ویرایش مشخصات، نام، تلفن، آیدی تلگرام، وضعیت بدهی و آواتار مشتری نماینده (بدون تغییر مستقیم حجم/روز)"""
    reseller_id = session.get("reseller_id")
    sub = db.get_reseller_subscription(reseller_id, sub_id)
    if not sub:
        flash("اشتراک مورد نظر یافت نشد.", "danger")
        return redirect(url_for("reseller_users"))

    account_name = request.form.get("account_name", "").strip() or sub.get("account_name") or f"user_{sub_id}"
    phone_number = request.form.get("phone_number", "").strip()
    telegram_id_raw = request.form.get("telegram_id", "").strip()
    telegram_id = int(telegram_id_raw) if telegram_id_raw.isdigit() else None
    comment = request.form.get("comment", "").strip()
    avatar_preset = request.form.get("avatar_preset", "").strip()

    status_val = request.form.get("status", "").strip()
    status = status_val if status_val in ("active", "disabled") else None

    payment_status = request.form.get("payment_status", sub.get("payment_status") or "paid").strip()
    debt_amount_raw = request.form.get("debt_amount", "").strip()
    debt_notes = request.form.get("debt_notes", "").strip()
    debt_amount = int(debt_amount_raw) if debt_amount_raw.isdigit() else 0

    # ۱. بروزرسانی در دیتابیس محلی (حجم و مدت توسط نماینده مستقیماً تغییر داده نمی‌شود)
    db.update_reseller_subscription(
        reseller_id=reseller_id,
        sub_id=sub_id,
        account_name=account_name,
        phone_number=phone_number,
        comment=comment,
        status=status,
        telegram_id=telegram_id,
        payment_status=payment_status,
        debt_amount=debt_amount,
        debt_notes=debt_notes
    )

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

    # ۳. بروزرسانی مستقیم و بلادرنگ در سرور هیدیفای
    h_uuid = sub.get("hidify_uuid")
    if h_uuid:
        reseller_data = db.get_reseller(reseller_id) or {}
        r_name = reseller_data.get("name") or session.get("name") or reseller_data.get("username") or f"Reseller #{reseller_id}"
        full_comment = f"Reseller #{reseller_id} ({r_name})"
        if phone_number:
            full_comment += f" | Phone: {phone_number}"
        if telegram_id:
            full_comment += f" | TG: {telegram_id}"
        if comment:
            full_comment += f" | {comment}"

        h_payload = {
            "name": account_name,
            "comment": full_comment[:200]
        }
        if status == "disabled":
            h_payload["enable"] = False
            h_payload["is_active"] = False
        elif status == "active":
            h_payload["enable"] = True
            h_payload["is_active"] = True

        h_res = hidify_sync_update_user(
            h_uuid,
            reseller_id=reseller_id,
            **h_payload
        )
        if isinstance(h_res, dict) and "error" in h_res:
            logger.warning(f"Warning: Failed to update user {h_uuid} in Hiddify: {h_res.get('error')}")

    # ۴. همگام‌سازی فوری برای تثبیت داده‌ها
    try:
        sync_hiddify_online_users(force=True)
    except Exception as e_sync:
        logger.error(f"Error in sync_hiddify_online_users after edit: {e_sync}")

    flash(f"مشخصات مشتری «{account_name}» با موفقیت ذخیره و در سرور هیدیفای اعمال شد.", "success")
    return redirect(get_redirect_target("reseller_users"))


@app.route("/reseller/subscription/<int:sub_id>/request-change", methods=["POST"])
@reseller_required
def reseller_request_quota_change(sub_id):
    """ثبت و ارسال تیکت درخواست تغییر حجم و مدت اشتراک توسط نماینده به مدیریت"""
    reseller_id = session.get("reseller_id")
    requested_limit_raw = request.form.get("requested_limit", "").strip()
    requested_duration_raw = request.form.get("requested_duration", "").strip()
    reason = request.form.get("reason", "").strip()

    try:
        requested_limit = float(requested_limit_raw)
        requested_duration = int(requested_duration_raw)
    except Exception:
        flash("مقادیر حجم یا مدت زمان درخواستی نامعتبر است.", "danger")
        return redirect(get_redirect_target("reseller_users"))

    res = db.create_quota_change_request(
        sub_id=sub_id,
        reseller_id=reseller_id,
        requested_limit=requested_limit,
        requested_duration=requested_duration,
        reason=reason
    )

    if res.get("success"):
        ticket_id = res.get("ticket_id")
        try:
            admin_tg = db.get_setting("admin_telegram_id") or get_admin_id()
            if admin_tg:
                r_info = db.get_reseller(reseller_id) or {}
                r_name = r_info.get("name") or session.get("name") or f"نماینده #{reseller_id}"
                sub_info = db.get_subscription(sub_id) or {}
                acc_name = sub_info.get("account_name") or f"user_{sub_id}"
                quota_notif = (
                    f"⚖️ <b>درخواست تغییر مشخصات اشتراک از سمت نماینده!</b>\n\n"
                    f"🎫 شماره تیکت: <b>#{ticket_id}</b>\n"
                    f"👤 نماینده: <b>{r_name}</b> (کد #{reseller_id})\n"
                    f"📦 اشتراک: <code>{acc_name}</code> (شناسه #{sub_id})\n"
                    f"📊 حجم درخواستی: <b>{requested_limit} GB</b>\n"
                    f"⏳ مدت درخواستی: <b>{requested_duration} روز</b>\n"
                    + (f"📝 علت درخواست: {reason}\n" if reason else "")
                    + f"⏰ زمان: {get_now_shamsi()}"
                )
                adm_kb = {
                    "inline_keyboard": [
                        [
                            {"text": "✅ تایید و اعمال مستقیم", "callback_data": f"adm_quota_app_{ticket_id}"},
                            {"text": "❌ رد درخواست", "callback_data": f"adm_quota_rej_{ticket_id}"}
                        ]
                    ]
                }
                send_telegram_msg(int(admin_tg), quota_notif, reply_markup=adm_kb)
        except Exception as e_tg:
            logger.warning(f"Failed to notify admin of quota change request: {e_tg}")
        flash(f"✅ درخواست تغییر حجم به {requested_limit} گیگابایت و {requested_duration} روز با موفقیت برای مدیریت ارسال شد و در تیکت #{res.get('ticket_id')} ثبت گردید.", "success")
    else:
        flash(f"خطا در ثبت درخواست: {res.get('error')}", "danger")

    return redirect(get_redirect_target("reseller_users"))


@app.route("/reseller/subscription/<int:sub_id>/toggle", methods=["POST"])
@reseller_required
def reseller_toggle_user(sub_id: int):
    """فعال یا غیرفعال کردن مشتری نماینده با ثبت علت در صورت غیرفعال‌سازی (بدون کسر یا استرداد هزینه)"""
    reseller_id = session.get("reseller_id")
    sub = db.get_reseller_subscription(reseller_id, sub_id)
    if not sub:
        flash("اشتراک مورد نظر یافت نشد.", "danger")
        return redirect(get_redirect_target("reseller_users"))

    current_status = sub.get("status", "active")
    new_status = "disabled" if current_status == "active" else "active"
    is_active = (new_status == "active")

    reason = request.form.get("reason", "").strip()
    custom_reason = request.form.get("custom_reason", "").strip()
    final_reason = custom_reason if reason == "custom" and custom_reason else (reason or "سایر")
    dis_reason = final_reason if not is_active else None

    res = db.toggle_reseller_subscription(reseller_id, sub_id, enable=is_active, reason=dis_reason)
    if res.get("success"):
        if sub.get("hidify_uuid"):
            hidify_sync_update_user(sub["hidify_uuid"], enable=is_active, is_active=is_active, reseller_id=reseller_id)
        
        status_fa = "فعال" if is_active else "غیرفعال"
        reason_fa = f" (علت: {dis_reason})" if dis_reason else ""
        flash(f"وضعیت اشتراک «{sub['account_name']}» به حالت «{status_fa}» تغییر یافت.{reason_fa}", "info")
    else:
        flash(f"خطا در تغییر وضعیت: {res.get('error')}", "danger")

    return redirect(get_redirect_target("reseller_users"))


@app.route("/reseller/subscription/<int:sub_id>/renew", methods=["POST"])
@reseller_required
def reseller_renew_user(sub_id: int):
    """تمدید اشتراک مشتری با کسر اعتبار تخفیف‌دار نماینده"""
    reseller_id = session.get("reseller_id")
    reseller = db.get_reseller(reseller_id) or {}
    sub = db.get_reseller_subscription(reseller_id, sub_id)
    if not sub:
        flash("اشتراک مورد نظر یافت نشد.", "danger")
        return redirect(get_redirect_target("reseller_users"))

    plan_key = request.form.get("plan_id")
    payment_source = request.form.get("payment_source", "auto").strip()
    plans = get_reseller_plans_dict(reseller_id)
    if plan_key not in plans:
        flash("پلن انتخابی نامعتبر است.", "danger")
        return redirect(get_redirect_target("reseller_users"))

    plan = plans[plan_key]
    stats = db.get_reseller_stats(reseller_id) or {}
    discount = stats.get("discount_percent", reseller.get("discount_percent", 20))
    original_price = plan.get("display_price") or plan.get("price") or plan.get("master_price") or 0
    final_price = plan.get("wholesale_price") if plan.get("wholesale_price") is not None else int(original_price * (100 - discount) / 100)

    total_purchasing_power = stats.get("total_purchasing_power", stats.get("balance", reseller.get("balance", 0)))
    if total_purchasing_power < final_price:
        flash(f"توان خرید شما (کیف پول + اعتبار) برای تمدید این پلن کافی نیست! توان خرید: {total_purchasing_power:,} ت | هزینه تمدید: {final_price:,} ت", "danger")
        return redirect(get_redirect_target("reseller_users"))

    instant_activate = bool(request.form.get("instant_activate"))
    base_plan_title = plan.get("display_name") or plan.get("name") or plan.get("master_name", "")
    data_limit_gb = plan.get("display_data_limit") if plan.get("display_data_limit") is not None else plan.get("data_limit", 30)
    duration_days = plan.get("display_duration") if plan.get("display_duration") is not None else plan.get("duration", 30)

    can_gift = bool(reseller.get("can_gift_traffic"))
    gift_traffic = 0.0
    if can_gift:
        try:
            gift_traffic = max(0.0, float(request.form.get("gift_traffic_gb", 0) or 0))
        except (ValueError, TypeError):
            gift_traffic = 0.0

    effective_limit_gb = data_limit_gb + gift_traffic
    plan_title = base_plan_title + (f" (+{gift_traffic}GB هدیه)" if gift_traffic > 0 else "")

    # ۱. در صورت فعال‌سازی آنی، هیدیفای بلافاصله ریست می‌شود
    renewal_res = {"renewal_type": "reset_and_replaced"}
    if instant_activate and sub.get("hidify_uuid"):
        try:
            renewal_res = hidify_sync_renew_user(sub["hidify_uuid"], effective_limit_gb, duration_days, force_instant=True)
        except Exception as e:
            logger.error(f"Error in reseller renew Hiddify {sub.get('hidify_uuid')}: {e}")

    # دریافت وضعیت مالی مشتری (تسویه یا بدهکار) و یادداشت تمدید
    payment_status = request.form.get("payment_status", "paid").strip()
    debt_amount_raw = request.form.get("debt_amount", "").strip()
    renewal_notes = request.form.get("renewal_notes", "").strip()

    if payment_status in ("unpaid", "debtor"):
        debt_amount = int(debt_amount_raw) if debt_amount_raw.isdigit() else original_price
        debt_status = "unpaid"
    else:
        debt_amount = 0
        debt_status = "paid"

    # ۲. ثبت در دیتابیس (آنی با ریست یا رزرو در صف) و کسر هزینه با توجه به منبع پرداخت
    creator_user = session.get("username") or f"reseller_{reseller_id}"
    profit_margin = 0 if debt_status == "unpaid" else max(0, original_price - final_price)
    renew_selling_price = 0 if debt_status == "unpaid" else original_price
    renew_db = db.renew_reseller_subscription(
        reseller_id=reseller_id,
        sub_id=sub_id,
        plan_id=plan_key,
        plan_name=plan_title,
        cost=final_price,
        data_limit=effective_limit_gb,
        duration=duration_days,
        instant_activate=instant_activate,
        renewal_type=renewal_res.get("renewal_type", "reset_and_replaced"),
        payment_source=payment_source,
        selling_price=renew_selling_price,
        profit_margin=profit_margin,
        created_by=creator_user
    )

    if renew_db.get("success"):
        # تنظیم یا تسویه وضعیت مالی و بدهی مشتری
        old_debt = int(sub.get("debt_amount") or 0)
        total_sub_debt = old_debt + debt_amount if debt_status == "unpaid" else 0

        if debt_status == "unpaid":
            try:
                db.add_customer_debt_record(
                    subscription_id=sub_id,
                    account_name=sub.get("account_name"),
                    telegram_id=sub.get("telegram_id") or 0,
                    reseller_id=reseller_id,
                    action_type="renew",
                    plan_name=plan_title,
                    amount=debt_amount,
                    notes=renewal_notes or "ثبت بدهی هنگام تمدید توسط نماینده",
                    created_by=creator_user,
                    previous_debt=old_debt
                )
            except Exception as e_rec:
                logger.error(f"Error logging customer debt record in reseller_renew_user: {e_rec}")
        else:
            db.clear_subscription_debt(sub_id, reseller_id=reseller_id, settled_by=creator_user)
            if renewal_notes:
                conn = db.get_connection()
                conn.execute("UPDATE subscriptions SET debt_notes=? WHERE id=? AND reseller_id=?", (renewal_notes, sub_id, reseller_id))
                conn.commit()
                conn.close()

        debt_tag = f" (مشتری بدهکار ثبت شد: {debt_amount:,} ت | مجموع بدهی: {total_sub_debt:,} ت)" if debt_status == "unpaid" else " (وضعیت مالی مشتری: تسویه شده)"

        # ثبت فیش پرداخت و درآمد مشتری در صورت تسویه و عدم بدهکاری
        if debt_status != "unpaid" and original_price > 0:
            try:
                rx_order_id = f"RNW_RES_{get_now_naive().strftime('%Y%m%d%H%M%S')}_{random.randint(100, 999)}"
                db.save_transaction(
                    order_id=rx_order_id,
                    user_id=sub.get("telegram_id") or 0,
                    username=sub.get("account_name") or "",
                    plan_name=plan_title,
                    amount=original_price,
                    gateway="cash_reseller",
                    tracking_code=f"RENEW_{creator_user}",
                    status="approved",
                    account_name=sub.get("account_name") or "",
                    source="reseller",
                    reseller_id=reseller_id,
                    subscription_id=sub_id,
                    is_renewal=1
                )
            except Exception as e_rx:
                logger.error(f"Error saving customer renew transaction in reseller_renew_user: {e_rx}")

        if instant_activate:
            # ثبت در تاریخچه سوابق مصرف دوره‌های گذشته
            try:
                db.log_subscription_history(
                    subscription_id=sub_id,
                    telegram_id=sub.get("telegram_id") or 0,
                    hidify_uuid=sub.get("hidify_uuid") or "",
                    account_name=sub["account_name"],
                    plan_name=plan_title,
                    previous_usage_gb=sub.get("data_used") or 0,
                    previous_limit_gb=sub.get("data_limit") or 0,
                    period_days=duration_days,
                    renewal_type="reset_and_replaced",
                    reseller_id=reseller_id,
                    cost_paid=final_price,
                    created_by=creator_user
                )
            except Exception as e:
                logger.warning(f"Failed to log subscription history on reseller renew: {e}")

            flash(f"اشتراک «{sub['account_name']}» با پلن «{plan_title}» به صورت آنی تمدید شد، حجم و روز آن ریست گردید و مبلغ {final_price:,} تومان از حساب/اعتبار شما کسر شد.{debt_tag}", "success")
        else:
            flash(f"بسته تمدیدی «{plan_title}» برای اشتراک «{sub['account_name']}» در صف رزرو قرار گرفت و مبلغ {final_price:,} تومان کسر شد.{debt_tag} پس از مصرف ۹۹٪ یا در روز پایانی اشتراک به صورت خودکار فعال خواهد شد.", "info")

        r_after = db.get_reseller(reseller_id)
        if r_after:
            session["balance"] = r_after.get("balance", 0)
            c_lim = r_after.get("credit_limit", 0)
            c_debt = r_after.get("credit_debt", 0)
            c_en = bool(r_after.get("credit_enabled")) or (c_lim > 0)
            session["credit_enabled"] = c_en
            session["credit_limit"] = c_lim
            session["credit_debt"] = c_debt
            session["available_credit"] = max(0, c_lim - c_debt) if c_en else 0
            session["total_purchasing_power"] = session["balance"] + session["available_credit"]
    else:
        flash(f"خطا در تمدید اشتراک: {renew_db.get('error')}", "danger")

    return redirect(get_redirect_target("reseller_users"))


@app.route("/reseller/subscriptions/bulk-renew", methods=["POST"])
@reseller_required
def reseller_subscriptions_bulk_renew():
    """تمدید گروهی اشتراک‌های انتخابی نماینده (آنی یا در صف) با محاسبه مجموع هزینه و کسر از کیف‌پول/اعتبار"""
    reseller_id = session.get("reseller_id")
    selected_ids_str = request.form.get("selected_ids_str", "").strip()
    if not selected_ids_str:
        flash("هیچ اشتراکی برای تمدید گروهی انتخاب نشده است.", "warning")
        return redirect(url_for("reseller_users"))

    try:
        sub_ids = [int(x.strip()) for x in selected_ids_str.split(",") if x.strip().isdigit()]
    except Exception:
        flash("شناسه‌های ارسالی نامعتبر هستند.", "danger")
        return redirect(url_for("reseller_users"))

    if not sub_ids:
        flash("هیچ اشتراک معتبری یافت نشد.", "warning")
        return redirect(url_for("reseller_users"))

    plan_key = request.form.get("plan_id", "current").strip()
    payment_source = request.form.get("payment_source", "auto").strip()
    instant_activate = bool(request.form.get("instant_activate"))
    plans = get_reseller_plans_dict(reseller_id)
    stats = db.get_reseller_stats(reseller_id)
    discount = stats.get("discount_percent", 20)

    # ۱. محاسبه کل هزینه مورد نیاز و اعتبارسنجی توان خرید
    subs_to_renew = []
    total_cost_required = 0

    for s_id in sub_ids:
        sub = db.get_reseller_subscription(reseller_id, s_id)
        if not sub:
            continue

        if plan_key == "current" or plan_key not in plans:
            p_key = str(sub.get("plan_id") or "custom")
            if p_key in plans:
                p_item = plans[p_key]
                p_name = p_item.get("display_name") or p_item.get("name") or p_item.get("master_name", "")
                p_limit = float(p_item.get("display_data_limit") if p_item.get("display_data_limit") is not None else p_item.get("data_limit", 30))
                p_dur = int(p_item.get("display_duration") if p_item.get("display_duration") is not None else p_item.get("duration", 30))
                orig_price = p_item.get("display_price") or p_item.get("price") or p_item.get("master_price") or 0
                final_price = p_item.get("wholesale_price") if p_item.get("wholesale_price") is not None else int(orig_price * (100 - discount) / 100)
            else:
                p_limit = float(sub.get("data_limit") or 30)
                p_dur = int(sub.get("duration") or 30)
                p_name = sub.get("plan_name") or f"{p_limit} گیگ"
                orig_price = int(sub.get("cost_paid") or 0)
                final_price = orig_price
        else:
            p_item = plans[plan_key]
            p_key = plan_key
            p_name = p_item.get("display_name") or p_item.get("name") or p_item.get("master_name", "")
            p_limit = float(p_item.get("display_data_limit") if p_item.get("display_data_limit") is not None else p_item.get("data_limit", 30))
            p_dur = int(p_item.get("display_duration") if p_item.get("display_duration") is not None else p_item.get("duration", 30))
            orig_price = p_item.get("display_price") or p_item.get("price") or p_item.get("master_price") or 0
            final_price = p_item.get("wholesale_price") if p_item.get("wholesale_price") is not None else int(orig_price * (100 - discount) / 100)

        total_cost_required += final_price

        subs_to_renew.append({
            "sub": sub,
            "plan_key": p_key,
            "plan_name": p_name,
            "data_limit": p_limit,
            "duration": p_dur,
            "cost": final_price,
            "selling_price": orig_price,
            "profit_margin": max(0, orig_price - final_price)
        })

    total_purchasing_power = stats.get("total_purchasing_power", stats["balance"])
    if total_purchasing_power < total_cost_required:
        flash(f"توان خرید شما برای تمدید گروهی {len(subs_to_renew)} اشتراک کافی نیست! مبلغ مورد نیاز: {total_cost_required:,} ت | توان خرید شما: {total_purchasing_power:,} ت", "danger")
        return redirect(get_redirect_target("reseller_users"))

    # ۲. اعمال تمدیدها برای تک‌تک اشتراک‌ها
    creator_user = session.get("username") or f"reseller_{reseller_id}"
    success_count = 0
    for item in subs_to_renew:
        sub = item["sub"]
        renew_res = db.renew_reseller_subscription(
            reseller_id=reseller_id,
            sub_id=sub["id"],
            plan_id=item["plan_key"],
            plan_name=item["plan_name"],
            cost=item["cost"],
            data_limit=item["data_limit"],
            duration=item["duration"],
            instant_activate=instant_activate,
            payment_source=payment_source,
            selling_price=item.get("selling_price", 0),
            profit_margin=item.get("profit_margin", 0),
            created_by=creator_user
        )
        if renew_res.get("success"):
            if instant_activate and sub.get("hidify_uuid"):
                try:
                    hidify_sync_renew_user(sub["hidify_uuid"], item["data_limit"], item["duration"], force_instant=True)
                except Exception as e:
                    logger.error(f"Error in reseller bulk renew Hiddify {sub.get('hidify_uuid')}: {e}")

                try:
                    db.log_subscription_history(
                        subscription_id=sub["id"],
                        telegram_id=sub.get("telegram_id") or 0,
                        hidify_uuid=sub.get("hidify_uuid") or "",
                        account_name=sub["account_name"],
                        plan_name=item["plan_name"],
                        previous_usage_gb=sub.get("data_used") or 0,
                        previous_limit_gb=sub.get("data_limit") or 0,
                        period_days=item["duration"],
                        renewal_type="reset_and_replaced",
                        reseller_id=reseller_id,
                        cost_paid=item["cost"],
                        created_by=creator_user
                    )
                except Exception:
                    pass
            success_count += 1

    r_after = db.get_reseller(reseller_id)
    if r_after:
        session["balance"] = r_after.get("balance", 0)
        c_lim = r_after.get("credit_limit", 0)
        c_debt = r_after.get("credit_debt", 0)
        c_en = bool(r_after.get("credit_enabled")) or (c_lim > 0)
        session["credit_enabled"] = c_en
        session["credit_limit"] = c_lim
        session["credit_debt"] = c_debt
        session["available_credit"] = max(0, c_lim - c_debt) if c_en else 0
        session["total_purchasing_power"] = session["balance"] + session["available_credit"]

    mode_text = "به صورت آنی تمدید و ریست شدند" if instant_activate else "در صف تمدید رزرو قرار گرفتند"
    flash(f"{success_count} اشتراک با موفقیت {mode_text} و مجموع مبلغ {total_cost_required:,} تومان کسر گردید.", "success")
    return redirect(get_redirect_target("reseller_users"))


@app.route("/reseller/queue/<int:queue_id>/activate", methods=["POST"])
@reseller_required
def reseller_queue_activate(queue_id: int):
    """فعال‌سازی آنی بسته در صف تمدید توسط نماینده"""
    reseller_id = session.get("reseller_id")
    conn = db.get_connection()
    q_item = conn.execute("SELECT * FROM subscription_queue WHERE id=? AND reseller_id=?", (queue_id, reseller_id)).fetchone()
    conn.close()
    if not q_item:
        flash("بسته مورد نظر یافت نشد یا متعلق به شما نیست.", "danger")
        return redirect(get_redirect_target("reseller_users"))

    username = session.get("username") or f"نماینده #{reseller_id}"
    res = activate_single_queue_item(queue_id, triggered_by=username)
    if res.get("success"):
        flash(f"بسته «{res.get('plan_name')}» برای اشتراک «{res.get('account_name')}» با موفقیت فعال شد و حجم و تاریخ آن ریست گردید.", "success")
    else:
        flash(f"خطا در فعال‌سازی بسته: {res.get('error')}", "danger")
    return redirect(get_redirect_target("reseller_users"))


@app.route("/reseller/queue/<int:queue_id>/cancel", methods=["POST"])
@reseller_required
def reseller_queue_cancel(queue_id: int):
    """لغو بسته در صف تمدید توسط نماینده و استرداد وجه به کیف‌پول"""
    reseller_id = session.get("reseller_id")
    res = db.cancel_queue_item(queue_id, reseller_id=reseller_id)
    if res.get("success"):
        refund_txt = f" و مبلغ {res.get('refunded_amount'):,} تومان به کیف‌پول شما استرداد گردید" if res.get('refunded_amount') else ""
        flash(f"بسته رزرو شده با موفقیت از صف تمدید لغو شد{refund_txt}.", "success")
    else:
        flash(f"خطا در لغو بسته: {res.get('error')}", "danger")
    return redirect(get_redirect_target("reseller_users"))


@app.route("/reseller/queue/<int:queue_id>/move", methods=["POST"])
@reseller_required
def reseller_queue_move(queue_id: int):
    """تغییر نوبت بسته در صف تمدید توسط نماینده"""
    reseller_id = session.get("reseller_id")
    direction = request.form.get("direction") or request.args.get("direction", "up")
    if request.is_json:
        direction = (request.get_json(silent=True) or {}).get("direction") or direction
    conn = db.get_connection()
    q_row = conn.execute("SELECT subscription_id FROM subscription_queue WHERE id=? AND reseller_id=?", (queue_id, reseller_id)).fetchone()
    conn.close()
    if not q_row:
        if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.is_json:
            return jsonify({"success": False, "error": "بسته مورد نظر یافت نشد یا متعلق به شما نیست."}), 404
        flash("بسته مورد نظر یافت نشد یا متعلق به شما نیست.", "danger")
        return redirect(get_redirect_target("reseller_users"))
    sub_id = q_row[0]
    res = db.reorder_subscription_queue(sub_id, queue_id, direction)
    if res.get("success"):
        if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.is_json:
            return jsonify({"success": True, "message": "ترتیب بسته‌های در صف تمدید با موفقیت به‌روزرسانی شد."})
        flash("ترتیب بسته‌های در صف تمدید با موفقیت به‌روزرسانی شد.", "success")
    else:
        err = res.get("error", "خطا در جابجایی بسته")
        if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.is_json:
            return jsonify({"success": False, "error": err}), 400
        flash(f"خطا در جابجایی بسته: {err}", "danger")
    return redirect(get_redirect_target("reseller_users"))


@app.route("/reseller/subscription/<int:sub_id>/delete", methods=["POST"])
@reseller_required
def reseller_delete_user(sub_id: int):
    """انتقال مشتری به سطل زباله با ثبت علت حذف و استرداد وجه طبق قوانین بازه ۱۲ و ۲۴ ساعته"""
    reseller_id = session.get("reseller_id")
    conn = db.get_connection()
    sub = conn.execute("SELECT * FROM subscriptions WHERE id=? AND reseller_id=?", (sub_id, reseller_id)).fetchone()
    conn.close()
    if not sub:
        flash("اشتراک مورد نظر یافت نشد.", "danger")
        return redirect(get_redirect_target("reseller_users"))

    sub = dict(sub)
    preset_reason = request.form.get("reason", "").strip()
    custom_reason = request.form.get("custom_reason", "").strip()
    final_reason = custom_reason if preset_reason == "custom" and custom_reason else (preset_reason or "سایر")

    # ۱. بروزرسانی آخرین وضعیت مصرف و تاریخ‌ها از سرور هیدیفای قبل از انتقال به سطل زباله
    if sub.get("hidify_uuid"):
        try:
            active_k = db.get_reseller_hiddify_key(reseller_id)
            h_info = hidify_sync_request("GET", f"/admin/user/{sub['hidify_uuid']}/", api_key=active_k)
            if isinstance(h_info, dict) and "error" not in h_info:
                latest_used = float(h_info.get("current_usage_GB") or 0)
                latest_start = h_info.get("start_date")
                latest_exp = h_info.get("expiry_time") or h_info.get("expire_date")
                conn = db.get_connection()
                conn.execute("""
                    UPDATE subscriptions 
                    SET data_used = ?, 
                        start_date = COALESCE(?, start_date), 
                        expire_date = COALESCE(?, expire_date) 
                    WHERE id = ? AND reseller_id = ?
                """, (latest_used, latest_start, latest_exp, sub_id, reseller_id))
                conn.commit()
                conn.close()
                sub["data_used"] = latest_used
                if latest_start:
                    sub["start_date"] = latest_start
                if latest_exp:
                    sub["expire_date"] = latest_exp
        except Exception as ex:
            logger.warning(f"Error syncing usage before reseller soft-delete: {ex}")

        # غیرفعال‌سازی کاربر در سرور هیدیفای به جای حذف قطعی
        try:
            hidify_sync_update_user(sub["hidify_uuid"], enable=False, is_active=False, reseller_id=reseller_id)
        except Exception as e:
            logger.warning(f"Error disabling user {sub['hidify_uuid']} in Hiddify on soft-delete: {e}")

    # ۲. اجرای حذف نرم در دیتابیس با محاسبه استرداد وجه
    del_res = db.delete_reseller_subscription(reseller_id, sub_id, reason=final_reason)
    if del_res.get("success"):
        refund_amount = del_res.get("refund_amount", 0)
        refund_percent = del_res.get("refund_percent", 0)
        time_passed = del_res.get("time_passed_text", "")

        if refund_amount > 0:
            flash(f"اشتراک «{sub['account_name']}» به سطل زباله منتقل شد و مبلغ {refund_amount:,} تومان ({refund_percent}٪ استرداد - مدت زمان گذشته: {time_passed}) به کیف پول شما بازگردانده شد. (علت: {final_reason})", "success")
        else:
            flash(f"اشتراک «{sub['account_name']}» به سطل زباله منتقل شد. (علت: {final_reason} - بدون استرداد وجه به دلیل گذشت بیش از ۲۴ ساعت)", "warning")

        r_after = db.get_reseller(reseller_id)
        if r_after:
            session["balance"] = r_after.get("balance", 0)
    else:
        flash(f"خطا در حذف اشتراک: {del_res.get('error')}", "danger")

    return redirect(get_redirect_target("reseller_users"))


@app.route("/reseller/subscription/<int:sub_id>/restore", methods=["POST"])
@reseller_required
def reseller_restore_user(sub_id: int):
    """بازگردانی مشتری از سطل زباله توسط نماینده با ساخت مجدد در هیدیفای، حفظ حجم مصرفی و زمان باقی‌مانده و کسر هزینه پلن"""
    reseller_id = session.get("reseller_id")
    conn = db.get_connection()
    sub = conn.execute("SELECT * FROM subscriptions WHERE id=? AND reseller_id=? AND is_deleted=1", (sub_id, reseller_id)).fetchone()
    conn.close()
    if not sub:
        flash("اشتراک حذف‌شده‌ای یافت نشد.", "danger")
        return redirect(get_redirect_target("reseller_users", status="deleted"))

    sub = dict(sub)

    # بررسی سقف مجاز بازگردانی روزانه نماینده
    can_restore, restore_err, restore_limit, current_count = db.can_reseller_restore(reseller_id, 1)
    if not can_restore:
        flash(restore_err, "danger")
        return redirect(get_redirect_target("reseller_users", status="deleted"))

    plans = get_reseller_plans_dict(reseller_id)
    plan_key = str(sub.get("plan_id"))
    plan = plans.get(plan_key) if plan_key in plans else None
    payment_source = request.form.get("payment_source", "auto").strip()
    stats = db.get_reseller_stats(reseller_id)
    discount = stats.get("discount_percent", 20)
    
    if plan:
        original_price = plan.get("display_price") or plan.get("price") or plan.get("master_price") or 0
        final_price = plan.get("wholesale_price") if plan.get("wholesale_price") is not None else int(original_price * (100 - discount) / 100)
    else:
        final_price = sub.get("cost_paid") or 0

    total_power = stats.get("total_purchasing_power", stats["balance"])
    if total_power < final_price:
        flash(f"توان خرید شما (کیف پول + اعتبار: {total_power:,} ت) برای هزینه بازگردانی این اشتراک ({final_price:,} ت) کافی نیست.", "danger")
        return redirect(get_redirect_target("reseller_users", status="deleted"))

    # ۱. بازگردانی یا ساخت مجدد کاربر در سرور هیدیفای با حفظ حجم و زمان مصرف‌شده
    h_res = hiddify_restore_or_recreate_subscription(sub, reseller_id=reseller_id)
    if not h_res.get("success"):
        flash(f"خطا در ایجاد/فعال‌سازی کاربر در سرور هیدیفای: {h_res.get('error')}", "danger")
        return redirect(get_redirect_target("reseller_users", status="deleted"))

    # ۲. اعمال تغییرات در دیتابیس و کسر هزینه از حساب نماینده
    res = db.restore_subscription(
        sub_id,
        is_reseller=True,
        reseller_id=reseller_id,
        cost=final_price,
        new_uuid=h_res.get("uuid"),
        new_start_date=h_res.get("new_start_date"),
        new_expire_date=h_res.get("new_expire_date"),
        new_data_used=h_res.get("data_used"),
        payment_source=payment_source
    )
    if res.get("success"):
        r_after = db.get_reseller(reseller_id)
        if r_after:
            session["balance"] = r_after.get("balance", 0)

        recreated_text = "مجدداً در پنل هیدیفای ساخته شد" if h_res.get("recreated") else "در پنل هیدیفای فعال شد"
        used_gb = h_res.get("data_used", 0)
        rem_days = h_res.get("remaining_days", 0)
        flash(f"اشتراک «{res.get('account_name')}» با موفقیت {recreated_text} و از سطل زباله بازگردانی شد (حجم مصرفی: {used_gb} گیگ | زمان باقی‌مانده: {rem_days} روز لحاظ گردید) و مبلغ {final_price:,} تومان از حساب شما کسر شد.", "success")
    else:
        flash(f"خطا در ثبت بازگردانی در پایگاه داده: {res.get('error')}", "danger")

    return redirect(get_redirect_target("reseller_users"))


@app.route("/reseller/subscription/<int:sub_id>/purge", methods=["POST"])
@reseller_required
def reseller_purge_user(sub_id: int):
    """حذف دائمی مشتری از سطل زباله و سرور هیدیفای توسط نماینده"""
    reseller_id = session.get("reseller_id")
    conn = db.get_connection()
    sub_row = conn.execute("SELECT * FROM subscriptions WHERE id=? AND reseller_id=? AND is_deleted=1", (sub_id, reseller_id)).fetchone()
    conn.close()
    if not sub_row:
        flash("اشتراک حذف‌شده‌ای یافت نشد.", "danger")
        return redirect(get_redirect_target("reseller_users", status="deleted"))

    sub = dict(sub_row)
    uuid_val = sub.get("hidify_uuid")
    if uuid_val:
        try:
            hidify_sync_delete_user(uuid_val)
        except Exception as e:
            logger.warning(f"Error purging user {uuid_val} from Hiddify by reseller: {e}")

    res = db.purge_subscription_permanently(sub_id, reseller_id=reseller_id)
    if res.get("success"):
        flash(f"اشتراک «{sub.get('account_name')}» برای همیشه از سطل زباله و پنل هیدیفای حذف گردید.", "warning")
    else:
        flash(f"خطا در حذف دائمی اشتراک: {res.get('error')}", "danger")

    return redirect(get_redirect_target("reseller_users", status="deleted"))


@app.route("/reseller/trash/bulk", methods=["POST"])
@reseller_required
def reseller_trash_bulk():
    """عملیات گروهی در سطل زباله نماینده (بازگردانی گروهی یا حذف دائمی گروهی)"""
    reseller_id = session.get("reseller_id")
    action = request.form.get("bulk_action")
    raw_ids = request.form.getlist("selected_ids") or [x.strip() for x in request.form.get("selected_ids_str", "").split(",") if x.strip()]
    sub_ids = []
    for s_id in raw_ids:
        try:
            val = int(str(s_id).strip())
            if val > 0:
                sub_ids.append(val)
        except (ValueError, TypeError):
            continue

    if not sub_ids:
        flash("هیچ اشتراکی برای انجام عملیات گروهی سطل زباله انتخاب نشده است.", "warning")
        return redirect(get_redirect_target("reseller_users", status="deleted"))

    success_count = 0
    if action == "restore":
        can_restore, restore_err, restore_limit, current_count = db.can_reseller_restore(reseller_id, len(sub_ids))
        if not can_restore:
            flash(restore_err, "danger")
            return redirect(get_redirect_target("reseller_users", status="deleted"))

        plans = get_reseller_plans_dict(reseller_id)
        stats = db.get_reseller_stats(reseller_id)
        discount = stats.get("discount_percent", 20)

        for sub_id in sub_ids:
            conn = db.get_connection()
            sub_row = conn.execute("SELECT * FROM subscriptions WHERE id=? AND reseller_id=? AND is_deleted=1", (sub_id, reseller_id)).fetchone()
            conn.close()
            if not sub_row:
                continue
            sub = dict(sub_row)
            plan_key = str(sub.get("plan_id"))
            plan = plans.get(plan_key) if plan_key in plans else None
            if plan:
                original_price = plan.get("display_price") or plan.get("price") or plan.get("master_price") or 0
                final_price = plan.get("wholesale_price") if plan.get("wholesale_price") is not None else int(original_price * (100 - discount) / 100)
            else:
                final_price = sub.get("cost_paid") or 0

            # بررسی توان خرید
            r_cur = db.get_reseller_stats(reseller_id)
            cur_power = r_cur.get("total_purchasing_power", r_cur["balance"])
            if cur_power < final_price:
                continue

            h_res = hiddify_restore_or_recreate_subscription(sub, reseller_id=reseller_id)
            if h_res.get("success"):
                db.restore_subscription(
                    sub_id,
                    is_reseller=True,
                    reseller_id=reseller_id,
                    cost=final_price,
                    new_uuid=h_res.get("uuid"),
                    new_start_date=h_res.get("new_start_date"),
                    new_expire_date=h_res.get("new_expire_date"),
                    new_data_used=h_res.get("data_used")
                )
                success_count += 1

        r_after = db.get_reseller(reseller_id)
        if r_after:
            session["balance"] = r_after.get("balance", 0)

        db.add_system_log(
            category="reseller",
            action="bulk_restore",
            title=f"بازگردانی گروهی {success_count} اشتراک توسط نماینده",
            description=f"تعداد {success_count} اشتراک به صورت گروهی توسط نماینده (#{reseller_id}) از سطل زباله بازیابی شدند.",
            actor_type="reseller",
            actor_id=reseller_id,
            actor_name=f"نماینده #{reseller_id}",
            target_type="subscription",
            target_name=f"{success_count} اشتراک",
            details={"sub_ids": sub_ids, "success_count": success_count, "reseller_id": reseller_id},
            level="success",
            ip_address=request.remote_addr
        )
        flash(f"{success_count} اشتراک با موفقیت از سطل زباله بازگردانی و در هیدیفای فعال شدند.", "success")
    elif action == "purge":
        for sub_id in sub_ids:
            conn = db.get_connection()
            sub_row = conn.execute("SELECT * FROM subscriptions WHERE id=? AND reseller_id=? AND is_deleted=1", (sub_id, reseller_id)).fetchone()
            conn.close()
            if not sub_row:
                continue
            sub = dict(sub_row)
            if sub.get("hidify_uuid"):
                try:
                    hidify_sync_delete_user(sub["hidify_uuid"])
                except Exception as e:
                    logger.warning(f"Error purging user {sub['hidify_uuid']} from Hiddify: {e}")
            del_res = db.purge_subscription_permanently(sub_id, reseller_id=reseller_id)
            if del_res.get("success"):
                success_count += 1

        db.add_system_log(
            category="reseller",
            action="bulk_purge",
            title=f"حذف دائمی گروهی {success_count} اشتراک توسط نماینده",
            description=f"تعداد {success_count} اشتراک به صورت گروهی توسط نماینده (#{reseller_id}) برای همیشه از هیدیفای و سطل زباله پاکسازی شدند.",
            actor_type="reseller",
            actor_id=reseller_id,
            actor_name=f"نماینده #{reseller_id}",
            target_type="subscription",
            target_name=f"{success_count} اشتراک",
            details={"sub_ids": sub_ids, "success_count": success_count, "reseller_id": reseller_id},
            level="danger",
            ip_address=request.remote_addr
        )
        flash(f"{success_count} اشتراک برای همیشه از سطل زباله و پنل هیدیفای حذف گردیدند.", "warning")

    return redirect(get_redirect_target("reseller_users", status="deleted"))


@app.route("/reseller/subscriptions/bulk", methods=["POST"])
@reseller_required
def reseller_subscriptions_bulk():
    """عملیات گروهی روی اشتراک‌های انتخابی نماینده (غیرفعال، فعال، حذف، تسویه بدهی، ارسال یادآوری) با ثبت علت"""
    reseller_id = session.get("reseller_id")
    action = request.form.get("bulk_action")
    raw_ids = request.form.getlist("selected_ids") or [x.strip() for x in request.form.get("selected_ids_str", "").split(",") if x.strip()]
    sub_ids = []
    for s_id in raw_ids:
        try:
            val = int(str(s_id).strip())
            if val > 0:
                sub_ids.append(val)
        except (ValueError, TypeError):
            continue

    if not sub_ids:
        flash("هیچ اشتراکی برای انجام عملیات گروهی انتخاب نشده است.", "warning")
        return redirect(get_redirect_target("reseller_users"))

    bulk_reason = request.form.get("reason", "").strip()
    bulk_custom_reason = request.form.get("custom_reason", "").strip()
    final_bulk_reason = bulk_custom_reason if bulk_reason == "custom" and bulk_custom_reason else (bulk_reason or "عملیات گروهی")

    success_count = 0
    total_refund = 0

    for sub_id in sub_ids:
        sub = db.get_reseller_subscription(reseller_id, sub_id)
        if not sub:
            continue

        if action == "disable":
            res = db.toggle_reseller_subscription(reseller_id, sub_id, enable=False, reason=final_bulk_reason)
            if res.get("success"):
                if sub.get("hidify_uuid"):
                    hidify_sync_update_user(sub["hidify_uuid"], enable=False, is_active=False, reseller_id=reseller_id)
                success_count += 1
        elif action == "enable":
            res = db.toggle_reseller_subscription(reseller_id, sub_id, enable=True)
            if res.get("success"):
                if sub.get("hidify_uuid"):
                    hidify_sync_update_user(sub["hidify_uuid"], enable=True, is_active=True, reseller_id=reseller_id)
                success_count += 1
        elif action == "delete":
            if sub.get("hidify_uuid"):
                try:
                    active_k = db.get_reseller_hiddify_key(reseller_id)
                    h_info = hidify_sync_request("GET", f"/admin/user/{sub['hidify_uuid']}/", api_key=active_k)
                    if isinstance(h_info, dict) and "error" not in h_info:
                        latest_used = float(h_info.get("current_usage_GB") or 0)
                        latest_start = h_info.get("start_date")
                        latest_exp = h_info.get("expiry_time") or h_info.get("expire_date")
                        conn = db.get_connection()
                        conn.execute("""
                            UPDATE subscriptions 
                            SET data_used = ?, 
                                start_date = COALESCE(?, start_date), 
                                expire_date = COALESCE(?, expire_date) 
                            WHERE id = ? AND reseller_id = ?
                        """, (latest_used, latest_start, latest_exp, sub_id, reseller_id))
                        conn.commit()
                        conn.close()
                except Exception as ex:
                    logger.warning(f"Error syncing usage before bulk soft-delete: {ex}")

                try:
                    hidify_sync_update_user(sub["hidify_uuid"], enable=False, is_active=False, reseller_id=reseller_id)
                except Exception as e:
                    logger.warning(f"Error bulk disabling user {sub['hidify_uuid']} in Hiddify: {e}")
            del_res = db.delete_reseller_subscription(reseller_id, sub_id, reason=final_bulk_reason)
            if del_res.get("success"):
                success_count += 1
                total_refund += del_res.get("refund_amount", 0)
        elif action == "clear_debt":
            db.clear_subscription_debt(sub_id, reseller_id=reseller_id)
            success_count += 1
        elif action == "send_reminder":
            tg_id = sub.get("telegram_id")
            debt_amount = sub.get("debt_amount") or 0
            if tg_id and int(tg_id) > 0 and debt_amount > 0:
                try:
                    r_info = db.get_reseller(reseller_id) or {}
                    card_number = r_info.get("card_number") or db.get_setting("card_number") or ""
                    card_holder = r_info.get("card_holder") or db.get_setting("card_holder") or ""
                    bank_name = r_info.get("bank_name") or db.get_setting("bank_name") or ""
                    msg = (
                        f"🌸 <b>کاربر گرامی، با سلام و احترام</b>\n\n"
                        f"📋 <b>یادآوری صورت‌حساب اشتراک:</b> «{sub.get('account_name')}»\n"
                        f"💰 <b>مبلغ بدهی / مانده پرداخت:</b> <code>{debt_amount:,}</code> تومان\n"
                    )
                    if sub.get("debt_notes"):
                        msg += f"📝 <b>توضیحات:</b> {sub.get('debt_notes')}\n"
                    if card_number:
                        msg += f"\n💳 <b>شماره کارت جهت واریز:</b>\n<code>{card_number}</code>\n👤 بنام: {card_holder} ({bank_name})\n"
                    msg += "\n🙏 لطفاً پس از واریز، تصویر فیش پرداخت خود را در همین بات ارسال فرمایید."
                    send_telegram_msg(tg_id, msg, bot_token=r_info.get("bot_token"))
                    success_count += 1
                except Exception:
                    pass

    if action == "delete":
        if total_refund > 0:
            flash(f"✅ تعداد {success_count} اشتراک با موفقیت حذف شدند و مبلغ {total_refund:,} تومان به کیف پول شما استرداد یافت.", "success")
        else:
            flash(f"✅ تعداد {success_count} اشتراک با موفقیت حذف شدند.", "success")
        r_after = db.get_reseller(reseller_id)
        if r_after:
            session["balance"] = r_after.get("balance", 0)
    elif action == "disable":
        flash(f"✅ تعداد {success_count} اشتراک با موفقیت غیرفعال شدند.", "info")
    elif action == "enable":
        flash(f"✅ تعداد {success_count} اشتراک با موفقیت فعال‌سازی مجدد شدند.", "success")
    elif action == "clear_debt":
        flash(f"✅ بدهی تعداد {success_count} اشتراک با موفقیت تسویه گردید.", "success")
    elif action == "send_reminder":
        flash(f"✅ پیام یادآوری بدهی برای {success_count} کاربر در تلگرام ارسال شد.", "success")
    else:
        flash(f"عملیات برای {success_count} اشتراک انجام شد.", "info")

    return redirect(get_redirect_target("reseller_users"))


@app.route("/reseller/transactions")
@reseller_required
def reseller_transactions():
    """لیست تراکنش‌ها، قبوض بدهی و شارژ کیف پول نماینده"""
    reseller_id = session.get("reseller_id")
    tx_list = db.get_reseller_transactions(reseller_id)
    debts = db.get_reseller_debts(reseller_id)
    stats = db.get_reseller_stats(reseller_id)
    bundles = db.get_reseller_credit_bundles(active_only=True)
    admin_cards = db.get_active_bank_cards()
    admin_gateway = db.get_admin_gateway()
    return render_template(
        "reseller_transactions.html",
        transactions=tx_list,
        debts=debts,
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
                is_active=is_active,
                preserve_specs=True
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

    receipt_file = request.files.get("receipt_image")
    has_image = bool(receipt_file and receipt_file.filename)

    if not tracking_code and not has_image:
        flash("لطفاً متن رسید پرداخت یا فایل تصویر فیش واریزی را ارسال فرمایید.", "danger")
        return redirect(url_for("reseller_transactions"))

    import random
    order_id = f"R_BUNDLE_CARD_{reseller_id}_{int(datetime.now().timestamp() * 1000)}_{random.randint(100, 999)}"
    reseller = db.get_reseller(reseller_id) or {}
    username = reseller.get("username", f"reseller_{reseller_id}")

    receipt_file_path = None
    if has_image:
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
        tracking_code=tracking_code or (f"تصویر فیش ({receipt_file_path})" if receipt_file_path else order_id),
        status="pending",
        receipt_image=receipt_file_path or tracking_code,
        receipt_file_type="web_upload" if receipt_file_path else "tracking_code",
        account_comment=notes,
        notes=notes,
        reseller_id=reseller_id
    )

    try:
        admin_tg = db.get_setting("admin_telegram_id") or get_admin_id()
        if admin_tg:
            bundle_notif = (
                f"📦 <b>رسید خرید بسته اعتباری نماینده!</b>\n\n"
                f"👤 نماینده: <b>{username}</b> (کد #{reseller_id})\n"
                f"📋 بسته: <b>{bundle['title']}</b>\n"
                f"💰 مبلغ پرداختی: <b>{bundle['price']:,} تومان</b>\n"
                f"🎁 اعتبار شارژ: <b>{bundle['credit']:,} تومان</b>\n"
                f"🔢 کد رهگیری: <code>{tracking_code or 'ثبت شده با عکس فیش'}</code>\n"
                f"🆔 کد سفارش: <code>{order_id}</code>\n"
                f"⏰ زمان: {get_now_shamsi()}"
            )
            adm_bundle_kb = {
                "inline_keyboard": [
                    [
                        {"text": "✅ تایید فیش و شارژ کیف پول", "callback_data": f"adm_pay_app_{order_id}"},
                        {"text": "❌ رد فیش", "callback_data": f"adm_pay_rej_{order_id}"}
                    ]
                ]
            }
            send_telegram_msg(int(admin_tg), bundle_notif, reply_markup=adm_bundle_kb)
    except Exception as e_b_tg:
        logger.warning(f"Failed to notify admin of bundle receipt: {e_b_tg}")

    flash(f"✅ رسید پرداخت برای «{bundle['title']}» با موفقیت ثبت شد. پس از بررسی و تایید مدیریت، مبلغ {bundle['credit']:,} تومان (با {bundle['badge']}) به کیف پول شما اضافه خواهد شد.", "success")
    return redirect(url_for("reseller_transactions"))


@app.route("/api/reseller/bundles/create-smart-invoice", methods=["POST"])
@reseller_required
def reseller_bundles_create_smart_invoice():
    """صدور فاکتور هوشمند کارت‌به‌کارت با ارقام خرد برای خرید بسته اعتباری همکار"""
    reseller_id = session.get("reseller_id")
    bundle_id = request.form.get("bundle_id") or (request.json.get("bundle_id") if request.is_json else None)
    bundles = {b["id"]: b for b in db.get_reseller_credit_bundles()}
    bundle = bundles.get(bundle_id)
    if not bundle:
        return jsonify({"success": False, "error": "بسته اعتباری مورد نظر یافت نشد."}), 404

    admin_cards = db.get_active_bank_cards()
    if not admin_cards:
        return jsonify({"success": False, "error": "شماره کارت فعالی برای مدیریت در سیستم تعریف نشده است."}), 400

    target_card = admin_cards[0]
    price = bundle["price"]

    sms_cfg = db.get_admin_bank_sms_config()
    digits = sms_cfg.get("digits", 3) if isinstance(sms_cfg, dict) else 3
    timeout = sms_cfg.get("timeout", 20) if isinstance(sms_cfg, dict) else 20

    invoice = db.create_smart_invoice(
        sub_id=0,
        plan_id=bundle_id,
        reseller_id=0,  # واریز به حساب مدیریت برای تایید پیامک بانک
        base_amount=price,
        target_card=target_card,
        digits=digits,
        timeout_minutes=timeout,
        instant_activation=True
    )

    now_iso = get_now_iso()
    reseller = db.get_reseller(reseller_id) or {}
    username = reseller.get("username", f"reseller_{reseller_id}")

    # ذخیره تراکنش معلق
    conn = db.get_connection()
    conn.execute("""
        INSERT OR REPLACE INTO transactions (
            order_id, user_id, username, plan_name, amount, status, gateway,
            tracking_code, reseller_id, is_renewal, account_name, source, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, 'pending', 'bundle_reseller', ?, ?, 0, ?, 'reseller_panel', ?, ?)
    """, (
        invoice["order_id"], reseller.get("telegram_id") or reseller_id, username,
        f"بسته {bundle['title']}", invoice["final_amount"],
        f"کارت {target_card.get('card_number', '')}", reseller_id,
        username, now_iso, now_iso
    ))
    conn.commit()
    conn.close()

    return jsonify({
        "success": True,
        "order_id": invoice["order_id"],
        "token": invoice["token"],
        "final_amount_toman": invoice["final_amount"],
        "final_amount_rial": invoice["final_amount"] * 10,
        "card_number": target_card.get("card_number"),
        "card_holder": target_card.get("card_holder"),
        "bank_name": target_card.get("bank_name"),
        "expires_at": invoice["expires_at"]
    })


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
    invoice_id = None
    if gw_type == "zarinpal":
        from payment import ZarinPal
        zp = ZarinPal(merchant_id=gw_key, sandbox=sandbox)
        res = zp.create_payment(amount=price, description=f"خرید بسته اعتباری {bundle['title']}", callback_url=callback_url)
        if res.get("success"):
            pay_url = res.get("payment_url")
            invoice_id = res.get("authority")
    elif gw_type == "idpay":
        from payment import IDPay
        idp = IDPay(api_key=gw_key, sandbox=sandbox)
        res = idp.create_payment(amount=price, name=reseller.get("name") or username, description=f"خرید بسته {bundle['title']}", callback_url=callback_url, order_id=order_id)
        if res.get("success"):
            pay_url = res.get("payment_url")
            invoice_id = res.get("payment_id")
    elif gw_type == "blupal":
        from payment import BluPal
        bp = BluPal(api_key=gw_key, sandbox=sandbox)
        res = bp.create_payment(amount=price, order_id=order_id, description=f"خرید بسته اعتباری {bundle['title']}")
        if res.get("success"):
            pay_url = res.get("payment_url") or res.get("payment_link")
            invoice_id = res.get("invoice_id")

    if pay_url:
        db.save_transaction(
            order_id=order_id,
            user_id=reseller.get("telegram_id") or reseller_id,
            username=username,
            plan_name=f"بسته {bundle['title']}",
            amount=price,
            gateway=f"{gw_type}_admin",
            tracking_code=str(invoice_id or order_id),
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
    """گزارشات، گردش حساب ۳۰ روز اخیر و هوش مالی پیشرفته نماینده فروش"""
    reseller_id = session.get("reseller_id")
    reseller = db.get_reseller(reseller_id)
    stats = db.get_reseller_stats(reseller_id)
    analytics = db.get_advanced_analytics(reseller_id=reseller_id)
    fin_summary = db.get_reseller_financial_summary(reseller_id)
    monthly_audit = db.get_monthly_accounting_audit(reseller_id=reseller_id, days=30)

    return render_template(
        "reseller_reports.html",
        reseller=reseller,
        stats=stats,
        fin_summary=fin_summary,
        monthly_audit=monthly_audit,
        popular_plans=analytics.get("popular_plans", []),
        top_users_month=analytics.get("top_users_month", []),
        top_users_year=analytics.get("top_users_year", []),
        most_active_users=analytics.get("most_active_users", []),
        usage_history=analytics.get("usage_history", []),
        timeline_subscriptions=analytics.get("timeline_subscriptions", [])
    )


@app.route("/reseller/reports/export/monthly-audit")
@reseller_required
def reseller_reports_export_monthly_audit():
    """خروجی اکسل/CSV استاندارد با فرمت UTF-8 BOM از حسابرسی و گردش حساب ۳۰ روز اخیر نماینده"""
    reseller_id = session.get("reseller_id")
    reseller = db.get_reseller(reseller_id)
    if not reseller:
        flash("اطلاعات نماینده یافت نشد.", "danger")
        return redirect(url_for("reseller_reports"))

    audit = db.get_monthly_accounting_audit(reseller_id=reseller_id, days=30)
    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([f"گزارش حسابرسی و گردش حساب ۳۰ روز اخیر نماینده: {reseller.get('name')} (@{reseller.get('username')})"])
    writer.writerow(["تاریخ تهیه گزارش:", filter_shamsi_date(get_now_iso())])
    writer.writerow([])
    writer.writerow(["--- شاخص‌های مالی و عملکرد دوره ---"])
    writer.writerow(["فروش کل (تومان)", "فروش نقدی (تومان)", "خرید/فروش اعتباری (تومان)", "بهای تمام شده پلن‌ها (تومان)", "سود ناخالص نماینده (تومان)", "ترافیک مصرفی کل (GB)", "تعداد کل اشتراک‌ها", "مانده بدهی اعتباری"])
    writer.writerow([
        f"{audit['total_revenue']:,}",
        f"{audit['cash_revenue']:,}",
        f"{audit['credit_revenue']:,}",
        f"{audit['total_expenses']:,}",
        f"{audit['net_profit']:,}",
        f"{audit['total_gb_sold']:.1f}",
        audit['total_subs_count'],
        f"{audit['total_outstanding_debt']:,}"
    ])
    writer.writerow([])
    writer.writerow(["--- ریز تراکنش‌ها و سفارشات ۳۰ روز اخیر ---"])
    writer.writerow(["شناسه", "کد سفارش", "مشتری / کاربر", "پلن", "مبلغ (تومان)", "روش پرداخت", "کد پیگیری", "تاریخ ثبت (شمسی)"])

    for tx in audit.get("transactions", []):
        c_at = tx.get("created_at") or ""
        writer.writerow([
            tx.get("id"),
            tx.get("order_id") or "",
            tx.get("username") or tx.get("user_id") or "",
            tx.get("plan_name") or "",
            tx.get("amount") or 0,
            tx.get("gateway") or "",
            tx.get("tracking_code") or "",
            filter_shamsi_date(c_at) if c_at else ""
        ])

    csv_data = "\ufeff" + output.getvalue()
    filename = f"reseller_monthly_audit_{reseller_id}_{get_now_iso()[:10]}.csv"
    return Response(
        csv_data.encode("utf-8-sig"),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment;filename={filename}"}
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
    """پایش بلادرنگ اعلان‌ها، فیش‌های دریافتی مشتریان و تغییر وضعیت برای نماینده"""
    reseller_id = session.get("reseller_id")
    unread_notifs = db.get_reseller_notifications(reseller_id, unread_only=True, limit=10)
    
    conn = db.get_connection()
    cursor = conn.cursor()
    
    # فیش‌های پرداخت در انتظار تایید مشتریان ربات این نماینده
    cursor.execute("""
        SELECT COUNT(*) FROM transactions 
        WHERE reseller_id = ? 
          AND (gateway != 'bundle_reseller' AND order_id NOT LIKE 'R_BUNDLE%')
          AND (is_deleted = 0 OR is_deleted IS NULL)
          AND status = 'pending'
    """, (reseller_id,))
    pending_customer_receipts_count = cursor.fetchone()[0] or 0

    # تیکت‌های باز مشتریان این نماینده
    cursor.execute("""
        SELECT COUNT(*) FROM support_tickets 
        WHERE reseller_id = ? AND status = 'open' 
          AND (ticket_type NOT IN ('reseller_to_admin', 'quota_change') OR ticket_type IS NULL) 
          AND (target_role IS NULL OR target_role != 'admin')
    """, (reseller_id,))
    open_customer_tickets_count = cursor.fetchone()[0] or 0

    # پیام‌ها یا تیکت‌های پاسخ‌داده‌شده توسط مدیریت به این نماینده
    cursor.execute("""
        SELECT COUNT(*) FROM support_tickets 
        WHERE reseller_id = ? AND status = 'replied' 
          AND (ticket_type IN ('reseller_to_admin', 'quota_change') OR target_role = 'admin')
    """, (reseller_id,))
    admin_replied_tickets_count = cursor.fetchone()[0] or 0

    # کل تیکت‌های نیازمند اقدام
    open_tickets_count = open_customer_tickets_count + admin_replied_tickets_count

    # دریافت آخرین فیش‌های اخیر جهت آگاهی از تغییر وضعیت
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
        "pending_customer_receipts_count": pending_customer_receipts_count,
        "open_customer_tickets_count": open_customer_tickets_count,
        "admin_replied_tickets_count": admin_replied_tickets_count,
        "open_tickets_count": open_tickets_count,
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


@app.route("/api/reseller/balance")
@reseller_required
def api_reseller_balance():
    """دریافت زنده و لحظه‌ای موجودی کیف پول نماینده جهت بروزرسانی خودکار UI بدون نیاز به رفرش"""
    reseller_id = session.get("reseller_id")
    r_data = db.get_reseller(reseller_id)
    balance = r_data.get("balance", 0) if r_data else 0
    session["balance"] = balance
    return jsonify({
        "success": True,
        "balance": balance,
        "formatted": f"{balance:,}",
        "formatted_full": f"{balance:,} ت"
    })


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

        # دریافت ادمین‌های تلگرام ربات با نقش‌های مختلف
        admin_tids = request.form.getlist("admin_telegram_id[]")
        admin_roles = request.form.getlist("admin_role[]")
        admin_titles = request.form.getlist("admin_title[]")

        bot_admins = []
        primary_admin_id = None
        for tid, role, title in zip(admin_tids, admin_roles, admin_titles):
            tid_clean = re.sub(r"\D", "", str(tid or ""))
            if tid_clean:
                numeric_tid = int(tid_clean)
                role_clean = role if role in ("main", "finance", "support", "sales") else "main"
                bot_admins.append({
                    "telegram_id": numeric_tid,
                    "role": role_clean,
                    "title": str(title or "").strip()
                })
                if role_clean == "main" and primary_admin_id is None:
                    primary_admin_id = numeric_tid

        # اگر ادمین اصلی وجود نداشت اما اولین ادمین دیگر موجود بود
        if not primary_admin_id and bot_admins:
            primary_admin_id = bot_admins[0]["telegram_id"]

        bot_admins_json = json.dumps(bot_admins, ensure_ascii=False) if bot_admins else None

        update_kwargs = {
            "bot_token": bot_token,
            "bot_username": bot_username,
            "channel_id": channel_id,
            "brand_name": brand_name,
            "start_message": start_message,
            "support_username": support_username,
            "card_number": card_number,
            "card_holder": card_holder,
            "bank_name": bank_name,
            "vip_auto_enabled": vip_auto_enabled,
            "vip_auto_threshold": vip_auto_threshold,
            "vip_cashback_percent": vip_cashback_percent,
            "bot_admins": bot_admins_json
        }
        if primary_admin_id:
            update_kwargs["telegram_id"] = primary_admin_id

        db.update_reseller_bot_settings(reseller_id, **update_kwargs)

        # تنظیمات درگاه پرداخت آنلاین اختصاصی نماینده
        is_gw_active = request.form.get("is_gateway_active") in ("on", "1")
        gw_type = request.form.get("gateway_type", "zarinpal").strip().lower()
        gw_key = request.form.get("gateway_key", "").strip()
        gw_sandbox = request.form.get("gateway_sandbox") in ("on", "1")
        db.update_reseller_gateway(reseller_id, is_gw_active, gw_type, gw_key, gw_sandbox)

        # ریلود کانفیگ ربات نماینده در multibot_manager
        multibot_manager.restart_reseller_bot(reseller_id)

        flash("تنظیمات ربات اختصاصی، ادمین‌های تلگرام، باشگاه VIP و درگاه پرداخت با موفقیت ذخیره شد.", "success")
        return redirect(url_for("reseller_bot_settings"))

    bot_status = multibot_manager.get_bot_status(reseller_id)
    reseller_gateway = db.get_reseller_gateway(reseller_id)
    bot_admins = db.get_reseller_bot_admins(reseller_id)
    return render_template(
        "reseller_bot_settings.html",
        reseller=reseller,
        bot_status=bot_status,
        reseller_gateway=reseller_gateway,
        bot_admins=bot_admins
    )


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
    """لیست و تایید فیش‌های واریزی مشتریان ربات و پرتال نماینده"""
    reseller_id = session.get("reseller_id")
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM transactions 
        WHERE reseller_id = ? AND (gateway != 'bundle_reseller' AND order_id NOT LIKE 'R_BUNDLE%') AND (is_deleted = 0 OR is_deleted IS NULL)
        ORDER BY CASE WHEN status = 'pending' THEN 0 ELSE 1 END, id DESC
    """, (reseller_id,))
    raw_txs = [dict(r) for r in cursor.fetchall()]
    conn.close()
    
    # واکشی سریع اشتراک‌های نماینده جهت تطبیق هوشمند مشخصات مشتری
    sub_list = db.get_reseller_subscriptions(reseller_id)
    sub_map = {s["id"]: s for s in sub_list}
    sub_by_acc = {s["account_name"]: s for s in sub_list if s.get("account_name")}

    portal_count = 0
    telegram_count = 0
    transactions = []

    for tx in raw_txs:
        src = str(tx.get("source") or "").lower()
        order_id = str(tx.get("order_id") or "")
        gateway = str(tx.get("gateway") or "")
        user_id = tx.get("user_id") or 0
        renew_sub_id = tx.get("renew_sub_id")
        
        origin = determine_transaction_origin(tx)
        tx["source"] = origin
            
        # یافتن اشتراک مرتبط در صورت وجود
        matched_sub = None
        if renew_sub_id and renew_sub_id in sub_map:
            matched_sub = sub_map[renew_sub_id]
        elif tx.get("subscription_id") and tx["subscription_id"] in sub_map:
            matched_sub = sub_map[tx["subscription_id"]]
        elif tx.get("account_name") and tx["account_name"] in sub_by_acc:
            matched_sub = sub_by_acc[tx["account_name"]]

        tx["sub_info"] = matched_sub
        
        # استخراج نام شفاف و معتبر برای نمایش مشتری
        if origin in ("portal", "admin", "reseller"):
            customer_name = tx.get("account_name")
            if not customer_name and matched_sub:
                customer_name = matched_sub.get("account_name")
            if not customer_name:
                customer_name = tx.get("username")
            if not customer_name or customer_name in ("None", "null", "", "کاربر"):
                customer_name = f"مشتری #{renew_sub_id or tx['id']}"
            tx["customer_name"] = customer_name
            tx["customer_phone"] = matched_sub.get("phone_number") if matched_sub else None
        else:
            cust_name = tx.get("username")
            if not cust_name or cust_name in ("None", "null", "", "کاربر"):
                cust_name = f"کاربر {user_id}" if user_id else "کاربر تلگرام"
            tx["customer_name"] = cust_name
            tx["customer_phone"] = None
            
        transactions.append(tx)
        
    portal_count = sum(1 for tx in transactions if tx.get("source") == "portal")
    telegram_count = sum(1 for tx in transactions if tx.get("source") == "telegram")
    reseller_count = sum(1 for tx in transactions if tx.get("source") == "reseller")
    admin_count = sum(1 for tx in transactions if tx.get("source") == "admin")

    stats = db.get_reseller_stats(reseller_id)
    return render_template(
        "reseller_customer_payments.html", 
        transactions=transactions, 
        stats=stats,
        portal_count=portal_count,
        telegram_count=telegram_count,
        reseller_count=reseller_count,
        admin_count=admin_count
    )


@app.route("/reseller/payment/<int:payment_id>/approve", methods=["POST"])
@reseller_required
def reseller_payment_approve(payment_id):
    """تایید فیش پرداخت مشتری توسط نماینده در وب، کسر از کیف پول و صدور یا تمدید اشتراک"""
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

    user_id = tx.get("user_id") or 0
    plan_name = tx["plan_name"]
    plans = get_reseller_plans_dict(reseller_id)
    selected_plan = next((p for p in plans.values() if p.get("name") == plan_name or p.get("display_name") == plan_name or p.get("master_name") == plan_name or str(p.get("plan_id")) == str(tx.get("plan_id"))), None)
    if not selected_plan and plans:
        selected_plan = list(plans.values())[0]

    data_limit = selected_plan.get("display_data_limit") if selected_plan and selected_plan.get("display_data_limit") is not None else (selected_plan.get("data_limit") if selected_plan else 30)
    duration = selected_plan.get("display_duration") if selected_plan and selected_plan.get("display_duration") is not None else (selected_plan.get("duration") if selected_plan else 30)
    original_price = selected_plan.get("display_price") or selected_plan.get("price") if selected_plan else tx.get("amount", 0)

    # محاسبه هزینه خرید عمده نماینده با تخفیف
    stats = db.get_reseller_stats(reseller_id)
    discount = stats.get("discount_percent", 20)
    wholesale_price = selected_plan.get("wholesale_price") if selected_plan and selected_plan.get("wholesale_price") is not None else (original_price - int((original_price * discount) / 100))

    if stats["balance"] < wholesale_price:
        flash(f"موجودی کیف پول شما کافی نیست! موجودی: {stats['balance']:,} ت | مبلغ کسر: {wholesale_price:,} ت", "danger")
        return redirect(url_for("reseller_payments"))

    is_renewal = bool(tx.get("is_renewal"))
    renew_sub_id = tx.get("renew_sub_id")
    target_sub = None
    if is_renewal and renew_sub_id:
        target_sub = db.get_reseller_subscription(reseller_id, renew_sub_id) or db.get_subscription(renew_sub_id)

    approver_user = session.get("username") or f"reseller_{reseller_id}"
    res_profit = max(0, original_price - wholesale_price)
    sub_link = ""

    if target_sub:
        # تمدید اشتراک موجود مشتری (تمدید هوشمند پرتال / ربات بدون ایجاد اکانت تکراری)
        account_name = target_sub.get("account_name")
        smart_inv = db.get_smart_invoice_by_order_id(tx.get("order_id"))
        instant_act = bool(smart_inv.get("instant_activation", 1)) if smart_inv else True

        db.deduct_reseller_balance(reseller_id, wholesale_price, plan_name, account_name, selling_price=original_price, profit_margin=res_profit, created_by=approver_user)
        
        if instant_act and target_sub.get("hidify_uuid"):
            try:
                hidify_sync_renew_user(target_sub["hidify_uuid"], data_limit, duration, force_instant=True)
            except Exception as e:
                logger.error(f"Error renewing user in Hiddify: {e}")

        plan_id_val = str(selected_plan.get("id") or selected_plan.get("plan_id") or 1) if selected_plan else "1"
        db.renew_reseller_subscription(
            reseller_id=reseller_id,
            sub_id=target_sub["id"],
            plan_id=plan_id_val,
            cost=wholesale_price,
            instant_activate=instant_act,
            payment_source="wallet",
            selling_price=original_price,
            profit_margin=res_profit,
            creator=approver_user
        )
        sub_uuid = target_sub.get("hidify_uuid") or str(target_sub["id"])
        h_url = get_hiddify_url()
        u_proxy = get_user_proxy()
        sub_link = f"{h_url}/{u_proxy}/{sub_uuid}/" if (h_url and sub_uuid) else f"https://vpn.service/sub/{account_name}"
    else:
        # ساخت اکانت جدید در هیدیفای و دیتابیس
        account_name = tx.get("account_name") or f"r_{reseller_id}_{user_id}_{int(time.time()) % 10000}"
        user_comment = f"Reseller #{reseller_id} ({session.get('name')}) via Web"

        h_res = hidify_sync_create_user(
            name=account_name,
            usage_limit_gb=data_limit,
            package_days=duration,
            comment=user_comment
        )

        uuid_val = h_res.get("uuid", "") if h_res else ""
        sub_link = h_res.get("subscription_url", "") if h_res else ""
        if not uuid_val:
            import uuid
            uuid_val = str(uuid.uuid4())
            sub_link = f"https://vpn.service/sub/{account_name}"

        # کسر از کیف پول نماینده
        db.deduct_reseller_balance(reseller_id, wholesale_price, plan_name, account_name, selling_price=original_price, profit_margin=res_profit, created_by=approver_user)
        
        # ثبت اشتراک برای کاربر
        plan_id_val = str(selected_plan.get("id") or 1) if selected_plan else "1"
        sub_row_id = db.save_subscription(
            telegram_id=user_id,
            hidify_uuid=uuid_val,
            plan_id=plan_id_val,
            plan_name=plan_name,
            data_limit=float(data_limit),
            duration=int(duration),
            data_used=0.0,
            status="active",
            account_name=account_name,
            account_comment=user_comment,
            reseller_id=reseller_id,
            created_by=approver_user
        )

        # واریز پورسانت زیرمجموعه‌گیری به بالادستی
        try:
            sub_id_int = sub_row_id.get("subscription_id") if isinstance(sub_row_id, dict) else sub_row_id
            plan_base_price = int(selected_plan.get("price") or wholesale_price) if selected_plan else wholesale_price
            db.process_sub_reseller_affiliate_commission(
                sub_reseller_id=reseller_id,
                plan_price=plan_base_price,
                plan_name=plan_name,
                account_name=account_name,
                sub_id=sub_id_int
            )
        except Exception as e:
            logger.error(f"Error processing affiliate commission in quick create: {e}")

    r_after = db.get_reseller(reseller_id)
    if r_after:
        session["balance"] = r_after.get("balance", 0)

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

    # تکمیل وضعیت فاکتور هوشمند در صورت وجود
    try:
        if tx.get("order_id"):
            db.mark_smart_invoice_paid(tx["order_id"], tracking_code=tx.get("tracking_code"))
    except Exception:
        pass

    reseller_data = db.get_reseller(reseller_id)
    bot_tok = reseller_data.get("bot_token") if reseller_data else None
    brand_title = reseller_data.get("brand_name") or "فروشگاه"
    cashback_note = ""

    # پردازش کش‌بک مشتریان VIP نماینده (تنها در صورت داشتن آیدی تلگرام)
    if user_id and int(user_id) > 0:
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

    flash(f"پرداخت سفارش #{payment_id} با موفقیت تایید و اعمال شد.", "success")
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
        "UPDATE transactions SET status = 'rejected', rejection_reason = ?, processed_by = ?, processed_at = ?, updated_at = ? WHERE id = ?", 
        (reason, f"{reseller_name} (نماینده #{reseller_id})", now_iso, now_iso, payment_id)
    )
    conn.commit()

    # به روزرسانی فاکتور هوشمند در صورت وجود
    if tx.get("order_id"):
        try:
            cursor.execute("UPDATE smart_invoices SET status = 'rejected' WHERE order_id = ?", (tx["order_id"],))
            conn.commit()
        except Exception:
            pass

    conn.close()

    # اطلاع به کاربر (تنها در صورت داشتن آیدی تلگرام)
    user_id = tx.get("user_id") or 0
    if user_id and int(user_id) > 0:
        reseller_data = db.get_reseller(reseller_id)
        bot_tok = reseller_data.get("bot_token") if reseller_data else None
        msg_to_user = f"❌ **پرداخت سفارش شما تایید نشد.**\n\nعلت: {reason}\nدر صورت داشتن هرگونه سوال با پشتیبانی تماس بگیرید."
        if bot_tok:
            send_telegram_msg(user_id, msg_to_user, bot_token=bot_tok)
        else:
            send_telegram_msg(user_id, msg_to_user)

    flash("فیش پرداخت با موفقیت رد شد و وضعیت آن ثبت گردید.", "info")
    return redirect(url_for("reseller_customer_payments"))


@app.route("/reseller/customer-payments/bulk", methods=["POST"])
@reseller_required
def reseller_customer_payments_bulk():
    """عملیات گروهی روی فیش‌های پرداخت مشتریان نماینده (رد، حذف)"""
    reseller_id = session.get("reseller_id")
    action = request.form.get("bulk_action")
    raw_ids = request.form.getlist("selected_ids") or [x.strip() for x in request.form.get("selected_ids_str", "").split(",") if x.strip()]
    payment_ids = []
    for p_id in raw_ids:
        try:
            val = int(str(p_id).strip())
            if val > 0:
                payment_ids.append(val)
        except (ValueError, TypeError):
            continue

    if not payment_ids:
        flash("هیچ فیش پرداختی انتخاب نشده است.", "warning")
        return redirect(url_for("reseller_customer_payments"))

    success_count = 0
    now_iso = get_now_iso()
    reseller_name = session.get("name") or session.get("username") or f"نماینده #{reseller_id}"

    for pid in payment_ids:
        conn = db.get_connection()
        tx_row = conn.execute("SELECT * FROM transactions WHERE id=? AND reseller_id=?", (pid, reseller_id)).fetchone()
        if not tx_row:
            conn.close()
            continue

        if action == "reject":
            conn.execute("UPDATE transactions SET status='rejected', rejection_reason='رد توسط نماینده در عملیات گروهی', processed_by=?, processed_at=?, updated_at=? WHERE id=?", (f"{reseller_name} (نماینده #{reseller_id})", now_iso, now_iso, pid))
            conn.commit()
            success_count += 1
        elif action == "delete":
            conn.execute("DELETE FROM transactions WHERE id=? AND reseller_id=?", (pid, reseller_id))
            conn.commit()
            success_count += 1
        conn.close()

    if action == "reject":
        flash(f"✅ تعداد {success_count} فیش پرداخت با موفقیت رد شدند.", "info")
    elif action == "delete":
        flash(f"✅ تعداد {success_count} فیش پرداخت حذف شدند.", "success")
    else:
        flash(f"عملیات برای {success_count} فیش انجام شد.", "info")

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
        elif action == "save_reseller_bank_sms":
            enabled = bool(request.form.get("bank_sms_enabled"))
            digits = int(request.form.get("bank_sms_digits", 3))
            timeout = int(request.form.get("bank_sms_timeout", 15))
            regenerate = bool(request.form.get("regenerate_token"))
            db.save_reseller_bank_sms_config(reseller_id, enabled=enabled, digits=digits, timeout=timeout, regenerate_token=regenerate)
            flash("تنظیمات تایید خودکار با پیامک بانک برای پنل شما با موفقیت ذخیره شد.", "success")
        elif action == "save_reseller_crypto":
            enabled = bool(request.form.get("crypto_enabled"))
            wallet_address = request.form.get("crypto_wallet_address", "").strip()
            usdt_rate = int(request.form.get("crypto_usdt_rate", 90000) or 90000)
            db.save_reseller_crypto_config(reseller_id, enabled, wallet_address, usdt_rate)
            flash("تنظیمات درگاه ارزی و کیف پول تتر با موفقیت ذخیره شد.", "success")

        return redirect(url_for("reseller_cards"))

    cards = db.get_reseller_cards(reseller_id)
    payment_methods = db.get_payment_methods(reseller_id=reseller_id)
    reseller_gateway = db.get_reseller_gateway(reseller_id)
    reseller_crypto = db.get_reseller_crypto_config(reseller_id)

    r_info = db.get_reseller(reseller_id) or {}
    domain = r_info.get("custom_domain") or db.get_setting("custom_domain") or os.getenv("PANEL_DOMAIN", "http://localhost:5000")
    if not str(domain).startswith("http"):
        domain = f"https://{domain}"
    blupal_webhook_url = f"{str(domain).rstrip('/')}/payment/blupal/webhook"
    blupal_callback_url = f"{str(domain).rstrip('/')}/payment/blupal/callback"

    reseller_bank_sms = db.get_reseller_bank_sms_config(reseller_id)
    bank_sms_webhook_url = f"{str(domain).rstrip('/')}/api/bank-sms/webhook?token={reseller_bank_sms['token']}"
    bank_sms_logs = db.get_bank_sms_logs(owner_type="reseller", owner_id=reseller_id, limit=15)

    return render_template(
        "reseller_cards.html",
        cards=cards,
        payment_methods=payment_methods,
        reseller_gateway=reseller_gateway,
        reseller_crypto=reseller_crypto,
        blupal_webhook_url=blupal_webhook_url,
        blupal_callback_url=blupal_callback_url,
        reseller_bank_sms=reseller_bank_sms,
        bank_sms_webhook_url=bank_sms_webhook_url,
        bank_sms_logs=bank_sms_logs
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
    """مشاهده و مدیریت تیکت‌های پشتیبانی مشتریان ربات نماینده و مکاتبات با مدیریت"""
    reseller_id = session.get("reseller_id")
    category_filter = request.args.get("category", "all")
    status_filter = request.args.get("status", "all")
    search = request.args.get("search", "").strip()
    prefill_subject = request.args.get("subject", "").strip()
    prefill_message = request.args.get("message", "").strip()
    open_modal = request.args.get("open_modal", "0").strip()

    ticket_list = db.get_all_tickets(status=status_filter, reseller_id=reseller_id, search=search, category=category_filter)
    stats = db.get_tickets_stats(reseller_id=reseller_id)

    return render_template(
        "reseller_tickets.html",
        tickets=ticket_list,
        status_filter=status_filter,
        category_filter=category_filter,
        search=search,
        stats=stats,
        prefill_subject=prefill_subject,
        prefill_message=prefill_message,
        open_modal=open_modal
    )


@app.route("/reseller/ticket/create-to-admin", methods=["POST"])
@reseller_required
def reseller_create_ticket_to_admin():
    """ارسال تیکت جدید از سمت نماینده به مدیریت با قالب‌های آماده"""
    reseller_id = session.get("reseller_id")
    subject = request.form.get("subject", "").strip()
    category_type = request.form.get("category_type", "").strip()
    message = request.form.get("message", "").strip()

    if not subject or not message:
        flash("لطفاً موضوع و متن پیام تیکت را وارد نمایید.", "warning")
        return redirect(url_for("reseller_tickets", category="admin"))

    full_subject = f"[{category_type}] {subject}" if category_type and category_type != "عمومی" else subject
    res = db.create_reseller_to_admin_ticket(reseller_id=reseller_id, subject=full_subject, message=message)
    if res.get("success"):
        ticket_id = res.get("ticket_id")
        try:
            admin_tg = db.get_setting("admin_telegram_id") or get_admin_id()
            if admin_tg:
                r_info = db.get_reseller(reseller_id) or {}
                r_name = r_info.get("name") or session.get("name") or f"نماینده #{reseller_id}"
                adm_notif = (
                    f"🎫 <b>تیکت جدید از نماینده برای مدیریت!</b>\n\n"
                    f"🆔 شماره تیکت: <b>#{ticket_id}</b>\n"
                    f"👤 نماینده: <b>{r_name}</b> (کد #{reseller_id})\n"
                    f"🔖 موضوع: <b>{full_subject}</b>\n"
                    f"📝 متن پیام:\n{message}\n"
                    f"⏰ زمان: {get_now_shamsi()}\n\n"
                    f"💡 پاسخگویی از دکمه‌های زیر یا دستور <code>/reply_ticket {ticket_id} متن پاسخ</code>"
                )
                adm_kb = {
                    "inline_keyboard": [
                        [
                            {"text": "✍️ پاسخ متنی", "callback_data": f"adm_reply_tkt_{ticket_id}"},
                            {"text": "⚡ پاسخ‌های آماده", "callback_data": f"adm_canned_tkt_{ticket_id}"}
                        ],
                        [
                            {"text": "🔒 بستن تیکت", "callback_data": f"adm_close_tkt_{ticket_id}"}
                        ]
                    ]
                }
                send_telegram_msg(int(admin_tg), adm_notif, reply_markup=adm_kb)
        except Exception as e_tg:
            logger.warning(f"Failed to notify admin of reseller ticket: {e_tg}")
        flash("✅ تیکت شما با موفقیت برای مدیریت ارسال شد و در اسرع وقت پاسخ داده می‌شود.", "success")
    else:
        flash(f"خطا در ارسال تیکت: {res.get('error')}", "danger")
    return redirect(url_for("reseller_tickets", category="admin"))


@app.route("/reseller/ticket/<int:ticket_id>/reply-to-admin", methods=["POST"])
@reseller_required
def reseller_ticket_reply_to_admin(ticket_id):
    """ارسال پاسخ یا ادامه گفتگو توسط نماینده در تیکت‌های مکاتبه با مدیریت"""
    reseller_id = session.get("reseller_id")
    reply_msg = request.form.get("reply_message", "").strip()
    if not reply_msg:
        flash("متن پیام نمی‌تواند خالی باشد.", "warning")
        return redirect(url_for("reseller_tickets", category="admin"))

    res = db.add_reseller_admin_ticket_reply(ticket_id=ticket_id, reseller_id=reseller_id, message=reply_msg)
    if res.get("success"):
        try:
            admin_tg = db.get_setting("admin_telegram_id") or get_admin_id()
            if admin_tg:
                r_info = db.get_reseller(reseller_id) or {}
                r_name = r_info.get("name") or r_info.get("display_name") or session.get("display_name") or session.get("name") or f"نماینده #{reseller_id}"
                adm_notif = (
                    f"💬 <b>پیام جدید در تیکت مکاتبه با نماینده!</b>\n\n"
                    f"🆔 شماره تیکت: <b>#{ticket_id}</b>\n"
                    f"👤 فرستنده: <b>{r_name}</b> (نماینده #{reseller_id})\n"
                    f"📝 متن پیام:\n{reply_msg}\n"
                    f"⏰ زمان: {get_now_shamsi()}\n\n"
                    f"💡 پاسخگویی از دکمه‌های زیر یا دستور <code>/reply_ticket {ticket_id} متن پاسخ</code>"
                )
                adm_kb = {
                    "inline_keyboard": [
                        [
                            {"text": "✍️ پاسخ متنی", "callback_data": f"adm_reply_tkt_{ticket_id}"},
                            {"text": "⚡ پاسخ‌های آماده", "callback_data": f"adm_canned_tkt_{ticket_id}"}
                        ],
                        [
                            {"text": "🔒 بستن تیکت", "callback_data": f"adm_close_tkt_{ticket_id}"}
                        ]
                    ]
                }
                send_telegram_msg(int(admin_tg), adm_notif, reply_markup=adm_kb)
        except Exception as e_tg:
            logger.warning(f"Failed to notify admin of reseller ticket reply: {e_tg}")
        flash("✅ پیام شما برای مدیریت ارسال شد.", "success")
    else:
        flash(f"خطا در ثبت پیام: {res.get('error')}", "danger")
    return redirect(url_for("reseller_tickets", category="admin"))


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

    sender_name = session.get("display_name") or session.get("name") or session.get("username") or "پشتیبانی نماینده"
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
        try:
            discount_percent = int(request.form.get("discount_percent") or 0)
        except (ValueError, TypeError):
            discount_percent = 0

        try:
            discount_amount = int(request.form.get("discount_amount") or 0)
        except (ValueError, TypeError):
            discount_amount = 0

        try:
            max_uses = int(request.form.get("max_uses") or 0)
        except (ValueError, TypeError):
            max_uses = 0

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
    """مدیریت تیم و کارمندان زیرمجموعه نماینده (مدیر دو، شریک، مالی، پشتیبانی)"""
    reseller_id = session.get("reseller_id")
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        display_name = request.form.get("display_name", "").strip()
        role = request.form.get("role", "support").strip()
        phone = request.form.get("phone", "").strip()
        share_percent = 0 if role == "manager2" else int(request.form.get("share_percent", 0))

        if not username or not password or not display_name:
            flash("نام کاربری، رمز عبور و نام نمایشی الزامی هستند.", "warning")
        else:
            res = db.create_reseller_team_member(reseller_id, username, password, display_name, role, phone, share_percent)
            if res.get("success"):
                role_label = "مدیر دوم" if role == "manager2" else role
                flash(f"عضو جدید «{display_name}» با نقش {role_label} افزوده شد.", "success")
            else:
                flash(f"خطا: {res.get('error')}", "danger")
        return redirect(get_redirect_target("reseller_team"))

    team_members = db.get_reseller_team_with_sessions(reseller_id)
    is_main_reseller = (session.get("role") == "reseller" and not session.get("sub_role"))
    return render_template("reseller_team.html", team_members=team_members, is_main_reseller=is_main_reseller)


@app.route("/reseller/team/<int:member_id>/toggle", methods=["POST"])
@reseller_required
def reseller_team_toggle(member_id):
    """فعال/غیرفعال‌سازی کارمند نماینده"""
    reseller_id = session.get("reseller_id")
    db.toggle_reseller_team_member(member_id, reseller_id)
    flash("وضعیت دسترسی کارمند تغییر یافت.", "info")
    return redirect(get_redirect_target("reseller_team"))


@app.route("/reseller/team/<int:member_id>/delete", methods=["POST"])
@reseller_required
def reseller_team_delete(member_id):
    """حذف کارمند نماینده"""
    reseller_id = session.get("reseller_id")
    db.delete_reseller_team_member(member_id, reseller_id)
    flash("کارمند از تیم شما حذف شد.", "info")
    return redirect(get_redirect_target("reseller_team"))


@app.route("/reseller/session/<int:session_id>/terminate", methods=["POST"])
@reseller_required
def reseller_terminate_session(session_id):
    """خاتمه نشست فعال توسط مدیر اصلی نماینده"""
    if session.get("sub_role"):
        flash("فقط مدیر اصلی حساب نمایندگی مجاز به خاتمه نشست‌ها می‌باشد.", "danger")
        return redirect(request.referrer or url_for("reseller_dashboard"))

    reseller_id = session.get("reseller_id")
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_type, user_id FROM login_logs WHERE id = ?", (session_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        flash("نشست مورد نظر یافت نشد.", "warning")
        return redirect(request.referrer or url_for("reseller_dashboard"))

    u_type = row["user_type"]
    u_id = row["user_id"]

    allowed = False
    if u_type == "reseller" and u_id == reseller_id:
        allowed = True
    elif u_type == "reseller_subadmin":
        team = db.get_reseller_team_members(reseller_id)
        if any(m["id"] == u_id for m in team):
            allowed = True

    if not allowed:
        flash("شما مجاز به خاتمه دادن به این نشست نیستید.", "danger")
        return redirect(request.referrer or url_for("reseller_dashboard"))

    success = db.terminate_session(session_id)
    if success:
        flash("نشست مورد نظر با موفقیت خاتمه یافت و کاربر مربوطه خارج شد.", "success")
    else:
        flash("خطا در خاتمه نشست یا نشست از قبل غیرفعال بوده است.", "warning")
    return redirect(request.referrer or url_for("reseller_team"))


@app.route("/reseller/team/<int:member_id>/terminate-sessions", methods=["POST"])
@reseller_required
def reseller_terminate_member_sessions(member_id):
    """خاتمه تمام نشست‌های فعال یک عضو تیم توسط مدیر اصلی نماینده"""
    if session.get("sub_role"):
        flash("فقط مدیر اصلی حساب نمایندگی مجاز به خاتمه نشست‌ها می‌باشد.", "danger")
        return redirect(request.referrer or url_for("reseller_team"))

    reseller_id = session.get("reseller_id")
    team = db.get_reseller_team_members(reseller_id)
    if not any(m["id"] == member_id for m in team):
        flash("این عضو متعلق به تیم شما نیست.", "danger")
        return redirect(request.referrer or url_for("reseller_team"))

    count = db.terminate_all_user_sessions("reseller_subadmin", member_id)
    flash(f"تعداد {count} نشست فعال این عضو تیم با موفقیت خاتمه یافت.", "success")
    return redirect(request.referrer or url_for("reseller_team"))


@app.route("/reseller/terminate-other-sessions", methods=["POST"])
@reseller_required
def reseller_terminate_other_sessions():
    """خاتمه تمام نشست‌های دیگر حساب خود نماینده به جز نشست فعلی"""
    if session.get("sub_role"):
        flash("فقط مدیر اصلی حساب نمایندگی مجاز به این عملیات است.", "danger")
        return redirect(request.referrer or url_for("reseller_profile"))

    reseller_id = session.get("reseller_id")
    current_token = session.get("session_token")
    count = db.terminate_all_user_sessions("reseller", reseller_id, except_token=current_token)
    flash(f"تعداد {count} نشست فعال دیگر حساب شما با موفقیت خاتمه یافتند.", "success")
    return redirect(request.referrer or url_for("reseller_profile"))


# ─── ۶. هویت بصری، لوگو و دامنه اختصاصی نماینده (Branding & Custom Domain) ───

@app.route("/reseller/branding", methods=["GET", "POST"])
@reseller_required
def reseller_branding():
    """تنظیمات هویت بصری، لوگو، رنگ‌بندی، عنوان و دامنه اختصاصی نماینده"""
    reseller_id = session.get("reseller_id")
    reseller = db.get_reseller(reseller_id) or {}

    if request.method == "POST":
        brand_title = request.form.get("brand_title", "").strip()
        logo_url = request.form.get("logo_url", "").strip()
        favicon_url = request.form.get("favicon_url", "").strip()
        primary_color = request.form.get("primary_color", "").strip()
        footer_text = request.form.get("footer_text", "").strip()
        portal_title = request.form.get("portal_title", "").strip()
        portal_subtitle = request.form.get("portal_subtitle", "").strip()
        support_phone = request.form.get("support_phone", "").strip()
        support_username = request.form.get("support_username", "").strip().lstrip("@")
        portal_layout = request.form.get("portal_layout", "").strip().lower()
        portal_plan_style = request.form.get("portal_plan_style", "").strip().lower()

        # بررسی پاک‌سازی یا آپلود لوگوی اختصاصی
        if request.form.get("clear_logo"):
            logo_url = ""
        elif "logo_file" in request.files:
            file = request.files["logo_file"]
            if file and file.filename:
                ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else "png"
                fn = f"reseller_{reseller_id}_logo_{int(time.time())}.{ext}"
                fp = AVATAR_CACHE_DIR / fn
                file.save(fp)
                logo_url = url_for("telegram_avatar", identifier=fn)

        if not request.form.get("clear_logo") and not logo_url and reseller and reseller.get("logo_url"):
            logo_url = reseller["logo_url"]

        branding_kwargs = {
            "brand_title": brand_title,
            "portal_title": portal_title,
            "portal_subtitle": portal_subtitle,
            "support_phone": support_phone,
            "support_username": support_username,
            "logo_url": logo_url,
            "favicon_url": favicon_url,
            "primary_color": primary_color,
            "footer_text": footer_text,
            "portal_layout": portal_layout,
            "portal_plan_style": portal_plan_style
        }

        # فقط در صورتی که فیلد دامنه در فرم ارسال شده باشد آن را پردازش کن
        if "custom_domain" in request.form:
            cd = request.form.get("custom_domain", "").strip().lower()
            branding_kwargs["custom_domain"] = cd if cd else None

        if "tutorial_domain" in request.form:
            td = request.form.get("tutorial_domain", "").strip().lower()
            branding_kwargs["tutorial_domain"] = td if td else None

        res = db.update_reseller_branding(reseller_id, **branding_kwargs)
        if res.get("success"):
            flash("تنظیمات هویت بصری و شخصی‌سازی شما با موفقیت ذخیره شد.", "success")
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

        # دریافت و اعمال حجم هدیه (Gift Traffic)
        gift_traffic = 0.0
        try:
            gift_traffic = max(0.0, float(request.form.get("gift_traffic_gb", 0) or 0))
        except (ValueError, TypeError):
            gift_traffic = 0.0

        if gift_traffic > 0:
            data_limit += gift_traffic
            plan_name += f" (+{gift_traffic}GB هدیه)"

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
        if gift_traffic > 0:
            h_comment += f" | +{gift_traffic}GB Gift"
        h_res = hidify_sync_create_user(name=account_name, usage_limit_gb=data_limit, package_days=duration, comment=h_comment)
        user_uuid = h_res.get("uuid", "")
        if not user_uuid:
            flash(f"خطا در ایجاد اکانت در سرور هیدیفای: {h_res.get('error')}", "danger")
            return redirect(url_for("admin_create_customer"))

        # تعیین وضعیت بدهی
        debt_amount_raw = request.form.get("debt_amount", "").strip()
        debt_notes = request.form.get("debt_notes", "").strip()
        if payment_method == "debtor":
            payment_status = "unpaid"
            debt_amount = int(debt_amount_raw) if debt_amount_raw.isdigit() else price
        else:
            payment_status = "paid"
            debt_amount = 0

        now = get_now_iso()
        debt_created = now if debt_amount > 0 else None

        # ذخیره در دیتابیس
        admin_creator = session.get("username") or "admin"
        sub_res = db.save_subscription(
            telegram_id=telegram_id or 0,
            hidify_uuid=user_uuid,
            plan_id=plan_id or "custom_admin",
            plan_name=plan_name,
            data_limit=data_limit,
            duration=duration,
            status="active",
            account_name=account_name,
            user_limit=user_limit,
            created_by=admin_creator
        )
        sub_id = sub_res.get("subscription_id") if isinstance(sub_res, dict) else sub_res

        # بروزرسانی شماره تماس، وضعیت پرداخت و بدهی در جدول subscriptions
        conn = db.get_connection()
        conn.execute("""
            UPDATE subscriptions 
            SET phone_number = ?, account_comment = ?, payment_status = ?, debt_amount = ?, debt_notes = ?, debt_created_at = ?, created_by = COALESCE(created_by, ?)
            WHERE id = ?
        """, (phone_number or None, comment or None, payment_status, debt_amount, debt_notes or None, debt_created, admin_creator, sub_id))
        conn.commit()
        conn.close()

        # ثبت سابقه دوره اولیه در تاریخچه
        db.save_subscription_history(
            subscription_id=sub_id,
            telegram_id=telegram_id or 0,
            hidify_uuid=user_uuid,
            account_name=account_name,
            plan_name=plan_name,
            previous_usage_gb=0,
            previous_limit_gb=data_limit,
            period_days=duration,
            renewal_type="new_subscription",
            plan_price=price,
            cost_paid=price if payment_method != "debtor" else 0,
            start_date=now
        )

        # ثبت کاربر در جدول users
        if telegram_id:
            db.save_user(telegram_id, account_name, None, None, 0, phone_number)
            if phone_number:
                db.set_user_phone(telegram_id, phone_number)

        # ثبت تراکنش و حسابداری بدهی نقدی مدیر
        debt_info_text = ""
        if payment_method == "debtor":
            debt_info_text = f" (مشتری بدهکار ثبت گردید: {debt_amount:,} تومان)"
            try:
                db.add_customer_debt_record(
                    subscription_id=sub_id,
                    account_name=account_name,
                    telegram_id=telegram_id or 0,
                    reseller_id=None,
                    action_type="create",
                    plan_name=plan_name,
                    amount=debt_amount,
                    notes=debt_notes or "ثبت بدهی هنگام ساخت اشتراک توسط مدیریت",
                    created_by=admin_creator,
                    previous_debt=0
                )
            except Exception as e_rec:
                logger.error(f"Error logging initial customer debt record: {e_rec}")
        elif payment_method == "wallet" and price > 0:
            order_id = f"WLT_{get_now_naive().strftime('%Y%m%d%H%M%S')}_{random.randint(100, 999)}"
            db.save_transaction(
                order_id=order_id,
                user_id=telegram_id or 0,
                username=account_name,
                plan_name=plan_name,
                amount=price,
                gateway="wallet",
                tracking_code=f"WALLET_{telegram_id}",
                status="approved",
                account_name=account_name,
                source="admin"
            )
            try:
                db.add_accounting_record(
                    type="income",
                    category="فروش اشتراک",
                    title=f"خرید از کیف پول {account_name} ({plan_name})",
                    amount=price,
                    source="wallet",
                    ref_type="subscription",
                    ref_id=str(sub_id),
                    description=f"کسر از کیف پول کاربر {telegram_id}",
                    date=now[:10]
                )
            except Exception as e_acc:
                logger.error(f"Error recording accounting record for wallet sale: {e_acc}")
        elif payment_method == "cash" and price > 0:
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
                account_name=account_name,
                source="admin"
            )
            try:
                db.add_accounting_record(
                    type="income",
                    category="فروش اشتراک",
                    title=f"فروش نقدی {account_name} ({plan_name})",
                    amount=price,
                    source="admin_panel",
                    ref_type="subscription",
                    ref_id=str(sub_id),
                    description=f"ثبت نقدی مشتری توسط {session.get('username') or 'admin'}",
                    date=now[:10]
                )
            except Exception as e_acc:
                logger.error(f"Error recording accounting record for cash sale: {e_acc}")

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
        single_link_template = get_single_link_template(db)
        single_url = format_single_link(single_link_template, uuid=user_uuid, name=account_name) if user_uuid else ""

        if telegram_id and sub_url:
            send_subscription_card_sync(
                telegram_id,
                sub_url,
                "🎉 **اشتراک جدید شما آماده شد!**",
                f"📋 پلن: **{plan_name}**\n📊 حجم: **{data_limit} گیگابایت**\n⏰ مدت: **{duration} روز**"
            )

        # ثبت رویداد در سامانه لاگ و حسابرسی
        try:
            db.add_system_log(
                category="admin",
                action="create",
                title=f"ایجاد اشتراک جدید «{account_name}»",
                description=f"اشتراک «{account_name}» با بسته {plan_name} ({data_limit} گیگابایت / {duration} روز) توسط مدیر ({admin_creator}) ایجاد گردید.{debt_info_text}",
                actor_type="admin",
                actor_name=admin_creator,
                target_type="subscription",
                target_id=sub_id,
                target_name=account_name,
                details={
                    "plan_name": plan_name,
                    "data_limit": data_limit,
                    "duration": duration,
                    "price": price,
                    "payment_method": payment_method,
                    "hidify_uuid": user_uuid,
                    "telegram_id": telegram_id
                },
                level="success",
                ip_address=request.remote_addr
            )
        except Exception:
            pass

        flash(f"✅ اشتراک «{account_name}» با موفقیت ایجاد شد!{debt_info_text}", "success")
        return render_template(
            "admin_customer_created.html",
            sub_id=sub_id,
            sub_url=sub_url,
            single_url=single_url,
            account_name=account_name,
            plan_name=plan_name,
            data_limit=data_limit,
            duration=duration,
            user_uuid=user_uuid,
            debt_info=debt_info_text
        )

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
        return redirect(get_redirect_target("admin_managers"))

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
    return redirect(get_redirect_target("admin_managers"))


@app.route("/admin/manager/<int:admin_id>/toggle")
@super_admin_required
def admin_manager_toggle(admin_id):
    """تغییر وضعیت فعال/غیرفعال مدیر"""
    if admin_id == session.get("admin_id"):
        flash("شما نمی‌توانید حساب کاربری خودتان را غیرفعال کنید!", "warning")
        return redirect(get_redirect_target("admin_managers"))

    res = db.toggle_admin_user(admin_id)
    if res.get("success"):
        flash("وضعیت مدیر با موفقیت تغییر یافت.", "info")
    else:
        flash(f"خطا: {res.get('error')}", "danger")
    return redirect(get_redirect_target("admin_managers"))


@app.route("/admin/manager/<int:admin_id>/delete")
@super_admin_required
def admin_manager_delete(admin_id):
    """حذف مدیر"""
    if admin_id == session.get("admin_id"):
        flash("شما نمی‌توانید حساب کاربری خودتان را حذف کنید!", "danger")
        return redirect(get_redirect_target("admin_managers"))

    res = db.delete_admin_user(admin_id)
    if res.get("success"):
        flash("حساب مدیر با موفقیت حذف شد.", "warning")
    else:
        flash(f"خطا در حذف مدیر: {res.get('error')}", "danger")
    return redirect(get_redirect_target("admin_managers"))


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
    usage_summary = db.get_reseller_usage_summary(reseller_id)
    is_main_reseller = (session.get("role") == "reseller" and not session.get("sub_role"))
    return render_template(
        "reseller_profile.html",
        reseller=reseller,
        login_history=login_history,
        current_token=current_token,
        usage_summary=usage_summary,
        is_main_reseller=is_main_reseller
    )


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
    """نمایش فاکتور رسمی دیجیتال با امکان چاپ، بارکد QR، تاریخ‌های شمسی و اطلاعات کامل سرویس اینترنت پرو"""
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
                "brand_title": reseller.get("brand_title") or reseller.get("name") or "خدمات اینترنت پرو",
                "logo_url": reseller.get("logo_url"),
                "footer_text": reseller.get("footer_text") or "کلیه حقوق برای سامانه محفوظ است.",
                "primary_color": reseller.get("primary_color") or "#4f46e5"
            }
    if not branding:
        branding = {
            "brand_title": db.get_setting("brand_title") or "سامانه هوشمند اینترنت پرو",
            "logo_url": db.get_setting("logo_url") or "",
            "footer_text": "ارائه‌دهنده راهکارهای ارتباطی و شبکه پرسرعت اینترنت پرو",
            "primary_color": "#4f46e5"
        }

    h_url = get_hiddify_url()
    u_proxy = get_user_proxy()
    user_uuid = sub.get("hidify_uuid") or ""
    sub_url = f"{h_url}/{u_proxy}/{user_uuid}/" if (user_uuid and h_url) else (sub.get("sub_url") or "")

    single_link_template = get_single_link_template(db)
    single_url = format_single_link(single_link_template, uuid=user_uuid, name=sub.get("account_name") or "") if user_uuid else ""

    # فرمت تاریخ‌های شمسی
    shamsi_created = filter_shamsi_date(sub.get("created_at") or "")
    shamsi_start = filter_shamsi_date(sub.get("start_date") or "") if sub.get("start_date") else "پس از اولین اتصال"
    shamsi_expire = filter_shamsi_date(sub.get("expire_date") or "") if sub.get("expire_date") else "بر اساس مدت اعتبار"

    is_credit = bool(sub.get("is_credit") or sub.get("payment_status") in ("unpaid", "debtor") or (sub.get("debt_amount") or 0) > 0)

    return render_template(
        "invoice.html",
        sub=sub,
        branding=branding,
        sub_url=sub_url,
        single_url=single_url,
        shamsi_created=shamsi_created,
        shamsi_start=shamsi_start,
        shamsi_expire=shamsi_expire,
        is_credit=is_credit
    )


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
    """پردازش بازگشت از درگاه پرداخت آنلاین شاپرک (زرین‌پال / آیدی‌پی / بلوپال)"""
    authority = request.args.get("Authority") or request.form.get("Authority")
    status = request.args.get("Status") or request.form.get("Status")
    idpay_id = request.args.get("id") or request.form.get("id")
    idpay_status = request.args.get("status") or request.form.get("status")

    trans = db.get_transaction_by_order_id(order_id)
    if not trans:
        return render_template("payment_result.html", success=False, message="تراکنش یافت نشد.")

    # اگر از قبل تایید شده باشد
    if trans.get("status") == "approved":
        return render_template("payment_result.html", success=True, order_id=order_id, amount=trans.get("amount", 0), ref_id=trans.get("ref_id"), plan_name=trans.get("plan_name", ""))

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
    elif gw_type == "blupal" or str(trans.get("gateway", "")).startswith("blupal"):
        # بررسی وضعیت فاکتور در بلوپال
        invoice_id = trans.get("tracking_code")
        if invoice_id and str(invoice_id).isdigit():
            from payment import BluPal
            bp = BluPal(api_key=gw_key, sandbox=sandbox)
            res = bp.check_invoice(int(invoice_id))
            if res.get("success") and res.get("is_paid"):
                verified = True
                ref_id = f"کارت: {res.get('payer_card', '')} | فاکتور: {invoice_id}"

    portal_token = request.args.get("token")
    if not portal_token and trans.get("renew_sub_id"):
        sub_info = db.get_subscription(trans.get("renew_sub_id"))
        if sub_info:
            portal_token = sub_info.get("hidify_uuid") or str(sub_info.get("id"))
    portal_url = url_for("customer_portal", token=portal_token) if portal_token else None

    if verified:
        fulfill_approved_transaction(order_id, ref_id=str(ref_id or authority or idpay_id), processed_by=f"درگاه {gw_type}")
        return render_template("payment_result.html", success=True, order_id=order_id, amount=amount, ref_id=ref_id, plan_name=plan_name, portal_url=portal_url)
    else:
        db.update_transaction(order_id, status="failed")
        return render_template("payment_result.html", success=False, order_id=order_id, amount=amount, message="پرداخت ناموفق بود یا توسط کاربر لغو گردید.", portal_url=portal_url)


# ═══════════════════════════════════════════════════════════════════════
# مسیرهای اختصاصی وب‌هوک و کال‌بک درگاه کارت به کارت هوشمند بلوپال (BluPal)
# ═══════════════════════════════════════════════════════════════════════

@app.route("/payment/blupal/webhook", methods=["POST"])
@app.route("/api/blupal/webhook", methods=["POST"])
def blupal_webhook():
    """
    دریافت اعلان خودکار وب‌هوک پرداخت موفق از سرورهای بلوپال (BluPal Webhook)
    مستندات: https://blupal.net/documentation
    فرمت: { "success": true, "event": "payment.completed", "invoice_id": 123, "status": "PAID", ... }
    """
    payload = request.get_json(silent=True) or {}
    logger.info(f"Received BluPal webhook notification: {payload}")

    if not payload:
        return jsonify({"error": "Empty payload"}), 400

    event = payload.get("event")
    status = payload.get("status")
    invoice_id = payload.get("invoice_id")

    if event != "payment.completed" or status != "PAID" or not invoice_id:
        return jsonify({"error": "Invalid payload or unhandled event"}), 400

    # یافتن تراکنش بر اساس شماره فاکتور بلوپال (tracking_code)
    tx = db.get_transaction_by_tracking_code(str(invoice_id))
    if not tx:
        logger.warning(f"BluPal Webhook: No transaction found for invoice_id={invoice_id}")
        # طبق مستندات سرور باید پاسخ HTTP 200 بدهد تا ارسال مکرر متوقف شود
        return jsonify({"received": True, "warning": "Invoice not found"}), 200

    order_id = tx.get("order_id")
    payer_name = payload.get("payer_name") or ""
    payer_card = payload.get("payer_card") or ""
    payer_bank = payload.get("payer_bank_name") or ""
    mode = payload.get("mode", "live")
    ref_info = f"کارت: {payer_card} | نام: {payer_name} | بانک: {payer_bank} | فاکتور: {invoice_id} ({mode})"

    # فعال‌سازی و تایید خودکار و امن سفارش
    fulfill_res = fulfill_approved_transaction(
        order_id=order_id,
        ref_id=ref_info,
        payer_info=payload,
        processed_by="وب‌هوک بلوپال (BluPal)"
    )

    logger.info(f"BluPal Webhook processed for order {order_id}: {fulfill_res}")
    return jsonify({"received": True}), 200


@app.route("/payment/blupal/callback/<order_id>", methods=["GET", "POST"])
@app.route("/payment/blupal/callback", methods=["GET", "POST"])
def blupal_callback(order_id: str = None):
    """
    صفحه بازگشت کاربر پس از پرداخت در درگاه کارت به کارت هوشمند بلوپال
    """
    if not order_id:
        order_id = request.args.get("order_id") or request.form.get("order_id")
        inv_param = request.args.get("invoice_id") or request.args.get("id")
        if not order_id and inv_param:
            tx_by_inv = db.get_transaction_by_tracking_code(str(inv_param))
            if tx_by_inv:
                order_id = tx_by_inv.get("order_id")

    if not order_id:
        return render_template("payment_result.html", success=False, message="شناسه سفارش نامعتبر است.")

    tx = db.get_transaction_by_order_id(order_id)
    if not tx:
        return render_template("payment_result.html", success=False, message="تراکنش یافت نشد.")

    amount = tx.get("amount", 0)
    plan_name = tx.get("plan_name", "")
    invoice_id = tx.get("tracking_code")
    reseller_id = tx.get("reseller_id")

    # اگر قبلاً با وب‌هوک یا تایید قبلی انجام شده باشد
    if tx.get("status") == "approved":
        return render_template(
            "payment_result.html",
            success=True,
            order_id=order_id,
            amount=amount,
            plan_name=plan_name,
            ref_id=tx.get("ref_id")
        )

    # در غیر این صورت، استعلام زنده از API بلوپال جهت اطمینان
    if reseller_id:
        gw_cfg = db.get_reseller_gateway(reseller_id)
    else:
        gw_cfg = db.get_admin_gateway()

    gw_key = gw_cfg.get("key", "")
    sandbox = gw_cfg.get("sandbox", False)

    if gw_key and invoice_id and str(invoice_id).isdigit():
        from payment import BluPal
        bp = BluPal(api_key=gw_key, sandbox=sandbox)
        try:
            check_res = bp.check_invoice(int(invoice_id))
            if check_res.get("success") and check_res.get("is_paid"):
                payer_card = check_res.get("payer_card") or ""
                payer_name = check_res.get("payer_name") or ""
                ref_info = f"کارت: {payer_card} | نام: {payer_name} | فاکتور: {invoice_id}"
                fulfill_approved_transaction(
                    order_id=order_id,
                    ref_id=ref_info,
                    payer_info=check_res,
                    processed_by="استعلام بازگشت بلوپال"
                )
                return render_template(
                    "payment_result.html",
                    success=True,
                    order_id=order_id,
                    amount=amount,
                    plan_name=plan_name,
                    ref_id=ref_info
                )
            elif check_res.get("status") == "PENDING":
                return render_template(
                    "payment_result.html",
                    success=False,
                    order_id=order_id,
                    amount=amount,
                    plan_name=plan_name,
                    message="فاکتور شما در وضعیت در انتظار واریز قرار دارد. به محض واریز کارت به کارت، اشتراک شما به صورت خودکار فعال خواهد شد."
                )
        except Exception as e:
            logger.error(f"Error checking invoice in blupal_callback: {e}")

    return render_template(
        "payment_result.html",
        success=False,
        order_id=order_id,
        amount=amount,
        plan_name=plan_name,
        message="پرداخت هنوز تایید نشده است یا مهلت فاکتور به پایان رسیده است."
    )


# ═══════════════════════════════════════════════════════════════════════
# سیستم زیرمجموعه‌گیری و پورسانت نمایندگان (Reseller Affiliate System)
# ═══════════════════════════════════════════════════════════════════════

@app.route("/admin/reseller-affiliates", methods=["GET"])
@admin_required
def admin_reseller_affiliates():
    """صفحه مدیریت جامع زیرمجموعه‌گیری و پورسانت‌های نمایندگان در پنل مدیریت"""
    overview = db.get_admin_reseller_affiliates_overview()
    commissions = db.get_reseller_affiliate_commissions_history(limit=150)
    all_tickets = db.get_all_tickets(category="resellers")
    applications = [t for t in all_tickets if t.get("ticket_type") == "reseller_application"]
    
    return render_template(
        "admin_reseller_affiliates.html",
        overview=overview,
        commissions=commissions,
        applications=applications
    )


@app.route("/admin/reseller-affiliates/update-settings", methods=["POST"])
@admin_required
def admin_reseller_affiliates_update_settings():
    """بروزرسانی تنظیمات سراسری سیستم زیرمجموعه‌گیری همکاران"""
    enabled = bool(request.form.get("enabled"))
    try:
        default_percent = float(request.form.get("default_percent", 10.0))
    except (ValueError, TypeError):
        default_percent = 10.0
    calc_base = request.form.get("calc_base", "plan_price").strip()
    terms = request.form.get("terms", "").strip()

    res = db.update_reseller_affiliate_settings(enabled, default_percent, calc_base, terms)
    if res.get("success"):
        flash("تنظیمات سیستم زیرمجموعه‌گیری با موفقیت ذخیره شد.", "success")
    else:
        flash(f"خطا در ذخیره تنظیمات: {res.get('error')}", "danger")
    return redirect(url_for("admin_reseller_affiliates"))


@app.route("/admin/reseller-affiliates/set-parent", methods=["POST"])
@admin_required
def admin_reseller_affiliates_set_parent():
    """تغییر یا انتساب نماینده بالادستی (معرف)"""
    reseller_id = int(request.form.get("reseller_id", 0))
    parent_id_raw = request.form.get("parent_reseller_id", "").strip()
    parent_id = int(parent_id_raw) if parent_id_raw.isdigit() and int(parent_id_raw) > 0 else None

    res = db.update_reseller_parent(reseller_id, parent_id)
    if res.get("success"):
        flash("نماینده بالادستی با موفقیت بروزرسانی شد.", "success")
    else:
        flash(f"خطا در انتساب بالادستی: {res.get('error')}", "danger")
    return redirect(url_for("admin_reseller_affiliates"))


@app.route("/admin/reseller-affiliates/set-commission", methods=["POST"])
@admin_required
def admin_reseller_affiliates_set_commission():
    """تنظیم درصد پورسانت اختصاصی برای یک نماینده"""
    reseller_id = int(request.form.get("reseller_id", 0))
    custom_percent_raw = request.form.get("custom_percent", "").strip()
    custom_percent = float(custom_percent_raw) if custom_percent_raw else None

    res = db.update_reseller_custom_commission(reseller_id, custom_percent)
    if res.get("success"):
        flash("درصد پورسانت اختصاصی نماینده با موفقیت ذخیره شد.", "success")
    else:
        flash(f"خطا در تغییر درصد پورسانت: {res.get('error')}", "danger")
    return redirect(url_for("admin_reseller_affiliates"))


@app.route("/admin/reseller-application/<int:ticket_id>/approve", methods=["POST"])
@admin_required
def admin_reseller_application_approve(ticket_id):
    """تایید درخواست اخذ نمایندگی و ساخت آنی حساب"""
    password = request.form.get("password", "").strip() or None
    discount_percent = int(request.form.get("discount_percent", 20))
    initial_balance = int(request.form.get("initial_balance", 0))
    custom_commission_raw = request.form.get("custom_commission", "").strip()
    custom_commission = float(custom_commission_raw) if custom_commission_raw else None

    res = db.approve_reseller_application(
        ticket_id=ticket_id,
        password=password,
        initial_balance=initial_balance,
        discount_percent=discount_percent,
        custom_commission=custom_commission
    )
    if res.get("success"):
        flash(f"حساب نمایندگی با نام کاربری «{res['username']}» با موفقیت ایجاد و به معرف متصل گردید. رمز عبور: {res['password']}", "success")
    else:
        flash(f"خطا در تایید درخواست: {res.get('error')}", "danger")
    return redirect(request.referrer or url_for("admin_reseller_affiliates"))


@app.route("/admin/reseller-application/<int:ticket_id>/reject", methods=["POST"])
@admin_required
def admin_reseller_application_reject(ticket_id):
    """رد درخواست اخذ نمایندگی"""
    reason = request.form.get("reason", "").strip()
    res = db.reject_reseller_application(ticket_id, reason=reason)
    if res.get("success"):
        flash("درخواست نمایندگی با موفقیت رد شد.", "info")
    else:
        flash(f"خطا در رد درخواست: {res.get('error')}", "danger")
    return redirect(request.referrer or url_for("admin_reseller_affiliates"))


# ═══════════════════════════════════════════════════════════════════════
# بخش مدیریت بسته‌های پیش‌خرید همکاران و نمایندگان (Reseller Bundles - Admin)
# ═══════════════════════════════════════════════════════════════════════

@app.route("/admin/reseller-bundles", methods=["GET", "POST"])
@admin_required
def admin_reseller_bundles():
    """مدیریت بسته‌های پیش‌خرید اعتباری با بونوس شارژ هدیه برای همکاران و نمایندگان"""
    if request.method == "POST":
        action = request.form.get("action", "").strip()
        
        if action in ("create", "edit"):
            bundle_id = request.form.get("bundle_id", "").strip()
            title = request.form.get("title", "").strip()
            price_raw = request.form.get("price", "0").replace(",", "").strip()
            credit_raw = request.form.get("credit", "0").replace(",", "").strip()
            bonus_percent_raw = request.form.get("bonus_percent", "0").strip()
            badge = request.form.get("badge", "").strip()
            color = request.form.get("color", "primary").strip()
            description = request.form.get("description", "").strip()
            display_order_raw = request.form.get("display_order", "0").strip()
            is_active = request.form.get("is_active") in ("on", "1", "true", True)

            try:
                price = int(price_raw)
            except ValueError:
                price = 0

            try:
                credit = int(credit_raw)
            except ValueError:
                credit = 0

            try:
                bonus_percent = int(bonus_percent_raw)
            except ValueError:
                bonus_percent = 0

            try:
                display_order = int(display_order_raw)
            except ValueError:
                display_order = 0

            if not bundle_id and action == "create":
                import time
                bundle_id = f"bundle_{int(time.time())}"

            if not bundle_id or not title or price <= 0:
                flash("خطا: شناسه بسته، عنوان و قیمت معتبر الزامی هستند.", "danger")
                return redirect(url_for("admin_reseller_bundles"))

            # اگر کردیت داده نشده بود، بر مبنای بونوس درصد حساب شود
            if credit <= 0:
                credit = price + int(price * bonus_percent / 100)

            # اگر درصد صفر بود ولی کردیت بیشتر از قیمت بود، درصد را حساب کنیم
            if bonus_percent <= 0 and price > 0 and credit > price:
                bonus_percent = round(((credit - price) / price) * 100)

            if not badge:
                badge = f"{bonus_percent}٪ شارژ هدیه" if bonus_percent > 0 else "شارژ کیف پول"

            bundle_data = {
                "id": bundle_id,
                "title": title,
                "price": price,
                "credit": credit,
                "bonus_percent": bonus_percent,
                "badge": badge,
                "color": color,
                "description": description,
                "display_order": display_order,
                "is_active": is_active
            }

            res = db.save_reseller_credit_bundle(bundle_data)
            if res.get("success"):
                op_title = "ایجاد" if action == "create" else "ویرایش"
                flash(f"بسته «{title}» با موفقیت {op_title} شد.", "success")
            else:
                flash(f"خطا در ذخیره بسته: {res.get('error')}", "danger")
            return redirect(url_for("admin_reseller_bundles"))

        elif action == "toggle":
            bundle_id = request.form.get("bundle_id", "").strip()
            res = db.toggle_reseller_credit_bundle(bundle_id)
            if res.get("success"):
                state_text = "فعال" if res.get("is_active") else "غیرفعال"
                flash(f"وضعیت بسته با موفقیت به «{state_text}» تغییر یافت.", "info")
            else:
                flash(f"خطا در تغییر وضعیت بسته: {res.get('error')}", "danger")
            return redirect(url_for("admin_reseller_bundles"))

        elif action == "delete":
            bundle_id = request.form.get("bundle_id", "").strip()
            res = db.delete_reseller_credit_bundle(bundle_id)
            if res.get("success"):
                flash("بسته پیش‌خرید با موفقیت حذف شد.", "success")
            else:
                flash(f"خطا در حذف بسته: {res.get('error')}", "danger")
            return redirect(url_for("admin_reseller_bundles"))

        elif action == "reset_defaults":
            res = db.reset_default_reseller_credit_bundles()
            if res.get("success"):
                flash("بسته‌های پیش‌خرید همکاران به ۴ بسته استاندارد سیستم بازنشانی شد.", "info")
            else:
                flash(f"خطا در بازنشانی بسته‌ها: {res.get('error')}", "danger")
            return redirect(url_for("admin_reseller_bundles"))

    bundles = db.get_reseller_credit_bundles(active_only=False)
    total_bundles = len(bundles)
    active_bundles = sum(1 for b in bundles if b.get("is_active", 1))
    max_bonus = max([b.get("bonus_percent", 0) for b in bundles] or [0])
    avg_bonus = round(sum(b.get("bonus_percent", 0) for b in bundles) / max(total_bundles, 1), 1)

    return render_template(
        "admin_reseller_bundles.html",
        bundles=bundles,
        total_bundles=total_bundles,
        active_bundles=active_bundles,
        max_bonus=max_bonus,
        avg_bonus=avg_bonus
    )


@app.route("/reseller/affiliates", methods=["GET"])
@reseller_required
def reseller_affiliates():
    """صفحه زیرمجموعه‌گیری و کسب درآمد پورسانت در پنل نماینده"""
    reseller_id = session.get("reseller_id")
    stats = db.get_reseller_affiliate_stats(reseller_id)
    sub_resellers = db.get_sub_resellers(reseller_id)
    commissions = db.get_reseller_affiliate_commissions_history(reseller_id=reseller_id, limit=100)
    
    # تولید لینک دعوت اختصاصی
    base_url = request.host_url.rstrip("/")
    ref_code = stats.get("referral_code", f"REF-{reseller_id}")
    invite_link = f"{base_url}/reseller/apply?ref={ref_code}"

    return render_template(
        "reseller_affiliates.html",
        stats=stats,
        sub_resellers=sub_resellers,
        commissions=commissions,
        invite_link=invite_link
    )


@app.route("/reseller/apply", methods=["GET", "POST"])
@app.route("/apply-reseller", methods=["GET", "POST"])
def reseller_apply():
    """صفحه و فرم عمومی ثبت درخواست نمایندگی با لینک معرف"""
    ref_code = request.args.get("ref", "").strip() or request.form.get("ref_code", "").strip()
    referrer = db.get_reseller_by_referral_code(ref_code) if ref_code else None
    aff_settings = db.get_reseller_affiliate_settings()

    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        phone_number = request.form.get("phone_number", "").strip()
        telegram_id_raw = request.form.get("telegram_id", "").strip()
        requested_username = request.form.get("requested_username", "").strip()
        notes = request.form.get("notes", "").strip()

        if not full_name or not phone_number or not requested_username:
            flash("لطفاً تمامی فیلدهای الزامی را تکمیل نمایید.", "danger")
            return render_template("reseller_apply.html", referrer=referrer, ref_code=ref_code, aff_settings=aff_settings)

        telegram_id = int(telegram_id_raw) if telegram_id_raw.isdigit() else None
        referrer_id = referrer["id"] if referrer else None

        res = db.create_reseller_application(
            referrer_id=referrer_id,
            full_name=full_name,
            phone_number=phone_number,
            telegram_id=telegram_id,
            requested_username=requested_username,
            notes=notes
        )

        if res.get("success"):
            return render_template(
                "reseller_apply.html",
                submitted=True,
                full_name=full_name,
                requested_username=requested_username,
                ticket_id=res.get("ticket_id"),
                referrer=referrer,
                aff_settings=aff_settings
            )
        else:
            flash(f"خطا در ثبت درخواست: {res.get('error')}", "danger")

    return render_template(
        "reseller_apply.html",
        referrer=referrer,
        ref_code=ref_code,
        aff_settings=aff_settings,
        submitted=False
    )


# ═══════════════════════════════════════════════════════════════════════
# مسیر اختصاصی وب‌هوک دریافت پیامک‌های بانک (Smart Bank SMS Webhook)
# ═══════════════════════════════════════════════════════════════════════

@app.route("/api/bank-sms/webhook", methods=["GET", "POST"])
def bank_sms_webhook():
    """
    دریافت اعلان خودکار پیامک بانک از اپلیکیشن فورواردر گوشی (SMS Forwarder / MacroDroid)
    پشتیبانی از توکن اختصاصی برای ادمین و نمایندگان
    """
    token = request.args.get("token") or request.headers.get("X-Bank-SMS-Token") or request.headers.get("Authorization")
    if token and str(token).startswith("Bearer "):
        token = str(token)[7:].strip()

    # خواندن از JSON یا فرم
    payload = request.get_json(silent=True) or {}
    if not token and payload:
        token = payload.get("token")
    if not token and request.form:
        token = request.form.get("token")

    if not token:
        return jsonify({"error": "Unauthorized: Missing webhook token"}), 401

    owner = db.find_bank_sms_owner_by_token(token)
    if not owner:
        return jsonify({"error": "Unauthorized: Invalid webhook token"}), 403

    owner_type = owner["type"]
    owner_id = owner["id"]

    if request.method == "GET":
        return jsonify({
            "status": "ok",
            "message": "Bank SMS Webhook is active and connected.",
            "owner": owner
        })

    # استخراج متن و فرستنده پیامک
    raw_message = (
        payload.get("message") or payload.get("text") or payload.get("sms") or 
        payload.get("content") or payload.get("body") or request.form.get("message") or 
        request.form.get("text") or request.form.get("sms") or ""
    )
    sender = (
        payload.get("sender") or payload.get("from") or payload.get("phone") or 
        request.form.get("sender") or request.form.get("from") or ""
    )

    if not raw_message:
        return jsonify({"error": "Empty message body"}), 400

    logger.info(f"Received Bank SMS for {owner_type} #{owner_id} from {sender}: {raw_message}")

    from bank_sms_parser import parse_bank_sms
    parsed = parse_bank_sms(raw_message, sender=sender)

    if not parsed or not parsed.get("is_deposit"):
        db.log_bank_sms(
            owner_type=owner_type,
            owner_id=owner_id,
            sender_number=sender,
            raw_message=raw_message,
            status="ignored"
        )
        return jsonify({"status": "ignored", "reason": "Not a deposit SMS"}), 200

    amount_toman = parsed.get("amount_toman")
    if not amount_toman or amount_toman <= 0:
        db.log_bank_sms(
            owner_type=owner_type,
            owner_id=owner_id,
            sender_number=sender,
            raw_message=raw_message,
            status="unmatched"
        )
        return jsonify({"status": "unmatched", "reason": "Could not extract deposit amount"}), 200

    # تطبیق با فاکتورهای معلق باز
    matched_invoice = db.match_smart_invoice_by_amount(amount_toman, owner_type=owner_type, owner_id=owner_id)

    if not matched_invoice:
        db.log_bank_sms(
            owner_type=owner_type,
            owner_id=owner_id,
            sender_number=sender,
            raw_message=raw_message,
            extracted_amount=amount_toman,
            status="unmatched"
        )
        return jsonify({
            "status": "unmatched",
            "amount_toman": amount_toman,
            "bank": parsed.get("bank_name"),
            "message": "No pending invoice matched this amount"
        }), 200

    order_id = matched_invoice["order_id"]
    sub_id = matched_invoice.get("sub_id")
    tracking = parsed.get("tracking_code") or f"SMS-{int(get_now_naive().timestamp())}"

    # ثبت پرداخت فاکتور هوشمند
    db.mark_smart_invoice_paid(order_id, tracking_code=tracking)

    # ثبت لاگ موفقیت‌آمیز
    db.log_bank_sms(
        owner_type=owner_type,
        owner_id=owner_id,
        sender_number=sender,
        raw_message=raw_message,
        extracted_amount=amount_toman,
        matched_order_id=order_id,
        status="matched"
    )

    # تحویل و تمدید خودکار اشتراک
    processed_by = f"پیامک بانک ({parsed.get('bank_name', 'شتاب')})"
    fulfill_res = fulfill_approved_transaction(order_id, ref_id=tracking, processed_by=processed_by)
    logger.info(f"Smart Invoice {order_id} fulfilled via Bank SMS: {fulfill_res}")

    # ارسال پیامک تایید به مشتری (در صورت وجود شماره)
    try:
        if sub_id:
            sub = db.get_subscription(sub_id)
            if sub and sub.get("phone_number"):
                from sms_service import send_sms
                sms_body = f"کاربر گرامی، پرداخت {amount_toman:,} تومانی شما تایید و اشتراک «{sub.get('account_name')}» تمدید شد."
                send_sms(sub["phone_number"], sms_body, db_instance=db)
    except Exception as e_sms:
        logger.warning(f"Failed to send confirmation SMS to customer: {e_sms}")

    return jsonify({
        "status": "success",
        "matched_order_id": order_id,
        "amount_toman": amount_toman,
        "bank": parsed.get("bank_name"),
        "tracking_code": tracking,
        "fulfill": fulfill_res
    }), 200


# ═══════════════════════════════════════════════════════════════════════
# مسیرهای پورتال دائمی و صفحه تمدید اختصاصی مشتریان
# ═══════════════════════════════════════════════════════════════════════

def get_customer_portal_server_status() -> dict:
    """دریافت وضعیت نمایشی سرورها برای پورتال مشتری بر اساس تنظیمات هوشمند یا دستی پنل مدیریت"""
    mode = db.get_setting("server_status_mode", "smart")  # "smart" or "manual"
    custom_text = db.get_setting("server_status_custom_text", "").strip()

    if mode == "manual":
        state = db.get_setting("server_status_manual_state", "operational")
        if state == "operational":
            return {
                "mode": "manual",
                "state": "operational",
                "status_title": "متصل و عملیاتی",
                "color_name": "success",
                "color_code": "#10b981",
                "bg_class": "bg-success",
                "icon": "fa-check",
                "show_ping": False,
                "latency": 0,
                "custom_text": custom_text
            }
        elif state == "disruption":
            return {
                "mode": "manual",
                "state": "disruption",
                "status_title": "اختلال در سرورها",
                "color_name": "warning",
                "color_code": "#f59e0b",
                "bg_class": "bg-warning",
                "icon": "fa-triangle-exclamation",
                "show_ping": False,
                "latency": 0,
                "custom_text": custom_text
            }
        else:  # disconnected
            return {
                "mode": "manual",
                "state": "disconnected",
                "status_title": "سرورها قطع میباشند",
                "color_name": "danger",
                "color_code": "#ef4444",
                "bg_class": "bg-danger",
                "icon": "fa-xmark",
                "show_ping": False,
                "latency": 0,
                "custom_text": custom_text
            }
    else:
        # حالت هوشمند: تست زنده سرور هیدیفای
        health = hidify_sync_ping()
        if health.get("online"):
            lat = int(health.get("latency") or 0)
            # نکته درخواستی: اگر پینگ سرور بالاتر از ۱۸۰ بود پینگ نمایش داده نشود
            show_ping = (lat > 0 and lat <= 180)
            return {
                "mode": "smart",
                "state": "operational",
                "status_title": "متصل و عملیاتی",
                "color_name": "success",
                "color_code": "#10b981",
                "bg_class": "bg-success",
                "icon": "fa-check",
                "show_ping": show_ping,
                "latency": lat,
                "custom_text": custom_text
            }
        else:
            return {
                "mode": "smart",
                "state": "disconnected",
                "status_title": "سرورها قطع میباشند",
                "color_name": "danger",
                "color_code": "#ef4444",
                "bg_class": "bg-danger",
                "icon": "fa-xmark",
                "show_ping": False,
                "latency": 0,
                "custom_text": custom_text
            }


@app.route("/api/server-status", methods=["GET"])
def api_server_status():
    """استعلام وضعیت سرور برای پورتال مشتریان"""
    return jsonify(get_customer_portal_server_status())


@app.route("/renew/check-discount/<token>", methods=["POST"])
def customer_check_discount(token: str):
    """بررسی و اعتبارسنجی بلادرنگ کد تخفیف برای مشتری با تفکیک کامل نماینده و مدیریت"""
    conn = db.get_connection()
    sub_row = conn.execute("SELECT * FROM subscriptions WHERE hidify_uuid=? OR id=?", (token, token)).fetchone()
    conn.close()

    if not sub_row:
        return jsonify({"valid": False, "error": "اشتراک یافت نشد"}), 404

    sub = dict(sub_row)
    data = request.get_json(silent=True) or request.form
    code = (data.get("code") or "").strip().upper()
    plan_id = str(data.get("plan_id") or "").strip()

    if not code:
        return jsonify({"valid": False, "error": "لطفاً کد تخفیف را وارد کنید."})

    reseller_id = sub.get("reseller_id") or 0
    price = 0
    if reseller_id:
        r_plan = db.get_reseller_plan(reseller_id, plan_id)
        if r_plan:
            price = r_plan.get("custom_price") or r_plan.get("price") or 0
    if not price:
        g_plan = get_plans_dict().get(plan_id)
        if g_plan:
            price = g_plan.get("price", 0)

    if not price:
        if reseller_id:
            raw_plans = db.get_reseller_active_plans(reseller_id)
            if raw_plans:
                price = raw_plans[0].get("custom_price") or raw_plans[0].get("price") or 0
        if not price:
            all_p = get_plans_dict()
            if all_p:
                price = next(iter(all_p.values())).get("price", 100000)
            else:
                price = 100000

    res = db.validate_customer_discount(sub, code, price)
    if res.get("valid"):
        return jsonify({
            "valid": True,
            "discount_code": res["discount_code"],
            "discount_amount": res["discount_amount"],
            "original_amount": price,
            "final_amount": res["final_amount"],
            "message": f"کد تخفیف اعمال شد: {res['discount_amount']:,} تومان تخفیف"
        })
    else:
        return jsonify({
            "valid": False,
            "error": res.get("error", "این کد تخفیف برای شما معتبر نمی‌باشد.")
        })


def get_portal_payment_methods(sub: dict) -> list:
    """
    دریافت لیست و اولویت روش‌های پرداخت فعال اختصاصی برای مشتری این اشتراک
    با تفکیک و ایزولاسیون کامل بین نماینده و مدیریت اصلی.
    هر روشی که غیرفعال باشد هرگز نمایش داده نمی‌شود.
    """
    reseller_id = sub.get("reseller_id") or 0
    ordered_methods = db.get_payment_methods(reseller_id=reseller_id if reseller_id else None)

    # دریافت اطلاعات پرداخت اختصاصی مالک اشتراک
    if reseller_id:
        r_cards = db.get_reseller_cards(reseller_id)
        active_cards = [c for c in r_cards if c.get("is_active")]
        if not active_cards:
            adm_cards = db.get_all_bank_cards()
            active_cards = [c for c in adm_cards if c.get("is_active")]
        gw_cfg = db.get_reseller_gateway(reseller_id)
        crypto_cfg = db.get_reseller_crypto_config(reseller_id)
    else:
        adm_cards = db.get_all_bank_cards()
        active_cards = [c for c in adm_cards if c.get("is_active")]
        gw_cfg = db.get_admin_gateway()
        from payment import CryptoPaymentGateway
        crypto_cfg = CryptoPaymentGateway.get_crypto_config(db)

    user_id = sub.get("telegram_id") or 0
    user_wallet = db.get_user_wallet_balance(user_id) if user_id else 0

    active_methods = []
    for m in ordered_methods:
        if not m.get("enabled", True):
            continue

        m_id = m.get("id")
        if m_id == "card_to_card":
            if active_cards:
                active_methods.append({
                    "id": "card_to_card",
                    "name": "کارت به کارت (بانکی)",
                    "title": "کارت به کارت (واریز بانکی)",
                    "desc": "واریز به شماره کارت با تایید خودکار پیامک بانک",
                    "icon": "fa-credit-card",
                    "color": "primary",
                    "badge": "تایید خودکار"
                })
        elif m_id == "online_gateway":
            if gw_cfg.get("enabled") and gw_cfg.get("key"):
                gw_type = gw_cfg.get("type", "zarinpal")
                if gw_type == "blupal":
                    gw_title = "کارت به کارت هوشمند (بلوپال)"
                    gw_desc = "پرداخت شتابی با درگاه کارت به کارت هوشمند بلوپال"
                else:
                    gw_label = "زرین‌پال" if gw_type == "zarinpal" else ("آیدی‌پی" if gw_type == "idpay" else "شاپرک")
                    gw_title = f"درگاه پرداخت اینترنتی ({gw_label})"
                    gw_desc = "پرداخت آنلاین و آنی با کلیه کارت‌های بانکی عضو شتاب"

                active_methods.append({
                    "id": "online_gateway",
                    "name": gw_title,
                    "title": gw_title,
                    "desc": gw_desc,
                    "icon": "fa-globe",
                    "color": "success",
                    "badge": "پرداخت آنی"
                })
        elif m_id == "crypto":
            if crypto_cfg.get("enabled") and (crypto_cfg.get("wallet_address") or crypto_cfg.get("api_key")):
                active_methods.append({
                    "id": "crypto",
                    "name": "ارز دیجیتال (تتر / کریپتو)",
                    "title": "پرداخت با تتر (USDT)",
                    "desc": f"شبکه USDT (TRC20 / TON) - نرخ: {crypto_cfg.get('usdt_rate', 90000):,} ت",
                    "icon": "fa-gem",
                    "color": "warning",
                    "badge": "TRC20 / TON"
                })
        elif m_id == "wallet":
            if user_id and user_id > 0:
                active_methods.append({
                    "id": "wallet",
                    "name": "کیف پول",
                    "title": "پرداخت از موجودی کیف پول",
                    "desc": f"کسر آنی از کیف پول کاربری (موجودی: {user_wallet:,} تومان)",
                    "icon": "fa-wallet",
                    "color": "info",
                    "badge": f"{user_wallet:,} ت",
                    "balance": user_wallet
                })

    return active_methods


def _handle_customer_portal_view(token: str):
    """
    پورتال دائمی و صفحه استعلام وضعیت و تمدید اشتراک مشتری (بدون نیاز به لاگین)
    token می‌تواند hidify_uuid یا شناسه اشتراک باشد.
    """
    conn = db.get_connection()
    sub_row = conn.execute("SELECT * FROM subscriptions WHERE hidify_uuid=? OR id=?", (token, token)).fetchone()
    conn.close()

    if not sub_row:
        return render_template("troubleshoot_wizard.html", error="اشتراک مورد نظر یافت نشد یا حذف شده است."), 404

    sub = dict(sub_row)
    sub = enrich_subscription_details(sub)
    sub_id = sub["id"]
    reseller_id = sub.get("reseller_id") or 0

    # بررسی برندینگ و نماینده
    brand_title = db.get_setting("portal_title") or db.get_setting("store_name") or "فروشگاه اینترنت آزاد"
    portal_subtitle = db.get_setting("portal_subtitle") or "پورتال اختصاصی استعلام وضعیت و تمدید اشتراک"
    logo_url = db.get_setting("store_logo")
    support_username = db.get_setting("support_username")
    support_phone = db.get_setting("support_phone")
    portal_layout = db.get_setting("portal_layout", "classic")
    portal_plan_style = db.get_setting("portal_plan_style", "glass_classic")

    if reseller_id:
        r_info = db.get_reseller(reseller_id) or {}
        brand_title = r_info.get("portal_title") or r_info.get("brand_title") or r_info.get("brand_name") or r_info.get("name") or brand_title
        portal_subtitle = r_info.get("portal_subtitle") or portal_subtitle
        logo_url = r_info.get("logo_url") or logo_url
        support_username = r_info.get("support_username") or support_username
        support_phone = r_info.get("support_phone") or r_info.get("phone") or support_phone
        if r_info.get("portal_layout"):
            portal_layout = r_info["portal_layout"]
        if r_info.get("portal_plan_style"):
            portal_plan_style = r_info["portal_plan_style"]

    # روزهای مانده از تابع غنی‌ساز هیدیفای
    days_left = sub.get("remaining_days", sub.get("duration", 30))
    if sub.get("is_expired") and days_left < 0:
        days_left = 0

    # دریافت پلن‌های مجاز
    if reseller_id:
        raw_plans = db.get_reseller_active_plans(reseller_id)
        plans = []
        for rp in raw_plans:
            plans.append({
                "id": str(rp["plan_id"]),
                "plan_id": str(rp["plan_id"]),
                "name": rp.get("custom_name") or rp.get("name") or rp["plan_id"],
                "price": rp.get("custom_price") or rp.get("price") or 0,
                "data_limit": rp.get("data_limit", 30),
                "duration": rp.get("duration", 30),
                "plan_icon": rp.get("plan_icon", "")
            })
        if not plans:
            raw = get_plans_dict()
            plans = [{"id": str(k), "plan_id": str(k), **v} for k, v in raw.items() if v.get("is_active", True)]
    else:
        raw = get_plans_dict()
        plans = [{"id": str(k), "plan_id": str(k), **v} for k, v in raw.items() if v.get("is_active", True)]

    # دریافت آخرین فاکتور فعال معلق برای این اشتراک (در صورت وجود)
    now_str = get_now_naive().isoformat()
    conn = db.get_connection()
    inv_row = conn.execute("""
        SELECT * FROM smart_invoices 
        WHERE sub_id=? AND status='pending' AND expires_at > ?
        ORDER BY id DESC LIMIT 1
    """, (sub_id, now_str)).fetchone()
    conn.close()
    invoice = dict(inv_row) if inv_row else None

    # لینک‌های اشتراک و کانفیگ تکی
    user_uuid = sub.get("hidify_uuid") or str(sub_id)
    acc_name = sub.get("account_name") or ""
    panel_url = get_hiddify_url()
    user_proxy = get_user_proxy()
    sub_url = f"{panel_url}/{user_proxy}/{user_uuid}/" if (panel_url and user_uuid) else ""
    single_link_template = db.get_setting("single_link_template")
    single_url = format_single_link(single_link_template, uuid=user_uuid, name=acc_name) if (single_link_template and user_uuid) else ""

    # لینک آموزش‌ها و عیب‌یابی اتصال
    troubleshoot_url = url_for("troubleshoot_wizard", _external=True)

    portal_enable_renewal = str(db.get_setting("portal_enable_renewal", "1")).lower() in ("1", "true")
    portal_show_troubleshoot = str(db.get_setting("portal_show_troubleshoot", "1")).lower() in ("1", "true")
    pending_queues = db.get_pending_queue_items(sub_id)
    pending_queue = pending_queues[0] if pending_queues else None

    # دریافت سوابق دوره‌ها و تمدیدهای گذشته و تراکنش‌های پرداخت این اشتراک
    conn = db.get_connection()
    sub_hist_rows = conn.execute("""
        SELECT * FROM subscription_history 
        WHERE subscription_id = ? OR (hidify_uuid = ? AND hidify_uuid IS NOT NULL AND hidify_uuid != '')
        ORDER BY 
            CASE 
                WHEN period_offset IS NOT NULL AND period_offset > 0 THEN period_offset 
                ELSE 9999 
            END ASC,
            renewed_at DESC, id DESC
    """, (sub_id, sub.get("hidify_uuid") or "")).fetchall()

    tx_rows = conn.execute("""
        SELECT * FROM transactions 
        WHERE (renew_sub_id = ? OR (account_name IS NOT NULL AND account_name != '' AND account_name = ?) OR (user_id = ? AND user_id > 0))
          AND (is_deleted = 0 OR is_deleted IS NULL)
          AND (gateway != 'bundle_reseller' AND order_id NOT LIKE 'R_BUNDLE%')
        ORDER BY created_at DESC LIMIT 40
    """, (sub_id, acc_name, sub.get("telegram_id") or 0)).fetchall()
    conn.close()

    sub_history = [dict(r) for r in sub_hist_rows]
    tx_history = [dict(r) for r in tx_rows]
    total_paid = sum(int(t.get("amount") or 0) for t in tx_history if t.get("status") in ("approved", "completed", "paid"))

    server_status = get_customer_portal_server_status()
    portal_palette_config = get_active_palette_config(db, context="portal")
    portal_palette_css = generate_palette_css(portal_palette_config)
    chat_settings = db.get_chat_settings()
    support_online_info = db.is_support_online_for_sub(sub_id, reseller_id=reseller_id)

    # روش‌های پرداخت فعال اختصاصی برای مشتری بر اساس مالک اشتراک
    portal_payment_methods = get_portal_payment_methods(sub)
    user_id = sub.get("telegram_id") or 0
    user_wallet = db.get_user_wallet_balance(user_id) if user_id else 0

    return render_template(
        "customer_portal.html",
        sub=sub,
        token=token,
        brand_title=brand_title,
        portal_subtitle=portal_subtitle,
        logo_url=logo_url,
        support_username=support_username,
        support_phone=support_phone,
        days_left=days_left,
        plans=plans,
        invoice=invoice,
        sub_url=sub_url,
        single_url=single_url,
        troubleshoot_url=troubleshoot_url,
        portal_enable_renewal=portal_enable_renewal,
        portal_show_troubleshoot=portal_show_troubleshoot,
        pending_queue=pending_queue,
        pending_queues=pending_queues,
        sub_history=sub_history,
        tx_history=tx_history,
        total_paid=total_paid,
        server_status=server_status,
        palette_config=portal_palette_config,
        palette_css=portal_palette_css,
        chat_settings=chat_settings,
        support_online_info=support_online_info,
        portal_layout=portal_layout,
        portal_plan_style=portal_plan_style,
        portal_payment_methods=portal_payment_methods,
        user_wallet=user_wallet
    )


@app.route("/user/<token>", methods=["GET"])
@app.route("/sub/<token>", methods=["GET"])
@app.route("/renew/<token>", methods=["GET"])
def customer_portal(token: str):
    """روت اصلی پورتال دائمی و استعلام وضعیت و تمدید اشتراک مشتری"""
    return _handle_customer_portal_view(token)


@app.route("/<portal_prefix>/<token>", methods=["GET"])
def customer_portal_dynamic(portal_prefix: str, token: str):
    """روت پویا و سفارشی پورتال مشتری با پشتیبانی از هر پروکسی پچ تنظیمی"""
    active_prefix = get_portal_proxy_path()
    valid_prefixes = {active_prefix, "renew", "user", "sub"}
    if portal_prefix not in valid_prefixes:
        abort(404)
    return _handle_customer_portal_view(token)


@app.route("/renew/cancel-invoice/<token>", methods=["GET", "POST"])
@app.route("/renew/cancel-invoice/<token>/<order_id>", methods=["GET", "POST"])
def customer_cancel_invoice(token: str, order_id: str = None):
    """لغو فاکتور معلق فعلی و بازگشت به انتخاب مجدد روش پرداخت توسط مشتری"""
    conn = db.get_connection()
    sub_row = conn.execute("SELECT * FROM subscriptions WHERE hidify_uuid=? OR id=?", (token, token)).fetchone()
    conn.close()

    if not sub_row:
        flash("اشتراک یافت نشد.", "danger")
        return redirect(url_for("customer_portal", token=token))

    sub_id = sub_row["id"]
    if not order_id:
        now_str = get_now_naive().isoformat()
        conn = db.get_connection()
        inv_row = conn.execute("""
            SELECT order_id FROM smart_invoices 
            WHERE sub_id=? AND status='pending' AND expires_at > ?
            ORDER BY id DESC LIMIT 1
        """, (sub_id, now_str)).fetchone()
        conn.close()
        if inv_row:
            order_id = inv_row["order_id"]

    if order_id:
        db.cancel_smart_invoice(order_id, sub_id=sub_id)
        conn = db.get_connection()
        conn.execute("UPDATE transactions SET status='cancelled' WHERE order_id=? AND status='pending'", (order_id,))
        conn.commit()
        conn.close()
        flash("فاکتور قبلی لغو شد. اکنون می‌توانید روش پرداخت مورد نظر خود را انتخاب نمایید.", "info")
    else:
        flash("هیچ فاکتور فعالی برای لغو یافت نشد.", "warning")

    return redirect(url_for("customer_portal", token=token))


@app.route("/renew/create-invoice/<token>", methods=["POST"])
def customer_create_invoice(token: str):
    """ایجاد فاکتور و پردازش پرداخت تمدید مشتری با پشتیبانی کامل از روش‌های پرداخت تفکیک‌شده (کارت به کارت، درگاه آنلاین، کریپتو، کیف پول)"""
    conn = db.get_connection()
    sub_row = conn.execute("SELECT * FROM subscriptions WHERE hidify_uuid=? OR id=?", (token, token)).fetchone()
    conn.close()

    if not sub_row:
        flash("اشتراک یافت نشد.", "danger")
        return redirect(url_for("customer_portal", token=token))

    sub = dict(sub_row)
    sub_id = sub["id"]
    reseller_id = sub.get("reseller_id") or 0
    plan_id = request.form.get("plan_id")
    payment_method = request.form.get("payment_method", "card_to_card").strip()
    instant_activation = (request.form.get("instant_activation") == "1")

    # استخراج مشخصات پلن انتخابی
    price = 0
    plan_name = "بسته تمدید"
    plan_data_limit = 30
    plan_duration = 30
    if reseller_id:
        r_plan = db.get_reseller_plan(reseller_id, plan_id)
        if r_plan:
            price = r_plan.get("custom_price") or r_plan.get("price") or 0
            plan_name = r_plan.get("custom_name") or r_plan.get("name") or plan_id
            plan_data_limit = r_plan.get("data_limit", 30)
            plan_duration = r_plan.get("duration", 30)
    if not price:
        g_plan = get_plans_dict().get(plan_id)
        if g_plan:
            price = g_plan.get("price", 0)
            plan_name = g_plan.get("name", plan_id)
            plan_data_limit = g_plan.get("data_limit", 30)
            plan_duration = g_plan.get("duration", 30)

    if not price:
        price = 100000

    # پردازش و اعتبارسنجی کد تخفیف
    raw_discount_code = request.form.get("discount_code", "").strip().upper()
    discount_val = 0
    valid_discount_code = None

    if raw_discount_code:
        chk_res = db.validate_customer_discount(sub, raw_discount_code, price)
        if chk_res.get("valid"):
            discount_val = int(chk_res.get("discount_amount") or 0)
            valid_discount_code = raw_discount_code
            price = max(0, price - discount_val)
            db.apply_customer_discount(sub, raw_discount_code)
        else:
            flash(f"کد تخفیف نامعتبر: {chk_res.get('error', 'این کد تخفیف برای شما معتبر نیست.')}", "warning")

    now_iso = get_now_iso()
    user_id = sub.get("telegram_id") or 0
    account_name = sub.get("account_name") or f"sub_{sub_id}"

    # ۱. حالت ویژه: مبلغ صفر ریال (۱۰۰٪ تخفیف یا رایگان)
    if price <= 0:
        order_id = f"FREE_{int(datetime.now().timestamp())}_{sub_id}"
        conn = db.get_connection()
        conn.execute("""
            INSERT OR REPLACE INTO transactions (
                order_id, user_id, username, plan_name, amount, status, gateway, 
                tracking_code, reseller_id, is_renewal, renew_sub_id, 
                account_name, source, created_at, updated_at
            ) VALUES (?, ?, ?, ?, 0, 'approved', 'free_discount', 'رایگان', ?, 1, ?, ?, 'portal_free', ?, ?)
        """, (order_id, user_id, account_name, plan_name, reseller_id, sub_id, account_name, now_iso, now_iso))
        conn.commit()
        conn.close()

        fulfill_approved_transaction(order_id, ref_id="رایگان", processed_by="کد تخفیف ۱۰۰٪")
        flash(f"🎉 تبریک! اشتراک شما با بسته «{plan_name}» به صورت رایگان فعال شد.", "success")
        return redirect(url_for("customer_portal", token=token))

    # ۲. پرداخت آنلاین از طریق درگاه شاپرک / بلوپال
    if payment_method == "online_gateway":
        if reseller_id:
            gw_cfg = db.get_reseller_gateway(reseller_id)
        else:
            gw_cfg = db.get_admin_gateway()

        if not gw_cfg.get("enabled") or not gw_cfg.get("key"):
            flash("درگاه پرداخت آنلاین در دسترس نیست یا توسط مدیریت/نماینده فعال نشده است. لطفاً از کارت به کارت استفاده فرمایید.", "warning")
            return redirect(url_for("customer_portal", token=token))

        gw_type = gw_cfg.get("type", "zarinpal")
        gw_key = gw_cfg.get("key")
        sandbox = gw_cfg.get("sandbox", False)
        order_id = f"CP_ONL_{int(datetime.now().timestamp())}_{sub_id}"

        # دریافت دامنه پایه جهت کال‌بک
        r_info = db.get_reseller(reseller_id) or {} if reseller_id else {}
        domain = r_info.get("custom_domain") or db.get_setting("custom_domain") or os.getenv("PANEL_DOMAIN", "http://localhost:5000")
        if not str(domain).startswith("http"):
            domain = f"https://{domain}"
        callback_url = f"{str(domain).rstrip('/')}/payment/callback/{order_id}?token={token}"

        conn = db.get_connection()
        conn.execute("""
            INSERT OR REPLACE INTO transactions (
                order_id, user_id, username, plan_name, amount, status, gateway, 
                tracking_code, reseller_id, is_renewal, renew_sub_id, 
                account_name, source, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'pending', ?, '', ?, 1, ?, ?, 'portal_online', ?, ?)
        """, (order_id, user_id, account_name, plan_name, price, f"{gw_type}_portal", reseller_id, sub_id, account_name, now_iso, now_iso))
        conn.commit()
        conn.close()

        # ثبت هوشمند جهت حفظ وضعیت instant_activation در زمان بازگشت از درگاه
        db.create_smart_invoice(
            sub_id=sub_id,
            plan_id=plan_id,
            reseller_id=reseller_id,
            base_amount=price,
            target_card={"card_number": f"ONLINE_{gw_type.upper()}", "card_holder": f"درگاه {gw_type}", "bank_name": "شاپرک"},
            digits=0,
            timeout_minutes=60,
            instant_activation=instant_activation,
            discount_code=valid_discount_code,
            discount_amount=discount_val
        )

        try:
            if gw_type == "zarinpal":
                from payment import ZarinPal
                zp = ZarinPal(merchant_id=gw_key, sandbox=sandbox)
                res = zp.create_payment(amount=price, description=f"تمدید اشتراک {account_name} ({plan_name})", callback_url=callback_url)
                if res.get("success"):
                    db.update_transaction(order_id, tracking_code=res.get("authority", ""))
                    return redirect(res.get("payment_url"))
                else:
                    flash(f"خطا در ایجاد تراکنش زرین‌پال: {res.get('error')}", "danger")
                    return redirect(url_for("customer_portal", token=token))
            elif gw_type == "idpay":
                from payment import IDPay
                idp = IDPay(api_key=gw_key, sandbox=sandbox)
                res = idp.create_payment(amount=price, name=account_name, description=f"تمدید اشتراک {account_name} ({plan_name})", callback_url=callback_url, order_id=order_id)
                if res.get("success"):
                    db.update_transaction(order_id, tracking_code=res.get("payment_id", ""))
                    return redirect(res.get("payment_url"))
                else:
                    flash(f"خطا در ایجاد تراکنش آیدی‌پی: {res.get('error')}", "danger")
                    return redirect(url_for("customer_portal", token=token))
            elif gw_type == "blupal":
                from payment import BluPal
                bp = BluPal(api_key=gw_key, sandbox=sandbox)
                res = bp.create_payment(amount=price, order_id=order_id, description=f"تمدید اشتراک {account_name} ({plan_name})")
                if res.get("success"):
                    invoice_id = res.get("invoice_id")
                    db.update_transaction(order_id, tracking_code=str(invoice_id or order_id))
                    return redirect(res.get("payment_url") or res.get("payment_link"))
                else:
                    flash(f"خطا در ایجاد فاکتور بلوپال: {res.get('error')}", "danger")
                    return redirect(url_for("customer_portal", token=token))
            else:
                flash("درگاه انتخاب شده پشتیبانی نمی‌شود.", "warning")
                return redirect(url_for("customer_portal", token=token))
        except Exception as e_gw:
            logger.error(f"Online gateway exception: {e_gw}")
            flash(f"خطا در اتصال به درگاه پرداخت: {str(e_gw)}", "danger")
            return redirect(url_for("customer_portal", token=token))

    # ۳. پرداخت آنی از موجودی کیف پول کاربر
    elif payment_method == "wallet":
        if not user_id or user_id <= 0:
            flash("پرداخت از کیف پول فقط برای اشتراک‌های متصل به حساب تلگرام امکان‌پذیر است.", "warning")
            return redirect(url_for("customer_portal", token=token))

        user_wallet = db.get_user_wallet_balance(user_id)
        if user_wallet < price:
            flash(f"موجودی کیف پول شما ({user_wallet:,} تومان) کافی نیست. کسری موجودی: {price - user_wallet:,} تومان.", "warning")
            return redirect(url_for("customer_portal", token=token))

        deduct_res = db.deduct_wallet_balance(user_id, price, f"تمدید اشتراک {account_name} ({plan_name}) از پورتال")
        if not deduct_res.get("success"):
            flash(f"خطا در کسر از کیف پول: {deduct_res.get('error')}", "danger")
            return redirect(url_for("customer_portal", token=token))

        order_id = f"CP_WAL_{int(datetime.now().timestamp())}_{sub_id}"
        conn = db.get_connection()
        conn.execute("""
            INSERT OR REPLACE INTO transactions (
                order_id, user_id, username, plan_name, amount, status, gateway, 
                tracking_code, reseller_id, is_renewal, renew_sub_id, 
                account_name, source, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'approved', 'wallet', 'کیف پول', ?, 1, ?, ?, 'portal_wallet', ?, ?)
        """, (order_id, user_id, account_name, plan_name, price, reseller_id, sub_id, account_name, now_iso, now_iso))
        conn.commit()
        conn.close()

        fulfill_approved_transaction(order_id, ref_id="کسر از کیف پول", processed_by="کیف پول (پورتال)")
        flash(f"✅ مبلغ {price:,} تومان از کیف پول شما کسر و بسته «{plan_name}» با موفقیت فعال شد.", "success")
        return redirect(url_for("customer_portal", token=token))

    # ۴. پرداخت با ارز دیجیتال (تتر / کریپتو)
    elif payment_method == "crypto":
        if reseller_id:
            crypto_cfg = db.get_reseller_crypto_config(reseller_id)
        else:
            from payment import CryptoPaymentGateway
            crypto_cfg = CryptoPaymentGateway.get_crypto_config(db)

        wallet_addr = crypto_cfg.get("wallet_address", "").strip()
        if not crypto_cfg.get("enabled") or not wallet_addr:
            flash("درگاه پرداخت کریپتو برای این فروشگاه فعال نشده است. لطفاً از کارت به کارت استفاده فرمایید.", "warning")
            return redirect(url_for("customer_portal", token=token))

        usdt_rate = crypto_cfg.get("usdt_rate") or 90000
        usdt_amount = round(float(price) / float(usdt_rate), 2)
        order_id = f"CP_CRY_{int(datetime.now().timestamp())}_{sub_id}"

        target_card = {
            "card_number": wallet_addr,
            "card_holder": f"{usdt_amount} USDT ({crypto_cfg.get('network', 'TRC20 / TON')})",
            "bank_name": "ارز دیجیتال (تتر)"
        }

        invoice = db.create_smart_invoice(
            sub_id=sub_id,
            plan_id=plan_id,
            reseller_id=reseller_id,
            base_amount=price,
            target_card=target_card,
            digits=0,
            timeout_minutes=120,
            instant_activation=instant_activation,
            discount_code=valid_discount_code,
            discount_amount=discount_val
        )

        conn = db.get_connection()
        conn.execute("""
            INSERT OR REPLACE INTO transactions (
                order_id, user_id, username, plan_name, amount, status, gateway, 
                tracking_code, reseller_id, is_renewal, renew_sub_id, 
                account_name, source, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'pending', 'crypto', ?, ?, 1, ?, ?, 'portal_crypto', ?, ?)
        """, (order_id, user_id, account_name, plan_name, price, f"تتر: {usdt_amount} USDT", reseller_id, sub_id, account_name, now_iso, now_iso))
        conn.commit()
        conn.close()

        # اطلاع به مالک در تلگرام
        pay_notif = (
            f"💎 <b>صدور فاکتور تمدید ارزی (تتر / کریپتو) در پرتال مشتری!</b>\n\n"
            f"🆔 شناسه سفارش: <code>{order_id}</code>\n"
            f"👤 مشتری: <b>{account_name}</b> (اشتراک #{sub_id})\n"
            f"📦 بسته انتخابی: <b>{plan_name}</b>\n"
            f"💰 مبلغ تتر: <b>{usdt_amount} USDT</b> ({price:,} تومان)\n"
            f"📥 والت مقصد: <code>{wallet_addr}</code>\n"
            f"⏰ زمان: {get_now_shamsi()}"
        )
        if reseller_id:
            try:
                r_info = db.get_reseller(reseller_id) or {}
                if r_info.get("telegram_id"):
                    r_pay_kb = {
                        "inline_keyboard": [
                            [
                                {"text": "✅ تایید پرداخت و تمدید", "callback_data": f"res_pay_app_{order_id}"},
                                {"text": "❌ رد پرداخت", "callback_data": f"res_pay_rej_{order_id}"}
                            ]
                        ]
                    }
                    send_telegram_msg(r_info["telegram_id"], pay_notif, reply_markup=r_pay_kb, bot_token=r_info.get("bot_token"))
            except Exception as e_res_tg:
                logger.warning(f"Failed to notify reseller of crypto invoice: {e_res_tg}")
        else:
            try:
                admin_tg = db.get_setting("admin_telegram_id") or get_admin_id()
                if admin_tg:
                    adm_pay_kb = {
                        "inline_keyboard": [
                            [
                                {"text": "✅ تایید پرداخت و تمدید", "callback_data": f"adm_pay_app_{order_id}"},
                                {"text": "❌ رد پرداخت", "callback_data": f"adm_pay_rej_{order_id}"}
                            ]
                        ]
                    }
                    send_telegram_msg(int(admin_tg), pay_notif, reply_markup=adm_pay_kb)
            except Exception as e_adm_tg:
                logger.warning(f"Failed to notify admin of crypto invoice: {e_adm_tg}")

        flash(f"فاکتور پرداخت ارزی صادر شد. لطفاً دقیقاً مبلغ {usdt_amount} تتر (USDT) را به آدرس والت مشخص شده واریز نمایید.", "info")
        return redirect(url_for("customer_portal", token=token))

    # ۵. حالت پیش‌فرض: کارت به کارت بانکی (با اولویت کارت‌های فعال مالک)
    target_card = None
    sms_cfg = {}
    if reseller_id:
        r_cards = db.get_reseller_cards(reseller_id)
        active_r_cards = [c for c in r_cards if c.get("is_active")]
        if active_r_cards:
            target_card = random.choice(active_r_cards)
            sms_cfg = db.get_reseller_bank_sms_config(reseller_id)
        else:
            adm_cards = db.get_all_bank_cards()
            active_adm_cards = [c for c in adm_cards if c.get("is_active")]
            if active_adm_cards:
                target_card = random.choice(active_adm_cards)
                sms_cfg = db.get_admin_bank_sms_config()
                logger.warning(f"Reseller {reseller_id} has no active bank cards. Falling back to admin cards for sub {sub_id}.")
    else:
        adm_cards = db.get_all_bank_cards()
        active_adm_cards = [c for c in adm_cards if c.get("is_active")]
        if active_adm_cards:
            target_card = random.choice(active_adm_cards)
            sms_cfg = db.get_admin_bank_sms_config()

    if not target_card:
        flash("هیچ کارت بانکی فعالی در سامانه تعریف نشده است. لطفاً به پشتیبانی پیام دهید.", "warning")
        return redirect(url_for("customer_portal", token=token))

    digits = sms_cfg.get("digits", 3) if isinstance(sms_cfg, dict) else 3
    timeout = sms_cfg.get("timeout", 15) if isinstance(sms_cfg, dict) else 15

    invoice = db.create_smart_invoice(
        sub_id=sub_id,
        plan_id=plan_id,
        reseller_id=reseller_id,
        base_amount=price,
        target_card=target_card,
        digits=digits,
        timeout_minutes=timeout,
        instant_activation=instant_activation,
        discount_code=valid_discount_code,
        discount_amount=discount_val
    )

    order_id = invoice["order_id"]
    conn = db.get_connection()
    conn.execute("""
        INSERT OR REPLACE INTO transactions (
            order_id, user_id, username, plan_name, amount, status, gateway, 
            tracking_code, reseller_id, is_renewal, renew_sub_id, 
            account_name, source, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, 'pending', 'bank_sms', ?, ?, 1, ?, ?, 'portal', ?, ?)
    """, (
        order_id, user_id, account_name, plan_name, invoice["final_amount"],
        f"کارت {target_card.get('card_number', '')}", reseller_id, sub_id,
        account_name, now_iso, now_iso
    ))
    conn.commit()
    conn.close()

    # ارسال اعلان تلگرام برای نماینده یا مدیریت
    final_amount = invoice["final_amount"]
    card_info = target_card.get("card_number", "")
    card_holder = target_card.get("card_holder", "")
    pay_notif = (
        f"💳 <b>صدور پیش‌فاکتور تمدید جدید در پرتال مشتری!</b>\n\n"
        f"🆔 شناسه سفارش: <code>{order_id}</code>\n"
        f"👤 مشتری: <b>{account_name}</b> (اشتراک #{sub_id})\n"
        f"📦 بسته انتخابی: <b>{plan_name}</b>\n"
        f"💰 مبلغ واریزی: <b>{final_amount:,} تومان</b>\n"
        f"💳 کارت مقصد: <code>{card_info}</code> ({card_holder})\n"
        f"⏰ زمان: {get_now_shamsi()}"
    )
    if discount_val > 0 and valid_discount_code:
        pay_notif += f"\n🎟️ کد تخفیف اعمال‌شده: <code>{valid_discount_code}</code> ({discount_val:,} تومان)"
    if reseller_id:
        try:
            r_info = db.get_reseller(reseller_id) or {}
            r_tg = r_info.get("telegram_id")
            if r_tg:
                r_bot_token = r_info.get("bot_token")
                r_pay_kb = {
                    "inline_keyboard": [
                        [
                            {"text": "✅ تایید پرداخت و تمدید", "callback_data": f"res_pay_app_{order_id}"},
                            {"text": "❌ رد پرداخت", "callback_data": f"res_pay_rej_{order_id}"}
                        ]
                    ]
                }
                send_telegram_msg(r_tg, pay_notif, reply_markup=r_pay_kb, bot_token=r_bot_token)
        except Exception as e_res_tg:
            logger.warning(f"Failed to notify reseller of invoice: {e_res_tg}")
    else:
        try:
            admin_tg = db.get_setting("admin_telegram_id") or get_admin_id()
            if admin_tg:
                adm_pay_kb = {
                    "inline_keyboard": [
                        [
                            {"text": "✅ تایید پرداخت و تمدید", "callback_data": f"adm_pay_app_{order_id}"},
                            {"text": "❌ رد پرداخت", "callback_data": f"adm_pay_rej_{order_id}"}
                        ]
                    ]
                }
                send_telegram_msg(int(admin_tg), pay_notif, reply_markup=adm_pay_kb)
        except Exception as e_adm_tg:
            logger.warning(f"Failed to notify admin of invoice: {e_adm_tg}")

    flash(f"فاکتور تمدید برای «{plan_name}» صادر شد. لطفاً دقیقاً مبلغ مشخص شده را واریز نمایید.", "info")
    return redirect(url_for("customer_portal", token=token))


@app.route("/renew/settle-debt/<token>", methods=["POST"])
def customer_settle_debt_invoice(token: str):
    """ایجاد فاکتور و پرداخت جهت تسویه بدهی مشتری از طریق پرتال با پشتیبانی از کلیه روش‌های فعال"""
    conn = db.get_connection()
    sub_row = conn.execute("SELECT * FROM subscriptions WHERE hidify_uuid=? OR id=?", (token, token)).fetchone()
    conn.close()

    if not sub_row:
        flash("اشتراک یافت نشد.", "danger")
        return redirect(url_for("customer_portal", token=token))

    sub = dict(sub_row)
    sub_id = sub["id"]
    reseller_id = sub.get("reseller_id") or 0
    debt_amount = int(sub.get("debt_amount") or 0)
    payment_method = request.form.get("payment_method", "card_to_card").strip()

    if debt_amount <= 0:
        flash("این اشتراک هیچ بدهی پرداخت‌نشده‌ای ندارد.", "info")
        return redirect(url_for("customer_portal", token=token))

    now_iso = get_now_iso()
    user_id = sub.get("telegram_id") or 0
    account_name = sub.get("account_name") or f"sub_{sub_id}"

    # ۱. پرداخت آنلاین بدهی با درگاه شاپرک / بلوپال
    if payment_method == "online_gateway":
        if reseller_id:
            gw_cfg = db.get_reseller_gateway(reseller_id)
        else:
            gw_cfg = db.get_admin_gateway()

        if not gw_cfg.get("enabled") or not gw_cfg.get("key"):
            flash("درگاه پرداخت آنلاین در دسترس نیست. لطفاً از کارت به کارت استفاده فرمایید.", "warning")
            return redirect(url_for("customer_portal", token=token))

        gw_type = gw_cfg.get("type", "zarinpal")
        gw_key = gw_cfg.get("key")
        sandbox = gw_cfg.get("sandbox", False)
        order_id = f"DEBT_ONL_{int(datetime.now().timestamp())}_{sub_id}"

        r_info = db.get_reseller(reseller_id) or {} if reseller_id else {}
        domain = r_info.get("custom_domain") or db.get_setting("custom_domain") or os.getenv("PANEL_DOMAIN", "http://localhost:5000")
        if not str(domain).startswith("http"):
            domain = f"https://{domain}"
        callback_url = f"{str(domain).rstrip('/')}/payment/callback/{order_id}?token={token}"

        conn = db.get_connection()
        conn.execute("""
            INSERT OR REPLACE INTO transactions (
                order_id, user_id, username, plan_name, amount, status, gateway, 
                tracking_code, reseller_id, is_renewal, renew_sub_id, 
                account_name, source, is_debt_settlement, created_at, updated_at
            ) VALUES (?, ?, ?, 'تسویه بدهی اشتراک', ?, 'pending', ?, '', ?, 0, ?, ?, 'portal_debt_online', 1, ?, ?)
        """, (order_id, user_id, account_name, debt_amount, f"{gw_type}_portal", reseller_id, sub_id, account_name, now_iso, now_iso))
        conn.commit()
        conn.close()

        db.create_smart_invoice(
            sub_id=sub_id,
            plan_id="debt_settlement",
            reseller_id=reseller_id,
            base_amount=debt_amount,
            target_card={"card_number": f"ONLINE_{gw_type.upper()}", "card_holder": f"درگاه {gw_type}", "bank_name": "شاپرک"},
            digits=0,
            timeout_minutes=60,
            instant_activation=False,
            is_debt_settlement=1
        )

        try:
            if gw_type == "zarinpal":
                from payment import ZarinPal
                zp = ZarinPal(merchant_id=gw_key, sandbox=sandbox)
                res = zp.create_payment(amount=debt_amount, description=f"تسویه بدهی اشتراک {account_name}", callback_url=callback_url)
                if res.get("success"):
                    db.update_transaction(order_id, tracking_code=res.get("authority", ""))
                    return redirect(res.get("payment_url"))
                else:
                    flash(f"خطا در درگاه زرین‌پال: {res.get('error')}", "danger")
                    return redirect(url_for("customer_portal", token=token))
            elif gw_type == "idpay":
                from payment import IDPay
                idp = IDPay(api_key=gw_key, sandbox=sandbox)
                res = idp.create_payment(amount=debt_amount, name=account_name, description=f"تسویه بدهی اشتراک {account_name}", callback_url=callback_url, order_id=order_id)
                if res.get("success"):
                    db.update_transaction(order_id, tracking_code=res.get("payment_id", ""))
                    return redirect(res.get("payment_url"))
                else:
                    flash(f"خطا در درگاه آیدی‌پی: {res.get('error')}", "danger")
                    return redirect(url_for("customer_portal", token=token))
            elif gw_type == "blupal":
                from payment import BluPal
                bp = BluPal(api_key=gw_key, sandbox=sandbox)
                res = bp.create_payment(amount=debt_amount, order_id=order_id, description=f"تسویه بدهی اشتراک {account_name}")
                if res.get("success"):
                    invoice_id = res.get("invoice_id")
                    db.update_transaction(order_id, tracking_code=str(invoice_id or order_id))
                    return redirect(res.get("payment_url") or res.get("payment_link"))
                else:
                    flash(f"خطا در درگاه بلوپال: {res.get('error')}", "danger")
                    return redirect(url_for("customer_portal", token=token))
            else:
                flash("درگاه انتخاب شده پشتیبانی نمی‌شود.", "warning")
                return redirect(url_for("customer_portal", token=token))
        except Exception as e_gw:
            flash(f"خطا در اتصال به درگاه: {str(e_gw)}", "danger")
            return redirect(url_for("customer_portal", token=token))

    # ۲. پرداخت بدهی از کیف پول کاربر
    elif payment_method == "wallet":
        if not user_id or user_id <= 0:
            flash("پرداخت از کیف پول فقط برای کاربران متصل به تلگرام مجاز است.", "warning")
            return redirect(url_for("customer_portal", token=token))

        user_wallet = db.get_user_wallet_balance(user_id)
        if user_wallet < debt_amount:
            flash(f"موجودی کیف پول شما ({user_wallet:,} ت) برای تسویه این بدهی کافی نیست.", "warning")
            return redirect(url_for("customer_portal", token=token))

        db.deduct_wallet_balance(user_id, debt_amount, f"تسویه بدهی اشتراک {account_name} از پورتال")
        db.clear_subscription_debt(sub_id, reseller_id=reseller_id, settled_by="کیف پول (پورتال)")

        order_id = f"DEBT_WAL_{int(datetime.now().timestamp())}_{sub_id}"
        conn = db.get_connection()
        conn.execute("""
            INSERT OR REPLACE INTO transactions (
                order_id, user_id, username, plan_name, amount, status, gateway, 
                tracking_code, reseller_id, is_renewal, renew_sub_id, 
                account_name, source, is_debt_settlement, created_at, updated_at
            ) VALUES (?, ?, ?, 'تسویه بدهی اشتراک', ?, 'approved', 'wallet', 'کیف پول', ?, 0, ?, ?, 'portal_debt_wallet', 1, ?, ?)
        """, (order_id, user_id, account_name, debt_amount, reseller_id, sub_id, account_name, now_iso, now_iso))
        conn.commit()
        conn.close()

        flash(f"بدهی اشتراک شما به مبلغ {debt_amount:,} تومان با موفقیت از کیف پول تسویه گردید.", "success")
        return redirect(url_for("customer_portal", token=token))

    # ۳. پرداخت بدهی با کارت به کارت بانکی
    target_card = None
    sms_cfg = {}
    if reseller_id:
        r_cards = db.get_reseller_cards(reseller_id)
        active_r_cards = [c for c in r_cards if c.get("is_active")]
        if active_r_cards:
            target_card = random.choice(active_r_cards)
            sms_cfg = db.get_reseller_bank_sms_config(reseller_id)
        else:
            adm_cards = db.get_all_bank_cards()
            active_adm_cards = [c for c in adm_cards if c.get("is_active")]
            if active_adm_cards:
                target_card = random.choice(active_adm_cards)
                sms_cfg = db.get_admin_bank_sms_config()
    else:
        adm_cards = db.get_all_bank_cards()
        active_adm_cards = [c for c in adm_cards if c.get("is_active")]
        if active_adm_cards:
            target_card = random.choice(active_adm_cards)
            sms_cfg = db.get_admin_bank_sms_config()

    if not target_card:
        flash("هیچ کارت بانکی فعالی در سامانه تعریف نشده است. لطفاً با پشتیبانی تماس بگیرید.", "warning")
        return redirect(url_for("customer_portal", token=token))

    digits = sms_cfg.get("digits", 3) if isinstance(sms_cfg, dict) else 3
    timeout = sms_cfg.get("timeout", 15) if isinstance(sms_cfg, dict) else 15

    invoice = db.create_smart_invoice(
        sub_id=sub_id,
        plan_id="debt_settlement",
        reseller_id=reseller_id,
        base_amount=debt_amount,
        target_card=target_card,
        digits=digits,
        timeout_minutes=timeout,
        instant_activation=False,
        is_debt_settlement=1
    )

    conn = db.get_connection()
    conn.execute("""
        INSERT OR REPLACE INTO transactions (
            order_id, user_id, username, plan_name, amount, status, gateway, 
            tracking_code, reseller_id, is_renewal, renew_sub_id, 
            account_name, source, is_debt_settlement, created_at, updated_at
        ) VALUES (?, ?, ?, 'تسویه بدهی اشتراک', ?, 'pending', 'bank_sms', ?, ?, 0, ?, ?, 'portal', 1, ?, ?)
    """, (
        invoice["order_id"], user_id, account_name, invoice["final_amount"],
        f"کارت {target_card.get('card_number', '')}", reseller_id, sub_id,
        account_name, now_iso, now_iso
    ))
    conn.commit()
    conn.close()

    flash(f"فاکتور تسویه بدهی صادر شد. لطفاً مبلغ دقیق فاکتور ({invoice['final_amount']:,} تومان) را جهت تسویه واریز فرمایید.", "info")
    return redirect(url_for("customer_portal", token=token))


@app.route("/api/invoice/status/<order_id>", methods=["GET"])
def api_invoice_status(order_id: str):
    """بررسی زنده وضعیت فاکتور توسط صفحه مرورگر مشتری"""
    inv = db.get_smart_invoice_by_order_id(order_id)
    if not inv:
        return jsonify({"status": "not_found"}), 404

    status = inv.get("status", "pending")
    is_expired = False
    if status == "pending" and inv.get("expires_at"):
        try:
            exp_clean = str(inv["expires_at"]).strip().replace("Z", "")
            exp_dt = datetime.fromisoformat(exp_clean)
            if get_now_naive() > exp_dt:
                is_expired = True
        except Exception:
            pass

    return jsonify({
        "order_id": inv["order_id"],
        "status": status,
        "is_expired": is_expired,
        "paid_at": inv.get("paid_at"),
        "tracking_code": inv.get("tracking_code"),
        "final_amount": inv.get("final_amount"),
        "expires_at": inv.get("expires_at")
    })


@app.route("/sub/<token>/queue/<int:queue_id>/activate", methods=["POST"])
@app.route("/user/<token>/queue/<int:queue_id>/activate", methods=["POST"])
def portal_queue_activate(token: str, queue_id: int):
    """فعال‌سازی آنی بسته در صف توسط مشتری از پورتال اختصاصی"""
    conn = db.get_connection()
    sub_row = conn.execute("SELECT * FROM subscriptions WHERE hidify_uuid=? OR id=?", (token, token)).fetchone()
    conn.close()
    if not sub_row:
        if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.is_json:
            return jsonify({"success": False, "error": "اشتراک یافت نشد."}), 404
        flash("اشتراک یافت نشد.", "danger")
        return redirect(url_for("customer_portal", token=token))

    sub = dict(sub_row)
    sub_id = sub["id"]

    # اعتبارسنجی تعلق بسته به این اشتراک و وضعیت معلق آن
    conn = db.get_connection()
    q_row = conn.execute("SELECT * FROM subscription_queue WHERE id=? AND subscription_id=? AND status='pending'", (queue_id, sub_id)).fetchone()
    conn.close()
    if not q_row:
        msg = "بسته مورد نظر در صف یافت نشد یا قبلاً فعال شده است."
        if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.is_json:
            return jsonify({"success": False, "error": msg}), 400
        flash(msg, "warning")
        return redirect(url_for("customer_portal", token=token))

    acc_name = sub.get("account_name") or f"مشتری #{sub_id}"
    res = activate_single_queue_item(queue_id, triggered_by=f"مشتری ({acc_name})")
    if res.get("success"):
        msg = f"بسته «{res.get('plan_name')}» با موفقیت فعال شد و حجم و تاریخ سرویس شما ریست گردید."
        if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.is_json:
            return jsonify({"success": True, "message": msg, "plan_name": res.get("plan_name")})
        flash(msg, "success")
    else:
        err = res.get("error", "خطا در فعال‌سازی بسته")
        if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.is_json:
            return jsonify({"success": False, "error": err}), 500
        flash(f"خطا در فعال‌سازی بسته: {err}", "danger")

    return redirect(url_for("customer_portal", token=token))


@app.route("/sub/<token>/queue/<int:queue_id>/move", methods=["POST"])
@app.route("/user/<token>/queue/<int:queue_id>/move", methods=["POST"])
def portal_queue_move(token: str, queue_id: int):
    """تغییر نوبت بسته در صف توسط مشتری از پورتال اختصاصی"""
    conn = db.get_connection()
    sub_row = conn.execute("SELECT * FROM subscriptions WHERE hidify_uuid=? OR id=?", (token, token)).fetchone()
    conn.close()
    if not sub_row:
        if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.is_json:
            return jsonify({"success": False, "error": "اشتراک یافت نشد."}), 404
        flash("اشتراک یافت نشد.", "danger")
        return redirect(url_for("customer_portal", token=token))

    sub = dict(sub_row)
    sub_id = sub["id"]

    direction = request.form.get("direction") or request.args.get("direction", "up")
    if request.is_json:
        data = request.get_json(silent=True) or {}
        direction = data.get("direction") or direction

    conn = db.get_connection()
    q_row = conn.execute("SELECT * FROM subscription_queue WHERE id=? AND subscription_id=? AND status='pending'", (queue_id, sub_id)).fetchone()
    conn.close()
    if not q_row:
        msg = "بسته مورد نظر در صف یافت نشد."
        if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.is_json:
            return jsonify({"success": False, "error": msg}), 400
        flash(msg, "warning")
        return redirect(url_for("customer_portal", token=token))

    res = db.reorder_subscription_queue(sub_id, queue_id, direction)
    if res.get("success"):
        msg = "ترتیب صف بسته‌های رزرو با موفقیت تغییر کرد."
        if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.is_json:
            return jsonify({"success": True, "message": msg})
        flash(msg, "success")
    else:
        err = res.get("error", "خطا در تغییر ترتیب صف")
        if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.is_json:
            return jsonify({"success": False, "error": err}), 400
        flash(f"خطا در تغییر ترتیب صف: {err}", "danger")

    return redirect(url_for("customer_portal", token=token))


@app.route("/api/portal/<token>/chat/init", methods=["GET"])
def api_portal_chat_init(token: str):
    """دریافت اطلاعات اولیه گفتگوی آنلاین، آخرین گفتگوی فعال و تاریخچه برای پورتال مشتری"""
    conn = db.get_connection()
    sub_row = conn.execute("SELECT * FROM subscriptions WHERE hidify_uuid=? OR id=?", (token, token)).fetchone()
    conn.close()

    if not sub_row:
        return jsonify({"success": False, "error": "اشتراک مورد نظر یافت نشد."}), 404

    sub = dict(sub_row)
    sub_id = sub["id"]
    tg_id = sub.get("telegram_id")

    history = db.get_portal_chat_history(sub_id, telegram_id=tg_id, portal_token=token)

    active_ticket = None
    active_messages = []
    for t in history:
        if t.get("status") in ("open", "in_progress", "replied"):
            active_ticket = t
            active_messages = db.get_ticket_messages(t["id"])
            break

    if not active_ticket and history:
        active_ticket = history[0]
        active_messages = db.get_ticket_messages(active_ticket["id"])

    default_name = sub.get("account_name") or ""
    if default_name.startswith("user_") or default_name.startswith("sub_"):
        default_name = ""
    default_phone = sub.get("phone_number") or ""

    reseller_id = sub.get("reseller_id") or 0
    support_status_info = db.is_support_online_for_sub(sub_id, reseller_id=reseller_id)
    chat_cfg = db.get_chat_settings()

    return jsonify({
        "success": True,
        "subscription_id": sub_id,
        "customer_name": default_name,
        "customer_phone": default_phone,
        "active_ticket": active_ticket,
        "messages": active_messages,
        "history_count": len(history),
        "history": history,
        "support_status": support_status_info["status"],
        "support_is_online": support_status_info["is_online"],
        "support_name": support_status_info["support_name"],
        "support_status_text": support_status_info["status_text"],
        "chat_button_style": chat_cfg["chat_button_style"],
        "chat_button_text": chat_cfg["chat_button_text"],
        "chat_button_position": chat_cfg["chat_button_position"],
        "customer_avatar_url": f"/avatar/{tg_id if tg_id else (sub.get('account_name') or sub_id)}",
        "support_avatar_url": f"/avatar/{('reseller_' + str(reseller_id)) if reseller_id else 'support'}"
    })


@app.route("/api/portal/<token>/chat/history", methods=["GET"])
def api_portal_chat_history(token: str):
    """دریافت لیست تمامی گفتگوهای گذشته مشتری"""
    conn = db.get_connection()
    sub_row = conn.execute("SELECT * FROM subscriptions WHERE hidify_uuid=? OR id=?", (token, token)).fetchone()
    conn.close()

    if not sub_row:
        return jsonify({"success": False, "error": "اشتراک مورد نظر یافت نشد."}), 404

    sub = dict(sub_row)
    history = db.get_portal_chat_history(sub["id"], telegram_id=sub.get("telegram_id"), portal_token=token)
    return jsonify({
        "success": True,
        "history": history
    })


@app.route("/api/portal/<token>/chat/messages/<int:ticket_id>", methods=["GET"])
def api_portal_chat_messages(token: str, ticket_id: int):
    """دریافت پیام‌های یک گفتگوی مشخص"""
    conn = db.get_connection()
    sub_row = conn.execute("SELECT * FROM subscriptions WHERE hidify_uuid=? OR id=?", (token, token)).fetchone()
    conn.close()

    if not sub_row:
        return jsonify({"success": False, "error": "اشتراک مورد نظر یافت نشد."}), 404

    sub = dict(sub_row)
    ticket = db.get_portal_ticket(ticket_id, subscription_id=sub["id"], portal_token=token)
    if not ticket:
        return jsonify({"success": False, "error": "گفتگوی مورد نظر یافت نشد."}), 404

    messages = db.get_ticket_messages(ticket_id)
    return jsonify({
        "success": True,
        "ticket": ticket,
        "messages": messages
    })


@app.route("/api/portal/<token>/chat/start", methods=["POST"])
def api_portal_chat_start(token: str):
    """شروع گفتگوی جدید آنلاین توسط مشتری با انتخاب موضوع، نام و شماره تماس"""
    conn = db.get_connection()
    sub_row = conn.execute("SELECT * FROM subscriptions WHERE hidify_uuid=? OR id=?", (token, token)).fetchone()
    conn.close()

    if not sub_row:
        return jsonify({"success": False, "error": "اشتراک مورد نظر یافت نشد."}), 404

    sub = dict(sub_row)
    data = request.get_json(silent=True) or request.form.to_dict() or {}
    subject = (data.get("subject") or "پیام آنلاین مشتری از پرتال").strip()
    name = (data.get("name") or sub.get("account_name") or f"مشتری #{sub['id']}").strip()
    phone = (data.get("phone") or sub.get("phone_number") or "").strip()
    message_text = (data.get("message") or "").strip()

    if not message_text:
        return jsonify({"success": False, "error": "لطفاً متن پیام خود را وارد نمایید."}), 400

    sub_id = sub["id"]
    reseller_id = sub.get("reseller_id") or 0
    tg_id = sub.get("telegram_id") or sub_id

    if phone and not sub.get("phone_number"):
        try:
            conn = db.get_connection()
            conn.execute("UPDATE subscriptions SET phone_number=? WHERE id=?", (phone, sub_id))
            conn.commit()
            conn.close()
        except Exception:
            pass

    res = db.create_portal_chat_ticket(
        subscription_id=sub_id,
        customer_name=name,
        customer_phone=phone,
        subject=subject,
        initial_message=message_text,
        portal_token=token,
        reseller_id=reseller_id,
        telegram_id=tg_id
    )

    if not res.get("success"):
        return jsonify({"success": False, "error": res.get("error", "خطا در ایجاد گفتگو")}), 500

    ticket_id = res["ticket_id"]

    try:
        notif_msg = (
            f"💬 <b>گفتگوی آنلاین جدید در پورتال مشتری!</b>\n\n"
            f"🎫 شماره تیکت: <b>#{ticket_id}</b>\n"
            f"👤 مشتری: <b>{name}</b> (اشتراک #{sub_id})\n"
            f"🔖 موضوع: <b>{subject}</b>\n"
            + (f"📱 شماره تماس: <code>{phone}</code>\n" if phone else "")
            + f"📝 پیام مشتری:\n{message_text}\n"
            f"⏰ زمان: {get_now_shamsi()}\n\n"
            f"💡 پاسخگویی از طریق میز کار وب یا دستور <code>/reply_ticket {ticket_id} متن پاسخ</code>"
        )
        if reseller_id:
            r_info = db.get_reseller(reseller_id) or {}
            r_tg = r_info.get("telegram_id")
            if r_tg:
                r_bot_token = r_info.get("bot_token")
                r_kb = {
                    "inline_keyboard": [
                        [
                            {"text": "✍️ پاسخ متنی", "callback_data": f"res_reply_tkt_{ticket_id}"},
                            {"text": "⚡ پاسخ‌های آماده", "callback_data": f"res_canned_tkt_{ticket_id}"}
                        ],
                        [
                            {"text": "🔒 بستن تیکت", "callback_data": f"res_close_tkt_{ticket_id}"}
                        ]
                    ]
                }
                send_telegram_msg(r_tg, notif_msg, reply_markup=r_kb, bot_token=r_bot_token)
        else:
            admin_tg = db.get_setting("admin_telegram_id") or get_admin_id()
            if admin_tg:
                adm_kb = {
                    "inline_keyboard": [
                        [
                            {"text": "✍️ پاسخ متنی", "callback_data": f"adm_reply_tkt_{ticket_id}"},
                            {"text": "⚡ پاسخ‌های آماده", "callback_data": f"adm_canned_tkt_{ticket_id}"}
                        ],
                        [
                            {"text": "🔒 بستن تیکت", "callback_data": f"adm_close_tkt_{ticket_id}"}
                        ]
                    ]
                }
                send_telegram_msg(int(admin_tg), notif_msg, reply_markup=adm_kb)
    except Exception as e_notif:
        logger.warning(f"Failed to notify of new portal chat: {e_notif}")

    chat_cfg = db.get_chat_settings()
    if chat_cfg.get("chat_ai_enabled"):
        try:
            ai_msg1 = "پیام شما دریافت شد و به پشتیبانی مربوط به مشکل خودتون ارسال کردم و بزودی پشتیبان پاسخ شمارو خواهد داد"
            ai_msg2 = "من هوش مصنوعی هستم آیا مایلید مشکلتون رو حل کنم؟"
            db.add_ticket_message(ticket_id, sender_type="ai", sender_name="هوش مصنوعی", message=ai_msg1, new_status="open")
            db.add_ticket_message(ticket_id, sender_type="ai", sender_name="هوش مصنوعی", message=ai_msg2, new_status="open")
        except Exception as e_ai_init:
            logger.warning(f"Error adding initial AI messages: {e_ai_init}")

    ticket = db.get_portal_ticket(ticket_id, subscription_id=sub_id, portal_token=token)
    messages = db.get_ticket_messages(ticket_id)

    return jsonify({
        "success": True,
        "ticket_id": ticket_id,
        "ticket": ticket,
        "messages": messages,
        "message": "گفتگوی شما با موفقیت ثبت شد و کارشناس پشتیبانی به زودی پاسخ خواهد داد."
    })


@app.route("/api/portal/<token>/chat/send", methods=["POST"])
def api_portal_chat_send(token: str):
    """ارسال پیام بعدی توسط مشتری در گفتگوی جاری"""
    conn = db.get_connection()
    sub_row = conn.execute("SELECT * FROM subscriptions WHERE hidify_uuid=? OR id=?", (token, token)).fetchone()
    conn.close()

    if not sub_row:
        return jsonify({"success": False, "error": "اشتراک مورد نظر یافت نشد."}), 404

    sub = dict(sub_row)
    data = request.get_json(silent=True) or request.form.to_dict() or {}
    ticket_id = data.get("ticket_id")
    message_text = (data.get("message") or "").strip()
    name = (data.get("name") or sub.get("account_name") or "مشتری").strip()

    if not ticket_id:
        return jsonify({"success": False, "error": "شناسه گفتگو الزامی است."}), 400
    if not message_text:
        return jsonify({"success": False, "error": "متن پیام نمی‌تواند خالی باشد."}), 400

    try:
        ticket_id = int(ticket_id)
    except ValueError:
        return jsonify({"success": False, "error": "شناسه گفتگو نامعتبر است."}), 400

    sub_id = sub["id"]
    res = db.add_portal_user_message(
        ticket_id=ticket_id,
        subscription_id=sub_id,
        message=message_text,
        customer_name=name
    )

    if not res.get("success"):
        return jsonify({"success": False, "error": res.get("error", "خطا در ارسال پیام")}), 400

    try:
        reseller_id = sub.get("reseller_id") or 0
        notif_msg = (
            f"📩 <b>پیام جدید مشتری در گفتگوی آنلاین #{ticket_id}</b>\n\n"
            f"👤 از طرف: <b>{name}</b> (اشتراک #{sub_id})\n"
            f"💬 متن پیام:\n{message_text}\n"
            f"⏰ {get_now_shamsi()}\n\n"
            f"💡 پاسخ سریع با: <code>/reply_ticket {ticket_id} متن پاسخ</code>"
        )
        if reseller_id:
            r_info = db.get_reseller(reseller_id) or {}
            r_tg = r_info.get("telegram_id")
            if r_tg:
                r_bot_token = r_info.get("bot_token")
                r_kb = {
                    "inline_keyboard": [
                        [
                            {"text": "✍️ پاسخ متنی", "callback_data": f"res_reply_tkt_{ticket_id}"},
                            {"text": "⚡ پاسخ‌های آماده", "callback_data": f"res_canned_tkt_{ticket_id}"}
                        ],
                        [
                            {"text": "🔒 بستن تیکت", "callback_data": f"res_close_tkt_{ticket_id}"}
                        ]
                    ]
                }
                send_telegram_msg(r_tg, notif_msg, reply_markup=r_kb, bot_token=r_bot_token)
        else:
            admin_tg = db.get_setting("admin_telegram_id") or get_admin_id()
            if admin_tg:
                adm_kb = {
                    "inline_keyboard": [
                        [
                            {"text": "✍️ پاسخ متنی", "callback_data": f"adm_reply_tkt_{ticket_id}"},
                            {"text": "⚡ پاسخ‌های آماده", "callback_data": f"adm_canned_tkt_{ticket_id}"}
                        ],
                        [
                            {"text": "🔒 بستن تیکت", "callback_data": f"adm_close_tkt_{ticket_id}"}
                        ]
                    ]
                }
                send_telegram_msg(int(admin_tg), notif_msg, reply_markup=adm_kb)
    except Exception as e_notif:
        logger.warning(f"Failed to notify of chat user message: {e_notif}")

    ai_reply_data = None
    chat_cfg = db.get_chat_settings()
    if chat_cfg.get("chat_ai_enabled"):
        # بررسی عدم پاسخگویی یا دخالت پشتیبان انسانی (در صورت پاسخ پشتیبان، هوش مصنوعی ادامه نمی‌دهد)
        if not db.has_human_support_replied(ticket_id):
            ai_text = db.generate_ai_chat_reply(ticket_id, message_text, sub_info=sub)
            if ai_text:
                ai_res = db.add_ticket_message(
                    ticket_id=ticket_id,
                    sender_type="ai",
                    sender_name="هوش مصنوعی",
                    message=ai_text,
                    new_status="open"
                )
                if ai_res.get("success"):
                    ai_reply_data = {
                        "id": ai_res.get("message_id"),
                        "sender_type": "ai",
                        "sender_name": "هوش مصنوعی",
                        "message": ai_text,
                        "created_at": get_now_iso()
                    }

    return jsonify({
        "success": True,
        "message_id": res.get("message_id"),
        "ai_reply": ai_reply_data,
        "ticket_id": ticket_id
    })


@app.route("/api/portal/<token>/chat/poll", methods=["GET"])
def api_portal_chat_poll(token: str):
    """بررسی دوره‌ای پیام‌های جدید دریافتی از پشتیبان برای هشدار صوتی و نوتیفیکیشن"""
    conn = db.get_connection()
    sub_row = conn.execute("SELECT * FROM subscriptions WHERE hidify_uuid=? OR id=?", (token, token)).fetchone()
    conn.close()

    if not sub_row:
        return jsonify({"success": False, "error": "اشتراک مورد نظر یافت نشد."}), 404

    sub = dict(sub_row)
    sub_id = sub["id"]

    raw_ticket_id = request.args.get("ticket_id")
    raw_last_msg_id = request.args.get("last_msg_id", 0)

    try:
        ticket_id = int(raw_ticket_id) if raw_ticket_id else None
    except ValueError:
        ticket_id = None

    try:
        last_msg_id = int(raw_last_msg_id)
    except ValueError:
        last_msg_id = 0

    poll_result = db.poll_portal_ticket_updates(
        subscription_id=sub_id,
        ticket_id=ticket_id,
        last_msg_id=last_msg_id
    )

    reseller_id = sub.get("reseller_id") or 0
    support_status_info = db.is_support_online_for_sub(sub_id, reseller_id=reseller_id)

    return jsonify({
        "success": True,
        "support_status": support_status_info["status"],
        "support_is_online": support_status_info["is_online"],
        "support_name": support_status_info["support_name"],
        "support_status_text": support_status_info["status_text"],
        **poll_result
    })


@app.route("/api/portal/<token>/support-message", methods=["POST"])
def api_portal_support_message(token: str):
    """سازگاری با ای‌پی‌آی قدیمی ثبت پیام با ارجاع به شروع گفتگوی آنلاین"""
    return api_portal_chat_start(token)


@app.route("/admin/subscription/<int:sub_id>/send_renewal_link", methods=["POST"])
@admin_required
def admin_send_renewal_link(sub_id: int):
    """ارسال لینک پورتال دائمی و تمدید اختصاصی به تلگرام و پیامک مشتری توسط مدیریت"""
    sub = db.get_subscription(sub_id)
    if not sub:
        flash("اشتراک مورد نظر یافت نشد.", "danger")
        return redirect(request.referrer or url_for("subscriptions"))

    token = sub.get("hidify_uuid") or str(sub["id"])
    portal_url = get_customer_portal_url(token, _external=True)
    account_name = sub.get("account_name") or "کاربر گرامی"

    sent_channels = []

    # ارسال از طریق تلگرام
    tg_id = None
    try:
        if sub.get("telegram_id"):
            tg_id = int(sub["telegram_id"])
    except (ValueError, TypeError):
        tg_id = None

    if tg_id:
        tg_text = (
            f"سلام <b>{account_name}</b> عزیز 🌸\n\n"
            f"🔗 <b>لینک اختصاصی و دائمی اشتراک شما:</b>\n"
            f"<code>{portal_url}</code>\n\n"
            f"📊 از طریق این صفحه اختصاصی می‌توانید در هر لحظه وضعیت حجم مصرفی، روزهای باقی‌مانده، لینک‌ها و بارکدهای اتصال و همچنین تمدید آنلاین خودکار سرویس را مشاهده فرمایید."
        )
        markup = {
            "inline_keyboard": [
                [{"text": "🌐 ورود به پورتال و تمدید آنلاین", "url": portal_url}]
            ]
        }
        if send_telegram_msg(tg_id, tg_text, reply_markup=markup):
            sent_channels.append("تلگرام")

    # ارسال از طریق پیامک
    phone = sub.get("phone_number")
    if phone:
        sms_text = (
            f"کاربر گرامی {account_name}\n"
            f"جهت مشاهده وضعیت اشتراک، لینک‌های اتصال و تمدید آنلاین به لینک زیر مراجعه فرمایید:\n"
            f"{portal_url}"
        )
        ok, _ = send_sms(receptor=phone, message=sms_text, db_instance=db)
        if ok:
            sent_channels.append("پیامک")

    if sent_channels:
        flash(f"✅ لینک پورتال اختصاصی با موفقیت از طریق {' و '.join(sent_channels)} برای {account_name} ارسال شد.", "success")
    else:
        flash(f"⚠️ برای مشتری «{account_name}» شماره موبایل یا آیدی تلگرام فعالی ثبت نشده است. لطفاً لینک را دستی کپی نمایید.", "warning")

    return redirect(request.referrer or url_for("subscriptions"))


@app.route("/reseller/subscription/<int:sub_id>/send_renewal_link", methods=["POST"])
@reseller_required
def reseller_send_renewal_link(sub_id: int):
    """ارسال لینک پورتال دائمی و تمدید اختصاصی به تلگرام و پیامک مشتری توسط نماینده"""
    reseller_id = session.get("reseller_id")
    sub = db.get_reseller_subscription(reseller_id, sub_id)
    if not sub:
        flash("اشتراک مورد نظر یافت نشد یا متعلق به شما نیست.", "danger")
        return redirect(request.referrer or url_for("reseller_users"))

    r_info = db.get_reseller(reseller_id) or {}
    brand_title = r_info.get("brand_title") or r_info.get("name") or "پشتیبانی اینترنت"
    custom_domain = r_info.get("domain")

    token = sub.get("hidify_uuid") or str(sub["id"])
    proxy_path = get_portal_proxy_path()
    if custom_domain:
        portal_url = f"https://{custom_domain}/{proxy_path}/{token}"
    else:
        portal_url = get_customer_portal_url(token, _external=True)

    account_name = sub.get("account_name") or "کاربر گرامی"
    sent_channels = []

    # ارسال تلگرام با ربات اختصاصی نماینده
    tg_id = None
    try:
        if sub.get("telegram_id"):
            tg_id = int(sub["telegram_id"])
    except (ValueError, TypeError):
        tg_id = None

    if tg_id:
        bot_token = r_info.get("bot_token")
        tg_text = (
            f"سلام <b>{account_name}</b> عزیز 🌸\n\n"
            f"🔗 <b>لینک اختصاصی و دائمی اشتراک شما ({brand_title}):</b>\n"
            f"<code>{portal_url}</code>\n\n"
            f"📊 از طریق این صفحه اختصاصی می‌توانید در هر لحظه وضعیت مصرف، روزهای باقی‌مانده و تمدید آنلاین سرویس خود را مدیریت نمایید."
        )
        markup = {
            "inline_keyboard": [
                [{"text": "🌐 ورود به پورتال و تمدید آنلاین", "url": portal_url}]
            ]
        }
        if send_telegram_msg(tg_id, tg_text, reply_markup=markup, bot_token=bot_token):
            sent_channels.append("تلگرام")

    # ارسال پیامک
    phone = sub.get("phone_number")
    if phone:
        sms_text = (
            f"کاربر گرامی {account_name} ({brand_title})\n"
            f"جهت استعلام وضعیت و تمدید آنلاین اشتراک به لینک اختصاصی زیر مراجعه فرمایید:\n"
            f"{portal_url}"
        )
        ok, _ = send_sms(receptor=phone, message=sms_text, db_instance=db)
        if ok:
            sent_channels.append("پیامک")

    if sent_channels:
        flash(f"✅ لینک پورتال با موفقیت از طریق {' و '.join(sent_channels)} برای {account_name} ارسال شد.", "success")
    else:
        flash(f"⚠️ برای مشتری «{account_name}» شماره موبایل یا آیدی تلگرام ثبت نشده است. لطفاً لینک را دستی کپی نمایید.", "warning")

    return redirect(request.referrer or url_for("reseller_users"))


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

    # پاکسازی خودکار ۷ روزه اشتراک‌های سطل زباله از هیدیفای در پس‌زمینه
    def _run_periodic_purge():
        try:
            purged = db.purge_expired_deleted_subscriptions(hidify_sync_delete_user)
            if purged > 0:
                logger.info(f"Purged {purged} expired subscriptions from Hiddify")
        except Exception as ex:
            logger.error(f"Error in 7-day purge task: {ex}")

    try:
        threading.Thread(target=_run_periodic_purge, daemon=True, name="PurgeExpiredSubs").start()
    except Exception:
        pass

    app.run(host=host, port=port, debug=debug, use_reloader=False)


def start_dashboard_thread():
    """اجرای داشبورد در thread جداگانه هنگام استارت بات"""
    import threading
    t = threading.Thread(target=run_dashboard, daemon=True)
    t.start()
    return t


if __name__ == "__main__":
    run_dashboard(debug=True)
