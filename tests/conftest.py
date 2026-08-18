"""Фикстуры сценариев: api, admin, regular_user.

Здесь живёт «инфраструктура сценария» — подготовка сущностей и их
очистка. Тест-разработчик просто объявляет нужные фикстуры параметрами
теста и пишет шаги.
"""
from __future__ import annotations

import pytest

from src import generate
from src.api.gateway import Gateway

_PASSWORD = "Test12345!"


@pytest.fixture(scope="function")
def api() -> Gateway:
    """Готовый фасад api-gateway (без аутентификации)."""
    return Gateway()


@pytest.fixture(scope="function")
def admin(api: Gateway):
    """Администратор: регистрация -> setAdmin -> повторный login (admin-токен)."""
    email = generate.unique_email()
    username = f"admin_{generate.uuid4()[:6]}"
    ctx = api.create_admin(email, _PASSWORD, username)
    yield ctx
    _safe_delete(api, ctx)


@pytest.fixture(scope="function")
def regular_user(api: Gateway):
    """Обычный зарегистрированный пользователь (без прав администратора)."""
    email = generate.unique_email()
    username = f"user_{generate.uuid4()[:6]}"
    ctx = api.register(email, _PASSWORD, username)
    yield ctx
    _safe_delete(api, ctx)


def _safe_delete(api: Gateway, ctx) -> None:
    """Безусловная очистка пользователя в teardown (не маскируем ошибки теста)."""
    try:
        api.delete_user(ctx, ctx.user_id)
    except Exception:  # noqa: BLE001 - стек мог быть остановлен после теста
        pass
