"""Envio de e-mail transacional (hoje: apenas recuperação de senha).

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

import structlog

from app.core.config import settings

logger = structlog.get_logger(__name__)


class EmailService:
    async def send_password_reset_email(self, *, to_email: str, to_name: str, reset_url: str) -> None:
        subject = "Redefinição de senha — Foco Policial"
        text_body, html_body = _render_password_reset_email(to_name=to_name, reset_url=reset_url)

        if settings.EMAIL_DRIVER == "smtp":
            await self._send_via_smtp(
                to_email=to_email, subject=subject, text_body=text_body, html_body=html_body
            )
        else:
            self._send_via_console(to_email=to_email, subject=subject, text_body=text_body)

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


def _render_password_reset_email(*, to_name: str, reset_url: str) -> tuple[str, str]:
    first_name = to_name.split(" ")[0] if to_name else ""
    text_body = (
        f"Olá{f', {first_name}' if first_name else ''}!\n\n"
        "Recebemos um pedido para redefinir a senha da sua conta no Foco Policial.\n\n"
        f"Para criar uma nova senha, acesse o link abaixo:\n{reset_url}\n\n"
        "Este link expira em 1 hora. Se você não pediu essa redefinição, "
        "pode ignorar este e-mail com segurança — sua senha atual continua válida.\n\n"
        "Equipe Foco Policial"
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
          senha da sua conta no Foco Policial.
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
