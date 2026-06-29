from openpyxl.worksheet.worksheet import Worksheet

from src.writers._style import apply_row_style, autofit_columns, write_headers

HEADERS = [
    "Report Refresh Date", "Report Period",
    "Exchange Active", "Exchange Inactive",
    "OneDrive Active", "OneDrive Inactive",
    "SharePoint Active", "SharePoint Inactive",
    "Skype Active", "Skype Inactive",
    "Yammer Active", "Yammer Inactive",
    "Teams Active", "Teams Inactive",
    "Office 365 Active", "Office 365 Inactive",
]

_FIELDS = [
    "report_refresh_date", "report_period",
    "exchange_active", "exchange_inactive",
    "onedrive_active", "onedrive_inactive",
    "sharepoint_active", "sharepoint_inactive",
    "skype_active", "skype_inactive",
    "yammer_active", "yammer_inactive",
    "teams_active", "teams_inactive",
    "office365_active", "office365_inactive",
]


def write(ws: Worksheet, rows: list[dict]) -> None:
    write_headers(ws, HEADERS)

    if not rows:
        ws.cell(row=2, column=1, value="— No service count data imported (set M365USAGE_ACTIVE_USERS_SERVICES) —")
    else:
        for i, r in enumerate(rows, start=2):
            for col, field in enumerate(_FIELDS, start=1):
                ws.cell(row=i, column=col, value=r.get(field))
            apply_row_style(ws, i, len(HEADERS))

    autofit_columns(ws, HEADERS)
