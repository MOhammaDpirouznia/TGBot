#!/usr/bin/env python3
"""
ماژول پارس هوشمند پیامک‌های واریز بانک‌های ایران
استخراج خودکار مبلغ، ارز (ریال/تومان)، شماره کارت/حساب و نوع تراکنش
"""

import re
import logging
from typing import Optional, Dict, Any, Tuple

logger = logging.getLogger(__name__)

# جدول تبدیل اعداد فارسی و عربی به انگلیسی
PERSIAN_ARABIC_DIGITS = {
    '۰': '0', '۱': '1', '۲': '2', '۳': '3', '۴': '4',
    '۵': '5', '۶': '6', '۷': '7', '۸': '8', '۹': '9',
    '٠': '0', '١': '1', '٢': '2', '٣': '3', '٤': '4',
    '٥': '5', '٦': '6', '٧': '7', '٨': '8', '٩': '9'
}


def normalize_persian_text(text: str) -> str:
    """نرمال‌سازی حروف و اعداد فارسی و عربی"""
    if not text:
        return ""
    
    # تبدیل اعداد
    for p_digit, e_digit in PERSIAN_ARABIC_DIGITS.items():
        text = text.replace(p_digit, e_digit)
        
    # یکنواخت‌سازی حروف
    text = text.replace('ي', 'ی').replace('ك', 'ک').replace('ة', 'ه')
    # حذف نیم‌فاصله و کاراکترهای مخفی
    text = text.replace('\u200c', ' ').replace('\u200f', '').replace('\u200e', '')
    return text


def parse_bank_sms(raw_text: str, sender: str = "") -> Optional[Dict[str, Any]]:
    """
    تحلیل و استخراج اطلاعات پیامک واریز بانکی
    
    خروجی:
        dict حاوی:
            - is_deposit: بولین (آیا واریز است یا خیر)
            - amount_toman: مبلغ به تومان (عدد صحیح)
            - amount_raw: مبلغ خام
            - currency: 'toman' یا 'rial'
            - bank_name: نام بانک تشخیص داده شده
            - tracking_code: کد پیگیری (در صورت وجود)
            - card_hint: ۴ رقم آخر کارت یا حساب (در صورت وجود)
    """
    if not raw_text or not isinstance(raw_text, str):
        return None

    text = normalize_persian_text(raw_text.strip())
    lower_sender = sender.lower() if sender else ""

    # ۱. بررسی اینکه آیا پیامک واریز است یا برداشت
    withdrawal_keywords = [
        "برداشت", "خرید اینترنتی", "خرید کالا", "انتقال از حساب شما",
        "کسر شد", "کارمزد", "پرداخت قبض", "شارژ سیم کارت"
    ]
    deposit_keywords = [
        "واریز", "واريز", "افزایش", "انتقال به", "دریافت شد", "پایا واریز",
        "ساتنا واریز", "واریز پایا", "واریز ساتنا", "واریز شتابی", "انتقال پل"
    ]

    has_deposit = any(k in text for k in deposit_keywords)
    has_withdrawal = any(k in text for k in withdrawal_keywords)

    if has_withdrawal and not has_deposit:
        logger.debug("SMS is a withdrawal, ignoring.")
        return {"is_deposit": False, "reason": "withdrawal"}

    if not has_deposit:
        if not ("موجود" in text or "مانده" in text or "افزایش" in text):
            return {"is_deposit": False, "reason": "not_a_deposit"}

    # ۲. تشخیص بانک بر اساس متن یا شماره فرستنده
    detected_bank = "نامشخص"
    bank_patterns = [
        (r"بلو(بانک)?|blubank", "بلوبانک"),
        (r"بانک ملی|بام|bmi\.ir", "بانک ملی"),
        (r"بانک ملت|mellat", "بانک ملت"),
        (r"بانک سامان|sb24", "بانک سامان"),
        (r"بانک پاسارگاد|bpi", "بانک پاسارگاد"),
        (r"بانک تجارت|tejarat", "بانک تجارت"),
        (r"بانک سپه|sepah", "بانک سپه"),
        (r"بانک صادرات|bsi", "بانک صادرات"),
        (r"بانک کشاورزی|bki", "بانک کشاورزی"),
        (r"بانک رسالت|resalat", "بانک رسالت"),
        (r"بانک مهر|qmb", "بانک مهر ایران"),
        (r"بانک شهر|shahr", "بانک شهر"),
        (r"بانک مسکن|maskan", "بانک مسکن"),
        (r"بانک آینده|ayandeh", "بانک آینده"),
        (r"بانک پارسیان|parsian", "بانک پارسیان"),
        (r"بانک سینا|sina", "بانک سینا"),
        (r"بانک دی|day", "بانک دی"),
        (r"بانک رفاه|refah", "بانک رفاه"),
    ]

    combined_bank_str = text + " " + lower_sender
    for pattern, bname in bank_patterns:
        if re.search(pattern, combined_bank_str, re.IGNORECASE):
            detected_bank = bname
            break

    # ۳. استخراج مبلغ با دقت بالا
    amount_toman = None
    currency_found = None
    raw_amount_found = None

    amount_regexes = [
        r"(?:واریز|واريز|انتقال به|مبلغ)\s*[:\s]*([0-9,]{4,15})\s*(تومان|ریال|ريال)",
        r"مبلغ\s*[:\s]+([0-9,]{4,15})(?:\s*(تومان|ریال|ريال))?",
        r"\+\s*([0-9,]{4,15})\s*(تومان|ریال|ريال)",
        r"(?:واریز|واريز)\s*[:\s]+([0-9,]{4,15})",
        r"([0-9,]{4,15})\s*(تومان|ریال|ريال)\s*(?:به|واریز|واريز)",
    ]

    for rgx in amount_regexes:
        match = re.search(rgx, text)
        if match:
            num_str = match.group(1).replace(",", "").strip()
            try:
                raw_amount = int(num_str)
                curr = None
                if len(match.groups()) >= 2 and match.group(2):
                    curr = match.group(2).strip()

                raw_amount_found = raw_amount

                if curr == "تومان" or detected_bank == "بلوبانک":
                    currency_found = "toman"
                    amount_toman = raw_amount
                elif curr in ("ریال", "ريال"):
                    currency_found = "rial"
                    amount_toman = raw_amount // 10
                else:
                    if raw_amount >= 10000 and raw_amount % 10 == 0:
                        currency_found = "rial (assumed)"
                        amount_toman = raw_amount // 10
                    else:
                        currency_found = "toman (assumed)"
                        amount_toman = raw_amount

                if amount_toman and amount_toman > 0:
                    break
            except ValueError:
                continue

    if not amount_toman:
        logger.warning(f"Could not extract amount from bank SMS: {text[:80]}...")
        return {
            "is_deposit": True,
            "bank_name": detected_bank,
            "amount_toman": None,
            "raw_text": text
        }

    # ۴. استخراج شماره پیگیری / ارجاع / شناسه (در صورت وجود)
    tracking_code = None
    track_match = re.search(r"(?:پیگیری|ارجاع|شناسه|رهگیری|مرجع|rrn)\s*[:\s]*([0-9a-zA-Z]{5,20})", text, re.IGNORECASE)
    if track_match:
        tracking_code = track_match.group(1)

    # ۵. استخراج ۴ رقم کارت یا حساب مقصد
    card_hint = None
    card_match = re.search(r"(?:حساب|کارت|به)\s*[:\s]*\*?([0-9]{3,4})\b", text)
    if card_match:
        card_hint = card_match.group(1)

    return {
        "is_deposit": True,
        "amount_toman": amount_toman,
        "amount_raw": raw_amount_found,
        "currency": currency_found,
        "bank_name": detected_bank,
        "tracking_code": tracking_code,
        "card_hint": card_hint,
        "raw_text": text
    }
