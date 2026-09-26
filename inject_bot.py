import sys
import re

with open('admin_bot_admin.py', 'r', encoding='utf-8') as f:
    content = f.read()

# using regex
pattern = r'(InlineKeyboardButton\("🌐 پایش سلامت نودها و سرورها", callback_data="adm_adv_nodes"\),\n\s*\])'
replacement = r'\1,\n                [\n                    InlineKeyboardButton("🖥️ خط فرمان (ترمینال)", callback_data="adm_terminal_menu")\n                ]'

new_content = re.sub(pattern, replacement, content)

with open('admin_bot_admin.py', 'w', encoding='utf-8') as f:
    f.write(new_content)
