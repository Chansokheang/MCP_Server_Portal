"""Set up the AskDoc chatbot backend so a model can use it without being handed a botId.

Safe to run again. It trims the backend to the tools a chat needs, gives them
readable names and descriptions, binds corpNo to the caller's company, writes
the usage notes, and sets the opening lines of the gateway that serves it.

    uv run python scripts/guide_askdoc.py --portal https://mcp-portal.aiconvergencelab.com

On a portal older than the guidance release the names, notes and bindings are
ignored by the API; the script says so, and a second run after upgrading adds them.
"""

from __future__ import annotations

import argparse
import os

import httpx

KEEP = {
    "listByCorp": ("listBots", "List the chatbots of the signed-in user's company. Call this first to get a botId; never ask the user for a botId."),
    "get_2": ("getBot", "Read one chatbot's configuration (name, description, model) by botId."),
    "listRecommendedQuestions": ("listStarterQuestions", "Suggested starter questions of a chatbot, by botId. Offer them when the user has no specific question."),
    "chat": ("askBot", "Ask a chatbot a question and get its answer from the company's documents. Put the question in `query` and the bot in "
                       "`botId` (from listBots). Leave sessionId empty on the first turn; on follow-ups send the sessionId the previous answer returned."),
    "history": ("getChatHistory", "Read the messages of one chat session, by sessionId."),
    "list_3": ("listBotDocuments", "List the documents a chatbot answers from, by botId."),
}
NOTES = """To answer a company policy or how-to question:
1. listBots to see the company's chatbots (the company is filled in for you).
2. Pick the bot whose name or description fits the question; if unsure, listStarterQuestions shows what it covers.
3. askBot with that botId and the user's question. Keep the returned sessionId for follow-up questions.
Never ask the user for a botId, a company number or a corp group id. If listBots returns nothing, say the company has no chatbot yet."""
GATEWAY_LEAD = ("You help an employee with company knowledge and their work in FLOW. Use the AskDoc chatbot tools for policy and how-to "
                "questions, and the FLOW tools for projects, tasks and schedules. Work as the signed-in user; do not ask for ids you can look up.")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--portal", default=os.environ.get("PORTAL_URL", "http://127.0.0.1:18090"))
    ap.add_argument("--email", default=os.environ.get("PORTAL_EMAIL", "admin@bizplay.co.kr"))
    ap.add_argument("--password", default=os.environ.get("PORTAL_PASSWORD", "admin1234"))
    ap.add_argument("--backend", default="bzp-chatbot")
    ap.add_argument("--gateway", default="askdoc")
    args = ap.parse_args()

    c = httpx.Client(base_url=args.portal, timeout=60)
    c.headers["Authorization"] = "Bearer " + c.post("/api/login", json={"email": args.email, "password": args.password}).json()["token"]

    tools = c.get(f"/api/registry/{args.backend}/tools").json()["items"]
    on = off = 0
    for t in tools:
        if t["name"] in KEEP:
            alias, description = KEEP[t["name"]]
            r = c.put(f"/api/registry/{args.backend}/tools/{t['name']}", json={
                "enabled": True, "confirm": False, "roles": ["employee", "manager"], "description": description, "alias": alias})
            r.raise_for_status()
            on += 1
        elif t["enabled"]:
            c.put(f"/api/registry/{args.backend}/tools/{t['name']}", json={"enabled": False}).raise_for_status()
            off += 1
    print(f"tools: {on} kept with descriptions, {off} switched off, {len(tools) - on - off} already off")

    r = c.patch(f"/api/registry/{args.backend}", json={
        "instructions": NOTES,
        # Which tool produces which id: written into askBot's description, and into the error when botId is missing.
        "comes_from": {"chat.botId": {"tool": "listByCorp", "field": "id"}, "history.sessionId": {"tool": "chat", "field": "sessionId"},
                       "get_2.id": {"tool": "listByCorp", "field": "id"}, "listRecommendedQuestions.id": {"tool": "listByCorp", "field": "id"},
                       "list_3.botId": {"tool": "listByCorp", "field": "id"}}})
    r.raise_for_status()
    guided = "instructions" in r.json()
    named = any(t.get("alias") for t in c.get(f"/api/registry/{args.backend}/tools").json()["items"])
    if guided:
        print(f"backend: usage notes set, company filled in from the caller, readable tool names {'set' if named else 'NOT set'}")
    else:
        print("backend: this portal is older than the guidance release, so names, notes and bindings were ignored. Upgrade, then run this again.")

    prefix = next((p["tool_prefix"] for p in c.get("/api/registry").json()["items"] if p["id"] == args.backend), "bzp_chatbot_")
    # One tool that does the whole thing: list the company's bots, take the first, ask it. The gateway runs the steps in order.
    workflow = {"name": "askCompanyBot", "description": "Ask the company's chatbot a question and return its answer. Use this for any policy or how-to question; no botId needed.",
                "inputs": {"question": {"description": "The user's question, in their own words"}},
                "steps": [{"tool": f"{prefix}listBots", "args": {}},
                          {"tool": f"{prefix}askBot", "args": {"botId": "{{steps.0.data.0.id}}", "query": "{{input.question}}"}}],
                "output": "steps.1.data"}
    r = c.put(f"/api/endpoints/{args.gateway}/settings", json={"instructions": GATEWAY_LEAD, "workflows": [workflow]})
    if r.status_code == 200 and guided:
        told = c.get(f"/api/endpoints/{args.gateway}/instructions").json()["text"]
        print(f"gateway {args.gateway}: opening lines set; a model is now told {len(told)} characters of guidance")
    elif r.status_code != 200:
        print(f"gateway {args.gateway}: not found ({r.status_code}); set its instructions on the gateway page")


if __name__ == "__main__":
    main()
