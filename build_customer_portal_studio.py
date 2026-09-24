#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
🎨 Customer Portal UI Studio Packager
=============================================================================
این اسکریپت یک محیط اختصاصی و ایزوله شبیه به UI Dev Preview Server می‌سازد
که فقط و فقط مخصوص "پرتال مشتری" با تمام چیدمان‌ها، استایل‌های دکمه، پالت‌ها
و وضعیت‌های کاربری است؛ بدون دسترسی به پنل‌های ادمین، نمایندگی یا دیتابیس.
=============================================================================
"""

import os
import sys
import shutil
import zipfile
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

BASE_DIR = Path(__file__).resolve().parent
STUDIO_DIR = BASE_DIR / "Customer_Portal_UI_Package"
TEMPLATES_DIR = STUDIO_DIR / "templates"
STATIC_DIR = STUDIO_DIR / "static"
IMAGES_DIR = STATIC_DIR / "images"

# پاک‌سازی پوشه قبلی در صورت وجود
if STUDIO_DIR.exists():
    shutil.rmtree(STUDIO_DIR)
STUDIO_DIR.mkdir(parents=True, exist_ok=True)
TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
STATIC_DIR.mkdir(parents=True, exist_ok=True)
IMAGES_DIR.mkdir(parents=True, exist_ok=True)

# ۱. کپی قالب customer_portal.html
src_template = BASE_DIR / "templates" / "customer_portal.html"
shutil.copy2(src_template, TEMPLATES_DIR / "customer_portal.html")

# ۲. کپی ماژول palette_manager.py برای کارکرد کامل پالت‌ها
src_palette = BASE_DIR / "palette_manager.py"
shutil.copy2(src_palette, STUDIO_DIR / "palette_manager.py")

# ۳. کپی تصاویر و آیکون‌ها
if (BASE_DIR / "static" / "images").exists():
    for f in (BASE_DIR / "static" / "images").glob("*.*"):
        if f.is_file():
            shutil.copy2(f, IMAGES_DIR / f.name)

if (BASE_DIR / "static" / "favicon.ico").exists():
    shutil.copy2(BASE_DIR / "static" / "favicon.ico", STATIC_DIR / "favicon.ico")

# ۴. ایجاد فایل استایل اختصاصی طراح (designer-custom.css)
with open(STATIC_DIR / "designer-custom.css", "w", encoding="utf-8") as f:
    f.write("""/* ========================================================
   🎨 فایل استایل‌های اختصاصی طراح (Designer Custom CSS)
   تمام تغییرات، بازطراحی‌ها، انیمیشن‌ها و استایل‌های جدید
   پرتال مشتری را در این فایل بنویسید.
   این فایل روی تمام طرح‌بندی‌ها اعمال خواهد شد.
   ======================================================== */

/* مثال: تغییر شعاع کارت‌ها یا افکت‌های جدید */
/*
.bento-card, .portal-card {
    border-radius: 20px !important;
}
*/
""")

# ۵. ایجاد قالب کاتالوگ صفحه اصلی (templates/index.html)
INDEX_HTML = """<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>استودیو بازطراحی پرتال مشتری | Customer Portal UI Studio</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.rtl.min.css" rel="stylesheet">
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css" rel="stylesheet">
    <link href="https://cdn.jsdelivr.net/gh/rastikerdar/vazirmatn@v33.003/misc/Farsi-Digits/Vazirmatn-FD-font-face.css" rel="stylesheet">
    <style>
        body {
            font-family: 'Vazirmatn', sans-serif;
            background: #f8fafc;
            color: #0f172a;
        }
        .hero-banner {
            background: linear-gradient(135deg, #1e3a8a 0%, #3b82f6 50%, #06b6d4 100%);
            color: white;
            border-radius: 24px;
            padding: 2.5rem 2rem;
            margin-bottom: 2rem;
            box-shadow: 0 10px 30px -10px rgba(59, 130, 246, 0.4);
        }
        .palette-chip {
            cursor: pointer;
            border-radius: 50px;
            padding: 8px 16px;
            border: 2px solid transparent;
            background: white;
            display: inline-flex;
            align-items: center;
            gap: 8px;
            font-size: 0.88rem;
            font-weight: 600;
            box-shadow: 0 2px 8px rgba(0,0,0,0.06);
            transition: all 0.2s ease;
            text-decoration: none;
            color: #334155;
        }
        .palette-chip:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 16px rgba(0,0,0,0.1);
            color: #0f172a;
        }
        .palette-chip.active {
            border-color: #2563eb;
            background: #eff6ff;
            color: #1d4ed8;
        }
        .color-dot {
            width: 14px;
            height: 14px;
            border-radius: 50%;
            display: inline-block;
        }
        .feature-card {
            background: white;
            border-radius: 18px;
            border: 1px solid #e2e8f0;
            padding: 1.5rem;
            height: 100%;
            transition: all 0.25s ease;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
        }
        .feature-card:hover {
            transform: translateY(-4px);
            box-shadow: 0 12px 24px -6px rgba(0,0,0,0.08);
            border-color: #cbd5e1;
        }
        .badge-soft {
            background: #f1f5f9;
            color: #475569;
            font-weight: 600;
            border-radius: 8px;
            padding: 4px 10px;
        }
    </style>
</head>
<body>

<div class="container py-4" style="max-width: 1100px;">

    <!-- بنر معرفی -->
    <div class="hero-banner text-center position-relative">
        <span class="badge bg-white text-primary rounded-pill px-3 py-2 fw-bold mb-3 shadow-sm">
            <i class="fas fa-sparkles me-1"></i> محیط اختصاصی بازطراحی پرتال مشتری (Customer Portal)
        </span>
        <h2 class="fw-bold mb-2">استودیو تست و بازطراحی زنده UI</h2>
        <p class="mb-0 opacity-90 fs-6">مشاهده، ادیت و تست بلادرنگ تمام چیدمان‌ها، استایل‌های دکمه و پالت‌های رنگی بدون نیاز به دیتابیس</p>
    </div>

    <!-- بخش انتخاب پالت رنگی زنده -->
    <div class="card border-0 shadow-sm rounded-4 p-4 mb-4 bg-white">
        <div class="d-flex justify-content-between align-items-center mb-3">
            <h5 class="fw-bold mb-0">
                <i class="fas fa-palette text-primary me-2"></i> انتخاب پالت رنگی پیش‌نمایش ({{ all_palettes|length }} تم رنگی)
            </h5>
            <span class="small text-muted">پالت فعال: <strong>{{ active_palette_name }}</strong></span>
        </div>
        <div class="d-flex flex-wrap gap-2">
            {% for p in all_palettes %}
            <a href="/?palette={{ p.id }}" class="palette-chip {% if p.id == active_palette %}active{% endif %}">
                <span class="color-dot" style="background: {{ p.preview.blob1 }};"></span>
                <span>{{ p.name }}</span>
            </a>
            {% endfor %}
        </div>
    </div>

    <!-- بخش ۱: چیدمان‌های مختلف پرتال (Layouts) -->
    <div class="mb-4">
        <h4 class="fw-bold mb-3 d-flex align-items-center gap-2">
            <i class="fas fa-layer-group text-primary"></i>
            <span>۱. انواع طرح‌بندی‌های پرتال مشتری (Layouts)</span>
        </h4>
        <div class="row g-3">
            <div class="col-md-6 col-lg-3">
                <div class="feature-card">
                    <div>
                        <span class="badge bg-primary-subtle text-primary rounded-pill px-2 py-1 small mb-2">طرح پیش‌فرض</span>
                        <h5 class="fw-bold">بنتو گرید (Bento Grid)</h5>
                        <p class="small text-muted mb-3">چیدمان کاشی‌کاری مدرن و شبکه‌ای شبیه به iOS با کارت‌های اطلاعاتی مجزا.</p>
                    </div>
                    <a href="/portal?layout=bento_grid&palette={{ active_palette }}" target="_blank" class="btn btn-primary w-100 rounded-pill">
                        مشاهده زنده <i class="fas fa-arrow-left ms-1"></i>
                    </a>
                </div>
            </div>

            <div class="col-md-6 col-lg-3">
                <div class="feature-card">
                    <div>
                        <span class="badge bg-secondary-subtle text-secondary rounded-pill px-2 py-1 small mb-2">طرح ۲</span>
                        <h5 class="fw-bold">کلاسیک آبشاری (Classic)</h5>
                        <p class="small text-muted mb-3">ساختار عمودی سنتی با تاکید بر کارت اشتراک و لیست پلن‌ها در پایین صفحه.</p>
                    </div>
                    <a href="/portal?layout=classic&palette={{ active_palette }}" target="_blank" class="btn btn-outline-primary w-100 rounded-pill">
                        مشاهده زنده <i class="fas fa-arrow-left ms-1"></i>
                    </a>
                </div>
            </div>

            <div class="col-md-6 col-lg-3">
                <div class="feature-card">
                    <div>
                        <span class="badge bg-info-subtle text-info rounded-pill px-2 py-1 small mb-2">طرح ۳</span>
                        <h5 class="fw-bold">داشبورد دو ستونه (Split)</h5>
                        <p class="small text-muted mb-3">ستون سمت راست مشخصات کاربر و ستون چپ پنل خرید و تمدید سریع.</p>
                    </div>
                    <a href="/portal?layout=split_dashboard&palette={{ active_palette }}" target="_blank" class="btn btn-outline-primary w-100 rounded-pill">
                        مشاهده زنده <i class="fas fa-arrow-left ms-1"></i>
                    </a>
                </div>
            </div>

            <div class="col-md-6 col-lg-3">
                <div class="feature-card">
                    <div>
                        <span class="badge bg-success-subtle text-success rounded-pill px-2 py-1 small mb-2">طرح ۴</span>
                        <h5 class="fw-bold">تب‌بندی مینیمال (Tabs)</h5>
                        <p class="small text-muted mb-3">صفحه بسیار خلوت و تمیز با تفکیک وضعیت و پلن‌ها در تب‌های مجزا.</p>
                    </div>
                    <a href="/portal?layout=minimal_tabbed&palette={{ active_palette }}" target="_blank" class="btn btn-outline-primary w-100 rounded-pill">
                        مشاهده زنده <i class="fas fa-arrow-left ms-1"></i>
                    </a>
                </div>
            </div>
        </div>
    </div>

    <!-- بخش ۲: استایل‌های دکمه‌ها و کارت‌های پلن (Plan Styles) -->
    <div class="mb-4">
        <h4 class="fw-bold mb-3 d-flex align-items-center gap-2">
            <i class="fas fa-gem text-warning"></i>
            <span>۲. استایل دکمه‌ها و کارت‌های خرید پلن (Plan & Button Styles)</span>
        </h4>
        <div class="row g-3">
            <div class="col-md-4">
                <div class="feature-card">
                    <div>
                        <h6 class="fw-bold"><i class="fas fa-glass-martini-alt text-primary me-1"></i> شیشه‌ای کلاسیک (Glass Classic)</h6>
                        <p class="small text-muted mb-3">حالت شیشه‌ای نرم، پس‌زمینه نیمه‌شفاف با بلور مات (Frosted Glass).</p>
                    </div>
                    <a href="/portal?plan_style=glass_classic&palette={{ active_palette }}" target="_blank" class="btn btn-sm btn-outline-dark rounded-pill w-100">
                        تست این استایل
                    </a>
                </div>
            </div>

            <div class="col-md-4">
                <div class="feature-card">
                    <div>
                        <h6 class="fw-bold"><i class="fas fa-cube text-danger me-1"></i> برجسته لمسی سه‌بعدی (Tactile 3D)</h6>
                        <p class="small text-muted mb-3">دکمه‌های برجسته با سایه سخت و افکت فشرده شدن کلیکی (Active Push).</p>
                    </div>
                    <a href="/portal?plan_style=tactile_3d&palette={{ active_palette }}" target="_blank" class="btn btn-sm btn-outline-dark rounded-pill w-100">
                        تست این استایل
                    </a>
                </div>
            </div>

            <div class="col-md-4">
                <div class="feature-card">
                    <div>
                        <h6 class="fw-bold"><i class="fas fa-bolt text-warning me-1"></i> نئون سایبری (Cyber Neon)</h6>
                        <p class="small text-muted mb-3">کادرهای درخشان با خطوط نئونی و استایل دارک مدرن با زوایای تیز.</p>
                    </div>
                    <a href="/portal?plan_style=cyber_neon_outline&palette={{ active_palette }}" target="_blank" class="btn btn-sm btn-outline-dark rounded-pill w-100">
                        تست این استایل
                    </a>
                </div>
            </div>

            <div class="col-md-6">
                <div class="feature-card">
                    <div>
                        <h6 class="fw-bold"><i class="fas fa-cloud text-info me-1"></i> کارت معلق پرمیوم (Floating Elevation)</h6>
                        <p class="small text-muted mb-3">سایه‌های عمیق با فاصله زیاد از سطح، افکت هاور معلق و جلوه نرم و شناور.</p>
                    </div>
                    <a href="/portal?plan_style=floating_elevation&palette={{ active_palette }}" target="_blank" class="btn btn-sm btn-outline-dark rounded-pill w-100">
                        تست این استایل
                    </a>
                </div>
            </div>

            <div class="col-md-6">
                <div class="feature-card">
                    <div>
                        <h6 class="fw-bold"><i class="fas fa-bars text-success me-1"></i> نواری فشرده (Compact Row)</h6>
                        <p class="small text-muted mb-3">چیدمان خطی و کم‌جا برای موبایل، دسترسی سریع بدون اسکرول طولانی.</p>
                    </div>
                    <a href="/portal?plan_style=compact_row&palette={{ active_palette }}" target="_blank" class="btn btn-sm btn-outline-dark rounded-pill w-100">
                        تست این استایل
                    </a>
                </div>
            </div>
        </div>
    </div>

    <!-- بخش ۳: شبیه‌سازی وضعیت‌های مختلف کاربر (Customer States) -->
    <div class="mb-4">
        <h4 class="fw-bold mb-3 d-flex align-items-center gap-2">
            <i class="fas fa-user-gear text-success"></i>
            <span>۳. شبیه‌سازی وضعیت‌های مختلف کاربر (Customer States)</span>
        </h4>
        <div class="row g-3">
            <div class="col-md-4">
                <div class="feature-card">
                    <div>
                        <h6 class="fw-bold text-success"><i class="fas fa-crown me-1"></i> کاربر فعال VIP</h6>
                        <p class="small text-muted mb-2">نمایش گردونه شانس، بج وفاداری طلایی، حجم پر و وضعیت متصل.</p>
                    </div>
                    <a href="/portal?state=vip&palette={{ active_palette }}" target="_blank" class="btn btn-sm btn-success rounded-pill w-100">
                        مشاهده حالت VIP
                    </a>
                </div>
            </div>

            <div class="col-md-4">
                <div class="feature-card">
                    <div>
                        <h6 class="fw-bold text-danger"><i class="fas fa-clock me-1"></i> کاربر منقضی / بدهکار</h6>
                        <p class="small text-muted mb-2">نمایش بج هشدار قرمز، ترافیک تمام‌شده و اولویت تمدید اضطراری.</p>
                    </div>
                    <a href="/portal?state=debt&palette={{ active_palette }}" target="_blank" class="btn btn-sm btn-danger rounded-pill w-100">
                        مشاهده حالت منقضی
                    </a>
                </div>
            </div>

            <div class="col-md-4">
                <div class="feature-card">
                    <div>
                        <h6 class="fw-bold text-primary"><i class="fas fa-user-plus me-1"></i> مشتری جدید (خرید اول)</h6>
                        <p class="small text-muted mb-2">بدون اشتراک قبلی، متن خوش‌آمدگویی و تمرکز مستقیم روی کارت‌های خرید.</p>
                    </div>
                    <a href="/portal?state=new&palette={{ active_palette }}" target="_blank" class="btn btn-sm btn-primary rounded-pill w-100">
                        مشاهده حالت جدید
                    </a>
                </div>
            </div>
        </div>
    </div>

    <!-- راهنمای ادیت استایل -->
    <div class="alert alert-light border rounded-4 p-3 d-flex align-items-center gap-3 shadow-sm">
        <div class="fs-2 text-primary"><i class="fas fa-code"></i></div>
        <div class="small">
            <strong>نکته مهم برای طراح:</strong> برای اعمال استایل‌ها و کلاس‌های CSS دلخواه، کافی است فایل 
            <code class="bg-white px-2 py-1 rounded border">static/designer-custom.css</code> را ویرایش کنید. تغییرات بلافاصله با رفرش صفحه در دسترس خواهند بود.
        </div>
    </div>

</div>

</body>
</html>
"""
with open(TEMPLATES_DIR / "index.html", "w", encoding="utf-8") as f:
    f.write(INDEX_HTML)

# ۶. ایجاد فایل اجرایی اصلی سرور استودیو (app.py)
APP_PY_CODE = """# -*- coding: utf-8 -*-
\"\"\"
🚀 Customer Portal UI Studio - Local Preview Server
سرور پیش‌نمایش ایزوله و کامل پرتال مشتری با قابلیت تغییر پالت، چیدمان و استایل‌ها
\"\"\"

import os
import sys
from pathlib import Path
from flask import Flask, render_template, request, session, redirect, jsonify, send_from_directory
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

# کلاس SafeUndefined برای جلوگیری از خطاهای متغیرهای ناموجود
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
    def __format__(self, spec): return ""
    def get(self, *args, **kwargs):
        return args[1] if len(args) > 1 else SafeUndefined()

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
app.jinja_env.filters["gregorian_date"] = lambda v, *a, **k: "2026-09-24 14:00"
app.jinja_env.filters["format_gregorian_date"] = lambda v, *a, **k: "2026-09-24 14:00"
app.jinja_env.filters["last_connection_display"] = lambda v, *a, **k: "آنلاین (۵ دقیقه پیش)"
app.jinja_env.filters["format_last_connection_display"] = lambda v, *a, **k: "آنلاین (۵ دقیقه پیش)"
app.jinja_env.filters["field_display_name"] = lambda v, *a, **k: str(v) if v else ""

app.jinja_env.globals["url_for"] = lambda endpoint, **kwargs: "#"
app.jinja_env.globals["get_customer_portal_url"] = lambda token="", _external=False: "/portal"

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
        "desc": "واریز کارت به کارت مستقیم و ثبت فیش پرداخت",
        "icon": "fas fa-credit-card",
        "color": "primary",
        "btn_text": "ثبت فیش و شماره کارت"
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

@app.route("/")
def index():
    active_palette = request.args.get("palette") or session.get("active_palette", "vps_aurora")
    session["active_palette"] = active_palette
    pal_data = get_palette(active_palette)
    return render_template(
        "index.html",
        all_palettes=get_all_palettes(),
        active_palette=active_palette,
        active_palette_name=pal_data.get("name", "وی‌پی‌اس اورورا")
    )

@app.route("/portal")
def view_portal():
    layout = request.args.get("layout", "bento_grid")
    plan_style = request.args.get("plan_style", "glass_classic")
    state = request.args.get("state", "vip")
    selected_palette = request.args.get("palette") or session.get("active_palette", "vps_aurora")
    session["active_palette"] = selected_palette

    # تنظیم پالت رنگی
    pal_data = get_palette(selected_palette)
    palette_css = generate_palette_css({"data": pal_data, "intensity": "normal", "animation": "float"})

    # تزریق استایل اختصاصی طراح (designer-custom.css)
    custom_designer_css = ""
    custom_css_file = STATIC_DIR / "designer-custom.css"
    if custom_css_file.exists():
        custom_designer_css = custom_css_file.read_text(encoding="utf-8")
    
    full_css = palette_css + "\\n\\n" + custom_designer_css

    # داده‌های کاربر بر اساس حالت انتخابی
    if state == "new":
        is_new = True
        sub_data = None
        days_left = 0
        remain_gb = 0
    elif state == "debt":
        is_new = False
        days_left = 0
        remain_gb = 0.5
        sub_data = {
            "id": 102,
            "account_name": "کاربر گرامی (بدهکار)",
            "phone_number": "09120000000",
            "telegram_id": 987654321,
            "telegram_username": "demo_user",
            "status": "expired",
            "data_limit": 30.0,
            "data_used": 29.5,
            "remaining_traffic_gb": 0.5,
            "expire_date_shamsi": "۱۴۰۴/۰۷/۰۱ (منقضی شده)",
            "days_left": 0,
            "is_vip": False,
            "debt_amount": 120000,
            "reseller_name": "پشتیبانی خدمات"
        }
    else:  # VIP default
        is_new = False
        days_left = 18
        remain_gb = 34.2
        sub_data = {
            "id": 101,
            "account_name": "کاربر نمونه (آقای رضایی)",
            "phone_number": "09120000000",
            "telegram_id": 987654321,
            "telegram_username": "demo_user",
            "status": "active",
            "data_limit": 50.0,
            "data_used": 15.8,
            "remaining_traffic_gb": 34.2,
            "expire_date_shamsi": "۱۴۰۴/۰۹/۱۰",
            "days_left": 18,
            "is_vip": True,
            "debt_amount": 0,
            "reseller_name": "پشتیبانی پرمیوم",
            "sub_url": "https://sub.demo-domain.com/token-sample-12345",
            "sub_link": "https://sub.demo-domain.com/token-sample-12345"
        }

    return render_template(
        "customer_portal.html",
        sub=sub_data,
        token="demo-token",
        plans=MOCK_PLANS,
        total_paid=380000,
        portal_layout=layout,
        portal_plan_style=plan_style,
        portal_enable_renewal=True,
        enable_new_purchase=True,
        lucky_wheel_enabled=(state == "vip"),
        customer_ref_enabled=True,
        customer_ref_code="VIP-9920",
        customer_ref_link="https://demo-domain.com/join/VIP-9920",
        portal_payment_methods=MOCK_PAYMENT_METHODS,
        remain_gb=remain_gb,
        days_left=days_left,
        server_status={"state": "operational", "title": "سرویس ابری فعال و متصل"},
        brand_title="سامانه خدمات آنلاین اینترنت آزاد",
        portal_subtitle="پرتال هوشمند استعلام وضعیت و تمدید اشتراک",
        logo_url="/static/images/Logo.webp",
        favicon_url="/static/favicon.ico",
        support_username="demo_support",
        support_phone="09120000000",
        palette_css=full_css,
        is_new_customer=is_new,
        profile_completion_pct=85,
        loyalty_tier_info={
            "tier_name": "کاربر طلایی (VIP)",
            "discount_percent": 15,
            "badge_color": "gold",
            "icon": "fas fa-crown"
        },
        user_wallet={"balance": 50000, "formatted_balance": "۵۰,۰۰۰ تومان"},
        user_subscriptions=[
            {"account_name": "اشتراک موبایل", "days_left": 18, "remain_gb": 34.2, "is_active": True},
            {"account_name": "اشتراک لپ‌تاپ", "days_left": 5, "remain_gb": 6.5, "is_active": True}
        ],
        portal_banners=[
            {
                "id": 1,
                "title": "جشنواره پاییزه: ۲۰٪ تخفیف تمدید",
                "subtitle": "کد تخفیف: AUTUMN2026",
                "button_text": "مشاهده پلن‌ها",
                "button_link": "#plansSection",
                "gradient": "linear-gradient(135deg, #3b82f6 0%, #06b6d4 100%)"
            }
        ]
    )

if __name__ == "__main__":
    port = 5000
    print("=" * 60)
    print("🚀 Customer Portal UI Studio Is Running!")
    print(f"👉 Open in browser: http://127.0.0.1:{port}")
    print("=" * 60)
    app.run(host="127.0.0.1", port=port, debug=True)
"""

with open(STUDIO_DIR / "app.py", "w", encoding="utf-8") as f:
    f.write(APP_PY_CODE)

# ۷. فایل‌های راه‌اندازی (run.bat و run.sh و requirements.txt)
with open(STUDIO_DIR / "requirements.txt", "w", encoding="utf-8") as f:
    f.write("Flask>=2.3.0\n")

# run.bat: اجرای خودکار با ۱ کلیک در ویندوز و باز کردن خودکار مرورگر
RUN_BAT = """@echo off
title Customer Portal UI Studio
chcp 65001 >nul
echo ========================================================
echo   🚀 در حال راه‌اندازی استودیو طراحی پرتال مشتری...
echo ========================================================
pip install -r requirements.txt -q
start http://127.0.0.1:5000
python app.py
pause
"""
with open(STUDIO_DIR / "run.bat", "w", encoding="utf-8", newline="\r\n") as f:
    f.write(RUN_BAT)

# run.sh برای لینوکس/مک
RUN_SH = """#!/usr/bin/env bash
echo "Starting Customer Portal UI Studio..."
pip install -r requirements.txt -q
python3 app.py
"""
with open(STUDIO_DIR / "run.sh", "w", encoding="utf-8", newline="\n") as f:
    f.write(RUN_SH)

# ۸. راهنمای کامل و شفاف برای طراح (README.md)
README_CONTENT = """# 🎨 راهنمای استودیو بازطراحی پرتال مشتری (Customer Portal UI Studio)

طراح گرامی، درود!  
این پکیج یک استودیوی کامل و ایزوله جهت بازطراحی، مدرن‌سازی و استایل‌دهی به **پرتال مشتریان** است.

---

### 🚀 نحوه اجرا (فقط با ۱ کلیک):
* **در ویندوز:** کافی است روی فایل **`run.bat`** دو بار کلیک کنید!  
  *(سرور به صورت خودکار اجرا شده و صفحه کاتالوگ در مرورگر شما باز می‌شود).*
* **در مک یا لینوکس:**
  ```bash
  bash run.sh
  ```
👉 آدرس پیش‌فرض در مرورگر: **`http://127.0.0.1:5000`**

---

### 🌟 امکانات این استودیو:
1. **تغییر زنده پالت رنگی:** با یک کلیک بین ۸ پالت رنگی مدرن (اورورا، زمرد سایبری، سحابی بنفش، غروب شیدایی و...) سوییچ کنید.
2. **بررسی انواع طرح‌بندی‌ها (Layouts):**  
   - بنتو گرید مدرن (Bento Grid)
   - کلاسیک آبشاری (Classic)
   - دو ستونه (Split Dashboard)
   - تب‌بندی مینیمال (Tabs)
3. **تست انواع استایل دکمه‌ها و پلن‌ها (Plan Styles):**  
   - شیشه‌ای کلاسیک (Glass Classic)
   - برجسته لمسی سه‌بعدی (Tactile 3D)
   - نئون سایبری (Cyber Neon)
   - کارت معلق (Floating Elevation)
   - نواری فشرده (Compact Row)
4. **شبیه‌سازی وضعیت‌های کاربر:**  
   - کاربر فعال VIP (با گردونه شانس و بج وفاداری)
   - کاربر منقضی و بدهکار
   - کاربر جدید (خرید اول)

---

### 🖌️ نحوه اعمال استایل‌های اختصاصی:
شما می‌توانید تمام استایل‌ها، رنگ‌ها، فونت‌ها و افکت‌های جدید خود را درون فایل **`static/designer-custom.css`** بنویسید یا ویرایش فرمایید.  
همچنین می‌توانید قالب اصلی را در **`templates/customer_portal.html`** بازطراحی کنید.

موفق و پیروز باشید!
"""
with open(STUDIO_DIR / "README.md", "w", encoding="utf-8") as f:
    f.write(README_CONTENT)

# ۹. ساخت فایل فشرده ZIP نهایی
ZIP_OUTPUT = BASE_DIR / "Customer_Portal_UI_Package.zip"
with zipfile.ZipFile(ZIP_OUTPUT, "w", zipfile.ZIP_DEFLATED) as zipf:
    for root, dirs, files in os.walk(STUDIO_DIR):
        for file in files:
            p = Path(root) / file
            arc = p.relative_to(STUDIO_DIR)
            zipf.write(p, arc)

zip_mb = os.path.getsize(ZIP_OUTPUT) / (1024 * 1024)
print("=" * 65)
print("🎉 پکیج استودیو پرتال مشتری با موفقیت ساخته شد!")
print(f"📁 پوشه استودیو: {STUDIO_DIR}")
print(f"📦 فایل فشرده آماده ارسال به دیزاینر: {ZIP_OUTPUT}")
print(f"📊 حجم فایل ZIP: {zip_mb:.2f} مگابایت")
print("=" * 65)
