# Demo script: one chat, four systems, one gateway

Gateway: `https://mcp-portal.aiconvergencelab.com/mcp/wc-group` (WC_Group)

| Backend | What it is | How the gateway gets in | Tools |
|---|---|---|---|
| **FLOW** | Project collaboration (flow.team), an existing MCP server | OAuth, each user's own Flow account | 20 |
| **COOCON** | Financial data scraping: bank, card, Hometax, insurance | Username and password, signed in by the gateway | 8 |
| **TravelExpense** | Business trips, settlements, receipts | Open API, company scoped by the gateway | 38 |
| **BZP_Compliance** | Rule engine: split payment, nighttime, limits, holidays, audits | Open API | 6 |

The point: an employee asks ordinary questions in one claude.ai chat and
the assistant works across all four systems as that employee, with the
company's rules applied, without pasting a single token. Every prompt below
was run against the live gateway and returns real content.

## Before the demo (5 minutes)

1. Users page: Kim Minji (emp001) exists, group `finance`, company `1078836129`.
2. WC_Group gateway page: "Require an agent token" = Required, saved.
3. Minji's links: FLOW connected (Connected accounts on the FLOW page);
   COOCON connected (Sign-in card on the COOCON page).
4. COOCON page, tool policy: `startJob` **off** (it is the guardrail in turn 6).
   BZP_Compliance: `checkR01`, `checkR02`, `checkR03`, `checkR09` on (they are).
5. claude.ai: Settings, Connectors, Add custom connector, paste the gateway
   URL, Authentication "Sign in now", OAuth client "Use Claude's published
   identity" or "Register automatically". The portal's sign-in page opens:
   `minji@bizplay.co.kr / minji1234`.
6. New chat with the connector enabled. Keep the portal's Audit Log open in
   a second window.

## The chat, nine turns

Text in brackets is what to say, and what to point at.

### 1. Identity, all four systems

> Which account am I signed in as on each system behind this gateway? Check FLOW, COOCON and TravelExpense, and tell me which company all my calls are limited to.

[Three backends, three identities, one sign-in: the Flow user, the COOCON
username, the BizPlay employee 김충북. The company comes from the token. Nothing
was typed.]

### 2. FLOW: what is going on in my project

> Summarize what happened in the FLOW project "비즈플레이 & 충북대 AI 협업 관련" since August 1: how many tasks, how many waiting versus in progress, and the three most recent items with links.

[One call collects tasks, posts and comments; the assistant writes the
summary. Flow's own MCP server, proxied with Minji's Flow token, refreshed
by the gateway when it expires.]

### 3. COOCON: the money side of the same month

> For company 1078836129, list the COOCON scraping projects. For "DemoCorp01 monthly close" give me the totals per source, and the three largest bank withdrawals with their counterparties.

[Nobody wrote an MCP server for COOCON. The gateway generated the tools from
its OpenAPI spec and does the login itself. The audit log shows emp001 on
every call.]

### 4. TravelExpense: trips against receipts

> List my approved business trip plans and my personal-card receipts from August 1 to today. Match each receipt to a trip where you can, and flag receipts with no matching trip.

[Two TravelExpense calls, joined by the assistant. Both carry corpNo
1078836129 because that is Minji's company.]

### 5. BZP_Compliance: run the rules on real card data

> Take the card records of COOCON job job-0002. For each record, run the compliance checks: split payment on the amount, spending limit with category MEAL, nighttime on the date at 23:00, and the holiday check on the date. Give me a table with one row per record, one column per rule, and mark the failures.

[This is the cross-system chain: records come from COOCON, verdicts from
the rule engine, and the assistant builds the table. Point out that the
compliance tools are POST calls that the admin enabled on purpose, with
clear descriptions written in the portal so the model knows which to pick.]

### 6. The guardrail

> Start a new COOCON scraping job for project prj-1001, source hometax, from September 1 to September 15.

[Refused: "tool startJob is disabled by the provider admin". Now open COOCON
in the portal, enable `startJob` with "Confirm before call", and repeat the
prompt. It runs on the next request, no restart. The audit log shows the
refusal, then the success.]

### 7. The company boundary

> Show the COOCON projects for company 2200000000.

[Refused before it reaches COOCON: "corpNo=2200000000 is not the caller's
company". The gateway scopes every call to the token's company, whatever
the model was asked.]

### 8. The briefing

> Write a Monday briefing for my manager in ten lines: project status from FLOW, this month's bank and card totals from COOCON, my approved trips and any unmatched receipts from TravelExpense, and how many card records failed a compliance rule.

[Four systems, one paragraph, and the reason for a gateway: one connector
per team, one policy, one audit trail, each backend still seeing the real
person.]

### 9. The chart

> Build an interactive dashboard from what we found in this chat: a bar chart of COOCON totals per source for DemoCorp01 monthly close, a bar chart of the FLOW project's tasks by status, a chart of my receipts by expense category, and a heatmap of the compliance table with failures in red. Add a headline number for total card spend and for the number of rule failures.

[claude.ai renders it as an artifact. Every number in it came through the
gateway in this session. If the chat is long, add: "use the numbers already
in this conversation, do not call the tools again".]

### Close with the portal

- Agent Tokens: the claude.ai session is a token bound to emp001, marked
  via OAuth, revocable here. Revoke it and the next prompt fails until the
  connector signs in again.
- Security, Sign-in log: every step claude.ai took to get in.
- Users: move Minji out of `finance` and set the gateway to "Only these
  access groups: finance". The next prompt is refused with the reason.
- MCP Gateways: create a second gateway with two of the four backends. It
  is live at its own URL in a minute, no restart.

## Korean prompts, same order

1. 이 게이트웨이 뒤의 각 시스템(FLOW, COOCON, TravelExpense)에서 나는 어떤 계정으로 로그인되어 있고, 내 호출은 어느 회사로 제한되어 있어?
2. FLOW 프로젝트 "비즈플레이 & 충북대 AI 협업 관련"에서 8월 1일 이후 무슨 일이 있었는지 요약해줘. 업무 수, 대기와 진행 건수, 최근 항목 3개를 링크와 함께.
3. 사업자번호 1078836129의 COOCON 스크래핑 프로젝트를 나열하고, "DemoCorp01 monthly close"의 소스별 합계와 가장 큰 은행 출금 3건을 거래처와 함께 알려줘.
4. 승인된 내 출장계획서와 8월 1일부터 오늘까지의 개인카드 영수증을 나열하고, 영수증을 출장에 매칭해줘. 매칭되지 않는 영수증은 표시해줘.
5. COOCON 작업 job-0002의 카드 기록을 가져와서 기록마다 컴플라이언스 검사를 실행해줘: 금액으로 분할결제 검사, 카테고리 MEAL로 한도 검사, 해당 날짜 23시로 심야 검사, 해당 날짜로 휴일 검사. 기록별 한 행, 규칙별 한 열인 표로 만들고 실패를 표시해줘.
6. COOCON 프로젝트 prj-1001에서 홈택스 소스로 9월 1일부터 9월 15일까지 스크래핑 작업을 시작해줘.
7. 사업자번호 2200000000의 COOCON 프로젝트를 보여줘.
8. 팀장에게 보낼 월요일 브리핑을 열 줄로 써줘: FLOW 프로젝트 현황, 이번 달 COOCON 은행·카드 합계, 승인된 출장과 매칭 안 된 영수증, 컴플라이언스 규칙에 걸린 카드 기록 수.
9. 이 대화에서 찾은 내용으로 인터랙티브 대시보드를 만들어줘: DemoCorp01 monthly close의 소스별 COOCON 합계 막대 차트, FLOW 프로젝트 업무 상태별 막대 차트, 지출 카테고리별 영수증 차트, 컴플라이언스 표의 히트맵(실패는 빨간색). 총 카드 지출과 규칙 실패 건수를 헤드라인 숫자로 넣어줘.

## What to say if asked

- "Did you write an MCP server for COOCON or Compliance?" No. The gateway
  generated both from their OpenAPI specs. COOCON's login endpoint is marked
  `x-mcp: exclude` so it never becomes a tool.
- "Why does the model pick the right tool out of 72?" Each tool carries a
  description the admin can rewrite in the portal; the compliance checks
  say exactly what input they want. Named gateways also keep the set small.
- "Where are the passwords?" In the portal's state, per user, used only
  for that user's calls. Production puts them in a vault; the flow is the same.
- "What if Flow's token expires mid-demo?" The gateway refreshes it; the
  last refresh time is on the FLOW page.
- "Can another team get a different set?" Yes: a second named gateway with
  its own backends, entitlement and URL, in a minute, no restart.
