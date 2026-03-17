import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime
from sqlalchemy.orm import sessionmaker, declarative_base
from datetime import datetime

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

app = FastAPI(title="PingChat Server")

clients = {}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        username = await websocket.receive_text()
        clients[username] = websocket

        db = SessionLocal()
        all_messages = db.query(Message).order_by(Message.timestamp).all()
        for msg in all_messages:
            await websocket.send_json({
                "sender": msg.sender,
                "text": msg.text,
                "timestamp": str(msg.timestamp)
            })

        while True:
            data = await websocket.receive_json()
            sender = data.get("sender", username)
            text = data.get("text", "")

            new_msg = Message(sender=sender, text=text)
            db.add(new_msg)
            db.commit()

            for user, conn in clients.items():
                if conn != websocket:
                    try:
                        await conn.send_json({
                            "sender": sender,
                            "text": text,
                            "timestamp": str(new_msg.timestamp)
                        })
                    except:
                        continue
    except WebSocketDisconnect:
        del clients[username]

# Для запуска локально через uvicorn
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
