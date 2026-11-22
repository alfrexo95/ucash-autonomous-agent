# -*- coding: utf-8 -*-
import unittest
from core_logic import encrypt_bytes, decrypt_bytes, derive_key, strip_claim_code, validate_delivery_output, record_processed_state, _keystream, _CIPHER_MAGIC


class CoreLogicTests(unittest.TestCase):
    def test_new_delivery_cipher_authenticates_content(self):
        key = derive_key("tx-1", "claim-code")
        blob = encrypt_bytes(b"private report", key)
        self.assertTrue(blob.startswith(b"UCASH2"))
        self.assertEqual(decrypt_bytes(blob, key), b"private report")

    def test_new_delivery_cipher_rejects_tampering(self):
        key = derive_key("tx-2", "claim-code")
        blob = bytearray(encrypt_bytes(b"private report", key))
        blob[-1] ^= 1
        with self.assertRaises(ValueError):
            decrypt_bytes(bytes(blob), key)

    def test_legacy_ucash1_delivery_still_decrypts(self):
        key = derive_key("tx-3", "claim-code")
        nonce = b"0" * 16
        plaintext = b"legacy delivery"
        legacy = _CIPHER_MAGIC + nonce + bytes(a ^ b for a, b in zip(plaintext, _keystream(key, nonce, len(plaintext))))
        self.assertEqual(decrypt_bytes(legacy, key), plaintext)

    def test_claim_code_removed_from_order_before_service(self):
        text = "[Claim: secret_1234] audit this source"
        self.assertEqual(strip_claim_code(text), "audit this source")

    def test_failed_service_output_is_not_marked_as_success(self):
        self.assertFalse(validate_delivery_output("Error: model unavailable"))\n        self.assertFalse(validate_delivery_output("Error OCR: unsupported image"))
        self.assertFalse(validate_delivery_output(""))
        self.assertFalse(validate_delivery_output("   "))
        self.assertTrue(validate_delivery_output("## Report\nFindings: none"))

    def test_processed_transaction_recording_is_idempotent(self):
        state = {"processed_tx": [], "history": [], "needs_claim": {"tx-4": "code_audit"}, "in_progress": {"tx-4": "code_audit"}}
        self.assertTrue(record_processed_state(state, "tx-4", "code_audit", 5))
        self.assertFalse(record_processed_state(state, "tx-4", "code_audit", 5))
        self.assertEqual(state["processed_tx"], ["tx-4"])
        self.assertEqual(len(state["history"]), 1)
        self.assertEqual(state["earnings_usd"], 5.0)
        self.assertNotIn("tx-4", state["needs_claim"])
        self.assertNotIn("tx-4", state["in_progress")


if __name__ == "__main__":
    unittest.main()
