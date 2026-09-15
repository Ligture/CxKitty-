#!/usr/bin/env python3
"""config.yml 迁移工具: v1(扁平格式) -> v2(分段格式)

用法::

    python scripts/migrate_config.py                 # 迁移 config.yml, 自动备份
    python scripts/migrate_config.py --dry-run       # 只打印结果(敏感值打码)
    python scripts/migrate_config.py --show-secrets  # 配合 --dry-run 显示完整密钥
    python scripts/migrate_config.py -p other.yml    # 指定其它配置文件
    python scripts/migrate_config.py --style block   # 输出缩进块式(默认花括号流式)

说明:

* 只做"结构搬家", 原有取值保持不变, 缺少的字段用默认值补齐
* 已是 v2 的文件不会重复迁移
* 原文件备份为 ``config.yml.bak.<时间戳>``, 迁移内容说明见 docs/configuration.md
"""

from __future__ import annotations

import argparse
import copy
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import config_schema as schema  # noqa: E402

#: 命中这些关键字的字段在 --dry-run 输出中打码
SENSITIVE_HINTS = (
    "api_key",
    "token",
    "secure_1psid",
    "secure_1psidts",
    "cookie",
    "password",
    "secret",
    "authorization",
)


class BlockDumper(yaml.SafeDumper):
    """多行字符串使用 ``|`` 块标量, 便于阅读提示词"""

    def represent_str(self, data: str):  # noqa: D102 - PyYAML 回调
        style = "|" if _use_block(data) else None
        return self.represent_scalar("tag:yaml.org,2002:str", data, style=style)


def _use_block(text: str) -> bool:
    """判断字符串是否适合用块标量表示"""
    if "\n" not in text or "\r" in text or text.startswith((" ", "\t", "\n")):
        return False
    return all(line == line.rstrip() for line in text.split("\n"))


BlockDumper.add_representer(str, BlockDumper.represent_str)


class FlowDumper(yaml.SafeDumper):
    """花括号写法下, 多行字符串用双引号 + \n 转义, 避免折行歧义"""

    def represent_str(self, data: str):  # noqa: D102 - PyYAML 回调
        style = '"' if "\n" in data else None
        return self.represent_scalar("tag:yaml.org,2002:str", data, style=style)


FlowDumper.add_representer(str, FlowDumper.represent_str)


def dumps(conf: dict[str, Any], flow: bool = True) -> str:
    """序列化为 YAML

    Args:
        conf: 配置字典
        flow: True 输出花括号流式写法(可读性好且支持注释), False 输出块式写法

    Returns:
        YAML 文本; 结果会做一次 round-trip 校验, 不合法时回退普通风格
    """
    dumpers = [FlowDumper, yaml.SafeDumper] if flow else [BlockDumper, yaml.SafeDumper]
    for dumper in dumpers:
        try:
            text = yaml.dump(
                conf,
                Dumper=dumper,
                allow_unicode=True,
                sort_keys=False,
                default_flow_style=flow,
                width=100,
            )
        except yaml.YAMLError:
            continue
        if yaml.safe_load(text) == conf:
            return text
    raise RuntimeError("配置序列化失败, 请检查内容")


def dump_header(conf: dict[str, Any], backup_name: str, timestamp: str, flow: bool) -> str:
    """生成带说明注释的文件头(流式写法下注释写在文件顶部)"""
    style = "花括号(YAML 流式)" if flow else "块式"
    return (
        f"# CxKitty 配置文件 ({style}写法, 格式版本 2)\n"
        "# 字段说明: docs/configuration.md | 示例: config.yml.example\n"
        f"# 由 scripts/migrate_config.py 生成于 {timestamp}, 原文件备份: {backup_name}\n"
        "# 提示: 这是 YAML 而非严格 JSON, 允许 # 注释、尾逗号与省略键名引号\n\n"
    )


def mask_secrets(value: Any, key: str = "") -> Any:
    """深拷贝并打码敏感字段(仅用于终端预览)"""
    if isinstance(value, dict):
        return {k: mask_secrets(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [mask_secrets(item) for item in value]
    if isinstance(value, str) and value and any(hint in key.casefold() for hint in SENSITIVE_HINTS):
        return f"{value[:4]}***" if len(value) > 4 else "***"
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description="config.yml v1 -> v2 迁移工具")
    parser.add_argument("-p", "--path", default="config.yml", help="配置文件路径(默认 config.yml)")
    parser.add_argument("--dry-run", action="store_true", help="只打印结果, 不写入文件")
    parser.add_argument("--show-secrets", action="store_true", help="预览时显示完整密钥")
    parser.add_argument(
        "--style",
        choices=("flow", "block"),
        default="flow",
        help="输出风格: flow 花括号流式(默认), block 缩进块式",
    )
    args = parser.parse_args()

    path = Path(args.path)
    if not path.is_file():
        print(f"[ERROR] 找不到配置文件: {path}", file=sys.stderr)
        return 1

    raw = yaml.load(path.read_text(encoding="utf8"), yaml.FullLoader)
    if not isinstance(raw, dict):
        print(f"[ERROR] {path} 内容不是 YAML 映射", file=sys.stderr)
        return 1
    if schema.is_v2(raw):
        print(f"[SKIP] {path} 已是 v2 格式, 无需迁移")
        return 0

    conf, problems = schema.normalize(raw)
    flow = args.style == "flow"
    body = dumps(conf, flow)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(f"{path.name}.bak.{timestamp}")
    header = dump_header(conf, backup.name, timestamp, flow)

    if args.dry_run:
        preview = conf if args.show_secrets else mask_secrets(copy.deepcopy(conf))
        print(header + dumps(preview, flow) + "\n# (--dry-run 预览结束, 未写入文件)")
    else:
        shutil.copy2(path, backup)
        path.write_text(header + body, encoding="utf8")
        print(f"[OK] 已迁移 {path} -> v2 格式, 备份: {backup}")

    for problem in problems:
        print(f"[WARN] {problem}", file=sys.stderr)

    enabled = [item for item in conf["searchers"]["items"] if item.get("enabled", True) is not False]
    print(f"[INFO] 搜索器 {len(conf['searchers']['items'])} 个, 其中启用 {len(enabled)} 个")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())