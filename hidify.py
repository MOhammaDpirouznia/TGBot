#!/usr/bin/env python3
"""
Hidify API Client - v2 API (Async)
"""

import httpx
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class HidifyClient:
    """کلاینت اتصال به پنل Hidify v2 (async)"""

    def __init__(self, panel_url: str, api_key: str, proxy_path: str):
        self.panel_url = panel_url.rstrip("/")
        self.api_key = api_key
        self.proxy_path = proxy_path.strip("/")
        self.base_api = f"{self.panel_url}/{self.proxy_path}/api/v2"
        self.headers = {
            "Hiddify-API-Key": api_key,
            "Content-Type": "application/json",
        }
        self._client = None

    async def _get_client(self) -> httpx.AsyncClient:
        """دریافت یا ساخت کلاینت async"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                verify=False,
                follow_redirects=True,
                timeout=httpx.Timeout(15.0)
            )
        return self._client

    async def _request(self, method: str, endpoint: str, data: dict = None) -> dict:
        """ارسال درخواست به API (async)"""
        url = f"{self.base_api}{endpoint}"
        try:
            client = await self._get_client()
            
            if method == "GET":
                response = await client.get(url, headers=self.headers, params=data)
            elif method == "POST":
                response = await client.post(url, headers=self.headers, json=data)
            elif method == "PUT":
                response = await client.put(url, headers=self.headers, json=data)
            elif method == "PATCH":
                response = await client.patch(url, headers=self.headers, json=data)
            elif method == "DELETE":
                response = await client.delete(url, headers=self.headers)
            else:
                return {"error": "Invalid method"}

            logger.info(f"Hidify API: {method} {url} -> {response.status_code}")
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            error_msg = f"HTTP {e.response.status_code}: {e.response.text[:200]}"
            logger.error(f"Hidify API error: {error_msg}")
            return {"error": error_msg}
        except httpx.TimeoutException:
            error_msg = "Timeout: درخواست بیش از حد طول کشید"
            logger.error(f"Hidify timeout: {url}")
            return {"error": error_msg}
        except httpx.ConnectError as e:
            error_msg = f"Connection error: {e}"
            logger.error(f"Hidify connection error: {error_msg}")
            return {"error": error_msg}
        except Exception as e:
            error_msg = f"{type(e).__name__}: {e}"
            logger.error(f"Hidify error: {error_msg}")
            return {"error": error_msg}

    async def close(self):
        """بستن کلاینت"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    # ─── User Management ───

    async def get_users(self) -> list:
        """دریافت لیست کاربران"""
        return await self._request("GET", "/admin/user/")

    async def get_user(self, uuid: str) -> dict:
        """دریافت اطلاعات یک کاربر"""
        return await self._request("GET", f"/admin/user/{uuid}/")

    async def create_user(self, name: str, usage_limit_gb: float = None,
                    package_days: int = None, enable: bool = True,
                    comment: str = None) -> dict:
        """ساخت کاربر جدید"""
        payload = {
            "name": name,
            "enable": enable,
            "is_active": True,
        }
        if usage_limit_gb is not None:
            payload["usage_limit_GB"] = usage_limit_gb
        if package_days is not None:
            payload["package_days"] = package_days
        if comment is not None:
            payload["comment"] = comment
        return await self._request("POST", "/admin/user/", payload)

    async def update_user(self, uuid: str, **kwargs) -> dict:
        """بروزرسانی اطلاعات کاربر با قابلیت بازیابی در صورت خطای اسکیما"""
        res = await self._request("PATCH", f"/admin/user/{uuid}/", kwargs)
        if "error" not in res:
            return res

        logger.warning(f"PATCH user {uuid} failed ({res.get('error')}), trying fallback update...")
        try:
            existing = await self.get_user(uuid)
            if isinstance(existing, dict) and "error" not in existing and existing.get("name"):
                payload = dict(existing)
                payload.update(kwargs)
                res_put = await self._request("PUT", f"/admin/user/{uuid}/", payload)
                if "error" not in res_put:
                    return res_put
                res_patch = await self._request("PATCH", f"/admin/user/{uuid}/", payload)
                if "error" not in res_patch:
                    return res_patch
        except Exception as e:
            logger.error(f"Fallback update error for {uuid}: {e}")
        return res


    async def renew_user(self, uuid: str, new_limit_gb: float, new_duration_days: int) -> dict:
        """
        تمدید هوشمند اشتراک در هیدیفای:
        حالت اول: اتمام زمان یا حجم -> جایگزینی حجم و روز + ریست حجم مصرفی و ریست زمان شروع
        حالت دوم: باقی‌ماندن حجم و زمان -> اضافه کردن حجم و روز به مقادیر قبلی
        """
        try:
            user_info = await self.get_user(uuid)
            if not user_info or "error" in user_info or not isinstance(user_info, dict):
                return await self.update_user(
                    uuid,
                    usage_limit_GB=new_limit_gb,
                    package_days=new_duration_days,
                    current_usage_GB=0,
                    start_date=None,
                    enable=True,
                    is_active=True
                )

            current_usage = float(user_info.get("current_usage_GB") or 0)
            curr_limit = float(user_info.get("usage_limit_GB") or 0)
            curr_days = int(user_info.get("package_days") or 0)
            is_active = user_info.get("is_active", True)
            enable = user_info.get("enable", True)

            is_traffic_finished = (curr_limit > 0 and current_usage >= curr_limit)
            is_expired = (not is_active or not enable or is_traffic_finished)

            if is_expired:
                # حالت اول: جایگزینی و ریست کامل
                logger.info(f"Async Renew {uuid}: Expired -> Full Reset & Replace ({new_limit_gb} GB, {new_duration_days} days)")
                return await self.update_user(
                    uuid,
                    usage_limit_GB=new_limit_gb,
                    package_days=new_duration_days,
                    current_usage_GB=0,
                    start_date=None,
                    enable=True,
                    is_active=True
                )
            else:
                # حالت دوم: افزایش حجم و زمان
                combined_limit = (curr_limit + new_limit_gb) if curr_limit > 0 and new_limit_gb > 0 else (new_limit_gb if new_limit_gb > 0 else 0)
                combined_days = curr_days + new_duration_days
                logger.info(f"Async Renew {uuid}: Active -> Appended ({combined_limit} GB, {combined_days} days)")
                return await self.update_user(
                    uuid,
                    usage_limit_GB=combined_limit,
                    package_days=combined_days,
                    enable=True,
                    is_active=True
                )
        except Exception as e:
            logger.error(f"Error in async renew_user for {uuid}: {e}")
            return await self.update_user(uuid, usage_limit_GB=new_limit_gb, package_days=new_duration_days, enable=True, is_active=True)

    async def delete_user(self, uuid: str) -> dict:
        """حذف کاربر"""
        return await self._request("DELETE", f"/admin/user/{uuid}/")

    # ─── Admin / Reseller Sub-Account Management ───

    async def get_admins(self) -> list:
        """دریافت لیست ادمین‌ها و نمایندگان در هیدیفای"""
        return await self._request("GET", "/admin/admin_user/")

    async def get_admin(self, uuid: str) -> dict:
        """دریافت اطلاعات یک ادمین در هیدیفای"""
        return await self._request("GET", f"/admin/admin_user/{uuid}/")

    async def create_admin(self, name: str, mode: str = "agent", comment: str = None,
                           can_add_users: bool = True, max_users: int = None,
                           max_usage_limit_gb: float = None) -> dict:
        """ایجاد ادمین / نماینده جدید در هیدیفای"""
        payload = {
            "name": name,
            "mode": mode,
            "can_add_users": can_add_users,
            "is_active": True
        }
        if comment:
            payload["comment"] = str(comment)[:200]
        if max_users is not None and max_users > 0:
            payload["max_users"] = int(max_users)
        if max_usage_limit_gb is not None and max_usage_limit_gb > 0:
            payload["max_usage_limit_GB"] = float(max_usage_limit_gb)

        return await self._request("POST", "/admin/admin_user/", payload)

    async def update_admin(self, uuid: str, **kwargs) -> dict:
        """بروزرسانی ادمین در هیدیفای"""
        return await self._request("PATCH", f"/admin/admin_user/{uuid}/", kwargs)

    async def delete_admin(self, uuid: str) -> dict:
        """حذف ادمین از هیدیفای"""
        return await self._request("DELETE", f"/admin/admin_user/{uuid}/")

    # ─── Panel Info ───

    async def ping(self) -> dict:
        """تست اتصال"""
        return await self._request("GET", "/panel/ping/")

    async def get_panel_info(self) -> dict:
        """دریافت اطلاعات پنل"""
        return await self._request("GET", "/panel/info/")

    async def get_server_status(self) -> dict:
        """دریافت وضعیت سرور"""
        return await self._request("GET", "/admin/server_status/")
