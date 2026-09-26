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

# ---- Real WinGo (ar-lottery / 51game / saasLottery) h5 DOM selectors ----
# Verified against the actual frontend: js/elements.js, js/events.js, index.html
PERIOD_SELECTOR = ".TimeLeft__C-id"
TIME_SELECTOR = ".TimeLeft__C-time"
NUM_ITEM_SELECTOR = ".Betting__C-numC-item"          # -> .Betting__C-numC-item0 .. item9
GAME_ITEM_SELECTOR = ".GameList__C-item"
BALANCE_SELECTOR = ".Wallet__C-balance-l1"
BET_POPUP_SELECTOR = ".Betting__Popup-body"
BET_CONFIRM_SELECTOR = ".Betting__Popup-foot-s"      # "Total amount ₹..." button
BET_CANCEL_SELECTOR = ".Betting__Popup-foot-c"       # "Cancel" button
BET_AGREE_SELECTOR = ".Betting__Popup-agree"
BET_SHEET_ITEM_SELECTOR = ".Betting__Popup-body-line-item"
BET_QUANTITY_INPUT_SELECTOR = "#van-field-5-input, .Betting__Popup-input input"
TOAST_SUCCESS_SELECTOR = ".van-toast--text"
TOAST_FAIL_SELECTOR = ".van-toast--fail"
WIN_DIALOG_SELECTOR = ".WinningTip__C"
LOGIN_PHONE_SELECTOR = "input[name='userNumber'], input[placeholder*='phone'], input[placeholder*='Phone']"
LOGIN_PASS_SELECTOR = "input[type='password']"
LOGIN_SUBMIT_SELECTOR = (
    ".signIn__container-button button:has-text('Log in'), "
    ".signIn__container-button button, "
    "button:has-text('Log in'), button:has-text('Log In')"
)

CLOSE_SELECTORS = [
    ".first-recharge-queue-dialog__close",
    ".closeBtn",
    ".close-btn",
    ".van-icon-cross",
    ".van-icon-close",
    ".van-popup__close-icon",
    ".van-popup__close-icon--bottom",
    ".dialog__close",
    "img[src*='close']",
    "[class*='close-icon']",
    "[class*='CloseBtn']",
    ".activity-close",
]

# Betting/timing tuning.
# WinGo 1M rule: "1 minute 1 issue, 45 seconds to order, 15 seconds waiting for
# the draw" — ordering LOCKS 15s before the draw. Clicking numbers inside that
# window is what caused the endless "Modal still open (Glitch detected)" retries.
GAME_LOCK_SECONDS = 15    # site closes ordering 15s before the draw
BET_MIN_SECONDS = 18      # never click numbers closer than this to the draw
BET_STOP_SECONDS = 18     # mid-loop: stop before entering the locked zone
MIN_WINDOW_SECONDS = 40   # need ~22s usable to fit all 10 bets before the lock
                          # (works whether a fresh window shows 45s or 59s)
WAIT_WINDOW_TIMEOUT = 80  # max seconds to wait for a fresh betting window
WAIT_FLIP_TIMEOUT = 12    # max seconds to wait for a lagging board to flip
BET_UNIT_CAP = 100       # prefer the "100" balance chip (same as the old behaviour)
DEFAULT_BET_UNIT = 100
POPUP_OPEN_TIMEOUT = 2500   # ms after clicking a number
POPUP_CLOSE_TIMEOUT = 2000  # ms after clicking Confirm/Cancel


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def profile_dir(idx, owner_id):
    return os.path.join(BASE_DIR, f"playwright_profile_{idx}_{owner_id}")


def period_matches(on_page: str, intended: str) -> bool:
    """True when the on-page period looks like the intended period.
    Kept lenient (compares the last 4 digits) because the on-page number
    may carry leading prefix digits that differ across gateways."""
    a = ''.join(filter(str.isdigit, on_page or ''))
    b = ''.join(filter(str.isdigit, intended or ''))
    if len(a) < 4 or len(b) < 4:
        return True
    return a[-4:] == b[-4:]


def _period_seq(period: str):
    """Last 4 digits of a period as int (round sequence), or None."""
    d = ''.join(filter(str.isdigit, period or ''))
    if len(d) < 4:
        return None
    try:
        return int(d[-4:])
    except ValueError:
        return None


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

    # ------------------------------------------------------------------ #
    #  logging + emit
    # ------------------------------------------------------------------ #
    def log(self, msg):
        print(msg, flush=True)

    def _emit_status(self, key, value):
        """Orchestrator-readable status lines. Prefix is indexed by client id."""
        self.log(f"{key}_{self.idx}={value}")

    def _emit_failed(self):
        self.log(f"FAILED_CLIENT_INFO={self.idx}:{self.phone}:{self.password}")
        self.log(f"INCOMPLETE_BETS_ERROR_FOR_CLIENT={self.idx}")

    # ------------------------------------------------------------------ #
    #  tiny locator helpers (safe against the old .count() overflow bug)
    # ------------------------------------------------------------------ #
    @staticmethod
    def _visible(locator, timeout=500) -> bool:
        try:
            return locator.first.is_visible(timeout=timeout)
        except Exception:
            return False

    @staticmethod
    def _hidden(locator, timeout=500) -> bool:
        try:
            return locator.first.is_hidden(timeout=timeout)
        except Exception:
            return True

    @staticmethod
    def _has(locator) -> bool:
        try:
            return locator.first.count() > 0
        except Exception:
            return False

    @staticmethod
    def _text(locator, timeout=500) -> str:
        try:
            return (locator.first.inner_text(timeout=timeout) or "").strip()
        except Exception:
            return ""

    # ------------------------------------------------------------------ #
    #  token / announcements
    # ------------------------------------------------------------------ #
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

            # "No more reminders today" bottom-sheet dismiss
            try:
                no_reminders = page.locator("text='No more reminders today'").first
                if no_reminders.is_visible(timeout=250):
                    no_reminders.click(timeout=800)
                    time.sleep(0.4)
                    dismissed = True
            except Exception:
                pass

            for sel in CLOSE_SELECTORS:
                try:
                    el = page.locator(sel).first
                    if el.is_visible(timeout=250):
                        self.log(f"👉 Dismissing popup using selector: {sel}")
                        el.click(timeout=1200)
                        time.sleep(0.6)
                        dismissed = True
                        break
                except Exception:
                    pass

            # prometheus/first-recharge dialog: confirm button closes it too
            if not dismissed:
                try:
                    confirm_el = page.locator(".first-recharge-queue-dialog button:has-text('Confirm')").first
                    if confirm_el.is_visible(timeout=250):
                        self.log("👉 Dismissing first-recharge prompt via its Confirm button")
                        confirm_el.click(timeout=1200)
                        time.sleep(0.6)
                        dismissed = True
                except Exception:
                    pass

            if not dismissed:
                break

    # ------------------------------------------------------------------ #
    #  login
    # ------------------------------------------------------------------ #
    def is_logged_out(self, page) -> bool:
        try:
            if page.locator(".van-toast:has-text('expired'), .van-toast:has-text('login')").is_visible(timeout=700):
                return True
            if "#/login" in page.url:
                return True
            if page.locator("input[name='userNumber'], input[placeholder*='phone']").first.is_visible(timeout=700):
                return True
            if (page.locator(".p8-home__guest-btn--login").is_visible(timeout=700)
                    and not self._visible(page.locator(PERIOD_SELECTOR), timeout=700)):
                return True
        except Exception:
            pass
        return False

    def ensure_logged_in(self, page) -> bool:
        time.sleep(2)
        current_url = ""
        try:
            current_url = page.url
        except Exception:
            pass

        phone_el = page.locator(LOGIN_PHONE_SELECTOR).first
        login_btn_el = page.locator(".p8-home__guest-btn--login").first
        needs_login = False
        try:
            if ("#/login" in current_url or phone_el.is_visible(timeout=800)
                    or login_btn_el.is_visible(timeout=800)):
                needs_login = True
        except Exception:
            pass

        if not needs_login:
            return True

        self.log("🔑 Logging in automatically...")
        try:
            if "#/login" not in current_url:
                page.goto(self.login_url)
                time.sleep(2)

            phone_field = page.locator(LOGIN_PHONE_SELECTOR).first
            phone_field.wait_for(state="visible", timeout=8000)
            phone_field.fill(self.phone)
            time.sleep(0.3)

            pwd_field = page.locator(LOGIN_PASS_SELECTOR).first
            if pwd_field.is_visible(timeout=2000):
                pwd_field.fill(self.password)
                time.sleep(0.3)
            else:
                self.log("⚠️ Password field nahi mila — login page alag format ka hai")

            try:
                rem_cb = page.locator(".signIn__container-rememberRow .van-checkbox").first
                if rem_cb.is_visible(timeout=800) and rem_cb.get_attribute("aria-checked") == "false":
                    rem_cb.click()
            except Exception:
                pass

            submit = page.locator(LOGIN_SUBMIT_SELECTOR).first
            submit.click()
            self.log("👉 Login button clicked, waiting for authentication...")
            time.sleep(4)
            self.dismiss_announcements(page)
            self.setup_lottery_token(page)
            # verify login actually happened
            logged_out = self.is_logged_out(page)
            if logged_out:
                self.log("⚠️ Login ke baad bhi login page par hai — credentials/OTP check karo")
                return False
            return True
        except Exception as e:
            self.log(f"❌ Auto-login error: {e}")
            return False

    def force_login(self, page) -> bool:
        self.log("🔁 Force re-login kar raha hoon")
        try:
            page.goto(self.login_url)
            time.sleep(2)
            self.dismiss_announcements(page)

            phone_field = page.locator(LOGIN_PHONE_SELECTOR).first
            phone_field.wait_for(state="visible", timeout=10000)
            phone_field.fill(self.phone)
            time.sleep(0.3)

            pwd_field = page.locator(LOGIN_PASS_SELECTOR).first
            if pwd_field.is_visible(timeout=2000):
                pwd_field.fill(self.password)
                time.sleep(0.3)

            page.locator(LOGIN_SUBMIT_SELECTOR).first.click()
            self.log("👉 Login button clicked (force), waiting...")
            time.sleep(4)
            self.dismiss_announcements(page)
            self.setup_lottery_token(page)
            if self.is_logged_out(page):
                return False
            page.goto(self.room_url)
            return self.ensure_wingo_room(page, attempts=3)
        except Exception as e:
            self.log(f"❌ Force login fail: {e}")
            return False

    # ------------------------------------------------------------------ #
    #  board / room / timers / balance
    # ------------------------------------------------------------------ #
    def board_visible(self, page, timeout=1500) -> bool:
        return self._visible(page.locator(PERIOD_SELECTOR), timeout=timeout)

    def ensure_1min_tab(self, page):
        """Best-effort: make sure the 1Min game tab is selected."""
        try:
            tab = page.locator(".GameList__C-item").filter(
                has_text=re.compile(r"1\s*Min", re.I)).first
            if tab.is_visible(timeout=800):
                classes = (tab.get_attribute("class") or "")
                if "active" not in classes:
                    self.log("👉 Ensuring 1Min tab is selected...")
                    tab.click(timeout=1000)
                    time.sleep(1)
        except Exception as e:
            self.log(f"⚠️ Could not click 1Min tab: {e}")

    def ensure_wingo_room(self, page, attempts=5) -> bool:
        for attempt in range(attempts):
            time.sleep(1)
            self.dismiss_announcements(page)

            if self.is_logged_out(page):
                self.log(f"🔑 Attempt {attempt+1}: logged out laga, login kar raha hoon")
                if not self.ensure_logged_in(page):
                    self.debug_shot(page, "login")
                self.setup_lottery_token(page)
                time.sleep(2)
                self.dismiss_announcements(page)

            if self.board_visible(page, timeout=1500):
                self.ensure_1min_tab(page)
                return True

            self.log(f"⚠️ Attempt {attempt+1}/{attempts} board nahi mila -> {self.diagnose(page)}")

            try:
                self.setup_lottery_token(page)
                self.log("👉 Room url dobara khol raha hoon")
                page.goto(self.room_url)
                time.sleep(3)
                self.dismiss_announcements(page)
            except Exception as e:
                self.log(f"⚠️ Room url kholne me error: {e}")

        return self.board_visible(page, timeout=3000)

    def open_room(self, page) -> bool:
        if not self.ensure_logged_in(page):
            self.setup_lottery_token(page)
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
        return self._text(page.locator(PERIOD_SELECTOR), timeout=timeout)

    @staticmethod
    def _parse_countdown(text: str):
        """Parse "0 0 : 1 3" / "00:13" / "01:13" style countdown into seconds."""
        if not text:
            return None
        digits = ''.join(filter(str.isdigit, text))
        if not digits:
            return None
        # strip a trailing ':' separator pattern is already handled (non-digits dropped)
        if len(digits) >= 4:
            mm = digits[-4:-2]
            ss = digits[-2:]
            try:
                return int(mm) * 60 + int(ss)
            except ValueError:
                return None
        try:
            return int(digits)
        except ValueError:
            return None

    def seconds_left(self, page, timeout=1000):
        text = self._text(page.locator(TIME_SELECTOR), timeout=timeout)
        parsed = self._parse_countdown(text)
        if parsed is not None:
            return parsed
        # fallback: any generic count-down element on the page
        fallback = self._text(page.locator(".van-count-down, .countDown, .time"), timeout=timeout)
        return self._parse_countdown(fallback)

    def read_balance(self, page, timeout=1500, tries=1):
        """Read the wallet balance shown on the WinGo board.
        Returns float or None (unknown). `tries` re-reads with a short pause
        (the wallet line renders late / re-renders around the period roll)."""
        for attempt in range(max(1, tries)):
            if attempt:
                time.sleep(0.8)
            text = self._text(page.locator(BALANCE_SELECTOR), timeout=timeout)
            if not text:
                # fallback: any element under the wallet header
                text = self._text(page.locator(".Wallet__C-balance"), timeout=timeout)
            nums = re.findall(r"\d[\d,]*(?:\.\d+)?", text or "")
            for n in nums:
                try:
                    return float(n.replace(",", ""))
                except ValueError:
                    continue
        return None

    # ------------------------------------------------------------------ #
    #  diagnostics
    # ------------------------------------------------------------------ #
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
            bits.append("board=yes" if self.board_visible(page, timeout=600) else "board=no")
        except Exception:
            bits.append("board=no")
        try:
            if page.locator(LOGIN_PHONE_SELECTOR).first.is_visible(timeout=600):
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

    # ------------------------------------------------------------------ #
    #  refresh / keepalive
    # ------------------------------------------------------------------ #
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

    # ------------------------------------------------------------------ #
    #  bet-sheet helpers
    # ------------------------------------------------------------------ #
    def _confirm_total(self, page, timeout=800):
        """Total amount shown on the Confirm button, e.g. 'Total amount ₹500.00'."""
        text = self._text(page.locator(BET_CONFIRM_SELECTOR), timeout=timeout)
        if not text:
            return None
        nums = re.findall(r"\d[\d,]*(?:\.\d+)?", text)
        if not nums:
            return None
        try:
            return float(nums[-1].replace(",", ""))
        except ValueError:
            return None

    def sheet_total(self, page):
        """Backwards-compatible alias: total amount currently selected."""
        return self._confirm_total(page)

    def _available_bet_units(self, page, timeout=800):
        """Read the numeric balance chips shown inside the bet popup (1/10/100/1000...)."""
        units = set()
        try:
            items = page.locator(BET_SHEET_ITEM_SELECTOR)
            for i in range(items.count()):
                t = (items.nth(i).inner_text(timeout=timeout) or "").strip()
                if re.fullmatch(r"\d+", t or ""):
                    try:
                        units.add(int(t))
                    except ValueError:
                        continue
        except Exception:
            pass
        return sorted(units)

    def _choose_unit_and_qty(self, units, balance, target_total):
        """Pick a sheet chip (unit) and quantity (1..120) that come closest
        to target_total without exceeding the wallet balance."""
        if not units:
            units = [1, 10, 100, 1000]
        feasible = [u for u in units if balance is None or u <= balance] or [min(units)]

        # prefer the "100" chip to mirror the original behaviour when affordable
        preferred = [u for u in feasible if u == DEFAULT_BET_UNIT]
        ordered = preferred + sorted((u for u in feasible if u != DEFAULT_BET_UNIT), reverse=True)

        for unit in ordered:
            if target_total >= unit and target_total % unit == 0:
                qty = target_total // unit
                if 1 <= qty <= 120 and (balance is None or unit * qty <= balance):
                    return unit, int(qty)
        # closest non-divisible fit (never above balance)
        for unit in ordered:
            qty = max(1, min(120, int(target_total // unit)))
            if balance is not None and unit * qty > balance:
                qty = max(1, int(balance // unit))
            if unit * qty <= (balance if balance is not None else unit * qty):
                return (unit, int(qty))
        # fallback: smallest unit at qty directly capped by balance
        smallest = min(units) if units else 1
        qty = max(1, int(balance // smallest)) if balance is not None else 1
        return smallest, qty

    def set_bet_amount(self, page, target_total, balance=None):
        """Select a chip + quantity on the open popup; returns the verified total."""
        for attempt in range(3):
            units = self._available_bet_units(page)
            unit, qty = self._choose_unit_and_qty(units, balance, target_total)

            try:
                page.locator(BET_SHEET_ITEM_SELECTOR).filter(
                    has_text=re.compile(rf"^{unit}$")).first.click(timeout=1200)
            except Exception:
                try:
                    page.get_by_text(str(unit), exact=True).first.click(timeout=800)
                except Exception:
                    pass

            try:
                qty_el = page.locator(BET_QUANTITY_INPUT_SELECTOR).first
                qty_el.wait_for(state="visible", timeout=1500)
                if attempt == 0:
                    qty_el.click(timeout=800)
                    page.keyboard.press("End")
                    for _ in range(4):
                        page.keyboard.press("Backspace")
                    page.keyboard.type(str(qty))
                else:
                    qty_el.fill(str(qty), timeout=800)
                try:
                    qty_el.dispatch_event("input")
                    qty_el.dispatch_event("change")
                except Exception:
                    pass
            except Exception as e:
                self.log(f"⚠️ Quantity {qty} set nahi hui (attempt {attempt+1}): {e}")

            total = self._confirm_total(page)
            expected = unit * qty
            if total is not None and abs(total - expected) < 0.01:
                return total
            self.log(f"⚠️ Total ₹{total} dikh raha hai, ₹{expected} chahiye — dobara set kar raha hoon")

        return self._confirm_total(page)

    # ------------------------------------------------------------------ #
    #  modal handling
    # ------------------------------------------------------------------ #
    def _popup_open(self, page, timeout=600) -> bool:
        return self._visible(page.locator(BET_POPUP_SELECTOR), timeout=timeout)

    def _popup_closed(self, page, timeout=600) -> bool:
        return self._hidden(page.locator(BET_POPUP_SELECTOR), timeout=timeout)

    def _ensure_agreed(self, page):
        """The popup needs 'I agree' active before Confirm works."""
        try:
            agree = page.locator(BET_AGREE_SELECTOR).first
            if agree.is_visible(timeout=500):
                classes = agree.get_attribute("class") or ""
                if "active" not in classes:
                    agree.click(timeout=800)
                    time.sleep(0.2)
        except Exception:
            pass

    def _force_close_modal(self, page):
        """Last-resort modal cleanup, mirroring the app's own Cancel handler.
        (Clicking Cancel can fail during the 'Glitch' re-render.)"""
        try:
            page.locator(BET_CANCEL_SELECTOR).first.click(timeout=500)
            time.sleep(0.2)
        except Exception:
            pass
        try:
            page.evaluate("""() => {
                const ov = document.querySelector('div[role="dialog"] .van-overlay')
                         || document.querySelector('.van-overlay');
                if (ov) ov.style.setProperty('display', 'none');
                const dlg = document.querySelector('div[role="dialog"]');
                if (dlg) dlg.style.setProperty('display', 'none');
                document.body.classList.remove('van-overflow-hidden');
            }""")
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    #  core betting
    # ------------------------------------------------------------------ #
    def _wait_for_window(self, page, min_window):
        """Wait until the board shows a fresh betting window with at least
        `min_window` seconds left (i.e. enough room to fit all 10 bets before
        the 15s draw-lock). Returns (period, secs) or (None, None) on timeout."""
        deadline = time.time() + WAIT_WINDOW_TIMEOUT
        logged = False
        polls = 0
        while time.time() < deadline:
            polls += 1
            if polls == 1 or polls % 5 == 0:
                try:
                    self.dismiss_announcements(page)
                except Exception:
                    pass
            period = self.current_period(page, timeout=1500)
            secs = self.seconds_left(page, timeout=800)
            if period and secs is not None and secs >= min_window:
                return period, secs
            if not logged:
                self.log(f"⏳ Is period me poora window nahi mila (secs={secs}) "
                         f"— agle period ka wait kar raha hoon...")
                logged = True
            time.sleep(1.0)
        return None, None

    def place_bets(self, page, mode="bet", intended_period=None) -> dict:
        result = {"ok": False, "bets": 0, "amount": 0, "period": "",
                  "reason": "", "balance": None}

        self.dismiss_announcements(page)

        # 1) period
        on_page_period = self.current_period(page, timeout=5000)
        if on_page_period:
            self.log(f"👉 Current Period: {on_page_period}")
        else:
            self.log("⚠️ Period number not found.")
        result["period"] = on_page_period or "unknown"

        if on_page_period and intended_period and not period_matches(on_page_period, intended_period):
            board_seq = _period_seq(on_page_period)
            want_seq = _period_seq(intended_period)
            if board_seq is not None and want_seq is not None and board_seq > want_seq:
                # CDN was stale when the round was planned (common right after a
                # draw) — the on-page period IS the open round; bet on it.
                self.log(f"⏰ CDN stale tha — board actual period {on_page_period} "
                         f"pe bet laga raha hoon (planned {intended_period}).")
            else:
                # board is behind (mid-roll / lagging render) — give it a moment
                self.log(f"⏰ Board abhi purana period dikha raha hai "
                         f"({on_page_period} != {intended_period}) — flip ka wait...")
                deadline = time.time() + WAIT_FLIP_TIMEOUT
                flipped = False
                while time.time() < deadline:
                    time.sleep(1.0)
                    np = self.current_period(page, timeout=1000)
                    if not np:
                        continue
                    nseq = _period_seq(np)
                    if period_matches(np, intended_period) or (
                            nseq is not None and want_seq is not None and nseq > want_seq):
                        self.log(f"👉 Period flip ho gaya: {np}")
                        on_page_period = np
                        result["period"] = np
                        flipped = True
                        break
                if not flipped:
                    self.log(f"⏰ Period mismatch! Expected {intended_period}, found {on_page_period}. Aborting.")
                    result["reason"] = "period mismatch"
                    self._emit_failed()
                    return result

        # 2) balance (funds check) — retries so a slow/re-rendering wallet line
        #    does not read as "no balance" right before betting
        balance = self.read_balance(page, timeout=2000, tries=3)
        result["balance"] = balance
        if balance is not None:
            self.log(f"💰 ID {self.idx} balance: ₹{balance:,.2f}")
            self._emit_status("BALANCE", f"{balance}")
        else:
            self.log(f"⚠️ ID {self.idx} balance detect nahi hua (board abhi load ho raha hai?)")

        # 3) timing: need a full window (10 bets + the 15s draw-lock). If this
        #    period's window is too short, wait for the next period instead of
        #    clicking into the locked zone (that was the "Glitch detected" spam).
        secs = self.seconds_left(page)
        if secs is None:
            self.log("⚠️ Countdown nahi mila — phir bhi bet try kar raha hoon")
        else:
            self.log(f"⏱️ Seconds left: {secs}")

        if secs is not None and secs < MIN_WINDOW_SECONDS:
            new_period, new_secs = self._wait_for_window(page, MIN_WINDOW_SECONDS)
            if new_period:
                self.log(f"🔄 Naya betting window mila — period {new_period} "
                         f"({new_secs}s left) pe bet laga raha hoon.")
                on_page_period = new_period
                result["period"] = new_period
                secs = new_secs
                new_balance = self.read_balance(page, timeout=1500, tries=2)
                if new_balance is not None:
                    balance = new_balance
                    result["balance"] = balance
                    self.log(f"💰 ID {self.idx} balance: ₹{balance:,.2f}")
                    self._emit_status("BALANCE", f"{balance}")
            else:
                secs = self.seconds_left(page)
                if secs is not None and secs <= BET_MIN_SECONDS:
                    self.log(f"⏰ Sirf {secs}s bache hain — is period pe bet lock hai, "
                             f"aur agla window bhi nahi mila.")
                    result["reason"] = f"only {secs}s left"
                    self._emit_failed()
                    return result
                self.log("⚠️ Naya window confirm nahi hua — current board pe hi bet try kar raha hoon.")

        # 4) amount
        multiplier = random.randint(1, 24) * 5          # 5 .. 120 (unchanged)
        if balance is not None and balance < 1:
            self.log(f"❌ ID {self.idx} wallet khaali hai (₹{balance:.2f}) — bet possible nahi.")
            result["reason"] = "no funds"
            self._emit_status("FUNDS", "empty")
            self._emit_failed()
            return result

        # nominal target = multiplier * 100 (same as before); auto-fit to balance
        target_total = multiplier * DEFAULT_BET_UNIT
        if balance is not None and balance < target_total:
            target_total = max(1.0, float(int(balance // 1)))
            self.log(f"⏳ Balance ₹{balance:,.2f} — bet auto-adjust ho kar ₹{target_total:,.0f}"
                     f" (x{multiplier}) target rakha")
        self.log(f"🎲 Selected random bet amount for this period: ₹{target_total:,.0f}")
        self.log(f"BET_AMOUNT_{self.idx}={target_total:g}")
        result["amount"] = target_total

        if balance is not None and balance < 1:
            self.log(f"❌ ID {self.idx} ke paas bet ke liye balance nahi.")
            result["reason"] = "insufficient balance"
            self._emit_status("FUNDS", "insufficient")
            self._emit_failed()
            return result

        # 5) place the bets
        successful_bets = 0
        funds_done = False
        period_changed = False

        def cleanup_leftover():
            if self._popup_open(page, timeout=200):
                self.log("🧹 Puraani bet modal khuli thi — close kar raha hoon")
                self._force_close_modal(page)
                time.sleep(0.2)

        cleanup_leftover()

        for num in range(10):
            if period_changed or funds_done:
                break
            number_to_bet = str(num)
            bet_ok = False

            for attempt in range(3):
                # timing re-check
                try:
                    loop_period = self.current_period(page, timeout=200)
                    if on_page_period and loop_period and loop_period != on_page_period:
                        self.log(f"⏰ Period changed from {on_page_period} to {loop_period}. Stopping loop.")
                        period_changed = True
                        break
                except Exception:
                    pass

                secs = self.seconds_left(page, timeout=200)
                if secs is not None and secs <= BET_STOP_SECONDS:
                    self.log(f"⏰ Only {secs} seconds left! Betting is locked. Stopping loop.")
                    result["reason"] = f"locked at {secs}s"
                    break

                if funds_done:
                    break

                try:
                    page.evaluate("if ((window.scrollY || document.documentElement.scrollTop) > 50) "
                                  "window.scrollTo({ top: 0, behavior: 'instant' })")
                except Exception:
                    pass

                self.log(f"👉 Clicking on Number {number_to_bet} (Attempt {attempt+1})...")
                try:
                    num_ball = page.locator(f"{NUM_ITEM_SELECTOR}{number_to_bet}").first
                    num_ball.click(timeout=1500)
                except Exception:
                    # some builds re-render mid-round; retry via JS dispatch once
                    try:
                        page.locator(f"{NUM_ITEM_SELECTOR}{number_to_bet}").first.dispatch_event("click")
                    except Exception:
                        pass

                if not self._popup_open(page, timeout=POPUP_OPEN_TIMEOUT):
                    if self._visible(page.locator(TOAST_FAIL_SELECTOR), timeout=300):
                        self.log(f"💸 ID {self.idx}: insufficient balance toast dekha — funds khatam.")
                        result["reason"] = "insufficient balance"
                        self._emit_status("FUNDS", "insufficient")
                        funds_done = True
                        break
                    self.log(f"⚠️ Number {number_to_bet} pe bet popup nahi khula "
                             f"(attempt {attempt+1}) — retry karta hoon")
                    self._force_close_modal(page)
                    continue

                self._ensure_agreed(page)
                placed = self.set_bet_amount(page, target_total, balance=balance)
                if placed is not None and placed != result["amount"]:
                    self.log(f"ℹ️ Asli total ₹{placed:,.0f} laga (planned ₹{result['amount']:,.0f})")
                    self.log(f"BET_AMOUNT_{self.idx}={placed:g}")
                    result["amount"] = placed

                # Confirm
                confirmed = False
                try:
                    confirm_btn = page.locator(BET_CONFIRM_SELECTOR).first
                    if not confirm_btn.is_visible(timeout=500):
                        self.log(f"⚠️ Number {number_to_bet}: Confirm button visible nahi — retry")
                        self._force_close_modal(page)
                        continue
                    confirm_btn.click(timeout=1500)
                    confirmed = True
                except Exception as e:
                    self.log(f"⚠️ Confirm click fail on {number_to_bet}: {e}")

                # wait for the modal to close (bet accepted) or a fail toast (funds)
                closed = self._popup_closed(page, timeout=POPUP_CLOSE_TIMEOUT) if confirmed else False
                success_toast = self._visible(page.locator(TOAST_SUCCESS_SELECTOR), timeout=600)
                fail_toast = self._visible(page.locator(TOAST_FAIL_SELECTOR), timeout=600)

                if fail_toast:
                    self.log(f"💸 ID {self.idx}: bet reject hui — insufficient balance/error toast.")
                    result["reason"] = "bet rejected (insufficient balance)"
                    self._emit_status("FUNDS", "insufficient")
                    funds_done = True
                    self._force_close_modal(page)
                    break

                if closed or success_toast:
                    self.log(f"✅ Bet Confirmed for {number_to_bet}!")
                    successful_bets += 1
                    bet_ok = True
                    time.sleep(0.05)
                    break

                # glitch: modal still open after Confirm
                self.log(f"⚠️ Number {number_to_bet}: modal abhi bhi khuli hai (Glitch detected) — "
                         f"Cancel karke retry.")
                self._force_close_modal(page)
                time.sleep(0.15)

            if not bet_ok and not funds_done and not period_changed:
                # one more timing guard before moving to next number
                secs = self.seconds_left(page, timeout=150)
                if secs is not None and secs <= BET_STOP_SECONDS:
                    break

        result["bets"] = successful_bets

        if funds_done or result["reason"] in ("insufficient balance", "no funds", "bet rejected (insufficient balance)"):
            self.log(f"❌ ID {self.idx}: funds/balance issue — {result['reason']}")
            self._emit_failed()
            return result

        need = 10
        if successful_bets == 0 or (mode == "hbet" and successful_bets < need):
            self.log(f"❌ Only {successful_bets} bets were placed. Aborting.")
            self._emit_failed()
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

    # ------------------------------------------------------------------ #
    #  results
    # ------------------------------------------------------------------ #
    def _fetch_winning_number(self):
        try:
            import requests
            r = requests.get(self.cdn_url, timeout=5)
            return r.json()["data"]["list"][0].get("number")
        except Exception as e:
            self.log(f"⚠️ Could not fetch winning number: {e}")
            return None

    def _winning_from_cdn(self):
        if not self.cdn_url:
            return None
        win = self._fetch_winning_number()
        if win is not None:
            self.log(f"WINNING_NUMBER={win}")
        return win

    def capture_result(self, page, mode, info) -> None:
        successful_bets = info.get("bets", 0)
        total_seconds_left = self.seconds_left(page)
        if total_seconds_left is None:
            total_seconds_left = 50
        wait_timeout = (total_seconds_left + 15) * 1000

        if mode == "hbet":
            self.log(f"Waiting for result... (Timeout: {wait_timeout//1000}s)")
            try:
                time.sleep(total_seconds_left + 5)
            except Exception:
                pass

            self._winning_from_cdn()

            # Screenshot of the board after the round resolves.
            try:
                self.dismiss_announcements(page)
                time.sleep(1)
                screenshot_path = os.path.join(
                    BASE_DIR, f"hbet_win_{self.idx}_{self.owner_id}.png")
                page.screenshot(path=screenshot_path)
                self.log(f"SUCCESS_SCREENSHOT_PATH_{self.idx}={screenshot_path}")
            except Exception as e:
                self.log(f"⚠️ hbet screenshot fail: {e}")
            return

        # ---- mode == "bet": WinGo 1Min win popup (Congratulations) ----
        self.log(f"Waiting for Congratulations popup... (Timeout: {wait_timeout//1000}s)")
        win_dialog = page.locator(WIN_DIALOG_SELECTOR).first
        try:
            page.wait_for_selector(WIN_DIALOG_SELECTOR, state="visible", timeout=wait_timeout)
            self.log("🎉 Winning Popup Detect ho gaya! Screenshot le raha hu...")
            time.sleep(1.5)
        except Exception:
            # popup may already be gone / auto-dismissed; still chase the CDN win number
            try:
                if not win_dialog.is_visible(timeout=500):
                    page.wait_for_selector("text='Congratulations'", timeout=wait_timeout)
                    self.log("🎉 Winning Popup (text) Detect ho gaya! Screenshot le raha hu...")
                    time.sleep(1.5)
            except Exception as e:
                self.log(f"⚠️ Winning popup nahi dikha: {e}")

        try:
            screenshot_path = os.path.join(BASE_DIR, f"auto_win_popup_{self.idx}_{self.owner_id}.png")
            page.screenshot(path=screenshot_path)
            self.log(f"SUCCESS_SCREENSHOT_PATH_{self.idx}={screenshot_path}")
        except Exception as e:
            self.log(f"⚠️ Win screenshot fail: {e}")

        try:
            time.sleep(2)
            self._winning_from_cdn()
        except Exception as e:
            self.log(f"⚠️ Could not fetch winning number: {e}")

        if successful_bets < 10:
            self._emit_failed()
        else:
            self.log("ℹ️ WinGo 1Min round ka result capture complete.")

    def run_round(self, page, mode="bet", intended_period=None) -> dict:
        info = self.place_bets(page, mode, intended_period)
        if info.get("ok"):
            self.capture_result(page, mode, info)
        return info
