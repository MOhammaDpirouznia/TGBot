#!/usr/bin/env python3
"""
🌍 ماژول چندزبانه سیستم ربات HiddiBot (Internationalization / i18n)
پشتیبانی کامل از ۴ زبان:
- 🇮🇷 فارسی (fa)
- 🇬🇧 English (en)
- 🇷🇺 Русский (ru)
- 🇨🇳 中文 (zh)
"""

from telegram import KeyboardButton, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

SUPPORTED_LANGUAGES = {
    "fa": {"name": "فارسی", "flag": "🇮🇷", "title": "🇮🇷 فارسی"},
    "en": {"name": "English", "flag": "🇬🇧", "title": "🇬🇧 English"},
    "ru": {"name": "Русский", "flag": "🇷🇺", "title": "🇷🇺 Русский"},
    "zh": {"name": "中文", "flag": "🇨🇳", "title": "🇨🇳 中文"},
}

STRINGS = {
    # ─── مینی‌اپ و کیف پول ───
    "btn_webapp": {
        "fa": "📱 پنل هوشمند من (Mini App)",
        "en": "📱 Smart Panel (Mini App)",
        "ru": "📱 Смарт-панель (Mini App)",
        "zh": "📱 智能面板 (Mini App)",
    },
    "btn_wallet": {
        "fa": "💰 کیف پول و موجودی",
        "en": "💰 Wallet & Balance",
        "ru": "💰 Кошелек и баланс",
        "zh": "💰 钱包与余额",
    },
    # ─── انتخاب زبان ───
    "lang_select_prompt": {
        "fa": "🌐 لطفاً زبان مورد نظر خود را انتخاب کنید:\n\n🇬🇧 Please select your preferred language:\n🇷🇺 Пожалуйста, выберите язык:\n🇨🇳 请选择您的语言：",
        "en": "🌐 Please select your preferred language:",
        "ru": "🌐 Пожалуйста, выберите язык:",
        "zh": "🌐 请选择您的首选语言：",
    },
    "lang_changed": {
        "fa": "✅ زبان با موفقیت به **فارسی** تغییر یافت.",
        "en": "✅ Language successfully changed to **English**.",
        "ru": "✅ Язык успешно изменен на **Русский**.",
        "zh": "✅ 语言已成功更改为 **中文**。",
    },

    # ─── دکمه‌های منوی اصلی ───
    "btn_buy": {
        "fa": "🛒 خرید اشتراک",
        "en": "🛒 Buy Subscription",
        "ru": "🛒 Купить подписку",
        "zh": "🛒 购买订阅",
    },
    "btn_test": {
        "fa": "🧪 اشتراک تست",
        "en": "🧪 Free Trial",
        "ru": "🧪 Тестовый доступ",
        "zh": "🧪 免费试用",
    },
    "btn_renew": {
        "fa": "🔄 تمدید اشتراک",
        "en": "🔄 Renew Subscription",
        "ru": "🔄 Продлить подписку",
        "zh": "🔄 续费订阅",
    },
    "btn_status": {
        "fa": "📊 وضعیت اشتراک",
        "en": "📊 Subscription Status",
        "ru": "📊 Статус подписки",
        "zh": "📊 订阅状态",
    },
    "btn_link": {
        "fa": "🔗 لینک اتصال",
        "en": "🔗 Connection Link",
        "ru": "🔗 Ссылка для подключения",
        "zh": "🔗 连接链接",
    },
    "btn_payments": {
        "fa": "🧾 پرداخت‌های من",
        "en": "🧾 My Payments",
        "ru": "🧾 Мои платежи",
        "zh": "🧾 我的账单",
    },
    "btn_referral": {
        "fa": "👥 زیرمجموعه‌گیری",
        "en": "👥 Referral Program",
        "ru": "👥 Реферальная программа",
        "zh": "👥 推广返利",
    },
    "btn_support": {
        "fa": "💬 پشتیبانی",
        "en": "💬 Support",
        "ru": "💬 Поддержка",
        "zh": "💬 在线客服",
    },
    "btn_language": {
        "fa": "🌐 زبان / Language",
        "en": "🌐 Language",
        "ru": "🌐 Язык",
        "zh": "🌐 语言设置",
    },
    "btn_admin": {
        "fa": "🔧 پنل مدیریت",
        "en": "🔧 Admin Panel",
        "ru": "🔧 Панель управления",
        "zh": "🔧 管理后台",
    },
    "btn_back": {
        "fa": "◀️ بازگشت",
        "en": "◀️ Back",
        "ru": "◀️ Назад",
        "zh": "◀️ 返回",
    },
    "btn_cancel": {
        "fa": "❌ انصراف",
        "en": "❌ Cancel",
        "ru": "❌ Отмена",
        "zh": "❌ 取消",
    },
    "btn_confirm_send": {
        "fa": "✅ تایید و ارسال",
        "en": "✅ Confirm & Submit",
        "ru": "✅ Подтвердить и отправить",
        "zh": "✅ 确认并提交",
    },
    "btn_copy_help": {
        "fa": "📋 کپی لینک",
        "en": "📋 Copy Link",
        "ru": "📋 Скопировать ссылку",
        "zh": "📋 复制链接",
    },
    "btn_send_contact": {
        "fa": "📱 تایید و ارسال شماره تلفن",
        "en": "📱 Share & Verify Phone Number",
        "ru": "📱 Отправить номер телефона",
        "zh": "📱 发送并验证手机号",
    },
    "contact_auth_prompt": {
        "fa": "🔐 **احراز هویت و فعال‌سازی حساب کاربری**\n\nبرای امنیت و دسترسی به خدمات ربات، لطفاً با لمس دکمه زیر شماره تماس اکانت تلگرام خود را ارسال نمایید تا حسابتان فعال شود:",
        "en": "🔐 **Account Verification**\n\nFor security and account activation, please tap the button below to share and verify your Telegram phone number:",
        "ru": "🔐 **Верификация аккаунта**\n\nДля активации аккаунта отправьте ваш номер телефона с помощью кнопки ниже:",
        "zh": "🔐 **账户身份验证**\n\n为了激活您的账户，请点击下方按钮发送并验证您的 Telegram 手机号码：",
    },
    "contact_auth_success": {
        "fa": "✅ **احراز هویت شما با موفقیت انجام شد!**\n\nشماره تماس ثبت‌شده: `{phone}`\nاکنون می‌توانید از تمامی خدمات ربات استفاده فرمایید.",
        "en": "✅ **Verification successful!**\n\nRegistered Phone: `{phone}`\nYou can now use all bot features.",
        "ru": "✅ **Верификация успешно завершена!**\n\nНомер телефона: `{phone}`",
        "zh": "✅ **验证成功！**\n\n已登记手机号：`{phone}`",
    },
    "contact_auth_invalid": {
        "fa": "❌ خطا: لطفاً فقط شماره اختصاصی اکانت تلگرام خودتان را با لمس دکمه زیر ارسال فرمایید.",
        "en": "❌ Error: Please send only your own Telegram phone number using the button below.",
        "ru": "❌ Ошибка: Пожалуйста, отправьте именно ваш номер телефона с помощью кнопки.",
        "zh": "❌ 错误：请仅通过下方按钮发送您本人的 Telegram 手机号码。",
    },
    "contact_auth_required": {
        "fa": "⚠️ برای استفاده از این بخش، ابتدا باید احراز هویت شماره تلفن خود را تکمیل نمایید.",
        "en": "⚠️ Please verify your phone number first to access this feature.",
        "ru": "⚠️ Для доступа к этому разделу сначала подтвердите номер телефона.",
        "zh": "⚠️ 请先完成手机号码验证以使用此功能。",
    },
    "btn_quick_connect": {
        "fa": "🌐 صفحه کاربری و اتصال سریع",
        "en": "🌐 Quick Connect Portal",
        "ru": "🌐 Быстрое подключение",
        "zh": "🌐 快速连接面板",
    },
    "btn_single_link": {
        "fa": "⚡ تبدیل به لینک تکی",
        "en": "⚡ Single Direct Link",
        "ru": "⚡ Прямая ссылка (Single)",
        "zh": "⚡ 转换为单节点直连链接",
    },
    "single_link_card_title": {
        "fa": "⚡ **لینک اتصال مستقیم (تکی):**",
        "en": "⚡ **Single Direct Connection Link:**",
        "ru": "⚡ **Прямая ссылка для подключения (Single):**",
        "zh": "⚡ **单节点直接连接配置：**",
    },
    "single_link_card_hint": {
        "fa": "💡 **راهنمای استفاده از لینک تکی:**\n• این لینک به صورت مستقیم کانفیگ اتصال اختصاصی شما را در بر دارد.\n• لینک بالا را کپی کرده و در نرم‌افزار خود Import نمایید.",
        "en": "💡 **Single Link Guide:**\n• This is a direct configuration link containing your credentials.\n• Copy the link above and import it into your VPN client.",
        "ru": "💡 **Инструкция:**\n• Это прямая ссылка с вашей персональной конфигурацией.\n• Скопируйте ссылку выше и импортируйте в ваше приложение.",
        "zh": "💡 **单节点配置说明：**\n• 此链接为包含您专属配置的直连节点。\n• 复制上方链接后直接导入客户端即可连接。",
    },

    # ─── پیام خوش‌آمدگویی ───
    "welcome_msg": {
        "fa": """سلام {name}! 👋

به ربات هوشمند مدیریت و خرید VPN خوش آمدید!

از منوی زیر می‌توانید:
• 🛒 خرید اشتراک جدید
• 🧪 اشتراک تست (رایگان)
• 🔄 تمدید اشتراک
• 📊 مشاهده وضعیت و حجم لحظه‌ای اشتراک
• 🔗 دریافت لینک اتصال و بارکد QR
• 🧾 مشاهده سوابق و وضعیت پرداخت‌ها
• 👥 زیرمجموعه‌گیری و کسب درآمد
• 💬 پشتیبانی و ارسال تیکت
• 🌐 تغییر زبان ربات
""",
        "en": """Hello {name}! 👋

Welcome to our High-Speed VPN Management Bot!

You can easily:
• 🛒 Buy a new VPN subscription
• 🧪 Get a Free Trial
• 🔄 Renew your existing subscription
• 📊 Check live traffic usage & remaining days
• 🔗 Get connection links & QR codes
• 🧾 View your payment & order history
• 👥 Invite friends & earn rewards
• 💬 Contact 24/7 Support
• 🌐 Change bot language
""",
        "ru": """Привет, {name}! 👋

Добро пожаловать в бот управления высокоскоростным VPN!

Вам доступны следующие возможности:
• 🛒 Покупка новой подписки
• 🧪 Бесплатный тестовый период
• 🔄 Продление действующей подписки
• 📊 Проверка оставшегося трафика и дней
• 🔗 Получение ссылок для подключения и QR-кодов
• 🧾 История платежей и заказов
• 👥 Реферальная программа и заработок
• 💬 Круглосуточная поддержка
• 🌐 Смена языка интерфейса
""",
        "zh": """您好，{name}！ 👋

欢迎使用高速 VPN 智能管理与购买机器人！

您可以随时进行以下操作：
• 🛒 购买全新 VPN 订阅
• 🧪 领取免费试用
• 🔄 续费现有订阅
• 📊 实时查询剩余流量与到期天数
• 🔗 获取连接链接与二维码
• 🧾 查看历史账单与订单状态
• 👥 邀请好友并赚取佣金
• 💬 联系全天候在线客服
• 🌐 切换机器人语言
""",
    },

    "choose_option": {
        "fa": "لطفاً یکی از گزینه‌ها را انتخاب کنید:",
        "en": "Please select an option from the menu below:",
        "ru": "Пожалуйста, выберите действие из меню ниже:",
        "zh": "请从下方菜单中选择一项操作：",
    },

    # ─── اشتراک تست ───
    "trial_generating": {
        "fa": "⏳ در حال ساخت اشتراک تست رایگان شما...",
        "en": "⏳ Creating your free trial subscription...",
        "ru": "⏳ Создание вашей тестовой подписки...",
        "zh": "⏳ 正在为您创建免费试用订阅...",
    },
    "trial_already_used": {
        "fa": "❌ شما قبلاً از اشتراک تست رایگان استفاده کرده‌اید!\n\n💡 برای استفاده از سرویس، می‌توانید از دکمه «🛒 خرید اشتراک» استفاده کنید.",
        "en": "❌ You have already used your free trial!\n\n💡 Please use the '🛒 Buy Subscription' button to purchase a plan.",
        "ru": "❌ Вы уже использовали бесплатный тестовый период!\n\n💡 Чтобы продолжить, воспользуйтесь кнопкой «🛒 Купить подписку».",
        "zh": "❌ 您已经使用过免费试用订阅！\n\n💡 请点击「🛒 购买订阅」以选择并购买套餐。",
    },
    "trial_success_title": {
        "fa": "🎉 **اشتراک تست رایگان شما فعال شد!**",
        "en": "🎉 **Your Free Trial is Ready!**",
        "ru": "🎉 **Ваш тестовый доступ активирован!**",
        "zh": "🎉 **您的免费试用订阅已就绪！**",
    },
    "trial_details": {
        "fa": "📋 پلن: **تست رایگان**\n📊 حجم: **{data_limit} گیگابایت**\n⏰ مدت: **{duration} روز**",
        "en": "📋 Plan: **Free Trial**\n📊 Traffic: **{data_limit} GB**\n⏰ Validity: **{duration} Days**",
        "ru": "📋 Тариф: **Бесплатный тест**\n📊 Трафик: **{data_limit} ГБ**\n⏰ Срок: **{duration} дня**",
        "zh": "📋 套餐：**免费试用**\n📊 流量：**{data_limit} GB**\n⏰ 时长：**{duration} 天**",
    },

    # ─── وضعیت اشتراک ───
    "status_checking": {
        "fa": "⏳ در حال استعلام لحظه‌ای حجم و روزهای مانده از سرور...",
        "en": "⏳ Querying real-time traffic and expiry from server...",
        "ru": "⏳ Запрос актуального трафика и срока действия с сервера...",
        "zh": "⏳ 正在从服务器实时查询流量与到期时间...",
    },
    "status_empty": {
        "fa": "❌ شما هنوز هیچ اشتراکی ندارید!\n\n💡 برای خرید، روی «🛒 خرید اشتراک» کلیک کنید.",
        "en": "❌ You don't have any active subscriptions yet!\n\n💡 Click '🛒 Buy Subscription' to get started.",
        "ru": "❌ У вас пока нет активных подписок!\n\n💡 Нажмите «🛒 Купить подписку», чтобы оформить заказ.",
        "zh": "❌ 您目前没有任何订阅！\n\n💡 请点击「🛒 购买订阅」开始使用。",
    },
    "status_title": {
        "fa": "📊 **وضعیت لحظه‌ای اشتراک‌های شما:**\n\n",
        "en": "📊 **Real-time Status of Your Subscriptions:**\n\n",
        "ru": "📊 **Текущий статус ваших подписок:**\n\n",
        "zh": "📊 **您的订阅实时状态：**\n\n",
    },
    "status_active": {
        "fa": "🟢 فعال",
        "en": "🟢 Active",
        "ru": "🟢 Активен",
        "zh": "🟢 生效中",
    },
    "status_expired": {
        "fa": "🔴 منقضی",
        "en": "🔴 Expired",
        "ru": "🔴 Истек",
        "zh": "🔴 已到期",
    },
    "status_inactive": {
        "fa": "⚪ غیرفعال",
        "en": "⚪ Inactive",
        "ru": "⚪ Неактивен",
        "zh": "⚪ 已停用",
    },
    "status_traffic": {
        "fa": "📊 مصرف: **{used}** از **{limit}** گیگابایت\n   {emoji} `{bar}` {percent}%\n   💾 باقیمانده: **{remaining}** گیگابایت",
        "en": "📊 Usage: **{used}** of **{limit}** GB\n   {emoji} `{bar}` {percent}%\n   💾 Remaining: **{remaining}** GB",
        "ru": "📊 Расход: **{used}** из **{limit}** ГБ\n   {emoji} `{bar}` {percent}%\n   💾 Осталось: **{remaining}** ГБ",
        "zh": "📊 已用流量：**{used}** / **{limit}** GB\n   {emoji} `{bar}` {percent}%\n   💾 剩余流量：**{remaining}** GB",
    },
    "status_unlimited": {
        "fa": "📊 مصرف: **{used}** گیگابایت (حجم نامحدود)",
        "en": "📊 Usage: **{used}** GB (Unlimited Traffic)",
        "ru": "📊 Расход: **{used}** ГБ (Безлимитный трафик)",
        "zh": "📊 已用流量：**{used}** GB（无限流量）",
    },
    "status_days_left": {
        "fa": " (⏰ **{days} روز مانده**)",
        "en": " (⏰ **{days} days left**)",
        "ru": " (⏰ **Осталось {days} дн.**)",
        "zh": " (⏰ **剩余 {days} 天**)",
    },

    # ─── پرداخت‌ها ───
    "payments_title": {
        "fa": "🧾 **سوابق و گزارش پرداخت‌های شما ({count} تراکنش):**\n\n",
        "en": "🧾 **Your Payment History ({count} transactions):**\n\n",
        "ru": "🧾 **История ваших платежей ({count} транзакций):**\n\n",
        "zh": "🧾 **您的支付记录（共 {count} 笔）：**\n\n",
    },
    "payments_empty": {
        "fa": "🧾 **سوابق پرداخت:**\n\nشما تاکنون هیچ پرداخت یا تراکنشی ثبت نکرده‌اید.\n\n💡 برای خرید اشتراک از «🛒 خرید اشتراک» استفاده کنید.",
        "en": "🧾 **Payment History:**\n\nNo payments recorded yet.\n\n💡 Click '🛒 Buy Subscription' to get started.",
        "ru": "🧾 **История платежей:**\n\nПлатежи отсутствуют.\n\n💡 Воспользуйтесь «🛒 Купить подписку» для покупки.",
        "zh": "🧾 **账单记录：**\n\n暂无任何支付记录。\n\n💡 点击「🛒 购买订阅」立即开通服务。",
    },

    # ─── لینک اتصال ───
    "link_no_sub": {
        "fa": "❌ شما هنوز هیچ اشتراکی ندارید!\n\n💡 برای خرید، روی «🛒 خرید اشتراک» کلیک کنید.",
        "en": "❌ You don't have any subscription link yet!\n\n💡 Click '🛒 Buy Subscription' to purchase.",
        "ru": "❌ У вас нет активных подписок для подключения!\n\n💡 Нажмите «🛒 Купить подписку».",
        "zh": "❌ 您尚未拥有任何连接链接！\n\n💡 请点击「🛒 购买订阅」购买。",
    },
    "link_card_title": {
        "fa": "🔗 **لینک اتصال اشتراک شما:**",
        "en": "🔗 **Your Connection Link:**",
        "ru": "🔗 **Ваша ссылка для подключения:**",
        "zh": "🔗 **您的连接链接：**",
    },
    "link_card_hint": {
        "fa": "💡 **راهنمای اتصال سریع:**\n• لینک بالا را لمس کنید تا در کلیپ‌بورد کپی شود.\n• وارد نرم‌افزار (Hiddify / v2rayNG / Streisand / Clash) شوید و آن را اضافه کنید.",
        "en": "💡 **Quick Setup Guide:**\n• Tap the link above to copy it.\n• Open your client app (Hiddify / v2rayNG / Streisand / Clash / Shadowrocket) and import it.",
        "ru": "💡 **Быстрая настройка:**\n• Нажмите на ссылку выше, чтобы скопировать.\n• Откройте приложение (Hiddify / v2rayNG / Streisand / Clash) и импортируйте подписку.",
        "zh": "💡 **快速配置说明：**\n• 点击上方链接自动复制到剪贴板。\n• 打开客户端（Hiddify / v2rayNG / Streisand / Clash / Shadowrocket）粘贴导入即可。",
    },

    # ─── فرآیند خرید و پرداخت ───
    "plans_select_prompt": {
        "fa": "📦 **لطفاً پلن مورد نظر خود را انتخاب کنید:**",
        "en": "📦 **Please select your desired plan:**",
        "ru": "📦 **Пожалуйста, выберите подходящий тариф:**",
        "zh": "📦 **请选择您心仪的套餐：**",
    },
    "plan_unlimited_label": {
        "fa": "نامحدود",
        "en": "Unlimited",
        "ru": "Безлимит",
        "zh": "无限流量",
    },
    "plan_days_label": {
        "fa": "روز",
        "en": "days",
        "ru": "дн.",
        "zh": "天",
    },
    "plan_currency": {
        "fa": "تومان",
        "en": "Tomans",
        "ru": "туманов",
        "zh": "托曼",
    },

    # ─── زیرمجموعه‌گیری ───
    "referral_title": {
        "fa": """👥 **سیستم همکاری در فروش و زیرمجموعه‌گیری**

با اشتراک‌گذاری لینک اختصاصی خود با دوستانتان، به ازای هر خرید آنها پاداش نقدی دریافت کنید!

🔗 **لینک دعوت اختصاصی شما:**
`{ref_link}`

📊 **آمار شما:**
• تعداد دعوت‌ها: **{count} نفر**
• مجموع پاداش دریافتی: **{earnings:,} تومان**
""",
        "en": """👥 **Referral & Affiliate Program**

Invite your friends with your exclusive link and earn commission on every purchase they make!

🔗 **Your Referral Link:**
`{ref_link}`

📊 **Your Statistics:**
• Total Invited: **{count} users**
• Total Earnings: **{earnings:,} Tomans**
""",
        "ru": """👥 **Реферальная программа**

Приглашайте друзей по вашей персональной ссылке и получайте бонусы за каждую их покупку!

🔗 **Ваша реферальная ссылка:**
`{ref_link}`

📊 **Ваша статистика:**
• Приглашено пользователей: **{count}**
• Всего заработано: **{earnings:,} туманов**
""",
        "zh": """👥 **推广邀请返利计划**

分享您的专属邀请链接给好友，好友完成购买即可获得丰厚现金佣金！

🔗 **您的专属邀请链接：**
`{ref_link}`

📊 **您的推广数据：**
• 成功邀请人数：**{count} 人**
• 累计获得佣金：**{earnings:,} 托曼**
""",
    },

    # ─── پشتیبانی ───
    "support_title": {
        "fa": """💬 **مرکز پشتیبانی ۲۴ ساعته**

تیم پشتیبانی ما همواره آماده پاسخگویی و رفع مشکلات شماست.

برای ارسال تیکت و پیام جدید، دکمه زیر را لمس کنید:
""",
        "en": """💬 **24/7 Customer Support**

Our support team is always ready to assist you.

To open a new support ticket, please tap the button below:
""",
        "ru": """💬 **Круглосуточная служба поддержки**

Наша команда поддержки всегда готова помочь вам.

Чтобы отправить тикет или сообщение, нажмите кнопку ниже:
""",
        "zh": """💬 **全天候在线客服中心**

我们的专业客服团队随时为您解答疑问并解决使用问题。

点击下方按钮即可提交新的客服工单：
""",
    },
    "support_btn_new": {
        "fa": "✉️ ارسال تیکت جدید",
        "en": "✉️ New Ticket",
        "ru": "✉️ Создать тикет",
        "zh": "✉️ 提交新工单",
    },
    "support_btn_my_tickets": {
        "fa": "📋 تیکت‌های قبلی من",
        "en": "📋 My Tickets",
        "ru": "📋 Мои тикеты",
        "zh": "📋 我的工单记录",
    },
    "support_prompt_msg": {
        "fa": "📝 لطفاً پیام یا مشکل خود را به صورت متن یا عکس ارسال فرمایید:",
        "en": "📝 Please type your message or send a screenshot describing your issue:",
        "ru": "📝 Пожалуйста, напишите ваше сообщение или отправьте скриншот:",
        "zh": "📝 请输入您的咨询内容或发送相关截图：",
    },
    "support_ticket_sent": {
        "fa": "✅ پیام شما ثبت و برای پشتیبانی ارسال شد. به زودی پاسخ برای شما ارسال خواهد شد.",
        "en": "✅ Your message has been sent to our support team. We will reply shortly.",
        "ru": "✅ Ваше сообщение отправлено в поддержку. Мы ответим вам в ближайшее время.",
        "zh": "✅ 您的工单已成功提交至客服团队，我们将尽快为您处理并回复。",
    },

    # ─── عملیات عمومی ───
    "op_cancelled": {
        "fa": "❌ عملیات لغو شد.",
        "en": "❌ Operation cancelled.",
        "ru": "❌ Действие отменено.",
        "zh": "❌ 操作已取消。",
    },
    "membership_required": {
        "fa": "⚠️ برای استفاده از ربات، لطفاً ابتدا در کانال‌های زیر عضو شوید:",
        "en": "⚠️ To use this bot, please join our official channels first:",
        "ru": "⚠️ Для использования бота, пожалуйста, подпишитесь на каналы:",
        "zh": "⚠️ 请先加入以下官方频道以解锁机器人所有功能：",
    },
    "membership_check_btn": {
        "fa": "✅ عضو شدم (بررسی)",
        "en": "✅ I Have Joined",
        "ru": "✅ Я подписался",
        "zh": "✅ 我已加入（验证）",
    },
}


def t(key: str, lang: str = "fa", **kwargs) -> str:
    """دریافت متن ترجمه شده با فرمت‌دهی متغیرها"""
    lang = lang if lang in SUPPORTED_LANGUAGES else "fa"
    trans = STRINGS.get(key, {})
    text = trans.get(lang) or trans.get("fa") or trans.get("en") or key
    if kwargs:
        try:
            return text.format(**kwargs)
        except Exception:
            return text
    return text


def get_language_keyboard() -> InlineKeyboardMarkup:
    """کیبورد اینلاین انتخاب زبان"""
    keyboard = [
        [
            InlineKeyboardButton("🇮🇷 فارسی", callback_data="lang_fa"),
            InlineKeyboardButton("🇬🇧 English", callback_data="lang_en"),
        ],
        [
            InlineKeyboardButton("🇷🇺 Русский", callback_data="lang_ru"),
            InlineKeyboardButton("🇨🇳 中文", callback_data="lang_zh"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_contact_keyboard(lang: str = "fa") -> ReplyKeyboardMarkup:
    """کیبورد درخواست ارسال و احراز هویت شماره تلفن تلگرام"""
    lang = lang if lang in SUPPORTED_LANGUAGES else "fa"
    btn_text = t("btn_send_contact", lang)
    keyboard = [
        [KeyboardButton(btn_text, request_contact=True)]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)


def get_main_keyboard(user_id: int, admin_id: int, lang: str = "fa", webapp_url: str = None) -> ReplyKeyboardMarkup:
    """تولید منوی اصلی متناسب با زبان انتخاب‌شده کاربر و چیدمان داینامیک دکمه‌ها از پنل مدیریت"""
    lang = lang if lang in SUPPORTED_LANGUAGES else "fa"
    keyboard = []

    try:
        from database import db
        menu_rows = db.get_bot_menu_keyboard_rows(is_admin=(user_id == admin_id), is_reseller=False)
        if menu_rows:
            for row in menu_rows:
                kb_row = []
                for btn in row:
                    b_id = btn.get("id")
                    b_title = btn.get("title") or t(f"btn_{b_id}", lang)
                    kb_row.append(KeyboardButton(b_title))
                if kb_row:
                    keyboard.append(kb_row)
    except Exception as e:
        logger.warning(f"Failed to load dynamic bot menu rows: {e}")

    if not keyboard:
        # ساختار پیش‌فرض فال‌بک
        top_row = [KeyboardButton(t("btn_wallet", lang))]
        keyboard = [
            top_row,
            [KeyboardButton(t("btn_buy", lang)), KeyboardButton(t("btn_test", lang))],
            [KeyboardButton(t("btn_renew", lang)), KeyboardButton(t("btn_status", lang))],
            [KeyboardButton(t("btn_link", lang)), KeyboardButton(t("btn_payments", lang))],
            [KeyboardButton(t("btn_referral", lang)), KeyboardButton(t("btn_support", lang))],
            [KeyboardButton(t("btn_language", lang))],
        ]

    if user_id == admin_id and not any(any(t("btn_admin", lang) in (getattr(b, "text", "") or "") for b in row) for row in keyboard):
        keyboard.append([KeyboardButton(t("btn_admin", lang))])

    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def get_all_lang_regex(key: str) -> str:
    """تولید رجکس تطبیق دکمه در تمام ۴ زبان با پشتیبانی کامل از نیم‌فاصله، فاصله و بدون ایموجی"""
    import re
    options = set()
    for l in SUPPORTED_LANGUAGES:
        val = t(key, l).strip()
        if not val:
            continue
        options.add(val)
        if "\u200c" in val:
            options.add(val.replace("\u200c", " "))
            options.add(val.replace("\u200c", ""))
        # پشتیبانی از پیام متنی بدون ایموجی
        no_emoji = re.sub(r"^[^\w\s\u0600-\u06FF]+", "", val).strip()
        if no_emoji:
            options.add(no_emoji)
            if "\u200c" in no_emoji:
                options.add(no_emoji.replace("\u200c", " "))
                options.add(no_emoji.replace("\u200c", ""))

    escaped = [re.escape(v) for v in options]
    return "^(" + "|".join(escaped) + ")$"
