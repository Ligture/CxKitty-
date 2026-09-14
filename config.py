"""配置加载与全局访问

``config.yml`` 使用 v2 分段格式(结构定义见 ``config_schema.py``,
完整说明见 ``docs/configuration.md``); 旧版 v1 扁平格式仍可读取,
启动时提示迁移: ``python scripts/migrate_config.py``。

本模块把配置导出为常量供全局使用, 例如 ``config.WORK`` / ``config.SEARCHERS``。
所有字段都会先用 ``config_schema.DEFAULTS`` 补齐并校验, 因此各处下标访问安全。
"""

from __future__ import annotations

import copy
import warnings
from pathlib import Path
from typing import Any

import yaml

import config_schema as schema

CONFIG_PATH = Path("config.yml")


def load(path: str | Path = CONFIG_PATH) -> dict[str, Any]:
    """读取并规范化配置文件

    Args:
        path: 配置文件路径

    Returns:
        v2 结构的完整配置, 缺失字段已用默认值补齐
    """
    path = Path(path)
    raw: Any = {}
    if path.is_file():
        with path.open("r", encoding="utf8") as fp:
            raw = yaml.load(fp, yaml.FullLoader)
    else:
        warnings.warn(f"未找到配置文件 {path}, 已使用默认配置", RuntimeWarning)

    if isinstance(raw, dict) and raw and not schema.is_v2(raw):
        warnings.warn(
            f"{path} 仍是 v1 扁平格式, 已自动兼容; "
            "建议执行 `python scripts/migrate_config.py` 迁移到 v2 分段格式",
            RuntimeWarning,
        )

    conf, problems = schema.normalize(raw)
    for problem in problems:
        warnings.warn(f"{path}: {problem}", RuntimeWarning)
    return conf


CONF: dict[str, Any] = load()


def as_dict() -> dict[str, Any]:
    """返回当前配置的深拷贝(调试 / 迁移脚本使用)"""
    return copy.deepcopy(CONF)


# -------------------- 目录 --------------------
SESSIONS_PATH = Path(CONF["paths"]["session"])
LOGS_PATH = Path(CONF["paths"]["logs"])
EXPORT_PATH = Path(CONF["paths"]["export"])
FACE_PATH = Path(CONF["paths"]["faces"])
if not EXPORT_PATH.exists():
    EXPORT_PATH.mkdir(parents=True, exist_ok=True)

# -------------------- 网络代理 --------------------
HTTP_EN: bool = CONF["proxy"]["enable"]
HTTP: str = CONF["proxy"]["http"]
HTTPS: str = CONF["proxy"]["https"]

# -------------------- 运行 / 界面 --------------------
MULTI_SESS: bool = CONF["runtime"]["multi_session"]
TUI_MAX_HEIGHT: int | None = CONF["runtime"]["tui_max_height"]
MASKACC: bool = CONF["runtime"]["mask_acc"]
FETCH_UPLOADED_FACE: bool = CONF["runtime"]["fetch_uploaded_face"]

# -------------------- 刷课任务 --------------------
VIDEO: dict = CONF["tasks"]["video"]
WORK: dict = CONF["tasks"]["work"]
DOCUMENT: dict = CONF["tasks"]["document"]
EXAM: dict = CONF["tasks"]["exam"]

VIDEO_EN: bool = VIDEO["enable"]
WORK_EN: bool = WORK["enable"]
DOCUMENT_EN: bool = DOCUMENT["enable"]

VIDEO_WAIT: int = VIDEO["wait"]
WORK_WAIT: int = WORK["wait"]
DOCUMENT_WAIT: int = DOCUMENT["wait"]

VIDEO_DOWNLOAD: bool = VIDEO["download"]

# -------------------- 视频转录管道 --------------------
TRANSCRIPT: dict = CONF["transcript"]
TRANSCRIPT_EN: bool = TRANSCRIPT["enable"]

# -------------------- 搜索器 --------------------
SEARCHERS: list[dict] = CONF["searchers"]["items"]
SEARCHER_DEFAULTS: dict = CONF["searchers"]["defaults"]

__all__ = [
    "CONFIG_PATH",
    "CONF",
    "as_dict",
    "load",
    "SESSIONS_PATH",
    "LOGS_PATH",
    "EXPORT_PATH",
    "FACE_PATH",
    "HTTP_EN",
    "HTTP",
    "HTTPS",
    "MULTI_SESS",
    "TUI_MAX_HEIGHT",
    "MASKACC",
    "FETCH_UPLOADED_FACE",
    "VIDEO",
    "WORK",
    "DOCUMENT",
    "EXAM",
    "VIDEO_EN",
    "WORK_EN",
    "DOCUMENT_EN",
    "VIDEO_WAIT",
    "WORK_WAIT",
    "DOCUMENT_WAIT",
    "VIDEO_DOWNLOAD",
    "TRANSCRIPT",
    "TRANSCRIPT_EN",
    "SEARCHERS",
    "SEARCHER_DEFAULTS",
]