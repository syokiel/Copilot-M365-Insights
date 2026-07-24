"""
Usage Agent ID Override importer.

Reads a static CSV that force-maps an m365_usage_agents.agent_name to its
Copilot Studio bot GUID (agent_id in dim_agent / tokenomics_entitlement_per_agent).

Needed because m365_usage_agents.agent_id (from the M365 Admin usage report)
is a different ID scheme than the Copilot Studio bot GUID, so the two can
only be bridged by name — and auto-resolution (SqliteStore._resolve_usage_agent_ids)
skips any agent_name that maps to more than one bot_id in
m365_admin_agent_inventory (common when the same agent name is cloned across
dev/test/prod environments). Use store.fetch_m365_usage_agents_unresolved()
to find which names need an entry here.

CSV format (imports/usage_agent_id_overrides.csv):
  agent_name, bot_id
"""
import csv
from pathlib import Path


def _read(path: str) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    with open(p, newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


class UsageAgentOverrideImporter:
    """Reads the static agent_name -> bot_id override CSV."""

    def __init__(self, map_path: str = "") -> None:
        self._path = map_path

    def fetch_overrides(self) -> list[dict]:
        out = []
        for r in _read(self._path):
            agent_name = r.get("agent_name", "").strip()
            bot_id     = r.get("bot_id", "").strip()
            if not agent_name or not bot_id:
                continue
            out.append({"agent_name": agent_name, "bot_id": bot_id})
        return out
