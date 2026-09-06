const $app = document.getElementById("app");
const $addr = document.getElementById("addr");

function route() {
  return decodeURIComponent((location.hash || "#/home").replace(/^#\/?/, "")) || "home";
}
function go(p) {
  location.hash = "#/" + String(p).replace(/^#\/?/, "").replace(/^reticulum:\/\//, "");
}
async function api(path, init) {
  const res = await fetch(path, { cache: "no-store", ...init });
  return res.json();
}
function esc(s) {
  return String(s || "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

async function render() {
  const path = route();
  $addr.value = path;
  document.body.classList.remove("chat-on");
  if (path === "home" || path === "") return home();
  if (path === "networks") return networks();
  if (path === "nodes") return nodes();
  if (path === "msg" || path === "messages") return inbox();
  if (path.startsWith("msg/")) return thread(path.slice(4).split("/")[0]);
  if (path.startsWith("lxmf@")) return thread(path.slice(5));
  if (path.startsWith("node/")) return page(path.slice(5));
  return alias(path);
}

async function home() {
  const data = await api("/api/data").catch(() => ({ aliases: {}, history: [] }));
  const aliases = data.aliases || {};
  const history = data.history || [];
  $app.innerHTML = `
    <h1>Panel</h1>
    <p class="muted">This device is the gateway. Nothing else needs installing.</p>
    <div class="row">
      <button type="button" id="toNodes">Announced nodes</button>
      <button type="button" id="toMsg">Messages</button>
      <button type="button" id="toNets">Networks</button>
    </div>
    <h2>Aliases</h2>
    <div id="al">${Object.keys(aliases).length ? Object.entries(aliases).map(([n, a]) => `
      <div class="card spread"><div><h3>${esc(n)}</h3><div class="hash">${esc(a.hash)}</div></div>
      <button class="small" data-go="${esc(n)}">Open</button></div>`).join("") : `<p class="muted">None yet. Set an alias on a node page.</p>`}</div>
    <h2>History</h2>
    <div>${history.length ? history.map((h) => `
      <div class="card spread"><div>${esc(h.title || h.url)}<div class="hash">${esc(h.url)}</div></div>
      <button class="ghost small" data-go="${esc(h.url)}">Open</button></div>`).join("") : `<p class="muted">Empty.</p>`}</div>`;
  $app.querySelector("#toNodes").onclick = () => go("nodes");
  $app.querySelector("#toMsg").onclick = () => go("msg");
  $app.querySelector("#toNets").onclick = () => go("networks");
  $app.querySelectorAll("[data-go]").forEach((b) => { b.onclick = () => go(b.dataset.go); });
}

async function networks() {
  const info = await api("/api/networks").catch(() => null);
  if (!info || !info.presets) {
    $app.innerHTML = `<p class="warn">Could not load networks.</p>`;
    return;
  }
  $app.innerHTML = `
    <h1>Networks</h1>
    <p class="muted">Enable the home mesh and/or a public hub. The old Dublin endpoint is gone.</p>
    <div id="presets">${info.presets.map((p) => `
      <label class="card spread"><div><h3>${esc(p.title)}${p.recommended ? " · recommended" : ""}</h3>
      <p class="muted">${esc(p.hint)}</p></div>
      <input type="checkbox" data-id="${esc(p.id)}" ${p.enabled ? "checked" : ""}></label>`).join("")}</div>
    <h2>Custom server</h2>
    <div class="row">
      <input class="field" id="cHost" placeholder="host">
      <input class="field" id="cPort" placeholder="4242" style="max-width:90px">
    </div>
    <div class="row" style="margin-top:12px">
      <button type="button" id="save">Save and connect</button>
      <span class="muted" id="info"></span>
    </div>`;
  $app.querySelector("#save").onclick = async () => {
    const enabled = [...$app.querySelectorAll("input[type=checkbox]:checked")].map((el) => el.dataset.id);
    const host = $app.querySelector("#cHost").value.trim();
    const custom = host ? [{ host, port: $app.querySelector("#cPort").value.trim() || "4242" }] : [];
    $app.querySelector("#info").textContent = "Saving…";
    const out = await api("/api/networks", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ enabled, custom }),
    });
    $app.querySelector("#info").textContent = out.ok ? "Gateway restarting. Refresh in 5 s." : (out.error || "Error");
    if (out.ok) setTimeout(() => go("nodes"), 5000);
  };
}

async function nodes() {
  $app.innerHTML = `<h1>Nodes</h1><p class="muted" id="st">Loading…</p><input class="field search" id="f" placeholder="Filter"><div id="list"></div>`;
  const data = await api("/api/nodes").catch(() => ({ nodes: [] }));
  const all = data.nodes || [];
  const paint = () => {
    const q = $app.querySelector("#f").value.trim().toLowerCase();
    const show = all.filter((n) => !q || (n.name || "").toLowerCase().includes(q) || (n.hash || "").includes(q));
    $app.querySelector("#st").innerHTML = all.length
      ? `${all.length} announced`
      : `Nothing here yet. Open <a href="#/networks">Networks</a> and enable a hub.`;
    $app.querySelector("#list").innerHTML = show.map((n) => `
      <div class="card spread"><div><h3>${esc(n.name)}</h3><div class="hash">${esc(n.hash)}</div>
      <div class="muted">${esc(n.app || "")}</div></div>
      <button data-h="${esc(n.hash)}">Visit</button></div>`).join("");
    $app.querySelectorAll("button[data-h]").forEach((b) => {
      b.onclick = () => go("node/" + b.dataset.h + "/page/index.mu");
    });
  };
  $app.querySelector("#f").oninput = paint;
  paint();
}

async function page(rest) {
  const m = rest.match(/^([a-fA-F0-9]{32})(\/.*)?$/);
  if (!m) { $app.innerHTML = `<p class="warn">Invalid address.</p>`; return; }
  const hash = m[1].toLowerCase();
  const pth = m[2] || "/page/index.mu";
  $app.innerHTML = `<p class="muted">Loading…</p>`;
  const data = await api("/api/page?hash=" + encodeURIComponent(hash) + "&path=" + encodeURIComponent(pth));
  await api("/api/data", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ history: { url: "node/" + hash + pth, title: hash.slice(0, 8) + pth, hash, path: pth } }),
  });
  if (!data.ok && !data.html && !data.text) {
    $app.innerHTML = `<p class="warn">${esc(data.error || "Error")}</p>`;
    return;
  }
  $app.innerHTML = `
    <div class="spread"><div><h1>${esc(hash.slice(0, 8))}</h1><div class="hash">${esc(hash + pth)}</div></div>
    <button class="ghost small" id="alias">Save alias</button></div>
    <div class="card page" id="body">${data.html || "<pre>" + esc(data.text || "") + "</pre>"}</div>`;
  $app.querySelector("#alias").onclick = async () => {
    const name = prompt("Short name, e.g. forum");
    if (!name) return;
    const key = name.trim().toLowerCase().replace(/\s+/g, "-");
    await api("/api/data", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ alias: { name: key, hash, path: pth, title: name.trim() } }),
    });
    alert("reticulum://" + key);
  };
  $app.querySelector("#body").onclick = (e) => {
    const a = e.target.closest("a");
    if (!a) return;
    e.preventDefault();
    openMesh(a.getAttribute("href") || "", hash);
  };
}

function lxmfPeer(s) {
  const m = String(s || "").match(/lxmf@([a-fA-F0-9]{32})/i) || String(s || "").match(/^([a-fA-F0-9]{32})$/);
  return m ? m[1].toLowerCase() : "";
}

function openMesh(href, currentHash) {
  const h = String(href || "").trim();
  if (h.startsWith("#/")) {
    go(h.slice(2));
    return;
  }
  const fromMsg = h.match(/(?:msg\/|lxmf@)([a-fA-F0-9]{32})/i);
  const peer = lxmfPeer(h) || (fromMsg && fromMsg[1].toLowerCase());
  if (peer && peer.length === 32) {
    go("msg/" + peer);
    return;
  }
  let hash = currentHash;
  let path = "/page/index.mu";
  const raw = h.replace(/^nomadnetwork:\/\//, "").replace(/^https?:\/\/[^/]+\//, "");
  if (raw.startsWith(":/")) path = raw.slice(1);
  else if (raw.includes(":")) {
    const i = raw.indexOf(":");
    hash = raw.slice(0, i).replace(/[<>]/g, "");
    path = raw.slice(i + 1) || "/page/index.mu";
  } else if (/^[a-fA-F0-9]{32}$/.test(raw)) hash = raw;
  else if (raw.startsWith("/")) path = raw;
  if (!path.startsWith("/")) path = "/" + path;
  go("node/" + hash + path);
}

async function alias(path) {
  const data = await api("/api/data").catch(() => ({ aliases: {} }));
  const key = path.split("/")[0];
  const a = (data.aliases || {})[key];
  if (!a) {
    $app.innerHTML = `<div class="card"><h1>Not found</h1><p class="muted">${esc(path)}</p></div>`;
    return;
  }
  const rest = path.includes("/") ? path.slice(path.indexOf("/")) : a.path || "/page/index.mu";
  go("node/" + a.hash + (rest.startsWith("/") ? rest : "/" + rest));
}

document.getElementById("goHome").onclick = () => go("home");
document.getElementById("goMsg").onclick = () => go("msg");
document.getElementById("goNets").onclick = () => go("networks");

async function inbox() {
  const data = await api("/api/lxmf").catch(() => ({ conversations: [] }));
  $app.innerHTML = `
    <h1>Messages</h1>
    <p class="muted">${data.lxmf ? "Your LXMF address: " + esc(data.me || "") : "LXMF is off. On the Pi: pip install lxmf and restart."}</p>
    <div class="row">
      <input class="field" id="newTo" placeholder="lxmf@… or hash" style="max-width:360px">
      <button type="button" id="openTo">Open</button>
    </div>
    <div id="list">${(data.conversations || []).length ? (data.conversations || []).map((c) => `
      <div class="card spread"><div><h3>${esc(c.name)}</h3><div class="hash">${esc(c.peer)}</div>
      <div class="muted">${esc(c.last)}</div></div>
      <button class="small" data-p="${esc(c.peer)}">Open</button></div>`).join("") : `<p class="muted">Empty. Use Contact me on a node page or paste an address.</p>`}</div>`;
  $app.querySelector("#openTo").onclick = () => {
    const p = lxmfPeer($app.querySelector("#newTo").value.trim()) || $app.querySelector("#newTo").value.replace(/lxmf@/gi, "").trim();
    if (p) go("msg/" + p);
  };
  $app.querySelectorAll("button[data-p]").forEach((b) => { b.onclick = () => go("msg/" + b.dataset.p); });
}

function bubbleHtml(m) {
  const t = m.ts ? new Date(m.ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "";
  return `<div class="bubble ${m.dir === "out" ? "out" : "in"}">
    ${m.title ? `<div class="muted">${esc(m.title)}</div>` : ""}
    <div>${esc(m.text)}</div>
    <div class="meta">${esc(t)}${m.status && m.status !== "ok" && m.status !== "sent" ? " · " + esc(m.status) : ""}</div>
  </div>`;
}

async function thread(peer) {
  peer = String(peer || "").toLowerCase().replace(/lxmf@/g, "").replace(/[^a-f0-9]/g, "");
  if (peer.length !== 32) {
    $app.innerHTML = `<p class="warn">Invalid LXMF address.</p>`;
    return;
  }
  document.body.classList.add("chat-on");
  $app.innerHTML = `
    <div class="chat-app">
      <div class="chat-head">
        <button class="ghost small" id="back" type="button">←</button>
        <div>
          <h1>${esc(peer.slice(0, 8))}</h1>
          <div class="hash">${esc(peer)}</div>
        </div>
      </div>
      <div class="chat" id="chat"><p class="muted">Opening conversation…</p></div>
      <form class="composer" id="form">
        <input class="field" id="box" autocomplete="off" placeholder="Write a message">
        <button type="submit">Send</button>
      </form>
      <p class="muted" id="st"></p>
    </div>`;
  $app.querySelector("#back").onclick = () => go("msg");
  const box = $app.querySelector("#box");
  box.focus();

  const paint = (messages) => {
    const el = $app.querySelector("#chat");
    if (!messages.length) {
      el.innerHTML = `<p class="muted">Type something — it is sent to this LXMF address immediately.</p>`;
    } else {
      el.innerHTML = messages.map(bubbleHtml).join("");
      el.scrollTop = el.scrollHeight;
    }
  };

  let data = { messages: [] };
  try {
    data = await api("/api/lxmf?peer=" + encodeURIComponent(peer));
  } catch {}
  paint(data.messages || []);

  $app.querySelector("#form").onsubmit = async (e) => {
    e.preventDefault();
    const text = box.value.trim();
    if (!text) return;
    box.value = "";
    const pending = { dir: "out", text, title: "", ts: Date.now() / 1000, status: "…" };
    const cur = data.messages || [];
    cur.push(pending);
    data.messages = cur;
    paint(cur);
    $app.querySelector("#st").textContent = "";
    const out = await api("/api/lxmf", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ to: peer, text }),
    }).catch(() => ({ ok: false, error: "No connection to the gateway" }));
    if (!out.ok) $app.querySelector("#st").textContent = out.error || "Send failed";
    const fresh = await api("/api/lxmf?peer=" + encodeURIComponent(peer)).catch(() => data);
    data = fresh;
    paint(fresh.messages || cur);
    box.focus();
  };
}
document.getElementById("addrForm").onsubmit = (e) => { e.preventDefault(); go($addr.value.trim() || "home"); };
window.addEventListener("hashchange", render);
render();
(async function stamp() {
  const el = document.getElementById("ver");
  if (!el) return;
  try {
    const [v, h] = await Promise.all([
      fetch("/api/version", { cache: "no-store" }).then((r) => r.json()),
      fetch("/api/hello", { cache: "no-store" }).then((r) => r.json()),
    ]);
    const name = h.name || "";
    const ver = v.label || "";
    el.textContent = [name, ver].filter(Boolean).join(" · ") || "—";
  } catch (e) {
    el.textContent = "—";
  }
})();
