import os
import asyncio
import json
import re
import requests
import traceback
import io
import time
from telethon import TelegramClient
from telethon.sessions import StringSession

# ==========================================
# 🔌 PROTOCOL RELAY v8.3 (Full Sync Wait)
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

CMD_RESET = "/" + "n" + "e" + "w"
BTN_L1 = "".join(["Neu", "ral", " net", "work"])
BTN_L2 = "Gem" + "ini"
ERR_MSG = "SYSTEM ERROR: Reply ONLY with JSON object."

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
    
    last_error = None
    for v in variants:
        if v:
            try:
                client = TelegramClient(StringSession(v), SYS_CFG['nid'], SYS_CFG['hash'])
                await client.connect()
                if await client.get_me(): return client
            except Exception as e:
                last_error = e
                print(f"[ERR] Login attempt failed: {e}")
                
    raise Exception(f"Connection Failed. Reason: {last_error}")

async def _wait_for_new_message(client, peer, last_msg_id, timeout=180):
    start_time = time.time()
    while (time.time() - start_time) < timeout:
        await asyncio.sleep(5)
        try:
            msgs = await client.get_messages(peer, limit=1)
            if not msgs: continue
            
            latest = msgs[0]
            if latest.id > last_msg_id:
                raw = latest.text or ""
                if len(raw) < 5 or "thinking" in raw.lower() or "typing" in raw.lower():
                    continue 
                return latest
        except: pass
    return None

async def _find_and_click(client, peer, text_match_func, retries=3):
    print(f"[SYS] Hunting for button...")
    for attempt in range(retries):
        messages = await client.get_messages(peer, limit=5)
        for msg in messages:
            if not msg.buttons: continue
            for row in msg.buttons:
                for btn in row:
                    clean_text = btn.text.replace('\ufe0f', '').strip()
                    if text_match_func(clean_text):
                        print(f"[SYS] 👉 Clicked: '{clean_text}' (MsgID: {msg.id})")
                        await btn.click()
                        return True
        await asyncio.sleep(3)
    print("[ERR] Button hunt failed.")
    return False

async def _execute_sequence(client, peer, payload):
    mode = 'DATA'
    prompt = payload.get('prompt')
    content = payload.get('content')
    ctx_time = payload.get('time_context', '')
    
    # שליפת ID התחלתי
    last_msgs = await client.get_messages(peer, limit=1)
    last_id = last_msgs[0].id if last_msgs else 0

    # ==========================================
    # 🌅 PHASE 1: Initialization
    # ==========================================
    if mode == 'INIT':
        print("[SYS] Init sequence started")
        
        # 1. Send /new
        sent = await client.send_message(peer, CMD_RESET)
        last_id = sent.id # עדכון כדי שלא נתבלבל
        await asyncio.sleep(4)
        
        # 2. Click Neural Network
        await _find_and_click(client, peer, lambda t: BTN_L1.lower() in t.lower())
        await asyncio.sleep(4)
        
        # 3. Click Gemini
        await _find_and_click(client, peer, lambda t: BTN_L2.lower() in t.lower())
        await asyncio.sleep(4)
        
        # 4. Click Gemini 3 (חיפוש מדויק)
        await _find_and_click(client, peer, lambda t: 'gemini' in t.lower() and '3' in t.lower())
        await asyncio.sleep(4)
        
        # 5. Click Create -->
        await _find_and_click(client, peer, lambda t: 'create' in t.lower() or '-->' in t)
        await asyncio.sleep(4)
        
        # 6. Send Prompt & WAIT FOR ACK
        if prompt:
            print("[SYS] Sending prompt...")
            prompt_msg = await client.send_message(peer, prompt)
            last_id = prompt_msg.id # מעדכנים ID
            
            print("[SYS] Waiting for Prompt ACK...")
            # ⭐ ההמתנה הקריטית: מחכים שהבוט יגיד "הבנתי"
            ack_msg = await _wait_for_new_message(client, peer, last_id, timeout=60)
            
            if ack_msg:
                print("[SYS] Prompt acknowledged. Moving to Data Phase.")
                last_id = ack_msg.id # מעדכנים ID שוב כדי לדלג על ה-ACK
            else:
                print("[WARN] No ACK for prompt, proceeding anyway...")
            
            await asyncio.sleep(2)

    # ==========================================
    # 🚀 PHASE 2: Data Transfer
    # ==========================================
    print(f"[SYS] Transferring data (Mode: {mode})")
    msg_text = f"CURRENT_TIME: {ctx_time}\nDATA_STREAM: {content}"
    
    sent_msg = None
    if len(msg_text) > 4000:
        f = io.BytesIO(msg_text.encode('utf-8')); f.name = "blob.txt"
        sent_msg = await client.send_file(peer, f)
    else:
        sent_msg = await client.send_message(peer, msg_text)
    
    if sent_msg: last_id = sent_msg.id

# ==========================================
    # 🔧 PHASE 3: Polling Response (STRICT ONE-SHOT)
    # ==========================================
    print("[SYS] Polling for JSON response (Single Attempt)...")
    
    response_msg = await _wait_for_new_message(client, peer, last_id, timeout=180)
    
    if not response_msg:
        print("[WARN] Timeout waiting for response. Aborting.")
        return None
    
    last_id = response_msg.id 
    raw = response_msg.text or ""
    
    print(f"[DEBUG] Received response from AI. Length: {len(raw)} chars.")
    
    # מנגנון עצירה מיידית: אם ה-AI מדווח על שגיאה
    if "ERROR" in raw.upper():
        print("[ERR] 🚨 AI explicitly returned an ERROR! Aborting JSON hunt.")
        return None
        
    # שלב 1: חותכים רק את מה שבין הסוגריים המסולסלים 
    match = re.search(r'\{.*\}', raw, re.DOTALL)
    
    if match:
        json_str = match.group(0)
        print("[DEBUG] Extracting JSON payload. Applying heavy sanitization...")
        
        # ניקוי רעלים מהטקסט
        json_str = json_str.replace('“', '"').replace('”', '"').replace('‘', "'").replace('’', "'")
        json_str = json_str.replace('\u200b', '').replace('\xa0', ' ')
        json_str = re.sub(r',\s*\}', '}', json_str)
        json_str = re.sub(r',\s*\]', ']', json_str)
        
        parsed_obj = None
        try:
            parsed_obj = json.loads(json_str, strict=False)
        except Exception as e1:
            print(f"[WARN] First parse failed ({e1}). Attempting Nuclear Clean...")
            try:
                nuclear_str = json_str.replace('\n', '\\n').replace('\r', '')
                parsed_obj = json.loads(nuclear_str, strict=False)
            except Exception as e2:
                print(f"[ERR] ❌ JSON Parse Failed Completely: {e2}")
                return None # הבאסה נחתכת פה, עוברים ל-10 דקות
        
        # בדיקה האם חילצנו אובייקט תקין
        if parsed_obj and isinstance(parsed_obj, dict):
            if "action" in parsed_obj:
                print(f"[SYS] ✅ Valid JSON parsed successfully! Action: {parsed_obj['action']}")
                return parsed_obj
            else:
                print("[ERR] JSON parsed, but 'action' key is missing!")
                return None
                
    else:
        print("[ERR] ❌ Could not find { } brackets in response.")
    
    # אין ניסיונות חוזרים. לא מצאנו? מחזירים None וקופצים להמתנה.
    return None

async def _main():
    blob = SYS_CFG['payload']
    telemetry_url = SYS_CFG['telemetry']
    webhook_url = SYS_CFG['webhook']
    timer_updated = False  # משתנה המעקב הקריטי לקריסות קשות

    if not blob: return

    try:
        data = json.loads(blob)
        data['mode'] = 'DATA' # כופה מצב DATA לבדיקות
    except Exception as e: 
        print(f"[ERR] Payload load failed: {e}")

    client = None
    try:
        client = await _connect_node()
        async with client:
            try: peer = await client.get_entity(SYS_CFG['target'])
            except: peer = await client.get_input_entity(SYS_CFG['target'])
            
            result = await _execute_sequence(client, peer, data)
            
            # --- שלב האימות הקפדני (Validating the Result) ---
            is_valid_success = False
            final_text_to_publish = ""
            source_id_to_publish = ""
            reply_to_publish = None
            
            if result and isinstance(result, dict):
                print(f"[DEBUG] AI JSON Keys found: {list(result.keys())}")
                action = result.get("action")
                
                if action == "PUBLISH":
                    # מחפשים טקסט בכל קומבינציה אפשרית
                    raw_text = result.get("finaltext") or result.get("final_text") or result.get("text") or result.get("content") or ""
                    final_text_to_publish = str(raw_text).strip()
                    
                    if final_text_to_publish:
                        is_valid_success = True
                        source_id_to_publish = result.get("sourceid") or result.get("source_id") or result.get("id") or ""
                        reply_to_publish = result.get("replytosourceid") or result.get("reply_to_source_id") or result.get("reply_to")
                    else:
                        print("[ERR] 🚨 AI returned PUBLISH but text is empty/missing. Treating as ERROR.")
                
                elif action == "SKIP":
                    is_valid_success = True
                    print("[SYS] AI chose to SKIP. No webhook fired.")
            
            # --- ביצוע פעולות בהתאם לסטטוס ---
            if is_valid_success:
                print("[SYS] Flow validated successfully. Proceeding with triggers...")
                
                # 1. עדכון טיימר (מצב הצלחה - OK)
                if telemetry_url:
                    try:
                        scan_mins = result.get("nextscanminutes") or result.get("next_scan_minutes") or result.get("minutes") or 15
                        res_t = requests.post(telemetry_url, json={"type": "UPDATE_TIMER", "minutes": int(scan_mins), "status": "OK"}, timeout=10)
                        print(f"[SYS] ⏱️ Telemetry (OK) HTTP Status: {res_t.status_code}")
                        timer_updated = True
                    except Exception as e:
                        print(f"[ERR] Telemetry request failed: {e}")
                
                # 2. פרסום לטלגרם (רק אם זה PUBLISH)
                if result.get("action") == "PUBLISH" and webhook_url:
                    print("[SYS] 🌐 Firing PUBLISH webhook to Google Apps Script...")
                    try:
                        res_w = requests.post(webhook_url, json={
                            "type": "PUBLISH_CONTENT",
                            "text": final_text_to_publish,
                            "source_id": source_id_to_publish,
                            "reply_to_source_id": reply_to_publish
                        }, timeout=20)
                        print(f"[SYS] 🌐 Webhook HTTP Status: {res_w.status_code}")
                    except Exception as e:
                        print(f"[ERR] ❌ Webhook request crashed: {e}")
            
            else:
                # -----------------------------------------
                # ⭐ מנגנון חירום 1: טקסט ריק, JSON שבור או ERROR מפורש
                # -----------------------------------------
                print("[ERR] ❌ Flow ended with invalid result. Triggering 10-minute fallback.")
                if telemetry_url:
                    try:
                        res_fail = requests.post(telemetry_url, json={"type": "UPDATE_TIMER", "minutes": 10, "status": "FAIL"}, timeout=10)
                        print(f"[SYS] ⏱️ Telemetry (FAIL) HTTP Status: {res_fail.status_code}")
                        timer_updated = True
                    except Exception as e:
                        print(f"[ERR] Telemetry fail request crashed: {e}")

    except Exception as e:
        print(f"[ERR] Critical crash during execution: {e}")
        traceback.print_exc()
        
    finally:
        if client and client.is_connected():
            await client.disconnect()
            
        # -----------------------------------------
        # 🛡️ מנגנון חירום 2: חומת המגן הקריטית (אם פייתון קרס לחלוטין)
        # -----------------------------------------
        if not timer_updated and telemetry_url:
            print("[SYS] 🛡️ ULTIMATE FALLBACK: Script crashed unexpectedly. Forcing 10 min wait.")
            try:
                requests.post(telemetry_url, json={"type": "UPDATE_TIMER", "minutes": 10, "status": "FAIL"}, timeout=10)
            except Exception as e:
                print(f"[ERR] Ultimate fallback also failed: {e}")

if __name__ == "__main__":
    asyncio.run(_main())
