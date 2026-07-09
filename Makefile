VENV = venv/bin
PYTHON = $(VENV)/python
MANAGE = $(PYTHON) manage.py

.PHONY: dev migrate shell test

## Start the development server
dev:
	$(MANAGE) runserver

## Run all pending migrations
migrate:
	$(MANAGE) migrate

## Open Django shell
shell:
	$(MANAGE) shell

## Run tests
test:
	$(MANAGE) test tickets organizations --keepdb
