import json

from src import report
from src.api.gateway import AuthContext
from src.http_error import HttpError


def test_json_attachments_redact_nested_credentials_without_mutating_payload(monkeypatch):
    captured = []
    monkeypatch.setattr(report.allure, 'attach', lambda body, **kwargs: captured.append(body))
    payload = {'variables': {'input': {'password': 'private-password-unique'}},
               'data': {'login': {'token': 'private-token-unique', 'user': {'id': 'user-1'}}}}
    report.attach_json('graphql', payload)
    saved = json.loads(captured[0])
    assert saved['variables']['input']['password'] == '[REDACTED]'
    assert saved['data']['login']['token'] == '[REDACTED]'
    assert saved['data']['login']['user']['id'] == 'user-1'
    assert payload['data']['login']['token'] == 'private-token-unique'


def test_error_diagnostics_redact_credentials_and_reflections():
    report.redact({'password': 'reflected-private-password'})
    error = HttpError('Rejected reflected-private-password', response={
        'token': 'response-private-token',
        'errors': [{'message': 'bad reflected-private-password'}],
    })
    assert 'reflected-private-password' not in str(error)
    assert 'response-private-token' not in str(error)
    assert 'Rejected' in str(error)


def test_auth_context_repr_never_contains_password_or_token():
    context = AuthContext(token='context-private-token', user_id='id', email='test@example.test',
                          username='test', password='context-private-password')
    assert 'context-private-token' not in repr(context)
    assert 'context-private-password' not in repr(context)
    assert "user_id='id'" in repr(context)


def test_evidence_gate_rejects_leak_without_echoing_the_secret(tmp_path):
    import pytest
    from scripts.check_evidence import verify_evidence

    path = tmp_path / 'result.json'
    path.write_text('{"error": "artifact-private-password"}')
    with pytest.raises(RuntimeError) as error:
        verify_evidence([tmp_path], ['artifact-private-password'])
    assert 'artifact-private-password' not in str(error.value)
    path.write_text('{"error": "[REDACTED]"}')
    verify_evidence([tmp_path], ['artifact-private-password'])
