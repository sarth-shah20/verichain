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

# Routes — uncomment as each module is ready
# from routes import verify, history, mock
# app.include_router(verify.router)
# app.include_router(history.router)
# app.include_router(mock.router)

@app.get("/")
def root():
    return {"status": "VeriChain backend running"}

@app.get("/health")
def health():
    return {"status": "ok"}