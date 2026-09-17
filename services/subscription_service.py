#!/usr/bin/env python3
"""
Subscription Service - سرویس مدیریت و محاسبات اشتراک‌های کاربران
فراهم‌آورنده منطق تجاری متمرکز، پردازش سریع و قالب‌بندی اطلاعات اشتراک
"""

from typing import Dict, Any, Optional, List
from utils import gregorian_to_shamsi, days_remaining_shamsi


class SubscriptionService:
    """سرویس پردازش و محاسبات وضعیت اشتراک"""

    @staticmethod
    def generate_progress_bar(used: float, total: float, length: int = 10) -> str:
        """تولید نوار پیشرفت گرافیکی مصرف ترافیک (Progress Bar)"""
        if total <= 0:
            return "🟩" * length
        ratio = min(max(used / total, 0.0), 1.0)
        filled = int(round(ratio * length))
        empty = length - filled
        if ratio >= 0.9:
            return "🟥" * filled + "⬜" * empty
        elif ratio >= 0.7:
            return "🟨" * filled + "⬜" * empty
        else:
            return "🟩" * filled + "⬜" * empty

    @classmethod
    def calculate_metrics(cls, sub: Dict[str, Any]) -> Dict[str, Any]:
        """محاسبه کامل متریک‌های مصرف و زمان باقی‌مانده اشتراک"""
        used_gb = round(float(sub.get("data_used", 0) or 0), 2)
        total_gb = round(float(sub.get("data_limit", 0) or 0), 2)
        remaining_gb = max(round(total_gb - used_gb, 2), 0.0) if total_gb > 0 else 0.0

        usage_percent = round((used_gb / total_gb * 100), 1) if total_gb > 0 else 0.0
        usage_percent = min(usage_percent, 100.0)

        exp_date_str = sub.get("expire_date") or ""
        days_left = 0
        is_time_expired = False
        shamsi_date = "نامشخص"

        if exp_date_str:
            try:
                shamsi_date = gregorian_to_shamsi(exp_date_str)
                days_left = days_remaining_shamsi(exp_date_str)
                is_time_expired = days_left <= 0
            except Exception:
                pass

        is_traffic_exhausted = (total_gb > 0 and used_gb >= total_gb)
        status = sub.get("status", "active")
        is_active = (status == "active" and not is_time_expired and not is_traffic_exhausted)

        return {
            "used_gb": used_gb,
            "total_gb": total_gb,
            "remaining_gb": remaining_gb,
            "usage_percent": usage_percent,
            "progress_bar": cls.generate_progress_bar(used_gb, total_gb),
            "expire_date_shamsi": shamsi_date,
            "days_left": max(days_left, 0),
            "is_time_expired": is_time_expired,
            "is_traffic_exhausted": is_traffic_exhausted,
            "is_active": is_active,
            "status_badge": "🟢 فعال" if is_active else ("🔴 منقضی" if is_time_expired else ("🟡 اتمام حجم" if is_traffic_exhausted else "⚪ غیرفعال"))
        }

    @classmethod
    def format_subscription_card(cls, sub: Dict[str, Any], brand_name: str = "سرویس اتصال") -> str:
        """قالب‌بندی کارت متنی زیبا و مرتب اطلاعات اشتراک جهت نمایش در تلگرام"""
        m = cls.calculate_metrics(sub)
        account_name = sub.get("account_name") or f"sub_{sub.get('id', '')}"
        plan_name = sub.get("plan_name") or "اشتراک اختصاصی"

        lines = [
            f"👤 **نام کاربری:** `{account_name}`",
            f"📦 **پلن:** {plan_name}",
            f"📊 **وضعیت:** {m['status_badge']}",
            "━━━━━━━━━━━━━━━━━━━",
            f"📉 **مصرف:** {m['used_gb']} از {m['total_gb']} GB ({m['usage_percent']}%)",
            f"📈 **باقی‌مانده:** {m['remaining_gb']} GB",
            f"⏳ **پیشرفت:** {m['progress_bar']}",
            "━━━━━━━━━━━━━━━━━━━",
            f"📅 **انقضا:** {m['expire_date_shamsi']}",
            f"⏳ **اعتبار باقی‌مانده:** {m['days_left']} روز"
        ]
        return "\n".join(lines)
