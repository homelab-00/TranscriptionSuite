"""ADR-009 lifecycle state machine (Issue #104, Story 5.6).

States::

    pending  ──► in_review  ──► completed  ──► released

Triggers (one transition per trigger; the machine NEVER skips intermediate
states — every exit path passes through ``completed``):

  - on_transcription_complete()      → insert pending (only if low-conf turns)
  - on_review_view_opened()          → pending → in_review
  - on_run_summary_now_clicked()     → in_review → completed
  - on_auto_summary_fired()          → completed → released

Predicates consumed by Stories 5.7 (banner) and 5.8 (auto-summary HOLD):

  - banner_visible(recording_id)     → status IN {'pending', 'in_review'}
  - auto_summary_is_held(recording_id) → row exists AND status != 'released'

Persistence-Before-Deliver (NFR16):
  Every public trigger calls ``diarization_review_repository.{create_review,
  update_status}`` which already commit before returning (Sprint 1 Story 1.9
  invariant). HTTP routes that invoke a trigger and then return are
  automatically Persist-Before-Deliver — no extra plumbing required.

Cross-references: FR25, FR27, FR28, R-EL10, R-EL19, R-EL20, NFR23.
"""

from __future__ import annotations

import logging

from server.database import diarization_review_repository as repo

logger = logging.getLogger(__name__)


# Allowed transitions. Key is current status (None for "row does not exist");
# value is the set of statuses we can move to.
_VALID_TRANSITIONS: dict[str | None, frozenset[str]] = {
    None: frozenset({"pending"}),
    "pending": frozenset({"in_review"}),
    "in_review": frozenset({"completed"}),
    "completed": frozenset({"released"}),
    "released": frozenset(),  # terminal
}


class IllegalReviewTransitionError(RuntimeError):
    """Raised when a trigger attempts a transition not allowed by ADR-009."""

    def __init__(self, recording_id: int, current: str | None, target: str) -> None:
        super().__init__(
            f"recording {recording_id}: cannot transition {current!r} → {target!r}; "
            f"valid targets from {current!r}: {sorted(_VALID_TRANSITIONS.get(current, set()))}"
        )
        self.recording_id = recording_id
        self.current = current
        self.target = target


def _transition(recording_id: int, target: str) -> None:
    row = repo.get_review(recording_id)
    current = row["status"] if row else None
    allowed = _VALID_TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        raise IllegalReviewTransitionError(recording_id, current, target)
    if current is None:
        repo.create_review(recording_id, status=target)
    else:
        repo.update_status(recording_id, target)


# ──────────────────────────────────────────────────────────────────────────
# Public trigger functions
# ──────────────────────────────────────────────────────────────────────────


def on_transcription_complete(recording_id: int, has_low_confidence_turn: bool) -> None:
    """Insert a ``pending`` row IFF at least one turn is low-confidence.

    Story 5.6 AC1 — when no low-confidence turns exist the banner does
    NOT appear (no row → predicates return False).
    """
    if not has_low_confidence_turn:
        return
    _transition(recording_id, "pending")


def on_review_view_opened(recording_id: int) -> bool:
    """``pending`` → ``in_review``. Returns True if a transition occurred.

    Idempotent: opening the view a second time when already ``in_review``
    is a no-op (returns False) — does NOT raise.
    """
    row = repo.get_review(recording_id)
    if not row or row["status"] != "pending":
        return False
    _transition(recording_id, "in_review")
    return True


def on_run_summary_now_clicked(recording_id: int) -> None:
    """``in_review`` → ``completed``."""
    _transition(recording_id, "completed")


def on_auto_summary_fired(recording_id: int) -> None:
    """``completed`` → ``released`` (Sprint 4 Story 6.2 will call this)."""
    _transition(recording_id, "released")


# ──────────────────────────────────────────────────────────────────────────
# Predicates
# ──────────────────────────────────────────────────────────────────────────


def banner_visible(recording_id: int) -> bool:
    """Story 5.7 — banner visibility predicate."""
    row = repo.get_review(recording_id)
    return bool(row) and row["status"] in {"pending", "in_review"}


def auto_summary_is_held(recording_id: int) -> bool:
    """Story 5.8 — auto-summary HOLD predicate.

    Returns True iff a review row exists AND its status is not yet
    ``released``. No row → no HOLD (the recording has nothing flagged).
    Manual summary callers MUST NOT consult this predicate (Story 5.8
    AC3 — manual summary is always allowed).
    """
    row = repo.get_review(recording_id)
    if not row:
        return False
    return row["status"] != "released"


def current_status(recording_id: int) -> str | None:
    """Convenience accessor for routes that need to surface state to clients."""
    row = repo.get_review(recording_id)
    return row["status"] if row else None
