
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
    return "/ui/page?hash=" + m[1].toLowerCase() + "&path=" + encodeURIComponent(m[2] || "/page/index.mu");
  }
  return "/ui/home";
}
function load() {
  const path = route();
  const addr = document.getElementById("addr");
  if (addr) addr.value = path;
  document.body.classList.toggle("chat-on", path.startsWith("msg/") || path.startsWith("lxmf@"));
  document.querySelectorAll("nav.tabs a").forEach((a) => {
    const href = a.getAttribute("href") || "";
    const top = path.split("/")[0];
    a.classList.toggle("on", href === "#/" + top || (path.startsWith("node/") && href === "#/nodes") || (path.startsWith("msg") && href === "#/msg"));
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
document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("addrForm");
  if (form) form.onsubmit = (e) => {
    e.preventDefault();
    location.hash = "#/" + (document.getElementById("addr").value.trim() || "home");
  };
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
