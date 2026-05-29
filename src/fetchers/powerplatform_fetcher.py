import requests
from azure.identity import ClientSecretCredential

_PP_API_BASE = "https://api.powerplatform.com"
_PP_SCOPE = "https://api.powerplatform.com/.default"

# BAP endpoint — used by configure_agent_telemetry.py; returns all tenant environments
_BAP_BASE = "https://api.bap.microsoft.com"
_BAP_SCOPE = "https://api.bap.microsoft.com/.default"

# Dynamics 365 Global Discovery — returns Dataverse orgs the SP has been granted access to
_DISCO_BASE = "https://globaldisco.crm.dynamics.com"
_DISCO_SCOPE = "https://globaldisco.crm.dynamics.com/.default"


class PowerPlatformFetcher:
    def __init__(
        self,
        tenant_id: str,
        client_id: str,
        client_secret: str,
        dataverse_url: str,
        environment_id: str = "",
    ) -> None:
        self._tenant_id = tenant_id
        self._dataverse_url = dataverse_url.rstrip("/")
        self._environment_id = environment_id
        self._credential = ClientSecretCredential(tenant_id, client_id, client_secret)
        self._dv_scope = f"{self._dataverse_url}/.default"

    def _headers(self) -> dict:
        """Dataverse Web API headers."""
        token = self._credential.get_token(self._dv_scope).token
        return {
            "Authorization": f"Bearer {token}",
            "OData-MaxVersion": "4.0",
            "OData-Version": "4.0",
            "Accept": "application/json",
        }

    def _pp_headers(self) -> dict:
        """Power Platform Admin API headers."""
        token = self._credential.get_token(_PP_SCOPE).token
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _bap_headers(self) -> dict:
        token = self._credential.get_token(_BAP_SCOPE).token
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    def _disco_headers(self) -> dict:
        token = self._credential.get_token(_DISCO_SCOPE).token
        return {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    # ------------------------------------------------------------------
    # Bots (Dataverse) — single env or all environments
    # ------------------------------------------------------------------

    def fetch_bots_from(self, dataverse_url: str, environment_id: str) -> list[dict]:
        """Fetch bots from a specific Dataverse org URL."""
        dv_url = dataverse_url.rstrip("/")
        scope = f"{dv_url}/.default"
        token = self._credential.get_token(scope).token
        headers = {
            "Authorization": f"Bearer {token}",
            "OData-MaxVersion": "4.0",
            "OData-Version": "4.0",
            "Accept": "application/json",
        }
        resp = requests.get(
            f"{dv_url}/api/data/v9.2/bots",
            headers=headers,
            params={"$select": "botid,name,schemaname,createdon,modifiedon,publishedon"},
            timeout=30,
        )
        resp.raise_for_status()
        return [
            {
                "id": b.get("botid", ""),
                "name": b.get("name", ""),
                "schemaName": b.get("schemaname", ""),
                "environmentId": environment_id,
                "createdDateTime": b.get("createdon", ""),
                "modifiedDateTime": b.get("modifiedon", ""),
                "publishedDateTime": b.get("publishedon", ""),
            }
            for b in resp.json().get("value", [])
        ]

    def fetch_bots(self) -> list[dict]:
        """Fetch bots from the configured Dataverse URL (single-environment convenience wrapper)."""
        return self.fetch_bots_from(self._dataverse_url, self._environment_id)

    # ------------------------------------------------------------------
    # Environments (Power Platform Admin API)
    # ------------------------------------------------------------------

    def fetch_environments(self) -> list[dict]:
        """
        Return ALL Power Platform environments in the tenant.

        Discovery order (first success wins):
          1. BAP Admin API  — full tenant view; requires Power Platform Administrator role
          2. Global Discovery — Dataverse orgs the SP has been explicitly granted access to
          3. Config fallback  — the single env in DATAVERSE_URL / POWERPLATFORM_ENVIRONMENT_ID
        """
        # ── 1. BAP Admin API (full tenant) ──────────────────────────────────────
        try:
            resp = requests.get(
                f"{_BAP_BASE}/providers/Microsoft.BusinessAppPlatform/scopes/admin/environments",
                headers=self._bap_headers(),
                params={"api-version": "2021-04-01"},
                timeout=30,
            )
            resp.raise_for_status()
            out = []
            for e in resp.json().get("value", []):
                props = e.get("properties", {})
                linked = props.get("linkedEnvironmentMetadata") or {}
                out.append({
                    "environment_id": e.get("name", ""),
                    "display_name": props.get("displayName", ""),
                    "type": props.get("environmentSku", ""),
                    "region": e.get("location", ""),
                    "state": (props.get("states", {}).get("runtime", {}) or {}).get("id", ""),
                    "created_at": props.get("createdTime", ""),
                    "modified_at": props.get("modifiedTime", ""),
                    "sku": props.get("environmentSku", ""),
                    "dataverse_url": linked.get("instanceUrl", "").rstrip("/"),
                })
            if out:
                return out
        except Exception:
            pass

        # ── 2. Global Discovery (orgs the SP has Dataverse access to) ───────────
        try:
            resp = requests.get(
                f"{_DISCO_BASE}/api/discovery/v2.0/Instances",
                headers=self._disco_headers(),
                timeout=30,
            )
            resp.raise_for_status()
            out = []
            for inst in resp.json().get("value", []):
                out.append({
                    "environment_id": inst.get("EnvironmentId", ""),
                    "display_name": inst.get("FriendlyName", ""),
                    "type": inst.get("EnvironmentSku", ""),
                    "region": inst.get("DatacenterRegion", ""),
                    "state": "Ready",
                    "created_at": "",
                    "modified_at": "",
                    "sku": inst.get("EnvironmentSku", ""),
                    "dataverse_url": inst.get("Url", "").rstrip("/"),
                })
            if out:
                return out
        except Exception:
            pass

        # ── 3. Config fallback (single env) ─────────────────────────────────────
        if self._environment_id:
            return [{
                "environment_id": self._environment_id,
                "display_name": "",
                "type": "",
                "region": "",
                "state": "Ready",
                "created_at": "",
                "modified_at": "",
                "sku": "",
                "dataverse_url": self._dataverse_url,
            }]
        return []

    # ------------------------------------------------------------------
    # Publishers (Dataverse)
    # ------------------------------------------------------------------

    def fetch_publishers(self) -> list[dict]:
        """Return solution publishers from Dataverse (excluding Microsoft built-ins)."""
        url = f"{self._dataverse_url}/api/data/v9.2/publishers"
        resp = requests.get(
            url,
            headers=self._headers(),
            params={
                "$select": "publisherid,friendlyname,uniquename,emailaddress,customizationprefix",
                "$filter": "isreadonly eq false",
                "$orderby": "friendlyname asc",
            },
            timeout=30,
        )
        resp.raise_for_status()
        return [
            {
                "publisher_id": p.get("publisherid", ""),
                "display_name": p.get("friendlyname", ""),
                "unique_name": p.get("uniquename", ""),
                "email": p.get("emailaddress", "") or "",
                "phone": "",
                "custom_prefix": p.get("customizationprefix", ""),
                "solution_count": None,
            }
            for p in resp.json().get("value", [])
        ]

    # ------------------------------------------------------------------
    # Solutions (Dataverse)
    # ------------------------------------------------------------------

    def fetch_bot_solutions_from(self, dataverse_url: str) -> list[dict]:
        """
        Return solution membership for bots in a specific Dataverse org.
        componenttype 380 = Chatbot in Power Platform.
        Returns empty list if the component type doesn't exist or access is denied.
        """
        dv_url = dataverse_url.rstrip("/")
        scope = f"{dv_url}/.default"
        token = self._credential.get_token(scope).token
        headers = {
            "Authorization": f"Bearer {token}",
            "OData-MaxVersion": "4.0",
            "OData-Version": "4.0",
            "Accept": "application/json",
        }
        try:
            resp = requests.get(
                f"{dv_url}/api/data/v9.2/solutioncomponents",
                headers=headers,
                params={
                    "$filter": "componenttype eq 380",
                    "$select": "objectid,_solutionid_value",
                    "$expand": "solutionid($select=uniquename,friendlyname,version,ismanaged)",
                },
                timeout=30,
            )
            resp.raise_for_status()
            out = []
            for sc in resp.json().get("value", []):
                sol = sc.get("solutionid") or {}
                out.append({
                    "bot_id": sc.get("objectid", ""),
                    "solution_id": sc.get("_solutionid_value", ""),
                    "solution_name": sol.get("friendlyname", ""),
                    "solution_unique": sol.get("uniquename", ""),
                    "version": sol.get("version", ""),
                    "is_managed": sol.get("ismanaged", False),
                })
            return out
        except Exception:
            return []

    def fetch_bot_solutions(self) -> list[dict]:
        """Fetch bot solutions from the configured Dataverse URL (single-environment wrapper)."""
        return self.fetch_bot_solutions_from(self._dataverse_url)

    # ------------------------------------------------------------------
    # DLP Policies (Power Platform Admin API)
    # ------------------------------------------------------------------

    def fetch_dlp_policies(self) -> list[dict]:
        """Return tenant-level DLP policies."""
        # Try the newer Power Platform API first — better app-only SP support
        try:
            resp = requests.get(
                f"{_PP_API_BASE}/governance/connectorPolicies",
                headers=self._pp_headers(),
                params={"api-version": "2022-03-01-preview"},
                timeout=30,
            )
            resp.raise_for_status()
            out = []
            for p in resp.json().get("value", []):
                props = p.get("properties", {})
                groups = props.get("connectorGroups", [])
                # Newer API uses Confidential/General; older used Business/NonBusiness
                out.append({
                    "policy_id": p.get("name", ""),
                    "display_name": props.get("displayName", ""),
                    "environment_type": props.get("environmentType", ""),
                    "created_by": (props.get("createdBy", {}) or {}).get("displayName", ""),
                    "created_at": props.get("createdTime", ""),
                    "modified_at": props.get("lastModifiedTime", ""),
                    "enforcement_mode": props.get("etag", ""),
                    "blocked_connectors": _connector_names(groups, "Blocked"),
                    "business_connectors": _connector_names(groups, "Confidential") or _connector_names(groups, "Business"),
                    "non_business_connectors": _connector_names(groups, "General") or _connector_names(groups, "NonBusiness"),
                })
            return out
        except Exception:
            pass

        # Fall back to BAP Admin API
        resp = requests.get(
            f"{_BAP_BASE}/providers/Microsoft.BusinessAppPlatform/scopes/admin/apiPolicies",
            headers=self._bap_headers(),
            params={"api-version": "2021-04-01"},
            timeout=30,
        )
        resp.raise_for_status()
        out = []
        for p in resp.json().get("value", []):
            props = p.get("properties", {})
            groups = props.get("connectorGroups", [])
            out.append({
                "policy_id": p.get("name", ""),
                "display_name": props.get("displayName", ""),
                "environment_type": props.get("environmentType", ""),
                "created_by": (props.get("createdBy", {}) or {}).get("displayName", ""),
                "created_at": props.get("createdTime", ""),
                "modified_at": props.get("lastModifiedTime", ""),
                "enforcement_mode": props.get("etag", ""),
                "blocked_connectors": _connector_names(groups, "Blocked"),
                "business_connectors": _connector_names(groups, "Business"),
                "non_business_connectors": _connector_names(groups, "NonBusiness"),
            })
        return out


def _connector_names(groups: list, classification: str) -> str:
    for g in groups:
        if g.get("classification") == classification:
            return ", ".join(
                c.get("name", c.get("id", "")) for c in g.get("connectors", [])
            )
    return ""
