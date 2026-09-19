# Environment setup (for the teammate holding AWS keys)

## Local development — no keys needed

File storage, deterministic parser, no AWS calls:

```bash
pip install -e ".[dev]"
python scripts/verify.py
python -m services.api.server 8000
```

## Deploying — keys needed once

1. Copy `.env.example` to `.env` (gitignored — never commit it) and fill:
   `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`,
   `AMPLIFY_TOKEN` (GitHub token for Amplify hosting only).
2. `source .env` (bash) or load it in PowerShell:
   `Get-Content .env | ForEach-Object { if ($_ -match '^\w+=') { $k,$v = $_ -split '=',2; Set-Item "env:$k" $v } }`
3. `bash infra/deploy.sh` (or `infra/deploy.ps1`). The script writes the
   `ApiUrl` output — put it in `.env` as `API_URL` for smoke tests and UI config.
4. CI (`.github/workflows/ci.yml`) needs **no AWS secrets**: verify, pytest,
   benchmark, and infra-validate all run credential-free.

## Key hygiene

- Least-privilege IAM user for deploys; Bedrock scoped to the inference
  profile + model (see `infra/template.yaml`).
- Rotate `AMPLIFY_TOKEN` after first deploy; it is only used at stack creation.
- Never print `.env`; `docs/cost.md` estimates spend before you deploy.
