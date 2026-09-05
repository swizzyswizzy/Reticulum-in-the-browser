#!/usr/bin/env python3
"""Jeden ekran: pobiera Lite 64-bit, zapisuje kartę."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import urllib.request

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

IMAGE_URL = "https://downloads.raspberrypi.com/raspios_lite_arm64_latest"
CACHE = os.path.join(os.path.expanduser("~"), ".cache", "reticulum-gateway")


STYLE = """
QMainWindow, QWidget#root { background: #1b1e1c; color: #d7ddd4; }
QLabel { color: #d7ddd4; font-size: 13px; }
QLabel#title { color: #cfe7c4; font-size: 18px; font-weight: 700; }
QLabel#hint { color: #8b9486; font-size: 12px; }
QLabel#err { color: #e08a7a; font-size: 12px; }
QLineEdit, QComboBox {
  background: #111411; color: #e8eee4; border: 1px solid #3a4338;
  padding: 6px 8px; selection-background-color: #3d6b46;
}
QLineEdit:focus, QComboBox:focus { border: 1px solid #7dba8a; }
QRadioButton { spacing: 8px; }
QRadioButton::indicator { width: 12px; height: 12px; border: 1px solid #7dba8a; background: #111411; }
QRadioButton::indicator:checked { background: #7dba8a; }
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
QProgressBar { border: 1px solid #3a4338; background: #111411; color: #cfe7c4; text-align: center; height: 16px; }
QProgressBar::chunk { background: #3c6b46; }
QFrame#box { border: 1px solid #2c332c; background: #161916; }
"""


def repo_url():
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    try:
        url = subprocess.check_output(
            ["git", "-C", root, "remote", "get-url", "origin"],
            text=True, stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return ""
    if url.startswith("git@"):
        path = url.split(":", 1)[-1]
        url = "https://github.com/" + path
    if url.endswith(".git") is False:
        url += ".git"
    return url


def is_bootfs(path):
    return os.path.isfile(os.path.join(path, "cmdline.txt")) and os.path.isfile(
        os.path.join(path, "config.txt")
    )


def list_cards():
    cards = []
    if os.name == "nt":
        try:
            raw = subprocess.check_output(
                ["wmic", "logicaldisk", "where", "drivetype=2", "get", "deviceid,size,volumename"],
                text=True, stderr=subprocess.DEVNULL, creationflags=0x08000000,
            )
        except Exception:
            raw = ""
        for line in raw.splitlines():
            parts = line.split()
            if len(parts) >= 1 and re.match(r"^[A-Z]:$", parts[0]):
                letter = parts[0] + "/"
                size = 0
                for p in parts[1:]:
                    if p.isdigit():
                        size = int(p)
                gb = size / (1024 ** 3) if size else 0
                name = f"Karta {gb:.1f} GB" if gb else "Karta SD"
                cards.append({"label": name, "boot": letter if is_bootfs(letter) else "", "root": letter})
        if not cards:
            for letter in "DEFGHIJKLMNOPQRSTUVWXYZ":
                root = f"{letter}:/"
                if is_bootfs(root):
                    cards.append({"label": "Karta Raspberry", "boot": root, "root": root})
    else:
        for base in ("/media", "/run/media", "/Volumes", "/mnt"):
            if not os.path.isdir(base):
                continue
            for dirpath, dirnames, filenames in os.walk(base):
                if "cmdline.txt" in filenames and "config.txt" in filenames:
                    cards.append({"label": "Karta Raspberry", "boot": dirpath, "root": dirpath})
                    dirnames.clear()
                if dirpath[len(base):].count(os.sep) >= 3:
                    dirnames.clear()
    return cards


def patch_cmdline(text: str) -> str:
    line = " ".join(text.replace("\n", " ").split())
    line = re.sub(r"\bsystemd\.run\S*", "", line)
    line = re.sub(r"\s+", " ", line).strip()
    line += " systemd.run=/boot/firmware/firstrun.sh systemd.run_success_action=none systemd.run_failure_action=none"
    return line + "\n"


def nm_file(kind, ssid, psk, dhcp, ip, prefix, gw, dns):
    lines = ["[connection]", "id=rns-net", f"type={'wifi' if kind == 'wifi' else 'ethernet'}", "autoconnect=true", ""]
    if kind == "wifi":
        lines += ["[wifi]", f"ssid={ssid}", "mode=infrastructure", "", "[wifi-security]", "key-mgmt=wpa-psk", f"psk={psk}", ""]
    else:
        lines += ["[ethernet]", ""]
    lines += ["[ipv4]"]
    if dhcp:
        lines.append("method=auto")
    else:
        lines += ["method=manual", f"address1={ip}/{prefix},{gw}", f"dns={dns};"]
    lines += ["", "[ipv6]", "method=auto", ""]
    return "\n".join(lines) + "\n"


def firstrun_script(repo, kind):
    repo_q = repo.replace("'", "'\\''")
    return f"""#!/bin/bash
set +e
exec > /boot/firmware/rns-firstboot.log 2>&1 || exec > /boot/rns-firstboot.log 2>&1
echo "RNS firstboot start"
BOOT=/boot/firmware
[ -f "$BOOT/cmdline.txt" ] || BOOT=/boot
if ! id rnode >/dev/null 2>&1; then
  useradd -m -s /bin/bash rnode
  echo 'rnode:rnode' | chpasswd
  usermod -aG sudo rnode
  echo 'rnode ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/rnode
fi
systemctl enable ssh >/dev/null 2>&1
systemctl start ssh >/dev/null 2>&1
if [ -f "$BOOT/rns-net.nmconnection" ]; then
  mkdir -p /etc/NetworkManager/system-connections
  cp "$BOOT/rns-net.nmconnection" /etc/NetworkManager/system-connections/rns-net.nmconnection
  chmod 600 /etc/NetworkManager/system-connections/rns-net.nmconnection
  nmcli connection reload >/dev/null 2>&1
  nmcli connection up rns-net >/dev/null 2>&1
fi
echo "czekam na siec ({kind})"
for i in $(seq 1 45); do
  ip=$(hostname -I 2>/dev/null | awk '{{print $1}}')
  [ -n "$ip" ] && break
  sleep 2
done
echo "IP=$ip"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq curl ca-certificates git python3 python3-pip openssl
RAW="{repo_q}"
RAW="${{RAW%.git}}"
case "$RAW" in
  https://github.com/*) RAW="https://raw.githubusercontent.com/${{RAW#https://github.com/}}/main/install.sh" ;;
esac
curl -fsSL "$RAW" -o /tmp/rns-install.sh && bash /tmp/rns-install.sh '{repo_q}'
sed -i -E 's/ systemd.run[^ ]*//g' "$BOOT/cmdline.txt" 2>/dev/null
rm -f "$BOOT/firstrun.sh" "$BOOT/rns-net.nmconnection"
echo "RNS firstboot done"
"""


def write_boot(boot, repo, kind, wifi, static):
    with open(os.path.join(boot, "cmdline.txt"), encoding="utf-8") as fh:
        cmd = fh.read()
    with open(os.path.join(boot, "cmdline.txt"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(patch_cmdline(cmd))
    with open(os.path.join(boot, "firstrun.sh"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(firstrun_script(repo, kind))
    if kind == "wifi" or not static["dhcp"]:
        with open(os.path.join(boot, "rns-net.nmconnection"), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(nm_file(
                kind, wifi["ssid"], wifi["psk"], static["dhcp"],
                static["ip"], static["prefix"], static["gw"], static["dns"],
            ))
    open(os.path.join(boot, "ssh"), "w", encoding="utf-8").close()


class Worker(QObject):
    progress = Signal(int)
    log = Signal(str)
    done = Signal(str)
    fail = Signal(str)

    def __init__(self, dest_xz):
        super().__init__()
        self.dest_xz = dest_xz
        self._stop = False

    def run(self):
        os.makedirs(os.path.dirname(self.dest_xz), exist_ok=True)
        self.log.emit("pobieram Raspberry Pi OS Lite 64-bit")
        try:
            req = urllib.request.Request(IMAGE_URL, headers={"User-Agent": "rns-imager"})
            with urllib.request.urlopen(req, timeout=60) as src:
                total = int(src.headers.get("Content-Length") or 0)
                got = 0
                with open(self.dest_xz, "wb") as out:
                    while True:
                        chunk = src.read(1024 * 256)
                        if not chunk:
                            break
                        out.write(chunk)
                        got += len(chunk)
                        if total:
                            self.progress.emit(int(got * 100 / total))
                        elif got:
                            self.progress.emit(min(99, got // (1024 * 1024)))
            self.progress.emit(100)
            self.done.emit(self.dest_xz)
        except Exception as exc:
            self.fail.emit(str(exc))


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
        self.resize(640, 640)
        self.cards = []
        self.thread = None
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        col = QVBoxLayout(root)
        col.setContentsMargins(16, 16, 16, 16)
        col.setSpacing(10)

        title = QLabel("RETICULUM  ·  karta SD")
        title.setObjectName("title")
        hint = QLabel("Lite 64-bit ściągnie się sam. Włóż kartę, ustaw sieć, RUN.")
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
        scan.clicked.connect(self.refresh_cards)
        row.addWidget(scan)
        b1.layout().addLayout(row)
        self.err_card = QLabel("")
        self.err_card.setObjectName("err")
        b1.layout().addWidget(self.err_card)
        col.addWidget(b1)

        b2 = box()
        r = QHBoxLayout()
        self.eth = QRadioButton("Ethernet HAT")
        self.wifi = QRadioButton("Wi-Fi")
        self.eth.setChecked(True)
        g = QButtonGroup(self)
        g.addButton(self.eth)
        g.addButton(self.wifi)
        r.addWidget(self.eth)
        r.addWidget(self.wifi)
        r.addStretch()
        b2.layout().addLayout(r)
        self.wifi_box = QWidget()
        wg = QGridLayout(self.wifi_box)
        wg.setContentsMargins(0, 6, 0, 0)
        self.ssid = QLineEdit()
        self.psk = QLineEdit()
        self.psk.setEchoMode(QLineEdit.Password)
        wg.addWidget(QLabel("SSID"), 0, 0)
        wg.addWidget(self.ssid, 0, 1)
        wg.addWidget(QLabel("Hasło"), 1, 0)
        wg.addWidget(self.psk, 1, 1)
        b2.layout().addWidget(self.wifi_box)
        self.err_net = QLabel("")
        self.err_net.setObjectName("err")
        b2.layout().addWidget(self.err_net)
        col.addWidget(b2)

        b3 = box()
        r = QHBoxLayout()
        self.dhcp = QRadioButton("DHCP")
        self.static = QRadioButton("Stałe IP")
        self.dhcp.setChecked(True)
        g2 = QButtonGroup(self)
        g2.addButton(self.dhcp)
        g2.addButton(self.static)
        r.addWidget(self.dhcp)
        r.addWidget(self.static)
        r.addStretch()
        b3.layout().addLayout(r)
        self.ip_box = QWidget()
        ig = QGridLayout(self.ip_box)
        ig.setContentsMargins(0, 6, 0, 0)
        self.ip = QLineEdit("192.168.0.50")
        self.prefix = QLineEdit("24")
        self.gw = QLineEdit("192.168.0.1")
        self.dns = QLineEdit("1.1.1.1")
        ig.addWidget(QLabel("IP"), 0, 0)
        ig.addWidget(self.ip, 0, 1)
        ig.addWidget(QLabel("/"), 0, 2)
        ig.addWidget(self.prefix, 0, 3)
        ig.addWidget(QLabel("Bramka"), 1, 0)
        ig.addWidget(self.gw, 1, 1, 1, 3)
        ig.addWidget(QLabel("DNS"), 2, 0)
        ig.addWidget(self.dns, 2, 1, 1, 3)
        b3.layout().addWidget(self.ip_box)
        self.err_ip = QLabel("")
        self.err_ip.setObjectName("err")
        b3.layout().addWidget(self.err_ip)
        col.addWidget(b3)

        repo = repo_url()
        info = QLabel(
            "System i bramka wezmą się z internetu przy pierwszym starcie Pi. "
            + (f"Repo: {repo}" if repo else "Wypchnij to repo na GitHub (git remote origin).")
        )
        info.setObjectName("hint")
        info.setWordWrap(True)
        col.addWidget(info)
        self.repo = repo

        self.bar = QProgressBar()
        self.bar.setValue(0)
        col.addWidget(self.bar)

        run = QPushButton("RUN")
        run.setObjectName("run")
        run.clicked.connect(self.run)
        col.addWidget(run)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(120)
        col.addWidget(self.log)

        self.eth.toggled.connect(self.sync)
        self.wifi.toggled.connect(self.sync)
        self.dhcp.toggled.connect(self.sync)
        self.static.toggled.connect(self.sync)
        self.sync()
        self.refresh_cards()
        if self.repo:
            self.say("repo " + self.repo)

    def sync(self):
        self.wifi_box.setVisible(self.wifi.isChecked())
        self.ip_box.setVisible(self.static.isChecked())

    def say(self, text):
        self.log.append(text)
        self.log.moveCursor(QTextCursor.End)

    def mark(self, w, bad):
        w.setStyleSheet("border: 1px solid #e08a7a;" if bad else "")

    def refresh_cards(self):
        self.card.clear()
        self.cards = list_cards()
        if not self.cards:
            self.card.addItem("włóż kartę i odśwież")
            self.say("nie widzę karty")
            return
        for c in self.cards:
            extra = " · gotowa" if c.get("boot") else ""
            self.card.addItem(c["label"] + extra)
        self.say("karta: " + self.cards[0]["label"])

    def selected(self):
        i = self.card.currentIndex()
        if i < 0 or i >= len(self.cards):
            return None
        return self.cards[i]

    def run(self):
        self.err_card.setText("")
        self.err_net.setText("")
        self.err_ip.setText("")
        bad = False
        card = self.selected()
        if not card:
            self.err_card.setText("tu: włóż kartę SD i odśwież")
            bad = True
        if self.wifi.isChecked() and not self.ssid.text().strip():
            self.err_net.setText("tu: brak SSID")
            self.mark(self.ssid, True)
            bad = True
        else:
            self.mark(self.ssid, False)
        if self.static.isChecked() and not re.match(r"^\d+\.\d+\.\d+\.\d+$", self.ip.text().strip()):
            self.err_ip.setText("tu: IP wygląda źle")
            self.mark(self.ip, True)
            bad = True
        else:
            self.mark(self.ip, False)
        if not self.repo or "YOURUSER" in self.repo:
            self.err_card.setText("to repo nie ma publicznego origin — wypchnij je na GitHub")
            bad = True
        if bad:
            self.say("stop — popraw czerwone")
            return

        dest = os.path.join(CACHE, "raspios-lite-arm64.img.xz")
        if os.path.isfile(dest) and os.path.getsize(dest) > 10_000_000:
            self.say("obraz już jest w cache")
            self.bar.setValue(100)
            self.after_download(dest)
            return

        self.say("ściągam obraz…")
        self.thread = QThread()
        self.worker = Worker(dest)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.bar.setValue)
        self.worker.log.connect(self.say)
        self.worker.done.connect(self.after_download)
        self.worker.fail.connect(self.download_fail)
        self.worker.done.connect(self.thread.quit)
        self.worker.fail.connect(self.thread.quit)
        self.thread.start()

    def download_fail(self, err):
        self.say("pobieranie padło: " + err)
        self.err_card.setText("tu: nie ściągnąłem obrazu — sieć?")

    def after_download(self, _path):
        card = self.selected()
        if not card:
            self.err_card.setText("tu: karta zniknęła")
            return
        boot = card.get("boot") or ""
        if not boot or not is_bootfs(boot):
            self.say("karta nie ma jeszcze systemu — nagraj Lite tym obrazem z cache, odśwież, RUN jeszcze raz")
            self.say("cache: " + os.path.join(CACHE, "raspios-lite-arm64.img.xz"))
            self.err_card.setText("tu: po nagraniu Lite odśwież kartę i RUN")
            return
        kind = "wifi" if self.wifi.isChecked() else "ethernet"
        try:
            write_boot(
                boot, self.repo, kind,
                {"ssid": self.ssid.text(), "psk": self.psk.text()},
                {
                    "dhcp": self.dhcp.isChecked(),
                    "ip": self.ip.text().strip(),
                    "prefix": self.prefix.text().strip() or "24",
                    "gw": self.gw.text().strip(),
                    "dns": self.dns.text().strip() or "1.1.1.1",
                },
            )
        except Exception as exc:
            self.say("zapis boot: " + str(exc))
            self.err_card.setText("tu: nie zapisałem na kartę")
            return
        self.say("zapisane. wyjmij kartę → Pi → zasilanie")
        self.say("pierwszy start 3–5 min, potem http://IP:4240")


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
