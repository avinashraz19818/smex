import os
import re

text = open('../pyrogram_bot/playwright_bet.py', 'r', encoding='utf-8').read()

text = text.replace('intended_period = sys.argv[1] if len(sys.argv) > 1 else ""', '''client_idx = int(sys.argv[1]) if len(sys.argv) > 1 else 1
phone = sys.argv[2] if len(sys.argv) > 2 else ""
password = sys.argv[3] if len(sys.argv) > 3 else ""
mode = sys.argv[4] if len(sys.argv) > 4 else "bet"
owner_id = sys.argv[5] if len(sys.argv) > 5 else ""''')

text = text.replace('mode = sys.argv[2] if len(sys.argv) > 2 else "bet"', '')

text = text.replace('LOGIN_PHONE = os.getenv("LOGIN_USER", "")', 'LOGIN_PHONE = phone')
text = text.replace('LOGIN_PASSWORD = os.getenv("LOGIN_PWD", "")', 'LOGIN_PASSWORD = password')

text = text.replace('SUCCESS_SCREENSHOT_PATH=', 'SUCCESS_SCREENSHOT_PATH_{client_idx}=')
text = text.replace('auto_win_popup.png', 'auto_win_popup_{client_idx}_{owner_id}.png')
text = text.replace('hbet_win.png', 'hbet_win_{client_idx}_{owner_id}.png')
text = text.replace('playwright_profile', 'playwright_profile_{client_idx}_{owner_id}')

text = text.replace('URLS = config.get("urls", {})', '''owner_cfg = config.get("owners", {}).get(owner_id, {})
URLS = owner_cfg.get("urls", {})''')

open('client_runner.py', 'w', encoding='utf-8').write(text)
print("Fixed client_runner.py with owner isolation")
