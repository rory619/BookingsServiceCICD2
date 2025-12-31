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
import logging
import pybreaker

#Replacing @app.on_event("startup")
@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine) 
    yield

app = FastAPI(title="Service B - Proxy API")
SERVICE_A_BASE_URL = os.getenv("SERVICE_A_BASE_URL", "http://users:8000")
EXCHANGE_NAME = "events_topic"
RABBIT_URL = os.getenv("RABBIT_URL")

logger = logging.getLogger("bookings")
logging.basicConfig(level=logging.INFO, force=True)

#  opens after 3 failures tries again after 30s
USERS_CB = pybreaker.CircuitBreaker(fail_max=3, reset_timeout=30)

USERS_TIMEOUT = float(os.getenv("USERS_TIMEOUT", "2.0"))

@USERS_CB
def users_service_user_exists(user_id: int) -> bool:

    url = f"{SERVICE_A_BASE_URL}/api/users/{user_id}"

    with httpx.Client(timeout=USERS_TIMEOUT) as client:
        r = client.get(url)

    if r.status_code == 404:
        return False

    r.raise_for_status()
    return True


def check_user_with_circuit_breaker(user_id: int) -> tuple[bool | None, str]:
    try:
        return users_service_user_exists(user_id), "checked"

    except pybreaker.CircuitBreakerError:
        logger.warning("Users circuit breaker OPEN  skipping user check")
        return None, "skipped_circuit_open"

    except Exception as e:
        logger.warning(f"Users check failed  using fallback, error={type(e).__name__}")
        return None, "skipped_users_down"





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
    exists, note = check_user_with_circuit_breaker(payload.user_id)
    #  404
    if exists is False:
        raise HTTPException(status_code=404, detail="User not found (validated via Users service)")
    booking_status = payload.status
    if exists is None:
        booking_status = "pending_user_check"

    db_book = BookingDB(
        user_id=payload.user_id,
        course_id=payload.course_id,
        status=booking_status,
    )

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