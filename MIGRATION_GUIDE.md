# 🔄 راهنمای بکاپ، بازیابی و مهاجرت به سرور جدید (Zero-Downtime Migration Guide)

سامانه **HiddiBot** به گونه‌ای معماری شده است که تمامی اطلاعات (کاربران، اشتراک‌ها، تنظیمات، فیش‌ها، لاگ‌ها و آواتارها) به صورت کاملاً ایزوله در پوشه‌های `data/` و `cache_avatars/` ذخیره می‌شوند. این ویژگی انتقال به سرور جدید را در چند ثانیه ممکن می‌سازد.

---

## 📦 ۱. پشتیبان‌گیری کامل از سرور فعلی (Backup)

برای ساخت یک فایل فشرده کامل از تمام داده‌ها:

```bash
cd /opt/hiddibot

# متوقف کردن موقت سرویس‌ها جهت تضمین یکپارچگی دیتابیس (اختیاری):
sudo systemctl stop hiddibot-bot hiddibot-web

# ساخت فایل پشتیبان زیپ با تاریخ روز:
tar -czvf /root/hiddibot_backup_$(date +%F).tar.gz \
    --exclude='venv' \
    --exclude='__pycache__' \
    --exclude='.git' \
    /opt/hiddibot

# استارت مجدد سرویس‌ها:
sudo systemctl start hiddibot-bot hiddibot-web
```

اکنون فایل پشتیبان در مسیر `/root/hiddibot_backup_YYYY-MM-DD.tar.gz` آماده است.

---

## 🚀 ۲. انتقال مستقیم به سرور جدید (Transfer)

از طریق دستور `scp` فایل را از سرور فعلی به سرور جدید منتقل کنید:

```bash
# اجرا روی سرور مبدا:
scp /root/hiddibot_backup_*.tar.gz root@NEW_SERVER_IP:/root/
```

---

## 🛠️ ۳. بازیابی و راه‌اندازی روی سرور جدید (Restore)

روی سرور جدید وارد شوید و مراحل زیر را اجرا کنید:

```bash
# نصب پیش‌نیازها
sudo apt update && sudo apt install -y python3 python3-pip python3-venv git curl nginx

# استخراج فایل‌ها در مسیر هدف
sudo mkdir -p /opt/hiddibot
tar -xzvf /root/hiddibot_backup_*.tar.gz -C /

# ساخت مجدد محیط پایتون
cd /opt/hiddibot
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
pip install gunicorn

# فعال‌سازی سرویس‌ها (مطابق راهنمای DEPLOYMENT.md)
sudo systemctl daemon-reload
sudo systemctl enable hiddibot-web hiddibot-bot
sudo systemctl start hiddibot-web hiddibot-bot
```

تمام اطلاعات، سوابق کاربران، آواتارها و تنظیمات بدون هیچ‌گونه اتلافی با موفقیت به سرور جدید منتقل شد.
