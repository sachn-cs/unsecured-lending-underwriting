.PHONY: install dev test lint typecheck clean build dist

install:
	pip install -e .

dev:
	pip install -e ".[dev,risk,postgres]"

test:
	python -m pytest tests/ -v --tb=short -q

lint:
	ruff check underwrite/

typecheck:
	mypy underwrite/

build:
	python -m build

dist: build
	@echo "Wheel and sdist in dist/"

clean:
	rm -rf build/ dist/ *.egg-info .pytest_cache __pycache__
	find . -name '*.pyc' -delete
	find . -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
	rm -rf .mypy_cache .ruff_cache
