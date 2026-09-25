"""OAuth 2.1 / PKCE unit tests (no SketchUp, no network)."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import secrets
import sys
import time
from pathlib import Path

import pytest
from pydantic import AnyUrl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

from mcp.server.auth.provider import AuthorizationParams  # noqa: E402
from mcp.shared.auth import OAuthClientInformationFull  # noqa: E402
from oauth_provider import SketchupOAuthProvider  # noqa: E402


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


def _client() -> OAuthClientInformationFull:
    return OAuthClientInformationFull(
        client_id="test-client",
        redirect_uris=[AnyUrl("http://127.0.0.1/callback")],
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        token_endpoint_auth_method="none",
    )


def test_authorize_login_and_pkce_token_exchange():
    async def _run() -> None:
        provider = SketchupOAuthProvider(
            server_url="http://127.0.0.1:8788",
            username="u1",
            password="p1",
            scope="sketchup",
        )
        client = _client()
        await provider.register_client(client)
        verifier, challenge = _pkce_pair()

        login_url = await provider.authorize(
            client,
            AuthorizationParams(
                state="st1",
                scopes=["sketchup"],
                code_challenge=challenge,
                redirect_uri=AnyUrl("http://127.0.0.1/callback"),
                redirect_uri_provided_explicitly=True,
                resource="http://127.0.0.1:8788/mcp",
            ),
        )
        assert "login" in login_url
        assert "state=st1" in login_url

        redirect = await provider._complete_login("u1", "p1", "st1")
        assert "code=" in redirect
        code = redirect.split("code=")[1].split("&")[0]

        auth_code = await provider.load_authorization_code(client, code)
        assert auth_code is not None
        assert auth_code.code_challenge == challenge
        assert auth_code.resource == "http://127.0.0.1:8788/mcp"

        hashed = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        assert hashed == auth_code.code_challenge

        tokens = await provider.exchange_authorization_code(client, auth_code)
        assert tokens.access_token.startswith("atk_")
        assert tokens.refresh_token
        assert tokens.token_type == "Bearer"

        access = await provider.load_access_token(tokens.access_token)
        assert access is not None
        assert access.scopes == ["sketchup"]
        assert access.resource == "http://127.0.0.1:8788/mcp"

    asyncio.run(_run())


def test_bad_password_rejected():
    async def _run() -> None:
        provider = SketchupOAuthProvider(server_url="http://127.0.0.1:8788", username="u1", password="p1")
        client = _client()
        await provider.register_client(client)
        _, challenge = _pkce_pair()
        await provider.authorize(
            client,
            AuthorizationParams(
                state="st2",
                scopes=["sketchup"],
                code_challenge=challenge,
                redirect_uri=AnyUrl("http://127.0.0.1/callback"),
                redirect_uri_provided_explicitly=True,
                resource=None,
            ),
        )
        with pytest.raises(Exception):
            await provider._complete_login("u1", "wrong", "st2")

    asyncio.run(_run())


def test_expired_access_token_returns_none():
    async def _run() -> None:
        provider = SketchupOAuthProvider(
            server_url="http://127.0.0.1:8788",
            username="u1",
            password="p1",
            access_ttl_sec=1,
        )
        client = _client()
        await provider.register_client(client)
        _, challenge = _pkce_pair()
        await provider.authorize(
            client,
            AuthorizationParams(
                state="st3",
                scopes=["sketchup"],
                code_challenge=challenge,
                redirect_uri=AnyUrl("http://127.0.0.1/callback"),
                redirect_uri_provided_explicitly=True,
                resource="http://127.0.0.1:8788/mcp",
            ),
        )
        redirect = await provider._complete_login("u1", "p1", "st3")
        code = redirect.split("code=")[1].split("&")[0]
        auth_code = await provider.load_authorization_code(client, code)
        tokens = await provider.exchange_authorization_code(client, auth_code)
        provider.access_tokens[tokens.access_token].expires_at = int(time.time()) - 10
        assert await provider.load_access_token(tokens.access_token) is None

    asyncio.run(_run())


def test_refresh_rotates_tokens():
    async def _run() -> None:
        provider = SketchupOAuthProvider(server_url="http://127.0.0.1:8788", username="u1", password="p1")
        client = _client()
        await provider.register_client(client)
        _, challenge = _pkce_pair()
        await provider.authorize(
            client,
            AuthorizationParams(
                state="st4",
                scopes=["sketchup"],
                code_challenge=challenge,
                redirect_uri=AnyUrl("http://127.0.0.1/callback"),
                redirect_uri_provided_explicitly=True,
                resource="http://127.0.0.1:8788/mcp",
            ),
        )
        redirect = await provider._complete_login("u1", "p1", "st4")
        code = redirect.split("code=")[1].split("&")[0]
        auth_code = await provider.load_authorization_code(client, code)
        tokens = await provider.exchange_authorization_code(client, auth_code)
        old_access = tokens.access_token
        rt = await provider.load_refresh_token(client, tokens.refresh_token)
        assert rt is not None
        new_tokens = await provider.exchange_refresh_token(client, rt, ["sketchup"])
        assert new_tokens.access_token != old_access
        assert await provider.load_access_token(old_access) is None

    asyncio.run(_run())
