import json, os, time, traceback, hashlib, re
from pathlib import Path
from agents_u_cash import AgentsUCash
from core_logic import get_hash, get_cache, set_cache, validate_python, validate_solidity

try:
    from ddgs import DDGS
except ImportError:
    from duckduckgo_search import DDGS

from transformers import pipeline
import torch

API_KEY = os.environ.get("UCASH_API_KEY", "")
# MODELO MEJORADO: Especializado en código (3B parámetros)
MODEL_NAME = os.environ.get("MODEL_NAME", "Qwen/Qwen2.5-Coder-3B-Instruct") 
RUN_HOURS = float(os.environ.get("RUN_HOURS", "0.25"))
POLL_SECONDS = int(os.environ.get("POLL_SECONDS", "60"))

STATE_FILE = Path("ucash_state.json")
DELIVERIES = Path("deliveries")
INBOX = Path("inbox")
DELIVERIES.mkdir(exist_ok=True)
INBOX.mkdir(exist_ok=True)

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

log(f"Cargando modelo {MODEL_NAME} (esto puede tardar)...")
generator = pipeline(
    "text-generation", 
    model=MODEL_NAME, 
    device="cpu", 
    torch_dtype=torch.float32, 
    trust_remote_code=True
)

def ask(system, user, max_tokens=1200):
    torch.manual_seed(42)
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    out = generator(msgs, max_new_tokens=max_tokens, do_sample=False, repetition_penalty=1.1)
    return out[0]["generated_text"][-1]["content"].strip()

def web_search(query, n=5):
    rows = []
    try:
        with DDGS() as d:
            for r in d.text(query, max_results=n):
                rows.append({"title": r.get("title"), "snippet": r.get("body"), "url": r.get("href")})
    except Exception as e:
        log(f"busqueda fallo: {e}")
    return rows

# --- SERVICIOS ---
def svc_prompt_engineering(order):
    return ask("You are an expert prompt engineer. Produce a production-ready system prompt.", order)

def svc_code_audit(order):
    # 1. Validación estática real
    if "pragma solidity" in order:
        is_valid, msg = validate_solidity(order)
    else:
        is_valid, msg = validate_python(order)
        
    # 2. Explicación por IA (el modelo Coder 3B es mucho mejor para esto)
    ai_explanation = ask(
        "You are a senior security auditor. Briefly explain the security implications of the following code. Do not invent issues.",
        order,
        800
    )
    return f"## Auditoría de Seguridad\n\n**Análisis Estático:** {msg}\n\n### Análisis de IA:\n{ai_explanation}"

def svc_data_research(order):
    sources = web_search(order)
    ctx = json.dumps(sources, ensure_ascii=False, indent=2)
    report = ask("You write factual reports using ONLY the sources provided.", f"Topic: {order}\n\nSources:\n{ctx}", 1000)
    return report + "\n\n## Fuentes\n" + "\n".join(f"- {s['url']}" for s in sources)

HANDLERS = {
    "prompt_engineering": svc_prompt_engineering,
    "code_audit": svc_code_audit,
    "data_research": svc_data_research,
}

# --- PRIVACIDAD Y PROCESAMIENTO ---
def extract_claim_code(text):
    """Busca el patrón [Claim: codigo] o [Code: codigo] en el texto del cliente."""
    match = re.search(r'\[(?:Claim|Code|Key):\s*([a-zA-Z0-9_-]{4,32})\]', text, re.IGNORECASE)
    if match:
        return match.group(1)
    return "default"

def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"resources": {}, "processed_tx": [], "earnings_usd": 0.0, "history": []}

def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2))

def process(agent, state):
    txs = agent.get_transactions(status="C", limit=50)
    resp = txs.get("response", txs) if isinstance(txs, dict) else txs
    tx_list = resp.get("transactions", []) if isinstance(resp, dict) else resp

    for tx in tx_list:
        tx_id = str(tx.get("id"))
        if tx_id in state["processed_tx"]: continue
        
        res_id = tx.get("res_id")
        service = next((k for k, v in state["resources"].items() if v["res_id"] == res_id), None)
        if not service: continue
        
        order = (tx.get("description") or "").strip()
        cf = tx.get("custom_fields", {})
        if isinstance(cf, dict):
            for v in cf.values():
                if isinstance(v, str) and len(v.strip()) > len(order):
                    order = v.strip()
        
        if not order:
            log(f"[{tx_id}] Pagado pero sin pedido.")
            continue

        log(f"[{tx_id}] Procesando '{service}'...")
        try:
            # Generar entregable
            output = HANDLERS[service](order)
            
            # SISTEMA DE PRIVACIDAD: Hash basado en tx_id + claim_code
            claim_code = extract_claim_code(order)
            secret_hash = hashlib.sha256(f"{tx_id}-{claim_code}".encode()).hexdigest()[:16]
            
            filepath = DELIVERIES / f"{secret_hash}.md"
            filepath.write_text(f"# {service}\n\n{output}\n\n---\n*Tu código de reclamo privado es: {claim_code}*")
            
            # Guardar transacción como procesada
            state["processed_tx"].append(tx_id)
            state["earnings_usd"] += float(tx.get("amount_fiat", 0))
            save_state(state)
            log(f"[{tx_id}] Entregado privadamente en deliveries/{secret_hash}.md")
        except Exception:
            log(traceback.format_exc())

if __name__ == "__main__":
    log("Iniciando ciclo del agente...")
    agent = AgentsUCash(api_key=API_KEY)
    state = load_state()
    process(agent, state)
    log("Ciclo finalizado.")
