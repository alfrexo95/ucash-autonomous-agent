# -*- coding: utf-8 -*-
import json, sys, tempfile, time, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import self_repair as sr

class TestRegistroFallos(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.f = Path(self.tmp.name) / "failures.json"
    def test_record_y_pending(self):
        sr.record_failure("agent.py", "code_audit", "boom", failures_file=self.f)
        sr.record_failure("core_logic.py", "data_research", "boom2", failures_file=self.f)
        pend = sr.pending_failures(failures_file=self.f)
        self.assertEqual(len(pend), 2); self.assertEqual(pend[0]["status"], "pending")
    def test_mark_status_cierra_el_fallo(self):
        sr.record_failure("agent.py", "ocr_extractor", "error grave", failures_file=self.f)
        fid = sr.pending_failures(failures_file=self.f)[0]["id"]
        sr.mark_status(fid, "repaired", "rama enviada", failures_file=self.f)
        self.assertEqual(sr.pending_failures(failures_file=self.f), [])

class TestExtraccionDeCodigo(unittest.TestCase):
    def test_extrae_el_ultimo_bloque(self):
        text = ("intro\n```python\nprint(1)\n```\ntexto del medio\n```python\nprint(2)\n```\ncierre")
        self.assertEqual(sr.extract_code_block(text), "print(2)")
    def test_sin_bloque_devuelve_none(self): self.assertIsNone(sr.extract_code_block("no hay fences aqui"))

class TestValidacionCandidatos(unittest.TestCase):
    ORIGINAL = "def a():\n    return 1\n\nHANDLERS = {'x': a}\n"
    def test_acepta_candidato_valido(self):
        cand = "def a():\n    return 2\n\nHANDLERS = {'x': a}\n"
        ok, _ = sr.validate_candidate(self.ORIGINAL, cand); self.assertTrue(ok)
    def test_rechaza_sintaxis_invalida(self):
        ok, reason = sr.validate_candidate(self.ORIGINAL, "def a(:\n    return 1\n")
        self.assertFalse(ok); self.assertIn("sintaxis", reason)
    def test_rechaza_si_borra_definiciones(self):
        ok, reason = sr.validate_candidate(self.ORIGINAL, "HANDLERS = {}\n")
        self.assertFalse(ok); self.assertIn("elimina", reason)
    def test_rechaza_codigo_peligroso(self):
        ok, reason = sr.validate_candidate(self.ORIGINAL, self.ORIGINAL + "import subprocess\n")
        self.assertFalse(ok); self.assertIn("bloqueado", reason)
    def test_rechaza_tamano_desproporcionado(self):
        cand = self.ORIGINAL + "extra = 1\n" * 500
        ok, reason = sr.validate_candidate(self.ORIGINAL, cand)
        self.assertFalse(ok); self.assertIn("tamano", reason)

class TestGuardrails(unittest.TestCase):
    def test_archivo_no_editable_se_omite_sin_llamar_al_llm(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "failures.json"
            sr.record_failure("setup_ucash.py", "code_audit", "error", failures_file=f)
            entry = sr.pending_failures(failures_file=f)[0]
            self.assertEqual(sr.attempt_repair(entry, failures_file=f), "skipped")
    def test_workflow_y_secrets_son_intocables(self):
        for bloqueado in (".github/workflows/agent.yml", "self_repair.py", "tests/test_self_repair.py", ".env"):
            self.assertNotIn(bloqueado, sr.EDITABLE_FILES)
    def test_cooldown_cuenta_solo_reparaciones_recientes(self):
        with tempfile.TemporaryDirectory() as d:
            lp = Path(d) / "repair_log.json"; ahora = time.time()
            lp.write_text(json.dumps([{"result": "pushed", "ts_epoch": ahora - 3600}, {"result": "reverted", "ts_epoch": ahora - 3600}, {"result": "pushed", "ts_epoch": ahora - 100 * 3600}]))
            self.assertEqual(sr.repairs_in_window(12, log_file=lp), 1)

if __name__ == "__main__": unittest.main()
