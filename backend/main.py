import os
import sys

# Make `routes` importable whether uvicorn is invoked from backend/ or project root.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(
    title="VeriChain API",
    description="Real-time document verification for loan underwriting",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

import store
store.init()  # create verifications table + migrate blockchain_log (idempotent)

from routes.verify import router as verify_router
from routes.batch import router as batch_router
from routes.history import router as history_router
app.include_router(batch_router)  # /verify/batch — register before /verify
app.include_router(verify_router)
app.include_router(history_router)  # /verifications


@app.get("/")
def root():
    return {"status": "VeriChain backend running"}


@app.get("/health")
def health():
    return {"status": "ok"}