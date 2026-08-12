# scripts/grant_premium_access.py
"""
Script para conceder acesso premium a um usuário específico.
Uso: poetry run python scripts/grant_premium_access.py luizfer.12321@gmail.com
"""

import asyncio
import sys
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.database.session import AsyncSessionFactory
from app.models.billing.plan import Plan
from app.models.billing.subscription import Subscription
from app.models.billing.subscription_history import SubscriptionHistory
from app.models.enums import BillingPeriod, SubscriptionStatus, SubscriptionHistoryReason
from app.models.identity.user import User


async def grant_premium_access(email: str):
    async with AsyncSessionFactory() as session:
        # 1. Buscar o usuário
        user_result = await session.execute(
            select(User).where(User.email == email)
        )
        user = user_result.scalar_one_or_none()
        if not user:
            print(f"❌ Usuário não encontrado: {email}")
            return False

        print(f"✅ Usuário encontrado: {user.email} (ID: {user.id})")

        # 2. Buscar o plano PRO
        plan_result = await session.execute(
            select(Plan).where(Plan.slug == "pro")
        )
        plan = plan_result.scalar_one_or_none()
        if not plan:
            print("❌ Plano PRO não encontrado. Execute seed_test_data.py primeiro.")
            return False

        print(f"✅ Plano PRO encontrado: {plan.name} (ID: {plan.id})")

        # 3. Verificar se já tem assinatura ativa
        existing = await session.execute(
            select(Subscription).where(
                Subscription.user_id == user.id,
                Subscription.status == SubscriptionStatus.ATIVA
            )
        )
        if existing.scalar_one_or_none():
            print("⚠️ Usuário já possui assinatura ativa.")
            return True

        # 4. Remover assinaturas pendentes/inadimplentes (se houver)
        await session.execute(
            select(Subscription).where(
                Subscription.user_id == user.id,
                Subscription.status.in_([
                    SubscriptionStatus.PENDENTE,
                    SubscriptionStatus.INADIMPLENTE
                ])
            )
        )

        # 5. Criar assinatura ATIVA
        now = datetime.now(UTC)
        period_end = now + timedelta(days=365)  # 1 ano de acesso

        subscription = Subscription(
            id=uuid.uuid4(),
            user_id=user.id,
            plan_id=plan.id,
            status=SubscriptionStatus.ATIVA,
            current_period_start=now,
            current_period_end=period_end,
            cancel_at_period_end=False,
            dunning_attempts=0,
            dunning_next_retry_at=None,
            dunning_grace_period_ends_at=None,
        )

        session.add(subscription)
        await session.flush()

        # 6. Registrar histórico
        history = SubscriptionHistory(
            id=uuid.uuid4(),
            subscription_id=subscription.id,
            from_plan_id=None,
            to_plan_id=plan.id,
            from_status=None,
            to_status=SubscriptionStatus.ATIVA,
            reason=SubscriptionHistoryReason.CRIADA,
        )
        session.add(history)

        await session.commit()

        print(f"""
✅ Acesso Premium concedido com sucesso!

📧 Usuário: {user.email}
📋 Plano: {plan.name}
📅 Válido até: {period_end.strftime('%d/%m/%Y %H:%M')}
🔑 Assinatura ID: {subscription.id}

Agora você pode acessar todas as funcionalidades Premium.
""")
        return True


async def main():
    if len(sys.argv) < 2:
        print("Uso: poetry run python scripts/grant_premium_access.py <email>")
        print("Exemplo: poetry run python scripts/grant_premium_access.py luizfer.12321@gmail.com")
        sys.exit(1)

    email = sys.argv[1]
    success = await grant_premium_access(email)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())