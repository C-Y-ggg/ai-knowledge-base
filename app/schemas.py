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

class ChatRequest(BaseModel):
    query: str
    history: Optional[List[dict]] = []  # 接收历史对话列表(记忆)