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

create_github_release() {
    local version="$1"
    local tag="v${version}"
    local notes_file
    local editor="${EDITOR:-vi}"
    local -a editor_cmd

    command -v gh >/dev/null 2>&1 || abort "gh (GitHub CLI) not found; install/authenticate it, then run: gh release create ${tag} release-dist/* --title \"OTAmpy ${tag}\""

    if [[ -z "$(find release-dist -maxdepth 1 -type f -print -quit 2>/dev/null)" ]]; then
        abort "release-dist/ is empty or missing; nothing to attach to the GitHub release."
    fi

    notes_file=$(mktemp --suffix=.md /tmp/otampy-release-notes.XXXXXX)

    cat > "$notes_file" <<EOF
<!--
Release notes for ${tag}.
Everything up to and including the first line containing only '---' is
stripped before publishing. Write your notes below that line, then save
and exit the editor to continue.
-->
---
# What's changed

## MAJOR (breaking changes)

- None

## MINOR (functionality added in a backward compatible manner)

- None

## PATCH (backward compatible bug fixes)

- 

EOF

    # $EDITOR/$VISUAL conventionally may contain arguments (e.g. "code --wait"),
    # so split on whitespace into an array rather than treating it as one token.
    read -r -a editor_cmd <<< "$editor"
    "${editor_cmd[@]}" "$notes_file"

    # Strip the instructional header (everything up to and including the first '---' line).
    sed -i '1,/^---$/d' "$notes_file"

    if [[ -z "$(sed '/^[[:space:]]*$/d' "$notes_file")" ]]; then
        rm -f "$notes_file"
        abort "release notes were empty; aborting before creating the GitHub release."
    fi

    echo
    echo "--- Release notes preview (${tag}) ---"
    cat "$notes_file"
    echo "--- end preview ---"
    echo
    echo "This will create and publish a GitHub release for ${tag}, attaching:"
    find release-dist -maxdepth 1 -type f -printf '  %f\n'

    if ! confirm "Create and publish this GitHub release now?"; then
        echo "Skipped. Your drafted notes are preserved at: $notes_file"
        return 0
    fi

    gh release create "$tag" release-dist/* --title "OTAmpy ${tag}" --notes-file "$notes_file"
    rm -f "$notes_file"
    echo "GitHub release ${tag} published: $(gh release view "$tag" --json url -q .url 2>/dev/null || echo "$tag")"
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
  ./release.sh --no-publish           Run version bump, docs commit, and the
                                       full release gate (lint, tests, build,
                                       artifact checks), then stop. Does NOT
                                       publish to PyPI, push to any remote,
                                       tag, or create a GitHub release.
                                       Verified artifacts are left in
                                       release-dist/ and local commits stay
                                       unpushed.
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

# --- Argument parsing --------------------------------------------------------
NO_PUBLISH=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            usage
            exit 0
            ;;
        --no-publish)
            NO_PUBLISH=true
            shift
            ;;
        *)
            usage
            abort "unrecognized argument: ${1}"
            ;;
    esac
done

echo "=== OTAmpy Release ==="

# --- 0. Check for a clean worktree ------------------------------------------
if [ -z "$(git status --porcelain)" ]; then
  echo "Worktree is clean"
else
  echo "Worktree is dirty"
  exit 1
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

if [[ "$NO_PUBLISH" == true ]]; then
    echo
    echo "=== --no-publish: stopping before PyPI publish ==="
    echo "Verified artifacts are in release-dist/ for inspection only."
    echo "The version-bump and docs commits made above exist locally on this"
    echo "branch but have NOT been pushed. Nothing was published, tagged, or"
    echo "released on GitHub. To discard this dry run and reset your branch:"
    echo "  git reset --hard @{upstream}"
    exit 0
fi

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
    echo "Afterwards, create the GitHub release yourself, e.g.:"
    echo "  gh release create v${NEW_VERSION} release-dist/* --title \"OTAmpy v${NEW_VERSION}\""
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
echo "Tag v${NEW_VERSION} pushed."

# --- 11. Create the GitHub release -------------------------------------------
echo
echo "Creating the GitHub release for v${NEW_VERSION}..."
create_github_release "$NEW_VERSION"

echo
echo "=== Release v${NEW_VERSION} complete ==="
