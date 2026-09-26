from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from database import db
from terminal_manager import TerminalManager

WAITING_FOR_TERMINAL_CMD = "WAITING_FOR_TERMINAL_CMD"

async def adm_terminal_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    # Check if PIN is set in DB
    pin = db.get_setting("terminal_pin")
    if not pin:
        await query.edit_message_text(
            "⚠️ **هشدار امنیتی**\n\nبرای استفاده از خط فرمان، باید ابتدا یک **پین‌کد امنیتی** در پنل وب (بخش سیستم و تنظیمات -> خط فرمان) تنظیم کنید.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="adm_adv_menu")]])
        )
        return ConversationHandler.END

    txt = (
        "🖥️ **خط فرمان سرور (Terminal Lite)**\n\n"
        "این بخش به شما اجازه می‌دهد تا دستورات لینوکسی را مستقیماً روی سرور فعلی اجرا کنید.\n"
        "برای اجرای دستور دلخواه روی دکمه ارسال دستور کلیک کنید یا از ابزارهای سریع استفاده نمایید.\n\n"
        "⚠️ از اجرای دستورات تعاملی (مثل nano) خودداری کنید."
    )
    
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 وضعیت RAM و CPU", callback_data="term_cmd_top"),
            InlineKeyboardButton("💾 وضعیت دیسک", callback_data="term_cmd_disk")
        ],
        [
            InlineKeyboardButton("🔄 ریستارت ربات", callback_data="term_cmd_restart"),
            InlineKeyboardButton("⌨️ ارسال دستور دلخواه", callback_data="term_cmd_custom")
        ],
        [InlineKeyboardButton("🔙 بازگشت به پنل مدیریت", callback_data="adm_adv_menu")]
    ])
    
    await query.edit_message_text(txt, reply_markup=kb, parse_mode="Markdown")
    # Return CHOOSING (0) so we stay in the main menu handler loop
    return 0 

async def term_cmd_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("در حال اجرا...")
    data = query.data
    
    if data == "term_cmd_custom":
        await query.edit_message_text(
            "⌨️ لطفاً دستور دلخواه خود را دقیقاً با متن لاتین ارسال کنید:\n\n"
            "برای انصراف گزینه زیر را انتخاب کنید.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ انصراف", callback_data="adm_terminal_menu")]])
        )
        return WAITING_FOR_TERMINAL_CMD
        
    cmds = {
        "term_cmd_top": "free -h && echo '\n--- CPU Load ---' && uptime",
        "term_cmd_disk": "df -h /",
        "term_cmd_restart": "systemctl restart tgbot || echo 'Failed to restart using systemctl. Try in web panel.'"
    }
    
    cmd = cmds.get(data, "echo Invalid")
    success, out = TerminalManager.run_local_command(cmd)
    
    out = out[:3800] # Telegram limit
    
    await query.edit_message_text(
        f"🖥️ **نتیجه اجرای دستور:**\n`{cmd}`\n\n```\n{out}\n```",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به خط فرمان", callback_data="adm_terminal_menu")]])
    )
    return 0

async def receive_custom_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message.text
    await update.message.reply_text("⏳ در حال اجرا...")
    
    success, out = TerminalManager.run_local_command(msg)
    out = out[:3800]
    
    await update.message.reply_text(
        f"🖥️ **نتیجه دستور:**\n`{msg}`\n\n```\n{out}\n```",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به منوی مدیریت", callback_data="adm_adv_menu")]])
    )
    return 0
