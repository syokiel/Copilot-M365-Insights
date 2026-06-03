from datetime import timedelta

from azure.monitor.query import LogsQueryClient, LogsQueryStatus

# Copilot Studio emits to AppEvents (conversation turns) and AppDependencies
# (connector/action calls). OperationId is unpopulated; SessionId is the
# reliable correlation key across both tables.

_CONVERSATION_EVENTS_KQL = """
AppEvents
| extend props = parse_json(Properties)
| project
    Timestamp              = TimeGenerated,
    EventName              = Name,
    GenAiOperationName     = "invoke_agent",
    GenAiAgentId           = tostring(props["gen_ai.agent.id"]),
    GenAiAgentName         = tostring(props["gen_ai.agent.name"]),
    GenAiEnvironmentId     = tostring(props["gen_ai.environment.id"]),
    SessionId,
    UserId,
    ConversationId         = tostring(props["conversationId"]),
    ChannelId              = tostring(props["channelId"]),
    DesignMode             = tobool(props["DesignMode"]),
    TopicName              = tostring(props["TopicName"]),
    Text                   = tostring(props["text"]),
    Properties
| order by Timestamp desc
"""

_CONNECTOR_CALLS_KQL = """
AppDependencies
| where DependencyType == "Connector"
| extend props = parse_json(Properties)
| project
    Timestamp              = TimeGenerated,
    ConnectorName          = Name,
    GenAiOperationName     = "execute_tool",
    GenAiAgentId           = tostring(props["gen_ai.agent.id"]),
    GenAiAgentName         = tostring(props["gen_ai.agent.name"]),
    GenAiEnvironmentId     = tostring(props["gen_ai.environment.id"]),
    ActionTarget           = Target,
    SessionId,
    UserId,
    ConversationId         = tostring(props["conversationId"]),
    ChannelId              = tostring(props["channelId"]),
    DesignMode             = tobool(props["DesignMode"]),
    DurationMs,
    Success,
    ResultCode,
    Properties
| order by Timestamp desc
"""


class OtelFetcher:
    def __init__(
        self,
        client: LogsQueryClient,
        workspace_id: str,
        lookback: timedelta,
    ) -> None:
        self._client = client
        self._workspace_id = workspace_id
        self._lookback = lookback

    def _run_query(self, kql: str) -> list[dict]:
        response = self._client.query_workspace(
            workspace_id=self._workspace_id,
            query=kql,
            timespan=self._lookback,
        )
        if response.status == LogsQueryStatus.SUCCESS:
            table = response.tables[0]
        elif response.status == LogsQueryStatus.PARTIAL:
            table = response.partial_data[0]
        else:
            raise RuntimeError(f"Log Analytics query failed: {response.status}")

        columns = table.columns
        return [dict(zip(columns, row)) for row in table.rows]

    def fetch_conversation_events(self) -> list[dict]:
        """BotMessageReceived, BotMessageSend, TopicStart, etc. from AppEvents."""
        return self._run_query(_CONVERSATION_EVENTS_KQL)

    def fetch_connector_calls(self) -> list[dict]:
        """Connector/action calls (Teams, Outlook, etc.) from AppDependencies."""
        return self._run_query(_CONNECTOR_CALLS_KQL)
