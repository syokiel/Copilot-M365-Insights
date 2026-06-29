from openpyxl.worksheet.worksheet import Worksheet

from src.writers._style import apply_row_style, autofit_columns, write_headers

HEADERS = [
    "Report Date", "Report Period", "Report Refresh Date",
    "Exchange", "OneDrive", "SharePoint", "Skype", "Yammer", "Teams",
]

_FIELDS = [
    "report_date", "report_period", "report_refresh_date",
    "exchange", "onedrive", "sharepoint", "skype", "yammer", "teams",
]


def write(ws: Worksheet, rows: list[dict]) -> None:
    write_headers(ws, HEADERS)

    if not rows:
        ws.cell(row=2, column=1, value="— No activity count data imported (set M365USAGE_ACTIVE_USERS_ACTIVITY) —")
    else:
        for i, r in enumerate(rows, start=2):
            for col, field in enumerate(_FIELDS, start=1):
                ws.cell(row=i, column=col, value=r.get(field))
            apply_row_style(ws, i, len(HEADERS))

    autofit_columns(ws, HEADERS)
