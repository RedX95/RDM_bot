#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="${PROJECT_DIR:-/repo}"
DEPLOY_BRANCH="${DEPLOY_BRANCH:-refactor-bot-structure}"
LOCK_FILE="${LOCK_FILE:-/tmp/rdm-bot-deploy.lock}"

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "Deploy already running, skip."
  exit 0
fi

cd "$PROJECT_DIR"

git config --global --add safe.directory "$PROJECT_DIR" || true

echo "==> Fetching origin/$DEPLOY_BRANCH"
git fetch origin "$DEPLOY_BRANCH"

echo "==> Resetting workspace to origin/$DEPLOY_BRANCH"
git checkout "$DEPLOY_BRANCH"
git reset --hard "origin/$DEPLOY_BRANCH"

echo "==> Rebuilding bot container"
docker compose -f docker-compose.yml up --build -d --remove-orphans rdm-bot

echo "==> Cleaning old Docker resources"
docker system prune -f

echo "==> Deploy finished"
