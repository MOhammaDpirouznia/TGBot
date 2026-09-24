# -*- coding: utf-8 -*-
"""
🚀 Customer Portal UI Studio - Local Preview Server
سرور پیش‌نمایش ایزوله و کامل پرتال مشتری با قابلیت تغییر پالت، چیدمان و استایل‌ها
با شبیه‌سازی کامل باشگاه مشتریان (گردونه و ماموریت‌ها)، نمودار تحلیل مصرف ساعتی/روزانه/ماهانه،
ابزارهای اتصال و بارکد QR، و ترکیب آزادانه هر چیدمان با هر استایل دکمه
"""

import os
import sys
import time
import io
from pathlib import Path
from datetime import datetime, timedelta
from flask import Flask, render_template, request, session, redirect, jsonify, send_from_directory, Response
import jinja2

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

app = Flask(
    __name__,
    template_folder=str(TEMPLATES_DIR),
    static_folder=str(STATIC_DIR)
)
app.secret_key = "customer-portal-studio-2026"

# لود ماژول پالت‌ها
from palette_manager import get_palette, get_all_palettes, generate_palette_css

# کلاس SafeUndefined کامل برای جلوگیری از خطای متغیرهای ناموجود
class SafeUndefined(jinja2.ChainableUndefined):
    def __call__(self, *args, **kwargs): return SafeUndefined()
    def __getattr__(self, name): return SafeUndefined()
    def __getitem__(self, key): return SafeUndefined()
    def __str__(self): return ""
    def __repr__(self): return ""
    def __html__(self): return ""
    def __iter__(self): return iter([])
    def __bool__(self): return False
    def __int__(self): return 0
    def __float__(self): return 0.0
    def __format__(self, spec):
        try:
            return format(0, spec)
        except Exception:
            return ""
    def get(self, *args, **kwargs):
        if len(args) > 1:
            return args[1]
        return SafeUndefined()
    def items(self): return []
    def keys(self): return []
    def values(self): return []
    def startswith(self, *args): return False
    def endswith(self, *args): return False
    def split(self, *args): return []
    def strip(self, *args): return ""
    def lower(self): return ""
    def upper(self): return ""
    def __abs__(self): return 0
    def __round__(self, *args): return 0
    def __neg__(self): return 0
    def __pos__(self): return 0
    def __len__(self): return 0
    def __add__(self, other):
        if isinstance(other, (int, float, str)):
            return other
        return self
    def __radd__(self, other):
        if isinstance(other, (int, float, str)):
            return other
        return self
    def __sub__(self, other): return 0
    def __rsub__(self, other): return 0
    def __mul__(self, other): return 0
    def __rmul__(self, other): return 0
    def __truediv__(self, other): return 0
    def __rtruediv__(self, other): return 0
    def __contains__(self, item): return False
    def __eq__(self, other): return False
    def __ne__(self, other): return True
    def __lt__(self, other): return False
    def __le__(self, other): return False
    def __gt__(self, other): return False
    def __ge__(self, other): return False

app.jinja_env.undefined = SafeUndefined

# فیلترهای استاندارد فارسی
PERSIAN_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
def to_fa_digits(val):
    return str(val).translate(PERSIAN_DIGITS) if val is not None else ""

app.jinja_env.filters["persian_digits"] = lambda v, *a, **k: to_fa_digits(v)
app.jinja_env.filters["to_persian_digits"] = lambda v, *a, **k: to_fa_digits(v)
app.jinja_env.filters["shamsi_date"] = lambda v, *a, **k: "۱۴۰۴/۰۸/۱۵"
app.jinja_env.filters["format_shamsi_date"] = lambda v, *a, **k: "۱۴۰۴/۰۸/۱۵"
app.jinja_env.filters["activity_time"] = lambda v, *a, **k: "۱۰ دقیقه پیش"
app.jinja_env.filters["format_activity_time"] = lambda v, *a, **k: "۱۰ دقیقه پیش"
app.jinja_env.filters["diff_time"] = lambda v, *a, **k: "۲ ساعت پیش"
app.jinja_env.filters["format_diff_time"] = lambda v, *a, **k: "۲ ساعت پیش"
app.jinja_env.filters["avatar_url"] = lambda v, *a, **k: "/static/images/Logo.webp"
app.jinja_env.filters["format_single_link"] = lambda v, *a, **k: "vless://sample-uuid@127.0.0.1:443?security=tls#SampleServer"
app.jinja_env.filters["happ_url"] = lambda v, *a, **k: "happ://sample-link"
app.jinja_env.filters["format_happ_url"] = lambda v, *a, **k: "happ://sample-link"
app.jinja_env.filters["gateway_name"] = lambda v, *a, **k: "درگاه پرداخت امن شتابی"
app.jinja_env.filters["format_gateway_name"] = lambda v, *a, **k: "درگاه پرداخت امن شتابی"
app.jinja_env.filters["reviewer_name"] = lambda v, *a, **k: "پشتیبانی"
app.jinja_env.filters["format_reviewer"] = lambda v, *a, **k: "پشتیبانی"
app.jinja_env.filters["gregorian_clean"] = lambda v, *a, **k: "2026-09-24"
app.jinja_env.filters["format_gregorian_clean"] = lambda v, *a, **k: "2026-09-24"
app.jinja_env.filters["last_connection_display"] = lambda v, *a, **k: "آنلاین (۵ دقیقه پیش)"
app.jinja_env.filters["format_last_connection_display"] = lambda v, *a, **k: "آنلاین (۵ دقیقه پیش)"
app.jinja_env.filters["field_display_name"] = lambda v, *a, **k: str(v) if v else ""

# تابع تولید استایل و آیکون کارت‌های بسته‌ها
def get_plan_icon(plan=None, plan_id=None):
    p = plan or {}
    name = str(p.get("name", "")).lower()
    pid = str(plan_id or p.get("id", ""))
    
    if "اقتصادی" in name or pid == "1":
        return {
            "icon": "fas fa-bolt",
            "color_hex": "#3b82f6",
            "bg_color": "rgba(59, 130, 246, 0.15)",
            "border_color": "rgba(59, 130, 246, 0.35)",
            "bg_class": "avatar-primary"
        }
    elif "طلایی" in name or "vip" in name or pid == "2":
        return {
            "icon": "fas fa-crown",
            "color_hex": "#f59e0b",
            "bg_color": "rgba(245, 158, 11, 0.15)",
            "border_color": "rgba(245, 158, 11, 0.35)",
            "bg_class": "avatar-warning"
        }
    elif "نامحدود" in name or "سرعتی" in name or pid == "3":
        return {
            "icon": "fas fa-rocket",
            "color_hex": "#8b5cf6",
            "bg_color": "rgba(139, 92, 246, 0.15)",
            "border_color": "rgba(139, 92, 246, 0.35)",
            "bg_class": "avatar-info"
        }
    elif "پرو" in name or "خانوادگی" in name or pid == "4":
        return {
            "icon": "fas fa-shield-halved",
            "color_hex": "#10b981",
            "bg_color": "rgba(16, 185, 129, 0.15)",
            "border_color": "rgba(16, 185, 129, 0.35)",
            "bg_class": "avatar-success"
        }
    return {
        "icon": "fas fa-shield-alt",
        "color_hex": "#06b6d4",
        "bg_color": "rgba(6, 182, 212, 0.15)",
        "border_color": "rgba(6, 182, 212, 0.35)",
        "bg_class": "avatar-secondary"
    }

app.jinja_env.globals["get_plan_icon"] = get_plan_icon
app.jinja_env.filters["get_plan_icon"] = get_plan_icon
app.jinja_env.globals["avatar_url"] = lambda *a, **k: "/static/images/Logo.webp"

def mock_url_for(endpoint, **kwargs):
    if endpoint in ("customer_portal", "portal", "telegram_webapp"):
        q = {}
        for k in ["layout", "plan_style", "palette", "state", "invoice_mode", "sub_mode"]:
            if request.args.get(k):
                q[k] = request.args.get(k)
        for k, v in kwargs.items():
            if k == "token":
                q["sub_id"] = v
            else:
                q[k] = v
        qs = "&".join(f"{k}={v}" for k, v in q.items())
        return f"/portal?{qs}" if qs else "/portal"
    elif endpoint in ("customer_create_invoice", "customer_buy_new_plan"):
        return "/create_invoice"
    elif endpoint == "customer_cancel_invoice":
        return "/cancel_invoice"
    return "#"

app.jinja_env.globals["url_for"] = mock_url_for
app.jinja_env.globals["get_customer_portal_url"] = lambda token="", _external=False: f"/portal?sub_id={token}" if token else "/portal"

# داده‌های ساختگی کامل و کاملاً امن (Sanitized Mock Data)
MOCK_PLANS = [
    {"id": 1, "name": "اشتراک ۱ ماهه اقتصادی", "price": 120000, "data_limit": 30, "duration": 30, "traffic_gb": 30, "days": 30, "is_active": 1, "user_limit": 2, "description": "مناسب وبگردی و شبکه‌های اجتماعی"},
    {"id": 2, "name": "اشتراک ۱ ماهه طلایی (VIP)", "price": 190000, "data_limit": 60, "duration": 30, "traffic_gb": 60, "days": 30, "is_active": 1, "user_limit": 2, "description": "پرسرعت‌ترین سرورها بدون قطعی مخصوص استریم"},
    {"id": 3, "name": "اشتراک ۲ ماهه نامحدود سرعتی", "price": 350000, "data_limit": 120, "duration": 60, "traffic_gb": 120, "days": 60, "is_active": 1, "user_limit": 3, "description": "ترافیک بالا با پینگ پایین مناسب گیم و ویدیو"},
    {"id": 4, "name": "اشتراک ۳ ماهه پرو خانوادگی", "price": 490000, "data_limit": 200, "duration": 90, "traffic_gb": 200, "days": 90, "is_active": 1, "user_limit": 4, "description": "حجم زیاد و به صرفه برای استفاده چند دستگاه"},
]

MOCK_PAYMENT_METHODS = [
    {
        "id": "online_gateway",
        "title": "درگاه پرداخت امن شتابی",
        "badge": "پرداخت آنی",
        "badge_class": "bg-success",
        "desc": "پرداخت با کلیه کارت‌های عضو شبکه شتاب با تایید لحظه‌ای",
        "icon": "fas fa-shield-alt",
        "color": "success",
        "btn_text": "ورود به درگاه پرداخت بانکی"
    },
    {
        "id": "card_to_card",
        "title": "کارت به کارت (رسید دیجیتال)",
        "badge": "تایید سریع",
        "badge_class": "bg-primary",
        "desc": "واریز کارت به کارت هوشمند با تایید خودکار پیامک بانک",
        "icon": "fas fa-credit-card",
        "color": "primary",
        "btn_text": "صدور فاکتور کارت به کارت هوشمند"
    },
    {
        "id": "crypto",
        "title": "پرداخت تتری (USDT)",
        "badge": "TRC-20",
        "badge_class": "bg-warning text-dark",
        "desc": "پرداخت خودکار با رمزارز تتر بدون نیاز به کارت بانکی",
        "icon": "fab fa-bitcoin",
        "color": "warning",
        "btn_text": "پرداخت با رمزارز"
    }
]

MOCK_USER_SUBSCRIPTIONS = [
    {
        "id": "sub_mobile",
        "hidify_uuid": "sub_mobile",
        "account_name": "📱 اشتراک موبایل (آیفون)",
        "remaining_days": 18,
        "duration": 30,
        "traffic_limit": 50,
        "traffic_limit_display": "۵۰ گیگ",
        "remaining_traffic_gb": 34.2,
        "data_used": 15.8,
        "status": "active"
    },
    {
        "id": "sub_laptop",
        "hidify_uuid": "sub_laptop",
        "account_name": "💻 اشتراک لپ‌تاپ (ویندوز)",
        "remaining_days": 26,
        "duration": 30,
        "traffic_limit": 100,
        "traffic_limit_display": "۱۰۰ گیگ",
        "remaining_traffic_gb": 87.5,
        "data_used": 12.5,
        "status": "active"
    }
]

AVATAR_PRESETS = [
    {"id": "gamer", "name": "گیمر"},
    {"id": "pro", "name": "حرفه‌ای"},
    {"id": "cyber", "name": "سایبری"},
    {"id": "vip", "name": "وی‌آی‌پی"},
    {"id": "minimal", "name": "مینیمال"},
    {"id": "bot", "name": "ربات"}
]

# ماموریت‌های باشگاه مشتریان
MOCK_SOCIAL_TASKS = [
    {
        "id": 1,
        "title": "عضویت در کانال اطلاع‌رسانی تلگرام",
        "description": "عضویت در کانال رسمی جهت دریافت آدرس‌های بدون فیلتر و اخبار سرورها",
        "task_type": "telegram_channel",
        "reward_type": "traffic",
        "reward_value": 2.0,
        "status": "pending",
        "action_url": "https://t.me/CloudOfficial"
    },
    {
        "id": 2,
        "title": "دعوت از ۳ نفر از دوستان",
        "description": "معرفی سرویس به دوستان با کد تخفیف و دریافت پاداش نقدی",
        "task_type": "referral",
        "reward_type": "wallet",
        "reward_value": 30000,
        "status": "in_progress",
        "action_url": "#tab-club-ref-pane"
    },
    {
        "id": 3,
        "title": "ثبت نظر و امتیاز رضایت",
        "description": "ارسال نظر درباره کیفیت پینگ و پایداری سرورها در کانال پشتیبانی",
        "task_type": "review",
        "reward_type": "discount",
        "reward_value": 15,
        "status": "completed"
    }
]


@app.route("/")
def index():
    active_palette = request.args.get("palette") or session.get("active_palette", "vps_aurora")
    session["active_palette"] = active_palette
    pal_data = get_palette(active_palette)
    pal_list = list(get_all_palettes().values())
    return render_template(
        "index.html",
        all_palettes=pal_list,
        active_palette=active_palette,
        active_palette_name=pal_data.get("name", "وی‌پی‌اس اورورا")
    )


@app.route("/portal")
def view_portal():
    layout = request.args.get("layout", "bento_grid")
    plan_style = request.args.get("plan_style", "glass_classic")
    state = request.args.get("state", "vip")
    sub_mode = request.args.get("sub_mode", "multi")  # single or multi
    selected_palette = request.args.get("palette") or session.get("active_palette", "vps_aurora")
    session["active_palette"] = selected_palette
    
    # تعیین دستگاه و اشتراک فعال (موبایل یا لپ‌تاپ)
    sub_id = request.args.get("sub_id") or request.args.get("token") or "sub_mobile"
    if "laptop" in str(sub_id).lower():
        active_device = "laptop"
        active_token = "sub_laptop"
    else:
        active_device = "mobile"
        active_token = "sub_mobile"

    # تنظیم پالت رنگی
    pal_data = get_palette(selected_palette)
    palette_css = generate_palette_css({"data": pal_data, "intensity": "normal", "animation": "float"})

    # تزریق استایل اختصاصی طراح (designer-custom.css)
    custom_designer_css = ""
    custom_css_file = STATIC_DIR / "designer-custom.css"
    if custom_css_file.exists():
        custom_designer_css = custom_css_file.read_text(encoding="utf-8")
    
    full_css = palette_css + "\n\n" + custom_designer_css

    # لینک‌های اشتراک و کانفیگ تکی
    sub_url = f"https://sub.cloud-edge.net/token-{active_device}-vip"
    single_url = f"vless://b63892a0-4a81-4279-88c2-edge443@127.0.0.1:443?security=tls&encryption=none&type=ws&host=demo.cloud#{active_device.capitalize()}-IranEdge"

    # آماده‌سازی دیتاست کامل نمودار هوشمند ترافیک (۲۴ ساعت، ۷ روز و ۳۰ روز)
    now_ts = int(time.time())
    fa_days = ["شنبه", "یک‌شنبه", "دوشنبه", "سه‌شنبه", "چهارشنبه", "پنج‌شنبه", "جمعه"]

    hourly_24h = []
    for i in range(24):
        hour_ts = now_ts - (23 - i) * 3600
        dt = datetime.fromtimestamp(hour_ts)
        lbl = f"{dt.hour:02d}:00"
        is_peak = (19 <= dt.hour <= 22)
        if active_device == "laptop":
            mb = (350 + (i * 35 % 420)) if is_peak else ((25 + (i * 9 % 30)) if dt.hour < 7 else (120 + (i * 22 % 160)))
        else:
            mb = (190 + (i * 18 % 180)) if is_peak else ((15 + (i * 5 % 20)) if dt.hour < 7 else (65 + (i * 14 % 85)))

        hourly_24h.append({
            "timestamp": hour_ts,
            "local_hour": dt.hour,
            "label": lbl,
            "usage_mb": mb,
            "is_peak": is_peak,
            "is_current": (i == 23)
        })

    daily_7d = [
        {"day_name": fa_days[0], "jalali_date": "۱۴۰۴/۰۸/۱۰", "usage_mb": 2150 if active_device == "mobile" else 4850, "is_peak": False, "is_today": False},
        {"day_name": fa_days[1], "jalali_date": "۱۴۰۴/۰۸/۱۱", "usage_mb": 3480 if active_device == "mobile" else 6200, "is_peak": True, "is_today": False},
        {"day_name": fa_days[2], "jalali_date": "۱۴۰۴/۰۸/۱۲", "usage_mb": 1820 if active_device == "mobile" else 5100, "is_peak": False, "is_today": False},
        {"day_name": fa_days[3], "jalali_date": "۱۴۰۴/۰۸/۱۳", "usage_mb": 4210 if active_device == "mobile" else 7950, "is_peak": True, "is_today": False},
        {"day_name": fa_days[4], "jalali_date": "۱۴۰۴/۰۸/۱۴", "usage_mb": 2930 if active_device == "mobile" else 4300, "is_peak": False, "is_today": False},
        {"day_name": fa_days[5], "jalali_date": "۱۴۰۴/۰۸/۱۵", "usage_mb": 3100 if active_device == "mobile" else 5800, "is_peak": False, "is_today": False},
        {"day_name": fa_days[6], "jalali_date": "۱۴۰۴/۰۸/۱۶", "usage_mb": 1050 if active_device == "mobile" else 2400, "is_peak": False, "is_today": True}
    ]

    daily_30d = []
    for d in range(30):
        factor = 1.8 if active_device == "laptop" else 1.0
        day_mb = int((1100 + ((d * 147) % 2700)) * factor)
        daily_30d.append({
            "day_name": fa_days[d % 7],
            "jalali_date": f"۱۴۰۴/۰۷/{30 - d:02d}" if d < 15 else f"۱۴۰۴/۰۸/{d - 14:02d}",
            "usage_mb": day_mb,
            "is_peak": (day_mb > 3200 * factor),
            "is_today": (d == 29)
        })

    weekly_chart = {
        "bento1": {"area": "M0,45 Q30,25 60,35 T120,15 T180,28 T240,10 L240,50 L0,50 Z", "path": "M0,45 Q30,25 60,35 T120,15 T180,28 T240,10", "peak_x": 240, "peak_y": 10},
        "bento3": {"area": "M0,50 Q40,30 80,40 T160,20 T240,30 L240,60 L0,60 Z", "path": "M0,50 Q40,30 80,40 T160,20 T240,30", "peak_x": 160, "peak_y": 20},
        "peak_text_formatted": "اوج مصرف: ۴.۲ گیگ" if active_device == "mobile" else "اوج مصرف: ۷.۹ گیگ"
    }

    # داده‌های کاربر بر اساس حالت انتخابی
    if state == "new":
        is_new = True
        sub_data = SafeUndefined()
        days_left = 0
        remain_gb = 0
        analytics = {
            "total_gb": 0, "used_gb": 0, "remain_gb": 0, "percent": 0,
            "daily_avg_gb": 0, "peak_hour": "—", "day_pct": 0, "night_pct": 0, "estimated_days_left": "۰ روز",
            "hourly_24h": [], "daily_7d": [], "daily_30d": [], "weekly_chart": {}
        }
    elif state == "debt":
        is_new = False
        days_left = 0
        remain_gb = 0.5
        sub_data = {
            "id": 103,
            "hidify_uuid": active_token,
            "account_name": "کاربر گرامی (بدهکار / منقضی)",
            "phone_number": "09121234567",
            "telegram_id": 987654321,
            "telegram_username": "demo_user",
            "status": "expired",
            "data_limit": 30.0,
            "data_used": 29.5,
            "remaining_traffic_gb": 0.5,
            "traffic_limit": 30,
            "expire_date_shamsi": "۱۴۰۴/۰۷/۰۱ (منقضی شده)",
            "days_left": 0,
            "remaining_days": 0,
            "duration": 30,
            "is_vip": False,
            "debt_amount": 120000,
            "reseller_name": "پشتیبانی خدمات"
        }
        analytics = {
            "total_gb": 30.0, "used_gb": 29.5, "remain_gb": 0.5, "percent": 98,
            "daily_avg_gb": 1.2, "peak_hour": "۱۹:۰۰ الی ۲۲:۰۰", "day_pct": 80, "night_pct": 20, "estimated_days_left": "منقضی شده",
            "hourly_24h": hourly_24h, "daily_7d": daily_7d, "daily_30d": daily_30d, "weekly_chart": weekly_chart
        }
    else:  # VIP default
        is_new = False
        if active_device == "laptop":
            days_left = 26
            remain_gb = 87.5
            sub_data = {
                "id": 102,
                "hidify_uuid": "sub_laptop",
                "account_name": "کاربر نمونه (آقای رضایی)",
                "device_label": "💻 لپ‌تاپ دل XPS (ویندوز ۱۱)",
                "phone_number": "09121234567",
                "telegram_id": 987654321,
                "telegram_username": "rezaei_vip",
                "status": "active",
                "data_limit": 100.0,
                "data_used": 12.5,
                "remaining_traffic_gb": 87.5,
                "traffic_limit": 100,
                "traffic_limit_display": "۱۰۰ گیگ",
                "expire_date_shamsi": "۱۴۰۴/۰۹/۲۴",
                "days_left": 26,
                "remaining_days": 26,
                "duration": 30,
                "is_vip": True,
                "debt_amount": 0,
                "reseller_name": "پشتیبانی پرمیوم",
                "sub_url": sub_url,
                "sub_link": sub_url,
                "single_url": single_url
            }
            analytics = {
                "total_gb": 100.0,
                "used_gb": 12.5,
                "remain_gb": 87.5,
                "percent": 13,
                "daily_avg_gb": 3.4,
                "peak_hour": "۱۹:۰۰ الی ۲۲:۰۰",
                "day_pct": 75,
                "night_pct": 25,
                "estimated_days_left": 26,
                "hourly_24h": hourly_24h,
                "daily_7d": daily_7d,
                "daily_30d": daily_30d,
                "weekly_chart": weekly_chart
            }
        else:  # mobile
            days_left = 18
            remain_gb = 34.2
            sub_data = {
                "id": 101,
                "hidify_uuid": "sub_mobile",
                "account_name": "کاربر نمونه (آقای رضایی)",
                "device_label": "📱 آیفون ۱۶ پرو (iOS)",
                "phone_number": "09121234567",
                "telegram_id": 987654321,
                "telegram_username": "rezaei_vip",
                "status": "active",
                "data_limit": 50.0,
                "data_used": 15.8,
                "remaining_traffic_gb": 34.2,
                "traffic_limit": 50,
                "traffic_limit_display": "۵۰ گیگ",
                "expire_date_shamsi": "۱۴۰۴/۰۹/۱۰",
                "days_left": 18,
                "remaining_days": 18,
                "duration": 30,
                "is_vip": True,
                "debt_amount": 0,
                "reseller_name": "پشتیبانی پرمیوم",
                "sub_url": sub_url,
                "sub_link": sub_url,
                "single_url": single_url
            }
            analytics = {
                "total_gb": 50.0,
                "used_gb": 15.8,
                "remain_gb": 34.2,
                "percent": 32,
                "daily_avg_gb": 1.8,
                "peak_hour": "۱۹:۰۰ الی ۲۲:۰۰",
                "day_pct": 75,
                "night_pct": 25,
                "estimated_days_left": 18,
                "hourly_24h": hourly_24h,
                "daily_7d": daily_7d,
                "daily_30d": daily_30d,
                "weekly_chart": weekly_chart
            }

    # مدیریت حالت اشتراک تکی (Single) در برابر چند اشتراکه (Multi)
    if sub_mode == "single":
        portal_user_subs = [MOCK_USER_SUBSCRIPTIONS[0] if active_device == "mobile" else MOCK_USER_SUBSCRIPTIONS[1]]
    else:
        portal_user_subs = MOCK_USER_SUBSCRIPTIONS

    # شبیه‌سازی فاکتور کارت به کارت هوشمند (در صورت درخواست)
    invoice_mode = request.args.get("invoice_mode") or session.get("invoice_mode")
    mock_invoice = None
    is_auto_confirm_active = False

    if invoice_mode in ("c2c", "card_to_card"):
        is_auto_confirm_active = True
        session["invoice_created_at"] = session.get("invoice_created_at") or time.time()
        mock_invoice = {
            "order_id": "ORD-C2C-8812",
            "card_number": "۶۰۳۷-۹۹۷۵-۱۲۳۴-۵۶۷۸",
            "card_holder": "محمد پیروزنیا (سامانه پرداخت هوشمند)",
            "bank_name": "بانک ملی ایران",
            "shaba_number": "IR120170000000123456789012",
            "raw_amount": 190000,
            "final_amount": 190340,
            "status": "pending",
            "created_at": datetime.now().isoformat(),
            "expires_at": (datetime.now() + timedelta(minutes=15)).isoformat()
        }
    elif invoice_mode == "crypto":
        mock_invoice = {
            "order_id": "ORD-CRY-5519",
            "card_number": "TX8gKqW3y9PvM17zKLoQ4N2mB8X1eLopQr",
            "card_holder": "ولت رسمی تتر (USDT - TRC20)",
            "bank_name": "ارز دیجیتال (تتر)",
            "raw_amount": 190000,
            "final_amount": "2.10",
            "status": "pending",
            "created_at": datetime.now().isoformat(),
            "expires_at": (datetime.now() + timedelta(minutes=60)).isoformat()
        }

    # آمار و اطلاعات بخش رفرال و دعوت از دوستان
    customer_ref_stats = {
        "total_invites": 12,
        "rewarded_invites": 8,
        "total_reward": 160000,
        "wallet_balance": 50000
    }
    customer_ref_cfg = {
        "reward_type": "fixed",
        "reward_amount": 20000,
        "min_purchase_amount": 100000,
        "custom_terms": "پاداش‌ها به صورت آنی به کیف پول شما واریز شده و در تمام خریدها قابل استفاده است."
    }

    rendered_html = render_template(
        "customer_portal.html",
        sub=sub_data,
        token=active_token,
        plans=MOCK_PLANS,
        total_paid=380000,
        portal_layout=layout,
        portal_plan_style=plan_style,
        portal_enable_renewal=True,
        enable_new_purchase=True,
        lucky_wheel_enabled=True,
        customer_ref_enabled=True,
        customer_ref_code="VIP-9920",
        customer_ref_link="https://t.me/DemoVpnBot?start=ref_VIP9920",
        customer_web_ref_link="https://demo-cloud.net/join/VIP-9920",
        customer_ref_cfg=customer_ref_cfg,
        customer_ref_stats=customer_ref_stats,
        user_social_tasks=MOCK_SOCIAL_TASKS,
        traffic_analytics=analytics,
        portal_payment_methods=MOCK_PAYMENT_METHODS,
        remain_gb=remain_gb,
        days_left=days_left,
        server_status={"state": "operational", "title": "سرویس ابری فعال و متصل"},
        brand_title="سامانه خدمات آنلاین اینترنت آزاد",
        portal_subtitle="پرتال هوشمند استعلام وضعیت و تمدید اشتراک",
        logo_url="/static/images/Logo.webp",
        favicon_url="/static/favicon.ico",
        support_username="demo_support",
        support_phone="09121234567",
        palette_css=full_css,
        is_new_customer=is_new,
        profile_completion_pct=85,
        loyalty_tier_info={
            "tier_name": "کاربر طلایی (VIP)",
            "discount_percent": 15,
            "cashback_percent": 5,
            "badge_color": "gold",
            "icon": "fas fa-crown"
        },
        user_wallet={"balance": 50000, "formatted_balance": "۵۰,۰۰۰ تومان"},
        user_subscriptions=portal_user_subs,
        avatar_presets=AVATAR_PRESETS,
        sub_url=sub_url,
        sub_link=sub_url,
        single_url=single_url,
        portal_banners=[
            {
                "id": 1,
                "title": "جشنواره پاییزه: ۲۰٪ تخفیف تمدید",
                "subtitle": "کد تخفیف: AUTUMN2026",
                "button_text": "مشاهده پلن‌ها",
                "button_link": "#plansSection",
                "gradient": "linear-gradient(135deg, #3b82f6 0%, #06b6d4 100%)"
            }
        ],
        invoice=mock_invoice,
        is_auto_confirm_active=is_auto_confirm_active
    )

    # تزریق نوار ابزار کنترل استودیو طراح در انتهای صفحه (Studio Floating Dock)
    all_pals = list(get_all_palettes().values())
    pal_options = "".join([f'<option value="{p["id"]}" {"selected" if p["id"] == selected_palette else ""}>{p["name"]}</option>' for p in all_pals])
    
    studio_toolbar = f"""
    <!-- 🎛️ نوار کنترل تست زنده طراح (Customer Portal Studio Floating Dock) -->
    <div id="studioFloatingDock" style="position: fixed; bottom: 12px; left: 50%; transform: translateX(-50%); z-index: 9999; background: rgba(15, 23, 42, 0.92); backdrop-filter: blur(20px); border: 1px solid rgba(255, 255, 255, 0.2); border-radius: 50px; padding: 6px 16px; box-shadow: 0 10px 35px rgba(0, 0, 0, 0.5); display: flex; align-items: center; gap: 8px; font-family: 'Vazirmatn', sans-serif; max-width: 96vw; overflow-x: auto;">
        
        <a href="/" style="background: rgba(255,255,255,0.12); color: #fff; text-decoration: none; padding: 4px 10px; border-radius: 30px; font-size: 0.78rem; font-weight: 600; white-space: nowrap;">
            <i class="fas fa-home me-1"></i> خانه
        </a>

        <div style="height: 16px; width: 1px; background: rgba(255,255,255,0.2);"></div>

        <!-- سلکتور چیدمان -->
        <div class="d-flex align-items-center gap-1" style="white-space: nowrap;">
            <span style="font-size: 0.72rem; color: #94a3b8;"><i class="fas fa-layer-group me-1"></i>قالب:</span>
            <select onchange="location.href='/portal?layout=' + this.value + '&plan_style={plan_style}&palette={selected_palette}&sub_mode={sub_mode}&sub_id={sub_id}'" style="background: #1e293b; color: #fff; border: 1px solid rgba(255,255,255,0.15); border-radius: 20px; font-size: 0.72rem; padding: 3px 8px; outline: none;">
                <option value="bento_grid" {"selected" if layout == "bento_grid" else ""}>بنتو گرید</option>
                <option value="classic" {"selected" if layout == "classic" else ""}>کلاسیک</option>
                <option value="split_dashboard" {"selected" if layout == "split_dashboard" else ""}>دو ستونه</option>
                <option value="minimal_tabbed" {"selected" if layout == "minimal_tabbed" else ""}>تب‌بندی مینیمال</option>
            </select>
        </div>

        <!-- سلکتور استایل دکمه و کارت‌ها -->
        <div class="d-flex align-items-center gap-1" style="white-space: nowrap;">
            <span style="font-size: 0.72rem; color: #94a3b8;"><i class="fas fa-gem me-1"></i>استایل دکمه:</span>
            <select onchange="location.href='/portal?layout={layout}&plan_style=' + this.value + '&palette={selected_palette}&sub_mode={sub_mode}&sub_id={sub_id}'" style="background: #1e293b; color: #fff; border: 1px solid rgba(255,255,255,0.15); border-radius: 20px; font-size: 0.72rem; padding: 3px 8px; outline: none;">
                <option value="glass_classic" {"selected" if plan_style == "glass_classic" else ""}>شیشه‌ای</option>
                <option value="tactile_3d" {"selected" if plan_style == "tactile_3d" else ""}>برجسته ۳ بعدی</option>
                <option value="cyber_neon_outline" {"selected" if plan_style == "cyber_neon_outline" else ""}>نئون سایبری</option>
                <option value="floating_elevation" {"selected" if plan_style == "floating_elevation" else ""}>کارت معلق</option>
                <option value="compact_row" {"selected" if plan_style == "compact_row" else ""}>نواری فشرده</option>
            </select>
        </div>

        <div style="height: 16px; width: 1px; background: rgba(255,255,255,0.2);"></div>

        <!-- حالت اشتراک تکی یا چندگانه -->
        <div class="d-flex align-items-center gap-1" style="white-space: nowrap;">
            <span style="font-size: 0.72rem; color: #94a3b8;"><i class="fas fa-users me-1"></i>اشتراک:</span>
            <a href="/portal?sub_mode={'multi' if sub_mode == 'single' else 'single'}&layout={layout}&plan_style={plan_style}&palette={selected_palette}&sub_id={sub_id}" style="text-decoration: none; padding: 3px 8px; border-radius: 20px; font-size: 0.72rem; font-weight: 600; {'background: #8b5cf6; color: #fff;' if sub_mode == 'single' else 'background: rgba(255,255,255,0.1); color: #cbd5e1;'}">
                {'👤 تک اشتراک (بدون نوار)' if sub_mode == 'single' else '👥 چند اشتراکه (با نوار)'}
            </a>
        </div>

        <!-- سوییچ دستگاه -->
        <div class="d-flex align-items-center gap-1" style="white-space: nowrap;">
            <a href="/portal?sub_id=sub_mobile&layout={layout}&plan_style={plan_style}&palette={selected_palette}&sub_mode={sub_mode}&state={state}" style="text-decoration: none; padding: 3px 8px; border-radius: 20px; font-size: 0.72rem; font-weight: 600; {'background: #2563eb; color: #fff;' if active_device == 'mobile' else 'background: rgba(255,255,255,0.08); color: #cbd5e1;'}">
                📱 موبایل
            </a>
            <a href="/portal?sub_id=sub_laptop&layout={layout}&plan_style={plan_style}&palette={selected_palette}&sub_mode={sub_mode}&state={state}" style="text-decoration: none; padding: 3px 8px; border-radius: 20px; font-size: 0.72rem; font-weight: 600; {'background: #0d9488; color: #fff;' if active_device == 'laptop' else 'background: rgba(255,255,255,0.08); color: #cbd5e1;'}">
                💻 لپ‌تاپ
            </a>
        </div>

        <div style="height: 16px; width: 1px; background: rgba(255,255,255,0.2);"></div>

        <!-- میانبرهای مودال‌ها -->
        <div class="d-flex align-items-center gap-1" style="white-space: nowrap;">
            <button type="button" class="btn btn-sm py-1 px-2 text-white" style="background: rgba(255,255,255,0.1); border-radius: 20px; font-size: 0.72rem;" data-bs-toggle="modal" data-bs-target="#subConfigModal" title="باز کردن بارکد و لینک اتصال">
                <i class="fas fa-qrcode text-info me-1"></i> QR اتصال
            </button>
            <button type="button" class="btn btn-sm py-1 px-2 text-white" style="background: rgba(255,255,255,0.1); border-radius: 20px; font-size: 0.72rem;" onclick="openCustomerClubModal('wheel')" title="باز کردن باشگاه مشتریان و گردونه">
                <i class="fas fa-gift text-warning me-1"></i> گردونه و جوایز
            </button>
            <button type="button" class="btn btn-sm py-1 px-2 text-white" style="background: rgba(255,255,255,0.1); border-radius: 20px; font-size: 0.72rem;" data-bs-toggle="modal" data-bs-target="#trafficAnalyticsModal" title="باز کردن نمودار هوشمند">
                <i class="fas fa-chart-line text-success me-1"></i> نمودار مصرف
            </button>
        </div>

        <button onclick="document.getElementById('studioFloatingDock').style.display='none';" style="background: none; border: none; color: #94a3b8; font-size: 0.85rem; cursor: pointer; padding: 0 4px;" title="مخفی کردن نوار">
            <i class="fas fa-times"></i>
        </button>
    </div>
    """

    if "</body>" in rendered_html:
        rendered_html = rendered_html.replace("</body>", f"{studio_toolbar}</body>")

    return rendered_html


# مسیر تولید محلی تصویر بارکد QR (بدون نیاز به اینترنت خارجی)
@app.route("/api/qr-image")
def generate_qr():
    text = request.args.get("text", "")
    try:
        import qrcode
        qr = qrcode.QRCode(box_size=8, border=2)
        qr.add_data(text or "https://demo.cloud")
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return Response(buf.getvalue(), mimetype="image/png")
    except Exception as e:
        # Fallback SVG in case qrcode module issue
        svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200" width="200" height="200">
            <rect width="200" height="200" fill="white" />
            <rect x="20" y="20" width="50" height="50" fill="black" />
            <rect x="130" y="20" width="50" height="50" fill="black" />
            <rect x="20" y="130" width="50" height="50" fill="black" />
            <rect x="80" y="80" width="40" height="40" fill="black" />
        </svg>'''
        return Response(svg, mimetype="image/svg+xml")


# API گردونه شانس و جوایز باشگاه مشتریان
@app.route("/api/portal/<token>/lucky-wheel/prizes")
def lucky_wheel_prizes(token):
    prizes = [
        {"id": 1, "title": "۵ گیگابایت ترافیک هدیه", "prize_type": "traffic", "amount": 5.0, "color": "#3b82f6", "icon": "fas fa-bolt"},
        {"id": 2, "title": "۲۰٪ تخفیف تمدید اشتراک", "prize_type": "discount", "amount": 20, "color": "#f59e0b", "icon": "fas fa-percent"},
        {"id": 3, "title": "۳ روز اشتراک اضافه", "prize_type": "days", "amount": 3, "color": "#10b981", "icon": "fas fa-calendar-plus"},
        {"id": 4, "title": "پوچ (شانس دوباره)", "prize_type": "empty", "amount": 0, "color": "#64748b", "icon": "fas fa-face-smile"},
        {"id": 5, "title": "۱۰ گیگابایت فوق‌العاده", "prize_type": "traffic", "amount": 10.0, "color": "#8b5cf6", "icon": "fas fa-crown"},
        {"id": 6, "title": "کد تخفیف ۵۰ هزار تومانی", "prize_type": "voucher", "amount": 50000, "color": "#ec4899", "icon": "fas fa-ticket"}
    ]
    return jsonify({
        "success": True,
        "enabled": True,
        "can_spin": True,
        "remaining_time": "",
        "rem_seconds": 0,
        "prizes": prizes
    })


@app.route("/api/portal/<token>/lucky-wheel/spin", methods=["POST"])
def lucky_wheel_spin(token):
    return jsonify({
        "success": True,
        "prize_index": 0,
        "spin_id": 9920,
        "prize": {
            "id": 1,
            "title": "۵ گیگابایت ترافیک هدیه",
            "prize_type": "traffic",
            "amount": 5.0
        },
        "reward_message": "تبریک! شما برنده ۵ گیگابایت ترافیک هدیه شدید.",
        "needs_sub_choice": False
    })


@app.route("/api/portal/<token>/lucky-wheel/assign-traffic", methods=["POST"])
def lucky_wheel_assign_traffic(token):
    return jsonify({
        "success": True,
        "message": "حجم با موفقیت به اشتراک شما اضافه شد."
    })


# API ماموریت‌های پاداش
@app.route("/api/portal/<token>/social-tasks/verify-claim", methods=["POST"])
def social_tasks_verify_claim(token):
    return jsonify({
        "success": True,
        "message": "پاداش ماموریت با موفقیت به حساب کاربری شما اضافه شد!"
    })


# API چت پشتیبانی آنلاین
@app.route("/api/portal/<token>/chat/init")
def chat_init(token):
    return jsonify({
        "success": True,
        "is_online": True,
        "support_avatar_url": "/avatar/Support",
        "customer_avatar_url": "/avatar/User",
        "support_name": "پشتیبانی پرمیوم",
        "welcome_msg": "سلام! در صورتی که هرگونه سوال یا راهنمایی نیاز دارید، پیام دهید."
    })


# مسیرهای شبیه‌ساز پرداخت
@app.route("/create_invoice", methods=["GET", "POST"])
@app.route("/portal/buy-new-plan", methods=["POST"])
def create_invoice():
    plan_id = request.form.get("plan_id") or "2"
    payment_method = request.form.get("payment_method") or "card_to_card"
    sub_id = request.args.get("sub_id") or request.form.get("token") or "sub_mobile"
    
    plan_obj = next((p for p in MOCK_PLANS if str(p["id"]) == str(plan_id)), MOCK_PLANS[1])
    amount = plan_obj["price"]

    if payment_method == "online_gateway":
        return redirect(f"/mock_gateway?order_id=ORD-ONL-{int(time.time())}&amount={amount}&sub_id={sub_id}")
    elif payment_method == "card_to_card":
        session["invoice_created_at"] = time.time()
        session["invoice_mode"] = "c2c"
        return redirect(f"/portal?invoice_mode=c2c&sub_id={sub_id}")
    elif payment_method == "crypto":
        session["invoice_mode"] = "crypto"
        return redirect(f"/portal?invoice_mode=crypto&sub_id={sub_id}")
    
    return redirect(f"/portal?sub_id={sub_id}")


@app.route("/mock_gateway")
def mock_gateway():
    order_id = request.args.get("order_id", f"ORD-ONL-{int(time.time())}")
    amount = int(request.args.get("amount", 190000))
    sub_id = request.args.get("sub_id", "sub_mobile")
    active_palette = request.args.get("palette", session.get("active_palette", "vps_aurora"))
    layout = request.args.get("layout", "bento_grid")
    plan_style = request.args.get("plan_style", "glass_classic")

    return render_template(
        "mock_gateway.html",
        order_id=order_id,
        amount=amount,
        sub_id=sub_id,
        active_palette=active_palette,
        layout=layout,
        plan_style=plan_style
    )


# پولینگ زنده وضعیت فاکتور کارت به کارت (شبیه‌ساز تایید خودکار پیامک بانک)
@app.route("/api/invoice/status/<order_id>")
def check_invoice_status(order_id):
    created_at = session.get("invoice_created_at", 0)
    now = time.time()
    force_pay = request.args.get("force") == "1"
    
    # بعد از ۶ ثانیه به صورت خودکار پیامک بانک دریافت و تایید می‌شود
    if force_pay or (created_at and (now - created_at) >= 6):
        return jsonify({
            "status": "paid",
            "tracking_code": f"BNK-SMS-{str(int(now))[-6:]}",
            "order_id": order_id,
            "final_amount": 190340
        })
    
    return jsonify({
        "status": "pending",
        "order_id": order_id,
        "is_expired": False
    })


@app.route("/cancel_invoice")
def cancel_invoice():
    session.pop("invoice_mode", None)
    session.pop("invoice_created_at", None)
    sub_id = request.args.get("sub_id", "sub_mobile")
    return redirect(f"/portal?sub_id={sub_id}")


# هندلر تصویر آواتار و آیکون‌ها برای جلوگیری از بروز هرگونه عکس شکسته
@app.route("/avatar/<path:filename>")
@app.route("/avatars/<path:filename>")
def serve_avatar(filename):
    fname = Path(filename).name.lower()
    if fname in ("logo.webp", "logo.png"):
        logo_path = STATIC_DIR / "images" / "Logo.webp"
        if logo_path.exists():
            return send_from_directory(STATIC_DIR / "images", "Logo.webp")
    if fname in ("favicon.ico",):
        fav_path = STATIC_DIR / "favicon.ico"
        if fav_path.exists():
            return send_from_directory(STATIC_DIR, "favicon.ico")

    # تولید آواتار SVG زیبا
    bg = "#3b82f6"
    if "support" in fname or "reseller" in fname:
        bg = "#06b6d4"
    elif "vip" in fname or "gold" in fname:
        bg = "#f59e0b"

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="100" height="100">
        <defs>
            <linearGradient id="g" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" stop-color="{bg}" />
                <stop offset="100%" stop-color="#1e1b4b" />
            </linearGradient>
        </defs>
        <circle cx="50" cy="50" r="50" fill="url(#g)" />
        <circle cx="50" cy="38" r="18" fill="#ffffff" opacity="0.9" />
        <path d="M 22 84 C 22 66, 36 60, 50 60 C 64 60, 78 66, 78 84 Z" fill="#ffffff" opacity="0.9" />
    </svg>'''
    return Response(svg, mimetype="image/svg+xml")


@app.route("/avatar/preset/<preset_id>")
def serve_avatar_preset(preset_id):
    colors = {
        "gamer": "#ef4444",
        "pro": "#3b82f6",
        "cyber": "#8b5cf6",
        "vip": "#f59e0b",
        "minimal": "#10b981",
        "bot": "#06b6d4"
    }
    col = colors.get(preset_id, "#6366f1")
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="100" height="100">
        <circle cx="50" cy="50" r="48" fill="{col}" fill-opacity="0.2" stroke="{col}" stroke-width="3" />
        <circle cx="50" cy="38" r="16" fill="{col}" />
        <path d="M 24 82 C 24 64, 37 60, 50 60 C 63 60, 76 64, 76 82 Z" fill="{col}" />
    </svg>'''
    return Response(svg, mimetype="image/svg+xml")


if __name__ == "__main__":
    port = 5000
    print("=" * 65)
    print("🚀 Customer Portal UI Studio Is Running!")
    print(f"👉 Open in browser: http://127.0.0.1:{port}")
    print("=" * 65)
    app.run(host="127.0.0.1", port=port, debug=True)
