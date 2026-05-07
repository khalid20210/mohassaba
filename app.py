"""
app.py — entry point (thin)
كل المنطق موجود في modules/
"""
import os

from modules import create_app

app = create_app()

if __name__ == "__main__":
    flask_env = os.getenv("FLASK_ENV", "development").lower()
    debug_default = "0" if flask_env == "production" else "1"
    debug_raw = str(os.getenv("FLASK_DEBUG", debug_default)).strip()
    debug = debug_raw == "1" or (debug_raw and debug_raw.lower() in ("true", "yes", "on"))
    host = os.getenv("FLASK_RUN_HOST", "0.0.0.0")
    port = int(os.getenv("PORT", os.getenv("FLASK_RUN_PORT", "5001")))
    app.run(debug=debug, host=host, port=port)
