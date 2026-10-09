# app/main.py 改完后的完整代码

import os
import uuid
import json
from fastapi import FastAPI, File, UploadFile, Depends
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from . import schemas, service, models
from .database import engine, get_db

models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="AI Knowledge Base API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = "./uploaded_files"
os.makedirs(UPLOAD_DIR, exist_ok=True)
@app.get("/")
async def root():
    return {"msg": "service ok"}
# 👇 上传接口：去掉 async，改为 def
@app.post("/api/v1/knowledge-bases/{kb_id}/knowledge/file", response_model=schemas.KnowledgeResponse, status_code=202)
def upload_knowledge_file(kb_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    file_ext = os.path.splitext(file.filename)[1]
    unique_filename = f"{uuid.uuid4()}{file_ext}"
    file_path = os.path.join(UPLOAD_DIR, unique_filename)
    with open(file_path, "wb") as buffer:
        buffer.write(file.file.read())  # 注意：def 里读文件不需要 await

    result = service.create_knowledge_from_file(db, file.filename, file_path)
    return result

# 👇 流式问答接口：去掉 async，改为 def
@app.post("/api/v1/chat/stream")
def chat_stream(request: schemas.ChatRequest, db: Session = Depends(get_db)):
    return StreamingResponse(
        service.chat_stream_with_knowledge_base(db, request.query, request.history),
        media_type="text/event-stream"
    )

# 👇 LobeChat 兼容接口：去掉 async，改为 def
@app.post("/v1/chat/completions")
def openai_compatible_chat(request: dict, db: Session = Depends(get_db)):
    messages = request.get("messages", [])
    query = messages[-1]["content"] if messages else "你好"
    history = messages[:-1] if len(messages) > 1 else []

    def event_stream():
        for chunk in service.chat_stream_with_knowledge_base(db, query, history):
            if chunk.startswith("data: "):
                data_content = chunk[6:].strip()
                if data_content == "[DONE]":
                    break
                try:
                    obj = json.loads(data_content)
                    if "sources" in obj:
                        source_text = "\n\n📚 参考来源：\n" + "\n".join([f"  [{s['index']}] {s['file_name']}" for s in obj["sources"]])
                        payload = {"choices": [{"delta": {"content": source_text}}]}
                        yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                except:
                    payload = {"choices": [{"delta": {"content": data_content}}]}
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")

# ==================== 文件管理接口 ====================

# 1. 获取知识库文件列表
@app.get("/api/v1/knowledge-bases/{kb_id}/knowledge")
def list_knowledge_files(kb_id: int, db: Session = Depends(get_db)):
    files = db.query(models.Knowledge).order_by(models.Knowledge.id.desc()).all()
    return [{"id": f.id, "file_name": f.file_name, "parse_status": f.parse_status, "created_at": f.created_at} for f in files]

# 2. 查询单个文件状态（用于前端轮询）
@app.get("/api/v1/knowledge/{knowledge_id}/status")
def get_knowledge_status(knowledge_id: int, db: Session = Depends(get_db)):
    knowledge = db.query(models.Knowledge).filter(models.Knowledge.id == knowledge_id).first()
    if not knowledge:
        return {"error": "文件不存在"}
    return {"id": knowledge.id, "parse_status": knowledge.parse_status}

# 3. 删除文件（同时删除关联的切片）
@app.delete("/api/v1/knowledge/{knowledge_id}")
def delete_knowledge(knowledge_id: int, db: Session = Depends(get_db)):
    # 先删 chunks 表中的关联数据
    db.query(models.Chunk).filter(models.Chunk.knowledge_id == knowledge_id).delete()
    # 再删 knowledge 表中的主记录
    knowledge = db.query(models.Knowledge).filter(models.Knowledge.id == knowledge_id).first()
    if knowledge:
        db.delete(knowledge)
        db.commit()
        return {"message": "删除成功"}
    return {"error": "文件不存在"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)