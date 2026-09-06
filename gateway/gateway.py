#!/usr/bin/env python3
"""Lokalna bramka HTTP dla dodatku Reticulum Gateway."""

from __future__ import annotations

import argparse
import json
import os
import socket
import ssl
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

PORT = 80
HTTPS_PORT = 443
APP_NAME = "Reticulum Gateway"
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
DATA_FILE = os.path.expanduser("~/.reticulum-gateway/data.json")
MSG_FILE = os.path.expanduser("~/.reticulum-gateway/messages.json")
LXMF_DIR = os.path.expanduser("~/.reticulum-gateway/lxmf")
PAGES_DIR = os.path.expanduser("~/.reticulum-gateway/pages")
REPO_URL = "https://github.com/swizzyswizzy/Reticulum-in-the-browser"
data_lock = threading.Lock()
msg_lock = threading.Lock()
lxmf_router = None
lxmf_source = None
lxmf_address = None
lxmf_ok = False
node_dest = None
node_identity = None
DEMO_HASH_DOCS = "a8d24177d946de4f1f0a0fe1af9a1338"
DEMO_HASH_HUB = "9ce92808be498e9e05590ff27cbfdfe4"

nodes_lock = threading.Lock()
nodes = {}
sse_clients = []
sse_lock = threading.Lock()
rns_ready = False
demo_mode = False
device_name = socket.gethostname() or "rNode"


def load_store():
    with data_lock:
        try:
            with open(DATA_FILE, encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:
            data = {}
        data.setdefault("aliases", {})
        data.setdefault("history", [])
        return data


def save_store(data):
    folder = os.path.dirname(DATA_FILE)
    os.makedirs(folder, exist_ok=True)
    tmp = DATA_FILE + ".tmp"
    with data_lock:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
        os.replace(tmp, DATA_FILE)


def load_msgs():
    with msg_lock:
        try:
            with open(MSG_FILE, encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:
            data = {}
        data.setdefault("peers", {})
        return data


def save_msgs(data):
    os.makedirs(os.path.dirname(MSG_FILE), exist_ok=True)
    tmp = MSG_FILE + ".tmp"
    with msg_lock:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
        os.replace(tmp, MSG_FILE)


def add_message(peer, direction, text, title="", status="ok"):
    peer = (peer or "").lower()
    store = load_msgs()
    box = store["peers"].setdefault(peer, {"name": peer[:8], "messages": []})
    box["messages"].append({
        "dir": direction,
        "text": text or "",
        "title": title or "",
        "status": status,
        "ts": time.time(),
    })
    box["messages"] = box["messages"][-80:]
    save_msgs(store)


def list_conversations():
    store = load_msgs()
    out = []
    for peer, box in store["peers"].items():
        msgs = box.get("messages") or []
        last = msgs[-1] if msgs else {}
        out.append({
            "peer": peer,
            "name": box.get("name") or peer[:8],
            "last": last.get("text") or last.get("title") or "",
            "ts": last.get("ts") or 0,
            "count": len(msgs),
        })
    out.sort(key=lambda x: x["ts"], reverse=True)
    return out


def now() -> float:
    return time.time()


def hexhash(value) -> str:
    if isinstance(value, bytes):
        return value.hex()
    return str(value)


def upsert_node(node: dict) -> None:
    h = node["hash"]
    with nodes_lock:
        prev = nodes.get(h, {})
        prev.update(node)
        prev["last_seen"] = now()
        nodes[h] = prev
    payload = json.dumps({"type": "node", "node": public_node(nodes[h])})
    with sse_lock:
        dead = []
        for q in sse_clients:
            try:
                q.append(payload)
            except Exception:
                dead.append(q)
        for q in dead:
            sse_clients.remove(q)


def public_node(node: dict) -> dict:
    age = int(now() - node.get("last_seen", now()))
    return {
        "hash": node.get("hash"),
        "name": node.get("name") or node.get("hash", "")[:12],
        "app": node.get("app") or "nomadnetwork.node",
        "age": age,
        "demo": bool(node.get("demo")),
    }


def list_nodes() -> list:
    with nodes_lock:
        items = [public_node(n) for n in nodes.values()]
    items.sort(key=lambda n: (n.get("name") or "").lower())
    return items


def load_demo_nodes() -> None:
    upsert_node(
        {
            "hash": DEMO_HASH_DOCS,
            "name": "Dokumentacja Reticulum",
            "app": "nomadnetwork.node",
            "demo": True,
        }
    )
    upsert_node(
        {
            "hash": DEMO_HASH_HUB,
            "name": "Hub testowy",
            "app": "nomadnetwork.node",
            "demo": True,
        }
    )


def demo_page(path: str, dest_hash: str) -> str:
    title = "Dokumentacja Reticulum" if dest_hash == DEMO_HASH_DOCS else "Hub testowy"
    if path.endswith("about.mu"):
        return (
            f">O node\n\n"
            f"To jest strona demo bramki.\n\n"
            f"`[Wróć na start`{dest_hash}:/page/index.mu]\n"
        )
    return (
        f">{title}\n\n"
        f"Bramka działa. To zawartość poglądowa, bo jesteś w trybie demo "
        f"albo node nie odpowiedział.\n\n"
        f">>Linki\n\n"
        f"`[O node`{dest_hash}:/page/about.mu]\n"
        f"`[Start`:/page/index.mu]\n"
    )


def micron_to_html(text: str) -> str:
    import html as H

    colors = {
        "red": "#e07070", "green": "#7dba8a", "blue": "#7aa7d4",
        "yellow": "#d6c86a", "orange": "#d49a5a", "white": "#e7eee4",
        "black": "#111", "grey": "#9aa394", "gray": "#9aa394",
        "cyan": "#6ec4c4", "pink": "#d48aa8", "purple": "#b48ad4",
    }

    def hex3(code):
        code = code.lower()
        if code in colors:
            return colors[code]
        if len(code) == 3 and all(c in "0123456789abcdef" for c in code):
            return "#" + "".join(c * 2 for c in code)
        return None

    def wrap_chunk(txt, st):
        if not txt:
            return ""
        open_t = close_t = ""
        if st["bold"]:
            open_t += "<b>"; close_t = "</b>" + close_t
        if st["italic"]:
            open_t += "<i>"; close_t = "</i>" + close_t
        if st["under"]:
            open_t += "<u>"; close_t = "</u>" + close_t
        style = []
        if st["fg"]:
            style.append(f"color:{st['fg']}")
        if st["bg"]:
            style.append(f"background:{st['bg']}")
        if style:
            open_t = f'<span style="{";".join(style)}">' + open_t
            close_t = close_t + "</span>"
        return open_t + txt + close_t

    def parse_inline(s, st):
        out = []
        buf = []
        i = 0
        n = len(s)

        def flush():
            if buf:
                out.append(wrap_chunk("".join(buf), st))
                buf.clear()

        while i < n:
            ch = s[i]
            if ch == "\\" and i + 1 < n:
                buf.append(H.escape(s[i + 1]))
                i += 2
                continue
            if ch != "`":
                buf.append(H.escape(ch))
                i += 1
                continue
            if i + 1 >= n:
                break
            nxt = s[i + 1]
            if nxt == "`":
                flush()
                st.update(bold=False, italic=False, under=False, fg=None, bg=None)
                i += 2
                continue
            if nxt == "!":
                flush(); st["bold"] = not st["bold"]; i += 2; continue
            if nxt == "*":
                flush(); st["italic"] = not st["italic"]; i += 2; continue
            if nxt == "_":
                flush(); st["under"] = not st["under"]; i += 2; continue
            if nxt in "clra":
                flush()
                st["align"] = {"c": "center", "l": "left", "r": "right", "a": ""}[nxt]
                i += 2
                continue
            if nxt == "f":
                flush(); st["fg"] = None; i += 2; continue
            if nxt == "b":
                flush(); st["bg"] = None; i += 2; continue
            if nxt in "t=":
                i += 2
                continue
            if nxt in "FB":
                flush()
                j = i + 2
                while j < n and s[j] not in "` \t" and (j - i) < 10:
                    j += 1
                col = hex3(s[i + 2:j])
                if nxt == "F":
                    st["fg"] = col
                else:
                    st["bg"] = col
                i = j
                continue
            if nxt == "[":
                flush()
                close = s.find("]", i + 2)
                if close == -1:
                    buf.append("`")
                    i += 1
                    continue
                inner = s[i + 2:close]
                if "`" in inner:
                    label, dest = inner.split("`", 1)
                else:
                    label, dest = inner, inner
                href = dest
                low = dest.lower()
                if "lxmf@" in low:
                    href = "#/msg/" + low.split("lxmf@")[-1].split("/")[0]
                out.append(wrap_chunk(f'<a href="{H.escape(href)}">{H.escape(label)}</a>', st))
                i = close + 1
                continue
            i += 1
        flush()
        return "".join(out)

    def render_table(rows):
        parsed = []
        for row in rows:
            cells = [c.strip() for c in row.strip().strip("|").split("|")]
            if cells and all(c and set(c) <= set("-:= ") for c in cells):
                continue
            parsed.append(cells)
        if not parsed:
            return ""
        html = ["<table>"]
        for idx, cells in enumerate(parsed):
            tag = "th" if idx == 0 else "td"
            html.append("<tr>" + "".join(f"<{tag}>{H.escape(c)}</{tag}>" for c in cells) + "</tr>")
        html.append("</table>")
        return "".join(html)

    st = {"bold": False, "italic": False, "under": False, "fg": None, "bg": None, "align": ""}
    out = []
    table = []
    ascii_buf = None
    for raw in (text or "").replace("\r\n", "\n").split("\n"):
        line = raw.rstrip()
        stripped = line.strip()
        if ascii_buf is not None:
            if stripped == "#END":
                import html as H
                out.append("<pre class=\"ascii\">" + H.escape("\n".join(ascii_buf)) + "</pre>")
                ascii_buf = None
            else:
                ascii_buf.append(raw)
            continue
        if stripped == "#ASCII":
            ascii_buf = []
            continue
        if stripped.startswith("#"):
            continue
        if stripped in ("`t", "`T") or stripped.startswith("`t"):
            if table:
                out.append(render_table(table))
                table = []
            rest = stripped[2:].lstrip()
            if rest.startswith("|") or (rest and "|" in rest):
                table.append(rest)
            continue
        if stripped.startswith("|") or (table and "|" in stripped and not stripped.startswith(">")):
            table.append(stripped)
            continue
        if table:
            out.append(render_table(table))
            table = []
        if not stripped:
            out.append("<div class='sp'></div>")
            continue
        if stripped == "-" or (stripped.startswith("-") and len(stripped) <= 3):
            out.append("<hr>")
            continue
        if len(stripped) >= 3 and set(stripped) <= set("-=─━*"):
            out.append("<hr>")
            continue
        heading = 0
        rest = stripped
        if rest.startswith(">"):
            while rest.startswith(">"):
                heading += 1
                rest = rest[1:]
            rest = rest.lstrip()
        inner = parse_inline(rest, st)
        if not inner.strip() and heading == 0:
            continue
        cls = f' class="{st["align"]}"' if st["align"] else ""
        if heading:
            lvl = min(heading, 3)
            out.append(f"<h{lvl}{cls}>{inner}</h{lvl}>")
        else:
            out.append(f"<p{cls}>{inner}</p>")
    if table:
        out.append(render_table(table))
    return "\n".join(out)


def default_index_mu():
    name = host_name()
    return (
        f"`c`!{name}``\n"
        "`c`F999placeholder``\n"
        "\n"
        "#ASCII\n"
        " _._     _,-'\"\"`-._\n"
        "(,-.`._,'(       |\\`-/|\n"
        "    `-.-' \\ )-`( , o o)\n"
        "          `-    \\`_`\"'-\n"
        "#END\n"
        "\n"
        "Tu jeszcze nic nie ma. To startowa strona tego node'a.\n"
        "\n"
        f"Repozytorium: {REPO_URL}\n"
        f"Nazwa node'a: {name}\n"
    )


def ensure_pages():
    os.makedirs(PAGES_DIR, exist_ok=True)
    index = os.path.join(PAGES_DIR, "index.mu")
    if not os.path.isfile(index) or os.path.getsize(index) < 20:
        with open(index, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(default_index_mu())


def page_file(req_path: str) -> str:
    req_path = (req_path or "/page/index.mu").split("?")[0]
    if req_path.startswith("/page/"):
        req_path = req_path[6:]
    req_path = req_path.lstrip("/")
    if not req_path:
        req_path = "index.mu"
    if ".." in req_path or req_path.startswith("/"):
        req_path = "index.mu"
    return os.path.join(PAGES_DIR, req_path)


def load_local_page(req_path: str) -> str:
    ensure_pages()
    full = page_file(req_path)
    if os.path.isfile(full):
        with open(full, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    if req_path.endswith("index.mu") or req_path in ("/page/index.mu", "index.mu", "/"):
        return default_index_mu()
    return f"`!Brak strony``\n\nNie ma {req_path}\n"


def fetch_nomad_page(dest_hash_hex: str, path: str, timeout: float = 20.0) -> dict:
    path = path or "/page/index.mu"
    if not path.startswith("/"):
        path = "/" + path

    if demo_mode:
        text = demo_page(path, dest_hash_hex)
        return {"ok": True, "hash": dest_hash_hex, "path": path, "text": text, "html": micron_to_html(text), "source": "demo"}

    try:
        import RNS
    except Exception as exc:
        text = demo_page(path, dest_hash_hex)
        return {
            "ok": True,
            "hash": dest_hash_hex,
            "path": path,
            "text": text,
            "html": micron_to_html(text),
            "source": "demo",
            "note": f"Brak RNS ({exc})",
        }

    try:
        dest_hash = bytes.fromhex(dest_hash_hex)
    except ValueError:
        return {"ok": False, "error": "Niepoprawny hash"}

    if len(dest_hash) != 16:
        return {"ok": False, "error": "Hash musi mieć 32 znaki hex"}

    if node_dest is not None and dest_hash == node_dest.hash:
        text = load_local_page(path)
        return {
            "ok": True,
            "hash": dest_hash_hex,
            "path": path,
            "text": text,
            "html": micron_to_html(text),
            "source": "local",
        }

    result = {"ok": False, "error": "Timeout"}
    done = threading.Event()

    def finish(payload):
        result.clear()
        result.update(payload)
        done.set()

    try:
        if not RNS.Transport.has_path(dest_hash):
            RNS.Transport.request_path(dest_hash)
            deadline = time.time() + min(timeout, 12)
            while time.time() < deadline and not RNS.Transport.has_path(dest_hash):
                time.sleep(0.2)

        identity = RNS.Identity.recall(dest_hash)
        if identity is None:
            text = demo_page(path, dest_hash_hex)
            return {
                "ok": True,
                "hash": dest_hash_hex,
                "path": path,
                "text": text,
                "html": micron_to_html(text),
                "source": "demo",
                "note": "Brak tożsamości node'a w pamięci RNS",
            }

        destination = RNS.Destination(
            identity,
            RNS.Destination.OUT,
            RNS.Destination.SINGLE,
            "nomadnetwork",
            "node",
        )

        def established(link):
            def got_response(request_receipt):
                body = request_receipt.response
                if body is None:
                    finish({"ok": False, "error": "Pusta odpowiedź"})
                    return
                if isinstance(body, bytes):
                    try:
                        text = body.decode("utf-8")
                    except Exception:
                        text = body.decode("utf-8", errors="replace")
                else:
                    text = str(body)
                finish(
                    {
                        "ok": True,
                        "hash": dest_hash_hex,
                        "path": path,
                        "text": text,
                        "html": micron_to_html(text),
                        "source": "rns",
                    }
                )

            def failed(_receipt=None):
                finish({"ok": False, "error": "Node nie oddał strony"})

            link.request(
                path,
                data=None,
                response_callback=got_response,
                failed_callback=failed,
                timeout=timeout,
            )

        def closed(link):
            if not done.is_set():
                finish({"ok": False, "error": "Połączenie zamknięte"})

        link = RNS.Link(destination, established_callback=established, closed_callback=closed)
        if not done.wait(timeout + 2):
            try:
                link.teardown()
            except Exception:
                pass
            return {"ok": False, "error": "Timeout przy pobieraniu strony"}
        return dict(result)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def decode_app_data(app_data):
    if not app_data:
        return None
    if isinstance(app_data, str):
        return app_data.strip() or None
    try:
        text = app_data.decode("utf-8").strip()
        if text:
            return text
    except Exception:
        pass
    return None


def classify_dest(destination_hash, announced_identity):
    if announced_identity is None:
        return "announce"
    try:
        import RNS
        for aspect, label in (
            ("nomadnetwork.node", "nomadnetwork.node"),
            ("lxmf.delivery", "lxmf.delivery"),
        ):
            expected = RNS.Destination.hash_from_name_and_identity(aspect, announced_identity)
            if expected == destination_hash:
                return label
    except Exception:
        pass
    return "announce"


def ingest_announce(destination_hash, announced_identity, app_data):
    name = decode_app_data(app_data)
    app = classify_dest(destination_hash, announced_identity)
    h = hexhash(destination_hash)
    with nodes_lock:
        is_new = h not in nodes
    upsert_node({"hash": h, "name": name, "app": app, "demo": False})
    if is_new:
        print(f"[announce] {app} {h[:16]}… {name or ''}")


def harvest_known_paths():
    try:
        import RNS
    except Exception:
        return
    table = getattr(RNS.Transport, "destination_table", None) or {}
    for dest_hash in list(table.keys()):
        try:
            ident = RNS.Identity.recall(dest_hash)
            app_data = RNS.Identity.recall_app_data(dest_hash)
            ingest_announce(dest_hash, ident, app_data)
        except Exception:
            continue


def path_harvester():
    while True:
        time.sleep(5)
        harvest_known_paths()


def start_rns() -> None:
    global rns_ready
    try:
        import RNS
    except Exception as exc:
        print(f"[gateway] RNS niedostępny ({exc}), tryb demo")
        return

    sanitize_rns_config()
    try:
        reticulum = RNS.Reticulum()
    except OSError as exc:
        print(f"[gateway] port zajęty ({exc}), wyłączam Extra AutoInterface")
        sanitize_rns_config(disable_all_auto=True)
        try:
            reticulum = RNS.Reticulum()
        except Exception as exc2:
            print(f"[gateway] Nie udało się uruchomić RNS ({exc2}), tryb demo")
            return
    except Exception as exc:
        print(f"[gateway] Nie udało się uruchomić RNS ({exc}), tryb demo")
        return

    class Handler:
        aspect_filter = None
        receive_path_responses = True

        def received_announce(self, destination_hash, announced_identity, app_data, *args, **kwargs):
            ingest_announce(destination_hash, announced_identity, app_data)

    try:
        RNS.Transport.register_announce_handler(Handler())
        rns_ready = True
        ifaces = getattr(RNS.Transport, "interfaces", None) or []
        if ifaces:
            for iface in ifaces:
                print(f"[gateway] interfejs: {iface}")
        else:
            print("[gateway] brak interfejsów RNS — sprawdź ~/.reticulum/config")
        print("[gateway] RNS włączony, czekam na announce")
        harvest_known_paths()
        threading.Thread(target=path_harvester, daemon=True).start()
        start_lxmf()
        start_node_announce()
    except Exception as exc:
        print(f"[gateway] Handler announce nie wszedł ({exc})")
        reticulum = reticulum  # keep instance alive


def start_lxmf():
    global lxmf_router, lxmf_source, lxmf_address, lxmf_ok
    try:
        import LXMF
        import RNS
    except Exception as exc:
        print(f"[gateway] Brak LXMF ({exc}). pip install lxmf")
        return
    try:
        os.makedirs(LXMF_DIR, exist_ok=True)
        ident_path = os.path.join(LXMF_DIR, "identity")
        if os.path.exists(ident_path):
            identity = RNS.Identity.from_file(ident_path)
        else:
            identity = RNS.Identity()
            identity.to_file(ident_path)
        lxmf_router = LXMF.LXMRouter(storagepath=LXMF_DIR)
        lxmf_source = lxmf_router.register_delivery_identity(identity, display_name=device_name)
        lxmf_address = hexhash(lxmf_source.hash)
        lxmf_router.register_delivery_callback(_lxmf_in)
        try:
            lxmf_router.announce(lxmf_source.hash)
        except Exception:
            try:
                lxmf_source.announce()
            except Exception:
                pass
        lxmf_ok = True
        print(f"[gateway] LXMF {lxmf_address}")
        threading.Thread(target=lxmf_announce_loop, daemon=True).start()
    except Exception as exc:
        print(f"[gateway] LXMF nie wstaje ({exc})")


def host_name():
    return (socket.gethostname() or device_name or "node").strip() or "node"


def announce_on_all(dest, app_data):
    import RNS
    ifaces = list(getattr(RNS.Transport, "interfaces", None) or [])
    sent = 0
    if ifaces:
        for iface in ifaces:
            try:
                dest.announce(app_data=app_data, attached_interface=iface)
                sent += 1
            except TypeError:
                dest.announce(app_data=app_data)
                sent = max(sent, 1)
                break
            except Exception as exc:
                print(f"[gateway] announce na {iface}: {exc}")
    if sent == 0:
        dest.announce(app_data=app_data)
        sent = 1
    return sent


def start_node_announce():
    global node_dest, node_identity, device_name
    try:
        import RNS
    except Exception:
        return
    device_name = host_name()
    ident_path = os.path.expanduser("~/.reticulum-gateway/identity")
    os.makedirs(os.path.dirname(ident_path), exist_ok=True)
    if os.path.exists(ident_path):
        node_identity = RNS.Identity.from_file(ident_path)
    else:
        node_identity = RNS.Identity()
        node_identity.to_file(ident_path)
    node_dest = RNS.Destination(
        node_identity,
        RNS.Destination.IN,
        RNS.Destination.SINGLE,
        "nomadnetwork",
        "node",
    )
    ensure_pages()

    def page_response(path, data, request_id, link_id, remote_identity, requested_at):
        try:
            return load_local_page(path or "/page/index.mu").encode("utf-8")
        except Exception as exc:
            return f"`!blad`` {exc}".encode("utf-8")

    try:
        node_dest.register_request_handler(
            "/page",
            response_generator=page_response,
            allow=RNS.Destination.ALLOW_ALL,
        )
    except Exception as exc:
        print(f"[gateway] handler stron: {exc}")
    app = device_name.encode("utf-8")
    h = hexhash(node_dest.hash)
    upsert_node({"hash": h, "name": device_name, "app": "nomadnetwork.node", "demo": False})
    n = announce_on_all(node_dest, app)
    print(f"[gateway] node {device_name} {h[:16]}… announce x{n}")
    threading.Thread(target=node_announce_loop, daemon=True).start()


def node_announce_loop():
    while True:
        time.sleep(120)
        if node_dest is None:
            continue
        name = host_name()
        try:
            n = announce_on_all(node_dest, name.encode("utf-8"))
            upsert_node({"hash": hexhash(node_dest.hash), "name": name, "app": "nomadnetwork.node", "demo": False})
            print(f"[gateway] announce {name} x{n}")
        except Exception as exc:
            print(f"[gateway] announce {exc}")


def lxmf_announce_loop():
    while True:
        time.sleep(120)
        if not lxmf_ok or lxmf_source is None:
            continue
        try:
            import RNS
            name = host_name()
            if hasattr(lxmf_source, "display_name"):
                lxmf_source.display_name = name
            app = name.encode("utf-8")
            try:
                announce_on_all(lxmf_source, app)
            except Exception:
                lxmf_source.announce()
        except Exception as exc:
            print(f"[gateway] lxmf announce {exc}")


def _lxmf_in(message):
    try:
        src = hexhash(getattr(message, "source_hash", None) or message.source.hash)
        content = getattr(message, "content", "") or ""
        if isinstance(content, bytes):
            content = content.decode("utf-8", errors="replace")
        title = getattr(message, "title", "") or ""
        if isinstance(title, bytes):
            title = title.decode("utf-8", errors="replace")
        add_message(src, "in", content, title)
        print(f"[lxmf] od {src[:12]}…")
    except Exception as exc:
        print(f"[lxmf] odbiór {exc}")


def send_lxmf(to_hex, text, title=""):
    if not lxmf_ok:
        return {"ok": False, "error": "LXMF wyłączone. Na Pi: pip install lxmf"}
    import LXMF
    import RNS
    to_hex = str(to_hex or "").lower().replace("lxmf@", "").replace("/", "")
    try:
        dest_hash = bytes.fromhex(to_hex)
    except Exception:
        return {"ok": False, "error": "Zły adres LXMF"}
    if len(dest_hash) != 16:
        return {"ok": False, "error": "Adres LXMF musi mieć 32 znaki"}
    try:
        if not RNS.Transport.has_path(dest_hash):
            RNS.Transport.request_path(dest_hash)
            deadline = time.time() + 8
            while time.time() < deadline and not RNS.Transport.has_path(dest_hash):
                time.sleep(0.2)
        ident = RNS.Identity.recall(dest_hash)
        if ident is None:
            add_message(to_hex, "out", text, title, status="czekam")
            return {"ok": False, "error": "Nie znam jeszcze tej osoby w sieci. Spróbuj za chwilę."}
        dest = RNS.Destination(ident, RNS.Destination.OUT, RNS.Destination.SINGLE, "lxmf", "delivery")
        method = getattr(LXMF.LXMessage, "DIRECT", None)
        kwargs = {"desired_method": method} if method is not None else {}
        lxm = LXMF.LXMessage(dest, lxmf_source, text, title or None, **kwargs)
        if hasattr(lxm, "try_propagation_on_fail"):
            lxm.try_propagation_on_fail = True
        lxmf_router.handle_outbound(lxm)
        add_message(to_hex, "out", text, title, status="wysłane")
        return {"ok": True, "to": to_hex}
    except Exception as exc:
        add_message(to_hex, "out", text, title, status="błąd")
        return {"ok": False, "error": str(exc)}


NETWORK_PRESETS = [
    {
        "id": "lan",
        "section": "Siec domowa",
        "title": "Sieć w domu",
        "hint": "Samo znajduje inne Reticulum w Twojej sieci Wi‑Fi / LAN.",
        "type": "AutoInterface",
        "options": {},
        "recommended": True,
    },
    {
        "id": "auto-inet",
        "section": "Auto Internet IPv6",
        "title": "Auto po internecie",
        "hint": "Szuka innych node’ów w internecie po IPv6. Działa tylko gdy operator przepuszcza multicast.",
        "type": "AutoInterface",
        "options": {"discovery_scope": "global", "group_id": "reticulum"},
        "recommended": False,
    },
    {
        "id": "rmap",
        "section": "RMAP World",
        "title": "Sieć publiczna — RMAP",
        "hint": "Wejście po adresie IP. Włącz to na start.",
        "type": "TCPClientInterface",
        "options": {"target_host": "217.154.9.220", "target_port": "4242"},
        "recommended": True,
    },
    {
        "id": "nodns",
        "section": "Siec publiczna IP",
        "title": "Sieć publiczna — zapasowy IP",
        "hint": "Nie używa DNS. Gdy RMAP milczy, włącz to.",
        "type": "TCPClientInterface",
        "options": {"target_host": "202.61.243.41", "target_port": "4965"},
        "recommended": True,
    },
    {
        "id": "btb",
        "section": "Siec publiczna BetweenTheBorders",
        "title": "Sieć publiczna — Between the Borders",
        "hint": "Drugi publiczny hub.",
        "type": "TCPClientInterface",
        "options": {"target_host": "162.255.87.166", "target_port": "4242"},
        "recommended": False,
    },
]


BAD_AUTO_SECTIONS = ("Siec domowa", "Auto Internet IPv6")
DEAD_TCP_HOSTS = {
    "dublin.connect.reticulum.network": ("217.154.9.220", "4242"),
    "amsterdam.connect.reticulum.network": ("217.154.9.220", "4242"),
    "rmap.world": ("217.154.9.220", "4242"),
    "reticulum.betweentheborders.com": ("162.255.87.166", "4242"),
}


def sanitize_rns_config(disable_all_auto=False):
    path = rns_config_path()
    if not os.path.exists(path):
        return
    try:
        cfg, path = load_rns_cfg()
        interfaces = cfg.get("interfaces") if "interfaces" in cfg else None
        if isinstance(interfaces, dict):
            for name in list(interfaces.keys()):
                if name in BAD_AUTO_SECTIONS:
                    try:
                        del interfaces[name]
                    except Exception:
                        pass
                    continue
                block = interfaces.get(name)
                if isinstance(block, dict):
                    host = str(block.get("target_host") or "").strip()
                    if host in DEAD_TCP_HOSTS:
                        ip, port = DEAD_TCP_HOSTS[host]
                        block["target_host"] = ip
                        block["target_port"] = port
                if disable_all_auto and isinstance(block, dict) and block.get("type") == "AutoInterface":
                    block["enabled"] = "no"
                    block["interface_enabled"] = "no"
            autos = [
                name for name, block in list(interfaces.items())
                if isinstance(block, dict) and block.get("type") == "AutoInterface" and iface_enabled(block)
            ]
            if len(autos) > 1:
                keep = "Default Interface" if "Default Interface" in autos else autos[0]
                for name in autos:
                    if name != keep:
                        interfaces[name]["enabled"] = "no"
                        interfaces[name]["interface_enabled"] = "no"
            if hasattr(cfg, "write"):
                cfg.write()
            print("[gateway] poprawiłem ~/.reticulum/config (jeden AutoInterface)")
            return
    except Exception as exc:
        print(f"[gateway] ConfigObj nie ogarnął configu ({exc}), czyszczę tekstowo")
    _sanitize_config_text(path, disable_all_auto)


def _sanitize_config_text(path, disable_all_auto=False):
    try:
        raw = open(path, encoding="utf-8").read()
    except Exception:
        return
    lines = raw.splitlines(True)
    out = []
    section = None
    skip_section = False
    auto_kept = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[[") and stripped.endswith("]]"):
            section = stripped[2:-2].strip()
            skip_section = section in BAD_AUTO_SECTIONS
            if skip_section:
                continue
            out.append(line)
            continue
        if skip_section:
            if stripped.startswith("[") and not stripped.startswith("[["):
                skip_section = False
                section = stripped
                out.append(line)
            continue
        out.append(line)
    text = "".join(out)
    if disable_all_auto:
        text = text.replace("type = AutoInterface", "type = AutoInterface\n# disabled-by-gateway")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    print("[gateway] wyczyściłem zdublowany AutoInterface w configu")


def rns_config_path():
    for path in (
        os.path.expanduser("~/.reticulum/config"),
        os.path.expanduser("~/.config/reticulum/config"),
        "/etc/reticulum/config",
    ):
        if os.path.exists(path):
            return path
    return os.path.expanduser("~/.reticulum/config")


def load_rns_cfg():
    path = rns_config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        from RNS.vendor.configobj import ConfigObj
        return ConfigObj(path, encoding="utf-8"), path
    except Exception:
        from configparser import ConfigParser
        cfg = ConfigParser(interpolation=None)
        cfg.optionxform = str
        if os.path.exists(path):
            cfg.read(path)
        return cfg, path


def iface_enabled(block):
    if not isinstance(block, dict):
        return False
    val = str(block.get("enabled") or block.get("interface_enabled") or "").strip().lower()
    return val in ("yes", "true", "1", "on")


def list_network_state():
    cfg, path = load_rns_cfg()
    interfaces = cfg.get("interfaces") if hasattr(cfg, "get") else None
    if interfaces is None and hasattr(cfg, "keys"):
        interfaces = cfg["interfaces"] if "interfaces" in cfg else {}
    if not isinstance(interfaces, dict):
        interfaces = {}

    presets_out = []
    for preset in NETWORK_PRESETS:
        block = interfaces.get(preset["section"], {}) if hasattr(interfaces, "get") else {}
        if not isinstance(block, dict):
            block = {}
        on = iface_enabled(block)
        if not on and preset["type"] == "TCPClientInterface":
            host = preset["options"].get("target_host")
            for name, other in list(interfaces.items()):
                if not isinstance(other, dict):
                    continue
                if str(other.get("target_host", "")).strip() == host and iface_enabled(other):
                    on = True
                    break
        if preset["id"] in ("lan", "auto-inet"):
            auto = None
            for name, other in list(interfaces.items()):
                if isinstance(other, dict) and other.get("type") == "AutoInterface" and iface_enabled(other):
                    auto = other
                    break
            if auto is not None:
                scope = str(auto.get("discovery_scope") or "").lower()
                if preset["id"] == "auto-inet":
                    on = scope == "global"
                else:
                    on = True
        presets_out.append({**preset, "enabled": on})

    extras = []
    known = {p["section"] for p in NETWORK_PRESETS} | {"Default Interface"}
    for name, block in list(interfaces.items()):
        if name in known or not isinstance(block, dict):
            continue
        extras.append({
            "section": name,
            "type": block.get("type"),
            "enabled": iface_enabled(block),
            "target_host": block.get("target_host"),
            "target_port": block.get("target_port"),
        })

    live = []
    try:
        import RNS
        for iface in getattr(RNS.Transport, "interfaces", []) or []:
            live.append(str(iface))
    except Exception:
        pass

    return {
        "ok": True,
        "config": path,
        "presets": presets_out,
        "extras": extras,
        "live": live,
        "nodes": len(list_nodes()),
    }


def drop_iface(interfaces, name):
    if name in interfaces:
        try:
            del interfaces[name]
        except Exception:
            if isinstance(interfaces.get(name), dict):
                interfaces[name]["enabled"] = "no"
                interfaces[name]["interface_enabled"] = "no"


def apply_networks(enabled_ids, custom):
    cfg, path = load_rns_cfg()
    if "reticulum" not in cfg:
        cfg["reticulum"] = {}
    cfg["reticulum"].setdefault("share_instance", "yes")
    if "interfaces" not in cfg:
        cfg["interfaces"] = {}
    interfaces = cfg["interfaces"]

    wanted = set(enabled_ids or [])

    # Jeden AutoInterface — drugi wywala "Address already in use".
    drop_iface(interfaces, "Siec domowa")
    drop_iface(interfaces, "Auto Internet IPv6")

    want_auto = "lan" in wanted or "auto-inet" in wanted
    auto_name = "Default Interface" if "Default Interface" in interfaces else "Default Interface"
    auto = dict(interfaces.get(auto_name) or {}) if isinstance(interfaces.get(auto_name), dict) else {}
    auto["type"] = "AutoInterface"
    if want_auto:
        auto["enabled"] = "yes"
        auto["interface_enabled"] = "yes"
        if "auto-inet" in wanted:
            auto["discovery_scope"] = "global"
            auto["group_id"] = "reticulum"
        else:
            auto.pop("discovery_scope", None)
    else:
        auto["enabled"] = "no"
        auto["interface_enabled"] = "no"
        auto.pop("discovery_scope", None)
    interfaces[auto_name] = auto

    for preset in NETWORK_PRESETS:
        if preset["type"] != "TCPClientInterface":
            continue
        section = preset["section"]
        if preset["id"] in wanted:
            block = dict(interfaces.get(section) or {}) if isinstance(interfaces.get(section), dict) else {}
            block["type"] = "TCPClientInterface"
            block["enabled"] = "yes"
            block["interface_enabled"] = "yes"
            block.update(preset["options"])
            interfaces[section] = block
        elif section in interfaces and isinstance(interfaces[section], dict):
            interfaces[section]["enabled"] = "no"
            interfaces[section]["interface_enabled"] = "no"

    for item in custom or []:
        host = str(item.get("host") or "").strip()
        port = str(item.get("port") or "4242").strip()
        if not host:
            continue
        name = str(item.get("name") or f"Wlasny {host}").strip()
        interfaces[name] = {
            "type": "TCPClientInterface",
            "enabled": "yes",
            "interface_enabled": "yes",
            "target_host": host,
            "target_port": port,
        }

    if hasattr(cfg, "write"):
        cfg.write()
    else:
        with open(path, "w", encoding="utf-8") as fh:
            cfg.write(fh)
    print(f"[gateway] zapisano sieci do {path}")
    return path


def restart_soon():
    def _go():
        time.sleep(1.2)
        print("[gateway] restart po zmianie sieci")
        os.execv(sys.executable, [sys.executable] + sys.argv)
    threading.Thread(target=_go, daemon=True).start()


def start_mdns(port: int) -> None:
    try:
        from zeroconf import ServiceInfo, Zeroconf
    except Exception:
        return
    try:
        ip = socket.gethostbyname(socket.gethostname())
        info = ServiceInfo(
            "_rns-gw._tcp.local.",
            f"{device_name}._rns-gw._tcp.local.",
            addresses=[socket.inet_aton(ip)] if ip.count(".") == 3 else None,
            port=port,
            properties={"path": "/api/hello", "name": device_name.encode()},
            server=f"{device_name}.local.",
        )
        zc = Zeroconf()
        zc.register_service(info)
        print(f"[gateway] mDNS: {device_name}.local")
    except Exception as exc:
        print(f"[gateway] mDNS pominięty ({exc})")


def git_version():
    try:
        import subprocess
        count = subprocess.check_output(
            ["git", "-C", REPO_ROOT, "rev-list", "--count", "HEAD"],
            text=True, stderr=subprocess.DEVNULL,
        ).strip()
        sha = subprocess.check_output(
            ["git", "-C", REPO_ROOT, "rev-parse", "--short=8", "HEAD"],
            text=True, stderr=subprocess.DEVNULL,
        ).strip()
        return {"ok": True, "count": int(count), "hash": sha, "label": f"{count} {sha}"}
    except Exception:
        return {"ok": False, "count": 0, "hash": "", "label": "—"}


def ensure_certs():
    folder = os.path.expanduser("~/.reticulum-gateway")
    os.makedirs(folder, exist_ok=True)
    cert = os.path.join(folder, "cert.pem")
    key = os.path.join(folder, "key.pem")
    if os.path.exists(cert) and os.path.exists(key):
        return cert, key
    import subprocess
    subprocess.check_call([
        "openssl", "req", "-x509", "-nodes", "-newkey", "rsa:2048",
        "-keyout", key, "-out", cert, "-days", "3650",
        "-subj", "/CN=reticulum-gateway",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"[gateway] nowy certyfikat: {cert}")
    return cert, key


class DualHTTPServer(ThreadingHTTPServer):
    pass


def serve_web(path):
    if path in ("/", "/index.html", "/home"):
        path = "/index.html"
    name = os.path.basename(path)
    if name not in ("index.html", "panel.css", "panel.js"):
        return None
    full = os.path.join(WEB_DIR, name)
    if not os.path.isfile(full):
        return None
    with open(full, "rb") as fh:
        body = fh.read()
    types = {
        ".html": "text/html; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".js": "application/javascript; charset=utf-8",
    }
    return 200, types.get(os.path.splitext(name)[1], "application/octet-stream"), body


def json_bytes(data, code=200):
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    return code, "application/json; charset=utf-8", body


class GatewayHandler(BaseHTTPRequestHandler):
    server_version = "ReticulumGateway/1.0"

    def log_message(self, fmt, *args):
        print("[http]", fmt % args)

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-store")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            self._send(*json_bytes({"ok": False, "error": "Zły JSON"}, 400))
            return
        if parsed.path == "/api/lxmf":
            to_hex = body.get("to") or body.get("peer") or ""
            text = body.get("text") or ""
            title = body.get("title") or ""
            if not text.strip():
                self._send(*json_bytes({"ok": False, "error": "Pusta wiadomość"}, 400))
                return
            self._send(*json_bytes(send_lxmf(to_hex, text.strip(), title)))
            return
        if parsed.path == "/api/data":
            store = load_store()
            if body.get("alias"):
                a = body["alias"]
                name = str(a.get("name") or "").strip().lower()
                if name:
                    store["aliases"][name] = {
                        "hash": a.get("hash"),
                        "path": a.get("path") or "/page/index.mu",
                        "title": a.get("title") or name,
                    }
            if body.get("history"):
                h = body["history"]
                url = h.get("url")
                store["history"] = [x for x in store["history"] if x.get("url") != url]
                store["history"].insert(0, {
                    "url": url,
                    "title": h.get("title") or url,
                    "hash": h.get("hash"),
                    "path": h.get("path"),
                })
                store["history"] = store["history"][:40]
            save_store(store)
            self._send(*json_bytes({"ok": True}))
            return
        if parsed.path == "/api/networks":
            enabled = body.get("enabled") or []
            custom = body.get("custom") or []
            try:
                path = apply_networks(enabled, custom)
            except Exception as exc:
                self._send(*json_bytes({"ok": False, "error": str(exc)}, 500))
                return
            restart_soon()
            self._send(*json_bytes({
                "ok": True,
                "restarting": True,
                "config": path,
                "note": "Bramka zaraz się zrestartuje. Odśwież panel za kilka sekund.",
            }))
            return
        self._send(*json_bytes({"ok": False, "error": "Nie znaleziono"}, 404))

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path.startswith("/lxmf@") or path.startswith("/lxmf/"):
            peer = path.split("@")[-1].split("/")[-1]
            self.send_response(302)
            self.send_header("Location", f"/#/msg/{peer}")
            self._cors()
            self.end_headers()
            return

        if path == "/api/lxmf":
            peer = (query.get("peer") or [""])[0].strip().lower()
            store = load_msgs()
            if peer:
                box = store["peers"].get(peer, {"messages": []})
                self._send(*json_bytes({
                    "ok": True,
                    "me": lxmf_address,
                    "lxmf": lxmf_ok,
                    "peer": peer,
                    "messages": box.get("messages") or [],
                }))
                return
            self._send(*json_bytes({
                "ok": True,
                "me": lxmf_address,
                "lxmf": lxmf_ok,
                "conversations": list_conversations(),
            }))
            return

        if path == "/api/data":
            self._send(*json_bytes({"ok": True, **load_store()}))
            return

        if path == "/api/version":
            self._send(*json_bytes(git_version()))
            return

        if path == "/api/hello":
            self._send(*json_bytes({
                "ok": True,
                "name": device_name,
                "app": APP_NAME,
                "port": self.server.server_address[1],
                "rns": rns_ready,
                "demo": demo_mode or not rns_ready,
                "nodes": len(list_nodes()),
            }))
            return

        if path == "/api/networks":
            self._send(*json_bytes(list_network_state()))
            return

        if path == "/api/nodes":
            self._send(*json_bytes({"ok": True, "nodes": list_nodes()}))
            return

        if path == "/api/page":
            dest = (query.get("hash") or [""])[0].strip().lower()
            page = unquote((query.get("path") or ["/page/index.mu"])[0])
            if not dest:
                self._send(*json_bytes({"ok": False, "error": "Brak hash"}, 400))
                return
            self._send(*json_bytes(fetch_nomad_page(dest, page)))
            return

        if path == "/api/stream":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self._cors()
            self.end_headers()
            queue = []
            with sse_lock:
                sse_clients.append(queue)
            try:
                self.wfile.write(b"data: " + json.dumps({"type": "hello", "nodes": list_nodes()}).encode() + b"\n\n")
                self.wfile.flush()
                while True:
                    if queue:
                        item = queue.pop(0)
                        self.wfile.write(b"data: " + item.encode("utf-8") + b"\n\n")
                        self.wfile.flush()
                    else:
                        time.sleep(0.3)
            except Exception:
                pass
            finally:
                with sse_lock:
                    if queue in sse_clients:
                        sse_clients.remove(queue)
            return

        served = serve_web(path)
        if served:
            self._send(*served)
            return

        self._send(*json_bytes({"ok": False, "error": "Nie znaleziono"}, 404))

    def _send(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)


def main():
    global demo_mode, device_name
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--demo", action="store_true", help="Nie łącz z RNS, pokaż przykładowe node'y")
    parser.add_argument("--name", default=os.environ.get("RNS_GW_NAME", device_name))
    args = parser.parse_args()
    device_name = args.name
    demo_mode = args.demo

    if demo_mode:
        load_demo_nodes()
        print("[gateway] tryb demo")
    else:
        start_rns()
        if not rns_ready:
            load_demo_nodes()
            print("[gateway] działam z node'ami poglądowymi")

    start_mdns(args.port)
    http = ThreadingHTTPServer(("0.0.0.0", args.port), GatewayHandler)
    print(f"[gateway] http://0.0.0.0:{args.port}")
    try:
        cert, key = ensure_certs()
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert, key)
        https = ThreadingHTTPServer(("0.0.0.0", HTTPS_PORT), GatewayHandler)
        https.socket = ctx.wrap_socket(https.socket, server_side=True)
        threading.Thread(target=https.serve_forever, daemon=True).start()
        print(f"[gateway] https://0.0.0.0:{HTTPS_PORT}  (self-signed)")
    except Exception as exc:
        print(f"[gateway] TLS pominięty ({exc})")
    try:
        http.serve_forever()
    except KeyboardInterrupt:
        print("\n[gateway] stop")
        http.server_close()


if __name__ == "__main__":
    main()
