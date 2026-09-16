# Demo script: one chat, four systems, one gateway

Gateway: `https://mcp-portal.aiconvergencelab.com/mcp/wc-group` (WC_Group)
Backends behind it: **Flow** (project collaboration, OAuth per user), **COOCON**
(financial data scraping, username/password per user), **TravelExpense** and
**BZP_Compliance** (open REST APIs). 68 tools, one connector, one sign-in.

The point of the demo: an employee asks ordinary questions in claude.ai and
the assistant pulls from all four systems as that employee, with the
company's rules applied, without the employee pasting a single token.

## Before the demo (5 minutes)

1. Users page: Kim Minji (emp001) exists, group `finance`, company `1078836129`.
2. WC_Group gateway page: "Require an agent token" = Required, saved.
3. Minji's links: Flow connected (Connected accounts on the Flow page),
   COOCON connected (Sign-in card on the COOCON page, service account or
   Minji's own login).
4. In claude.ai: Settings, Connectors, Add custom connector, paste the
   gateway URL, Authentication "Sign in now", OAuth client "Register
   automatically" or "Use Claude's published identity". The portal's sign-in
   page opens: `minji@bizplay.co.kr / minji1234`.
5. Open a new chat with the connector enabled. Keep the portal's Audit Log
   open in a second window.

## The chat

Each prompt is one turn in the same chat. The text in brackets is what to say
out loud, and what to point at.

### 1. Who am I here?

> Which account am I signed in as on each system behind this gateway? Check Flow, COOCON and TravelExpense.

[Three different backends, three different identities, one sign-in. Flow
answers with the linked Flow user, COOCON with the username the gateway
signed in with, TravelExpense with the BizPlay employee. Nothing was typed.]

### 2. What is going on in my project?

> Summarize what happened in the Flow project "비즈플레이 & 충북대 AI 협업 관련" since August 1: how many tasks, what is waiting, what is in progress, and the three most recent items with links.

[One tool call collects tasks, posts and comments; the assistant writes the
summary. This is Flow's own MCP server, proxied through the gateway with
Minji's token, not a shared key.]

### 3. Money side of the same month

> For company 1078836129, what COOCON scraping projects exist, and for "DemoCorp01 monthly close" give me the totals per source and the three largest bank withdrawals with counterparties.

[COOCON is a REST API with a login endpoint. Nobody wrote an MCP server for
it: the gateway generated the tools from its OpenAPI spec and signs in
itself. Point at the audit log: every call shows emp001.]

### 4. Cross-check travel spending

> List my approved business trip plans and the personal-card receipts from August 1 to today. Match each receipt to a trip where you can, and flag receipts with no matching trip.

[TravelExpense answers two different questions and the assistant joins
them. Both calls carry corpNo 1078836129 because that is Minji's company.]

### 5. The guardrail

> Start a new COOCON scraping job for project prj-1001, source hometax, from September 1 to September 15.

[Refused: "tool startJob is disabled by the provider admin". Writes start
off. Now, in the portal, open COOCON, enable `startJob` with "Confirm before
call", and repeat the prompt. It runs on the next request, no restart, and
the audit log shows the denial and then the success.]

### 6. Company boundary

> Show the COOCON projects for company 2200000000.

[Refused before it reaches COOCON: "corpNo=2200000000 is not the caller's
company". The gateway scopes every call to the token's company, whatever
the model was asked.]

### 7. Put it together

> Write a short Monday briefing for my manager: project status from Flow, this month's bank and card totals from COOCON, my approved trips and any unmatched receipts from TravelExpense, and whether any compliance audits exist for our company. Keep it to ten lines.

[Four systems, one paragraph. Compliance returns none for this company,
and the assistant says so honestly. This is the answer to "why a gateway":
one connector per team, one policy, one audit trail, and each backend still
sees the real person.]

### 8. Close with the portal

- Agent Tokens: the claude.ai session is a token bound to emp001, marked
  via OAuth, revocable here. Revoke it and the next prompt fails until the
  connector signs in again.
- Security, Sign-in log: every step claude.ai took to get in.
- Users: change Minji's group and the gateway's "Who can use this gateway"
  to a group she is not in. The next prompt is refused with the reason.

## Korean prompts (same order)

1. 이 게이트웨이 뒤의 각 시스템(Flow, COOCON, TravelExpense)에서 나는 어떤 계정으로 로그인되어 있어?
2. Flow 프로젝트 "비즈플레이 & 충북대 AI 협업 관련"에서 8월 1일 이후 무슨 일이 있었는지 요약해줘. 업무 수, 대기/진행 현황, 최근 항목 3개를 링크와 함께.
3. 사업자번호 1078836129의 COOCON 스크래핑 프로젝트 목록을 보여주고, "DemoCorp01 monthly close"의 소스별 합계와 가장 큰 은행 출금 3건을 거래처와 함께 알려줘.
4. 승인된 내 출장계획서와 8월 1일부터 오늘까지의 개인카드 영수증을 나열하고, 영수증을 출장과 매칭해줘. 매칭되지 않는 영수증은 표시해줘.
5. COOCON 프로젝트 prj-1001에서 홈택스 소스로 9월 1일부터 9월 15일까지 스크래핑 작업을 시작해줘.
6. 사업자번호 2200000000의 COOCON 프로젝트를 보여줘.
7. 팀장에게 보낼 월요일 브리핑을 열 줄로 써줘: Flow 프로젝트 현황, 이번 달 COOCON 은행·카드 합계, 내 승인된 출장과 매칭 안 된 영수증, 우리 회사의 컴플라이언스 감사 존재 여부.

## What to say if asked

- "Did you write an MCP server for COOCON?" No. The gateway generated it
  from the OpenAPI spec; the login endpoint is marked `x-mcp: exclude` so it
  never becomes a tool.
- "Where are the passwords?" In the portal's state, per user, used only for
  that user's calls. Production puts them in a vault; the flow is the same.
- "What if Flow's token expires mid-demo?" It is refreshed automatically;
  the last refresh time is on the Flow page.
- "Can another team get a different set?" Yes: a second named gateway with
  its own backends, its own entitlement, and its own URL, in a minute, no
  restart.
