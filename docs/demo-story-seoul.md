# A trip to Seoul: one chat across FLOW, the policy bot and TravelExpense

A demo story for claude.ai on the Bizplay MCP gateway, built on what is
actually in FLOW and in the chatbot (checked and prepared on 23 Sep 2026).
The TravelExpense scenes use the demo BizPlay company, where any trip can
be filed, so they follow the story freely.

The setting is real: the FLOW project **비즈플레이 & 충북대 AI 협업 관련**
(Bizplay and Chungbuk National University), where the Bizplay team and the
lab are building the very travel agents this demo runs on. The presenter
is the lab researcher who travels to Bizplay's Seoul office on
**Wednesday 30 September 2026** to show this gateway. The trip in the
story is that trip: the plan is filed for the 30th, and the settlement is
filed the same day, on stage. The assistant is claude.ai, connected to one
gateway URL.

## What is really there

**FLOW** (the presenter's own Flow account, linked once on the FLOW page)

| What | Detail |
|---|---|
| Profile | Sokheang Chan, IT Department |
| Project | 비즈플레이 & 충북대 AI 협업 관련, id 2859855: 111 posts, 60 tasks, 164 comments |
| Task board | 피드백 28, 대기 20, 진행 8, 완료 3, 보류 1 |
| The presenter's open tasks | `DELETE /api/v1/rules/{ruleId} 다건용도 추가요청` (진행), `POST /api/v1/categories/update/batch 추가 요청` (피드백), `bot-config` (피드백), `GET /api/v1/rules/{corpNo} 페이징 처리 추가` (피드백) |
| The mention | 김민수, post **출장 정산서 작성 API 및 관련 자료** (5 Aug), 9 comments. The presenter's own comment on 3 Sep: the AI model and API moved to the Bizplay GPU server. 김민수's reply: the policy-amount setting (규정금액) is missing when evidence is added to a settlement, with a document attached. |
| Latest alarms (22 Sep) | 박지훈 moved two tasks from 진행 to 피드백; 김민수 reassigned a task from 김민수 to 박지훈; a comment to 심우진 이사 about the SK하이닉스 settlement. |
| The product posts | 심우진 (3 Aug): ⭐비즈플레이 AI상품 6종 출시, 출장품의 Agent, 출장예약 Agent, 출장정산 Agent, [BZP-TA6] 출장 Agent - 하이닉스. |
| Calendar | Empty for Sep to Nov. Do not ask about events. |

**Chatbot**: a bot made for this story, in the demo company

| What | Detail |
|---|---|
| Bot | 국내출장 규정 안내 봇, id `430ba21f-866d-411d-9ef2-71f7cc971549`, company `1078836129` (the demo corp, so `listBots` finds it) |
| Documents | Two versions of the same rulebook, both uploaded and embedded: Korean, `docs/demo-rulebook-democorp01.md`, and English, `docs/demo-rulebook-democorp01-en.md`. The bot answers in the language of the question and cites the matching file. |
| Starter questions | 출장 가기 전에 무엇을 먼저 해야 하나요? · 서울 1박 출장의 일비와 숙박비 한도는 얼마인가요? · 영수증이 없으면 어떻게 하나요? |
| What it answers, verified through the gateway | 일비 40,000원/day (임원 60,000). Lodging 80,000원 per night fixed, excess is the employee's own; Seoul in Oct to Nov up to 100,000원 with a reason on the plan. KTX 일반실 only, 특실 for executives; 오송 to 서울 standard fare 18,500원. No receipt: 기타증빙 with a reason, 80% of the fixed amount. Trip plan first, approver for 테스트1팀 is 인사1팀 팀장 김도하 상무. It cites the article numbers. |

The older ACME-001 bot (`44dc5873…`) is untouched; it is simply not this
company's bot, so the assistant will not see it.

**TravelExpense** (demo BizPlay company, flexible)

| What | Detail |
|---|---|
| Identity behind the token | 김충북, DemoCorp01, 테스트1팀, employee C0001 |
| Approver | 김도하, 상무, 인사1팀 팀장 |
| Trip purpose | 국내출장 exists |

## Before the demo (15 minutes)

1. **One gateway with all three backends.** Create `seoul` (or add
   BZP_Chatbot to WC_Group) with `flow-6703`, `bzp-chatbot`,
   `travelexpense`. Require an agent token.
2. **Instructions for the model** on that gateway:
   > You help a researcher who works with Bizplay on the travel-agent project. FLOW holds the project, tasks and discussions. The chatbot answers travel-policy questions from the company rulebook. TravelExpense files trip plans and settlements. Work as the signed-in user; never ask for ids you can look up.
3. **Values for this gateway** (needs the 23 Sep build): TravelExpense,
   every tool that takes it, `X-Bizplay-Token`, fixed, the BizPlay token.
   Nothing is needed for the chatbot: `listBots` returns the demo
   company's bot, exactly as the usage notes describe.
4. **The presenter's portal user.** The FLOW link belongs to `emp001`
   (Kim Minji, company 1078836129). Sign in as that user, or rename the
   user to the presenter's name for the day on the Users page. In FLOW the
   assistant will say "Sokheang Chan" and in BizPlay "김충북" whatever the
   portal name is; say so up front, it is a demo company.
5. **Usage notes** are already set on BZP_Chatbot and TravelExpense. FLOW
   needs none.
6. **claude.ai:** Settings, Connectors, Add custom connector, the gateway
   URL, sign in on the portal's page. New chat. Keep the portal's Audit Log
   in a second window.

To change the rulebook, edit `docs/demo-rulebook-democorp01.md`, save it
as a `.txt`, and upload it to the bot (POST `/api/v1/rag/documents/upload`
with `botId`, `title` and `file` on the chatbot API); delete the old
document first so answers do not mix.

## The story

Say the line in bold. The bracketed text is what to point at while the
assistant works. Korean versions of every line are in
`demo-story-seoul-ko-prompts.md`. Scenes 1 to 4 return the real content
listed above.

### Scene 1. Monday 28 September. What is waiting for me?

> **I am going to Bizplay in Seoul on Wednesday to present the MCP gateway for the AI collaboration project. Before I go, what is waiting for me in FLOW: mentions, overdue work, and anything that changed in the last few days?**

[`flow_get_my_worklist` and `flow_find_alarms`. The answer: one mention
from 김민수 on the settlement-API post, and the 22 Sep changes by 박지훈
and 김민수 in the collaboration project.]

Point at: the Audit Log. Two calls, backend FLOW, made with the
presenter's own Flow token, refreshed by the gateway. Nothing was pasted
into claude.ai.

### Scene 2. What is the state of the project?

> **Summarize the Bizplay and CBNU collaboration project for the meeting: how the task board looks, and which tasks are on me.**

[`flow_find_projects`, then `flow_collect_project_chain` and
`flow_query_tasks`. The answer: the board with 28 items in 피드백, the four
API tasks assigned to the presenter, and the six-product launch post.]

Point at: nothing yet. Let the numbers land.

### Scene 3. The one thing to settle in Seoul

> **Open 김민수's post about the settlement API and read the whole comment thread. What did the Bizplay side say is still missing on our side?**

[`flow_get_post` on 82494830. The answer names the gap: when evidence is
added to a settlement, the policy amount must be looked up and the claim
capped to it, and it quotes the attached document. That is the agenda for
the Seoul meeting.]

Point at: the FLOW page, Tool policy. 20 of 39 tools enabled, every one a
read. The assistant reads discussions; it cannot post or edit in FLOW.

### Scene 4. What does the rulebook allow?

> **On 30 September I go to Bizplay in Seoul for one day, from Osong by KTX, carrying the demo equipment. I am regular staff. What must I do before I go, what is my daily allowance, which KTX class may I take, and may I take a taxi from Seoul Station to the office?**

[`listBots` for the company (corpNo filled in by the gateway), then
`askBot` on 국내출장 규정 안내 봇. The answer, with article numbers: file a
trip plan first, approver 김도하; 40,000원 for a full day; KTX standard
class, 18,500원 one way Osong to Seoul; a taxi is accepted with a reason,
and carrying equipment is one.]

Point at: the BZP_Chatbot page, "Which tool produces which id". `askBot`
needs a botId that `listBots` returns in field `id`. That one line is why
the assistant never asked "which bot?".

### Scene 5. File the trip plan for today

> **File a domestic trip plan for today, 30 September 2026: Seoul, Bizplay head office, from Osong by KTX and back the same day, purpose "MCP gateway showcase for the Bizplay AI collaboration project". Send it to 김도하 for approval.**

[`planChat`, several turns the assistant holds on its own: purpose chips,
destination, route, remaining fields, then `corporationUsers` to pick
김도하 by name, then `createPlan`. The reply carries the document number.
If the audience includes 김도하, this is the moment to approve it on a
phone.]

Point at: the TravelExpense usage notes, the line "Answer them yourself".
Before those notes the assistant stopped at the first chip and told the
user to click it in the web app.

### Scene 6. Same day, end of the showcase. Settle it

> **The trip is done. Settle today's Seoul trip: KTX Osong to Seoul round trip 37,000 won, taxi from Seoul Station to the Bizplay office 12,000 won because I carried the demo equipment, no receipt images. Submit it to 김도하.**

[The long one. `settlementChat` finds today's approved plan and imports
it; for each expense the assistant sends `manual-expense`, one plain
sentence, `expense-confirm`, "no image"; then `receipts-done`. If the
agent flags an amount against the company's configured limit and asks
whether to split the excess, the assistant asks the presenter only that.
Then SUBMIT, the approver by name, `CREATE_SETTLEMENT`, document number.
Total 49,000원 plus the automatic 40,000원 daily allowance.]

Point at: the Audit Log, a dozen calls in a row, one person, one company.
Then back to scene 4: the taxi rule the bot quoted is the reason written
on the expense. Two systems, one answer.

### Scene 7. Tell the team

> **Draft my reply to 김민수's thread: what we agreed today in Seoul on the policy-amount setting, and that today's trip is already settled through the gateway. Keep it short; I will paste it in FLOW.**

[No tool call, or one `flow_get_post` to re-read. The assistant writes the
reply and hands it over. It cannot post: FLOW is read-only on this
gateway, and it says so.]

### Scene 8. The one that is refused

Second chat, signed in as Lee Junho (`junho@bizplay.co.kr / junho1234`,
HR group).

> **Show me what Sokheang Chan is working on in FLOW.**

[Junho has no linked Flow account. The gateway tells the assistant so,
and the assistant tells Junho to connect his own account first. He cannot
borrow anyone else's.]

Point at: the Sign-in log or Audit Log. Same gateway, different person,
different answer, nothing configured in claude.ai.

## The three sentences to end on

- One URL, three systems, one sign-in. Every call ran as the person in the
  chat, with their own Flow account, their company and their audit trail.
- The assistant knew what to call first because the company wrote it down
  once, on the backend's page, and every gateway serving that backend
  inherits it.
- What the assistant may not do is decided in the portal, by tool and by
  person, and applies to any AI client that connects.

## A closing visual (optional)

After scene 6:

> **Draw one chart of today's trip: KTX, taxi and the daily allowance as bars, the rulebook standard fare as a line, and the settlement total in the title.**

claude.ai draws it from the numbers already in the conversation.
