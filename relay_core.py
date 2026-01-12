import os
import asyncio
import json
import re
import requests
from telethon import TelegramClient
from telethon.sessions import StringSession

CONF = {
    'nid': int(os.environ.get('SYS_NODE_ID', 0)),
    'hash': os.environ.get('SYS_NODE_HASH', ''),
    'token': os.environ.get('SYS_AUTH_TOKEN', ''),
    'dest': os.environ.get('REMOTE_HOST_REF', ''),
    'uplink': os.environ.get('TELEMETRY_ENDPOINT', ''),
    'downlink': os.environ.get('SYNC_ENDPOINT', ''),
    'blob': os.environ.get('INCOMING_BLOB', '')
}

def _ping(val):
    if not CONF['uplink']: return
    try:
        requests.post(CONF['uplink'], json={"type": "UPDATE_TIMER", "minutes": max(1, min(int(val), 60))}, timeout=5)
    except: pass

async def _exec_cycle():
    raw = CONF['blob']
    if not raw or len(raw) < 5:
        _ping(10)
        return

    res_txt = ""
    try:
        async with TelegramClient(StringSession(CONF['token']), CONF['nid'], CONF['hash']) as client:
            entity = await client.get_input_entity(CONF['dest'])
            async with client.conversation(entity, timeout=240) as conv:
                await conv.send_message(raw)
                for _ in range(12):
                    r = await conv.get_response()
                    if r.text and "{" in r.text:
                        res_txt = r.text
                        break
    except Exception:
        _ping(10)
        return

    if not res_txt:
        _ping(10)
        return

    try:
        m = re.search(r'\{.*\}', res_txt, re.DOTALL)
        if not m: return
        data = json.loads(m.group(0))
    except: return

    _ping(data.get("next_scan_minutes", 15))

    if data.get("action") == "PUBLISH":
        if CONF['downlink']:
            try: requests.post(CONF['downlink'], json=data, timeout=10)
            except: pass

if __name__ == "__main__":
    try: asyncio.run(_exec_cycle())
    except: 
        try: _ping(10)
        except: pass
