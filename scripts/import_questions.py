#!/usr/bin/env python
"""Importação em lote de questões para o banco (RDS Postgres em produção,
ou local em desenvolvimento) — via QuestionService, não SQL direto.

Por que passa pelo QuestionService (o mesmo usado por `POST /questions`) em
vez de fazer INSERT direto na tabela `questions`:
  - roda as MESMAS validações do Pydantic (letras A-E únicas, exatamente uma
    alternativa correta, etc.);
  - grava o snapshot de auditoria em `question_revisions` (mesmo histórico
    que uma criação manual pelo admin geraria);
  - garante que o `search_vector` (full-text search) e os índices compostos
    da tabela continuam corretos, pois a linha nasce pelo caminho oficial.

Taxonomia (disciplina/assunto/tópico), banca, órgão, edição e tags ainda não
têm endpoint HTTP de criação neste backend (só leitura) — então são
resolvidas/criadas aqui com o mesmo padrão `get_or_create_*` já usado em
`scripts/seed_test_data.py`, direto via SQLAlchemy, na mesma sessão. Cada
questão é commitada individualmente (o `QuestionService` já commita
internamente via `UnitOfWork`), então uma falha numa questão não derruba as
demais — o script continua e reporta o que deu certo/errado no final.

Aceita tanto um JSON (lista de objetos, formato nativo) quanto um .xlsx/.xlsm
gerado a partir de `questoes.template.xlsx` (planilha com uma linha por
questão) — o formato é detectado pela extensão do arquivo.

USO
---
  # 1) Validar o arquivo sem gravar nada no banco (recomendado sempre antes)
  python scripts/import_questions.py --file questoes.json --admin-email admin@empresa.com --dry-run
  python scripts/import_questions.py --file questoes.xlsx --admin-email admin@empresa.com --dry-run

  # 2) Importar de fato, deixando como rascunho (padrão do QuestionService)
  python scripts/import_questions.py --file questoes.json --admin-email admin@empresa.com

  # 3) Importar já publicando as que tiverem "publish": true no JSON
  python scripts/import_questions.py --file questoes.json --admin-email admin@empresa.com --publish-flagged

  # 4) Pular questões cujo enunciado (primeiros 120 caracteres) já existe
  python scripts/import_questions.py --file questoes.json --admin-email admin@empresa.com --skip-duplicates

Para rodar contra o RDS de produção: aponte a variável de ambiente
DATABASE_URL (lida por app/core/config.py) para o endpoint do RDS, a partir
de uma máquina com rota de rede até ele (bastion/EC2 na mesma VPC, ECS task,
ou túnel SSH) — NUNCA exponha o RDS publicamente para rodar isso do seu
notebook. Veja o README.md ao lado deste script para o passo a passo.

FORMATO DO JSON (ver questoes.exemplo.json)
--------------------------------------------
Lista de objetos. Campos obrigatórios: discipline, exam_board, difficulty,
statement, alternatives (2 a 5, exatamente uma com is_correct=true).
Campos opcionais: subject, topic, organization, exam_edition, year,
explanation, tags (lista de nomes), attachments (imagens), publish.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# --- módulos da própria aplicação (rodar este script a partir da raiz do
#     repositório do backend, com o venv/deps do projeto já instalados) ---
from app.database.session import AsyncSessionFactory
from app.models.content.exam_source import ExamBoard, ExamEdition, Organization
from app.models.content.question import Question
from app.models.content.question_attachment import QuestionAttachment
from app.models.content.question_tag import QuestionTag
from app.models.content.taxonomy import Discipline, Subject, Topic
from app.models.enums import AttachmentType, QuestionDifficulty, QuestionStatus
from app.models.identity.user import User
from app.schemas.content.question import QuestionAlternativeInput, QuestionCreateRequest
from app.services.content.question_service import QuestionService


# --------------------------------------------------------------------------- #
# Helpers de slug (mesma ideia usada nos modelos: nome legível + slug único)  #
# --------------------------------------------------------------------------- #


def slugify(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^\w\s-]", "", value).strip().lower()
    return re.sub(r"[\s_-]+", "-", value)


# --------------------------------------------------------------------------- #
# Leitura de entrada: JSON (formato nativo) ou XLSX (planilha-modelo)         #
# --------------------------------------------------------------------------- #


def _clean(value):
    """Normaliza célula de planilha: NaN/None -> None; string -> stripada."""
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


# Padrões que, no meio de um enunciado colado de uma planilha/PDF, marcam o
# início de um novo item e por isso merecem quebra de linha própria:
#   - algarismos romanos numerados ("I.", "II.", "III.", "IV." — até XX)
#   - alternativas de julgamento Certo/Errado em parênteses, com ou sem
#     espaços dentro ("( )", "(  )", "(x)")
# Ambos aparecem sempre precedidos de espaço (nunca no início da string) e
# são a fonte nº1 de "questão quebrada" quando a célula do Excel não tem
# quebra de linha manual (Alt+Enter). Ver README da seção de importação.
_ITEM_BREAK_PATTERN = re.compile(
    r"[ \t]+(?=(?:X{0,2}(?:IX|IV|V?I{1,3})\.|(?:\(\s*[xX]?\s*\))))"
)


def normalize_statement_breaks(text: str) -> str:
    """Insere quebra de linha real antes de cada item 'I.', 'II.', 'III.'...
    e de cada marcador de julgamento '( )' encontrado dentro do enunciado.

    Só entra em ação se o texto ainda não tiver nenhuma quebra de linha —
    se quem preencheu a planilha já usou Alt+Enter, respeitamos o que foi
    digitado e não mexemos em nada."""
    if text is None or "\n" in text:
        return text
    return _ITEM_BREAK_PATTERN.sub("\n", text)


def _row_to_item(row: dict) -> dict:
    """Converte uma linha da planilha-modelo (colunas achatadas) no mesmo
    formato de item usado pelo JSON nativo (dicts aninhados)."""
    item: dict = {}

    item["discipline"] = {"name": _clean(row.get("discipline_name"))}
    if _clean(row.get("discipline_slug")):
        item["discipline"]["slug"] = _clean(row["discipline_slug"])

    if _clean(row.get("subject_name")):
        item["subject"] = {"name": _clean(row["subject_name"])}
        if _clean(row.get("subject_slug")):
            item["subject"]["slug"] = _clean(row["subject_slug"])

    if _clean(row.get("topic_name")):
        item["topic"] = {"name": _clean(row["topic_name"])}
        if _clean(row.get("topic_slug")):
            item["topic"]["slug"] = _clean(row["topic_slug"])

    item["exam_board"] = {"name": _clean(row.get("exam_board_name"))}
    if _clean(row.get("exam_board_acronym")):
        item["exam_board"]["acronym"] = _clean(row["exam_board_acronym"])

    if _clean(row.get("organization_name")):
        item["organization"] = {"name": _clean(row["organization_name"])}
        if _clean(row.get("organization_acronym")):
            item["organization"]["acronym"] = _clean(row["organization_acronym"])

    if _clean(row.get("exam_edition_name")):
        edition_year = _clean(row.get("exam_edition_year"))
        item["exam_edition"] = {
            "name": _clean(row["exam_edition_name"]),
            "year": int(edition_year) if edition_year is not None else None,
        }

    year = _clean(row.get("year"))
    item["year"] = int(year) if year is not None else None
    item["difficulty"] = _clean(row.get("difficulty"))
    item["statement"] = normalize_statement_breaks(_clean(row.get("statement")))
    item["explanation"] = _clean(row.get("explanation"))

    correct_letter = (_clean(row.get("correct_letter")) or "").upper()
    alternatives = []
    for letter in ["A", "B", "C", "D", "E"]:
        text = _clean(row.get(f"alt_{letter.lower()}_text"))
        if text:
            alternatives.append({"letter": letter, "text": text, "is_correct": letter == correct_letter})
    item["alternatives"] = alternatives

    tags_raw = _clean(row.get("tags"))
    item["tags"] = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else []

    images_raw = _clean(row.get("image_urls"))
    item["attachments"] = (
        [{"type": "imagem", "url": u.strip()} for u in images_raw.split(",") if u.strip()]
        if images_raw
        else []
    )

    publish_raw = (_clean(row.get("publish")) or "").strip().lower()
    item["publish"] = publish_raw in {"sim", "s", "yes", "true", "1", "verdadeiro"}

    return item


def load_items(path: str) -> list[dict]:
    suffix = Path(path).suffix.lower()
    if suffix == ".json":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError("O JSON de entrada deve ser uma lista de questões.")
        for item in data:
            if item.get("statement"):
                item["statement"] = normalize_statement_breaks(item["statement"])
        return data

    if suffix in (".xlsx", ".xlsm"):
        # Linha 1 = chaves técnicas (cabeçalho real p/ o pandas), linha 2 =
        # rótulo em português (pulada), linha 3 em diante = dados.
        df = pd.read_excel(path, sheet_name="Questões", header=0, skiprows=[1])
        df = df.dropna(how="all")  # descarta linhas totalmente em branco
        return [_row_to_item(row.to_dict()) for _, row in df.iterrows()]

    raise ValueError(f"Formato de arquivo não suportado: '{suffix}'. Use .json, .xlsx ou .xlsm.")


# --------------------------------------------------------------------------- #
# get_or_create — mesmo padrão de scripts/seed_test_data.py                   #
# --------------------------------------------------------------------------- #


async def get_or_create_discipline(session: AsyncSession, *, name: str, slug: str | None = None) -> Discipline:
    slug = slug or slugify(name)
    result = await session.execute(select(Discipline).where(Discipline.slug == slug))
    obj = result.scalar_one_or_none()
    if obj:
        return obj
    obj = Discipline(name=name, slug=slug)
    session.add(obj)
    await session.flush()
    return obj


async def get_or_create_subject(
    session: AsyncSession, *, discipline: Discipline, name: str, slug: str | None = None
) -> Subject:
    slug = slug or slugify(name)
    result = await session.execute(select(Subject).where(Subject.slug == slug))
    obj = result.scalar_one_or_none()
    if obj:
        return obj
    obj = Subject(discipline_id=discipline.id, name=name, slug=slug)
    session.add(obj)
    await session.flush()
    return obj


async def get_or_create_topic(
    session: AsyncSession, *, subject: Subject, name: str, slug: str | None = None
) -> Topic:
    slug = slug or slugify(name)
    result = await session.execute(select(Topic).where(Topic.slug == slug))
    obj = result.scalar_one_or_none()
    if obj:
        return obj
    obj = Topic(subject_id=subject.id, name=name, slug=slug)
    session.add(obj)
    await session.flush()
    return obj


async def get_or_create_exam_board(
    session: AsyncSession, *, name: str, acronym: str | None = None, slug: str | None = None
) -> ExamBoard:
    slug = slug or slugify(name)
    result = await session.execute(select(ExamBoard).where(ExamBoard.slug == slug))
    obj = result.scalar_one_or_none()
    if obj:
        return obj
    obj = ExamBoard(name=name, acronym=acronym or name, slug=slug)
    session.add(obj)
    await session.flush()
    return obj


async def get_or_create_organization(
    session: AsyncSession, *, name: str, acronym: str | None = None, slug: str | None = None
) -> Organization:
    slug = slug or slugify(name)
    result = await session.execute(select(Organization).where(Organization.slug == slug))
    obj = result.scalar_one_or_none()
    if obj:
        return obj
    obj = Organization(name=name, acronym=acronym or name, slug=slug)
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
    slug: str | None = None,
) -> ExamEdition:
    slug = slug or slugify(name)
    result = await session.execute(select(ExamEdition).where(ExamEdition.slug == slug))
    obj = result.scalar_one_or_none()
    if obj:
        return obj
    obj = ExamEdition(
        organization_id=organization.id, exam_board_id=exam_board.id, year=year, name=name, slug=slug
    )
    session.add(obj)
    await session.flush()
    return obj


async def get_or_create_tag(session: AsyncSession, *, name: str, slug: str | None = None) -> QuestionTag:
    slug = slug or slugify(name)
    result = await session.execute(select(QuestionTag).where(QuestionTag.slug == slug))
    obj = result.scalar_one_or_none()
    if obj:
        return obj
    obj = QuestionTag(name=name, slug=slug)
    session.add(obj)
    await session.flush()
    return obj


async def fetch_admin_id(email: str):
    """Sessão curta e isolada só para resolver o admin_id (um UUID simples,
    sem estado de ORM) antes do loop principal — evita reusar/expirar o
    mesmo objeto `User` entre transações de itens diferentes."""
    async with AsyncSessionFactory() as session:
        result = await session.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if user is None:
            raise RuntimeError(
                f"Usuário admin '{email}' não encontrado. Crie-o antes (ex.: scripts/seed_admin.py) "
                "— este script não cadastra usuários, só questões."
            )
        if not user.is_admin:
            raise RuntimeError(f"Usuário '{email}' existe mas não é admin. Promova-o antes de importar.")
        return user.id


# --------------------------------------------------------------------------- #
# Resolução de uma questão do JSON -> QuestionCreateRequest + extras          #
# --------------------------------------------------------------------------- #


@dataclass
class ImportResult:
    total: int = 0
    created: int = 0
    published: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[dict] = field(default_factory=list)


async def is_duplicate(session: AsyncSession, statement: str) -> bool:
    prefix = statement.strip()[:120]
    result = await session.execute(select(Question.id).where(Question.statement.ilike(f"{prefix}%")))
    return result.scalar_one_or_none() is not None


async def resolve_taxonomy(session: AsyncSession, item: dict) -> dict:
    """Cria/recupera disciplina, assunto, tópico, banca, órgão e edição a
    partir dos nomes informados no JSON, retornando os UUIDs prontos para o
    QuestionCreateRequest."""
    discipline = await get_or_create_discipline(session, **item["discipline"])
    subject = None
    if item.get("subject"):
        subject = await get_or_create_subject(session, discipline=discipline, **item["subject"])
    topic = None
    if item.get("topic"):
        if subject is None:
            raise ValueError("`topic` informado sem `subject` — tópico depende de um assunto.")
        topic = await get_or_create_topic(session, subject=subject, **item["topic"])

    exam_board = await get_or_create_exam_board(session, **item["exam_board"])

    organization = None
    if item.get("organization"):
        organization = await get_or_create_organization(session, **item["organization"])

    exam_edition = None
    if item.get("exam_edition"):
        if organization is None:
            raise ValueError("`exam_edition` informado sem `organization`.")
        exam_edition = await get_or_create_exam_edition(
            session, organization=organization, exam_board=exam_board, **item["exam_edition"]
        )

    tags = []
    for tag_name in item.get("tags", []):
        tags.append(await get_or_create_tag(session, name=tag_name))

    return {
        "discipline_id": discipline.id,
        "subject_id": subject.id if subject else None,
        "topic_id": topic.id if topic else None,
        "exam_board_id": exam_board.id,
        "organization_id": organization.id if organization else None,
        "exam_edition_id": exam_edition.id if exam_edition else None,
        "tag_ids": [t.id for t in tags],
    }


async def import_one(
    admin_id,
    item: dict,
    *,
    dry_run: bool,
    skip_duplicates: bool,
    publish_flagged: bool,
) -> str:
    """Abre e fecha sua própria sessão/transação — cada questão é uma unidade
    isolada, então uma falha numa não deixa a sessão de outra em estado
    inconsistente. Retorna 'created', 'published', ou 'skipped'."""

    async with AsyncSessionFactory() as session:
        if skip_duplicates and await is_duplicate(session, item["statement"]):
            return "skipped"

        ids = await resolve_taxonomy(session, item)

        request = QuestionCreateRequest(
            discipline_id=ids["discipline_id"],
            subject_id=ids["subject_id"],
            topic_id=ids["topic_id"],
            exam_board_id=ids["exam_board_id"],
            exam_edition_id=ids["exam_edition_id"],
            organization_id=ids["organization_id"],
            year=item.get("year"),
            difficulty=QuestionDifficulty(item["difficulty"]),
            statement=item["statement"],
            explanation=item.get("explanation"),
            alternatives=[QuestionAlternativeInput(**alt) for alt in item["alternatives"]],
            tag_ids=ids["tag_ids"],
        )

        if dry_run:
            # Os validators do Pydantic já rodaram ao montar `request` acima.
            # Desfaz qualquer get_or_create que tenha dado flush (taxonomia
            # nova só criada de fato em uma rodada sem --dry-run).
            await session.rollback()
            return "created"

        service = QuestionService(session)
        question = await service.create_question(admin_id, request)

        if item.get("attachments"):
            for attachment in item["attachments"]:
                session.add(
                    QuestionAttachment(
                        question_id=question.id,
                        type=AttachmentType(attachment.get("type", "imagem")),
                        url=attachment["url"],
                        alt_text=attachment.get("alt_text"),
                    )
                )
            await session.commit()

        if publish_flagged and item.get("publish"):
            await service.update_status(question.id, admin_id, QuestionStatus.PUBLICADA)
            return "published"

        return "created"


# --------------------------------------------------------------------------- #
# Entry point                                                                  #
# --------------------------------------------------------------------------- #


async def run(args: argparse.Namespace) -> ImportResult:
    data = load_items(args.file)
    result = ImportResult(total=len(data))
    admin_id = await fetch_admin_id(args.admin_email)

    for index, item in enumerate(data, start=1):
        label = item.get("statement", "")[:60].replace("\n", " ")
        try:
            outcome = await import_one(
                admin_id,
                item,
                dry_run=args.dry_run,
                skip_duplicates=args.skip_duplicates,
                publish_flagged=args.publish_flagged,
            )
            if outcome == "skipped":
                result.skipped += 1
                print(f"[{index}/{result.total}] ⏭️  duplicada, pulada — {label}...")
            elif outcome == "published":
                result.created += 1
                result.published += 1
                print(f"[{index}/{result.total}] ✅ criada e publicada — {label}...")
            else:
                result.created += 1
                print(f"[{index}/{result.total}] ✅ criada (rascunho) — {label}...")
        except Exception as exc:  # noqa: BLE001 — queremos continuar o lote
            result.failed += 1
            result.errors.append({"index": index, "statement_preview": label, "error": str(exc)})
            print(f"[{index}/{result.total}] ❌ falhou — {label}... ({exc})")

    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--file", required=True, help="Caminho do arquivo com as questões: .json, .xlsx ou .xlsm."
    )
    parser.add_argument("--admin-email", required=True, help="E-mail de um usuário admin já existente.")
    parser.add_argument(
        "--dry-run", action="store_true", help="Só valida (schema + regras) sem gravar nada no banco."
    )
    parser.add_argument(
        "--skip-duplicates",
        action="store_true",
        help="Pula questões cujos 120 primeiros caracteres do enunciado já existem no banco.",
    )
    parser.add_argument(
        "--publish-flagged",
        action="store_true",
        help='Publica (status "publicada") as questões que tiverem "publish": true no JSON. '
        "Sem esta flag, tudo entra como rascunho — igual ao comportamento padrão da API.",
    )
    parser.add_argument(
        "--report",
        default=None,
        help="Caminho para salvar um relatório JSON com o resultado (padrão: não salva).",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    result = await run(args)

    print("\n" + "=" * 60)
    print("Resumo da importação")
    print("=" * 60)
    print(f"Total no arquivo:  {result.total}")
    print(f"Criadas:           {result.created}")
    print(f"  (publicadas):    {result.published}")
    print(f"Puladas (dup.):    {result.skipped}")
    print(f"Falharam:          {result.failed}")
    if args.dry_run:
        print("\n⚠️  Modo --dry-run: nada foi gravado no banco.")

    if result.errors:
        print("\nErros:")
        for err in result.errors:
            print(f"  #{err['index']}: {err['statement_preview']}... -> {err['error']}")

    if args.report:
        Path(args.report).write_text(
            json.dumps(
                {
                    "total": result.total,
                    "created": result.created,
                    "published": result.published,
                    "skipped": result.skipped,
                    "failed": result.failed,
                    "errors": result.errors,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"\nRelatório salvo em {args.report}")

    if result.failed:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
