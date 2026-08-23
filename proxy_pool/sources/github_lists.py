"""GitHub 原始文本列表数据源：每行一个 ip:port（兼容 http://ip:port 前缀）。"""

from __future__ import annotations

import logging

import aiohttp

from proxy_pool.models import Proxy
from proxy_pool.sources.base import BaseSource, register_source

logger = logging.getLogger(__name__)


@register_source
class GitHubListSource(BaseSource):
    name = "github_list"

    def __init__(self, url: str, protocol: str, source_name: str):
        self.url = url
        self.protocol = protocol
        self.source_name = source_name

    async def fetch(self, session: aiohttp.ClientSession) -> list[Proxy]:
        headers = {"User-Agent": "Mozilla/5.0 proxy-pool-filter"}
        async with session.get(self.url, headers=headers) as resp:
            resp.raise_for_status()
            text = await resp.text()

        proxies: list[Proxy] = []
        for line in text.splitlines():
            p = Proxy.from_raw(line, protocol=self.protocol, source=self.source_name)
            if p is not None:
                proxies.append(p)
        logger.info("  [%s] 抓取到 %d 条代理", self.source_name, len(proxies))
        return proxies
