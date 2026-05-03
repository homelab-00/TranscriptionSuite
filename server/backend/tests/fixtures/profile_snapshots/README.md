# Profile snapshot golden fixtures

These JSON files are the **golden references** for the `profile_snapshot_golden`
pytest fixture (defined in `server/backend/tests/conftest.py`). They are loaded
by name, e.g. `loader("minimal")` resolves to `minimal-v1.0.json`.

## Rules

1. **Public fields only.** Private secrets (webhook tokens, API keys) are NEVER
   stored in plaintext here. They appear only as keychain reference IDs under
   `private_field_refs`, e.g. `"webhook_token": "ref:keyring:profile.full.webhook_token"`.
   This invariant is enforced by FR11 / R-EL22 in the Audio Notebook QoL pack PRD.

2. **Forward-only schema versioning** (R-EL30). A `schema_version` bump requires
   a NEW file (e.g. `minimal-v1.1.json`), never an in-place edit of an existing
   `*-v1.0.json` file. Old snapshots stay frozen so historical jobs can be
   replayed against the schema they were captured under.

3. **ADR-003-aware reviewers only.** Any change to these snapshots must be
   reviewed by someone familiar with ADR-003 (profile-snapshot semantics). The
   downstream consumers (Stories 1.3, 4.x, 6.x, 7.x) compare actual job-time
   snapshots to these goldens via `loader.assert_matches(...)`, so a careless
   edit here breaks every consumer test.

## Files

- `minimal-v1.0.json` — Minimum public-field set (filename_template + destination_folder).
- `full-v1.0.json` — Every public field the QoL pack ships, plus a `private_field_refs`
  block demonstrating the keychain-reference pattern.
