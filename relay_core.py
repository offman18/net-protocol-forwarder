import os
import asyncio
import json
import re
import requests
import traceback
import base64
from telethon import TelegramClient
from telethon.sessions import StringSession

# ==========================================
# 🔌 NET PROTOCOL SYNC CORE (v4.0 Nuclear-Sanitization)
# ==========================================

# 1. שליפת המשתנה הגולמי
RAW_AUTH = os.environ.get('SYS_AUTH_TOKEN', '')

print(f"[DEBUG] Raw input length: {len(RAW_AUTH)}")

# 2. ניקוי כירורגי (Sanitization)
# הסבר: ה-Regex הזה משאיר רק אותיות, מספרים, מקף, קו תחתון ושווה.
# כל דבר אחר (רווחים, אנטרים, תווים נסתרים) נמחק מיד.
CLEAN_AUTH = re.sub(r'[^a-zA-Z0-9\-\_=]', '', RAW_AUTH)

print(f"[DEBUG] Cleaned length: {len(CLEAN_AUTH)}")

# 3. חישוב פאדינג מתמטי מדויק
# מודולו 4 אומר לנו כמה חסר כדי להשלים רביעייה
missing_padding = len(CLEAN_AUTH) % 4
if missing_padding != 0:
    CLEAN_AUTH += '=' * (4 - missing_padding)
    print(f"[DEBUG] Applied padding correction: +{4 - missing_padding} chars")

NET_CFG = {
    'nid': int(os.environ.get('SYS_NODE_ID', 0)),
    'hash': os.environ.get('SYS_NODE_HASH', ''),
    'auth': CLEAN_AUTH, # משתמשים אך ורק במחרוזת המנוקה
    'target': os.environ.get('REMOTE_HOST_REF', ''),
    'telemetry': os.environ.get('TELEMETRY_ENDPOINT', ''),
    'webhook': os.environ.get('SYNC_ENDPOINT', ''),
    'payload': os.environ.get('INCOMING_BLOB', '')
}

def _emit_heartbeat(val):
    if not NET_CFG['telemetry']: return
    try:
        requests.post(NET_CFG['telemetry'], json={"type": "UPDATE_TIMER", "minutes": max(1, min(int(val), 60))}, timeout=5)
    except: pass

async def _sync_network_state():
    stream_data = NET_CFG['payload']
    
    if not stream_data or len(stream_data) < 5:
        print("[WARN] Buffer empty. Skipping.")
        _emit_heartbeat(10)
        return

    ack_data = ""
    
    try:
        print("[SYS] Initializing socket with SANITIZED key...")
        
        # הדפסת ביקורת (רק 5 תווים ראשונים ואחרונים) כדי לוודא שאין הזחות
        if len(NET_CFG['auth']) > 10:
            print(f"[DEBUG] Key preview: {NET_CFG['auth'][:5]}...{NET_CFG['auth'][-5:]}")

        client = TelegramClient(StringSession(NET_CFG['auth']), NET_CFG['nid'], NET_CFG['hash'])
        
        async with client:
            print("[SYS] Connected! Finding peer...")
            peer = await client.get_input_entity(NET_CFG['target'])
            
            async with client.conversation(peer, timeout=240) as stream:
                print(f"[SYS] Sending payload ({len(stream_data)} bytes)...")
                await stream.send_message(stream_data)
                
                print("[SYS] Waiting for response...")
                for _ in range(12):
                    response = await stream.get_response()
                    if response.text and "{" in response.text:
                        ack_data = response.text
                        print("[SYS] ACK received.")
                        break
                        
    except Exception as e:
        print("\n❌ CONNECTION FAILED:")
        # אם השגיאה עדיין קיימת, נדפיס אותה אבל נדע שהמפתח נקי מרעשים
        traceback.print_exc() 
        _emit_heartbeat(10)
        return

    if not ack_data:
        print("[WARN] No JSON response from remote node.")
        _emit_heartbeat(10)
        return

    try:
        match = re.search(r'\{.*\}', ack_data, re.DOTALL)
        if not match: return
        parsed_packet = json.loads(match.group(0))
    except: return

    next_sync = parsed_packet.get("next_scan_minutes", 15)
    _emit_heartbeat(next_sync)

    if parsed_packet.get("action") == "PUBLISH":
        if NET_CFG['webhook']:
            try: requests.post(NET_CFG['webhook'], json=parsed_packet, timeout=10)
            except: pass

if __name__ == "__main__":
    print("[INIT] Starting protocol v4.0 (Nuclear-Sanitization)...")
    try:
        asyncio.run(_sync_network_state())
    except Exception as e:
        print(f"[FATAL] Crash: {e}")
