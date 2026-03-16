# Agentic IDE - Perforce & Swarm MCP Servers

Two MCP (Model Context Protocol) servers that give your Agentic IDE full Perforce + Swarm superpowers:

| Server | What it does |
|--------|-------------|
| **perforce-p4** | Official Perforce MCP server — query/modify files, changelists, shelves, workspaces, jobs, reviews |
| **p4-workflow** | Custom one-click workflow — create CLs with Cisco template, checkout files, shelve, raise Swarm reviews, fetch diffs from any review, add comments |

## Architecture

Scripts run directly from this repo — no copies, no placeholders, no deployment step.

All config is passed as **environment variables** via `mcp.json`. Edit once in mcp.json, restart your IDE, done.

```
~/.cursor/mcp.json
    │
    ├── perforce-p4 ──► this-repo/perforce-p4/p4-mcp-start.sh
    │                       ├── reads P4PORT, P4USER, P4_BIN, P4_MCP_SERVER from env
    │                       ├── resolves P4CLIENT from `p4 set`
    │                       ├── auto-login from Keychain if ticket expired
    │                       └── exec p4-mcp-server
    │
    └── p4-workflow ──► this-repo/p4-workflow/server.py
                            ├── reads P4PORT, P4USER, P4_BIN, SWARM_URL from env
                            ├── auto-login from Keychain on every p4 command
                            └── FastMCP server with 9 tools
```

---

## Prerequisites

| Tool | How to get it |
|------|---------------|
| **Agentic IDE** (Cursor/Windsurf/etc.) | https://cursor.sh |
| **p4 CLI** | `brew install --cask perforce` (macOS) or https://www.perforce.com/downloads/helix-command-line-client-p4 |
| **p4-mcp-server** | Download from https://www.perforce.com/downloads (search "MCP Server") — get the binary for your OS/arch |
| **Python 3.10+** | `brew install python3` or https://python.org |
| **Perforce account** | Your P4USER with login access to your P4PORT |
| **Swarm access** | Your Swarm instance URL (e.g. `https://your-swarm.company.com`) |

---

## Quick Start (Automated)

```bash
git clone <this-repo>
cd p4v-swarm-mcp-server
chmod +x setup.sh
./setup.sh
```

The setup script will:
1. Check for `p4` CLI and `p4-mcp-server`
2. Install Python dependencies (`fastmcp`, `httpx`)
3. Generate `~/.cursor/mcp.json` pointing to this repo's scripts

Then restart your IDE.

---

## Manual Setup

### Step 1: Install prerequisites

```bash
brew install --cask perforce
brew install python3
pip3 install fastmcp httpx
```

Download `p4-mcp-server` from Perforce and place it in `~/bin/p4-mcp-server*/p4-mcp-server`.

### Step 2: Configure mcp.json

Create or edit `~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "perforce-p4": {
      "command": "/path/to/this-repo/perforce-p4/p4-mcp-start.sh",
      "args": [
        "--toolsets", "files", "changelists", "shelves", "workspaces", "jobs", "reviews"
      ],
      "env": {
        "P4PORT": "ssl:YOUR-P4-SERVER:1666",
        "P4USER": "YOUR_USERNAME",
        "P4CLIENT_DEFAULT": "YOUR_USERNAME_YOUR_WORKSPACE",
        "P4_BIN": "/path/to/p4",
        "P4_MCP_SERVER": "/path/to/p4-mcp-server",
        "PATH": "/path/to/p4/dir:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
      }
    },
    "p4-workflow": {
      "command": "python3",
      "args": ["/path/to/this-repo/p4-workflow/server.py"],
      "env": {
        "P4PORT": "ssl:YOUR-P4-SERVER:1666",
        "P4USER": "YOUR_USERNAME",
        "P4_BIN": "/path/to/p4",
        "SWARM_URL": "https://YOUR-SWARM-SERVER",
        "PYTHONPATH": "/path/to/this-repo/p4-workflow",
        "PATH": "/path/to/p4/dir:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
      }
    }
  }
}
```

### Step 3: Restart your IDE and test

```
List my pending changelists
```

---

## Environment Variables

### perforce-p4 (p4-mcp-start.sh)

| Variable | Required | Description |
|----------|----------|-------------|
| `P4PORT` | Yes | Perforce server (e.g. `ssl:server:1666`) |
| `P4USER` | Yes | Perforce username |
| `P4CLIENT_DEFAULT` | No | Fallback workspace when `p4 set P4CLIENT` returns nothing |
| `P4_BIN` | No | Path to `p4` CLI (auto-detected from PATH or `~/bin/p4`) |
| `P4_MCP_SERVER` | No | Path to `p4-mcp-server` binary (auto-detected from `~/bin/p4-mcp-server*`) |

### p4-workflow (server.py)

| Variable | Required | Description |
|----------|----------|-------------|
| `P4PORT` | Yes | Perforce server |
| `P4USER` | Yes | Perforce username |
| `SWARM_URL` | No | Swarm base URL (default: `https://sp4-fp-swarm.cisco.com`) |
| `P4_BIN` | No | Path to `p4` CLI (auto-detected) |

---

## Available Tools

### perforce-p4 (Official)

| Tool | Description |
|------|-------------|
| `query_files` | Get file info, content, history, diff, annotations |
| `query_changelists` | List/search changelists |
| `modify_changelists` | Create/update changelist descriptions |
| `query_shelves` | List shelved files |
| `modify_shelves` | Shelve/unshelve files |
| `modify_files` | Add/edit/delete/revert files |
| `query_workspaces` | List/search workspaces |
| `modify_workspaces` | Create/update workspaces |
| `query_jobs` | List/search jobs |
| `modify_jobs` | Create/update jobs |
| `query_reviews` | List Swarm reviews |
| `modify_reviews` | Update Swarm reviews |
| `query_server` | Server info and connection status |

### p4-workflow (Custom Cisco Workflow)

| Tool | Description |
|------|-------------|
| `create_changelist` | Create CL with full Cisco IMS template against a bug ID |
| `checkout_file` | Open file(s) for edit in a CL (`p4 edit`) |
| `update_description` | Update CL description with no char limit |
| `update_review` | Re-shelve code changes — Swarm auto-versions |
| `raise_review` | Shelve + create a new Swarm review (one call) |
| `get_review_diff` | Fetch full diff + metadata for any Swarm review |
| `get_review_info` | Fetch metadata + file list for any Swarm review (no diff body) |
| `add_review_comment` | Add a comment to a Swarm review |
| `p4_login` | Check/refresh login status (auto-renews from Keychain) |
| `save_p4_password` | Store P4 password in Keychain for auto-login |

---

## Troubleshooting

**MCP servers not showing in your IDE?**
- Check `~/.cursor/mcp.json` is valid JSON (no trailing commas)
- Restart IDE completely (Cmd+Q, reopen)

**"Connect to server failed"?**
- Run `p4 login` in terminal to refresh your ticket
- Verify P4PORT: `p4 -p ssl:YOUR-SERVER:1666 info`

**p4-workflow "module not found"?**
- Run `pip3 install fastmcp httpx`
- Check `PYTHONPATH` in mcp.json points to the directory containing `server.py`

**"P4PORT must be set" error?**
- Ensure `env` block in mcp.json includes `P4PORT` and `P4USER`

---

## File Structure

```
p4v-swarm-mcp-server/
  README.md              <- You are here
  setup.sh               <- Automated installer (generates mcp.json)
  mcp.json.template      <- Template for ~/.cursor/mcp.json
  .gitignore
  perforce-p4/
    p4-mcp-start.sh      <- Wrapper script for official MCP server
  p4-workflow/
    server.py             <- Custom workflow MCP server
    requirements.txt      <- Python dependencies
```
