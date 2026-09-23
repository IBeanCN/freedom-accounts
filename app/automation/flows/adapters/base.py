"""FlowAdapter: one class per login strategy, sync + async flavors.

Besides the login flow itself, an adapter MAY implement five optional
credential operations:

  - list_accounts   远端账号列表
  - get_account     指定远端账号详情
  - auth_link       获取账号授权链接（OAuth start）
  - redeem_token    兑换账号令牌（OAuth complete）
  - refresh_token   刷新账号令牌

Contract:
  - These operations are adapter capabilities, not adapter HTTP endpoints.
    They are invoked by internal services; refresh_token is additionally
    triggered by the account UI API.
  - Every call MUST append one row to the `adapter_logs` table via
    `alog.log_action` — logging is the only observable output.
  - `group` carries the group row: `id`, `login_url` (= upstream base URL),
    `upstream_key` (= upstream auth key).
"""
from typing import Callable


class FlowAdapter:
    """A pluggable login-flow strategy.

    Attributes:
        key:          stable identifier stored in groups.login_type (e.g. "cpr").
        label:        human-readable name for the frontend dropdown.
        run_sync:     sync flow  (executed on the cloakbrowser session thread).
        run_async:    async flow (native async Playwright contexts).

    Flow callable signature (both flavors):
        fn(ctx, username, password, totp_secret, login_url, steps) -> dict
    where `steps` is mutated in place with progress entries and the return
    value is the task result_json.
    """

    key: str = ""
    label: str = ""
    description: str = ""

    run_sync: Callable = None
    run_async: Callable = None

    # ---- optional credential operations (log-only, no API surface) ----------
    async def list_accounts(self, group: dict) -> dict:
        """List upstream accounts visible to this group's credential.

        Returns {"total": int, "accounts": [ {...}, ... ]} where each item
        SHOULD carry as much upstream identity as available: `id` (remote id),
        `name`/`email` (account name), `status`, `enabled`, `remark`.
        """
        raise NotImplementedError(f"{self.key} does not implement list_accounts")

    async def get_account(self, group: dict, remote_account_id: str) -> dict:
        """Fetch one upstream account's detail."""
        raise NotImplementedError(f"{self.key} does not implement get_account")

    async def auth_link(self, group: dict, name: str,
                        remote_account_id: str | None = None) -> dict:
        """Start an authorization flow; returns {flow_id, url, expires_at}."""
        raise NotImplementedError(f"{self.key} does not implement auth_link")

    async def redeem_token(self, group: dict, flow_id: str, callback_url: str) -> dict:
        """Complete an authorization flow (exchange callback for tokens)."""
        raise NotImplementedError(f"{self.key} does not implement redeem_token")

    async def refresh_token(self, group: dict, remote_account_id: str) -> dict:
        """Refresh one upstream account's access token."""
        raise NotImplementedError(f"{self.key} does not implement refresh_token")

    @classmethod
    def manifest(cls) -> dict:
        return {"key": cls.key, "label": cls.label, "description": cls.description}
