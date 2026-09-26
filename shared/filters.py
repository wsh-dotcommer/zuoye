"""采集层共用的过滤规则（design.md §6.2）。

机器人账号（GitHub Actions、评审机器人等）不属于团队成员，
默认排除，避免日报被噪声淹没；可通过配置 ``exclude_bots: false`` 关闭。
"""

from __future__ import annotations

BOT_LOGIN_SUFFIX = "[bot]"


def is_bot(login: str, user_type: str = "") -> bool:
    """判断一个 GitHub 账号是否是机器人。"""

    if (user_type or "").strip().lower() == "bot":
        return True
    return (login or "").strip().lower().endswith(BOT_LOGIN_SUFFIX)
