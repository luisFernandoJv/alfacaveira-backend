# app/services/learning/__init__.py
"""Serviços do contexto 'learning'."""

from app.services.learning.flashcard_service import FlashcardService
from app.services.learning.notebook_service import NotebookService

__all__ = [
    "FlashcardService",
    "NotebookService",
]