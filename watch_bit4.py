#!/usr/bin/env python3
#
#watch_bit4.py
#
#Watch Bitcoin blocks via ZMQ (rawblock), detect versionbits bit 4 signalling,
#and raise a loud alert to:
#  - Windows desktop toast listener (BurntToast bridge via HTTP POST)
#  - Pushover Emergency notification (optional)
#
#Designed to run as user 'bitcoin' and be managed by systemd.


import os
import sys
import time
import json
import signal
import hashlib
import logging
import subprocess
import urllib.request
import urllib.parse
from typing import Optional, Dict, Any

import zmq  # pip install pyzmq


# -----------------------------
# Configuration (env vars)
# -----------------------------

# ZMQ rawblock endpoint (you already have zmqpubrawblock=tcp://127.0.0.1:28332)
ZMQ_RAWBLOCK = os.environ.get("ZMQ_RAWBLOCK", "tcp://127.0.0.1:28332")

# Where to POST desktop alerts (your Windows listener)
# Example: http://192.168.1.89:8099/
DESKTOP_TOAST_URL = os.environ.get("DESKTOP_TOAST_URL", "").strip()

# Pushover (optional). If either is missing, pushover is skipped.
PUSHOVER_TOKEN = os.environ.get("PUSHOVER_TOKEN", "").strip()  # application API token
PUSHOVER_USER = os.environ.get("PUSHOVER_USER", "").strip()    # user key
PUSHOVER_SOUND = os.environ.get("PUSHOVER_SOUND", "siren").strip()
PUSHOVER_RETRY = int(os.environ.get("PUSHOVER_RETRY", "60"))     # seconds (>=30 for priority=2)
PUSHOVER_EXPIRE = int(os.environ.get("PUSHOVER_EXPIRE", "3600")) # seconds

# Heartbeat: set to N>0 to send a low-noise "alive" message every N blocks
HEARTBEAT_EVERY_N_BLOCKS = int(os.environ.get("HEARTBEAT_EVERY_N_BLOCKS", "0"))
HEARTBEAT_TO_DESKTOP = os.environ.get("HEARTBEAT_TO_DESKTOP", "0") == "1"
HEARTBEAT_TO_PUSHOVER = os.environ.get("HEARTBEAT_TO_PUSHOVER", "0") == "1"
TOAST_EVERY_BLOCK = os.environ.get("TOAST_EVERY_BLOCK", "0") == "1"

# bitcoin-cli settings
BITCOIN_CLI = os.environ.get("BITCOIN_CLI", "/usr/local/bin/bitcoin-cli").strip()
BITCOIN_CONF = os.environ.get("BITCOIN_CONF", "/home/bitcoin/.bitcoin/bitcoin.conf").strip()

# State file (prevents duplicate alerts if restarted quickly)
STATE_FILE = os.environ.get("STATE_FILE", "/home/bitcoin/monitoring/bip110/state.json").strip()

# Versionbits bit to watch (default bit 4)
WATCH_BIT = int(os.environ.get("WATCH_BIT", "4"))
WATCH_MASK = 1 << WATCH_BIT

# Optional: send a startup toast so you know it launched
STARTUP_TOAST = os.environ.get("STARTUP_TOAST", "1") == "1"
STARTUP_PUSHOVER = os.environ.get("STARTUP_PUSHOVER", "1") == "1"

# -----------------------------
# Logging
# -----------------------------

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("watch_bit4")


# -----------------------------
# Graceful shutdown
# -----------------------------

_running = True


def _handle_sigterm(signum, frame):
    global _running
    _running = False
    log.info("Signal received (%s). Shutting down...", signum)


signal.signal(signal.SIGTERM, _handle_sigterm)
signal.signal(signal.SIGINT, _handle_sigterm)


# -----------------------------
# Helpers: state
# -----------------------------

def load_state() -> Dict[str, Any]:
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception as e:
        log.warning("Could not load state file (%s): %s", STATE_FILE, e)
        return {}


def save_state(state: Dict[str, Any]) -> None:
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, sort_keys=True)
        os.replace(tmp, STATE_FILE)
    except Exception as e:
        log.warning("Could not save state file (%s): %s", STATE_FILE, e)


# -----------------------------
# Helpers: desktop toast
# -----------------------------

def desktop_toast(message: str) -> None:
    if not DESKTOP_TOAST_URL:
        return
    try:
        data = message.encode("utf-8", errors="replace")
        req = urllib.request.Request(
            DESKTOP_TOAST_URL,
            data=data,
            method="POST",
            headers={"Content-Type": "text/plain; charset=utf-8"},
        )
        urllib.request.urlopen(req, timeout=3).read()
    except Exception as e:
        log.warning("Desktop toast POST failed: %s", e)


# -----------------------------
# Helpers: pushover
# -----------------------------

def pushover_notify(title: str, message: str, emergency: bool) -> None:
    """
    Send a Pushover notification.
    If emergency=True, uses priority=2 and requires retry/expire.
    Pushover emergency retry/expire behavior per API docs. 
    """
    if not (PUSHOVER_TOKEN and PUSHOVER_USER):
        return

    url = "https://api.pushover.net/1/messages.json"
    payload = {
        "token": PUSHOVER_TOKEN,
        "user": PUSHOVER_USER,
        "title": title,
        "message": message,
        "sound": PUSHOVER_SOUND,
    }

    if emergency:
        # Pushover requires retry/expire for priority=2, retry must be >= 30 seconds.
        retry = max(PUSHOVER_RETRY, 30)
        expire = max(PUSHOVER_EXPIRE, retry)
        payload.update({
            "priority": 2,
            "retry": retry,
            "expire": expire,
        })
    else:
        payload["priority"] = 0  # normal

    try:
        data = urllib.parse.urlencode(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        urllib.request.urlopen(req, timeout=10).read()
    except Exception as e:
        log.warning("Pushover send failed: %s", e)


# -----------------------------
# Helpers: bitcoin-cli
# -----------------------------

def bitcoin_cli_json(*args: str) -> Dict[str, Any]:
    """
    Run bitcoin-cli with -conf explicitly so systemd/home quirks don't matter.
    """
    cmd = [BITCOIN_CLI, f"-conf={BITCOIN_CONF}", *args]
    out = subprocess.check_output(cmd, text=True)
    return json.loads(out)


def block_hash_from_rawblock(raw: bytes) -> str:
    """
    rawblock message body begins with the 80-byte block header.
    Block hash is double-SHA256(header), displayed as little-endian hex.
    """
    header = raw[:80]
    h = hashlib.sha256(hashlib.sha256(header).digest()).digest()
    return h[::-1].hex()


# -----------------------------
# Main loop
# -----------------------------

def main() -> int:
    state = load_state()
    last_alert_hash = state.get("last_alert_hash", "")
    last_seen_height = state.get("last_seen_height", None)

    # ZMQ setup
    ctx = zmq.Context()
    sock = ctx.socket(zmq.SUB)
    sock.connect(ZMQ_RAWBLOCK)
    sock.setsockopt(zmq.SUBSCRIBE, b"rawblock")
    sock.setsockopt(zmq.RCVTIMEO, 1000)  # 1s timeout so we can notice shutdown

    log.info("Watching ZMQ rawblock at %s", ZMQ_RAWBLOCK)
    log.info("Watching version bit %d (mask 0x%x)", WATCH_BIT, WATCH_MASK)
    if DESKTOP_TOAST_URL:
        log.info("Desktop toast enabled: %s", DESKTOP_TOAST_URL)
    else:
        log.info("Desktop toast disabled (DESKTOP_TOAST_URL not set)")

    if PUSHOVER_TOKEN and PUSHOVER_USER:
        log.info("Pushover enabled (token/user present)")
    else:
        log.info("Pushover disabled (PUSHOVER_TOKEN/PUSHOVER_USER not set)")

    blocks_since_heartbeat = 0

    if STARTUP_TOAST:
        desktop_toast("✅ BIP110 watch started on EQU1N0XB0X (desktop bridge OK)")

    if STARTUP_PUSHOVER:
        pushover_notify("BIP110 Watch", "✅ Watcher started on EQU1N0XB0X (startup test).", emergency=False)


    while _running:
        try:
            # multipart: topic, body, seq
            try:
                parts = sock.recv_multipart(flags=0)
            except zmq.error.Again:
            # recv timed out (RCVTIMEO); loop back so we can notice shutdown
                continue

            if len(parts) < 2:
                continue
            _topic = parts[0]
            body = parts[1]

            bh = block_hash_from_rawblock(body)

            # Query header
            hdr = bitcoin_cli_json("getblockheader", bh, "true")
            height = hdr.get("height")
            version = int(hdr.get("version", 0))
            version_hex = hdr.get("versionHex", "")
            t = hdr.get("time", 0)

            bit_set = (version & WATCH_MASK) != 0

            log.info(
                "block height=%s hash=%s version=%s %s bit%d=%s",
                height, bh, version, version_hex, WATCH_BIT, "YES" if bit_set else "no"
            )
            if TOAST_EVERY_BLOCK:
                desktop_toast(f"Block {height}  bit{WATCH_BIT}={'YES' if bit_set else 'no'}")

            # Heartbeat (optional)
            blocks_since_heartbeat += 1
            if HEARTBEAT_EVERY_N_BLOCKS > 0 and blocks_since_heartbeat >= HEARTBEAT_EVERY_N_BLOCKS:
                blocks_since_heartbeat = 0
                hb_msg = f"Heartbeat: height={height} bit{WATCH_BIT}={'YES' if bit_set else 'no'} peers=check-cli"
                if HEARTBEAT_TO_DESKTOP:
                    desktop_toast(hb_msg)
                if HEARTBEAT_TO_PUSHOVER:
                    pushover_notify("BIP110 Heartbeat", hb_msg, emergency=False)

            # Alert if bit set
            if bit_set and bh != last_alert_hash:
                alert_msg = (
                    f"🚨 BIT-{WATCH_BIT} SIGNAL DETECTED 🚨\n"
                    f"height={height}\n"
                    f"hash={bh}\n"
                    f"version={version} {version_hex}\n"
                    f"time={t}\n"
                )
                desktop_toast(alert_msg)
                pushover_notify(f"BIP110 BIT-{WATCH_BIT}!", alert_msg, emergency=True)

                last_alert_hash = bh
                state["last_alert_hash"] = last_alert_hash
                state["last_seen_height"] = height
                save_state(state)

                log.info("ALERT sent for hash=%s height=%s. Continuing to watch...", bh, height)

            # Save last seen height occasionally
            if height is not None and height != last_seen_height:
                last_seen_height = height
                state["last_seen_height"] = height
                save_state(state)

        except subprocess.CalledProcessError as e:
            log.warning("bitcoin-cli failed: %s", e)
            time.sleep(1)
        except json.JSONDecodeError as e:
            log.warning("JSON decode error: %s", e)
            time.sleep(1)
        except Exception as e:
            log.warning("Loop error: %s", e)
            time.sleep(1)

    log.info("Stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
