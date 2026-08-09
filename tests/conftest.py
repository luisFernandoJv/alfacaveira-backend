"""Fixtures globais do Pytest.

Roadmap item 7 (fechamento) — achado real desta sessão (validado contra
execução real, ver docs/HANDOFF.md): as fixtures de Postgres efêmero via
Docker (`postgres_container`, `_apply_migrations`, `db_engine`,
`db_session`) estavam neste arquivo com `_apply_migrations` marcado
`autouse=True` em escopo de sessão. Como `tests/conftest.py` é raiz de
TODA a árvore `tests/`, isso fazia qualquer coleção de teste — inclusive
`tests/unit/`, que usa só dublês/fakes e nunca toca em Postgres/Docker —
tentar subir um container Docker antes do primeiro teste rodar. Sem
Docker disponível no ambiente (o mesmo motivo já documentado para o
script manual não ter sido executado por este agente), isso quebra as
111 collections de `tests/unit/` inteiras com
`ModuleNotFoundError`/erro de conexão ao daemon Docker — uma regressão
real, não só uma lacuna, introduzida junto com a fixture de Postgres real
(ADR-020) e nunca detectada porque nenhuma sessão anterior rodou
`pytest tests/unit` de fato depois de introduzir este arquivo (ver
HANDOFF: "Nenhum comando do projeto foi executado pelo agente").

Correção: as fixtures que dependem de Docker/Postgres real foram movidas
para `tests/integration/conftest.py`, que só é carregado ao coletar
`tests/integration/`. Este arquivo (`tests/conftest.py`) fica reservado
para fixtures verdadeiramente globais (compartilhadas por unit e
integration) — hoje, nenhuma é necessária; os testes de unidade seguem
usando fakes/dublês locais em `tests/unit/billing/fakes.py` e não
precisam de nada daqui.
"""

from __future__ import annotations