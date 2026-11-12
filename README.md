# Predator U.CASH Agent Elite (starter)

Python stdlib HTTP server + official zero-dependency `agents-u-cash` SDK.

## Important status
This starter creates genuine U.CASH checkout resources and exposes a service catalog.
It **does not claim a payment has settled**, and it does not release paid deliverables yet.
Do not advertise fulfillment as automatic until a settlement verifier/webhook handler is
implemented and tested against U.CASH's current event schema. U.CASH payment is non-custodial:
settlements go to your configured wallet; the platform is not a wallet balance.

## Setup (Termux)
```bash
pkg update && pkg install python git
git clone YOUR_REPO_URL predator-ucash-agent
cd predator-ucash-agent
python -m pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
```
Set secrets in shell (do not commit `.env`):
```bash
export UCASH_API_KEY='uxc_...'
python setup_ucash.py
python agent.py
```
Check:
```bash
curl http://127.0.0.1:8080/health
curl http://127.0.0.1:8080/catalog
curl -X POST http://127.0.0.1:8080/order \
 -H 'Content-Type: application/json' \
 -d '{"service":"Predator Code Analyzer","task":"Analyze this Python code"}'
```
The response includes a real checkout URL. A created checkout/resource is not proof of payment.

## Services
- `code_review` — automated code review/triage (not formal audit)
- `research` — evidence-based research (baseline currently requires supplied sources)
- `prompt_engineering` — prompts and automation plans

## GitHub Actions
Use Actions for scheduled maintenance, smoke tests, or catalog/resource provisioning—not a
permanent HTTP server. GitHub-hosted runners are ephemeral and stop after the job. Add
`UCASH_API_KEY` as a repository Actions secret; never put it in YAML or logs.

## Production checklist before launch
1. Configure wallet and verify accepted asset in U.CASH dashboard.
2. Confirm SDK methods/response shape against the installed package and official API.
3. Implement settlement verification from `GET /v1/settlements` or signed webhook.
4. Persist raw settlement IDs and deduplicate (unique DB key).
5. Only after verified settlement, execute job and make result available via expiring,
   authenticated delivery URL.
6. Add rate limits, payload limits, privacy/retention controls, isolated code execution
   (never run customer code in the server process), and LLM backend with budget caps.
7. Test sandbox first; do not expose public server without TLS/reverse proxy and auth.

## Termux bootstrap
Run `bash termux_setup.sh`; prompts securely for account credentials and saves API key in
`~/.ucash_api_key` mode 600. Heavy packages in requirements-heavy.txt install only in
GitHub Actions when manually dispatched with `mode=heavy_ai`. Actions runners are ephemeral,
not persistent AI hosting; large model downloads can exceed runtime/cache limits.
