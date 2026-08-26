#!/bin/bash

# رنگ‌ها
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}شروع ربات تلگرام VPN...${NC}"

# بررسی وجود Python
if ! command -v python &> /dev/null; then
    echo -e "${RED}Python پیدا نشد! لطفاً Python را نصب کنید.${NC}"
    exit 1
fi

# نصب وابستگی‌ها
echo -e "${YELLOW}در حال نصب وابستگی‌ها...${NC}"
pip install -r requirements.txt

# اجرای ربات
echo -e "${GREEN}در حال اجرای ربات...${NC}"
echo -e "${YELLOW}برای توقف، Ctrl+C را بزنید.${NC}"
python bot.py
