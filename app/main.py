from fastapi import FastAPI
from app.database import Base, engine
from app.routes import users

app = FastAPI(title="ShiftSync API")

Base.metadata.create_all(bind=engine)

app.include_router(users.router)


@app.get("/")
def root():
    return {"message": "ShiftSync API running"}