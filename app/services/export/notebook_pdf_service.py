"""Geração de cadernos PDF com layout profissional.

O PDF é montado no backend para que o aluno receba um arquivo real, com
paginação, cabeçalho, identificação da prova/disciplina e gabarito opcional.
Nenhum conteúdo é aceito do cliente além dos IDs das questões já pertencentes
ao caderno autenticado.
"""

from __future__ import annotations

from io import BytesIO
from re import sub
from xml.sax.saxutils import escape

from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepTogether,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.lib import colors


def _safe_text(value: str | None) -> str:
    if not value:
        return ""
    return escape(value).replace("\n", "<br/>")


def _filename(value: str) -> str:
    value = sub(r"[^A-Za-z0-9À-ÿ _-]+", "", value).strip()
    value = sub(r"\s+", "-", value)
    return value[:80] or "caderno-de-questoes"


def build_notebook_pdf(
    notebook,
    items,
    *,
    include_answer_key: bool = False,
) -> tuple[bytes, str]:
    """Retorna bytes do PDF e nome de arquivo seguro."""
    buffer = BytesIO()

    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        "NotebookTitle",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=20,
        leading=24,
        alignment=TA_CENTER,
        spaceAfter=6 * mm,
    )
    subtitle = ParagraphStyle(
        "NotebookSubtitle",
        parent=styles["Normal"],
        fontSize=9,
        leading=13,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#64748B"),
        spaceAfter=7 * mm,
    )
    question = ParagraphStyle(
        "Question",
        parent=styles["BodyText"],
        fontName="Helvetica-Bold",
        fontSize=10.5,
        leading=15,
        spaceAfter=3 * mm,
    )
    alternative = ParagraphStyle(
        "Alternative",
        parent=styles["BodyText"],
        fontSize=10,
        leading=14,
        leftIndent=5 * mm,
        firstLineIndent=-5 * mm,
        spaceAfter=2.5 * mm,
    )
    meta = ParagraphStyle(
        "Meta",
        parent=styles["BodyText"],
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor("#64748B"),
        spaceAfter=3 * mm,
    )
    section = ParagraphStyle(
        "Section",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=13,
        leading=17,
        spaceBefore=5 * mm,
        spaceAfter=4 * mm,
    )
    answer = ParagraphStyle(
        "Answer",
        parent=styles["BodyText"],
        fontSize=10,
        leading=14,
        spaceAfter=2 * mm,
    )

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#E2E8F0"))
        canvas.line(18 * mm, 13 * mm, 192 * mm, 13 * mm)
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#64748B"))
        canvas.drawString(18 * mm, 9 * mm, "Alfa Caveira · Caderno de questões")
        canvas.drawRightString(192 * mm, 9 * mm, f"Página {doc.page}")
        canvas.restoreState()

    doc = BaseDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=notebook.name,
        author="Alfa Caveira",
    )
    frame = Frame(
        doc.leftMargin,
        doc.bottomMargin,
        doc.width,
        doc.height,
        id="normal",
    )
    doc.addPageTemplates([PageTemplate(id="main", frames=frame, onPage=footer)])

    story = [
        Paragraph("ALFA CAVEIRA", subtitle),
        Paragraph(_safe_text(notebook.name), title),
        Paragraph(
            f"{len(items)} questão{'ões' if len(items) != 1 else ''}"
            + (" · Caderno de estudo" if not notebook.description else ""),
            subtitle,
        ),
    ]

    if notebook.description:
        story.append(Paragraph(_safe_text(notebook.description), subtitle))

    story.append(
        Table(
            [
                [
                    Paragraph("<b>Formato</b><br/>Questões objetivas", meta),
                    Paragraph(
                        f"<b>Gabarito</b><br/>{'Incluído ao final' if include_answer_key else 'Não incluído'}",
                        meta,
                    ),
                    Paragraph("<b>Uso</b><br/>Estudo pessoal", meta),
                ]
            ],
            colWidths=[doc.width / 3] * 3,
            style=TableStyle(
                [
                    ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
                    ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5 * mm),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5 * mm),
                    ("TOPPADDING", (0, 0), (-1, -1), 3 * mm),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm),
                ]
            ),
        )
    )
    story.append(Spacer(1, 7 * mm))

    for position, item in enumerate(items, start=1):
        q = item.question
        board = getattr(q.exam_board, "acronym", None) or getattr(q.exam_board, "name", "")
        discipline = getattr(q.discipline, "name", "")
        year = getattr(q, "year", None)
        meta_line = " · ".join(
            str(part) for part in [board, discipline, year] if part
        )

        blocks = [
            Paragraph(f"{position}. {_safe_text(q.statement)}", question),
        ]
        if meta_line:
            blocks.insert(0, Paragraph(_safe_text(meta_line), meta))

        for alt in q.alternatives:
            blocks.append(
                Paragraph(
                    f"<b>{escape(alt.letter)})</b> {_safe_text(alt.text)}",
                    alternative,
                )
            )

        story.append(
            KeepTogether(
                [
                    Table(
                        [[Paragraph(f"<b>QUESTÃO {position:02d}</b>", meta)]],
                        colWidths=[doc.width],
                        style=TableStyle(
                            [
                                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F1F5F9")),
                                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
                                ("LEFTPADDING", (0, 0), (-1, -1), 4 * mm),
                                ("RIGHTPADDING", (0, 0), (-1, -1), 4 * mm),
                                ("TOPPADDING", (0, 0), (-1, -1), 2 * mm),
                                ("BOTTOMPADDING", (0, 0), (-1, -1), 2 * mm),
                            ]
                        ),
                    ),
                    Spacer(1, 3 * mm),
                    *blocks,
                    Spacer(1, 5 * mm),
                ]
            )
        )

    if include_answer_key:
        story.append(Paragraph("Gabarito", section))
        answer_rows = []
        for position, item in enumerate(items, start=1):
            answer_rows.append(
                [
                    Paragraph(f"<b>{position:02d}</b>", answer),
                    Paragraph(
                        escape(item.question.correct_alternative_letter),
                        answer,
                    ),
                ]
            )
        story.append(
            Table(
                answer_rows,
                colWidths=[25 * mm, 25 * mm],
                style=TableStyle(
                    [
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
                        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
                        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                        ("TOPPADDING", (0, 0), (-1, -1), 3 * mm),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm),
                    ]
                ),
            )
        )

    doc.build(story)
    return buffer.getvalue(), f"{_filename(notebook.name)}.pdf"
