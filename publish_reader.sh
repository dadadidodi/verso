#!/usr/bin/env bash

set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 PROJECT_ID [OUT_DIR]" >&2
  exit 2
fi

PROJECT_ID="$1"
OUT_DIR="${2:-dist-reader}"

if [[ -z "${VERSO_READER_PASSWORD:-}" && -z "${VERSO_READER_PASSWORDS:-}" && -z "${VERSO_READER_PASSWORD_HASH:-}" && -z "${VERSO_READER_PASSWORD_HASHES:-}" ]]; then
  echo "Set VERSO_READER_PASSWORD(S) or VERSO_READER_PASSWORD_HASH(ES) before publishing." >&2
  exit 2
fi

ARGS=(--project-id "${PROJECT_ID}" --out "${OUT_DIR}")
if [[ -n "${VERSO_READER_PASSWORD_HASH:-}" ]]; then
  ARGS+=(--reader-password-hash "${VERSO_READER_PASSWORD_HASH}")
fi
if [[ -n "${VERSO_READER_PASSWORD_HASHES:-}" ]]; then
  IFS=',' read -ra HASH_ITEMS <<< "${VERSO_READER_PASSWORD_HASHES}"
  for item in "${HASH_ITEMS[@]}"; do
    [[ -n "${item}" ]] && ARGS+=(--reader-password-hash "${item}")
  done
fi
if [[ -n "${VERSO_READER_PASSWORD:-}" ]]; then
  ARGS+=(--reader-password "${VERSO_READER_PASSWORD}")
fi
if [[ -n "${VERSO_READER_PASSWORDS:-}" ]]; then
  IFS=',' read -ra PASSWORD_ITEMS <<< "${VERSO_READER_PASSWORDS}"
  for item in "${PASSWORD_ITEMS[@]}"; do
    [[ -n "${item}" ]] && ARGS+=(--reader-password "${item}")
  done
fi

python3 -m tools.export_reader_site "${ARGS[@]}"

echo
echo "Reader site exported to ${OUT_DIR}."
echo "Preview: python3 -m http.server 9000 --directory ${OUT_DIR}"
echo "Deploy:  vercel deploy ${OUT_DIR} --prod"
