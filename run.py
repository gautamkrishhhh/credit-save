"""Start CreditSage locally:  python run.py  ->  http://localhost:8000"""
import os
import sys

import uvicorn

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend"))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("app.main:create_app", factory=True, host=os.environ.get("HOST", "127.0.0.1"), port=port,
                reload=bool(os.environ.get("RELOAD")))
