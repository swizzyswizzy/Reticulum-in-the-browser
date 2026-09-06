# Reticulum Gateway

Panel WWW na porcie **4240**. Jedna bramka Python.

## Karta SD — kreator

Na komputerze:

```bash
cd wizard
pip install -r requirements.txt
python3 rns-imager.py
```

1. Nagraj **Raspberry Pi OS Lite 64-bit** Imagerem (goły system wystarczy).
2. Zostaw kartę w czytniku, otwórz kreator.
3. Ethernet albo Wi‑Fi, DHCP albo stałe IP. Repo: https://github.com/swizzyswizzy/Reticulum-in-the-browser
4. Zapisz, wyjmij kartę, włóż do Pi, zasilanie.
5. Pierwszy start 3–5 min. Potem `http://IP:4240`.

## Start przy rozwoju

```bash
./start.sh
```
