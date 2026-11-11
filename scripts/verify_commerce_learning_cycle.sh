#!/usr/bin/env bash
set -euo pipefail

API_BASE="${API_BASE:-http://127.0.0.1:8789/api}"
CLIPFORGE_BASE_URL="${CLIPFORGE_BASE_URL:-http://127.0.0.1:3010}"

if ! command -v jq >/dev/null 2>&1; then
  echo "jq is required for this verifier."
  exit 1
fi

echo "Checking backend: $API_BASE/health"
curl -fsS --max-time 10 "$API_BASE/health" | jq .

PRODUCT_ID="$(curl -fsS --max-time 15 "$API_BASE/products" | jq -r '.items[0].id')"
if [[ -z "$PRODUCT_ID" || "$PRODUCT_ID" == "null" ]]; then
  echo "No product found. Upload or seed a product first."
  exit 1
fi

echo "Running commerce learning cycle for product: $PRODUCT_ID"
jq -n --arg id "$PRODUCT_ID" --arg clip "$CLIPFORGE_BASE_URL" '{
  product_id:$id,
  platform:"抖音短视频",
  daily_target:6,
  mode:"冷启动测品",
  keywords:"通勤好物 夏天怕热 桌面收纳 快速出门",
  samples:[
    {title:"夏天通勤最怕出门就狼狈",comments:["求链接","真的能解决吗","想看实拍对比"],metrics:{likes:1200,comments:88}},
    {title:"办公室桌面乱的人可以试试这个",comments:["多少钱","放包里占地方吗"],metrics:{likes:680,comments:43}}
  ],
  feedback:[
    {style_id:"pain_seed",views:7200,likes:386,comments:58,orders:11,notes:"痛点开头表现好"}
  ],
  clipforge_base_url:$clip,
  save_asset:true
}' | curl -fsS --max-time 30 -X POST "$API_BASE/commerce-learning/run-cycle" -H 'Content-Type: application/json' -d @- > /tmp/commerce_cycle_verify.json

jq -r '
  "cycle=" + .item.id,
  "queue=" + (.item.test_queue|length|tostring),
  "workflows=" + (.workflows|length|tostring),
  "assets=" + (.assets|length|tostring),
  "clipforge=" + .clipforge_status.status,
  "first_task=" + .item.test_queue[0].slot + " " + .item.test_queue[0].type + " " + .item.test_queue[0].hook
' /tmp/commerce_cycle_verify.json

QUEUE_COUNT="$(jq '.item.test_queue|length' /tmp/commerce_cycle_verify.json)"
ASSET_COUNT="$(jq '.assets|length' /tmp/commerce_cycle_verify.json)"
if [[ "$QUEUE_COUNT" -lt 4 || "$ASSET_COUNT" -lt 2 ]]; then
  echo "Verifier failed: expected at least 4 queue items and 2 saved assets."
  exit 1
fi

echo "Commerce learning cycle verifier passed."
