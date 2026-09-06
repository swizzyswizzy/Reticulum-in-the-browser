#!/bin/bash
set +e
DEST=/opt/reticulum-gateway
LOG=/var/lib/rns/update.log
mkdir -p /var/lib/rns
echo "[$(date -Iseconds)] start" >> "$LOG"
cd "$DEST" || exit 1
old=$(git rev-parse HEAD 2>/dev/null)
git fetch --depth 1 origin master >>"$LOG" 2>&1
git merge --ff-only origin/master >>"$LOG" 2>&1 || git reset --hard origin/master >>"$LOG" 2>&1
new=$(git rev-parse HEAD 2>/dev/null)
if [ -z "$new" ] || [ "$old" = "$new" ]; then
  echo "[$(date -Iseconds)] bez zmian ($old)" >> "$LOG"
  exit 0
fi
echo "[$(date -Iseconds)] $old -> $new" >> "$LOG"
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
systemctl restart reticulum-gateway >>"$LOG" 2>&1
echo "[$(date -Iseconds)] zrestartowano bramkę" >> "$LOG"
