# scripts/promote_admin.py
"""Promove um usuário existente a admin (`is_admin=True`).

Não cria usuário, não mexe em assinatura nem em taxonomia — só isso.
Para setup completo (admin + Pro + dados de exemplo), use
`scripts/seed_alfacaveira_admin.py`.

Uso:

    poetry run python scripts/promote_admin.py usuario@exemplo.com
"""

import asyncio
import sys

from sqlalchemy import select

from app.database.session import AsyncSessionFactory
from app.models.identity.user import User


async def promote(email: str) -> None:
    async with AsyncSessionFactory() as session:
        result = await session.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()

        if user is None:
            raise SystemExit(f"❌ Usuário '{email}' não encontrado.")

        if user.is_admin:
            print(f"ℹ️  Usuário '{email}' já é admin. Nada a fazer.")
            return

        user.is_admin = True
        await session.commit()
        print(f"✅ Usuário '{email}' promovido a admin.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Uso: poetry run python scripts/promote_admin.py <email>")
    asyncio.run(promote(sys.argv[1]))