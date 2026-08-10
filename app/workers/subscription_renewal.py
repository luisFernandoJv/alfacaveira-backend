"""Worker de renovação automática de assinaturas (PROMPT 10, roadmap item 10).

Contexto (mesmo raciocínio de `app/workers/analytics_aggregator.py`): o
projeto não tem fila/agendador dedicado além do Redis de rate limit, e a API
roda como processo único de uvicorn — por isso este worker é pensado tanto
para ser chamado por um cron externo quanto para ser agendado in-process via
APScheduler (`app/core/scheduler.py`), o mesmo padrão já estabelecido.

O job faz duas coisas por execução, usando exclusivamente os services já
existentes (`PaymentService`, `SubscriptionService`) — nenhuma lógica de
transição de estado é duplicada aqui:

1. **Cobrança de renovação**: para cada assinatura ATIVA, não agendada para
   cancelar, cujo período corrente já terminou
   (`SubscriptionRepository.list_due_for_renewal`), tenta cobrar exatamente
   uma vez (`PaymentService.charge_subscription`) e aplica o resultado
   diretamente via `SubscriptionService.renew_subscription_system`/
   `mark_payment_failed` (não via `PaymentService.process_webhook_event` —
   ver docstring de `_charge_and_apply` para o porquê).
2. **Cancelamentos agendados vencidos**: para cada assinatura ATIVA com
   `cancel_at_period_end=True` cujo período já terminou
   (`list_scheduled_cancellations_due`), efetiva o cancelamento
   (`SubscriptionService.finalize_scheduled_cancellation`) — sem cobrar de
   novo.

Idempotente por construção, não por um lock explícito:

- "Tentativa única" (requisito do PROMPT 10): cada assinatura elegível é
  cobrada no máximo uma vez por execução — o loop não tenta de novo se a
  cobrança falhar dentro da mesma execução (retry entre execuções é uma
  decisão de dunning/grace period, fora do escopo desta etapa — ver
  PROMPT 11).
- "Retry seguro" (rodar o job de novo não duplica cobrança): depois de uma
  cobrança bem-sucedida, `renew_subscription_system` avança
  `current_period_end` para o futuro — a próxima execução não seleciona
  mais essa assinatura em `list_due_for_renewal` (o filtro é
  `current_period_end <= now`). Depois de uma falha, a assinatura sai de
  ATIVA (`mark_payment_failed` -> INADIMPLENTE), então também some do
  filtro `status == ATIVA` — nenhuma cobrança duplicada é possível nem no
  caminho de sucesso nem no de falha.
- Duas execuções verdadeiramente concorrentes do próprio job não são
  esperadas (`app/core/scheduler.py` usa `max_instances=1`, mesmo padrão do
  agregador de analytics) — mas mesmo assim, `PaymentService`/
  `SubscriptionService` já são seguros sob concorrência real (CAS +
  `payment_id` único, ver `docs/DECISIONS.md` ADR-017/ADR-019/ADR-022/
  ADR-023), então uma segunda execução simultânea não duplicaria histórico
  mesmo que a garantia acima falhasse.

Uso como script standalone (mesmo padrão de `analytics_aggregator`):

    poetry run python -m app.workers.subscription_renewal
"""

import argparse
import asyncio
from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import AsyncSessionFactory
from app.models.enums import PaymentStatus
from app.repositories.billing.subscription_repository import SubscriptionRepository
from app.services.billing.payment_service import PaymentService
from app.services.billing.subscription_service import SubscriptionService

logger = structlog.get_logger(__name__)


async def _charge_and_apply(
    payment_service: PaymentService,
    subscription_service: SubscriptionService,
    subscription_id,
) -> None:
    """Tentativa única de cobrança de renovação para uma assinatura, com o
    efeito colateral aplicado diretamente (sem passar por
    `PaymentService.process_webhook_event`).

    Isto é deliberado, não um atalho: `charge_subscription` (ver seu
    docstring) grava o `Payment` já com `status=result.status` — para o
    driver `console` (único hoje, síncrono), isso significa que o
    `Payment` já nasce com o status final (ex.: APROVADO) na mesma chamada
    que o cria. Se este worker chamasse `process_webhook_event` logo em
    seguida com esse MESMO status, cairia direto no guard de idempotência
    de reentrega (`if payment.status == status: return payment`,
    pensado para uma segunda entrega do MESMO evento) e nunca aplicaria o
    efeito colateral — não é esse guard que este caminho síncrono deveria
    atravessar. `process_webhook_event` continua sendo a única porta de
    entrada para uma confirmação assíncrona chegando por um webhook real;
    este worker, ao cobrar e já receber o resultado na mesma chamada,
    aplica o efeito diretamente via `SubscriptionService`, sem duplicar a
    lógica de transição de estado (que já está centralizada lá) nem
    reaproveitar incorretamente a idempotência pensada para outro caso.

    Um driver real e assíncrono devolveria `PENDENTE` aqui — este worker
    não faria nada além de iniciar a cobrança, e a confirmação chegaria
    depois pelo endpoint de webhook de verdade, seguindo
    `process_webhook_event` normalmente.
    """
    payment = await payment_service.charge_subscription(subscription_id)
    if payment.status == PaymentStatus.APROVADO:
        await subscription_service.renew_subscription_system(subscription_id, payment_id=payment.id)
    elif payment.status in (PaymentStatus.RECUSADO, PaymentStatus.ESTORNADO):
        await subscription_service.mark_payment_failed(subscription_id)
    # PaymentStatus.PENDENTE: driver assíncrono real — nada a aplicar agora,
    # a confirmação chega depois via webhook.


async def run_once(session: AsyncSession, *, now: datetime | None = None) -> dict[str, int]:
    """Uma execução do job. Recebe a `session` já aberta (em vez de abrir a
    sua própria) para ser exercitável em teste automatizado com dublês —
    ver `tests/unit/billing/test_subscription_renewal.py`, que roda esta
    função duas vezes seguidas para validar o requisito "executar o job
    duas vezes não duplica cobrança" (PROMPT 10).

    Retorna contadores (`charged`, `finalized_cancellations`) só para
    logging/observabilidade do chamador — não é o mecanismo de
    idempotência em si (ver docstring do módulo).
    """
    now = now or datetime.now(UTC)
    subscriptions = SubscriptionRepository(session)
    payment_service = PaymentService(session)
    subscription_service = SubscriptionService(session)

    due = await subscriptions.list_due_for_renewal(now)
    charged = 0
    for subscription in due:
        logger.info("subscription_renewal.charging", subscription_id=str(subscription.id))
        try:
            await _charge_and_apply(payment_service, subscription_service, subscription.id)
        except Exception:
            # Uma falha nesta assinatura não deve impedir o job de seguir
            # para as demais — mesmo espírito de `_run_aggregator_job` em
            # `app/core/scheduler.py` (não relançar para o scheduler), só
            # que aqui por-item em vez de por-execução inteira, já que uma
            # exceção isolada (ex.: gateway indisponível para uma cobrança
            # específica) não deveria interromper a renovação das outras
            # assinaturas elegíveis na mesma janela.
            logger.exception(
                "subscription_renewal.charge_failed", subscription_id=str(subscription.id)
            )
            continue
        charged += 1

    scheduled_cancellations = await subscriptions.list_scheduled_cancellations_due(now)
    finalized = 0
    for subscription in scheduled_cancellations:
        logger.info(
            "subscription_renewal.finalizing_cancellation", subscription_id=str(subscription.id)
        )
        try:
            await subscription_service.finalize_scheduled_cancellation(subscription.id)
        except Exception:
            logger.exception(
                "subscription_renewal.finalize_cancellation_failed",
                subscription_id=str(subscription.id),
            )
            continue
        finalized += 1

    return {"charged": charged, "finalized_cancellations": finalized}


async def run() -> None:
    """Ponto de entrada do worker — abre sua própria sessão (mesmo padrão
    de `analytics_aggregator.run`) e delega a lógica a `run_once`."""
    async with AsyncSessionFactory() as session:
        result = await run_once(session)

    print(
        "Renovação automática concluída "
        f"(cobradas: {result['charged']}, cancelamentos efetivados: "
        f"{result['finalized_cancellations']})."
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Cobra assinaturas ATIVA vencidas e efetiva cancelamentos agendados vencidos."
        )
    )
    return parser.parse_args()


if __name__ == "__main__":
    _parse_args()
    asyncio.run(run())