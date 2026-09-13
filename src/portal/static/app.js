/* Bizplay MCP onboarding portal. Mockup front end (vanilla JS, no build step). */

const $ = (sel, root = document) => root.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmtTs = (t) => (typeof t === "number" ? new Date(t * 1000) : new Date(t)).toLocaleString();
const fmtDate = (t) => (typeof t === "number" ? new Date(t * 1000) : new Date(t)).toLocaleDateString(undefined, { day: "numeric", month: "long", year: "numeric" });
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
const authChip = (m) => ({ bearer: chip("lilac", "Bearer", "key"), network: chip("amber", "Network", "shield-check"), open: chip("red", "Open", "warning") }[m] || chip("lilac", "Bearer", "key"));
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
  go(location.hash.replace("#", "") || "overview");
}

// ---- router ----
const pages = {};
const titles = { overview: "Overview", registry: "MCP Registry", provider: "API details", access: "Access Control", tokens: "Agent Tokens", security: "Security", audit: "Audit Log" };
// Pages reached from another page keep that page's rail icon lit.
const RAIL_OF = { provider: "registry" };
function hashParam(name) { return new URLSearchParams(location.hash.split("?")[1] || "").get(name); }
function setHash(page, params) { const q = new URLSearchParams(params || {}).toString(); location.hash = q ? `${page}?${q}` : page; }
function go(page) {
  page = (page || "").split("?")[0];
  if (!pages[page]) page = "overview";
  if (location.hash.slice(1).split("?")[0] !== page) location.hash = page;
  const rail = RAIL_OF[page] || page;
  document.querySelectorAll(".rail-nav a").forEach((a) => a.classList.toggle("active", a.dataset.page === rail));
  $("#page-title").textContent = titles[page];
  $("#tabs").classList.add("hidden");
  $("#page").innerHTML = SKELETON;
  pages[page]().catch((err) => { $("#page").innerHTML = `<div class="card">${emptyState("warning-circle", "Could not load this page", esc(err.message))}<div style="text-align:center"><button class="btn" onclick="location.reload()">Retry</button></div></div>`; });
}
document.querySelectorAll(".rail-nav a").forEach((a) => a.addEventListener("click", () => go(a.dataset.page)));
window.addEventListener("hashchange", () => session && go(location.hash.slice(1).split("?")[0]));

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
    + `<span class="spacer"></span>` + (note ? `<span class="tab-note"><span class="tab-ic"><i class="ph ph-check"></i></span><span><strong>${esc(note.title)}</strong><span>${esc(note.sub)}</span></span></span>` : "");
  el.classList.remove("hidden");
  el.querySelectorAll(".tab").forEach((b) => b.onclick = () => onPick(b.dataset.key));
}

// ---- Overview ----
pages.overview = async () => {
  const d = await api("GET", "/api/overview");
  $("#page").innerHTML = `
    <div class="stats">
      <div class="stat"><span class="num">${d.providers}</span><span class="lbl">Registered APIs, ${d.published} published</span></div>
      <div class="stat"><span class="num">${d.tools_enabled}</span><span class="lbl">Tools enabled for agents</span></div>
      <div class="stat"><span class="num">${d.tokens_active}</span><span class="lbl">Active agent tokens</span></div>
      <div class="stat"><span class="num" style="color:${d.score >= 70 ? "var(--green-ink)" : "var(--amber-ink)"}">${d.score}%</span><span class="lbl">Security checklist</span></div>
    </div>
    <div class="two">
      <div>
        <h2 class="section-title">How a request flows</h2>
        <div class="card">
          <div class="flow">
            <div class="node"><strong>AI agent</strong><span class="muted">Claude, Copilot, Agentforce</span></div><span class="arrow">agent token</span>
            <div class="node hl"><strong>MCP Gateway</strong>auth, policy, company scope, audit</div><span class="arrow">service token</span>
            <div class="node"><strong>Bizplay API</strong><span class="muted">unchanged</span></div>
          </div>
          <p class="muted small" style="margin:4px 0 0">Two separate tokens. One identifies the end user to the gateway, one identifies the gateway to the API. Neither reaches the model.</p>
        </div>
        <h2 class="section-title" style="margin-top:22px">Security checklist</h2>
        <div class="checklist">${d.checklist.map((c) => `<div class="check-item ${c.ok ? "ok" : "bad"}"><span class="mark"><i class="ph ${c.ok ? "ph-check" : "ph-x"}"></i></span><div><strong>${esc(c.label)}</strong><div class="muted small">${esc(c.detail)}</div></div></div>`).join("")}</div>
      </div>
      <div>
        <h2 class="section-title">Recent gateway activity</h2>
        <div class="table-card">${d.audit_recent.length ? `<div class="table-wrap"><table><tr><th>Time</th><th>User</th><th>Tool</th><th>Result</th></tr>${d.audit_recent.map((e) => `<tr><td class="small">${esc(fmtTs(e.ts))}</td><td><span class="mono">${esc(e.user_id)}</span> ${chip("", e.via || "env")}</td><td class="mono">${esc(e.tool)}</td><td>${outcomeChip(e.outcome)}</td></tr>`).join("")}</table></div>` : emptyState("chat-circle-dots", "No gateway calls yet", "Ask Claude something that uses a Bizplay tool and it shows up here.")}</div>
      </div>
    </div>`;
};

// ---- Registry ----
pages.registry = async () => {
  const d = await api("GET", "/api/registry");
  const filter = hashParam("f") || "all";
  const items = d.items.filter((p) => filter === "all" || p.status === filter);
  renderTabs([
    { key: "all", label: "All APIs", icon: "squares-four", count: d.items.length },
    { key: "published", label: "Published", icon: "check-circle", count: d.items.filter((p) => p.status === "published").length },
    { key: "draft", label: "Drafts", icon: "pencil-simple", count: d.items.filter((p) => p.status === "draft").length },
  ], filter, (k) => { setHash("registry", { f: k }); pages.registry(); },
  { title: "Registry live", sub: `${d.items.filter((p) => p.status === "published").length} API(s) reachable by agents` });

  $("#page").innerHTML = `
    <div>
      <div style="display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:12px">
        <h2 class="section-title" style="margin:0">Registered APIs</h2>
        <button class="btn solid" id="btn-register"><i class="ph ph-plus"></i> Register API</button>
      </div>
      ${items.length ? `<div class="cards">${items.map((p, i) => `
        <div class="card lift">
          <div class="card-head"><span class="card-brand">${logo(p.name, i)} ${esc(p.name)}</span>${authChip(p.auth_mode)}</div>
          <div class="tiles">${tile("plug", "Tools", `${p.tools_enabled} of ${p.tool_count} enabled`)}${tile("calendar-blank", "Registered", fmtDate(p.created_at))}</div>
          <h3 class="card-title">${esc(p.base_url.replace(/^https?:\/\//, ""))}</h3>
          <p class="card-desc">MCP endpoint ${esc(p.mcp_url)}${p.tool_prefix ? `, tools named ${esc(p.tool_prefix)}*` : ""}. Spec from ${esc(p.spec_source)}. Owner ${esc(p.owner)}.</p>
          <div class="card-actions">
            <button class="btn small" data-act="detail" data-id="${esc(p.id)}"><i class="ph ph-info"></i> View details</button>
            <button class="btn small solid" data-act="usage" data-id="${esc(p.id)}"><i class="ph ph-robot"></i> How to use it</button>
          </div>
        </div>`).join("")}</div>`
      : `<div class="card">${emptyState("plugs-connected", "No APIs here", "Register one with an OpenAPI spec. The API itself is not changed.")}</div>`}
    </div>
    <div class="callout"><i class="ph ph-info"></i><span><strong>Published</strong> makes the MCP endpoint reachable by agents and enforces this portal's tool policy. The gateway picks up a newly published API on the next request, so no restart is needed. Listing in public directories (official MCP Registry, Claude, Copilot Studio, Agentforce) is a separate step.</span></div>`;

  $("#btn-register").onclick = registerDialog;
  $("#page").querySelectorAll("[data-act]").forEach((b) => b.onclick = async () => {
    const { act, id } = b.dataset;
    try {
      if (act === "detail") { setHash("provider", { p: id }); return; }
      if (act === "usage") { setHash("provider", { p: id, c: "claude-desktop" }); return; }
      await api("POST", `/api/registry/${id}/${act}`);
      toast(act === "publish" ? "Published" : "Unpublished", `${id} ${act === "publish" ? "is now reachable by agents" : "is hidden from agents"}`);
      pages.registry();
    } catch (err) { toast("Action failed", err.message, 4500); }
  });
};

async function registerDialog() {
  modal(`<h2><i class="ph ph-plus-circle"></i> Register an API</h2>
    <form id="reg-form" class="form">
      <label class="field">Provider name <input name="name" placeholder="e.g. Bizplay HR API" required></label>
      <label class="field">Base URL of the existing API <input name="base_url" placeholder="https://api.example.com" required></label>
      <label class="field">MCP endpoint agents will use <input name="mcp_url" value="${esc(SERVER.default_mcp_url || "")}" placeholder="https://your-host/mcp">
        <span class="muted small">Any address that reaches this gateway. Use an HTTPS one for claude.ai and ChatGPT.</span></label>
      <label class="field">How is the API protected?
        <select name="auth_mode" id="reg-mode">
          <option value="bearer">Bearer token: the API rejects anonymous calls (recommended)</option>
          <option value="network">Network-isolated: no token, only the gateway's address can reach it</option>
          <option value="open">Open: anyone can call it (demo data only, recorded as accepted risk)</option>
        </select></label>
      <label class="field" id="reg-token-field">Service bearer token the gateway will send <input name="service_token" placeholder="issued by the provider (stored, never shown again)"></label>
      <label class="field hidden" id="reg-allowlist-field">Gateway address the API allows <input name="allowlist" placeholder="e.g. 203.0.113.10 or 10.0.0.0/24"></label>
      <div class="callout warn hidden" id="reg-open-warning"><i class="ph ph-warning"></i><span><strong>Open API.</strong> The gateway still authenticates agents, applies tool policy, and limits results to the caller's company, but anyone who knows the URL can bypass it. The overview will show this as an accepted risk.</span></div>
      <label class="field">OpenAPI spec (JSON) <textarea name="spec" placeholder='{"openapi":"3.0.3","paths":{...}}' required></textarea></label>
      <div style="display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap">
        <button type="button" class="btn small" id="reg-sample"><i class="ph ph-file-arrow-down"></i> Load Bizplay sample spec</button>
        <span style="display:flex;gap:8px"><button type="button" class="btn" id="reg-cancel">Cancel</button><button class="btn solid" type="submit"><i class="ph ph-check"></i> Register as draft</button></span>
      </div>
      <p class="error" id="reg-error"></p>
    </form>`);
  $("#reg-cancel").onclick = closeModal;
  $("#reg-mode").onchange = (e) => {
    const m = e.target.value;
    $("#reg-token-field").classList.toggle("hidden", m !== "bearer");
    $("#reg-allowlist-field").classList.toggle("hidden", m !== "network");
    $("#reg-open-warning").classList.toggle("hidden", m !== "open");
  };
  $("#reg-sample").onclick = async () => {
    const r = await fetch("/static/sample-openapi.json"); $("#reg-form [name=spec]").value = await r.text();
    $("#reg-form [name=name]").value ||= "Bizplay Expense API (copy)";
    $("#reg-form [name=base_url]").value ||= "http://127.0.0.1:18080";
    $("#reg-form [name=service_token]").value ||= "demo-service-token";
  };
  $("#reg-form").onsubmit = async (e) => {
    e.preventDefault(); const f = Object.fromEntries(new FormData(e.target));
    try {
      const p = await api("POST", "/api/registry", { ...f, spec_source: "uploaded" });
      toast("Registered as draft", `${p.tool_count} tools generated from the spec`);
      testDialog(p.id);  // prove the connection now, while the details are fresh
    } catch (err) { $("#reg-error").textContent = err.message; }
  };
}

/** Ready-to-paste commands. Issues a token first when the gateway needs one. */
function commandResult(p, token) {
  const hdr = token ? ` \\\n  --header "Authorization: Bearer ${token}"` : "";
  const plainHttp = p.mcp_url.startsWith("http://") && !LOCAL_HOST.test(hostOf(p.mcp_url));
  const desktop = `"${p.id}": ` + JSON.stringify({
    command: "npx",
    args: ["-y", "mcp-remote", p.mcp_url, "--transport", "http-only",
      ...(plainHttp ? ["--allow-http"] : []),
      ...(token ? ["--header", `Authorization: Bearer ${token}`] : [])],
  }, null, 2);
  modal(`<h2><i class="ph ph-terminal-window"></i> Connect to ${esc(p.name)}</h2>
    ${token ? `<p class="muted">A token was issued for this command. It is shown once, so copy the command now. Revoke it any time on the Agent Tokens page.</p>`
            : `<p class="muted">This gateway accepts anonymous callers, so no token is needed.</p>`}
    <h2 class="section-title" style="margin-top:14px">Claude Code, one line</h2>
    ${codeBlock("cc-code", `claude mcp add --transport http ${p.id} ${p.mcp_url}${hdr}`)}
    <h2 class="section-title" style="margin-top:16px">Claude Desktop, add under mcpServers</h2>
    ${codeBlock("cc-desktop", desktop, "Needs Node.js. Restart Claude Desktop from the system tray afterwards.")}
    <h2 class="section-title" style="margin-top:16px">Check it from a terminal</h2>
    ${codeBlock("cc-curl", `curl -s ${p.mcp_url} \\\n  -H "Accept: application/json, text/event-stream" \\\n  -H "Content-Type: application/json"${token ? ` \\\n  -H "Authorization: Bearer ${token}"` : ""} \\\n  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'`)}
    <div style="display:flex;justify-content:flex-end;margin-top:14px"><button class="btn solid" id="cc-done">Done</button></div>`);
  $("#cc-done").onclick = () => { closeModal(); pages.provider(); };
}

async function commandDialog(p) {
  if (SERVER.require_agent_token === false) return commandResult(p, null);
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
      commandResult(p, r.token);
    } catch (err) { $("#cc-error").textContent = err.message; }
  };
}

async function editDialog(p) {
  const opt = (v, label) => `<option value="${v}" ${p.auth_mode === v ? "selected" : ""}>${label}</option>`;
  modal(`<h2><i class="ph ph-pencil-simple"></i> Edit connection</h2>
    <form id="ed-form" class="form">
      <label class="field">Provider name <input name="name" value="${esc(p.name)}"></label>
      <label class="field">Base URL of the existing API <input name="base_url" value="${esc(p.base_url)}">
        <span class="muted small">Host only. The paths come from the spec, so a base URL ending in a path the spec also has causes 404.</span></label>
      <label class="field">MCP endpoint agents will use <input name="mcp_url" value="${esc(p.mcp_url)}">
        <span class="muted small">Use the address reachable from outside this server, not 127.0.0.1.</span></label>
      <label class="field">How is the API protected?
        <select name="auth_mode" id="ed-mode">
          ${opt("bearer", "Bearer token: the API rejects anonymous calls")}
          ${opt("network", "Network-isolated: no token, only the gateway's address can reach it")}
          ${opt("open", "Open: anyone can call it (demo data only, recorded as accepted risk)")}
        </select></label>
      <label class="field ${p.auth_mode === "bearer" ? "" : "hidden"}" id="ed-token-field">Service bearer token <input name="service_token" placeholder="leave blank to keep the stored one"></label>
      <label class="field ${p.auth_mode === "network" ? "" : "hidden"}" id="ed-allowlist-field">Gateway address the API allows <input name="allowlist" value="${esc(p.allowlist || "")}" placeholder="e.g. 203.0.113.10"></label>
      <div style="display:flex;justify-content:flex-end;gap:8px"><button type="button" class="btn" id="ed-cancel">Cancel</button><button class="btn solid" type="submit"><i class="ph ph-check"></i> Save</button></div>
      <p class="error" id="ed-error"></p>
    </form>`);
  $("#ed-cancel").onclick = closeModal;
  $("#ed-mode").onchange = (e) => {
    $("#ed-token-field").classList.toggle("hidden", e.target.value !== "bearer");
    $("#ed-allowlist-field").classList.toggle("hidden", e.target.value !== "network");
  };
  $("#ed-form").onsubmit = async (e) => {
    e.preventDefault(); const f = Object.fromEntries(new FormData(e.target));
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
  renderTabs(reg.items.map((p) => ({ key: p.id, label: p.name, icon: "plugs-connected", count: p.tools_enabled })), pid,
    (k) => { setHash("access", { p: k }); pages.access(); });

  $("#page").innerHTML = `
    <div class="stats">
      <div class="stat"><span class="num">${total}</span><span class="lbl">Endpoints in this API</span></div>
      <div class="stat"><span class="num" style="color:var(--green-ink)">${enabled}</span><span class="lbl">Enabled for agents</span></div>
      <div class="stat"><span class="num">${reads}</span><span class="lbl">Read tools</span></div>
      <div class="stat"><span class="num" style="color:var(--amber-ink)">${writes}</span><span class="lbl">Write tools, ${d.items.filter((t) => t.kind === "write" && t.enabled).length} enabled</span></div>
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

  $("#page").innerHTML = `
    <div>
      <div style="display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:12px">
        <h2 class="section-title" style="margin:0">Agent tokens</h2>
        <button class="btn solid" id="btn-issue"><i class="ph ph-plus"></i> Issue token</button>
      </div>
      ${items.length ? `<div class="cards">${items.map((t, i) => `
        <div class="card lift">
          <div class="card-head"><span class="card-brand">${logo(t.agent, i)} ${esc(t.agent)}</span>${{ active: chip("green", "Active", "check"), revoked: chip("red", "Revoked", "prohibit"), expired: chip("amber", "Expired", "hourglass") }[state(t)]}</div>
          <div class="tiles">${tile("user", "Bizplay user", `${t.sub}, ${t.role}`)}${tile("calendar-blank", "Expires", fmtDate(t.expires_at))}</div>
          <h3 class="card-title">${esc(t.label)}</h3>
          <p class="card-desc">${esc(t.company)}. ${t.scopes.join(", ")}. ${t.last_used_at ? `Last used ${esc(fmtTs(t.last_used_at))}.` : "Never used."} Issued by ${esc(t.created_by)}.</p>
          <div class="card-actions">
            <span class="btn small" style="cursor:default"><i class="ph ph-key"></i> <span class="mono">${esc(t.hint)}</span></span>
            ${alive(t) ? `<button class="btn small solid" data-revoke="${esc(t.id)}"><i class="ph ph-prohibit"></i> Revoke</button>` : ""}
          </div>
        </div>`).join("")}</div>`
      : `<div class="card">${emptyState("key", "No tokens here", "Issue one to connect an AI agent to the gateway over HTTP.")}</div>`}
    </div>`;
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

/** Setup guides written for one registered API: its endpoint, prefix and a real tool of its own. */
function clientGuides(p, tools) {
  const enabled = tools.filter((t) => t.enabled);
  const sample = enabled.find((t) => t.kind === "read") || enabled[0];
  const toolName = sample ? `${p.tool_prefix || ""}${sample.name}` : "a_tool_name";
  const sampleArgs = sample && /\{corpNo\}/.test(sample.route || "") ? `{"corpNo": "1078836129"}` : "{}";
  const port = portOf(p.mcp_url);
  const localModule = p.has_spec ? "bizplay_mcp.registry_gateway" : "bizplay_mcp.server";
  const env = p.has_spec
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
  const plainHttpRemote = p.mcp_url.startsWith("http://") && !LOCAL_HOST.test(hostOf(p.mcp_url));
  const remoteArgs = ["-y", "mcp-remote", p.mcp_url, "--transport", "http-only",
    ...(plainHttpRemote ? ["--allow-http"] : []),
    ...(needsToken ? ["--header", "Authorization: Bearer <YOUR_AGENT_TOKEN>"] : [])];
  const remoteCfg = `"${p.id}": ` + JSON.stringify({ command: "npx", args: remoteArgs }, null, 2);
  const headerArg = needsToken ? ` \\\n  --header "Authorization: Bearer <YOUR_AGENT_TOKEN>"` : "";
  const endpointIsLocal = LOCAL_HOST.test(hostOf(p.mcp_url));

  return {
    "claude-desktop": {
      label: "Claude Desktop", icon: "desktop", ready: true,
      lead: `Claude Desktop runs on your own machine, so it either connects to this gateway over the network or starts its own copy locally. Pick one of the two entries below.`,
      steps: [
        { t: "Open the config file", b: `<p>Windows: <span class="mono">%APPDATA%\\Claude\\claude_desktop_config.json</span><br>macOS: <span class="mono">~/Library/Application Support/Claude/claude_desktop_config.json</span></p>` },
        { t: `Option A, connect to this gateway${endpointIsLocal ? "" : " (recommended)"}`,
          b: codeBlock("g-remote", remoteCfg, endpointIsLocal
            ? "This endpoint is 127.0.0.1, so it only works if Claude Desktop runs on the same machine as the gateway. Use Edit connection to set the address other machines can reach."
            : "Needs Node.js. Issue a token on the Agent Tokens page and paste it in place of the placeholder.") },
        { t: "Option B, run a local copy instead",
          b: codeBlock("g-desktop", desktopCfg, `Replace the directory with the path to the project on the machine running Claude Desktop. This value is where the portal's own server keeps it. No agent token is needed, because identity comes from the config.`) },
        { t: "Quit Claude Desktop from the system tray, then reopen", b: `<p>Closing the window is not enough. The tools appear in the tools menu of a new chat.</p>` },
        { t: "Try it", b: `<p>Ask for something this API covers, for example a call to <span class="mono">${esc(toolName)}</span>.</p>` },
      ],
    },
    "claude-code": {
      label: "Claude Code", icon: "terminal-window", ready: true,
      lead: needsToken
        ? `Claude Code calls this API over HTTP at ${p.mcp_url} and sends an agent token as a header. Use Connect command above to get a line with the token already in it.`
        : `This gateway accepts anonymous callers, so one line with no token connects Claude Code to ${p.mcp_url}.`,
      steps: [
        { t: "Add the server", b: codeBlock("g-code-1", `claude mcp add --transport http ${p.id} ${p.mcp_url}${headerArg}`,
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
        { t: "Connection details", b: `<dl class="kv"><dt>Endpoint</dt><dd>${esc(p.mcp_url)}</dd><dt>Transport</dt><dd>streamable HTTP</dd><dt>Header</dt><dd>Authorization: Bearer &lt;token&gt;</dd><dt>Tool names</dt><dd>${esc(p.tool_prefix || "no prefix")}</dd></dl>` },
        { t: "Python, with the FastMCP client", b: codeBlock("g-py", `from fastmcp import Client\nfrom fastmcp.client.transports import StreamableHttpTransport\n\nclient = Client(StreamableHttpTransport(\n    "${p.mcp_url}", auth="<YOUR_AGENT_TOKEN>"))\n\nasync with client as c:\n    tools = await c.list_tools()\n    result = await c.call_tool("${toolName}", ${sampleArgs})`) },
        { t: "Raw HTTP, to check the token", b: codeBlock("g-curl", `curl -s ${p.mcp_url} \\\n  -H "Authorization: Bearer <YOUR_AGENT_TOKEN>" \\\n  -H "Accept: application/json, text/event-stream" \\\n  -H "Content-Type: application/json" \\\n  -d '{"jsonrpc":"2.0","id":1,"method":"initialize",\n       "params":{"protocolVersion":"2025-06-18","capabilities":{},\n                 "clientInfo":{"name":"curl","version":"0"}}}'`, "Without the header this returns 401. That is the gateway refusing an unauthenticated agent.") },
      ],
    },
    "chatgpt": (() => {
      const isHttps = p.mcp_url.startsWith("https://");
      const ready = isHttps && !needsToken;
      const addSteps = [
        { t: "Copy this endpoint", b: codeBlock("g-url", p.mcp_url, "This exact URL, including the /mcp path. The root path serves nothing and shows Not found.") },
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
        { t: "Microsoft Copilot Studio", b: `<p>Add the gateway as a custom connector, point it at ${esc(p.mcp_url)} on its public address, then enable it as a tool for the agent.</p>` },
        { t: "Salesforce Agentforce", b: `<p>Register the endpoint in the Agentforce MCP registry, then grant the agent access to the tools you enabled for this API.</p>` },
        { t: "What to prepare", b: `<p>A hosted gateway with a certificate, OAuth mapped to the customer's identity provider, and an agent token policy per company. The Security page tracks what is still open.</p>` },
      ],
    },
  };
}

pages.provider = async () => {
  const pid = hashParam("p");
  const reg = await api("GET", "/api/registry");
  const p = reg.items.find((x) => x.id === pid);
  if (!p) {
    $("#page").innerHTML = `<div class="card">${emptyState("plugs", "API not found", "It may have been deleted. Open the registry to see what is registered.")}
      <div style="text-align:center"><button class="btn" onclick="location.hash='registry'">Back to registry</button></div></div>`;
    return;
  }
  const d = await api("GET", `/api/registry/${pid}/tools`);
  const tools = d.items, enabled = tools.filter((t) => t.enabled);
  const guides = clientGuides(p, tools);
  const key = guides[hashParam("c")] ? hashParam("c") : "claude-desktop";
  const g = guides[key];
  $("#page-title").textContent = p.name;
  renderTabs(Object.entries(guides).map(([k, v]) => ({ key: k, label: v.label, icon: v.icon })), key,
    (k) => { setHash("provider", { p: pid, c: k }); pages.provider(); },
    p.status === "published" ? { title: "Live", sub: `${enabled.length} tools reachable by agents` } : null);

  const shown = enabled.slice(0, 10);
  $("#page").innerHTML = `
    <div><button class="btn small" id="back-registry"><i class="ph ph-arrow-left"></i> All APIs</button></div>
    <div class="card">
      <div class="card-head">
        <span class="card-brand" style="font-size:16px">${logo(p.name, 0)} ${esc(p.name)}</span>
        <span style="display:flex;gap:6px;flex-wrap:wrap">${authChip(p.auth_mode)}${statusChip(p.status)}</span>
      </div>
      <div class="tiles" style="grid-template-columns:repeat(4, 1fr)">
        <div class="tile"><span class="k"><i class="ph ph-link"></i>MCP endpoint
          <button class="btn small copy" data-copy="p-endpoint" title="Copy the endpoint" style="margin-left:auto;padding:2px 7px"><i class="ph ph-copy"></i></button></span>
          <span class="v mono" id="p-endpoint">${esc(p.mcp_url)}</span></div>
        ${tile("cloud", "Upstream API", p.base_url.replace(/^https?:\/\//, ""), true)}
        ${tile("plug", "Tools", `${p.tools_enabled} of ${p.tool_count} enabled`)}
        ${tile("textbox", "Tool names", p.tool_prefix ? `${p.tool_prefix}*` : "no prefix")}
      </div>
      <p class="card-desc" style="-webkit-line-clamp:3">Spec from ${esc(p.spec_source)}. Registered by ${esc(p.owner)} on ${esc(fmtDate(p.created_at))}. ${p.auth_mode === "open" ? "The upstream API accepts anonymous calls, so the gateway carries all the enforcement." : p.auth_mode === "network" ? `Reachable only from ${esc(p.allowlist || "the allowlisted gateway address")}.` : "The gateway sends a stored service token on every call."}</p>
      <div class="card-actions">
        <button class="btn small solid" data-act="command"><i class="ph ph-terminal-window"></i> Connect command</button>
        <button class="btn small" data-act="edit"><i class="ph ph-pencil-simple"></i> Edit connection</button>
        <button class="btn small" data-act="test"><i class="ph ph-plugs"></i> Test connection</button>
        <button class="btn small" data-act="access"><i class="ph ph-sliders-horizontal"></i> Manage tools</button>
        <button class="btn small ${p.status === "published" ? "" : "solid"}" data-act="${p.status === "published" ? "unpublish" : "publish"}"><i class="ph ${p.status === "published" ? "ph-eye-slash" : "ph-check"}"></i> ${p.status === "published" ? "Unpublish" : "Publish"}</button>
        ${p.id !== "bizplay" ? `<button class="btn small danger" data-act="delete"><i class="ph ph-trash"></i> Delete</button>` : ""}
      </div>
    </div>
    ${LOCAL_HOST.test(hostOf(p.mcp_url)) && !LOCAL_HOST.test(location.hostname) ? `<div class="callout warn"><i class="ph ph-warning"></i><span><strong>Other machines cannot reach this endpoint.</strong> It points at ${esc(hostOf(p.mcp_url))}, which only resolves on the server itself. Use Edit connection and set it to <span class="mono">http://${esc(location.hostname)}:${esc(portOf(p.mcp_url))}/mcp</span>, or set PUBLIC_HOST in the server's .env file.</span></div>` : ""}
    <div>
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:2px">
        <h2 class="section-title" style="margin:0">Use ${esc(p.name)} from ${esc(g.label)}</h2>
        ${g.ready ? chip("green", "Works today", "check") : chip("amber", "Needs hosting and OAuth", "warning")}
      </div>
      <p class="muted" style="max-width:76ch">${esc(g.lead)}</p>
      <div class="steps">${g.steps.map((s, i) => `<div class="step"><span class="step-n">${i + 1}</span><div class="step-b"><strong>${esc(s.t)}</strong>${s.b}</div></div>`).join("")}</div>
    </div>
    <div>
      <h2 class="section-title">Tools this API exposes to agents</h2>
      <div class="table-card"><div class="table-wrap"><table><tr><th>Tool name the agent calls</th><th>Kind</th><th>Upstream endpoint</th></tr>
      ${shown.length ? shown.map((t) => `<tr><td class="mono">${esc((p.tool_prefix || "") + t.name)}${t.summary ? `<div class="muted small">${esc(t.summary)}</div>` : ""}</td><td>${t.kind === "write" ? chip("amber", "write", "pencil-simple") : chip("lilac", "read", "eye")}${t.confirm ? ` ${chip("", "confirm first")}` : ""}</td><td class="mono small">${esc(t.route || "composed from several endpoints")}</td></tr>`).join("")
        : `<tr><td colspan="3">${emptyState("sliders-horizontal", "No tools enabled", "Enable some on the Access Control page and they appear here.")}</td></tr>`}
      </table></div></div>
      ${enabled.length > shown.length ? `<p class="muted small" style="margin-top:8px">${enabled.length - shown.length} more enabled. Open Manage tools to see the full list.</p>` : ""}
    </div>
    <div class="callout"><i class="ph ph-key"></i><span>Results are limited to the company on the caller's token, and every call is written to the audit log. Tokens are shown once, so issue a new one and revoke the old if you lost it.</span></div>`;

  $("#back-registry").onclick = () => { location.hash = "registry"; };
  $("#page").querySelectorAll("[data-act]").forEach((b) => b.onclick = async () => {
    const act = b.dataset.act;
    try {
      if (act === "access") { setHash("access", { p: pid }); return; }
      if (act === "command") return commandDialog(p);
      if (act === "edit") return editDialog(p);
      if (act === "test") return testDialog(pid);
      if (act === "delete") {
        if (!confirm(`Delete ${p.name}?`)) return;
        await api("DELETE", `/api/registry/${pid}`); toast("Provider deleted", p.name); location.hash = "registry"; return;
      }
      await api("POST", `/api/registry/${pid}/${act}`);
      toast(act === "publish" ? "Published" : "Unpublished", `${p.name} ${act === "publish" ? "is now reachable by agents" : "is hidden from agents"}`);
      pages.provider();
    } catch (err) { toast("Action failed", err.message, 4500); }
  });
};

// ---- Security ----
pages.security = async () => {
  const d = await api("GET", "/api/security");
  const s = d.settings;
  $("#page").innerHTML = `
    <div class="two">
      <div>
        <h2 class="section-title">Gateway settings</h2>
        <div class="card">
          <div class="form">
            <label class="check"><input type="checkbox" class="switch" data-s="require_upstream_bearer" ${s.require_upstream_bearer ? "checked" : ""}> Require a bearer token on every Bizplay API endpoint</label>
            <label class="check"><input type="checkbox" class="switch" data-s="require_gateway_bearer" ${s.require_gateway_bearer ? "checked" : ""}> Require an agent token on the MCP gateway (HTTP)</label>
            <label class="check"><input type="checkbox" class="switch" data-s="confirm_on_write" ${s.confirm_on_write ? "checked" : ""}> Force user confirmation on all write tools</label>
            <label class="field">Default agent token lifetime (days) <input type="number" data-s="token_ttl_days" value="${s.token_ttl_days}" min="1" max="365" style="width:140px"></label>
            <label class="field">Public MCP endpoint <input data-s="public_mcp_url" value="${esc(s.public_mcp_url || "")}" placeholder="https://your-host/mcp, blank to use this server's own address">
              <span class="muted small">The address agents reach the gateway on, when a tunnel or nginx sits in front. Every newly registered API inherits it.</span></label>
          </div>
          <p class="muted small" style="margin:12px 0 0">The agent token switch is enforced by the gateways, which read it at startup, so restart them after changing it. Turning it off lets anyone call the gateway and lowers the checklist score. The upstream switch records policy only, since that is the provider's own API.</p>
        </div>
        <h2 class="section-title" style="margin-top:22px">Identity mapping</h2>
        <div class="cards">${Object.entries(d.identity).map(([pid, i], n) => `<div class="card"><div class="card-head"><span class="card-brand">${logo(pid, n)} ${esc(pid)}</span>${chip("lilac", i.issuer, "fingerprint")}</div><dl class="kv"><dt>user claim</dt><dd>${esc(i.user_claim)}</dd><dt>role claim</dt><dd>${esc(i.role_claim)}</dd><dt>company claim</dt><dd>${esc(i.company_claim)}</dd></dl></div>`).join("")}</div>
        <p class="muted small" style="margin-top:8px">Production: point the issuer at Bizplay SSO (OAuth 2.1 / OIDC) so tokens are signed JWTs verified by key, not looked up in a table.</p>
      </div>
      <div>
        <h2 class="section-title">Upstream credentials</h2>
        <div class="cards" style="grid-template-columns:1fr">${d.credentials.map((c, n) => `<div class="card"><div class="card-head"><span class="card-brand">${logo(c.provider_id, n)} ${esc(c.label)}</span>${c.rotated_at ? chip("green", "Rotated", "arrows-clockwise") : chip("", "Never rotated", "clock")}</div><div class="tiles">${tile("key", "Secret", c.secret, true)}${tile("calendar-blank", "Rotated", c.rotated_at ? fmtDate(c.rotated_at) : "never")}</div><div class="card-actions"><button class="btn small solid" data-rotate="${esc(c.id)}"><i class="ph ph-arrows-clockwise"></i> Rotate</button></div></div>`).join("")}</div>
        <h2 class="section-title" style="margin-top:22px">Checklist</h2>
        <div class="checklist">${d.checklist.map((c) => `<div class="check-item ${c.ok ? "ok" : "bad"}"><span class="mark"><i class="ph ${c.ok ? "ph-check" : "ph-x"}"></i></span><div><strong>${esc(c.label)}</strong><div class="muted small">${esc(c.detail)}</div></div></div>`).join("")}</div>
      </div>
    </div>`;
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

  $("#page").innerHTML = `
    <div>
      <div style="display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:12px;flex-wrap:wrap">
        <h2 class="section-title" style="margin:0">Gateway calls, newest first</h2>
        <span style="display:flex;gap:8px;align-items:center"><input id="audit-filter" class="filter" placeholder="Filter by user or tool" aria-label="Filter audit log"><button class="btn" id="audit-refresh"><i class="ph ph-arrows-clockwise"></i> Refresh</button></span>
      </div>
      <div class="table-card"><div class="table-wrap"><table id="audit-table"><tr><th>Time (UTC)</th><th>User</th><th>Identified via</th><th>Tool</th><th>Arguments</th><th>Outcome</th><th>Detail</th></tr>
      ${items.length ? items.map((e) => `<tr><td class="small mono">${esc(e.ts)}</td><td class="mono">${esc(e.user_id)}</td><td>${e.via === "bearer" ? chip("green", "bearer", "key") : chip("", "env")}</td><td class="mono">${esc(e.tool)}</td><td class="small mono">${esc(JSON.stringify(e.arguments))}</td><td>${outcomeChip(e.outcome)}</td><td class="small">${esc(e.detail)}</td></tr>`).join("")
        : `<tr><td colspan="7">${emptyState("list-magnifying-glass", "Nothing here", "Every gateway call is recorded with who made it and the outcome.")}</td></tr>`}</table></div></div>
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
