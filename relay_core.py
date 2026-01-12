import os
import asyncio
import json
import re
import requests
import traceback
from telethon import TelegramClient
from telethon.sessions import StringSession

# ==========================================
# 🔌 NET PROTOCOL SYNC CORE (v6.1 Debug)
# ==========================================

NET_CFG = {
    'nid': int(os.environ.get('SYS_NODE_ID', 0)),
    'hash': os.environ.get('SYS_NODE_HASH', ''),
    'auth': os.environ.get('SYS_AUTH_TOKEN', ''),
    'target': os.environ.get('REMOTE_HOST_REF', ''),
    'telemetry': os.environ.get('TELEMETRY_ENDPOINT', ''),
    'webhook': os.environ.get('SYNC_ENDPOINT', ''), # המפרסם שלך
    'payload': os.environ.get('INCOMING_BLOB', '')
}

def _emit_heartbeat(val):
    if not NET_CFG['telemetry']: return
    try:
        requests.post(NET_CFG['telemetry'], json={"type": "UPDATE_TIMER", "minutes": max(1, min(int(val), 60))}, timeout=5)
    except Exception as e:
        print(f"[WARN] Telemetry failed: {e}")

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
            except ValueError:
                # ניסיון גיבוי למקרה שהמשתמש לא ב-Cache
                peer = await client.get_input_entity(NET_CFG['target'])
            
            async with client.conversation(peer, timeout=240) as stream:
                print(f"[SYS] Sending payload ({len(stream_data)} bytes)...")
                await stream.send_message(stream_data)
                
                print("[SYS] Waiting for response...")
                # הגדלנו מעט את הטווח כדי לתפוס הודעות מרובות
                for _ in range(15):
                    response = await stream.get_response()
                    print(f"[DEBUG] Msg received: {response.text[:50]}...") # הדפסת דיבאג
                    if response.text and "{" in response.text:
                        ack_data = response.text
                        print("[SYS] ACK received (JSON detected).")
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

    # === ניתוח ועיבוד המידע ===
    try:
        match = re.search(r'\{.*\}', ack_data, re.DOTALL)
        if not match: 
            print("[ERR] Regex failed to find JSON object.")
            return
        
        parsed_packet = json.loads(match.group(0))
        print(f"[DEBUG] Parsed Packet: {json.dumps(parsed_packet)}") # נראה מה קיבלנו
    except Exception as e:
        print(f"[ERR] JSON Parsing failed: {e}")
        return

    next_sync = parsed_packet.get("next_scan_minutes", 15)
    _emit_heartbeat(next_sync)

    # === החלק של המפרסם (Webhook) ===
    received_action = parsed_packet.get("action")
    webhook_url = NET_CFG['webhook']

    if received_action == "PUBLISH":
        if webhook_url:
            print(f"[SYS] 🚀 Publishing to Webhook: {webhook_url}")
            try: 
                # הוספתי הדפסת סטטוס ושגיאות מלאות
                res = requests.post(webhook_url, json=parsed_packet, timeout=15)
                print(f"[SYS] Webhook Response: Status {res.status_code} | Body: {res.text[:100]}")
            except Exception as e:
                print(f"[FATAL] Webhook POST failed: {e}")
                traceback.print_exc()
        else:
            print("[WARN] Action is PUBLISH but 'SYNC_ENDPOINT' (webhook) is empty/missing!")
    else:
        print(f"[INFO] Action received is '{received_action}' (Not 'PUBLISH'). Skipping webhook.")

if __name__ == "__main__":
    print("[INIT] Starting protocol v6.1 (Debug Mode)...")
    try:
        asyncio.run(_sync_network_state())
    except Exception as e:
        print(f"[FATAL] Crash: {e}")
