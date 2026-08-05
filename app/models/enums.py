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
