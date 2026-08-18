"""Генерация тестовых данных: уникальные email/имена/uuid.

Используется mimesis (детерминированный при GENERATE_UNIQUE_DATA=false)
и uuid4 для уникальных идентификаторов. Данные должны быть уникальными,
чтобы тесты были изолированы и не конфликтовали между собой.
"""
from __future__ import annotations

import uuid

from mimesis import Person
from mimesis.locales import Locale

from src.configuration import config

# Фиксированный пул email-доменов — не теряем письма реальных юзеров.
_DOMAINS = ("example.com", "exaple.ru", "test.local")

_person = Person(locale=Locale.RU)


def unique_email() -> str:
    """Уникальный email вида <slug>-<hex>@<domain>."""
    return f"{_slug()}-{uuid4()[:8]}@{_random_domain()}"


def random_username() -> str:
    if config.GENERATE_UNIQUE_DATA:
        return f"user_{_slug()}_{uuid4()[:6]}"
    return _slug()


def random_first_name() -> str:
    return _person.first_name()


def random_last_name() -> str:
    return _person.last_name()


def uuid4() -> str:
    """Строковый UUID4 (без дефисов) — для idempotency-ключей и ID."""
    return str(uuid.uuid4()).replace("-", "")


def _slug() -> str:
    return _person.username().replace(".", "_").lower()


def _random_domain() -> str:
    import random

    return random.choice(_DOMAINS)
