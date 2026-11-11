#!/usr/bin/env bash
set -euo pipefail

API_BASE="${API_BASE:-http://127.0.0.1:8789/api}"

if ! command -v jq >/dev/null 2>&1; then
  echo "jq is required for this verifier."
  exit 1
fi

curl -fsS --max-time 10 "$API_BASE/health" >/dev/null

jq -n '{
  platform:"抖音短视频",
  keywords:"夏天通勤 小风扇 防晒衣 桌面收纳",
  raw_text:"夏天通勤最怕出门就狼狈 | 赞:1200 | 评:88\n小风扇别乱买，看这 5 点 | 赞:2400 | 评:166\n办公室桌面乱的人可以试试这个 | 赞:680 | 评:43\n短袖显不显胖真的看肩线 | 赞:900 | 评:71",
  save_asset:true
}' | curl -fsS --max-time 30 -X POST "$API_BASE/commerce-learning/market-opportunities" -H 'Content-Type: application/json' -d @- > /tmp/xhs_market_radar_verify.json

jq -r '
  "samples=" + (.item.sample_count|tostring),
  "top_product=" + .item.product_picks[0].name + " score=" + (.item.product_picks[0].score|tostring),
  "top_mode=" + .item.sales_modes[0].name + " score=" + (.item.sales_modes[0].score|tostring),
  "asset=" + (.asset.id // "none")
' /tmp/xhs_market_radar_verify.json

PICK_COUNT="$(jq '.item.product_picks|length' /tmp/xhs_market_radar_verify.json)"
MODE_COUNT="$(jq '.item.sales_modes|length' /tmp/xhs_market_radar_verify.json)"
if [[ "$PICK_COUNT" -lt 3 || "$MODE_COUNT" -lt 3 ]]; then
  echo "Verifier failed: expected at least 3 product picks and 3 sales modes."
  exit 1
fi

echo "Market radar verifier passed."
