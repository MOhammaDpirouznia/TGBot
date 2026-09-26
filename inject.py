import sys
import re

with open('templates/base.html', 'r', encoding='utf-8') as f:
    content = f.read()

# using regex
pattern = r'(<i class="fas fa-sliders text-secondary"></i> تنظیمات سیستم\s*</a>)'
replacement = r'\1\n                          <a class="submenu-item {% if request.endpoint == \'admin_terminal\' %}active{% endif %}" href="{{ url_for(\'admin_terminal\') }}">\n                              <i class="fas fa-terminal text-primary"></i> خط فرمان (Terminal)\n                          </a>'

new_content = re.sub(pattern, replacement, content)

with open('templates/base.html', 'w', encoding='utf-8') as f:
    f.write(new_content)
