"""测试基座：独立测试库 ccdev_test，每个用例前清库重播种子。"""
import os

os.environ["DATABASE_URL"] = "postgresql+psycopg2://ccdev:ccdev@127.0.0.1:5432/ccdev_test"
os.environ["AUTO_CREATE_TABLES"] = "0"

import psycopg2
import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from app.db import Base, SessionLocal, engine
from app.main import app
from app.seed import seed


def _ensure_test_db():
    conn = psycopg2.connect(host="127.0.0.1", port=5432, user="ccdev",
                            password="ccdev", dbname="ccdev")
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("select 1 from pg_database where datname = 'ccdev_test'")
    if cur.fetchone() is None:
        cur.execute("create database ccdev_test")
    conn.close()


_ensure_test_db()
Base.metadata.create_all(engine)


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def fresh_db():
    db = SessionLocal()
    try:
        for table in reversed(Base.metadata.sorted_tables):
            db.execute(sa.text(f'TRUNCATE TABLE "{table.name}" RESTART IDENTITY CASCADE'))
        db.commit()
        seed(db)
    finally:
        db.close()
    yield


def login(client: TestClient, username: str, password: str) -> dict:
    resp = client.post("/api/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['token']}"}
