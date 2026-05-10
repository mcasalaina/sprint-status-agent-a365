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
    ↕  (OpenAI Responses API via Foundry applications protocol)
Foundry Prompt Agent  (configured in Foundry UI)
    ↕  (WorkIQ — emails, meetings, files)
M365 Data  (Outlook, Calendar, OneDrive/SharePoint)
```

Key files to fork from the reference repo:
- `agent.py` → `sprint_agent.py` (swap `RefundAgent` for `SprintStatusAgent`)
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

### Knowledge Base (Foundry IQ / Instructions)
The agent's instructions include:
- **Team roster & roles** — who's on the team, what area they own
- **Project/feature taxonomy** — current epics, features, workstreams so the agent can categorize activity
- **Sprint conventions** — sprint cadence, standup schedule, definition of "blocker"
- **Synthesis rules** — how to summarize, what to highlight (blockers > progress > FYIs), confidence levels when inferring status from indirect signals

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
- Thread/conversation management (same pattern)
- Notification support for proactive digests

### 3. Create Scaffolding Files
Copy and adapt from refund-agent-a365:
- `agent_interface.py` — copy as-is
- `host_agent_server.py` — copy and adapt agent import
- `start_with_generic_host.py` — copy and adapt
- `local_authentication_options.py` — copy as-is
- `token_cache.py` — copy as-is
- `pyproject.toml` / `requirements.txt` — same dependencies
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

---

## Key Differences from Refund Agent

| Aspect | Refund Agent | Sprint Status Agent |
|--------|-------------|-------------------|
| Foundry IQ data | Hardcoded order table + policy | Team roster + project taxonomy |
| WorkIQ usage | Supplementary (email lookup) | **Primary data source** (all intelligence from M365) |
| Query pattern | Lookup-style ("check order #8822") | Synthesis-style ("what's happening this week?") |
| Response style | Structured eligibility assessment | Narrative summary with confidence levels |
| Proactive features | Notifications on refund status | Weekly digests, blocker alerts |
