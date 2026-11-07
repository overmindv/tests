# =====================================================================
# overmindv/tests — Makefile e2e-тестов
#
# Принцип: разработчик работает с двумя командами — `make setup`
# (один раз) и `make test`. Подъём стека делегируется в `infra`
# (docker-compose живёт в одном месте, не дублируем его здесь).
# =====================================================================

SHELL := /bin/bash
VENV := .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
PYTEST := $(VENV)/bin/pytest

# Путь к репозиторию infra (там docker-compose и целевые сервисы).
INFRA_DIR ?= ../infra
# Путь к .env текущего репозитория (подтягивается в стек infra ниже — см. up)
ENV_FILE ?= .env
COMPOSE := docker compose --env-file $(INFRA_DIR)/$(ENV_FILE) -f $(INFRA_DIR)/docker-compose.yml

PYTEST_ARGS ?= tests

.DEFAULT_GOAL := help

.PHONY: help setup install up down clean test lint lint-check ci allure

## setup: создать venv и установить зависимости (выполнить один раз)
setup:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt

## install: переустановить зависимости в существующем venv
install:
	$(PIP) install -r requirements.txt

## up: собрать и запустить весь стек (делегируется в infra) с ожиданием готовности
up:
	@if [ ! -f $(INFRA_DIR)/$(ENV_FILE) ]; then \
		cd $(INFRA_DIR) && make init ENV_FILE=$(ENV_FILE); \
	fi
	cd $(INFRA_DIR) && make up ENV_FILE=$(ENV_FILE)

## down: остановить стек и сохранить данные (делегируется в infra)
down:
	cd $(INFRA_DIR) && make down ENV_FILE=$(ENV_FILE)

## clean: остановить стек и удалить локальные базы (делегируется в infra)
clean:
	cd $(INFRA_DIR) && make clean ENV_FILE=$(ENV_FILE)

## test: прогнать e2e-тесты (подразумевается, что стек уже поднят: make up)
test:
	$(PYTEST) $(PYTEST_ARGS)

## allure: сгенерировать HTML-отчёт из allure-results
allure:
	$(VENV)/bin/allure generate allure-results -o allure-report --clean

## lint: автофикс форматирования и линтинга
lint:
	$(VENV)/bin/ruff format .
	$(VENV)/bin/ruff check . --fix

## lint-check: проверить формат и линтинг без изменений
lint-check:
	$(VENV)/bin/ruff format . --check
	$(VENV)/bin/ruff check .

## ci: полный прогон, как в CI (setup -> up -> test -> allure)
ci: setup up test allure

## help: показать справку по таргетам
help:
	@grep -E '^## ' $(MAKEFILE_LIST) | sed 's/## //' | column -t -s ':'

# Браузерная симуляция пользователей — отдельна от существующего pytest e2e.
SIMULATION_DIR := user-simulation
.PHONY: simulation-setup simulation-list simulation-smoke simulation-local simulation-live simulation-report

## simulation-setup: установить фиксированные npm-зависимости и Chromium
simulation-setup:
	cd $(SIMULATION_DIR) && npm ci && npx playwright install chromium

## simulation-list: показать сценарии и устройства без запуска браузера
simulation-list:
	cd $(SIMULATION_DIR) && npm run test:list

## simulation-smoke: UI smoke на SIM_BASE_URL (GraphQL намеренно недоступен)
simulation-smoke:
	cd $(SIMULATION_DIR) && npm test

## simulation-local: UI smoke с временным Vite на 127.0.0.1:5174
simulation-local:
	cd $(SIMULATION_DIR) && SIM_START_FRONTEND=1 npm test

## simulation-live: настоящий UI journey на выделенном стеке и тестовых аккаунтах
simulation-live:
	cd $(SIMULATION_DIR) && npm run test:live

## simulation-report: открыть HTML-отчёт последнего smoke-прогона
simulation-report:
	cd $(SIMULATION_DIR) && npm run report

.PHONY: simulation-check
## simulation-check: проверить TypeScript браузерных сценариев
simulation-check:
	cd $(SIMULATION_DIR) && npm run typecheck

.PHONY: simulation-privacy
## simulation-privacy: проверить все артефакты намеренных падений на утечку синтетических секретов
simulation-privacy:
	cd $(SIMULATION_DIR) && npm run test:privacy
