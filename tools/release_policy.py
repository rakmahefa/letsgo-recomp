#!/usr/bin/env python3
"""Pure release provenance/asset policy checks shared by the publisher and unit tests."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys


TAG_RE = re.compile(r"v(?P<version>[0-9]+\.[0-9]+\.[0-9]+)-linux\Z")
SHA_RE = re.compile(r"[0-9a-f]{40}\Z")


class PolicyError(ValueError):
    """A candidate fails a release policy check."""


def parse_tag(tag: str) -> str:
    match = TAG_RE.fullmatch(tag)
    if not match:
        raise PolicyError("tag must be exactly v<major>.<minor>.<patch>-linux")
    return match.group("version")


def validate_run(run: dict, expected_repository: str) -> str:
    if run.get("status") != "completed" or run.get("conclusion") != "success":
        raise PolicyError("selected workflow run is not completed successfully")
    if run.get("name") != "Linux native build":
        raise PolicyError("selected run is not named 'Linux native build'")
    if run.get("path") not in {
        ".github/workflows/build-linux.yml",
        ".github/workflows/build-linux.yml@refs/heads/main",
    }:
        raise PolicyError("selected run is not from the trusted build-linux workflow")
    if run.get("event") != "push" or run.get("head_branch") != "main":
        raise PolicyError("only a push build from main is releasable")
    if (run.get("repository") or {}).get("full_name") != expected_repository:
        raise PolicyError("workflow run repository does not match the release repository")
    if (run.get("head_repository") or {}).get("full_name") != expected_repository:
        raise PolicyError("workflow run source repository does not match the release repository")
    source_sha = run.get("head_sha", "")
    if not SHA_RE.fullmatch(source_sha):
        raise PolicyError("workflow run does not contain a full source commit SHA")
    return source_sha


def validate_assets(
    *,
    tag: str,
    version: str,
    source_sha: str,
    manifest_sha: str,
    manifest_ref: str,
    appimage_name: str,
    archive_name: str,
) -> None:
    tag_version = parse_tag(tag)
    if version != tag_version:
        raise PolicyError(f"tag version {tag_version} does not match artifact version {version}")
    if not SHA_RE.fullmatch(source_sha) or manifest_sha != source_sha:
        raise PolicyError("embedded manifest source commit does not match the selected build run")
    if manifest_ref != "refs/heads/main":
        raise PolicyError(f"expected source ref refs/heads/main, got {manifest_ref}")
    expected_appimage = f"LetsGoRecomp-{version}-linux-x86_64.AppImage"
    expected_archive = f"LetsGoRecomp-{version}-linux-x86_64.tar.gz"
    if appimage_name != expected_appimage:
        raise PolicyError(f"AppImage name/version mismatch: expected {expected_appimage}, got {appimage_name}")
    if archive_name != expected_archive:
        raise PolicyError(f"archive name/version mismatch: expected {expected_archive}, got {archive_name}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    tag_cmd = sub.add_parser("tag", help="validate a release tag and print its version")
    tag_cmd.add_argument("--tag", required=True)
    run_cmd = sub.add_parser("run", help="validate the selected build run and print its source SHA")
    run_cmd.add_argument("--run-json", required=True, type=Path)
    run_cmd.add_argument("--repository", required=True)
    asset_cmd = sub.add_parser("assets", help="validate artifact names/version and provenance")
    asset_cmd.add_argument("--tag", required=True)
    asset_cmd.add_argument("--version", required=True)
    asset_cmd.add_argument("--source-sha", required=True)
    asset_cmd.add_argument("--manifest-sha", required=True)
    asset_cmd.add_argument("--manifest-ref", required=True)
    asset_cmd.add_argument("--appimage", required=True)
    asset_cmd.add_argument("--archive", required=True)
    args = parser.parse_args()
    try:
        if args.command == "tag":
            print(parse_tag(args.tag))
        elif args.command == "run":
            try:
                run = json.loads(args.run_json.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise PolicyError(f"cannot read workflow run metadata: {exc}") from exc
            print(validate_run(run, args.repository))
        else:
            validate_assets(
                tag=args.tag,
                version=args.version,
                source_sha=args.source_sha,
                manifest_sha=args.manifest_sha,
                manifest_ref=args.manifest_ref,
                appimage_name=args.appimage,
                archive_name=args.archive,
            )
            print("Release version, assets, and source provenance match.")
    except PolicyError as exc:
        print(f"release policy rejected candidate: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
