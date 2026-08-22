#!/usr/bin/env bash
# Deploy do Alfa Caveira (backend) para ECS/Fargate.
# Pré-requisitos: aws-cli v2 configurado (aws configure / SSO), docker, jq.
#
# Uso:
#   chmod +x deploy-ecs.sh
#   ./deploy-ecs.sh
#
# Preencha as variáveis abaixo com os nomes reais do seu ambiente.
# (aws ecs list-clusters / list-services / describe-services ajudam a achar.)

set -euo pipefail

# ------------------------- CONFIGURE AQUI -------------------------
AWS_REGION="sa-east-1"
AWS_ACCOUNT_ID="240462142513"
ECR_REPO="concurso-backend"
ECS_CLUSTER="concurso-cluster"
ECS_SERVICE="concurso-backend-svc"
TASK_FAMILY="concurso-backend"          # família da task definition
CONTAINER_NAME="concurso-backend"       # nome do container dentro da task def
PLATFORM="linux/arm64"                  # task roda em ARM64 (Fargate) — build precisa bater

# Variáveis de ambiente da task definition que este script sempre reafirma,
# independente do que já estava registrado na revisão anterior. Evita que um
# valor antigo/errado (ex: nome de marca desatualizado) continue se arrastando
# de deploy em deploy. Adicione outras entradas aqui se precisar travar mais
# alguma variável.
declare -A ENFORCED_ENV_VARS=(
  [SMTP_FROM_NAME]="Alfa Caveira"
  [GOOGLE_CLIENT_ID]="344958051466-1bphge6deod8cg1ugav422tlmvmaik3e.apps.googleusercontent.com"
)
# --------------------------------------------------------------------

ECR_URI="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPO}"
IMAGE_TAG="$(git rev-parse --short HEAD 2>/dev/null || date +%Y%m%d%H%M%S)"

echo "==> 1/5 Login no ECR"
aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin "$ECR_URI"

echo "==> 2/5 Build da imagem (${PLATFORM})"
# --platform é essencial: a task roda em ARM64. buildx cuida da compilação cruzada
# mesmo se você estiver numa máquina Intel/AMD.
docker buildx build --platform "$PLATFORM" -t "${ECR_URI}:${IMAGE_TAG}" -t "${ECR_URI}:latest" --push .

echo "==> 3/5 Registrando nova revisão da task definition (imagem: ${IMAGE_TAG})"
CURRENT_TASK_DEF=$(aws ecs describe-task-definition \
  --task-definition "$TASK_FAMILY" \
  --region "$AWS_REGION")

# Monta os pares [{"name": ..., "value": ...}] a partir de ENFORCED_ENV_VARS
ENFORCED_JSON="[]"
for key in "${!ENFORCED_ENV_VARS[@]}"; do
  ENFORCED_JSON=$(echo "$ENFORCED_JSON" | jq --arg N "$key" --arg V "${ENFORCED_ENV_VARS[$key]}" '. + [{"name": $N, "value": $V}]')
done

NEW_TASK_DEF=$(echo "$CURRENT_TASK_DEF" | jq \
  --arg IMAGE "${ECR_URI}:${IMAGE_TAG}" \
  --arg NAME "$CONTAINER_NAME" \
  --argjson ENFORCED "$ENFORCED_JSON" '
  .taskDefinition |
  .containerDefinitions = (.containerDefinitions | map(
    if .name == $NAME then
      .image = $IMAGE |
      # sobrescreve/insere cada variável de ENFORCED, preservando as demais
      .environment = (
        (.environment // []) as $current |
        ($ENFORCED | map(.name)) as $enforcedNames |
        ($current | map(select(.name as $n | ($enforcedNames | index($n)) | not))) + $ENFORCED
      )
    else . end
  )) |
  del(.taskDefinitionArn, .revision, .status, .requiresAttributes, .compatibilities, .registeredAt, .registeredBy)
')

NEW_TASK_ARN=$(aws ecs register-task-definition \
  --region "$AWS_REGION" \
  --cli-input-json "$NEW_TASK_DEF" \
  | jq -r '.taskDefinition.taskDefinitionArn')

echo "Nova task definition: $NEW_TASK_ARN"

echo "==> 4/5 Rodando a migration (alembic upgrade head) como task avulsa"
# Pega network config (subnets/SG) do próprio service, pra rodar a task avulsa na mesma rede.
NETWORK_CONFIG=$(aws ecs describe-services \
  --cluster "$ECS_CLUSTER" --services "$ECS_SERVICE" --region "$AWS_REGION" \
  | jq -c '.services[0].networkConfiguration')

MIGRATION_TASK=$(aws ecs run-task \
  --cluster "$ECS_CLUSTER" \
  --task-definition "$NEW_TASK_ARN" \
  --launch-type FARGATE \
  --network-configuration "$NETWORK_CONFIG" \
  --overrides "{\"containerOverrides\":[{\"name\":\"${CONTAINER_NAME}\",\"command\":[\"alembic\",\"upgrade\",\"head\"]}]}" \
  --region "$AWS_REGION")

MIGRATION_TASK_ARN=$(echo "$MIGRATION_TASK" | jq -r '.tasks[0].taskArn')
echo "Task de migration: $MIGRATION_TASK_ARN"
echo "Aguardando a migration terminar..."

aws ecs wait tasks-stopped \
  --cluster "$ECS_CLUSTER" \
  --tasks "$MIGRATION_TASK_ARN" \
  --region "$AWS_REGION"

EXIT_CODE=$(aws ecs describe-tasks \
  --cluster "$ECS_CLUSTER" --tasks "$MIGRATION_TASK_ARN" --region "$AWS_REGION" \
  | jq -r '.tasks[0].containers[0].exitCode')

if [ "$EXIT_CODE" != "0" ]; then
  echo "❌ Migration falhou (exit code $EXIT_CODE). Abortando deploy do service."
  echo "   Veja os logs no CloudWatch (log group da task definition) antes de prosseguir."
  exit 1
fi
echo "✅ Migration concluída com sucesso."

echo "==> 5/5 Atualizando o service para a nova task definition"
aws ecs update-service \
  --cluster "$ECS_CLUSTER" \
  --service "$ECS_SERVICE" \
  --task-definition "$NEW_TASK_ARN" \
  --region "$AWS_REGION" \
  > /dev/null

echo "Aguardando o service estabilizar (rolling deployment)..."
aws ecs wait services-stable \
  --cluster "$ECS_CLUSTER" \
  --services "$ECS_SERVICE" \
  --region "$AWS_REGION"

echo "🚀 Deploy concluído. Imagem em produção: ${ECR_URI}:${IMAGE_TAG}"