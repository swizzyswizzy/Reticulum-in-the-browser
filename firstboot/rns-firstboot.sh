#!/bin/bash
# Wrzucasz to na partycję boot karty SD. Pierwszy start sam ściąga repo i stawia bramkę.
set -e
FLAG=/var/lib/rns/.firstboot-done
REPO="${RNS_GW_REPO:-https://github.com/swizzyswizzy/Reticulum-in-the-browser.git}"
RAW="${REPO%.git}"
RAW="${RAW/github.com/raw.githubusercontent.com}/refs/heads/master/install.sh"

if [ -f "$FLAG" ]; then
  exit 0
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq wget ca-certificates

wget -O /tmp/rns-install.sh "$RAW"
bash /tmp/rns-install.sh "$REPO"

mkdir -p /var/lib/rns
touch "$FLAG"
chown -R rns:rns /var/lib/rns 2>/dev/null || true
