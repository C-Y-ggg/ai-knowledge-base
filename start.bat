@echo off
echo ========================================
echo    正在启动 RAG 智能知识库系统...
echo ========================================

echo.
echo [1/3] 正在启动 FastAPI 后端服务 (端口 8026)...
start cmd /k "conda activate ai-dev && python -m uvicorn app.main:app --reload --port 8026"

echo.
echo [2/3] 正在启动后台异步 Worker...
start cmd /k "conda activate ai-dev && python worker.py"

echo.
echo [3/3] 正在启动桌面应用...
timeout /t 3 >nul
start cmd /k "conda activate ai-dev && python desktop_app.py"

echo.
echo ========================================
echo 所有服务已尝试启动！请检查各个窗口的日志。
echo ========================================
pause