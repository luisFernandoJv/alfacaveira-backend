#!/usr/bin/env bash
# scripts/manual/test_concurrency_postgres.sh
#
# OBJETIVO
#   Rodar tests/integration/test_subscription_concurrency_postgres.py contra
#   um Postgres real efêmero (via testcontainers-python, ADR-020), validando
#   o compare_and_swap/compare_and_swap_status acumulado (ADR-017+018+019)
#   contra concorrência de verdade — não só o dublê determinístico de
#   tests/unit/billing/.
#
#   Necessário rodar manualmente porque o ambiente onde este script foi
#   ESCRITO não tem Docker nem acesso de rede para instalar as dependências
#   do pyproject.toml (ver docs/HANDOFF.md desta sessão). Nunca foi
#   executado — não é um "já validei, só formalizei"; rode antes de confiar.
#
# PRÉ-REQUISITOS
#   - Docker rodando localmente (testcontainers-python sobe o container via
#     Docker; sem Docker, este script falha na primeira linha do conftest).
#   - Python 3.13 e Poetry instalados.
#   - Dependências do projeto instaladas, incluindo o grupo dev:
#       poetry install --with dev
#     E adicionalmente (não estava no pyproject.toml original — ver ADR-020
#     sobre por que testcontainers-python foi escolhido, e adicionar como
#     dependência de dev antes de rodar):
#       poetry add --group dev testcontainers[postgres] psycopg2-binary
#   - Repositório com os arquivos desta sessão já aplicados: novo
#     tests/conftest.py, novo diretório tests/integration/, e o
#     compare_and_swap generalizado (ADR-019) já em
#     app/repositories/billing/subscription_repository.py.
#
# COMANDO EXATO
#   poetry run pytest tests/integration/test_subscription_concurrency_postgres.py -v
#
# DADOS DE ENTRADA
#   Nenhum dado de entrada externo — cada teste cria seu próprio User/Plan/
#   Subscription mínimos direto no banco efêmero (ver
#   _seed_user_plan_subscription no arquivo de teste). Nada de produção ou
#   staging é tocado; o container Postgres é descartado ao final da sessão
#   de teste (testcontainers derruba automaticamente ao sair do `with`).
#
# RESULTADO ESPERADO
#   7 testes (um por método protegido por CAS: cancel_subscription,
#   reactivate_subscription, renew_subscription, change_plan,
#   activate_subscription, expire_subscription, mark_payment_failed), todos
#   passando, cada um confirmando:
#     - nenhuma exceção inesperada em qualquer das duas chamadas
#       concorrentes;
#     - exatamente 1 linha em SubscriptionHistory (nunca 2, nunca 0);
#     - estado final coerente com a chamada vencedora.
#
# CÓDIGO DE SAÍDA
#   0 = todos os testes passaram (só então este item pode ser marcado
#       CONCLUÍDO em HANDOFF.md — ver regra do PROMPT desta sessão: rodar
#       este script sem executar de fato os testes só sustenta status
#       PARCIAL, nunca CONCLUÍDO).
#   != 0 = pelo menos um teste falhou, ou pré-requisito ausente (Docker não
#       encontrado, dependência faltando) — não editar HANDOFF.md como
#       CONCLUÍDO neste caso; registrar o que falhou.

set -euo pipefail

if ! command -v docker >/dev/null 2>&1; then
  echo "ERRO: Docker não encontrado no PATH. testcontainers-python precisa" >&2
  echo "de um daemon Docker acessível para subir o Postgres efêmero." >&2
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "ERRO: Docker encontrado mas o daemon não está acessível (rodando?" >&2
  echo "permissão do usuário atual para o socket do Docker?)." >&2
  exit 1
fi

echo "Rodando testes de concorrência real contra Postgres efêmero..."
poetry run pytest tests/integration/test_subscription_concurrency_postgres.py -v