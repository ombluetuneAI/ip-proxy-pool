"""协议验证器：按协议构造连接器，访问目标站点验证连通性并记录延迟。

- http / https 代理: aiohttp.ProxyConnector（HTTP 代理，HTTPS 走 CONNECT）
- socks5 代理: aiohttp_socks.ProxyConnector
信号量控制并发，避免打满本地连接。
"""

from __future__ import annotations

import asyncio
import logging
import time

import aiohttp
from aiohttp_socks import ProxyConnector as SocksProxyConnector
from python_socks import ProxyType

import config
from proxy_pool.cache import VerificationCache
from proxy_pool.models import Proxy

logger = logging.getLogger(__name__)


def _make_connector(proxy: Proxy) -> aiohttp.BaseConnector:
    """按代理协议构造 aiohttp 连接器。

    aiohttp 3.11 已移除内置 ProxyConnector，统一使用 aiohttp_socks 的
    ProxyConnector（支持 http / https / socks4 / socks5 代理协议）。
    """
    scheme = proxy.protocol.split("/")[0]
    proxy_type = {
        "socks5": ProxyType.SOCKS5,
        "socks4": ProxyType.SOCKS4,
        "https": ProxyType.HTTP,
        "http": ProxyType.HTTP,
    }.get(scheme, ProxyType.HTTP)
    return SocksProxyConnector(
        host=proxy.ip,
        port=proxy.port,
        proxy_type=proxy_type,
        rdns=True,
    )


async def verify_proxy(proxy: Proxy, target_url: str) -> bool:
    """验证单个代理：能通过代理访问 target_url 且延迟在阈值内即为有效。"""
    start = time.perf_counter()
    connector: aiohttp.BaseConnector | None = None
    session: aiohttp.ClientSession | None = None
    try:
        connector = _make_connector(proxy)
        timeout = aiohttp.ClientTimeout(total=config.VERIFY_TIMEOUT)
        session = aiohttp.ClientSession(connector=connector, timeout=timeout)
        headers = {"User-Agent": config.USER_AGENT}
        async with session.get(target_url, headers=headers, ssl=False) as resp:
            if resp.status < 400:
                latency = time.perf_counter() - start
                if latency <= config.MAX_LATENCY:
                    proxy.latency = latency
                    return True
        return False
    except Exception:
        return False
    finally:
        if session is not None:
            await session.close()
        if connector is not None:
            await connector.close()


async def verify_all(
    proxies: list[Proxy],
    target_url: str,
    cache: "VerificationCache | None" = None,
) -> list[Proxy]:
    """并发验证代理列表，返回有效子集（已写入 latency）。

    cache 提供时：命中缓存的代理直接复用结果、不再发请求；新验证的结果回写缓存，
    便于 10 万量级断点续跑、避免对同一代理重复打网络。
    """
    if not proxies:
        return []
    if cache is not None:
        todo, hit_ok = cache.filter_unverified(proxies)
        if not todo:
            logger.info("验证完成：缓存全覆盖，无需实际请求")
            return hit_ok
        proxies = todo

    sem = asyncio.Semaphore(config.VERIFY_CONCURRENCY)

    async def _limited(p: Proxy) -> Proxy | None:
        async with sem:
            ok = await verify_proxy(p, target_url)
            if cache is not None:
                cache.record(p, ok)
            return p if ok else None

    results = await asyncio.gather(*(_limited(p) for p in proxies))
    valid = [r for r in results if r is not None]
    if cache is not None:
        valid = hit_ok + valid  # 合并断点续跑命中的有效代理
    logger.info("验证完成：%d 个候选，%d 个有效", len(proxies), len(valid))
    return valid
