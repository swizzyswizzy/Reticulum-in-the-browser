#!/bin/bash
# Instalacja na Raspberry Pi. Uruchamiaj jako root.
set -e
REPO="${1:-${RNS_GW_REPO:-https://github.com/YOURUSER/reticulum-gateway.git}}"
DEST=/opt/reticulum-gateway
HOME_RNS=/var/lib/rns

if [ "$(id -u)" -ne 0 ]; then
  echo "Uruchom: sudo bash install.sh"
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

python3 -m pip install --break-system-packages -q -r "$DEST/requirements.txt"

id rns >/dev/null 2>&1 || useradd --system --home "$HOME_RNS" --create-home --shell /usr/sbin/nologin rns
mkdir -p "$HOME_RNS" "$HOME_RNS/.reticulum" "$HOME_RNS/.reticulum-gateway"
chown -R rns:rns "$HOME_RNS"

cp "$DEST/systemd/reticulum-gateway.service" /etc/systemd/system/reticulum-gateway.service
systemctl daemon-reload
systemctl enable reticulum-gateway
systemctl restart reticulum-gateway

sleep 1
IP=$(hostname -I 2>/dev/null | awk '{print $1}')
echo
echo "Gotowe. Panel: http://${IP:-IP}:4240"
echo "IP zapisane w $HOME_RNS/ip.txt"
