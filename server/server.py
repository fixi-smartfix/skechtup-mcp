"""SketchUp MCP entrypoint - stdio (local) or streamable-http + OAuth 2.1 (remote)."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

# Allow `python server/server.py` (script path) to import sibling modules.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from pydantic import AnyHttpUrl
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared.auth import ProtectedResourceMetadata

from oauth_provider import SketchupOAuthProvider
from tools import INSTRUCTIONS, register_tools

logger = logging.getLogger("sketchup-mcp")

SCOPE = os.getenv("MCP_SCOPE", "sketchup").strip() or "sketchup"


def _public_base() -> str:
    raw = os.getenv("MCP_PUBLIC_URL", "").strip().rstrip("/")
    if not raw:
        raise RuntimeError(
            "MCP_PUBLIC_URL is required for streamable-http OAuth mode "
            "(e.g. https://sketchup.example.com from Cloudflare Tunnel)."
        )
    parsed = urlparse(raw)
    if parsed.scheme != "https" and parsed.hostname not in ("localhost", "127.0.0.1"):
        raise RuntimeError("MCP_PUBLIC_URL must be https (or http://127.0.0.1 for local test)")
    return raw


def create_stdio_app() -> FastMCP:
    app = FastMCP("sketchup", instructions=INSTRUCTIONS)
    register_tools(app)
    return app


def create_oauth_http_app() -> tuple[FastMCP, SketchupOAuthProvider]:
    """MCP Resource Server + Authorization Server (Auth Code + PKCE) on one origin."""
    public = _public_base()
    resource_url = f"{public}/mcp"
    host = os.getenv("MCP_HTTP_HOST", "127.0.0.1")
    port = int(os.getenv("MCP_HTTP_PORT", "8788"))

    oauth = SketchupOAuthProvider(server_url=public, login_path="/login", scope=SCOPE)

    public_host = urlparse(public).hostname or ""
    transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[
            public_host,
            f"{public_host}:443",
            f"{public_host}:*",
            "127.0.0.1:*",
            "localhost:*",
            "[::1]:*",
        ],
        allowed_origins=[
            public,
            f"https://{public_host}",
            "https://chatgpt.com",
            "https://*.chatgpt.com",
            "https://chat.openai.com",
            "https://claude.ai",
            "https://*.claude.ai",
            "http://127.0.0.1:*",
            "http://localhost:*",
        ],
    )

    app = FastMCP(
        "sketchup",
        instructions=INSTRUCTIONS,
        host=host,
        port=port,
        streamable_http_path="/mcp",
        auth_server_provider=oauth,
        auth=AuthSettings(
            issuer_url=AnyHttpUrl(public),
            resource_server_url=AnyHttpUrl(resource_url),
            required_scopes=[SCOPE],
            validate_token_resource=True,
            client_registration_options=ClientRegistrationOptions(
                enabled=True,
                valid_scopes=[SCOPE],
                default_scopes=[SCOPE],
            ),
            revocation_options=RevocationOptions(enabled=True),
        ),
        transport_security=transport_security,
    )
    register_tools(app)

    @app.custom_route("/login", methods=["GET"])
    async def login_page(request: Request) -> Response:
        state = request.query_params.get("state")
        if not state:
            raise HTTPException(400, "Missing state parameter")
        return await oauth.get_login_page(state)

    @app.custom_route("/login/callback", methods=["POST"])
    async def login_callback(request: Request) -> Response:
        return await oauth.handle_login_callback(request)

    # Also expose PRM at root well-known (in addition to /mcp path insertion).
    @app.custom_route("/.well-known/oauth-protected-resource", methods=["GET", "OPTIONS"])
    async def protected_resource_root(_request: Request) -> Response:
        meta = ProtectedResourceMetadata(
            resource=AnyHttpUrl(resource_url),
            authorization_servers=[AnyHttpUrl(public)],
            scopes_supported=[SCOPE],
            resource_name="SketchUp MCP",
        )
        return JSONResponse(
            meta.model_dump(mode="json", exclude_none=True),
            headers={"Cache-Control": "no-store", "Access-Control-Allow-Origin": "*"},
        )

    return app, oauth


def main() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    transport = os.getenv("MCP_TRANSPORT", "stdio").strip().lower()

    if transport in ("stdio", ""):
        create_stdio_app().run(transport="stdio")
        return

    if transport not in ("streamable-http", "http", "sse"):
        raise SystemExit(f"Unsupported MCP_TRANSPORT={transport!r}")

    app, _ = create_oauth_http_app()
    public = _public_base()
    logger.info("SketchUp MCP OAuth HTTP on %s (resource %s/mcp)", public, public)
    logger.info(
        "Well-known: %s/.well-known/oauth-authorization-server and "
        "%s/.well-known/oauth-protected-resource[/mcp]",
        public,
        public,
    )
    logger.info(
        "Cloudflare Tunnel must target http://%s:%s (NOT SketchUp :8766)",
        app.settings.host,
        app.settings.port,
    )
    run_transport = "sse" if transport == "sse" else "streamable-http"
    app.run(transport=run_transport)


# Default module-level app for stdio MCP clients (Cursor mcp.json).
mcp = create_stdio_app()

if __name__ == "__main__":
    main()
