import random
import string
import json
import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime
from sqlalchemy.orm import sessionmaker, declarative_base
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ------------------- Настройки Mail.ru -------------------
MAIL_SERVER = 'smtp.mail.ru'
MAIL_PORT = 465
MAIL_USE_SSL = True
MAIL_USE_TLS = False
MAIL_USERNAME = 'sendcoder@mail.ru'      # твой email
MAIL_PASSWORD = '4RlinG8uZ0CTkkvkCpPg'  # пароль
MAIL_DEFAULT_SENDER = ('PingChat', MAIL_USERNAME)
MAIL_DEBUG = True

def send_code_email(to_email: str, code: str):
    subject = "PingChat: Код подтверждения"
    body = f"Ваш код подтверждения: {code}"

    msg = MIMEMultipart()
    msg['From'] = f"{MAIL_DEFAULT_SENDER[0]} <{MAIL_DEFAULT_SENDER[1]}>"
    msg['To'] = to_email
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))

    if MAIL_USE_SSL:
        server = smtplib.SMTP_SSL(MAIL_SERVER, MAIL_PORT)
    else:
        server = smtplib.SMTP(MAIL_SERVER, MAIL_PORT)
        if MAIL_USE_TLS:
            server.starttls()

    if MAIL_DEBUG:
        server.set_debuglevel(1)

    server.login(MAIL_USERNAME, MAIL_PASSWORD)
    server.send_message(msg)
    server.quit()

# ------------------- Сервер -------------------
app = FastAPI(title="PingChat Server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------- База данных -------------------
DATABASE_URL = "sqlite:///pingchat.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

class Message(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True, index=True)
    sender = Column(String(50))
    text = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(bind=engine)

# ------------------- Пользователи -------------------
users = {}  # email -> {password, code, verified}
clients = {}  # username -> websocket

# ------------------- Pydantic модели -------------------
class RegisterModel(BaseModel):
    email: str
    password: str

class VerifyModel(BaseModel):
    email: str
    code: str

# ------------------- Регистрация -------------------
@app.post("/register")
def register(user: RegisterModel):
    if user.email in users:
        raise HTTPException(status_code=400, detail="Email уже зарегистрирован")
    code = "".join(random.choices(string.digits, k=6))
    users[user.email] = {"password": user.password, "code": code, "verified": False}
    send_code_email(user.email, code)
    return {"success": True, "message": "Код подтверждения отправлен на email"}

# ------------------- Подтверждение кода -------------------
@app.post("/verify")
def verify_code(data: VerifyModel):
    user = users.get(data.email)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    if user["code"] == data.code:
        user["verified"] = True
        return {"success": True, "message": "Email подтверждён"}
    else:
        raise HTTPException(status_code=400, detail="Неверный код")

# ------------------- Логин -------------------
@app.post("/login")
def login(user: RegisterModel):
    db_user = users.get(user.email)
    if not db_user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    if not db_user["verified"]:
        raise HTTPException(status_code=400, detail="Email не подтверждён")
    if db_user["password"] != user.password:
        raise HTTPException(status_code=400, detail="Неверный пароль")
    return {"success": True, "message": "Успешный вход"}

# ------------------- WebSocket для чата -------------------
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        username = await websocket.receive_text()
        if username not in users or not users[username]["verified"]:
            await websocket.send_text(json.dumps({"sender":"system","text":"Доступ запрещён"}))
            return

        clients[username] = websocket

        # Отправляем всю историю сообщений
        db = SessionLocal()
        all_messages = db.query(Message).order_by(Message.timestamp).all()
        for msg in all_messages:
            await websocket.send_json({
                "sender": msg.sender,
                "text": msg.text,
                "timestamp": str(msg.timestamp)
            })

        # Основной цикл чата
        while True:
            data = await websocket.receive_json()
            sender = data.get("sender", username)
            text = data.get("text", "")

            # Сохраняем в базу
            new_msg = Message(sender=sender, text=text)
            db.add(new_msg)
            db.commit()

            # Рассылаем всем подключенным клиентам
            for user, conn in clients.items():
                try:
                    await conn.send_json({
                        "sender": sender,
                        "text": text,
                        "timestamp": str(new_msg.timestamp)
                    })
                except:
                    continue

    except WebSocketDisconnect:
        if username in clients:
            del clients[username]
