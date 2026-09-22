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
// Close on a click on the backdrop only when the press started there too: a text selection
// that begins in a field and ends outside the card must not throw the dialog away.
let pressedOnBackdrop = false;
$("#modal").addEventListener("mousedown", (e) => { pressedOnBackdrop = e.target.id === "modal"; });
$("#modal").addEventListener("click", (e) => { if (e.target.id === "modal" && pressedOnBackdrop) closeModal(); pressedOnBackdrop = false; });

const SKELETON = `<div class="skeleton" aria-busy="true"><div class="bar w-40"></div><div class="bar tall"></div><div class="bar w-70"></div><div class="bar tall"></div></div>`;
const emptyState = (icon, title, hint) => `<div class="empty"><span class="mark"><i class="ph ph-${icon}"></i></span><strong>${title}</strong><span class="small">${hint}</span></div>`;
/** Full-page state for a route that has nothing to show: not found, deleted, or failed to load. */
const errorPage = ({ code = "", title, detail, actions = [] }) => `
  <div class="error-page">
    ${code ? `<p class="error-code">${esc(code)}</p>` : `<span class="mark"><i class="ph ph-warning-circle"></i></span>`}
    <h2>${esc(title)}</h2>
    <p class="muted" style="max-width:56ch">${esc(detail)}</p>
    <div class="error-actions">${actions.map((a) => `<a class="btn ${a.primary ? "solid" : ""}" href="${esc(a.href)}">${a.icon ? `<i class="ph ph-${a.icon}"></i> ` : ""}${esc(a.label)}</a>`).join("")}</div>
  </div>`;
const notFoundPage = (what, backHref, backLabel) => errorPage({ code: "404", title: `${what} not found`,
  detail: "It may have been deleted, or the link is out of date. Nothing on the gateway was changed by opening this page.",
  actions: [{ href: backHref, label: backLabel, icon: "arrow-left", primary: true }, { href: "#overview", label: "Overview" }] });
const chip = (kind, text, icon) => `<span class="chip ${kind}">${icon ? `<i class="ph ph-${icon}"></i>` : ""}${esc(text)}</span>`;
const tile = (icon, k, v, mono = false) => `<div class="tile"><span class="k"><i class="ph ph-${icon}"></i>${esc(k)}</span><span class="v ${mono ? "mono" : ""}">${esc(v)}</span></div>`;
const LOGO_COLORS = ["green", "lilac", "amber", "dark", "red"];
const logo = (name, i = 0) => `<span class="logo ${LOGO_COLORS[i % LOGO_COLORS.length]}">${esc(initials(name))}</span>`;
const authChip = (m) => ({ bearer: chip("lilac", "Bearer", "key"), network: chip("amber", "Network", "shield-check"), open: chip("red", "Open", "warning"), oauth: chip("green", "OAuth per user", "user-circle"), login: chip("green", "Login endpoint", "sign-in") }[m] || chip("lilac", "Bearer", "key"));
// Fields for a backend with its own username-and-password login endpoint. Shared by the register and edit dialogs.
const loginFields = (prefix, cfg = {}, sa = {}) => `
  <div class="form-2">
    <label class="field">Login URL <input name="login.url" value="${esc(cfg.url || "")}" placeholder="https://api.example.com/auth/login"></label>
    <label class="field">Token field in the response <input name="login.token_path" value="${esc(cfg.token_path || "token")}" placeholder="data.accessToken"><span class="muted small">Dot path into the JSON answer.</span></label>
  </div>
  <label class="field">Request body <textarea name="login.body" rows="2" style="min-height:52px">${esc(cfg.body || '{"username": "{username}", "password": "{password}"}')}</textarea><span class="muted small">JSON sent to the login URL; {username} and {password} are filled in.</span></label>
  <div class="form-2">
    <label class="field">Expiry field (optional) <input name="login.expires_path" value="${esc(cfg.expires_path || "")}" placeholder="expiresIn (seconds)"></label>
    <label class="field">Lifetime if no expiry field (minutes) <input name="login.ttl_minutes" type="number" min="1" value="${esc(cfg.ttl_minutes || 60)}"></label>
    <label class="field">Send the token in header <input name="login.header" value="${esc(cfg.header || "Authorization")}" placeholder="Authorization"></label>
    <label class="field">Scheme prefix <input name="login.scheme" value="${esc(cfg.scheme ?? "Bearer")}" placeholder="Bearer (empty for none)"></label>
  </div>
  <label class="field">Whose credentials
    <select name="login.per_user" id="${prefix}-login-per-user">
      <option value="false" ${cfg.per_user ? "" : "selected"}>Service account: one username and password shared by every caller</option>
      <option value="true" ${cfg.per_user ? "selected" : ""}>Each user: people sign in with their own username and password</option>
    </select></label>
  <div class="form-2 ${cfg.per_user ? "hidden" : ""}" id="${prefix}-login-sa">
    <label class="field">Service account username <input name="login_username" value="${esc(sa.username || "")}" placeholder="svc-gateway"></label>
    <label class="field">Service account password <input name="login_password" type="password" placeholder="${sa.has_password ? "stored, leave blank to keep" : "stored, never shown again"}" autocomplete="new-password"></label>
  </div>
  <div class="callout"><i class="ph ph-info"></i><span>The gateway calls the login URL itself, caches the token, and signs in again when it expires or the API answers 401. With per-user credentials each person connects on their <strong>My access</strong> page and the API sees them, not a shared account.</span></div>`;
const bindLoginFields = (prefix) => { const sel = $(`#${prefix}-login-per-user`); if (sel) sel.onchange = () => $(`#${prefix}-login-sa`).classList.toggle("hidden", sel.value === "true"); };
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
/** Pull "oauth.x" and "login.x" fields out of a form into {oauth: {x}, login: {x}}. */
function splitOauth(f) {
  const oauth = {}, login = {};
  for (const [k, v] of Object.entries(f)) {
    if (k.startsWith("oauth.")) { oauth[k.slice(6)] = v; delete f[k]; }
    if (k.startsWith("login.")) { login[k.slice(6)] = v; delete f[k]; }
  }
  if (!f.login_password) delete f.login_password;
  return { ...f, oauth, login };
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

// ---- language ----
// Korean is applied to the rendered DOM by i18n.js; the buttons only store the choice and reload.
document.querySelectorAll("[data-lang-toggle]").forEach((b) => {
  b.querySelector("[data-lang-label]").textContent = I18N.lang === "ko" ? "English" : "한국어";
  b.onclick = () => I18N.setLang(I18N.lang === "ko" ? "en" : "ko");
});
I18N.watch();

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
  $("#whoami-sub").textContent = isAdmin() ? `DemoCorp01 / ${session.user.role}` : `${session.user.user_id} / ${session.user.user_role || "employee"}`;
  document.querySelectorAll("[data-admin]").forEach((el) => el.classList.toggle("hidden", !isAdmin()));
  document.querySelectorAll("[data-member]").forEach((el) => el.classList.toggle("hidden", isAdmin()));
  go(location.hash.replace("#", "") || (isAdmin() ? "overview" : "me"));
}

// ---- router ----
const pages = {};
const titles = { overview: "Overview", registry: "MCP Registry", gateways: "MCP Gateways", gateway: "Gateway details", servers: "MCP Servers", provider: "Backend details", access: "Access Control", users: "Users", tokens: "Agent Tokens", security: "Security", audit: "Audit Log", me: "My access" };
// What a member (an employee serving themselves) can open; anything else sends them home.
const MEMBER_PAGES = new Set(["me", "gateway"]);
const isAdmin = () => session?.user?.is_admin !== false;
// Pages reached from another page keep that page's nav item lit.
const RAIL_OF = { provider: "registry", access: "registry", gateway: "gateways" };
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
  if (!isAdmin() && pages[page] && !MEMBER_PAGES.has(page)) { location.hash = "me"; page = "me"; }
  if (isAdmin() && page === "me") { location.hash = "overview"; page = "overview"; }
  if (!pages[page]) {
    document.querySelectorAll(".side-nav a").forEach((a) => a.classList.remove("active"));
    $("#page-title").textContent = "Not found"; crumbs({ page: "overview", label: "Not found" }); pageActions(""); $("#tabs").classList.add("hidden");
    $("#page").innerHTML = errorPage({ code: "404", title: "No such page", detail: `There is no page called "${page}". Pick one from the menu.`,
      actions: [{ href: "#overview", label: "Overview", icon: "house", primary: true }, { href: "#registry", label: "MCP Registry" }] });
    return;
  }
  if (location.hash.slice(1).split("?")[0] !== page) location.hash = page;
  const rail = RAIL_OF[page] || page;
  document.querySelectorAll(".side-nav a").forEach((a) => a.classList.toggle("active", a.dataset.page === rail));
  $("#page-title").textContent = titles[page];
  crumbs({ page, label: titles[page] });
  pageActions("");
  $("#global-search").value = "";
  $("#tabs").classList.add("hidden");
  $("#page").innerHTML = SKELETON;
  pages[page]().catch((err) => {
    $("#page").innerHTML = errorPage({ title: "Could not load this page", detail: `${err.message}. The portal could not get what it needs from the server; nothing was changed.`,
      actions: [{ href: location.hash || "#overview", label: "Try again", icon: "arrows-clockwise", primary: true }, { href: "#overview", label: "Overview" }] });
    $("#page").querySelector(".error-actions a.solid").onclick = (e) => { e.preventDefault(); go(page); };
  });
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
// ---- charts (inline SVG; colors validated for CVD on the white surface) ----
const VIZ = { ok: "#008300", denied: "#eda100", error: "#e34948", series: "#2f6bff", track: "#dbe4f5" };
const fmtDay = (iso) => { const [y, m, d] = iso.split("-"); return `${Number(m)}/${Number(d)}`; };
const niceMax = (n) => { if (n <= 5) return 5; const p = Math.pow(10, Math.floor(Math.log10(n))); const u = n / p; return (u <= 1 ? 1 : u <= 2 ? 2 : u <= 5 ? 5 : 10) * p; };

/** Stacked columns: one per day, ok / denied / error, 2px surface gaps, rounded top segment, hover tooltip. */
function callsByDayChart(rows, W = 1000) {
  const H = 180, padL = 36, padR = 8, padT = 10, padB = 24;
  const innerW = W - padL - padR, innerH = H - padT - padB;
  const max = niceMax(Math.max(1, ...rows.map((r) => r.ok + r.denied + r.error)));
  const slot = innerW / rows.length, bw = Math.min(22, slot * 0.5);
  const y = (v) => padT + innerH - (v / max) * innerH;
  const ticks = [0, max / 2, max];
  const cols = rows.map((r, i) => {
    const x = padL + i * slot + (slot - bw) / 2;
    const stack = ["ok", "denied", "error"].filter((k) => r[k] > 0);
    let acc = 0;
    const segs = stack.map((k, j) => {
      const y0 = y(acc + r[k]), y1 = y(acc); acc += r[k];
      const gap = j < stack.length - 1 ? 2 : 0;
      const h = Math.max(0, y1 - y0 - gap);
      const last = j === stack.length - 1;
      return `<rect x="${x}" y="${y0}" width="${bw}" height="${h}" fill="${VIZ[k]}" ${last ? 'rx="4"' : ""}></rect>${last ? `<rect x="${x}" y="${y0 + Math.min(4, h)}" width="${bw}" height="${Math.max(0, h - Math.min(4, h))}" fill="${VIZ[k]}"></rect>` : ""}`;
    }).join("");
    const total = r.ok + r.denied + r.error;
    const tip = `${fmtDay(r.date)} · ${total} call${total === 1 ? "" : "s"} · ok ${r.ok}, denied ${r.denied}, error ${r.error}`;
    return `<g class="col" data-tip="${esc(tip)}"><rect x="${padL + i * slot}" y="${padT}" width="${slot}" height="${innerH}" fill="transparent"></rect>${segs}</g>`;
  }).join("");
  const labels = rows.map((r, i) => (rows.length <= 14 || i % 2 === 0) ? `<text x="${padL + i * slot + slot / 2}" y="${H - 8}" text-anchor="middle" class="ax">${fmtDay(r.date)}</text>` : "").join("");
  return `<svg class="viz" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="Gateway calls per day">
    ${ticks.map((t) => `<line x1="${padL}" x2="${W - padR}" y1="${y(t)}" y2="${y(t)}" class="grid"></line><text x="${padL - 6}" y="${y(t) + 4}" text-anchor="end" class="ax">${t}</text>`).join("")}
    ${cols}${labels}</svg>`;
}

/** Horizontal bars, one series, value at the tip; denied/error share shown in the tooltip. */
function callsByBackendChart(rows, W = 640) {
  const rowH = 26, padL = 8, padR = 56, labelW = Math.min(170, W * 0.3);
  const H = Math.max(60, rows.length * rowH + 8);
  const max = Math.max(1, ...rows.map((r) => r.calls));
  const innerW = W - padL - padR - labelW;
  return `<svg class="viz" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="Gateway calls by backend">
    ${rows.map((r, i) => {
      const yy = 4 + i * rowH, w = Math.max(2, (r.calls / max) * innerW);
      const tip = `${r.backend} · ${r.calls} call${r.calls === 1 ? "" : "s"}${r.denied || r.error ? ` · denied ${r.denied}, error ${r.error}` : ""}${r.folded ? ` · ${r.folded} backends folded` : ""}`;
      return `<g class="bar" data-tip="${esc(tip)}">
        <rect x="0" y="${yy}" width="${W}" height="${rowH}" fill="transparent"></rect>
        <text x="${padL + labelW - 10}" y="${yy + rowH / 2 + 4}" text-anchor="end" class="lbl">${esc(r.backend.length > 24 ? r.backend.slice(0, 23) + "…" : r.backend)}</text>
        <rect x="${padL + labelW}" y="${yy + 5}" width="${w}" height="${rowH - 10}" fill="${VIZ.series}" rx="4"></rect><rect x="${padL + labelW}" y="${yy + 5}" width="${Math.min(4, w)}" height="${rowH - 10}" fill="${VIZ.series}"></rect>
        <text x="${padL + labelW + w + 8}" y="${yy + rowH / 2 + 4}" class="val">${r.calls}</text></g>`;
    }).join("")}</svg>`;
}

/** Part-to-whole per backend: enabled tools on a track of the total, "enabled / total" at the tip. */
function toolsByBackendChart(rows, W = 640) {
  const rowH = 26, padL = 8, padR = 74, labelW = Math.min(170, W * 0.3);
  const H = Math.max(60, rows.length * rowH + 8);
  const max = Math.max(1, ...rows.map((r) => r.total));
  const innerW = W - padL - padR - labelW;
  return `<svg class="viz" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="Tools enabled per backend">
    ${rows.map((r, i) => {
      const yy = 4 + i * rowH, wt = Math.max(2, (r.total / max) * innerW), we = (r.enabled / max) * innerW;
      const tip = `${r.backend} · ${r.enabled} of ${r.total} tools enabled${r.published ? "" : " · not published"}`;
      return `<g class="bar" data-tip="${esc(tip)}">
        <rect x="0" y="${yy}" width="${W}" height="${rowH}" fill="transparent"></rect>
        <text x="${padL + labelW - 10}" y="${yy + rowH / 2 + 4}" text-anchor="end" class="lbl">${esc(r.backend.length > 24 ? r.backend.slice(0, 23) + "…" : r.backend)}</text>
        <rect x="${padL + labelW}" y="${yy + 5}" width="${wt}" height="${rowH - 10}" fill="${VIZ.track}" rx="4"></rect>
        ${we > 0 ? `<rect x="${padL + labelW}" y="${yy + 5}" width="${Math.max(2, we)}" height="${rowH - 10}" fill="${VIZ.series}" rx="4"></rect><rect x="${padL + labelW}" y="${yy + 5}" width="${Math.min(4, we)}" height="${rowH - 10}" fill="${VIZ.series}"></rect>` : ""}
        <text x="${padL + labelW + wt + 8}" y="${yy + rowH / 2 + 4}" class="val">${r.enabled} / ${r.total}</text></g>`;
    }).join("")}</svg>`;
}

const legend = (items) => `<div class="legend">${items.map(([c, l]) => `<span><i style="background:${c}"></i>${esc(l)}</span>`).join("")}</div>`;
const tableView = (headers, rows) => `<details class="viz-table"><summary>Table view</summary><div class="table-wrap"><table><tr>${headers.map((h) => `<th>${esc(h)}</th>`).join("")}</tr>${rows.map((r) => `<tr>${r.map((c) => `<td>${esc(c)}</td>`).join("")}</tr>`).join("")}</table></div></details>`;

/** One tooltip for every chart on the page: follows the pointer over marks that carry data-tip. */
function bindChartTips(root) {
  let tip = document.getElementById("viz-tip");
  if (!tip) { tip = document.createElement("div"); tip.id = "viz-tip"; tip.className = "viz-tip hidden"; document.body.appendChild(tip); }
  root.querySelectorAll("[data-tip]").forEach((g) => {
    g.addEventListener("pointerenter", () => { tip.textContent = g.dataset.tip; tip.classList.remove("hidden"); });
    g.addEventListener("pointermove", (e) => { tip.style.left = `${e.clientX + 12}px`; tip.style.top = `${e.clientY + 14}px`; });
    g.addEventListener("pointerleave", () => tip.classList.add("hidden"));
  });
}

// ---- Overview ----
pages.overview = async () => {
  const d = await api("GET", "/api/overview");
  const open = d.checklist.filter((c) => !c.ok).length;
  const u = d.usage, byDay = u.calls_by_day, byBackend = u.calls_by_backend, tools = d.tools_by_backend;
  const denied = byDay.reduce((n, r) => n + r.denied, 0), errors = byDay.reduce((n, r) => n + r.error, 0);
  $("#page").innerHTML = `
    <div class="stats">
      <div class="stat"><span class="num">${d.providers}</span><span class="lbl">Registered backends, ${d.published} published</span></div>
      <div class="stat"><span class="num">${d.tools_enabled}</span><span class="lbl">Tools enabled for agents</span></div>
      <div class="stat"><span class="num">${u.total}</span><span class="lbl">Gateway calls, last ${u.days} days${denied + errors ? ` · ${denied} denied, ${errors} errors` : ""}</span></div>
      <div class="stat"><span class="num" style="color:${d.score >= 70 ? "var(--green-ink)" : "var(--amber-ink)"}">${d.score}%</span><span class="lbl">Security score, ${open} open item(s)</span></div>
    </div>
    <div class="card flow-card">
      <div class="flow">
        <div class="node"><strong>AI agent</strong><span class="muted">Claude, ChatGPT, Copilot, Agentforce</span></div>
        <span class="arrow"><i class="ph ph-arrow-right"></i><br>agent token</span>
        <div class="node hl"><strong>MCP Gateway</strong><span>authentication, tool policy, company scope, audit</span></div>
        <span class="arrow"><i class="ph ph-arrow-right"></i><br>service or user token</span>
        <div class="node"><strong>REST API or MCP server</strong><span class="muted">unchanged; may also be deployed as its own MCP server</span></div>
      </div>
    </div>
    <div class="card chart-card">
      <div class="section-head"><h2 class="section-title">Gateway calls per day</h2><a class="btn small link" href="#audit">Audit log</a></div>
      ${u.total ? `<div class="viz-slot" data-chart="day"></div>` + legend([[VIZ.ok, "ok"], [VIZ.denied, "denied"], [VIZ.error, "error"]]) : emptyState("chart-bar", "No calls yet", `Ask an agent something that uses a gateway tool and the last ${u.days} days fill in here.`)}
      ${u.total ? tableView(["Day", "ok", "denied", "error"], byDay.filter((r) => r.ok + r.denied + r.error).map((r) => [r.date, r.ok, r.denied, r.error])) : ""}
    </div>
    <div class="two">
      <div class="card chart-card">
        <div class="section-head"><h2 class="section-title">Calls by backend</h2><span class="muted small">last ${u.days} days</span></div>
        ${byBackend.length ? `<div class="viz-slot" data-chart="backend"></div>` + tableView(["Backend", "calls", "denied", "error"], byBackend.map((r) => [r.backend, r.calls, r.denied, r.error])) : emptyState("plugs-connected", "No backend called yet", "Traffic per backend appears here.")}
      </div>
      <div class="card chart-card">
        <div class="section-head"><h2 class="section-title">Tools enabled per backend</h2><a class="btn small link" href="#registry">Registry</a></div>
        ${tools.length ? `<div class="viz-slot" data-chart="tools"></div>` + legend([[VIZ.series, "enabled"], [VIZ.track, "registered but off"]]) + tableView(["Backend", "enabled", "total"], tools.map((r) => [r.backend, r.enabled, r.total])) : emptyState("plug", "No backends", "Register one in the MCP Registry.")}
      </div>
    </div>`;
  const draw = () => {
    $("#page").querySelectorAll(".viz-slot").forEach((slot) => {
      const w = Math.max(320, Math.floor(slot.clientWidth));
      slot.innerHTML = slot.dataset.chart === "day" ? callsByDayChart(byDay, w)
        : slot.dataset.chart === "backend" ? callsByBackendChart(byBackend, w) : toolsByBackendChart(tools, w);
    });
    bindChartTips($("#page"));
  };
  draw();
  // Redraw at the new width when the window changes size, without re-fetching.
  clearTimeout(pages.overview._rs);
  window.onresize = () => { clearTimeout(pages.overview._rs); pages.overview._rs = setTimeout(() => { if (location.hash.startsWith("#overview") || !location.hash) draw(); }, 150); };
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
      <label>Auth <select id="reg-filter-auth"><option value="">All</option><option value="bearer">Bearer</option><option value="oauth">OAuth per user</option><option value="login">Login endpoint</option><option value="network">Network</option><option value="open">Open</option></select></label>
      <span class="grow"></span>
      <span class="muted small">${items.length} backend(s). Type in the search box above to filter by name, URL or owner.</span>
    </div>
    <div class="table-card"><div class="table-wrap"><table id="registry-table">
      <tr><th>Backend</th><th>Type and auth</th><th>Status</th><th>Tools</th><th>Served on</th><th></th></tr>
      ${items.length ? items.map((p, i) => `<tr class="row-link" data-kind="${esc(p.kind)}" data-auth="${esc(p.auth_mode)}" data-open="${esc(p.id)}" title="Registered ${esc(fmtDate(p.created_at))} by ${esc(p.owner)}">
        <td><span class="name">${logo(p.name, i)} <span>${esc(p.name)}<div class="sub mono">${esc(p.base_url.replace(/^https?:\/\//, ""))}</div></span></span></td>
        <td><div class="chips">${kindChip(p.kind)}${authChip(p.auth_mode)}</div></td>
        <td><div class="chips">${statusChip(p.status)}${standaloneChip(p)}</div></td>
        <td><span class="mono">${p.tools_enabled} / ${p.tool_count}</span></td>
        <td class="small">${p.status === "published" ? `<div>shared gateway${p.tool_prefix ? ` <span class="mono">${esc(p.tool_prefix)}*</span>` : ""}</div>` : `<div class="muted">not published</div>`}${p.standalone ? `<div class="sub mono">${esc(p.standalone_url)}</div>` : ""}</td>
        <td class="actions">
          ${p.has_spec ? `<button class="btn small ${p.standalone ? "" : "link"}" data-act="${p.standalone ? "undeploy" : "deploy"}" data-id="${esc(p.id)}" title="${p.standalone ? "Stop serving " + esc(p.standalone_url) : "Serve this backend alone at " + esc(p.standalone_url)}"><i class="ph ${p.standalone ? "ph-rocket" : "ph-rocket-launch"}"></i> ${p.standalone ? "Undeploy" : "Deploy"}</button>` : `<button class="btn small link" data-act="usage" data-id="${esc(p.id)}"><i class="ph ph-robot"></i> Setup</button>`}
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
      if (act === "usage") { const p = d.items.find((x) => x.id === id); if (p?.standalone) setHash("gateway", { s: id }); else setHash("gateway", { g: "" }); return; }
      const r = await api("POST", `/api/registry/${id}/${act}`);
      if (act === "deploy") { toast("Deployed as MCP server", `${r.name} now answers at ${r.standalone_url}`, 6000); setHash("gateway", { s: id }); return; }
      if (act === "undeploy") { toast("Undeployed", `${r.standalone_url} now returns 404; the shared gateway still serves it`, 5000); }
      else toast(act === "publish" ? "Published" : "Unpublished", `${id} ${act === "publish" ? "is now reachable by agents" : "is hidden from agents"}`);
      pages.registry();
    } catch (err) { toast("Action failed", err.message, 4500); }
  });
};

// ---- MCP Gateways: a chosen set of backends on their own URL ----
pages.gateways = async () => {
  const [gw, reg] = await Promise.all([api("GET", "/api/gateways"), api("GET", "/api/registry")]);
  const servable = reg.items.filter((p) => p.has_spec || p.kind === "mcp");
  const all = { id: "", name: "Everything", url: (SERVER.public_mcp_url || location.origin + "/mcp"), backends: servable.filter((p) => p.status === "published"), tools_enabled: servable.filter((p) => p.status === "published").reduce((n, p) => n + p.tools_enabled, 0), builtin: true };
  pageActions(`<button class="btn solid" id="btn-new-gateway"><i class="ph ph-plus"></i> New gateway</button>`);
  renderTabs([{ key: "all", label: "Gateways", icon: "squares-four", count: gw.items.length + 1 }], "all", () => {},
    { title: `${gw.items.length} named gateway(s)`, sub: "plus the shared endpoint" });

  const row = (g, i) => `<tr class="row-link" data-gid="${esc(g.id)}" data-open="1">
      <td><span class="name">${logo(g.name, i)} <span>${esc(g.name)}<div class="sub">${g.builtin ? "every backend the caller is entitled to" : esc(g.description || g.id)}</div></span></span></td>
      <td class="mono small url">${esc(g.url)}<div class="sub">tools prefixed by backend id</div></td>
      <td><div class="chips">${g.backends.length ? g.backends.map((b) => chip(b.status === "published" ? "lilac" : "amber", b.name, b.status === "published" ? "" : "pencil-simple")).join("") : chip("", "none")}</div></td>
      <td><span class="mono">${g.tools_enabled}</span></td>
      <td class="actions">
        <button class="btn small" data-act="setup" data-gid="${esc(g.id)}"><i class="ph ph-robot"></i> How to connect</button>
        ${g.builtin ? "" : `<button class="btn small link" data-act="edit" data-gid="${esc(g.id)}"><i class="ph ph-pencil-simple"></i> Edit</button><button class="btn small danger" data-act="delete" data-gid="${esc(g.id)}"><i class="ph ph-trash"></i></button>`}
      </td></tr>`;
  $("#page").innerHTML = `
    <div class="table-card"><div class="table-wrap"><table>
      <tr><th>Gateway</th><th>Endpoint</th><th>Backends</th><th>Tools</th><th></th></tr>
      ${row(all, 0)}${gw.items.map((g, i) => row(g, i + 1)).join("")}
    </table></div></div>
    <div class="callout"><i class="ph ph-info"></i><span>A named gateway is one address that serves a chosen set of backends, prefixed like the shared endpoint: one connector for a team or a product line, without giving out everything. Entitlements, tool policy, tokens and audit apply unchanged. For a single backend with plain tool names, deploy it as an MCP server instead.</span></div>`;

  $("#btn-new-gateway").onclick = () => gatewayDialog(null, servable);
  $("#page").querySelectorAll("tr[data-open]").forEach((tr) => tr.onclick = (e) => {
    if (e.target.closest("button")) return;
    setHash("gateway", { g: tr.dataset.gid });
  });
  $("#page").querySelectorAll("[data-act]").forEach((b) => b.onclick = async () => {
    const { act, gid } = b.dataset;
    const g = gid ? gw.items.find((x) => x.id === gid) : all;
    if (act === "setup") { setHash("gateway", { g: g.id }); return; }
    if (act === "edit") return gatewayDialog(g, servable);
    if (act === "delete") {
      if (!confirm(`Delete gateway ${g.name}? Its address stops answering at once; the backends stay registered.`)) return;
      try { await api("DELETE", `/api/gateways/${gid}`); toast("Gateway deleted", g.url); pages.gateways(); } catch (err) { toast("Delete failed", err.message, 4500); }
    }
  });
};

function gatewayDialog(g, servable) {
  const picked = new Set(g ? g.backends.map((b) => b.id) : []);
  modal(`<h2><i class="ph ph-squares-four"></i> ${g ? "Edit gateway" : "New gateway"}</h2>
    <form id="gw-form" class="form">
      <label class="field">Name <input name="name" value="${esc(g?.name || "")}" placeholder="e.g. Sales Team" required ${g ? "readonly" : ""}>
        ${g ? "" : `<span class="muted small">Becomes the address: ${esc(SERVER.public_mcp_url || location.origin + "/mcp")}/&lt;name&gt;</span>`}</label>
      <label class="field">Description <input name="description" value="${esc(g?.description || "")}" placeholder="who this gateway is for"></label>
      <div class="field"><span>Backends served</span>
        <div class="card" style="padding:10px 14px;gap:6px">${servable.length ? servable.map((p) => `<label class="check"><input type="checkbox" name="providers" value="${esc(p.id)}" ${picked.has(p.id) ? "checked" : ""}> ${esc(p.name)} <span class="muted small">${p.tools_enabled} tools${p.status === "published" ? "" : ", draft"}</span></label>`).join("") : `<span class="muted small">Register a backend first.</span>`}</div></div>
      <div style="display:flex;justify-content:flex-end;gap:8px"><button type="button" class="btn" id="gw-cancel">Cancel</button><button class="btn solid" type="submit"><i class="ph ph-check"></i> ${g ? "Save" : "Create gateway"}</button></div>
      <p class="error" id="gw-error"></p>
    </form>`);
  $("#gw-cancel").onclick = closeModal;
  $("#gw-form").onsubmit = async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    const body = { name: f.get("name"), description: f.get("description"), providers: f.getAll("providers") };
    try {
      const r = g ? await api("PATCH", `/api/gateways/${g.id}`, body) : await api("POST", "/api/gateways", body);
      closeModal(); toast(g ? "Gateway updated" : "Gateway created", `${r.name} answers at ${r.url}`, 6000); pages.gateways();
    } catch (err) { $("#gw-error").textContent = err.message; }
  };
}

// ---- MCP Servers: one deployed server per product, next to the shared gateway ----
pages.servers = async () => {
  const d = await api("GET", "/api/registry");
  const deployable = d.items.filter((p) => p.has_spec);  // MCP-kind backends are already MCP servers
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
            ? `<button class="btn small" data-act="usage" data-id="${esc(p.id)}"><i class="ph ph-robot"></i> How to connect</button><button class="btn small danger" data-act="undeploy" data-id="${esc(p.id)}"><i class="ph ph-rocket"></i> Undeploy</button>`
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
    const p = rows.find((x) => x.id === tr.dataset.open);
    if (p?.standalone) setHash("gateway", { s: tr.dataset.open }); else setHash("provider", { p: tr.dataset.open });
  });
  $("#page").querySelectorAll("[data-act]").forEach((b) => b.onclick = async () => {
    const { act, id } = b.dataset;
    try {
      if (act === "usage") { setHash("gateway", { s: id, c: "chatgpt" }); return; }
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
      setHash("gateway", { s: pid, c: "chatgpt" });
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
      <label class="field">Provider name <input name="name" placeholder="e.g. Orders API" required></label>
      <label class="field"><span id="reg-base-label">Base URL of the existing API</span> <input name="base_url" id="reg-base" placeholder="https://api.example.com" required></label>
      <label class="field"><span id="reg-mode-label">How is the API protected?</span>
        <select name="auth_mode" id="reg-mode">
          <option value="bearer">Bearer token: it rejects anonymous calls (recommended)</option>
          <option value="network">Network-isolated: no token, only the gateway's address can reach it</option>
          <option value="open">Open: anyone can call it (demo data only, recorded as accepted risk)</option>
          <option value="oauth">OAuth: each user links their own account; the gateway sends that user's token</option>
          <option value="login">Login endpoint: it has its own username-and-password sign-in; the gateway signs in and sends the token</option>
        </select></label>
      <label class="field" id="reg-token-field">Service bearer token the gateway will send <input name="service_token" placeholder="issued by the provider (stored, never shown again)"></label>
      <label class="field hidden" id="reg-allowlist-field">Gateway address the API allows <input name="allowlist" placeholder="e.g. 203.0.113.10 or 10.0.0.0/24"></label>
      <div class="hidden" id="reg-oauth-fields">${oauthFields("reg")}</div>
      <div class="hidden" id="reg-login-fields">${loginFields("reg")}</div>
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
    $("#reg-login-fields").classList.toggle("hidden", m !== "login");
  };
  bindLoginFields("reg");
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
          setHash("gateway", { s: p.id, c: "chatgpt" }); return;
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
  if (!(via.needsToken ?? (SERVER.require_agent_token !== false))) return commandResult(p, null, via);
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
      <label class="field">How is the ${p.kind === "mcp" ? "MCP server" : "API"} protected?
        <select name="auth_mode" id="ed-mode">
          ${opt("bearer", "Bearer token: the API rejects anonymous calls")}
          ${opt("network", "Network-isolated: no token, only the gateway's address can reach it")}
          ${opt("open", "Open: anyone can call it (demo data only, recorded as accepted risk)")}
          ${opt("oauth", "OAuth: each user links their own account; the gateway sends that user's token")}
          ${opt("login", "Login endpoint: the gateway signs in with a username and password")}
        </select></label>
      <label class="field ${p.auth_mode === "bearer" ? "" : "hidden"}" id="ed-token-field">Service bearer token <input name="service_token" placeholder="leave blank to keep the stored one"></label>
      <label class="field ${p.auth_mode === "network" ? "" : "hidden"}" id="ed-allowlist-field">Gateway address the API allows <input name="allowlist" value="${esc(p.allowlist || "")}" placeholder="e.g. 203.0.113.10"></label>
      <div class="${p.auth_mode === "oauth" ? "" : "hidden"}" id="ed-oauth-fields">${oauthFields("ed", p.oauth || {})}</div>
      <div class="${p.auth_mode === "login" ? "" : "hidden"}" id="ed-login-fields">${loginFields("ed", p.login || {}, p.service_account || {})}</div>
      <div style="display:flex;justify-content:flex-end;gap:8px"><button type="button" class="btn" id="ed-cancel">Cancel</button><button class="btn solid" type="submit"><i class="ph ph-check"></i> Save</button></div>
      <p class="error" id="ed-error"></p>
    </form>`);
  $("#ed-cancel").onclick = closeModal;
  $("#ed-mode").onchange = (e) => {
    $("#ed-token-field").classList.toggle("hidden", e.target.value !== "bearer");
    $("#ed-allowlist-field").classList.toggle("hidden", e.target.value !== "network");
    $("#ed-oauth-fields").classList.toggle("hidden", e.target.value !== "oauth");
    $("#ed-login-fields").classList.toggle("hidden", e.target.value !== "login");
  };
  bindLoginFields("ed");
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
    $("#t-close").onclick = () => { closeModal(); refreshPage(); };
    if (suggestOpen) {
      $("#t-open").onclick = async () => {
        try { await api("PATCH", `/api/registry/${id}`, { auth_mode: "open" }); toast("Switched to Open mode", "Recorded as an accepted risk"); testDialog(id); }
        catch (err) { toast("Could not switch", err.message, 4500); }
      };
    }
  } catch (err) { modal(`<h2>Connection test</h2><p class="error">${esc(err.message)}</p>`); }
}

// ---- Access control ----
/** Entitlement + tool policy for one backend, rendered inside its page. */
/** How a parameter's value is chosen: a <select> of the kinds, plus a value box for fixed and default. */
const SOURCE_KINDS = (sources) => [["", "Asked from the model"], ...Object.entries(sources).map(([k, l]) => [`caller:${k}`, `Filled with ${l}`]), ["fixed", "Fixed value, hidden from the model"], ["default", "Default, used when the model leaves it out"]];
function sourceControl(sources, current, id) {
  const cur = current ? (current.kind === "caller" ? `caller:${current.value}` : current.kind) : "";
  const showValue = cur === "fixed" || cur === "default";
  return `<select data-k="kind" aria-label="Where ${esc(id)} comes from">${SOURCE_KINDS(sources).map(([v, l]) => `<option value="${esc(v)}" ${v === cur ? "selected" : ""}>${esc(l)}</option>`).join("")}</select>
    <input data-k="value" class="mono ${showValue ? "" : "hidden"}" value="${esc(showValue ? (typeof current.value === "string" ? current.value : JSON.stringify(current.value)) : "")}" placeholder="value" aria-label="Value for ${esc(id)}" style="min-width:120px">`;
}
function readSource(tr) {
  const kind = tr.querySelector("[data-k=kind]").value, value = tr.querySelector("[data-k=value]").value;
  if (!kind) return null;
  if (kind.startsWith("caller:")) return { kind: "caller", value: kind.slice(7) };
  return value.trim() ? { kind, value } : null;
}
function bindSourceControls(root) {
  root.querySelectorAll("[data-k=kind]").forEach((sel) => sel.onchange = () => { const v = sel.value; sel.parentElement.querySelector("[data-k=value]").classList.toggle("hidden", v !== "fixed" && v !== "default"); });
}

/** Notes for the model, where each parameter's value comes from, and which tool produces which id: per backend, inherited by every gateway. */
function guidanceSection(p, params) {
  const toolName = (n) => { const t = params.tools.find((x) => x.name === n); return t?.alias || n; };
  const producerSelect = (tools, sel, param) => `<select data-k="producer" aria-label="Where ${esc(param)} comes from"><option value="">not set</option>${tools.map((t) => `<option value="${esc(t.name)}" ${t.name === sel ? "selected" : ""}>from ${esc(t.alias || t.name)}</option>`).join("")}</select>`;
  const originRow = (o) => {
    const key = `${o.tool}.${o.param}`;
    if (o.fixed || o.default) {  // typed before values moved to the gateway pages: kept until removed, set per gateway from now on
      const typed = o.fixed ? o.confirmed.value : o.confirmed.default;
      return `<tr data-typed="${esc(key)}"><td class="mono">${esc(toolName(o.tool))}<span class="muted">.</span>${esc(o.param)}</td>
        <td class="small">${o.fixed ? "Fixed value" : "Default"} <span class="mono">${esc(typeof typed === "string" ? typed : JSON.stringify(typed))}</span>${o.enabled === false ? " (off)" : ""}, set here earlier. Values are now set on each gateway's page; this one still applies to every gateway until removed.</td>
        <td><button class="btn small link" data-k="remove"><i class="ph ph-x"></i> Remove</button></td>
        <td class="small muted">set by hand</td></tr>`;
    }
    const top = o.seen[0];
    const producer = o.confirmed?.tool || (top ? top.origin.split(".")[0].split(":").pop() : "");
    const field = o.confirmed?.field ?? (top ? top.origin.split(".").slice(1).join(".") : "");
    return `<tr data-origin="${esc(key)}"><td class="mono">${esc(toolName(o.tool))}<span class="muted">.</span>${esc(o.param)}</td>
      <td><div class="cell-row">${producerSelect(params.tools, producer, o.param)}
        <input data-k="field" class="mono" value="${esc(field)}" placeholder="field, e.g. id" style="min-width:110px"></div></td>
      <td class="small">${o.confirmed ? chip("green", "Confirmed", "check") : chip("amber", "Seen, not confirmed", "eye")}</td>
      <td class="small muted">${o.seen.length ? o.seen.map((s) => `${esc(s.origin)} × ${s.count}`).join(", ") : "set by hand"}</td></tr>`;
  };
  return `
    <div id="guidance">
      <div class="section-head"><h2 class="section-title">Guidance for the model</h2>${p.instructions ? chip("green", "Usage notes set", "check") : chip("amber", "No usage notes", "warning")}${Object.keys(p.comes_from || {}).length ? chip("lilac", `${Object.keys(p.comes_from).length} origin(s)`, "flow-arrow") : ""}</div>
      <div class="card settings-list">
        <div class="setting stacked"><div class="setting-text"><strong>How to use this backend</strong><p class="muted small">Sent to the model when it connects, on every gateway that serves this backend. Say which tool to call first and which next, in plain steps, and what never to ask the user for.</p></div>
          <div class="setting-ctl"><textarea id="gd-notes" rows="5" style="width:100%;min-height:110px" placeholder="To answer a question: 1) call the list tool to find the right item, 2) call the detail tool with its id. Never ask the user for an id or a company number.">${esc(p.instructions || "")}</textarea></div></div>
        <div class="setting"><div class="setting-text"><strong>Filled in from the signed-in user</strong><p class="muted small">${params.items.some((x) => x.implicit) ? `The gateway fills in <span class="mono">${esc(params.items.filter((x) => x.implicit).map((x) => x.name).join(", "))}</span> from the caller's company on every call and never shows ${params.items.filter((x) => x.implicit).length > 1 ? "them" : "it"} to the model, so the model cannot ask for the wrong company.` : "This backend's tools take no company parameter, so nothing is filled in automatically."}</p></div></div>
        <div class="setting stacked"><div class="setting-text"><strong>Which tool produces which id</strong><p class="muted small">"getItem needs an itemId, which listItems returns in field id." This is a fact about the API, so it holds on every gateway: the gateway writes it into the tool's description and, when a call arrives without the value, tells the model what to call first. Rows marked seen were observed in real calls: a value one tool returned was used by another. A fixed value or a default for a parameter depends on who is using it, so those are set on each gateway's page.</p></div>
          <div class="setting-ctl"><div class="table-wrap"><table id="gd-origins">
            <tr><th>Parameter</th><th>Comes from</th><th></th><th>Observed</th></tr>
            ${params.origins.map(originRow).join("")}
            <tr id="gd-origin-new"><td style="min-width:300px"><div class="cell-row"><select data-k="new-tool" aria-label="Tool"><option value="">tool…</option>${params.tools.map((t) => `<option value="${esc(t.name)}">${esc(t.alias || t.name)}</option>`).join("")}</select><select data-k="new-param" aria-label="Parameter"><option value="">parameter…</option></select></div></td>
              <td><div class="cell-row">${producerSelect(params.tools, "", "new")}<input data-k="field" class="mono" placeholder="field, e.g. id" style="min-width:110px"></div></td>
              <td colspan="2" class="small muted">Add a row by hand</td></tr>
          </table></div></div></div>
        <div class="setting"><div class="setting-text"><p class="muted small" style="margin:0">Applies on the next connection. A caller with no token has no identity to fill in, so they keep seeing those parameters.</p></div>
          <div class="setting-ctl"><button class="btn solid small" id="gd-save"><i class="ph ph-check"></i> Save guidance</button></div></div>
      </div>
    </div>
    <div id="flows">
      <div class="section-head"><h2 class="section-title">Workflows of ${esc(p.name)}</h2><button class="btn small" id="wf-add"><i class="ph ph-plus"></i> New workflow</button></div>
      ${workflowTable(p.workflows || [], [], "A workflow is a fixed sequence of this backend's tools published as one extra tool, on every gateway that serves the backend. The model may use it or call the tools itself.")}
    </div>`;
}

/** The workflows table used on backend and gateway pages; inherited rows are read-only here. */
function workflowTable(own, inherited, hint) {
  const row = (w, i, from) => `<tr><td><strong class="mono">${esc(w.name)}</strong><div class="sub">${esc(w.description)}${from ? ` · from <a href="#provider?p=${esc(from)}">${esc(from)}</a>` : ""}</div></td><td class="mono small">${esc(Object.keys(w.inputs || {}).join(", ") || "none")}</td><td class="small">${w.steps.map((s, n) => `${n + 1}. <span class="mono">${esc(s.tool)}</span>`).join("<br>")}</td><td class="actions">${from ? `<span class="muted small">inherited</span>` : `<button class="btn small" data-wf-edit="${i}"><i class="ph ph-pencil-simple"></i> Edit</button> <button class="btn small danger" data-wf-del="${i}"><i class="ph ph-trash"></i></button>`}</td></tr>`;
  return `<div class="table-card"><div class="table-wrap"><table>
        <tr><th>Tool the model sees</th><th>Inputs</th><th>Steps, in order</th><th></th></tr>
        ${own.length || inherited.length ? own.map((w, i) => row(w, i, null)).join("") + inherited.map((w) => row(w, -1, w.backend)).join("")
          : `<tr><td colspan="4">${emptyState("flow-arrow", "No workflows yet", hint)}</td></tr>`}
      </table></div></div>`;
}

/** Wire the New / Edit / Delete buttons of a workflows table to a save function that stores the whole list. */
function gatewayValuesSection(es, told) {
  const rows = es.effective_values || [];
  const backends = (told.backends || []).map((b) => ({ ...b, tools: b.tools.filter((t) => t.enabled && (t.params || []).length) })).filter((b) => b.tools.length);
  const kindSelect = (sel) => `<select data-k="kind" aria-label="Kind" style="min-width:150px"><option value="value" ${sel === "value" ? "selected" : ""}>fixed (hidden)</option><option value="default" ${sel === "default" ? "selected" : ""}>default (may change)</option></select>`;
  const show = (v) => v == null ? "" : typeof v === "string" ? v : JSON.stringify(v);
  const row = (r) => `<tr data-gv="${esc(r.backend)}|${esc(r.tool)}.${esc(r.param)}" data-inherited="${r.inherited ? 1 : 0}" data-bkind="${esc(r.backend_kind || "")}" data-bvalue="${esc(show(r.backend_value))}">
      <td>${esc(r.backend_name)}</td><td class="mono">${esc(r.alias || r.tool)}<span class="muted">.</span>${esc(r.param)}</td>
      <td>${kindSelect(r.kind)}</td>
      <td><input data-k="value" class="mono" value="${esc(r.changed && r.value != null ? show(r.value) : "")}" placeholder="${r.inherited ? esc(show(r.backend_value)) : "the value"}" style="min-width:120px"></td>
      <td><input type="checkbox" class="switch" data-k="on" ${r.enabled ? "checked" : ""} aria-label="On"></td>
      <td class="small">${r.inherited ? (r.changed ? chip("lilac", "Changed here", "pencil-simple") : chip("", "From the backend", "arrow-elbow-down-right")) : chip("lilac", "This gateway only", "push-pin")}${r.inherited && r.changed ? ` <button class="btn small link" data-gv-reset><i class="ph ph-arrow-counter-clockwise"></i> Use the backend's</button>` : ""}${!r.inherited ? ` <button class="btn small link" data-gv-remove><i class="ph ph-x"></i></button>` : ""}</td></tr>`;
  return `<div id="gvalues">
      <div class="section-head"><h2 class="section-title">Values for this gateway</h2>${rows.length ? chip("lilac", `${rows.filter((r) => r.enabled).length} of ${rows.length} in use`, "sliders-horizontal") : ""}</div>
      <div class="card settings-list">
        <div class="setting stacked"><div class="setting-text"><strong>Fixed values and defaults</strong><p class="muted small">A value that belongs to the people who use this gateway: their project, their team's usual choice. A fixed value is sent on every call and hidden from the model; a default is shown to the model and used only when it leaves the parameter out. Pick the backend, the tool and the parameter, type the value, and switch it off whenever it should not apply.</p></div>
          <div class="setting-ctl"><div class="table-wrap"><table id="gv-table">
            <tr><th>Backend</th><th>Parameter</th><th>Kind</th><th>Value here</th><th>On</th><th></th></tr>
            ${rows.map(row).join("")}
            <tr id="gv-new"><td colspan="2" style="min-width:420px"><div class="cell-row" style="flex-wrap:nowrap"><select data-k="new-backend" aria-label="Backend"><option value="">backend…</option>${backends.map((b) => `<option value="${esc(b.id)}">${esc(b.name)}</option>`).join("")}</select><select data-k="new-tool" aria-label="Tool"><option value="">tool…</option></select><select data-k="new-param" aria-label="Parameter"><option value="">parameter…</option></select></div></td>
              <td>${kindSelect("value")}</td><td><input data-k="value" class="mono" placeholder="the value" style="min-width:120px"></td><td><input type="checkbox" class="switch" data-k="on" checked aria-label="On"></td><td class="small muted">Add a value for this gateway</td></tr>
          </table></div></div></div>
        <div class="setting"><div class="setting-text"><p class="muted small" style="margin:0">Applies on the next connection. Other gateways are not affected.</p></div>
          <div class="setting-ctl"><button class="btn solid small" id="gv-save"><i class="ph ph-check"></i> Save values</button></div></div>
      </div>
    </div>`;
}

function bindGatewayValues(es, told, settingsKey) {
  if (!$("#gv-save")) return;
  const backends = told.backends || [];
  const nb = $("#gv-new [data-k=new-backend]"), nt = $("#gv-new [data-k=new-tool]"), np = $("#gv-new [data-k=new-param]");
  nb.onchange = () => { const b = backends.find((x) => x.id === nb.value); nt.innerHTML = `<option value="">tool…</option>` + (b?.tools || []).filter((t) => t.enabled && (t.params || []).length).map((t) => `<option value="${esc(t.name)}">${esc(t.alias || t.name)}</option>`).join(""); np.innerHTML = `<option value="">parameter…</option>`; };
  nt.onchange = () => { const b = backends.find((x) => x.id === nb.value); const t = (b?.tools || []).find((x) => x.name === nt.value); np.innerHTML = `<option value="">parameter…</option>` + (t?.params || []).map((q) => `<option value="${esc(q)}">${esc(q)}</option>`).join(""); };
  $("#page").querySelectorAll("#gv-table [data-gv-remove]").forEach((b) => b.onclick = () => b.closest("tr").remove());
  $("#page").querySelectorAll("#gv-table [data-gv-reset]").forEach((b) => b.onclick = () => { const tr = b.closest("tr"); tr.querySelector("[data-k=value]").value = ""; tr.querySelector("[data-k=kind]").value = tr.dataset.bkind; tr.querySelector("[data-k=on]").checked = true; tr.dataset.reset = "1"; b.remove(); });
  $("#gv-save").onclick = async () => {
    const values = {};
    const put = (pid, key, kind, text, on, inherited, bkind) => {
      const change = {};
      if (text) change[kind] = text;
      else if (inherited && kind !== bkind) change[kind] = $("#page").querySelector(`tr[data-gv="${CSS.escape(pid)}|${CSS.escape(key)}"]`).dataset.bvalue;
      if (!on) change.enabled = false;
      if (!inherited && !text) return;  // a gateway-only row needs a value
      if (Object.keys(change).length) (values[pid] ||= {})[key] = change;
    };
    $("#page").querySelectorAll("#gv-table tr[data-gv]").forEach((tr) => {
      const [pid, key] = tr.dataset.gv.split("|");
      put(pid, key, tr.querySelector("[data-k=kind]").value, tr.querySelector("[data-k=value]").value.trim(), tr.querySelector("[data-k=on]").checked, tr.dataset.inherited === "1", tr.dataset.bkind);
    });
    if (nb.value && nt.value && np.value) put(nb.value, `${nt.value}.${np.value}`, $("#gv-new [data-k=kind]").value, $("#gv-new [data-k=value]").value.trim(), $("#gv-new [data-k=on]").checked, false, "");
    try {
      const r = await api("PUT", `/api/endpoints/${settingsKey}/settings`, { values });
      const n = Object.values(r.values || {}).reduce((a, m) => a + Object.keys(m).length, 0);
      toast("Values saved", n ? `${n} value(s) set for this gateway` : "This gateway uses the backends' own values"); pages.gateway();
    } catch (err) { toast("Save failed", err.message, 4500); }
  };
}

function bindWorkflows(own, allTools, save, after) {
  if (!$("#wf-add")) return;
  $("#wf-add").onclick = () => workflowDialog(null, own, allTools, save, after);
  $("#page").querySelectorAll("[data-wf-edit]").forEach((b) => b.onclick = () => workflowDialog(Number(b.dataset.wfEdit), own, allTools, save, after));
  $("#page").querySelectorAll("[data-wf-del]").forEach((b) => b.onclick = async () => {
    const i = Number(b.dataset.wfDel);
    if (!confirm(`Remove workflow ${own[i].name}?`)) return;
    try { await save(own.filter((_, n) => n !== i)); toast("Workflow removed"); after(); } catch (err) { toast("Save failed", err.message, 4500); }
  });
}

function accessSection(p, d, known, params) {
  const access = p.access || { mode: "everyone", groups: [], companies: [] };
  const whoLabel = access.mode === "groups" ? `groups: ${access.groups.join(", ")}` : access.mode === "companies" ? `companies: ${access.companies.join(", ")}` : "everyone with a token";
  return `
    <div id="access">
      <div class="section-head"><h2 class="section-title">Who can use ${esc(p.name)}</h2>${access.mode === "everyone" ? chip("", "Everyone", "users") : chip("lilac", whoLabel, "users-three")}</div>
      <div class="card settings-list" id="access-card">
        <div class="setting"><div class="setting-text"><strong>Entitlement</strong><p class="muted small">Decides which callers see this backend at all, on every gateway that serves it. Everyone else gets no tools from it and is refused if they try. Tool policy below applies on top.</p></div>
          <div class="setting-ctl"><select id="acc-mode" aria-label="Who can use this backend">
            <option value="everyone" ${access.mode === "everyone" ? "selected" : ""}>Everyone with a token</option>
            <option value="groups" ${access.mode === "groups" ? "selected" : ""}>Only these access groups</option>
            <option value="companies" ${access.mode === "companies" ? "selected" : ""}>Only these companies</option>
          </select></div></div>
        <div class="setting ${access.mode === "groups" ? "" : "hidden"}" id="acc-groups-row"><div class="setting-text"><strong>Access groups</strong><p class="muted small">Comma separated. A caller needs any one of them on their agent token${known.length ? `. In use: ${esc(known.join(", "))}` : ""}.</p></div>
          <div class="setting-ctl"><input id="acc-groups" class="ctl-wide" value="${esc(access.groups.join(", "))}" placeholder="finance, hr" list="acc-known"><datalist id="acc-known">${known.map((g) => `<option value="${esc(g)}">`).join("")}</datalist></div></div>
        <div class="setting ${access.mode === "companies" ? "" : "hidden"}" id="acc-companies-row"><div class="setting-text"><strong>Companies</strong><p class="muted small">Comma separated company ids, matched against the company on the caller's token.</p></div>
          <div class="setting-ctl"><input id="acc-companies" class="ctl-wide" value="${esc(access.companies.join(", "))}" placeholder="1234567890, 9876543210"></div></div>
        <div class="setting"><div class="setting-text"><p class="muted small" style="margin:0">Applies on the next call, on the shared gateway, named gateways and this backend's own MCP server alike.</p></div>
          <div class="setting-ctl"><button class="btn solid small" id="acc-save"><i class="ph ph-check"></i> Save entitlement</button></div></div>
      </div>
    </div>
    ${params ? guidanceSection(p, params) : ""}
    <div>
      <div class="section-head"><h2 class="section-title">Tool policy</h2><span class="muted small">${d.items.filter((t) => t.enabled).length} of ${d.items.length} enabled</span></div>
      <div class="table-card"><div class="table-wrap"><table><tr><th>Tool</th><th>Kind</th><th>Enabled</th><th>Allowed roles</th><th>Only these groups</th><th>Confirm before call</th></tr>
      ${d.items.map((t) => `<tr data-name="${esc(t.name)}">
        <td class="tool"><input data-k="alias" class="mono tool-alias" value="${esc(t.alias || "")}" placeholder="${esc(t.name)}" aria-label="Tool name the agent calls" title="The name clients see. Blank keeps ${esc(t.name)}">${t.alias ? `<div class="muted small mono">was ${esc(t.name)}</div>` : ""}${t.route ? `<div class="muted small mono">${esc(t.route)}</div>` : ""}
          <input data-k="description" class="desc" value="${esc(t.description || "")}" placeholder="${esc(t.generated || t.summary || "Describe what this tool does, for the model")}" aria-label="Description the model sees" title="What the model reads when choosing a tool. Blank keeps the text from the spec or server: ${esc(t.generated || t.summary || "(none)")}"></td>
        <td>${t.kind === "write" ? chip("amber", "write", "pencil-simple") : chip("lilac", "read", "eye")}</td>
        <td><input type="checkbox" class="switch" data-k="enabled" ${t.enabled ? "checked" : ""} aria-label="Enabled"></td>
        <td class="nowrap">${d.roles.map((r) => `<label class="check"><input type="checkbox" data-k="role" value="${r}" ${t.roles.includes(r) ? "checked" : ""}>${r}</label>`).join(" ")}</td>
        <td><input data-k="groups" value="${esc((t.groups || []).join(", "))}" placeholder="inherit from backend" list="acc-known" aria-label="Only these groups" style="min-width:150px"></td>
        <td><input type="checkbox" class="switch" data-k="confirm" ${t.confirm ? "checked" : ""} ${t.kind === "read" ? "disabled" : ""} aria-label="Confirm before call"></td>
      </tr>`).join("")}</table></div></div>
      <p class="muted small" style="margin-top:8px">The description field is what the model reads when it chooses a tool; the placeholder shows what the spec or server provides today. A tool with groups listed is shown only to callers in one of them; blank means every entitled caller. Changes apply on the next call.</p>
    </div>`;
}

function bindAccess(pid, reload, params = { tools: [] }) {
  $("#acc-mode").onchange = (e) => {
    $("#acc-groups-row").classList.toggle("hidden", e.target.value !== "groups");
    $("#acc-companies-row").classList.toggle("hidden", e.target.value !== "companies");
  };
  $("#acc-save").onclick = async () => {
    try {
      const r = await api("PATCH", `/api/registry/${pid}`, { access: { mode: $("#acc-mode").value, groups: $("#acc-groups").value, companies: $("#acc-companies").value } });
      toast("Entitlement saved", r.access.mode === "everyone" ? "Everyone with a token can use it" : `Limited to ${r.access.mode}: ${(r.access[r.access.mode] || []).join(", ")}`);
      reload();
    } catch (err) { toast("Save failed", err.message, 4500); }
  };
  bindWorkflows(params.workflows || [], (params.tools || []).filter((t) => t.enabled !== false).map((t) => ({ name: t.alias || t.name, params: t.params })),
    (next) => api("PATCH", `/api/registry/${pid}`, { workflows: next }), reload);
  if ($("#gd-save")) {
    bindSourceControls($("#guidance"));
    const newTool = $("#gd-origin-new [data-k=new-tool]"), newParam = $("#gd-origin-new [data-k=new-param]");
    $("#page").querySelectorAll("#gd-origins tr[data-typed] [data-k=remove]").forEach((b) => b.onclick = () => b.closest("tr").remove());
    if (newTool) newTool.onchange = () => { const t = (params.tools || []).find((x) => x.name === newTool.value); newParam.innerHTML = `<option value="">parameter…</option>` + (t?.params || []).map((q) => `<option value="${esc(q)}">${esc(q)}</option>`).join(""); };
    $("#gd-save").onclick = async () => {
      const comes_from = {};
      const spec = (producer, text) => ({ tool: producer, field: text });
      $("#page").querySelectorAll("tr[data-typed]").forEach((tr) => { comes_from[tr.dataset.typed] = (p.comes_from || {})[tr.dataset.typed]; });  // older typed values stay until removed
      $("#page").querySelectorAll("tr[data-origin]").forEach((tr) => { const t = tr.querySelector("[data-k=producer]").value; if (t) comes_from[tr.dataset.origin] = spec(t, tr.querySelector("[data-k=field]").value.trim()); });
      if (newTool?.value && newParam?.value && $("#gd-origin-new [data-k=producer]").value) comes_from[`${newTool.value}.${newParam.value}`] = spec($("#gd-origin-new [data-k=producer]").value, $("#gd-origin-new [data-k=field]").value.trim());
      try {
        const r = await api("PATCH", `/api/registry/${pid}`, { instructions: $("#gd-notes").value, comes_from });
        toast("Guidance saved", `${r.instructions ? "Usage notes set" : "No usage notes"}; ${Object.keys(r.comes_from || {}).length} origin(s)`); reload();
      } catch (err) { toast("Save failed", err.message, 4500); }
    };
  }
  $("#page").querySelectorAll("tr[data-name] input").forEach((inp) => inp.onchange = async () => {
    const tr = inp.closest("tr"); const name = tr.dataset.name;
    const body = {
      enabled: tr.querySelector('[data-k=enabled]').checked,
      confirm: tr.querySelector('[data-k=confirm]').checked,
      roles: [...tr.querySelectorAll('[data-k=role]:checked')].map((x) => x.value),
      groups: tr.querySelector('[data-k=groups]').value,
      description: tr.querySelector('[data-k=description]').value,
      alias: tr.querySelector('[data-k=alias]').value,
    };
    try { await api("PUT", `/api/registry/${pid}/tools/${name}`, body); toast("Policy saved", body.alias ? `${name} is now ${body.alias}` : name); if (inp.dataset.k === "alias") reload(); }
    catch (err) { toast("Save failed", err.message, 4500); }
  });
}

// Old links to the Access Control page land on the backend's own page.
pages.access = async () => { const p = hashParam("p"); if (p) setHash("provider", { p }); else location.hash = "registry"; };

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
        <td><span class="name">${logo(t.label, i)} <span>${esc(t.label)}<div class="sub mono">${esc(t.hint)}</div></span></span></td>
        <td class="nowrap"><strong>${esc(t.user_name || t.sub)}</strong><div class="sub"><span class="mono">${esc(t.sub)}</span> · ${esc(t.role)}${(t.groups || []).length ? ` · ${esc(t.groups.join(", "))}` : ""}</div></td>
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

/** A <select> of directory users, with a read-only preview of the picked one's role, company and groups. */
const NEW_USER = "__new__";
function userPicker(users, selected) {
  const opt = (u) => `<option value="${esc(u.id)}" ${u.id === selected ? "selected" : ""}>${esc(u.name)} · ${esc(u.id)}</option>`;
  return `<label class="field">User <select name="user_id" id="pick-user" required>${users.map(opt).join("")}<option value="${NEW_USER}">Someone not listed…</option></select>
      <span class="muted small">Role, company and groups come from the <a href="#users">Users</a> page, so they cannot disagree with the token.</span></label>
    <div class="pick-preview" id="pick-preview"></div>
    <div id="pick-new" class="form-2 hidden">
      <label class="field">Bizplay user id <input name="new_id" placeholder="u1001" pattern="[a-z0-9_-]+"><span class="muted small">Added to the Users page as well.</span></label>
      <label class="field">Name <input name="new_name" placeholder="Full name"></label>
      <label class="field">Role <select name="new_role"><option value="employee">employee</option><option value="manager">manager</option></select></label>
      <label class="field">Access groups <input name="new_groups" placeholder="finance, hr (comma separated)"></label>
    </div>`;
}
function bindUserPicker(users) {
  const show = () => {
    const v = $("#pick-user").value, u = users.find((x) => x.id === v);
    $("#pick-new").classList.toggle("hidden", v !== NEW_USER);
    $("#pick-new [name=new_id]").required = v === NEW_USER;
    $("#pick-preview").innerHTML = u ? `${chip("", u.role, "identification-badge")}${chip("", u.company || "1078836129", "buildings")}${(u.groups || []).length ? u.groups.map((g) => chip("lilac", g, "users-three")).join("") : chip("", "no groups", "users-three")}` : "";
  };
  $("#pick-user").onchange = show; show();
}
/** Form fields → API body: a typed-in person becomes user_id plus the fields that create them. */
function pickedUser(f) {
  if (f.user_id !== NEW_USER) return { user_id: f.user_id };
  return { user_id: (f.new_id || "").trim().toLowerCase(), name: (f.new_name || "").trim(), role: f.new_role || "employee", groups: f.new_groups || "" };
}

/** Does an endpoint's entitlement rule admit a person with these groups and company? */
function entitled(access, who) {
  const a = access || { mode: "everyone" };
  const groups = new Set(who.groups || []);
  if (a.mode === "groups") return (a.groups || []).some((g) => groups.has(g));
  if (a.mode === "companies") return (a.companies || []).includes(who.company);
  return true;
}

/** Where a fresh token is used: the public address if set, else this portal's own /mcp. */
const agentUrl = () => SERVER.public_mcp_url || SERVER.default_mcp_url || SERVER.portal_mcp_url || `${location.origin}/mcp`;

async function issueDialog(after) {
  const me = session.user;
  const users = isAdmin() ? (await api("GET", "/api/users")).items : [{ id: me.user_id, name: me.name, role: me.user_role, company: me.company, groups: me.groups || [] }];
  if (!users.length) { toast("No users yet", "Add the person on the Users page first", 4500); return; }
  modal(`<h2><i class="ph ph-key"></i> Issue an agent token</h2>
    <form id="tok-form" class="form">
      <label class="field">Label <input name="label" placeholder="${esc(users[0].name.split(" ")[0])}'s Claude Desktop" required></label>
      ${isAdmin() ? userPicker(users, me.user_id || users[0].id) : `<div class="who-card"><span class="avatar">${esc(initials(me.name))}</span><div><div class="who-name">${esc(me.name)}</div><div class="who-meta"><span class="mono">${esc(me.user_id)}</span> · ${esc(me.user_role || "employee")}${(me.groups || []).length ? ` · ${esc(me.groups.join(", "))}` : ""}</div></div></div>`}
      <label class="field">Expires in (days) <input name="ttl_days" type="number" value="30" min="1" max="365"><span class="muted small">The token works from any MCP client; say which one in the label.</span></label>
      <div style="display:flex;justify-content:flex-end;gap:8px"><button type="button" class="btn" id="tok-cancel">Cancel</button><button class="btn solid" type="submit"><i class="ph ph-check"></i> Issue</button></div>
      <p class="error" id="tok-error"></p></form>`);
  if (isAdmin()) bindUserPicker(users);
  $("#tok-cancel").onclick = closeModal;
  $("#tok-form").onsubmit = async (e) => {
    e.preventDefault(); const f = Object.fromEntries(new FormData(e.target));
    try {
      const r = await api("POST", "/api/tokens", { label: f.label, ttl_days: f.ttl_days, ...(isAdmin() ? pickedUser(f) : {}) });
      // The endpoints this token opens: the named gateways the person is entitled to. The shared
      // endpoint is offered only when there is no named gateway for them.
      const gws = (await api("GET", "/api/gateways").catch(() => ({ items: [] }))).items.filter((g) => entitled(g.access, r.record));
      const targets = gws.length ? gws.map((g) => ({ label: g.name, url: g.url, id: g.id })) : [{ label: "Shared gateway", url: agentUrl(), id: "" }];
      modal(`<h2><i class="ph ph-check-circle"></i> Token issued</h2><p>Copy it now. It will not be shown again.</p>
        <div class="token-box"><code id="tok-value">${esc(r.token)}</code><button class="btn small" id="tok-copy"><i class="ph ph-copy"></i> Copy</button></div>
        <h2 class="section-title" style="margin-top:16px">${targets.length > 1 ? "Gateways this token opens" : "Use it from any MCP client"}</h2>
        <pre>${targets.map((t) => `${targets.length > 1 ? esc(t.label) + "\n" : ""}URL:    ${esc(t.url)}`).join("\n\n")}
Header: Authorization: Bearer ${esc(r.token)}</pre>
        <p class="muted small" style="margin-top:8px">Bound to ${esc(r.record.user_name || r.record.sub)} (<span class="mono">${esc(r.record.sub)}</span>, ${esc(r.record.role)}), expires ${esc(fmtTs(r.record.expires_at))}.${gws.length ? "" : " No named gateway admits this person yet, so the shared endpoint is shown."}</p>
        <div style="display:flex;justify-content:space-between;gap:8px;margin-top:8px"><button class="btn" id="tok-connect"><i class="ph ph-robot"></i> Setup instructions</button><button class="btn solid" id="tok-done">Done</button></div>`);
      $("#tok-connect").onclick = () => { closeModal(); setHash("gateway", { g: targets[0].id }); };
      $("#tok-copy").onclick = () => navigator.clipboard?.writeText(r.token).then(() => toast("Copied", "Token is on your clipboard"));
      $("#tok-done").onclick = () => { closeModal(); (after || pages.tokens)(); };
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
  const needsToken = via.needsToken ?? (SERVER.require_agent_token !== false);
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
      const ready = isHttps;
      const addSteps = [
        { t: "Copy this endpoint", b: codeBlock("g-url", url, via.standalone ? `This exact URL. It serves only ${esc(p.name)}, so the connector shows this one product, the way a vendor's own MCP app does.` : "This exact URL, including the /mcp path. The root path serves nothing and shows Not found.") },
        { t: "Add it in claude.ai", b: `<p>Settings, then Connectors, then Add custom connector. Paste the URL, give it a name, and click Add. It appears in the chat's tool menu.</p>` },
        { t: "Add it in ChatGPT", b: `<p>Settings, then Connectors, then Add. Paste the same URL. Requires a plan that allows custom connectors.</p>` },
        { t: "Ask for something", b: `<p class="mono">List the corporations I can see.</p><p class="mono">What classification rules does my company have?</p>` },
      ];
      if (ready) {
        return { label: "ChatGPT and Claude.ai", icon: "globe", ready: true,
          lead: needsToken
            ? `This endpoint is public HTTPS and asks callers to sign in. Both products discover the gateway's own OAuth sign-in on their own: paste the URL, sign in with your employee account when the portal's page opens, and every call is made as you.`
            : `This endpoint is public HTTPS and needs no sign-in, so both products can connect to it directly.`,
          steps: needsToken ? [addSteps[0], { t: "Sign in when asked", b: `<p>Right after you add the connector, the portal's sign-in page opens. Use your employee email and password (members only, not the admin account). The connector then holds a token bound to you, renewed automatically and listed on the Agent Tokens page, where it can be revoked.</p>` }, ...addSteps.slice(1)] : addSteps };
      }
      return {
        label: "ChatGPT and Claude.ai", icon: "globe", ready: false,
        lead: `These products refuse plain HTTP. Give the gateway an HTTPS address first, then add it the same way.`,
        steps: [
          ...(isHttps ? [] : [{ t: "Put HTTPS in front of it", b:
            `<p>Quickest for a demo, a Cloudflare quick tunnel on the server:</p>
             ${codeBlock("g-tunnel", `docker run -d --restart unless-stopped --name mcp-tunnel --network host \\\n  cloudflare/cloudflared:latest tunnel --no-autoupdate --url http://localhost:${port}\n\ndocker logs mcp-tunnel 2>&1 | grep -o 'https://[a-z0-9-]*\\.trycloudflare\\.com'`,
             "The printed address plus /mcp is the connector URL. It changes every restart and is open to anyone who has it. For a stable URL, terminate TLS with nginx and proxy to this port, with proxy_buffering off.")}
             <p class="muted small" style="margin-top:8px">Then set that address here with Edit connection, so these instructions and any new tokens use it.</p>` }]),
          ...addSteps,
        ],
      };
    })(),
    "enterprise": {
      label: "Copilot Studio and Agentforce", icon: "buildings", ready: false,
      lead: `Both support remote MCP servers and use the same public HTTPS address and the gateway's own OAuth sign-in as the cloud chat products.`,
      steps: [
        { t: "Microsoft Copilot Studio", b: `<p>Add the gateway as a custom connector, point it at ${esc(url)} on its public address, then enable it as a tool for the agent.</p>` },
        { t: "Salesforce Agentforce", b: `<p>Register the endpoint in the Agentforce MCP registry, then grant the agent access to the tools you enabled for this API.</p>` },
        { t: "What to prepare", b: `<p>A hosted gateway with a certificate, OAuth mapped to the customer's identity provider, and an agent token policy per company. The Security page tracks what is still open.</p>` },
      ],
    },
  };
}

/** Link one user's account on an OAuth backend: the auth server opens in a new tab and sends the user back here. */
async function connectDialog(p, after) {
  const me = session.user;
  const users = isAdmin() ? (await api("GET", "/api/users")).items : [];
  modal(`<h2><i class="ph ph-user-circle-plus"></i> Connect an account on ${esc(p.name)}</h2>
    <p class="muted">${isAdmin() ? "The user" : "You"} sign${isAdmin() ? "s" : ""} in at ${esc(hostOf(p.oauth?.authorization_url) || "the backend's auth server")} in a new tab. The tokens are kept by the gateway and used only for ${isAdmin() ? "that user's" : "your"} own calls.</p>
    <form id="cn-form" class="form">
      ${isAdmin() ? userPicker(users, me.user_id || users[0]?.id) : `<div class="who-card"><span class="avatar">${esc(initials(me.name))}</span><div><div class="who-name">${esc(me.name)}</div><div class="who-meta">Linking as <span class="mono">${esc(me.user_id)}</span>, the identity your agent tokens carry.</div></div></div>`}
      <div style="display:flex;justify-content:flex-end;gap:8px"><button type="button" class="btn" id="cn-cancel">Cancel</button><button class="btn solid" type="submit"><i class="ph ph-arrow-square-out"></i> Open sign-in</button></div>
      <p class="error" id="cn-error"></p>
    </form>`);
  if (isAdmin()) bindUserPicker(users);
  $("#cn-cancel").onclick = closeModal;
  $("#cn-form").onsubmit = async (e) => {
    e.preventDefault(); const f = Object.fromEntries(new FormData(e.target));
    const body = isAdmin() ? pickedUser(f) : {};
    const who = isAdmin() ? (users.find((u) => u.id === body.user_id)?.name || body.name || body.user_id) : me.name;
    try {
      const r = await api("POST", `/api/registry/${p.id}/oauth/start`, body);
      const win = window.open(r.authorization_url, "_blank");
      modal(`<h2><i class="ph ph-hourglass"></i> Waiting for ${esc(who)} to sign in</h2>
        <p class="muted">A sign-in tab was opened. When it finishes, it returns to this portal and the account appears under Connected accounts.</p>
        ${win ? "" : `<p class="error">The browser blocked the pop-up. Open this address instead:</p>${codeBlock("cn-url", r.authorization_url)}`}
        <div style="display:flex;justify-content:flex-end"><button class="btn" id="cn-done">Close</button></div>`);
      $("#cn-done").onclick = () => { closeModal(); (after || pages.provider)(); };
    } catch (err) { $("#cn-error").textContent = err.message; }
  };
}

/** A user's own username and password for a login-endpoint backend. Proved with a real sign-in before it is stored. */
async function loginConnectDialog(p, after) {
  const me = session.user;
  const users = isAdmin() ? (await api("GET", "/api/users")).items : [];
  modal(`<h2><i class="ph ph-sign-in"></i> Connect an account on ${esc(p.name)}</h2>
    <p class="muted">The gateway signs in at ${esc(hostOf(p.login?.url) || "the backend")} with these credentials, keeps them, and signs in again whenever the token expires. They are used only for ${isAdmin() ? "that user's" : "your"} own calls.</p>
    <form id="lc-form" class="form">
      ${isAdmin() ? userPicker(users, me.user_id || users[0]?.id) : `<div class="who-card"><span class="avatar">${esc(initials(me.name))}</span><div><div class="who-name">${esc(me.name)}</div><div class="who-meta">Connecting as <span class="mono">${esc(me.user_id)}</span>, the identity your agent tokens carry.</div></div></div>`}
      <div class="form-2">
        <label class="field">${esc(p.name)} username <input name="username" required autocomplete="off"></label>
        <label class="field">${esc(p.name)} password <input name="password" type="password" required autocomplete="new-password"></label>
      </div>
      <div style="display:flex;justify-content:flex-end;gap:8px"><button type="button" class="btn" id="lc-cancel">Cancel</button><button class="btn solid" type="submit" id="lc-submit"><i class="ph ph-sign-in"></i> Sign in and connect</button></div>
      <p class="error" id="lc-error"></p>
    </form>`);
  if (isAdmin()) bindUserPicker(users);
  $("#lc-cancel").onclick = closeModal;
  $("#lc-form").onsubmit = async (e) => {
    e.preventDefault(); const f = Object.fromEntries(new FormData(e.target));
    const btn = $("#lc-submit"); btn.disabled = true;
    try {
      const r = await api("POST", `/api/registry/${p.id}/login/connect`, { username: f.username, password: f.password, ...(isAdmin() ? pickedUser(f) : {}) });
      closeModal(); toast("Account connected", r.note, 5000); (after || pages.provider)();
    } catch (err) { $("#lc-error").textContent = err.message; btn.disabled = false; }
  };
}

/** The Sign-in card for a login-endpoint backend: how the gateway signs in, and as whom. */
function loginCard(p, conns) {
  const cfg = p.login || {}, sa = p.service_account || {};
  const sent = `${cfg.header || "Authorization"}: ${cfg.scheme ? cfg.scheme + " " : ""}<token>`;
  return `
    <div class="card">
      <div class="card-head">
        <span class="card-brand"><span class="logo ${p.login_ready ? "green" : "amber"}"><i class="ph ph-sign-in"></i></span> Sign-in</span>
        ${p.login_ready ? chip("green", "Login endpoint configured", "check") : chip("amber", "Login endpoint not configured", "warning")}
      </div>
      <div class="tiles" style="grid-template-columns:2fr 1fr 1fr 1fr">
        ${tile("globe", "Login URL", cfg.url || "not set", true)}
        ${tile("brackets-curly", "Token field", cfg.token_path || "token", true)}
        ${tile("paper-plane-tilt", "Sent as", sent, true)}
        ${tile(cfg.per_user ? "users" : "user-gear", "Credentials", cfg.per_user ? `Each user (${conns.length} connected)` : "Service account")}
      </div>
      <p class="card-desc" style="-webkit-line-clamp:4">${cfg.per_user
        ? "Each person signs in with their own username and password for this backend, so it sees the real user. The gateway keeps the credentials, signs in when the token expires or the API answers 401, and never uses one person's sign-in for another."
        : `The gateway signs in as <strong>${esc(sa.username || "(no username yet)")}</strong> and sends that token on every call, so this backend sees one shared identity. It signs in again when the token expires or the API answers 401.${sa.expires_at ? ` Token valid until ${esc(fmtTs(sa.expires_at))}.` : " Not signed in yet."}`}</p>
      ${cfg.per_user ? (conns.length ? `<div class="table-wrap"><table><tr><th>User</th><th>Signs in as</th><th>Connected</th><th>Token expires</th><th></th></tr>
        ${conns.map((c) => `<tr><td class="nowrap"><strong>${esc(c.user_name || c.user_id)}</strong><div class="sub mono">${esc(c.user_id)}</div></td><td class="mono small">${esc(c.username || "")}</td><td class="small">${esc(fmtTs(c.connected_at))}</td><td class="small">${c.expires_at ? esc(fmtTs(c.expires_at)) + " (auto sign-in)" : "never"}</td><td><button class="btn small danger" data-disconnect="${esc(c.user_id)}"><i class="ph ph-link-break"></i> Disconnect</button></td></tr>`).join("")}
        </table></div>` : `<p class="muted small">No accounts connected yet.</p>`) : ""}
      <div class="card-actions">
        ${cfg.per_user ? `<button class="btn small solid" data-act="connect" ${p.login_ready ? "" : "disabled"}><i class="ph ph-sign-in"></i> Connect account</button>` : `<button class="btn small solid" data-act="test"><i class="ph ph-plugs"></i> Test sign-in</button>`}
        <button class="btn small" data-act="edit"><i class="ph ph-pencil-simple"></i> Edit sign-in settings</button>
        ${p.kind === "mcp" ? `<button class="btn small" data-act="refresh-tools"><i class="ph ph-arrows-clockwise"></i> Refresh tools</button>` : ""}
      </div>
    </div>`;
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
        ${conns.map((c) => `<tr><td class="nowrap"><strong>${esc(c.user_name || c.user_id)}</strong><div class="sub mono">${esc(c.user_id)}</div></td><td class="small">${esc(fmtTs(c.connected_at))}</td><td class="small">${c.expires_at ? esc(fmtTs(c.expires_at)) + (c.can_refresh ? " (auto-refresh)" : "") : "never"}</td><td class="small mono">${esc(c.scope || "")}</td><td><button class="btn small danger" data-disconnect="${esc(c.user_id)}"><i class="ph ph-link-break"></i> Disconnect</button></td></tr>`).join("")}
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
  if (!isAdmin()) { const q = Object.fromEntries(new URLSearchParams(location.hash.split("?")[1] || "")); delete q.p; setHash("me", q); return; }
  if (hashParam("connected")) { toast("Account linked", `${hashParam("connected")} can now use this backend${hashParam("tools") ? `; ${hashParam("tools")} tools loaded from the server` : ""}`, 6000); setHash("provider", { p: pid }); return; }
  if (hashParam("oauth_error")) { toast("Sign-in failed", hashParam("oauth_error"), 7000); setHash("provider", { p: pid }); return; }
  const [reg, gws, known] = await Promise.all([api("GET", "/api/registry"), api("GET", "/api/gateways"), api("GET", "/api/groups")]);
  const p = reg.items.find((x) => x.id === pid);
  if (!p) {
    $("#page-title").textContent = "Not found"; crumbs({ page: "registry", label: "MCP Registry" }, { page: "provider", label: "Not found" }); pageActions("");
    $("#page").innerHTML = notFoundPage("Backend", "#registry", "All backends");
    return;
  }
  const [d, params] = await Promise.all([api("GET", `/api/registry/${pid}/tools`), api("GET", `/api/registry/${pid}/params`)]);
  const conns = p.per_user ? (await api("GET", `/api/registry/${pid}/connections`)).items : [];
  const enabled = d.items.filter((t) => t.enabled);
  const canDeploy = !!p.has_spec;  // an MCP-kind backend is already an MCP server
  $("#page-title").textContent = p.name;
  crumbs({ page: "registry", label: "MCP Registry" }, { page: "provider", label: p.name });
  pageActions(`<button class="btn" id="head-back"><i class="ph ph-arrow-left"></i> All backends</button>`);
  $("#head-back").onclick = () => { location.hash = "registry"; };
  renderTabs([], "", () => {}, p.status === "published" ? { title: "Live", sub: `${enabled.length} tools reachable by agents` } : null);

  // Every address this backend answers on, with a link to its connect instructions.
  const served = [];
  if ((p.has_spec || p.kind === "mcp") && p.status === "published") served.push({ label: "Everything", url: SERVER.public_mcp_url || location.origin + "/mcp", href: "#gateway?g=", note: "shared endpoint, every backend the caller is entitled to" });
  gws.items.filter((g) => g.backends.some((b) => b.id === pid)).forEach((g) => served.push({ label: g.name, url: g.url, href: `#gateway?g=${encodeURIComponent(g.id)}`, note: "named gateway" }));
  if (p.standalone) served.push({ label: `${p.name} (own MCP server)`, url: p.standalone_url, href: `#gateway?s=${encodeURIComponent(pid)}`, note: "plain tool names" });
  if (!p.has_spec && p.kind !== "mcp") served.push({ label: "Curated Bizplay gateway", url: p.mcp_url, href: "", note: "hand-written tools, served by its own process" });

  const backendLabel = p.kind === "mcp" ? "Upstream MCP server" : "Upstream API";
  $("#page").innerHTML = `
    <div class="card">
      <div class="card-head">
        <span class="card-brand" style="font-size:16px">${logo(p.name, 0)} ${esc(p.name)}</span>
        <span style="display:flex;gap:6px;flex-wrap:wrap">${standaloneChip(p)}${kindChip(p.kind)}${authChip(p.auth_mode)}${statusChip(p.status)}</span>
      </div>
      <div class="tiles" style="grid-template-columns:repeat(4, 1fr)">
        ${tile(p.kind === "mcp" ? "plugs-connected" : "cloud", backendLabel, p.base_url.replace(/^https?:\/\//, ""), true)}
        ${tile("plug", "Tools", `${p.tools_enabled} of ${p.tool_count} enabled`)}
        ${tile("textbox", "Tool names on gateways", p.tool_prefix ? `${p.tool_prefix}*` : "no prefix")}
        ${tile("squares-four", "Served on", `${served.length} endpoint(s)`)}
      </div>
      <p class="card-desc" style="-webkit-line-clamp:3">${p.kind === "mcp" ? "Tools proxied from the MCP server, unchanged" : `Spec from ${esc(p.spec_source)}`}. Registered by ${esc(p.owner)} on ${esc(fmtDate(p.created_at))}. ${p.auth_mode === "open" ? "The upstream accepts anonymous calls, so the gateway carries all the enforcement." : p.auth_mode === "network" ? `Reachable only from ${esc(p.allowlist || "the allowlisted gateway address")}.` : p.auth_mode === "oauth" ? `Each caller's own linked account token is sent; ${conns.length} user(s) linked.` : p.auth_mode === "login" ? (p.login?.per_user ? `The gateway signs in with each caller's own credentials; ${conns.length} user(s) connected.` : `The gateway signs in with a service account and sends the token it gets.`) : "The gateway sends a stored service token on every call."}</p>
      <div class="card-actions">
        <button class="btn small" data-act="edit"><i class="ph ph-pencil-simple"></i> Edit connection</button>
        <button class="btn small" data-act="test"><i class="ph ph-plugs"></i> Test connection</button>
        <button class="btn small ${p.status === "published" ? "" : "solid"}" data-act="${p.status === "published" ? "unpublish" : "publish"}"><i class="ph ${p.status === "published" ? "ph-eye-slash" : "ph-check"}"></i> ${p.status === "published" ? "Unpublish" : "Publish"}</button>
        ${canDeploy ? `<button class="btn small ${p.standalone ? "" : "solid"}" data-act="${p.standalone ? "undeploy" : "deploy"}"><i class="ph ${p.standalone ? "ph-rocket" : "ph-rocket-launch"}"></i> ${p.standalone ? "Undeploy MCP server" : "Deploy as MCP server"}</button>` : ""}
        ${p.id !== "bizplay" ? `<button class="btn small danger" data-act="delete"><i class="ph ph-trash"></i> Delete</button>` : ""}
      </div>
    </div>
    <div>
      <div class="section-head"><h2 class="section-title">Served on</h2><a class="btn small link" href="#gateways">All gateways</a></div>
      <div class="table-card"><div class="table-wrap"><table>
        <tr><th>Endpoint</th><th>Address</th><th></th></tr>
        ${served.length ? served.map((x) => `<tr><td><strong>${esc(x.label)}</strong><div class="sub">${esc(x.note)}</div></td><td class="mono small url">${esc(x.url)}</td><td class="actions">${x.href ? `<a class="btn small" href="${x.href}"><i class="ph ph-robot"></i> How to connect</a>` : ""}</td></tr>`).join("")
          : `<tr><td colspan="3">${emptyState("squares-four", "Not served anywhere yet", "Publish it to put it on the shared gateway, deploy it as its own MCP server, or add it to a named gateway.")}</td></tr>`}
      </table></div></div>
    </div>
    ${p.auth_mode === "oauth" ? connectionsCard(p, conns) : p.auth_mode === "login" ? loginCard(p, conns) : ""}
    ${accessSection(p, d, known.items, params)}
    <div class="callout"><i class="ph ph-key"></i><span>Results are limited to the company on the caller's token, and every call is written to the audit log. Connect instructions live on each endpoint's page under Served on.</span></div>`;

  bindAccess(pid, pages.provider, params);
  $("#page").querySelectorAll("[data-disconnect]").forEach((b) => b.onclick = async () => {
    if (!confirm(`Disconnect ${b.dataset.disconnect}? Their calls to ${p.name} are refused until they link the account again.`)) return;
    try { await api("DELETE", `/api/registry/${pid}/connections/${b.dataset.disconnect}`); toast("Account disconnected", b.dataset.disconnect); pages.provider(); }
    catch (err) { toast("Disconnect failed", err.message, 4500); }
  });
  $("#page").querySelectorAll("[data-act]").forEach((b) => b.onclick = async () => {
    const act = b.dataset.act;
    try {
      if (act === "edit") return editDialog(p);
      if (act === "test") return testDialog(pid);
      if (act === "connect") return p.auth_mode === "login" ? loginConnectDialog(p) : connectDialog(p);
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
      if (act === "deploy") { toast("Deployed", `${p.name} now answers at ${r.standalone_url}`, 5000); setHash("gateway", { s: pid }); return; }
      if (act === "undeploy") toast("Undeployed", `${r.standalone_url} now returns 404; the shared gateway still serves it`, 5000);
      else toast(act === "publish" ? "Published" : "Unpublished", `${p.name} ${act === "publish" ? "is now reachable by agents" : "is hidden from agents"}`);
      pages.provider();
    } catch (err) { toast("Action failed", err.message, 4500); }
  });
};

// ---- Gateway page: one endpoint, how to connect, what it serves ----
const SOURCES_CALLER = { company: "the caller's company (corp number)", user: "the caller's user id", role: "the caller's role" };

/** Create or edit a workflow: a name, inputs, and steps whose arguments may reference {{input.x}} or {{steps.N.path}}. */
function workflowDialog(index, workflows, allTools, save, after) {
  const wf = index == null ? { name: "", description: "", inputs: { question: { description: "" } }, steps: [{ tool: "", args: {} }], output: "" } : JSON.parse(JSON.stringify(workflows[index]));
  const toolOpts = (sel) => `<option value="">tool…</option>` + allTools.map((t) => `<option value="${esc(t.name)}" ${t.name === sel ? "selected" : ""}>${esc(t.name)}</option>`).join("");
  const stepRow = (s, i) => `<div class="wf-step" data-i="${i}"><div class="form-2" style="grid-template-columns:auto 1fr auto;align-items:start">
      <strong style="padding-top:9px">${i + 1}.</strong>
      <div class="field"><select data-k="tool">${toolOpts(s.tool)}</select>
        <textarea data-k="args" rows="2" style="min-height:44px" placeholder='{"itemId": "{{steps.0.data.0.id}}", "query": "{{input.query}}"}'>${esc(Object.keys(s.args || {}).length ? JSON.stringify(s.args) : "")}</textarea>
        <span class="muted small" data-k="hint"></span></div>
      <button type="button" class="btn small danger" data-k="del" style="margin-top:6px"><i class="ph ph-x"></i></button></div></div>`;
  modal(`<h2><i class="ph ph-flow-arrow"></i> ${index == null ? "New workflow" : `Edit ${esc(wf.name)}`}</h2>
    <p class="muted">Published as one tool. The gateway runs the steps in order and every step passes through entitlement, tool policy and the audit log as usual. Arguments may use <span class="mono">{{input.name}}</span> for an input and <span class="mono">{{steps.0.data.0.id}}</span> for a field of an earlier step's result.</p>
    <form id="wf-form" class="form">
      <div class="form-2">
        <label class="field">Tool name the model sees <input name="name" value="${esc(wf.name)}" placeholder="searchThenGetDetails" pattern="[A-Za-z][A-Za-z0-9_]{1,50}" required></label>
        <label class="field">What it does, for the model <input name="description" value="${esc(wf.description)}" placeholder="Find the matching item and return its details."></label>
      </div>
      <label class="field">Inputs, one per line as name: description <textarea name="inputs" rows="2" style="min-height:52px" placeholder="query: What the user is looking for">${esc(Object.entries(wf.inputs || {}).map(([k, v]) => `${k}: ${v.description || ""}`).join("\n"))}</textarea></label>
      <div id="wf-steps">${wf.steps.map(stepRow).join("")}</div>
      <div><button type="button" class="btn small" id="wf-step-add"><i class="ph ph-plus"></i> Add step</button></div>
      <label class="field">Result to return (optional) <input name="output" value="${esc(wf.output || "")}" placeholder="steps.1.data  (blank returns the last step's result)"></label>
      <div style="display:flex;justify-content:flex-end;gap:8px"><button type="button" class="btn" id="wf-cancel">Cancel</button><button class="btn solid" type="submit"><i class="ph ph-check"></i> Save workflow</button></div>
      <p class="error" id="wf-error"></p></form>`);
  const bindSteps = () => {
    $("#wf-steps").querySelectorAll(".wf-step").forEach((row) => {
      row.querySelector("[data-k=del]").onclick = () => { row.remove(); renumber(); };
      const sel = row.querySelector("[data-k=tool]"), hint = row.querySelector("[data-k=hint]");
      const show = () => { const t = allTools.find((x) => x.name === sel.value); hint.textContent = t ? (t.params.length ? `takes: ${t.params.join(", ")}` : "takes no arguments") : ""; };
      sel.onchange = show; show();
    });
  };
  const renumber = () => $("#wf-steps").querySelectorAll(".wf-step").forEach((row, i) => { row.dataset.i = i; row.querySelector("strong").textContent = `${i + 1}.`; });
  $("#wf-step-add").onclick = () => { $("#wf-steps").insertAdjacentHTML("beforeend", stepRow({ tool: "", args: {} }, $("#wf-steps").children.length)); bindSteps(); };
  bindSteps();
  $("#wf-cancel").onclick = closeModal;
  $("#wf-form").onsubmit = async (e) => {
    e.preventDefault(); const f = Object.fromEntries(new FormData(e.target));
    const inputs = {};
    f.inputs.split("\n").map((l) => l.trim()).filter(Boolean).forEach((l) => { const [k, ...d] = l.split(":"); inputs[k.trim()] = { description: d.join(":").trim() }; });
    const steps = [...$("#wf-steps").querySelectorAll(".wf-step")].map((row) => ({ tool: row.querySelector("[data-k=tool]").value, args: row.querySelector("[data-k=args]").value.trim() || "{}" }));
    const next = [...workflows]; const spec = { name: f.name.trim(), description: f.description.trim(), inputs, steps, output: f.output.trim() };
    if (index == null) next.push(spec); else next[index] = spec;
    try { await save(next); closeModal(); toast("Workflow saved", `${spec.name} is now a tool the model can choose`); after(); }
    catch (err) { $("#wf-error").textContent = err.message; }
  };
}

pages.gateway = async () => {
  const gid = hashParam("g"), sid = hashParam("s");
  const [gws, reg] = await Promise.all([api("GET", "/api/gateways"), api("GET", "/api/registry")]);
  const servable = reg.items.filter((p) => p.has_spec || p.kind === "mcp");
  let ep;  // { id, name, url, backends: [provider], prefixed, standalone, editable, description }
  if (sid !== null) {
    const p = reg.items.find((x) => x.id === sid);
    if (!p || !p.standalone) { $("#page-title").textContent = "Not found"; crumbs({ page: "servers", label: "MCP Servers" }, { page: "gateway", label: "Not found" }); pageActions(""); $("#page").innerHTML = notFoundPage("MCP server", "#servers", "All servers"); return; }
    ep = { id: p.id, name: p.name, url: p.standalone_url, backends: [p], prefixed: false, standalone: true, description: "This backend on its own address, tool names as the backend defines them." };
  } else if (gid) {
    const g = gws.items.find((x) => x.id === gid);
    if (!g) { $("#page-title").textContent = "Not found"; crumbs({ page: "gateways", label: "MCP Gateways" }, { page: "gateway", label: "Not found" }); pageActions(""); $("#page").innerHTML = notFoundPage("Gateway", "#gateways", "All gateways"); return; }
    ep = { id: g.id, name: g.name, url: g.url, backends: g.backends.map((b) => reg.items.find((x) => x.id === b.id)).filter(Boolean), prefixed: true, editable: true, description: g.description || "Named gateway: a chosen set of backends, tool names prefixed by backend id.", raw: g };
  } else {
    ep = { id: "", name: "Everything", url: SERVER.public_mcp_url || location.origin + "/mcp", backends: servable.filter((p) => p.status === "published"), prefixed: true, description: "The shared endpoint: every published backend the caller is entitled to, tool names prefixed by backend id." };
  }
  // Tools this endpoint serves, named as the agent sees them.
  const toolLists = await Promise.all(ep.backends.map((p) => api("GET", `/api/registry/${p.id}/tools`)));
  // Only published backends are actually served; a draft member contributes nothing yet.
  const tools = ep.backends.flatMap((p, i) => p.status !== "published" ? [] : toolLists[i].items.filter((t) => t.enabled).map((t) => ({ ...t, name: (ep.prefixed ? (p.tool_prefix || "") : "") + t.name, backend: p.name, backend_id: p.id })));
  const drafts = ep.backends.filter((p) => p.status !== "published");
  const settingsKey = ep.id || "_shared";
  const [es, known] = await Promise.all([api("GET", `/api/endpoints/${settingsKey}/settings`), api("GET", "/api/groups")]);
  const previewAs = hashParam("as") || "";
  const [told, people] = await Promise.all([
    api("GET", `/api/endpoints/${settingsKey}/instructions${previewAs ? `?as=${encodeURIComponent(previewAs)}` : ""}`).catch(() => ({ text: "", backends: [] })),
    isAdmin() ? api("GET", "/api/users").then((u) => u.items).catch(() => []) : Promise.resolve([])]);
  const via = { url: ep.url, prefix: "", standalone: ep.standalone, label: ep.name, needsToken: es.require_token };
  const guides = clientGuides({ id: ep.id || "bizplay-gateway", name: ep.name, has_spec: true, kind: "openapi", tool_prefix: "" }, tools, via);
  const key = guides[hashParam("c")] ? hashParam("c") : "claude-desktop";

  $("#page-title").textContent = ep.name;
  crumbs(ep.standalone ? { page: "servers", label: "MCP Servers" } : { page: "gateways", label: "MCP Gateways" }, { page: "gateway", label: ep.name });
  pageActions(`<button class="btn" id="head-back"><i class="ph ph-arrow-left"></i> ${ep.standalone ? "All servers" : "All gateways"}</button><button class="btn solid" id="head-command"><i class="ph ph-terminal-window"></i> Connect command</button>`);
  $("#head-back").onclick = () => { location.hash = ep.standalone ? "servers" : "gateways"; };
  $("#head-command").onclick = () => commandDialog({ id: ep.id || "bizplay-gateway", name: ep.name }, via);
  renderTabs([], "", () => {}, { title: `${tools.length} tools on this endpoint`, sub: `${ep.backends.length} backend(s)` });

  $("#page").innerHTML = `
    <div class="card">
      <div class="card-head">
        <span class="card-brand" style="font-size:16px">${logo(ep.name, 0)} ${esc(ep.name)}</span>
        <span style="display:flex;gap:6px;flex-wrap:wrap">${ep.standalone ? chip("green", "Own MCP server", "rocket-launch") : ep.id ? chip("lilac", "Named gateway", "squares-four") : chip("", "Shared endpoint", "squares-four")}</span>
      </div>
      <div class="tiles" style="grid-template-columns:2fr 1fr 1fr 1fr">
        <div class="tile"><span class="k"><i class="ph ph-link"></i>Endpoint
          <button class="btn small copy" data-copy="g-endpoint" title="Copy the endpoint" style="margin-left:auto;padding:2px 7px"><i class="ph ph-copy"></i></button></span>
          <span class="v mono" id="g-endpoint">${esc(ep.url)}</span></div>
        ${tile("plugs-connected", "Backends", String(ep.backends.length))}
        ${tile("plug", "Tools", String(tools.length))}
        ${tile("key", "Auth", es.require_token ? "agent token required" : "no token required")}
      </div>
      <p class="card-desc" style="-webkit-line-clamp:3">${esc(ep.description)}</p>
      <div class="chips">${ep.backends.length ? ep.backends.map((p) => `<a class="chip ${p.status === "published" ? "lilac" : "amber"}" href="#provider?p=${encodeURIComponent(p.id)}" title="${p.status === "published" ? "Open" : "Draft, not served yet: open"} ${esc(p.name)}"><i class="ph ${p.status === "published" ? "ph-arrow-square-out" : "ph-pencil-simple"}"></i>${esc(p.name)}</a>`).join("") : chip("", "no backends")}</div>
      ${drafts.length ? `<p class="muted small" style="margin:0">${esc(drafts.map((p) => p.name).join(", "))}: draft, so not served on this endpoint until published.</p>` : ""}
      ${ep.editable || ep.standalone ? `<div class="card-actions">
        ${ep.editable ? `<button class="btn small" data-act="edit"><i class="ph ph-pencil-simple"></i> Edit backends</button><button class="btn small danger" data-act="delete"><i class="ph ph-trash"></i> Delete gateway</button>` : ""}
        ${ep.standalone ? `<button class="btn small danger" data-act="undeploy"><i class="ph ph-rocket"></i> Undeploy</button>` : ""}
      </div>` : ""}
    </div>
    ${isAdmin() ? `<div>
      <div class="section-head"><h2 class="section-title">Gateway settings</h2>${es.access.mode === "everyone" ? chip("", "Open to every entitled caller", "users") : chip("lilac", `${es.access.mode}: ${(es.access[es.access.mode] || []).join(", ")}`, "users-three")}</div>
      <div class="card settings-list">
        <div class="setting"><div class="setting-text"><strong>Require an agent token</strong><p class="muted small">Callers must present a portal-issued token on this endpoint. Applies on the next request; no restart. Without a token every caller is the demo identity and no per-user rule can apply.</p></div>
          <div class="setting-ctl"><select id="es-require" aria-label="Require an agent token">
            <option value="inherit" ${es.inherits ? "selected" : ""}>Default (${es.default_require_token ? "required" : "not required"})</option>
            <option value="true" ${!es.inherits && es.require_token ? "selected" : ""}>Required</option>
            <option value="false" ${!es.inherits && !es.require_token ? "selected" : ""}>Not required</option>
          </select></div></div>
        <div class="setting"><div class="setting-text"><strong>Who can use this gateway</strong><p class="muted small">Checked before anything else. Each backend's own entitlement and tool policy still apply on top.</p></div>
          <div class="setting-ctl"><select id="es-mode" aria-label="Who can use this gateway">
            <option value="everyone" ${es.access.mode === "everyone" ? "selected" : ""}>Everyone with access</option>
            <option value="groups" ${es.access.mode === "groups" ? "selected" : ""}>Only these access groups</option>
            <option value="companies" ${es.access.mode === "companies" ? "selected" : ""}>Only these companies</option>
          </select></div></div>
        <div class="setting ${es.access.mode === "groups" ? "" : "hidden"}" id="es-groups-row"><div class="setting-text"><strong>Access groups</strong><p class="muted small">Comma separated${known.items.length ? `. In use: ${esc(known.items.join(", "))}` : ""}.</p></div>
          <div class="setting-ctl"><input id="es-groups" class="ctl-wide" value="${esc(es.access.groups.join(", "))}" placeholder="finance, hr"></div></div>
        <div class="setting ${es.access.mode === "companies" ? "" : "hidden"}" id="es-companies-row"><div class="setting-text"><strong>Companies</strong><p class="muted small">Comma separated company ids from the caller's token.</p></div>
          <div class="setting-ctl"><input id="es-companies" class="ctl-wide" value="${esc(es.access.companies.join(", "))}" placeholder="1234567890"></div></div>
        <div class="setting stacked"><div class="setting-text"><strong>Instructions for the model</strong><p class="muted small">The opening lines a model reads when it connects here: who it is helping and how the backends fit together. Each backend's own usage notes are added underneath.</p></div>
          <div class="setting-ctl"><textarea id="es-instructions" rows="3" style="width:100%;min-height:72px" placeholder="You are the assistant for this team. Say which backend to use for which kind of question.">${esc(es.instructions || "")}</textarea></div></div>
        <div class="setting"><div class="setting-text"><p class="muted small" style="margin:0">Token lifetime, the public address and upstream credentials stay on the Security page; they are not per gateway.</p></div>
          <div class="setting-ctl"><button class="btn solid small" id="es-save"><i class="ph ph-check"></i> Save gateway settings</button></div></div>
      </div>
    </div>` : ""}
    ${isAdmin() ? `<div id="flows">
      <div class="section-head"><h2 class="section-title">Workflows</h2><button class="btn small" id="wf-add"><i class="ph ph-plus"></i> New workflow</button></div>
      ${workflowTable(es.workflows || [], es.inherited_workflows || [], "A workflow is a fixed sequence of tools published as one extra tool. The gateway runs the steps in order; the model may use it or call the tools itself. Workflows defined on a backend's page appear here too.")}
    </div>` : ""}
    ${isAdmin() ? gatewayValuesSection(es, told) : ""}
    <div id="told">
      <div class="section-head"><h2 class="section-title">What the model is told</h2>
        ${isAdmin() ? `<label class="muted small" style="display:flex;align-items:center;gap:8px">Preview as <select id="told-as"><option value="">a caller with no token</option>${people.map((u) => `<option value="${esc(u.id)}" ${u.id === previewAs ? "selected" : ""}>${esc(u.name)} · ${esc(u.id)}</option>`).join("")}</select></label>` : ""}</div>
      <div class="card">
        ${told.text ? `<pre class="told">${esc(told.text)}</pre>` : emptyState("chat-text", "Nothing yet", "Add instructions above, or usage notes on a backend's page. Without them a model has only tool names and descriptions to go on.")}
        ${(told.backends || []).length ? `<p class="muted small" style="margin:10px 0 0">${told.backends.map((b) => `<a href="#provider?p=${esc(b.id)}">${esc(b.name)}</a>: ${b.has_notes ? "usage notes" : "<strong>no usage notes</strong>"}${Object.keys(b.bound).length ? `, fills in ${esc(Object.keys(b.bound).join(", "))}` : ""}`).join(" · ")}</p>` : ""}
      </div>
    </div>
    <div>
      <div class="section-head"><h2 class="section-title">How to connect</h2>${es.require_token ? chip("green", "Agent token required", "key") : chip("amber", "No token: every caller is the demo user", "warning")}</div>
      <div class="card" style="margin-bottom:12px">
        <dl class="kv"><dt>Endpoint</dt><dd>${esc(ep.url)}</dd><dt>Transport</dt><dd>streamable HTTP</dd><dt>Auth</dt><dd>${es.require_token ? "Authorization: Bearer &lt;agent token&gt;" : "none required on this endpoint"}</dd><dt>Tool names</dt><dd>${ep.prefixed ? "prefixed by backend id" : "as the backend defines them"}</dd></dl>
        <p class="muted small" style="margin:0">Same endpoint for every client below. Open the one you use; <strong>Connect command</strong> at the top prints a ready-to-paste version with a token.</p>
      </div>
      <div class="guides">${Object.entries(guides).map(([k, v]) => `
        <details class="guide" ${k === key ? "open" : ""} data-guide="${esc(k)}">
          <summary><span class="guide-title"><i class="ph ph-${esc(v.icon)}"></i> ${esc(v.label)}</span>${v.ready ? chip("green", "Works today", "check") : chip("amber", "Needs hosting and OAuth", "warning")}<i class="ph ph-caret-down caret"></i></summary>
          <div class="guide-body">
            <p class="muted" style="max-width:76ch">${esc(v.lead)}</p>
            <div class="steps">${v.steps.map((s, i) => `<div class="step"><span class="step-n">${i + 1}</span><div class="step-b"><strong>${esc(s.t)}</strong>${s.b}</div></div>`).join("")}</div>
          </div>
        </details>`).join("")}</div>
    </div>
    <div>
      <div class="section-head"><h2 class="section-title">Tools on this endpoint</h2><span class="muted small">policy is edited on each backend's page</span></div>
      <div class="table-card"><div class="table-wrap"><table><tr><th>Tool name the agent calls</th><th>Backend</th><th>Kind</th></tr>
      ${tools.length ? tools.slice(0, 60).map((t) => `<tr><td class="tool"><span class="mono">${esc(t.name)}</span>${t.description || t.summary ? `<div class="muted small">${esc(t.description || t.summary)}</div>` : ""}</td><td><a class="btn small link" href="#provider?p=${encodeURIComponent(t.backend_id)}">${esc(t.backend)}</a></td><td>${t.kind === "write" ? chip("amber", "write", "pencil-simple") : chip("lilac", "read", "eye")}${t.confirm ? ` ${chip("", "confirm first")}` : ""}</td></tr>`).join("")
        : `<tr><td colspan="3">${emptyState("sliders-horizontal", "No tools enabled", "Enable some on the backends' pages and they appear here.")}</td></tr>`}
      </table></div></div>
      ${tools.length > 60 ? `<p class="muted small" style="margin-top:8px">${tools.length - 60} more.</p>` : ""}
    </div>`;

  $("#es-mode").onchange = (e) => {
    $("#es-groups-row").classList.toggle("hidden", e.target.value !== "groups");
    $("#es-companies-row").classList.toggle("hidden", e.target.value !== "companies");
  };
  bindWorkflows(es.workflows || [], (told.backends || []).flatMap((b) => b.tools.filter((t) => t.enabled).map((t) => ({ name: (t.prefix || "") + (t.alias || t.name), params: t.params }))),
    (next) => api("PUT", `/api/endpoints/${settingsKey}/settings`, { workflows: next }), pages.gateway);
  bindGatewayValues(es, told, settingsKey);
  if ($("#told-as")) $("#told-as").onchange = (e) => { const q = Object.fromEntries(new URLSearchParams(location.hash.split("?")[1] || "")); if (e.target.value) q.as = e.target.value; else delete q.as; setHash("gateway", q); pages.gateway(); };
  if ($("#es-save")) $("#es-save").onclick = async () => {
    try {
      const v = $("#es-require").value;
      const r = await api("PUT", `/api/endpoints/${settingsKey}/settings`, { require_token: v === "inherit" ? null : v === "true",
        access: { mode: $("#es-mode").value, groups: $("#es-groups").value, companies: $("#es-companies").value },
        instructions: $("#es-instructions").value });
      toast("Gateway settings saved", `${r.require_token ? "Token required" : "No token required"}; applies on the next request`); pages.gateway();
    } catch (err) { toast("Save failed", err.message, 4500); }
  };
  $("#page").querySelectorAll("[data-act]").forEach((b) => b.onclick = async () => {
    const act = b.dataset.act;
    try {
      if (act === "edit") return gatewayDialog(ep.raw, servable);
      if (act === "delete") {
        if (!confirm(`Delete gateway ${ep.name}? Its address stops answering at once; the backends stay registered.`)) return;
        await api("DELETE", `/api/gateways/${ep.id}`); toast("Gateway deleted", ep.url); location.hash = "gateways"; return;
      }
      if (act === "undeploy") {
        const r = await api("POST", `/api/registry/${ep.id}/undeploy`); toast("Undeployed", `${r.standalone_url} now returns 404`, 5000); location.hash = "servers";
      }
    } catch (err) { toast("Action failed", err.message, 4500); }
  });
};

// ---- Security ----
pages.security = async () => {
  const d = await api("GET", "/api/security");
  const s = d.settings;
  const passed = d.checklist.filter((c) => c.ok).length, score = Math.round(100 * passed / d.checklist.length);
  const tab = ["checklist", "settings", "credentials", "signins"].includes(hashParam("t")) ? hashParam("t") : "checklist";
  const log = tab === "signins" ? await api("GET", "/api/auth-log") : { items: [], clients: [] };
  renderTabs([
    { key: "checklist", label: "Checklist", icon: "list-checks", count: `${passed}/${d.checklist.length}` },
    { key: "settings", label: "Defaults", icon: "sliders-horizontal" },
    { key: "credentials", label: "Upstream credentials", icon: "key", count: d.credentials.length },
    { key: "signins", label: "Sign-in log", icon: "sign-in" },
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
      <div class="callout"><i class="ph ph-info"></i><span>Two of these stay open by design in the mockup: OAuth 2.1 for agents and a vault for secrets are production work. The rest are decided by the Defaults tab, each gateway's own settings, and how each backend is registered.</span></div>
      <div class="card" style="gap:6px">
        <div class="section-head" style="margin-bottom:0"><h2 class="section-title">How a caller is identified</h2>${chip("lilac", "issuer: portal", "fingerprint")}</div>
        <p class="muted small" style="margin:0">Every gateway endpoint reads the same claims from an agent token: <span class="mono">sub</span> is the Bizplay user, <span class="mono">role</span> and <span class="mono">company</span> drive tool policy and company scoping, <span class="mono">groups</span> drive entitlement. Tokens are issued by this portal today; production points the issuer at Bizplay SSO (OAuth 2.1 / OIDC) so they become signed JWTs verified by key.</p>
      </div>`,

    settings: `
      <div class="card settings-list">
        ${setting("require_upstream_bearer", "Bizplay API endpoints require a bearer token",
          "Records the policy that every /api/* call carries the service token. Enforced by the provider's own API, not here.", toggle("require_upstream_bearer"))}
        ${setting("require_gateway_bearer", "Gateways require an agent token by default",
          "The default for every gateway endpoint; each gateway can override it on its own page. Applies on the next request. Off means anyone who reaches an endpoint is the same demo user.", toggle("require_gateway_bearer"))}
        ${setting("confirm_on_write", "Write tools ask for confirmation",
          "Turning this on sets confirm-before-call on every write tool of every backend at once.", toggle("confirm_on_write"))}
        ${setting("token_ttl_days", "Default agent token lifetime",
          "Days before a newly issued agent token expires. The checklist flags anything over 90.", `<div class="ctl-inline"><input type="number" data-s="token_ttl_days" value="${s.token_ttl_days}" min="1" max="365" aria-label="Token lifetime in days"><span class="muted small">days</span></div>`)}
        ${setting("public_mcp_url", "Public MCP endpoint",
          `The address agents use when a tunnel or nginx sits in front. New registrations inherit it. Blank means this portal's own address, ${esc(SERVER.portal_mcp_url || location.origin + "/mcp")}.`,
          `<input data-s="public_mcp_url" value="${esc(s.public_mcp_url || "")}" placeholder="${esc(SERVER.portal_mcp_url || "https://your-host/mcp")}" aria-label="Public MCP endpoint" class="ctl-wide">`)}
      </div>
      <p class="muted small">Changes save as you make them. Token requirement and who may use an endpoint are set per gateway on its own page; these are the portal-wide defaults.</p>`,

    signins: `
      <div class="callout"><i class="ph ph-sign-in"></i><span>Every step an MCP client takes at the gateway's sign-in endpoints (discovery, registration, the sign-in page, token exchange) and every call the gateway refused. When a connector says it could not reach the gateway, the last lines here say how far it got.</span></div>
      <div class="section-head" style="margin-top:14px"><h2 class="section-title">Registered MCP clients</h2><span class="muted small">${log.clients.length} client(s)</span></div>
      <div class="table-card"><div class="table-wrap"><table>
        <tr><th>Client</th><th>Client id</th><th>Sends users back to</th><th>Registered</th></tr>
        ${log.clients.length ? log.clients.map((c) => `<tr><td><strong>${esc(c.client_name)}</strong>${c.cimd ? `<div class="sub">${esc("published identity (metadata document)")}</div>` : ""}</td><td class="mono small clip" title="${esc(c.client_id)}">${esc(c.client_id)}</td><td class="mono small">${esc((c.redirect_uris || []).join(", "))}</td><td class="small nowrap">${esc(fmtTs(c.client_id_issued_at))}</td></tr>`).join("")
          : `<tr><td colspan="4">${emptyState("plugs", "No client has registered yet", "claude.ai and ChatGPT register themselves the first time someone adds a gateway that requires a token.")}</td></tr>`}
      </table></div></div>
      <div class="section-head" style="margin-top:18px"><h2 class="section-title">Recent steps</h2><span class="muted small">Newest first, ${log.items.length} line(s)</span></div>
      <div class="table-card"><div class="table-wrap"><table>
        <tr><th>Time</th><th>Step</th><th>Status</th><th>Client</th><th>User</th><th>Detail</th><th>Path</th><th>Client software</th></tr>
        ${log.items.length ? log.items.map((e) => `<tr><td class="small mono nowrap">${esc(fmtTs(e.ts))}</td><td>${chip("", e.kind)}</td><td>${e.status < 300 ? chip("green", String(e.status)) : e.status < 400 ? chip("", String(e.status)) : chip("red", String(e.status))}</td><td class="small">${esc(e.client || "")}</td><td class="mono small">${esc(e.user || "")}</td><td class="small">${esc(e.detail)}</td><td class="mono small">${esc(e.path)}</td><td class="small muted clip" title="${esc(e.agent)}">${esc((e.agent || "").slice(0, 40))}</td></tr>`).join("")
          : `<tr><td colspan="8">${emptyState("sign-in", "Nothing yet", "Steps appear as soon as a client discovers the sign-in or the gateway refuses a call.")}</td></tr>`}
      </table></div></div>`,
    credentials: `
      <div class="table-card"><div class="table-wrap"><table>
        <tr><th>Credential</th><th>Backend</th><th>Secret</th><th>Rotated</th><th></th></tr>
        ${d.credentials.length ? d.credentials.map((c, n) => `<tr>
          <td><span class="name">${logo(c.provider_id, n)} <span>${esc(c.label)}<div class="sub">${c.type === "login" ? `signs in as ${esc(c.username || "(no username)")}` : `${esc(c.type)} token the gateway sends`}</div></span></span></td>
          <td class="mono">${esc(c.provider_id)}</td>
          <td class="mono">${esc(c.secret)}</td>
          <td>${c.rotated_at ? `${chip("green", "Rotated", "arrows-clockwise")}<div class="sub">${esc(fmtDate(c.rotated_at))}</div>` : chip("amber", "Never rotated", "clock")}</td>
          <td class="actions">${c.type === "login" ? `<a class="btn small" href="#provider?p=${esc(c.provider_id)}"><i class="ph ph-pencil-simple"></i> Change on backend</a>` : `<button class="btn small" data-rotate="${esc(c.id)}"><i class="ph ph-arrows-clockwise"></i> Rotate</button>`}</td>
        </tr>`).join("") : `<tr><td colspan="5">${emptyState("key", "No upstream credentials", "Backends in bearer mode get one when they are registered.")}</td></tr>`}
      </table></div></div>
      <div class="callout"><i class="ph ph-info"></i><span>Secrets are masked here and never shown again after rotation. The mockup keeps them in a JSON file; production keeps them in a vault.</span></div>`,

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

// ---- Users: the directory tokens and linked accounts belong to ----
pages.users = async () => {
  const d = await api("GET", "/api/users");
  const q = ($("#global-search").value || "").toLowerCase();
  const items = d.items.filter((u) => !q || `${u.id} ${u.name} ${u.email} ${u.role} ${(u.groups || []).join(" ")}`.toLowerCase().includes(q));
  pageActions(`<button class="btn solid" id="btn-add-user"><i class="ph ph-user-plus"></i> Add user</button>`);
  $("#page").innerHTML = `
    <div class="callout"><i class="ph ph-users"></i><span>Agent tokens and linked accounts are issued to people listed here. A token takes its role, company and groups from the person, so they are set once. Users with a portal password sign in as members and issue their own tokens and link their own accounts; the rest are managed here.</span></div>
    <div class="table-card" style="margin-top:14px"><div class="table-wrap"><table>
      <tr><th>User</th><th>Email</th><th>Role</th><th>Company</th><th>Groups</th><th>Portal sign-in</th><th>Tokens</th><th>Linked accounts</th><th></th></tr>
      ${items.length ? items.map((u, i) => `<tr data-user="${esc(u.id)}" class="row-link">
        <td><span class="name">${logo(u.name, i)} <span>${esc(u.name)}<div class="sub mono">${esc(u.id)}</div></span></span></td>
        <td class="small">${esc(u.email || "")}</td>
        <td>${chip("", u.role, "identification-badge")}</td>
        <td class="small">${esc(u.company || "")}</td>
        <td><span class="chips">${(u.groups || []).length ? u.groups.map((g) => chip("lilac", g)).join("") : `<span class="muted small">none</span>`}</span></td>
        <td>${u.can_sign_in ? chip("green", "Member", "sign-in") : chip("", "Managed by admin", "user-gear")}</td>
        <td class="small">${u.active_tokens}</td>
        <td class="small">${(u.linked_backends || []).length ? esc(u.linked_backends.join(", ")) : `<span class="muted">none</span>`}</td>
        <td class="actions"><button class="btn small" data-edit="${esc(u.id)}"><i class="ph ph-pencil-simple"></i> Edit</button></td>
      </tr>`).join("")
      : `<tr><td colspan="9">${emptyState("users", "No users", "Add the people who will call the gateway through an AI agent.")}</td></tr>`}
    </table></div></div>`;
  $("#btn-add-user").onclick = () => userDialog(null);
  $("#page").querySelectorAll("[data-edit]").forEach((b) => b.onclick = (e) => { e.stopPropagation(); userDialog(d.items.find((u) => u.id === b.dataset.edit)); });
  $("#page").querySelectorAll("tr[data-user]").forEach((tr) => tr.onclick = () => userDialog(d.items.find((u) => u.id === tr.dataset.user)));
};

async function userDialog(u) {
  const editing = !!u;
  modal(`<h2><i class="ph ph-${editing ? "user-gear" : "user-plus"}"></i> ${editing ? `Edit ${esc(u.name)}` : "Add a user"}</h2>
    <form id="usr-form" class="form">
      <div class="form-2">
        <label class="field">Bizplay user id <input name="id" value="${esc(u?.id || "")}" placeholder="u1001" pattern="[a-z0-9_-]+" ${editing ? "disabled" : "required"}><span class="muted small">What agent tokens carry as the caller and what the audit log shows.</span></label>
        <label class="field">Name <input name="name" value="${esc(u?.name || "")}" placeholder="Full name" required></label>
        <label class="field">Email <input name="email" type="email" value="${esc(u?.email || "")}" placeholder="name@example.com"></label>
        <label class="field">Role <select name="role"><option value="employee" ${u?.role === "employee" ? "selected" : ""}>employee</option><option value="manager" ${u?.role === "manager" ? "selected" : ""}>manager</option></select></label>
        <label class="field">Company (corpNo) <input name="company" value="${esc(u?.company || "1078836129")}" placeholder="1234567890"><span class="muted small">The corp number the gateway limits this person's calls and results to.</span></label>
        <label class="field">Access groups <input name="groups" value="${esc((u?.groups || []).join(", "))}" placeholder="finance, hr (comma separated)"></label>
      </div>
      <label class="field">Portal password <input name="password" type="password" placeholder="${editing && u.can_sign_in ? "(unchanged)" : "leave empty: no portal sign-in"}" autocomplete="new-password" minlength="6"><span class="muted small">With a password the person signs in as a member and manages their own tokens and linked accounts.</span></label>
      <div style="display:flex;justify-content:space-between;gap:8px">
        <span>${editing && u.id !== session.user.user_id ? `<button type="button" class="btn danger" id="usr-delete"><i class="ph ph-trash"></i> Remove</button>` : ""}</span>
        <span style="display:flex;gap:8px"><button type="button" class="btn" id="usr-cancel">Cancel</button><button class="btn solid" type="submit"><i class="ph ph-check"></i> ${editing ? "Save" : "Add user"}</button></span>
      </div>
      <p class="error" id="usr-error"></p></form>`);
  $("#usr-cancel").onclick = closeModal;
  if ($("#usr-delete")) $("#usr-delete").onclick = async () => {
    if (!confirm(`Remove ${u.name}? Their tokens are revoked and their linked accounts dropped.`)) return;
    try { await api("DELETE", `/api/users/${u.id}`); closeModal(); toast("User removed", u.name); pages.users(); } catch (err) { $("#usr-error").textContent = err.message; }
  };
  $("#usr-form").onsubmit = async (e) => {
    e.preventDefault(); const f = Object.fromEntries(new FormData(e.target));
    if (!f.password) delete f.password;
    try {
      if (editing) await api("PATCH", `/api/users/${u.id}`, f); else await api("POST", "/api/users", f);
      closeModal(); toast(editing ? "User saved" : "User added", f.name); pages.users();
    } catch (err) { $("#usr-error").textContent = err.message; }
  };
}

// ---- My access: what a signed-in employee can do for themselves ----
pages.me = async () => {
  if (hashParam("connected")) { toast("Account linked", `You can now use this backend${hashParam("tools") ? `; ${hashParam("tools")} tools loaded` : ""}`, 6000); setHash("me", {}); return; }
  if (hashParam("oauth_error")) { toast("Sign-in failed", hashParam("oauth_error"), 7000); setHash("me", {}); return; }
  const me = session.user;
  const [toks, reg, gws] = await Promise.all([api("GET", "/api/tokens"), api("GET", "/api/registry"), api("GET", "/api/gateways")]);
  const oauthBackends = reg.items.filter((p) => p.per_user);
  const conns = await Promise.all(oauthBackends.map((p) => api("GET", `/api/registry/${p.id}/connections`).then((c) => c.items[0] || null)));
  const alive = (t) => !t.revoked && t.expires_at > toks.now;
  const mine = toks.items.filter(alive);
  const usable = gws.items.filter((g) => entitled(g.access, me));
  pageActions(`<button class="btn solid" id="btn-issue"><i class="ph ph-plus"></i> Issue token</button>`);
  $("#page").innerHTML = `
    <div class="card"><div class="who-card"><span class="avatar">${esc(initials(me.name))}</span><div><div class="who-name">${esc(me.name)}</div><div class="who-meta"><span class="mono">${esc(me.user_id)}</span> · ${esc(me.user_role || "employee")} · ${esc(me.company || "")}${(me.groups || []).length ? ` · groups: ${esc(me.groups.join(", "))}` : ""}</div></div></div></div>
    <div>
      <div class="section-head"><h2 class="section-title">My agent tokens</h2><span class="muted small">${mine.length} active</span></div>
      <div class="table-card"><div class="table-wrap"><table>
        <tr><th>Token</th><th>Expires</th><th>Last used</th><th></th></tr>
        ${mine.length ? mine.map((t, i) => `<tr><td><span class="name">${logo(t.label, i)} <span>${esc(t.label)}<div class="sub mono">${esc(t.hint)}</div></span></span></td><td class="small nowrap">${esc(fmtDate(t.expires_at))}</td><td class="small nowrap">${t.last_used_at ? esc(fmtTs(t.last_used_at)) : "never"}</td><td class="actions"><button class="btn small danger" data-revoke="${esc(t.id)}"><i class="ph ph-prohibit"></i> Revoke</button></td></tr>`).join("")
          : `<tr><td colspan="4">${emptyState("key", "No tokens yet", "Issue one and paste it into your AI client. It identifies you on every call.")}</td></tr>`}
      </table></div></div>
    </div>
    <div>
      <div class="section-head"><h2 class="section-title">Connected accounts</h2><span class="muted small">Backends that need your own sign-in</span></div>
      <div class="card">
        ${oauthBackends.length ? oauthBackends.map((p, i) => `<div class="link-row">
          <div><span class="name">${logo(p.name, i)} <span>${esc(p.name)}<div class="sub">${conns[i] ? `${conns[i].kind === "login" ? `Signed in as ${esc(conns[i].username)}, ` : "Linked "}${esc(fmtTs(conns[i].connected_at))}${conns[i].expires_at ? `, token renews automatically` : ""}` : `Not connected: your calls to ${esc(p.name)} are refused until you ${p.auth_mode === "login" ? "sign in with your " + esc(p.name) + " username and password" : "sign in there"}`}</div></span></span></div>
          <div>${conns[i] ? `${chip("green", "Linked", "check")} <button class="btn small danger" data-disconnect="${esc(p.id)}"><i class="ph ph-link-break"></i> Disconnect</button>` : `<button class="btn small solid" data-connect="${esc(p.id)}" ${(p.auth_mode === "login" ? p.login_ready : p.oauth_ready) ? "" : "disabled"}><i class="ph ph-${p.auth_mode === "login" ? "sign-in" : "user-circle-plus"}"></i> ${p.auth_mode === "login" ? "Sign in" : "Connect"}</button>`}</div>
        </div>`).join("") : `<p class="muted small" style="margin:0">No backend needs a personal sign-in.</p>`}
      </div>
    </div>
    <div>
      <div class="section-head"><h2 class="section-title">Gateways you can use</h2></div>
      <div class="table-card"><div class="table-wrap"><table>
        <tr><th>Gateway</th><th>Address</th><th>Backends</th><th></th></tr>
        ${usable.length ? usable.map((g) => `<tr><td><strong>${esc(g.name)}</strong></td><td class="mono small url">${esc(g.url)}</td><td class="small">${esc((g.backends || []).map((b) => b.name).join(", "))}</td><td class="actions"><a class="btn small" href="#gateway?g=${esc(g.id)}"><i class="ph ph-robot"></i> How to connect</a></td></tr>`).join("")
          : `<tr><td colspan="4">${emptyState("squares-four", "No gateway yet", "An admin creates gateways and decides who may use them.")}</td></tr>`}
      </table></div></div>
    </div>`;
  $("#btn-issue").onclick = () => issueDialog(pages.me);
  $("#page").querySelectorAll("[data-revoke]").forEach((b) => b.onclick = async () => {
    if (!confirm("Revoke this token? The agent loses access immediately.")) return;
    try { await api("POST", `/api/tokens/${b.dataset.revoke}/revoke`); toast("Token revoked"); pages.me(); } catch (err) { toast("Revoke failed", err.message, 4500); }
  });
  $("#page").querySelectorAll("[data-connect]").forEach((b) => b.onclick = () => { const p = reg.items.find((x) => x.id === b.dataset.connect); (p.auth_mode === "login" ? loginConnectDialog : connectDialog)(p, pages.me); });
  $("#page").querySelectorAll("[data-disconnect]").forEach((b) => b.onclick = async () => {
    if (!confirm("Disconnect this account? Your calls to it are refused until you link it again.")) return;
    try { await api("DELETE", `/api/registry/${b.dataset.disconnect}/connections/${me.user_id}`); toast("Account disconnected"); pages.me(); } catch (err) { toast("Disconnect failed", err.message, 4500); }
  });
};

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
