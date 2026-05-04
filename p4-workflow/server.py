#!/usr/bin/env python3
"""
p4-workflow -- Single source of truth for all Perforce + Swarm workflow operations.

All config is read from environment variables (set by mcp.json):
  P4_BIN      -- path to p4 CLI          (default: p4 on PATH or ~/bin/p4)
  P4PORT      -- Perforce server          (required)
  P4USER      -- Perforce username        (required)
  SWARM_URL   -- Swarm base URL           (default: https://sp4-fp-swarm.cisco.com)

Auth architecture (zero-touch):
  1. Startup: validate ticket -> Keychain auto-login if expired
  2. Runtime: every _p4() call auto-handles auth (Keychain -> SAML browser -> retry)
  3. Swarm: ticket cached 20h; auto-refreshes on 401; extracted from `p4 login -p`
  4. Both servers share P4TICKETS file so perforce-p4 never drifts out of sync
"""
import fcntl
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
P4_BIN = os.environ.get("P4_BIN") or shutil.which("p4") or os.path.expanduser("~/bin/p4")
P4_PORT = os.environ["P4PORT"]
P4_USER = os.environ["P4USER"]
P4_TICKETS = os.environ.get("P4TICKETS", os.path.expanduser("~/.p4tickets"))

SWARM_URL = os.environ.get("SWARM_URL", "https://sp4-fp-swarm.cisco.com")
SWARM_API = f"{SWARM_URL}/api/v9"

_KEYCHAIN_SERVICE = "p4-workflow"

_TICKET_ERROR_SIGNALS = (
    "ticket has expired",
    "your session has expired",
    "password invalid",
    "p4passwd",
    "password (p4passwd)",
    "login required",
)


# ── Keychain helpers (macOS) ─────────────────────────────────────────────────
def _keychain_read() -> str | None:
    try:
        r = subprocess.run(
            ["security", "find-generic-password", "-a", P4_USER,
             "-s", _KEYCHAIN_SERVICE, "-w"],
            capture_output=True, text=True,
        )
        return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None
    except FileNotFoundError:
        return None


def _keychain_write(password: str) -> bool:
    subprocess.run(
        ["security", "delete-generic-password", "-a", P4_USER,
         "-s", _KEYCHAIN_SERVICE],
        capture_output=True,
    )
    r = subprocess.run(
        ["security", "add-generic-password", "-a", P4_USER,
         "-s", _KEYCHAIN_SERVICE, "-w", password],
        capture_output=True, text=True,
    )
    return r.returncode == 0


def _login_with_password(password: str) -> bool:
    r = subprocess.run(
        [P4_BIN, "login"],
        input=password + "\n",
        capture_output=True, text=True, env=_p4_env(),
    )
    return r.returncode == 0


def _try_keychain_login() -> bool:
    pw = _keychain_read()
    if pw and _login_with_password(pw):
        log.info("Auto-logged in from Keychain")
        return True
    return False


# ── P4 environment ──────────────────────────────────────────────────────────
def _p4_env(client: str | None = None) -> dict:
    """Build a clean env dict for p4 subprocesses.

    Explicitly sets P4PORT, P4USER, P4TICKETS so that both this server
    and perforce-p4 always share the same ticket file and config.
    """
    env = os.environ.copy()
    env["P4PORT"] = P4_PORT
    env["P4USER"] = P4_USER
    env["P4TICKETS"] = P4_TICKETS
    if client:
        env["P4CLIENT"] = client
    return env


def _check_ticket() -> tuple[bool, str]:
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


def _do_saml_login() -> tuple[bool, str]:
    """Run `p4 login`, open the SAML URL in a browser, wait for completion.

    Caller is responsible for ensuring only ONE process invokes this at a
    time -- use _saml_login_coordinated() instead of calling this directly.
    """
    proc = subprocess.Popen(
        [P4_BIN, "login"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, env=_p4_env(),
    )
    url = None
    for line in iter(proc.stdout.readline, ""):
        if "Navigate to URL:" in line:
            url = line.split("Navigate to URL:", 1)[-1].strip()
            subprocess.Popen(["open", url])
            break
    if not url:
        proc.kill()
        return False, "p4 login did not output a SAML URL. Check VPN."
    try:
        proc.wait(timeout=180)
    except subprocess.TimeoutExpired:
        proc.kill()
        return False, f"Browser login timed out (3 min). Complete manually: {url}"
    if _ticket_valid():
        return True, "Logged in via browser SSO."
    return False, f"Browser auth completed but ticket not valid. Retry: {url}"


_SAML_LOCK_PATH = f"/tmp/p4-saml-{P4_USER}.lock"


def _saml_login_coordinated(timeout_s: int = 180) -> tuple[bool, str]:
    """Coordinated SAML login -- guarantees only one browser tab opens.

    Uses fcntl.flock on _SAML_LOCK_PATH (the same lock file the
    perforce-p4/p4-mcp-start.sh wrapper uses via lockf(1)) so the two
    MCP servers cooperate and the user never sees duplicate SAML tabs
    when Cursor launches them in parallel.

    Algorithm:
      1. Try to acquire the lock non-blockingly. If held by another
         process, poll the ticket file every second -- if it becomes
         valid we exit early without opening a browser.
      2. Once we own the lock, re-check the ticket: a sibling may have
         just refreshed it. If so, skip SAML.
      3. Otherwise call _do_saml_login() (the only place that opens
         the browser).
    """
    fd = os.open(_SAML_LOCK_PATH, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        deadline = time.monotonic() + timeout_s
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if _ticket_valid():
                    return True, "Logged in (sibling MCP server completed SAML)."
                if time.monotonic() >= deadline:
                    return False, (
                        "Timed out waiting for the other MCP server to finish SAML login. "
                        "Re-run p4_login or restart Cursor."
                    )
                time.sleep(1.0)
        if _ticket_valid():
            return True, "Logged in (sibling MCP server completed SAML)."
        return _do_saml_login()
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(fd)


def _is_auth_error(msg: str) -> bool:
    lower = msg.lower()
    return any(s in lower for s in _TICKET_ERROR_SIGNALS)


def _ensure_auth() -> None:
    ok, status = _check_ticket()
    if ok:
        log.info("Auth OK: %s", status)
        return
    if _try_keychain_login():
        log.info("Auth OK (auto-refreshed from Keychain)")
        return
    log.warning("Perforce ticket expired at startup — will auto-login on first command.")


# ── P4 command runner ────────────────────────────────────────────────────────
def _p4(*args: str, client: str | None = None) -> str:
    """Run a p4 command. Handles all auth automatically."""
    env = _p4_env(client)
    r = subprocess.run([P4_BIN, *args], capture_output=True, text=True, env=env)

    if r.returncode != 0:
        msg = (r.stderr or r.stdout).strip()

        if _is_auth_error(msg):
            if _try_keychain_login():
                r = subprocess.run([P4_BIN, *args], capture_output=True, text=True, env=env)
                if r.returncode == 0:
                    return r.stdout.strip()

            ok, login_msg = _saml_login_coordinated()
            if ok:
                r = subprocess.run([P4_BIN, *args], capture_output=True, text=True, env=env)
                if r.returncode == 0:
                    return r.stdout.strip()

            raise RuntimeError(f"Authentication failed after auto-login.\n{login_msg}")

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


def _pending_cls_raw() -> list[dict]:
    """Return parsed pending changelists for the current user via p4 -ztag."""
    out = _p4("-ztag", "changes", "-u", P4_USER, "-s", "pending")
    cls = []
    current: dict = {}
    for line in out.splitlines():
        m = re.match(r"^\.\.\.\s+(\w+)\s+(.*)", line)
        if m:
            key, val = m.group(1), m.group(2)
            if key == "change" and current:
                cls.append(current)
                current = {}
            current[key] = val
    if current:
        cls.append(current)
    return cls


def _shelve(changelist_id: int, client: str) -> str:
    """Shelve open files. On 'no open files', suggests the user's other pending CLs."""
    files = _opened_files(changelist_id, client)
    if not files:
        other = _pending_cls_raw()
        suggestions = [
            c["change"] for c in other
            if c.get("change") != str(changelist_id) and c.get("client", "") == client
        ]
        hint = ""
        if suggestions:
            hint = f"\nYour other pending CLs in {client}: {', '.join(suggestions)}. Did you mean one of those?"
        raise RuntimeError(
            f"No open files found in changelist {changelist_id}.{hint}"
        )
    return _p4("shelve", "-f", "-c", str(changelist_id), *files, client=client)


def _cl_for_review(review_id: int) -> int:
    """Look up the active changelist for a Swarm review via the Swarm API."""
    status, body = _swarm("get", f"reviews/{review_id}")
    if status != 200:
        raise RuntimeError(f"Swarm API returned {status} for review {review_id}: {body}")
    review = body.get("review", {})
    changes = review.get("changes") or []
    if isinstance(changes, int):
        changes = [changes]
    if not changes:
        raise RuntimeError(f"Review {review_id} has no associated changelists.")
    return changes[-1]


def _swarm_review_for_cl(changelist_id: int) -> dict | None:
    """Find the Swarm review associated with a changelist, if any."""
    status, body = _swarm("get", f"reviews?change[]={changelist_id}")
    if status != 200:
        return None
    reviews = body.get("reviews", [])
    return reviews[0] if reviews else None


# ── Swarm layer ─────────────────────────────────────────────────────────────
warnings.filterwarnings("ignore", message=".*Unverified HTTPS.*")
_http = httpx.Client(verify=False, timeout=30)

_SWARM_TICKET_TTL = 20 * 3600
_swarm_ticket_cache: dict = {"value": None, "expires_at": 0.0}


def _extract_ticket(raw: str) -> str:
    for line in reversed(raw.strip().splitlines()):
        stripped = line.strip()
        if re.fullmatch(r"[0-9A-Fa-f]{32,}", stripped):
            return stripped
    return raw.strip().splitlines()[-1].strip() if raw.strip() else raw.strip()


def _swarm_ticket(force_refresh: bool = False) -> str:
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

    raise RuntimeError("Swarm authentication failed after ticket refresh.")


# ── Startup auth ────────────────────────────────────────────────────────────
_ensure_auth()

# ── MCP server ──────────────────────────────────────────────────────────────
mcp = FastMCP(
    "p4-workflow",
    instructions="""
Single source of truth for Perforce + Swarm workflow -- one tool per task:

  p4_status          -> pre-flight check: auth, workspace, pending CLs, Swarm reachability
  list_pending_cls   -> your open changelists with file counts
  create_changelist  -> new CL with full Cisco template against a bug ID
  checkout_file      -> open file(s) for edit in a CL (p4 edit)
  update_description -> update CL description (no char limit)
  push_to_review     -> shelve + raise OR update Swarm review (one call, auto-detects)
  get_review_diff    -> fetch full diff + metadata for any Swarm review
  get_review_info    -> fetch metadata + file list for any Swarm review (no diff)
  add_review_comment -> comment on a review
  p4_login           -> check/refresh ticket (usually not needed — auth is automatic)
  save_p4_password   -> one-time: store P4 password in Keychain for silent auth

Accepts review_id OR changelist_id — resolves automatically via Swarm API.
Auth is fully automatic. Workspace is auto-detected from the changelist.
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


# ── Pre-flight & discovery tools ─────────────────────────────────────────────
@mcp.tool()
def p4_status() -> str:
    """One-shot pre-flight: auth status, workspace, pending CLs, Swarm reachability.

    Call this FIRST before starting any workflow to confirm everything is wired up.
    """
    lines: list[str] = []

    ok, ticket_msg = _check_ticket()
    lines.append(f"Auth:       {'OK' if ok else 'EXPIRED'} — {ticket_msg}")
    lines.append(f"Server:     {P4_PORT}")
    lines.append(f"User:       {P4_USER}")
    lines.append(f"Tickets:    {P4_TICKETS}")

    try:
        client_out = _p4("set", "P4CLIENT")
        client = re.sub(r"\s*\(.*?\)\s*$", "", client_out.replace("P4CLIENT=", "")).strip()
        if client in ("none", "(config)", ""):
            client = "(not set)"
    except RuntimeError:
        client = "(error reading)"
    lines.append(f"Workspace:  {client}")

    pending = _pending_cls_raw()
    if pending:
        lines.append(f"Pending CLs ({len(pending)}):")
        for c in pending[:15]:
            desc_first = (c.get("desc", "") or "")[:80]
            ws = c.get("client", "?")
            lines.append(f"  CL {c['change']:>8}  [{ws}]  {desc_first}")
        if len(pending) > 15:
            lines.append(f"  ... and {len(pending) - 15} more")
    else:
        lines.append("Pending CLs: none")

    try:
        swarm_status, _ = _swarm("get", "version")
        lines.append(f"Swarm:      {'reachable' if swarm_status == 200 else f'HTTP {swarm_status}'} ({SWARM_URL})")
    except Exception as e:
        lines.append(f"Swarm:      unreachable ({e})")

    return "\n".join(lines)


@mcp.tool()
def list_pending_cls(workspace: str | None = None) -> str:
    """List your pending changelists, optionally filtered to a specific workspace.

    Shows CL number, workspace, file count, and first line of description.

    Args:
        workspace: Optional workspace short name to filter (e.g. 'IMS_10_5_MAIN').
                   Omit to show all workspaces.
    """
    client_filter = _resolve_client(workspace) if workspace else None
    pending = _pending_cls_raw()

    if client_filter:
        pending = [c for c in pending if c.get("client") == client_filter]

    if not pending:
        scope = f" in {client_filter}" if client_filter else ""
        return f"No pending changelists{scope}."

    lines = [f"Pending changelists for {P4_USER} ({len(pending)}):"]
    for c in pending:
        cl_id = c["change"]
        ws = c.get("client", "?")
        desc_first = (c.get("desc", "") or "")[:80]

        file_count = 0
        try:
            opened = _p4("opened", "-c", cl_id, client=ws)
            file_count = len([l for l in opened.splitlines() if l.strip()])
        except RuntimeError:
            pass

        lines.append(f"  CL {cl_id:>8}  [{ws}]  {file_count} files  {desc_first}")

    return "\n".join(lines)


# ── Auth tools ───────────────────────────────────────────────────────────────
@mcp.tool()
def p4_login() -> str:
    """Check Perforce login status and auto-refresh the ticket if possible.

    Auth cascade (fully automatic):
      1. Already logged in? -> done.
      2. Password in Keychain? -> silent refresh -> done.
      3. SAML/SSO -> opens browser automatically -> waits for completion -> done.
    """
    if _ticket_valid():
        return f"Already logged in. {_ticket_status()}"
    if _try_keychain_login():
        return f"Auto-logged in from Keychain. {_ticket_status()}"
    ok, msg = _saml_login_coordinated()
    if ok:
        return f"{msg} {_ticket_status()}"
    return msg


@mcp.tool()
def save_p4_password(password: str) -> str:
    """Store your Perforce password in macOS Keychain for automatic login renewal.

    One-time setup. After this, all p4 operations auto-renew silently.
    The password is stored in the macOS Keychain and is never written to disk or logs.

    Args:
        password: Your Perforce password (P4PASSWD)
    """
    if not _login_with_password(password):
        return "Login failed — check that the password is correct and VPN is connected."
    if _keychain_write(password):
        return (
            f"Password saved to Keychain and login successful.\n"
            f"{_ticket_status()}\n"
            f"All future p4 operations will auto-renew the ticket silently."
        )
    return "Login succeeded but Keychain save failed. The ticket is active for now."


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
        workspace:           Workspace short name e.g. '7_4_1_MAIN', 'IMS_7_7_MAIN'
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
        user=P4_USER, bug_id=bug_id,
        change_description=change_description,
        root_cause=root_cause, solution=solution,
        feature_testing=feature_testing, unit_test=unit_test,
        upgrade_scenario=upgrade_scenario, documentation=documentation,
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
        f"Next: use checkout_file to open files for edit, then push_to_review."
    )


@mcp.tool()
def checkout_file(file_path: str, changelist_id: int) -> str:
    """Open a file for edit in a specific changelist (p4 edit).

    Accepts either a local filesystem path OR a depot path -- auto-detects.
    Workspace is auto-detected from the changelist.

    Args:
        file_path:      Local path or depot path (e.g. //depot/.../foo.pm)
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

    Bypasses the 2000-char restriction in the official perforce-p4 MCP server.

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
def push_to_review(
    changelist_id: int | None = None,
    review_id: int | None = None,
    reviewers: list[str] | None = None,
    required_reviewers: list[str] | None = None,
) -> str:
    """Shelve + raise OR update a Swarm review -- in one call, auto-detects which.

    Accepts EITHER a changelist_id OR a review_id (resolves the CL via Swarm).
    If a review already exists for this CL, updates it. Otherwise creates a new one.
    After shelving, polls Swarm to report the exact version number created.

    Args:
        changelist_id:      Perforce changelist number (e.g. 5063715)
        review_id:          Swarm review ID (e.g. 5063722) -- auto-resolves to the CL
        reviewers:          Optional list of reviewer usernames
        required_reviewers: Optional list of required reviewer usernames
    """
    if not changelist_id and not review_id:
        raise RuntimeError(
            "Provide either changelist_id or review_id.\n"
            "Use list_pending_cls to find your active CLs."
        )

    if review_id and not changelist_id:
        changelist_id = _cl_for_review(review_id)

    client = _client_for_cl(changelist_id)
    _shelve(changelist_id, client)

    existing = _swarm_review_for_cl(changelist_id)

    if existing:
        rid = existing["id"]
        time.sleep(1)
        s2, b2 = _swarm("get", f"reviews/{rid}")
        versions = b2.get("review", {}).get("versions", []) if s2 == 200 else []
        ver = len(versions) if versions else "?"
        return (
            f"Review {rid} updated from CL {changelist_id} (workspace: {client}).\n"
            f"Version: {ver}\n"
            f"URL: {SWARM_URL}/reviews/{rid}"
        )

    description = _desc_for_cl(changelist_id)
    payload: dict = {"change": changelist_id, "description": description}
    if reviewers:
        payload["reviewers"] = reviewers
    if required_reviewers:
        payload["requiredReviewers"] = required_reviewers

    status, body = _swarm("post", "reviews", payload)

    if status == 200:
        review = body["review"]
        rid = review["id"]
        return (
            f"Review {rid} created from CL {changelist_id} (workspace: {client}).\n"
            f"Version: 1\n"
            f"URL: {SWARM_URL}/reviews/{rid}\n"
            f"State: {review.get('state', 'needsReview')}"
        )

    if status == 400 and "already exists" in str(body):
        return (
            f"CL {changelist_id} re-shelved (workspace: {client}).\n"
            f"Review already exists — Swarm auto-versioned it.\n"
            f"Check: {SWARM_URL}"
        )

    raise RuntimeError(f"Swarm API returned {status}: {body}")


@mcp.tool()
def get_review_diff(review_id: int, max_lines: int = 600) -> str:
    """Fetch the full diff and metadata for any Swarm review.

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
