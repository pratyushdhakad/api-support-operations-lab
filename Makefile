.PHONY: run test pipeline registry monitor incidents evaluate

registry:
	PYTHONPATH=src python3 -m api_support_operations.pipeline

monitor:
	PYTHONPATH=src python3 -m api_support_operations.monitoring_pipeline

incidents: monitor
	PYTHONPATH=src python3 -m api_support_operations.incident_pipeline

evaluate: incidents
	PYTHONPATH=src python3 -m api_support_operations.evaluation_pipeline

run: registry evaluate

test:
	PYTHONPATH=src python3 -m unittest discover -s tests -v

pipeline: run test
