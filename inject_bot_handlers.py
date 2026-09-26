import re

with open('bot.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Add imports
import_str = "from terminal_bot_handlers import adm_terminal_menu, term_cmd_action, receive_custom_cmd, WAITING_FOR_TERMINAL_CMD\n"
if "terminal_bot_handlers" not in content:
    content = content.replace("from telegram import ", import_str + "from telegram import ", 1)

# 2. Add CHOOSING callbacks
choosing_pattern = r'(CHOOSING: \[)'
choosing_replacement = r'\1\n                  CallbackQueryHandler(adm_terminal_menu, pattern="^adm_terminal_menu$"),\n                  CallbackQueryHandler(term_cmd_action, pattern="^term_cmd_"),'
if "adm_terminal_menu$" not in content:
    content = re.sub(choosing_pattern, choosing_replacement, content, count=1)

# 3. Add new state WAITING_FOR_TERMINAL_CMD
states_pattern = r'(states={)'
# Find end of CHOOSING state list (it's hard with regex, so I will inject the state at the beginning of states block)
# Actually just put it after states={
state_replacement = r'states={\n              WAITING_FOR_TERMINAL_CMD: [\n                  MessageHandler(filters.TEXT & ~filters.COMMAND, receive_custom_cmd),\n                  CallbackQueryHandler(adm_terminal_menu, pattern="^adm_terminal_menu$")\n              ],'

if "WAITING_FOR_TERMINAL_CMD:" not in content:
    content = re.sub(states_pattern, state_replacement, content, count=1)

with open('bot.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("Injected handlers successfully.")
