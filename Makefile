.PHONY: test lint smoke

test:
	python3 -m pytest

lint:
	python3 -m py_compile $$(find src tests -name '*.py')

smoke:
	PYTHONPATH=src python3 -m nowhere.cli --help
