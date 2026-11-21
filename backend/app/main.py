"""FastAPI 应用入口。启动时自动建表；数据库为空时注入演示种子数据。"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .db import Base, engine
from .routers import access, audit, auth, catalog, projects, qualifications, quality, quota


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.AUTO_CREATE_TABLES:
        Base.metadata.create_all(engine)
    # 空库自动注入演示数据（幂等：已有用户则跳过）
    from .db import SessionLocal
    from .models import User
    from .seed import seed

    db = SessionLocal()
    try:
        if db.query(User).count() == 0:
            seed(db)
    finally:
        db.close()
    yield


app = FastAPI(
    title="科研数据产品目录与项目资格开通工作台",
    description=(
        "面向医学研究中心的数据产品目录、课题资格编译开通、额度账本与审计回查系统。\n\n"
        "核心能力：字段级求交（产品字段 × 用途条件 × 成员范围 × 伦理约束）、"
        "按（项目×产品×用途）隔离的资格实例、并发额度占用与幂等扣减、访问依据快照回查。"
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(catalog.router)
app.include_router(projects.router)
app.include_router(qualifications.router)
app.include_router(access.router)
app.include_router(quota.router)
app.include_router(audit.router)
app.include_router(quality.router)


@app.get("/api/health", tags=["系统"])
def health():
    return {"status": "ok"}
