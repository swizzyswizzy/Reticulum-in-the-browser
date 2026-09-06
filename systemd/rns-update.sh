#!/bin/bash
set +e
DEST=/opt/reticulum-gateway
LOG=/var/lib/rns/update.log
REPO="${RNS_GW_REPO:-https://github.com/swizzyswizzy/Reticulum-in-the-browser.git}"
mkdir -p /var/lib/rns
echo "[$(date '+%Y-%m-%d %H:%M:%S')] start" >> "$LOG"

if [ ! -d "$DEST/.git" ]; then
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] no repo — cloning" >> "$LOG"
  rm -rf "$DEST"
  git clone --depth 1 -b master "$REPO" "$DEST" >>"$LOG" 2>&1 || git clone --depth 1 "$REPO" "$DEST" >>"$LOG" 2>&1
fi

cd "$DEST" || { echo "missing $DEST" >> "$LOG"; exit 1; }
git remote set-url origin "$REPO" >/dev/null 2>&1 || git remote add origin "$REPO" >/dev/null 2>&1
old=$(git rev-parse HEAD 2>/dev/null)
git fetch --depth 1 origin master >>"$LOG" 2>&1 || git fetch --depth 1 origin >>"$LOG" 2>&1
git merge --ff-only FETCH_HEAD >>"$LOG" 2>&1 || git reset --hard FETCH_HEAD >>"$LOG" 2>&1 || git reset --hard origin/master >>"$LOG" 2>&1
new=$(git rev-parse HEAD 2>/dev/null)

if [ -z "$new" ]; then
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: git failed" >> "$LOG"
  exit 1
fi

if [ "$old" = "$new" ]; then
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] no change ($old)" >> "$LOG"
  exit 0
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] $old -> $new" >> "$LOG"
date "+%Y-%m-%d %H:%M:%S" > /var/lib/rns/updated_at
if [ -f "$DEST/requirements.txt" ]; then
  python3 -m pip install --break-system-packages -q -r "$DEST/requirements.txt" >>"$LOG" 2>&1
fi
if [ -f "$DEST/systemd/reticulum-gateway.service" ]; then
  cp "$DEST/systemd/reticulum-gateway.service" /etc/systemd/system/reticulum-gateway.service
fi
if [ -f "$DEST/systemd/reticulum-gateway-update.timer" ]; then
  cp "$DEST/systemd/reticulum-gateway-update.service" /etc/systemd/system/
  cp "$DEST/systemd/reticulum-gateway-update.timer" /etc/systemd/system/
  install -m 755 "$DEST/systemd/rns-update.sh" /usr/local/sbin/rns-update.sh
fi
systemctl daemon-reload
systemctl enable --now reticulum-gateway-update.timer >>"$LOG" 2>&1
systemctl restart reticulum-gateway >>"$LOG" 2>&1
echo "[$(date '+%Y-%m-%d %H:%M:%S')] gateway restarted" >> "$LOG"
