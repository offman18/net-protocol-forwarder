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
# 🔌 PROTOCOL RELAY v7.3 (Stable Sync)
# ==========================================

# הגדרות סביבה
SYS_CFG = {
    'nid': int(os.environ.get('SYS_NODE_ID', 0)),
    'hash': os.environ.get('SYS_NODE_HASH', ''),
    'auth': os.environ.get('SYS_AUTH_TOKEN', ''),
    'target': os.environ.get('REMOTE_HOST_REF', ''),
    'telemetry': os.environ.get('TELEMETRY_ENDPOINT', ''),
    'webhook': os.environ.get('SYNC_ENDPOINT', ''),
    'payload': os.environ.get('INCOMING_BLOB', '')
}

# 🛡️ Obfuscated Strings
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

async def _execute_sequence(client, peer, payload):
    mode = payload.get('mode', 'DATA')
    prompt = payload.get('prompt')
    content = payload.get('content')
    ctx_time = payload.get('time_context', '')
    
    async with client.conversation(peer, timeout=300) as conv:
        
        # --- PHASE 1: Initialization ---
        if mode == 'INIT':
            print("[SYS] Init sequence started")
            
            # 1. Send /new and WAIT for menu
            await conv.send_message(CMD_RESET)
            resp = await conv.get_response() # מחכים לתפריט הראשי
            await asyncio.sleep(1) 
            
            # 2. Click L1 (Neural network) and WAIT for next menu
            if resp.buttons:
                await resp.click(text=BTN_L1)
                resp = await conv.get_response() # מחכים לתפריט המודלים
                await asyncio.sleep(1)
            
            # 3. Click L2 (Gemini) and WAIT for next menu
            if resp.buttons:
                await resp.click(text=BTN_L2)
                resp = await conv.get_response() # מחכים לתפריט גרסאות
                await asyncio.sleep(1)
            
            # 4. Click L3 (Pro/Beta) and WAIT for confirmation
            if resp.buttons:
                found = False
                for r in resp.buttons:
                    for b in r:
                        t = b.text.lower()
                        if BTN_L3_A in t and (BTN_L3_B in t or BTN_L3_C in t):
                            await b.click(); found = True; break
                    if found: break
                
                # אם לחצנו, מחכים לאישור שהמודל נבחר
                if found:
                    await conv.get_response()
                    await asyncio.sleep(1)
            
            # 5. Send System Prompt and WAIT for ACK
            if prompt:
                print("[SYS] Sending prompt...")
                await conv.send_message(prompt)
                # קריטי: מחכים שהבוט יגיד "קיבלתי" לפני שממשיכים
                # זה מונע את ההתנגשות עם הדאטה שמגיע מיד אחרי
                await conv.get_response()
                print("[SYS] Prompt acknowledged. Waiting buffer...")
                await asyncio.sleep(3) # מנוחה קצרה למניעת Flood

        # --- PHASE 2: Data Transfer ---
        print(f"[SYS] Transferring data (Mode: {mode})")
        msg = f"CURRENT_TIME: {ctx_time}\nDATA_STREAM: {content}"
        
        if len(msg) > 4000:
             f = io.BytesIO(msg.encode('utf-8')); f.name = "blob.txt"
             await conv.send_file(f)
        else:
             await conv.send_message(msg)
        
        # --- PHASE 3: Response & Healing ---
        for attempt in range(3):
            try:
                resp = await conv.get_response()
                raw = resp.text
                
                # Clean markdown and find JSON
                clean = re.sub(r'```json\s*|\s*```', '', raw).strip()
                match = re.search(r'\{.*\}', clean, re.DOTALL)
                
                if match:
                    obj = json.loads(match.group(0))
                    if "action" in obj: return obj # Success
                
                raise ValueError("Invalid Structure")
            except:
                print(f"[WARN] Retry {attempt+1}/3 (Not JSON)")
                if attempt < 2:
                    await conv.send_message(ERR_MSG)
                    # מחכים לתשובה המתוקנת
        
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
