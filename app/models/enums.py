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
    # PENDENTE: assinatura criada, aguardando confirmação de pagamento do
    # gateway. Nasce aqui por padrão (ADR-003) e só vira ATIVA quando
    # `PaymentService.process_webhook_event` confirma um pagamento
    # APROVADO via `SubscriptionService.activate_subscription` (ver
    # ADR-014, PROMPT 05).
    PENDENTE = "pendente"
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
    # ATIVADA: transição PENDENTE -> ATIVA feita por
    # `SubscriptionService.activate_subscription` quando o webhook
    # confirma o primeiro pagamento (PROMPT 05). Distinta de RENOVADA
    # (que é ATIVA -> ATIVA, avanço de período de uma assinatura que já
    # estava paga).
    ATIVADA = "ativada"
    RENOVADA = "renovada"
    UPGRADE = "upgrade"
    DOWNGRADE = "downgrade"
    CANCELADA = "cancelada"
    REATIVADA = "reativada"
    EXPIRADA = "expirada"
    PAGAMENTO_FALHOU = "pagamento_falhou"
    # PROMPT 11 (Dunning): tentativa de recobrança de uma assinatura já
    # INADIMPLENTE falhou de novo (permanece INADIMPLENTE, from_status ==
    # to_status — mesmo espírito de RENOVADA, que também é ATIVA -> ATIVA).
    # Distinta de PAGAMENTO_FALHOU, que é a transição inicial ATIVA/PENDENTE
    # -> INADIMPLENTE/CANCELADA (falha de status muda).
    RETRY_DUNNING_FALHOU = "retry_dunning_falhou"
    # PROMPT 11: uma tentativa de recobrança de uma assinatura INADIMPLENTE
    # foi aprovada — volta para ATIVA e o período é avançado (mesmo efeito
    # de uma renovação normal).
    RECUPERADA_DUNNING = "recuperada_dunning"
    # PROMPT 12 (Upgrade/Downgrade): upgrade pendente de confirmação de
    # pagamento (gateway assíncrono). A assinatura permanece no plano atual
    # até a confirmação; quando o webhook APROVADO chega, a transição é
    # registrada como UPGRADE (não UPGRADE_PENDENTE). Este valor é usado
    # apenas para rastrear o estado intermediário, se necessário.
    UPGRADE_PENDENTE = "upgrade_pendente"

    # app/models/enums.py (adicionar ao final)

class SubscriptionEmailEvent(str, enum.Enum):
    """Eventos que disparam e-mails transacionais de assinatura."""
    PAYMENT_APPROVED = "payment_approved"
    PAYMENT_FAILED = "payment_failed"
    RENEWAL_SUCCESS = "renewal_success"
    RENEWAL_REMINDER = "renewal_reminder"
    CANCELLATION = "cancellation"
    REACTIVATION = "reactivation"
    PLAN_CHANGE = "plan_change"
    DUNNING_RECOVERED = "dunning_recovered"
    DUNNING_RETRY_FAILED = "dunning_retry_failed"
    DUNNING_EXPIRED = "dunning_expired"

# app/models/enums.py (adicionar)

# Adicionar ao final do arquivo app/models/enums.py

class ReviewStatus(str, enum.Enum):
    PENDENTE = "pendente"
    EM_ANDAMENTO = "em_andamento"
    CONCLUIDA = "concluida"
    PULAR = "pular"


class ReviewPriority(str, enum.Enum):
    ALTA = "alta"
    MEDIA = "media"
    BAIXA = "baixa"

class CommentStatus(str, enum.Enum):
    """Status de um comentário."""
    PUBLICADO = "publicado"
    PENDENTE = "pendente"
    DENUNCIADO = "denunciado"
    REMOVIDO = "removido"
    BLOQUEADO = "bloqueado"


class CommentVoteType(str, enum.Enum):
    """Tipo de voto em um comentário."""
    UP = "up"
    DOWN = "down"



# app/models/enums.py (adicionar)

# app/models/enums.py (adicionar no final do arquivo)

class NotificationType(str, enum.Enum):
    """Tipos de notificação."""
    NEW_COMMENT = "new_comment"
    NEW_REPLY = "new_reply"
    COMMENT_VOTE = "comment_vote"
    MENTION = "mention"
    SYSTEM = "system"
    PAYMENT = "payment"
    RENEWAL = "renewal"


class NotificationStatus(str, enum.Enum):
    """Status da notificação."""
    UNREAD = "unread"
    READ = "read"
    ARCHIVED = "archived"