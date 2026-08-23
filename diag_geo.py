"""临时诊断脚本：测试 ip-api batch 与 geonode 抓取。"""

import asyncio

import aiohttp

import config


async def main():
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        # 1. ip-api batch
        payload = [{"query": "8.8.8.8", "fields": "status,countryCode,regionName,city"},
                   {"query": "114.114.114.114", "fields": "status,countryCode,regionName,city"}]
        try:
            async with session.post(config.GEOIP_BATCH_URL, json=payload) as resp:
                print("ip-api status:", resp.status)
                data = await resp.json(content_type=None)
                print("ip-api body:", data)
        except Exception as exc:
            print("ip-api error:", type(exc).__name__, exc)

        # 2. geonode
        try:
            headers = {"User-Agent": config.USER_AGENT, "Accept": "application/json"}
            async with session.get(config.SOURCES[9]["url"], headers=headers) as resp:
                print("geonode status:", resp.status)
                if resp.status == 200:
                    d = await resp.json(content_type=None)
                    print("geonode keys:", list(d.keys())[:5], "total:", d.get("total"))
                else:
                    print("geonode body:", (await resp.text())[:300])
        except Exception as exc:
            print("geonode error:", type(exc).__name__, exc)


if __name__ == "__main__":
    asyncio.run(main())
