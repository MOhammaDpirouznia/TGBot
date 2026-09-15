#!/usr/bin/env python3
"""
ماژول مدیریت آی‌پی سرور و دریافت خودکار گواهی‌های امنیتی SSL (SSL & Domain Manager)
ارائه‌دهنده:
۱. استعلام هوشمند آی‌پی عمومی سرور با مکانیزم Fallback چندگانه
۲. بررسی اتصال DNS دامنه به آی‌پی سرور
۳. صدور خودکار سرتیفیکیت با اولویت‌بندی ترتیبی: Let's Encrypt ➔ ZeroSSL ➔ Self-Signed / Cloudflare Fallback
"""

import os
import re
import socket
import logging
import subprocess
import urllib.request
from typing import Optional, Dict, Any

from database import db

logger = logging.getLogger("ssl_manager")

PUBLIC_IP_APIS = [
    "https://api.ipify.org",
    "https://icanhazip.com",
    "https://ifconfig.me/ip",
    "https://ident.me",
    "https://checkip.amazonaws.com"
]

CERTS_DIR = os.path.join("data", "certs")
os.makedirs(CERTS_DIR, exist_ok=True)


def get_server_public_ip() -> str:
    """استعلام سریع و پایدار آی‌پی عمومی سرور با استفاده از چند ارائه‌دهنده بین‌المللی"""
    cached_ip = db.get_setting("server_public_ip")
    
    for api_url in PUBLIC_IP_APIS:
        try:
            req = urllib.request.Request(
                api_url, 
                headers={"User-Agent": "curl/7.68.0"}
            )
            with urllib.request.urlopen(req, timeout=3.5) as resp:
                ip = resp.read().decode("utf-8").strip()
                # بررسی اعتبارسنجی فرمت IPv4
                if re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", ip):
                    db.save_setting("server_public_ip", ip)
                    return ip
        except Exception as e:
            logger.debug(f"IP check failed for {api_url}: {e}")
            continue

    if cached_ip:
        return str(cached_ip)

    # فال‌بک به اتصال سوکت لوکال
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        return local_ip
    except Exception:
        return "127.0.0.1"


def clean_domain(domain: str) -> str:
    """پالایش دامنه و حذف پروتکل، مسیر، پورت و اسلش‌ها"""
    if not domain:
        return ""
    d = domain.strip().lower()
    d = re.sub(r"^https?://", "", d)
    # حذف هرگونه مسیر، کوئری یا پورت بعد از دامنه
    d = d.split("/")[0].split("?")[0].split("#")[0]
    d = re.sub(r":\d+$", "", d)
    return d.strip()


def check_domain_dns(domain: str) -> Dict[str, Any]:
    """بررسی اینکه آیا رکورد A دامنه به آی‌پی سرور اشاره می‌کند یا خیر"""
    clean_d = clean_domain(domain)
    if not clean_d:
        return {"valid": False, "error": "دامنه نامعتبر است.", "domain": "", "server_ip": "", "resolved_ip": ""}

    server_ip = get_server_public_ip()
    resolved_ip = ""
    try:
        resolved_ip = socket.gethostbyname(clean_d)
        matches = (resolved_ip == server_ip)
        return {
            "valid": matches,
            "domain": clean_d,
            "server_ip": server_ip,
            "resolved_ip": resolved_ip,
            "matches": matches,
            "is_cloudflare": False,
            "error": None if matches else f"آی‌پی دامنه ({resolved_ip}) با آی‌پی سرور ({server_ip}) یکسان نیست."
        }
    except Exception as e:
        return {
            "valid": False,
            "domain": clean_d,
            "server_ip": server_ip,
            "resolved_ip": "",
            "matches": False,
            "error": f"عدم امکان دریافت رکورد DNS دامنه: {e}"
        }


def _try_certbot_certificate(domain: str, server_url: Optional[str] = None) -> Dict[str, Any]:
    """تلاش برای دریافت گواهی از طریق ابزار استاندارد Certbot"""
    try:
        # بررسی نصب بودن certbot در سیستم لینوکس
        which_out = subprocess.run(["which", "certbot"], capture_output=True, text=True)
        if which_out.returncode != 0:
            return {"success": False, "reason": "certbot_not_installed"}

        cmd = [
            "certbot", "certonly", "--standalone",
            "-d", domain,
            "--non-interactive", "--agree-tos",
            "--register-unsafely-without-email"
        ]
        if server_url:
            cmd.extend(["--server", server_url])

        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if proc.returncode == 0:
            cert_dir = f"/etc/letsencrypt/live/{domain}"
            return {
                "success": True,
                "cert_path": os.path.join(cert_dir, "fullchain.pem"),
                "key_path": os.path.join(cert_dir, "privkey.pem"),
                "stdout": proc.stdout
            }
        return {"success": False, "error": proc.stderr or proc.stdout}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _generate_self_signed_cert(domain: str) -> Dict[str, Any]:
    """تولید گواهی امنیتی خودامضا (Self-Signed) به عنوان مطمئن‌ترین پشتیبان"""
    cert_path = os.path.join(CERTS_DIR, f"{domain}.crt")
    key_path = os.path.join(CERTS_DIR, f"{domain}.key")

    try:
        # ساخت با OpenSSL خط فرمان در صورت وجود
        cmd = [
            "openssl", "req", "-x509", "-nodes", "-days", "365",
            "-newkey", "rsa:2048",
            "-keyout", key_path,
            "-out", cert_path,
            "-subj", f"/CN={domain}"
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if proc.returncode == 0:
            return {"success": True, "cert_path": cert_path, "key_path": key_path}
    except Exception:
        pass

    # فال‌بک تولید پایتونی در صورت نبود openssl
    try:
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        import datetime

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, domain),
        ])
        cert = x509.CertificateBuilder().subject_name(
            subject
        ).issuer_name(
            issuer
        ).public_key(
            key.public_key()
        ).serial_number(
            x509.random_serial_number()
        ).not_valid_before(
            datetime.datetime.utcnow()
        ).not_valid_after(
            datetime.datetime.utcnow() + datetime.timedelta(days=365)
        ).add_extension(
            x509.SubjectAlternativeName([x509.DNSName(domain)]),
            critical=False,
        ).sign(key, hashes.SHA256())

        with open(key_path, "wb") as f:
            f.write(key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption()
            ))

        with open(cert_path, "wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))

        return {"success": True, "cert_path": cert_path, "key_path": key_path}
    except Exception as e:
        return {"success": False, "error": f"تولید خودامضا مقدور نشد: {e}"}


def request_ssl_certificate(domain: str) -> Dict[str, Any]:
    """
    درخواست و دریافت خودکار گواهی SSL به ترتیب اولویت و اعتبار:
    ۱. Let's Encrypt (معتبرترین و پرکاربردترین)
    ۲. ZeroSSL (جایگزین معتبر در صورت محدودیت یا خطای لتس اینکریپت)
    ۳. Self-Signed با راهنمای Cloudflare (پوشش امنیتی کامل تحت هر شرایطی)
    """
    clean_d = clean_domain(domain)
    if not clean_d:
        return {"success": False, "error": "دامنه وارد نشده یا نامعتبر است."}

    dns_check = check_domain_dns(clean_d)
    
    # اولویت ۱: تلاش با Let's Encrypt
    logger.info(f"Attempting SSL for {clean_d} via Let's Encrypt...")
    le_res = _try_certbot_certificate(clean_d)
    if le_res.get("success"):
        res = {
            "success": True,
            "provider": "letsencrypt",
            "provider_name": "Let's Encrypt (رایگان و معتبر)",
            "domain": clean_d,
            "cert_path": le_res["cert_path"],
            "key_path": le_res["key_path"],
            "message": "✅ گواهی امنیتی SSL با موفقیت از مرجع معتبر Let's Encrypt صادر شد."
        }
        _save_ssl_success(res)
        return res

    # اولویت ۲: تلاش با ZeroSSL در صورت خطا یا محدودیت در Let's Encrypt
    logger.info(f"Let's Encrypt failed, attempting SSL for {clean_d} via ZeroSSL...")
    zero_res = _try_certbot_certificate(clean_d, server_url="https://acme.zerossl.com/v2/DV90")
    if zero_res.get("success"):
        res = {
            "success": True,
            "provider": "zerossl",
            "provider_name": "ZeroSSL ACME",
            "domain": clean_d,
            "cert_path": zero_res["cert_path"],
            "key_path": zero_res["key_path"],
            "message": "✅ گواهی امنیتی SSL با موفقیت از مرجع معتبر ZeroSSL صادر شد."
        }
        _save_ssl_success(res)
        return res

    # اولویت ۳: تولید سرتیفیکیت خودامضا و هماهنگی با کلودفلر
    logger.info(f"ACME standalone failed, generating Self-Signed fallback for {clean_d}...")
    self_res = _generate_self_signed_cert(clean_d)
    if self_res.get("success"):
        res = {
            "success": True,
            "provider": "self_signed",
            "provider_name": "Self-Signed (سازگار با Cloudflare Flexible/Full)",
            "domain": clean_d,
            "cert_path": self_res["cert_path"],
            "key_path": self_res["key_path"],
            "message": "🔒 گواهی امنیتی داخلی ایجاد شد. در صورت استفاده از کلودفلر (پروکسی روشن ☁️)، ارتباط به صورت اتوماتیک کاملاً امن و سبز خواهد بود."
        }
        _save_ssl_success(res)
        return res

    return {
        "success": False,
        "error": "امکان صدور خودکار گواهی فراهم نشد. لطفاً دامنه را از طریق کلودفلر پروکسی فرمایید یا از گواهی دستی استفاده کنید.",
        "details": f"Let's Encrypt: {le_res.get('error')}, Self-Signed: {self_res.get('error')}"
    }


def _save_ssl_success(res: dict):
    """ذخیره وضعیت سرتیفیکیت صادر شده در تنظیمات دیتابیس"""
    try:
        db.save_setting("ssl_domain", res.get("domain"))
        db.save_setting("ssl_provider", res.get("provider"))
        db.save_setting("ssl_provider_name", res.get("provider_name"))
        db.save_setting("ssl_cert_path", res.get("cert_path"))
        db.save_setting("ssl_key_path", res.get("key_path"))
        db.save_setting("ssl_status", "active")
        db.save_setting("ssl_updated_at", str(os.path.getmtime(res.get("cert_path", ""))) if os.path.exists(res.get("cert_path", "")) else "")
    except Exception as e:
        logger.warning(f"Error saving SSL settings to DB: {e}")
