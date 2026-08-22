#!/usr/bin/env python3
"""Configura CORS mínimo para o bucket S3 de imagens.

O fluxo novo de avatar usa upload server-side e não depende deste CORS.
A configuração continua útil para anexos de questões que usam presigned PUT.
"""

import json
import os

import boto3


def main() -> None:
    bucket = os.environ["S3_BUCKET_NAME"]
    origins = [
        value.strip()
        for value in os.environ.get(
            "S3_CORS_ALLOWED_ORIGINS",
            "https://alfacaveira.com,https://www.alfacaveira.com",
        ).split(",")
        if value.strip()
    ]

    config = {
        "CORSRules": [
            {
                "AllowedOrigins": origins,
                "AllowedMethods": ["GET", "PUT", "HEAD"],
                "AllowedHeaders": ["*"],
                "ExposeHeaders": ["ETag", "Content-Length", "Content-Type"],
                "MaxAgeSeconds": 3600,
            }
        ]
    }

    boto3.client("s3", region_name=os.getenv("S3_REGION", "sa-east-1")).put_bucket_cors(
        Bucket=bucket,
        CORSConfiguration=config,
    )
    print(json.dumps(config, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
