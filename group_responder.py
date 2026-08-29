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
                # collect group context (last 10 msgs) for agents
                # simple: use current text + recent history placeholder
                history_text = f"הודעת מפעיל: {text}\n(קבוצה {GROUP_ID})"
                # === PERSONA ORDER - ברור מי שולח ===
                # 1. FOCUS - אחראי מיקוד
                focus = run_agent("FOCUS", f"המפעיל כתב: \"{text}\" - על מה להתמקד? הסבר בעברית.", history_text)
                if focus: send_to_group(focus); time.sleep(1.3)
                # 2. EDITOR - העורך
                editor = run_agent("EDITOR", f"המפעיל כתב: \"{text}\" - נסח הודעה בהתאם בעברית טבעית.", history_text + ("\n"+focus if focus else ""))
                if editor: send_to_group(editor); time.sleep(1.3)
                # 3. CRITIC - המבקר
                if editor:
                    critic = run_agent("CRITIC", f"טיוטה: {editor}\nבדוק אם אנושי?", history_text)
                    if critic: send_to_group(critic); time.sleep(1.2)
                # 4. PROMPT_ENGINEER - רק אם צריך
                if "פרומפט" in text or "prompt" in text.lower() or (focus and "הצעת פרומפט" in focus):
                    pe = run_agent("PROMPT_ENGINEER", f"המפעיל: {text}\nFOCUS: {focus}\nהאם לעדכן פרומפט?", history_text)
                    if pe: send_to_group(pe)
                # שמירת הצעת פרומפט
                try:
                    if focus and "הצעת פרומפט" in focus:
                        m=re.search(r"הצעת פרומפט:\s*(.+)", focus)
                        if m and len(m.group(1))>10 and SCANNER_URL:
                            requests.post(SCANNER_URL, json={"action":"setProps","PROMPT_PATCH": m.group(1).strip()}, timeout=8)
                except: pass

        except Exception as e:
            print(f"loop err {e}")
            traceback.print_exc()
        time.sleep(1.4)
    print("6h done, exiting")

if __name__ == "__main__":
    main()
