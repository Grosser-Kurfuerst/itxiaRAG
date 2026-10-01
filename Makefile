.PHONY: up migrate test-unit test-integration acceptance down
ITERATION ?= 1
STEP ?= S6
ENV_FILE ?= /tmp/itxiaRAG.env
COMPOSE_PROJECT_NAME ?= itxia-phase1
COMPOSE = docker compose --env-file "$(ENV_FILE)" -p "$(COMPOSE_PROJECT_NAME)"
ifneq ($(ITERATION),1)
$(error ITERATION=$(ITERATION) 尚未实现)
endif

up:
	$(COMPOSE) up -d --build --wait
migrate:
	$(COMPOSE) exec -T app python manage.py migrate --noinput
test-unit:
	$(COMPOSE) exec -T app python -m pytest tests/unit tests/contract -q
test-integration:
	$(COMPOSE) exec -T app python -m pytest tests/integration -q
acceptance:
	$(COMPOSE) exec -T app python scripts/acceptance.py --step "$(STEP)"
down:
	$(COMPOSE) down
