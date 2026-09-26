#!/usr/bin/env bash
# ============================================================
#  SMEX Bot Starter
#  Kaam: purane processes band -> .venv banao/active ->
#        requirements install -> fresh bot start (background)
#
#  Chalao:   ./start.sh          (fresh restart)
#            ./start.sh stop     (sirf band karna ho)
#            ./start.sh logs     (live logs dekhna ho)
# ============================================================
set -u
cd "$(dirname "$0")"

case "${1:-start}" in
  stop)
    echo "🛑 Bot band kar raha hoon..."
    pkill -f "main.py" 2>/dev/null
    pkill -f "browser_worker.py" 2>/dev/null
    pkill -f "client_runner.py" 2>/dev/null
    pkill -f "playwright_runner.py" 2>/dev/null
    pkill -f "dp_manager.py" 2>/dev/null
    sleep 3
    pkill -9 -f "main.py" 2>/dev/null
    pkill -9 -f "browser_worker.py" 2>/dev/null
    rm -f bot.pid
    echo "✅ Bot band ho gaya."
    exit 0
    ;;
  logs)
    tail -f logs/bot.log
    exit 0
    ;;
esac

echo "=========================================="
echo "🤖 SMEX Bot Starter (fresh restart)"
echo "=========================================="

# ---- 1. purane processes band ----
echo "🛑 Purane processes band kar raha hoon..."
pkill -f "main.py" 2>/dev/null
pkill -f "browser_worker.py" 2>/dev/null
pkill -f "client_runner.py" 2>/dev/null
pkill -f "playwright_runner.py" 2>/dev/null
pkill -f "dp_manager.py" 2>/dev/null
sleep 3
for pat in "main.py" "browser_worker.py" "client_runner.py" "playwright_runner.py" "dp_manager.py"; do
  if pgrep -f "$pat" >/dev/null 2>&1; then
    echo "   Force kill: $pat"
    pkill -9 -f "$pat" 2>/dev/null
  fi
done
rm -f bot.pid
echo "✅ Purane processes band."

# ---- 2. python check ----
if ! command -v python3 >/dev/null 2>&1; then
  echo "❌ python3 nahi mila. Pehle install karo: sudo apt install python3 python3-venv"
  exit 1
fi

# ---- 3. .venv banao + active ----
if [ ! -d ".venv" ]; then
  echo "📦 .venv bana raha hoon (pehli baar)..."
  python3 -m venv .venv || {
    echo "❌ venv nahi bana. Ye chalao: sudo apt install python3-venv"
    exit 1
  }
else
  echo "📦 .venv mil gaya."
fi
# shellcheck disable=SC1091
source .venv/bin/activate
echo "✅ venv active: $(which python)"

# ---- 4. requirements ----
echo "📥 Requirements install ho rahe hain..."
python -m pip install --upgrade pip -q
pip install -r requirements.txt || { echo "❌ requirements install fail"; exit 1; }
echo "✅ Requirements done."

# ---- 5. playwright browser ----
echo "🌐 Playwright chromium check..."
python -m playwright install chromium || echo "⚠️ Chromium install me dikkat — agar browser error aaye to: sudo .venv/bin/playwright install-deps"

# ---- 6. .env check ----
if [ ! -f ".env" ]; then
  echo "❌ .env file nahi mili!"
  echo "   .env.example dekh ke .env banao (BOT_TOKEN, API_ID, API_HASH), phir dobara chalao."
  exit 1
fi

# ---- 7. fresh start ----
mkdir -p logs
echo "🚀 Fresh bot start kar raha hoon..."
nohup python main.py > logs/bot.log 2>&1 &
echo $! > bot.pid
sleep 5
if kill -0 "$(cat bot.pid)" 2>/dev/null; then
  echo "=========================================="
  echo "✅ Bot chal raha hai! PID: $(cat bot.pid)"
  echo "📄 Live logs: ./start.sh logs"
  echo "🛑 Band karna ho: ./start.sh stop"
  echo "📱 Ab Telegram pe bot ko /start bhejo!"
  echo "=========================================="
else
  echo "❌ Bot start nahi hua. Error dekho:"
  tail -25 logs/bot.log
  exit 1
fi
