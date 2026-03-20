#!/bin/bash
set -euo pipefail

# ── Agentic IDE Perforce MCP Setup ────────────────────────────────────────────────
# TRUE zero-to-working installer. Handles everything from a bare macOS machine:
#
#   1. Homebrew          (auto-install if missing)
#   2. p4 CLI            (download from Perforce CDN, fallback to brew)
#   3. Python 3          (brew install)
#   4. Node.js           (brew install — needed for sequential-thinking MCP)
#   5. p4-mcp-server     (guided download — Perforce auth required)
#   6. Python deps       (fastmcp, httpx)
#   7. Auth              (P4 login + macOS Keychain storage)
#   8. ~/.cursor/mcp.json (generated, pointing to this repo)
#   9. Cursor rules      (workflow guidance installed globally)
#
# Architecture: scripts run directly from this repo. All config is passed
# as environment variables via mcp.json. No copies, no placeholders.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTALL_DIR="$HOME/bin"
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

mkdir -p "$INSTALL_DIR"

# ═══════════════════════════════════════════════════════════════════════════════
# Step 1: Homebrew
# ═══════════════════════════════════════════════════════════════════════════════
step "1/9" "Checking Homebrew..."
if command -v brew &>/dev/null; then
    ok "Homebrew: $(brew --prefix)"
else
    warn "Homebrew not found — installing..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    # Add brew to current session PATH
    if [[ -x /opt/homebrew/bin/brew ]]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
    elif [[ -x /usr/local/bin/brew ]]; then
        eval "$(/usr/local/bin/brew shellenv)"
    fi
    ok "Homebrew installed"
fi

# ═══════════════════════════════════════════════════════════════════════════════
# Step 2: p4 CLI
# ═══════════════════════════════════════════════════════════════════════════════
step "2/9" "Checking p4 CLI..."
P4_BIN=""
if command -v p4 &>/dev/null; then
    P4_BIN="$(command -v p4)"
elif [[ -x "$INSTALL_DIR/p4" ]]; then
    P4_BIN="$INSTALL_DIR/p4"
fi

if [[ -z "$P4_BIN" ]]; then
    warn "p4 CLI not found — installing..."
    ARCH="$(uname -m)"
    P4_URL=""
    if [[ "$ARCH" == "arm64" ]]; then
        P4_URL="https://cdist2.perforce.com/perforce/r24.2/bin.macosx13arm64/p4"
    else
        P4_URL="https://cdist2.perforce.com/perforce/r24.2/bin.macosx13x86_64/p4"
    fi
    if curl -fsSL "$P4_URL" -o "$INSTALL_DIR/p4" 2>/dev/null; then
        chmod +x "$INSTALL_DIR/p4"
        P4_BIN="$INSTALL_DIR/p4"
        ok "p4 CLI downloaded to $P4_BIN"
    else
        warn "Direct download failed. Trying Homebrew..."
        brew install --cask perforce 2>/dev/null || true
        if command -v p4 &>/dev/null; then
            P4_BIN="$(command -v p4)"
            ok "p4 CLI: $P4_BIN"
        else
            fail "Could not install p4 CLI. Install manually:"
            echo "    brew install --cask perforce"
            echo "    OR: https://www.perforce.com/downloads/helix-command-line-client-p4"
            exit 1
        fi
    fi
else
    ok "p4 CLI: $P4_BIN"
fi

# ═══════════════════════════════════════════════════════════════════════════════
# Step 3: Python 3
# ═══════════════════════════════════════════════════════════════════════════════
step "3/9" "Checking Python 3..."
if command -v python3 &>/dev/null; then
    ok "Python: $(python3 --version 2>&1)"
else
    warn "Python3 not found — installing via Homebrew..."
    brew install python3
    ok "Python: $(python3 --version 2>&1)"
fi

# ═══════════════════════════════════════════════════════════════════════════════
# Step 4: Node.js (for npx / sequential-thinking MCP)
# ═══════════════════════════════════════════════════════════════════════════════
step "4/9" "Checking Node.js..."
if command -v npx &>/dev/null; then
    ok "Node.js: $(node --version 2>&1)"
else
    warn "Node.js not found — installing via Homebrew..."
    brew install node
    ok "Node.js: $(node --version 2>&1)"
fi

# ═══════════════════════════════════════════════════════════════════════════════
# Step 5: p4-mcp-server binary
# ═══════════════════════════════════════════════════════════════════════════════
step "5/9" "Checking p4-mcp-server..."
P4_MCP_BIN=""
for dir in "$INSTALL_DIR"/p4-mcp-server*; do
    if [[ -x "$dir/p4-mcp-server" ]]; then
        P4_MCP_BIN="$dir/p4-mcp-server"
        break
    fi
done

if [[ -z "$P4_MCP_BIN" ]]; then
    warn "p4-mcp-server not found."
    echo ""
    echo "  The Perforce MCP Server binary must be downloaded manually"
    echo "  (Perforce requires authentication for this download)."
    echo ""
    echo "  1. Go to: https://www.perforce.com/downloads"
    echo "  2. Search for 'Helix MCP Server'"
    echo "  3. Download the macOS binary for your architecture"
    echo "  4. Extract to: $INSTALL_DIR/p4-mcp-server/"
    echo ""
    read -rp "  Path to p4-mcp-server binary (or Enter to skip): " MCP_PATH
    if [[ -n "$MCP_PATH" && -x "$MCP_PATH" ]]; then
        P4_MCP_BIN="$MCP_PATH"
        ok "p4-mcp-server: $P4_MCP_BIN"
    elif [[ -n "$MCP_PATH" ]]; then
        warn "Not found or not executable at $MCP_PATH. Skipping."
        warn "The p4-workflow server will still work. perforce-p4 needs this binary."
    else
        warn "Skipped. p4-workflow will work. perforce-p4 needs this binary."
    fi
else
    ok "p4-mcp-server: $P4_MCP_BIN"
fi

# ═══════════════════════════════════════════════════════════════════════════════
# Step 6: Python dependencies
# ═══════════════════════════════════════════════════════════════════════════════
step "6/9" "Installing Python dependencies..."
PIP_ARGS=(--quiet -r "$SCRIPT_DIR/p4-workflow/requirements.txt")
if pip3 install "${PIP_ARGS[@]}" 2>/dev/null; then
    ok "fastmcp + httpx installed"
else
    warn "Standard pip install failed, retrying with --break-system-packages..."
    pip3 install --break-system-packages "${PIP_ARGS[@]}"
    ok "fastmcp + httpx installed"
fi

# ═══════════════════════════════════════════════════════════════════════════════
# Step 7: Authenticate + Keychain
# ═══════════════════════════════════════════════════════════════════════════════
step "7/9" "Setting up authentication..."

export P4PORT P4USER
KEYCHAIN_SERVICE="p4-workflow"
NEED_LOGIN=true

echo "  Testing connectivity to $P4PORT..."
if "$P4_BIN" -p "$P4PORT" -u "$P4USER" info &>/dev/null; then
    ok "Connected to $P4PORT"
else
    warn "Cannot reach $P4PORT — check VPN. Auth setup will continue."
fi

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
    echo "  It will be stored in macOS Keychain (secure, never written to disk)."
    echo "  Press Enter to skip (you can use save_p4_password tool later)."
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
            warn "Login failed — check your password. You can fix this later with save_p4_password tool."
        fi
    else
        warn "Skipped. Use save_p4_password tool or 'p4 login' after setup."
    fi
fi

if [[ "$NEED_LOGIN" == "true" ]]; then
    warn "Not logged in. Use save_p4_password tool or 'p4 login' after setup."
fi

# ═══════════════════════════════════════════════════════════════════════════════
# Step 8: Generate ~/.cursor/mcp.json
# ═══════════════════════════════════════════════════════════════════════════════
step "8/9" "Generating Cursor MCP config..."

chmod +x "$SCRIPT_DIR/perforce-p4/p4-mcp-start.sh"

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

# ═══════════════════════════════════════════════════════════════════════════════
# Step 9: Install Cursor rules and skills
# ═══════════════════════════════════════════════════════════════════════════════
step "9/9" "Installing Cursor rules and skills..."

RULES_DIR="$HOME/.cursor/rules"
SKILLS_DIR="$HOME/.cursor/skills/p4-workflow"
mkdir -p "$RULES_DIR" "$SKILLS_DIR"

if [[ -f "$SCRIPT_DIR/rules/p4-workflow.mdc" ]]; then
    cp "$SCRIPT_DIR/rules/p4-workflow.mdc" "$RULES_DIR/p4-workflow.mdc"
    ok "Rule:  $RULES_DIR/p4-workflow.mdc"
else
    warn "No rules file at $SCRIPT_DIR/rules/p4-workflow.mdc — skipping."
fi

if [[ -f "$SCRIPT_DIR/skills/p4-workflow/SKILL.md" ]]; then
    cp "$SCRIPT_DIR/skills/p4-workflow/SKILL.md" "$SKILLS_DIR/SKILL.md"
    ok "Skill: $SKILLS_DIR/SKILL.md"
else
    warn "No skill file at $SCRIPT_DIR/skills/p4-workflow/SKILL.md — skipping."
fi

# ═══════════════════════════════════════════════════════════════════════════════
# Done
# ═══════════════════════════════════════════════════════════════════════════════
echo ""
echo -e "${BOLD}════════════════════════════════════════════════${NC}"
echo -e "${GREEN}${BOLD}  Setup Complete!${NC}"
echo -e "${BOLD}════════════════════════════════════════════════${NC}"
echo ""
echo "What was installed:"
echo "  p4 CLI:          $P4_BIN"
[[ -n "${P4_MCP_BIN:-}" ]] && echo "  p4-mcp-server:   $P4_MCP_BIN"
echo "  Python deps:     fastmcp, httpx"
echo "  MCP config:      $MCP_JSON"
echo "  Cursor rule:     $RULES_DIR/p4-workflow.mdc"
echo "  Cursor skill:    $SKILLS_DIR/SKILL.md"
echo ""
echo "Next steps:"
echo "  1. Restart your IDE (Cmd+Q, then reopen)"
echo "  2. Test: ask your AI 'List my pending changelists'"
echo ""
