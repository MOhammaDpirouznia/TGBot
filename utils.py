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

