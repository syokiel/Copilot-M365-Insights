"""
Microsoft Purview fetcher — data catalog assets, sensitivity labels, data policies.

Auth scope: https://purview.azure.net/.default
Required role: Purview Data Reader (catalog) / Purview Policy Author (policies)

Set PURVIEW_ACCOUNT_NAME (or PURVIEW_ENDPOINT) in your .env to enable.
"""
import requests
from azure.core.credentials import TokenCredential

_PURVIEW_SCOPE = "https://purview.azure.net/.default"


class PurviewFetcher:
    def __init__(
        self,
        credential: TokenCredential,
        account_name: str,
        endpoint: str = "",
    ) -> None:
        self._credential = credential
        base = endpoint.rstrip("/") if endpoint else f"https://{account_name}.purview.azure.com"
        self._catalog_base = f"{base}/catalog/api"
        self._account_base = f"{base}/account/api"

    def _headers(self) -> dict:
        token = self._credential.get_token(_PURVIEW_SCOPE).token
        return {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    # ------------------------------------------------------------------
    # Catalog search
    # ------------------------------------------------------------------

    def fetch_assets(self, keywords: str = "*", limit: int = 1000) -> list[dict]:
        """Search the Purview data catalog — returns raw asset value list."""
        resp = requests.post(
            f"{self._catalog_base}/search/query",
            headers={**self._headers(), "Content-Type": "application/json"},
            json={"keywords": keywords, "limit": limit},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json().get("value", [])

    def fetch_asset_by_guid(self, guid: str) -> dict:
        """Fetch a single catalog asset by its GUID."""
        resp = requests.get(
            f"{self._catalog_base}/atlas/v2/entity/guid/{guid}",
            headers=self._headers(),
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Sensitivity labels
    # ------------------------------------------------------------------

    def fetch_sensitivity_labels(self) -> list[dict]:
        """
        Fetch sensitivity labels configured in this Purview account.
        Requires Microsoft.Purview/accounts/read + Information Protection permissions.
        Stubbed — returns [] until scope is confirmed.
        """
        # TODO: implement via Purview Information Protection API
        return []

    # ------------------------------------------------------------------
    # Data access policies
    # ------------------------------------------------------------------

    def fetch_data_policies(self) -> list[dict]:
        """
        Fetch Purview data access policies.
        Requires Purview Policy Author role.
        Stubbed — returns [] until scope is confirmed.
        """
        # TODO: implement via GET {_account_base}/metadataPolicies/getAllMetadataPolicies
        return []
