#!/usr/bin/env python3
"""Create a release-side manifest with hashes of final downloadable artifacts."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--appimage", required=True, type=Path)
    p.add_argument("--archive", required=True, type=Path)
    p.add_argument("--manifest", required=True, type=Path, help="embedded build-manifest.json")
    p.add_argument("--sbom", required=True, type=Path)
    p.add_argument("--dependencies", required=True, type=Path)
    p.add_argument("--elf-report", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--run-id", required=True)
    p.add_argument("--repository", required=True)
    args = p.parse_args()

    for path in (args.appimage, args.archive, args.manifest, args.sbom, args.dependencies, args.elf_report):
        if not path.is_file():
            p.error(f"missing release evidence: {path}")
    embedded = json.loads(args.manifest.read_text(encoding="utf-8"))
    dependency_doc = json.loads(args.dependencies.read_text(encoding="utf-8"))
    if sha256(args.dependencies) != embedded.get("dependency_lock_sha256"):
        p.error("dependency lock SHA-256 does not match the embedded build manifest")
    if dependency_doc.get("dependencies") != embedded.get("dependencies"):
        p.error("dependency lock contents do not match the embedded build manifest")
    report = {
        "schema": 1,
        "created_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "repository": args.repository,
        "workflow_run_id": args.run_id,
        "source_commit": embedded.get("source_commit"),
        "source_ref": embedded.get("source_ref"),
        "version": embedded.get("version"),
        "architecture": embedded.get("architecture"),
        "artifacts": [
            {"name": args.appimage.name, "size_bytes": args.appimage.stat().st_size, "sha256": sha256(args.appimage)},
            {"name": args.archive.name, "size_bytes": args.archive.stat().st_size, "sha256": sha256(args.archive)},
        ],
        "evidence": {
            "build_manifest": {"name": args.manifest.name, "sha256": sha256(args.manifest)},
            "cyclonedx_sbom": {"name": args.sbom.name, "sha256": sha256(args.sbom)},
            "dependency_lock": {"name": args.dependencies.name, "sha256": sha256(args.dependencies)},
            "elf_audit": {"name": args.elf_report.name, "sha256": sha256(args.elf_report)},
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
