#!/usr/bin/env python3
"""Negative and positive tests for the release policy used by the publishing workflow."""
from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from release_policy import PolicyError, parse_tag, validate_assets, validate_run  # noqa: E402


REPOSITORY = "rakmahefa/letsgo-recomp"
SHA = "a" * 40
VERSION = "0.7.5"


def valid_run() -> dict:
    return {
        "status": "completed",
        "conclusion": "success",
        "name": "Linux native build",
        "path": ".github/workflows/build-linux.yml",
        "event": "push",
        "head_branch": "main",
        "head_sha": SHA,
        "repository": {"full_name": REPOSITORY},
        "head_repository": {"full_name": REPOSITORY},
    }


class TagPolicyTests(unittest.TestCase):
    def test_accepts_exact_versioned_linux_tag(self) -> None:
        self.assertEqual(parse_tag("v0.7.5-linux"), VERSION)

    def test_rejects_unversioned_or_wrong_platform_tags(self) -> None:
        for tag in ("0.7.5-linux", "v0.7-linux", "v0.7.5", "v0.7.5-windows", "v0.7.5-linux-extra"):
            with self.subTest(tag=tag), self.assertRaises(PolicyError):
                parse_tag(tag)


class WorkflowRunPolicyTests(unittest.TestCase):
    def test_accepts_trusted_successful_main_push(self) -> None:
        self.assertEqual(validate_run(valid_run(), REPOSITORY), SHA)

    def test_rejects_unfinished_or_failed_runs(self) -> None:
        for field, value in (("status", "in_progress"), ("conclusion", "failure"), ("conclusion", None)):
            run = valid_run()
            run[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(PolicyError):
                validate_run(run, REPOSITORY)

    def test_rejects_untrusted_workflow_event_or_branch(self) -> None:
        for field, value in (
            ("name", "publish anything"),
            ("path", ".github/workflows/other.yml"),
            ("event", "pull_request"),
            ("head_branch", "feature/untrusted"),
        ):
            run = valid_run()
            run[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(PolicyError):
                validate_run(run, REPOSITORY)

    def test_rejects_repository_mismatch_and_short_sha(self) -> None:
        run = valid_run()
        run["repository"] = {"full_name": "attacker/other"}
        with self.assertRaises(PolicyError):
            validate_run(run, REPOSITORY)
        run = valid_run()
        run["head_repository"] = {"full_name": "attacker/other"}
        with self.assertRaises(PolicyError):
            validate_run(run, REPOSITORY)
        run = valid_run()
        run["head_sha"] = "deadbeef"
        with self.assertRaises(PolicyError):
            validate_run(run, REPOSITORY)


class WorkflowDryRunTests(unittest.TestCase):
    def test_release_workflow_is_read_only_until_explicit_publish(self) -> None:
        workflow_path = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "publish-linux.yml"
        workflow = workflow_path.read_text(encoding="utf-8")
        self.assertIn("default: true", workflow[workflow.index("      dry_run:"):workflow.index("jobs:")])
        self.assertIn("inputs.dry_run == false", workflow)
        self.assertNotIn("gh release create", workflow.split("  preflight:", 1)[1].split("  publish:", 1)[0])
        publish_job = workflow.split("  publish:", 1)[1]
        self.assertIn("contents: write", publish_job)
        self.assertIn("gh \"\u0024{args[@]}\"", publish_job)


class ArtifactPolicyTests(unittest.TestCase):
    def valid_args(self) -> dict[str, str]:
        return {
            "tag": f"v{VERSION}-linux",
            "version": VERSION,
            "source_sha": SHA,
            "manifest_sha": SHA,
            "manifest_ref": "refs/heads/main",
            "appimage_name": f"LetsGoRecomp-{VERSION}-linux-x86_64.AppImage",
            "archive_name": f"LetsGoRecomp-{VERSION}-linux-x86_64.tar.gz",
        }

    def test_accepts_matching_tag_assets_and_provenance(self) -> None:
        validate_assets(**self.valid_args())

    def test_rejects_mismatched_tag_version_commit_and_source_ref(self) -> None:
        cases = (
            {"tag": "v0.7.4-linux"},
            {"manifest_sha": "b" * 40},
            {"source_sha": "invalid"},
            {"manifest_ref": "refs/heads/feature"},
        )
        for updates in cases:
            args = self.valid_args()
            args.update(updates)
            with self.subTest(updates=updates), self.assertRaises(PolicyError):
                validate_assets(**args)

    def test_rejects_asset_filename_from_another_version(self) -> None:
        for field, value in (
            ("appimage_name", "LetsGoRecomp-0.7.4-linux-x86_64.AppImage"),
            ("archive_name", "LetsGoRecomp-0.7.4-linux-x86_64.tar.gz"),
        ):
            args = self.valid_args()
            args[field] = value
            with self.subTest(field=field), self.assertRaises(PolicyError):
                validate_assets(**args)


if __name__ == "__main__":
    unittest.main(verbosity=2)
