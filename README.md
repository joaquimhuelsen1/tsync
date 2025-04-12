# Telegram Sync

Integração Telegram ↔ N8N ↔ CRM + Documentação de Conversas

## Descrição

Este projeto cria um listener que:

- Conecta sua conta pessoal do Telegram via QR Code (usando Telethon/gramjs)
- Escuta mensagens recebidas e enviadas
- Envia essas mensagens para o webhook do N8N
- O N8N processa as mensagens, consulta o CRM (como Pipedrive), registra a conversa no Google Drive e dispara automações

## Requisitos

- Python 3.8+
- Conta no Telegram
- API ID e API Hash do Telegram (obtidos em https://my.telegram.org)
- Endpoint webhook do N8N

## Instalação

1. Clone este repositório:
```bash
git clone https://github.com/seu-usuario/telegram_sync.git
cd telegram_sync
```

2. Instale as dependências:
```bash
pip install -r requirements.txt
```

3. Configure as variáveis de ambiente:
```bash
export TELEGRAM_API_ID=seu_api_id
export TELEGRAM_API_HASH=seu_api_hash
export N8N_WEBHOOK_URL=sua_url_webhook
```

Alternativamente, crie um arquivo `.env` na raiz do projeto:
```
TELEGRAM_API_ID=seu_api_id
TELEGRAM_API_HASH=seu_api_hash
N8N_WEBHOOK_URL=sua_url_webhook
```

## Uso

Execute o script principal:
```bash
python telegram_sync.py
```

Na primeira execução, será solicitado que você faça login através de um QR Code ou código enviado por SMS. Após a autenticação, um arquivo de sessão será criado e você não precisará autenticar novamente nas próximas execuções.

## Configuração no N8N

1. Crie um fluxo de trabalho no N8N com um trigger de webhook
2. Configure o webhook para receber os dados no formato:
```json
{
  "user_id": "12345678",
  "user_name": "Nome do Usuário",
  "username": "username_do_telegram",
  "direction": "incoming" or "outgoing",
  "message": "Texto da mensagem",
  "timestamp": "2023-04-01T22:00:00Z"
}
```

3. Implemente as automações necessárias para integrar com o CRM e o Google Drive

## Suporte

Para dúvidas ou problemas, abra uma issue no repositório.

## Licença

MIT 