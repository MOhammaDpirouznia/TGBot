# -*- coding: utf-8 -*-
    return css
    """
def get_active_palette_config(db_instance, context: str = "system", reseller_id: int = None) -> Dict[str, Any]:
    """
    دریافت تنظیمات پالت فعال بر اساس کانتکست
    context: 'system' برای پنل ادمین و نمایندگان، 'portal' برای پورتال مشتری
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

    intensity = db_instance.get_setting("palette_intensity", "normal")
    animation = db_instance.get_setting("palette_animation", "float")
    
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
