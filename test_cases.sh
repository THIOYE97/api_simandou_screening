#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
EMAIL="${EMAIL:-admin@test.com}"
PASSWORD="${PASSWORD:-tonmotdepasse}"

# --- helpers ---------------------------------------------------------------

PASS_COUNT=0
FAIL_COUNT=0

hr() { echo "----------------------------------------------------------------------"; }

have_cmd() { command -v "$1" >/dev/null 2>&1; }

json_get() {
  # json_get '<json>' 'key'
  python3 - <<'PY' "$1" "$2"
import json,sys
data=json.loads(sys.argv[1])
key=sys.argv[2]
print(data.get(key, ""))
PY
}

pretty() {
  # Pretty print JSON if possible, else raw.
  python3 - <<'PY'
import sys, json
raw = sys.stdin.read()
raw = raw.strip()
if not raw:
    sys.exit(0)
try:
    obj=json.loads(raw)
    print(json.dumps(obj, indent=2, ensure_ascii=False))
except Exception:
    print(raw)
PY
}

request() {
  # request METHOD PATH BODY(optional) AUTH(optional true/false)
  local method="$1"
  local path="$2"
  local body="${3:-}"
  local auth="${4:-true}"

  local url="${BASE_URL}${path}"
  local tmp_body
  tmp_body="$(mktemp)"

  local -a args
  args=(-s -S -X "$method" "$url" -H "Content-Type: application/json")

  if [[ "$auth" == "true" ]]; then
    args+=(-H "Authorization: Bearer ${TOKEN:-}")
  fi

  if [[ -n "$body" ]]; then
    args+=(-d "$body")
  fi

  # capture http code separately
  local http_code
  http_code="$(curl "${args[@]}" -o "$tmp_body" -w "%{http_code}")"

  local resp
  resp="$(cat "$tmp_body")"
  rm -f "$tmp_body"

  echo "$http_code" $'\n' "$resp"
}

run_test() {
  # run_test "NAME" METHOD PATH BODY AUTH expected_http_regex
  local name="$1"
  local method="$2"
  local path="$3"
  local body="${4:-}"
  local auth="${5:-true}"
  local expect="${6:-^2}"

  echo
  echo "🧪 $name"
  hr

  local out http body_out
  out="$(request "$method" "$path" "$body" "$auth")"
  http="$(echo "$out" | head -n 1 | tr -d '\r')"
  body_out="$(echo "$out" | tail -n +2)"

  if [[ "$http" =~ $expect ]]; then
    echo "✅ OK (HTTP $http)"
    echo "$body_out" | pretty
    PASS_COUNT=$((PASS_COUNT+1))
  else
    echo "❌ FAIL (HTTP $http) — attendu $expect"
    echo "$body_out" | pretty
    FAIL_COUNT=$((FAIL_COUNT+1))
  fi
}

extract_json_field() {
  # extract_json_field '<json>' 'path' (simple: top-level key only)
  python3 - <<'PY' "$1" "$2"
import json,sys
data=json.loads(sys.argv[1])
key=sys.argv[2]
print(data.get(key, ""))
PY
}

extract_nested() {
  # extract_nested '<json>' 'a.b.c' (best-effort)
  python3 - <<'PY' "$1" "$2"
import json,sys
data=json.loads(sys.argv[1])
path=sys.argv[2].split(".")
cur=data
for p in path:
    if isinstance(cur, dict) and p in cur:
        cur=cur[p]
    else:
        print("")
        sys.exit(0)
print(cur if not isinstance(cur,(dict,list)) else json.dumps(cur))
PY
}

must() {
  if [[ -z "${1:-}" ]]; then
    echo "❌ Erreur: variable vide: $2"
    exit 1
  fi
}

# --- start -----------------------------------------------------------------

echo "BASE_URL=$BASE_URL"
echo "EMAIL=$EMAIL"
echo

# 1) LOGIN
echo "🔐 Login..."
LOGIN_OUT="$(request "POST" "/auth/login" "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}" "false")"
LOGIN_HTTP="$(echo "$LOGIN_OUT" | head -n 1 | tr -d '\r')"
LOGIN_BODY="$(echo "$LOGIN_OUT" | tail -n +2)"

if [[ ! "$LOGIN_HTTP" =~ ^2 ]]; then
  echo "❌ Login failed (HTTP $LOGIN_HTTP)"
  echo "$LOGIN_BODY" | pretty
  exit 1
fi

TOKEN="$(python3 - <<'PY' "$LOGIN_BODY"
import json,sys
print(json.loads(sys.argv[1]).get("access_token",""))
PY
)"
must "$TOKEN" "TOKEN"
echo "✅ Login OK (HTTP $LOGIN_HTTP)"
echo "TOKEN obtenu."

# 2) Create KYB case
echo
echo "➕ Create KYB case..."
CREATE_KYB_OUT="$(request "POST" "/cases" '{"case_type":"KYB"}' "true")"
CREATE_KYB_HTTP="$(echo "$CREATE_KYB_OUT" | head -n 1 | tr -d '\r')"
CREATE_KYB_BODY="$(echo "$CREATE_KYB_OUT" | tail -n +2)"
if [[ ! "$CREATE_KYB_HTTP" =~ ^2 ]]; then
  echo "❌ Create KYB case failed (HTTP $CREATE_KYB_HTTP)"
  echo "$CREATE_KYB_BODY" | pretty
  exit 1
fi

CASE_ID="$(python3 - <<'PY' "$CREATE_KYB_BODY"
import json,sys
print(json.loads(sys.argv[1]).get("id",""))
PY
)"
must "$CASE_ID" "CASE_ID"
echo "✅ KYB created: $CASE_ID"

# 3) Create KYC case (to get a person entity_id)
echo
echo "➕ Create KYC case..."
CREATE_KYC_OUT="$(request "POST" "/cases" '{"case_type":"KYC"}' "true")"
CREATE_KYC_HTTP="$(echo "$CREATE_KYC_OUT" | head -n 1 | tr -d '\r')"
CREATE_KYC_BODY="$(echo "$CREATE_KYC_OUT" | tail -n +2)"
if [[ ! "$CREATE_KYC_HTTP" =~ ^2 ]]; then
  echo "❌ Create KYC case failed (HTTP $CREATE_KYC_HTTP)"
  echo "$CREATE_KYC_BODY" | pretty
  exit 1
fi

KYC_ID="$(python3 - <<'PY' "$CREATE_KYC_BODY"
import json,sys
print(json.loads(sys.argv[1]).get("id",""))
PY
)"
must "$KYC_ID" "KYC_ID"
echo "✅ KYC created: $KYC_ID"

# --- TESTS -----------------------------------------------------------------

# GET /cases list
run_test "List cases" "GET" "/cases" "" "true" "^2"

# GET /cases?status=DRAFT
run_test "List cases filtered by status=DRAFT" "GET" "/cases?status=DRAFT" "" "true" "^2"

# GET /cases?q=<id>
run_test "Search cases by q=<CASE_ID>" "GET" "/cases?q=${CASE_ID}" "" "true" "^2"

# GET /cases/{case_id} detail KYB
run_test "Get KYB case detail" "GET" "/cases/${CASE_ID}" "" "true" "^2"

# PATCH /cases/{case_id}
run_test "Update KYB case (PATCH status/risk/urgent)" "PATCH" "/cases/${CASE_ID}" \
'{"status":"ACTION_REQUIRED","urgent_flag":true,"urgent_reason":"Docs manquants","risk_level":"MEDIUM"}' "true" "^2"

# PUT /cases/{case_id}/company
run_test "Upsert company for KYB case" "PUT" "/cases/${CASE_ID}/company" \
'{"legal_name":"ACME SARL","registration_number":"SN-RCCM-2026-A-0001","country":"SN","incorporation_date":"2023-01-15","address_line1":"Dakar Plateau"}' "true" "^2"

# PUT /cases/{kyc_id}/person
run_test "Upsert person for KYC case" "PUT" "/cases/${KYC_ID}/person" \
'{"first_names":"Moussa","last_name":"Diop","nationality":"SN","dob":"1990-05-12"}' "true" "^2"

# Get KYC case detail to extract person.entity_id
echo
echo "🔎 Extract person_entity_id from KYC detail..."
KYC_DETAIL_OUT="$(request "GET" "/cases/${KYC_ID}" "" "true")"
KYC_DETAIL_HTTP="$(echo "$KYC_DETAIL_OUT" | head -n 1 | tr -d '\r')"
KYC_DETAIL_BODY="$(echo "$KYC_DETAIL_OUT" | tail -n +2)"

if [[ ! "$KYC_DETAIL_HTTP" =~ ^2 ]]; then
  echo "❌ Get KYC detail failed (HTTP $KYC_DETAIL_HTTP)"
  echo "$KYC_DETAIL_BODY" | pretty
else
  PERSON_ENTITY_ID="$(python3 - <<'PY' "$KYC_DETAIL_BODY"
import json,sys
d=json.loads(sys.argv[1])
p=d.get("person") or {}
print(p.get("entity_id",""))
PY
)"
  if [[ -z "$PERSON_ENTITY_ID" ]]; then
    echo "⚠️  Impossible d'extraire person.entity_id depuis /cases/$KYC_ID"
    echo "$KYC_DETAIL_BODY" | pretty
  else
    echo "✅ person_entity_id=$PERSON_ENTITY_ID"
  fi
fi

# POST /cases/{case_id}/company/people (UBO)
if [[ -n "${PERSON_ENTITY_ID:-}" ]]; then
  run_test "Add company person (UBO) to KYB case" "POST" "/cases/${CASE_ID}/company/people" \
"{\"person_entity_id\":\"${PERSON_ENTITY_ID}\",\"role_type\":\"UBO\",\"ownership_pct\":25}" "true" "^2"
else
  echo
  echo "🧪 Add company person (UBO) to KYB case"
  hr
  echo "❌ SKIP — person_entity_id manquant (voir étape extraction KYC detail)"
  FAIL_COUNT=$((FAIL_COUNT+1))
fi

# Re-check KYB detail after company + people
run_test "Get KYB case detail (after updates)" "GET" "/cases/${CASE_ID}" "" "true" "^2"

# Negative test: call /cases without token should fail (expect 401/403)
run_test "NEGATIVE: Create case without token should fail" "POST" "/cases" '{"case_type":"KYB"}' "false" "^(401|403)$"

# --- summary ---------------------------------------------------------------

echo
hr
echo "✅ PASS: $PASS_COUNT"
echo "❌ FAIL: $FAIL_COUNT"
hr

if [[ "$FAIL_COUNT" -gt 0 ]]; then
  exit 2
fi
echo "🎉 All tests passed!"
