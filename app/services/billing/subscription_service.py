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

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.database.uow import UnitOfWork
from app.models.billing.subscription import Subscription
from app.models.billing.subscription_history import SubscriptionHistory
from app.models.enums import BillingPeriod, SubscriptionHistoryReason, SubscriptionStatus
from app.repositories.billing.plan_repository import PlanRepository
from app.repositories.billing.subscription_history_repository import SubscriptionHistoryRepository
from app.repositories.billing.subscription_repository import SubscriptionRepository

_PERIOD_LENGTH: dict[BillingPeriod, timedelta] = {
    BillingPeriod.MENSAL: timedelta(days=30),
    BillingPeriod.SEMESTRAL: timedelta(days=182),
    BillingPeriod.ANUAL: timedelta(days=365),
}


class SubscriptionService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._subscriptions = SubscriptionRepository(session)
        self._plans = PlanRepository(session)
        self._history = SubscriptionHistoryRepository(session)

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
        return await self.get_subscription(subscription_id, user_id)

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
        return await self.get_subscription(subscription_id, user_id)

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
        """
        subscription = await self.get_subscription(subscription_id, user_id)
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
            return await self.get_subscription(subscription_id, user_id)

        if not applied:
            # Perdeu a corrida (mesma leitura, duas escritas — ver acima):
            # outra renovação verdadeiramente concorrente já avançou o
            # período entre a leitura e o CAS. Idempotente — devolve o
            # período já avançado pela chamada vencedora em vez de
            # duplicar.
            current = await self.get_subscription(subscription_id, user_id)
            return current

        return subscription

    async def change_plan(
        self, subscription_id: uuid.UUID, user_id: uuid.UUID, new_plan_id: uuid.UUID
    ) -> Subscription:
        """Upgrade ou downgrade — decidido automaticamente comparando
        `price_cents` do plano atual com o novo.

        ADR-023 (análise do achado do ADR-022 aplicada a `change_plan`):
        ao contrário de `renew_subscription`, a duplicação real descrita
        no ADR-022 **não se materializa** aqui sem mudança de código,
        porque duas proteções já existentes cobrem os dois sub-casos:

        1. Duas chamadas para o MESMO plano-alvo, verdadeiramente
           concorrentes (mesma leitura): o `CAS` abaixo (`expected` inclui
           `plan_id`) garante que só uma escreve — a outra perde o CAS e
           devolve o estado atual, sem duplicar `SubscriptionHistory`
           (mesmo padrão de `renew_subscription`/ADR-019).
        2. Duas chamadas para o MESMO plano-alvo, sequenciais (a segunda
           lê **depois** do commit da primeira, cenário do ADR-022): a
           segunda já enxerga `subscription.plan_id == new_plan.id` e cai
           no guard `raise ConflictError("A assinatura já está neste
           plano.")` logo abaixo — falha explícita, não duplicação
           silenciosa.

        O único caso não coberto — uma segunda chamada para um plano-alvo
        **diferente** do último aplicado, chegando logo em seguida — não é
        tecnicamente distinguível de uma correção legítima do usuário
        ("errei, quero o outro plano") sem uma chave de evento que o
        endpoint hoje não recebe (`idempotency_key`, opção (b) do ADR-022,
        que exigiria mudar o contrato do endpoint — fora do escopo desta
        sessão). Por isso nenhum código novo foi adicionado aqui: as
        proteções existentes já eliminam o risco financeiro de duplicação
        que o ADR-022 levantou para `change_plan`; o que resta é uma
        decisão de produto/UX (bloquear trocas em sequência rápida?), não
        um bug de concorrência. Ver ADR-023 para o raciocínio completo.
        """
        subscription = await self.get_subscription(subscription_id, user_id)
        if subscription.status != SubscriptionStatus.ATIVA:
            raise ConflictError("Apenas assinaturas ativas podem trocar de plano.")

        new_plan = await self._plans.get_by_id(new_plan_id)
        if new_plan is None or not new_plan.is_active:
            raise NotFoundError("Plano não encontrado ou inativo.")
        if new_plan.id == subscription.plan_id:
            raise ConflictError("A assinatura já está neste plano.")

        reason = (
            SubscriptionHistoryReason.UPGRADE
            if new_plan.price_cents > subscription.plan.price_cents
            else SubscriptionHistoryReason.DOWNGRADE
        )
        old_plan_id = subscription.plan_id

        async with UnitOfWork(self._session):
            # `expected` inclui `plan_id` (não só `status`): duas trocas
            # de plano concorrentes para a mesma assinatura devem deixar
            # só a primeira vencer — a segunda, se recalculada contra o
            # `old_plan_id` já obsoleto, perde o CAS em vez de sobrescrever
            # a troca já aplicada (ver ADR-019).
            applied = await self._subscriptions.compare_and_swap(
                subscription_id,
                expected={
                    "status": SubscriptionStatus.ATIVA,
                    "plan_id": old_plan_id,
                },
                values={"plan_id": new_plan.id},
            )
            if applied:
                subscription.plan_id = new_plan.id
                self._session.add(
                    SubscriptionHistory(
                        subscription_id=subscription.id,
                        from_plan_id=old_plan_id,
                        to_plan_id=new_plan.id,
                        from_status=SubscriptionStatus.ATIVA,
                        to_status=SubscriptionStatus.ATIVA,
                        reason=reason,
                    )
                )
                await self._session.flush()

        # `applied is False`: outra troca de plano concorrente já mudou
        # `plan_id` entre a leitura e o CAS — idempotente, devolve o plano
        # já gravado pela chamada vencedora em vez de duplicar histórico.
        return await self.get_subscription(subscription_id, user_id)

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

        async with UnitOfWork(self._session):
            applied = await self._subscriptions.compare_and_swap_status(
                subscription_id, expected_status=previous_status, new_status=new_status
            )
            if applied:
                subscription.status = new_status
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


def _utcnow() -> datetime:
    return datetime.now(UTC)