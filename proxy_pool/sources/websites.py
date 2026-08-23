"""免费代理网站数据源。

- free-proxy-list.net: HTML 表格（#proxylisttable），列: IP | Port | Code(国家) | Country | Anonymity | Google | HTTPS | Last Checked
- geonode.com: JSON API，data[].{ip, port, protocols[], country}
"""

from __future__ import annotations

import logging

import aiohttp
from bs4 import BeautifulSoup

from proxy_pool.models import Proxy
from proxy_pool.sources.base import BaseSource, register_source

logger = logging.getLogger(__name__)

# 兼容 http/https 两类协议的关键字
_HTTP_KEYWORDS = {"http", "https", "yes", "no", "-"}


@register_source
class HtmlTableSource(BaseSource):
    """解析 free-proxy-list.net 风格的代理表格。"""

    name = "website_html"

    def __init__(self, url: str, source_name: str, table_id: str = "proxylisttable"):
        self.url = url
        self.source_name = source_name
        self.table_id = table_id

    async def fetch(self, session: aiohttp.ClientSession) -> list[Proxy]:
        headers = {"User-Agent": "Mozilla/5.0 proxy-pool-filter"}
        async with session.get(self.url, headers=headers) as resp:
            resp.raise_for_status()
            html = await resp.text()

        soup = BeautifulSoup(html, "lxml")
        table = soup.find("table", id=self.table_id)
        if table is None:
            logger.warning("  [%s] 未找到表格 #%s，已跳过", self.source_name, self.table_id)
            return []

        proxies: list[Proxy] = []
        for row in table.find("tbody").find_all("tr"):
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            if len(cells) < 2:
                continue
            ip, port = cells[0], cells[1]
            if not ip or not port.isdigit():
                continue
            # free-proxy-list.net 表格中 HTTPS 列（索引 6）为 yes/no；Anonymity 列（索引 4）
            https_ok = len(cells) > 6 and cells[6].lower() == "yes"
            protocols = ["https", "http"] if https_ok else ["http"]
            country = cells[2] if len(cells) > 2 else None
            for protocol in protocols:
                p = Proxy(
                    ip=ip,
                    port=int(port),
                    protocol=protocol,
                    country=country,
                    source=self.source_name,
                )
                proxies.append(p)
        logger.info("  [%s] 抓取到 %d 条代理", self.source_name, len(proxies))
        return proxies


@register_source
class JsonApiSource(BaseSource):
    """解析 geonode 风格 JSON API。"""

    name = "website_json"

    def __init__(self, url: str, source_name: str, data_path: str = "data"):
        self.url = url
        self.source_name = source_name
        self.data_path = data_path

    async def fetch(self, session: aiohttp.ClientSession) -> list[Proxy]:
        headers = {"User-Agent": "Mozilla/5.0 proxy-pool-filter", "Accept": "application/json"}
        async with session.get(self.url, headers=headers) as resp:
            resp.raise_for_status()
            payload = await resp.json(content_type=None)

        items = payload.get(self.data_path, []) if isinstance(payload, dict) else []
        if not isinstance(items, list):
            logger.warning("  [%s] 响应结构异常，已跳过", self.source_name)
            return []

        proxies: list[Proxy] = []
        for item in items:
            ip = item.get("ip")
            port = item.get("port")
            if not ip or not port:
                continue
            protocols = item.get("protocols") or ["http"]
            if isinstance(protocols, str):
                protocols = [protocols]
            country = item.get("country")
            for protocol in protocols:
                protocol = protocol.lower().split("/")[0]
                if protocol not in {"http", "https", "socks5", "socks4"}:
                    protocol = "http"
                proxies.append(
                    Proxy(
                        ip=str(ip),
                        port=int(port),
                        protocol=protocol,
                        country=country,
                        source=self.source_name,
                    )
                )
        logger.info("  [%s] 抓取到 %d 条代理", self.source_name, len(proxies))
        return proxies
