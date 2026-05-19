from pathlib import Path

import openpyxl

from src.writers import (
    sheet_agents,
    sheet_connectors,
    sheet_dlp,
    sheet_environments,
    sheet_invocations,
    sheet_publishers,
    sheet_summary,
)


def build_workbook(
    events: list[dict],
    connector_calls: list[dict],
    output_path: str,
    bots: list[dict] | None = None,
    environments: list[dict] | None = None,
    publishers: list[dict] | None = None,
    dlp_policies: list[dict] | None = None,
) -> None:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    sheet_summary.write(wb.create_sheet("Summary"), events, connector_calls)
    sheet_invocations.write(wb.create_sheet("Invocations"), events, connector_calls)
    sheet_connectors.write(wb.create_sheet("Connectors"), connector_calls)
    sheet_agents.write(wb.create_sheet("Agents"), bots or [])
    sheet_environments.write(wb.create_sheet("Environments"), environments or [])
    sheet_publishers.write(wb.create_sheet("Publishers"), publishers or [])
    sheet_dlp.write(wb.create_sheet("DLP Policies"), dlp_policies or [])

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)
    print(f"Saved: {output_path}")
