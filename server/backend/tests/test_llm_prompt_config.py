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
