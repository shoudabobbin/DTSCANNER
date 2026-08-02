"""Config loading with attribute-style access."""
from __future__ import annotations

import os
from pathlib import Path

import yaml


class Cfg(dict):
    """dict that also supports cfg.key access."""

    def __getattr__(self, item):
        try:
            v = self[item]
        except KeyError as e:
            raise AttributeError(item) from e
        return Cfg(v) if isinstance(v, dict) else v

    def get_path(self, dotted: str, default=None):
        node = self
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return Cfg(node) if isinstance(node, dict) else node


def load_config(path: str | os.PathLike | None = None) -> Cfg:
    path = Path(path) if path else Path(__file__).resolve().parents[1] / "config.yaml"
    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    cfg = Cfg(raw)
    cfg["_root"] = str(Path(path).resolve().parent)
    return cfg


def resolve(cfg: Cfg, relative: str) -> Path:
    """Resolve a config-declared path relative to the project root."""
    p = Path(relative)
    return p if p.is_absolute() else Path(cfg["_root"]) / p
