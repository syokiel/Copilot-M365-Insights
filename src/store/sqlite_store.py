"""SQLite store for the telemetry pipeline.

SqliteStore is assembled from per-domain mixins — one module per data area —
so each area's tables, upserts and fetches live together:

  _schema.py     base DDL, compatibility views and shared column constants
  _base.py       connection lifecycle, migrations, shared helpers
  telemetry.py   OTel events / connector calls / model calls, Azure Monitor, PP bot analytics
  agents.py      dim_agent, environments, publishers, DLP, solutions, Entra users, XLA mapping
  m365_admin.py  M365 Admin Center agent inventory / usage, Cowork, Copilot Chat, connectors
  m365_usage.py  Copilot / Teams / O365 / Apps usage (Graph + CSV) and billing
  viva.py        Viva Insights API, Copilot Studio analytics, Adoption/Impact, Consumption
  tokenomics.py  Copilot Studio credit consumption
  kpi.py         KPI snapshots
"""
from src.store._base import StoreBase
from src.store.telemetry import TelemetryMixin
from src.store.agents import AgentsMixin
from src.store.m365_admin import M365AdminMixin
from src.store.m365_usage import M365UsageMixin
from src.store.viva import VivaMixin
from src.store.tokenomics import TokenomicsMixin
from src.store.kpi import KpiMixin


class SqliteStore(
    TelemetryMixin,
    AgentsMixin,
    M365AdminMixin,
    M365UsageMixin,
    VivaMixin,
    TokenomicsMixin,
    KpiMixin,
    StoreBase,
):
    pass
