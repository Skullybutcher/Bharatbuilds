.PHONY: verify test benchmark api demo infra-validate
verify:
	python scripts/verify.py
test:
	python -m pytest tests -q
benchmark:
	python scripts/benchmark.py
api:
	python -m services.api.server 8000
demo:
	python scripts/demo.py
infra-validate:
	python scripts/validate_infra.py
