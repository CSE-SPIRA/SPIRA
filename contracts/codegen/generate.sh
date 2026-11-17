#!/usr/bin/env bash
# Regenerate the data models in contracts/generated/ from contracts/schemas/ and enums.json.
# Run from anywhere after changing a schema; CI fails if generated/ is out of date.
# Needs: pip install -r contracts/check/requirements.txt, Node.js (npx).
set -euo pipefail
C="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/schemas" && cp "$C"/schemas/*.json "$TMP/schemas/"

# Python (pydantic v2): server and hub
PKG="$C/generated/python/spira_contracts"
rm -rf "$PKG"
(cd "$TMP" && datamodel-codegen --input schemas --input-file-type jsonschema --output "$PKG" \
  --output-model-type pydantic_v2.BaseModel --target-python-version 3.12 \
  --use-standard-collections --use-union-operator --disable-timestamp \
  --use-title-as-name --collapse-root-models --use-schema-description --use-field-description \
  --capitalise-enum-members --formatters black isort 2>/dev/null)
mkdir -p "$PKG/data"
cp "$C"/schemas/*.json "$PKG/data/" && cp "$C/enums.json" "$PKG/data/"
cp "$C/codegen/validate.py" "$PKG/validate.py"

# Dart: app
mkdir -p "$C/generated/dart"
(cd "$TMP/schemas" && npx --yes quicktype@26.0.0 --lang dart -s schema --quiet \
  $(ls *.json | grep -v '^common.json$') -o "$C/generated/dart/spira_contracts.dart")
echo "generated: $PKG, $C/generated/dart/spira_contracts.dart"
