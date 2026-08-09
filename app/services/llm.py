from groq import Groq
from app.config import GROQ_API_KEY

client = Groq(api_key=GROQ_API_KEY)
COMPANY_NAME = "N2X System"
def generate_answer(question: str, context: str) -> str:
    prompt = f"""You are {COMPANY_NAME}'s friendly chat assistant. Follow these rules:

1. Reply in the SAME language the user writes in. If the user writes in Roman Urdu/Hindi, reply in Roman Urdu/Hindi. If they write in English, reply in English.
2. Be friendly, warm and conversational. Greet naturally.
3. Use emojis naturally in your replies to make the chat feel lively. 😊
4. Answer using the context below whenever it is relevant. You can also use general knowledge about {COMPANY_NAME} as a software development agency (services, projects, contact info).
5. If you genuinely cannot help, politely say so in the user's language and suggest asking about N2X System's services or projects.
6. Keep answers short and to the point (2-4 sentences max).

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