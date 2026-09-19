.PHONY: verify test benchmark api app demo infra-validate
verify:
	python scripts/verify.py
test:
	python -m pytest tests -q
benchmark:
	python scripts/benchmark.py
api:
	python -m services.api.server 8000
app:
	python scripts/app.py
demo:
	python scripts/demo.py
infra-validate:
	python scripts/validate_infra.py
