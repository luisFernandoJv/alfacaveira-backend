# Foco Policial — Backend

Backend do SaaS Foco Policial. Ver `docs/architecture.md` para as decisões
arquiteturais completas.

## Estrutura

```
backend/
  app/
    api/v1/<contexto>/     # routers HTTP por bounded context
    core/                  # config, logging, exceções, paginação, respostas
    database/               # engine, sessão async, unit of work
    models/<contexto>/      # modelos SQLAlchemy
    schemas/<contexto>/     # schemas Pydantic (request/response)
    repositories/<contexto>/# acesso a dados (interfaces + implementação)
    services/<contexto>/    # regras de negócio
    middlewares/            # rate limiting, logging de requisições
    security/                # senha, JWT, refresh token, dependencies
    workers/                 # background jobs
    utils/                   # utilitários genéricos
    main.py                  # entrypoint FastAPI
  tests/
    unit/                    # services com repositórios fake
    integration/              # endpoints via httpx.AsyncClient + banco real
    factories/                 # geração de dados de teste
  docs/                       # architecture, database, api, developer guide
  migrations/                 # Alembic (populado na Etapa 4)
  scripts/                    # scripts de inicialização/deploy
```

Bounded contexts: `identity`, `content`, `practice`, `assessment`,
`learning`, `analytics`, `billing`, `platform`.

## Como rodar

```bash
cp .env.example .env
docker compose up --build
```

Isso sobe Postgres + Redis + a API, aplica a migration inicial
automaticamente (`alembic upgrade head`) e serve em `http://localhost:8000`.
Healthcheck em `GET /health`.

Desenvolvimento local sem Docker:

```bash
poetry install
poetry run alembic upgrade head
poetry run uvicorn app.main:app --reload
```

## Status

Etapas 1-9 concluídas (arquitetura, estrutura, modelagem do banco,
configuração do projeto, autenticação, usuários/perfil, questões,
treinos/sessões, simulados). Endpoints disponíveis: `/api/v1/auth`
(`register`, `login`, `refresh`, `logout`), `/api/v1/users` (`me`,
`me/profile`, `me/change-password`, listagem e administração de usuários),
`/api/v1/questions` (CRUD admin + listagem pública paginada/filtrável +
busca full-text + detalhe), `/api/v1/disciplines`,
`/api/v1/subjects/{id}/topics`, `/api/v1/exam-boards`,
`/api/v1/organizations` e `/api/v1/exam-editions` (taxonomia para os
filtros do frontend), `/api/v1/training-sessions` (criar treino a partir de
filtros, listar/consultar histórico, responder questão da sessão, finalizar),
`/api/v1/attempts` (histórico geral de respostas), `/api/v1/exam-templates`
(criar/listar/consultar moldes de simulado, públicos ou pessoais) e
`/api/v1/exam-attempts` (iniciar simulado a partir de um molde,
listar/consultar histórico, responder questão, finalizar, abandonar).
Próxima etapa: Flashcards (`learning`). Ver progresso completo em
`docs/architecture.md`.
