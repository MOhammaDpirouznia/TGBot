# ☁️ راهنمای اتصال و استقرار با کلودفلر (Cloudflare Integration & Tunneling)

استفاده از کلودفلر (Cloudflare) چندین مزیت فوق‌العاده برای سامانه HiddiBot به همراه دارد:
1. **پنهان‌سازی کامل IP اصلی سرور (Anti-DDoS & IP Masking)**
2. **اتصال بدون نیاز به پورت باز با Cloudflare Tunnel (دور زدن فیلترینگ و NAT)**
3. **SSL رایگان و خودکار (Full Strict)**
4. **توزیع ترافیک جهانی با تاخیر کم (Global Edge Caching & CDN)**

---

## 🚀 روش ۱: اتصال از طریق Cloudflare Tunnel (توصیه شده و فوق امن)

با استفاده از **Cloudflare Tunnel (`cloudflared`)**، بدون نیاز به باز کردن پورت‌های ۸۰ یا ۴۴۳ روی سرور و حتی بدون داشتن IP اختصاصی/ثابت، پنل وب به دامنه شما متصل می‌شود.

### ۱. نصب `cloudflared` روی سرور لینوکس:

```bash
# دانلود و نصب پکیج deb کلودفلر
curl -L --output cloudflared.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
sudo dpkg -i cloudflared.deb
```

### ۲. لاگین در اکانت کلودفلر:

```bash
cloudflared tunnel login
```
یک لینک در خروجی ترمینال نمایش داده می‌شود؛ آن را در مرورگر باز کرده و دامنه خود را تایید کنید.

### ۳. ساخت تانل جدید:

```bash
cloudflared tunnel create hiddibot-tunnel
```
این دستور یک فایل اعتبارنامه (`Credentials JSON`) و یک شناسه تانل (`Tunnel ID`) تولید می‌کند.

### ۴. ساخت فایل کانفیگ تانل (`/etc/cloudflared/config.yml`):

```bash
sudo mkdir -p /etc/cloudflared
sudo nano /etc/cloudflared/config.yml
```

محتوای زیر را وارد کنید (شناسه تانل و دامنه خود را جایگزین کنید):

```yaml
tunnel: YOUR_TUNNEL_ID_HERE
credentials-file: /root/.cloudflared/YOUR_TUNNEL_ID_HERE.json

ingress:
  - hostname: panel.yourdomain.com
    service: http://127.0.0.1:5000
  - service: http_status:404
```

### ۵. مسیردهی DNS و اجرای سرویس دائمی:

```bash
cloudflared tunnel route dns hiddibot-tunnel panel.yourdomain.com
sudo cloudflared service install
sudo systemctl start cloudflared
sudo systemctl enable cloudflared
```

اکنون دامنه `panel.yourdomain.com` به صورت آنی و با امنیت کامل کلودفلر متصل شده است!

---

## ⚡ روش ۲: اتصال به عنوان پروکسی معکوس (Cloudflare Reverse Proxy & DNS)

اگر سرور شما دارای IP ثابت است و از Nginx استفاده می‌کنید:

1. در پنل کلودفلر به تب **DNS > Records** بروید.
2. یک رکورد `A` برای زیردامنه خود ایجاد کنید:
   - **Type:** `A`
   - **Name:** `panel`
   - **IPv4 Address:** `آدرس IP سرور شما`
   - **Proxy status:** 🟧 **Proxied (ابری روشن)**
3. به تب **SSL/TLS** بروید و حالت رمزنگاری را روی **Full** یا **Full (strict)** قرار دهید.
4. در تب **SSL/TLS > Edge Certificates** گزینه **Always Use HTTPS** را فعال کنید.

---

## 🛡️ بهینه‌سازی تنظیمات امنیتی (WAF & Bot Fight)

برای اینکه وب‌هوک‌های تلگرام یا درخواست‌های API مسدود نشوند:

1. به تب **Security > WAF** بروید.
2. در بخش **Custom Rules** یک قانون مجازسازی برای تلگرام بسازید:
   - **Rule Name:** Allow Telegram
   - **Field:** `User Agent` contains `TelegramBot`
   - **Action:** `Skip / Bypass`
3. بخش **Bot Fight Mode**: توصیه می‌شود در صورت استفاده از تلگرام مینی‌اپ در حالت پیش‌فرض باقی بماند تا سشن‌های وب‌اپ دچار مسدودی نگردند.
