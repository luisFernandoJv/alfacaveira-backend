#!/bin/bash
# scripts/manual/test_comments.sh
#
# 🔥 AJUSTE: a versão original sempre criava a questão em nome de
# admin@focopolicial.com.br e comentava com aluno@focopolicial.com.br — ou
# seja, a notificação SEMPRE vai pro admin, nunca para a conta que você
# está usando no navegador. Isso não é bug: é o comportamento correto do
# sistema (notifica o dono da questão). O problema era só usar o script
# errado pra validar visualmente com a SUA sessão logada.
#
# Agora dá pra escolher quem é o "dono da questão" (quem recebe a
# notificação) via variável de ambiente, sem mexer no resto do script:
#
#   QUESTION_OWNER_EMAIL=voce@seudominio.com \
#   QUESTION_OWNER_PASSWORD='SuaSenha123' \
#   ./scripts/manual/test_comments.sh
#
# Se não informar nada, cai no comportamento antigo (admin/aluno de teste).

echo "========================================="
echo "🧪 TESTE SIMPLIFICADO - COMENTÁRIO"
echo "========================================="

BASE_URL="http://localhost:8000/api/v1"

OWNER_EMAIL="${QUESTION_OWNER_EMAIL:-admin@focopolicial.com.br}"
OWNER_PASSWORD="${QUESTION_OWNER_PASSWORD:-Admin@123456}"
COMMENTER_EMAIL="${COMMENTER_EMAIL:-aluno@focopolicial.com.br}"
COMMENTER_PASSWORD="${COMMENTER_PASSWORD:-Aluno@123456}"
QUESTION_OWNER_EMAIL=luizfer.12321@gmail.com
QUESTION_OWNER_PASSWORD='12345Luis..' 

# 1. Login de quem vai ser dono da questão (quem RECEBE a notificação)
echo ""
echo "🔐 1. Login do dono da questão ($OWNER_EMAIL)..."
TOKEN_OWNER=$(curl -s -X POST "$BASE_URL/auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"email\": \"$OWNER_EMAIL\", \"password\": \"$OWNER_PASSWORD\"}" \
  | jq -r '.data.access_token')

if [ "$TOKEN_OWNER" == "null" ] || [ -z "$TOKEN_OWNER" ]; then
  echo "❌ Falha ao autenticar $OWNER_EMAIL — confira email/senha."
  exit 1
fi
echo "✅ Dono da questão autenticado"

# 2. Login de quem vai comentar (quem DISPARA a notificação)
echo ""
echo "🔐 2. Login de quem vai comentar ($COMMENTER_EMAIL)..."
TOKEN_COMMENTER=$(curl -s -X POST "$BASE_URL/auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"email\": \"$COMMENTER_EMAIL\", \"password\": \"$COMMENTER_PASSWORD\"}" \
  | jq -r '.data.access_token')

if [ "$TOKEN_COMMENTER" == "null" ] || [ -z "$TOKEN_COMMENTER" ]; then
  echo "❌ Falha ao autenticar $COMMENTER_EMAIL — confira email/senha."
  exit 1
fi
echo "✅ Comentarista autenticado"

if [ "$OWNER_EMAIL" == "$COMMENTER_EMAIL" ]; then
  echo ""
  echo "⚠️  QUESTION_OWNER_EMAIL e COMMENTER_EMAIL são o mesmo usuário."
  echo "    notify_new_comment não notifica autor sobre o próprio comentário"
  echo "    (comment_author_id == question_author_id → early return)."
  echo "    Use dois usuários diferentes para ver a notificação ser criada."
  exit 1
fi

# 3. Criar uma nova questão em nome do dono
echo ""
echo "📝 3. Criando nova questão em nome de $OWNER_EMAIL..."
TIMESTAMP=$(date +%s)

QUESTION_RESPONSE=$(python3 << EOF
import requests
import json

url = "$BASE_URL/questions"
headers = {
    "Authorization": "Bearer $TOKEN_OWNER",
    "Content-Type": "application/json"
}
data = {
    "discipline_id": "59e48aa9-db48-4281-84c9-da31cdcd175d",
    "subject_id": "afc516c8-2920-42d5-afd2-8a89010181dc",
    "topic_id": "93fa7e4c-69b2-44cd-b96e-02488e5d0c8e",
    "exam_board_id": "2399faa8-84b5-434b-9b40-95e85ac80dad",
    "organization_id": "1f829c19-0444-4f27-a5b7-44d118c37396",
    "year": 2026,
    "difficulty": "facil",
    "statement": "Questão de teste para notificações - $TIMESTAMP",
    "explanation": "Esta questão foi criada para testar o sistema de notificações.",
    "alternatives": [
        {"letter": "A", "text": "Alternativa correta", "is_correct": True},
        {"letter": "B", "text": "Alternativa errada 1", "is_correct": False},
        {"letter": "C", "text": "Alternativa errada 2", "is_correct": False},
        {"letter": "D", "text": "Alternativa errada 3", "is_correct": False}
    ]
}

try:
    response = requests.post(url, headers=headers, json=data)
    print(json.dumps({
        "status": response.status_code,
        "data": response.json() if response.text else None
    }))
except Exception as e:
    print(json.dumps({"status": 500, "error": str(e)}))
EOF
)

HTTP_STATUS=$(echo "$QUESTION_RESPONSE" | python3 -c "import sys, json; data=json.load(sys.stdin); print(data.get('status', 0))")

if [ "$HTTP_STATUS" != "201" ]; then
    echo "❌ Falha ao criar questão"
    echo "$QUESTION_RESPONSE"
    exit 1
fi

QUESTION_ID=$(echo "$QUESTION_RESPONSE" | python3 -c "import sys, json; data=json.load(sys.stdin); print(data.get('data', {}).get('data', {}).get('id', ''))")
echo "✅ Nova questão criada: $QUESTION_ID"

# 4. Comentarista comenta na questão do dono
echo ""
echo "💬 4. $COMMENTER_EMAIL comentando na questão de $OWNER_EMAIL..."

COMMENT_RESPONSE=$(python3 << EOF
import requests
import json

url = "$BASE_URL/comments"
headers = {
    "Authorization": "Bearer $TOKEN_COMMENTER",
    "Content-Type": "application/json"
}
data = {
    "question_id": "$QUESTION_ID",
    "content": "Excelente questão! Criada para testar notificações. $(date +%H:%M:%S)"
}

try:
    response = requests.post(url, headers=headers, json=data)
    print(json.dumps({
        "status": response.status_code,
        "data": response.json() if response.text else None
    }))
except Exception as e:
    print(json.dumps({"status": 500, "error": str(e)}))
EOF
)

HTTP_STATUS=$(echo "$COMMENT_RESPONSE" | python3 -c "import sys, json; data=json.load(sys.stdin); print(data.get('status', 0))")

if [ "$HTTP_STATUS" != "201" ]; then
    echo "❌ Falha ao criar comentário"
    echo "$COMMENT_RESPONSE"
    exit 1
fi

COMMENT_ID=$(echo "$COMMENT_RESPONSE" | python3 -c "import sys, json; data=json.load(sys.stdin); print(data.get('data', {}).get('data', {}).get('id', ''))")
echo "✅ Comentário criado: $COMMENT_ID"

# 5. Verificar notificações do dono da questão
echo ""
echo "📋 5. Verificando notificações de $OWNER_EMAIL..."
NOTIFICATIONS=$(curl -s -X GET "$BASE_URL/notifications?limit=10" \
  -H "Authorization: Bearer $TOKEN_OWNER")

echo "$NOTIFICATIONS" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    if data.get('error'):
        print(f\"❌ Erro: {data['error']}\")
    elif data.get('data'):
        items = data['data'].get('items', [])
        total = data['data'].get('total', 0)
        unread = data['data'].get('unread_count', 0)
        print(f\"✅ Total: {total}\")
        print(f\"✅ Não lidas: {unread}\")
        if items:
            print(\"\n📨 Últimas notificações:\")
            for item in items[:3]:
                print(f\"  - {item.get('type')}: {item.get('title', '')[:50]}\")
                print(f\"    Status: {item.get('status')}\")
        else:
            print(\"⚠️ Nenhuma notificação encontrada\")
    else:
        print(f\"❌ Resposta inesperada: {data}\")
except Exception as e:
    print(f\"❌ Erro ao processar: {e}\")
"

echo ""
echo "========================================="
echo "✅ TESTE CONCLUÍDO!"
echo "   Se você quer VER isso aparecer no sino do navegador,"
echo "   faça login como $OWNER_EMAIL no app (não como outra conta)."
echo "========================================="