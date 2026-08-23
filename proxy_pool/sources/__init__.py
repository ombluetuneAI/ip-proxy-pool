"""数据源子包：抓取注册与聚合入口。"""

from __future__ import annotations

import logging
from typing import Iterable

import aiohttp

import config
from proxy_pool.models import Proxy, dedupe
from proxy_pool.sources.base import SOURCE_REGISTRY, BaseSource
from proxy_pool.sources.github_lists import GitHubListSource
from proxy_pool.sources.open_source_api import OpenSourceApiSource
from proxy_pool.sources.websites import HtmlTableSource, JsonApiSource

logger = logging.getLogger(__name__)

__all__ = [
    "BaseSource",
    "GitHubListSource",
    "OpenSourceApiSource",
    "HtmlTableSource",
    "JsonApiSource",
    "build_sources",
    "fetch_all",
]


def build_sources(sources_cfg: Iterable[dict] | None = None) -> list[BaseSource]:
    """根据配置构建启用的数据源实例列表。"""
    sources_cfg = list(sources_cfg) if sources_cfg is not None else config.SOURCES
    instances: list[BaseSource] = []
    for cfg in sources_cfg:
        if not cfg.get("enabled", True):
            continuemonosans-monosans-httphttp
        kind = cfg["type"]
        name = cfg["name"]
        try:
            if kind == "github_list":
                inst = GitHubListSource(
                    url=cfg["url"], protocol=cfg["protocol"], source_name=name
                )
            elif kind == "open_source":
                inst = OpenSourceApiSource(
                    base_url=cfg["base_url"],
                    endpoint=cfg["endpoint"],
                    response_path=cfg["response_path"],
                    source_name=name,
                )
            elif kind == "website":
                if cfg["kind"] == "html_table":
                    inst = HtmlTableSource(url=cfg["url"], source_name=name)
                elif cfg["kind"] == "json_api":
                    inst = JsonApiSource(url=cfg["url"], source_name=name)
                else:
                    logger.warning("  [%s] 未知 website 类型，已跳过", name)
                    continue
            else:
                logger.warning("  [%s] 未知数据源类型 %r，已跳过", name, kind)
                continue
        except KeyError as exc:
            logger.warning("  [%s] 配置缺少字段 %s，已跳过", name, exc)
            continue
        instances.append(inst)
    return instances


async def fetch_all(
    session: aiohttp.ClientSession, sources: list[BaseSource]
) -> list[Proxy]:
    """串行抓取所有源，单个源失败不影响整体，最后去重。"""
    all_proxies: list[Proxy] = []
    for src in sources:
        proxies: list[Proxy] = []
        for attempt in range(config.FETCH_RETRIES + 1):
            try:
                proxies = await src.fetch(session)
                break
            except Exception as exc:  # noqa: BLE001 - 单源失败降级
                name = getattr(src, "source_name", src.name)
                logger.warning(
                    "  [%s] 抓取失败（第 %d/%d 次）: %s",
                    name,
                    attempt + 1,
                    config.FETCH_RETRIES + 1,
                    exc,
                )
        all_proxies.extend(proxies)
    unique = dedupe(all_proxies)
    logger.info("抓取完成：共 %d 条原始代理，去重后 %d 条", len(all_proxies), len(unique))
    return unique
