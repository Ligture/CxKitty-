"""
CxKitty 服务端主入口

FastAPI + Socket.IO (ASGI) 多会话架构

启动:
    python -m server.main
    或
    uvicorn server.main:socket_app --host 0.0.0.0 --port 5000 --reload

开发模式 (Vite 前端热更新):
    前端: cd web && npm run dev  (端口 5173, 自动代理 /api 到 5000)
    后端: uvicorn server.main:socket_app --host 0.0.0.0 --port 5000 --reload

生产模式:
    cd web && npm run build
    python -m server.main  (自动在 /web/dist/ 中查找静态文件)
"""

import asyncio
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# 确保项目根目录在 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import socketio as sio_lib  # noqa: E402


# ---------------------------------------------------------------
# 生命周期 — 捕获主事件循环供工作线程使用
# ---------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    from server.services.callback_factory import set_event_loop
    loop = asyncio.get_running_loop()
    set_event_loop(loop)
    yield


# ---------------------------------------------------------------
# 创建应用
# ---------------------------------------------------------------

app = FastAPI(
    title="CxKitty Server",
    version="2.0.0",
    description="超星学习通多会话 WebUI 后端",
    lifespan=lifespan,
)

# CORS — 允许所有来源 (本地工具)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------
# 路由注册
# ---------------------------------------------------------------

from server.routers.auth import router as auth_router          # noqa: E402
from server.routers.courses import router as courses_router    # noqa: E402
from server.routers.tasks import router as tasks_router        # noqa: E402
from server.routers.config_router import router as config_router  # noqa: E402
from server.routers.sessions import router as sessions_router  # noqa: E402
from server.routers.logs import router as logs_router          # noqa: E402

app.include_router(auth_router)
app.include_router(courses_router)
app.include_router(tasks_router)
app.include_router(config_router)
app.include_router(sessions_router)
app.include_router(logs_router)


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "2.0.0"}


# ---------------------------------------------------------------
# Socket.IO 集成
# ---------------------------------------------------------------

from server.websocket import sio  # noqa: E402

# 将 sio 存入 app.state 供 routers 访问
app.state.sio = sio

# 创建 Socket.IO ASGI 应用 (包装 FastAPI)
socket_app = sio_lib.ASGIApp(sio, other_asgi_app=app)


# ---------------------------------------------------------------
# 静态文件 (生产模式)
# ---------------------------------------------------------------

WEB_DIST = PROJECT_ROOT / "web" / "dist"
if WEB_DIST.is_dir():
    from starlette.responses import Response

    # 挂载 assets 目录 (必须在 catch-all 之前)
    assets_dir = WEB_DIST / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """SPA fallback: 非 API 路径返回 index.html 让 React Router 处理"""
        file_path = WEB_DIST / full_path
        if file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(WEB_DIST / "index.html")


# ---------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------

def main():
    import uvicorn
    import dotenv
    dotenv.load_dotenv(dotenv.find_dotenv()) 
    host = os.environ.get("CXKITTY_HOST", "0.0.0.0")
    port = int(os.environ.get("CXKITTY_PORT", "5000"))
    reload = os.environ.get("CXKITTY_DEV", "").lower() in ("1", "true", "yes")

    print("=" * 60)
    print("  CxKitty WebUI v2.0.0")
    print("  超星学习通答题姬 - 多会话 Web 控制台")
    print(f"  http://{host}:{port}")
    if WEB_DIST.is_dir():
        print(f"  静态文件: {WEB_DIST}")
    else:
        print("  (开发模式 - 请使用 Vite 前端)")
    print("=" * 60)

    uvicorn.run(
        "server.main:socket_app",
        host=host,
        port=port,
        reload=reload,
    )


if __name__ == "__main__":
    main()
