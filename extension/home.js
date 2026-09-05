const ext = typeof browser !== "undefined" ? browser : chrome;
const PORT = 4240;
const SCAN_BASES = ["192.168.0", "192.168.1", "192.168.8", "192.168.88", "10.0.0"];

const $app = document.getElementById("app");
const $addr = document.getElementById("addr");
const $form = document.getElementById("addrForm");

function stateDefaults() {
  return { gateway: null, aliases: {}, history: [] };
}

async function loadState() {
  const data = await ext.storage.local.get(["gateway", "aliases", "history"]);
  return {
    gateway: data.gateway || null,
    aliases: data.aliases || {},
    history: data.history || [],
  };
}

async function saveState(patch) {
  await ext.storage.local.set(patch);
}

function route() {
  let raw = decodeURIComponent((location.hash || "#/home").replace(/^#\/?/, ""));
  raw = raw.replace(/^(ext\+)?reticulum:\/\//, "");
  return raw || "home";
}

function go(path) {
  const clean = String(path)
    .replace(/^(ext\+)?reticulum:\/\//, "")
    .replace(/^#\/?/, "");
  location.hash = "#/" + clean;
}

function gwBase(gw) {
  return `${gw.proto || "http"}://${gw.ip}:${gw.port || PORT}`;
}

async function api(gw, path) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), 8000);
  try {
    const res = await fetch(gwBase(gw) + path, { signal: ctrl.signal });
    if (!res.ok) throw new Error("HTTP " + res.status);
    return await res.json();
  } finally {
    clearTimeout(t);
  }
}

async function helloOnce(proto, ip, port, ms) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), ms);
  try {
    const res = await fetch(`${proto}://${ip}:${port}/api/hello`, { signal: ctrl.signal });
    if (!res.ok) return null;
    const data = await res.json();
    if (!data || !data.ok) return null;
    return { ip, port, proto, name: data.name || ip, demo: !!data.demo, rns: !!data.rns };
  } catch {
    return null;
  } finally {
    clearTimeout(t);
  }
}

async function hello(ip, port = PORT, ms = 350) {
  return (await helloOnce("http", ip, port, ms)) || (await helloOnce("https", ip, port, ms));
}

async function scanLan(onHit) {
  const found = [];
  const seen = new Set();
  const tryHost = async (host, ms) => {
    const key = host;
    if (seen.has(key)) return;
    seen.add(key);
    const hit = await hello(host, PORT, ms);
    if (hit) {
      found.push(hit);
      onHit([...found]);
    }
  };

  await tryHost("127.0.0.1", 600);
  await tryHost("localhost", 600);
  await tryHost("rnode.local", 700);

  const jobs = [];
  for (const base of SCAN_BASES) {
    for (let i = 1; i <= 254; i++) jobs.push(`${base}.${i}`);
  }
  const batch = 40;
  for (let i = 0; i < jobs.length; i += batch) {
    await Promise.all(jobs.slice(i, i + batch).map((ip) => tryHost(ip, 280)));
  }
  return found;
}

function escapeHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function rewritePageHtml(html, currentHash) {
  const wrap = document.createElement("div");
  wrap.innerHTML = html || "";
  wrap.querySelectorAll("a").forEach((a) => {
    const href = a.getAttribute("href") || "";
    a.addEventListener("click", (ev) => {
      ev.preventDefault();
      openMeshUrl(href, currentHash);
    });
  });
  return wrap;
}

function openMeshUrl(href, currentHash) {
  let hash = currentHash;
  let path = "/page/index.mu";
  const raw = href.replace(/^nomadnetwork:\/\//, "");
  if (raw.startsWith(":/")) {
    path = raw.slice(1);
  } else if (raw.includes(":")) {
    const i = raw.indexOf(":");
    hash = raw.slice(0, i).replace(/[<>]/g, "");
    path = raw.slice(i + 1) || "/page/index.mu";
  } else if (/^[a-fA-F0-9]{32}$/.test(raw)) {
    hash = raw;
  } else if (raw.startsWith("/")) {
    path = raw;
  }
  if (!path.startsWith("/")) path = "/" + path;
  go(`node/${hash}${path}`);
}

async function pushHistory(entry) {
  const st = await loadState();
  const history = [
    { ...entry, when: Date.now() },
    ...st.history.filter((h) => h.url !== entry.url),
  ].slice(0, 40);
  await saveState({ history });
}

async function render() {
  const st = await loadState();
  const path = route();
  $addr.value = path;

  if (path === "setup" || path === "setup/") {
    return renderSetup(st);
  }
  if (!st.gateway) {
    return renderSetup(st, true);
  }
  if (path === "home" || path === "") {
    return renderHome(st);
  }
  if (path === "networks") {
    return renderNetworks(st);
  }
  if (path === "nodes") {
    return renderNodes(st);
  }
  if (path.startsWith("node/")) {
    return renderPage(st, path.slice(5));
  }
  const alias = st.aliases[path.split("/")[0]];
  if (alias) {
    const rest = path.includes("/") ? path.slice(path.indexOf("/")) : alias.path || "/page/index.mu";
    return renderPage(st, `${alias.hash}${rest.startsWith("/") ? rest : "/" + rest}`, path.split("/")[0]);
  }
  $app.innerHTML = `<div class="card"><h1>Nie znaleziono</h1><p class="muted">Brak aliasu <code>${escapeHtml(path)}</code>.</p></div>`;
}

function renderSetup(st, first = false) {
  $app.innerHTML = `
    <h1>${first ? "Wskaż rNode" : "Urządzenie"}</h1>
    <p class="muted">Dodatek skanuje sieć lokalną po porcie ${PORT}. Możesz też wpisać IP ręcznie.</p>
    <div class="row">
      <button id="scanBtn" type="button">Skanuj sieć</button>
      <span id="scanInfo" class="muted"></span>
    </div>
    <div id="found" class="list"></div>
    <label class="adv">Opcja zaawansowana — IP na sztywno</label>
    <div class="row">
      <input class="field" id="manualIp" placeholder="192.168.1.50" style="max-width:240px">
      <button class="ghost" id="manualBtn" type="button">Użyj tego IP</button>
    </div>
  `;
  const $found = $app.querySelector("#found");
  const $info = $app.querySelector("#scanInfo");

  const paint = (list) => {
    if (!list.length) {
      $found.innerHTML = `<p class="muted">Nic jeszcze nie znaleziono.</p>`;
      return;
    }
    $found.innerHTML = list
      .map(
        (d, i) => `
      <div class="card spread">
        <div>
          <h3>${escapeHtml(d.name)}</h3>
          <div class="hash">${escapeHtml(d.ip)}:${d.port}${d.demo ? " · demo" : ""}</div>
        </div>
        <button data-i="${i}" type="button">Wybierz</button>
      </div>`
      )
      .join("");
    $found.querySelectorAll("button[data-i]").forEach((btn) => {
      btn.onclick = async () => {
        await saveState({ gateway: list[Number(btn.dataset.i)] });
        go("home");
      };
    });
  };

  $app.querySelector("#scanBtn").onclick = async () => {
    $info.textContent = "Skanuję…";
    const list = await scanLan((partial) => {
      $info.textContent = `Znaleziono ${partial.length}…`;
      paint(partial);
    });
    $info.textContent = list.length ? `Gotowe (${list.length})` : "Brak urządzeń. Wpisz IP albo zaakceptuj certyfikat HTTPS.";
    paint(list);
    if (!list.length) showHttpsHint($app.querySelector("#manualIp").value.trim());
  };

  const showHttpsHint = (ip) => {
    const host = ip || "IP-RPI";
    let box = $app.querySelector("#httpsHint");
    if (!box) {
      box = document.createElement("div");
      box.id = "httpsHint";
      box.className = "card";
      $app.appendChild(box);
    }
    box.innerHTML = `
      <p>Firefox często wymusza HTTPS. Bramka ma własny certyfikat — trzeba go raz zaakceptować.</p>
      <ol>
        <li>Otwórz <a href="https://${escapeHtml(host)}:${PORT}" target="_blank" rel="noopener">https://${escapeHtml(host)}:${PORT}</a></li>
        <li>Zaawansowane → zaakceptuj ryzyko</li>
        <li>Wróć tutaj i skanuj / potwierdź IP jeszcze raz</li>
      </ol>
      <p class="muted">Albo w ustawieniach Firefoksa wyłącz „Tryb tylko HTTPS”.</p>
    `;
  };

  $app.querySelector("#manualBtn").onclick = async () => {
    const ip = $app.querySelector("#manualIp").value.trim();
    if (!ip) return;
    $info.textContent = "Sprawdzam…";
    const hit = await hello(ip, PORT, 2000);
    if (!hit) {
      $info.textContent = "Brak odpowiedzi — pewnie HTTPS w Firefoxie.";
      showHttpsHint(ip);
      return;
    }
    await saveState({ gateway: hit });
    go("home");
  };
}

async function renderHome(st) {
  const gw = st.gateway;
  $app.innerHTML = `
    <h1>Panel</h1>
    <p class="muted">Urządzenie: <b>${escapeHtml(gw.name)}</b> · ${escapeHtml(gw.ip)}:${gw.port || PORT}</p>
    <div class="row">
      <button type="button" id="toNodes">Rozgłoszone node'y</button>
      <button type="button" id="toNets">Sieci</button>
      <button class="ghost" type="button" id="rescan">Zmień urządzenie</button>
    </div>
    <h2>Szukaj / alias</h2>
    <input class="field search" id="q" placeholder="np. forum albo fragment hasha">
    <div id="aliasHits"></div>
    <h2>Historia</h2>
    <div id="hist"></div>
  `;
  $app.querySelector("#toNodes").onclick = () => go("nodes");
  $app.querySelector("#toNets").onclick = () => go("networks");
  $app.querySelector("#rescan").onclick = () => go("setup");

  const hist = st.history
    .map(
      (h) => `
      <div class="card spread hist">
        <div>
          <div>${escapeHtml(h.title || h.url)}</div>
          <div class="hash">${escapeHtml(h.url)}</div>
        </div>
        <button class="ghost small" data-url="${escapeHtml(h.url)}">Otwórz</button>
      </div>`
    )
    .join("") || `<p class="muted">Pusto. Wejdź na node, żeby tu wrócił.</p>`;
  $app.querySelector("#hist").innerHTML = hist;
  $app.querySelectorAll("#hist button").forEach((b) => {
    b.onclick = () => go(b.dataset.url.replace(/^reticulum:\/\//, ""));
  });

  const $q = $app.querySelector("#q");
  const $hits = $app.querySelector("#aliasHits");
  const paintHits = () => {
    const q = $q.value.trim().toLowerCase();
    const aliases = Object.entries(st.aliases);
    const list = aliases.filter(([name, a]) => {
      if (!q) return true;
      return name.includes(q) || (a.hash || "").includes(q) || (a.title || "").toLowerCase().includes(q);
    });
    if (!aliases.length) {
      $hits.innerHTML = `<p class="muted">Brak aliasów. Nadaj je na stronie node'a.</p>`;
      return;
    }
    $hits.innerHTML = list
      .map(
        ([name, a]) => `
        <div class="card spread">
          <div>
            <h3>${escapeHtml(name)}</h3>
            <div class="hash">${escapeHtml(a.hash)}</div>
          </div>
          <button class="small" data-name="${escapeHtml(name)}">Otwórz</button>
        </div>`
      )
      .join("");
    $hits.querySelectorAll("button[data-name]").forEach((b) => {
      b.onclick = () => go(b.dataset.name);
    });
  };
  $q.oninput = paintHits;
  paintHits();
}

async function renderNetworks(st) {
  $app.innerHTML = `
    <h1>Sieci</h1>
    <p class="muted">Włącz jedną sieć publiczną, żeby od razu zobaczyć obce node’y. Nic nie edytujesz na malinie — zapis idzie z tego ekranu.</p>
    <p class="muted" id="netStatus">Wczytuję…</p>
    <div id="presets" class="list"></div>
    <h2>Własny serwer</h2>
    <div class="row">
      <input class="field" id="cHost" placeholder="np. rmap.world" style="max-width:220px">
      <input class="field" id="cPort" placeholder="4242" style="max-width:90px">
      <input class="field" id="cName" placeholder="nazwa (opcjonalnie)" style="max-width:180px">
    </div>
    <div class="row" style="margin-top:12px">
      <button type="button" id="saveNets">Zapisz i połącz</button>
      <span class="muted" id="saveInfo"></span>
    </div>
    <p class="muted" id="live"></p>
  `;
  const $status = $app.querySelector("#netStatus");
  const $presets = $app.querySelector("#presets");
  let data = { presets: [] };
  try {
    data = await api(st.gateway, "/api/networks");
    $status.textContent = data.live && data.live.length
      ? "Bramka zgłasza " + data.live.length + " interfejs(y)."
      : "Na razie brak połączenia ze światem — włącz Dublin albo RMAP.";
  } catch {
    $status.textContent = "Nie mogę odczytać sieci z urządzenia.";
    return;
  }

  const paint = () => {
    $presets.innerHTML = data.presets
      .map(
        (p) => `
      <label class="card spread" style="cursor:pointer">
        <div>
          <h3>${escapeHtml(p.title)}${p.recommended ? " · polecane" : ""}</h3>
          <p class="muted">${escapeHtml(p.hint)}</p>
        </div>
        <input type="checkbox" data-id="${escapeHtml(p.id)}" ${p.enabled ? "checked" : ""}>
      </label>`
      )
      .join("");
  };
  paint();
  $app.querySelector("#live").textContent = (data.live || []).join(" · ");

  $app.querySelector("#saveNets").onclick = async () => {
    const enabled = [...$presets.querySelectorAll("input[type=checkbox]:checked")].map((el) => el.dataset.id);
    const host = $app.querySelector("#cHost").value.trim();
    const custom = host
      ? [{ host, port: $app.querySelector("#cPort").value.trim() || "4242", name: $app.querySelector("#cName").value.trim() }]
      : [];
    if (!enabled.length && !custom.length) {
      $app.querySelector("#saveInfo").textContent = "Zaznacz choć jedną sieć.";
      return;
    }
    $app.querySelector("#saveInfo").textContent = "Zapisuję…";
    try {
      const res = await fetch(gwBase(st.gateway) + "/api/networks", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled, custom }),
      });
      const out = await res.json();
      if (!out.ok) throw new Error(out.error || "błąd");
      $app.querySelector("#saveInfo").textContent = "Bramka się restartuje. Czekaj 5 sekund…";
      setTimeout(() => go("nodes"), 5000);
    } catch (e) {
      $app.querySelector("#saveInfo").textContent = "Nie zapisało się. Sprawdź, czy bramka działa.";
    }
  };
}

async function renderNodes(st) {
  $app.innerHTML = `
    <h1>Node'y</h1>
    <p class="muted" id="status">Pobieram listę z ${escapeHtml(st.gateway.ip)}…</p>
    <input class="field search" id="filter" placeholder="Filtruj po nazwie albo hashu">
    <div id="list" class="list"></div>
  `;
  const $status = $app.querySelector("#status");
  const $list = $app.querySelector("#list");
  const $filter = $app.querySelector("#filter");
  let nodes = [];

  const paint = () => {
    const q = $filter.value.trim().toLowerCase();
    const show = nodes.filter((n) => {
      if (!q) return true;
      return (n.name || "").toLowerCase().includes(q) || (n.hash || "").includes(q);
    });
    if (!show.length) {
      $list.innerHTML = `<p class="muted">Nic nie pasuje.</p>`;
      return;
    }
    $list.innerHTML = show
      .map(
        (n) => `
        <div class="card">
          <div class="spread">
            <div>
              <h3>${escapeHtml(n.name)}</h3>
              <div class="hash">${escapeHtml(n.hash)}</div>
              <div class="muted">${escapeHtml(n.app || "")}${n.demo ? " · demo" : ""}</div>
            </div>
            <button data-hash="${escapeHtml(n.hash)}" data-name="${escapeHtml(n.name)}">Odwiedź</button>
          </div>
        </div>`
      )
      .join("");
    $list.querySelectorAll("button[data-hash]").forEach((b) => {
      b.onclick = () => go(`node/${b.dataset.hash}/page/index.mu`);
    });
  };

  try {
    const data = await api(st.gateway, "/api/nodes");
    nodes = data.nodes || [];
    $status.innerHTML = nodes.length
      ? `${nodes.length} rozgłoszonych`
      : `Lista pusta. Wejdź w <a href="#/networks">Sieci</a> i włącz „Dublin” albo „RMAP”.`;
    paint();
  } catch (e) {
    $status.innerHTML = `Nie mam połączenia z urządzeniem. <button class="ghost small" id="fix">Ustawienia</button>`;
    $app.querySelector("#fix").onclick = () => go("setup");
  }
  $filter.oninput = paint;
}

async function renderPage(st, rest, aliasName) {
  const m = rest.match(/^([a-fA-F0-9]{32})(\/.*)?$/);
  if (!m) {
    $app.innerHTML = `<div class="card"><p class="warn">Zły adres node'a.</p></div>`;
    return;
  }
  const hash = m[1].toLowerCase();
  const path = m[2] || "/page/index.mu";
  $app.innerHTML = `
    <p class="muted">Ładuję ${escapeHtml(hash.slice(0, 8))}…${escapeHtml(path)}</p>
  `;
  try {
    const data = await api(
      st.gateway,
      `/api/page?hash=${encodeURIComponent(hash)}&path=${encodeURIComponent(path)}`
    );
    if (!data.ok && !data.text) {
      $app.innerHTML = `<div class="card"><p class="warn">${escapeHtml(data.error || "Błąd")}</p></div>`;
      return;
    }
    const title = aliasName || hash.slice(0, 8);
    await pushHistory({
      title: title + path,
      url: aliasName ? aliasName : `node/${hash}${path}`,
      hash,
      path,
    });
    $app.innerHTML = `
      <div class="spread">
        <div>
          <h1>${escapeHtml(title)}</h1>
          <div class="hash">${escapeHtml(hash)}${escapeHtml(path)}</div>
          ${data.source === "demo" ? `<p class="muted">Źródło poglądowe${data.note ? " · " + escapeHtml(data.note) : ""}</p>` : ""}
        </div>
        <button class="ghost small" id="aliasBtn">Zapisz alias</button>
      </div>
      <div class="card page" id="page"></div>
    `;
    const page = $app.querySelector("#page");
    page.appendChild(rewritePageHtml(data.html || `<pre>${escapeHtml(data.text || "")}</pre>`, hash));
    $app.querySelector("#aliasBtn").onclick = async () => {
      const name = prompt("Krótka nazwa, np. forum", aliasName || "");
      if (!name) return;
      const key = name.trim().toLowerCase().replace(/\s+/g, "-");
      const st2 = await loadState();
      st2.aliases[key] = { hash, path, title: name.trim() };
      await saveState({ aliases: st2.aliases });
      alert("Alias reticulum://" + key);
    };
  } catch (e) {
    $app.innerHTML = `<div class="card"><p class="warn">Bramka nie odpowiedziała.</p><button id="fix">Urządzenie</button></div>`;
    $app.querySelector("#fix").onclick = () => go("setup");
  }
}

$form.addEventListener("submit", (ev) => {
  ev.preventDefault();
  go($addr.value.trim() || "home");
});
document.getElementById("goHome").onclick = () => go("home");
document.getElementById("goNetworks").onclick = () => go("networks");
document.getElementById("goSetup").onclick = () => go("setup");
window.addEventListener("hashchange", render);
render();
