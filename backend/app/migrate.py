"""数据库迁移入口（Alembic）。

两种场景都覆盖：
1. 新库：直接 `upgrade head` 建表，并写入 alembic_version。
2. 老库（本项目早期用 CREATE TABLE 手搓的）：检测到业务表但没有 alembic_version，
   先按现有列判定基线并 `stamp`，再升级到最新版本——不丢数据、不重复建表。
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from .config import settings

log = logging.getLogger("director.migrate")

BACKEND_DIR = Path(__file__).resolve().parents[1]
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"
ALEMBIC_DIR = BACKEND_DIR / "alembic"


def db_url() -> str:
    env = os.environ.get("DIRECTOR_DB_URL")
    if env:
        return env
    db_path = Path(settings.paths["data"]) / "director.db"
    return f"sqlite:///{db_path.as_posix()}"


def _config(url: str) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(ALEMBIC_DIR))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def _legacy_baseline(engine) -> str | None:
    """返回需要 stamp 的 revision；不是老库则返回 None。"""
    tables = set(inspect(engine).get_table_names())
    if not tables or "alembic_version" in tables:
        return None
    if "projects" not in tables:
        return None
    cols = {c["name"] for c in inspect(engine).get_columns("shots")} if "shots" in tables else set()
    if {"values_json", "last_frame"} <= cols:
        return "0002_shot_values"
    return "0001_initial"


def ensure_schema() -> None:
    url = db_url()
    engine = create_engine(url)
    try:
        baseline = _legacy_baseline(engine)
        cfg = _config(url)
        if baseline:
            log.warning("检测到旧版数据库，按 %s 建立基线", baseline)
            command.stamp(cfg, baseline)
        command.upgrade(cfg, "head")
    finally:
        engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ensure_schema()
    print(f"schema is up to date: {db_url()}")
