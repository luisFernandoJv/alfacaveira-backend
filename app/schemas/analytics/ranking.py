"""Schemas de resposta de ranking."""

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.analytics.ranking import UserRanking


class RankingPositionResponse(BaseModel):
    """Posição de um usuário no ranking."""

    model_config = ConfigDict(from_attributes=True)

    user_id: uuid.UUID
    user_name: str = Field(description="Nome do usuário")
    total_points: int = Field(description="Pontuação total")
    questions_answered: int = Field(description="Total de questões respondidas")
    accuracy: float = Field(description="Taxa de acerto (%)")
    streak_days: int = Field(description="Sequência de estudos (dias)")
    rank: int | None = Field(description="Posição no ranking")

    @classmethod
    def from_model(cls, ranking: UserRanking) -> "RankingPositionResponse":
        """Constrói a resposta a partir do modelo ORM."""
        return cls(
            user_id=ranking.user_id,
            user_name=ranking.user.full_name if ranking.user else "Usuário",
            total_points=ranking.total_points,
            questions_answered=ranking.questions_answered,
            accuracy=ranking.accuracy,
            streak_days=ranking.streak_days,
            rank=ranking.rank,
        )


class RankingResponse(BaseModel):
    """Resposta de listagem de ranking."""

    items: list[RankingPositionResponse]
    total: int = Field(
        description=(
            "Total de usuários elegíveis nesta aba do ranking (não o tamanho "
            "da página atual — ver `RankingRepository.get_global_count` / "
            "`get_weekly_count` / `get_monthly_count`)"
        )
    )
    user_position: int | None = Field(description="Posição do usuário atual")
    has_more: bool = Field(description="Se há mais itens para carregar")


class UserRankingResponse(BaseModel):
    """Ranking do usuário autenticado."""

    model_config = ConfigDict(from_attributes=True)

    user_id: uuid.UUID
    total_points: int
    questions_answered: int
    correct_answers: int
    accuracy: float
    streak_days: int
    rank: int | None
    rank_weekly: int | None
    rank_monthly: int | None
    updated_at: datetime