with open('templates/admin_terminal.html', 'r', encoding='utf-8') as f:
    content = f.read()

# I need to move the <script> block completely OUTSIDE of {% if not is_auth %} / {% else %} ... {% endif %}
# The structure is currently:
# {% block content %}
# {% if not is_auth %}
#    ... auth form ...
# {% else %}
#    ... terminal UI ...
#    <script> ... </script>
# {% endif %}
# {% endblock %}
# I want:
# {% block content %}
# {% if not is_auth %}
#    ... auth form ...
# {% else %}
#    ... terminal UI ...
# {% endif %}
# <script> ... </script>
# {% endblock %}

import re

# Find the start of the script tag
script_start = content.find('<script>')
script_end = content.find('</script>') + len('</script>')

if script_start != -1:
    script_content = content[script_start:script_end]
    content = content[:script_start] + content[script_end:]
    
    # Place script before {% endblock %}
    content = content.replace('{% endblock %}', script_content + '\n{% endblock %}')

with open('templates/admin_terminal.html', 'w', encoding='utf-8') as f:
    f.write(content)

print("Fixed admin_terminal.html script placement.")
