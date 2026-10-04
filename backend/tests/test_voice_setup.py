"""Setup checks must work before credentials exist and never contact providers."""
import importlib.util
from pathlib import Path

import httpx
import httpx2
import pytest
from dotenv import dotenv_values

from app import config


@pytest.fixture
def setup(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location("voice_setup_checks", Path(__file__).resolve().parents[1] / "scripts/setup_voice.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ENV", tmp_path / ".env")
    for key in ("API_TOKEN", "PUBLIC_URL", "ELEVENLABS_API_KEY", "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_PHONE_NUMBER"):
        monkeypatch.setattr(config, key, "")
    def unexpected(request):
        pytest.fail("Local preparation/check attempted an HTTP request")
    monkeypatch.setattr(module, "_http", httpx.Client(transport=httpx.MockTransport(unexpected)))
    monkeypatch.setattr(httpx2, "AsyncClient", lambda **kwargs: pytest.fail("Local check attempted an MCP connection"))
    return module


def test_prepare_preserves_existing_settings_and_token(setup, monkeypatch, capsys):
    setup.ENV.write_text("# Keep this\nGEMINI_API_KEY=keep-me\nTWILIO_AUTH_TOKEN=private-secret\n")
    monkeypatch.setattr(config, "TWILIO_AUTH_TOKEN", "private-secret")
    setup.main(["--prepare"])
    first = dotenv_values(setup.ENV)
    assert first["GEMINI_API_KEY"] == "keep-me"
    assert first["TWILIO_AUTH_TOKEN"] == "private-secret"
    assert len(first["API_TOKEN"]) >= 32
    assert "ELEVENLABS_API_KEY" in first and "PUBLIC_URL" in first
    setup.main(["--prepare"])
    assert dotenv_values(setup.ENV)["API_TOKEN"] == first["API_TOKEN"]
    assert "# Keep this" in setup.ENV.read_text()
    output = capsys.readouterr().out
    assert "private-secret" not in output and first["API_TOKEN"] not in output


def test_check_reports_missing_settings_without_writes_or_network(setup, monkeypatch, capsys):
    monkeypatch.setattr(config, "ELEVENLABS_API_KEY", "private-key")
    with pytest.raises(SystemExit) as error:
        setup.main(["--check"])
    assert error.value.code == 1
    output = capsys.readouterr().out
    assert "TWILIO_ACCOUNT_SID" in output and "PUBLIC_URL" in output
    assert "private-key" not in output
    assert not setup.ENV.exists()


def test_check_ready_does_not_connect(setup, monkeypatch, capsys):
    for key, value in {"API_TOKEN": "private-token", "PUBLIC_URL": "https://demo.ngrok.app", "ELEVENLABS_API_KEY": "private-key",
                       "TWILIO_ACCOUNT_SID": "ACtest", "TWILIO_AUTH_TOKEN": "private-twilio", "TWILIO_PHONE_NUMBER": "+17345550199"}.items():
        monkeypatch.setattr(config, key, value)
    setup.main(["--check"])
    assert "ready" in capsys.readouterr().out.lower()
    assert not setup.ENV.exists()


def test_setup_requires_prepared_token_before_any_remote_change(setup, monkeypatch):
    for key, value in {"PUBLIC_URL": "https://demo.ngrok.app", "ELEVENLABS_API_KEY": "xi", "TWILIO_ACCOUNT_SID": "ACtest",
                       "TWILIO_AUTH_TOKEN": "tok", "TWILIO_PHONE_NUMBER": "+17345550199"}.items():
        monkeypatch.setattr(config, key, value)
    with pytest.raises(SystemExit) as error:
        setup.main([])
    assert "--prepare" in str(error.value)
    assert not setup.ENV.exists()


def test_tunnel_check_rejects_a_server_running_without_token_protection(setup, monkeypatch):
    monkeypatch.setattr(config, "API_TOKEN", "tok")
    monkeypatch.setattr(setup, "_http", httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={}))))
    # Avoid a real MCP session; the anonymous HTTP check must reject this server first.
    def skip_session(coroutine):
        coroutine.close()
        return []
    monkeypatch.setattr(setup.asyncio, "run", skip_session)
    with pytest.raises(SystemExit, match="restart"):
        setup.check_public_url("https://demo.ngrok.app/mcp")


def test_agent_update_failure_does_not_create_a_duplicate(setup, monkeypatch):
    monkeypatch.setattr(config, "ELEVENLABS_AGENT_ID", "existing-agent")
    requests = []
    def refused(request):
        requests.append(request.method)
        return httpx.Response(422, json={"detail": "invalid agent configuration"})
    monkeypatch.setattr(setup, "_http", httpx.Client(transport=httpx.MockTransport(refused)))
    with pytest.raises(SystemExit):
        setup.upsert_agent("mcp1")
    assert requests == ["PATCH"]


def test_existing_twilio_number_must_be_explicitly_selected(setup):
    with pytest.raises(SystemExit, match="TWILIO_PHONE_NUMBER"):
        setup.twilio_number(False)


@pytest.mark.parametrize("old_url, expected_methods, expected_id", [
    ("https://demo.ngrok.app/mcp", ["GET", "PATCH"], "owned-mcp"),
    ("https://previous.ngrok.app/mcp", ["GET", "POST"], "new-mcp"),
    (None, ["GET", "POST"], "new-mcp"),
])
def test_mcp_rerun_uses_saved_id_and_preserves_other_registrations(setup, monkeypatch, old_url, expected_methods, expected_id):
    monkeypatch.setattr(config, "ELEVENLABS_MCP_SERVER_ID", "owned-mcp", raising=False)
    requests = []
    def provider(request):
        requests.append(request.method)
        if request.method == "GET" and request.url.path.endswith("/owned-mcp"):
            if old_url is None:
                return httpx.Response(404, json={"detail": "not found"})
            return httpx.Response(200, json={"id": "owned-mcp", "config": {"url": old_url, "transport": "STREAMABLE_HTTP"}})
        if request.method == "PATCH" and request.url.path.endswith("/owned-mcp"):
            return httpx.Response(200, json={"id": "owned-mcp"})
        if request.method == "POST" and request.url.path.endswith("/mcp-servers"):
            return httpx.Response(200, json={"id": "new-mcp"})
        pytest.fail(f"Unexpected resource operation: {request.method} {request.url.path}")
    monkeypatch.setattr(setup, "_http", httpx.Client(transport=httpx.MockTransport(provider)))
    assert setup.register_mcp("https://demo.ngrok.app/mcp") == expected_id
    assert requests == expected_methods
    if expected_id == "new-mcp":
        # Persist before the agent update: a failed update must resume this registration.
        assert dotenv_values(setup.ENV)["ELEVENLABS_MCP_SERVER_ID"] == "new-mcp"
