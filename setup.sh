#!/bin/bash
set -euo pipefail

# ── Agentic IDE Perforce MCP Setup ────────────────────────────────────────────────
# One-click installer: run this once and everything works.
#
# What it does:
#   1. Verifies prerequisites (p4 CLI, p4-mcp-server, Python, pip packages)
#   2. Tests Perforce connectivity
#   3. Authenticates and saves password to macOS Keychain (auto-login forever)
#   4. Generates ~/.cursor/mcp.json pointing to this repo
#   5. Installs Cursor rules for seamless P4 workflow
#
# Architecture: scripts run directly from this repo. All config is passed
# as environment variables via mcp.json. No copies, no placeholders.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BOLD='\033[1m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
NC='\033[0m'

ok()   { echo -e "  ${GREEN}✓${NC} $*"; }
warn() { echo -e "  ${YELLOW}⚠${NC} $*"; }
fail() { echo -e "  ${RED}✗${NC} $*"; }
step() { echo -e "\n${BOLD}[$1]${NC} $2"; }

echo ""
echo -e "${BOLD}════════════════════════════════════════════════${NC}"
echo -e "${BOLD}  Agentic IDE — Perforce & Swarm MCP Setup${NC}"
echo -e "${BOLD}════════════════════════════════════════════════${NC}"
echo ""

# ── Gather config ─────────────────────────────────────────────────────────────
read -rp "Perforce username (P4USER): " P4USER
[[ -z "$P4USER" ]] && { fail "P4USER is required."; exit 1; }

read -rp "Perforce server (P4PORT) [ssl:sbg-perforce.esl.cisco.com:1666]: " P4PORT
P4PORT="${P4PORT:-ssl:sbg-perforce.esl.cisco.com:1666}"

read -rp "Default workspace short name (e.g. 7_4_1_MAIN): " DEFAULT_WS
[[ -z "$DEFAULT_WS" ]] && { fail "Workspace name is required."; exit 1; }
P4CLIENT_DEFAULT="${P4USER}_${DEFAULT_WS}"

read -rp "Swarm URL [https://sp4-fp-swarm.cisco.com]: " SWARM_URL
SWARM_URL="${SWARM_URL:-https://sp4-fp-swarm.cisco.com}"

echo ""
echo -e "${BOLD}Configuration:${NC}"
echo "  P4USER           = $P4USER"
echo "  P4PORT           = $P4PORT"
echo "  Default Client   = $P4CLIENT_DEFAULT"
echo "  Swarm URL        = $SWARM_URL"
echo "  Repo (scripts)   = $SCRIPT_DIR"
echo ""
read -rp "Proceed? (y/n): " CONFIRM
[[ "$CONFIRM" != "y" && "$CONFIRM" != "Y" ]] && { echo "Aborted."; exit 0; }

# ── Step 1: Prerequisites ────────────────────────────────────────────────────
step "1/7" "Checking prerequisites..."

P4_BIN=""
if command -v p4 &>/dev/null; then
    P4_BIN="$(command -v p4)"
elif [[ -x "$HOME/bin/p4" ]]; then
    P4_BIN="$HOME/bin/p4"
fi

if [[ -z "$P4_BIN" ]]; then
    fail "p4 CLI not found."
    echo "  Install:  brew install --cask perforce"
    echo "  Or:       https://www.perforce.com/downloads/helix-command-line-client-p4"
    exit 1
fi
ok "p4 CLI: $P4_BIN"

P4_MCP_BIN=""
for dir in "$HOME"/bin/p4-mcp-server*; do
    if [[ -x "$dir/p4-mcp-server" ]]; then
        P4_MCP_BIN="$dir/p4-mcp-server"
        break
    fi
done

if [[ -z "$P4_MCP_BIN" ]]; then
    warn "p4-mcp-server not found in ~/bin/"
    echo "  Download from: https://www.perforce.com/downloads (search 'Helix MCP Server')"
    read -rp "  Enter full path to p4-mcp-server binary (or 'skip'): " MCP_PATH
    if [[ "$MCP_PATH" == "skip" ]]; then
        warn "Skipping perforce-p4 server. You can configure it later."
    elif [[ -x "$MCP_PATH" ]]; then
        P4_MCP_BIN="$MCP_PATH"
        ok "p4-mcp-server: $P4_MCP_BIN"
    else
        warn "Not found at $MCP_PATH. Skipping perforce-p4."
    fi
else
    ok "p4-mcp-server: $P4_MCP_BIN"
fi

if ! command -v python3 &>/dev/null; then
    fail "Python3 not found. Install: brew install python3"
    exit 1
fi
ok "Python: $(python3 --version 2>&1)"

# ── Step 2: Python dependencies ──────────────────────────────────────────────
step "2/7" "Installing Python dependencies..."
pip3 install --quiet -r "$SCRIPT_DIR/p4-workflow/requirements.txt" 2>&1 | tail -1
ok "fastmcp + httpx installed"

# ── Step 3: Test Perforce connectivity ───────────────────────────────────────
step "3/7" "Testing Perforce connectivity..."
export P4PORT P4USER
if "$P4_BIN" -p "$P4PORT" -u "$P4USER" info &>/dev/null; then
    ok "Connected to $P4PORT"
else
    warn "Cannot reach $P4PORT — check VPN. Setup will continue."
fi

# ── Step 4: Authenticate + save to Keychain ──────────────────────────────────
step "4/7" "Setting up authentication (Keychain auto-login)..."

KEYCHAIN_SERVICE="p4-workflow"
NEED_LOGIN=true

if "$P4_BIN" login -s &>/dev/null; then
    ok "Already logged in: $("$P4_BIN" login -s 2>&1 | head -1)"
    NEED_LOGIN=false
fi

KC_EXISTS=false
if security find-generic-password -a "$P4USER" -s "$KEYCHAIN_SERVICE" -w &>/dev/null; then
    KC_EXISTS=true
fi

if [[ "$NEED_LOGIN" == "true" ]] && [[ "$KC_EXISTS" == "true" ]]; then
    KC_PASS=$(security find-generic-password -a "$P4USER" -s "$KEYCHAIN_SERVICE" -w 2>/dev/null)
    if echo "$KC_PASS" | "$P4_BIN" login &>/dev/null; then
        ok "Auto-logged in from Keychain"
        NEED_LOGIN=false
    else
        warn "Keychain password is stale. Need to update."
        KC_EXISTS=false
    fi
fi

if [[ "$KC_EXISTS" == "false" ]]; then
    echo ""
    echo "  To enable permanent auto-login, enter your Perforce password."
    echo "  It will be stored in macOS Keychain (secure, never on disk)."
    echo "  Press Enter to skip (you'll need to run 'p4 login' manually)."
    echo ""
    read -rsp "  Perforce password: " P4_PASS
    echo ""

    if [[ -n "$P4_PASS" ]]; then
        security delete-generic-password -a "$P4USER" -s "$KEYCHAIN_SERVICE" &>/dev/null || true
        if security add-generic-password -a "$P4USER" -s "$KEYCHAIN_SERVICE" -w "$P4_PASS"; then
            ok "Password saved to Keychain (service: $KEYCHAIN_SERVICE)"
        else
            warn "Failed to save to Keychain. You can use save_p4_password tool later."
        fi

        if echo "$P4_PASS" | "$P4_BIN" login &>/dev/null; then
            ok "Logged in successfully"
            NEED_LOGIN=false
        else
            warn "Login failed — check your password. You can fix this later."
        fi
    else
        warn "Skipped Keychain setup. Run save_p4_password tool or 'p4 login' to authenticate."
    fi
fi

if [[ "$NEED_LOGIN" == "true" ]]; then
    warn "Not logged in. Run 'p4 login' or use the save_p4_password tool after setup."
fi

# ── Step 5: Make scripts executable ──────────────────────────────────────────
step "5/7" "Preparing scripts..."
chmod +x "$SCRIPT_DIR/perforce-p4/p4-mcp-start.sh"
ok "perforce-p4/p4-mcp-start.sh"
ok "p4-workflow/server.py"

# ── Step 6: Generate ~/.cursor/mcp.json ──────────────────────────────────────
step "6/7" "Generating Cursor MCP config..."
MCP_JSON="$HOME/.cursor/mcp.json"
mkdir -p "$HOME/.cursor"

P4_DIR="$(dirname "$P4_BIN")"

if [[ -f "$MCP_JSON" ]]; then
    BACKUP="$MCP_JSON.backup.$(date +%Y%m%d%H%M%S)"
    cp "$MCP_JSON" "$BACKUP"
    ok "Backed up existing config to: $BACKUP"
fi

cat > "$MCP_JSON" << MCPEOF
{
  "mcpServers": {
    "sequential-thinking": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-sequential-thinking"]
    },
    "perforce-p4": {
      "command": "$SCRIPT_DIR/perforce-p4/p4-mcp-start.sh",
      "args": [
        "--toolsets", "files", "changelists", "shelves", "workspaces", "jobs", "reviews"
      ],
      "env": {
        "P4PORT": "$P4PORT",
        "P4USER": "$P4USER",
        "P4CLIENT_DEFAULT": "$P4CLIENT_DEFAULT",
        "P4_BIN": "$P4_BIN",
        "P4_MCP_SERVER": "${P4_MCP_BIN:-}",
        "PATH": "$P4_DIR:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
      },
      "alwaysAllow": []
    },
    "p4-workflow": {
      "command": "python3",
      "args": ["$SCRIPT_DIR/p4-workflow/server.py"],
      "env": {
        "P4PORT": "$P4PORT",
        "P4USER": "$P4USER",
        "P4_BIN": "$P4_BIN",
        "SWARM_URL": "$SWARM_URL",
        "PYTHONPATH": "$SCRIPT_DIR/p4-workflow",
        "PATH": "$P4_DIR:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
      },
      "alwaysAllow": []
    }
  }
}
MCPEOF
ok "Created: $MCP_JSON"

# ── Step 7: Install Cursor rules for P4 workflow ────────────────────────────
step "7/7" "Installing Cursor rules..."
RULES_DIR="$HOME/.cursor/rules"
mkdir -p "$RULES_DIR"

if [[ -f "$SCRIPT_DIR/rules/p4-workflow.mdc" ]]; then
    cp "$SCRIPT_DIR/rules/p4-workflow.mdc" "$RULES_DIR/p4-workflow.mdc"
    ok "Installed: $RULES_DIR/p4-workflow.mdc"
else
    warn "No rules file found at $SCRIPT_DIR/rules/p4-workflow.mdc — skipping."
fi

# ── Done ─────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}════════════════════════════════════════════════${NC}"
echo -e "${GREEN}${BOLD}  Setup Complete!${NC}"
echo -e "${BOLD}════════════════════════════════════════════════${NC}"
echo ""
echo "Next steps:"
echo "  1. Restart your IDE (Cmd+Q, then reopen)"
echo "  2. Test: ask your AI 'List my pending changelists'"
echo ""
echo "Scripts (run from this repo — no copies):"
echo "  $SCRIPT_DIR/perforce-p4/p4-mcp-start.sh"
echo "  $SCRIPT_DIR/p4-workflow/server.py"
echo ""
echo "Config:"
echo "  $MCP_JSON"
if [[ -f "$RULES_DIR/p4-workflow.mdc" ]]; then
    echo "  $RULES_DIR/p4-workflow.mdc"
fi
echo ""
