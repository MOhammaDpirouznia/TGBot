"""
ماژول اختصاصی مدیریت دکمه ثابت مینی‌اپ تلگرام (Chat Menu Button / MenuButtonWebApp)
و همگام‌سازی بلادرنگ برای ربات اصلی و ربات‌های نمایندگان
"""

import os
import json
import logging
import urllib.request
import urllib.error
from typing import Tuple, Dict, Any, Optional
from dotenv import load_dotenv
load_dotenv()

from database import db

logger = logging.getLogger(__name__)


def get_miniapp_base_url(reseller_id: int = 0, host_url: Optional[str] = None) -> str:
    """
    دریافت آدرس پایه HTTPS مینی‌اپ با اولویت‌بندی هوشمند و معتبر.
    تلگرام صرفاً آدرس‌های دارای پروتکل امن https:// را برای MenuButtonWebApp می‌پذیرد.
    """
    def _clean_https(raw: Optional[str]) -> Optional[str]:
        if not raw or not str(raw).strip():
            return None
        val = str(raw).strip().rstrip('/')
        # فیلتر دامنه‌های نامعتبر، لوکال یا تستی قدیمی
        val_lower = val.lower()
        if "pay.gotel.ir" in val_lower or "gotel.ir" in val_lower:
            return None
        if "localhost" in val_lower or "127.0.0.1" in val:
            return None
        if val.startswith("http://"):
            return "https://" + val[7:]
        elif not val.startswith("https://"):
            return "https://" + val
        return val

    # ۱. بررسی دامنه اختصاصی نماینده در صورت وجود
    if reseller_id and int(reseller_id) > 0:
        try:
            r_info = db.get_reseller(int(reseller_id)) or {}
            r_domain = _clean_https(r_info.get("custom_domain"))
            if r_domain:
                return r_domain
        except Exception:
            pass

    # ۲. آدرس سفارشی وب‌اپ ذخیره شده در تنظیمات پنل ادمین (mini_app_custom_url)
    custom_override = _clean_https(db.get_setting("mini_app_custom_url"))
    if custom_override:
        return custom_override

    # ۳. تنظیم صریح webapp_url در دیتابیس
    db_webapp = _clean_https(db.get_setting("webapp_url"))
    if db_webapp:
        return db_webapp

    # ۴. متغیر محیطی DASHBOARD_URL
    env_dash = _clean_https(os.getenv("DASHBOARD_URL"))
    if env_dash:
        return env_dash

    # ۵. متغیر محیطی سرور ریلوِی (RAILWAY_PUBLIC_DOMAIN)
    railway_domain = os.getenv("RAILWAY_PUBLIC_DOMAIN", "").strip()
    if railway_domain:
        r_clean = _clean_https(railway_domain)
        if r_clean:
            return r_clean

    # ۶. متغیر محیطی رندر یا PaaS دیگر (RENDER_EXTERNAL_URL)
    env_render = _clean_https(os.getenv("RENDER_EXTERNAL_URL"))
    if env_render:
        return env_render

    # ۷. دامنه custom_domain یا متغیر محیطی PANEL_DOMAIN
    db_custom_domain = _clean_https(db.get_setting("custom_domain"))
    if db_custom_domain:
        return db_custom_domain

    env_panel_domain = _clean_https(os.getenv("PANEL_DOMAIN"))
    if env_panel_domain:
        return env_panel_domain

    # ۸. هاست ریکوئست ورودی در صورت فراخوانی از محیط وب
    if host_url:
        req_clean = _clean_https(host_url)
        if req_clean:
            return req_clean

    return ""


def get_miniapp_url(reseller_id: int = 0, user_id: Optional[int] = None, host_url: Optional[str] = None) -> str:
    """
    تولید آدرس معتبر HTTPS برای مینی‌اپ تلگرام با تفکیک نماینده و کاربر.
    تلگرام صرفاً آدرس‌های دارای پروتکل امن https:// را برای MenuButtonWebApp می‌پذیرد.
    """
    base = get_miniapp_base_url(reseller_id=reseller_id, host_url=host_url)
    if not base:
        logger.warning(f"Could not determine valid HTTPS Mini App base URL (reseller_id={reseller_id})")
        return ""

    # حذف پسوندهای احتمالی و اطمینان از قرارگیری /webapp در مسیر
    base_clean = base.rstrip('/')
    if not base_clean.endswith("/webapp"):
        base_url = f"{base_clean}/webapp"
    else:
        base_url = base_clean

    sep = "&" if "?" in base_url else "?"
    query_parts = [f"r={reseller_id or 0}"]
    if user_id and int(user_id) > 0:
        query_parts.append(f"tg_id={int(user_id)}")

    return f"{base_url}{sep}{'&'.join(query_parts)}"


def get_miniapp_button_text() -> str:
    """دریافت متن روی دکمه ثابت مینی‌اپ در تلگرام"""
    return db.get_setting("mini_app_menu_button_text", "ورود به برنامه | HiddiPlus") or "ورود به برنامه | HiddiPlus"


def is_miniapp_menu_button_enabled() -> bool:
    """بررسی فعال بودن دکمه ثابت مینی‌اپ در تلگرام"""
    return db.get_setting("mini_app_menu_button_enabled", "1") != "0"


def sync_telegram_menu_button_via_api(
    token: str,
    target_url: Optional[str] = None,
    btn_text: Optional[str] = None,
    enabled: bool = True,
    chat_id: Optional[int] = None,
    host_url: Optional[str] = None
) -> Tuple[bool, str]:
    """
    تنظیم دکمه منوی چت (Chat Menu Button) مستقیماً از طریق فراخوانی HTTP تلگرام Bot API.
    این تابع سنکرون بوده و بدون نیاز به event loop در هر کجای فلسک یا تردها کار می‌کند.
    """
    if not token or not str(token).strip():
        return False, "توکن ربات تلگرام نامعتبر است."

    clean_token = str(token).strip()
    api_url = f"https://api.telegram.org/bot{clean_token}/setChatMenuButton"

    if enabled:
        if not target_url:
            target_url = get_miniapp_url(reseller_id=0, host_url=host_url)
        if not target_url:
            return False, "آدرس معتبر HTTPS برای مینی‌اپ یافت نشد. لطفاً در تنظیمات ربات، دامنه یا آدرس وب‌اپ را مشخص نمایید."

        if not btn_text:
            btn_text = get_miniapp_button_text()

        # تلگرام الزاماً HTTPS می‌خواهد
        if not target_url.startswith("https://"):
            if target_url.startswith("http://"):
                target_url = "https://" + target_url[7:]
            else:
                target_url = "https://" + target_url

        payload: Dict[str, Any] = {
            "menu_button": {
                "type": "web_app",
                "text": str(btn_text)[:64],
                "web_app": {
                    "url": target_url
                }
            }
        }
    else:
        payload = {
            "menu_button": {
                "type": "default"
            }
        }

    if chat_id:
        payload["chat_id"] = int(chat_id)

    try:
        req = urllib.request.Request(
            api_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("ok"):
                return True, "دکمه منوی مینی‌اپ با موفقیت در تلگرام تنظیم شد."
            return False, data.get("description", "خطای ناشناخته تلگرام")
    except urllib.error.HTTPError as he:
        try:
            err_body = he.read().decode("utf-8")
            err_json = json.loads(err_body)
            err_desc = err_json.get("description", err_body)
        except Exception:
            err_desc = str(he)
        logger.warning(f"Telegram setChatMenuButton HTTPError: {err_desc}")
        return False, f"خطای تلگرام: {err_desc}"
    except Exception as e:
        logger.warning(f"Telegram setChatMenuButton Exception: {e}")
        return False, f"خطا در ارتباط با سرور تلگرام: {str(e)}"


def sync_all_bots_menu_button(host_url: Optional[str] = None) -> Dict[str, Any]:
    """
    همگام‌سازی دکمه ثابت منوی مینی‌اپ برای ربات اصلی و تمامی ربات‌های فعال نمایندگان.
    """
    results = {
        "success": False,
        "main_bot": None,
        "resellers_count": 0,
        "resellers_synced": 0,
        "errors": []
    }

    enabled = is_miniapp_menu_button_enabled()
    btn_text = get_miniapp_button_text()

    # ۱. ربات اصلی مدیریت
    main_token = os.getenv("BOT_TOKEN") or db.get_setting("bot_token")
    if main_token:
        main_url = get_miniapp_url(reseller_id=0, host_url=host_url)
        ok, msg = sync_telegram_menu_button_via_api(
            token=main_token,
            target_url=main_url if enabled else None,
            btn_text=btn_text,
            enabled=enabled,
            host_url=host_url
        )
        results["main_bot"] = {"ok": ok, "message": msg, "url": main_url}
        if ok:
            results["success"] = True
        else:
            results["errors"].append(f"ربات اصلی: {msg}")
    else:
        results["errors"].append("توکن ربات اصلی یافت نشد.")

    # ۲. ربات‌های نمایندگان
    try:
        resellers = db.get_all_resellers() or []
        for r in resellers:
            r_id = r.get("id")
            r_token = r.get("bot_token")
            if not r_token or not r.get("is_active"):
                continue

            results["resellers_count"] += 1
            r_url = get_miniapp_url(reseller_id=r_id, host_url=host_url)
            r_ok, r_msg = sync_telegram_menu_button_via_api(
                token=r_token,
                target_url=r_url if enabled else None,
                btn_text=btn_text,
                enabled=enabled,
                host_url=host_url
            )
            if r_ok:
                results["resellers_synced"] += 1
            else:
                results["errors"].append(f"نماینده #{r_id} ({r.get('username')}): {r_msg}")
    except Exception as e_res:
        logger.error(f"Error syncing reseller bots menu buttons: {e_res}")
        results["errors"].append(f"خطا در همگام‌سازی نمایندگان: {str(e_res)}")

    return results


async def setup_telegram_chat_menu_button(
    bot,
    chat_id: Optional[int] = None,
    user_id: Optional[int] = None,
    reseller_id: int = 0
) -> bool:
    """
    تابع آسنکرون برای تنظیم دکمه MenuButtonWebApp در هندلرهای python-telegram-bot
    """
    try:
        from telegram import MenuButtonWebApp, MenuButtonDefault, WebAppInfo

        enabled = is_miniapp_menu_button_enabled()
        if not enabled:
            if chat_id:
                await bot.set_chat_menu_button(chat_id=chat_id, menu_button=MenuButtonDefault())
            else:
                await bot.set_chat_menu_button(menu_button=MenuButtonDefault())
            return True

        target_url = get_miniapp_url(reseller_id=reseller_id, user_id=user_id)
        if not target_url:
            logger.warning(f"Could not determine valid Mini App URL for menu button (user_id={user_id}, reseller={reseller_id})")
            return False

        btn_text = get_miniapp_button_text()

        menu_btn = MenuButtonWebApp(
            text=str(btn_text)[:64],
            web_app=WebAppInfo(url=target_url)
        )

        if chat_id:
            await bot.set_chat_menu_button(chat_id=chat_id, menu_button=menu_btn)
        else:
            await bot.set_chat_menu_button(menu_button=menu_btn)

        return True
    except Exception as e:
        logger.warning(f"setup_telegram_chat_menu_button failed: {e}")
        return False
