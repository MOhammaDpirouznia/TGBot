#!/usr/bin/env bash
# ==============================================================================
# 🚀 HiddiBot / TGBot - اسکریپت نصب و راه‌اندازی خودکار سرور لینوکس
# قابلیت اجرای مستقیم از گیت‌هاب با دستور:
# bash <(curl -sL https://raw.githubusercontent.com/MOhammaDpirouznia/TGBot/main/install.sh)
# ==============================================================================

set -e

# رنگ‌ها برای خروجی زیبا
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color
BOLD='\033[1m'

INSTALL_DIR="/opt/tgbot"
REPO_URL="https://github.com/MOhammaDpirouznia/TGBot.git"

echo -e "${CYAN}${BOLD}"
echo "=================================================================="
echo "    🚀 سامانه جامع مدیریت هوشمند فروش VPN و ربات‌های تلگرام     "
echo "           HiddiBot / TGBot Linux Automated Installer             "
echo "=================================================================="
echo -e "${NC}"

# ۱. بررسی دسترسی روت
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}❌ لطفاً این اسکریپت را با دسترسی root اجرا کنید (sudo bash install.sh).${NC}"
    exit 1
fi

# ۲. شناسایی سیستم‌عامل و نصب پکیج‌های پیش‌نیاز
echo -e "${BLUE}🔍 در حال بررسی پیش‌نیازهای سیستم و پکیج‌های لینوکس...${NC}"
if [ -f /etc/debian_version ]; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq python3 python3-pip python3-venv git curl wget openssl certbot socat
elif [ -f /etc/redhat-release ]; then
    if command -v dnf &>/dev/null; then
        dnf install -y python3 python3-pip git curl wget openssl certbot socat
    else
        yum install -y python3 python3-pip git curl wget openssl certbot socat
    fi
else
    echo -e "${YELLOW}⚠️ توزیع لینوکس شما به طور کامل شناسایی نشد، ادامه نصب با پیش‌فرض...${NC}"
fi

# ۳. کلون یا بروزرسانی مخزن پروژه
echo -e "${BLUE}📦 در حال دریافت آخرین نسخه پروژه از گیت‌هاب...${NC}"
if [ -d "$INSTALL_DIR/.git" ]; then
    echo -e "${YELLOW}پروژه از قبل در مسیر $INSTALL_DIR موجود است. در حال بروزرسانی...${NC}"
    cd "$INSTALL_DIR"
    git fetch origin main
    git reset --hard origin/main
else
    mkdir -p "$INSTALL_DIR"
    git clone "$REPO_URL" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

# ۴. ساخت دایرکتوری‌های مورد نیاز
mkdir -p "$INSTALL_DIR/data"
mkdir -p "$INSTALL_DIR/data/receipts"
mkdir -p "$INSTALL_DIR/data/certs"
mkdir -p "$INSTALL_DIR/logs"

# ۵. راه‌اندازی Virtualenv و نصب وابستگی‌های پایتون
echo -e "${BLUE}🐍 در حال راه‌اندازی محیط پایتون و نصب وابستگی‌ها...${NC}"
if [ ! -d "$INSTALL_DIR/venv" ]; then
    python3 -m venv "$INSTALL_DIR/venv"
fi
"$INSTALL_DIR/venv/bin/pip" install --upgrade pip -q
"$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt" -q

# ۶. شناسایی آی‌پی عمومی سرور
SERVER_IP=$(curl -s --max-time 5 https://api.ipify.org || curl -s --max-time 5 https://ifconfig.me || hostname -I | awk '{print $1}')
SERVER_IP=${SERVER_IP:-"127.0.0.1"}

# تولید DASHBOARD_SECRET تصادفی ایمن
RANDOM_SECRET=$(openssl rand -hex 16 2>/dev/null || echo "hiddibot-secret-$(date +%s)")

# ۷. بررسی تداخل پورت و توابع هوشمند هم‌زیستی پروژه‌ها
is_port_in_use() {
    local p="$1"
    if command -v ss >/dev/null 2>&1; then
        ss -tuln 2>/dev/null | grep -qE "[: ]$p[ ]" && return 0
    elif command -v netstat >/dev/null 2>&1; then
        netstat -tuln 2>/dev/null | grep -qE "[: ]$p[ ]" && return 0
    elif command -v lsof >/dev/null 2>&1; then
        lsof -i:"$p" >/dev/null 2>&1 && return 0
    elif command -v fuser >/dev/null 2>&1; then
        fuser "$p/tcp" >/dev/null 2>&1 && return 0
    fi
    return 1
}

find_next_free_port() {
    local start_p="$1"
    local check_p="$start_p"
    while [ "$check_p" -le 65535 ]; do
        if ! is_port_in_use "$check_p"; then
            echo "$check_p"
            return 0
        fi
        check_p=$((check_p + 1))
    done
    echo "$start_p"
}

echo ""
echo -e "${PURPLE}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}${BOLD}💡 آیا مایلید تنظیمات اولیه را هم‌اکنون در خط فرمان (CLI) انجام دهید؟${NC}"
echo -e "${YELLOW}• با انتخاب خیر (پیش‌فرض):${NC} پروژه سریعاً استارت خورده و می‌توانید تمام تنظیمات را در محیط گرافیکی وب‌پنل انجام دهید."
echo -e "${YELLOW}• با انتخاب بله:${NC} مواردی نظیر نام کاربری، پورت، دامنه و دریافت SSL در ترمینال سوال می‌شود."
echo -e "${PURPLE}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

read -p "آیا تنظیم در ترمینال انجام شود؟ [y/N] (پیش‌فرض: N): " CLI_CHOICE
CLI_CHOICE=${CLI_CHOICE:-"N"}

ENV_FILE="$INSTALL_DIR/.env"
CUSTOM_DOMAIN=""
BOT_TOKEN=""
ADMIN_ID=""

if [[ "$CLI_CHOICE" =~ ^[Yy]$ ]]; then
    echo ""
    echo -e "${CYAN}⚙️ پیکربندی گام به گام در ترمینال:${NC}"
    
    read -p "🔹 کلید لایسنس فعال‌سازی محصول (LICENSE_KEY): " INPUT_LICENSE
    LICENSE_KEY=${INPUT_LICENSE:-""}

    SUGGESTED_PORT=$(find_next_free_port 5000)
    if is_port_in_use 5000; then
        echo -e "${YELLOW}⚠️ توجه: پورت 5000 در این سرور اشغال است (احتمالاً توسط هیدیفای، لایسنس‌هاب یا پروژه‌ای دیگر).${NC}"
        echo -e "${CYAN}💡 پورت پیشنهادی آزاد: ${BOLD}$SUGGESTED_PORT${NC}"
        read -p "🔹 پورت مورد نظر برای پنل وب (پیش‌فرض: $SUGGESTED_PORT): " INPUT_PORT
        APP_PORT=${INPUT_PORT:-"$SUGGESTED_PORT"}
    else
        read -p "🔹 پورت مورد نظر برای پنل وب (پیش‌فرض: 5000): " INPUT_PORT
        APP_PORT=${INPUT_PORT:-"5000"}
    fi

    # بررسی نهایی در دسترس بودن پورت انتخابی
    if is_port_in_use "$APP_PORT"; then
        ALT_PORT=$(find_next_free_port $((APP_PORT + 1)))
        echo -e "${RED}⚠️ پورت $APP_PORT نیز در حال حاضر اشغال است! تغییر خودکار به پورت آزاد $ALT_PORT${NC}"
        APP_PORT="$ALT_PORT"
    fi

    read -p "🔹 توکن ربات اصلی تلگرام (اختیاری - برای تنظیم بعداً Enter بزنید): " INPUT_TOKEN
    BOT_TOKEN=${INPUT_TOKEN:-""}

    read -p "🔹 شناسه عددی تلگرام ادمین ارشد (اختیاری - مثال 12345678): " INPUT_ADMIN
    ADMIN_ID=${INPUT_ADMIN:-""}

    read -p "🔹 دامنه اختصاصی متصل به سرور (اختیاری - مثال: panel.example.com): " INPUT_DOMAIN
    CUSTOM_DOMAIN=${INPUT_DOMAIN:-""}

    if [ -n "$CUSTOM_DOMAIN" ]; then
        read -p "آیا مایلید گواهی رسمی SSL با Certbot برای $CUSTOM_DOMAIN صادر شود؟ [Y/n]: " SSL_CHOICE
        SSL_CHOICE=${SSL_CHOICE:-"Y"}
        if [[ "$SSL_CHOICE" =~ ^[Yy]$ ]]; then
            echo -e "${BLUE}🔒 در حال صدور گواهی SSL رایگان Let's Encrypt...${NC}"
            certbot certonly --standalone -d "$CUSTOM_DOMAIN" --non-interactive --agree-tos --register-unsafely-without-email || {
                echo -e "${YELLOW}⚠️ دریافت گواهی خودکار با خطا مواجه شد. در وب‌پنل نیز می‌توانید گواهی صادر نمایید.${NC}"
            }
        fi
    fi
else
    # انتخاب خودکار پورت با بررسی اشغال بودن پورت 5000
    if is_port_in_use 5000; then
        APP_PORT=$(find_next_free_port 5001)
        echo -e "${YELLOW}⚠️ توجه: پورت پیش‌فرض 5000 در سرور اشغال بود (تداخل با سایر پروژه‌ها).${NC}"
        echo -e "${GREEN}✅ پورت آزاد ${BOLD}$APP_PORT${NC}${GREEN} به طور خودکار تعیین شد.${NC}"
    else
        APP_PORT="5000"
    fi
    echo -e "${GREEN}⏩ رد کردن تنظیمات ترمینال. ادامه راه‌اندازی از طریق مرورگر انجام خواهد شد.${NC}"
fi

# ۸. ایجاد فایل .env
cat <<EOF > "$ENV_FILE"
PORT=$APP_PORT
PANEL_PORT=$APP_PORT
HOST=0.0.0.0
DATA_DIR=$INSTALL_DIR/data
DASHBOARD_SECRET=$RANDOM_SECRET
EOF

if [ -n "$LICENSE_KEY" ]; then
    echo "LICENSE_KEY=$LICENSE_KEY" >> "$ENV_FILE"
fi
if [ -n "$BOT_TOKEN" ]; then
    echo "BOT_TOKEN=$BOT_TOKEN" >> "$ENV_FILE"
fi
if [ -n "$ADMIN_ID" ]; then
    echo "ADMIN_ID=$ADMIN_ID" >> "$ENV_FILE"
fi
if [ -n "$CUSTOM_DOMAIN" ]; then
    echo "CUSTOM_DOMAIN=$CUSTOM_DOMAIN" >> "$ENV_FILE"
fi

# ۹. ساخت و فعال‌سازی سرویس Systemd با تفکیک چندنسخه‌ای و حفاظت از رم
SERVICE_NAME="tgbot"
if [ -f "/etc/systemd/system/tgbot.service" ]; then
    EXISTING_DIR=$(grep -E "^WorkingDirectory=" /etc/systemd/system/tgbot.service 2>/dev/null | cut -d'=' -f2)
    if [ -n "$EXISTING_DIR" ] && [ "$EXISTING_DIR" != "$INSTALL_DIR" ]; then
        SERVICE_NAME="tgbot-$(basename "$INSTALL_DIR")"
        echo -e "${YELLOW}⚠️ یک سرویس TGBot دیگر در مسیر $EXISTING_DIR ثبت شده است.${NC}"
        echo -e "${CYAN}📌 نام سرویس مستقل این پروژه: ${BOLD}$SERVICE_NAME.service${NC}"
    fi
fi

SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
echo -e "${BLUE}⚙️ در حال ساخت سرویس سیستمی ($SERVICE_FILE)...${NC}"

cat <<EOF > "$SERVICE_FILE"
[Unit]
Description=Telegram Multi-Bot & VPN Management Service ($SERVICE_NAME)
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/venv/bin/python run.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1
EnvironmentFile=-$INSTALL_DIR/.env
# محدودیت هوشمند منابع در صورت هم‌زیستی با هیدیفای و سایر سرویس‌ها
MemoryHigh=600M
MemoryMax=850M
CPUQuota=100%

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable ${SERVICE_NAME}.service
systemctl restart ${SERVICE_NAME}.service

# ۱۰. نمایش پیام موفقیت نهایی
echo ""
echo -e "${GREEN}${BOLD}==================================================================${NC}"
echo -e "${GREEN}${BOLD}        🎉 تبریک! سامانه با موفقیت نصب و فعال‌سازی شد.           ${NC}"
echo -e "${GREEN}${BOLD}==================================================================${NC}"
echo ""
echo -e "${BOLD}🌐 آدرس دسترسی به پنل وب و ویزارد راه‌اندازی اولیه:${NC}"

if [ -n "$CUSTOM_DOMAIN" ]; then
    echo -e "   👉 ${CYAN}${BOLD}http://$CUSTOM_DOMAIN:$APP_PORT/setup${NC}"
fi
echo -e "   👉 ${CYAN}${BOLD}http://$SERVER_IP:$APP_PORT/setup${NC}"

echo ""
echo -e "${YELLOW}💡 نکته مهم:${NC} با ورود به لینک بالا، صفحه ویزارد راه‌اندازی گام به گام نمایش داده می‌شود"
echo "که می‌توانید دیتابیس قبلی خود را بازگردانی کرده یا متغیرها را داینامیک تنظیم نمایید."
echo ""
echo -e "${BOLD}🛠️ دستورات کاربردی مدیریت سرویس در سرور:${NC}"
echo -e "   • مشاهده وضعیت:   ${CYAN}systemctl status ${SERVICE_NAME}${NC}"
echo -e "   • شروع مجدد:     ${CYAN}systemctl restart ${SERVICE_NAME}${NC}"
echo -e "   • مشاهده لاگ‌ها:   ${CYAN}journalctl -u ${SERVICE_NAME} -f${NC}"
echo -e "   • توقف سرویس:     ${CYAN}systemctl stop ${SERVICE_NAME}${NC}"
echo ""
echo -e "${GREEN}${BOLD}==================================================================${NC}"
