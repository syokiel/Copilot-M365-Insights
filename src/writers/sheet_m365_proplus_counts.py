from openpyxl.worksheet.worksheet import Worksheet

from src.writers._style import apply_row_style, autofit_columns, write_headers

HEADERS = [
    "Report Date", "Report Period", "Report Refresh Date",
    "Outlook", "Word", "Excel", "PowerPoint", "OneNote", "Teams",
]

_FIELDS = [
    "report_date", "report_period", "report_refresh_date",
    "outlook", "word", "excel", "powerpoint", "onenote", "teams",
]


def write(ws: Worksheet, rows: list[dict]) -> None:
    write_headers(ws, HEADERS)

    if not rows:
        ws.cell(row=2, column=1, value="— No ProPlus app count data imported (set M365USAGE_PROPLUS_COUNTS) —")
    else:
        for i, r in enumerate(rows, start=2):
            for col, field in enumerate(_FIELDS, start=1):
                ws.cell(row=i, column=col, value=r.get(field))
            apply_row_style(ws, i, len(HEADERS))

    autofit_columns(ws, HEADERS)
