"""Regras de negócio de `Subscription`: criar, ativar, cancelar, reativar,
renovar e trocar de plano.

Toda transição de status ou de plano grava uma linha em `SubscriptionHistory`
dentro da mesma `UnitOfWork` que altera a `Subscription` — nunca separado. A
regra "no máximo 1 assinatura ATIVA por usuário" é garantida em duas camadas:
checagem otimista aqui (mensagem de erro amigável) + índice único parcial
`ux_subscriptions_one_active_per_user` no banco (migration 0005) como
garantia final contra corrida.

Máquina de estados (PROMPT 05, ver ADR-003 e ADR-014):

    create_subscription        PENDENTE
                                   |
    activate_subscription         v   (webhook: pagamento APROVADO)
    (PaymentService)            ATIVA
                                 / |
                    cancel_subscription  change_plan / renew_subscription
                       |                             (permanece ATIVA)
                       v
                  CANCELADA

                 ATIVA --[falha de cobrança recorrente]--> INADIMPLENTE
                 ATIVA --[periodo termina sem renovar]---> EXPIRADA
              PENDENTE --[pagamento inicial recusado]----> CANCELADA
              PENDENTE --[usuario cancela antes de pagar]-> CANCELADA

`mark_payment_failed` e `activate_subscription` não recebem `user_id`
porque quem os aciona é `PaymentService.process_webhook_event` — processamento
de webhook, não uma requisição autenticada de usuário (mesmo padrão já
existente para `mark_payment_failed` antes desta sessão).
"""

import math
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import UTC, datetime, timedelta 

from app.core.config import settings
from app.core.exceptions import ConflictError, NotFoundError
from app.database.uow import UnitOfWork
from app.models.billing.plan import Plan
from app.models.billing.subscription import Subscription
from app.models.billing.subscription_history import SubscriptionHistory
from app.models.enums import (
    BillingPeriod,
    PaymentStatus,
    SubscriptionHistoryReason,
    SubscriptionStatus,
)
from app.repositories.billing.plan_repository import PlanRepository
from app.repositories.billing.subscription_history_repository import SubscriptionHistoryRepository
from app.repositories.billing.subscription_repository import SubscriptionRepository
from app.repositories.identity.user_repository import UserRepository
from app.services.billing.notification_service import SubscriptionNotificationService

_PERIOD_LENGTH: dict[BillingPeriod, timedelta] = {
    BillingPeriod.MENSAL: timedelta(days=30),
    BillingPeriod.SEMESTRAL: timedelta(days=182),
    BillingPeriod.ANUAL: timedelta(days=365),
}

# --- PROMPT 12: Upgrade/Downgrade com pró-rata ------------------------- #
# Valor mínimo para considerar uma cobrança pró-rata (1 centavo)
_MIN_PRORATED_AMOUNT_CENTS = 1


class SubscriptionService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._subscriptions = SubscriptionRepository(session)
        self._plans = PlanRepository(session)
        self._history = SubscriptionHistoryRepository(session)
        self._users = UserRepository(session)
        self._notification = SubscriptionNotificationService()

    # ------------------------------------------------------------------ #
    # Leitura
    # ------------------------------------------------------------------ #

    async def get_subscription(self, subscription_id: uuid.UUID, user_id: uuid.UUID) -> Subscription:
        subscription = await self._subscriptions.get_owned(subscription_id, user_id)
        if subscription is None:
            raise NotFoundError("Assinatura não encontrada.")
        return subscription

    async def get_active(self, user_id: uuid.UUID) -> Subscription | None:
        return await self._subscriptions.get_active_by_user(user_id)

    async def list_subscriptions(self, user_id: uuid.UUID) -> list[Subscription]:
        return await self._subscriptions.list_by_user(user_id)

    # ------------------------------------------------------------------ #
    # Escrita
    # ------------------------------------------------------------------ #

    async def create_subscription(self, user_id: uuid.UUID, plan_id: uuid.UUID) -> Subscription:
        """Cria a assinatura como PENDENTE (ADR-003 é bloqueadora aqui) —
        nunca ATIVA diretamente. Só `activate_subscription` pode mover para
        ATIVA, e só depois de uma confirmação de pagamento vinda do webhook.
        """
        if await self._subscriptions.get_active_by_user(user_id) is not None:
            raise ConflictError("Usuário já possui uma assinatura ativa.")
        if await self._subscriptions.get_pending_by_user(user_id) is not None:
            raise ConflictError("Usuário já possui uma assinatura pendente de pagamento.")

        plan = await self._plans.get_by_id(plan_id)
        if plan is None or not plan.is_active:
            raise NotFoundError("Plano não encontrado ou inativo.")

        now = _utcnow()
        subscription = Subscription(
            user_id=user_id,
            plan_id=plan.id,
            status=SubscriptionStatus.PENDENTE,
            # Placeholder de largura zero (start == end): as colunas são
            # NOT NULL e uma assinatura PENDENTE ainda não tem período de
            # cobrança de verdade — ele só é definido em
            # `activate_subscription`, a partir do momento em que o
            # pagamento é confirmado (ver ADR-014). Não interpretar este
            # valor como "período válido" enquanto `status == PENDENTE`.
            current_period_start=now,
            current_period_end=now,
            cancel_at_period_end=False,
        )

        try:
            async with UnitOfWork(self._session):
                await self._subscriptions.add(subscription)
                await self._session.flush()
                self._session.add(
                    SubscriptionHistory(
                        subscription_id=subscription.id,
                        from_plan_id=None,
                        to_plan_id=plan.id,
                        from_status=None,
                        to_status=SubscriptionStatus.PENDENTE,
                        reason=SubscriptionHistoryReason.CRIADA,
                    )
                )
                await self._session.flush()
        except IntegrityError as exc:
            # Backstop contra corrida: duas requisições concorrentes tentando
            # criar a assinatura ativa do mesmo usuário. A checagem acima já
            # cobre o caso comum; isto cobre a janela entre checagem e commit.
            # Só existe índice único de banco para ATIVA (migration 0005) —
            # a checagem de PENDENTE acima é só aplicativa, sem backstop de
            # `IntegrityError` equivalente (ver `get_pending_by_user`).
            raise ConflictError("Usuário já possui uma assinatura ativa.") from exc

        return await self.get_subscription(subscription.id, user_id)

    async def activate_subscription(self, subscription_id: uuid.UUID) -> Subscription:
        """Move PENDENTE -> ATIVA quando `PaymentService.process_webhook_event`
        confirma um pagamento APROVADO (ver ADR-003, ADR-014, PROMPT 05).

        Define `current_period_start`/`current_period_end` a partir de
        *agora* (momento da ativação), não do momento em que a assinatura
        foi criada — o período placeholder gravado em `create_subscription`
        é descartado aqui.

        Corrida corrigida nesta sessão (roadmap item 7, ADR-018 — mesmo
        padrão de `mark_payment_failed`/ADR-017): `process_webhook_event`
        só chama isto depois de vencer o CAS do próprio `Payment`, mas
        isso não fecha a janela em `Subscription` — dois `Payment`
        distintos para a mesma assinatura (ex.: cobrança duplicada por
        duplo-clique em `charge_subscription`, cada um com seu próprio
        `provider_payment_id`) podem chegar aqui quase juntos, cada um já
        tendo vencido o CAS do seu próprio `Payment`. A escrita usa
        `compare_and_swap_status` (`UPDATE ... WHERE status = PENDENTE`),
        gravando `current_period_start`/`current_period_end` no mesmo
        `UPDATE` condicional — quem perde o CAS não grava um segundo
        `SubscriptionHistory` nem sobrescreve o período já definido pela
        chamada vencedora, e recebe de volta o estado atual em vez de
        levantar `ConflictError` (é uma reentrega/corrida, não um erro do
        chamador).
        """
        subscription = await self._subscriptions.get_by_id_with_plan(subscription_id)
        if subscription is None:
            raise NotFoundError("Assinatura não encontrada.")
        if subscription.status == SubscriptionStatus.ATIVA:
            # Idempotente: outra execução concorrente (duas entregas do mesmo
            # webhook, ou dois Payments distintos para a mesma assinatura) já
            # ativou esta assinatura entre esta leitura e agora — mesmo padrão
            # de mark_payment_failed (ADR-017) e expire_subscription (ADR-018).
            # Achado real via teste de concorrência contra Postgres (ADR-020);
            # o dublê em memória nunca reproduzia esta janela.
            return subscription
        if subscription.status != SubscriptionStatus.PENDENTE:
            raise ConflictError("Apenas assinaturas pendentes podem ser ativadas.")

        now = _utcnow()
        period_length = _PERIOD_LENGTH[subscription.plan.billing_period]
        new_period_start = now
        new_period_end = now + period_length

        async with UnitOfWork(self._session):
            applied = await self._subscriptions.compare_and_swap_status(
                subscription_id,
                expected_status=SubscriptionStatus.PENDENTE,
                new_status=SubscriptionStatus.ATIVA,
                period_start=new_period_start,
                period_end=new_period_end,
            )
            if applied:
                subscription.status = SubscriptionStatus.ATIVA
                subscription.current_period_start = new_period_start
                subscription.current_period_end = new_period_end
                self._session.add(
                    SubscriptionHistory(
                        subscription_id=subscription.id,
                        from_plan_id=subscription.plan_id,
                        to_plan_id=subscription.plan_id,
                        from_status=SubscriptionStatus.PENDENTE,
                        to_status=SubscriptionStatus.ATIVA,
                        reason=SubscriptionHistoryReason.ATIVADA,
                    )
                )
                await self._session.flush()

        if not applied:
            # Perdeu a corrida: outra chamada concorrente já ativou esta
            # assinatura entre a leitura acima e o CAS. Idempotente —
            # devolve o estado atual (já ATIVA, com o período gravado pela
            # vencedora) em vez de levantar ConflictError.
            current = await self._subscriptions.get_by_id_with_plan(subscription_id)
            return current if current is not None else subscription

        # --- NOTIFICAÇÃO: Pagamento aprovado (PROMPT 13) ---
        user = await self._users.get_by_id(subscription.user_id)
        if user:
            await self._notification.notify_payment_approved(user, subscription)

        return subscription

    async def cancel_subscription(
        self, subscription_id: uuid.UUID, user_id: uuid.UUID, *, immediately: bool = False
    ) -> Subscription:
        """Cancela uma assinatura ATIVA (comportamento inalterado desde
        antes do PROMPT 05: agenda para o fim do período, a menos que
        `immediately=True`) ou uma assinatura PENDENTE (novo nesta sessão:
        cancela na hora sempre, ignorando `immediately` — não existe "fim
        do período corrente" para uma assinatura que nunca chegou a
        cobrar, ver ADR-014).

        CORREÇÃO (achado desta sessão, rerun de integração real): faltava
        aqui o mesmo guard de idempotência que `activate_subscription` e
        `mark_payment_failed` já têm — "se já estou no estado terminal que
        eu mesmo produziria, retorna sem erro" ANTES de checar se o status
        atual é cancelável. Sem isso, uma segunda chamada concorrente cuja
        leitura acontece *depois* do commit da primeira (`asyncio.gather`
        não garante contenção real — mesmo raciocínio do `change_plan`,
        ver ADR-023) lia `status == CANCELADA` e levantava `ConflictError`
        em vez de idempotência; o CAS logo abaixo só protege a janela
        entre a leitura *e* o CAS, não cobre uma leitura que já começa
        depois do commit alheio (mesmo padrão do achado do ADR-022 em
        `renew_subscription`).
        """
        subscription = await self.get_subscription(subscription_id, user_id)
        if subscription.status == SubscriptionStatus.CANCELADA:
            # Idempotente: outra chamada concorrente (duplo-clique do
            # mesmo usuário, ver ADR-019) já cancelou esta assinatura
            # entre a leitura desta chamada e agora. `CANCELADA` só é
            # alcançado por este próprio método ou por
            # `mark_payment_failed` (PENDENTE com pagamento inicial
            # recusado) — em ambos os casos, "cancelar de novo" já é
            # verdade, então devolver o estado atual é a resposta certa,
            # não um erro.
            return subscription
        if subscription.status not in (SubscriptionStatus.ATIVA, SubscriptionStatus.PENDENTE):
            raise ConflictError("Apenas assinaturas ativas ou pendentes podem ser canceladas.")

        previous_status = subscription.status
        new_status = (
            SubscriptionStatus.CANCELADA
            if previous_status == SubscriptionStatus.PENDENTE or immediately
            else previous_status
        )
        values: dict[str, object] = {}
        if new_status != previous_status:
            values["status"] = new_status
        if previous_status == SubscriptionStatus.ATIVA:
            values["cancel_at_period_end"] = True

        async with UnitOfWork(self._session):
            applied = await self._subscriptions.compare_and_swap(
                subscription_id,
                expected={"status": previous_status},
                values=values,
            )
            if applied:
                subscription.status = new_status
                if previous_status == SubscriptionStatus.ATIVA:
                    subscription.cancel_at_period_end = True
                self._session.add(
                    SubscriptionHistory(
                        subscription_id=subscription.id,
                        from_plan_id=subscription.plan_id,
                        to_plan_id=subscription.plan_id,
                        from_status=previous_status,
                        to_status=new_status,
                        reason=SubscriptionHistoryReason.CANCELADA,
                    )
                )
                await self._session.flush()

        # Se `applied` for `False`, outra chamada concorrente já cancelou
        # esta assinatura entre a leitura acima e o CAS (duplo-clique do
        # mesmo usuário, ver ADR-019) — tratado como idempotente, sem
        # duplicar `SubscriptionHistory`; o retorno abaixo reflete o
        # estado atual (já cancelado pela chamada vencedora) em ambos os
        # casos.
        final_subscription = await self.get_subscription(subscription_id, user_id)

        # --- NOTIFICAÇÃO: Cancelamento (PROMPT 13) ---
        if applied and final_subscription.status == SubscriptionStatus.CANCELADA:
            user = await self._users.get_by_id(user_id)
            if user:
                await self._notification.notify_cancellation(user, final_subscription)

        return final_subscription

    async def reactivate_subscription(self, subscription_id: uuid.UUID, user_id: uuid.UUID) -> Subscription:
        """Desfaz um cancelamento agendado (`cancel_at_period_end`) antes do
        fim do período — a assinatura segue ATIVA sem interrupção.

        Não confundir com `activate_subscription` (PENDENTE -> ATIVA, novo
        no PROMPT 05): este método sempre operou só sobre assinaturas já
        ATIVA, comportamento inalterado.
        """
        subscription = await self.get_subscription(subscription_id, user_id)
        if subscription.status != SubscriptionStatus.ATIVA:
            raise ConflictError("Esta assinatura não está agendada para cancelamento.")
        if not subscription.cancel_at_period_end:
            # Idempotente (ADR-021, opção (a) escolhida): trata "já reativada
            # por uma chamada concorrente" e "nunca foi agendada para
            # cancelamento" da mesma forma — sucesso sem-op — em vez de
            # ConflictError. Justificativa: o único jeito de distinguir os
            # dois casos seria checar SubscriptionHistory por uma entrada
            # REATIVADA muito recente (opção (b), mais complexa, não
            # escolhida); e, na prática, o frontend só habilita o botão
            # "reativar" quando cancel_at_period_end já é true, então uma
            # chamada real "nunca agendada" é essencialmente inalcançável
            # fora de um cliente malicioso/desatualizado — para esse caso,
            # devolver o estado atual (ATIVA, sem cancelamento agendado) já
            # é uma resposta correta, só não é um erro.
            return subscription

        async with UnitOfWork(self._session):
            applied = await self._subscriptions.compare_and_swap(
                subscription_id,
                expected={
                    "status": SubscriptionStatus.ATIVA,
                    "cancel_at_period_end": True,
                },
                values={"cancel_at_period_end": False},
            )
            if applied:
                subscription.cancel_at_period_end = False
                self._session.add(
                    SubscriptionHistory(
                        subscription_id=subscription.id,
                        from_plan_id=subscription.plan_id,
                        to_plan_id=subscription.plan_id,
                        from_status=SubscriptionStatus.ATIVA,
                        to_status=SubscriptionStatus.ATIVA,
                        reason=SubscriptionHistoryReason.REATIVADA,
                    )
                )
                await self._session.flush()

        # `applied is False`: outra chamada concorrente já reativou entre
        # a leitura e o CAS (ver ADR-019) — idempotente, mesmo padrão de
        # `cancel_subscription` acima.
        final_subscription = await self.get_subscription(subscription_id, user_id)

        # --- NOTIFICAÇÃO: Reativação (PROMPT 13) ---
        if applied:
            user = await self._users.get_by_id(user_id)
            if user:
                await self._notification.notify_reactivation(user, final_subscription)

        return final_subscription

    async def renew_subscription(
        self, subscription_id: uuid.UUID, user_id: uuid.UUID, payment_id: uuid.UUID
    ) -> Subscription:
        """Avança o período da assinatura após confirmação de pagamento
        (chamado por `PaymentService`, não diretamente por um endpoint).

        `payment_id` obrigatório (ADR-023, resolvendo o achado do ADR-022):
        o CAS de `current_period_end` sozinho protege contra duas
        chamadas **verdadeiramente simultâneas** (mesma leitura, uma
        vence), mas não contra uma segunda chamada cuja leitura acontece
        **depois** do commit da primeira — nesse caso ela lê o período já
        avançado como sua própria baseline e o CAS bate normalmente,
        produzindo um segundo avanço de período (ex.: reentrega de
        webhook, ou dois `Payment`s distintos para o mesmo evento lógico
        de renovação). `payment_id` é a chave que distingue "isto é uma
        nova renovação legítima" de "isto é o mesmo evento de novo": antes
        do CAS, checamos se este `payment_id` já gerou uma entrada de
        `SubscriptionHistory` para esta assinatura; se sim, é reentrega —
        no-op idempotente, sem tocar no período. O índice único parcial
        `ux_subscription_history_payment` (migration 0008) é o backstop de
        banco contra a janela entre esta checagem e o `INSERT`, para o
        caso (mais raro) de duas chamadas com o MESMO `payment_id`
        chegarem verdadeiramente juntas.

        `payment_id` obrigatoriamente referencia um `Payment` já existente
        (FK da migration 0008) — chamar este método com um `payment_id`
        que não corresponde a nenhum `Payment` real é erro do chamador, e
        deve estourar, não virar um no-op silencioso (achado desta sessão:
        ver ADR-023, correção pós-rerun de integração). Por isso o
        `except IntegrityError` abaixo inspeciona o `sqlstate` — só
        `unique_violation` (23505, o índice parcial) é tratado como
        backstop de corrida; qualquer outro `IntegrityError` (em especial
        `foreign_key_violation`, 23503) é relançado.

        Compartilha a implementação com `renew_subscription_system`
        (PROMPT 10, roadmap item 10) via `_renew_by_subscription` — a
        única diferença entre as duas é como a `Subscription` é resolvida
        (com ou sem checagem de posse por `user_id`); a lógica de CAS,
        idempotência por `payment_id` e histórico é idêntica.
        """
        subscription = await self.get_subscription(subscription_id, user_id)
        return await self._renew_by_subscription(subscription, payment_id, user_id=user_id)

    async def renew_subscription_system(
        self, subscription_id: uuid.UUID, payment_id: uuid.UUID
    ) -> Subscription:
        """Mesma renovação de `renew_subscription`, mas acionada pelo job
        de renovação automática (`app/workers/subscription_renewal.py`,
        PROMPT 10) ou por `PaymentService.process_webhook_event` quando um
        pagamento APROVADO chega para uma assinatura já ATIVA — não recebe
        `user_id` porque quem aciona não é uma requisição autenticada de
        usuário (mesmo padrão de `activate_subscription`/
        `mark_payment_failed`/`expire_subscription`).
        """
        subscription = await self._subscriptions.get_by_id_with_plan(subscription_id)
        if subscription is None:
            raise NotFoundError("Assinatura não encontrada.")
        return await self._renew_by_subscription(subscription, payment_id, user_id=None)

    async def _renew_by_subscription(
        self, subscription: Subscription, payment_id: uuid.UUID, user_id: uuid.UUID | None = None
    ) -> Subscription:
        """Corpo comum de `renew_subscription`/`renew_subscription_system`
        (PROMPT 10). Recebe a `Subscription` já resolvida pelo chamador —
        cada refetch interno (idempotência por `payment_id`, corrida
        perdida no CAS) usa `get_by_id_with_plan` (sem `user_id`), já que
        a posse/existência já foi validada uma vez antes de chegar aqui.
        """
        subscription_id = subscription.id
        if subscription.status != SubscriptionStatus.ATIVA:
            raise ConflictError("Apenas assinaturas ativas podem ser renovadas.")

        already_processed = await self._history.get_by_subscription_and_payment(
            subscription_id, payment_id
        )
        if already_processed is not None:
            # Idempotente: este payment_id já renovou esta assinatura —
            # reentrega do mesmo evento, não uma nova renovação.
            return subscription

        period_length = _PERIOD_LENGTH[subscription.plan.billing_period]
        old_period_end = subscription.current_period_end
        new_period_start = old_period_end
        new_period_end = old_period_end + period_length

        applied = False

        try:
            async with UnitOfWork(self._session):
                # `expected` inclui `current_period_end` (não só `status`)
                # porque o novo período é calculado a partir do período
                # *atual* lido acima, não de "agora" (diferente de
                # `activate_subscription`) — se outra renovação concorrente
                # verdadeiramente simultânea já avançou o período entre a
                # leitura e este CAS, gravar aqui cegamente duplicaria o
                # avanço em vez de perder a corrida (ver ADR-019). Isto
                # protege a corrida "mesma leitura, duas escritas"; a
                # checagem de `payment_id` acima protege a janela adicional
                # descrita no ADR-022 ("leitura depois do commit alheio").
                applied = await self._subscriptions.compare_and_swap(
                    subscription_id,
                    expected={
                        "status": SubscriptionStatus.ATIVA,
                        "current_period_end": old_period_end,
                    },
                    values={
                        "current_period_start": new_period_start,
                        "current_period_end": new_period_end,
                    },
                )
                if applied:
                    subscription.current_period_start = new_period_start
                    subscription.current_period_end = new_period_end
                    self._session.add(
                        SubscriptionHistory(
                            subscription_id=subscription.id,
                            from_plan_id=subscription.plan_id,
                            to_plan_id=subscription.plan_id,
                            from_status=SubscriptionStatus.ATIVA,
                            to_status=SubscriptionStatus.ATIVA,
                            reason=SubscriptionHistoryReason.RENOVADA,
                            payment_id=payment_id,
                        )
                    )
                    await self._session.flush()
        except IntegrityError as exc:
            # Backstop contra corrida real: outra chamada com o MESMO
            # payment_id venceu entre a checagem `already_processed` acima
            # e este INSERT (ex.: duas entregas do mesmo webhook
            # processadas por workers diferentes quase juntas). O índice
            # único parcial `ux_subscription_history_payment` rejeita o
            # segundo INSERT — idempotente, não um erro do chamador (mesmo
            # espírito de `create_subscription` acima, que também trata
            # `IntegrityError` como backstop de corrida, não como erro).
            #
            # CORREÇÃO (achado do rerun de integração desta sessão): o
            # `except` original capturava QUALQUER `IntegrityError`,
            # inclusive violação da FK `payment_id -> payments.id`
            # (23503) — um `payment_id` inválido/inexistente ficava
            # indistinguível de uma corrida legítima e virava um no-op
            # silencioso (nenhum `SubscriptionHistory` gravado, nenhum
            # erro reportado). Só `unique_violation` (23505 — o índice
            # parcial, a corrida que este backstop deve mesmo cobrir) é
            # tratado como idempotência; qualquer outro `IntegrityError`
            # é relançado, para não mascarar um `payment_id` errado como
            # sucesso.
            sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None)
            if sqlstate != "23505":
                raise
            current = await self._subscriptions.get_by_id_with_plan(subscription_id)
            return current if current is not None else subscription

        if not applied:
            # Perdeu a corrida (mesma leitura, duas escritas — ver acima):
            # outra renovação verdadeiramente concorrente já avançou o
            # período entre a leitura e o CAS. Idempotente — devolve o
            # período já avançado pela chamada vencedora em vez de
            # duplicar.
            current = await self._subscriptions.get_by_id_with_plan(subscription_id)
            return current if current is not None else subscription

        # --- NOTIFICAÇÃO: Renovação bem-sucedida (PROMPT 13) ---
        if user_id is not None:
            user = await self._users.get_by_id(user_id)
        else:
            user = await self._users.get_by_id(subscription.user_id)
        if user:
            await self._notification.notify_renewal_success(user, subscription)

        return subscription

    # ==================================================================== #
    # Upgrade / Downgrade / Pró-rata (PROMPT 12)                          #
    # ==================================================================== #

    def _calculate_prorated_amount(
        self,
        current_price_cents: int,
        new_price_cents: int,
        current_period_end: datetime,
        plan_duration_days: int,
        now: datetime | None = None,
    ) -> int:
        """Calcula o valor pró-rata da diferença entre planos.
        
        Retorna em centavos (int), arredondado para cima (ceil).
        """
        if now is None:
            now = _utcnow()
        
        if new_price_cents <= current_price_cents:
            return 0
        
        remaining_seconds = (current_period_end - now).total_seconds()
        if remaining_seconds <= 0:
            return 0
        
        total_seconds = plan_duration_days * 24 * 60 * 60
        prorated_fraction = remaining_seconds / total_seconds
        
        difference_cents = new_price_cents - current_price_cents
        prorated_amount_cents = difference_cents * prorated_fraction
        
        # Arredondar para cima (ceil) para evitar cobrar menos que o devido
        return math.ceil(prorated_amount_cents)

    async def _apply_plan_change(
        self,
        subscription: Subscription,
        new_plan: Plan,
        reason: SubscriptionHistoryReason,
        payment_id: uuid.UUID | None = None,
    ) -> Subscription:
        """Aplica a troca de plano, atualiza o período e registra histórico."""
        subscription_id = subscription.id
        old_plan_id = subscription.plan_id
        old_plan_name = subscription.plan.name  # Guardar para notificação
        
        # Se for upgrade, recalcula o período a partir de agora
        if reason == SubscriptionHistoryReason.UPGRADE:
            now = _utcnow()
            period_length = _PERIOD_LENGTH[new_plan.billing_period]
            new_period_start = now
            new_period_end = now + period_length
        else:
            # Downgrade ou troca sem cobrança: mantém o período atual
            new_period_start = subscription.current_period_start
            new_period_end = subscription.current_period_end

        applied = False

        async with UnitOfWork(self._session):
            applied = await self._subscriptions.compare_and_swap(
                subscription_id,
                expected={
                    "status": SubscriptionStatus.ATIVA,
                    "plan_id": old_plan_id,
                },
                values={
                    "plan_id": new_plan.id,
                    "current_period_start": new_period_start,
                    "current_period_end": new_period_end,
                    # Limpa qualquer downgrade agendado
                    "pending_plan_id": None,
                    "pending_plan_effective_at": None,
                },
            )
            if applied:
                subscription.plan_id = new_plan.id
                subscription.current_period_start = new_period_start
                subscription.current_period_end = new_period_end
                subscription.pending_plan_id = None
                subscription.pending_plan_effective_at = None
                
                self._session.add(
                    SubscriptionHistory(
                        subscription_id=subscription.id,
                        from_plan_id=old_plan_id,
                        to_plan_id=new_plan.id,
                        from_status=subscription.status,
                        to_status=subscription.status,
                        reason=reason,
                        payment_id=payment_id,
                    )
                )
                await self._session.flush()
        
        if not applied:
            current = await self._subscriptions.get_by_id_with_plan(subscription_id)
            return current if current is not None else subscription

        # --- NOTIFICAÇÃO: Mudança de plano (PROMPT 13) ---
        user = await self._users.get_by_id(subscription.user_id)
        if user:
            await self._notification.notify_plan_change(user, subscription, old_plan_name)

        return subscription

    async def _change_plan_upgrade(
        self,
        subscription: Subscription,
        new_plan: Plan,
        user_id: uuid.UUID,
    ) -> Subscription:
        """Upgrade: cobra a diferença pró-rata imediatamente."""
        
        # Upgrade sobrescreve a intenção de cancelar
        if subscription.cancel_at_period_end:
            async with UnitOfWork(self._session):
                subscription.cancel_at_period_end = False
                await self._session.flush()
        
        prorated_amount_cents = self._calculate_prorated_amount(
            current_price_cents=subscription.plan.price_cents,
            new_price_cents=new_plan.price_cents,
            current_period_end=subscription.current_period_end,
            plan_duration_days=_PERIOD_LENGTH[subscription.plan.billing_period].days,
        )
        
        if prorated_amount_cents < _MIN_PRORATED_AMOUNT_CENTS:
            # Não precisa cobrar (ex.: upgrade no último dia do período)
            return await self._apply_plan_change(
                subscription, new_plan, SubscriptionHistoryReason.UPGRADE
            )
        
        # Criar Payment para a diferença
        from app.services.billing.payment_service import PaymentService
        payment_service = PaymentService(self._session)
        payment = await payment_service.charge_prorated(
            subscription_id=subscription.id,
            amount_cents=prorated_amount_cents,
            description=f"Upgrade: {subscription.plan.name} → {new_plan.name} (pró-rata)",
        )
        
        if payment.status == PaymentStatus.APROVADO:
            return await self._apply_plan_change(
                subscription, new_plan, SubscriptionHistoryReason.UPGRADE, payment_id=payment.id
            )
        elif payment.status == PaymentStatus.PENDENTE:
            # Gateway assíncrono: aguardar confirmação via webhook
            # A assinatura permanece no plano atual até a confirmação
            # O PaymentService.process_webhook_event chamará _apply_plan_change
            # quando receber a confirmação
            return subscription
        else:
            # RECUSADO ou ESTORNADO
            raise ConflictError(
                f"O pagamento do upgrade não foi aprovado. Tente novamente. "
                f"Status: {payment.status.value}"
            )

    async def _change_plan_downgrade(
        self,
        subscription: Subscription,
        new_plan: Plan,
    ) -> Subscription:
        """Downgrade: agenda para o próximo ciclo de cobrança."""
        
        # Se já tem um downgrade agendado, substitui
        async with UnitOfWork(self._session):
            subscription.pending_plan_id = new_plan.id
            subscription.pending_plan_effective_at = subscription.current_period_end
            await self._session.flush()
            
            self._session.add(
                SubscriptionHistory(
                    subscription_id=subscription.id,
                    from_plan_id=subscription.plan_id,
                    to_plan_id=new_plan.id,
                    from_status=subscription.status,
                    to_status=subscription.status,
                    reason=SubscriptionHistoryReason.DOWNGRADE,
                )
            )
            await self._session.flush()
        
        return subscription

    async def change_plan(
        self,
        subscription_id: uuid.UUID,
        user_id: uuid.UUID,
        new_plan_id: uuid.UUID,
    ) -> Subscription:
        """Upgrade com cobrança imediata da diferença pró-rata,
        ou downgrade agendado para o próximo ciclo de cobrança."""
        
        subscription = await self.get_subscription(subscription_id, user_id)
        if subscription.status != SubscriptionStatus.ATIVA:
            raise ConflictError("Apenas assinaturas ativas podem trocar de plano.")
        
        new_plan = await self._plans.get_by_id(new_plan_id)
        if new_plan is None or not new_plan.is_active:
            raise NotFoundError("Plano não encontrado ou inativo.")
        if new_plan.id == subscription.plan_id:
            raise ConflictError("A assinatura já está neste plano.")
        
        # Se já tem um downgrade agendado, limpa
        if subscription.pending_plan_id is not None:
            async with UnitOfWork(self._session):
                subscription.pending_plan_id = None
                subscription.pending_plan_effective_at = None
                await self._session.flush()
        
        is_upgrade = new_plan.price_cents > subscription.plan.price_cents
        
        if is_upgrade:
            return await self._change_plan_upgrade(subscription, new_plan, user_id)
        else:
            return await self._change_plan_downgrade(subscription, new_plan)

    async def apply_pending_downgrade(self, subscription_id: uuid.UUID) -> Subscription:
        """Aplica um downgrade agendado, se houver e se a data já tiver chegado.
        
        Chamado pelo worker de renovação automática.
        """
        subscription = await self._subscriptions.get_by_id_with_plan(subscription_id)
        if subscription is None:
            raise NotFoundError("Assinatura não encontrada.")
        
        if subscription.pending_plan_id is None:
            return subscription
        
        now = _utcnow()
        if (subscription.pending_plan_effective_at is not None and
            subscription.pending_plan_effective_at > now):
            return subscription
        
        pending_plan = await self._plans.get_by_id(subscription.pending_plan_id)
        if pending_plan is None:
            # Plano foi deletado: limpa o agendamento
            async with UnitOfWork(self._session):
                subscription.pending_plan_id = None
                subscription.pending_plan_effective_at = None
                await self._session.flush()
            return subscription
        
        # Aplica a troca sem cobrança (downgrade)
        return await self._apply_plan_change(
            subscription, pending_plan, SubscriptionHistoryReason.DOWNGRADE
        )

    # ==================================================================== #
    # Dunning (PROMPT 11)                                                  #
    # ==================================================================== #

    async def mark_payment_failed(self, subscription_id: uuid.UUID) -> Subscription:
        """Chamado por `PaymentService` quando um pagamento é recusado ou
        estornado — não exige `user_id` porque quem aciona é o processamento
        de webhook, não uma requisição autenticada do usuário.

        O status de destino depende do status atual da assinatura
        (ver ADR-014):
        - PENDENTE (o pagamento que falhou era o primeiro, de ativação):
          vai direto para CANCELADA — a assinatura nunca chegou a existir
          de fato como um produto pago, não faz sentido tratá-la como
          "inadimplente" (que pressupõe ter sido paga antes).
        - ATIVA (falha de cobrança recorrente/renovação): vai para
          INADIMPLENTE.
        - Qualquer outro status (já INADIMPLENTE, CANCELADA, EXPIRADA):
          tratado como idempotente — retorna sem gravar nada. Antes desta
          sessão isso não era checado (qualquer status virava INADIMPLENTE
          incondicionalmente); nenhum teste existente exercitava essa
          origem, então a checagem é estritamente uma correção, não uma
          mudança de contrato observado (ver ADR-017).

        Corrida corrigida nesta sessão (roadmap item 7, ADR-017): a escrita
        agora é um `compare_and_swap_status` (`UPDATE ... WHERE status =
        <o status que foi lido>`) em vez de uma atribuição direta. Se duas
        entregas concorrentes do mesmo evento (ou dois eventos de falha
        diferentes) chegam aqui para a mesma assinatura, cada uma lê o
        mesmo `previous_status`, mas só a que gravar primeiro tem seu CAS
        aplicado — a outra recebe `False` (a linha já não bate mais o
        `WHERE`) e é tratada como reentrega idempotente: não grava uma
        segunda `SubscriptionHistory` para o mesmo evento. Este é o achado
        documentado em `docs/DECISIONS.md` ("Risco registrado — possível
        corrida em `mark_payment_failed`") e reproduzido por
        `TestMarkPaymentFailedConcurrencyFinding` — o teste foi atualizado
        nesta sessão para validar a correção (1 entrada de histórico, não
        mais 2) em vez de só documentar o achado.
        """
        subscription = await self._subscriptions.get_by_id(subscription_id)
        if subscription is None:
            raise NotFoundError("Assinatura não encontrada.")

        previous_status = subscription.status
        if previous_status not in (SubscriptionStatus.PENDENTE, SubscriptionStatus.ATIVA):
            # Já está num status terminal para fins de cobrança (ou já foi
            # processado por uma entrega concorrente que venceu a corrida
            # antes desta chamada sequer ler). Idempotente: nada a fazer.
            return subscription

        new_status = (
            SubscriptionStatus.CANCELADA
            if previous_status == SubscriptionStatus.PENDENTE
            else SubscriptionStatus.INADIMPLENTE
        )

        # PROMPT 11 (dunning): ao entrar em INADIMPLENTE a partir de ATIVA,
        # inicializa o ciclo de dunning (grava atomicamente no mesmo CAS que
        # a transição de status — mesmo raciocínio de `activate_subscription`
        # gravar o período junto com o CAS, em vez de um segundo UPDATE
        # incondicional que reabriria uma janela de corrida). Origem PENDENTE
        # vai para CANCELADA, não tem ciclo de dunning.
        cas_values: dict[str, object] = {"status": new_status}
        if new_status == SubscriptionStatus.INADIMPLENTE:
            now = _utcnow()
            cas_values["dunning_attempts"] = 0
            cas_values["dunning_next_retry_at"] = now + timedelta(
                days=settings.DUNNING_RETRY_INTERVAL_DAYS
            )
            cas_values["dunning_grace_period_ends_at"] = now + timedelta(
                days=settings.DUNNING_GRACE_PERIOD_DAYS
            )

        applied = False

        async with UnitOfWork(self._session):
            applied = await self._subscriptions.compare_and_swap(
                subscription_id,
                expected={"status": previous_status},
                values=cas_values,
            )
            if applied:
                subscription.status = new_status
                if new_status == SubscriptionStatus.INADIMPLENTE:
                    subscription.dunning_attempts = cas_values["dunning_attempts"]
                    subscription.dunning_next_retry_at = cas_values["dunning_next_retry_at"]
                    subscription.dunning_grace_period_ends_at = cas_values[
                        "dunning_grace_period_ends_at"
                    ]
                self._session.add(
                    SubscriptionHistory(
                        subscription_id=subscription.id,
                        from_plan_id=subscription.plan_id,
                        to_plan_id=subscription.plan_id,
                        from_status=previous_status,
                        to_status=new_status,
                        reason=SubscriptionHistoryReason.PAGAMENTO_FALHOU,
                    )
                )
                await self._session.flush()

        if not applied:
            # Perdeu a corrida: outra entrega concorrente já aplicou esta
            # transição entre a leitura acima e o CAS. Devolve o estado
            # atual em vez do objeto potencialmente desatualizado.
            current = await self._subscriptions.get_by_id(subscription_id)
            return current if current is not None else subscription

        # --- NOTIFICAÇÃO: Falha de pagamento (PROMPT 13) ---
        user = await self._users.get_by_id(subscription.user_id)
        if user and new_status == SubscriptionStatus.INADIMPLENTE:
            await self._notification.notify_payment_failed(user, subscription)
        elif user and new_status == SubscriptionStatus.CANCELADA:
            # Falha do pagamento inicial de ativação: já tem notificação de cancelamento
            # que será enviada pelo método cancel_subscription (não chamado aqui)
            pass

        return subscription

    async def record_dunning_retry_failure(self, subscription_id: uuid.UUID) -> Subscription:
        """Chamado pelo job de dunning (`app/workers/subscription_dunning.py`,
        PROMPT 11) quando uma tentativa de recobrança de uma assinatura
        INADIMPLENTE falha de novo. Permanece INADIMPLENTE (não muda de
        status) — só incrementa `dunning_attempts` e agenda a próxima
        tentativa (`dunning_next_retry_at`), sem tocar
        `dunning_grace_period_ends_at` (o grace period é fixo desde que a
        assinatura entrou em INADIMPLENTE, não se estende a cada retry).

        Se a tentativa que acabou de falhar já era a última permitida
        (`dunning_attempts + 1 >= DUNNING_MAX_RETRIES`), não agenda mais
        nenhum retry (`dunning_next_retry_at = None`) — a assinatura só sai
        de INADIMPLENTE quando o grace period vencer
        (`expire_from_dunning`, via `list_due_for_dunning_expiration`, que
        não depende de `dunning_next_retry_at`).

        CAS inclui `dunning_attempts` esperado (não só `status`): duas
        execuções concorrentes do job de dunning para a mesma assinatura
        (não deveria acontecer com `max_instances=1` no scheduler, mesmo
        raciocínio de `finalize_scheduled_cancellation`) não incrementam a
        contagem em duplicidade — quem perde o CAS devolve o estado atual
        em vez de sobrescrever `dunning_attempts` com um valor obsoleto.
        """
        subscription = await self._subscriptions.get_by_id(subscription_id)
        if subscription is None:
            raise NotFoundError("Assinatura não encontrada.")
        if subscription.status != SubscriptionStatus.INADIMPLENTE:
            # Idempotente: outra execução concorrente já tirou esta
            # assinatura de INADIMPLENTE (recuperada ou expirada) entre a
            # seleção do job e esta chamada — mesmo padrão dos demais
            # métodos deste service diante de corrida.
            return subscription

        previous_attempts = subscription.dunning_attempts
        new_attempts = previous_attempts + 1
        next_retry_at = (
            None
            if new_attempts >= settings.DUNNING_MAX_RETRIES
            else _utcnow() + timedelta(days=settings.DUNNING_RETRY_INTERVAL_DAYS)
        )

        applied = False

        async with UnitOfWork(self._session):
            applied = await self._subscriptions.compare_and_swap(
                subscription_id,
                expected={
                    "status": SubscriptionStatus.INADIMPLENTE,
                    "dunning_attempts": previous_attempts,
                },
                values={
                    "dunning_attempts": new_attempts,
                    "dunning_next_retry_at": next_retry_at,
                },
            )
            if applied:
                subscription.dunning_attempts = new_attempts
                subscription.dunning_next_retry_at = next_retry_at
                self._session.add(
                    SubscriptionHistory(
                        subscription_id=subscription.id,
                        from_plan_id=subscription.plan_id,
                        to_plan_id=subscription.plan_id,
                        from_status=SubscriptionStatus.INADIMPLENTE,
                        to_status=SubscriptionStatus.INADIMPLENTE,
                        reason=SubscriptionHistoryReason.RETRY_DUNNING_FALHOU,
                    )
                )
                await self._session.flush()

        if not applied:
            current = await self._subscriptions.get_by_id(subscription_id)
            return current if current is not None else subscription

        # --- NOTIFICAÇÃO: Retry de dunning falhou (PROMPT 13) ---
        user = await self._users.get_by_id(subscription.user_id)
        if user:
            await self._notification.notify_dunning_retry_failed(user, subscription)

        return subscription

    async def recover_from_dunning(
        self, subscription_id: uuid.UUID, payment_id: uuid.UUID
    ) -> Subscription:
        """Uma tentativa de recobrança de uma assinatura INADIMPLENTE foi
        aprovada — volta para ATIVA e avança o período corrente (mesmo
        efeito de uma renovação normal: a cobrança que acabou de ser
        aprovada paga exatamente o período que estava em aberto). Chamado
        pelo job de dunning (aplicação direta, mesmo padrão de
        `renew_subscription_system` — ver docstring de
        `app/workers/subscription_dunning.py`) e por
        `PaymentService.process_webhook_event` quando um evento APROVADO
        chega para uma assinatura já INADIMPLENTE (caminho de um provedor
        assíncrono real, ainda não implementado — roadmap item 6).

        Idempotência por `payment_id`, mesmo mecanismo de
        `_renew_by_subscription` (ADR-023): reentrega do mesmo evento não
        avança o período nem grava uma segunda `SubscriptionHistory`. Ao
        contrário de `_renew_by_subscription`, este método também limpa os
        campos de dunning (`dunning_attempts=0`,
        `dunning_next_retry_at=None`, `dunning_grace_period_ends_at=None`)
        — o próximo ciclo de inadimplência, se houver, começa do zero.
        """
        subscription = await self._subscriptions.get_by_id_with_plan(subscription_id)
        if subscription is None:
            raise NotFoundError("Assinatura não encontrada.")
        if subscription.status == SubscriptionStatus.ATIVA:
            # Idempotente: outra execução concorrente já recuperou esta
            # assinatura entre a leitura do chamador e agora.
            return subscription
        if subscription.status != SubscriptionStatus.INADIMPLENTE:
            raise ConflictError("Apenas assinaturas inadimplentes podem ser recuperadas.")

        already_processed = await self._history.get_by_subscription_and_payment(
            subscription_id, payment_id
        )
        if already_processed is not None:
            # Idempotente: este payment_id já recuperou esta assinatura —
            # reentrega do mesmo evento, mesmo padrão de
            # `_renew_by_subscription`.
            return subscription

        period_length = _PERIOD_LENGTH[subscription.plan.billing_period]
        now = _utcnow()
        new_period_start = now
        new_period_end = now + period_length

        applied = False

        try:
            async with UnitOfWork(self._session):
                applied = await self._subscriptions.compare_and_swap(
                    subscription_id,
                    expected={"status": SubscriptionStatus.INADIMPLENTE},
                    values={
                        "status": SubscriptionStatus.ATIVA,
                        "current_period_start": new_period_start,
                        "current_period_end": new_period_end,
                        "dunning_attempts": 0,
                        "dunning_next_retry_at": None,
                        "dunning_grace_period_ends_at": None,
                    },
                )
                if applied:
                    subscription.status = SubscriptionStatus.ATIVA
                    subscription.current_period_start = new_period_start
                    subscription.current_period_end = new_period_end
                    subscription.dunning_attempts = 0
                    subscription.dunning_next_retry_at = None
                    subscription.dunning_grace_period_ends_at = None
                    self._session.add(
                        SubscriptionHistory(
                            subscription_id=subscription.id,
                            from_plan_id=subscription.plan_id,
                            to_plan_id=subscription.plan_id,
                            from_status=SubscriptionStatus.INADIMPLENTE,
                            to_status=SubscriptionStatus.ATIVA,
                            reason=SubscriptionHistoryReason.RECUPERADA_DUNNING,
                            payment_id=payment_id,
                        )
                    )
                    await self._session.flush()
        except IntegrityError as exc:
            # Backstop de corrida real, mesmo padrão de
            # `_renew_by_subscription`/ADR-023: só `unique_violation`
            # (23505, o índice único parcial de `payment_id`) é tratado
            # como idempotência; qualquer outro `IntegrityError` (ex.: FK
            # de `payment_id` inválido) é relançado.
            sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None)
            if sqlstate != "23505":
                raise
            current = await self._subscriptions.get_by_id_with_plan(subscription_id)
            return current if current is not None else subscription

        if not applied:
            current = await self._subscriptions.get_by_id_with_plan(subscription_id)
            return current if current is not None else subscription

        # --- NOTIFICAÇÃO: Recuperação de dunning (PROMPT 13) ---
        user = await self._users.get_by_id(subscription.user_id)
        if user:
            await self._notification.notify_dunning_recovered(user, subscription)

        return subscription

    async def expire_from_dunning(self, subscription_id: uuid.UUID) -> Subscription:
        """Chamado pelo job de dunning quando o grace period de uma
        assinatura INADIMPLENTE termina sem recuperação
        (`list_due_for_dunning_expiration`) — move para EXPIRADA,
        independentemente de quantas tentativas de retry ainda restariam.

        Distinto de `expire_subscription` (ATIVA -> EXPIRADA, período
        terminou sem renovação — roadmap item 7/18): este é
        INADIMPLENTE -> EXPIRADA, fim do grace period de dunning. Mesmo
        `SubscriptionHistoryReason.EXPIRADA` é reaproveitado para os dois
        casos (a distinção fica em `from_status`, já registrado em toda
        entrada de histórico) — não crio uma razão nova só para diferenciar
        a origem, mesmo espírito de reaproveitar `PAGAMENTO_FALHOU` para
        ATIVA->INADIMPLENTE e PENDENTE->CANCELADA.
        """
        subscription = await self._subscriptions.get_by_id(subscription_id)
        if subscription is None:
            raise NotFoundError("Assinatura não encontrada.")
        if subscription.status == SubscriptionStatus.EXPIRADA:
            # Idempotente: outra execução concorrente já expirou esta
            # assinatura entre a seleção do job e esta chamada.
            return subscription
        if subscription.status != SubscriptionStatus.INADIMPLENTE:
            raise ConflictError("Apenas assinaturas inadimplentes podem expirar por dunning.")

        applied = False

        async with UnitOfWork(self._session):
            applied = await self._subscriptions.compare_and_swap(
                subscription_id,
                expected={"status": SubscriptionStatus.INADIMPLENTE},
                values={
                    "status": SubscriptionStatus.EXPIRADA,
                    "dunning_next_retry_at": None,
                },
            )
            if applied:
                subscription.status = SubscriptionStatus.EXPIRADA
                subscription.dunning_next_retry_at = None
                self._session.add(
                    SubscriptionHistory(
                        subscription_id=subscription.id,
                        from_plan_id=subscription.plan_id,
                        to_plan_id=subscription.plan_id,
                        from_status=SubscriptionStatus.INADIMPLENTE,
                        to_status=SubscriptionStatus.EXPIRADA,
                        reason=SubscriptionHistoryReason.EXPIRADA,
                    )
                )
                await self._session.flush()

        if not applied:
            current = await self._subscriptions.get_by_id(subscription_id)
            return current if current is not None else subscription

        # --- NOTIFICAÇÃO: Expiração por dunning (PROMPT 13) ---
        user = await self._users.get_by_id(subscription.user_id)
        if user:
            await self._notification.notify_dunning_expired(user, subscription)

        return subscription

    async def expire_subscription(self, subscription_id: uuid.UUID) -> Subscription:
        """Chamado por um job agendado (fora do escopo desta etapa) quando o
        período termina sem renovação.

        Corrida corrigida nesta sessão (roadmap item 7, ADR-018): ao
        contrário das demais escritas de `Subscription` fora do caminho de
        webhook (`cancel_subscription`, `change_plan`, `renew_subscription`
        — não tratadas nesta sessão, ver ADR-018 "Não decidido/implementado
        nesta sessão"), esta é acionada por um job agendado, e
        `PROJECT_STATE.md` §16 já registra como pendência "evitar jobs
        duplicados em múltiplas instâncias" antes de escalar a API
        horizontalmente — ou seja, o risco de duas execuções concorrentes
        (duas instâncias do scheduler, ou dois disparos do mesmo job por
        alguma falha de agendamento) não é hipotético do mesmo jeito que
        para as escritas disparadas por request autenticada de usuário.
        Usa o mesmo `compare_and_swap_status` de `mark_payment_failed`/
        `activate_subscription`: quem perde o CAS recebe o estado atual em
        vez de levantar `ConflictError`, e não duplica `SubscriptionHistory`.
        """
        subscription = await self._subscriptions.get_by_id(subscription_id)
        if subscription is None:
            raise NotFoundError("Assinatura não encontrada.")
        if subscription.status == SubscriptionStatus.EXPIRADA:
            # Idempotente: outra execução concorrente do job (duas instâncias do
            # scheduler, ou dois disparos do mesmo job) já expirou esta assinatura
            # entre esta leitura e agora — mesmo padrão de mark_payment_failed
            # (ADR-017). Achado real via teste de concorrência contra Postgres
            # (ADR-020); o dublê em memória nunca reproduzia esta janela porque
            # não tem I/O real entre a leitura e o CAS.
            return subscription
        if subscription.status != SubscriptionStatus.ATIVA:
            raise ConflictError("Apenas assinaturas ativas podem expirar.")

        async with UnitOfWork(self._session):
            applied = await self._subscriptions.compare_and_swap_status(
                subscription_id,
                expected_status=SubscriptionStatus.ATIVA,
                new_status=SubscriptionStatus.EXPIRADA,
            )
            if applied:
                subscription.status = SubscriptionStatus.EXPIRADA
                self._session.add(
                    SubscriptionHistory(
                        subscription_id=subscription.id,
                        from_plan_id=subscription.plan_id,
                        to_plan_id=subscription.plan_id,
                        from_status=SubscriptionStatus.ATIVA,
                        to_status=SubscriptionStatus.EXPIRADA,
                        reason=SubscriptionHistoryReason.EXPIRADA,
                    )
                )
                await self._session.flush()

        if not applied:
            # Perdeu a corrida: outra execução concorrente do job já
            # expirou esta assinatura entre a leitura acima e o CAS.
            current = await self._subscriptions.get_by_id(subscription_id)
            return current if current is not None else subscription

        return subscription

    async def finalize_scheduled_cancellation(self, subscription_id: uuid.UUID) -> Subscription:
        """Efetiva um cancelamento agendado (`cancel_subscription` com
        `immediately=False`, `cancel_at_period_end=True`) cujo período já
        terminou — chamado pelo job de renovação automática
        (`app/workers/subscription_renewal.py`, PROMPT 10), nunca por uma
        requisição autenticada de usuário (por isso não recebe `user_id`,
        mesmo padrão de `expire_subscription`/`renew_subscription_system`).

        Não cobra: uma assinatura marcada para cancelar ao fim do período
        não deve gerar uma nova tentativa de cobrança neste momento — é
        exatamente o requisito "não cobrar cancelada/expirada" do
        PROMPT 10 aplicado ao caso "cancelamento agendado que acabou de
        vencer" (distinto de uma assinatura já CANCELADA/EXPIRADA, que
        `list_due_for_renewal`/`list_scheduled_cancellations_due` já nem
        selecionam).

        Mesmo padrão de CAS + idempotência de `expire_subscription`: quem
        perde a corrida (duas execuções concorrentes do job — não deveria
        acontecer com `max_instances=1` no scheduler, mas o guard custa
        pouco e seguiria correto mesmo assim) recebe o estado atual em vez
        de duplicar `SubscriptionHistory`.
        """
        subscription = await self._subscriptions.get_by_id_with_plan(subscription_id)
        if subscription is None:
            raise NotFoundError("Assinatura não encontrada.")
        if subscription.status == SubscriptionStatus.CANCELADA:
            # Idempotente: outra execução (concorrente, ou reentrega do
            # mesmo job) já efetivou este cancelamento agendado.
            return subscription
        if subscription.status != SubscriptionStatus.ATIVA or not subscription.cancel_at_period_end:
            raise ConflictError("Esta assinatura não está agendada para cancelamento.")

        applied = False

        async with UnitOfWork(self._session):
            applied = await self._subscriptions.compare_and_swap(
                subscription_id,
                expected={
                    "status": SubscriptionStatus.ATIVA,
                    "cancel_at_period_end": True,
                },
                values={"status": SubscriptionStatus.CANCELADA},
            )
            if applied:
                subscription.status = SubscriptionStatus.CANCELADA
                self._session.add(
                    SubscriptionHistory(
                        subscription_id=subscription.id,
                        from_plan_id=subscription.plan_id,
                        to_plan_id=subscription.plan_id,
                        from_status=SubscriptionStatus.ATIVA,
                        to_status=SubscriptionStatus.CANCELADA,
                        reason=SubscriptionHistoryReason.CANCELADA,
                    )
                )
                await self._session.flush()

        if not applied:
            current = await self._subscriptions.get_by_id_with_plan(subscription_id)
            return current if current is not None else subscription

        # --- NOTIFICAÇÃO: Cancelamento (já enviada por cancel_subscription,
        # mas se o cancelamento foi agendado e só efetivado agora, o e-mail
        # já foi enviado no momento do agendamento. Não enviar novamente.
        # A notificação de cancelamento é enviada em cancel_subscription. ---

        return subscription


def _utcnow() -> datetime:
    return datetime.now(UTC)