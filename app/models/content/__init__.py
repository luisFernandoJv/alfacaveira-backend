"""Models do contexto 'content' (taxonomia, origem e questões)."""

from app.models.content.exam_source import ExamBoard, ExamEdition, Organization
from app.models.content.question import Question, QuestionAlternative
from app.models.content.question_attachment import QuestionAttachment
from app.models.content.question_revision import QuestionRevision
from app.models.content.question_tag import QuestionTag, question_tag_links
from app.models.content.taxonomy import Discipline, Subject, Topic

__all__ = [
    "Discipline",
    "Subject",
    "Topic",
    "ExamBoard",
    "Organization",
    "ExamEdition",
    "Question",
    "QuestionAlternative",
    "QuestionAttachment",
    "QuestionRevision",
    "QuestionTag",
    "question_tag_links",
]
