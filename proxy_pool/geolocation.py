"""GeoIP 归属地模块。

查询策略（优先级从高到低）：
1. 本地离线库 GeoLite2-Country.mmdb（maxminddb，零网络、零限频、秒级，10 万量级首选）
2. 本地结果缓存 GeoCache（跨运行复用，避免重复查）
3. 在线 ip-api.com 批量接口（带退避重试），作为离线库未覆盖时的回退

离线库缺失时自动降级为「缓存 + 在线」原方案，不影响可用性。
"""

from __future__ import annotations

import asyncio
import logging
from functools import lru_cache
from pathlib import Path

import aiohttp

import config
from proxy_pool.cache import GeoCache

logger = logging.getLogger(__name__)

# 离线 mmdb reader 单例（懒加载），进程内共享一份 mmap
_mmdb_reader = None
_mmdb_checked = False


def _get_mmdb_reader():
    """返回 maxminddb 读取器单例；文件不存在/读取失败则返回 None。"""
    global _mmdb_reader, _mmdb_checked
    if _mmdb_checked:
        return _mmdb_reader
    _mmdb_checked = True
    path = Path(config.GEOIP_MMDB_PATH)
    if not path.exists():
        logger.warning("离线 GeoIP 库不存在（%s），将回退在线查询", path)
        return None
    try:
        import maxminddb

        _mmdb_reader = maxminddb.open_database(str(path))
        logger.info("离线 GeoIP 库已加载：%s", path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("离线 GeoIP 库加载失败，回退在线查询：%s", exc)
        _mmdb_reader = None
    return _mmdb_reader


def _lookup_mmdb(ip: str) -> dict | None:
    """用离线库查单个 IP，返回 {"country","region","city"} 或 None。"""
    reader = _get_mmdb_reader()
    if reader is None:
        return None
    try:
        rec = reader.get(ip)
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(rec, dict):
        return None
    # 兼容两种结构：官方 MaxMind（{"country": {"iso_code": "CN"}}）与社区镜像（{"country_code": "CN"}）
    country = rec.get("country")
    if isinstance(country, dict):
        code = country.get("iso_code", "") or country.get("code", "")
    else:
        code = rec.get("country_code", "") or ""
    if not code:
        return None
    # GeoLite2-Country 仅含 country；region/city 留空（够用于国内/国外分类）
    return {"country": code, "region": "", "city": ""}


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

    优先级：离线 mmdb → 本地缓存 → 在线 ip-api。
    """
    result: dict[str, dict] = {}
    unique_ips = list(dict.fromkeys(ips))  # 去重且保序
    offline_hits = online_hits = cache_hits = 0

    # 1. 离线库 + 缓存 优先（同步读取，用线程池避免阻塞事件循环）
    todo: list[str] = []
    for ip in unique_ips:
        # 缓存优先
        if geo_cache is not None:
            cached = geo_cache.get(ip)
            if cached is not None:
                result[ip] = cached
                cache_hits += 1
                continue
        # 离线库
        info = await asyncio.to_thread(_lookup_mmdb, ip)
        if info is not None and info.get("country"):
            result[ip] = info
            offline_hits += 1
            if geo_cache is not None:
                geo_cache.record(ip, info)
        else:
            todo.append(ip)

    if todo:
        logger.info(
            "GeoIP：离线命中 %d / 缓存命中 %d，需在线查询 %d 条",
            offline_hits,
            cache_hits,
            len(todo),
        )
        # 2. 未命中部分走在线批量查询
        for i in range(0, len(todo), config.GEOIP_MAX_BATCH):
            batch = todo[i : i + config.GEOIP_MAX_BATCH]
            batch_result = await _query_batch(session, batch)
            for ip, info in batch_result.items():
                result[ip] = info
                if geo_cache is not None:
                    geo_cache.record(ip, info)
            online_hits += len(batch_result)
            if i + config.GEOIP_MAX_BATCH < len(todo):
                await asyncio.sleep(config.GEOIP_RATE_SLEEP)
    else:
        logger.info("GeoIP：离线库 + 缓存全覆盖 %d 条，无需在线查询", len(unique_ips))

    logger.info(
        "GeoIP 查询完成：%d 个 IP，识别 %d 个（离线 %d / 缓存 %d / 在线 %d）",
        len(unique_ips),
        len(result),
        offline_hits,
        cache_hits,
        online_hits,
    )
    return result
