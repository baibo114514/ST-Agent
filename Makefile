install:
	pip install uv
	uv sync

DOCKER_COMPOSE ?= docker compose

ifeq ($(OS),Windows_NT)
VENV_PYTHON ?= .venv/Scripts/python.exe
else
VENV_PYTHON ?= .venv/bin/python
endif

set-env:
	@if [ -z "$(ENV)" ]; then \
		echo "ENV is not set. Usage: make set-env ENV=development|staging|production"; \
		exit 1; \
	fi
	@if [ "$(ENV)" != "development" ] && [ "$(ENV)" != "staging" ] && [ "$(ENV)" != "production" ] && [ "$(ENV)" != "test" ]; then \
		echo "ENV is not valid. Must be one of: development, staging, production, test"; \
		exit 1; \
	fi
	@echo "Setting environment to $(ENV)"
	@bash -c "source scripts/set_env.sh $(ENV)"

prod:
	@echo "Starting server in production environment"
	@bash -c "source scripts/set_env.sh production && ./.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --loop uvloop"

staging:
	@echo "Starting server in staging environment"
	@bash -c "source scripts/set_env.sh staging && ./.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --loop uvloop"

dev:
	@echo "Starting server in development environment"
	@$(VENV_PYTHON) scripts/dev_server.py

dev-backend:
	@echo "Starting backend control-plane on http://127.0.0.1:8000"
	@$(VENV_PYTHON) scripts/dev_server.py

dev-knowledge:
	@echo "Starting knowledge-service on http://127.0.0.1:8010"
	@$(VENV_PYTHON) scripts/knowledge_server.py

dev-frontend:
	@echo "Starting frontend on http://127.0.0.1:5174"
	@$(VENV_PYTHON) scripts/frontend_server.py

dev-infra:
	@ENV_FILE=.env.development; \
	if [ ! -f $$ENV_FILE ]; then \
		echo "Environment file $$ENV_FILE not found. Please create it."; \
		exit 1; \
	fi; \
	APP_ENV=development $(DOCKER_COMPOSE) --env-file $$ENV_FILE up -d db

dev-embedding:
	@ENV_FILE=.env.development; \
	if [ ! -f $$ENV_FILE ]; then \
		echo "Environment file $$ENV_FILE not found. Please create it."; \
		exit 1; \
	fi; \
	APP_ENV=development $(DOCKER_COMPOSE) --env-file $$ENV_FILE up -d ollama
	@$(DOCKER_COMPOSE) --env-file .env.development exec ollama ollama pull bge-m3

# Evaluation commands
eval:
	@echo "Running retrieval evaluation"
	@bash -c "source scripts/set_env.sh ${ENV:-development} && python -m services.evaluation_service.main"

eval-quick:
	@echo "Running evaluation with default settings"
	@bash -c "source scripts/set_env.sh ${ENV:-development} && python -m services.evaluation_service.main --limit 8"

eval-no-report:
	@echo "Running retrieval evaluation without generating report"
	@bash -c "source scripts/set_env.sh ${ENV:-development} && python -m services.evaluation_service.main --limit 8 --no-report"

lint:
	ruff check .

format:
	ruff format .

clean:
	rm -rf .venv
	rm -rf __pycache__
	rm -rf .pytest_cache

docker-build:
	docker build -t fastapi-langgraph-template .

docker-build-env:
	@if [ -z "$(ENV)" ]; then \
		echo "ENV is not set. Usage: make docker-build-env ENV=development|staging|production"; \
		exit 1; \
	fi
	@if [ "$(ENV)" != "development" ] && [ "$(ENV)" != "staging" ] && [ "$(ENV)" != "production" ]; then \
		echo "ENV is not valid. Must be one of: development, staging, production"; \
		exit 1; \
	fi
	@./scripts/build-docker.sh $(ENV)

docker-run:
	@ENV_FILE=.env.development; \
	if [ ! -f $$ENV_FILE ]; then \
		echo "Environment file $$ENV_FILE not found. Please create it."; \
		exit 1; \
	fi; \
	APP_ENV=development $(DOCKER_COMPOSE) --env-file $$ENV_FILE up -d --build db app

docker-run-env:
	@if [ -z "$(ENV)" ]; then \
		echo "ENV is not set. Usage: make docker-run-env ENV=development|staging|production"; \
		exit 1; \
	fi
	@if [ "$(ENV)" != "development" ] && [ "$(ENV)" != "staging" ] && [ "$(ENV)" != "production" ]; then \
		echo "ENV is not valid. Must be one of: development, staging, production"; \
		exit 1; \
	fi
	@ENV_FILE=.env.$(ENV); \
	if [ ! -f $$ENV_FILE ]; then \
		echo "Environment file $$ENV_FILE not found. Please create it."; \
		exit 1; \
	fi; \
	APP_ENV=$(ENV) $(DOCKER_COMPOSE) --env-file $$ENV_FILE up -d --build db app
	# @./scripts/ensure-db-user.sh $(ENV)

docker-logs:
	@if [ -z "$(ENV)" ]; then \
		echo "ENV is not set. Usage: make docker-logs ENV=development|staging|production"; \
		exit 1; \
	fi
	@if [ "$(ENV)" != "development" ] && [ "$(ENV)" != "staging" ] && [ "$(ENV)" != "production" ]; then \
		echo "ENV is not valid. Must be one of: development, staging, production"; \
		exit 1; \
	fi
	@ENV_FILE=.env.$(ENV); \
	if [ ! -f $$ENV_FILE ]; then \
		echo "Environment file $$ENV_FILE not found. Please create it."; \
		exit 1; \
	fi; \
	APP_ENV=$(ENV) $(DOCKER_COMPOSE) --env-file $$ENV_FILE logs -f app db

docker-stop:
	@if [ -z "$(ENV)" ]; then \
		echo "ENV is not set. Usage: make docker-stop ENV=development|staging|production"; \
		exit 1; \
	fi
	@if [ "$(ENV)" != "development" ] && [ "$(ENV)" != "staging" ] && [ "$(ENV)" != "production" ]; then \
		echo "ENV is not valid. Must be one of: development, staging, production"; \
		exit 1; \
	fi
	@ENV_FILE=.env.$(ENV); \
	if [ ! -f $$ENV_FILE ]; then \
		echo "Environment file $$ENV_FILE not found. Please create it."; \
		exit 1; \
	fi; \
	APP_ENV=$(ENV) $(DOCKER_COMPOSE) --env-file $$ENV_FILE down

# Docker Compose commands for the entire stack
docker-compose-up:
	@if [ -z "$(ENV)" ]; then \
		echo "ENV is not set. Usage: make docker-compose-up ENV=development|staging|production"; \
		exit 1; \
	fi
	@if [ "$(ENV)" != "development" ] && [ "$(ENV)" != "staging" ] && [ "$(ENV)" != "production" ]; then \
		echo "ENV is not valid. Must be one of: development, staging, production"; \
		exit 1; \
	fi
	@ENV_FILE=.env.$(ENV); \
	if [ ! -f $$ENV_FILE ]; then \
		echo "Environment file $$ENV_FILE not found. Please create it."; \
		exit 1; \
	fi; \
	APP_ENV=$(ENV) $(DOCKER_COMPOSE) --env-file $$ENV_FILE up -d

docker-compose-down:
	@if [ -z "$(ENV)" ]; then \
		echo "ENV is not set. Usage: make docker-compose-down ENV=development|staging|production"; \
		exit 1; \
	fi
	@ENV_FILE=.env.$(ENV); \
	if [ ! -f $$ENV_FILE ]; then \
		echo "Environment file $$ENV_FILE not found. Please create it."; \
		exit 1; \
	fi; \
	APP_ENV=$(ENV) $(DOCKER_COMPOSE) --env-file $$ENV_FILE down

docker-compose-logs:
	@if [ -z "$(ENV)" ]; then \
		echo "ENV is not set. Usage: make docker-compose-logs ENV=development|staging|production"; \
		exit 1; \
	fi
	@ENV_FILE=.env.$(ENV); \
	if [ ! -f $$ENV_FILE ]; then \
		echo "Environment file $$ENV_FILE not found. Please create it."; \
		exit 1; \
	fi; \
	APP_ENV=$(ENV) $(DOCKER_COMPOSE) --env-file $$ENV_FILE logs -f

# Help
help:
	@echo "Usage: make <target>"
	@echo "Targets:"
	@echo "  install: Install dependencies"
	@echo "  set-env ENV=<environment>: Set environment variables (development, staging, production, test)"
	@echo "  run ENV=<environment>: Set environment and run server"
	@echo "  prod: Run server in production environment"
	@echo "  staging: Run server in staging environment"
	@echo "  dev: Run server in development environment"
	@echo "  dev-backend: Run backend control-plane locally on port 8000"
	@echo "  dev-knowledge: Run knowledge-service locally on port 8010"
	@echo "  dev-frontend: Run static frontend locally on port 5174"
	@echo "  dev-infra: Run Docker infra only (Postgres)"
	@echo "  dev-embedding: Start Ollama and pull the bge-m3 embedding model"
	@echo "  test: Run tests"
	@echo "  clean: Clean up"
	@echo "  docker-build: Build default Docker image"
	@echo "  docker-build-env ENV=<environment>: Build Docker image for specific environment"
	@echo "  docker-run: Run default Docker container"
	@echo "  docker-run-env ENV=<environment>: Run Docker container for specific environment"
	@echo "  docker-logs ENV=<environment>: View logs from running container"
	@echo "  docker-stop ENV=<environment>: Stop and remove container"
	@echo "  docker-compose-up: Start the entire stack"
	@echo "  docker-compose-down: Stop the entire stack"
	@echo "  docker-compose-logs: View logs from all services"
