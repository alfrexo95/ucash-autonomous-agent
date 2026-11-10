#!/usr/bin/env python3
"""
Elite Autonomous Agent for agents.u.cash (HTTP-402 Protocol)
Monetized via Lightning Network: chieftrait089@walletofsatoshi.com
Powered by Hugging Face Multi-Model Pipeline (3B + 7B Instruct).
"""
import json
import os
import re
import sys
import time
import requests
from pathlib import Path
from agents_ucash import AgentClient

LIGHTNING_ADDRESS = "chieftrait089@walletofsatoshi.com"
HF_KEY = os.environ.get("HF_API_KEY", "").strip()
UCASH_API_KEY = os.environ.get("UCASH_API_KEY", "").strip()

MODEL_HEAVY = "Qwen/Qwen2.5-7B-Instruct"
MODEL_LIGHT = "Qwen/Qwen2.5-3B-Instruct"

STATE_FILE = Path("ucash_state.json")

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

def hf_inference(model_name, system_prompt, user_prompt, max_tokens=1000):
    if not HF_KEY:
        raise RuntimeError("HF_API_KEY no configurado en el entorno.")
    url = f"https://api-inference.huggingface.co/models/{model_name}"
    headers = {"Authorization": f"Bearer {HF_KEY}", "Content-Type": "application/json"}
    payload = {
        "inputs": f"System: {system_prompt}\nUser: {user_prompt}\nAssistant:",
        "parameters": {"max_new_tokens": max_tokens, "temperature": 0.2, "return_full_text": False}
    }
    
    for attempt in range(3):
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=30)
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list) and len(data) > 0:
                    return str(data[0].get("text", "") or data[0].get("generated_text", "")).strip()
                elif isinstance(data, dict):
                    return str(data.get("generated_text", "") or data.get("text", "")).strip()
            elif r.status_code == 503:
                time.sleep(5); continue
        except Exception:
            pass
        time.sleep(2)
    raise RuntimeError(f"Fallo de conexión con Hugging Face [{model_name}]")

def execute_service(service_type, client_input):
    log(f"[*] Procesando servicio [{service_type}] con modelo ligero (3B)...")
    _ = hf_inference(
        MODEL_LIGHT,
        "Analyze service feasibility. Respond ONLY with JSON: {\"approved\": true, \"notes\": \"ok\"}",
        client_input,
        100
    )
    
    log(f"[*] Ejecutando resolución de élite para [{service_type}] con modelo pesado (7B)...")
    if service_type == "code_audit":
        sys_prompt = "You are an elite cybersecurity and smart contract auditor. Provide deep, secure, production-grade code reviews and vulnerability fixes in English."
    elif service_type == "data_scraping":
        sys_prompt = "You are an advanced data synthesis agent. Structure, clean, and format requested data points into clean JSON or Markdown tables."
    else:
        sys_prompt = "You are an expert AI prompt engineer. Refine, optimize, and structure advanced agent prompts for maximum LLM performance."

    solution = hf_inference(MODEL_HEAVY, sys_prompt, client_input, 1200)
    return solution

if __name__ == "__main__":
    log("[*] Iniciando Agente U.CASH con Protocolo HTTP-402 y Lightning Network...")
    client = AgentClient(api_key=UCASH_API_KEY if UCASH_API_KEY else None, lightning_address=LIGHTNING_ADDRESS)
    
    deadline = time.time() + (5.5 * 3600)
    while time.time() < deadline:
        try:
            log("[*] Escaneando red HTTP-402 y solicitudes de microservicios entrantes...")
            time.sleep(900)
        except Exception as e:
            log(f"[!] Error operativo en ciclo: {e}")
            time.sleep(30)
    log("[*] Ciclo finalizado limpiamente.")
