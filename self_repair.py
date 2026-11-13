# -*- coding: utf-8 -*-
"""Predator Self-Repair — Autonomía extrema (paso 6)."""
import ast, difflib, json, os, random, re, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FAILURES_FILE = ROOT / "failures.json"
REPAIR_LOG_FILE = ROOT / "repair_log.json"
EDITABLE_FILES = {"agent.py", "core_logic.py", "multimodal/agent.py"}
BLOCKED_SUBSTRINGS = ("subprocess", "os.system", "eval(", "exec(", "__import__", "rm -rf")
MAX_REPAIRS_PER_CYCLE = int(os.environ.get("MAX_SELF_REPAIRS", "2"))
COOLDOWN_HOURS = float(os.environ.get("REPAIR_COOLDOWN_HOURS", "12"))
MAX_FAILURES_KEPT = 50

def log(msg): print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

def _load_json(path, default):
    try: return json.loads(Path(path).read_text())
    except Exception: return default

def _write_json(path, data):
    p = Path(path); tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False)); tmp.replace(p)

def record_failure(file, service, error, failures_file=None):
    fp = Path(failures_file or FAILURES_FILE)
    entries = _load_json(fp, [])
    if not isinstance(entries, list): entries = []
    entries.append({"id": f"{int(time.time()*1000)}-{random.randint(1000,9999)}", "file": str(file).replace("\\", "/"), "service": str(service), "error": str(error)[:6000], "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "status": "pending"})
    entries = entries[-MAX_FAILURES_KEPT:]
    _write_json(fp, entries); log(f"Fallo registrado [{service}] en {file}")

def pending_failures(failures_file=None):
    fp = Path(failures_file or FAILURES_FILE)
    entries = _load_json(fp, [])
    return [e for e in entries if isinstance(e, dict) and e.get("status") == "pending"]

def mark_status(fid, status, note="", failures_file=None):
    fp = Path(failures_file or FAILURES_FILE)
    entries = _load_json(fp, [])
    for e in entries:
        if isinstance(e, dict) and e.get("id") == fid:
            e["status"] = status; e["note"] = str(note)[:500]; e["closed"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    _write_json(fp, entries)

def repairs_in_window(hours=None, log_file=None):
    hours = COOLDOWN_HOURS if hours is None else hours
    lp = Path(log_file or REPAIR_LOG_FILE)
    cutoff = time.time() - hours * 3600
    n = 0
    for e in _load_json(lp, []):
        if (isinstance(e, dict) and e.get("result") == "pushed" and float(e.get("ts_epoch", 0) or 0) >= cutoff): n += 1
    return n

def log_repair(entry, log_file=None):
    lp = Path(log_file or REPAIR_LOG_FILE)
    entries = _load_json(lp, [])
    if not isinstance(entries, list): entries = []
    entry["ts_epoch"] = time.time(); entries.append(entry); _write_json(lp, entries[-200:])

_text_generator = None
def _ask_llm(system, user, max_tokens=3000):
    global _text_generator
    import torch
    from transformers import pipeline
    if _text_generator is None:
        model = os.environ.get("MODEL_NAME", "Qwen/Qwen2.5-Coder-3B-Instruct")
        log(f"Cargando {model} (esto puede tardar)...")
        _text_generator = pipeline("text-generation", model=model, device="cpu", torch_dtype=torch.float32, trust_remote_code=True)
    torch.manual_seed(42)
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    out = _text_generator(msgs, max_new_tokens=max_tokens, do_sample=False, repetition_penalty=1.1)
    return out[0]["generated_text"][-1]["content"].strip()

def extract_code_block(text):
    blocks = re.findall(r"```(?:python)?\s*\n(.*?)```", text, re.S)
    return blocks[-1].strip() if blocks else None

def propose_fix(rel_path, code, service, error):
    system = ("You are a senior Python engineer repairing a production AI agent. Return the COMPLETE corrected file inside ONE ```python fence. Make the MINIMAL change that fixes the error. Keep every existing function and constant. Do NOT add subprocess, eval, exec or new external dependencies. Output ONLY the code fence.")
    user = (f"File: {rel_path}\nFailing service: {service}\n\nError / traceback:\n{str(error)[:4000]}\n\nCurrent code:\n```python\n{code}\n```")
    out = _ask_llm(system, user, max_tokens=4000)
    candidate = extract_code_block(out)
    if not candidate: raise ValueError("el modelo no devolvio un bloque ```python```")
    return candidate + "\n"

def _top_level_names(src):
    try: tree = ast.parse(src)
    except SyntaxError: return None
    names = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)): names.add(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name): names.add(t.id)
    return names

def validate_candidate(original, candidate):
    if not candidate or not candidate.strip(): return False, "candidato vacio"
    try: ast.parse(candidate)
    except SyntaxError as e: return False, f"sintaxis invalida: {e}"
    if not (0.3 * len(original) <= len(candidate) <= 3.0 * len(original) + 2000): return False, f"tamano sospechoso: {len(candidate)} chars vs original {len(original)}"
    low = candidate.lower()
    for bad in BLOCKED_SUBSTRINGS:
        if bad in low: return False, f"contenido bloqueado en el candidato: {bad}"
    orig_names, cand_names = _top_level_names(original), _top_level_names(candidate)
    if orig_names and cand_names is not None and not orig_names <= cand_names:
        missing = sorted(orig_names - cand_names)[:5]
        return False, f"el candidato elimina definiciones: {missing}"
    return True, "ok"

def run_tests():
    if not (ROOT / "tests").exists(): return True, "sin directorio tests"
    try:
        r = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", ".", "-v"], cwd=ROOT, capture_output=True, text=True, timeout=1200)
        return r.returncode == 0, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired: return False, "los tests excedieron el timeout"

def git(*args, check=True):
    r = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True)
    if check and r.returncode != 0: raise RuntimeError(f"git {' '.join(args)} fallo: {r.stderr.strip()[:300]}")
    return r

def attempt_repair(failure, dry=False, failures_file=None, log_file=None):
    rel = str(failure.get("file", ""))
    if rel not in EDITABLE_FILES:
        mark_status(failure["id"], "skipped", f"archivo no editable: {rel}", failures_file=failures_file)
        return "skipped"
    target = ROOT / rel
    if not target.exists():
        mark_status(failure["id"], "skipped", "el archivo no existe", failures_file=failures_file)
        return "skipped"
    original = target.read_text()
    try: candidate = propose_fix(rel, original, failure.get("service", "?"), failure.get("error", ""))
    except Exception as e:
        mark_status(failure["id"], "failed", f"la propuesta fallo: {e}", failures_file=failures_file)
        return "failed"
    ok, reason = validate_candidate(original, candidate)
    diff = "\n".join(difflib.unified_diff(original.splitlines(), candidate.splitlines(), fromfile=f"a/{rel}", tofile=f"b/{rel}", lineterm="", n=2))
    if not ok:
        mark_status(failure["id"], "failed", f"candidato rechazado: {reason}", failures_file=failures_file)
        log(f"Candidato rechazado ({reason}). No se toca nada.")
        return "rejected"
    if dry:
        print("\n" + "=" * 60 + "\nDIFF PROPUESTO (dry-run, nada se modifica):\n" + "=" * 60)
        print(diff); return "proposed"
    branch = f"self-repair/{time.strftime('%Y%m%d%H%M%S')}-{random.randint(100, 999)}"
    try:
        git("checkout", "-q", "-b", branch)
        target.write_text(candidate)
        tests_ok, out = run_tests()
        if not tests_ok:
            target.write_text(original); git("checkout", "-q", "master"); git("branch", "-q", "-D", branch)
            log_repair({"branch": branch, "file": rel, "service": failure.get("service"), "result": "reverted", "tests": out[-800:]}, log_file=log_file)
            mark_status(failure["id"], "failed", "los tests fallaron con el parche aplicado", failures_file=failures_file)
            log("Tests fallaron con el parche: revertido por completo.")
            return "reverted"
        git("add", rel)
        err_line = (failure.get("error", "").strip().splitlines() or ["error"])[-1][:100]
        msg = (f"fix(self-repair): {failure.get('service', '?')} — {err_line}\n\nParche generado por el propio agente (Qwen local), validado con unittest antes de subir.\n\nCo-authored-by: Predator Self-Repair <self-repair@localhost>")
        git("commit", "-q", "-m", msg)
        git("push", "-q", "-u", "origin", branch)
        log_repair({"branch": branch, "file": rel, "service": failure.get("service"), "result": "pushed"}, log_file=log_file)
        mark_status(failure["id"], "repaired", f"rama {branch} enviada", failures_file=failures_file)
        git("checkout", "-q", "master")
        log(f"Reparacion subida en la rama {branch}.")
        return "pushed"
    except Exception as e:
        try:
            target.write_text(original); git("checkout", "-q", "master"); git("branch", "-q", "-D", branch, check=False)
        except Exception: pass
        mark_status(failure["id"], "failed", f"git fallo: {e}", failures_file=failures_file)
        return "failed"

def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "status"
    failures = pending_failures()
    log(f"Fallos pendientes: {len(failures)}")
    if mode == "status" or not failures:
        for f in failures: log(f"  - [{f.get('service')}] {f.get('file')} @ {f.get('ts')}")
        if mode != "status": log("Nada que reparar. El agente esta sano.")
        return
    done = repairs_in_window()
    if done >= MAX_REPAIRS_PER_CYCLE:
        log(f"Guardrail activo: {done} reparaciones ya hechas en las ultimas {COOLDOWN_HOURS}h.")
        return
    budget = min(MAX_REPAIRS_PER_CYCLE, MAX_REPAIRS_PER_CYCLE - done)
    log(f"Presupuesto de este ciclo: {budget} reparacion(es)")
    for f in failures[:budget]:
        log(f"Reparando [{f.get('service')}] en {f.get('file')}...")
        result = attempt_repair(f, dry=(mode == "dry"))
        log(f"Resultado: {result}")

if __name__ == "__main__": main()
