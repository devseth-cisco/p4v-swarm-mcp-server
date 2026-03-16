#!/usr/bin/env python3
"""
p4-workflow -- Single source of truth for all Perforce + Swarm workflow operations.

All config is read from environment variables (set by mcp.json):
  P4_BIN      -- path to p4 CLI          (default: p4 on PATH or ~/bin/p4)
  P4PORT      -- Perforce server          (required)
  P4USER      -- Perforce username        (required)
  SWARM_URL   -- Swarm base URL           (default: https://sp4-fp-swarm.cisco.com)

Auth architecture:
  1. Startup: validate ticket or auto-login from Keychain; warm Swarm ticket cache
  2. Runtime: every _p4() call auto-retries on auth failure via Keychain
  3. Swarm: ticket cached 20h; auto-refreshes on 401; extracted from `p4 login -p`
  4. Both servers share Keychain service "p4-workflow" / account = P4USER
"""
import logging
import os
import re
import shutil
import subprocess
import sys
import time
import warnings

import httpx

sys.path.insert(0, os.path.dirname(__file__))
from fastmcp import FastMCP

log = logging.getLogger("p4-workflow")

# ── Config (from environment — set by mcp.json env block) ───────────────────
P4_BIN  = os.environ.get("P4_BIN") or shutil.which("p4") or os.path.expanduser("~/bin/p4")
P4_PORT = os.environ["P4PORT"]
P4_USER = os.environ["P4USER"]

SWARM_URL = os.environ.get("SWARM_URL", "https://sp4-fp-swarm.cisco.com")
SWARM_API = f"{SWARM_URL}/api/v9"

_KEYCHAIN_SERVICE = "p4-workflow"

# ── Auth layer ──────────────────────────────────────────────────────────────
# Single auth subsystem shared by p4 commands and Swarm API calls.
# Keychain password is read ONCE per server lifetime and cached in-process.
# `save_p4_password` invalidates the cache so a fresh read happens next time.

_kc_cache: dict = {"password": None, "checked": False}

_TICKET_ERROR_SIGNALS = (
    "ticket has expired",
    "your session has expired",
    "password invalid",
    "p4passwd",
    "password (p4passwd)",
    "login required",
)


def _keychain_password(*, force_refresh: bool = False) -> str | None:
    """Read P4 password from macOS Keychain. Cached after first read."""
    if _kc_cache["checked"] and not force_refresh:
        return _kc_cache["password"]
    r = subprocess.run(
        ["security", "find-generic-password", "-a", P4_USER, "-s", _KEYCHAIN_SERVICE, "-w"],
        capture_output=True, text=True,
    )
    pw = r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None
    _kc_cache["password"] = pw
    _kc_cache["checked"] = True
    return pw


def _invalidate_kc_cache() -> None:
    _kc_cache["password"] = None
    _kc_cache["checked"] = False


def _p4_env(client: str | None = None) -> dict:
    """Build a clean env dict for p4 subprocesses."""
    env = os.environ.copy()
    env["P4PORT"] = P4_PORT
    env["P4USER"] = P4_USER
    if client:
        env["P4CLIENT"] = client
    return env


def _check_ticket() -> tuple[bool, str]:
    """Run `p4 login -s` once and return (is_valid, status_message)."""
    r = subprocess.run(
        [P4_BIN, "login", "-s"],
        capture_output=True, text=True, env=_p4_env(),
    )
    msg = r.stdout.strip() if r.returncode == 0 else (r.stderr or r.stdout).strip()
    return r.returncode == 0, msg


def _ticket_valid() -> bool:
    ok, _ = _check_ticket()
    return ok


def _ticket_status() -> str:
    _, msg = _check_ticket()
    return msg


def _do_login(password: str) -> bool:
    r = subprocess.run(
        [P4_BIN, "login"],
        input=password, capture_output=True, text=True, env=_p4_env(),
    )
    return r.returncode == 0


def _auto_login() -> bool:
    """Try Keychain-stored password. Returns True on success."""
    pwd = _keychain_password()
    if not pwd:
        return False
    return _do_login(pwd)


def _is_auth_error(msg: str) -> bool:
    lower = msg.lower()
    return any(s in lower for s in _TICKET_ERROR_SIGNALS)


def _ensure_auth() -> None:
    """Pre-flight: guarantee a valid ticket before first tool call.

    Called at server startup and can be called before any critical operation.
    Never raises — logs warnings instead so the server still starts.
    """
    ok, status = _check_ticket()
    if ok:
        log.info("Auth OK: %s", status)
        return
    log.warning("Ticket expired at startup, attempting auto-login from Keychain...")
    if _auto_login():
        _, status = _check_ticket()
        log.info("Auto-login succeeded: %s", status)
        return
    if _keychain_password() is None:
        log.warning(
            "No Keychain entry found. Run save_p4_password tool or `p4 login` in a terminal."
        )
    else:
        log.warning(
            "Keychain password exists but login failed (wrong password?). "
            "Run save_p4_password tool to update."
        )


# ── P4 command runner ────────────────────────────────────────────────────────
def _p4(*args: str, client: str | None = None) -> str:
    """Run a p4 command. Auto-retries once on auth failure via Keychain."""
    env = _p4_env(client)
    r = subprocess.run([P4_BIN, *args], capture_output=True, text=True, env=env)

    if r.returncode != 0:
        msg = (r.stderr or r.stdout).strip()

        if _is_auth_error(msg):
            if _auto_login():
                r2 = subprocess.run([P4_BIN, *args], capture_output=True, text=True, env=env)
                if r2.returncode == 0:
                    return r2.stdout.strip()
                msg = (r2.stderr or r2.stdout).strip()

            has_kc = _keychain_password() is not None
            if has_kc:
                raise RuntimeError(
                    "Perforce ticket expired and auto-login failed (wrong password stored?).\n"
                    "Fix: run the save_p4_password tool to update your stored password,\n"
                    "     or run `p4 login` in a terminal."
                )
            raise RuntimeError(
                "Perforce ticket expired.\n"
                "Quick fix: run the p4_login tool — it will guide you.\n"
                "Permanent fix: run the save_p4_password tool once to enable auto-login."
            )

        if "Connect to server failed" in msg or "nodename nor servname" in msg:
            raise RuntimeError(
                f"Cannot reach Perforce server ({P4_PORT}).\n"
                "Check your VPN connection and retry."
            )

        raise RuntimeError(msg)

    return r.stdout.strip()


# ── P4 helpers ───────────────────────────────────────────────────────────────
def _opened_files(changelist_id: int, client: str) -> list[str]:
    out = _p4("opened", "-c", str(changelist_id), client=client)
    return [m.group(1) for line in out.splitlines() if (m := re.match(r"^(//[^#]+)#", line))]


def _shelve(changelist_id: int, client: str) -> str:
    files = _opened_files(changelist_id, client)
    if not files:
        raise RuntimeError(f"No open files found in changelist {changelist_id}")
    return _p4("shelve", "-f", "-c", str(changelist_id), *files, client=client)


def _client_for_cl(changelist_id: int) -> str:
    out = _p4("change", "-o", str(changelist_id))
    m = re.search(r"^Client:\t(\S+)", out, re.MULTILINE)
    if not m:
        raise RuntimeError(f"Could not detect client for changelist {changelist_id}.\nOutput: {out[:200]}")
    return m.group(1)


def _desc_for_cl(changelist_id: int) -> str:
    out = _p4("change", "-o", str(changelist_id))
    m = re.search(r"^Description:\n(.*?)(?=^\S|\Z)", out, re.MULTILINE | re.DOTALL)
    if not m:
        return ""
    return "\n".join(line.lstrip("\t") for line in m.group(1).split("\n")).strip()


def _resolve_client(workspace: str | None) -> str:
    if not workspace:
        raise RuntimeError("workspace is required for create_changelist")
    if workspace.startswith(P4_USER + "_"):
        return workspace
    return f"{P4_USER}_{workspace}"


# ── Swarm layer ─────────────────────────────────────────────────────────────
# Persistent HTTP client reuses TCP connections across all Swarm calls.
# Swarm authenticates with (P4USER, p4_ticket) — ticket from `p4 login -p`.
# The ticket is cached for 20h and auto-refreshes on 401 from Swarm.

warnings.filterwarnings("ignore", message=".*Unverified HTTPS.*")
_http = httpx.Client(verify=False, timeout=30)

_SWARM_TICKET_TTL = 20 * 3600  # 20h (p4 tickets expire in 24h)
_swarm_ticket_cache: dict = {"value": None, "expires_at": 0.0}


def _extract_ticket(raw: str) -> str:
    """Extract the hex ticket hash from `p4 login -p` output.

    Handles both clean output (just the hash) and noisy output
    (messages + hash on last non-empty line).
    """
    for line in reversed(raw.strip().splitlines()):
        stripped = line.strip()
        if re.fullmatch(r"[0-9A-Fa-f]{32,}", stripped):
            return stripped
    return raw.strip().splitlines()[-1].strip() if raw.strip() else raw.strip()


def _swarm_ticket(force_refresh: bool = False) -> str:
    """Return a cached Swarm ticket; refresh only when expired or forced."""
    now = time.monotonic()
    if (
        not force_refresh
        and _swarm_ticket_cache["value"]
        and now < _swarm_ticket_cache["expires_at"]
    ):
        return _swarm_ticket_cache["value"]
    raw = _p4("login", "-p")
    ticket = _extract_ticket(raw)
    _swarm_ticket_cache["value"] = ticket
    _swarm_ticket_cache["expires_at"] = now + _SWARM_TICKET_TTL
    return ticket


def _swarm(method: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
    """Make a Swarm API call. Caches the ticket and retries once on 401."""
    url = f"{SWARM_API}/{path}"
    for attempt in range(2):
        auth = (P4_USER, _swarm_ticket(force_refresh=(attempt > 0)))
        if method == "get":
            resp = _http.get(url, auth=auth)
        elif method == "post":
            resp = _http.post(url, auth=auth, json=payload or {})
        else:
            resp = _http.patch(url, auth=auth, json=payload or {})

        if resp.status_code == 401 and attempt == 0:
            _swarm_ticket_cache["value"] = None
            continue
        return resp.status_code, resp.json() if resp.content else {}

    raise RuntimeError(
        "Swarm authentication failed after ticket refresh.\n"
        "Run p4_login to re-authenticate."
    )


# ── Startup auth ────────────────────────────────────────────────────────────
_ensure_auth()

# ── MCP server ──────────────────────────────────────────────────────────────
mcp = FastMCP(
    "p4-workflow",
    instructions="""
Single source of truth for Perforce + Swarm workflow -- one tool per task:

  1. create_changelist  -> new CL with full Cisco template against a bug ID
  2. checkout_file      -> open file(s) for edit in a CL (p4 edit)
  3. update_description -> update CL description (no char limit)
  4. update_review      -> after saving code, push new version to Swarm (1 call)
  5. raise_review       -> first-time: shelve + create Swarm review (1 call)
  6. add_review_comment -> comment on a review
  7. get_review_diff    -> fetch full diff + metadata for any Swarm review
  8. get_review_info    -> fetch metadata + file list for any Swarm review (no diff)
  9. p4_login           -> check ticket status; auto-refreshes from Keychain if stored
 10. save_p4_password   -> one-time: store P4 password in Keychain for auto-login

Workspace (P4CLIENT) is always auto-detected from the changelist.
Tickets auto-refresh from Keychain — run save_p4_password once to enable.
""",
)

# Exact Cisco IMS changelist template
_CL_TEMPLATE = """\
Fixes: [{user} {bug_id}]

Change Description:
{change_description}

Root Cause:
{root_cause}

Solution:
{solution}

Feature Testing/Change-Based Regression Done:
{feature_testing}

Unit Test:
{unit_test}

MR Local Build Test: {mr_local_build}

Architect review performed and ship it received: N

Architect (userid):

Test case review performed and ship it received:

SIL/Test Architect (userid):

Automated test case exists: N

If "No", was this test case added to the backlog for automation:
<TargetProcess link to automation backlog feature>

Automated test cases run: N

Upgrade scenario considered? Please include details:
{upgrade_scenario}

Review Link:

Documentation:
{documentation}"""


# ── Auth tools ───────────────────────────────────────────────────────────────
@mcp.tool()
def p4_login() -> str:
    """Check Perforce login status and auto-refresh the ticket if possible.

    If a password is stored in Keychain (via save_p4_password), the ticket is
    refreshed automatically. Otherwise returns instructions for manual login.
    """
    if _ticket_valid():
        return f"Logged in. {_ticket_status()}"

    if _auto_login():
        return f"Ticket expired — auto-renewed from Keychain. {_ticket_status()}"

    return (
        "Perforce ticket expired and no password stored in Keychain.\n\n"
        "Option 1 (recommended — enables auto-login forever):\n"
        "  Run the save_p4_password tool with your P4 password.\n\n"
        "Option 2 (manual, one session):\n"
        "  Open a terminal and run: p4 login"
    )


@mcp.tool()
def save_p4_password(password: str) -> str:
    """Store your Perforce password in macOS Keychain for automatic login renewal.

    This is a one-time setup. After this, every p4 command will silently
    re-authenticate when the ticket expires — no more manual `p4 login`.

    The password is stored securely in the macOS Keychain under the service
    name 'p4-workflow' and is never written to disk or logs.

    Args:
        password: Your Perforce password (P4PASSWD)
    """
    subprocess.run(
        ["security", "delete-generic-password", "-a", P4_USER, "-s", _KEYCHAIN_SERVICE],
        capture_output=True,
    )

    r = subprocess.run(
        ["security", "add-generic-password", "-a", P4_USER, "-s", _KEYCHAIN_SERVICE, "-w", password],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        raise RuntimeError(f"Failed to save to Keychain: {r.stderr.strip()}")

    _invalidate_kc_cache()

    if _do_login(password):
        return (
            f"Password saved to Keychain (service: {_KEYCHAIN_SERVICE}, account: {P4_USER}).\n"
            f"Auto-login is now enabled — tickets will renew silently.\n"
            f"Current status: {_ticket_status()}"
        )

    return (
        "Password saved to Keychain, but login failed — double-check your password.\n"
        "Run save_p4_password again with the correct password."
    )


# ── Workflow tools ────────────────────────────────────────────────────────────
@mcp.tool()
def create_changelist(
    bug_id: str,
    workspace: str,
    change_description: str,
    root_cause: str,
    solution: str,
    feature_testing: str = "- No regression on same-version HA pairs\n- Tested version mismatch scenario",
    unit_test: str = "Manual end-to-end test on FMC HA lab",
    upgrade_scenario: str = "N/A",
    documentation: str = "No doc update required",
    mr_local_build: str = "N",
) -> str:
    """Create a new Perforce changelist with the exact Cisco IMS template against a bug ID.

    The workspace short name is accepted (e.g. '7_4_1_MAIN') -- prefix is prepended automatically.

    Args:
        bug_id:              Bug ID e.g. 'CSCwt43076'
        workspace:           Workspace short name e.g. '7_4_1_MAIN', 'IMS_7_7_MAIN', 'ims_10_10_MAIN'
        change_description:  What the change does
        root_cause:          Root cause of the bug
        solution:            How the fix works
        feature_testing:     Regression / integration testing done (bullet points)
        unit_test:           Unit test description
        upgrade_scenario:    Upgrade impact (default: N/A)
        documentation:       Doc impact (default: 'No doc update required')
        mr_local_build:      MR local build done? 'Y' or 'N'
    """
    client = _resolve_client(workspace)

    description = _CL_TEMPLATE.format(
        user=P4_USER,
        bug_id=bug_id,
        change_description=change_description,
        root_cause=root_cause,
        solution=solution,
        feature_testing=feature_testing,
        unit_test=unit_test,
        upgrade_scenario=upgrade_scenario,
        documentation=documentation,
        mr_local_build=mr_local_build,
    )

    spec = f"Change:\tnew\nClient:\t{client}\nUser:\t{P4_USER}\nStatus:\tnew\nDescription:\n"
    for line in description.split("\n"):
        spec += f"\t{line}\n"

    r = subprocess.run(
        [P4_BIN, "change", "-i"],
        input=spec, capture_output=True, text=True, env=_p4_env(client),
    )
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip())

    m = re.search(r"Change (\d+) created", r.stdout)
    cl_id = m.group(1) if m else "?"
    return (
        f"Changelist {cl_id} created in workspace {client}.\n"
        f"Bug: {bug_id} | Template: Cisco IMS\n"
        f"Next: use checkout_file to open files for edit, then update_review / raise_review."
    )


@mcp.tool()
def checkout_file(
    file_path: str,
    changelist_id: int,
) -> str:
    """Open a file for edit in a specific changelist (p4 edit).

    Accepts either a local filesystem path OR a depot path -- auto-detects and
    converts local paths to depot paths using 'p4 where'.

    The workspace (P4CLIENT) is auto-detected from the changelist.

    Args:
        file_path:      Local path (e.g. /Users/you/Perforce/.../foo.pm)
                        OR depot path (e.g. //depot/firepower/ims/.../foo.pm)
        changelist_id:  The changelist to open the file in
    """
    client = _client_for_cl(changelist_id)

    if not file_path.startswith("//"):
        where_out = _p4("where", file_path, client=client)
        depot_path = where_out.split()[0]
    else:
        depot_path = file_path

    _p4("edit", "-c", str(changelist_id), depot_path, client=client)
    return f"Opened {depot_path} for edit in CL {changelist_id} (workspace: {client})."


@mcp.tool()
def update_description(changelist_id: int, description: str) -> str:
    """Update a changelist description with no character limit.

    Uses 'p4 change -i' directly, bypassing the 2000-char restriction in the
    official perforce-p4 MCP server.

    Args:
        changelist_id:  The Perforce changelist number
        description:    Full description text (any length)
    """
    client = _client_for_cl(changelist_id)
    spec = _p4("change", "-o", str(changelist_id), client=client)
    indented = "\n".join(f"\t{line}" for line in description.splitlines())
    new_spec = re.sub(
        r"^Description:.*?(?=^\S|\Z)",
        f"Description:\n{indented}\n\n",
        spec,
        flags=re.MULTILINE | re.DOTALL,
    )
    r = subprocess.run(
        [P4_BIN, "change", "-i"],
        input=new_spec, capture_output=True, text=True, env=_p4_env(client),
    )
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip())
    return f"CL {changelist_id} description updated ({len(description)} chars)."


@mcp.tool()
def update_review(changelist_id: int) -> str:
    """Push your saved code changes to Swarm by force re-shelving the changelist.

    Swarm auto-detects the new shelf and creates a new review version -- no other steps needed.
    Workspace (P4CLIENT) is auto-detected from the changelist.

    Args:
        changelist_id: The Perforce changelist number (e.g. 4990352)
    """
    client = _client_for_cl(changelist_id)
    _shelve(changelist_id, client)
    return (
        f"CL {changelist_id} re-shelved (workspace: {client}).\n"
        f"Swarm auto-creates a new review version. Check: {SWARM_URL}"
    )


@mcp.tool()
def raise_review(
    changelist_id: int,
    reviewers: list[str] | None = None,
    required_reviewers: list[str] | None = None,
) -> str:
    """Shelve a changelist AND create a new Swarm review -- in one call.

    The review description is read automatically from the changelist description.
    Workspace is auto-detected.

    Args:
        changelist_id:      The Perforce changelist number
        reviewers:          Optional list of reviewer usernames to add
        required_reviewers: Optional list of required reviewer usernames
    """
    client = _client_for_cl(changelist_id)
    _shelve(changelist_id, client)
    description = _desc_for_cl(changelist_id)

    payload: dict = {"change": changelist_id, "description": description}
    if reviewers:
        payload["reviewers"] = reviewers
    if required_reviewers:
        payload["requiredReviewers"] = required_reviewers

    status, body = _swarm("post", "reviews", payload)

    if status == 200:
        review = body["review"]
        review_id = review["id"]
        return (
            f"Review {review_id} raised from CL {changelist_id} (workspace: {client}).\n"
            f"URL: {SWARM_URL}/reviews/{review_id}\n"
            f"State: {review.get('state', 'needsReview')}"
        )

    if status == 400 and "already exists" in str(body):
        return (
            f"CL {changelist_id} re-shelved (workspace: {client}).\n"
            f"Review already exists for this CL -- Swarm auto-versioned it.\n"
            f"Check: {SWARM_URL}"
        )

    raise RuntimeError(f"Swarm API returned {status}: {body}")


@mcp.tool()
def get_review_diff(review_id: int, max_lines: int = 600) -> str:
    """Fetch the full diff and metadata for any Swarm review.

    Retrieves review info from Swarm then runs p4 describe -S on each shelved
    changelist to get the actual file diffs.

    Args:
        review_id: Swarm review ID (e.g. 4960267)
        max_lines: Truncate diff output at this many lines (default 600)
    """
    status, body = _swarm("get", f"reviews/{review_id}")
    if status != 200:
        raise RuntimeError(f"Swarm API returned {status} for review {review_id}: {body}")

    review = body["review"]
    author = review.get("author", "?")
    state = review.get("state", "?")
    desc = (review.get("description") or "").strip().splitlines()[0] if review.get("description") else ""
    changes = review.get("changes") or review.get("versions", [{}])[-1].get("change", [])
    if isinstance(changes, int):
        changes = [changes]

    header = (
        f"Review:      {SWARM_URL}/reviews/{review_id}\n"
        f"Author:      {author}\n"
        f"State:       {state}\n"
        f"Description: {desc}\n"
        f"Changelists: {', '.join(str(c) for c in changes)}\n"
        f"{'─' * 60}\n"
    )

    diff_parts = []
    for cl in changes:
        try:
            out = _p4("describe", "-S", "-du", str(cl))
            diff_parts.append(f"=== CL {cl} ===\n{out}")
        except RuntimeError as e:
            diff_parts.append(f"=== CL {cl} === (p4 describe failed: {e})")

    full_diff = "\n".join(diff_parts)
    lines = full_diff.splitlines()
    if len(lines) > max_lines:
        full_diff = "\n".join(lines[:max_lines]) + f"\n\n... (truncated at {max_lines} lines, {len(lines)} total)"

    return header + full_diff


@mcp.tool()
def get_review_info(review_id: int) -> str:
    """Fetch summary info for any Swarm review -- no diff, just metadata and file list.

    Args:
        review_id: Swarm review ID (e.g. 4960267)
    """
    status, body = _swarm("get", f"reviews/{review_id}")
    if status != 200:
        raise RuntimeError(f"Swarm API returned {status}: {body}")

    review = body["review"]
    author = review.get("author", "?")
    state = review.get("state", "?")
    desc = (review.get("description") or "").strip()
    changes = review.get("changes") or []
    if isinstance(changes, int):
        changes = [changes]

    files_out = ""
    for cl in changes:
        try:
            out = _p4("describe", "-S", "-s", str(cl))
            files_out += f"\n=== Files in CL {cl} ===\n{out}\n"
        except RuntimeError as e:
            files_out += f"\n=== CL {cl} failed: {e} ===\n"

    return (
        f"Review:      {SWARM_URL}/reviews/{review_id}\n"
        f"Author:      {author}\n"
        f"State:       {state}\n"
        f"CLs:         {', '.join(str(c) for c in changes)}\n\n"
        f"Description:\n{desc}\n"
        f"{files_out}"
    )


@mcp.tool()
def add_review_comment(review_id: int, body: str) -> str:
    """Add a comment to an existing Swarm review.

    Args:
        review_id: The Swarm review ID (e.g. 4990354)
        body:      Comment text
    """
    status, resp = _swarm("post", "comments", {"topic": f"reviews/{review_id}", "body": body})
    if status == 200:
        comment_id = resp.get("comment", {}).get("id", "?")
        return f"Comment {comment_id} added to review {review_id}."
    raise RuntimeError(f"Swarm API returned {status}: {resp}")


if __name__ == "__main__":
    mcp.run()
