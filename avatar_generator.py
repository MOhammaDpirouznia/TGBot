"""
سرویس تولید خودکار و آفلاین آواتارهای سه‌بعدی و وکتور مدرن (Procedural SVG Avatar Generator)
بدون نیاز به اینترنت یا APIهای خارجی - سریع، پایدار و کاملاً باکیفیت
"""

import hashlib
import urllib.parse
from typing import Optional, List, Dict, Tuple


# پالت‌های رنگی گرادیان مدرن
GRADIENTS = [
    # (id, c1, c2, c3, name)
    ("grad_cyber", "#4f46e5", "#06b6d4", "#3b82f6", "Cyber Blue"),
    ("grad_neon", "#7928ca", "#ff0080", "#9333ea", "Neon Purple"),
    ("grad_sunset", "#f59e0b", "#ef4444", "#ec4899", "Sunset Amber"),
    ("grad_emerald", "#059669", "#10b981", "#34d399", "Emerald Mint"),
    ("grad_royal", "#1e1b4b", "#4338ca", "#6366f1", "Royal Indigo"),
    ("grad_dark", "#0f172a", "#1e293b", "#334155", "Midnight Slate"),
    ("grad_ruby", "#881337", "#e11d48", "#f43f5e", "Ruby Crimson"),
    ("grad_ocean", "#0c4a6e", "#0284c7", "#38bdf8", "Deep Ocean"),
    ("grad_gold", "#78350f", "#d97706", "#fbbf24", "Gold Amber"),
    ("grad_aurora", "#134e4a", "#0d9488", "#2dd4bf", "Aurora Teal"),
]

# تم‌های رباتیک و کاراکتری
PRESETS = [
    {"id": "cyber_bot", "name": "ربات سایبرپانک", "category": "robot"},
    {"id": "robot_neon", "name": "ربات نئونی هوشمند", "category": "robot"},
    {"id": "adventurer_boy", "name": "ماجراجوی جوان", "category": "human"},
    {"id": "adventurer_girl", "name": "ماجراجوی مدرن", "category": "human"},
    {"id": "cyber_ninja", "name": "نینجای تکنولوژی", "category": "hero"},
    {"id": "astronaut", "name": "فضانورد کیهانی", "category": "space"},
    {"id": "agent_pro", "name": "ایجنت حرفه‌ای", "category": "agent"},
    {"id": "wizard_mystic", "name": "حکیم کوانتومی", "category": "mystic"},
    {"id": "cyber_cat", "name": "گربه رباتیک", "category": "animal"},
    {"id": "cyber_fox", "name": "روباه هوشمند", "category": "animal"},
    {"id": "emoji_cool", "name": "کاراکتر عینک‌دودی", "category": "emoji"},
    {"id": "emoji_happy", "name": "کاراکتر شاد سه‌بعدی", "category": "emoji"},
]


def _hash_seed(seed: str) -> List[int]:
    """تبدیل رشته ورودی به مجموعه‌ای از اعداد شبه‌تصادفی قطعی"""
    clean = str(seed or "Customer").strip()
    md5_hex = hashlib.md5(clean.encode("utf-8")).hexdigest()
    # تولید ۱۰ عدد صحیح از روی تکه‌های هش
    nums = []
    for i in range(0, len(md5_hex), 3):
        chunk = md5_hex[i:i+3]
        if len(chunk) == 3:
            nums.append(int(chunk, 16))
    while len(nums) < 12:
        nums.append(sum(nums) % 1000 + 17)
    return nums


def generate_procedural_avatar_svg(seed: str, preset_id: Optional[str] = None) -> str:
    """
    تولید SVG فوق‌العاده مدرن، شکیل و سه‌بعدی به صورت محلی و ۱۰۰٪ آفلاین
    """
    nums = _hash_seed(seed)
    
    # تعیین پریست
    if not preset_id or preset_id not in [p["id"] for p in PRESETS]:
        preset_idx = nums[0] % len(PRESETS)
        preset_id = PRESETS[preset_idx]["id"]

    # انتخاب پالت رنگی
    grad_idx = nums[1] % len(GRADIENTS)
    g_id, c1, c2, c3, _ = GRADIENTS[grad_idx]

    # ابعاد استاندارد
    w, h = 120, 120

    # المان‌های داخلی بر اساس نوع پریست
    inner_svg = _render_preset_content(preset_id, nums, c1, c2, c3)

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}">
    <defs>
        <linearGradient id="bg_{g_id}_{nums[2]}" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stop-color="{c1}" />
            <stop offset="60%" stop-color="{c2}" />
            <stop offset="100%" stop-color="{c3}" />
        </linearGradient>
        <radialGradient id="specular_{nums[2]}" cx="35%" cy="30%" r="60%">
            <stop offset="0%" stop-color="#ffffff" stop-opacity="0.35" />
            <stop offset="100%" stop-color="#000000" stop-opacity="0.2" />
        </radialGradient>
        <filter id="glow_{nums[2]}" x="-20%" y="-20%" width="140%" height="140%">
            <feGaussianBlur stdDeviation="2" result="blur" />
            <feComposite in="SourceGraphic" in2="blur" operator="over" />
        </filter>
        <linearGradient id="metal_grad" x1="0%" y1="0%" x2="0%" y2="100%">
            <stop offset="0%" stop-color="#f8fafc" />
            <stop offset="50%" stop-color="#cbd5e1" />
            <stop offset="100%" stop-color="#64748b" />
        </linearGradient>
    </defs>
    
    <!-- پس‌زمینه دایره‌ای با سایه ملایم -->
    <circle cx="60" cy="60" r="58" fill="url(#bg_{g_id}_{nums[2]})" />
    <circle cx="60" cy="60" r="58" fill="url(#specular_{nums[2]})" />
    
    <!-- حلقه حاشیه مدرن نئونی -->
    <circle cx="60" cy="60" r="56" fill="none" stroke="#ffffff" stroke-width="1.5" stroke-opacity="0.25" />

    <!-- محتوای کاراکتر -->
    {inner_svg}
</svg>"""
    return svg


def _render_preset_content(preset_id: str, nums: List[int], c1: str, c2: str, c3: str) -> str:
    """تولید محتوای هندسی کاراکتر بر اساس پریست انتخابی"""

    # رنگ‌های مکمل
    neon_color = "#38bdf8" if nums[3] % 2 == 0 else "#34d399"
    accent_gold = "#fbbf24"
    eye_color = "#22d3ee" if nums[4] % 2 == 0 else "#a855f7"

    if preset_id in ["cyber_bot", "robot_neon"]:
        # ─── ربات سه‌بعدی و مدرن ───
        visor_shape = (
            f'<rect x="40" y="48" width="40" height="14" rx="7" fill="#0f172a" />'
            f'<rect x="42" y="50" width="36" height="10" rx="5" fill="{eye_color}" opacity="0.9" />'
            f'<circle cx="48" cy="55" r="2.5" fill="#ffffff" />'
            f'<circle cx="72" cy="55" r="2.5" fill="#ffffff" />'
        ) if preset_id == "cyber_bot" else (
            f'<circle cx="48" cy="54" r="6.5" fill="#0f172a" />'
            f'<circle cx="48" cy="54" r="4.5" fill="{eye_color}" />'
            f'<circle cx="72" cy="54" r="6.5" fill="#0f172a" />'
            f'<circle cx="72" cy="54" r="4.5" fill="{eye_color}" />'
            f'<circle cx="49.5" cy="52.5" r="1.5" fill="#ffffff" />'
            f'<circle cx="73.5" cy="52.5" r="1.5" fill="#ffffff" />'
        )

        antenna = (
            f'<line x1="60" y1="28" x2="60" y2="18" stroke="#cbd5e1" stroke-width="3" stroke-linecap="round" />'
            f'<circle cx="60" cy="16" r="4" fill="{accent_gold}" />'
        )

        headphones = (
            f'<rect x="25" y="44" width="7" height="22" rx="3.5" fill="#334155" stroke="#94a3b8" stroke-width="1" />'
            f'<rect x="88" y="44" width="7" height="22" rx="3.5" fill="#334155" stroke="#94a3b8" stroke-width="1" />'
            f'<path d="M 28 44 Q 60 22 92 44" fill="none" stroke="#64748b" stroke-width="3.5" stroke-linecap="round" />'
        )

        body = (
            f'<path d="M 36 94 Q 60 84 84 94 L 88 116 L 32 116 Z" fill="#1e293b" />'
            f'<rect x="52" y="94" width="16" height="8" rx="2" fill="{neon_color}" opacity="0.8" />'
        )

        return f"""
        {headphones}
        {body}
        <!-- سر ربات -->
        <rect x="32" y="30" width="56" height="50" rx="16" fill="url(#metal_grad)" stroke="#ffffff" stroke-width="1" />
        {antenna}
        {visor_shape}
        <!-- دهان/اسپیکر -->
        <line x1="48" y1="70" x2="72" y2="70" stroke="#334155" stroke-width="3" stroke-linecap="round" />
        <circle cx="60" cy="70" r="1.5" fill="{accent_gold}" />
        """

    elif preset_id in ["adventurer_boy", "adventurer_girl"]:
        # ─── کاراکتر انسان / آواتار سه‌بعدی ───
        skin_color = "#fed7aa" if nums[5] % 2 == 0 else "#fde047"
        hair_color = "#334155" if preset_id == "adventurer_boy" else "#be185d"
        
        glasses = (
            f'<rect x="40" y="48" width="16" height="13" rx="4" fill="none" stroke="#1e293b" stroke-width="2.5" />'
            f'<rect x="64" y="48" width="16" height="13" rx="4" fill="none" stroke="#1e293b" stroke-width="2.5" />'
            f'<line x1="56" y1="54" x2="64" y2="54" stroke="#1e293b" stroke-width="2.5" />'
        ) if nums[6] % 2 == 0 else ""

        hair = (
            f'<path d="M 36 44 C 36 24 84 24 84 44 C 74 32 46 32 36 44 Z" fill="{hair_color}" />'
            f'<path d="M 40 30 Q 60 18 80 30" fill="{hair_color}" />'
        ) if preset_id == "adventurer_boy" else (
            f'<path d="M 32 48 C 32 20 88 20 88 48 C 88 72 82 76 82 76 C 82 50 78 36 60 36 C 42 36 38 50 38 76 Z" fill="{hair_color}" />'
        )

        return f"""
        <!-- لباس -->
        <path d="M 32 94 C 44 82 76 82 88 94 L 92 118 L 28 118 Z" fill="#0f172a" />
        <path d="M 52 86 L 60 98 L 68 86 Z" fill="#f8fafc" />
        
        <!-- گردن و صورت -->
        <rect x="52" y="72" width="16" height="16" rx="4" fill="{skin_color}" />
        <circle cx="60" cy="56" r="24" fill="{skin_color}" />
        
        {hair}
        
        <!-- چشم‌ها و لبخند -->
        <circle cx="50" cy="54" r="3" fill="#0f172a" />
        <circle cx="70" cy="54" r="3" fill="#0f172a" />
        <circle cx="51" cy="53" r="1" fill="#ffffff" />
        <circle cx="71" cy="53" r="1" fill="#ffffff" />
        <path d="M 52 66 Q 60 73 68 66" fill="none" stroke="#e11d48" stroke-width="2.5" stroke-linecap="round" />
        {glasses}
        """

    elif preset_id == "astronaut":
        # ─── فضانورد آینده‌نگر ───
        return f"""
        <!-- کلاه و لباس فضانوردی -->
        <path d="M 30 92 C 42 78 78 78 90 92 L 96 118 L 24 118 Z" fill="#e2e8f0" stroke="#94a3b8" stroke-width="1.5" />
        <circle cx="60" cy="52" r="30" fill="#f8fafc" stroke="#cbd5e1" stroke-width="2" />
        <!-- ویزور طلایی/نئونی شیشه‌ای -->
        <ellipse cx="60" cy="52" rx="22" ry="17" fill="#0f172a" />
        <ellipse cx="60" cy="52" rx="20" ry="15" fill="url(#bg_{GRADIENTS[nums[2]%len(GRADIENTS)][0]}_{nums[2]})" opacity="0.85" />
        <path d="M 45 42 Q 60 36 75 42" fill="none" stroke="#ffffff" stroke-width="2" stroke-linecap="round" opacity="0.6" />
        <circle cx="70" cy="46" r="2" fill="#ffffff" opacity="0.8" />
        """

    elif preset_id == "cyber_ninja":
        # ─── نینجا / هیرو تکنولوژی ───
        return f"""
        <!-- هودی و لباس تیره -->
        <path d="M 28 92 C 40 76 80 76 92 92 L 98 118 L 22 118 Z" fill="#090d16" />
        <!-- نقاب و سر -->
        <circle cx="60" cy="54" r="26" fill="#1e293b" />
        <!-- ماسک تهویه‌دار -->
        <path d="M 40 56 L 60 76 L 80 56 Z" fill="#0f172a" stroke="{neon_color}" stroke-width="1.5" />
        <line x1="52" y1="62" x2="68" y2="62" stroke="{neon_color}" stroke-width="1.5" />
        <line x1="55" y1="68" x2="65" y2="68" stroke="{neon_color}" stroke-width="1.5" />
        <!-- چشم‌های خشن نئونی -->
        <polygon points="44,48 54,51 44,53" fill="{neon_color}" />
        <polygon points="76,48 66,51 76,53" fill="{neon_color}" />
        <circle cx="48" cy="51" r="1.5" fill="#ffffff" />
        <circle cx="72" cy="51" r="1.5" fill="#ffffff" />
        """

    elif preset_id == "cyber_cat" or preset_id == "cyber_fox":
        # ─── گربه و روباه سایبرپانک ───
        ear_color = "#f97316" if preset_id == "cyber_fox" else "#a855f7"
        return f"""
        <!-- گوش‌های هندسی -->
        <polygon points="36,44 26,18 50,30" fill="{ear_color}" stroke="#ffffff" stroke-width="1" />
        <polygon points="84,44 94,18 70,30" fill="{ear_color}" stroke="#ffffff" stroke-width="1" />
        <polygon points="36,40 30,24 46,32" fill="#fed7aa" />
        <polygon points="84,40 90,24 74,32" fill="#fed7aa" />
        
        <!-- سر -->
        <circle cx="60" cy="58" r="26" fill="#f8fafc" stroke="#cbd5e1" stroke-width="1.5" />
        
        <!-- چشم‌ها -->
        <ellipse cx="48" cy="54" rx="5" ry="7" fill="#0f172a" />
        <ellipse cx="72" cy="54" rx="5" ry="7" fill="#0f172a" />
        <circle cx="50" cy="52" r="2.5" fill="{neon_color}" />
        <circle cx="74" cy="52" r="2.5" fill="{neon_color}" />
        <circle cx="51" cy="50" r="1" fill="#ffffff" />
        <circle cx="75" cy="50" r="1" fill="#ffffff" />
        
        <!-- بینی و سبیل -->
        <polygon points="60,63 56,60 64,60" fill="#e11d48" />
        <line x1="34" y1="62" x2="48" y2="63" stroke="#64748b" stroke-width="1.5" stroke-linecap="round" />
        <line x1="34" y1="67" x2="48" y2="66" stroke="#64748b" stroke-width="1.5" stroke-linecap="round" />
        <line x1="86" y1="62" x2="72" y2="63" stroke="#64748b" stroke-width="1.5" stroke-linecap="round" />
        <line x1="86" y1="67" x2="72" y2="66" stroke="#64748b" stroke-width="1.5" stroke-linecap="round" />
        """

    elif preset_id in ["emoji_cool", "emoji_happy"]:
        # ─── ایموجی شاد / باحال سه‌بعدی ───
        glasses_or_eyes = (
            f'<path d="M 34 46 Q 47 43 60 46 Q 73 43 86 46 L 84 58 Q 72 61 60 56 Q 48 61 36 58 Z" fill="#0f172a" />'
            f'<line x1="38" y1="49" x2="56" y2="49" stroke="#38bdf8" stroke-width="1.5" opacity="0.7" />'
            f'<line x1="64" y1="49" x2="82" y2="49" stroke="#38bdf8" stroke-width="1.5" opacity="0.7" />'
        ) if preset_id == "emoji_cool" else (
            f'<path d="M 44 48 Q 50 42 56 48" fill="none" stroke="#0f172a" stroke-width="3.5" stroke-linecap="round" />'
            f'<path d="M 64 48 Q 70 42 76 48" fill="none" stroke="#0f172a" stroke-width="3.5" stroke-linecap="round" />'
            f'<circle cx="40" cy="58" r="4" fill="#f43f5e" opacity="0.5" />'
            f'<circle cx="80" cy="58" r="4" fill="#f43f5e" opacity="0.5" />'
        )

        mouth = (
            f'<path d="M 46 68 Q 60 80 74 68" fill="#e11d48" stroke="#0f172a" stroke-width="2" />'
            f'<path d="M 50 68 Q 60 74 70 68" fill="#ffffff" />'
        )

        return f"""
        <!-- گوی طلایی ۳ بعدی -->
        <circle cx="60" cy="58" r="32" fill="#fbbf24" stroke="#d97706" stroke-width="1.5" />
        <path d="M 38 42 Q 60 30 82 42" fill="none" stroke="#ffffff" stroke-width="3" stroke-linecap="round" opacity="0.5" />
        {glasses_or_eyes}
        {mouth}
        """

    else:
        # ─── ایجنت / حکیم کوانتومی / پیش‌فرض ───
        return f"""
        <!-- لباس شیک -->
        <path d="M 30 94 C 42 80 78 80 90 94 L 96 118 L 24 118 Z" fill="#0f172a" />
        <polygon points="60,82 54,98 60,110 66,98" fill="#e11d48" />
        <polygon points="52,82 60,94 56,82" fill="#ffffff" />
        <polygon points="68,82 60,94 64,82" fill="#ffffff" />
        
        <!-- سر و صورت -->
        <circle cx="60" cy="54" r="25" fill="#f8fafc" stroke="#cbd5e1" stroke-width="1.5" />
        
        <!-- عینک مدرن ایجنت -->
        <rect x="42" y="48" width="15" height="10" rx="2" fill="#0f172a" />
        <rect x="63" y="48" width="15" height="10" rx="2" fill="#0f172a" />
        <line x1="57" y1="52" x2="63" y2="52" stroke="#0f172a" stroke-width="2" />
        <circle cx="46" cy="51" r="1.5" fill="{neon_color}" />
        <circle cx="67" cy="51" r="1.5" fill="{neon_color}" />
        
        <!-- لبخند با اعتماد به نفس -->
        <path d="M 52 67 Q 60 72 68 67" fill="none" stroke="#0f172a" stroke-width="2" stroke-linecap="round" />
        """
