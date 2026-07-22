"""RAG检索引擎 — 基于ChromaDB的SOP知识库检索"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import CHROMA_DIR, SOP_DIR


def init_chroma():
    """初始化ChromaDB并导入SOP知识库"""
    import chromadb
    from chromadb.config import Settings

    os.makedirs(CHROMA_DIR, exist_ok=True)
    client = chromadb.PersistentClient(path=CHROMA_DIR)
    collection = client.get_or_create_collection(name="sop_knowledge")

    # 如果知识库为空，导入文档
    if collection.count() == 0:
        _import_sop_docs(collection)

    return collection


def _import_sop_docs(collection):
    """将SOP markdown文件导入ChromaDB"""
    doc_id = 0
    if not os.path.exists(SOP_DIR):
        print(f"警告：SOP知识库目录不存在: {SOP_DIR}")
        return

    for filename in sorted(os.listdir(SOP_DIR)):
        if not filename.endswith(".md"):
            continue
        filepath = os.path.join(SOP_DIR, filename)
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        # 按Q分割为独立文档块
        sections = content.split("## Q")
        for section in sections[1:]:  # 跳过标题
            full_section = "## Q" + section
            # 提取问题标题作为元数据
            title_line = section.split("\n")[0].strip()
            collection.add(
                documents=[full_section],
                metadatas=[{"source": filename, "title": title_line}],
                ids=[f"sop_{doc_id}"]
            )
            doc_id += 1

    print(f"SOP知识库导入完成，共 {doc_id} 条文档")


def search_sop(query: str, collection, n_results: int = 3) -> list[dict]:
    """检索最相关的SOP条目"""
    results = collection.query(
        query_texts=[query],
        n_results=n_results
    )
    sop_entries = []
    if results["documents"] and len(results["documents"]) > 0:
        for i in range(len(results["documents"][0])):
            sop_entries.append({
                "content": results["documents"][0][i],
                "source": results["metadatas"][0][i]["source"],
                "title": results["metadatas"][0][i]["title"],
                "distance": results["distances"][0][i],
            })
    return sop_entries
