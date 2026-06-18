"""
M365 Admin Center CSV report importer.

Reads the standard export files from the M365 Admin Center and converts
them to lists of dicts for the SQLite store.

Supported files (passed as direct file paths via config env vars):
  M365Admin.Agents.AllAgents.Registry.Agents_*.csv          → m365_admin_agent_inventory
  M365Admin.Reporting.Usage.Agents.Agents.*_Agents_*.csv    → m365_usage_agents
  M365Admin.Reporting.Usage.Agents.UsersAndAgents.*csv      → m365_usage_agent_users
  DeclarativeAgents_Users_30_*.csv                          → m365_usage_users
"""
import csv
import re
from pathlib import Path


_MONTHS = {'jan':'01','feb':'02','mar':'03','apr':'04','may':'05','jun':'06',
           'jul':'07','aug':'08','sep':'09','oct':'10','nov':'11','dec':'12'}

def _norm_date(v: str) -> str:
    if not v or not v.strip():
        return ''
    v = v.strip().strip('"')
    if re.match(r'^\d{4}-\d{2}-\d{2}', v):
        return v[:10]
    # "Jun 12, 2026" or "Jun 12 2026"
    m = re.match(r'^([A-Za-z]{3})\s+(\d{1,2}),?\s+(\d{4})$', v)
    if m:
        mon_str, day, yr = m.groups()
        mon = _MONTHS.get(mon_str.lower(), '01')
        return f"{yr}-{mon}-{day.zfill(2)}"
    # "12-Jun-26" or "12-Jun-2026"
    m = re.match(r'^(\d{1,2})-([A-Za-z]{3})-(\d{2,4})$', v)
    if m:
        day, mon_str, yr = m.groups()
        mon = _MONTHS.get(mon_str.lower(), '01')
        if len(yr) == 2:
            yr = '20' + yr
        return f"{yr}-{mon}-{day.zfill(2)}"
    # MM/DD/YY or MM/DD/YYYY
    m = re.match(r'^(\d{1,2})/(\d{1,2})/(\d{2,4})$', v)
    if m:
        mo, day, yr = m.groups()
        if len(yr) == 2:
            yr = '20' + yr
        return f"{yr}-{mo.zfill(2)}-{day.zfill(2)}"
    return v


def _int(v) -> int | None:
    try:
        s = str(v).strip()
        return int(s) if s else None
    except (ValueError, TypeError):
        return None


def _bool(v) -> int:
    return 1 if str(v).strip().upper() in ('YES', 'TRUE', '1') else 0


def _read(path: str) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    with open(p, newline='', encoding='utf-8-sig') as fh:
        return list(csv.DictReader(fh))


class M365AdminReportImporter:
    """Reads M365 Admin Center CSV exports from direct file paths."""

    def __init__(
        self,
        inventory_path: str = "",
        agents_path: str = "",
        agent_users_path: str = "",
        users_path: str = "",
    ) -> None:
        self._inventory_path   = inventory_path
        self._agents_path      = agents_path
        self._agent_users_path = agent_users_path
        self._users_path       = users_path

    def fetch_agent_inventory(self) -> list[dict]:
        out = []
        for r in _read(self._inventory_path):
            out.append({
                'title_id':                r.get('Title ID', ''),
                'name':                    r.get('Name', ''),
                'status':                  r.get('Status', ''),
                'channel':                 r.get('Channel', ''),
                'date_created':            _norm_date(r.get('Date created', '')),
                'last_modified':           _norm_date(r.get('Last Modified', '')),
                'publisher':               r.get('Publisher', ''),
                'publisher_type':          r.get('Publisher Type', ''),
                'version':                 r.get('Version', ''),
                'owner':                   r.get('Owner', ''),
                'description':             r.get('Description', ''),
                'platform':                r.get('Platform', ''),
                'creator_id':              r.get('Creator Id', ''),
                'environment_id':          r.get('Environment Id', ''),
                'bot_id':                  r.get('Bot Id', ''),
                'custom_actions':          _int(r.get('Custom actions')),
                'custom_action_list':      r.get('Custom action list', ''),
                'sensitivity':             r.get('Sensitivity', ''),
                'can_read_od_sp':          _bool(r.get('Can read OneDrive and Sharepoint items', '')),
                'od_sp_items':             r.get('OneDrive and Sharepoint items', ''),
                'can_read_od_files':       _bool(r.get('Can read OneDrive files', '')),
                'od_files':                r.get('OneDrive files', ''),
                'od_sites':                r.get('OneDrive sites', ''),
                'can_read_sp_sites':       _bool(r.get('Can read Sharepoint sites and files', '')),
                'sp_files':                r.get('Sharepoint files', ''),
                'sp_sites':                r.get('Sharepoint sites', ''),
                'can_extend_graph':        _bool(r.get('Can extend to Graph connector', '')),
                'graph_connector_details': r.get('Graph connector details', ''),
                'can_generate_images':     _bool(r.get('Can generate images using user prompt', '')),
                'can_use_code_interpreter': _bool(r.get('Can use code interpreter', '')),
                'contains_uploaded_files': _bool(r.get('Contains uploaded files', '')),
                'uploaded_files':          r.get('Uploaded files', ''),
                'instructions':            r.get('Instructions', ''),
                'groups_shared':           r.get('Groups shared', ''),
                'users_shared':            r.get('Users shared', ''),
            })
        return out

    def fetch_usage_agents(self) -> list[dict]:
        out = []
        for r in _read(self._agents_path):
            out.append({
                'agent_id':               r.get('Agent ID', ''),
                'agent_name':             r.get('Agent name', ''),
                'creator_type':           r.get('Creator type', ''),
                'active_users_licensed':  _int(r.get('Active users (licensed)')),
                'active_users_unlicensed': _int(r.get('Active users (unlicensed)')),
                'responses_sent':         _int(r.get('Responses sent to users')),
                'last_activity_date':     _norm_date(r.get('Last activity date (UTC)', '')),
            })
        return out

    def fetch_usage_agent_users(self) -> list[dict]:
        out = []
        for r in _read(self._agent_users_path):
            out.append({
                'agent_id':           r.get('Agent ID', ''),
                'username':           r.get('Username', ''),
                'agent_name':         r.get('Agent name', ''),
                'creator_type':       r.get('Creator type', ''),
                'responses_sent':     _int(r.get('Responses sent to users')),
                'last_activity_date': _norm_date(r.get('Last activity date (UTC)', '')),
            })
        return out

    def fetch_usage_users(self) -> list[dict]:
        """Per-user rollup: how many agents each user interacted with and total responses."""
        out = []
        for r in _read(self._users_path):
            out.append({
                'username':                 r.get('Username', ''),
                'display_name':             r.get('Display name', ''),
                'agents_used':              _int(r.get('Number of agents used')),
                'agent_responses_received': _int(r.get('Agent responses received')),
                'last_activity_date':       _norm_date(r.get('Last activity date (UTC)', '')),
            })
        return out
