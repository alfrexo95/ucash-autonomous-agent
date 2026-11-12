#!/usr/bin/env python3
import os
import json
import getpass
import urllib.request
import urllib.error
from pathlib import Path

BASE = "https://agents.u.cash"
API = BASE + "/v1"
UA = "PredatorUCashAgent/1.0"

def request(path, method="GET", key=None, body=None):
    data = json.dumps(body).encode() if body is not None else None

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": UA,
    }

    if key:
        headers["X-Api-Key"] = key

    req = urllib.request.Request(
        API + path,
        data=data,
        method=method,
        headers=headers
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode())

    except urllib.error.HTTPError as e:
        print("HTTP ERROR:", e.code)
        print(e.read().decode()[:1000])
        raise

def unwrap(data):
    return data.get("response", data) if isinstance(data, dict) else data

def save_key(key):
    path = Path.home() / ".ucash_api_key"
    path.write_text(key + "\n")
    path.chmod(0o600)
    print("API KEY guardada:", path)

def main():
    key = os.getenv("UCASH_API_KEY", "").strip()

    if not key:
        print("=== REGISTRO U.CASH ===")
        email = input("Email: ").strip()
        password = getpass.getpass("Password: ")

        result = unwrap(request(
            "/signup",
            "POST",
            body={
                "email": email,
                "password": password,
                "agreed_to_terms": True
            }
        ))

        key = result.get("api_key")

        if not key:
            print("Respuesta:", json.dumps(result, indent=2))
            raise SystemExit("No se recibió API Key.")

        save_key(key)

    print("\n=== CUENTA ===")
    account = unwrap(request("/agent", key=key))
    print("Cuenta U.CASH consultada correctamente.")

    print("\n=== CONFIGURAR WALLETS BTC Y ETH ===")

    wallets = {
        "btc": os.getenv("BTC_ADDRESS", "").strip(),
        "eth": os.getenv("ETH_ADDRESS", "").strip(),
    }

    for asset, address in wallets.items():
        if not address:
            print(f"{asset.upper()}: dirección no configurada; omitida.")
            continue

        result = unwrap(request(
            "/wallets",
            "POST",
            key,
            {
                "asset": asset,
                "address": address
            }
        ))

        print(f"{asset.upper()}: wallet configurada correctamente.")

    print("\nConfiguración terminada.")

if __name__ == "__main__":
    main()
