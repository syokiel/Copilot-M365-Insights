from openpyxl.worksheet.worksheet import Worksheet

from src.writers._style import apply_row_style, autofit_columns, write_headers

HEADERS = [
    "User Principal Name", "Display Name", "User GUID",
    "Last Activity Date", "Prompts Submitted", "Active Usage Days",
    "Last Activity — M365 Copilot App", "Last Activity — Word",
    "Last Activity — Excel", "Last Activity — PowerPoint",
    "Last Activity — OneNote", "Last Activity — Edge",
    "Last Activity — Teams", "Last Activity — Outlook",
    "Last Activity — Copilot.cloud.microsoft",
    "Report Period", "Report Refresh Date",
]

_FIELDS = [
    "user_principal_name", "display_name", "user_guid",
    "last_activity_date", "prompts_submitted", "active_usage_days",
    "last_activity_m365_copilot_app", "last_activity_word",
    "last_activity_excel", "last_activity_powerpoint",
    "last_activity_onenote", "last_activity_edge",
    "last_activity_teams", "last_activity_outlook",
    "last_activity_copilot_cloud",
    "report_period", "report_refresh_date",
]


def write(ws: Worksheet, rows: list[dict]) -> None:
    write_headers(ws, HEADERS)

    if not rows:
        ws.cell(row=2, column=1, value="— No Copilot Chat usage data imported (set M365ADMIN_USAGE_COPILOT_CHAT) —")
    else:
        for i, r in enumerate(rows, start=2):
            for col, field in enumerate(_FIELDS, start=1):
                ws.cell(row=i, column=col, value=r.get(field))
            apply_row_style(ws, i, len(HEADERS))

    autofit_columns(ws, HEADERS)
