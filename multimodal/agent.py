# -*- coding: utf-8 -*-
"""Predator Multimodal — OCR, vision, audio y contratos (Qwen lazy para texto)."""
import json, os, re, sys, time, traceback
from pathlib import Path
from agents_u_cash import AgentsUCash
sys.path.append('..')
from core_logic import (analyze_solidity, delivery_name, derive_key, encrypt_bytes,
                        robust_download, load_state, save_state)

API_KEY = os.environ.get("UCASH_API_KEY", "")
TEXT_MODEL_NAME = os.environ.get("MODEL_NAME", "Qwen/Qwen2.5-Coder-3B-Instruct")
STATE_FILE = Path("ucash_state.json"); DELIVERIES = Path("deliveries"); INBOX = Path("inbox")
DELIVERIES.mkdir(exist_ok=True); INBOX.mkdir(exist_ok=True)
_text_generator = None

def _ask_text(system, user, max_tokens=1000):
    global _text_generator
    if _text_generator is None:
        print(f"[{time.strftime('%H:%M:%S')}] Cargando modelo {TEXT_MODEL_NAME}...", flush=True)
        import torch
        from transformers import pipeline
        _text_generator = pipeline("text-generation", model=TEXT_MODEL_NAME, device="cpu",
                                   torch_dtype=torch.float32, trust_remote_code=True)
    torch.manual_seed(42)
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    out = _text_generator(msgs, max_new_tokens=max_tokens, do_sample=False, repetition_penalty=1.1)
    return out[0]["generated_text"][-1]["content"].strip()

def _strip_claim(text):
    return re.sub(r'\[(?:Claim|Code|Key):\s*[a-zA-Z0-9_-]+\]', '', text).strip()

def extract_claim_code(text):
    match = re.search(r'\[(?:Claim|Code|Key):\s*([a-zA-Z0-9_-]{4,32})\]', text, re.IGNORECASE)
    return match.group(1) if match else None

def deliver_encrypted(tx_id, service, output, claim_code):
    content = f"# {service}\n\n{output}\n".encode("utf-8")
    key = derive_key(tx_id, claim_code)
    path = DELIVERIES / delivery_name(tx_id, claim_code)
    path.write_bytes(encrypt_bytes(content, key))
    return path

def handle_ocr(order):
    try:
        import pytesseract; from PIL import Image
        url = _strip_claim(order); path = robust_download(url)
        return f"## OCR Result\n\n```text\n{pytesseract.image_to_string(Image.open(path))}\n```"
    except Exception as e: return f"Error OCR: {e}"

def handle_sentiment(order):
    try:
        from transformers import pipeline
        classifier = pipeline("sentiment-analysis", model="distilbert-base-uncased-finetuned-sst-2-english")
        result = classifier(_strip_claim(order)[:512])
        return f"## Sentiment\n\n- **Label**: {result[0]['label']}\n- **Confidence**: {result[0]['score']:.2%}"
    except Exception as e: return f"Error: {e}"

def handle_image_classifier(order):
    try:
        from transformers import pipeline
        classifier = pipeline("image-classification", model="google/vit-base-patch16-224")
        result = classifier(robust_download(_strip_claim(order)))
        return "## Classification\n\n" + "\n".join([f"- {r['label']}: {r['score']:.2%}" for r in result[:5]])
    except Exception as e: return f"Error: {e}"

def handle_transcriber(order):
    try:
        from transformers import pipeline
        transcriber = pipeline("automatic-speech-recognition", model="openai/whisper-tiny")
        return f"## Transcription\n\n{transcriber(robust_download(_strip_claim(order), 'audio'))['text']}"
    except Exception as e: return f"Error: {e}"

def handle_object_detector(order):
    try:
        from transformers import pipeline
        detector = pipeline("object-detection", model="facebook/detr-resnet-50")
        result = detector(robust_download(_strip_claim(order)))
        return "## Objects\n\n" + "\n".join([f"- {r['label']} ({r['score']:.2f})" for r in result])
    except Exception as e: return f"Error: {e}"

def handle_smart_contract(order):
    try:
        code = _strip_claim(order)
        if code.startswith("https://"):
            path = robust_download(code, "text")
            code = Path(path).read_text(errors="replace")[:200000]
        valid, report = analyze_solidity(code)
        return report + "\n\n### Veredicto\n" + ("APROBADO: sin hallazgos HIGH." if valid else "RECHAZADO: revisar hallazgos HIGH antes de desplegar.")
    except Exception as e: return f"Error en auditoria: {e}"

def handle_translator(order):
    try:
        text = _strip_claim(order)
        m = re.match(r"^([a-z]{2,3})\s*>\s*([a-z]{2,3})\s*:\s*", text)
        if m: src, tgt, text = m.group(1), m.group(2), text[m.end():]
        else: src, tgt = "es", "en"
        if not text: return "Error: texto vacio."
        translation = _ask_text(f"You are a professional translator from {src} to {tgt}. Output ONLY the translation.", text[:4000], 1200)
        return f"## Traduccion ({src} > {tgt})\n\n{translation}"
    except Exception as e: return f"Error traduccion: {e}"

def handle_summarizer(order):
    try:
        text = _strip_claim(order)
        if not text: return "Error: texto vacio."
        summary = _ask_text("You are an executive summary expert. Summarize in markdown: one-line thesis, 3-5 key bullets, action items. Output ONLY the summary.", text[:8000], 800)
        return f"## Resumen\n\n{summary}"
    except Exception as e: return f"Error resumen: {e}"

HANDLERS = {
    "ocr_extractor": handle_ocr, "sentiment_analyzer": handle_sentiment,
    "image_classifier": handle_image_classifier, "audio_transcriber": handle_transcriber,
    "object_detector": handle_object_detector, "smart_contract_auditor": handle_smart_contract,
    "text_translator": handle_translator, "document_summarizer": handle_summarizer,
}

def _to_float(v, default=0.0):
    try: return float(v)
    except (TypeError, ValueError): return default

def record_processed(state, tx_id, service, amount):
    state["processed_tx"].append(str(tx_id))
    state["needs_claim"].pop(str(tx_id), None)
    state["history"].append({"tx_id": str(tx_id), "service": service,
                             "amount": round(_to_float(amount), 6),
                             "ts": time.strftime("%Y-%m-%dT%H:%M:%S")})
    state["earnings_usd"] = round(sum(_to_float(h.get("amount")) for h in state["history"]), 6)

def process(agent, state):
    txs = agent.get_transactions(status="C", limit=50)
    resp = txs.get("response", txs) if isinstance(txs, dict) else txs
    tx_list = resp.get("transactions", []) if isinstance(resp, dict) else resp
    for tx in tx_list:
        tx_id = str(tx.get("id"))
        if tx_id in state["processed_tx"]: continue
        res_id = tx.get("res_id")
        service = next((k for k, v in state["resources"].items() if v["res_id"] == res_id), None)
        if not service or service not in HANDLERS: continue
        order = (tx.get("description") or "").strip()
        cf = tx.get("custom_fields", {})
        if isinstance(cf, dict):
            for v in cf.values():
                if isinstance(v, str) and len(v.strip()) > len(order): order = v.strip()
        if not order: continue
        claim_code = extract_claim_code(order)
        if not claim_code:
            state.setdefault("needs_claim", {})[tx_id] = service
            save_state(STATE_FILE, state)
            print(f"[{tx_id}] Sin [Claim: ...]: pendiente.", flush=True)
            continue
        try:
            output = HANDLERS[service](order)
            path = deliver_encrypted(tx_id, service, output, claim_code)
            record_processed(state, tx_id, service, tx.get("amount_fiat", 0))
            save_state(STATE_FILE, state)
            print(f"[{tx_id}] Entregado y CIFRADO en {path}", flush=True)
        except Exception: print(traceback.format_exc())

if __name__ == "__main__":
    print("Iniciando Multimodal Agent...")
    agent = AgentsUCash(api_key=API_KEY); state = load_state(STATE_FILE)
    process(agent, state); save_state(STATE_FILE, state)
    print("Ciclo finalizado.")
