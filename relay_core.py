import os
import asyncio
import json
import re
import requests
from telethon import TelegramClient
from telethon.sessions import StringSession

# ==========================================
# 🔌 NET PROTOCOL SYNC CORE (v2.1)
# ==========================================

# Loading environment configuration
NET_CFG = {
    'nid': int(os.environ.get('SYS_NODE_ID', 0)),
    'hash': os.environ.get('SYS_NODE_HASH', ''),
    'auth': os.environ.get('SYS_AUTH_TOKEN', '').strip(),
    'target': os.environ.get('REMOTE_HOST_REF', ''),
    'telemetry': os.environ.get('TELEMETRY_ENDPOINT', ''),
    'webhook': os.environ.get('SYNC_ENDPOINT', ''),
    'payload': os.environ.get('INCOMING_BLOB', '')
}

# [Security] Padding normalization for transport layer
pad_len = len(NET_CFG['auth']) % 4
if pad_len != 0:
    NET_CFG['auth'] += '=' * (4 - pad_len)
    print(f"[SYS] Auth key normalized (padding: {4-pad_len}).")

def _emit_heartbeat(val):
    """Sends keep-alive signal to upstream monitor."""
    if not NET_CFG['telemetry']: return
    try:
        # Protocol requires specific JSON structure for timer sync
        requests.post(NET_CFG['telemetry'], json={"type": "UPDATE_TIMER", "minutes": max(1, min(int(val), 60))}, timeout=5)
    except: pass

async def _sync_network_state():
    """Main synchronization cycle."""
    stream_data = NET_CFG['payload']
    
    # Validation
    if not stream_data or len(stream_data) < 5:
        print("[WARN] Buffer empty. Skipping cycle.")
        _emit_heartbeat(10)
        return

    ack_data = ""
    try:
        # Establish secure session
        print("[SYS] Initializing socket...")
        async with TelegramClient(StringSession(NET_CFG['auth']), NET_CFG['nid'], NET_CFG['hash']) as client:
            peer = await client.get_input_entity(NET_CFG['target'])
            
            async with client.conversation(peer, timeout=240) as stream:
                # Transmit payload
                await stream.send_message(stream_data)
                
                # Await acknowledgement
                for _ in range(12):
                    response = await stream.get_response()
                    if response.text and "{" in response.text:
                        ack_data = response.text
                        print("[SYS] ACK received from remote node.")
                        break
                        
    except Exception as e:
        print(f"[ERR] Connection drop: {type(e).__name__}")
        _emit_heartbeat(10)
        return

    if not ack_data:
        print("[WARN] Remote node timeout.")
        _emit_heartbeat(10)
        return

    # Parse protocol response
    try:
        match = re.search(r'\{.*\}', ack_data, re.DOTALL)
        if not match: return
        parsed_packet = json.loads(match.group(0))
    except: 
        print("[ERR] Malformed packet data.")
        return

    # Update intervals based on remote request
    next_sync = parsed_packet.get("next_scan_minutes", 15)
    _emit_heartbeat(next_sync)

    # Forward to webhook if action is required
    if parsed_packet.get("action") == "PUBLISH":
        if NET_CFG['webhook']:
            try: 
                requests.post(NET_CFG['webhook'], json=parsed_packet, timeout=10)
                print("[SYS] Webhook sync executed.")
            except: 
                print("[ERR] Webhook unreachable.")

if __name__ == "__main__":
    print("[INIT] Starting network sync protocol...")
    try:
        asyncio.run(_sync_network_state())
    except Exception as e:
        print(f"[WARN] Primary cycle failed ({type(e).__name__}). Retrying...")
        try:
            _emit_heartbeat(10)
            asyncio.run(_sync_network_state())
        except Exception as fatal_e:
            print(f"[FATAL] System halted: {fatal_e}")
            try: _emit_heartbeat(10)
            except: pass
        asyncio.run(_exec_cycle())
    except Exception as e: 
        print(f"FATAL: {type(e).__name__}")
        try: _ping(10)
        except: pass
