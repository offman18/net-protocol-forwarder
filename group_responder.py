import os, json, time, requests, traceback, re

# === CONFIG (from GitHub Secrets, not exposed in code) ===
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN","").strip() or os.environ.get("EDITOR_BOT_TOKEN","").strip()
GROUP_ID = os.environ.get("EDITOR_GROUP_ID","").strip()
NVIDIA_KEY = os.environ.get("NVIDIA_API_KEY","").strip()
SCANNER_URL = os.environ.get("SCANNER_URL","").strip()
SYNC_ENDPOINT = os.environ.get("SYNC_ENDPOINT","").strip()

# Fallback chain for LLM calls
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

# === PERSONAS - צוות מערכת חדשות עם גישה מלאה לכלים ===
PERSONAS = {
  "FOCUS": {
    "tag": "🎯 עורך ראשי:",
    "system": """אתה העורך הראשי וראש דסק המודיעין בחדר המערכת 'חדשות בזק'.
תפקידך: לנהל את חדר החדשות, לענות לשאלות המפעיל, להסביר תמונת מצב, להפעיל כלים ולהנחות את הסוכנים.

כלים זמינים שבאפשרותך להפעיל באופן עצמאי במידת הצורך:
1. הפעלת סריקת מודיעין: שלב בתשובתך [כלי: סריקה]
2. הנחיית סוכן אחר לבצע משימה: שלב בתשובתך [כלי: קריאה: @עורך נסח מבזק על ...] או [כלי: קריאה: @מבקר בדוק ...]
3. פרסום מבזק מאושר לערוץ: שלב בתשובתך [כלי: פרסום: נוסח המבזק]
4. עדכון פרומפט: שלב בתשובתך [כלי: עדכון_פרומפט: שם_הסוכן: הטקסט]

סגנון: אנושי, חכם, קצר, מדויק ומקצועי (כמו עורך בכיר בחדר חדשות).
חוק ברזל: ענה בעברית בלבד. אסור לכתוב באנגלית, אסור לכתוב תהליכי חשיבה פנימיים ואסור לפלוט JSON."""
  },
  "EDITOR": {
    "tag": "✍️ העורך:",
    "system": """אתה עורך המבזקים של 'חדשות בזק'.
תפקידך: 
1. לנסח מבזקי חדשות חדים, קצרים וקצביים על אירועים אקטואליים אמיתיים בעולם (1-2 שורות בעברית רהוטה).
2. בשיחה פנימית עם העורך הראשי או המפעיל: לענות באופן ישיר וטבעי כקולגה בחדר החדשות (ולא לנסח מבזק מומצא על העבודה הפנימית של המערכת).

כלים זמינים:
1. העברת טיוטה לבדיקת מבקר: [כלי: קריאה: @מבקר בדוק את הטיוטה הבאה: ...]
2. בקשת סריקת מקורות: [כלי: סריקה]
3. פרסום לערוץ (לאחר אישור): [כלי: פרסום: נוסח המבזק]

סגנון: כותב כמו חבר שמעדכן, עברית רהוטה וזורמת.
חוק ברזל: ענה בעברית בלבד, ישיר וללא שום אנגלית."""
  },
  "CRITIC": {
    "tag": "🔍 המבקר:",
    "system": """אתה מבקר האיכות והעריכה של חדר המערכת.
תפקידך: לבדוק טיוטות, לוודא דיוק עובדתי, שפה טבעית והיעדר כפילויות.

כלים זמינים:
1. אישור ופרסום מיידי לערוץ: [כלי: פרסום: נוסח המבזק]
2. החזרת הערות לעורך לשכתוב: [כלי: קריאה: @עורך תקן את הניסוח הבא: ...]
3. בקשת סריקה מעודכנת: [כלי: סריקה]

סגנון: ענייני, חד, תמציתי ומנומק.
חוק ברזל: ענה בעברית בלבד."""
  },
  "PROMPT_ENGINEER": {
    "tag": "🛠️ מהנדס הפרומפט:",
    "system": """אתה מהנדס הפרומפט והאחראי הטכני על מודלי ה-AI במערכת.
תפקידך: לענות על שאלות טכניות על הפרומפטים, לכייל את הסוכנים ולעדכן הגדרות.

כלים זמינים:
1. עדכון פרומפט: [כלי: עדכון_פרומפט: שם_הסוכן: הטקסט]
2. בדיקת סריקה: [כלי: סריקה]

סגנון: מקצועי, טכני, קצר וברור.
חוק ברזל: ענה בעברית בלבד."""
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
        msgs.append({"role":"user","content": "דיון אחרון בחדר המערכת (כולל טיוטות פעילות והודעות שנשלחו):\n" + history_text[-3000:]})
    msgs.append({"role":"user","content": f"הודעה/בקשה מהמפעיל: {user_content}"})
    out = _call_nvidia(msgs, max_tokens=600, temperature=0.2)
    if out:
        return f"{p['tag']} {out}"
    return None

def send_to_group(text):
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

    try:
        r = requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": gid, "text": display_text, "parse_mode":"HTML", "disable_web_page_preview": True},
            timeout=10)
        ok = r.status_code==200 and r.json().get("ok")
        if not ok:
            # Fallback to plain text
            r = requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={"chat_id": gid, "text": display_text, "disable_web_page_preview": True},
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

        payload = {"type":"PUBLISH_CONTENT","source_id":source_id,"text":clean_text,"reply_to_source_id":None}
        r = requests.post(SYNC_ENDPOINT, json=payload, timeout=12)
        ok = r.status_code==200
        send_to_group(f"📤 {'הידיעה פורסמה בהצלחה לערוץ! ✅' if ok else 'הפרסום לערוץ נכשל ❌'}\n\n{clean_text[:120]}...")
        return ok
    except Exception as e:
        print(f"publish err {e}")
        send_to_group(f"❌ שגיאה בפרסום לערוץ: {e}")
        return False

def save_prompt_patch(agent, patch, is_remove=False):
    if not patch or len(patch)<5: return
    key = "PROMPT_PATCH" if agent=="ALL" else f"PROMPT_PATCH_{agent}"
    if is_remove:
        patch = f"[הסרה] {patch}"
    try:
        if SCANNER_URL:
            requests.post(SCANNER_URL, json={"action":"setProps", key: patch.strip()[:1000]}, timeout=8)
            if is_remove and len(patch)<30:
                try: requests.post(SCANNER_URL, json={"action":"deleteProps", key: key}, timeout=8)
                except: pass
            send_to_group(f"🛠️ פרומפט עודכן בהצלחה ({key}):\n{patch[:250]}")
            print(f"saved {key}: {patch[:80]}")
    except Exception as e:
        print(f"patch save err {e}")

def wake_google():
    for url in [SCANNER_URL, SYNC_ENDPOINT]:
        if not url: continue
        try: requests.get(url, timeout=30); print(f"woke {url[:40]}")
        except Exception as e:
            if "timeout" not in str(e).lower(): print(f"wake err {e}")

def execute_agent_tools(agent_name, agent_output, history_str):
    """Parses and executes any autonomous tools requested by the agent."""
    if not agent_output: return
    
    # 1. Check for scan tool [כלי: סריקה]
    if "[כלי: סריקה]" in agent_output:
        print(f"[{agent_name}] Triggered SCAN tool")
        try: requests.get(SCANNER_URL, timeout=10)
        except: pass

    # 2. Check for publish tool [כלי: פרסום: ...]
    pub_match = re.search(r"\[כלי:\s*פרסום:\s*([^\]]+)\]", agent_output)
    if pub_match:
        to_pub = pub_match.group(1).strip()
        print(f"[{agent_name}] Triggered PUBLISH tool: {to_pub[:60]}")
        publish_to_channel(to_pub, source_id=f"{agent_name.lower()}_{int(time.time())}")

    # 3. Check for prompt update tool [כלי: עדכון_פרומפט: ...]
    prompt_match = re.search(r"\[כלי:\s*עדכון_פרומפט:\s*([^:]+):\s*([^\]]+)\]", agent_output)
    if prompt_match:
        target_agent = prompt_match.group(1).strip()
        patch_body = prompt_match.group(2).strip()
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

        if target_persona and target_persona != agent_name:
            print(f"[{agent_name}] Delegating to {target_persona}: {task[:60]}")
            time.sleep(1.2)
            sub_resp = run_agent(target_persona, task, history_str + "\n" + agent_output)
            if sub_resp:
                send_to_group(sub_resp)
                execute_agent_tools(target_persona, sub_resp, history_str + "\n" + agent_output)

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
    DURATION = 6*3600  # 6 hours
    last_wake = 0
    
    chat_history = []

    while time.time() - start < DURATION:
        try:
            # Wake google every 120s quietly
            if time.time() - last_wake > 120:
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
                if c_num != g_num and c_num not in ["3951660065", "5469136458"]:
                    continue

                from_user = msg.get("from", {})
                is_bot = from_user.get("is_bot", False)
                user_name = from_user.get('first_name', 'מפעיל')
                text = (msg.get("text") or msg.get("caption") or "").strip()
                if not text or len(text) < 2: 
                    continue

                # Record all messages (including bot drafts and agent replies) into chat_history
                sender_label = "מערכת (טיוטה)" if ("טיוטה לפרסום" in text or text.startswith("📝")) else user_name
                chat_history.append(f"[{sender_label}]: {text}")
                if len(chat_history) > 25: chat_history = chat_history[-25:]
                history_str = "\n".join(chat_history)

                # Do not trigger auto-reply to bot messages
                if is_bot or text.startswith("📝 <b>טיוטה לפרסום</b>") or text.startswith("🎯 עורך ראשי:") or text.startswith("✍️ העורך:") or text.startswith("🔍 המבקר:"):
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
                    
                    polished = run_agent("EDITOR", f"לטש למבזק חדשותי מוכן לפרסום (1-2 שורות בעברית טבעית): \"{to_pub_raw}\"", history_str)
                    polished_text = re.sub(r"^.*?:\s*", "", polished or to_pub_raw, count=1).strip()
                    
                    critic = run_agent("CRITIC", f"בדוק טיוטה זו לפרסום מיידי: \"{polished_text}\"", history_str)
                    if critic and ("לא" in critic or "נפסל" in critic):
                        send_to_group(f"⛔ הבודק העיר על הטיוטה ולא אישר פרסום:\n{critic}")
                        continue
                    
                    publish_to_channel(polished_text, source_id=f"manual_{int(time.time())}")
                    continue

                # === 3. פקודות צפייה ועריכת פרומפט ===
                if "הראה פרומפט" in text or "הצג פרומפט" in text or "show prompt" in lower:
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
                            send_to_group(f"📄 פרומפט {k}:\n{v[:3000]}")
                            time.sleep(0.6)
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
                        send_to_group(f"✅ פרומפט {which} עודכן בהצלחה.")
                    except Exception as e:
                        send_to_group(f"❌ שגיאה בעדכון פרומפט: {e}")
                    continue

                # === 4. פנייה ישירה לסוכן ספציפי (עם ביצוע כלים אוטונומי) ===
                single_agent = None
                if any(k in text for k in ["@עורך", "עורך ת", "תקרא לעורך"]): single_agent = "EDITOR"
                elif any(k in text for k in ["@מבקר", "מבקר ת", "תקרא למבקר"]): single_agent = "CRITIC"
                elif any(k in text for k in ["@מיקוד", "אחראי מיקוד", "תקרא למיקוד"]): single_agent = "FOCUS"
                elif any(k in text for k in ["@מהנדס", "מהנדס הפרומפט"]): single_agent = "PROMPT_ENGINEER"

                if single_agent:
                    resp = run_agent(single_agent, text, history_str)
                    if resp:
                        send_to_group(resp)
                        chat_history.append(resp)
                        execute_agent_tools(single_agent, resp, history_str)
                    continue

                # === 5. דיון מערכת בין כל הסוכנים ===
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

                # === 6. שיחה טבעית של המפעיל (מענה עורך ראשי + הפעלת כלים אוטונומית) ===
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
