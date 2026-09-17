import os
import sys

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

import wingo

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

load_dotenv()

client_idx = int(sys.argv[1]) if len(sys.argv) > 1 else 1
phone = sys.argv[2] if len(sys.argv) > 2 else ""
password = sys.argv[3] if len(sys.argv) > 3 else ""
mode = sys.argv[4] if len(sys.argv) > 4 else "bet"
owner_id = sys.argv[5] if len(sys.argv) > 5 else ""
intended_period = sys.argv[6] if len(sys.argv) > 6 else ""

HEADLESS = os.getenv("HEADLESS", "false").lower() in ("true", "1", "yes")


def run_betting_sequence():
    client = wingo.WingoClient(client_idx, phone, password, owner_id)

    with sync_playwright() as p:
        with p.chromium.launch_persistent_context(
            wingo.profile_dir(client_idx, owner_id),
            headless=HEADLESS,
            **wingo.MOBILE_CONTEXT
        ) as context:
            page = context.pages[0] if context.pages else context.new_page()
            try:
                client.open_room(page)
                client.log("🎯 Connected to Wingo Room")
                client.run_round(page, mode, intended_period or None)
            finally:
                try:
                    page.close()
                except Exception:
                    pass
                try:
                    context.close()
                except Exception:
                    pass


if __name__ == '__main__':
    run_betting_sequence()
