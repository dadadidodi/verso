#!/usr/bin/env bash

set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 PROJECT_ID [OUT_DIR]" >&2
  exit 2
fi

PROJECT_ID="$1"
OUT_DIR="${2:-dist-reader}"

if [[ -z "${DUREADING_READER_PASSWORD:-}" && -z "${DUREADING_READER_PASSWORD_HASH:-}" ]]; then
  echo "Set DUREADING_READER_PASSWORD or DUREADING_READER_PASSWORD_HASH before publishing." >&2
  exit 2
fi

ARGS=(--project-id "${PROJECT_ID}" --out "${OUT_DIR}")
if [[ -n "${DUREADING_READER_PASSWORD_HASH:-}" ]]; then
  ARGS+=(--reader-password-hash "${DUREADING_READER_PASSWORD_HASH}")
else
  ARGS+=(--reader-password "${DUREADING_READER_PASSWORD}")
fi

python3 export_reader_site.py "${ARGS[@]}"

echo
echo "Reader site exported to ${OUT_DIR}."
echo "Preview: python3 -m http.server 9000 --directory ${OUT_DIR}"
echo "Deploy:  vercel deploy ${OUT_DIR} --prod"
