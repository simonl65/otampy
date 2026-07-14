#!/usr/bin/env bash
#
# release.sh — automates the OTAmpy release process.
# Prompts for the version number and confirms before any irreversible step
# (commit, publish, tag/push). Run from the repository root.

set -euo pipefail

confirm() {
    local prompt="$1"
    local reply
    read -r -p "$prompt [y/N] " reply
    case "$reply" in
        [yY][eE][sS]|[yY]) return 0 ;;
        *) return 1 ;;
    esac
}

abort() {
    echo "Aborting: $*" >&2
    exit 1
}

commit_version_bump() {
    local version="$1"
    local bump_files=()
    local file

    if [[ -n "$(git status --porcelain=v1 -- pyproject.toml uv.lock)" ]]; then
        abort "pyproject.toml or uv.lock already has uncommitted changes; commit or stash them before bumping the version."
    fi

    uv version "$version"

    for file in pyproject.toml uv.lock; do
        if [[ -n "$(git status --porcelain=v1 -- "$file")" ]]; then
            bump_files+=("$file")
        fi
    done

    if [[ ${#bump_files[@]} -eq 0 ]]; then
        abort "version bump did not change pyproject.toml or uv.lock."
    fi

    echo
    echo "Committing version-bump files before continuing:"
    printf '  %s\n' "${bump_files[@]}"
    git diff --check -- "${bump_files[@]}"
    git add "${bump_files[@]}"
    git commit -m "chore(release): bump version to v${version}"
}

usage() {
    cat <<'EOF'
Usage:
  ./release.sh                        Run the full release process.
  ./release.sh --preflight PATH       Preflight OTAmpy against a local URST
                                       checkout at PATH, before URST itself
                                       has been published. Produces artifacts
                                       for inspection only — never publishes.
  ./release.sh -h | --help            Show this help.
EOF
}

wait_for_pypi_version() {
  local package=$1
  local version=$2
  local max_retries=30
  local sleep_interval=10

  echo "Checking PyPI index for $package==$version..."

  for ((i=1; i<=max_retries; i++)); do
    sleep $sleep_interval
    # We use 'uv pip compile' to see if the version is resolvable.
    # --refresh forces uv to ignore its local cache and check the registry.
    if echo "$package==$version" | uv pip compile - --refresh > /dev/null 2>&1; then
      echo "Confirmed: $package==$version is now resolvable via uv."
      return 0
    fi

    echo "Attempt $i/$max_retries: Not yet visible in index. Retrying in ${sleep_interval}s..."
  done

  echo "Error: Timed out waiting for $package==$version to be resolvable"
  return 1
}

run_preflight() {
    local urst_path="$1"

    [[ -n "$urst_path" ]] || abort "--preflight requires a path to a local urst-mpy checkout."
    [[ -d "$urst_path" ]] || abort "no such directory: $urst_path"

    echo "=== OTAmpy Preflight (against local URST checkout) ==="
    echo
    echo "URST source: $urst_path"
    echo
    echo "This mode is for preflight only. It resolves URST from your local"
    echo "checkout instead of the registry, so it does NOT verify registry"
    echo "dependency resolution. Artifacts produced here must never be published."
    echo

    echo "Current version:"
    uv version

    if confirm "Bump the version before preflighting? (skip if you just want to test the current tree)"; then
        read -r -p "Enter the version to set: " PRE_VERSION
        [[ -n "$PRE_VERSION" ]] || abort "version cannot be empty."
        commit_version_bump "$PRE_VERSION"
    fi

    echo
    echo "scripts/release_check.py requires a clean worktree unless you pass"
    echo "--allow-dirty yourself directly (not recommended, dev-only)."
    git status --short

    if ! confirm "Proceed with: uv run python scripts/release_check.py --urst-source \"$urst_path\" ?"; then
        abort "cancelled by user."
    fi

    uv run python scripts/release_check.py --urst-source "$urst_path"

    echo
    echo "=== Preflight complete ==="
    echo "Artifacts are in release-dist/ for inspection only."
    echo "Do NOT run 'uv publish' on them: the final, publishable release check"
    echo "must be rerun without --urst-source once URST is on the registry."
}

# --- Argument parsing --------------------------------------------------------
if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    usage
    exit 0
elif [[ "${1:-}" == "--preflight" ]]; then
    run_preflight "${2:-}"
    exit 0
elif [[ $# -gt 0 ]]; then
    usage
    abort "unrecognized argument: ${1}"
fi

echo "=== OTAmpy Release ==="

# --- 1. Choose the version --------------------------------------------------
echo
echo "Current version:"
uv version
read -r -p "Enter the new OTAmpy version (e.g. 1.1.0): " NEW_VERSION
[[ -n "$NEW_VERSION" ]] || abort "version cannot be empty."

if ! confirm "Set version to ${NEW_VERSION}?"; then
    abort "cancelled by user."
fi

# This looks for 'status-stable_(' followed by digits/dots and ends with ')-green'
FILE="README.md"
sed -i "s/status-stable_([0-9.]*)-green/status-stable_($NEW_VERSION)-green/g" "$FILE"

echo "Updated $FILE to version $NEW_VERSION"

commit_version_bump "$NEW_VERSION"

# --- 2. Prepare release notes and docs --------------------------------------
echo
echo "Review docs/README/release notes and the diff before continuing."
git diff --check
git status --short

if ! confirm "Have docs/release notes been updated, and are you ready to commit docs and README.md if changed?"; then
    abort "make your documentation changes, then rerun this script."
fi

DOC_FILES=()
for file in docs README.md; do
    if [[ -n "$(git status --porcelain=v1 -- "$file")" ]]; then
        DOC_FILES+=("$file")
    fi
done

if [[ ${#DOC_FILES[@]} -gt 0 ]]; then
    git add "${DOC_FILES[@]}"
    git commit -m "docs(release): update notes for v${NEW_VERSION}"
else
    echo "No docs or README.md changes to commit."
fi

if [[ -n "$(git status --short)" ]]; then
    abort "worktree is not clean after commit; the release gate requires a clean worktree."
fi

# --- 3-7. Run the automated release gate ------------------------------------
echo
echo "Running scripts/release_check.py (lint, tests, bundling, build, artifact"
echo "inspection, clean-install + dry-run)..."
uv run python scripts/release_check.py

echo
echo "Release gate passed. Verified artifacts are in release-dist/."

# --- 8. Inspect and publish --------------------------------------------------
echo
echo "Contents of release-dist/:"
find release-dist -maxdepth 1 -type f -printf '%f\n'

if ! confirm "Confirm release-dist/ contains exactly one wheel and one sdist for v${NEW_VERSION}. Publish now?"; then
    abort "publish cancelled. Verified files remain in release-dist/ for a manual publish later."
fi

echo "Publishing..."
source ~/.secrets
uv publish release-dist/* --token $UV_PUBLISH_TOKEN
echo "Published v${NEW_VERSION}."
git push

# --- 9. Verify the registry release -----------------------------------------
# Delay to allow time for publish to finish and propagate to the registry. This is a best-effort check; if it fails, you can retry later.
if wait_for_pypi_version "otampy" "$NEW_VERSION"; then
    echo "Registry is up to date. Proceeding to next steps..."
else
    echo "Registry update failed or timed out. Aborting."
    exit 1
fi
echo
echo "Verifying registry release in an isolated tool environment..."
uvx --refresh --from "otampy==${NEW_VERSION}" otampy --help

VERIFY_DIR=$(mktemp -d /tmp/otampy-release-verification.XXXXXX)
echo "Verifying consumer workflow in ${VERIFY_DIR} ..."
(
    cd "$VERIFY_DIR"
    uv init
    uv add "otampy==${NEW_VERSION}"
    uv run otampy init device
    uv run otampy deploy --device-dir device --dry-run --no-mip
)
echo "Consumer workflow verification passed."

# --- 10. Tag the verified release -------------------------------------------
echo
if ! confirm "Tag v${NEW_VERSION} at this commit and push it (and develop) now?"; then
    echo "Stopping before tagging. The package is already published; tag manually"
    echo "with: git tag -a v${NEW_VERSION} -m \"OTAmpy ${NEW_VERSION}\" && git push origin develop v${NEW_VERSION}"
    exit 0
fi

git tag -a "v${NEW_VERSION}" -m "OTAmpy ${NEW_VERSION}"
git push origin develop
git push origin "v${NEW_VERSION}"
git checkout main
git merge develop
git push origin main
git checkout develop
git push --tags

echo
echo "=== Release v${NEW_VERSION} complete ==="
echo "Remember to create the corresponding hosting-platform release and attach/link"
echo "the release notes. Do not attach any artifacts other than those from release-dist/."
