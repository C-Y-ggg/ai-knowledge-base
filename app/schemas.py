from pydantic import BaseModel
from datetime import datetime
from typing import List, Optional

class KnowledgeResponse(BaseModel):
    id: int
    file_name: str
    parse_status: str
    created_at: datetime

    class Config:
        from_attributes = True

# 👇 更新后的 ChatRequest
class ChatRequest(BaseModel):
    query: str
    conversation_id: Optional[int] = None # 如果是新对话，不传此字段
    kb_id: int = 1

# 👇 新增：会话相关 Schema
class ConversationResponse(BaseModel):
    id: int
    title: str
    created_at: datetime
    class Config:
        from_attributes = True

class MessageResponse(BaseModel):
    id: int
    role: str
    content: str
    created_at: datetime
    class Config:
        from_attributes = True