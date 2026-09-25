from collections import Counter
from datetime import datetime, timezone

from openpyxl.styles import Font, PatternFill
from openpyxl.worksheet.worksheet import Worksheet

from src.writers._style import HEADER_FILL, HEADER_FONT, LEFT, autofit_columns


def write(
    ws: Worksheet,
    events: list[dict],
    connector_calls: list[dict],
    model_calls: list[dict] = [],
    kpi_snapshot: dict | None = None,
    viva_reports_cs_sessions: list[dict] | None = None,
    viva_reports_cs_wau: list[dict] | None = None,
    viva_reports_cs_autonomous: list[dict] | None = None,
    viva_reports_cs_agents: dict[str, dict] | None = None,
    previous_kpi_snapshot: dict | None = None,
    import_status: list[dict] | None = None,
) -> None:
    prod_events = [e for e in events if not e.get("DesignMode")]
    prod_connectors = [c for c in connector_calls if not c.get("DesignMode")]

    all_conversations = {e["ConversationId"] for e in events if e.get("ConversationId")}
    prod_conversations = {e["ConversationId"] for e in prod_events if e.get("ConversationId")}

    received = [e for e in events if e.get("EventName") == "BotMessageReceived"]
    sent = [e for e in events if e.get("EventName") == "BotMessageSend"]

    connector_counter: Counter = Counter(c.get("ConnectorName", "Unknown") for c in prod_connectors)
    failed_connectors = [c for c in prod_connectors if not c.get("Success")]

    timestamps = [e["Timestamp"] for e in events if e.get("Timestamp")]
    earliest = min(timestamps) if timestamps else None
    latest = max(timestamps) if timestamps else None

    total_input_tokens = sum(r.get("gen_ai_usage_input_tokens") or 0 for r in model_calls)
    total_output_tokens = sum(r.get("gen_ai_usage_output_tokens") or 0 for r in model_calls)
    model_counter: Counter = Counter(
        r.get("gen_ai_request_model") or r.get("gen_ai_response_model", "unknown")
        for r in model_calls
        if r.get("gen_ai_request_model") or r.get("gen_ai_response_model")
    )
    agents_using_ai = {r.get("gen_ai_agent_name") or r.get("gen_ai_agent_id", "") for r in model_calls if r.get("gen_ai_agent_id")}

    rows = [
        ("Report generated", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")),
        ("Data range (earliest)", str(earliest)[:19] if earliest else "—"),
        ("Data range (latest)", str(latest)[:19] if latest else "—"),
        (None, None),
        ("── Conversations ─────────────────────────────", None),
        ("Total conversations", len(all_conversations)),
        ("Production conversations", len(prod_conversations)),
        ("Design-mode conversations", len(all_conversations) - len(prod_conversations)),
        (None, None),
        ("── Messages ──────────────────────────────────", None),
        ("Total events", len(events)),
        ("Messages received (user → bot)", len(received)),
        ("Messages sent (bot → user)", len(sent)),
        (None, None),
        ("── Connector Calls (production) ──────────────", None),
        ("Total connector calls", len(prod_connectors)),
        ("Failed connector calls", len(failed_connectors)),
    ]

    if connector_counter:
        rows.append((None, None))
        rows.append(("── Top Connectors ────────────────────────────", None))
        for name, count in connector_counter.most_common(10):
            rows.append((f"  {name}", count))

    rows.append((None, None))
    rows.append(("── Generative AI Usage ───────────────────────", None))
    if model_calls:
        rows += [
            ("AI model calls",               len(model_calls)),
            ("Agents using generative AI",   len(agents_using_ai)),
            ("Total input tokens",           total_input_tokens),
            ("Total output tokens",          total_output_tokens),
            ("Total tokens",                 total_input_tokens + total_output_tokens),
        ]
        if model_counter:
            rows.append((None, None))
            rows.append(("── Models Used ───────────────────────────────", None))
            for model, count in model_counter.most_common():
                rows.append((f"  {model}", count))
    else:
        rows.append(("  No AI model call data in this window", None))

    if kpi_snapshot:
        rows += _kpi_rows(kpi_snapshot, previous_kpi_snapshot)

    # ── Viva CS (Copilot Studio analytics) ────────────────────────────────────
    rows.append((None, None))
    rows.append(("── Viva CS (Copilot Studio) ──────────────────", None))

    if viva_reports_cs_sessions:
        total_sess     = sum(r.get("total_sessions")    or 0 for r in viva_reports_cs_sessions)
        total_engaged  = sum(r.get("engaged_sessions")  or 0 for r in viva_reports_cs_sessions)
        total_resolved = sum(r.get("resolved_sessions") or 0 for r in viva_reports_cs_sessions)
        total_escalated= sum(r.get("escalated_sessions")or 0 for r in viva_reports_cs_sessions)
        total_abandoned= sum(r.get("abandoned_sessions")or 0 for r in viva_reports_cs_sessions)
        total_csat_n   = sum(r.get("csat_responses")    or 0 for r in viva_reports_cs_sessions)

        # Weighted avg CSAT
        csat_score = 0.0
        if total_csat_n:
            for r in viva_reports_cs_sessions:
                n = r.get("csat_responses") or 0
                if n:
                    s = (
                        (r.get("csat_1") or 0) * 1 + (r.get("csat_2") or 0) * 2 +
                        (r.get("csat_3") or 0) * 3 + (r.get("csat_4") or 0) * 4 +
                        (r.get("csat_5") or 0) * 5
                    )
                    csat_score += s
            csat_score = round(csat_score / total_csat_n, 2)

        pct = lambda v, d: f"{v/d*100:.1f}%" if d else "—"  # noqa: E731

        rows += [
            ("Catalog agents",      len(viva_reports_cs_agents) if viva_reports_cs_agents else "—"),
            ("Total sessions",      total_sess),
            ("Engaged sessions",    f"{total_engaged}  ({pct(total_engaged, total_sess)})"),
            ("Resolved sessions",   f"{total_resolved}  ({pct(total_resolved, total_sess)})"),
            ("Escalated sessions",  f"{total_escalated}  ({pct(total_escalated, total_sess)})"),
            ("Abandoned sessions",  f"{total_abandoned}  ({pct(total_abandoned, total_sess)})"),
            ("CSAT responses",      total_csat_n),
            ("Avg CSAT score",      csat_score if total_csat_n else "—"),
        ]
    else:
        rows.append(("  No Copilot Studio session data imported", None))

    if viva_reports_cs_wau:
        peak = max(viva_reports_cs_wau, key=lambda r: r.get("active_user_count") or 0)
        rows += [
            ("Peak weekly active users", peak.get("active_user_count")),
            ("Peak WAU week",           peak.get("start_date", "—")),
        ]

    if viva_reports_cs_autonomous:
        total_runs  = sum(r.get("total_runs")      or 0 for r in viva_reports_cs_autonomous)
        total_succ  = sum(r.get("successful_runs") or 0 for r in viva_reports_cs_autonomous)
        rows += [
            ("Autonomous runs (total)",   total_runs),
            ("Autonomous success rate",   f"{total_succ/total_runs*100:.1f}%" if total_runs else "—"),
        ]

    if import_status:
        rows.append((None, None))
        rows.append(("── Data as of (latest load per source) ───────", None))
        for st in import_status:
            rows.append((
                f"  {st['table_name']}",
                f"{st['row_count']:,} rows · {(st['imported_at'] or '')[:10]} · {st['mode']}",
                "current" if st["current_run"] else "carried forward from an earlier run",
            ))

    prev_label = "Previous"
    if previous_kpi_snapshot:
        prev_label = f"Previous ({_period_label(previous_kpi_snapshot)})"
    headers = ["Metric", "Value", prev_label, "Change"]
    ws.column_dimensions["A"].width = 48
    ws.column_dimensions["B"].width = 28
    ws.column_dimensions["C"].width = 22
    ws.column_dimensions["D"].width = 16

    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = LEFT

    ws.freeze_panes = "A2"

    for row_idx, row in enumerate(rows, 2):
        metric = row[0]
        fmt = row[4] if len(row) > 4 else None
        a = ws.cell(row=row_idx, column=1, value=metric)
        a.alignment = LEFT
        if metric and metric.startswith("──"):
            a.font = Font(bold=True, size=11, color="1F4E79")
            continue
        a.font = Font(size=11)
        for col, val in enumerate(row[1:4], start=2):
            cell = ws.cell(row=row_idx, column=col, value=val)
            cell.alignment = LEFT
            cell.font = Font(size=11)
            if fmt and isinstance(val, (int, float)):
                cell.number_format = _CHANGE_FORMATS[fmt] if col == 4 else _VALUE_FORMATS[fmt]
            if col == 4 and isinstance(val, (int, float)) and val:
                cell.font = Font(size=11, color="548235" if val > 0 else "C00000")
            if col == 3 and isinstance(val, str) and val.startswith("carried"):
                cell.font = Font(size=11, color="C55A11")


# KPI rows on the summary: (section, [(label, snapshot key, format)])
# format: "int" | "dec" | "pct" (stored 0–100)
_KPI_SECTIONS = [
    ("M365 Copilot", [
        ("Total Licenses", "total_licenses", "int"),
        ("Enabled Users", "enabled_users", "int"),
        ("Active Users", "active_users", "int"),
        ("Activation Rate", "activation_rate", "pct"),
        ("Adoption Rate", "adoption_rate", "pct"),
        ("Power Users", "power_users", "int"),
        ("Total Prompts", "total_prompts", "int"),
        ("Avg Prompts / Active User", "avg_prompts_per_user", "dec"),
        ("Copilot Chat Users", "chat_users", "int"),
        ("Copilot Chat Active Users", "chat_active_users", "int"),
        ("Copilot Chat Prompts", "chat_prompts", "int"),
    ]),
    ("Viva Copilot Adoption (last 4 weeks of data)", [
        ("Enabled Users", "viva_enabled_users", "int"),
        ("Active Users", "viva_active_users", "int"),
        ("Copilot Actions", "viva_total_actions", "int"),
    ]),
    ("Agents & Connectors", [
        ("Agents with Usage (M365 report)", "m365_active_agents", "int"),
        ("Agent Users", "m365_agent_users", "int"),
        ("Agent Responses", "m365_agent_responses", "int"),
        ("Connector Users", "connector_users", "int"),
        ("Connector Responses", "connector_responses", "int"),
        ("Cowork Users", "cowork_users", "int"),
        ("Cowork Tasks", "cowork_tasks", "int"),
    ]),
    ("Copilot Studio Agents (last 4 weeks of data)", [
        ("Sessions", "cs_sessions", "int"),
        ("Resolution Rate", "cs_resolution_rate", "pct"),
        ("Escalation Rate", "cs_escalation_rate", "pct"),
        ("Abandon Rate", "cs_abandon_rate", "pct"),
        ("Avg CSAT", "cs_csat_avg", "dec"),
        ("Peak Weekly Active Users", "cs_peak_wau", "int"),
    ]),
    ("Agent Inventory & Conversations", [
        ("Total Agents", "total_agents", "int"),
        ("Active Agents (OTel)", "active_agents", "int"),
        ("Utilization Rate", "utilization_rate", "pct"),
        ("Production Agents", "production_agents", "int"),
        ("Non-Prod Agents", "non_prod_agents", "int"),
        ("Ownership Coverage", "ownership_pct", "pct"),
        ("Total Conversations", "total_conversations", "int"),
        ("Agent Adopters", "agent_adopters", "int"),
        ("Agent Adoption %", "agent_adoption_pct", "pct"),
    ]),
    ("Credits", [
        ("Entitled Credits", "credits_entitled", "dec"),
        ("Prepaid Consumed", "credits_prepaid", "dec"),
        ("PAYG Consumed", "credits_payg", "dec"),
        ("% Entitlement Used", "credits_pct_used", "pct"),
        ("Viva Consumption Credits (last 4 weeks)", "consumption_credits", "dec"),
        ("GitHub AI Users (last 4 weeks)", "github_users", "int"),
        ("GitHub AI Credits (last 4 weeks)", "github_credits", "dec"),
    ]),
]

_VALUE_FORMATS = {"int": "#,##0", "dec": "#,##0.0", "pct": "0.0%"}
# pct changes are percentage points, shown in % format (0.012 → +1.2%).
_CHANGE_FORMATS = {"int": "+#,##0;-#,##0;0", "dec": "+#,##0.0;-#,##0.0;0", "pct": "+0.0%;-0.0%;0.0%"}


def _period_label(snap: dict) -> str:
    return snap.get("period") or (snap.get("snapshot_date") or "")[:10]


def _kpi_rows(current: dict, previous: dict | None) -> list[tuple]:
    """(label, value, previous, change, format) rows; metrics with no value
    in either period are skipped."""
    def val(snap, key, fmt):
        v = (snap or {}).get(key)
        if v is None:
            return None
        return v / 100 if fmt == "pct" else v

    title = f"KPIs — period {_period_label(current)}"
    if current.get("period_end"):
        title += f" (data to {current['period_end']})"
    out: list[tuple] = [(None, None), (f"── {title} ─────────", None)]
    for section, metrics in _KPI_SECTIONS:
        section_rows = []
        for label, key, fmt in metrics:
            cur, prev = val(current, key, fmt), val(previous, key, fmt)
            if cur is None and prev is None:
                continue
            change = cur - prev if cur is not None and prev is not None else None
            section_rows.append((f"  {label}", cur if cur is not None else "—", prev, change, fmt))
        if section_rows:
            out.append((f"── {section} ─────────", None))
            out += section_rows
    return out
