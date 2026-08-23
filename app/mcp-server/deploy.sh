#!/bin/bash
# Deploy the DocIntelligence document-source MCP server as a standalone
# Databricks App. No frontend build — packages this directory and deploys.
set -e

APP_FOLDER=${1:-"/Workspace/Users/jaiwant.jonathan@databricks.com/docintel-sources-app"}
APP_NAME=${2:-"docintel-sources"}
PROFILE=${3:-"jai-az-ws"}
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "🚀 Deploying MCP sources server"
echo "🏷️  App: $APP_NAME   🔑 Profile: $PROFILE"

# Create the app once (no-op if it already exists).
databricks apps get "$APP_NAME" --profile "$PROFILE" >/dev/null 2>&1 \
  || databricks apps create "$APP_NAME" --profile "$PROFILE"

# Package (exclude caches) and upload.
BUILD="$SCRIPT_DIR/build"
rm -rf "$BUILD"; mkdir -p "$BUILD"
find "$SCRIPT_DIR" -mindepth 1 -maxdepth 1 \
  -not -name '.*' -not -name 'build' -not -name '__pycache__' -not -name 'deploy.sh' \
  -exec cp -r {} "$BUILD/" \;
cp "$SCRIPT_DIR/deploy.sh" "$BUILD/" 2>/dev/null || true
find "$BUILD" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true

echo "📤 Uploading..."
databricks workspace import-dir "$BUILD" "$APP_FOLDER" --overwrite --profile "$PROFILE"
rm -rf "$BUILD"

echo "🚀 Deploying app..."
databricks apps deploy "$APP_NAME" --source-code-path "$APP_FOLDER" --profile "$PROFILE"

echo "✅ Done. Get the URL: databricks apps get $APP_NAME --profile $PROFILE"
