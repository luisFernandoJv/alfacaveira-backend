import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from app.database.session import AsyncSessionFactory
from app.models.billing.plan import Plan
from app.models.billing.subscription import Subscription
from app.models.enums import SubscriptionStatus
from app.models.identity.user import User, UserProfile
from app.security.password import hash_password
from app.services.billing.subscription_service import SubscriptionService


def log(msg: str, indent: int = 0) -> None:
    print("  " * indent + msg)


async def get_plan_by_slug(session, slug: str) -> Plan:
    from sqlalchemy import select
    stmt = select(Plan).where(Plan.slug == slug)
    result = await session.execute(stmt)
    plan = result.scalar_one_or_none()
    if plan is None:
        raise ValueError(f"Plano '{slug}' não encontrado. Rode seed_test_data.py primeiro.")
    return plan


async def create_test_user(session) -> uuid.UUID:
    """Cria um usuário de teste com email único."""
    from sqlalchemy import select
    user_id = uuid.uuid4()
    email = f"upgrade-test-{user_id.hex[:8]}@staging.local"

    stmt = select(User).where(User.email == email)
    result = await session.execute(stmt)
    if result.scalar_one_or_none():
        return user_id

    user = User(
        id=user_id,
        email=email,
        password_hash=hash_password("Test@123456"),
        full_name="Upgrade Test",
        is_active=True,
    )
    session.add(user)
    await session.flush()
    session.add(UserProfile(user_id=user.id))
    await session.commit()
    log(f"Usuário criado: {user_id} ({email})")
    return user_id


async def create_subscription(
    session,
    user_id: uuid.UUID,
    plan_id: uuid.UUID,
    status: SubscriptionStatus = SubscriptionStatus.ATIVA,
    days_used: int = 15,
) -> uuid.UUID:
    """Cria uma assinatura de teste com ID único."""
    sub_id = uuid.uuid4()
    now = datetime.now(UTC)
    sub = Subscription(
        id=sub_id,
        user_id=user_id,
        plan_id=plan_id,
        status=status,
        current_period_start=now - timedelta(days=days_used),
        current_period_end=now + timedelta(days=30 - days_used),
        cancel_at_period_end=False,
    )
    session.add(sub)
    await session.flush()
    return sub.id


async def run_upgrade_test(session) -> tuple[uuid.UUID, uuid.UUID]:
    """Teste 1: Upgrade com cobrança pró-rata. Retorna (subscription_id, user_id)."""
    log("\n--- Teste 1: Upgrade Standard → Pro (pró-rata) ---")

    standard = await get_plan_by_slug(session, "standard")
    pro = await get_plan_by_slug(session, "pro")

    log(f"Plano Standard: {standard.name} (R$ {standard.price_cents/100:.2f})")
    log(f"Plano Pro: {pro.name} (R$ {pro.price_cents/100:.2f})")

    user_id = await create_test_user(session)
    sub_id = await create_subscription(session, user_id, standard.id, days_used=15)
    log(f"Assinatura criada: {sub_id}")

    subscription_service = SubscriptionService(session)
    result = await subscription_service.change_plan(sub_id, user_id, pro.id)

    log(f"Resultado: plano_atual={result.plan_id} (deveria ser Pro)")
    log(f"  pending_plan_id={result.pending_plan_id} (deveria ser None)")

    assert result.plan_id == pro.id, "Plano não foi atualizado para Pro"
    assert result.pending_plan_id is None, "Upgrade não deve ter pending_plan_id"

    from sqlalchemy import select
    from app.models.billing.payment import Payment
    stmt = select(Payment).where(Payment.subscription_id == sub_id)
    payments = (await session.execute(stmt)).scalars().all()
    log(f"Payments criados: {len(payments)}")
    for p in payments:
        log(f"  Payment: R$ {p.amount_cents/100:.2f}, status={p.status.value}")

    log("✅ Teste 1 PASSOU")
    return sub_id, user_id


async def run_upgrade_no_cost_test(session) -> tuple[uuid.UUID, uuid.UUID]:
    """Teste 2: Upgrade sem cobrança (período já vencido)."""
    log("\n--- Teste 2: Upgrade sem cobrança (pró-rata zero) ---")

    standard = await get_plan_by_slug(session, "standard")
    pro = await get_plan_by_slug(session, "pro")

    user_id = await create_test_user(session)

    now = datetime.now(UTC)
    sub_id = uuid.uuid4()
    sub = Subscription(
        id=sub_id,
        user_id=user_id,
        plan_id=standard.id,
        status=SubscriptionStatus.ATIVA,
        current_period_start=now - timedelta(days=35),
        current_period_end=now - timedelta(days=5),
        cancel_at_period_end=False,
    )
    session.add(sub)
    await session.flush()
    log(f"Assinatura criada com período já vencido: {sub_id}")

    subscription_service = SubscriptionService(session)
    result = await subscription_service.change_plan(sub_id, user_id, pro.id)

    log(f"Plano atual: {result.plan_id} (deveria ser Pro)")
    assert result.plan_id == pro.id, "Plano não foi atualizado"

    from sqlalchemy import select
    from app.models.billing.payment import Payment
    stmt = select(Payment).where(Payment.subscription_id == sub_id)
    payments = (await session.execute(stmt)).scalars().all()
    log(f"Payments criados: {len(payments)} (deveria ser 0)")
    assert len(payments) == 0, "Não deve criar payment para valor zero"

    log("✅ Teste 2 PASSOU")
    return sub_id, user_id


async def run_downgrade_test(session, sub_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """Teste 3: Downgrade agendado."""
    log("\n--- Teste 3: Downgrade Pro → Standard (agendado) ---")

    standard = await get_plan_by_slug(session, "standard")
    pro = await get_plan_by_slug(session, "pro")

    log(f"Usando assinatura: {sub_id} (plano atual: Pro)")

    subscription_service = SubscriptionService(session)
    result = await subscription_service.change_plan(sub_id, user_id, standard.id)

    log(f"Resultado: plano_atual={result.plan_id} (deveria continuar Pro)")
    log(f"  pending_plan_id={result.pending_plan_id} (deveria ser Standard)")
    log(f"  pending_plan_effective_at={result.pending_plan_effective_at}")

    assert result.plan_id == pro.id, "Downgrade não deve aplicar na hora"
    assert result.pending_plan_id == standard.id, "Downgrade não foi agendado"
    assert result.pending_plan_effective_at is not None, "Downgrade sem data"

    log("✅ Teste 3 PASSOU")


async def run_downgrade_apply_test(session, sub_id: uuid.UUID) -> None:
    """Teste 4: Aplicar downgrade agendado (simula worker)."""
    log("\n--- Teste 4: Aplicar downgrade agendado ---")

    # Força o período a terminar E atualiza pending_plan_effective_at
    sub = await session.get(Subscription, sub_id)
    if sub is None:
        raise ValueError(f"Assinatura {sub_id} não encontrada")

    now = datetime.now(UTC)
    sub.current_period_end = now - timedelta(hours=1)
    # CRUCIAL: também atualiza pending_plan_effective_at para que o worker veja que já venceu
    sub.pending_plan_effective_at = now - timedelta(hours=1)
    await session.flush()

    log(f"Período forçado a terminar: current_period_end={sub.current_period_end}")
    log(f"pending_plan_effective_at={sub.pending_plan_effective_at}")

    log("Rodando apply_pending_downgrade...")

    subscription_service = SubscriptionService(session)
    result = await subscription_service.apply_pending_downgrade(sub_id)

    log(f"Resultado: plano_atual={result.plan_id} (deveria ser Standard)")
    log(f"  pending_plan_id={result.pending_plan_id} (deveria ser None)")

    standard = await get_plan_by_slug(session, "standard")
    assert result.plan_id == standard.id, "Downgrade não foi aplicado"
    assert result.pending_plan_id is None, "pending_plan_id não foi limpo"

    log("✅ Teste 4 PASSOU")


async def main() -> None:
    print("=== Teste de Upgrade/Downgrade/Pró-rata ===\n")

    async with AsyncSessionFactory() as session:
        try:
            sub_id_1, user_id_1 = await run_upgrade_test(session)
            sub_id_2, user_id_2 = await run_upgrade_no_cost_test(session)
            await run_downgrade_test(session, sub_id_1, user_id_1)
            await run_downgrade_apply_test(session, sub_id_1)

            print("\n" + "=" * 50)
            print("✅ TODOS OS TESTES PASSARAM")
            print("=" * 50)

        except AssertionError as e:
            print(f"\n❌ TESTE FALHOU: {e}")
            raise


if __name__ == "__main__":
    asyncio.run(main())