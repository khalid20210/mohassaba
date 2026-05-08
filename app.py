"""
app.py — entry point (thin)
كل المنطق موجود في modules/
"""
import os

from modules import create_app

app = create_app()

if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "5001"))
    debug = os.environ.get("DEBUG", "false").lower() in ("1", "true", "yes")
    app.run(debug=debug, host=host, port=port)
