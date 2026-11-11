#!/usr/bin/env bash
set -euo pipefail

PORT="${1:-${IMAGE_WATERMARK_PORT:-3020}}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="$ROOT_DIR/.external/image-watermark"

if [[ ! -d "$APP_DIR/.git" ]]; then
  echo "Missing .external/image-watermark. Clone it first:"
  echo "  git clone https://github.com/xyh9949/image-watermark.git .external/image-watermark"
  exit 1
fi

cd "$APP_DIR"

if [[ ! -d node_modules ]]; then
  npm ci
fi

exec npm run dev -- --port "$PORT"
