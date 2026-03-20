---
name: p4-workflow
description: >-
  Perforce + Swarm MCP workflow. Use when the user mentions changelists, code
  reviews, Swarm URLs, Perforce, p4, shelving, diffs, or bug fix workflows.
---

# Perforce + Swarm Workflow

## Server Selection

- **p4-workflow**: mutations and Swarm (create CL, checkout, shelve, review, diff, comment)
- **perforce-p4**: read-only depot queries (file content, history, annotations, workspace info)

## Workflow

```
create_changelist → checkout_file → [edit] → raise_review → [edit] → update_review
```

## Conventions

- Workspace arg: branch name only (e.g. `IMS_10_5_MAIN`); prefix auto-added
- Swarm URL → review ID: extract number after `/reviews/`, ignore trailing path
- Auth: fully automatic — never prompt the user for login
- CL template: auto-applied by `create_changelist`
