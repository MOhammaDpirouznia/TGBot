import os
import httpx
import json
from dotenv import load_dotenv

load_dotenv()
API_URL = os.getenv('HIDIFY_PANEL_URL')
API_KEY = os.getenv('HIDIFY_API_KEY')
PROXY_PATH = os.getenv('HIDIFY_PROXY_PATH')

headers = {
    'Accept': 'application/json',
    'Hiddify-API-Key': API_KEY
}
full_url = f'{API_URL}/{PROXY_PATH}/api/v2/admin/user/'

with httpx.Client(verify=False) as client:
    response = client.get(full_url, headers=headers, timeout=10.0)
    users = response.json()
    with open('first_user.json', 'w', encoding='utf-8') as f:
        json.dump(users[0], f, ensure_ascii=False, indent=2)
