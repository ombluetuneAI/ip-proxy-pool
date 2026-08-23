"""开源代理池公开 API 数据源。

适配两类常见响应：
- go_proxy_pool 风格: {"data": [{"ip": ..., "port": ..., "type": "http"}, ...]}
- jhao104/proxy_pool 风格: {"proxy": ["ip:port", ...]}
Base URL 可配置为自建实例。
"""

from __future__ import annotations

import json
import logging
from urllib.parse import urljoin

import aiohttp

from proxy_pool.models import Proxy
from proxy_pool.sources.base import BaseSource, register_source

logger = logging.getLogger(__name__)


@register_source
class OpenSourceApiSource(BaseSource):
    name = "open_source"

    def __init__(self, base_url: str, endpoint: str, response_path: str, source_name: str):
        self.url = urljoin(base_url.rstrip("/") + "/", endpoint.lstrip("/"))
        self.response_path = response_path  # "data" | "proxy"
        self.source_name = source_name

    @staticmethod
    def _normalize_protocol(raw: str) -> str:
        return raw.lower().strip().split("/")[0] or "http"

    async def fetch(self, session: aiohttp.ClientSession) -> list[Proxy]:
        headers = {"User-Agent": "Mozilla/5.0 proxy-pool-filter", "Accept": "application/json"}
        async with session.get(self.url, headers=headers) as resp:
            resp.raise_for_status()
            payload = await resp.json()

        items = payload.get(self.response_path, []) if isinstance(payload, dict) else payload
        if not isinstance(items, list):
            logger.warning("  [%s] API 响应结构异常，已跳过", self.source_name)
            return []

        proxies: list[Proxy] = []
        for item in items:
            if isinstance(item, str):
                # proxy_pool 风格: "ip:port"
                p = Proxy.from_raw(item, source=self.source_name)
            elif isinstance(item, dict):
                ip = item.get("ip") or item.get("host")
                port = item.get("port")
                if not ip or not port:
                    continue
                protocol = self._normalize_protocol(
                    item.get("type") or item.get("protocol") or item.get("protocols", "http")
                    if not isinstance(item.get("protocols"), list)
                    else ",".join(item.get("protocols") or ["http"])
                )
                p = Proxy(ip=str(ip), port=int(port), protocol=protocol, source=self.source_name)
            else:
                continue
            if p is not None:
                proxies.append(p)
        logger.info("  [%s] 抓取到 %d 条代理", self.source_name, len(proxies))
        return proxies
