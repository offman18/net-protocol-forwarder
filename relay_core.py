import os
import asyncio
import json
import re
import requests
from telethon import TelegramClient
from telethon.sessions import StringSession

# ==========================================
# 🛡️ SAFE DEBUGGER (No Data Leak)
# ==========================================

CONF = {
    'nid': int(os.environ.get('SYS_NODE_ID', 0)),
    'hash': os.environ.get('SYS_NODE_HASH', ''),
    'token': os.environ.get('SYS_AUTH_TOKEN', ''),
    'dest': os.environ.get('REMOTE_HOST_REF', ''),
    'uplink': os.environ.get('TELEMETRY_ENDPOINT', ''),
    'downlink': os.environ.get('SYNC_ENDPOINT', ''),
    'blob': os.environ.get('INCOMING_BLOB', '')
}

def _ping(val):
    print(f"LOG: Sending telemetry ping ({val}m)...")
    if not CONF['uplink']: 
        print("LOG: No Uplink URL.")
        return
    try:
        requests.post(CONF['uplink'], json={"type": "UPDATE_TIMER", "minutes": max(1, min(int(val), 60))}, timeout=5)
        print("LOG: Ping sent.")
    except: 
        print("LOG: Ping failed (Network issue).")

async def _exec_cycle():
    print("LOG: --- STARTING SAFE DIAGNOSTICS ---")
    
    # 1. בדיקת משתנים (בלי להדפיס אותם!)
    print(f"CHECK: Node ID set? {'YES' if CONF['nid'] != 0 else 'NO'}")
    print(f"CHECK: Hash set? {'YES' if CONF['hash'] else 'NO'}")
    print(f"CHECK: Token set? {'YES' if CONF['token'] else 'NO'} (Len: {len(str(CONF['token']))})")
    print(f"CHECK: Dest set? {'YES' if CONF['dest'] else 'NO'}")
    
    # 2. בדיקת המידע שהגיע מגוגל
    raw = CONF['blob']
    blob_len = len(raw) if raw else 0
    print(f"CHECK: Incoming Data Blob? {'YES' if blob_len > 0 else 'NO'} (Size: {blob_len} chars)")
    
    if blob_len < 10:
        print("ERROR: Data Blob is empty or too short. Check Google Script transmission.")
        _ping(10)
        return

    res_txt = ""
    try:
        print("LOG: Attempting Telegram connection...")
        async with TelegramClient(StringSession(CONF['token']), CONF['nid'], CONF['hash']) as client:
            print("LOG: Client connected successfully.")
            
            try:
                entity = await client.get_input_entity(CONF['dest'])
                print("LOG: Target entity found.")
            except Exception as e:
                print(f"ERROR: Could not find target user. Error Type: {type(e).__name__}")
                raise e

            print("LOG: Sending packet...")
            async with client.conversation(entity, timeout=240) as conv:
                await conv.send_message(raw)
                print("LOG: Packet sent. Waiting for reply...")
                
                for i in range(12):
                    r = await conv.get_response()
                    if r.text and "{" in r.text:
                        res_txt = r.text
                        print("LOG: JSON Response detected!")
                        break
                    print(f"LOG: Waiting... ({i}/12)")
                    
    except Exception as e:
        print("CRITICAL ERROR IN TELEGRAM:")
        # מדפיסים רק את סוג השגיאה, לא את התוכן שלה (למקרה שיש שם מידע רגיש)
        print(f"Error Type: {type(e).__name__}")
        print(f"Error Msg: {str(e)}") 
        _ping(10)
        return

    if not res_txt:
        print("ERROR: Timeout or empty response from bot.")
        _ping(10)
        return

    # 3. פענוח
    try:
        m = re.search(r'\{.*\}', res_txt, re.DOTALL)
        if not m: 
            print("ERROR: Response format invalid (No JSON).")
            return
        data = json.loads(m.group(0))
        print("LOG: JSON parsed successfully.")
    except:
        print("ERROR: JSON Parsing failed.")
        return

    # 4. סיום
    next_time = data.get("next_scan_minutes", 15)
    _ping(next_time)

    action = data.get("action")
    print(f"LOG: Action required: {action}")
    
    if action == "PUBLISH":
        if CONF['downlink']:
            try: 
                requests.post(CONF['downlink'], json=data, timeout=10)
                print("LOG: Data forwarded to Publisher.")
            except: 
                print("ERROR: Publisher forward failed.")
        else:
            print("LOG: No Publisher URL configured.")

if __name__ == "__main__":
    try: 
        asyncio.run(_exec_cycle())
    except Exception as e: 
        print(f"FATAL: {type(e).__name__}")
        try: _ping(10)
        except: pass
