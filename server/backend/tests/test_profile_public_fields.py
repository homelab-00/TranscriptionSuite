"""GH-254 — the dead per-profile summary configuration is gone.

``summary_prompt_template`` and ``summary_model_id`` were declared on
``ProfilePublicFields`` but were never editable in any UI (recording profiles
support create + delete only) and were read by nothing except a single
``.get()`` in the auto-summary engine that could only ever return None.

No migration is needed: ``public_fields`` is a JSON blob and the model sets
``extra="allow"``, so keys already written into existing rows keep round
tripping as extras — they are simply never read again.
"""

import importlib

# ``server.database.database`` must be in sys.modules before any route module is
# imported: the lazy ``__getattr__`` in server/backend/database/__init__.py
# resolves ``from server.database import X`` by importing the submodule, and if
# the submodule is not loaded yet the fromlist handler calls that same
# __getattr__ again — infinite recursion at collection time. Every other route
# test dodges this the same way (see test_profile_routes.py).
#
# Imported for its side effect via import_module rather than a plain ``import``
# statement, so the intent reads as a preload instead of an unused binding.
importlib.import_module("server.database.database")

from server.api.routes.profiles import ProfilePublicFields  # noqa: E402 — see preload above


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
