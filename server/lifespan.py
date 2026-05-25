from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # 后续阶段在此挂载数据库连接、ownership 续约、background 任务等启停资源。
    yield
