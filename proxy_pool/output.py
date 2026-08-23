"""输出模块：写入国内/国外代理池的 txt 与 JSON 文件（原子写入防中断损坏）。"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path

import config
from proxy_pool.models import Proxy

logger = logging.getLogger(__name__)


def _atomic_write_text(path: Path, lines: list[str]) -> None:
    content = "\n".join(lines)
    if content:
        content += "\n"
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp", text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def _atomic_write_json(path: Path, data: list[dict]) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp", text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def save_pools(cn_proxies: list[Proxy], foreign_proxies: list[Proxy]) -> dict[str, Path]:
    """保存两个代理池，返回输出文件路径映射。"""
    out_dir = Path(config.OUTPUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)

    cn_txt = out_dir / f"{config.CN_PREFIX}.txt"
    cn_json = out_dir / f"{config.CN_PREFIX}.json"
    foreign_txt = out_dir / f"{config.FOREIGN_PREFIX}.txt"
    foreign_json = out_dir / f"{config.FOREIGN_PREFIX}.json"

    _atomic_write_text(cn_txt, [p.endpoint for p in cn_proxies])
    _atomic_write_json(cn_json, [p.to_dict() for p in cn_proxies])

    _atomic_write_text(foreign_txt, [p.endpoint for p in foreign_proxies])
    _atomic_write_json(foreign_json, [p.to_dict() for p in foreign_proxies])

    logger.info("国内代理池已保存：%s (%d 条) / %s", cn_txt, len(cn_proxies), cn_json)
    logger.info("国外代理池已保存：%s (%d 条) / %s", foreign_txt, len(foreign_proxies), foreign_json)
    return {
        "cn_txt": cn_txt,
        "cn_json": cn_json,
        "foreign_txt": foreign_txt,
        "foreign_json": foreign_json,
    }
