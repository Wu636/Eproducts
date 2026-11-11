#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

python3 -m py_compile backend/server.py backend/services/commerce_learning.py
node --check <(perl -0ne 'if(/<script>(.*)<\/script>/s){print $1}' xhs-asset-generator-2.html)

./scripts/verify_market_radar.sh
./scripts/verify_commerce_learning_cycle.sh
./scripts/verify_clipforge_handoff.sh

curl -fsSI --max-time 10 http://127.0.0.1:8790/xhs-asset-generator-2.html >/dev/null

echo "Full commerce product verifier passed."
