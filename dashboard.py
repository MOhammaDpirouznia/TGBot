#!/usr/bin/env python3
"""
پنل مدیریت جامع تحت وب و سامانه اختصاصی نمایندگی (Reseller Portal)
"""

import os
import csv
import io
import json
import time
import urllib.request
import urllib.parse
import urllib.error
import functools
import logging
from datetime import datetime, timedelta
from pathlib import Path
from flask import (
    Flask, render_template, request, redirect, url_for, session,
    jsonify, flash, Response
)

from dotenv import load_dotenv
load_dotenv()

from database import db
from utils import generate_qr_code_bytes, get_now_iso, get_now_naive

logger = logging.getLogger(__name__)

# ─── تنظیمات Flask ───
app = Flask(__name__)
app.secret_key = os.getenv("DASHBOARD_SECRET", "hiddibot-super-secret-key-2026")


# ─── توابع داینامیک خواندن تنظیمات محیطی ───

def get_admin_username() -> str:
    return os.getenv("DASHBOARD_USERNAME", "admin")

def get_admin_password() -> str:
    return os.getenv("DASHBOARD_PASSWORD", "admin123")

def get_bot_token() -> str:
    return os.getenv("BOT_TOKEN", "")

def get_admin_id() -> int:
    return int(os.getenv("ADMIN_ID", 0))

def get_hiddify_url() -> str:
    return os.getenv("HIDIFY_PANEL_URL", "").rstrip("/")

def get_hiddify_key() -> str:
    return os.getenv("HIDIFY_API_KEY", "")

def get_hiddify_proxy() -> str:
    return os.getenv("HIDIFY_PROXY_PATH", "").strip("/")

def get_user_proxy() -> str:
    return os.getenv("USER_PROXY_PATH", "user").strip("/")


# ─── هلپرهای ارتباط همگام با تلگرام و هیدیفای (Sync Helpers) ───

def send_telegram_msg(chat_id: int, text: str, reply_markup=None, parse_mode: str = "HTML") -> bool:
    """ارسال پیام تلگرام به صورت همگام از پنل وب"""
    bot_token = get_bot_token()
    if not bot_token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as e:
        logger.error(f"Error sending telegram msg to {chat_id}: {e}")
        return False


def send_subscription_card_sync(chat_id: int, sub_url: str, title: str, details: str):
    """ارسال کارت اشتراک همراه با بارکد QR و دکمه‌های اتصال مستقیم از وب به کاربر"""
    bot_token = get_bot_token()
    clean_sub_url = sub_url.strip()
    qr_bytes = generate_qr_code_bytes(clean_sub_url)

    inline_keyboard = {
        "inline_keyboard": [
            [{"text": "🌐 صفحه کاربری و اتصال سریع", "url": clean_sub_url}],
            [{"text": "📋 راهنمای کپی لینک", "callback_data": "copy_link"}],
        ]
    }

    caption = (
        f"{title}\n\n"
        f"{details}\n\n"
        f"🔗 <b>لینک اتصال شما (برای کپی لمس کنید):</b>\n"
        f"<code>{clean_sub_url}</code>\n\n"
        f"💡 <b>راهنمای اتصال:</b>\n"
        f"1️⃣ کادر لینک بالا را لمس کنید تا کپی شود.\n"
        f"2️⃣ در اپلیکیشن (Hiddify / v2rayNG / Streisand) دکمه افزودن کانفیگ از کلیپ‌بورد را بزنید.\n"
        f"3️⃣ یا از دکمه «🌐 صفحه کاربری و اتصال سریع» استفاده نمایید."
    )

    if qr_bytes and bot_token:
        try:
            boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
            body = bytearray()
            # chat_id
            body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"chat_id\"\r\n\r\n{chat_id}\r\n".encode())
            # caption
            body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"caption\"\r\n\r\n{caption}\r\n".encode())
            # parse_mode
            body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"parse_mode\"\r\n\r\nHTML\r\n".encode())
            # reply_markup
            body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"reply_markup\"\r\n\r\n{json.dumps(inline_keyboard)}\r\n".encode())
            # photo file
            body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"photo\"; filename=\"qr.png\"\r\nContent-Type: image/png\r\n\r\n".encode())
            body.extend(qr_bytes)
            body.extend(f"\r\n--{boundary}--\r\n".encode())

            req = urllib.request.Request(
                f"https://api.telegram.org/bot{bot_token}/sendPhoto",
                data=bytes(body),
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}
            )
            with urllib.request.urlopen(req, timeout=12) as resp:
                if resp.status == 200:
                    return True
        except Exception as e:
            logger.error(f"Error sending photo card via sync web: {e}")

    # Fallback به ارسال متنی
    return send_telegram_msg(chat_id, caption, reply_markup=inline_keyboard)


def hidify_sync_request(method: str, endpoint: str, data: dict = None) -> dict:
    """درخواست همگام به API پنل هیدیفای"""
    panel_url = get_hiddify_url()
    api_key = get_hiddify_key()
    proxy_path = get_hiddify_proxy()

    if not panel_url or not api_key:
        return {"error": "اطلاعات پنل هیدیفای (HIDIFY_PANEL_URL / HIDIFY_API_KEY) تنظیم نشده است"}

    base_api = f"{panel_url}/{proxy_path}/api/v2"
    url = f"{base_api}{endpoint}"
    headers = {
        "Hiddify-API-Key": api_key,
        "User-Agent": "HiddiBot-Web/2.0"
    }
    req_data = None
    if data is not None:
        headers["Content-Type"] = "application/json"
        req_data = json.dumps(data).encode("utf-8")

    req = urllib.request.Request(url, data=req_data, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp_body = resp.read().decode("utf-8")
            return json.loads(resp_body) if resp_body else {}
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode("utf-8") if e.fp else str(e)
        logger.error(f"Hidify sync HTTP error {e.code}: {err_msg[:200]}")
        return {"error": f"HTTP {e.code}: {err_msg[:200]}"}
    except Exception as e:
        logger.error(f"Hidify sync request error: {e}")
        return {"error": str(e)}


def hidify_sync_create_user(name: str, usage_limit_gb: float = None, package_days: int = 30, comment: str = None) -> dict:
    """ساخت کاربر در هیدیفای"""
    payload = {
        "name": name,
        "enable": True,
        "is_active": True,
        "package_days": package_days,
        "mode": "no_reset",
    }
    if usage_limit_gb is not None and usage_limit_gb > 0:
        payload["usage_limit_GB"] = usage_limit_gb
    if comment:
        payload["comment"] = comment
    return hidify_sync_request("POST", "/admin/user/", payload)


def hidify_sync_update_user(uuid: str, **kwargs) -> dict:
    """بروزرسانی کاربر در هیدیفای"""
    res = hidify_sync_request("PATCH", f"/admin/user/{uuid}/", kwargs)
    if "error" in res:
        # Fallback به دریافت کاربر و ارسال کامل PUT
        user_obj = hidify_sync_request("GET", f"/admin/user/{uuid}/")
        if "error" not in user_obj:
            user_obj.update(kwargs)
            res = hidify_sync_request("PUT", f"/admin/user/{uuid}/", user_obj)
    return res


def hidify_sync_ping() -> dict:
    """تست اتصال و پینگ سرور هیدیفای"""
    panel_url = get_hiddify_url()
    if not panel_url:
        return {"online": False, "latency": 0, "error": "آدرس سرور تنظیم نشده"}
    start_t = time.time()
    try:
        res = hidify_sync_request("GET", "/admin/user/")
        latency = int((time.time() - start_t) * 1000)
        if "error" in res:
            return {"online": False, "latency": latency, "error": res["error"]}
        return {"online": True, "latency": latency, "users_count": len(res) if isinstance(res, list) else 0}
    except Exception as e:
        latency = int((time.time() - start_t) * 1000)
        return {"online": False, "latency": latency, "error": str(e)}


def get_plans_dict():
    """دریافت لیست پلن‌ها"""
    return {
        "1month_30gb": {"name": "۱ ماهه ۳۰ گیگ", "price": 100000, "data_limit": 30, "duration": 30},
        "1month_50gb": {"name": "۱ ماهه ۵۰ گیگ", "price": 150000, "data_limit": 50, "duration": 30},
        "1month_100gb": {"name": "۱ ماهه ۱۰۰ گیگ", "price": 250000, "data_limit": 100, "duration": 30},
        "3month_100gb": {"name": "۳ ماهه ۱۰۰ گیگ", "price": 300000, "data_limit": 100, "duration": 90},
        "3month_200gb": {"name": "۳ ماهه ۲۰۰ گیگ", "price": 500000, "data_limit": 200, "duration": 90},
    }


# ─── دکوریتورهای احراز هویت (Auth Decorators) ───

def login_required(f):
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function


def admin_required(f):
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("logged_in") or session.get("role") != "admin":
            flash("دسترسی به این صفحه فقط برای مدیر کل مجاز است.", "danger")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function


def reseller_required(f):
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("logged_in") or session.get("role") != "reseller":
            flash("دسترسی به این صفحه فقط برای نمایندگان مجاز است.", "danger")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function


# ─── مسیرهای احراز هویت (Authentication) ───

@app.route("/login", methods=["GET", "POST"])
def login():
    """صفحه ورود با پشتیبانی از دو نقش Admin و Reseller"""
    if session.get("logged_in"):
        if session.get("role") == "reseller":
            return redirect(url_for("reseller_dashboard"))
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        # ۱. بررسی ادمین اصلی
        if username == get_admin_username() and password == get_admin_password():
            session["logged_in"] = True
            session["role"] = "admin"
            session["username"] = username
            session["name"] = "مدیر کل"
            flash("خوش آمدید! ورود به عنوان مدیر کل انجام شد.", "success")
            return redirect(url_for("dashboard"))

        # ۲. بررسی نماینده فروش (Reseller)
        reseller = db.authenticate_reseller(username, password)
        if reseller:
            session["logged_in"] = True
            session["role"] = "reseller"
            session["reseller_id"] = reseller["id"]
            session["username"] = reseller["username"]
            session["name"] = reseller["name"]
            session["balance"] = reseller["balance"]
            flash(f"سلام {reseller['name']}! ورود به پنل نمایندگی با موفقیت انجام شد.", "success")
            return redirect(url_for("reseller_dashboard"))

        flash("نام کاربری یا رمز عبور اشتباه است!", "danger")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("با موفقیت از سیستم خارج شدید.", "info")
    return redirect(url_for("login"))


# ═══════════════════════════════════════════════════════════════════════
# مسیرهای داشبورد مدیر کل (Super Admin Routes)
# ═══════════════════════════════════════════════════════════════════════

@app.route("/")
@admin_required
def dashboard():
    """داشبورد اصلی مدیر کل"""
    conn = db.get_connection()

    total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    total_subscriptions = conn.execute("SELECT COUNT(*) FROM subscriptions").fetchone()[0]
    active_subscriptions = conn.execute("SELECT COUNT(*) FROM subscriptions WHERE status='active'").fetchone()[0]
    total_revenue = conn.execute("SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE status='approved'").fetchone()[0]
    pending_payments = conn.execute("SELECT COUNT(*) FROM transactions WHERE status='pending'").fetchone()[0]
    open_tickets = conn.execute("SELECT COUNT(*) FROM support_tickets WHERE status='open'").fetchone()[0]
    total_resellers = conn.execute("SELECT COUNT(*) FROM resellers").fetchone()[0]

    recent_transactions = conn.execute("""
        SELECT * FROM transactions ORDER BY created_at DESC LIMIT 8
    """).fetchall()

    daily_revenue = conn.execute("""
        SELECT DATE(created_at) as date, SUM(amount) as total
        FROM transactions 
        WHERE status='approved' AND created_at >= DATE('now', '-7 days')
        GROUP BY DATE(created_at)
        ORDER BY date ASC
    """).fetchall()

    conn.close()

    server_health = hidify_sync_ping()

    return render_template(
        "dashboard.html",
        total_users=total_users,
        total_subscriptions=total_subscriptions,
        active_subscriptions=active_subscriptions,
        total_revenue=total_revenue,
        pending_payments=pending_payments,
        open_tickets=open_tickets,
        total_resellers=total_resellers,
        recent_transactions=recent_transactions,
        daily_revenue=daily_revenue,
        server_health=server_health
    )


@app.route("/users")
@admin_required
def users():
    """مدیریت کاربران تلگرام"""
    conn = db.get_connection()
    search = request.args.get("search", "").strip()

    if search:
        user_list = conn.execute("""
            SELECT u.*, 
                   (SELECT COUNT(*) FROM subscriptions WHERE telegram_id=u.telegram_id) as subs_count
            FROM users u
            WHERE u.username LIKE ? OR u.telegram_id LIKE ?
            ORDER BY u.created_at DESC
        """, (f"%{search}%", f"%{search}%")).fetchall()
    else:
        user_list = conn.execute("""
            SELECT u.*, 
                   (SELECT COUNT(*) FROM subscriptions WHERE telegram_id=u.telegram_id) as subs_count
            FROM users u
            ORDER BY u.created_at DESC LIMIT 100
        """).fetchall()

    conn.close()
    return render_template("users.html", users=user_list, search=search)


@app.route("/user/<int:telegram_id>")
@admin_required
def user_detail(telegram_id):
    """جزئیات کاربر ۳۶۰ درجه"""
    conn = db.get_connection()
    user = conn.execute("SELECT * FROM users WHERE telegram_id=?", (telegram_id,)).fetchone()
    subscriptions = conn.execute("SELECT * FROM subscriptions WHERE telegram_id=? ORDER BY created_at DESC", (telegram_id,)).fetchall()
    transactions = conn.execute("SELECT * FROM transactions WHERE user_id=? ORDER BY created_at DESC", (telegram_id,)).fetchall()
    tickets = conn.execute("SELECT * FROM support_tickets WHERE telegram_id=? ORDER BY created_at DESC", (telegram_id,)).fetchall()
    conn.close()
    return render_template("user_detail.html", user=user, subscriptions=subscriptions, transactions=transactions, tickets=tickets)


@app.route("/payments")
@admin_required
def payments():
    """کارتابل مدیریت و تایید فیش‌های پرداخت"""
    conn = db.get_connection()
    status_filter = request.args.get("status", "all")
    search = request.args.get("search", "").strip()

    query = "SELECT * FROM transactions WHERE 1=1"
    params = []

    if status_filter != "all":
        query += " AND status=?"
        params.append(status_filter)

    if search:
        query += " AND (tracking_code LIKE ? OR username LIKE ? OR user_id LIKE ? OR order_id LIKE ?)"
        params.extend([f"%{search}%", f"%{search}%", f"%{search}%", f"%{search}%"])

    query += " ORDER BY created_at DESC LIMIT 150"
    payment_list = conn.execute(query, params).fetchall()
    conn.close()

    return render_template("payments.html", payments=payment_list, status_filter=status_filter, search=search)


@app.route("/payment/approve/<int:payment_id>")
@admin_required
def approve_payment(payment_id):
    """تایید پرداخت در وب و صدور خودکار اکانت در هیدیفای + ارسال به تلگرام"""
    conn = db.get_connection()
    tx = conn.execute("SELECT * FROM transactions WHERE id=?", (payment_id,)).fetchone()
    conn.close()

    if not tx:
        flash("تراکنش یافت نشد.", "danger")
        return redirect(url_for("payments"))

    if tx["status"] == "approved":
        flash("این تراکنش قبلاً تایید شده است.", "warning")
        return redirect(url_for("payments"))

    user_id = tx["user_id"]
    is_renewal = bool(tx["is_renewal"])
    renew_sub_id = tx["renew_sub_id"]
    plan_name = tx["plan_name"]

    # یافتن مشخصات پلن
    plans = get_plans_dict()
    selected_plan = next((p for p in plans.values() if p["name"] == plan_name), None)
    data_limit = selected_plan["data_limit"] if selected_plan else 30
    duration = selected_plan["duration"] if selected_plan else 30

    account_name = tx["account_name"] or f"tg_{user_id}"
    user_uuid = ""

    if is_renewal and renew_sub_id:
        user_subs = db.get_user_subscriptions(user_id)
        target_sub = next((s for s in user_subs if s["id"] == renew_sub_id), None)
        if target_sub:
            user_uuid = target_sub.get("hidify_uuid", "")
            # بروزرسانی در هیدیفای
            hidify_sync_update_user(user_uuid, usage_limit_GB=data_limit, package_days=duration)
            db.update_subscription(renew_sub_id, plan_name=plan_name, data_limit=data_limit, duration=duration, status="active")
    else:
        # خرید جدید
        res = hidify_sync_create_user(name=account_name, usage_limit_gb=data_limit, package_days=duration, comment=str(user_id))
        user_uuid = res.get("uuid", "")
        if user_uuid:
            db.save_subscription(
                telegram_id=user_id,
                hidify_uuid=user_uuid,
                plan_id="custom",
                plan_name=plan_name,
                data_limit=data_limit,
                duration=duration,
                status="active",
                account_name=account_name
            )

    # بروزرسانی وضعیت تراکنش در دیتابیس
    conn = db.get_connection()
    conn.execute("UPDATE transactions SET status='approved', updated_at=? WHERE id=?", (get_now_iso(), payment_id))
    conn.commit()
    conn.close()

    # پاداش رفرال
    db.complete_referral(user_id)

    # ارسال کارت و بارکد به تلگرام مشتری
    h_url = get_hiddify_url()
    u_proxy = get_user_proxy()
    if user_uuid and h_url:
        sub_url = f"{h_url}/{u_proxy}/{user_uuid}/"
        card_title = "🎉 **اشتراک شما تایید و فعال شد!**" if not is_renewal else "🔄 **اشتراک شما با موفقیت تمدید شد!**"
        card_details = f"📋 پلن: **{plan_name}**\n📊 حجم: **{data_limit} گیگابایت**\n⏰ مدت: **{duration} روز**"
        send_subscription_card_sync(user_id, sub_url, card_title, card_details)

    flash(f"پرداخت #{payment_id} تایید شد و اشتراک در هیدیفای فعال گردید!", "success")
    return redirect(url_for("payments"))


@app.route("/payment/reject/<int:payment_id>", methods=["GET", "POST"])
@admin_required
def reject_payment(payment_id):
    """رد فیش پرداخت با ثبت دلیل و ارسال پیام به کاربر"""
    reason = request.form.get("reason") or request.args.get("reason") or "عدم تطابق فیش واریزی یا نامعتبر بودن رسید"
    conn = db.get_connection()
    tx = conn.execute("SELECT * FROM transactions WHERE id=?", (payment_id,)).fetchone()

    if tx:
        conn.execute("UPDATE transactions SET status='rejected', rejection_reason=?, updated_at=? WHERE id=?", (reason, get_now_iso(), payment_id))
        conn.commit()

        # ارسال پیام رد به تلگرام
        user_id = tx["user_id"]
        msg = f"❌ <b>پرداخت شما تایید نشد.</b>\n\n📝 <b>علت رد:</b> {reason}\n\nدر صورت وجود سوال، با بخش «💬 پشتیبانی» تماس بگیرید."
        send_telegram_msg(user_id, msg)

    conn.close()
    flash(f"پرداخت #{payment_id} رد شد و به کاربر اطلاع داده شد.", "warning")
    return redirect(url_for("payments"))


@app.route("/subscriptions")
@admin_required
def subscriptions():
    """لیست اشتراک‌های هیدیفای"""
    conn = db.get_connection()
    status_filter = request.args.get("status", "all")
    if status_filter == "all":
        sub_list = conn.execute("SELECT * FROM subscriptions ORDER BY created_at DESC LIMIT 150").fetchall()
    else:
        sub_list = conn.execute("SELECT * FROM subscriptions WHERE status=? ORDER BY created_at DESC LIMIT 150", (status_filter,)).fetchall()
    conn.close()
    return render_template("subscriptions.html", subscriptions=sub_list, status_filter=status_filter, panel_url=get_hiddify_url(), user_proxy=get_user_proxy())


# ═══════════════════════════════════════════════════════════════════════
# بخش مدیریت نمایندگان فروش (Resellers Management - Admin)
# ═══════════════════════════════════════════════════════════════════════

@app.route("/admin/resellers", methods=["GET", "POST"])
@admin_required
def admin_resellers():
    """صفحه مدیریت همکاران و نمایندگان فروش"""
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        name = request.form.get("name")
        telegram_id = int(request.form.get("telegram_id")) if request.form.get("telegram_id") else None
        discount_percent = int(request.form.get("discount_percent", 20))
        initial_balance = int(request.form.get("initial_balance", 0))

        res = db.create_reseller(username, password, name, telegram_id, discount_percent, initial_balance)
        if res.get("success"):
            flash(f"نماینده جدید «{name}» با موفقیت افزوده شد!", "success")
        else:
            flash(f"خطا در ایجاد نماینده: {res.get('error')}", "danger")
        return redirect(url_for("admin_resellers"))

    reseller_list = db.get_all_resellers()
    return render_template("resellers.html", resellers=reseller_list)


@app.route("/admin/reseller/<int:reseller_id>/add-balance", methods=["POST"])
@admin_required
def admin_reseller_add_balance(reseller_id):
    """افزایش اعتبار نماینده توسط ادمین"""
    amount = int(request.form.get("amount", 0))
    desc = request.form.get("description", "شارژ کیف پول توسط ادمین")
    if amount > 0:
        db.add_reseller_balance(reseller_id, amount, desc)
        flash(f"مبلغ {amount:,} تومان به کیف پول نماینده افزوده شد.", "success")
    return redirect(url_for("admin_resellers"))


@app.route("/admin/reseller/<int:reseller_id>/toggle")
@admin_required
def admin_reseller_toggle(reseller_id):
    """تغییر وضعیت فعال/غیرفعال نماینده"""
    r = db.get_reseller(reseller_id)
    if r:
        new_status = "suspended" if r["status"] == "active" else "active"
        db.update_reseller(reseller_id, status=new_status)
        flash(f"وضعیت نماینده به {new_status} تغییر یافت.", "info")
    return redirect(url_for("admin_resellers"))


# ═══════════════════════════════════════════════════════════════════════
# بخش پیام همگانی و برودکست (Targeted Broadcast Engine)
# ═══════════════════════════════════════════════════════════════════════

@app.route("/broadcast", methods=["GET", "POST"])
@admin_required
def broadcast():
    """ارسال پیام انبوه هدفمند به کاربران تلگرام"""
    if request.method == "POST":
        target_group = request.form.get("target_group", "all")
        message_text = request.form.get("message", "").strip()
        btn_text = request.form.get("btn_text", "").strip()
        btn_url = request.form.get("btn_url", "").strip()

        if not message_text:
            flash("متن پیام نمی‌تواند خالی باشد!", "danger")
            return redirect(url_for("broadcast"))

        user_ids = db.get_target_broadcast_users(target_group)
        if not user_ids:
            flash("هیچ کاربری در گروه هدف انتخاب شده یافت نشد.", "warning")
            return redirect(url_for("broadcast"))

        reply_markup = None
        if btn_text and btn_url:
            reply_markup = {"inline_keyboard": [[{"text": btn_text, "url": btn_url}]]}

        success_count = 0
        fail_count = 0
        for uid in user_ids:
            ok = send_telegram_msg(uid, message_text, reply_markup=reply_markup)
            if ok:
                success_count += 1
            else:
                fail_count += 1

        flash(f"پیام به {success_count} کاربر ارسال شد. (خطا: {fail_count})", "success")
        return redirect(url_for("broadcast"))

    return render_template("broadcast.html")


# ═══════════════════════════════════════════════════════════════════════
# بخش پشتیبانی و تیکتینگ تحت وب (Web Support Desk)
# ═══════════════════════════════════════════════════════════════════════

@app.route("/tickets")
@admin_required
def tickets():
    """لیست تیکت‌های پشتیبانی"""
    conn = db.get_connection()
    ticket_list = conn.execute("""
        SELECT t.*, u.username
        FROM support_tickets t
        LEFT JOIN users u ON t.telegram_id = u.telegram_id
        ORDER BY t.created_at DESC
    """).fetchall()
    conn.close()
    return render_template("tickets.html", tickets=ticket_list)


@app.route("/ticket/reply/<int:ticket_id>", methods=["POST"])
@admin_required
def ticket_reply(ticket_id):
    """ارسال پاسخ به تیکت از پنل وب مستقیم به تلگرام کاربر"""
    reply_text = request.form.get("reply", "").strip()
    if not reply_text:
        flash("متن پاسخ نمی‌تواند خالی باشد.", "danger")
        return redirect(url_for("tickets"))

    ticket = db.get_ticket(ticket_id)
    if ticket:
        db.reply_ticket(ticket_id, reply_text)
        user_id = ticket["telegram_id"]
        msg = f"🔔 <b>پاسخ پشتیبانی به تیکت #{ticket_id}:</b>\n\n{reply_text}\n\n──────────────\nدر صورت نیاز به پیام مجدد از دکمه «💬 پشتیبانی» استفاده فرمایید."
        send_telegram_msg(user_id, msg)
        flash(f"پاسخ به تیکت #{ticket_id} با موفقیت به تلگرام کاربر ارسال شد!", "success")

    return redirect(url_for("tickets"))


# ═══════════════════════════════════════════════════════════════════════
# مدیریت کارت‌های بانکی مقصد (Bank Card Rotator)
# ═══════════════════════════════════════════════════════════════════════

@app.route("/cards", methods=["GET", "POST"])
@admin_required
def cards():
    """مدیریت کارت‌های بانکی و سقف تراکنش"""
    if request.method == "POST":
        card_num = request.form.get("card_number")
        holder = request.form.get("card_holder")
        bank = request.form.get("bank_name")
        limit = int(request.form.get("daily_limit", 50000000))
        db.add_bank_card(card_num, holder, bank, limit)
        flash("کارت بانکی جدید افزوده شد.", "success")
        return redirect(url_for("cards"))

    cards_list = db.get_all_bank_cards()
    return render_template("cards.html", cards=cards_list)


@app.route("/card/toggle/<int:card_id>")
@admin_required
def card_toggle(card_id):
    """فعال/غیرفعال کردن کارت"""
    cards_list = db.get_all_bank_cards()
    target = next((c for c in cards_list if c["id"] == card_id), None)
    if target:
        db.toggle_bank_card(card_id, not bool(target["is_active"]))
    return redirect(url_for("cards"))


@app.route("/card/delete/<int:card_id>")
@admin_required
def card_delete(card_id):
    """حذف کارت"""
    db.delete_bank_card(card_id)
    flash("کارت بانکی حذف شد.", "info")
    return redirect(url_for("cards"))


# ═══════════════════════════════════════════════════════════════════════
# مانیتورینگ سلامت، لاگ‌ها و گزارشات مالی
# ═══════════════════════════════════════════════════════════════════════

@app.route("/reports")
@admin_required
def reports():
    """گزارشات آماری و هوش مالی"""
    conn = db.get_connection()
    total_revenue = conn.execute("SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE status='approved'").fetchone()[0]
    monthly_revenue = conn.execute("""
        SELECT strftime('%Y-%m', created_at) as month, SUM(amount) as total, COUNT(*) as count
        FROM transactions WHERE status='approved'
        GROUP BY strftime('%Y-%m', created_at) ORDER BY month DESC LIMIT 12
    """).fetchall()

    popular_plans = conn.execute("""
        SELECT plan_name, COUNT(*) as count, SUM(amount) as revenue
        FROM transactions WHERE status='approved'
        GROUP BY plan_name ORDER BY count DESC LIMIT 10
    """).fetchall()
    conn.close()

    return render_template("reports.html", total_revenue=total_revenue, monthly_revenue=monthly_revenue, popular_plans=popular_plans)


@app.route("/export/transactions")
@admin_required
def export_transactions():
    """خروجی CSV از تراکنش‌ها"""
    conn = db.get_connection()
    rows = conn.execute("SELECT id, order_id, user_id, username, plan_name, amount, gateway, tracking_code, status, created_at FROM transactions ORDER BY created_at DESC").fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Order ID", "User ID", "Username", "Plan", "Amount (Tomans)", "Gateway", "Tracking Code", "Status", "Date"])
    for r in rows:
        writer.writerow(list(r))

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=transactions_export.csv"}
    )


@app.route("/admin/logs")
@admin_required
def admin_logs():
    """مشاهده لاگ‌های زنده سرور"""
    health = hidify_sync_ping()
    return render_template("logs.html", health=health)


@app.route("/settings")
@admin_required
def settings():
    """تنظیمات کلی سیستم"""
    conn = db.get_connection()
    settings_list = conn.execute("SELECT * FROM settings").fetchall()
    conn.close()
    return render_template("settings.html", settings=settings_list)


# ═══════════════════════════════════════════════════════════════════════
# پنل اختصاصی نمایندگان و همکاران فروش (Reseller Portal Routes)
# ═══════════════════════════════════════════════════════════════════════

@app.route("/reseller/dashboard")
@reseller_required
def reseller_dashboard():
    """داشبورد اصلی نماینده فروش"""
    reseller_id = session.get("reseller_id")
    stats = db.get_reseller_stats(reseller_id)
    session["balance"] = stats["balance"]
    recent_transactions = db.get_reseller_transactions(reseller_id, limit=6)
    return render_template("reseller_dashboard.html", stats=stats, recent_transactions=recent_transactions)


@app.route("/reseller/create-user", methods=["GET", "POST"])
@reseller_required
def reseller_create_user():
    """ساخت آنی اشتراک مشتری توسط نماینده با کسر اعتبار عمده‌فروشی"""
    reseller_id = session.get("reseller_id")
    stats = db.get_reseller_stats(reseller_id)
    discount = stats["discount_percent"]
    plans = get_plans_dict()

    if request.method == "POST":
        plan_key = request.form.get("plan_id")
        account_name = request.form.get("account_name", "").strip()

        if plan_key not in plans:
            flash("پلن انتخابی نامعتبر است.", "danger")
            return redirect(url_for("reseller_create_user"))

        plan = plans[plan_key]
        original_price = plan["price"]
        discount_amount = int((original_price * discount) / 100)
        final_price = original_price - discount_amount

        if stats["balance"] < final_price:
            flash(f"اعتبار کیف پول شما کافی نیست! موجودی: {stats['balance']:,} تومان | مبلغ مورد نیاز: {final_price:,} تومان", "danger")
            return redirect(url_for("reseller_create_user"))

        if not account_name:
            account_name = f"res_{reseller_id}_{int(time.time()) % 10000}"

        # کسر از موجودی نماینده
        deduct_res = db.deduct_reseller_balance(reseller_id, final_price, plan["name"], account_name)
        if not deduct_res.get("success"):
            flash(deduct_res.get("error", "خطا در کسر اعتبار"), "danger")
            return redirect(url_for("reseller_create_user"))

        # ساخت کاربر در هیدیفای
        h_res = hidify_sync_create_user(
            name=account_name,
            usage_limit_gb=plan["data_limit"],
            package_days=plan["duration"],
            comment=f"Reseller #{reseller_id} ({session.get('name')})"
        )

        user_uuid = h_res.get("uuid", "")
        if not user_uuid:
            # برگشت اعتبار در صورت خطای هیدیفای
            db.add_reseller_balance(reseller_id, final_price, "برگشت اعتبار به دلیل خطای سرور هیدیفای")
            flash(f"خطا در ساخت اکانت روی سرور هیدیفای: {h_res.get('error', 'نامشخص')}", "danger")
            return redirect(url_for("reseller_create_user"))

        # ثبت اشتراک با شناسه نماینده
        conn = db.get_connection()
        conn.execute("""
            INSERT INTO subscriptions 
            (telegram_id, hidify_uuid, plan_id, plan_name, account_name, data_limit, duration, status, reseller_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)
        """, (
            0, user_uuid, plan_key, plan["name"], account_name,
            plan["data_limit"], plan["duration"], reseller_id, get_now_iso(), get_now_iso()
        ))
        conn.commit()
        conn.close()

        subscription_url = f"{get_hiddify_url()}/{get_user_proxy()}/{user_uuid}/"
        flash(f"اشتراک «{account_name}» با موفقیت ساخته شد و مبلغ {final_price:,} تومان از کیف پول شما کسر گردید.", "success")

        return render_template(
            "reseller_created_success.html",
            account_name=account_name,
            plan=plan,
            sub_url=subscription_url,
            final_price=final_price
        )

    return render_template("reseller_create_user.html", plans=plans, discount=discount, balance=stats["balance"])


@app.route("/reseller/users")
@reseller_required
def reseller_users():
    """لیست مشتریان نماینده"""
    reseller_id = session.get("reseller_id")
    subs = db.get_reseller_subscriptions(reseller_id)
    return render_template("reseller_users.html", subscriptions=subs, panel_url=get_hiddify_url(), user_proxy=get_user_proxy())


@app.route("/reseller/transactions")
@reseller_required
def reseller_transactions():
    """لیست تراکنش‌ها و شارژ کیف پول نماینده"""
    reseller_id = session.get("reseller_id")
    tx_list = db.get_reseller_transactions(reseller_id)
    stats = db.get_reseller_stats(reseller_id)
    return render_template("reseller_transactions.html", transactions=tx_list, stats=stats)


# ─── راه‌اندازی سرور وب ───

def run_dashboard(host="0.0.0.0", port=None, debug=False):
    if port is None:
        port = int(os.getenv("PORT", 5000))
    print(f"🌐 Modern Web Dashboard running at http://{host}:{port}")
    app.run(host=host, port=port, debug=debug, use_reloader=False)


def start_dashboard_thread():
    """اجرای داشبورد در thread جداگانه هنگام استارت بات"""
    import threading
    t = threading.Thread(target=run_dashboard, daemon=True)
    t.start()
    return t


if __name__ == "__main__":
    run_dashboard(debug=True)
