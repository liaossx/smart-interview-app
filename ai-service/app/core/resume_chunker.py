"""简历语义分块提取器 —— 将简历 analysis 结构化结果切成向量入库的 chunks

本模块接收 resume_analyzer_node 解析出的结构化简历数据（JSON），
将其按"项目经历"和"专业技能"两个维度切成独立的语义块（Chunks），
供 RAG 引擎向量化入库。

切块策略（已与用户确认）：
- 项目经历（project）：每个独立项目切为一个 Chunk，包含项目名、技术栈、亮点
- 专业技能（skills）：整个技能列表切为一个 Chunk
- 排除：教育背景、自我介绍（语义价值低，干扰向量检索）

Chunk 文本格式设计原则：
- 尽量把最有区分度的技术名词和业务场景集中在文本里
- 方便 Embedding 模型准确捕捉技术领域语义
"""

import logging
from typing import List

logger = logging.getLogger(__name__)


def extract_resume_chunks(resume_analysis: dict) -> List[dict]:
    """
    从简历分析结果中提取语义块列表。

    Args:
        resume_analysis: resume_analyzer_node 输出的结构化简历 JSON，格式:
            {
              "skills": ["Java", "Redis", "MySQL", ...],
              "projects": [
                {
                  "name": "智慧社区管理平台",
                  "tech_stack": ["SpringBoot", "Redis", "RabbitMQ"],
                  "description": "...",
                  "highlights": ["用 Redis+Lua 实现秒杀库存原子扣减", ...]
                }
              ],
              ...
            }

    Returns:
        List[dict]: chunk 列表，每个 chunk 格式:
            {
              "id": "chunk_0",          # 唯一 ID（入库用）
              "text": "...",            # 向量化文本内容
              "metadata": {
                "section": "project",   # "project" 或 "skills"
                "source": "简历项目经历 - 智慧社区管理平台"
              }
            }
    """
    chunks = []
    chunk_index = 0

    # ---- 1. 切块：每个项目经历独立为一个 Chunk ----
    projects = resume_analysis.get("projects", [])
    for project in projects:
        if not project:
            continue

        name = project.get("name", "未命名项目")
        tech_stack = project.get("tech_stack", [])
        description = project.get("description", "")
        highlights = project.get("highlights", [])

        # 拼接项目文本：技术名词密集，有利于语义向量精准定位
        tech_str = "、".join(tech_stack) if tech_stack else ""
        highlights_str = "；".join(highlights) if highlights else ""

        text_parts = [f"项目名称：{name}"]
        if tech_str:
            text_parts.append(f"使用技术栈：{tech_str}")
        if description:
            text_parts.append(f"项目描述：{description}")
        if highlights_str:
            text_parts.append(f"技术亮点：{highlights_str}")

        text = "\n".join(text_parts)

        if len(text.strip()) < 10:   # 跳过内容过少的空项目
            continue

        chunks.append({
            "id": f"chunk_{chunk_index}",
            "text": text,
            "metadata": {
                "section": "project",
                "source": f"简历项目经历 - {name}"
            }
        })
        chunk_index += 1
        logger.debug(f"提取项目 Chunk: [{name}] ({len(text)} 字)")

    # ---- 2. 切块：专业技能整体为一个 Chunk ----
    skills = resume_analysis.get("skills", [])
    if skills:
        skills_str = "、".join(str(s) for s in skills if s)
        if skills_str:
            text = f"候选人专业技能与技术栈：{skills_str}"
            chunks.append({
                "id": f"chunk_{chunk_index}",
                "text": text,
                "metadata": {
                    "section": "skills",
                    "source": "简历专业技能"
                }
            })
            chunk_index += 1
            logger.debug(f"提取技能 Chunk: {len(skills)} 项技能")

    logger.info(f"简历分块完成：共提取 {len(chunks)} 个语义块（{len(projects)} 个项目 + 1 个技能块）")
    return chunks
