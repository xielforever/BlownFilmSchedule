"""
APS 排程系统 — 认证与权限模块

JWT Token 认证，角色: admin(厂长) / planner(计划员) / viewer(只读)
"""
from __future__ import annotations
import os
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from pydantic import BaseModel
import hashlib

SECRET_KEY = os.getenv("APS_SECRET_KEY", "aps-blown-film-secret-2026")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 480  # 8 小时

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def _hash_pw(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()


# 内置用户（生产环境应改为数据库存储）
USERS_DB = {
    "admin":   {"password": _hash_pw("admin123"),   "role": "admin",   "name": "系统管理员"},
    "planner": {"password": _hash_pw("planner123"), "role": "planner", "name": "排程计划员"},
    "viewer":  {"password": _hash_pw("viewer123"),  "role": "viewer",  "name": "只读查看员"},
}


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    name: str


class TokenData(BaseModel):
    username: str
    role: str


def verify_password(plain: str, hashed: str) -> bool:
    return _hash_pw(plain) == hashed


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


async def get_current_user(token: str = Depends(oauth2_scheme)) -> TokenData:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="认证失败",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        role: str = payload.get("role", "viewer")
        if username is None:
            raise credentials_exception
        return TokenData(username=username, role=role)
    except JWTError:
        raise credentials_exception


def require_role(*allowed_roles):
    """角色权限装饰器"""
    async def role_checker(user: TokenData = Depends(get_current_user)):
        if user.role not in allowed_roles:
            raise HTTPException(status_code=403, detail="权限不足")
        return user
    return role_checker
