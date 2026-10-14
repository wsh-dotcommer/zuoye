"""飞书用户授权测试（v2.5）：拼授权链接、换令牌、续期与本地存储。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from shared.errors import CollectorError
from shared.feishu_oauth import (
    APP_ACCESS_TOKEN_PATH,
    OIDC_REFRESH_PATH,
    OIDC_TOKEN_PATH,
    TOKEN_PATH,
    UserToken,
    UserTokenProvider,
    UserTokenStore,
    parse_callback_input,
    build_authorize_url,
    build_legacy_authorize_url,
    exchange_code,
    hint_for_authorize_error,
    refresh_user_token,
)


def _token_payload(access: str = "u-1", refresh: str = "ur-1", expires_in: int = 7200) -> dict:
    return {
        "code": 0,
        "access_token": access,
        "refresh_token": refresh,
        "expires_in": expires_in,
        "refresh_token_expires_in": 2592000,
        "scope": "task:task:read task:tasklist:read",
    }


V1_DATA = {
    "access_token": "u-v1",
    "refresh_token": "ur-v1",
    "expires_in": 7200,
    "refresh_token_expires_in": 2592000,
    "scope": "task:task:read",
}


def _router(
    seen: list[httpx.Request],
    *,
    v1_ok: bool = True,
    v2_ok: bool = True,
    v2_payload: dict | None = None,
):
    """按路径分发的 Mock：覆盖旧版 OIDC 与新版 OAuth 两条路。"""

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        path = request.url.path
        if path == APP_ACCESS_TOKEN_PATH:
            if not v1_ok:
                return httpx.Response(200, json={"code": 99991, "msg": "app not found"})
            return httpx.Response(200, json={"code": 0, "app_access_token": "a-1"})
        if path == OIDC_TOKEN_PATH:
            return httpx.Response(200, json={"code": 0, "msg": "success", "data": V1_DATA})
        if path == OIDC_REFRESH_PATH:
            return httpx.Response(200, json={"code": 0, "data": {**V1_DATA, "access_token": "u-v1-new"}})
        if path == TOKEN_PATH:
            if not v2_ok:
                return httpx.Response(200, json={"code": 20004, "msg": "code expired"})
            return httpx.Response(200, json=v2_payload if v2_payload is not None else _token_payload())
        return httpx.Response(404, json={"code": 1, "msg": "not found"})

    return httpx.MockTransport(handler)


def test_build_authorize_url_carries_app_and_redirect() -> None:
    url = build_authorize_url("cli_demo", redirect_uri="http://localhost:8765/callback")

    assert url.startswith("https://accounts.feishu.cn/open-apis/authen/v1/authorize?")
    assert "client_id=cli_demo" in url
    assert "redirect_uri=http%3A%2F%2Flocalhost%3A8765%2Fcallback" in url
    assert "scope=task%3Atask%3Aread+task%3Atasklist%3Aread" in url
    # 显式传入的 state 必须原样出现在链接里——脚本就是拿它回校验的
    assert "state=custom-state" in build_authorize_url("cli_demo", state="custom-state")
    assert (
        "state=custom-state"
        in build_legacy_authorize_url("cli_demo", state="custom-state")
    )


def test_legacy_authorize_url_uses_app_id_param() -> None:
    url = build_legacy_authorize_url("cli_demo")

    assert url.startswith("https://open.feishu.cn/open-apis/authen/v1/index?")
    assert "app_id=cli_demo" in url
    assert "redirect_uri=http%3A%2F%2Flocalhost%3A8765%2Fcallback" in url


# ===== v2.5：手动模式粘贴内容的解析 =====


def test_parse_callback_input_accepts_full_url() -> None:
    result = parse_callback_input(
        "http://localhost:8765/callback?code=abc-123_XYZ&state=daily-report"
    )

    assert result.code == "abc-123_XYZ"
    assert result.state == "daily-report"
    assert result.error == ""


def test_parse_callback_input_accepts_query_only_and_bare_code() -> None:
    assert parse_callback_input("code=abc&state=daily-report").code == "abc"
    assert parse_callback_input("abc123").code == "abc123"
    # 粘贴时常见的多余引号/空白
    assert parse_callback_input('  "abc123"  ').code == "abc123"


def test_parse_callback_input_extracts_error() -> None:
    result = parse_callback_input(
        "http://localhost:8765/callback?error=access_denied&error_description=user+denied"
    )

    assert result.code == ""
    assert "access_denied" in result.error
    assert "denied" in result.error


def test_parse_callback_input_ignores_garbage() -> None:
    assert parse_callback_input("").code == ""
    assert parse_callback_input("这不是链接 也不是码").code == ""


def test_hint_for_authorize_error_maps_common_cases() -> None:
    assert "重定向 URL" in hint_for_authorize_error("invalid redirect_uri")
    assert "用户身份" in hint_for_authorize_error("scope not granted")
    assert "拒绝" in hint_for_authorize_error("access_denied")
    assert "发给我" in hint_for_authorize_error("something weird")


def test_exchange_code_prefers_v1_oidc() -> None:
    """默认先走旧版 OIDC：先换 app_access_token，再换用户令牌（稳定带 refresh_token）。"""

    seen: list[httpx.Request] = []

    token = exchange_code("cli_demo", "app-secret", "code-1", transport=_router(seen))

    assert token.access_token == "u-v1"
    assert token.refresh_token == "ur-v1"
    assert token.usable()
    assert [request.url.path for request in seen] == [APP_ACCESS_TOKEN_PATH, OIDC_TOKEN_PATH]
    assert b"authorization_code" in seen[1].read()


def test_exchange_code_falls_back_to_v2_when_v1_fails() -> None:
    """旧版拿不到 app_access_token 时，自动退回新版 OAuth 端点。"""

    seen: list[httpx.Request] = []

    token = exchange_code("cli_demo", "app-secret", "code-1", transport=_router(seen, v1_ok=False))

    assert token.access_token == "u-1"
    assert TOKEN_PATH in [request.url.path for request in seen]


def test_exchange_code_without_refresh_token_still_succeeds() -> None:
    """新版端点可能只给 access_token——不能整体判失败，令牌要留下。"""

    payload = {
        "code": 0,
        "token_type": "Bearer",
        "access_token": "u-only",
        "expires_in": 7200,
        "scope": "task:task:read",
    }

    token = exchange_code(
        "cli_demo",
        "app-secret",
        "code-1",
        transport=_router([], v1_ok=False, v2_payload=payload),
    )

    assert token.access_token == "u-only"
    assert token.refresh_token == ""
    assert token.usable()


def test_exchange_code_reports_both_flows_on_failure() -> None:
    seen: list[httpx.Request] = []

    with pytest.raises(CollectorError) as excinfo:
        exchange_code("cli_demo", "app-secret", "bad", transport=_router(seen, v1_ok=False, v2_ok=False))

    message = str(excinfo.value)
    assert "旧版 OIDC" in message and "新版 OAuth" in message


def test_refresh_user_token_prefers_v1_oidc() -> None:
    seen: list[httpx.Request] = []

    token = refresh_user_token("cli_demo", "app-secret", "ur-old", transport=_router(seen))

    assert token.access_token == "u-v1-new"
    assert OIDC_REFRESH_PATH in [request.url.path for request in seen]


def test_token_store_round_trip_and_missing_file(tmp_path: Path) -> None:
    store = UserTokenStore(tmp_path / "token.json")
    assert store.load() is None

    token = UserToken(
        access_token="u-1",
        refresh_token="ur-1",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        scope="task:task:read",
    )
    store.save(token)

    loaded = store.load()
    assert loaded is not None
    assert (loaded.access_token, loaded.refresh_token) == ("u-1", "ur-1")

    store.clear()
    assert store.load() is None


def test_token_store_ignores_broken_file(tmp_path: Path) -> None:
    path = tmp_path / "token.json"
    path.write_text("{不是 JSON", encoding="utf-8")

    assert UserTokenStore(path).load() is None


def test_provider_without_token_raises_actionable_error(tmp_path: Path) -> None:
    provider = UserTokenProvider("cli_demo", "app-secret", UserTokenStore(tmp_path / "none.json"))

    assert provider.has_token is False
    with pytest.raises(CollectorError) as excinfo:
        provider.access_token()

    assert "authorize-feishu.py" in str(excinfo.value)


def test_provider_reuses_valid_token_and_refreshes_expired_one(tmp_path: Path) -> None:
    path = tmp_path / "token.json"
    store = UserTokenStore(path)
    seen: list[httpx.Request] = []

    # 1) 有效期还够：直接用，不发请求
    store.save(
        UserToken(
            access_token="u-alive",
            refresh_token="ur-1",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
    )
    provider = UserTokenProvider("cli_demo", "app-secret", store, transport=_router(seen))
    assert provider.access_token() == "u-alive"
    assert seen == []

    # 2) 快过期了：自动续期并写回文件
    store.save(
        UserToken(
            access_token="u-stale",
            refresh_token="ur-1",
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=10),
        )
    )
    fresh = UserTokenProvider("cli_demo", "app-secret", store, transport=_router(seen))
    assert fresh.access_token() == "u-v1-new"
    assert [request.url.path for request in seen] == [APP_ACCESS_TOKEN_PATH, OIDC_REFRESH_PATH]
    assert store.load().access_token == "u-v1-new"  # 新令牌已写回


def test_provider_without_refresh_token_warns_when_expired(tmp_path: Path) -> None:
    """只有 access_token（无续期令牌）时：有效期内可用，过期后提示重新授权。"""

    store = UserTokenStore(tmp_path / "token.json")
    store.save(
        UserToken(
            access_token="u-only",
            refresh_token="",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
    )
    provider = UserTokenProvider("cli_demo", "app-secret", store, transport=_router([]))
    assert provider.has_token is True
    assert provider.access_token() == "u-only"

    store.save(
        UserToken(
            access_token="u-only",
            refresh_token="",
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        )
    )
    expired = UserTokenProvider("cli_demo", "app-secret", store, transport=_router([]))
    with pytest.raises(CollectorError) as excinfo:
        expired.access_token()

    assert "authorize-feishu.py" in str(excinfo.value)
