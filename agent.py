#!/usr/bin/env python3
"""
U.CASH Agent v2 - vende servicios de IA y cobra de verdad via HTTP 402 (agents.u.cash / pay.u.cash).

Cambios clave respecto a la v1:
  * El ledger YA NO inventa ingresos: solo se acredita lo que U.CASH reporta como liquidado (status "C").
  * Cada pago se procesa una sola vez (dedupe por id de transaccion).
  * Cada recurso (res_id) vendible esta ligado a un servicio y un precio.
  * La entrega queda guardada en deliveries/<tx_id>.md.
  * Todas las credenciales vienen de variables de entorno (GitHub Secrets), nada hardcodeado.

Requisitos (pip): agents-u-cash ddgs transformers torch
Secrets / env:  UCASH_API_KEY (obligatorio), MODEL_NAME (opcional), RUN_HOURS (opcional)
"""
import json
import os
import time
import traceback
from pathlib import Path

from agents_u_cash import AgentsUCash
from core_logic import get_hash, get_cache, set_cache, validate_python

try:
    from ddgs import DDGS  # paquete actual
except ImportError:  # compatibilidad con el nombre viejo
    from duckduckgo_search import DDGS

from transformers import pipeline

# ------------------------------------------------------------------ CONFIG
API_KEY = os.environ.get("UCASH_API_KEY", "")
MODEL_NAME = os.environ.get("MODEL_NAME", "Qwen/Qwen2.5-1.5B-Instruct")
RUN_HOURS = float(os.environ.get("RUN_HOURS", "5.5"))
POLL_SECONDS = int(os.environ.get("POLL_SECONDS", "120"))

STATE_FILE = Path("ucash_state.json")
DELIVERIES = Path("deliveries")
INBOX = Path("inbox")  # el cliente deja aqui <tx_id>.txt o <res_id>.txt con su pedido
DELIVERIES.mkdir(exist_ok=True)
INBOX.mkdir(exist_ok=True)

# Catalogo: servicio -> precio en USD. Se crea un recurso 402 por cada uno.
CATALOG = {
    "prompt_engineering": {"price": 2.0, "title": "Prompt Engineering"},
    "code_audit": {"price": 5.0, "title": "Auditoria de codigo / smart contracts"},
    "data_research": {"price": 3.0, "title": "Investigacion web verificada"},
}


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ------------------------------------------------------------------ ESTADO / LEDGER
def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"resources": {}, "processed_tx": [], "earnings_usd": 0.0, "history": []}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2))


# ------------------------------------------------------------------ IA LOCAL
log(f"Cargando modelo {MODEL_NAME} ...")
generator = pipeline("text-generation", model=MODEL_NAME, device_map="cpu", dtype="auto")


import torch

def ask(system, user, max_tokens=900):
    torch.manual_seed(42)
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    out = generator(
        msgs,
        max_new_tokens=max_tokens,
        do_sample=False,
        repetition_penalty=1.1,
    )
    return out[0]["generated_text"][-1]["content"].strip()


# ------------------------------------------------------------------ SERVICIOS
def web_search(query, n=5):
    rows = []
    try:
        with DDGS() as d:
            for r in d.text(query, max_results=n):
                rows.append({"title": r.get("title"), "snippet": r.get("body"), "url": r.get("href")})
    except Exception as e:
        log(f"busqueda fallo: {e}")
    return rows


def svc_automation_builder(order):
    cache_key = get_hash(order)
    cached = get_cache(cache_key)
    if cached: return cached["md"]
    
    # Simulamos generación de código
    code = "def run():\n    print('hello')" # Aquí iría tu modelo
    is_valid, msg = validate_python(code)
    
    result = f"## Automation Builder\n\nValidation: {msg}\n\n```python\n{code}\n```"
    set_cache(cache_key, {"md": result})
    return result

def svc_prompt_engineering(order):
    return ask(
        "You are an expert prompt engineer. Produce a production-ready system prompt: role, "
        "constraints, steps, output format, and 2 examples. Match the language of the request.",
        order,
    )


def svc_code_audit(order):
    return ask(
        "You are a security auditor for Python/Solidity. List vulnerabilities by severity, explain "
        "each briefly, and give corrected code. Do not invent issues that are not in the code.",
        order,
        1200,
    )


def svc_data_research(order):
    sources = web_search(order)
    ctx = json.dumps(sources, ensure_ascii=False, indent=2)
    report = ask(
        "You write factual Markdown reports using ONLY the sources provided. Cite each claim with "
        "its URL. If sources are insufficient, say so.",
        f"Topic: {order}\n\nSources:\n{ctx}",
        1000,
    )
    return report + "\n\n## Fuentes\n" + "\n".join(f"- {s['url']}" for s in sources)


HANDLERS = {
    "prompt_engineering": svc_prompt_engineering,
    "code_audit": svc_code_audit,
    "data_research": svc_data_research,
}


# ------------------------------------------------------------------ U.CASH
def as_list(resp):
    """El SDK puede devolver lista o {'response': [...]}; normalizamos."""
    if isinstance(resp, dict):
        resp = resp.get("response", resp.get("transactions", []))
    return resp if isinstance(resp, list) else []




def fill_missing_checkout_urls(agent, state):
    """Rellena checkout_url vacias consultando get_resources() del SDK."""
    try:
        resp = agent.get_resources()
    except Exception as e:
        log(f"get_resources fallo: {e}")
        return
    items = resp.get("response", resp) if isinstance(resp, dict) else resp
    if not isinstance(items, list):
        return
    by_res = {r.get("res_id"): r.get("checkout_url", "") for r in items if isinstance(r, dict)}
    changed = False
    for name, cfg in state["resources"].items():
        if cfg.get("checkout_url"):
            continue
        url = by_res.get(cfg["res_id"], "")
        if url:
            cfg["checkout_url"] = url
            changed = True
            log(f"checkout_url rellenada para {name}")
    if changed:
        save_state(state)


def ensure_resources(agent, state):
    """Crea un recurso 402 por servicio (una sola vez) y guarda su checkout_url."""
    for name, cfg in CATALOG.items():
        if name in state["resources"]:
            continue
        try:
            res = agent.create_resource(amount=cfg["price"], title=cfg["title"])
        except TypeError:  # versiones del SDK sin title
            res = agent.create_resource(amount=cfg["price"])
        res = res.get("response", res) if isinstance(res, dict) else res
        state["resources"][name] = {"res_id": res["res_id"], "checkout_url": res["checkout_url"]}
        log(f"Recurso creado: {name} -> {res['checkout_url']}")
    save_state(state)


def service_for_res(state, res_id):
    for name, r in state["resources"].items():
        if r["res_id"] == res_id:
            return name
    return None


def read_order(tx):
    """Extrae el pedido de custom_fields, description o inbox (en ese orden)."""
    # 1. custom_fields: el campo que creamos en el checkout
    cf = tx.get("custom_fields", {})
    if isinstance(cf, dict):
        for k, v in cf.items():
            if isinstance(v, str) and len(v.strip()) > 5:
                return v.strip()
    # 2. description (fallback)
    desc = (tx.get("description") or "").strip()
    if desc:
        return desc
    # 3. inbox (fallback manual)
    for key in (str(tx.get("id")), str(tx.get("res_id"))):
        p = INBOX / f"{key}.txt"
        if p.exists():
            return p.read_text().strip()
    return ""


def process_settled(agent, state):
    txs = as_list(agent.get_transactions(status="C", limit=100))
    for tx in txs:
        tx_id = str(tx.get("id"))
        if tx_id in state["processed_tx"]:
            continue
        service = service_for_res(state, tx.get("res_id"))
        if not service:
            continue  # pago de otro recurso, no es de este bot
        order = read_order(tx)
        if not order:
            log(f"[tx {tx_id}] pagada pero sin pedido; queda pendiente de inbox/{tx_id}.txt")
            continue
        log(f"[tx {tx_id}] entregando '{service}' ...")
        try:
            output = HANDLERS[service](order)
        except Exception:
            log(traceback.format_exc())
            continue
        (DELIVERIES / f"{tx_id}.md").write_text(f"# {service}\n\nPedido:\n{order}\n\n---\n\n{output}\n")
        fiat = float(tx.get("amount_fiat") or 0)
        state["processed_tx"].append(tx_id)
        state["earnings_usd"] = round(state["earnings_usd"] + fiat, 2)
        state["history"].append({
            "tx": tx_id, "service": service, "usd": fiat,
            "asset": tx.get("asset"), "settled_at": tx.get("settled_at"),
        })
        save_state(state)
        log(f"[tx {tx_id}] entregado. Ingresos liquidados acumulados: ${state['earnings_usd']}")


# ------------------------------------------------------------------ MAIN
if __name__ == "__main__":
    if not API_KEY:
        raise SystemExit("Falta UCASH_API_KEY (agregalo en GitHub > Settings > Secrets).")
    agent = AgentsUCash(api_key=API_KEY)
    state = load_state()
    ensure_resources(agent, state)
    fill_missing_checkout_urls(agent, state)

    log("Catalogo activo (comparte estos enlaces para cobrar):")
    for name, r in state["resources"].items():
        log(f"  {name}: ${CATALOG[name]['price']} -> {r['checkout_url']}")

    deadline = time.time() + RUN_HOURS * 3600
    while time.time() < deadline:
        try:
            process_settled(agent, state)
        except Exception:
            log(traceback.format_exc())
        time.sleep(POLL_SECONDS)
    log("Ciclo finalizado.")
