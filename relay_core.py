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
# 🔌 PROTOCOL RELAY v8.5 Kimi Judge + Backup (kimi-k3 -> kimi-k2.6)
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

# Kimi judge/backup via Nvidia NIM
NVIDIA_KEY = os.environ.get('NVIDIA_API_KEY', '').strip()
KIMI_MODELS = ["moonshotai/kimi-k3", "moonshotai/kimi-k2.6", "openai/gpt-oss-20b"]

def _call_nvidia(model, messages, max_tokens=800):
    if not NVIDIA_KEY:
        return None
    try:
        r = requests.post("https://integrate.api.nvidia.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {NVIDIA_KEY}", "Content-Type": "application/json"},
            json={"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": 0.7},
            timeout=25)
        if r.status_code == 200:
            j = r.json()
            return j['choices'][0]['message'].get('content','')
        else:
            print(f"[KIMI] {model} HTTP {r.status_code}: {r.text[:120]}")
    except Exception as e:
        print(f"[KIMI] {model} ERR {e}")
    return None

def _kimi_judge(proposed_text, history_hint=""):
    """Kimi as judge: receives 30 last msgs hint + proposed, returns edited final_text or None"""
    if not NVIDIA_KEY or not proposed_text:
        return None
    judge_prompt = f"""אתה שופט עורך חדשות בזק. קיבלת הצעה לפרסום:
"{proposed_text}"
היסטוריה (30 אחרונות רמז): {history_hint[:1500]}

משימה: ערוך את ההצעה להיות קריאה, בלי אמרת שפר, בלי פרשנות, בלי "דרמה.".
אם זה סקר - חובה רשימה אנכית עם • ו-<b> לכותרת.
החזר אך ורק JSON: {{"final_text":"הטקסט הערוך"}} בלי שום מילה נוספת."""
    for model in KIMI_MODELS:
        content = _call_nvidia(model, [{"role":"user","content": judge_prompt}])
        if content:
            try:
                m = re.search(r'\{.*\}', content, re.DOTALL)
                if m:
                    obj = json.loads(m.group(0))
                    edited = obj.get('final_text') or obj.get('finalText') or obj.get('text')
                    if edited and len(edited.strip()) > 5:
                        print(f"[KIMI] Judge {model} edited: {edited[:60]}...")
                        return edited.strip()
            except Exception as e:
                print(f"[KIMI] Judge parse fail {model}: {e}")
                continue
    return None

def _kimi_generate_fallback(data_payload):
    """Kimi as backup generator if Gemini fails: tries to generate PUBLISH/SKIP directly"""
    if not NVIDIA_KEY:
        return None
    fallback_prompt = f"""אתה עורך חדשות בזק. קיבלת DATA:
{data_payload.get('content','')[:3000]}

החזר אך ורק JSON: {{"action":"PUBLISH","final_text":"<b>כותרת</b> טקסט","source_id":"id","reply_to_source_id":null,"next_scan_minutes":3}} או {{"action":"SKIP","final_text":"","source_id":"","reply_to_source_id":null,"next_scan_minutes":3}}
אם זה לא על בחירות/חדשות חשובה -> SKIP. אם זה סקר -> רשימה עם •."""
    for model in KIMI_MODELS:
        content = _call_nvidia(model, [{"role":"user","content": fallback_prompt}], max_tokens=600)
        if content:
            try:
                m = re.search(r'\{.*\}', content, re.DOTALL)
                if m:
                    obj = json.loads(m.group(0))
                    if obj.get('action') in ('PUBLISH','SKIP'):
                        print(f"[KIMI] Fallback {model} -> {obj.get('action')}")
                        # Second judge call on fallback result
                        if obj.get('action') == 'PUBLISH' and obj.get('final_text'):
                            edited = _kimi_judge(obj['final_text'])
                            if edited:
                                obj['final_text'] = edited
                        return obj
            except Exception as e:
                print(f"[KIMI] Fallback parse {model}: {e}")
                continue
    return None

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

async def _wait_for_new_message(client, peer, last_msg_id, timeout=60):
    start_time = time.time()
    while (time.time() - start_time) < timeout:
        await asyncio.sleep(2)
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
        await asyncio.sleep(1.5)
    print("[ERR] Button hunt failed.")
    return False

async def _execute_sequence(client, peer, payload):
    mode = payload.get('mode', 'DATA') 
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
        await asyncio.sleep(2)
        
        # 2. Click Neural Network
        await _find_and_click(client, peer, lambda t: BTN_L1.lower() in t.lower())
        await asyncio.sleep(2)
        
# 3. Click Gemini
        await _find_and_click(client, peer, lambda t: BTN_L2.lower() in t.lower())
        await asyncio.sleep(2)
        
        # 4. Click Target Model (Dynamic Search)
        target_model = payload.get('target_model', 'GEMINI_3')
        
        model_btn_map = {
            'GEMINI_3': 'gemini 3',
            'GEMINI_3_FLASH': 'gemini 3 flash',
            'GEMINI_2_5_FLASH': 'gemini 2.5 flash'
        }
        
        btn_text_to_find = model_btn_map.get(target_model, 'gemini 3')
        print(f"[SYS] Looking for dynamic model button: '{btn_text_to_find}'")
        
        await _find_and_click(client, peer, lambda t: btn_text_to_find in t.lower())
        await asyncio.sleep(2)
        
        # 5. Click Create -->
        await _find_and_click(client, peer, lambda t: 'create' in t.lower() or '-->' in t)
        await asyncio.sleep(2)
        
        # 6. Send Prompt & WAIT FOR ACK
        if prompt:
            print("[SYS] Sending prompt...")
            prompt_msg = await client.send_message(peer, prompt)
            last_id = prompt_msg.id # מעדכנים ID
            
            print("[SYS] Waiting for Prompt ACK...")
            # ⭐ ההמתנה הקריטית: מחכים שהבוט יגיד "הבנתי"
            ack_msg = await _wait_for_new_message(client, peer, last_id, timeout=30)
            
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
    
    response_msg = await _wait_for_new_message(client, peer, last_id, timeout=60)
    
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
    timer_updated = False  

    if not blob: 
        print("[SYS] No payload found. Exiting.")
        return

    try:
        data = json.loads(blob)
    except Exception as e: 
        print(f"[ERR] Payload load failed: {e}")
        return

    client = None
    try:
        client = await _connect_node()
        async with client:
            try: 
                peer = await client.get_entity(SYS_CFG['target'])
            except: 
                peer = await client.get_input_entity(SYS_CFG['target'])
            
            # ביצוע הרצף מול ה-AI
            result = await _execute_sequence(client, peer, data)

            # === Kimi judge + backup (Nvidia) ===
            # אם Gemini הצליח -> Kimi כשופט עורך (30 הודעות רמז)
            if result and result.get('action') == 'PUBLISH':
                try:
                    edited = _kimi_judge(result.get('final_text',''), str(data.get('content',''))[:1000])
                    if edited:
                        print(f"[KIMI] Judge edited text applied")
                        result['final_text'] = edited
                except Exception as e:
                    print(f"[KIMI] Judge error: {e}")
            elif not result:
                print("[SYS] Gemini failed, trying Kimi fallback (kimi-k3 -> kimi-k2.6)...")
                try:
                    kimi_result = _kimi_generate_fallback(data)
                    if kimi_result:
                        result = kimi_result
                        print(f"[SYS] Kimi fallback succeeded: {result.get('action')}")
                except Exception as e:
                    print(f"[KIMI] Fallback error: {e}")
            
            # --- שלב האימות הקפדני (Validating the Result) ---
            is_valid_success = False
            final_text_to_publish = ""
            source_id_to_publish = ""
            reply_to_publish = None
            
            if result and isinstance(result, dict):
                print(f"[DEBUG] AI JSON Keys found: {list(result.keys())}")
                action = result.get("action")
                
                if action == "PUBLISH":
                    # בדיקת שדות גמישה (תמיכה בכל הווריאציות של ג'מיני)
                    raw_text = (result.get("finaltext") or result.get("final_text") or 
                                result.get("final__text") or result.get("text") or 
                                result.get("content") or "")
                    final_text_to_publish = str(raw_text).strip()
                    
                    if final_text_to_publish:
                        is_valid_success = True
                        source_id_to_publish = (result.get("sourceid") or result.get("source_id") or 
                                               result.get("source__id") or result.get("id") or "")
                        reply_to_publish = (result.get("replytosourceid") or result.get("reply_to_source_id") or 
                                           result.get("reply__to__source__id") or result.get("reply_to"))
                    else:
                        print("[ERR] 🚨 AI returned PUBLISH but text is empty.")
                
                elif action == "SKIP":
                    is_valid_success = True
                    print("[SYS] AI chose to SKIP. No webhook fired.")
            
            # --- ביצוע פעולות בהתאם לסטטוס ---
            if is_valid_success:
                print("[SYS] Flow validated successfully. Proceeding with triggers...")
                
                # 1. עדכון טיימר (מצב הצלחה)
                if telemetry_url:
                    try:
                        scan_mins = (result.get("nextscanminutes") or result.get("next_scan_minutes") or 
                                     result.get("next__scan__minutes") or result.get("minutes") or 3)
                        res_t = requests.post(telemetry_url, json={"type": "UPDATE_TIMER", "minutes": int(scan_mins), "status": "OK"}, timeout=10)
                        print(f"[SYS] ⏱️ Telemetry (OK) HTTP Status: {res_t.status_code}")
                        timer_updated = True
                    except Exception as e:
                        print(f"[ERR] Telemetry request failed: {e}")
                
                # 2. פרסום (Webhook)
                if result and result.get("action") == "PUBLISH" and webhook_url:
                    print("[SYS] 🌐 Firing PUBLISH webhook...")
                    try:
                        res_w = requests.post(webhook_url, json={
                            "type": "PUBLISH_CONTENT",
                            "text": final_text_to_publish,
                            "source_id": source_id_to_publish,
                            "reply_to_source_id": reply_to_publish
                        }, timeout=20)
                        print(f"[SYS] 🌐 Webhook HTTP Status: {res_w.status_code}")
                    except Exception as e:
                        print(f"[ERR] ❌ Webhook crashed: {e}")
            else:
                # מנגנון חירום: תוצאה לא תקינה
                print("[ERR] ❌ Flow ended with invalid result. Triggering 3-minute fallback.")
                if telemetry_url:
                    try:
                        res_fail = requests.post(telemetry_url, json={"type": "UPDATE_TIMER", "minutes": 3, "status": "FAIL"}, timeout=10)
                        print(f"[SYS] ⏱️ Telemetry (FAIL) HTTP Status: {res_fail.status_code}")
                        timer_updated = True
                    except: pass

    except Exception as e:
        print(f"[ERR] Critical crash during execution: {e}")
        traceback.print_exc()
        if not timer_updated and telemetry_url:
            try:
                requests.post(telemetry_url, json={"type": "UPDATE_TIMER", "minutes": 3, "status": "FAIL"}, timeout=10)
            except: pass
    finally:
        if client and client.is_connected():
            await client.disconnect()

if __name__ == "__main__":
    asyncio.run(_main())
