from pathlib import Path
import sys
import json
import io
import os
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from daytrace.personalization.provider import TextProvider, Vault, NoRedirect, DEEPSEEK_ENDPOINT, DEEPSEEK_MODEL


class ProviderTests(unittest.TestCase):
    def test_removed_review_never_sends(self):
        provider = self.provider()
        provider.opener = Mock()
        with self.assertRaises(ValueError):
            provider.classify({'mode': 'review', 'records': []})
        provider.opener.open.assert_not_called()

    def payload(self):
        return {'profile': {}, 'candidates': [{'id': 'task'}], 'evidence': [
            {'interval_id': 'interval', 'evidence_ids': ['event'], 'title': 'Synthetic activity', 'text': ''}]}

    def provider(self, budget=2):
        return TextProvider('https://example.invalid/v1/chat/completions', 'test-model', budget=budget, vault=Mock(get=lambda: 'synthetic-not-a-real-key'))

    def response(self):
        results = [{'interval_id': 'interval', 'task_id': 'task', 'evidence_ids': ['event']}]
        return io.BytesIO(json.dumps({'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps({'results': results})}}]}).encode())

    def test_request_is_text_only_bounded_cached_and_cancelled(self):
        provider = self.provider()
        with patch.object(provider.opener, 'open', return_value=self.response()) as send:
            result = provider.classify(self.payload())
            self.assertEqual(result[0]['task_id'], 'task')
            provider.classify(self.payload())
            self.assertEqual(send.call_count, 1)
            body = json.loads(send.call_args.args[0].data)
            self.assertNotIn('tools', body)
            self.assertNotIn('image', json.dumps(body))
            self.assertFalse(body['store'])
            self.assertEqual(send.call_args.kwargs['timeout'], 15)
            provider.cancel()
            self.assertEqual(provider.cache, {})
            with self.assertRaises(RuntimeError):
                provider.classify(self.payload())

    def test_retry_budget_and_redirection(self):
        provider = self.provider()
        with patch.object(provider.opener, 'open', side_effect=OSError('secret response')) as send:
            with self.assertRaisesRegex(RuntimeError, '^AI unavailable$'):
                provider.classify(self.payload())
            self.assertEqual(send.call_count, 2)
            with self.assertRaises(RuntimeError):
                provider.classify(self.payload())
            self.assertEqual(send.call_count, 2)
        with self.assertRaises(RuntimeError):
            NoRedirect().redirect_request()
        for endpoint in ('http://example.com', 'https://user:key@example.com', 'https://example.com?key=value'):
            with self.assertRaises(ValueError):
                TextProvider(endpoint, 'test', vault=Mock())

    def test_deepseek_documented_parameters_and_generic_host_isolation(self):
        for endpoint in (DEEPSEEK_ENDPOINT, 'https://api.deepseek.com/v1/chat/completions',
                         'https://api.deepseek.com.example.invalid/chat/completions'):
            provider = TextProvider(endpoint, DEEPSEEK_MODEL, vault=Mock(get=lambda: 'synthetic-not-a-real-key'))
            with patch.object(provider.opener, 'open', return_value=self.response()) as send:
                provider.classify(self.payload())
                body = json.loads(send.call_args.args[0].data)
                if '.invalid' in endpoint:
                    self.assertIn('max_completion_tokens', body)
                    self.assertNotIn('thinking', body)
                else:
                    self.assertEqual(body['max_tokens'], 2000)
                    self.assertEqual(body['thinking'], {'type': 'disabled'})
                    self.assertFalse(body['stream'])
                    self.assertNotIn('max_completion_tokens', body)
                    self.assertNotIn('store', body)
                    self.assertEqual(body['response_format'], {'type': 'json_object'})

    def test_inflight_cancel_drops_response(self):
        provider = self.provider()
        def send(*args, **kwargs):
            provider.cancel()
            return self.response()
        with patch.object(provider.opener, 'open', side_effect=send):
            with self.assertRaises(ValueError):
                provider.classify(self.payload())
        self.assertEqual(provider.cache, {})

    @unittest.skipUnless(os.name == 'nt', 'Windows Credential Manager required')
    def test_windows_vault_synthetic_roundtrip_and_delete(self):
        import uuid
        vault = Vault('https://synthetic-vault-test.invalid/' + str(uuid.uuid4()))
        value = 'synthetic-test-value-' + str(uuid.uuid4())
        try:
            vault.put(value)
            self.assertEqual(vault.get(), value)
        finally:
            vault.delete()
        with self.assertRaises(RuntimeError):
            vault.get()
