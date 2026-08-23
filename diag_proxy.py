"""临时诊断脚本：测试单个代理的验证流程，打印具体异常。"""

import asyncio
import time

import aiohttp

from proxy_pool.models import Proxy
from proxy_pool.validator import _make_connector, verify_proxy


async def main():
    # 测试几个代表性代理
    candidates = [
        Proxy(ip="45.174.243.145", port=999, protocol="http"),
        Proxy(ip="103.236.134.210", port=1080, protocol="http"),
    ]
    for p in candidates:
        start = time.perf_counter()
        ok = await verify_proxy(p, "https://www.baidu.com")
        print(f"{p.endpoint} -> ok={ok}, latency={time.perf_counter()-start:.2f}s")

    # 手动尝试以打印真实异常
    p = candidates[0]
    connector = _make_connector(p)
    session = aiohttp.ClientSession(connector=connector, timeout=aiohttp.ClientTimeout(total=8))
    try:
        async with session.get("https://www.baidu.com", ssl=False) as resp:
            print("status:", resp.status)
    except Exception as exc:
        print(f"exception: {type(exc).__name__}: {exc}")
    finally:
        await session.close()
        await connector.close()


if __name__ == "__main__":
    asyncio.run(main())
