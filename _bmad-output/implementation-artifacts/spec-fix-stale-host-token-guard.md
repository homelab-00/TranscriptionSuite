---
title: 'Validate cached auth token against server on startup to detect stale tokens'
type: 'bugfix'
created: '2026-04-03'
status: 'done'
baseline_commit: '8922f86'
context: ['docs/project-context.md']
---

<frozen-after-approval reason="human-owned intent -- do not modify unless human renegotiates">

## Intent

**Problem:** After a Docker volume recreation, the HOST Electron app keeps a stale admin token in its config. The token was valid for the old token store but the new store has a different admin token. The user copies the stale token from the HOST to a remote client, where it silently fails with `"Token validation failed: token not found"`. The app provides no signal that the cached token is invalid — it just loops on auth failures.

**Approach:** When the server becomes reachable and the client has a cached auth token, validate it by POSTing to the public `/api/auth/login` endpoint. If the server rejects the token, clear it from config and `apiClient` so the user gets the clear "Auth token not configured" prompt instead of a confusing rejection loop. Wire this into the existing `useAuthTokenSync` hook using its already-declared-but-unused `serverReachable` parameter. Also fix the `AuthenticationMiddleware` token extraction to strip whitespace, matching `utils.py`'s `extract_bearer_token()`.

## Boundaries & Constraints

**Always:**
- Only validate when server is reachable AND a token is cached — never clear on network errors.
- Validate at most once per app session (not on every poll cycle).
- The `apiClient.login()` method already exists (`client.ts:320`) — use it, don't add new endpoints.
- The HTTP middleware token extraction must be consistent with `utils.py:extract_bearer_token()`.

**Ask First:**
- Any change to the `/api/auth/login` endpoint or its response format.
- Adding new React Query cache keys beyond `['authToken']`.

**Never:**
- Do not validate on every `serverReachable` toggle (polling artifact).
- Do not block app startup waiting for validation.
- Do not silently retry with different tokens.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Stale token, server reachable | Cached token invalid, server up | Token cleared, "Auth token not configured" prompt shown | N/A |
| Valid token, server reachable | Cached token valid, server up | No change, app works normally | N/A |
| No token cached | `authToken` empty/null | Validation skipped entirely | N/A |
| Server unreachable at startup | Cached token, server down | Validation deferred until server reachable | N/A |
| Network error during validation | POST to `/api/auth/login` fails | Token preserved (conservative: don't clear on network errors) | Catch silently |
| Server reachable, then goes down and up | Already validated this session | Skip re-validation (once per session) | N/A |

</frozen-after-approval>

## Code Map

- `dashboard/src/hooks/useAuthTokenSync.ts` -- Token lifecycle hook; has unused `serverReachable` param
- `dashboard/src/api/client.ts:320` -- Existing `apiClient.login(token)` method (POSTs to public `/api/auth/login`)
- `server/backend/api/main.py:319-320` -- HTTP middleware token extraction (missing `.strip()`)
- `server/backend/api/routes/utils.py:89-93` -- Reference implementation with `.strip()`
- `server/backend/api/routes/auth.py:45-76` -- Public `/api/auth/login` endpoint

## Tasks & Acceptance

**Execution:**
- [x] `dashboard/src/hooks/useAuthTokenSync.ts` -- Add a validation effect that fires when `serverReachable` becomes true. Use a `validatedRef` to ensure at-most-once-per-session. Call `apiClient.login(knownTokenRef.current)`. On `success: false`, clear the token from config, `apiClient`, and React Query cache. On network error, preserve the token (conservative).
- [x] `server/backend/api/main.py:319-320` -- Add `.strip()` to `auth_header[7:]` to match `utils.py:extract_bearer_token()` behavior.

**Acceptance Criteria:**
- Given the app starts with a stale cached token and the server is reachable, when `useAuthTokenSync` runs, then the token is validated via `/api/auth/login`, found invalid, cleared from config and `apiClient`, and the UI shows "Auth token not configured" instead of looping on "token rejected".
- Given the app starts with a valid cached token and the server is reachable, when `useAuthTokenSync` runs, then the token is validated, found valid, and no change occurs.
- Given the server is unreachable at startup, when `useAuthTokenSync` runs, then validation is deferred. When the server later becomes reachable, validation fires once.
- Given whitespace in a Bearer token, when the `AuthenticationMiddleware` extracts it, then trailing/leading whitespace is stripped before validation.

## Verification

**Commands:**
- `cd dashboard && npx tsc --noEmit` -- expected: no errors
- `cd server/backend && ../../build/.venv/bin/pytest tests/test_token_store.py -v --tb=short` -- expected: all pass

**Manual checks:**
- On the HOST, enter a known-bad token in Settings. Restart the app with the server running. Confirm the token is automatically cleared and "Auth token not configured" warning appears within seconds.

## Spec Change Log

- **Review round 1**: Race condition found — validation effect fires before `init()` seeds `knownTokenRef` when server is already reachable on mount. Added inline validation to `init()` after config seeding (step 1b). Also fixed SettingsModal cache subscriber to handle token clearing (was ignoring falsy values). Also extracted `clearStaleToken()` helper to avoid duplicating clearing logic between `init()` and the second effect. KEEP: second useEffect for deferred validation (handles server-becomes-reachable-later), `validatedRef` at-most-once pattern, `.strip()` middleware fix.

## Suggested Review Order

- Stale-token clearing helper extracted to avoid duplication
  [`useAuthTokenSync.ts:40`](../../dashboard/src/hooks/useAuthTokenSync.ts#L40)

- Inline validation after config seed handles "server already reachable on mount"
  [`useAuthTokenSync.ts:95`](../../dashboard/src/hooks/useAuthTokenSync.ts#L95)

- Second effect handles "server becomes reachable later" (deferred validation)
  [`useAuthTokenSync.ts:139`](../../dashboard/src/hooks/useAuthTokenSync.ts#L139)

- SettingsModal subscriber now handles token clearing (was ignoring falsy cache values)
  [`SettingsModal.tsx:165`](../../dashboard/components/views/SettingsModal.tsx#L165)

- HTTP middleware `.strip()` consistency fix
  [`main.py:320`](../../server/backend/api/main.py#L320)
