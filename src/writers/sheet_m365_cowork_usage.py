from openpyxl.worksheet.worksheet import Worksheet

from src.writers._style import apply_row_style, autofit_columns, write_headers

HEADERS = [
    "User Principal Name", "Display Name",
    "Total Tasks", "Scheduled Tasks", "User Initiated Tasks",
    "Active Days", "Last Activity Date",
]

_FIELDS = [
    "user_principal_name", "display_name",
    "total_tasks", "scheduled_tasks", "user_initiated_tasks",
    "active_days", "last_activity_date",
]


def write(ws: Worksheet, rows: list[dict]) -> None:
    write_headers(ws, HEADERS)

    if not rows:
        ws.cell(row=2, column=1, value="— No Cowork usage data imported (set M365ADMIN_COWORK_USAGE) —")
    else:
        for i, r in enumerate(rows, start=2):
            for col, field in enumerate(_FIELDS, start=1):
                ws.cell(row=i, column=col, value=r.get(field))
            apply_row_style(ws, i, len(HEADERS))

    autofit_columns(ws, HEADERS)
