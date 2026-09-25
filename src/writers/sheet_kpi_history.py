"""KPI History — one row per data period (oldest first), plus trend charts.

Rows come from kpi_snapshots, which store each period's own values (see
src/store/kpi.py), so every column is genuinely historical. Columns with no
data in any period (e.g. OTel metrics for a CSV-only tenant) are omitted.
"""
from openpyxl.chart import LineChart, Reference
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from src.writers._style import LEFT

# (section label, light fill, dark fill, [(header, snapshot key, format)])
# format: "int" | "pct" (value stored 0–100) | "dec" | "text"
_SECTIONS = [
    ("", "F2F2F2", "595959", [
        ("Period", "period", "text"),
        ("Data To", "period_end", "text"),
    ]),
    ("M365 Copilot", "DEEAF1", "2E75B6", [
        ("Licenses", "total_licenses", "int"),
        ("Enabled Users", "enabled_users", "int"),
        ("Active Users", "active_users", "int"),
        ("Activation Rate", "activation_rate", "pct"),
        ("Adoption Rate", "adoption_rate", "pct"),
        ("Power Users", "power_users", "int"),
        ("Total Prompts", "total_prompts", "int"),
        ("Prompts / Active User", "avg_prompts_per_user", "dec"),
    ]),
    ("Prompts by Workload", "E2EFDA", "538135", [
        ("Copilot Chat", "prompts_copilot_chat", "int"),
        ("Teams", "prompts_teams", "int"),
        ("Outlook", "prompts_outlook", "int"),
        ("Excel", "prompts_excel", "int"),
        ("Word", "prompts_word", "int"),
        ("PowerPoint", "prompts_powerpoint", "int"),
        ("OneNote", "prompts_onenote", "int"),
        ("Loop", "prompts_loop", "int"),
    ]),
    ("Copilot Chat", "DDEBF7", "1F4E79", [
        ("Chat Users", "chat_users", "int"),
        ("Chat Active Users", "chat_active_users", "int"),
        ("Chat Prompts", "chat_prompts", "int"),
    ]),
    ("Viva Adoption (last 4 wks)", "E4DFEC", "5B3F8C", [
        ("Enabled Users", "viva_enabled_users", "int"),
        ("Active Users", "viva_active_users", "int"),
        ("Copilot Actions", "viva_total_actions", "int"),
    ]),
    ("Agents & Connectors", "FFF2CC", "BF8F00", [
        ("Agents with Usage", "m365_active_agents", "int"),
        ("Agent Users", "m365_agent_users", "int"),
        ("Agent Responses", "m365_agent_responses", "int"),
        ("Connector Users", "connector_users", "int"),
        ("Connector Responses", "connector_responses", "int"),
        ("Cowork Users", "cowork_users", "int"),
        ("Cowork Tasks", "cowork_tasks", "int"),
    ]),
    ("Copilot Studio (last 4 wks)", "FCE4D6", "C55A11", [
        ("Sessions", "cs_sessions", "int"),
        ("Resolution Rate", "cs_resolution_rate", "pct"),
        ("Escalation Rate", "cs_escalation_rate", "pct"),
        ("Abandon Rate", "cs_abandon_rate", "pct"),
        ("Avg CSAT", "cs_csat_avg", "dec"),
        ("Peak WAU", "cs_peak_wau", "int"),
    ]),
    ("Agent Inventory & Conversations", "FBE5D6", "843C0C", [
        ("Total Agents", "total_agents", "int"),
        ("Active Agents (OTel)", "active_agents", "int"),
        ("Utilization Rate", "utilization_rate", "pct"),
        ("Production Agents", "production_agents", "int"),
        ("Non-Prod Agents", "non_prod_agents", "int"),
        ("Agents with Owner", "agents_with_owner", "int"),
        ("Ownership %", "ownership_pct", "pct"),
        ("Conversations", "total_conversations", "int"),
        ("Agent Adopters", "agent_adopters", "int"),
        ("Agent Adoption %", "agent_adoption_pct", "pct"),
    ]),
    ("Environments", "EAD7F5", "7030A0", [
        ("Default", "env_default", "int"),
        ("Developer", "env_developer", "int"),
        ("Teams", "env_teams", "int"),
        ("Production", "env_production", "int"),
        ("Sandbox", "env_sandbox", "int"),
        ("Trial", "env_trial", "int"),
    ]),
    ("Credits", "FFE0E0", "C00000", [
        ("Entitled", "credits_entitled", "dec"),
        ("Prepaid Consumed", "credits_prepaid", "dec"),
        ("PAYG Consumed", "credits_payg", "dec"),
        ("% Entitlement Used", "credits_pct_used", "pct"),
        ("Capacity Consumed", "capacity_total", "dec"),
        ("Avg Daily Burn", "capacity_avg_daily", "dec"),
        ("Days Remaining", "_days_remaining", "int"),
        ("Viva Consumption (last 4 wks)", "consumption_credits", "dec"),
        ("GitHub AI Users (last 4 wks)", "github_users", "int"),
        ("GitHub AI Credits (last 4 wks)", "github_credits", "dec"),
    ]),
]

# Charts drawn under the table when there are 2+ periods: (title, y-axis, keys)
_CHARTS = [
    ("Copilot users", "Users", ["enabled_users", "active_users", "viva_active_users", "chat_active_users"]),
    ("Copilot prompts & actions", "Count", ["total_prompts", "viva_total_actions", "chat_prompts"]),
    ("Agent activity", "Count", ["m365_agent_responses", "cs_sessions", "total_conversations"]),
]

_NUMBER_FORMATS = {"int": "#,##0", "dec": "#,##0.0", "pct": "0.0%"}


def _value(snap: dict, key: str, fmt: str):
    if key == "period":
        # Snapshots taken before period keying show their run date instead.
        return snap.get("period") or (snap.get("snapshot_date") or "")[:10]
    if key == "_days_remaining":
        remaining = (snap.get("credits_entitled") or 0) - (snap.get("credits_prepaid") or 0)
        burn = snap.get("capacity_avg_daily")
        return round(remaining / burn) if burn and remaining > 0 else None
    v = snap.get(key)
    if v is None:
        return None
    return v / 100 if fmt == "pct" else v


def write(ws: Worksheet, snapshots: list[dict]) -> None:
    # Oldest first so the table (and its charts) read left-to-right in time.
    rows = list(reversed(snapshots))

    # Keep only columns with data in at least one period.
    sections = []
    for label, light, dark, cols in _SECTIONS:
        kept = [c for c in cols if c[1] == "period" or any(_value(s, c[1], c[2]) is not None for s in rows)]
        if kept:
            sections.append((label, light, dark, kept))

    center = Alignment(horizontal="center", vertical="center")
    col = 1
    key_col: dict[str, int] = {}
    for label, light, dark, cols in sections:
        start = col
        for header, key, _fmt in cols:
            cell = ws.cell(row=2, column=col, value=header)
            cell.fill = PatternFill("solid", fgColor=dark)
            cell.font = Font(bold=True, color="FFFFFF", size=10)
            cell.alignment = center
            key_col[key] = col
            col += 1
        if label:
            cell = ws.cell(row=1, column=start, value=label)
            cell.fill = PatternFill("solid", fgColor=light)
            cell.font = Font(bold=True, size=10, color=dark)
            cell.alignment = center
            if col - 1 > start:
                ws.merge_cells(start_row=1, start_column=start, end_row=1, end_column=col - 1)
    last_col = col - 1

    ws.freeze_panes = "B3"
    ws.row_dimensions[1].height = 18
    ws.row_dimensions[2].height = 20

    if not rows:
        ws.cell(row=3, column=1, value="— No KPI snapshots yet — run sync to create the first one —")
        return

    fills = (PatternFill("solid", fgColor="FFFFFF"), PatternFill("solid", fgColor="EBF3FB"))
    data_font = Font(size=10)
    for r, snap in enumerate(rows, start=3):
        for _label, _light, _dark, cols in sections:
            for header, key, fmt in cols:
                cell = ws.cell(row=r, column=key_col[key], value=_value(snap, key, fmt))
                cell.fill = fills[r % 2]
                cell.font = data_font
                cell.alignment = LEFT
                if fmt in _NUMBER_FORMATS:
                    cell.number_format = _NUMBER_FORMATS[fmt]
    last_row = 2 + len(rows)

    for c in range(1, last_col + 1):
        header = str(ws.cell(row=2, column=c).value or "")
        widest = max([len(header)] + [len(f"{ws.cell(row=r, column=c).value:,}")
                                      if isinstance(ws.cell(row=r, column=c).value, (int, float))
                                      else len(str(ws.cell(row=r, column=c).value or ""))
                                      for r in range(3, last_row + 1)])
        ws.column_dimensions[get_column_letter(c)].width = min(widest + 3, 30)

    if len(rows) < 2:
        return
    anchor_row = last_row + 3
    categories = Reference(ws, min_col=key_col["period"], min_row=3, max_row=last_row)
    for title, y_title, keys in _CHARTS:
        series_cols = [key_col[k] for k in keys if k in key_col]
        if not series_cols:
            continue
        chart = LineChart()
        chart.title = title
        chart.y_axis.title = y_title
        chart.height, chart.width = 7.5, 16
        for c in series_cols:
            chart.add_data(Reference(ws, min_col=c, min_row=2, max_row=last_row), titles_from_data=True)
        chart.set_categories(categories)
        ws.add_chart(chart, f"A{anchor_row}")
        anchor_row += 16
