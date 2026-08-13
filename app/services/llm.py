from groq import Groq
from app.config import GROQ_API_KEY
from app.db import DEFAULT_SYSTEM_PROMPT

client = Groq(api_key=GROQ_API_KEY)

def generate_answer(question: str, context: str, system_prompt: str = DEFAULT_SYSTEM_PROMPT) -> str:
    prompt = f"""{system_prompt}

Context:
{context}

Question: {question}

Answer:"""

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7
    )

    return response.choices[0].message.content
