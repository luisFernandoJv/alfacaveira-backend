#!/usr/bin/env python
"""Seed de provas anteriores para desenvolvimento."""

import asyncio
import uuid

from sqlalchemy import select

from app.database.session import AsyncSessionFactory
from app.models.content.exam_paper import ExamPaper, ExamPaperQuestion
from app.models.content.exam_source import ExamBoard, Organization
from app.models.content.question import Question


async def seed_exam_papers():
    async with AsyncSessionFactory() as session:
        # Buscar banca e órgão existentes
        board_result = await session.execute(
            select(ExamBoard).where(ExamBoard.slug == "cebraspe")
        )
        board = board_result.scalar_one_or_none()

        org_result = await session.execute(
            select(Organization).where(Organization.slug == "pp-rn")
        )
        org = org_result.scalar_one_or_none()

        if not board or not org:
            print("❌ Banca ou órgão não encontrados. Execute seed_test_data.py primeiro.")
            return

        print(f"✅ Banca: {board.name} (ID: {board.id})")
        print(f"✅ Órgão: {org.name} (ID: {org.id})")

        # Buscar questões existentes
        questions_result = await session.execute(
            select(Question).where(Question.status == "publicada")
        )
        questions = questions_result.scalars().all()

        if len(questions) < 5:
            print("❌ Poucas questões disponíveis. Execute seed_test_data.py primeiro.")
            return

        print(f"✅ Encontradas {len(questions)} questões para adicionar às provas.")

        # --- Prova 1: 2026 ---
        paper1 = ExamPaper(
            id=uuid.uuid4(),
            title="Concurso Polícia Penal RN 2026 - Prova Completa",
            description="Prova completa do concurso para Polícia Penal do Rio Grande do Norte, aplicada em 2026 pela CEBRASPE. Contém questões de Direito Penal, Direito Processual Penal, Legislação Especial e Português.",
            exam_board_id=board.id,
            organization_id=org.id,
            year=2026,
            total_questions=len(questions),
            pdf_url=None,
            is_active=True,
        )
        session.add(paper1)
        await session.flush()

        # Adicionar questões à prova 1
        for position, question in enumerate(questions, start=1):
            paper_question = ExamPaperQuestion(
                id=uuid.uuid4(),
                exam_paper_id=paper1.id,
                question_id=question.id,
                position=position,
            )
            session.add(paper_question)

        print(f"✅ Prova 1 criada: {paper1.title} ({paper1.total_questions} questões)")

        # --- Prova 2: 2024 ---
        paper2 = ExamPaper(
            id=uuid.uuid4(),
            title="Concurso Polícia Penal RN 2024 - Prova Completa",
            description="Prova completa do concurso para Polícia Penal do Rio Grande do Norte, aplicada em 2024 pela CEBRASPE. Questões de Direito Penal, Processo Penal e Legislação Especial.",
            exam_board_id=board.id,
            organization_id=org.id,
            year=2024,
            total_questions=min(len(questions), 10),
            pdf_url=None,
            is_active=True,
        )
        session.add(paper2)
        await session.flush()

        # Adicionar questões à prova 2 (apenas as 10 primeiras)
        for position, question in enumerate(questions[:10], start=1):
            paper_question = ExamPaperQuestion(
                id=uuid.uuid4(),
                exam_paper_id=paper2.id,
                question_id=question.id,
                position=position,
            )
            session.add(paper_question)

        print(f"✅ Prova 2 criada: {paper2.title} ({paper2.total_questions} questões)")

        # --- Prova 3: 2022 ---
        paper3 = ExamPaper(
            id=uuid.uuid4(),
            title="Simulado PRF 2022 - Direito Constitucional",
            description="Simulado focado em Direito Constitucional para a Polícia Rodoviária Federal, com questões da CEBRASPE.",
            exam_board_id=board.id,
            organization_id=org.id,
            year=2022,
            total_questions=min(len(questions), 8),
            pdf_url=None,
            is_active=True,
        )
        session.add(paper3)
        await session.flush()

        # Adicionar questões à prova 3
        for position, question in enumerate(questions[:8], start=1):
            paper_question = ExamPaperQuestion(
                id=uuid.uuid4(),
                exam_paper_id=paper3.id,
                question_id=question.id,
                position=position,
            )
            session.add(paper_question)

        print(f"✅ Prova 3 criada: {paper3.title} ({paper3.total_questions} questões)")

        await session.commit()

        # Exibir resumo
        print("\n📊 Resumo:")
        result = await session.execute(
            select(ExamPaper).where(ExamPaper.is_active.is_(True))
        )
        all_papers = result.scalars().all()
        print(f"Total de provas ativas: {len(all_papers)}")
        for p in all_papers:
            print(f"  - {p.title} ({p.year}) - {p.total_questions} questões")


if __name__ == "__main__":
    asyncio.run(seed_exam_papers())