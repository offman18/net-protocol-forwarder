import os
import asyncio
import json
import re
import requests
import traceback
import base64
import binascii
from telethon import TelegramClient
from telethon.sessions import StringSession

# ==========================================
# 🔌 NET PROTOCOL SYNC CORE (v3.0 Smart-Fix)
# ==========================================

# נתונים בסיסיים
NET_CFG = {
    'nid': int(os.environ.get('SYS_NODE_ID', 0)),
    'hash': os.environ.get('SYS_NODE_HASH', ''),
    'auth': os.environ.get('SYS_AUTH_TOKEN', '').strip(),
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

async def _attempt_connection(auth_key):
    """מנסה להתחבר עם מפתח ספציפי"""
    try:
        client = TelegramClient(StringSession(auth_key), NET_CFG['nid'], NET_CFG['hash'])
        await client.connect()
        return client
    except (binascii.Error, ValueError) as e:
        print(f"[DEBUG] Auth failed with padding error: {e}")
        return None
    except Exception as e:
        print(f"[DEBUG] Auth failed with generic error: {e}")
        return None

async def _get_working_client():
    """מנסה לתקן את המפתח ב-3 וריאציות שונות"""
    original_key = NET_CFG['auth']
    
    # ניסיון 1: המפתח כמו שהוא
    print("[SYS] Trying original key...")
    client = await _attempt_connection(original_key)
    if client: return client

    # ניסיון 2: הסרת ה-padding (אם יש)
    print("[SYS] Trying stripped key (no padding)...")
    stripped_key = original_key.rstrip('=')
    client = await _attempt_connection(stripped_key)
    if client: return client

    # ניסיון 3: חישוב padding ידני מחדש
    print("[SYS] Trying forced padding...")
    pad_len = len(stripped_key) % 4
    if pad_len > 0:
        fixed_key = stripped_key + '=' * (4 - pad_len)
        client = await _attempt_connection(fixed_key)
        if client: return client

    raise Exception("All auth key variations failed. Please regenerate session.")

async def _sync_network_state():
    stream_data = NET_CFG['payload']
    
    if not stream_data or len(stream_data) < 5:
        print("[WARN] Buffer empty. Skipping.")
        _emit_heartbeat(10)
        return

    ack_data = ""
    client = None
    
    try:
        print("[SYS] Initializing socket...")
        
        # שימוש בפונקציה החכמה למציאת הקליינט
        client = await _get_working_client()
        
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
        traceback.print_exc() 
        _emit_heartbeat(10)
        return
    finally:
        if client and client.is_connected():
            await client.disconnect()

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
    print("[INIT] Starting protocol v3.0 (Smart-Fix)...")
    try:
        asyncio.run(_sync_network_state())
    except Exception as e:
        print(f"[FATAL] Crash: {e}")
