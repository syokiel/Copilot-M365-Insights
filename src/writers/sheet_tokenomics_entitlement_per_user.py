from openpyxl.worksheet.worksheet import Worksheet

from src.writers._style import apply_row_style, autofit_columns, write_headers

HEADERS = [
    "User Email", "Agent Name",
    "Billable Credit Used", "Credits Used", "M365 Copilot Licensed",
]

_FIELDS = [
    "user_email", "agent_name",
    "billable_credit_used", "credits_used", "m365_copilot_licensed",
]


def _yn(v) -> str:
    return "Yes" if v else ("No" if v is not None else "")


def write(ws: Worksheet, rows: list[dict]) -> None:
    write_headers(ws, HEADERS)

    if not rows:
        ws.cell(row=2, column=1, value="— No per-user entitlement data imported (set PPADMIN_LICENSES_CS_CONSUMPTION_USER) —")
    else:
        for i, r in enumerate(rows, start=2):
            for col, field in enumerate(_FIELDS, start=1):
                value = _yn(r.get(field)) if field == "m365_copilot_licensed" else r.get(field)
                ws.cell(row=i, column=col, value=value)
            apply_row_style(ws, i, len(HEADERS))

    autofit_columns(ws, HEADERS)
