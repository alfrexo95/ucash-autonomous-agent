#!/usr/bin/env python3
"""Descifra una entrega privada: python3 decrypt_delivery.py <tx_id> <claim_code> [carpeta]"""
import sys
from pathlib import Path
from core_logic import decrypt_bytes, delivery_name, derive_key

def find_delivery(tx_id, claim_code, folder_arg=None):
    if folder_arg:
        candidates = [Path(folder_arg)]
    else:
        here = Path(__file__).parent
        candidates = [here / "deliveries", here / "multimodal" / "deliveries",
                      Path("deliveries"), Path("multimodal") / "deliveries"]
    name = delivery_name(tx_id, claim_code); seen = set()
    for folder in candidates:
        folder = folder.resolve()
        if folder in seen: continue
        seen.add(folder)
        path = folder / name
        if path.exists(): return path
    return None

def main():
    if len(sys.argv) < 3: print(__doc__); sys.exit(1)
    tx_id, claim_code = sys.argv[1].strip(), sys.argv[2].strip()
    folder = sys.argv[3] if len(sys.argv) > 3 else None
    path = find_delivery(tx_id, claim_code, folder)
    if path is None:
        print(f"No se encontro {delivery_name(tx_id, claim_code)}. Verifica tx_id y claim_code.")
        sys.exit(1)
    content = decrypt_bytes(path.read_bytes(), derive_key(tx_id, claim_code))
    text = content.decode("utf-8", errors="replace")
    out_md = path.with_suffix(".decrypted.md"); out_md.write_text(text)
    print(text); print(f"\n---\n[Guardado tambien en: {out_md}]")

if __name__ == "__main__": main()
