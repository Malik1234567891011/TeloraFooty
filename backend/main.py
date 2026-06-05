from fastapi import FastAPI

app = FastAPI(title="TeloraFooty")


@app.get("/api/health")
def health():
    return {"ok": True}
