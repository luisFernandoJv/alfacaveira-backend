"""Worker de dunning (PROMPT 11, roadmap item 11).

Mesmo padrão de `app/workers/subscription_renewal.py` (PROMPT 10): a API
roda como processo único de uvicorn, sem fila/agendador dedicado, então
este worker é pensado tanto para cron externo quanto para agendamento
in-process via APScheduler (`app/core/scheduler.py`).

Política comercial (decidida explicitamente pelo usuário, não inventada —
ver `docs/DECISIONS.md` ADR-027 e `app/core/config.py`, `DUNNING_*`): até
`DUNNING_MAX_RETRIES` tentativas de recobrança, uma a cada
`DUNNING_RETRY_INTERVAL_DAYS` dias, dentro de um grace period de
`DUNNING_GRACE_PERIOD_DAYS` dias a partir do momento em que a assinatura
entrou em INADIMPLENTE (`SubscriptionService.mark_payment_failed`).

O job faz duas coisas por execução, usando exclusivamente os services já
existentes (`PaymentService`, `SubscriptionService`) — nenhuma lógica de
transição de estado é duplicada aqui, mesmo espírito do worker de
renovação:

1. **Retry de recobrança**: para cada assinatura INADIMPLENTE com uma
   tentativa elegível agora (`SubscriptionRepository.
   list_due_for_dunning_retry`), tenta cobrar exatamente uma vez
   (`PaymentService.charge_subscription`) e aplica o resultado
   diretamente via `SubscriptionService.recover_from_dunning` (aprovado)
   ou `SubscriptionService.record_dunning_retry_failure` (recusado/
   estornado) — não via `PaymentService.process_webhook_event`, pelo
   mesmo motivo documentado em `_charge_and_apply` de
   `subscription_renewal.py`: o driver `console` grava o `Payment` já com
   o status final na mesma chamada que o cria, o que cairia no guard de
   idempotência de reentrega de `process_webhook_event` e nunca aplicaria
   o efeito colateral.
2. **Expiração por fim de grace period**: para cada assinatura
   INADIMPLENTE cujo grace period já terminou
   (`list_due_for_dunning_expiration`), expira
   (`SubscriptionService.expire_from_dunning`) — independentemente de
   quantas tentativas de retry ainda restariam. Uma assinatura pode
   aparecer nas duas listas na mesma execução (retry elegível E grace
   period já vencido, se o job não rodou por um tempo); roda-se a
   cobrança primeiro — se aprovada, `recover_from_dunning` já tira a
   assinatura de INADIMPLENTE, então a segunda passada
   (`list_due_for_dunning_expiration`, executada depois, com dados já
   recarregados do banco) não a encontra mais.

Idempotente por construção, mesmo raciocínio do worker de renovação:

- Depois de uma recobrança bem-sucedida, `recover_from_dunning` move a
  assinatura para ATIVA — some de `list_due_for_dunning_retry` (filtro
  `status == INADIMPLENTE`) na próxima execução.
- Depois de uma falha de retry, `record_dunning_retry_failure` incrementa
  `dunning_attempts` e agenda (ou não, se esgotado) o próximo
  `dunning_next_retry_at` — a mesma assinatura só volta a aparecer na
  lista quando esse novo prazo chegar (ou nunca mais, se as tentativas já
  se esgotaram, até o grace period vencer e ela ser expirada pelo outro
  caminho).
- Depois de expirada, sai de `list_due_for_dunning_expiration` (filtro
  `status == INADIMPLENTE`).
- Duas execuções verdadeiramente concorrentes do próprio job não são
  esperadas (`max_instances=1` no scheduler, mesmo padrão dos demais
  workers) — mas `SubscriptionService` já é seguro sob concorrência real
  (CAS em todos os métodos novos desta etapa), então uma segunda execução
  simultânea não duplicaria histórico mesmo que essa garantia falhasse.

Uso como script standalone (mesmo padrão de `subscription_renewal`):

    poetry run python -m app.workers.subscription_dunning
"""

import argparse
import asyncio
from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.database.session import AsyncSessionFactory
from app.models.enums import PaymentStatus
from app.repositories.billing.subscription_repository import SubscriptionRepository
from app.services.billing.payment_service import PaymentService
from app.services.billing.subscription_service import SubscriptionService

logger = structlog.get_logger(__name__)


async def _retry_charge_and_apply(
    payment_service: PaymentService,
    subscription_service: SubscriptionService,
    subscription_id,
) -> bool:
    """Tentativa única de recobrança para uma assinatura INADIMPLENTE, com
    o efeito colateral aplicado diretamente (ver docstring do módulo).
    Retorna `True` se a recobrança foi aprovada (recuperada), `False` caso
    contrário (falha registrada, ou confirmação assíncrona pendente).
    """
    payment = await payment_service.charge_subscription(subscription_id)
    if payment.status == PaymentStatus.APROVADO:
        await subscription_service.recover_from_dunning(subscription_id, payment_id=payment.id)
        return True
    if payment.status in (PaymentStatus.RECUSADO, PaymentStatus.ESTORNADO):
        await subscription_service.record_dunning_retry_failure(subscription_id)
        return False
    # PaymentStatus.PENDENTE: driver assíncrono real — nada a aplicar
    # agora, a confirmação chega depois via webhook
    # (`PaymentService.process_webhook_event`, ramo INADIMPLENTE).
    return False


async def run_once(session: AsyncSession, *, now: datetime | None = None) -> dict[str, int]:
    """Uma execução do job. Recebe a `session` já aberta (mesmo padrão de
    `subscription_renewal.run_once`) para ser exercitável em teste
    automatizado com dublês — ver
    `tests/unit/billing/test_subscription_dunning_worker.py`.

    Retorna contadores (`retried`, `recovered`, `expired`) só para
    logging/observabilidade do chamador — não é o mecanismo de
    idempotência em si (ver docstring do módulo).
    """
    now = now or datetime.now(UTC)
    subscriptions = SubscriptionRepository(session)
    payment_service = PaymentService(session)
    subscription_service = SubscriptionService(session)

    due_retry = await subscriptions.list_due_for_dunning_retry(
        now, max_attempts=settings.DUNNING_MAX_RETRIES
    )
    retried = 0
    recovered = 0
    for subscription in due_retry:
        logger.info("subscription_dunning.retrying", subscription_id=str(subscription.id))
        try:
            was_recovered = await _retry_charge_and_apply(
                payment_service, subscription_service, subscription.id
            )
        except Exception:
            # Mesmo espírito de `subscription_renewal.run_once`: uma falha
            # isolada não deve impedir o job de seguir para as demais
            # assinaturas elegíveis na mesma janela.
            logger.exception(
                "subscription_dunning.retry_failed", subscription_id=str(subscription.id)
            )
            continue
        retried += 1
        if was_recovered:
            recovered += 1

    due_expiration = await subscriptions.list_due_for_dunning_expiration(now)
    expired = 0
    for subscription in due_expiration:
        logger.info("subscription_dunning.expiring", subscription_id=str(subscription.id))
        try:
            await subscription_service.expire_from_dunning(subscription.id)
        except Exception:
            logger.exception(
                "subscription_dunning.expire_failed", subscription_id=str(subscription.id)
            )
            continue
        expired += 1

    return {"retried": retried, "recovered": recovered, "expired": expired}


async def run() -> None:
    """Ponto de entrada do worker — abre sua própria sessão (mesmo padrão
    de `subscription_renewal.run`) e delega a lógica a `run_once`."""
    async with AsyncSessionFactory() as session:
        result = await run_once(session)

    print(
        "Dunning concluído "
        f"(tentativas: {result['retried']}, recuperadas: {result['recovered']}, "
        f"expiradas: {result['expired']})."
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Tenta recobrar assinaturas INADIMPLENTE elegíveis e expira as que "
            "esgotaram o grace period."
        )
    )
    return parser.parse_args()


if __name__ == "__main__":
    _parse_args()
    asyncio.run(run())