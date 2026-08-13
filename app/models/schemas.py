from pydantic import BaseModel


class ChatRequest(BaseModel):
    question: str
    session_id: str | None = None
    agent_id: int | None = None


class ApiKeyCreate(BaseModel):
    label: str


class AgentCreate(BaseModel):
    name: str
    system_prompt: str
    greeting: str = ""


class AgentUpdate(BaseModel):
    name: str
    system_prompt: str
    greeting: str = ""
