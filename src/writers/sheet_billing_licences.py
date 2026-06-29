from openpyxl.worksheet.worksheet import Worksheet

from src.writers._style import apply_row_style, autofit_columns, write_headers

HEADERS = [
    "Product Title", "Total Licenses", "Assigned Licenses",
    "Expired Licenses", "Status Message",
]

_FIELDS = [
    "product_title", "total_licenses", "assigned_licenses",
    "expired_licenses", "status_message",
]


def write(ws: Worksheet, rows: list[dict]) -> None:
    write_headers(ws, HEADERS)

    if not rows:
        ws.cell(row=2, column=1, value="— No license data imported (set BILLING_LICENCES) —")
    else:
        for i, r in enumerate(rows, start=2):
            for col, field in enumerate(_FIELDS, start=1):
                ws.cell(row=i, column=col, value=r.get(field))
            apply_row_style(ws, i, len(HEADERS))

    autofit_columns(ws, HEADERS)
