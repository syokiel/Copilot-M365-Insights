from openpyxl.worksheet.worksheet import Worksheet

from src.writers._style import apply_row_style, autofit_columns, write_headers

HEADERS = [
    "Organization", "Function Type", "Copilot Licensed",
    "Service Name", "Metric Date", "Session Count",
    "Total Credits Used", "Spending Policy Limit", "User Limit",
]

_FIELDS = [
    "organization", "function_type", "is_copilot_licensed",
    "service_name", "metric_date", "session_count",
    "total_credits_used", "spending_policy_limit", "user_limit",
]


def _yn(v) -> str:
    return "Yes" if v else ("No" if v is not None else "")


def write(ws: Worksheet, rows: list[dict]) -> None:
    write_headers(ws, HEADERS)

    if not rows:
        ws.cell(row=2, column=1, value="— No Viva Consumption data imported (set VIVA_REPORT_CONSUMPTION) —")
    else:
        for i, r in enumerate(rows, start=2):
            for col, field in enumerate(_FIELDS, start=1):
                value = _yn(r.get(field)) if field == "is_copilot_licensed" else r.get(field)
                ws.cell(row=i, column=col, value=value)
            apply_row_style(ws, i, len(HEADERS))

    autofit_columns(ws, HEADERS)
