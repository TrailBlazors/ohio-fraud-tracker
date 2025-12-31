"""
Vercel Serverless Function Handler

This file exposes the FastAPI app to Vercel's serverless runtime.
All /api/* routes are handled by this single entry point.
"""

from app.main import app

# Vercel looks for an `app` variable or a `handler` function
# FastAPI's ASGI app works directly with Vercel's Python runtime
handler = app
