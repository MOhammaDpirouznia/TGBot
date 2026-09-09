"""
موتور و ساختار داده‌های آموزشی و عیب‌یابی چندسکویی (Interactive VPN Guides & Troubleshooting Data)
پوشش جامع: اندروید، تلویزیون هوشمند (Android TV)، آیفون و آیپد (iOS)، ویندوز، مک، لینوکس، مودم و روترها
طراحی شده بر اساس استانداردهای برترین سامانه‌های VPN و پروتکل‌های نوین (VLESS, VMess, Trojan, ShadowTLS, Reality, Sing-box)
"""

PLATFORMS = {
    "android": {
        "title": "اندروید (Android)",
        "icon": "fab fa-android",
        "color": "#3ddc84",
        "description": "گوشی‌ها و تبلت‌های سامسونگ، شیائومی، هواوی، موتورولا و کلیه دستگاه‌های اندرویدی",
        "apps": ["v2rayng", "hiddify-android", "happ", "nekobox"]
    },
    "ios": {
        "title": "آیفون و آیپد (iOS)",
        "icon": "fab fa-apple",
        "color": "#000000",
        "description": "گوشی‌های آیفون و تبلت‌های آیپد با سیستم‌عامل iOS و iPadOS (نسخه ۱۴ به بالا)",
        "apps": ["streisand", "foxray-ios", "v2box", "shadowrocket", "singbox-ios"]
    },
    "windows": {
        "title": "ویندوز (Windows)",
        "icon": "fab fa-windows",
        "color": "#0078d4",
        "description": "رایانه‌ها و لپ‌تاپ‌های دارای سیستم‌عامل ویندوز ۱۰ و ۱۱ (نسخه‌های 64 بیتی و 32 بیتی)",
        "apps": ["v2rayn", "hiddify-windows", "nekoray-win", "clash-verge"]
    },
    "tv": {
        "title": "اندروید تی‌وی (Android TV)",
        "icon": "fas fa-tv",
        "color": "#e11d48",
        "description": "تلویزیون‌های هوشمند سونی، شیائومی، تی‌سی‌ال، اسنوا، دوو، جی‌پلاس و کلیه اندروید‌باکس‌ها",
        "apps": ["v2rayng-tv", "hiddify-tv", "spark-tv"]
    },
    "macos": {
        "title": "مک‌بوک و مک (macOS)",
        "icon": "fas fa-laptop",
        "color": "#64748b",
        "description": "لپ‌تاپ‌های مک‌بوک و رایانه‌های آی‌مک اپل (پردازنده‌های Apple Silicon سری M و اینتل)",
        "apps": ["foxray-mac", "hiddify-mac", "v2rayu"]
    },
    "linux": {
        "title": "لینوکس (Linux)",
        "icon": "fab fa-linux",
        "color": "#f59e0b",
        "description": "توزیع‌های لینوکس اوبونتو (Ubuntu)، دبیان، فدورا، آرچ و سرورهای توزیع‌شده",
        "apps": ["v2raya", "nekoray-linux"]
    },
    "router": {
        "title": "مودم و روتر (Modem / Router)",
        "icon": "fas fa-network-wired",
        "color": "#8b5cf6",
        "description": "آزادسازی کل شبکه اینترنت خانه و محل کار بر روی مودم، روتر و اکسس‌پوینت",
        "apps": ["openwrt", "mikrotik", "asuswrt"]
    }
}

TUTORIALS = {
    # ─── اندروید (Android) ───
    "v2rayng": {
        "platform": "android",
        "name": "v2rayNG",
        "subtitle": "پراستفاده‌ترین و سازگارترین نرم‌افزار اندروید با قابلیت پشتیبانی از تمام پروتکل‌ها و فرگمنت",
        "badge": "پیشنهادی اندروید (پایدار)",
        "badge_color": "success",
        "icon": "fas fa-rocket",
        "rating": "4.9",
        "downloads": [
            {"title": "دانلود مستقیم نسخه APK (پیشنهادی)", "url": "https://github.com/2dust/v2rayNG/releases/latest", "icon": "fas fa-download", "btn_class": "btn-success"},
            {"title": "دریافت از Google Play", "url": "https://play.google.com/store/apps/details?id=com.v2ray.ang", "icon": "fab fa-google-play", "btn_class": "btn-outline-primary"},
            {"title": "صفحه رسمی گیت‌هاب", "url": "https://github.com/2dust/v2rayNG/releases", "icon": "fab fa-github", "btn_class": "btn-outline-dark"}
        ],
        "steps": [
            {
                "step": 1,
                "title": "کپی کردن لینک اشتراک هوشمند",
                "desc": "در ربات تلگرام یا پنل کاربری خود، روی لینک اشتراک (سابسکریپشن) کلیک کنید تا در حافظه موقت (Clipboard) کپی شود.",
                "tip": "لینک‌های سابسکریپشن کامل‌تر از تک کانفیگ هستند و با تغییر سرورها به شکل خودکار به‌روز می‌شوند."
            },
            {
                "step": 2,
                "title": "تعریف گروه اشتراک در برنامه (روش اصولی)",
                "desc": "اپلیکیشن v2rayNG را باز کنید. روی آیکون منوی همبرگری (سه خط سمت چپ بالا) ضربه بزنید و وارد گزینه «Subscription group setting» (تنظیمات گروه اشتراک) شوید. سپس علامت مثبت (+) بالای صفحه را بزنید.",
                "tip": "در فیلد Remarks یک اسم دلخواه مانند 'VIP' بگذارید و در فیلد Subscription URL لینک کپی‌شده را قرار دهید و تیک تایید بالای صفحه را بزنید."
            },
            {
                "step": 3,
                "title": "به‌روزرسانی سرورها و دریافت لیست کانفیگ‌ها",
                "desc": "به صفحه اصلی نرم‌افزار برگردید. روی آیکون سه‌نقطه در گوشه بالا سمت راست ضربه بزنید و گزینه «Update subscription» (به‌روزرسانی اشتراک) را انتخاب کنید. چند ثانیه منتظر بمانید تا کلیه سرورها با پرچم و اسامی بارگذاری شوند.",
                "tip": "اگر از قبل با فیلترشکن دیگری متصل نیستید، حتماً گزینه بدون پروکسی (Update subscription without proxy) را لمس فرمایید."
            },
            {
                "step": 4,
                "title": "تست پینگ واقعی (Real Delay Test)",
                "desc": "مجدداً منوی سه‌نقطه بالا سمت راست را لمس کرده و گزینه «Real delay all configuration» را انتخاب کنید. پس از چند لحظه پینگ عددی سرورها به رنگ سبز نمایش داده می‌شود.",
                "tip": "سروری که کمترین عدد پینگ سبز رنگ (مثلاً 180ms یا 250ms) را دارد بهترین سرعت و کمترین اختلال را ارائه می‌دهد. از انتخاب سرورهای با خطای -1 خودداری کنید."
            },
            {
                "step": 5,
                "title": "اتصال و تایید مجوز امنیتی سیستم‌عامل",
                "desc": "سرور سبز رنگ مورد نظر را لمس کنید تا نوار کناری آن برجسته شود. سپس روی دکمه دایره‌ای بزرگ شناور پایین صفحه (علامت V) کلیک کنید. دکمه به رنگ سبز درآمده و وضعیت اتصال به Connected تغییر می‌یابد.",
                "tip": "در اولین مرتبه اتصال، پنجره تایید ساخت تونل امن VPN در گوشی ظاهر می‌شود که حتماً روی OK یا 'تایید' ضربه بزنید."
            }
        ],
        "troubleshoot": [
            "برای همراه اول و ایرانسل: وارد Settings برنامه شوید > بخش Fragment را فعال کرده و packets را 1-3 و length را 10-20 بگذارید.",
            "برای باز شدن بانک‌ها و سایت‌های ایرانی: در Settings گزینه Routing Rules را روی Bypass LAN and Iran قرار دهید.",
            "در صورت خطای Invalid User یا پینگ -1: تاریخ و ساعت گوشی را از Settings > General Management > Date & Time در حالت اتوماتیک قرار دهید.",
            "تغییر DNS: در Settings بخش Remote DNS را روی https://1.1.1.1/dns-query بگذارید تا اختلال DNS اپراتور رفع شود."
        ]
    },
    "hiddify-android": {
        "platform": "android",
        "name": "Hiddify (اندروید)",
        "subtitle": "نرم‌افزار نسل جدید با رابط کاربری فارسی، هوشمند، ضد فیلتر و مبتنی بر هسته سریع Sing-box",
        "badge": "فوق‌العاده ساده و فارسی",
        "badge_color": "primary",
        "icon": "fas fa-shield-halved",
        "rating": "4.9",
        "downloads": [
            {"title": "دانلود فایل نصبی مستقیم APK", "url": "https://github.com/hiddify/hiddify-next/releases/latest", "icon": "fas fa-download", "btn_class": "btn-primary"},
            {"title": "نصب از Google Play", "url": "https://play.google.com/store/apps/details?id=app.hiddify.com", "icon": "fab fa-google-play", "btn_class": "btn-outline-primary"},
            {"title": "مخزن رسمی گیت‌هاب", "url": "https://github.com/hiddify/hiddify-next/releases", "icon": "fab fa-github", "btn_class": "btn-outline-dark"}
        ],
        "steps": [
            {
                "step": 1,
                "title": "کپی کردن لینک سابسکریپشن",
                "desc": "لینک اشتراک دریافتی از ربات را لمس کنید تا در کلیپ‌بورد کپی شود.",
                "tip": "نرم‌افزار هیدیفای به شکل هوشمند به محض باز شدن کلیپ‌بورد شما را بررسی می‌کند."
            },
            {
                "step": 2,
                "title": "افزودن پروفایل جدید (New Profile)",
                "desc": "نرم‌افزار Hiddify را باز کنید. روی علامت مثبت (+) بالا سمت چپ یا دکمه «پروفایل جدید» ضربه بزنید و گزینه «افزودن از کلیپ‌بورد» (Add from Clipboard) را انتخاب کنید.",
                "tip": "همچنین می‌توانید با لمس آیکون اسکنر، بارکد QR ارائه‌شده در پنل کاربری را اسکن کنید."
            },
            {
                "step": 3,
                "title": "تنظیم منطقه روی ایران (Bypass Iran)",
                "desc": "در صفحه تنظیمات هیدیفای، منطقه جغرافیایی (Region) را روی 'ایران (IR)' قرار دهید تا سایت‌های بانکی و دولتی بدون فیلترشکن باز شده و حجم اینترنت شما نیم‌بها محاسبه شود.",
                "tip": "در این حالت نیاز نیست هنگام پرداخت‌های آنلاین شاپرک، فیلترشکن را خاموش کنید."
            },
            {
                "step": 4,
                "title": "تست تأخیر واقعی و اتصال با یک لمس",
                "desc": "روی آیکون صاعقه یا تست پینگ در صفحه اصلی ضربه بزنید تا کم‌تاخیرترین سرور انتخاب شود. سپس دکمه بزرگ دایره‌ای وسط صفحه را لمس کنید تا اتصال برقرار گردد.",
                "tip": "وقتی دکمه به رنگ سبز درآمد و آیکون کلید بالای گوشی ظاهر شد، یعنی اینترنت آزاد متصل است."
            }
        ],
        "troubleshoot": [
            "اگر روی همراه اول وصل نشد: وارد تنظیمات هیدیفای شوید > بخش دورزدن فیلترینگ (Fragment) را روی TLS Hello فعال کنید.",
            "اگر اتصال برقرار شد ولی وب‌سایتی باز نشد: حالت کارکرد (Service Mode) را از پروکسی به VPN Service تغییر دهید.",
            "در صورت اخطار امنیتی: تیک گزینه Allow Insecure را در تنظیمات عمومی موقتاً فعال نمایید."
        ]
    },
    "happ": {
        "platform": "android",
        "name": "Happ Proxy Client",
        "subtitle": "اپلیکیشن سبک، کم‌حجم، سریع و بهینه‌سازی‌شده برای مصرف باتری در اندروید",
        "badge": "سبک و روان",
        "badge_color": "info",
        "icon": "fas fa-bolt",
        "rating": "4.8",
        "downloads": [
            {"title": "دانلود فایل نصبی APK", "url": "https://github.com", "icon": "fas fa-download", "btn_class": "btn-info text-white"},
            {"title": "دریافت از گوگل پلی", "url": "https://play.google.com", "icon": "fab fa-google-play", "btn_class": "btn-outline-dark"}
        ],
        "steps": [
            {
                "step": 1,
                "title": "کپی لینک کانفیگ یا اشتراک",
                "desc": "لینک اختصاصی اشتراک خود را از ربات یا پرتال کاربری کپی کنید.",
                "tip": "لینک‌های بلند سابسکریپشن همیشه تمام کانفیگ‌های فعال را یکجا وارد می‌کنند."
            },
            {
                "step": 2,
                "title": "ایمپورت در اپلیکیشن",
                "desc": "برنامه Happ را اجرا کرده و دکمه (+) بالای صفحه را بزنید. گزینه Import Subscription را لمس کنید و لینک را جای‌گذاری نمایید.",
                "tip": "برنامه خودکار لیست سرورها را دانلود و سازمان‌دهی می‌کند."
            },
            {
                "step": 3,
                "title": "اتصال سریع",
                "desc": "سرور با پینگ سبز را انتخاب کرده و دکمه سوئیچ اتصال را روشن کنید.",
                "tip": "مجوز دسترسی VPN را در کادر باز شده تایید کنید."
            }
        ],
        "troubleshoot": [
            "اگر خطای DNS دریافت کردید، در تنظیمات شبکه برنامه تیک DoH را فعال کنید.",
            "در صورت قطع شدن مکرر، دسترسی بهینه‌سازی باتری (Battery Optimization) را برای برنامه غیرفعال کنید."
        ]
    },
    "nekobox": {
        "platform": "android",
        "name": "NekoBox (اندروید)",
        "subtitle": "کلاینت فوق حرفه‌ای بر پایه هسته Sing-box ویژه گیمرها، پینگ پایین و پروتکل‌های مدرن",
        "badge": "حرفه‌ای و گیمینگ",
        "badge_color": "dark",
        "icon": "fas fa-cat",
        "rating": "4.8",
        "downloads": [
            {"title": "دانلود از مخزن گیت‌هاب", "url": "https://github.com/MatsuriDayo/NekoBoxForAndroid/releases/latest", "icon": "fab fa-github", "btn_class": "btn-dark"}
        ],
        "steps": [
            {
                "step": 1,
                "title": "افزودن گروه سابسکریپشن",
                "desc": "وارد منوی Groups در اپلیکیشن NekoBox شوید، دکمه (+) را بزنید و Type را روی Subscription قرار دهید. نام دلخواه و لینک ساب را وارد کنید.",
                "tip": "تیک Auto Update را روشن بگذارید تا سرورها به شکل دوره‌ای تازه شوند."
            },
            {
                "step": 2,
                "title": "بروزرسانی گروه سرورها",
                "desc": "منوی ۳ نقطه کنار گروه را بزنید و Update Subscription را لمس کنید تا کلیه سرورها ظاهر شوند.",
                "tip": "با لمس آیکون رعد و برق پایین صفحه، تست پینگ واقعی کلیه سرورها انجام می‌شود."
            },
            {
                "step": 3,
                "title": "فعال‌سازی حالت TUN و استارت",
                "desc": "تیک TUN Mode را در بالای صفحه روشن کنید و دکمه اتصال را لمس کنید.",
                "tip": "حالت TUN باعث می‌شود بازی‌های آنلاین و تماس‌های صوتی با کمترین پینگ از VPN عبور کنند."
            }
        ],
        "troubleshoot": [
            "برای عدم مسدودی پکت‌ها، در منوی تنظیمات هسته (Core Settings) گزینه Sing-box را انتخاب کنید.",
            "اگر بعد از اتصال اینترنت قطع شد، در تنظیمات DNS گزینه Remote DNS را روی 1.1.1.1 بگذارید."
        ]
    },

    # ─── آیفون و آیپد (iOS) ───
    "streisand": {
        "platform": "ios",
        "name": "Streisand",
        "subtitle": "محبوب‌ترین، پرسرعت‌ترین و کامل‌ترین نرم‌افزار رایگان برای آیفون و آیپد با هسته Xray",
        "badge": "پیشنهادی برای iOS (رایگان)",
        "badge_color": "success",
        "icon": "fas fa-paper-plane",
        "rating": "4.9",
        "downloads": [
            {"title": "دانلود رایگان از App Store", "url": "https://apps.apple.com/app/streisand/id6450534064", "icon": "fab fa-app-store-ios", "btn_class": "btn-primary"}
        ],
        "steps": [
            {
                "step": 1,
                "title": "کپی کردن لینک سابسکریپشن",
                "desc": "در ربات تلگرام روی لینک اختصاصی اشتراک خود ضربه بزنید تا در کلیپ‌بورد آیفون کپی شود.",
                "tip": "لینک‌های اشتراک با https:// شروع می‌شوند."
            },
            {
                "step": 2,
                "title": "افزودن لینک به Streisand",
                "desc": "نرم‌افزار Streisand را باز کنید. علامت مثبت (+) بالای صفحه سمت راست را لمس کرده و گزینه «Import from Clipboard» را انتخاب نمایید. در پنجره باز شده اجازه پیست (Allow Paste) را بدهید.",
                "tip": "در صورت تمایل می‌توانید با زدن Scan QR Code، بارکد اشتراک را اسکن کنید."
            },
            {
                "step": 3,
                "title": "بروزرسانی سرورها و تست پینگ (Refresh)",
                "desc": "انگشت خود را در صفحه اصلی روی لیست سرورها به سمت پایین بکشید (Pull-down to Refresh) تا تمام سرورها به‌روزرسانی شوند. پینگ سرورها به رنگ سبز یا زرد در کنار نام هر سرور درج می‌شود.",
                "tip": "سروری که کمترین عدد پینگ سبز رنگ (مثلاً 190ms) را دارد انتخاب نمایید."
            },
            {
                "step": 4,
                "title": "فعال‌سازی عبور سایت‌های داخلی (Bypass Iran)",
                "desc": "به تب Settings در پایین برنامه بروید و گزینه‌های «Bypass LAN & Iran» یا «Route LAN & Domestic» را روشن کنید تا همراه بانک و سایت‌های داخلی با سرعت کامل باز شوند.",
                "tip": "این گزینه از افت سرعت و قطعی در سایت‌های بانکی جلوگیری می‌کند."
            },
            {
                "step": 5,
                "title": "روشن کردن دکمه اتصال و تایید امنیتی iOS",
                "desc": "به صفحه اصلی برگشته و دکمه اتصال بزرگ دایره‌ای بالای صفحه را روشن کنید. اولین بار پیامی جهت تایید پروفایل VPN نشان داده می‌شود که باید روی Allow بزنید و رمز عبور یا FaceID آیفون را تایید کنید.",
                "tip": "با ظاهر شدن علامت VPN در کنار ساعت یا منوی کنترل‌سنتر آیفون، اتصال پایدار شما برقرار شده است."
            }
        ],
        "troubleshoot": [
            "گیر کردن در Connecting: اگر برنامه روی Connecting ماند، حالت هواپیما (Airplane Mode) را ۱۰ ثانیه روشن و خاموش کنید.",
            "خطای زمان: در تنظیمات آیفون (Settings > General > Date & Time) حتماً گزینه Set Automatically را روشن کنید.",
            "اگر سرورها آپدیت نشدند: یک بار فیلترشکن رایگان دیگری موقتاً روشن کنید و Pull-down کنید تا لیست بارگذاری شود."
        ]
    },
    "foxray-ios": {
        "platform": "ios",
        "name": "FoXray",
        "subtitle": "اپلیکیشن پایدار، قدرتمند و بدون قطعی با پشتیبانی کامل از پروتکل VLESS و Reality در iOS",
        "badge": "پایدار و مدرن",
        "badge_color": "info",
        "icon": "fas fa-shield-cat",
        "rating": "4.8",
        "downloads": [
            {"title": "دریافت از App Store", "url": "https://apps.apple.com/app/foxray/id6448898396", "icon": "fab fa-app-store-ios", "btn_class": "btn-dark"}
        ],
        "steps": [
            {
                "step": 1,
                "title": "کپی لینک یا اسکن QR",
                "desc": "لینک اشتراک خود را کپی کرده یا کد QR را در دسترس نگه دارید.",
                "tip": "برنامه فاکس‌ری برای پروتکل‌های Reality عملکرد بی‌نظیری دارد."
            },
            {
                "step": 2,
                "title": "افزودن اشتراک با علامت (+)",
                "desc": "برنامه FoXray را باز کنید. علامت مثبت (+) بالای صفحه را بزنید و گزینه Clipboard را لمس نمایید تا سرورها اضافه شوند.",
                "tip": "اگر اخطار دسترسی کلیپ‌بورد آمد، گزینه Allow Paste را لمس کنید."
            },
            {
                "step": 3,
                "title": "تست پینگ و اتصال",
                "desc": "روی آیکون سرعت‌سنج یا پینگ بزنید، سرور سبز را انتخاب کنید و دکمه مثلثی Play پایین صفحه را برای برقراری اتصال لمس فرمایید.",
                "tip": "در پنجره مجوز سیستم‌عامل روی Allow کلیک کنید."
            }
        ],
        "troubleshoot": [
            "برای فعال کردن تفکیک ایران: در بخش Routing گزینه Routing Assets را به‌روز کنید.",
            "در صورت قطعی ناگهانی، در بخش Settings گزینه Always On VPN را فعال نمایید."
        ]
    },
    "v2box": {
        "platform": "ios",
        "name": "V2Box",
        "subtitle": "رابط کاربری خلوت، روان با قابلیت تفکیک آسان کانفیگ‌ها در آیفون و آیپد",
        "badge": "محبوب و ساده",
        "badge_color": "secondary",
        "icon": "fas fa-box-open",
        "rating": "4.7",
        "downloads": [
            {"title": "دریافت از App Store", "url": "https://apps.apple.com/app/v2box-v2ray-client/id6446814690", "icon": "fab fa-app-store-ios", "btn_class": "btn-primary"}
        ],
        "steps": [
            {
                "step": 1,
                "title": "کپی لینک اشتراک",
                "desc": "لینک اشتراک خود را از پنل کاربری کپی کنید.",
                "tip": "از کپی شدن کامل لینک با پروتکل https:// اطمینان حاصل کنید."
            },
            {
                "step": 2,
                "title": "افزودن در تب Configs",
                "desc": "اپلیکیشن V2Box را باز کرده، به تب دوم (Configs) بروید. علامت (+) بالا راست را بزنید و گزینه Add Subscription را انتخاب کنید. یک نام بگذارید و لینک را در کادر URL قرار دهید.",
                "tip": "دکمه Add Sub را بزنید و سپس گزینه Update All Subscriptions را لمس نمایید."
            },
            {
                "step": 3,
                "title": "اتصال در تب Home",
                "desc": "به تب اول (Home) برگردید، سرور دلخواه را لمس کنید و اسلایدر Slide to Connect را به سمت راست بکشید.",
                "tip": "وضعیت به Connected تغییر یافته و اینترنت آزاد فعال می‌شود."
            }
        ],
        "troubleshoot": [
            "اگر سرعت پایین بود: در تب Configs روی سرورها تست پینگ پیاپی بزنید تا بهترین روتینگ انتخاب شود.",
            "رفع مشکل قطع شدن: برنامه را در پس‌زمینه (Background App Refresh) باز نگه دارید."
        ]
    },
    "shadowrocket": {
        "platform": "ios",
        "name": "Shadowrocket (شادوراکت)",
        "subtitle": "قدرتمندترین و حرفه‌ای‌ترین کلاینت iOS با امکانات بی‌نظیر روتینگ و تست سرعت",
        "badge": "تخصصی و فوق‌العاده",
        "badge_color": "danger",
        "icon": "fas fa-shuttle-space",
        "rating": "5.0",
        "downloads": [
            {"title": "مشاهده در اپ استور (نیازمند خرید اپ استور)", "url": "https://apps.apple.com/app/shadowrocket/id932747118", "icon": "fab fa-apple", "btn_class": "btn-dark"}
        ],
        "steps": [
            {
                "step": 1,
                "title": "کپی کردن لینک اشتراک",
                "desc": "لینک اشتراک اختصاصی خود را کپی کنید.",
                "tip": "شادوراکت به محض باز شدن لینک کپی‌شده را تشخیص می‌دهد."
            },
            {
                "step": 2,
                "title": "افزودن سابسکریپشن",
                "desc": "علامت (+) بالای صفحه را بزنید، گزینه Type را روی Subscribe قرار دهید و در کادر URL لینک را پیست کرده و Save را بزنید.",
                "tip": "لیست تمام سرورها بارگذاری خواهد شد."
            },
            {
                "step": 3,
                "title": "تنظیم روتینگ روی Config یا Rule",
                "desc": "در پایین صفحه، Global Routing را روی حالت Config بگذارید تا سایت‌های داخلی به صورت خودکار بدون فیلترشکن باز شوند.",
                "tip": "سرور با پینگ سبز را لمس کرده و سوئیچ بالای صفحه را روشن کنید."
            }
        ],
        "troubleshoot": [
            "در صورت عدم اتصال، در منوی Settings بخش UDP Relay را بررسی نمایید.",
            "برای همراه اول و ایرانسل، از سرورهای Reality استفاده کنید."
        ]
    },
    "singbox-ios": {
        "platform": "ios",
        "name": "Sing-box (iOS)",
        "subtitle": "کلاینت رسمی هسته نسل جدید Sing-box با سرعت فوق‌العاده و مصرف حافظه ناچیز",
        "badge": "هسته نسل جدید",
        "badge_color": "primary",
        "icon": "fas fa-cube",
        "rating": "4.8",
        "downloads": [
            {"title": "دریافت رایگان از App Store", "url": "https://apps.apple.com/app/sing-box/id6451272673", "icon": "fab fa-app-store-ios", "btn_class": "btn-primary"}
        ],
        "steps": [
            {
                "step": 1,
                "title": "افزودن پروفایل",
                "desc": "وارد تب Profiles شوید، New Profile را بزنید، Type را Remote بگذارید و لینک اشتراک را قرار دهید.",
                "tip": "تیک Auto Update را فعال بگذارید."
            },
            {
                "step": 2,
                "title": "اتصال سراسری",
                "desc": "به تب Dashboard بروید، سرور مورد نظر را انتخاب کرده و دکمه اتصال را روشن نمایید.",
                "tip": "در پنجره سیستم‌عامل روی تایید و وارد کردن پسورد کلیک فرمایید."
            }
        ],
        "troubleshoot": [
            "اگر با ارور روتینگ مواجه شدید، از پروفایل‌های استاندارد Sing-box استفاده کنید."
        ]
    },

    # ─── ویندوز (Windows) ───
    "v2rayn": {
        "platform": "windows",
        "name": "v2rayN",
        "subtitle": "کلاینت استاندارد، فوق‌العاده پایدار، جامع و باسابقه برای سیستم‌عامل ویندوز با هسته کامل Xray",
        "badge": "پیشنهادی ویندوز (پایدار)",
        "badge_color": "success",
        "icon": "fas fa-desktop",
        "rating": "4.9",
        "downloads": [
            {"title": "دانلود جدیدترین نسخه با هسته کامل (With-Core)", "url": "https://github.com/2dust/v2rayN/releases/latest", "icon": "fab fa-github", "btn_class": "btn-success"},
            {"title": "دانلود پکیج کامل از گیت‌هاب", "url": "https://github.com/2dust/v2rayN/releases", "icon": "fas fa-download", "btn_class": "btn-outline-dark"}
        ],
        "steps": [
            {
                "step": 1,
                "title": "استخراج فایل فشرده و اجرای ادمین",
                "desc": "فایل zip دانلود شده را از حالت فشرده خارج (Extract) کنید. وارد پوشه شده و روی فایل v2rayN.exe راست کلیک کرده و گزینه Run as administrator را انتخاب کنید.",
                "tip": "اجرای به صورت ادمین برای فعال‌سازی بدون نقص قابلیت‌های سیستمی و تونل TUN ضروری است."
            },
            {
                "step": 2,
                "title": "ثبت لینک سابسکریپشن در برنامه",
                "desc": "از نوار منوی بالای نرم‌افزار، روی گزینه Subscription Group (گروه اشتراک) کلیک کرده و Subscription group setting را انتخاب نمایید. در پنجره باز شده دکمه Add را بزنید، نامی دلخواه بنویسید و لینک اشتراک خود را در فیلد url پیست کرده و Confirm بزنید.",
                "tip": "همیشه از ثبت لینک در بخش Subscription Group استفاده کنید تا با یک کلیک بتوانید تمام سرورها را به‌روز کنید."
            },
            {
                "step": 3,
                "title": "به‌روزرسانی سرورها بدون پروکسی",
                "desc": "مجدداً از منوی بالای نرم‌افزار روی Subscription Group کلیک کرده و گزینه «Update subscription without proxy» (بروزرسانی بدون پروکسی) را بزنید. چند ثانیه صبر کنید تا لیست سرورها در جدول ظاهر شوند.",
                "tip": "اگر کانفیگ‌ها لود نشدند، با یک فیلترشکن کمکی موقت دکمه Update subscription را لمس کنید."
            },
            {
                "step": 4,
                "title": "تست پینگ واقعی تمام سرورها",
                "desc": "کلیدهای ترکیبی Ctrl + A را بزنید تا تمام سرورها انتخاب شوند. سپس راست کلیک کرده و گزینه «Real delay test» (تست پینگ واقعی) را انتخاب کنید. کمترین پینگ عددی سبز رنگ را با دو بار کلیک انتخاب کنید.",
                "tip": "پینگ سبز نشان‌دهنده دسترسی آزاد و پرسرعت به سرور است."
            },
            {
                "step": 5,
                "title": "فعال‌سازی پروکسی سیستم یا حالت TUN",
                "desc": "در نوار پایینی نرم‌افزار، فیلد System Proxy را از Clear System Proxy روی گزینه «Set system proxy» بگذارید (آیکون برنامه در تسک‌بار کنار ساعت به رنگ قرمز یا آبی درمی‌آید). برای عبور دادن بازی‌ها و تلگرام دسکتاپ، تیک گزینه «Enable Tun» را در پایین برنامه فعال کنید.",
                "tip": "برای باز شدن سایت‌های بانکی ایرانی بدون مشکل، گزینه Routing در پایین برنامه را روی Bypass LAN and mainland china/iran بگذارید."
            }
        ],
        "troubleshoot": [
            "خطای Port Occupied یا اشغال پورت 10808: از منوی Settings > OptionSetting وارد شوید و Local SOCKS Port را از 10808 به 10809 یا 20808 تغییر داده و Confirm بزنید.",
            "اگر اینترنت رد نشد: روی ساعت ویندوز کلیک راست کرده، Adjust date/time را بزنید و روی دکمه Sync Now کلیک کنید تا ساعت ویندوز با ساعت جهانی همگام شود.",
            "اخطار فایروال ویندوز: در صورت نمایش پنجره Windows Defender Firewall، تیک Private و Public را زده و روی Allow Access کلیک کنید."
        ]
    },
    "hiddify-windows": {
        "platform": "windows",
        "name": "Hiddify (ویندوز)",
        "subtitle": "کلاینت مدرن، زیبا و کاملاً فارسی بر پایه Sing-box با قابلیت اتصال یک‌کلیکه و دور زدن آسان فیلترینگ",
        "badge": "محیط زیبا و فارسی",
        "badge_color": "primary",
        "icon": "fas fa-shield-halved",
        "rating": "4.9",
        "downloads": [
            {"title": "دانلود فایل نصبی ویندوز (Setup.exe)", "url": "https://github.com/hiddify/hiddify-next/releases/latest", "icon": "fab fa-windows", "btn_class": "btn-primary"},
            {"title": "دانلود نسخه پرتابل بدون نیاز به نصب", "url": "https://github.com/hiddify/hiddify-next/releases", "icon": "fas fa-box-archive", "btn_class": "btn-outline-dark"}
        ],
        "steps": [
            {
                "step": 1,
                "title": "نصب و اجرای برنامه",
                "desc": "نرم‌افزار Hiddify را دانلود و به سادگی نصب نمایید. برنامه به صورت خودکار زبان ویندوز را شناسایی کرده و به زبان شیرین فارسی باز می‌شود.",
                "tip": "در صورت درخواست دسترسی توسط سیستم‌عامل، روی Yes کلیک کنید."
            },
            {
                "step": 2,
                "title": "افزودن لینک اشتراک",
                "desc": "لینک اشتراک خود را کپی کنید. در برنامه روی دکمه بزرگ (+) یا گزینه «افزودن از کلیپ‌بورد» کلیک کنید. کانفیگ‌ها بارگذاری می‌شوند.",
                "tip": "همچنین می‌توانید لینک را مستقیماً بکشید و روی پنجره برنامه رها کنید (Drag & Drop)."
            },
            {
                "step": 3,
                "title": "فعال‌سازی حالت TUN و اتصال",
                "desc": "حالت کارکرد را روی VPN Service بگذارید تا کل نرم‌افزارهای سیستم از تونل عبور کنند. سپس دکمه دایره‌ای وسط صفحه را بزنید.",
                "tip": "سبز شدن دایره نشان‌دهنده برقراری اتصال است."
            }
        ],
        "troubleshoot": [
            "برای حل مسدودی اپراتورها: در بخش تنظیمات > دور زدن فیلترینگ، Fragment را فعال کنید.",
            "در صورت ارور WinTUN: برنامه را ببندید و با راست کلیک روی آیکون برنامه Run as administrator بزنید."
        ]
    },
    "nekoray-win": {
        "platform": "windows",
        "name": "Nekoray (ویندوز)",
        "subtitle": "کلاینت فوق‌العاده سریع با هسته Sing-box ویژه پینگ بسیار پایین، بازی‌های آنلاین و روتینگ تفکیکی",
        "badge": "ویژه پینگ پایین و بازی",
        "badge_color": "danger",
        "icon": "fas fa-gamepad",
        "rating": "4.9",
        "downloads": [
            {"title": "دانلود جدیدترین نسخه با هسته کامل از گیت‌هاب", "url": "https://github.com/MatsuriDayo/nekoray/releases/latest", "icon": "fab fa-github", "btn_class": "btn-dark"}
        ],
        "steps": [
            {
                "step": 1,
                "title": "استخراج و انتخاب هسته Sing-box",
                "desc": "فایل فشرده را اکسترکت کرده و nekoray.exe را اجرا کنید. در اولین اجرا هسته Sing-box را تایید نمایید.",
                "tip": "هسته Sing-box پایداری بالاتری روی شبکه‌های با اختلال دارد."
            },
            {
                "step": 2,
                "title": "افزودن سرورها با کلید میانبر",
                "desc": "لینک اشتراک را کپی کنید. در محیط نرم‌افزار کلیدهای ترکیبی Ctrl + V را فشار دهید تا سرورها به صورت خودکار اضافه شوند.",
                "tip": "سرورها در یک گروه اختصاصی مرتب می‌شوند."
            },
            {
                "step": 3,
                "title": "فعال کردن TUN Mode و استارت",
                "desc": "تیک گزینه TUN Mode را در بالای صفحه فعال کنید، سرور با کمترین پینگ را انتخاب کرده و راست کلیک و Start را بزنید.",
                "tip": "برای اجرای TUN نیاز به دسترسی ادمین است."
            }
        ],
        "troubleshoot": [
            "ارور درایور Wintun: در پوشه برنامه فایل wintun.dll را بررسی کنید که توسط آنتی‌ویروس حذف نشده باشد.",
            "تغییر پورت: از منوی Preferences > Basic Settings پورت را در صورت اشغال بودن تغییر دهید."
        ]
    },
    "clash-verge": {
        "platform": "windows",
        "name": "Clash Verge Rev",
        "subtitle": "مدرن‌ترین کلاینت بر پایه Clash Meta با تفکیک هوشمند ترافیک و ظاهر فوق‌العاده زیبا",
        "badge": "مدرن و پیشرفته",
        "badge_color": "info",
        "icon": "fas fa-sliders",
        "rating": "4.8",
        "downloads": [
            {"title": "دانلود فایل نصبی از گیت‌هاب", "url": "https://github.com/clash-verge-rev/clash-verge-rev/releases/latest", "icon": "fab fa-github", "btn_class": "btn-dark"}
        ],
        "steps": [
            {
                "step": 1,
                "title": "وارد کردن پروفایل اشتراک",
                "desc": "نرم‌افزار را باز کنید، به تب Profiles بروید، لینک سابسکریپشن را در کادر بالا قرار داده و دکمه Import را بزنید.",
                "tip": "پروفایل بارگذاری شده را فعال کنید (کلیک کنید تا آبی شود)."
            },
            {
                "step": 2,
                "title": "انتخاب سرور و فعال‌سازی System Proxy",
                "desc": "به تب Proxies رفته و روی گروه سرورها کمترین پینگ را انتخاب کنید. سپس از تب Settings تیک System Proxy یا Tun Mode را روشن کنید.",
                "tip": "این نرم‌افزار به صورت هوشمند سایت‌های بانکی ایران را از ترافیک پروکسی مستثنی می‌کند."
            }
        ],
        "troubleshoot": [
            "در صورت خطای Service Mode، وارد Settings برنامه شده و گزینه Install Service Mode را کلیک کنید."
        ]
    },

    # ─── اندروید تی‌وی (Android TV) ───
    "v2rayng-tv": {
        "platform": "tv",
        "name": "v2rayNG (نسخه تلویزیون هوشمند)",
        "subtitle": "سازگار کامل با ریموت کنترل انواع تلویزیون‌های هوشمند، اندروید‌باکس‌ها و Mi Box",
        "badge": "پیشنهادی تلویزیون",
        "badge_color": "danger",
        "icon": "fas fa-tv",
        "rating": "4.9",
        "downloads": [
            {"title": "دانلود مستقیم فایل نصبی APK برای تلویزیون", "url": "https://github.com/2dust/v2rayNG/releases/latest", "icon": "fas fa-download", "btn_class": "btn-danger"}
        ],
        "steps": [
            {
                "step": 1,
                "title": "انتقال فایل APK به تلویزیون",
                "desc": "فایل APK برنامه را با فلش مموری (USB) یا اپلیکیشن Send Files to TV از گوشی به تلویزیون هوشمند خود ارسال و نصب کنید.",
                "tip": "اجازه نصب برنامه‌ها از منابع ناشناس (Unknown Sources) را در تنظیمات امنیت تلویزیون فعال کنید."
            },
            {
                "step": 2,
                "title": "اسکن بارکد QR با وب‌کم یا وارد کردن لینک",
                "desc": "برنامه را با ریموت باز کنید. روی علامت (+) بروید؛ اگر تلویزیون دوربین دارد Scan QR Code را بزنید یا با کیبورد مجازی در بخش Subscription group setting لینک را وارد کنید.",
                "tip": "می‌توانید با یک ماوس سیمی یا بی‌سیم خیلی سریع‌تر لینک را در کادر Paste کنید."
            },
            {
                "step": 3,
                "title": "بروزرسانی و اتصال",
                "desc": "گزینه Update subscription را بزنید، سرور پرسرعت را انتخاب کرده و دکمه اتصال را فشار دهید.",
                "tip": "اکنون YouTube، پلتفرم‌های پخش فیلم و تمام نرم‌افزارهای تلویزیون با کیفیت 4K و بدون بافر باز می‌شوند."
            }
        ],
        "troubleshoot": [
            "برای فعال ماندن فیلیمو و نماوا: در تنظیمات برنامه گزینه Bypass LAN and Iran را تیک بزنید.",
            "اگر ریموت کنترل کلیدها را انتخاب نمی‌کرد، از ماوس یا برنامه ریموت مجازی گوشی استفاده کنید."
        ]
    },
    "hiddify-tv": {
        "platform": "tv",
        "name": "Hiddify TV",
        "subtitle": "رابط اختصاصی بهینه‌سازی شده برای صفحه‌نمایش‌های بزرگ خانگی و تلویزیون‌های سونی و شیائومی",
        "badge": "سریع و سازگار با ریموت",
        "badge_color": "primary",
        "icon": "fas fa-display",
        "rating": "4.8",
        "downloads": [
            {"title": "دانلود فایل نصبی اندروید تی‌وی", "url": "https://github.com/hiddify/hiddify-next/releases/latest", "icon": "fas fa-download", "btn_class": "btn-primary"}
        ],
        "steps": [
            {
                "step": 1,
                "title": "نصب برنامه در تلویزیون",
                "desc": "برنامه را نصب کرده و باز کنید.",
                "tip": "محیط این برنامه بسیار بزرگ و خوانا طراحی شده است."
            },
            {
                "step": 2,
                "title": "افزودن اشتراک",
                "desc": "لینک اشتراک را وارد نمایید یا QR کد را اسکن کنید.",
                "tip": "امکان به‌روزرسانی خودکار سرورها وجود دارد."
            },
            {
                "step": 3,
                "title": "اتصال پایدار",
                "desc": "دکمه اتصال را با ریموت بزنید و از تماشای ویدیوهای بدون قطعی لذت ببرید.",
                "tip": "پروتکل‌های Reality بیشترین سازگاری را با تلویزیون دارند."
            }
        ],
        "troubleshoot": []
    },
    "spark-tv": {
        "platform": "tv",
        "name": "Spark TV",
        "subtitle": "کلاینت کم‌حجم ویژه استریمینگ و تماشای بدون قطعی یوتیوب در تلویزیون هوشمند",
        "badge": "ویژه استریم",
        "badge_color": "secondary",
        "icon": "fas fa-play",
        "rating": "4.7",
        "downloads": [
            {"title": "دریافت فایل نصبی مستقیم", "url": "https://github.com", "icon": "fas fa-download", "btn_class": "btn-dark"}
        ],
        "steps": [
            {
                "step": 1,
                "title": "وارد کردن لینک",
                "desc": "لینک را وارد کنید و روی سرور با پینگ سبز کلیک نمایید.",
                "tip": "بسیار سبک بوده و حافظه رم تلویزیون را اشغال نمی‌کند."
            }
        ],
        "troubleshoot": []
    },

    # ─── مک‌بوک و مک (macOS) ───
    "foxray-mac": {
        "platform": "macos",
        "name": "FoXray (macOS)",
        "subtitle": "بهترین کلاینت برای سیستم‌های مک با سازگاری بومی برای تراشه‌های اپل M1/M2/M3/M4 و اینتل",
        "badge": "پیشنهادی مک",
        "badge_color": "success",
        "icon": "fas fa-shield-cat",
        "rating": "4.9",
        "downloads": [
            {"title": "دانلود از Mac App Store", "url": "https://apps.apple.com/app/foxray/id6448898396", "icon": "fab fa-apple", "btn_class": "btn-dark"}
        ],
        "steps": [
            {
                "step": 1,
                "title": "کپی لینک سابسکریپشن",
                "desc": "لینک اشتراک خود را از پنل کاربری کپی کنید.",
                "tip": "برنامه فاکس‌ری روی مک کاملاً بهینه و کم‌مصرف است."
            },
            {
                "step": 2,
                "title": "ایمپورت در مک",
                "desc": "نرم‌افزار را اجرا کنید، کلید (+) را بزنید و گزینه Clipboard را لمس نمایید.",
                "tip": "لیست سرورها اضافه می‌شوند."
            },
            {
                "step": 3,
                "title": "اتصال و استارت",
                "desc": "روی آیکون استارت کلیک کنید و در صورت نیاز پسورد مک را جهت ساخت VPN Interface وارد نمایید.",
                "tip": "تمام برنامه‌ها، ترمینال و مرورگرهای مک به اینترنت آزاد متصل می‌شوند."
            }
        ],
        "troubleshoot": []
    },
    "hiddify-mac": {
        "platform": "macos",
        "name": "Hiddify (macOS)",
        "subtitle": "رابط گرافیکی فارسی و مدرن با عملکرد هوشمند برای سیستم‌عامل مک",
        "badge": "رابط کاربری زیبا",
        "badge_color": "primary",
        "icon": "fas fa-shield-halved",
        "rating": "4.8",
        "downloads": [
            {"title": "دانلود پکیج DMG برای مک", "url": "https://github.com/hiddify/hiddify-next/releases/latest", "icon": "fab fa-apple", "btn_class": "btn-primary"}
        ],
        "steps": [
            {
                "step": 1,
                "title": "نصب فایل DMG",
                "desc": "فایل دانلود شده را باز کرده و آیکون برنامه را به پوشه Applications بکشید.",
                "tip": "در بخش Security & Privacy در صورت اخطار دسترسی Open Anyway را بزنید."
            },
            {
                "step": 2,
                "title": "افزودن لینک و اتصال",
                "desc": "لینک را وارد کرده و دکمه دایره‌ای وسط را بزنید.",
                "tip": "حالت کارکرد را روی VPN Service قرار دهید."
            }
        ],
        "troubleshoot": []
    },
    "v2rayu": {
        "platform": "macos",
        "name": "v2rayU",
        "subtitle": "کلاینت کلاسیک و سبک مک که در منوبار بالای صفحه مستقر می‌شود",
        "badge": "سبک در منوبار",
        "badge_color": "secondary",
        "icon": "fas fa-laptop",
        "rating": "4.7",
        "downloads": [
            {"title": "دانلود از مخزن رسمی گیت‌هاب", "url": "https://github.com/yanue/V2rayU/releases/latest", "icon": "fab fa-github", "btn_class": "btn-dark"}
        ],
        "steps": [
            {
                "step": 1,
                "title": "افزودن ساب و روشن کردن",
                "desc": "از منوبار روی آیکون برنامه کلیک کرده، وارد Subscriptions شوید، لینک را ادد کنید و Turn v2ray-core On را بزنید.",
                "tip": "پروکسی سیستم روی گلوبال یا رول قرار می‌گیرد."
            }
        ],
        "troubleshoot": []
    },

    # ─── لینوکس (Linux) ───
    "v2raya": {
        "platform": "linux",
        "name": "v2rayA",
        "subtitle": "کلاینت قدرتمند تحت وب لینوکس با روتینگ شفاف (Transparent Proxy) برای کل سیستم",
        "badge": "پیشنهادی لینوکس",
        "badge_color": "success",
        "icon": "fab fa-linux",
        "rating": "4.9",
        "downloads": [
            {"title": "راهنمای نصب و دبیان/اوبونتو", "url": "https://github.com/v2rayA/v2rayA", "icon": "fab fa-github", "btn_class": "btn-dark"}
        ],
        "steps": [
            {
                "step": 1,
                "title": "اجرای سرویس در لینوکس",
                "desc": "دستور `sudo systemctl start v2raya` را در ترمینال اجرا کنید.",
                "tip": "با دستور `sudo systemctl enable v2raya` برنامه در هر بار بوت فعال خواهد بود."
            },
            {
                "step": 2,
                "title": "ورود به داشبورد مرورگر",
                "desc": "در مرورگر خود آدرس `http://localhost:2017` را باز کنید.",
                "tip": "یک نام کاربری و رمز عبور اولیه انتخاب نمایید."
            },
            {
                "step": 3,
                "title": "افزودن لینک و اتصال شفاف",
                "desc": "دکمه Import را در داشبورد زده، لینک ساب را وارد کنید و روی Start کلیک نمایید.",
                "tip": "کل سیستم، مخازن پکیج‌ها (apt) و ترمینال از پروکسی عبور خواهند کرد."
            }
        ],
        "troubleshoot": []
    },
    "nekoray-linux": {
        "platform": "linux",
        "name": "Nekoray (لینوکس)",
        "subtitle": "محیط گرافیکی (GUI) زیبا با هسته Sing-box برای توزیع‌های اوبونتو، فدورا و آرچ",
        "badge": "محیط گرافیکی (GUI)",
        "badge_color": "info",
        "icon": "fas fa-window-maximize",
        "rating": "4.8",
        "downloads": [
            {"title": "دانلود فایل AppImage", "url": "https://github.com/MatsuriDayo/nekoray/releases/latest", "icon": "fas fa-download", "btn_class": "btn-info text-white"}
        ],
        "steps": [
            {
                "step": 1,
                "title": "اجرای فایل AppImage",
                "desc": "مجوز اجرایی `chmod +x` به فایل بدهید و آن را اجرا کنید. با Ctrl+V لینک را پیست کنید.",
                "tip": "تیک TUN Mode را فعال نمایید."
            }
        ],
        "troubleshoot": []
    },

    # ─── مودم و روترها (Modem & Router) ───
    "openwrt": {
        "platform": "router",
        "name": "OpenWrt (PassWall / SSR-Plus)",
        "subtitle": "آزادسازی کل شبکه اینترنت و وای‌فای خانه بر روی مودم، روتر، پلی‌استیشن و تلویزیون",
        "badge": "حرفه‌ای‌ترین و بهترین روش",
        "badge_color": "purple",
        "icon": "fas fa-wifi",
        "rating": "5.0",
        "downloads": [
            {"title": "مخزن افزونه PassWall در گیت‌هاب", "url": "https://github.com/xiaorouji/openwrt-passwall", "icon": "fab fa-github", "btn_class": "btn-dark"}
        ],
        "steps": [
            {
                "step": 1,
                "title": "ورود به پنل تنظیمات مودم OpenWrt",
                "desc": "در مرورگر کامپیوتر یا گوشی آدرس آی‌پی روتر (معمولاً 192.168.1.1) را وارد کرده و لاگین کنید.",
                "tip": "اطمینان یابید پکیج PassWall یا ShadowsocksR Plus بر روی فریمور نصب است."
            },
            {
                "step": 2,
                "title": "افزودن لینک سابسکریپشن در PassWall",
                "desc": "از منوی خدمات (Services) وارد گزینه PassWall شوید و به تب «Node List / سابسکریپشن» بروید. روی Add کلیک کرده و لینک اشتراک را در Subscribe URL قرار دهید.",
                "tip": "تیک ذخیره و اعمال (Save & Apply) را بزنید."
            },
            {
                "step": 3,
                "title": "بروزرسانی نودها و فعال‌سازی سراسری",
                "desc": "دکمه Update All Nodes را بزنید. در صفحه اول PassWall وضعیت Main Node را روی سرور دلخواه گذاشته و کلید را Enabled کنید.",
                "tip": "از این لحظه هر دستگاهی به وای‌فای متصل شود، بدون نصب هیچ فیلترشکنی به اینترنت آزاد متصل است!"
            }
        ],
        "troubleshoot": [
            "برای بازی‌های کنسول PS5 / Xbox: حالت روتینگ را روی China/Iran Bypass قرار دهید تا پینگ بازی تحت تاثیر قرار نگیرد."
        ]
    },
    "mikrotik": {
        "platform": "router",
        "name": "MikroTik RouterOS",
        "subtitle": "اتصال روترهای شرکتی میکروتیک با پروتکل‌های امن و روتینگ بر پایه آدرس‌لیست",
        "badge": "شبکه‌های شرکتی و اداری",
        "badge_color": "secondary",
        "icon": "fas fa-server",
        "rating": "4.9",
        "downloads": [
            {"title": "مستندات رسمی RouterOS", "url": "https://help.mikrotik.com", "icon": "fas fa-book", "btn_class": "btn-outline-dark"}
        ],
        "steps": [
            {
                "step": 1,
                "title": "تنظیم Interface و روتینگ",
                "desc": "در نرم‌افزار WinBox مشخصات سرور را در بخش Interface اضافه کرده و مسیر پیش‌فرض را به سمت آن هدایت کنید.",
                "tip": "می‌توانید ترافیک را بر اساس IP مقصد تفکیک کنید."
            }
        ],
        "troubleshoot": []
    },
    "asuswrt": {
        "platform": "router",
        "name": "Asuswrt-Merlin",
        "subtitle": "اتصال مودم‌ها و روترهای گیمینگ ایسوس با قابلیت اختصاصی VPN Fusion",
        "badge": "روترهای ایسوس",
        "badge_color": "info",
        "icon": "fas fa-network-wired",
        "rating": "4.8",
        "downloads": [
            {"title": "وب‌سایت رسمی فریمور مرلین", "url": "https://www.asuswrt-merlin.net/", "icon": "fas fa-globe", "btn_class": "btn-info text-white"}
        ],
        "steps": [
            {
                "step": 1,
                "title": "ورود به تب VPN Fusion",
                "desc": "در پنل روتر به بخش VPN > VPN Fusion بروید، کانفیگ را ادد کرده و دستگاه‌های مورد نظر را انتخاب کنید.",
                "tip": "امکان تعیین فیلترشکن تنها برای تلویزیون یا کنسول بازی وجود دارد."
            }
        ],
        "troubleshoot": []
    }
}

# ═══════════════════════════════════════════════════════════════════════
# مقالات تخصصی عیب‌یابی و حل مشکلات اتصال (Comprehensive Troubleshooting)
# ═══════════════════════════════════════════════════════════════════════

TROUBLESHOOTING_GUIDES = [
    {
        "slug": "time_desync",
        "title": "خطای انحراف ساعت و تاریخ سیستم (Time Desync Error)",
        "subtitle": "علت ۹۰٪ خطاهای اتصال در پروتکل‌های امن VLESS, VMess و TLS",
        "icon": "fas fa-clock",
        "color": "danger",
        "problem": "در اپلیکیشن پیام خطای `invalid user`، `certificate is not valid yet`، خطای TLS handshake یا پینگ بی‌پاسخ (-1) علی‌رغم سالم بودن اشتراک دریافت می‌شود.",
        "cause": "پروتکل‌های نسل جدید برای مقابله با حملات Replay Attack و رمزنگاری داده‌ها، بر پایه زمان استاندارد جهانی (UTC) با دقت ثانیه کار می‌کنند. اگر ساعت دستگاه شما حتی ۱ یا ۲ دقیقه عقب یا جلو باشد، سرور برای امنیت اتصال را فوراً رد می‌کند.",
        "solution_steps": [
            "**در گوشی‌های اندروید (Samsung, Xiaomi, Huawei):** به Settings > General Management (یا System) > Date and time بروید. گزینه های `Set time automatically` و `Set time zone automatically` را یک بار خاموش و مجدداً روشن کنید تا ساعت دقیق همگام شود.",
            "**در گوشی‌های آیفون (iOS):** به Settings > General > Date & Time بروید و تیک گزینه `Set Automatically` را روشن کنید. اگر از قبل روشن بود، یک بار خاموش، ۵ ثانیه صبر و سپس روشن نمایید.",
            "**در ویندوز (Windows 10 / 11):** روی ساعت در گوشه پایین سمت راست دسکتاپ راست‌کلیک کرده و گزینه `Adjust date/time` را انتخاب کنید. سپس روی دکمه **Sync now** کلیک کنید تا تیک سبز دریافت شود.",
            "**در مک (macOS):** به System Settings > General > Date & Time رفته و `Set time and date automatically` را تایید نمایید."
        ]
    },
    {
        "slug": "internet_package",
        "title": "بررسی اتمام بسته اینترنت یا هدایت اجباری اپراتور (Captive Portal)",
        "subtitle": "بررسی بسته اینترنت فعال و جلوگیری از مسدودسازی مخفیانه اپراتورها",
        "icon": "fas fa-wifi",
        "color": "warning",
        "problem": "فیلترشکن به هیچ عنوان وصل نمی‌شود یا بعد از ۱ ثانیه قطع می‌شود، یا در مرورگر صفحه خرید بسته شارژ اپراتور باز می‌شود.",
        "cause": "هنگامی که حجم بسته اینترنت سیم‌کارت به اتمام می‌رسد یا به چند مگابایت آخر می‌رسد، اپراتورها (همراه اول، ایرانسل، رایتل) تمام پکت‌های اینترنت را به صفحه خرید بسته هدایت می‌کنند که باعث قطعی کامل تونل‌های رمزنگاری VPN می‌شود.",
        "solution_steps": [
            "**استعلام بسته همراه اول:** کد دستوری `#10*100*` یا `#320*10*` را شماره‌گیری کنید یا اپلیکیشن «همراه من» را بررسی نمایید.",
            "**استعلام بسته ایرانسل:** کد دستوری `#4*1*555*` را شماره‌گیری کنید یا برنامه «ایرانسل من» را باز کنید.",
            "**استعلام بسته رایتل:** کد دستوری `#144*` را شماره‌گیری نمایید.",
            "**در صورت استفاده از اینترنت خانگی (مودم ADSL/VDSL/فیبرنوری):** وارد پنل کاربری شرکت ارائه‌دهنده اینترنت (مخابرات، شاتل، آسیاتک، های‌وب) شوید و از باقی ماندن حجم ترافیک بین‌الملل مطمئن شوید.",
            "اگر بسته به اتمام رسیده بود، ابتدا بسته جدید خریداری کرده، یک بار گوشی را روی حالت پرواز (Airplane Mode) برده و برگردانید و مجدداً متصل شوید."
        ]
    },
    {
        "slug": "subscription_quota",
        "title": "بررسی انقضا یا اتمام حجم اشتراک VPN در پنل کاربری",
        "subtitle": "چک کردن اعتبار اشتراک، روزهای باقی‌مانده و ترافیک مصرفی",
        "icon": "fas fa-id-card",
        "color": "primary",
        "problem": "نرم‌افزار هیچ پینگی نمی‌دهد و ارورهای `rejected by remote server` یا `user traffic expired` نمایش داده می‌شود.",
        "cause": "حجم بسته اشتراک VPN شما (مثلاً 50GB) به اتمام رسیده و یا مهلت زمانی آن (مثلاً ۳۰ روز) منقضی شده است.",
        "solution_steps": [
            "وارد **ربات تلگرام** شوید و دکمه **«اشتراک‌های من»** یا **«وضعیت حساب»** را لمس کنید تا جزئیات حجم و تاریخ انقضا را مشاهده فرمایید.",
            "همچنین می‌توانید لینک اشتراک خود را در نوار آدرس مرورگر وارد و باز کنید تا صفحه گزارش مصرف و تاریخ انقضا نمایش داده شود.",
            "در صورت اتمام حجم یا زمان، از طریق ربات و دکمه **«تمدید اشتراک»** یا خرید پلن جدید، سرویس خود را فوراً شارژ نمایید."
        ]
    },
    {
        "slug": "fragmentation",
        "title": "فیلترینگ شدید پکت‌های TLS اپراتورها (همراه اول و ایرانسل) و فعال‌سازی Fragment",
        "subtitle": "تکه‌تکه کردن پکت‌های اینترنت برای دور زدن سیستم فیلترینگ عمیق (DPI)",
        "icon": "fas fa-shield-virus",
        "color": "danger",
        "problem": "روی همراه اول یا ایرانسل کانفیگ متصل می‌شود ولی هیچ داده‌ای رد و بدل نمی‌شود، یا اینستاگرام و یوتیوب بعد از چند ثانیه متوقف می‌شوند.",
        "cause": "سیستم فیلترینگ اپراتورها با بررسی پکت ابتدایی اتصال (TLS Client Hello) سرور را شناسایی و مسدود می‌کنند.",
        "solution_steps": [
            "**در نرم‌افزار v2rayNG:** وارد منوی همبرگری سمت چپ > Settings شوید. به بخش **Fragment** بروید و تیک آن را روشن کنید. مقدار packets را روی `1-3` (یا `100-200`) و length را روی `10-20` تنظیم نمایید.",
            "**در نرم‌افزار Hiddify:** وارد تنظیمات برنامه شوید > بخش **دور زدن فیلترینگ (Fragment)** را باز کرده و حالت آن را روی `TLS Hello` قرار دهید.",
            "**در نرم‌افزار Streisand (آیفون):** وارد Settings برنامه شده و گزینه **Fragment** را روشن کنید.",
            "سپس یک بار برنامه را قطع و مجدداً به سرور با کمترین پینگ متصل شوید."
        ]
    },
    {
        "slug": "dns_poisoning",
        "title": "مسمومیت DNS و خطای Timeout در باز شدن سایت‌ها",
        "subtitle": "پینگ سبز است اما هیچ صفحه‌ای باز نمی‌شود (رفع مشکل DNS اپراتورها)",
        "icon": "fas fa-globe",
        "color": "info",
        "problem": "نرم‌افزار متصل است و پینگ سرورها بین ۱۰۰ تا ۲۵۰ میلی‌ثانیه سبز است، اما صفحات اینترنتی و تلگرام لود نمی‌شوند.",
        "cause": "اپراتورهای اینترنت با دستکاری پاسخ‌های DNS (مسموم‌سازی DNS) اجازه ترجمه دامنه سایت‌ها به آی‌پی صحیح را نمی‌دهند.",
        "solution_steps": [
            "**در v2rayNG:** وارد Settings برنامه شوید. بخش **Remote DNS** را روی `https://1.1.1.1/dns-query` (کلودفلر) یا `https://dns.google/dns-query` (گوگل) بگذارید. همچنین گزینه **Local DNS** را روی `8.8.8.8` قرار دهید.",
            "**در Hiddify:** در بخش تنظیمات > DNS، ارائه‌دهنده را روی Cloudflare یا Google تنظیم فرمایید.",
            "**در مودم‌های خانگی:** وارد پنل تنظیمات مودم خود شده و در بخش DHCP، دی‌ان‌اس‌ها را به `1.1.1.1` و `8.8.8.8` تغییر دهید و مودم را یک‌بار ری‌استارت کنید."
        ]
    },
    {
        "slug": "bypass_iran",
        "title": "خطای عدم باز شدن همراه بانک، اسنپ و سایت‌های دولتی (Bypass Iran)",
        "subtitle": "استفاده همزمان از اینترنت بدون فیلتر و سایت‌های بانکی و شاپرک بدون نیاز به خاموش کردن VPN",
        "icon": "fas fa-building-columns",
        "color": "success",
        "problem": "هنگام خرید اینترنتی یا ورود به همراه بانک و درگاه پرداخت شاپرک با خطای «دسترسی تنها از داخل ایران مجاز است» مواجه می‌شوید.",
        "cause": "بانک‌ها و سرویس‌های ایرانی برای جلوگیری از حملات سایبری، آی‌پی‌های خارج از کشور را مسدود می‌کنند.",
        "solution_steps": [
            "**در v2rayNG:** وارد Settings شوید > گزینه **Routing Rules** را باز کرده و روی **Bypass LAN and Iran** (عبور آدرس‌های محلی و ایران) قرار دهید.",
            "**در Hiddify:** در صفحه اصلی برنامه، بخش منطقه (Country) را روی **ایران (IR)** بگذارید.",
            "**در Streisand (آیفون):** به تب Settings بروید و تیک گزینه **Bypass Iran** را روشن کنید.",
            "**در v2rayN (ویندوز):** در پایین صفحه گزینه Routing را روی **Bypass LAN and mainland china/iran** قرار دهید."
        ]
    },
    {
        "slug": "ssl_cert_error",
        "title": "خطای گواهی امنیتی SSL و پیام Certificate Expired یا x509",
        "subtitle": "رفع ارورهای امنیتی مربوط به گواهی سرورها",
        "icon": "fas fa-lock",
        "color": "secondary",
        "problem": "هنگام اتصال، خطاهایی شامل `x509: certificate has expired or is not yet valid` یا `bad certificate` در لاگ برنامه ظاهر می‌شود.",
        "cause": "انحراف تاریخ میلادی دستگاه و یا تغییر گواهی سرور بدون به‌روزرسانی در کلاینت شما.",
        "solution_steps": [
            "ابتدا تاریخ میلادی دستگاه خود را چک کنید که سال جاری میلادی و تاریخ روز دقیقاً تنظیم باشد.",
            "در تنظیمات کانفیگ یا در تنظیمات عمومی نرم‌افزار، تیک گزینه **Allow Insecure** (مجوز ارتباط بدون تایید گواهی) را موقتاً روشن نمایید.",
            "یک بار اشتراک خود را با زدن دکمه **Update Subscription** به‌روزرسانی کنید تا آخرین مشخصات گواهی معتبر دریافت گردد."
        ]
    },
    {
        "slug": "windows_port_firewall",
        "title": "اشغال بودن پورت‌های ویندوز (Port 10808 Occupied) و خطای فایروال",
        "subtitle": "رفع ارورهای Bind Port و مسدودی هسته v2rayN در کامپیوتر",
        "icon": "fab fa-windows",
        "color": "primary",
        "problem": "در نرم‌افزار v2rayN یا Nekoray ویندوز پیام `Failed to start core: listen tcp 127.0.0.1:10808: bind: address already in use` ظاهر می‌شود.",
        "cause": "نرم‌افزار فیلترشکن دیگری یا فرآیندی در ویندوز پورت پیش‌فرض ۱۰۸۰۸ را اشغال کرده است.",
        "solution_steps": [
            "سایر فیلترشکن‌ها و برنامه‌های پروکسی (مانند سایفون، لنترن یا نسخه‌های دیگر v2ray) را کاملاً ببندید (در Task Manager بررسی کنید).",
            "در نرم‌افزار v2rayN از منوی بالای صفحه وارد **Settings > OptionSetting** شوید. مقدار **Local SOCKS Port** را از 10808 به **10809** یا **20808** تغییر داده و Confirm بزنید.",
            "نرم‌افزار را حتماً با کلیک راست و انتخاب **Run as administrator** اجرا کنید."
        ]
    },
    {
        "slug": "ios_connecting_loop",
        "title": "گیر کردن در وضعیت در حال اتصال (Connecting Loop) در آیفون",
        "subtitle": "رفع مشکل وصل نشدن Streisand و Shadowrocket در سیستم‌عامل iOS",
        "icon": "fab fa-apple",
        "color": "dark",
        "problem": "در آیفون دکمه اتصال را روشن می‌کنید اما روی حالت Connecting می‌ماند و علامت VPN ظاهر نمی‌شود.",
        "cause": "سیستم‌عامل iOS گاهی در بازنشانی اینترفیس شبکه دچار بن‌بست موقت می‌شود.",
        "solution_steps": [
            "**ترفند حالت پرواز:** کنترل سنتر آیفون را باز کرده، آیکون حالت پرواز (Airplane Mode) را روشن کنید، ۱۰ ثانیه صبر کرده و سپس خاموش کنید.",
            "**ریست پروفایل VPN:** به Settings آیفون > General > VPN & Device Management بروید. روی آیکون (i) کنار نام نرم‌افزار کلیک کرده و **Delete VPN** را بزنید. سپس وارد نرم‌افزار شوید و مجدداً اتصال را بزنید تا پروفایل تازه ساخته شود.",
            "در اپلیکیشن Streisand با پایین کشیدن صفحه (Pull to refresh) سرورها را به‌روزرسانی کرده و سرور دیگری را انتخاب فرمایید."
        ]
    },
    {
        "slug": "ipv6_leak_conflict",
        "title": "اختلال پروتکل IPv6 در اینترنت ثابت (مخابرات، شاتل و ADSL)",
        "subtitle": "حل قطعی اینستاگرام و سایت‌ها در زمان اتصال به وای‌فای خانگی",
        "icon": "fas fa-network-wired",
        "color": "info",
        "problem": "روی اینترنت همراه وصل می‌شود اما روی اینترنت وای‌فای خانه یا مودم مخابرات متصل نمی‌شود یا بعضی برنامه‌ها لود نمی‌شوند.",
        "cause": "تداخل آدرس‌دهی IPv6 ارائه‌دهنده اینترنت و عدم عبور بسته‌های IPv6 از هسته پروکسی.",
        "solution_steps": [
            "در تنظیمات نرم‌افزار VPN خود، گزینه **Enable IPv6** را خاموش (Disable) کنید تا تمام اتصالات اجباراً از IPv4 عبور کنند.",
            "در گوشی همراه، در بخش تنظیمات وای‌فای، یک‌بار Forget Network زده و مجدداً متصل شوید.",
            "در ویندوز، وارد تنظیمات کارت شبکه (Network Connections) شده، روی وای‌فای راست‌کلیک کرده، Properties بزنید و تیک گزینه **Internet Protocol Version 6 (TCP/IPv6)** را بردارید و OK کنید."
        ]
    }
]

# ═══════════════════════════════════════════════════════════════════════
# ساختار ویزاردهای تعاملی قدم‌به‌قدم (Interactive Step-by-Step Wizards)
# ═══════════════════════════════════════════════════════════════════════

STEP_BY_STEP_TROUBLESHOOT = {
    "title": "سامانه هوشمند ویزارد عیب‌یابی و حل مشکلات اتصال",
    "description": "راهنمای تعاملی و مرحله‌به‌مرحله جهت رفع سریع هرگونه مشکل در اتصال به VPN",
    "steps": [
        {
            "id": "device",
            "step_number": 1,
            "title": "انتخاب دستگاه در حال عیب‌یابی",
            "subtitle": "دستگاهی که قصد دارید مشکل اتصال آن را برطرف کنید انتخاب نمایید:",
            "icon": "fas fa-mobile-screen-button",
            "options": [
                {"id": "android", "label": "گوشی یا تبلت اندروید 📱", "platform": "android", "icon": "fab fa-android"},
                {"id": "ios", "label": "آیفون یا آیپد (iOS) 🍏", "platform": "ios", "icon": "fab fa-apple"},
                {"id": "windows", "label": "کامپیوتر یا لپ‌تاپ ویندوز 💻", "platform": "windows", "icon": "fab fa-windows"},
                {"id": "macos", "label": "مک‌بوک یا رایانه اپل (Mac) 🖥️", "platform": "macos", "icon": "fas fa-laptop"},
                {"id": "tv", "label": "تلویزیون هوشمند یا اندروید‌باکس 📺", "platform": "tv", "icon": "fas fa-tv"}
            ]
        },
        {
            "id": "package",
            "step_number": 2,
            "title": "بررسی فعال بودن بسته اینترنت سیم‌کارت یا سرویس خانگی",
            "subtitle": "گاهی با تمام شدن حجم بسته یا رسیدن به مگابایت‌های پایانی، اپراتور پکت‌ها را مسدود می‌کند.",
            "icon": "fas fa-sim-card",
            "instruction": "ابتدا استعلام بسته اینترنت خود را با کدهای زیر بگیرید:\n• همراه اول: `#10*100*`\n• ایرانسل: `#4*1*555*`\n• رایتل: `#144*`\n• اینترنت خانگی: بررسی داشبورد شرکت ارائه‌دهنده (شاتل، مخابرات، آسیاتک و...)",
            "buttons": [
                {"action": "next", "label": "بسته اینترنت من فعال است و حجم کافی دارد 🟢", "style": "success"},
                {"action": "resolve_pkg", "label": "بسته‌ام تمام شده بود / نیاز به خرید بسته دارم 🔴", "style": "warning"}
            ]
        },
        {
            "id": "subscription",
            "step_number": 3,
            "title": "بررسی انقضا و حجم باقی‌مانده اشتراک VPN",
            "subtitle": "اطمینان حاصل کنید که حجم گیگابایتی یا مهلت روزهای اشتراک شما تمام نشده باشد.",
            "icon": "fas fa-shield-halved",
            "instruction": "وارد ربات تلگرام شده و دکمه **«اشتراک‌های من»** را بزنید یا لینک اشتراک را در مرورگر باز کنید. از باقی ماندن گیگابایت مصرفی و عدم عبور از تاریخ انقضا اطمینان حاصل فرمایید.",
            "buttons": [
                {"action": "next", "label": "اشتراکم معتبر است و زمان و حجم کافی دارد ✅", "style": "success"},
                {"action": "resolve_sub", "label": "حجم یا زمان اشتراکم به پایان رسیده / خرید شارژ 🔄", "style": "primary"}
            ]
        },
        {
            "id": "time",
            "step_number": 4,
            "title": "بررسی تنظیم دقیق ساعت و تاریخ دستگاه (Time Synchronization)",
            "subtitle": "پروتکل‌های نسل جدید در صورت اختلاف بیش از ۶۰ ثانیه با ساعت جهانی به هیچ عنوان متصل نمی‌شوند.",
            "icon": "fas fa-clock",
            "instruction": "وارد تنظیمات ساعت دستگاه خود شده و گزینه **تنظیم خودکار (Set Automatically)** را یک بار خاموش و مجدداً روشن کنید. در ویندوز روی دکمه Sync Now بزنید.",
            "has_live_clock_checker": True,
            "buttons": [
                {"action": "next", "label": "ساعت و تاریخ دقیقاً با ساعت رسمی تنظیم است ⏱️", "style": "success"}
            ]
        },
        {
            "id": "operator",
            "step_number": 5,
            "title": "انتخاب اپراتور و اعمال تنظیمات دور زدن فیلترینگ شدید",
            "subtitle": "اپراتور اینترنتی که در حال حاضر به آن متصل هستید را انتخاب کنید:",
            "icon": "fas fa-tower-broadcast",
            "branches": [
                {
                    "operator_id": "mci_irancell",
                    "title": "همراه اول یا ایرانسل (دیتای سیم‌کارت) 📶",
                    "guide": "به دلیل فیلترینگ شدید DPI در این دو اپراتور، حتماً وارد تنظیمات نرم‌افزار خود (v2rayNG یا Hiddify) شده و بخش **Fragment** را روشن کنید و مقادیر packets را روی `1-3` قرار دهید.",
                    "confirm_label": "تنظیمات Fragment را اعمال کردم 🛡️"
                },
                {
                    "operator_id": "wifi_adsl",
                    "title": "اینترنت خانگی / وای‌فای (مخابرات، شاتل، فیبر نوری، آسیاتک) 🌐",
                    "guide": "در اینترنت خانگی تداخل IPv6 و مسمومیت DNS رایج است. در تنظیمات برنامه VPN گزینه **Enable IPv6** را خاموش کنید و Remote DNS را روی `https://1.1.1.1/dns-query` قرار دهید.",
                    "confirm_label": "تنظیمات DNS و IPv6 را اعمال کردم 🌐"
                },
                {
                    "operator_id": "rightel_other",
                    "title": "رایتل یا سایر ارائه‌دهندگان 📱",
                    "guide": "یک بار گوشی را به مدت ۱۰ ثانیه روی حالت پرواز (Airplane Mode) برده و بازگردانید تا آی‌پی تمیز از اپراتور دریافت شود.",
                    "confirm_label": "حالت پرواز را انجام دادم ✈️"
                }
            ]
        },
        {
            "id": "update_ping",
            "step_number": 6,
            "title": "به‌روزرسانی سرورها و دریافت لیست کانفیگ‌های تازه (Update Subscription)",
            "subtitle": "کانفیگ‌ها به صورت پویا توسط سرورهای ما به‌روزرسانی می‌شوند.",
            "icon": "fas fa-arrows-rotate",
            "instruction": "در نرم‌افزار خود دکمه بروزرسانی اشتراک (Update Subscription یا کشیدن صفحه به پایین در آیفون) را بزنید و سپس تست پینگ واقعی (Real Delay) بگیرید. سروری که کمترین پینگ عددی سبز رنگ دارد را انتخاب کنید.",
            "buttons": [
                {"action": "next", "label": "سرورها آپدیت شدند و پینگ سبز دریافت کردم 📶", "style": "success"},
                {"action": "retry_update", "label": "سرورها آپدیت نشدند / پینگ ناموفق (-1) دارم ⚠️", "style": "warning"}
            ]
        },
        {
            "id": "finalize",
            "step_number": 7,
            "title": "نتیجه نهایی اتصال و تست مرورگر",
            "subtitle": "دکمه اتصال را روشن کرده و یک سایت مانند گوگل یا یوتیوب را در مرورگر باز کنید:",
            "icon": "fas fa-flag-checkered",
            "instruction": "آیا موفق به اتصال شدید و اینترنت بدون فیلتر فعال شد؟",
            "buttons": [
                {"action": "success", "label": "مشکل برطرف شد و با موفقیت متصل شدم! 🎉", "style": "success"},
                {"action": "support", "label": "هنوز متصل نیستم / ارسال گزارش به پشتیبانی 🎧", "style": "danger"}
            ]
        }
    ]
}

STEP_BY_STEP_CONNECTION = {
    "title": "راهنمای گام‌به‌گام اتصال به سرویس",
    "description": "آموزش مرحله‌به‌مرحله راه‌اندازی و اتصال آسان برای تمامی دستگاه‌ها",
    "steps": [
        {
            "id": "step_platform",
            "step_number": 1,
            "title": "گام اول: سیستم‌عامل دستگاه خود را انتخاب کنید",
            "subtitle": "دستگاهی که می‌خواهید روی آن متصل شوید چیست؟",
            "icon": "fas fa-laptop-mobile"
        },
        {
            "id": "step_app",
            "step_number": 2,
            "title": "گام دوم: نرم‌افزار پیشنهادی را دانلود و نصب کنید",
            "subtitle": "نرم‌افزار سازگار و رسمی را از لینک‌های معتبر دانلود و باز نمایید.",
            "icon": "fas fa-download",
            "confirm_label": "نرم‌افزار را دانلود و نصب کردم 📲"
        },
        {
            "id": "step_import",
            "step_number": 3,
            "title": "گام سوم: وارد کردن لینک اشتراک در نرم‌افزار (Import)",
            "subtitle": "لینک اشتراک خود را کپی کرده و در برنامه با علامت (+) وارد نمایید.",
            "icon": "fas fa-file-import",
            "confirm_label": "لینک اشتراک را در برنامه وارد کردم 📥"
        },
        {
            "id": "step_update",
            "step_number": 4,
            "title": "گام چهارم: به‌روزرسانی لیست سرورها و تست پینگ",
            "subtitle": "گزینه Update subscription را لمس کرده و پینگ سرورها را بررسی فرمایید.",
            "icon": "fas fa-rotate",
            "confirm_label": "سرورها آپدیت شدند و پینگ سبز دیدم 🔄"
        },
        {
            "id": "step_connect",
            "step_number": 5,
            "title": "گام پنجم: روشن کردن دکمه اتصال و تایید دسترسی",
            "subtitle": "روی دکمه اتصال کلیک کنید و در پنجره امنیتی سیستم‌عامل دکمه تایید (OK / Allow) را بزنید.",
            "icon": "fas fa-power-off",
            "confirm_label": "دکمه اتصال را روشن کردم و متصل شد 🚀"
        }
    ]
}
