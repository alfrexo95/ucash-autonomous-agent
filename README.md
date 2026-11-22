# 🦅 Predator U.CASH Autonomous Agent

Multi-modal AI agent and service marketplace fulfilled through U.CASH Agent HTTP-402 resources. 11 services, multi-coin U.CASH checkout, local PyTorch inference, zero external paid APIs. There is no direct x402 service endpoint: payments must use the published U.CASH checkout resources so the fulfillment workers can detect settled transactions.

## Live
- Landing Page: https://alfrexo95.github.io/ucash-autonomous-agent/
- OpenAPI: https://predator-x402-proxy.alfrexo95.workers.dev/openapi.json

## 🔒 Encrypted Private Deliveries
Every order requires a Claim Code. Format: `[Claim: your_password] your_payload`
The output is encrypted with `sha256(tx_id + "-" + claim_code)` and saved as `deliveries/<sha256[:16]>.enc`.
To decrypt: `python3 decrypt_delivery.py <tx_id> <claim_code>`

## 11 Services
Text (Qwen2.5-Coder-3B): PromptForge ($2), Sentinel Code Review ($5), DeepIntel Research ($3)
Multimodal: TextLens OCR ($1), EmotionPulse ($2), VisionTag ($2), Polyglot Bridge ($3), BriefCraft ($4), EchoScript ($6), ObjectScope ($8), ChainGuard ($20)

## Architecture
- Payments: U.CASH (HTTP 402)
- Webhook: Cloudflare Worker
- Execution: GitHub Actions (text-agent every 30 minutes; multimodal agent hourly)\n- Hub discovery: https://x402-api-wigc.onrender.com/public/ucash-services (catalog and hosted checkout links)\n- Workers register marketplace-only presence; they do not claim Hub task-queue jobs. U.CASH settled transactions trigger fulfillment.
- AI: Local HuggingFace Transformers
- State: atomic merged JSON (ucash_state.json)
- Security: SSRF-protected downloads, encrypted deliveries, mandatory claim codes
