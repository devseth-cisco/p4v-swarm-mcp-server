#!/bin/zsh
# Wrapper for p4-mcp-server that dynamically reads the active P4CLIENT.
# To switch workspaces: run `p4 set P4CLIENT=<workspace>` then restart your IDE.
#
# Placeholders are replaced by setup.sh:
#   __P4PORT__            -> your Perforce server
#   __P4USER__            -> your Perforce username
#   __P4CLIENT_DEFAULT__  -> fallback workspace name
#   __P4_BIN__            -> path to p4 CLI binary
#   __P4_MCP_SERVER__     -> path to p4-mcp-server binary

export P4PORT="${P4PORT:-__P4PORT__}"
export P4USER="${P4USER:-__P4USER__}"

# Read active P4CLIENT from `p4 set`, fall back to default
ACTIVE_CLIENT=$(__P4_BIN__ set P4CLIENT 2>/dev/null | grep -oP 'P4CLIENT=\K[^\s]+' | head -1)
if [[ -n "$ACTIVE_CLIENT" ]]; then
    export P4CLIENT="$ACTIVE_CLIENT"
else
    export P4CLIENT="__P4CLIENT_DEFAULT__"
fi

exec __P4_MCP_SERVER__ "$@"
