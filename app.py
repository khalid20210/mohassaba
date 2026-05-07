"""
app.py — entry point (thin)
كل المنطق موجود في modules/
"""
import os

from modules import create_app

app = create_app()

if __name__ == "__main__":
    debug = os.getenv("FLASK_DEBUG", "1").lower() in ("1", "true", "yes", "on")
    host = os.getenv("FLASK_RUN_HOST", "0.0.0.0")
    port = int(os.getenv("PORT", os.getenv("FLASK_RUN_PORT", "5001")))
    app.run(debug=debug, host=host, port=port)
