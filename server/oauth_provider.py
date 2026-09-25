"""OAuth 2.1 Authorization Server for SketchUp MCP (Authorization Code + PKCE S256)."""

from __future__ import annotations

import os
import secrets
import time
from typing import Any

from pydantic import AnyHttpUrl
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken


def _env(name: str, default: str) -> str:
    value = os.getenv(name, default).strip()
    return value if value else default


class SketchupOAuthProvider(OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]):
    """Combined AS for MCP remote: Auth Code + PKCE, refresh tokens, DCR."""

    def __init__(
        self,
        *,
        server_url: str,
        login_path: str = "/login",
        scope: str = "sketchup",
        username: str | None = None,
        password: str | None = None,
        access_ttl_sec: int = 3600,
        refresh_ttl_sec: int = 86400 * 7,
        auth_code_ttl_sec: int = 300,
    ) -> None:
        self.server_url = server_url.rstrip("/")
        self.login_url = f"{self.server_url}{login_path}"
        self.scope = scope
        self.username = username or _env("MCP_OAUTH_USERNAME", "sketchup")
        env_password = password if password is not None else os.getenv("MCP_OAUTH_PASSWORD")
        self.password = (env_password or "").strip()
        if not self.password:
            raise ValueError(
                "MCP_OAUTH_PASSWORD is required for OAuth HTTP mode. "
                "Set a strong password before exposing the tunnel."
            )
        self.access_ttl_sec = access_ttl_sec
        self.refresh_ttl_sec = refresh_ttl_sec
        self.auth_code_ttl_sec = auth_code_ttl_sec

        self.clients: dict[str, OAuthClientInformationFull] = {}
        self.auth_codes: dict[str, AuthorizationCode] = {}
        self.access_tokens: dict[str, AccessToken] = {}
        self.refresh_tokens: dict[str, RefreshToken] = {}
        self.refresh_to_access: dict[str, str] = {}
        self.state_mapping: dict[str, dict[str, str | None]] = {}

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        return self.clients.get(client_id)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        if not client_info.client_id:
            raise ValueError("No client_id provided")
        self.clients[client_info.client_id] = client_info

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        state = params.state or secrets.token_urlsafe(24)
        self.state_mapping[state] = {
            "redirect_uri": str(params.redirect_uri),
            "code_challenge": params.code_challenge,
            "redirect_uri_provided_explicitly": str(params.redirect_uri_provided_explicitly),
            "client_id": client.client_id,
            "resource": params.resource,
            "scopes": " ".join(params.scopes or [self.scope]),
        }
        return f"{self.login_url}?state={state}&client_id={client.client_id}"

    async def get_login_page(self, state: str) -> HTMLResponse:
        if not state:
            raise HTTPException(400, "Missing state parameter")
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <title>SketchUp MCP Authorization</title>
  <style>
    body {{ font-family: system-ui, sans-serif; max-width: 420px; margin: 48px auto; padding: 0 16px; }}
    label {{ display:block; margin-top: 12px; font-size: 14px; }}
    input {{ width: 100%; padding: 10px; margin-top: 4px; box-sizing: border-box; }}
    button {{ margin-top: 16px; width: 100%; padding: 12px; background: #0b5fff; color: #fff; border: 0; cursor: pointer; }}
    .hint {{ color: #555; font-size: 13px; }}
  </style>
</head>
<body>
  <h1>Authorize SketchUp MCP</h1>
  <p class="hint">Sign in to grant ChatGPT permission to control SketchUp on this machine.</p>
  <form method="post" action="{self.server_url}/login/callback">
    <input type="hidden" name="state" value="{state}"/>
    <label>Username<input name="username" autocomplete="username" required value="{self.username}"/></label>
    <label>Password<input name="password" type="password" autocomplete="current-password" required/></label>
    <button type="submit">Allow access</button>
  </form>
</body>
</html>"""
        return HTMLResponse(html)

    async def handle_login_callback(self, request: Request) -> Response:
        form = await request.form()
        username = form.get("username")
        password = form.get("password")
        state = form.get("state")
        if not isinstance(username, str) or not isinstance(password, str) or not isinstance(state, str):
            raise HTTPException(400, "Missing or invalid form fields")
        redirect = await self._complete_login(username, password, state)
        return RedirectResponse(url=redirect, status_code=302)

    async def _complete_login(self, username: str, password: str, state: str) -> str:
        data = self.state_mapping.get(state)
        if not data:
            raise HTTPException(400, "Invalid or expired state")
        if username != self.username or not secrets.compare_digest(password, self.password):
            raise HTTPException(401, "Invalid credentials")

        redirect_uri = data["redirect_uri"]
        code_challenge = data["code_challenge"]
        client_id = data["client_id"]
        resource = data.get("resource")
        scopes = (data.get("scopes") or self.scope).split()
        assert redirect_uri and code_challenge and client_id

        code = f"sk_{secrets.token_urlsafe(32)}"
        self.auth_codes[code] = AuthorizationCode(
            code=code,
            client_id=client_id,
            redirect_uri=AnyHttpUrl(redirect_uri),
            redirect_uri_provided_explicitly=data["redirect_uri_provided_explicitly"] == "True",
            expires_at=time.time() + self.auth_code_ttl_sec,
            scopes=scopes,
            code_challenge=code_challenge,
            resource=resource,
            subject=username,
        )
        del self.state_mapping[state]
        return construct_redirect_uri(redirect_uri, code=code, state=state)

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        return self.auth_codes.get(authorization_code)

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        if authorization_code.code not in self.auth_codes:
            raise ValueError("Invalid authorization code")
        if not client.client_id:
            raise ValueError("No client_id")
        del self.auth_codes[authorization_code.code]
        return self._issue_tokens(
            client_id=client.client_id,
            scopes=authorization_code.scopes,
            resource=authorization_code.resource,
            subject=authorization_code.subject,
        )

    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str) -> RefreshToken | None:
        token = self.refresh_tokens.get(refresh_token)
        if token is None or token.client_id != client.client_id:
            return None
        if token.expires_at and token.expires_at < time.time():
            await self.revoke_token(token)
            return None
        return token

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        if refresh_token.token not in self.refresh_tokens:
            raise ValueError("Invalid refresh token")
        if not client.client_id:
            raise ValueError("No client_id")
        await self.revoke_token(refresh_token)
        return self._issue_tokens(
            client_id=client.client_id,
            scopes=scopes,
            resource=refresh_token.resource,
            subject=refresh_token.subject,
        )

    async def load_access_token(self, token: str) -> AccessToken | None:
        access = self.access_tokens.get(token)
        if not access:
            return None
        if access.expires_at and access.expires_at < time.time():
            del self.access_tokens[token]
            return None
        return access

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        if isinstance(token, AccessToken):
            self.access_tokens.pop(token.token, None)
            for rt, at in list(self.refresh_to_access.items()):
                if at == token.token:
                    self.refresh_tokens.pop(rt, None)
                    self.refresh_to_access.pop(rt, None)
            return
        at = self.refresh_to_access.pop(token.token, None)
        self.refresh_tokens.pop(token.token, None)
        if at:
            self.access_tokens.pop(at, None)

    def _issue_tokens(
        self,
        *,
        client_id: str,
        scopes: list[str],
        resource: str | None,
        subject: str | None,
    ) -> OAuthToken:
        access = f"atk_{secrets.token_urlsafe(32)}"
        refresh = f"rtk_{secrets.token_urlsafe(32)}"
        now = int(time.time())
        self.access_tokens[access] = AccessToken(
            token=access,
            client_id=client_id,
            scopes=scopes,
            expires_at=now + self.access_ttl_sec,
            resource=resource,
            subject=subject,
            claims={"iss": self.server_url},
        )
        self.refresh_tokens[refresh] = RefreshToken(
            token=refresh,
            client_id=client_id,
            scopes=scopes,
            expires_at=now + self.refresh_ttl_sec,
            resource=resource,
            subject=subject,
        )
        self.refresh_to_access[refresh] = access
        return OAuthToken(
            access_token=access,
            token_type="Bearer",
            expires_in=self.access_ttl_sec,
            scope=" ".join(scopes),
            refresh_token=refresh,
        )
