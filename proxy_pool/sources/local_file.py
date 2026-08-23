"""本地有效数据数据源：读取历史落盘的有效代理，作为回灌源参与再验证。

读取优先级：data/cn_proxies.json + data/foreign_proxies.json（含 protocol 等元数据）；
若 JSON 缺失则回退 data/cn_proxies.txt + data/foreign_proxies.txt（每行 ip:port，默认 http）。
用于「生成 → 落盘 → 下次再验证」闭环，避免每轮从零抓取。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import aiohttp

from proxy_pool.models import Proxy
from proxy_pool.sources.base import BaseSource

logger = logging.getLogger(__name__)


class LocalValidSource(BaseSource):
    """从本地 data/ 读取上轮有效代理（国内 + 国外）。"""

    name = "local_file"

    def __init__(
        self,
        cn_json: str,
        foreign_json: str,
        cn_txt: str | None = None,
        foreign_txt: str | None = None,
        source_name: str = "local-valid",
    ):
        self.cn_json = Path(cn_json)
        self.foreign_json = Path(foreign_json)
        self.cn_txt = Path(cn_txt) if cn_txt else self.cn_json.with_suffix(".txt")
        self.foreign_txt = (
            Path(foreign_txt) if foreign_txt else self.foreign_json.with_suffix(".txt")
        )
        self.source_name = source_name

    def _read_json(self, path: Path, out: list[Proxy]) -> None:
        if not path.exists():
            return
        try:
            with path.open("r", encoding="utf-8") as f:
                items = json.load(f)
            for item in items:
                if not isinstance(item, dict):
                    continue
                try:
                    out.append(
                        Proxy(
                            ip=item["ip"],
                            port=int(item["port"]),
                            protocol=item.get("protocol", "http"),
                            country=item.get("country"),
                            region=item.get("region"),
                            city=item.get("city"),
                            latency=item.get("latency"),
                            source=item.get("source") or self.source_name,
                            verified_at=item.get("verified_at", ""),
                        )
                    )
                except (KeyError, ValueError, TypeError):
                    continue
        except Exception as exc:  # noqa: BLE001
            logger.warning("  [%s] 读取 JSON 失败 %s: %s", self.source_name, path, exc)

    def _read_txt(self, path: Path, protocol: str, out: list[Proxy]) -> None:
        if not path.exists():
            return
        try:
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    p = Proxy.from_raw(line, protocol=protocol, source=self.source_name)
                    if p is not None:
                        out.append(p)
        except Exception as exc:  # noqa: BLE001
            logger.warning("  [%s] 读取 TXT 失败 %s: %s", self.source_name, path, exc)

    async def fetch(self, session: aiohttp.ClientSession) -> list[Proxy]:
        out: list[Proxy] = []
        # 优先 JSON（保留 protocol/延迟等元数据）
        self._read_json(self.cn_json, out)
        self._read_json(self.foreign_json, out)
        # JSON 任一存在则视为已覆盖；两份都缺失时回退 TXT
        if not self.cn_json.exists() and not self.foreign_json.exists():
            self._read_txt(self.cn_txt, "http", out)
            self._read_txt(self.foreign_txt, "http", out)
        logger.info("  [%s] 从本地读取 %d 条历史有效代理", self.source_name, len(out))
        return out
