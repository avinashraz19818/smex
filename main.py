import os
import sys
import json
import asyncio
import random
import re

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

from dotenv import load_dotenv
from pyrogram import Client, filters, enums
from pyrogram.types import Message
from pyrogram.errors import FloodWait

load_dotenv()

BASE_DIR = os.path.dirname(__file__)
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", os.path.join(BASE_DIR, "pw-browsers"))

CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

config = load_config()

bot = Client(
    "orchestrator_bot",
    api_id=int(os.getenv("API_ID", 1234567)),
    api_hash=os.getenv("API_HASH", "abcdef"),
    bot_token=os.getenv("BOT_TOKEN"),
    in_memory=True,
)

client_sessions = []
client_slot_map = {}  # session_env ("CLIENT_1_SESSION") -> Client  (bot_setup /login ke liye)
owner_sessions = {}
browser_pools = {}

async def init_clients():
    telegram_clients = config.get("telegram_clients", [])
    for i, session_env in enumerate(telegram_clients):
        session_str = os.getenv(session_env, "").strip()
        if session_str and not session_str.startswith("your_"):
            try:
                c = Client(f"client_{i+1}", api_id=int(os.getenv("API_ID", 1234567)), api_hash=os.getenv("API_HASH", "abcdef"), session_string=session_str, sleep_threshold=60)
                await c.start()
                c.my_user = await c.get_me()
                client_sessions.append(c)
                client_slot_map[session_env] = c
                print(f"✅ Started Global Client {i+1}: {c.my_user.first_name}")
                try:
                    async for _ in c.get_dialogs(limit=50): pass
                except Exception:
                    pass
            except Exception as e:
                print(f"⚠️ Could not start Global Client {i+1} ({session_env}): {e}")

    for owner_id_str, o_cfg in config.get("owners", {}).items():
        session_env = o_cfg.get("main_id_env", "")
        session_str = os.getenv(session_env, "").strip()
        if session_str and not session_str.startswith("your_"):
            try:
                c = Client(f"owner_{owner_id_str}", api_id=int(os.getenv("API_ID", 1234567)), api_hash=os.getenv("API_HASH", "abcdef"), session_string=session_str, sleep_threshold=60)
                await c.start()
                c.my_user = await c.get_me()
                owner_sessions[owner_id_str] = c
                print(f"✅ Started Owner Main ID for {owner_id_str}: {c.my_user.first_name}")
                try:
                    async for _ in c.get_dialogs(limit=100): pass
                except Exception:
                    pass
            except Exception as e:
                print(f"⚠️ Could not start Owner Main ID for {owner_id_str} ({session_env}): {e}")

EMOJI_MAP = {
    "TICK": ("TICK_EMOJI", "✔️"),
    "TICK_EMOJI": ("TICK_EMOJI", "✔️"),
    "CASH": ("MONEY_EMOJI", "💰"),
    "MONEY": ("MONEY_EMOJI", "💰"),
    "MONEY_EMOJI": ("MONEY_EMOJI", "💰"),
    "HUNDRED": ("CROWN_EMOJI", "👑"),
    "CROWN": ("CROWN_EMOJI", "👑"),
    "CROWN_EMOJI": ("CROWN_EMOJI", "👑"),
    "FIRE": ("FIRE_EMOJI", "🔥"),
    "FIRE_EMOJI": ("FIRE_EMOJI", "🔥"),
}

valid_emoji_ids = set()

def resolve_emoji_id(key: str):
    env_key, glyph = EMOJI_MAP.get(key.upper(), (key, "✔️"))
    for candidate in (key, key.upper(), env_key):
        val = os.getenv(candidate, "").strip()
        if val.isdigit():
            return val, glyph
    return "", glyph

def configured_emoji_ids():
    found = {}
    for key in EMOJI_MAP:
        eid, _ = resolve_emoji_id(key)
        if eid:
            found.setdefault(eid, key)
    return found

async def validate_premium_emojis():
    configured = configured_emoji_ids()
    if not configured:
        print("ℹ️ Koi premium emoji id set nahi hai — normal emoji use honge")
        return

    non_premium = [oid for oid, c in owner_sessions.items()
                   if getattr(c.my_user, "is_premium", None) is False]
    if non_premium:
        print(f"⚠️ Owner ID {non_premium} pe Telegram Premium nahi hai — Telegram custom emoji "
              f"bhejne hi nahi dega, normal emoji use honge")
        return

    owner_client = next(iter(owner_sessions.values()), None)
    if not owner_client:
        return

    bad = []
    for eid, key in configured.items():
        try:
            stickers = await owner_client.get_custom_emoji_stickers([int(eid)])
            if stickers:
                valid_emoji_ids.add(eid)
            else:
                bad.append(f"{key}={eid}")
        except Exception as e:
            print(f"ℹ️ {key}={eid} verify nahi hua ({e}) — try karke dekhenge")
            valid_emoji_ids.add(eid)

    if valid_emoji_ids:
        print(f"✅ Premium emoji active: "
              + ", ".join(f"{configured[i]}={i}" for i in sorted(valid_emoji_ids)))
    if bad:
        print("⚠️ Ye emoji ids Telegram pe nahi mili (normal emoji use hoga): " + ", ".join(bad))

def format_premium_message(raw_text: str, next_period: str) -> str:
    text = raw_text.replace("{PERIOD}", next_period)

    def replace_placeholder(match):
        key = match.group(1)
        eid, glyph = resolve_emoji_id(key)
        if eid and eid in valid_emoji_ids:
            return f'<emoji id="{eid}">{glyph}</emoji>'
        return glyph

    return re.sub(r"\{([A-Za-z0-9_]+)\}", replace_placeholder, text)

PERMANENT_ERRORS = ("DOCUMENT_INVALID", "EMOJI_INVALID", "EMOJI_MARKUP_INVALID",
                    "ENTITY_BOUNDS_INVALID", "PREMIUM_ACCOUNT_REQUIRED",
                    "PEER_ID_INVALID", "USER_IS_BLOCKED", "USER_BLOCKED",
                    "MESSAGE_EMPTY", "CHAT_WRITE_FORBIDDEN")

def strip_premium_emojis(text: str) -> str:
    return re.sub(r'<emoji id="\d+">(.*?)</emoji>', r"\1", text)

async def safe_send_message(client, chat_id, text, label="", parse_mode=None, retries=3):
    backoff = 1.5
    attempt = 0
    tried_plain = False
    while attempt < retries:
        attempt += 1
        try:
            return await client.send_message(chat_id, text, parse_mode=parse_mode)
        except FloodWait as e:
            wait = getattr(e, "value", None) or getattr(e, "x", 5)
            print(f"⏳ FloodWait {wait}s -> {label} (attempt {attempt}/{retries})")
            await asyncio.sleep(int(wait) + 1)
        except Exception as e:
            err = str(e).upper()
            permanent = any(code in err for code in PERMANENT_ERRORS)
            if permanent and not tried_plain:
                plain = strip_premium_emojis(text)
                if plain != text:
                    if valid_emoji_ids:
                        valid_emoji_ids.clear()
                        print("⚠️ Telegram ne premium emoji reject kiya — is run me normal emoji "
                              "se bheja jayega (emoji ids check karo)")
                    text = plain
                    tried_plain = True
                    attempt -= 1
                    continue
            if permanent:
                print(f"❌ {label}: {e} — retry se fayda nahi, skip")
                return None
            print(f"⚠️ Send failed -> {label} (attempt {attempt}/{retries}): {e}")
            await asyncio.sleep(backoff)
            backoff *= 2
    print(f"❌ Could not send -> {label} after {retries} attempts")
    return None

async def send_bet_sequence(owner_client, c, bet_msgs, next_period, pending_map, start_delay, client_no):
    if start_delay:
        await asyncio.sleep(start_delay)
    delivered = 0
    total = len(bet_msgs)
    for i, msg_tpl in enumerate(bet_msgs):
        formatted_text = format_premium_message(msg_tpl, next_period)
        sent = await safe_send_message(
            owner_client, c.my_user.id, formatted_text,
            label=f"bet msg {i+1}/{total} to Client {client_no} ({c.my_user.first_name})",
            parse_mode=enums.ParseMode.HTML
        )
        if sent:
            delivered += 1
            seen_after(c, owner_client.my_user.id, 0.8, 3.5)
            nums = [str(n) for n in range(10) if f"{n} -- NUMBER" in msg_tpl]
            if len(nums) == 1:
                pending_map[nums[0]] = sent.id
        if i < total - 1:
            await asyncio.sleep(random.uniform(1.1, 1.5))
    print(f"📨 Client {client_no} ({c.my_user.first_name}): {delivered}/{total} bet messages delivered")
    return delivered

def format_win_amount(amount: int) -> str:
    if amount < 1000:
        return str(amount)
    k = amount / 1000
    k_text = f"{k:.0f}k" if abs(k - round(k)) < 0.05 else f"{k:.1f}k"
    return random.choice([str(amount), k_text])

def pick_exchange(owner_cfg, kind):
    block = owner_cfg.get(kind)
    if not block:
        return None

    if isinstance(block, list):
        item = random.choice(block)
        if isinstance(item, dict):
            client_text = item.get("s2_msg") or item.get("session2_random") or ""
            owner_text = item.get("s1_reply") or item.get("s1_msg") or ""
            return {"client": client_text, "owner": owner_text}
        return {"client": str(item), "owner": ""}

    client_lines = block.get("session2_random") or block.get("s2_msg") or []
    owner_lines = (block.get("session1_random") or block.get("session1_reply")
                   or block.get("s1_reply") or block.get("s1_msg") or [])
    if not client_lines:
        return None
    return {
        "client": random.choice(client_lines),
        "owner": random.choice(owner_lines) if owner_lines else "",
    }

async def mark_seen(reader, peer_id):
    try:
        await reader.read_chat_history(peer_id)
        return True
    except Exception as e:
        print(f"⚠️ Seen mark nahi hua: {e}")
        return False

def seen_after(reader, peer_id, lo=1.5, hi=6.0):
    async def _later():
        await asyncio.sleep(random.uniform(lo, hi))
        await mark_seen(reader, peer_id)
    return asyncio.create_task(_later())

async def human_send(sender, chat_id, text, reply_to=None, parse_mode=None, max_wait=5.0):
    try:
        await sender.send_chat_action(chat_id, enums.ChatAction.TYPING)
    except Exception:
        pass
    await asyncio.sleep(min(max_wait, max(0.4, len(text) / random.uniform(8, 16))))
    try:
        return await sender.send_message(chat_id, text, reply_to_message_id=reply_to,
                                         parse_mode=parse_mode)
    except Exception as e:
        print(f"⚠️ Chat message nahi gaya: {e}")
        return None

async def find_message_id(reader, peer_id, text, limit=6):
    try:
        async for m in reader.get_chat_history(peer_id, limit=limit):
            if (m.text or m.caption or "") == text:
                return m.id
    except Exception as e:
        print(f"⚠️ Reply ke liye message nahi mila: {e}")
    return None

async def human_chat_exchange(owner_client, c, owner_cfg, kind):
    ex = pick_exchange(owner_cfg, kind)
    if not ex or not ex["client"]:
        return

    await asyncio.sleep(random.uniform(2.0, 30.0))

    asked = ex["client"]
    sent = await human_send(c, owner_client.my_user.id, asked)
    if sent is None:
        return

    await asyncio.sleep(random.uniform(1.5, 6.0))
    await mark_seen(owner_client, c.my_user.id)

    if not ex["owner"]:
        return

    await asyncio.sleep(random.uniform(1.5, 7.0))
    reply_to = await find_message_id(owner_client, c.my_user.id, asked)

    replied = await human_send(owner_client, c.my_user.id, ex["owner"], reply_to=reply_to)

    if replied is not None:
        seen_after(c, owner_client.my_user.id)

def pick_feedback_senders(bet_shot_idxs, ss_only_idxs):
    senders = set(ss_only_idxs)
    if len(bet_shot_idxs) > 1:
        k = random.randint(1, len(bet_shot_idxs) - 1)
        senders.update(random.sample(bet_shot_idxs, k))
    elif bet_shot_idxs:
        senders.update(random.sample(bet_shot_idxs, random.randint(0, 1)))
    return senders

def fill_placeholder(text, key, value):
    return re.sub(r"\{" + key + r"\}", lambda m: value, text, flags=re.IGNORECASE)

def build_feedback(owner_cfg, bet_amount, winning_number):
    feedbacks = owner_cfg.get("feedbacks", ["Maza aagya {WIN} jeet gya!"])
    fb = random.choice(feedbacks)
    win = bet_amount * 9 if bet_amount else 900
    fb = fill_placeholder(fb, "WIN", format_win_amount(win))
    fb = fill_placeholder(fb, "BET", str(bet_amount) if bet_amount else "100")
    if winning_number is not None and str(winning_number) != "":
        fb = fill_placeholder(fb, "NUMBER", str(winning_number))
    return fb

async def do_bet(mode: str, owner_id: str, message: Message):
    owner_cfg = config["owners"].get(owner_id)
    if not owner_cfg:
        await message.reply_text("❌ Unauthorized owner.")
        return
        
    owner_client = owner_sessions.get(owner_id)
    if not owner_client:
        await message.reply_text("❌ Owner main ID session is not configured or running.")
        return

    next_period_full = fetch_next_period(owner_cfg)

    pool = browser_pools.get(owner_id)
    if pool and pool.ready_count():
        warn = ""
        bad = [w.idx for w in pool.problem_workers() if w.alive]
        if bad:
            warn = f"\n⚠️ Browser {bad} board pe nahi hai — koshish karega par miss ho sakta hai (/refresh)"
        await message.reply_text(
            f"🚀 {mode}: {pool.healthy_count()}/{len(pool.workers)} browsers ready — "
            f"period {next_period_full[-3:] if next_period_full else '???'} pe turant bet lag rahi hai..."
            + warn
        )
        bet_output = asyncio.create_task(pool.bet(mode, period=next_period_full))
    else:
        await message.reply_text(
            f"⚠️ Koi browser khula nahi mila — {mode} ke liye naye browser launch kar raha hoon "
            f"(thoda slow, period nikal sakta hai)."
        )
        script_path = os.path.join(os.path.dirname(__file__), "playwright_runner.py")
        process = await asyncio.create_subprocess_exec(
            sys.executable, script_path, mode, owner_id, next_period_full or "",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, "PYTHONUNBUFFERED": "1"}
        )
        bet_output = asyncio.create_task(legacy_bet_output(process))

    asyncio.create_task(run_chat_simulation(
        mode, owner_id, owner_client, owner_cfg, message, bet_output, next_period_full
    ))

async def legacy_bet_output(process):
    stdout, stderr = await process.communicate()
    return stdout.decode('utf-8', errors='replace') + "\n" + stderr.decode('utf-8', errors='replace')

def fetch_next_period(owner_cfg):
    import requests
    cdn_url = owner_cfg.get("urls", {}).get("cdn_url", "")
    if not cdn_url:
        return ""
    try:
        r = requests.get(cdn_url, timeout=5)
        latest_period = int(r.json()["data"]["list"][0]["issueNumber"])
        return str(latest_period + 1)
    except Exception as e:
        print(f"Error fetching period from CDN: {e}")
        return ""

@bot.on_message(filters.command(["bet", "hbet"], prefixes="/"))
async def handle_bot_bet_command(client: Client, message: Message):
    owner_id = str(message.from_user.id) if message.from_user else ""
    if owner_id not in config["owners"]:
        await message.reply_text("❌ Unauthorized owner.")
        return
    command = message.command[0].lower()
    mode = "hbet" if command == "hbet" else "bet"
    await do_bet(mode, owner_id, message)

async def run_chat_simulation(mode, owner_id, owner_client, owner_cfg, bot_message, bet_output, next_period_full=""):
    import requests
    cdn_url = owner_cfg.get("urls", {}).get("cdn_url", "")
    if not next_period_full:
        next_period_full = fetch_next_period(owner_cfg)
    next_period = next_period_full[-3:] if next_period_full else "???"

    total_clients = len(client_sessions)
    all_indices = list(range(total_clients))
    random.shuffle(all_indices)
    
    bet_indices = all_indices[:4] if total_clients >= 4 else all_indices
    ss_only_indices = all_indices[4:] if total_clients >= 4 else []
    if total_clients < 6:
        print(f"⚠️ Sirf {total_clients}/6 global clients start huye — bet messages {len(bet_indices)} clients ko jayenge")
    print(f"🎯 Bet message clients: {[i+1 for i in bet_indices]} | SS-only: {[i+1 for i in ss_only_indices]}")

    pending_bet_messages = {}
    bet_msgs = owner_cfg.get("bet_messages", [])
    
    if owner_client and bet_msgs:
        send_tasks = []
        for n, idx in enumerate(bet_indices):
            c = client_sessions[idx]
            pending_bet_messages[c.my_user.id] = {}
            send_tasks.append(asyncio.create_task(
                send_bet_sequence(
                    owner_client, c, bet_msgs, next_period,
                    pending_bet_messages[c.my_user.id],
                    start_delay=n * 0.4,
                    client_no=idx + 1
                )
            ))
        results = await asyncio.gather(*send_tasks, return_exceptions=True)

        incomplete = []
        for n, idx in enumerate(bet_indices):
            delivered = results[n] if isinstance(results[n], int) else 0
            if delivered < len(bet_msgs):
                incomplete.append(f"Client {idx+1} ({client_sessions[idx].my_user.first_name}): {delivered}/{len(bet_msgs)}")
        if incomplete:
            await bot_message.reply_text(
                "⚠️ Kuch bet messages deliver nahi hue:\n" + "\n".join(incomplete)
            )
        else:
            await bot_message.reply_text(
                f"✅ Saare {len(bet_msgs)} bet messages "
                f"{len(bet_indices)} clients ko bhej diye: "
                + ", ".join(f"Client {i+1}" for i in sorted(bet_indices))
            )

    chat_tasks = []
    chat_kinds = {}
    for idx in bet_indices:
        kind = random.choice(["conversations", "confuse_chat"])
        chat_kinds[idx + 1] = kind
        chat_tasks.append(asyncio.create_task(
            human_chat_exchange(owner_client, client_sessions[idx], owner_cfg, kind)
        ))
    if chat_kinds:
        print("💬 " + ", ".join(f"Client {i}: {k}" for i, k in sorted(chat_kinds.items())))

    output = await bet_output
    for t in chat_tasks:
        t.cancel()
    print("Betting output:\n", output)

    screenshot_paths = {}
    winning_number = None
    bet_amounts = {}
    failed_clients = {}

    wingo_accounts = owner_cfg.get("wingo_accounts", [])

    for line in output.split('\n'):
        line = line.strip()
        if line.startswith("WINNING_NUMBER="):
            winning_number = line.split("WINNING_NUMBER=")[1].strip()
        elif line.startswith("BET_AMOUNT_"):
            try:
                key, val = line.split("=", 1)
                bet_amounts[int(key.replace("BET_AMOUNT_", ""))] = int(val.strip())
            except Exception:
                pass
        elif line.startswith("SUCCESS_SCREENSHOT_PATH_"):
            parts = line.split("=", 1)
            client_idx = int(parts[0].replace("SUCCESS_SCREENSHOT_PATH_", ""))
            screenshot_paths[client_idx] = parts[1].strip()
        elif line.startswith("FAILED_CLIENT_INFO="):
            parts = line.split("FAILED_CLIENT_INFO=")[1].split(":")
            if len(parts) >= 3:
                f_idx = int(parts[0])
                failed_clients[f_idx] = (parts[1], parts[2])

    for i, w_cfg in enumerate(wingo_accounts):
        c_idx = i + 1
        if c_idx not in screenshot_paths and c_idx not in failed_clients:
            failed_clients[c_idx] = (w_cfg.get("phone", ""), w_cfg.get("password", ""))

    if failed_clients:
        for f_idx, (f_phone, f_pass) in failed_clients.items():
            await bot_message.reply_text(
                f"⚠️ ID {f_idx} bet nahi lga paayi (fund khatam ya error).\n"
                f"📱 Phone: `{f_phone}`\n"
                f"🔑 Pass: `{f_pass}`"
            )

    if not screenshot_paths:
        await bot_message.reply_text(f"❌ Kisi bhi ID se bet nahi lag paayi ya screenshot nahi mila.\nLogs:\n{output[-800:]}")
        return

    if not winning_number and cdn_url:
        try:
            r = requests.get(cdn_url, timeout=5)
            winning_number = str(r.json()["data"]["list"][0].get("number"))
        except Exception:
            pass

    if winning_number is not None and owner_client:
        for idx in bet_indices:
            c = client_sessions[idx]
            c_id = c.my_user.id
            if c_id in pending_bet_messages:
                losing_ids = [m_id for num, m_id in pending_bet_messages[c_id].items() if str(num) != str(winning_number)]
                if losing_ids:
                    try:
                        await owner_client.delete_messages(c_id, losing_ids)
                    except Exception as e:
                        print(f"⚠️ Error deleting losing numbers for Client {idx+1}: {e}")

    live_shots = {i: p for i, p in screenshot_paths.items()
                  if os.path.exists(p) and (i - 1) < len(client_sessions)}
    bet_shot_idxs = [i for i in live_shots if (i - 1) in bet_indices]
    ss_only_idxs = [i for i in live_shots if (i - 1) not in bet_indices]

    feedback_senders = pick_feedback_senders(bet_shot_idxs, ss_only_idxs)

    send_order = list(live_shots.items())
    random.shuffle(send_order)

    async def deliver_shot(idx, screenshot_path, stagger):
        c = client_sessions[idx - 1]
        if stagger:
            await asyncio.sleep(stagger)

        if idx not in feedback_senders:
            try:
                await c.send_photo(owner_client.my_user.id, photo=screenshot_path)
                seen_after(owner_client, c.my_user.id, 0.5, 2.0)
            except Exception as e:
                print(f"⚠️ Client {idx} failed to send pure screenshot to owner: {e}")
            return

        fb = build_feedback(owner_cfg, bet_amounts.get(idx, 0), winning_number)
        try:
            if random.random() < 0.55:
                await c.send_photo(owner_client.my_user.id, photo=screenshot_path, caption=fb)
            else:
                await c.send_photo(owner_client.my_user.id, photo=screenshot_path)
                await asyncio.sleep(random.uniform(0.8, 2.5))
                await human_send(c, owner_client.my_user.id, fb, max_wait=1.8)
            seen_after(owner_client, c.my_user.id, 0.5, 2.0)
        except Exception as e:
            print(f"⚠️ Client {idx} failed to send feedback to owner: {e}")

    await asyncio.gather(*[
        deliver_shot(idx, path, n * random.uniform(0.15, 0.5))
        for n, (idx, path) in enumerate(send_order)
    ], return_exceptions=True)

    no_fb = sorted(i for i in live_shots if i not in feedback_senders)
    print(f"📝 Feedback bheja: {sorted(feedback_senders)} | sirf screenshot: {no_fb}")

    await bot_message.reply_text(f"✅ Round complete! Winning Number: {winning_number or 'Done'}. Successful screenshots and chats Owner account ko bhej diye gaye hain.")

async def do_dp(message: Message):
    await message.reply_text("🔄 Changing DP and names for all 6 clients... This will take a few seconds.")
    try:
        script_path = os.path.join(os.path.dirname(__file__), "dp_manager.py")
        process = await asyncio.create_subprocess_exec(
            sys.executable, script_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, "PYTHONUNBUFFERED": "1"}
        )
        stdout, stderr = await process.communicate()
        out_text = stdout.decode('utf-8', errors='ignore').strip()
        err_text = stderr.decode('utf-8', errors='ignore').strip()
        if out_text:
            await message.reply_text(f"✅ DP Update completed:\n{out_text}")
        elif err_text:
            await message.reply_text(f"⚠️ DP Update error:\n{err_text}")
        else:
            await message.reply_text("✅ DP Update finished.")
    except Exception as e:
        await message.reply_text(f"❌ Subprocess error: {e}")

@bot.on_message(filters.command("dp", prefixes="/"))
async def handle_bot_dp_command(client: Client, message: Message):
    owner_id = str(message.from_user.id) if message.from_user else ""
    if owner_id not in config["owners"]:
        await message.reply_text("❌ Unauthorized owner.")
        return
    await do_dp(message)

async def start_browser_pools():
    from browser_pool import BrowserPool

    for owner_id in owner_sessions:
        accounts = config["owners"].get(owner_id, {}).get("wingo_accounts", [])
        if not accounts:
            print(f"ℹ️ Owner {owner_id} ke liye koi wingo account nahi — browser nahi khulega")
            continue
        pool = BrowserPool(owner_id, accounts)
        browser_pools[owner_id] = pool
        await pool.start()

async def browser_keepalive_loop(interval=300):
    while True:
        try:
            await asyncio.sleep(interval)
            for owner_id, pool in browser_pools.items():
                if not pool.ready_count():
                    continue
                statuses = await pool.keepalive()
                bad = {i: s for i, s in statuses.items() if not s.startswith("ok")}
                if bad:
                    print("🔧 Keepalive: " + ", ".join(f"Browser {i}: {s}" for i, s in bad.items()))
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"⚠️ Keepalive loop error: {e}")

@bot.on_message(filters.command("refresh", prefixes="/"))
async def handle_refresh_command(client: Client, message: Message):
    owner_id = str(message.from_user.id) if message.from_user else ""
    if owner_id not in config["owners"]:
        await message.reply_text("❌ Unauthorized owner.")
        return

    pool = browser_pools.get(owner_id)
    if not pool or not pool.ready_count():
        await message.reply_text("⚠️ Koi browser khula nahi hai. Bot restart karo.")
        return

    status_msg = await message.reply_text(f"🔄 {pool.ready_count()} browsers refresh kar raha hoon...")
    statuses = await pool.refresh()

    lines = []
    for idx in sorted(statuses):
        txt = statuses[idx]
        mark = "✅" if "ready" in txt or "khola" in txt else "⚠️"
        lines.append(f"{mark} Browser {idx}: {txt}")
    tail = ""
    if pool.problem_workers():
        tail = ("\n\nℹ️ Jo browser theek nahi hua uska screenshot project folder me "
                "`debug_refresh_<N>_<owner>.png` naam se save hai — usme dikhega page pe kya atka hai.")
    await status_msg.edit_text("🔄 Refresh complete:\n" + "\n".join(lines) + tail)

@bot.on_message(filters.command("browsers", prefixes="/"))
async def handle_browsers_command(client: Client, message: Message):
    owner_id = str(message.from_user.id) if message.from_user else ""
    if owner_id not in config["owners"]:
        await message.reply_text("❌ Unauthorized owner.")
        return

    pool = browser_pools.get(owner_id)
    if not pool:
        await message.reply_text("⚠️ Is owner ke liye koi browser pool nahi chal raha.")
        return
    lines = []
    for w in pool.workers:
        if not w.alive:
            icon = "🔴"
        elif w.healthy:
            icon = "🟢"
        else:
            icon = "🟡"
        lines.append(f"{icon} Browser {w.idx}: {w.status.strip() or w.failed_reason or 'no status'}")
    await message.reply_text(
        f"🌐 {pool.healthy_count()}/{len(pool.workers)} browsers WinGo board pe ready:\n"
        + "\n".join(lines)
    )

@bot.on_message(filters.command("emojiid", prefixes="/"))
async def handle_emoji_id_command(client: Client, message: Message):
    owner_id = str(message.from_user.id) if message.from_user else ""
    if owner_id not in config["owners"]:
        await message.reply_text("❌ Unauthorized owner.")
        return

    target = message.reply_to_message or message
    entities = (target.entities or []) + (target.caption_entities or [])
    ids = []
    for ent in entities:
        if ent.type == enums.MessageEntityType.CUSTOM_EMOJI and ent.custom_emoji_id:
            if str(ent.custom_emoji_id) not in ids:
                ids.append(str(ent.custom_emoji_id))

    if not ids:
        await message.reply_text(
            "ℹ️ Premium emoji bhejo is tarah:\n"
            "`/emojiid ✔️💰👑` (premium emoji keyboard se)\n"
            "ya premium emoji wale message pe reply karke `/emojiid` likho."
        )
        return

    lines = "\n".join(f"`{i}`" for i in ids)
    await message.reply_text(f"✅ Custom emoji ids:\n{lines}\n\nIn ids ko .env me daalo (TICK_EMOJI, MONEY_EMOJI, CROWN_EMOJI, FIRE_EMOJI).")

# ---- Bot se poora setup: /login (OTP), wingo, links, emoji, owners ----
# (bot_setup.py — session string / code edit kiye bina sab bot se)
try:
    import bot_setup
    bot_setup.register(bot, {
        "config": config,
        "client_sessions": client_sessions,
        "client_slot_map": client_slot_map,
        "owner_sessions": owner_sessions,
        "browser_pools": browser_pools,
        "valid_emoji_ids": valid_emoji_ids,
        "revalidate": validate_premium_emojis,
        "do_bet": do_bet,
        "do_dp": do_dp,
    })
    print("✅ Bot-setup module loaded (bot me /help bhejo)")
except Exception as e:
    print(f"⚠️ bot_setup load nahi hua: {e}")

async def main():
    print("Initializing clients...")
    await init_clients()
    await validate_premium_emojis()
    print("Starting Orchestrator Bot...")
    try:
        await bot.start()
    except Exception as e:
        print(f"Bot start nahi hua: {e}")
        print("BOT_TOKEN ko BotFather se verify/regenerate karo. Userbot sessions ke liye /login se new session banao.")
        raise
    me = await bot.get_me()
    print(f"✅ Orchestrator Bot started: @{me.username} ({me.first_name})")

    await start_browser_pools()
    keepalive_task = asyncio.create_task(browser_keepalive_loop())

    print("🤖 Bot is active! Commands: /help, /login, /bet, /hbet, /refresh, /browsers, /dp, /emojiid")

    try:
        from pyrogram import idle
        await idle()
    finally:
        keepalive_task.cancel()
        print("🧹 Browsers band kar raha hoon...")
        for pool in browser_pools.values():
            await pool.stop()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(main())
    except (KeyboardInterrupt, SystemExit):
        print("\nStopping bot...")
