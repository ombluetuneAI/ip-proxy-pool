"""IP 代理池过滤工具主入口。

流程: 抓取 → 去重 → 协议验证(百度连通性) → GeoIP 归属地分类 → 国外二次验证(Google) → 落盘
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

import aiohttp

import config
from proxy_pool.cache import GeoCache, VerificationCache
from proxy_pool.classifier import classify
from proxy_pool.output import save_pools
from proxy_pool.sources import build_sources, fetch_all
from proxy_pool.validator import verify_all

logger = logging.getLogger("proxy_pool")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="抓取免费代理源，过滤有效代理，按国内/国外代理池保存到本地。"
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=config.VERIFY_CONCURRENCY,
        help=f"代理验证并发数（默认 {config.VERIFY_CONCURRENCY}）",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=config.VERIFY_TIMEOUT,
        help=f"单个代理验证超时秒数（默认 {config.VERIFY_TIMEOUT}）",
    )
    parser.add_argument(
        "--max-latency",
        type=float,
        default=config.MAX_LATENCY,
        help=f"延迟上限秒数，超过视为不可用（默认 {config.MAX_LATENCY}）",
    )
    parser.add_argument(
        "--sources",
        type=str,
        default="",
        help="仅启用指定数据源（逗号分隔的源名，如 monosans-http,geonode；默认全部启用）",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=config.OUTPUT_DIR,
        help=f"输出目录（默认 {config.OUTPUT_DIR}）",
    )
    parser.add_argument(
        "--skip-geoip",
        action="store_true",
        help="跳过 GeoIP 归属地查询，直接按目标站点访问归类（默认开启 GeoIP）",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="禁用验证/GeoIP 本地缓存（默认启用，断点续跑、避免重复请求）",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="仅输出警告与错误",
    )
    return parser.parse_args()


def setup_logging(quiet: bool) -> None:
    # Windows 控制台默认 GBK 会导致中文乱码，统一以 UTF-8 输出（配合 chcp 65001 使用）
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    level = logging.WARNING if quiet else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )


def apply_args(args: argparse.Namespace) -> None:
    """命令行参数覆盖配置。"""
    config.VERIFY_CONCURRENCY = args.concurrency
    config.VERIFY_TIMEOUT = args.timeout
    config.MAX_LATENCY = args.max_latency
    config.OUTPUT_DIR = args.output_dir


async def _fetch_phase(session: aiohttp.ClientSession, args: argparse.Namespace) -> list:
    """抓取 + 去重。"""
    sources_cfg = config.SOURCES
    if args.sources:
        wanted = {s.strip() for s in args.sources.split(",") if s.strip()}
        sources_cfg = [
            {**cfg, "enabled": cfg["name"] in wanted} for cfg in config.SOURCES
        ]
        enabled_names = {cfg["name"] for cfg in sources_cfg if cfg["enabled"]}
        missing = wanted - enabled_names
        if missing:
            logger.warning("以下数据源未找到或未启用: %s", ", ".join(sorted(missing)))
    logger.info("启用数据源: %s", ", ".join(cfg["name"] for cfg in sources_cfg if cfg["enabled"]))
    sources = build_sources(sources_cfg)
    if not sources:
        logger.error("没有可用的数据源，请检查 config.py 配置")
        raise SystemExit(1)
    return await fetch_all(session, sources)


async def run(args: argparse.Namespace) -> int:
    apply_args(args)
    setup_logging(args.quiet)
    logger.info("=== IP 代理池过滤工具开始 ===")

    # 本地缓存（断点续跑 / 去重请求）；--no-cache 时关闭
    out_dir = Path(config.OUTPUT_DIR)
    verify_cache = (
        None if args.no_cache else VerificationCache(out_dir / ".verify_cache.jsonl")
    )
    geo_cache = None if args.no_cache else GeoCache(out_dir / ".geo_cache.jsonl")

    # 抓取阶段使用独立、更宽松的会话
    fetch_timeout = aiohttp.ClientTimeout(total=config.FETCH_TIMEOUT)
    async with aiohttp.ClientSession(
        timeout=fetch_timeout,
        headers={"User-Agent": config.USER_AGENT},
    ) as session:
        raw_proxies = await _fetch_phase(session, args)
        if not raw_proxies:
            logger.error("未抓取到任何代理，流程终止")
            return 1

        # 第一步：基础连通性验证（国内目标，国内外代理均可访问）
        logger.info("开始基础连通性验证（目标 %s）...", config.CN_TARGET_URL)
        valid_proxies = await verify_all(
            raw_proxies, config.CN_TARGET_URL, cache=verify_cache
        )
        if not valid_proxies:
            logger.error("没有代理通过基础验证，流程终止")
            return 1

        # 第二步：归属地分类 + 国外二次验证
        if args.skip_geoip:
            logger.info("已跳过 GeoIP，直接按目标站点访问归类")
            from proxy_pool.classifier import ClassifyResult

            foreign_valid = await verify_all(
                valid_proxies, config.FOREIGN_TARGET_URL, cache=verify_cache
            )
            foreign_set = {id(p) for p in foreign_valid}
            cn = [p for p in valid_proxies if id(p) not in foreign_set]
            result = ClassifyResult(cn_proxies=cn, foreign_proxies=foreign_valid)
        else:
            result = await classify(session, valid_proxies, geo_cache=geo_cache)

        paths = save_pools(result.cn_proxies, result.foreign_proxies)

    logger.info("=== 完成：国内 %d 条 / 国外 %d 条 ===", len(result.cn_proxies), len(result.foreign_proxies))
    for key in ("cn_txt", "cn_json", "foreign_txt", "foreign_json"):
        print(f"{key}: {paths[key]}")
    return 0


def _suppress_reset_noise(loop: asyncio.AbstractEventLoop) -> None:
    """Windows Proactor 下代理连接被重置时会产生无害的 ConnectionResetError 回调噪音，静默之。"""
    default_handler = loop.get_exception_handler() or loop.default_exception_handler

    def _handler(_loop: asyncio.AbstractEventLoop, context: dict) -> None:
        exc = context.get("exception")
        if isinstance(exc, ConnectionResetError):
            return
        default_handler(_loop, context)

    loop.set_exception_handler(_handler)


def main() -> int:
    args = parse_args()
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        _suppress_reset_noise(loop)
        return loop.run_until_complete(run(args))
    except KeyboardInterrupt:
        print("\n已中断", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001
        logger.exception("程序异常: %s", exc)
        return 2
    finally:
        try:
            asyncio.set_event_loop(None)
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
