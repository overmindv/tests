"""Единый конфиг тестов: читается из переменных окружения (и .env).

Все параметры — атрибуты класса. Значения подтягиваются из env
посредством `helper.env`. Допускается переопределение в тестах
(например, для инъекции фейкового клиента), но менять атрибуты класса
на лету не нужно — значения читаются при обращении.
"""
from __future__ import annotations

from src.helper import env


class Config:
    # Базовый URL api-gateway (главная точка входа e2e-сценариев).
    BASE_URL: str = env.get("BASE_URL", "http://localhost:8081")  # type: ignore[assignment]

    # Путь GraphQL-эндпоинта api-gateway.
    GRAPHQL_PATH: str = env.get("GRAPHQL_PATH", "/graphql")  # type: ignore[assignment]

    # Таймауты HTTP (секунды).
    API_READ_TIMEOUT: int = env.get_int("API_READ_TIMEOUT", 30)
    API_CONNECT_TIMEOUT: int = env.get_int("API_CONNECT_TIMEOUT", 10)

    # true — генерировать уникальные данные; false — фиксированные.
    GENERATE_UNIQUE_DATA: bool = env.get_bool("GENERATE_UNIQUE_DATA", True)

    # Ожидание готовности сервисов.
    SERVICE_READY_ATTEMPTS: int = env.get_int("SERVICE_READY_ATTEMPTS", 30)
    SERVICE_READY_SLEEP: int = env.get_int("SERVICE_READY_SLEEP", 2)

    # Bootstrap-суперпользователь users-сервиса (сеется при старте стека из infra).
    # Используется фикстурой admin для admin-операций. Значения по умолчанию
    # совпадают с `infra/.env.example`, в CI/локально переопределяются в tests/.env.
    BOOTSTRAP_SUPERUSER_EMAIL: str = env.get("BOOTSTRAP_SUPERUSER_EMAIL", "admin@overmindv.com")  # type: ignore[assignment]
    BOOTSTRAP_SUPERUSER_USERNAME: str = env.get("BOOTSTRAP_SUPERUSER_USERNAME", "superadmin")  # type: ignore[assignment]
    BOOTSTRAP_SUPERUSER_PASSWORD: str = env.get(  # type: ignore[assignment]
        "BOOTSTRAP_SUPERUSER_PASSWORD",
        "98754dd033b152bb4a887141990259624f2861a792d86e33ecb0b7705d87a20a",
    )

    # Инфраструктура pytest (пробрасываются в addopts в CI).
    PYTEST_NUM_WORKERS: int = env.get_int("PYTEST_NUM_WORKERS", 0)
    PYTEST_RERUNS: int = env.get_int("PYTEST_RERUNS", 2)


config = Config()
