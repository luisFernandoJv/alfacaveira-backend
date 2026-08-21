# app/core/constants.py
"""Constantes compartilhadas entre módulos — evita magic numbers duplicados
(e divergentes) em schemas/services diferentes.
"""

# Teto de quantas questões um usuário pode selecionar/operar de uma vez em
# fluxos de lote (Banco de Questões → "selecionar tudo que bate com o
# filtro", adicionar/mover/copiar em massa para caderno, iniciar treino a
# partir de uma seleção explícita). Não é "ilimitado" de propósito — protege
# a query de IN(...) e o payload da request — mas é alto o suficiente para
# cobrir o uso real (bancos de questões típicos por filtro ficam na casa das
# centenas, não milhares). Se um filtro específico algum dia passar disso,
# reavaliar com paginação real no cliente, não subir o número às cegas.
#
# Não usado por `ExamTemplateCreateRequest`/`MAX_SELECTED_QUESTIONS`
# (`app/services/assessment/exam_template_service.py`) de propósito — o teto
# de um simulado é uma regra de negócio diferente (tamanho de prova), não
# uma questão técnica de payload, e continua fixo em 100.
MAX_BULK_QUESTION_SELECTION = 500