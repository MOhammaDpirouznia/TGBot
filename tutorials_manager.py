"""
ماژول مدیریت آموزش‌ها، عیب‌یابی و ویزاردهای تعاملی (Tutorials & Troubleshooting Manager)
پشتیبانی از شخصی‌سازی، ویرایش، افزودن مطالب جدید توسط مدیر در دیتابیس و بازنشانی به پیش‌فرض
"""

import json
import logging
import copy
from typing import Dict, List, Any, Optional

from database import db
from tutorials_data import (
    PLATFORMS as DEFAULT_PLATFORMS,
    TUTORIALS as DEFAULT_TUTORIALS,
    TROUBLESHOOTING_GUIDES as DEFAULT_TROUBLESHOOTING_GUIDES,
    STEP_BY_STEP_TROUBLESHOOT as DEFAULT_STEP_BY_STEP_TROUBLESHOOT,
    STEP_BY_STEP_CONNECTION as DEFAULT_STEP_BY_STEP_CONNECTION
)

logger = logging.getLogger(__name__)

SETTING_KEY_CUSTOM_TUTORIALS = "custom_tutorials_data"
SETTING_KEY_CUSTOM_GUIDES = "custom_troubleshooting_guides"
SETTING_KEY_CUSTOM_PLATFORMS = "custom_platforms_data"
SETTING_KEY_CUSTOM_STEP_TROUBLESHOOT = "custom_step_by_step_troubleshoot"
SETTING_KEY_CUSTOM_STEP_CONNECTION = "custom_step_by_step_connection"


def get_platforms() -> Dict[str, Any]:
    """دریافت لیست تمام پلتفرم‌ها (ترکیب پیش‌فرض و تغییرات دیتابیس)"""
    platforms = copy.deepcopy(DEFAULT_PLATFORMS)
    try:
        custom_raw = db.get_setting(SETTING_KEY_CUSTOM_PLATFORMS)
        if custom_raw:
            custom_data = json.loads(custom_raw) if isinstance(custom_raw, str) else custom_raw
            if isinstance(custom_data, dict):
                for p_key, p_val in custom_data.items():
                    if p_val is None and p_key in platforms:
                        del platforms[p_key]
                    elif isinstance(p_val, dict):
                        platforms[p_key] = p_val
    except Exception as e:
        logger.error(f"Error loading custom platforms: {e}")
    return platforms


def save_platforms(platforms_data: Dict[str, Any]) -> bool:
    """ذخیره تنظیمات پلتفرم‌ها در دیتابیس"""
    try:
        db.save_setting(SETTING_KEY_CUSTOM_PLATFORMS, json.dumps(platforms_data, ensure_ascii=False))
        return True
    except Exception as e:
        logger.error(f"Error saving platforms: {e}")
        return False


def get_all_tutorials() -> Dict[str, Any]:
    """دریافت تمام آموزش‌های نرم‌افزارها (پیش‌فرض + شخصی‌سازی شده‌های مدیر در دیتابیس)"""
    tutorials = copy.deepcopy(DEFAULT_TUTORIALS)
    try:
        custom_raw = db.get_setting(SETTING_KEY_CUSTOM_TUTORIALS)
        if custom_raw:
            custom_data = json.loads(custom_raw) if isinstance(custom_raw, str) else custom_raw
            if isinstance(custom_data, dict):
                for app_key, app_val in custom_data.items():
                    if app_val is None:  # علامت‌گذاری شده به عنوان حذف شده
                        tutorials.pop(app_key, None)
                    elif isinstance(app_val, dict):
                        tutorials[app_key] = app_val
    except Exception as e:
        logger.error(f"Error loading custom tutorials: {e}")
    return tutorials


def get_tutorial(app_slug: str) -> Optional[Dict[str, Any]]:
    """دریافت آموزش یک نرم‌افزار خاص بر اساس شناسه (Slug)"""
    if not app_slug:
        return None
    all_tutorials = get_all_tutorials()
    return all_tutorials.get(app_slug.lower())


def save_tutorial(app_slug: str, data: Dict[str, Any]) -> bool:
    """ذخیره یا ویرایش آموزش نرم‌افزار در دیتابیس"""
    if not app_slug or not isinstance(data, dict):
        return False
    app_key = app_slug.strip().lower()
    try:
        custom_raw = db.get_setting(SETTING_KEY_CUSTOM_TUTORIALS)
        custom_data = json.loads(custom_raw) if custom_raw and isinstance(custom_raw, str) else (custom_raw or {})
        if not isinstance(custom_data, dict):
            custom_data = {}

        data["slug"] = app_key
        custom_data[app_key] = data
        db.save_setting(SETTING_KEY_CUSTOM_TUTORIALS, json.dumps(custom_data, ensure_ascii=False))

        # همچنین اطمینان حاصل کنیم که این نرم‌افزار به لیست apps پلتفرم مربوطه متصل باشد
        platform_name = data.get("platform")
        if platform_name:
            platforms = get_platforms()
            if platform_name in platforms:
                if "apps" not in platforms[platform_name]:
                    platforms[platform_name]["apps"] = []
                if app_key not in platforms[platform_name]["apps"]:
                    platforms[platform_name]["apps"].append(app_key)
                    save_platforms(platforms)

        return True
    except Exception as e:
        logger.error(f"Error saving tutorial {app_slug}: {e}")
        return False


def delete_tutorial(app_slug: str) -> bool:
    """حذف یک نرم‌افزار از پورتال آموزش"""
    if not app_slug:
        return False
    app_key = app_slug.strip().lower()
    try:
        custom_raw = db.get_setting(SETTING_KEY_CUSTOM_TUTORIALS)
        custom_data = json.loads(custom_raw) if custom_raw and isinstance(custom_raw, str) else (custom_raw or {})
        if not isinstance(custom_data, dict):
            custom_data = {}

        # علامت‌گذاری به عنوان حذف شده تا پیش‌فرض‌ها را هم بپوشاند
        custom_data[app_key] = None
        db.save_setting(SETTING_KEY_CUSTOM_TUTORIALS, json.dumps(custom_data, ensure_ascii=False))

        # حذف از پلتفرم مربوطه
        platforms = get_platforms()
        for p_key, p_info in platforms.items():
            if "apps" in p_info and app_key in p_info["apps"]:
                p_info["apps"].remove(app_key)
        save_platforms(platforms)

        return True
    except Exception as e:
        logger.error(f"Error deleting tutorial {app_slug}: {e}")
        return False


def get_troubleshooting_guides() -> List[Dict[str, Any]]:
    """دریافت لیست مقالات عیب‌یابی و حل مشکلات اتصال"""
    default_guides = copy.deepcopy(DEFAULT_TROUBLESHOOTING_GUIDES)
    try:
        custom_raw = db.get_setting(SETTING_KEY_CUSTOM_GUIDES)
        if custom_raw:
            custom_data = json.loads(custom_raw) if isinstance(custom_raw, str) else custom_raw
            if isinstance(custom_data, list):
                # اگر لیست اختصاصی کامل ذخیره شده است، آن را بازمی‌گرداند
                return custom_data
            elif isinstance(custom_data, dict):
                # اگر به صورت دیکشنری کلید-مقدار تغییرات داده شده است
                guides_dict = {g["slug"]: g for g in default_guides}
                for g_slug, g_val in custom_data.items():
                    if g_val is None:
                        guides_dict.pop(g_slug, None)
                    elif isinstance(g_val, dict):
                        guides_dict[g_slug] = g_val
                return list(guides_dict.values())
    except Exception as e:
        logger.error(f"Error loading troubleshooting guides: {e}")
    return default_guides


def get_troubleshooting_guide(slug: str) -> Optional[Dict[str, Any]]:
    """دریافت راهکار عیب‌یابی یک خطای خاص"""
    if not slug:
        return None
    guides = get_troubleshooting_guides()
    return next((g for g in guides if g.get("slug") == slug), None)


def save_troubleshooting_guide(slug: str, data: Dict[str, Any]) -> bool:
    """ذخیره یا ویرایش یک راهکار خطای اتصال در دیتابیس"""
    if not slug or not isinstance(data, dict):
        return False
    slug_key = slug.strip().lower()
    try:
        current_guides = get_troubleshooting_guides()
        data["slug"] = slug_key

        existing_index = next((i for i, g in enumerate(current_guides) if g.get("slug") == slug_key), None)
        if existing_index is not None:
            current_guides[existing_index] = data
        else:
            current_guides.append(data)

        db.save_setting(SETTING_KEY_CUSTOM_GUIDES, json.dumps(current_guides, ensure_ascii=False))
        return True
    except Exception as e:
        logger.error(f"Error saving troubleshooting guide {slug}: {e}")
        return False


def delete_troubleshooting_guide(slug: str) -> bool:
    """حذف یک راهکار خطای اتصال"""
    if not slug:
        return False
    slug_key = slug.strip().lower()
    try:
        current_guides = get_troubleshooting_guides()
        filtered = [g for g in current_guides if g.get("slug") != slug_key]
        db.save_setting(SETTING_KEY_CUSTOM_GUIDES, json.dumps(filtered, ensure_ascii=False))
        return True
    except Exception as e:
        logger.error(f"Error deleting troubleshooting guide {slug}: {e}")
        return False


def get_step_by_step_troubleshoot() -> Dict[str, Any]:
    """دریافت ساختار ویزارد گام‌به‌گام حل مشکلات اتصال"""
    wizard = copy.deepcopy(DEFAULT_STEP_BY_STEP_TROUBLESHOOT)
    try:
        custom_raw = db.get_setting(SETTING_KEY_CUSTOM_STEP_TROUBLESHOOT)
        if custom_raw:
            custom_data = json.loads(custom_raw) if isinstance(custom_raw, str) else custom_raw
            if isinstance(custom_data, dict):
                wizard.update(custom_data)
    except Exception as e:
        logger.error(f"Error loading custom step-by-step troubleshoot: {e}")
    return wizard


def save_step_by_step_troubleshoot(wizard_data: Dict[str, Any]) -> bool:
    """ذخیره ساختار شخصی‌سازی‌شده ویزارد گام‌به‌گام عیب‌یابی"""
    try:
        db.save_setting(SETTING_KEY_CUSTOM_STEP_TROUBLESHOOT, json.dumps(wizard_data, ensure_ascii=False))
        return True
    except Exception as e:
        logger.error(f"Error saving step-by-step troubleshoot: {e}")
        return False


def get_step_by_step_connection() -> Dict[str, Any]:
    """دریافت ساختار ویزارد گام‌به‌گام راهنمای اتصال"""
    wizard = copy.deepcopy(DEFAULT_STEP_BY_STEP_CONNECTION)
    try:
        custom_raw = db.get_setting(SETTING_KEY_CUSTOM_STEP_CONNECTION)
        if custom_raw:
            custom_data = json.loads(custom_raw) if isinstance(custom_raw, str) else custom_raw
            if isinstance(custom_data, dict):
                wizard.update(custom_data)
    except Exception as e:
        logger.error(f"Error loading custom step-by-step connection: {e}")
    return wizard


def save_step_by_step_connection(wizard_data: Dict[str, Any]) -> bool:
    """ذخیره ساختار شخصی‌سازی‌شده ویزارد گام‌به‌گام اتصال"""
    try:
        db.save_setting(SETTING_KEY_CUSTOM_STEP_CONNECTION, json.dumps(wizard_data, ensure_ascii=False))
        return True
    except Exception as e:
        logger.error(f"Error saving step-by-step connection: {e}")
        return False


def reset_to_defaults(section: Optional[str] = None) -> bool:
    """
    بازنشانی تنظیمات به پیش‌فرض کارخانه (Reset to Factory Defaults)
    section: 'tutorials', 'guides', 'wizard_troubleshoot', 'wizard_connection', یا None برای کل آموزش‌ها
    """
    try:
        if not section or section == "tutorials":
            db.save_setting(SETTING_KEY_CUSTOM_TUTORIALS, "")
            db.save_setting(SETTING_KEY_CUSTOM_PLATFORMS, "")
        if not section or section == "guides":
            db.save_setting(SETTING_KEY_CUSTOM_GUIDES, "")
        if not section or section == "wizard_troubleshoot":
            db.save_setting(SETTING_KEY_CUSTOM_STEP_TROUBLESHOOT, "")
        if not section or section == "wizard_connection":
            db.save_setting(SETTING_KEY_CUSTOM_STEP_CONNECTION, "")
        return True
    except Exception as e:
        logger.error(f"Error resetting tutorials to defaults: {e}")
        return False
