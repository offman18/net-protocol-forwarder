import os, json, time, requests, traceback, re

# === CONFIG (from GitHub Secrets, not exposed in code) ===
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN","").strip() or os.environ.get("EDITOR_BOT_TOKEN","").strip()
GROUP_ID = os.environ.get("EDITOR_GROUP_ID","").strip()
NVIDIA_KEY = os.environ.get("NVIDIA_API_KEY","").strip()
SCANNER_URL = os.environ.get("SCANNER_URL","").strip()
SYNC_ENDPOINT = os.environ.get("SYNC_ENDPOINT","").strip()

# Fallback chain for LLM calls (NVIDIA NIM endpoint)
KIMI_MODELS = [
  "moonshotai/kimi-k3",
  "minimaxai/minimax-m3",
  "nvidia/nemotron-3-ultra-550b-a55b",
  "deepseek-ai/deepseek-v4-pro-0813",
  "deepseek-ai/deepseek-v4-flash-0731",
  "openai/gpt-oss-20b",
  "nvidia/nemotron-3-nano-30b-a3b",
  "nvidia/nemotron-3-super-120b-a12b",
]

# === UNIFIED TOOLS DEFINITION - מפת כלים מלאה ואיסור דיבורי סרק ===
UNIFIED_TOOLS_DOCS = """
🛠️ ארגז הכלים המערכתי (מופעל ע"י כתיבת התגית בטקסט):
1. [כלי: סריקה] - הפעלת סריקת מודיעין של כל 35 מקורות הגלם ברקע.
2. [כלי: פרסום: נוסח המבזק] - פרסום ישיר לערוץ הטלגרם הציבורי.
3. [כלי: עדכון_פרומפט: שם_הסוכן: הכלל המדויק] - עדכון ושמירת כלל בשרת (למשל: עורך / כל_הסוכנים / מבקר).
4. [כלי: קריאה: @סוכן משימה] - הפעלת סוכן מומחה אחר בדסק:
   • @עורך : ניסוח ושכתוב מבזקי חדשות.
   • @מבקר : אימות עובדות, אישור טיוטות ובדיקת איכות.
   • @עורך_ראשי : קבלת החלטות, הובלת הדסק ואישור פרסום.
   • @מהנדס : עדכון פרומפטים וכיול כללי AI.
   • @אנליסט : ניתוח מקורות אויב זרים (ערבית/פרסית/רוסית) ורקע טקטי.

⛔ חוק ברזל עליון (איסור מוחלט על דיבורי סרק!):
1. אסור לחלוטין להצהיר שביצעת פעולה, שאתה מעדכן, שאתה סורק או שאתה מפרסם — ללא כתיבת תגית הכלי המתאימה במפורש באותה הודעה!
2. לעולם אל תגיד "מעדכן את הפרומפט" בלי [כלי: עדכון_פרומפט: ...]. לעולם אל תגיד "מפרסם" בלי [כלי: פרסום: ...].
3. כל שינוי/פעולה שביקש המפעיל חייבת להתבצע באמצעות כלי מיד. ענה תמיד בעברית בלבד."""

# === PERSONAS - פשוט: א' כותב, ב' עורך, ג' מאשר ושולח. כל אחד מקבל היסטוריית ערוץ ===
PERSONAS = {
  "FOCUS": {
    "tag": "🤖 בוט ג' - המאשר:",
    "system": f"""אתה בוט ג' - המאשר של 'חדשות בזק'. אתה מקבל: טיוטה ערוכה + היסטוריית פרסומי הערוץ (50 אחרונות).
תפקידך: לאשר ולשלוח. אם הטיוטה טובה ולא כפילות - כתוב "מאושר" ופרסם מיד: [כלי: פרסום: נוסח המבזק]. אם כפילות או לא ראוי - כתוב "נדחה: [סיבה]" ואל תפרסם.
כללים: ידיעה אחת בלבד לפרסום. בלי JSON. עברית טבעית קצרה.
{UNIFIED_TOOLS_DOCS}"""
  },
  "EDITOR": {
    "tag": "🤖 בוט א' - הכותב:",
    "system": f"""אתה בוט א' - הכותב של 'חדשות בזק'. אתה מקבל: חומר גלם (מקורות) + היסטוריית פרסומי הערוץ (50 אחרונות).
תפקידך: לכתוב מבזק אחד חד (1-2 שורות, עברית טבעית). כלל ברזל: ידיעה אחת בלבד, אסור שני פריטים בהודעה. בלי "חדשות בזק" בהתחלה. בלי JSON - רק טקסט נקי.
{UNIFIED_TOOLS_DOCS}"""
  },
  "CRITIC": {
    "tag": "🤖 בוט ב' - העורך:",
    "system": f"""אתה בוט ב' - העורך של 'חדשות בזק'. אתה מקבל: טיוטה של בוט א' + היסטוריית פרסומי הערוץ (50 אחרונות).
תפקידך: לערוך ולבדוק כפילויות מול ההיסטוריה. אם כפילות - כתוב "כפילות - לדחות". אם צריך תיקון - החזר טקסט מתוקן נקי. אם טוב - כתוב "ערוך ומוכן:" + הטקסט. בלי JSON.
{UNIFIED_TOOLS_DOCS}"""
  },
  "PROMPT_ENGINEER": {
    "tag": "🛠️ מהנדס הפרומפט:",
    "system": f"""אתה מהנדס הפרומפט והאחראי הטכני על מודלי ה-AI במערכת.
תפקידך: לעדכן פרומפטים וכללים באופן מעשי ומיידי באמצעות הכלי.

חוקי ברזל:
1. אסור לחלוטין לפלוט פילוסופיה, הרצאות או לצטט את כל הפרומפט מחדש!
2. כשיש בקשה לשינוי כלל/סגנון/הנחיה – חובה להפעיל מיד את הכלי: [כלי: עדכון_פרומפט: שם_הסוכן: הכלל המדויק החדש].
3. פלט התשובה שלך חייב להיות קצר מאוד (משפט אחד בלבד שמאשר את הכלל החדש שהוגדר).
4. סגנון: טכני, סופר קצר ותכליתי.
{UNIFIED_TOOLS_DOCS}"""
  },
  "OSINT": {
    "tag": "🌐 אנליסט מודיעין:",
    "system": f"""אתה אנליסט המודיעין ומקורות הגלם של הדסק (ערבית, פרסית, רוסית).
תפקידך: לנתח דיווחי שטח של ערוצי ציר ההתנגדות, לזהות התפתחויות ביטחוניות חריגות ולתת הקשר אסטרטגי לעורך הראשי.

חוקי עבודה:
1. הצלב דיווחים ממספר ערוצי אויב וקבע רמת אמינות.
2. כשיש אירוע דחוף, הנחה את העורך לנסח מבזק: [כלי: קריאה: @עורך נסח מבזק על האירוע הבא: ...]
3. סגנון: תמציתי, מודיעיני, עובדתי.
{UNIFIED_TOOLS_DOCS}"""
  }
}

def clean_llm_output(txt):
    if not txt: return ""
    cleaned = txt.strip()
    # Strip any English thinking/reasoning prefixes
    if "The user wants" in cleaned or "I need to" in cleaned or "Active Prompt" in cleaned or "Let me analyze" in cleaned:
        hebrew_match = re.search(r"[\u0590-\u05FF]", cleaned)
        if hebrew_match:
            cleaned = cleaned[hebrew_match.start():].strip()
        else:
            return ""
    # Strip markdown code blocks
    cleaned = cleaned.replace("```json", "").replace("```", "").strip()
    return cleaned

def _call_nvidia(messages, max_tokens=600, temperature=0.2):
    if not NVIDIA_KEY:
        print("[NVIDIA] no key")
        return None
    for model in KIMI_MODELS:
        try:
            r = requests.post("https://integrate.api.nvidia.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {NVIDIA_KEY}", "Content-Type": "application/json"},
                json={"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature},
                timeout=22)
            if r.status_code == 200:
                j = r.json()
                txt = j["choices"][0]["message"].get("content","")
                if txt and len(txt.strip())>3:
                    cleaned = clean_llm_output(txt)
                    if cleaned:
                        print(f"[NVIDIA] {model} ok")
                        return cleaned
            else:
                print(f"[NVIDIA] {model} {r.status_code}: {r.text[:120]}")
                if r.status_code in (429,404,410,500,502,503): continue
        except Exception as e:
            print(f"[NVIDIA] {model} err {e}")
            continue
    print("[NVIDIA] all models failed")
    return None

def run_agent(name, user_content, history_text=""):
    p = PERSONAS.get(name)
    if not p: return None
    msgs = [{"role":"system","content": p["system"]}]
    if history_text:
        msgs.append({"role":"user","content": "דיון רחב ומלא בחדר המערכת (כולל כל הטיוטות הפעילות, חומרי הגלם, ההערות וההודעות האחרונות):\n" + history_text[-30000:]})
    msgs.append({"role":"user","content": f"הודעה/בקשה מהמפעיל: {user_content[:5000]}"})
    out = _call_nvidia(msgs, max_tokens=700, temperature=0.2)
    if out:
        return f"{p['tag']} {out}"
    return None

def send_to_group(text, reply_to=None):
    if not BOT_TOKEN or not GROUP_ID:
        print("missing BOT_TOKEN/GROUP_ID")
        return False

    # Ensure correct supergroup prefix -100
    gid = str(GROUP_ID).strip()
    if gid.startswith("-") and not gid.startswith("-100") and len(gid) > 8:
        gid = "-100" + gid[1:]
    elif not gid.startswith("-") and len(gid) > 8:
        gid = "-100" + gid

    # Clean out internal tool tags before displaying to users
    display_text = re.sub(r"\[כלי:[^\]]+\]", "", text).strip()
    display_text = re.sub(r"\n{3,}", "\n\n", display_text)
    if not display_text:
        return True

    # סדר: הודעה קצרה + שרשור. חתוך הודעות ארוכות
    if len(display_text) > 900:
        display_text = display_text[:900] + "…"

    try:
        payload = {"chat_id": gid, "text": display_text, "parse_mode":"HTML", "disable_web_page_preview": True}
        if reply_to:
            payload["reply_to_message_id"] = reply_to
        r = requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json=payload,
            timeout=10)
        ok = r.status_code==200 and r.json().get("ok")
        if not ok:
            # Fallback to plain text
            payload.pop("parse_mode", None)
            r = requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json=payload,
                timeout=10)
            ok = r.status_code==200 and r.json().get("ok")
            if not ok: print(f"send fail {r.text[:200]}")
        return ok
    except Exception as e:
        print(f"send err {e}")
        return False

def publish_to_channel(text, source_id="manual"):
    if not SYNC_ENDPOINT:
        send_to_group("❌ אין כתובת SYNC_ENDPOINT מוגדרת לפרסום.")
        return False
    try:
        clean_text = str(text or "").strip()
        clean_text = re.sub(r"^```(?:json)?\s*", "", clean_text, flags=re.I)
        clean_text = re.sub(r"\s*```$", "", clean_text)
        # Strip tool tags if embedded
        clean_text = re.sub(r"\[כלי:[^\]]+\]", "", clean_text).strip()
        if not clean_text or not re.search(r"[\u0590-\u05FF]", clean_text):
            send_to_group("🛑 הפרסום נחסם: הטקסט אינו בעברית תקינה.")
            return False

        meta_pattern = r"אין ידיעה|אין חדשות|ללא תוכן חדשותי|אין תוכן חדשותי|ללא תוכן|אין תוכן|אין דיווח|ללא דיווח|זמני תפילה|לוח זמנים|להוסיף reply_to|להוסיף reply|לנסח מחדש|הערת עריכה|הערת ביקורת|טיוטת עורך|הודעת מערכת"
        if re.search(meta_pattern, clean_text, flags=re.I):
            send_to_group("🛑 הפרסום נחסם: הטקסט מכיל הערת מטא/הסבר על היעדר תוכן ואינו מבזק חדשותי.")
            return False

        payload = {"type":"PUBLISH_CONTENT","source_id":source_id,"text":clean_text,"reply_to_source_id":None}
        r = requests.post(SYNC_ENDPOINT, json=payload, timeout=12)
        ok = r.status_code==200
        send_to_group(f"📤 {'הידיעה פורסמה בהצלחה לערוץ! ✅' if ok else 'הפרסום לערוץ נכשל ❌'}\n\n{clean_text[:120]}...")
        return ok
    except Exception as e:
        print(f"publish err {e}")
        send_to_group(f"❌ שגיאה בפרסום לערוץ: {e}")
        return False

def normalize_agent_name(name):
    if not name: return "ALL"
    n = str(name).strip()
    if "עורך" in n and "ראשי" not in n: return "EDITOR"
    if "מבקר" in n: return "CRITIC"
    if "מיקוד" in n or "ראשי" in n or "focus" in n.lower(): return "FOCUS"
    if "מהנדס" in n: return "PROMPT_ENGINEER"
    return "ALL"

def save_prompt_patch(agent, patch, is_remove=False):
    if not patch or len(patch)<5: return
    norm_agent = normalize_agent_name(agent)
    key = "PROMPT_PATCH" if norm_agent=="ALL" else f"PROMPT_PATCH_{norm_agent}"
    if is_remove:
        patch = f"[הסרה] {patch}"
    try:
        if SCANNER_URL:
            r = requests.post(SCANNER_URL, json={"action":"setProps", key: patch.strip()[:1000]}, timeout=8)
            print(f"saved {key}: {patch[:80]} | res: {r.text[:60]}")
            if is_remove and len(patch)<30:
                try: requests.post(SCANNER_URL, json={"action":"deleteProps", key: key}, timeout=8)
                except: pass
            send_to_group(f"🛠️ פרומפט עודכן בהצלחה ({key}):\n{patch[:250]}")
    except Exception as e:
        print(f"patch save err {e}")

def wake_google():
    for url in [SCANNER_URL, SYNC_ENDPOINT]:
        if not url: continue
        try: requests.get(url, timeout=30); print(f"woke {url[:40]}")
        except Exception as e:
            if "timeout" not in str(e).lower(): print(f"wake err {e}")

_last_sync_time = 0

def sync_context_to_scanner(history_str):
    global _last_sync_time
    if not SCANNER_URL: return
    now = time.time()
    if now - _last_sync_time < 30:  # Debounce: sync at most every 30 seconds
        return
    _last_sync_time = now
    try:
        requests.post(SCANNER_URL, json={"action": "syncGroupContext", "context": history_str[-9000:]}, timeout=6)
    except Exception as e:
        print(f"syncGroupContext err: {e}")

def execute_agent_tools(agent_name, agent_output, history_str, depth=0):
    """Parses and executes any autonomous tools requested by the agent."""
    if not agent_output: return
    if depth > 2:
        print(f"[{agent_name}] Max tool delegation depth reached, stopping.")
        return
    
    # 1. Check for scan tool [כלי: סריקה]
    if "[כלי: סריקה]" in agent_output:
        print(f"[{agent_name}] Triggered SCAN tool")
        try: requests.get(SCANNER_URL, timeout=10)
        except: pass

    # 2. Check for publish tool [כלי: פרסום: ...]
    pub_match = re.search(r"\[כלי:\s*פרסום:\s*([^\]]+)\]", agent_output)
    if pub_match:
        to_pub = pub_match.group(1).strip()
        # Protect against dummy placeholders
        if len(to_pub) > 20 and not any(p in to_pub for p in ["נוסח המבזק", "טקסט המבזק", "הטקסט כאן", "נוסח כאן", "...", "כותרת ותוכן"]):
            print(f"[{agent_name}] Triggered PUBLISH tool: {to_pub[:60]}")
            publish_to_channel(to_pub, source_id=f"{agent_name.lower()}_{int(time.time())}")

    # 3. Check for prompt update tool [כלי: עדכון_פרומפט: ...]
    prompt_match = re.search(r"\[כלי:\s*עדכון_פרומפט:\s*([^:]+):\s*([^\]]+)\]", agent_output)
    if prompt_match:
        target_agent = prompt_match.group(1).strip()
        patch_body = prompt_match.group(2).strip()
        if len(patch_body) > 10 and not any(p in patch_body for p in ["הטקסט", "שם_הסוכן", "..."]):
            print(f"[{agent_name}] Triggered PROMPT_UPDATE tool for {target_agent}")
            save_prompt_patch(target_agent, patch_body)

    # 4. Check for delegation / inter-agent call [כלי: קריאה: @סוכן ...]
    call_match = re.search(r"\[כלי:\s*קריאה:\s*@?([^\s:]+)\s*([^\]]+)\]", agent_output)
    if call_match:
        target = call_match.group(1).strip()
        task = call_match.group(2).strip()
        target_persona = None
        if "עורך" in target: target_persona = "EDITOR"
        elif "מבקר" in target: target_persona = "CRITIC"
        elif "מיקוד" in target: target_persona = "FOCUS"
        elif "מהנדס" in target: target_persona = "PROMPT_ENGINEER"
        elif "אנליסט" in target or "מודיעין" in target: target_persona = "OSINT"

        if target_persona and target_persona != agent_name:
            print(f"[{agent_name}] Delegating to {target_persona}: {task[:60]}")
            time.sleep(1.2)
            sub_resp = run_agent(target_persona, task, history_str + "\n" + agent_output)
            if sub_resp:
                send_to_group(sub_resp)
                execute_agent_tools(target_persona, sub_resp, history_str + "\n" + agent_output, depth=depth+1)

    # === SMART FALLBACK PARSING: חילוץ פעולות גם אם המודל דיבר בעברית בלי סוגריים מרובעים ===
    if not pub_match and not prompt_match and not call_match and "[כלי: סריקה]" not in agent_output:
        # א. חילוץ עדכון פרומפט טבעי (למשל: "מעדכן את הפרומפט של העורך: ...")
        fallback_prompt = re.search(r"(?:מעדכן את הפרומפט של|עדכון פרומפט ל-|הנחיה חדשה ל-|קובע כלל ל-)\s*([^\n:]+)[:：]\s*([^\n]+)", agent_output)
        if fallback_prompt:
            tgt = fallback_prompt.group(1).strip()
            body = fallback_prompt.group(2).strip()
            if len(body) > 10 and not any(p in body for p in ["הטקסט", "שם_הסוכן", "..."]):
                print(f"[{agent_name}] Triggered SMART FALLBACK PROMPT_UPDATE for {tgt}")
                save_prompt_patch(tgt, body)

        # ב. חילוץ סריקה טבעית
        if any(k in agent_output for k in ["מפעיל סריקה של כל מקורות", "מבצע סריקה מיידית", "סורק את כל הערוצים"]):
            print(f"[{agent_name}] Triggered SMART FALLBACK SCAN")
            try: requests.get(SCANNER_URL, timeout=10)
            except: pass

        # ג. חילוץ הפעלת סוכן טבעית (למשל: "מפעיל את העורך לנסח...")
        fallback_call = re.search(r"(?:מפעיל את|מעביר ל-|קורא ל-)\s*@?(עורך|מבקר|מהנדס|אנליסט|עורך ראשי)\s*[:：]?\s*([^\n]+)", agent_output)
        if fallback_call:
            tgt_name = fallback_call.group(1).strip()
            tgt_task = fallback_call.group(2).strip()
            tgt_p = None
            if "עורך" in tgt_name and "ראשי" not in tgt_name: tgt_p = "EDITOR"
            elif "מבקר" in tgt_name: tgt_p = "CRITIC"
            elif "ראשי" in tgt_name: tgt_p = "FOCUS"
            elif "מהנדס" in tgt_name: tgt_p = "PROMPT_ENGINEER"
            elif "אנליסט" in tgt_name: tgt_p = "OSINT"
            if tgt_p and tgt_p != agent_name:
                print(f"[{agent_name}] Triggered SMART FALLBACK DELEGATION to {tgt_p}: {tgt_task[:60]}")
                time.sleep(1.2)
                sub_r = run_agent(tgt_p, tgt_task, history_str + "\n" + agent_output)
                if sub_r:
                    send_to_group(sub_r)
                    execute_agent_tools(tgt_p, sub_r, history_str + "\n" + agent_output, depth=depth+1)

def main():
    print(f"Starting group_responder GROUP={GROUP_ID} bot={BOT_TOKEN[:6]}...")
    
    # Ensure clean polling by removing any active webhooks
    if BOT_TOKEN:
        try:
            rw = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook", timeout=8)
            print(f"Webhook reset status: {rw.status_code}")
        except Exception as e:
            print(f"deleteWebhook warning: {e}")

    offset = 0
    try:
        with open("offset.txt","r") as f: offset=int(f.read().strip() or 0)
    except: pass
    
    start = time.time()
    DURATION = 5.6*3600  # under cron interval to avoid overlap
    last_wake = 0
    
    chat_history = []
    
    # Pre-populate full newsroom history (past publications, active drafts, group discussion) from Google Apps Script
    if SCANNER_URL:
        try:
            r_hist = requests.post(SCANNER_URL, json={"action":"getNewsroomHistory"}, timeout=10)
            h_data = r_hist.json() if r_hist.headers.get("content-type","").startswith("application/json") else json.loads(r_hist.text)
            if h_data.get("published_snippets"):
                for p_snip in h_data["published_snippets"]:
                    chat_history.append(p_snip)
            if h_data.get("last_draft_raw"):
                chat_history.append(f"[מערכת (טיוטה אחרונה)]: {h_data['last_draft_raw']}")
            if h_data.get("recent_group_context"):
                for line in h_data["recent_group_context"].split("\n")[-15:]:
                    if line.strip() and line not in chat_history:
                        chat_history.append(line.strip())
            print(f"Pre-loaded {len(chat_history)} history entries on startup!")
        except Exception as e:
            print(f"pre-load history err: {e}")

    while time.time() - start < DURATION:
        try:
            # Watchdog בלבד: מעיר את גוגל רק אם אין פעימה 10 דקות (לא כל 120 שניות - זה שבר את הסורק)
            if time.time() - last_wake > 600:
                try:
                    hr = requests.post(SCANNER_URL, json={"action":"getHeartbeat"}, timeout=10).json()
                    import time as _t
                    if _t.time()*1000 - int(hr.get("heartbeat","0")) > 600000:
                        wake_google()
                except:
                    wake_google()
                last_wake = time.time()

            # Poll Telegram updates
            r = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates",
                params={"offset": offset, "timeout": 15, "limit": 30}, timeout=25)
            if r.status_code != 200:
                time.sleep(1.2)
                continue

            data = r.json()
            for upd in data.get("result", []):
                offset = max(offset, upd["update_id"]+1)
                try: open("offset.txt","w").write(str(offset))
                except: pass

                msg = upd.get("message") or upd.get("edited_message")
                if not msg: continue
                chat = msg.get("chat",{})
                
                chat_id_str = str(chat.get("id", ""))
                c_num = chat_id_str.replace("-100", "").replace("-", "")
                g_num = str(GROUP_ID).replace("-100", "").replace("-", "")
                if c_num != g_num:
                    continue

                from_user = msg.get("from", {})
                is_bot = from_user.get("is_bot", False)
                user_name = from_user.get('first_name', 'מפעיל')
                text = (msg.get("text") or msg.get("caption") or "").strip()
                if not text: 
                    continue

                # Record all messages (bot drafts, agent replies, human chats) into rolling chat_history
                sender_label = "מערכת (טיוטה)" if ("טיוטה לפרסום" in text or text.startswith("📝")) else (user_name if not is_bot else "בוט מערכת")
                chat_history.append(f"[{sender_label}]: {text}")
                if len(chat_history) > 100: chat_history = chat_history[-100:]
                # חבר גם 50 אחרונות מהערוץ כדי שהסוכנים יראו כפילויות
                try:
                    _hr = requests.post(SCANNER_URL, json={"action":"getHistory"}, timeout=8)
                    _ch = _hr.json() if _hr.headers.get("content-type","").startswith("application/json") else json.loads(_hr.text)
                    ch_txt = "\n".join([f"- {h.get('source_id','')}: {h.get('snippet','')[:80]}" for h in _ch[-50:]])
                    history_str = f"ערוץ (50 אחרונות):\n{ch_txt}\n\nקבוצה (100 אחרונות):\n" + "\n".join(chat_history)
                except:
                    history_str = "\n".join(chat_history)

                # Sync full context to Google Apps Script scanner so both systems are in the same universe
                sync_context_to_scanner(history_str)

                # צינור פשוט עם לולאת משוב + שרשור מסודר: הכל בתשובה להודעת חומר הגלם
                if is_bot and any(k in text for k in ["חומר גלם", "📎", "טיוטה לפרסום", "📝", "מקורות"]):
                    raw = text[:3000]
                    thread_id = msg.get("message_id")
                    fb_b = next((m for m in reversed(chat_history) if "בוט ב'" in m[:30]), "")
                    fb_g = next((m for m in reversed(chat_history) if "בוט ג'" in m[:30]), "")
                    a_out = run_agent("EDITOR", f"חומר גלם חדש:\n{raw}\nמשוב קודם של בוט ב' (לתקן הפעם):\n{fb_b[:600]}\nכתוב מבזק אחד (טקסט נקי בלבד).", history_str)
                    if a_out: send_to_group(a_out, reply_to=thread_id); time.sleep(1.0); chat_history.append(a_out); history_str += "\n" + a_out
                    b_out = run_agent("CRITIC", f"טיוטה של בוט א':\n{a_out}\nמשוב קודם של בוט ג' (ליישם):\n{fb_g[:600]}\nערוך ובדוק כפילות מול היסטוריית הערוץ.", history_str)
                    if b_out: send_to_group(b_out, reply_to=thread_id); time.sleep(1.0); chat_history.append(b_out); history_str += "\n" + b_out
                    if b_out and ("כפילות" in b_out or "לדחות" in b_out or "נדחה" in b_out):
                        send_to_group("🤖 בוט ג' - המאשר: נדחה (כפילות).", reply_to=thread_id)
                        continue
                    g_out = run_agent("FOCUS", f"טיוטה ערוכה:\n{b_out}\nאתה יכול גם לערוך ולשפר לפני שליחה. אשר עם [כלי: פרסום: נוסח סופי] או דחה עם נימוק.", history_str)
                    if g_out:
                        send_to_group(g_out, reply_to=thread_id); chat_history.append(g_out)
                        execute_agent_tools("FOCUS", g_out, history_str)
                    continue

                # ONLY skip auto-responding if the message actually came from a bot account
                if is_bot:
                    continue

                print(f"[HUMAN {user_name}]: {text[:80]}")
                lower = text.lower()

                # === 1. פקודת סריקה יזומה מהמפעיל ===
                if any(k in text for k in ["סרוק", "תסרוק", "/scan", "סריקה עכשיו", "יש חדש"]):
                    send_to_group("🔍 מפעיל סריקה של כל מקורות המודיעין ברקע... אם יימצא דיווח דחוף, הטיוטה תופיע כאן.")
                    try: requests.get(SCANNER_URL, timeout=10)
                    except: pass
                    continue

                # === 2. פקודת פרסום יזומה מהמפעיל לערוץ ===
                if any(text.startswith(k) for k in ["שלח לערוץ:", "פרסם:", "שלח:", "פרסם לערוץ:"]):
                    to_pub_raw = re.sub(r"^(?:שלח לערוץ|פרסם|שלח|פרסם לערוץ)\s*[:：]?\s*", "", text).strip()
                    if len(to_pub_raw) < 5:
                        send_to_group("❓ אנא ציין את נוסח המבזק: שלח לערוץ: [טקסט המבזק]")
                        continue
                    
                    polished = run_agent("EDITOR", f"לטש למבזק חדשותי מוכן לפרסום (רק טקסט נקי בעברית, בלי JSON): \"{to_pub_raw}\"", history_str)
                    polished_text = (polished or to_pub_raw).strip()
                    try:
                        jm = re.search(r"\{[\s\S]*\}", polished_text)
                        if jm:
                            jj = json.loads(jm.group(0))
                            if jj.get("final_text"): polished_text = jj["final_text"]
                    except: pass
                    polished_text = re.sub(r"^[🎯✍️🔍🛠️📝][^:\n]*:\s*", "", polished_text).strip()[:1100]
                    
                    critic = run_agent("CRITIC", f"בדוק טיוטה זו לפרסום מיידי: \"{polished_text}\"", history_str)
                    if critic and ("לא" in critic or "נפסל" in critic):
                        send_to_group(f"⛔ הבודק העיר על הטיוטה ולא אישר פרסום:\n{critic}")
                        continue
                    
                    publish_to_channel(polished_text, source_id=f"manual_{int(time.time())}")
                    continue

                # === 3. אישור אנושי מפורש לפרסום הטיוטה האחרונה שנחסמה ===
                if any(k in text for k in ["תפרסם על האירוע", "תפרסם את זה", "לפרסם את הטיוטה", "לפרסם על האירוע", "אשר פרסום", "תפרסם תמיד", "תפרסם"]):
                    # חפש את הטיוטה האחרונה בהיסטוריה
                    last_draft = None
                    for h_msg in reversed(chat_history):
                        if "טיוטה לפרסום" in h_msg or "📝" in h_msg:
                            # חלץ את גוף הטיוטה
                            draft_match = re.search(r"(?:טיוטה לפרסום\n\n|📝\s*)([^\n]+(?:\n[^\n]+)?)", h_msg)
                            if draft_match:
                                last_draft = draft_match.group(1).strip()
                                last_draft = re.sub(r"(?:🎯|🔍|📊|📎)[\s\S]*", "", last_draft).strip()
                                break
                    # אם לא נמצא בהיסטוריה המקומית, שאל ישירות את גוגל סקריפט
                    if not last_draft and SCANNER_URL:
                        try:
                            r_draft = requests.post(SCANNER_URL, json={"action":"getLastDraft"}, timeout=8)
                            d_json = r_draft.json() if r_draft.headers.get("content-type","").startswith("application/json") else json.loads(r_draft.text)
                            last_draft = d_json.get("draft_text", "")
                        except: pass

                    if last_draft and len(last_draft) > 15:
                        send_to_group(f"✍️ העורך הראשי מפרסם לערוץ באישור המפעיל:\n{last_draft}")
                        publish_to_channel(last_draft, source_id=f"human_override_{int(time.time())}")
                        continue
                    else:
                        send_to_group("🔍 מפעיל סריקה מהירה להבאת חומר גלם עדכני...")
                        try: requests.get(SCANNER_URL, timeout=10)
                        except: pass
                        continue

                # === 4. פקודות צפייה ועריכת פרומפט גולמי ===
                if "הראה פרומפט" in text or "הצג פרומפט" in text or "הפרומפט הגולמי" in text or "show prompt" in lower:
                    which = "ALL"
                    if "עורך" in text: which="EDITOR"
                    elif "מבקר" in text: which="CRITIC"
                    elif "מיקוד" in text: which="FOCUS"
                    elif "ראשי" in text: which="MAIN"
                    try:
                        r = requests.post(SCANNER_URL, json={"action":"getPrompt","which":which}, timeout=12)
                        j = r.json() if r.headers.get("content-type","").startswith("application/json") else json.loads(r.text)
                        for k,v in j.items():
                            if k=="PATCHES": continue
                            send_to_group(f"📄 <b>פרומפט גולמי {k}:</b>\n<pre>{v[:3500]}</pre>")
                            time.sleep(0.6)
                        if j.get("PATCHES"):
                            send_to_group(f"🩹 <b>פאצ'ים שמורים:</b>\n<pre>{json.dumps(j['PATCHES'], ensure_ascii=False, indent=2)[:1000]}</pre>")
                    except Exception as e:
                        send_to_group(f"❌ שגיאה בקריאת הפרומפט: {e}")
                    continue

                if ("ערוך פרומפט" in text or "קבע פרומפט" in text) and ":" in text:
                    which = "ALL"
                    if "עורך" in text: which="EDITOR"
                    elif "מבקר" in text: which="CRITIC"
                    elif "מיקוד" in text: which="FOCUS"
                    elif "ראשי" in text: which="MAIN"
                    new_text = text.split(":",1)[1].strip()
                    if len(new_text) < 10:
                        send_to_group("❓ כתוב: ערוך פרומפט של [שם]: [הטקסט החדש]")
                        continue
                    try:
                        r = requests.post(SCANNER_URL, json={"action":"setPrompt","which":which,"text":new_text}, timeout=12)
                        send_to_group(f"✅ פרומפט {which} עודכן בהצלחה בגוגל סקריפט.")
                    except Exception as e:
                        send_to_group(f"❌ שגיאה בעדכון פרומפט: {e}")
                    continue

                # === 5. פנייה ישירה לסוכן ספציפי (עם ביצוע כלים אוטונומי) ===
                single_agent = None
                if any(k in text for k in ["@עורך", "עורך ת", "תקרא לעורך"]): single_agent = "EDITOR"
                elif any(k in text for k in ["@מבקר", "מבקר ת", "תקרא למבקר"]): single_agent = "CRITIC"
                elif any(k in text for k in ["@מיקוד", "אחראי מיקוד", "תקרא למיקוד"]): single_agent = "FOCUS"
                elif any(k in text for k in ["@מהנדס", "מהנדס הפרומפט"]): single_agent = "PROMPT_ENGINEER"
                elif any(k in text for k in ["@אנליסט", "אנליסט", "תקרא לאנליסט", "מודיעין"]): single_agent = "OSINT"

                if single_agent:
                    resp = run_agent(single_agent, text, history_str)
                    if resp:
                        send_to_group(resp)
                        chat_history.append(resp)
                        execute_agent_tools(single_agent, resp, history_str)
                    continue

                # === 6. דיון מערכת בין כל הסוכנים ===
                if "תדברו ביניכם" in text or "דיון מערכת" in text or "שיחה ביניכם" in text:
                    current_hist = history_str
                    for name in ["FOCUS", "EDITOR", "CRITIC"]:
                        out = run_agent(name, f"דיון חדר מערכת בנושא: \"{text}\"", current_hist)
                        if out:
                            send_to_group(out)
                            current_hist += "\n" + out
                            chat_history.append(out)
                            execute_agent_tools(name, out, current_hist)
                            time.sleep(1.2)
                    continue

                # === 7. שיחה טבעית של המפעיל (מענה עורך ראשי + הפעלת כלים אוטונומית) ===
                resp = run_agent("FOCUS", text, history_str)
                if resp:
                    send_to_group(resp)
                    chat_history.append(resp)
                    execute_agent_tools("FOCUS", resp, history_str)

        except Exception as e:
            print(f"loop err {e}")
            traceback.print_exc()
        time.sleep(1.2)

    print("6h loop finished, restarting")

if __name__ == "__main__":
    main()
