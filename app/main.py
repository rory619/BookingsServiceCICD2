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

#Replacing @app.on_event("startup")
@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine) 
    yield

app = FastAPI(lifespan=lifespan)
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