"""Tests for the connector registry and its auto-discovery."""
import pytest

from agent.connectors import registry
from agent.connectors.base import BaseConnector
from agent.connectors.manifold import ManifoldConnector
from agent.connectors.synthetic import SyntheticConnector


def test_builtins_are_discovered():
    names = registry.available()
    assert {"manifold", "polymarket", "synthetic"}.issubset(set(names))


def test_create_returns_the_right_type():
    conn = registry.create("manifold")
    assert isinstance(conn, ManifoldConnector)
    assert isinstance(conn, BaseConnector)


def test_create_is_case_insensitive():
    assert isinstance(registry.create("SYNTHETIC"), SyntheticConnector)


def test_create_forwards_only_accepted_kwargs():
    # synthetic accepts `seed`; the junk kwarg must be dropped, not raised.
    conn = registry.create("synthetic", seed=3, totally_unknown_kwarg=123)
    assert isinstance(conn, SyntheticConnector)


def test_create_unknown_raises():
    with pytest.raises(KeyError):
        registry.create("does-not-exist")


def test_double_registration_is_rejected():
    with pytest.raises(ValueError):

        @registry.register("manifold")
        def _factory():  # pragma: no cover
            raise AssertionError("should not be called")
