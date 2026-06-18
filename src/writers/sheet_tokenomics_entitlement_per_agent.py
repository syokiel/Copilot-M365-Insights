from openpyxl.worksheet.worksheet import Worksheet

from src.writers._style import apply_row_style, autofit_columns, write_headers

HEADERS = [
    "Agent Name", "Product", "AI Feature / Billable Feature",
    "Billed Credit", "Non-Billed Credit", "Channel",
    "Tool Used", "LLM Model", "Scenario Name",
    "Environment Name",
]

_FIELDS = [
    "agent_name", "product", "ai_feature",
    "billed_credit", "non_billed_credit", "channel",
    "tool_used", "llm_model", "scenario_name",
    "environment_name",
]


def write(ws: Worksheet, rows: list[dict]) -> None:
    write_headers(ws, HEADERS)

    if not rows:
        ws.cell(row=2, column=1, value="— No per-agent entitlement data imported (set PPADMIN_LICENSES_CS_CONSUMPTION_AGENT) —")
    else:
        for i, r in enumerate(rows, start=2):
            for col, field in enumerate(_FIELDS, start=1):
                ws.cell(row=i, column=col, value=r.get(field))
            apply_row_style(ws, i, len(HEADERS))

    autofit_columns(ws, HEADERS)
