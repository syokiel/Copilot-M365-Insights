"""Tokenomics: Copilot Studio credit consumption exports from the Power Platform Admin Center."""
import hashlib


def _capacity_consumption_row_id(r: dict) -> str:
    # Natural key (environment/resource/feature/channel/billable/date) isn't fully
    # unique — the same resource can appear twice on one date under a renamed
    # ResourceName, so fold that in too.
    key = (
        f"{r.get('environment_id')}|{r.get('resource_id')}|{r.get('resource_name')}|"
        f"{r.get('feature_name')}|{r.get('channel_id')}|{r.get('is_billable')}|{r.get('consumption_date')}"
    )
    return hashlib.sha1(key.encode()).hexdigest()


def _entitlement_per_agent_row_id(r: dict) -> str:
    key = (
        f"{r.get('agent_id')}|{r.get('ai_feature')}|{r.get('channel')}|"
        f"{r.get('tool_used')}|{r.get('scenario_name')}|{r.get('environment_id')}"
    )
    return hashlib.sha1(key.encode()).hexdigest()


class TokenomicsMixin:
    def upsert_tokenomics_capacity_consumption(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            self._begin_import('tokenomics_capacity_consumption', rows, snapshot=False)
            for r in rows:
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO tokenomics_capacity_consumption VALUES
                    (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        _capacity_consumption_row_id(r), r.get('tenant_id'), r.get('environment_id'),
                        r.get('environment_name'), r.get('environment_type'), r.get('resource_id'),
                        r.get('resource_name'), r.get('resource_type'), r.get('product_name'),
                        r.get('feature_name'), r.get('channel_id'), r.get('is_billable'),
                        r.get('unit'), r.get('consumption_date'), r.get('consumed_quantity'),
                    ),
                )
                written += cur.rowcount
        return written

    def fetch_tokenomics_capacity_consumption(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM tokenomics_capacity_consumption ORDER BY consumption_date DESC, environment_name"
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_tokenomics_entitlement_consumption(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            self._begin_import('tokenomics_entitlement_consumption', rows, snapshot=False)
            for r in rows:
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO tokenomics_entitlement_consumption VALUES
                    (?,?,?,?,?,?,?,?,?)""",
                    (
                        r.get('billing_plan_id'), r.get('billing_plan_name'), r.get('environment_id'),
                        r.get('environment_name'), r.get('capacity_type'), r.get('entitled_quantity'),
                        r.get('prepaid_consumed_quantity'), r.get('payg_consumed_quantity'),
                        r.get('usage_date'),
                    ),
                )
                written += cur.rowcount
        return written

    def fetch_tokenomics_entitlement_consumption(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM tokenomics_entitlement_consumption ORDER BY usage_date DESC, environment_name"
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_tokenomics_entitlement_per_agent(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            self._begin_import('tokenomics_entitlement_per_agent', rows, snapshot=True)
            for r in rows:
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO tokenomics_entitlement_per_agent VALUES
                    (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        _entitlement_per_agent_row_id(r),
                        r.get('agent_name'), r.get('agent_id'), r.get('product'),
                        r.get('ai_feature'), r.get('billed_credit'), r.get('non_billed_credit'),
                        r.get('channel'), r.get('knowledge_sources'), r.get('tool_used'),
                        r.get('llm_model'), r.get('scenario_name'),
                        r.get('environment_id'), r.get('environment_name'),
                    ),
                )
                written += cur.rowcount
        return written

    def fetch_tokenomics_entitlement_per_agent(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM tokenomics_entitlement_per_agent ORDER BY billed_credit DESC, agent_name"
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_tokenomics_entitlement_per_user(self, rows: list[dict]) -> int:
        written = 0
        with self._conn:
            self._begin_import('tokenomics_entitlement_per_user', rows, snapshot=True)
            for r in rows:
                cur = self._conn.execute(
                    """INSERT OR REPLACE INTO tokenomics_entitlement_per_user VALUES
                    (?,?,?,?,?,?,?)""",
                    (
                        r.get('user_id'), r.get('agent_id'), r.get('user_email'),
                        r.get('agent_name'), r.get('billable_credit_used'),
                        r.get('credits_used'), r.get('m365_copilot_licensed'),
                    ),
                )
                written += cur.rowcount
        return written

    def fetch_tokenomics_entitlement_per_user(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM tokenomics_entitlement_per_user ORDER BY credits_used DESC"
        ).fetchall()
        return [dict(r) for r in rows]

