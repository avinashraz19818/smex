import os
import sys
import json
import asyncio
import random

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

from dotenv import load_dotenv
from pyrogram import Client

load_dotenv()
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")

async def update_dp_and_name():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)

    all_names = list(dict.fromkeys(config.get("names_pool", [])))
    names_pool = [n for n in all_names if n.strip() and len(n.encode("utf-16-le")) // 2 <= 64]
    skipped = [n for n in all_names if n not in names_pool]
    if skipped:
        print(f"Skipping {len(skipped)} name(s) longer than Telegram's 64 limit: {skipped}")
    used_names = config.get("used_names", [])
    used_pics = config.get("used_pics", [])

    telegram_clients = config.get("telegram_clients", [])
    num_clients = len(telegram_clients)
    if num_clients == 0:
        print("No telegram_clients configured.")
        return

    available_names = [n for n in names_pool if n not in used_names]
    if len(available_names) < num_clients:
        print("Not enough available names, resetting used_names.")
        used_names = []
        available_names = list(names_pool)
        
    pics_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pics")
    if not os.path.isdir(pics_dir):
        print(f"Error: pics folder nahi mila: {pics_dir}")
        return
    all_pics = [f for f in os.listdir(pics_dir) if f.lower().endswith(('.png', '.jpg', '.jpeg'))] if os.path.exists(pics_dir) else []
    
    available_pics = [p for p in all_pics if p not in used_pics]
    if len(available_pics) < num_clients:
        print("Not enough available pics, resetting used_pics.")
        used_pics = []
        available_pics = list(all_pics)

    if len(available_names) < num_clients or len(available_pics) < num_clients:
        print(f"Error: Not enough names or pics even after reset. Ensure pics folder has at least {num_clients} images.")
        return

    selected_names = random.sample(available_names, num_clients)
    selected_pics = random.sample(available_pics, num_clients)

    for i, session_env in enumerate(telegram_clients):
        session_str = os.getenv(session_env)
        if session_str:
            c = Client(f"client_temp_{i+1}", api_id=int(os.getenv("API_ID", 1234567)), api_hash=os.getenv("API_HASH", "abcdef"), session_string=session_str)
            try:
                await c.start()
                
                new_name = selected_names[i]
                pic_name = selected_pics[i]
                
                await c.update_profile(first_name=new_name)
                
                async for photo in c.get_chat_photos("me"):
                    await c.delete_profile_photos(photo.file_id)
                    
                await c.set_profile_photo(photo=os.path.join(pics_dir, pic_name))
                await c.stop()
                
                used_names.append(new_name)
                used_pics.append(pic_name)
                print(f"Updated client {i+1} to {new_name} with {pic_name}")
            except Exception as e:
                print(f"Failed to update client {i+1}: {e}")

    config["used_names"] = used_names
    config["used_pics"] = used_pics

    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4, ensure_ascii=False)
        
if __name__ == "__main__":
    asyncio.run(update_dp_and_name())
