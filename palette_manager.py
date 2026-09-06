# -*- coding: utf-8 -*-
"""
ماژول مدیریت پالت‌های رنگی و جلوه شیشه‌ای مات (Palette & Glassmorphism Manager)
طراحی‌شده با الگوبرداری از رابط کاربری VPS Host و سیستم‌های مدرن ابری
پشتیبانی کامل از حالت روشن (Light Mode) و حالت تیره (Dark Mode)
"""

from typing import Dict, Any, List

PALETTES: Dict[str, Dict[str, Any]] = {
    "vps_aurora": {
        "id": "vps_aurora",
        "name": "وی‌پی‌اس اورورا (الگوی مرجع)",
        "subtitle": "هاله‌های نوری فیروزه‌ای، آبی آسمانی و ارغوانی نئونی",
        "description": "دقیقاً مطابق با الگوی تصویری VPS Host با جلوه کریستالی شیشه‌ای و هاله‌های ملایم درخشان",
        "is_default": True,
        "primary_color": "#2563eb",
        "primary_hover": "#1d4ed8",
        "accent_color": "#00d2ff",
        "preview": {
            "blob1": "#00d2ff",
            "blob2": "#d946ef",
            "blob3": "#3b82f6",
            "gradient": "linear-gradient(135deg, #00d2ff 0%, #3b82f6 50%, #d946ef 100%)"
        },
        "light": {
            "body_bg": "#f8fafc",
            "card_bg": "rgba(255, 255, 255, 0.76)",
            "card_border": "rgba(255, 255, 255, 0.85)",
            "card_border_subtle": "rgba(226, 232, 240, 0.75)",
            "card_shadow": "0 14px 38px -10px rgba(37, 99, 235, 0.08), 0 4px 14px rgba(0, 0, 0, 0.04)",
            "text_main": "#0f172a",
            "text_muted": "#475569",
            "chip_bg": "rgba(255, 255, 255, 0.7)",
            "chip_border": "rgba(226, 232, 240, 0.9)",
            "blob1_color": "rgba(0, 210, 255, 0.38)",
            "blob2_color": "rgba(217, 70, 239, 0.32)",
            "blob3_color": "rgba(59, 130, 246, 0.28)",
            "mesh_blend": "multiply"
        },
        "dark": {
            "body_bg": "#070b14",
            "card_bg": "rgba(15, 23, 42, 0.72)",
            "card_border": "rgba(255, 255, 255, 0.09)",
            "card_border_subtle": "rgba(255, 255, 255, 0.06)",
            "card_shadow": "0 20px 45px -12px rgba(0, 0, 0, 0.65), 0 0 25px rgba(37, 99, 235, 0.12)",
            "text_main": "#f8fafc",
            "text_muted": "#94a3b8",
            "chip_bg": "rgba(255, 255, 255, 0.05)",
            "chip_border": "rgba(255, 255, 255, 0.1)",
            "blob1_color": "rgba(0, 180, 255, 0.28)",
            "blob2_color": "rgba(192, 38, 211, 0.25)",
            "blob3_color": "rgba(37, 99, 235, 0.22)",
            "mesh_blend": "screen"
        }
    },
    "cyber_emerald": {
        "id": "cyber_emerald",
        "name": "زمرد سایبری (سبز مدرن)",
        "subtitle": "هاله‌های نوری زمردی، فیروزه‌ای و لیمویی پرسرعت",
        "description": "حس مدرنیته، پایداری و سرعت بالا با بازتاب نورهای زمردی و فیروزه‌ای کریستالی",
        "is_default": False,
        "primary_color": "#059669",
        "primary_hover": "#047857",
        "accent_color": "#10b981",
        "preview": {
            "blob1": "#10b981",
            "blob2": "#06b6d4",
            "blob3": "#84cc16",
            "gradient": "linear-gradient(135deg, #10b981 0%, #06b6d4 50%, #84cc16 100%)"
        },
        "light": {
            "body_bg": "#f7faf8",
            "card_bg": "rgba(255, 255, 255, 0.78)",
            "card_border": "rgba(255, 255, 255, 0.85)",
            "card_border_subtle": "rgba(209, 250, 229, 0.8)",
            "card_shadow": "0 14px 38px -10px rgba(16, 185, 129, 0.09), 0 4px 14px rgba(0, 0, 0, 0.04)",
            "text_main": "#062e20",
            "text_muted": "#405b50",
            "chip_bg": "rgba(255, 255, 255, 0.72)",
            "chip_border": "rgba(209, 250, 229, 0.95)",
            "blob1_color": "rgba(16, 185, 129, 0.36)",
            "blob2_color": "rgba(6, 182, 212, 0.30)",
            "blob3_color": "rgba(132, 204, 22, 0.26)",
            "mesh_blend": "multiply"
        },
        "dark": {
            "body_bg": "#050f0c",
            "card_bg": "rgba(8, 26, 20, 0.74)",
            "card_border": "rgba(16, 185, 129, 0.15)",
            "card_border_subtle": "rgba(255, 255, 255, 0.06)",
            "card_shadow": "0 20px 45px -12px rgba(0, 0, 0, 0.7), 0 0 25px rgba(16, 185, 129, 0.14)",
            "text_main": "#ecfdf5",
            "text_muted": "#94a3b8",
            "chip_bg": "rgba(16, 185, 129, 0.08)",
            "chip_border": "rgba(16, 185, 129, 0.2)",
            "blob1_color": "rgba(16, 185, 129, 0.28)",
            "blob2_color": "rgba(6, 182, 212, 0.24)",
            "blob3_color": "rgba(132, 204, 22, 0.18)",
            "mesh_blend": "screen"
        }
    },
    "sunset_cosmic": {
        "id": "sunset_cosmic",
        "name": "غروب کیهانی (رز و امبر)",
        "subtitle": "هاله‌های گرم مرجانی، رز نئونی و پرتو طلایی غروب",
        "description": "پالت لوکس، پرانرژی و جذاب با ترکیب لطیف رنگ‌های گرم و بنفش شامگاهی",
        "is_default": False,
        "primary_color": "#e11d48",
        "primary_hover": "#be123c",
        "accent_color": "#f97316",
        "preview": {
            "blob1": "#f43f5e",
            "blob2": "#f97316",
            "blob3": "#8b5cf6",
            "gradient": "linear-gradient(135deg, #f43f5e 0%, #f97316 50%, #8b5cf6 100%)"
        },
        "light": {
            "body_bg": "#fff8f6",
            "card_bg": "rgba(255, 255, 255, 0.78)",
            "card_border": "rgba(255, 255, 255, 0.88)",
            "card_border_subtle": "rgba(254, 226, 226, 0.8)",
            "card_shadow": "0 14px 38px -10px rgba(225, 29, 72, 0.09), 0 4px 14px rgba(0, 0, 0, 0.04)",
            "text_main": "#260e14",
            "text_muted": "#5e3e46",
            "chip_bg": "rgba(255, 255, 255, 0.72)",
            "chip_border": "rgba(254, 215, 170, 0.8)",
            "blob1_color": "rgba(244, 63, 94, 0.35)",
            "blob2_color": "rgba(249, 115, 22, 0.30)",
            "blob3_color": "rgba(139, 92, 246, 0.24)",
            "mesh_blend": "multiply"
        },
        "dark": {
            "body_bg": "#12090e",
            "card_bg": "rgba(29, 14, 22, 0.75)",
            "card_border": "rgba(244, 63, 94, 0.16)",
            "card_border_subtle": "rgba(255, 255, 255, 0.06)",
            "card_shadow": "0 20px 45px -12px rgba(0, 0, 0, 0.7), 0 0 25px rgba(244, 63, 94, 0.15)",
            "text_main": "#fff1f2",
            "text_muted": "#fda4af",
            "chip_bg": "rgba(244, 63, 94, 0.08)",
            "chip_border": "rgba(244, 63, 94, 0.22)",
            "blob1_color": "rgba(244, 63, 94, 0.27)",
            "blob2_color": "rgba(249, 115, 22, 0.24)",
            "blob3_color": "rgba(139, 92, 246, 0.20)",
            "mesh_blend": "screen"
        }
    },
    "deep_nebula": {
        "id": "deep_nebula",
        "name": "سحابی بنفش (کهکشان رویال)",
        "subtitle": "هاله‌های بنفش الکتریک، ایندیگو و ارغوانی سحابی",
        "description": "سبک اعیانی و اسرارآمیز با عمق رنگ‌های کهکشانی و کارت‌های شیشه‌ای مخملی",
        "is_default": False,
        "primary_color": "#7c3aed",
        "primary_hover": "#6d28d9",
        "accent_color": "#c026d3",
        "preview": {
            "blob1": "#8b5cf6",
            "blob2": "#c026d3",
            "blob3": "#3b82f6",
            "gradient": "linear-gradient(135deg, #8b5cf6 0%, #c026d3 50%, #3b82f6 100%)"
        },
        "light": {
            "body_bg": "#faf7ff",
            "card_bg": "rgba(255, 255, 255, 0.78)",
            "card_border": "rgba(255, 255, 255, 0.88)",
            "card_border_subtle": "rgba(237, 233, 254, 0.8)",
            "card_shadow": "0 14px 38px -10px rgba(124, 58, 237, 0.09), 0 4px 14px rgba(0, 0, 0, 0.04)",
            "text_main": "#1e1338",
            "text_muted": "#51436e",
            "chip_bg": "rgba(255, 255, 255, 0.72)",
            "chip_border": "rgba(237, 233, 254, 0.9)",
            "blob1_color": "rgba(139, 92, 246, 0.36)",
            "blob2_color": "rgba(192, 38, 211, 0.30)",
            "blob3_color": "rgba(59, 130, 246, 0.25)",
            "mesh_blend": "multiply"
        },
        "dark": {
            "body_bg": "#0a0715",
            "card_bg": "rgba(22, 16, 38, 0.75)",
            "card_border": "rgba(139, 92, 246, 0.18)",
            "card_border_subtle": "rgba(255, 255, 255, 0.06)",
            "card_shadow": "0 20px 45px -12px rgba(0, 0, 0, 0.75), 0 0 25px rgba(139, 92, 246, 0.16)",
            "text_main": "#f5f3ff",
            "text_muted": "#c4b5fd",
            "chip_bg": "rgba(139, 92, 246, 0.08)",
            "chip_border": "rgba(139, 92, 246, 0.22)",
            "blob1_color": "rgba(139, 92, 246, 0.30)",
            "blob2_color": "rgba(192, 38, 211, 0.24)",
            "blob3_color": "rgba(59, 130, 246, 0.20)",
            "mesh_blend": "screen"
        }
    },
    "ocean_breeze": {
        "id": "ocean_breeze",
        "name": "نسیم اقیانوس (آبی و فیروزه‌ای)",
        "subtitle": "هاله‌های زلال اقیانوسی، آکوامارین و آسمانی روشن",
        "description": "آرامش‌بخش، شفاف و فوق‌العاده خوانا با بازتاب ملایم رنگ‌های آبی دریایی",
        "is_default": False,
        "primary_color": "#0284c7",
        "primary_hover": "#0369a1",
        "accent_color": "#14b8a6",
        "preview": {
            "blob1": "#0ea5e9",
            "blob2": "#14b8a6",
            "blob3": "#38bdf8",
            "gradient": "linear-gradient(135deg, #0ea5e9 0%, #14b8a6 50%, #38bdf8 100%)"
        },
        "light": {
            "body_bg": "#f4f9fd",
            "card_bg": "rgba(255, 255, 255, 0.78)",
            "card_border": "rgba(255, 255, 255, 0.88)",
            "card_border_subtle": "rgba(224, 242, 254, 0.8)",
            "card_shadow": "0 14px 38px -10px rgba(2, 132, 199, 0.08), 0 4px 14px rgba(0, 0, 0, 0.04)",
            "text_main": "#082f49",
            "text_muted": "#475569",
            "chip_bg": "rgba(255, 255, 255, 0.72)",
            "chip_border": "rgba(224, 242, 254, 0.9)",
            "blob1_color": "rgba(14, 165, 233, 0.36)",
            "blob2_color": "rgba(20, 184, 166, 0.30)",
            "blob3_color": "rgba(56, 189, 248, 0.26)",
            "mesh_blend": "multiply"
        },
        "dark": {
            "body_bg": "#051119",
            "card_bg": "rgba(10, 28, 41, 0.74)",
            "card_border": "rgba(14, 165, 233, 0.16)",
            "card_border_subtle": "rgba(255, 255, 255, 0.06)",
            "card_shadow": "0 20px 45px -12px rgba(0, 0, 0, 0.7), 0 0 25px rgba(14, 165, 233, 0.14)",
            "text_main": "#f0f9ff",
            "text_muted": "#7dd3fc",
            "chip_bg": "rgba(14, 165, 233, 0.08)",
            "chip_border": "rgba(14, 165, 233, 0.2)",
            "blob1_color": "rgba(14, 165, 233, 0.28)",
            "blob2_color": "rgba(20, 184, 166, 0.22)",
            "blob3_color": "rgba(56, 189, 248, 0.20)",
            "mesh_blend": "screen"
        }
    },
    "midnight_obsidian": {
        "id": "midnight_obsidian",
        "name": "آبسیدین مینیمال (استیل و نقره‌ای)",
        "subtitle": "مونوکروم تیتانیوم، استیل و هایلایت یخی محو",
        "description": "استایلی باوقار، رسمی و مینیمال با حداقل رنگ و بالاترین سطح خوانایی سازمانی",
        "is_default": False,
        "primary_color": "#475569",
        "primary_hover": "#334155",
        "accent_color": "#64748b",
        "preview": {
            "blob1": "#64748b",
            "blob2": "#94a3b8",
            "blob3": "#38bdf8",
            "gradient": "linear-gradient(135deg, #475569 0%, #64748b 50%, #94a3b8 100%)"
        },
        "light": {
            "body_bg": "#f8fafc",
            "card_bg": "rgba(255, 255, 255, 0.82)",
            "card_border": "rgba(255, 255, 255, 0.9)",
            "card_border_subtle": "rgba(226, 232, 240, 0.85)",
            "card_shadow": "0 14px 38px -10px rgba(0, 0, 0, 0.06), 0 4px 14px rgba(0, 0, 0, 0.03)",
            "text_main": "#0f172a",
            "text_muted": "#475569",
            "chip_bg": "rgba(255, 255, 255, 0.75)",
            "chip_border": "rgba(203, 213, 225, 0.85)",
            "blob1_color": "rgba(100, 116, 139, 0.24)",
            "blob2_color": "rgba(148, 163, 184, 0.20)",
            "blob3_color": "rgba(56, 189, 248, 0.16)",
            "mesh_blend": "multiply"
        },
        "dark": {
            "body_bg": "#090d14",
            "card_bg": "rgba(18, 24, 34, 0.75)",
            "card_border": "rgba(255, 255, 255, 0.08)",
            "card_border_subtle": "rgba(255, 255, 255, 0.05)",
            "card_shadow": "0 20px 45px -12px rgba(0, 0, 0, 0.7), 0 0 20px rgba(255, 255, 255, 0.03)",
            "text_main": "#f8fafc",
            "text_muted": "#94a3b8",
            "chip_bg": "rgba(255, 255, 255, 0.04)",
            "chip_border": "rgba(255, 255, 255, 0.08)",
            "blob1_color": "rgba(100, 116, 139, 0.20)",
            "blob2_color": "rgba(148, 163, 184, 0.16)",
            "blob3_color": "rgba(56, 189, 248, 0.12)",
            "mesh_blend": "screen"
        }
    },
    "classic_clean": {
        "id": "classic_clean",
        "name": "کلاسیک ساده (بدون هاله نوری)",
        "subtitle": "رابط کاربری کلاسیک تخت بدون المان‌های نوری",
        "description": "مناسب سیستم‌های قدیمی‌تر یا کاربرانی که ظاهر ساده، مات سنتی و بدون حرکت را می‌پسندند",
        "is_default": False,
        "primary_color": "#4f46e5",
        "primary_hover": "#4338ca",
        "accent_color": "#0ea5e9",
        "preview": {
            "blob1": "#4f46e5",
            "blob2": "#0ea5e9",
            "blob3": "#e2e8f0",
            "gradient": "linear-gradient(135deg, #4f46e5 0%, #0ea5e9 100%)"
        },
        "light": {
            "body_bg": "#f8fafc",
            "card_bg": "#ffffff",
            "card_border": "rgba(0, 0, 0, 0.08)",
            "card_border_subtle": "rgba(0, 0, 0, 0.06)",
            "card_shadow": "0 10px 25px -5px rgba(0, 0, 0, 0.05)",
            "text_main": "#1e293b",
            "text_muted": "#64748b",
            "chip_bg": "#f1f5f9",
            "chip_border": "rgba(0, 0, 0, 0.08)",
            "blob1_color": "transparent",
            "blob2_color": "transparent",
            "blob3_color": "transparent",
            "mesh_blend": "normal"
        },
        "dark": {
            "body_bg": "#0b0f19",
            "card_bg": "#151e2e",
            "card_border": "#1e293b",
            "card_border_subtle": "rgba(255, 255, 255, 0.05)",
            "card_shadow": "0 16px 36px -8px rgba(0, 0, 0, 0.5)",
            "text_main": "#f8fafc",
            "text_muted": "#94a3b8",
            "chip_bg": "rgba(255, 255, 255, 0.05)",
            "chip_border": "rgba(255, 255, 255, 0.08)",
            "blob1_color": "transparent",
            "blob2_color": "transparent",
            "blob3_color": "transparent",
            "mesh_blend": "normal"
        }
    }
}


def get_all_palettes() -> Dict[str, Dict[str, Any]]:
    """دریافت لیست کامل پالت‌های پشتیبانی‌شده"""
    return PALETTES


def get_palette(palette_id: str) -> Dict[str, Any]:
    """دریافت اطلاعات یک پالت با پشتیبانی از پالت پیش‌فرض"""
    return PALETTES.get(palette_id) or PALETTES["vps_aurora"]


def get_active_palette_config(db_instance, context: str = "system") -> Dict[str, Any]:
    """
    دریافت تنظیمات پالت فعال از دیتابیس
    context: 'system' برای پنل ادمین و همکاران، 'portal' برای پورتال مشتری
    """
    system_palette_id = db_instance.get_setting("active_palette", "vps_aurora")
    portal_setting = db_instance.get_setting("portal_palette", "inherit")
    
    if context == "portal" and portal_setting and portal_setting != "inherit":
        palette_id = portal_setting
    else:
        palette_id = system_palette_id

    intensity = db_instance.get_setting("palette_intensity", "normal") # high, normal, subtle, off
    animation = db_instance.get_setting("palette_animation", "float") # float, static, off
    
    palette_data = get_palette(palette_id)

    return {
        "palette_id": palette_id,
        "intensity": intensity,
        "animation": animation,
        "portal_palette": portal_setting,
        "data": palette_data
    }


def generate_palette_css(palette_config: Dict[str, Any]) -> str:
    """
    تولید کدهای بهینه‌شده CSS برای تزریق مستقیم به هدر قالب‌ها
    """
    data = palette_config.get("data") or PALETTES["vps_aurora"]
    intensity = palette_config.get("intensity", "normal")
    animation = palette_config.get("animation", "float")
    pid = data.get("id", "vps_aurora")

    # ضرایب بلور و شدت نور بر اساس intensity
    if intensity == "off" or pid == "classic_clean":
        blur_val = "0px"
        light_opacity = "0"
        dark_opacity = "0"
        glass_blur = "0px"
    elif intensity == "subtle":
        blur_val = "100px"
        light_opacity = "0.55"
        dark_opacity = "0.6"
        glass_blur = "12px"
    elif intensity == "high":
        blur_val = "70px"
        light_opacity = "1.25"
        dark_opacity = "1.3"
        glass_blur = "24px"
    else: # normal
        blur_val = "85px"
        light_opacity = "1.0"
        dark_opacity = "1.0"
        glass_blur = "18px"

    l = data["light"]
    d = data["dark"]

    css = f"""
    /* ─── پالت اختصاصی: {data['name']} ─── */
    :root {{
        --palette-primary: {data['primary_color']};
        --palette-primary-hover: {data['primary_hover']};
        --palette-accent: {data['accent_color']};
        --aura-blur: {blur_val};
        --glass-blur: {glass_blur};
        
        /* حالت روشن (Light Mode) */
        --palette-body-bg: {l['body_bg']};
        --palette-card-bg: {l['card_bg']};
        --palette-card-border: {l['card_border']};
        --palette-card-border-subtle: {l['card_border_subtle']};
        --palette-card-shadow: {l['card_shadow']};
        --palette-text-main: {l['text_main']};
        --palette-text-muted: {l['text_muted']};
        --palette-chip-bg: {l['chip_bg']};
        --palette-chip-border: {l['chip_border']};
        --aura-blob-1: {l['blob1_color']};
        --aura-blob-2: {l['blob2_color']};
        --aura-blob-3: {l['blob3_color']};
        --aura-opacity: {light_opacity};
        --aura-blend: {l['mesh_blend']};
    }}

    [data-bs-theme="dark"] {{
        /* حالت تیره (Dark Mode) */
        --palette-body-bg: {d['body_bg']};
        --palette-card-bg: {d['card_bg']};
        --palette-card-border: {d['card_border']};
        --palette-card-border-subtle: {d['card_border_subtle']};
        --palette-card-shadow: {d['card_shadow']};
        --palette-text-main: {d['text_main']};
        --palette-text-muted: {d['text_muted']};
        --palette-chip-bg: {d['chip_bg']};
        --palette-chip-border: {d['chip_border']};
        --aura-blob-1: {d['blob1_color']};
        --aura-blob-2: {d['blob2_color']};
        --aura-blob-3: {d['blob3_color']};
        --aura-opacity: {dark_opacity};
        --aura-blend: {d['mesh_blend']};
    }}
    """
    return css
