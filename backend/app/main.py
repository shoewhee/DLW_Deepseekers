from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .db import init_db
from .routers import auth, dashboard, planner, quiz, reports, topics

settings = get_settings()
allowed_origins = {settings.frontend_origin.rstrip("/")}

if "localhost" in settings.frontend_origin:
    allowed_origins.add(settings.frontend_origin.replace("localhost", "127.0.0.1").rstrip("/"))
if "127.0.0.1" in settings.frontend_origin:
    allowed_origins.add(settings.frontend_origin.replace("127.0.0.1", "localhost").rstrip("/"))

app = FastAPI(title="Study Mastery Assistant API", version="1.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(allowed_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.get("/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(auth.router)
app.include_router(topics.router)
app.include_router(quiz.router)
app.include_router(dashboard.router)
app.include_router(planner.router)
app.include_router(reports.router)
