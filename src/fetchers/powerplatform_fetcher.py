import requests
from azure.identity import ClientSecretCredential

_PP_API_BASE = "https://api.powerplatform.com"
_PP_SCOPE = "https://api.powerplatform.com/.default"


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

    # ------------------------------------------------------------------
    # Bots (Dataverse)
    # ------------------------------------------------------------------

    def fetch_bots(self) -> list[dict]:
        """Return all Copilot Studio bots from Dataverse."""
        url = f"{self._dataverse_url}/api/data/v9.2/bots"
        resp = requests.get(
            url,
            headers=self._headers(),
            params={"$select": "botid,name,schemaname,createdon,modifiedon,publishedon"},
            timeout=30,
        )
        resp.raise_for_status()
        return [
            {
                "id": b.get("botid", ""),
                "name": b.get("name", ""),
                "schemaName": b.get("schemaname", ""),
                "environmentId": self._environment_id,
                "createdDateTime": b.get("createdon", ""),
                "modifiedDateTime": b.get("modifiedon", ""),
                "publishedDateTime": b.get("publishedon", ""),
            }
            for b in resp.json().get("value", [])
        ]

    # ------------------------------------------------------------------
    # Environments (Power Platform Admin API)
    # ------------------------------------------------------------------

    def fetch_environments(self) -> list[dict]:
        """Return Power Platform environments. Falls back to config-derived record if API unavailable."""
        try:
            url = f"{_PP_API_BASE}/appmanagement/environments"
            resp = requests.get(
                url,
                headers=self._pp_headers(),
                params={"api-version": "2022-03-01-preview"},
                timeout=30,
            )
            resp.raise_for_status()
            out = []
            for e in resp.json().get("value", []):
                props = e.get("properties", {})
                linked = props.get("linkedEnvironmentMetadata", {}) or {}
                out.append({
                    "environment_id": e.get("name", ""),
                    "display_name": props.get("displayName", ""),
                    "type": props.get("environmentSku", ""),
                    "region": e.get("location", ""),
                    "state": (props.get("states", {}).get("runtime", {}) or {}).get("id", ""),
                    "created_at": props.get("createdTime", ""),
                    "modified_at": props.get("modifiedTime", ""),
                    "sku": props.get("environmentSku", ""),
                    "dataverse_url": linked.get("instanceUrl", ""),
                })
            return out
        except Exception:
            pass

        # Fallback: construct from known config values
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
    # DLP Policies (Power Platform Admin API)
    # ------------------------------------------------------------------

    def fetch_dlp_policies(self) -> list[dict]:
        """Return tenant-level DLP policies. Requires Power Platform Admin role on the SP."""
        url = f"{_PP_API_BASE}/powerapps/tenants/{self._tenant_id}/apiPolicies"
        resp = requests.get(
            url,
            headers=self._pp_headers(),
            params={"api-version": "2016-11-01-preview"},
            timeout=30,
        )
        resp.raise_for_status()
        out = []
        for p in resp.json().get("value", []):
            props = p.get("properties", {})
            connector_groups = props.get("connectorGroups", [])
            blocked = _connector_names(connector_groups, "Blocked")
            business = _connector_names(connector_groups, "Business")
            non_business = _connector_names(connector_groups, "NonBusiness")
            out.append({
                "policy_id": p.get("name", ""),
                "display_name": props.get("displayName", ""),
                "environment_type": props.get("environmentType", ""),
                "created_by": (props.get("createdBy", {}) or {}).get("displayName", ""),
                "created_at": props.get("createdTime", ""),
                "modified_at": props.get("lastModifiedTime", ""),
                "enforcement_mode": props.get("etag", ""),
                "blocked_connectors": blocked,
                "business_connectors": business,
                "non_business_connectors": non_business,
            })
        return out


def _connector_names(groups: list, classification: str) -> str:
    for g in groups:
        if g.get("classification") == classification:
            return ", ".join(
                c.get("name", c.get("id", "")) for c in g.get("connectors", [])
            )
    return ""
