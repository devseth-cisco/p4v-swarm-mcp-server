Single source of truth for Perforce + Swarm workflow -- one tool per task:

  1. create_changelist  -> new CL with full Cisco template against a bug ID
  2. checkout_file      -> open file(s) for edit in a CL (p4 edit)
  3. update_description -> update CL description (no char limit)
  4. update_review      -> after saving code, push new version to Swarm (1 call)
  5. raise_review       -> first-time: shelve + create Swarm review (1 call)
  6. add_review_comment -> comment on a review
  7. get_review_diff    -> fetch full diff + metadata for any Swarm review
  8. get_review_info    -> fetch metadata + file list for any Swarm review (no diff)
  9. p4_login           -> check/refresh ticket (usually not needed — auth is automatic)
 10. save_p4_password   -> one-time: store P4 password in Keychain for silent auth

Workspace (P4CLIENT) is always auto-detected from the changelist.
Auth is fully automatic — Keychain first, then browser SSO if needed. No manual steps.
