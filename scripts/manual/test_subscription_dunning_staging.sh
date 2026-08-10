#!/usr/bin/env bash
# scripts/manual/test_subscription_dunning_staging.sh
#
# OBJETIVO
#   Exercitar app/workers/subscription_dunning.py (PROMPT 11, roadmap item
#   11) fim-a-fim contra um Postgres de staging real — os testes automáticos
#   em tests/unit/billing/test_subscription_dunning_worker.py já cobrem a
#   lógica do job com dublês em memória (incluindo os critérios de aceite
#   "rodar o job duas vezes não duplica cobrança/histórico" e "grace period
#   expira mesmo com tentativas restantes"), mas nenhum deles toca banco de
#   verdade nem o scheduler/APScheduler real, nem exercita as duas queries
#   novas de repositório (list_due_for_dunning_retry/
#   list_due_for_dunning_expiration) contra SQL real.
#
#   Nunca foi executado — escrito e revisado por leitura de código nesta
#   sessão, não validado contra staging de verdade. Rode antes de confiar,
#   mesma ressalva do script irmão de renovação (PROMPT 10).
#
# PRÉ-REQUISITOS
#   - Banco de staging acessível via DATABASE_URL, com as migrations em dia:
#       poetry run alembic upgrade head
#     (confirma, entre outras, que a migration 0009_dunning foi aplicada —
#     colunas dunning_attempts/dunning_next_retry_at/
#     dunning_grace_period_ends_at existem em `subscriptions`.)
#   - Um usuário + plano + assinatura de teste já existentes nesse banco.
#   - PAYMENT_GATEWAY_DRIVER=console (padrão) — não fala com nenhum
#     provedor real. O driver console sempre aprova; para exercitar o
#     caminho de recusa (passo 3), veja a nota no próprio passo.
#
# PASSO A PASSO
#
#   1. Coloque uma assinatura de teste em INADIMPLENTE com um ciclo de
#      dunning já inicializado, direto no banco de staging (simula o que
#      `mark_payment_failed` faria automaticamente):
#
#        UPDATE subscriptions
#           SET status = 'inadimplente',
#               dunning_attempts = 0,
#               dunning_next_retry_at = now() - interval '1 hour',
#               dunning_grace_period_ends_at = now() + interval '2 days'
#         WHERE id = '<subscription_id>';
#
#   2. Rode o worker uma vez:
#
#        poetry run python -m app.workers.subscription_dunning
#
#      Resultado esperado (driver console, sempre aprova): log
#      `subscription_dunning.retrying` para esta assinatura, e no banco:
#        - um novo `payments` com status=aprovado;
#        - `subscriptions.status` volta para `ativa`;
#        - `subscriptions.current_period_end` avançado (agora + duração do
#          plano);
#        - `dunning_attempts` = 0, `dunning_next_retry_at` e
#          `dunning_grace_period_ends_at` = NULL;
#        - uma nova linha em `subscription_history` com
#          reason=recuperada_dunning e payment_id preenchido.
#
#   3. Caminho de recusa — repita com uma segunda assinatura, mas force o
#      driver console a recusar (ver PAYMENT_GATEWAY_CONSOLE_FORCE_DECLINE
#      ou equivalente em app/services/billing/gateway.py; se essa opção não
#      existir ainda, este passo fica bloqueado — não é escopo do PROMPT 11
#      criar um driver de teste com recusa configurável, ver docs/
#      DECISIONS.md ADR-027):
#
#        UPDATE subscriptions
#           SET status = 'inadimplente',
#               dunning_attempts = 0,
#               dunning_next_retry_at = now() - interval '1 hour',
#               dunning_grace_period_ends_at = now() + interval '2 days'
#         WHERE id = '<outra_subscription_id>';
#
#        poetry run python -m app.workers.subscription_dunning
#
#      Resultado esperado: `subscriptions.status` continua `inadimplente`,
#      `dunning_attempts` = 1, `dunning_next_retry_at` avançado ~1 dia,
#      `dunning_grace_period_ends_at` inalterado, nova linha em
#      `subscription_history` com reason=retry_dunning_falhou.
#
#   4. Rode o worker DE NOVO logo em seguida, sem tocar em nada (mesmo
#      `now`, na prática):
#
#        poetry run python -m app.workers.subscription_dunning
#
#      Resultado esperado (critério de aceite — "rodar o job duas vezes não
#      duplica cobrança"): nenhum novo log `subscription_dunning.retrying`
#      para as assinaturas dos passos 2/3 (a do passo 2 já está `ativa`; a
#      do passo 3 tem `dunning_next_retry_at` no futuro agora), nenhum
#      `payments` novo, nenhuma `subscription_history` nova.
#
#   5. Caminho de expiração por fim de grace period:
#
#        UPDATE subscriptions
#           SET status = 'inadimplente',
#               dunning_attempts = 3,
#               dunning_next_retry_at = NULL,
#               dunning_grace_period_ends_at = now() - interval '1 hour'
#         WHERE id = '<terceira_subscription_id>';
#
#        poetry run python -m app.workers.subscription_dunning
#
#      Resultado esperado: log `subscription_dunning.expiring`,
#      `subscriptions.status` vira `expirada`, nenhum `payments` novo para
#      esta assinatura (não tenta cobrar de novo, só expira), nova linha em
#      `subscription_history` com reason=expirada e from_status=inadimplente.
#
#   6. (Opcional) Scheduler in-process real: com a API rodando
#      (`DUNNING_ENABLED=true`, `DUNNING_INTERVAL_MINUTES=1` para não
#      esperar a hora cheia padrão), repita os passos 1-2 e confirme que o
#      job dispara sozinho no intervalo configurado. Confira os logs
#      `subscription_dunning.scheduler_job_registered` no start-up e
#      `subscription_dunning.job_start`/`job_finished` a cada execução.
#
# LIMPEZA
#   Nenhum dado de produção é tocado (staging apenas). Se quiser reverter o
#   estado das assinaturas de teste manualmente:
#
#     UPDATE subscriptions
#        SET status = 'ativa',
#            dunning_attempts = 0,
#            dunning_next_retry_at = NULL,
#            dunning_grace_period_ends_at = NULL
#      WHERE id IN ('<subscription_id>', '<outra_subscription_id>',
#                    '<terceira_subscription_id>');