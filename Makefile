.PHONY: dev stop

dev:
	@lsof -ti :8000 | xargs kill -9 2>/dev/null; true
	.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --reload

stop:
	@lsof -ti :8000 | xargs kill -9 2>/dev/null; true
	@echo "stopped"
