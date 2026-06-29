from openpyxl.worksheet.worksheet import Worksheet

from src.writers._style import apply_row_style, autofit_columns, write_headers

HEADERS = [
    "User Principal Name", "Display Name", "Product Type",
    "Last Activated Date", "Windows", "Mac", "iOS", "Android",
    "Windows 10 Mobile", "Shared Computer", "Report Refresh Date",
]

_FIELDS = [
    "user_principal_name", "display_name", "product_type",
    "last_activated_date", "windows", "mac", "ios", "android",
    "windows_10_mobile", "shared_computer", "report_refresh_date",
]

_BOOL_FIELDS = {"windows", "mac", "ios", "android", "windows_10_mobile", "shared_computer"}


def write(ws: Worksheet, rows: list[dict]) -> None:
    write_headers(ws, HEADERS)

    if not rows:
        ws.cell(row=2, column=1, value="— No activation data imported (set M365USAGE_ACTIVATIONS_USERS) —")
    else:
        for i, r in enumerate(rows, start=2):
            for col, field in enumerate(_FIELDS, start=1):
                v = r.get(field)
                ws.cell(row=i, column=col, value=("Yes" if v else "No") if field in _BOOL_FIELDS else v)
            apply_row_style(ws, i, len(HEADERS))

    autofit_columns(ws, HEADERS)
