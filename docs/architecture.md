# Arquitetura — Foco Policial Backend

> Documento vivo. Atualizado a cada etapa do desenvolvimento.

## Visão geral

Backend do SaaS **Foco Policial** (preparação para concursos policiais).
Segue Clean Architecture pragmática + DDD leve (bounded contexts), pensado
para escalar de milhares para centenas de milhares de questões e dezenas de
milhares de usuários ativos.

## Camadas

```
API layer        -> routers FastAPI, validação de entrada, HTTP. Sem regra de negócio.
Service layer     -> regras de negócio, casos de uso, orquestra repositórios.
Repository layer  -> acesso a dados via interfaces (Protocol). Só CRUD/queries.
Database          -> PostgreSQL (Supabase, apenas como Postgres gerenciado) + Redis.
```

Regra de dependência única: `api -> services -> repositories -> database`.
Nunca ao contrário, nunca pulando camada.

## Bounded contexts

| Contexto     | Módulos                                                  |
| ------------ | --------------------------------------------------------- |
| `identity`   | Autenticação, Usuários, Perfil                             |
| `content`    | Disciplinas, Assuntos, Subassuntos, Questões, Bancas/Concursos/Órgãos |
| `practice`   | Treinos, Sessões de estudo, Histórico                      |
| `assessment` | Simulados                                                   |
| `learning`   | Flashcards, Revisões (SM-2)                                 |
| `analytics`  | Dashboard, Estatísticas                                     |
| `billing`    | Assinaturas, Pagamentos                                     |
| `platform`   | Notificações, Administração                                 |

Cada contexto tem sua própria pasta espelhada em `models/`, `schemas/`,
`repositories/`, `services/` e `api/v1/`.

## Decisões-chave

- **Repository Pattern com interfaces**: permite trocar implementação de
  persistência e testar `services/` com repositórios fake, sem banco real.
- **Dependency Injection**: via `Depends` nativo do FastAPI. Sem containers
  de DI externos.
- **Unit of Work**: transações atômicas para operações que tocam múltiplos
  repositórios (ex.: criação de simulado).
- **Autenticação própria**: sem Supabase Auth. Hash de senha com Argon2,
  access token JWT de vida curta + refresh token opaco (hash em DB, rotação
  a cada uso).
- **Questões**: modelo totalmente normalizado (tabelas de dimensão para
  disciplina/assunto/subassunto/banca/órgão/concurso), histórico de
  alterações como tabela de auditoria append-only, busca via `tsvector`.
- **Paginação**: cursor-based nas listagens de alto volume (Questões).
- **Cache/Rate limit**: Redis.
- **Resposta padrão**: envelope único `{data, meta, error}`.

## Stack

Python 3.13 · FastAPI · SQLAlchemy 2 (async) · Alembic · Pydantic v2 ·
PostgreSQL (Supabase) · Redis · JWT · Docker · Poetry · Ruff · MyPy · Pytest.

## Estado do roadmap

| Etapa | Descrição                        | Status        |
| ----- | --------------------------------- | -------------- |
| 1     | Arquitetura completa               | ✅ Concluída   |
| 2     | Estrutura de pastas                 | ✅ Concluída   |
| 3     | Modelagem do banco                  | ✅ Concluída   |
| 4     | Configuração do projeto             | ✅ Concluída   |
| 5     | Autenticação                        | ✅ Concluída   |
| 6     | Usuários / Perfil                   | ✅ Concluída   |
| 7     | Questões                            | ✅ Concluída   |
| 8     | Treinos / Sessões                   | ✅ Concluída   |
| 9     | Simulados                           | ✅ Concluída   |
| 10+   | Flashcards, Dashboard, Assinaturas, Notificações/Admin, Testes, Deploy | 🔲 Próxima     |

## Etapa 5 — Autenticação

Implementada em `identity`: registro, login, refresh (com rotação de token) e
logout, seguindo as decisões-chave já definidas (Argon2, JWT + refresh opaco
com hash em DB, envelope de resposta, `DomainError`, `UnitOfWork`).

- `security/password.py` — hash/verify com Argon2.
- `security/jwt.py` — access token JWT (15 min) + geração/hash de refresh
  token opaco (`secrets.token_urlsafe`, hash SHA-256 para lookup indexado).
- `security/dependencies.py` — `get_current_user` / `get_current_admin_user`
  via `HTTPBearer`, para proteger endpoints das próximas etapas.
- `repositories/identity/` — `UserRepository`, `RefreshTokenRepository`.
- `schemas/identity/auth.py` — request/response da autenticação.
- `services/identity/auth_service.py` — `AuthService` orquestra os
  repositórios; refresh usa `UnitOfWork` para revogar o token antigo e criar
  o novo atomicamente (rotação).
- `api/v1/identity/auth.py` — `POST /auth/register`, `POST /auth/login`,
  `POST /auth/refresh`, `POST /auth/logout`.

Testes de integração (Etapa 13, conforme já indicado em
`tests/conftest.py`) ainda não foram escritos — ficam para quando a fixture
de banco de teste for montada.

## Etapa 6 — Usuários / Perfil

Continua o contexto `identity`: conta (tabela `users`) e perfil (tabela
`user_profiles`, 1:1), mais administração básica de usuários.

- `repositories/identity/user_repository.py` — `list_paginated` (keyset por
  `created_at, id`, conforme decisão de paginação cursor-based).
- `repositories/identity/user_profile_repository.py` — `UserProfileRepository`.
- `services/identity/user_service.py` — `UserService`: perfil (get/update com
  criação preguiçosa caso não exista), dados de conta, troca de senha,
  listagem/consulta/ativação de usuários (admin).
- `schemas/identity/user.py` — schemas de perfil, conta, troca de senha e
  administração.
- `api/v1/identity/users.py`:
  - `GET/PATCH /users/me` — conta + perfil do usuário autenticado.
  - `PATCH /users/me/profile` — atualização parcial do perfil (PATCH real:
    `exclude_unset`, então só os campos enviados são alterados).
  - `POST /users/me/change-password`.
  - `GET /users` (admin, paginado por cursor) · `GET /users/{id}` (admin) ·
    `PATCH /users/{id}/status` (admin, ativar/desativar).
- `auth.py`: o antigo `GET /auth/me` (Etapa 5) foi absorvido por
  `GET /users/me`, que já retorna conta + perfil juntos — evita duas rotas
  concorrentes para a mesma informação.
- `services/identity/auth_service.py`: `register` agora também cria a linha
  de `UserProfile` (vazia) no mesmo `UnitOfWork`, garantindo que todo usuário
  sempre tenha um perfil associado desde a criação da conta.

Auditoria de ações administrativas (`platform.admin_audit_log`) fica para a
etapa dedicada ao contexto `platform`, fora do escopo de `identity`.

## Etapa 7 — Questões (`content`)

Modelo já existia completo desde a Etapa 3 (normalizado, `search_vector`
mantido por trigger de banco); esta etapa implementou repositórios,
schemas, serviços e endpoints por cima dele.

- `repositories/content/taxonomy_repository.py` — `DisciplineRepository`,
  `SubjectRepository`, `TopicRepository`: listagens simples ordenadas por
  nome (tabelas de dimensão, baixo volume — sem paginação cursor-based).
- `repositories/content/exam_source_repository.py` — `ExamBoardRepository`,
  `OrganizationRepository`, `ExamEditionRepository` (esta última com filtro
  opcional por órgão/banca).
- `repositories/content/question_tag_repository.py` — `QuestionTagRepository`
  (`list_all`, `list_by_ids` para validar tags recebidas no CRUD).
- `repositories/content/question_repository.py` — `QuestionRepository`:
  - `QuestionFilters` (dataclass): todos os filtros da listagem pública,
    combinados com AND — disciplina/assunto/subassunto/banca/edição/
    órgão/ano/dificuldade/status/tag.
  - Busca full-text via `search_vector.op("@@")(func.plainto_tsquery("portuguese", ...))`,
    casando com o `to_tsvector('portuguese', ...)` do trigger de banco.
  - `list_paginated` — mesmo padrão keyset (`created_at, id`) da Etapa 6,
    com `selectinload` das relações usadas pelos schemas de resposta
    (evita N+1 na listagem).
  - `get_with_relations` — carregamento antecipado para o detalhe.
- `services/content/taxonomy_service.py`, `exam_source_service.py` — apenas
  repassam para os repositórios, validando existência do pai (ex.: 404 se
  a disciplina não existir ao listar assuntos).
- `services/content/question_service.py` — `QuestionService`:
  - CRUD completo com `UnitOfWork`; toda escrita (criação, edição, mudança
    de status, exclusão) gera uma linha em `QuestionRevision` com snapshot
    JSON do estado resultante, conforme a decisão de auditoria append-only.
  - Exclusão é **lógica** (`status = DESATIVADA` + revisão `EXCLUSAO`) —
    nunca `DELETE` físico, o que apagaria em cascata o próprio histórico de
    auditoria (`question_revisions` tem `ON DELETE CASCADE` em
    `question_id`).
  - Validação de domínio: disciplina/banca devem existir (`NotFoundError`),
    exatamente uma alternativa marcada como correta e letras não repetidas
    (validado no schema, `QuestionCreateRequest`/`UpdateRequest`), tags
    referenciadas devem existir.
- `schemas/content/taxonomy.py`, `exam_source.py`, `question.py` — schemas
  de resposta aninham as entidades relacionadas (ex.: `QuestionListItem`
  traz `discipline`, `exam_board` etc. como objetos, não só IDs), alinhado
  ao que as telas do frontend (`app/(app)/questoes/*`) já esperam consumir.
- `api/v1/content/questions.py`:
  - `GET /questions` — pública (qualquer usuário autenticado), paginada por
    cursor, filtrável e com busca full-text (`?search=`); por padrão só
    retorna questões `publicada` (`status` default), mas aceita
    `?status=` explícito.
  - `GET /questions/{id}` — detalhe completo (alternativas + gabarito).
  - `POST /questions`, `PATCH /questions/{id}`, `PATCH /questions/{id}/status`,
    `DELETE /questions/{id}` — restritos a administradores
    (`CurrentAdminUser`); não existe papel "editor" separado no modelo de
    usuário atual, então o CRUD ficou admin-only por ora.
- `api/v1/content/taxonomy.py` — `GET /disciplines`,
  `GET /disciplines/{id}/subjects`, `GET /subjects/{id}/topics`.
- `api/v1/content/exam_sources.py` — `GET /exam-boards`,
  `GET /organizations`, `GET /exam-editions` (filtros opcionais por
  órgão/banca).
- `api/v1/router.py` — routers de `content` registrados
  (`/questions`, taxonomia e origem sem prefixo compartilhado, já que cada
  um expõe recursos com nomes de path distintos).

Frontend não foi tocado nesta etapa (mock em `config/questions.ts` segue
ativo); os schemas de resposta foram desenhados para bater com os campos
reais do modelo — alguns campos do mock (`code`, `favorite`,
`communityAccuracy`, `comments`) dependem de dados que só existirão em
`practice`/`analytics` (tentativas de resposta, favoritos por usuário) e
ficam para as etapas correspondentes.

## Etapa 8 — Treinos / Sessões (`practice`)

Modelo já existia completo desde a Etapa 3 (`TrainingSession`,
`TrainingSessionQuestion`, `QuestionAttempt` — este último compartilhado
com o futuro `assessment`, via `session_type` + `session_id` "frouxos", sem
FK física). Esta etapa implementou repositórios, schemas, serviços e
endpoints por cima dele, reutilizando `QuestionRepository` (content) como
dependência natural entre contextos.

- `repositories/content/question_repository.py` — estendido (sem alterar o
  que já existia) com `list_by_ids` (busca em lote, usada para montar as
  questões de uma sessão sem N+1) e `list_random` (seleção aleatória via
  `ORDER BY random()`, reaproveitando `QuestionFilters`/`_apply_filters`
  já existentes; anotado como candidato a revisão se o volume crescer para
  a casa de milhões de questões).
- `repositories/practice/training_session_repository.py` —
  `TrainingSessionRepository`: `get_with_questions` (`selectinload` das
  questões da sessão) e `list_paginated` — histórico do usuário, keyset por
  `created_at, id` (mesmo padrão da Etapa 6/7), sempre filtrado por
  `user_id` (treino é recurso pessoal).
- `repositories/practice/question_attempt_repository.py` —
  `QuestionAttemptRepository`: `get_for_question_in_session` (evita resposta
  duplicada), `list_by_session` (quais questões da sessão já foram
  respondidas) e `list_paginated` (histórico geral do usuário, por
  `answered_at, id`).
- `services/practice/training_session_service.py` — `TrainingSessionService`:
  - `create_session`: valida os filtros recebidos, seleciona questões
    aleatórias publicadas via `QuestionRepository.list_random`,
    `NotFoundError` se nenhuma questão casar com os filtros; grava a sessão
    + as `TrainingSessionQuestion` (posição ordinal) num único `UnitOfWork`,
    junto com o snapshot (JSONB) dos filtros usados.
  - `get_session`: `NotFoundError` tanto para sessão inexistente quanto para
    sessão de outro usuário — não expõe existência de recursos de terceiros.
  - `finish_session`: marca `finished_at`; `ConflictError` se já finalizada.
- `services/practice/question_attempt_service.py` — `QuestionAttemptService`:
  - `submit_training_answer`: valida sessão (existe, pertence ao usuário,
    não finalizada), questão pertence à sessão, ainda não respondida
    (`ConflictError` caso contrário) e alternativa (se enviada) pertence à
    questão; grava a `QuestionAttempt` e incrementa `correct_count` da
    sessão atomicamente via `UnitOfWork` quando a resposta é correta.
    Resposta em branco (`selected_alternative_id=None`) ainda gera tentativa
    registrada, marcada como incorreta, para não deixar buraco no
    histórico/estatísticas.
  - `list_history`: histórico geral de tentativas do usuário (qualquer
    origem, hoje só `treino`), paginado por cursor.
- `schemas/practice/training_session.py`, `question_attempt.py` —
  `TrainingSessionCreateRequest` (filtros + `quantity`),
  `TrainingSessionQuestionResponse` (questão sem gabarito, com flag
  `answered`), `TrainingSessionListItem`/`DetailResponse`,
  `AnswerSubmitRequest`/`AnswerResultResponse` (resultado imediato com
  gabarito comentado) e `QuestionAttemptListItem` (histórico).
- `api/v1/practice/training_sessions.py`:
  - `POST /training-sessions` — cria sessão a partir de filtros + `quantity`.
  - `GET /training-sessions` — histórico paginado do usuário autenticado.
  - `GET /training-sessions/{id}` — detalhe (questões na ordem, sem
    gabarito, com flag `answered` por questão).
  - `POST /training-sessions/{id}/questions/{question_id}/answer` —
    submete resposta, retorna resultado imediato (acerto/erro + gabarito
    comentado).
  - `POST /training-sessions/{id}/finish` — finaliza a sessão.
- `api/v1/practice/attempts.py` — `GET /attempts`: histórico geral de
  respostas do usuário, paginado por cursor.

## Etapa 9 — Simulados (`assessment`)

Modelo já existia completo desde a Etapa 3 (`ExamTemplate`, `ExamAttempt`,
`ExamAttemptQuestion`). Um simulado tem dois níveis: o **molde**
(`ExamTemplate` — filtros + quantidade de questões + tempo limite, público
ou pessoal) e a **execução** (`ExamAttempt` — uma tentativa concreta de um
usuário sobre um molde, com status `em_andamento` / `finalizado` /
`abandonado`). Resposta de questão reutiliza a mesma tabela unificada
`QuestionAttempt` (practice, Etapa 8) via `session_type=SIMULADO`, exatamente
como antecipado no comentário de modelagem daquela tabela — o histórico
geral (`GET /attempts`) já cobre simulado sem qualquer alteração fora deste
contexto.

- `repositories/assessment/exam_template_repository.py` —
  `ExamTemplateRepository`: `list_visible` — moldes públicos (`is_public`)
  + próprios do usuário (`created_by`), keyset por `created_at, id`.
- `repositories/assessment/exam_attempt_repository.py` —
  `ExamAttemptRepository`: `get_with_questions` (`selectinload` das
  questões do simulado) e `list_paginated` — histórico do usuário, mesmo
  padrão de `TrainingSessionRepository`.
- `services/assessment/exam_template_service.py` — `ExamTemplateService`:
  - `create_template`: grava o snapshot (JSONB) dos filtros; `ForbiddenError`
    se um usuário não-admin tentar criar molde público (`is_public=True`).
  - `get_template`/`list_templates`: `NotFoundError` para molde pessoal de
    outro usuário — não expõe existência (mesmo princípio da Etapa 8).
- `services/assessment/exam_attempt_service.py` — `ExamAttemptService`:
  - `start_attempt`: reconstrói `QuestionFilters` a partir do
    `filters_snapshot` do molde, seleciona questões aleatórias publicadas
    via `QuestionRepository.list_random` (`NotFoundError` se nenhuma
    casar), grava o `ExamAttempt` + `ExamAttemptQuestion` (posição ordinal)
    num único `UnitOfWork`.
  - `submit_answer`: valida simulado (existe, pertence ao usuário, status
    `em_andamento`), questão pertence ao simulado, ainda não respondida
    (`ConflictError` caso contrário) e alternativa (se enviada) pertence à
    questão; grava `QuestionAttempt` (`session_type=SIMULADO`) e atualiza
    `ExamAttemptQuestion` + `correct_count` do simulado atomicamente via
    `UnitOfWork`.
  - `finish_attempt`/`abandon_attempt`: transições de status a partir de
    `em_andamento`; `ConflictError` se o simulado já não estiver em
    andamento.
- `schemas/assessment/exam_template.py`, `exam_attempt.py` —
  `ExamTemplateCreateRequest` (filtros + `question_count` +
  `time_limit_minutes` + `is_public`), `ExamTemplateListItem`/
  `DetailResponse`, `ExamAttemptStartRequest`, `ExamAttemptQuestionResponse`
  (questão sem gabarito, com flag `answered`), `ExamAttemptListItem`/
  `DetailResponse`. Submissão de resposta reutiliza
  `AnswerSubmitRequest`/`AnswerResultResponse` de
  `schemas/practice/question_attempt.py` — mesmo contrato de treino.
- `api/v1/assessment/exam_templates.py`:
  - `POST /exam-templates` — cria molde (pessoal, ou público se admin).
  - `GET /exam-templates` — moldes visíveis ao usuário, paginado por cursor.
  - `GET /exam-templates/{id}` — detalhe do molde.
- `api/v1/assessment/exam_attempts.py`:
  - `POST /exam-attempts` — inicia simulado a partir de um molde.
  - `GET /exam-attempts` — histórico paginado do usuário autenticado.
  - `GET /exam-attempts/{id}` — detalhe (questões na ordem, sem gabarito,
    com flag `answered` por questão).
  - `POST /exam-attempts/{id}/questions/{question_id}/answer` — submete
    resposta, retorna resultado imediato (acerto/erro + gabarito comentado).
  - `POST /exam-attempts/{id}/finish` — finaliza o simulado.
  - `POST /exam-attempts/{id}/abandon` — marca o simulado como abandonado.
- `api/v1/router.py` — routers de `practice` registrados
  (`/training-sessions`, `/attempts`).

Todos os endpoints são pessoais (o próprio usuário autenticado via
`CurrentUser`) — treino não tem conceito de administração. Frontend não foi
tocado nesta etapa (`components/practice/*`, `config/practice.ts` seguem
com mock); a tela `app/(app)/questoes/novo-treino` ainda é um placeholder no
frontend, então não havia contrato de filtros a seguir além do que já foi
estabelecido em `content` (Etapa 7).
