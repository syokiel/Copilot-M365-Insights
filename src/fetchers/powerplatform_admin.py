"""
Power Platform Admin fetcher — environments, DLP policies, agent inventory.

Uses three API surfaces:
  - BAP Admin API  (api.bap.microsoft.com)    — environments, DLP fallback
  - PP Admin API   (api.powerplatform.com)    — DLP connector policies, Inventory
  - Inventory API  (api.powerplatform.com)    — tenant-wide V2 agent list

Requires Power Platform Administrator role on the service principal.
"""
import requests
from azure.core.credentials import TokenCredential

_PP_API_BASE     = "https://api.powerplatform.com"
_PP_SCOPE        = "https://api.powerplatform.com/.default"
_INVENTORY_API   = f"{_PP_API_BASE}/resourcequery/resources/query?api-version=2024-10-01"
_INVENTORY_PAGE  = 1000

_BAP_BASE  = "https://api.bap.microsoft.com"
_BAP_SCOPE = "https://api.bap.microsoft.com/.default"


class PowerPlatformAdminFetcher:
    def __init__(self, credential: TokenCredential) -> None:
        self._credential = credential

    def _pp_headers(self) -> dict:
        token = self._credential.get_token(_PP_SCOPE).token
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _bap_headers(self) -> dict:
        token = self._credential.get_token(_BAP_SCOPE).token
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # ------------------------------------------------------------------
    # Environments (BAP Admin API)
    # ------------------------------------------------------------------

    def fetch_environments(self) -> list[dict]:
        """All Power Platform environments — requires Power Platform Administrator role."""
        resp = requests.get(
            f"{_BAP_BASE}/providers/Microsoft.BusinessAppPlatform/scopes/admin/environments",
            headers=self._bap_headers(),
            params={"api-version": "2021-04-01"},
            timeout=30,
        )
        resp.raise_for_status()
        out = []
        for e in resp.json().get("value", []):
            props  = e.get("properties", {})
            linked = props.get("linkedEnvironmentMetadata") or {}
            out.append({
                "environment_id": e.get("name", ""),
                "display_name":   props.get("displayName", ""),
                "type":           props.get("environmentSku", ""),
                "region":         e.get("location", ""),
                "state":          (props.get("states", {}).get("runtime", {}) or {}).get("id", ""),
                "created_at":     props.get("createdTime", ""),
                "modified_at":    props.get("modifiedTime", ""),
                "sku":            props.get("environmentSku", ""),
                "dataverse_url":  linked.get("instanceUrl", "").rstrip("/"),
            })
        return out

    # ------------------------------------------------------------------
    # DLP Policies
    # ------------------------------------------------------------------

    def fetch_dlp_policies(self) -> list[dict]:
        """
        Tenant-level DLP connector policies.
        Tries the newer PP governance API first; falls back to BAP Admin API.
        """
        try:
            resp = requests.get(
                f"{_PP_API_BASE}/governance/connectorPolicies",
                headers=self._pp_headers(),
                params={"api-version": "2022-03-01-preview"},
                timeout=30,
            )
            resp.raise_for_status()
            return [_map_policy(p) for p in resp.json().get("value", [])]
        except Exception:
            pass

        resp = requests.get(
            f"{_BAP_BASE}/providers/Microsoft.BusinessAppPlatform/scopes/admin/apiPolicies",
            headers=self._bap_headers(),
            params={"api-version": "2021-04-01"},
            timeout=30,
        )
        resp.raise_for_status()
        return [_map_policy(p) for p in resp.json().get("value", [])]

    # ------------------------------------------------------------------
    # Agent Inventory (PP Inventory API)
    # ------------------------------------------------------------------

    def fetch_inventory_agents(self) -> list[dict]:
        """
        All Copilot Studio V2 agents across the tenant via the Inventory API.
        Bypasses the PPAC display cap; returns richer metadata (createdBy, ownerId,
        createdIn) than the per-environment Dataverse bot API.
        Classic PVA V1 agents are NOT included here.
        """
        headers = self._pp_headers()
        field_list = [
            "agentId = name",
            "displayName = tostring(properties.displayName)",
            "environmentId = tostring(properties.environmentId)",
            "createdAt = tostring(properties.createdAt)",
            "createdBy = tostring(properties.createdBy)",
            "ownerId = tostring(properties.ownerId)",
            "lastPublishedAt = tostring(properties.lastPublishedAt)",
            "createdIn = tostring(properties.createdIn)",
            "schemaName = tostring(properties.schemaName)",
        ]
        rows, seen, skip_token, prev_token = [], set(), "", None
        while True:
            options: dict = {"Top": _INVENTORY_PAGE}
            if skip_token:
                options["SkipToken"] = skip_token
            body = {
                "TableName": "PowerPlatformResources",
                "Clauses": [
                    {"$type": "where", "FieldName": "type",
                     "Operator": "==", "Values": ["'microsoft.copilotstudio/agents'"]},
                    {"$type": "project", "FieldList": field_list},
                ],
                "Options": options,
            }
            resp = requests.post(_INVENTORY_API, headers=headers, json=body, timeout=120)
            resp.raise_for_status()
            data = resp.json()
            new = 0
            for r in data.get("data", []):
                key = r.get("agentId")
                if key not in seen:
                    seen.add(key)
                    rows.append({
                        "id":              r.get("agentId", ""),
                        "name":            r.get("displayName", ""),
                        "schemaName":      r.get("schemaName", ""),
                        "environmentId":   r.get("environmentId", ""),
                        "createdDateTime": r.get("createdAt", ""),
                        "modifiedDateTime": "",
                        "publishedDateTime": r.get("lastPublishedAt", ""),
                        "createdBy":       r.get("createdBy", ""),
                        "ownerId":         r.get("ownerId", ""),
                        "createdIn":       r.get("createdIn", ""),
                    })
                    new += 1
            skip_token = data.get("skipToken") or ""
            if not skip_token or new == 0 or skip_token == prev_token:
                break
            total = data.get("totalRecords")
            if total is not None and len(rows) >= total:
                break
            prev_token = skip_token
        return rows


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _connector_names(groups: list, classification: str) -> str:
    for g in groups:
        if g.get("classification") == classification:
            return ", ".join(
                c.get("name", c.get("id", "")) for c in g.get("connectors", [])
            )
    return ""


def _map_policy(p: dict) -> dict:
    props  = p.get("properties", {})
    groups = props.get("connectorGroups", [])
    return {
        "policy_id":             p.get("name", ""),
        "display_name":          props.get("displayName", ""),
        "environment_type":      props.get("environmentType", ""),
        "created_by":            (props.get("createdBy", {}) or {}).get("displayName", ""),
        "created_at":            props.get("createdTime", ""),
        "modified_at":           props.get("lastModifiedTime", ""),
        "enforcement_mode":      props.get("etag", ""),
        "blocked_connectors":    _connector_names(groups, "Blocked"),
        "business_connectors":   _connector_names(groups, "Confidential") or _connector_names(groups, "Business"),
        "non_business_connectors": _connector_names(groups, "General") or _connector_names(groups, "NonBusiness"),
    }
