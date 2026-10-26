#!/usr/bin/env python3
"""ROM-free regression tests for the read-only setup diagnostic.

Usage: python3 tests/test_setup_dry_run.py --binary build/lasrecomp
"""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import struct
import subprocess
import tempfile


EEVEE_PROGRAM_ID = 0x0100187003A36000
EEVEE_BUILD_ID = bytes((0x0A, 0x3F, 0x0D, 0x21, 0xE6, 0x7D, 0xAD, 0x80))


def write_exefs(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    npdm = bytearray(0x98)
    npdm[0:4] = b"META"
    struct.pack_into("<I", npdm, 0x70, 0x80)
    npdm[0x80:0x84] = b"ACI0"
    struct.pack_into("<Q", npdm, 0x90, EEVEE_PROGRAM_ID)
    (root / "main.npdm").write_bytes(npdm)
    main = bytearray(0x48)
    main[0x40:0x48] = EEVEE_BUILD_ID
    (root / "main").write_bytes(main)


def write_romfs_dir(root: Path) -> None:
    # The finder recognises the RomFS root by bin/message being a directory.
    message = root / "bin" / "message"
    message.mkdir(parents=True)
    (message / "fixture.txt").write_text("synthetic fixture only\n", encoding="utf-8")


def write_romfs_image(path: Path) -> None:
    # Minimal structurally-valid header for romfs_image_ok(); no game content.
    header = [0x50, 0x200, 4, 0x204, 1, 0x205, 4, 0x209, 1, 0x200]
    image = bytearray(0x220)
    struct.pack_into("<10Q", image, 0, *header)
    path.write_bytes(image)


def snapshot(root: Path) -> dict[str, str]:
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def run(binary: Path, folder: Path, cwd: Path, env: dict[str, str], redact: bool = False) -> subprocess.CompletedProcess[str]:
    command = [str(binary), "--setup-dry-run", str(folder)]
    if redact:
        command.append("--redact-paths")
    return subprocess.run(command, cwd=cwd, env=env, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, check=False, timeout=15)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", required=True, type=Path)
    args = parser.parse_args()
    binary = args.binary.resolve()
    if not binary.is_file() or not os.access(binary, os.X_OK):
        parser.error(f"runtime executable not found or not executable: {binary}")

    with tempfile.TemporaryDirectory(prefix="lasrecomp-setup-dry-run-") as tmp:
        root = Path(tmp)
        work = root / "cwd"
        work.mkdir()
        home = root / "home"
        xdg = root / "xdg"
        env = os.environ.copy()
        env.update({"HOME": str(home), "XDG_DATA_HOME": str(xdg)})
        env.pop("LARECOMP_DATA_ROOT", None)

        # Conventional nested layout: exefs + a RomFS directory.
        nested = root / "wrapped" / "game"
        write_exefs(nested / "exefs")
        write_romfs_dir(nested / "romfs")

        # Existing image layout.
        existing = root / "image-layout"
        write_exefs(existing / "exefs")
        write_romfs_image(existing / "romfs.bin")

        # A flat dump where main and the RomFS files share a root.
        flat = root / "flat"
        write_exefs(flat)
        write_romfs_dir(flat)

        # Rejection cases: an unrecognised folder and a packed game package.
        invalid = root / "invalid"
        invalid.mkdir()
        (invalid / "notes.txt").write_text("not a game dump\n", encoding="utf-8")
        packed = root / "packed"
        packed.mkdir()
        (packed / "game.nsp").write_bytes(b"not actual content")

        sentinel = work / "extracted"
        sentinel.mkdir()
        (sentinel / "must-stay.txt").write_text("existing user file\n", encoding="utf-8")
        before = snapshot(root)
        assert not xdg.exists() and not home.exists(), "precondition: user data roots must not exist"

        for name, folder in (("nested", nested), ("romfs.bin", existing), ("flat", flat)):
            result = run(binary, folder, work, env)
            assert result.returncode == 0, f"{name}: expected valid source, got {result.returncode}\n{result.stdout}"
            assert "DRY RUN" in result.stdout and "aucun fichier modifié" in result.stdout, result.stdout
            assert "source valide" in result.stdout, result.stdout

        bad = run(binary, invalid, work, env)
        assert bad.returncode == 2, f"invalid folder should return 2, got {bad.returncode}\n{bad.stdout}"
        packaged = run(binary, packed, work, env)
        assert packaged.returncode == 3, f"packed file should return 3, got {packaged.returncode}\n{packaged.stdout}"

        redacted = run(binary, nested, work, env, redact=True)
        assert redacted.returncode == 0, redacted.stdout
        assert "<chemin masqué>" in redacted.stdout, redacted.stdout
        assert str(nested) not in redacted.stdout, redacted.stdout

        after = snapshot(root)
        assert before == after, "dry-run modified or created a file in the fixture tree"
        assert (sentinel / "must-stay.txt").read_text(encoding="utf-8") == "existing user file\n"
        assert not xdg.exists(), "dry-run created an XDG data directory"
        assert not home.exists(), "dry-run created a HOME directory"
        assert not (work / "lasrecomp.log").exists(), "dry-run initialised runtime logging"
        print("PASS: setup dry-run is read-only for nested, flat, romfs.bin, invalid and packaged fixtures")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
