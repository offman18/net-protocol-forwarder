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

# === PERSONAS - שמות בעברית, ברור מי כותב, מבינים הקשר ===
PERSONAS = {
  "FOCUS": {
    "tag": "🎯 אחראי מיקוד",
    "system": "אתה 'אחראי מיקוד' בחדר מערכת 'חדשות בזק'. אתה מבין עברית מצוין וחושב כמו עורך חדשות. תפקידך להחליט על מה להתמקד. קבל הודעת מפעיל + חומר גלם + היסטוריית ערוץ. ענה בעברית טבעית וקצרה (2-3 שורות), לא JSON. הסבר מה חשוב עכשיו ולמה. אם רואה תבנית חוזרת שצריך לתקן בפרומפט - הוסף בסוף: הצעת פרומפט: ..."
  },
  "EDITOR": {
    "tag": "✍️ העורך",
    "system": "אתה 'העורך' - כותב מבזקים אנושי. אתה מבין עברית מצוין וכותב כמו אדם שמעדכן חברים, לא כמו רובוט. כתוב ידיעה אחת חדה וטבעית (1-2 שורות או רשימת • לסקר). אסור לפתוח כל פעם ב-'מילה:' או 'קמפיין בחירות:', אסור <i>, אימוג'י רק מדי פעם. חבר ל-thread אם קשור. ענה בעברית טבעית בלבד."
  },
  "CRITIC": {
    "tag": "🔍 המבקר",
    "system": "אתה 'המבקר' - מבין עברית מצוין ובודק אם הטיוטה נשמעת אנושית. קבל טיוטה + היסטוריה. בדוק: האם רובוטי? חוזר על תבנית? אם טוב - כתוב 'אושר - נשמע אנושי'. אם צריך תיקון - הצע שכתוב קצר בעברית. תמיד חד וקצר."
  },
  "PROMPT_ENGINEER": {
    "tag": "🛠️ מהנדס הפרומפט",
    "system": "אתה 'מהנדס הפרומפט' - מבין עברית וטכני. קבל פרומפט + טיוטה + ביקורת. אם צריך לעדכן פרומפט (למשל איסור תבנית) - כתוב בעברית: מציע עדכון פרומפט: ... אם לא - כתוב: אין צורך בשינוי."
  }
}

def _call_nvidia(messages, max_tokens=600, temperature=0.7):
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
                    print(f"[NVIDIA] {model} ok")
                    return txt.strip()
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
    out = _call_nvidia(msgs, max_tokens=700)
    if out:
        return f"{p['tag']} {out}"
    return None

def send_to_group(text):
    if not BOT_TOKEN or not GROUP_ID: 
        print("missing BOT_TOKEN/GROUP_ID")
        return False
    try:
        r = requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": GROUP_ID, "text": text, "parse_mode":"HTML", "disable_web_page_preview": True},
            timeout=10)
        ok = r.status_code==200 and r.json().get("ok")
        if not ok: print(f"send fail {r.text[:200]}")
        return ok
    except Exception as e:
        print(f"send err {e}")
        return False

def publish_to_channel(text, source_id="manual"):
    if not SYNC_ENDPOINT:
        send_to_group("❌ אין SYNC_ENDPOINT - לא יכול לפרסם לערוץ")
        return False
    try:
        payload = {"type":"PUBLISH_CONTENT","source_id":source_id,"text":text,"reply_to_source_id":None}
        r = requests.post(SYNC_ENDPOINT, json=payload, timeout=12)
        ok = r.status_code==200
        send_to_group(f"📤 {'פורסם לערוץ' if ok else 'כשל פרסום'}: {text[:80]}")
        return ok
    except Exception as e:
        print(f"publish err {e}")
        send_to_group(f"❌ שגיאת פרסום: {e}")
        return False

def save_prompt_patch(agent, patch):
    if not patch or len(patch)<8: return
    key = "PROMPT_PATCH" if agent=="ALL" else f"PROMPT_PATCH_{agent}"
    try:
        if SCANNER_URL:
            requests.post(SCANNER_URL, json={"action":"setProps", key: patch.strip()[:800]}, timeout=8)
            send_to_group(f"🛠️ {agent}: פרומפט עודכן ✅\n{patch[:200]}")
            print(f"saved {key}")
    except Exception as e:
        print(f"patch save err {e}")

def wake_google():
    for url in [SCANNER_URL, SYNC_ENDPOINT]:
        if not url: continue
        try: requests.get(url, timeout=8); print(f"woke {url[:40]}")
        except: pass

def main():
    print(f"Starting group_responder GROUP={GROUP_ID} bot={BOT_TOKEN[:6]}... models={KIMI_MODELS[0]}...")
    # state
    offset = 0
    # load offset from file if exists
    try:
        with open("offset.txt","r") as f: offset=int(f.read().strip() or 0)
    except: pass
    start = time.time()
    DURATION = 6*3600  # 6 hours
    last_wake = 0
    # history buffer for agents (last 50 channel messages not available here, will be passed via wake)
    # Instead we fetch group history as context
    while time.time() - start < DURATION:
        try:
            # wake google every 90s
            if time.time() - last_wake > 90:
                wake_google()
                last_wake = time.time()
            # poll Telegram
            r = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates",
                params={"offset": offset, "timeout": 1, "limit": 30}, timeout=12)
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
                if str(chat.get("id")) != str(GROUP_ID): continue
                from_user = msg.get("from",{})
                if from_user.get("is_bot"): continue  # ignore bot messages
                text = (msg.get("text") or msg.get("caption") or "").strip()
                if not text or len(text)<2: continue
                if text.startswith("/"): continue
                print(f"[HUMAN] {from_user.get('first_name')}: {text[:80]}")
                lower = text.lower()
                # === כלים מיידיים ===
                # 1. פרסום לערוץ: "שלח לערוץ: ...", "פרסם: ...", "publish: ..." - עובר דרך עורך+מבקר, לא שולח גולמי
                if any(k in text for k in ["שלח לערוץ", "פרסם", "publish", "שלח הודעה לערוץ"]):
                    to_pub_raw = text.split(":",1)[1].strip() if ":" in text else re.sub(r"שלח לערוץ|פרסם|publish|שלח הודעה לערוץ","",text, flags=re.I).strip()
                    if "אירוע" in text or "יש חדש" in text:
                        send_to_group("🔍 בודק אירועים טריים...")
                        try: requests.get(SCANNER_URL, timeout=10)
                        except: pass
                    if to_pub_raw and len(to_pub_raw)>3:
                        send_to_group("✍️ מלטש לפני פרסום...")
                        history_text2 = f"בקשת פרסום מהמפעיל: {to_pub_raw}"
                        polished = run_agent("EDITOR", f"לטש והפוך למבזק מוכן לפרסום בעברית טבעית (בלי 'מילה:' קבוע): \"{to_pub_raw}\"", history_text2)
                        if polished:
                            # הסר תג
                            polished_text = re.sub(r"^\[.*?\]|✍️ העורך|🎯.*?|🔍.*?\n", "", polished).strip()
                            polished_text = polished_text[:1000]
                            # ביקורת מהירה
                            critic2 = run_agent("CRITIC", f"טיוטה מלוטשת: {polished_text}\nאשר או הצע תיקון קצר", history_text2)
                            if critic2 and "אושר" not in critic2:
                                send_to_group(critic2)
                            publish_to_channel(polished_text, source_id=f"manual_{int(time.time())}")
                        else:
                            publish_to_channel(to_pub_raw, source_id=f"manual_{int(time.time())}")
                    else:
                        send_to_group("❓ כתוב: שלח לערוץ: [הטקסט שלך] — אני אלטש ואפרסם")
                    continue
                # 2. עדכון פרומפט פר-סוכן: "תעדכן פרומפט של העורך/מבקר/מיקוד/הכל: ..."
                patch_match = re.search(r"עדכן.*?פרומפט.*?של\s*(העורך|המבקר|מיקוד|הכל|העורך הראשי|מהנדס)?\s*[:：]\s*(.+)", text, re.I)
                if patch_match or ("עדכן" in text and "פרומפט" in text):
                    target = "ALL"
                    if patch_match:
                        raw_target = patch_match.group(1) or ""
                        patch_text = patch_match.group(2)
                        if "עורך" in raw_target: target = "EDITOR"
                        elif "מבקר" in raw_target: target = "CRITIC"
                        elif "מיקוד" in raw_target: target = "FOCUS"
                        elif "מהנדס" in raw_target: target = "PROMPT_ENGINEER"
                        else: patch_text = text.split(":",1)[1].strip() if ":" in text else patch_text
                    else:
                        patch_text = text.split(":",1)[1].strip() if ":" in text else text
                        if "עורך" in text: target = "EDITOR"
                        elif "מבקר" in text: target = "CRITIC"
                        elif "מיקוד" in text: target = "FOCUS"
                    if len(patch_text)>8:
                        save_prompt_patch(target, patch_text)
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
