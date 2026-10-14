"""一次性飞书用户授权（v2.5）。

为什么需要这一步：飞书的任务接口区分身份。用应用身份（tenant_access_token）
读「我负责的」任务，里面的「我」是应用自己，所以永远读不到你个人账号下的
任务；要读个人任务必须拿到用户身份令牌（user_access_token），而这只能由你
本人在浏览器里点一次「授权」。

用法：
    .\\.venv\\Scripts\\python.exe authorize-feishu.py              # 打开浏览器完成授权
    .\\.venv\\Scripts\\python.exe authorize-feishu.py --print-url  # 只打印授权链接，不自动打开
    .\\.venv\\Scripts\\python.exe authorize-feishu.py --status     # 查看本地令牌状态
    .\\.venv\\Scripts\\python.exe authorize-feishu.py --redirect-uri <URL>   # 换回调地址

前置条件：开发者后台「安全设置 → 重定向 URL」里要登记下面这个回调地址
（默认 http://localhost:8765/callback），否则飞书会拒绝回调。
"""

from __future__ import annotations

import argparse
import os
import socket
import sys
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from shared.config import load_env_file
from shared.errors import CollectorError
from shared.feishu_oauth import (
    DEFAULT_CALLBACK_PORT,
    DEFAULT_REDIRECT_URI,
    DEFAULT_TOKEN_FILE,
    TASK_SCOPES,
    UserTokenStore,
    build_authorize_url,
    build_legacy_authorize_url,
    exchange_code,
    hint_for_authorize_error,
    parse_callback_input,
)

STATE = "daily-report-authorize"
HEARTBEAT_SECONDS = 10.0

MANUAL_HELP = """手动模式（不启动本地回调服务）：
  1) 在浏览器里打开下面这条链接并点「授权」；
  2) 授权后地址栏会跳到 <回调地址>?code=... —— 页面显示"无法访问"是正常的，因为我们没在监听；
  3) 把地址栏里的整条链接复制粘贴到这里（只粘授权码也可以）。"""

SUCCESS_PAGE = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<title>授权成功</title></head>
<body style="font-family:-apple-system,'Microsoft YaHei',sans-serif;padding:48px;line-height:1.7">
<h1>授权成功</h1><p>令牌已写入本地文件，可以关闭本页并回到终端。</p></body></html>"""

FAILURE_PAGE = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<title>授权失败</title></head>
<body style="font-family:-apple-system,'Microsoft YaHei',sans-serif;padding:48px;line-height:1.7">
<h1>授权失败</h1><p>{reason}</p><p>请回到终端查看详细信息，然后重新运行 authorize-feishu.py。</p></body></html>"""


class _CallbackState:
    """回调处理器与主流程之间传递结果的小容器。"""

    code = ""
    state = ""
    error = ""
    finished = False


def _build_handler(callback_path: str, holder: _CallbackState):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib 约定
            parsed = urlparse(self.path)
            if parsed.path != callback_path:
                self.send_response(404)
                self.end_headers()
                return
            params = parse_qs(parsed.query)
            holder.code = (params.get("code") or [""])[0]
            holder.state = (params.get("state") or [""])[0]
            holder.error = (params.get("error") or [""])[0] or (
                (params.get("error_description") or [""])[0]
            )
            holder.finished = True
            body = FAILURE_PAGE.format(reason=holder.error) if holder.error else SUCCESS_PAGE
            payload = body.encode("utf-8")
            self.send_response(200 if not holder.error else 400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_args) -> None:
            """静音：不要把回调参数打进终端日志。"""

    return Handler


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    environment = {**load_env_file(Path(".env")), **os.environ}
    app_id = (environment.get("FEISHU_APP_ID") or "").strip()
    app_secret = (environment.get("FEISHU_APP_SECRET") or "").strip()
    store = UserTokenStore(args.token_file)

    if args.status:
        return _print_status(store)

    if not app_id or not app_secret:
        print(
            "[错误] 缺少 FEISHU_APP_ID 或 FEISHU_APP_SECRET，请先填到 .env",
            file=sys.stderr,
        )
        return 1

    # state 必须与下面校验用的是同一个值：这里统一传 STATE，避免"自己发出去的
    # state 和自己校验的 state 不一致"（v2.5.2 修）
    authorize_url = build_authorize_url(
        app_id, redirect_uri=args.redirect_uri, scope=args.scope, state=STATE
    )
    if args.print_url:
        print(authorize_url)
        return 0

    if args.clear:
        store.clear()
        print("[已清除] 本地的飞书用户令牌已删除。")
        return 0

    if args.manual:
        return _run_manual(app_id, app_secret, store, args, authorize_url)

    callback_path = urlparse(args.redirect_uri).path or "/callback"
    port = urlparse(args.redirect_uri).port or DEFAULT_CALLBACK_PORT

    print("[1/3] 回调地址：" + args.redirect_uri)
    print("      请确认它已登记在开发者后台「安全设置 → 重定向 URL」，否则飞书会拒绝回调。")
    print("[2/3] 正在打开浏览器；如果没自动打开，手动访问下面的链接：")
    print("      " + authorize_url)
    print("      如果上面这条在浏览器里报错，试这条旧版入口（手动复制到浏览器）：")
    print(
        "      "
        + build_legacy_authorize_url(app_id, redirect_uri=args.redirect_uri, state=STATE)
    )
    webbrowser.open(authorize_url)

    holder = _CallbackState()
    try:
        server = HTTPServer(("127.0.0.1", port), _build_handler(callback_path, holder))
    except OSError as exc:
        print(f"[错误] 无法监听 127.0.0.1:{port}（{exc}）。换个端口请用 --redirect-uri。", file=sys.stderr)
        return 1

    server.timeout = 1.0
    print("[3/3] 等待你在浏览器里点「授权」…（Ctrl+C 取消）")
    started = time.monotonic()
    last_note = 0.0
    try:
        while not holder.finished:
            server.handle_request()
            elapsed = time.monotonic() - started
            if not holder.finished and elapsed - last_note >= HEARTBEAT_SECONDS:
                last_note = elapsed
                print(f"      …仍在等待回调（已等 {int(elapsed)} 秒，Ctrl+C 取消）")
    except KeyboardInterrupt:
        print("\n[已取消] 没有完成授权。")
        return 1
    finally:
        server.server_close()

    if holder.error:
        print(f"[失败] 飞书返回错误：{holder.error}", file=sys.stderr)
        print("       " + hint_for_authorize_error(holder.error), file=sys.stderr)
        return 1
    if holder.state != STATE:
        print(f"[失败] state 不匹配（收到 {holder.state!r}），出于安全考虑已中止。", file=sys.stderr)
        return 1
    if not holder.code:
        print("[失败] 回调里没有授权码。", file=sys.stderr)
        return 1

    try:
        token = exchange_code(
            app_id,
            app_secret,
            holder.code,
            redirect_uri=args.redirect_uri,
        )
    except CollectorError as exc:
        print(f"[失败] {exc}", file=sys.stderr)
        return 1

    store.save(token)
    _report_success(store, token, args.scope)
    return 0


def _run_manual(app_id: str, app_secret: str, store: UserTokenStore, args, authorize_url: str) -> int:
    """手动粘贴授权码：不依赖浏览器能否把回调送到本机端口。"""

    print(MANUAL_HELP)
    print("      授权链接：" + authorize_url)
    print("      如果上面这条在浏览器里报错，再试旧版入口：")
    print(
        "      "
        + build_legacy_authorize_url(app_id, redirect_uri=args.redirect_uri, state=STATE)
    )
    print()
    print("      正在自动打开浏览器（没弹出来就手动打开上面那条链接；")
    print("      从终端复制长链接容易把折行一起复制进去，可以用 --print-url | Set-Clipboard）")
    webbrowser.open(authorize_url)
    print()
    try:
        pasted = input("把地址栏整条链接粘到这里 > ")
    except (EOFError, KeyboardInterrupt):
        print("\n[已取消] 没有完成授权。")
        return 1

    result = parse_callback_input(pasted)
    if result.error:
        print(f"[失败] 飞书返回错误：{result.error}", file=sys.stderr)
        print("       " + hint_for_authorize_error(result.error), file=sys.stderr)
        return 1
    if not result.code:
        print(
            "[失败] 没从粘贴内容里找到授权码。"
            "请回到浏览器，复制地址栏里那条带 code= 的完整链接。",
            file=sys.stderr,
        )
        return 1
    if result.state and result.state != STATE:
        print(
            f"[失败] state 不匹配（收到 {result.state!r}），出于安全考虑已中止。",
            file=sys.stderr,
        )
        return 1
    if not result.state:
        print("[提示] 粘贴内容里没有 state（可能被截断），手动模式下跳过校验。")

    try:
        token = exchange_code(
            app_id,
            app_secret,
            result.code,
            redirect_uri=args.redirect_uri,
        )
    except CollectorError as exc:
        print(f"[失败] {exc}", file=sys.stderr)
        return 1

    store.save(token)
    _report_success(store, token, args.scope)
    return 0


def _report_success(store: UserTokenStore, token, scope: str) -> None:
    print("[成功] 已拿到用户令牌并写入 " + str(store.path.resolve()))
    print("       权限范围：" + (token.scope or scope))
    if not token.refresh_token:
        print(
            "       [注意] 飞书这次没有返回续期令牌（refresh_token），这个令牌约 2 小时后失效，"
            "到期需要重新授权一次。"
        )
    print("       接下来直接跑日报（--dry-run 也行），「任务进展 · 飞书任务」就能读到")
    print("       你「我负责的」任务了。")


def _print_status(store: UserTokenStore) -> int:
    token = store.load()
    if token is None:
        print(
            "[未授权] 本地还没有用户令牌（"
            + str(store.path.resolve())
            + " 不存在），请运行 authorize-feishu.py 完成一次授权。"
        )
        return 0
    print("[已授权] 令牌文件：" + str(store.path.resolve()))
    print("       权限范围：" + (token.scope or "(未记录)"))
    print("       access_token 到期：" + token.expires_at.isoformat())
    print("       refresh_token 到期：" + (
        token.refresh_expires_at.isoformat() if token.refresh_expires_at else "(未知)"
    ))
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="一次性飞书用户授权（读个人任务用）")
    parser.add_argument("--redirect-uri", default=DEFAULT_REDIRECT_URI, help="回调地址，需与开发者后台登记一致")
    parser.add_argument("--scope", default=TASK_SCOPES, help="申请的权限范围，空格分隔")
    parser.add_argument("--token-file", default=str(DEFAULT_TOKEN_FILE), help="令牌落盘位置")
    parser.add_argument("--print-url", action="store_true", help="只打印授权链接，不打开浏览器")
    parser.add_argument("--status", action="store_true", help="查看本地令牌状态")
    parser.add_argument("--clear", action="store_true", help="清除本地令牌")
    parser.add_argument(
        "--manual",
        action="store_true",
        help="手动模式：不启动本地回调服务，自己把回调链接粘回来",
    )
    args = parser.parse_args(argv)
    if _is_port_taken(urlparse(args.redirect_uri).port or DEFAULT_CALLBACK_PORT) and not (
        args.print_url or args.status or args.clear or args.manual
    ):
        print(
            f"[提示] 端口 {urlparse(args.redirect_uri).port or DEFAULT_CALLBACK_PORT} 已被占用，"
            "可以换一个：--redirect-uri http://localhost:8766/callback",
            file=sys.stderr,
        )
    return args


def _is_port_taken(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.2)
        return probe.connect_ex(("127.0.0.1", port)) == 0


if __name__ == "__main__":
    raise SystemExit(main())
