# app/services/export/session_print_service.py
"""Geração do PDF de impressão configurável da sessão de resolução.

Contraparte de `notebook_pdf_service.py` (que exporta um `Notebook`
inteiro, sem opções), mas para a sessão de treino ativa
(`TrainingSession`/`TrainingSessionQuestion` — não é a mesma tabela que
`Notebook`), e com as opções pedidas na tela "Imprimir" (item 3 do
prompt de continuidade): quantidade máxima, o que entra no cabeçalho,
onde o gabarito aparece, tamanho da fonte, espaço para rascunho.

A filtragem (quais questões entram: excluir respondidas/acertadas/
favoritadas, corte por quantidade máxima) é feita ANTES de chegar aqui,
em `TrainingSessionService.select_questions_for_print` — este módulo só
desenha o PDF a partir da lista já decidida, mesma separação de
responsabilidade que `notebook_pdf_service.build_notebook_pdf` já usa
(monta PDF a partir de `items` prontos).

Decisão de escopo (avisada ao aluno): sem QR code por questão — não há
hoje uma rota pública de questão individual que sustente isso com
segurança, e sem cota diária de impressão — o catálogo de features
(`FeatureKey`) só tem cota para responder questões (`DAILY_QUESTIONS`),
não para exportar/imprimir; não inventamos uma regra de negócio nova
aqui.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from re import sub
from typing import Literal
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    HRFlowable,
    KeepTogether,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from app.models.content.question import Question
from app.services.export.assets import BRAND_LOGO_PNG_B64

AnswerKeyMode = Literal["end", "inline", "none"]
PrintFontSize = Literal["sm", "md", "lg"]

_BRAND = {
    "ink": colors.HexColor("#0F172A"),
    "muted": colors.HexColor("#64748B"),
    "line": colors.HexColor("#E2E8F0"),
    "surface": colors.HexColor("#F8FAFC"),
    "accent": colors.HexColor("#F59E0B"),
    "accent_ink": colors.HexColor("#7C2D12"),
}

_DIFFICULTY_LABEL = {
    "FACIL": "Fácil",
    "MEDIO": "Médio",
    "DIFICIL": "Difícil",
}

# Multiplicador aplicado sobre os tamanhos-base de fonte/leading definidos
# abaixo — evita duplicar todo o bloco de ParagraphStyle para cada tamanho.
_FONT_SCALE: dict[PrintFontSize, float] = {
    "sm": 0.88,
    "md": 1.0,
    "lg": 1.16,
}

_LOGO_READER = ImageReader(BytesIO(base64.b64decode(BRAND_LOGO_PNG_B64)))
_LOGO_ASPECT = 276 / 300


@dataclass(frozen=True, slots=True)
class SessionPrintOptions:
    """Opções configuráveis da tela "Imprimir" — já validadas/normalizadas
    pelo schema Pydantic antes de chegar aqui (ver `PrintSessionQuery`)."""

    answer_key_mode: AnswerKeyMode = "none"
    font_size: PrintFontSize = "md"
    include_draft_space: bool = False
    header_student_name: bool = True
    header_date: bool = True
    header_summary: bool = True


def _safe_text(value: str | None) -> str:
    if not value:
        return ""
    return escape(value).replace("\n", "<br/>")


def _filename(value: str) -> str:
    value = sub(r"[^A-Za-z0-9À-ÿ _-]+", "", value).strip()
    value = sub(r"\s+", "-", value)
    return value[:80] or "sessao-de-treino"


class _NumberedCanvas(pdfcanvas.Canvas):
    """Mesma técnica de `notebook_pdf_service._NumberedCanvas`: guarda cada
    página desenhada e só escreve "Página X de Y" em `save()`, quando o
    total de páginas já é conhecido."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states: list[dict] = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self._draw_page_number(total_pages)
            super().showPage()
        super().save()

    def _draw_page_number(self, total_pages: int) -> None:
        self.setFont("Helvetica", 8)
        self.setFillColor(_BRAND["muted"])
        self.drawRightString(
            192 * mm, 9 * mm, f"Página {self._pageNumber} de {total_pages}"
        )


def build_session_print_pdf(
    *,
    title: str,
    questions: list[Question],
    options: SessionPrintOptions,
    student_name: str | None = None,
) -> tuple[bytes, str]:
    """Monta o PDF de impressão a partir das questões já filtradas
    (ordem preservada) e das opções escolhidas na tela de impressão.

    Retorna (bytes do PDF, nome de arquivo seguro).
    """
    buffer = BytesIO()
    scale = _FONT_SCALE[options.font_size]

    styles = getSampleStyleSheet()

    eyebrow = ParagraphStyle(
        "Eyebrow",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8.5 * scale,
        leading=11 * scale,
        alignment=TA_CENTER,
        textColor=_BRAND["accent_ink"],
        spaceAfter=2 * mm,
    )
    title_style = ParagraphStyle(
        "SessionTitle",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=22 * scale,
        leading=26 * scale,
        alignment=TA_CENTER,
        textColor=_BRAND["ink"],
        spaceAfter=3 * mm,
    )
    subtitle = ParagraphStyle(
        "SessionSubtitle",
        parent=styles["Normal"],
        fontSize=9.5 * scale,
        leading=13 * scale,
        alignment=TA_CENTER,
        textColor=_BRAND["muted"],
        spaceAfter=2 * mm,
    )
    question_number = ParagraphStyle(
        "QuestionNumber",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=11 * scale,
        leading=13 * scale,
        textColor=colors.white,
        alignment=TA_CENTER,
    )
    chip_text = ParagraphStyle(
        "ChipText",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=7.5 * scale,
        leading=9 * scale,
        textColor=_BRAND["muted"],
    )
    question_statement = ParagraphStyle(
        "QuestionStatement",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=10.5 * scale,
        leading=15.5 * scale,
        textColor=_BRAND["ink"],
        spaceBefore=2.5 * mm,
        spaceAfter=3.5 * mm,
    )
    alternative = ParagraphStyle(
        "Alternative",
        parent=styles["BodyText"],
        fontSize=10 * scale,
        leading=14.5 * scale,
        leftIndent=6 * mm,
        firstLineIndent=-6 * mm,
        spaceAfter=2 * mm,
        textColor=_BRAND["ink"],
    )
    inline_answer = ParagraphStyle(
        "InlineAnswer",
        parent=styles["BodyText"],
        fontName="Helvetica-Bold",
        fontSize=9.5 * scale,
        leading=13 * scale,
        textColor=_BRAND["accent_ink"],
        spaceBefore=1.5 * mm,
    )
    section = ParagraphStyle(
        "Section",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=14,
        leading=18,
        textColor=colors.white,
    )
    answer_cell = ParagraphStyle(
        "AnswerCell",
        parent=styles["BodyText"],
        fontName="Helvetica-Bold",
        fontSize=10,
        leading=13,
        alignment=TA_CENTER,
        textColor=_BRAND["ink"],
    )

    # ---------------------------------------------------------------- #
    # Cabeçalho / rodapé de marca — desenhados em TODAS as páginas.     #
    # ---------------------------------------------------------------- #
    def _brand_header(canvas_obj: pdfcanvas.Canvas) -> None:
        logo_h = 8 * mm
        logo_w = logo_h * _LOGO_ASPECT
        x = 18 * mm
        y = 279 * mm
        canvas_obj.drawImage(
            _LOGO_READER,
            x,
            y,
            width=logo_w,
            height=logo_h,
            mask="auto",
            preserveAspectRatio=True,
        )
        canvas_obj.setFont("Helvetica-Bold", 12)
        canvas_obj.setFillColor(_BRAND["ink"])
        canvas_obj.drawString(x + logo_w + 3 * mm, y + 2.6 * mm, "ALFA CAVEIRA")
        canvas_obj.setFont("Helvetica", 7)
        canvas_obj.setFillColor(_BRAND["muted"])
        canvas_obj.drawString(
            x + logo_w + 3 * mm, y - 1.6 * mm, "Plataforma de estudos para concursos"
        )

        canvas_obj.setFont("Helvetica", 7.5)
        canvas_obj.setFillColor(_BRAND["muted"])
        canvas_obj.drawRightString(192 * mm, y + 1 * mm, escape(title)[:70])

        canvas_obj.setStrokeColor(_BRAND["line"])
        canvas_obj.setLineWidth(0.6)
        canvas_obj.line(18 * mm, 276 * mm, 192 * mm, 276 * mm)

    def _brand_footer(canvas_obj: pdfcanvas.Canvas) -> None:
        canvas_obj.setStrokeColor(_BRAND["line"])
        canvas_obj.setLineWidth(0.6)
        canvas_obj.line(18 * mm, 13 * mm, 192 * mm, 13 * mm)
        canvas_obj.setFont("Helvetica", 7.5)
        canvas_obj.setFillColor(_BRAND["muted"])
        canvas_obj.drawString(
            18 * mm,
            9 * mm,
            f"Gerado em {datetime.now().strftime('%d/%m/%Y')} · alfacaveira.com.br",
        )

    def _on_page(canvas_obj: pdfcanvas.Canvas, doc_obj) -> None:
        canvas_obj.saveState()
        _brand_header(canvas_obj)
        _brand_footer(canvas_obj)
        canvas_obj.restoreState()

    doc = BaseDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=26 * mm,
        bottomMargin=18 * mm,
        title=title,
        author="Alfa Caveira",
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="normal")
    doc.addPageTemplates([PageTemplate(id="main", frames=frame, onPage=_on_page)])

    total = len(questions)
    generated_at = datetime.now().strftime("%d/%m/%Y às %H:%M")

    story: list = [
        Paragraph("SESSÃO DE RESOLUÇÃO", eyebrow),
        Paragraph(_safe_text(title), title_style),
    ]

    if options.header_summary:
        subtitle_bits = [f"{total} questão{'ões' if total != 1 else ''}"]
        if options.header_student_name and student_name:
            subtitle_bits.append(f"Aluno(a): {student_name}")
        if options.header_date:
            subtitle_bits.append(f"Gerado em {generated_at}")
        story.append(Paragraph(" · ".join(subtitle_bits), subtitle))
    elif options.header_date:
        story.append(Paragraph(f"Gerado em {generated_at}", subtitle))

    story.append(Spacer(1, 5 * mm))

    # ---------------------------------------------------------------- #
    # Questões                                                          #
    # ---------------------------------------------------------------- #
    for position, question in enumerate(questions, start=1):
        board = getattr(question.exam_board, "acronym", None) or getattr(
            question.exam_board, "name", ""
        )
        org = getattr(question.organization, "acronym", None) or getattr(
            question.organization, "name", ""
        )
        discipline = getattr(question.discipline, "name", "")
        subject = getattr(question.subject, "name", "") if question.subject else ""
        year = getattr(question, "year", None)
        difficulty = _DIFFICULTY_LABEL.get(
            getattr(getattr(question, "difficulty", None), "value", None)
            or str(getattr(question, "difficulty", "")),
            None,
        )

        chip_bits = [b for b in [board, org, discipline, subject, year] if b]
        if difficulty:
            chip_bits.append(difficulty)
        chips_line = "  •  ".join(str(b) for b in chip_bits)

        header_row = Table(
            [
                [
                    Table(
                        [[Paragraph(f"{position:02d}", question_number)]],
                        colWidths=[9 * mm],
                        rowHeights=[9 * mm],
                        style=TableStyle(
                            [
                                ("BACKGROUND", (0, 0), (-1, -1), _BRAND["ink"]),
                                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                            ]
                        ),
                    ),
                    Paragraph(_safe_text(chips_line) or "Questão", chip_text),
                ]
            ],
            colWidths=[11 * mm, doc.width - 11 * mm],
            style=TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ]
            ),
        )

        # Cabeçalho + enunciado ficam juntos (evita "questão órfã" no topo
        # da página seguinte); as alternativas, não — questão muito longa
        # pode ultrapassar uma página A4, e forçar tudo junto causa
        # LayoutError (mesma decisão de `notebook_pdf_service`).
        story.append(
            KeepTogether(
                [
                    header_row,
                    Paragraph(_safe_text(question.statement), question_statement),
                ]
            )
        )

        for alt in question.alternatives:
            story.append(
                Paragraph(
                    f"<b>{escape(alt.letter)})</b> {_safe_text(alt.text)}",
                    alternative,
                )
            )

        # Gabarito logo abaixo da própria questão — só quando o modo
        # escolhido é "inline" (a alternativa do resto do menu é "end",
        # que reaproveita o bloco de gabarito em grade no fim do PDF).
        if options.answer_key_mode == "inline":
            story.append(
                Paragraph(
                    f"Gabarito: <font color='#7C2D12'>{escape(question.correct_alternative_letter)}</font>",
                    inline_answer,
                )
            )

        # Espaço para rascunho — algumas linhas em branco com régua sutil,
        # útil pra quem quer fazer conta/anotação ao lado da questão sem
        # rabiscar em cima do enunciado.
        if options.include_draft_space:
            story.append(Spacer(1, 3 * mm))
            story.append(
                Paragraph(
                    "RASCUNHO",
                    ParagraphStyle(
                        "DraftLabel",
                        parent=chip_text,
                        textColor=_BRAND["muted"],
                    ),
                )
            )
            for _ in range(3):
                story.append(Spacer(1, 6 * mm))
                story.append(
                    HRFlowable(
                        width=doc.width, color=_BRAND["line"], thickness=0.4, dash=(1, 2)
                    )
                )

        story.append(Spacer(1, 2 * mm))
        story.append(HRFlowable(width=doc.width, color=_BRAND["line"], thickness=0.6))
        story.append(Spacer(1, 5 * mm))

    # ---------------------------------------------------------------- #
    # Gabarito em grade, no fim do PDF                                  #
    # ---------------------------------------------------------------- #
    if options.answer_key_mode == "end":
        story.append(
            Table(
                [[Paragraph("GABARITO", section)]],
                colWidths=[doc.width],
                style=TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, -1), _BRAND["ink"]),
                        ("LEFTPADDING", (0, 0), (-1, -1), 5 * mm),
                        ("TOPPADDING", (0, 0), (-1, -1), 3 * mm),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm),
                    ]
                ),
            )
        )
        story.append(Spacer(1, 4 * mm))

        cols = 5
        rows: list[list] = []
        row: list = []
        for position, question in enumerate(questions, start=1):
            row.append(
                Paragraph(
                    f"{position:02d} — <font color='#7C2D12'>"
                    f"{escape(question.correct_alternative_letter)}</font>",
                    answer_cell,
                )
            )
            if len(row) == cols:
                rows.append(row)
                row = []
        if row:
            while len(row) < cols:
                row.append(Paragraph("", answer_cell))
            rows.append(row)

        zebra = [
            ("BACKGROUND", (0, r), (-1, r), _BRAND["surface"] if r % 2 else colors.white)
            for r in range(len(rows))
        ]
        story.append(
            Table(
                rows,
                colWidths=[doc.width / cols] * cols,
                style=TableStyle(
                    [
                        ("GRID", (0, 0), (-1, -1), 0.5, _BRAND["line"]),
                        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                        ("TOPPADDING", (0, 0), (-1, -1), 3 * mm),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm),
                        *zebra,
                    ]
                ),
            )
        )

    doc.build(story, canvasmaker=_NumberedCanvas)
    return buffer.getvalue(), f"{_filename(title)}.pdf"
