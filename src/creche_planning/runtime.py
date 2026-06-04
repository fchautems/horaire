from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .domain import DEFAULT_RUN_CONFIG

def parse_aliases(values: list[str]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"Alias invalide: {value}. Format attendu: ANCIEN=NOUVEAU")
        old, new = value.split("=", 1)
        aliases[old.strip()] = new.strip()
    return aliases


def load_run_config(path: Path | None) -> tuple[dict[str, Any], Path]:
    if path is None:
        return {}, Path.cwd()
    path = path.resolve()
    with path.open("r", encoding="utf-8") as handle:
        loaded = json.load(handle)
    if not isinstance(loaded, dict):
        raise ValueError("Le fichier de configuration doit contenir un objet JSON.")
    config = dict(DEFAULT_RUN_CONFIG)
    config.update(loaded)
    return config, path.parent


def resolve_config_path(value: str | Path | None, base_dir: Path) -> Path | None:
    if value is None or str(value).strip() == "":
        return None
    path = Path(value)
    if path.is_absolute():
        return path.resolve()
    return (base_dir / path).resolve()


def timestamped_path(path: Path | None, timestamp: str | None) -> Path | None:
    if path is None or not timestamp:
        return path
    if "{timestamp}" in str(path):
        return Path(str(path).replace("{timestamp}", timestamp))
    return path.with_name(f"{path.stem}_{timestamp}{path.suffix}")


def config_aliases(value: Any) -> dict[str, str]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return {str(key).strip(): str(val).strip() for key, val in value.items() if str(key).strip()}
    if isinstance(value, list):
        return parse_aliases([str(item) for item in value])
    raise ValueError("type_aliases doit etre un objet JSON ou une liste d'alias ANCIEN=NOUVEAU.")


def pick(cli_value: Any, config: dict[str, Any], key: str, default: Any = None) -> Any:
    if cli_value is not None:
        return cli_value
    return config.get(key, default)


def emit_progress(percent: int, message: str) -> None:
    print(f"PROGRESS|{max(0, min(100, int(percent)))}|{message}", flush=True)

