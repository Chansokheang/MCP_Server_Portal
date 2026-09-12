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

// ---- small UI helpers ----
function toast(title, sub = "", ms = 3000) {
  const el = $("#toast");
  el.innerHTML = `<span class="mark"><i class="ph ph-check"></i></span><div><strong>${esc(title)}</strong>${sub ? `<span>${esc(sub)}</span>` : ""}</div>`;
  el.classList.remove("hidden");
  clearTimeout(toast._t); toast._t = setTimeout(() => el.classList.add("hidden"), ms);
}
function modal(html) { $("#modal-body").innerHTML = html; $("#modal").classList.remove("hidden"); }
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
  $("#whoami-avatar").textContent = initials(session.user.name);
  $("#whoami-name").textContent = session.user.name;
  go(location.hash.replace("#", "") || "overview");
}

// ---- router ----
const pages = {};
const titles = { overview: "Overview", registry: "MCP Registry", access: "Access Control", tokens: "Agent Tokens", security: "Security", audit: "Audit Log" };
function hashParam(name) { return new URLSearchParams(location.hash.split("?")[1] || "").get(name); }
function setHash(page, params) { const q = new URLSearchParams(params || {}).toString(); location.hash = q ? `${page}?${q}` : page; }
function go(page) {
  page = (page || "").split("?")[0];
  if (!pages[page]) page = "overview";
  if (location.hash.slice(1).split("?")[0] !== page) location.hash = page;
  document.querySelectorAll(".rail-nav a").forEach((a) => a.classList.toggle("active", a.dataset.page === page));
  $("#page-title").textContent = titles[page];
  $("#tabs").classList.add("hidden");
  $("#page").innerHTML = SKELETON;
  pages[page]().catch((err) => { $("#page").innerHTML = `<div class="card">${emptyState("warning-circle", "Could not load this page", esc(err.message))}<div style="text-align:center"><button class="btn" onclick="location.reload()">Retry</button></div></div>`; });
}
document.querySelectorAll(".rail-nav a").forEach((a) => a.addEventListener("click", () => go(a.dataset.page)));
window.addEventListener("hashchange", () => session && go(location.hash.slice(1).split("?")[0]));

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
            <button class="btn small" data-act="test" data-id="${esc(p.id)}"><i class="ph ph-plugs"></i> Test connection</button>
            <button class="btn small" data-act="access" data-id="${esc(p.id)}"><i class="ph ph-sliders-horizontal"></i> Tools</button>
            <button class="btn small ${p.status === "published" ? "" : "solid"}" data-act="${p.status === "published" ? "unpublish" : "publish"}" data-id="${esc(p.id)}"><i class="ph ${p.status === "published" ? "ph-eye-slash" : "ph-check"}"></i> ${p.status === "published" ? "Unpublish" : "Publish"}</button>
            ${p.id !== "bizplay" ? `<button class="btn small danger" data-act="delete" data-id="${esc(p.id)}"><i class="ph ph-trash"></i></button>` : ""}
          </div>
        </div>`).join("")}</div>`
      : `<div class="card">${emptyState("plugs-connected", "No APIs here", "Register one with an OpenAPI spec. The API itself is not changed.")}</div>`}
    </div>
    <div class="callout"><i class="ph ph-info"></i><span><strong>Published</strong> makes the MCP endpoint reachable by agents and enforces this portal's tool policy. Listing in public directories (official MCP Registry, Claude, Copilot Studio, Agentforce) is a separate step.</span></div>`;

  $("#btn-register").onclick = registerDialog;
  $("#page").querySelectorAll("[data-act]").forEach((b) => b.onclick = async () => {
    const { act, id } = b.dataset;
    try {
      if (act === "access") { setHash("access", { p: id }); return; }
      if (act === "test") return testDialog(id);
      if (act === "delete") { if (!confirm(`Delete provider ${id}?`)) return; await api("DELETE", `/api/registry/${id}`); toast("Provider deleted", id); }
      else { await api("POST", `/api/registry/${id}/${act}`); toast(act === "publish" ? "Published" : "Unpublished", `${id} ${act === "publish" ? "is now reachable by agents" : "is hidden from agents"}`); }
      pages.registry();
    } catch (err) { toast("Action failed", err.message, 4500); }
  });
};

async function registerDialog() {
  modal(`<h2><i class="ph ph-plus-circle"></i> Register an API</h2>
    <form id="reg-form" class="form">
      <label class="field">Provider name <input name="name" placeholder="e.g. Bizplay HR API" required></label>
      <label class="field">Base URL of the existing API <input name="base_url" placeholder="https://api.example.com" required></label>
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
    try { const p = await api("POST", "/api/registry", { ...f, spec_source: "uploaded" }); closeModal(); toast("Registered as draft", `${p.tool_count} tools generated from the spec`); pages.registry(); }
    catch (err) { $("#reg-error").textContent = err.message; }
  };
}

async function testDialog(id) {
  modal(`<h2><i class="ph ph-plugs"></i> Connection test: ${esc(id)}</h2>${SKELETON}`);
  try {
    const r = await api("POST", `/api/registry/${id}/test`);
    modal(`<h2><i class="ph ph-plugs"></i> Connection test: ${esc(id)} ${passChip(r.ok)}</h2>
      <div class="table-card"><div class="table-wrap"><table><tr><th>Check</th><th>Path</th><th>HTTP</th><th>Result</th></tr>
      ${r.results.map((x) => `<tr><td>${esc(x.check)}</td><td class="mono">${esc(x.path)}</td><td class="mono">${x.status ?? "n/a"}</td><td>${passChip(x.ok)}${x.error ? `<div class="muted small">${esc(x.error)}</div>` : ""}${x.note ? `<div class="muted small">${esc(x.note)}</div>` : ""}</td></tr>`).join("")}</table></div></div>
      <p class="muted small" style="margin-top:12px">In bearer mode a failing "rejects missing token" check blocks publishing. In open mode the API is public by decision and the gateway carries all the enforcement.</p>
      <div style="display:flex;justify-content:flex-end;margin-top:8px"><button class="btn solid" onclick="document.getElementById('modal').classList.add('hidden')">Close</button></div>`);
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
        <div style="display:flex;justify-content:flex-end;margin-top:8px"><button class="btn solid" id="tok-done">Done</button></div>`);
      $("#tok-copy").onclick = () => navigator.clipboard?.writeText(r.token).then(() => toast("Copied", "Token is on your clipboard"));
      $("#tok-done").onclick = () => { closeModal(); pages.tokens(); };
    } catch (err) { $("#tok-error").textContent = err.message; }
  };
}

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
          </div>
          <p class="muted small" style="margin:12px 0 0">In this mockup the bearer requirements are enforced in code; the switches record the policy. Turning one off lowers the checklist score so reviewers notice.</p>
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
    const body = { [inp.dataset.s]: inp.type === "checkbox" ? inp.checked : Number(inp.value) };
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
if (session?.token) {
  api("GET", "/api/me").then((u) => { session.user = u; enterApp(); }).catch(() => signOut());
} else {
  $("#login").classList.remove("hidden");
}
