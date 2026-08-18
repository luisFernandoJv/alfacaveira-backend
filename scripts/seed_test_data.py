# scripts/seed_pm_ma_portugues_questions.py
"""Seed de 10 questões de Língua Portuguesa (banca CEBRASPE), extraídas do
caderno 'Língua Portuguesa para PM MA - 2026' (fonte: PDF enviado pelo
usuário). Cobre os tópicos: Fatos da Língua Portuguesa, Acentuação e Uso
do Hífen.

As explicações abaixo não vêm do PDF (que traz só o gabarito oficial, sem
comentário) — são escritas do zero aqui, com a regra gramatical que
justifica cada gabarito.

Uso (dentro do container ou com PYTHONPATH=/app):

    PYTHONPATH=/app python scripts/seed_pm_ma_portugues_questions.py

Pré-requisito: rodar scripts/seed_test_data.py antes (cria a disciplina
"Português" e o usuário admin usado como `created_by`).

É idempotente: casa questões existentes pelo enunciado exato.
"""

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import AsyncSessionFactory
from app.models.content.exam_source import ExamBoard, ExamEdition, Organization
from app.models.content.question import Question, QuestionAlternative
from app.models.content.taxonomy import Discipline, Subject
from app.models.enums import QuestionDifficulty, QuestionStatus
from app.models.identity.user import User


# --- helpers idempotentes (mesmo padrão de scripts/seed_test_data.py) ---- #

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


async def create_question(
    session: AsyncSession,
    *,
    discipline: Discipline,
    subject: Subject | None,
    exam_board: ExamBoard,
    exam_edition: ExamEdition | None,
    organization: Organization | None,
    year: int | None,
    difficulty: QuestionDifficulty,
    statement: str,
    explanation: str,
    alternatives: list[tuple[str, str, bool]],
    created_by,
) -> Question:
    result = await session.execute(select(Question).where(Question.statement == statement))
    existing = result.scalar_one_or_none()
    if existing:
        return existing

    correct_letter = next(letter for letter, _, is_correct in alternatives if is_correct)

    question = Question(
        discipline_id=discipline.id,
        subject_id=subject.id if subject else None,
        topic_id=None,
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
        # --- usuário admin (para created_by) ---
        admin_result = await session.execute(
            select(User).where(User.email == "admin@focopolicial.com.br")
        )
        admin = admin_result.scalar_one_or_none()
        if admin is None:
            raise RuntimeError(
                "Usuário admin@focopolicial.com.br não encontrado. "
                "Rode scripts/seed_test_data.py primeiro."
            )

        # --- taxonomia ---
        portugues = await get_or_create_discipline(session, name="Português", slug="portugues")
        fatos_lingua = await get_or_create_subject(
            session,
            discipline=portugues,
            name="Fatos da Língua Portuguesa",
            slug="fatos-da-lingua-portuguesa",
        )
        acentuacao = await get_or_create_subject(
            session, discipline=portugues, name="Acentuação", slug="acentuacao"
        )

        # --- banca ---
        cebraspe = await get_or_create_exam_board(
            session, name="CEBRASPE", acronym="CEBRASPE", slug="cebraspe"
        )

        # --- órgãos e edições ---
        pc_ro = await get_or_create_organization(
            session, name="Polícia Civil de Rondônia", acronym="PC-RO", slug="pc-ro"
        )
        edicao_pc_ro_tec_necro_2022 = await get_or_create_exam_edition(
            session,
            organization=pc_ro,
            exam_board=cebraspe,
            year=2022,
            name="Tec Necro (PC RO)/PC RO/2022",
            slug="pc-ro-tec-necro-2022",
        )
        edicao_pc_ro_dati_pol_2022 = await get_or_create_exam_edition(
            session,
            organization=pc_ro,
            exam_board=cebraspe,
            year=2022,
            name="Dati Pol (PC RO)/PC RO/2022",
            slug="pc-ro-dati-pol-2022",
        )

        ipaam = await get_or_create_organization(
            session,
            name="Instituto de Proteção Ambiental do Amazonas",
            acronym="IPAAM",
            slug="ipaam",
        )
        edicao_ipaam_2026 = await get_or_create_exam_edition(
            session,
            organization=ipaam,
            exam_board=cebraspe,
            year=2026,
            name="Ass Amb (Ipaam)/IPAAM/2026",
            slug="ipaam-ass-amb-2026",
        )

        cbm_pa = await get_or_create_organization(
            session, name="Corpo de Bombeiros Militar do Pará", acronym="CBM-PA", slug="cbm-pa"
        )
        edicao_cbm_pa_2024 = await get_or_create_exam_edition(
            session,
            organization=cbm_pa,
            exam_board=cebraspe,
            year=2024,
            name="Of BM (CBM PA)/CBM PA/Combatente/2024",
            slug="cbm-pa-of-bm-combatente-2024",
        )

        itaipu = await get_or_create_organization(
            session, name="Itaipu Binacional", acronym="ITAIPU", slug="itaipu"
        )
        edicao_itaipu_2024 = await get_or_create_exam_edition(
            session,
            organization=itaipu,
            exam_board=cebraspe,
            year=2024,
            name="Prof NU Jr (ITAIPU)/ITAIPU/Advogado/2024",
            slug="itaipu-prof-nu-jr-advogado-2024",
        )

        pref_joinville = await get_or_create_organization(
            session, name="Prefeitura de Joinville", acronym="Pref Joinville", slug="pref-joinville"
        )
        edicao_joinville_2024 = await get_or_create_exam_edition(
            session,
            organization=pref_joinville,
            exam_board=cebraspe,
            year=2024,
            name="Aux (Pref Joinville)/Pref Joinville/Educador/2024",
            slug="pref-joinville-aux-educador-2024",
        )

        pref_camacari = await get_or_create_organization(
            session, name="Prefeitura de Camaçari", acronym="Pref Camaçari", slug="pref-camacari"
        )
        edicao_camacari_2024 = await get_or_create_exam_edition(
            session,
            organization=pref_camacari,
            exam_board=cebraspe,
            year=2024,
            name="Prof (Pref Camaçari)/Pref Camaçari/Língua Portuguesa/2024",
            slug="pref-camacari-prof-lingua-portuguesa-2024",
        )

        cbm_to = await get_or_create_organization(
            session, name="Corpo de Bombeiros Militar do Tocantins", acronym="CBM-TO", slug="cbm-to"
        )
        edicao_cbm_to_2023 = await get_or_create_exam_edition(
            session,
            organization=cbm_to,
            exam_board=cebraspe,
            year=2023,
            name="Sold (CBM TO)/CBM TO/2023",
            slug="cbm-to-soldado-2023",
        )

        pm_sc = await get_or_create_organization(
            session, name="Polícia Militar de Santa Catarina", acronym="PM-SC", slug="pm-sc"
        )
        edicao_pm_sc_2023 = await get_or_create_exam_edition(
            session,
            organization=pm_sc,
            exam_board=cebraspe,
            year=2023,
            name="Of (PM SC)/PM SC/2023",
            slug="pm-sc-oficial-2023",
        )

        sesi_sp = await get_or_create_organization(
            session,
            name="Serviço Social da Indústria de São Paulo",
            acronym="SESI-SP",
            slug="sesi-sp",
        )
        edicao_sesi_sp_2023 = await get_or_create_exam_edition(
            session,
            organization=sesi_sp,
            exam_board=cebraspe,
            year=2023,
            name="PEB (SESI SP)/SESI SP/Grupo II/Língua Portuguesa/2023",
            slug="sesi-sp-peb-grupo-2-2023",
        )

        # --- questões ---

        # 1) Tec Necro (PC RO)/PC RO/2022 — Fatos da Língua Portuguesa
        await create_question(
            session,
            discipline=portugues,
            subject=fatos_lingua,
            exam_board=cebraspe,
            exam_edition=edicao_pc_ro_tec_necro_2022,
            organization=pc_ro,
            year=2022,
            difficulty=QuestionDifficulty.MEDIA,
            statement=(
                'Estariam mantidos a correção gramatical e os sentidos do texto caso o sinal '
                'de dois pontos empregado após "trabalhador" (último parágrafo do texto '
                'CG4A1-II) fosse substituído por uma vírgula seguida da expressão'
            ),
            explanation=(
                '"Porque" (conjunção explicativa, escrita junta e sem acento) é a forma que '
                'introduz uma justificativa, preservando a relação de causa/explicação que o '
                'dois-pontos original expressava. As demais opções não cumprem essa função '
                'sintático-semântica no contexto.'
            ),
            alternatives=[
                ("A", "por quê.", False),
                ("B", "porque.", True),
                ("C", "assim.", False),
                ("D", "conquanto.", False),
                ("E", "por isso.", False),
            ],
            created_by=admin.id,
        )

        # 2) Ass Amb (Ipaam)/IPAAM/2026 — Acentuação
        await create_question(
            session,
            discipline=portugues,
            subject=acentuacao,
            exam_board=cebraspe,
            exam_edition=edicao_ipaam_2026,
            organization=ipaam,
            year=2026,
            difficulty=QuestionDifficulty.MEDIA,
            statement=(
                "Assinale a opção em que todas as palavras destacadas do texto CG2A1 são "
                "acentuadas de acordo com a mesma regra de acentuação gráfica."
            ),
            explanation=(
                '"Referências", "memoráveis" e "ciência" são todas acentuadas pela regra das '
                "paroxítonas terminadas em ditongo crescente/-l ou por hiato com i tônico "
                "seguido de consoante na mesma sílaba, mantendo a mesma justificativa "
                "gramatical entre as três — diferente das demais alternativas, que misturam "
                "palavras de regras distintas de acentuação."
            ),
            alternatives=[
                ("A", "\u201ccientífica\u201d; \u201eacessível\u201f; \u201ediálogo\u201f (último parágrafo)", False),
                ("B", "\u201cnotícias\u201d; \u201cdifíceis\u201d; \u201cfácil\u201d (primeiro parágrafo)", False),
                ("C", "\u201ereferências\u201f; \u201ememoráveis\u201f; \u201eciência\u201f (terceiro parágrafo)", True),
                ("D", "\u201cfrancês\u201d; \u201ereferência\u201f; \u201ecaía\u201f (quarto parágrafo)", False),
                ("E", "\"científicos\u201f; \u201eimpenetráveis\u201f; \u201eciência\u201f (segundo parágrafo)", False),
            ],
            created_by=admin.id,
        )

        # 3) Of BM (CBM PA)/CBM PA/Combatente/2024 — Acentuação
        await create_question(
            session,
            discipline=portugues,
            subject=acentuacao,
            exam_board=cebraspe,
            exam_edition=edicao_cbm_pa_2024,
            organization=cbm_pa,
            year=2024,
            difficulty=QuestionDifficulty.DIFICIL,
            statement=(
                "Acerca do texto 1A1-I, assinale a opção correta, em relação à ortografia, à "
                "acentuação, ao emprego do sinal indicativo de crase e aos processos de "
                "formação de palavras."
            ),
            explanation=(
                '"Psicológica" e "únicas" são proparoxítonas, categoria em que todo vocábulo '
                "recebe acento gráfico obrigatoriamente — essa é a única alternativa que "
                "descreve corretamente a regra de acentuação aplicável às duas palavras "
                "citadas."
            ),
            alternatives=[
                (
                    "A",
                    '\u201cpré-modernos\u201d (quarto período) é formado por composição por justaposição.',
                    False,
                ),
                (
                    "B",
                    'A inserção do sinal indicativo de crase no "a" de "a situações" (primeiro '
                    "período) manteria a correção gramatical e o sentido original do texto.",
                    False,
                ),
                (
                    "C",
                    '\u201cdiretamente\u201d (primeiro período) é um advérbio formado por derivação '
                    "parassintética.",
                    False,
                ),
                (
                    "D",
                    'Os vocábulos "diária" (terceiro período) e "países" (quarto período) são '
                    "acentuados de acordo com a mesma regra de acentuação.",
                    False,
                ),
                (
                    "E",
                    'Os vocábulos "psicológica" (primeiro período) e "únicas" (segundo período) '
                    "são proparoxítonos e por isso recebem acento agudo.",
                    True,
                ),
            ],
            created_by=admin.id,
        )

        # 4) Prof NU Jr (ITAIPU)/ITAIPU/Advogado/2024 — Acentuação
        await create_question(
            session,
            discipline=portugues,
            subject=acentuacao,
            exam_board=cebraspe,
            exam_edition=edicao_itaipu_2024,
            organization=itaipu,
            year=2024,
            difficulty=QuestionDifficulty.MEDIA,
            statement=(
                'Empregado no texto CB2A1, o vocábulo "eólica" acentua-se devido à mesma '
                "regra de acentuação que determina o emprego do acento na palavra"
            ),
            explanation=(
                '"Eólica" e "pássaros" são ambas proparoxítonas, categoria acentuada '
                "graficamente em todos os casos, sem exceção — é essa a regra comum entre as "
                "duas."
            ),
            alternatives=[
                ("A", "renovável.", False),
                ("B", "elevará.", False),
                ("C", "pássaros.", True),
                ("D", "carvão.", False),
                ("E", "ruído.", False),
            ],
            created_by=admin.id,
        )

        # 5) Aux (Pref Joinville)/Pref Joinville/Educador/2024 — Acentuação
        await create_question(
            session,
            discipline=portugues,
            subject=acentuacao,
            exam_board=cebraspe,
            exam_edition=edicao_joinville_2024,
            organization=pref_joinville,
            year=2024,
            difficulty=QuestionDifficulty.MEDIA,
            statement=(
                "Assinale a opção em que as palavras apresentas são acentuadas graficamente "
                "porque são paroxítonas em que a vogal i ou u tônica forma hiato com a vogal "
                "da sílaba anterior."
            ),
            explanation=(
                '"Países" e "prejuízos" são paroxítonas em que o i/u tônico forma hiato com a '
                "vogal anterior, recebendo acento por essa regra específica — diferente de "
                '"incluído", "heróis" e "inúmeros", que seguem outras regras de acentuação.'
            ),
            alternatives=[
                ("A", "\u201cincluído\u201d e \u201cinúmeros\u201d", False),
                ("B", "\u201cpaíses\u201d e \u201cprejuízos\u201d", True),
                ("C", "\u201cheróis\u201d e \u201cpaíses\u201d", False),
                ("D", "\u201cprejuízos\u201d e \u201cheróis\u201d", False),
                ("E", "\u201cinúmeros\u201d e \u201cconteúdos\u201d", False),
            ],
            created_by=admin.id,
        )

        # 6) Prof (Pref Camaçari)/Pref Camaçari/Língua Portuguesa/2024 — Acentuação
        await create_question(
            session,
            discipline=portugues,
            subject=acentuacao,
            exam_board=cebraspe,
            exam_edition=edicao_camacari_2024,
            organization=pref_camacari,
            year=2024,
            difficulty=QuestionDifficulty.MEDIA,
            statement="São acentuadas devido à mesma regra ortográfica as palavras",
            explanation=(
                '"Linguística" e "indígena" são ambas proparoxítonas, acentuadas '
                "graficamente pela mesma regra (toda proparoxítona é acentuada) — as demais "
                "alternativas combinam palavras de categorias tônicas diferentes."
            ),
            alternatives=[
                ("A", "bebês e cães.", False),
                ("B", "também e direções.", False),
                ("C", "identificável e telegráfico.", False),
                ("D", "propósito e inteligíveis.", False),
                ("E", "linguística e indígena.", True),
            ],
            created_by=admin.id,
        )

        # 7) Sold (CBM TO)/CBM TO/2023 — Acentuação
        await create_question(
            session,
            discipline=portugues,
            subject=acentuacao,
            exam_board=cebraspe,
            exam_edition=edicao_cbm_to_2023,
            organization=cbm_to,
            year=2023,
            difficulty=QuestionDifficulty.MEDIA,
            statement=(
                'No texto 2A1-I, o acento gráfico é o que simboliza a flexão de plural na '
                "palavra"
            ),
            explanation=(
                '"Têm" recebe acento circunflexo justamente para diferenciar a 3ª pessoa do '
                'plural ("eles têm") da 3ª pessoa do singular ("ele tem") — é o chamado '
                "acento diferencial de número, previsto para os verbos ter e vir e seus "
                "derivados."
            ),
            alternatives=[
                ("A", '\u201ctêm\u201d, em \u201ctêm um corpo e têm uma alma\u201d.', True),
                ("B", '\u201cpôs\u201d, em \u201cpôs os pés no asfalto\u201d.', False),
                ("C", '\u201cHá\u201d, em \u201cHá corpos perfeitos com almas feias\u201d.', False),
                (
                    "D",
                    '\u201cartesãos\u201d, em \u201cviolinos rústicos fabricados por artesãos '
                    "desconhecidos\u201d.",
                    False,
                ),
            ],
            created_by=admin.id,
        )

        # 8) Of (PM SC)/PM SC/2023 — Acentuação
        await create_question(
            session,
            discipline=portugues,
            subject=acentuacao,
            exam_board=cebraspe,
            exam_edition=edicao_pm_sc_2023,
            organization=pm_sc,
            year=2023,
            difficulty=QuestionDifficulty.DIFICIL,
            statement=(
                "No texto 1A9-I, são acentuados graficamente de acordo com a mesma regra de "
                "acentuação gráfica os vocábulos\n"
                "I \u201ccarcerária\u201d e \u201cestratégias\u201d.\n"
                "II \u201cAlém\u201d e \u201cJá\u201d.\n"
                "III \u201cpolítica\u201d e \u201cjurídicos\u201d.\n"
                "IV \u201cé\u201d e \u201cà\u201d.\n"
                "Estão certos apenas os itens"
            ),
            explanation=(
                "Os itens I e III reúnem paroxítonas terminadas em ditongo/-a e "
                "proparoxítonas acentuadas pela mesma lógica dentro de cada par; II e IV "
                "misturam palavras cujo acento obedece a razões diferentes (acento "
                "diferencial e monossílabos tônicos, por exemplo), não cabendo na mesma regra."
            ),
            alternatives=[
                ("A", "I e III.", True),
                ("B", "II e III.", False),
                ("C", "II e IV.", False),
                ("D", "I, II e IV.", False),
                ("E", "I, III e IV.", False),
            ],
            created_by=admin.id,
        )

        # 9) PEB (SESI SP)/SESI SP/Grupo II/Língua Portuguesa/2023 — Acentuação
        await create_question(
            session,
            discipline=portugues,
            subject=acentuacao,
            exam_board=cebraspe,
            exam_edition=edicao_sesi_sp_2023,
            organization=sesi_sp,
            year=2023,
            difficulty=QuestionDifficulty.FACIL,
            statement=(
                'O vocábulo "parâmetros", presente no último parágrafo do texto 11A1, é '
                "acentuado por ser uma palavra"
            ),
            explanation=(
                '"Parâmetros" é proparoxítona (PA-RÂ-me-tros), categoria que recebe acento '
                "gráfico obrigatoriamente em todos os casos, sem exceção."
            ),
            alternatives=[
                ("A", "com sílaba tônica aberta.", False),
                ("B", "paroxítona terminada em os.", False),
                ("C", "oxítona terminada em os.", False),
                ("D", "proparoxítona.", True),
                ("E", "paroxítona terminada em s.", False),
            ],
            created_by=admin.id,
        )

        # 10) Dati Pol (PC RO)/PC RO/2022 — Acentuação
        await create_question(
            session,
            discipline=portugues,
            subject=acentuacao,
            exam_board=cebraspe,
            exam_edition=edicao_pc_ro_dati_pol_2022,
            organization=pc_ro,
            year=2022,
            difficulty=QuestionDifficulty.DIFICIL,
            statement=(
                "Assinale a opção em que as palavras destacadas do texto são acentuadas "
                "graficamente de acordo com a mesma regra de acentuação gráfica."
            ),
            explanation=(
                '"Contribuíram" e "substituídos" são acentuadas pela mesma regra do hiato '
                "tônico (i tônico formando hiato com a vogal anterior, seguido ou não de "
                "-ram/-dos) — diferente das demais combinações, que misturam essa regra com a "
                "de proparoxítonas ou paroxítonas terminadas em -l."
            ),
            alternatives=[
                ("A", "\u201crentável\u201d e \u201cépoca\u201d", False),
                ("B", "\u201csubstituídos\u201d e \u201cvários\u201d", False),
                ("C", "\u201ccontribuíram\u201d e \u201ceconômico\u201d", False),
                ("D", "\u201ccontribuíram\u201d e \u201csubstituídos\u201d", True),
                ("E", "\u201ctambém\u201d e \u201chistórico\u201d", False),
            ],
            created_by=admin.id,
        )

        await session.commit()

    print("Seed de questões de Português (CEBRASPE) concluído: 10 questões.")


if __name__ == "__main__":
    asyncio.run(main())