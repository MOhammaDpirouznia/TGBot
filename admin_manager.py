#!/usr/bin/env python3
"""
ماژول مدیریت کارت‌ها و پلن‌ها توسط ادمین
"""

import os
import json
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict
from utils import get_now_iso

# تشخیص مسیر پویا بر اساس متغیرهای محیطی یا مسیرهای پیش‌فرض
POSSIBLE_DIRS = [
    Path(os.environ.get("DATA_DIR", "")) if os.environ.get("DATA_DIR") else None,
    Path("/data"),
    Path(os.path.expanduser("~/.vpn-bot/data")),
    Path("data"),
    Path("."),
]

def get_storage_dir() -> Path:
    for p in POSSIBLE_DIRS:
        if p and p != Path(""):
            try:
                p.mkdir(parents=True, exist_ok=True)
                test_f = p / ".write_test_admin"
                test_f.write_text("ok")
                test_f.unlink()
                return p
            except Exception:
                continue
    p = Path("data")
    p.mkdir(exist_ok=True)
    return p

DATA_DIR = get_storage_dir()
CARDS_FILE = DATA_DIR / "cards.json"
PLANS_FILE = DATA_DIR / "plans.json"


# ═══════════════════════════════════════════════════════════════════════
# مدیریت کارت‌ها
# ═══════════════════════════════════════════════════════════════════════

def load_cards() -> dict:
    """بارگذاری کارت‌ها با اولویت تمام مسیرهای فایل محلی -> دیتابیس -> فایل پشتیبان"""
    candidate_files = [
        CARDS_FILE,
        Path("data/cards.json"),
        Path("/data/cards.json"),
        Path("cards.json"),
    ]
    for cfile in candidate_files:
        if cfile.exists():
            try:
                with open(cfile, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if data and isinstance(data, dict):
                        return data
            except Exception:
                pass

    # بررسی دیتابیس
    try:
        from database import db
        setting_cards = db.get_setting("cards_config")
        if setting_cards and isinstance(setting_cards, dict):
            save_cards(setting_cards)
            return setting_cards

        # بررسی جدول bank_cards
        db_cards = db.get_all_bank_cards()
        if db_cards:
            res = {}
            for c in db_cards:
                cid = f"card_{c['id']}"
                res[cid] = {
                    "card_number": c["card_number"],
                    "card_holder": c["card_holder"],
                    "bank_name": c["bank_name"],
                    "is_active": bool(c.get("is_active", True)),
                    "created_at": c.get("created_at") or get_now_iso(),
                }
            save_cards(res)
            return res
    except Exception:
        pass

    return {}


def save_cards(cards: dict):
    """ذخیره کارت‌ها در تمامی مسیرهای ذخیره‌سازی و دیتابیس"""
    targets = [CARDS_FILE, Path("data/cards.json"), Path("cards.json")]
    if Path("/data").exists():
        targets.append(Path("/data/cards.json"))
        
    for target in targets:
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "w", encoding="utf-8") as f:
                json.dump(cards, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    try:
        from database import db
        db.save_setting("cards_config", cards)
        db.export_full_backup_json()
    except Exception:
        pass


def add_card(card_number: str, card_holder: str, bank_name: str) -> dict:
    """افزودن کارت جدید"""
    cards = load_cards()
    
    # ساخت آیدی یکتا
    card_id = f"card_{len(cards) + 1}"
    while card_id in cards:
        card_id = f"card_{len(cards) + 100}"
    
    cards[card_id] = {
        "card_number": card_number,
        "card_holder": card_holder,
        "bank_name": bank_name,
        "is_active": True,
        "created_at": get_now_iso(),
    }
    
    save_cards(cards)
    return {"success": True, "card_id": card_id}


def update_card(card_id: str, **kwargs) -> dict:
    """بروزرسانی کارت"""
    cards = load_cards()
    
    if card_id not in cards:
        return {"success": False, "error": "کارت یافت نشد"}
    
    for key, value in kwargs.items():
        if key in ["card_number", "card_holder", "bank_name", "is_active"]:
            cards[card_id][key] = value
    
    cards[card_id]["updated_at"] = get_now_iso()
    save_cards(cards)
    return {"success": True}


def delete_card(card_id: str) -> dict:
    """حذف کارت"""
    cards = load_cards()
    
    if card_id not in cards:
        return {"success": False, "error": "کارت یافت نشد"}
    
    del cards[card_id]
    save_cards(cards)
    return {"success": True}


def get_active_cards() -> dict:
    """دریافت کارت‌های فعال"""
    cards = load_cards()
    return {cid: c for cid, c in cards.items() if c.get("is_active", False)}


def get_active_card(incoming_amount: int = 0) -> dict:
    """دریافت کارت فعال برای پرداخت با اولویت دیتابیس پنل مدیریت و روتاتور هوشمند پیش‌فرض/پشتیبان بر اساس سقف روزانه"""
    try:
        from database import db
        best = db.get_best_active_card(owner_type="admin", incoming_amount=incoming_amount)
        if best:
            return {
                "card_id": f"card_{best['id']}",
                "card_number": best["card_number"],
                "card_holder": best.get("card_holder") or "",
                "bank_name": best.get("bank_name") or "",
                "is_active": True,
                **best
            }
        # در صورت نبود جدول، بررسی کارت‌های فعال معمولی
        db_cards = db.get_active_bank_cards()
        if db_cards:
            c = db_cards[0]
            return {
                "card_id": f"card_{c['id']}",
                "card_number": c["card_number"],
                "card_holder": c.get("card_holder") or "",
                "bank_name": c.get("bank_name") or "",
                "is_active": True,
                **c
            }
    except Exception:
        pass

    cards = load_cards()
    for card_id, card in cards.items():
        if card.get("is_active", False):
            return {"card_id": card_id, **card}
    if cards:
        first_card_id = next(iter(cards))
        return {"card_id": first_card_id, **cards[first_card_id]}
    return {}



def get_all_cards() -> dict:
    """دریافت تمام کارت‌ها"""
    return load_cards()


# ═══════════════════════════════════════════════════════════════════════
# مدیریت پلن‌ها
# ═══════════════════════════════════════════════════════════════════════

def load_plans() -> dict:
    """بارگذاری پلن‌ها با اولویت فایل محلی -> دیتابیس -> بک‌آپ جامع -> پلن‌های پیش‌فرض"""
    candidate_files = [
        PLANS_FILE,
        Path("data/plans.json"),
        Path("/data/plans.json"),
        Path("plans.json"),
    ]
    for pfile in candidate_files:
        if pfile.exists():
            try:
                with open(pfile, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if data and isinstance(data, dict):
                        return data
            except Exception:
                pass

    # بررسی دیتابیس
    try:
        from database import db
        setting_plans = db.get_setting("plans_config")
        if setting_plans and isinstance(setting_plans, dict):
            save_plans(setting_plans)
            return setting_plans

        # بررسی فایل پشتیبان جامع backup_full_latest.json
        for backup_path in [Path("data/backup_full_latest.json"), Path("/data/backup_full_latest.json"), Path("backup_full_latest.json")]:
            if backup_path.exists():
                with open(backup_path, "r", encoding="utf-8") as f:
                    bdata = json.load(f)
                    settings_rows = bdata.get("tables", {}).get("settings", [])
                    for s in settings_rows:
                        if s.get("key") == "plans_config":
                            val = s.get("value")
                            pdict = json.loads(val) if isinstance(val, str) else val
                            if pdict and isinstance(pdict, dict):
                                save_plans(pdict)
                                return pdict
    except Exception:
        pass

    # پلن‌های پیش‌فرض
    default_plans = {
        "basic": {
            "name": "پایه",
            "price": 250000,
            "data_limit": 30,
            "duration": 30,
            "description": "۳۰ گیگ | ۳۰ روز",
            "is_active": True,
            "created_at": get_now_iso(),
        },
        "standard": {
            "name": "استاندارد",
            "price": 400000,
            "data_limit": 60,
            "duration": 30,
            "description": "۶۰ گیگ | ۳۰ روز",
            "is_active": True,
            "created_at": get_now_iso(),
        },
        "premium": {
            "name": "پریمیوم",
            "price": 600000,
            "data_limit": 100,
            "duration": 30,
            "description": "۱۰۰ گیگ | ۳۰ روز",
            "is_active": True,
            "created_at": get_now_iso(),
        },
        "gem": {
            "name": "الماس",
            "price": 990000,
            "data_limit": 180,
            "duration": 30,
            "description": "۱۸۰ گیگ | ۳۰ روز",
            "is_active": True,
            "created_at": get_now_iso(),
        },
    }
    save_plans(default_plans)
    return default_plans


def save_plans(plans: dict):
    """ذخیره پلن‌ها در تمامی فایل‌های محلی، دیتابیس و بک‌آپ"""
    targets = [PLANS_FILE, Path("data/plans.json"), Path("plans.json")]
    if Path("/data").exists():
        targets.append(Path("/data/plans.json"))

    for target in targets:
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "w", encoding="utf-8") as f:
                json.dump(plans, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    try:
        from database import db
        db.save_setting("plans_config", plans)
        db.export_full_backup_json()
    except Exception:
        pass


# نگاشت آیکون‌های فونت‌آوسام به ایموجی‌های شکیل تلگرام
ICON_TO_TELEGRAM_EMOJI = {
    "crown": "👑",
    "gem": "💎",
    "diamond": "💎",
    "trophy": "🏆",
    "award": "🥇",
    "medal": "🥇",
    "star": "⭐",
    "fire": "🔥",
    "flame": "🔥",
    "fire-flame-curved": "🔥",
    "shield": "🛡️",
    "shield-halved": "🛡️",
    "cube": "📦",
    "cubes": "📦",
    "box": "📦",
    "box-open": "📦",
    "rocket": "🚀",
    "bolt": "⚡",
    "zap": "⚡",
    "gauge": "⚡",
    "gauge-high": "⚡",
    "apple": "🍏",
    "apple-whole": "🍏",
    "heart": "❤️",
    "globe": "🌐",
    "cloud": "☁️",
    "wifi": "📶",
    "network-wired": "🌐",
    "server": "🖥️",
    "laptop": "💻",
    "mobile": "📱",
    "mobile-screen": "📱",
    "check": "✅",
    "circle-check": "✅",
    "leaf": "🍃",
    "seedling": "🌱",
    "lock": "🔒",
    "key": "🔑",
    "gift": "🎁",
    "sparkles": "✨",
    "wand-magic-sparkles": "✨",
    "infinity": "♾️",
    "cart": "🛒",
    "bag": "🛍️",
    "basket-shopping": "🛍️",
    "tag": "🏷️",
    "tags": "🏷️",
    "plane": "✈️",
    "tornado": "🌪️",
    "thumbs-up": "👍",
    "bell": "🔔",
    "compass": "🧭",
}

TIER_COLOR_CONFIG = {
    "primary": {
        "hex": "#6366f1",
        "bg": "rgba(99, 102, 241, 0.15)",
        "border": "rgba(99, 102, 241, 0.35)",
        "class": "bg-primary-subtle text-primary border border-primary border-opacity-50 shadow-sm",
    },
    "warning": {
        "hex": "#f59e0b",
        "bg": "rgba(245, 158, 11, 0.15)",
        "border": "rgba(245, 158, 11, 0.35)",
        "class": "bg-warning-subtle text-warning border border-warning shadow-sm",
    },
    "danger": {
        "hex": "#ef4444",
        "bg": "rgba(239, 68, 68, 0.15)",
        "border": "rgba(239, 68, 68, 0.35)",
        "class": "bg-danger-subtle text-danger border border-danger shadow-sm",
    },
    "info": {
        "hex": "#0284c7",
        "bg": "rgba(2, 132, 199, 0.15)",
        "border": "rgba(2, 132, 199, 0.35)",
        "class": "bg-info-subtle text-info border border-info shadow-sm",
    },
    "secondary": {
        "hex": "#64748b",
        "bg": "rgba(100, 116, 139, 0.15)",
        "border": "rgba(100, 116, 139, 0.35)",
        "class": "bg-secondary-subtle text-secondary border border-secondary",
    },
    "success": {
        "hex": "#10b981",
        "bg": "rgba(16, 185, 129, 0.15)",
        "border": "rgba(16, 185, 129, 0.35)",
        "class": "bg-success-subtle text-success border border-success",
    },
}


def get_plan_icon(plan: dict = None, plan_id: str = None) -> dict:
    """
    تحلیل هوشمند رتبه پلن و ارائه آیکون و استایل شیک و یکپارچه در تمامی بخش‌های سیستم
    (پنل مدیریت، پنل نمایندگان، لینک تمدید/پرداخت مشتری، و ربات تلگرام).
    تمامی بخش‌ها مستقیماً از آیکون و مشخصات پلن مادر در پنل مدیریت الگوبرداری می‌کنند.
    """
    plan_dict = plan if isinstance(plan, dict) else {}
    pid = str(plan_id or plan_dict.get("plan_id") or plan_dict.get("id") or "").strip()

    # دریافت اطلاعات پلن مادر از پنل مدیریت (مرجع قطعی اطلاعات)
    master_plan = {}
    if pid:
        try:
            all_masters = load_plans() or {}
            master_plan = all_masters.get(pid) or {}
        except Exception:
            pass

    # استخراج آیکون سفارشی تعریف شده توسط مدیریت
    custom_icon = (
        master_plan.get("plan_icon")
        or master_plan.get("icon")
        or plan_dict.get("plan_icon")
        or plan_dict.get("icon")
    )
    detected_emoji = None

    if custom_icon:
        custom_icon = str(custom_icon).strip()
        # بررسی اگر کاربر ایموجی مستقیم یا نام کلاس فونت‌آوسام وارد کرده باشد
        if any(ord(c) > 127 for c in custom_icon) and not any(p in custom_icon for p in ["fa-", "fas", "far", "fab"]):
            detected_emoji = custom_icon
            for kw, em in ICON_TO_TELEGRAM_EMOJI.items():
                if em in custom_icon:
                    custom_icon = f"fas fa-{kw}"
                    break
        else:
            cleaned = custom_icon.strip()
            # استخراج آیکون صحیح حتی اگر کاربر متن اضافی یا دونقطه نوشته باشد
            if "fa-" in cleaned:
                import re
                fa_match = re.search(r'(fas|far|fab|fa-solid|fa-regular)?\s*(fa-[a-z0-9-]+)', cleaned)
                if fa_match:
                    prefix = fa_match.group(1) or "fas"
                    if prefix.startswith("fa-"):
                        prefix = "fas"
                    custom_icon = f"{prefix} {fa_match.group(2)}"
                else:
                    custom_icon = cleaned
            elif not cleaned.startswith("fa") and not cleaned.startswith("bi"):
                custom_icon = f"fas fa-{cleaned}"
            elif cleaned.startswith("fa-") and not any(cleaned.startswith(p) for p in ["fas ", "far ", "fab ", "fa-solid ", "fa-regular ", "fa-light "]):
                custom_icon = f"fas {cleaned}"
            else:
                custom_icon = cleaned

    # مشخصات پلن: اولویت کامل با پلن مادر مدیریت جهت حفظ هماهنگی ۱۰۰٪
    name = (master_plan.get("name") or plan_dict.get("master_name") or plan_dict.get("name") or "").strip().lower()
    data_limit = float(master_plan.get("data_limit") if master_plan.get("data_limit") is not None else (plan_dict.get("master_data_limit") or plan_dict.get("data_limit") or plan_dict.get("display_data_limit") or 0))
    price = int(master_plan.get("price") if master_plan.get("price") is not None else (plan_dict.get("master_price") or plan_dict.get("price") or plan_dict.get("display_price") or 0))
    pid_lower = pid.lower()

    # رتبه ۷: الماس / اپل پلاس / VIP ارشد / زمرد / یاقوت / ماکسیمم حجم یا قیمت
    if any(k in name or k in pid_lower for k in ["اپل", "apple", "الماس", "زمرد", "یاقوت", "فیروزه", "جواهر", "کریستال", "gem", "diamond", "emerald", "ruby", "crystal", "royal", "رویال", "vip", "وی آی پی", "ویژه"]) or data_limit >= 250 or price >= 1500000:
        c_name = "primary"
        fallback_icon = "fas fa-gem"
        badge_style = "background: linear-gradient(135deg, #6366f1 0%, #a855f7 100%); color: white;"
        rank_title = "الماس VIP"
        tier = 7
        fallback_emoji = "💎"

    # رتبه ۶: پرومکس پلاس / اولترا / سوپر / تاج / سلطنتی / نامحدود
    elif any(k in name or k in pid_lower for k in ["پرومکس پلاس", "promaxplus", "promax+", "ultra", "اولترا", "سوپر", "super", "تاج", "شاه", "سلطنتی", "crown", "king", "نامحدود", "بینهایت", "unlimited", "infinite"]) or data_limit >= 180 or price >= 1100000:
        c_name = "warning"
        fallback_icon = "fas fa-crown"
        badge_style = "background: linear-gradient(135deg, #f59e0b 0%, #ef4444 100%); color: white;"
        rank_title = "پرومکس پلاس"
        tier = 6
        fallback_emoji = "👑"

    # رتبه ۵: پرومکس / پلاتینیوم / کاپ قهرمانی / پریمیوم
    elif any(k in name or k in pid_lower for k in ["پرومکس", "promax", "platinum", "پلاتین", "پلاتینیوم", "جام", "قهرمان", "trophy", "champion", "premium", "پرمیوم", "پریمیوم", "توربو پلاس"]) or data_limit >= 100 or price >= 800000:
        c_name = "warning"
        fallback_icon = "fas fa-trophy"
        badge_style = "background-color: #fef3c7; color: #b45309;"
        rank_title = "پرومکس"
        tier = 5
        fallback_emoji = "🏆"

    # رتبه ۴: پرو پلاس / آتش / موشک / توربو / سریع / رعد
    elif any(k in name or k in pid_lower for k in ["پرو پلاس", "proplus", "pro+", "موشک", "موشکی", "rocket", "توربو", "turbo", "سرعت", "سریع", "اکسپرس", "express", "آتش", "اتش", "شعله", "داغ", "خفن", "fire", "flame", "رعد", "صاعقه", "برق", "bolt", "zap", "شتاب", "جت"]) or data_limit >= 80:
        c_name = "danger"
        fallback_icon = "fas fa-fire-flame-curved"
        badge_style = "background-color: #fee2e2; color: #b91c1c;"
        rank_title = "پرو پلاس"
        tier = 4
        fallback_emoji = "🔥"

    # رتبه ۳: پرو / طلایی / ستاره / حرفه‌ای
    elif any(k in name or k in pid_lower for k in ["پرو", "pro", "طلا", "طلایی", "gold", "golden", "ستاره", "star", "حرفه‌ای", "حرفه ای", "محبوب", "برتر", "خاص"]) or data_limit >= 60 or price >= 500000:
        c_name = "warning"
        fallback_icon = "fas fa-star"
        badge_style = "background-color: #fef9c3; color: #854d0e;"
        rank_title = "پرو"
        tier = 3
        fallback_emoji = "⭐"

    # رتبه ۲: استاندارد / نقره‌ای / سپر / امنیت / اطلس
    elif any(k in name or k in pid_lower for k in ["استاندارد", "standard", "نقره", "نقره‌ای", "silver", "medium", "متوسط", "سپر", "امن", "امنیت", "shield", "گارد", "guard", "اطلس", "atlas", "شبکه", "گلوبال", "globe"]) or data_limit >= 40:
        c_name = "info"
        fallback_icon = "fas fa-shield-halved"
        badge_style = "background-color: #e0f2fe; color: #0369a1;"
        rank_title = "استاندارد"
        tier = 2
        fallback_emoji = "🛡️"

    # رتبه ۱: پایه / استارتر / برنز / شروع / تست / بلویال
    else:
        c_name = "secondary"
        fallback_icon = "fas fa-cube"
        badge_style = "background-color: #f1f5f9; color: #475569;"
        rank_title = "پایه"
        tier = 1
        fallback_emoji = "📦"

    final_icon = custom_icon or fallback_icon

    # تخصیص ایموجی متناظر تلگرام
    if detected_emoji:
        emoji = detected_emoji
    else:
        emoji = fallback_emoji
        if custom_icon:
            c_icon_lower = str(custom_icon).lower()
            for kw, em in ICON_TO_TELEGRAM_EMOJI.items():
                if kw in c_icon_lower:
                    emoji = em
                    break

    # تنظیم رنگ و کلاس‌ها بر اساس کانفیگ رنگ
    color_info = TIER_COLOR_CONFIG.get(c_name, TIER_COLOR_CONFIG["secondary"])

    return {
        "icon": final_icon,
        "color": color_info["hex"],  # مقدار هگز جهت حل مشکل استایل‌های inline قبلی
        "color_hex": color_info["hex"],
        "color_name": c_name,
        "bg_color": color_info["bg"],
        "border_color": color_info["border"],
        "bg_class": color_info["class"],
        "badge_style": badge_style,
        "rank_title": rank_title,
        "tier": tier,
        "emoji": emoji,
    }


def get_plan_telegram_emoji(plan: dict = None, plan_id: str = None) -> str:
    """دریافت ایموجی متناظر و همسان با پلن پنل مدیریت جهت استفاده در دکمه‌ها و پیام‌های ربات تلگرام"""
    try:
        info = get_plan_icon(plan, plan_id)
        return info.get("emoji", "📦")
    except Exception:
        return "📦"


def get_bundle_icon(bundle: dict) -> dict:
    """
    آیکون‌های شیک و جذاب برای بسته‌های پیش‌خرید شارژ کیف پول نماینده
    """
    bid = str(bundle.get("id") or "").lower()
    title = str(bundle.get("title") or "").lower()
    price = int(bundle.get("price") or 0)
    bonus = int(bundle.get("bonus_percent") or 0)

    # بالاترین بسته: الماس VIP (۱۰ میلیون یا بونوس >= ۱۵٪ یا نام الماس/VIP)
    if "10m" in bid or "الماس" in title or "vip" in title or price >= 10000000 or bonus >= 15:
        c = "#8b5cf6"
        return {
            "icon": "fas fa-gem",
            "badge_color": "warning",
            "container_class": "bundle-icon-diamond",
            "icon_color": c,
            "color": c,
            "bg": f"{c}18",
            "gradient": "linear-gradient(135deg, #a855f7 0%, #6366f1 100%)",
            "title": "الماس VIP",
            "tier": 4
        }
    # بسته طلایی (۵ میلیون یا بونوس >= ۱۰٪)
    elif "5m" in bid or "طلا" in title or "gold" in title or price >= 5000000 or bonus >= 10:
        c = "#d97706"
        return {
            "icon": "fas fa-crown",
            "badge_color": "warning",
            "container_class": "bundle-icon-gold",
            "icon_color": c,
            "color": c,
            "bg": f"{c}18",
            "gradient": "linear-gradient(135deg, #f59e0b 0%, #d97706 100%)",
            "title": "بسته طلایی",
            "tier": 3
        }
    # بسته نقره‌ای (۳ میلیون یا بونوس >= ۷٪)
    elif "3m" in bid or "نقره" in title or "silver" in title or price >= 3000000 or bonus >= 7:
        c = "#0284c7"
        return {
            "icon": "fas fa-medal",
            "badge_color": "primary",
            "container_class": "bundle-icon-silver",
            "icon_color": c,
            "color": c,
            "bg": f"{c}18",
            "gradient": "linear-gradient(135deg, #0284c7 0%, #2563eb 100%)",
            "title": "بسته نقره‌ای",
            "tier": 2
        }
    # بسته استارتر (۱ میلیون یا سایر)
    else:
        c = "#059669"
        return {
            "icon": "fas fa-rocket",
            "badge_color": "info",
            "container_class": "bundle-icon-starter",
            "icon_color": c,
            "color": c,
            "bg": f"{c}18",
            "gradient": "linear-gradient(135deg, #10b981 0%, #059669 100%)",
            "title": "بسته استارتر",
            "tier": 1
        }


def add_plan(name: str, price: int, data_limit: int, duration: int, is_exclusive_admin: bool = False, plan_icon: str = "", allowed_resellers: list = None, is_exclusive_reseller: bool = False, is_exclusive_admin_bot: bool = False) -> dict:
    """افزودن پلن جدید با امکان تعیین دسترسی اختصاصی برای مدیریت، ربات مدیریت یا نمایندگان منتخب"""
    plans = load_plans()
    
    # ساخت آیدی یکتا
    plan_id = f"plan_{len(plans) + 1}"
    while plan_id in plans:
        plan_id = f"plan_{len(plans) + 100}"
    
    # ساخت توضیحات خودکار
    data_text = f"{data_limit} گیگ" if data_limit > 0 else "نامحدود"
    description = f"{data_text} | {duration} روز"
    
    clean_resellers = [int(x) for x in allowed_resellers if str(x).isdigit() or isinstance(x, int)] if allowed_resellers else []
    is_reseller_excl = bool(clean_resellers) or bool(is_exclusive_reseller)
    is_admin_bot_excl = bool(is_exclusive_admin_bot) and not is_reseller_excl
    is_admin_excl = bool(is_exclusive_admin) and not is_reseller_excl and not is_admin_bot_excl
    
    plans[plan_id] = {
        "name": name,
        "price": price,
        "data_limit": data_limit,
        "duration": duration,
        "description": description,
        "is_active": True,
        "is_exclusive_admin": is_admin_excl,
        "is_exclusive_admin_bot": is_admin_bot_excl,
        "is_exclusive_reseller": is_reseller_excl,
        "allowed_resellers": clean_resellers,
        "plan_icon": plan_icon.strip() if plan_icon else "",
        "created_at": get_now_iso(),
    }
    
    save_plans(plans)
    return {"success": True, "plan_id": plan_id}


def update_plan(plan_id: str, **kwargs) -> dict:
    """بروزرسانی پلن و امکان تغییر شناسه و سطح دسترسی پلن"""
    plans = load_plans()
    
    if plan_id not in plans:
        return {"success": False, "error": "پلن یافت نشد"}

    # تغییر شناسه پلن (در صورت ارسال new_plan_id)
    new_plan_id = kwargs.pop("new_plan_id", None)
    current_id = plan_id
    if new_plan_id and new_plan_id != plan_id:
        if new_plan_id in plans:
            return {"success": False, "error": "این شناسه پلن قبلاً وجود دارد"}
        # انتقال اطلاعات به کلید جدید
        plans[new_plan_id] = plans.pop(plan_id)
        current_id = new_plan_id

    for key, value in kwargs.items():
        if key in ["name", "price", "data_limit", "duration", "is_active", "is_exclusive_admin", "is_exclusive_admin_bot", "plan_icon", "allowed_resellers", "is_exclusive_reseller"]:
            if key == "is_exclusive_admin_bot":
                val = bool(value)
                plans[current_id]["is_exclusive_admin_bot"] = val
                if val:
                    plans[current_id]["is_exclusive_admin"] = False
                    plans[current_id]["is_exclusive_reseller"] = False
                    plans[current_id]["allowed_resellers"] = []
            elif key == "is_exclusive_admin":
                val = bool(value)
                plans[current_id]["is_exclusive_admin"] = val
                if val:
                    plans[current_id]["is_exclusive_admin_bot"] = False
                    plans[current_id]["is_exclusive_reseller"] = False
                    plans[current_id]["allowed_resellers"] = []
            elif key == "allowed_resellers":
                clean_resellers = [int(x) for x in value if str(x).isdigit() or isinstance(x, int)] if value else []
                plans[current_id]["allowed_resellers"] = clean_resellers
                plans[current_id]["is_exclusive_reseller"] = bool(clean_resellers)
                if clean_resellers:
                    plans[current_id]["is_exclusive_admin"] = False
                    plans[current_id]["is_exclusive_admin_bot"] = False
            elif key == "is_exclusive_reseller":
                plans[current_id][key] = bool(value)
                if value:
                    plans[current_id]["is_exclusive_admin"] = False
                    plans[current_id]["is_exclusive_admin_bot"] = False
            else:
                plans[current_id][key] = value
    
    # بروزرسانی توضیحات
    data_limit = plans[current_id].get("data_limit", 0)
    duration = plans[current_id].get("duration", 30)
    data_text = f"{data_limit} گیگ" if data_limit > 0 else "نامحدود"
    plans[current_id]["description"] = f"{data_text} | {duration} روز"
    
    plans[current_id]["updated_at"] = get_now_iso()
    save_plans(plans)
    return {"success": True, "plan_id": current_id}


def delete_plan(plan_id: str) -> dict:
    """حذف پلن"""
    plans = load_plans()
    
    if plan_id not in plans:
        return {"success": False, "error": "پلن یافت نشد"}
    
    del plans[plan_id]
    save_plans(plans)
    return {"success": True}


def get_active_plans(include_exclusive_admin: bool = False, reseller_id: Optional[int] = None) -> dict:
    """دریافت پلن‌های فعال (پلن‌های اختصاصی مدیریت و پلن‌های اختصاصی نمایندگان از ربات عمومی مخفی هستند)"""
    plans = load_plans()
    result = {}
    for pid, p in plans.items():
        if not p.get("is_active", False):
            continue
        if p.get("is_exclusive_admin") and not include_exclusive_admin:
            continue
        # پلن اختصاصی برای پنل و ربات مدیریت (مخفی از نمایندگان و ربات نمایندگان)
        if p.get("is_exclusive_admin_bot"):
            if reseller_id is not None:
                continue
            # برای ربات اصلی و پنل مدیریت مجاز است
            result[pid] = p
            continue
        allowed = p.get("allowed_resellers") or []
        if allowed:
            # پلن اختصاصی نمایندگان منتخب
            if reseller_id is not None and int(reseller_id) in [int(x) for x in allowed]:
                result[pid] = p
        else:
            # اگر پلن فقط اختصاصی نماینده است اما بدون لیست مشخص، مخفی بماند مگر اینکه شناسه داده شود
            if p.get("is_exclusive_reseller") and reseller_id is None:
                continue
            # پلن عمومی یا ادمین
            if reseller_id is None or not p.get("is_exclusive_admin"):
                result[pid] = p
    return result


def get_all_plans() -> dict:
    """دریافت تمام پلن‌ها"""
    return load_plans()


def get_plan(plan_id: str) -> dict:
    """دریافت یک پلن"""
    plans = load_plans()
    return plans.get(plan_id, {})


def move_plan_up(plan_id: str) -> dict:
    """انتقال یک پلن به سمت بالا در لیست ترتیب"""
    plans = load_plans()
    keys = list(plans.keys())
    if plan_id not in keys:
        return {"success": False, "error": "پلن یافت نشد"}
    idx = keys.index(plan_id)
    if idx == 0:
        return {"success": True, "message": "پلن در بالاترین جایگاه است"}
    # جابجایی با پلن قبلی
    keys[idx - 1], keys[idx] = keys[idx], keys[idx - 1]
    reordered_plans = {k: plans[k] for k in keys}
    save_plans(reordered_plans)
    return {"success": True}


def move_plan_down(plan_id: str) -> dict:
    """انتقال یک پلن به سمت پایین در لیست ترتیب"""
    plans = load_plans()
    keys = list(plans.keys())
    if plan_id not in keys:
        return {"success": False, "error": "پلن یافت نشد"}
    idx = keys.index(plan_id)
    if idx >= len(keys) - 1:
        return {"success": True, "message": "پلن در پایین‌ترین جایگاه است"}
    # جابجایی با پلن بعدی
    keys[idx], keys[idx + 1] = keys[idx + 1], keys[idx]
    reordered_plans = {k: plans[k] for k in keys}
    save_plans(reordered_plans)
    return {"success": True}

