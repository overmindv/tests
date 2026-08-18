"""Сценарии аутентификации через api-gateway."""
import allure
import pytest

from src import asserts, generate

pytestmark = pytest.mark.e2e and pytest.mark.auth


@allure.title("Регистрация нового пользователя и повторный вход")
def test_register_and_login(api):
    """Регистрация возвращает токен и user; последующий login идентифицирует того же пользователя."""
    email = generate.unique_email()
    password = "Test12345!"
    username = f"auth_{generate.uuid4()[:6]}"

    registered = api.register(email, password, username)
    try:
        asserts.is_not_empty(registered.token, "При регистрации должен вернуться токен")
        asserts.equal(registered.is_admin, False, "Новый пользователь не администратор")

        logged = api.login(email, password)
        asserts.equal(logged.user_id, registered.user_id, "login возвращает того же пользователя")
        asserts.is_not_empty(logged.token, "При входе должен вернуться токен")
    finally:
        api.delete_user(registered, registered.user_id)


@allure.title("Повторная регистрация с тем же email отклоняется")
def test_register_duplicate_email(api):
    """Система не позволяет создать двух пользователей с одинаковым email."""
    email = generate.unique_email()
    password = "Test12345!"

    first = api.register(email, password, f"dup_{generate.uuid4()[:6]}")
    try:
        with pytest.raises(Exception):
            api.register(email, password, f"other_{generate.uuid4()[:6]}")
    finally:
        api.delete_user(first, first.user_id)
