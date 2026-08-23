"""分类器：结合 GeoIP 归属地与目标站点二次验证，划分国内/国外代理池。

流程：
1. 已验证有效的代理已通过基础连通性验证（百度）；
2. GeoIP 查询归属国家，分流为国内候选（CN）与国外候选（非 CN）；
3. 国外候选再用 Google 做二次验证，通过者进入国外池；
4. 国内候选已通过百度验证，直接进入国内池；
5. GeoIP 查询失败的代理：通过 Google 验证则归国外池，否则保留在基础验证通过的国内池。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import aiohttp

import config
from proxy_pool.cache import GeoCache
from proxy_pool.geolocation import query_countries
from proxy_pool.models import Proxy
from proxy_pool.validator import verify_all

logger = logging.getLogger(__name__)


@dataclass
class ClassifyResult:
    cn_proxies: list[Proxy] = field(default_factory=list)
    foreign_proxies: list[Proxy] = field(default_factory=list)


async def classify(
    session: aiohttp.ClientSession,
    valid_proxies: list[Proxy],
    geo_cache: "GeoCache | None" = None,
) -> ClassifyResult:
    """对已验证连通性的代理执行归属地分类与二次验证。"""
    if not valid_proxies:
        return ClassifyResult()

    # 1. GeoIP 归属地查询
    country_map = await query_countries(
        session, [p.ip for p in valid_proxies], geo_cache=geo_cache
    )

    cn_candidates: list[Proxy] = []
    foreign_candidates: list[Proxy] = []
    unknown_candidates: list[Proxy] = []
    for p in valid_proxies:
        info = country_map.get(p.ip)
        if info:
            p.country = info.get("country") or None
            p.region = info.get("region") or None
            p.city = info.get("city") or None
            code = info.get("country")
        else:
            code = None
        if code == "CN":
            cn_candidates.append(p)
        elif code:
            foreign_candidates.append(p)
        else:
            unknown_candidates.append(p)
            logger.debug("  GeoIP 未识别 %s，走目标访问回退", p.endpoint)

    # 2. 二次验证：国外候选访问 Google
    foreign_valid = await verify_all(foreign_candidates, config.FOREIGN_TARGET_URL)

    # 3. GeoIP 失败回退：能访问 Google 归国外，否则（已通过百度）归国内
    fallback_foreign: list[Proxy] = []
    if unknown_candidates:
        fallback_foreign = await verify_all(unknown_candidates, config.FOREIGN_TARGET_URL)
        fallback_set = {id(p) for p in fallback_foreign}
        unknown_cn = [p for p in unknown_candidates if id(p) not in fallback_set]
        cn_candidates.extend(unknown_cn)
        logger.info(
            "GeoIP 未识别 %d 个，目标访问回退：%d 归国外，%d 归国内",
            len(unknown_candidates),
            len(fallback_foreign),
            len(unknown_cn),
        )

    result = ClassifyResult(
        cn_proxies=cn_candidates,
        foreign_proxies=foreign_valid + fallback_foreign,
    )
    logger.info(
        "分类完成：国内 %d 个，国外 %d 个",
        len(result.cn_proxies),
        len(result.foreign_proxies),
    )
    return result
