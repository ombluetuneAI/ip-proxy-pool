"""本地缓存：验证结果缓存（断点续跑）与 GeoIP 结果缓存（去重查询）。

- VerificationCache: 以 (ip, port, protocol) 为键，记录代理是否通过验证及延迟。
  重跑时可跳过已验证条目，10 万量级下避免重复打网络、支持中断续跑。
- GeoCache: 以 ip 为键，记录 GeoIP 归属地，避免对同一 IP 重复请求 ip-api。
两条缓存均以追加写 jsonl 形式落盘，加载时全量读入内存（10 万量级内存可控）。
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

from proxy_pool.models import Proxy

logger = logging.getLogger(__name__)


def _key(p: Proxy) -> tuple[str, int, str]:
    return (p.ip, p.port, p.protocol)


class VerificationCache:
    """验证结果缓存：键=(ip,port,protocol)，值=是否通过 + 延迟 + 验证时间。"""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = threading.Lock()
        # key -> {"ok": bool, "latency": float|None, "verified_at": str}
        self._data: dict[tuple[str, int, str], dict] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            with self.path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    rec = json.loads(line)
                    k = (rec["ip"], int(rec["port"]), rec["protocol"])
                    self._data[k] = {
                        "ok": bool(rec["ok"]),
                        "latency": rec.get("latency"),
                        "verified_at": rec.get("verified_at", ""),
                    }
            logger.info("验证缓存加载：%d 条已验证记录（%s）", len(self._data), self.path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("验证缓存读取失败，忽略：%s", exc)

    def get(self, p: Proxy) -> dict | None:
        return self._data.get(_key(p))

    def record(self, p: Proxy, ok: bool) -> None:
        rec = {
            "ip": p.ip,
            "port": p.port,
            "protocol": p.protocol,
            "ok": ok,
            "latency": round(p.latency, 3) if p.latency is not None else None,
            "verified_at": p.verified_at,
        }
        with self._lock:
            self._data[_key(p)] = {
                "ok": ok,
                "latency": rec["latency"],
                "verified_at": p.verified_at,
            }
            try:
                with self.path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            except Exception as exc:  # noqa: BLE001
                logger.warning("验证缓存写入失败：%s", exc)

    def filter_unverified(self, proxies: list[Proxy]) -> tuple[list[Proxy], list[Proxy]]:
        """拆分为 (待验证列表, 缓存命中且有效列表)。

        命中缓存且曾验证通过的代理直接回填延迟/时间并放入 hit_ok，
        避免断点续跑时这些已验证有效的代理在后续流程被丢失。
        """
        todo: list[Proxy] = []
        hit_ok: list[Proxy] = []
        hit = 0
        for p in proxies:
            cached = self.get(p)
            if cached is None:
                todo.append(p)
            else:
                hit += 1
                if cached["ok"]:
                    p.latency = cached["latency"]
                    p.verified_at = cached["verified_at"] or p.verified_at
                    hit_ok.append(p)
        if hit:
            logger.info("验证缓存命中 %d 条（其中有效 %d 条），跳过实际请求", hit, len(hit_ok))
        return todo, hit_ok


class GeoCache:
    """GeoIP 结果缓存：键=ip，值=country/region/city。"""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = threading.Lock()
        # ip -> {"country":..., "region":..., "city":...}
        self._data: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            with self.path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    rec = json.loads(line)
                    self._data[rec["ip"]] = {
                        "country": rec.get("country", ""),
                        "region": rec.get("region", ""),
                        "city": rec.get("city", ""),
                    }
            logger.info("GeoIP 缓存加载：%d 条（%s）", len(self._data), self.path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("GeoIP 缓存读取失败，忽略：%s", exc)

    def get(self, ip: str) -> dict | None:
        return self._data.get(ip)

    def record(self, ip: str, info: dict) -> None:
        with self._lock:
            self._data[ip] = info
            try:
                rec = {
                    "ip": ip,
                    "country": info.get("country", ""),
                    "region": info.get("region", ""),
                    "city": info.get("city", ""),
                }
                with self.path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            except Exception as exc:  # noqa: BLE001
                logger.warning("GeoIP 缓存写入失败：%s", exc)
