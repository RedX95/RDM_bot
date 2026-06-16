#!/usr/bin/env sh
set -eu

: "${WEBHOOK_SECRET:?WEBHOOK_SECRET is required}"

WEBHOOK_BRANCH="${WEBHOOK_BRANCH:-refactor-bot-structure}"
WEBHOOK_PORT="${WEBHOOK_PORT:-9000}"
HOOK_ID="${HOOK_ID:-update-my-bot}"

cat > /tmp/hooks.json <<EOF
[
  {
    "id": "${HOOK_ID}",
    "execute-command": "/bin/bash",
    "command-working-directory": "/repo",
    "pass-arguments-to-command": [
      {
        "source": "string",
        "name": "/repo/deploy/redeploy.sh"
      }
    ],
    "response-message": "RDM bot deploy started",
    "trigger-rule": {
      "and": [
        {
          "match": {
            "type": "payload-hash-sha256",
            "secret": "${WEBHOOK_SECRET}",
            "parameter": {
              "source": "header",
              "name": "X-Hub-Signature-256"
            }
          }
        },
        {
          "match": {
            "type": "value",
            "value": "refs/heads/${WEBHOOK_BRANCH}",
            "parameter": {
              "source": "payload",
              "name": "ref"
            }
          }
        }
      ]
    }
  }
]
EOF

exec webhook -hooks /tmp/hooks.json -port "$WEBHOOK_PORT" -verbose
