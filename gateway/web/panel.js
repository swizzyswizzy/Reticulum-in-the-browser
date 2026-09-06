
function route() {
  return decodeURIComponent((location.hash || "#/home").replace(/^#\/?/, "")) || "home";
}
function viewUrl(path) {
  path = path || route();
  if (path === "home" || path === "") return "/ui/home";
  if (path === "networks") return "/ui/networks";
  if (path === "nodes") return "/ui/nodes";
  if (path === "msg" || path === "messages") return "/ui/inbox";
  if (path.startsWith("msg/")) return "/ui/thread?peer=" + encodeURIComponent(path.slice(4).split("/")[0]);
  if (path.startsWith("lxmf@")) return "/ui/thread?peer=" + encodeURIComponent(path.slice(5));
  if (path.startsWith("node/")) {
    const rest = path.slice(5);
    const m = rest.match(/^([a-fA-F0-9]{32})(\/.*)?$/);
    if (!m) return "/ui/home";
    let url = "/ui/page?hash=" + m[1].toLowerCase();
    if (m[2]) url += "&path=" + encodeURIComponent(m[2]);
    return url;
  }
  return "/ui/home";
}
function load() {
  const path = route();
  const addr = document.getElementById("addr");
  if (addr && document.activeElement !== addr) addr.value = path;
  hideSug();
  document.body.classList.toggle("chat-on", path.startsWith("msg/") || path.startsWith("lxmf@"));
  document.querySelectorAll("nav.tabs a").forEach((a) => {
    const href = a.getAttribute("href") || "";
    const top = path.split("/")[0];
    a.classList.toggle("on", href.indexOf("#/" + top) === 0 || (path.startsWith("node/") && href === "#/nodes"));
  });
  if (window.htmx) htmx.ajax("GET", viewUrl(path), { target: "#app", swap: "innerHTML" });
}
function openPeer(ev) {
  ev.preventDefault();
  const v = (document.getElementById("newTo") || {}).value || "";
  const m = v.match(/([a-fA-F0-9]{32})/i);
  if (m) location.hash = "#/msg/" + m[1].toLowerCase();
}
function saveAlias(hash, path) {
  const name = prompt("Short name, e.g. forum");
  if (!name) return;
  const key = name.trim().toLowerCase().replace(/\s+/g, "-");
  fetch("/api/data", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ alias: { name: key, hash, path, title: name.trim() } }),
  }).then(() => alert("reticulum://" + key));
}
function pin(kind, hash, name, path) {
  fetch("/ui/pin", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ kind, hash, name, path: path || "" }),
  }).then(() => load());
}
function pageBack() {
  if (window.history.length > 1) history.back();
  else location.hash = "#/nodes";
}
let sugItems = [];
let sugIdx = -1;
function hideSug() {
  const box = document.getElementById("sug");
  if (box) { box.hidden = true; box.innerHTML = ""; }
  sugItems = [];
  sugIdx = -1;
}
function paintSug() {
  const box = document.getElementById("sug");
  if (!box) return;
  if (!sugItems.length) { hideSug(); return; }
  box.hidden = false;
  box.innerHTML = sugItems.map((it, i) =>
    `<button type="button" class="sug-item${i === sugIdx ? " on" : ""}" data-i="${i}">${it.label} <span class="muted">${it.kind}</span></button>`
  ).join("");
  box.querySelectorAll(".sug-item").forEach((b) => {
    b.onmousedown = (e) => { e.preventDefault(); goSug(Number(b.dataset.i)); };
  });
}
function goSug(i) {
  const it = sugItems[i];
  hideSug();
  if (it && it.href) location.hash = it.href.replace(/^#\/?/, "#/");
}
function jump(q) {
  q = (q || "").trim();
  if (!q || q === "home") { location.hash = "#/home"; return; }
  if (q === "nodes" || q === "msg" || q === "networks") { location.hash = "#/" + q; return; }
  const hex = (q.match(/([a-fA-F0-9]{32})/) || [])[1];
  if (hex && /lxmf/i.test(q)) { location.hash = "#/msg/" + hex.toLowerCase(); return; }
  if (hex && q.indexOf("/") >= 0) {
    location.hash = "#/node/" + hex.toLowerCase() + q.slice(q.indexOf("/"));
    return;
  }
  if (sugItems.length) { goSug(sugIdx >= 0 ? sugIdx : 0); return; }
  if (hex) { location.hash = "#/node/" + hex.toLowerCase(); return; }
  location.hash = "#/" + q;
}
document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("addrForm");
  const addr = document.getElementById("addr");
  if (form) form.onsubmit = (e) => { e.preventDefault(); jump(addr.value); };
  if (addr) {
    addr.addEventListener("input", () => {
      const q = addr.value.trim();
      if (q.length < 2) { hideSug(); return; }
      fetch("/ui/suggest?q=" + encodeURIComponent(q)).then((r) => r.json()).then((d) => {
        sugItems = d.items || [];
        sugIdx = sugItems.length ? 0 : -1;
        paintSug();
      }).catch(() => hideSug());
    });
    addr.addEventListener("keydown", (e) => {
      if (e.key === "Escape") { hideSug(); addr.blur(); }
      if (e.key === "ArrowDown" && sugItems.length) { e.preventDefault(); sugIdx = (sugIdx + 1) % sugItems.length; paintSug(); }
      if (e.key === "ArrowUp" && sugItems.length) { e.preventDefault(); sugIdx = (sugIdx - 1 + sugItems.length) % sugItems.length; paintSug(); }
    });
  }
  load();
});
window.addEventListener("hashchange", load);
fetch("/api/version").then((r) => r.json()).then((v) => {
  return fetch("/api/hello").then((r) => r.json()).then((hello) => {
    const el = document.getElementById("ver");
    if (el) el.textContent = [hello.name || "", v.label || ""].filter(Boolean).join(" · ");
  });
}).catch(() => {});
document.body.addEventListener("click", (e) => {
  const a = e.target.closest(".page a");
  if (!a) return;
  const href = a.getAttribute("href") || "";
  if (href.startsWith("http") || href.startsWith("mailto:")) return;
  e.preventDefault();
  const cur = route();
  const m = cur.match(/^node\/([a-fA-F0-9]{32})/);
  const hash = m ? m[1] : "";
  const raw = href.replace(/^nomadnetwork:\/\//, "");
  if (/lxmf@/i.test(raw) || raw.startsWith("#/msg/")) {
    const p = (raw.match(/([a-fA-F0-9]{32})/) || [])[1];
    if (p) location.hash = "#/msg/" + p.toLowerCase();
    return;
  }
  if (raw.startsWith(":/")) location.hash = "#/node/" + hash + raw.slice(1);
  else if (raw.includes(":")) {
    const i = raw.indexOf(":");
    location.hash = "#/node/" + raw.slice(0, i) + (raw.slice(i + 1) || "/page/index.mu");
  } else if (raw.startsWith("/")) location.hash = "#/node/" + hash + raw;
});
