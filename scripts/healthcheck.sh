#!/usr/bin/env bash
# Health check for ai-workflow-dashboard.
# Called by systemd timer. Restarts the service if /health does not respond.

SERVICE="ai-workflow-dashboard.service"
URL="http://127.0.0.1:9000/health"
TIMEOUT=10

if ! systemctl is-active --quiet "$SERVICE"; then
    echo "Service not active, skipping health check"
    exit 0
fi

HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time "$TIMEOUT" "$URL" 2>/dev/null)

if [ "$HTTP_CODE" != "200" ]; then
    echo "Health check failed (HTTP $HTTP_CODE), restarting $SERVICE"
    systemctl restart "$SERVICE"
else
    echo "Health check OK"
fi
