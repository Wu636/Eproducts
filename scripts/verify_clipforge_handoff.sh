#!/usr/bin/env bash
set -euo pipefail

API_BASE="${API_BASE:-http://127.0.0.1:8789/api}"
CLIPFORGE_BASE_URL="${CLIPFORGE_BASE_URL:-http://127.0.0.1:3010}"
COMPOSE="${COMPOSE:-1}"

if ! command -v jq >/dev/null 2>&1; then
  echo "jq is required for this verifier."
  exit 1
fi

curl -fsS --max-time 10 "$API_BASE/health" >/dev/null
curl -fsS --max-time 10 "$CLIPFORGE_BASE_URL/api/project" >/dev/null

PRODUCT_ID="$(curl -fsS --max-time 15 "$API_BASE/products" | jq -r '.items[0].id')"
if [[ -z "$PRODUCT_ID" || "$PRODUCT_ID" == "null" ]]; then
  echo "No product found. Upload or seed a product first."
  exit 1
fi

echo "Building workflow from commerce learning cycle..."
jq -n --arg id "$PRODUCT_ID" --arg clip "$CLIPFORGE_BASE_URL" '{
  product_id:$id,
  platform:"抖音短视频",
  daily_target:4,
  keywords:"通勤好物 夏天怕热 桌面收纳 快速出门",
  samples:[{title:"夏天通勤最怕出门就狼狈",comments:["求链接","想看实拍"]}],
  clipforge_base_url:$clip,
  save_asset:false
}' | curl -fsS --max-time 30 -X POST "$API_BASE/commerce-learning/run-cycle" -H 'Content-Type: application/json' -d @- > /tmp/xhs_clipforge_cycle_verify.json

echo "Pushing workflow into ClipForge..."
jq -n --arg id "$PRODUCT_ID" --arg clip "$CLIPFORGE_BASE_URL" --argjson compose "$COMPOSE" --slurpfile cycle /tmp/xhs_clipforge_cycle_verify.json '{
  product_id:$id,
  workflow:$cycle[0].workflows[0],
  clipforge_base_url:$clip,
  upload_storyboard:true,
  compose:$compose,
  renderPreset:"fast",
  compose_timeout:180
}' | curl -fsS --max-time 240 -X POST "$API_BASE/commerce-learning/clipforge-project" -H 'Content-Type: application/json' -d @- > /tmp/xhs_clipforge_handoff_verify.json

jq -r '
  "project=" + .item.project_id,
  "project_url=" + .item.project_url,
  "imported_shots=" + (.item.import.shots|tostring),
  "materials=" + (.item.materials.materials|length|tostring),
  "stock_fill=" + (.item.stock_fill.filled|tostring) + "/" + (.item.stock_fill.total|tostring),
  "compose_status=" + (.item.composition.status // "not_requested"),
  "video_url=" + (.item.video_url // "")
' /tmp/xhs_clipforge_handoff_verify.json

FILLED="$(jq '.item.stock_fill.filled' /tmp/xhs_clipforge_handoff_verify.json)"
TOTAL="$(jq '.item.stock_fill.total' /tmp/xhs_clipforge_handoff_verify.json)"
if [[ "$FILLED" -lt 1 || "$FILLED" -lt "$TOTAL" ]]; then
  echo "Verifier failed: ClipForge stock-fill did not fill every shot."
  exit 1
fi

if [[ "$COMPOSE" == "1" || "$COMPOSE" == "true" ]]; then
  VIDEO_URL="$(jq -r '.item.video_url // empty' /tmp/xhs_clipforge_handoff_verify.json)"
  if [[ -z "$VIDEO_URL" ]]; then
    echo "Verifier failed: compose was requested but no video_url was returned."
    exit 1
  fi
  curl -fsSI --max-time 20 "$VIDEO_URL" | sed -n '1,8p'
fi

echo "ClipForge handoff verifier passed."
