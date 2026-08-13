# app/schemas/learning/__init__.py
"""Schemas do contexto 'learning'."""

from app.schemas.learning.flashcard import (
    FlashcardCreateFromQuestionRequest,
    FlashcardCreateRequest,
    FlashcardResponse,
    FlashcardReviewRequest,
    FlashcardReviewStateResponse,
    FlashcardStatsResponse,
    FlashcardUpdateRequest,
)
from app.schemas.learning.notebook import (
    NotebookCreateRequest,
    NotebookDetailResponse,
    NotebookFavoriteToggleRequest,
    NotebookListResponse,
    NotebookResponse,
    NotebookUpdateRequest,
)
from app.schemas.learning.notebook_folder import (
    NotebookFolderCreateRequest,
    NotebookFolderListResponse,
    NotebookFolderResponse,
    NotebookFolderUpdateRequest,
)
from app.schemas.learning.notebook_question import (
    NotebookQuestionAddRequest,
    NotebookQuestionBulkAddRequest,
    NotebookQuestionCopyRequest,
    NotebookQuestionListResponse,
    NotebookQuestionMoveRequest,
    NotebookQuestionResponse,
)
from app.schemas.learning.notebook_tag import (
    NotebookTagCreateRequest,
    NotebookTagListResponse,
    NotebookTagResponse,
)

__all__ = [
    # Flashcards
    "FlashcardCreateRequest",
    "FlashcardCreateFromQuestionRequest",
    "FlashcardUpdateRequest",
    "FlashcardReviewRequest",
    "FlashcardResponse",
    "FlashcardReviewStateResponse",
    "FlashcardStatsResponse",
    # Notebooks
    "NotebookCreateRequest",
    "NotebookUpdateRequest",
    "NotebookResponse",
    "NotebookDetailResponse",
    "NotebookListResponse",
    "NotebookFavoriteToggleRequest",
    # Notebook Folders
    "NotebookFolderCreateRequest",
    "NotebookFolderUpdateRequest",
    "NotebookFolderResponse",
    "NotebookFolderListResponse",
    # Notebook Questions
    "NotebookQuestionAddRequest",
    "NotebookQuestionBulkAddRequest",
    "NotebookQuestionMoveRequest",
    "NotebookQuestionCopyRequest",
    "NotebookQuestionResponse",
    "NotebookQuestionListResponse",
    # Notebook Tags
    "NotebookTagCreateRequest",
    "NotebookTagResponse",
    "NotebookTagListResponse",
]