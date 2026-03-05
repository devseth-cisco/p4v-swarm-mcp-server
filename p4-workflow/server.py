#!/usr/bin/env python3
"""
p4-workflow -- Single source of truth for all Perforce + Swarm workflow operations.

ONE-CLICK TOOLS:
  create_changelist  -- create a CL with the exact Cisco template against a bug ID
  update_review      -- save code changes -> Swarm auto-versions (1 call, workspace auto-detected)
  raise_review       -- shelve + create Swarm review (1 call, description auto-read from CL)
  add_review_comment -- add a comment to a review
  checkout_file      -- open a file for edit in a changelist (p4 edit)

All tools auto-detect the correct P4CLIENT from the changelist or workspace name.
Works across ALL workspaces: 7_4_1_MAIN, IMS_7_7_MAIN, ims_10_10_MAIN, IMS_10_5_MAIN, etc.

Placeholders replaced by setup.sh:
  __P4_BIN__    -> path to p4 CLI
  __P4PORT__    -> Perforce server
  __P4USER__    -> Perforce username
  __SWARM_URL__ -> Swarm base URL
"""
import sys
import os
import re
import subprocess
import httpx
import warnings

sys.path.insert(0, os.path.dirname(__file__))
from fastmcp import FastMCP

# ── Config (update these for your environment) ─────────────────────────────
P4_BIN    = "__P4_BIN__"
P4_PORT   = "__P4PORT__"
P4_USER   = "__P4USER__"

SWARM_URL = "__SWARM_URL__"
SWARM_API = f"{SWARM_URL}/api/v9"

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

# ── P4 helpers ──────────────────────────────────────────────────────────────
def _p4(*args: str, client: str | None = None) -> str:
    env = os.environ.copy()
    env["P4PORT"] = P4_PORT
    env["P4USER"] = P4_USER
    if client:
        env["P4CLIENT"] = client
    r = subprocess.run([P4_BIN] + list(args), capture_output=True, text=True, env=env)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip())
    return r.stdout.strip()


def _opened_files(changelist_id: int, client: str) -> list[str]:
    """Return list of depot paths open in a changelist."""
    out = _p4("opened", "-c", str(changelist_id), client=client)
    paths = []
    for line in out.splitlines():
        m = re.match(r"^(//[^#]+)#", line)
        if m:
            paths.append(m.group(1))
    return paths


def _shelve(changelist_id: int, client: str) -> str:
    """Force-shelve all open files in a changelist, passing paths explicitly to avoid hangs."""
    files = _opened_files(changelist_id, client)
    if not files:
        raise RuntimeError(f"No open files found in changelist {changelist_id}")
    return _p4("shelve", "-f", "-c", str(changelist_id), *files, client=client)


def _client_for_cl(changelist_id: int) -> str:
    """Auto-detect P4CLIENT from a changelist ID."""
    out = _p4("change", "-o", str(changelist_id))
    m = re.search(r"^Client:\t(\S+)", out, re.MULTILINE)
    if not m:
        raise RuntimeError(f"Could not detect client for changelist {changelist_id}. "
                           f"Output: {out[:200]}")
    return m.group(1)


def _desc_for_cl(changelist_id: int) -> str:
    """Read the current description of a changelist."""
    out = _p4("change", "-o", str(changelist_id))
    m = re.search(r"^Description:\n(.*?)(?=^\S|\Z)", out, re.MULTILINE | re.DOTALL)
    if not m:
        return ""
    lines = m.group(1).split("\n")
    return "\n".join(line.lstrip("\t") for line in lines).strip()


def _resolve_client(workspace: str | None) -> str:
    """Resolve workspace name -> P4CLIENT. Prepends username if not already present."""
    if not workspace:
        raise RuntimeError("workspace is required for create_changelist")
    if workspace.startswith(P4_USER + "_"):
        return workspace
    return f"{P4_USER}_{workspace}"


# ── Swarm helpers ───────────────────────────────────────────────────────────
def _swarm_ticket() -> str:
    return _p4("login", "-p")


def _swarm(method: str, path: str, payload: dict) -> tuple[int, dict]:
    ticket = _swarm_ticket()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        if method == "get":
            resp = httpx.get(
                f"{SWARM_API}/{path}",
                auth=(P4_USER, ticket),
                verify=False,
                timeout=30,
            )
        else:
            fn = httpx.post if method == "post" else httpx.patch
            resp = fn(
                f"{SWARM_API}/{path}",
                auth=(P4_USER, ticket),
                json=payload,
                verify=False,
                timeout=30,
            )
    return resp.status_code, resp.json() if resp.content else {}


# ── MCP server ──────────────────────────────────────────────────────────────
mcp = FastMCP(
    "p4-workflow",
    instructions="""
Single source of truth for Perforce + Swarm workflow -- one tool per task:

  1. create_changelist  -> new CL with full Cisco template against a bug ID
  2. checkout_file      -> open file(s) for edit in a CL (p4 edit)
  3. update_review      -> after saving code, push new version to Swarm (1 call)
  4. raise_review       -> first-time: shelve + create Swarm review (1 call)
  5. add_review_comment -> comment on a review

Workspace (P4CLIENT) is always auto-detected.
""",
)


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

    env = os.environ.copy()
    env["P4PORT"] = P4_PORT
    env["P4USER"] = P4_USER
    env["P4CLIENT"] = client
    r = subprocess.run(
        [P4_BIN, "change", "-i"],
        input=spec, capture_output=True, text=True, env=env
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

    Accepts either a local filesystem path OR a depot path — auto-detects and
    converts local paths to depot paths using 'p4 where' so you never need to
    look up the depot path manually.

    The workspace (P4CLIENT) is auto-detected from the changelist.

    Args:
        file_path:      Local path (e.g. /Users/you/Perforce/.../foo.pm)
                        OR depot path (e.g. //depot/firepower/ims/.../foo.pm)
        changelist_id:  The changelist to open the file in
    """
    client = _client_for_cl(changelist_id)

    # Auto-convert local path → depot path via p4 where
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
    official perforce-p4 MCP server. Use this for long descriptions with full
    test cases, change details, etc.

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
        input=new_spec, capture_output=True, text=True,
        env={**os.environ, "P4PORT": P4_PORT, "P4USER": P4_USER, "P4CLIENT": client},
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
    """Fetch the diff and metadata for any Swarm review.

    Retrieves review info from Swarm (title, author, state, CLs) then runs
    p4 describe -S on each shelved changelist to get the actual file diffs.

    Args:
        review_id: Swarm review ID (e.g. 4960267)
        max_lines: Truncate diff output at this many lines (default 600)
    """
    status, body = _swarm("get", f"reviews/{review_id}", {})
    if status != 200:
        raise RuntimeError(f"Swarm API returned {status} for review {review_id}: {body}")

    review   = body["review"]
    author   = review.get("author", "?")
    state    = review.get("state", "?")
    desc     = (review.get("description") or "").strip().splitlines()[0] if review.get("description") else ""
    changes  = review.get("changes") or review.get("versions", [{}])[-1].get("change", [])
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
    """Fetch summary info for any Swarm review — no diff, just metadata and file list.

    Args:
        review_id: Swarm review ID (e.g. 4960267)
    """
    status, body = _swarm("get", f"reviews/{review_id}", {})
    if status != 200:
        raise RuntimeError(f"Swarm API returned {status}: {body}")

    review  = body["review"]
    author  = review.get("author", "?")
    state   = review.get("state", "?")
    desc    = (review.get("description") or "").strip()
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
