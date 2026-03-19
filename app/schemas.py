from pydantic import BaseModel, EmailStr


class UserCreate(BaseModel):
    email: EmailStr
    login: str
    password: str