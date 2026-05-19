from collections import Counter
from datetime import datetime, timezone

from openpyxl.styles import Font, PatternFill
from openpyxl.worksheet.worksheet import Worksheet

from src.writers._style import HEADER_FILL, HEADER_FONT, LEFT, autofit_columns


def write(ws: Worksheet, events: list[dict], connector_calls: list[dict]) -> None:
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

    headers = ["Metric", "Value"]
    ws.column_dimensions["A"].width = 48
    ws.column_dimensions["B"].width = 28

    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = LEFT

    ws.freeze_panes = "A2"

    for row_idx, (metric, value) in enumerate(rows, 2):
        a = ws.cell(row=row_idx, column=1, value=metric)
        b = ws.cell(row=row_idx, column=2, value=value)
        a.alignment = LEFT
        b.alignment = LEFT
        if metric and metric.startswith("──"):
            a.font = Font(bold=True, size=11, color="1F4E79")
        else:
            a.font = Font(size=11)
            b.font = Font(size=11)
