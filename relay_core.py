import os
import asyncio
import json
import re
import requests
import traceback
import io
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import TimeoutError as TelethonTimeout

# ==========================================
# 🔌 NET PROTOCOL v6.6 - Smart Recovery
# ==========================================

NET_CFG = {
    'nid': int(os.environ.get('SYS_NODE_ID', 0)),
    'hash': os.environ.get('SYS_NODE_HASH', ''),
    'auth': os.environ.get('SYS_AUTH_TOKEN', ''),
    'target': os.environ.get('REMOTE_HOST_REF', ''),
    'telemetry': os.environ.get('TELEMETRY_ENDPOINT', ''),
    'webhook': os.environ.get('SYNC_ENDPOINT', ''),
    'payload': os.environ.get('INCOMING_BLOB', ''),
    'failure_file': '/tmp/failure_count.txt'  # קובץ זמני לספירת כשלונות
}

# הגדרות
MAX_CONSECUTIVE_FAILURES = 3  # כמה כשלונות רצופים עד reset מלא
CONVERSATION_TIMEOUT = 240

def _emit_heartbeat(val):
    if not NET_CFG['telemetry']: return
    try:
        requests.post(NET_CFG['telemetry'], json={"type": "UPDATE_TIMER", "minutes": max(1, min(int(val), 60))}, timeout=10)
    except: pass

def _get_failure_count():
    """קורא את מספר הכשלונות הרצופים"""
    try:
        if os.path.exists(NET_CFG['failure_file']):
            with open(NET_CFG['failure_file'], 'r') as f:
                return int(f.read().strip())
    except:
        pass
    return 0

def _increment_failure():
    """מגדיל את מונה הכשלונות"""
    count = _get_failure_count() + 1
    try:
        with open(NET_CFG['failure_file'], 'w') as f:
            f.write(str(count))
    except:
        pass
    return count

def _reset_failure_count():
    """מאפס את המונה אחרי הצלחה"""
    try:
        if os.path.exists(NET_CFG['failure_file']):
            os.remove(NET_CFG['failure_file'])
    except:
        pass

async def _try_connect(key_variant, variant_name):
    print(f"[SYS] 🔄 Trying variant: {variant_name}")
    try:
        client = TelegramClient(StringSession(key_variant), NET_CFG['nid'], NET_CFG['hash'])
        await client.connect()
        if await client.get_me():
            print(f"[SYS] ✅ Connected with {variant_name}")
            return client
    except Exception as e:
        print(f"[SYS] ❌ Failed ({variant_name}): {str(e)[:50]}")
    return None

async def _get_robust_client():
    raw_key = NET_CFG['auth']
    clean_key = raw_key.strip()
    
    for variant_name, key in [
        ("Clean", clean_key),
        ("Trimmed", clean_key[:-1] if len(clean_key) % 4 != 0 else None),
        ("Padded", clean_key + '=' * (4 - len(clean_key) % 4) if len(clean_key) % 4 > 0 else None)
    ]:
        if key:
            client = await _try_connect(key, variant_name)
            if client: return client
    
    raise Exception("All connection variants failed")

# ⭐ פונקציית Recovery מלאה
async def _full_bot_reset(client, peer):
    """
    רצף מלא: /new → Neural network → Gemini → gemini 3 pro [beta] → Create
    """
    print("[RECOVERY] 🔄 Starting FULL bot reset...")
    
    try:
        # שלב 1: /new
        await client.send_message(peer, '/new')
        await asyncio.sleep(3)
        
        # שלב 2: Neural network
        msgs = await client.get_messages(peer, limit=1)
        if msgs and msgs[0].buttons:
            print("[RECOVERY] 🧠 → Neural network")
            await msgs[0].click(text='Neural network')
            await asyncio.sleep(3)
        else:
            return False
        
        # שלב 3: Gemini
        msgs = await client.get_messages(peer, limit=1)
        if msgs and msgs[0].buttons:
            print("[RECOVERY] 💎 → Gemini")
            await msgs[0].click(text='Gemini')
            await asyncio.sleep(3)
        else:
            return False
        
        # שלב 4: gemini 3 pro [beta]
        msgs = await client.get_messages(peer, limit=1)
        if msgs and msgs[0].buttons:
            print("[RECOVERY] 🚀 → gemini 3 pro [beta]")
            clicked = False
            for row in msgs[0].buttons:
                for btn in row:
                    if 'gemini' in btn.text.lower() and ('pro' in btn.text.lower() or 'beta' in btn.text.lower()):
                        await btn.click()
                        clicked = True
                        break
                if clicked: break
            
            if not clicked:
                return False
            await asyncio.sleep(3)
        
        # שלב 5: Create -->
        msgs = await client.get_messages(peer, limit=1)
        if msgs and msgs[0].buttons:
            print("[RECOVERY] ➡️ → Create")
            clicked = False
            for row in msgs[0].buttons:
                for btn in row:
                    if 'create' in btn.text.lower() or '-->' in btn.text:
                        await btn.click()
                        clicked = True
                        break
                if clicked: break
            
            if not clicked:
                return False
            await asyncio.sleep(3)
        
        print("[RECOVERY] ✅ Full reset completed successfully!")
        return True
        
    except Exception as e:
        print(f"[RECOVERY] ❌ Reset error: {e}")
        return False

async def _sync_network_state():
    stream_data = NET_CFG['payload']
    
    if not stream_data or len(stream_data) < 5:
        print("[WARN] Empty payload, skipping")
        _emit_heartbeat(10)
        return

    # ⭐ בדיקת מונה כשלונות
    failure_count = _get_failure_count()
    print(f"[SYS] Consecutive failures: {failure_count}/{MAX_CONSECUTIVE_FAILURES}")
    
    client = None
    ack_data = ""
    
    try:
        print("[SYS] Connecting...")
        client = await _get_robust_client()
        
        async with client:
            print(f"[SYS] Peer: {NET_CFG['target']}")
            try:
                peer = await client.get_entity(NET_CFG['target'])
            except:
                peer = await client.get_input_entity(NET_CFG['target'])
            
            # ⭐ אם יש יותר מדי כשלונות - עשה reset מלא
            if failure_count >= MAX_CONSECUTIVE_FAILURES:
                print(f"[ALERT] 🚨 {failure_count} failures detected! Forcing full reset...")
                reset_ok = await _full_bot_reset(client, peer)
                if reset_ok:
                    print("[RECOVERY] ✅ Reset successful, clearing counter")
                    _reset_failure_count()
                else:
                    print("[RECOVERY] ⚠️ Reset incomplete")
            
            # ניסיון שליחה רגיל
            try:
                async with client.conversation(peer, timeout=CONVERSATION_TIMEOUT) as stream:
                    data_len = len(stream_data)
                    
                    if data_len > 4000:
                        print(f"[SYS] 📦 Sending file ({data_len} bytes)")
                        f = io.BytesIO(stream_data.encode('utf-8'))
                        f.name = "sync_payload.json"
                        await stream.send_file(f, caption=f"Sync ({data_len})")
                    else:
                        print(f"[SYS] 📤 Sending text ({data_len} bytes)")
                        await stream.send_message(stream_data)
                    
                    print("[SYS] ⏳ Waiting for response...")
                    for _ in range(15):
                        response = await stream.get_response()
                        if response.text and "{" in response.text:
                            ack_data = response.text
                            print("[SYS] ✅ Response received!")
                            _reset_failure_count()  # איפוס אחרי הצלחה
                            break
                    
            except TelethonTimeout:
                fail_num = _increment_failure()
                print(f"[WARN] ⏱️ Timeout! Failure #{fail_num}")
                _emit_heartbeat(10)
                return
                
    except Exception as e:
        print(f"[ERROR] {e}")
        traceback.print_exc()
        _increment_failure()
        _emit_heartbeat(10)
        return
    finally:
        if client and client.is_connected():
            await client.disconnect()

    if not ack_data:
        print("[WARN] No valid response")
        _emit_heartbeat(10)
        return

    # עיבוד תשובה
    try:
        match = re.search(r'\{.*\}', ack_data, re.DOTALL)
        if not match: return
        parsed_packet = json.loads(match.group(0))
    except:
        return

    next_sync = parsed_packet.get("next_scan_minutes", 15)
    _emit_heartbeat(next_sync)

    # פרסום ל-Google Apps Script
    if parsed_packet.get("action") == "PUBLISH":
        if NET_CFG['webhook']:
            gas_payload = {
                "type": "PUBLISH_CONTENT",
                "text": parsed_packet.get("final_text"),
                "source_id": parsed_packet.get("source_id"),
                "reply_to_source_id": parsed_packet.get("reply_to_source_id")
            }
            
            try: 
                res = requests.post(NET_CFG['webhook'], json=gas_payload, timeout=20)
                print(f"[WEBHOOK] {res.status_code} | {res.text[:100]}")
            except Exception as e:
                print(f"[WEBHOOK] Error: {e}")

if __name__ == "__main__":
    print("[INIT] Protocol v6.6 - Smart Recovery")
    try:
        asyncio.run(_sync_network_state())
    except Exception as e:
        print(f"[FATAL] {e}")
