#!/usr/bin/env python3
"""
ماژول مدیریت کارت‌ها و پلن‌ها توسط ادمین
"""

import json
from pathlib import Path
from datetime import datetime
from utils import get_now_iso

# مسیر ذخیره اطلاعات
DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

# فایل‌های ذخیره‌سازی
CARDS_FILE = DATA_DIR / "cards.json"
PLANS_FILE = DATA_DIR / "plans.json"


# ═══════════════════════════════════════════════════════════════════════
# مدیریت کارت‌ها
# ═══════════════════════════════════════════════════════════════════════

def load_cards() -> dict:
    """بارگذاری کارت‌ها با اولویت فایل محلی -> دیتابیس -> فایل پشتیبان"""
    if CARDS_FILE.exists():
        try:
            with open(CARDS_FILE, "r", encoding="utf-8") as f:
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
            with open(CARDS_FILE, "w", encoding="utf-8") as f:
                json.dump(setting_cards, f, ensure_ascii=False, indent=2)
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
            with open(CARDS_FILE, "w", encoding="utf-8") as f:
                json.dump(res, f, ensure_ascii=False, indent=2)
            return res
    except Exception:
        pass

    return {}


def save_cards(cards: dict):
    """ذخیره کارت‌ها"""
    with open(CARDS_FILE, "w", encoding="utf-8") as f:
        json.dump(cards, f, ensure_ascii=False, indent=2)
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


def get_active_card() -> dict:
    """دریافت کارت فعال"""
    cards = load_cards()
    
    for card_id, card in cards.items():
        if card.get("is_active", False):
            return {"card_id": card_id, **card}
    
    # اگه کارت فعال نبود، اولین کارت رو برگردون
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
    if PLANS_FILE.exists():
        try:
            with open(PLANS_FILE, "r", encoding="utf-8") as f:
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
            with open(PLANS_FILE, "w", encoding="utf-8") as f:
                json.dump(setting_plans, f, ensure_ascii=False, indent=2)
            return setting_plans

        # بررسی فایل پشتیبان جامع backup_full_latest.json
        for backup_path in [Path("data/backup_full_latest.json"), Path("/data/backup_full_latest.json")]:
            if backup_path.exists():
                with open(backup_path, "r", encoding="utf-8") as f:
                    bdata = json.load(f)
                    settings_rows = bdata.get("tables", {}).get("settings", [])
                    for s in settings_rows:
                        if s.get("key") == "plans_config":
                            val = s.get("value")
                            pdict = json.loads(val) if isinstance(val, str) else val
                            if pdict and isinstance(pdict, dict):
                                with open(PLANS_FILE, "w", encoding="utf-8") as pf:
                                    json.dump(pdict, pf, ensure_ascii=False, indent=2)
                                return pdict
    except Exception:
        pass

    # پلن‌های پیش‌فرض فقط در صورتی که دیتابیس و بک‌آپ نیز کاملاً خالی باشند
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
    with open(PLANS_FILE, "w", encoding="utf-8") as f:
        json.dump(default_plans, f, ensure_ascii=False, indent=2)
    return default_plans


def save_plans(plans: dict):
    """ذخیره پلن‌ها"""
    with open(PLANS_FILE, "w", encoding="utf-8") as f:
        json.dump(plans, f, ensure_ascii=False, indent=2)
    try:
        from database import db
        db.save_setting("plans_config", plans)
        db.export_full_backup_json()
    except Exception:
        pass


def add_plan(name: str, price: int, data_limit: int, duration: int) -> dict:
    """افزودن پلن جدید"""
    plans = load_plans()
    
    # ساخت آیدی یکتا
    plan_id = f"plan_{len(plans) + 1}"
    while plan_id in plans:
        plan_id = f"plan_{len(plans) + 100}"
    
    # ساخت توضیحات خودکار
    data_text = f"{data_limit} گیگ" if data_limit > 0 else "نامحدود"
    description = f"{data_text} | {duration} روز"
    
    plans[plan_id] = {
        "name": name,
        "price": price,
        "data_limit": data_limit,
        "duration": duration,
        "description": description,
        "is_active": True,
        "created_at": get_now_iso(),
    }
    
    save_plans(plans)
    return {"success": True, "plan_id": plan_id}


def update_plan(plan_id: str, **kwargs) -> dict:
    """بروزرسانی پلن و امکان تغییر شناسه پلن"""
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
        if key in ["name", "price", "data_limit", "duration", "is_active"]:
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


def get_active_plans() -> dict:
    """دریافت پلن‌های فعال"""
    plans = load_plans()
    return {pid: p for pid, p in plans.items() if p.get("is_active", False)}


def get_all_plans() -> dict:
    """دریافت تمام پلن‌ها"""
    return load_plans()


def get_plan(plan_id: str) -> dict:
    """دریافت یک پلن"""
    plans = load_plans()
    return plans.get(plan_id, {})
