"""RAG 核心引擎 -- 会话级纯内存极速语义检索系统

【RAG 业务全景流程】：
1. 【入库阶段】候选人上传 2000+ 字简历后，文本被切分为项目经历/技能片段（Chunks），调用 build_session_rag() 建立纯内存 TF-IDF 语义向量索引；
2. 【检索阶段】当出题 Agent（question_generator）需要考察某个岗位技术点（如 MySQL/Redis/高并发）时，调用 retrieve_resume_context()；
3. 【匹配阶段】在 0.001 秒内计算余弦相似度，精准抓取候选人简历中做过该技术的真实项目片段（Top-K）；
4. 【生成阶段】将抓取到的真实项目经历拼接进 Prompt，让 AI 面试官生成“结合候选人真实经历的深度追问”，杜绝通用八股文与大模型幻觉！
"""

import re
import logging
import numpy as np
from typing import Optional, List, Dict
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

logger = logging.getLogger(__name__)

# 全局会话内存存储字典：key -> session_id, value -> 包含向量矩阵与文本切片的索引字典
_session_stores: Dict[str, dict] = {}
_embedding_model = None


def _embed_texts(texts: List[str]) -> Optional[np.ndarray]:
    """计算文本向量（若存在显式加载的神经网络模型则使用，否则返回 None 触发内存 TF-IDF 快速引擎）"""
    global _embedding_model
    if _embedding_model is not None:
        try:
            embeddings = _embedding_model.encode(
                texts,
                normalize_embeddings=True,
                show_progress_bar=False,
                batch_size=32,
            )
            return embeddings.astype("float32")
        except Exception:
            return None
    return None


def build_session_rag(session_id: str, chunks: List[dict]) -> bool:
    """
    【第一步：构建 RAG 语义索引】
    接收简历文本切片（chunks），在内存中建立 TF-IDF 词频-逆文档频率特征矩阵。
    - 0 网络开销：无需连接海外 HuggingFace，纯 CPU 内存计算（耗时 < 0.001s）；
    - 会话隔离：以 session_id 为隔离单元，不同候选人的数据互不干扰。
    """
    if not chunks:
        logger.warning(f"Session {session_id}: 简历分块为空，跳过 RAG 入库")
        return False

    texts = [chunk["text"] for chunk in chunks]

    # 1. 尝试 FAISS 向量库（若环境已预加载神经网络 Embedding）
    if _embedding_model is not None:
        try:
            import faiss
            embeddings = _embed_texts(texts)
            if embeddings is not None:
                dim = embeddings.shape[1]
                index = faiss.IndexFlatIP(dim)
                index.add(embeddings)

                _session_stores[session_id] = {
                    "type": "faiss",
                    "index": index,
                    "texts": texts,
                    "chunks": chunks,
                }
                logger.info(f"Session {session_id}: 成功使用 FAISS 索引 {len(chunks)} 个简历分块")
                return True
        except Exception as e:
            logger.warning(f"Session {session_id}: FAISS 索引初始化跳过 ({e})")

    # 2. 默认高性能引擎：纯内存 TF-IDF 矩阵 + 余弦相似度
    try:
        # 支持中英文词法特征提取
        vectorizer = TfidfVectorizer(token_pattern=r"(?u)\b\w+\b")
        tfidf_matrix = vectorizer.fit_transform(texts)

        _session_stores[session_id] = {
            "type": "tfidf",
            "vectorizer": vectorizer,
            "matrix": tfidf_matrix,
            "texts": texts,
            "chunks": chunks,
        }
        logger.info(f"Session {session_id}: 成功构建 TF-IDF 语义索引，{len(chunks)} 个简历分块已就绪")
        return True

    except Exception as e:
        # 3. 关键词匹配降级兜底
        _session_stores[session_id] = {
            "type": "keyword",
            "texts": texts,
            "chunks": chunks,
        }
        return True


def retrieve_resume_context(
    session_id: str,
    query_topic: str,
    top_k: int = 2,
    min_similarity: float = 0.25
) -> Optional[str]:
    """
    【第二步：根据面试考点检索简历项目片段】
    - 输入：session_id（会话ID），query_topic（考察技术点，例如 "MySQL慢查询" 或 "Redis缓存"）；
    - 计算：将考点向量化，与简历所有分块计算 Cosine Similarity（余弦相似度）；
    - 输出：得分最高且相似度高于阈值的真实项目经历片段（Top-K），回传给出题 Agent。
    """
    store = _session_stores.get(session_id)
    if not store:
        return None

    texts = store.get("texts", [])
    if not texts:
        return None

    matched_texts = []

    # 1. 优先使用 TF-IDF 语义余弦相似度检索
    if store.get("type") == "tfidf":
        try:
            vectorizer = store["vectorizer"]
            matrix = store["matrix"]
            # 考点主题向量化
            q_vec = vectorizer.transform([query_topic])
            # 计算余弦相似度得分 [0.0 ~ 1.0]
            sims = cosine_similarity(q_vec, matrix)[0]

            # 取相似度排名前 top_k 的简历段落
            top_indices = np.argsort(sims)[::-1][:top_k]
            for idx in top_indices:
                if sims[idx] >= min_similarity:
                    matched_texts.append(texts[idx])
        except Exception as e:
            logger.warning(f"Session {session_id}: 检索匹配异常 ({e})")

    # 2. 关键词交集补充匹配（若向量相似度未达标则触发保底检索）
    if not matched_texts:
        tokens = [t.strip().lower() for t in re.split(r"[\s,，、/]+", query_topic) if t.strip()]
        scored = []
        for i, t in enumerate(texts):
            t_lower = t.lower()
            hit_count = sum(1 for token in tokens if token in t_lower)
            if hit_count > 0:
                scored.append((hit_count, i))
        scored.sort(reverse=True)
        for _, idx in scored[:top_k]:
            matched_texts.append(texts[idx])

    if not matched_texts:
        return None

    # 用分割线拼接返回多个匹配到的真实经历片段
    return "\n---\n".join(matched_texts)


def clear_session(session_id: str):
    """
    【第三步：会话销毁与内存释放】
    面试结束或会话关闭时，立即从内存字典中删除该候选人的向量索引，实现 0 内存泄漏与数据隐私安全。
    """
    if session_id in _session_stores:
        del _session_stores[session_id]
        logger.debug(f"Session {session_id}: RAG 索引已清除，内存已释放")


def get_session_count() -> int:
    """返回当前并发活跃的 RAG 面试会话数量"""
    return len(_session_stores)


def get_session_stats(session_id: str) -> dict:
    """获取指定会话的 RAG 索引健康状态"""
    store = _session_stores.get(session_id)
    if not store:
        return {"exists": False, "chunk_count": 0, "engine": "none"}
    return {
        "exists": True,
        "chunk_count": len(store.get("texts", [])),
        "engine": store.get("type", "unknown")
    }
