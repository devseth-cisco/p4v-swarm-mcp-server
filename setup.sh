#!/bin/bash
set -euo pipefail

# ── Agentic IDE Perforce MCP Setup ────────────────────────────────────────────────
# Interactive installer for perforce-p4 and p4-workflow MCP servers.
# Run: chmod +x setup.sh && ./setup.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "========================================"
echo " Agentic IDE Perforce MCP Server Setup"
echo "========================================"
echo ""

# ── Gather user config ─────────────────────────────────────────────────────
read -rp "Perforce username (P4USER): " P4USER
read -rp "Perforce server (P4PORT) [ssl:sbg-perforce.esl.cisco.com:1666]: " P4PORT
P4PORT="${P4PORT:-ssl:sbg-perforce.esl.cisco.com:1666}"

read -rp "Default workspace name (e.g. 7_4_1_MAIN): " DEFAULT_WS
DEFAULT_CLIENT="${P4USER}_${DEFAULT_WS}"

read -rp "Swarm URL [https://sp4-fp-swarm.cisco.com]: " SWARM_URL
SWARM_URL="${SWARM_URL:-https://sp4-fp-swarm.cisco.com}"

INSTALL_DIR="$HOME/bin"
read -rp "Install directory [$INSTALL_DIR]: " INPUT_DIR
INSTALL_DIR="${INPUT_DIR:-$INSTALL_DIR}"

echo ""
echo "Configuration:"
echo "  P4USER          = $P4USER"
echo "  P4PORT          = $P4PORT"
echo "  Default Client  = $DEFAULT_CLIENT"
echo "  Swarm URL       = $SWARM_URL"
echo "  Install Dir     = $INSTALL_DIR"
echo ""
read -rp "Proceed? (y/n): " CONFIRM
if [[ "$CONFIRM" != "y" && "$CONFIRM" != "Y" ]]; then
    echo "Aborted."
    exit 0
fi

mkdir -p "$INSTALL_DIR"

# ── Step 1: Check p4 CLI ──────────────────────────────────────────────────
echo ""
echo "[1/6] Checking p4 CLI..."
P4_BIN=""
if command -v p4 &>/dev/null; then
    P4_BIN="$(command -v p4)"
    echo "  Found: $P4_BIN"
elif [[ -x "$INSTALL_DIR/p4" ]]; then
    P4_BIN="$INSTALL_DIR/p4"
    echo "  Found: $P4_BIN"
else
    echo "  ERROR: p4 CLI not found."
    echo "  Install it:"
    echo "    macOS:  brew install --cask perforce"
    echo "    Manual: https://www.perforce.com/downloads/helix-command-line-client-p4"
    echo "  Then re-run this script."
    exit 1
fi

# ── Step 2: Check p4-mcp-server ────────────────────────────────────────────
echo ""
echo "[2/6] Checking p4-mcp-server..."
P4_MCP_BIN=""
for dir in "$INSTALL_DIR"/p4-mcp-server*; do
    if [[ -x "$dir/p4-mcp-server" ]]; then
        P4_MCP_BIN="$dir/p4-mcp-server"
        break
    fi
done

if [[ -z "$P4_MCP_BIN" ]]; then
    echo "  p4-mcp-server not found in $INSTALL_DIR/"
    echo ""
    echo "  Download it from Perforce:"
    echo "    https://www.perforce.com/downloads"
    echo "    Search for 'Helix MCP Server' for your platform."
    echo ""
    echo "  Extract and place the binary at:"
    echo "    $INSTALL_DIR/p4-mcp-server/p4-mcp-server"
    echo ""
    read -rp "  Have you placed it? Enter full path to p4-mcp-server binary (or 'skip'): " MCP_PATH
    if [[ "$MCP_PATH" == "skip" ]]; then
        echo "  Skipping perforce-p4 server setup. You can configure it later."
        P4_MCP_BIN=""
    elif [[ -x "$MCP_PATH" ]]; then
        P4_MCP_BIN="$MCP_PATH"
    else
        echo "  Binary not found at $MCP_PATH. Skipping perforce-p4 setup."
        P4_MCP_BIN=""
    fi
else
    echo "  Found: $P4_MCP_BIN"
fi

# ── Step 3: Install p4-mcp-start.sh wrapper ────────────────────────────────
echo ""
echo "[3/6] Installing p4-mcp-start.sh wrapper..."
WRAPPER="$INSTALL_DIR/p4-mcp-start.sh"
sed \
    -e "s|__P4PORT__|$P4PORT|g" \
    -e "s|__P4USER__|$P4USER|g" \
    -e "s|__P4CLIENT_DEFAULT__|$DEFAULT_CLIENT|g" \
    -e "s|__P4_BIN__|$P4_BIN|g" \
    -e "s|__P4_MCP_SERVER__|${P4_MCP_BIN:-\$HOME/bin/p4-mcp-server/p4-mcp-server}|g" \
    "$SCRIPT_DIR/perforce-p4/p4-mcp-start.sh" > "$WRAPPER"
chmod +x "$WRAPPER"
echo "  Created: $WRAPPER"

# ── Step 4: Install p4-workflow Python dependencies ─────────────────────────
echo ""
echo "[4/6] Installing Python dependencies for p4-workflow..."
pip3 install --quiet -r "$SCRIPT_DIR/p4-workflow/requirements.txt"
echo "  Done."

# ── Step 5: Install p4-workflow server.py ───────────────────────────────────
echo ""
echo "[5/6] Installing p4-workflow server..."
WORKFLOW_DIR="$INSTALL_DIR/p4-workflow"
mkdir -p "$WORKFLOW_DIR"
sed \
    -e "s|__P4_BIN__|$P4_BIN|g" \
    -e "s|__P4PORT__|$P4PORT|g" \
    -e "s|__P4USER__|$P4USER|g" \
    -e "s|__SWARM_URL__|$SWARM_URL|g" \
    "$SCRIPT_DIR/p4-workflow/server.py" > "$WORKFLOW_DIR/server.py"
chmod +x "$WORKFLOW_DIR/server.py"
echo "  Created: $WORKFLOW_DIR/server.py"

# ── Step 6: Generate ~/.cursor/mcp.json ─────────────────────────────────────
echo ""
echo "[6/6] Generating Agentic IDE MCP config..."
MCP_JSON="$HOME/.cursor/mcp.json"
mkdir -p "$HOME/.cursor"

if [[ -f "$MCP_JSON" ]]; then
    BACKUP="$MCP_JSON.backup.$(date +%Y%m%d%H%M%S)"
    cp "$MCP_JSON" "$BACKUP"
    echo "  Backed up existing config to: $BACKUP"
fi

cat > "$MCP_JSON" << MCPEOF
{
  "mcpServers": {
    "sequential-thinking": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-sequential-thinking"]
    },
    "perforce-p4": {
      "command": "$WRAPPER",
      "args": [
        "--toolsets", "files", "changelists", "shelves", "workspaces", "jobs", "reviews"
      ],
      "env": {
        "P4PORT": "$P4PORT",
        "P4USER": "$P4USER",
        "PATH": "$INSTALL_DIR:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
      }
    },
    "p4-workflow": {
      "command": "python3",
      "args": ["$WORKFLOW_DIR/server.py"],
      "env": {
        "PYTHONPATH": "$WORKFLOW_DIR",
        "PATH": "$INSTALL_DIR:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
      }
    }
  }
}
MCPEOF
echo "  Created: $MCP_JSON"

# ── Done ─────────────────────────────────────────────────────────────────────
echo ""
echo "========================================"
echo " Setup Complete!"
echo "========================================"
echo ""
echo "Next steps:"
echo "  1. Make sure you're logged in:  p4 login"
echo "  2. Restart your IDE (Cmd+Q, then reopen)"
echo "  3. Test in your IDE chat:  'List my pending changelists'"
echo ""
echo "Config files created:"
echo "  $WRAPPER"
echo "  $WORKFLOW_DIR/server.py"
echo "  $MCP_JSON"
echo ""
