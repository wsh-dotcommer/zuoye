"""HTTP 客户端与错误处理策略（design.md §4.1、§6.1）。

超时重试、限流等待这两条非功能约束统一在这里实现，采集器只关心业务字段。
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from datetime import datetime, timezone
from typing import Any

import httpx

from shared.errors import CollectorError
from shared.feishu_oauth import UserTokenProvider
from shared.logger import JsonLineLogger, build_logger

GITHUB_API = "https://api.github.com"
FEISHU_API = "https://open.feishu.cn"

TOKEN_PATH = "/open-apis/auth/v3/tenant_access_token/internal"


class GitHubClient:
    """带重试与限流等待的 GitHub REST 客户端。"""

    def __init__(
        self,
        token: str = "",
        *,
        base_url: str = GITHUB_API,
        retry_times: int = 3,
        retry_interval: float = 5.0,
        rate_limit_max_wait: float = 300.0,
        timeout: float = 15.0,
        per_page: int = 100,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        logger: JsonLineLogger | None = None,
    ) -> None:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "daily-report/1.0",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._client = httpx.Client(
            base_url=base_url,
            headers=headers,
            timeout=timeout,
            transport=transport,
        )
        self.retry_times = max(0, retry_times)
        self.retry_interval = max(0.0, retry_interval)
        self.rate_limit_max_wait = max(0.0, rate_limit_max_wait)
        self.per_page = per_page
        self._sleep = sleep
        self._logger = logger or build_logger(None)
        self._auth_configured = bool(token)

    @property
    def auth_configured(self) -> bool:
        return self._auth_configured

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> GitHubClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        response = self._get(path, params)
        try:
            return response.json()
        except ValueError as exc:  # pragma: no cover - 非 JSON 响应分支
            raise CollectorError(f"GitHub 返回内容不是合法 JSON: {path}") from exc

    def paginate(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        per_page: int | None = None,
        max_pages: int = 20,
    ) -> Iterator[Any]:
        """按 page 参数翻页，直到某页返回数量不足 per_page。"""

        page_size = per_page or self.per_page
        page = 1
        while page <= max_pages:
            merged = dict(params or {})
            merged["page"] = page
            merged["per_page"] = page_size
            payload = self.get_json(path, merged)
            if not isinstance(payload, list):
                raise CollectorError(f"期望列表响应，实际得到 {type(payload).__name__}: {path}")
            yield from payload
            if len(payload) < page_size:
                return
            page += 1

    def _get(self, path: str, params: dict[str, Any] | None) -> httpx.Response:
        attempt = 0
        while True:
            attempt += 1
            try:
                response = self._client.get(path, params=params)
            except httpx.HTTPError as exc:
                self._retry_or_raise(
                    attempt,
                    path,
                    f"请求异常 {type(exc).__name__}: {exc}",
                )
                continue

            if self._is_rate_limited(response):
                wait = self._rate_limit_wait(response)
                self._logger.error(
                    "github_rate_limited",
                    path=path,
                    attempt=attempt,
                    wait_seconds=round(wait, 1),
                )
                self._retry_or_raise(attempt, path, "GitHub API 限流", sleep_seconds=wait)
                continue

            if response.status_code >= 500:
                self._retry_or_raise(attempt, path, f"服务端错误 {response.status_code}")
                continue

            if response.status_code >= 400:
                snippet = response.text[:200].replace("\n", " ")
                raise CollectorError(f"GitHub API {response.status_code}: {path} {snippet}")

            return response

    def _retry_or_raise(
        self,
        attempt: int,
        path: str,
        reason: str,
        *,
        sleep_seconds: float | None = None,
    ) -> None:
        if attempt > self.retry_times:
            raise CollectorError(f"{reason}（已重试 {self.retry_times} 次）: {path}")
        wait = self.retry_interval if sleep_seconds is None else sleep_seconds
        self._sleep(wait)

    def _is_rate_limited(self, response: httpx.Response) -> bool:
        if response.status_code not in (403, 429):
            return False
        if response.headers.get("X-RateLimit-Remaining") == "0":
            return True
        if response.headers.get("Retry-After"):
            return True
        return "rate limit" in response.text.lower()

    def _rate_limit_wait(self, response: httpx.Response) -> float:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return min(float(retry_after), self.rate_limit_max_wait)
            except ValueError:
                pass
        reset = response.headers.get("X-RateLimit-Reset")
        if reset:
            try:
                return min(max(float(reset) - time.time() + 1.0, 1.0), self.rate_limit_max_wait)
            except ValueError:
                pass
        return min(self.retry_interval, self.rate_limit_max_wait)


def parse_timestamp(value: str) -> datetime:
    """解析 GitHub 返回的 ISO 8601 时间（含 Z 后缀）。"""

    if not value:
        raise CollectorError("缺少时间字段")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class FeishuClient:
    """飞书开放平台客户端（v2.3，只读数据源用）。

    与 `GitHubClient` 共用同一套超时重试策略，但认证方式不同：
    先用 app_id/app_secret 换 `tenant_access_token`（单次运行取一次并缓存），
    之后每个请求带 `Authorization: Bearer <token>`。

    v2.5 起支持「用户身份」：传入 `user_token_provider` 后，`as_user=True`
    的请求用 `user_access_token`（读「我负责的」任务必须走这条，见
    `shared/feishu_oauth.py` 的说明）。
    """

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        *,
        base_url: str = FEISHU_API,
        retry_times: int = 3,
        retry_interval: float = 5.0,
        timeout: float = 15.0,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        logger: JsonLineLogger | None = None,
        user_token_provider: UserTokenProvider | None = None,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url,
            headers={"User-Agent": "daily-report/1.0"},
            timeout=timeout,
            transport=transport,
        )
        self._app_id = app_id
        self._app_secret = app_secret
        self._token = ""
        self.retry_times = max(0, retry_times)
        self.retry_interval = max(0.0, retry_interval)
        self._sleep = sleep
        self._logger = logger or build_logger(None)
        self._user_tokens = user_token_provider

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> FeishuClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    @property
    def auth_configured(self) -> bool:
        return bool(self._app_id and self._app_secret)

    def tenant_access_token(self) -> str:
        """换取（并缓存）tenant_access_token；失败抛 CollectorError。"""

        if self._token:
            return self._token
        payload = self._request(
            "POST",
            TOKEN_PATH,
            json={"app_id": self._app_id, "app_secret": self._app_secret},
        )
        token = str(payload.get("tenant_access_token") or "") if isinstance(payload, dict) else ""
        if not token:
            detail = payload.get("msg") if isinstance(payload, dict) else payload
            raise CollectorError(f"飞书未返回 tenant_access_token: {detail}")
        self._token = token
        return token

    @property
    def user_token_configured(self) -> bool:
        """是否已配置用户令牌提供者且本地确实有过授权。"""

        return self._user_tokens is not None and self._user_tokens.has_token

    def access_token(self, *, as_user: bool = False) -> str:
        """按身份取令牌：用户身份读个人数据，应用身份读应用可见范围。"""

        if not as_user:
            return self.tenant_access_token()
        if self._user_tokens is None:
            raise CollectorError("本次调用要求用户身份，但没有配置用户令牌提供者")
        return self._user_tokens.access_token()

    def get_json(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        as_user: bool = False,
    ) -> Any:
        """GET 并校验飞书业务返回码（`code != 0` 视为失败）。"""

        payload = self._request(
            "GET",
            path,
            params=params,
            headers={"Authorization": f"Bearer {self.access_token(as_user=as_user)}"},
        )
        if isinstance(payload, dict):
            code = payload.get("code")
            if code not in (0, None):
                raise CollectorError(f"飞书 API 错误 {code}: {payload.get('msg', '')} {path}")
            return payload.get("data")
        return payload

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        attempt = 0
        while True:
            attempt += 1
            try:
                response = self._client.request(
                    method, path, params=params, json=json, headers=headers
                )
            except httpx.HTTPError as exc:
                self._retry_or_raise(attempt, path, f"请求异常 {type(exc).__name__}: {exc}")
                continue

            if response.status_code >= 500:
                self._retry_or_raise(attempt, path, f"飞书服务端错误 {response.status_code}")
                continue

            if response.status_code >= 400:
                snippet = response.text[:200].replace("\n", " ")
                raise CollectorError(f"飞书 API {response.status_code}: {path} {snippet}")

            try:
                return response.json()
            except ValueError as exc:
                raise CollectorError(f"飞书返回内容不是合法 JSON: {path}") from exc

    def _retry_or_raise(self, attempt: int, path: str, reason: str) -> None:
        if attempt > self.retry_times:
            raise CollectorError(f"{reason}（已重试 {self.retry_times} 次）: {path}")
        self._logger.error("feishu_request_retry", path=path, attempt=attempt, reason=reason)
        self._sleep(self.retry_interval)


def to_github_time(moment: datetime) -> str:
    """把 datetime 转成 GitHub API 需要的 UTC ISO 字符串。"""

    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
