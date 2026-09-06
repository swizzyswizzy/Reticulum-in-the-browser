#!/bin/bash
# Install on the Raspberry Pi. Run as root.
set -e
REPO="${1:-${RNS_GW_REPO:-https://github.com/swizzyswizzy/Reticulum-in-the-browser.git}}"
DEST=/opt/reticulum-gateway
HOME_RNS=/var/lib/rns

if [ "$(id -u)" -ne 0 ]; then
  echo "Run: sudo bash install.sh"
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq git python3 python3-pip openssl ca-certificates

if [ -f "$DEST/gateway/gateway.py" ]; then
  git -C "$DEST" pull --ff-only || true
elif [ -f "$(dirname "$0")/gateway/gateway.py" ]; then
  mkdir -p "$DEST"
  cp -a "$(cd "$(dirname "$0")" && pwd)/." "$DEST/"
else
  git clone --depth 1 "$REPO" "$DEST"
fi

if [ -f "$DEST/requirements.txt" ]; then
  python3 -m pip install --break-system-packages -q -r "$DEST/requirements.txt"
else
  python3 -m pip install --break-system-packages -q rns lxmf
fi

id rns >/dev/null 2>&1 || useradd --system --home "$HOME_RNS" --create-home --shell /usr/sbin/nologin rns
mkdir -p "$HOME_RNS" "$HOME_RNS/.reticulum" "$HOME_RNS/.reticulum-gateway"
chown -R rns:rns "$HOME_RNS"

cp "$DEST/systemd/reticulum-gateway.service" /etc/systemd/system/reticulum-gateway.service
if [ -f "$DEST/systemd/rns-update.sh" ]; then
  install -m 755 "$DEST/systemd/rns-update.sh" /usr/local/sbin/rns-update.sh
fi
if [ -f "$DEST/systemd/reticulum-gateway-update.service" ]; then
  cp "$DEST/systemd/reticulum-gateway-update.service" /etc/systemd/system/
  cp "$DEST/systemd/reticulum-gateway-update.timer" /etc/systemd/system/
fi
systemctl daemon-reload
systemctl reset-failed reticulum-gateway 2>/dev/null || true
systemctl enable reticulum-gateway
if [ "${RNS_AUTO_UPDATE:-1}" = "0" ]; then
  systemctl disable --now reticulum-gateway-update.timer 2>/dev/null || true
  echo "auto-update: disabled"
else
  systemctl enable --now reticulum-gateway-update.timer
  echo "auto-update: enabled (every 1 min)"
fi
date "+%Y-%m-%d %H:%M:%S" > "$HOME_RNS/updated_at" || true

LOG="$HOME_RNS/install.log"
mkdir -p "$HOME_RNS"
wait_service() {
  deadline=$(( $(date +%s) + 300 ))
  n=0
  while [ "$(date +%s)" -lt "$deadline" ]; do
    n=$((n + 1))
    echo "[$(date -Iseconds)] restart #$n" | tee -a "$LOG"
    systemctl reset-failed reticulum-gateway 2>/dev/null || true
    systemctl restart reticulum-gateway >>"$LOG" 2>&1 || systemctl start reticulum-gateway >>"$LOG" 2>&1 || true
    sleep 3
    if systemctl is-active --quiet reticulum-gateway; then
      echo "[$(date -Iseconds)] reticulum-gateway active after $n attempt(s)" | tee -a "$LOG"
      return 0
    fi
    echo "[$(date -Iseconds)] still dead: $(systemctl is-active reticulum-gateway 2>/dev/null || true)" | tee -a "$LOG"
    sleep 2
  done
  echo "[$(date -Iseconds)] ERROR: reticulum-gateway did not start within 5 minutes" | tee -a "$LOG"
  systemctl --no-pager --full status reticulum-gateway >>"$LOG" 2>&1 || true
  journalctl -u reticulum-gateway -n 80 --no-pager >>"$LOG" 2>&1 || true
  return 1
}

if ! wait_service; then
  echo "Error: service did not start. Log: $LOG"
  exit 1
fi

IP=$(hostname -I 2>/dev/null | awk '{print $1}')
echo
echo "Done. Panel: http://${IP:-IP}/  and  https://${IP:-IP}/"
echo "IP written to $HOME_RNS/ip.txt"
