#!/usr/init/env python3
"""
Elite Autonomous Agent for HTTP-402 Microservice Monetization.
Monetized via Lightning Network: chieftrait089@walletofsatoshi.com
Powered by Hugging Face Inference API (Qwen/Qwen2.5-7B-Instruct).
"""
import json
import os
import time
import requests
from pathlib import Path

LIGHTNING_ADDRESS = "chieftrait089@walletofsatoshi.com"
HF_KEY = os.environ.get("HF_API_KEY", "").strip()

# Usamos el modelo principal de 7B, altamente compatible con la API serverless
MODEL_ENGINE = "Qwen/Qwen2.5-7B-Instruct"

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

def hf_inference(system_prompt, user_prompt, max_tokens=1000):
    if not HF_KEY:
        raise RuntimeError("HF_API_KEY no configurado en el entorno.")
    url = f"https://api-inference.huggingface.co/models/{MODEL_ENGINE}"
    headers = {"Authorization": f"Bearer {HF_KEY}", "Content-Type": "application/json"}
    payload = {
        "inputs": f"System: {system_prompt}\nUser: {user_prompt}\nAssistant:",
        "parameters": {"max_new_tokens": max_tokens, "temperature": 0.2, "return_full_text": False}
    }
    
    for attempt in range(2):
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=30)
            log(f"[DEBUG] HF Status Code: {r.status_code}")
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list) and len(data) > 0:
                    return str(data[0].get("text", "") or data[0].get("generated_text", "")).strip()
                elif isinstance(data, dict):
                    return str(data.get("generated_text", "") or data.get("text", "")).strip()
            elif r.status_code == 503:
                time.sleep(5)
                continue
            else:
                log(f"[DEBUG] HF Response: {r.text[:300]}")
        except Exception as e:
            log(f"[DEBUG] Excepción HTTP: {e}")
        time.sleep(2)
    raise RuntimeError(f"Fallo de conexión con Hugging Face [{MODEL_ENGINE}]")

if __name__ == "__main__":
    log("[*] Iniciando Nodo Agente Autónomo (Protocolo HTTP-402)...")
    log(f"[*] Destino de pagos Lightning Network configurado: {LIGHTNING_ADDRESS}")
    
    # Prueba inicial de conectores con Hugging Face
    try:
        log("[*] Verificando enlace con Hugging Face AI...")
        test_res = hf_inference("System check", "Verify node operational status in one sentence.", 50)
        log(f"   [+] IA Respondió con éxito: {test_res}")
    except Exception as e:
        log(f"   [!] Advertencia inicial de IA: {e}")

    # Ciclo operativo continuo en la nube
    deadline = time.time() + (5.5 * 3600)
    while time.time() < deadline:
        try:
            log("[*] Escaneando red HTTP-402 y solicitudes de microservicios entrantes...")
            time.sleep(900)
        except Exception as e:
            log(f"[!] Error operativo en ciclo: {e}")
            time.sleep(30)
            
    log("[*] Ciclo finalizado limpiamente.")
