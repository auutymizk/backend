from fastapi import FastAPI, Depends, HTTPException, status, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr
from datetime import timedelta
import os, logging

from database import engine, get_db, Base
import models
from auth import get_password_hash, verify_password, create_access_token, get_current_user, ACCESS_TOKEN_EXPIRE_MINUTES
from routers import users, bots, credits
from bot_engine import bot_manager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Hyper Trader Bot API",
    description="Auto Trading Bot for IQ Option",
    version="2.0.0",
)

_origins_env = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
ALLOWED_ORIGINS = [o.strip() for o in _origins_env.split(",")]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

os.makedirs("uploads/avatars", exist_ok=True)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

app.include_router(users.router, prefix="/api/users", tags=["Users"])
app.include_router(bots.router, prefix="/api/bots", tags=["Bots"])
app.include_router(credits.router, prefix="/api/credits", tags=["Credits"])


class RegisterRequest(BaseModel):
    username: str
    email: EmailStr
    password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


@app.post("/api/auth/register", status_code=201)
def register(data: RegisterRequest, db: Session = Depends(get_db)):
    if len(data.username) < 3 or len(data.username) > 20:
        raise HTTPException(status_code=400, detail="username: ต้องมี 3-20 ตัวอักษร")
    if not data.username.replace("_", "").isalnum():
        raise HTTPException(status_code=400, detail="username: ใช้ได้เฉพาะตัวอักษร ตัวเลข และ _")
    if len(data.password) < 8:
        raise HTTPException(status_code=400, detail="password: ต้องมีอย่างน้อย 8 ตัวอักษร")

    if db.query(models.User).filter(models.User.email == data.email.lower()).first():
        raise HTTPException(status_code=400, detail="email: อีเมลนี้ถูกใช้งานแล้ว")
    if db.query(models.User).filter(models.User.username == data.username).first():
        raise HTTPException(status_code=400, detail="username: ชื่อผู้ใช้นี้ถูกใช้งานแล้ว")

    user = models.User(
        username=data.username,
        email=data.email.lower(),
        hashed_password=get_password_hash(data.password),
        credits=0.0,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"message": "สมัครสมาชิกสำเร็จ", "user_id": user.id}


@app.post("/api/auth/login")
def login(data: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == data.email.lower()).first()
    if not user or not verify_password(data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="อีเมลหรือรหัสผ่านไม่ถูกต้อง",
        )
    if not user.is_active:
        raise HTTPException(status_code=400, detail="บัญชีนี้ถูกระงับการใช้งาน")

    token = create_access_token(
        data={"sub": str(user.id)},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    slots_count = db.query(models.BotSlot).filter(models.BotSlot.user_id == user.id).count()
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "profile_image": user.profile_image,
            "credits": user.credits,
            "password_changes_this_month": user.password_changes_this_month,
            "slots_count": slots_count,
            "created_at": user.created_at.isoformat(),
        }
    }


@app.websocket("/ws/bot/{slot_id}")
async def websocket_bot(
    websocket: WebSocket,
    slot_id: int,
    token: str = None,
    db: Session = Depends(get_db)
):
    from jose import jwt, JWTError
    from auth import SECRET_KEY, ALGORITHM

    await websocket.accept()

    if not token:
        await websocket.send_text('{"type":"error","message":"Unauthorized"}')
        await websocket.close()
        return

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload.get("sub"))
    except (JWTError, Exception):
        await websocket.send_text('{"type":"error","message":"Invalid token"}')
        await websocket.close()
        return

    slot = db.query(models.BotSlot).filter(
        models.BotSlot.id == slot_id,
        models.BotSlot.user_id == user_id
    ).first()
    if not slot:
        await websocket.send_text('{"type":"error","message":"Slot not found"}')
        await websocket.close()
        return

    bot_manager.register_ws(slot_id, websocket)
    try:
        while True:
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        bot_manager.unregister_ws(slot_id, websocket)


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "Hyper Trader Bot API v2.0"}


@app.get("/")
def root():
    return {"message": "Hyper Trader Bot API", "docs": "/docs"}
