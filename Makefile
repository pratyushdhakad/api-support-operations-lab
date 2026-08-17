.PHONY: run test

run:
	PYTHONPATH=src python3 -m api_support_operations.pipeline

test:
	PYTHONPATH=src python3 -m unittest discover -s tests -v

