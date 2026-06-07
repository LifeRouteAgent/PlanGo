#!/bin/sh
set -eu

cat > /usr/share/nginx/html/app-config.json <<EOF
{
  "amap_key": "${AMAP_API_KEY:-}",
  "amap_security_js_code": "${AMAP_SECURITY_JS_CODE:-}"
}
EOF
