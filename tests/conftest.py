"""Фикстуры сценариев: api, admin, regular_user.

Здесь живёт «инфраструктура сценария» — подготовка сущностей и их
очистка. Тест-разработчик просто объявляет нужные фикстуры параметрами
теста и пишет шаги.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack

import pytest

from src.api.gateway import AuthContext, Gateway
from src.scenario_data import ScenarioData


@pytest.fixture(scope="function")
def api() -> Iterator[Gateway]:
    """Готовый фасад api-gateway (без аутентификации)."""
    gateway = Gateway()
    try:
        yield gateway
    finally:
        gateway.gql.session.close()


@pytest.fixture(scope="function")
def admin(api: Gateway) -> AuthContext:
    return api.login_bootstrap_superuser()


@pytest.fixture(scope="function")
def scenario_data(api: Gateway) -> Iterator[ScenarioData]:
    with ExitStack() as cleanup:
        yield ScenarioData(api, cleanup)


@pytest.fixture(scope="function")
def regular_user(scenario_data: ScenarioData) -> AuthContext:
    return scenario_data.user()
