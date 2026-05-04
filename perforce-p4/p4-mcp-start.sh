#!/bin/zsh
# Wrapper for p4-mcp-server that:
#   1. Sets P4PORT / P4USER / P4CLIENT / P4TICKETS from environment
#   2. Auto-refreshes expired tickets: Keychain -> SAML browser (zero-touch)
#   3. Guards against P4CLIENT=none from stale .p4enviro
#
# Required env:  P4PORT, P4USER
# Optional env:  P4CLIENT_DEFAULT, P4_BIN, P4_MCP_SERVER, P4TICKETS

export P4PORT="${P4PORT:?P4PORT must be set}"
export P4USER="${P4USER:?P4USER must be set}"
export P4TICKETS="${P4TICKETS:-$HOME/.p4tickets}"

P4_BIN="${P4_BIN:-$(command -v p4 2>/dev/null || echo "$HOME/bin/p4")}"
P4_MCP_SERVER="${P4_MCP_SERVER:-$(echo "$HOME"/bin/p4-mcp-server*/p4-mcp-server)}"
P4CLIENT_DEFAULT="${P4CLIENT_DEFAULT:-${P4USER}_7_4_1_MAIN}"

# ── Resolve P4CLIENT (portable: no grep -P on macOS) ────────────────────────
ACTIVE_CLIENT=$("$P4_BIN" set P4CLIENT 2>/dev/null | sed -n 's/^P4CLIENT=\([^ ]*\).*/\1/p' | head -1)

if [[ "$ACTIVE_CLIENT" == "none" || "$ACTIVE_CLIENT" == "(config)" || -z "$ACTIVE_CLIENT" ]]; then
    ACTIVE_CLIENT=""
fi

export P4CLIENT="${ACTIVE_CLIENT:-$P4CLIENT_DEFAULT}"

# ── Auto-login: Keychain first, then SAML with auto-browser-open ────────────
# SAML browser-open is coordinated with p4-workflow/server.py via a shared
# lock file at /tmp/p4-saml-${P4USER}.lock so Cursor only ever opens ONE
# browser tab per launch even though both MCP servers start in parallel.
if ! "$P4_BIN" login -s >/dev/null 2>&1; then
    KC_PASS=$(security find-generic-password -a "$P4USER" -s "p4-workflow" -w 2>/dev/null)
    if [[ -n "$KC_PASS" ]]; then
        echo "$KC_PASS" | "$P4_BIN" login >/dev/null 2>&1
    fi

    if ! "$P4_BIN" login -s >/dev/null 2>&1; then
        SAML_LOCK="/tmp/p4-saml-${P4USER}.lock"
        # Critical section: only one process opens the SAML browser tab
        if command -v lockf >/dev/null 2>&1; then
            P4_BIN="$P4_BIN" lockf -k -t 180 "$SAML_LOCK" zsh -c '
                # Re-check inside the lock: a sibling MCP server may have
                # just finished SAML login while we were waiting.
                if "$P4_BIN" login -s >/dev/null 2>&1; then
                    exit 0
                fi
                "$P4_BIN" login 2>&1 | while IFS= read -r line; do
                    case "$line" in
                        *"Navigate to URL:"*)
                            open "${line#*Navigate to URL: }" ;;
                    esac
                done
            ' >/dev/null 2>&1 || true
        else
            "$P4_BIN" login 2>&1 | while IFS= read -r line; do
                case "$line" in
                    *"Navigate to URL:"*)
                        open "${line#*Navigate to URL: }" ;;
                esac
            done
        fi
    fi
fi

exec "$P4_MCP_SERVER" "$@"
