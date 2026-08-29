import os, json, time, requests, traceback, re

# === CONFIG (from GitHub Secrets, not exposed in code) ===
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN","").strip() or os.environ.get("EDITOR_BOT_TOKEN","").strip()
GROUP_ID = os.environ.get("EDITOR_GROUP_ID","").strip()  # -5469136458
NVIDIA_KEY = os.environ.get("NVIDIA_API_KEY","").strip()
SCANNER_URL = os.environ.get("SCANNER_URL","").strip()  # to wake Google
SYNC_ENDPOINT = os.environ.get("SYNC_ENDPOINT","").strip()

# Fallback chain - קימי -> מינימקס3 -> אולטרא -> דיפסיק פרו -> פלאש -> לא קורס
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

# === PERSONAS - עברית טבעית, חדה, ללא הרהורים באנגלית ===
PERSONAS = {
  "FOCUS": {
    "tag": "🎯 אחראי מיקוד:",
    "system": "אתה 'אחראי מיקוד' ועורך ראשי בחדר מערכת 'חדשות בזק'.\nתפקידך: לקבוע במה להתמקד ומה הנושא הדחוף והחשוב ביותר כעת מתוך כלל המקורות.\nחוק ברזל: ענה בעברית בלבד, ישיר, קצר (2-3 שורות). אסור לחלוטין לכתוב מילה באנגלית, ואסור לכתוב את תהליך המחשבה או 'The user wants'. אל תחזיר JSON."
  },
  "EDITOR": {
    "tag": "✍️ העורך:",
    "system": "אתה 'העורך' - כותב מבזקים אנושי וחד בחדשות בזק.\nתפקידך: לנסח ידיעה אחת טבעית, קצרה וקצבית (1-2 שורות או רשימת נקודות).\nחוק ברזל: ענה בעברית בלבד, ישיר, ללא פתיחים קבועים וללא אנגלית. אסור לכתוב הרהורים."
  },
  "CRITIC": {
    "tag": "🔍 המבקר:",
    "system": "אתה 'המבקר' בחדר המערכת.\nתפקידך: לבדוק את הטיוטה ולוודא שהיא טבעית, מדויקת וללא כפילויות.\nחוק ברזל: ענה בעברית בלבד, קצר וענייני. אם הטיוטה טובה: 'אושר - ניסוח חד ומדויק'. אם לא: הצע שכתוב קצר בעברית."
  },
  "PROMPT_ENGINEER": {
    "tag": "🛠️ מהנדס הפרומפט:",
    "system": "אתה 'מהנדס הפרומפט' של המערכת.\nתפקידך: לעזור למפעיל לכוונן את הפרומפטים לפי בקשה מפורשת בלבד.\nחוק ברזל: ענה בעברית בלבד, קצר, מדויק וטכני."
  }
}

def clean_llm_output(txt):
    if not txt: return ""
    cleaned = txt.strip()
    # Strip any English thinking/reasoning prefixes
    if "The user wants" in cleaned or "I need to" in cleaned or "Active Prompt" in cleaned:
        # Find first Hebrew letter
        import re
        hebrew_match = re.search(r"[\u0590-\u05FF]", cleaned)
        if hebrew_match:
            cleaned = cleaned[hebrew_match.start():].strip()
        else:
            # If completely English thinking, discard
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
        msgs.append({"role":"user","content": "הקשר (היסטוריית ערוץ + דיון קבוצה):\n"+history_text[:3500]})
    msgs.append({"role":"user","content": user_content[:3500]})
    out = _call_nvidia(msgs, max_tokens=700, temperature=0.2)
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

    try:
        # First attempt with HTML formatting
        r = requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": gid, "text": text, "parse_mode":"HTML", "disable_web_page_preview": True},
            timeout=10)
        ok = r.status_code==200 and r.json().get("ok")
        if not ok:
            # Automatic fallback: send as plain text if HTML parsing failed
            r = requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={"chat_id": gid, "text": text, "disable_web_page_preview": True},
                timeout=10)
            ok = r.status_code==200 and r.json().get("ok")
            if not ok: print(f"send fail {r.text[:200]}")
        return ok
    except Exception as e:
        print(f"send err {e}")
        return False

def publish_to_channel(text, source_id="manual"):
    if not SYNC_ENDPOINT:
        send_to_group("❌ כלי publish_to_channel: אין SYNC_ENDPOINT")
        return False
    try:
        clean_text = str(text or "").strip()
        # Clean markdown code fences and JSON if present
        clean_text = re.sub(r"^```(?:json)?\s*", "", clean_text, flags=re.I)
        clean_text = re.sub(r"\s*```$", "", clean_text)
        if clean_text.startswith("{") and ("final_text" in clean_text or "action" in clean_text):
            try:
                m = re.search(r"\{[\s\S]*\}", clean_text)
                if m:
                    pj = json.loads(m.group(0))
                    clean_text = str(pj.get("final_text") or pj.get("text") or clean_text).strip()
            except: pass
        if not clean_text or clean_text.startswith('{"') or '"action":' in clean_text:
            send_to_group("🛑 כלי publish_to_channel נחסם: הטקסט מכיל JSON גולמי")
            return False

        payload = {"type":"PUBLISH_CONTENT","source_id":source_id,"text":clean_text,"reply_to_source_id":None}
        r = requests.post(SYNC_ENDPOINT, json=payload, timeout=12)
        ok = r.status_code==200
        send_to_group(f"📤 כלי publish_to_channel: {'פורסם לערוץ ✅' if ok else 'כשל ❌'}: {clean_text[:90]}")
        return ok
    except Exception as e:
        print(f"publish err {e}")
        send_to_group(f"❌ כלי publish_to_channel שגיאה: {e}")
        return False

def save_prompt_patch(agent, patch, is_remove=False):
    if not patch or len(patch)<5: return
    key = "PROMPT_PATCH" if agent=="ALL" else f"PROMPT_PATCH_{agent}"
    # תמיכה בהסרה: אם is_remove - נמחק את הפאץ' או נוסיף הוראת הסרה
    if is_remove:
        patch = f"[הסרה] {patch}"
    try:
        if SCANNER_URL:
            requests.post(SCANNER_URL, json={"action":"setProps", key: patch.strip()[:1000]}, timeout=8)
            # גם מחיקה אם ביקש להסיר חלק
            if is_remove and len(patch)<30:
                try: requests.post(SCANNER_URL, json={"action":"deleteProps", key: key}, timeout=8)
                except: pass
            send_to_group(f"🛠️ כלי save_prompt_patch: {key} עודכן ✅\n{patch[:250]}")
            print(f"saved {key}: {patch[:80]}")
    except Exception as e:
        print(f"patch save err {e}")

def wake_google():
    for url in [SCANNER_URL, SYNC_ENDPOINT]:
        if not url: continue
        try: requests.get(url, timeout=30); print(f"woke {url[:40]}")
        except Exception as e:
            # timeout is ok - scanner still running in background
            if "timeout" not in str(e).lower(): print(f"wake err {e}")

def main():
    print(f"Starting group_responder GROUP={GROUP_ID} bot={BOT_TOKEN[:6]}... models={KIMI_MODELS[0]}...")
    
    # Ensure clean polling by removing any active webhooks on this bot token
    if BOT_TOKEN:
        try:
            rw = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook", timeout=8)
            print(f"Webhook reset status: {rw.status_code}")
        except Exception as e:
            print(f"deleteWebhook warning: {e}")

    # state
    offset = 0
    try:
        with open("offset.txt","r") as f: offset=int(f.read().strip() or 0)
    except: pass
    start = time.time()
    DURATION = 6*3600  # 6 hours
    last_wake = 0
    while time.time() - start < DURATION:
        try:
            # wake google every 90s
            if time.time() - last_wake > 90:
                wake_google()
                last_wake = time.time()
            # poll Telegram with timeout 15s for efficient long polling
            r = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates",
                params={"offset": offset, "timeout": 15, "limit": 30}, timeout=25)
            if r.status_code != 200:
                time.sleep(1.2); continue
            data = r.json()
            for upd in data.get("result", []):
                offset = max(offset, upd["update_id"]+1)
                # write offset
                try: open("offset.txt","w").write(str(offset))
                except: pass
                msg = upd.get("message") or upd.get("edited_message")
                if not msg: continue
                chat = msg.get("chat",{})
                # Flexible chat ID matching for supergroups
                chat_id_str = str(chat.get("id", ""))
                c_num = chat_id_str.replace("-100", "").replace("-", "")
                g_num = str(GROUP_ID).replace("-100", "").replace("-", "")
                
                if c_num != g_num and c_num not in ["3951660065", "5469136458"]:
                    continue

                from_user = msg.get("from", {})
                if from_user.get("is_bot"): 
                    continue  # ignore bot messages

                text = (msg.get("text") or msg.get("caption") or "").strip()
                if not text or len(text) < 2: 
                    continue

                # Ignore automated draft broadcasts to avoid feedback cascade
                if text.startswith("📝") or "טיוטה לפרסום" in text or text.startswith("🤖") or "כלי wake_scanner" in text or "כלי publish_to_channel" in text:
                    continue

                print(f"[HUMAN in chat {chat_id_str}] {from_user.get('first_name')}: {text[:80]}")
                lower = text.lower()
                # === קריאה לסוכן בודד - ברור לגמרי ===
                single = None
                if any(k in text for k in ["@עורך","עורך ת","תקרא לעורך"]): single="EDITOR"
                elif any(k in text for k in ["@מבקר","מבקר ת","תקרא למבקר"]): single="CRITIC"
                elif any(k in text for k in ["@מיקוד","אחראי מיקוד","תקרא למיקוד"]): single="FOCUS"
                elif any(k in text for k in ["@מהנדס","מהנדס הפרומפט"]): single="PROMPT_ENGINEER"
                elif "תדברו ביניכם" in text or "שיחה ביניכם" in text:
                    # סוכנים מדברים ביניהם - סבב 1
                    history_text = f"דיון קבוצה: {text}"
                    for name in ["FOCUS","EDITOR","CRITIC"]:
                        out = run_agent(name, f"שיחה בין סוכנים: הגב לקודמך. הודעת מפעיל: \"{text}\"", history_text)
                        if out: send_to_group(out); history_text += "\n"+out; time.sleep(1.2)
                    continue
                if single:
                    # קריאה לסוכן אחד בלבד
                    history_text = f"קריאה ישירה ל-{single}: {text}"
                    out = run_agent(single, text, history_text)
                    if out: send_to_group(out)
                    # גם המבקר מגיב אם זה עורך
                    if single=="EDITOR" and out:
                        cr = run_agent("CRITIC", f"טיוטת {single}: {out}", history_text)
                        if cr: send_to_group(cr)
                    continue
                # === שליטה מלאה: הראה/ערוך פרומפט ===
                if "הראה פרומפט" in text or "הצג פרומפט" in text or "show prompt" in lower:
                    which = "ALL"
                    if "עורך" in text: which="EDITOR"
                    elif "מבקר" in text: which="CRITIC"
                    elif "מיקוד" in text: which="FOCUS"
                    elif "ראשי" in text or "main" in lower: which="MAIN"
                    try:
                        r = requests.post(SCANNER_URL, json={"action":"getPrompt","which":which}, timeout=12)
                        j = r.json() if r.headers.get("content-type","").startswith("application/json") else json.loads(r.text)
                        # send each prompt truncated
                        for k,v in j.items():
                            if k=="PATCHES": continue
                            send_to_group(f"📄 פרומפט {k}:\n{v[:3500]}")
                            time.sleep(0.8)
                        if j.get("PATCHES"):
                            send_to_group(f"🩹 פאצ'ים: {json.dumps(j['PATCHES'], ensure_ascii=False)[:1000]}")
                    except Exception as e:
                        send_to_group(f"❌ שגיאת הראה פרומפט: {e}")
                    continue
                if ("ערוך פרומפט" in text or "קבע פרומפט" in text or "set prompt" in lower) and ":" in text:
                    which = "ALL"
                    if "עורך" in text: which="EDITOR"
                    elif "מבקר" in text: which="CRITIC"
                    elif "מיקוד" in text: which="FOCUS"
                    elif "ראשי" in text or "main" in lower: which="MAIN"
                    new_text = text.split(":",1)[1].strip()
                    if len(new_text) < 10:
                        send_to_group("❓ כתוב: ערוך פרומפט של העורך: [טקסט מלא חדש]")
                        continue
                    try:
                        r = requests.post(SCANNER_URL, json={"action":"setPrompt","which":which,"text":new_text}, timeout=12)
                        send_to_group(f"✅ פרומפט {which} עודכן ({len(new_text)} תווים): {r.text[:200]}")
                    except Exception as e:
                        send_to_group(f"❌ שגיאת ערוך פרומפט: {e}")
                    continue
                # === החלטת AI איזה כלי להפעיל ===
                router = run_agent("FOCUS", f"המפעיל כתב בקבוצה: \"{text}\"\nהחלט איזה כלי להפעיל: wake_scanner / publish_to_channel / save_prompt_patch / none. ענה בשורה אחת: כלי: [שם] + הסבר קצר.", f"כלים זמינים: wake_scanner (סרוק חדשות), publish_to_channel (פרסם לערוץ), save_prompt_patch (עדכן פרומפט), none (רק דיון)")
                # אם ה-AI החליט על כלי - בצע, אם לא - המשך לדיון רגיל
                chosen = ""
                if router:
                    if "wake_scanner" in router.lower():
                        chosen = "wake_scanner"
                        send_to_group(router)
                        send_to_group("🔍 כלי wake_scanner: סורק 50 מקורות...")
                        try:
                            r = requests.get(SCANNER_URL, timeout=30)
                            send_to_group(f"✅ סריקה הוערה ({r.status_code}), טיוטה תגיע תוך דקה")
                        except Exception as e:
                            # timeout זה גם הצלחה - הסורק רץ ברקע גם אם גוגל איטי
                            if "Read timed out" in str(e) or "timeout" in str(e).lower():
                                send_to_group(f"✅ סריקה הוערה (timeout אבל רץ ברקע), טיוטה תגיע תוך דקה")
                            else:
                                send_to_group(f"❌ שגיאת סריקה: {e}")
                        continue
                    elif "publish_to_channel" in router.lower():
                        chosen = "publish"
                        # חלץ טקסט לפרסום באמצעות AI
                        m = re.search(r"(?:שלח לערוץ|פרסם|publish)\s*[:：]?\s*(.*)", text, re.I)
                        to_pub_raw = m.group(1).strip() if m and m.group(1) else text
                        # אם ה-router החליט publish אבל אין טקסט ברור - בקש מהעורך לנסח
                        if len(to_pub_raw) < 10:
                            to_pub_raw = text
                        send_to_group(router)
                        send_to_group("✍️ כלי polish: מלטש לפני פרסום...")
                        polished = run_agent("EDITOR", f"לטש והפוך למבזק מוכן לפרסום: \"{to_pub_raw}\"", f"בקשת מפעיל: {text}")
                        if polished:
                            polished_text = re.sub(r"^.*?:\s*", "", polished, count=1).strip()[:1100]
                            if "לא הבנתי" in polished_text:
                                send_to_group(polished)
                                continue
                            critic2 = run_agent("CRITIC", f"טיוטה: {polished_text}", "")
                            if critic2: send_to_group(critic2)
                            publish_to_channel(polished_text, source_id=f"manual_{int(time.time())}")
                        continue
                    elif "save_prompt_patch" in router.lower():
                        chosen = "patch"
                        # חלץ פרומפט להצלה
                        # יטופל בהמשך בבלוק הפאץ'
                        pass
                    else:
                        # none - המשך לדיון רגיל, שלח את החלטת ה-router כ-FOCUS
                        send_to_group(router)
                # אם ה-router בחר patch - טפל
                if chosen == "patch":
                    # המשך לבלוק עדכון פרומפט למטה
                    pass
                elif router and "none" not in router.lower() and chosen == "":
                    # router החליט על דיון רגיל - כבר שלחנו, המשך ל-EDITOR/CRITIC
                    pass
                # אם הגענו לכאן בלי continue - זה דיון רגיל
                # 1. פרסום לערוץ fallback אם ה-AI פספס ויש מילת מפתח
                if chosen == "" and any(k in text for k in ["שלח לערוץ", "שלח הודעה לערוץ"]) and "publish_to_channel" not in (router or ""):
                    # חילוץ גם בלי נקודותיים: "שלח לערוץ עדכון נו כב" -> "עדכון נו כב"
                    m = re.search(r"(?:שלח לערוץ|פרסם|publish|שלח הודעה לערוץ)\s*[:：]?\s*(.*)", text, re.I)
                    to_pub_raw = m.group(1).strip() if m else ""
                    if "אירוע" in text or "יש חדש" in text:
                        send_to_group("🔍 כלי wake_scanner: בודק אירועים טריים...")
                        try: requests.get(SCANNER_URL, timeout=10)
                        except: pass
                        if not to_pub_raw or len(to_pub_raw)<4:
                            send_to_group("✅ סריקה הוערה, ממתין לחומר גלם")
                            continue
                    if to_pub_raw and len(to_pub_raw)>3:
                        # ג'יבריש קצר? בקש הבהרה במקום לפרסם זבל
                        if len(to_pub_raw)<10 or to_pub_raw.strip() in ["עדכון נו כב","נו כב","בדיקה"]:
                            send_to_group("❓ כלי publish_to_channel: הטקסט קצר/לא מובן — כתוב: שלח לערוץ: [טקסט מלא, לפחות 10 תווים]")
                            continue
                        send_to_group("✍️ כלי polish: מלטש לפני פרסום...")
                        history_text2 = f"בקשת פרסום מהמפעיל: {to_pub_raw}"
                        polished = run_agent("EDITOR", f"לטש והפוך למבזק מוכן לפרסום בעברית טבעית (בלי 'מילה:' קבוע): \"{to_pub_raw}\"", history_text2)
                        if polished:
                            polished_text = re.sub(r"^.*?:\s*", "", polished, count=1).strip()  # הסר "✍️ העורך:"
                            polished_text = polished_text[:1100]
                            if "לא הבנתי" in polished_text:
                                send_to_group(polished)  # בקשת הבהרה מהעורך
                                continue
                            critic2 = run_agent("CRITIC", f"טיוטה מלוטשת: {polished_text}\nאשר או הצע תיקון קצר", history_text2)
                            if critic2:
                                send_to_group(critic2)
                                if "אושר" not in critic2 and len(critic2)>20:
                                    # אם המבקר הציע תיקון - השתמש בו
                                    pass
                            publish_to_channel(polished_text, source_id=f"manual_{int(time.time())}")
                        else:
                            send_to_group("❌ כלי polish נכשל, מפרסם גולמי")
                            publish_to_channel(to_pub_raw, source_id=f"manual_{int(time.time())}")
                    else:
                        send_to_group("❓ כלי publish_to_channel: כתוב: שלח לערוץ: [טקסט מלא, לפחות 10 תווים]")
                    continue
                # 2. עדכון/הסרת פרומפט פר-סוכן: תומך גם ב"הסר"
                is_remove = "הסר" in text or "מחק" in text or "remove" in lower
                patch_match = re.search(r"(?:עדכן|הסר|מחק).*?פרומפט.*?של\s*(העורך|המבקר|מיקוד|הכל|העורך הראשי|מהנדס)?\s*[:：]?\s*(.+)", text, re.I)
                if patch_match or (("עדכן" in text or "הסר" in text) and "פרומפט" in text):
                    target = "ALL"
                    if patch_match:
                        raw_target = patch_match.group(1) or ""
                        patch_text = patch_match.group(2).strip()
                        if "עורך" in raw_target: target = "EDITOR"
                        elif "מבקר" in raw_target: target = "CRITIC"
                        elif "מיקוד" in raw_target: target = "FOCUS"
                        elif "מהנדס" in raw_target: target = "PROMPT_ENGINEER"
                    else:
                        m2 = re.search(r"[:：]\s*(.+)", text)
                        patch_text = m2.group(1).strip() if m2 else text
                        if "עורך" in text: target = "EDITOR"
                        elif "מבקר" in text: target = "CRITIC"
                        elif "מיקוד" in text: target = "FOCUS"
                    if len(patch_text)>5:
                        save_prompt_patch(target, patch_text, is_remove=is_remove)
                        # הסבר איזה פרומפט עודכן: ראשי או פר-סוכן
                        tool_name = "פרומפט ראשי (AI_PROTOCOL)" if target=="ALL" else f"פרומפט {target}"
                        send_to_group(f"ℹ️ כלי save_prompt_patch: עודכן {tool_name}")
                        continue
                # 3. דיון רגיל - פרסונות עונות בסדר
                history_text = f"הודעת מפעיל: {text}\n(קבוצה {GROUP_ID})"
                # === PERSONA ORDER - ברור מי שולח ===
                focus = run_agent("FOCUS", f"המפעיל כתב: \"{text}\" - על מה להתמקד? הסבר בעברית.", history_text)
                if focus: send_to_group(focus); time.sleep(1.3)
                editor = run_agent("EDITOR", f"המפעיל כתב: \"{text}\" - נסח הודעה בהתאם בעברית טבעית.", history_text + ("\n"+focus if focus else ""))
                if editor: send_to_group(editor); time.sleep(1.3)
                if editor:
                    critic = run_agent("CRITIC", f"טיוטה: {editor}\nבדוק אם אנושי?", history_text)
                    if critic: send_to_group(critic); time.sleep(1.2)
                if "פרומפט" in text or "prompt" in lower or (focus and "הצעת פרומפט" in focus):
                    pe = run_agent("PROMPT_ENGINEER", f"המפעיל: {text}\nFOCUS: {focus}\nהאם לעדכן פרומפט?", history_text)
                    if pe: send_to_group(pe)
                try:
                    if focus and "הצעת פרומפט" in focus:
                        m=re.search(r"הצעת פרומפט:\s*(.+)", focus)
                        if m and len(m.group(1))>10:
                            save_prompt_patch("ALL", m.group(1).strip())
                except: pass

        except Exception as e:
            print(f"loop err {e}")
            traceback.print_exc()
        time.sleep(1.4)
    print("6h done, exiting")

if __name__ == "__main__":
    main()
