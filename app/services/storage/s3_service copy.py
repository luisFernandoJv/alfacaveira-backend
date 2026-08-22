"""Serviço de armazenamento de imagens das questões em S3, via presigned URL.

O backend NUNCA recebe o binário da imagem — só gera uma URL assinada de
upload (PUT) que o navegador do admin usa para subir o arquivo direto pro
bucket. Isso mantém a API leve (não bufferiza arquivo grande) e escala sem
esforço. O RDS Postgres só guarda a URL final (`question_attachments.url`).
"""

import uuid
from typing import BinaryIO

import boto3
from botocore.client import Config as BotoConfig
from botocore.exceptions import ClientError

from app.core.config import settings
from app.core.exceptions import DomainError

ALLOWED_CONTENT_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}


class S3ConfigError(DomainError):
    """S3 não está configurado corretamente (bucket/URL pública ausentes)."""

    code = "s3_not_configured"


class S3UploadValidationError(DomainError):
    """Tipo de arquivo (ou outro parâmetro) inválido para upload."""

    code = "s3_upload_invalid"


def _get_client():
    if not settings.S3_BUCKET_NAME:
        raise S3ConfigError(
            "Upload de imagens não está configurado: defina S3_BUCKET_NAME "
            "e S3_PUBLIC_BASE_URL nas variáveis de ambiente do backend."
        )
    kwargs: dict = {
        "region_name": settings.S3_REGION,
        "config": BotoConfig(signature_version="s3v4"),
    }
    # Em produção, prefira a Task Role do ECS (não passe credenciais
    # explícitas). Local/dev pode usar S3_ACCESS_KEY_ID/SECRET no .env.
    if settings.S3_ACCESS_KEY_ID and settings.S3_SECRET_ACCESS_KEY:
        kwargs["aws_access_key_id"] = settings.S3_ACCESS_KEY_ID
        kwargs["aws_secret_access_key"] = settings.S3_SECRET_ACCESS_KEY
    return boto3.client("s3", **kwargs)


def create_presigned_upload(
    filename: str,
    content_type: str,
    prefix: str | None = None,
) -> dict:
    """Gera uma URL assinada de upload (PUT) + a URL pública final do objeto.

    A chave do objeto é gerada no backend (UUID), nunca a partir do nome
    original do arquivo — evita path traversal, colisão de nomes e
    vazamento do nome original do arquivo do usuário/admin.
    """
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise S3UploadValidationError(
            f"Tipo de arquivo não permitido: '{content_type}'. "
            f"Aceitos: {', '.join(ALLOWED_CONTENT_TYPES)}."
        )

    extension = ALLOWED_CONTENT_TYPES[content_type]
    object_prefix = (prefix or settings.S3_QUESTIONS_PREFIX).strip("/")
    key = f"{object_prefix}/{uuid.uuid4().hex}{extension}"

    client = _get_client()
    try:
        upload_url = client.generate_presigned_url(
            ClientMethod="put_object",
            Params={
                "Bucket": settings.S3_BUCKET_NAME,
                "Key": key,
                "ContentType": content_type,
            },
            ExpiresIn=settings.S3_PRESIGN_EXPIRES_SECONDS,
        )
    except ClientError as exc:
        raise S3ConfigError(f"Falha ao gerar URL de upload: {exc}") from exc

    public_base = settings.S3_PUBLIC_BASE_URL.rstrip("/")
    return {
        "upload_url": upload_url,
        "public_url": f"{public_base}/{key}",
        "key": key,
        "expires_in": settings.S3_PRESIGN_EXPIRES_SECONDS,
    }

def upload_profile_avatar(fileobj: BinaryIO, content_type: str, prefix: str | None = None) -> dict:
    """Faz upload server-side do avatar para eliminar CORS direto do navegador."""
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise S3UploadValidationError(
            f"Tipo de arquivo não permitido: '{content_type}'. "
            f"Aceitos: {', '.join(ALLOWED_CONTENT_TYPES)}."
        )

    object_prefix = (prefix or settings.S3_PROFILE_PREFIX).strip("/")
    extension = ALLOWED_CONTENT_TYPES[content_type]
    key = f"{object_prefix}/{uuid.uuid4().hex}{extension}"
    client = _get_client()

    try:
        client.upload_fileobj(
            fileobj,
            settings.S3_BUCKET_NAME,
            key,
            ExtraArgs={"ContentType": content_type},
        )
    except ClientError as exc:
        raise S3ConfigError(f"Falha ao enviar avatar para o S3: {exc}") from exc

    public_base = settings.S3_PUBLIC_BASE_URL.rstrip("/")
    return {
        "key": key,
        "public_url": f"{public_base}/{key}",
    }


def create_presigned_download(key: str) -> str:
    """Gera URL assinada de GET sem assinar Content-Type."""
    if not settings.S3_BUCKET_NAME:
        raise S3ConfigError("S3_BUCKET_NAME não configurado.")

    client = _get_client()
    try:
        return client.generate_presigned_url(
            ClientMethod="get_object",
            Params={
                "Bucket": settings.S3_BUCKET_NAME,
                "Key": key,
            },
            ExpiresIn=settings.S3_PRESIGN_EXPIRES_SECONDS,
        )
    except ClientError as exc:
        raise S3ConfigError(f"Falha ao gerar URL de leitura: {exc}") from exc
