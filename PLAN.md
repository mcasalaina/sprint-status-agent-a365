# Sprint Status Intelligence Agent — Implementation Plan

> **Reference implementation**: This project follows the same architecture as
> [`aycabas/refund-agent-a365`](https://github.com/aycabas/refund-agent-a365)
> (local path: `~/src/refund-agent-a365`). That repo contains the working
> Foundry prompt agent + A365 hosted agent pattern we're replicating here for
> a different use case.

## Problem Statement

Build a two-agent system following the same architecture as the refund agent:
1. **Foundry Prompt Agent** ("Sprint Intelligence Agent") — mines M365 data via WorkIQ to understand team activity, blockers, decisions, and commitments across emails, meetings, and files.
2. **A365 Hosted Agent** ("Sprint Status Bot") — Teams bot that dev leads / PMs / engineers interact with to get synthesized status on what's happening across the team.

The goal: replace the "what's everyone working on?" meeting with an agent that already knows, because it can read the team's email, meeting notes, and documents.

---

## Architecture

Mirrors the refund-agent-a365 pattern (see [`agent.py`](https://github.com/aycabas/refund-agent-a365/blob/main/agent.py), [`host_agent_server.py`](https://github.com/aycabas/refund-agent-a365/blob/main/host_agent_server.py), [`agent_interface.py`](https://github.com/aycabas/refund-agent-a365/blob/main/agent_interface.py)):

```
Teams User (dev lead / PM)
    ↕  (A365 / Teams channel)
A365 Hosted Agent  (host_agent_server.py + sprint_agent.py)
    │   Orchestrated via LangChain
    ↕  (OpenAI Responses API via Foundry applications protocol)
Foundry Prompt Agent  (configured in Foundry UI)
    ↕  (WorkIQ — emails, meetings, files, Teams messages)
M365 Data  (Outlook, Calendar, OneDrive/SharePoint, Teams)
```

### Identity & Auth Flow

The **hosted agent** is the one running in Teams with an A365 identity (blueprint + agent user). When a user messages the bot:

1. The **hosted agent** receives the message in Teams via the A365 `host_agent_server.py` handler
2. The A365 platform provides the agent's identity credentials (via `AgenticUserAuthorization`)
3. The hosted agent calls `auth.exchange_token()` to get an **OBO (On-Behalf-Of) token** scoped to `https://ai.azure.com/.default`
4. This token is passed to the Foundry agent via the `Authorization: Bearer <token>` header on the OpenAI Responses API call
5. The **Foundry prompt agent** uses this token to authenticate with WorkIQ — so WorkIQ calls (email search, Teams messages, etc.) are made **under the agent's A365 identity**, not the end user's personal identity
6. This means the agent has access to its own mailbox, its own Teams presence, and any M365 data shared with its agent user account

This is the same pattern used by the refund agent (see [`_exchange_user_token()`](https://github.com/aycabas/refund-agent-a365/blob/main/agent.py#L217) and [`_get_client_for_user()`](https://github.com/aycabas/refund-agent-a365/blob/main/agent.py#L94)).

The A365 blueprint's `customBlueprintPermissions` must include:
- `McpServers.Mail.All` — email search and send
- `McpServers.Teams.All` — Teams message read/send (for outreach to teammates)
- `McpServersMetadata.Read.All` — WorkIQ metadata

### A365 Blueprint

Create an Agent 365 blueprint for this agent, following the same pattern as the refund agent (see [`a365.config.json`](https://github.com/aycabas/refund-agent-a365/blob/main/a365.config.json)). The blueprint name should be human-readable but still end with "Blueprint":

- `agentBlueprintDisplayName`: **"Sprint Status Intelligence Blueprint"**
- `agentIdentityDisplayName`: "Sprint Status Intelligence Identity"
- `agentUserPrincipalName`: `sprintstatusagent@agent365001.onmicrosoft.com`
- `agentUserDisplayName`: "Sprint Status Intelligence Agent User"
- `agentDescription`: "Sprint Status Intelligence — Agent 365 Agent"

Compare with refund agent's `"refundagent Blueprint"` — this one uses a descriptive, human-readable name while keeping the "Blueprint" suffix convention.

### LangChain Orchestration

The **hosted agent** (`sprint_agent.py`) uses **LangChain** to orchestrate the interaction with the Foundry prompt agent. Instead of making raw OpenAI Responses API calls like the refund agent does, it uses LangChain to:

- **Manage conversation memory**: LangChain's `ConversationBufferMemory` or `ConversationSummaryMemory` replaces the manual `_conversations` dict in the refund agent
- **Chain multiple Foundry calls**: For complex queries (e.g., "collect standup from the team"), the hosted agent can use a LangChain chain/agent to break the task into steps — first search for existing data, then decide if outreach is needed, then compose the final response
- **Tool abstraction**: The Foundry prompt agent is wrapped as a LangChain tool, making it composable with other tools if needed in the future
- **Structured output**: LangChain's output parsers ensure the Foundry agent's responses are consistently structured before being sent to Teams

This means the Foundry prompt agent remains a simple, focused agent (search M365, synthesize, respond), while the hosted agent handles multi-step orchestration logic via LangChain.

Key files to fork from the reference repo:
- `agent.py` → `sprint_agent.py` (swap `RefundAgent` for `SprintStatusAgent`, add LangChain orchestration)
- `agent_interface.py` → copy as-is (same abstract base class)
- `host_agent_server.py` → copy and adapt (same generic host pattern)
- `agent-instructions.md` → `sprint-agent-instructions.md` (entirely new content)
- `a365.config.json` → new config with same structure, new agent identity
- `.env` / `.env.template` → new Foundry agent endpoint + ID

---

## Foundry Prompt Agent: "Sprint Intelligence Agent"

### What It Does
When queried, it uses WorkIQ to search the user's M365 data and synthesizes engineering status. It answers questions like:
- "What's the team been working on this week?"
- "Are there any blockers mentioned in recent emails or meetings?"
- "What did we decide in the last sprint planning?"
- "What's the status of Feature X?"
- "Summarize the last standup notes"

### How It Uses WorkIQ (Material Usage)
WorkIQ is the **primary data source** — the agent has no hardcoded data (unlike the refund agent's order table). Everything comes from live M365 data:

1. **Email Mining**: Searches for PR notification emails, build/deploy alerts, team discussion threads, escalation emails, blocker reports. Uses WorkIQ `$search` with KQL to find relevant messages (same query syntax rules as the [refund agent instructions](https://github.com/aycabas/refund-agent-a365/blob/main/agent-instructions.md)).
2. **Meeting Intelligence**: Searches for meeting notes, standup summaries, sprint planning outcomes, retro action items. Looks at recent calendar events and any associated notes/transcripts.
3. **Document Awareness**: Finds specs, design docs, and status reports in OneDrive/SharePoint that relate to active work.
4. **Teams Outreach**: When the agent can't find enough information from M365 data alone, it uses WorkIQ to send Teams messages to team members asking for updates. For example:
   - PM asks "What's the status of the auth migration?" → agent finds no recent signals → agent uses WorkIQ to DM the feature owner on Teams: "Hi James — your PM is asking about the auth migration status. Can you share a quick update?"
   - Supports **async standup collection**: agent uses WorkIQ to DM each team member asking for their standup update, then compiles the responses into a summary
   - All outreach is transparent — the agent tells the requester who it's contacting and why, and always asks permission before reaching out

### Knowledge Base (Foundry IQ / Instructions)
The agent's instructions include:
- **Team roster & roles** — who's on the team, what area they own
- **Project/feature taxonomy** — current epics, features, workstreams so the agent can categorize activity
- **Sprint conventions** — sprint cadence, standup schedule, definition of "blocker"
- **Synthesis rules** — how to summarize, what to highlight (blockers > progress > FYIs), confidence levels when inferring status from indirect signals
- **Outreach rules** — when to offer to contact a team member (e.g., no data found, stale data, ambiguous signals), how to frame the ask, always get requester's permission first

### Response Format
Structured summaries with:
- **Activity Summary**: What happened, organized by person or workstream
- **Blockers & Risks**: Anything flagged as a blocker in emails/meetings, or inferred from patterns (e.g., "no updates on Feature X in 5 days")
- **Decisions Made**: Key decisions from meetings or email threads
- **Action Items**: Commitments found in emails/meetings that appear unresolved
- **Confidence Notes**: Where the agent is inferring vs. has direct evidence

---

## A365 Hosted Agent: "Sprint Status Bot"

### What It Does
A Teams bot that acts as the interface to the Foundry agent. Dev leads, PMs, and engineers message it in Teams (DM or channel) to get status intelligence.

### Key Capabilities
- Forwards user queries to the Foundry Sprint Intelligence Agent
- Formats responses as Teams Adaptive Cards (structured status reports)
- Can send proactive notifications (e.g., weekly digest, blocker alerts)
- Maintains conversation threading so follow-up questions have context

### Implementation
Mirrors [`agent.py` in refund-agent-a365](https://github.com/aycabas/refund-agent-a365/blob/main/agent.py):
- Inherits from `AgentInterface`
- Uses OpenAI Responses API to communicate with Foundry agent (same `_API_VERSION = "2025-11-15-preview"` pattern)
- Same `host_agent_server.py` pattern for A365 hosting
- Same A365 config pattern for Teams registration, identity, permissions
- Same WorkIQ permissions: `McpServers.Mail.All`, `McpServers.Teams.All`, `McpServersMetadata.Read.All` (see [a365.config.json](https://github.com/aycabas/refund-agent-a365/blob/main/a365.config.json))

---

## Implementation Todos

### 1. Create Foundry Agent Instructions (`sprint-agent-instructions.md`)
Write the system prompt for the Foundry prompt agent, including:
- Role description and boundaries
- Team roster (sample data for demo)
- Project taxonomy (sample features/epics)
- Sprint conventions
- WorkIQ search patterns and query syntax rules (adapted from [refund agent instructions](https://github.com/aycabas/refund-agent-a365/blob/main/agent-instructions.md))
- Response format specification
- Explicit rules about what the agent does NOT do (doesn't write code, doesn't file bugs, doesn't modify anything)

### 2. Create A365 Hosted Agent (`sprint_agent.py`)
Fork from [`agent.py`](https://github.com/aycabas/refund-agent-a365/blob/main/agent.py), adapting:
- Class name: `SprintStatusAgent`
- Foundry agent reference: point to the new Sprint Intelligence Agent
- **LangChain orchestration**: Replace raw OpenAI Responses API calls with LangChain
  - Wrap the Foundry agent as a LangChain `Tool`
  - Use `ConversationBufferMemory` for conversation history (replaces manual `_conversations` dict)
  - Use a LangChain `AgentExecutor` or chain for multi-step workflows (search → assess → outreach → summarize)
- Same OBO token exchange pattern for identity passthrough
- Notification support for proactive digests

### 3. Create Scaffolding Files
Copy and adapt from refund-agent-a365:
- `agent_interface.py` — copy as-is
- `host_agent_server.py` — copy and adapt agent import
- `start_with_generic_host.py` — copy and adapt
- `local_authentication_options.py` — copy as-is
- `token_cache.py` — copy as-is
- `pyproject.toml` / `requirements.txt` — same dependencies + `langchain`, `langchain-openai`
- `.env.template` — new Foundry agent endpoint + ID
- `a365.config.json` / `a365.config.example.json` — new agent identity

### 4. Configure Foundry Agent in Azure AI Foundry UI
- Create new agent in Foundry
- Paste instructions from `sprint-agent-instructions.md`
- Connect WorkIQ tool
- Configure model (GPT-4o or similar)
- Note the agent ID for the hosted agent config

### 5. Test End-to-End
- Test Foundry agent standalone (via Foundry playground)
- Test hosted agent locally (same `python start_with_generic_host.py` pattern)
- Test via Teams

---

## Sample Interactions

**User**: "What's the team been working on since Monday?"

**Agent** (via WorkIQ email search + meeting search):
> **Weekly Activity Summary (May 4–10)**
>
> **Frontend (Sarah & Alex)**
> - PR merged: Dashboard redesign (#423) — per GitHub notification email Wed
> - Sarah mentioned in standup notes: "accessibility audit wrapping up Friday"
>
> **Backend (James & Lisa)**
> - Email thread about API rate limiting design — decision made Thursday to use token bucket
> - James flagged in email: blocked on DevOps approval for staging deploy
>
> **Blockers**
> - 🔴 James: staging deploy blocked on DevOps approval (mentioned in Thu email)
> - 🟡 No update from Lisa since Tuesday — may want to check in
>
> **Decisions**
> - Token bucket for rate limiting (from Thu email thread, decision by James + Lisa)

**User**: "Tell me more about the rate limiting decision"

**Agent** (deeper WorkIQ search):
> Found email thread "RE: API Rate Limiting Approach" (Thu May 7, 4 participants).
> James proposed token bucket, Lisa raised concern about Redis dependency, team agreed to use in-memory for v1 with Redis migration later. Action item: James to write ADR by Friday.

**User**: "What's the status of the auth migration?"

**Agent** (WorkIQ search finds nothing recent):
> I couldn't find any recent emails, meeting notes, or documents about the auth migration in the last 2 weeks. The feature owner is James Park.
>
> Would you like me to reach out to James on Teams to ask for a status update?

**User**: "Yes, ask him"

**Agent** (sends Teams DM to James):
> ✉️ I've messaged James on Teams: *"Hi James — your PM is asking about the auth migration status. Can you share a quick update on where things stand?"*
>
> I'll let you know when he responds.

*(later, after James replies)*

**Agent**:
> 📬 James responded: *"Auth migration is about 70% done. Finished the token refresh flow, still working on the session-to-JWT cutover. Should be ready for code review by Wednesday. No blockers."*
>
> **Summary**: Auth migration ~70% complete, code review expected Wednesday, no blockers.

---

## Key Differences from Refund Agent

| Aspect | Refund Agent | Sprint Status Agent |
|--------|-------------|-------------------|
| Foundry IQ data | Hardcoded order table + policy | Team roster + project taxonomy |
| WorkIQ usage | Supplementary (email lookup) | **Primary data source** (all intelligence from M365) |
| Query pattern | Lookup-style ("check order #8822") | Synthesis-style ("what's happening this week?") |
| Response style | Structured eligibility assessment | Narrative summary with confidence levels |
| Proactive features | Notifications on refund status | Weekly digests, blocker alerts |
