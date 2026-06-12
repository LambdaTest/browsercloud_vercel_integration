# Vercel Python runtime entrypoint. Exposes the FastAPI ASGI app; vercel.json
# rewrites all routes here.
from app.main import app  # noqa: F401
