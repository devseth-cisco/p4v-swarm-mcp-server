#!/bin/zsh
# Wrapper for p4-mcp-server that:
#   1. Sets P4PORT / P4USER / P4CLIENT from environment (passed by mcp.json)
#   2. Auto-refreshes expired tickets from macOS Keychain
#   3. Guards against P4CLIENT=none from stale .p4enviro
#
# All config comes from environment variables — no hardcoded placeholders.
# Required env:  P4PORT, P4USER
# Optional env:  P4CLIENT_DEFAULT, P4_BIN, P4_MCP_SERVER

export P4PORT="${P4PORT:?P4PORT must be set}"
export P4USER="${P4USER:?P4USER must be set}"

P4_BIN="${P4_BIN:-$(command -v p4 2>/dev/null || echo "$HOME/bin/p4")}"
P4_MCP_SERVER="${P4_MCP_SERVER:-$(echo "$HOME"/bin/p4-mcp-server*/p4-mcp-server)}"
P4CLIENT_DEFAULT="${P4CLIENT_DEFAULT:-${P4USER}_7_4_1_MAIN}"

# ── Resolve P4CLIENT (portable: no grep -P on macOS) ────────────────────────
ACTIVE_CLIENT=$("$P4_BIN" set P4CLIENT 2>/dev/null | sed -n 's/^P4CLIENT=\([^ ]*\).*/\1/p' | head -1)

if [[ "$ACTIVE_CLIENT" == "none" || "$ACTIVE_CLIENT" == "(config)" || -z "$ACTIVE_CLIENT" ]]; then
    ACTIVE_CLIENT=""
fi

export P4CLIENT="${ACTIVE_CLIENT:-$P4CLIENT_DEFAULT}"

# ── Auto-login from Keychain if ticket is expired ────────────────────────────
if ! "$P4_BIN" login -s >/dev/null 2>&1; then
    KC_PASS=$(security find-generic-password -a "$P4USER" -s "p4-workflow" -w 2>/dev/null)
    if [[ -n "$KC_PASS" ]]; then
        echo "$KC_PASS" | "$P4_BIN" login >/dev/null 2>&1
    fi
fi

exec "$P4_MCP_SERVER" "$@"
