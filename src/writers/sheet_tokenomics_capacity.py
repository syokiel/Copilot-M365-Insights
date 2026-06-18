from openpyxl.worksheet.worksheet import Worksheet

from src.writers._style import apply_row_style, autofit_columns, write_headers

HEADERS = [
    "Environment Name", "Environment Type", "Resource Name", "Resource Type",
    "Product Name", "Feature Name", "Channel", "Is Billable", "Unit",
    "Consumption Date", "Consumed Quantity",
]

_FIELDS = [
    "environment_name", "environment_type", "resource_name", "resource_type",
    "product_name", "feature_name", "channel_id", "is_billable", "unit",
    "consumption_date", "consumed_quantity",
]


def _yn(v) -> str:
    return "Yes" if v else ("No" if v is not None else "")


def write(ws: Worksheet, rows: list[dict]) -> None:
    write_headers(ws, HEADERS)

    if not rows:
        ws.cell(row=2, column=1, value="— No capacity consumption data imported (set PPADMIN_LICENSES_CS_CONSUMPTION_MANAGEAGENTS) —")
    else:
        for i, r in enumerate(rows, start=2):
            for col, field in enumerate(_FIELDS, start=1):
                value = _yn(r.get(field)) if field == "is_billable" else r.get(field)
                ws.cell(row=i, column=col, value=value)
            apply_row_style(ws, i, len(HEADERS))

    autofit_columns(ws, HEADERS)
