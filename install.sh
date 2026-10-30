#!/bin/sh
set -eu
umask 077
KIT_SOURCE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
for KIT_ARG in "$@"; do
  if [ "$KIT_ARG" = "--dry-run" ]; then
    if command -v python3 >/dev/null 2>&1; then exec python3 "$KIT_SOURCE/install.py" "$@"; fi
    echo "Would install pinned uv, managed Python 3.12, OMP and Graphify in a dedicated user directory. No changes made."
    exit 0
  fi
done
case "$(uname -s)" in
  Darwin) KIT_OS=apple-darwin ;;
  Linux)
    KIT_OS=unknown-linux-gnu
    if [ -f /etc/alpine-release ] || ls /lib/ld-musl-*.so* >/dev/null 2>&1; then KIT_OS=unknown-linux-musl; fi
    ;;
  *) echo "Use install.ps1 on Windows. Supported shells: macOS and Linux/WSL." >&2; exit 1 ;;
esac
case "$(uname -m)" in
  arm64|aarch64) KIT_ARCH=aarch64 ;;
  x86_64|amd64) KIT_ARCH=x86_64 ;;
  *) echo "A 64-bit x86 or ARM device is required." >&2; exit 1 ;;
esac
KIT_TRIPLE=$KIT_ARCH-$KIT_OS
. "$KIT_SOURCE/scripts/bootstrap-assets.sh"
kit_uv_asset "$KIT_TRIPLE"
KIT_CACHE=${XDG_CACHE_HOME:-"$HOME/.cache"}/omp-context-kit/bootstrap
mkdir -p "$KIT_CACHE"
chmod 700 "$KIT_CACHE"
KIT_TEMP=$(mktemp -d "$KIT_CACHE/run.XXXXXX")
trap 'rm -rf "$KIT_TEMP"' EXIT HUP INT TERM
KIT_ARCHIVE=$KIT_TEMP/uv.tar.gz
curl -fLSs --retry 2 "$KIT_UV_URL" -o "$KIT_ARCHIVE"
if command -v sha256sum >/dev/null 2>&1; then
  KIT_ACTUAL=$(sha256sum "$KIT_ARCHIVE" | cut -d ' ' -f 1)
else
  KIT_ACTUAL=$(shasum -a 256 "$KIT_ARCHIVE" | cut -d ' ' -f 1)
fi
if [ "$KIT_ACTUAL" != "$KIT_UV_SHA256" ]; then echo "uv SHA-256 mismatch; bootstrap stopped." >&2; exit 1; fi
tar -xzf "$KIT_ARCHIVE" -C "$KIT_TEMP" "uv-$KIT_TRIPLE/uv"
KIT_UV=$KIT_TEMP/uv-$KIT_TRIPLE/uv
chmod 700 "$KIT_UV"
"$KIT_UV" run --no-project --no-config --python 3.12 "$KIT_SOURCE/install.py" --uv "$KIT_UV" "$@"
