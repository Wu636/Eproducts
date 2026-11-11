#!/usr/bin/env bash
set -euo pipefail

PORT="${1:-${CLIPFORGE_PORT:-3010}}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLIPFORGE_DIR="$ROOT_DIR/.external/clipforge"

if [[ ! -d "$CLIPFORGE_DIR/.git" ]]; then
  echo "Missing .external/clipforge. Clone it first:"
  echo "  git clone https://github.com/xixihhhh/clipforge.git .external/clipforge"
  exit 1
fi

cd "$CLIPFORGE_DIR"

if [[ ! -d node_modules ]]; then
  pnpm install || {
    echo "pnpm install needs build approval; approving pending local builds and retrying..."
    pnpm approve-builds --all || true
    pnpm install
  }
else
  pnpm approve-builds --all >/dev/null 2>&1 || true
fi

exec pnpm exec next dev --webpack -p "$PORT"
