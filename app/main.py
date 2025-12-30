from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.database import engine
from app.models import Base

from fastapi import Depends, HTTPException, status, Response 
from sqlalchemy.orm import Session 
from sqlalchemy import select 
from sqlalchemy.exc import IntegrityError 
from sqlalchemy.orm import selectinload 
from app.database import SessionLocal 
from app.models import BookingDB
from app.schemas import ( BookingCreate, BookingRead ) 
import httpx, os
import json
import aio_pika

#Replacing @app.on_event("startup")
@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine) 
    yield

app = FastAPI(title="Service B - Proxy API")
SERVICE_A_BASE_URL = os.getenv("SERVICE_A_BASE_URL", "http://localhost:8001")
EXCHANGE_NAME = "events_topic"
RABBIT_URL = os.getenv("RABBIT_URL")







# CORS (add this block)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # dev-friendly; tighten in prod
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine),

def get_db(): 
    db = SessionLocal() 
    try: 
        yield db 
    finally: 
        db.close() 
 
def commit_or_rollback(db: Session, error_msg: str): 
    try: 
        db.commit() 
    except IntegrityError: 
        db.rollback() 
        raise HTTPException(status_code=409, detail=error_msg) 
 
@app.get("/health") 
def health(): 
    return {"status": "ok"} 

@app.get("/api/proxy-greet")
def call_service_a(name: str = "world"):
    url = f"{SERVICE_A_BASE_URL}/api/greet/{name}"
    with httpx.Client() as client:
        r = client.get(url)
    return {"service_b": True, "service_a_response": r.json()}

@app.post("/order")
async def publish_order(order: dict):
    connection = await aio_pika.connect_robust(RABBIT_URL)
    channel = await connection.channel()

    message = aio_pika.Message(body=json.dumps(order).encode())

    await channel.default_exchange.publish(
        message,
        routing_key="orders_queue"
    )

    await connection.close()

    return {"status": "Message sent", "order": order}

async def get_exchange():
    conn = await aio_pika.connect_robust(RABBIT_URL)
    ch = await conn.channel()
    ex = await ch.declare_exchange(EXCHANGE_NAME, aio_pika.ExchangeType.TOPIC)
    return conn, ch, ex

@app.post("/order/create")
async def order_created(order: dict):
    conn, ch, ex = await get_exchange()
    msg = aio_pika.Message(body=json.dumps(order).encode())

    await ex.publish(msg, routing_key="order.created")
    await conn.close()

    return {"event": "order.created", "order": order}

@app.post("/payment/success")
async def payment_success(payment: dict):
    conn, ch, ex = await get_exchange()
    msg = aio_pika.Message(body=json.dumps(payment).encode())

    await ex.publish(msg, routing_key="payment.success")
    await conn.close()

    return {"event": "payment.success", "payment": payment}
 
#Bookings
@app.post("/api/bookings", response_model=BookingRead, status_code=201, summary="Create new booking") 
def create_booking(payload: BookingCreate, db: Session = Depends(get_db)): 
    db_book = BookingDB(**payload.model_dump()) 
    db.add(db_book) 
    commit_or_rollback(db, "Booking create failed") 
    db.refresh(db_book) 
    return db_book 
 
@app.get("/api/bookings", response_model=list[BookingRead]) 
def list_bookings(limit: int = 10, offset: int = 0, db: Session = Depends(get_db)): 
    stmt = select(BookingDB).order_by(BookingDB.id).limit(limit).offset(offset) 
    return db.execute(stmt).scalars().all() 
 

@app.get(
    "/api/bookings/{booking_id}",response_model=BookingRead,summary="Get a single booking",)
def get_booking(booking_id: int,db: Session = Depends(get_db),):
    book = db.get(BookingDB, booking_id)
    if not book:
        raise HTTPException(status_code=404, detail="Booking not found")
    return book

@app.put(
    "/api/bookings/{booking_id}",response_model=BookingRead,summary="Update an existing booking",)
def update_booking(booking_id: int,payload: BookingCreate,db: Session = Depends(get_db),):
    book = db.get(BookingDB, booking_id)
    if not book:
        raise HTTPException(status_code=404, detail="booking not found")

    book.user_id = payload.user_id
    book.course_id = payload.course_id
    book.status = payload.status

    commit_or_rollback(db, "booking update failed")
    db.refresh(book)
    return book

@app.delete("/api/bookings/{booking_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_booking(booking_id: int,db: Session = Depends(get_db),) -> Response:
    book = db.get(BookingDB, booking_id)
    if not book:
        raise HTTPException(status_code=404, detail="Booking not found")
    db.delete(book)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)