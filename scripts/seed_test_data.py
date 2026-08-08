"""Seed de dados de teste para desenvolvimento local.

Popula o banco com:
- 1 usuário admin (para logar e testar o CRUD de questões)
- 1 usuário aluno comum (para testar o fluxo público)
- Taxonomia mínima (disciplinas -> assuntos -> subassuntos)
- 1 banca examinadora, 1 órgão, 1 edição de concurso
- Algumas questões publicadas, com alternativas

Uso (dentro do container ou com o venv/poetry ativo, apontando para o
mesmo DATABASE_URL do .env):

    poetry run python scripts/seed_test_data.py

ou, rodando dentro do container da API:

    docker compose exec api python scripts/seed_test_data.py

É idempotente: pode rodar mais de uma vez, ele verifica se os registros
já existem antes de criar (por slug/email únicos).
"""

import asyncio

from app.database.session import AsyncSessionFactory
from app.models.billing.plan import Plan
from app.models.content.exam_source import ExamBoard, ExamEdition, Organization
from app.models.content.question import Question, QuestionAlternative
from app.models.content.taxonomy import Discipline, Subject, Topic
from app.models.enums import BillingPeriod, FeatureKey, FeatureKind, QuestionDifficulty, QuestionStatus
from app.models.identity.user import User, UserProfile
from app.repositories.billing.feature_repository import FeatureRepository
from app.security.password import hash_password
from app.services.billing.feature_gate_service import FREE_PLAN_SLUG
from app.services.billing.plan_service import PlanService
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# --- catálogo de features (Etapa 5) -------------------------------------- #
# Uma linha por FeatureKey do enum (`app/models/enums.py`), sincronizado com
# os valores criados em `migrations/versions/0005_billing_features.py`.
# `kind` decide se `PlanFeature.quota_limit` é relevante (QUOTA) ou se a
# feature é liga/desliga (BOOLEAN).
FEATURE_CATALOG: list[tuple[FeatureKey, FeatureKind, str, str]] = [
    (FeatureKey.DAILY_QUESTIONS, FeatureKind.QUOTA, "Questões por dia", "Quantidade de questões que o usuário pode responder por dia."),
    (FeatureKey.NOTEBOOKS, FeatureKind.BOOLEAN, "Cadernos de questões", "Acesso à criação de cadernos de questões personalizados."),
    (FeatureKey.NOTEBOOK_MAX_QUESTIONS, FeatureKind.QUOTA, "Questões por caderno", "Limite de questões por caderno de questões."),
    (FeatureKey.SIMULADOS, FeatureKind.BOOLEAN, "Simulados", "Acesso à realização de simulados cronometrados."),
    (FeatureKey.FLASHCARDS, FeatureKind.BOOLEAN, "Flashcards", "Acesso ao módulo de flashcards com revisão espaçada."),
    (FeatureKey.ESTATISTICAS, FeatureKind.BOOLEAN, "Estatísticas básicas", "Acesso às estatísticas básicas de desempenho."),
    (FeatureKey.DASHBOARD_COMPLETO, FeatureKind.BOOLEAN, "Dashboard completo", "Acesso ao dashboard completo de acompanhamento de estudos."),
    (FeatureKey.AI_EXPLICACAO_QUESTAO, FeatureKind.BOOLEAN, "Explicação de questão por IA", "Explicação de questões geradas por IA."),
    (FeatureKey.AI_RESUMOS, FeatureKind.BOOLEAN, "Resumos por IA", "Geração de resumos de conteúdo por IA."),
    (FeatureKey.AI_CRONOGRAMA, FeatureKind.BOOLEAN, "Cronograma por IA", "Geração de cronograma de estudos por IA."),
    (FeatureKey.AI_ANALISE_DESEMPENHO, FeatureKind.BOOLEAN, "Análise de desempenho por IA", "Análise de desempenho gerada por IA."),
    (FeatureKey.ANALYTICS_AVANCADO, FeatureKind.BOOLEAN, "Analytics avançado", "Métricas avançadas de desempenho e evolução."),
]

# --- planos base (Etapa 5) ------------------------------------------------ #
# `quota_limit=None` em uma feature QUOTA significa "ilimitado" (ver
# docstring de `PlanFeature`). Features BOOLEAN não devem receber quota_limit
# (o service levanta `ValidationDomainError` se isso acontecer).
PLAN_CATALOG: list[dict] = [
    {
        "slug": FREE_PLAN_SLUG,
        "name": "Free",
        "price_cents": 0,
        "billing_period": BillingPeriod.MENSAL,
        "features": {
            FeatureKey.DAILY_QUESTIONS: 5,
            FeatureKey.FLASHCARDS: None,
            FeatureKey.ESTATISTICAS: None,
        },
    },
    {
        "slug": "standard",
        "name": "Standard",
        "price_cents": 2990,
        "billing_period": BillingPeriod.MENSAL,
        "features": {
            FeatureKey.DAILY_QUESTIONS: None,
            FeatureKey.NOTEBOOKS: None,
            FeatureKey.NOTEBOOK_MAX_QUESTIONS: 50,
            FeatureKey.SIMULADOS: None,
            FeatureKey.FLASHCARDS: None,
            FeatureKey.ESTATISTICAS: None,
            FeatureKey.DASHBOARD_COMPLETO: None,
        },
    },
    {
        "slug": "pro",
        "name": "Pro",
        "price_cents": 4990,
        "billing_period": BillingPeriod.MENSAL,
        "features": {
            FeatureKey.DAILY_QUESTIONS: None,
            FeatureKey.NOTEBOOKS: None,
            FeatureKey.NOTEBOOK_MAX_QUESTIONS: None,
            FeatureKey.SIMULADOS: None,
            FeatureKey.FLASHCARDS: None,
            FeatureKey.ESTATISTICAS: None,
            FeatureKey.DASHBOARD_COMPLETO: None,
            FeatureKey.AI_EXPLICACAO_QUESTAO: None,
            FeatureKey.AI_RESUMOS: None,
            FeatureKey.AI_CRONOGRAMA: None,
            FeatureKey.AI_ANALISE_DESEMPENHO: None,
            FeatureKey.ANALYTICS_AVANCADO: None,
        },
    },
]


async def seed_feature_catalog(session: AsyncSession, plan_service: PlanService) -> None:
    """Cria o catálogo de `Feature` (uma linha por `FeatureKey`), se ainda
    não existir. Precisa rodar antes do seed de planos: `set_plan_feature`
    levanta `NotFoundError` para uma `FeatureKey` sem `Feature` cadastrada.
    """
    features = FeatureRepository(session)
    for key, kind, name, description in FEATURE_CATALOG:
        existing = await features.get_by_key(key)
        if existing is not None:
            continue
        await plan_service.create_feature(key=key, kind=kind, name=name, description=description)


async def seed_plans(session: AsyncSession, plan_service: PlanService) -> None:
    """Cria os planos base (free/standard/pro) e associa as features do
    catálogo via `PlanService.set_plan_feature` — nunca escrevendo direto em
    `Plan.features` (JSONB), que é gerenciado pelo service.
    """
    for spec in PLAN_CATALOG:
        result = await session.execute(select(Plan).where(Plan.slug == spec["slug"]))
        plan = result.scalar_one_or_none()
        if plan is None:
            plan = await plan_service.create_plan(
                name=spec["name"],
                slug=spec["slug"],
                price_cents=spec["price_cents"],
                billing_period=spec["billing_period"],
            )

        for feature_key, quota_limit in spec["features"].items():
            await plan_service.set_plan_feature(
                plan_id=plan.id, feature_key=feature_key, quota_limit=quota_limit
            )


async def get_or_create_user(
    session: AsyncSession, *, email: str, full_name: str, is_admin: bool, password: str
) -> User:
    result = await session.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user:
        return user

    user = User(
        email=email,
        password_hash=hash_password(password),
        full_name=full_name,
        is_admin=is_admin,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    session.add(UserProfile(user_id=user.id, target_exam="Polícia Penal RN"))
    return user


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


async def get_or_create_exam_board(
    session: AsyncSession, *, name: str, acronym: str, slug: str
) -> ExamBoard:
    result = await session.execute(select(ExamBoard).where(ExamBoard.slug == slug))
    obj = result.scalar_one_or_none()
    if obj:
        return obj
    obj = ExamBoard(name=name, acronym=acronym, slug=slug)
    session.add(obj)
    await session.flush()
    return obj


async def get_or_create_organization(
    session: AsyncSession, *, name: str, acronym: str, slug: str
) -> Organization:
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


async def create_question(
    session: AsyncSession,
    *,
    discipline: Discipline,
    subject: Subject | None,
    topic: Topic | None,
    exam_board: ExamBoard,
    exam_edition: ExamEdition | None,
    organization: Organization | None,
    year: int | None,
    difficulty: QuestionDifficulty,
    statement: str,
    explanation: str,
    alternatives: list[tuple[str, str, bool]],
    created_by: "uuid.UUID | None" = None,
) -> Question:
    # Evita duplicar em reruns: casa pelo enunciado exato.
    result = await session.execute(select(Question).where(Question.statement == statement))
    existing = result.scalar_one_or_none()
    if existing:
        return existing

    correct_letter = next(letter for letter, _, is_correct in alternatives if is_correct)

    question = Question(
        discipline_id=discipline.id,
        subject_id=subject.id if subject else None,
        topic_id=topic.id if topic else None,
        exam_board_id=exam_board.id,
        exam_edition_id=exam_edition.id if exam_edition else None,
        organization_id=organization.id if organization else None,
        year=year,
        difficulty=difficulty,
        status=QuestionStatus.PUBLICADA,
        statement=statement,
        correct_alternative_letter=correct_letter,
        explanation=explanation,
        created_by=created_by,
    )
    session.add(question)
    await session.flush()

    for letter, text, is_correct in alternatives:
        session.add(
            QuestionAlternative(
                question_id=question.id, letter=letter, text=text, is_correct=is_correct
            )
        )

    return question


async def main() -> None:
    async with AsyncSessionFactory() as session:
        # --- billing: catálogo de features + planos base (Etapa 5) ---
        # Precisa rodar antes de qualquer outra coisa que dependa de
        # `FeatureGateService.get_effective_plan` (ex.: qualquer endpoint
        # autenticado que verifique quota/feature) — sem o plano FREE
        # seedado, `GET /billing/subscriptions/me/plan` levanta `NotFoundError`
        # pra qualquer usuário sem assinatura ativa (comportamento intencional).
        plan_service = PlanService(session)
        await seed_feature_catalog(session, plan_service)
        await seed_plans(session, plan_service)

        # --- usuários ---
        admin = await get_or_create_user(
            session,
            email="admin@focopolicial.com.br",
            full_name="Admin Foco Policial",
            is_admin=True,
            password="Admin@123456",
        )
        await get_or_create_user(
            session,
            email="aluno@focopolicial.com.br",
            full_name="Aluno Teste",
            is_admin=False,
            password="Aluno@123456",
        )

        # --- taxonomia ---
        direito_penal = await get_or_create_discipline(
            session, name="Direito Penal", slug="direito-penal"
        )
        crimes_pessoa = await get_or_create_subject(
            session, discipline=direito_penal, name="Crimes contra a pessoa", slug="crimes-contra-a-pessoa"
        )
        homicidio = await get_or_create_topic(
            session, subject=crimes_pessoa, name="Homicídio", slug="homicidio"
        )

        portugues = await get_or_create_discipline(session, name="Português", slug="portugues")
        interpretacao = await get_or_create_subject(
            session, discipline=portugues, name="Interpretação de texto", slug="interpretacao-de-texto"
        )

        # --- origem da questão ---
        cebraspe = await get_or_create_exam_board(
            session, name="CEBRASPE", acronym="CEBRASPE", slug="cebraspe"
        )
        pp_rn = await get_or_create_organization(
            session, name="Polícia Penal do Rio Grande do Norte", acronym="PP-RN", slug="pp-rn"
        )
        edicao_2026 = await get_or_create_exam_edition(
            session,
            organization=pp_rn,
            exam_board=cebraspe,
            year=2026,
            name="Concurso Polícia Penal RN 2026",
            slug="pp-rn-2026",
        )

        # --- questões de exemplo ---
        await create_question(
            session,
            discipline=direito_penal,
            subject=crimes_pessoa,
            topic=homicidio,
            exam_board=cebraspe,
            exam_edition=edicao_2026,
            organization=pp_rn,
            year=2026,
            difficulty=QuestionDifficulty.MEDIA,
            statement=(
                "Considerando o Código Penal, julgue: o homicídio qualificado "
                "por motivo torpe admite a incidência de causa de diminuição "
                "de pena por relevante valor moral na mesma conduta."
            ),
            explanation=(
                "Errado: motivo torpe (qualificadora) e relevante valor moral "
                "(privilégio) são incompatíveis entre si, pois ambos dizem "
                "respeito ao motivo do crime."
            ),
            alternatives=[
                ("A", "Certo", False),
                ("B", "Errado", True),
            ],
            created_by=admin.id,
        )
        await create_question(
            session,
            discipline=direito_penal,
            subject=crimes_pessoa,
            topic=homicidio,
            exam_board=cebraspe,
            exam_edition=edicao_2026,
            organization=pp_rn,
            year=2026,
            difficulty=QuestionDifficulty.FACIL,
            statement="O homicídio simples está previsto em qual artigo do Código Penal?",
            explanation="O homicídio simples está previsto no art. 121, caput, do Código Penal.",
            alternatives=[
                ("A", "Art. 121, caput", True),
                ("B", "Art. 129, caput", False),
                ("C", "Art. 155, caput", False),
                ("D", "Art. 157, caput", False),
            ],
            created_by=admin.id,
        )
        await create_question(
            session,
            discipline=portugues,
            subject=interpretacao,
            topic=None,
            exam_board=cebraspe,
            exam_edition=edicao_2026,
            organization=pp_rn,
            year=2026,
            difficulty=QuestionDifficulty.MEDIA,
            statement=(
                "Em textos dissertativo-argumentativos, a tese central deve, via "
                "de regra, ser apresentada logo na introdução."
            ),
            explanation="Certo: é a estrutura clássica de texto dissertativo-argumentativo.",
            alternatives=[
                ("A", "Certo", True),
                ("B", "Errado", False),
            ],
            created_by=admin.id,
        )

        await session.commit()

    print("Seed concluído.")
    print("  Admin:  admin@focopolicial.com.br / Admin@123456")
    print("  Aluno:  aluno@focopolicial.com.br / Aluno@123456")


if __name__ == "__main__":
    asyncio.run(main())