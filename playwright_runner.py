import os
import sys
import asyncio
import json

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

mode = sys.argv[1] if len(sys.argv) > 1 else "bet"
owner_id = sys.argv[2] if len(sys.argv) > 2 else ""
intended_period = sys.argv[3] if len(sys.argv) > 3 else ""

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")

async def run_client(idx, phone, password, mode, owner_id):
    script_path = os.path.join(os.path.dirname(__file__), "client_runner.py")
    process = await asyncio.create_subprocess_exec(
        sys.executable, script_path, str(idx), phone, password, mode, owner_id, intended_period,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, "PYTHONUNBUFFERED": "1"}
    )
    stdout, stderr = await process.communicate()
    output = stdout.decode('utf-8', errors='replace') + "\n" + stderr.decode('utf-8', errors='replace')
    
    clean_lines = []
    for line in output.split("\n"):
        if (line.startswith("SUCCESS_SCREENSHOT_PATH_") or 
            line.startswith("WINNING_NUMBER=") or 
            line.startswith("BET_AMOUNT") or
            line.startswith("INCOMPLETE_BETS_ERROR") or
            line.startswith("FAILED_CLIENT_INFO=")):
            clean_lines.append(line)
        else:
            clean_lines.append(f"[Client {idx}] {line}")
            
    return "\n".join(clean_lines)

async def run_all_clients():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)
        
    owner_cfg = config.get("owners", {}).get(owner_id, {})
    wingo_accounts = owner_cfg.get("wingo_accounts", [])
    if not wingo_accounts:
        print("No wingo_accounts configured for this owner.")
        return
        
    tasks = []
    for i, w_cfg in enumerate(wingo_accounts):
        tasks.append(run_client(i+1, w_cfg.get("phone", ""), w_cfg.get("password", ""), mode, owner_id))
        
    results = await asyncio.gather(*tasks)
    
    for out in results:
        print(out)

if __name__ == "__main__":
    asyncio.run(run_all_clients())
