#!/usr/bin/env python3
"""Dopisuje Wi-Fi i firstboot na kartę nagraną Raspberry Pi Imagerem."""

from __future__ import annotations

import json
import os
import re
import secrets
import string
import subprocess
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QCheckBox,
    QMainWindow,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

REPO_URL = "https://github.com/swizzyswizzy/Reticulum-in-the-browser.git"
WIFI_SAVE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wifi.json")

STYLE = """
QMainWindow, QWidget#root { background: #1b1e1c; color: #d7ddd4; }
QLabel { color: #d7ddd4; font-size: 13px; }
QLabel#title { color: #cfe7c4; font-size: 18px; font-weight: 700; }
QLabel#hint { color: #8b9486; font-size: 12px; }
QLabel#err { color: #e08a7a; font-size: 12px; }
QLabel#rootpw { color: #ff6b5b; font-size: 16px; font-weight: 700; }
QLabel#cred { color: #e8eee4; font-size: 13px; }
QLineEdit, QComboBox {
  background: #111411; color: #e8eee4; border: 1px solid #3a4338;
  padding: 6px 8px; selection-background-color: #3d6b46;
}
QLineEdit:focus, QComboBox:focus { border: 1px solid #7dba8a; }
QPushButton {
  background: #2a3329; color: #e8eee4; border: 1px solid #4a5547; padding: 7px 12px;
}
QPushButton:hover { border-color: #7dba8a; }
QPushButton#run {
  background: #3c6b46; border: 1px solid #7dba8a; font-weight: 700; padding: 10px 16px;
}
QTextEdit {
  background: #0e100e; color: #9cff9c; border: 1px solid #3a4338;
  font-family: ui-monospace, Consolas, monospace; font-size: 12px;
}
QFrame#box { border: 1px solid #2c332c; background: #161916; }
"""


def is_bootfs(path):
    return os.path.isfile(os.path.join(path, "cmdline.txt")) and os.path.isfile(
        os.path.join(path, "config.txt")
    )


def list_bootfs():
    found = []
    if os.name == "nt":
        for letter in "DEFGHIJKLMNOPQRSTUVWXYZ":
            root = f"{letter}:/"
            if is_bootfs(root):
                found.append({"label": f"bootfs {letter}:", "path": root})
    else:
        for base in ("/media", "/run/media", "/Volumes", "/mnt"):
            if not os.path.isdir(base):
                continue
            for dirpath, dirnames, filenames in os.walk(base):
                if "cmdline.txt" in filenames and "config.txt" in filenames:
                    found.append({"label": os.path.basename(dirpath) or dirpath, "path": dirpath})
                    dirnames.clear()
                if dirpath[len(base):].count(os.sep) >= 3:
                    dirnames.clear()
    return found


def read_text(path):
    with open(path, "rb") as fh:
        data = fh.read()
    if not data or b"\x00" in data[:80]:
        raise RuntimeError("uszkodzony plik: " + path)
    return data.decode("ascii", errors="replace")


def write_text(path, text):
    raw = text.replace("\r\n", "\n").encode("ascii", errors="replace")
    tmp = path + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(raw)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def patch_cmdline(text: str) -> str:
    line = " ".join(text.replace("\n", " ").split())
    line = re.sub(r"\bsystemd\.run\S*", "", line)
    line = re.sub(r"\bmodules-load=\S*", "", line)
    line = re.sub(r"\s+", " ", line).strip()
    if re.search(r"\brootwait\b", line):
        line = re.sub(r"\brootwait\b", "rootwait modules-load=dwc2,g_ether", line, count=1)
    else:
        line += " modules-load=dwc2,g_ether"
    line += " systemd.run=/boot/firmware/rns-firstboot.sh systemd.run_success_action=none systemd.run_failure_action=none"
    return re.sub(r"\s+", " ", line).strip() + "\n"


def patch_config(text: str) -> str:
    text = re.sub(r"^([ \t]*)otg_mode=", r"\1#otg_mode=", text, flags=re.M)
    if not re.search(r"^dtoverlay=dwc2\b", text, re.M):
        if re.search(r"^\[all\]", text, re.M):
            text = re.sub(r"^\[all\]", "[all]\ndtoverlay=dwc2", text, count=1, flags=re.M)
        else:
            text = text.rstrip() + "\n\n[all]\ndtoverlay=dwc2\n"
    if not text.endswith("\n"):
        text += "\n"
    return text


def known_hosts_path():
    return os.path.join(os.path.expanduser("~"), ".ssh", "known_hosts")


def drop_known_host(name):
    name = (name or "").strip()
    if not name:
        return "pusty adres"
    try:
        subprocess.check_call(
            ["ssh-keygen", "-R", name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return "ssh-keygen -R " + name
    except Exception:
        pass
    path = known_hosts_path()
    if not os.path.isfile(path):
        return "brak pliku known_hosts"
    keep = []
    dropped = 0
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            token = line.split()[0] if line.split() else ""
            if name in token.split(","):
                dropped += 1
                continue
            keep.append(line)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.writelines(keep)
    return ("usunięto " + str(dropped) + " linii dla " + name) if dropped else ("nie było wpisu " + name)


def make_hostname():
    alphabet = string.ascii_lowercase + string.digits
    return "node-" + "".join(secrets.choice(alphabet) for _ in range(6))


def make_root_pw():
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(14))


def crypt_sha512(password):
    try:
        import crypt
        return crypt.crypt(password, crypt.METHOD_SHA512)
    except Exception:
        pass
    try:
        return subprocess.check_output(["openssl", "passwd", "-6", password], text=True).strip()
    except Exception:
        return ""


def user_data(hostname, root_pw):
    return (
        "#cloud-config\n"
        f"hostname: {hostname}\n"
        f"fqdn: {hostname}\n"
        "manage_etc_hosts: true\n"
        "enable_ssh: true\n"
        "ssh_pwauth: true\n"
        "disable_root: false\n"
        "chpasswd:\n"
        "  expire: false\n"
        "  list: |\n"
        f"    root:{root_pw}\n"
        "    rtclm:reticulum\n"
        "users:\n"
        "  - name: rtclm\n"
        "    gecos: Reticulum\n"
        "    primary_group: users\n"
        "    groups: [adm, dialout, sudo, audio, video, plugdev, netdev, gpio, i2c, spi]\n"
        "    shell: /bin/bash\n"
        "    lock_passwd: false\n"
        "    sudo: ALL=(ALL) NOPASSWD:ALL\n"
        "    plain_text_passwd: reticulum\n"
    )


def yaml_str(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def wifi_nm(ssid, psk):
    return (
        "[connection]\n"
        "id=rns-wifi\n"
        "uuid=7c9e6679-7425-40de-944b-e07fc1f90ae7\n"
        "type=wifi\n"
        "interface-name=wlan0\n"
        "autoconnect=true\n"
        "autoconnect-priority=100\n"
        "\n"
        "[wifi]\n"
        f"ssid={ssid}\n"
        "mode=infrastructure\n"
        "\n"
        "[wifi-security]\n"
        "key-mgmt=wpa-psk\n"
        f"psk={psk}\n"
        "\n"
        "[ipv4]\n"
        "method=auto\n"
        "\n"
        "[ipv6]\n"
        "method=auto\n"
    )


def network_config(ssid, psk):
    return (
        "network:\n"
        "  version: 2\n"
        "  wifis:\n"
        "    wlan0:\n"
        "      dhcp4: true\n"
        "      regulatory-domain: \"PL\"\n"
        "      access-points:\n"
        f"        {yaml_str(ssid)}:\n"
        f"          password: {yaml_str(psk)}\n"
        "      optional: true\n"
    )


def wpa_conf(ssid, psk):
    s = ssid.replace("\\", "\\\\").replace('"', '\\"')
    p = psk.replace("\\", "\\\\").replace('"', '\\"')
    return (
        "country=PL\n"
        "ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev\n"
        "update_config=1\n"
        "\n"
        "network={\n"
        f'    ssid="{s}"\n'
        f'    psk="{p}"\n'
        "    key_mgmt=WPA-PSK\n"
        "}\n"
    )


def firstboot_sh(ssid, psk, hostname, root_pw, do_install=True, auto_update=False):
    repo = REPO_URL.replace("'", "'\\''")
    ssid_q = ssid.replace("'", "'\\''")
    psk_q = psk.replace("'", "'\\''")
    host_q = hostname.replace("'", "'\\''")
    root_q = root_pw.replace("'", "'\\''")
    if do_install:
        install_block = f"""
mkdir -p /usr/local/sbin /etc/systemd/system /var/lib/rns
cat > /usr/local/sbin/rns-install-once.sh << 'INST'
#!/bin/bash
set +e
FLAG=/var/lib/rns/.installed
[ -f "$FLAG" ] && exit 0
mkdir -p /var/lib/rns
exec >> /var/lib/rns/install.log 2>&1
echo "install $(date)"
for i in $(seq 1 90); do
  ping -c1 -W2 1.1.1.1 && break
  ping -c1 -W2 8.8.8.8 && break
  sleep 2
done
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq wget ca-certificates git python3 python3-pip openssl
RAW="{repo}"
RAW="${{RAW%.git}}"
RAW="https://raw.githubusercontent.com/${{RAW#https://github.com/}}/refs/heads/master/install.sh"
wget -O /tmp/rns-install.sh "$RAW" && RNS_AUTO_UPDATE={1 if auto_update else 0} bash /tmp/rns-install.sh '{repo}'
touch "$FLAG"
INST
chmod 755 /usr/local/sbin/rns-install-once.sh
cat > /etc/systemd/system/rns-install.service << 'UNIT'
[Unit]
Description=RNS gateway install
After=network-online.target NetworkManager-wait-online.service
Wants=network-online.target
[Service]
Type=oneshot
TimeoutStartSec=0
ExecStart=/usr/local/sbin/rns-install-once.sh
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable rns-install.service
systemctl start rns-install.service || /usr/local/sbin/rns-install-once.sh
echo "instalacja repo zlecona"
"""
    else:
        install_block = 'echo "pomijam instalację bramki"\n'
    return f"""#!/bin/bash
set +e
exec >> /boot/firmware/rns-firstboot.log 2>&1 || exec >> /boot/rns-firstboot.log 2>&1
echo "===== RNS firstboot $(date) ====="
BOOT=/boot/firmware
[ -f "$BOOT/cmdline.txt" ] || BOOT=/boot
rm -f /etc/nologin /run/nologin /var/lib/nologin
systemctl disable --now userconfig.service userconfig-pi.service >/dev/null 2>&1
systemctl stop systemd-user-sessions >/dev/null 2>&1
rm -f /etc/nologin /run/nologin
systemctl start systemd-user-sessions >/dev/null 2>&1
echo '{host_q}' > /etc/hostname
hostname '{host_q}' >/dev/null 2>&1
hostnamectl set-hostname '{host_q}' >/dev/null 2>&1
if ! id rtclm >/dev/null 2>&1; then
  useradd -m -s /bin/bash -G sudo,adm,netdev,gpio,i2c,spi,video,plugdev rtclm
fi
echo 'rtclm:reticulum' | chpasswd
echo 'root:{root_q}' | chpasswd
passwd -u root >/dev/null 2>&1
usermod -s /bin/bash rtclm >/dev/null 2>&1
usermod -s /bin/bash root >/dev/null 2>&1
echo 'rtclm ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/rtclm
chmod 440 /etc/sudoers.d/rtclm
mkdir -p /etc/ssh/sshd_config.d
printf '%s\\n' 'PasswordAuthentication yes' 'PermitRootLogin yes' 'KbdInteractiveAuthentication yes' > /etc/ssh/sshd_config.d/99-rns.conf
systemctl enable ssh >/dev/null 2>&1
systemctl enable sshd >/dev/null 2>&1
systemctl start ssh >/dev/null 2>&1
systemctl start sshd >/dev/null 2>&1
raspi-config nonint do_ssh 0 >/dev/null 2>&1
systemctl reload ssh >/dev/null 2>&1 || systemctl restart ssh >/dev/null 2>&1
echo "ssh/user/hostname ustawione"
rfkill unblock wifi >/dev/null 2>&1
rfkill unblock all >/dev/null 2>&1
mkdir -p /etc/NetworkManager/system-connections
cat > /etc/NetworkManager/system-connections/rns-wifi.nmconnection << 'NMEOF'
{wifi_nm(ssid, psk)}NMEOF
chmod 600 /etc/NetworkManager/system-connections/rns-wifi.nmconnection
chown root:root /etc/NetworkManager/system-connections/rns-wifi.nmconnection
echo "nmconnection zapisany"
systemctl restart NetworkManager >/dev/null 2>&1
sleep 3
nmcli radio wifi on >/dev/null 2>&1
nmcli connection reload >/dev/null 2>&1
nmcli device wifi connect '{ssid_q}' password '{psk_q}' >/dev/null 2>&1
nmcli connection up rns-wifi >/dev/null 2>&1
echo "nmcli exit=$?"
{install_block}
if [ -f /var/lib/rns/.installed ]; then
  sed -i -E 's/ systemd\\.run[^ ]*//g' "$BOOT/cmdline.txt" 2>/dev/null
  echo "systemd.run zdjęty — bramka już stoi"
fi
echo "RNS firstboot done"
"""


HOOK = "bash /boot/firmware/rns-firstboot.sh || bash /boot/rns-firstboot.sh || true\n"


def hook_firstrun(boot, ssid, psk, hostname, root_pw, log, do_install=True, auto_update=False):
    path = os.path.join(boot, "firstrun.sh")
    if os.path.isfile(path):
        log("jest firstrun.sh z Imagera — " + str(os.path.getsize(path)) + " B")
        try:
            text = read_text(path)
        except Exception:
            text = open(path, encoding="utf-8", errors="replace").read()
        if "rns-firstboot.sh" in text:
            log("hook już był w firstrun.sh")
            return
        if re.search(r"^exit 0", text, re.M):
            text = text.replace("exit 0", HOOK + "exit 0", 1)
            log("hook wstawiony przed exit 0")
        else:
            text = text.rstrip() + "\n" + HOOK
            log("hook dopisany na końcu firstrun.sh")
        write_text(path, text)
        return
    log("brak firstrun.sh — tworzę własny")
    write_text(path, firstboot_sh(ssid, psk, hostname, root_pw, do_install, auto_update))


def apply(boot, ssid, psk, hostname, root_pw, log, do_install=True, auto_update=False):
    def peek(name):
        p = os.path.join(boot, name)
        if os.path.isfile(p):
            log(f"  {name}: {os.path.getsize(p)} B")
        else:
            log(f"  {name}: BRAK")

    log("1. bootfs = " + boot)
    log("2. pliki na karcie:")
    for name in (
        "cmdline.txt", "config.txt", "firstrun.sh", "user-data",
        "network-config", "meta-data", "wpa_supplicant.conf", "ssh",
    ):
        peek(name)

    cmd_path = os.path.join(boot, "cmdline.txt")
    old_cmd = read_text(cmd_path)
    log("3. cmdline PRZED:")
    log("   " + old_cmd.strip())
    if "ds=nocloud" in old_cmd:
        log("   wykryto cloud-init (ds=nocloud) — Imager 2.x / Trixie")
    if "systemd.run" in old_cmd:
        log("   wykryto systemd.run (stary firstrun)")
    new_cmd = patch_cmdline(old_cmd)
    if "cfg80211.ieee80211_regdom=" not in new_cmd:
        new_cmd = new_cmd.rstrip() + " cfg80211.ieee80211_regdom=PL\n"
        log("   dopisuję regdom=PL")
    write_text(cmd_path, new_cmd)
    log("4. cmdline PO:")
    log("   " + new_cmd.strip())

    cfg_path = os.path.join(boot, "config.txt")
    old_cfg = read_text(cfg_path)
    new_cfg = patch_config(old_cfg)
    write_text(cfg_path, new_cfg)
    log("5. config.txt: dtoverlay=dwc2=" + str("dtoverlay=dwc2" in new_cfg) +
        "  otg_mode zakomentowane=" + str(bool(re.search(r"^#otg_mode=", new_cfg, re.M))))

    log("6. zapis network-config (cloud-init / netplan — tak działa Trixie)")
    write_text(os.path.join(boot, "network-config"), network_config(ssid, psk))
    log("   SSID=" + ssid + "  hasło=" + str(len(psk)) + " znaków")

    log("7. zapis wpa_supplicant.conf (starsze obrazy)")
    write_text(os.path.join(boot, "wpa_supplicant.conf"), wpa_conf(ssid, psk))

    log("8. hostname=" + hostname + "  user=rtclm")
    write_text(os.path.join(boot, "user-data"), user_data(hostname, root_pw))
    if not os.path.isfile(os.path.join(boot, "meta-data")):
        write_text(os.path.join(boot, "meta-data"), "instance-id: " + hostname + "\n")
    hashed = crypt_sha512("reticulum")
    if hashed:
        write_text(os.path.join(boot, "userconf.txt"), "rtclm:" + hashed + "\n")
        write_text(os.path.join(boot, "userconf"), "rtclm:" + hashed + "\n")
        log("   userconf.txt zapisany")
    else:
        log("   brak openssl/crypt — user z cloud-init i firstboot")

    log("9. zapis rns-firstboot.sh")
    write_text(os.path.join(boot, "rns-firstboot.sh"), firstboot_sh(ssid, psk, hostname, root_pw, do_install, auto_update))
    log("   auto-install repo=" + str(do_install) + "  auto-update=" + str(auto_update))

    log("10. hook firstrun")
    hook_firstrun(boot, ssid, psk, hostname, root_pw, log, do_install, auto_update)

    write_text(os.path.join(boot, "ssh"), "")
    log("11. plik ssh (włączenie demona)")

    log("12. kontrola po zapisie:")
    for name in ("cmdline.txt", "network-config", "user-data", "userconf.txt", "rns-firstboot.sh", "firstrun.sh", "ssh"):
        peek(name)
    log("13. gotowe. SSH: rtclm / reticulum   host: " + hostname)


def box():
    f = QFrame()
    f.setObjectName("box")
    f.setLayout(QVBoxLayout())
    f.layout().setContentsMargins(12, 10, 12, 10)
    f.layout().setSpacing(6)
    return f


class App(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Reticulum SD")
        self.resize(580, 680)
        self.root_pw = ""
        self.hostname = ""
        self.cards = []
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        col = QVBoxLayout(root)
        col.setContentsMargins(16, 16, 16, 16)
        col.setSpacing(10)

        title = QLabel("RETICULUM  ·  karta SD")
        title.setObjectName("title")
        hint = QLabel(
            "Najpierw nagraj Lite 64-bit Raspberry Pi Imagerem (Wi‑Fi możesz też tam ustawić). "
            "Potem zostaw kartę i wciśnij RUN — dopiszemy firstboot bramki."
        )
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        col.addWidget(title)
        col.addWidget(hint)

        b1 = box()
        row = QHBoxLayout()
        row.addWidget(QLabel("Karta"))
        self.card = QComboBox()
        row.addWidget(self.card, 1)
        scan = QPushButton("Odśwież")
        scan.clicked.connect(self.refresh)
        row.addWidget(scan)
        b1.layout().addLayout(row)
        self.err_card = QLabel("")
        self.err_card.setObjectName("err")
        b1.layout().addWidget(self.err_card)
        col.addWidget(b1)

        b2 = box()
        b2.layout().addWidget(QLabel("Wi‑Fi (DHCP)"))
        g = QGridLayout()
        self.ssid = QLineEdit()
        self.psk = QLineEdit()
        self.psk.setEchoMode(QLineEdit.Password)
        g.addWidget(QLabel("SSID"), 0, 0)
        g.addWidget(self.ssid, 0, 1)
        g.addWidget(QLabel("Hasło"), 1, 0)
        g.addWidget(self.psk, 1, 1)
        b2.layout().addLayout(g)
        saved = {}
        try:
            with open(WIFI_SAVE, encoding="utf-8") as fh:
                saved = json.load(fh)
        except Exception:
            saved = {}
        self.ssid.setText(str(saved.get("ssid") or ""))
        self.psk.setText(str(saved.get("psk") or ""))
        self.err_net = QLabel("")
        self.err_net.setObjectName("err")
        b2.layout().addWidget(self.err_net)
        self.do_install = QCheckBox("Pobierz repo i startuj bramkę (http/https) przy starcie Pi")
        self.do_install.setChecked(bool(saved.get("do_install", True)))
        b2.layout().addWidget(self.do_install)
        self.auto_update = QCheckBox("Automatycznie pobieraj nowe aktualizacje repozytorium na urządzenie")
        self.auto_update.setChecked(bool(saved.get("auto_update", False)))
        b2.layout().addWidget(self.auto_update)
        col.addWidget(b2)

        cred = box()
        self.host_lab = QLabel("host: —")
        self.host_lab.setObjectName("cred")
        self.user_lab = QLabel("ssh: rtclm / reticulum")
        self.user_lab.setObjectName("cred")
        self.pw_lab = QLabel("hasło roota: (po RUN)")
        self.pw_lab.setObjectName("rootpw")
        self.pw_lab.setWordWrap(True)
        copy = QPushButton("Kopiuj hasło roota")
        copy.clicked.connect(self.copy_root)
        cred.layout().addWidget(self.host_lab)
        cred.layout().addWidget(self.user_lab)
        cred.layout().addWidget(self.pw_lab)
        cred.layout().addWidget(copy)
        kh = QHBoxLayout()
        self.kh_host = QLineEdit(str(saved.get("ssh_host") or "192.168.0.153"))
        self.kh_host.setPlaceholderText("IP albo node-xxxxx")
        wipe = QPushButton("Wyrzuć z known_hosts")
        wipe.clicked.connect(self.wipe_known)
        kh.addWidget(self.kh_host)
        kh.addWidget(wipe)
        cred.layout().addLayout(kh)
        col.addWidget(cred)

        run = QPushButton("RUN")
        run.setObjectName("run")
        run.clicked.connect(self.run)
        col.addWidget(run)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(220)
        col.addWidget(self.log)
        for lab in self.findChildren(QLabel):
            lab.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        self.refresh()

    def wipe_known(self):
        targets = []
        typed = self.kh_host.text().strip()
        if typed:
            targets.append(typed)
        if self.hostname:
            targets.append(self.hostname)
            targets.append(self.hostname + ".local")
        seen = []
        for t in targets:
            if t not in seen:
                seen.append(t)
        if not seen:
            self.say("wpisz IP albo zrób RUN (żeby była nazwa hosta)")
            return
        for t in seen:
            self.say(drop_known_host(t))

    def copy_root(self):
        if not self.root_pw:
            return
        QApplication.clipboard().setText(self.root_pw)
        self.say("hasło roota w schowku")

    def say(self, text):
        self.log.append(text)
        self.log.moveCursor(QTextCursor.End)

    def refresh(self):
        self.card.clear()
        self.cards = list_bootfs()
        if not self.cards:
            self.card.addItem("włóż kartę z Lite i odśwież")
            self.say("nie widzę bootfs — najpierw Imager")
            return
        for c in self.cards:
            self.card.addItem(c["label"])
        self.say("karta: " + self.cards[0]["label"])

    def selected(self):
        i = self.card.currentIndex()
        if i < 0 or i >= len(self.cards):
            return None
        return self.cards[i]

    def run(self):
        self.err_card.setText("")
        self.err_net.setText("")
        card = self.selected()
        ssid = self.ssid.text().strip()
        if not card:
            self.err_card.setText("tu: karta z cmdline.txt (po Imagerze)")
            return
        if not ssid:
            self.err_net.setText("tu: podaj SSID")
            return
        self.hostname = make_hostname()
        self.root_pw = make_root_pw()
        self.host_lab.setText("host: " + self.hostname)
        self.pw_lab.setText("hasło roota: " + self.root_pw)
        self.say("=== RUN " + card["path"] + " ===")
        try:
            apply(
                card["path"], ssid, self.psk.text(), self.hostname, self.root_pw, self.say,
                self.do_install.isChecked(),
                self.auto_update.isChecked(),
            )
            with open(WIFI_SAVE, "w", encoding="utf-8") as fh:
                json.dump({
                    "ssid": ssid,
                    "psk": self.psk.text(),
                    "ssh_host": self.kh_host.text().strip(),
                    "do_install": self.do_install.isChecked(),
                    "auto_update": self.auto_update.isChecked(),
                }, fh)
        except Exception as exc:
            self.err_card.setText(str(exc))
            self.say("BŁĄD: " + str(exc))
            return


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 10))
    app.setStyleSheet(STYLE)
    win = App()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
