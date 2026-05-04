"""Service-layer modules for TranscriptionSuite (Issue #104, Sprint 5).

Houses long-running coordinator services that own background tasks and
sit between the API layer and the database layer. The first inhabitant
is :mod:`server.services.webhook_worker` (Story 7.3) — a singleton
async worker that drains the ``webhook_deliveries`` queue.
"""
