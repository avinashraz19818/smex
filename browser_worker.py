import os
import sys
import json

from dotenv import load_dotenv

BASE_DIR = os.path.dirname(__file__)
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", os.path.join(BASE_DIR, "pw-browsers"))


from playwright.sync_api import sync_playwright

import wingo

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

load_dotenv()

client_idx = int(sys.argv[1]) if len(sys.argv) > 1 else 1
phone = sys.argv[2] if len(sys.argv) > 2 else ""
password = sys.argv[3] if len(sys.argv) > 3 else ""
owner_id = sys.argv[4] if len(sys.argv) > 4 else ""

HEADLESS = os.getenv("HEADLESS", "false").lower() in ("true", "1", "yes")


def emit(marker, text=""):
    print(f"{marker}{text}", flush=True)


def main():
    client = wingo.WingoClient(client_idx, phone, password, owner_id)

    with sync_playwright() as p:
        with p.chromium.launch_persistent_context(
            wingo.profile_dir(client_idx, owner_id),
            headless=HEADLESS,
            **wingo.MOBILE_CONTEXT
        ) as context:
            page = context.pages[0] if context.pages else context.new_page()

            ok = client.open_room(page)
            period = client.current_period(page) or "?"
            if ok:
                client.log(f"🎯 Browser ready on WinGo 1Min (period {period})")
                emit("__READY__", f"period {period}")
            else:
                client.log("⚠️ WinGo board nahi khula — /refresh se dobara try karo")
                emit("__READY_FAILED__", "wingo room nahi khula")

            while True:
                line = sys.stdin.readline()
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue

                try:
                    cmd = json.loads(line)
                except Exception:
                    client.log(f"⚠️ Invalid command: {line}")
                    continue

                name = cmd.get("cmd")

                if name == "bet":
                    mode = cmd.get("mode", "bet")
                    try:
                        if not client.current_period(page, timeout=1000):
                            client.log("↩️ Board pe nahi tha — pehle WinGo 1Min khol raha hoon")
                            client.ensure_wingo_room(page)
                        client.run_round(page, mode, cmd.get("period"))
                    except Exception as e:
                        client.log(f"❌ Round error: {e}")
                        client.log(f"FAILED_CLIENT_INFO={client_idx}:{phone}:{password}")
                    try:
                        client.dismiss_announcements(page)
                        if not client.current_period(page, timeout=1500):
                            client.ensure_wingo_room(page)
                    except Exception:
                        pass
                    emit("__BET_DONE__")

                elif name == "refresh":
                    try:
                        status = client.refresh(page)
                    except Exception as e:
                        status = f"refresh error: {e}"
                    emit("__REFRESH_DONE__", status)

                elif name == "keepalive":
                    try:
                        status = client.keepalive(page)
                    except Exception as e:
                        status = f"keepalive error: {e}"
                    emit("__KEEPALIVE_DONE__", status)

                elif name == "shutdown":
                    client.log("👋 Shutting down browser")
                    break

                else:
                    client.log(f"⚠️ Unknown command: {name}")


if __name__ == "__main__":
    main()
