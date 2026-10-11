import hashlib
import os
import secrets
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

ROOT = Path(__file__).resolve().parent
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{ROOT / 'trading_arena.db'}")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
elif DATABASE_URL.startswith("postgresql://") and "+psycopg" not in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

engine_kwargs: dict[str, Any] = {"pool_pre_ping": True}
if DATABASE_URL.startswith("sqlite"):
    engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    engine_kwargs.update({"pool_size": 3, "max_overflow": 2, "pool_recycle": 300})

engine = create_engine(DATABASE_URL, **engine_kwargs)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
passwords = CryptContext(schemes=["bcrypt"], deprecated="auto")
SESSION_COOKIE = "trading_arena_session"
SESSION_DAYS = int(os.getenv("SESSION_DAYS", "14"))
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "true" if os.getenv("VERCEL") else "false").lower() == "true"


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    workspace: Mapped["Workspace | None"] = relationship(back_populates="user", cascade="all, delete-orphan")


class LoginSession(Base):
    __tablename__ = "login_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Workspace(Base):
    __tablename__ = "workspaces"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    user: Mapped[User] = relationship(back_populates="workspace")


class DatasetRecord(Base):
    __tablename__ = "dataset_records"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    dataset_type: Mapped[str] = mapped_column(String(80), index=True)
    external_key: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class RegisterInput(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginInput(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class WorkspaceInput(BaseModel):
    data: dict[str, Any]


class DatasetInput(BaseModel):
    dataset_type: str = Field(min_length=1, max_length=80)
    external_key: str | None = Field(default=None, max_length=160)
    payload: dict[str, Any]


def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def public_user(user: User) -> dict[str, str]:
    return {"id": user.id, "name": user.name, "email": user.email}


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_session(response: Response, db: Session, user: User) -> None:
    raw = secrets.token_urlsafe(48)
    db.add(LoginSession(
        token_hash=hash_token(raw),
        user_id=user.id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS),
    ))
    db.commit()
    response.set_cookie(
        SESSION_COOKIE,
        raw,
        max_age=SESSION_DAYS * 86400,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="strict",
        path="/",
    )


def current_user(request: Request, db: Session = Depends(db_session)) -> User:
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        raise HTTPException(status_code=401, detail="Please sign in.")
    login_session = db.get(LoginSession, hash_token(raw))
    now = datetime.now(timezone.utc)
    if not login_session:
        raise HTTPException(status_code=401, detail="Session is invalid.")
    expires = login_session.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires <= now:
        db.delete(login_session)
        db.commit()
        raise HTTPException(status_code=401, detail="Session has expired.")
    user = db.get(User, login_session.user_id)
    if not user:
        raise HTTPException(status_code=401, detail="Account no longer exists.")
    return user


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)
    yield


app = FastAPI(title="Trading Arena SaaS", version="3.0", lifespan=lifespan)


@app.exception_handler(Exception)
async def unexpected_error(_: Request, exc: Exception):
    print(f"Unhandled error: {exc!r}")
    return JSONResponse(status_code=500, content={"detail": "Unexpected server error."})


@app.get("/api/health")
def health():
    return {"status": "ok", "database": "configured"}


@app.post("/api/auth/register")
def register(payload: RegisterInput, response: Response, db: Session = Depends(db_session)):
    email = payload.email.lower().strip()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=409, detail="An account with this email already exists.")
    user = User(
        id=str(uuid.uuid4()),
        name=payload.name.strip(),
        email=email,
        password_hash=passwords.hash(payload.password),
    )
    db.add(user)
    db.add(Workspace(user_id=user.id, data={}))
    db.commit()
    db.refresh(user)
    issue_session(response, db, user)
    return {"user": public_user(user)}


@app.post("/api/auth/login")
def login(payload: LoginInput, response: Response, db: Session = Depends(db_session)):
    email = payload.email.lower().strip()
    user = db.scalar(select(User).where(User.email == email))
    if not user or not passwords.verify(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    issue_session(response, db, user)
    return {"user": public_user(user)}


@app.get("/api/auth/me")
def me(user: User = Depends(current_user)):
    return {"user": public_user(user)}


@app.post("/api/auth/logout")
def logout(request: Request, response: Response, db: Session = Depends(db_session)):
    raw = request.cookies.get(SESSION_COOKIE)
    if raw:
        login_session = db.get(LoginSession, hash_token(raw))
        if login_session:
            db.delete(login_session)
            db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@app.get("/api/workspace")
def get_workspace(user: User = Depends(current_user), db: Session = Depends(db_session)):
    workspace = db.get(Workspace, user.id)
    return {"data": workspace.data if workspace else {}, "updated_at": workspace.updated_at if workspace else None}


@app.put("/api/workspace")
def put_workspace(payload: WorkspaceInput, user: User = Depends(current_user), db: Session = Depends(db_session)):
    workspace = db.get(Workspace, user.id)
    if not workspace:
        workspace = Workspace(user_id=user.id, data=payload.data)
        db.add(workspace)
    else:
        workspace.data = payload.data
        workspace.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True, "updated_at": workspace.updated_at}


@app.post("/api/workspace/beacon")
async def workspace_beacon(request: Request, user: User = Depends(current_user), db: Session = Depends(db_session)):
    payload = WorkspaceInput.model_validate(await request.json())
    workspace = db.get(Workspace, user.id)
    if not workspace:
        db.add(Workspace(user_id=user.id, data=payload.data))
    else:
        workspace.data = payload.data
        workspace.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True}


@app.get("/api/datasets")
def list_datasets(
    dataset_type: str | None = None,
    limit: int = 100,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    query = select(DatasetRecord).where(DatasetRecord.user_id == user.id)
    if dataset_type:
        query = query.where(DatasetRecord.dataset_type == dataset_type)
    records = db.scalars(query.order_by(DatasetRecord.created_at.desc()).limit(min(limit, 500))).all()
    return {"items": [
        {
            "id": record.id,
            "dataset_type": record.dataset_type,
            "external_key": record.external_key,
            "payload": record.payload,
            "created_at": record.created_at,
        }
        for record in records
    ]}


@app.post("/api/datasets", status_code=201)
def create_dataset(
    payload: DatasetInput,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    record = DatasetRecord(
        id=str(uuid.uuid4()),
        user_id=user.id,
        dataset_type=payload.dataset_type,
        external_key=payload.external_key,
        payload=payload.payload,
    )
    db.add(record)
    db.commit()
    return {"id": record.id, "created_at": record.created_at}


app.mount("/", StaticFiles(directory=ROOT / "public", html=True), name="frontend")
