# One trip, three systems, one chat

A demo story for claude.ai on the Bizplay MCP gateway. Three backends sit
behind one gateway URL: **FLOW** (project collaboration, an MCP server the
gateway proxies with each user's own Flow account), **BZP_Chatbot** (AskDoc,
answers from company documents) and **TravelExpense** (trip plans,
settlements, receipts, approval). The employee never sees three systems.
She sees one assistant that knows who she is.

The story follows one business trip from the morning it is proposed to the
afternoon the expense report lands on the approver's desk.

## Cast

| Who | Where | Role in the story |
|---|---|---|
| Kim Minji, finance team | Portal user `emp001`, FLOW account linked | The employee. She talks to claude.ai; every call runs as her. |
| 김도하 | BizPlay staff roster | The approver. Picked by name from the approval line. |
| The gateway | `https://mcp-portal.aiconvergencelab.com/mcp/<gateway>` | Signs her in once, fills in her company, keeps the audit log. |

## Before the demo (10 minutes)

1. **One gateway with all three backends.** Today FLOW is on WC_Group and
   the chatbot is on AskDocs, but no gateway has all three. Either add
   BZP_Chatbot to WC_Group (Edit backends) or create a gateway `demo` with
   `flow-6703`, `bzp-chatbot`, `travelexpense`. Set "Require an agent
   token" to Required.
2. **Gateway instructions** (the Instructions box on that gateway):
   > You help an employee with company knowledge, their work in FLOW and their business trips. Use the chatbot tools for policy and how-to questions, FLOW for projects, tasks and schedules, and TravelExpense for trip plans and settlements. Work as the signed-in user; never ask for ids you can look up.
3. **TravelExpense token.** On the gateway page, "Values for this gateway":
   backend TravelExpense, tool "every tool that takes it", parameter
   `X-Bizplay-Token`, kind fixed, paste the BizPlay token. (Needs the build
   from 23 Sep or later; before that, one row per tool.)
4. **Minji's FLOW link** is in place (FLOW page, Connected accounts, 1 user).
5. **Usage notes** are set on BZP_Chatbot and TravelExpense (both show
   "Usage notes set"). FLOW has none and needs none: its tool names say
   what they do.
6. **claude.ai:** Settings, Connectors, Add custom connector, the gateway
   URL, sign in as `minji@bizplay.co.kr / minji1234` on the portal's page.
   New chat with the connector on. Keep the portal's Audit Log in a second
   window.

One honesty note for the presenter: TravelExpense answers as the BizPlay
account the token belongs to. If that account is not named Kim Minji, the
assistant will say so when asked who it is. Either use that person's name
in the story, or say up front that the demo company maps portal users to
BizPlay accounts.

## The story

Say the line in bold. The bracketed text is what to point at while the
assistant works. Korean versions follow each prompt.

### Scene 1. Tuesday, 9:05. What is on my plate?

> **What do I need to handle today, and is there anything about a Jeju trip in my projects?**
>
> 오늘 내가 처리해야 할 일이 뭐야? 그리고 내 프로젝트에 제주 출장 관련된 게 있어?

[The assistant calls `flow_get_my_worklist`, then `flow_search` or
`flow_find_projects` for "제주". It answers with her overdue and due-soon
items and finds the project post asking her to visit the Jeju partner on
14 to 15 October.]

Point at: the Audit Log. Two calls, user `emp001`, backend FLOW. The Flow
token used was hers, refreshed by the gateway; nobody pasted it anywhere.

### Scene 2. 9:10. What does the policy say?

> **Before I book, what is our travel policy for a domestic trip: flight class, daily allowance and hotel limit? And do I need approval before booking?**
>
> 예약하기 전에 국내 출장 규정 알려줘: 항공 좌석 등급, 일비, 숙박 한도. 그리고 예약 전에 승인이 필요해?

[The assistant calls `listBots` (corpNo filled in by the gateway, never
asked), picks the policy bot by its description, then `askBot`. It quotes
the domestic rules: economy air, the daily allowance amount, the lodging
limit, and that a trip plan must be filed and approved first.]

Point at: the BZP_Chatbot page, "Which tool produces which id". `askBot`
needs a botId that `listBots` returns in field `id`. That one line is why
the assistant did not ask "which bot?".

### Scene 3. 9:15. File the trip plan

> **File a domestic trip plan for me: Jeju, 14 to 15 October, purpose "partner visit and business meeting", flying from Gimpo. Send it to 김도하 for approval.**
>
> 국내 출장 계획서 올려줘: 제주, 10월 14일부터 15일, 목적은 "협력사 방문 및 업무 협의", 김포에서 비행기. 결재는 김도하에게.

[The assistant starts `planChat`. The agent answers with purpose chips;
the assistant picks the matching purpose itself, answers the destination
and route questions, fills the remaining fields from her sentence, and at
the approval-line question calls `corporationUsers` and picks 김도하 by
name. `createPlan` files it. The reply carries the document number.]

Point at: the TravelExpense usage notes. "Every reply may carry
pendingChoices. Answer them yourself." Before those notes the assistant
stopped at the first chip and asked the user to click it in the web app.

### Scene 4. Two weeks later, 16 October, 14:00. Back from Jeju

> **I am back from the Jeju trip. Settle it: flight 104,500 won round trip Gimpo to Jeju on the 14th, express bus 25,000 won one way, hotel 180,000 won for one night. No receipt images. Submit it to 김도하.**
>
> 제주 출장 다녀왔어. 정산해줘: 14일 김포-제주 왕복 항공 104,500원, 고속버스 편도 25,000원, 숙박 1박 180,000원. 영수증 이미지는 없어. 김도하에게 상신해줘.

[This is the long one, and the one to let run. `settlementChat` finds the
approved plan and imports it. For each expense the assistant sends
`manual-expense`, describes the expense in one plain sentence, confirms
the preview, says there is no image, and moves to the next. At
`receipts-done` the agent reports a total of 309,500 won and, because the
bus fare is over the policy amount, asks whether to split the excess; the
assistant asks Minji only that question. Then SUBMIT, the approver picked
by name, and `CREATE_SETTLEMENT` with the document number.]

Point at: the draft totals in the assistant's answer, then the Audit Log:
a dozen calls in a row, all `emp001`, all TravelExpense. One sentence from
her, one conversation the assistant held with the settlement agent.

### Scene 5. 14:20. Close the loop in FLOW

> **Read the Jeju project and tell the team what happened: what I did on the trip, what is still open, and that the expense report is filed. Draft it as a project post I can paste.**
>
> 제주 프로젝트를 읽고 팀에 공유할 내용을 정리해줘: 출장에서 한 일, 아직 남은 일, 정산서 제출 완료. 프로젝트 게시글로 붙여넣을 수 있게 초안 써줘.

[`flow_collect_project_chain` gathers the project's tasks, posts and
comments; the assistant drafts the update. It does not post it: the FLOW
tools on this gateway are read-only, so it hands her the text.]

Point at: the FLOW page, Tool policy. 20 of 39 tools enabled, every one a
read. The company decided that an assistant reads FLOW but does not write
to it, and the gateway enforces that for every client, not just claude.ai.

### Scene 6. The one that is refused

Switch to a second chat signed in as Lee Junho (`junho@bizplay.co.kr /
junho1234`, HR).

> **Show me Kim Minji's Jeju settlement and its amounts.**
>
> 김민지의 제주 정산서와 금액 보여줘.

[If TravelExpense entitlement is "finance group only", the assistant has
no TravelExpense tools at all and says so. If it is "everyone with a
token", the settlement list is his own company's documents, not Minji's
private view: the gateway filled in his company and his BizPlay identity.
Either way he cannot act as her.]

Point at: the Audit Log or Sign-in log. Same gateway, different person,
different answer. Nothing was configured in claude.ai to make that happen.

## The three sentences to end on

- One URL, three systems, one sign-in. Every call ran as the person in the
  chat, with her Flow account, her company number and her audit trail.
- The assistant knew what to call first because the company wrote it down
  once, on the backend's page, and every gateway serving that backend
  inherits it.
- What the assistant may not do is decided in the portal, by tool and by
  person, and applies to any AI client that connects.

## A closing visual (optional)

After scene 4, in the same chat:

> **Draw one chart of this trip: the three expenses as bars with the policy limit marked, and the settlement total in the title.**
>
> 이 출장 비용을 차트 하나로 그려줘: 세 항목을 막대로, 규정 한도를 선으로 표시하고 제목에 정산 총액을 넣어서.

claude.ai renders it from the numbers already in the conversation; no tool
call is needed.
