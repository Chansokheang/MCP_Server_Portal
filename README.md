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
- **Over stdio there is no bearer check.** Claude Desktop launches the server as
  a local process, so the identity comes from `BIZPLAY_USER_ID`.
- **Compliance rules are simplified demo values.** They are not tax advice and
  need review by a Korean tax professional.
- **The existing API is a mock.** Replace `openapi/bizplay-existing-api.json`
  with the real Swagger export and point `BIZPLAY_API_BASE_URL` at the real API.
- **Option A has no guardrails.** Do not expose it to customers as is.
