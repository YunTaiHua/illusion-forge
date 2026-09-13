"""
更新检查子命令
==============

提供 IllusionForge 的版本检查功能。发行渠道为 GitHub Releases（Windows
安装包，桌面版内置 electron-updater 自动更新），因此本命令只做"检查 +
指引下载"，不再通过 pip 就地升级。

子命令:
    - update: 检查是否有新版本
"""
from __future__ import annotations

import typer

from illusion_forge.cli import app
from illusion_forge.config.i18n import t


@app.command("update")
def update_cmd() -> None:
    """检查 IllusionForge 是否有新版本 / Check for a newer IllusionForge release

    查询 GitHub Releases 最新版本并与当前版本比较；有新版本时给出下载指引。
    """
    from packaging.version import InvalidVersion, Version

    from illusion_forge.commands.misc import (
        RELEASES_PAGE_URL,
        _check_latest_release,
        _get_current_version,
    )

    current = _get_current_version()
    print(t("update_checking"))
    latest = _check_latest_release()
    if latest is None:
        print(t("update_network_error"))
        raise typer.Exit(1)

    try:
        has_update = Version(latest) > Version(current)
    except InvalidVersion:
        has_update = latest != current

    if not has_update:
        print(t("update_latest", version=current))
        return

    print(t("update_available", current=current, latest=latest))
    print(t("update_download_hint", url=RELEASES_PAGE_URL))
