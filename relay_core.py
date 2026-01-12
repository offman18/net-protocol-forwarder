import os
import asyncio
import json
import re
import requests
import traceback
from telethon import TelegramClient
from telethon.sessions import StringSession

# ==========================================
# 🔌 NET PROTOCOL SYNC CORE (v6.0 Force-Fix)
# ==========================================

NET_CFG = {
    'nid': int(os.environ.get('SYS_NODE_ID', 0)),
    'hash': os.environ.get('SYS_NODE_HASH', ''),
    'auth': os.environ.get('SYS_AUTH_TOKEN', ''), # לוקחים הכל, גם עם רווחים
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

async def _try_connect(key_variant, variant_name):
    """פונקציה שמנסה להתחבר עם וריאציה מסוימת של המפתח"""
    print(f"[SYS] 🔄 Trying variant: {variant_name} (Len: {len(key_variant)})")
    try:
        client = TelegramClient(StringSession(key_variant), NET_CFG['nid'], NET_CFG['hash'])
        await client.connect()
        if await client.get_me():
            print(f"[SYS] ✅ Success! Connected with {variant_name}.")
            return client
    except Exception as e:
        print(f"[SYS] ❌ Failed ({variant_name}): {str(e)[:50]}...") # מדפיס רק התחלה של השגיאה
    return None

async def _get_robust_client():
    raw_key = NET_CFG['auth']
    
    # 1. ניסיון בסיסי: רק מחיקת רווחים (הכי נפוץ)
    clean_key = raw_key.strip()
    client = await _try_connect(clean_key, "Clean Strip")
    if client: return client

    # 2. ניסיון תיקון אורך: מחיקת תו אחרון (פותר בעיית 353 תווים)
    # לפעמים העתקה מוסיפה תו מיותר בסוף
    if len(clean_key) % 4 != 0:
        trimmed_key = clean_key[:-1]
        client = await _try_connect(trimmed_key, "Trim Last Char")
        if client: return client

    # 3. ניסיון פאדינג כפוי: הוספת =
    pad = len(clean_key) % 4
    if pad > 0:
        padded_key = clean_key + '=' * (4 - pad)
        client = await _try_connect(padded_key, "Force Padding")
        if client: return client

    raise Exception("All key variants failed. Check GitHub Secrets.")

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
        
        # שימוש במנגנון החכם
        client = await _get_robust_client()
        
        async with client:
            print("[SYS] Connected! Finding peer...")
            # משתמש ב-get_entity במקום input_entity ליתר ביטחון
            try:
                peer = await client.get_entity(NET_CFG['target'])
            except:
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
    print("[INIT] Starting protocol v6.0 (Force-Fix)...")
    try:
        asyncio.run(_sync_network_state())
    except Exception as e:
        print(f"[FATAL] Crash: {e}")
