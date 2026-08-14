"""评估 Agent —— 面试结束后生成综合评估报告

本模块在所有面试题目答完后被调用（由 InterviewSession._run_evaluation() 直接触发，
不经过 LangGraph 图），根据逐题评分数据和维度聚合结果，生成最终评估报告。

核心设计要点：
1. 四维度评分体系：
   - 技术基础：考察八股文、底层原理的掌握程度
   - 项目经验：考察项目经历的深度和真实性
   - 场景设计：考察架构思维和方案设计能力
   - 软技能：考察沟通表达、学习能力等综合素质
   这四个维度对应出题时的四类题目（技术基础/项目经验/场景设计/软技能），
   形成"出题-评分-评估"的闭环。

2. 评分数据流：
   逐题评分 → 维度聚合（aggregated_dimensions）→ 评估报告
   - 逐题评分：每道题在 Q&A 阶段由评分逻辑打分（0-10分），含各维度子分
   - 维度聚合：将同一维度的所有题目得分取均值，得到维度总分
   - 评估报告：LLM 基于聚合分数撰写评语和建议，不重新打分

3. 统计上下文注入（stats_context）：
   将候选人的历史面试统计数据（如平均分、各维度历史表现）作为上下文注入 Prompt，
   让 LLM 在撰写评语时能做横向对比（如"相比上次面试，技术基础有明显提升"）。
   这是实现"个性化反馈"的关键机制。

4. Prompt 约束："score 直接使用输入数据中的聚合均分，不要改动分数"
   确保 LLM 不会主观调整分数，评分的客观性由逐题评分逻辑保证，
   LLM 只负责撰写评语和建议（主观但有价值的人文解读）。

详见 AI链路学习路径.md 第7步（评估节点）
"""

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from langchain_core.output_parsers import JsonOutputParser
from app.core.llm import get_fast_llm
from app.agents.state import InterviewState
from app.models.evaluation_schemas import ComprehensiveEvaluationResult
import json
import logging

logger = logging.getLogger(__name__)

_eval_parser = JsonOutputParser(pydantic_object=ComprehensiveEvaluationResult)
_format_instructions = _eval_parser.get_format_instructions()

SYSTEM_PROMPT = f"""你是一位面试评估专家。根据面试全过程和各维度评分数据，生成综合评估报告。

注意：dimensions 中的 score 直接使用输入数据中各题维度的聚合均分（已提供在 aggregated_dimensions 中），不要改动分数。
comment 和 suggestions 需要你根据各维度表现撰写。
overall_score 取四个维度分的均值。

{_format_instructions}
"""


def create_evaluator():
    """
    创建评估 ReAct Agent。

    使用 get_fast_llm()（低温度 0.3）：评估报告需要客观、稳定的输出。
    """
    return create_agent(
        model=get_fast_llm(),
        tools=[],
        name="evaluator",
        system_prompt=SYSTEM_PROMPT,
    )


# 单例 Agent 实例（懒加载）
_evaluator_agent = None


def _get_evaluator():
    """获取评估 Agent 单例（懒加载模式）"""
    global _evaluator_agent
    if _evaluator_agent is None:
        _evaluator_agent = create_evaluator()
    return _evaluator_agent


def evaluator_node(state: InterviewState) -> InterviewState:
    """
    评估节点函数 —— 不在 LangGraph 图中，由 InterviewSession 直接调用。
    """
    aggregated = state.get("aggregated_dimensions", [])
    answers = state.get("answers", [])

    input_data = {
        "aggregated_dimensions": aggregated,
        "answers": [
            {
                "question": a.get("question", ""),
                "category": a.get("category", ""),
                "score": a.get("score", 0),
                "dimensions": a.get("dimensions", {}),
                "feedback": a.get("feedback", ""),
            }
            for a in answers
        ],
        "jd_analysis": state.get("jd_analysis", {}),
        "gap_analysis": state.get("gap_analysis", {}),
    }

    stats_context = state.get("stats_context", "")
    prompt_content = json.dumps(input_data, ensure_ascii=False, indent=2)
    if stats_context:
        prompt_content = stats_context + "\n\n" + prompt_content

    agent = _get_evaluator()
    result = agent.invoke({
        "messages": [HumanMessage(content=prompt_content)]
    })

    raw_content = result["messages"][-1].content.strip()
    if raw_content.startswith("```"):
        raw_content = raw_content.split("\n", 1)[-1]
        if raw_content.endswith("```"):
            raw_content = raw_content[:-3]
        raw_content = raw_content.strip()

    try:
        try:
            parsed = _eval_parser.parse(raw_content)
        except Exception:
            parsed = json.loads(raw_content)
        validated = ComprehensiveEvaluationResult.model_validate(parsed)
        evaluation = validated.model_dump()
    except Exception as e:
        logger.warning(f"评估报告解析校验降级: {e}")
        try:
            evaluation = json.loads(raw_content)
        except Exception:
            evaluation = {"overall_score": 0, "dimensions": [], "improvement_suggestions": []}

    return {**state, "evaluation": evaluation, "phase": "done"}

