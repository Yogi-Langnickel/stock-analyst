import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).parents[1] / "scripts" / "reconcile_manifest.py"
SPEC = importlib.util.spec_from_file_location("reconcile_manifest", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ReconcileManifestTest(unittest.TestCase):
    def _fixtures(self, private: Path) -> tuple[Path, Path]:
        plan = {
            "issueId": "2099-W01",
            "rows": [{
                "sourceId": "row-001",
                "tab": "Aktuell",
                "rowKind": "stock_recommendation",
                "issueId": "2099-W01",
                "page": 12,
                "sourceBlock": "card-001",
                "values": ["private value excluded from fingerprint"],
            }],
        }
        inventory = {
            "schemaVersion": 3,
            "planIssueId": "2099-W01",
            "issueTabId": "DA_2099_01",
            "discoveryScope": "whole_issue",
            "documentPageCount": 100,
            "candidates": [{
                "candidateId": "candidate-001",
                "page": 12,
                "sourcePages": [12, 13],
                "sourceKind": "stock_recommendation",
                "disposition": "mapped",
                "rowSourceId": "row-001",
                "visuallyInspected": True,
            }],
        }
        plan_path = private / "plan.json"
        inventory_path = private / "candidates.json"
        plan_path.write_text(json.dumps(plan), encoding="utf-8")
        inventory_path.write_text(json.dumps(inventory), encoding="utf-8")
        return inventory_path, plan_path

    def test_key_initialization_is_private_and_never_overwrites(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            key_path = Path(directory) / "private" / "manifest.key"
            fingerprint = MODULE.initialize_key(key_path)
            self.assertEqual(len(fingerprint), 16)
            self.assertEqual(key_path.stat().st_mode & 0o777, 0o600)
            original = key_path.read_bytes()
            with self.assertRaisesRegex(MODULE.ManifestError, "refusing to overwrite"):
                MODULE.initialize_key(key_path)
            self.assertEqual(key_path.read_bytes(), original)

    def test_build_and_validate_are_keyed_deterministic_and_not_public_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            private = Path(directory) / "private"
            private.mkdir()
            candidates, plan = self._fixtures(private)
            key_path = private / "manifest.key"
            MODULE.initialize_key(key_path)
            first_path = private / "first.json"
            second_path = private / "second.json"

            first = MODULE.build(candidates, plan, first_path, key_path)
            second = MODULE.build(candidates, plan, second_path, key_path)

            self.assertEqual(first, second)
            self.assertEqual(first_path.read_bytes(), second_path.read_bytes())
            serialized = first_path.read_text(encoding="utf-8")
            self.assertNotIn("candidate-001", serialized)
            self.assertNotIn("row-001", serialized)
            old_public_guess = hashlib.sha256(
                b"stock-analyst-weekly-refresh:v3|2099-W01|candidate|candidate-001"
            ).hexdigest()[:24]
            self.assertNotEqual(first["reconciliation"][0]["candidateRef"], old_public_guess)
            result = MODULE.validate(first_path, plan, key_path)
            self.assertTrue(result["planVerified"])
            self.assertEqual(first["pagesWithCandidates"], [12, 13])
            self.assertEqual(first["reconciliation"][0]["sourcePages"], [12, 13])

            wrong_key = private / "wrong.key"
            MODULE.initialize_key(wrong_key)
            with self.assertRaisesRegex(MODULE.ManifestError, "integrity MAC"):
                MODULE.validate(first_path, plan, wrong_key)

    def test_legacy_migration_is_deterministic_with_same_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            private = Path(directory) / "private"
            private.mkdir()
            _, plan = self._fixtures(private)
            legacy = {
                "issueId": "2099-W01",
                "candidates": [{
                    "page": 12,
                    "rowKind": "stock_recommendation",
                    "sourceId": "row-001",
                    "reconciliation": "one_normalized_row",
                    "visualInspection": "complete",
                    "reviewStatus": "needs_review",
                    "sourcePages": [12, 13],
                }],
                "exceptions": [],
                "visuallyInspectedPages": [12, 13],
                "private": True,
                "sourceTextIncluded": False,
            }
            legacy_path = private / "legacy.json"
            legacy_path.write_text(json.dumps(legacy), encoding="utf-8")
            key_path = private / "manifest.key"
            MODULE.initialize_key(key_path)

            outputs = []
            for name in ("migrated-one.json", "migrated-two.json"):
                outputs.append(MODULE.migrate_legacy(
                    legacy_path, plan, "DA_2099_01", 100, private / name, key_path
                ))
            self.assertEqual(outputs[0], outputs[1])
            self.assertEqual(outputs[0]["pagesWithCandidates"], [12, 13])

    def test_manifest_wide_mac_rejects_structural_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            private = Path(directory) / "private"
            private.mkdir()
            candidates, plan = self._fixtures(private)
            key_path = private / "manifest.key"
            MODULE.initialize_key(key_path)
            manifest_path = private / "manifest.json"
            original = MODULE.build(candidates, plan, manifest_path, key_path)

            mutations = {
                "delete_reconciliation": lambda value: value.pop("reconciliation"),
                "delete_candidate": lambda value: value["reconciliation"].pop(),
                "change_page": lambda value: value["reconciliation"][0].__setitem__("page", 14),
                "change_source_kind": lambda value: value["reconciliation"][0].__setitem__(
                    "sourceKind", "derivative_card"
                ),
                "change_count": lambda value: value.__setitem__("candidateCount", 0),
                "downgrade_provenance": lambda value: value["reconciliation"][0].__setitem__(
                    "sourcePages", [12]
                ),
            }
            for label, mutate in mutations.items():
                with self.subTest(label=label):
                    tampered = json.loads(json.dumps(original))
                    mutate(tampered)
                    tampered_path = private / f"tampered-{label}.json"
                    tampered_path.write_text(json.dumps(tampered), encoding="utf-8")
                    with self.assertRaisesRegex(MODULE.ManifestError, "integrity MAC"):
                        MODULE.validate(tampered_path, plan, key_path)

    def test_key_authorized_provenance_change_still_fails_plan_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            private = Path(directory) / "private"
            private.mkdir()
            candidates, plan = self._fixtures(private)
            key_path = private / "manifest.key"
            MODULE.initialize_key(key_path)
            manifest_path = private / "manifest.json"
            manifest = MODULE.build(candidates, plan, manifest_path, key_path)
            key = MODULE._load_key(key_path)

            manifest["reconciliation"][0]["sourcePages"] = [12]
            manifest["pagesWithCandidates"] = [12]
            manifest["manifestHmacSha256"] = MODULE._manifest_mac(manifest, key)
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            with self.assertRaisesRegex(MODULE.ManifestError, "plan structure"):
                MODULE.validate(manifest_path, plan, key_path)

    def test_key_with_group_access_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            key_path = Path(directory) / "private" / "manifest.key"
            MODULE.initialize_key(key_path)
            os.chmod(key_path, 0o640)
            with self.assertRaisesRegex(MODULE.ManifestError, "deny group"):
                MODULE._load_key(key_path)

    def test_manifest_output_cannot_overwrite_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            private = Path(directory) / "private"
            private.mkdir()
            candidates, plan = self._fixtures(private)
            key_path = private / "manifest.key"
            MODULE.initialize_key(key_path)
            original = key_path.read_bytes()
            with self.assertRaisesRegex(MODULE.ManifestError, "must not overwrite"):
                MODULE.build(candidates, plan, key_path, key_path)
            self.assertEqual(key_path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
