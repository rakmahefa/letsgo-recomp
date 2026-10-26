#!/usr/bin/env python3
"""Write build identity, SHA-256 payload inventory, and a CycloneDX SBOM into a Linux AppDir."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import subprocess
from urllib.parse import quote


EXCLUDED_METADATA = {"BUILD-INFO.txt", "build-manifest.json", "sbom.cdx.json"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def version_of(command: list[str]) -> str:
    result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            check=False, timeout=20)
    value = result.stdout.strip().splitlines()
    return value[0] if result.returncode == 0 and value else "unavailable"


def license_component(name: str, version: str, license_id: str, component_type: str = "library") -> dict:
    return {
        "type": component_type,
        "name": name,
        "version": version,
        "licenses": [{"license": {"id": license_id}}],
        "bom-ref": f"pkg:generic/{quote(name.lower().replace(' ', '-'), safe='-._~')}@{version}",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--appdir", required=True, type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--python", required=True, type=Path)
    parser.add_argument("--zig", required=True, type=Path)
    parser.add_argument("--clang", default="clang-21")
    parser.add_argument("--ffmpeg", default="6.1.6")
    parser.add_argument("--sdl", default="release-3.4.18")
    parser.add_argument("--vulkan-headers", default="v1.3.296")
    parser.add_argument("--vma", default="v3.1.0")
    parser.add_argument("--shaderc", default="v2024.4")
    args = parser.parse_args()

    appdir = args.appdir.resolve()
    if not appdir.is_dir():
        parser.error(f"AppDir not found: {appdir}")
    payload = []
    for path in sorted(appdir.rglob("*")):
        if not path.is_file() or path.name in EXCLUDED_METADATA:
            continue
        try:
            rel = path.relative_to(appdir).as_posix()
            payload.append({"path": rel, "size_bytes": path.stat().st_size, "sha256": sha256(path)})
        except OSError as exc:
            parser.error(f"could not inventory {path}: {exc}")

    python_exe = str(args.python.absolute())
    packages = {}
    for dist in importlib.metadata.distributions():
        name = dist.metadata.get("Name", "").strip()
        version = dist.version
        if name and version:
            packages[name.lower().replace("_", "-")] = {"name": name, "version": version}

    built_utc = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    zig_version = version_of([str(args.zig.resolve()), "version"])
    clang_version = version_of([args.clang, "--version"])
    build = {
        "version": args.version,
        "source_commit": args.commit,
        "source_ref": args.ref,
        "built_utc": built_utc,
        "architecture": platform.machine(),
        "os": "linux",
        "python": version_of([python_exe, "--version"]),
        "python_packages": dict(sorted(packages.items())),
        "clang": clang_version,
        "zig": zig_version,
        "sdl": args.sdl,
        "ffmpeg": args.ffmpeg,
        "vulkan_headers": args.vulkan_headers,
        "vulkan_memory_allocator": args.vma,
        "shaderc": args.shaderc,
        "payload_file_count": len(payload),
        "payload": payload,
    }
    (appdir / "build-manifest.json").write_text(json.dumps(build, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    info = [
        "Let's Go Recomp — Linux build identity",
        f"version={args.version}",
        f"source_commit={args.commit}",
        f"source_ref={args.ref}",
        f"built_utc={built_utc}",
        f"architecture={platform.machine()}",
        f"python={build['python']}",
        f"clang={clang_version}",
        f"zig={zig_version}",
        f"SDL3={args.sdl}",
        f"FFmpeg={args.ffmpeg}",
        f"Vulkan-Headers={args.vulkan_headers}",
        f"VulkanMemoryAllocator={args.vma}",
        f"shaderc={args.shaderc}",
    ]
    (appdir / "BUILD-INFO.txt").write_text("\n".join(info) + "\n", encoding="utf-8")

    components = [
        license_component("Let's Go Recomp", args.version, "LicenseRef-LetsGoRecomp", "application"),
        license_component("Zig", zig_version, "MIT"),
        license_component("SDL3", args.sdl, "Zlib"),
        license_component("FFmpeg", args.ffmpeg, "LGPL-2.1-or-later"),
        license_component("Vulkan-Headers", args.vulkan_headers, "Apache-2.0"),
        license_component("Vulkan Memory Allocator", args.vma, "MIT"),
        license_component("shaderc", args.shaderc, "Apache-2.0"),
        license_component("Capstone", packages.get("capstone", {}).get("version", "unknown"), "BSD-3-Clause"),
        license_component("Unicorn Engine", packages.get("unicorn", {}).get("version", "unknown"), "GPL-2.0-or-later"),
        license_component("lz4", packages.get("lz4", {}).get("version", "unknown"), "BSD-2-Clause"),
        license_component("PyInstaller", packages.get("pyinstaller", {}).get("version", "unknown"), "GPL-2.0-or-later"),
    ]
    for key in ("altgraph", "packaging", "pyinstaller-hooks-contrib", "setuptools"):
        value = packages.get(key)
        if value:
            components.append(license_component(value["name"], value["version"], "NOASSERTION"))
    sbom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:{hashlib.sha256((args.commit + args.version).encode()).hexdigest()[:8]}-0000-4000-8000-{hashlib.sha256(args.ref.encode()).hexdigest()[:12]}",
        "version": 1,
        "metadata": {
            "timestamp": built_utc,
            "tools": [{"vendor": "Let's Go Recomp", "name": "write_linux_metadata.py", "version": "1"}],
            "component": license_component("Let's Go Recomp", args.version, "LicenseRef-LetsGoRecomp", "application"),
            "properties": [
                {"name": "source.commit", "value": args.commit},
                {"name": "source.ref", "value": args.ref},
                {"name": "build.manifest", "value": "build-manifest.json"},
            ],
        },
        "components": components,
    }
    (appdir / "sbom.cdx.json").write_text(json.dumps(sbom, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote BUILD-INFO.txt, build-manifest.json ({len(payload)} payload files), sbom.cdx.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
