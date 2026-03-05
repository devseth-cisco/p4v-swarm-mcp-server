# Agentic IDE - Perforce & Swarm MCP Servers

Two MCP (Model Context Protocol) servers that give your Agentic IDE full Perforce + Swarm superpowers:

| Server | What it does |
|--------|-------------|
| **perforce-p4** | Official Perforce MCP server — query/modify files, changelists, shelves, workspaces, jobs, reviews |
| **p4-workflow** | Custom one-click workflow — create CLs with Cisco template, checkout files, shelve, raise Swarm reviews, add comments |

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
cd agentic-ide-p4-mcp-setup
chmod +x setup.sh
./setup.sh
```

Example session (using devseth's config as reference):
```
Perforce username (P4USER): devseth
Perforce server (P4PORT) [ssl:sbg-perforce.esl.cisco.com:1666]: ssl:sbg-perforce.esl.cisco.com:1666
Default workspace name (e.g. 7_4_1_MAIN): 7_4_1_MAIN
Swarm URL [https://sp4-fp-swarm.cisco.com]: https://sp4-fp-swarm.cisco.com
Install directory [/Users/devseth/bin]: /Users/devseth/bin

Configuration:
  P4USER          = devseth
  P4PORT          = ssl:sbg-perforce.esl.cisco.com:1666
  Default Client  = devseth_7_4_1_MAIN
  Swarm URL       = https://sp4-fp-swarm.cisco.com
  Install Dir     = /Users/devseth/bin

Proceed? (y/n): y
```

Then restart your IDE.

---

## Manual Setup (Step-by-Step)

### Step 1: Install p4 CLI

```bash
# macOS (Homebrew)
brew install --cask perforce

# Or download directly and place in ~/bin/
mkdir -p ~/bin
# Copy the downloaded p4 binary to ~/bin/p4
chmod +x ~/bin/p4
```

Verify it works:
```bash
~/bin/p4 -V
```

### Step 2: Configure p4 CLI

```bash
# Set your Perforce server and user
p4 set P4PORT=ssl:YOUR-P4-SERVER:1666
p4 set P4USER=YOUR_USERNAME
p4 set P4CLIENT=YOUR_WORKSPACE_NAME

# Login (you'll be prompted for password)
p4 login
```

### Step 3: Install p4-mcp-server (Official Perforce MCP Server)

1. Download from Perforce website — look for "Helix MCP Server" for your platform
2. Extract and place the binary:

```bash
mkdir -p ~/bin/p4-mcp-server
# Copy/move the extracted p4-mcp-server binary into ~/bin/p4-mcp-server/
chmod +x ~/bin/p4-mcp-server/p4-mcp-server
```

3. Copy the wrapper script:

```bash
cp perforce-p4/p4-mcp-start.sh ~/bin/p4-mcp-start.sh
chmod +x ~/bin/p4-mcp-start.sh
```

4. Edit `~/bin/p4-mcp-start.sh` — update these values:

```bash
export P4PORT="${P4PORT:-ssl:YOUR-P4-SERVER:1666}"
export P4USER="${P4USER:-YOUR_USERNAME}"
# Update the fallback workspace name:
export P4CLIENT="YOUR_DEFAULT_WORKSPACE"
# Update the path to the p4-mcp-server binary:
exec ~/bin/p4-mcp-server/p4-mcp-server "$@"
```

### Step 4: Install p4-workflow (Custom Workflow Server)

1. Install Python dependencies:

```bash
cd p4-workflow
pip3 install -r requirements.txt
```

2. Copy server.py to your preferred location:

```bash
mkdir -p ~/bin/p4-workflow
cp server.py ~/bin/p4-workflow/server.py
```

3. Edit `~/bin/p4-workflow/server.py` — update the config block at the top:

```python
P4_BIN    = "/path/to/your/p4"          # e.g. ~/bin/p4 or /usr/local/bin/p4
P4_PORT   = "ssl:YOUR-P4-SERVER:1666"
P4_USER   = "YOUR_USERNAME"
SWARM_URL = "https://YOUR-SWARM-SERVER"
```

### Step 5: Configure Agentic IDE MCP Settings

1. Open or create `~/.cursor/mcp.json`
2. Copy the contents of `mcp.json.template` from this repo
3. Update all paths and credentials to match your setup

The file should look like:

```json
{
  "mcpServers": {
    "sequential-thinking": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-sequential-thinking"]
    },
    "perforce-p4": {
      "command": "/PATH/TO/YOUR/bin/p4-mcp-start.sh",
      "args": [
        "--toolsets", "files", "changelists", "shelves", "workspaces", "jobs", "reviews"
      ],
      "env": {
        "P4PORT": "ssl:YOUR-P4-SERVER:1666",
        "P4USER": "YOUR_USERNAME",
        "PATH": "/YOUR/HOME/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
      }
    },
    "p4-workflow": {
      "command": "python3",
      "args": ["/PATH/TO/YOUR/bin/p4-workflow/server.py"],
      "env": {
        "PYTHONPATH": "/PATH/TO/YOUR/bin/p4-workflow",
        "PATH": "/YOUR/HOME/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
      }
    }
  }
}
```

### Step 6: Restart your IDE

Close and reopen your IDE. The MCP servers will start automatically.

### Step 7: Verify

In your IDE's AI chat, try:

```
List my pending changelists
```

or

```
Create a changelist for bug CSCxx12345 on workspace 7_4_1_MAIN
```

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
| `update_review` | Re-shelve code changes — Swarm auto-versions |
| `raise_review` | Shelve + create a new Swarm review (one call) |
| `add_review_comment` | Add a comment to a Swarm review |

---

## Supported Workspaces

The p4-workflow server auto-detects the workspace from the changelist. Works with any workspace that follows the `{username}_{branch}` naming convention:

- `7_4_1_MAIN`
- `IMS_7_7_MAIN`
- `ims_10_10_MAIN`
- `IMS_10_5_MAIN`
- `new_ims_7_g_main`
- `7_2_MR`
- _(any other workspace)_

---

## Troubleshooting

**MCP servers not showing in your IDE?**
- Check `~/.cursor/mcp.json` is valid JSON (no trailing commas)
- Restart IDE completely (Cmd+Q, reopen)

**"Connect to server failed"?**
- Run `p4 login` in terminal to refresh your ticket
- Verify P4PORT: `p4 -p ssl:YOUR-SERVER:1666 info`

**p4-workflow "module not found"?**
- Ensure `pip3 install -r requirements.txt` completed successfully
- Check PYTHONPATH in mcp.json points to the directory containing server.py

**"No open files found in changelist"?**
- Use `checkout_file` tool first before `update_review`

---

## File Structure

```
agentic-ide-p4-mcp-setup/
  README.md              <- You are here
  setup.sh               <- Automated installer
  mcp.json.template      <- Template for ~/.cursor/mcp.json
  perforce-p4/
    p4-mcp-start.sh      <- Wrapper script for official MCP server
  p4-workflow/
    server.py             <- Custom workflow MCP server
    requirements.txt      <- Python dependencies
```
