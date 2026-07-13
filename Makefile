VENV = venv/bin
PYTHON = $(VENV)/python
MANAGE = $(PYTHON) manage.py

.PHONY: dev migrate shell test ngrok

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

## Start ngrok tunnel on port 8000
ngrok:
	ngrok http 8000
