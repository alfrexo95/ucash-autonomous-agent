# -*- coding: utf-8 -*-
"""Nucleo compartido del Predator Agent (solo stdlib)."""
import hashlib, hmac, ipaddress, json, os, re, socket, time
from pathlib import Path
from urllib.parse import urlparse

CACHE_DIR = Path("cache"); CACHE_DIR.mkdir(exist_ok=True)

def get_hash(text): return hashlib.sha256(str(text).encode()).hexdigest()[:16]

def get_cache(key):
    p = CACHE_DIR / f"{key}.json"
    if p.exists():
        try: return json.loads(p.read_text())
        except ValueError: return None
    return None

def set_cache(key, data):
    (CACHE_DIR / f"{key}.json").write_text(json.dumps(data, indent=2, ensure_ascii=False))

# ---- Cifrado de entregas autenticado (stdlib puro) ----
_CIPHER_MAGIC = b"UCASH1"  # legacy format; retained for backward-compatible decrypt
_CIPHER_MAGIC_V2 = b"UCASH2"
_CIPHER_TAG_LEN = 32


def _keystream(key, nonce, length):
    """Legacy UCASH1 stream generator; used only to decrypt old files."""
    out = bytearray(); counter = 0
    while len(out) < length:
        out.extend(hashlib.sha256(key + nonce + counter.to_bytes(8, "big")).digest()); counter += 1
    return bytes(out[:length])


def _keystream_v2(key, nonce, length):
    out = bytearray(); counter = 0
    while len(out) < length:
        out.extend(hmac.new(key, nonce + counter.to_bytes(8, "big"), hashlib.sha256).digest())
        counter += 1
    return bytes(out[:length])


def encrypt_bytes(data, key):
    nonce = os.urandom(16)
    enc_key = hmac.new(key, b"UCASH2|enc", hashlib.sha256).digest()
    mac_key = hmac.new(key, b"UCASH2|mac", hashlib.sha256).digest()
    ks = _keystream_v2(enc_key, nonce, len(data))
    ciphertext = bytes(a ^ b for a, b in zip(data, ks))
    header = _CIPHER_MAGIC_V2 + nonce
    tag = hmac.new(mac_key, header + ciphertext, hashlib.sha256).digest()
    return header + ciphertext + tag


def decrypt_bytes(blob, key):
    if blob.startswith(_CIPHER_MAGIC_V2):
        header_len = len(_CIPHER_MAGIC_V2) + 16
        if len(blob) < header_len + _CIPHER_TAG_LEN:
            raise ValueError("Entrega UCASH2 truncada.")
        nonce = blob[len(_CIPHER_MAGIC_V2):header_len]
        ciphertext = blob[header_len:-_CIPHER_TAG_LEN]
        tag = blob[-_CIPHER_TAG_LEN:]
        enc_key = hmac.new(key, b"UCASH2|enc", hashlib.sha256).digest()
        mac_key = hmac.new(key, b"UCASH2|mac", hashlib.sha256).digest()
        expected = hmac.new(mac_key, blob[:header_len] + ciphertext, hashlib.sha256).digest()
        if not hmac.compare_digest(tag, expected):
            raise ValueError("Entrega alterada o clave de Claim incorrecta.")
        ks = _keystream_v2(enc_key, nonce, len(ciphertext))
        return bytes(a ^ b for a, b in zip(ciphertext, ks))
    if blob.startswith(_CIPHER_MAGIC):
        nonce = blob[len(_CIPHER_MAGIC):len(_CIPHER_MAGIC) + 16]
        body = blob[len(_CIPHER_MAGIC) + 16:]
        ks = _keystream(key, nonce, len(body))
        return bytes(a ^ b for a, b in zip(body, ks))
    raise ValueError("Archivo de entrega invalido o ya descifrado.")


def strip_claim_code(text):
    return re.sub(r"\\[(?:Claim|Code|Key):\\s*[a-zA-Z0-9_-]{4,32}\\]", "", str(text), flags=re.I).strip()


def validate_delivery_output(output):
    if not isinstance(output, str) or not output.strip():
        return False
    text = output.strip()
    return not re.match(r"^(?:error|exception|failed|http error)\\s*[:\\-]", text, re.I)
# ---- Estado con fusion atomica ----
def default_state():
    return {"resources": {}, "processed_tx": [], "needs_claim": {}, "in_progress": {}, "earnings_usd": 0.0, "history": []}

def load_state(path):
    p = Path(path); state = {}
    if p.exists():
        try: state = json.loads(p.read_text())
        except ValueError: state = {}
    base = default_state()
    if isinstance(state, dict): base.update(state)
    if isinstance(base.get("processed_tx"), list):
        base["processed_tx"] = [str(x) for x in base["processed_tx"]]
    if not isinstance(base.get("in_progress"), dict):
        base["in_progress"] = {}
    return base

def _dedupe_history(entries):
    seen = {}
    for e in entries or []:
        if isinstance(e, dict) and e.get("tx_id"): seen[str(e["tx_id"])] = e
    return list(seen.values())

def merge_states(base, other):
    base = base if isinstance(base, dict) else default_state()
    other = other if isinstance(other, dict) else default_state()
    merged = default_state()
    merged["resources"] = {**base.get("resources", {}), **other.get("resources", {})}
    merged["processed_tx"] = list(set(map(str, base.get("processed_tx", []))) | set(map(str, other.get("processed_tx", []))))
    # needs_claim: las eliminaciones en `other` tienen prioridad para evitar reprocesos.
    kept = {k: v for k, v in base.get("needs_claim", {}).items() if k in other.get("needs_claim", {})}
    merged["needs_claim"] = {**kept, **other.get("needs_claim", {})}
    merged["in_progress"] = {**base.get("in_progress", {}), **other.get("in_progress", {})}
    merged["history"] = _dedupe_history((base.get("history") or []) + (other.get("history") or []))
    merged["earnings_usd"] = max(float(base.get("earnings_usd", 0) or 0),
                                 float(other.get("earnings_usd", 0) or 0),
                                 sum(float(h.get("amount", 0) or 0) for h in merged["history"] if isinstance(h, dict)))
    for src in (base, other):
        for k, v in src.items():
            if k not in merged: merged[k] = v
    return merged

def save_state(path, state):
    p = Path(path)
    on_disk = load_state(p) if p.exists() else default_state()
    merged = merge_states(on_disk, state)
    tmp = p.with_suffix(".tmp"); tmp.write_text(json.dumps(merged, indent=2, ensure_ascii=False)); os.replace(tmp, p)
    return merged

# ---- Descarga segura (anti-SSRF) ----
_MAX_DOWNLOAD = 10 * 1024 * 1024

def _ip_is_blocked(ip):
    return (ip.is_private or ip.is_loopback or ip.is_reserved or
            ip.is_link_local or ip.is_multicast or ip.is_unspecified)

def _assert_public_host(hostname):
    if not hostname: raise ValueError("URL invalida.")
    try: ip = ipaddress.ip_address(hostname)
    except ValueError: ip = None
    if ip is not None:
        if _ip_is_blocked(ip): raise ValueError("IP privada o no enrutable bloqueada (SSRF).")
        return
    try: infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as e: raise ValueError(f"No se pudo resolver el host: {e}")
    for info in infos or []:
        try: addr = str(info[4][0]).split("%")[0]
        except (IndexError, TypeError): continue
        try: a = ipaddress.ip_address(addr)
        except ValueError: continue
        if _ip_is_blocked(a): raise ValueError("El host resuelve a una IP privada (SSRF bloqueado).")

def robust_download(url, expected_type="image"):
    url = str(url).strip()
    if not url.startswith("https://"): raise ValueError("Solo se permiten URLs HTTPS por seguridad.")
    parsed = urlparse(url); _assert_public_host(parsed.hostname or "")
    ext = ".png" if expected_type == "image" else (".mp3" if expected_type == "audio" else ".bin")
    Path("inbox").mkdir(exist_ok=True)
    filename = f"inbox/{get_hash(url)}{ext}"
    if os.path.exists(filename): return filename
    import urllib.request
    last_err = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; PredatorAgent/2.0)"})
            with urllib.request.urlopen(req, timeout=20) as r:
                content_type = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
                if content_type.startswith("text/html"):
                    raise ValueError("La URL no devuelve un archivo descargable valido.")
                content = r.read(_MAX_DOWNLOAD + 1)
                if len(content) > _MAX_DOWNLOAD: raise ValueError("Archivo mayor a 10MB, rechazado.")
                with open(filename, "wb") as f: f.write(content)
                return filename
        except Exception as e:
            last_err = e
            if attempt == 2: raise
            time.sleep(2 ** attempt)
    raise last_err or RuntimeError("Descarga fallida.")

# ---- Validacion de codigo ----
def validate_python(code):
    import ast
    try: ast.parse(code); return True, "Sintaxis valida"
    except SyntaxError as e: return False, f"Error de sintaxis: {e}"

# ---- Analizador estatico de Solidity (ChainGuard) ----
_SOLIDITY_RULES = [
    (r"\btx\.origin\b", "HIGH", "Uso de `tx.origin` para autenticacion: vulnerable a phishing."),
    (r"\bdelegatecall\b", "HIGH", "Uso de `delegatecall`: ejecuta codigo externo con permisos del contrato."),
    (r"\bselfdestruct\b", "MED", "Uso de `selfdestruct`: destruccion irreversible del contrato."),
    (r"\.call\s*\{", "MED", "Llamada externa de bajo nivel (`.call{}`): verifica valor de retorno y reentrancia."),
    (r"\bassembly\b", "MED", "Bloque `assembly`: evita las protecciones del compilador."),
    (r"\bextcodesize\b", "MED", "Uso de `extcodesize` para detectar contratos: evitable con EOA."),
    (r"\.send\s*\(", "MED", "Uso de `.send()`: devuelve false silencioso, prefiere `call` con chequeo."),
    (r"\bblock\.timestamp\b", "LOW", "Dependencia de `block.timestamp`: manipulable por validadores."),
    (r"\bblock\.number\b", "LOW", "Dependencia de `block.number` como fuente de aleatoriedad/mercado."),
]

def _solidity_strip(code):
    code = re.sub(r"/\*.*?\*/", "", code, flags=re.S)
    code = re.sub(r"//[^\n]*", "", code)
    code = re.sub(r'"(?:[^"\\]|\\.)*"', '""', code)
    code = re.sub(r"'(?:[^'\\]|\\.)*'", "''", code)
    return code

def _extract_functions(cleaned):
    funcs = []
    for m in re.finditer(r"\bfunction\s+(\w+)\s*\(", cleaned):
        name = m.group(1); start = cleaned.find("{", m.end())
        if start == -1: continue
        depth, end = 0, None
        for j in range(start, len(cleaned)):
            if cleaned[j] == "{": depth += 1
            elif cleaned[j] == "}":
                depth -= 1
                if depth == 0: end = j; break
        if end is not None: funcs.append((name, cleaned[m.start():start], cleaned[start + 1:end]))
    return funcs

def analyze_solidity(code):
    cleaned = _solidity_strip(str(code))
    if not cleaned.strip(): return False, "Contrato vacio o ilegible."
    issues = []
    if cleaned.count("{") != cleaned.count("}"):
        issues.append(("HIGH", f"Llaves desbalanceadas ({cleaned.count('{')}/{cleaned.count('}')})."))
    if cleaned.count("(") != cleaned.count(")"):
        issues.append(("MED", "Parentesis desbalanceados."))
    if "pragma solidity" not in cleaned:
        issues.append(("MED", "Falta la directiva `pragma solidity`."))
    mver = re.search(r"pragma\s+solidity\s+\^?(\d+)\.(\d+)", cleaned)
    if mver:
        version = (int(mver.group(1)), int(mver.group(2)))
        if version < (0, 8) and not re.search(r"\bSafeMath\b", cleaned):
            issues.append(("MED", f"Solidity {version[0]}.{version[1]} sin SafeMath: posible overflow aritmetico."))
    elif not re.search(r"\bSafeMath\b", cleaned):
        issues.append(("LOW", "Version no detectada: verifica overflow aritmetico si usas Solidity <0.8."))
    for pattern, sev, msg in _SOLIDITY_RULES:
        if re.search(pattern, cleaned): issues.append((sev, msg))
    for name, header, body in _extract_functions(cleaned):
        if not re.search(r"\b(public|private|internal|external)\b", header):
            issues.append(("MED", f"Funcion `{name}` sin visibilidad explicita."))
        if re.search(r"\bpayable\b", header) and not re.search(r"nonReentrant|onlyOwner|require\s*\(", body):
            issues.append(("LOW", f"Funcion payable `{name}` sin control de acceso/reentrancia visible."))
    ext_call = re.compile(r"\.(call|transfer|send)\s*[\({]")
    state_write = re.compile(r"(?<![.a-zA-Z0-9_])(?:\w+\s*\[[^\]]*\]|\w+)\s*(?:[-+*/%]?)=(?!=)")
    for name, header, body in _extract_functions(cleaned):
        m1 = ext_call.search(body)
        if m1 and state_write.search(body[m1.end():]):
            issues.append(("HIGH", f"Posible reentrancia en `{name}`: escritura de estado DESPUES de una llamada externa (viola checks-effects-interactions)."))
    if re.search(r"\.transfer\s*\(|\.call\s*\{", cleaned) and "require(" not in cleaned:
        issues.append(("MED", "Llamadas externas sin `require()` previo visible."))
    if not issues:
        return True, ("No se detectaron patrones de riesgo obvios.\n\n"
                      "Analisis estatico heuristico completado sin hallazgos.")
    counts = {"HIGH": 0, "MED": 0, "LOW": 0}
    for sev, _ in issues: counts[sev] += 1
    lines = ["## Informe de auditoria estatica (ChainGuard)", "",
             f"**Hallazgos:** {counts['HIGH']} HIGH / {counts['MED']} MED / {counts['LOW']} LOW", ""]
    for sev, msg in issues: lines.append(f"- **[{sev}]** {msg}")
    return counts["HIGH"] == 0, "\n".join(lines)

def validate_solidity(code): return analyze_solidity(code)
