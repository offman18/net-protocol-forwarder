import os
import asyncio
import json
import re
import requests
import traceback
from telethon import TelegramClient
from telethon.sessions import StringSession

# ==========================================
# 🔌 NET PROTOCOL SYNC CORE (v2.3 Auto-Heal)
# ==========================================

# 1. שליפה וניקוי ראשוני
RAW_AUTH = os.environ.get('SYS_AUTH_TOKEN', '')

# 🧹 סניטציה אגרסיבית: מחיקת רווחים, אנטרים וטאבים שאולי נכנסו בטעות
CLEAN_AUTH = "".join(RAW_AUTH.split())

# 🧮 תיקון פאדינג מתמטי (Force Padding)
pad_needed = len(CLEAN_AUTH) % 4
if pad_needed != 0:
    CLEAN_AUTH += '=' * (4 - pad_needed)

NET_CFG = {
    'nid': int(os.environ.get('SYS_NODE_ID', 0)),
    'hash': os.environ.get('SYS_NODE_HASH', ''),
    'auth': CLEAN_AUTH, # משתמשים במחרוזת המתוקנת
    'target': os.environ.get('REMOTE_HOST_REF', ''),
    'telemetry': os.environ.get('TELEMETRY_ENDPOINT', ''),
    'webhook': os.environ.get('SYNC_ENDPOINT', ''),
    'payload': os.environ.get('INCOMING_BLOB', '')
}

print(f"[DEBUG] Raw Key Length: {len(RAW_AUTH)}")
print(f"[DEBUG] Clean Key Length: {len(NET_CFG['auth'])} (Padding Added: {4 - pad_needed if pad_needed else 0})")

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
        print("[SYS] Initializing socket...")
        
        # ניסיון חיבור עם המפתח המתוקן
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
    print("[INIT] Starting protocol v2.3...")
    try:
        asyncio.run(_sync_network_state())
    except Exception as e:
        print(f"[FATAL] Crash: {e}")
    print("[INIT] Starting network sync protocol...")
    try:
        asyncio.run(_sync_network_state())
    except Exception as e:
        print(f"[FATAL] Crash: {e}")
