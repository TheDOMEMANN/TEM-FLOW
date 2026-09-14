from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from temflow.versioned_registry import RevisionStore


def payload(object_id: str, date: str, *, status: str = "approved", supersedes: str | None = None):
    return {
        "object_kind": "node",
        "object_id": object_id,
        "observed_at": date,
        "effective_at": date,
        "status": status,
        "actor": "test-curator",
        "provenance": "test:documented-source",
        "change_reason": "test revision",
        "attributes": {"cpc_identified_lower": 1, "cpc_identified_upper": 2},
        "supersedes": supersedes,
    }


class VersionedRegistryTests(unittest.TestCase):
    def test_latest_approved_hides_newer_draft(self):
        with TemporaryDirectory() as directory:
            store = RevisionStore(Path(directory))
            approved = store.append(payload("NODE-1", "2025-01-01"))
            store.append(payload("NODE-1", "2026-01-01", status="draft", supersedes=approved.revision_id))
            self.assertEqual(store.latest("node", "NODE-1").revision_id, approved.revision_id)
            self.assertEqual(len(store.history("node", "NODE-1")), 1)
            self.assertEqual(len(store.history("node", "NODE-1", include_drafts=True)), 2)

    def test_as_of_and_prev_next_order_are_deterministic(self):
        with TemporaryDirectory() as directory:
            store = RevisionStore(Path(directory))
            first = store.append(payload("NODE-2", "2024-01-01"))
            second = store.append(payload("NODE-2", "2025-01-01", supersedes=first.revision_id))
            history = store.history("node", "NODE-2")
            self.assertEqual([row.revision_id for row in history], [first.revision_id, second.revision_id])
            self.assertEqual(store.latest("node", "NODE-2", as_of="2024-06-01").revision_id, first.revision_id)

    def test_supersession_cannot_cross_objects(self):
        with TemporaryDirectory() as directory:
            store = RevisionStore(Path(directory))
            first = store.append(payload("NODE-A", "2024-01-01"))
            with self.assertRaises(ValueError):
                store.append(payload("NODE-B", "2025-01-01", supersedes=first.revision_id))


if __name__ == "__main__":
    unittest.main()

