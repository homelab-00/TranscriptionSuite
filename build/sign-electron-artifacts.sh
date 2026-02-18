#!/usr/bin/env bash
# Create armored detached GPG signatures for packaged Electron artifacts.
# Supported artifacts in release dir:
#   *.AppImage, *.exe, *.dmg, *.zip
#
# Required env:
#   GPG_KEY_ID         - key id / fingerprint used to sign
#
# Optional env:
#   GPG_PASSPHRASE     - when set, use non-interactive loopback mode
#   GPG_TIMEOUT_MINUTES- timeout for each signing command (default: 45)
#
# Usage:
#   ./build/sign-electron-artifacts.sh [release_dir]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
RELEASE_DIR="${1:-$PROJECT_ROOT/dashboard/release}"
GPG_TIMEOUT_MINUTES="${GPG_TIMEOUT_MINUTES:-45}"

if ! command -v gpg >/dev/null 2>&1; then
  echo "ERROR: gpg not found on PATH."
  exit 1
fi

if [[ ! -d "$RELEASE_DIR" ]]; then
  echo "ERROR: release directory not found: $RELEASE_DIR"
  exit 1
fi

if [[ -z "${GPG_KEY_ID:-}" ]]; then
  echo "ERROR: GPG_KEY_ID is required."
  exit 1
fi

# Required for interactive pinentry in many shells.
if [[ -z "${GPG_PASSPHRASE:-}" ]] && [[ -t 0 ]]; then
  export GPG_TTY
  GPG_TTY="$(tty)"
fi

run_with_optional_timeout() {
  if command -v timeout >/dev/null 2>&1; then
    timeout --foreground "${GPG_TIMEOUT_MINUTES}m" "$@"
  else
    "$@"
  fi
}

artifacts=()
while IFS= read -r artifact; do
  artifacts+=("$artifact")
done < <(
  find "$RELEASE_DIR" -maxdepth 1 -type f \
    \( -name "*.AppImage" -o -name "*.exe" -o -name "*.dmg" -o -name "*.zip" \) \
    ! -name "*.asc" \
    | sort
)

if [[ "${#artifacts[@]}" -eq 0 ]]; then
  echo "ERROR: no release artifacts found in $RELEASE_DIR"
  exit 1
fi

echo "Signing ${#artifacts[@]} artifact(s) in $RELEASE_DIR"
for artifact in "${artifacts[@]}"; do
  signature_path="${artifact}.asc"
  echo "→ Signing $(basename "$artifact")"

  if [[ -n "${GPG_PASSPHRASE:-}" ]]; then
    run_with_optional_timeout \
      gpg --batch --yes --pinentry-mode loopback \
      --passphrase "$GPG_PASSPHRASE" \
      --local-user "$GPG_KEY_ID" \
      --armor --detach-sign \
      --output "$signature_path" \
      "$artifact"
  else
    run_with_optional_timeout \
      gpg --yes \
      --local-user "$GPG_KEY_ID" \
      --armor --detach-sign \
      --output "$signature_path" \
      "$artifact"
  fi

  echo "✓ Created $(basename "$signature_path")"
done

echo "Done. Armored signatures are in: $RELEASE_DIR"
