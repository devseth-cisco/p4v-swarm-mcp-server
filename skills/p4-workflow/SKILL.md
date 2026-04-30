---
name: p4-workflow
description: >-
  Perforce + Swarm MCP workflow. Use when the user mentions changelists, code
  reviews, Swarm URLs, Perforce, p4, shelving, diffs, or bug fix workflows.
---

# Perforce + Swarm Workflow

## Server Selection

- **p4-workflow**: all mutations, discovery, and Swarm ops (create CL, checkout, shelve, review, diff, comment, status)
- **perforce-p4**: read-only depot queries (file content, history, annotations, workspace info)

## Tools

| Tool | When to use |
|------|-------------|
| `p4_status` | First call of any session — shows auth, workspace, pending CLs, Swarm health |
| `list_pending_cls` | Find the user's active CLs (optionally filtered by workspace) |
| `create_changelist` | New bug fix — requires bug_id, workspace, description, root_cause, solution |
| `checkout_file` | Open files for edit in a CL — accepts local or depot paths |
| `push_to_review` | Shelve + raise OR update a Swarm review — accepts changelist_id OR review_id |
| `get_review_diff` | Fetch full diff for any review |
| `get_review_info` | Fetch metadata + file list for any review |
| `add_review_comment` | Comment on a review |
| `update_description` | Update CL description (no char limit) |

## Workflow

```
p4_status -> create_changelist -> checkout_file -> [edit] -> push_to_review -> [edit] -> push_to_review
```

## Conventions

- Workspace arg: branch name only (e.g. `IMS_10_5_MAIN`); prefix auto-added
- Swarm URL -> review ID: extract number after `/reviews/`, ignore trailing path
- Auth: fully automatic — never prompt the user for login
- `push_to_review` replaces both `raise_review` and `update_review` — one tool for both
- CL template: auto-applied by `create_changelist`
