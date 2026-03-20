# Agentic IDE: Perforce + Swarm MCP — Demo Guide

## The Pitch (30 seconds)

> "I built an MCP server that gives Cursor AI full Perforce and Swarm superpowers.
> You talk to the AI in plain English — it creates changelists with the Cisco template,
> checks out files, shelves, raises Swarm reviews, fetches diffs, adds comments.
> Auth is zero-touch — Keychain or browser SSO, fully automatic, no terminal needed."

---

## Problem → Solution (2 minutes)

### Before (the old way)

| Step | What you did manually |
|------|----------------------|
| 1 | Terminal: `p4 login` → copy URL → open browser → SSO → come back |
| 2 | Terminal: `p4 change` → edit spec → fill in Cisco template by hand |
| 3 | Terminal: `p4 edit -c 12345 //depot/path/to/file.pm` |
| 4 | Edit code in IDE |
| 5 | Terminal: `p4 shelve -f -c 12345` |
| 6 | Browser: Go to Swarm → create review manually |
| 7 | Browser: Swarm → add reviewers → submit |
| 8 | Later: terminal `p4 shelve -f -c 12345` again to push updates |

**8 context switches** between IDE, terminal, and browser. Every. Single. Time.

### After (with MCP)

| Step | What you say to the AI |
|------|------------------------|
| 1 | "Create a changelist for CSCwt43076 in IMS_10_5_MAIN" |
| 2 | "Check out COOP.pm in that CL" |
| 3 | Edit code in IDE (AI can help) |
| 4 | "Raise a Swarm review with reviewer jsmith" |
| 5 | "Push my latest changes to the review" |

**Zero context switches.** Auth is invisible. Template is automatic. One IDE for everything.

---

## Architecture Slide

```
┌─────────────────────────────────────────────────────┐
│                    Cursor IDE                        │
│                                                      │
│  User ──► AI Agent ──► MCP Protocol ──┐              │
│                                       │              │
│            ┌──────────────────────────┼──────────┐   │
│            │      mcp.json            │          │   │
│            │                          ▼          │   │
│            │   ┌──────────────────────────────┐  │   │
│            │   │   p4-workflow (server.py)    │  │   │
│            │   │   • FastMCP Python server    │  │   │
│            │   │   • 10 tools                 │  │   │
│            │   │   • Zero-touch auth          │  │   │
│            │   │   • Cisco IMS template       │  │   │
│            │   └───────┬──────────┬───────────┘  │   │
│            │           │          │               │   │
│            │           ▼          ▼               │   │
│            │     Perforce     Swarm API           │   │
│            │     (p4 CLI)    (HTTP/REST)          │   │
│            │                                      │   │
│            │   ┌──────────────────────────────┐   │   │
│            │   │  perforce-p4 (official)      │   │   │
│            │   │  • Helix MCP Server binary   │   │   │
│            │   │  • File queries, history     │   │   │
│            │   │  • Workspace management      │   │   │
│            │   └──────────────────────────────┘   │   │
│            └──────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
```

### Auth Flow (zero-touch)

```
Any p4 command
  │
  ├─ Ticket valid? ──► Execute ──► Done
  │
  ├─ Keychain password? ──► p4 login ──► Retry ──► Done
  │
  └─ SAML/SSO ──► Auto-open browser ──► Wait ──► Retry ──► Done
                   (no copy-paste)
```

---

## Live Demo Script

### Demo 1: Zero-to-Working Setup (2 min)

> Show this if audience hasn't seen the setup before.

```
1. Open terminal in the repo
2. Run: ./setup.sh
3. It asks for P4USER, P4PORT, workspace name
4. Installs everything, generates mcp.json, stores password in Keychain
5. Restart Cursor
6. Type: "List my pending changelists"
   → AI uses perforce-p4 to query and show results
```

**Talking point:** "From a bare Mac to a fully working Perforce AI workflow — one script, 2 minutes."

---

### Demo 2: Full Bug Fix Workflow (5 min) ← THE MAIN DEMO

> This is the money demo. Do this one live.

**Step 1 — Create the changelist**

Type in Cursor chat:
```
Create a changelist for CSCwt43076 in workspace IMS_10_5_MAIN.
Description: Fix HA sync skip when peer upgrade is running
Root cause: Missing guard for upgrade-in-progress state in Transaction::HADC::Request
Solution: Add upgrade state check before initiating periodic sync
```

**What happens:** AI calls `create_changelist` → CL created with full Cisco IMS template filled in. Show the CL number.

**Step 2 — Check out a file**

```
Check out COOP.pm in that changelist
```

**What happens:** AI calls `checkout_file` with the local path → auto-converts to depot path → `p4 edit`.

**Step 3 — Make a code change**

Open the file, make a small edit (or let the AI do it). This part is normal IDE work.

**Step 4 — Raise a Swarm review**

```
Raise a Swarm review for that CL with reviewer jsmith
```

**What happens:** AI calls `raise_review` → shelves files + creates Swarm review in ONE call. Returns the review URL.

**Step 5 — Show the review**

```
Show me the diff for that review
```

**What happens:** AI calls `get_review_diff` → fetches from Swarm API + runs `p4 describe -S` → shows full diff inline.

**Step 6 — Push an update**

Make another edit, then:
```
Push my changes to the review
```

**What happens:** AI calls `update_review` → re-shelves → Swarm auto-creates a new version.

---

### Demo 3: Auth is Invisible (1 min)

> Best shown if your ticket is actually expired. If not, describe it.

**If ticket is expired:**
```
List my pending changelists
```

**What happens:** The command auto-detects expired ticket → tries Keychain → if Keychain fails → opens browser for SSO automatically → waits → retries → returns results. User does nothing except complete SSO in the browser that opened on its own.

**Talking point:** "I never typed `p4 login`. I never copied a URL. The server handled everything. If Keychain is set up, you don't even see the browser — it's fully silent."

---

### Demo 4: Review Any Colleague's Code (1 min)

```
Show me the diff for Swarm review 4960267
```

or

```
What files are in review 4990354?
```

**What happens:** AI calls `get_review_diff` or `get_review_info` → works for ANY review, not just yours.

**Talking point:** "Code review without leaving the IDE. The AI can also analyze the diff and explain what changed."

---

## Key Numbers for the Slide

| Metric | Value |
|--------|-------|
| Lines of code (server.py) | ~740 |
| External dependencies | 2 (fastmcp, httpx) |
| Tools exposed | 10 |
| Setup time (bare Mac) | ~3 minutes |
| Context switches per code review | 0 (was 8+) |
| Auth handling | Fully automatic |
| Template compliance | 100% (Cisco IMS template built-in) |

---

## Anticipated Questions

**Q: Why not just use the official Perforce MCP server?**
> It handles queries well but doesn't know about Cisco's CL template, doesn't integrate with Swarm's review API, and has a 2000-char limit on descriptions. p4-workflow fills those gaps. They work side by side.

**Q: Is the password safe in Keychain?**
> Yes — macOS Keychain is hardware-backed on Apple Silicon (Secure Enclave). It's the same store that Safari uses for passwords. Never written to disk or logs.

**Q: Does it work with other IDEs?**
> Any IDE that supports MCP (Model Context Protocol). Today that's Cursor. VS Code + GitHub Copilot are adding MCP support. The server is IDE-agnostic — it's just a Python process speaking JSON over stdio.

**Q: Can other teams use this?**
> Yes. `./setup.sh` handles everything. Clone the repo, run the script, restart IDE. Works for any Perforce server and any Swarm instance — just change the env vars.

**Q: What about CI/CD? Does this replace automation?**
> No — this is for the developer inner loop (write code, raise review). CI/CD runs after the review is approved. They're complementary.

---

## Presentation Order (recommended)

| # | Section | Time | Notes |
|---|---------|------|-------|
| 1 | The Pitch | 0:30 | Start with the one-liner |
| 2 | Problem → Solution | 2:00 | Before/after comparison — this is what hooks people |
| 3 | Architecture Slide | 1:00 | Quick, don't over-explain |
| 4 | **Live Demo: Full Workflow** | 5:00 | The main event — Demo 2 above |
| 5 | Auth Demo | 1:00 | Show or describe the zero-touch flow |
| 6 | Review Colleague's Code | 1:00 | Quick "one more thing" |
| 7 | Q&A | 2:00 | Use the anticipated questions above |
| | **Total** | **~12 min** | |

---

## Pre-Demo Checklist

- [ ] VPN connected
- [ ] Cursor open with MCP servers green (check bottom status bar)
- [ ] `p4 login -s` shows valid ticket
- [ ] Have a test CDETS ID ready (e.g. CSCwt43076)
- [ ] Know your workspace name (e.g. IMS_10_5_MAIN)
- [ ] Have a file in mind to check out (e.g. COOP.pm)
- [ ] Browser open in background (for SSO demo if needed)
- [ ] Terminal visible showing `p4 login -s` result (to prove ticket before/after)
