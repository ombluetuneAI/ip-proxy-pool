"""全链路核心数据结构。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class Proxy:
    """一个代理条目，同一 IP 不同协议视为不同条目。"""

    ip: str
    port: int
    protocol: str            # "http" | "https" | "socks5"
    country: str | None = None   # 归属国家代码，如 "CN"
    region: str | None = None    # 归属省份/州
    city: str | None = None
    latency: float | None = None  # 验证响应延迟（秒）
    source: str = ""             # 来源数据源名称
    verified_at: str = ""        # 验证时间 ISO 字符串

    @property
    def endpoint(self) -> str:
        return f"{self.ip}:{self.port}"

    def to_dict(self) -> dict:
        return {
            "ip": self.ip,
            "port": self.port,
            "protocol": self.protocol,
            "endpoint": self.endpoint,
            "country": self.country,
            "region": self.region,
            "city": self.city,
            "latency": round(self.latency, 3) if self.latency is not None else None,
            "source": self.source,
            "verified_at": self.verified_at,
        }

    @classmethod
    def from_raw(cls, raw: str, protocol: str = "http", source: str = "") -> "Proxy | None":
        """从 'ip:port' 字符串解析，非法格式返回 None。"""
        raw = raw.strip()
        if not raw or raw.startswith("#"):
            return None
        # 兼容 "http://ip:port" 与 "ip:port" 两种写法
        if "://" in raw:
            raw = raw.rsplit("://", 1)[1]
        parts = raw.split(":")
        if len(parts) != 2:
            return None
        ip, port_str = parts[0].strip(), parts[1].strip()
        if not ip or not port_str.isdigit():
            return None
        port = int(port_str)
        if not (1 <= port <= 65535):
            return None
        return cls(
            ip=ip,
            port=port,
            protocol=protocol,
            source=source,
            verified_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )


def dedupe(proxies: list[Proxy]) -> list[Proxy]:
    """按 (ip, port, protocol) 去重，保留首次出现。"""
    seen: set[tuple[str, int, str]] = set()
    result: list[Proxy] = []
    for p in proxies:
        key = (p.ip, p.port, p.protocol)
        if key not in seen:
            seen.add(key)
            result.append(p)
    return result
