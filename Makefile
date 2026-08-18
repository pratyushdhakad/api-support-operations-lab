.PHONY: run test pipeline registry monitor incidents

registry:
	PYTHONPATH=src python3 -m api_support_operations.pipeline

monitor:
	PYTHONPATH=src python3 -m api_support_operations.monitoring_pipeline

incidents: monitor
	PYTHONPATH=src python3 -m api_support_operations.incident_pipeline

run: registry incidents

test:
	PYTHONPATH=src python3 -m unittest discover -s tests -v

pipeline: run test
