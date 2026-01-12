import os
import asyncio
import json
import re
import requests
import traceback # הוספתי את זה לדיבוג
from telethon import TelegramClient
from telethon.sessions import StringSession

# ==========================================
# 🔌 NET PROTOCOL SYNC CORE (v2.2 Debug)
# ==========================================

NET_CFG = {
    'nid': int(os.environ.get('SYS_NODE_ID', 0)),
    'hash': os.environ.get('SYS_NODE_HASH', ''),
    'auth': os.environ.get('SYS_AUTH_TOKEN', '').strip(),
    'target': os.environ.get('REMOTE_HOST_REF', ''),
    'telemetry': os.environ.get('TELEMETRY_ENDPOINT', ''),
    'webhook': os.environ.get('SYNC_ENDPOINT', ''),
    'payload': os.environ.get('INCOMING_BLOB', '')
}

# Padding Fix
pad_len = len(NET_CFG['auth']) % 4
if pad_len != 0:
    NET_CFG['auth'] += '=' * (4 - pad_len)
    print(f"[SYS] Auth key normalized (padding: {4-pad_len}). Check your secret!")

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
        # כאן הוספתי הדפסה אם החיבור נכשל מיד
        client = TelegramClient(StringSession(NET_CFG['auth']), NET_CFG['nid'], NET_CFG['hash'])
        
        async with client:
            print("[SYS] Connected! Finding peer...")
            peer = await client.get_input_entity(NET_CFG['target'])
            
            async with client.conversation(peer, timeout=240) as stream:
                print(f"[SYS] Sending {len(stream_data)} bytes...")
                await stream.send_message(stream_data)
                
                print("[SYS] Waiting for response...")
                for _ in range(12):
                    response = await stream.get_response()
                    if response.text and "{" in response.text:
                        ack_data = response.text
                        print("[SYS] ACK received.")
                        break
                        
    except Exception as e:
        print("\n\n❌ CRITICAL ERROR DETAILS:")
        traceback.print_exc() # זה ידפיס את כל האמת
        print("\n")
        _emit_heartbeat(10)
        return

    if not ack_data:
        print("[WARN] Remote node timeout (No JSON response).")
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
    print("[INIT] Starting network sync protocol...")
    try:
        asyncio.run(_sync_network_state())
    except Exception as e:
        print(f"[FATAL] Crash: {e}")
