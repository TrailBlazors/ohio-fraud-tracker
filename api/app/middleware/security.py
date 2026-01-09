"""
Security middleware for blocking malicious bot traffic.

Instantly rejects requests to known attack paths (WordPress, PHP exploits, etc.)
without any processing, saving server resources and reducing log noise.
"""

from fastapi import Request
from fastapi.responses import Response
from starlette.middleware.base import BaseHTTPMiddleware


# Paths that are 100% malicious bot traffic
BLOCKED_PATH_PREFIXES = {
    "/wp-admin",
    "/wp-login",
    "/wp-content",
    "/wp-includes",
    "/wordpress",
    "/xmlrpc.php",
    "/.env",
    "/.git",
    "/.svn",
    "/.htaccess",
    "/config.php",
    "/admin.php",
    "/administrator",
    "/phpmyadmin",
    "/pma",
    "/myadmin",
    "/mysql",
    "/backup",
    "/shell",
    "/c99",
    "/r57",
    "/eval-stdin.php",
    "/cgi-bin",
    "/scripts",
    "/aspnet_client",
    "/vendor/phpunit",
    "/solr",
    "/actuator",
    "/manager/html",
    "/invoker",
    "/jmx-console",
    "/web-console",
    "/console",
    "/debug",
    "/telescope",
    "/elfinder",
    "/filemanager",
}

# File extensions that should never be requested
BLOCKED_EXTENSIONS = {
    ".php",
    ".asp",
    ".aspx",
    ".jsp",
    ".cgi",
    ".pl",
}


class BotBlockerMiddleware(BaseHTTPMiddleware):
    """Middleware that blocks known malicious bot requests."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path.lower()

        # Block known attack path prefixes
        for blocked in BLOCKED_PATH_PREFIXES:
            if path.startswith(blocked):
                return Response(status_code=404)

        # Block dangerous file extensions
        for ext in BLOCKED_EXTENSIONS:
            if path.endswith(ext):
                return Response(status_code=404)

        return await call_next(request)
