# ☁️ راهنمای جامع و تضمینی اتصال با کلودفلر و تانل (Cloudflare Tunnel Guide)

استفاده از **کلودفلر تانل (`cloudflared`)** بهترین، امن‌ترین و مطمئن‌ترین روش برای اتصال دامنه به پنل وب HiddiBot است، به ویژه زمانی که پنل را **در کنار هیدیفای (Hiddify)، مرزبان (Marzban) یا Nginx** روی یک سرور مشترک نصب کرده‌اید.

### 🌟 چرا کلودفلر تانل بهترین راهکار همزیستی است؟
1. **بدون نیاز به باز کردن پورت ۸۰ یا ۴۴۳:** پورت‌های اصلی وب سرور کاملاً در اختیار هیدیفای یا هسته Xray باقی می‌مانند.
2. **پنهان‌سازی ۱۰۰٪ آی‌پی سرور (Anti-DDoS & IP Masking):** هیچ‌کس نمی‌تواند آی‌پی واقعی سرور شما را از طریق پنل شناسایی یا فیلتر کند.
3. **گواهی SSL خودکار، معتبر و بدون دردسر:** نیازی به اجرای Certbot یا درگیری با چالش تداخل پورت ۸۰ نیست.
4. **عدم نیاز به IP ثابت یا پورت فورواردینگ:** حتی روی سرورهای پشت NAT یا شبکه‌های داخلی نیز بدون مشکل کار می‌کند.
5. **راه‌اندازی خودکار پس از ریبوت سرور:** سرویس `cloudflared` توسط `systemd` مدیریت شده و با هر بار ریست سرور فعال می‌گردد.

---

## 🚀 روش ۱ (پیشنهادی و ۱۰۰٪ بدون خطا): اتصال با توکن کلودفلر Zero Trust

این روش مدرن‌ترین و پایدارترین شیوه کلودفلر است که تمام مراحل ساخت سرویس، گواهی‌ها و ارتباط امن را تنها با **یک دستور** انجام می‌دهد و هیچ نیازی به ساخت دستی فایل‌های کانفیگ YAML ندارد.

### گام ۱: دریافت دستور نصب تانل از داشبورد کلودفلر
1. وارد پنل [Cloudflare Zero Trust Dashboard](https://one.dash.cloudflare.com/) شوید.
2. از منوی سمت چپ به مسیر **Networks > Tunnels** بروید.
3. روی دکمه **Add a tunnel** کلیک کرده و گزینه **Cloudflared** را انتخاب کنید.
4. یک نام دلخواه برای تانل وارد کنید (مثلاً `tgbot-tunnel`) و دکمه **Save tunnel** را بزنید.
5. در صفحه بعد، سیستم‌عامل **Debian** یا **Ubuntu** (معماری 64-bit) را انتخاب کنید.
6. کلودفلر یک دستور آماده حاوی توکن به شما نمایش می‌دهد که مشابه زیر است:

```bash
# دانلود و نصب پکیج deb کلودفلر
curl -L --output cloudflared.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb && sudo dpkg -i cloudflared.deb

# نصب و استارت سرویس تانل به صورت خودکار (توکن اختصاصی خود را از داشبورد کپی کنید)
sudo cloudflared service install <YOUR_TUNNEL_TOKEN>
```

دستور بالا را در ترمینال سرور اوبونتو اجرا کنید. سرویس `cloudflared` به صورت خودکار ساخته شده، فعال (`enabled`) شده و استارت می‌خورد.

### گام ۲: متصل کردن دامنه به پنل وب
1. در همان صفحه کلودفلر، تب **Public Hostnames** را انتخاب کنید.
2. روی دکمه **Add a public hostname** کلیک کنید:
   - **Subdomain:** ساب‌دامین مورد نظر (مثلاً `bot` یا `panel`)
   - **Domain:** دامنه ثبت‌شده شما در کلودفلر (مثلاً `yourdomain.com`)
   - **Type:** گزینه `HTTP` را انتخاب نمایید.
   - **URL:** مقدار `127.0.0.1:5000` (یا پورتی که در فایل `.env` پروژه برای پنل تنظیم کرده‌اید).
3. روی **Save hostname** کلیک کنید.

تمام! اکنون با باز کردن آدرس `https://panel.yourdomain.com` پنل مدیریت با SSL امن و معتبر در دسترس است.

---

## 🛠️ روش ۲: راه‌اندازی دستی تانل از طریق ترمینال (CLI - نسخه کاملاً اصلاح‌شده)

> [!WARNING]
> در راهنماهای قدیمی اینترنت، به دلیل ارجاع مسیر `credentials-file` به پوشه کاربر روت (`/root/.cloudflared/`)، سرویس سیستمی کلودفلر هنگام بوت با خطای **Permission Denied** مواجه شده و پس از ریبوت سرور متوقف می‌شد. دستورات زیر کاملاً استانداردسازی شده و بدون هیچ خطایی کار می‌کنند.

### ۱. نصب پکیج `cloudflared` روی اوبونتو:
```bash
curl -L --output cloudflared.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
sudo dpkg -i cloudflared.deb
rm -f cloudflared.deb
```

### ۲. ورود به حساب کلودفلر:
```bash
cloudflared tunnel login
```
لینکی در ترمینال نمایش داده می‌شود؛ آن را در مرورگر باز کرده و دامنه خود را تایید نمایید. فایل گواهی لاگین در `/root/.cloudflared/cert.pem` ذخیره می‌شود.

### ۳. ساخت تانل جدید:
```bash
cloudflared tunnel create tgbot-tunnel
```
خروجی این دستور شامل **Tunnel ID** (یک رشته ۳۶ کاراکتری مانند `a1b2c3d4-e5f6-...`) است.

### ۴. انتقال ایمن فایل مشخصات به دایرکتوری سیستمی:
برای اینکه سرویس سیستمی بدون خطای پرمیشن در زمان ریبوت اجرا شود، دایرکتوری `/etc/cloudflared` را ایجاد کرده و فایل اعتبارنامه را به آنجا کپی کنید:
```bash
sudo mkdir -p /etc/cloudflared
sudo cp ~/.cloudflared/*.json /etc/cloudflared/
```

### ۵. ساخت فایل پیکربندی استاندارد (`/etc/cloudflared/config.yml`):
فایل کانفیگ را با ادیتور باز کنید:
```bash
sudo nano /etc/cloudflared/config.yml
```
محتوای زیر را قرار دهید (شناسه تانل و نام دامنه را با مقادیر خودتان جایگزین کنید):

```yaml
tunnel: YOUR_TUNNEL_ID_HERE
credentials-file: /etc/cloudflared/YOUR_TUNNEL_ID_HERE.json

ingress:
  - hostname: panel.yourdomain.com
    service: http://127.0.0.1:5000
  - service: http_status:404
```
*(نکته: اگر پورت پنل را در پروژه تغییر داده‌اید، به جای ۵۰۰۰ پورت جدید را قرار دهید).*

### ۶. ایجاد خودکار رکورد DNS در کلودفلر:
```bash
cloudflared tunnel route dns tgbot-tunnel panel.yourdomain.com
```

### ۷. نصب و فعال‌سازی سرویس دائمی در استارت‌آپ بوت سیستم:
```bash
sudo cloudflared service install
sudo systemctl daemon-reload
sudo systemctl enable cloudflared
sudo systemctl restart cloudflared
```

### ۸. بررسی وضعیت اجرای تانل:
```bash
sudo systemctl status cloudflared
```
اگر وضعیت `active (running)` بود، تانل فعال است و پس از هر بار ریبوت سرور نیز به صورت خودکار اجرا خواهد شد.

---

## 🛡️ بهینه‌سازی تنظیمات فایروال کلودفلر (WAF & Bot Fight)

برای اینکه درخواست‌های تلگرام، وب‌اپ و وب‌سرویس‌ها بدون قطعی از فایروال کلودفلر عبور کنند:

1. **معاف‌سازی ربات‌های تلگرام در WAF:**
   - در پنل کلودفلر به تب **Security > WAF** بروید.
   - یک قانون جدید بسازید:
     - **Rule name:** `Allow Telegram`
     - **Field:** `User Agent` | **Operator:** `contains` | **Value:** `TelegramBot`
     - **Action:** `Skip` (تمامی گزینه‌های امنیتی را رد کند).
2. **وضعیت SSL/TLS:**
   - در منوی **SSL/TLS** وضعیت را روی **Full** قرار دهید.
3. **تنظیم Bot Fight Mode:**
   - در تب **Security > Bots**، قابلیت **Bot Fight Mode** را در صورت بروز مشکل در باز شدن تلگرام مینی‌اپ غیرفعال کنید تا سشن‌های وب‌اپ با چالش کپچا مواجه نشوند.
