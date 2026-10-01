PYTHON ?= .venv/bin/python
.PHONY: run migrate test test-unit test-integration
run:
	$(PYTHON) manage.py runserver 127.0.0.1:8000
migrate:
	$(PYTHON) manage.py migrate
test:
	$(PYTHON) -m pytest -q
test-unit:
	$(PYTHON) -m pytest tests/unit -q
test-integration:
	$(PYTHON) -m pytest tests/integration -q
