"""Criação inicial do schema — 31 tabelas, 10 enums e trigger de busca.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-08-04
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE TYPE billing_period AS ENUM ('mensal', 'semestral', 'anual')")
    op.execute("CREATE TYPE subscription_status AS ENUM ('ativa', 'cancelada', 'inadimplente', 'expirada')")
    op.execute("CREATE TYPE exam_attempt_status AS ENUM ('em_andamento', 'finalizado', 'abandonado')")
    op.execute("CREATE TYPE payment_status AS ENUM ('pendente', 'aprovado', 'recusado', 'estornado')")
    op.execute("CREATE TYPE question_difficulty AS ENUM ('facil', 'media', 'dificil')")
    op.execute("CREATE TYPE question_status AS ENUM ('rascunho', 'publicada', 'em_revisao', 'desativada')")
    op.execute("CREATE TYPE attachment_type AS ENUM ('imagem', 'arquivo')")
    op.execute("CREATE TYPE question_revision_type AS ENUM ('criacao', 'edicao', 'status', 'exclusao')")
    op.execute("CREATE TYPE flashcard_grade AS ENUM ('errou', 'dificil', 'bom', 'facil')")
    op.execute("CREATE TYPE session_type AS ENUM ('treino', 'simulado')")

    op.execute("""CREATE TABLE disciplines (
	name VARCHAR(150) NOT NULL, 
	slug VARCHAR(160) NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (name)
)""")
    op.execute("""CREATE TABLE exam_boards (
	name VARCHAR(150) NOT NULL, 
	acronym VARCHAR(30) NOT NULL, 
	slug VARCHAR(160) NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (name), 
	UNIQUE (slug)
)""")
    op.execute("""CREATE TABLE organizations (
	name VARCHAR(200) NOT NULL, 
	acronym VARCHAR(30) NOT NULL, 
	slug VARCHAR(210) NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (name), 
	UNIQUE (slug)
)""")
    op.execute("""CREATE TABLE plans (
	name VARCHAR(100) NOT NULL, 
	slug VARCHAR(110) NOT NULL, 
	price_cents INTEGER NOT NULL, 
	billing_period billing_period NOT NULL, 
	features JSONB NOT NULL, 
	is_active BOOLEAN NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (slug)
)""")
    op.execute("""CREATE TABLE question_tags (
	name VARCHAR(80) NOT NULL, 
	slug VARCHAR(90) NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (name)
)""")
    op.execute("""CREATE TABLE users (
	email VARCHAR(255) NOT NULL, 
	password_hash VARCHAR(255) NOT NULL, 
	full_name VARCHAR(255) NOT NULL, 
	is_active BOOLEAN NOT NULL, 
	is_admin BOOLEAN NOT NULL, 
	email_verified_at TIMESTAMP WITH TIME ZONE, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id)
)""")
    op.execute("""CREATE TABLE admin_audit_logs (
	admin_user_id UUID NOT NULL, 
	action VARCHAR(100) NOT NULL, 
	entity_type VARCHAR(100) NOT NULL, 
	entity_id UUID, 
	extra_metadata JSONB NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	id UUID NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(admin_user_id) REFERENCES users (id) ON DELETE SET NULL
)""")
    op.execute("""CREATE TABLE exam_editions (
	organization_id UUID NOT NULL, 
	exam_board_id UUID NOT NULL, 
	year INTEGER NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	slug VARCHAR(270) NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(organization_id) REFERENCES organizations (id) ON DELETE RESTRICT, 
	FOREIGN KEY(exam_board_id) REFERENCES exam_boards (id) ON DELETE RESTRICT, 
	UNIQUE (slug)
)""")
    op.execute("""CREATE TABLE exam_templates (
	created_by UUID, 
	title VARCHAR(255) NOT NULL, 
	description VARCHAR(1000), 
	question_count INTEGER NOT NULL, 
	time_limit_minutes INTEGER, 
	filters_snapshot JSONB NOT NULL, 
	is_public BOOLEAN NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(created_by) REFERENCES users (id)
)""")
    op.execute("""CREATE TABLE notifications (
	user_id UUID NOT NULL, 
	type VARCHAR(60) NOT NULL, 
	title VARCHAR(255) NOT NULL, 
	body TEXT NOT NULL, 
	read_at TIMESTAMP WITH TIME ZONE, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
)""")
    op.execute("""CREATE TABLE refresh_tokens (
	user_id UUID NOT NULL, 
	token_hash VARCHAR(255) NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	revoked_at TIMESTAMP WITH TIME ZONE, 
	replaced_by_token_id UUID, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
	UNIQUE (token_hash), 
	FOREIGN KEY(replaced_by_token_id) REFERENCES refresh_tokens (id)
)""")
    op.execute("""CREATE TABLE study_streaks (
	user_id UUID NOT NULL, 
	current_streak INTEGER NOT NULL, 
	longest_streak INTEGER NOT NULL, 
	last_study_date DATE, 
	PRIMARY KEY (user_id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
)""")
    op.execute("""CREATE TABLE subjects (
	discipline_id UUID NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	slug VARCHAR(210) NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(discipline_id) REFERENCES disciplines (id) ON DELETE CASCADE
)""")
    op.execute("""CREATE TABLE subscriptions (
	user_id UUID NOT NULL, 
	plan_id UUID NOT NULL, 
	status subscription_status NOT NULL, 
	current_period_start TIMESTAMP WITH TIME ZONE NOT NULL, 
	current_period_end TIMESTAMP WITH TIME ZONE NOT NULL, 
	cancel_at_period_end BOOLEAN NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
	FOREIGN KEY(plan_id) REFERENCES plans (id) ON DELETE RESTRICT
)""")
    op.execute("""CREATE TABLE training_sessions (
	user_id UUID NOT NULL, 
	filters_snapshot JSONB NOT NULL, 
	total_questions INTEGER NOT NULL, 
	correct_count INTEGER NOT NULL, 
	started_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	finished_at TIMESTAMP WITH TIME ZONE, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
)""")
    op.execute("""CREATE TABLE user_daily_stats (
	user_id UUID NOT NULL, 
	date DATE NOT NULL, 
	questions_answered INTEGER NOT NULL, 
	correct_count INTEGER NOT NULL, 
	time_studied_seconds INTEGER NOT NULL, 
	id UUID NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_user_daily_stat UNIQUE (user_id, date), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
)""")
    op.execute("""CREATE TABLE user_profiles (
	user_id UUID NOT NULL, 
	target_exam VARCHAR(255), 
	avatar_url VARCHAR(500), 
	bio VARCHAR(1000), 
	phone VARCHAR(30), 
	birth_date DATE, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (user_id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
)""")
    op.execute("""CREATE TABLE user_subject_stats (
	user_id UUID NOT NULL, 
	discipline_id UUID NOT NULL, 
	questions_answered INTEGER NOT NULL, 
	correct_count INTEGER NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	id UUID NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_user_subject_stat UNIQUE (user_id, discipline_id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
	FOREIGN KEY(discipline_id) REFERENCES disciplines (id) ON DELETE CASCADE
)""")
    op.execute("""CREATE TABLE exam_attempts (
	exam_template_id UUID NOT NULL, 
	user_id UUID NOT NULL, 
	status exam_attempt_status NOT NULL, 
	total_questions INTEGER NOT NULL, 
	correct_count INTEGER NOT NULL, 
	started_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	finished_at TIMESTAMP WITH TIME ZONE, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(exam_template_id) REFERENCES exam_templates (id) ON DELETE RESTRICT, 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
)""")
    op.execute("""CREATE TABLE payments (
	subscription_id UUID NOT NULL, 
	amount_cents INTEGER NOT NULL, 
	currency VARCHAR(3) NOT NULL, 
	status payment_status NOT NULL, 
	provider VARCHAR(50), 
	provider_payment_id VARCHAR(255), 
	paid_at TIMESTAMP WITH TIME ZONE, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(subscription_id) REFERENCES subscriptions (id) ON DELETE CASCADE
)""")
    op.execute("""CREATE TABLE topics (
	subject_id UUID NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	slug VARCHAR(210) NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(subject_id) REFERENCES subjects (id) ON DELETE CASCADE
)""")
    op.execute("""CREATE TABLE questions (
	discipline_id UUID NOT NULL, 
	subject_id UUID, 
	topic_id UUID, 
	exam_board_id UUID NOT NULL, 
	exam_edition_id UUID, 
	organization_id UUID, 
	year INTEGER, 
	difficulty question_difficulty NOT NULL, 
	status question_status NOT NULL, 
	statement TEXT NOT NULL, 
	correct_alternative_letter VARCHAR(1) NOT NULL, 
	explanation TEXT, 
	created_by UUID, 
	search_vector TSVECTOR, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(discipline_id) REFERENCES disciplines (id) ON DELETE RESTRICT, 
	FOREIGN KEY(subject_id) REFERENCES subjects (id) ON DELETE SET NULL, 
	FOREIGN KEY(topic_id) REFERENCES topics (id) ON DELETE SET NULL, 
	FOREIGN KEY(exam_board_id) REFERENCES exam_boards (id) ON DELETE RESTRICT, 
	FOREIGN KEY(exam_edition_id) REFERENCES exam_editions (id) ON DELETE SET NULL, 
	FOREIGN KEY(organization_id) REFERENCES organizations (id) ON DELETE SET NULL, 
	FOREIGN KEY(created_by) REFERENCES users (id)
)""")
    op.execute("""CREATE TABLE flashcards (
	user_id UUID NOT NULL, 
	question_id UUID, 
	discipline_id UUID, 
	front TEXT NOT NULL, 
	back TEXT NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
	FOREIGN KEY(question_id) REFERENCES questions (id) ON DELETE SET NULL, 
	FOREIGN KEY(discipline_id) REFERENCES disciplines (id) ON DELETE SET NULL
)""")
    op.execute("""CREATE TABLE question_alternatives (
	question_id UUID NOT NULL, 
	letter VARCHAR(1) NOT NULL, 
	text TEXT NOT NULL, 
	is_correct BOOLEAN NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_question_alternative_letter UNIQUE (question_id, letter), 
	FOREIGN KEY(question_id) REFERENCES questions (id) ON DELETE CASCADE
)""")
    op.execute("""CREATE TABLE question_attachments (
	question_id UUID NOT NULL, 
	type attachment_type NOT NULL, 
	url VARCHAR(1000) NOT NULL, 
	alt_text VARCHAR(500), 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(question_id) REFERENCES questions (id) ON DELETE CASCADE
)""")
    op.execute("""CREATE TABLE question_revisions (
	question_id UUID NOT NULL, 
	changed_by UUID, 
	change_type question_revision_type NOT NULL, 
	snapshot JSONB NOT NULL, 
	changed_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	id UUID NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(question_id) REFERENCES questions (id) ON DELETE CASCADE, 
	FOREIGN KEY(changed_by) REFERENCES users (id)
)""")
    op.execute("""CREATE TABLE question_tag_links (
	question_id UUID NOT NULL, 
	tag_id UUID NOT NULL, 
	PRIMARY KEY (question_id, tag_id), 
	FOREIGN KEY(question_id) REFERENCES questions (id) ON DELETE CASCADE, 
	FOREIGN KEY(tag_id) REFERENCES question_tags (id) ON DELETE CASCADE
)""")
    op.execute("""CREATE TABLE training_session_questions (
	session_id UUID NOT NULL, 
	question_id UUID NOT NULL, 
	position INTEGER NOT NULL, 
	id UUID NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(session_id) REFERENCES training_sessions (id) ON DELETE CASCADE, 
	FOREIGN KEY(question_id) REFERENCES questions (id) ON DELETE RESTRICT
)""")
    op.execute("""CREATE TABLE exam_attempt_questions (
	exam_attempt_id UUID NOT NULL, 
	question_id UUID NOT NULL, 
	position INTEGER NOT NULL, 
	selected_alternative_id UUID, 
	is_correct BOOLEAN, 
	time_spent_seconds INTEGER, 
	id UUID NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(exam_attempt_id) REFERENCES exam_attempts (id) ON DELETE CASCADE, 
	FOREIGN KEY(question_id) REFERENCES questions (id) ON DELETE RESTRICT, 
	FOREIGN KEY(selected_alternative_id) REFERENCES question_alternatives (id)
)""")
    op.execute("""CREATE TABLE flashcard_reviews (
	flashcard_id UUID NOT NULL, 
	user_id UUID NOT NULL, 
	easiness_factor FLOAT NOT NULL, 
	interval_days INTEGER NOT NULL, 
	repetitions INTEGER NOT NULL, 
	due_date DATE NOT NULL, 
	last_reviewed_at TIMESTAMP WITH TIME ZONE, 
	last_grade flashcard_grade, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (flashcard_id), 
	FOREIGN KEY(flashcard_id) REFERENCES flashcards (id) ON DELETE CASCADE, 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
)""")
    op.execute("""CREATE TABLE question_attempts (
	user_id UUID NOT NULL, 
	question_id UUID NOT NULL, 
	session_type session_type NOT NULL, 
	session_id UUID NOT NULL, 
	selected_alternative_id UUID, 
	is_correct BOOLEAN, 
	time_spent_seconds INTEGER, 
	answered_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	id UUID NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
	FOREIGN KEY(question_id) REFERENCES questions (id) ON DELETE RESTRICT, 
	FOREIGN KEY(selected_alternative_id) REFERENCES question_alternatives (id)
)""")

    op.execute("""CREATE UNIQUE INDEX ix_disciplines_slug ON disciplines (slug)""")
    op.execute("""CREATE UNIQUE INDEX ix_exam_boards_acronym ON exam_boards (acronym)""")
    op.execute("""CREATE INDEX ix_organizations_acronym ON organizations (acronym)""")
    op.execute("""CREATE UNIQUE INDEX ix_question_tags_slug ON question_tags (slug)""")
    op.execute("""CREATE UNIQUE INDEX ix_users_email ON users (email)""")
    op.execute("""CREATE INDEX ix_admin_audit_logs_created_at ON admin_audit_logs (created_at)""")
    op.execute("""CREATE INDEX ix_admin_audit_logs_admin_user_id ON admin_audit_logs (admin_user_id)""")
    op.execute("""CREATE INDEX ix_exam_editions_exam_board_id ON exam_editions (exam_board_id)""")
    op.execute("""CREATE INDEX ix_exam_editions_year ON exam_editions (year)""")
    op.execute("""CREATE INDEX ix_exam_editions_organization_id ON exam_editions (organization_id)""")
    op.execute("""CREATE INDEX ix_notifications_user_id ON notifications (user_id)""")
    op.execute("""CREATE INDEX ix_refresh_tokens_user_id ON refresh_tokens (user_id)""")
    op.execute("""CREATE INDEX ix_subjects_discipline_id ON subjects (discipline_id)""")
    op.execute("""CREATE INDEX ix_subjects_slug ON subjects (slug)""")
    op.execute("""CREATE INDEX ix_subscriptions_status ON subscriptions (status)""")
    op.execute("""CREATE INDEX ix_subscriptions_user_id ON subscriptions (user_id)""")
    op.execute("""CREATE INDEX ix_subscriptions_plan_id ON subscriptions (plan_id)""")
    op.execute("""CREATE INDEX ix_training_sessions_user_id ON training_sessions (user_id)""")
    op.execute("""CREATE INDEX ix_user_daily_stats_user_id ON user_daily_stats (user_id)""")
    op.execute("""CREATE INDEX ix_user_subject_stats_discipline_id ON user_subject_stats (discipline_id)""")
    op.execute("""CREATE INDEX ix_user_subject_stats_user_id ON user_subject_stats (user_id)""")
    op.execute("""CREATE INDEX ix_exam_attempts_exam_template_id ON exam_attempts (exam_template_id)""")
    op.execute("""CREATE INDEX ix_exam_attempts_user_id ON exam_attempts (user_id)""")
    op.execute("""CREATE INDEX ix_exam_attempts_status ON exam_attempts (status)""")
    op.execute("""CREATE INDEX ix_payments_subscription_id ON payments (subscription_id)""")
    op.execute("""CREATE INDEX ix_payments_status ON payments (status)""")
    op.execute("""CREATE INDEX ix_payments_provider_payment_id ON payments (provider_payment_id)""")
    op.execute("""CREATE INDEX ix_topics_slug ON topics (slug)""")
    op.execute("""CREATE INDEX ix_topics_subject_id ON topics (subject_id)""")
    op.execute("""CREATE INDEX ix_questions_exam_edition_id ON questions (exam_edition_id)""")
    op.execute("""CREATE INDEX ix_questions_discipline_id ON questions (discipline_id)""")
    op.execute("""CREATE INDEX ix_questions_exam_board_id ON questions (exam_board_id)""")
    op.execute("""CREATE INDEX ix_questions_year ON questions (year)""")
    op.execute("""CREATE INDEX ix_questions_status ON questions (status)""")
    op.execute("""CREATE INDEX ix_questions_difficulty ON questions (difficulty)""")
    op.execute("""CREATE INDEX ix_questions_organization_id ON questions (organization_id)""")
    op.execute("""CREATE INDEX ix_questions_topic_id ON questions (topic_id)""")
    op.execute("""CREATE INDEX ix_questions_filter_composite ON questions (discipline_id, subject_id, exam_board_id, year, difficulty, status)""")
    op.execute("""CREATE INDEX ix_questions_subject_id ON questions (subject_id)""")
    op.execute("""CREATE INDEX ix_questions_search_vector ON questions USING gin (search_vector)""")
    op.execute("""CREATE INDEX ix_flashcards_user_id ON flashcards (user_id)""")
    op.execute("""CREATE INDEX ix_question_alternatives_question_id ON question_alternatives (question_id)""")
    op.execute("""CREATE INDEX ix_question_attachments_question_id ON question_attachments (question_id)""")
    op.execute("""CREATE INDEX ix_question_revisions_question_id ON question_revisions (question_id)""")
    op.execute("""CREATE INDEX ix_question_revisions_changed_at ON question_revisions (changed_at)""")
    op.execute("""CREATE INDEX ix_training_session_questions_question_id ON training_session_questions (question_id)""")
    op.execute("""CREATE INDEX ix_training_session_questions_session_id ON training_session_questions (session_id)""")
    op.execute("""CREATE INDEX ix_exam_attempt_questions_exam_attempt_id ON exam_attempt_questions (exam_attempt_id)""")
    op.execute("""CREATE INDEX ix_exam_attempt_questions_question_id ON exam_attempt_questions (question_id)""")
    op.execute("""CREATE INDEX ix_flashcard_reviews_due_date ON flashcard_reviews (due_date)""")
    op.execute("""CREATE INDEX ix_flashcard_reviews_user_id ON flashcard_reviews (user_id)""")
    op.execute("""CREATE INDEX ix_question_attempts_question_id ON question_attempts (question_id)""")
    op.execute("""CREATE INDEX ix_question_attempts_session_id ON question_attempts (session_id)""")
    op.execute("""CREATE INDEX ix_question_attempts_user_id ON question_attempts (user_id)""")
    op.execute("""CREATE INDEX ix_question_attempts_session_type ON question_attempts (session_type)""")
    op.execute("""CREATE INDEX ix_question_attempts_answered_at ON question_attempts (answered_at)""")

    op.execute("""
        CREATE OR REPLACE FUNCTION questions_search_vector_update() RETURNS trigger AS $$
        BEGIN
            NEW.search_vector := to_tsvector('portuguese', coalesce(NEW.statement, '') || ' ' || coalesce(NEW.explanation, ''));
            RETURN NEW;
        END
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER trg_questions_search_vector
        BEFORE INSERT OR UPDATE ON questions
        FOR EACH ROW EXECUTE FUNCTION questions_search_vector_update();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_questions_search_vector ON questions")
    op.execute("DROP FUNCTION IF EXISTS questions_search_vector_update")
    op.execute("DROP TABLE IF EXISTS question_attempts CASCADE")
    op.execute("DROP TABLE IF EXISTS flashcard_reviews CASCADE")
    op.execute("DROP TABLE IF EXISTS exam_attempt_questions CASCADE")
    op.execute("DROP TABLE IF EXISTS training_session_questions CASCADE")
    op.execute("DROP TABLE IF EXISTS question_tag_links CASCADE")
    op.execute("DROP TABLE IF EXISTS question_revisions CASCADE")
    op.execute("DROP TABLE IF EXISTS question_attachments CASCADE")
    op.execute("DROP TABLE IF EXISTS question_alternatives CASCADE")
    op.execute("DROP TABLE IF EXISTS flashcards CASCADE")
    op.execute("DROP TABLE IF EXISTS questions CASCADE")
    op.execute("DROP TABLE IF EXISTS topics CASCADE")
    op.execute("DROP TABLE IF EXISTS payments CASCADE")
    op.execute("DROP TABLE IF EXISTS exam_attempts CASCADE")
    op.execute("DROP TABLE IF EXISTS user_subject_stats CASCADE")
    op.execute("DROP TABLE IF EXISTS user_profiles CASCADE")
    op.execute("DROP TABLE IF EXISTS user_daily_stats CASCADE")
    op.execute("DROP TABLE IF EXISTS training_sessions CASCADE")
    op.execute("DROP TABLE IF EXISTS subscriptions CASCADE")
    op.execute("DROP TABLE IF EXISTS subjects CASCADE")
    op.execute("DROP TABLE IF EXISTS study_streaks CASCADE")
    op.execute("DROP TABLE IF EXISTS refresh_tokens CASCADE")
    op.execute("DROP TABLE IF EXISTS notifications CASCADE")
    op.execute("DROP TABLE IF EXISTS exam_templates CASCADE")
    op.execute("DROP TABLE IF EXISTS exam_editions CASCADE")
    op.execute("DROP TABLE IF EXISTS admin_audit_logs CASCADE")
    op.execute("DROP TABLE IF EXISTS users CASCADE")
    op.execute("DROP TABLE IF EXISTS question_tags CASCADE")
    op.execute("DROP TABLE IF EXISTS plans CASCADE")
    op.execute("DROP TABLE IF EXISTS organizations CASCADE")
    op.execute("DROP TABLE IF EXISTS exam_boards CASCADE")
    op.execute("DROP TABLE IF EXISTS disciplines CASCADE")
    op.execute("DROP TYPE IF EXISTS billing_period")
    op.execute("DROP TYPE IF EXISTS subscription_status")
    op.execute("DROP TYPE IF EXISTS exam_attempt_status")
    op.execute("DROP TYPE IF EXISTS payment_status")
    op.execute("DROP TYPE IF EXISTS question_difficulty")
    op.execute("DROP TYPE IF EXISTS question_status")
    op.execute("DROP TYPE IF EXISTS attachment_type")
    op.execute("DROP TYPE IF EXISTS question_revision_type")
    op.execute("DROP TYPE IF EXISTS flashcard_grade")
    op.execute("DROP TYPE IF EXISTS session_type")
