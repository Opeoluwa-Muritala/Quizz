"""Stable entry point for Flask, Gunicorn, and Vercel."""
import utils.net
import utils.clients
import utils.http_session
import utils.transport
import utils.session
from talent_portal.application import app

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000)
