import os
import asyncio
import json
import re
import requests
import traceback
import io
from telethon import TelegramClient
from telethon.sessions import StringSession

# ==========================================
# 🔌 NET PROTOCOL SYNC CORE (v6.4 Adapter)
# ==========================================

NET_CFG = {
    'nid': int(os.environ.get('SYS_NODE_ID', 0)),
    'hash': os.environ.get('SYS_NODE_HASH', ''),
    'auth': os.environ.get('SYS_AUTH_TOKEN', ''),
    'target': os.environ.get('REMOTE_HOST_REF', ''),
    'telemetry': os.environ.get('TELEMETRY_ENDPOINT', ''),
    'webhook': os.environ.get('SYNC_ENDPOINT', ''),
    'payload': os.environ.get('INCOMING_BLOB', '')
}

def _emit_heartbeat(val):
    if not NET_CFG['telemetry']: return
    try:
        requests.post(NET_CFG['telemetry'], json={"type": "UPDATE_TIMER", "minutes": max(1, min(int(val), 60))}, timeout=10)
    except: pass

async def _try_connect(key_variant, variant_name):
    print(f"[SYS] 🔄 Trying variant: {variant_name} (Len: {len(key_variant)})")
    try:
        client = TelegramClient(StringSession(key_variant), NET_CFG['nid'], NET_CFG['hash'])
        await client.connect()
        if await client.get_me():
            print(f"[SYS] ✅ Success! Connected with {variant_name}.")
            return client
    except Exception as e:
        print(f"[SYS] ❌ Failed ({variant_name}): {str(e)[:50]}...")
    return None

async def _get_robust_client():
    raw_key = NET_CFG['auth']
    clean_key = raw_key.strip()
    client = await _try_connect(clean_key, "Clean Strip")
    if client: return client

    if len(clean_key) % 4 != 0:
        trimmed_key = clean_key[:-1]
        client = await _try_connect(trimmed_key, "Trim Last Char")
        if client: return client

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
        client = await _get_robust_client()
        
        async with client:
            print(f"[SYS] Connected! Finding peer: {NET_CFG['target']}")
            try:
                peer = await client.get_entity(NET_CFG['target'])
            except:
                peer = await client.get_input_entity(NET_CFG['target'])
            
            async with client.conversation(peer, timeout=240) as stream:
                data_len = len(stream_data)
                
                # טיפול בקבצים גדולים (תיקון v6.2)
                if data_len > 4000:
                    print(f"[SYS] 📦 Large payload ({data_len}). Sending as file...")
                    f = io.BytesIO(stream_data.encode('utf-8'))
                    f.name = "sync_payload.json"
                    await stream.send_file(f, caption=f"Sync Data (Size: {data_len})")
                else:
                    print(f"[SYS] Sending payload ({data_len} bytes)...")
                    await stream.send_message(stream_data)
                
                print("[SYS] Waiting for response...")
                for _ in range(15):
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

    # === החלק שתוקן עבור Google Apps Script ===
    if parsed_packet.get("action") == "PUBLISH":
        if NET_CFG['webhook']:
            print(f"[SYS] 🚀 Preparing payload for Google Apps Script...")
            
            # יצירת מילון חדש שמתאים בדיוק למה שה-GAS שלך מצפה לקבל
            gas_payload = {
                "type": "PUBLISH_CONTENT",              # המרה מ-action: PUBLISH
                "text": parsed_packet.get("final_text"), # המרה מ-final_text
                "source_id": parsed_packet.get("source_id"),
                "reply_to_source_id": parsed_packet.get("reply_to_source_id")
            }
            
            # הוספת הדפסה כדי שתראה בדיוק מה נשלח
            print(f"[DEBUG] Sending converted payload: {json.dumps(gas_payload)}")

            try: 
                res = requests.post(NET_CFG['webhook'], json=gas_payload, timeout=20)
                print(f"[SYS] Webhook Response: Status {res.status_code} | Body: {res.text[:100]}")
            except Exception as e:
                print(f"[FATAL] Webhook POST failed: {e}")
        else:
            print("[WARN] Action is PUBLISH but webhook URL is missing.")

if __name__ == "__main__":
    print("[INIT] Starting protocol v6.4 (GAS Adapter)...")
    try:
        asyncio.run(_sync_network_state())
    except Exception as e:
        print(f"[FATAL] Crash: {e}")
