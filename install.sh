#!/usr/bin/env bash
# ==============================================================================
# 🚀 HiddiBot / TGBot - Multi-Language Automated Linux Installer
# ==============================================================================

set -e

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
echo "    🚀 Telegram Multi-Bot & VPN Automated Linux Installer        "
echo "=================================================================="
echo -e "${NC}"

# ۱. انتخاب زبان / Language Selection
echo -e "${BOLD}Select your language / زبان خود را انتخاب کنید:${NC}"
echo "1) فارسی (Persian) - [پیش‌فرض]"
echo "2) English"
echo "3) Русский (Russian)"
echo "4) 中文 (Chinese)"
read -p "Choice / انتخاب [1-4] (Default: 1): " LANG_INPUT
LANG_INPUT=${LANG_INPUT:-"1"}

case "$LANG_INPUT" in
    2) SYSTEM_LANG="en" ;;
    3) SYSTEM_LANG="ru" ;;
    4) SYSTEM_LANG="zh" ;;
    *) SYSTEM_LANG="fa" ;;
esac

# تنظیم پیام‌های بومی‌سازی شده
if [ "$SYSTEM_LANG" = "en" ]; then
    MSG_ROOT_ERR="❌ Please run this script with root privileges (sudo bash install.sh)."
    MSG_CHECK_DEPS="🔍 Checking system prerequisites and Linux packages..."
    MSG_WARN_DISTRO="⚠️ Your Linux distribution could not be fully identified, continuing with default packages..."
    MSG_CLONE="📦 Fetching the latest version of the project from GitHub..."
    MSG_UPDATE="Project already exists at $INSTALL_DIR. Updating to latest commit..."
    MSG_VENV="🐍 Setting up Python virtual environment and dependencies..."
    MSG_CLI_BOX="💡 Would you like to configure settings in the terminal (CLI) now?"
    MSG_CLI_NO="• No (Default): Fast start, you can configure everything in the web panel."
    MSG_CLI_YES="• Yes: Configure port, domain, SSL, admin ID directly in terminal."
    MSG_CLI_PROMPT="Configure in terminal? [y/N] (Default: N): "
    MSG_LICENSE="🔹 Product License Key (LICENSE_KEY): "
    MSG_PORT_IN_USE="⚠️ Notice: Port 5000 is occupied on this server (e.g. by another panel)."
    MSG_PORT_SUGG="💡 Suggested free port:"
    MSG_PORT_REQ="🔹 Desired port for web panel (Default: "
    MSG_PORT_ALT="⚠️ Port is currently occupied! Switching automatically to free port"
    MSG_TOKEN="🔹 Main Telegram Bot Token (Optional - press Enter to skip): "
    MSG_ADMIN="🔹 Super Admin Telegram Numeric ID (Optional - e.g. 12345678): "
    MSG_DOMAIN="🔹 Custom domain connected to server (Optional - e.g. panel.example.com): "
    MSG_SSL_PROMPT="Issue official Let's Encrypt SSL certificate for "
    MSG_SSL_GEN="🔒 Issuing free Let's Encrypt SSL certificate..."
    MSG_SSL_FAIL="⚠️ SSL certificate generation failed. You can issue it later via web panel."
    MSG_PORT_AUTO_OCC="⚠️ Notice: Default port 5000 is occupied."
    MSG_PORT_AUTO_OK="✅ Free port automatically selected:"
    MSG_SKIP_CLI="⏩ Skipping terminal configuration. Continue setup in browser."
    MSG_SVC_GEN="⚙️ Creating systemd service ($SERVICE_FILE)..."
    MSG_SUCCESS="🎉 Congratulations! System installed and activated successfully."
    MSG_ACCESS_TITLE="🌐 Access URLs for Web Panel and Initial Setup Wizard:"
    MSG_WIZARD_NOTE="💡 Important: Open the link above to access the Step-by-Step Setup Wizard."
    MSG_CMDS="🛠️ Useful service management commands:"
    MSG_CMD_STAT="• Status: "
    MSG_CMD_RESTART="• Restart: "
    MSG_CMD_LOGS="• Logs: "
    MSG_CMD_STOP="• Stop: "
elif [ "$SYSTEM_LANG" = "ru" ]; then
    MSG_ROOT_ERR="❌ Пожалуйста, запустите этот скрипт с правами root (sudo bash install.sh)."
    MSG_CHECK_DEPS="🔍 Проверка системных требований и пакетов Linux..."
    MSG_WARN_DISTRO="⚠️ Ваш дистрибутив Linux не был точно определён, продолжаем со стандартными пакетами..."
    MSG_CLONE="📦 Получение последней версии проекта из GitHub..."
    MSG_UPDATE="Проект уже существует в $INSTALL_DIR. Обновление..."
    MSG_VENV="🐍 Настройка виртуального окружения Python и зависимостей..."
    MSG_CLI_BOX="💡 Хотите выполнить начальную настройку в терминале (CLI) сейчас?"
    MSG_CLI_NO="• Нет (По умолчанию): Быстрый запуск, вы сможете настроить всё в веб-панели."
    MSG_CLI_YES="• Да: Настройка порта, домена, SSL и админа прямо в терминале."
    MSG_CLI_PROMPT="Настроить в терминале? [y/N] (По умолчанию: N): "
    MSG_LICENSE="🔹 Лицензионный ключ продукта (LICENSE_KEY): "
    MSG_PORT_IN_USE="⚠️ Внимание: Порт 5000 на этом сервере уже занят."
    MSG_PORT_SUGG="💡 Рекомендуемый свободный порт:"
    MSG_PORT_REQ="🔹 Порт для веб-панели (По умолчанию: "
    MSG_PORT_ALT="⚠️ Порт занят! Автоматическое переключение на свободный порт"
    MSG_BOT_TOKEN="🔹 Токен основного Telegram бота (Необязательно - нажмите Enter): "
    MSG_ADMIN="🔹 Telegram ID главного администратора (Необязательно - напр. 12345678): "
    MSG_DOMAIN="🔹 Домен сервера (Необязательно - напр. panel.example.com): "
    MSG_SSL_PROMPT="Выпустить сертификат Let's Encrypt SSL для "
    MSG_SSL_GEN="🔒 Выпуск бесплатного сертификата Let's Encrypt SSL..."
    MSG_SSL_FAIL="⚠️ Ошибка выпуска SSL. Вы сможете выпустить его позже в веб-панели."
    MSG_PORT_AUTO_OCC="⚠️ Внимание: Порт 5000 занят."
    MSG_PORT_AUTO_OK="✅ Автоматически выбран свободный порт:"
    MSG_SKIP_CLI="⏩ Настройка в терминале пропущена. Продолжите в браузере."
    MSG_SVC_GEN="⚙️ Создание службы systemd ($SERVICE_FILE)..."
    MSG_SUCCESS="🎉 Поздравляем! Система успешно установлена и активирована."
    MSG_ACCESS_TITLE="🌐 Ссылки для доступа к веб-панели и мастеру настройки:"
    MSG_WIZARD_NOTE="💡 Примечание: Перейдите по ссылке выше для завершения настройки в мастере."
    MSG_CMDS="🛠️ Полезные команды управления службой:"
    MSG_CMD_STAT="• Статус: "
    MSG_CMD_RESTART="• Перезапуск: "
    MSG_CMD_LOGS="• Логи: "
    MSG_CMD_STOP="• Остановка: "
elif [ "$SYSTEM_LANG" = "zh" ]; then
    MSG_ROOT_ERR="❌ 请使用 root 权限运行此脚本 (sudo bash install.sh)。"
    MSG_CHECK_DEPS="🔍 正在检查系统环境与 Linux 软件包..."
    MSG_WARN_DISTRO="⚠️ 无法完全识别您的 Linux 发行版，使用默认包继续..."
    MSG_CLONE="📦 正在从 GitHub 获取项目最新版本..."
    MSG_UPDATE="项目已存在于 $INSTALL_DIR。正在更新..."
    MSG_VENV="🐍 正在配置 Python 虚拟环境与依赖项..."
    MSG_CLI_BOX="💡 是否希望现在在终端命令行 (CLI) 中进行初始设置？"
    MSG_CLI_NO="• 否 (默认)：快速启动，稍后可在网页控制面板完成全部配置。"
    MSG_CLI_YES="• 是：在终端中直接配置端口、域名、SSL 证书等。"
    MSG_CLI_PROMPT="在终端中设置？ [y/N] (默认: N): "
    MSG_LICENSE="🔹 产品激活授权密钥 (LICENSE_KEY): "
    MSG_PORT_IN_USE="⚠️ 注意：此服务器上的端口 5000 已被占用。"
    MSG_PORT_SUGG="💡 建议的空闲端口："
    MSG_PORT_REQ="🔹 网页控制面板端口 (默认: "
    MSG_PORT_ALT="⚠️ 端口已被占用！自动切换至空闲端口"
    MSG_TOKEN="🔹 Telegram 主机器人令牌 (可选 - 直接回车跳过): "
    MSG_ADMIN="🔹 超级管理员 Telegram ID (可选 - 例如: 12345678): "
    MSG_DOMAIN="🔹 解析到服务器的域名 (可选 - 例如: panel.example.com): "
    MSG_SSL_PROMPT="是否为该域名申请 Let's Encrypt 官方 SSL 证书？ "
    MSG_SSL_GEN="🔒 正在申请免费 Let's Encrypt SSL 证书..."
    MSG_SSL_FAIL="⚠️ SSL 证书申请失败。您稍后可在网页面板中再次申请。"
    MSG_PORT_AUTO_OCC="⚠️ 注意：默认端口 5000 已被占用。"
    MSG_PORT_AUTO_OK="✅ 已自动选择空闲端口："
    MSG_SKIP_CLI="⏩ 跳过终端设置。请在浏览器中继续进行配置。"
    MSG_SVC_GEN="⚙️ 正在创建系统 systemd 服务 ($SERVICE_FILE)..."
    MSG_SUCCESS="🎉 恭喜！系统已成功安装并启动。"
    MSG_ACCESS_TITLE="🌐 网页控制面板与安装向导访问地址："
    MSG_WIZARD_NOTE="💡 提示：访问上方链接将进入初始设置向导，可进行数据恢复或可视化配置。"
    MSG_CMDS="🛠️ 常用服务管理命令："
    MSG_CMD_STAT="• 查看状态: "
    MSG_CMD_RESTART="• 重启服务: "
    MSG_CMD_LOGS="• 实时日志: "
    MSG_CMD_STOP="• 停止服务: "
else
    # Persian (fa)
    MSG_ROOT_ERR="❌ لطفاً این اسکریپت را با دسترسی root اجرا کنید (sudo bash install.sh)."
    MSG_CHECK_DEPS="🔍 در حال بررسی پیش‌نیازهای سیستم و پکیج‌های لینوکس..."
    MSG_WARN_DISTRO="⚠️ توزیع لینوکس شما به طور کامل شناسایی نشد، ادامه نصب با پیش‌فرض..."
    MSG_CLONE="📦 در حال دریافت آخرین نسخه پروژه از گیت‌هاب..."
    MSG_UPDATE="پروژه از قبل در مسیر $INSTALL_DIR موجود است. در حال بروزرسانی..."
    MSG_VENV="🐍 در حال راه‌اندازی محیط پایتون و نصب وابستگی‌ها..."
    MSG_CLI_BOX="💡 آیا مایلید تنظیمات اولیه را هم‌اکنون در خط فرمان (CLI) انجام دهید؟"
    MSG_CLI_NO="• با انتخاب خیر (پیش‌فرض): پروژه سریعاً استارت خورده و می‌توانید تمام تنظیمات را در محیط گرافیکی وب‌پنل انجام دهید."
    MSG_CLI_YES="• با انتخاب بله: مواردی نظیر نام کاربری، پورت، دامنه و دریافت SSL در ترمینال سوال می‌شود."
    MSG_CLI_PROMPT="آیا تنظیم در ترمینال انجام شود؟ [y/N] (پیش‌فرض: N): "
    MSG_LICENSE="🔹 کلید لایسنس فعال‌سازی محصول (LICENSE_KEY): "
    MSG_PORT_IN_USE="⚠️ توجه: پورت 5000 در این سرور اشغال است."
    MSG_PORT_SUGG="💡 پورت پیشنهادی آزاد:"
    MSG_PORT_REQ="🔹 پورت مورد نظر برای پنل وب (پیش‌فرض: "
    MSG_PORT_ALT="⚠️ پورت اشغال است! تغییر خودکار به پورت آزاد"
    MSG_TOKEN="🔹 توکن ربات اصلی تلگرام (اختیاری - برای تنظیم بعداً Enter بزنید): "
    MSG_ADMIN="🔹 شناسه عددی تلگرام ادمین ارشد (اختیاری - مثال 12345678): "
    MSG_DOMAIN="🔹 دامنه اختصاصی متصل به سرور (اختیاری - مثال: panel.example.com): "
    MSG_SSL_PROMPT="آیا مایلید گواهی رسمی SSL با Certbot صادر شود؟ "
    MSG_SSL_GEN="🔒 در حال صدور گواهی SSL رایگان Let's Encrypt..."
    MSG_SSL_FAIL="⚠️ دریافت گواهی خودکار با خطا مواجه شد. در وب‌پنل نیز می‌توانید گواهی صادر نمایید."
    MSG_PORT_AUTO_OCC="⚠️ توجه: پورت پیش‌فرض 5000 در سرور اشغال بود."
    MSG_PORT_AUTO_OK="✅ پورت آزاد به طور خودکار تعیین شد:"
    MSG_SKIP_CLI="⏩ رد کردن تنظیمات ترمینال. ادامه راه‌اندازی از طریق مرورگر انجام خواهد شد."
    MSG_SVC_GEN="⚙️ در حال ساخت سرویس سیستمی ($SERVICE_FILE)..."
    MSG_SUCCESS="🎉 تبریک! سامانه با موفقیت نصب و فعال‌سازی شد."
    MSG_ACCESS_TITLE="🌐 آدرس دسترسی به پنل وب و ویزارد راه‌اندازی اولیه:"
    MSG_WIZARD_NOTE="💡 نکته مهم: با ورود به لینک بالا، صفحه ویزارد راه‌اندازی گام به گام نمایش داده می‌شود."
    MSG_CMDS="🛠️ دستورات کاربردی مدیریت سرویس در سرور:"
    MSG_CMD_STAT="• مشاهده وضعیت:   "
    MSG_CMD_RESTART="• شروع مجدد:     "
    MSG_CMD_LOGS="• مشاهده لاگ‌ها:   "
    MSG_CMD_STOP="• توقف سرویس:     "
fi

# ۲. بررسی دسترسی روت
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}${MSG_ROOT_ERR}${NC}"
    exit 1
fi

# ۳. شناسایی سیستم‌عامل و نصب پکیج‌های پیش‌نیاز
echo -e "${BLUE}${MSG_CHECK_DEPS}${NC}"
if [ -f /etc/debian_version ]; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq python3 python3-pip python3-venv git curl wget openssl certbot python3-certbot-nginx socat
elif [ -f /etc/redhat-release ]; then
    if command -v dnf &>/dev/null; then
        dnf install -y python3 python3-pip git curl wget openssl certbot python3-certbot-nginx socat
    else
        yum install -y python3 python3-pip git curl wget openssl certbot python3-certbot-nginx socat
    fi
else
    echo -e "${YELLOW}${MSG_WARN_DISTRO}${NC}"
fi

# ۴. کلون یا بروزرسانی مخزن پروژه
echo -e "${BLUE}${MSG_CLONE}${NC}"
if [ -d "$INSTALL_DIR/.git" ]; then
    echo -e "${YELLOW}${MSG_UPDATE}${NC}"
    cd "$INSTALL_DIR"
    git fetch origin main
    git reset --hard origin/main
else
    mkdir -p "$INSTALL_DIR"
    git clone "$REPO_URL" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

# ۵. ساخت دایرکتوری‌های مورد نیاز
mkdir -p "$INSTALL_DIR/data"
mkdir -p "$INSTALL_DIR/data/receipts"
mkdir -p "$INSTALL_DIR/data/certs"
mkdir -p "$INSTALL_DIR/logs"

# ۶. راه‌اندازی Virtualenv و نصب وابستگی‌های پایتون
echo -e "${BLUE}${MSG_VENV}${NC}"
if [ ! -d "$INSTALL_DIR/venv" ]; then
    python3 -m venv "$INSTALL_DIR/venv"
fi
"$INSTALL_DIR/venv/bin/pip" install --upgrade pip -q
"$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt" -q

# ۷. شناسایی آی‌پی عمومی سرور
SERVER_IP=$(curl -s --max-time 5 https://api.ipify.org || curl -s --max-time 5 https://ifconfig.me || hostname -I | awk '{print $1}')
SERVER_IP=${SERVER_IP:-"127.0.0.1"}

# تولید DASHBOARD_SECRET تصادفی ایمن
RANDOM_SECRET=$(openssl rand -hex 16 2>/dev/null || echo "hiddibot-secret-$(date +%s)")

# ۸. توابع بررسی تداخل پورت
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
echo -e "${GREEN}${BOLD}${MSG_CLI_BOX}${NC}"
echo -e "${YELLOW}${MSG_CLI_NO}${NC}"
echo -e "${YELLOW}${MSG_CLI_YES}${NC}"
echo -e "${PURPLE}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

read -p "${MSG_CLI_PROMPT}" CLI_CHOICE
CLI_CHOICE=${CLI_CHOICE:-"N"}

ENV_FILE="$INSTALL_DIR/.env"
CUSTOM_DOMAIN=""
BOT_TOKEN=""
ADMIN_ID=""

if [[ "$CLI_CHOICE" =~ ^[Yy]$ ]]; then
    echo ""
    read -p "${MSG_LICENSE}" INPUT_LICENSE
    LICENSE_KEY=${INPUT_LICENSE:-""}

    SUGGESTED_PORT=$(find_next_free_port 5000)
    if is_port_in_use 5000; then
        echo -e "${YELLOW}${MSG_PORT_IN_USE}${NC}"
        echo -e "${CYAN}${MSG_PORT_SUGG} ${BOLD}$SUGGESTED_PORT${NC}"
        read -p "${MSG_PORT_REQ}$SUGGESTED_PORT): " INPUT_PORT
        APP_PORT=${INPUT_PORT:-"$SUGGESTED_PORT"}
    else
        read -p "${MSG_PORT_REQ}5000): " INPUT_PORT
        APP_PORT=${INPUT_PORT:-"5000"}
    fi

    if is_port_in_use "$APP_PORT"; then
        ALT_PORT=$(find_next_free_port $((APP_PORT + 1)))
        echo -e "${RED}${MSG_PORT_ALT} $ALT_PORT${NC}"
        APP_PORT="$ALT_PORT"
    fi

    read -p "${MSG_TOKEN}" INPUT_TOKEN
    BOT_TOKEN=${INPUT_TOKEN:-""}

    read -p "${MSG_ADMIN}" INPUT_ADMIN
    ADMIN_ID=${INPUT_ADMIN:-""}

    read -p "${MSG_DOMAIN}" INPUT_DOMAIN
    CUSTOM_DOMAIN=${INPUT_DOMAIN:-""}

    if [ -n "$CUSTOM_DOMAIN" ]; then
        read -p "${MSG_SSL_PROMPT}[$CUSTOM_DOMAIN]? [Y/n]: " SSL_CHOICE
        SSL_CHOICE=${SSL_CHOICE:-"Y"}
        if [[ "$SSL_CHOICE" =~ ^[Yy]$ ]]; then
            echo -e "${BLUE}${MSG_SSL_GEN}${NC}"
            certbot certonly --standalone -d "$CUSTOM_DOMAIN" --non-interactive --agree-tos --register-unsafely-without-email || {
                echo -e "${YELLOW}${MSG_SSL_FAIL}${NC}"
            }
        fi
    fi
else
    if is_port_in_use 5000; then
        APP_PORT=$(find_next_free_port 5001)
        echo -e "${YELLOW}${MSG_PORT_AUTO_OCC}${NC}"
        echo -e "${GREEN}${MSG_PORT_AUTO_OK} ${BOLD}$APP_PORT${NC}"
    else
        APP_PORT="5000"
    fi
    echo -e "${GREEN}${MSG_SKIP_CLI}${NC}"
fi

# ۹. ایجاد فایل .env با ذخیره زبان سیستم
cat <<EOF > "$ENV_FILE"
PORT=$APP_PORT
PANEL_PORT=$APP_PORT
HOST=0.0.0.0
DATA_DIR=$INSTALL_DIR/data
DASHBOARD_SECRET=$RANDOM_SECRET
SYSTEM_LANG=$SYSTEM_LANG
DEFAULT_LANGUAGE=$SYSTEM_LANG
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

# ۱۰. ساخت و فعال‌سازی سرویس Systemd
SERVICE_NAME="tgbot"
if [ -f "/etc/systemd/system/tgbot.service" ]; then
    EXISTING_DIR=$(grep -E "^WorkingDirectory=" /etc/systemd/system/tgbot.service 2>/dev/null | cut -d'=' -f2)
    if [ -n "$EXISTING_DIR" ] && [ "$EXISTING_DIR" != "$INSTALL_DIR" ]; then
        SERVICE_NAME="tgbot-$(basename "$INSTALL_DIR")"
    fi
fi

SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
echo -e "${BLUE}${MSG_SVC_GEN}${NC}"

cat <<EOF > "$SERVICE_FILE"
[Unit]
Description=Telegram Multi-Bot & VPN Management Service ($SERVICE_NAME)
After=network.target network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/venv/bin/python run.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1
EnvironmentFile=-$INSTALL_DIR/.env
MemoryHigh=600M
MemoryMax=850M
CPUQuota=100%

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable ${SERVICE_NAME}.service
systemctl restart ${SERVICE_NAME}.service

# ۱۱. نمایش پیام موفقیت نهایی
echo ""
echo -e "${GREEN}${BOLD}==================================================================${NC}"
echo -e "${GREEN}${BOLD}        ${MSG_SUCCESS}           ${NC}"
echo -e "${GREEN}${BOLD}==================================================================${NC}"
echo ""
echo -e "${BOLD}${MSG_ACCESS_TITLE}${NC}"

if [ -n "$CUSTOM_DOMAIN" ]; then
    echo -e "   👉 ${CYAN}${BOLD}http://$CUSTOM_DOMAIN:$APP_PORT/setup${NC}"
fi
echo -e "   👉 ${CYAN}${BOLD}http://$SERVER_IP:$APP_PORT/setup${NC}"

echo ""
echo -e "${YELLOW}${MSG_WIZARD_NOTE}${NC}"
echo ""
echo -e "${BOLD}${MSG_CMDS}${NC}"
echo -e "   ${MSG_CMD_STAT}${CYAN}systemctl status ${SERVICE_NAME}${NC}"
echo -e "   ${MSG_CMD_RESTART}${CYAN}systemctl restart ${SERVICE_NAME}${NC}"
echo -e "   ${MSG_CMD_LOGS}${CYAN}journalctl -u ${SERVICE_NAME} -f${NC}"
echo -e "   ${MSG_CMD_STOP}${CYAN}systemctl stop ${SERVICE_NAME}${NC}"
echo ""
echo -e "${GREEN}${BOLD}==================================================================${NC}"
