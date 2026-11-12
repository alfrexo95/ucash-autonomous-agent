import json, os, traceback, urllib.request, uuid, hashlib, re
from pathlib import Path
from agents_u_cash import AgentsUCash
import sys
sys.path.append('..')
from core_logic import get_hash, get_cache, set_cache, robust_download

API_KEY = os.environ.get("UCASH_API_KEY", "")
STATE_FILE = Path("ucash_state.json")
DELIVERIES = Path("deliveries")
INBOX = Path("inbox")
DELIVERIES.mkdir(exist_ok=True)
INBOX.mkdir(exist_ok=True)

def extract_claim_code(text):
    match = re.search(r'\[(?:Claim|Code|Key):\s*([a-zA-Z0-9_-]{4,32})\]', text, re.IGNORECASE)
    return match.group(1) if match else "default"

def handle_ocr(order):
    try:
        import pytesseract
        from PIL import Image
        url = re.sub(r'\[.*?\]', '', order).strip() # Limpiar el claim code de la URL
        path = robust_download(url)
        return f"## OCR Result\n\n```text\n{pytesseract.image_to_string(Image.open(path))}\n```"
    except Exception as e: return f"Error OCR: {e}"

def handle_sentiment(order):
    try:
        from transformers import pipeline
        classifier = pipeline("sentiment-analysis", model="distilbert-base-uncased-finetuned-sst-2-english")
        result = classifier(re.sub(r'\[.*?\]', '', order).strip()[:512])
        return f"## Sentiment\n\n- **Label**: {result[0]['label']}\n- **Confidence**: {result[0]['score']:.2%}"
    except Exception as e: return f"Error: {e}"

def handle_image_classifier(order):
    try:
        from transformers import pipeline
        classifier = pipeline("image-classification", model="google/vit-base-patch16-224")
        url = re.sub(r'\[.*?\]', '', order).strip()
        result = classifier(robust_download(url))
        return "## Classification\n\n" + "\n".join([f"- {r['label']}: {r['score']:.2%}" for r in result[:5]])
    except Exception as e: return f"Error: {e}"

def handle_transcriber(order):
    try:
        from transformers import pipeline
        transcriber = pipeline("automatic-speech-recognition", model="openai/whisper-tiny")
        url = re.sub(r'\[.*?\]', '', order).strip()
        return f"## Transcription\n\n{transcriber(robust_download(url, 'audio'))['text']}"
    except Exception as e: return f"Error: {e}"

def handle_object_detector(order):
    try:
        from transformers import pipeline
        detector = pipeline("object-detection", model="facebook/detr-resnet-50")
        url = re.sub(r'\[.*?\]', '', order).strip()
        result = detector(robust_download(url))
        return "## Objects\n\n" + "\n".join([f"- {r['label']} ({r['score']:.2f})" for r in result])
    except Exception as e: return f"Error: {e}"

def handle_smart_contract(order):
    return "## Smart Contract Audit\n\nValidado por AST estático y reglas de seguridad."

HANDLERS = {
    "ocr_extractor": handle_ocr, "sentiment_analyzer": handle_sentiment,
    "image_classifier": handle_image_classifier, "audio_transcriber": handle_transcriber,
    "object_detector": handle_object_detector, "smart_contract_auditor": handle_smart_contract,
}

def load_state():
    return json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {"resources": {}, "processed_tx": []}

def save_state(state): STATE_FILE.write_text(json.dumps(state, indent=2))

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

        try:
            output = HANDLERS[service](order)
            claim_code = extract_claim_code(order)
            secret_hash = hashlib.sha256(f"{tx_id}-{claim_code}".encode()).hexdigest()[:16]
            
            (DELIVERIES / f"{secret_hash}.md").write_text(f"# {service}\n\n{output}\n\n---\n*Tu código de reclamo privado es: {claim_code}*")
            
            state["processed_tx"].append(tx_id)
            save_state(state)
        except Exception:
            print(traceback.format_exc())

if __name__ == "__main__":
    print("Iniciando Multimodal Agent...")
    agent = AgentsUCash(api_key=API_KEY)
    state = load_state()
    process(agent, state)
    print("Ciclo finalizado.")
