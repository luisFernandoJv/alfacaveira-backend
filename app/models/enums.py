"""Enums compartilhados entre models de diferentes bounded contexts."""

import enum


class QuestionDifficulty(str, enum.Enum):
    FACIL = "facil"
    MEDIA = "media"
    DIFICIL = "dificil"


class QuestionStatus(str, enum.Enum):
    RASCUNHO = "rascunho"
    PUBLICADA = "publicada"
    EM_REVISAO = "em_revisao"
    DESATIVADA = "desativada"


class QuestionRevisionType(str, enum.Enum):
    CRIACAO = "criacao"
    EDICAO = "edicao"
    STATUS = "status"
    EXCLUSAO = "exclusao"


class AttachmentType(str, enum.Enum):
    IMAGEM = "imagem"
    ARQUIVO = "arquivo"


class SessionType(str, enum.Enum):
    TREINO = "treino"
    SIMULADO = "simulado"


class ExamAttemptStatus(str, enum.Enum):
    EM_ANDAMENTO = "em_andamento"
    FINALIZADO = "finalizado"
    ABANDONADO = "abandonado"


class FlashcardGrade(str, enum.Enum):
    ERROU = "errou"
    DIFICIL = "dificil"
    BOM = "bom"
    FACIL = "facil"


class BillingPeriod(str, enum.Enum):
    MENSAL = "mensal"
    SEMESTRAL = "semestral"
    ANUAL = "anual"


class SubscriptionStatus(str, enum.Enum):
    ATIVA = "ativa"
    CANCELADA = "cancelada"
    INADIMPLENTE = "inadimplente"
    EXPIRADA = "expirada"


class PaymentStatus(str, enum.Enum):
    PENDENTE = "pendente"
    APROVADO = "aprovado"
    RECUSADO = "recusado"
    ESTORNADO = "estornado"


class FeatureKey(str, enum.Enum):
    """Catálogo fechado de features que um `Plan` pode conceder."""

    DAILY_QUESTIONS = "daily_questions"
    NOTEBOOKS = "notebooks"
    NOTEBOOK_MAX_QUESTIONS = "notebook_max_questions"
    SIMULADOS = "simulados"
    FLASHCARDS = "flashcards"
    ESTATISTICAS = "estatisticas"
    DASHBOARD_COMPLETO = "dashboard_completo"
    AI_EXPLICACAO_QUESTAO = "ai_explicacao_questao"
    AI_RESUMOS = "ai_resumos"
    AI_CRONOGRAMA = "ai_cronograma"
    AI_ANALISE_DESEMPENHO = "ai_analise_desempenho"
    ANALYTICS_AVANCADO = "analytics_avancado"


class FeatureKind(str, enum.Enum):
    """Como uma `Feature` é interpretada por `FeatureGateService`."""

    BOOLEAN = "boolean"
    QUOTA = "quota"


class SubscriptionHistoryReason(str, enum.Enum):
    CRIADA = "criada"
    RENOVADA = "renovada"
    UPGRADE = "upgrade"
    DOWNGRADE = "downgrade"
    CANCELADA = "cancelada"
    REATIVADA = "reativada"
    EXPIRADA = "expirada"
    PAGAMENTO_FALHOU = "pagamento_falhou"