#!/usr/bin/env python3
"""Audit every ELF executable/shared object in an extracted Linux AppDir/AppImage."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys

HOST_ALLOWLIST = [
    r"^linux-vdso\.so(?:\.|$)",
    r"^ld-linux(?:-[^.]*)?\.so(?:\.|$)",
    r"^libc\.so(?:\.|$)", r"^libm\.so(?:\.|$)", r"^libpthread\.so(?:\.|$)",
    r"^libdl\.so(?:\.|$)", r"^librt\.so(?:\.|$)", r"^libresolv\.so(?:\.|$)",
    r"^libgcc_s\.so(?:\.|$)", r"^libstdc\+\+\.so(?:\.|$)",
    r"^libvulkan\.so(?:\.|$)", r"^libGL(?:X|dispatch)?\.so(?:\.|$)", r"^libEGL\.so(?:\.|$)",
    r"^libOpenGL\.so(?:\.|$)", r"^libdrm\.so(?:\.|$)", r"^libgbm\.so(?:\.|$)",
    r"^libwayland-[^/]+\.so(?:\.|$)", r"^libX[^/]*\.so(?:\.|$)", r"^libxcb[^/]*\.so(?:\.|$)",
    r"^libxkbcommon[^/]*\.so(?:\.|$)", r"^libudev\.so(?:\.|$)", r"^libdbus-1\.so(?:\.|$)",
    r"^libsystemd\.so(?:\.|$)", r"^libasound\.so(?:\.|$)", r"^libpulse[^/]*\.so(?:\.|$)",
    r"^libpipewire-[^/]+\.so(?:\.|$)", r"^libspa-[^/]+\.so(?:\.|$)", r"^libibus-1\.0\.so(?:\.|$)",
    r"^libz\.so(?:\.|$)", r"^libbz2\.so(?:\.|$)", r"^libffi\.so(?:\.|$)",
    r"^libuuid\.so(?:\.|$)", r"^libexpat\.so(?:\.|$)", r"^libgcc_s\.so(?:\.|$)",
    r"^libXau\.so(?:\.|$)", r"^libXdmcp\.so(?:\.|$)", r"^libbsd\.so(?:\.|$)",
    r"^libmd\.so(?:\.|$)", r"^libpcre2-[^/]+\.so(?:\.|$)", r"^libselinux\.so(?:\.|$)",
    r"^libcap\.so(?:\.|$)", r"^libgpg-error\.so(?:\.|$)", r"^libkeyutils\.so(?:\.|$)",
    r"^libnss_[^/]+\.so(?:\.|$)", r"^libnsl\.so(?:\.|$)", r"^libtirpc\.so(?:\.|$)",
    r"^libgcrypt\.so(?:\.|$)", r"^libzstd\.so(?:\.|$)", r"^liblzma\.so(?:\.|$)",
    r"^libtinfo\.so(?:\.|$)", r"^libncurses[^/]*\.so(?:\.|$)", r"^libgomp\.so(?:\.|$)",
    r"^libatomic\.so(?:\.|$)", r"^libnuma\.so(?:\.|$)", r"^libunwind\.so(?:\.|$)",
    r"^libicu[^/]*\.so(?:\.|$)", r"^libssl\.so(?:\.|$)", r"^libcrypto\.so(?:\.|$)",
    r"^libxml2\.so(?:\.|$)", r"^libfontconfig\.so(?:\.|$)", r"^libfreetype\.so(?:\.|$)",
    r"^libpng[^/]*\.so(?:\.|$)", r"^libharfbuzz\.so(?:\.|$)", r"^libbrotli[^/]*\.so(?:\.|$)",
]
ALLOW = [re.compile(p) for p in HOST_ALLOWLIST]


def elf_type(path: Path) -> int | None:
    try:
        with path.open("rb") as f:
            h = f.read(20)
        if len(h) < 20 or h[:4] != b"\x7fELF":
            return None
        if h[5] == 1:
            return struct.unpack("<H", h[16:18])[0]
        if h[5] == 2:
            return struct.unpack(">H", h[16:18])[0]
    except OSError:
        return None
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path, help="extracted AppImage root (squashfs-root)")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--require-bundled", action="append", default=[])
    args = parser.parse_args()
    root = args.root.resolve()
    if not root.is_dir():
        parser.error(f"AppImage root does not exist: {root}")

    lib_dirs = [root / "usr/lib", root / "usr/lib64", root / "usr/lib/x86_64-linux-gnu"]
    existing = [str(p) for p in lib_dirs if p.is_dir()]
    old_ld = os.environ.get("LD_LIBRARY_PATH", "")
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = ":".join(existing + ([old_ld] if old_ld else []))

    records: list[dict[str, object]] = []
    errors: list[str] = []
    bundled_names: set[str] = set()
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        kind = elf_type(path)
        if kind not in (2, 3):  # ET_EXEC and ET_DYN; omit relocatable .o files
            continue
        rel = str(path.relative_to(root))
        if kind == 3:
            bundled_names.add(path.name)
        try:
            proc = subprocess.run(["ldd", str(path)], text=True, stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, env=env, check=False, timeout=30)
            output = proc.stdout
        except (OSError, subprocess.TimeoutExpired) as exc:
            errors.append(f"{rel}: ldd could not run: {exc}")
            records.append({"path": rel, "elf_type": kind, "error": str(exc)})
            continue

        if "not found" in output:
            errors.append(f"{rel}: unresolved shared-library dependency")
        if proc.returncode != 0 and not re.search(r"not a dynamic executable|statically linked", output, re.I):
            errors.append(f"{rel}: ldd exited {proc.returncode}: {output.strip()[:500]}")

        dependencies: list[dict[str, str]] = []
        host_dependencies: list[str] = []
        for line in output.splitlines():
            line = line.strip()
            m = re.match(r"^(\S+)\s+=>\s+(\S+)", line)
            if m:
                name, resolved = m.groups()
                if resolved == "not":
                    errors.append(f"{rel}: dependency {name} not resolved")
                    continue
                if str(root) in resolved:
                    dependencies.append({"soname": name, "path": resolved})
                    bundled_names.add(name)
                elif resolved.startswith("/"):
                    host_dependencies.append(name)
                    if not any(p.match(name) for p in ALLOW):
                        errors.append(f"{rel}: host dependency not in allowlist: {name} ({resolved})")
                continue
            m = re.match(r"^(\S+)\s+\((?:0x[0-9a-fA-F]+)\)$", line)
            if m:
                dependencies.append({"soname": m.group(1), "path": "resolved without pathname"})

        records.append({"path": rel, "elf_type": kind, "returncode": proc.returncode,
                        "bundled_dependencies": dependencies, "host_dependencies": sorted(set(host_dependencies))})

    for soname in args.require_bundled:
        matches = [r for r in records if any(dep.get("soname") == soname for dep in r.get("bundled_dependencies", []))]
        if not matches:
            errors.append(f"required library not bundled: {soname}")

    report = {
        "schema": 1,
        "root": str(root),
        "elf_count": len(records),
        "host_dependency_allowlist": HOST_ALLOWLIST,
        "required_bundled": args.require_bundled,
        "errors": errors,
        "files": records,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"ELF audit: {len(records)} ELF objects, {len(errors)} error(s); report={args.report}")
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
