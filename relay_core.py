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
    # 🔧 PHASE 3: Polling Response (SAFE DEBUG MODE)
    # ==========================================
    print("[SYS] Polling for JSON response...")
    
    for attempt in range(3):
        response_msg = await _wait_for_new_message(client, peer, last_id, timeout=180)
        
        if not response_msg:
            print("[WARN] Timeout waiting for response")
            return None
        
last_id = response_msg.id 
        raw = response_msg.text or ""
        
        print(f"[DEBUG] Received response from AI. Length: {len(raw)} chars.")
        
        # --- התוספת החדשה זיהוי שגיאה מהבוט ---
        if "error" in raw.lower():
            print("[WARN] 🛑 Bot returned an ERROR message! Aborting retry and sleeping for 10 minutes.")
            # מחזירים אובייקט שאומר למערכת לדלג על הפרסום ולחזור עוד 10 דקות
            return {"action": "SKIP", "next_scan_minutes": 10, "reason": "Bot Error"}
        # ----------------------------------------
        
        clean = re.sub(r'```(?:json)?\s*|\s*```', '', raw).strip()
        match = re.search(r'\{.*\}', clean, re.DOTALL)
        
        if match:
            print("[DEBUG] Found { } brackets in response. Attempting JSON parse...")
            try:
                obj = json.loads(match.group(0))
                if "action" in obj: 
                    print(f"[SYS] ✅ Valid JSON parsed successfully! Action: {obj['action']}")
                    return obj
                else:
                    print("[ERR] JSON parsed, but 'action' key is missing!")
            except Exception as e: 
                print(f"[ERR] ❌ JSON Parse Failed: {e}")
                print("[DEBUG] The JSON structure is likely broken or contains unescaped characters.")
        else:
            print("[ERR] ❌ Could not find valid { } JSON format in the AI's response.")
        
        if len(raw) > 50:
            print(f"[WARN] Invalid JSON (Attempt {attempt+1}/3). Requesting fix from AI...")
            sent_fix = await client.send_message(peer, ERR_MSG)
            last_id = sent_fix.id

    return None

async def _main():
    blob = SYS_CFG['payload']
    if not blob: return

    try:
        data = json.loads(blob)
        # זמנית - כופה מצב DATA כדי שנוכל לבדוק מיד
        data['mode'] = 'DATA'
    except Exception as e: 
        print(f"[ERR] Payload load failed: {e}")
        return

    client = None
    try:
        client = await _connect_node()
        async with client:
            try: peer = await client.get_entity(SYS_CFG['target'])
            except: peer = await client.get_input_entity(SYS_CFG['target'])
            
            result = await _execute_sequence(client, peer, data)
            
            if result:
                print("[SYS] Action decided. Attempting to trigger Google Script...")
                
                webhook_url = SYS_CFG['webhook']
                telemetry_url = SYS_CFG['telemetry']
                
                # בדיקה בטוחה אם הכתובות בכלל קיימות (ללא הדפסתן)
                print(f"[DEBUG] Webhook configured: {'YES' if webhook_url else 'NO ⚠️'}")
                print(f"[DEBUG] Telemetry configured: {'YES' if telemetry_url else 'NO ⚠️'}")

                # עדכון טיימר
                if telemetry_url:
                    try:
                        res_t = requests.post(telemetry_url, json={"type": "UPDATE_TIMER", "minutes": result.get("next_scan_minutes", 15), "status": "OK"}, timeout=10)
                        print(f"[SYS] ⏱️ Telemetry HTTP Status: {res_t.status_code}")
                    except Exception as e:
                        print(f"[ERR] Telemetry request failed: {e}")
                
# פרסום
                if result.get("action") == "PUBLISH":
                    if webhook_url:
                        print("[SYS] 🌐 Firing PUBLISH webhook to Google Apps Script...")
                        try:
                            res_w = requests.post(webhook_url, json={
                                "type": "PUBLISH_CONTENT",
                                "text": result.get("final_text", ""),
                                "source_id": result.get("source_id", ""),
                                "reply_to_source_id": result.get("reply_to_source_id")
                            }, timeout=20)
                            print(f"[SYS] 🌐 Webhook HTTP Status: {res_w.status_code}")
                            print(f"[DEBUG] Google Script Answered: {res_w.text[:200]}")
                            if res_w.status_code != 200:
                                print(f"[DEBUG] Webhook Error Response (Safe Preview): {res_w.text[:100]}")
                        except Exception as e:
                            print(f"[ERR] ❌ Webhook request crashed: {e}")
                    else:
                        print("[ERR] 🛑 Action is PUBLISH but SYNC_ENDPOINT is empty!")
                else:
                    print("[SYS] AI chose to SKIP. No webhook fired.")
            else:
                print("[ERR] ❌ Flow ended without a valid result.")
    except Exception as e:
        print("[ERR] Critical crash:")
        traceback.print_exc()
    finally:
        if client and client.is_connected():
            await client.disconnect()

if __name__ == "__main__":
    asyncio.run(_main())
