"""Connector registry — the pluggable seam, made discoverable.

Every market connector decorates its class with ``@register("name")``.
``create("name", **kwargs)`` builds one by name, passing only the keyword
arguments that connector's ``__init__`` actually accepts, so a single
``Settings``-derived kwargs bag works for every connector.

Adding a platform is therefore:
  1. Drop a new module in ``agent/connectors/`` with a ``BaseConnector``
     subclass decorated ``@register("yourplatform")``.
  2. That's it — auto-discovery imports it and it shows up in ``available()``,
     the CLI, and the web dashboard's platform switch.

No engine, CLI, or web code needs to change. See ``docs/adding-a-connector.md``.
"""
from __future__ import annotations

import importlib
import inspect
import pkgutil
from collections.abc import Callable

from ..logging_setup import get_logger
from .base import BaseConnector

log = get_logger(__name__)

ConnectorFactory = Callable[..., BaseConnector]

_REGISTRY: dict[str, ConnectorFactory] = {}
_DISCOVERED = False

# Modules in agent/connectors/ that are not market connectors and should be
# skipped by auto-discovery.
_SKIP = {"base", "registry", "paper", "news", "news_fixtures", "social", "wallets"}


def register(name: str) -> Callable[[ConnectorFactory], ConnectorFactory]:
    """Class decorator: register a connector under ``name`` (case-insensitive)."""
    key = name.strip().lower()

    def _decorator(factory: ConnectorFactory) -> ConnectorFactory:
        if key in _REGISTRY and _REGISTRY[key] is not factory:
            raise ValueError(f"connector {name!r} is already registered")
        _REGISTRY[key] = factory
        return factory

    return _decorator


def _discover() -> None:
    """Import every connector module once so their @register decorators fire.

    A connector whose optional dependency is missing must not break discovery
    of the others, so import failures are logged and swallowed.
    """
    global _DISCOVERED
    if _DISCOVERED:
        return
    _DISCOVERED = True
    package = importlib.import_module("agent.connectors")
    for info in pkgutil.iter_modules(package.__path__):
        if info.name in _SKIP:
            continue
        try:
            importlib.import_module(f"agent.connectors.{info.name}")
        except Exception as e:  # pragma: no cover - optional-dep connectors
            log.debug("registry.discover_skipped", module=info.name, error=str(e))


def available() -> list[str]:
    """Sorted list of registered connector names."""
    _discover()
    return sorted(_REGISTRY)


def is_registered(name: str) -> bool:
    _discover()
    return name.strip().lower() in _REGISTRY


def create(name: str, **kwargs) -> BaseConnector:
    """Instantiate a connector by name.

    Only the kwargs the connector's ``__init__`` declares are forwarded
    (unless it accepts ``**kwargs``), so callers can pass a broad settings
    bag and each connector picks what it needs.
    """
    _discover()
    key = name.strip().lower()
    if key not in _REGISTRY:
        raise KeyError(f"unknown connector {name!r}. Available: {available()}")
    factory = _REGISTRY[key]

    sig = inspect.signature(factory)
    accepts_var_kw = any(
        p.kind is inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
    )
    if accepts_var_kw:
        return factory(**kwargs)
    allowed = {k: v for k, v in kwargs.items() if k in sig.parameters}
    return factory(**allowed)
