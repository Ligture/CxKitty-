"""配置加载与全局访问

配置文件默认是运行目录下的 ``config.yml``; 启动时也可指定其它文件, 实现一套代码
多套配置(如刷课答题用 ``config.yml``, 只刷课转录用 ``config(no_answer).yml``)。
解析优先级: **启动参数 > 环境变量 > 默认值**:

* 启动参数 ``-C path.yml`` / ``--config-file path.yml`` / ``--config-file=path.yml``
* 环境变量 ``CXKITTY_CONFIG=path.yml``

例如 ``poetry run python main.py -C "config(no_answer).yml"``。

``-C/--config-file`` 在 ``config`` 模块导入时即被消费(并从 ``sys.argv`` 中移除),
因此系统各处 ``import config`` 拿到的都是指定配置, 且不会干扰其它参数解析器。

``config.yml`` 使用 v2 分段格式(结构定义见 ``config_schema.py``,
完整说明见 ``docs/configuration.md``); 旧版 v1 扁平格式仍可读取,
启动时提示迁移: ``python scripts/migrate_config.py``。

本模块把配置导出为常量供全局使用, 例如 ``config.WORK`` / ``config.SEARCHERS``。
所有字段都会先用 ``config_schema.DEFAULTS`` 补齐并校验, 因此各处下标访问安全。
"""

from __future__ import annotations

import copy
import os
import sys
import warnings
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

import config_schema as schema

#: 默认配置文件(相对运行目录)
DEFAULT_CONFIG_PATH = Path("config.yml")
#: 环境变量: 指定配置文件, 与启动参数等价
CONFIG_ENV_VAR = "CXKITTY_CONFIG"
#: 启动参数: 指定配置文件
CONFIG_CLI_FLAGS = ("-C", "--config-file")


def _take_config_arg(argv: Sequence[str]) -> tuple[str | None, list[str]]:
    """从参数列表中摘出配置文件路径

    支持 ``-C path`` / ``-Cpath`` / ``--config-file path`` / ``--config-file=path``,
    ``--`` 之后的参数原样保留。

    Args:
        argv: 参数列表(不含程序名)

    Returns:
        (配置文件路径, 移除该选项后的参数列表); 未指定时为 ``(None, argv)``
    """
    value: str | None = None
    rest: list[str] = []
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg == "--":  # 分隔符之后原样交给上层解析
            rest.extend(argv[index:])
            break
        if arg.startswith("--config-file="):
            value = arg.split("=", 1)[1]
        elif arg == "--config-file":
            value = argv[index + 1] if index + 1 < len(argv) else ""
            index += 1
        elif arg.startswith("-C") and arg != "-C":
            value = arg[2:]
        elif arg == "-C":
            value = argv[index + 1] if index + 1 < len(argv) else ""
            index += 1
        else:
            rest.append(arg)
            index += 1
            continue
        index += 1
    return value, rest


def resolve_config_path(
    argv: Sequence[str] | None = None,
    environ: Mapping[str, str] | None = None,
) -> tuple[Path, list[str], bool]:
    """解析最终使用的配置文件路径

    Args:
        argv: 参数列表(默认 ``sys.argv[1:]``)
        environ: 环境变量映射(默认 ``os.environ``)

    Returns:
        (配置文件路径, 移除 ``-C/--config-file`` 后的参数列表, 是否由启动参数 / 环境变量显式指定)

    Raises:
        SystemExit: 指定了选项却没有给出路径
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    environ = os.environ if environ is None else environ

    cli_value, rest = _take_config_arg(argv)
    if cli_value is not None and not cli_value.strip():
        raise SystemExit(
            f"选项 {' / '.join(CONFIG_CLI_FLAGS)} 需要一个配置文件路径, "
            '例如: python main.py -C "config(no_answer).yml"'
        )

    env_value = (environ.get(CONFIG_ENV_VAR) or "").strip()
    raw = cli_value.strip() if cli_value is not None else env_value
    if not raw:
        return DEFAULT_CONFIG_PATH, rest, False
    return Path(raw), rest, True


# 启动时解析一次: 指定配置同时从 sys.argv 摘除, 保证其它参数解析器不受影响
CONFIG_PATH, _REST_ARGV, _CONFIG_EXPLICIT = resolve_config_path()
if _REST_ARGV != sys.argv[1:]:
    sys.argv[1:] = _REST_ARGV


def load(path: str | Path = CONFIG_PATH, *, required: bool = False) -> dict[str, Any]:
    """读取并规范化配置文件

    Args:
        path: 配置文件路径
        required: 文件不存在时是否直接报错退出(显式指定配置文件时为 True,
            避免静默跑成默认配置)

    Returns:
        v2 结构的完整配置, 缺失字段已用默认值补齐
    """
    path = Path(path)
    raw: Any = {}
    if path.is_file():
        with path.open("r", encoding="utf8") as fp:
            raw = yaml.load(fp, yaml.FullLoader)
    elif required:
        raise SystemExit(
            f"指定的配置文件不存在: {path}\n"
            "请检查路径是否正确, 或先创建该文件(可从 config.yml.example 复制)"
        )
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


CONF: dict[str, Any] = load(CONFIG_PATH, required=_CONFIG_EXPLICIT)


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
    "DEFAULT_CONFIG_PATH",
    "CONFIG_ENV_VAR",
    "CONFIG_CLI_FLAGS",
    "CONFIG_PATH",
    "CONF",
    "as_dict",
    "resolve_config_path",
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
