"""CxKitty 配置文件格式定义 (v2)

顶层结构::

    version: 2            # 格式版本
    runtime:   {...}      # 运行 / 界面
    paths:     {...}      # 目录
    proxy:     {...}      # 网络代理
    tasks:     {...}      # 刷课任务 (video / work / document / exam)
    transcript: {...}     # 视频转录管道
    searchers:            # 题库 / AI 搜索器
      defaults: {...}     # AI 提示词等公共默认值
      items: [{...}]      # 搜索器列表(自上而下依次调用)

本模块只描述"配置长什么样"(默认值 / 校验 / v1 兼容转换),
读取与导出常量见 ``config.py``, 完整说明见 ``docs/configuration.md``。
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

#: 当前配置格式版本
CONFIG_VERSION = 2

#: 完整默认值, 同时作为各配置段的字段白名单
DEFAULTS: dict[str, Any] = {
    "version": CONFIG_VERSION,
    "runtime": {
        "multi_session": True,
        "mask_acc": True,
        "tui_max_height": 25,
        "fetch_uploaded_face": True,
        # 数值计算线程上限(BLAS/OpenMP/torch), 0 = 跟随系统
        # 系统线程数多时 BLAS 会按线程预分配内存(每线程约 30-60MB), 调小可显著降低占用
        "cpu_threads": 0,
    },
    "paths": {
        "session": "session/",
        "logs": "logs/",
        "export": "export/",
        "faces": "faces/",
    },
    "proxy": {
        "enable": False,
        "http": "http://127.0.0.1:7897",
        "https": "http://127.0.0.1:7897",
    },
    "tasks": {
        "video": {
            "enable": True,
            "wait": 15,
            "speed": 1.0,
            "report_rate": 58,
            "download": True,
        },
        "work": {
            "enable": True,
            "export": True,
            "wait": 15,
            "fallback_fuzzer": False,
            "fallback_save": True,
        },
        "document": {
            "enable": True,
            "wait": 15,
        },
        "exam": {
            "fallback_fuzzer": False,
            "persubmit_delay": 15,
            "confirm_submit": True,
        },
    },
    "transcript": {
        "enable": False,
        "model_root": "",
        "device": "auto",
        "language": "auto",
        "use_itn": True,
        "cache_path": "transcripts/",
        "video_path": "videos/",
        "audio_path": "audios/",
        "keep_video": False,
        "keep_audio": False,
    },
    "searchers": {
        "defaults": {},
        "items": [],
    },
}

#: 允许显式写 null 的字段(其余字段写成 null 时回退默认值)
NULLABLE: set[tuple[str, ...]] = {("runtime", "tui_max_height")}

#: v1 扁平字段 -> v2 路径, 用于自动兼容旧配置
_LEGACY_PATHS = {
    "session": "session_path",
    "logs": "log_path",
    "export": "export_path",
    "faces": "face_image_path",
}
_LEGACY_RUNTIME = ("multi_session", "mask_acc", "tui_max_height", "fetch_uploaded_face")
_LEGACY_TASKS = ("video", "work", "document", "exam")


def is_v2(raw: Any) -> bool:
    """判断配置是否为 v2 分段格式"""
    if not isinstance(raw, dict):
        return False
    if raw.get("version") or any(key in raw for key in ("runtime", "paths", "proxy", "tasks")):
        return True
    return isinstance(raw.get("searchers"), dict)


def from_legacy(raw: dict) -> dict:
    """v1 扁平配置 -> v2 结构(缺失项用默认值补齐)"""
    conf = deepcopy(DEFAULTS)

    conf["runtime"].update(
        {key: raw[key] for key in _LEGACY_RUNTIME if raw.get(key) is not None}
    )
    for name, legacy_key in _LEGACY_PATHS.items():
        if raw.get(legacy_key):
            conf["paths"][name] = raw[legacy_key]

    proxies = raw.get("proxies")
    if isinstance(proxies, dict):
        if proxies.get("enable") is not None:
            conf["proxy"]["enable"] = proxies["enable"]
        if proxies.get("HTTP"):
            conf["proxy"]["http"] = proxies["HTTP"]
        if proxies.get("HTTPS"):
            conf["proxy"]["https"] = proxies["HTTPS"]

    for name in _LEGACY_TASKS:
        section = raw.get(name)
        if isinstance(section, dict):
            conf["tasks"][name].update({k: v for k, v in section.items() if v is not None})

    transcript = raw.get("transcript")
    if isinstance(transcript, dict):
        conf["transcript"].update({k: v for k, v in transcript.items() if v is not None})

    searchers = raw.get("searchers")
    if isinstance(searchers, list):
        conf["searchers"]["items"] = [dict(item) for item in searchers if isinstance(item, dict)]

    return conf


def normalize(raw: Any) -> tuple[dict[str, Any], list[str]]:
    """把任意版本配置规范化为 v2 结构

    Args:
        raw: ``yaml.load`` 得到的配置字典

    Returns:
        (规范化后的配置, 问题列表), 问题列表为空表示未发现可疑配置
    """
    problems: list[str] = []
    if not isinstance(raw, dict):
        problems.append("配置文件内容不是 YAML 映射, 已全部使用默认值")
        raw = {}

    if is_v2(raw):
        _check_unknown(raw, DEFAULTS, (), problems)
        conf = _merge(DEFAULTS, raw)
    else:
        conf = from_legacy(raw)

    conf["version"] = CONFIG_VERSION
    _coerce(conf, DEFAULTS, (), problems)
    _normalize_searchers(conf["searchers"], problems)
    return conf, problems


def _merge(template: Any, override: Any) -> Any:
    """按默认值模板递归合并用户配置(深层字典逐键合并, 列表整体覆盖)"""
    if isinstance(template, dict) and isinstance(override, dict):
        result = {key: deepcopy(value) for key, value in template.items()}
        for key, value in override.items():
            result[key] = _merge(template[key], value) if key in template else deepcopy(value)
        return result
    return deepcopy(override)


def _check_unknown(raw: dict, template: dict, path: tuple[str, ...], problems: list[str]) -> None:
    """递归检查配置中是否存在拼写错误/废弃字段"""
    for key, value in raw.items():
        here = path + (str(key),)
        if key not in template:
            problems.append(f"未知配置项 `{'.'.join(here)}`, 已忽略")
            continue
        # 搜索器条目由 resolver 侧按各自参数表校验, 这里不递归
        if here in (("searchers", "defaults"), ("searchers", "items")):
            continue
        child = template[key]
        if isinstance(child, dict) and isinstance(value, dict):
            _check_unknown(value, child, here, problems)


def _coerce(conf: dict, template: dict, path: tuple[str, ...], problems: list[str]) -> None:
    """按默认值类型矫正用户配置(类型错误时回退默认值并记录问题)"""
    for key, default in template.items():
        here = path + (str(key),)
        label = ".".join(here)
        if isinstance(default, dict):
            value = conf.get(key)
            if not isinstance(value, dict):
                problems.append(f"`{label}` 应为映射, 已回退默认值")
                conf[key] = deepcopy(default)
                continue
            _coerce(value, default, here, problems)
            continue

        value = conf.get(key)
        if value is None and here in NULLABLE:
            continue
        if isinstance(default, list):
            if not isinstance(value, list):
                problems.append(f"`{label}` 应为列表, 已回退默认值")
                conf[key] = deepcopy(default)
            continue
        if value is None:
            conf[key] = deepcopy(default)
            continue

        coerced = _to_type(value, default)
        if coerced is None:
            problems.append(f"`{label}` 的值 {value!r} 类型不正确, 已回退默认值 {default!r}")
            conf[key] = deepcopy(default)
        else:
            conf[key] = coerced


def _to_type(value: Any, default: Any) -> Any:
    """把 value 转换为 default 的类型; 无法转换时返回 None"""
    try:
        if isinstance(default, bool):
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, float)):
                return bool(value)
            if isinstance(value, str):
                text = value.strip().casefold()
                if text in ("true", "yes", "on", "1"):
                    return True
                if text in ("false", "no", "off", "0", ""):
                    return False
            return None
        if isinstance(default, int):
            if isinstance(value, bool):
                return None
            return int(value)
        if isinstance(default, float):
            if isinstance(value, bool):
                return None
            return float(value)
        if isinstance(default, str):
            if isinstance(value, (dict, list, bool)):
                return None
            return str(value)
    except (TypeError, ValueError):
        return None
    return value


def _normalize_searchers(section: dict, problems: list[str]) -> None:
    """校验 searchers 段: defaults 必须为映射, items 必须是带 type 的映射列表"""
    if not isinstance(section.get("defaults"), dict):
        problems.append("`searchers.defaults` 应为映射, 已置空")
        section["defaults"] = {}

    items = section.get("items")
    if not isinstance(items, list):
        problems.append("`searchers.items` 应为列表, 已置空")
        section["items"] = []
        return

    valid: list[dict] = []
    for index, item in enumerate(items, start=1):
        label = f"searchers.items[{index}]"
        if not isinstance(item, dict):
            problems.append(f"`{label}` 不是映射, 已忽略")
            continue
        if not str(item.get("type") or "").strip():
            problems.append(f"`{label}` 缺少 type 字段, 已忽略")
            continue
        item = dict(item)
        item["type"] = str(item["type"]).strip()
        if "enabled" in item and not isinstance(item["enabled"], bool):
            enabled = _to_type(item["enabled"], True)
            if enabled is None:
                problems.append(f"`{label}.enabled` 不是布尔值, 已按 true 处理")
                enabled = True
            item["enabled"] = enabled
        valid.append(item)
    section["items"] = valid


__all__ = ["CONFIG_VERSION", "DEFAULTS", "NULLABLE", "is_v2", "from_legacy", "normalize"]