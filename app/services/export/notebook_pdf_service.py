"""Geração de cadernos PDF com layout profissional.

O PDF é montado no backend para que o aluno receba um arquivo real, com
paginação, marca d'água de identidade visual, cabeçalho/rodapé de marca em
todas as páginas, chips de metadado por questão e gabarito opcional em
grade. Nenhum conteúdo é aceito do cliente além dos IDs das questões já
pertencentes ao caderno autenticado.

🔥 REDESIGN (2026-08-22): layout anterior era funcional mas genérico (sem
identidade de marca, sem numeração "página X de Y", metadado da questão em
uma única linha cinza). Este redesign:
  - usa `NumberedCanvas` para numeração "Página X de Y" (2 passes do
    ReportLab: o canvas base já resolve isso sem re-renderizar o story);
  - desenha cabeçalho de marca (logo + nome) e rodapé em TODAS as páginas
    via `onPage`, não só a capa;
  - cada questão ganha um cartão com número em destaque, chips de
    disciplina/banca/ano/dificuldade e tags, em vez de uma linha corrida;
  - gabarito em grade com zebra striping, mais fácil de escanear;
  - paleta de marca (`_BRAND`) centralizada para fácil ajuste futuro.
"""

from __future__ import annotations

import base64
from datetime import datetime
from io import BytesIO
from re import sub
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
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
    NextPageTemplate,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from app.services.export.assets import BRAND_LOGO_PNG_B64

# ==================================================================== #
# PALETA DE MARCA                                                      #
# ==================================================================== #
_BRAND = {
    "ink": colors.HexColor("#0F172A"),       # texto principal
    "muted": colors.HexColor("#64748B"),     # texto secundário
    "line": colors.HexColor("#E2E8F0"),      # divisórias/bordas
    "surface": colors.HexColor("#F8FAFC"),   # fundo sutil
    "surface_alt": colors.HexColor("#F1F5F9"),
    "accent": colors.HexColor("#F59E0B"),    # âmbar — cor de marca (Alfa Caveira)
    "accent_ink": colors.HexColor("#7C2D12"),
    "success": colors.HexColor("#16A34A"),
    "danger": colors.HexColor("#DC2626"),
}

_DIFFICULTY_LABEL = {
    "FACIL": "Fácil",
    "MEDIO": "Médio",
    "DIFICIL": "Difícil",
}

_LOGO_READER = ImageReader(BytesIO(base64.b64decode(BRAND_LOGO_PNG_B64)))
_LOGO_ASPECT = 276 / 300  # largura / altura do PNG de origem


def _safe_text(value: str | None) -> str:
    if not value:
        return ""
    return escape(value).replace("\n", "<br/>")


def _filename(value: str) -> str:
    value = sub(r"[^A-Za-z0-9À-ÿ _-]+", "", value).strip()
    value = sub(r"\s+", "-", value)
    return value[:80] or "caderno-de-questoes"


class _NumberedCanvas(pdfcanvas.Canvas):
    """Canvas que resolve 'Página X de Y' sem precisar montar o story duas vezes.

    ReportLab só sabe o total de páginas depois que TODAS as páginas já
    foram desenhadas. A técnica padrão é: guardar cada página desenhada em
    `_saved_page_states`, e só escrever o número final delas em `save()`,
    quando o total já é conhecido.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

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


def build_notebook_pdf(
    notebook,
    items,
    *,
    include_answer_key: bool = False,
    student_name: str | None = None,
) -> tuple[bytes, str]:
    """Retorna bytes do PDF e nome de arquivo seguro."""
    buffer = BytesIO()

    styles = getSampleStyleSheet()

    brand_wordmark = ParagraphStyle(
        "BrandWordmark",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=13,
        leading=15,
        textColor=_BRAND["ink"],
    )
    brand_tagline = ParagraphStyle(
        "BrandTagline",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=7.5,
        leading=9,
        textColor=_BRAND["muted"],
    )
    eyebrow = ParagraphStyle(
        "Eyebrow",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8.5,
        leading=11,
        alignment=TA_CENTER,
        textColor=_BRAND["accent_ink"],
        spaceAfter=2 * mm,
    )
    title = ParagraphStyle(
        "NotebookTitle",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=22,
        leading=26,
        alignment=TA_CENTER,
        textColor=_BRAND["ink"],
        spaceAfter=3 * mm,
    )
    subtitle = ParagraphStyle(
        "NotebookSubtitle",
        parent=styles["Normal"],
        fontSize=9.5,
        leading=13,
        alignment=TA_CENTER,
        textColor=_BRAND["muted"],
        spaceAfter=2 * mm,
    )
    card_label = ParagraphStyle(
        "CardLabel",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=7.5,
        leading=10,
        textColor=_BRAND["muted"],
    )
    card_value = ParagraphStyle(
        "CardValue",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=14,
        textColor=_BRAND["ink"],
    )
    question_number = ParagraphStyle(
        "QuestionNumber",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=13,
        textColor=colors.white,
        alignment=TA_CENTER,
    )
    chip_text = ParagraphStyle(
        "ChipText",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=7.5,
        leading=9,
        textColor=_BRAND["muted"],
    )
    question_statement = ParagraphStyle(
        "QuestionStatement",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=10.5,
        leading=15.5,
        textColor=_BRAND["ink"],
        spaceBefore=2.5 * mm,
        spaceAfter=3.5 * mm,
    )
    alternative = ParagraphStyle(
        "Alternative",
        parent=styles["BodyText"],
        fontSize=10,
        leading=14.5,
        leftIndent=6 * mm,
        firstLineIndent=-6 * mm,
        spaceAfter=2 * mm,
        textColor=_BRAND["ink"],
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
    footer_meta = ParagraphStyle(
        "FooterMeta",
        parent=styles["Normal"],
        fontSize=7.5,
        leading=9,
        textColor=_BRAND["muted"],
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
        canvas_obj.drawRightString(
            192 * mm, y + 1 * mm, escape(notebook.name)[:70]
        )

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
        # A numeração "Página X de Y" é escrita depois, pelo _NumberedCanvas.

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
    doc.addPageTemplates([PageTemplate(id="main", frames=frame, onPage=_on_page)])

    total = len(items)
    generated_at = datetime.now().strftime("%d/%m/%Y às %H:%M")

    story = [
        Paragraph("CADERNO DE QUESTÕES", eyebrow),
        Paragraph(_safe_text(notebook.name), title),
    ]

    subtitle_bits = [f"{total} questão{'ões' if total != 1 else ''}"]
    if student_name:
        subtitle_bits.append(f"Aluno(a): {student_name}")
    subtitle_bits.append(f"Gerado em {generated_at}")
    story.append(Paragraph(" · ".join(subtitle_bits), subtitle))

    if notebook.description:
        story.append(Paragraph(_safe_text(notebook.description), subtitle))

    story.append(Spacer(1, 5 * mm))
    story.append(
        Table(
            [
                [
                    Paragraph("FORMATO", card_label),
                    Paragraph("GABARITO", card_label),
                    Paragraph("USO", card_label),
                ],
                [
                    Paragraph("Questões objetivas", card_value),
                    Paragraph(
                        "Incluído ao final" if include_answer_key else "Não incluído",
                        card_value,
                    ),
                    Paragraph("Estudo pessoal", card_value),
                ],
            ],
            colWidths=[doc.width / 3] * 3,
            style=TableStyle(
                [
                    ("BOX", (0, 0), (-1, -1), 0.75, _BRAND["line"]),
                    ("INNERGRID", (0, 0), (-1, -1), 0.75, _BRAND["line"]),
                    ("BACKGROUND", (0, 0), (-1, -1), _BRAND["surface"]),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5 * mm),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5 * mm),
                    ("TOPPADDING", (0, 0), (-1, -1), 3.5 * mm),
                    ("BOTTOMPADDING", (0, 0), (0, 0), 1 * mm),
                    ("BOTTOMPADDING", (1, 1), (-1, -1), 3.5 * mm),
                ]
            ),
        )
    )
    story.append(Spacer(1, 8 * mm))

    # ---------------------------------------------------------------- #
    # Questões                                                          #
    # ---------------------------------------------------------------- #
    for position, item in enumerate(items, start=1):
        q = item.question
        board = getattr(q.exam_board, "acronym", None) or getattr(q.exam_board, "name", "")
        org = getattr(q.organization, "acronym", None) or getattr(q.organization, "name", "")
        discipline = getattr(q.discipline, "name", "")
        subject = getattr(q.subject, "name", "") if getattr(q, "subject", None) else ""
        year = getattr(q, "year", None)
        difficulty = _DIFFICULTY_LABEL.get(
            getattr(getattr(q, "difficulty", None), "value", None)
            or str(getattr(q, "difficulty", "")),
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

        # Cabeçalho + enunciado ficam juntos (evita "questão órfã" no topo da
        # página seguinte); as alternativas, não — uma questão muito longa
        # pode ultrapassar uma página A4, e forçar tudo junto causaria
        # LayoutError.
        story.append(
            KeepTogether(
                [
                    header_row,
                    Paragraph(f"{_safe_text(q.statement)}", question_statement),
                ]
            )
        )

        for alt in q.alternatives:
            story.append(
                Paragraph(
                    f"<b>{escape(alt.letter)})</b> {_safe_text(alt.text)}",
                    alternative,
                )
            )

        story.append(Spacer(1, 2 * mm))
        story.append(HRFlowable(width=doc.width, color=_BRAND["line"], thickness=0.6))
        story.append(Spacer(1, 5 * mm))

    # ---------------------------------------------------------------- #
    # Gabarito                                                          #
    # ---------------------------------------------------------------- #
    if include_answer_key:
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
        rows = []
        row = []
        for position, item in enumerate(items, start=1):
            row.append(
                Paragraph(
                    f"{position:02d} — <font color='#7C2D12'>"
                    f"{escape(item.question.correct_alternative_letter)}</font>",
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
    return buffer.getvalue(), f"{_filename(notebook.name)}.pdf"