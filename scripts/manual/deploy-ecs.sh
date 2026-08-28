#!/usr/bin/env bash
# Deploy do Alfa Caveira (backend) para a arquitetura EC2 única + Docker Compose.
# Substitui o antigo deploy-ecs.sh (ECS/Fargate), que não serve mais depois da
# migração pra EC2 (ver migracao-ec2-status.md).
#
# Pré-requisitos: aws-cli v2 configurado (aws configure / SSO), docker buildx, jq.
# O usuário local precisa de permissão pra: ecr:GetAuthorizationToken/push,
# ssm:SendCommand, ssm:GetCommandInvocation na instância alvo.
#
# Uso:
#   chmod +x deploy-ec2.sh
#   ./deploy-ec2.sh
#
# O que o script faz, em ordem:
#   1. Build da imagem (ARM64, mesma arquitetura da t4g.micro) e push pro ECR
#   2. Envia um script remoto pra instância via SSM (send-command), que:
#      a. faz backup do docker-compose.yml atual
#      b. troca só a linha "image:" do serviço backend pro novo digest
#      c. faz login no ECR e dá pull da imagem nova
#      d. roda a migration (alembic upgrade head) via `docker-compose run --rm`
#         (esse comando herda o `environment:` do arquivo automaticamente,
#         sem precisar reconstruir env vars na mão)
#      e. se a migration falhar: restaura o docker-compose.yml original e
#         aborta — o container de produção NUNCA é recriado nesse caso
#      f. se a migration passar: `docker-compose up -d backend` (recria só o
#         container do backend com a imagem nova — downtime de poucos
#         segundos, já que é uma instância só, sem rolling deployment)
#      g. checa `/health` local pra confirmar que subiu saudável
#   3. Usa `aws ssm send-command` (não `start-session` interativo) porque
#      evita os problemas de paste multi-linha vistos na sessão de migração
#      (barras de continuação `\` quebrando dentro da sessão SSM)
#
# Diferença estrutural em relação ao deploy-ecs.sh antigo:
#   Antes (ECS): build -> push ECR -> nova revisão de task definition ->
#                migration como task avulsa -> update-service (rolling,
#                múltiplas tasks, zero downtime)
#   Agora (EC2): build -> push ECR -> troca a imagem no docker-compose.yml ->
#                migration via `docker-compose run --rm` -> recria o único
#                container do backend (downtime curto, sem rolling deployment
#                porque só existe uma instância)

set -euo pipefail

# ------------------------- CONFIGURE AQUI -------------------------
AWS_REGION="sa-east-1"
AWS_ACCOUNT_ID="240462142513"
ECR_REPO="concurso-backend"
INSTANCE_ID="i-0ce22b3597d0c02d0"        # EC2 t4g.micro, ver migracao-ec2-status.md
BACKEND_SERVICE="backend"                 # nome do serviço no docker-compose.yml
APP_DIR="/home/ssm-user/app"              # diretório do projeto na instância
PLATFORM="linux/arm64"                    # t4g.micro é ARM (Graviton)
HEALTH_URL="http://localhost/health"      # via Caddy, dentro da própria instância
SSM_TIMEOUT_SECONDS=600                   # timeout de espera do send-command
# --------------------------------------------------------------------

ECR_URI="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPO}"
IMAGE_TAG="$(git rev-parse --short HEAD 2>/dev/null || date +%Y%m%d%H%M%S)"
METADATA_FILE="$(mktemp)"

cleanup() { rm -f "$METADATA_FILE" "$REMOTE_SCRIPT_FILE" 2>/dev/null || true; }
trap cleanup EXIT

echo "==> 1/4 Login no ECR (local)"
aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin "$ECR_URI"

echo "==> 2/4 Build da imagem (${PLATFORM}) e push pro ECR"
# --metadata-file guarda o digest exato que foi pushado. Usamos o digest (não
# uma tag mutável tipo "latest") porque é assim que o projeto já referencia
# imagens no ECR hoje (ver seção 4 do migracao-ec2-status.md) — garante que o
# que testamos localmente é byte-a-byte o que sobe em produção.
docker buildx build \
  --platform "$PLATFORM" \
  -t "${ECR_URI}:${IMAGE_TAG}" \
  --push \
  --metadata-file "$METADATA_FILE" \
  .

DIGEST=$(jq -r '."containerimage.digest"' "$METADATA_FILE")
if [ -z "$DIGEST" ] || [ "$DIGEST" == "null" ]; then
  echo "❌ Não consegui capturar o digest da imagem pushada. Abortando."
  exit 1
fi
NEW_IMAGE="${ECR_URI}@${DIGEST}"
echo "Imagem nova: ${NEW_IMAGE} (tag local de referência: ${IMAGE_TAG})"

echo "==> 3/4 Montando o script remoto (roda dentro da instância via SSM)"
REMOTE_SCRIPT_FILE="$(mktemp)"
cat > "$REMOTE_SCRIPT_FILE" << REMOTE_EOF
#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR}"
BACKEND_SERVICE="${BACKEND_SERVICE}"
NEW_IMAGE="${NEW_IMAGE}"
AWS_REGION="${AWS_REGION}"
ECR_URI="${ECR_URI}"
HEALTH_URL="${HEALTH_URL}"

cd "\$APP_DIR"

BACKUP_FILE="docker-compose.yml.bak.\$(date +%Y%m%d%H%M%S)"
cp docker-compose.yml "\$BACKUP_FILE"
echo "Backup salvo em \$BACKUP_FILE"

echo "--> Login no ECR (dentro da instância)"
aws ecr get-login-password --region "\$AWS_REGION" \\
  | docker login --username AWS --password-stdin "\$ECR_URI"

echo "--> Pull da imagem nova"
docker pull "\$NEW_IMAGE"

echo "--> Atualizando a linha 'image:' do serviço '\$BACKEND_SERVICE' no docker-compose.yml"
# Só troca o "image:" dentro do bloco do serviço backend (indentação de 2
# espaços pro nome do serviço, 4 espaços pra chave "image:"), sem tocar nos
# outros serviços (postgres, redis, caddy).
awk -v svc="\$BACKEND_SERVICE" -v img="\$NEW_IMAGE" '
  BEGIN { in_svc = 0 }
  \$0 ~ "^  " svc ":\$" { in_svc = 1; print; next }
  in_svc && /^  [A-Za-z]/ { in_svc = 0 }
  in_svc && /^    image:/ { print "    image: " img; next }
  { print }
' docker-compose.yml > docker-compose.yml.new

if ! grep -q "image: \${NEW_IMAGE}" docker-compose.yml.new 2>/dev/null && ! grep -qF "\$NEW_IMAGE" docker-compose.yml.new; then
  echo "❌ Não encontrei a linha 'image:' do serviço '\$BACKEND_SERVICE' pra atualizar. Abortando sem tocar no arquivo original."
  rm -f docker-compose.yml.new
  exit 1
fi
mv docker-compose.yml.new docker-compose.yml

echo "--> Rodando a migration (alembic upgrade head) via docker-compose run --rm"
# docker-compose run herda o "environment:" já definido no arquivo pro
# serviço backend (DATABASE_URL, JWT_SECRET_KEY, etc.) — não precisa
# reconstruir variável nenhuma na mão.
if ! docker-compose run --rm "\$BACKEND_SERVICE" alembic upgrade head; then
  echo "❌ Migration falhou. Restaurando o docker-compose.yml original."
  cp "\$BACKUP_FILE" docker-compose.yml
  echo "   Container de produção NÃO foi recriado. Nada mudou em produção."
  exit 1
fi
echo "✅ Migration concluída com sucesso."

echo "--> Recriando o container do backend com a imagem nova"
docker-compose up -d "\$BACKEND_SERVICE"

echo "--> Aguardando o backend responder..."
sleep 5
if curl -sf "\$HEALTH_URL" > /dev/null; then
  echo "✅ Health check OK em \$HEALTH_URL"
else
  echo "⚠️  Health check falhou em \$HEALTH_URL — confira 'docker-compose logs backend --tail=50' na instância."
  exit 1
fi

docker-compose ps
echo "🚀 Deploy concluído na instância. Imagem em produção: \$NEW_IMAGE"
REMOTE_EOF

echo "==> 4/4 Enviando e executando o script na instância (${INSTANCE_ID}) via SSM"
ENCODED_SCRIPT=$(base64 -w0 "$REMOTE_SCRIPT_FILE" 2>/dev/null || base64 "$REMOTE_SCRIPT_FILE")

COMMAND_ID=$(aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --region "$AWS_REGION" \
  --document-name "AWS-RunShellScript" \
  --comment "deploy-ec2.sh: ${IMAGE_TAG}" \
  --parameters "commands=[\"echo '${ENCODED_SCRIPT}' | base64 -d > /tmp/deploy-remote.sh\",\"chmod +x /tmp/deploy-remote.sh\",\"/tmp/deploy-remote.sh\"]" \
  --timeout-seconds "$SSM_TIMEOUT_SECONDS" \
  --query "Command.CommandId" \
  --output text)

echo "Command ID: $COMMAND_ID — aguardando terminar..."

# Pequena espera pro comando ser registrado antes do primeiro get-command-invocation
sleep 3
aws ssm wait command-executed \
  --command-id "$COMMAND_ID" \
  --instance-id "$INSTANCE_ID" \
  --region "$AWS_REGION" || true   # "wait" retorna erro se o status final for Failed; tratamos abaixo

RESULT=$(aws ssm get-command-invocation \
  --command-id "$COMMAND_ID" \
  --instance-id "$INSTANCE_ID" \
  --region "$AWS_REGION")

STATUS=$(echo "$RESULT" | jq -r '.Status')
echo "--- STDOUT da instância ---"
echo "$RESULT" | jq -r '.StandardOutputContent'
echo "--- STDERR da instância ---"
echo "$RESULT" | jq -r '.StandardErrorContent'

if [ "$STATUS" != "Success" ]; then
  echo "❌ Deploy falhou (status SSM: $STATUS). Veja o STDOUT/STDERR acima."
  exit 1
fi

echo "🚀 Deploy concluído com sucesso. Imagem em produção: ${NEW_IMAGE}"