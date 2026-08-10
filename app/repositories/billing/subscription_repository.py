"""Repositório de acesso a dados de `Subscription`.

`get_active_by_user` é a query mais executada do módulo — roda a cada
verificação de `FeatureGateService` (potencialmente em todo request de
outros contextos), por isso já carrega o plano com suas features via
`selectinload` (evita N+1 no gate) e se apoia no índice
`ix_subscriptions_status`/`ix_subscriptions_user_id` já existentes.
"""

import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from app.models.billing.plan import Plan
from app.models.billing.plan_feature import PlanFeature
from app.models.billing.subscription import Subscription
from app.models.enums import SubscriptionStatus
from app.repositories.base import BaseRepository

_WITH_PLAN = selectinload(Subscription.plan).selectinload(Plan.plan_features).selectinload(
    PlanFeature.feature
)
_WITH_PLAN_AND_HISTORY = (_WITH_PLAN, selectinload(Subscription.history))


class SubscriptionRepository(BaseRepository[Subscription]):
    model = Subscription

    async def get_active_by_user(self, user_id: uuid.UUID) -> Subscription | None:
        """Assinatura ATIVA do usuário, se houver.

        `None` significa "sem assinatura paga" — o usuário está no plano
        FREE por convenção (nunca há linha em `subscriptions` para FREE).
        O índice único parcial `ux_subscriptions_one_active_per_user`
        (migration 0005) garante que este resultado é sempre 0 ou 1 linha.
        """
        stmt = (
            select(Subscription)
            .where(
                Subscription.user_id == user_id,
                Subscription.status == SubscriptionStatus.ATIVA,
            )
            .options(_WITH_PLAN)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_pending_by_user(self, user_id: uuid.UUID) -> Subscription | None:
        """Assinatura PENDENTE do usuário, se houver (PROMPT 05).

        Usada por `SubscriptionService.create_subscription` para impedir
        que o mesmo usuário acumule várias assinaturas aguardando
        pagamento. Diferente de `get_active_by_user`, não há índice único
        parcial no banco cobrindo PENDENTE — a checagem aqui é só
        aplicativa (ver ADR-014, pendência registrada). Se dois requests
        concorrentes criarem PENDENTE ao mesmo tempo, nenhum backstop de
        `IntegrityError` os impede (diferente do caso ATIVA).
        """
        stmt = (
            select(Subscription)
            .where(
                Subscription.user_id == user_id,
                Subscription.status == SubscriptionStatus.PENDENTE,
            )
            .options(_WITH_PLAN)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id_with_plan(self, subscription_id: uuid.UUID) -> Subscription | None:
        """Busca por id (sem exigir `user_id`), com o plano e suas features
        já carregados — mesmo `selectinload` de `get_active_by_user`. Usada
        por `PaymentService.charge_subscription` e por
        `SubscriptionService.activate_subscription`, que já resolveram a
        posse/identidade da assinatura antes de chamar isto (não é um
        método de leitura exposta diretamente a partir de um endpoint
        escopado ao usuário).
        """
        stmt = select(Subscription).where(Subscription.id == subscription_id).options(_WITH_PLAN)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_owned(
        self, subscription_id: uuid.UUID, user_id: uuid.UUID
    ) -> Subscription | None:
        """Busca por id, restrita ao dono — usada antes de cancelar/alterar."""
        stmt = (
            select(Subscription)
            .where(Subscription.id == subscription_id, Subscription.user_id == user_id)
            .options(*_WITH_PLAN_AND_HISTORY)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_user(self, user_id: uuid.UUID) -> list[Subscription]:
        """Histórico completo de assinaturas do usuário (ativas, canceladas,
        expiradas), mais recente primeiro. Volume baixo por usuário — sem
        paginação cursor-based, mesmo raciocínio de `DisciplineRepository`.
        """
        stmt = (
            select(Subscription)
            .where(Subscription.user_id == user_id)
            .options(_WITH_PLAN)
            .order_by(Subscription.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().unique().all())

    async def list_due_for_renewal(self, now: datetime) -> list[Subscription]:
        """Assinaturas ATIVA, não agendadas para cancelamento
        (`cancel_at_period_end=False`), cujo período corrente já terminou —
        elegíveis para o job de renovação automática cobrar (PROMPT 10).

        Não inclui PENDENTE/CANCELADA/INADIMPLENTE/EXPIRADA nem assinaturas
        agendadas para cancelar (ver `list_scheduled_cancellations_due`) —
        cobrar qualquer uma dessas violaria o requisito "não cobrar
        cancelada/expirada" do PROMPT 10.
        """
        stmt = (
            select(Subscription)
            .where(
                Subscription.status == SubscriptionStatus.ATIVA,
                Subscription.cancel_at_period_end.is_(False),
                Subscription.current_period_end <= now,
            )
            .options(_WITH_PLAN)
            .order_by(Subscription.current_period_end.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().unique().all())

    async def list_scheduled_cancellations_due(self, now: datetime) -> list[Subscription]:
        """Assinaturas ATIVA agendadas para cancelar ao fim do período
        (`cancel_subscription` com `immediately=False`) cujo período já
        terminou — elegíveis para o job efetivar o cancelamento
        (`SubscriptionService.finalize_scheduled_cancellation`, PROMPT 10)
        sem gerar uma nova tentativa de cobrança.
        """
        stmt = (
            select(Subscription)
            .where(
                Subscription.status == SubscriptionStatus.ATIVA,
                Subscription.cancel_at_period_end.is_(True),
                Subscription.current_period_end <= now,
            )
            .options(_WITH_PLAN)
            .order_by(Subscription.current_period_end.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().unique().all())

    async def list_due_for_dunning_retry(
        self, now: datetime, *, max_attempts: int
    ) -> list[Subscription]:
        """Assinaturas INADIMPLENTE com uma tentativa de recobrança elegível
        agora — usadas pelo job de dunning (PROMPT 11) para tentar cobrar de
        novo. `max_attempts` é responsabilidade do chamador (config de
        negócio, não do repositório — mesmo raciocínio de `now` ser passado
        de fora): só assinaturas com `dunning_attempts < max_attempts`
        entram na seleção; ao atingir o limite, a assinatura só volta a ser
        tocada por `list_due_for_dunning_expiration` quando o grace period
        vencer.

        `dunning_next_retry_at IS NOT NULL` exclui assinaturas cujo ciclo de
        dunning nunca foi inicializado (dado herdado de antes da migration
        0009, ou qualquer estado inconsistente) — não tenta adivinhar uma
        data de retry para elas.
        """
        stmt = (
            select(Subscription)
            .where(
                Subscription.status == SubscriptionStatus.INADIMPLENTE,
                Subscription.dunning_attempts < max_attempts,
                Subscription.dunning_next_retry_at.is_not(None),
                Subscription.dunning_next_retry_at <= now,
            )
            .options(_WITH_PLAN)
            .order_by(Subscription.dunning_next_retry_at.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().unique().all())

    async def list_due_for_dunning_expiration(self, now: datetime) -> list[Subscription]:
        """Assinaturas INADIMPLENTE cujo grace period já terminou — elegíveis
        para o job de dunning mover para EXPIRADA (PROMPT 11), independente
        de quantas tentativas de retry ainda restariam.

        `dunning_grace_period_ends_at IS NOT NULL` mesma razão do método
        acima: dado herdado de antes da migration 0009 nunca expira
        automaticamente por este caminho.
        """
        stmt = (
            select(Subscription)
            .where(
                Subscription.status == SubscriptionStatus.INADIMPLENTE,
                Subscription.dunning_grace_period_ends_at.is_not(None),
                Subscription.dunning_grace_period_ends_at <= now,
            )
            .options(_WITH_PLAN)
            .order_by(Subscription.dunning_grace_period_ends_at.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().unique().all())

    async def compare_and_swap(
        self,
        subscription_id: uuid.UUID,
        *,
        expected: dict[str, object],
        values: dict[str, object],
    ) -> bool:
        """Generalização de `compare_and_swap_status` (ADR-019) para
        cobrir escritas de `Subscription` que não são *apenas* uma
        transição de status: `expected` é um dicionário arbitrário de
        colunas/valores que devem bater no banco para o `UPDATE` se
        aplicar (sempre inclui `id`, adicionado aqui automaticamente —
        quem chama não precisa repetir), `values` é o que será gravado.

        Mesmo raciocínio de `UPDATE ... WHERE ...` sob READ COMMITTED já
        documentado em `compare_and_swap_status` (mantido abaixo como
        atalho para o caso comum de CAS só-de-status): a segunda transação
        concorrente bloqueia no lock de linha, reavalia o `WHERE` contra o
        valor já commitado pela primeira, e afeta 0 linhas se qualquer
        coluna de `expected` não bater mais — não só `status`.

        Existe porque `cancel_subscription`, `reactivate_subscription`,
        `renew_subscription` e `change_plan` (ADR-018, "Não decidido/
        implementado nesta sessão") comparam/gravam colunas diferentes
        cada um (`cancel_at_period_end`, `current_period_start`/
        `current_period_end` a partir do período *atual* não de "agora",
        `plan_id`) — parâmetros nomeados fixos não davam conta sem um
        método por escrita. Não atualiza o objeto ORM em memória; mesma
        responsabilidade do chamador que `compare_and_swap_status`.
        """
        conditions = [Subscription.id == subscription_id]
        for column_name, expected_value in expected.items():
            conditions.append(getattr(Subscription, column_name) == expected_value)
        stmt = update(Subscription).where(*conditions).values(**values)
        result = await self.session.execute(stmt)
        return result.rowcount == 1

    async def compare_and_swap_status(
        self,
        subscription_id: uuid.UUID,
        *,
        expected_status: SubscriptionStatus,
        new_status: SubscriptionStatus,
        period_start: datetime | None = None,
        period_end: datetime | None = None,
    ) -> bool:
        """Grava `new_status` somente se o status atual em banco ainda for
        `expected_status` (roadmap item 7 — concorrência real de webhook,
        ver ADR-017 e ADR-018).

        Desde o ADR-019, é um atalho fino sobre `compare_and_swap` para o
        caso comum de CAS só-de-status (usado por `mark_payment_failed`,
        `activate_subscription`, `expire_subscription`) — ver o docstring
        de `compare_and_swap` para o raciocínio completo de por que o
        `UPDATE ... WHERE` condicional é suficiente sob READ COMMITTED,
        sem precisar de `SELECT ... FOR UPDATE` nem de SERIALIZABLE.

        `period_start`/`period_end` são opcionais e, quando informados,
        entram no mesmo `UPDATE` condicional (análogo ao `paid_at`
        opcional de `PaymentRepository.compare_and_swap_status`) — usado
        por `SubscriptionService.activate_subscription` (ADR-018) para
        gravar o período real de cobrança atomicamente com a transição de
        status, em vez de um segundo `UPDATE` incondicional separado que
        reabriria uma janela de corrida entre os dois passos.

        Não atualiza o objeto ORM já carregado em memória — quem chama é
        responsável por refletir os novos valores no objeto quando o
        retorno for `True` (ver `SubscriptionService.mark_payment_failed`,
        `activate_subscription`, `expire_subscription`).
        """
        values: dict[str, object] = {"status": new_status}
        if period_start is not None:
            values["current_period_start"] = period_start
        if period_end is not None:
            values["current_period_end"] = period_end
        return await self.compare_and_swap(
            subscription_id,
            expected={"status": expected_status},
            values=values,
        )