from pydantic import BaseModel


class ChatRequest(BaseModel):
    question: str
    session_id: str | None = None
    agent_id: int | None = None


class ApiKeyCreate(BaseModel):
    label: str
    agent_id: int | None = None


class AgentCreate(BaseModel):
    name: str
    description: str = ""
    greeting: str = ""
    slug: str = ""
    # Advanced: optional full custom prompt. Empty -> auto-built from the
    # universal template + name/description.
    system_prompt: str = ""
    primary_color: str = "#2563EB"


class AgentUpdate(BaseModel):
    name: str
    description: str = ""
    greeting: str = ""
    slug: str = ""
    system_prompt: str = ""
    primary_color: str | None = None


class PlanUpdate(BaseModel):
    name: str
    price: float = 0
    max_ai_agents: int | None = None
    unlimited_ai_agents: bool = False
    max_support_agents: int | None = None
    unlimited_support_agents: bool = False
    max_documents: int | None = None
    unlimited_documents: bool = False
    max_messages_per_period: int | None = None
    unlimited_messages: bool = False
    is_active: bool = True


class HandoffReply(BaseModel):
    message: str


class AdminUserCreate(BaseModel):
    username: str
    password: str
    role: str = "admin"
    plan_id: int | None = None


class AdminPasswordChange(BaseModel):
    password: str
