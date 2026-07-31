# GH-254 AI Summary Persistence + Configurable Prompts — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show the already-persisted AI summary immediately when a note is reopened, add an explicit Regenerate control, make the summary and chat system prompts editable in Settings → AI, and delete the dead per-profile summary config.

**Architecture:** Two new `local_llm.*` config keys (`summary_system_prompt`, `chat_system_prompt`) resolved through a fallback chain that ends at the legacy `default_system_prompt`, so existing configs behave identically. The summarize and chat call sites stop sharing one prompt. On the dashboard, the notebook modal's summary panel is seeded from `recording.summary` by a single effect instead of being cleared on open and replayed through a fake typewriter, and a new presentational `AiPromptsSection` component holds the two prompt editors.

**Tech Stack:** FastAPI + Pydantic (backend), pytest run from `server/backend/` with the **build venv**; React 19 + TypeScript + Tailwind (Electron dashboard), vitest on Node 22; server settings live in `config.yaml`, written by the dashboard over Electron IPC and hot-reloaded via `POST /api/llm/config/reload`.

**Spec:** [2026-07-30-gh254-ai-summary-persistence-and-prompts-design.md](../specs/2026-07-30-gh254-ai-summary-persistence-and-prompts-design.md)

---

## File Structure

**Create:**

| Path | Responsibility |
|---|---|
| `server/backend/tests/test_llm_prompt_config.py` | Every prompt-resolution and prompt-routing assertion for the backend. Owns the fake-httpx capture helpers used by Tasks 3-5. |
| `server/backend/tests/test_profile_public_fields.py` | Guards that the dead profile keys stay gone and that legacy stored keys still round-trip as extras. |
| `dashboard/components/views/settings/AiPromptsSection.tsx` | Presentational editor for the two prompts. No data fetching, no store access — props in, callbacks out. |
| `dashboard/components/views/settings/__tests__/AiPromptsSection.test.tsx` | Unit test for the above. |
| `dashboard/components/views/__tests__/AudioNoteModal.summary.test.tsx` | Wiring tests for the summary panel: seed-on-open, no stream for stored text, regenerate, error restore. |

**Modify:**

| Path | Change |
|---|---|
| `server/backend/api/routes/llm.py` | Prompt constants, `get_llm_config()` resolution, `LLMStatus` fields, `_status()`, both summarize call sites, `chat_with_llm`. |
| `server/backend/core/auto_summary_engine.py` | Use the summary prompt; drop the dead `summary_prompt_template` read. |
| `server/backend/api/routes/profiles.py` | Drop `summary_model_id` + `summary_prompt_template`. |
| `server/backend/tests/test_p2_llm_routes.py`, `test_llm_summarize_persistence.py` | `_config()` helpers gain the new keys. |
| `server/backend/tests/test_profile_repository.py`, `test_create_job_profile_snapshot.py`, `test_reexport_endpoint.py`, `test_profile_snapshot_durability.py`, `test_delete_recording_artifacts.py` | Drop the two keys from fixtures. |
| `dashboard/src/api/types.ts` | Four new `LLMStatus` fields. |
| `dashboard/src/api/client.ts` | Drop the two dead `ProfilePublicFields` members. |
| `dashboard/src/services/profileDefaults.ts` | Same. |
| `dashboard/components/views/SettingsModal.tsx` | Prompt state, load-effect seeding, render `AiPromptsSection`. |
| `dashboard/components/views/AudioNoteModal.tsx` | Seeding effect, generation path, Regenerate button, error state. |
| `docs/api-contracts-server.md` | Document the new `LLMStatus` fields. |
| `dashboard/ui-contract/*` | Regenerated baseline. |

**Deviation from the spec, deliberate:** the spec put the prompt UI inline in `renderAITab`. `SettingsModal.tsx` is already ~2 450 lines, and a render test of it would need roughly twenty mocks. Extracting the fields into `AiPromptsSection` keeps the diff testable and follows the repo's existing `components/views/server/` sub-component pattern. The `<Section title="Prompts">` wrapper still lives in `renderAITab`, so the rendered result matches the spec.

---

## Task 1: Prompt constants and resolution in `get_llm_config()`

**Files:**
- Test: `server/backend/tests/test_llm_prompt_config.py` (create)
- Modify: `server/backend/api/routes/llm.py:169-235`

- [ ] **Step 1: Write the failing test**

Create `server/backend/tests/test_llm_prompt_config.py`:

```python
"""GH-254 — prompt configuration for AI summaries and AI chat.

Two config keys replace the single shared ``default_system_prompt``:

  * ``local_llm.summary_system_prompt`` — manual + automatic summaries
  * ``local_llm.chat_system_prompt``    — notebook AI chat

Both fall back to the legacy ``default_system_prompt`` before reaching their
built-in default, so a config.yaml written before this change keeps producing
byte-identical behaviour. Empty strings fall through to the built-in — that is
what makes the Settings "Reset to default" button a plain write rather than a
key deletion.
"""

from server.api.routes import llm


class _FakeServerConfig:
    """Stand-in for ``ServerConfig`` — only ``.config`` is read."""

    def __init__(self, data: dict):
        self.config = data


def _resolve(monkeypatch, local_llm: dict) -> dict:
    """Run ``get_llm_config()`` against a fake ``local_llm`` config block."""
    monkeypatch.setattr(llm, "get_config", lambda: _FakeServerConfig({"local_llm": local_llm}))
    return llm.get_llm_config()


class TestPromptResolution:
    def test_builtin_defaults_when_nothing_configured(self, monkeypatch):
        cfg = _resolve(monkeypatch, {})
        assert cfg["summary_system_prompt"] == llm.DEFAULT_SUMMARY_SYSTEM_PROMPT
        assert cfg["chat_system_prompt"] == llm.DEFAULT_CHAT_SYSTEM_PROMPT

    def test_legacy_key_feeds_both_chains(self, monkeypatch):
        """A pre-GH-254 config.yaml must not change behaviour on upgrade."""
        cfg = _resolve(monkeypatch, {"default_system_prompt": "Legacy prompt"})
        assert cfg["summary_system_prompt"] == "Legacy prompt"
        assert cfg["chat_system_prompt"] == "Legacy prompt"

    def test_new_keys_win_over_legacy(self, monkeypatch):
        cfg = _resolve(
            monkeypatch,
            {
                "default_system_prompt": "Legacy prompt",
                "summary_system_prompt": "Summary prompt",
                "chat_system_prompt": "Chat prompt",
            },
        )
        assert cfg["summary_system_prompt"] == "Summary prompt"
        assert cfg["chat_system_prompt"] == "Chat prompt"

    def test_empty_string_falls_through_to_builtin(self, monkeypatch):
        cfg = _resolve(monkeypatch, {"summary_system_prompt": "", "chat_system_prompt": ""})
        assert cfg["summary_system_prompt"] == llm.DEFAULT_SUMMARY_SYSTEM_PROMPT
        assert cfg["chat_system_prompt"] == llm.DEFAULT_CHAT_SYSTEM_PROMPT

    def test_config_load_failure_still_returns_builtin_prompts(self, monkeypatch):
        def _boom():
            raise RuntimeError("config unavailable")

        monkeypatch.setattr(llm, "get_config", _boom)
        cfg = llm.get_llm_config()
        assert cfg["summary_system_prompt"] == llm.DEFAULT_SUMMARY_SYSTEM_PROMPT
        assert cfg["chat_system_prompt"] == llm.DEFAULT_CHAT_SYSTEM_PROMPT

    def test_summary_and_chat_defaults_are_distinct(self):
        """The whole point of the split: chat must not be told to summarise."""
        assert llm.DEFAULT_SUMMARY_SYSTEM_PROMPT != llm.DEFAULT_CHAT_SYSTEM_PROMPT
        assert "Summarize" in llm.DEFAULT_SUMMARY_SYSTEM_PROMPT
        assert "Summarize" not in llm.DEFAULT_CHAT_SYSTEM_PROMPT
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd server/backend && ../../build/.venv/bin/pytest tests/test_llm_prompt_config.py -v --tb=short
```

Expected: every test errors with `AttributeError: module 'server.api.routes.llm' has no attribute 'DEFAULT_SUMMARY_SYSTEM_PROMPT'`.

- [ ] **Step 3: Add the constants**

In `server/backend/api/routes/llm.py`, immediately after the `_summary_in_flight_lock` definition (around line 44) and before `def _get_httpx()`:

```python
# --- Prompt defaults (GH-254) ---
#
# Before GH-254 a single ``local_llm.default_system_prompt`` was the system
# message for AI summaries AND for AI chat, which meant every conversation in
# the notebook opened with "Summarize this transcription concisely." Each
# feature now owns a key; ``default_system_prompt`` survives as the legacy
# fallback so pre-existing config.yaml files behave exactly as they did.

DEFAULT_SUMMARY_SYSTEM_PROMPT = (
    "Summarize this transcription concisely. "
    "Respond in the same language as the transcript."
)

DEFAULT_CHAT_SYSTEM_PROMPT = (
    "You are a helpful assistant answering questions about a transcript. "
    "Base your answers on the transcript provided; if it does not contain the "
    "answer, say so plainly. Respond in the same language as the user's question."
)

DEFAULT_TITLE_GENERATION_PROMPT = (
    "Your task is to produce a SHORT TITLE for this conversation.\n"
    "Rules:\n"
    "- Maximum 8 words\n"
    "- Use the primary language of the conversation\n"
    "- Output ONLY the title — no preamble, no explanation, no quotes, no punctuation at the end\n"
    "Examples of good titles:\n"
    "  Copper grain boundary discussion\n"
    "  Project deadline planning\n"
    'Bad (do not do this): "Sure, here is a title: Grain boundaries in copper alloys."'
)
```

- [ ] **Step 4: Rewrite both return blocks of `get_llm_config()`**

Replace the `try` block's return (llm.py:184-209) with:

```python
        legacy_prompt = llm_config.get("default_system_prompt")

        return {
            "enabled": llm_config.get("enabled", True),
            "base_url": base_url,
            "api_key": env_api_key or llm_config.get("api_key", ""),
            "model": llm_config.get("model", ""),
            "gpu_offload": llm_config.get("gpu_offload", 1.0),
            "context_length": llm_config.get("context_length"),
            "max_tokens": llm_config.get("max_tokens", 2048),
            "temperature": llm_config.get("temperature", 0.7),
            # Legacy key — still honoured by /process, and the middle link of
            # both chains below. ``or`` (not a .get default) so an empty string
            # falls through to the built-in.
            "default_system_prompt": legacy_prompt or DEFAULT_SUMMARY_SYSTEM_PROMPT,
            "summary_system_prompt": (
                llm_config.get("summary_system_prompt")
                or legacy_prompt
                or DEFAULT_SUMMARY_SYSTEM_PROMPT
            ),
            "chat_system_prompt": (
                llm_config.get("chat_system_prompt") or legacy_prompt or DEFAULT_CHAT_SYSTEM_PROMPT
            ),
            "title_generation_prompt": (
                llm_config.get("title_generation_prompt") or DEFAULT_TITLE_GENERATION_PROMPT
            ),
            "auto_title_enabled": llm_config.get("auto_title_enabled", True),
        }
```

Replace the exception-path return (llm.py:213-235) with:

```python
    return {
        "enabled": True,
        "base_url": default_base_url.rstrip("/").removesuffix("/v1"),
        "api_key": env_api_key,
        "model": "",
        "gpu_offload": 1.0,
        "context_length": None,
        "max_tokens": 2048,
        "temperature": 0.7,
        "default_system_prompt": DEFAULT_SUMMARY_SYSTEM_PROMPT,
        "summary_system_prompt": DEFAULT_SUMMARY_SYSTEM_PROMPT,
        "chat_system_prompt": DEFAULT_CHAT_SYSTEM_PROMPT,
        "title_generation_prompt": DEFAULT_TITLE_GENERATION_PROMPT,
        "auto_title_enabled": True,
    }
```

- [ ] **Step 5: Run the test to verify it passes**

```bash
cd server/backend && ../../build/.venv/bin/pytest tests/test_llm_prompt_config.py -v --tb=short
```

Expected: 6 passed.

- [ ] **Step 6: Commit**

```bash
git add server/backend/api/routes/llm.py server/backend/tests/test_llm_prompt_config.py
git commit -m "feat(server): separate summary and chat system prompts (GH-254)

* feat(server): add summary_system_prompt and chat_system_prompt config keys
  * each falls back to the legacy default_system_prompt so existing config.yaml files are unaffected
  * empty string falls through to the built-in default, which is what makes Reset to default a plain write

* refactor(server): extract the duplicated default title prompt into DEFAULT_TITLE_GENERATION_PROMPT"
```

---

## Task 2: Expose the prompts on `GET /api/llm/status`

**Files:**
- Test: `server/backend/tests/test_llm_prompt_config.py` (append)
- Modify: `server/backend/api/routes/llm.py:101-112` and `:259-266`

- [ ] **Step 1: Write the failing test**

Add `import asyncio` to the import block at the top of `server/backend/tests/test_llm_prompt_config.py`, then append:

```python
def _full_config(**overrides) -> dict:
    """A complete get_llm_config() result — every key the routes index."""
    cfg = {
        "enabled": True,
        "base_url": "http://localhost:1234",
        "api_key": "",
        "model": "test-model",
        "gpu_offload": 1.0,
        "context_length": None,
        "max_tokens": 2048,
        "temperature": 0.7,
        "default_system_prompt": "Legacy prompt",
        "summary_system_prompt": "Summary prompt",
        "chat_system_prompt": "Chat prompt",
        "title_generation_prompt": "Title prompt",
        "auto_title_enabled": True,
    }
    cfg.update(overrides)
    return cfg


class TestStatusExposesPrompts:
    def test_status_returns_effective_and_default_prompts(self, monkeypatch):
        """Settings → AI reads the effective values and the built-ins for Reset."""
        monkeypatch.setattr(llm, "get_llm_config", lambda: _full_config(enabled=False))

        status = asyncio.run(llm.get_llm_status())

        assert status.summary_system_prompt == "Summary prompt"
        assert status.chat_system_prompt == "Chat prompt"
        assert status.summary_system_prompt_default == llm.DEFAULT_SUMMARY_SYSTEM_PROMPT
        assert status.chat_system_prompt_default == llm.DEFAULT_CHAT_SYSTEM_PROMPT
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd server/backend && ../../build/.venv/bin/pytest tests/test_llm_prompt_config.py::TestStatusExposesPrompts -v --tb=short
```

Expected: FAIL with `AttributeError: 'LLMStatus' object has no attribute 'summary_system_prompt'`.

- [ ] **Step 3: Add the fields to the model and the factory**

In `LLMStatus` (llm.py:101), after `auto_title_enabled`:

```python
    # GH-254 — Settings → AI edits these; the *_default fields let the
    # dashboard implement "Reset to default" without hardcoding a second
    # copy of the prompt text that can drift from the server's.
    summary_system_prompt: str | None = None
    summary_system_prompt_default: str | None = None
    chat_system_prompt: str | None = None
    chat_system_prompt_default: str | None = None
```

In the `_status()` factory inside `get_llm_status()` (llm.py:259), add to the `LLMStatus(...)` call:

```python
            summary_system_prompt=config.get("summary_system_prompt"),
            summary_system_prompt_default=DEFAULT_SUMMARY_SYSTEM_PROMPT,
            chat_system_prompt=config.get("chat_system_prompt"),
            chat_system_prompt_default=DEFAULT_CHAT_SYSTEM_PROMPT,
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd server/backend && ../../build/.venv/bin/pytest tests/test_llm_prompt_config.py -v --tb=short
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add server/backend/api/routes/llm.py server/backend/tests/test_llm_prompt_config.py
git commit -m "feat(server): expose summary and chat prompts on /api/llm/status (GH-254)

* feat(server): add four prompt fields to LLMStatus so Settings can read the effective values and the built-in defaults"
```

---

## Task 3: Summarize routes send the summary prompt

**Files:**
- Test: `server/backend/tests/test_llm_prompt_config.py` (append)
- Modify: `server/backend/api/routes/llm.py:778-845` and `:848-906`
- Modify: `server/backend/tests/test_p2_llm_routes.py:22-35`, `server/backend/tests/test_llm_summarize_persistence.py:25-38`

- [ ] **Step 1: Write the failing test**

Add `import json` and `import pytest` to the import block at the top of `server/backend/tests/test_llm_prompt_config.py`, then append:

```python
class _FakeJsonResponse:
    status_code = 200

    def json(self) -> dict:
        return {
            "choices": [{"message": {"content": "A summary."}}],
            "model": "test-model",
            "usage": {"total_tokens": 12},
        }


class _FakeStreamResponse:
    """Async context manager mimicking a streaming ``httpx.Response``."""

    status_code = 200

    def __init__(self, lines: list[str]):
        self._lines = lines

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def aread(self) -> bytes:
        return b""

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class _CapturingClient:
    """``httpx.AsyncClient`` stub that records every JSON payload it is given."""

    def __init__(self, captured: list[dict], lines: list[str]):
        self._captured = captured
        self._lines = lines

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def post(self, _url, json=None, headers=None):
        self._captured.append(json)
        return _FakeJsonResponse()

    def stream(self, _method, _url, json=None, headers=None):
        self._captured.append(json)
        return _FakeStreamResponse(self._lines)


class _CapturingHttpx:
    """Stub httpx module — only what the LLM routes touch."""

    def __init__(self, captured: list[dict], lines: list[str] | None = None):
        self._client = _CapturingClient(captured, lines or [])

    def AsyncClient(self, **_kwargs):
        return self._client

    ConnectError = ConnectionError
    ConnectTimeout = TimeoutError
    TimeoutException = TimeoutError


def _sse(content: str) -> str:
    return f"data: {json.dumps({'model': 'test-model', 'choices': [{'delta': {'content': content}}]})}"


def _drain(response) -> list[str]:
    """Synchronously consume an async StreamingResponse body."""

    async def _collect() -> list[str]:
        return [
            chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk
            async for chunk in response.body_iterator
        ]

    return asyncio.run(_collect())


@pytest.fixture
def _stub_recording(monkeypatch):
    """Recording 42 exists with one transcription segment; summary saves are no-ops."""
    import server.database.database as database_mod

    monkeypatch.setattr(
        database_mod, "get_recording", lambda rid: {"id": rid} if rid == 42 else None
    )
    monkeypatch.setattr(
        database_mod,
        "get_transcription",
        lambda rid: {"segments": [{"text": "Hello world"}]} if rid == 42 else None,
    )
    monkeypatch.setattr(
        database_mod, "update_recording_summary", lambda *_args, **_kwargs: True
    )
    return database_mod


class TestSummarizeUsesSummaryPrompt:
    def test_streaming_summarize_sends_summary_prompt(self, monkeypatch, _stub_recording):
        captured: list[dict] = []
        monkeypatch.setattr(llm, "get_llm_config", lambda: _full_config())
        monkeypatch.setattr(
            llm, "_get_httpx", lambda: _CapturingHttpx(captured, [_sse("A summary."), "data: [DONE]"])
        )

        _drain(asyncio.run(llm.summarize_recording_stream(42)))

        assert captured, "no request was sent to the provider"
        assert captured[0]["messages"][0] == {"role": "system", "content": "Summary prompt"}

    def test_blocking_summarize_sends_summary_prompt(self, monkeypatch, _stub_recording):
        captured: list[dict] = []
        monkeypatch.setattr(llm, "get_llm_config", lambda: _full_config())
        monkeypatch.setattr(llm, "_get_httpx", lambda: _CapturingHttpx(captured))

        asyncio.run(llm.summarize_recording(42))

        assert captured[0]["messages"][0] == {"role": "system", "content": "Summary prompt"}
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd server/backend && ../../build/.venv/bin/pytest tests/test_llm_prompt_config.py::TestSummarizeUsesSummaryPrompt -v --tb=short
```

Expected: both FAIL — the system message is `"Legacy prompt"` (inherited from `default_system_prompt`), not `"Summary prompt"`.

- [ ] **Step 3: Pass the summary prompt at both call sites**

In `summarize_recording` (llm.py:778), inside the `try:` after the preamble is built, replace the `process_with_llm(...)` call with:

```python
        # GH-254 — summaries use their own system prompt, not the shared
        # default_system_prompt that also feeds the chat.
        config = get_llm_config()
        llm_response = await process_with_llm(
            LLMRequest(
                transcription_text=full_text,
                system_prompt=config["summary_system_prompt"],
                user_prompt=custom_prompt,
            )
        )
```

In `summarize_recording_stream` (llm.py:848), replace the `_build_llm_stream_response(...)` call's request with:

```python
        config = get_llm_config()
        return _build_llm_stream_response(
            LLMRequest(
                transcription_text=full_text,
                system_prompt=config["summary_system_prompt"],
                user_prompt=custom_prompt,
            ),
            on_complete=_persist,
            on_finally=_release_slot,
        )
```

- [ ] **Step 4: Update the two existing `_config()` test helpers**

Both hand-build a config dict, so they now raise `KeyError`. In `server/backend/tests/test_p2_llm_routes.py:22` and `server/backend/tests/test_llm_summarize_persistence.py:25`, add to the `defaults` dict right after `"default_system_prompt"`:

```python
        "summary_system_prompt": "Summarize this transcription concisely.",
        "chat_system_prompt": "You are a helpful assistant.",
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
cd server/backend && ../../build/.venv/bin/pytest tests/test_llm_prompt_config.py tests/test_p2_llm_routes.py tests/test_llm_summarize_persistence.py -v --tb=short
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add server/backend/api/routes/llm.py server/backend/tests/test_llm_prompt_config.py server/backend/tests/test_p2_llm_routes.py server/backend/tests/test_llm_summarize_persistence.py
git commit -m "feat(server): summarize routes send the dedicated summary prompt (GH-254)

* feat(server): pass summary_system_prompt explicitly from both summarize call sites so they no longer inherit default_system_prompt through process_with_llm

* test(server): extend the two hand-built LLM config fixtures with the new keys"
```

---

## Task 4: Chat stops borrowing the summary prompt

**Files:**
- Test: `server/backend/tests/test_llm_prompt_config.py` (append)
- Modify: `server/backend/api/routes/llm.py:1643`

- [ ] **Step 1: Write the failing test**

Append to `server/backend/tests/test_llm_prompt_config.py`:

```python
class TestChatUsesChatPrompt:
    def test_chat_sends_chat_prompt_not_summary_prompt(self, monkeypatch):
        """Regression: every conversation used to open with the summarise instruction."""
        import server.database.database as database_mod

        monkeypatch.setattr(
            database_mod,
            "get_conversation_with_messages",
            lambda cid: {"id": cid, "recording_id": 1, "messages": [], "model": None},
        )
        monkeypatch.setattr(database_mod, "add_message", lambda **_kwargs: 1)

        captured: list[dict] = []
        monkeypatch.setattr(llm, "get_llm_config", lambda: _full_config())
        monkeypatch.setattr(
            llm, "_get_httpx", lambda: _CapturingHttpx(captured, [_sse("Hi."), "data: [DONE]"])
        )

        response = asyncio.run(
            llm.chat_with_llm(
                llm.ChatRequest(
                    conversation_id=7,
                    user_message="What was decided?",
                    include_transcription=False,
                )
            )
        )
        _drain(response)

        assert captured[0]["messages"][0] == {"role": "system", "content": "Chat prompt"}
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd server/backend && ../../build/.venv/bin/pytest tests/test_llm_prompt_config.py::TestChatUsesChatPrompt -v --tb=short
```

Expected: FAIL — the system message is `"Legacy prompt"`.

- [ ] **Step 3: Point the chat at its own key**

In `chat_with_llm` (llm.py:1643), replace:

```python
    system_prompt = request.system_prompt or config.get("default_system_prompt", "")
```

with:

```python
    # GH-254 — the chat gets its own prompt. It used to share
    # default_system_prompt with the summariser, so every conversation opened
    # with "Summarize this transcription concisely."
    system_prompt = request.system_prompt or config.get("chat_system_prompt", "")
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd server/backend && ../../build/.venv/bin/pytest tests/test_llm_prompt_config.py -v --tb=short
```

Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add server/backend/api/routes/llm.py server/backend/tests/test_llm_prompt_config.py
git commit -m "fix(server): AI chat no longer opens with the summarise instruction (GH-254)

* fix(server): chat_with_llm reads chat_system_prompt instead of the shared default_system_prompt
  * behaviour change for anyone who never customised default_system_prompt: conversations stop being prefixed with \"Summarize this transcription concisely.\""
```

---

## Task 5: Auto-summary inherits the same summary prompt

**Files:**
- Test: `server/backend/tests/test_llm_prompt_config.py` (append)
- Modify: `server/backend/core/auto_summary_engine.py:49-74`

- [ ] **Step 1: Write the failing test**

Append to `server/backend/tests/test_llm_prompt_config.py`:

```python
class TestAutoSummaryUsesSummaryPrompt:
    def test_auto_summary_sends_summary_prompt_and_no_user_prompt(self, monkeypatch):
        """Automatic and manual summaries must not be able to diverge."""
        from server.core import auto_summary_engine

        import server.database.database as database_mod

        monkeypatch.setattr(database_mod, "get_recording", lambda rid: {"id": rid})
        monkeypatch.setattr(
            database_mod,
            "get_transcription",
            lambda _rid: {"segments": [{"text": "Hello world"}]},
        )
        monkeypatch.setattr(llm, "get_llm_config", lambda: _full_config())

        seen: list[llm.LLMRequest] = []

        async def _fake_process(request):
            seen.append(request)
            return llm.LLMResponse(response="A summary.", model="test-model", tokens_used=10)

        monkeypatch.setattr(llm, "process_with_llm", _fake_process)

        result = asyncio.run(auto_summary_engine.summarize_for_auto_action(42, {}))

        assert result["text"] == "A summary."
        assert seen[0].system_prompt == "Summary prompt"
        assert seen[0].user_prompt is None
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd server/backend && ../../build/.venv/bin/pytest tests/test_llm_prompt_config.py::TestAutoSummaryUsesSummaryPrompt -v --tb=short
```

Expected: FAIL — `seen[0].system_prompt` is `None`.

- [ ] **Step 3: Update the engine**

In `server/backend/core/auto_summary_engine.py`, extend the local import block (lines 49-56) with `get_llm_config`:

```python
    from fastapi import HTTPException
    from server.api.routes.llm import (
        _VERBATIM_DIRECTIVE,
        LLMRequest,
        _build_alias_aware_transcript_text,
        get_llm_config,
        process_with_llm,
    )
    from server.database.database import get_recording, get_transcription
```

Replace lines 70-74:

```python
    custom_prompt = public_fields.get("summary_prompt_template")
    request = LLMRequest(
        transcription_text=full_text,
        user_prompt=custom_prompt or None,
    )
```

with:

```python
    # GH-254 — the per-profile ``summary_prompt_template`` was dead config
    # (never editable in any UI, always None). Automatic summaries use the
    # same global summary prompt as manual ones so the two cannot diverge.
    config = get_llm_config()
    request = LLMRequest(
        transcription_text=full_text,
        system_prompt=config["summary_system_prompt"],
    )
```

Also update the docstring of `summarize_for_auto_action` to note that `public_fields` is retained for coordinator compatibility but no longer read for the prompt.

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd server/backend && ../../build/.venv/bin/pytest tests/test_llm_prompt_config.py tests/test_auto_summary_truncation.py tests/test_auto_action_coordinator.py -v --tb=short
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add server/backend/core/auto_summary_engine.py server/backend/tests/test_llm_prompt_config.py
git commit -m "feat(server): auto-summary uses the global summary prompt (GH-254)

* feat(server): auto_summary_engine passes summary_system_prompt and stops reading the dead per-profile summary_prompt_template"
```

---

## Task 6: Delete the dead profile configuration

**Files:**
- Test: `server/backend/tests/test_profile_public_fields.py` (create)
- Modify: `server/backend/api/routes/profiles.py:99-100`
- Modify: `server/backend/tests/test_profile_repository.py:48-49`, `test_create_job_profile_snapshot.py:48-49`, `test_reexport_endpoint.py:73-74`, `test_profile_snapshot_durability.py:47-48`, `test_delete_recording_artifacts.py:105-106`
- Modify: `dashboard/src/api/client.ts:54-62`, `dashboard/src/services/profileDefaults.ts:9-31`

- [ ] **Step 1: Write the failing test**

Create `server/backend/tests/test_profile_public_fields.py`:

```python
"""GH-254 — the dead per-profile summary configuration is gone.

``summary_prompt_template`` and ``summary_model_id`` were declared on
``ProfilePublicFields`` but were never editable in any UI (recording profiles
support create + delete only) and were read by nothing except a single
``.get()`` in the auto-summary engine that could only ever return None.

No migration is needed: ``public_fields`` is a JSON blob and the model sets
``extra="allow"``, so keys already written into existing rows keep round
tripping as extras — they are simply never read again.
"""

from server.api.routes.profiles import ProfilePublicFields


class TestDeadSummaryConfigRemoved:
    def test_fields_are_no_longer_declared(self):
        assert "summary_prompt_template" not in ProfilePublicFields.model_fields
        assert "summary_model_id" not in ProfilePublicFields.model_fields

    def test_live_fields_survive(self):
        for name in (
            "filename_template",
            "destination_folder",
            "auto_summary_enabled",
            "auto_export_enabled",
            "export_format",
        ):
            assert name in ProfilePublicFields.model_fields

    def test_legacy_keys_in_stored_rows_still_round_trip(self):
        """Existing profile rows must not fail validation after the removal."""
        fields = ProfilePublicFields(
            **{"summary_prompt_template": "old value", "summary_model_id": "old-model"}
        )
        dumped = fields.model_dump()
        assert dumped["summary_prompt_template"] == "old value"
        assert dumped["summary_model_id"] == "old-model"
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd server/backend && ../../build/.venv/bin/pytest tests/test_profile_public_fields.py -v --tb=short
```

Expected: `test_fields_are_no_longer_declared` FAILS (both keys are still declared); the other two pass.

- [ ] **Step 3: Remove the fields from the model**

In `server/backend/api/routes/profiles.py`, delete these two lines from `ProfilePublicFields` (lines 99-100):

```python
    summary_model_id: str | None = None
    summary_prompt_template: str | None = None
```

- [ ] **Step 4: Remove the keys from the five backend fixtures**

In each of `server/backend/tests/test_profile_repository.py`, `test_create_job_profile_snapshot.py`, `test_reexport_endpoint.py`, `test_profile_snapshot_durability.py`, `test_delete_recording_artifacts.py`, delete the two dict entries:

```python
        "summary_model_id": None,
        "summary_prompt_template": None,
```

- [ ] **Step 5: Remove them from the dashboard types**

In `dashboard/src/api/client.ts`, delete from `ProfilePublicFields` (lines 59-60):

```ts
  summary_model_id: string | null;
  summary_prompt_template: string | null;
```

In `dashboard/src/services/profileDefaults.ts`, delete the same two members from the `ProfilePublicFieldDefaults` interface and the two entries from the object returned by `defaultPublicFields`.

- [ ] **Step 6: Run the tests to verify they pass**

```bash
cd server/backend && ../../build/.venv/bin/pytest tests/test_profile_public_fields.py tests/test_profile_repository.py tests/test_create_job_profile_snapshot.py tests/test_reexport_endpoint.py tests/test_profile_snapshot_durability.py tests/test_delete_recording_artifacts.py tests/test_profile_routes.py -v --tb=short
```

Expected: all pass.

```bash
cd dashboard && npx tsc --noEmit -p tsconfig.json
```

Expected: no errors. If `EmptyProfileForm.tsx` or any test references a removed member, fix the reference — do not re-add the field.

- [ ] **Step 7: Commit**

```bash
git add server/backend/api/routes/profiles.py server/backend/tests dashboard/src/api/client.ts dashboard/src/services/profileDefaults.ts
git commit -m "refactor(server, dashboard): drop dead per-profile summary config (GH-254)

* refactor(server): remove summary_prompt_template and summary_model_id from ProfilePublicFields
  * neither was editable anywhere — recording profiles support create and delete only — and summary_model_id was read by nothing at all
  * no migration: public_fields is a JSON blob with extra=allow, so keys already stored keep round-tripping as extras

* refactor(dashboard): drop the same two members from ProfilePublicFields and profileDefaults"
```

---

## Task 7: `AiPromptsSection` component

**Files:**
- Create: `dashboard/components/views/settings/AiPromptsSection.tsx`
- Test: `dashboard/components/views/settings/__tests__/AiPromptsSection.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `dashboard/components/views/settings/__tests__/AiPromptsSection.test.tsx`:

```tsx
/**
 * AiPromptsSection — Settings → AI prompt editors (GH-254).
 *
 * Presentational component: props in, callbacks out. What matters is that
 * edits propagate verbatim and that Reset emits the server-supplied default
 * rather than a hardcoded copy of the prompt text.
 */

import React from 'react';
import { render, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';

import { AiPromptsSection } from '../AiPromptsSection';

const DEFAULTS = {
  summaryDefault: 'Summarize this transcription concisely.',
  chatDefault: 'You are a helpful assistant.',
};

describe('AiPromptsSection', () => {
  it('renders the current prompt values', () => {
    const { getByLabelText } = render(
      <AiPromptsSection
        summaryPrompt="Fasse auf Deutsch zusammen."
        chatPrompt="Answer in English."
        onSummaryPromptChange={vi.fn()}
        onChatPromptChange={vi.fn()}
        {...DEFAULTS}
      />,
    );

    expect((getByLabelText('AI summary prompt') as HTMLTextAreaElement).value).toBe(
      'Fasse auf Deutsch zusammen.',
    );
    expect((getByLabelText('AI chat prompt') as HTMLTextAreaElement).value).toBe(
      'Answer in English.',
    );
  });

  it('emits edits to the summary prompt', () => {
    const onSummaryPromptChange = vi.fn();
    const { getByLabelText } = render(
      <AiPromptsSection
        summaryPrompt=""
        chatPrompt=""
        onSummaryPromptChange={onSummaryPromptChange}
        onChatPromptChange={vi.fn()}
        {...DEFAULTS}
      />,
    );

    fireEvent.change(getByLabelText('AI summary prompt'), {
      target: { value: 'Bullet points only.' },
    });

    expect(onSummaryPromptChange).toHaveBeenCalledWith('Bullet points only.');
  });

  it('emits edits to the chat prompt', () => {
    const onChatPromptChange = vi.fn();
    const { getByLabelText } = render(
      <AiPromptsSection
        summaryPrompt=""
        chatPrompt=""
        onSummaryPromptChange={vi.fn()}
        onChatPromptChange={onChatPromptChange}
        {...DEFAULTS}
      />,
    );

    fireEvent.change(getByLabelText('AI chat prompt'), { target: { value: 'Be terse.' } });

    expect(onChatPromptChange).toHaveBeenCalledWith('Be terse.');
  });

  it('reset emits the server-supplied default, not a hardcoded copy', () => {
    const onSummaryPromptChange = vi.fn();
    const onChatPromptChange = vi.fn();
    const { getByLabelText } = render(
      <AiPromptsSection
        summaryPrompt="Custom."
        chatPrompt="Custom."
        onSummaryPromptChange={onSummaryPromptChange}
        onChatPromptChange={onChatPromptChange}
        {...DEFAULTS}
      />,
    );

    fireEvent.click(getByLabelText('Reset AI summary prompt to default'));
    fireEvent.click(getByLabelText('Reset AI chat prompt to default'));

    expect(onSummaryPromptChange).toHaveBeenCalledWith(DEFAULTS.summaryDefault);
    expect(onChatPromptChange).toHaveBeenCalledWith(DEFAULTS.chatDefault);
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd dashboard && npx vitest run components/views/settings/__tests__/AiPromptsSection.test.tsx
```

Expected: FAIL — cannot resolve `../AiPromptsSection`. If the run errors with `ERR_REQUIRE_ESM`, you are on the wrong Node: run `nvm use` (Node 22) first.

- [ ] **Step 3: Write the component**

Create `dashboard/components/views/settings/AiPromptsSection.tsx`:

```tsx
/**
 * AI prompt editors for Settings → AI (GH-254).
 *
 * Renders the *contents* of a Section; SettingsModal supplies the
 * <Section title="Prompts"> wrapper. Kept out of SettingsModal.tsx because
 * that file is already ~2450 lines and a render test of it would need
 * roughly twenty mocks — this one needs none.
 *
 * The default texts are supplied by the server (GET /api/llm/status) rather
 * than hardcoded here, so "Reset to default" can never drift from what the
 * backend actually falls back to.
 */

import React from 'react';
import { RotateCw } from 'lucide-react';
import { Button } from '../../ui/Button';

interface AiPromptsSectionProps {
  summaryPrompt: string;
  chatPrompt: string;
  summaryDefault: string;
  chatDefault: string;
  onSummaryPromptChange: (value: string) => void;
  onChatPromptChange: (value: string) => void;
}

const TEXTAREA_CLASS =
  'focus:border-accent-cyan/50 w-full resize-y rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-sm text-white placeholder-slate-600 focus:outline-none';

export const AiPromptsSection: React.FC<AiPromptsSectionProps> = ({
  summaryPrompt,
  chatPrompt,
  summaryDefault,
  chatDefault,
  onSummaryPromptChange,
  onChatPromptChange,
}) => (
  <>
    <div>
      <div className="mb-2 flex items-center justify-between gap-3">
        <label htmlFor="ai-summary-prompt" className="text-sm text-slate-200">
          AI summary prompt
        </label>
        <Button
          variant="secondary"
          size="sm"
          icon={<RotateCw size={14} />}
          aria-label="Reset AI summary prompt to default"
          onClick={() => onSummaryPromptChange(summaryDefault)}
        >
          Reset to default
        </Button>
      </div>
      <p className="mb-3 text-xs text-slate-400">
        System prompt used when a recording is summarised — both the Generate button in a note and
        the automatic summary after transcription.
      </p>
      <textarea
        id="ai-summary-prompt"
        aria-label="AI summary prompt"
        rows={4}
        value={summaryPrompt}
        onChange={(e) => onSummaryPromptChange(e.target.value)}
        placeholder={summaryDefault}
        className={TEXTAREA_CLASS}
      />
    </div>

    <div>
      <div className="mb-2 flex items-center justify-between gap-3">
        <label htmlFor="ai-chat-prompt" className="text-sm text-slate-200">
          AI chat prompt
        </label>
        <Button
          variant="secondary"
          size="sm"
          icon={<RotateCw size={14} />}
          aria-label="Reset AI chat prompt to default"
          onClick={() => onChatPromptChange(chatDefault)}
        >
          Reset to default
        </Button>
      </div>
      <p className="mb-3 text-xs text-slate-400">
        System message that opens every conversation in a note's AI chat panel.
      </p>
      <textarea
        id="ai-chat-prompt"
        aria-label="AI chat prompt"
        rows={4}
        value={chatPrompt}
        onChange={(e) => onChatPromptChange(e.target.value)}
        placeholder={chatDefault}
        className={TEXTAREA_CLASS}
      />
    </div>
  </>
);
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd dashboard && npx vitest run components/views/settings/__tests__/AiPromptsSection.test.tsx
```

Expected: 4 passed. (`Button` extends `React.ButtonHTMLAttributes` and spreads `...props` onto the underlying `<button>`, so `aria-label` reaches the DOM — no wrapper needed.)

- [ ] **Step 5: Commit**

```bash
git add dashboard/components/views/settings
git commit -m "feat(dashboard): add AiPromptsSection for the summary and chat prompts (GH-254)

* feat(dashboard): presentational prompt editors with Reset to default driven by the server-supplied defaults, so the dashboard never holds a second copy of the prompt text"
```

---

## Task 8: Wire the prompts into Settings → AI

**Files:**
- Modify: `dashboard/src/api/types.ts:444-453`
- Modify: `dashboard/components/views/SettingsModal.tsx` (state ~191, load effect ~284-312, `renderAITab` ~2118)

- [ ] **Step 1: Add the status fields to the API type**

In `dashboard/src/api/types.ts`, inside `interface LLMStatus`, after `auto_title_enabled`:

```ts
  summary_system_prompt?: string | null;
  summary_system_prompt_default?: string | null;
  chat_system_prompt?: string | null;
  chat_system_prompt_default?: string | null;
```

- [ ] **Step 2: Add component state**

In `dashboard/components/views/SettingsModal.tsx`, after `const [aiAutoTitle, setAiAutoTitle] = useState(true);` (line 192):

```tsx
  // GH-254 — editable summary/chat prompts. The *Default values come from the
  // server so "Reset to default" cannot drift from the backend fallback.
  const [aiSummaryPrompt, setAiSummaryPrompt] = useState('');
  const [aiChatPrompt, setAiChatPrompt] = useState('');
  const [aiSummaryPromptDefault, setAiSummaryPromptDefault] = useState('');
  const [aiChatPromptDefault, setAiChatPromptDefault] = useState('');
```

- [ ] **Step 3: Seed them in the AI-tab load effect**

In the `.then((status) => { … })` block of the AI-tab load effect (starting line 284), after the `auto_title_enabled` handling:

```tsx
        if (status.summary_system_prompt != null) {
          setAiSummaryPrompt(status.summary_system_prompt);
        }
        if (status.chat_system_prompt != null) {
          setAiChatPrompt(status.chat_system_prompt);
        }
        if (status.summary_system_prompt_default != null) {
          setAiSummaryPromptDefault(status.summary_system_prompt_default);
        }
        if (status.chat_system_prompt_default != null) {
          setAiChatPromptDefault(status.chat_system_prompt_default);
        }
```

- [ ] **Step 4: Render the section**

Add the import next to the other component imports at the top of the file:

```tsx
import { AiPromptsSection } from './settings/AiPromptsSection';
```

In `renderAITab`, between the `<Section title="Model">` block and `<Section title="Automatic Title Generation">` (line 2120):

```tsx
        <Section title="Prompts">
          <AiPromptsSection
            summaryPrompt={aiSummaryPrompt}
            chatPrompt={aiChatPrompt}
            summaryDefault={aiSummaryPromptDefault}
            chatDefault={aiChatPromptDefault}
            onSummaryPromptChange={(value) => {
              setAiSummaryPrompt(value);
              handleAiFieldChange('summary_system_prompt', value);
            }}
            onChatPromptChange={(value) => {
              setAiChatPrompt(value);
              handleAiFieldChange('chat_system_prompt', value);
            }}
          />
        </Section>
```

- [ ] **Step 5: Update the tab's Notes section**

The AI tab's Notes list (line ~2149) says "Changes take effect after server restart." That is wrong for prompts — `get_llm_config()` re-reads on every call and the modal already posts `/api/llm/config/reload` on save. Add a bullet after the first one:

```tsx
            <li>Prompt changes apply to the next summary or chat — no restart needed.</li>
```

- [ ] **Step 6: Verify types and the existing suite**

```bash
cd dashboard && npx tsc --noEmit -p tsconfig.json && npx vitest run
```

Expected: no type errors; all existing tests still pass.

- [ ] **Step 7: Commit**

```bash
git add dashboard/src/api/types.ts dashboard/components/views/SettingsModal.tsx
git commit -m "feat(dashboard): editable AI summary and chat prompts in Settings (GH-254)

* feat(dashboard): render AiPromptsSection in the AI tab, wired to local_llm.summary_system_prompt and local_llm.chat_system_prompt

* feat(dashboard): seed both prompts and their defaults from GET /api/llm/status

* docs(dashboard): note that prompt changes need no server restart"
```

---

## Task 9: Show the stored summary on open, delete the fake typewriter

**Files:**
- Test: `dashboard/components/views/__tests__/AudioNoteModal.summary.test.tsx` (create)
- Modify: `dashboard/components/views/AudioNoteModal.tsx:463`, `:742-744`, `:856-926`

- [ ] **Step 1: Write the failing test**

Create `dashboard/components/views/__tests__/AudioNoteModal.summary.test.tsx`:

```tsx
/**
 * AudioNoteModal — AI summary panel wiring (GH-254).
 *
 * The row has always been persisted (recordings.summary). The defect was that
 * the modal cleared the panel on open, always labelled the control "Generate
 * AI Summary", and replayed the STORED text through a 15ms/char typewriter —
 * which looked and felt exactly like a fresh generation.
 *
 * What we verify here is the wiring:
 *   1. A stored summary renders immediately, with no call to the LLM.
 *   2. No stored summary leaves the collapsed Generate button in place.
 *   3. Regenerate confirms, then streams.
 *   4. A failed stream restores the previous text instead of leaving an error
 *      where the summary was.
 */

import React from 'react';
import { render, act, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

// ── Hoisted controllable state ────────────────────────────────────────────

let mockRecording: Record<string, unknown> | null = null;
const mockRefresh = vi.fn();
const mockConfirm = vi.fn().mockResolvedValue(true);

// ── Heavy mocks (mirror AudioNoteModal hook surface) ───────────────────────

vi.mock('../../../src/hooks/useRecording', () => ({
  useRecording: () => ({
    recording: mockRecording,
    transcription: { recording_id: 1, segments: [] },
    loading: false,
    error: null,
    refresh: mockRefresh,
    audioUrl: null,
  }),
}));

vi.mock('../../../src/hooks/useDiarizationConfidence', () => ({
  useDiarizationConfidence: () => ({ turns: [], loading: false, error: null }),
}));

vi.mock('../../../src/hooks/useDiarizationReview', () => ({
  useDiarizationReview: () => ({
    state: { recording_id: 1, status: null, reviewed_turns_json: null },
    refresh: vi.fn(),
    triggerOpen: vi.fn(),
    triggerComplete: vi.fn(),
  }),
}));

vi.mock('../../../src/hooks/useRecordingAliases', () => ({
  useRecordingAliases: () => ({
    aliases: [],
    aliasMap: new Map(),
    setAliases: vi.fn().mockResolvedValue(undefined),
    refresh: vi.fn(),
  }),
}));

vi.mock('../../../src/hooks/useWordHighlighter', () => ({
  useWordHighlighter: () => ({ activeWordIndex: -1, registerWord: vi.fn(), scrollTo: vi.fn() }),
}));

vi.mock('../../../src/hooks/useConfirm', () => ({
  useConfirm: () => ({ confirm: mockConfirm, dialog: null }),
}));

vi.mock('../../../src/hooks/useAutoActionRetry', () => ({
  useAutoActionRetry: () => ({ mutate: vi.fn(), isPending: false, error: null }),
}));

vi.mock('../../../src/stores/activeProfileStore', () => ({
  useActiveProfileStore: (selector?: (s: { activeProfileId: number | null }) => unknown) => {
    const state = { activeProfileId: null };
    return typeof selector === 'function' ? selector(state) : state;
  },
}));

vi.mock('../../../src/hooks/useAriaAnnouncer', () => ({
  useAriaAnnouncer: () => vi.fn(),
}));

const mockSummarizeStream = vi.fn();

vi.mock('../../../src/api/client', () => ({
  apiClient: {
    listConversations: vi.fn().mockResolvedValue({ conversations: [] }),
    getConversation: vi.fn().mockResolvedValue({ id: 0, title: '', messages: [] }),
    createConversation: vi.fn().mockResolvedValue({ id: 1, title: 'New Chat' }),
    updateConversation: vi.fn().mockResolvedValue(undefined),
    deleteConversation: vi.fn().mockResolvedValue(undefined),
    deleteMessagesFrom: vi.fn().mockResolvedValue(undefined),
    generateConversationTitle: vi.fn().mockResolvedValue({ title: '' }),
    chat: vi.fn(),
    summarizeRecordingStream: (...args: unknown[]) => mockSummarizeStream(...args),
    summarizeRecording: vi.fn().mockResolvedValue({ summary: '' }),
    getAudioUrl: vi.fn().mockReturnValue(null),
    getAvailableModels: vi.fn().mockResolvedValue({ models: [] }),
    getLLMStatus: vi.fn().mockResolvedValue({ available: true, model: 'test-model' }),
    deleteRecording: vi.fn().mockResolvedValue(undefined),
    updateRecordingTitle: vi.fn().mockResolvedValue(undefined),
    updateRecordingDate: vi.fn().mockResolvedValue(undefined),
    updateRecordingSummary: vi.fn().mockResolvedValue(undefined),
    updateRecordingCorrectedTranscript: vi.fn().mockResolvedValue(undefined),
    getExportUrl: vi.fn().mockReturnValue('http://localhost/export'),
    retryAutoAction: vi.fn().mockResolvedValue({ status: 'retry_initiated' }),
  },
}));

vi.mock('../../../src/config/store', () => ({
  getConfig: vi.fn().mockResolvedValue(undefined),
  setConfig: vi.fn().mockResolvedValue(undefined),
}));

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
}));

vi.mock('react-markdown', () => ({
  default: ({ children }: { children: React.ReactNode }) =>
    React.createElement('div', null, children),
}));
vi.mock('remark-gfm', () => ({ default: () => undefined }));

// ── Imports after mocks ───────────────────────────────────────────────────

import { AudioNoteModal } from '../AudioNoteModal';

// ── Helpers ────────────────────────────────────────────────────────────────

function createWrapper(): ({ children }: { children: React.ReactNode }) => React.ReactElement {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }) =>
    React.createElement(QueryClientProvider, { client: qc }, children) as React.ReactElement;
}

const NOTE = { title: 'Test Recording', date: '2026-05-04', duration: '00:60', recordingId: 1 };

const BASE_RECORDING = {
  id: 1,
  filename: 'test.wav',
  filepath: '/data/test.wav',
  title: 'Test Recording',
  duration_seconds: 60,
  recorded_at: '2026-05-04T12:00:00Z',
  imported_at: null,
  word_count: 5,
  has_diarization: false,
  summary: null,
  summary_model: null,
  transcript_corrected: null,
  transcription_backend: 'whisper',
  auto_summary_status: null,
  auto_export_status: null,
  webhook_status: null,
};

/** Flush the modal's portal effect and its double-rAF open animation. */
async function openModal() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await new Promise((r) => requestAnimationFrame(r));
    await new Promise((r) => requestAnimationFrame(r));
    await Promise.resolve();
  });
}

// ── Tests ──────────────────────────────────────────────────────────────────

describe('AudioNoteModal — stored summary (GH-254)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockConfirm.mockResolvedValue(true);
    mockRecording = null;
    document.body.innerHTML = '';
  });

  it('renders a stored summary immediately without calling the LLM', async () => {
    mockRecording = { ...BASE_RECORDING, summary: 'Stored summary text.', summary_model: 'qwen3' };

    render(React.createElement(AudioNoteModal, { isOpen: true, onClose: vi.fn(), note: NOTE }), {
      wrapper: createWrapper(),
    });
    await openModal();

    expect(document.body.textContent).toContain('Stored summary text.');
    expect(document.body.textContent).not.toContain('Generate AI Summary');
    expect(mockSummarizeStream).not.toHaveBeenCalled();
  });

  it('keeps the collapsed Generate button when nothing is stored', async () => {
    mockRecording = { ...BASE_RECORDING, summary: null };

    render(React.createElement(AudioNoteModal, { isOpen: true, onClose: vi.fn(), note: NOTE }), {
      wrapper: createWrapper(),
    });
    await openModal();

    expect(document.body.textContent).toContain('Generate AI Summary');
    expect(mockSummarizeStream).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd dashboard && npx vitest run components/views/__tests__/AudioNoteModal.summary.test.tsx
```

Expected: the first test FAILS — the body contains "Generate AI Summary" and not the stored text, because the open effect clears the panel.

- [ ] **Step 3: Add the generation ref and setter**

In `AudioNoteModal.tsx`, replace line 463:

```tsx
  const [isGenerating, setIsGenerating] = useState(false);
```

with:

```tsx
  const [isGenerating, setIsGenerating] = useState(false);
  // GH-254 — the seeding effect must read the CURRENT generating state without
  // taking it as a dependency: as a dependency it would re-run when a stream
  // finishes and overwrite the fresh text with the stale recording.summary.
  const isGeneratingRef = useRef(false);
  const setGenerating = useCallback((value: boolean) => {
    isGeneratingRef.current = value;
    setIsGenerating(value);
  }, []);
```

Then replace every other `setIsGenerating(` call in the file with `setGenerating(`. In the original file they are at lines 744, 868, 890, 904, 921 and 925; the ones at 868/890/904 sit inside the effect that Step 5 rewrites wholesale, so after this task the only remaining callers are the mount effect, `handleGenerateSummary`, `handleStopGeneration` and the new streaming effect. Verify with `grep -n "setIsGenerating(" dashboard/components/views/AudioNoteModal.tsx` — the only hit left must be the `useState` declaration itself.

- [ ] **Step 4: Replace the open-effect reset with a seeding effect**

Delete these two lines from the `isOpen` branch of the mount effect (lines 742-743):

```tsx
      setSummaryExpanded(false);
      setSummaryText('');
```

Keep `setGenerating(false);` on the line below them.

Then add this effect immediately after the mount effect:

```tsx
  // GH-254 — seed the summary panel from the persisted recording.
  //
  // Reset and populate MUST live in the same effect. The modal stays mounted
  // between open and close (isRendered holds it for the exit animation), so
  // useRecording does not refetch when the same note is reopened; a separate
  // reset would clear the text and this effect would not re-run to restore it.
  useEffect(() => {
    if (!isOpen || isGeneratingRef.current) return;
    const stored = (recording?.summary as string | null) ?? '';
    setSummaryText(stored);
    setSummaryExpanded(Boolean(stored));
    setSummaryError(null);
  }, [isOpen, note?.recordingId, recording?.summary]);
```

Add the error state next to the other summary state (after line 466):

```tsx
  // GH-254 — generation failures render as their own line instead of being
  // written into summaryText, where an edit-save would persist the error.
  const [summaryError, setSummaryError] = useState<string | null>(null);
```

- [ ] **Step 5: Delete the typewriter branches from the generation effect**

Replace the whole effect at lines 856-910 with:

```tsx
  // Stream a new summary from the API. Stored summaries never reach this
  // effect — they are seeded above (GH-254).
  useEffect(() => {
    if (!isGenerating) return;

    if (!note?.recordingId) {
      setSummaryError('Open a synced recording to generate an AI summary.');
      setGenerating(false);
      return;
    }

    let cancelled = false;
    const previous = (recording?.summary as string | null) ?? '';
    (async () => {
      try {
        const stream = apiClient.summarizeRecordingStream(note.recordingId!);
        let text = '';
        for await (const chunk of stream) {
          if (cancelled) break;
          text += chunk;
          setSummaryText(text);
        }
      } catch {
        if (!cancelled) {
          // Never leave the error where the summary was: the row is untouched
          // on failure, so restore what the user had (CLAUDE.md — no data loss).
          setSummaryError('Failed to generate summary. Is the AI provider running?');
          setSummaryText(previous);
        }
      } finally {
        if (!cancelled) {
          setGenerating(false);
          // Re-sync summary + summary_model from the row the server just wrote.
          refresh();
          onRecordingMutated?.();
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [isGenerating, note?.recordingId]);
```

`refresh` is not currently destructured from `useRecording`. Add it at line 621-626:

```tsx
  const {
    recording,
    transcription,
    loading: recordingLoading,
    audioUrl,
    refresh,
  } = useRecording(note?.recordingId ?? null);
```

- [ ] **Step 6: Clear the error when a generation starts**

Replace `handleGenerateSummary` (lines 919-922) with:

```tsx
  const handleGenerateSummary = () => {
    setSummaryError(null);
    setSummaryExpanded(true);
    setGenerating(true);
  };
```

- [ ] **Step 7: Render the error line**

In the summary panel JSX, immediately after the `renderLlmResponseContent({...})` / textarea conditional (after line 2309), add:

```tsx
                      {summaryError && (
                        <p role="alert" className="mt-2 text-xs text-red-400">
                          {summaryError}
                        </p>
                      )}
```

- [ ] **Step 8: Run the test to verify it passes**

```bash
cd dashboard && npx vitest run components/views/__tests__/AudioNoteModal.summary.test.tsx
```

Expected: 2 passed.

- [ ] **Step 9: Commit**

```bash
git add dashboard/components/views/AudioNoteModal.tsx dashboard/components/views/__tests__/AudioNoteModal.summary.test.tsx
git commit -m "fix(dashboard): show the persisted AI summary on reopen (GH-254)

* fix(dashboard): seed the summary panel from recording.summary in a single effect that owns both reset and populate
  * the modal stays mounted between open and close, so a separate reset left the panel permanently empty on reopening the same note

* fix(dashboard): delete the 15ms/char typewriter replay of stored summaries
  * a 2000-character summary took 30 seconds to display and was indistinguishable from a fresh generation

* fix(dashboard): render generation failures as their own line instead of writing them into the summary text"
```

---

## Task 10: Regenerate control

**Files:**
- Test: `dashboard/components/views/__tests__/AudioNoteModal.summary.test.tsx` (append)
- Modify: `dashboard/components/views/AudioNoteModal.tsx` (handlers ~924, JSX ~2250)

- [ ] **Step 1: Write the failing test**

Append inside the existing `describe` block in `AudioNoteModal.summary.test.tsx`:

```tsx
  it('regenerate confirms and then streams a fresh summary', async () => {
    mockRecording = { ...BASE_RECORDING, summary: 'Old summary.' };
    mockSummarizeStream.mockImplementation(async function* () {
      yield 'New ';
      yield 'summary.';
    });

    render(React.createElement(AudioNoteModal, { isOpen: true, onClose: vi.fn(), note: NOTE }), {
      wrapper: createWrapper(),
    });
    await openModal();

    const button = document.body.querySelector(
      '[aria-label="Regenerate summary"]',
    ) as HTMLButtonElement;
    expect(button).toBeTruthy();

    await act(async () => {
      fireEvent.click(button);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(mockConfirm).toHaveBeenCalled();
    expect(mockSummarizeStream).toHaveBeenCalledWith(1);
    expect(document.body.textContent).toContain('New summary.');
  });

  it('a failed regeneration restores the previous summary', async () => {
    mockRecording = { ...BASE_RECORDING, summary: 'Old summary.' };
    mockSummarizeStream.mockImplementation(() => {
      throw new Error('provider offline');
    });

    render(React.createElement(AudioNoteModal, { isOpen: true, onClose: vi.fn(), note: NOTE }), {
      wrapper: createWrapper(),
    });
    await openModal();

    await act(async () => {
      fireEvent.click(
        document.body.querySelector('[aria-label="Regenerate summary"]') as HTMLButtonElement,
      );
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(document.body.textContent).toContain('Old summary.');
    expect(document.body.textContent).toContain('Failed to generate summary');
  });

  it('declining the confirmation does not stream', async () => {
    mockRecording = { ...BASE_RECORDING, summary: 'Old summary.' };
    mockConfirm.mockResolvedValue(false);

    render(React.createElement(AudioNoteModal, { isOpen: true, onClose: vi.fn(), note: NOTE }), {
      wrapper: createWrapper(),
    });
    await openModal();

    await act(async () => {
      fireEvent.click(
        document.body.querySelector('[aria-label="Regenerate summary"]') as HTMLButtonElement,
      );
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(mockSummarizeStream).not.toHaveBeenCalled();
    expect(document.body.textContent).toContain('Old summary.');
  });
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd dashboard && npx vitest run components/views/__tests__/AudioNoteModal.summary.test.tsx
```

Expected: the three new tests FAIL — no element matches `[aria-label="Regenerate summary"]`.

- [ ] **Step 3: Add the handler**

In `AudioNoteModal.tsx`, after `handleStopGeneration` (line 926):

```tsx
  // GH-254 — the server always regenerates when the stream endpoint is called;
  // the "don't regenerate" behaviour is purely this component's short-circuit
  // on a stored summary. Confirm first because this overwrites hand edits.
  const handleRegenerateSummary = useCallback(async () => {
    if (!note?.recordingId || isGenerating) return;
    if (
      !(await confirm('Regenerate the summary? The current one will be replaced.', {
        danger: true,
        confirmLabel: 'Regenerate',
      }))
    )
      return;
    setSummaryError(null);
    setSummaryText('');
    setSummaryExpanded(true);
    setGenerating(true);
  }, [note?.recordingId, isGenerating, confirm, setGenerating]);
```

- [ ] **Step 4: Add the button**

In the summary panel header, immediately before the existing "Edit summary" button (line 2250):

```tsx
                          {!isGenerating && summaryText && !isSummaryEditing && (
                            <button
                              onClick={() => void handleRegenerateSummary()}
                              className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-white/10 hover:text-white"
                              title="Regenerate summary"
                              aria-label="Regenerate summary"
                            >
                              <RotateCw size={14} />
                            </button>
                          )}
```

`RotateCw` is already imported at AudioNoteModal.tsx:28 — do not add a duplicate import.

- [ ] **Step 5: Run the test to verify it passes**

```bash
cd dashboard && npx vitest run components/views/__tests__/AudioNoteModal.summary.test.tsx
```

Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add dashboard/components/views/AudioNoteModal.tsx dashboard/components/views/__tests__/AudioNoteModal.summary.test.tsx
git commit -m "feat(dashboard): add a Regenerate control to the AI summary panel (GH-254)

* feat(dashboard): regenerate streams a fresh summary after a confirmation, since regeneration overwrites hand-edited text
  * before this the only way to re-run the model was Clear followed by Generate"
```

---

## Task 11: Documentation, UI contract, full verification

**Files:**
- Modify: `docs/api-contracts-server.md`
- Modify: `dashboard/ui-contract/*` (regenerated)

- [ ] **Step 1: Document the new status fields**

In `docs/api-contracts-server.md`, find the `GET /api/llm/status` entry and add a note describing the response fields:

```markdown
`GET /api/llm/status` also returns the effective prompts and their built-in
defaults (GH-254): `summary_system_prompt`, `summary_system_prompt_default`,
`chat_system_prompt`, `chat_system_prompt_default`. The dashboard's Settings →
AI tab reads these; the `*_default` pair backs "Reset to default" so the
prompt text lives only on the server. Config keys are
`local_llm.summary_system_prompt` and `local_llm.chat_system_prompt`; both fall
back to the legacy `local_llm.default_system_prompt` before their built-in.
```

- [ ] **Step 2: Refresh the UI contract**

```bash
cd dashboard
npm run ui:contract:extract
npm run ui:contract:build
```

Then bump `meta.spec_version` in the contract YAML (patch bump), and only then:

```bash
node scripts/ui-contract/validate-contract.mjs --update-baseline
npm run ui:contract:check
```

Expected: `ui:contract:check` passes. If validation fails with `semver_bump_required`, the version bump was missed — bump it and re-run `--update-baseline`. If the YAML ends up corrupt, `git checkout --` the contract files and redo the sequence from `extract`.

- [ ] **Step 3: Run the full backend suite**

```bash
cd server/backend && ../../build/.venv/bin/pytest tests/ -v --tb=short
```

Expected: all pass. The project rule is the **full** suite, not a subset — prompt resolution touches the auto-action coordinator, profile snapshots and the reexport path.

- [ ] **Step 4: Run the full dashboard suite and typecheck**

```bash
cd dashboard && npx tsc --noEmit -p tsconfig.json && npx vitest run
```

Expected: no type errors, all tests pass.

- [ ] **Step 5: Commit**

```bash
git add docs/api-contracts-server.md dashboard/ui-contract
git commit -m "docs(server, dashboard): document the prompt config and refresh the UI contract (GH-254)

* docs(server): describe the four new /api/llm/status prompt fields and the two config keys

* chore(dashboard): regenerate the UI contract baseline for the prompt section and the regenerate button"
```

---

## Task 12: Manual smoke checklist (record results in the PR body)

Not automatable — the LLM provider and the Electron shell are both out of reach of the test suites.

- [ ] Open a note that already has a summary → the panel is expanded with the full text on open, instantly, and no request hits the provider.
- [ ] Close and reopen the *same* note → still expanded, still instant (this is the remount trap from Task 9 Step 4).
- [ ] Open a note with no summary → collapsed "Generate AI Summary" button; clicking it streams and the text persists after closing and reopening.
- [ ] Click Regenerate → confirmation appears; accepting streams a new summary; the notebook list reflects the new text.
- [ ] Stop the AI provider, click Regenerate → the previous summary is still on screen with an error line beneath it, and the DB row is unchanged.
- [ ] Settings → AI → edit the summary prompt, save, generate a summary → the new prompt is in effect without restarting the server.
- [ ] Settings → AI → "Reset to default" on both fields → the textareas fill with the server defaults.
- [ ] Open the AI chat in a note → replies are conversational, not summaries (the Task 4 fix).

---

---

## Task 13: Open the PR and answer the issue

- [ ] **Step 1: Push the branch**

```bash
git push -u origin feat/gh254-summary-persistence-and-prompt
```

- [ ] **Step 2: Open the PR directly on GitHub**

```bash
gh pr create --title "feat(server, dashboard): persist-visible AI summaries and configurable prompts (GH-254)" --body "…"
```

The body must cover, in this order: what the issue reported vs what the code actually did (persistence existed; the modal hid it and faked a typewriter); the four shipped changes; the **behaviour change** that AI chat conversations no longer open with "Summarize this transcription concisely."; the removal of the two dead profile keys with the no-migration reasoning; and the manual smoke checklist from Task 12 as unchecked boxes for the maintainer to tick after hardware testing.

Do not write the body to a local draft file — repo rule.

- [ ] **Step 3: Reply to the issue**

Post a comment on [#254](https://github.com/homelab-00/TranscriptionSuite/issues/254) for a non-technical reader: the summary was always being saved, the bug was that the note hid it and re-typed it on every open; it now appears instantly with a Regenerate button; and the summary prompt is editable in Settings → AI, which covers the German-meeting use case. Mention that the chat prompt became editable too. Do not close the issue — the maintainer closes issues manually.

---

## Notes for the implementer

- **Never use `pip`.** Backend tests run with the build venv: `../../build/.venv/bin/pytest` from `server/backend/`.
- **Node 22 for vitest.** `ERR_REQUIRE_ESM` means you are on Node 20 — run `nvm use` in `dashboard/`.
- **Write `GH-254`, never `#254`, in dashboard source comments.** The UI-contract scanner reads `#254` as a CSS colour literal and fails the check.
- **No AI attribution** in commits, PR text or code comments — repo rule, overrides any default.
- Format hooks run on commit and will abort it if they rewrite a file; re-stage and re-commit when that happens.
