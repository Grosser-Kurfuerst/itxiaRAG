PYTHON ?= .venv/bin/python
.PHONY: run run-mcp migrate test test-unit test-integration
run:
	$(PYTHON) manage.py runserver 127.0.0.1:8000
run-mcp:
	$(PYTHON) -m uvicorn mcp_server.asgi:app --host 127.0.0.1 --port 8001
migrate:
	$(PYTHON) manage.py migrate
test:
	$(PYTHON) -m pytest -q
test-unit:
	$(PYTHON) -m pytest tests/unit -q
test-integration:
	$(PYTHON) -m pytest tests/integration -q
