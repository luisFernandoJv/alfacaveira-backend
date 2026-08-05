"""Paginação cursor-based, para listagens de alto volume (ex.: Questões).

Cursor-based em vez de offset: em tabelas com milhões de linhas, `OFFSET N`
degrada linearmente com N. O cursor aqui é o próprio `id` (UUID) do último
item da página anterior, combinado com ordenação estável por `created_at`.
"""

import base64
from dataclasses import dataclass


@dataclass
class CursorPage:
    limit: int = 20
    cursor: str | None = None

    def decode_cursor(self) -> str | None:
        if not self.cursor:
            return None
        return base64.urlsafe_b64decode(self.cursor.encode()).decode()

    @staticmethod
    def encode_cursor(value: str) -> str:
        return base64.urlsafe_b64encode(value.encode()).decode()
