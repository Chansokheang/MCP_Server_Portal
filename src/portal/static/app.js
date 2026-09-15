/* Bizplay MCP onboarding portal. Mockup front end (vanilla JS, no build step). */

const $ = (sel, root = document) => root.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const asDate = (t) => (typeof t === "number" ? new Date(t * 1000) : new Date(t));
// Compact, single-line date formats so table columns never wrap.
const fmtTs = (t) => asDate(t).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false });
const fmtDate = (t) => asDate(t).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
const fmtUtc = (iso) => String(iso).replace("T", " ").replace(/\+00:00$/, "").slice(5, 19);  // "09-14 14:25:38"
const days = (secs) => Math.max(0, Math.round(secs / 86400));
const initials = (s) => String(s || "?").split(/[\s\-_]+/).slice(0, 2).map((w) => w[0]?.toUpperCase() || "").join("");

let session = null;
try { session = JSON.parse(localStorage.getItem("portal.session") || "null"); } catch { session = null; }

// ---- API client: every call carries the portal session bearer token ----
async function api(method, path, body) {
  const headers = { "Content-Type": "application/json" };
  if (session?.token) headers.Authorization = `Bearer ${session.token}`;
  const res = await fetch(path, { method, headers, body: body ? JSON.stringify(body) : undefined });
  if (res.status === 401 && path !== "/api/login") { signOut(); throw new Error("Session expired, please sign in again"); }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `${res.status} ${res.statusText}`);
  return data;
}

// ---- motion ----
const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)");

/** Restart a CSS animation on an element that is being reused. */
function replay(el, cls) {
  if (!el || reduceMotion.matches) return;
  el.classList.remove(cls); void el.offsetWidth; el.classList.add(cls);
}

/** Flatten a block into the pieces worth animating: grid items, not their wrappers. */
function animUnits(block) {
  const groups = [...block.querySelectorAll(".stats, .cards, .checklist")];
  if (!groups.length) return [block];
  const out = [];
  for (const child of block.children) {
    if (groups.includes(child)) out.push(...child.children);
    else if (groups.some((g) => child.contains(g))) out.push(...animUnits(child));
    else out.push(child);
  }
  return out;
}

/** Stagger a freshly rendered page so numbers land first, then the detail below. */
function animateIn(root) {
  if (reduceMotion.matches || !root) return;
  const units = [...root.children].flatMap(animUnits);
  units.forEach((el, i) => { el.style.setProperty("--i", Math.min(i, 14)); replay(el, "anim"); });
  root.querySelectorAll(".stat .num").forEach(countUp);
}

/** Count a headline metric up from zero. Draws the eye to what changed. */
function countUp(el) {
  const m = el.textContent.trim().match(/^(\d+)(\D*)$/);
  if (!m) return;
  const to = Number(m[1]), suffix = m[2], start = performance.now(), dur = 650;
  const step = (now) => {
    const p = Math.min(1, (now - start) / dur);
    el.textContent = Math.round(to * (1 - Math.pow(1 - p, 3))) + suffix;
    if (p < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

// ---- small UI helpers ----
function toast(title, sub = "", ms = 3000) {
  const el = $("#toast");
  el.innerHTML = `<span class="mark"><i class="ph ph-check"></i></span><div><strong>${esc(title)}</strong>${sub ? `<span>${esc(sub)}</span>` : ""}</div>`;
  el.classList.remove("hidden", "leaving");
  replay(el, "toast");
  clearTimeout(toast._t); clearTimeout(toast._h);
  toast._t = setTimeout(() => {
    if (reduceMotion.matches) return el.classList.add("hidden");
    el.classList.add("leaving");
    toast._h = setTimeout(() => el.classList.add("hidden"), 220);
  }, ms);
}
function modal(html) {
  $("#modal-body").innerHTML = html;
  $("#modal").classList.remove("hidden");
  replay($("#modal .modal-card"), "modal-card");
}
function closeModal() { $("#modal").classList.add("hidden"); }
$("#modal").addEventListener("click", (e) => { if (e.target.id === "modal") closeModal(); });

const SKELETON = `<div class="skeleton" aria-busy="true"><div class="bar w-40"></div><div class="bar tall"></div><div class="bar w-70"></div><div class="bar tall"></div></div>`;
const emptyState = (icon, title, hint) => `<div class="empty"><span class="mark"><i class="ph ph-${icon}"></i></span><strong>${title}</strong><span class="small">${hint}</span></div>`;
const chip = (kind, text, icon) => `<span class="chip ${kind}">${icon ? `<i class="ph ph-${icon}"></i>` : ""}${esc(text)}</span>`;
const tile = (icon, k, v, mono = false) => `<div class="tile"><span class="k"><i class="ph ph-${icon}"></i>${esc(k)}</span><span class="v ${mono ? "mono" : ""}">${esc(v)}</span></div>`;
const LOGO_COLORS = ["green", "lilac", "amber", "dark", "red"];
const logo = (name, i = 0) => `<span class="logo ${LOGO_COLORS[i % LOGO_COLORS.length]}">${esc(initials(name))}</span>`;
const authChip = (m) => ({ bearer: chip("lilac", "Bearer", "key"), network: chip("amber", "Network", "shield-check"), open: chip("red", "Open", "warning"), oauth: chip("green", "OAuth per user", "user-circle") }[m] || chip("lilac", "Bearer", "key"));
// Fields for a backend whose users link their own accounts. Shared by the register and edit dialogs.
const oauthFields = (prefix, cfg = {}) => `
  <div class="form-2">
    <label class="field">Authorization URL <input name="oauth.authorization_url" value="${esc(cfg.authorization_url || "")}" placeholder="https://auth.example.com/authorize"></label>
    <label class="field">Token URL <input name="oauth.token_url" value="${esc(cfg.token_url || "")}" placeholder="https://auth.example.com/token"></label>
    <label class="field">Client id <input name="oauth.client_id" value="${esc(cfg.client_id || "")}" placeholder="issued by the auth server"></label>
    <label class="field">Client secret <input name="oauth.client_secret" placeholder="${cfg.has_client_secret ? "stored, leave blank to keep" : "if the auth server issued one"}"></label>
    <label class="field">Scopes <input name="oauth.scopes" value="${esc(cfg.scopes || "")}" placeholder="space separated, e.g. tasks:read"></label>
    <label class="field">Resource (RFC 8707) <input name="oauth.resource" value="${esc(cfg.resource || "")}" placeholder="MCP servers: their own URL"></label>
  </div>
  <div class="callout"><i class="ph ph-info"></i><span>Register this redirect URL with the auth server: <span class="mono">${esc(SERVER.oauth_redirect_uri || (location.origin + "/oauth/callback"))}</span>. MCP servers that publish their auth metadata can fill all of this in with <strong>Discover</strong> on the provider page, and register the gateway as a client by themselves.</span></div>`;
/** Pull "oauth.x" fields out of a form into {oauth: {x}}. */
function splitOauth(f) {
  const oauth = {};
  for (const [k, v] of Object.entries(f)) if (k.startsWith("oauth.")) { oauth[k.slice(6)] = v; delete f[k]; }
  return { ...f, oauth };
}
const kindChip = (k) => k === "mcp" ? chip("green", "MCP server", "plugs-connected") : chip("", "REST API", "cloud");
const standaloneChip = (p) => p.standalone ? chip("green", "Deployed", "rocket-launch") : "";
const statusChip = (s) => s === "published" ? chip("green", "Published", "check") : chip("", "Draft", "pencil-simple");
const outcomeChip = (o) => ({ ok: chip("green", "ok"), denied: chip("red", "denied"), error: chip("amber", "error") }[o] || chip("", o));
const passChip = (ok) => ok ? chip("green", "pass", "check") : chip("red", "fail", "x");

// ---- auth ----
function signOut() {
  if (session?.token) api("POST", "/api/logout").catch(() => {});
  session = null; localStorage.removeItem("portal.session");
  $("#app").classList.add("hidden"); $("#login").classList.remove("hidden");
}
$("#login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  try {
    const data = await api("POST", "/api/login", { email: f.get("email"), password: f.get("password") });
    session = { token: data.token, user: data.user };
    localStorage.setItem("portal.session", JSON.stringify(session));
    $("#login-error").textContent = "";
    enterApp();
  } catch (err) { $("#login-error").textContent = err.message; }
});
$("#logout").addEventListener("click", signOut);

// ---- theme ----
const isDark = () => document.documentElement.dataset.theme === "dark";
function applyThemeIcon() { $("#theme-toggle i").className = isDark() ? "ph ph-sun" : "ph ph-moon"; }
$("#theme-toggle").addEventListener("click", () => {
  const next = isDark() ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem("portal.theme", next); } catch {}
  applyThemeIcon();
});
applyThemeIcon();

function enterApp() {
  $("#login").classList.add("hidden"); $("#app").classList.remove("hidden");
  api("GET", "/api/config").then((c) => { SERVER = c; }).catch(() => {});
  $("#whoami-avatar").textContent = initials(session.user.name);
  $("#whoami-name").textContent = session.user.name;
  $("#whoami-sub").textContent = `DemoCorp01 / ${session.user.role}`;
  go(location.hash.replace("#", "") || "overview");
}

// ---- router ----
const pages = {};
const titles = { overview: "Overview", registry: "MCP Registry", servers: "MCP Servers", provider: "Backend details", access: "Access Control", tokens: "Agent Tokens", security: "Security", audit: "Audit Log" };
// Pages reached from another page keep that page's nav item lit.
const RAIL_OF = { provider: "registry" };
function hashParam(name) { return new URLSearchParams(location.hash.split("?")[1] || "").get(name); }
function setHash(page, params) { const q = new URLSearchParams(params || {}).toString(); location.hash = q ? `${page}?${q}` : page; }
/** Breadcrumb: Home / Section [/ Item]. */
function crumbs(...trail) {
  const items = [`<a data-page="overview"><i class="ph ph-house"></i> Home</a>`];
  trail.forEach((t, i) => {
    const last = i === trail.length - 1;
    items.push(`<span class="sep">/</span>`, last ? `<span class="here">${esc(t.label)}</span>` : `<a data-page="${esc(t.page)}">${esc(t.label)}</a>`);
  });
  $("#crumbs").innerHTML = items.join("");
  $("#crumbs").querySelectorAll("a").forEach((a) => a.onclick = () => go(a.dataset.page));
}
/** The one primary action for the page, top right. */
function pageActions(html) { $("#page-actions").innerHTML = html || ""; }
function go(page) {
  page = (page || "").split("?")[0];
  if (!pages[page]) page = "overview";
  if (location.hash.slice(1).split("?")[0] !== page) location.hash = page;
  const rail = RAIL_OF[page] || page;
  document.querySelectorAll(".side-nav a").forEach((a) => a.classList.toggle("active", a.dataset.page === rail));
  $("#page-title").textContent = titles[page];
  crumbs({ page, label: titles[page] });
  pageActions("");
  $("#global-search").value = "";
  $("#tabs").classList.add("hidden");
  $("#page").innerHTML = SKELETON;
  pages[page]().catch((err) => { $("#page").innerHTML = `<div class="card">${emptyState("warning-circle", "Could not load this page", esc(err.message))}<div style="text-align:center"><button class="btn" onclick="location.reload()">Retry</button></div></div>`; });
}
document.querySelectorAll(".side-nav a").forEach((a) => a.addEventListener("click", () => go(a.dataset.page)));
window.addEventListener("hashchange", () => session && go(location.hash.slice(1).split("?")[0]));

// Unified search: filters the rows and cards of whatever page is open. Ctrl+K focuses it.
$("#global-search").addEventListener("input", (e) => {
  const q = e.target.value.trim().toLowerCase();
  $("#page").querySelectorAll("tbody tr, tr:not(:first-child), .cards > .card").forEach((el) => {
    if (el.querySelector("th")) return;
    el.style.display = !q || el.textContent.toLowerCase().includes(q) ? "" : "none";
  });
});
document.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); $("#global-search").focus(); }
});

/** Re-run the current page's fetch, keeping the tab and provider you are on. */
function refreshPage() {
  const page = (location.hash.slice(1).split("?")[0]) || "overview";
  if (session && pages[page] && $("#modal").classList.contains("hidden")) pages[page]().catch(() => {});
}
$("#refresh").addEventListener("click", () => { refreshPage(); toast("Reloaded"); });
// Coming back to the tab shows current data, so registering an API elsewhere
// (or from a script) does not leave a stale page behind.
window.addEventListener("focus", refreshPage);
document.addEventListener("visibilitychange", () => { if (!document.hidden) refreshPage(); });

// Tab strip: [{key, label, icon, count}], plus optional note {title, sub}.
function renderTabs(items, active, onPick, note) {
  const el = $("#tabs");
  el.innerHTML = items.map((t) => `<button class="tab ${t.key === active ? "active" : ""}" data-key="${esc(t.key)}"><span class="tab-ic"><i class="ph ph-${t.icon}"></i></span>${esc(t.label)}${t.count != null ? `<span class="count">${t.count}</span>` : ""}</button>`).join("")
    + `<span class="spacer"></span>` + (note ? `<span class="tab-note ${note.tone || ""}"><span class="tab-ic"><i class="ph ${note.tone === "warn" ? "ph-warning" : "ph-check"}"></i></span><span><strong>${esc(note.title)}</strong><span>${esc(note.sub)}</span></span></span>` : "");
  el.classList.remove("hidden");
  el.querySelectorAll(".tab").forEach((b) => b.onclick = () => onPick(b.dataset.key));
}

// ---- Overview ----
pages.overview = async () => {
  const d = await api("GET", "/api/overview");
  const open = d.checklist.filter((c) => !c.ok), passing = d.checklist.length - open.length;
  const when = (ts) => { const t = new Date(ts); return `${t.getMonth() + 1}/${t.getDate()} ${String(t.getHours()).padStart(2, "0")}:${String(t.getMinutes()).padStart(2, "0")}`; };
  $("#page").innerHTML = `
    <div class="stats">
      <div class="stat"><span class="num">${d.providers}</span><span class="lbl">Registered backends, ${d.published} published</span></div>
      <div class="stat"><span class="num">${d.tools_enabled}</span><span class="lbl">Tools enabled for agents</span></div>
      <div class="stat"><span class="num">${d.tokens_active}</span><span class="lbl">Active agent tokens</span></div>
      <div class="stat"><span class="num" style="color:${d.score >= 70 ? "var(--green-ink)" : "var(--amber-ink)"}">${d.score}%</span><span class="lbl">Security score, ${open.length} open item(s)</span></div>
    </div>
    <div class="card flow-card">
      <div class="flow">
        <div class="node"><strong>AI agent</strong><span class="muted">Claude, ChatGPT, Copilot, Agentforce</span></div>
        <span class="arrow"><i class="ph ph-arrow-right"></i><br>agent token</span>
        <div class="node hl"><strong>MCP Gateway</strong><span>authentication, tool policy, company scope, audit</span></div>
        <span class="arrow"><i class="ph ph-arrow-right"></i><br>service or user token</span>
        <div class="node"><strong>REST API or MCP server</strong><span class="muted">unchanged; may also be deployed as its own MCP server</span></div>
      </div>
      <p class="muted small" style="margin:0">Two separate tokens: one identifies the end user to the gateway, one identifies the gateway to the backend. Neither reaches the model.</p>
    </div>
    <div class="two">
      <div>
        <div class="section-head"><h2 class="section-title">Security checklist</h2><a class="btn small link" href="#security?t=checklist">View all ${d.checklist.length}</a></div>
        <div class="table-card"><div class="table-wrap"><table>
          <tr><th style="width:90px">Status</th><th>Check</th></tr>
          ${open.map((c) => `<tr><td>${chip("red", "Open", "x")}</td><td><strong>${esc(c.label)}</strong><div class="sub">${esc(c.detail)}</div></td></tr>`).join("")}
          ${open.length ? "" : `<tr><td colspan="2">${emptyState("shield-check", "Every check passes", "Nothing open on the Security page.")}</td></tr>`}
          ${passing ? `<tr><td>${chip("green", "Pass", "check")}</td><td class="muted">${passing} check(s) passing</td></tr>` : ""}
        </table></div></div>
      </div>
      <div>
        <div class="section-head"><h2 class="section-title">Recent gateway activity</h2><a class="btn small link" href="#audit">Audit log</a></div>
        <div class="table-card">${d.audit_recent.length ? `<div class="table-wrap"><table><tr><th>Time</th><th>User</th><th>Tool</th><th>Result</th></tr>${d.audit_recent.map((e) => `<tr><td class="small mono" style="white-space:nowrap">${esc(when(e.ts))}</td><td><span class="mono">${esc(e.user_id)}</span><div class="sub">${esc(e.via || "env")}</div></td><td class="mono small">${esc(e.tool)}</td><td>${outcomeChip(e.outcome)}</td></tr>`).join("")}</table></div>` : emptyState("chat-circle-dots", "No gateway calls yet", "Ask Claude something that uses a Bizplay tool and it shows up here.")}</div>
      </div>
    </div>`;
};

// ---- Registry ----
pages.registry = async () => {
  const d = await api("GET", "/api/registry");
  const filter = hashParam("f") || "all";
  const items = d.items.filter((p) => filter === "all" || (filter === "deployed" ? p.standalone : p.status === filter));
  renderTabs([
    { key: "all", label: "All", icon: "squares-four", count: d.items.length },
    { key: "published", label: "Published", icon: "check-circle", count: d.items.filter((p) => p.status === "published").length },
    { key: "draft", label: "Draft", icon: "pencil-simple", count: d.items.filter((p) => p.status === "draft").length },
    { key: "deployed", label: "Deployed as MCP server", icon: "rocket-launch", count: d.items.filter((p) => p.standalone).length },
  ], filter, (k) => { setHash("registry", { f: k }); pages.registry(); },
  { title: "Registry live", sub: `${d.items.filter((p) => p.status === "published").length} backend(s) reachable by agents` });

  pageActions(`<button class="btn solid" id="btn-register"><i class="ph ph-plus"></i> Register backend</button>`);
  $("#page").innerHTML = `
    <div class="filter-bar">
      <label>Type <select id="reg-filter-kind"><option value="">All</option><option value="openapi">REST API</option><option value="mcp">MCP server</option></select></label>
      <label>Auth <select id="reg-filter-auth"><option value="">All</option><option value="bearer">Bearer</option><option value="oauth">OAuth per user</option><option value="network">Network</option><option value="open">Open</option></select></label>
      <span class="grow"></span>
      <span class="muted small">${items.length} backend(s). Type in the search box above to filter by name, URL or owner.</span>
    </div>
    <div class="table-card"><div class="table-wrap"><table id="registry-table">
      <tr><th>Backend</th><th>Type and auth</th><th>Status</th><th>Tools</th><th>Endpoint</th><th></th></tr>
      ${items.length ? items.map((p, i) => `<tr class="row-link" data-kind="${esc(p.kind)}" data-auth="${esc(p.auth_mode)}" data-open="${esc(p.id)}" title="Registered ${esc(fmtDate(p.created_at))} by ${esc(p.owner)}">
        <td><span class="name">${logo(p.name, i)} <span>${esc(p.name)}<div class="sub mono">${esc(p.base_url.replace(/^https?:\/\//, ""))}</div></span></span></td>
        <td><div class="chips">${kindChip(p.kind)}${authChip(p.auth_mode)}</div></td>
        <td><div class="chips">${statusChip(p.status)}${standaloneChip(p)}</div></td>
        <td><span class="mono">${p.tools_enabled} / ${p.tool_count}</span></td>
        <td class="mono small url">${esc(p.standalone ? p.standalone_url : p.mcp_url)}${p.tool_prefix && !p.standalone ? `<div class="sub">tools ${esc(p.tool_prefix)}*</div>` : p.standalone ? `<div class="sub">own server, plain tool names</div>` : ""}</td>
        <td class="actions">
          ${p.has_spec || p.kind === "mcp" ? `<button class="btn small ${p.standalone ? "" : "link"}" data-act="${p.standalone ? "undeploy" : "deploy"}" data-id="${esc(p.id)}" title="${p.standalone ? "Stop serving " + esc(p.standalone_url) : "Serve this backend alone at " + esc(p.standalone_url)}"><i class="ph ${p.standalone ? "ph-rocket" : "ph-rocket-launch"}"></i> ${p.standalone ? "Undeploy" : "Deploy"}</button>` : `<button class="btn small link" data-act="usage" data-id="${esc(p.id)}"><i class="ph ph-robot"></i> Setup</button>`}
        </td>
      </tr>`).join("")
      : `<tr><td colspan="6">${emptyState("plugs-connected", "No backends here", "Register a REST API with its OpenAPI spec, or an MCP server that already exists. Neither is changed.")}</td></tr>`}
    </table></div></div>
    <div class="callout"><i class="ph ph-info"></i><span><strong>Published</strong> puts a backend on the shared gateway endpoint, with this portal's tool policy enforced. <strong>Deployed</strong> additionally gives it an MCP server of its own at <span class="mono">/mcp/&lt;id&gt;</span>, with plain tool names, for teams that want one product per connector. Both take effect on the next request, no restart.</span></div>`;

  $("#btn-register").onclick = registerDialog;
  const applyFilters = () => {
    const k = $("#reg-filter-kind").value, a = $("#reg-filter-auth").value;
    $("#registry-table").querySelectorAll("tr[data-open]").forEach((tr) => {
      tr.style.display = (!k || tr.dataset.kind === k) && (!a || tr.dataset.auth === a) ? "" : "none";
    });
  };
  $("#reg-filter-kind").onchange = applyFilters; $("#reg-filter-auth").onchange = applyFilters;
  $("#page").querySelectorAll("tr[data-open]").forEach((tr) => tr.onclick = (e) => {
    if (e.target.closest("button")) return;
    setHash("provider", { p: tr.dataset.open });
  });
  $("#page").querySelectorAll("[data-act]").forEach((b) => b.onclick = async () => {
    const { act, id } = b.dataset;
    try {
      if (act === "detail") { setHash("provider", { p: id }); return; }
      if (act === "usage") { setHash("provider", { p: id, c: "claude-desktop" }); return; }
      const r = await api("POST", `/api/registry/${id}/${act}`);
      if (act === "deploy") { toast("Deployed as MCP server", `${r.name} now answers at ${r.standalone_url}`, 6000); setHash("provider", { p: id, via: "standalone" }); return; }
      if (act === "undeploy") { toast("Undeployed", `${r.standalone_url} now returns 404; the shared gateway still serves it`, 5000); }
      else toast(act === "publish" ? "Published" : "Unpublished", `${id} ${act === "publish" ? "is now reachable by agents" : "is hidden from agents"}`);
      pages.registry();
    } catch (err) { toast("Action failed", err.message, 4500); }
  });
};

// ---- MCP Servers: one deployed server per product, next to the shared gateway ----
pages.servers = async () => {
  const d = await api("GET", "/api/registry");
  const deployable = d.items.filter((p) => p.has_spec || p.kind === "mcp");
  const live = deployable.filter((p) => p.standalone);
  const candidates = deployable.filter((p) => !p.standalone);
  const filter = hashParam("f") || "deployed";
  renderTabs([
    { key: "deployed", label: "Deployed", icon: "rocket-launch", count: live.length },
    { key: "available", label: "Available to deploy", icon: "cube", count: candidates.length },
  ], filter, (k) => { setHash("servers", { f: k }); pages.servers(); },
  live.length ? { title: `${live.length} server(s) live`, sub: `${live.reduce((n, p) => n + p.tools_enabled, 0)} tools served` } : null);
  pageActions(`<button class="btn solid" id="btn-deploy-new"><i class="ph ph-rocket-launch"></i> Deploy MCP server</button>`);

  const rows = filter === "deployed" ? live : candidates;
  $("#page").innerHTML = `
    <div class="stats">
      <div class="stat"><span class="num">${live.length}</span><span class="lbl">MCP servers deployed</span></div>
      <div class="stat"><span class="num">${live.reduce((n, p) => n + p.tools_enabled, 0)}</span><span class="lbl">Tools served by them</span></div>
      <div class="stat"><span class="num">${candidates.length}</span><span class="lbl">Registered backends not deployed yet</span></div>
      <div class="stat"><span class="num">${d.items.filter((p) => p.status === "published").length}</span><span class="lbl">Backends on the shared gateway</span></div>
    </div>
    <div class="table-card"><div class="table-wrap"><table>
      <tr><th>MCP server</th><th>Built from</th><th>${filter === "deployed" ? "Endpoint" : "Would be served at"}</th><th>Tools</th><th>Status</th><th></th></tr>
      ${rows.length ? rows.map((p, i) => `<tr class="row-link" data-open="${esc(p.id)}">
        <td><span class="name">${logo(p.name, i)} <span>${esc(p.name)}<div class="sub">${esc(p.id)}</div></span></span></td>
        <td>${kindChip(p.kind)}<div class="sub mono">${esc(p.base_url.replace(/^https?:\/\//, ""))}</div></td>
        <td class="mono small url">${esc(p.standalone_url)}${filter === "deployed" ? `<div class="sub">plain tool names, no prefix</div>` : ""}</td>
        <td><span class="mono">${p.tools_enabled} / ${p.tool_count}</span></td>
        <td>${p.standalone ? (p.status === "published" ? chip("green", "Serving", "check") : chip("amber", "Waiting for publish", "hourglass")) : statusChip(p.status)}</td>
        <td class="actions">
          ${p.standalone
            ? `<button class="btn small" data-act="usage" data-id="${esc(p.id)}"><i class="ph ph-robot"></i> Setup</button><button class="btn small danger" data-act="undeploy" data-id="${esc(p.id)}"><i class="ph ph-rocket"></i> Undeploy</button>`
            : `<button class="btn small solid" data-act="deploy" data-id="${esc(p.id)}"><i class="ph ph-rocket-launch"></i> Deploy</button>`}
        </td>
      </tr>`).join("")
      : `<tr><td colspan="6">${filter === "deployed"
          ? emptyState("rocket-launch", "No MCP server deployed yet", "Deploy one from a registered backend, or register a new API and deploy it in one go.")
          : emptyState("cube", "Everything is deployed", "Register another backend in the MCP Registry to deploy it here.")}</td></tr>`}
    </table></div></div>
    <div class="callout"><i class="ph ph-info"></i><span>An MCP server here is one backend served on its own address (<span class="mono">/mcp/&lt;id&gt;</span>) with plain tool names: the shape a vendor's own MCP app has in claude.ai or ChatGPT. It runs inside this gateway, so deploying needs no restart, and the same agent tokens, tool policy, company scoping and audit apply. The same backend keeps working on the shared gateway with prefixed names.</span></div>`;

  $("#btn-deploy-new").onclick = () => deployDialog(candidates);
  $("#page").querySelectorAll("tr[data-open]").forEach((tr) => tr.onclick = (e) => {
    if (e.target.closest("button")) return;
    setHash("provider", { p: tr.dataset.open, via: "standalone" });
  });
  $("#page").querySelectorAll("[data-act]").forEach((b) => b.onclick = async () => {
    const { act, id } = b.dataset;
    try {
      if (act === "usage") { setHash("provider", { p: id, c: "chatgpt", via: "standalone" }); return; }
      const r = await api("POST", `/api/registry/${id}/${act}`);
      toast(act === "deploy" ? "MCP server deployed" : "Undeployed",
        act === "deploy" ? `${r.name} now answers at ${r.standalone_url}` : `${r.standalone_url} now returns 404; the shared gateway still serves it`, 6000);
      setHash("servers", { f: "deployed" }); pages.servers();
    } catch (err) { toast("Action failed", err.message, 4500); }
  });
};

/** Pick a registered backend to deploy, or register a new API and deploy it right after. */
function deployDialog(candidates) {
  modal(`<h2><i class="ph ph-rocket-launch"></i> Deploy an MCP server</h2>
    <p class="muted">One product, one server. Pick a backend already registered, or register a new API first and it deploys as soon as it is saved.</p>
    <form id="dp-form" class="form">
      <label class="field">Backend to deploy
        <select name="pid" ${candidates.length ? "" : "disabled"}>
          ${candidates.length ? candidates.map((p) => `<option value="${esc(p.id)}">${esc(p.name)} (${p.kind === "mcp" ? "MCP server" : "REST API"}, ${p.tools_enabled} tools)</option>`).join("") : `<option>Every registered backend is already deployed</option>`}
        </select></label>
      <div class="callout"><i class="ph ph-info"></i><span>It will be served at <span class="mono" id="dp-url">${esc(candidates[0]?.standalone_url || "...")}</span> with plain tool names, and published on the shared gateway if it was still a draft.</span></div>
      <div style="display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap">
        <button type="button" class="btn" id="dp-register"><i class="ph ph-plus"></i> Register a new API instead</button>
        <span style="display:flex;gap:8px"><button type="button" class="btn" id="dp-cancel">Cancel</button><button class="btn solid" type="submit" ${candidates.length ? "" : "disabled"}><i class="ph ph-rocket-launch"></i> Deploy</button></span>
      </div>
      <p class="error" id="dp-error"></p>
    </form>`);
  $("#dp-cancel").onclick = closeModal;
  $("#dp-register").onclick = () => { closeModal(); registerDialog({ deployAfter: true }); };
  $("#dp-form [name=pid]").onchange = (e) => { $("#dp-url").textContent = candidates.find((p) => p.id === e.target.value)?.standalone_url || ""; };
  $("#dp-form").onsubmit = async (e) => {
    e.preventDefault(); const pid = $("#dp-form [name=pid]").value;
    try {
      const r = await api("POST", `/api/registry/${pid}/deploy`);
      closeModal(); toast("MCP server deployed", `${r.name} now answers at ${r.standalone_url}`, 6000);
      setHash("provider", { p: pid, c: "chatgpt", via: "standalone" });
    } catch (err) { $("#dp-error").textContent = err.message; }
  };
}

async function registerDialog(opts = {}) {
  modal(`<h2><i class="ph ph-plus-circle"></i> Register a backend</h2>
    <form id="reg-form" class="form">
      <div class="seg" id="reg-kind" role="radiogroup" aria-label="Backend type">
        <label class="seg-opt"><input type="radio" name="kind" value="openapi" checked><i class="ph ph-cloud"></i><span><strong>REST API</strong><span>Paste its OpenAPI spec. The gateway generates the tools.</span></span></label>
        <label class="seg-opt"><input type="radio" name="kind" value="mcp"><i class="ph ph-plugs-connected"></i><span><strong>Existing MCP server</strong><span>Give its URL. The gateway proxies its tools.</span></span></label>
      </div>
      <label class="field">Provider name <input name="name" placeholder="e.g. Bizplay HR API" required></label>
      <label class="field"><span id="reg-base-label">Base URL of the existing API</span> <input name="base_url" id="reg-base" placeholder="https://api.example.com" required></label>
      <label class="field">MCP endpoint agents will use <input name="mcp_url" value="${esc(SERVER.public_mcp_url || (location.origin + "/mcp"))}" placeholder="https://your-host/mcp">
        <span class="muted small">Any address that reaches this gateway. Use an HTTPS one for claude.ai and ChatGPT.</span></label>
      <label class="field"><span id="reg-mode-label">How is the API protected?</span>
        <select name="auth_mode" id="reg-mode">
          <option value="bearer">Bearer token: it rejects anonymous calls (recommended)</option>
          <option value="network">Network-isolated: no token, only the gateway's address can reach it</option>
          <option value="open">Open: anyone can call it (demo data only, recorded as accepted risk)</option>
          <option value="oauth">OAuth: each user links their own account; the gateway sends that user's token</option>
        </select></label>
      <label class="field" id="reg-token-field">Service bearer token the gateway will send <input name="service_token" placeholder="issued by the provider (stored, never shown again)"></label>
      <label class="field hidden" id="reg-allowlist-field">Gateway address the API allows <input name="allowlist" placeholder="e.g. 203.0.113.10 or 10.0.0.0/24"></label>
      <div class="hidden" id="reg-oauth-fields">${oauthFields("reg")}</div>
      <div class="callout warn hidden" id="reg-open-warning"><i class="ph ph-warning"></i><span><strong>Open backend.</strong> The gateway still authenticates agents, applies tool policy, and limits results to the caller's company, but anyone who knows the URL can bypass it. The overview will show this as an accepted risk.</span></div>
      <label class="field" id="reg-spec-field">OpenAPI spec (JSON) <textarea name="spec" placeholder='{"openapi":"3.0.3","paths":{...}}' required></textarea></label>
      <div class="callout hidden" id="reg-mcp-note"><i class="ph ph-info"></i><span>The portal connects to the server now and reads its tool list. Tools marked read-only by the server start enabled; the rest start off and can be switched on under Access Control.</span></div>
      <div style="display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap">
        <button type="button" class="btn small" id="reg-sample"><i class="ph ph-file-arrow-down"></i> Load Bizplay sample spec</button>
        <span style="display:flex;gap:8px"><button type="button" class="btn" id="reg-cancel">Cancel</button><button class="btn solid" type="submit" id="reg-submit"><i class="ph ph-check"></i> Register as draft</button></span>
      </div>
      <p class="error" id="reg-error"></p>
    </form>`);
  $("#reg-cancel").onclick = closeModal;
  const kindOf = () => $("#reg-form [name=kind]:checked").value;
  $("#reg-kind").onchange = () => {
    const mcp = kindOf() === "mcp";
    $("#reg-base-label").textContent = mcp ? "URL of the MCP server" : "Base URL of the existing API";
    $("#reg-base").placeholder = mcp ? "https://mcp.example.com/mcp" : "https://api.example.com";
    $("#reg-mode-label").textContent = mcp ? "How is the MCP server protected?" : "How is the API protected?";
    $("#reg-spec-field").classList.toggle("hidden", mcp);
    $("#reg-form [name=spec]").required = !mcp;
    $("#reg-mcp-note").classList.toggle("hidden", !mcp);
    $("#reg-sample").classList.toggle("hidden", mcp);
  };
  $("#reg-mode").onchange = (e) => {
    const m = e.target.value;
    $("#reg-token-field").classList.toggle("hidden", m !== "bearer");
    $("#reg-allowlist-field").classList.toggle("hidden", m !== "network");
    $("#reg-open-warning").classList.toggle("hidden", m !== "open");
    $("#reg-oauth-fields").classList.toggle("hidden", m !== "oauth");
  };
  $("#reg-sample").onclick = async () => {
    const r = await fetch("/static/sample-openapi.json"); $("#reg-form [name=spec]").value = await r.text();
    $("#reg-form [name=name]").value ||= "Bizplay Expense API (copy)";
    $("#reg-form [name=base_url]").value ||= "http://127.0.0.1:18080";
    $("#reg-form [name=service_token]").value ||= "demo-service-token";
  };
  $("#reg-form").onsubmit = async (e) => {
    e.preventDefault(); const f = splitOauth(Object.fromEntries(new FormData(e.target)));
    const btn = $("#reg-submit"); btn.disabled = true;
    if (f.kind === "mcp") { delete f.spec; btn.innerHTML = `<i class="ph ph-circle-notch"></i> Reading tools from the server`; }
    try {
      const p = await api("POST", "/api/registry", { ...f, spec_source: "uploaded" });
      toast("Registered as draft", p.kind === "mcp" ? `${p.tool_count} tools read from the MCP server` : `${p.tool_count} tools generated from the spec`);
      if (opts.deployAfter && p.auth_mode !== "bearer") {
        // Came from the MCP Servers page: serve it on its own address right away.
        // Bearer mode needs its service token checked first, so that one goes through the test.
        try {
          const r = await api("POST", `/api/registry/${p.id}/deploy`);
          closeModal(); toast("MCP server deployed", `${r.name} now answers at ${r.standalone_url}`, 6000);
          setHash("provider", { p: p.id, c: "chatgpt", via: "standalone" }); return;
        } catch (err) { toast("Registered, but not deployed", err.message, 6000); }
      }
      if (p.auth_mode === "oauth" && !p.oauth_ready) {
        // Try the server's own metadata before asking anyone to type endpoints.
        try { const d = await api("POST", `/api/registry/${p.id}/oauth/discover`, {}); toast("OAuth endpoints discovered", d.note, 5000); }
        catch (err) { toast("Fill the OAuth endpoints under Edit connection", err.message, 6000); }
        closeModal(); setHash("provider", { p: p.id }); return;
      }
      testDialog(p.id);  // prove the connection now, while the details are fresh
    } catch (err) { $("#reg-error").textContent = err.message; btn.disabled = false; btn.innerHTML = `<i class="ph ph-check"></i> Register as draft`; }
  };
}

/** Ready-to-paste commands. Issues a token first when the gateway needs one. */
function commandResult(p, token, via) {
  const url = via.url;
  const hdr = token ? ` \\\n  --header "Authorization: Bearer ${token}"` : "";
  const plainHttp = url.startsWith("http://") && !LOCAL_HOST.test(hostOf(url));
  const desktop = `"${p.id}": ` + JSON.stringify({
    command: "npx",
    args: ["-y", "mcp-remote", url, "--transport", "http-only",
      ...(plainHttp ? ["--allow-http"] : []),
      ...(token ? ["--header", `Authorization: Bearer ${token}`] : [])],
  }, null, 2);
  modal(`<h2><i class="ph ph-terminal-window"></i> Connect to ${esc(p.name)}</h2>
    <p class="muted">${via.standalone ? `Its own MCP server at <span class="mono">${esc(url)}</span>, tool names without a prefix.` : `The shared gateway at <span class="mono">${esc(url)}</span>, tools named <span class="mono">${esc(via.prefix)}*</span>.`}
    ${token ? `A token was issued for this command. It is shown once, so copy the command now. Revoke it any time on the Agent Tokens page.`
            : `This gateway accepts anonymous callers, so no token is needed.`}</p>
    <h2 class="section-title" style="margin-top:14px">Claude Code, one line</h2>
    ${codeBlock("cc-code", `claude mcp add --transport http ${p.id} ${url}${hdr}`)}
    <h2 class="section-title" style="margin-top:16px">Claude Desktop, add under mcpServers</h2>
    ${codeBlock("cc-desktop", desktop, "Needs Node.js. Restart Claude Desktop from the system tray afterwards.")}
    <h2 class="section-title" style="margin-top:16px">Check it from a terminal</h2>
    ${codeBlock("cc-curl", `curl -s ${url} \\\n  -H "Accept: application/json, text/event-stream" \\\n  -H "Content-Type: application/json"${token ? ` \\\n  -H "Authorization: Bearer ${token}"` : ""} \\\n  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'`)}
    <div style="display:flex;justify-content:flex-end;margin-top:14px"><button class="btn solid" id="cc-done">Done</button></div>`);
  $("#cc-done").onclick = () => { closeModal(); pages.provider(); };
}

async function commandDialog(p, via) {
  if (SERVER.require_agent_token === false) return commandResult(p, null, via);
  modal(`<h2><i class="ph ph-terminal-window"></i> Connect command</h2>
    <p class="muted">Who should the agent act as? A token is issued for this command.</p>
    <form id="cc-form" class="form">
      <div class="form-2">
        <label class="field">Bizplay user id <input name="user_id" value="emp001" required></label>
        <label class="field">Role <select name="role"><option value="employee">employee</option><option value="manager">manager</option></select></label>
        <label class="field">Company <input name="company" value="1078836129"></label>
        <label class="field">Expires in (days) <input name="ttl_days" type="number" value="30" min="1" max="365"></label>
      </div>
      <div style="display:flex;justify-content:flex-end;gap:8px"><button type="button" class="btn" id="cc-cancel">Cancel</button><button class="btn solid" type="submit"><i class="ph ph-check"></i> Create command</button></div>
      <p class="error" id="cc-error"></p>
    </form>`);
  $("#cc-cancel").onclick = closeModal;
  $("#cc-form").onsubmit = async (e) => {
    e.preventDefault(); const f = Object.fromEntries(new FormData(e.target));
    try {
      const r = await api("POST", "/api/tokens", { ...f, label: `${p.name} connect command`, agent: "Claude Code" });
      commandResult(p, r.token, via);
    } catch (err) { $("#cc-error").textContent = err.message; }
  };
}

async function editDialog(p) {
  const opt = (v, label) => `<option value="${v}" ${p.auth_mode === v ? "selected" : ""}>${label}</option>`;
  modal(`<h2><i class="ph ph-pencil-simple"></i> Edit connection</h2>
    <form id="ed-form" class="form">
      <label class="field">Provider name <input name="name" value="${esc(p.name)}"></label>
      <label class="field">${p.kind === "mcp" ? "URL of the MCP server" : "Base URL of the existing API"} <input name="base_url" value="${esc(p.base_url)}">
        <span class="muted small">${p.kind === "mcp" ? "Saving reconnects and refreshes the tool list; your enable, role and confirm settings are kept." : "Host only. The paths come from the spec, so a base URL ending in a path the spec also has causes 404."}</span></label>
      <label class="field">MCP endpoint agents will use <input name="mcp_url" value="${esc(p.mcp_url)}">
        <span class="muted small">Use the address reachable from outside this server, not 127.0.0.1. A deployed server lives at this address plus /${esc(p.id)}.</span></label>
      <label class="field">How is the ${p.kind === "mcp" ? "MCP server" : "API"} protected?
        <select name="auth_mode" id="ed-mode">
          ${opt("bearer", "Bearer token: the API rejects anonymous calls")}
          ${opt("network", "Network-isolated: no token, only the gateway's address can reach it")}
          ${opt("open", "Open: anyone can call it (demo data only, recorded as accepted risk)")}
          ${opt("oauth", "OAuth: each user links their own account; the gateway sends that user's token")}
        </select></label>
      <label class="field ${p.auth_mode === "bearer" ? "" : "hidden"}" id="ed-token-field">Service bearer token <input name="service_token" placeholder="leave blank to keep the stored one"></label>
      <label class="field ${p.auth_mode === "network" ? "" : "hidden"}" id="ed-allowlist-field">Gateway address the API allows <input name="allowlist" value="${esc(p.allowlist || "")}" placeholder="e.g. 203.0.113.10"></label>
      <div class="${p.auth_mode === "oauth" ? "" : "hidden"}" id="ed-oauth-fields">${oauthFields("ed", p.oauth || {})}</div>
      <div style="display:flex;justify-content:flex-end;gap:8px"><button type="button" class="btn" id="ed-cancel">Cancel</button><button class="btn solid" type="submit"><i class="ph ph-check"></i> Save</button></div>
      <p class="error" id="ed-error"></p>
    </form>`);
  $("#ed-cancel").onclick = closeModal;
  $("#ed-mode").onchange = (e) => {
    $("#ed-token-field").classList.toggle("hidden", e.target.value !== "bearer");
    $("#ed-allowlist-field").classList.toggle("hidden", e.target.value !== "network");
    $("#ed-oauth-fields").classList.toggle("hidden", e.target.value !== "oauth");
  };
  $("#ed-form").onsubmit = async (e) => {
    e.preventDefault(); const f = splitOauth(Object.fromEntries(new FormData(e.target)));
    try {
      const r = await api("PATCH", `/api/registry/${p.id}`, f);
      closeModal(); toast("Connection updated", r.note || `${r.name} now points at ${r.base_url}`, r.note ? 6000 : 3000);
      pages.provider();
    } catch (err) { $("#ed-error").textContent = err.message; }
  };
}

async function testDialog(id) {
  modal(`<h2><i class="ph ph-plugs"></i> Connection test: ${esc(id)}</h2>${SKELETON}`);
  try {
    const r = await api("POST", `/api/registry/${id}/test`);
    const p = (await api("GET", "/api/registry")).items.find((x) => x.id === id) || {};
    // The most common registration mistake: an open API registered as bearer.
    const answersAnonymously = r.results.some((x) => x.check.includes("rejects missing token") && x.status === 200);
    const suggestOpen = p.auth_mode === "bearer" && answersAnonymously;
    modal(`<h2><i class="ph ph-plugs"></i> Connection test: ${esc(id)} ${passChip(r.ok)}</h2>
      ${suggestOpen ? `<div class="callout warn" style="margin-bottom:12px"><i class="ph ph-warning"></i><span><strong>This API answers without a token.</strong> It is registered as Bearer, which means "rejects anonymous calls", so the test fails and publishing is blocked. Switch it to Open if that is how the API is meant to work.</span></div>` : ""}
      <div class="table-card"><div class="table-wrap"><table><tr><th>Check</th><th>Path</th><th>HTTP</th><th>Result</th></tr>
      ${r.results.map((x) => `<tr><td>${esc(x.check)}</td><td class="mono">${esc(x.path)}</td><td class="mono">${x.status ?? "n/a"}</td><td>${passChip(x.ok)}${x.error ? `<div class="muted small">${esc(x.error)}</div>` : ""}${x.note ? `<div class="muted small">${esc(x.note)}</div>` : ""}</td></tr>`).join("")}</table></div></div>
      <p class="muted small" style="margin-top:12px">In bearer mode a failing "rejects missing token" check blocks publishing. In open mode the API is public by decision and the gateway carries all the enforcement.</p>
      <div style="display:flex;justify-content:${suggestOpen ? "space-between" : "flex-end"};gap:8px;margin-top:8px">
        ${suggestOpen ? `<button class="btn solid" id="t-open"><i class="ph ph-lock-open"></i> Switch to Open mode</button>` : ""}
        <button class="btn" id="t-close">Close</button></div>`);
    $("#t-close").onclick = () => { closeModal(); pages.registry(); };
    if (suggestOpen) {
      $("#t-open").onclick = async () => {
        try { await api("PATCH", `/api/registry/${id}`, { auth_mode: "open" }); toast("Switched to Open mode", "Recorded as an accepted risk"); testDialog(id); }
        catch (err) { toast("Could not switch", err.message, 4500); }
      };
    }
  } catch (err) { modal(`<h2>Connection test</h2><p class="error">${esc(err.message)}</p>`); }
}

// ---- Access control ----
pages.access = async () => {
  const reg = await api("GET", "/api/registry");
  const wanted = hashParam("p");
  const pid = reg.items.some((p) => p.id === wanted) ? wanted : (reg.items[0]?.id || "bizplay");
  const d = await api("GET", `/api/registry/${pid}/tools`);
  const total = d.items.length, enabled = d.items.filter((t) => t.enabled).length;
  const reads = d.items.filter((t) => t.kind === "read").length, writes = total - reads;
  const provider = reg.items.find((p) => p.id === pid) || {};
  const access = provider.access || { mode: "everyone", groups: [], companies: [] };
  const known = (await api("GET", "/api/groups")).items;
  renderTabs(reg.items.map((p) => ({ key: p.id, label: p.name, icon: "plugs-connected", count: p.tools_enabled })), pid,
    (k) => { setHash("access", { p: k }); pages.access(); });

  const whoLabel = access.mode === "groups" ? `groups: ${access.groups.join(", ")}` : access.mode === "companies" ? `companies: ${access.companies.join(", ")}` : "everyone with a token";
  $("#page").innerHTML = `
    <div class="stats">
      <div class="stat"><span class="num">${total}</span><span class="lbl">Endpoints in this API</span></div>
      <div class="stat"><span class="num" style="color:var(--green-ink)">${enabled}</span><span class="lbl">Enabled for agents</span></div>
      <div class="stat"><span class="num">${reads}</span><span class="lbl">Read tools</span></div>
      <div class="stat"><span class="num" style="color:var(--amber-ink)">${writes}</span><span class="lbl">Write tools, ${d.items.filter((t) => t.kind === "write" && t.enabled).length} enabled</span></div>
    </div>
    <div>
      <div class="section-head"><h2 class="section-title">Who can use ${esc(provider.name || pid)}</h2>${access.mode === "everyone" ? chip("", "Everyone", "users") : chip("lilac", whoLabel, "users-three")}</div>
      <div class="card settings-list" id="access-card">
        <div class="setting"><div class="setting-text"><strong>Entitlement</strong><p class="muted small">Decides which callers see this backend at all on the gateway address. Everyone else gets no tools from it and is refused if they try. Tool policy below applies on top.</p></div>
          <div class="setting-ctl"><select id="acc-mode" aria-label="Who can use this backend">
            <option value="everyone" ${access.mode === "everyone" ? "selected" : ""}>Everyone with a token</option>
            <option value="groups" ${access.mode === "groups" ? "selected" : ""}>Only these access groups</option>
            <option value="companies" ${access.mode === "companies" ? "selected" : ""}>Only these companies</option>
          </select></div></div>
        <div class="setting ${access.mode === "groups" ? "" : "hidden"}" id="acc-groups-row"><div class="setting-text"><strong>Access groups</strong><p class="muted small">Comma separated. A caller needs any one of them on their agent token${known.length ? `. In use: ${esc(known.join(", "))}` : ""}.</p></div>
          <div class="setting-ctl"><input id="acc-groups" class="ctl-wide" value="${esc(access.groups.join(", "))}" placeholder="finance, hr" list="acc-known"><datalist id="acc-known">${known.map((g) => `<option value="${esc(g)}">`).join("")}</datalist></div></div>
        <div class="setting ${access.mode === "companies" ? "" : "hidden"}" id="acc-companies-row"><div class="setting-text"><strong>Companies</strong><p class="muted small">Comma separated company ids, matched against the company on the caller's token.</p></div>
          <div class="setting-ctl"><input id="acc-companies" class="ctl-wide" value="${esc(access.companies.join(", "))}" placeholder="1078836129, 2200000000"></div></div>
        <div class="setting"><div class="setting-text"><p class="muted small" style="margin:0">Applies on the next call, on the shared gateway and on this backend's own MCP server alike.</p></div>
          <div class="setting-ctl"><button class="btn solid small" id="acc-save"><i class="ph ph-check"></i> Save entitlement</button></div></div>
      </div>
    </div>
    <div>
      <h2 class="section-title">Tool policy</h2>
      <div class="table-card"><div class="table-wrap"><table><tr><th>Tool</th><th>Kind</th><th>Enabled</th><th>Allowed roles</th><th>Confirm before call</th></tr>
      ${d.items.map((t) => `<tr data-name="${esc(t.name)}">
        <td><span class="mono">${esc(t.name)}</span>${t.summary ? `<div class="muted small">${esc(t.summary)}</div>` : ""}${t.route ? `<div class="muted small mono">${esc(t.route)}</div>` : ""}</td>
        <td>${t.kind === "write" ? chip("amber", "write", "pencil-simple") : chip("lilac", "read", "eye")}</td>
        <td><input type="checkbox" class="switch" data-k="enabled" ${t.enabled ? "checked" : ""} aria-label="Enabled"></td>
        <td>${d.roles.map((r) => `<label class="check"><input type="checkbox" data-k="role" value="${r}" ${t.roles.includes(r) ? "checked" : ""}>${r}</label>`).join(" ")}</td>
        <td><input type="checkbox" class="switch" data-k="confirm" ${t.confirm ? "checked" : ""} ${t.kind === "read" ? "disabled" : ""} aria-label="Confirm before call"></td>
      </tr>`).join("")}</table></div></div>
    </div>
    <div class="callout"><i class="ph ph-shield-check"></i><span>Changes apply to the gateway on the next call. The gateway also checks that the role inside the agent token matches the provider's own record and limits results to the caller's company.</span></div>`;

  $("#acc-mode").onchange = (e) => {
    $("#acc-groups-row").classList.toggle("hidden", e.target.value !== "groups");
    $("#acc-companies-row").classList.toggle("hidden", e.target.value !== "companies");
  };
  $("#acc-save").onclick = async () => {
    try {
      const r = await api("PATCH", `/api/registry/${pid}`, { access: { mode: $("#acc-mode").value, groups: $("#acc-groups").value, companies: $("#acc-companies").value } });
      toast("Entitlement saved", r.access.mode === "everyone" ? "Everyone with a token can use it" : `Limited to ${r.access.mode}: ${(r.access[r.access.mode] || []).join(", ")}`);
      pages.access();
    } catch (err) { toast("Save failed", err.message, 4500); }
  };
  $("#page").querySelectorAll("tr[data-name] input").forEach((inp) => inp.onchange = async () => {
    const tr = inp.closest("tr"); const name = tr.dataset.name;
    const body = {
      enabled: tr.querySelector('[data-k=enabled]').checked,
      confirm: tr.querySelector('[data-k=confirm]').checked,
      roles: [...tr.querySelectorAll('[data-k=role]:checked')].map((x) => x.value),
    };
    try { await api("PUT", `/api/registry/${pid}/tools/${name}`, body); toast("Policy saved", name); }
    catch (err) { toast("Save failed", err.message, 4500); }
  });
};

// ---- Agent tokens ----
pages.tokens = async () => {
  const d = await api("GET", "/api/tokens");
  const alive = (t) => !t.revoked && t.expires_at > d.now;
  const state = (t) => t.revoked ? "revoked" : alive(t) ? "active" : "expired";
  const filter = hashParam("f") || "active";
  const items = d.items.filter((t) => filter === "all" || state(t) === filter);
  renderTabs([
    { key: "active", label: "Active", icon: "key", count: d.items.filter((t) => state(t) === "active").length },
    { key: "revoked", label: "Revoked", icon: "prohibit", count: d.items.filter((t) => state(t) === "revoked").length },
    { key: "expired", label: "Expired", icon: "hourglass", count: d.items.filter((t) => state(t) === "expired").length },
    { key: "all", label: "All", icon: "squares-four", count: d.items.length },
  ], filter, (k) => { setHash("tokens", { f: k }); pages.tokens(); });

  pageActions(`<button class="btn solid" id="btn-issue"><i class="ph ph-plus"></i> Issue token</button>`);
  const stateChip = { active: chip("green", "Active", "check"), revoked: chip("red", "Revoked", "prohibit"), expired: chip("amber", "Expired", "hourglass") };
  $("#page").innerHTML = `
    <div class="table-card"><div class="table-wrap"><table>
      <tr><th>Token</th><th>Bizplay user</th><th>Company</th><th>Status</th><th>Expires</th><th>Last used</th><th></th></tr>
      ${items.length ? items.map((t, i) => `<tr title="Issued by ${esc(t.created_by)}">
        <td><span class="name">${logo(t.agent, i)} <span>${esc(t.label)}<div class="sub"><span class="mono">${esc(t.hint)}</span> · ${esc(t.agent)}</div></span></span></td>
        <td class="nowrap"><span class="mono">${esc(t.sub)}</span><div class="sub">${esc(t.role)}${(t.groups || []).length ? ` · ${esc(t.groups.join(", "))}` : ""}</div></td>
        <td class="small">${esc(t.company)}</td>
        <td>${stateChip[state(t)]}</td>
        <td class="small nowrap">${esc(fmtDate(t.expires_at))}</td>
        <td class="small nowrap">${t.last_used_at ? esc(fmtTs(t.last_used_at)) : "never"}</td>
        <td class="actions">${alive(t) ? `<button class="btn small danger" data-revoke="${esc(t.id)}"><i class="ph ph-prohibit"></i> Revoke</button>` : ""}</td>
      </tr>`).join("")
      : `<tr><td colspan="7">${emptyState("key", "No tokens here", "Issue one to connect an AI agent to the gateway over HTTP.")}</td></tr>`}
    </table></div></div>`;
  $("#btn-issue").onclick = issueDialog;
  $("#page").querySelectorAll("[data-revoke]").forEach((b) => b.onclick = async () => {
    if (!confirm("Revoke this token? The agent loses access immediately.")) return;
    try { await api("POST", `/api/tokens/${b.dataset.revoke}/revoke`); toast("Token revoked", "The agent can no longer call the gateway"); pages.tokens(); } catch (err) { toast("Revoke failed", err.message, 4500); }
  });
};

async function issueDialog() {
  modal(`<h2><i class="ph ph-key"></i> Issue an agent token</h2>
    <form id="tok-form" class="form">
      <label class="field">Label <input name="label" placeholder="Minji's Claude Desktop" required></label>
      <div class="form-2">
        <label class="field">Bizplay user id <input name="user_id" value="emp001" required></label>
        <label class="field">Role <select name="role"><option value="employee">employee</option><option value="manager">manager</option></select></label>
        <label class="field">Company <input name="company" value="Bizplay Demo Co."></label>
        <label class="field">Access groups <input name="groups" placeholder="finance, hr (comma separated)"><span class="muted small">Backends limited to groups are visible only to tokens that carry one of them.</span></label>
        <label class="field">AI agent <select name="agent"><option>Claude Desktop</option><option>Claude.ai</option><option>Microsoft Copilot Studio</option><option>Salesforce Agentforce</option></select></label>
        <label class="field">Expires in (days) <input name="ttl_days" type="number" value="30" min="1" max="365"></label>
      </div>
      <p class="muted small">The gateway rejects the token if its role differs from the provider's record for this user. Demo users: emp001 and emp002 (employee), mgr001 (manager).</p>
      <div style="display:flex;justify-content:flex-end;gap:8px"><button type="button" class="btn" id="tok-cancel">Cancel</button><button class="btn solid" type="submit"><i class="ph ph-check"></i> Issue</button></div>
      <p class="error" id="tok-error"></p></form>`);
  $("#tok-cancel").onclick = closeModal;
  $("#tok-form").onsubmit = async (e) => {
    e.preventDefault(); const f = Object.fromEntries(new FormData(e.target));
    try {
      const r = await api("POST", "/api/tokens", f);
      modal(`<h2><i class="ph ph-check-circle"></i> Token issued</h2><p>Copy it now. It will not be shown again.</p>
        <div class="token-box"><code id="tok-value">${esc(r.token)}</code><button class="btn small" id="tok-copy"><i class="ph ph-copy"></i> Copy</button></div>
        <h2 class="section-title" style="margin-top:16px">Use it from any MCP client</h2>
        <pre>URL:    http://127.0.0.1:8000/mcp
Header: Authorization: Bearer ${esc(r.token)}</pre>
        <p class="muted small" style="margin-top:8px">Bound to ${esc(r.record.sub)} (${esc(r.record.role)}), expires ${esc(fmtTs(r.record.expires_at))}.</p>
        <div style="display:flex;justify-content:space-between;gap:8px;margin-top:8px"><button class="btn" id="tok-connect"><i class="ph ph-robot"></i> Setup instructions</button><button class="btn solid" id="tok-done">Done</button></div>`);
      $("#tok-connect").onclick = () => { closeModal(); location.hash = "registry"; toast("Pick an API", "Open How to use it on the API you want to connect"); };
      $("#tok-copy").onclick = () => navigator.clipboard?.writeText(r.token).then(() => toast("Copied", "Token is on your clipboard"));
      $("#tok-done").onclick = () => { closeModal(); pages.tokens(); };
    } catch (err) { $("#tok-error").textContent = err.message; }
  };
}

// ---- Registered API detail: how to use this one API ----
// Filled from /api/config at sign-in: the server knows where it keeps the project.
let SERVER = { project_dir: "/path/to/bizplay-mcp-server", require_agent_token: true };
const LOCAL_HOST = /^(127\.|localhost$|::1$|0\.0\.0\.0$)/;
const hostOf = (url) => { try { return new URL(url).hostname; } catch { return ""; } };

function codeBlock(id, text, note) {
  return `<div class="code-block"><button class="btn small copy" data-copy="${id}"><i class="ph ph-copy"></i> Copy</button><pre id="${id}">${esc(text)}</pre>${note ? `<p class="muted small" style="margin:8px 0 0">${note}</p>` : ""}</div>`;
}

const portOf = (url) => (String(url).match(/:(\d+)/) || [, "8002"])[1];

/** Where an agent connects: the shared gateway (prefixed tools) or this provider's own server. */
function connectVia(p) {
  const standalone = p.standalone && hashParam("via") === "standalone";
  return standalone
    ? { url: p.standalone_url, prefix: "", standalone: true, label: "its own MCP server" }
    : { url: p.mcp_url, prefix: p.tool_prefix || "", standalone: false, label: "the shared gateway" };
}

/** Setup guides written for one registered API: its endpoint, prefix and a real tool of its own. */
function clientGuides(p, tools, via) {
  const url = via.url;
  const enabled = tools.filter((t) => t.enabled);
  const sample = enabled.find((t) => t.kind === "read") || enabled[0];
  const toolName = sample ? `${via.prefix}${sample.name}` : "a_tool_name";
  const sampleArgs = sample && /\{corpNo\}/.test(sample.route || "") ? `{"corpNo": "1078836129"}` : "{}";
  const port = portOf(url);
  const localModule = p.has_spec || p.kind === "mcp" ? "bizplay_mcp.registry_gateway" : "bizplay_mcp.server";
  const env = p.has_spec || p.kind === "mcp"
    ? { BIZPLAY_USER_ID: "emp001", BIZPLAY_ROLE: "employee", BIZPLAY_COMPANY: "1078836129", FASTMCP_SHOW_SERVER_BANNER: "false" }
    : { BIZPLAY_API_BASE_URL: "embedded", BIZPLAY_USER_ID: "emp001", FASTMCP_SHOW_SERVER_BANNER: "false" };
  const desktopCfg = `"${p.id}": ` + JSON.stringify({
    command: "uv",
    args: ["--directory", SERVER.project_dir, "run", "--no-sync", "python", "-m", localModule],
    env,
  }, null, 2);
  // With the agent-token requirement switched off there is no header to send.
  const needsToken = SERVER.require_agent_token !== false;
  // mcp-remote refuses plain HTTP to anything but localhost without --allow-http.
  const plainHttpRemote = url.startsWith("http://") && !LOCAL_HOST.test(hostOf(url));
  const remoteArgs = ["-y", "mcp-remote", url, "--transport", "http-only",
    ...(plainHttpRemote ? ["--allow-http"] : []),
    ...(needsToken ? ["--header", "Authorization: Bearer <YOUR_AGENT_TOKEN>"] : [])];
  const remoteCfg = `"${p.id}": ` + JSON.stringify({ command: "npx", args: remoteArgs }, null, 2);
  const headerArg = needsToken ? ` \\\n  --header "Authorization: Bearer <YOUR_AGENT_TOKEN>"` : "";
  const endpointIsLocal = LOCAL_HOST.test(hostOf(url));
  const what = via.standalone ? `this server` : `this gateway`;

  return {
    "claude-desktop": {
      label: "Claude Desktop", icon: "desktop", ready: true,
      lead: `Claude Desktop runs on your own machine, so it either connects to ${what} over the network or starts its own copy locally. Pick one of the two entries below.`,
      steps: [
        { t: "Open the config file", b: `<p>Windows: <span class="mono">%APPDATA%\\Claude\\claude_desktop_config.json</span><br>macOS: <span class="mono">~/Library/Application Support/Claude/claude_desktop_config.json</span></p>` },
        { t: `Option A, connect to ${what}${endpointIsLocal ? "" : " (recommended)"}`,
          b: codeBlock("g-remote", remoteCfg, endpointIsLocal
            ? "This endpoint is 127.0.0.1, so it only works if Claude Desktop runs on the same machine as the gateway. Use Edit connection to set the address other machines can reach."
            : "Needs Node.js. Issue a token on the Agent Tokens page and paste it in place of the placeholder.") },
        { t: "Option B, run a local copy instead",
          b: codeBlock("g-desktop", desktopCfg, `Replace the directory with the path to the project on the machine running Claude Desktop. This value is where the portal's own server keeps it. No agent token is needed, because identity comes from the config.${via.standalone ? " A local copy serves every published backend with prefixed names, since only the HTTP endpoint is per provider." : ""}`) },
        { t: "Quit Claude Desktop from the system tray, then reopen", b: `<p>Closing the window is not enough. The tools appear in the tools menu of a new chat.</p>` },
        { t: "Try it", b: `<p>Ask for something this API covers, for example a call to <span class="mono">${esc(toolName)}</span>.</p>` },
      ],
    },
    "claude-code": {
      label: "Claude Code", icon: "terminal-window", ready: true,
      lead: needsToken
        ? `Claude Code calls this API over HTTP at ${url} and sends an agent token as a header. Use Connect command above to get a line with the token already in it.`
        : `${what[0].toUpperCase() + what.slice(1)} accepts anonymous callers, so one line with no token connects Claude Code to ${url}.`,
      steps: [
        { t: "Add the server", b: codeBlock("g-code-1", `claude mcp add --transport http ${p.id} ${url}${headerArg}`,
          needsToken ? "The token is shown once, when issued. Its user, role and company decide what this API returns."
                     : "No credential is required because the agent-token requirement is switched off on the Security page.") },
        { t: "Check it connected", b: codeBlock("g-code-2", `claude mcp list`) },
        { t: "Remove it later", b: codeBlock("g-code-3", `claude mcp remove ${p.id}`) },
      ],
    },
    "any-mcp": {
      label: "Any MCP client", icon: "plugs-connected", ready: true,
      lead: `Any client that speaks MCP over HTTP can use this API. It needs the endpoint and an Authorization header.`,
      steps: [
        { t: "Connection details", b: `<dl class="kv"><dt>Endpoint</dt><dd>${esc(url)}</dd><dt>Transport</dt><dd>streamable HTTP</dd><dt>Header</dt><dd>Authorization: Bearer &lt;token&gt;</dd><dt>Tool names</dt><dd>${esc(via.prefix ? via.prefix + "*" : "no prefix")}</dd></dl>` },
        { t: "Python, with the FastMCP client", b: codeBlock("g-py", `from fastmcp import Client\nfrom fastmcp.client.transports import StreamableHttpTransport\n\nclient = Client(StreamableHttpTransport(\n    "${url}", auth="<YOUR_AGENT_TOKEN>"))\n\nasync with client as c:\n    tools = await c.list_tools()\n    result = await c.call_tool("${toolName}", ${sampleArgs})`) },
        { t: "Raw HTTP, to check the token", b: codeBlock("g-curl", `curl -s ${url} \\\n  -H "Authorization: Bearer <YOUR_AGENT_TOKEN>" \\\n  -H "Accept: application/json, text/event-stream" \\\n  -H "Content-Type: application/json" \\\n  -d '{"jsonrpc":"2.0","id":1,"method":"initialize",\n       "params":{"protocolVersion":"2025-06-18","capabilities":{},\n                 "clientInfo":{"name":"curl","version":"0"}}}'`, "Without the header this returns 401. That is the gateway refusing an unauthenticated agent.") },
      ],
    },
    "chatgpt": (() => {
      const isHttps = url.startsWith("https://");
      const ready = isHttps && !needsToken;
      const addSteps = [
        { t: "Copy this endpoint", b: codeBlock("g-url", url, via.standalone ? `This exact URL. It serves only ${esc(p.name)}, so the connector shows this one product, the way a vendor's own MCP app does.` : "This exact URL, including the /mcp path. The root path serves nothing and shows Not found.") },
        { t: "Add it in claude.ai", b: `<p>Settings, then Connectors, then Add custom connector. Paste the URL, give it a name, and click Add. It appears in the chat's tool menu.</p>` },
        { t: "Add it in ChatGPT", b: `<p>Settings, then Connectors, then Add. Paste the same URL. Requires a plan that allows custom connectors.</p>` },
        { t: "Ask for something", b: `<p class="mono">List the corporations I can see.</p><p class="mono">What classification rules does my company have?</p>` },
      ];
      if (ready) {
        return { label: "ChatGPT and Claude.ai", icon: "globe", ready: true,
          lead: `This endpoint is public HTTPS and needs no sign-in, so both products can connect to it directly.`,
          steps: addSteps };
      }
      return {
        label: "ChatGPT and Claude.ai", icon: "globe", ready: false,
        lead: isHttps
          ? `The address is fine, but this gateway requires an agent token and these products have no field for one. Turn the requirement off on the Security page for a demo, or add OAuth.`
          : `These products refuse plain HTTP. Give the gateway an HTTPS address first, then add it the same way.`,
        steps: [
          ...(isHttps ? [] : [{ t: "Put HTTPS in front of it", b:
            `<p>Quickest for a demo, a Cloudflare quick tunnel on the server:</p>
             ${codeBlock("g-tunnel", `docker run -d --restart unless-stopped --name mcp-tunnel --network host \\\n  cloudflare/cloudflared:latest tunnel --no-autoupdate --url http://localhost:${port}\n\ndocker logs mcp-tunnel 2>&1 | grep -o 'https://[a-z0-9-]*\\.trycloudflare\\.com'`,
             "The printed address plus /mcp is the connector URL. It changes every restart and is open to anyone who has it. For a stable URL, terminate TLS with nginx and proxy to this port, with proxy_buffering off.")}
             <p class="muted small" style="margin-top:8px">Then set that address here with Edit connection, so these instructions and any new tokens use it.</p>` }]),
          ...(needsToken ? [{ t: "Allow connections without a token", b:
            `<p>These products sign in with OAuth and cannot send a static token. For a demo, switch off the agent token requirement on the Security page and restart the gateways. For production, add an OAuth provider instead.</p>` }] : []),
          ...addSteps,
        ],
      };
    })(),
    "enterprise": {
      label: "Copilot Studio and Agentforce", icon: "buildings", ready: false,
      lead: `Both support remote MCP servers and need the same public HTTPS address and OAuth login as the cloud chat products.`,
      steps: [
        { t: "Microsoft Copilot Studio", b: `<p>Add the gateway as a custom connector, point it at ${esc(url)} on its public address, then enable it as a tool for the agent.</p>` },
        { t: "Salesforce Agentforce", b: `<p>Register the endpoint in the Agentforce MCP registry, then grant the agent access to the tools you enabled for this API.</p>` },
        { t: "What to prepare", b: `<p>A hosted gateway with a certificate, OAuth mapped to the customer's identity provider, and an agent token policy per company. The Security page tracks what is still open.</p>` },
      ],
    },
  };
}

/** Link one user's account on an OAuth backend: the auth server opens in a new tab and sends the user back here. */
async function connectDialog(p) {
  modal(`<h2><i class="ph ph-user-circle-plus"></i> Connect an account on ${esc(p.name)}</h2>
    <p class="muted">The user signs in at ${esc(hostOf(p.oauth?.authorization_url) || "the backend's auth server")} in a new tab. Their tokens are kept by the gateway and used only for their own calls.</p>
    <form id="cn-form" class="form">
      <label class="field">Bizplay user id this account belongs to <input name="user_id" value="emp001" required>
        <span class="muted small">The identity agents call with: the user id on the agent token, or BIZPLAY_USER_ID when tokens are off.</span></label>
      <div style="display:flex;justify-content:flex-end;gap:8px"><button type="button" class="btn" id="cn-cancel">Cancel</button><button class="btn solid" type="submit"><i class="ph ph-arrow-square-out"></i> Open sign-in</button></div>
      <p class="error" id="cn-error"></p>
    </form>`);
  $("#cn-cancel").onclick = closeModal;
  $("#cn-form").onsubmit = async (e) => {
    e.preventDefault(); const f = Object.fromEntries(new FormData(e.target));
    try {
      const r = await api("POST", `/api/registry/${p.id}/oauth/start`, f);
      const win = window.open(r.authorization_url, "_blank");
      modal(`<h2><i class="ph ph-hourglass"></i> Waiting for ${esc(f.user_id)} to sign in</h2>
        <p class="muted">A sign-in tab was opened. When it finishes, it returns to this portal and the account appears under Connected accounts.</p>
        ${win ? "" : `<p class="error">The browser blocked the pop-up. Open this address instead:</p>${codeBlock("cn-url", r.authorization_url)}`}
        <div style="display:flex;justify-content:flex-end"><button class="btn" id="cn-done">Close</button></div>`);
      $("#cn-done").onclick = () => { closeModal(); pages.provider(); };
    } catch (err) { $("#cn-error").textContent = err.message; }
  };
}

/** The Connected accounts card for an OAuth backend. */
function connectionsCard(p, conns) {
  const cfg = p.oauth || {};
  return `
    <div class="card">
      <div class="card-head">
        <span class="card-brand"><span class="logo ${p.oauth_ready ? "green" : "amber"}"><i class="ph ph-user-circle"></i></span> Connected accounts</span>
        ${p.oauth_ready ? chip("green", "Auth server configured", "check") : chip("amber", "Auth server not configured", "warning")}
      </div>
      <div class="tiles" style="grid-template-columns:2fr 1fr 1fr">
        ${tile("globe", "Auth server", hostOf(cfg.authorization_url) || "not set", true)}
        ${tile("identification-card", "Client id", cfg.client_id || "not set", true)}
        ${tile("users", "Linked users", String(conns.length))}
      </div>
      <p class="card-desc" style="-webkit-line-clamp:4">This backend wants each user's own token from its auth server. The AI client never sees that server: a user links their account here once, the gateway keeps the refresh token and attaches the right access token to that user's calls. A caller without a linked account gets a message telling them to connect it.</p>
      ${conns.length ? `<div class="table-wrap"><table><tr><th>User</th><th>Linked</th><th>Token expires</th><th>Scope</th><th></th></tr>
        ${conns.map((c) => `<tr><td class="mono">${esc(c.user_id)}</td><td class="small">${esc(fmtTs(c.connected_at))}</td><td class="small">${c.expires_at ? esc(fmtTs(c.expires_at)) + (c.can_refresh ? " (auto-refresh)" : "") : "never"}</td><td class="small mono">${esc(c.scope || "")}</td><td><button class="btn small danger" data-disconnect="${esc(c.user_id)}"><i class="ph ph-link-break"></i> Disconnect</button></td></tr>`).join("")}
        </table></div>` : `<p class="muted small">No accounts linked yet.</p>`}
      <div class="card-actions">
        <button class="btn small solid" data-act="connect" ${p.oauth_ready ? "" : "disabled"}><i class="ph ph-user-circle-plus"></i> Connect account</button>
        <button class="btn small" data-act="discover"><i class="ph ph-magnifying-glass"></i> ${cfg.client_id ? "Re-discover endpoints" : "Discover and register client"}</button>
        ${p.kind === "mcp" ? `<button class="btn small" data-act="refresh-tools" ${conns.length ? "" : "disabled"}><i class="ph ph-arrows-clockwise"></i> Refresh tools</button>` : ""}
      </div>
    </div>`;
}

pages.provider = async () => {
  const pid = hashParam("p");
  if (hashParam("connected")) { toast("Account linked", `${hashParam("connected")} can now use this backend`, 5000); setHash("provider", { p: pid }); return; }
  if (hashParam("oauth_error")) { toast("Sign-in failed", hashParam("oauth_error"), 7000); setHash("provider", { p: pid }); return; }
  const reg = await api("GET", "/api/registry");
  const p = reg.items.find((x) => x.id === pid);
  if (!p) {
    $("#page").innerHTML = `<div class="card">${emptyState("plugs", "API not found", "It may have been deleted. Open the registry to see what is registered.")}
      <div style="text-align:center"><button class="btn" onclick="location.hash='registry'">Back to registry</button></div></div>`;
    return;
  }
  const d = await api("GET", `/api/registry/${pid}/tools`);
  const conns = p.auth_mode === "oauth" ? (await api("GET", `/api/registry/${pid}/connections`)).items : [];
  const tools = d.items, enabled = tools.filter((t) => t.enabled);
  const via = connectVia(p);
  const guides = clientGuides(p, tools, via);
  const key = guides[hashParam("c")] ? hashParam("c") : "claude-desktop";
  const g = guides[key];
  const canDeploy = p.has_spec || p.kind === "mcp";
  $("#page-title").textContent = p.name;
  crumbs({ page: "registry", label: "MCP Registry" }, { page: "provider", label: p.name });
  pageActions(`<button class="btn" id="head-back"><i class="ph ph-arrow-left"></i> All backends</button><button class="btn solid" id="head-command"><i class="ph ph-terminal-window"></i> Connect command</button>`);
  $("#head-back").onclick = () => { location.hash = "registry"; };
  renderTabs(Object.entries(guides).map(([k, v]) => ({ key: k, label: v.label, icon: v.icon })), key,
    (k) => { setHash("provider", { p: pid, c: k, ...(via.standalone ? { via: "standalone" } : {}) }); pages.provider(); },
    p.status === "published" ? { title: "Live", sub: `${enabled.length} tools reachable by agents` } : null);

  const shown = enabled.slice(0, 10);
  const backendLabel = p.kind === "mcp" ? "Upstream MCP server" : "Upstream API";
  $("#page").innerHTML = `
    <div class="card">
      <div class="card-head">
        <span class="card-brand" style="font-size:16px">${logo(p.name, 0)} ${esc(p.name)}</span>
        <span style="display:flex;gap:6px;flex-wrap:wrap">${standaloneChip(p)}${kindChip(p.kind)}${authChip(p.auth_mode)}${statusChip(p.status)}</span>
      </div>
      <div class="tiles" style="grid-template-columns:repeat(4, 1fr)">
        <div class="tile"><span class="k"><i class="ph ph-link"></i>Gateway endpoint
          <button class="btn small copy" data-copy="p-endpoint" title="Copy the endpoint" style="margin-left:auto;padding:2px 7px"><i class="ph ph-copy"></i></button></span>
          <span class="v mono" id="p-endpoint">${esc(p.mcp_url)}</span></div>
        ${tile(p.kind === "mcp" ? "plugs-connected" : "cloud", backendLabel, p.base_url.replace(/^https?:\/\//, ""), true)}
        ${tile("plug", "Tools", `${p.tools_enabled} of ${p.tool_count} enabled`)}
        ${tile("textbox", "Tool names", p.tool_prefix ? `${p.tool_prefix}*` : "no prefix")}
      </div>
      <p class="card-desc" style="-webkit-line-clamp:3">${p.kind === "mcp" ? "Tools proxied from the MCP server, unchanged" : `Spec from ${esc(p.spec_source)}`}. Registered by ${esc(p.owner)} on ${esc(fmtDate(p.created_at))}. ${p.auth_mode === "open" ? "The upstream accepts anonymous calls, so the gateway carries all the enforcement." : p.auth_mode === "network" ? `Reachable only from ${esc(p.allowlist || "the allowlisted gateway address")}.` : p.auth_mode === "oauth" ? `Each caller's own linked account token is sent; ${conns.length} user(s) linked.` : "The gateway sends a stored service token on every call."}</p>
      <div class="card-actions">
        <button class="btn small" data-act="edit"><i class="ph ph-pencil-simple"></i> Edit connection</button>
        <button class="btn small" data-act="test"><i class="ph ph-plugs"></i> Test connection</button>
        <button class="btn small" data-act="access"><i class="ph ph-sliders-horizontal"></i> Manage tools</button>
        <button class="btn small ${p.status === "published" ? "" : "solid"}" data-act="${p.status === "published" ? "unpublish" : "publish"}"><i class="ph ${p.status === "published" ? "ph-eye-slash" : "ph-check"}"></i> ${p.status === "published" ? "Unpublish" : "Publish"}</button>
        ${canDeploy ? `<button class="btn small ${p.standalone ? "" : "solid"}" data-act="${p.standalone ? "undeploy" : "deploy"}"><i class="ph ${p.standalone ? "ph-rocket" : "ph-rocket-launch"}"></i> ${p.standalone ? "Undeploy MCP server" : "Deploy as MCP server"}</button>` : ""}
        ${p.id !== "bizplay" ? `<button class="btn small danger" data-act="delete"><i class="ph ph-trash"></i> Delete</button>` : ""}
      </div>
    </div>
    ${LOCAL_HOST.test(hostOf(p.mcp_url)) && !LOCAL_HOST.test(location.hostname) ? `<div class="callout warn"><i class="ph ph-warning"></i><span><strong>Other machines cannot reach this endpoint.</strong> It points at ${esc(hostOf(p.mcp_url))}, which only resolves on the server itself. Use Edit connection and set it to <span class="mono">${esc(location.origin)}/mcp</span>, or set PUBLIC_HOST in the server's .env file.</span></div>` : ""}
    ${p.auth_mode === "oauth" ? connectionsCard(p, conns) : ""}
    ${canDeploy ? `
    <div class="card deploy ${p.standalone ? "on" : ""}">
      <div class="card-head">
        <span class="card-brand"><span class="logo ${p.standalone ? "green" : "dark"}"><i class="ph ph-rocket-launch"></i></span> ${p.standalone ? "Deployed as its own MCP server" : "Deploy as its own MCP server"}</span>
        ${p.standalone ? chip("green", "Serving", "check") : chip("", "Not deployed", "moon")}
      </div>
      ${p.standalone ? `
      <div class="tiles" style="grid-template-columns:2fr 1fr 1fr">
        <div class="tile"><span class="k"><i class="ph ph-link"></i>Standalone endpoint
          <button class="btn small copy" data-copy="p-standalone" title="Copy the endpoint" style="margin-left:auto;padding:2px 7px"><i class="ph ph-copy"></i></button></span>
          <span class="v mono" id="p-standalone">${esc(p.standalone_url)}</span></div>
        ${tile("textbox", "Tool names", "no prefix")}
        ${tile("shield-check", "Governance", "same tokens, policy, audit")}
      </div>
      <p class="card-desc" style="-webkit-line-clamp:4">One connector, one product: an agent that adds this URL sees only ${esc(p.name)}, with tool names such as <span class="mono">${esc(enabled[0]?.name || "list_items")}</span>. The shared gateway keeps serving it too, prefixed. ${p.status === "published" ? "" : "It answers once the backend is published."}</p>
      <div class="seg" role="radiogroup" aria-label="Write the instructions for">
        <label class="seg-opt ${via.standalone ? "" : "on"}"><input type="radio" name="via" value="gateway" ${via.standalone ? "" : "checked"}><i class="ph ph-squares-four"></i><span><strong>Shared gateway</strong><span>Every published backend, tools named ${esc(p.tool_prefix || "")}*</span></span></label>
        <label class="seg-opt ${via.standalone ? "on" : ""}"><input type="radio" name="via" value="standalone" ${via.standalone ? "checked" : ""}><i class="ph ph-rocket-launch"></i><span><strong>This server only</strong><span>Just ${esc(p.name)}, plain tool names</span></span></label>
      </div>`
      : `<p class="card-desc" style="-webkit-line-clamp:4">Gives ${esc(p.name)} an endpoint of its own at <span class="mono">${esc(p.standalone_url)}</span>, serving only its tools with no prefix, the way a vendor's own MCP app appears in claude.ai or ChatGPT. It runs inside this gateway, so it needs no extra process and keeps the same tokens, tool policy, company scoping and audit log. It also publishes the backend on the shared gateway.</p>`}
    </div>` : ""}
    <div>
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:2px;flex-wrap:wrap">
        <h2 class="section-title" style="margin:0">Use ${esc(p.name)} from ${esc(g.label)}</h2>
        ${g.ready ? chip("green", "Works today", "check") : chip("amber", "Needs hosting and OAuth", "warning")}
        ${via.standalone ? chip("green", "via its own server", "rocket-launch") : chip("", "via the shared gateway", "squares-four")}
      </div>
      <p class="muted" style="max-width:76ch">${esc(g.lead)}</p>
      <div class="steps">${g.steps.map((s, i) => `<div class="step"><span class="step-n">${i + 1}</span><div class="step-b"><strong>${esc(s.t)}</strong>${s.b}</div></div>`).join("")}</div>
    </div>
    <div>
      <h2 class="section-title">Tools this ${p.kind === "mcp" ? "server" : "API"} exposes to agents</h2>
      <div class="table-card"><div class="table-wrap"><table><tr><th>Tool name the agent calls</th><th>Kind</th><th>${p.kind === "mcp" ? "Upstream tool" : "Upstream endpoint"}</th></tr>
      ${shown.length ? shown.map((t) => `<tr><td class="mono">${esc(via.prefix + t.name)}${t.summary ? `<div class="muted small">${esc(t.summary)}</div>` : ""}</td><td>${t.kind === "write" ? chip("amber", "write", "pencil-simple") : chip("lilac", "read", "eye")}${t.confirm ? ` ${chip("", "confirm first")}` : ""}</td><td class="mono small">${esc(p.kind === "mcp" ? t.name : (t.route || "composed from several endpoints"))}</td></tr>`).join("")
        : `<tr><td colspan="3">${emptyState("sliders-horizontal", "No tools enabled", "Enable some on the Access Control page and they appear here.")}</td></tr>`}
      </table></div></div>
      ${enabled.length > shown.length ? `<p class="muted small" style="margin-top:8px">${enabled.length - shown.length} more enabled. Open Manage tools to see the full list.</p>` : ""}
    </div>
    <div class="callout"><i class="ph ph-key"></i><span>Results are limited to the company on the caller's token, and every call is written to the audit log. Tokens are shown once, so issue a new one and revoke the old if you lost it.</span></div>`;

  $("#head-command").onclick = () => commandDialog(p, via);
  $("#page").querySelectorAll("[name=via]").forEach((r) => r.onchange = () => {
    setHash("provider", { p: pid, c: key, ...(r.value === "standalone" ? { via: "standalone" } : {}) }); pages.provider();
  });
  $("#page").querySelectorAll("[data-disconnect]").forEach((b) => b.onclick = async () => {
    if (!confirm(`Disconnect ${b.dataset.disconnect}? Their calls to ${p.name} are refused until they link the account again.`)) return;
    try { await api("DELETE", `/api/registry/${pid}/connections/${b.dataset.disconnect}`); toast("Account disconnected", b.dataset.disconnect); pages.provider(); }
    catch (err) { toast("Disconnect failed", err.message, 4500); }
  });
  $("#page").querySelectorAll("[data-act]").forEach((b) => b.onclick = async () => {
    const act = b.dataset.act;
    try {
      if (act === "access") { setHash("access", { p: pid }); return; }
      if (act === "command") return commandDialog(p, via);
      if (act === "edit") return editDialog(p);
      if (act === "test") return testDialog(pid);
      if (act === "connect") return connectDialog(p);
      if (act === "discover") {
        b.disabled = true;
        const r = await api("POST", `/api/registry/${pid}/oauth/discover`, {});
        toast(r.registered_client ? "Client registered" : "Endpoints discovered", r.note, 6000); pages.provider(); return;
      }
      if (act === "refresh-tools") {
        const r = await api("POST", `/api/registry/${pid}/refresh-tools`, { user_id: conns[0]?.user_id });
        toast("Tools refreshed", r.note); pages.provider(); return;
      }
      if (act === "delete") {
        if (!confirm(`Delete ${p.name}?`)) return;
        await api("DELETE", `/api/registry/${pid}`); toast("Provider deleted", p.name); location.hash = "registry"; return;
      }
      const r = await api("POST", `/api/registry/${pid}/${act}`);
      if (act === "deploy") { toast("Deployed", `${p.name} now answers at ${r.standalone_url}`, 5000); setHash("provider", { p: pid, c: key, via: "standalone" }); }
      else if (act === "undeploy") { toast("Undeployed", `${r.standalone_url} now returns 404; the shared gateway still serves it`, 5000); setHash("provider", { p: pid, c: key }); }
      else toast(act === "publish" ? "Published" : "Unpublished", `${p.name} ${act === "publish" ? "is now reachable by agents" : "is hidden from agents"}`);
      pages.provider();
    } catch (err) { toast("Action failed", err.message, 4500); }
  });
};

// ---- Security ----
pages.security = async () => {
  const d = await api("GET", "/api/security");
  const s = d.settings;
  const passed = d.checklist.filter((c) => c.ok).length, score = Math.round(100 * passed / d.checklist.length);
  const tab = ["checklist", "settings", "credentials", "identity"].includes(hashParam("t")) ? hashParam("t") : "checklist";
  renderTabs([
    { key: "checklist", label: "Checklist", icon: "list-checks", count: `${passed}/${d.checklist.length}` },
    { key: "settings", label: "Gateway settings", icon: "sliders-horizontal" },
    { key: "credentials", label: "Upstream credentials", icon: "key", count: d.credentials.length },
    { key: "identity", label: "Identity mapping", icon: "fingerprint", count: Object.keys(d.identity).length },
  ], tab, (k) => { setHash("security", { t: k }); pages.security(); },
  { title: `Security score ${score}%`, sub: `${passed} of ${d.checklist.length} checks pass`, tone: score >= 70 ? "" : "warn" });

  // One setting per row: what it is on the left, the control on the right.
  const setting = (key, title, help, control) => `
    <div class="setting"><div class="setting-text"><strong>${title}</strong><p class="muted small">${help}</p></div><div class="setting-ctl">${control}</div></div>`;
  const toggle = (key) => `<input type="checkbox" class="switch" data-s="${key}" ${s[key] ? "checked" : ""} aria-label="${key}">`;

  const views = {
    checklist: `
      <div class="stats">
        <div class="stat"><span class="num" style="color:${score >= 70 ? "var(--green-ink)" : "var(--amber-ink)"}">${score}%</span><span class="lbl">Security score</span></div>
        <div class="stat"><span class="num">${passed}</span><span class="lbl">Checks passing</span></div>
        <div class="stat"><span class="num">${d.checklist.length - passed}</span><span class="lbl">Open items</span></div>
        <div class="stat"><span class="num">${d.credentials.filter((c) => c.rotated_at).length} / ${d.credentials.length}</span><span class="lbl">Credentials rotated at least once</span></div>
      </div>
      <div class="table-card"><div class="table-wrap"><table>
        <tr><th style="width:120px">Status</th><th>Check</th><th>Detail</th></tr>
        ${d.checklist.map((c) => `<tr><td>${c.ok ? chip("green", "Pass", "check") : chip("red", "Open", "x")}</td><td><strong>${esc(c.label)}</strong></td><td class="small muted">${esc(c.detail)}</td></tr>`).join("")}
      </table></div></div>
      <div class="callout"><i class="ph ph-info"></i><span>Two of these stay open by design in the mockup: OAuth 2.1 for agents and a vault for secrets are production work. The rest are decided on the Gateway settings tab and by how each backend is registered.</span></div>`,

    settings: `
      <div class="card settings-list">
        ${setting("require_upstream_bearer", "Bizplay API endpoints require a bearer token",
          "Records the policy that every /api/* call carries the service token. Enforced by the provider's own API, not here.", toggle("require_upstream_bearer"))}
        ${setting("require_gateway_bearer", "MCP gateway requires an agent token",
          "Agents must present a portal-issued token over HTTP. Read by the gateways at startup, so restart them after changing it. Off means anyone who reaches the gateway is the same demo user.", toggle("require_gateway_bearer"))}
        ${setting("confirm_on_write", "Write tools ask for confirmation",
          "Turning this on sets confirm-before-call on every write tool of every backend at once.", toggle("confirm_on_write"))}
        ${setting("token_ttl_days", "Default agent token lifetime",
          "Days before a newly issued agent token expires. The checklist flags anything over 90.", `<div class="ctl-inline"><input type="number" data-s="token_ttl_days" value="${s.token_ttl_days}" min="1" max="365" aria-label="Token lifetime in days"><span class="muted small">days</span></div>`)}
        ${setting("public_mcp_url", "Public MCP endpoint",
          `The address agents use when a tunnel or nginx sits in front. New registrations inherit it. Blank means this portal's own address, ${esc(SERVER.portal_mcp_url || location.origin + "/mcp")}.`,
          `<input data-s="public_mcp_url" value="${esc(s.public_mcp_url || "")}" placeholder="${esc(SERVER.portal_mcp_url || "https://your-host/mcp")}" aria-label="Public MCP endpoint" class="ctl-wide">`)}
      </div>
      <p class="muted small">Changes save as you make them.</p>`,

    credentials: `
      <div class="table-card"><div class="table-wrap"><table>
        <tr><th>Credential</th><th>Backend</th><th>Secret</th><th>Rotated</th><th></th></tr>
        ${d.credentials.length ? d.credentials.map((c, n) => `<tr>
          <td><span class="name">${logo(c.provider_id, n)} <span>${esc(c.label)}<div class="sub">${esc(c.type)} token the gateway sends</div></span></span></td>
          <td class="mono">${esc(c.provider_id)}</td>
          <td class="mono">${esc(c.secret)}</td>
          <td>${c.rotated_at ? `${chip("green", "Rotated", "arrows-clockwise")}<div class="sub">${esc(fmtDate(c.rotated_at))}</div>` : chip("amber", "Never rotated", "clock")}</td>
          <td class="actions"><button class="btn small" data-rotate="${esc(c.id)}"><i class="ph ph-arrows-clockwise"></i> Rotate</button></td>
        </tr>`).join("") : `<tr><td colspan="5">${emptyState("key", "No upstream credentials", "Backends in bearer mode get one when they are registered.")}</td></tr>`}
      </table></div></div>
      <div class="callout"><i class="ph ph-info"></i><span>Secrets are masked here and never shown again after rotation. The mockup keeps them in a JSON file; production keeps them in a vault.</span></div>`,

    identity: `
      <div class="table-card"><div class="table-wrap"><table>
        <tr><th>Backend</th><th>Issuer</th><th>User claim</th><th>Role claim</th><th>Company claim</th></tr>
        ${Object.entries(d.identity).map(([pid, i], n) => `<tr>
          <td><span class="name">${logo(pid, n)} ${esc(pid)}</span></td>
          <td>${chip("lilac", i.issuer, "fingerprint")}</td>
          <td class="mono">${esc(i.user_claim)}</td><td class="mono">${esc(i.role_claim)}</td><td class="mono">${esc(i.company_claim)}</td>
        </tr>`).join("")}
      </table></div></div>
      <div class="callout"><i class="ph ph-info"></i><span>How the gateway reads who is calling from an agent token. Production points the issuer at Bizplay SSO (OAuth 2.1 / OIDC), so tokens are signed JWTs verified by key rather than looked up in a table.</span></div>`,
  };
  $("#page").innerHTML = views[tab];
  $("#page").querySelectorAll("[data-s]").forEach((inp) => inp.onchange = async () => {
    const value = inp.type === "checkbox" ? inp.checked : (inp.type === "number" ? Number(inp.value) : inp.value);
    const body = { [inp.dataset.s]: value };
    try { await api("PUT", "/api/security", body); toast("Settings saved"); if (inp.dataset.s === "confirm_on_write") pages.security(); } catch (err) { toast("Save failed", err.message, 4500); }
  });
  $("#page").querySelectorAll("[data-rotate]").forEach((b) => b.onclick = async () => {
    if (!confirm("Rotate this credential? The provider must accept the new token before the old one is retired.")) return;
    try {
      const r = await api("POST", `/api/credentials/${b.dataset.rotate}/rotate`, {});
      modal(`<h2><i class="ph ph-arrows-clockwise"></i> New service token</h2><div class="token-box"><code>${esc(r.secret)}</code></div><p class="muted small" style="margin-top:10px">${esc(r.note)}</p>
        <div style="display:flex;justify-content:flex-end"><button class="btn solid" id="rot-done">Done</button></div>`);
      $("#rot-done").onclick = () => { closeModal(); pages.security(); };
    } catch (err) { toast("Rotation failed", err.message, 4500); }
  });
};

// ---- Audit ----
pages.audit = async () => {
  const d = await api("GET", "/api/audit?limit=200");
  const filter = hashParam("f") || "all";
  const items = d.items.filter((e) => filter === "all" || e.outcome === filter);
  renderTabs([
    { key: "all", label: "All calls", icon: "list-magnifying-glass", count: d.items.length },
    { key: "ok", label: "Succeeded", icon: "check-circle", count: d.items.filter((e) => e.outcome === "ok").length },
    { key: "denied", label: "Denied", icon: "prohibit", count: d.items.filter((e) => e.outcome === "denied").length },
    { key: "error", label: "Errors", icon: "warning", count: d.items.filter((e) => e.outcome === "error").length },
  ], filter, (k) => { setHash("audit", { f: k }); pages.audit(); });

  pageActions(`<button class="btn" id="audit-refresh"><i class="ph ph-arrows-clockwise"></i> Refresh</button>`);
  $("#page").innerHTML = `
    <div>
      <div class="filter-bar" style="margin-bottom:14px">
        <label>Filter <input id="audit-filter" class="filter" placeholder="User or tool" aria-label="Filter audit log"></label>
        <span class="grow"></span>
        <span class="muted small">Newest first, ${items.length} call(s)</span>
      </div>
      <div class="table-card"><div class="table-wrap"><table id="audit-table"><tr><th>Time (UTC)</th><th>User</th><th>Tool</th><th>Arguments</th><th>Outcome</th><th>Detail</th></tr>
      ${items.length ? items.map((e) => `<tr><td class="small mono nowrap">${esc(fmtUtc(e.ts))}</td><td class="nowrap"><span class="mono">${esc(e.user_id)}</span><div class="sub">${esc(e.via || "env")}</div></td><td class="mono small tool">${esc(e.tool)}</td><td class="small mono clip" title="${esc(JSON.stringify(e.arguments))}">${esc(JSON.stringify(e.arguments))}</td><td>${outcomeChip(e.outcome)}</td><td class="small muted">${esc(e.detail)}</td></tr>`).join("")
        : `<tr><td colspan="6">${emptyState("list-magnifying-glass", "Nothing here", "Every gateway call is recorded with who made it and the outcome.")}</td></tr>`}</table></div></div>
    </div>`;
  $("#audit-refresh").onclick = () => pages.audit();
  $("#audit-filter").oninput = (e) => {
    const q = e.target.value.toLowerCase();
    $("#audit-table").querySelectorAll("tr").forEach((tr, i) => { if (i) tr.style.display = tr.textContent.toLowerCase().includes(q) ? "" : "none"; });
  };
};

// ---- boot ----
// One handler for every copy button, on pages and inside dialogs.
document.addEventListener("click", (e) => {
  const b = e.target.closest?.(".copy");
  if (!b) return;
  const text = document.getElementById(b.dataset.copy)?.textContent || "";
  navigator.clipboard?.writeText(text).then(() => toast("Copied", "Paste it into your terminal"));
});

// Every page renders by replacing #page, so one observer animates them all.
new MutationObserver(() => animateIn($("#page"))).observe($("#page"), { childList: true });
new MutationObserver(() => replay($("#tabs"), "anim")).observe($("#tabs"), { childList: true });

if (session?.token) {
  api("GET", "/api/me").then((u) => { session.user = u; enterApp(); }).catch(() => signOut());
} else {
  $("#login").classList.remove("hidden");
}
