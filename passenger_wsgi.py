"""Passenger WSGI entry point for cPanel Python App hosting.

cPanel's "Setup Python App" uses Phusion Passenger, which expects a file named
`passenger_wsgi.py` with an `application` callable (WSGI).

FastAPI is ASGI, so we use `a2wsgi` to bridge ASGI→WSGI for Passenger.
"""
import os
import sys

# Ensure the app directory is on the path
sys.path.insert(0, os.path.dirname(__file__))

# Load environment from .env before anything else
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from api import app  # noqa: E402 — FastAPI app

try:
    from a2wsgi import ASGIMiddleware
    application = ASGIMiddleware(app)
except ImportError:
    raise RuntimeError(
        "Missing 'a2wsgi' package. Install it:\n"
        "  pip install a2wsgi\n"
        "Or in cPanel Python App → 'Run pip install' → a2wsgi"
    )
