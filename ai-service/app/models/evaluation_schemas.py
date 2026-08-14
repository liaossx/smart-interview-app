from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field, field_validator


class DimensionScores(BaseModel):
    """四维度单题评分明细"""
    技术基础: int = Field(default=0, description="技术基础维度得分，0-10分")
    项目经验: int = Field(default=0, description="项目经验维度得分，0-10分")
    场景设计: int = Field(default=0, description="场景设计维度得分，0-10分")
    软技能: int = Field(default=0, description="表达与软技能得分，0-10分")

    @field_validator("技术基础", "项目经验", "场景设计", "软技能", mode="before")
    @classmethod
    def clamp_dimension(cls, v: Any) -> int:
        try:
            val = int(float(v))
            return max(0, min(10, val))
        except (ValueError, TypeError):
            return 0

    def to_dict(self) -> Dict[str, int]:
        return {
            "技术基础": self.技术基础,
            "项目经验": self.项目经验,
            "场景设计": self.场景设计,
            "软技能": self.软技能,
        }


class AnswerEvaluationResult(BaseModel):
    """单题作答评分模型"""
    score: int = Field(default=0, description="综合得分，0-10分")
    dimensions: DimensionScores = Field(default_factory=DimensionScores, description="各细分维度评分（0-10分）")
    feedback: str = Field(default="", description="对本题回答的技术点评与分析")
    follow_up: Optional[str] = Field(
        default="",
        description="追问问题：如果候选人回答不完整或得分<7分，生成一个深入的追问；否则保持为空字符串"
    )
    confidence: int = Field(default=8, description="AI 对本次评分的自信程度（0-10分）")
    is_safe: bool = Field(default=True, description="是否通过安全护栏检测")

    @field_validator("score", "confidence", mode="before")
    @classmethod
    def clamp_score(cls, v: Any) -> int:
        try:
            val = int(float(v))
            return max(0, min(10, val))
        except (ValueError, TypeError):
            return 5


class DimensionReport(BaseModel):
    """综合报告维度评价"""
    name: str = Field(description="维度名称，如'技术基础'、'项目经验'、'场景设计'、'软技能'")
    score: int = Field(ge=0, le=100, description="该维度综合均分")
    comment: str = Field(description="该维度的具体综合评语")
    suggestions: List[str] = Field(default_factory=list, description="针对该维度的改进建议列表")


class RecommendedLearning(BaseModel):
    """推荐学习资源"""
    resource: str = Field(description="推荐的学习资源名称/书籍/技术文档")
    reason: str = Field(description="推荐原因与对应短板")


class ComprehensiveEvaluationResult(BaseModel):
    """全场面试综合评估报告模型"""
    overall_score: int = Field(ge=0, le=100, description="整场面试综合总评分，0-100分")
    dimensions: List[DimensionReport] = Field(default_factory=list, description="各维度的综合评价")
    strengths: List[str] = Field(default_factory=list, description="候选人展现出的主要技术优势列表")
    weaknesses: List[str] = Field(default_factory=list, description="候选人展现出的主要薄弱项列表")
    improvement_suggestions: List[str] = Field(default_factory=list, description="具体的复习与提升建议列表")
    recommended_learning: List[RecommendedLearning] = Field(default_factory=list, description="针对短板推荐的学习资源")
