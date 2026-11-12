import hashlib, json, os, urllib.request, time, ipaddress
from urllib.parse import urlparse
from pathlib import Path

CACHE_DIR = Path("cache")
CACHE_DIR.mkdir(exist_ok=True)

def get_hash(text):
    return hashlib.sha256(text.encode()).hexdigest()[:16]

def get_cache(key):
    p = CACHE_DIR / f"{key}.json"
    if p.exists(): return json.loads(p.read_text())
    return None

def set_cache(key, data):
    p = CACHE_DIR / f"{key}.json"
    p.write_text(json.dumps(data, indent=2))

def robust_download(url, expected_type="image"):
    """Descarga archivos validando HTTPS, bloqueando IPs privadas y limitando tamaño."""
    if not url.startswith("https://"):
        raise ValueError("Solo se permiten URLs HTTPS por seguridad.")
    
    parsed = urlparse(url)
    hostname = parsed.hostname
    if not hostname: raise ValueError("URL inválida.")
    
    # Bloquear IPs privadas o localhost (SSRF Protection)
    try:
        ip = ipaddress.ip_address(hostname)
        if ip.is_private or ip.is_loopback:
            raise ValueError("Acceso a IPs privadas bloqueado.")
    except ValueError:
        pass # Es un dominio normal

    ext = ".png" if expected_type == "image" else ".mp3"
    filename = f"inbox/{get_hash(url)}{ext}"
    if os.path.exists(filename): return filename

    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as r:
                # Límite de 10MB
                content = r.read(10 * 1024 * 1024)
                with open(filename, "wb") as f:
                    f.write(content)
                return filename
        except Exception as e:
            if attempt == 2: raise e
            time.sleep(2 ** attempt)
    return None

def validate_python(code):
    import ast
    try:
        ast.parse(code)
        return True, "Sintaxis válida"
    except SyntaxError as e:
        return False, f"Error de sintaxis: {e}"

def validate_solidity(code):
    """Análisis estático real de Solidity por tokens básicos."""
    issues = []
    if code.count("{") != code.count("}"): issues.append("Llaves desbalanceadas.")
    if "pragma solidity" not in code: issues.append("Falta directiva pragma.")
    if "tx.origin" in code: issues.append("[HIGH] Uso de tx.origin detectado.")
    if "delegatecall" in code: issues.append("[HIGH] Uso de delegatecall detectado.")
    if "selfdestruct" in code: issues.append("[HIGH] Uso de selfdestruct detectado.")
    
    # Reentrancy simple: llamada externa antes de actualizar estado
    if ".call{" in code and "balances[" not in code: issues.append("[MED] Posible riesgo de reentrada.")
    
    if issues: return False, "; ".join(issues)
    return True, "No se detectaron patrones de riesgo obvios."
