# Bizplay MCP Server (sample)

A working prototype of the "Bizplay MCP Server Gateway" from the strategy report,
built with [FastMCP](https://gofastmcp.com). It lets AI agents such as Claude,
Copilot Studio, or Agentforce use Bizplay corporate card and expense functions.

**The existing Bizplay API is not modified.** The MCP server is a separate
program that calls the existing REST endpoints over HTTP, the same way the web
or mobile app does.

```
AI agent (Claude, Copilot, Agentforce)
        |  MCP protocol (stdio or HTTP)
Bizplay MCP Gateway        <- NEW: this project
  - identity and role checks
  - Korean compliance rules
  - audit log
        |  plain HTTP / JSON
Existing Bizplay REST API  <- UNCHANGED (mocked here)
```

## Two ways to connect the existing API

| | Option A: zero-code | Option B: curated gateway |
|---|---|---|
| File | `src/bizplay_mcp/openapi_gateway.py` | `src/bizplay_mcp/server.py` |
| How | FastMCP reads the API's OpenAPI/Swagger spec and generates one tool per endpoint | Hand-written, task-level tools that call several endpoints each |
| Code per endpoint | None | A few lines in `adapters.py` |
| Permissions, compliance, audit | No | Yes |
| Best for | Fast prototyping, internal use | The real product |

Recommended path: start with Option A to see what agents can do with your API
today, then move the useful tools into Option B and add the guardrails.

## Onboarding portal (mockup)

A self-service web portal where an API provider registers its API with the
gateway and controls who may call what. Mockup scope: **auth, MCP registry,
access control, security**. No load balancing, scaling, or DevOps.

```bash
uv run bizplay-portal
```

Open http://127.0.0.1:18090 and sign in with `admin@bizplay.co.kr` / `admin1234`.
Two demo employees can sign in as members and serve themselves:
`minji@bizplay.co.kr` / `minji1234` (emp001, finance) and
`junho@bizplay.co.kr` / `junho1234` (emp002, hr).

| Page | What it does |
|---|---|
| Overview | Request-flow diagram, security checklist score, recent gateway calls |
| MCP Registry | Register a REST API from its OpenAPI spec or an existing MCP server by URL, publish/unpublish, **Deploy as MCP server**, **Test connection** |
| Access Control | Per tool: enabled, allowed roles, confirm-before-call. Applied by the gateway on the next call |
| Agent Tokens | Issue a bearer token bound to one Bizplay user and role; shown once; revoke takes effect immediately |
| Security | Bearer requirements, default token lifetime, identity mapping, upstream credential rotation |
| Audit Log | Every gateway call with user, how the user was identified (`bearer` or `env`), tool, outcome |

### Auth modes for a registered API

| Mode | API change | Publish rule | What the gateway does |
|---|---|---|---|
| Bearer | API rejects anonymous calls | Service token required, connection test must see 401 | Sends the service token |
| Network-isolated | None, firewall only | Allowlisted gateway address recorded | Sends nothing |
| Open | None | Allowed, flagged red as accepted risk | Sends nothing, enforces everything itself |
| OAuth per user | None; the backend has its own auth server | Authorization URL, token URL and client id known | Sends the calling user's own token, refreshed as needed |

In every mode the gateway still requires agent tokens, applies tool policy, and
scopes results to the caller's company: any argument named `corpNo` (or similar)
must equal the token's company, and records belonging to other companies are
removed from responses.

### Registry gateway: two kinds of backend

`bizplay_mcp/registry_gateway.py` serves every published provider. A provider
is one of:

| Kind | You give the portal | What the gateway does |
|---|---|---|
| REST API (`openapi`) | Base URL plus the OpenAPI spec | FastMCP generates one tool per endpoint (`OpenAPIProvider`) |
| Existing MCP server (`mcp`) | The server's MCP URL | Reads its tool list once, then proxies every call (`ProxyProvider`) |

Both get the same governance: agent tokens, per-tool policy, company scoping,
audit. On the shared endpoint tool names are prefixed by the provider id
(`bizplay_classifier_getAllCorps`, `flow_list_tasks`). Publishing adds the
tools on the next request, with no restart. Unpublishing hides and refuses them,
though they stay loaded until the next restart. Changing the agent token
requirement does need one, because that is fixed when the server starts.

The tool names stored by the portal are the ones FastMCP generates, which differ
from raw operationIds in some specs (FastAPI's
`download_url_api_v1_templates__template_id__download_get` becomes
`download_url_api_v1_templates`). Older registrations that stored raw ids are
renamed on load, policy intact.

```bash
uv run --no-sync python -m bizplay_mcp.registry_gateway --transport http --port 8002
```

Claude Desktop entry `bizplay-registry` runs the same server over stdio with the
identity taken from `BIZPLAY_USER_ID`, `BIZPLAY_ROLE`, and `BIZPLAY_COMPANY`.

### Deploy one API as its own MCP server

Every gateway endpoint serves two shapes:

```
<endpoint>/mcp            every published provider, tools prefixed by provider id
<endpoint>/mcp/<id>       one provider on its own, plain tool names
```

**Deploy as MCP server** on a provider's page switches the second one on (and
publishes the provider). An agent that adds `/mcp/workflow` sees only that
product, with names like `list_templates`, the way a vendor's own MCP app
appears in claude.ai or ChatGPT. Undeploy returns 404 there immediately; the
shared endpoint is unaffected. It is the same process, so nothing new is
started and the same tokens, policy, company scoping and audit apply. The
detail page writes its setup instructions for whichever endpoint you pick.

The portal process serves this gateway too, at its own origin, so one host name
covers the UI, `/mcp` and `/mcp/<id>`. That is the endpoint the register dialog
prefills unless a public address is set on the Security page.

### Per-user OAuth: the gateway as token broker

Backends A and B may each have their own auth server. The AI client never
sees either: it authenticates to the gateway once, and the gateway exchanges
that identity for the right backend token on every call.

```
Claude ──(one login: gateway)──► Gateway ──(user's token from auth server A)──► backend A
                                         ──(user's token from auth server B)──► backend B
```

Register the backend with auth mode **OAuth**. For MCP servers that publish
their auth metadata (RFC 9728 / RFC 8414), **Discover** fills the endpoints in
and registers the gateway as a client (RFC 7591); otherwise enter the
authorization URL, token URL and client id, and whitelist the redirect URL
shown (`<portal origin>/oauth/callback`). Then on the provider page:

1. **Connect account**: pick the Bizplay user id the account belongs to (the
   identity on the agent token), sign in at the backend's auth server in the
   tab that opens (authorization code + PKCE), and land back in the portal.
2. The gateway stores the access and refresh tokens per (user, backend),
   refreshes them before they expire, and attaches the access token to that
   user's calls. A caller who has not linked an account gets a tool error
   saying so; nobody else's token is ever used.
3. **Disconnect** revokes access at once. Tools of an OAuth MCP backend are
   read with a linked user's token (**Refresh tools**), since listing them
   needs one.

`scripts/mock_oauth_backend.py` is a backend with its own auth server to try
this against: `uv run python scripts/mock_oauth_backend.py --port 18095`,
register `http://127.0.0.1:18095` with the spec at `/openapi.json` in OAuth
mode, Discover, publish, Connect account, then call `items_api_listMyItems`
through the gateway and see the signed-in user's items.

### A second demo backend: COOCON

`coocon-mock` is a project-based data-scraping API in the style of a
financial data aggregator: a company owns projects, a project scrapes sources
(bank accounts, corporate cards, Hometax tax invoices, the four insurances)
through jobs, and a finished job yields records. It ships in the image as the
`coocon` compose service and runs locally with
`uv run coocon-mock --port 18096`.

Register it as a REST API with base URL `http://127.0.0.1:18096` (or
`http://coocon:18096` inside compose), spec at `/openapi.json`, auth mode
open, then publish. Reads (`listProjects`, `getJobRecords`, ...) are enabled
at once; `startJob` and `createProject` are writes, so enable them on the
backend page first. Set `COOCON_API_TOKEN` to make the API demand a bearer
token and register it in bearer mode instead. A useful multi-step prompt:
"For company 1078836129, scrape Hometax for the first half of September and
total the VAT."

### Helping the model find its way: instructions, filled-in parameters, tool names

A model facing sixty tools with names like `get_2` and `list_3` guesses, and
asks the user for ids it could have looked up. Three settings fix that, all
kept **per backend** so every gateway that serves the backend inherits them:

- **Usage notes** on the backend page ("How to use this backend"): which tool
  to call first and which next. The gateway sends them as MCP `instructions`
  when a client connects (on `initialize` and on `server/discover`). An
  endpoint's text is its own opening lines from the gateway page, then the
  notes of each backend it serves that this caller is entitled to. The
  gateway page previews the exact text, as any directory user.
- **Parameters filled in from the caller.** Bind a parameter such as `corpNo`
  or `employeeId` to the caller's company, user id or role. It disappears
  from the tools' schemas and the gateway fills it in on every call,
  replacing whatever the model sent. The portal suggests bindings by name
  and never applies one by itself. A caller with no token has no identity,
  so they keep seeing the parameter.
- **Tool names.** Type a readable name over an operation id in the tool
  policy table (`list_2` becomes `listBots`). Clients see and call the new
  name; the old one still works.

### Order and defaults: parameter sources, origins, workflows

Three more per-backend settings, with per-gateway overrides:

- **Company parameters are filled in from the caller**, with no setup: any
  parameter named like `corpNo` (the names in `BIZPLAY_COMPANY_KEYS`) leaves
  the tool schema and the caller's own company goes upstream, whatever the
  model sends. The API still accepts explicit sources per parameter (caller
  identity, fixed, default) and per-gateway overrides for teams that need them.
- **Which tool produces which id.** `askBot.botId` comes from `listBots`,
  field `id`. The gateway writes "get it from listBots" into the tool's
  description and, when a call arrives without the value, tells the model
  what to call first. Or type the value in by hand: it is then sent on every
  call of that tool and hidden from the model. Rows are stated by an admin or **learned from real
  calls**: within a session the gateway remembers the values each tool
  returned, and when a later call uses one of them, that is an observed link
  (counted, never applied until confirmed). It works across backends too.
- **Workflows.** A fixed sequence published as one tool on a gateway:
  `askCompanyBot(question)` runs `listBots`, then `askBot` with
  `{{steps.0.data.0.id}}` and `{{input.question}}`. The gateway runs the
  steps in order through the same entitlement, tool policy and audit as
  direct calls, so the model cannot get the order wrong. `scripts/guide_askdoc.py`
  sets all of this up for the AskDoc chatbot.

### Korean and English

The portal is written in English and translated to Korean in the browser:
`static/i18n.js` holds the dictionary and a few patterns for strings with
names and numbers in them, and applies them to every rendered page, dialog,
toast and confirm. The language button in the sidebar (and on the sign-in
page) stores the choice and reloads. A first visit follows the browser
language. Data stays as it is: backend names, tool descriptions from specs,
and audit details are shown as the server produced them.

### Users: who tokens and linked accounts belong to

The **Users** page is the directory. An agent token is issued *to a person
picked from it* and takes their role, company and access groups from there,
so those are set once per person and cannot disagree between tokens. The same
picker is used when linking an account on an OAuth backend. "Someone not
listed" in either dialog lets an admin type a new id (with role and groups),
which adds the person to the directory at the same time.

A user with a portal password signs in as a **member**: they see only
**My access**, where they issue their own tokens, link their own accounts on
backends that need a personal sign-in, and see the gateways they may use.
Members cannot reach the admin pages, and the API refuses them anything but
their own tokens and connections. Users without a password are managed by an
admin. Removing a user revokes their tokens and drops their linked accounts.

### MCP clients sign in with OAuth (claude.ai, ChatGPT)

claude.ai and ChatGPT connectors cannot send a static bearer header; they
only know "no auth" or OAuth against the server itself. So the gateway is
its own OAuth 2.1 authorization server, following the MCP authorization
spec: a 401 from `/mcp/<gateway>` carries a `resource_metadata` link, the
client reads `/.well-known/oauth-authorization-server`, registers itself at
`/register` (RFC 7591), sends the person to `/authorize` (the portal's own
sign-in page, employee accounts from the user directory), and trades the
code at `/token` with PKCE. The access token it gets is an agent token bound
to that person, so entitlement, tool policy, company scoping, per-user
backend links and the audit log apply unchanged; it lasts an hour and is
renewed with a refresh token that lasts the portal's token lifetime. These
sessions appear on the Agent Tokens page and can be revoked there.

In practice: turn on "Require token" on a gateway, paste its HTTPS URL into
claude.ai as a custom connector, and sign in as `minji@bizplay.co.kr` when
the portal's page opens. Admin accounts are refused there on purpose: an
agent acts as a person with a role and a company.

### Login-endpoint backends (username and password)

Many internal APIs have no OAuth server, just `POST /login` that returns a
token. Register those with auth mode **Login endpoint** and tell the gateway
where to sign in (login URL), what to send (a JSON body template with
`{username}` and `{password}`), where the token is in the answer (a dot path
such as `data.accessToken`), how long it lives (an expiry field or a fixed
lifetime), and how to present it on calls (header and scheme, `Authorization:
Bearer` by default). The gateway signs in itself, caches the token, and signs
in again when it expires or the API answers 401.

Credentials come in two shapes: a **service account** (one username and
password kept with the backend's upstream credential; every caller shares that
identity) or **each user** (people sign in with their own username and password
on **My access**, an admin can do it for them on the backend page, and the API
sees the real person). The COOCON mock demonstrates it: start it with
`COOCON_AUTH=login` and it wants a token from `POST /auth/login`
(users `minji:minji1234`, `junho:junho1234`, `svc:svc1234`); its `whoami` tool
then tells you which account the gateway signed in with.

### Bearer tokens everywhere

Three separate bearer tokens, none of them visible to the AI model:

```
AI agent --(agent token)--> MCP gateway --(service token)--> Bizplay API
                            ^ portal session token protects the portal's own /api/*
```

- **Bizplay API**: every `/api/*` endpoint returns 401 without `Authorization: Bearer <service token>` (`BIZPLAY_API_TOKENS`, default `demo-service-token`). Only `/health` is public.
- **MCP gateway (HTTP)**: every request needs a portal-issued agent token. The token's user and role become the caller's identity, and the role must match Bizplay's user record. Over stdio (Claude Desktop) the identity falls back to `BIZPLAY_USER_ID`.
- **Portal**: every `/api/*` call except login needs the session token from `/api/login`.

Shared state lives in `data/portal_state.json` (written by the portal, read by the gateway).
Delete it to reset to the seed data.

## Project layout

```
openapi/bizplay-existing-api.json   OpenAPI spec of the existing API (used by Option A)
src/legacy_bizplay_api/             MOCK of the existing Bizplay API. Treat as untouchable.
                                    (app.py enforces bearer auth on every /api/* endpoint)
src/bizplay_mcp/
  adapters.py       Only place that knows the existing endpoints (HTTP client, sends the service token)
  auth.py           Gateway bearer verification against portal-issued agent tokens
  policy_store.py   Shared control-plane state: registry, tokens, per-tool access policy
  specs.py          Tool tables: exact FastMCP names for a spec, tool list of an MCP server
  registry_gateway.py  Serves every published provider (OpenAPI or proxied MCP), /mcp and /mcp/<id>
  compliance.py     Korean corporate-card rules (simplified demo values)
  audit.py          JSON Lines audit log of every tool call -> logs/audit.jsonl
  server.py         Option B: curated MCP gateway (auth + policy + audit)
  openapi_gateway.py  Option A: auto-generated MCP gateway
src/portal/         Onboarding portal mockup (Starlette backend + vanilla JS UI)
scripts/smoke_http.py  Real-network end-to-end check
tests/              Automated tests (in-process, no network)
```

## Setup

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
```

## Run

Start the mock existing API (in production, this is Bizplay's real API):

```bash
uv run legacy-bizplay-api --port 18080
```

Then start one of the gateways in another terminal.

```bash
uv run bizplay-mcp --transport http --port 8000
```

```bash
uv run bizplay-mcp-openapi --transport http --port 8001
```

The MCP endpoints are `http://127.0.0.1:8000/mcp` and `http://127.0.0.1:8001/mcp`.
Point the gateway at another API with the `BIZPLAY_API_BASE_URL` environment variable.

Run the end-to-end check against the curated gateway:

```bash
uv run python scripts/smoke_http.py
```

## Connect an AI client

Open the registry, click **How to use it** on an API, and the detail page shows
copy-paste setup written for that API: its own endpoint, tool prefix, server
name, and a sample call using one of its real tools. Summary of what each
client needs:

| Client | How it connects | Works today |
|---|---|---|
| Claude Desktop | Launches the gateway locally over stdio, identity from env vars | Yes |
| Claude Code | HTTP with an `Authorization: Bearer` header | Yes |
| Any MCP client, scripts, curl | Same HTTP endpoint and header | Yes |
| ChatGPT, Claude.ai | Remote connector, needs public HTTPS and OAuth | Not yet |
| Copilot Studio, Agentforce | Remote MCP server, needs public HTTPS and OAuth | Not yet |

### An HTTPS address for claude.ai and ChatGPT

Those clients refuse plain HTTP, so the gateway needs TLS. Two ways:

**A throwaway URL, no DNS or certificate work.** A Cloudflare quick tunnel:

```bash
docker compose --profile tunnel up -d tunnel && docker compose logs tunnel | grep trycloudflare.com
```

The printed `https://...trycloudflare.com` plus `/mcp` is the connector URL. It
changes every restart and is open to anyone who has it.

**A stable URL.** Point a subdomain at the server and terminate TLS with nginx.
The portal serves the gateway on its own origin, so one `location /` covers the
UI, `/mcp` and every `/mcp/<id>`:

```bash
sudo certbot --nginx -d mcp-portal.example.com
```

```nginx
location / {
    proxy_pass http://127.0.0.1:9015;      # the portal's published port
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Connection '';
    proxy_buffering off;      # MCP streams responses; buffering makes it hang
    proxy_read_timeout 3600s;
}
```

`https://mcp-portal.example.com/mcp` is then the connector URL, and a deployed
provider is at `https://mcp-portal.example.com/mcp/<id>`. Put the HTTPS address
in **Public MCP endpoint** on the Security page so new registrations inherit
it, or set it per API with **Edit connection**, then add it in claude.ai under
Settings, Connectors, Add custom connector.

### The one-line shortcut

On an API's detail page, **Connect command** issues a token and prints commands
with that token already in them: a `claude mcp add` line, a Claude Desktop
config block using `mcp-remote`, and a curl call to check it. Copy, paste, done.

### Connecting without a token

The gateways require a portal-issued agent token over HTTP. For a demo you can
turn that off on the Security page, or with `BIZPLAY_REQUIRE_AGENT_TOKEN=false`,
which takes precedence. The gateways read the setting at startup, so restart
them afterwards. Then this is the whole setup:

```bash
claude mcp add --transport http bizplay-classifier http://HOST:9011/mcp
```

With the requirement off the gateway cannot tell callers apart: identity falls
back to `BIZPLAY_USER_ID`, `BIZPLAY_ROLE` and `BIZPLAY_COMPANY`, so every caller
is the same user and company scoping applies to that one identity. Demos only.
The Security checklist marks it red while it is off.

Claude Code, after issuing a token on the Agent Tokens page:

```bash
claude mcp add --transport http bizplay-registry http://127.0.0.1:8002/mcp --header "Authorization: Bearer <YOUR_AGENT_TOKEN>"
```

The cloud products cannot reach `127.0.0.1` and have no field for a static
bearer token, so they need the gateway exposed over HTTPS (a tunnel such as
cloudflared or ngrok for a demo) and an OAuth provider configured on the
gateway. FastMCP ships the providers, so that is configuration rather than a
rewrite.

## Use it from Claude Desktop

Add this entry under `mcpServers` in `%APPDATA%\Claude\claude_desktop_config.json`,
then fully quit Claude Desktop from the system tray and reopen it:

```json
"bizplay": {
  "command": "C:\\Users\\user\\.local\\bin\\uv.exe",
  "args": [
    "--directory",
    "C:\\Users\\user\\OneDrive\\Documents\\02. Master Degree\\03. Lab\\01. Project\\01. WebCash\\04. BizPlay\\07. Experiment\\01. Bizplay MCP Server",
    "run",
    "bizplay-mcp"
  ],
  "env": {
    "BIZPLAY_API_BASE_URL": "embedded",
    "BIZPLAY_USER_ID": "emp001",
    "FASTMCP_SHOW_SERVER_BANNER": "false"
  }
}
```

- `"embedded"` runs the mock existing API inside the MCP server process, so no
  second terminal is needed. Demo data resets every time Claude Desktop restarts.
  To use a separately running API instead, set it to `http://127.0.0.1:18080`
  and start `uv run legacy-bizplay-api --port 18080` first.
- Use the full path to `uv.exe`, because Claude Desktop may not see your terminal's PATH.
- Change `BIZPLAY_USER_ID` to `mgr001` to act as the manager.
- If the server does not appear, check `%LOCALAPPDATA%\Claude\Logs\mcp-server-bizplay.log`.
  If that file does not exist, Claude Desktop has not restarted since the config changed.

Try asking: "Help me close my September 2026 card expenses."

## What the curated gateway exposes

| Tool | Who | What it does |
|---|---|---|
| `get_card_balance` | anyone | Limit, spent, and remaining per card for a month |
| `list_card_transactions` | anyone | The caller's own card transactions |
| `find_missing_receipts` | anyone | Transactions missing receipt images or attendee lists |
| `validate_tax_compliance` | anyone | Korean rule check plus deductible input VAT estimate |
| `draft_expense_report` | anyone | Creates a draft report with a compliance check |
| `submit_for_approval` | owner | Submits to the manager, refused while blockers remain |
| `list_pending_approvals` | manager | Reports waiting for the caller |
| `decide_approval` | manager | Approve or reject, comment required to reject |

Resources: `bizplay://me/profile`, `bizplay://budgets/{department}/{month}`,
`bizplay://policies/korean-compliance`. Prompt: `month_end_closing`.

Demo users: `emp001` and `emp002` are employees, `mgr001` is their manager.
Seed data is for September 2026.

## Docker

One image, four services. Requires Docker Desktop running.

```bash
docker compose up --build
```

| Service | Default published port | Container port | Notes |
|---|---|---|---|
| gateway | 9010 | 8000 | Curated tools, calls `legacy-api` by service name |
| registry-gateway | 9011 | 8002 | Serves every published API; new ones appear without a restart |
| portal | 9012 | 18090 | UI and API, plus the same registry gateway at `/mcp` and `/mcp/<id>` on its own origin |
| legacy-api | 9013 | 18080 | Mock of the existing Bizplay API; drop the mapping in production |
| coocon | 9016 | 18096 | COOCON mock, a second demo backend (project-based scraping); register it as `http://coocon:18096` |

### Changing ports

Copy `.env.example` to `.env` and edit it. Compose reads it automatically, so
`docker-compose.yml` needs no changes.

```bash
PUBLIC_HOST=mcp.example.com
GATEWAY_PORT=9010
REGISTRY_PORT=9011
PORTAL_PORT=9012
LEGACY_API_PORT=9013
```

Containers always listen on their fixed internal ports. Only the published port
changes, so any range works as long as the values differ.

`PUBLIC_HOST` and the two gateway ports also set `BIZPLAY_PUBLIC_GATEWAY_URL`
and `BIZPLAY_PUBLIC_REGISTRY_URL`, which decide the endpoint the portal shows on
each API detail page and stores with newly registered APIs. Without them agents
would be handed a URL that only works inside the container.

If neither variable is set, the portal uses the host the browser opened it on,
with `BIZPLAY_GATEWAY_PORT` and `BIZPLAY_REGISTRY_PORT` (defaults 8000 and 8002).

Existing entries keep the URL they were registered with. After changing the
host or ports, open the API and use **Edit connection**, or reset the demo state
with `docker compose down -v`.

### Registering an API: the base URL

Give the **host only**, for example `https://api.example.com`. The paths come
from the spec. A base URL ending in a path that the spec's paths also start
with produces `/api/v1/api/v1/...` and a 404 on every call. The portal detects
that case and trims the duplicate, both on registration and on edit.

Portal state and the audit log live in named volumes (`state`, `logs`) so they
survive restarts. Set `BIZPLAY_API_TOKENS` in the environment to change the demo
service token. The registry gateway reaches external APIs such as
bizplay-api.aiconvergencelab.com directly, so the container needs outbound
internet access.

## Tests

```bash
uv run pytest
```

## Not production-ready yet

- **Tokens are static lookups, not OAuth.** Agent tokens are random strings
  stored in a JSON file and matched by value. Production needs OAuth 2.1 with
  signed JWTs from Bizplay's identity provider, verified by key (FastMCP's
  `JWTVerifier` / `RemoteAuthProvider`), and hashed storage for any API keys.
- **Portal accounts are demo accounts** with plain-text passwords and in-file sessions.
- **Linked-account tokens live in the JSON state file**, next to the other
  secrets. Production keeps per-user OAuth tokens in a vault and lets end
  users link accounts from their own login, not only from the admin portal.
- **Over stdio there is no bearer check.** Claude Desktop launches the server as
  a local process, so the identity comes from `BIZPLAY_USER_ID`.
- **Compliance rules are simplified demo values.** They are not tax advice and
  need review by a Korean tax professional.
- **The existing API is a mock.** Replace `openapi/bizplay-existing-api.json`
  with the real Swagger export and point `BIZPLAY_API_BASE_URL` at the real API.
- **Option A has no guardrails.** Do not expose it to customers as is.
