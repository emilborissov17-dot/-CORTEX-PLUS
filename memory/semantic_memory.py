#!/usr/bin/env python3
"""
memory/semantic_memory.py
Семантична памет за CORTEX++ — запомня инсайти, търси по смисъл.
Използва ChromaDB + sentence embeddings.
"""
import json, pathlib, hashlib
from datetime import datetime, timezone
import chromadb

BASE_DIR = pathlib.Path(__file__).resolve().parents[1]
DB_PATH  = BASE_DIR / "memory" / "chromadb"

def _get_collection():
    client = chromadb.PersistentClient(path=str(DB_PATH))
    return client.get_or_create_collection(
        name="cortex_insights",
        metadata={"hnsw:space": "cosine"}
    )

def remember(text: str, axis: str = "GENERAL", source: str = "agent") -> str:
    """Запомни инсайт в семантичната памет."""
    col = _get_collection()
    doc_id = hashlib.md5(text.encode()).hexdigest()[:12]
    col.add(
        documents=[text],
        metadatas=[{
            "axis": axis,
            "source": source,
            "date": datetime.now(timezone.utc).isoformat()[:10],
        }],
        ids=[doc_id]
    )
    return doc_id

def query(question: str, n: int = 5, axis: str = None) -> list:
    """Намери семантично свързани спомени."""
    col = _get_collection()
    where = {"axis": axis} if axis else None
    try:
        results = col.query(
            query_texts=[question],
            n_results=min(n, col.count()),
            where=where
        )
        memories = []
        for doc, meta, dist in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0]
        ):
            memories.append({
                "text": doc,
                "axis": meta.get("axis"),
                "date": meta.get("date"),
                "relevance": round(1 - dist, 3)
            })
        return memories
    except Exception as e:
        return []

def remember_from_snapshot() -> int:
    """Зареди инсайти от master snapshot в семантичната памет."""
    master_path = BASE_DIR / "snapshots" / "master" / "master_snapshot_latest.json"
    master = json.loads(master_path.read_text(encoding="utf-8"))
    
    # Зареди auto levels
    levels_path = BASE_DIR / "memory" / "auto_levels.json"
    try:
        auto_levels = json.loads(levels_path.read_text(encoding="utf-8"))
    except:
        auto_levels = {}

    count = 0
    for axis, snap in master.get("snapshots", {}).items():
        # Метриките са вложени: snap.metrics.metrics
        top = snap.get("metrics", {})
        metrics = top.get("metrics", top) if isinstance(top, dict) else {}
        level = auto_levels.get(axis, {}).get("level") or snap.get("current_level", "?")
        numeric = {k: v for k, v in metrics.items() if isinstance(v, (int, float))}
        if numeric:
            metric_str = ", ".join(f"{k}={round(v,1)}" for k, v in list(numeric.items())[:4])
            insight = f"{axis} е на ниво {level}. Метрики: {metric_str}."
        else:
            insight = f"{axis} е на ниво {level}."
        remember(insight, axis=axis, source="snapshot")
        count += 1

    return count

def remember_from_news() -> int:
    """Зареди инсайти от news_latest.json в семантичната памет."""
    news_path = BASE_DIR / "news" / "news_latest.json"
    try:
        news = json.loads(news_path.read_text(encoding="utf-8"))
    except:
        return 0
    
    count = 0
    for axis, r in news.get("results", {}).items():
        summary = r.get("summary", "")
        urgency = r.get("urgency", "LOW")
        if summary and urgency in ("HIGH", "CRITICAL"):
            text = f"{axis} [{urgency}]: {summary}"
            remember(text, axis=axis, source="internet_agent")
            count += 1
    
    return count

def status() -> dict:
    col = _get_collection()
    return {"total_memories": col.count()}

if __name__ == "__main__":
    print("[SEMANTIC_MEMORY] Зареждам спомени от snapshot...")
    n1 = remember_from_snapshot()
    print(f"  → {n1} snapshot инсайта записани")
    
    print("[SEMANTIC_MEMORY] Зареждам спомени от новини...")
    n2 = remember_from_news()
    print(f"  → {n2} news инсайта записани")
    
    total = status()["total_memories"]
    print(f"[SEMANTIC_MEMORY] Общо в паметта: {total} спомена")
    
    print()
    print("[SEMANTIC_MEMORY] Тест — търся: енергиен преход")
    results = query("енергиен преход и климат")
    for r in results:
        print(f"  [{r['relevance']}] {r['text'][:100]}") 

class SemanticMemory:
    def query(self,question,n=5,axis=None):
        return query(question,n=n,axis=axis)
    def remember(self,text,axis="GENERAL",source="agent"):
        return remember(text,axis=axis,source=source)
    def status(self):
        return status()
