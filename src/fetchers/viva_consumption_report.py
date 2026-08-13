"""
Viva Insights — Copilot Consumption Dashboard CSV importer.

Reads the "Consumption" export folder from Viva Insights and converts it to
lists of dicts for the SQLite store. Feeds/enhances the Tokenomics_* sheets
with per-person, per-service credit consumption.

Supported files (resolved case-insensitively from the given directory, same
flat/nested/rglob resolution as VivaReportImporter):
  PeopleMetaData.csv               → viva_consumption_people
  PersonServiceCreditsMetrics.csv  → viva_consumption_person_service_credits
  SpendingPolicyMetadata.csv       → viva_consumption_spending_policy
"""
import csv
import re
from pathlib import Path


def _norm_date(v: str) -> str:
    if not v or not v.strip():
        return ''
    v = v.strip().strip('"')
    if re.match(r'^\d{4}-\d{2}-\d{2}', v):
        return v[:10]
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


def _float(v) -> float | None:
    try:
        s = str(v).strip()
        return float(s) if s else None
    except (ValueError, TypeError):
        return None


def _bool(v) -> int:
    return 1 if str(v).strip().lower() in ('true', 'yes', '1') else 0


class VivaConsumptionImporter:
    """Reads Viva Insights Consumption CSV exports from a directory on disk."""

    _FILES = {
        'people':                'PeopleMetaData.csv',
        'person_service_credits': 'PersonServiceCreditsMetrics.csv',
        'spending_policy':       'SpendingPolicyMetadata.csv',
    }

    def __init__(self, report_dir: str) -> None:
        self._dir = Path(report_dir)

    def _read(self, key: str) -> list[dict]:
        filename = self._FILES[key]
        stem = Path(filename).stem

        candidates = [
            self._dir / filename,          # flat:   dir/PeopleMetaData.csv
            self._dir / stem / filename,   # nested: dir/PeopleMetaData/PeopleMetaData.csv
        ]

        p = None
        for c in candidates:
            if c.exists():
                p = c
                break

        if p is None:
            for entry in self._dir.rglob('*'):
                if entry.is_file() and entry.name.lower() == filename.lower():
                    p = entry
                    break

        if p is None:
            return []

        with open(p, newline='', encoding='utf-8-sig') as fh:
            return list(csv.DictReader(fh))

    def fetch_people(self) -> list[dict]:
        out = []
        for r in self._read('people'):
            out.append({
                'people_historical_id': r.get('PeopleHistoricalId', ''),
                'organization':         r.get('Organization', ''),
                'function_type':        r.get('FunctionType', ''),
                'is_copilot_licensed':  _bool(r.get('IsCopilotLicensed', '')),
            })
        return out

    def fetch_person_service_credits(self) -> list[dict]:
        out = []
        for r in self._read('person_service_credits'):
            out.append({
                'person_id':             r.get('PersonId', ''),
                'service_id':            r.get('ServiceId', ''),
                'service_name':          r.get('ServiceName', ''),
                'spending_policy_id':    r.get('SpendingPolicyId', ''),
                'metric_date':           _norm_date(r.get('MetricDate', '')),
                'session_count':         _int(r.get('Session count')),
                'spending_policy_limit': _float(r.get('Spending policy limit')),
                'total_credits_used':    _float(r.get('Total Copilot Credits used')),
                'user_limit':            _float(r.get('User limit')),
                'people_historical_id':  r.get('PeopleHistoricalId', ''),
            })
        return out

    def fetch_spending_policy(self) -> list[dict]:
        out = []
        for r in self._read('spending_policy'):
            out.append({
                'spending_policy_id': r.get('SpendingPolicyId', ''),
                'name':               r.get('Name', ''),
                'plan_limit':         _float(r.get('PlanLimit')),
                'user_limit':         _float(r.get('UserLimit')),
                'included_services':  r.get('IncludedServices', ''),
            })
        return out
