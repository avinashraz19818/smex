import os
import re
import json
import time
import random

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

MOBILE_CONTEXT = dict(
    viewport={'width': 390, 'height': 844},
    user_agent='Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 '
               '(KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1',
    device_scale_factor=3,
    is_mobile=True,
    has_touch=True,
)

CLOSE_SELECTORS = [
    "button:has-text('Confirm')",
    ".van-button:has-text('Confirm')",
    ".first-recharge-queue-dialog__close",
    ".closeBtn",
    ".close-btn",
    ".van-icon-cross",
    ".van-icon-close",
    ".van-popup__close-icon",
    ".van-popup__close-icon--bottom",
    ".dialog__close",
    "img[src*='close']",
    "xpath=//img[contains(@src, 'close')]",
    "[class*='close-icon']",
    "[class*='CloseBtn']",
    ".activity-close",
]


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def profile_dir(idx, owner_id):
    return os.path.join(BASE_DIR, f"playwright_profile_{idx}_{owner_id}")


def period_matches(on_page: str, intended: str) -> bool:
    a = ''.join(filter(str.isdigit, on_page or ''))
    b = ''.join(filter(str.isdigit, intended or ''))
    if len(a) < 4 or len(b) < 4:
        return True
    return a[-4:] == b[-4:]


class WingoClient:
    def __init__(self, idx, phone, password, owner_id, config=None):
        self.idx = idx
        self.phone = phone
        self.password = password
        self.owner_id = owner_id

        cfg = config or load_config()
        self.owner_cfg = cfg.get("owners", {}).get(owner_id, {})
        urls = self.owner_cfg.get("urls", {})
        self.login_url = urls.get("login_url", "https://yaarwin.club/#/login")
        self.room_url = urls.get(
            "wingo_room_url",
            "https://yaarwin.club/#/saasLottery/WinGo?gameCode=WinGo_1M&lottery=WinGo"
        )
        self.cdn_url = urls.get("cdn_url", "")

    def log(self, msg):
        print(msg, flush=True)


    def setup_lottery_token(self, page):
        try:
            page.evaluate("""() => {
                let urlStr = localStorage.getItem('lotteryLoginUrl');
                if (urlStr) {
                    try {
                        let u = new URL(urlStr);
                        let token = u.searchParams.get("Token");
                        let skin = u.searchParams.get("Skin") || "";
                        let lang = u.searchParams.get("Lang") || "en";

                        localStorage.setItem("ar_token", JSON.stringify({ value: token, expires: -1 }));
                        localStorage.setItem("ar_api", JSON.stringify({ value: "https://h5.ar-lottery06.com", expires: -1 }));
                        localStorage.setItem("ar_api_json", JSON.stringify({ value: "https://draw.ar-lottery06.com", expires: -1 }));
                        localStorage.setItem("ar_lang", JSON.stringify({ value: lang, expires: -1 }));
                        localStorage.setItem("ar_skin", JSON.stringify({ value: skin, expires: -1 }));
                    } catch(e) {}
                }
            }""")
        except Exception:
            pass

    def dismiss_announcements(self, page):
        for _ in range(4):
            dismissed = False

            try:
                no_reminders = page.locator("text='No more reminders today'").first
                if no_reminders.is_visible(timeout=300):
                    no_reminders.click(timeout=1000)
                    time.sleep(0.5)
            except Exception:
                pass

            for sel in CLOSE_SELECTORS:
                try:
                    el = page.locator(sel).first
                    if el.is_visible(timeout=300):
                        self.log(f"👉 Dismissing popup using selector: {sel}")
                        el.click(timeout=1500)
                        time.sleep(1)
                        dismissed = True
                        break
                except Exception:
                    pass

            if not dismissed:
                try:
                    overlay = page.locator(".van-overlay").first
                    if overlay.is_visible(timeout=300):
                        self.log("👉 Overlay detected but no close button found. Trying fallback coordinate click on 'X'...")
                        vp = page.viewport_size
                        if vp:
                            for offset in (180, 220, 260, 300):
                                page.mouse.click(vp['width'] / 2, vp['height'] / 2 + offset)
                            time.sleep(1)
                            dismissed = True
                except Exception:
                    pass

            if not dismissed:
                break

    def is_logged_out(self, page) -> bool:
        try:
            if page.locator(".van-toast:has-text('expired'), .van-toast:has-text('login')").is_visible(timeout=800):
                return True
            if "#/login" in page.url:
                return True
            if page.locator("input[name='userNumber']").is_visible(timeout=800):
                return True
            if (page.locator(".p8-home__guest-btn--login").is_visible(timeout=800)
                    and not page.locator(".TimeLeft__C-id").is_visible(timeout=800)):
                return True
        except Exception:
            pass
        return False

    def ensure_logged_in(self, page) -> bool:
        time.sleep(2)
        current_url = page.url

        login_btn = page.locator(".p8-home__guest-btn--login").first
        phone_input = page.locator("input[name='userNumber'], input[placeholder*='phone']").first

        needs_login = False
        try:
            if "#/login" in current_url or phone_input.is_visible(timeout=1000) or login_btn.is_visible(timeout=1000):
                needs_login = True
        except Exception:
            pass

        if not needs_login:
            return True

        self.log("🔑 Logging in automatically...")
        try:
            if "#/login" not in page.url:
                page.goto(self.login_url)
                time.sleep(2)

            phone_field = page.locator("input[name='userNumber'], input[placeholder*='phone']").first
            phone_field.wait_for(state="visible", timeout=8000)
            phone_field.fill(self.phone)
            time.sleep(0.3)

            pwd_field = page.locator(".tab-content.activecontent input[type='password'], input[type='password']").first
            pwd_field.fill(self.password)
            time.sleep(0.3)

            try:
                rem_cb = page.locator(".signIn__container-rememberRow .van-checkbox").first
                if rem_cb.is_visible(timeout=1000) and rem_cb.get_attribute("aria-checked") == "false":
                    rem_cb.click()
            except Exception:
                pass

            login_submit_btn = page.locator(
                ".signIn__container-button button:has-text('Log in'), "
                ".signIn__container-button button, button:has-text('Log in')"
            ).first
            login_submit_btn.click()
            self.log("👉 Login button clicked, waiting for authentication...")
            time.sleep(4)
            self.dismiss_announcements(page)
            self.setup_lottery_token(page)
            return True
        except Exception as e:
            self.log(f"❌ Auto-login error: {e}")
            return False

    def diagnose(self, page) -> str:
        bits = []
        try:
            bits.append(f"url={page.url}")
        except Exception:
            bits.append("url=?")
        try:
            bits.append(f"title={page.title()!r}")
        except Exception:
            pass
        try:
            bits.append("board=yes" if page.locator(".TimeLeft__C-id").is_visible(timeout=600) else "board=no")
        except Exception:
            bits.append("board=no")
        try:
            if page.locator("input[name='userNumber'], input[placeholder*='phone']").first.is_visible(timeout=600):
                bits.append("login-form=yes")
        except Exception:
            pass
        try:
            if page.locator(".van-overlay").first.is_visible(timeout=600):
                bits.append("popup-overlay=yes")
        except Exception:
            pass
        try:
            toast = page.locator(".van-toast").first
            if toast.is_visible(timeout=600):
                bits.append(f"toast={toast.inner_text(timeout=600)[:60]!r}")
        except Exception:
            pass
        return " ".join(bits)

    def debug_shot(self, page, tag="wingo") -> str:
        path = os.path.join(BASE_DIR, f"debug_{tag}_{self.idx}_{self.owner_id}.png")
        try:
            page.screenshot(path=path)
            self.log(f"📷 Debug screenshot: {path}")
            return path
        except Exception as e:
            self.log(f"⚠️ Debug screenshot fail: {e}")
            return ""

    def ensure_wingo_room(self, page, attempts=5) -> bool:
        for attempt in range(attempts):
            time.sleep(1)
            self.dismiss_announcements(page)

            if self.is_logged_out(page):
                self.log(f"🔑 Attempt {attempt+1}: logged out laga, login kar raha hoon")
                self.ensure_logged_in(page)
                self.setup_lottery_token(page)
                time.sleep(2)
                self.dismiss_announcements(page)

            try:
                if page.locator(".TimeLeft__C-id").is_visible(timeout=1500):
                    try:
                        card_1m = page.locator("text=/1\\s*Min/i").first
                        if card_1m.is_visible(timeout=1000):
                            self.log("👉 Ensuring 1Min tab is selected...")
                            card_1m.click(timeout=1000)
                            time.sleep(1)
                    except Exception as e:
                        self.log(f"⚠️ Could not click 1Min tab: {e}")
                    return True
            except Exception:
                pass

            self.log(f"⚠️ Attempt {attempt+1}/{attempts} board nahi mila -> {self.diagnose(page)}")

            clicked_wingo = False
            try:
                wingo_btn = page.locator(".p8-home, .game, body").get_by_text("Win Go", exact=False).first
                if wingo_btn.is_visible(timeout=1500):
                    self.log("👉 Home pe 'Win Go' mila, usko click kar raha hoon")
                    wingo_btn.click()
                    time.sleep(3)
                    self.dismiss_announcements(page)
                    clicked_wingo = True
            except Exception as e:
                self.log(f"⚠️ 'Win Go' click fail: {e}")
            if clicked_wingo:
                continue

            try:
                self.setup_lottery_token(page)
                self.log("👉 Room url dobara khol raha hoon")
                page.goto(self.room_url)
                time.sleep(3)
                self.dismiss_announcements(page)
            except Exception as e:
                self.log(f"⚠️ Room url kholne me error: {e}")

        try:
            return page.locator(".TimeLeft__C-id").is_visible(timeout=3000)
        except Exception:
            return False

    def force_login(self, page) -> bool:
        self.log("🔁 Force re-login kar raha hoon")
        try:
            page.goto(self.login_url)
            time.sleep(2)
            self.dismiss_announcements(page)

            phone_field = page.locator("input[name='userNumber'], input[placeholder*='phone']").first
            phone_field.wait_for(state="visible", timeout=10000)
            phone_field.fill(self.phone)
            time.sleep(0.3)

            pwd_field = page.locator(".tab-content.activecontent input[type='password'], input[type='password']").first
            pwd_field.fill(self.password)
            time.sleep(0.3)

            page.locator(
                ".signIn__container-button button:has-text('Log in'), "
                ".signIn__container-button button, button:has-text('Log in')"
            ).first.click()
            self.log("👉 Login button clicked (force), waiting...")
            time.sleep(4)
            self.dismiss_announcements(page)
            self.setup_lottery_token(page)
            page.goto(self.room_url)
            return self.ensure_wingo_room(page, attempts=3)
        except Exception as e:
            self.log(f"❌ Force login fail: {e}")
            return False

    def open_room(self, page) -> bool:
        self.ensure_logged_in(page)
        self.setup_lottery_token(page)
        try:
            page.goto(self.room_url)
        except Exception as e:
            self.log(f"⚠️ Could not open room url: {e}")
        if self.ensure_wingo_room(page):
            return True

        self.log(f"⚠️ Room nahi khula -> {self.diagnose(page)}")
        if self.force_login(page):
            return True
        self.debug_shot(page, "startup")
        return False

    def current_period(self, page, timeout=2000) -> str:
        try:
            return page.locator(".TimeLeft__C-id").inner_text(timeout=timeout).strip()
        except Exception:
            return ""

    def seconds_left(self, page, timeout=1000):
        try:
            t_text = page.locator(".TimeLeft__C-time, .van-count-down, .time").first.inner_text(timeout=timeout)
            nums = ''.join(filter(str.isdigit, t_text))
            if len(nums) >= 4:
                return int(nums[-4:-2]) * 60 + int(nums[-2:])
        except Exception:
            pass
        return None


    def refresh(self, page) -> str:
        try:
            page.goto(self.room_url)
        except Exception:
            try:
                page.reload()
            except Exception as e:
                return f"reload fail: {e}"

        time.sleep(1.5)
        self.dismiss_announcements(page)

        relogged = False
        if self.is_logged_out(page):
            self.log("🔑 Session expired — dobara login kar raha hoon")
            self.ensure_logged_in(page)
            self.setup_lottery_token(page)
            relogged = True

        ok = self.ensure_wingo_room(page)
        if not ok:
            self.log(f"⚠️ Refresh ke baad bhi room nahi khula -> {self.diagnose(page)}")
            ok = self.force_login(page)
            relogged = relogged or ok

        period = self.current_period(page) or "?"
        if not ok:
            shot = self.debug_shot(page, "refresh")
            detail = self.diagnose(page)
            if shot:
                detail += f" | shot={os.path.basename(shot)}"
            return f"room nahi khula | {detail}"
        return f"{'re-login + ' if relogged else ''}WinGo 1Min ready (period {period})"

    def keepalive(self, page) -> str:
        try:
            self.dismiss_announcements(page)
            if self.is_logged_out(page):
                self.log("🔑 Logged out detect hua — login kar raha hoon")
                self.ensure_logged_in(page)
                self.setup_lottery_token(page)
                self.ensure_wingo_room(page)
                return f"re-login done (period {self.current_period(page) or '?'})"
            if not self.current_period(page, timeout=1500):
                self.log("↩️ WinGo board se bahar tha — wapas le jaa raha hoon")
                if not self.ensure_wingo_room(page, attempts=3):
                    self.force_login(page)
                period = self.current_period(page)
                if not period:
                    return f"room nahi khula | {self.diagnose(page)}"
                return f"room wapas khola (period {period})"
            return f"ok (period {self.current_period(page) or '?'})"
        except Exception as e:
            return f"check fail: {e}"


    def sheet_total(self, page):
        try:
            text = page.locator("button.bet-amount").first.inner_text(timeout=800)
        except Exception:
            return None
        nums = re.findall(r"\d[\d,]*(?:\.\d+)?", text)
        if not nums:
            return None
        try:
            return int(float(nums[-1].replace(",", "")))
        except ValueError:
            return None

    def set_bet_amount(self, page, multiplier):
        expected = multiplier * 100
        total = None
        for attempt in range(3):
            try:
                page.locator(".balance-item, .amount-item, .item, .van-button").filter(
                    has_text=re.compile(r"^100$")).first.click(timeout=1500)
            except Exception:
                try:
                    page.get_by_text("100", exact=True).first.click(timeout=800)
                except Exception:
                    pass

            try:
                qty = page.locator("input:visible").last
                qty.wait_for(state="visible", timeout=1500)
                if attempt == 0:
                    qty.click(timeout=800)
                    page.keyboard.press("End")
                    for _ in range(4):
                        page.keyboard.press("Backspace")
                    page.keyboard.type(str(multiplier))
                else:
                    qty.fill(str(multiplier), timeout=800)
                    qty.dispatch_event("change")
            except Exception as e:
                self.log(f"⚠️ Quantity {multiplier} set nahi hui (attempt {attempt+1}): {e}")

            total = self.sheet_total(page)
            if total is None or total == expected:
                return total or expected
            self.log(f"⚠️ Total ₹{total} dikh raha hai, ₹{expected} chahiye — dobara set kar raha hoon")
        return total

    def place_bets(self, page, mode="bet", intended_period=None) -> dict:
        result = {"ok": False, "bets": 0, "amount": 0, "period": "", "reason": ""}

        self.dismiss_announcements(page)
        on_page_period = self.current_period(page, timeout=5000)
        if on_page_period:
            self.log(f"👉 Current Period: {on_page_period}")
        else:
            self.log("⚠️ Period number not found.")
        result["period"] = on_page_period or "unknown"

        if intended_period and on_page_period and not period_matches(on_page_period, intended_period):
            self.log(f"⏰ Period mismatch! Expected {intended_period}, found {on_page_period}. Aborting.")
            result["reason"] = "period mismatch"
            self.log(f"FAILED_CLIENT_INFO={self.idx}:{self.phone}:{self.password}")
            self.log(f"INCOMPLETE_BETS_ERROR_FOR_CLIENT={self.idx}")
            return result

        secs = self.seconds_left(page)
        if secs is not None and secs <= 8:
            self.log(f"⏰ Sirf {secs}s bache hain — is period pe bet lock hai, skip kar raha hoon.")
            result["reason"] = f"only {secs}s left"
            self.log(f"FAILED_CLIENT_INFO={self.idx}:{self.phone}:{self.password}")
            self.log(f"INCOMPLETE_BETS_ERROR_FOR_CLIENT={self.idx}")
            return result

        multiplier = random.randint(1, 24) * 5
        random_bet_amount = multiplier * 100
        self.log(f"🎲 Selected random bet amount for this period: ₹{random_bet_amount}")
        self.log(f"BET_AMOUNT_{self.idx}={random_bet_amount}")
        result["amount"] = random_bet_amount

        successful_bets = 0
        break_all = False

        for num in range(10):
            if break_all:
                break

            number_to_bet = str(num)
            for attempt in range(3):
                try:
                    loop_period = self.current_period(page, timeout=200)
                    if on_page_period and loop_period and loop_period != on_page_period:
                        self.log(f"⏰ Period changed from {on_page_period} to {loop_period}. Stopping loop.")
                        break_all = True
                        break

                    secs = self.seconds_left(page, timeout=200)
                    if secs is not None and secs <= 6:
                        self.log(f"⏰ Only {secs} seconds left! Betting is locked. Stopping loop.")
                        break_all = True
                        break

                    try:
                        page.evaluate("if ((window.scrollY || document.documentElement.scrollTop) > 50) "
                                      "window.scrollTo({ top: 0, behavior: 'instant' })")
                    except Exception:
                        pass

                    self.log(f"👉 Clicking on Number {number_to_bet} (Attempt {attempt+1})...")
                    num_ball = page.locator(f".Betting__C-numC-item{number_to_bet}").first
                    num_ball.click(timeout=1500)

                    placed = self.set_bet_amount(page, multiplier)
                    if placed and placed != result["amount"]:
                        self.log(f"⚠️ Asli bet ₹{placed} lagi (₹{result['amount']} nahi)")
                        self.log(f"BET_AMOUNT_{self.idx}={placed}")
                        result["amount"] = placed

                    try:
                        confirm_btn = page.locator("button.bet-amount").first
                        confirm_btn.click(timeout=1000)
                    except Exception:
                        try:
                            page.get_by_text("Total amount").first.click(timeout=1000)
                        except Exception:
                            pass

                    cancel_btn = page.locator("text='Cancel'").first
                    try:
                        cancel_btn.wait_for(state="hidden", timeout=1000)
                    except Exception:
                        if cancel_btn.is_visible(timeout=100):
                            self.log("⚠️ Modal still open (Glitch detected). Clicking Cancel and retrying...")
                            cancel_btn.click(timeout=500)
                            time.sleep(0.1)
                            continue

                    self.log(f"✅ Bet Confirmed for {number_to_bet}!")
                    successful_bets += 1
                    time.sleep(0.05)
                    break

                except Exception as e:
                    self.log(f"⚠️ Error placing bet on {number_to_bet}: {e}")
                    try:
                        page.locator("text='Cancel'").first.click(timeout=1000)
                        time.sleep(0.5)
                    except Exception:
                        pass

        result["bets"] = successful_bets

        if successful_bets == 0 or (mode == "hbet" and successful_bets < 10):
            self.log(f"❌ Only {successful_bets} bets were placed. Aborting.")
            self.log(f"FAILED_CLIENT_INFO={self.idx}:{self.phone}:{self.password}")
            self.log(f"INCOMPLETE_BETS_ERROR_FOR_CLIENT={self.idx}")
            result["reason"] = f"only {successful_bets} bets"
            return result

        if successful_bets == 10:
            self.log("✅ All 10 bets Placed! Applying random scroll jitter...")
        else:
            self.log(f"✅ {successful_bets} bets Placed! Applying random scroll jitter...")

        try:
            target_scroll = 120 + random.randint(0, 500)
            page.evaluate(f"window.scrollTo({{ top: {target_scroll}, behavior: 'smooth' }})")
            time.sleep(0.5)
        except Exception:
            pass

        result["ok"] = True
        return result

    def _fetch_winning_number(self):
        try:
            import requests
            r = requests.get(self.cdn_url, timeout=5)
            return r.json()["data"]["list"][0].get("number")
        except Exception as e:
            self.log(f"⚠️ Could not fetch winning number: {e}")
            return None

    def capture_result(self, page, mode, info) -> None:
        successful_bets = info.get("bets", 0)
        total_seconds_left = self.seconds_left(page)
        if total_seconds_left is None:
            total_seconds_left = 50
        wait_timeout = (total_seconds_left + 15) * 1000

        if mode == "hbet":
            self.log(f"Waiting for result... (Timeout: {wait_timeout//1000}s)")
            time.sleep(total_seconds_left + 5)

            winning_number = self._fetch_winning_number()
            if winning_number is not None:
                try:
                    winning_number = int(winning_number)
                    self.log(f"WINNING_NUMBER={winning_number}")
                except Exception:
                    winning_number = None

            if winning_number is not None:
                self.log(f"👉 Placing {winning_number + 1} dummy 1Rs bets to push history to Page 2...")
                page.reload()
                self.ensure_wingo_room(page)

                for num in range(winning_number + 1):
                    try:
                        self.log(f"👉 Dummy bet on Number {num}...")
                        page.locator(f".Betting__C-numC-item{num}").first.click(timeout=1500)

                        try:
                            page.locator(".balance-item, .amount-item, .item, .van-button").filter(
                                has_text=re.compile(r"^1$")).first.click(timeout=500)
                        except Exception:
                            pass

                        try:
                            input_qty = page.locator("input:visible").last
                            if input_qty.is_visible():
                                input_qty.click(timeout=300)
                                page.keyboard.press("End")
                                for _ in range(4):
                                    page.keyboard.press("Backspace")
                                page.keyboard.type("1")
                        except Exception:
                            pass

                        try:
                            page.locator("button.bet-amount").first.click(timeout=1000)
                        except Exception:
                            try:
                                page.get_by_text("Total amount").first.click(timeout=1000)
                            except Exception:
                                pass

                        try:
                            page.locator("text='Cancel'").first.wait_for(state="hidden", timeout=1000)
                        except Exception:
                            pass
                        time.sleep(0.1)
                    except Exception as e:
                        self.log(f"⚠️ Dummy bet error on {num}: {e}")

            try:
                self.dismiss_announcements(page)
                self.log("👉 Clicking My history tab...")
                page.locator(".nav-container div:has-text('My history'), "
                             ".nav-container div:has-text('Game history') ~ div ~ div").first.click(timeout=3000)

                try:
                    page.locator(".list-item").first.wait_for(state="visible", timeout=8000)
                except Exception:
                    pass
                time.sleep(1)

                self.log("👉 Clicking next page to find the real winning bet at the top...")
                page.locator(".my_r-foot-next, .van-icon-arrow").last.click(timeout=4000)
                time.sleep(2)

                success_item = page.locator(".list-item:has(.success)").first
                if success_item.is_visible(timeout=2000):
                    self.log("✅ Found winning bet on Page 2! Expanding...")
                    success_item.click(timeout=2000)
                    time.sleep(1)
                    box = success_item.bounding_box()
                    if box:
                        offset = random.randint(350, 500)
                        page.evaluate(f"window.scrollTo({{ top: window.scrollY + {box['y']} - {offset}, "
                                      f"behavior: 'instant' }})")
                        time.sleep(1)

                    screenshot_path = os.path.join(BASE_DIR, f"hbet_win_{self.idx}_{self.owner_id}.png")
                    page.screenshot(path=screenshot_path)
                    self.log(f"SUCCESS_SCREENSHOT_PATH_{self.idx}={screenshot_path}")
                else:
                    self.log("❌ Could not find winning bet on Page 2.")
            except Exception as e:
                self.log(f"❌ Error capturing hbet history: {e}")
            return

        self.log(f"Waiting for Congratulations popup... (Timeout: {wait_timeout//1000}s)")
        try:
            page.wait_for_selector('text="Congratulations"', timeout=wait_timeout)
            self.log("🎉 Winning Popup Detect ho gaya! Screenshot le raha hu...")
            time.sleep(1.5)

            screenshot_path = os.path.join(BASE_DIR, f"auto_win_popup_{self.idx}_{self.owner_id}.png")
            page.screenshot(path=screenshot_path)
            self.log(f"SUCCESS_SCREENSHOT_PATH_{self.idx}={screenshot_path}")

            try:
                time.sleep(2)
                if self.cdn_url:
                    win = self._fetch_winning_number()
                    if win is not None:
                        self.log(f"WINNING_NUMBER={win}")
            except Exception as e:
                self.log(f"⚠️ Could not fetch winning number: {e}")
        except Exception as e:
            if successful_bets < 10:
                self.log(f"FAILED_CLIENT_INFO={self.idx}:{self.phone}:{self.password}")
                self.log(f"INCOMPLETE_BETS_ERROR_FOR_CLIENT={self.idx}")
            else:
                self.log(f"❌ Winning popup nahi aaya ya error: {e}")

    def run_round(self, page, mode="bet", intended_period=None) -> dict:
        info = self.place_bets(page, mode, intended_period)
        if info.get("ok"):
            self.capture_result(page, mode, info)
        return info
