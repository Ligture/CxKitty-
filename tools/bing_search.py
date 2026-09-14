#!/usr/bin/env python3
"""
Bing Search 工具 — 供大模型 (LLM) 调用

用法:
  import:   from tools.bing_search import BingSearch, search
  CLI:      python -m tools.bing_search "关键词"
  LLM tool: BingSearch.as_openai_tool()

认证: 设置环境变量 BING_API_KEY 或直接传入 api_key 参数
获取: https://portal.azure.com → 创建 Bing Search 资源 → 密钥管理
"""

import json
import os
import sys
from typing import Optional

import requests


API_BING = "https://api.bing.microsoft.com/v7.0/search"


class BingSearch:
    """Bing Web Search 封装 — 供 LLM Function Calling 使用"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        market: str = "zh-CN",
        count: int = 10,
    ):
        self.api_key = api_key or os.environ.get("BING_API_KEY", "")
        self.market = market
        self.count = count

    # ─── 搜索 ───────────────────────────────────────

    def search(self, query: str, count: Optional[int] = None) -> list[dict]:
        """执行搜索，返回结构化结果"""
        n = count or self.count
        headers = {
            "Ocp-Apim-Subscription-Key": self.api_key,
            "Accept-Language": self.market,
        }
        params = {
            "q": query,
            "count": min(n, 50),
            "mkt": self.market,
        }
        resp = requests.get(API_BING, headers=headers, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        results = []
        for item in data.get("webPages", {}).get("value", [])[:n]:
            results.append({
                "title": item.get("name", ""),
                "url": item.get("url", ""),
                "snippet": item.get("snippet", ""),
                "date": item.get("datePublished", None),
            })
        return results

    # ─── LLM 输出格式化 ─────────────────────────────

    def text(self, query: str, count: int = 5) -> str:
        """返回适合 LLM 阅读的纯文本"""
        results = self.search(query, count)
        if not results:
            return f"未找到关于「{query}」的搜索结果。"

        lines = [f"Bing 搜索结果 ({len(results)} 条): {query}\n"]
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. **{r['title']}**")
            lines.append(f"   URL: {r['url']}")
            lines.append(f"   {r['snippet']}")
            if r.get("date"):
                lines.append(f"   日期: {r['date']}")
            lines.append("")
        return "\n".join(lines)

    def json_(self, query: str, count: int = 5) -> str:
        """返回 JSON 字符串"""
        return json.dumps({
            "query": query,
            "count": len(self.search(query, count)),
            "results": self.search(query, count),
        }, ensure_ascii=False, indent=2)

    # ─── OpenAI Function Calling 工具定义 ────────────

    @staticmethod
    def as_openai_tool() -> dict:
        """返回 OpenAI tools 定义"""
        return {
            "type": "function",
            "function": {
                "name": "bing_search",
                "description": "搜索互联网获取最新信息，支持中英文查询，返回网页标题、URL 和摘要。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "搜索关键词",
                        },
                        "count": {
                            "type": "integer",
                            "description": "返回结果数，默认 5",
                        },
                    },
                    "required": ["query"],
                },
            },
        }

    def invoke(self, arguments: dict) -> str:
        """LLM Function Calling 入口"""
        query = arguments.get("query", "")
        count = min(int(arguments.get("count", 5)), 20)
        return self.json_(query, count)


# ─── 快捷函数 ─────────────────────────────────────────

_default = BingSearch()
search = _default.search
search_text = _default.text
as_openai_tool = BingSearch.as_openai_tool


# ─── CLI ──────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python -m tools.bing_search <关键词> [数量]")
        print("示例: python -m tools.bing_search \"超星学习通\" 5")
        print()
        print("请先设置环境变量 BING_API_KEY")
        print("获取: https://portal.azure.com → 创建 Bing Search")
        sys.exit(1)

    if not _default.api_key:
        print("[错误] 未设置 BING_API_KEY 环境变量")
        sys.exit(1)

    query = sys.argv[1]
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    print(_default.text(query, count))
