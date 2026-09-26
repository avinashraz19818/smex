"""
bot_setup.py — Bot ke andar se poora setup (code/.env me haath se kuch dalne ki zaroorat nahi)

  /help              saare commands ki list
  /login <slot>      phone + OTP + 2FA se Telegram account login (session auto-save)
  /cancel            chal raha login radd karo
  /sessions          kaun-kaun se account login hain
  /logout <slot>     kisi slot ka session hatao
  /status            poori system summary

  /owners /addowner /delowner          owner (boss) accounts manage karo
  /wingo /addwingo /setwingo /delwingo WinGo phone+password manage karo
  /urls /seturl                        login/room/CDN links badlo
  /emojis /setemoji                    premium emoji ids badlo
  /setapi                              API_ID + API_HASH badlo
  /setheadless                         browser headless on/off
  /betmsgs /addbetmsg /delbetmsg       bet wale messages badlo
  /feedbacks /addfeedback /delfeedback jeetne ke baad wale messages badlo
  /restartbrowsers                     wingo/link badalne ke baad browser dobara kholo

Slot naam:
  owner              tumhara apna owner slot
  client1..client6   6 shared client slots (jaise client3)
"""

import os
import re
import json
import copy
import time
import asyncio

from pyrogram import filters
from pyrogram import Client as PyroClient
from pyrogram.types import Message
from pyrogram.errors import (
    FloodWait, SessionPasswordNeeded, PhoneCodeInvalid,
    PhoneNumberInvalid, PasswordHashInvalid, BadRequest,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
ENV_PATH = os.path.join(BASE_DIR, ".env")

CLIENT_SLOTS = [f"CLIENT_{i}_SESSION" for i in range(1, 7)]

EMOJI_KEYS = {
    "tick": "TICK_EMOJI",
    "money": "MONEY_EMOJI",
    "cash": "MONEY_EMOJI",
    "crown": "CROWN_EMOJI",
    "hundred": "CROWN_EMOJI",
    "fire": "FIRE_EMOJI",
}

URL_KEYS = {
    "login": "login_url",
    "room": "wingo_room_url",
    "wingo": "wingo_room_url",
    "cdn": "cdn_url",
}

# user_id -> {slot_kind, label, env, owner_id, cidx, step, phone, tmp, code_hash, ts}
pending_logins = {}

# user_id -> {action, step, data, ts}  (buttons wale flows ke text-jawab, bot_menu.py se)
pending_input = {}
input_processor = None  # bot_menu.register() isko set karta hai

_ctx = {}


# ---------------------------------------------------------------- helpers

def cfg():
    return _ctx["config"]


def get_api():
    try:
        api_id = int(os.getenv("API_ID", "1234567"))
    except ValueError:
        api_id = 1234567
    return api_id, os.getenv("API_HASH", "abcdef")


def is_owner(uid) -> bool:
    return str(uid) in cfg().get("owners", {})


def is_privileged(uid) -> bool:
    if is_owner(uid):
        return True
    superadmin = os.getenv("SUPERADMIN_ID", "").strip()
    return bool(superadmin) and str(uid) == superadmin


def need_privileged(message: Message):
    uid = message.from_user.id if message.from_user else 0
    if not is_privileged(uid):
        return None
    return str(uid)


def save_config():
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg(), f, indent=4, ensure_ascii=False)


def set_env_var(key: str, value: str):
    """`.env` file me KEY=value likho (purani value hata ke) + os.environ me turant lao."""
    value = str(value)
    lines = []
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, "r", encoding="utf-8", newline="") as f:
            for ln in f.read().splitlines():
                if "=" in ln and ln.split("=", 1)[0].strip() == key:
                    continue  # purani line hatao
                lines.append(ln)
    lines.append(f"{key}={value}")
    with open(ENV_PATH, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    os.environ[key] = value


def remove_env_var(key: str):
    lines = []
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, "r", encoding="utf-8", newline="") as f:
            for ln in f.read().splitlines():
                if "=" in ln and ln.split("=", 1)[0].strip() == key:
                    continue
                lines.append(ln)
        with open(ENV_PATH, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(lines) + "\n")
    os.environ.pop(key, None)


def mask_phone(p: str) -> str:
    d = re.sub(r"\D", "", p or "")
    if len(d) <= 4:
        return "****"
    return d[:2] + "****" + d[-2:]


def _rm_session_files(name: str):
    for ext in (".session", ".session-journal"):
        try:
            p = os.path.join(BASE_DIR, name + ext)
            if os.path.exists(p):
                os.remove(p)
        except Exception:
            pass


def parse_slot(arg: str, uid: str):
    """Slot naam samjho. Returns (info_dict, None) ya (None, error_msg)."""
    a = (arg or "").strip().lower().replace(" ", "").replace("_", "")
    if a in ("owner", "o", "main", "self", "my", "boss"):
        if uid not in cfg().get("owners", {}):
            return None, "Tum owner list me nahi ho. Pehle kisi owner se /addowner karwao."
        env = cfg()["owners"][uid].get("main_id_env", f"OWNER_{uid}_SESSION")
        return {"kind": "owner", "label": "owner", "env": env, "owner_id": uid}, None
    m = re.fullmatch(r"(?:client|c)(\d)", a)
    if m:
        n = int(m.group(1))
        if 1 <= n <= 6:
            return {"kind": "client", "label": f"client{n}",
                    "env": CLIENT_SLOTS[n - 1], "cidx": n - 1}, None
    return None, "Slot samajh nahi aaya. Likho: /login owner  ya  /login client3"


def rebuild_client_list():
    lst = _ctx["client_sessions"]
    mp = _ctx["client_slot_map"]
    lst.clear()
    for env in CLIENT_SLOTS:
        if env in mp:
            lst.append(mp[env])


async def start_owner_live(owner_id: str):
    mp = _ctx["owner_sessions"]
    env = cfg()["owners"][owner_id].get("main_id_env", f"OWNER_{owner_id}_SESSION")
    old = mp.pop(owner_id, None)
    if old is not None:
        try:
            await old.stop()
        except Exception:
            pass
    _rm_session_files(f"owner_{owner_id}")
    api_id, api_hash = get_api()
    c = PyroClient(f"owner_{owner_id}", api_id=api_id, api_hash=api_hash,
                   session_string=os.getenv(env, "").strip(), sleep_threshold=60)
    await c.start()
    c.my_user = await c.get_me()
    mp[owner_id] = c
    try:
        async for _ in c.get_dialogs(limit=100):
            pass
    except Exception:
        pass
    return c


async def start_client_live(cidx: int):
    mp = _ctx["client_slot_map"]
    env = CLIENT_SLOTS[cidx]
    old = mp.pop(env, None)
    if old is not None:
        try:
            await old.stop()
        except Exception:
            pass
    _rm_session_files(f"client_{cidx + 1}")
    api_id, api_hash = get_api()
    c = PyroClient(f"client_{cidx + 1}", api_id=api_id, api_hash=api_hash,
                   session_string=os.getenv(env, "").strip(), sleep_threshold=60)
    await c.start()
    c.my_user = await c.get_me()
    mp[env] = c
    rebuild_client_list()
    try:
        async for _ in c.get_dialogs(limit=50):
            pass
    except Exception:
        pass
    return c


async def stop_owner_live(owner_id: str):
    mp = _ctx["owner_sessions"]
    old = mp.pop(owner_id, None)
    if old is not None:
        try:
            await old.stop()
        except Exception:
            pass


async def stop_client_live(cidx: int):
    mp = _ctx["client_slot_map"]
    old = mp.pop(CLIENT_SLOTS[cidx], None)
    if old is not None:
        try:
            await old.stop()
        except Exception:
            pass
    rebuild_client_list()


async def revalidate_emojis_quiet():
    try:
        _ctx["valid_emoji_ids"].clear()
        await _ctx["revalidate"]()
    except Exception as e:
        print(f"⚠️ Emoji re-check fail: {e}")


async def cleanup_login(uid: int):
    st = pending_logins.pop(uid, None)
    if st and st.get("tmp"):
        try:
            await st["tmp"].disconnect()
        except Exception:
            pass


async def try_delete(message: Message):
    try:
        await message.delete()
    except Exception:
        pass


def owner_section(uid: str):
    return cfg()["owners"].get(uid)


# ---------------------------------------------------------------- register

def register(bot, ctx: dict):
    _ctx.update(ctx)

    # ---------------------------------------------------------- /help
    @bot.on_message(filters.command("help", prefixes="/"))
    async def _help(_: PyroClient, m: Message):
        uid = need_privileged(m)
        if uid is None:
            await m.reply_text("❌ Unauthorized. Ye bot sirf owners ke liye hai.")
            return
        await m.reply_text(
            "🤖 **COMMANDS** (sab bot se hi, code chhune ki zaroorat nahi)\n"
            "🎛️ Asaan tarika: **/start** bhejo — sab kuch BUTTONS me milega!\n\n"
            "📱 **LOGIN (bina session string)**\n"
            "`/login owner` — apna account login karo\n"
            "`/login client3` — client slot 1..6 login karo\n"
            "`/cancel` — chal raha login radd karo\n"
            "`/sessions` — kaun login hai, kaun nahi\n"
            "`/logout client3` — session hatao\n\n"
            "👑 **OWNERS**\n"
            "`/owners` — list\n"
            "`/addowner 123456789 note` — naya owner\n"
            "`/delowner 123456789` — owner hatao\n\n"
            "🎰 **WINGO ACCOUNTS**\n"
            "`/wingo` — list\n"
            "`/addwingo 9199xxxxxx mypass` — naya add\n"
            "`/setwingo 2 9199xxxxxx newpass` — number 2 badlo\n"
            "`/delwingo 2` — number 2 hatao\n\n"
            "🔗 **LINKS**\n"
            "`/urls` — teeno links dekho\n"
            "`/seturl login https://...` — login link\n"
            "`/seturl room https://...` — wingo room link\n"
            "`/seturl cdn https://...` — result CDN link\n\n"
            "✨ **EMOJI / API**\n"
            "`/emojis` — lagi hui emoji ids dekho\n"
            "`/setemoji tick 54630...` — tick/money/crown/fire\n"
            "`/setapi 1234567 abcdef...` — API_ID + API_HASH\n"
            "`/setheadless on` — browser on/off (on/off)\n\n"
            "💬 **MESSAGES**\n"
            "`/betmsgs` — bet wale messages dekho\n"
            "`/addbetmsg GREEN 5 -- NUMBER {PERIOD}` — naya jodo\n"
            "`/delbetmsg 3` — number 3 hatao\n"
            "`/feedbacks` — jeet wale messages dekho\n"
            "`/addfeedback Maza aagya {WIN} jeet gya!` — naya jodo\n"
            "`/delfeedback 3` — number 3 hatao\n\n"
            "🌐 **BROWSERS**\n"
            "`/restartbrowsers` — wingo/link badalne ke baad dobara kholo\n"
            "`/status` — poori summary\n\n"
            "🎯 **BET (pehle wale)**\n"
            "`/bet` `/hbet` `/refresh` `/browsers` `/dp` `/emojiid`\n\n"
            "⚠️ Wingo account ya link badalne ke baad `/restartbrowsers` "
            "zaroor chalao, tabhi naye browser me lagega."
        )

    # ---------------------------------------------------------- /status
    @bot.on_message(filters.command("status", prefixes="/"))
    async def _status(_: PyroClient, m: Message):
        uid = need_privileged(m)
        if uid is None:
            await m.reply_text("❌ Unauthorized.")
            return
        owners = cfg().get("owners", {})
        o_login = sum(1 for o in owners if o in _ctx["owner_sessions"])
        c_login = len(_ctx["client_slot_map"])
        api_ok = bool(os.getenv("API_ID", "").strip()) and bool(os.getenv("API_HASH", "").strip())
        emo = sorted(_ctx["valid_emoji_ids"])
        lines = [
            "📊 **STATUS**",
            f"🤖 Bot: 🟢 ON",
            f"👑 Owners login: {o_login}/{len(owners)}",
            f"📱 Clients login: {c_login}/6",
            f"🔑 API: {'🟢 set' if api_ok else '🔴 /setapi se dalo'}",
            f"✨ Emoji active: {len(emo)}" + (f" ({', '.join(emo)})" if emo else " (normal emoji chalenge)"),
            f"🌐 Headless: {os.getenv('HEADLESS', 'false')}",
        ]
        if uid in owners:
            pool = _ctx["browser_pools"].get(uid)
            n_acc = len(owners[uid].get("wingo_accounts", []))
            if pool:
                lines.append(f"🎰 Tumhare browsers: {pool.healthy_count()}/{len(pool.workers)} ready ({n_acc} wingo IDs)")
            else:
                lines.append(f"🎰 Tumhare browsers: band hain ({n_acc} wingo IDs set)")
        await m.reply_text("\n".join(lines))

    # ---------------------------------------------------------- LOGIN
    @bot.on_message(filters.command("login", prefixes="/"))
    async def _login(_: PyroClient, m: Message):
        uid = need_privileged(m)
        if uid is None:
            await m.reply_text("❌ Unauthorized.")
            return
        if len(m.command) < 2:
            await m.reply_text("Likho: `/login owner`  ya  `/login client3`  (1 se 6)")
            return
        info, err = parse_slot(m.command[1], uid)
        if err:
            await m.reply_text(f"❌ {err}")
            return
        me_uid = m.from_user.id
        if me_uid in pending_logins:
            await m.reply_text("⚠️ Ek login pehle se chal raha hai. `/cancel` karke dobara karo.")
            return
        pending_logins[me_uid] = {
            "kind": info["kind"], "label": info["label"], "env": info["env"],
            "owner_id": info.get("owner_id"), "cidx": info.get("cidx"),
            "step": "phone", "phone": "", "tmp": None, "code_hash": "",
            "ts": time.time(),
        }
        warn = ""
        try:
            if m.chat and str(m.chat.type) != "ChatType.PRIVATE":
                warn = "\n\n⚠️ Group me OTP dikhega — ho sake to bot ke **private chat** me /login karo."
        except Exception:
            pass
        await m.reply_text(
            f"📱 **{info['label']}** slot me login kar rahe ho.\n\n"
            f"Apna **mobile number** bhejo (country code ke saath, jaise `919876543210`):"
            + warn
        )

    @bot.on_message(filters.command("cancel", prefixes="/"))
    async def _cancel(_: PyroClient, m: Message):
        me_uid = m.from_user.id if m.from_user else 0
        had = False
        if me_uid in pending_logins:
            await cleanup_login(me_uid)
            had = True
        if me_uid in pending_input:
            pending_input.pop(me_uid, None)
            had = True
        if had:
            await m.reply_text("🚫 Radd kar diya.")
        else:
            await m.reply_text("Koi kaam chal hi nahi raha.")

    @bot.on_message(filters.text, group=5)
    async def _login_text(_: PyroClient, m: Message):
        if not m.text or m.text.startswith("/"):
            return
        me_uid = m.from_user.id if m.from_user else 0
        st = pending_logins.get(me_uid)
        if st:
            if time.time() - st.get("ts", 0) > 600:
                await cleanup_login(me_uid)
                await m.reply_text("⏰ Time khatam ho gaya. `/login` dobara karo.")
                return
            step = st["step"]
            if step == "phone":
                await _login_got_phone(m, me_uid, st)
            elif step == "otp":
                await _login_got_otp(m, me_uid, st)
            elif step == "password":
                await _login_got_password(m, me_uid, st)
            return
        # buttons wale flows ka jawab (bot_menu.py)
        pi = pending_input.get(me_uid)
        if not pi:
            return
        if time.time() - pi.get("ts", 0) > 600:
            pending_input.pop(me_uid, None)
            await m.reply_text("⏰ Time khatam ho gaya. `/start` se dobara karo.")
            return
        if input_processor is not None:
            await input_processor(m, me_uid, pi)
        else:
            pending_input.pop(me_uid, None)

    async def _login_got_phone(m: Message, me_uid: int, st: dict):
        phone = re.sub(r"[\s\-()]", "", m.text.strip())
        digits = re.sub(r"\D", "", phone)
        if len(digits) < 10 or len(digits) > 15:
            await m.reply_text("❌ Number sahi nahi lag raha. Country code ke saath bhejo, jaise `919876543210`")
            return
        phone = "+" + digits
        api_id, api_hash = get_api()
        tmp = PyroClient(f"login_{me_uid}", api_id=api_id, api_hash=api_hash, in_memory=True)
        try:
            await tmp.connect()
        except Exception as e:
            await m.reply_text(f"❌ Telegram se connect nahi hua: {e}\n(API_ID/API_HASH `/setapi` se check karo)")
            return
        try:
            sent = await tmp.send_code(phone)
        except FloodWait as e:
            try:
                await tmp.disconnect()
            except Exception:
                pass
            await cleanup_login(me_uid)
            await m.reply_text(f"⏳ Telegram ne rok lagayi hai. {getattr(e, 'value', 60)} second baad `/login` dobara karo.")
            return
        except PhoneNumberInvalid:
            try:
                await tmp.disconnect()
            except Exception:
                pass
            await m.reply_text("❌ Ye number Telegram pe registered nahi lag raha. Sahi number bhejo.")
            return
        except Exception as e:
            try:
                await tmp.disconnect()
            except Exception:
                pass
            await m.reply_text(f"❌ OTP bhejne me error: {e}")
            return
        st["tmp"] = tmp
        st["phone"] = phone
        st["code_hash"] = sent.phone_code_hash
        st["step"] = "otp"
        st["ts"] = time.time()
        await m.reply_text(
            f"📩 OTP **{phone}** par bhej diya hai.\n"
            f"Telegram app me aaya **login code** yahin bhejo (`1 2 3 4 5` aise space me bhi chalega).\n\n"
            f"`/cancel` — radd karne ke liye"
        )

    async def _login_got_otp(m: Message, me_uid: int, st: dict):
        otp = re.sub(r"\D", "", m.text.strip())
        if len(otp) < 4:
            await m.reply_text("❌ OTP ankdon me bhejo (jaise `48291`).")
            return
        try:
            await st["tmp"].sign_in(st["phone"], st["code_hash"], otp)
        except SessionPasswordNeeded:
            st["step"] = "password"
            st["ts"] = time.time()
            await try_delete(m)
            await m.reply_text("🔐 Is account pe **2-step password** laga hai, wo bhejo:")
            return
        except PhoneCodeInvalid:
            await m.reply_text("❌ OTP galat hai. Sahi OTP bhejo ya `/cancel` karo.")
            return
        except FloodWait as e:
            await m.reply_text(f"⏳ Thoda ruko ({getattr(e, 'value', 60)}s), phir OTP dobara bhejo.")
            return
        except Exception as e:
            if "EXPIRED" in str(e).upper():
                await cleanup_login(me_uid)
                await m.reply_text("⌛ OTP expire ho gaya. `/login` dobara karo.")
                return
            await cleanup_login(me_uid)
            await m.reply_text(f"❌ Login fail: {e}")
            return
        await try_delete(m)
        await _finish_login(m, me_uid, st)

    async def _login_got_password(m: Message, me_uid: int, st: dict):
        pwd = m.text.strip()
        try:
            await st["tmp"].check_password(pwd)
        except PasswordHashInvalid:
            await m.reply_text("❌ 2-step password galat hai. Sahi password bhejo ya `/cancel` karo.")
            return
        except FloodWait as e:
            await m.reply_text(f"⏳ Thoda ruko ({getattr(e, 'value', 60)}s), phir password dobara bhejo.")
            return
        except Exception as e:
            await cleanup_login(me_uid)
            await m.reply_text(f"❌ Login fail: {e}")
            return
        await try_delete(m)
        await _finish_login(m, me_uid, st)

    async def _finish_login(m: Message, me_uid: int, st: dict):
        wait = await m.reply_text("⏳ Login ho gaya! Session save karke account start kar raha hoon...")
        try:
            session_str = await st["tmp"].export_session_string()
        except Exception as e:
            await cleanup_login(me_uid)
            await wait.edit_text(f"❌ Session banane me error: {e}")
            return
        await cleanup_login(me_uid)
        set_env_var(st["env"], session_str)
        try:
            if st["kind"] == "owner":
                c = await start_owner_live(st["owner_id"])
            else:
                c = await start_client_live(st["cidx"])
        except Exception as e:
            await wait.edit_text(
                f"⚠️ Session **save** ho gaya ({st['env']}) par account start nahi hua: {e}\n"
                f"Bot restart karke dekho."
            )
            return
        if st["kind"] == "owner":
            await revalidate_emojis_quiet()
        who = f"{c.my_user.first_name} (id `{c.my_user.id}`)"
        await wait.edit_text(
            f"✅ **{st['label']}** login ho gaya!\n"
            f"👤 {who}\n"
            f"💾 Session `{st['env']}` me save — ab dobara dalne ki zaroorat nahi.\n"
            f"{'✨ Emoji dobara check kar liye hain.' if st['kind'] == 'owner' else ''}"
        )

    # ---------------------------------------------------------- /sessions /logout
    @bot.on_message(filters.command("sessions", prefixes="/"))
    async def _sessions(_: PyroClient, m: Message):
        uid = need_privileged(m)
        if uid is None:
            await m.reply_text("❌ Unauthorized.")
            return
        lines = ["🔑 **LOGIN STATUS**\n"]
        lines.append("👑 **Owner slots:**")
        for oid, o in cfg().get("owners", {}).items():
            c = _ctx["owner_sessions"].get(oid)
            if c is not None:
                lines.append(f"• `{oid}` — 🟢 {c.my_user.first_name} ({c.my_user.id})")
            else:
                lines.append(f"• `{oid}` — 🔴 login nahi (`/login owner` us account se)")
        lines.append("\n📱 **Client slots:**")
        for i, env in enumerate(CLIENT_SLOTS):
            c = _ctx["client_slot_map"].get(env)
            if c is not None:
                lines.append(f"• client{i+1} — 🟢 {c.my_user.first_name} ({c.my_user.id})")
            else:
                lines.append(f"• client{i+1} — 🔴 khaali (`/login client{i+1}`)")
        await m.reply_text("\n".join(lines))

    @bot.on_message(filters.command("logout", prefixes="/"))
    async def _logout(_: PyroClient, m: Message):
        uid = need_privileged(m)
        if uid is None:
            await m.reply_text("❌ Unauthorized.")
            return
        if len(m.command) < 2:
            await m.reply_text("Likho: `/logout owner`  ya  `/logout client3`")
            return
        info, err = parse_slot(m.command[1], uid)
        if err:
            await m.reply_text(f"❌ {err}")
            return
        if info["kind"] == "owner":
            await stop_owner_live(info["owner_id"])
            _rm_session_files(f"owner_{info['owner_id']}")
        else:
            await stop_client_live(info["cidx"])
            _rm_session_files(f"client_{info['cidx'] + 1}")
        remove_env_var(info["env"])
        await m.reply_text(
            f"🚪 **{info['label']}** logout ho gaya, session hata diya.\n"
            f"Dobara login: `/login {info['label']}`"
        )

    # ---------------------------------------------------------- OWNERS
    @bot.on_message(filters.command("owners", prefixes="/"))
    async def _owners(_: PyroClient, m: Message):
        uid = need_privileged(m)
        if uid is None:
            await m.reply_text("❌ Unauthorized.")
            return
        lines = ["👑 **OWNERS**"]
        for oid, o in cfg().get("owners", {}).items():
            on = "🟢 login" if oid in _ctx["owner_sessions"] else "🔴 login nahi"
            nw = len(o.get("wingo_accounts", []))
            note = o.get("note", "")
            lines.append(f"• `{oid}` — {on} | 🎰 {nw} wingo IDs {('— ' + note) if note else ''}")
        await m.reply_text("\n".join(lines) or "Koi owner nahi.")

    @bot.on_message(filters.command("addowner", prefixes="/"))
    async def _addowner(_: PyroClient, m: Message):
        uid = need_privileged(m)
        if uid is None:
            await m.reply_text("❌ Unauthorized.")
            return
        if len(m.command) < 2 or not m.command[1].isdigit():
            await m.reply_text("Likho: `/addowner 123456789 اختیاري note` (Telegram numeric ID)")
            return
        nid = m.command[1]
        if nid in cfg().get("owners", {}):
            await m.reply_text("Ye ID pehle se owner hai.")
            return
        template = next(iter(cfg().get("owners", {}).values()), {})
        new = {
            "note": " ".join(m.command[2:]) if len(m.command) > 2 else "bot se add hua",
            "main_id_env": f"OWNER_{nid}_SESSION",
            "urls": copy.deepcopy(template.get("urls", {
                "cdn_url": "", "wingo_room_url": "", "login_url": ""})),
            "bet_messages": copy.deepcopy(template.get("bet_messages", [])),
            "feedbacks": copy.deepcopy(template.get("feedbacks", ["Maza aagya {WIN} jeet gya!"])),
            "conversations": copy.deepcopy(template.get("conversations", [])),
            "confuse_chat": copy.deepcopy(template.get("confuse_chat", {})),
            "wingo_accounts": [],
        }
        cfg()["owners"][nid] = new
        save_config()
        await m.reply_text(
            f"✅ Owner `{nid}` add ho gaya.\n\n"
            f"Us account se ye steps karwao:\n"
            f"1️⃣ Bot ko `/login owner` bhejo (OTP se login)\n"
            f"2️⃣ `/addwingo phone password` se WinGo IDs dalo\n"
            f"3️⃣ `/restartbrowsers` chalao"
        )

    @bot.on_message(filters.command("delowner", prefixes="/"))
    async def _delowner(_: PyroClient, m: Message):
        uid = need_privileged(m)
        if uid is None:
            await m.reply_text("❌ Unauthorized.")
            return
        if len(m.command) < 2:
            await m.reply_text("Likho: `/delowner 123456789`")
            return
        nid = m.command[1]
        if nid not in cfg().get("owners", {}):
            await m.reply_text("Ye ID owner list me nahi hai.")
            return
        if nid == uid:
            await m.reply_text("❌ Khud ko nahi hata sakte. Kisi doosre owner se karwao.")
            return
        o = cfg()["owners"].pop(nid)
        save_config()
        await stop_owner_live(nid)
        _rm_session_files(f"owner_{nid}")
        remove_env_var(o.get("main_id_env", f"OWNER_{nid}_SESSION"))
        pool = _ctx["browser_pools"].pop(nid, None)
        if pool is not None:
            try:
                await pool.stop()
            except Exception:
                pass
        await m.reply_text(f"🗑️ Owner `{nid}` hata diya (session + browsers band).")

    # ---------------------------------------------------------- WINGO
    def _my_wingo(uid: str):
        o = owner_section(uid)
        if o is None:
            return None
        return o.setdefault("wingo_accounts", [])

    @bot.on_message(filters.command("wingo", prefixes="/"))
    async def _wingo(_: PyroClient, m: Message):
        uid = need_privileged(m)
        if uid is None or owner_section(uid) is None:
            await m.reply_text("❌ Ye command sirf owners ke liye hai.")
            return
        accs = _my_wingo(uid)
        if not accs:
            await m.reply_text("🎰 Koi WinGo ID nahi hai. Jodo: `/addwingo 9199xxxxxx mypass`")
            return
        lines = ["🎰 **TUMHARI WINGO IDs**"]
        for i, a in enumerate(accs, 1):
            ph = mask_phone(a.get("phone", ""))
            pw = a.get("password", "")
            lines.append(f"{i}. 📱 `{ph}`  🔑 {'•' * min(len(pw), 12)} ({len(pw)} char)")
        lines.append("\nBadlo: `/setwingo 2 phone pass` | Hatao: `/delwingo 2`")
        await m.reply_text("\n".join(lines))

    @bot.on_message(filters.command("addwingo", prefixes="/"))
    async def _addwingo(_: PyroClient, m: Message):
        uid = need_privileged(m)
        if uid is None or owner_section(uid) is None:
            await m.reply_text("❌ Ye command sirf owners ke liye hai.")
            return
        if len(m.command) < 3:
            await m.reply_text("Likho: `/addwingo 9199xxxxxx mypass`")
            return
        accs = _my_wingo(uid)
        accs.append({"phone": m.command[1], "password": m.command[2]})
        save_config()
        await m.reply_text(
            f"✅ WinGo ID **#{len(accs)}** save ho gayi ({mask_phone(m.command[1])}).\n"
            f"🌐 Browser me lagane ke liye `/restartbrowsers` chalao."
        )
        await try_delete(m)

    @bot.on_message(filters.command(["setwingo", "editwingo"], prefixes="/"))
    async def _setwingo(_: PyroClient, m: Message):
        uid = need_privileged(m)
        if uid is None or owner_section(uid) is None:
            await m.reply_text("❌ Ye command sirf owners ke liye hai.")
            return
        if len(m.command) < 4 or not m.command[1].isdigit():
            await m.reply_text("Likho: `/setwingo 2 9199xxxxxx newpass`")
            return
        accs = _my_wingo(uid)
        n = int(m.command[1])
        if n < 1 or n > len(accs):
            await m.reply_text(f"❌ Number 1 se {len(accs)} tak ho sakta hai. `/wingo` se list dekho.")
            return
        accs[n - 1] = {"phone": m.command[2], "password": m.command[3]}
        save_config()
        await m.reply_text(f"✅ WinGo ID **#{n}** badal di. `/restartbrowsers` chalao.")
        await try_delete(m)

    @bot.on_message(filters.command("delwingo", prefixes="/"))
    async def _delwingo(_: PyroClient, m: Message):
        uid = need_privileged(m)
        if uid is None or owner_section(uid) is None:
            await m.reply_text("❌ Ye command sirf owners ke liye hai.")
            return
        if len(m.command) < 2 or not m.command[1].isdigit():
            await m.reply_text("Likho: `/delwingo 2`")
            return
        accs = _my_wingo(uid)
        n = int(m.command[1])
        if n < 1 or n > len(accs):
            await m.reply_text(f"❌ Number 1 se {len(accs)} tak ho sakta hai.")
            return
        gone = accs.pop(n - 1)
        save_config()
        await m.reply_text(f"🗑️ ID #{n} ({mask_phone(gone.get('phone', ''))}) hata di. `/restartbrowsers` chalao.")

    # ---------------------------------------------------------- URLS
    @bot.on_message(filters.command("urls", prefixes="/"))
    async def _urls(_: PyroClient, m: Message):
        uid = need_privileged(m)
        if uid is None or owner_section(uid) is None:
            await m.reply_text("❌ Ye command sirf owners ke liye hai.")
            return
        u = owner_section(uid).get("urls", {})
        await m.reply_text(
            "🔗 **TUMHARE LINKS**\n\n"
            f"login: `{u.get('login_url', '')}`\n"
            f"room: `{u.get('wingo_room_url', '')}`\n"
            f"cdn: `{u.get('cdn_url', '')}`\n\n"
            "Badlo: `/seturl room https://...`"
        )

    @bot.on_message(filters.command("seturl", prefixes="/"))
    async def _seturl(_: PyroClient, m: Message):
        uid = need_privileged(m)
        if uid is None or owner_section(uid) is None:
            await m.reply_text("❌ Ye command sirf owners ke liye hai.")
            return
        if len(m.command) < 3 or m.command[1].lower() not in URL_KEYS:
            await m.reply_text("Likho: `/seturl login|room|cdn https://...`")
            return
        url = m.command[2].strip()
        if not url.startswith("http"):
            await m.reply_text("❌ Link `http` se shuru hona chahiye.")
            return
        owner_section(uid).setdefault("urls", {})[URL_KEYS[m.command[1].lower()]] = url
        save_config()
        await m.reply_text(f"✅ Link save ho gaya. `/restartbrowsers` chalao taaki naye browser me lage.")

    # ---------------------------------------------------------- EMOJI / API / HEADLESS
    @bot.on_message(filters.command("emojis", prefixes="/"))
    async def _emojis(_: PyroClient, m: Message):
        uid = need_privileged(m)
        if uid is None:
            await m.reply_text("❌ Unauthorized.")
            return
        active = _ctx["valid_emoji_ids"]
        lines = ["✨ **EMOJI IDS**"]
        for nick in ("tick", "money", "crown", "fire"):
            env = EMOJI_KEYS[nick]
            val = os.getenv(env, "").strip()
            mark = "🟢" if val and val in active else ("🟡 set par active nahi" if val else "⚪ khaali")
            lines.append(f"{nick}: `{val or '-'}`  {mark}")
        lines.append("\nID nikalo: premium emoji bhej ke `/emojiid`\nSet karo: `/setemoji tick 54630...`")
        await m.reply_text("\n".join(lines))

    @bot.on_message(filters.command("setemoji", prefixes="/"))
    async def _setemoji(_: PyroClient, m: Message):
        uid = need_privileged(m)
        if uid is None:
            await m.reply_text("❌ Unauthorized.")
            return
        if len(m.command) < 3 or m.command[1].lower() not in EMOJI_KEYS:
            await m.reply_text("Likho: `/setemoji tick|money|crown|fire 54630...`")
            return
        if not m.command[2].isdigit():
            await m.reply_text("❌ ID sirf ankdon me hoti hai (jaise `5463065366782386266`).")
            return
        set_env_var(EMOJI_KEYS[m.command[1].lower()], m.command[2])
        await revalidate_emojis_quiet()
        active = _ctx["valid_emoji_ids"]
        ok = m.command[2] in active
        await m.reply_text(
            f"{'✅' if ok else '🟡'} `{EMOJI_KEYS[m.command[1].lower()]}` = `{m.command[2]}` save ho gaya.\n"
            + ("🟢 Telegram ne accept kar liya — premium emoji chalega."
               if ok else "⚠️ Abhi active nahi hua — owner ID pe Premium hai? ID sahi hai? (normal emoji chalega)")
        )

    @bot.on_message(filters.command("setapi", prefixes="/"))
    async def _setapi(_: PyroClient, m: Message):
        uid = need_privileged(m)
        if uid is None:
            await m.reply_text("❌ Unauthorized.")
            return
        if len(m.command) < 3 or not m.command[1].isdigit():
            await m.reply_text("Likho: `/setapi 1234567 abcdef1234...` (my.telegram.org se milta hai)")
            return
        set_env_var("API_ID", m.command[1])
        set_env_var("API_HASH", m.command[2])
        await m.reply_text(
            "✅ API_ID + API_HASH save ho gaye.\n"
            "ℹ️ Naye `/login` isi se honge. Bot ke liye poora effect **restart** ke baad."
        )
        await try_delete(m)

    @bot.on_message(filters.command("setheadless", prefixes="/"))
    async def _setheadless(_: PyroClient, m: Message):
        uid = need_privileged(m)
        if uid is None:
            await m.reply_text("❌ Unauthorized.")
            return
        if len(m.command) < 2 or m.command[1].lower() not in ("on", "off", "true", "false"):
            await m.reply_text(f"Abhi: `{os.getenv('HEADLESS', 'false')}`\nLikho: `/setheadless on` ya `/setheadless off`")
            return
        val = "true" if m.command[1].lower() in ("on", "true") else "false"
        set_env_var("HEADLESS", val)
        await m.reply_text(f"✅ HEADLESS = `{val}` save. Effect **restart** ke baad.")

    # ---------------------------------------------------------- MESSAGES
    @bot.on_message(filters.command("betmsgs", prefixes="/"))
    async def _betmsgs(_: PyroClient, m: Message):
        uid = need_privileged(m)
        if uid is None or owner_section(uid) is None:
            await m.reply_text("❌ Ye command sirf owners ke liye hai.")
            return
        msgs = owner_section(uid).get("bet_messages", [])
        if not msgs:
            await m.reply_text("Koi bet message nahi. Jodo: `/addbetmsg tumhara message {PERIOD}`")
            return
        lines = ["💬 **BET MESSAGES** (yehi clients ko jayenge)"]
        for i, t in enumerate(msgs, 1):
            lines.append(f"\n**{i}.** {t}")
        txt = "\n".join(lines)
        await m.reply_text(txt[:3800] + ("\n\n... (bahut lambe hain, baaki config me)" if len(txt) > 3800 else ""))

    @bot.on_message(filters.command("addbetmsg", prefixes="/"))
    async def _addbetmsg(_: PyroClient, m: Message):
        uid = need_privileged(m)
        if uid is None or owner_section(uid) is None:
            await m.reply_text("❌ Ye command sirf owners ke liye hai.")
            return
        parts = (m.text or "").split(None, 1)
        if len(parts) < 2 or not parts[1].strip():
            await m.reply_text("Likho: `/addbetmsg GREEN 5 -- NUMBER {PERIOD}`\n(`{PERIOD}` ki jagah period number lagega)")
            return
        owner_section(uid).setdefault("bet_messages", []).append(parts[1].strip())
        save_config()
        await m.reply_text("✅ Bet message jud gaya. Turant effect — agle /bet se chalega.")

    @bot.on_message(filters.command("delbetmsg", prefixes="/"))
    async def _delbetmsg(_: PyroClient, m: Message):
        uid = need_privileged(m)
        if uid is None or owner_section(uid) is None:
            await m.reply_text("❌ Ye command sirf owners ke liye hai.")
            return
        msgs = owner_section(uid).get("bet_messages", [])
        if len(m.command) < 2 or not m.command[1].isdigit():
            await m.reply_text("Likho: `/delbetmsg 3` (`/betmsgs` se number dekho)")
            return
        n = int(m.command[1])
        if n < 1 or n > len(msgs):
            await m.reply_text(f"❌ Number 1 se {len(msgs)} tak ho sakta hai.")
            return
        msgs.pop(n - 1)
        save_config()
        await m.reply_text(f"🗑️ Bet message #{n} hata diya.")

    @bot.on_message(filters.command("feedbacks", prefixes="/"))
    async def _feedbacks(_: PyroClient, m: Message):
        uid = need_privileged(m)
        if uid is None or owner_section(uid) is None:
            await m.reply_text("❌ Ye command sirf owners ke liye hai.")
            return
        msgs = owner_section(uid).get("feedbacks", [])
        if not msgs:
            await m.reply_text("Koi feedback nahi. Jodo: `/addfeedback Maza aagya {WIN} jeet gya!`")
            return
        lines = ["📝 **FEEDBACKS** (`{WIN}` `{BET}` `{NUMBER}` auto-bharega)"]
        for i, t in enumerate(msgs, 1):
            lines.append(f"{i}. {t}")
        txt = "\n".join(lines)
        await m.reply_text(txt[:3800] + ("\n..." if len(txt) > 3800 else ""))

    @bot.on_message(filters.command("addfeedback", prefixes="/"))
    async def _addfeedback(_: PyroClient, m: Message):
        uid = need_privileged(m)
        if uid is None or owner_section(uid) is None:
            await m.reply_text("❌ Ye command sirf owners ke liye hai.")
            return
        parts = (m.text or "").split(None, 1)
        if len(parts) < 2 or not parts[1].strip():
            await m.reply_text("Likho: `/addfeedback Maza aagya {WIN} jeet gya!`")
            return
        owner_section(uid).setdefault("feedbacks", []).append(parts[1].strip())
        save_config()
        await m.reply_text("✅ Feedback jud gaya. Turant effect.")

    @bot.on_message(filters.command("delfeedback", prefixes="/"))
    async def _delfeedback(_: PyroClient, m: Message):
        uid = need_privileged(m)
        if uid is None or owner_section(uid) is None:
            await m.reply_text("❌ Ye command sirf owners ke liye hai.")
            return
        msgs = owner_section(uid).get("feedbacks", [])
        if len(m.command) < 2 or not m.command[1].isdigit():
            await m.reply_text("Likho: `/delfeedback 3` (`/feedbacks` se number dekho)")
            return
        n = int(m.command[1])
        if n < 1 or n > len(msgs):
            await m.reply_text(f"❌ Number 1 se {len(msgs)} tak ho sakta hai.")
            return
        msgs.pop(n - 1)
        save_config()
        await m.reply_text(f"🗑️ Feedback #{n} hata diya.")

    # ---------------------------------------------------------- /restartbrowsers
    @bot.on_message(filters.command("restartbrowsers", prefixes="/"))
    async def _restartbrowsers(_: PyroClient, m: Message):
        uid = need_privileged(m)
        if uid is None or owner_section(uid) is None:
            await m.reply_text("❌ Ye command sirf owners ke liye hai.")
            return
        accs = owner_section(uid).get("wingo_accounts", [])
        if not accs:
            await m.reply_text("❌ Pehle `/addwingo phone password` se WinGo IDs dalo.")
            return
        status = await m.reply_text(f"🌐 {len(accs)} browsers band karke naye sir se khol raha hoon... (2-4 min lag sakta hai)")
        old = _ctx["browser_pools"].pop(uid, None)
        if old is not None:
            try:
                await old.stop()
            except Exception as e:
                print(f"⚠️ Purana pool band karne me error: {e}")
        try:
            from browser_pool import BrowserPool
            pool = BrowserPool(uid, accs)
            _ctx["browser_pools"][uid] = pool
            await pool.start()
            await status.edit_text(
                f"✅ Browsers restart ho gaye: **{pool.healthy_count()}/{len(pool.workers)} ready**\n"
                f"`/browsers` se detail dekho."
            )
        except Exception as e:
            await status.edit_text(f"❌ Browser restart fail: {e}")

    # ---- Buttons menu (/start) — bot_menu.py ----
    try:
        import bot_menu
        bot_menu.register(bot)
        print("✅ Buttons menu loaded (bot me /start bhejo)")
    except Exception as e:
        print(f"⚠️ bot_menu load nahi hua: {e}")
