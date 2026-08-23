"""数据源抽象基类与注册表。"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

import aiohttp

from proxy_pool.models import Proxy

logger = logging.getLogger(__name__)


class BaseSource(ABC):
    """数据源扩展契约。子类实现 fetch() 并注册到 SOURCE_REGISTRY。"""

    name: str = "base"

    @abstractmethod
    async def fetch(self, session: aiohttp.ClientSession) -> list[Proxy]:
        """抓取并解析该源的代理列表；单个源异常由上层捕获降级，不影响整体。"""
        raise NotImplementedError


SOURCE_REGISTRY: dict[str, type[BaseSource]] = {}


def register_source(cls: type[BaseSource]) -> type[BaseSource]:
    """注册数据源类到注册表。"""
    SOURCE_REGISTRY[cls.name] = cls
    return cls
