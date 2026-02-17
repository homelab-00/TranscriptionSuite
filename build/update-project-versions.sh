#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

BUILD_DIR="$PROJECT_ROOT/build"
SERVER_BACKEND_DIR="$PROJECT_ROOT/server/backend"
DASHBOARD_DIR="$PROJECT_ROOT/dashboard"

BUILD_PYPROJECT="$BUILD_DIR/pyproject.toml"
SERVER_PYPROJECT="$SERVER_BACKEND_DIR/pyproject.toml"
DASHBOARD_PACKAGE_JSON="$DASHBOARD_DIR/package.json"

TARGET_VERSION="${1:-}"

fail() {
    echo "ERROR: $*" >&2
    exit 1
}

require_command() {
    local cmd="$1"
    if ! command -v "$cmd" >/dev/null 2>&1; then
        fail "Required command not found: ${cmd}"
    fi
}

require_file() {
    local path="$1"
    if [[ ! -f "$path" ]]; then
        fail "Required file not found: ${path}"
    fi
}

update_toml_version() {
    local file="$1"
    local version="$2"

    if ! grep -Eq '^version = ".*"$' "$file"; then
        fail "No top-level version field found in: ${file}"
    fi

    sed -Ei "s/^version = \".*\"$/version = \"${version}\"/" "$file"
}

if [[ -z "$TARGET_VERSION" ]]; then
    if [[ -t 0 && -t 1 ]]; then
        read -r -p "Enter new project version: " TARGET_VERSION
    else
        fail "No version provided. Run interactively or pass the version as the first argument."
    fi
fi

if [[ -z "$TARGET_VERSION" ]]; then
    fail "Version cannot be empty."
fi

if [[ ! "$TARGET_VERSION" =~ ^[0-9A-Za-z._+-]+$ ]]; then
    fail "Version '${TARGET_VERSION}' contains unsupported characters."
fi

require_command uv
require_command npm
require_command node

require_file "$BUILD_PYPROJECT"
require_file "$SERVER_PYPROJECT"
require_file "$DASHBOARD_PACKAGE_JSON"

echo "Updating project versions to: ${TARGET_VERSION}"
update_toml_version "$BUILD_PYPROJECT" "$TARGET_VERSION"
update_toml_version "$SERVER_PYPROJECT" "$TARGET_VERSION"

node -e '
const fs = require("fs");
const path = process.argv[1];
const version = process.argv[2];
const packageJson = JSON.parse(fs.readFileSync(path, "utf8"));
packageJson.version = version;
fs.writeFileSync(path, JSON.stringify(packageJson, null, 2) + "\n");
' "$DASHBOARD_PACKAGE_JSON" "$TARGET_VERSION"

echo "Refreshing dependencies in build/"
pushd "$BUILD_DIR" >/dev/null
uv lock --upgrade
uv sync
popd >/dev/null

echo "Refreshing dependencies in server/backend/"
pushd "$SERVER_BACKEND_DIR" >/dev/null
uv lock --upgrade
uv sync
popd >/dev/null

echo "Refreshing dependencies in dashboard/"
pushd "$DASHBOARD_DIR" >/dev/null
npm update
popd >/dev/null

echo "Done. Updated versions to ${TARGET_VERSION}."
