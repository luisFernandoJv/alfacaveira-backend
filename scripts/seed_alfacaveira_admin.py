# scripts/seed_alfacaveira_admin.py
"""Setup administrativo pontual para o e-mail informado em produção:

- Torna o usuário admin (`is_admin=True`), criando-o se ainda não existir.
- Concede assinatura Pro ATIVA (via `Subscription` + `SubscriptionHistory`
  criados diretamente com `status=ATIVA`, igual ao já feito em
  `scripts/grant_premium_access.py` — é setup administrativo, não uma
  transação real de pagamento, então pular o fluxo de webhook é intencional
  aqui; para o fluxo real, sempre usar `SubscriptionService`).
- Expande a taxonomia (disciplinas/assuntos/bancas/órgãos/edições) e cria
  `QuestionTag`s, aplicando-as às questões existentes, para exercitar
  filtros mais realistas no ambiente de teste.

É idempotente: pode rodar mais de uma vez (casa por email/slug/nome únicos).

Uso:

    poetry run python scripts/seed_alfacaveira_admin.py [email]

Se `email` não for passado, usa ADMIN_EMAIL abaixo.
"""

import asyncio
import sys
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import AsyncSessionFactory
from app.models.billing.plan import Plan
from app.models.billing.subscription import Subscription
from app.models.billing.subscription_history import SubscriptionHistory
from app.models.content.exam_source import ExamBoard, ExamEdition, Organization
from app.models.content.question import Question
from app.models.content.question_tag import QuestionTag
from app.models.content.taxonomy import Discipline, Subject, Topic
from app.models.enums import SubscriptionHistoryReason, SubscriptionStatus
from app.models.identity.user import User, UserProfile
from app.security.password import hash_password

ADMIN_EMAIL_DEFAULT = "luisfernando.engcp@gmail.com"
# Senha temporária apenas para permitir login local caso o usuário ainda não
# exista (se já existir, a senha atual NÃO é alterada). Trocar no primeiro
# acesso — este script não deve ser a fonte de verdade de credenciais.
FALLBACK_PASSWORD = "TrocarNoPrimeiroAcesso@2026"


# --- helpers idempotentes (mesmo padrão de scripts/seed_test_data.py) ---- #

async def get_or_create_admin_user(session: AsyncSession, *, email: str) -> User:
    result = await session.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user:
        if not user.is_admin:
            user.is_admin = True
            print(f"✅ Usuário existente promovido a admin: {email}")
        else:
            print(f"ℹ️  Usuário já era admin: {email}")
        return user

    user = User(
        email=email,
        password_hash=hash_password(FALLBACK_PASSWORD),
        full_name="Luis Fernando",
        is_admin=True,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    session.add(UserProfile(user_id=user.id, target_exam="Polícia Penal"))
    print(f"✅ Usuário criado como admin: {email} (senha temporária: {FALLBACK_PASSWORD})")
    return user


async def grant_active_pro_subscription(session: AsyncSession, *, user: User) -> Subscription:
    existing = await session.execute(
        select(Subscription).where(
            Subscription.user_id == user.id,
            Subscription.status == SubscriptionStatus.ATIVA,
        )
    )
    active = existing.scalar_one_or_none()
    if active:
        print("ℹ️  Usuário já possui assinatura ATIVA — nada a fazer.")
        return active

    plan_result = await session.execute(select(Plan).where(Plan.slug == "pro"))
    plan = plan_result.scalar_one_or_none()
    if plan is None:
        raise RuntimeError(
            "Plano 'pro' não encontrado. Rode scripts/seed_test_data.py primeiro "
            "(ele popula o catálogo de features e os planos base)."
        )

    now = datetime.now(UTC)
    period_end = now + timedelta(days=365)

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

    session.add(
        SubscriptionHistory(
            id=uuid.uuid4(),
            subscription_id=subscription.id,
            from_plan_id=None,
            to_plan_id=plan.id,
            from_status=None,
            to_status=SubscriptionStatus.ATIVA,
            reason=SubscriptionHistoryReason.CRIADA,
        )
    )
    print(f"✅ Assinatura Pro ATIVA concedida até {period_end.strftime('%d/%m/%Y')}.")
    return subscription


async def get_or_create_discipline(session: AsyncSession, *, name: str, slug: str) -> Discipline:
    result = await session.execute(select(Discipline).where(Discipline.slug == slug))
    obj = result.scalar_one_or_none()
    if obj:
        return obj
    obj = Discipline(name=name, slug=slug)
    session.add(obj)
    await session.flush()
    return obj


async def get_or_create_subject(
    session: AsyncSession, *, discipline: Discipline, name: str, slug: str
) -> Subject:
    result = await session.execute(select(Subject).where(Subject.slug == slug))
    obj = result.scalar_one_or_none()
    if obj:
        return obj
    obj = Subject(discipline_id=discipline.id, name=name, slug=slug)
    session.add(obj)
    await session.flush()
    return obj


async def get_or_create_topic(session: AsyncSession, *, subject: Subject, name: str, slug: str) -> Topic:
    result = await session.execute(select(Topic).where(Topic.slug == slug))
    obj = result.scalar_one_or_none()
    if obj:
        return obj
    obj = Topic(subject_id=subject.id, name=name, slug=slug)
    session.add(obj)
    await session.flush()
    return obj


async def get_or_create_exam_board(session: AsyncSession, *, name: str, acronym: str, slug: str) -> ExamBoard:
    result = await session.execute(select(ExamBoard).where(ExamBoard.slug == slug))
    obj = result.scalar_one_or_none()
    if obj:
        return obj
    obj = ExamBoard(name=name, acronym=acronym, slug=slug)
    session.add(obj)
    await session.flush()
    return obj


async def get_or_create_organization(session: AsyncSession, *, name: str, acronym: str, slug: str) -> Organization:
    result = await session.execute(select(Organization).where(Organization.slug == slug))
    obj = result.scalar_one_or_none()
    if obj:
        return obj
    obj = Organization(name=name, acronym=acronym, slug=slug)
    session.add(obj)
    await session.flush()
    return obj


async def get_or_create_exam_edition(
    session: AsyncSession,
    *,
    organization: Organization,
    exam_board: ExamBoard,
    year: int,
    name: str,
    slug: str,
) -> ExamEdition:
    result = await session.execute(select(ExamEdition).where(ExamEdition.slug == slug))
    obj = result.scalar_one_or_none()
    if obj:
        return obj
    obj = ExamEdition(
        organization_id=organization.id,
        exam_board_id=exam_board.id,
        year=year,
        name=name,
        slug=slug,
    )
    session.add(obj)
    await session.flush()
    return obj


async def get_or_create_tag(session: AsyncSession, *, name: str, slug: str) -> QuestionTag:
    result = await session.execute(select(QuestionTag).where(QuestionTag.slug == slug))
    obj = result.scalar_one_or_none()
    if obj:
        return obj
    obj = QuestionTag(name=name, slug=slug)
    session.add(obj)
    await session.flush()
    return obj


async def tag_question(session: AsyncSession, *, statement_contains: str, tags: list[QuestionTag]) -> None:
    """Aplica tags a uma questão existente, buscando pelo início do enunciado
    (evita depender de IDs fixos). Não faz nada se a questão não existir
    ainda (ex.: rodou sem o seed_test_data.py antes)."""
    result = await session.execute(
        select(Question).where(Question.statement.ilike(f"{statement_contains}%"))
    )
    question = result.scalar_one_or_none()
    if question is None:
        return
    await session.refresh(question, attribute_names=["tags"])
    existing_slugs = {t.slug for t in question.tags}
    for tag in tags:
        if tag.slug not in existing_slugs:
            question.tags.append(tag)


# --- expansão de taxonomia/bancas/órgãos, além do que já existe em seed_test_data.py ---- #

async def expand_taxonomy_and_tags(session: AsyncSession) -> None:
    # Disciplinas/assuntos adicionais
    direito_constitucional = await get_or_create_discipline(
        session, name="Direito Constitucional", slug="direito-constitucional"
    )
    direitos_fundamentais = await get_or_create_subject(
        session,
        discipline=direito_constitucional,
        name="Direitos e Garantias Fundamentais",
        slug="direitos-e-garantias-fundamentais",
    )
    await get_or_create_topic(
        session, subject=direitos_fundamentais, name="Direitos Individuais", slug="direitos-individuais"
    )

    direito_administrativo = await get_or_create_discipline(
        session, name="Direito Administrativo", slug="direito-administrativo"
    )
    await get_or_create_subject(
        session,
        discipline=direito_administrativo,
        name="Atos Administrativos",
        slug="atos-administrativos",
    )

    raciocinio_logico = await get_or_create_discipline(
        session, name="Raciocínio Lógico", slug="raciocinio-logico"
    )
    await get_or_create_subject(
        session, discipline=raciocinio_logico, name="Lógica Proposicional", slug="logica-proposicional"
    )

    # Bancas e órgãos adicionais
    fgv = await get_or_create_exam_board(session, name="FGV", acronym="FGV", slug="fgv")
    fcc = await get_or_create_exam_board(session, name="FCC", acronym="FCC", slug="fcc")

    depen = await get_or_create_organization(
        session, name="Departamento Penitenciário Nacional", acronym="DEPEN", slug="depen"
    )
    pf = await get_or_create_organization(session, name="Polícia Federal", acronym="PF", slug="pf")

    await get_or_create_exam_edition(
        session,
        organization=depen,
        exam_board=fgv,
        year=2025,
        name="Concurso DEPEN 2025",
        slug="depen-2025",
    )
    await get_or_create_exam_edition(
        session,
        organization=pf,
        exam_board=fcc,
        year=2026,
        name="Concurso Polícia Federal 2026",
        slug="pf-2026",
    )

    # Tags e aplicação em questões já existentes (criadas por seed_test_data.py)
    pegadinha = await get_or_create_tag(session, name="pegadinha", slug="pegadinha")
    jurisprudencia = await get_or_create_tag(
        session, name="jurisprudência 2024", slug="jurisprudencia-2024"
    )
    letra_de_lei = await get_or_create_tag(session, name="letra de lei", slug="letra-de-lei")

    await tag_question(
        session,
        statement_contains="Considerando o Código Penal, julgue: o homicídio qualificado",
        tags=[pegadinha, jurisprudencia],
    )
    await tag_question(
        session,
        statement_contains="O homicídio simples está previsto em qual artigo",
        tags=[letra_de_lei],
    )


async def main() -> None:
    email = sys.argv[1] if len(sys.argv) > 1 else ADMIN_EMAIL_DEFAULT

    async with AsyncSessionFactory() as session:
        admin = await get_or_create_admin_user(session, email=email)
        await grant_active_pro_subscription(session, user=admin)
        await expand_taxonomy_and_tags(session)

        await session.commit()

    print("\nSeed concluído.")
    print(f"  Admin com Pro ativo: {email}")


if __name__ == "__main__":
    asyncio.run(main())