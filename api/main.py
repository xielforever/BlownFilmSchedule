"""
APS 排程系统 — FastAPI 应用入口

启动: uvicorn api.main:app --reload --port 8000
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.security import OAuth2PasswordRequestForm

from api.auth import (
    USERS_DB, verify_password, create_access_token,
    Token, get_current_user
)
from api.routers import dashboard, schedule, orders, machines, rules

app = FastAPI(title="医疗PE薄膜 APS 排程系统", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Auth ───
@app.post("/api/auth/login", response_model=Token)
async def login(form: OAuth2PasswordRequestForm = Depends()):
    user = USERS_DB.get(form.username)
    if not user or not verify_password(form.password, user["password"]):
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    token = create_access_token({"sub": form.username, "role": user["role"]})
    return Token(access_token=token, role=user["role"], name=user["name"])


@app.get("/api/auth/me")
async def get_me(user=Depends(get_current_user)):
    info = USERS_DB.get(user.username, {})
    return {"username": user.username, "role": user.role, "name": info.get("name", "")}


# ─── Routers ───
app.include_router(dashboard.router)
app.include_router(schedule.router)
app.include_router(orders.router)
app.include_router(machines.router)
app.include_router(rules.router)

# ─── 静态文件（前端构建产物） ───
web_dist = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web", "dist")
if os.path.isdir(web_dist):
    app.mount("/", StaticFiles(directory=web_dist, html=True), name="web")
