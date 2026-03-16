# Agentic IDE - Perforce & Swarm MCP Servers

Two MCP (Model Context Protocol) servers that give your Agentic IDE full Perforce + Swarm superpowers:

| Server | What it does |
|--------|-------------|
| **perforce-p4** | Official Perforce MCP server — query/modify files, changelists, shelves, workspaces, jobs, reviews |
| **p4-workflow** | Custom one-click workflow — create CLs with Cisco template, checkout files, shelve, raise Swarm reviews, fetch diffs from any review, add comments |

## Quick Start (Zero Dependencies Required)

```bash
git clone <this-repo>
cd p4v-swarm-mcp-server
chmod +x setup.sh
./setup.sh
```

**That's it.** The script installs everything from scratch on a bare macOS machine:

| What | How |
|------|-----|
| Homebrew | Auto-installed if missing |
| p4 CLI | Downloaded from Perforce CDN or installed via Homebrew |
| Python 3 | `brew install python3` |
| Node.js | `brew install node` (needed for sequential-thinking MCP) |
| p4-mcp-server | Guided download (requires Perforce account) |
| Python deps | `pip3 install fastmcp httpx` |
| Auth | Interactive P4 login + macOS Keychain storage |
| MCP config | Auto-generates `~/.cursor/mcp.json` |
| AI rules | Installs workflow rules to `~/.cursor/rules/` |

After setup, restart your IDE (Cmd+Q, reopen) and test:
```
List my pending changelists
```

> **Cursor AI users**: Open this repo in Cursor and ask "set this up" — the AI will identify and run the setup script automatically.

---

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
                            └── FastMCP server with 10 tools
```

---

## Manual Setup (if you prefer)

### Step 1: Install prerequisites

```bash
# Homebrew
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# p4 CLI (pick one)
brew install --cask perforce
# OR download from https://www.perforce.com/downloads/helix-command-line-client-p4

# Python 3, Node.js
brew install python3 node

# Python dependencies
pip3 install fastmcp httpx

# p4-mcp-server — download from https://www.perforce.com/downloads (search "Helix MCP Server")
```

### Step 2: Configure mcp.json

Copy `mcp.json.template` to `~/.cursor/mcp.json` and replace all placeholders with your actual paths/values.

### Step 3: Restart your IDE and test

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
- Check VPN connection
- Run `p4 login` in terminal to refresh your ticket

**p4-workflow "module not found"?**
- Run `pip3 install fastmcp httpx`
- If that fails: `pip3 install --break-system-packages fastmcp httpx`

**"P4PORT must be set" error?**
- Ensure `env` block in mcp.json includes `P4PORT` and `P4USER`

**p4 CLI not found after install?**
- Check `~/bin/p4` exists and is executable
- Or re-run `./setup.sh`

---

## File Structure

```
p4v-swarm-mcp-server/
  README.md                     <- You are here
  setup.sh                      <- Zero-to-working installer
  mcp.json.template             <- Template for manual ~/.cursor/mcp.json setup
  .gitignore
  .cursor/rules/
    setup-guide.mdc             <- Tells Cursor AI how to set up this repo
  rules/
    p4-workflow.mdc             <- Workflow rules (installed globally by setup.sh)
  perforce-p4/
    p4-mcp-start.sh             <- Wrapper script for official MCP server
  p4-workflow/
    server.py                   <- Custom workflow MCP server
    requirements.txt            <- Python dependencies
```
