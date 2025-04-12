#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Telegram Sync - Integração Telegram ↔ N8N ↔ CRM
Este script conecta sua conta do Telegram via QR Code e monitora mensagens
enviadas e recebidas, enviando-as para um webhook do N8N.
"""

import os
import json
import logging
import requests
from datetime import datetime
from telethon import TelegramClient, events
from telethon.tl.functions.users import GetFullUserRequest

# Tentar carregar variáveis de ambiente do arquivo .env
try:
    from dotenv import load_dotenv
    load_dotenv()
    print("Variáveis de ambiente carregadas do arquivo .env")
except ImportError:
    print("dotenv não encontrado. Usando apenas variáveis de ambiente do sistema.")

# Configuração de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("telegram_sync.log")
    ]
)
logger = logging.getLogger(__name__)

# Configurações do Telegram
# Você pode obter api_id e api_hash em https://my.telegram.org
API_ID = os.environ.get("TELEGRAM_API_ID")
API_HASH = os.environ.get("TELEGRAM_API_HASH")
DEFAULT_SESSION_FILE = "telegram_session"
SESSIONS_DIR = "sessions" # Definir o diretório como uma constante

# URL do Webhook N8N
WEBHOOK_URL = os.environ.get("N8N_WEBHOOK_URL", "https://backend.reconquestyourex.com/webhook/telegram-sync")

class TelegramSync:
    def __init__(self, session_name='telegram_session', api_id=None, api_hash=None):
        if not API_ID or not API_HASH:
            raise ValueError("TELEGRAM_API_ID e TELEGRAM_API_HASH devem ser definidos como variáveis de ambiente")
        
        # Usar o nome de sessão fornecido ou o padrão
        base_session_name = session_name or DEFAULT_SESSION_FILE

        # GARANTIR que o diretório de sessões existe ANTES de inicializar o cliente
        if not os.path.exists(SESSIONS_DIR):
             os.makedirs(SESSIONS_DIR)
             # Usar o logger da classe se já configurado ou o logger global
             logger.info(f"Diretório de sessões '{SESSIONS_DIR}' criado pela classe TelegramSync.")

        # Construir o caminho completo para o arquivo de sessão (sem a extensão .session)
        # O TelegramClient adiciona a extensão .session automaticamente
        self.session_path_prefix = os.path.join(SESSIONS_DIR, base_session_name)
        # Manter o nome base original pode ser útil para logs ou referências internas
        self.session_name_base = base_session_name 

        logger.info(f"Inicializando TelegramClient com prefixo de caminho de sessão: {self.session_path_prefix}")

        # Adicionando parâmetros de sistema e versão para evitar o erro UPDATE_APP_TO_LOGIN
        self.client = TelegramClient(
            self.session_path_prefix, # PASSAR O CAMINHO COMPLETO AQUI
            API_ID,
            API_HASH,
            device_model="Desktop",
            system_version="Windows 10",
            app_version="1.0.0",
            lang_code="pt-br",
            system_lang_code="pt-br"
        )
    
    def format_user_name(self, first_name, last_name):
        """Formata o nome completo do usuário tratando valores nulos"""
        first = first_name or ""
        last = last_name or ""
        return f"{first} {last}".strip()
        
    async def get_user_info(self, user_id):
        """Obtém informações do usuário pelo ID"""
        try:
            # Na versão 1.39.0 do Telethon, primeiro tentamos obter as informações do usuário diretamente
            try:
                user = await self.client.get_entity(user_id)
                return {
                    "id": user.id,
                    "first_name": getattr(user, 'first_name', ''),
                    "last_name": getattr(user, 'last_name', ''),
                    "username": getattr(user, 'username', '')
                }
            except Exception as e:
                logger.error(f"Erro ao obter entidade do usuário {user_id}: {e}")
                
                # Fallback: tentar obter informações básicas
                return {
                    "id": user_id,
                    "first_name": "",
                    "last_name": "",
                    "username": ""
                }
        except Exception as e:
            logger.error(f"Erro ao obter informações do usuário {user_id}: {e}")
            return {"id": user_id}
    
    async def send_to_webhook(self, payload):
        """Envia os dados para o webhook do N8N"""
        try:
            logger.info(f"Enviando mensagem para webhook: {json.dumps(payload, indent=2, ensure_ascii=False)}")
            response = requests.post(WEBHOOK_URL, json=payload)
            if response.status_code == 200:
                logger.info(f"Webhook enviado com sucesso: {response.text}")
            else:
                logger.error(f"Erro ao enviar webhook: {response.status_code} - {response.text}")
        except Exception as e:
            logger.error(f"Erro ao enviar para webhook: {e}")
    
    async def send_message(self, chat_id, message):
        """Envia uma mensagem para um chat específico (usuário, grupo ou canal)
        
        Args:
            chat_id: ID do chat, grupo ou canal (int ou str)
            message: Texto da mensagem a ser enviada
            
        Returns:
            O objeto de mensagem enviada
        """
        try:
            logger.info(f"Enviando mensagem para chat {chat_id}")
            
            # Converter chat_id para int se possível (IDs de chats são numéricos)
            try:
                if isinstance(chat_id, str) and chat_id.strip('-').isdigit():
                    chat_id = int(chat_id)
            except ValueError:
                pass  # Manter como string se não for um número válido
            
            # Enviar a mensagem
            sent_message = await self.client.send_message(chat_id, message)
            
            logger.info(f"Mensagem enviada com sucesso para {chat_id}")
            return sent_message
        except Exception as e:
            logger.error(f"Erro ao enviar mensagem para {chat_id}: {e}")
            raise e
    
    async def send_photo(self, chat_id, photo_url, caption=None, parse_mode=None):
        """Envia uma imagem com legenda opcional para um chat específico
        
        Args:
            chat_id: ID do chat, grupo ou canal (int ou str)
            photo_url: URL da imagem ou caminho local do arquivo
            caption: Texto da legenda (opcional)
            parse_mode: Modo de formatação do texto (HTML ou Markdown)
            
        Returns:
            O objeto de mensagem enviada
        """
        try:
            logger.info(f"Enviando imagem para chat {chat_id}")
            
            # Converter chat_id para int se possível (IDs de chats são numéricos)
            try:
                if isinstance(chat_id, str) and chat_id.strip('-').isdigit():
                    chat_id = int(chat_id)
            except ValueError:
                pass  # Manter como string se não for um número válido
            
            # Enviar a imagem
            sent_message = await self.client.send_file(
                entity=chat_id,
                file=photo_url,
                caption=caption,
                parse_mode=parse_mode
            )
            
            logger.info(f"Imagem enviada com sucesso para {chat_id}")
            return sent_message
        except Exception as e:
            logger.error(f"Erro ao enviar imagem para {chat_id}: {e}")
            raise e
    
    async def setup_handlers(self):
        """Configura os handlers para mensagens recebidas e enviadas"""
        
        # Handler para mensagens recebidas
        @self.client.on(events.NewMessage(incoming=True))
        async def handle_incoming_message(event):
            try:
                sender = await self.get_user_info(event.sender_id)
                
                payload = {
                    "user_id": str(sender["id"]),
                    "user_name": self.format_user_name(sender.get('first_name'), sender.get('last_name')),
                    "username": sender.get("username") or "",
                    "direction": "incoming",
                    "message": event.text,
                    "timestamp": datetime.now().isoformat()
                }
                
                await self.send_to_webhook(payload)
            except Exception as e:
                logger.error(f"Erro ao processar mensagem recebida: {e}")
        
        # Handler para mensagens enviadas
        @self.client.on(events.NewMessage(outgoing=True))
        async def handle_outgoing_message(event):
            try:
                # Para mensagens enviadas, o destinatário é o chat
                chat_id = event.chat_id
                user_info = await self.get_user_info(chat_id)
                
                payload = {
                    "user_id": str(chat_id),
                    "user_name": self.format_user_name(user_info.get('first_name'), user_info.get('last_name')),
                    "username": user_info.get("username") or "",
                    "direction": "outgoing",
                    "message": event.text,
                    "timestamp": datetime.now().isoformat()
                }
                
                await self.send_to_webhook(payload)
            except Exception as e:
                logger.error(f"Erro ao processar mensagem enviada: {e}")
    
    async def start(self, phone=None, code_callback=None, password_callback=None):
        """Inicia o cliente do Telegram com autenticação, usando callbacks opcionais."""
        # Definir função interna para obter a senha via callback
        def get_password_from_ui():
            if password_callback:
                # Chama a função que interage com a UI e espera a resposta
                return password_callback() 
            else:
                # Se nenhum callback for fornecido, não podemos obter a senha
                raise RuntimeError("Senha 2FA necessária, mas nenhum callback foi fornecido.")
                
        try:
            print(f"Iniciando conexão com Telegram (sessão: {self.session_name_base}): connecting")
            
            # Passar os callbacks corretos para o método start do Telethon
            # Usamos o argumento 'password' para passar nossa função wrapper.
            await self.client.start(
                phone=phone,
                code_callback=code_callback,
                # password_callback=password_callback # Argumento inválido removido
                password=get_password_from_ui if password_callback else None # Passa a função wrapper se callback existir
            )
            
            print(f"Cliente Telegram conectado (sessão: {self.session_name_base})")
            
            if await self.client.is_user_authorized():
                me = await self.client.get_me()
                print(f"Conectado como: {me.first_name} (ID: {me.id})")
                return True
            else:
                print("Falha na autorização.")
                return False
        
        except RuntimeError as e:
             # Capturar o erro específico que lançamos se o callback de senha estiver faltando
             print(f"Erro de configuração: {e}")
             logger.error(f"Erro de configuração no start: {e}")
             raise
        except Exception as e:
            print(f"Erro ao conectar: {str(e)}")
            logger.error(f"Erro ao conectar: {e}", exc_info=True)
            raise

if __name__ == "__main__":
    import asyncio
    import sys
    
    logger.info("Iniciando Telegram Sync...")
    
    # Verificar se um nome de sessão foi fornecido via linha de comando
    session_name = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SESSION_FILE
    
    telegram_sync = TelegramSync(session_name)
    
    try:
        asyncio.run(telegram_sync.start())
    except KeyboardInterrupt:
        logger.info("Telegram Sync encerrado pelo usuário")
    except Exception as e:
        logger.error(f"Erro inesperado: {e}") 