"""
bot_menu.py — Saare commands BUTTONS me. Bot ko /start ya /menu bhejo.

Ye file bot_setup.py ke upar menu layer hai:
  - /start /menu  -> main menu (inline buttons)
  - har setting button dabao -> bot khud puchega, jawab text me bhejo
  - /wale purane commands bhi chalte rahenge
"""

import os
import re
import copy
import time

from pyrogram import filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery

import bot_setup as bs


# ------------------------------------------------------------------ helpers

def kb(rows):
    """rows = [[(text, callback), ...], ...]"""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(t, callback_data=d) for t, d in row] for row in rows]
    )


HOME = [[("🏠 Menu", "m:main")]]
CANCEL_KB = kb([[("❌ Radd karo", "act:cancel")]])
BACK_MAIN = kb(HOME)


def _uid_str(cb_or_msg) -> str:
    u = cb_or_msg.from_user
    return str(u.id) if u else "0"


async def _need_priv(cb: CallbackQuery):
    """Returns uid_str or None (alert bhej ke)."""
    uid = _uid_str(cb)
    if not bs.is_privileged(int(uid) if uid.isdigit() else 0):
        try:
            await cb.answer("❌ Unauthorized — sirf owners.", show_alert=True)
        except Exception:
            pass
        return None
    return uid


async def _need_owner(cb: CallbackQuery):
    uid = await _need_priv(cb)
    if uid is None:
        return None
    if bs.owner_section(uid) is None:
        try:
            await cb.answer("❌ Ye sirf owners ke liye hai.", show_alert=True)
        except Exception:
            pass
        return None
    return uid


async def _show(cb: CallbackQuery, text: str, markup=None):
    try:
        await cb.message.edit_text(text, reply_markup=markup)
    except Exception:
        try:
            await cb.message.reply_text(text, reply_markup=markup)
        except Exception:
            pass


async def _ask(cb: CallbackQuery, prompt: str):
    """Naya prompt message bhejo (menu wahi rahega) + cancel button."""
    try:
        await cb.message.reply_text(prompt, reply_markup=CANCEL_KB)
    except Exception:
        pass


def _set_input(uid: int, action: str, step: str, data: dict):
    bs.pending_input.pop(uid, None)
    bs.pending_logins.pop(uid, None)
    bs.pending_input[uid] = {"action": action, "step": step, "data": data, "ts": time.time()}


def _quick_stats(uid: str) -> str:
    owners = bs.cfg().get("owners", {})
    o_login = sum(1 for o in owners if o in bs._ctx["owner_sessions"])
    c_login = len(bs._ctx["client_slot_map"])
    return f"👑 {o_login}/{len(owners)} login • 📱 {c_login}/6 login"


# ------------------------------------------------------------------ pages

def page_main(uid: str):
    text = f"🤖 **SMEX CONTROL PANEL**\n{_quick_stats(uid)}\n\nKya karna hai? Button dabao 👇"
    markup = kb([
        [("📱 Login", "m:login"), ("📊 Status", "m:status")],
        [("🎰 WinGo IDs", "m:wingo"), ("🔗 Links", "m:urls")],
        [("💬 Messages", "m:msgs"), ("✨ Emoji / API", "m:emapi")],
        [("👑 Owners", "m:owners"), ("🌐 Browsers", "m:browsers")],
        [("🚀 Bet", "m:bet"), ("❓ Help", "m:help")],
    ])
    return text, markup


def page_login(uid: str):
    lines = ["📱 **LOGIN** (OTP se, session khud save hoga)\n"]
    sess_o = bs._ctx["owner_sessions"]
    sess_c = bs._ctx["client_slot_map"]
    if uid in bs.cfg().get("owners", {}):
        c = sess_o.get(uid)
        lines.append(f"👑 Owner: {'🟢 ' + c.my_user.first_name if c else '🔴 login nahi'}")
    else:
        lines.append("👑 Owner: (tum owner nahi ho)")
    n = len(sess_c)
    lines.append(f"📱 Clients: {n}/6 login")
    for i, env in enumerate(bs.CLIENT_SLOTS):
        c = sess_c.get(env)
        lines.append(f"  {i+1}. {'🟢 ' + c.my_user.first_name if c else '🔴 khaali'}")
    rows = []
    if uid in bs.cfg().get("owners", {}):
        rows.append([("👑 Owner login", "login:owner")])
    rows.append([("1️⃣ C1", "login:c1"), ("2️⃣ C2", "login:c2"), ("3️⃣ C3", "login:c3")])
    rows.append([("4️⃣ C4", "login:c4"), ("5️⃣ C5", "login:c5"), ("6️⃣ C6", "login:c6")])
    rows.append([("🚪 Logout...", "m:logout"), ("🏠 Menu", "m:main")])
    return "\n".join(lines), kb(rows)


def page_logout(uid: str):
    rows = []
    if uid in bs.cfg().get("owners", {}) and uid in bs._ctx["owner_sessions"]:
        rows.append([("👑 Owner logout", "logout:ask:owner")])
    for i, env in enumerate(bs.CLIENT_SLOTS):
        if env in bs._ctx["client_slot_map"]:
            rows.append([(f"📱 Client{i+1} logout", f"logout:ask:c{i+1}")])
    if not rows:
        return "🚪 Koi account login hi nahi hai.", kb(HOME)
    rows.append([("🔙 Back", "m:login")])
    return "🚪 **LOGOUT** — kisko hatana hai?", kb(rows)


def page_wingo(uid: str):
    accs = bs.owner_section(uid).get("wingo_accounts", [])
    if not accs:
        return ("🎰 **WINGO IDs** — koi ID nahi hai.\nNeeche Add dabao 👇",
                kb([[("➕ Add ID", "w:add")], [("🏠 Menu", "m:main")]]))
    lines = ["🎰 **WINGO IDs**"]
    for i, a in enumerate(accs, 1):
        lines.append(f"{i}. 📱 `{bs.mask_phone(a.get('phone', ''))}`")
    rows = [[("➕ Add ID", "w:add")]]
    row = []
    for i in range(1, len(accs) + 1):
        row.append((f"✏️{i}", f"w:edit:{i}"))
        row.append((f"🗑️{i}", f"w:delask:{i}"))
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([("🌐 Restart browsers", "br:restart")])
    rows.append([("🏠 Menu", "m:main")])
    return "\n".join(lines), kb(rows)


def page_urls(uid: str):
    u = bs.owner_section(uid).get("urls", {})
    text = ("🔗 **LINKS**\n\n"
            f"login: `{u.get('login_url', '-')}`\n"
            f"room: `{u.get('wingo_room_url', '-')}`\n"
            f"cdn: `{u.get('cdn_url', '-')}`")
    markup = kb([
        [("✏️ Login", "u:edit:login"), ("✏️ Room", "u:edit:room"), ("✏️ CDN", "u:edit:cdn")],
        [("🌐 Restart browsers", "br:restart")],
        [("🏠 Menu", "m:main")],
    ])
    return text, markup


def page_msgs(uid: str):
    o = bs.owner_section(uid)
    nb = len(o.get("bet_messages", []))
    nf = len(o.get("feedbacks", []))
    return (f"💬 **MESSAGES**\n\n💬 Bet messages: {nb}\n📝 Feedbacks: {nf}",
            kb([[("💬 Bet msgs", "m:betmsgs"), ("📝 Feedbacks", "m:feedbacks")],
                [("🏠 Menu", "m:main")]]))


def _compact_list(items, limit=12):
    lines = []
    for i, t in enumerate(items[:limit], 1):
        t = (t or "").replace("\n", " ")
        if len(t) > 70:
            t = t[:70] + "..."
        lines.append(f"{i}. {t}")
    if len(items) > limit:
        lines.append(f"... aur {len(items) - limit} (poori list: command se)")
    return "\n".join(lines) if lines else "(khaali)"


def page_betmsgs(uid: str):
    msgs = bs.owner_section(uid).get("bet_messages", [])
    text = "💬 **BET MESSAGES**\n(`{PERIOD}` auto-bharega)\n\n" + _compact_list(msgs)
    return text, kb([[("➕ Add", "b:add"), ("🗑️ Del (number)", "b:delask")],
                     [("🔙 Back", "m:msgs")]])


def page_feedbacks(uid: str):
    msgs = bs.owner_section(uid).get("feedbacks", [])
    text = "📝 **FEEDBACKS**\n(`{WIN}` `{BET}` `{NUMBER}` auto)\n\n" + _compact_list(msgs)
    return text, kb([[("➕ Add", "f:add"), ("🗑️ Del (number)", "f:delask")],
                     [("🔙 Back", "m:msgs")]])


def page_emapi(uid: str):
    active = bs._ctx["valid_emoji_ids"]
    lines = ["✨ **EMOJI / API**\n"]
    for nick in ("tick", "money", "crown", "fire"):
        env = bs.EMOJI_KEYS[nick]
        val = os.getenv(env, "").strip()
        mark = "🟢" if val and val in active else ("🟡" if val else "⚪")
        lines.append(f"{mark} {nick}: `{val or '-'}`")
    api_ok = bool(os.getenv("API_ID", "").strip()) and bool(os.getenv("API_HASH", "").strip())
    lines.append(f"\n{'🟢' if api_ok else '🔴'} API: {'set' if api_ok else 'nahi dala'}")
    lines.append(f"🌐 Headless: `{os.getenv('HEADLESS', 'false')}`")
    markup = kb([
        [("✏️ Tick", "e:edit:tick"), ("✏️ Money", "e:edit:money")],
        [("✏️ Crown", "e:edit:crown"), ("✏️ Fire", "e:edit:fire")],
        [("🔑 API set", "api:set")],
        [("🌐 Headless on/off", "hl:toggle")],
        [("🏠 Menu", "m:main")],
    ])
    return "\n".join(lines), markup


def page_owners(uid: str):
    lines = ["👑 **OWNERS**"]
    for oid, o in bs.cfg().get("owners", {}).items():
        on = "🟢" if oid in bs._ctx["owner_sessions"] else "🔴"
        nw = len(o.get("wingo_accounts", []))
        lines.append(f"{on} `{oid}` — 🎰{nw} {o.get('note', '')}")
    rows = [[("➕ Add owner", "o:add")]]
    for oid in bs.cfg().get("owners", {}):
        if oid != uid:
            rows.append([(f"🗑️ {oid}", f"o:delask:{oid}")])
    rows.append([("🏠 Menu", "m:main")])
    return "\n".join(lines), kb(rows)


def page_browsers(uid: str):
    pool = bs._ctx["browser_pools"].get(uid)
    n_acc = len(bs.owner_section(uid).get("wingo_accounts", []))
    if not pool:
        text = f"🌐 **BROWSERS** — band hain.\n🎰 WinGo IDs set: {n_acc}\nNeeche Start dabao 👇"
    else:
        lines = [f"🌐 **BROWSERS** — {pool.healthy_count()}/{len(pool.workers)} ready"]
        for w in pool.workers:
            icon = "🟢" if (w.alive and w.healthy) else ("🟡" if w.alive else "🔴")
            lines.append(f"{icon} B{w.idx}: {(w.status.strip() or w.failed_reason or '-')[:50]}")
        text = "\n".join(lines)
    markup = kb([
        [("🔄 Refresh", "br:refresh"), ("🌐 Restart", "br:restart")],
        [("🏠 Menu", "m:main")],
    ])
    return text, markup


def page_bet(uid: str):
    ok = uid in bs._ctx["owner_sessions"]
    n = len(bs._ctx["client_slot_map"])
    text = (f"🚀 **BET**\n\n👑 Owner: {'🟢 login' if ok else '🔴 login nahi — pehle /login owner'}\n"
            f"📱 Clients: {n}/6 login")
    markup = kb([
        [("🚀 BET", "bet:bet"), ("🎯 HBET", "bet:hbet")],
        [("🖼️ DP change", "bet:dp")],
        [("🏠 Menu", "m:main")],
    ])
    return text, markup


def page_status(uid: str):
    owners = bs.cfg().get("owners", {})
    o_login = sum(1 for o in owners if o in bs._ctx["owner_sessions"])
    c_login = len(bs._ctx["client_slot_map"])
    api_ok = bool(os.getenv("API_ID", "").strip()) and bool(os.getenv("API_HASH", "").strip())
    emo = sorted(bs._ctx["valid_emoji_ids"])
    lines = ["📊 **STATUS**",
             "🤖 Bot: 🟢 ON",
             f"👑 Owners: {o_login}/{len(owners)} login",
             f"📱 Clients: {c_login}/6 login",
             f"🔑 API: {'🟢' if api_ok else '🔴'}",
             f"✨ Emoji active: {len(emo)}",
             f"🌐 Headless: {os.getenv('HEADLESS', 'false')}"]
    if uid in owners:
        pool = bs._ctx["browser_pools"].get(uid)
        if pool:
            lines.append(f"🎰 Browsers: {pool.healthy_count()}/{len(pool.workers)} ready")
        else:
            lines.append("🎰 Browsers: band")
    return "\n".join(lines), kb([[("🔃 Refresh", "m:status")], [("🏠 Menu", "m:main")]])


def page_help():
    text = ("❓ **HELP**\n\n"
            "📱 **Login** — OTP se owner/client login (session khud save)\n"
            "🎰 **WinGo** — phone+password wali IDs\n"
            "🔗 **Links** — login/room/CDN links\n"
            "💬 **Messages** — bet + feedback messages\n"
            "✨ **Emoji/API** — premium emoji, API, headless\n"
            "👑 **Owners** — naye boss jodo/hatayo\n"
            "🌐 **Browsers** — refresh / restart\n"
            "🚀 **Bet** — /bet /hbet /dp yahin se\n\n"
            "⌨️ Purane `/commands` bhi chalte hain — `/help` me list hai.")
    return text, kb([[("🆕 Pehli baar setup?", "m:setup")], [("🏠 Menu", "m:main")]])


def page_setup():
    text = ("🆕 **PEHLI BAAR SETUP (sirf 5 min)**\n\n"
            "1️⃣ **Login** dabao → `Owner login` → apne main number + OTP se login\n"
            "2️⃣ **Login** me `C1..C6` — 6 client accounts login karo\n"
            "3️⃣ **WinGo IDs** → `Add` se apni WinGo phone+password dalo\n"
            "4️⃣ **Browsers** → `Restart` (2-4 min, ek baar)\n"
            "5️⃣ **Bet** → `BET` dabao. Ho gaya! 🎉\n\n"
            "⚠️ Owner login zaroori hai — bet messages aur screenshots "
            "tumhare main account se hi aate-jaate hain.")
    return text, kb([[("🔙 Back", "m:help")], [("🏠 Menu", "m:main")]])


# ------------------------------------------------------------------ actions

async def _do_logout_slot(uid: str, slot: str):
    if slot == "owner":
        await bs.stop_owner_live(uid)
        bs._rm_session_files(f"owner_{uid}")
        env = bs.cfg()["owners"][uid].get("main_id_env", f"OWNER_{uid}_SESSION")
    else:
        cidx = int(slot[1:]) - 1
        await bs.stop_client_live(cidx)
        bs._rm_session_files(f"client_{cidx + 1}")
        env = bs.CLIENT_SLOTS[cidx]
    bs.remove_env_var(env)


async def _do_restart_browsers(uid: str) -> str:
    accs = bs.owner_section(uid).get("wingo_accounts", [])
    if not accs:
        return "❌ Pehle WinGo IDs dalo (🎰 WinGo IDs → Add)."
    old = bs._ctx["browser_pools"].pop(uid, None)
    if old is not None:
        try:
            await old.stop()
        except Exception as e:
            print(f"⚠️ Purana pool band karne me error: {e}")
    try:
        from browser_pool import BrowserPool
        pool = BrowserPool(uid, accs)
        bs._ctx["browser_pools"][uid] = pool
        await pool.start()
        return (f"✅ Browsers restart: **{pool.healthy_count()}/{len(pool.workers)} ready**")
    except Exception as e:
        return f"❌ Browser restart fail: {e}"


# ------------------------------------------------------------------ text input processor (menu flows)

async def process_input(m: Message, uid: int, pi: dict):
    """Menu se shuru hue text-jawab yahan aate hain."""
    uid_s = str(uid)
    action, step, data = pi["action"], pi["step"], pi.get("data", {})
    txt = (m.text or "").strip()

    async def done(text, home=True):
        bs.pending_input.pop(uid, None)
        await m.reply_text(text, reply_markup=BACK_MAIN if home else None)

    async def ask_again(text):
        pi["ts"] = time.time()
        await m.reply_text(text, reply_markup=CANCEL_KB)

    # ---- WinGo add / edit ----
    if action in ("w_add", "w_edit"):
        if step == "phone":
            digits = re.sub(r"\D", "", txt)
            if len(digits) < 10 or len(digits) > 15:
                await ask_again("❌ Number sahi nahi. Country code ke saath bhejo (jaise `919876543210`):")
                return
            data["phone"] = txt.replace(" ", "")
            pi["step"] = "password"
            pi["ts"] = time.time()
            await m.reply_text("🔑 Ab us ID ka **password** bhejo:", reply_markup=CANCEL_KB)
            return
        if step == "password":
            if not txt:
                await ask_again("❌ Password khaali nahi ho sakta. Password bhejo:")
                return
            accs = bs.owner_section(uid_s).get("wingo_accounts", [])
            if action == "w_add":
                accs.append({"phone": data["phone"], "password": txt})
                n = len(accs)
            else:
                n = data["n"]
                accs[n - 1] = {"phone": data["phone"], "password": txt}
            bs.save_config()
            await bs.try_delete(m)
            await done(f"✅ WinGo ID **#{n}** save ho gayi ({bs.mask_phone(data['phone'])}).\n\n"
                       f"🌐 Browser me lagane ke liye neeche Restart dabao 👇\n\n"
                       f"(ya Menu → Browsers → Restart)",
                       home=False)
            await m.reply_text("👇", reply_markup=kb([[("🌐 Restart browsers", "br:restart")],
                                                      [("🏠 Menu", "m:main")]]))
            return

    # ---- Links ----
    if action == "u_edit":
        if not txt.startswith("http"):
            await ask_again("❌ Link `http` se shuru hona chahiye. Sahi link bhejo:")
            return
        bs.owner_section(uid_s).setdefault("urls", {})[data["key"]] = txt
        bs.save_config()
        await done(f"✅ Link save ho gaya.\n🌐 Menu → Browsers → **Restart** chalao.")
        return

    # ---- Emoji ----
    if action == "e_edit":
        if not txt.isdigit():
            await ask_again("❌ ID sirf ankdon me hoti hai (jaise `5463065...`). Sahi ID bhejo:")
            return
        bs.set_env_var(data["env"], txt)
        await bs.revalidate_emojis_quiet()
        ok = txt in bs._ctx["valid_emoji_ids"]
        await done(f"{'✅' if ok else '🟡'} `{data['env']}` = `{txt}` save.\n" +
                   ("🟢 Premium emoji chalega." if ok else "⚠️ Active nahi — owner pe Premium? ID sahi? (normal emoji chalega)"))
        return

    # ---- API ----
    if action == "api":
        if step == "aid":
            if not txt.isdigit():
                await ask_again("❌ API_ID sirf number hota hai. Sahi bhejo:")
                return
            data["aid"] = txt
            pi["step"] = "ahash"
            pi["ts"] = time.time()
            await m.reply_text("Ab **API_HASH** bhejo:", reply_markup=CANCEL_KB)
            return
        data_ah = txt
        if len(data_ah) < 8:
            await ask_again("❌ API_HASH itna chhota nahi hota. Sahi bhejo:")
            return
        bs.set_env_var("API_ID", data["aid"])
        bs.set_env_var("API_HASH", data_ah)
        await bs.try_delete(m)
        await done("✅ API save ho gaya.\nℹ️ Naye login isi se honge. Poora effect **restart** ke baad.")
        return

    # ---- Bet msgs / feedbacks add ----
    if action in ("b_add", "f_add"):
        if not txt:
            await ask_again("❌ Khaali message nahi. Text bhejo:")
            return
        key = "bet_messages" if action == "b_add" else "feedbacks"
        bs.owner_section(uid_s).setdefault(key, []).append(txt)
        bs.save_config()
        await done("✅ Jud gaya! Turant effect — agle /bet se chalega.")
        return

    # ---- Bet msgs / feedbacks del (number) ----
    if action in ("b_del", "f_del"):
        key = "bet_messages" if action == "b_del" else "feedbacks"
        msgs = bs.owner_section(uid_s).get(key, [])
        if not txt.isdigit() or not (1 <= int(txt) <= len(msgs)):
            await ask_again(f"❌ 1 se {len(msgs)} tak number bhejo:")
            return
        msgs.pop(int(txt) - 1)
        bs.save_config()
        await done(f"🗑️ #{txt} hata diya.")
        return

    # ---- Add owner ----
    if action == "o_add":
        if step == "oid":
            if not txt.isdigit():
                await ask_again("❌ Telegram **numeric ID** bhejo (jaise `8428751737`):")
                return
            if txt in bs.cfg().get("owners", {}):
                await done("Ye ID pehle se owner hai.")
                return
            data["nid"] = txt
            pi["step"] = "note"
            pi["ts"] = time.time()
            await m.reply_text("📝 Is owner ke liye **naam/note** bhejo (ya Skip dabao):",
                               reply_markup=kb([[("⏭️ Skip", "o:skipnote")],
                                                [("❌ Radd karo", "act:cancel")]]))
            return
        # step note
        template = next(iter(bs.cfg().get("owners", {}).values()), {})
        bs.cfg()["owners"][data["nid"]] = {
            "note": txt or "bot se add hua",
            "main_id_env": f"OWNER_{data['nid']}_SESSION",
            "urls": copy.deepcopy(template.get("urls", {"cdn_url": "", "wingo_room_url": "", "login_url": ""})),
            "bet_messages": copy.deepcopy(template.get("bet_messages", [])),
            "feedbacks": copy.deepcopy(template.get("feedbacks", ["Maza aagya {WIN} jeet gya!"])),
            "conversations": copy.deepcopy(template.get("conversations", [])),
            "confuse_chat": copy.deepcopy(template.get("confuse_chat", {})),
            "wingo_accounts": [],
        }
        bs.save_config()
        await done(f"✅ Owner `{data['nid']}` add ho gaya.\n\nUs account se:\n1️⃣ /start → Login → Owner login\n2️⃣ WinGo IDs dale\n3️⃣ Browsers → Restart")
        return

    bs.pending_input.pop(uid, None)


# ------------------------------------------------------------------ register

def register(bot):
    bs.input_processor = process_input

    @bot.on_message(filters.command(["start", "menu"], prefixes="/"))
    async def _start(_b, m: Message):
        uid = _uid_str(m)
        if not bs.is_privileged(int(uid) if uid.isdigit() else 0):
            await m.reply_text("❌ Unauthorized. Ye bot sirf owners ke liye hai.")
            return
        text, markup = page_main(uid)
        await m.reply_text(text, reply_markup=markup)

    @bot.on_callback_query()
    async def _cb(_b, cb: CallbackQuery):
        data = cb.data or ""
        try:
            await cb.answer()
        except Exception:
            pass

        # ---- cancel (login ya input) ----
        if data == "act:cancel":
            uid_int = cb.from_user.id if cb.from_user else 0
            had = False
            if uid_int in bs.pending_logins:
                await bs.cleanup_login(uid_int)
                had = True
            if uid_int in bs.pending_input:
                bs.pending_input.pop(uid_int, None)
                had = True
            try:
                await cb.message.edit_text("🚫 Radd kar diya.", reply_markup=BACK_MAIN)
            except Exception:
                pass
            return

        # ---- skip owner note ----
        if data == "o:skipnote":
            uid = await _need_priv(cb)
            if uid is None:
                return
            uid_int = int(uid)
            pi = bs.pending_input.get(uid_int)
            if not pi or pi.get("action") != "o_add":
                return
            template = next(iter(bs.cfg().get("owners", {}).values()), {})
            nid = pi["data"]["nid"]
            bs.cfg()["owners"][nid] = {
                "note": "bot se add hua",
                "main_id_env": f"OWNER_{nid}_SESSION",
                "urls": copy.deepcopy(template.get("urls", {"cdn_url": "", "wingo_room_url": "", "login_url": ""})),
                "bet_messages": copy.deepcopy(template.get("bet_messages", [])),
                "feedbacks": copy.deepcopy(template.get("feedbacks", ["Maza aagya {WIN} jeet gya!"])),
                "conversations": copy.deepcopy(template.get("conversations", [])),
                "confuse_chat": copy.deepcopy(template.get("confuse_chat", {})),
                "wingo_accounts": [],
            }
            bs.save_config()
            bs.pending_input.pop(uid_int, None)
            await _show(cb, f"✅ Owner `{nid}` add ho gaya.\n\nUs account se:\n1️⃣ /start → Login → Owner login\n2️⃣ WinGo IDs dale\n3️⃣ Browsers → Restart", BACK_MAIN)
            return

        # ---- main pages ----
        pages_priv = {"m:main": page_main, "m:login": page_login, "m:logout": page_logout,
                      "m:emapi": page_emapi, "m:owners": page_owners,
                      "m:status": page_status}
        pages_owner = {"m:wingo": page_wingo, "m:urls": page_urls, "m:msgs": page_msgs,
                       "m:betmsgs": page_betmsgs, "m:feedbacks": page_feedbacks,
                       "m:browsers": page_browsers, "m:bet": page_bet}
        if data in pages_priv:
            uid = await _need_priv(cb)
            if uid is None:
                return
            text, markup = pages_priv[data](uid)
            await _show(cb, text, markup)
            return
        if data in pages_owner:
            uid = await _need_owner(cb)
            if uid is None:
                return
            text, markup = pages_owner[data](uid)
            await _show(cb, text, markup)
            return
        if data == "m:help":
            uid = await _need_priv(cb)
            if uid is None:
                return
            text, markup = page_help()
            await _show(cb, text, markup)
            return
        if data == "m:setup":
            uid = await _need_priv(cb)
            if uid is None:
                return
            text, markup = page_setup()
            await _show(cb, text, markup)
            return

        # ---- LOGIN start ----
        if data.startswith("login:"):
            uid = await _need_priv(cb)
            if uid is None:
                return
            slot = data.split(":", 1)[1]  # owner / c1..c6
            if slot == "owner" and uid not in bs.cfg().get("owners", {}):
                await cb.answer("Tum owner nahi ho.", show_alert=True)
                return
            # pehle se login?
            if slot == "owner":
                c = bs._ctx["owner_sessions"].get(uid)
            else:
                c = bs._ctx["client_slot_map"].get(bs.CLIENT_SLOTS[int(slot[1:]) - 1])
            if c is not None:
                label = "owner" if slot == "owner" else f"client{slot[1:]}"
                await _show(cb, f"ℹ️ **{label}** pehle se login hai: {c.my_user.first_name}\n\nDobara login karna hai to pehle logout karo.",
                            kb([[("🚪 Logout karo", f"logout:ask:{slot}")], [("🔙 Back", "m:login")]]))
                return
            uid_int = int(uid)
            if uid_int in bs.pending_logins or uid_int in bs.pending_input:
                await _ask(cb, "⚠️ Ek kaam pehle se chal raha hai. Pehle use poora karo ya Radd karo.")
                return
            if slot == "owner":
                env = bs.cfg()["owners"][uid].get("main_id_env", f"OWNER_{uid}_SESSION")
                label = "owner"
                st = {"kind": "owner", "label": label, "env": env, "owner_id": uid, "cidx": None,
                      "step": "phone", "phone": "", "tmp": None, "code_hash": "", "ts": time.time()}
            else:
                cidx = int(slot[1:]) - 1
                label = f"client{cidx + 1}"
                st = {"kind": "client", "label": label, "env": bs.CLIENT_SLOTS[cidx],
                      "owner_id": None, "cidx": cidx,
                      "step": "phone", "phone": "", "tmp": None, "code_hash": "", "ts": time.time()}
            bs.pending_logins[uid_int] = st
            await _ask(cb, f"📱 **{label}** login kar rahe ho.\n\nMobile number bhejo (country code ke saath, jaise `919876543210`):")
            return

        # ---- LOGOUT ----
        if data.startswith("logout:ask:"):
            uid = await _need_priv(cb)
            if uid is None:
                return
            slot = data.split(":", 2)[2]
            label = "owner" if slot == "owner" else f"client{slot[1:]}"
            await _show(cb, f"🚪 **{label}** ko logout karna hai? Pakka?",
                        kb([[("✅ Haan", f"logout:yes:{slot}"), ("❌ Nahi", "m:login")]]))
            return
        if data.startswith("logout:yes:"):
            uid = await _need_priv(cb)
            if uid is None:
                return
            slot = data.split(":", 2)[2]
            try:
                await _do_logout_slot(uid, slot)
                label = "owner" if slot == "owner" else f"client{slot[1:]}"
                await _show(cb, f"🚪 **{label}** logout ho gaya.", kb([[("🔙 Login menu", "m:login")], [("🏠 Menu", "m:main")]]))
            except Exception as e:
                await _show(cb, f"❌ Logout fail: {e}", BACK_MAIN)
            return

        # ---- WINGO ----
        if data == "w:add":
            uid = await _need_owner(cb)
            if uid is None:
                return
            _set_input(int(uid), "w_add", "phone", {})
            await _ask(cb, "🎰 Nayi WinGo ID\n\n📱 **Phone number** bhejo (jaise `9199xxxxxx`):")
            return
        if data.startswith("w:edit:"):
            uid = await _need_owner(cb)
            if uid is None:
                return
            n = int(data.split(":")[2])
            _set_input(int(uid), "w_edit", "phone", {"n": n})
            await _ask(cb, f"✏️ ID **#{n}** badal rahe ho.\n\n📱 Naya **phone number** bhejo:")
            return
        if data.startswith("w:delask:"):
            uid = await _need_owner(cb)
            if uid is None:
                return
            n = int(data.split(":")[2])
            await _show(cb, f"🗑️ WinGo ID **#{n}** hatani hai? Pakka?",
                        kb([[("✅ Haan", f"w:delyes:{n}"), ("❌ Nahi", "m:wingo")]]))
            return
        if data.startswith("w:delyes:"):
            uid = await _need_owner(cb)
            if uid is None:
                return
            n = int(data.split(":")[2])
            accs = bs.owner_section(uid).get("wingo_accounts", [])
            if 1 <= n <= len(accs):
                gone = accs.pop(n - 1)
                bs.save_config()
                await _show(cb, f"🗑️ ID #{n} ({bs.mask_phone(gone.get('phone', ''))}) hata di.\n🌐 Browsers → Restart chalao.",
                            kb([[("🔙 WinGo menu", "m:wingo")], [("🏠 Menu", "m:main")]]))
            else:
                await _show(cb, "❌ Ye number ab list me nahi hai.", BACK_MAIN)
            return

        # ---- URLS ----
        if data.startswith("u:edit:"):
            uid = await _need_owner(cb)
            if uid is None:
                return
            key = {"login": "login_url", "room": "wingo_room_url", "cdn": "cdn_url"}[data.split(":")[2]]
            _set_input(int(uid), "u_edit", "url", {"key": key})
            await _ask(cb, f"🔗 **{key}** ka naya link bhejo (https:// se shuru):")
            return

        # ---- EMOJI ----
        if data.startswith("e:edit:"):
            uid = await _need_priv(cb)
            if uid is None:
                return
            env = bs.EMOJI_KEYS[data.split(":")[2]]
            _set_input(int(uid), "e_edit", "eid", {"env": env})
            await _ask(cb, f"✨ **{env}** ki nayi ID bhejo (sirf number).\n(ID nikalne ke liye premium emoji bhej ke /emojiid)")
            return

        # ---- API ----
        if data == "api:set":
            uid = await _need_priv(cb)
            if uid is None:
                return
            _set_input(int(uid), "api", "aid", {})
            await _ask(cb, "🔑 **API_ID** bhejo (number, my.telegram.org se):")
            return

        # ---- HEADLESS toggle ----
        if data == "hl:toggle":
            uid = await _need_priv(cb)
            if uid is None:
                return
            cur = os.getenv("HEADLESS", "false").lower() in ("true", "1", "yes")
            bs.set_env_var("HEADLESS", "false" if cur else "true")
            text, markup = page_emapi(uid)
            await _show(cb, text + f"\n\n✅ Headless: `{os.getenv('HEADLESS')}` (effect restart ke baad)", markup)
            return

        # ---- MSGS ----
        if data == "b:add":
            uid = await _need_owner(cb)
            if uid is None:
                return
            _set_input(int(uid), "b_add", "text", {})
            await _ask(cb, "💬 Naya **bet message** bhejo.\n(`{PERIOD}` ki jagah period lagega)")
            return
        if data == "b:delask":
            uid = await _need_owner(cb)
            if uid is None:
                return
            _set_input(int(uid), "b_del", "num", {})
            await _ask(cb, "🗑️ Kaunsa **number** hatana hai? Number bhejo:")
            return
        if data == "f:add":
            uid = await _need_owner(cb)
            if uid is None:
                return
            _set_input(int(uid), "f_add", "text", {})
            await _ask(cb, "📝 Naya **feedback** bhejo.\n(`{WIN}` `{BET}` `{NUMBER}` auto-bharega)")
            return
        if data == "f:delask":
            uid = await _need_owner(cb)
            if uid is None:
                return
            _set_input(int(uid), "f_del", "num", {})
            await _ask(cb, "🗑️ Kaunsa **number** hatana hai? Number bhejo:")
            return

        # ---- OWNERS ----
        if data == "o:add":
            uid = await _need_priv(cb)
            if uid is None:
                return
            _set_input(int(uid), "o_add", "oid", {})
            await _ask(cb, "👑 Naye owner ka **Telegram numeric ID** bhejo (jaise `8428751737`):")
            return
        if data.startswith("o:delask:"):
            uid = await _need_priv(cb)
            if uid is None:
                return
            nid = data.split(":", 2)[2]
            await _show(cb, f"🗑️ Owner `{nid}` hatana hai? (uske browsers + session band honge) Pakka?",
                        kb([[("✅ Haan", f"o:delyes:{nid}"), ("❌ Nahi", "m:owners")]]))
            return
        if data.startswith("o:delyes:"):
            uid = await _need_priv(cb)
            if uid is None:
                return
            nid = data.split(":", 2)[2]
            if nid == uid:
                await _show(cb, "❌ Khud ko nahi hata sakte.", BACK_MAIN)
                return
            if nid not in bs.cfg().get("owners", {}):
                await _show(cb, "Ye owner list me nahi hai.", BACK_MAIN)
                return
            o = bs.cfg()["owners"].pop(nid)
            bs.save_config()
            await bs.stop_owner_live(nid)
            bs._rm_session_files(f"owner_{nid}")
            bs.remove_env_var(o.get("main_id_env", f"OWNER_{nid}_SESSION"))
            pool = bs._ctx["browser_pools"].pop(nid, None)
            if pool is not None:
                try:
                    await pool.stop()
                except Exception:
                    pass
            await _show(cb, f"🗑️ Owner `{nid}` hata diya.", kb([[("🔙 Owners", "m:owners")], [("🏠 Menu", "m:main")]]))
            return

        # ---- BROWSERS ----
        if data == "br:refresh":
            uid = await _need_owner(cb)
            if uid is None:
                return
            pool = bs._ctx["browser_pools"].get(uid)
            if not pool or not pool.ready_count():
                await _show(cb, "⚠️ Koi browser khula nahi hai. Neeche Restart dabao.",
                            kb([[("🌐 Restart", "br:restart")], [("🏠 Menu", "m:main")]]))
                return
            await _show(cb, f"🔄 {pool.ready_count()} browsers refresh ho rahe hain...", None)
            try:
                statuses = await pool.refresh()
                lines = ["🔄 **Refresh complete:**"]
                for idx in sorted(statuses):
                    mark = "✅" if "ready" in statuses[idx] or "khola" in statuses[idx] else "⚠️"
                    lines.append(f"{mark} Browser {idx}: {statuses[idx]}")
                await _show(cb, "\n".join(lines), kb([[("🔙 Browsers", "m:browsers")], [("🏠 Menu", "m:main")]]))
            except Exception as e:
                await _show(cb, f"❌ Refresh fail: {e}", BACK_MAIN)
            return
        if data == "br:restart":
            uid = await _need_owner(cb)
            if uid is None:
                return
            await _show(cb, "🌐 Browsers band karke naye khol raha hoon... (2-4 min lag sakta hai)", None)
            result = await _do_restart_browsers(uid)
            await _show(cb, result, kb([[("🔙 Browsers", "m:browsers")], [("🏠 Menu", "m:main")]]))
            return

        # ---- BET / DP ----
        if data in ("bet:bet", "bet:hbet"):
            uid = await _need_owner(cb)
            if uid is None:
                return
            mode = "hbet" if data == "bet:hbet" else "bet"
            do_bet = bs._ctx.get("do_bet")
            if do_bet is None:
                await _show(cb, "❌ Bet function jud nahi paya. `/bet` command use karo.", BACK_MAIN)
                return
            await cb.message.reply_text(f"🚀 **{mode}** button se shuru kiya...")
            await do_bet(mode, uid, cb.message)
            return
        if data == "bet:dp":
            uid = await _need_owner(cb)
            if uid is None:
                return
            do_dp = bs._ctx.get("do_dp")
            if do_dp is None:
                await _show(cb, "❌ DP function jud nahi paya. `/dp` command use karo.", BACK_MAIN)
                return
            await do_dp(cb.message)
            return
