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


def get_miniapp_url(reseller_id: int = 0, user_id: Optional[int] = None) -> str:
    """
    تولید آدرس معتبر HTTPS برای مینی‌اپ تلگرام با تفکیک نماینده و کاربر.
    تلگرام صرفاً آدرس‌های دارای پروتکل امن https:// را برای MenuButtonWebApp می‌پذیرد.
    """
    custom_override = db.get_setting("mini_app_custom_url")
    if custom_override and str(custom_override).strip():
        base_url = str(custom_override).strip()
    else:
        domain = None
        if reseller_id and reseller_id > 0:
            r_info = db.get_reseller(reseller_id) or {}
            domain = r_info.get("custom_domain")

        if not domain:
            domain = db.get_setting("custom_domain") or os.getenv("PANEL_DOMAIN", "")

        if not domain or not str(domain).strip() or "localhost" in str(domain).lower():
            tut_d = db.get_setting("tutorial_domain") or ""
            if "gotel.ir" in tut_d:
                domain = "pay.gotel.ir"
            else:
                domain = "pay.gotel.ir"

        domain_str = str(domain).strip()
        if not domain_str.startswith("http://") and not domain_str.startswith("https://"):
            base_url = f"https://{domain_str.rstrip('/')}/webapp"
        elif domain_str.startswith("http://"):
            base_url = f"https://{domain_str[7:].rstrip('/')}/webapp"
        else:
            base_url = f"{domain_str.rstrip('/')}/webapp"

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
    chat_id: Optional[int] = None
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
            target_url = get_miniapp_url()
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
                "type": "commands"
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


def sync_all_bots_menu_button() -> Dict[str, Any]:
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
        main_url = get_miniapp_url(reseller_id=0)
        ok, msg = sync_telegram_menu_button_via_api(
            token=main_token,
            target_url=main_url,
            btn_text=btn_text,
            enabled=enabled
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
            r_url = get_miniapp_url(reseller_id=r_id)
            r_ok, r_msg = sync_telegram_menu_button_via_api(
                token=r_token,
                target_url=r_url,
                btn_text=btn_text,
                enabled=enabled
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
