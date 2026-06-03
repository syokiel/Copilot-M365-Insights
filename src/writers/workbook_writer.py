from pathlib import Path

import openpyxl

from src.writers import (
    sheet_agents,
    sheet_ai_usage,
    sheet_az_health,
    sheet_connectors,
    sheet_crossref,
    sheet_dlp,
    sheet_environments,
    sheet_invocations,
    sheet_m365_copilot,
    sheet_publishers,
    sheet_summary,
    sheet_teams_usage,
)


def build_workbook(
    events: list[dict],
    connector_calls: list[dict],
    output_path: str,
    agents: list[dict] | None = None,
    environments: list[dict] | None = None,
    publishers: list[dict] | None = None,
    dlp_policies: list[dict] | None = None,
    agent_solutions: list[dict] | None = None,
    aad_users: dict[str, dict] | None = None,
    model_calls: list[dict] | None = None,
    health_detail: list[dict] | None = None,
    crossref_summary: list[dict] | None = None,
    copilot_usage: list[dict] | None = None,
    teams_usage: list[dict] | None = None,
) -> None:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    sheet_summary.write(wb.create_sheet("Summary"), events, connector_calls, model_calls or [])
    sheet_invocations.write(wb.create_sheet("Invocations"), events, connector_calls)
    sheet_connectors.write(wb.create_sheet("Connectors"), connector_calls)
    sheet_ai_usage.write(wb.create_sheet("AI_Model_Calls"), model_calls or [])
    sheet_agents.write(wb.create_sheet("Agents"), agents or [], environments or [], agent_solutions or [], aad_users or {})
    sheet_environments.write(wb.create_sheet("Environments"), environments or [])
    sheet_publishers.write(wb.create_sheet("Publishers"), publishers or [])
    sheet_dlp.write(wb.create_sheet("DLP Policies"), dlp_policies or [])
    sheet_m365_copilot.write(wb.create_sheet("M365_Copilot_Usage"), copilot_usage or [])
    sheet_teams_usage.write(wb.create_sheet("Teams_Usage"), teams_usage or [])
    sheet_az_health.write(wb.create_sheet("AzureMonitor_Health"), health_detail or [])
    sheet_crossref.write(wb.create_sheet("CrossRef_Summary"), crossref_summary or [])

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)
    print(f"Saved: {output_path}")
