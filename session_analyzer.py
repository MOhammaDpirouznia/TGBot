#!/usr/bin/env python3
"""
ماژول تحلیل هوشمند نشست‌ها، کلاینت‌های VPN و دستگاه‌های متصل (Session & Client Analyzer)
شناسایی برنامه‌های Hiddify Next, Happ, Streisand, v2rayNG, Sing-box, FoXray, Shadowrocket و...
"""

import re
from typing import Dict, Any, Optional


def parse_user_agent_details(user_agent: str, client_ip: str = "") -> Dict[str, Any]:
    """
    تحلیل رشته User-Agent و استخراج مشخصات دقیق کلاینت، سیستم‌عامل و نام دستگاه
    """
    ua = str(user_agent or "").strip()
    ip = str(client_ip or "").strip()

    client_app = "سایر کلاینت‌ها / وب"
    app_icon = "fas fa-globe"
    client_version = ""
    os_name = "نامشخص"
    os_icon = "fab fa-ubuntu"
    device_name = "دستگاه ناشناس"

    # ۱. شناسایی برنامه کلاینت (Client Application)
    ua_lower = ua.lower()

    if "hiddifynext" in ua_lower or "hiddify" in ua_lower:
        client_app = "Hiddify Next"
        app_icon = "fas fa-rocket text-primary"
        m = re.search(r"hiddify(?:next)?[\s/vV]*([0-9\.]+)", ua, re.IGNORECASE)
        if m:
            client_version = f"v{m.group(1)}"
    elif "happ" in ua_lower:
        client_app = "Happ Proxy"
        app_icon = "fas fa-bolt text-warning"
        m = re.search(r"happ[\s/vV]*([0-9\.]+)", ua, re.IGNORECASE)
        if m:
            client_version = f"v{m.group(1)}"
    elif "streisand" in ua_lower:
        client_app = "Streisand"
        app_icon = "fas fa-shield-halved text-info"
        m = re.search(r"streisand[\s/vV]*([0-9\.]+)", ua, re.IGNORECASE)
        if m:
            client_version = f"v{m.group(1)}"
    elif "v2rayng" in ua_lower or "v2ray" in ua_lower:
        client_app = "v2rayNG"
        app_icon = "fab fa-android text-success"
        m = re.search(r"v2rayng[\s/vV]*([0-9\.]+)", ua, re.IGNORECASE)
        if m:
            client_version = f"v{m.group(1)}"
    elif "sing-box" in ua_lower or "singbox" in ua_lower:
        client_app = "Sing-box"
        app_icon = "fas fa-cube text-primary"
        m = re.search(r"sing-?box[\s/vV]*([0-9\.]+)", ua, re.IGNORECASE)
        if m:
            client_version = f"v{m.group(1)}"
    elif "foxray" in ua_lower:
        client_app = "FoXray"
        app_icon = "fas fa-paw text-danger"
        m = re.search(r"foxray[\s/vV]*([0-9\.]+)", ua, re.IGNORECASE)
        if m:
            client_version = f"v{m.group(1)}"
    elif "shadowrocket" in ua_lower:
        client_app = "Shadowrocket"
        app_icon = "fas fa-paper-plane text-warning"
        m = re.search(r"shadowrocket[\s/vV]*([0-9\.]+)", ua, re.IGNORECASE)
        if m:
            client_version = f"v{m.group(1)}"
    elif "clash" in ua_lower or "mihomo" in ua_lower or "clashmeta" in ua_lower:
        client_app = "Clash / Mihomo"
        app_icon = "fas fa-cat text-danger"
        m = re.search(r"(?:clash|mihomo)[\s/vV]*([0-9\.]+)", ua, re.IGNORECASE)
        if m:
            client_version = f"v{m.group(1)}"
    elif "nekobox" in ua_lower or "nekoray" in ua_lower:
        client_app = "NekoBox"
        app_icon = "fas fa-box text-secondary"
        m = re.search(r"neko(?:box|ray)[\s/vV]*([0-9\.]+)", ua, re.IGNORECASE)
        if m:
            client_version = f"v{m.group(1)}"
    elif "karing" in ua_lower:
        client_app = "Karing"
        app_icon = "fas fa-ring text-info"
        m = re.search(r"karing[\s/vV]*([0-9\.]+)", ua, re.IGNORECASE)
        if m:
            client_version = f"v{m.group(1)}"
    elif "v2box" in ua_lower:
        client_app = "V2Box"
        app_icon = "fas fa-cube text-success"
        m = re.search(r"v2box[\s/vV]*([0-9\.]+)", ua, re.IGNORECASE)
        if m:
            client_version = f"v{m.group(1)}"
    elif "telegram" in ua_lower:
        client_app = "Telegram WebApp"
        app_icon = "fab fa-telegram text-info"
    elif "chrome" in ua_lower:
        client_app = "Google Chrome"
        app_icon = "fab fa-chrome text-danger"
    elif "firefox" in ua_lower:
        client_app = "Mozilla Firefox"
        app_icon = "fab fa-firefox text-warning"
    elif "safari" in ua_lower:
        client_app = "Apple Safari"
        app_icon = "fab fa-safari text-primary"

    # ۲. شناسایی سیستم‌عامل (OS Name) و دستگاه (Device)
    if "iphone" in ua_lower or "ipad" in ua_lower or "ios" in ua_lower or "darwin" in ua_lower:
        os_name = "iOS / Apple"
        os_icon = "fab fa-apple text-dark"
        if "iphone" in ua_lower:
            device_name = "گوشی آیفون (iPhone)"
        elif "ipad" in ua_lower:
            device_name = "تبلت آیپد (iPad)"
        else:
            device_name = "دستگاه اپل (iOS)"
        # استخراج نسخه iOS
        m_ios = re.search(r"os\s+([0-9_]+)", ua_lower)
        if m_ios:
            os_name = f"iOS {m_ios.group(1).replace('_', '.')}"
    elif "android" in ua_lower:
        os_name = "Android"
        os_icon = "fab fa-android text-success"
        device_name = "گوشی اندروید"
        m_and = re.search(r"android\s+([0-9\.]+)", ua_lower)
        if m_and:
            os_name = f"Android {m_and.group(1)}"
        m_dev = re.search(r";\s*([^;]+?)\s*build", ua, re.IGNORECASE)
        if m_dev:
            device_name = m_dev.group(1).strip()
    elif "windows" in ua_lower or "win64" in ua_lower or "win32" in ua_lower:
        os_name = "Windows"
        os_icon = "fab fa-windows text-primary"
        device_name = "رایانه شخصی (PC)"
        if "windows nt 10.0" in ua_lower:
            os_name = "Windows 10/11"
    elif "macintosh" in ua_lower or "mac os" in ua_lower:
        os_name = "macOS"
        os_icon = "fab fa-apple text-dark"
        device_name = "مک‌بوک / آی‌مک"
    elif "linux" in ua_lower:
        os_name = "Linux"
        os_icon = "fab fa-linux text-warning"
        device_name = "لینوکس"

    # ۳. تشخیص اپراتور بر اساس محدوده آی‌پی‌های رایج ایران
    isp_name = "اینترنت ایران"
    isp_badge = "bg-secondary"
    if ip:
        if ip.startswith("5.127.") or ip.startswith("5.120.") or ip.startswith("2.188."):
            isp_name = "ایرانسل (MTN)"
            isp_badge = "bg-warning text-dark"
        elif ip.startswith("2.144.") or ip.startswith("91.99.") or ip.startswith("91.98."):
            isp_name = "همراه اول (MCI)"
            isp_badge = "bg-info text-dark"
        elif ip.startswith("5.106.") or ip.startswith("2.187."):
            isp_name = "رایتل (RighTel)"
            isp_badge = "bg-danger"
        elif ip.startswith("5.238.") or ip.startswith("185.105."):
            isp_name = "شاتل (Shatel)"
            isp_badge = "bg-success"
        elif ip.startswith("2.186.") or ip.startswith("2.181."):
            isp_name = "مخابرات ایران"
            isp_badge = "bg-primary"

    return {
        "client_app": client_app,
        "app_icon": app_icon,
        "client_version": client_version,
        "os_name": os_name,
        "os_icon": os_icon,
        "device_name": device_name,
        "ip_address": ip or "127.0.0.1",
        "isp_name": isp_name,
        "isp_badge": isp_badge,
        "user_agent": ua
    }
