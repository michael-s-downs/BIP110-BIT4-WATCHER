# BIP110 Bit-4 Watcher (v0.1.1)

This repo contains a **lightweight, opinionated watcher system** implemented across two machines by two scripts, a command-line installer (Windows) and a service configuration file (Linux).  The machines are:

1) **A Linux Bitcoin node** : runs `watch_bit4.py` and subscribes to your node’s ZMQ `rawblock` feed.  
2) **A Windows Desktop** : runs a simple HTTP listener that turns incoming messages into **BurntToast** notifications.

Optionally, the watcher can also send higher-attention alerts that merit a phone message via **Pushover** for special events, like a positive catch of the looked-for header.

Specifically, the watcher as implemented checks for the BIP-110 “Reduced Data” support signal on **versionbits bit 4**. Miners can signal readiness and support by setting bit 4 in the `version` field of blocks they mine. The watcher alerts you when it sees such a block with that bit set, so that it can be celebrated broadly, as proactive miner suppport is the desired path for BIP-110.

> NOTE:  This is a hobby / reference implementation built around my local implementation of a headless node server, managed from a convenient Windows Desktop environment. It’s designed to be forked (or just pulled) and tailored to *your* own specific environment as needed, and is shared in that spirit.

---

## What this Watcher System Does

On each new block, `watch_bit4.py`:

- Receives raw blocks via its own subscription to your node's ZMQ (`zmqpubrawblock`)
- Extracts the included block hash, then queries the header via `bitcoin-cli getblockheader` RPC call.
- Checks whether **bit 4** is set in the header `version`
- Sends desired notifications based on your `.env` configuration
- This system is easily modified and extended for other node-pushed alerts you may want to implement as real-time pushes (anything exposed by RPC like health and peer and network info) 

Notification channels currently supported are:

- **Windows desktop toasts** via a LAN HTTP POST to `toast-listener.ps1` (BurntToast Library)
- **Phone notifications** via **Pushover** (optional, a free Phone-App)

---

## Configurations

The scripts are configurable by channel and frequency, so your configuration can be meaningful within the signaling patterns:

- I like **frequent desktop toasts, once every block** (these let me know the system is up and there are not ANY signaling miners YET).
- But I reserve **phone notifications** for:
  - setup/startup channel check
  - a very low-rate **heartbeat** (144 blocks, ≈ 1x daily) so that off-beat messages signal the event I'm looking for...
  - immediate messaging on any block with a **positive bit-4 signal** flash so I can quickly spread the news to fellow enthusiasts!

Available configurations by channel are:

- Startup test notice (`STARTUP_TOAST`, `STARTUP_PUSHOVER`)
- Heartbeats On/Off (`HEARTBEAT_TO_DESKTOP`, `HEARTBEAT_TO_PUSHOVER`)
- Heartbeat frequency in blocks (`HEARTBEAT_EVERY_N_BLOCKS`)
- Toast for every block (`TOAST_EVERY_BLOCK`)

See `.env.example` for a working baseline.

---

## My Personal Setup For Cross-Reference 

This is my personal setup around which v.0 is designed, this what it supports 'as is':

- **A Separate Linux Node:** A Linux headless box running bitcoind/knots with `zmqpubrawblock` 
- **A Separate Windows Desktop:** A Windows machine on the same LAN running a BurntToast listener (HTTP POST)
- **A Phone running Pushover App:** (for “away-from-keyboard” alerts when its important)

## Diagram View

![My opinionated setup diagram](./My-Personal-Setup.png)

## Files Included 

- `watch_bit4.py` — the watcher, installed on your node server (if Linux)
- `toast-listener.ps1` — Windows toast listener (BurntToast), installed on your personal computer (if Windows) by the installer file.
- `install-or-update-toast-listener-task.ps1` - Standalone Installer/Updater sets up the Windows listener as a durable 'Scheduled Task' that will restart on login (see quick-start)
- `systemd/bip110-watch.service` — example systemd unit to run the watcher as a background service on your node
- `.env.example` — sample configuration (copy to `.env` on your node Watcher install and fill out)
- `requirements.txt` — Python library dependencies (pyzmq) to install for the Watcher python script.

## Node prerequisites

In your `bitcoin.conf` you must be exposing zmqpubrawblock.  You are probably already doing this, but an example config you would need to add to bitcoin.conf to add it (or confirm it) is:

```bash
zmqpubrawblock=tcp://127.0.0.1:28332
```
Restart bitcoind only if you change the configuration, before node-side Watcher install step below.

# Quick-Start Setups:  Windows Toast, Windows Task, Node Watcher, Linux Service

## 1) Set Up Windows toast listener on Local & LAN and verify messaging 
Install BurntToast (PowerShell as Admin is best for AllUsers (can still work with currentUser)):
``` PowerShell
Install-Module BurntToast -Scope AllUsers -Force
```
Reserve URL + firewall (example for port 8099):
```bash
netsh http add urlacl url=http://+:8099/ user=$env:USERNAME
New-NetFirewallRule -DisplayName "BIP110 Toast Listener 8099" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8099
```
Run the Installer-Updater from the project root to copy the Toast listener into place, and set up a Windows 'Scheduled Task,' this will keep the script running durably across restarts 'like' a service:
```bash
.\scripts\install-or-update-toast-listener-task.ps1
```

Test from local first and then from anywhere on your home LAN to see a test-toast pop up on your Windows Desktop:
``` PowerShell
On your Windows Desktop Computer, you can invoke using PowerShell... 
Invoke-WebRequest -Method POST -Uri "http://localhost:8099/" -Body "Desktop listener test ✅"
```
``` bash
or cURL:
curl.exe -X POST http://localhost:8099/ -d "TEST: toast listener installed or updated."
```
``` bash
then from your Linux Node-Server which will confirm the firewall rule is ready too:
curl -H "Content-Type: text/plain; charset=utf-8"   --data-binary "✅ Node -> Desktop toast test from the Node Server"   http://<YOUR-WINDOWS-LOCAL-IP>:8099/
```
## 1a) Set up Pushover (optional but recommended)

This is the optional-but-recommended “phone alert” channel.

1. Install the Pushover app on your phone (iOS App Store / Google Play).  This is where messages will get sent to.

2. Create a free Pushover account and grab:
    - your personal User Key

3. Create an “Application” in Pushover to get:
    - a personal API Token/Key

Paste these into your node .env as variables - these stay private (don't push to a repo etc):
- PUSHOVER_USER=...
- PUSHOVER_TOKEN=...

## 2) Set up the watcher on the Node (Linux Server) 
The following assumes:

- your bitcoind is run by user 'bitcoin' (standard) and watcher therefore lives at: /home/bitcoin/monitoring/bip110
- you will adjust paths given below as examples if you have a different bitcoin user

1. Create project folder 
```bash
sudo -iu bitcoin mkdir -p /home/bitcoin/monitoring/bip110
sudo -iu bitcoin cd /home/bitcoin/monitoring/bip110
```
2. Create virtualenv and install dependencies
```bash
sudo -iu bitcoin bash -lc '
cd /home/bitcoin/monitoring/bip110 &&
python3 -m venv .venv &&
./.venv/bin/pip install -r requirements.txt
'
```
3. Create your .env
```bash
sudo -iu bitcoin bash -lc '
cd /home/bitcoin/monitoring/bip110 &&
cp .env.example .env
'
```
Edit your .env for run configuration:
- Set your desktop local-network IP in DESKTOP_TOAST_URL (example: http://192.168.1.89:8099/)
- If using Pushover, set PUSHOVER_USER and PUSHOVER_TOKEN
- Decide whether you want:
    - every-block toasts (TOAST_EVERY_BLOCK=1)
    - heartbeats (HEARTBEAT_EVERY_N_BLOCKS=144, etc.)

## 2a) Run an interactive test from Node of the Watcher to see Block Notifications on Toast
Run the watcher manually once to prove it all works before committing to systemd:
```bash
sudo -iu bitcoin bash -lc '
cd /home/bitcoin/monitoring/bip110 &&
./.venv/bin/python ./watch_bit4.py
'
```
success is seeing log lines such as:
- 'Watching ZMQ rawblock...'
- 'Desktop toast enabled...'
- 'Pushover enabled...'
- One new log line per new BTC block

## 3) Setup Watcher as a durable, Systemd managed background service
Copy the included/suggested Service unit file into place...
```bash
sudo cp systemd/bip110-watch.service /etc/systemd/system/bip110-watch.service
```
Enable & Start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable bip110-watch.service
sudo systemctl start bip110-watch.service
```
Optional Follow Logs till you see at least 1 block get detected and toasted:
```bash
sudo journalctl -u bip110-watch.service -f
```
# MIT License
See Project [LICENSE](LICENSE)
