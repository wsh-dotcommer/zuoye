"""飞书用户授权与用户令牌管理（v2.5）。

为什么需要它：飞书的任务接口区分「应用身份」和「用户身份」。用
`tenant_access_token`（应用身份）读「我负责的」任务，里面的「我」指的是
应用自己，因此永远读不到个人工作台里的任务；要读个人任务必须拿到
`user_access_token`（用户身份），而这需要用户本人走一次 OAuth 授权。

本模块只做三件事：拼授权链接、用授权码换令牌、用 refresh_token 续期。
令牌存在本地文件里（默认 `data/feishu-user-token.json`，`data/` 已在
`.gitignore` 中），不进版本库、不进日志。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs

import httpx

from shared.errors import CollectorError

# 授权页（v2 域名）与换取令牌的接口
AUTHORIZE_ENDPOINT = "https://accounts.feishu.cn/open-apis/authen/v1/authorize"
# 旧版授权页：新版入口报错时用它兜底（参数名不同：app_id 而非 client_id）
LEGACY_AUTHORIZE_ENDPOINT = "https://open.feishu.cn/open-apis/authen/v1/index"
TOKEN_PATH = "/open-apis/authen/v2/oauth/token"
# 旧版 OIDC 换令牌（稳定返回 refresh_token）与它需要的 app_access_token
APP_ACCESS_TOKEN_PATH = "/open-apis/auth/v3/app_access_token/internal"
OIDC_TOKEN_PATH = "/open-apis/authen/v1/oidc/access_token"
OIDC_REFRESH_PATH = "/open-apis/authen/v1/oidc/refresh_access_token"
DEFAULT_BASE_URL = "https://open.feishu.cn"

# 本地一次性的回调地址（需在开发者后台「安全设置 → 重定向 URL」登记）
DEFAULT_REDIRECT_URI = "http://localhost:8765/callback"
DEFAULT_CALLBACK_PORT = 8765
DEFAULT_TOKEN_FILE = Path("data/feishu-user-token.json")

# 任务读取所需的用户身份权限
TASK_SCOPES = "task:task:read task:tasklist:read"

# access_token 剩余有效期低于该秒数就提前续期
REFRESH_MARGIN_SECONDS = 300


@dataclass(frozen=True)
class CallbackResult:
    """从"回调 URL 或裸授权码"里解析出来的三样东西。"""

    code: str = ""
    state: str = ""
    error: str = ""


def parse_callback_input(text: str) -> CallbackResult:
    """解析手动模式粘贴进来的内容（v2.5）。

    接受三种写法：整条回调链接（`http://localhost:8765/callback?code=...&state=...`）、
    只有查询串（`code=...&state=...`）、以及只有授权码本身。
    带了 `error` / `error_description` 时把错误原文返回，调用方据此给提示。
    """

    raw = (text or "").strip().strip('"').strip("'").strip()
    if not raw:
        return CallbackResult()

    if "?" in raw:
        query = raw.split("?", 1)[1]
    elif "=" in raw:
        query = raw
    else:
        # 裸授权码：中间不该有空白，有的话说明粘错了东西
        if any(char.isspace() for char in raw):
            return CallbackResult()
        return CallbackResult(code=raw)

    params = parse_qs(query.split("#", 1)[0])
    code = (params.get("code") or [""])[0].strip()
    state = (params.get("state") or [""])[0].strip()
    error = (params.get("error") or [""])[0].strip()
    description = (params.get("error_description") or [""])[0].strip()
    return CallbackResult(code=code, state=state, error=error or description)


def hint_for_authorize_error(text: str) -> str:
    """把飞书返回的授权错误翻译成"下一步该干什么"。"""

    lowered = (text or "").lower()
    if "redirect" in lowered:
        return (
            "重定向 URL 对不上：请到开发者后台「安全设置 → 重定向 URL」登记 "
            f"{DEFAULT_REDIRECT_URI}（必须和脚本里的一致）"
        )
    if "scope" in lowered or "permission" in lowered or "权限" in text:
        return (
            "权限不足：请在权限管理里把 task:task:read 与 task:tasklist:read 的"
            "「用户身份」版本也开通，然后重新发布版本"
        )
    if "access_denied" in lowered or "denied" in lowered:
        return "你在授权页点了拒绝。重新运行脚本，这次点「授权」。"
    if "app" in lowered and ("not" in lowered or "disable" in lowered):
        return "应用状态异常：请在开发者后台重新发布一版应用"
    return "把这段错误原文发给我，我来判断是哪一步的问题"


@dataclass(frozen=True)
class UserToken:
    """一次用户授权换来的令牌对。"""

    access_token: str
    refresh_token: str
    expires_at: datetime
    refresh_expires_at: datetime | None = None
    scope: str = ""

    @property
    def expired(self) -> bool:
        return datetime.now(timezone.utc) >= self.expires_at

    def usable(self, margin_seconds: int = REFRESH_MARGIN_SECONDS) -> bool:
        """access_token 还够不够用（留出续期余量）。"""

        return datetime.now(timezone.utc) + timedelta(seconds=margin_seconds) < self.expires_at

    def to_json(self) -> dict[str, Any]:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at.isoformat(),
            "refresh_expires_at": (
                self.refresh_expires_at.isoformat() if self.refresh_expires_at else ""
            ),
            "scope": self.scope,
        }

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> UserToken:
        return cls(
            access_token=str(payload.get("access_token") or ""),
            refresh_token=str(payload.get("refresh_token") or ""),
            expires_at=_parse_moment(payload.get("expires_at")),
            refresh_expires_at=(
                _parse_moment(payload["refresh_expires_at"])
                if payload.get("refresh_expires_at")
                else None
            ),
            scope=str(payload.get("scope") or ""),
        )


class UserTokenStore:
    """把用户令牌落在本地文件里；文件不存在就表示还没授权过。"""

    def __init__(self, path: str | Path = DEFAULT_TOKEN_FILE) -> None:
        self.path = Path(path)

    def load(self) -> UserToken | None:
        if not self.path.exists():
            return None
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        # 只要求 access_token：新版端点可能不给 refresh_token，那种情况仍应可用
        if not isinstance(payload, dict) or not payload.get("access_token"):
            return None
        return UserToken.from_json(payload)

    def save(self, token: UserToken) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(token.to_json(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()


def build_authorize_url(
    app_id: str,
    *,
    redirect_uri: str = DEFAULT_REDIRECT_URI,
    scope: str = TASK_SCOPES,
    state: str = "daily-report",
) -> str:
    """拼出让用户在浏览器里打开的授权页地址（scope 用空格分隔）。"""

    params = httpx.QueryParams(
        {
            "client_id": app_id,
            "redirect_uri": redirect_uri,
            "scope": scope,
            "state": state,
            "response_type": "code",
        }
    )
    return f"{AUTHORIZE_ENDPOINT}?{params}"


def build_legacy_authorize_url(
    app_id: str,
    *,
    redirect_uri: str = DEFAULT_REDIRECT_URI,
    state: str = "daily-report",
) -> str:
    """旧版授权页地址（v1 index 入口）。

    新版 `accounts.feishu.cn` 入口在应用缺少「网页应用」能力时可能报错，
    此时让用户手动打开这一条作为兜底。
    """

    params = httpx.QueryParams({"app_id": app_id, "redirect_uri": redirect_uri, "state": state})
    return f"{LEGACY_AUTHORIZE_ENDPOINT}?{params}"


def exchange_code(
    app_id: str,
    app_secret: str,
    code: str,
    *,
    redirect_uri: str = DEFAULT_REDIRECT_URI,
    base_url: str = DEFAULT_BASE_URL,
    timeout: float = 15.0,
    transport: httpx.BaseTransport | None = None,
) -> UserToken:
    """用授权码换用户令牌（授权码只能用一次、有效期 5 分钟）。

    先走旧版 OIDC 端点（稳定返回 refresh_token），失败再退回新版 OAuth 端点。
    实测新版在未声明离线访问时只给 access_token，因此把它当兜底。
    """

    errors: list[str] = []
    try:
        payload = _post_token_v1(
            app_id, app_secret, code, base_url=base_url, timeout=timeout, transport=transport
        )
        return _to_token(payload)
    except CollectorError as exc:
        errors.append(f"旧版 OIDC：{exc}")

    try:
        payload = _post_token(
            base_url,
            {
                "grant_type": "authorization_code",
                "client_id": app_id,
                "client_secret": app_secret,
                "code": code,
                "redirect_uri": redirect_uri,
            },
            timeout=timeout,
            transport=transport,
        )
        return _to_token(payload)
    except CollectorError as exc:
        errors.append(f"新版 OAuth：{exc}")

    raise CollectorError("飞书授权失败 —— " + "；".join(errors))


def refresh_user_token(
    app_id: str,
    app_secret: str,
    refresh_token: str,
    *,
    base_url: str = DEFAULT_BASE_URL,
    timeout: float = 15.0,
    transport: httpx.BaseTransport | None = None,
) -> UserToken:
    """用 refresh_token 换新的令牌对（refresh_token 有效期 30 天）。

    与 `exchange_code` 对称：先试旧版 OIDC 续期端点，失败再试新版。
    """

    errors: list[str] = []
    try:
        app_token = _app_access_token(
            app_id, app_secret, base_url=base_url, timeout=timeout, transport=transport
        )
        payload = _request_json(
            "POST",
            base_url.rstrip("/") + OIDC_REFRESH_PATH,
            json={"grant_type": "refresh_token", "refresh_token": refresh_token},
            headers={"Authorization": f"Bearer {app_token}"},
            timeout=timeout,
            transport=transport,
        )
        return _to_token(payload)
    except CollectorError as exc:
        errors.append(f"旧版 OIDC：{exc}")

    try:
        payload = _post_token(
            base_url,
            {
                "grant_type": "refresh_token",
                "client_id": app_id,
                "client_secret": app_secret,
                "refresh_token": refresh_token,
            },
            timeout=timeout,
            transport=transport,
        )
        return _to_token(payload)
    except CollectorError as exc:
        errors.append(f"新版 OAuth：{exc}")

    raise CollectorError("飞书续期失败 —— " + "；".join(errors))


def _post_token_v1(
    app_id: str,
    app_secret: str,
    code: str,
    *,
    base_url: str,
    timeout: float,
    transport: httpx.BaseTransport | None,
) -> dict[str, Any]:
    """旧版 OIDC：要先用 app_id/app_secret 换 app_access_token，再换用户令牌。"""

    app_token = _app_access_token(
        app_id, app_secret, base_url=base_url, timeout=timeout, transport=transport
    )
    return _request_json(
        "POST",
        base_url.rstrip("/") + OIDC_TOKEN_PATH,
        json={"grant_type": "authorization_code", "code": code},
        headers={"Authorization": f"Bearer {app_token}"},
        timeout=timeout,
        transport=transport,
    )


def _app_access_token(
    app_id: str,
    app_secret: str,
    *,
    base_url: str,
    timeout: float,
    transport: httpx.BaseTransport | None,
) -> str:
    payload = _request_json(
        "POST",
        base_url.rstrip("/") + APP_ACCESS_TOKEN_PATH,
        json={"app_id": app_id, "app_secret": app_secret},
        timeout=timeout,
        transport=transport,
    )
    token = str(payload.get("app_access_token") or "")
    if not token:
        raise CollectorError(f"飞书未返回 app_access_token：{payload}")
    return token


class UserTokenProvider:
    """按需给出可用的 user_access_token：进程内缓存，过期前自动续期。

    续期成功后会把新令牌写回 store——飞书的 refresh_token 每次续期都会换新的，
    不写回下次就失效了。
    """

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        store: UserTokenStore,
        *,
        base_url: str = DEFAULT_BASE_URL,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._app_id = app_id
        self._app_secret = app_secret
        self._store = store
        self._base_url = base_url
        self._transport = transport
        self._cached: UserToken | None = None

    @property
    def has_token(self) -> bool:
        """本地是否已有过授权（只看文件，不发请求）。"""

        return self._cached is not None or self._store.load() is not None

    def access_token(self) -> str:
        return self._current().access_token

    def _current(self) -> UserToken:
        if self._cached is not None and self._cached.usable():
            return self._cached
        stored = self._cached or self._store.load()
        if stored is None:
            raise CollectorError(
                "还没有飞书用户授权：先运行 authorize-feishu.py 完成一次授权"
                "（读个人任务必须用 user_access_token，应用身份读不到）"
            )
        if stored.usable():
            self._cached = stored
            return stored
        if not stored.refresh_token:
            raise CollectorError(
                "飞书用户令牌已过期，且这次授权没有拿到续期令牌（refresh_token）；"
                "请重新运行 authorize-feishu.py 再授权一次"
            )
        refreshed = refresh_user_token(
            self._app_id,
            self._app_secret,
            stored.refresh_token,
            base_url=self._base_url,
            transport=self._transport,
        )
        self._store.save(refreshed)
        self._cached = refreshed
        return refreshed


def _post_token(
    base_url: str,
    body: dict[str, Any],
    *,
    timeout: float,
    transport: httpx.BaseTransport | None,
) -> dict[str, Any]:
    return _request_json(
        "POST",
        base_url.rstrip("/") + TOKEN_PATH,
        json=body,
        timeout=timeout,
        transport=transport,
    )


def _request_json(
    method: str,
    url: str,
    *,
    json: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float,
    transport: httpx.BaseTransport | None,
) -> dict[str, Any]:
    """发一次请求并要求飞书返回 `code == 0`；任何异常都翻译成 CollectorError。"""

    try:
        with httpx.Client(timeout=timeout, transport=transport) as client:
            response = client.request(method, url, json=json, headers=headers)
    except httpx.HTTPError as exc:
        raise CollectorError(f"飞书授权请求失败：{type(exc).__name__}: {exc}") from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise CollectorError(f"飞书授权返回内容不是合法 JSON：HTTP {response.status_code}") from exc
    if not isinstance(payload, dict):
        raise CollectorError(f"飞书授权返回结构异常：{payload!r}")

    code = payload.get("code")
    if code not in (0, None) or payload.get("error"):
        detail = (
            payload.get("error_description")
            or payload.get("msg")
            or payload.get("error")
            or payload
        )
        raise CollectorError(f"飞书授权失败（code={code}）：{detail}")
    return payload


def _to_token(payload: dict[str, Any]) -> UserToken:
    """把飞书的返回转成 UserToken。

    兼容两种形态：新版 OAuth 是扁平结构，旧版 OIDC 把令牌放在 `data` 里。
    refresh_token 缺失时**不再整体判失败**——实测新版端点在不声明离线访问时
    只给 access_token，这时仍把令牌收下（有效期内可用），由调用方提示重新授权。
    """

    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    access_token = str(data.get("access_token") or "")
    refresh_token = str(data.get("refresh_token") or "")
    if not access_token:
        raise CollectorError(f"飞书授权未返回 access_token：{payload}")

    now = datetime.now(timezone.utc)
    expires_in = _as_int(data.get("expires_in"), default=7200)
    refresh_expires_in = _as_int(data.get("refresh_token_expires_in"), default=0)
    return UserToken(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=now + timedelta(seconds=max(expires_in, 60)),
        refresh_expires_at=(
            now + timedelta(seconds=refresh_expires_in) if refresh_expires_in else None
        ),
        scope=str(data.get("scope") or ""),
    )


def _as_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_moment(value: Any) -> datetime:
    text = str(value or "").strip()
    if text:
        try:
            moment = datetime.fromisoformat(text)
        except ValueError:
            moment = None
        if moment is not None:
            return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
    return datetime.fromtimestamp(time.time(), tz=timezone.utc)
