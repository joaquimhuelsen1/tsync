#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import eventlet
eventlet.monkey_patch()

import os
import json
import logging
import asyncio
import threading
import time
import glob
import subprocess
import re
from datetime import datetime, timedelta, timezone
from queue import Queue, Empty
from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO
from dotenv import load_dotenv
from telegram_sync import TelegramSync, logger as telegram_logger

# Log inicial
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("telegram_web.log")
    ]
)
logger = logging.getLogger(__name__)
logger.info("Iniciando importações...")

# Carregar variáveis de ambiente
logger.info("Carregando variáveis de ambiente...")
load_dotenv()
logger.info("Variáveis de ambiente carregadas.")

# Configuração de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("telegram_web.log")
    ]
)
logger = logging.getLogger(__name__)

# Inicializar Flask e SocketIO
logger.info("Inicializando Flask...")
app = Flask(__name__)
app.config['SECRET_KEY'] = 'telegram-sync-secret'
logger.info("Flask inicializado.")
logger.info("Inicializando SocketIO...")
socketio = SocketIO(app, cors_allowed_origins="*")
logger.info("SocketIO inicializado.")

# Variáveis globais
logger.info("Definindo variáveis globais...")
telegram_client = None
connected = False
user_info = {"first_name": None, "id": None}
current_session = None
logs = []
MAX_LOGS = 100
AUTO_CLEAR_LOGS = True
AUTO_CLEAR_INTERVAL = 5 * 60  # 5 minutos em segundos
log_clear_timer = None
loop = None # Loop de eventos asyncio da thread dedicada
telegram_thread = None # Referência à thread dedicada
auth_queue = Queue() # Fila para comunicação callbacks <-> socketio handlers
logger.info("Variáveis globais definidas.")

# Classe para capturar logs e enviá-los via WebSocket
logger.info("Definindo SocketIOHandler...")
class SocketIOHandler(logging.Handler):
    def emit(self, record):
        global logs
        try:
            log_entry = self.format(record)
            logs.append(log_entry)
            
            # Limitar o número de logs armazenados
            if len(logs) > MAX_LOGS:
                logs = logs[-MAX_LOGS:]
                
            # Enviar log para clientes conectados
            socketio.emit('log', {
                'message': log_entry,
                'type': record.levelname.lower(),
                'timestamp': datetime.now().isoformat()
            })
        except Exception as e:
            print(f"Erro ao enviar log: {e}")

logger.info("SocketIOHandler definido.")

# Adicionar handler personalizado
logger.info("Configurando handlers de log...")
socket_handler = SocketIOHandler()
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
socket_handler.setFormatter(formatter)
logger.addHandler(socket_handler)

# Adicionar o handler ao logger do telegram_sync também
telegram_logger.addHandler(socket_handler)
logger.info("Handlers de log configurados.")

# Função para obter sessões disponíveis
logger.info("Definindo get_available_sessions...")
def get_available_sessions():
    """Retorna lista de arquivos de sessão do Telegram disponíveis"""
    sessions = []
    
    # Buscar arquivos .session
    for session_file in glob.glob("*.session"):
        session_name = session_file.replace(".session", "")
        sessions.append(session_name)
    
    return sessions
logger.info("get_available_sessions definida.")

# Função para limpar logs periodicamente
logger.info("Definindo clear_logs_task...")
def clear_logs_task():
    global logs, log_clear_timer
    
    if AUTO_CLEAR_LOGS:
        # Limpar logs
        old_count = len(logs)
        logs = []
        
        # Registrar ação de limpeza
        log_message = f"Logs limpos automaticamente. {old_count} entradas removidas."
        logger.info(log_message)
        
        # Notificar clientes de que os logs foram limpos
        socketio.emit('logs_cleared', {
            'message': log_message,
            'timestamp': datetime.now().isoformat()
        })
        
        # Agendar próxima limpeza
        schedule_log_clearing()
logger.info("clear_logs_task definida.")

# Função para agendar a limpeza de logs
logger.info("Definindo schedule_log_clearing...")
def schedule_log_clearing():
    global log_clear_timer
    
    # Cancelar timer existente se houver
    if log_clear_timer:
        log_clear_timer.cancel()
    
    # Criar novo timer apenas se a limpeza automática estiver ativada
    if AUTO_CLEAR_LOGS:
        log_clear_timer = threading.Timer(AUTO_CLEAR_INTERVAL, clear_logs_task)
        log_clear_timer.daemon = True
        log_clear_timer.start()
logger.info("schedule_log_clearing definida.")

# Rotas da aplicação web
logger.info("Definindo rotas Flask...")
@app.route('/')
def index():
    return render_template('index.html')

# API endpoints
@app.route('/api/status')
def status():
    global connected, user_info, AUTO_CLEAR_LOGS, current_session
    return jsonify({
        "connected": connected,
        "user_info": user_info,
        "current_session": current_session,
        "auto_clear_logs": AUTO_CLEAR_LOGS,
        "auto_clear_interval": AUTO_CLEAR_INTERVAL,
    })

@app.route('/api/sessions')
def sessions():
    """Retorna as sessões disponíveis"""
    global current_session
    available_sessions = get_available_sessions()
    return jsonify({
        "sessions": available_sessions,
        "current_session": current_session
    })

@app.route('/api/logs')
def get_logs():
    global logs
    return jsonify(logs)

@app.route('/api/clear-logs', methods=['POST'])
def clear_logs():
    global logs
    logs = []
    logger.info("Logs limpos manualmente")
    return jsonify({"status": "success", "message": "Logs limpos com sucesso"})

@app.route('/api/toggle-auto-clear', methods=['POST'])
def toggle_auto_clear():
    global AUTO_CLEAR_LOGS
    
    data = request.json
    if 'enabled' in data:
        AUTO_CLEAR_LOGS = data['enabled']
        
        # Se ativado, agendar próxima limpeza
        if AUTO_CLEAR_LOGS:
            schedule_log_clearing()
            logger.info("Limpeza automática de logs ativada")
        else:
            # Cancelar timer existente
            if log_clear_timer:
                log_clear_timer.cancel()
            logger.info("Limpeza automática de logs desativada")
    
    if 'interval' in data and isinstance(data['interval'], int) and data['interval'] >= 1:
        global AUTO_CLEAR_INTERVAL
        AUTO_CLEAR_INTERVAL = data['interval'] * 60  # Converter minutos para segundos
        logger.info(f"Intervalo de limpeza automática definido para {data['interval']} minutos")
        
        # Reagendar com novo intervalo se a limpeza automática estiver ativada
        if AUTO_CLEAR_LOGS:
            schedule_log_clearing()
    
    return jsonify({
        "status": "success", 
        "auto_clear_logs": AUTO_CLEAR_LOGS,
        "auto_clear_interval": AUTO_CLEAR_INTERVAL // 60  # Converter segundos para minutos
    })

@app.route('/api/connect', methods=['POST'])
def connect():
    """Inicia a conexão com o Telegram ou reconecta com uma sessão existente"""
    data = request.json
    session_name = data.get('session_name')
    phone_from_request = data.get('phone') # Telefone vindo da requisição
    
    if not session_name:
        return jsonify({"success": False, "message": "Nome da sessão não fornecido"})
    
    session_file_path = f"{session_name}.session"
    is_new_session = not os.path.exists(session_file_path)
    
    # Determinar o telefone a ser usado
    phone_to_use = None
    if is_new_session:
        if not phone_from_request: # Nova sessão SEM telefone
            logger.warning(f"Tentativa de conectar nova sessão '{session_name}' sem número de telefone.")
            return jsonify({
                "success": False, 
                "message": "Número de telefone é obrigatório para conectar uma nova conta."
            })
        else: # Nova sessão COM telefone
            phone_to_use = phone_from_request
    # else: # Sessão existente, phone_to_use permanece None (força usar o arquivo .session)
    
    logger.info(f"Solicitação para conectar sessão '{session_name}'. Telefone a usar: {'Sim' if phone_to_use else 'Não'}. É nova sessão: {is_new_session}.")
    
    # Em vez de chamar start_background_task, chama a função que cria a thread
    success = start_telegram_thread(session_name, phone_to_use) 
    
    if success:
        return jsonify({"success": True, "message": "Processo de conexão iniciado"})
    else:
        return jsonify({"success": False, "message": "Falha ao iniciar a tarefa de conexão"})

@app.route('/api/disconnect', methods=['POST'])
def disconnect_route():
    global connected, telegram_client, current_session, user_info, loop, telegram_thread

    if not connected or not telegram_client:
        return jsonify({"status": "error", "message": "Não conectado"})

    # Função async interna para desconectar
    async def stop_client_async():
        global telegram_client # Apenas acessa
        logger.info("[_async_stop] Iniciando desconexão...")
        if telegram_client and telegram_client.client.is_connected():
            await telegram_client.client.disconnect()
        logger.info("[_async_stop] client.disconnect() chamado.")
        # O reset do estado global será feito após parar o loop/thread
        return True

    try:
        if loop and loop.is_running():
            logger.info("Enviando stop_client_async para o loop da thread...")
            future = asyncio.run_coroutine_threadsafe(stop_client_async(), loop)
            future.result(timeout=10) # Espera desconexão
            logger.info("Cliente desconectado (lógica async concluída).")
            
            # AGORA, parar o loop da thread e esperar a thread terminar
            logger.info("Solicitando parada do loop da thread...")
            loop.call_soon_threadsafe(loop.stop)
            if telegram_thread and telegram_thread.is_alive():
                logger.info("Aguardando thread do Telegram terminar...")
                telegram_thread.join(timeout=5)
                if telegram_thread.is_alive():
                     logger.warning("Thread do Telegram não terminou após timeout.")
                else:
                     logger.info("Thread do Telegram finalizada.")
            
            # Resetar estado global APÓS parar a thread
            connected = False
            telegram_client = None
            current_session = None
            user_info = {"first_name": None, "id": None}
            loop = None
            telegram_thread = None
            socketio.emit('status_update', {"connected": False, "user_info": None, "session": None})
            logger.info("Estado global resetado após parada da thread.")
            
            return jsonify({"status": "disconnected", "message": "Desconectado com sucesso"})
        else:
            logger.warning("Loop/Thread do cliente não encontrado ou não rodando para desconectar.")
            # Forçar reset do estado global 
            connected = False; telegram_client = None; current_session = None; user_info = {"first_name": None, "id": None}; loop = None; telegram_thread = None
            socketio.emit('status_update', {"connected": False, "user_info": None, "session": None})
            return jsonify({"status": "error", "message": "Loop/Thread indisponível, estado resetado"})

    except Exception as e:
        logger.error(f"Erro durante o processo de desconexão: {e}", exc_info=True)
        # Forçar reset do estado global
        connected = False; telegram_client = None; current_session = None; user_info = {"first_name": None, "id": None}; loop = None; telegram_thread = None
        socketio.emit('status_update', {"connected": False, "user_info": None, "session": None})
        return jsonify({"status": "error", "message": f"Erro ao desconectar: {e}"})

@app.route('/api/remove-session', methods=['POST'])
def remove_session():
    """Remove um arquivo de sessão do Telegram"""
    global connected, current_session, telegram_client
    
    # Verificar se está conectado e desconectar primeiro se necessário
    if connected and telegram_client:
        disconnect_route() # Chama a função de desconexão
    
    data = request.json or {}
    session_name = data.get('session_name')
    
    if not session_name:
        return jsonify({"status": "error", "message": "Nome da sessão não especificado"})
    
    session_file = f"{session_name}.session"
    
    try:
        if os.path.exists(session_file):
            os.remove(session_file)
            logger.info(f"Sessão removida: {session_name}")
            
            # Resetar sessão atual se for a mesma
            if current_session == session_name:
                current_session = None
            
            return jsonify({"status": "success", "message": f"Sessão {session_name} removida com sucesso"})
        else:
            return jsonify({"status": "error", "message": f"Sessão {session_name} não encontrada"})
    except Exception as e:
        logger.error(f"Erro ao remover sessão {session_name}: {e}")
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/send-message', methods=['POST'])
def send_message():
    global telegram_client, connected, loop
    
    # Verificar se está conectado
    if not connected or not telegram_client:
        return jsonify({
            "status": "error", 
            "message": "Não conectado ao Telegram. Conecte-se primeiro."
        })
    
    # Obter dados da requisição
    data = request.json or {}
    message = data.get('message')
    chat_id = data.get('chat_id')
    
    # Validar dados
    if not message:
        return jsonify({"status": "error", "message": "Mensagem não especificada"})
    
    if not chat_id:
        return jsonify({"status": "error", "message": "ID do chat/grupo não especificado"})
    
    async def _async_send():
        return await telegram_client.send_message(chat_id, message)

    try:
        if loop and loop.is_running() and telegram_client:
            future = asyncio.run_coroutine_threadsafe(_async_send(), loop)
            result = future.result(timeout=30)
            logger.info(f"Mensagem enviada para {chat_id}. ID: {getattr(result, 'id', None)}")
            return jsonify({
                "status": "success", 
                "message": "Mensagem enviada com sucesso",
                "message_id": getattr(result, 'id', None)
            })
        else:
            logger.error("Não foi possível enviar mensagem: loop ou cliente indisponível.")
            return jsonify({"status": "error", "message": "Cliente ou loop indisponível"})
            
    except Exception as e:
        logger.error(f"Erro ao enviar mensagem via run_coroutine_threadsafe: {e}", exc_info=True)
        return jsonify({"status": "error", "message": f"Erro ao enviar mensagem: {str(e)}"})

@app.route('/api/chats', methods=['GET'])
def get_chats():
    global telegram_client, connected, loop
    
    if not connected or not telegram_client:
        return jsonify({"status": "error", "message": "Não conectado"})
    
    try:
        if loop and loop.is_running() and telegram_client:
            async def get_recent_chats_async():
                global telegram_client # Acessa global
                chats = []
                reconquest_map_id = None
                seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
                logger.info(f"[_async_get_chats] Buscando diálogos desde {seven_days_ago.isoformat()}")
                async for dialog in telegram_client.client.iter_dialogs():
                    if dialog.date < seven_days_ago: continue
                    entity = dialog.entity
                    chat_info = {
                        "id": entity.id,
                        "name": dialog.name or "(Nome Indisponível)",
                        "type": entity.__class__.__name__ # 'User', 'Chat', 'Channel'
                    }
                    
                    # Adicionar informações específicas do tipo
                    if hasattr(entity, 'username') and entity.username:
                        chat_info["username"] = entity.username
                    if hasattr(entity, 'first_name') and entity.first_name:
                        chat_info["first_name"] = entity.first_name
                    if hasattr(entity, 'last_name') and entity.last_name:
                        chat_info["last_name"] = entity.last_name
                        # Formatar nome completo para usuários
                        if chat_info["type"] == 'User':
                             chat_info["name"] = f"{entity.first_name or ''} {entity.last_name or ''}".strip()
                    
                    # Verificar se é o grupo alvo pelo nome
                    if dialog.name and "TheReconquestMap" in dialog.name:
                        reconquest_map_id = entity.id
                        logger.info(f"Encontrado ID do grupo TheReconquestMap: {reconquest_map_id}")
                    
                    chats.append(chat_info)
                logger.info(f"[_async_get_chats] Encontrados {len(chats)} diálogos recentes.")
                return chats, reconquest_map_id
            
            logger.info("Enviando get_recent_chats_async para o loop do cliente...")
            future = asyncio.run_coroutine_threadsafe(get_recent_chats_async(), loop)
            chats, reconquest_map_id = future.result(timeout=60)
            logger.info("Busca de chats via run_coroutine_threadsafe concluída.")
            return jsonify({
                "status": "success",
                "chats": chats,
                "reconquest_map_id": reconquest_map_id
            })
        else:
             logger.error("Não foi possível buscar chats: loop ou cliente indisponível.")
             return jsonify({"status": "error", "message": "Cliente ou loop indisponível"})
             
    except Exception as e:
        logger.error(f"Erro ao buscar chats via run_coroutine_threadsafe: {e}", exc_info=True)
        return jsonify({"status": "error", "message": f"Erro ao obter chats: {str(e)}"})

@app.route('/api/webhook/send', methods=['POST'])
def webhook_send():
    """Endpoint para sistemas externos enviarem mensagens via webhook
    
    Formato esperado da requisição:
    {
        "message": "Texto da mensagem",
        "chat_id": "ID do chat/grupo/canal",
        "api_key": "chave opcional para autenticação"
    }
    """
    global telegram_client, connected
    
    # Verificar se está conectado
    if not connected or not telegram_client:
        return jsonify({
            "status": "error", 
            "message": "Não conectado ao Telegram. Conecte-se primeiro."
        })
    
    # Obter dados da requisição
    try:
        data = request.json
        if not data:
            return jsonify({"status": "error", "message": "JSON inválido ou ausente"}), 400
    except Exception:
        return jsonify({"status": "error", "message": "Erro ao processar JSON da requisição"}), 400
    
    # Autenticação (opcional, pode ser configurada posteriormente)
    api_key = os.environ.get("WEBHOOK_API_KEY")
    if api_key and data.get('api_key') != api_key:
        return jsonify({"status": "error", "message": "Chave de API inválida"}), 401
    
    # Validar dados
    message = data.get('message')
    chat_id = data.get('chat_id')
    
    if not message:
        return jsonify({"status": "error", "message": "Parâmetro 'message' é obrigatório"}), 400
    
    if not chat_id:
        return jsonify({"status": "error", "message": "Parâmetro 'chat_id' é obrigatório"}), 400
    
    try:
        # Executar envio da mensagem de forma assíncrona
        # Verificamos se o cliente existe antes de tentar rodar
        if telegram_client:
            # Função async interna
            async def _async_send():
                 return await telegram_client.send_message(chat_id, message)
            
            # Executar com asyncio.run()
            result = asyncio.run(_async_send())

            logger.info(f"[Webhook] Mensagem enviada para {chat_id}: {message[:50]}...")
            return jsonify({
                "status": "success", 
                "message": "Mensagem enviada com sucesso",
                "message_id": getattr(result, 'id', None)
            })
        else:
            return jsonify({
                "status": "error", 
                "message": "Cliente Telegram não disponível"
            }), 500
    except Exception as e:
        error_msg = str(e)
        logger.error(f"[Webhook] Erro ao enviar mensagem: {error_msg}")
        return jsonify({
            "status": "error", 
            "message": f"Erro ao enviar mensagem: {error_msg}"
        }), 500

@app.route('/api/webhook/send_photo', methods=['POST'])
def webhook_send_photo():
    """Endpoint para sistemas externos enviarem imagens via webhook
    
    Formato esperado da requisição:
    {
        "chat_id": "@seu_grupo_ou_id",
        "photo": "URL_DA_IMAGEM",
        "caption": "Texto da legenda",
        "parse_mode": "Markdown"
    }
    """
    global telegram_client, connected
    
    # Verificar se está conectado
    if not connected or not telegram_client:
        return jsonify({
            "status": "error", 
            "message": "Não conectado ao Telegram. Conecte-se primeiro."
        })
    
    # Obter dados da requisição
    try:
        data = request.json
        if not data:
            return jsonify({"status": "error", "message": "JSON inválido ou ausente"}), 400
    except Exception:
        return jsonify({"status": "error", "message": "Erro ao processar JSON da requisição"}), 400
    
    # Autenticação (opcional, pode ser configurada posteriormente)
    api_key = os.environ.get("WEBHOOK_API_KEY")
    if api_key and data.get('api_key') != api_key:
        return jsonify({"status": "error", "message": "Chave de API inválida"}), 401
    
    # Validar dados
    photo = data.get('photo')
    chat_id = data.get('chat_id')
    caption = data.get('caption')
    parse_mode = data.get('parse_mode')
    
    if not photo:
        return jsonify({"status": "error", "message": "Parâmetro 'photo' é obrigatório"}), 400
    
    if not chat_id:
        return jsonify({"status": "error", "message": "Parâmetro 'chat_id' é obrigatório"}), 400
    
    try:
        # Executar envio da imagem de forma assíncrona
        # Verificamos se o cliente existe antes de tentar rodar
        if telegram_client:
            # Função async interna
            async def _async_send():
                 return await telegram_client.send_photo(
                    chat_id=chat_id, 
                    photo_url=photo, 
                    caption=caption, 
                    parse_mode=parse_mode
                )
            
            # Executar com asyncio.run()
            result = asyncio.run(_async_send())

            logger.info(f"[Webhook] Imagem enviada para {chat_id}")
            return jsonify({
                "status": "success", 
                "message": "Imagem enviada com sucesso",
                "message_id": getattr(result, 'id', None)
            })
        else:
            return jsonify({
                "status": "error", 
                "message": "Cliente Telegram não disponível"
            }), 500
    except Exception as e:
        error_msg = str(e)
        logger.error(f"[Webhook] Erro ao enviar imagem: {error_msg}")
        return jsonify({
            "status": "error", 
            "message": f"Erro ao enviar imagem: {error_msg}"
        }), 500

# Funções para gerenciar o cliente Telegram
logger.info("Definindo funções de gerenciamento do cliente Telegram...")
def start_telegram_thread(session_name, phone=None):
    global telegram_thread, loop
    
    # Parar thread anterior se existir
    if telegram_thread and telegram_thread.is_alive():
        logger.info("Parando thread anterior do Telegram...")
        if loop and loop.is_running():
             # Tentar desconectar graciosamente antes
             disconnect_route()
        else: # Se o loop já não existe, apenas tenta matar a thread (menos ideal)
             logger.warning("Tentando finalizar thread anterior sem loop ativo.")
             # Não há método seguro para matar thread, join é a melhor opção
             telegram_thread.join(timeout=1) 

    # Limpar loop antigo
    loop = None
    
    logger.info(f"Iniciando NOVA thread para a sessão: {session_name}")
    telegram_thread = threading.Thread(
        target=run_telegram_client_thread, 
        args=(session_name, phone),
        daemon=True # Permite que o programa saia mesmo se a thread estiver rodando
    )
    telegram_thread.start()
    return True

# Função alvo da thread (SÍNCRONA no contexto da thread, mas gerencia loop asyncio)
def run_telegram_client_thread(session_name, phone=None):
    global telegram_client, connected, user_info, current_session, loop # Definir loop global aqui
    
    # Configurar o loop asyncio para ESTA thread
    local_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(local_loop)
    loop = local_loop # Armazena na variável global para as rotas usarem
    
    logger.info(f"[Thread-{threading.current_thread().name}] Loop asyncio criado e definido: {loop}")

    # Função interna async para conter a lógica
    async def _async_run_telegram_client(s_name, p_num):
        global telegram_client, connected, user_info, current_session # Modifica globais
        temp_client = None
        session_file_path = f"{s_name}.session"
        session_exists = os.path.exists(session_file_path)
        
        try:
            logger.info(f"[Thread-{threading.current_thread().name}] Iniciando para sessão: {s_name}. Existe: {session_exists}. Telefone fornecido: {'Sim' if p_num else 'Não'}")
            temp_client = TelegramSync(session_name=s_name)
            
            phone_to_use_in_start = p_num 
            
            if session_exists:
                # Sessão EXISTENTE: tentar conectar para validar
                logger.info(f"[Thread-{threading.current_thread().name}] Tentando validar sessão existente {s_name} com client.connect()...")
                connected_initially = False
                try:
                    connected_initially = await temp_client.client.connect()
                    if not connected_initially:
                        logger.warning(f"[Thread-{threading.current_thread().name}] client.connect() para sessão existente {s_name} retornou False. Sessão inválida.")
                        if os.path.exists(session_file_path):
                           try: os.remove(session_file_path); logger.info(f"[Thread-{threading.current_thread().name}] Arquivo de sessão inválido removido: {session_file_path}")
                           except OSError as remove_err: logger.error(f"[Thread-{threading.current_thread().name}] Erro ao remover {session_file_path}: {remove_err}")
                        return False # Falha
                    else:
                        logger.info(f"[Thread-{threading.current_thread().name}] client.connect() para {s_name} bem-sucedido.")
                        phone_to_use_in_start = None # Não precisa de telefone se connect() funcionou
                except Exception as connect_err:
                    logger.error(f"[Thread-{threading.current_thread().name}] Erro durante client.connect() para sessão existente {s_name}: {connect_err}", exc_info=True)
                    if os.path.exists(session_file_path):
                           try: os.remove(session_file_path); logger.info(f"[Thread-{threading.current_thread().name}] Arquivo de sessão inválido removido após erro connect(): {session_file_path}")
                           except OSError as remove_err: logger.error(f"[Thread-{threading.current_thread().name}] Erro ao remover {session_file_path}: {remove_err}")
                    return False # Falha
            # else: # Nova sessão, não tenta connect() primeiro
            
            # Configurar handlers ANTES de start()
            await temp_client.setup_handlers()
            
            logger.info(f"[Thread-{threading.current_thread().name}] Chamando temp_client.start (Telefone: {'Sim' if phone_to_use_in_start else 'Não'})...")
            await temp_client.start(
                phone=phone_to_use_in_start, 
                code_callback=ask_telegram_code, 
                password_callback=ask_telegram_password 
            )
            logger.info("[Thread-{threading.current_thread().name}] temp_client.start finalizado.")
            
            # Verificar autorização
            if await temp_client.client.is_user_authorized():
                me = await temp_client.client.get_me()
                telegram_client = temp_client
                user_info = {"first_name": me.first_name, "id": me.id}
                connected = True
                current_session = s_name
                
                # ARMAZENAR O LOOP ATIVO NESTA TAREFA
                loop = asyncio.get_running_loop() 
                logger.info(f"[_async_run] Conectado como {me.first_name}. Loop armazenado: {loop}")

                socketio.emit('status_update', {
                    "connected": True,
                    "user_info": user_info,
                    "session": current_session
                })
                
                # Manter a tarefa rodando para o cliente continuar ativo
                # O cliente Telethon gerencia a espera por eventos internamente.
                # Podemos apenas esperar indefinidamente ou até ser desconectado.
                logger.info("Cliente conectado e autorizado. Tarefa de fundo continuará rodando.")
                await telegram_client.client.run_until_disconnected() # Espera aqui até desconectar
                logger.info(f"Cliente {s_name} foi desconectado.")

            else:
                logger.warning(f"[_async_run] Falha na autorização final para a sessão {s_name} (após start).")
                # Remover sessão se falhou na autorização (pode ter criado arquivo antes de pedir 2FA)
                if os.path.exists(session_file_path):
                    try: os.remove(session_file_path); logger.info(f"[_async_run] Arquivo de sessão removido após falha final: {session_file_path}")
                    except OSError as remove_err: logger.error(f"[_async_run] Erro ao remover {session_file_path}: {remove_err}")
                return False
                
        except TimeoutError as te:
             logger.error(f"[_async_run] Timeout durante a autenticação ({s_name}): {te}")
             if temp_client and hasattr(temp_client, 'client') and temp_client.client.is_connected():
                try: await temp_client.client.disconnect(); logger.info("[_async_run] Cliente temporário desconectado após timeout.")
                except Exception as disconn_err: logger.error(f"[_async_run] Erro ao desconectar cliente temp após timeout: {disconn_err}")
             return False # Indica falha
        except Exception as e:
            logger.error(f"[_async_run] Erro fatal durante a conexão ({s_name}): {str(e)}", exc_info=True)
            if temp_client and hasattr(temp_client, 'client') and temp_client.client.is_connected():
                try: await temp_client.client.disconnect(); logger.info("[_async_run] Cliente temporário desconectado após erro.")
                except Exception as disconn_err: logger.error(f"[_async_run] Erro ao desconectar cliente temp após erro: {disconn_err}")
            return False # Indica falha
        finally:
            # Limpeza ao final da tarefa (seja sucesso, erro ou desconexão)
            logger.info(f"Tarefa de fundo run_telegram_client para {s_name} finalizando.")
            if current_session == s_name: # Se a sessão que terminou era a ativa
                 logger.info(f"Limpando estado global para {s_name}.")
                 connected = False
                 telegram_client = None
                 current_session = None
                 user_info = {"first_name": None, "id": None}
                 loop = None # Limpar referência ao loop
                 socketio.emit('status_update', {"connected": False, "user_info": None, "session": None})

    # --- Corpo da função da Thread --- 
    try:
        # Limpar a fila
        while not auth_queue.empty(): 
             try: auth_queue.get_nowait(); 
             except Empty: break
        logger.info(f"[Thread-{threading.current_thread().name}] Fila limpa. Executando _async_run...")
        
        # Executar a lógica principal de conexão
        success = loop.run_until_complete(_async_run_telegram_client(session_name, phone))
        
        logger.info(f"[Thread-{threading.current_thread().name}] _async_run finalizado. Sucesso: {success}")
        
        if success:
            # Se conectou com sucesso, manter o loop rodando para o cliente
            logger.info(f"[Thread-{threading.current_thread().name}] Conexão bem sucedida. Rodando loop para sempre...")
            loop.run_forever() # Mantém a thread ativa e o loop rodando
            # loop.stop() será chamado pela disconnect_route
            logger.info(f"[Thread-{threading.current_thread().name}] Loop foi parado externamente.")
        else:
            # Se a conexão falhou, não precisa rodar loop. Emitir erro.
            logger.warning(f"[Thread-{threading.current_thread().name}] Conexão falhou. Não iniciando loop.run_forever().")
            socketio.emit('status_update', {
                "connected": False,
                "error": "Falha na conexão ou autenticação inicial.",
                "session": session_name 
            })

    except Exception as e:
        logger.error(f"[Thread-{threading.current_thread().name}] Erro inesperado na thread: {str(e)}", exc_info=True)
        # Emitir erro se a thread falhar catastroficamente
        socketio.emit('status_update', {
            "connected": False,
            "error": f"Erro interno na thread: {str(e)}",
            "session": session_name
        })
    finally:
        # Limpeza quando o loop termina (seja por stop() ou erro)
        logger.info(f"[Thread-{threading.current_thread().name}] Loop finalizado. Fechando loop.")
        loop.close()
        logger.info(f"[Thread-{threading.current_thread().name}] Loop fechado. Thread encerrando.")
        # Resetar estado global se esta era a sessão ativa (redundante se disconnect foi chamado)
        if current_session == session_name:
             connected = False
             telegram_client = None
             current_session = None
             user_info = {"first_name": None, "id": None}
             loop = None # Garante que loop global seja None
             telegram_thread = None
             # Não emitir status aqui, pois disconnect já deve ter emitido

# --- Funções Callback para Telethon (Chamadas DENTRO da thread asyncio) ---

def ask_telegram_code(): 
    # Usa auth_queue.get(block=True) - bloqueia a thread dedicada, OK.
    try:
        logger.info("[Callback] Pedindo código...")
        socketio.emit('ask_code') # Emitir para a UI (thread-safe)
        code = auth_queue.get(block=True, timeout=300) 
        logger.info("[Callback] Código recebido.")
        return code
    except Empty:
        logger.error("[Callback] Timeout código.")
        raise TimeoutError("Timeout código")
    except Exception as e:
        logger.error(f"[Callback] Erro código: {e}")
        raise

def ask_telegram_password():
    # Usa auth_queue.get(block=True)
    try:
        logger.info("[Callback] Pedindo senha...")
        socketio.emit('ask_password')
        password = auth_queue.get(block=True, timeout=300) 
        logger.info("[Callback] Senha recebida.")
        return password
    except Empty:
        logger.error("[Callback] Timeout senha.")
        raise TimeoutError("Timeout senha")
    except Exception as e:
        logger.error(f"[Callback] Erro senha: {e}")
        raise

# --- Handlers Socket.IO para Respostas (Executam no contexto Flask/Eventlet) ---
# Colocam a resposta na fila para a thread dedicada consumir
@socketio.on('code_response')
def handle_code_response(data):
    # ... (código como antes, auth_queue.put(code)) ...
    code = data.get('code')
    if code:
        logger.info(f"Código recebido do frontend via SocketIO: {code}")
        auth_queue.put(code)
    else:
        logger.warning("Recebido evento 'code_response' sem código.")
        # Opcional: colocar um valor de erro na fila para desbloquear o callback
        # auth_queue.put(None)

@socketio.on('password_response')
def handle_password_response(data):
    # ... (código como antes, auth_queue.put(password)) ...
    password = data.get('password')
    if password:
        logger.info("Senha recebida do frontend via SocketIO.")
        auth_queue.put(password)
    else:
        logger.warning("Recebido evento 'password_response' sem senha.")
        # auth_queue.put(None)

# Código de inicialização da aplicação
if __name__ == '__main__':
    logger.info("Aplicação iniciando (__name__ == '__main__')...")

    # Verificar se as variáveis de ambiente necessárias estão definidas
    if not os.environ.get("TELEGRAM_API_ID") or not os.environ.get("TELEGRAM_API_HASH"):
        logger.error("Variáveis de ambiente TELEGRAM_API_ID ou TELEGRAM_API_HASH não definidas.")
        print("Erro: Variáveis de ambiente TELEGRAM_API_ID ou TELEGRAM_API_HASH não definidas.")
        exit(1)

    # Iniciar temporizador para limpeza de logs
    logger.info("Agendando limpeza de logs...")
    schedule_log_clearing()
    logger.info("Limpeza de logs agendada.")

    # Apenas log para indicar que o script foi carregado se executado diretamente
    logger.info("Script app.py carregado. Use Gunicorn para iniciar o servidor.") 