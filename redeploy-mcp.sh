#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------------------------------------
# Rebuilds the MCP server image from current source and pushes it to the
# already-deployed Azure Container App. Use this for routine code changes
# (server.py, config/, etc.) — it does NOT create or reconfigure any Azure
# resources. For first-time tenant setup, use deploy.sh instead.
#
# Usage:
#   bash redeploy-mcp.sh
#   RG=other-rg ACR=other-acr APP=other-app bash redeploy-mcp.sh   # different tenant
# ---------------------------------------------------------------------------

SUBSCRIPTION_ID="${SUBSCRIPTION_ID:-d5348d19-ba9e-42f9-8c93-92978dda36b5}"
RG="${RG:-MWC_Offering}"
ACR="${ACR:-agenttelemcpmwc1}"
APP="${APP:-agenttele-mcp}"

# Clear any SP env vars that would override az CLI's logged-in identity
unset AZURE_CLIENT_ID AZURE_CLIENT_SECRET AZURE_TENANT_ID AZURE_SUBSCRIPTION_ID 2>/dev/null || true

cd "$(dirname "$0")"

TAG="v$(date +%s)"

echo ""
echo "======================================================"
echo "  Redeploying MCP server"
echo "  Subscription:    $SUBSCRIPTION_ID"
echo "  Resource group:  $RG"
echo "  ACR:             $ACR"
echo "  Container App:   $APP"
echo "  New tag:         $TAG"
echo "======================================================"
echo ""

az account set --subscription "$SUBSCRIPTION_ID"

echo "==> Building and pushing image..."
az acr build -r "$ACR" --subscription "$SUBSCRIPTION_ID" -t "${APP}:${TAG}" .

echo "==> Updating Container App to new image..."
az containerapp update -n "$APP" -g "$RG" --subscription "$SUBSCRIPTION_ID" \
  --image "${ACR}.azurecr.io/${APP}:${TAG}" \
  --revision-suffix "$TAG"

echo "==> Waiting for the new revision to come up..."
sleep 5
FQDN=$(az containerapp show -n "$APP" -g "$RG" --subscription "$SUBSCRIPTION_ID" \
  --query properties.configuration.ingress.fqdn -o tsv)

echo "==> Health check..."
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 15 "https://${FQDN}/" || echo "000")

echo ""
echo "======================================================"
if [ "$HTTP_CODE" = "200" ]; then
  echo "  Redeploy complete — revision ${APP}--${TAG} is healthy (HTTP $HTTP_CODE)"
else
  echo "  WARNING: health check returned HTTP $HTTP_CODE — check logs:"
  echo "    az containerapp logs show -n $APP -g $RG --revision ${APP}--${TAG} --tail 50"
fi
echo "  MCP SSE endpoint: https://${FQDN}/sse"
echo "======================================================"
