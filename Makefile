.PHONY: up migrate seed-demo test-unit test-integration acceptance down
ITERATION ?= 1
STEP ?= S6
ENV_FILE ?= /tmp/itxiaRAG.env
COMPOSE_PROJECT_NAME ?= itxia-phase1
DEMO_TOKEN_DIR ?= /tmp/itxia-demo-tokens
COMPOSE = docker compose --env-file "$(ENV_FILE)" -p "$(COMPOSE_PROJECT_NAME)"
ifneq ($(ITERATION),1)
$(error ITERATION=$(ITERATION) 尚未实现)
endif

up:
	$(COMPOSE) up -d --build --wait
migrate:
	$(COMPOSE) exec -T app python manage.py migrate --noinput
	$(COMPOSE) exec -T app python manage.py kb_init --profiles profiles/iteration1
seed-demo:
	$(COMPOSE) exec -T app python manage.py kb_seed_demo --confirm-demo --token-dir "$(DEMO_TOKEN_DIR)"
test-unit:
	$(COMPOSE) exec -T app python -m pytest tests/unit tests/contract -q
test-integration:
	$(COMPOSE) exec -T app python -m pytest tests/integration -q
acceptance:
	$(COMPOSE) exec -T app python scripts/acceptance.py --step "$(STEP)"
down:
	$(COMPOSE) down
