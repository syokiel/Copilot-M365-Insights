"""
Viva / Copilot Studio analytics CSV report importer.

Reads the standard export files from the Copilot Studio analytics portal
and converts them to lists of dicts for the SQLite store.

Supported files (resolved case-insensitively from the given directory):
  AgentSessionMetrics.Csv
  AgentTopicMetrics.Csv
  AgentKnowledgeSourceMetrics.Csv
  AgentAutonomousMetrics_by_AgentId_MetricDate.Csv
  AgentAutonomousMetrics_by_AgentId_TriggerSchemaName_MetricDate.Csv
  AgentActionMetrics.Csv
  CopilotAgent.Csv
  AgentWeeklyActiveUsers.Csv
  AgentExtendedMetadata.Csv
"""
import csv
import re
from pathlib import Path


# ── helpers ───────────────────────────────────────────────────────────────────

def _norm_date(v: str) -> str:
    """Normalise any of the date formats used across these CSVs to YYYY-MM-DD."""
    if not v or not v.strip():
        return ''
    v = v.strip()
    # Already ISO  →  keep first 10 chars
    if re.match(r'^\d{4}-\d{2}-\d{2}', v):
        return v[:10]
    # M/D/YY  or  MM/DD/YY  or  MM/DD/YYYY
    m = re.match(r'^(\d{1,2})/(\d{1,2})/(\d{2,4})$', v)
    if m:
        mo, day, yr = m.groups()
        if len(yr) == 2:
            yr = '20' + yr
        return f"{yr}-{mo.zfill(2)}-{day.zfill(2)}"
    return v


def _int(v) -> int | None:
    try:
        s = str(v).strip()
        return int(s) if s else None
    except (ValueError, TypeError):
        return None


def _float(v) -> float | None:
    try:
        s = str(v).strip()
        return float(s) if s else None
    except (ValueError, TypeError):
        return None


# ── importer ──────────────────────────────────────────────────────────────────

class VivaReportImporter:
    """Reads Copilot Studio analytics CSV exports from a directory on disk."""

    _FILES = {
        'session':            'AgentSessionMetrics.Csv',
        'topic':              'AgentTopicMetrics.Csv',
        'knowledge':          'AgentKnowledgeSourceMetrics.Csv',
        'autonomous':         'AgentAutonomousMetrics_by_AgentId_MetricDate.Csv',
        'autonomous_trigger': 'AgentAutonomousMetrics_by_AgentId_TriggerSchemaName_MetricDate.Csv',
        'action':             'AgentActionMetrics.Csv',
        'agents':             'CopilotAgent.Csv',
        'wau':                'AgentWeeklyActiveUsers.Csv',
        'extended':           'AgentExtendedMetadata.Csv',
    }

    def __init__(self, report_dir: str) -> None:
        self._dir = Path(report_dir)

    def _read(self, key: str) -> list[dict]:
        filename = self._FILES[key]
        stem = Path(filename).stem   # e.g. "AgentSessionMetrics"

        candidates = [
            self._dir / filename,              # flat:   dir/AgentSessionMetrics.Csv
            self._dir / stem / filename,       # nested: dir/AgentSessionMetrics/AgentSessionMetrics.Csv
        ]

        p = None
        for c in candidates:
            if c.exists():
                p = c
                break

        if p is None:
            # Case-insensitive search — flat and one level deep
            for entry in self._dir.rglob('*'):
                if entry.is_file() and entry.name.lower() == filename.lower():
                    p = entry
                    break

        if p is None:
            return []

        with open(p, newline='', encoding='utf-8-sig') as fh:
            return list(csv.DictReader(fh))

    # ── session metrics ───────────────────────────────────────────────────────

    def fetch_session_metrics(self) -> list[dict]:
        out = []
        for r in self._read('session'):
            out.append({
                'agent_id':               r.get('AgentId', ''),
                'metric_date':            _norm_date(r.get('MetricDate', '')),
                'total_sessions':         _int(r.get('Total sessions')),
                'resolved_sessions':      _int(r.get('Number of resolved sessions')),
                'escalated_sessions':     _int(r.get('Number of escalated sessions')),
                'abandoned_sessions':     _int(r.get('Number of abandoned sessions')),
                'engaged_sessions':       _int(r.get('Number of engaged sessions')),
                'unengaged_sessions':     _int(r.get('Number of unengaged sessions')),
                'csat_responses':         _int(r.get('Number of CSAT responses')),
                'csat_1':                 _int(r.get('Number of responses with CSAT rating of 1')),
                'csat_2':                 _int(r.get('Number of responses with CSAT rating of 2')),
                'csat_3':                 _int(r.get('Number of responses with CSAT rating of 3')),
                'csat_4':                 _int(r.get('Number of responses with CSAT rating of 4')),
                'csat_5':                 _int(r.get('Number of responses with CSAT rating of 5')),
                'avg_duration_all':       _float(r.get('Average duration of all sessions')),
                'avg_duration_unengaged': _float(r.get('Average duration of unengaged sessions')),
                'avg_duration_engaged':   _float(r.get('Average duration of engaged sessions')),
                'avg_duration_resolved':  _float(r.get('Average duration of resolved sessions')),
                'avg_duration_escalated': _float(r.get('Average duration of escalated sessions')),
                'avg_duration_abandoned': _float(r.get('Average duration of abandoned sessions')),
                'ks_engaged':             _int(r.get('Number of engaged sessions with knowledge sources used')),
                'ks_unengaged':           _int(r.get('Number of unengaged sessions with knowledge sources used')),
                'ks_resolved':            _int(r.get('Number of resolved sessions with knowledge sources used')),
                'ks_escalated':           _int(r.get('Number of escalated sessions with knowledge sources used')),
                'ks_abandoned':           _int(r.get('Number of abandoned sessions with knowledge sources used')),
            })
        return out

    # ── topic metrics ─────────────────────────────────────────────────────────

    def fetch_topic_metrics(self) -> list[dict]:
        out = []
        for r in self._read('topic'):
            out.append({
                'agent_id':           r.get('AgentId', ''),
                'topic_id':           r.get('TopicId', ''),
                'topic_name':         r.get('TopicName', ''),
                'metric_date':        _norm_date(r.get('MetricDate', '')),
                'total_sessions':     _int(r.get('Total number of sessions per topic')),
                'resolved_sessions':  _int(r.get('Total number of resolved sessions per topic')),
                'escalated_sessions': _int(r.get('Total number of escalated sessions per topic')),
                'abandoned_sessions': _int(r.get('Total number of abandoned sessions per topic')),
                'engaged_sessions':   _int(r.get('Total number of engaged sessions per topic')),
                'unengaged_sessions': _int(r.get('Total number of unengaged sessions per topic')),
                'csat_responses':     _int(r.get('Number of CSAT responses per topic')),
                'csat_1':             _int(r.get('Number of responses with CSAT rating of 1 per topic')),
                'csat_2':             _int(r.get('Number of responses with CSAT rating of 2 per topic')),
                'csat_3':             _int(r.get('Number of responses with CSAT rating of 3 per topic')),
                'csat_4':             _int(r.get('Number of responses with CSAT rating of 4 per topic')),
                'csat_5':             _int(r.get('Number of responses with CSAT rating of 5 per topic')),
            })
        return out

    # ── knowledge source metrics ──────────────────────────────────────────────

    def fetch_knowledge_source_metrics(self) -> list[dict]:
        out = []
        for r in self._read('knowledge'):
            out.append({
                'agent_id':                  r.get('AgentId', ''),
                'source_type':               r.get('KnowledgeSourceType', ''),
                'metric_date':               _norm_date(r.get('MetricDate', '')),
                'count_total':               _int(r.get('Count of knowledge source in total sessions')),
                'count_unengaged':           _int(r.get('Count of knowledge source in unengaged sessions')),
                'count_engaged':             _int(r.get('Count of knowledge source in engaged sessions')),
                'count_resolved':            _int(r.get('Count of knowledge source in resolved sessions')),
                'count_escalated':           _int(r.get('Count of knowledge source in escalated sessions')),
                'count_abandoned':           _int(r.get('Count of knowledge source in abandoned sessions')),
                'count_autonomous':          _int(r.get('Count of Knowledge sources in autonomous runs')),
                'count_successful_autonomous': _int(r.get('Count of Knowledge sources in successful autonomous runs')),
            })
        return out

    # ── autonomous metrics (agent × date) ─────────────────────────────────────

    def fetch_autonomous_metrics(self) -> list[dict]:
        out = []
        for r in self._read('autonomous'):
            out.append({
                'agent_id':            r.get('AgentId', ''),
                'metric_date':         _norm_date(r.get('MetricDate', '')),
                'total_runs':          _int(r.get('Total Autonomous Runs')),
                'successful_runs':     _int(r.get('Number of successful runs')),
                'failed_runs':         _int(r.get('Number of failed runs')),
                'total_duration':      _float(r.get('Total duration of all runs')),
                'successful_duration': _float(r.get('Total duration of all successful runs')),
                'failed_duration':     _float(r.get('Total duration of all failed runs')),
                'ks_successful':       _int(r.get('Number of successful runs with knowledge sources used')),
                'ks_failed':           _int(r.get('Number of failed runs with knowledge sources used')),
                'actions_successful':  _int(r.get('Number of successful runs with actions used')),
                'actions_failed':      _int(r.get('Number of failed runs with actions used')),
                'no_op_successful':    _int(r.get('Number of successful runs with no external operations')),
                'no_op_failed':        _int(r.get('Number of failed runs with no external operations')),
            })
        return out

    # ── autonomous metrics (agent × trigger × date) ───────────────────────────

    def fetch_autonomous_trigger_metrics(self) -> list[dict]:
        out = []
        for r in self._read('autonomous_trigger'):
            out.append({
                'agent_id':            r.get('AgentId', ''),
                'trigger_schema_name': r.get('TriggerSchemaName', ''),
                'metric_date':         _norm_date(r.get('MetricDate', '')),
                'total_runs':          _int(r.get('Total Autonomous Runs per trigger')),
                'successful_runs':     _int(r.get('Number of successful runs per trigger')),
                'failed_runs':         _int(r.get('Number of failed runs per trigger')),
                'total_duration':      _float(r.get('Total duration of all runs per trigger')),
                'successful_duration': _float(r.get('Total duration of all successful runs per trigger')),
                'failed_duration':     _float(r.get('Total duration of all failed runs per trigger')),
                'ks_successful':       _int(r.get('Number of successful runs with knowledge sources used per trigger')),
                'ks_failed':           _int(r.get('Number of failed runs with knowledge sources used per trigger')),
                'actions_successful':  _int(r.get('Number of successful runs with actions used per trigger')),
                'actions_failed':      _int(r.get('Number of failed runs with actions used per trigger')),
                'no_op_successful':    _int(r.get('Number of successful runs where no operation ( use of an action or knowledge source access) was done per trigger')),
                'no_op_failed':        _int(r.get('Number of failed runs where no operation ( use of an action or knowledge source access) was done per trigger')),
            })
        return out

    # ── action metrics ────────────────────────────────────────────────────────

    def fetch_action_metrics(self) -> list[dict]:
        out = []
        for r in self._read('action'):
            out.append({
                'agent_id':                              r.get('AgentId', ''),
                'action_schema_name':                    r.get('ActionSchemaName', ''),
                'metric_date':                           _norm_date(r.get('MetricDate', '')),
                'total_runs':                            _int(r.get('Total Runs per action')),
                'successful_actions_in_runs':            _int(r.get('Number of successful actions in runs')),
                'actions_in_successful_runs':            _int(r.get('Number of actions in successful runs')),
                'successful_actions_in_successful_runs': _int(r.get('Number of successful actions in successful runs')),
            })
        return out

    # ── copilot agent catalog ─────────────────────────────────────────────────

    def fetch_copilot_agents(self) -> list[dict]:
        out = []
        for r in self._read('agents'):
            out.append({
                'agent_id':        r.get('AgentId', ''),
                'agent_name':      r.get('AgentName', ''),
                'description':     r.get('AgentDescription', ''),
                'surface':         r.get('AgentSurface', ''),
                'mode':            r.get('AgentMode', ''),
                'categories':      r.get('AgentCategories', ''),
                'agent_type':      r.get('AgentType', ''),
                'is_included':     1 if str(r.get('AgentIncluded', '')).upper() == 'TRUE' else 0,
                'excluded_reason': r.get('AgentExcludedReason', ''),
                'icon':            r.get('AgentIcon', ''),
            })
        return out

    # ── weekly active users ───────────────────────────────────────────────────

    def fetch_weekly_active_users(self) -> list[dict]:
        out = []
        for r in self._read('wau'):
            out.append({
                'agent_id':          r.get('AgentId', ''),
                'start_date':        _norm_date(r.get('StartDate', '')),
                'active_user_count': _int(r.get('ActiveUserCount')),
            })
        return out

    # ── extended metadata (ROI) ───────────────────────────────────────────────

    def fetch_extended_metadata(self) -> list[dict]:
        out = []
        for r in self._read('extended'):
            out.append({
                'agent_id':          r.get('AgentId', ''),
                'aad_tenant_id':     r.get('AadTenantId', ''),
                'roi_configuration': r.get('RoiConfiguration', ''),
            })
        return out
