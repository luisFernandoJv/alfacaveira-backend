"""Envio de e-mail transacional (hoje: recuperação de senha + notificações de assinatura).

Decisão de design (etapa de recuperação de senha):

Em vez de acoplar o projeto a um provedor específico (Resend, SendGrid,
SES...) antes de haver uma escolha de negócio definida, o serviço expõe uma
interface única (`send_password_reset_email`) com dois drivers selecionáveis
por variável de ambiente (`EMAIL_DRIVER`):

- `console` (padrão): não envia nada de verdade — apenas loga o e-mail
  formatado via `structlog`. Isso deixa o fluxo de "esqueci minha senha"
  100% testável em desenvolvimento (e em qualquer ambiente novo) sem exigir
  nenhuma credencial externa. O link de redefinição aparece direto no log.
- `smtp`: envia via SMTP puro (stdlib `smtplib`), o que funciona com
  praticamente qualquer provedor transacional (SES, Postmark, Mailgun,
  Resend, Gmail/Workspace etc. — todos oferecem um endpoint SMTP), sem
  adicionar nenhuma dependência nova ao projeto. Basta preencher as
  variáveis `SMTP_*` no `.env` quando o provedor for escolhido.

Quando a equipe decidir o provedor definitivo, normalmente basta configurar
as variáveis `SMTP_*` — nenhuma mudança de código é necessária. Se no futuro
for adotado um provedor via API HTTP (em vez de SMTP), um novo driver pode
ser adicionado aqui sem alterar `AuthService` nem os endpoints.
"""

import smtplib
import ssl
from asyncio import to_thread
from email.message import EmailMessage
from typing import Any, Dict, Optional

import structlog

from app.core.config import settings

logger = structlog.get_logger(__name__)


class EmailService:
    # ==================================================================== #
    # Método existente: recuperação de senha                               #
    # ==================================================================== #

    async def send_password_reset_email(self, *, to_email: str, to_name: str, reset_url: str) -> None:
        subject = "Redefinição de senha — Alfa Caveira"
        text_body, html_body = _render_password_reset_email(to_name=to_name, reset_url=reset_url)

        if settings.EMAIL_DRIVER == "smtp":
            await self._send_via_smtp(
                to_email=to_email, subject=subject, text_body=text_body, html_body=html_body
            )
        else:
            self._send_via_console(to_email=to_email, subject=subject, text_body=text_body)

    # ==================================================================== #
    # NOVO MÉTODO: envio genérico de e-mails transacionais (PROMPT 13)     #
    # ==================================================================== #

    async def send_email(
        self,
        *,
        to_email: str,
        to_name: str,
        subject: str,
        template_name: str,
        context: Dict[str, Any],
    ) -> None:
        """Envia um e-mail transacional usando um template nomeado.

        Args:
            to_email: Endereço de e-mail do destinatário
            to_name: Nome completo do destinatário
            subject: Assunto do e-mail
            template_name: Nome do template (ex: 'payment_approved')
            context: Dicionário com variáveis para o template

        O template é renderizado com o contexto fornecido, e o primeiro nome
        do destinatário é automaticamente adicionado ao contexto como 'first_name'.
        """
        first_name = to_name.split(" ")[0] if to_name else ""
        context_with_name = {"first_name": first_name, **context}

        text_body, html_body = self._render_transactional_template(
            template_name=template_name,
            context=context_with_name,
        )

        if text_body is None or html_body is None:
            logger.error(
                "email.template_not_found_or_invalid",
                template_name=template_name,
                to=to_email,
            )
            return

        if settings.EMAIL_DRIVER == "smtp":
            await self._send_via_smtp(
                to_email=to_email,
                subject=subject,
                text_body=text_body,
                html_body=html_body,
            )
        else:
            self._send_via_console(
                to_email=to_email,
                subject=subject,
                text_body=text_body,
            )

    def _render_transactional_template(
        self,
        template_name: str,
        context: Dict[str, Any],
    ) -> tuple[Optional[str], Optional[str]]:
        """Renderiza um template transacional.

        Retorna (text_body, html_body) ou (None, None) se o template não existir.
        """
        templates = {
            # Eventos de pagamento
            "payment_approved": (
                "Olá {first_name}!\n\n"
                "Seu pagamento para o plano {plan_name} (R$ {amount:.2f}) foi aprovado. "
                "Agora você tem acesso a todos os recursos do plano.\n\n"
                "Equipe Alfa Caveira",
                "<p>Olá <strong>{first_name}</strong>!</p>"
                "<p>Seu pagamento para o plano <strong>{plan_name}</strong> (R$ {amount:.2f}) "
                "foi aprovado. Agora você tem acesso a todos os recursos do plano.</p>"
                "<p>Equipe Alfa Caveira</p>",
            ),
            "payment_failed": (
                "Olá {first_name}!\n\n"
                "Houve um problema com o pagamento do plano {plan_name}. "
                "Por favor, verifique seus dados de pagamento no portal do assinante.\n\n"
                "Equipe Alfa Caveira",
                "<p>Olá <strong>{first_name}</strong>!</p>"
                "<p>Houve um problema com o pagamento do plano <strong>{plan_name}</strong>. "
                "Por favor, verifique seus dados de pagamento no portal do assinante.</p>"
                "<p>Equipe Alfa Caveira</p>",
            ),
            # Eventos de renovação
            "renewal_success": (
                "Olá {first_name}!\n\n"
                "Seu plano {plan_name} foi renovado com sucesso! "
                "A próxima cobrança será em {next_renewal}.\n\n"
                "Equipe Alfa Caveira",
                "<p>Olá <strong>{first_name}</strong>!</p>"
                "<p>Seu plano <strong>{plan_name}</strong> foi renovado com sucesso! "
                "A próxima cobrança será em <strong>{next_renewal}</strong>.</p>"
                "<p>Equipe Alfa Caveira</p>",
            ),
            "renewal_reminder": (
                "Olá {first_name}!\n\n"
                "Seu plano {plan_name} será renovado em {days_left} dia(s), "
                "no valor de R$ {amount:.2f}. "
                "Se você não quiser renovar, cancele antes dessa data no portal do assinante.\n\n"
                "Equipe Alfa Caveira",
                "<p>Olá <strong>{first_name}</strong>!</p>"
                "<p>Seu plano <strong>{plan_name}</strong> será renovado em "
                "<strong>{days_left}</strong> dia(s), no valor de R$ {amount:.2f}.</p>"
                "<p>Se você não quiser renovar, cancele antes dessa data no portal do assinante.</p>"
                "<p>Equipe Alfa Caveira</p>",
            ),
            # Eventos de gerenciamento
            "cancellation": (
                "Olá {first_name}!\n\n"
                "Seu plano {plan_name} foi cancelado. Você terá acesso até {expiration_date}.\n\n"
                "Equipe Alfa Caveira",
                "<p>Olá <strong>{first_name}</strong>!</p>"
                "<p>Seu plano <strong>{plan_name}</strong> foi cancelado. "
                "Você terá acesso até <strong>{expiration_date}</strong>.</p>"
                "<p>Equipe Alfa Caveira</p>",
            ),
            "reactivation": (
                "Olá {first_name}!\n\n"
                "Seu plano {plan_name} foi reativado. A cobrança continuará normalmente.\n\n"
                "Equipe Alfa Caveira",
                "<p>Olá <strong>{first_name}</strong>!</p>"
                "<p>Seu plano <strong>{plan_name}</strong> foi reativado. "
                "A cobrança continuará normalmente.</p>"
                "<p>Equipe Alfa Caveira</p>",
            ),
            "plan_change": (
                "Olá {first_name}!\n\n"
                "Seu plano foi alterado de {old_plan} para {new_plan}. "
                "A próxima cobrança será de R$ {new_amount:.2f}.\n\n"
                "Equipe Alfa Caveira",
                "<p>Olá <strong>{first_name}</strong>!</p>"
                "<p>Seu plano foi alterado de <strong>{old_plan}</strong> para "
                "<strong>{new_plan}</strong>. A próxima cobrança será de R$ {new_amount:.2f}.</p>"
                "<p>Equipe Alfa Caveira</p>",
            ),
            # Eventos de dunning (inadimplência)
            "dunning_recovered": (
                "Olá {first_name}!\n\n"
                "Uma cobrança pendente do seu plano {plan_name} foi regularizada. "
                "Seu acesso está normalizado.\n\n"
                "Equipe Alfa Caveira",
                "<p>Olá <strong>{first_name}</strong>!</p>"
                "<p>Uma cobrança pendente do seu plano <strong>{plan_name}</strong> foi regularizada. "
                "Seu acesso está normalizado.</p>"
                "<p>Equipe Alfa Caveira</p>",
            ),
            "dunning_retry_failed": (
                "Olá {first_name}!\n\n"
                "A cobrança do seu plano {plan_name} falhou novamente. "
                "Atualize seus dados de pagamento para evitar a perda de acesso.\n\n"
                "Equipe Alfa Caveira",
                "<p>Olá <strong>{first_name}</strong>!</p>"
                "<p>A cobrança do seu plano <strong>{plan_name}</strong> falhou novamente. "
                "Atualize seus dados de pagamento para evitar a perda de acesso.</p>"
                "<p>Equipe Alfa Caveira</p>",
            ),
            "dunning_expired": (
                "Olá {first_name}!\n\n"
                "Seu plano {plan_name} foi expirado por falta de pagamento. "
                "Acesse o portal para regularizar sua assinatura.\n\n"
                "Equipe Alfa Caveira",
                "<p>Olá <strong>{first_name}</strong>!</p>"
                "<p>Seu plano <strong>{plan_name}</strong> foi expirado por falta de pagamento. "
                "Acesse o portal para regularizar sua assinatura.</p>"
                "<p>Equipe Alfa Caveira</p>",
            ),
        }

        template = templates.get(template_name)
        if template is None:
            return None, None

        try:
            text_body = template[0].format(**context)
            html_body = template[1].format(**context)
            return text_body, html_body
        except KeyError as e:
            logger.error(
                "email.template_missing_key",
                template_name=template_name,
                missing_key=str(e),
                context=context,
            )
            return None, None

    # ==================================================================== #
    # Métodos privados de envio (console e SMTP)                           #
    # ==================================================================== #

    def _send_via_console(self, *, to_email: str, subject: str, text_body: str) -> None:
        logger.info(
            "email.sent (console driver — nenhum e-mail real foi enviado)",
            to=to_email,
            subject=subject,
            body=text_body,
        )

    async def _send_via_smtp(
        self, *, to_email: str, subject: str, text_body: str, html_body: str
    ) -> None:
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>"
        message["To"] = to_email
        message.set_content(text_body)
        message.add_alternative(html_body, subtype="html")

        def _send() -> None:
            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as client:
                if settings.SMTP_USE_TLS:
                    client.starttls(context=ssl.create_default_context())
                if settings.SMTP_USER:
                    client.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                client.send_message(message)

        try:
            await to_thread(_send)
        except (OSError, smtplib.SMTPException) as exc:
            # Nunca propagamos falha de e-mail como erro 500 para quem pediu a
            # redefinição: do ponto de vista do usuário, o pedido "funcionou"
            # (por segurança, a resposta é sempre genérica — ver AuthService).
            # A falha real fica registrada no log para observabilidade.
            logger.error("email.send_failed", to=to_email, error=str(exc))


# ======================================================================== #
# Função auxiliar: renderização do e-mail de recuperação de senha          #
# ======================================================================== #


def _render_password_reset_email(*, to_name: str, reset_url: str) -> tuple[str, str]:
    first_name = to_name.split(" ")[0] if to_name else ""
    text_body = (
        f"Olá{f', {first_name}' if first_name else ''}!\n\n"
        "Recebemos um pedido para redefinir a senha da sua conta no Alfa Caveira.\n\n"
        f"Para criar uma nova senha, acesse o link abaixo:\n{reset_url}\n\n"
        "Este link expira em 1 hora. Se você não pediu essa redefinição, "
        "pode ignorar este e-mail com segurança — sua senha atual continua válida.\n\n"
        "Equipe Alfa Caveira"
    )
    html_body = f"""\
<!doctype html>
<html>
  <body style="font-family: -apple-system, Segoe UI, Roboto, sans-serif; background:#0b0f14; padding:32px; color:#e5e7eb;">
    <table role="presentation" style="max-width:480px; margin:0 auto; background:#131a22; border-radius:16px; padding:32px;">
      <tr><td>
        <h1 style="font-size:20px; margin:0 0 16px;">Redefinir senha</h1>
        <p style="font-size:14px; line-height:1.6; color:#9ca3af;">
          Olá{f', {first_name}' if first_name else ''}! Recebemos um pedido para redefinir a
          senha da sua conta no Alfa Caveira.
        </p>
        <p style="text-align:center; margin:28px 0;">
          <a href="{reset_url}"
             style="background:#f97316; color:#0b0f14; font-weight:700; text-decoration:none;
                    padding:12px 24px; border-radius:10px; display:inline-block; font-size:14px;">
            Criar nova senha
          </a>
        </p>
        <p style="font-size:12px; line-height:1.6; color:#6b7280;">
          Este link expira em 1 hora. Se você não pediu essa redefinição, pode ignorar
          este e-mail com segurança — sua senha atual continua válida.
        </p>
      </td></tr>
    </table>
  </body>
</html>"""
    return text_body, html_body