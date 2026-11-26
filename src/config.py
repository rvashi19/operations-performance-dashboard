"""Configuration: YAML files for behaviour, environment variables for connection details."""
import logging
import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


def load_yaml(name: str) -> dict:
    with open(ROOT / "config" / name, encoding="utf-8") as f:
        return yaml.safe_load(f)


def settings() -> dict:
    return load_yaml("settings.yaml")


def validation_rules() -> dict:
    return load_yaml("validation_rules.yaml")


def database_url() -> str:
    if os.getenv("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    e = os.environ.get
    return (f"postgresql+psycopg://{e('POSTGRES_USER', 'ops')}:{e('POSTGRES_PASSWORD', 'ops_local_dev')}"
            f"@{e('POSTGRES_HOST', 'localhost')}:{e('POSTGRES_PORT', '5433')}/{e('POSTGRES_DB', 'ops311')}")


def setup_logging() -> None:
    """Structured key=value logs to console and logs/pipeline.log."""
    (ROOT / "logs").mkdir(exist_ok=True)
    fmt = "ts=%(asctime)s level=%(levelname)s logger=%(name)s msg=%(message)s"
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format=fmt,
        handlers=[logging.StreamHandler(), logging.FileHandler(ROOT / "logs" / "pipeline.log", encoding="utf-8")],
        force=True,
    )
