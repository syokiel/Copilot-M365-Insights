"""
Dynamics 365 Global Discovery fetcher.

Returns the Dataverse instances (organisations) that the credential has been
explicitly granted access to.  Used as a fallback when the Power Platform Admin
API is unavailable (e.g. the SP does not have the Power Platform Administrator
role but has been given Dataverse access to specific environments).

Endpoint: https://globaldisco.crm.dynamics.com/api/discovery/v2.0/Instances
"""
import requests
from azure.core.credentials import TokenCredential

_DISCO_BASE  = "https://globaldisco.crm.dynamics.com"
_DISCO_SCOPE = f"{_DISCO_BASE}/.default"


class GlobalDiscoveryFetcher:
    def __init__(self, credential: TokenCredential) -> None:
        self._credential = credential

    def _headers(self) -> dict:
        token = self._credential.get_token(_DISCO_SCOPE).token
        return {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    def fetch_instances(self) -> list[dict]:
        """
        Return Dataverse instances accessible to the credential.
        Each dict matches the pva_environments schema used by SqliteStore.
        """
        resp = requests.get(
            f"{_DISCO_BASE}/api/discovery/v2.0/Instances",
            headers=self._headers(),
            timeout=30,
        )
        resp.raise_for_status()
        out = []
        for inst in resp.json().get("value", []):
            out.append({
                "environment_id": inst.get("EnvironmentId", ""),
                "display_name":   inst.get("FriendlyName", ""),
                "type":           inst.get("EnvironmentSku", ""),
                "region":         inst.get("DatacenterRegion", ""),
                "state":          "Ready",
                "created_at":     "",
                "modified_at":    "",
                "sku":            inst.get("EnvironmentSku", ""),
                "dataverse_url":  inst.get("Url", "").rstrip("/"),
            })
        return out
