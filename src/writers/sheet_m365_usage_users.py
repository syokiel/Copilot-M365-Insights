from openpyxl.worksheet.worksheet import Worksheet

from src.writers._style import apply_row_style, autofit_columns, write_headers

HEADERS = [
    "Username", "Display Name", "Agents Used",
    "Agent Responses Received", "Last Activity Date",
]

_FIELDS = [
    "username", "display_name", "agents_used",
    "agent_responses_received", "last_activity_date",
]


def write(ws: Worksheet, rows: list[dict]) -> None:
    write_headers(ws, HEADERS)

    if not rows:
        ws.cell(row=2, column=1, value="— No M365 usage user data imported (set M365ADMIN_USAGE_REPORT_USERS) —")
    else:
        for i, r in enumerate(rows, start=2):
            for col, field in enumerate(_FIELDS, start=1):
                ws.cell(row=i, column=col, value=r.get(field))
            apply_row_style(ws, i, len(HEADERS))

    autofit_columns(ws, HEADERS)
