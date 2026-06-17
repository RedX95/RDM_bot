#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="${PROJECT_DIR:-/repo}"
DEPLOY_LOG_FILE="${DEPLOY_LOG_FILE:-$PROJECT_DIR/deploy.log}"

mkdir -p "$(dirname "$DEPLOY_LOG_FILE")"

{
  echo
  echo "==> Webhook received at $(date -Is)"
  /bin/bash "$PROJECT_DIR/deploy/redeploy.sh"
  echo "==> Webhook finished at $(date -Is)"
} 2>&1 | tee -a "$DEPLOY_LOG_FILE"
