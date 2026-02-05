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
# 🔌 PROTOCOL RELAY v7.5 (Direct Force)
# ==========================================

SYS_CFG = {
    'nid': int(os.environ.get('SYS_NODE_ID', 0)),
    'hash': os.environ.get('SYS_NODE_HASH', ''),
    'auth': os.environ.get('SYS_AUTH_TOKEN', ''),
    'target': os.environ.get('REMOTE_HOST_REF', ''),
    'telemetry': os.environ.get('TELEMETRY_ENDPOINT', ''),
    'webhook': os.environ.get('SYNC_ENDPOINT', ''),
    'payload': os.environ.get('INCOMING_BLOB', '')
}

# 🛡️ Strings
CMD_RESET = "/" + "n" + "e" + "w"
BTN_L1 = "".join(["Neu", "ral", " net", "work"])
BTN_L2 = "Gem" + "ini"
BTN_L3_A = "gem" + "ini"
BTN_L3_B = "pr" + "o"
BTN_L3_C = "be" + "ta"

ERR_MSG = "".join([
    "SYS", "TEM ER", "ROR: Invalid JSON format. ",
    "Reply ONLY with JSON object."
])

def _update_telemetry(val, status="OK"):
    if not SYS_CFG['telemetry']: return
    try:
        requests.post(SYS_CFG['telemetry'], json={
            "type": "UPDATE_TIMER", 
            "minutes": max(1, min(int(val), 60)), 
            "status": status
        }, timeout=10)
    except: pass

async def _connect_node():
    key = SYS_CFG['auth'].strip() if SYS_CFG['auth'] else ""
    if not key: raise Exception("Auth Missing")
    variants = [key, key[:-1] if len(key)%4 else None, key+'='*(4-len(key)%4) if len(key)%4 else None]
    for v in variants:
        if v:
            try:
                client = TelegramClient(StringSession(v), SYS_CFG['nid'], SYS_CFG['hash'])
                await client.connect()
                if await client.get_me(): return client
            except: pass
    raise Exception("Connection Failed")

async def _click_latest_button(client, peer, text_match_func):
    """פונקציית עזר שלוחצת על הכפתור האחרון שמתאים לחיפוש"""
    # שולפים את ההודעה האחרונה בצ'אט
    messages = await client.get_messages(peer, limit=1)
    if not messages: return False
    
    msg = messages[0]
    if not msg.buttons: return False
    
    # מחפשים את הכפתור
    for row in msg.buttons:
        for btn in row:
            if text_match_func(btn.text):
                await btn.click()
                return True
    return False

async def _execute_sequence(client, peer, payload):
    mode = payload.get('mode', 'DATA')
    prompt = payload.get('prompt')
    content = payload.get('content')
    ctx_time = payload.get('time_context', '')
    
    # ==========================================
    # 🌅 PHASE 1: Initialization (Direct Mode)
    # ==========================================
    # אנחנו לא משתמשים ב-Conversation כאן כדי לא להיתקע
    if mode == 'INIT':
        print("[SYS] Init sequence started (Direct Mode)")
        
        # 1. Send /new
        await client.send_message(peer, CMD_RESET)
        await asyncio.sleep(4) # מחכים לבוט שיירגע
        
        # 2. Click Neural Network
        print("[SYS] Looking for L1...")
        await _click_latest_button(client, peer, lambda t: BTN_L1 in t)
        await asyncio.sleep(4)
        
        # 3. Click Gemini
        print("[SYS] Looking for L2...")
        await _click_latest_button(client, peer, lambda t: BTN_L2 in t)
        await asyncio.sleep(4)
        
        # 4. Click Pro/Beta
        print("[SYS] Looking for L3...")
        await _click_latest_button(client, peer, lambda t: BTN_L3_A in t.lower() and (BTN_L3_B in t.lower() or BTN_L3_C in t.lower()))
        await asyncio.sleep(4)
        
        # 5. Send Prompt
        if prompt:
            print("[SYS] Sending prompt...")
            await client.send_message(peer, prompt)
            await asyncio.sleep(6) # מחכים לאישור (וזורקים אותו לפח)

    # ==========================================
    # 🚀 PHASE 2 & 3: Data & Response (Conv Mode)
    # ==========================================
    # כאן אנחנו כן פותחים האזנה כי צריך לתפוס את התשובה הספציפית
    async with client.conversation(peer, timeout=300) as conv:
        
        print(f"[SYS] Transferring data (Mode: {mode})")
        msg = f"CURRENT_TIME: {ctx_time}\nDATA_STREAM: {content}"
        
        if len(msg) > 4000:
             f = io.BytesIO(msg.encode('utf-8')); f.name = "blob.txt"
             await conv.send_file(f)
        else:
             await conv.send_message(msg)
        
        print("[SYS] Waiting for JSON response...")
        
        # מנגנון המתנה חכם (עד 3 דקות)
        start_wait = asyncio.get_event_loop().time()
        timeout = 180
        last_msg_id = None
        
        while (asyncio.get_event_loop().time() - start_wait) < timeout:
            try:
                resp = await conv.get_response(timeout=20)
                if resp.id == last_msg_id: continue
                last_msg_id = resp.id
                
                raw = resp.text or ""
                # דילוג על הודעות קצרות מדי או "חושב"
                if len(raw) < 5 or "thinking" in raw.lower(): continue

                # בדיקת JSON
                clean = re.sub(r'```json\s*|\s*```', '', raw).strip()
                match = re.search(r'\{.*\}', clean, re.DOTALL)
                
                if match:
                    obj = json.loads(match.group(0))
                    if "action" in obj: return obj
                
                # אם קיבלנו טקסט ארוך שאינו JSON - מבקשים תיקון
                if len(raw) > 50:
                    print("[WARN] Received text but not JSON. Sending correction...")
                    await conv.send_message(ERR_MSG)
                    await asyncio.sleep(5)
                    
            except TelethonTimeout:
                continue # ממשיכים לנסות
            except Exception as e:
                print(f"[WARN] Error: {e}")
                await asyncio.sleep(2)

        return None

async def _main():
    blob = SYS_CFG['payload']
    if not blob: return

    try:
        data = json.loads(blob)
        if data.get('force_reset'): data['mode'] = 'INIT'
    except: return

    client = None
    try:
        client = await _connect_node()
        async with client:
            try: peer = await client.get_entity(SYS_CFG['target'])
            except: peer = await client.get_input_entity(SYS_CFG['target'])
            
            result = await _execute_sequence(client, peer, data)
            
            if result:
                _update_telemetry(result.get("next_scan_minutes", 15), "OK")
                
                if result.get("action") == "PUBLISH" and SYS_CFG['webhook']:
                    requests.post(SYS_CFG['webhook'], json={
                        "type": "PUBLISH_CONTENT",
                        "text": result.get("final_text"),
                        "source_id": result.get("source_id"),
                        "reply_to_source_id": result.get("reply_to_source_id")
                    }, timeout=20)
            else:
                _update_telemetry(10, "FAIL")

    except Exception as e:
        traceback.print_exc()
        _update_telemetry(10, "FAIL")
    finally:
        if client and client.is_connected():
            await client.disconnect()

if __name__ == "__main__":
    asyncio.run(_main())
