from openpyxl.worksheet.worksheet import Worksheet

from src.writers._style import apply_row_style, autofit_columns, write_headers

HEADERS = [
    "Product Title", "Total Licenses", "Assigned Licenses", "Available Licenses",
    "% Assigned", "Expired Licenses", "Status Message",
]


def write(ws: Worksheet, rows: list[dict]) -> None:
    write_headers(ws, HEADERS)

    if not rows:
        ws.cell(row=2, column=1, value="— No license data imported (set BILLING_LICENCES) —")
    else:
        for i, r in enumerate(rows, start=2):
            total = r.get("total_licenses")
            assigned = r.get("assigned_licenses")
            available = total - assigned if total is not None and assigned is not None else None
            pct = assigned / total if total and assigned is not None else None
            values = [
                r.get("product_title"), total, assigned, available, pct,
                r.get("expired_licenses"), r.get("status_message"),
            ]
            for col, value in enumerate(values, start=1):
                cell = ws.cell(row=i, column=col, value=value)
                if col in (2, 3, 4, 6):
                    cell.number_format = "#,##0"
            apply_row_style(ws, i, len(HEADERS))
            ws.cell(row=i, column=5).number_format = "0.0%"

    autofit_columns(ws, HEADERS)
