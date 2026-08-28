"""ماژول ابزارهای کمکی شامل تبدیل تاریخ به شمسی و ساعت تهران"""

from datetime import datetime, timedelta, timezone
from typing import Optional, Union
import jdatetime

# ─── منطقه زمانی تهران (UTC+3:30) ───
TEHRAN_TZ = timezone(timedelta(hours=3, minutes=30))


def get_now() -> datetime:
    """
    دریافت زمان فعلی با ساعت تهران
    
    Returns:
        datetime object با منطقه زمانی تهران
    """
    return datetime.now(TEHRAN_TZ)


def get_now_naive() -> datetime:
    """
    دریافت زمان فعلی تهران (بدون timezone info)
    مناسب برای ذخیره‌سازی در دیتابیس
    """
    return datetime.now(TEHRAN_TZ).replace(tzinfo=None)


def get_now_iso() -> str:
    """
    دریافت زمان فعلی تهران به فرمت ISO
    """
    return get_now().isoformat()


def get_now_timestamp() -> int:
    """
    دریافت زمان فعلی تهران به فرمت timestamp
    """
    return int(get_now().timestamp())


def gregorian_to_shamsi(date_input: Union[str, datetime], fmt: str = "%Y/%m/%d") -> str:
    """
    تبدیل تاریخ میلادی به شمسی
    
    Args:
        date_input: تاریخ میلادی (string ISO یا datetime object)
        fmt: فرمت خروجی شمسی
    
    Returns:
        تاریخ شمسی به فرمت رشته‌ای
    """
    try:
        if isinstance(date_input, str):
            # حذف فاصله اضافی و Z از انتهای رشته
            clean = date_input.strip().replace("Z", "")
            if "." in clean:
                dt = datetime.fromisoformat(clean)
            else:
                dt = datetime.fromisoformat(clean)
        elif isinstance(date_input, datetime):
            dt = date_input
        else:
            return "نامشخص"
        
        jalali_date = jdatetime.datetime.fromgregorian(datetime=dt)
        return jalali_date.strftime(fmt)
    except Exception:
        return "نامشخص"


def gregorian_to_shamsi_full(date_input: Union[str, datetime]) -> str:
    """
    نمایش کامل تاریخ شمسی (سال/ماه/روز ساعت:دقیقه)
    """
    return gregorian_to_shamsi(date_input, fmt="%Y/%m/%d %H:%M")


def get_now_shamsi(fmt: str = "%Y/%m/%d %H:%M:%S") -> str:
    """
    دریافت زمان فعلی به شمسی (با ساعت تهران)
    """
    return jdatetime.datetime.fromgregorian(datetime=get_now()).strftime(fmt)


def days_remaining_shamsi(expire_date: str) -> Optional[int]:
    """
    محاسبه تعداد روزهای باقی‌مانده تا انقضا
    """
    try:
        if not expire_date:
            return None
        clean = expire_date.strip().replace("Z", "")
        expire_dt = datetime.fromisoformat(clean)
        now = get_now_naive()
        delta = expire_dt - now
        return max(0, delta.days)
    except Exception:
        return None


def is_expired(expire_date: str) -> bool:
    """
    بررسی آیا تاریخ انقضا گذشته
    """
    try:
        if not expire_date:
            return False
        clean = expire_date.strip().replace("Z", "")
        expire_dt = datetime.fromisoformat(clean)
        now = get_now_naive()
        return now > expire_dt
    except Exception:
        return False


def generate_qr_code_bytes(data: str) -> Optional[bytes]:
    """
    تولید تصویر QR Code به صورت بایت‌ها برای ارسال در تلگرام
    """
    import io
    try:
        import qrcode
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=2,
        )
        qr.add_data(data)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        bio = io.BytesIO()
        img.save(bio, format="PNG")
        bio.seek(0)
        return bio.getvalue()
    except Exception:
        # Fallback به API آنلاین در صورت نبود پکیج qrcode
        try:
            import urllib.parse
            import urllib.request
            encoded = urllib.parse.quote(data)
            url = f"https://api.qrserver.com/v1/create-qr-code/?size=350x350&data={encoded}"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=5) as response:
                return response.read()
        except Exception:
            return None


DEFAULT_SINGLE_CONFIG_TEMPLATE = """{
  "v": "2",
  "ps": "HiddiBot-{name}",
  "add": "your-domain.com",
  "port": "443",
  "id": "{uuid}",
  "aid": "0",
  "scy": "auto",
  "net": "ws",
  "type": "none",
  "host": "your-domain.com",
  "path": "/ws",
  "tls": "tls",
  "sni": "your-domain.com",
  "alpn": ""
}"""


def get_single_link_template(db_instance=None) -> str:
    """دریافت قالب لینک تکی از دیتابیس یا متغیرهای محیطی"""
    import os
    if db_instance is not None:
        try:
            tpl = db_instance.get_setting("single_link_template")
            if tpl and isinstance(tpl, str) and tpl.strip():
                return tpl.strip()
        except Exception:
            pass
    else:
        try:
            from database import db
            tpl = db.get_setting("single_link_template")
            if tpl and isinstance(tpl, str) and tpl.strip():
                return tpl.strip()
        except Exception:
            pass

    return os.getenv("SINGLE_LINK_TEMPLATE", DEFAULT_SINGLE_CONFIG_TEMPLATE)


def format_single_link(template: str, uuid: str, name: str) -> str:
    """
    جایگذاری خودکار UUID و نام مشتری در قالب لینک تکی و تولید خروجی VMess یا URI
    - در صورت ورودی JSON (یا vmess://): مشخصات مشتری در فیلدهای id و ps قرار گرفته و خروجی به فرمت استاندارد vmess://Base64 تولید می‌شود.
    - در صورت ورودی URI (مانند vless:// یا trojan://): متغیرهای {uuid} و {name} جایگذاری می‌شوند.
    """
    import base64
    import json
    import urllib.parse

    clean_uuid = str(uuid or "").strip()
    clean_name = str(name or "User").strip()
    encoded_name = urllib.parse.quote(clean_name)
    tpl_str = (template or "").strip()

    if not tpl_str:
        tpl_str = DEFAULT_SINGLE_CONFIG_TEMPLATE

    # اگر کاربر یک لینک کامل vmess:// وارد کرده باشد، ابتدا آن را Decode می‌کنیم
    if tpl_str.startswith("vmess://"):
        raw_b64 = tpl_str.replace("vmess://", "").strip()
        padded = raw_b64 + "=" * ((4 - len(raw_b64) % 4) % 4)
        try:
            decoded_json = base64.b64decode(padded).decode("utf-8")
            tpl_str = decoded_json.strip()
        except Exception:
            pass

    # بررسی آیا قالب ساختار JSON است
    if (tpl_str.startswith("{") and tpl_str.endswith("}")) or '"add"' in tpl_str or '"port"' in tpl_str:
        try:
            # جایگذاری اولیه متغیرها در متن JSON
            replaced_str = (
                tpl_str.replace("{uuid}", clean_uuid)
                .replace("{UUID}", clean_uuid)
                .replace("{name}", clean_name)
                .replace("{NAME}", clean_name)
                .replace("{username}", clean_name)
                .replace("{USERNAME}", clean_name)
                .replace("{encoded_name}", encoded_name)
            )

            parsed_json = json.loads(replaced_str)
            if isinstance(parsed_json, dict):
                # تنظیم فیلد id با UUID مشتری
                if "id" in parsed_json:
                    if "{uuid}" in str(parsed_json["id"]) or not parsed_json["id"] or parsed_json["id"] == "your-uuid-here":
                        parsed_json["id"] = clean_uuid
                    else:
                        parsed_json["id"] = clean_uuid
                else:
                    parsed_json["id"] = clean_uuid

                # تنظیم فیلد ps با نام مشتری
                if "ps" in parsed_json:
                    ps_val = str(parsed_json["ps"])
                    if "{name}" in ps_val or "{username}" in ps_val:
                        parsed_json["ps"] = ps_val.replace("{name}", clean_name).replace("{username}", clean_name)
                else:
                    parsed_json["ps"] = f"HiddiBot-{clean_name}"

                # تولید JSON فشرده و Base64 استاندارد
                compact_json = json.dumps(parsed_json, separators=(",", ":"), ensure_ascii=False)
                b64_encoded = base64.b64encode(compact_json.encode("utf-8")).decode("utf-8")
                return f"vmess://{b64_encoded}"
        except Exception:
            pass

    # در صورت عدم تطابق با JSON، جایگذاری متنی ساده
    res = (
        tpl_str.replace("{uuid}", clean_uuid)
        .replace("{UUID}", clean_uuid)
        .replace("{name}", clean_name)
        .replace("{NAME}", clean_name)
        .replace("{username}", clean_name)
        .replace("{USERNAME}", clean_name)
        .replace("{encoded_name}", encoded_name)
    )
    return res



