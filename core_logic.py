import hashlib, json, os, urllib.request, time
from pathlib import Path

CACHE_DIR = Path("cache")
CACHE_DIR.mkdir(exist_ok=True)

def get_hash(text):
    return hashlib.sha256(text.encode()).hexdigest()[:16]

def get_cache(key):
    p = CACHE_DIR / f"{key}.json"
    if p.exists():
        return json.loads(p.read_text())
    return None

def set_cache(key, data):
    p = CACHE_DIR / f"{key}.json"
    p.write_text(json.dumps(data, indent=2))

def robust_download(url, expected_type="image"):
    """Descarga archivos con reintentos y valida el tipo MIME."""
    ext = ".png" if expected_type == "image" else ".mp3"
    if not url.startswith("http"):
        return url # Fallback local
    
    filename = f"inbox/{get_hash(url)}{ext}"
    if os.path.exists(filename):
        return filename

    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as r:
                content_type = r.headers.get("Content-Type", "")
                if expected_type == "image" and not content_type.startswith("image/"):
                    raise ValueError(f"URL no es una imagen (MIME: {content_type})")
                with open(filename, "wb") as f:
                    f.write(r.read())
                return filename
        except Exception as e:
            if attempt == 2: raise e
            time.sleep(2 ** attempt) # Backoff exponencial
    return None

def validate_python(code):
    """Valida la sintaxis del código Python generado."""
    import ast
    try:
        ast.parse(code)
        return True, "Sintaxis válida"
    except SyntaxError as e:
        return False, f"Error de sintaxis: {e}"

def validate_solidity(code):
    """Validación básica de Solidity (llaves y puntos y coma)."""
    if code.count("{") != code.count("}"):
        return False, "Llaves desbalanceadas en Solidity"
    if "pragma solidity" not in code:
        return False, "Falta la directiva 'pragma solidity'"
    return True, "Estructura básica válida"
