# Modelagem do banco — Foco Policial

31 tabelas, organizadas pelos 8 bounded contexts. Todos os models estão em
`app/models/<contexto>/`, usando SQLAlchemy 2 (`Mapped`/`mapped_column`),
chave primária UUID e timestamps padronizados via mixins (`app/models/base.py`).

## Destaques por contexto

**identity** — `users`, `user_profiles` (1:1), `refresh_tokens` (hash do
token, nunca o valor em texto puro; suporta rotação via
`replaced_by_token_id`).

**content** (módulo mais crítico) — hierarquia de classificação totalmente
normalizada `disciplines -> subjects -> topics`, dimensões de origem
(`exam_boards`, `organizations`, `exam_editions`), e a tabela `questions`
com:
- Índice composto `ix_questions_filter_composite` cobrindo exatamente o
  conjunto de filtros do `filters-panel.tsx` do frontend (disciplina,
  assunto, banca, ano, dificuldade, status).
- Índice GIN em `search_vector` (tsvector) para busca textual — o valor é
  mantido por trigger de banco (criado na migration da Etapa 4), não escrito
  pela aplicação.
- `question_alternatives` (1:N, letra única por questão via constraint),
  `question_attachments`, `question_tags` (M2M via `question_tag_links`) e
  `question_revisions` como tabela de auditoria **append-only** — nunca é
  atualizada, cada mudança relevante gera uma nova linha com snapshot JSONB.

**practice** — `training_sessions` guarda o snapshot dos filtros usados
(JSONB) e a ordem das questões apresentadas. **Decisão importante**:
`question_attempts` é uma tabela única e compartilhada para todo tipo de
resposta (treino ou simulado), diferenciada por `session_type` +
`session_id` (sem FK física, pois aponta para origens diferentes). Isso
evita duplicar a lógica de histórico entre `practice` e `assessment`, e
simplifica MUITO as queries de Estatísticas e da tela de Histórico.

**assessment** — `exam_templates` (molde/config do simulado, pode ser
público ou pessoal) e `exam_attempts` + `exam_attempt_questions`
(execução real de um simulado por um aluno).

**learning** — `flashcards` (opcionalmente ligado a uma questão de origem)
e `flashcard_reviews` com os campos padrão do algoritmo SM-2
(`easiness_factor`, `interval_days`, `repetitions`, `due_date`).

**analytics** — tabelas **pré-agregadas** (`user_daily_stats`,
`user_subject_stats`, `study_streaks`), escritas por background workers a
partir dos dados crus de `question_attempts`. O Dashboard nunca agrega em
tempo real sobre a tabela de tentativas — é o que garante resposta rápida
mesmo com milhões de linhas na tabela de origem.

**billing** — `plans`, `subscriptions`, `payments`. Estrutura pronta para
integração de gateway (Etapa de Assinaturas), sem acoplar a um provedor
específico ainda.

**platform** — `notifications` e `admin_audit_logs` (trilha de auditoria
de ações administrativas).

## Convenções aplicadas em todo o esquema

- Chave primária UUID v4 gerada em Python (`default=uuid.uuid4`).
- `created_at`/`updated_at` com timezone, geridos pelo banco (`server_default=func.now()`).
- Enums Python (`str, enum.Enum`) mapeados para `ENUM` nativo do Postgres
  (criado explicitamente na migration, `create_type=False` no model).
- `ondelete` explícito em toda FK: `CASCADE` quando o filho não faz sentido
  sem o pai (ex.: alternativas de uma questão), `RESTRICT` quando a exclusão
  deve ser bloqueada (ex.: não apagar uma disciplina com questões), `SET NULL`
  quando a referência é informativa e opcional.
- Nenhuma regra de negócio nos models — apenas estrutura, constraints e
  relacionamentos. Regra de negócio vive em `services/`.

## Validação

Os 31 models foram importados e registrados em `Base.metadata` com sucesso
(script de smoke-test rodado manualmente). A geração da primeira migration
Alembic acontece na Etapa 4, junto da configuração do projeto.

## Próximos passos (Etapa 4)

- `alembic init` + configuração assíncrona.
- Migration inicial criando os tipos ENUM nativos e as 31 tabelas.
- Trigger de banco para popular `questions.search_vector` automaticamente.
- `pyproject.toml` (Poetry), Ruff, MyPy, Docker Compose, `.env.example`.
