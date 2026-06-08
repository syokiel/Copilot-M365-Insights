"""
Dataverse Web API fetcher — agents (bots), publishers, agent-solution membership.

Each method that accepts a dataverse_url parameter can target any Dataverse org
(cross-environment iteration), while methods without a parameter default to the
URL supplied at construction time.
"""
import json

import requests
from azure.core.credentials import TokenCredential


def _parse_ai_model(configuration: str) -> str:
    """
    Extract the AI model name from a Copilot Studio bot configuration JSON blob.

    Copilot Studio serialises AI model settings differently across versions, so
    we walk several known key paths and return the first non-empty string found.
    """
    if not configuration:
        return ""
    try:
        cfg = json.loads(configuration)
    except (json.JSONDecodeError, TypeError):
        return ""
    candidates = [
        cfg.get("DefaultAIModel"),
        (cfg.get("generativeAI") or {}).get("modelId"),
        (cfg.get("AICopilotConfig") or {}).get("ModelId"),
        (cfg.get("AICopilotConfig") or {}).get("modelId"),
        cfg.get("aiModel"),
        cfg.get("ModelId"),
        cfg.get("modelId"),
        cfg.get("model"),
        cfg.get("AIType"),
    ]
    for val in candidates:
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


class DataverseFetcher:
    def __init__(self, credential: TokenCredential, dataverse_url: str) -> None:
        self._credential = credential
        self._base = dataverse_url.rstrip("/")

    def _headers(self, url: str | None = None) -> dict:
        base  = (url or self._base).rstrip("/")
        scope = f"{base}/.default"
        token = self._credential.get_token(scope).token
        return {
            "Authorization":   f"Bearer {token}",
            "OData-MaxVersion": "4.0",
            "OData-Version":    "4.0",
            "Accept":           "application/json",
        }

    # ------------------------------------------------------------------
    # Agents
    # ------------------------------------------------------------------

    def fetch_agents(self, dataverse_url: str, environment_id: str) -> list[dict]:
        """Fetch agents (bots) from a specific Dataverse org."""
        url = dataverse_url.rstrip("/")
        resp = requests.get(
            f"{url}/api/data/v9.2/bots",
            headers=self._headers(url),
            params={"$select": "botid,name,schemaname,createdon,modifiedon,publishedon,configuration"},
            timeout=30,
        )
        resp.raise_for_status()
        return [
            {
                "id":              b.get("botid", ""),
                "name":            b.get("name", ""),
                "schemaName":      b.get("schemaname", ""),
                "environmentId":   environment_id,
                "createdDateTime": b.get("createdon", ""),
                "modifiedDateTime": b.get("modifiedon", ""),
                "publishedDateTime": b.get("publishedon", ""),
                "aiModel":         _parse_ai_model(b.get("configuration") or ""),
            }
            for b in resp.json().get("value", [])
        ]

    # ------------------------------------------------------------------
    # Publishers
    # ------------------------------------------------------------------

    def fetch_publishers(self, dataverse_url: str | None = None) -> list[dict]:
        """Solution publishers from a Dataverse org (excludes Microsoft built-ins)."""
        url = (dataverse_url or self._base).rstrip("/")
        resp = requests.get(
            f"{url}/api/data/v9.2/publishers",
            headers=self._headers(url),
            params={
                "$select":  "publisherid,friendlyname,uniquename,emailaddress,customizationprefix",
                "$filter":  "isreadonly eq false",
                "$orderby": "friendlyname asc",
            },
            timeout=30,
        )
        resp.raise_for_status()
        return [
            {
                "publisher_id": p.get("publisherid", ""),
                "display_name": p.get("friendlyname", ""),
                "unique_name":  p.get("uniquename", ""),
                "email":        p.get("emailaddress", "") or "",
                "phone":        "",
                "custom_prefix": p.get("customizationprefix", ""),
                "solution_count": None,
            }
            for p in resp.json().get("value", [])
        ]

    # ------------------------------------------------------------------
    # Agent-solution membership
    # ------------------------------------------------------------------

    def fetch_agent_solutions(self, dataverse_url: str) -> list[dict]:
        """
        Agent→solution membership for a Dataverse org.
        componenttype 380 = Chatbot in Power Platform.
        Returns [] if the component type doesn't exist or access is denied.
        """
        url = dataverse_url.rstrip("/")
        try:
            resp = requests.get(
                f"{url}/api/data/v9.2/solutioncomponents",
                headers=self._headers(url),
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
                    "agent_id":       sc.get("objectid", ""),
                    "solution_id":    sc.get("_solutionid_value", ""),
                    "solution_name":  sol.get("friendlyname", ""),
                    "solution_unique": sol.get("uniquename", ""),
                    "version":        sol.get("version", ""),
                    "is_managed":     sol.get("ismanaged", False),
                })
            return out
        except Exception:
            return []
