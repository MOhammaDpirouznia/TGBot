"""
موتور و ساختار داده‌های آموزشی و عیب‌یابی چندسکویی (Interactive VPN Guides & Troubleshooting Data)
پوشش جامع: اندروید، تلویزیون هوشمند (Android TV)، آیفون و آیپد (iOS)، ویندوز، مک، لینوکس، مودم و روترها
"""

PLATFORMS = {
    "android": {
        "title": "اندروید (Android)",
        "icon": "fab fa-android",
        "color": "#3ddc84",
        "description": "گوشی‌ها و تبلت‌های سامسونگ، شیائومی، هواوی و سایر دستگاه‌های اندرویدی",
        "apps": ["v2rayng", "hiddify-android", "happ", "nekobox"]
    },
    "ios": {
        "title": "آیفون و آیپد (iOS)",
        "icon": "fab fa-apple",
        "color": "#000000",
        "description": "گوشی‌های آیفون و تبلت‌های آیپد با سیستم‌عامل iOS و iPadOS",
        "apps": ["streisand", "foxray-ios", "v2box", "shadowrocket", "singbox-ios"]
    },
    "windows": {
        "title": "ویندوز (Windows)",
        "icon": "fab fa-windows",
        "color": "#0078d4",
        "description": "رایانه‌ها و لپ‌تاپ‌های دارای سیستم‌عامل ویندوز ۱۰ و ۱۱",
        "apps": ["hiddify-windows", "v2rayn", "nekoray-win", "clash-verge"]
    },
    "tv": {
        "title": "اندروید تی‌وی (Android TV)",
        "icon": "fas fa-tv",
        "color": "#e11d48",
        "description": "تلویزیون‌های هوشمند سونی، شیائومی، تی‌سی‌ال، اسنوا، دوو و تی‌وی‌باکس‌ها",
        "apps": ["v2rayng-tv", "hiddify-tv", "spark-tv"]
    },
    "macos": {
        "title": "مک‌بوک و مک (macOS)",
        "icon": "fas fa-laptop",
        "color": "#64748b",
        "description": "لپ‌تاپ‌های مک‌بوک و رایانه‌های آی‌مک (پردازنده‌های M1/M2/M3 و اینتل)",
        "apps": ["foxray-mac", "hiddify-mac", "v2rayu"]
    },
    "linux": {
        "title": "لینوکس (Linux)",
        "icon": "fab fa-linux",
        "color": "#f59e0b",
        "description": "توزیع‌های اوبونتو، دبیان، فدورا، آرچ و سرورهای لینوکسی",
        "apps": ["v2raya", "nekoray-linux"]
    },
    "router": {
        "title": "مودم و روتر (Modem / Router)",
        "icon": "fas fa-network-wired",
        "color": "#8b5cf6",
        "description": "آزادسازی اینترنت برای تمام دستگاه‌های خانه از روی مودم و وای‌فای",
        "apps": ["openwrt", "mikrotik", "asuswrt"]
    }
}

TUTORIALS = {
    # ─── اندروید ───
    "v2rayng": {
        "platform": "android",
        "name": "v2rayNG",
        "subtitle": "محبوب‌ترین و پایدارترین اپلیکیشن برای اندروید",
        "badge": "پیشنهادی و پرسرعت",
        "badge_color": "success",
        "icon": "fas fa-rocket",
        "rating": "4.9",
        "downloads": [
            {"title": "دانلود مستقیم APK", "url": "https://github.com/2dust/v2rayNG/releases/latest", "icon": "fas fa-download", "btn_class": "btn-success"},
            {"title": "دریافت از گوگل پلی", "url": "https://play.google.com/store/apps/details?id=com.v2ray.ang", "icon": "fab fa-google-play", "btn_class": "btn-outline-primary"},
            {"title": "دانلود از گیت‌هاب", "url": "https://github.com/2dust/v2rayNG/releases", "icon": "fab fa-github", "btn_class": "btn-outline-dark"}
        ],
        "steps": [
            {
                "step": 1,
                "title": "کپی کردن لینک اشتراک",
                "desc": "ابتدا در ربات تلگرام یا پنل کاربری خود، لینک اشتراک (سابسکریپشن) یا لینک تکی کانفیگ را لمس کنید تا در کلیپ‌بورد کپی شود.",
                "tip": "لینک‌ها معمولاً با https:// یا vless:// یا vmess:// شروع می‌شوند."
            },
            {
                "step": 2,
                "title": "وارد کردن لینک در نرم‌افزار (Import)",
                "desc": "نرم‌افزار v2rayNG را باز کنید. علامت مثبت (+) بالای صفحه را بزنید و گزینه «Import config from Clipboard» یا «وارد کردن کانفیگ از کلیپ‌بورد» را انتخاب نمایید.",
                "tip": "اگر لینک سابسکریپشن دارید، می‌توانید از منوی کشویی سمت چپ (سه خط) وارد «Subscription group setting» شده و علامت + را بزنید و لینک را در بخش Subscription URL قرار دهید."
            },
            {
                "step": 3,
                "title": "بروزرسانی سرورها و تست پینگ",
                "desc": "روی منوی سه‌نقطه بالا سمت راست ضربه بزنید و گزینه «Update subscription» را لمس کنید تا لیست کانفیگ‌ها دریافت شود. سپس علامت سه‌نقطه را زده و «Real delay all configuration» را بزنید تا پینگ سرورها مشخص شود.",
                "tip": "سروری که کمترین عدد پینگ سبز رنگ را دارد بهترین سرعت را ارائه می‌دهد."
            },
            {
                "step": 4,
                "title": "اتصال به شبکه",
                "desc": "سرور مورد نظر را انتخاب کرده و روی دکمه دایره‌ای شناور پایین صفحه (علامت V) بزنید. دکمه به رنگ سبز درآمده و اینترنت بدون فیلتر متصل می‌شود.",
                "tip": "در اولین اتصال، سیستم‌عامل اندروید پیامی جهت تایید ساخت VPN Profile نشان می‌دهد که باید روی OK / تایید بزنید."
            }
        ],
        "troubleshoot": [
            "اگر متصل شد ولی اینترنت رد نشد، ساعت گوشی را روی حالت اتوماتیک (Automatic Time) قرار دهید.",
            "در همراه اول یا ایرانسل اگر قطعی داشتید، از منوی تنظیمات v2rayNG گزینه Fragment را فعال کرده و مقادیر 100-200 را قرار دهید."
        ]
    },
    "hiddify-android": {
        "platform": "android",
        "name": "Hiddify Next (اندروید)",
        "subtitle": "هوشمندترین نرم‌افزار با قابلیت انتخاب خودکار بهترین سرور",
        "badge": "فوق‌العاده آسان",
        "badge_color": "primary",
        "icon": "fas fa-shield-halved",
        "rating": "4.9",
        "downloads": [
            {"title": "دانلود از گوگل‌پلی", "url": "https://play.google.com/store/apps/details?id=app.hiddify.com", "icon": "fab fa-google-play", "btn_class": "btn-primary"},
            {"title": "دانلود مستقیم APK", "url": "https://github.com/hiddify/hiddify-next/releases/latest", "icon": "fas fa-download", "btn_class": "btn-outline-success"}
        ],
        "steps": [
            {
                "step": 1,
                "title": "کپی لینک یا اسکن QR Code",
                "desc": "لینک سابسکریپشن اختصاصی خود را از ربات کپی کنید."
            },
            {
                "step": 2,
                "title": "کلیک روی دکمه افزودن در هیدیفای",
                "desc": "اپلیکیشن Hiddify را باز کنید. خود برنامه به صورت خودکار لینک کپی‌شده را تشخیص داده و با لمس دکمه «Add Profile / افزودن»، سرورها بارگذاری می‌شوند."
            },
            {
                "step": 3,
                "title": "روشن کردن دکمه اتصال",
                "desc": "روی دکمه بزرگ دایره‌ای وسط صفحه بزنید تا برنامه به سریع‌ترین سرور متصل گردد."
            }
        ],
        "troubleshoot": [
            "حالت Bypass LAN and Iran را در تنظیمات فعال کنید تا سایت‌های بانکی بدون فیلترشکن باز شوند."
        ]
    },
    "happ": {
        "platform": "android",
        "name": "Happ",
        "subtitle": "نرم‌افزار مدرن و سبک با رابط کاربری بسیار زیبا",
        "badge": "مدرن و سریع",
        "badge_color": "info",
        "icon": "fas fa-bolt",
        "rating": "4.8",
        "downloads": [
            {"title": "دانلود از گوگل پلی", "url": "https://play.google.com/store/apps/details?id=com.happproxy", "icon": "fab fa-google-play", "btn_class": "btn-info text-white"},
            {"title": "دانلود مستقیم", "url": "https://github.com/happ-proxy/happ/releases", "icon": "fas fa-download", "btn_class": "btn-outline-dark"}
        ],
        "steps": [
            {"step": 1, "title": "کپی کردن لینک", "desc": "لینک اشتراک خود را کپی کنید."},
            {"step": 2, "title": "افزودن پروفایل", "desc": "در اپلیکیشن Happ روی علامت + بالا بزنید و Import from Clipboard را انتخاب کنید."},
            {"step": 3, "title": "اتصال", "desc": "دکمه پاور را برای برقراری ارتباط لمس کنید."}
        ],
        "troubleshoot": []
    },
    "nekobox": {
        "platform": "android",
        "name": "NekoBox",
        "subtitle": "اپلیکیشن حرفه‌ای مبتنی بر هسته قدرتمند Sing-box",
        "badge": "ویژه کاربران حرفه‌ای",
        "badge_color": "secondary",
        "icon": "fas fa-cat",
        "rating": "4.8",
        "downloads": [
            {"title": "دانلود از گیت‌هاب", "url": "https://github.com/MatsuriDayo/NekoBoxForAndroid/releases/latest", "icon": "fab fa-github", "btn_class": "btn-dark"}
        ],
        "steps": [
            {"step": 1, "title": "افزودن لینک ساب", "desc": "وارد بخش Groups شده و New Group بزنید و لینک را پیست کنید."},
            {"step": 2, "title": "بروزرسانی و تست پینگ", "desc": "منوی سه‌نقطه را زده و Update Group را لمس کنید."},
            {"step": 3, "title": "اتصال", "desc": "پایین صفحه دکمه استارت را بزنید."}
        ],
        "troubleshoot": []
    },

    # ─── آیفون و آیپد (iOS) ───
    "streisand": {
        "platform": "ios",
        "name": "Streisand",
        "subtitle": "محبوب‌ترین و کامل‌ترین نرم‌افزار رایگان برای آیفون و آیپد",
        "badge": "پیشنهادی برای iOS (رایگان)",
        "badge_color": "success",
        "icon": "fas fa-paper-plane",
        "rating": "4.9",
        "downloads": [
            {"title": "دانلود رایگان از اپ استور (App Store)", "url": "https://apps.apple.com/app/streisand/id6450534064", "icon": "fab fa-app-store-ios", "btn_class": "btn-primary"}
        ],
        "steps": [
            {
                "step": 1,
                "title": "کپی کردن لینک اتصال",
                "desc": "لینک سابسکریپشن خود را از ربات تلگرام لمس کنید تا کپی شود."
            },
            {
                "step": 2,
                "title": "وارد کردن لینک در Streisand",
                "desc": "نرم‌افزار Streisand را باز کنید. علامت مثبت (+) بالا سمت راست را لمس کنید و گزینه «Import from Clipboard» را انتخاب نمایید."
            },
            {
                "step": 3,
                "title": "بروزرسانی و تست پینگ",
                "desc": "روی ردیف سرورها به سمت پایین بکشید (Pull to Refresh) یا دکمه بروزرسانی را بزنید. پینگ کانفیگ‌ها به رنگ سبز نمایش داده می‌شود."
            },
            {
                "step": 4,
                "title": "روشن کردن دکمه اتصال",
                "desc": "سرور با کمترین پینگ را لمس کرده و دکمه اتصال بزرگ بالای صفحه را روشن کنید. در پنجره باز شده روی Allow بزنید و پسورد یا FaceID آیفون را تایید کنید."
            }
        ],
        "troubleshoot": [
            "حتماً در تنظیمات آیفون (Settings > General > Date & Time) گزینه Set Automatically را روشن کنید.",
            "اگر سرورها لود نشدند یک بار آیفون را روی حالت پرواز (Airplane Mode) برده و برگردانید."
        ]
    },
    "foxray-ios": {
        "platform": "ios",
        "name": "FoXray",
        "subtitle": "اپلیکیشن پایدار، سریع و بدون قطعی برای سیستم‌عامل iOS",
        "badge": "رایگان و مطمئن",
        "badge_color": "info",
        "icon": "fas fa-shield-cat",
        "rating": "4.8",
        "downloads": [
            {"title": "دریافت از App Store", "url": "https://apps.apple.com/app/foxray/id6448898396", "icon": "fab fa-app-store-ios", "btn_class": "btn-dark"}
        ],
        "steps": [
            {"step": 1, "title": "کپی لینک یا اسکن QR", "desc": "لینک اشتراک را کپی کنید یا QR Code را با دوربین FoXray اسکن کنید."},
            {"step": 2, "title": "افزودن سابسکریپشن", "desc": "علامت + را بزنید و گزینه Clipboard را لمس نمایید."},
            {"step": 3, "title": "اتصال", "desc": "دکمه Play پایین صفحه را برای برقراری اتصال بزنید."}
        ],
        "troubleshoot": []
    },
    "v2box": {
        "platform": "ios",
        "name": "V2Box",
        "subtitle": "رابط کاربری ساده با قابلیت تفکیک آسان سرورها",
        "badge": "رایگان",
        "badge_color": "secondary",
        "icon": "fas fa-box-open",
        "rating": "4.7",
        "downloads": [
            {"title": "دریافت از App Store", "url": "https://apps.apple.com/app/v2box-v2ray-client/id6446814690", "icon": "fab fa-app-store-ios", "btn_class": "btn-primary"}
        ],
        "steps": [
            {"step": 1, "title": "کپی کردن لینک", "desc": "لینک ساب را کپی کنید."},
            {"step": 2, "title": "افزودن در تب Configs", "desc": "به تب Configs رفته، علامت + را بزنید و Add Subscription را لمس کنید."},
            {"step": 3, "title": "اتصال در تب Home", "desc": "به تب Home رفته و دکمه Slide to Connect را بکشید."}
        ],
        "troubleshoot": []
    },
    "shadowrocket": {
        "platform": "ios",
        "name": "Shadowrocket",
        "subtitle": "قدرتمندترین کلاینت برای iOS (پولی در اپ‌استور)",
        "badge": "حرفه‌ای و تخصصی",
        "badge_color": "warning",
        "icon": "fas fa-shuttle-space",
        "rating": "5.0",
        "downloads": [
            {"title": "صفحه نرم‌افزار در App Store ($2.99)", "url": "https://apps.apple.com/app/shadowrocket/id932747118", "icon": "fab fa-app-store-ios", "btn_class": "btn-outline-primary"}
        ],
        "steps": [
            {"step": 1, "title": "افزودن لینک", "desc": "برنامه را باز کنید و در پنجره باز شده روی Add کلیک کنید یا علامت + را بزنید."},
            {"step": 2, "title": "تست پینگ", "desc": "روی Ping Test بزنید تا سرورها تست شوند."},
            {"step": 3, "title": "اتصال", "desc": "دکمه سوئیچ بالای صفحه را فعال کنید."}
        ],
        "troubleshoot": []
    },
    "singbox-ios": {
        "platform": "ios",
        "name": "Sing-box (iOS)",
        "subtitle": "کلاینت رسمی و بسیار سبک هسته Sing-box",
        "badge": "فوق سبک",
        "badge_color": "dark",
        "icon": "fas fa-cube",
        "rating": "4.7",
        "downloads": [
            {"title": "دریافت از App Store", "url": "https://apps.apple.com/app/sing-box/id6451272673", "icon": "fab fa-app-store-ios", "btn_class": "btn-dark"}
        ],
        "steps": [
            {"step": 1, "title": "پروفایل سابسکریپشن", "desc": "وارد بخش Profiles شده و لینک اشتراک را اضافه کنید."},
            {"step": 2, "title": "اتصال", "desc": "در صفحه اصلی دکمه Start را بزنید."}
        ],
        "troubleshoot": []
    },

    # ─── ویندوز ───
    "hiddify-windows": {
        "platform": "windows",
        "name": "Hiddify Next (ویندوز)",
        "subtitle": "ساده‌ترین و کارآمدترین برنامه ویندوز با حالت TUN اختصاصی",
        "badge": "پیشنهادی ویندوز",
        "badge_color": "success",
        "icon": "fas fa-desktop",
        "rating": "4.9",
        "downloads": [
            {"title": "دانلود نسخه نصبی (Windows Setup)", "url": "https://github.com/hiddify/hiddify-next/releases/latest", "icon": "fab fa-windows", "btn_class": "btn-primary"},
            {"title": "دانلود نسخه پرتابل (بدون نیاز به نصب)", "url": "https://github.com/hiddify/hiddify-next/releases/latest", "icon": "fas fa-file-zipper", "btn_class": "btn-outline-dark"}
        ],
        "steps": [
            {
                "step": 1,
                "title": "نصب و اجرای برنامه",
                "desc": "فایل نصبی را دانلود و روی ویندوز اجرا کنید تا نرم‌افزار باز شود."
            },
            {
                "step": 2,
                "title": "افزودن لینک اشتراک",
                "desc": "لینک اشتراک خود را کپی کرده و روی علامت مثبت (+) بالای صفحه نرم‌افزار کلیک کنید. کانفیگ‌ها بارگذاری می‌شوند."
            },
            {
                "step": 3,
                "title": "فعال‌سازی TUN Mode و اتصال",
                "desc": "گزینه TUN Mode را در برنامه روشن نگه دارید (تا تمام برنامه‌ها، مرورگرها و بازی‌ها از فیلترشکن عبور کنند) و روی دکمه بزرگ دایره‌ای کلیک کنید."
            }
        ],
        "troubleshoot": [
            "اگر ارور فایروال ظاهر شد، در کادر ویندوز روی Allow Access کلیک کنید.",
            "در صورت عدم اتصال، در تنظیمات ساعت ویندوز روی Sync Now بزنید."
        ]
    },
    "v2rayn": {
        "platform": "windows",
        "name": "v2rayN",
        "subtitle": "کلاینت کلاسیک و قدرتمند با پایداری بسیار بالا در ویندوز",
        "badge": "پایدار و باسابقه",
        "badge_color": "info",
        "icon": "fas fa-network-wired",
        "rating": "4.8",
        "downloads": [
            {"title": "دانلود جدیدترین نسخه با هسته کامل (With-Core)", "url": "https://github.com/2dust/v2rayN/releases/latest", "icon": "fab fa-github", "btn_class": "btn-dark"}
        ],
        "steps": [
            {"step": 1, "title": "استخراج فایل فشرده", "desc": "فایل فشرده دانلود شده را از حالت زیپ خارج کرده و فایل v2rayN.exe را اجرا کنید."},
            {"step": 2, "title": "افزودن سابسکریپشن", "desc": "از منوی بالای نرم‌افزار روی Subscription Group کلیک کرده و Add را بزنید. نام دلخواه و لینک ساب را در کادر url وارد کرده و تایید کنید."},
            {"step": 3, "title": "بروزرسانی سرورها", "desc": "روی Subscription Group کلیک کرده و Update Subscription without Proxy را بزنید تا سرورها اضافه شوند."},
            {"step": 4, "title": "اتصال سراسری", "desc": "پایین صفحه گزینه System Proxy را روی Set System Proxy قرار دهید و سرور مورد نظر را انتخاب کرده و Enter بزنید."}
        ],
        "troubleshoot": []
    },
    "nekoray-win": {
        "platform": "windows",
        "name": "Nekoray (ویندوز)",
        "subtitle": "مناسب گیمرها، پینگ پایین با پروتکل‌های نوین Sing-box",
        "badge": "ویژه بازی و پینگ پایین",
        "badge_color": "danger",
        "icon": "fas fa-gamepad",
        "rating": "4.9",
        "downloads": [
            {"title": "دانلود از گیت‌هاب", "url": "https://github.com/MatsuriDayo/nekoray/releases/latest", "icon": "fab fa-github", "btn_class": "btn-dark"}
        ],
        "steps": [
            {"step": 1, "title": "افزودن سرورها", "desc": "نرم‌افزار را اجرا کرده و کلید میانبر Ctrl + V را بزنید تا کانفیگ‌ها وارد شوند."},
            {"step": 2, "title": "فعال‌سازی حالت TUN", "desc": "تیک گزینه TUN Mode را بالای صفحه فعال کنید."},
            {"step": 3, "title": "اتصال", "desc": "روی سرور راست کلیک کرده و Start را بزنید."}
        ],
        "troubleshoot": []
    },
    "clash-verge": {
        "platform": "windows",
        "name": "Clash Verge",
        "subtitle": "کلاینت مدرن Clash با تفکیک هوشمند ترافیک",
        "badge": "مدرن",
        "badge_color": "secondary",
        "icon": "fas fa-sliders",
        "rating": "4.8",
        "downloads": [
            {"title": "دانلود از گیت‌هاب", "url": "https://github.com/clash-verge-rev/clash-verge-rev/releases/latest", "icon": "fab fa-github", "btn_class": "btn-dark"}
        ],
        "steps": [
            {"step": 1, "title": "افزودن ساب", "desc": "وارد تب Profiles شده و لینک ساب را در کادر بالا پیست و Import بزنید."},
            {"step": 2, "title": "اتصال", "desc": "در تب Proxies سرور دلخواه را انتخاب کرده و System Proxy را روشن کنید."}
        ],
        "troubleshoot": []
    },

    # ─── اندروید تی‌وی (Android TV) ───
    "v2rayng-tv": {
        "platform": "tv",
        "name": "v2rayNG (نسخه تلویزیون)",
        "subtitle": "سازگار با ریموت کنترل تلویزیون‌های هوشمند و تی‌وی‌باکس‌ها",
        "badge": "پیشنهادی تلویزیون",
        "badge_color": "danger",
        "icon": "fas fa-tv",
        "rating": "4.9",
        "downloads": [
            {"title": "دانلود فایل APK مخصوص تلویزیون", "url": "https://github.com/2dust/v2rayNG/releases/latest", "icon": "fas fa-download", "btn_class": "btn-danger"}
        ],
        "steps": [
            {
                "step": 1,
                "title": "انتقال فایل نصبی به تلویزیون",
                "desc": "فایل APK برنامه v2rayNG را دانلود کرده و با فلش مموری (USB) یا برنامه Send Files to TV به تلویزیون منتقل و نصب کنید."
            },
            {
                "step": 2,
                "title": "انتقال کانفیگ با QR Code یا لینک ساب",
                "desc": "برنامه را در تلویزیون باز کنید. علامت مثبت (+) را با ریموت انتخاب کنید و گزینه Scan QR Code را بزنید (با وب‌کم تلویزیون) یا با کیبورد مجازی لینک اشتراک را در بخش Subscription Group وارد کنید."
            },
            {
                "step": 3,
                "title": "استارت و تماشای یوتیوب و شبکه‌ها",
                "desc": "سرور را با ریموت انتخاب کرده و دکمه اتصال را بزنید. اکنون تمام برنامه‌های تلویزیون شامل YouTube، فیلیمو و ماهواره اینترنتی بدون قطعی در دسترس هستند."
            }
        ],
        "troubleshoot": [
            "برای باز شدن بدون مشکل برنامه‌های ایرانی تلویزیون (مانند نماوا و روبیکا)، گزینه Bypass LAN and Iran را در تنظیمات v2rayNG فعال نگه دارید."
        ]
    },
    "hiddify-tv": {
        "platform": "tv",
        "name": "Hiddify TV",
        "subtitle": "محیط اختصاصی بهینه‌سازی شده برای صفحه‌نمایش‌های بزرگ خانگی",
        "badge": "سریع و زیبا",
        "badge_color": "primary",
        "icon": "fas fa-display",
        "rating": "4.8",
        "downloads": [
            {"title": "دانلود نسخه اندروید تی‌وی", "url": "https://github.com/hiddify/hiddify-next/releases/latest", "icon": "fas fa-download", "btn_class": "btn-primary"}
        ],
        "steps": [
            {"step": 1, "title": "نصب برنامه", "desc": "برنامه را روی تلویزیون نصب کنید."},
            {"step": 2, "title": "اسکن QR Code", "desc": "بارکد کانفیگ دریافتی از ربات را در صفحه برنامه اسکن کنید."},
            {"step": 3, "title": "اتصال", "desc": "دکمه اتصال را با ریموت بزنید."}
        ],
        "troubleshoot": []
    },
    "spark-tv": {
        "platform": "tv",
        "name": "Spark TV",
        "subtitle": "کلاینت سبک ویژه پخش استریم و یوتیوب در تلویزیون",
        "badge": "ویژه استریم",
        "badge_color": "secondary",
        "icon": "fas fa-play",
        "rating": "4.7",
        "downloads": [
            {"title": "دریافت فایل نصبی", "url": "https://github.com", "icon": "fas fa-download", "btn_class": "btn-dark"}
        ],
        "steps": [
            {"step": 1, "title": "وارد کردن لینک", "desc": "لینک را وارد کنید و Connect را بزنید."}
        ],
        "troubleshoot": []
    },

    # ─── مک‌بوک و مک (macOS) ───
    "foxray-mac": {
        "platform": "macos",
        "name": "FoXray (macOS)",
        "subtitle": "بهترین کلاینت برای سیستم‌های مک با پردازنده‌های M1/M2/M3 و اینتل",
        "badge": "پیشنهادی مک",
        "badge_color": "success",
        "icon": "fab fa-apple",
        "rating": "4.9",
        "downloads": [
            {"title": "دانلود از Mac App Store", "url": "https://apps.apple.com/app/foxray/id6448898396", "icon": "fab fa-apple", "btn_class": "btn-dark"}
        ],
        "steps": [
            {"step": 1, "title": "کپی لینک", "desc": "لینک اشتراک خود را کپی کنید."},
            {"step": 2, "title": "افزودن به FoXray", "desc": "برنامه را باز کرده و علامت + را بزنید و Clipboard را انتخاب کنید."},
            {"step": 3, "title": "اتصال", "desc": "دکمه Play را کلیک کرده و دسترسی VPN Profile را تایید کنید."}
        ],
        "troubleshoot": []
    },
    "hiddify-mac": {
        "platform": "macos",
        "name": "Hiddify Next (macOS)",
        "subtitle": "نرم‌افزار همه‌منظوره با اتصال سراسری سیستم در مک",
        "badge": "رایگان و ساده",
        "badge_color": "primary",
        "icon": "fas fa-laptop",
        "rating": "4.8",
        "downloads": [
            {"title": "دانلود فایل DMG برای مک", "url": "https://github.com/hiddify/hiddify-next/releases/latest", "icon": "fas fa-download", "btn_class": "btn-primary"}
        ],
        "steps": [
            {"step": 1, "title": "نصب فایل DMG", "desc": "فایل را در فولدر Applications کپی کرده و باز کنید."},
            {"step": 2, "title": "افزودن لینک", "desc": "روی علامت + کلیک کنید تا لینک کپی شده اضافه شود."},
            {"step": 3, "title": "اتصال", "desc": "دکمه اتصال را بزنید."}
        ],
        "troubleshoot": []
    },
    "v2rayu": {
        "platform": "macos",
        "name": "V2rayU",
        "subtitle": "کلاینت کم‌حجم در نوار منوبار مک",
        "badge": "کلاسیک",
        "badge_color": "secondary",
        "icon": "fas fa-bars",
        "rating": "4.7",
        "downloads": [
            {"title": "دانلود از گیت‌هاب", "url": "https://github.com/yanue/V2rayU/releases", "icon": "fab fa-github", "btn_class": "btn-outline-dark"}
        ],
        "steps": [
            {"step": 1, "title": "افزودن سابسکریپشن", "desc": "از آیکون نوار منوبار گزینه Subscription Setting را بزنید و لینک را وارد کنید."},
            {"step": 2, "title": "اتصال", "desc": "حالت Global Mode را انتخاب کرده و Turn on V2rayU را بزنید."}
        ],
        "troubleshoot": []
    },

    # ─── لینوکس ───
    "v2raya": {
        "platform": "linux",
        "name": "v2rayA",
        "subtitle": "کلاینت قدرتمند تحت وب با قابلیت روتینگ کل سیستم",
        "badge": "پیشنهادی لینوکس",
        "badge_color": "success",
        "icon": "fab fa-linux",
        "rating": "4.9",
        "downloads": [
            {"title": "راهنمای نصب از مخازن گیت‌هاب", "url": "https://github.com/v2rayA/v2rayA", "icon": "fab fa-github", "btn_class": "btn-dark"}
        ],
        "steps": [
            {"step": 1, "title": "اجرای سرویس", "desc": "دستور `sudo systemctl start v2raya` را اجرا کنید."},
            {"step": 2, "title": "ورود به پنل وب", "desc": "در مرورگر آدرس `http://localhost:2017` را باز کنید."},
            {"step": 3, "title": "وارد کردن لینک و اتصال", "desc": "دکمه Import را زده و لینک ساب را پیست کنید و Start را بزنید."}
        ],
        "troubleshoot": []
    },
    "nekoray-linux": {
        "platform": "linux",
        "name": "Nekoray (لینوکس)",
        "subtitle": "رابط کاربری گرافیکی با هسته Sing-box برای اوبونتو و دبیان",
        "badge": "محیط گرافیکی (GUI)",
        "badge_color": "info",
        "icon": "fas fa-window-maximize",
        "rating": "4.8",
        "downloads": [
            {"title": "دانلود فایل AppImage", "url": "https://github.com/MatsuriDayo/nekoray/releases/latest", "icon": "fas fa-download", "btn_class": "btn-info text-white"}
        ],
        "steps": [
            {"step": 1, "title": "اجرا و افزودن لینک", "desc": "فایل AppImage را اجرا کرده و کلیدهای Ctrl + V را بزنید."},
            {"step": 2, "title": "فعال‌سازی TUN و استارت", "desc": "تیک TUN Mode را فعال کرده و سرور را انتخاب نمایید."}
        ],
        "troubleshoot": []
    },

    # ─── مودم و روترها ───
    "openwrt": {
        "platform": "router",
        "name": "OpenWrt (PassWall / SSR-Plus)",
        "subtitle": "آزادسازی کل اینترنت خانه و محل کار روی مودم و وای‌فای",
        "badge": "حرفه‌ای‌ترین روش",
        "badge_color": "purple",
        "icon": "fas fa-wifi",
        "rating": "5.0",
        "downloads": [
            {"title": "مخزن افزونه PassWall در گیت‌هاب", "url": "https://github.com/xiaorouji/openwrt-passwall", "icon": "fab fa-github", "btn_class": "btn-dark"}
        ],
        "steps": [
            {
                "step": 1,
                "title": "ورود به پنل مودم OpenWrt",
                "desc": "در مرورگر کامپیوتر یا گوشی آدرس آی‌پی مودم خود (معمولاً 192.168.1.1) را وارد کرده و لاگین کنید."
            },
            {
                "step": 2,
                "title": "رفتن به بخش PassWall / SSR-Plus",
                "desc": "از منوی خدمات (Services) وارد گزینه PassWall یا SSR-Plus شوید و به تب «Node List / سابسکریپشن» بروید."
            },
            {
                "step": 3,
                "title": "افزودن لینک سابسکریپشن",
                "desc": "روی Add کلیک کنید، لینک سابسکریپشن دریافتی از ربات را در کادر Subscribe URL قرار دهید و Save & Apply بزنید."
            },
            {
                "step": 4,
                "title": "بروزرسانی نودها و فعال‌سازی سراسری",
                "desc": "دکمه Update All Nodes را بزنید. در صفحه اصلی افزونه سرور دلخواه را انتخاب کرده و وضعیت را روی Enabled بگذارید. از این پس هر دستگاهی (گوشی، لپ‌تاپ، پلی‌استیشن، تلویزیون، آیفون) به وای‌فای وصل شود بدون نیاز به فیلترشکن به اینترنت آزاد متصل است!"
            }
        ],
        "troubleshoot": [
            "برای عدم ایجاد تداخل در بازی‌های آنلاین یا بانک‌ها، حالت روتینگ را روی GFWList یا China/Iran Bypass بگذارید."
        ]
    },
    "mikrotik": {
        "platform": "router",
        "name": "MikroTik RouterOS",
        "subtitle": "اتصال روترهای حرفه‌ای میکروتیک با WireGuard یا Socks5",
        "badge": "شبکه‌های شرکتی",
        "badge_color": "secondary",
        "icon": "fas fa-server",
        "rating": "4.9",
        "downloads": [
            {"title": "مستندات رسمی RouterOS", "url": "https://help.mikrotik.com", "icon": "fas fa-book", "btn_class": "btn-outline-dark"}
        ],
        "steps": [
            {"step": 1, "title": "تنظیم Interface", "desc": "در WinBox وارد بخش WireGuard یا IP > SOCKS شوید."},
            {"step": 2, "title": "افزودن Peer و IP Route", "desc": "مشخصات سرور را اضافه کرده و روت پیش‌فرض ترافیک را به سمت اینترفیس هدایت کنید."}
        ],
        "troubleshoot": []
    },
    "asuswrt": {
        "platform": "router",
        "name": "Asuswrt-Merlin",
        "subtitle": "استفاده از قابلیت VPN Fusion در روترهای ایسوس",
        "badge": "روترهای ایسوس",
        "badge_color": "info",
        "icon": "fas fa-network-wired",
        "rating": "4.8",
        "downloads": [
            {"title": "سایت رسمی فریمور مرلین", "url": "https://www.asuswrt-merlin.net/", "icon": "fas fa-globe", "btn_class": "btn-info text-white"}
        ],
        "steps": [
            {"step": 1, "title": "ورود به تب VPN Fusion", "desc": "در پنل روتر به بخش VPN > VPN Fusion بروید."},
            {"step": 2, "title": "افزودن کانفیگ", "desc": "کانفیگ اختصاصی را اضافه کرده و دستگاه‌های مورد نظر را به آن اختصاص دهید."}
        ],
        "troubleshoot": []
    }
}

TROUBLESHOOTING_GUIDES = [
    {
        "slug": "time_desync",
        "title": "خطای عدم تطابق ساعت سیستم (System Time Desync Error)",
        "subtitle": "علت ۹۰٪ خطاهای اتصال در پروتکل‌های امن VLESS و VMess",
        "icon": "fas fa-clock",
        "color": "danger",
        "problem": "پیام خطای `invalid user` یا پینگ بی‌پاسخ علی‌رغم سالم بودن اشتراک.",
        "cause": "پروتکل‌های نسل جدید برای حفظ امنیت از سیستم توکن زمانی بر پایه ثانیه استفاده می‌کنند. اگر ساعت گوشی یا سیستم شما حتی ۲ دقیقه با ساعت جهانی اختلاف داشته باشد، اتصال توسط سرور رد می‌شود.",
        "solution_steps": [
            "**در گوشی اندروید:** وارد Settings > System / General Management > Date & Time شوید و گزینه‌های `Set Automatically` و `Automatic Time Zone` را خاموش و مجدداً روشن کنید.",
            "**در آیفون (iOS):** وارد Settings > General > Date & Time شوید و تیک `Set Automatically` را فعال کنید.",
            "**در ویندوز:** روی ساعت گوشه پایین کلیک راست کرده و Adjust Date/Time را بزنید؛ سپس روی دکمه `Sync now` کلیک نمایید."
        ]
    },
    {
        "slug": "fragmentation",
        "title": "فیلترینگ شدید اپراتورها (همراه اول، ایرانسل، مخابرات، رایتل)",
        "subtitle": "دور زدن فیلترینگ شدید با قابلیت تکه‌تکه کردن پکت‌های اینترنت (Fragment)",
        "icon": "fas fa-shield-virus",
        "color": "warning",
        "problem": "در اپراتورهایی مثل همراه اول یا ایرانسل کانفیگ متصل می‌شود اما سرعت بسیار پایین است یا بعد از چند ثانیه قطع می‌شود.",
        "cause": "سیستم فیلترینگ با ابزارهای DPI بسته اولیه درخواست (TLS Client Hello) را شناسایی و مسدود می‌کند.",
        "solution_steps": [
            "**در v2rayNG:** وارد منوی کشویی سمت چپ > Settings شوید. به بخش `Fragment` بروید و تیک آن را روشن کنید. مقدار packets را روی `100-200` و length را روی `10-20` بگذارید.",
            "**در Hiddify:** وارد تنظیمات برنامه شوید و بخش `Fragmentation` را روی حالت `tlshello` یا `random` تنظیم کنید.",
            "یک بار سرورها را تست پینگ بگیرید و متصل شوید."
        ]
    },
    {
        "slug": "bypass_iran",
        "title": "عدم باز شدن سایت‌های بانکی و ایرانی (Bypass Iran)",
        "subtitle": "استفاده همزمان از اینترنت بدون فیلتر و برنامه‌های بانکی بدون نیاز به خاموش کردن VPN",
        "icon": "fas fa-building-columns",
        "color": "success",
        "problem": "هنگامی که فیلترشکن روشن است، برنامه‌هایی مثل همراه بانک، اسنپ، دیجی‌کالا یا سامانه‌های دولتی باز نمی‌شوند.",
        "cause": "سایت‌های ایرانی برای امنیت بیشتر، آی‌پی‌های خارج از کشور را مسدود می‌کنند.",
        "solution_steps": [
            "**در v2rayNG:** وارد Settings شوید > گزینه `Routing Rules` یا قوانین مسیریابی را روی حالت `Bypass LAN and Iran` یا «عبور آدرس‌های محلی و ایران» قرار دهید.",
            "**در Hiddify:** در پایین صفحه اصلی، گزینه حالت روتینگ را روی `Bypass LAN and Iran` بگذارید.",
            "**در Streisand (آیفون):** در تب Settings گزینه `Bypass Iran` را روشن کنید.",
            "اکنون ترافیک سایت‌های ایرانی مستقیماً از اینترنت ملی عبور کرده و فیلترشکن برای سایر سایت‌ها فعال می‌ماند."
        ]
    },
    {
        "slug": "dns_leak_ping",
        "title": "خطای DNS و باز نشدن صفحات (Ping Timeout / DNS Error)",
        "subtitle": "رفع مشکل مسموم‌سازی DNS توسط شرکت‌های ارائه‌دهنده اینترنت",
        "icon": "fas fa-globe",
        "color": "info",
        "problem": "فیلترشکن متصل است و پینگ سبز نشان می‌دهد، اما هیچ صفحه‌ای در مرورگر باز نمی‌شود.",
        "cause": "اختلال در سرورهای DNS پیش‌فرض اپراتور اینترنت.",
        "solution_steps": [
            "در تنظیمات نرم‌افزار VPN خود وارد بخش DNS شوید.",
            "DNS سرور راه دور (Remote DNS) را روی `https://1.1.1.1/dns-query` (کلودفلر) یا `https://dns.google/dns-query` (گوگل) قرار دهید.",
            "یک بار برنامه را قطع و مجدداً متصل نمایید."
        ]
    },
    {
        "slug": "windows_firewall",
        "title": "مسدود شدن پورت توسط فایروال یا آنتی‌ویروس در ویندوز",
        "subtitle": "رفع ارورهای Bind Port و مسدودی شبکه در کامپیوتر",
        "icon": "fab fa-windows",
        "color": "secondary",
        "problem": "در ویندوز ارور `Port occupied` یا `Failed to start core` دریافت می‌شود.",
        "cause": "اشغال بودن پورت 10808/2080 توسط برنامه‌های دیگر یا مسدودی هسته توسط Windows Defender.",
        "solution_steps": [
            "پنجره Windows Defender Security را باز کرده و در بخش Protection History روی فایل هسته v2rayN یا Hiddify گزینه `Allow on device` را بزنید.",
            "در v2rayN از منوی Settings پورت لوکال (Local SOCKS Port) را از 10808 به 10809 یا 20808 تغییر دهید.",
            "برنامه را به صورت Run as administrator اجرا نمایید."
        ]
    }
]
