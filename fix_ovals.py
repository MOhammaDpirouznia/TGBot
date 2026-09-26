import re

with open('templates/node_monitor.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Replace the icon circles
# Old pattern: <div class="rounded-circle flex-shrink-0 p-3 bg-primary bg-opacity-10 text-primary fs-3 d-flex align-items-center justify-content-center" style="width: 64px; height: 64px; aspect-ratio: 1;">
# We want to remove `p-3` and adjust style.

content = re.sub(
    r'<div class="rounded-circle flex-shrink-0 p-3 (bg-[^\s]+) bg-opacity-10 (text-[^\s]+) fs-3 d-flex align-items-center justify-content-center" style="width: 64px; height: 64px; aspect-ratio: 1;">',
    r'<div class="rounded-circle flex-shrink-0 \1 bg-opacity-10 \2 fs-3 d-flex align-items-center justify-content-center" style="width: 64px; height: 64px; min-width: 64px; padding: 0;">',
    content
)

with open('templates/node_monitor.html', 'w', encoding='utf-8') as f:
    f.write(content)
print("Replaced circle styles in node_monitor.html")
