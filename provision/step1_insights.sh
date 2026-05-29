#!/usr/bin/env bash
# provision/phase1_insights.sh
# ─────────────────────────────────────────────────────────────────────────────
# Phase 1 — Observability Foundation
# Creates a Log Analytics Workspace and workspace-based Application Insights.
# Assumes a resource group already exists.
#
# All Azure resources are prefixed with  agenttele-insights
#
# Run in Azure Cloud Shell:
#   bash phase1_insights.sh
#
# Output: Application Insights connection string — copy it for Phase 2.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── CONFIG — fill in before running ──────────────────────────────────────────
SUBSCRIPTION_ID="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
RG="your-resource-group"            # Existing resource group name
LOCATION="eastus"        # Azure region, e.g. eastus
# ─────────────────────────────────────────────────────────────────────────────

ts()   { date "+%H:%M:%S"; }
step() { echo ""; echo "[$(ts)] ── $*"; }
info() { echo "          $*"; }
ok()   { echo "  [$(ts)] ✓  $*"; }

# Validate
for VAR in SUBSCRIPTION_ID RG LOCATION; do
  if [ -z "${!VAR:-}" ]; then
    echo "ERROR: $VAR is not set. Edit the CONFIG section at the top of this script."
    exit 1
  fi
done

LAW_NAME="agenttele-insights-law"
AI_NAME="agenttele-insights"

echo ""
echo "======================================================"
echo "  Phase 1 — Observability Foundation"
echo "  Subscription:   $SUBSCRIPTION_ID"
echo "  Resource group: $RG  ($LOCATION)"
echo "  Log Analytics:  $LAW_NAME"
echo "  App Insights:   $AI_NAME"
echo "======================================================"

step "Ensuring az CLI extensions..."
info "Checking application-insights extension..."
if az extension show -n application-insights &>/dev/null; then
  ok "application-insights extension already installed."
else
  info "Installing application-insights extension..."
  az extension add --name application-insights --upgrade --yes
  ok "application-insights extension installed."
fi

step "Setting subscription..."
az account set --subscription "$SUBSCRIPTION_ID"
ok "Subscription set."

# ── Resource providers ────────────────────────────────────────────────────────
step "Checking resource providers..."
for NS in Microsoft.OperationalInsights Microsoft.Insights; do
  info "Checking $NS..."
  STATE=$(az provider show -n "$NS" --subscription "$SUBSCRIPTION_ID" \
    --query "registrationState" -o tsv 2>/dev/null || echo "NotRegistered")
  if [ "$STATE" = "Registered" ]; then
    ok "$NS already registered."
  else
    info "Registering $NS (waiting for completion)..."
    az provider register --namespace "$NS" --subscription "$SUBSCRIPTION_ID" --wait
    ok "$NS registered."
  fi
done

# ── Log Analytics Workspace ───────────────────────────────────────────────────
step "Log Analytics Workspace: $LAW_NAME"
info "Checking existence..."
if az monitor log-analytics workspace show \
    -n "$LAW_NAME" -g "$RG" --subscription "$SUBSCRIPTION_ID" &>/dev/null; then
  ok "Already exists — skipping create."
else
  info "Creating workspace (90-day retention, PerGB2018 SKU)..."
  az monitor log-analytics workspace create \
    -n "$LAW_NAME" -g "$RG" -l "$LOCATION" \
    --subscription "$SUBSCRIPTION_ID" \
    --sku PerGB2018 \
    --retention-time 90
  ok "Workspace created."
fi

LAW_ID=$(az monitor log-analytics workspace show \
  -n "$LAW_NAME" -g "$RG" --subscription "$SUBSCRIPTION_ID" \
  --query id -o tsv)
info "Resource ID: $LAW_ID"

# ── Application Insights ──────────────────────────────────────────────────────
step "Application Insights: $AI_NAME"
info "Checking existence..."
if az monitor app-insights component show \
    -g "$RG" -a "$AI_NAME" --subscription "$SUBSCRIPTION_ID" &>/dev/null; then
  ok "Already exists — skipping create."
else
  info "Creating workspace-based Application Insights component (~30-60 seconds)..."
  az monitor app-insights component create \
    -g "$RG" -a "$AI_NAME" -l "$LOCATION" \
    --subscription "$SUBSCRIPTION_ID" \
    --workspace "$LAW_ID" \
    --application-type web
  ok "Application Insights created."
fi

info "Fetching connection string..."
AI_CONN=$(az monitor app-insights component show \
  -g "$RG" -a "$AI_NAME" --subscription "$SUBSCRIPTION_ID" \
  --query connectionString -o tsv)

AI_RESOURCE_ID=$(az monitor app-insights component show \
  -g "$RG" -a "$AI_NAME" --subscription "$SUBSCRIPTION_ID" \
  --query id -o tsv)
AI_URL="https://portal.azure.com/#resource${AI_RESOURCE_ID}/overview"

echo ""
echo "======================================================"
echo "  [$(ts)] Phase 1 complete."
echo ""
echo "  Portal link:"
echo "  $AI_URL"
echo ""
echo "  Connection string (save for Phase 2 and"
echo "  configure_agent_telemetry.py --appinsights-connection-string):"
echo ""
echo "  $AI_CONN"
echo "======================================================"
