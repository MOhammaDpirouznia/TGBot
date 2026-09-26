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
            "body_bg": "#f1f5f9",
            "card_bg": "#ffffff",
            "card_border": "#cbd5e1",
            "card_border_subtle": "#e2e8f0",
            "card_shadow": "0 4px 20px -2px rgba(15, 23, 42, 0.08), 0 2px 6px -1px rgba(15, 23, 42, 0.04)",
            "text_main": "#0f172a",
            "text_muted": "#475569",
            "chip_bg": "#f8fafc",
            "chip_border": "#cbd5e1",
            "blob1_color": "rgba(0, 210, 255, 0.22)",
            "blob2_color": "rgba(217, 70, 239, 0.18)",
            "blob3_color": "rgba(59, 130, 246, 0.16)",
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
    "ios_glass": {
        "id": "ios_glass",
        "name": "اپل گلس آیفون (iOS Liquid Glass)",
        "subtitle": "شیشه‌ای فوق‌مات و کریستالی با الهام از iOS 18 و سیستم‌های مدرن اپل",
        "description": "طراحی پیشرفته شیشه‌ای مات (Frosted Glassmorphism) با ماتی عمیق، لبه‌های بازتابنده نور و کنتراست فوق‌العاده بالا در هر دو حالت تیره و روشن",
        "is_default": False,
        "primary_color": "#007aff",
        "primary_hover": "#005ecb",
        "accent_color": "#5856d6",
        "preview": {
            "blob1": "#007aff",
            "blob2": "#af52de",
            "blob3": "#38bdf8",
            "gradient": "linear-gradient(135deg, #007aff 0%, #af52de 50%, #38bdf8 100%)"
        },
        "light": {
            "body_bg": "#f5f7fc",
            "card_bg": "rgba(255, 255, 255, 0.74)",
            "card_border": "rgba(255, 255, 255, 0.85)",
            "card_border_subtle": "rgba(226, 232, 240, 0.7)",
            "card_shadow": "0 10px 32px -4px rgba(0, 122, 255, 0.08), 0 2px 8px rgba(15, 23, 42, 0.04), inset 0 1px 1px rgba(255, 255, 255, 0.95)",
            "text_main": "#0f172a",
            "text_muted": "#475569",
            "chip_bg": "rgba(255, 255, 255, 0.65)",
            "chip_border": "rgba(255, 255, 255, 0.85)",
            "blob1_color": "rgba(0, 122, 255, 0.22)",
            "blob2_color": "rgba(175, 82, 222, 0.18)",
            "blob3_color": "rgba(56, 189, 248, 0.20)",
            "mesh_blend": "normal"
        },
        "dark": {
            "body_bg": "#080c14",
            "card_bg": "rgba(16, 24, 40, 0.65)",
            "card_border": "rgba(255, 255, 255, 0.14)",
            "card_border_subtle": "rgba(255, 255, 255, 0.07)",
            "card_shadow": "0 25px 60px -15px rgba(0, 0, 0, 0.8), 0 0 35px rgba(0, 122, 255, 0.12), inset 0 1px 1px rgba(255, 255, 255, 0.18)",
            "text_main": "#f8fafc",
            "text_muted": "#94a3b8",
            "chip_bg": "rgba(255, 255, 255, 0.06)",
            "chip_border": "rgba(255, 255, 255, 0.12)",
            "blob1_color": "rgba(0, 122, 255, 0.32)",
            "blob2_color": "rgba(175, 82, 222, 0.25)",
            "blob3_color": "rgba(56, 189, 248, 0.22)",
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
            "body_bg": "#f0fdf4",
            "card_bg": "#ffffff",
            "card_border": "#a7f3d0",
            "card_border_subtle": "#d1fae5",
            "card_shadow": "0 4px 20px -2px rgba(6, 95, 70, 0.08), 0 2px 6px -1px rgba(6, 95, 70, 0.04)",
            "text_main": "#064e3b",
            "text_muted": "#047857",
            "chip_bg": "#f0fdf4",
            "chip_border": "#a7f3d0",
            "blob1_color": "rgba(16, 185, 129, 0.20)",
            "blob2_color": "rgba(6, 182, 212, 0.18)",
            "blob3_color": "rgba(132, 204, 22, 0.15)",
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
            "body_bg": "#fff1f2",
            "card_bg": "#ffffff",
            "card_border": "#fecdd3",
            "card_border_subtle": "#ffe4e6",
            "card_shadow": "0 4px 20px -2px rgba(159, 18, 57, 0.08), 0 2px 6px -1px rgba(159, 18, 57, 0.04)",
            "text_main": "#881337",
            "text_muted": "#be123c",
            "chip_bg": "#fff1f2",
            "chip_border": "#fecdd3",
            "blob1_color": "rgba(244, 63, 94, 0.20)",
            "blob2_color": "rgba(249, 115, 22, 0.18)",
            "blob3_color": "rgba(139, 92, 246, 0.15)",
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
            "body_bg": "#f5f3ff",
            "card_bg": "#ffffff",
            "card_border": "#ddd6fe",
            "card_border_subtle": "#ede9fe",
            "card_shadow": "0 4px 20px -2px rgba(91, 33, 182, 0.08), 0 2px 6px -1px rgba(91, 33, 182, 0.04)",
            "text_main": "#3b0764",
            "text_muted": "#6d28d9",
            "chip_bg": "#f5f3ff",
            "chip_border": "#ddd6fe",
            "blob1_color": "rgba(139, 92, 246, 0.20)",
            "blob2_color": "rgba(192, 38, 211, 0.18)",
            "blob3_color": "rgba(59, 130, 246, 0.15)",
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
            "body_bg": "#f0f9ff",
            "card_bg": "#ffffff",
            "card_border": "#bae6fd",
            "card_border_subtle": "#e0f2fe",
            "card_shadow": "0 4px 20px -2px rgba(3, 105, 161, 0.08), 0 2px 6px -1px rgba(3, 105, 161, 0.04)",
            "text_main": "#0c4a6e",
            "text_muted": "#0284c7",
            "chip_bg": "#f0f9ff",
            "chip_border": "#bae6fd",
            "blob1_color": "rgba(14, 165, 233, 0.20)",
            "blob2_color": "rgba(20, 184, 166, 0.18)",
            "blob3_color": "rgba(56, 189, 248, 0.15)",
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
            "body_bg": "#f1f5f9",
            "card_bg": "#ffffff",
            "card_border": "#cbd5e1",
            "card_border_subtle": "#e2e8f0",
            "card_shadow": "0 4px 20px -2px rgba(15, 23, 42, 0.08), 0 2px 6px -1px rgba(15, 23, 42, 0.04)",
            "text_main": "#0f172a",
            "text_muted": "#475569",
            "chip_bg": "#f8fafc",
            "chip_border": "#cbd5e1",
            "blob1_color": "rgba(100, 116, 139, 0.16)",
            "blob2_color": "rgba(148, 163, 184, 0.14)",
            "blob3_color": "rgba(56, 189, 248, 0.12)",
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
    "ruby_sunset": {
        "id": "ruby_sunset",
        "name": "غروب یاقوتی (قرمز و نارنجی)",
        "subtitle": "ترکیبی گرم از طیف‌های قرمز، نارنجی و صورتی",
        "description": "پالتی پرانرژی و جذاب با الهام از غروب آفتاب و رنگ‌های گرم پاییزی",
        "primary_color": "#e11d48",
        "primary_hover": "#be123c",
        "accent_color": "#f97316",
        "preview": {
            "blob1": "#f43f5e",
            "blob2": "#fb923c",
            "blob3": "#e11d48",
            "gradient": "linear-gradient(135deg, #f43f5e 0%, #fb923c 50%, #e11d48 100%)"
        },
        "light": {
            "body_bg": "#fff1f2",
            "card_bg": "#ffffff",
            "card_border": "#fecdd3",
            "card_border_subtle": "#ffe4e6",
            "card_shadow": "0 4px 20px -2px rgba(159, 18, 57, 0.08), 0 2px 6px -1px rgba(159, 18, 57, 0.04)",
            "text_main": "#881337",
            "text_muted": "#be123c",
            "chip_bg": "#fff1f2",
            "chip_border": "#fecdd3",
            "blob1_color": "rgba(244, 63, 94, 0.20)",
            "blob2_color": "rgba(251, 146, 60, 0.18)",
            "blob3_color": "rgba(225, 29, 72, 0.15)",
            "mesh_blend": "multiply"
        },
        "dark": {
            "body_bg": "#10090a",
            "card_bg": "rgba(28, 15, 17, 0.75)",
            "card_border": "rgba(225, 29, 72, 0.18)",
            "card_border_subtle": "rgba(255, 255, 255, 0.06)",
            "card_shadow": "0 20px 45px -12px rgba(0, 0, 0, 0.65), 0 0 25px rgba(225, 29, 72, 0.12)",
            "text_main": "#f5f5f4",
            "text_muted": "#a8a29e",
            "chip_bg": "rgba(255, 255, 255, 0.05)",
            "chip_border": "rgba(225, 29, 72, 0.22)",
            "blob1_color": "rgba(244, 63, 94, 0.30)",
            "blob2_color": "rgba(251, 146, 60, 0.24)",
            "blob3_color": "rgba(225, 29, 72, 0.20)",
            "mesh_blend": "screen"
        }
    },
    "emerald_forest": {
        "id": "emerald_forest",
        "name": "جنگل زمرد (سبز و زرد)",
        "subtitle": "طراوت طبیعت با طیف‌های سبز و زرد لیمویی",
        "description": "پالتی آرامش‌بخش و شاداب با الهام از طبیعت و جنگل",
        "primary_color": "#10b981",
        "primary_hover": "#059669",
        "accent_color": "#facc15",
        "preview": {
            "blob1": "#34d399",
            "blob2": "#fde047",
            "blob3": "#10b981",
            "gradient": "linear-gradient(135deg, #34d399 0%, #fde047 50%, #10b981 100%)"
        },
        "light": {
            "body_bg": "#f0fdf4",
            "card_bg": "#ffffff",
            "card_border": "#a7f3d0",
            "card_border_subtle": "#d1fae5",
            "card_shadow": "0 4px 20px -2px rgba(6, 95, 70, 0.08), 0 2px 6px -1px rgba(6, 95, 70, 0.04)",
            "text_main": "#064e3b",
            "text_muted": "#047857",
            "chip_bg": "#f0fdf4",
            "chip_border": "#a7f3d0",
            "blob1_color": "rgba(52, 211, 153, 0.20)",
            "blob2_color": "rgba(253, 224, 71, 0.18)",
            "blob3_color": "rgba(16, 185, 129, 0.15)",
            "mesh_blend": "multiply"
        },
        "dark": {
            "body_bg": "#020f09",
            "card_bg": "rgba(11, 28, 20, 0.75)",
            "card_border": "rgba(16, 185, 129, 0.18)",
            "card_border_subtle": "rgba(255, 255, 255, 0.06)",
            "card_shadow": "0 20px 45px -12px rgba(0, 0, 0, 0.65), 0 0 25px rgba(16, 185, 129, 0.12)",
            "text_main": "#f8fafc",
            "text_muted": "#94a3b8",
            "chip_bg": "rgba(255, 255, 255, 0.05)",
            "chip_border": "rgba(16, 185, 129, 0.22)",
            "blob1_color": "rgba(52, 211, 153, 0.30)",
            "blob2_color": "rgba(253, 224, 71, 0.24)",
            "blob3_color": "rgba(16, 185, 129, 0.20)",
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
            "body_bg": "#f1f5f9",
            "card_bg": "#ffffff",
            "card_border": "#cbd5e1",
            "card_border_subtle": "#e2e8f0",
            "card_shadow": "0 4px 20px -2px rgba(15, 23, 42, 0.08), 0 2px 6px -1px rgba(15, 23, 42, 0.04)",
            "text_main": "#0f172a",
            "text_muted": "#475569",
            "chip_bg": "#f8fafc",
            "chip_border": "#cbd5e1",
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


def get_active_palette_config(db_instance, context: str = "system", reseller_id: int = None) -> Dict[str, Any]:
    """
    دریافت تنظیمات پالت فعال از دیتابیس
    context: 'system' برای پنل ادمین و همکاران، 'portal' برای پورتال مشتری
    """
    system_palette_id = db_instance.get_setting("active_palette", "vps_aurora")
    
    palette_id = system_palette_id
    portal_setting = "inherit"

    if reseller_id:
        res = db_instance.get_reseller(reseller_id)
        if res and res.get("portal_palette") and res.get("portal_palette") != "inherit":
            portal_setting = res.get("portal_palette")
            palette_id = portal_setting

    if portal_setting == "inherit" and context == "portal":
        global_portal_setting = db_instance.get_setting("portal_palette", "inherit")
        if global_portal_setting != "inherit":
            palette_id = global_portal_setting
            portal_setting = global_portal_setting

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
        minimal_mesh_css = """
    .aura-mesh-container {
        display: none !important;
        opacity: 0 !important;
        visibility: hidden !important;
    }
    """
    elif intensity == "subtle":
        blur_val = "100px"
        light_opacity = "0.25"
        dark_opacity = "0.6"
        glass_blur = "14px" if pid == "ios_glass" else "12px"
        minimal_mesh_css = ""
    elif intensity == "high":
        blur_val = "70px"
        light_opacity = "0.50"
        dark_opacity = "1.3"
        glass_blur = "28px" if pid == "ios_glass" else "24px"
        minimal_mesh_css = ""
    else: # normal
        blur_val = "85px"
        light_opacity = "0.35"
        dark_opacity = "1.0"
        glass_blur = "22px" if pid == "ios_glass" else "18px"
        minimal_mesh_css = ""

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
    {minimal_mesh_css}
    """
    return css
