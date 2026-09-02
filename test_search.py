from app.services.vector_store import search_similar_chunks, normalize_query
from app.services.embeddings import generate_embedding

q = "pakistan ne total kitni test series kheli"
nq = normalize_query(q)
print(f"Normalized query: {nq}")

emb = generate_embedding(nq)
print(f"Embedding dim: {len(emb)}")

for agent_id in [1, 14, 65]:
    chunks, ok = search_similar_chunks(emb, top_k=5, agent_id=agent_id, query_text=nq)
    print(f"\nAgent {agent_id}: {len(chunks)} chunks, available={ok}")
    for i, c in enumerate(chunks):
        score = c["score"]
        text = c["text"][:150]
        print(f"  [{i}] score={score:.4f} text={text}...")
