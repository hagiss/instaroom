from fastapi import FastAPI

from app.routes import generate

app = FastAPI(title="Instaroom", version="0.1.0")
app.include_router(generate.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
