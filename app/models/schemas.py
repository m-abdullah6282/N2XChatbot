from pydantic import BaseModel


class ChatRequest(BaseModel):
    question: str
    session_id: str | None = None
    agent_id: int | None = None


class ApiKeyCreate(BaseModel):
    label: str


class AgentCreate(BaseModel):
    name: str
    description: str = ""
    greeting: str = ""
    slug: str = ""
    # Advanced: optional full custom prompt. Empty -> auto-built from the
    # universal template + name/description.
    system_prompt: str = ""


class AgentUpdate(BaseModel):
    name: str
    description: str = ""
    greeting: str = ""
    slug: str = ""
    system_prompt: str = ""


class HandoffReply(BaseModel):
    message: str


class AdminUserCreate(BaseModel):
    username: str
    password: str
    role: str = "admin"


class AdminPasswordChange(BaseModel):
    password: str
