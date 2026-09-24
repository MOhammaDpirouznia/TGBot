"""ماژول ابزارهای کمکی شامل تبدیل تاریخ به شمسی و ساعت تهران"""

from datetime import datetime, timedelta, timezone
from typing import Optional, Union
import jdatetime

# ─── منطقه زمانی تهران (UTC+3:30 / Asia/Tehran) ───
try:
    from zoneinfo import ZoneInfo
    _tz_candidate = ZoneInfo("Asia/Tehran")
    datetime.now(_tz_candidate)
    TEHRAN_TZ = _tz_candidate
except Exception:
    TEHRAN_TZ = timezone(timedelta(hours=3, minutes=30), name="Asia/Tehran")


def get_now() -> datetime:
    """
    دریافت زمان فعلی با ساعت تهران
    
    Returns:
        datetime object با منطقه زمانی تهران
    """
    return datetime.now(TEHRAN_TZ)


def get_now_tehran() -> datetime:
    """
    دریافت زمان فعلی با ساعت تهران (نام مستعار get_now جهت وضوح بیشتر)
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


def parse_to_tehran_dt(date_input: Union[str, datetime, int, float, None]) -> Optional[datetime]:
    """
    تبدیل انواع ورودی تاریخ/زمان (ISO با Z، با افست، بدون افست، تایم‌استمپ یا datetime) به datetime معتبر با منطقه زمانی تهران
    """
    if not date_input:
        return None
    try:
        if isinstance(date_input, (int, float)):
            return datetime.fromtimestamp(date_input, tz=TEHRAN_TZ)
        if isinstance(date_input, datetime):
            if date_input.tzinfo is None:
                return date_input.replace(tzinfo=TEHRAN_TZ)
            return date_input.astimezone(TEHRAN_TZ)
        
        s = str(date_input).strip()
        if not s:
            return None
            
        if s.endswith("Z"):
            clean = s[:-1]
            dt = datetime.fromisoformat(clean).replace(tzinfo=timezone.utc)
            return dt.astimezone(TEHRAN_TZ)
        elif "+" in s or (s.count("-") >= 3):
            dt = datetime.fromisoformat(s)
            return dt.astimezone(TEHRAN_TZ)
        else:
            if "T" in s:
                dt = datetime.fromisoformat(s)
            elif " " in s:
                dt = datetime.fromisoformat(s.replace(" ", "T"))
            else:
                dt = datetime.strptime(s[:10], "%Y-%m-%d")
            return dt.replace(tzinfo=TEHRAN_TZ)
    except Exception:
        return None


def is_tehran_hour(target_hour: int) -> bool:
    """بررسی تطابق ساعت کنونی تهران با ساعت هدف (۰ تا ۲۳)"""
    try:
        return get_now().hour == int(target_hour)
    except Exception:
        return False


def is_in_quiet_hours(start_hour: int = 23, end_hour: int = 9) -> bool:
    """بررسی قرار داشتن زمان کنونی تهران در ساعات سکوت و استراحت شبانه"""
    try:
        h = get_now().hour
        sh = int(start_hour)
        eh = int(end_hour)
        if sh > eh:
            return h >= sh or h < eh
        else:
            return sh <= h < eh
    except Exception:
        return False


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


def to_persian_digits(text: Union[str, int, float, None]) -> str:
    """
    تبدیل ارقام انگلیسی به فارسی
    """
    if text is None:
        return ""
    s = str(text)
    mapping = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
    return s.translate(mapping)


def format_activity_time(date_input: Union[str, datetime, None]) -> dict:
    """
    محاسبه و فرمت‌بندی هوشمند زمان آخرین فعالیت بر اساس ساعت تهران و تبدیل به متن فارسی و تاریخ شمسی:
    - خروجی: دیکشنری شامل:
      - 'ago': متن زمان نسبی با ارقام فارسی (مثلاً «لحظاتی پیش»، «۱۵ دقیقه پیش»، «۲ ساعت پیش»، «دیروز ۱۶:۳۰»، «۴ روز پیش»)
      - 'shamsi_full': تاریخ و ساعت کامل شمسی (مثلاً «۱۴۰۵/۰۶/۲۹ ۱۶:۳۵»)
      - 'shamsi_date': تاریخ شمسی (مثلاً «۱۴۰۵/۰۶/۲۹»)
      - 'has_activity': آیا فعالیتی ثبت شده است یا خیر (True/False)
      - 'raw_iso': زمان خام دریافتی
      - 'tooltip': متن راهنمای کامل جهت استفاده در ویژگی title
    """
    if not date_input or str(date_input).strip() in ("", "None", "null", "-", "0") or str(date_input).startswith("0001"):
        return {
            "ago": "بدون فعالیت",
            "shamsi_full": "-",
            "shamsi_date": "-",
            "has_activity": False,
            "raw_iso": None,
            "tooltip": "هیچ فعالیت ثبت‌شده‌ای در سامانه یافت نشد"
        }
    
    try:
        clean = str(date_input).strip()
        # پردازش رشته‌های تاریخ ایزو یا معمولی
        if isinstance(date_input, datetime):
            dt = date_input
        else:
            clean_fixed = clean.replace("Z", "+00:00")
            if "+" in clean_fixed[10:] or "-" in clean_fixed[10:]:
                dt = datetime.fromisoformat(clean_fixed)
            else:
                clean_no_milli = clean.split(".")[0].replace("T", " ")
                if len(clean_no_milli) >= 19:
                    dt = datetime.strptime(clean_no_milli[:19], "%Y-%m-%d %H:%M:%S")
                elif len(clean_no_milli) >= 16:
                    dt = datetime.strptime(clean_no_milli[:16], "%Y-%m-%d %H:%M")
                elif len(clean_no_milli) >= 10:
                    dt = datetime.strptime(clean_no_milli[:10], "%Y-%m-%d")
                else:
                    dt = datetime.fromisoformat(clean)

        # اعمال دقیق منطقه زمانی تهران
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TEHRAN_TZ)
        else:
            dt = dt.astimezone(TEHRAN_TZ)

        now_tehran = datetime.now(TEHRAN_TZ)
        diff_sec = int((now_tehran - dt).total_seconds())

        shamsi_full_raw = gregorian_to_shamsi(dt, fmt="%Y/%m/%d %H:%M")
        shamsi_date_raw = gregorian_to_shamsi(dt, fmt="%Y/%m/%d")
        shamsi_full = to_persian_digits(shamsi_full_raw)
        shamsi_date = to_persian_digits(shamsi_date_raw)

        if diff_sec < 60:
            ago = "لحظاتی پیش"
        elif diff_sec < 3600:
            mins = diff_sec // 60
            ago = f"{to_persian_digits(mins)} دقیقه پیش"
        elif diff_sec < 86400 and (now_tehran.date() == dt.date()):
            hrs = diff_sec // 3600
            ago = f"{to_persian_digits(hrs)} ساعت پیش"
        elif diff_sec < 172800 or (now_tehran.date() - dt.date()).days == 1:
            time_part = to_persian_digits(dt.strftime("%H:%M"))
            ago = f"دیروز {time_part}"
        else:
            diff_days = (now_tehran.date() - dt.date()).days
            days = max(1, diff_days if diff_days > 0 else (diff_sec // 86400))
            if days < 30:
                ago = f"{to_persian_digits(days)} روز پیش"
            elif days < 365:
                months = days // 30
                ago = f"{to_persian_digits(months)} ماه پیش"
            else:
                years = days // 365
                ago = f"{to_persian_digits(years)} سال پیش"

        tooltip = f"آخرین فعالیت: {shamsi_full} (به وقت تهران)"

        return {
            "ago": ago,
            "shamsi_full": shamsi_full,
            "shamsi_date": shamsi_date,
            "has_activity": True,
            "raw_iso": clean,
            "tooltip": tooltip
        }
    except Exception:
        fallback_str = to_persian_digits(str(date_input)[:16].replace("T", " "))
        return {
            "ago": fallback_str,
            "shamsi_full": fallback_str,
            "shamsi_date": fallback_str[:10],
            "has_activity": True,
            "raw_iso": str(date_input),
            "tooltip": f"آخرین فعالیت: {fallback_str}"
        }


def generate_qr_code_bytes(data: str) -> Optional[bytes]:
    """
    تولید تصویر QR Code به صورت بایت‌ها با حاشیه سفید عریض (Quiet Zone) جهت اسکن بدون اختلال در تم‌های تیره
    """
    import io
    try:
        import qrcode
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=10,
            border=5,  # حاشیه سفید استاندارد و پهن دور QR برای تم‌های تاریک
        )
        qr.add_data(data)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        bio = io.BytesIO()
        img.save(bio, format="PNG")
        bio.seek(0)
        return bio.getvalue()
    except Exception:
        # Fallback به API آنلاین در صورت نبود پکیج qrcode با حاشیه سفید ۲۰ پیکسلی
        try:
            import urllib.parse
            import urllib.request
            encoded = urllib.parse.quote(data)
            url = f"https://api.qrserver.com/v1/create-qr-code/?size=350x350&margin=25&data={encoded}"
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
    import json
    tpl = None
    if db_instance is not None:
        try:
            tpl = db_instance.get_setting("single_link_template")
        except Exception:
            pass
    if tpl is None:
        try:
            from database import db
            tpl = db.get_setting("single_link_template")
        except Exception:
            pass

    if tpl is not None:
        if isinstance(tpl, dict):
            return json.dumps(tpl, indent=2, ensure_ascii=False)
        if isinstance(tpl, str) and tpl.strip():
            return tpl.strip()

    return os.getenv("SINGLE_LINK_TEMPLATE", DEFAULT_SINGLE_CONFIG_TEMPLATE)


def format_single_link(template, uuid: str, name: str) -> str:
    """
    جایگذاری خودکار UUID و نام مشتری در قالب لینک تکی و تولید خروجی VMess یا URI
    - در صورت ورودی JSON (یا vmess:// یا dict): مشخصات مشتری در فیلدهای id و ps قرار گرفته و خروجی به فرمت استاندارد vmess://Base64 تولید می‌شود.
    - در صورت ورودی URI (مانند vless:// یا trojan://): متغیرهای {uuid} و {name} جایگذاری می‌شوند.
    """
    import base64
    import json
    import urllib.parse

    clean_uuid = str(uuid or "").strip()
    clean_name = str(name or "User").strip()
    encoded_name = urllib.parse.quote(clean_name)

    if isinstance(template, dict):
        tpl_str = json.dumps(template, ensure_ascii=False)
    else:
        tpl_str = str(template or "").strip()

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


def to_english_digits(text: Union[str, int, float, None]) -> str:
    """تبدیل کلیه ارقام فارسی و عربی به ارقام انگلیسی"""
    if text is None:
        return ""
    s = str(text)
    persian_digits = "۰۱۲۳۴۵۶۷۸۹"
    arabic_digits = "٠١٢٣٤٥٦٧٨٩"
    for i in range(10):
        s = s.replace(persian_digits[i], str(i)).replace(arabic_digits[i], str(i))
    return s


def calculate_debt_auto_disable_at(
    days_val: Union[int, str, None] = 3,
    shamsi_date_str: Optional[str] = None,
    base_dt: Optional[datetime] = None
) -> str:
    """
    محاسبه تاریخ و زمان دقیق انقضا و قطع خودکار اشتراک بدهکار.
    ساعت، دقیقه و ثانیه دقیقا مطابق با لحظه تنظیم فرم (base_dt) حفظ می‌گردد.
    
    Args:
        days_val: تعداد روز مهلت (پیش‌فرض ۳ روز)
        shamsi_date_str: تاریخ دقیق شمسی به صورت YYYY/MM/DD یا YYYY-MM-DD
        base_dt: شیء datetime مبدا (پیش‌فرض زمان جاری تهران یا سرور)
        
    Returns:
        رشته ISO میلادی زمان قطع خودکار
    """
    if base_dt is None:
        base_dt = get_now_naive()

    # ۱. اگر تاریخ شمسی دقیق ارسال شده باشد
    if shamsi_date_str and str(shamsi_date_str).strip():
        clean_str = to_english_digits(str(shamsi_date_str).strip().replace("-", "/"))
        parts = [int(p) for p in clean_str.split("/") if p.isdigit()]
        if len(parts) == 3:
            jy, jm, jd = parts
            try:
                g_date = jdatetime.date(jy, jm, jd).togregorian()
                target_dt = datetime.combine(g_date, base_dt.time())
                # اگر تاریخ انتخابی از زمان فعلی گذشته باشد، حداقل مهلت ۱ روزه اعمال می‌شود
                if target_dt <= base_dt:
                    target_dt = base_dt + timedelta(days=1)
                return target_dt.isoformat()
            except Exception:
                pass

    # ۲. محاسبه بر مبنای تعداد روز
    try:
        days = int(days_val or 3)
        if days <= 0:
            days = 3
    except Exception:
        days = 3

    target_dt = base_dt + timedelta(days=days)
    return target_dt.isoformat()
