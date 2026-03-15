from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from pathlib import Path
from database import init_db
from routers import skills_router, workflows_router, agent_router, executions_router
from routers.logs import router as logs_router, setup_log_handler, sys_ready

# 确保 outputs 和 uploads 目录存在
OUTPUTS_DIR = Path(__file__).parent / "outputs"
OUTPUTS_DIR.mkdir(exist_ok=True)
UPLOADS_DIR = Path(__file__).parent / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    init_db()
    setup_log_handler()
    sys_ready()
    yield
    pass


app = FastAPI(
    title="Product Background API",
    description="Backend API for AI Skills Platform - supports skill management, workflow management, and AI agent chat",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(skills_router)
app.include_router(workflows_router)
app.include_router(agent_router)
app.include_router(executions_router)
app.include_router(logs_router)

# 静态文件服务 - 输出文件下载
app.mount("/outputs", StaticFiles(directory=str(OUTPUTS_DIR)), name="outputs")
# 静态文件服务 - 上传文件访问
app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")


@app.get("/")
async def root():
    return {"message": "Product Background API is running"}


@app.get("/health")
async def health_check():
    return {"status": "healthy"}
