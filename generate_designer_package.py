#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
اسکریپت تولید پکیج ایزوله و امن پرتال مشتری برای دیزاینر
"""

import os
import sys
import re
import shutil
import zipfile
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

BASE_DIR = Path(__file__).parent.resolve()
OUTPUT_DIR = BASE_DIR / "Customer_Portal_UI_Design_Package"
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

# آماده‌سازی پوشه خروجی
if OUTPUT_DIR.exists():
    shutil.rmtree(OUTPUT_DIR)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# پوشه استاتیک در پکیج دیزاینر
ASSETS_DIR = OUTPUT_DIR / "assets"
ASSETS_DIR.mkdir(parents=True, exist_ok=True)
IMAGES_DIR = ASSETS_DIR / "images"
IMAGES_DIR.mkdir(parents=True, exist_ok=True)

# کپی تصاویر لازم
if (STATIC_DIR / "images").exists():
    for img_file in (STATIC_DIR / "images").glob("*.*"):
        if img_file.is_file() and img_file.suffix.lower() in [".png", ".jpg", ".jpeg", ".webp", ".svg", ".ico"]:
            shutil.copy2(img_file, IMAGES_DIR / img_file.name)

if (STATIC_DIR / "favicon.ico").exists():
    shutil.copy2(STATIC_DIR / "favicon.ico", ASSETS_DIR / "favicon.ico")

print("🔄 در حال رندر و دریافت پرتال مشتری...")
sys.path.insert(0, str(BASE_DIR / "ui_package"))
from app import app, MOCK_PORTAL_SUB, MOCK_PORTAL_PLANS

# پاک‌سازی داده‌های ساختگی قبل از رندر
MOCK_PORTAL_SUB["account_name"] = "کاربر نمونه (آقای رضایی)"
MOCK_PORTAL_SUB["phone_number"] = "09120000000"
MOCK_PORTAL_SUB["telegram_username"] = "demo_user"
MOCK_PORTAL_SUB["reseller_name"] = "مرکز پشتیبانی اشتراک"
MOCK_PORTAL_SUB["sub_url"] = "https://sub.example.com/demo-subscription-token-key"
MOCK_PORTAL_SUB["sub_link"] = "https://sub.example.com/demo-subscription-token-key"

client = app.test_client()
res = client.get("/customer_portal?layout=bento_grid&plan_style=glass_classic")

if res.status_code != 200:
    print(f"❌ خطا در رندر صفحه: کد {res.status_code}")
    sys.exit(1)

rendered_html = res.data.decode("utf-8", errors="ignore")

print("🧹 در حال پاک‌سازی و ایزوله‌سازی متغیرها و کدهای حساس...")

# ۱. تبدیل مسیرهای محلی به پوشه assets
rendered_html = re.sub(r'href=[\'"]/static/favicon\.ico[\'"]', 'href="assets/favicon.ico"', rendered_html)
rendered_html = re.sub(r'src=[\'"]/static/images/([^\'"]+)[\'"]', r'src="assets/images/\1"', rendered_html)
rendered_html = re.sub(r'src=[\'"]/avatars/([^\'"]+)[\'"]', r'src="assets/images/\1"', rendered_html)
rendered_html = re.sub(r'href=[\'"]/avatars/([^\'"]+)[\'"]', r'href="assets/images/\1"', rendered_html)

# ۲. پاک‌سازی کامل تمام شماره‌ها و نام‌های واقعی که ممکن است در دامی دیتا باقی مانده باشد
rendered_html = re.sub(r'09118628259', '09120000000', rendered_html)
rendered_html = re.sub(r'زهرا خادملو', 'کاربر نمونه', rendered_html)
rendered_html = re.sub(r'netup_top', 'demo_support', rendered_html)
rendered_html = re.sub(r'https?://[a-zA-Z0-9.-]+\.example\.com', 'https://demo-domain.com', rendered_html)

# ۳. تزریق استایل اختصاصی دیزاینر قبل از بسته شدن head
custom_css_link = """
    <!-- استایل‌های اختصاصی شما به عنوان دیزاینر (این فایل را در پوشه assets ویرایش کنید) -->
    <link rel="stylesheet" href="assets/designer-custom.css">
</head>"""
rendered_html = rendered_html.replace("</head>", custom_css_link)

# نوشتن فایل نهایی index.html
index_file = OUTPUT_DIR / "index.html"
with open(index_file, "w", encoding="utf-8") as f:
    f.write(rendered_html)

# ایجاد فایل استایل اولیه برای دیزاینر
custom_css_file = ASSETS_DIR / "designer-custom.css"
with open(custom_css_file, "w", encoding="utf-8") as f:
    f.write("""/* ========================================================
   طراح گرامی، شما می‌توانید تمام استایل‌ها، رنگ‌ها، فونت‌ها
   و بازطراحی‌های جدید خود را درون این فایل بنویسید یا بازنویسی کنید.
   ======================================================== */

/* نمونه کدهای تغییر استایل */
/*
:root {
    --primary: #4f46e5 !important;
}
.portal-card {
    border-radius: 20px !important;
}
*/
""")

# ایجاد راهنمای دیزاینر
readme_file = OUTPUT_DIR / "README.md"
with open(readme_file, "w", encoding="utf-8") as f:
    f.write("""# راهنمای بازطراحی رابط کاربری پرتال مشتری (Customer Portal)

طراح گرامی، سلام!  
این پکیج به صورت کاملاً مستقل و آماده جهت بازطراحی، بهبود ظاهر، مدرن‌سازی و استایل‌دهی به پرتال کاربری آماده شده است.

---

### 🚀 نحوه اجرا و مشاهده صفحه:
نیازی به نصب هیچ نرم‌افزار، سرور، پایتون یا دیتابیس ندارید!
کافی است روی فایل **`index.html`** دو بار کلیک کنید تا در مرورگر شما (Chrome، Edge، Safari و...) باز شود.  
همچنین می‌توانید این پوشه را در نرم‌افزارهایی مثل **VS Code** باز کرده و با افزونه **Live Server** تغییرات را لحظه‌ای مشاهده فرمایید.

---

### 🎨 نحوه اعمال تغییرات ظاهری:
1. **استایل‌ها و رنگ‌ها:** تمام استایل‌ها و کلاس‌های اختصاصی جدید خود را می‌توانید درون فایل **`assets/designer-custom.css`** بنویسید یا ویرایش کنید.
2. **کلاس‌ها و ساختار HTML:** شما می‌توانید ساختار المان‌ها، دکمه‌ها، کارت‌های اشتراک، مدال‌ها و بخش‌های بصری را درون `index.html` بازطراحی کنید.
3. **نکته بسیار مهم:** لطفاً شناسه‌ها (`id="..."`) و نام ویژگی‌های عملکردی المان‌های اصلی را حذف یا تغییر ندهید تا در زمان اتصال به سامانه، عملکرد دکمه‌ها بدون تغییر بماند.

---

### 📦 محتویات این پکیج:
- 📄 `index.html`: صفحه اصلی پرتال مشتری با چیدمان کامل و داده‌های فرضی
- 📁 `assets/`: شامل تصاویر، لوگو و فایل استایل `designer-custom.css`

موفق و پیروز باشید!
""")

# ایجاد نسخه فشرده ZIP
zip_path = BASE_DIR / "Customer_Portal_UI_Package.zip"
with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
    for root, dirs, files in os.walk(OUTPUT_DIR):
        for file in files:
            file_path = Path(root) / file
            arcname = file_path.relative_to(OUTPUT_DIR)
            zipf.write(file_path, arcname)

print("=" * 60)
print(f"✅ پکیج ایزوله با موفقیت ساخته شد: {OUTPUT_DIR}")
print(f"📦 فایل فشرده آماده تحویل به دیزاینر: {zip_path}")
print(f"📊 حجم فایل ZIP: {os.path.getsize(zip_path) / 1024:.1f} کیلوبایت")
print("=" * 60)
