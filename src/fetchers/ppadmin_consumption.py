"""
Power Platform Admin — Copilot credit consumption CSV importer.

Reads the standard "Capacity Consumption" and "Entitlement Consumption"
tenant-detail exports from the Power Platform Admin Center and converts
them to lists of dicts for the SQLite store (Tokenomics_* tables).

Supported files (passed as direct file paths via config env vars):
  CapacityConsumptionTenantDetailsReport.csv                              → tokenomics_capacity_consumption
  EntitlementConsumptionTenantDetailsReport_MCSMessages_*.csv             → tokenomics_entitlement_consumption
  EntitlementConsumptionTenantPerAgentDetailsReport_MCSMessages_*.csv     → tokenomics_entitlement_per_agent
  EntitlementConsumptionTenantPerUserDetailsReport_MCSMessages_*.csv      → tokenomics_entitlement_per_user
"""
import csv
import re
from pathlib import Path


def _norm_date(v: str) -> str:
    if not v or not v.strip():
        return ''
    v = v.strip().strip('"')
    v = v.split(' ')[0]  # drop a trailing time component, e.g. "12:00:00 AM"
    if re.match(r'^\d{4}-\d{2}-\d{2}', v):
        return v[:10]
    m = re.match(r'^(\d{1,2})/(\d{1,2})/(\d{2,4})$', v)
    if m:
        mo, day, yr = m.groups()
        if len(yr) == 2:
            yr = '20' + yr
        return f"{yr}-{mo.zfill(2)}-{day.zfill(2)}"
    return v


def _float(v) -> float | None:
    try:
        s = str(v).strip()
        return float(s) if s else None
    except (ValueError, TypeError):
        return None


def _bool(v) -> int:
    return 1 if str(v).strip().lower() in ('true', 'yes', '1') else 0


def _read(path: str) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    with open(p, newline='', encoding='utf-8-sig') as fh:
        return list(csv.DictReader(fh))


class PPAdminConsumptionImporter:
    """Reads Power Platform Admin Center consumption CSV exports from direct file paths."""

    def __init__(
        self,
        capacity_path: str = "",
        entitlement_path: str = "",
        entitlement_per_agent_path: str = "",
        entitlement_per_user_path: str = "",
    ) -> None:
        self._capacity_path             = capacity_path
        self._entitlement_path          = entitlement_path
        self._entitlement_per_agent_path = entitlement_per_agent_path
        self._entitlement_per_user_path  = entitlement_per_user_path

    def fetch_capacity_consumption(self) -> list[dict]:
        out = []
        for r in _read(self._capacity_path):
            out.append({
                'tenant_id':        r.get('TenantId', ''),
                'environment_id':   r.get('EnvironmentId', ''),
                'environment_name': r.get('EnvironmentName', ''),
                'environment_type': r.get('EnvironmentType', ''),
                'resource_id':      r.get('ResourceId', ''),
                'resource_name':    r.get('ResourceName', ''),
                'resource_type':    r.get('ResourceType', ''),
                'product_name':     r.get('ProductName', ''),
                'feature_name':     r.get('FeatureName', ''),
                'channel_id':       r.get('ChannelId', ''),
                'is_billable':      _bool(r.get('isBillable', '')),
                'unit':             r.get('Unit', ''),
                'consumption_date': _norm_date(r.get('ConsumptionDate', '')),
                'consumed_quantity': _float(r.get('ConsumedQuantity')),
            })
        return out

    def fetch_entitlement_consumption(self) -> list[dict]:
        out = []
        for r in _read(self._entitlement_path):
            out.append({
                'billing_plan_id':           r.get('BillingPlan Id', ''),
                'billing_plan_name':         r.get('BillingPlan Name', ''),
                'environment_id':            r.get('Environment Id', ''),
                'environment_name':          r.get('Environment Name', ''),
                'capacity_type':             r.get('Capacity Type', ''),
                'entitled_quantity':         _float(r.get('Entitled Quantity')),
                'prepaid_consumed_quantity': _float(r.get('Prepaid Consumed Quantity')),
                'payg_consumed_quantity':    _float(r.get('Pay as you go Consumed Quantity')),
                'usage_date':                _norm_date(r.get('Usage Date', '')),
            })
        return out

    def fetch_entitlement_per_agent(self) -> list[dict]:
        """Per-agent credit breakdown from PerAgentDetails report."""
        out = []
        for r in _read(self._entitlement_per_agent_path):
            out.append({
                'agent_name':       r.get('Agent Name', ''),
                'agent_id':         r.get('Agent Id', ''),
                'product':          r.get('Product', ''),
                'ai_feature':       r.get('AI Feature/Billable Feature', ''),
                'billed_credit':    _float(r.get('Billed credit')),
                'non_billed_credit': _float(r.get('Non-billed credit')),
                'channel':          r.get('Channel', ''),
                'knowledge_sources': r.get('Knowledge Sources', ''),
                'tool_used':        r.get('Tool Used', ''),
                'llm_model':        r.get('LLM Model', ''),
                'scenario_name':    r.get('Scenario Name', ''),
                'environment_id':   r.get('Environment Id', ''),
                'environment_name': r.get('Environment Name', ''),
            })
        return out

    def fetch_entitlement_per_user(self) -> list[dict]:
        """Per-user credit breakdown from PerUserDetails report."""
        out = []
        for r in _read(self._entitlement_per_user_path):
            out.append({
                'user_id':              r.get('User Id', ''),
                'user_email':           r.get('User Email', ''),
                'agent_id':             r.get('Agent Id', ''),
                'agent_name':           r.get('Agent Name', ''),
                'billable_credit_used': _float(r.get('Billable credit used')),
                'credits_used':         _float(r.get('Credits used')),
                'm365_copilot_licensed': _bool(r.get('M365 Copilot Licensed', '')),
            })
        return out
