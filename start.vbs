Set sh = CreateObject("WScript.Shell")

' [1/3] FastAPI 后端 —— 完全隐藏窗口，日志写入 server.log
sh.Run "cmd /c conda activate ai-dev ^&^& python -m uvicorn app.main:app --reload --port 8026 >> server.log 2^>&1", 0, False

' [2/3] 后台 Worker —— 完全隐藏窗口，日志写入 worker.log
sh.Run "cmd /c conda activate ai-dev ^&^& python worker.py >> worker.log 2^>&1", 0, False

' [3/3] 桌面应用 —— 延迟 3 秒等后端起来，保留这一个可见窗口方便看报错
WScript.Sleep 3000
sh.Run "cmd /k conda activate ai-dev ^&^& python desktop_app.py", 1, False