from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from openpyxl.styles import Font, PatternFill
from openpyxl.worksheet.worksheet import Worksheet

from src.writers._style import HEADER_FILL, HEADER_FONT, LEFT

_WARN_FILL  = PatternFill("solid", fgColor="FFF2CC")   # amber — watch
_ALERT_FILL = PatternFill("solid", fgColor="FFE0E0")   # red   — action needed
_GOOD_FILL  = PatternFill("solid", fgColor="E2EFDA")   # green — healthy


def write(
    ws: Worksheet,
    entitlement: list[dict],
    per_agent: list[dict],
    per_user: list[dict],
    capacity: list[dict],
    consumption_by_service: list[dict] | None = None,
    daily_totals: list[dict] | None = None,
    github_by_person: list[dict] | None = None,
) -> None:
    consumption_by_service = consumption_by_service or []
    daily_totals = daily_totals or []
    github_by_person = github_by_person or []

    # ── Aggregates: entitlement ───────────────────────────────────────────────
    total_entitled  = sum(r.get("entitled_quantity")          or 0 for r in entitlement)
    total_prepaid   = sum(r.get("prepaid_consumed_quantity")  or 0 for r in entitlement)
    total_payg      = sum(r.get("payg_consumed_quantity")     or 0 for r in entitlement)
    total_consumed  = total_prepaid + total_payg
    remaining       = max(0.0, total_entitled - total_prepaid)
    pct_used        = round(total_consumed / total_entitled * 100, 1) if total_entitled else 0.0

    usage_dates = [r.get("usage_date") for r in entitlement if r.get("usage_date")]
    date_min = min(usage_dates) if usage_dates else None
    date_max = max(usage_dates) if usage_dates else None

    # ── Aggregates: capacity burn rate ────────────────────────────────────────
    daily: dict[str, float] = defaultdict(float)
    billable_capacity   = 0.0
    unbillable_capacity = 0.0
    for r in capacity:
        qty = r.get("consumed_quantity") or 0
        d   = r.get("consumption_date", "")
        if d:
            daily[d[:10]] += qty
        if r.get("is_billable"):
            billable_capacity += qty
        else:
            unbillable_capacity += qty

    total_capacity = billable_capacity + unbillable_capacity
    avg_daily  = round(total_capacity / len(daily), 1) if daily else 0.0
    peak_day   = max(daily, key=daily.get) if daily else None
    peak_qty   = round(daily[peak_day], 1) if peak_day else 0.0
    days_left  = round(remaining / avg_daily) if avg_daily and remaining else None

    # ── Aggregates: Viva Consumption credits by service ───────────────────────
    service_credits: dict[str, float] = defaultdict(float)
    for r in consumption_by_service:
        service_credits[r.get("service_name") or "Unknown"] += r.get("total_credits_used") or 0
    top_services = sorted(service_credits.items(), key=lambda x: x[1], reverse=True)
    consumption_people = {r.get("people_historical_id") for r in consumption_by_service if r.get("people_historical_id")}

    # ── Aggregates: per-agent credits ─────────────────────────────────────────
    agent_credits: dict[str, float] = defaultdict(float)
    agent_billed:  dict[str, float] = defaultdict(float)
    model_credits: dict[str, float] = defaultdict(float)
    channel_credits: dict[str, float] = defaultdict(float)
    feature_credits: dict[str, float] = defaultdict(float)

    for r in per_agent:
        name    = r.get("agent_name") or "Unknown"
        billed  = r.get("billed_credit")     or 0
        unbilled= r.get("non_billed_credit") or 0
        total   = billed + unbilled
        agent_credits[name]           += total
        agent_billed[name]            += billed
        model_credits[r.get("llm_model")   or "Unknown"] += total
        channel_credits[r.get("channel")   or "Unknown"] += total
        feature_credits[r.get("ai_feature")or "Unknown"] += total

    top_agents_total  = sorted(agent_credits.items(),  key=lambda x: x[1], reverse=True)[:10]
    top_agents_billed = sorted(agent_billed.items(),   key=lambda x: x[1], reverse=True)[:5]
    top_models        = sorted(model_credits.items(),  key=lambda x: x[1], reverse=True)
    top_channels      = sorted(channel_credits.items(),key=lambda x: x[1], reverse=True)
    top_features      = sorted(feature_credits.items(),key=lambda x: x[1], reverse=True)

    total_billed_credits   = sum(r.get("billed_credit")     or 0 for r in per_agent)
    total_unbilled_credits = sum(r.get("non_billed_credit") or 0 for r in per_agent)

    # ── Aggregates: per-user credits ──────────────────────────────────────────
    user_credits: dict[str, float] = defaultdict(float)
    user_billable: dict[str, float] = defaultdict(float)
    user_licensed: dict[str, bool]  = {}
    for r in per_user:
        email   = r.get("user_email") or r.get("user_id", "Unknown")
        credits = r.get("credits_used")        or 0
        billed  = r.get("billable_credit_used") or 0
        user_credits[email]  += credits
        user_billable[email] += billed
        if email not in user_licensed:
            user_licensed[email] = bool(r.get("m365_copilot_licensed"))

    top_users = sorted(user_credits.items(), key=lambda x: x[1], reverse=True)[:10]
    unlicensed_with_billable = [
        (email, round(user_billable[email], 1))
        for email, licensed in user_licensed.items()
        if not licensed and user_billable.get(email, 0) > 0
    ]
    unlicensed_with_billable.sort(key=lambda x: x[1], reverse=True)
    total_users_consuming = len(user_credits)
    licensed_credits   = sum(v for e, v in user_credits.items() if user_licensed.get(e))
    unlicensed_credits = sum(v for e, v in user_credits.items() if not user_licensed.get(e))

    # ── Environment-level entitlement ─────────────────────────────────────────
    env_totals: dict[str, dict] = {}
    for r in entitlement:
        env = r.get("environment_name") or "Unknown"
        if env not in env_totals:
            env_totals[env] = {"entitled": 0.0, "prepaid": 0.0, "payg": 0.0}
        env_totals[env]["entitled"] += r.get("entitled_quantity")         or 0
        env_totals[env]["prepaid"]  += r.get("prepaid_consumed_quantity") or 0
        env_totals[env]["payg"]     += r.get("payg_consumed_quantity")    or 0

    # ── Build row list ────────────────────────────────────────────────────────
    def _fmt(v) -> str:
        if v is None:
            return "—"
        if isinstance(v, float):
            return f"{v:,.1f}"
        return str(v)

    def _pct(v, d) -> str:
        return f"{v/d*100:.1f}%" if d else "—"

    rows: list[tuple] = [
        ("Report generated", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")),
        ("Data range", f"{date_min or '—'}  →  {date_max or '—'}"),
    ]

    # ── Section 1: Headline credit metrics ───────────────────────────────────
    rows += [
        (None, None),
        ("── Entitlement Overview ──────────────────────────", None),
        ("Total entitled credits",          _fmt(total_entitled)),
        ("Total prepaid consumed",          _fmt(total_prepaid)),
        ("Total PAYG consumed",             _fmt(total_payg)),
        ("Total consumed (prepaid + PAYG)", _fmt(total_consumed)),
        ("Remaining prepaid entitlement",   _fmt(remaining)),
        ("% of entitlement consumed",       f"{pct_used}%"),
        ("PAYG active?",                    "YES — review budget" if total_payg > 0 else "No"),
    ]

    # ── Section 2: Burn rate ──────────────────────────────────────────────────
    rows += [
        (None, None),
        ("── Capacity Burn Rate ────────────────────────────", None),
        ("Total capacity consumed",         _fmt(total_capacity)),
        ("  Billable",                      _fmt(billable_capacity)),
        ("  Non-billable",                  _fmt(unbillable_capacity)),
        ("Active consumption days",         str(len(daily))),
        ("Average daily consumption",       _fmt(avg_daily)),
        ("Peak single-day consumption",     f"{_fmt(peak_qty)}  ({peak_day or '—'})"),
        ("Estimated days of prepaid left",  str(days_left) if days_left is not None else "—"),
    ]

    # ── Section 2.5: Credits by service (Viva Consumption) ────────────────────
    if top_services:
        rows += [
            (None, None),
            ("── Credits by Service (Viva Consumption) ────────", None),
            ("People consuming credits (Viva Consumption)", str(len(consumption_people))),
        ]
        for service, total in top_services:
            rows.append((f"  {service}", _fmt(total)))

    rows += _daily_rows(daily_totals, _fmt)
    rows += _github_rows(daily_totals, github_by_person, _fmt)

    # ── Section 3: Credit breakdown by agent ─────────────────────────────────
    rows += [
        (None, None),
        ("── Top Agents by Total Credits ──────────────────", None),
    ]
    for agent, total in top_agents_total:
        rows.append((f"  {agent}", _fmt(total)))

    rows += [
        (None, None),
        ("── Top Agents by Billed Credits ─────────────────", None),
    ]
    for agent, billed in top_agents_billed:
        rows.append((f"  {agent}", _fmt(billed)))

    # ── Section 4: LLM model breakdown ───────────────────────────────────────
    rows += [
        (None, None),
        ("── Credits by LLM Model ─────────────────────────", None),
    ]
    for model, total in top_models:
        rows.append((f"  {model}", _fmt(total)))

    # ── Section 5: Channel breakdown ──────────────────────────────────────────
    rows += [
        (None, None),
        ("── Credits by Channel ────────────────────────────", None),
    ]
    for channel, total in top_channels:
        rows.append((f"  {channel}", _fmt(total)))

    # ── Section 6: AI Feature breakdown ──────────────────────────────────────
    rows += [
        (None, None),
        ("── Credits by AI Feature ────────────────────────", None),
    ]
    for feature, total in top_features:
        rows.append((f"  {feature}", _fmt(total)))

    # ── Section 7: Per-user consumption ──────────────────────────────────────
    rows += [
        (None, None),
        ("── User Consumption ─────────────────────────────", None),
        ("Total users consuming credits",      str(total_users_consuming)),
        ("Credits from M365 licensed users",   _fmt(licensed_credits)),
        ("Credits from unlicensed users",      _fmt(unlicensed_credits)),
        ("Unlicensed users with billed credits", str(len(unlicensed_with_billable))),
        (None, None),
        ("── Top Users by Total Credits ───────────────────", None),
    ]
    for email, total in top_users:
        licensed_tag = "" if user_licensed.get(email) else "  ⚠ unlicensed"
        rows.append((f"  {email}{licensed_tag}", _fmt(total)))

    if unlicensed_with_billable:
        rows += [
            (None, None),
            ("── Unlicensed Users with Billed Credits ─────────", None),
        ]
        for email, billed in unlicensed_with_billable[:10]:
            rows.append((f"  {email}", _fmt(billed)))

    # ── Section 8: Environment-level entitlement status ───────────────────────
    rows += [
        (None, None),
        ("── Entitlement by Environment ───────────────────", None),
    ]
    for env, t in sorted(env_totals.items()):
        pct = round((t["prepaid"] + t["payg"]) / t["entitled"] * 100, 1) if t["entitled"] else 0.0
        payg_flag = "  ⚠ PAYG active" if t["payg"] > 0 else ""
        rows.append((f"  {env}", f"{pct}% used  |  prepaid {_fmt(t['prepaid'])}  /  {_fmt(t['entitled'])}{payg_flag}"))

    # ── Write headers ─────────────────────────────────────────────────────────
    for col, header in enumerate(["Metric", "Value"], 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = LEFT

    ws.freeze_panes  = "A2"
    ws.column_dimensions["A"].width = 50
    ws.column_dimensions["B"].width = 40

    # ── Write rows ────────────────────────────────────────────────────────────
    for row_idx, (metric, value) in enumerate(rows, 2):
        a = ws.cell(row=row_idx, column=1, value=metric)
        b = ws.cell(row=row_idx, column=2, value=value)
        a.alignment = LEFT
        b.alignment = LEFT

        if metric and metric.startswith("──"):
            a.font = Font(bold=True, size=11, color="1F4E79")
            b.font = Font(size=11)
        else:
            a.font = Font(size=11)
            b.font = Font(size=11)

        # Colour-code alert rows
        val_str = str(value or "")
        if metric == "PAYG active?" and "YES" in val_str:
            a.fill = _ALERT_FILL
            b.fill = _ALERT_FILL
        elif metric == "Unlicensed users with billed credits" and value not in (None, "0", "—"):
            a.fill = _WARN_FILL
            b.fill = _WARN_FILL
        elif metric == "Estimated days of prepaid left" and value not in (None, "—"):
            try:
                if int(value) < 30:
                    a.fill = _ALERT_FILL
                    b.fill = _ALERT_FILL
                elif int(value) < 90:
                    a.fill = _WARN_FILL
                    b.fill = _WARN_FILL
                else:
                    a.fill = _GOOD_FILL
                    b.fill = _GOOD_FILL
            except (ValueError, TypeError):
                pass
        elif metric == "% of entitlement consumed":
            try:
                pct_v = float(val_str.replace("%", ""))
                if pct_v >= 90:
                    a.fill = _ALERT_FILL
                    b.fill = _ALERT_FILL
                elif pct_v >= 75:
                    a.fill = _WARN_FILL
                    b.fill = _WARN_FILL
                else:
                    a.fill = _GOOD_FILL
                    b.fill = _GOOD_FILL
            except (ValueError, TypeError):
                pass


def _window_change(by_date: dict[str, float], end: str) -> tuple[float, float]:
    """Credits in the 7 days ending `end` and the 7 days before that."""
    end_d = date.fromisoformat(end)
    last7 = sum(v for d, v in by_date.items() if end_d - timedelta(days=6) <= date.fromisoformat(d) <= end_d)
    prev7 = sum(v for d, v in by_date.items()
                if end_d - timedelta(days=13) <= date.fromisoformat(d) <= end_d - timedelta(days=7))
    return last7, prev7


def _change_text(last7: float, prev7: float, fmt) -> str:
    if not prev7:
        return f"{fmt(last7)}  (previous 7 days: none)"
    return f"{fmt(last7)}  ({(last7 - prev7) / prev7 * 100:+.1f}% vs previous 7 days)"


def _daily_rows(daily_totals: list[dict], fmt) -> list[tuple]:
    """Per-service summary of the Viva daily consumption export
    (detail in the DailyCredit_Trends and Credits_Daily tabs)."""
    if not daily_totals:
        return []
    end = max(r["metric_date"] for r in daily_totals)
    rows: list[tuple] = [
        (None, None),
        ("── Daily Credit Consumption (Viva daily export) ─", None),
        ("Data range", f"{min(r['metric_date'] for r in daily_totals)}  →  {end}"),
        ("Detail", "see DailyCredit_Trends and Credits_Daily tabs"),
    ]
    services = sorted({r["service"] for r in daily_totals}, key=lambda n: (n == "GitHub AI", n))
    for service in services:
        svc = [r for r in daily_totals if r["service"] == service]
        by_date = {r["metric_date"]: r.get("credits") or 0.0 for r in svc}
        total = sum(by_date.values())
        # Each service is measured over its own coverage in the export.
        first, last = min(by_date), max(by_date)
        calendar_days = (date.fromisoformat(last) - date.fromisoformat(first)).days + 1
        peak = max(svc, key=lambda r: r.get("credits") or 0)
        last7, prev7 = _window_change(by_date, last)
        rows += [
            (f"  {service} — total credits", f"{fmt(total)}  ({first} → {last})"),
            (f"  {service} — active days", f"{sum(1 for v in by_date.values() if v)} of {calendar_days}"),
            (f"  {service} — average per day", fmt(total / calendar_days)),
            (f"  {service} — peak day", f"{fmt(peak.get('credits') or 0.0)}  ({peak['metric_date']})"),
            (f"  {service} — most people in a day", str(max(r.get('people') or 0 for r in svc))),
            (f"  {service} — last 7 days", _change_text(last7, prev7, fmt)),
        ]
    return rows


def _github_rows(daily_totals: list[dict], github_by_person: list[dict], fmt) -> list[tuple]:
    """GitHub AI credit headline, licence split and top users
    (detail in the GitHub_AI_Credits tab)."""
    if not github_by_person:
        return []
    total = sum(p.get("total_credits") or 0 for p in github_by_person)
    licensed = [p for p in github_by_person if p.get("is_copilot_licensed")]
    unlicensed = [p for p in github_by_person if p.get("is_copilot_licensed") == 0]
    by_date = {r["metric_date"]: r.get("credits") or 0.0 for r in daily_totals if r["service"] == "GitHub AI"}
    rows: list[tuple] = [
        (None, None),
        ("── GitHub AI Credits ────────────────────────────", None),
        ("Detail", "see GitHub_AI_Credits and DailyCredit_Trends tabs"),
        ("Total GitHub AI credits", fmt(total)),
        ("People using GitHub AI", str(len(github_by_person))),
        ("Average credits per person", fmt(total / len(github_by_person))),
        ("  M365 Copilot licensed — people / credits",
         f"{len(licensed)}  /  {fmt(sum(p.get('total_credits') or 0 for p in licensed))}"),
        ("  Not M365 Copilot licensed — people / credits",
         f"{len(unlicensed)}  /  {fmt(sum(p.get('total_credits') or 0 for p in unlicensed))}"),
    ]
    if by_date:
        peak_day = max(by_date, key=by_date.get)
        last7, prev7 = _window_change(by_date, max(by_date))
        rows += [
            ("Peak day", f"{fmt(by_date[peak_day])}  ({peak_day})"),
            ("Last 7 days", _change_text(last7, prev7, fmt)),
        ]
    rows += [(None, None), ("── Top GitHub AI Users by Credits ───────────────", None)]
    for p in github_by_person[:10]:
        tag = "" if p.get("is_copilot_licensed") else "  (not M365 Copilot licensed)"
        rows.append((f"  {p['person_id']}{tag}", f"{fmt(p.get('total_credits') or 0.0)}  over {p.get('active_days')} days"))
    return rows
