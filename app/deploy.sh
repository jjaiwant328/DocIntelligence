#!/bin/bash
# Deploy DocIntelligence App to Databricks Apps (jai-az-ws)

show_help() {
  cat << EOF
Usage: ./deploy.sh [APP_FOLDER] [APP_NAME] [PROFILE]

Deploy the QSR Supply Chain DocIntelligence App to Databricks Apps.

ARGUMENTS:
  APP_FOLDER  Workspace path for app deployment
              Default: /Workspace/Users/jaiwant.jonathan@databricks.com/docintel-app

  APP_NAME    Databricks App name
              Default: docintel-supply-chain

  PROFILE     Databricks CLI profile
              Default: jai-az-ws

EXAMPLES:
  ./deploy.sh                                          # Deploy with defaults
  ./deploy.sh "/Workspace/Users/me@co.com/my-app" "my-app" "my-profile"
EOF
  exit 0
}

[[ "$1" == "-h" || "$1" == "--help" ]] && show_help

APP_FOLDER_IN_WORKSPACE=${1:-"/Workspace/Users/jaiwant.jonathan@databricks.com/docintel-app"}
LAKEHOUSE_APP_NAME=${2:-"docintel-supply-chain"}
PROFILE=${3:-"jai-az-ws"}

# Always resolve paths relative to THIS script's directory so deploy works
# regardless of the caller's working directory (e.g. bash app/deploy.sh vs ./deploy.sh)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "🚀 Deploying QSR Supply Chain DocIntelligence App"
echo "📁 Workspace Path : $APP_FOLDER_IN_WORKSPACE"
echo "🏷️  App Name       : $LAKEHOUSE_APP_NAME"
echo "🔑 Profile        : $PROFILE"

# ── Frontend build ────────────────────────────────────────────────────────────
echo ""
echo "🔨 Building Next.js frontend..."
(
  cd "$SCRIPT_DIR/frontend"
  npm install --silent
  npm run build

  echo "🔧 Fixing static export routing..."
  cp out/next-steps/index.html     out/next-steps.html     2>/dev/null || true
  cp out/document-intelligence/index.html out/document-intelligence.html 2>/dev/null || true
  cp out/supply-chain/index.html   out/supply-chain.html   2>/dev/null || true
  cp out/agent/index.html          out/agent.html           2>/dev/null || true
  cp out/setup/index.html          out/setup.html           2>/dev/null || true

  echo "🧹 Cleaning old static files from workspace..."
  databricks workspace delete "$APP_FOLDER_IN_WORKSPACE/static" --recursive --profile "$PROFILE" 2>/dev/null || true

  echo "📤 Uploading frontend static files..."
  # Remove large cache files that exceed Databricks workspace 10MB file limit
  find out -name "*.pack" -delete 2>/dev/null || true
  find out -path "*/.next/cache*" -delete 2>/dev/null || true
  databricks workspace import-dir out "$APP_FOLDER_IN_WORKSPACE/static" --overwrite --profile "$PROFILE"
) &

# ── Backend packaging ─────────────────────────────────────────────────────────
echo "📦 Packaging backend..."
(
  cd "$SCRIPT_DIR/backend"
  mkdir -p build
  find . -mindepth 1 -maxdepth 1 \
    -not -name '.*' \
    -not -name 'local_conf*' \
    -not -name 'build' \
    -not -name '__pycache__' \
    -exec cp -r {} build/ \;

  echo "📤 Uploading backend..."
  databricks workspace import-dir build "$APP_FOLDER_IN_WORKSPACE" --overwrite --profile "$PROFILE"
  rm -rf build
) &

wait
echo ""

# ── Clean large cache files from workspace before deploy ──────────────────────
echo "🧹 Removing build caches from workspace (avoid 10MB file limit)..."
# Remove any previously-uploaded .next cache directories (exceed 10 MB workspace limit)
for cache_path in \
    "$APP_FOLDER_IN_WORKSPACE/app/frontend/.next" \
    "$APP_FOLDER_IN_WORKSPACE/frontend/.next" \
    "$APP_FOLDER_IN_WORKSPACE/static/.next"; do
  databricks workspace delete "$cache_path" --recursive --profile "$PROFILE" 2>/dev/null || true
done

# ── Deploy app ────────────────────────────────────────────────────────────────
echo "🚀 Deploying Databricks App..."
databricks apps deploy "$LAKEHOUSE_APP_NAME" \
  --source-code-path "$APP_FOLDER_IN_WORKSPACE" \
  --profile "$PROFILE"

echo ""
echo "✅ Deployment complete!"
echo "🌐 App: $LAKEHOUSE_APP_NAME"
echo "📊 Check your Databricks workspace → Apps for the live URL."
echo ""
echo "Next steps:"
echo "  1. Open the app → Document Intelligence → upload a supply chain PDF"
echo "  2. Open Supply Chain Control Tower → view recall impact dashboard"
echo "  3. Open AI Agent → ask 'Which restaurants received the recalled product?'"
