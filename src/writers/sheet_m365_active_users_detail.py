from openpyxl.worksheet.worksheet import Worksheet

from src.writers._style import apply_row_style, autofit_columns, write_headers

HEADERS = [
    "User Principal Name", "Display Name", "Is Deleted",
    "Has Exchange", "Has OneDrive", "Has SharePoint", "Has Skype", "Has Yammer", "Has Teams",
    "Exchange Last Activity", "OneDrive Last Activity", "SharePoint Last Activity",
    "Skype Last Activity", "Yammer Last Activity", "Teams Last Activity",
    "Exchange License Date", "OneDrive License Date", "SharePoint License Date",
    "Skype License Date", "Yammer License Date", "Teams License Date",
    "Assigned Products", "Deleted Date", "Report Refresh Date",
]

_FIELDS = [
    "user_principal_name", "display_name", "is_deleted",
    "has_exchange", "has_onedrive", "has_sharepoint", "has_skype", "has_yammer", "has_teams",
    "exchange_last_activity", "onedrive_last_activity", "sharepoint_last_activity",
    "skype_last_activity", "yammer_last_activity", "teams_last_activity",
    "exchange_license_date", "onedrive_license_date", "sharepoint_license_date",
    "skype_license_date", "yammer_license_date", "teams_license_date",
    "assigned_products", "deleted_date", "report_refresh_date",
]

_BOOL_FIELDS = {
    "is_deleted", "has_exchange", "has_onedrive", "has_sharepoint",
    "has_skype", "has_yammer", "has_teams",
}


def write(ws: Worksheet, rows: list[dict]) -> None:
    write_headers(ws, HEADERS)

    if not rows:
        ws.cell(row=2, column=1, value="— No user detail data imported (set M365USAGE_ACTIVE_USERS_DETAIL) —")
    else:
        for i, r in enumerate(rows, start=2):
            for col, field in enumerate(_FIELDS, start=1):
                v = r.get(field)
                ws.cell(row=i, column=col, value=("Yes" if v else "No") if field in _BOOL_FIELDS else v)
            apply_row_style(ws, i, len(HEADERS))

    autofit_columns(ws, HEADERS)
