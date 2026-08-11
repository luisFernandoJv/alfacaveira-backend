#!/usr/bin/env bash
# scripts/manual/test_subscription_renewal_staging.sh
#
# OBJETIVO
#   Exercitar app/workers/subscription_renewal.py (PROMPT 10, roadmap item
#   10) fim-a-fim contra um Postgres de staging real — os testes automáticos
#   em tests/unit/billing/test_subscription_renewal_worker.py já cobrem a
#   lógica do job com dublês em memória (incluindo o critério de aceite
#   "rodar o job duas vezes não duplica cobrança"), mas nenhum deles toca
#   banco de verdade nem o scheduler/APScheduler real.
#
#   Nunca foi executado — escrito e revisado por leitura de código nesta
#   sessão, não validado contra staging de verdade. Rode antes de confiar.
#
# PRÉ-REQUISITOS
#   - Banco de staging acessível via DATABASE_URL, com as migrations em dia:
#       poetry run alembic upgrade head
#   - Um usuário + plano + assinatura ATIVA de teste já existentes nesse
#     banco (ex.: via scripts/seed_test_data.py, se aplicável) — este
#     script não cria dados, só avança o relógio lógico do teste.
#   - PAYMENT_GATEWAY_DRIVER=console (padrão) — não fala com nenhum
#     provedor real.
#
# PASSO A PASSO
#
#   1. Escolha (ou crie) uma assinatura ATIVA de teste e anote o `id`.
#
#   2. Force o período a vencer, direto no banco de staging:
#
#        UPDATE subscriptions
#           SET current_period_end = now() - interval '1 hour'
#         WHERE id = '<subscription_id>';
#
#   3. Rode o worker uma vez:
#
#        poetry run python -m app.workers.subscription_renewal
#
#      Resultado esperado: log `subscription_renewal.charging` para esta
#      assinatura, e no banco:
#        - um novo `payments` com status=aprovado (driver console);
#        - `subscriptions.current_period_end` avançado para o futuro
#          (agora + duração do plano);
#        - uma nova linha em `subscription_history` com
#          reason=renovada e payment_id preenchido.
#
#   4. Rode o worker DE NOVO, sem tocar em nada:
#
#        poetry run python -m app.workers.subscription_renewal
#
#      Resultado esperado (critério de aceite do PROMPT 10 — "executar o
#      job duas vezes não duplica cobrança"): NENHUM novo log
#      `subscription_renewal.charging` para esta assinatura (ela não está
#      mais vencida), nenhum `payments` novo, `current_period_end`
#      inalterado desde o passo 3.
#
#   5. Caso de cancelamento agendado — repita com uma segunda assinatura:
#
#        UPDATE subscriptions
#           SET cancel_at_period_end = true,
#               current_period_end = now() - interval '1 hour'
#         WHERE id = '<outra_subscription_id>';
#
#        poetry run python -m app.workers.subscription_renewal
#
#      Resultado esperado: log `subscription_renewal.finalizing_cancellation`,
#      `subscriptions.status` vira `cancelada`, nenhum `payments` novo para
#      esta assinatura (não deve cobrar uma assinatura que está sendo
#      cancelada).
#
#   6. (Opcional) Scheduler in-process real: com a API rodando
#      (`SUBSCRIPTION_RENEWAL_ENABLED=true`,
#      `SUBSCRIPTION_RENEWAL_INTERVAL_MINUTES=1` para não esperar a hora
#      cheia padrão), repita os passos 2-4 e confirme que o job dispara
#      sozinho no intervalo configurado, sem precisar rodar o comando do
#      passo 3 manualmente. Confira os logs
#      `subscription_renewal.scheduler_job_registered` no start-up e
#      `subscription_renewal.job_start`/`job_finished` a cada execução.
#
# LIMPEZA
#   Nenhum dado de produção é tocado (staging apenas). Se quiser reverter o
#   estado das assinaturas de teste manualmente:
#
#     UPDATE subscriptions SET status = 'ativa', cancel_at_period_end = false
#      WHERE id IN ('<subscription_id>', '<outra_subscription_id>');