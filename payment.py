#!/usr/bin/env python3
"""
ماژول پرداخت - پشتیبانی از ZarinPal و IDPay
"""

import os
import httpx
import logging
import hashlib
import json
from datetime import datetime
from utils import get_now_timestamp, get_now_iso
from pathlib import Path

logger = logging.getLogger(__name__)

# مسیر ذخیره تراکنش‌ها
DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)
TRANSACTIONS_FILE = DATA_DIR / "transactions.json"


def load_transactions() -> dict:
    """بارگذاری تراکنش‌ها"""
    if TRANSACTIONS_FILE.exists():
        with open(TRANSACTIONS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_transactions(transactions: dict):
    """ذخیره تراکنش‌ها"""
    with open(TRANSACTIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(transactions, f, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════════════
# ZarinPal
# ═══════════════════════════════════════════════════════════════════════

class ZarinPal:
    """کلاینت درگاه پرداخت ZarinPal"""

    SANDBOX = "https://sandbox.zarinpal.com"
    PRODUCTION = "https://api.zarinpal.com"

    def __init__(self, merchant_id: str, sandbox: bool = True):
        self.merchant_id = merchant_id
        self.base_url = self.SANDBOX if sandbox else self.PRODUCTION
        self.verify_url = f"{self.base_url}/pg/v4/payment/verify.json"
        self.request_url = f"{self.base_url}/pg/v4/payment/request.json"

    def create_payment(self, amount: int, description: str, 
                       callback_url: str, email: str = None, 
                       mobile: str = None) -> dict:
        """
        ساخت درخواست پرداخت
        
        Args:
            amount: مبلغ به تومان
            description: توضیحات پرداخت
            callback_url: آدرس بازگشت
            email: ایمیل (اختیاری)
            mobile: شماره موبایل (اختیاری)
        
        Returns:
            dict: حاوی authority و URL پرداخت
        """
        payload = {
            "merchant_id": self.merchant_id,
            "amount": amount,
            "callback_url": callback_url,
            "description": description,
        }
        if email:
            payload["email"] = email
        if mobile:
            payload["mobile"] = mobile

        try:
            with httpx.Client(verify=False, timeout=10) as client:
                response = client.post(
                    self.request_url,
                    json=payload,
                    headers={"Content-Type": "application/json"}
                )
                result = response.json()
                
                if result.get("data", {}).get("code") == 100:
                    authority = result["data"]["authority"]
                    payment_url = f"{self.base_url}/pg/StartPay.php?Authority={authority}"
                    return {
                        "success": True,
                        "authority": authority,
                        "payment_url": payment_url,
                        "fee": result["data"].get("fee", 0),
                    }
                else:
                    error_code = result.get("errors", {}).get("code", "unknown")
                    return {
                        "success": False,
                        "error": f"Error code: {error_code}",
                    }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def verify_payment(self, authority: str, amount: int) -> dict:
        """
        تایید پرداخت
        
        Args:
            authority: کد authority از درخواست قبلی
            amount: مبلغ پرداخت شده
        
        Returns:
            dict: حاوی نتیجه تایید
        """
        payload = {
            "merchant_id": self.merchant_id,
            "amount": amount,
            "authority": authority,
        }

        try:
            with httpx.Client(verify=False, timeout=10) as client:
                response = client.post(
                    self.verify_url,
                    json=payload,
                    headers={"Content-Type": "application/json"}
                )
                result = response.json()

                if result.get("data", {}).get("code") in (100, 101):
                    return {
                        "success": True,
                        "ref_id": result["data"].get("ref_id"),
                        "card_pan": result["data"].get("card_pan"),
                        "fee": result["data"].get("fee", 0),
                    }
                else:
                    return {"success": False, "error": "Payment not verified"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_pay_url(self, authority: str) -> str:
        """ساخت آدرس پرداخت"""
        return f"{self.base_url}/pg/StartPay.php?Authority={authority}"


# ═══════════════════════════════════════════════════════════════════════
# IDPay
# ═══════════════════════════════════════════════════════════════════════

class IDPay:
    """کلاینت درگاه پرداخت IDPay"""

    SANDBOX = "https://sandbox.idpay.ir"
    PRODUCTION = "https://api.idpay.ir"

    def __init__(self, api_key: str, sandbox: bool = True):
        self.api_key = api_key
        self.base_url = self.SANDBOX if sandbox else self.PRODUCTION
        self.request_url = f"{self.base_url}/v1/payment/request"
        self.verify_url = f"{self.base_url}/v1/payment/verify"

    def create_payment(self, amount: int, name: str, phone: str = None,
                       mail: str = None, description: str = None,
                       callback_url: str = None, order_id: str = None) -> dict:
        """
        ساخت درخواست پرداخت
        
        Args:
            amount: مبلغ به تومان
            name: نام پرداخت‌کننده
            phone: شماره موبایل
            mail: ایمیل
            description: توضیحات
            callback_url: آدرس بازگشت
            order_id: شماره سفارش
        
        Returns:
            dict: حاوی ID پرداخت و URL
        """
        payload = {
            "amount": amount,
            "name": name,
        }
        if phone:
            payload["phone"] = phone
        if mail:
            payload["mail"] = mail
        if description:
            payload["desc"] = description
        if callback_url:
            payload["callback"] = callback_url
        if order_id:
            payload["order_id"] = str(order_id)

        headers = {
            "X-API-KEY": self.api_key,
            "Content-Type": "application/json",
        }

        try:
            with httpx.Client(verify=False, timeout=10) as client:
                response = client.post(
                    self.request_url,
                    json=payload,
                    headers=headers
                )
                result = response.json()

                if response.status_code == 201 and "id" in result:
                    payment_url = f"https://idpay.ir/p/ws-{result['id']}/pay"
                    return {
                        "success": True,
                        "payment_id": result["id"],
                        "payment_url": payment_url,
                        "link": result.get("link"),
                    }
                else:
                    error_msg = result.get("error_message", "Unknown error")
                    return {"success": False, "error": error_msg}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def verify_payment(self, payment_id: str, order_id: str = None) -> dict:
        """
        تایید پرداخت
        
        Args:
            payment_id: شناسه پرداخت
            order_id: شماره سفارش (اختیاری)
        
        Returns:
            dict: حاوی نتیجه تایید
        """
        payload = {
            "id": payment_id,
        }
        if order_id:
            payload["order_id"] = str(order_id)

        headers = {
            "X-API-KEY": self.api_key,
            "Content-Type": "application/json",
        }

        try:
            with httpx.Client(verify=False, timeout=10) as client:
                response = client.post(
                    self.verify_url,
                    json=payload,
                    headers=headers
                )
                result = response.json()

                if response.status_code == 200 and result.get("status") == 2:
                    return {
                        "success": True,
                        "payment_id": result.get("id"),
                        "track_id": result.get("track_id"),
                        "amount": result.get("amount"),
                        "card_no": result.get("card_no"),
                        "fee": result.get("fee"),
                    }
                else:
                    status = result.get("status", "unknown")
                    error_msg = result.get("error_message", f"Status: {status}")
                    return {"success": False, "error": error_msg}
        except Exception as e:
            return {"success": False, "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════
# Payment Manager
# ═══════════════════════════════════════════════════════════════════════

class PaymentManager:
    """مدیریت پرداخت‌ها"""

    def __init__(self, gateway: str = "zarinpal"):
        """
        Args:
            gateway: نوع درگاه (zarinpal یا idpay)
        """
        self.gateway = gateway

        if gateway == "zarinpal":
            merchant_id = os.getenv("ZARINPAL_MERCHANT_ID", "")
            sandbox = os.getenv("ZARINPAL_SANDBOX", "true").lower() == "true"
            self.client = ZarinPal(merchant_id, sandbox)
        elif gateway == "idpay":
            api_key = os.getenv("IDPAY_API_KEY", "")
            sandbox = os.getenv("IDPAY_SANDBOX", "true").lower() == "true"
            self.client = IDPay(api_key, sandbox)
        else:
            raise ValueError(f"Unknown gateway: {gateway}")

    def create_payment(self, amount: int, user_id: int, plan_name: str,
                       callback_url: str) -> dict:
        """
        ساخت درخواست پرداخت
        
        Args:
            amount: مبلغ به تومان
            user_id: شناسه کاربر تلگرام
            plan_name: نام پلن
            callback_url: آدرس بازگشت
        """
        description = f"خرید اشتراک {plan_name}"
        order_id = f"tg_{user_id}_{get_now_timestamp()}"

        if self.gateway == "zarinpal":
            result = self.client.create_payment(
                amount=amount,
                description=description,
                callback_url=callback_url,
            )
            if result["success"]:
                result["order_id"] = order_id
        elif self.gateway == "idpay":
            result = self.client.create_payment(
                amount=amount,
                name=f"user_{user_id}",
                description=description,
                callback_url=callback_url,
                order_id=order_id,
            )
        
        # ذخیره تراکنش
        if result.get("success"):
            transactions = load_transactions()
            transactions[order_id] = {
                "user_id": user_id,
                "plan_name": plan_name,
                "amount": amount,
                "gateway": self.gateway,
                "status": "pending",
                "created_at": get_now_iso(),
                "authority": result.get("authority") or result.get("payment_id"),
            }
            save_transactions(transactions)
            result["order_id"] = order_id

        return result

    def verify_payment(self, **kwargs) -> dict:
        """تایید پرداخت"""
        if self.gateway == "zarinpal":
            return self.client.verify_payment(
                authority=kwargs.get("authority"),
                amount=kwargs.get("amount"),
            )
        elif self.gateway == "idpay":
            return self.client.verify_payment(
                payment_id=kwargs.get("payment_id"),
                order_id=kwargs.get("order_id"),
            )

    def get_pay_url(self, result: dict) -> str:
        """دریافت آدرس پرداخت از نتیجه"""
        if self.gateway == "zarinpal":
            return result.get("payment_url", "")
        elif self.gateway == "idpay":
            return result.get("link") or result.get("payment_url", "")
        return ""


# ═══════════════════════════════════════════════════════════════════════
# درگاه پرداخت ارزی و کریپتو (Crypto / USDT / TON Payment Gateway)
# ═══════════════════════════════════════════════════════════════════════

class CryptoPaymentGateway:
    """درگاه پرداخت هوشمند ارزی و کریپتو (OxaPay / NOWPayments / ولت مستقیم TRC20/TON)"""

    DEFAULT_USDT_RATE = 90000  # هر تتر معادل 90 هزار تومان (قابل تغییر در پنل تنظیمات)

    @classmethod
    def get_usdt_rate(cls, db_instance=None) -> int:
        """دریافت نرخ تبدیل تومان به تتر از تنظیمات دیتابیس یا مقدار پیش‌فرض"""
        if db_instance and hasattr(db_instance, "get_setting"):
            try:
                rate_val = db_instance.get_setting("crypto_usdt_rate", None)
                if rate_val and str(rate_val).isdigit():
                    return int(rate_val)
            except Exception:
                pass
        env_rate = os.getenv("CRYPTO_USDT_RATE", "")
        if env_rate and env_rate.isdigit():
            return int(env_rate)
        return cls.DEFAULT_USDT_RATE

    @classmethod
    def get_crypto_config(cls, db_instance=None) -> dict:
        """دریافت تنظیمات درگاه کریپتو"""
        cfg = {
            "enabled": False,
            "provider": "oxapay",
            "api_key": "",
            "wallet_address": "",
            "usdt_rate": cls.get_usdt_rate(db_instance),
        }
        if db_instance and hasattr(db_instance, "get_setting"):
            try:
                db_en = db_instance.get_setting("crypto_enabled", None)
                if db_en is not None:
                    cfg["enabled"] = str(db_en).lower() in ("true", "1", "yes")
                    cfg["provider"] = str(db_instance.get_setting("crypto_provider", "oxapay")).lower()
                    cfg["api_key"] = str(db_instance.get_setting("crypto_api_key", ""))
                    cfg["wallet_address"] = str(db_instance.get_setting("crypto_wallet_address", ""))
                    return cfg
            except Exception:
                pass
        cfg["enabled"] = os.getenv("CRYPTO_ENABLED", "false").lower() in ("true", "1", "yes")
        cfg["provider"] = os.getenv("CRYPTO_PROVIDER", "oxapay").lower()
        cfg["api_key"] = os.getenv("CRYPTO_API_KEY", "")
        cfg["wallet_address"] = os.getenv("CRYPTO_WALLET_ADDRESS", "")
        return cfg

    @classmethod
    def toman_to_usdt(cls, amount_toman: int, db_instance=None) -> float:
        """محاسبه معادل تتر مبلغ تومان با ۲ رقم اعشار"""
        rate = cls.get_usdt_rate(db_instance)
        if rate <= 0:
            rate = cls.DEFAULT_USDT_RATE
        return round(float(amount_toman) / float(rate), 2)

    @classmethod
    def create_payment(cls, amount_toman: int, user_id: int, plan_name: str, callback_url: str = None, db_instance=None) -> dict:
        """
        ایجاد فاکتور پرداخت کریپتو
        """
        cfg = cls.get_crypto_config(db_instance)
        usdt_amount = cls.toman_to_usdt(amount_toman, db_instance)
        order_id = f"crypto_{user_id}_{get_now_timestamp()}"

        provider = cfg.get("provider", "oxapay")
        api_key = cfg.get("api_key", "")

        # ۱. درگاه خودکار OxaPay
        if provider == "oxapay" and api_key:
            try:
                payload = {
                    "merchant": api_key,
                    "amount": usdt_amount,
                    "currency": "USDT",
                    "lifeTime": 60,
                    "feePaidByPayer": 1,
                    "underPaidCover": 2.5,
                    "callbackUrl": callback_url or "",
                    "description": f"خرید اشتراک {plan_name} توسط کاربر {user_id}",
                    "orderId": order_id
                }
                with httpx.Client(timeout=10) as client:
                    resp = client.post("https://api.oxapay.com/merchants/request", json=payload)
                    res_data = resp.json()
                    if res_data.get("result") == 100 or res_data.get("payLink"):
                        pay_url = res_data.get("payLink")
                        track_id = res_data.get("trackId")
                        return {
                            "success": True,
                            "order_id": order_id,
                            "track_id": track_id,
                            "payment_url": pay_url,
                            "usdt_amount": usdt_amount,
                            "provider": "oxapay"
                        }
                    else:
                        logger.warning(f"OxaPay error: {res_data.get('message')}")
            except Exception as e:
                logger.error(f"Error creating OxaPay payment: {e}")

        # ۲. درگاه خودکار NOWPayments
        elif provider == "nowpayments" and api_key:
            try:
                headers = {"x-api-key": api_key, "Content-Type": "application/json"}
                payload = {
                    "price_amount": usdt_amount,
                    "price_currency": "usd",
                    "pay_currency": "usdttrc20",
                    "ipn_callback_url": callback_url or "",
                    "order_id": order_id,
                    "order_description": f"اشتراک {plan_name}"
                }
                with httpx.Client(timeout=10) as client:
                    resp = client.post("https://api.nowpayments.io/v1/invoice", json=payload, headers=headers)
                    res_data = resp.json()
                    if res_data.get("invoice_url"):
                        return {
                            "success": True,
                            "order_id": order_id,
                            "payment_url": res_data["invoice_url"],
                            "usdt_amount": usdt_amount,
                            "provider": "nowpayments"
                        }
            except Exception as e:
                logger.error(f"Error creating NOWPayments payment: {e}")

        # ۳. درگاه مستقیم ولت (Direct Wallet Address)
        wallet = cfg.get("wallet_address") or "TLv4k5P... (Wallet Not Configured)"
        return {
            "success": True,
            "order_id": order_id,
            "usdt_amount": usdt_amount,
            "wallet_address": wallet,
            "network": "USDT (TRC20 / TON)",
            "provider": "direct_wallet",
            "is_manual": True
        }
