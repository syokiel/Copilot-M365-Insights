"""GitHub_AI_Credits — per-person GitHub AI credit rollup across all imported
days (Viva daily consumption export)."""
from openpyxl.worksheet.worksheet import Worksheet

from src.writers._style import apply_row_style, autofit_columns, write_headers

HEADERS = [
    "Person ID", "Copilot Licensed", "Organization", "Active Days",
    "Total Credits", "Avg Credits / Day", "First Date", "Last Date",
]
_FIELDS = [
    "person_id", "is_copilot_licensed", "organization", "active_days",
    "total_credits", "avg_credits_per_day", "first_date", "last_date",
]


def write(ws: Worksheet, rows: list[dict]) -> None:
    write_headers(ws, HEADERS)
    if not rows:
        ws.cell(row=2, column=1, value="— No GitHub AI credit data imported (set VIVA_REPORT_CONSUMPTION_DAILY) —")
    for i, r in enumerate(rows, start=2):
        for col, field in enumerate(_FIELDS, start=1):
            value = r.get(field)
            if field == "is_copilot_licensed" and value is not None:
                value = "Yes" if value else "No"
            cell = ws.cell(row=i, column=col, value=value)
            if field in ("total_credits", "avg_credits_per_day"):
                cell.number_format = "#,##0.00"
        apply_row_style(ws, i, len(HEADERS))
    autofit_columns(ws, HEADERS)
