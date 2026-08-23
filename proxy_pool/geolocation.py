"""GeoIP 归属地模块：批量查询 ip-api.com，带退避重试与失败回退。"""

from __future__ import annotations

import asyncio
import logging

import aiohttp

import config
from proxy_pool.cache import GeoCache

logger = logging.getLogger(__name__)


async def _query_batch(
    session: aiohttp.ClientSession, ips: list[str]
) -> dict[str, dict]:
    """查询一批 IP（<=100），返回 {ip: {"country": code, "region": ..., "city": ...}}。"""
    payload = [
        {"query": ip, "fields": "status,countryCode,regionName,city"} for ip in ips
    ]
    for attempt in range(config.GEOIP_MAX_RETRIES):
        try:
            timeout = aiohttp.ClientTimeout(total=config.FETCH_TIMEOUT)
            async with session.post(
                config.GEOIP_BATCH_URL,
                json=payload,
                timeout=timeout,
            ) as resp:
                if resp.status == 429:
                    logger.warning("  GeoIP 限频，第 %d 次退避重试", attempt + 1)
                    await asyncio.sleep(2 ** (attempt + 1))
                    continue
                resp.raise_for_status()
                items = await resp.json(content_type=None)
        except Exception as exc:  # noqa: BLE001
            logger.warning("  GeoIP 批量查询失败: %s", exc)
            await asyncio.sleep(2 ** attempt)
            continue

        # batch 接口响应不含 query 字段，但顺序与请求一致，按索引映射
        result: dict[str, dict] = {}
        if isinstance(items, list) and len(items) == len(ips):
            for ip, item in zip(ips, items):
                if isinstance(item, dict) and item.get("status") == "success":
                    result[ip] = {
                        "country": item.get("countryCode", ""),
                        "region": item.get("regionName", ""),
                        "city": item.get("city", ""),
                    }
        elif isinstance(items, list):
            # 数量不匹配时尝试用 item.query 兜底
            for item in items:
                if isinstance(item, dict) and item.get("status") == "success":
                    query = item.get("query")
                    if query:
                        result[query] = {
                            "country": item.get("countryCode", ""),
                            "region": item.get("regionName", ""),
                            "city": item.get("city", ""),
                        }
        return result
    logger.warning("  GeoIP 批量查询最终失败，该批 %d 个 IP 走目标访问回退", len(ips))
    return {}


async def query_countries(
    session: aiohttp.ClientSession,
    ips: list[str],
    geo_cache: "GeoCache | None" = None,
) -> dict[str, dict]:
    """批量查询所有 IP 的归属地，返回 {ip: {"country":..., "region":..., "city":...}}。

    geo_cache 提供时：命中缓存的 IP 直接复用、不再请求 ip-api，显著减少限频与网络开销
    （10 万量级下同一 IP 常跨源重复出现）。
    """
    result: dict[str, dict] = {}
    unique_ips = list(dict.fromkeys(ips))  # 去重且保序

    # 1. 先吃缓存
    todo: list[str] = []
    if geo_cache is not None:
        for ip in unique_ips:
            cached = geo_cache.get(ip)
            if cached is not None:
                result[ip] = cached
            else:
                todo.append(ip)
        logger.info("GeoIP 缓存命中 %d 条，需查询 %d 条", len(result), len(todo))
    else:
        todo = unique_ips

    # 2. 未命中部分走在线批量查询
    for i in range(0, len(todo), config.GEOIP_MAX_BATCH):
        batch = todo[i : i + config.GEOIP_MAX_BATCH]
        batch_result = await _query_batch(session, batch)
        for ip, info in batch_result.items():
            result[ip] = info
            if geo_cache is not None:
                geo_cache.record(ip, info)
        if i + config.GEOIP_MAX_BATCH < len(todo):
            await asyncio.sleep(config.GEOIP_RATE_SLEEP)
    logger.info("GeoIP 查询完成：%d 个 IP，成功识别 %d 个", len(unique_ips), len(result))
    return result
