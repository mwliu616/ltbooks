#!/usr/bin/env bash
# ============================================================================
# Build the two LtBooks Ver 1.0 clean deployment packages from the working tree.
#   auto   — full automatic install: only asks for a domain or server IP
#   manual — manual install: operator prepares the environment, script deploys
# Copyright (c) 2026 LEDU TECH CO., LIMITED
# SPDX-License-Identifier: MIT
#
# Unlike the legacy builder, this script never uses an old Git commit and never
# includes a production baseline. SQL is exported without rows; only the entity
# shell, chart of accounts and tax-rate master data are added separately.
# ============================================================================
set -euo pipefail

BACKEND="${LTBOOKS_BACKEND:-/opt/ltbooks/app}"
FRONTEND="${LTBOOKS_FRONTEND:-/opt/ltbooks/web}"
VERSION="${1:-1.1}"
DATE="$(TZ=Asia/Shanghai date +%Y%m%d)"
DEST="${RELEASE_DIR:-$FRONTEND/files/releases}"
DB_NAME="${LTBOOKS_BUILD_DB:-ltbooks}"
WORK="$(mktemp -d)"
COMMON="$WORK/common"
trap 'rm -rf "$WORK"' EXIT

printf '==> Preparing Lt-AI-Books %s clean source (%s)\n' "$VERSION" "$DATE"
mkdir -p "$COMMON"/{backend,frontend,sql,docs} "$DEST"

# Copy the actual reviewed working tree. Runtime files, credentials, old docs,
# migrations containing demonstration rows and generated reports are excluded.
rsync -a \
  --exclude '.git' --exclude '.env' --exclude '.env.*' --exclude 'venv' \
  --exclude 'storage' --exclude '__pycache__' --exclude '*.pyc' \
  --exclude 'docs' --exclude 'docs-legacy' --exclude 'reports-out' \
  --exclude 'reports-i18n' --exclude 'sql' --exclude 'tests' \
  --exclude '初始账号.txt' --exclude '账号口令.txt' --exclude 'CHANGELOG.md' \
  "$BACKEND/" "$COMMON/backend/"
rsync -a \
  --exclude '.git' --exclude '.user.ini' --exclude 'files' --exclude 'storage' \
  --exclude 'tests' --exclude 'README.md' \
  "$FRONTEND/" "$COMMON/frontend/"

cp "$BACKEND/requirements.txt" "$COMMON/requirements.txt"
cp "$BACKEND/.env.example" "$COMMON/.env.example"
cp "$BACKEND/LICENSE" "$COMMON/LICENSE"
cp "$BACKEND/tools/package-readme.md" "$COMMON/README.md"
# All documentation is English by default. Two Chinese editions of the deployment
# guide ship alongside it.
declare -A DOC_MAP=(
  ["README.md"]="README.md"
  ["HOWTO.md"]="HOWTO.md"
  ["DEPLOYMENT.md"]="DEPLOYMENT.md"
  ["DEPLOYMENT.zh-CN.md"]="DEPLOYMENT.zh-CN.md"
  ["DEPLOYMENT.zh-HK.md"]="DEPLOYMENT.zh-HK.md"
  ["DEVELOPMENT.md"]="DEVELOPMENT.md"
  ["RELEASE.md"]="RELEASE.md"
)
for source_name in "${!DOC_MAP[@]}"; do
  source_path="$FRONTEND/files/$source_name"
  if [[ -f "$source_path" ]]; then
    cp "$source_path" "$COMMON/docs/${DOC_MAP[$source_name]}"
  fi
done

printf '==> Exporting schema without business rows\n'
{
  printf -- '-- LtBooks Ver 1.0 clean database schema; no business data.\n'
  printf -- '-- Copyright (c) 2026 LEDU TECH CO., LIMITED; MIT License.\n'
  printf 'SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0;\n'
  mysqldump -uroot --no-data --routines --triggers --skip-add-drop-table \
    --skip-comments --compact --single-transaction "$DB_NAME"
  printf 'SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS;\n'
} | sed -E 's/DEFINER=[^ ]+//g; s/ AUTO_INCREMENT=[0-9]+//g' > "$COMMON/sql/01-schema.sql"

MASTER_ENTITY_ID="$(mysql -uroot -N -D "$DB_NAME" -e 'SELECT entity_id FROM entities ORDER BY entity_id LIMIT 1')"
[[ "$MASTER_ENTITY_ID" =~ ^[0-9]+$ ]] || { printf 'Cannot determine master entity ID\n' >&2; exit 1; }
{
  printf -- '-- LtBooks clean master data: one editable entity shell, accounts and tax rates only.\n'
  printf -- '-- No customers, vendors, documents, journals, bank accounts, FX cache or users.\n'
  printf 'INSERT INTO entities (entity_id,entity_code,entity_name,reporting_framework,two_tier_status,functional_currency,fiscal_year_end_mmdd) VALUES (%s,%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE entity_name=VALUES(entity_name);\n' \
    "$MASTER_ENTITY_ID" "'COMPANY'" "'My Company'" "'full_hkfrs'" "'undetermined'" "'HKD'" "'12-31'"
  mysqldump -uroot --no-create-info --complete-insert --insert-ignore --skip-triggers \
    --skip-comments --compact "$DB_NAME" accounts tax_rates --where="entity_id=$MASTER_ENTITY_ID"
} | sed 's/�/—/g' > "$COMMON/sql/02-master-data.sql"

cp "$BACKEND/tools/install.sh" "$COMMON/install.sh"
chmod 755 "$COMMON/install.sh"

build_variant() {
  local variant="$1"
  local name="LtBooks-Ver1.0-${variant}-clean-${DATE}"
  local stage="$WORK/$name"
  mkdir -p "$stage"
  cp -a "$COMMON"/. "$stage/"

  case "$variant" in
    auto)
      ;;
    manual)
      cp "$BACKEND/tools/install-manual.sh" "$stage/install-manual.sh"
      chmod 755 "$stage/install-manual.sh"
      ;;
    *) printf 'Unknown variant: %s\n' "$variant" >&2; return 1 ;;
  esac

  printf '{"product":"Lt-AI-Books","version":"%s","variant":"%s","clean":true,"built":"%s"}\n' \
    "$VERSION" "$variant" "$DATE" > "$stage/PACKAGE.json"
  (
    cd "$stage"
    while IFS= read -r -d '' file; do
      relative="${file#./}"
      [[ "$relative" == "MANIFEST.txt" ]] && continue
      sha256sum "$relative"
    done < <(find . -type f -print0 | sort -z) > MANIFEST.txt
  )

  local archive
  # Remove any previous artefact first: `zip -r` would otherwise keep members
  # that no longer exist in the staged tree, producing a stale manifest.
  if [[ "$variant" == "manual" ]]; then
    archive="$DEST/$name.zip"
    rm -f "$archive"
    (cd "$WORK" && zip -q -r "$archive" "$name")
  else
    archive="$DEST/$name.tar.gz"
    rm -f "$archive"
    tar -C "$WORK" -czf "$archive" "$name"
  fi
  (cd "$DEST" && sha256sum "$(basename "$archive")" > "$(basename "$archive").sha256")
  "$BACKEND/venv/bin/python" "$BACKEND/tools/verify_release.py" "$archive"
  printf '==> Built %s\n' "$archive"
}

build_variant auto
build_variant manual
printf '==> Both clean packages are in %s\n' "$DEST"
