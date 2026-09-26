# 🤖 Bot Se Poora Setup — Guide (Hindi)

Ab **session string, password, links — kuch bhi code me dalne ki zaroorat nahi.**
Sab kuch bot ko message bhej ke hoga. Code me haath lagana band. 🔒

## 0. Sabse Asaan Tarika — BUTTONS 🎛️

Bot ko **`/start`** bhejo — poora **control panel buttons me** khul jayega:

- 📱 **Login** — Owner / Client1-6 login (OTP se), Logout
- 🎰 **WinGo IDs** — Add / Edit / Delete (✏️1 🗑️1 buttons)
- 🔗 **Links** — login/room/CDN badlo
- 💬 **Messages** — bet messages + feedbacks
- ✨ **Emoji / API** — emoji IDs, API, headless on/off
- 👑 **Owners** — naya boss jodo/hatayo
- 🌐 **Browsers** — refresh / restart
- 🚀 **Bet** — BET / HBET / DP yahin se dabao
- ❓ **Help** — `🆕 Pehli baar setup?` me 5-step guide hai

Button dabao → bot puchega → jawab text me bhejo → ho gaya!
(Beech me chhodo to ❌ **Radd karo** dabao. `/` wale purane commands bhi chalte rahenge.)

---

## Server Pe Naya Code Lagana (Update) 🖥️

**Tarika 1 — GitHub se (agar naya code GitHub pe push hai):**

```bash
cd ~/smex
git pull
chmod +x start.sh
./start.sh
```

**Tarika 2 — ZIP se (bina git ke):**

1. `smex-update.zip` download karo
2. Server pe `smex` folder me extract karo (purani files replace ho jayengi)
3. Phir:
```bash
cd ~/smex
chmod +x start.sh
./start.sh
```

**`start.sh` kya-kya karta hai (ek command me sab):**

| Step | Kaam |
|---|---|
| 🛑 | Purane bot + browser processes band (force kill tak) |
| 📦 | `.venv` nahi hai to banata hai, phir active karta hai |
| 📥 | `requirements.txt` se sab install + Playwright chromium |
| 🚀 | Fresh bot background me start + `logs/bot.log` me logs |

Aur ye bhi:
```bash
./start.sh logs   # live logs dekho (Ctrl+C se bahar)
./start.sh stop   # bot band karo
```

> ⚠️ `./start.sh` chalane se **browsers dobara khulenge** (2-4 min). Bet ke beech me mat chalao!

---

## 1. Pehli Baar Chalane Ke Liye (sirf ek baar)

`.env` file me **sirf ye 4 cheezein** dalo:

```
BOT_TOKEN=...        (BotFather se)
API_ID=...           (my.telegram.org se)
API_HASH=...         (my.telegram.org se)
SUPERADMIN_ID=...    (apna Telegram numeric ID — @userinfobot se milega)
```

Phir bot start karo (ek hi command — venv + install + start sab khud hoga):

```bash
chmod +x start.sh
./start.sh
```

> Baaki sab neeche wale commands se bot ke andar hoga.

---

## 2. Account Login — Bina Session String 📱

Bot ko bhejo (bot ke **private chat** me karna, group me OTP dikhega):

| Kaam | Command |
|---|---|
| Apna owner account login | `/login owner` |
| Client 1 se 6 login | `/login client1` … `/login client6` |
| Login radd karna | `/cancel` |
| Kaun login hai / kaun nahi | `/sessions` |
| Logout karna | `/logout client3` |

**Flow:** `/login owner` → mobile number bhejo (`919876543210`) → Telegram app me aaya **OTP** bhejo →
agar 2-step password laga hai to wo bhejo → **ho gaya!** ✅

Session `.env` me **khud save** ho jayega aur account **turant start** bhi ho jayega.
(Bot ke restart ke baad bhi login bana rahega.)

> 🔐 OTP aur password wale messages bot khud delete karne ki koshish karta hai.

---

## 3. WinGo IDs (Phone + Password) 🎰

| Kaam | Command |
|---|---|
| List dekho | `/wingo` |
| Nayi jodo | `/addwingo 9199xxxxxx mypass` |
| Badlo | `/setwingo 2 9199xxxxxx newpass` |
| Hatao | `/delwingo 2` |

> ⚠️ WinGo ID badalne ke baad **`/restartbrowsers`** zaroor chalao, tabhi naye browser me lagega.

---

## 4. Links (Login / Room / CDN) 🔗

| Kaam | Command |
|---|---|
| Teenon links dekho | `/urls` |
| Login link badlo | `/seturl login https://...` |
| Wingo room link badlo | `/seturl room https://...` |
| Result (CDN) link badlo | `/seturl cdn https://...` |

> ⚠️ Link badalne ke baad bhi **`/restartbrowsers`** chalao.

---

## 5. Owner (Boss) Manage Karna 👑

| Kaam | Command |
|---|---|
| List | `/owners` |
| Naya owner jodo | `/addowner 123456789 Ramesh` |
| Owner hatao | `/delowner 123456789` |

Naya owner judne ke baad usko bolo:
1. `/login owner` — OTP se login
2. `/addwingo phone pass` — apni WinGo IDs dale
3. `/restartbrowsers` — browser khole

---

## 6. Emoji, API, Browser ✨

| Kaam | Command |
|---|---|
| Emoji IDs dekho | `/emojis` |
| Emoji ID lagao | `/setemoji tick 54630...` (tick / money / crown / fire) |
| Emoji ID nikalo | premium emoji bhej ke `/emojiid` |
| API badlo | `/setapi 1234567 abcdef...` |
| Browser headless on/off | `/setheadless on` ya `/setheadless off` |

---

## 7. Bet Messages 💬

| Kaam | Command |
|---|---|
| Bet messages dekho | `/betmsgs` |
| Naya jodo | `/addbetmsg GREEN 5 -- NUMBER {PERIOD}` |
| Hatao | `/delbetmsg 3` |
| Feedbacks dekho | `/feedbacks` |
| Feedback jodo | `/addfeedback Maza aagya {WIN} jeet gya!` |
| Feedback hatao | `/delfeedback 3` |

`{PERIOD}` `{WIN}` `{BET}` `{NUMBER}` apne aap bhar jayenge. **Turant effect** — restart nahi chahiye.

---

## 8. Kaam Ke Commands

| Kaam | Command |
|---|---|
| **Sab commands ki list** | **`/help`** |
| Poori summary (login/browsers/emoji) | `/status` |
| Browsers dobara kholo | `/restartbrowsers` |
| Bet lagao (purane) | `/bet` `/hbet` `/refresh` `/browsers` `/dp` |

---

## ⚠️ Ek Zaroori Security Baat

`.env` file me bot token + sessions hote hain — ye **kabhi GitHub pe mat daalo**.
`.gitignore` laga diya gaya hai, phir bhi:
- Agar `.env` pehle se GitHub pe chali gayi hai → repo ko **Private** karo aur BotFather se **token dobara generate** karo.
- Ye repo jiske paas hogi, wo tumhare accounts chala sakta hai. Dhyan rakho.
