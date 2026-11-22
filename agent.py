# -*- coding: utf-8 -*-
"""Predator U.CASH Agent — servicios de texto (Qwen2.5-Coder-3B, entregas cifradas)."""
import json, os, re, time, traceback
from pathlib import Path
from agents_u_cash import AgentsUCash
from core_logic import (analyze_solidity, delivery_name, derive_key, encrypt_bytes,
                        get_cache, get_hash, load_state, save_state, set_cache, validate_python, decrypt_bytes, record_processed_state, strip_claim_code, validate_delivery_output)
try:
    from ddgs import DDGS
except ImportError:
    from duckduckgo_search import DDGS
from transformers import pipeline
import torch

API_KEY = os.environ.get("UCASH_API_KEY", "")
MODEL_NAME = os.environ.get("MODEL_NAME", "Qwen/Qwen2.5-Coder-3B-Instruct")
RUN_HOURS = float(os.environ.get("RUN_HOURS", "0.25"))
POLL_SECONDS = int(os.environ.get("POLL_SECONDS", "60"))
STATE_FILE = Path("ucash_state.json"); DELIVERIES = Path("deliveries"); INBOX = Path("inbox")
DELIVERIES.mkdir(exist_ok=True); INBOX.mkdir(exist_ok=True)

def log(msg): print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

log(f"Cargando modelo {MODEL_NAME}...")
generator = pipeline("text-generation", model=MODEL_NAME, device="cpu",
                     torch_dtype=torch.float32, trust_remote_code=True)

def ask(system, user, max_tokens=1200):
    torch.manual_seed(42)
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    out = generator(msgs, max_new_tokens=max_tokens, do_sample=False, repetition_penalty=1.1)
    return out[0]["generated_text"][-1]["content"].strip()

def web_search(query, n=5):
    key = "ws_" + get_hash(query); cached = get_cache(key)
    if cached is not None: return cached
    rows = []
    try:
        with DDGS() as d:
            for r in d.text(query, max_results=n):
                rows.append({"title": r.get("title"), "snippet": r.get("body"), "url": r.get("href")})
    except Exception as e: log(f"busqueda fallo: {e}")
    if rows: set_cache(key, rows)
    return rows

def svc_prompt_engineering(order):
    return ask("You are an expert prompt engineer. Produce a production-ready system prompt.", order)

def svc_code_audit(order):
    if "pragma solidity" in order: is_valid, msg = analyze_solidity(order)
    else: is_valid, msg = validate_python(order)
    ai_explanation = ask("You are a senior security auditor. Briefly explain the security implications of the following code. Do not invent issues.", order, 800)
    return f"## Auditoria de Seguridad\n\n**Analisis Estatico:**\n\n{msg}\n\n### Analisis de IA:\n{ai_explanation}"

def svc_data_research(order):
    sources = web_search(order)
    ctx = json.dumps(sources, ensure_ascii=False, indent=2)
    report = ask("You write factual reports using ONLY the sources provided.", f"Topic: {order}\n\nSources:\n{ctx}", 1000)
    return report + "\n\n## Fuentes\n" + "\n".join(f"- {s['url']}" for s in sources)

HANDLERS = {"prompt_engineering": svc_prompt_engineering,
            "code_audit": svc_code_audit, "data_research": svc_data_research}

def extract_claim_code(text):
    match = re.search(r'\[(?:Claim|Code|Key):\s*([a-zA-Z0-9_-]{4,32})\]', text, re.IGNORECASE)
    return match.group(1) if match else None

def deliver_encrypted(tx_id, service, output, claim_code):
    content = f"# {service}\n\n{output}\n".encode("utf-8")
    key = derive_key(tx_id, claim_code)
    path = DELIVERIES / delivery_name(tx_id, claim_code)
    path.write_bytes(encrypt_bytes(content, key))
    return path

def _to_float(v, default=0.0):
    try: return float(v)
    except (TypeError, ValueError): return default

def record_processed(state, tx_id, service, amount):
    return record_processed_state(state, tx_id, service, amount)


def _recover_existing_delivery(tx_id, claim_code):
    path = DELIVERIES / delivery_name(tx_id, claim_code)
    if not path.exists():
        return False
    try:
        content = decrypt_bytes(path.read_bytes(), derive_key(tx_id, claim_code)).decode("utf-8", errors="replace")
        report = content.split("\n\n", 1)[-1]
        return validate_delivery_output(report)
    except Exception:
        return False


def process(agent, state):
    txs = agent.get_transactions(status="C", limit=50)
    resp = txs.get("response", txs) if isinstance(txs, dict) else txs
    tx_list = resp.get("transactions", []) if isinstance(resp, dict) else resp
    if not isinstance(tx_list, list):
        log("Respuesta de U.CASH no contiene lista de transacciones; ciclo omitido.")
        return
    for tx in tx_list:
        if not isinstance(tx, dict) or tx.get("id") is None:
            continue
        tx_id = str(tx["id"])
        if tx_id in set(map(str, state.get("processed_tx", []))):
            continue
        res_id = tx.get("res_id")
        resources = state.get("resources") or {}
        service = next((k for k, v in resources.items()
                       if isinstance(v, dict) and str(v.get("res_id")) == str(res_id)), None)
        if not service:
            continue
        order = (tx.get("description") or "").strip()
        cf = tx.get("custom_fields", {})
        if isinstance(cf, dict):
            for value in cf.values():
                if isinstance(value, str) and len(value.strip()) > len(order):
                    order = value.strip()
        claim_code = extract_claim_code(order)
        if not claim_code:
            state.setdefault("needs_claim", {})[tx_id] = service
            save_state(STATE_FILE, state)
            log(f"[{tx_id}] Sin [Claim: ...], guardado en needs_claim.")
            continue
        clean_order = strip_claim_code(order)
        if not clean_order:
            log(f"[{tx_id}] Pago confirmado pero pedido vacío; pendiente de revisión.")
            continue
        if service not in HANDLERS:
            log(f"[{tx_id}] Servicio desconocido o no registrado: {service}")
            continue
        if _recover_existing_delivery(tx_id, claim_code):
            record_processed(state, tx_id, service, tx.get("amount_fiat", 0))
            save_state(STATE_FILE, state)
            log(f"[{tx_id}] Entrega anterior validada; estado recuperado sin repetir inferencia.")
            continue
        log(f"[{tx_id}] Procesando '{service}'...")
        state.setdefault("in_progress", {})[tx_id] = service
        save_state(STATE_FILE, state)
        try:
            output = HANDLERS[service](clean_order)
            if not validate_delivery_output(output):
                raise RuntimeError("El handler devolvió un resultado vacío o un mensaje de error.")
            path = deliver_encrypted(tx_id, service, output, claim_code)
            record_processed(state, tx_id, service, tx.get("amount_fiat", 0))
            save_state(STATE_FILE, state)
            log(f"[{tx_id}] Entrega cifrada y validada en {path}")
        except Exception:
            state.get("in_progress", {}).pop(tx_id, None)
            save_state(STATE_FILE, state)
            err = traceback.format_exc()
            log(err)
            try:
                from self_repair import record_failure
                record_failure("agent.py", service, err)
            except Exception:
                pass

if __name__ == "__main__":
    log("Iniciando ciclo del agente...")
    agent = AgentsUCash(api_key=API_KEY)
    state = load_state(STATE_FILE)
    if state.get("in_progress"):
        log(f"Recuperando {len(state['in_progress'])} transaccion(es) marcadas en proceso.")
        state["in_progress"] = {}
        save_state(STATE_FILE, state)
    deadline = time.time() + RUN_HOURS * 3600.0
    log(f"Ventana activa: {RUN_HOURS}h (poll cada {POLL_SECONDS}s)")
    try:
        while True:
            process(agent, state)
            if time.time() >= deadline: break
            time.sleep(POLL_SECONDS)
    except KeyboardInterrupt: log("Interrumpido por el usuario.")
    save_state(STATE_FILE, state)
    log("Ciclo finalizado.")
