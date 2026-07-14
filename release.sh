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
        uv version "$PRE_VERSION"
    fi

    echo
    echo "Note: scripts/release_check.py still requires a clean worktree unless"
    echo "you pass --allow-dirty yourself directly (not recommended, dev-only)."
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
echo

# --- Prerequisite check -----------------------------------------------------
if ! confirm "Is a compatible urst release (>=1.0.0,<2.0.0) already published to the registry?"; then
    abort "Publish the compatible URST release first, then rerun this script."
fi

# --- 1. Choose the version --------------------------------------------------
echo
echo "Current version:"
uv version
read -r -p "Enter the new OTAmpy version (e.g. 1.1.0): " NEW_VERSION
[[ -n "$NEW_VERSION" ]] || abort "version cannot be empty."

if ! confirm "Set version to ${NEW_VERSION}?"; then
    abort "cancelled by user."
fi
uv version "$NEW_VERSION"

# --- 2. Prepare the release commit ------------------------------------------
echo
echo "Review docs/README/release notes and the diff before committing."
git diff --check
git status --short

if ! confirm "Have docs/release notes been updated, and are you ready to commit pyproject.toml, uv.lock, docs, README.md?"; then
    abort "make your documentation changes, then rerun this script."
fi

git add pyproject.toml uv.lock docs README.md
git commit -m "chore(release): prepare v${NEW_VERSION}"

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
uv publish release-dist/*
echo "Published v${NEW_VERSION}."

# --- 9. Verify the registry release -----------------------------------------
echo
echo "Verifying registry release in an isolated tool environment..."
uvx --refresh --from "otampy==${NEW_VERSION}" otampy --help

VERIFY_DIR=$(mktemp -d /tmp/otampy-release-verification.XXXXXX)
echo "Verifying consumer workflow in ${VERIFY_DIR} ..."
(
    cd "$VERIFY_DIR"
    uv init
    uv add "otampy==${NEW_VERSION}"
    uv run otampy init
    uv run otampy deploy --device-dir new-project --dry-run --no-mip
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

echo
echo "=== Release v${NEW_VERSION} complete ==="
echo "Remember to create the corresponding hosting-platform release and attach/link"
echo "the release notes. Do not attach any artifacts other than those from release-dist/."
