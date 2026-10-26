#!/usr/bin/env bash
# Read-only validation for publication of a Linux build artifact. Safe to run in a read-only token job.
set -euo pipefail

: "${REPOSITORY:?REPOSITORY is required}"
: "${RUN_ID:?RUN_ID is required}"
: "${TAG:?TAG is required}"
: "${GH_TOKEN:?GH_TOKEN is required}"
[[ "$RUN_ID" =~ ^[0-9]+$ ]] || { echo "run_id must be numeric" >&2; exit 1; }
[[ "$REPOSITORY" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] || { echo "Invalid repository name" >&2; exit 1; }
tag_version="$(python3 tools/release_policy.py tag --tag "$TAG")"

ARTIFACT_DIR=artifact
rm -rf "$ARTIFACT_DIR"
mkdir -p "$ARTIFACT_DIR"

run_json="$ARTIFACT_DIR/build-run.json"
gh api "repos/$REPOSITORY/actions/runs/$RUN_ID" > "$run_json"
source_sha="$(python3 tools/release_policy.py run --run-json "$run_json" --repository "$REPOSITORY")"

gh run download "$RUN_ID" --repo "$REPOSITORY" --name letsgo-recomp-linux-x86_64 --dir "$ARTIFACT_DIR"

bundles=("$ARTIFACT_DIR"/LetsGoRecomp-*-linux-x86_64.tar.gz)
bundle_checksums=("$ARTIFACT_DIR"/LetsGoRecomp-*-linux-x86_64.tar.gz.sha256)
appimages=("$ARTIFACT_DIR"/LetsGoRecomp-*-linux-x86_64.AppImage)
appimage_checksums=("$ARTIFACT_DIR"/LetsGoRecomp-*-linux-x86_64.AppImage.sha256)
[[ "${#bundles[@]}" -eq 1 && -f "${bundles[0]}" ]] || { echo "Expected one Linux tar.gz artifact." >&2; exit 1; }
[[ "${#bundle_checksums[@]}" -eq 1 && -f "${bundle_checksums[0]}" ]] || { echo "Expected one tar.gz checksum." >&2; exit 1; }
[[ "${#appimages[@]}" -eq 1 && -f "${appimages[0]}" ]] || { echo "Expected one x86_64 AppImage." >&2; exit 1; }
[[ "${#appimage_checksums[@]}" -eq 1 && -f "${appimage_checksums[0]}" ]] || { echo "Expected one AppImage checksum." >&2; exit 1; }

verify_sha256() {
  local file="$1" checksum_file="$2" actual expected
  expected="$(awk 'NR == 1 { print $1 }' "$checksum_file")"
  actual="$(sha256sum "$file" | awk '{ print $1 }')"
  [[ "$expected" =~ ^[[:xdigit:]]{64}$ && "$actual" == "$expected" ]] || {
    echo "SHA-256 mismatch for $file." >&2; exit 1;
  }
  printf '%s\n' "$actual"
}
bundle_sha="$(verify_sha256 "${bundles[0]}" "${bundle_checksums[0]}")"
appimage_sha="$(verify_sha256 "${appimages[0]}" "${appimage_checksums[0]}")"

# The archive gives an independently inspectable copy of the metadata embedded in the AppDir.
tar -tzf "${bundles[0]}" > "$ARTIFACT_DIR/archive-files.txt"
for required in \
  'LetsGoRecomp/build-manifest.json' \
  'LetsGoRecomp/BUILD-INFO.txt' \
  'LetsGoRecomp/DEPENDENCIES.json' \
  'LetsGoRecomp/sbom.cdx.json' \
  'LetsGoRecomp/usr/bin/lasgen/lasgen' \
  'LetsGoRecomp/usr/bin/zig/zig' \
  'LetsGoRecomp/AppRun'; do
  grep -Fxq "$required" "$ARTIFACT_DIR/archive-files.txt" || {
    echo "Archive is missing required bundle file: $required" >&2; exit 1;
  }
done
if grep -Eq '(^/|(^|/)\.\.(/|$))' "$ARTIFACT_DIR/archive-files.txt"; then
  echo "Archive contains an absolute or parent-traversal path." >&2; exit 1;
fi
tar -xOf "${bundles[0]}" LetsGoRecomp/build-manifest.json > "$ARTIFACT_DIR/embedded-build-manifest.json"
tar -xOf "${bundles[0]}" LetsGoRecomp/BUILD-INFO.txt > "$ARTIFACT_DIR/embedded-BUILD-INFO.txt"
tar -xOf "${bundles[0]}" LetsGoRecomp/DEPENDENCIES.json > "$ARTIFACT_DIR/embedded-DEPENDENCIES.json"
tar -xOf "${bundles[0]}" LetsGoRecomp/sbom.cdx.json > "$ARTIFACT_DIR/embedded-sbom.cdx.json"

[[ -f "$ARTIFACT_DIR/build-manifest.json" && -f "$ARTIFACT_DIR/sbom.cdx.json" && -f "$ARTIFACT_DIR/BUILD-INFO.txt" && -f "$ARTIFACT_DIR/DEPENDENCIES.json" ]] || {
  echo "Missing external copies of build metadata/SBOM." >&2; exit 1;
}
cmp "$ARTIFACT_DIR/build-manifest.json" "$ARTIFACT_DIR/embedded-build-manifest.json"
cmp "$ARTIFACT_DIR/sbom.cdx.json" "$ARTIFACT_DIR/embedded-sbom.cdx.json"
cmp "$ARTIFACT_DIR/BUILD-INFO.txt" "$ARTIFACT_DIR/embedded-BUILD-INFO.txt"
cmp "$ARTIFACT_DIR/DEPENDENCIES.json" "$ARTIFACT_DIR/embedded-DEPENDENCIES.json"

version="$(jq -er '.version' "$ARTIFACT_DIR/build-manifest.json")"
manifest_sha="$(jq -er '.source_commit' "$ARTIFACT_DIR/build-manifest.json")"
manifest_ref="$(jq -er '.source_ref' "$ARTIFACT_DIR/build-manifest.json")"
python3 tools/release_policy.py assets \
  --tag "$TAG" --version "$version" \
  --source-sha "$source_sha" --manifest-sha "$manifest_sha" --manifest-ref "$manifest_ref" \
  --appimage "$(basename "${appimages[0]}")" --archive "$(basename "${bundles[0]}")"
grep -Fxq "version=$version" "$ARTIFACT_DIR/BUILD-INFO.txt"
grep -Fxq "source_commit=$source_sha" "$ARTIFACT_DIR/BUILD-INFO.txt"
dependency_sha="$(sha256sum "$ARTIFACT_DIR/DEPENDENCIES.json" | awk '{ print $1 }')"
[[ "$dependency_sha" == "$(jq -er '.dependency_lock_sha256' "$ARTIFACT_DIR/build-manifest.json")" ]] || {
  echo "Dependency lock hash does not match the embedded build manifest." >&2; exit 1;
}
jq -e '.schema_version == 1 and (.dependencies | length > 0)' "$ARTIFACT_DIR/DEPENDENCIES.json" >/dev/null

jq -e '.bomFormat == "CycloneDX" and (.components | length > 0)' "$ARTIFACT_DIR/sbom.cdx.json" >/dev/null
jq -e \
  --arg sha "$source_sha" --arg version "$version" \
  --arg appimage_name "$(basename "${appimages[0]}")" --arg appimage_sha "$appimage_sha" \
  --arg archive_name "$(basename "${bundles[0]}")" --arg archive_sha "$bundle_sha" \
  '.source_commit == $sha and .version == $version and
   any(.artifacts[]; .name == $appimage_name and .sha256 == $appimage_sha) and
   any(.artifacts[]; .name == $archive_name and .sha256 == $archive_sha)' \
  "$ARTIFACT_DIR/build-manifest-release.json" >/dev/null
jq -e '.errors == [] and .elf_count > 0' "$ARTIFACT_DIR/linux-elf-audit.json" >/dev/null
manifest_copy_sha="$(sha256sum "$ARTIFACT_DIR/build-manifest.json" | awk '{ print $1 }')"
sbom_sha="$(sha256sum "$ARTIFACT_DIR/sbom.cdx.json" | awk '{ print $1 }')"
elf_report_sha="$(sha256sum "$ARTIFACT_DIR/linux-elf-audit.json" | awk '{ print $1 }')"
size_report_sha="$(sha256sum "$ARTIFACT_DIR/build-size-report.txt" | awk '{ print $1 }')"
jq -e --arg manifest_sha "$manifest_copy_sha" --arg sbom_sha "$sbom_sha" --arg dep_sha "$dependency_sha" --arg elf_sha "$elf_report_sha" --arg size_sha "$size_report_sha" \
  '.evidence.build_manifest.sha256 == $manifest_sha and .evidence.cyclonedx_sbom.sha256 == $sbom_sha and .evidence.dependency_lock.sha256 == $dep_sha and .evidence.elf_audit.sha256 == $elf_sha and .evidence.size_report.sha256 == $size_sha' \
  "$ARTIFACT_DIR/build-manifest-release.json" >/dev/null

# Test the actual AppImage code path with no write access to the repository. --version avoids SDL/GPU
# initialization; --self-test verifies the shipped helper, Zig, and game-code headers without game files.
version_output="$(APPIMAGE_EXTRACT_AND_RUN=1 "${appimages[0]}" --version)"
[[ "$version_output" == "Let's Go Recomp $version" ]] || { echo "AppImage --version failed." >&2; exit 1; }
smoke_home="$(mktemp -d)"
smoke_xdg="$smoke_home/xdg"
mkdir -p "$smoke_xdg"
env -u LARECOMP_DATA_ROOT -u LARECOMP_GEN -u LARECOMP_CC \
  HOME="$smoke_home/home" XDG_DATA_HOME="$smoke_xdg" APPIMAGE_EXTRACT_AND_RUN=1 \
  "${appimages[0]}" --self-test
[[ ! -e "$smoke_xdg/lasrecomp/extracted" ]] || { echo "Self-test created game files." >&2; exit 1; }
rm -rf "$smoke_home"

# Distinguish the expected 404 (tag absent) from permission/API/network errors.
api_base="https://api.github.com/repos/$REPOSITORY"
tag_http="$(curl --silent --show-error --output "$ARTIFACT_DIR/tag-ref.json" --write-out '%{http_code}' \
  -H "Authorization: Bearer $GH_TOKEN" -H 'Accept: application/vnd.github+json' \
  "$api_base/git/ref/tags/$TAG")"
[[ "$tag_http" == "404" ]] || {
  if [[ "$tag_http" == "200" ]]; then echo "Tag $TAG already exists; refusing to overwrite it." >&2;
  else echo "Could not safely verify tag absence (HTTP $tag_http)." >&2; fi
  exit 1
}
release_http="$(curl --silent --show-error --output "$ARTIFACT_DIR/release.json" --write-out '%{http_code}' \
  -H "Authorization: Bearer $GH_TOKEN" -H 'Accept: application/vnd.github+json' \
  "$api_base/releases/tags/$TAG")"
[[ "$release_http" == "404" ]] || {
  if [[ "$release_http" == "200" ]]; then echo "Release $TAG already exists; refusing to overwrite it." >&2;
  else echo "Could not safely verify release absence (HTTP $release_http)." >&2; fi
  exit 1
}

printf 'Validated release candidate: version=%s commit=%s tag=%s\n' "$version" "$source_sha" "$TAG"
