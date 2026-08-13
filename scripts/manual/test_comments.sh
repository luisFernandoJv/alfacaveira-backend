#!/bin/bash

echo "========================================="
echo "🧪 TESTE - MÓDULO DE CADERNOS (NOTEBOOKS)"
echo "========================================="

BASE_URL="http://localhost:8000/api/v1"

# 1. Login e captura do token
echo ""
echo "🔐 1. Login..."
RESPONSE=$(curl -s -X POST "$BASE_URL/auth/login" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "admin@focopolicial.com.br",
    "password": "Admin@123456"
  }')

TOKEN=$(echo "$RESPONSE" | jq -r '.data.access_token')

if [ "$TOKEN" == "null" ] || [ -z "$TOKEN" ]; then
  echo "❌ Falha no login"
  echo "$RESPONSE" | jq .
  exit 1
fi

echo "✅ Login realizado"
echo "Token: ${TOKEN:0:50}..."

# 2. Testar token com /users/me
echo ""
echo "🔍 2. Validando token..."
curl -s -X GET "$BASE_URL/users/me" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" | jq '.data | {id, email, full_name}'

# 3. Criar pasta
echo ""
echo "📁 3. Criando pasta..."
FOLDER_RESPONSE=$(curl -s -X POST "$BASE_URL/notebooks/folders" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "PRF 2026"}')

FOLDER_ID=$(echo "$FOLDER_RESPONSE" | jq -r '.data.id')

if [ "$FOLDER_ID" == "null" ] || [ -z "$FOLDER_ID" ]; then
  echo "❌ Falha ao criar pasta"
  echo "$FOLDER_RESPONSE" | jq .
  exit 1
fi

echo "✅ Pasta criada: $FOLDER_ID"

# 4. Listar pastas
echo ""
echo "📋 4. Listando pastas..."
curl -s -X GET "$BASE_URL/notebooks/folders" \
  -H "Authorization: Bearer $TOKEN" | jq '.data[] | {id, name}'

# 5. Criar tag
echo ""
echo "🏷️ 5. Criando tag..."
TAG_RESPONSE=$(curl -s -X POST "$BASE_URL/notebooks/tags" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "Reta Final"}')

TAG_ID=$(echo "$TAG_RESPONSE" | jq -r '.data.id')
echo "✅ Tag criada: $TAG_ID"

# 6. Criar caderno
echo ""
echo "📓 6. Criando caderno..."
NOTEBOOK_RESPONSE=$(curl -s -X POST "$BASE_URL/notebooks" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Direito Constitucional - PRF",
    "description": "Questões de Direito Constitucional para PRF",
    "folder_id": "'$FOLDER_ID'",
    "tag_ids": ["'$TAG_ID'"]
  }')

NOTEBOOK_ID=$(echo "$NOTEBOOK_RESPONSE" | jq -r '.data.id')
echo "✅ Caderno criado: $NOTEBOOK_ID"

# 7. Listar cadernos
echo ""
echo "📋 7. Listando cadernos..."
curl -s -X GET "$BASE_URL/notebooks" \
  -H "Authorization: Bearer $TOKEN" | jq '.data.items[] | {id, name, question_count}'

# 8. Buscar questão
echo ""
echo "❓ 8. Buscando questão..."
QUESTION_RESPONSE=$(curl -s -X GET "$BASE_URL/questions?limit=1" \
  -H "Authorization: Bearer $TOKEN")

QUESTION_ID=$(echo "$QUESTION_RESPONSE" | jq -r '.data[0].id')
echo "✅ Questão encontrada: $QUESTION_ID"

# 9. Adicionar questão ao caderno
echo ""
echo "➕ 9. Adicionando questão ao caderno..."
ADD_RESPONSE=$(curl -s -X POST "$BASE_URL/notebooks/$NOTEBOOK_ID/questions" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "question_id": "'$QUESTION_ID'",
    "note": "Revisar antes da prova - questão sobre direitos fundamentais"
  }')

echo "✅ Resposta: $(echo "$ADD_RESPONSE" | jq -c '.data | {id, question_id, note}')"

# 10. Verificar caderno com questão
echo ""
echo "🔍 10. Verificando caderno..."
curl -s -X GET "$BASE_URL/notebooks/$NOTEBOOK_ID" \
  -H "Authorization: Bearer $TOKEN" \
  | jq '.data | {id, name, question_count, questions: .questions | length}'

# 11. Remover questão
echo ""
echo "🗑️ 11. Removendo questão do caderno..."
curl -s -X DELETE "$BASE_URL/notebooks/$NOTEBOOK_ID/questions/$QUESTION_ID" \
  -H "Authorization: Bearer $TOKEN"
echo "✅ Questão removida"

# 12. Deletar caderno
echo ""
echo "🧹 12. Deletando caderno..."
curl -s -X DELETE "$BASE_URL/notebooks/$NOTEBOOK_ID" \
  -H "Authorization: Bearer $TOKEN"
echo "✅ Caderno deletado"

echo ""
echo "========================================="
echo "✅ TESTE CONCLUÍDO COM SUCESSO!"
echo "========================================="