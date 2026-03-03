#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
EMAIL="${EMAIL:-admin@test.com}"
PASSWORD="${PASSWORD:-tonmotdepasse}"

PASS=0
FAIL=0
FAILED_ENDPOINTS=()

hr() { echo "----------------------------------------------------------------------"; }

expect_http() {
  local name="$1"
  local endpoint="$2"
  local code="$3"
  local regex="$4"
  local body_file="$5"

  if [[ "$code" =~ $regex ]]; then
    echo "✅ OK (HTTP $code )"
    PASS=$((PASS+1))
  else
    echo "❌ FAIL (HTTP $code ) — attendu $regex"
    echo "↳ Endpoint: $endpoint"
    echo "↳ Body (extrait):"
    head -c 400 "$body_file" || true
    echo
    FAIL=$((FAIL+1))
    FAILED_ENDPOINTS+=("$name => $endpoint (HTTP $code)")
  fi
}

tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

echo "🔐 Login..."
hr
login_body="$tmpdir/login_body.txt"
login_code="$(
  curl -s -o "$login_body" -w "%{http_code}" \
    -H "Content-Type: application/json" \
    -X POST "$BASE_URL/auth/login" \
    -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}"
)"
expect_http "login" "$BASE_URL/auth/login" "$login_code" '^(200)$' "$login_body"

TOKEN="$(python3 - <<PY
import json,sys
try:
  d=json.load(open("$login_body"))
  print(d.get("access_token",""))
except Exception:
  print("")
PY
)"
if [[ -z "$TOKEN" ]]; then
  echo "❌ Impossible d'extraire access_token du login."
  exit 1
fi
echo "✅ TOKEN obtenu."

echo
echo "➕ Create KYB case (pour tester upload documents)..."
hr
case_body="$tmpdir/case_body.txt"
case_code="$(
  curl -s -o "$case_body" -w "%{http_code}" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -X POST "$BASE_URL/cases" \
    -d '{"case_type":"KYB"}'
)"
expect_http "create_case" "$BASE_URL/cases" "$case_code" '^(200|201)$' "$case_body"

CASE_ID="$(python3 - <<PY
import json
d=json.load(open("$case_body"))
print(d.get("id",""))
PY
)"
echo "✅ Case created: $CASE_ID"

# fichier dummy
echo "hello document" > "$tmpdir/sample.txt"

echo
echo "📤 Upload document (multipart form)..."
hr
upload_body="$tmpdir/upload_body.txt"
UPLOAD_ENDPOINT="$BASE_URL/documents/cases/$CASE_ID/documents"
upload_code="$(
  curl -s -o "$upload_body" -w "%{http_code}" \
    -H "Authorization: Bearer $TOKEN" \
    -X POST "$UPLOAD_ENDPOINT" \
    -F "doc_type=ID" \
    -F "file=@$tmpdir/sample.txt;type=text/plain"
)"
expect_http "upload_document" "$UPLOAD_ENDPOINT" "$upload_code" '^(200|201)$' "$upload_body"

DOC_ID=""
if [[ "$upload_code" =~ ^(200|201)$ ]]; then
  DOC_ID="$(python3 - <<PY
import json
d=json.load(open("$upload_body"))
print(d.get("id",""))
PY
)"
  echo "✅ Uploaded doc id: $DOC_ID"
fi

echo
echo "🧪 List documents for case..."
hr
list_body="$tmpdir/list_body.txt"
LIST_ENDPOINT="$BASE_URL/documents/cases/$CASE_ID/documents"
list_code="$(
  curl -s -o "$list_body" -w "%{http_code}" \
    -H "Authorization: Bearer $TOKEN" \
    -X GET "$LIST_ENDPOINT"
)"
expect_http "list_documents" "$LIST_ENDPOINT" "$list_code" '^(200)$' "$list_body"

if [[ -n "$DOC_ID" ]]; then
  echo
  echo "🧪 Get doc..."
  hr
  get_body="$tmpdir/get_body.txt"
  GET_ENDPOINT="$BASE_URL/documents/documents/$DOC_ID"
  get_code="$(
    curl -s -o "$get_body" -w "%{http_code}" \
      -H "Authorization: Bearer $TOKEN" \
      -X GET "$GET_ENDPOINT"
  )"
  expect_http "get_doc" "$GET_ENDPOINT" "$get_code" '^(200)$' "$get_body"

  echo
  echo "🧪 Download doc..."
  hr
  dl_body="$tmpdir/dl_body.txt"
  DL_ENDPOINT="$BASE_URL/documents/documents/$DOC_ID/download"
  dl_code="$(
    curl -s -o "$dl_body" -w "%{http_code}" \
      -H "Authorization: Bearer $TOKEN" \
      -X GET "$DL_ENDPOINT"
  )"
  expect_http "download_doc" "$DL_ENDPOINT" "$dl_code" '^(200)$' "$dl_body"
else
  echo
  echo "⚠️ Skip get/download: DOC_ID manquant (upload KO)"
fi

echo
echo "🧪 NEGATIVE: Upload without token should fail..."
hr
neg_body="$tmpdir/neg_body.txt"
neg_code="$(
  curl -s -o "$neg_body" -w "%{http_code}" \
    -X POST "$UPLOAD_ENDPOINT" \
    -F "doc_type=ID" \
    -F "file=@$tmpdir/sample.txt;type=text/plain"
)"
expect_http "upload_without_token" "$UPLOAD_ENDPOINT" "$neg_code" '^(401|403)$' "$neg_body"

echo
hr
echo "✅ PASS: $PASS"
echo "❌ FAIL: $FAIL"

if [[ "$FAIL" -gt 0 ]]; then
  echo
  echo "Endpoints en échec:"
  for e in "${FAILED_ENDPOINTS[@]}"; do
    echo " - $e"
  done
  exit 1
fi
