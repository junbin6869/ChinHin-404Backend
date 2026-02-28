from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Literal

from app.core.auth import create_token

router = APIRouter()

Role = Literal["promotion", "procurement", "document", "admin"]

class LoginRequest(BaseModel):
    role: Role
    password: str

class LoginResponse(BaseModel):
    token: str
    role: Role

@router.post("/login", response_model=LoginResponse)
def login(req: LoginRequest):
    if req.password != "123456":
        raise HTTPException(status_code=401, detail="Invalid password")

    token = create_token(req.role)
    return LoginResponse(token=token, role=req.role)