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

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CERTS_DIR = os.path.join(BASE_DIR, "data", "certs")
os.makedirs(CERTS_DIR, exist_ok=True)

# رنج‌های رسمی IPv4 و IPv6 سرورهای پروکسی Cloudflare جهت شناسایی هوشمند وضعیت اتصال دامنه
CLOUDFLARE_IPV4_CIDRS = [
    "173.245.48.0/20", "103.21.244.0/22", "103.22.200.0/22", "103.31.4.0/22",
    "141.101.64.0/18", "108.162.192.0/18", "190.93.240.0/20", "188.114.96.0/20",
    "197.234.240.0/22", "198.41.128.0/17", "162.158.0.0/15", "104.16.0.0/13",
    "104.24.0.0/14", "172.64.0.0/13", "131.0.72.0/22"
]
CLOUDFLARE_IPV6_CIDRS = [
    "2400:cb00::/32", "2606:4700::/32", "2803:f800::/32", "2405:b500::/32",
    "2405:8100::/32", "2a06:98c0::/29", "2c0f:f248::/32"
]


def is_cloudflare_ip(ip_str: str) -> bool:
    """بررسی اینکه آیا آی‌پی شناسایی‌شده متعلق به سرورهای پروکسی Cloudflare است یا خیر"""
    if not ip_str:
        return False
    try:
        import ipaddress
        ip = ipaddress.ip_address(ip_str)
        cidrs = CLOUDFLARE_IPV4_CIDRS if ip.version == 4 else CLOUDFLARE_IPV6_CIDRS
        for cidr in cidrs:
            if ip in ipaddress.ip_network(cidr):
                return True
    except Exception:
        pass
    return False


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
    """بررسی اینکه آیا رکورد A دامنه به آی‌پی سرور یا شبکه Cloudflare متصل است"""
    clean_d = clean_domain(domain)
    if not clean_d:
        return {"valid": False, "error": "دامنه نامعتبر است.", "domain": "", "server_ip": "", "resolved_ip": ""}

    server_ip = get_server_public_ip()
    resolved_ip = ""
    try:
        resolved_ip = socket.gethostbyname(clean_d)
        is_cf = is_cloudflare_ip(resolved_ip)
        matches = (resolved_ip == server_ip) or is_cf
        error_msg = None
        if not matches:
            error_msg = f"آی‌پی دامنه ({resolved_ip}) با آی‌پی سرور ({server_ip}) یکسان نیست."
        return {
            "valid": matches,
            "domain": clean_d,
            "server_ip": server_ip,
            "resolved_ip": resolved_ip,
            "matches": matches,
            "is_cloudflare": is_cf,
            "error": error_msg
        }
    except Exception as e:
        return {
            "valid": False,
            "domain": clean_d,
            "server_ip": server_ip,
            "resolved_ip": "",
            "matches": False,
            "is_cloudflare": False,
            "error": f"عدم امکان دریافت رکورد DNS دامنه: {e}"
        }


# ─────────────────────────────────────────────────────────────────────────────
# مدیریت خودکار کانفیگ‌های Nginx برای دامنه‌های پویا (Nginx Auto-Configurator)
# ─────────────────────────────────────────────────────────────────────────────

def is_nginx_running() -> bool:
    """بررسی فعال بودن وب‌سرور Nginx روی سیستم لینوکس"""
    try:
        proc = subprocess.run(["systemctl", "is-active", "--quiet", "nginx"], timeout=5)
        if proc.returncode == 0:
            return True
    except Exception:
        pass
    try:
        proc = subprocess.run(["pgrep", "-x", "nginx"], capture_output=True, timeout=5)
        if proc.returncode == 0:
            return True
    except Exception:
        pass
    return False


def get_nginx_config_target(domain: str) -> Optional[dict]:
    """تعیین مسیر ذخیره کانفیگ Nginx متناسب با سیستم‌عامل"""
    clean_d = clean_domain(domain)
    if not clean_d:
        return None

    conf_d = "/etc/nginx/conf.d"
    sites_avail = "/etc/nginx/sites-available"
    sites_enabled = "/etc/nginx/sites-enabled"

    if os.path.exists(conf_d) and os.path.isdir(conf_d):
        return {
            "type": "conf_d",
            "file_path": os.path.join(conf_d, f"tgbot_{clean_d}.conf"),
            "symlink_path": None
        }
    elif os.path.exists(sites_avail) and os.path.isdir(sites_avail):
        return {
            "type": "sites",
            "file_path": os.path.join(sites_avail, f"tgbot_{clean_d}.conf"),
            "symlink_path": os.path.join(sites_enabled, f"tgbot_{clean_d}.conf") if os.path.exists(sites_enabled) else None
        }
    return None


def configure_nginx_for_domain(domain: str, cert_path: Optional[str] = None, key_path: Optional[str] = None, log_fn=None) -> Dict[str, Any]:
    """
    پیکربندی و بارگذاری خودکار سرور مجازی (VirtualHost) در Nginx برای دامنه
    پشتیبانی همزمان از پورت 80 (برای چالش‌های Let's Encrypt) و پورت 443 (SSL/TLS امن)
    """
    clean_d = clean_domain(domain)
    if not clean_d:
        return {"success": False, "error": "نام دامنه نامعتبر است."}

    target = get_nginx_config_target(clean_d)
    if not target:
        msg = "دایرکتوری کانفیگ Nginx (/etc/nginx) یافت نشد."
        if log_fn:
            log_fn(f"⚠️ {msg}")
        return {"success": False, "error": msg}

    # ایجاد مسیر استاندارد چالش وب‌روت برای Let's Encrypt
    acme_dir = "/var/www/html/.well-known/acme-challenge"
    try:
        os.makedirs(acme_dir, exist_ok=True)
        for p in ["/var/www", "/var/www/html", "/var/www/html/.well-known", acme_dir]:
            if os.path.exists(p):
                try:
                    os.chmod(p, 0o755)
                except Exception:
                    pass
    except Exception as ex:
        logger.warning(f"Error preparing ACME directory: {ex}")

    # تعیین پورت داخلی وب‌پنل
    panel_port = 5000
    try:
        from dashboard import get_panel_port
        panel_port = get_panel_port()
    except Exception:
        env_p = os.getenv("PORT") or os.getenv("PANEL_PORT")
        if env_p and str(env_p).isdigit():
            panel_port = int(env_p)

    has_ssl = bool(cert_path and key_path and os.path.exists(cert_path) and os.path.exists(key_path))

    conf_lines = [
        f"# ==============================================================================",
        f"# 🚀 Auto-generated by TGBot Domain Manager for: {clean_d}",
        f"# ==============================================================================",
        f"",
        f"server {{",
        f"    listen 80;",
        f"    listen [::]:80;",
        f"    server_name {clean_d};",
        f"",
        f"    # مسیر تایید چالش امنیتی Let's Encrypt ACME",
        f"    location /.well-known/acme-challenge/ {{",
        f"        root /var/www/html;",
        f"        try_files $uri =404;",
        f"    }}",
        f""
    ]

    if has_ssl:
        conf_lines.extend([
            f"    # هدایت خودکار تمام درخواست‌ها به پروتکل امن HTTPS",
            f"    location / {{",
            f"        return 301 https://$host$request_uri;",
            f"    }}",
            f"}}",
            f"",
            f"server {{",
            f"    listen 443 ssl http2;",
            f"    listen [::]:443 ssl http2;",
            f"    server_name {clean_d};",
            f"",
            f"    ssl_certificate {cert_path};",
            f"    ssl_certificate_key {key_path};",
            f"    ssl_protocols TLSv1.2 TLSv1.3;",
            f"    ssl_ciphers HIGH:!aNULL:!MD5;",
            f"    ssl_prefer_server_ciphers on;",
            f"",
            f"    client_max_body_size 50M;",
            f"",
            f"    location / {{",
            f"        proxy_pass http://127.0.0.1:{panel_port};",
            f"        proxy_set_header Host $host;",
            f"        proxy_set_header X-Real-IP $remote_addr;",
            f"        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;",
            f"        proxy_set_header X-Forwarded-Proto $scheme;",
            f"        proxy_http_version 1.1;",
            f"        proxy_set_header Upgrade $http_upgrade;",
            f"        proxy_set_header Connection \"upgrade\";",
            f"    }}",
            f"}}"
        ])
    else:
        conf_lines.extend([
            f"    client_max_body_size 50M;",
            f"",
            f"    location / {{",
            f"        proxy_pass http://127.0.0.1:{panel_port};",
            f"        proxy_set_header Host $host;",
            f"        proxy_set_header X-Real-IP $remote_addr;",
            f"        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;",
            f"        proxy_set_header X-Forwarded-Proto $scheme;",
            f"        proxy_http_version 1.1;",
            f"        proxy_set_header Upgrade $http_upgrade;",
            f"        proxy_set_header Connection \"upgrade\";",
            f"    }}",
            f"}}"
        ])

    content = "\n".join(conf_lines) + "\n"
    file_path = target["file_path"]
    symlink_path = target["symlink_path"]

    backup_content = None
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                backup_content = f.read()
        except Exception:
            pass

    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)

        if symlink_path and not os.path.exists(symlink_path):
            try:
                os.symlink(file_path, symlink_path)
            except Exception as es:
                logger.debug(f"Symlink creation for Nginx: {es}")

        # آزمایش صحت کانفیگ با nginx -t
        t_proc = subprocess.run(["nginx", "-t"], capture_output=True, text=True, timeout=10)
        if t_proc.returncode != 0:
            err_msg = t_proc.stderr or t_proc.stdout
            logger.error(f"Nginx test error for {clean_d}: {err_msg}")
            # بازگردانی فایل قبلی در صورت بروز خطا برای عدم اختلال در بقیه سایت‌ها
            if backup_content is not None:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(backup_content)
            else:
                if os.path.exists(file_path):
                    os.remove(file_path)
                if symlink_path and os.path.islink(symlink_path):
                    os.remove(symlink_path)
            return {"success": False, "error": f"خطای تست کانفیگ Nginx: {err_msg}"}

        # بازخوانی سرویس Nginx
        subprocess.run(["systemctl", "reload", "nginx"], capture_output=True, text=True, timeout=10)

        if log_fn:
            log_fn(f"⚙️ کانفیگ Nginx برای دامنه {clean_d} بر روی پورت {'443 (SSL) و 80' if has_ssl else '80'} با موفقیت فعال و بارگذاری شد.")

        return {"success": True, "file": file_path, "ssl": has_ssl}
    except Exception as e:
        logger.error(f"Error configuring Nginx for domain {clean_d}: {e}")
        return {"success": False, "error": str(e)}


def remove_nginx_for_domain(domain: str) -> bool:
    """حذف کانفیگ Nginx مربوط به دامنه و ریلود وب‌سرور"""
    clean_d = clean_domain(domain)
    if not clean_d:
        return False
    target = get_nginx_config_target(clean_d)
    if not target:
        return False

    file_path = target["file_path"]
    symlink_path = target["symlink_path"]
    changed = False

    if symlink_path and (os.path.islink(symlink_path) or os.path.exists(symlink_path)):
        try:
            os.remove(symlink_path)
            changed = True
        except Exception:
            pass

    if os.path.exists(file_path):
        try:
            os.remove(file_path)
            changed = True
        except Exception:
            pass

    if changed:
        try:
            t_proc = subprocess.run(["nginx", "-t"], capture_output=True, text=True, timeout=5)
            if t_proc.returncode == 0:
                subprocess.run(["systemctl", "reload", "nginx"], timeout=5)
        except Exception:
            pass
    return True


# ─────────────────────────────────────────────────────────────────────────────
# توابع صدور گواهی امنیتی SSL (Certbot, ZeroSSL, Self-Signed)
# ─────────────────────────────────────────────────────────────────────────────

def _try_certbot_certificate(domain: str, server_url: Optional[str] = None, log_fn=None) -> Dict[str, Any]:
    """تلاش برای دریافت گواهی از طریق Certbot با سازگاری همزمان برای Nginx، Webroot و Standalone"""
    clean_d = clean_domain(domain)
    try:
        which_out = subprocess.run(["which", "certbot"], capture_output=True, text=True)
        if which_out.returncode != 0:
            if log_fn:
                log_fn("⚠️ ابزار certbot در سرور نصب نیست.")
            return {"success": False, "reason": "certbot_not_installed"}

        cert_dir = f"/etc/letsencrypt/live/{clean_d}"
        cert_file = os.path.join(cert_dir, "fullchain.pem")
        key_file = os.path.join(cert_dir, "privkey.pem")

        if is_nginx_running():
            if log_fn:
                log_fn("🌐 وب‌سرور Nginx شناسایی شد؛ اعمال کانفیگ پورت ۸۰ جهت چالش ACME...")
            # ابتدا کانفیگ پورت 80 را روی Nginx ایجاد می‌کنیم
            configure_nginx_for_domain(clean_d, log_fn=log_fn)

            # متد ۱: استفاده از روش webroot (مطمئن‌ترین روش در سرورهای دارای وب‌سرور فعال)
            if log_fn:
                log_fn("🔐 در حال درخواست سرتیفیکیت با متد استاندارد Certbot Webroot...")
            cmd_webroot = [
                "certbot", "certonly", "--webroot",
                "-w", "/var/www/html",
                "-d", clean_d,
                "--non-interactive", "--agree-tos",
                "--register-unsafely-without-email"
            ]
            if server_url:
                cmd_webroot.extend(["--server", server_url])

            proc_wr = subprocess.run(cmd_webroot, capture_output=True, text=True, timeout=75)
            if proc_wr.returncode == 0 and os.path.exists(cert_file):
                configure_nginx_for_domain(clean_d, cert_path=cert_file, key_path=key_file, log_fn=log_fn)
                return {
                    "success": True,
                    "cert_path": cert_file,
                    "key_path": key_file,
                    "stdout": proc_wr.stdout
                }

            # متد ۲: تلاش با پلاگین certbot --nginx در صورت عدم موفقیت وب‌روت
            if log_fn:
                log_fn("ℹ️ تلاش ثانویه با پلاگین مستقیم certbot --nginx...")
            cmd_nginx = [
                "certbot", "--nginx",
                "-d", clean_d,
                "--non-interactive", "--agree-tos",
                "--register-unsafely-without-email"
            ]
            if server_url:
                cmd_nginx.extend(["--server", server_url])

            proc_ng = subprocess.run(cmd_nginx, capture_output=True, text=True, timeout=75)
            if proc_ng.returncode == 0 and os.path.exists(cert_file):
                configure_nginx_for_domain(clean_d, cert_path=cert_file, key_path=key_file, log_fn=log_fn)
                return {
                    "success": True,
                    "cert_path": cert_file,
                    "key_path": key_file,
                    "stdout": proc_ng.stdout
                }

            err_out = proc_wr.stderr or proc_wr.stdout or proc_ng.stderr or proc_ng.stdout
            return {"success": False, "error": err_out}

        else:
            # حالت Standalone در صورتی که Nginx روی پورت 80 فعال نباشد
            if log_fn:
                log_fn("⚙️ وب‌سرور Nginx فعال نیست؛ تلاش برای صدور در حالت Certbot Standalone...")
            cmd = [
                "certbot", "certonly", "--standalone",
                "-d", clean_d,
                "--non-interactive", "--agree-tos",
                "--register-unsafely-without-email"
            ]
            if server_url:
                cmd.extend(["--server", server_url])

            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if proc.returncode == 0 and os.path.exists(cert_file):
                return {
                    "success": True,
                    "cert_path": cert_file,
                    "key_path": key_file,
                    "stdout": proc.stdout
                }
            return {"success": False, "error": proc.stderr or proc.stdout}

    except Exception as e:
        logger.error(f"Certbot error for {clean_d}: {e}")
        return {"success": False, "error": str(e)}


def _generate_self_signed_cert(domain: str, log_fn=None) -> Dict[str, Any]:
    """تولید گواهی امنیتی خودامضا (Self-Signed) و اعمال آن روی Nginx جهت حل قطعی خطای ۵۲۵ کلودفلر"""
    clean_d = clean_domain(domain)
    cert_path = os.path.join(CERTS_DIR, f"{clean_d}.crt")
    key_path = os.path.join(CERTS_DIR, f"{clean_d}.key")

    success = False
    try:
        cmd = [
            "openssl", "req", "-x509", "-nodes", "-days", "365",
            "-newkey", "rsa:2048",
            "-keyout", key_path,
            "-out", cert_path,
            "-subj", f"/CN={clean_d}"
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if proc.returncode == 0:
            success = True
    except Exception:
        pass

    if not success:
        try:
            from cryptography import x509
            from cryptography.x509.oid import NameOID
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import rsa
            import datetime

            key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            subject = issuer = x509.Name([
                x509.NameAttribute(NameOID.COMMON_NAME, clean_d),
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
                x509.SubjectAlternativeName([x509.DNSName(clean_d)]),
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

            success = True
        except Exception as e:
            return {"success": False, "error": f"تولید خودامضا مقدور نشد: {e}"}

    if success:
        # اگر Nginx در حال اجراست، سرور 443 را با این گواهی فعال می‌کنیم تا کلودفلر بتواند هندشیک را کامل کند
        if is_nginx_running():
            configure_nginx_for_domain(clean_d, cert_path=cert_path, key_path=key_path, log_fn=log_fn)
        return {"success": True, "cert_path": cert_path, "key_path": key_path}

    return {"success": False, "error": "شکست در تولید سرتیفیکیت"}


def request_ssl_certificate(domain: str, log_fn=None) -> Dict[str, Any]:
    """
    درخواست و دریافت خودکار گواهی SSL به ترتیب اولویت و اعتبار:
    ۱. Let's Encrypt (معتبرترین و پرکاربردترین)
    ۲. ZeroSSL (جایگزین معتبر در صورت محدودیت یا خطای لتس اینکریپت)
    ۳. Self-Signed با پیکربندی وب‌سرور جهت اتصال کامل Cloudflare (پوشش امنیتی کامل)
    """
    clean_d = clean_domain(domain)
    if not clean_d:
        return {"success": False, "error": "دامنه وارد نشده یا نامعتبر است."}

    # اولویت ۱: تلاش با Let's Encrypt
    if log_fn:
        log_fn("🔐 در حال درخواست سرتیفیکیت رسمی از مرجع Let's Encrypt...")
    logger.info(f"Attempting SSL for {clean_d} via Let's Encrypt...")
    le_res = _try_certbot_certificate(clean_d, log_fn=log_fn)
    if le_res.get("success"):
        res = {
            "success": True,
            "provider": "letsencrypt",
            "provider_name": "Let's Encrypt (رسمی و معتبر)",
            "domain": clean_d,
            "cert_path": le_res["cert_path"],
            "key_path": le_res["key_path"],
            "message": "✅ گواهی امنیتی رسمی SSL با موفقیت از مرجع معتبر Let's Encrypt صادر شد."
        }
        _save_ssl_success(res)
        return res

    # اولویت ۲: تلاش با ZeroSSL در صورت خطا یا محدودیت در Let's Encrypt
    if log_fn:
        log_fn("ℹ️ مرجع Let's Encrypt پاسخ نداد؛ در حال درخواست سرتیفیکیت از ZeroSSL...")
    logger.info(f"Let's Encrypt failed, attempting SSL for {clean_d} via ZeroSSL...")
    zero_res = _try_certbot_certificate(clean_d, server_url="https://acme.zerossl.com/v2/DV90", log_fn=log_fn)
    if zero_res.get("success"):
        res = {
            "success": True,
            "provider": "zerossl",
            "provider_name": "ZeroSSL ACME",
            "domain": clean_d,
            "cert_path": zero_res["cert_path"],
            "key_path": zero_res["key_path"],
            "message": "✅ گواهی امنیتی رسمی SSL با موفقیت از مرجع معتبر ZeroSSL صادر شد."
        }
        _save_ssl_success(res)
        return res

    # اولویت ۳: تولید سرتیفیکیت خودامضا و هماهنگی با کلودفلر
    if log_fn:
        log_fn("🔒 فعال‌سازی گواهی امنیتی اختصاصی سرور و اعمال روی وب‌سرور جهت اتصال پایدار با Cloudflare...")
    logger.info(f"ACME failed, generating Self-Signed fallback for {clean_d}...")
    self_res = _generate_self_signed_cert(clean_d, log_fn=log_fn)
    if self_res.get("success"):
        res = {
            "success": True,
            "provider": "self_signed",
            "provider_name": "Cloudflare Proxy / Origin SSL",
            "domain": clean_d,
            "cert_path": self_res["cert_path"],
            "key_path": self_res["key_path"],
            "message": "🔒 گواهی امنیتی داخلی صادر و بر روی Nginx فعال شد. در صورت استفاده از کلودفلر (پروکسی روشن ☁️)، ارتباط به صورت اتوماتیک کاملاً امن خواهد بود."
        }
        _save_ssl_success(res)
        return res

    return {
        "success": False,
        "error": "امکان صدور خودکار گواهی فراهم نشد. در صورت فعال بودن پروکسی کلودفلر، موقتاً پروکسی را خاموش (DNS Only) کرده و مجدداً امتحان فرمایید.",
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


def find_certificate_path(domain: str) -> Optional[str]:
    """یافتن مسیر فایل سرتیفیکیت معتبر برای یک دامنه خاص"""
    clean_d = clean_domain(domain)
    if not clean_d:
        return None

    # ۱. مسیر استاندارد Let's Encrypt / Certbot در لینوکس
    le_path = f"/etc/letsencrypt/live/{clean_d}/fullchain.pem"
    if os.path.exists(le_path):
        return le_path

    # ۲. مسیر سرتیفیکیت‌های داخلی و خودامضا (data/certs)
    local_path = os.path.join(CERTS_DIR, f"{clean_d}.crt")
    if os.path.exists(local_path):
        return local_path

    # ۳. بررسی مسیر ثبت‌شده در تنظیمات دیتابیس
    try:
        ssl_dom = db.get_setting("ssl_domain")
        if ssl_dom and clean_domain(ssl_dom) == clean_d:
            db_path = db.get_setting("ssl_cert_path")
            if db_path and os.path.exists(db_path):
                return db_path
    except Exception:
        pass

    return None


def get_certificate_expiry_days(domain: str) -> Optional[float]:
    """
    محاسبه روزهای باقیمانده تا انقضای گواهی امنیتی SSL برای یک دامنه
    اگر گواهی موجود نباشد None برمی‌گرداند.
    """
    cert_path = find_certificate_path(domain)
    if not cert_path or not os.path.exists(cert_path):
        return None

    try:
        from cryptography import x509
        import datetime

        with open(cert_path, "rb") as f:
            cert = x509.load_pem_x509_certificate(f.read())

        if hasattr(cert, "not_valid_after_utc"):
            expiry_dt = cert.not_valid_after_utc
        else:
            expiry_dt = cert.not_valid_after.replace(tzinfo=datetime.timezone.utc)

        now = datetime.datetime.now(datetime.timezone.utc)
        diff = (expiry_dt - now).total_seconds() / 86400.0
        return diff
    except Exception as e:
        logger.warning(f"Error reading SSL certificate expiry for {domain} from {cert_path}: {e}")
        return 0.0


def get_all_configured_domains() -> list[str]:
    """
    استخراج هوشمند کلیه دامنه‌ها و ساب‌دامنه‌های ثبت شده در سیستم:
    - جدول اختصاصی دامنه‌ها (domains)
    - دامنه اصلی پنل / مشتری (custom_domain, panel_domain)
    - دامنه آموزش‌ها و عیب‌یابی (tutorial_domain, troubleshoot_domain)
    - دامنه صادرشده جاری (ssl_domain)
    - کلیه دامنه‌های اختصاصی نمایندگان فعال (resellers.custom_domain, resellers.panel_domain, resellers.tutorial_domain)
    """
    raw_domains = []

    # ۱. جدول متمرکز دامنه‌ها
    try:
        dom_records = db.get_all_domains()
        for rec in dom_records:
            if rec.get("domain") and rec.get("is_active"):
                raw_domains.append(rec["domain"])
    except Exception as e:
        logger.warning(f"Error fetching from domains table: {e}")

    # ۲. تنظیمات عمومی پنل
    for key in ("custom_domain", "panel_domain", "tutorial_domain", "troubleshoot_domain", "ssl_domain"):
        try:
            val = db.get_setting(key)
            if val:
                raw_domains.append(str(val))
        except Exception:
            pass

    # ۳. دامنه‌های اختصاصی نمایندگان در جدول resellers
    try:
        conn = db.get_connection()
        cur = conn.cursor()
        cur.execute("SELECT custom_domain, panel_domain, tutorial_domain FROM resellers WHERE status != 'deleted'")
        for row in cur.fetchall():
            for col in ("custom_domain", "panel_domain", "tutorial_domain"):
                try:
                    if row[col]:
                        raw_domains.append(str(row[col]))
                except Exception:
                    pass
    except Exception as e:
        logger.warning(f"Error collecting reseller domains for SSL: {e}")

    # ۴. فیلترسازی، پالایش و حذف موارد تکراری و نامعتبر
    unique_domains: list[str] = []
    for d in raw_domains:
        cleaned = clean_domain(d)
        if not cleaned:
            continue
        # حذف آی‌پی‌ها و لوکال‌ها
        if cleaned in ("localhost", "127.0.0.1") or re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", cleaned):
            continue
        if cleaned not in unique_domains:
            unique_domains.append(cleaned)

    return unique_domains


def renew_domain_ssl_with_logs(domain_input: str) -> Dict[str, Any]:
    """
    اجرای دستی و جامع تمدید/صدور گواهی SSL به همراه جمع‌آوری لاگ لحظه‌ای جهت نمایش در مودال کاربری
    """
    from datetime import datetime, timezone, timedelta
    clean_d = clean_domain(domain_input)
    logs: list[str] = []

    def _log(msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        logs.append(line)
        logger.info(line)

    _log(f"🚀 شروع فرآیند استعلام و صدور گواهی امنیتی SSL برای دامنه: {clean_d}")

    if not clean_d:
        _log("❌ خطا: نام دامنه خالی یا نامعتبر است.")
        return {
            "success": False,
            "domain": domain_input,
            "logs": "\n".join(logs),
            "error": "نام دامنه نامعتبر است."
        }

    # مرحله ۱: استعلام وضعیت DNS دامنه و تطابق با سرور
    _log("🔍 در حال استعلام رکوردهای DNS و بررسی آی‌پی عمومی سرور...")
    dns_res = check_domain_dns(clean_d)
    server_ip = dns_res.get("server_ip", "ناشناس")
    resolved_ip = dns_res.get("resolved_ip", "یافت نشد")

    _log(f"📌 آی‌پی عمومی سرور شما: {server_ip}")
    _log(f"🌐 آی‌پی اشاره‌شده توسط دامنه (A Record): {resolved_ip}")

    if dns_res.get("matches"):
        _log("✅ رکورد DNS دامنه با موفقیت به این سرور اشاره می‌کند.")
    else:
        _log(f"⚠️ اخطار تطابق DNS: {dns_res.get('error') or 'عدم تطابق آی‌پی دامنه با سرور'}")
        _log("ℹ️ در صورتی که از Cloudflare پروکسی روشن (ابر نارنجی) استفاده می‌فرمایید، گواهی خودکار داخلی فعال خواهد شد.")

    # مرحله ۲: اجرای درخواست گواهی امنیتی SSL
    _log("🔐 درخواست صدور گواهی امنیتی معتبر با استاندارد ACME...")
    res = request_ssl_certificate(clean_d, log_fn=_log)

    success = res.get("success", False)
    provider_name = res.get("provider_name", "ناشناس")
    provider_id = res.get("provider", "unknown")

    if success:
        _log(f"🎉 گواهی امنیتی با موفقیت صادر/تمدید شد!")
        _log(f"🛡 مرجع ارائه‌دهنده گواهی: {provider_name}")
        _log(f"📁 مسیر فایل سرتیفیکیت: {res.get('cert_path')}")
        _log(f"🔑 مسیر کلید خصوصی: {res.get('key_path')}")

        # استخراج روزهای انقضا
        expiry_days = get_certificate_expiry_days(clean_d)
        expiry_date_str = ""
        if expiry_days is not None and expiry_days > 0:
            expiry_dt = datetime.now(timezone.utc) + timedelta(days=expiry_days)
            expiry_date_str = expiry_dt.strftime("%Y-%m-%d %H:%M:%S UTC")
            _log(f"📅 مدت اعتبار سرتیفیکیت: {round(expiry_days, 1)} روز (تا تاریخ {expiry_date_str})")
        else:
            _log("📅 مدت اعتبار سرتیفیکیت فعال ثبت گردید.")

        # ذخیره وضعیت در جدول domains در صورت وجود
        try:
            dom_record = db.get_domain_by_name(clean_d)
            if dom_record:
                status_text = "active" if (expiry_days is None or expiry_days > 15) else "expiring"
                db.update_domain(
                    dom_record["id"],
                    ssl_status=status_text,
                    ssl_expiry_date=expiry_date_str,
                    ssl_last_log="\n".join(logs)
                )
        except Exception as e:
            _log(f"⚠️ خطای به‌روزرسانی جدول دامنه‌ها: {e}")

        return {
            "success": True,
            "domain": clean_d,
            "provider": provider_name,
            "expiry_days": round(expiry_days, 1) if expiry_days else 90,
            "expiry_date": expiry_date_str,
            "logs": "\n".join(logs),
            "error": None
        }
    else:
        err_msg = res.get("error", "خطای ناشناخته در صدور SSL")
        _log(f"❌ عدم موفقیت در دریافت گواهی SSL: {err_msg}")
        if res.get("details"):
            _log(f"جزئیات خطا: {res.get('details')}")

        try:
            dom_record = db.get_domain_by_name(clean_d)
            if dom_record:
                db.update_domain(
                    dom_record["id"],
                    ssl_status="failed",
                    ssl_last_log="\n".join(logs)
                )
        except Exception:
            pass

        return {
            "success": False,
            "domain": clean_d,
            "logs": "\n".join(logs),
            "error": err_msg
        }


def renew_all_ssl_certificates(threshold_days: int = 30) -> Dict[str, Any]:
    """
    بررسی هوشمند و تمدید خودکار کلیه گواهی‌های SSL سیستم:
    - کلیه دامنه‌ها بررسی می‌شوند.
    - در صورتی که کمتر از threshold_days مانده باشد تمدید می‌گردد.
    """
    domains = get_all_configured_domains()
    logger.info(f"Starting SSL renewal check for {len(domains)} configured domains (threshold: {threshold_days} days)...")

    results: Dict[str, Any] = {
        "checked_domains": domains,
        "renewed": [],
        "skipped": [],
        "failed": []
    }

    for dom in domains:
        try:
            remaining_days = get_certificate_expiry_days(dom)
            if remaining_days is None or remaining_days <= threshold_days:
                logger.info(f"[SSL Auto-Renewal] Renewing domain '{dom}'...")
                res = renew_domain_ssl_with_logs(dom)
                if res.get("success"):
                    results["renewed"].append({"domain": dom, "provider": res.get("provider")})
                else:
                    results["failed"].append({"domain": dom, "error": res.get("error")})
            else:
                results["skipped"].append({"domain": dom, "remaining_days": round(remaining_days, 1)})
        except Exception as e:
            logger.error(f"[SSL Auto-Renewal] Unexpected error processing domain '{dom}': {e}")
            results["failed"].append({"domain": dom, "error": str(e)})

    logger.info(f"SSL renewal check completed: {len(results['renewed'])} renewed, {len(results['skipped'])} skipped, {len(results['failed'])} failed.")
    return results


