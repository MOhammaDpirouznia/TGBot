# 🚀 راهنمای استقرار در محیط پروداکشن (Linux VPS Deployment Guide)

این راهنما مراحل کامل و گام‌به‌گام راه‌اندازی دائمی، امن و خودکار سامانه **HiddiBot** را بر روی سرور مجازی لینوکس (Ubuntu 20.04 / 22.04 / 24.04 یا Debian 11/12) آموزش می‌دهد.

---

## 📋 نیازمندی‌های سخت‌افزاری و نرم‌افزاری

- **سرور مجازی (VPS):** حداقل ۱ گیگابایت رم و ۱ هسته CPU
- **دسترسی:** کاربر `root` یا کاربری با دسترسی `sudo`
- **پورت‌های باز:** پورت ۸۰ (HTTP) و ۴۴۳ (HTTPS) در فایروال

---

## ۱. آماده‌سازی و آپدیت سیستم‌عامل

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip python3-venv git curl ufw nginx
```

---

## ۲. دانلود و استقرار پروژه

```bash
# ایجاد دایرکتوری اختصاصی
sudo mkdir -p /opt/hiddibot
sudo chown -R $USER:$USER /opt/hiddibot
cd /opt/hiddibot

# انتقال فایل‌های پروژه به این مسیر یا کلون گیت
# پس از قرار دادن فایل‌ها:
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
pip install gunicorn
```

---

## ۳. تنظیم متغیرهای محیطی (`.env`)

فایل `.env` را در پوشه `/opt/hiddibot` ایجاد یا ویرایش کنید:

```bash
cp .env.example .env
nano .env
```

اطلاعات زیر را تکمیل کنید:
- `BOT_TOKEN`: توکن ربات اصلی دریافت شده از `@BotFather`
- `ADMIN_ID`: شناسه عددی تلگرام شما
- `HIDIFY_PANEL_URL`: آدرس پنل هیدیفای (همراه با اسلش انتهایی)
- `HIDIFY_API_KEY`: کلید اختصاصی API هیدیفای
- `ADMIN_USERNAME` و `ADMIN_PASSWORD`: نام کاربری و رمز ورود به پنل وب
- `SECRET_KEY`: یک عبارت تصادفی و طولانی جهت امنیت Sessionها

---

## ۴. ساخت سرویس‌های سیستمی (Systemd Services)

برای اینکه ربات و پنل وب همیشه در پس‌زمینه در حال اجرا باشند و در صورت ریبوت سرور خودکار اجرا شوند، دو سرویس می‌سازیم:

### الف) سرویس داشبورد وب (`/etc/systemd/system/hiddibot-web.service`):

```ini
[Unit]
Description=HiddiBot Modern Web Dashboard
After=network.target

[Service]
User=root
WorkingDirectory=/opt/hiddibot
Environment="PATH=/opt/hiddibot/venv/bin"
ExecStart=/opt/hiddibot/venv/bin/gunicorn --workers 3 --bind 127.0.0.1:5000 dashboard:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### ب) سرویس ربات تلگرام (`/etc/systemd/system/hiddibot-bot.service`):

```ini
[Unit]
Description=HiddiBot Telegram Bot Daemon
After=network.target

[Service]
User=root
WorkingDirectory=/opt/hiddibot
Environment="PATH=/opt/hiddibot/venv/bin"
ExecStart=/opt/hiddibot/venv/bin/python bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### فعال‌سازی و استارت سرویس‌ها:

```bash
sudo systemctl daemon-reload
sudo systemctl enable hiddibot-web hiddibot-bot
sudo systemctl start hiddibot-web hiddibot-bot

# بررسی وضعیت اجرا:
sudo systemctl status hiddibot-web
sudo systemctl status hiddibot-bot
```

---

## ۵. پیکربندی وب‌سرور Nginx و گواهی SSL رایگان

فایل تنظیمات Nginx را ایجاد کنید:

```bash
sudo nano /etc/nginx/sites-available/hiddibot
```

محتوای زیر را قرار دهید (به جای `panel.yourdomain.com` دامنه خود را بنویسید):

```nginx
server {
    listen 80;
    server_name panel.yourdomain.com;

    client_max_body_size 50M;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

فعال‌سازی کانفیگ در Nginx:

```bash
sudo ln -s /etc/nginx/sites-available/hiddibot /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

### دریافت SSL رایگان با Certbot:

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d panel.yourdomain.com
```

---

## ۶. تنظیم فایروال (UFW)

```bash
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

تبریک! اکنون سامانه شما به صورت کاملاً حرفه‌ای و پایدار با امنیت بالا و دامنه اختصاصی در حال کار است.
