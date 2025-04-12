import os
import glob
import logging
import asyncio
from datetime import datetime, timezone, timedelta
from contextlib import suppress

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import socketio
from pydantic import BaseModel, Field
from typing import Optional
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, PasswordHashInvalidError, ForbiddenError, UserIsBlockedError

# Importe sua classe TelegramSync (assumindo que está em telegram_sync.py)
try:
    from telegram_sync import TelegramSync
except ImportError:
    print("Certifique-se de que telegram_sync.py está no mesmo diretório.")
    exit(1)

# --- Configuração de Logging ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("app.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# --- Configuração FastAPI e Socket.IO ---
app = FastAPI(title="Telegram Sync Web") # <<<<< DEFINIÇÃO DO APP
sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')
socket_app = socketio.ASGIApp(sio, app) # <<<<< WRAP COM SOCKET.IO

# Montar diretórios estáticos e templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# --- Variáveis Globais de Estado ---
telegram_client: Optional[TelegramSync] = None
connected = False
user_info = {"first_name": None, "id": None}
current_session: Optional[str] = None
telegram_client_task: Optional[asyncio.Task] = None
logs = []
MAX_LOGS = 200 # Limite de logs em memória

# Configurações de Limpeza Automática de Logs
AUTO_CLEAR_LOGS = True
AUTO_CLEAR_INTERVAL = 15 * 60  # 15 minutos em segundos
log_clear_task: Optional[asyncio.Task] = None

# --- Funções Auxiliares ---
def log_and_store(message: str, level: str = "info"):
    """Adiciona log à lista global e ao logger padrão."""
    global logs
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[{timestamp}] {level.upper()}: {message}"
    
    if level == "info": logger.info(message)
    elif level == "warning": logger.warning(message)
    elif level == "error": logger.error(message)
    elif level == "debug": logger.debug(message)
    else: logger.info(message) # Default to info

    logs.append(log_entry)
    # Mantém a lista de logs dentro do limite
    logs = logs[-MAX_LOGS:]
    # Considerar emitir evento para UI aqui se necessário para logs em tempo real
    # asyncio.create_task(sio.emit('new_log', {'log': log_entry})) # Descomentar se quiser logs em tempo real

async def schedule_log_clearing_async():
    """Tarefa async que limpa os logs periodicamente."""
    global logs
    while True:
        await asyncio.sleep(AUTO_CLEAR_INTERVAL)
        if AUTO_CLEAR_LOGS and logs:
            old_count = len(logs)
            logs = []
            msg = f"Limpeza automática: {old_count} entradas de log removidas."
            logger.info(msg)
            await sio.emit('logs_cleared', {'message': msg})

# --- Eventos de Ciclo de Vida FastAPI ---
@app.on_event("startup")
async def startup_event():
    """Inicia tarefas de fundo na inicialização."""
    global log_clear_task
    logger.info("Aplicativo iniciado.")
    if AUTO_CLEAR_LOGS:
        log_clear_task = asyncio.create_task(schedule_log_clearing_async())
        logger.info(f"Agendamento de limpeza automática de logs iniciado (intervalo: {AUTO_CLEAR_INTERVAL // 60} min).")

@app.on_event("shutdown")
async def shutdown_event():
    """Executa tarefas de encerramento ao parar o servidor."""
    logger.info("Aplicativo encerrando...")
    if log_clear_task and not log_clear_task.done():
        log_clear_task.cancel()
        logger.info("Tarefa de limpeza de logs cancelada.")
    
    logger.info("Tentando desconexão do Telegram no shutdown...")
    await disconnect_telegram_logic() 
    logger.info("Desconexão do Telegram no shutdown concluída (ou não necessária).")
    
    # Esperar tarefas canceladas terminarem (com supressão de CancelledError)
    tasks_to_await = [task for task in [log_clear_task, telegram_client_task] if task and not task.done()]
    if tasks_to_await:
        logger.info(f"Aguardando {len(tasks_to_await)} tarefas pendentes finalizarem...")
        await asyncio.gather(*tasks_to_await, return_exceptions=True) # return_exceptions evita que um erro pare outros
        logger.info("Tarefas pendentes finalizadas.")
        
    logger.info("Tarefas de encerramento concluídas.")

# --- Utilidades ---
def get_available_sessions():
    """Retorna lista de arquivos de sessão do Telegram disponíveis"""
    return [f.replace(".session", "") for f in glob.glob("*.session")]

# --- Rotas FastAPI ---

@app.get("/", response_class=HTMLResponse, summary="Renderiza a página principal")
async def read_root(request: Request):
    """Renderiza o arquivo `index.html`."""
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/api/status", summary="Obtém o status atual da conexão")
async def get_status():
    """Retorna o status atual da conexão, informações do usuário e configurações."""
    return {
        "connected": connected,
        "user_info": user_info,
        "current_session": current_session,
        "auto_clear_logs": AUTO_CLEAR_LOGS,
        "auto_clear_interval": AUTO_CLEAR_INTERVAL // 60 # Retorna em minutos
    }

@app.get("/api/sessions", summary="Lista as sessões salvas")
async def get_sessions():
    """Retorna uma lista dos nomes das sessões salvas (arquivos .session)."""
    return {"sessions": get_available_sessions()}

@app.get("/api/logs", summary="Obtém os logs recentes")
async def get_logs_api():
    """Retorna a lista de logs armazenados na memória."""
    return logs

@app.post("/api/clear-logs", summary="Limpa os logs armazenados")
async def clear_logs_api():
    """Limpa a lista de logs armazenados na memória e emite evento."""
    global logs
    old_count = len(logs)
    logs = []
    log_message = f"Logs limpos manualmente via API. {old_count} entradas removidas."
    logger.info(log_message)
    await sio.emit('logs_cleared', {'message': log_message})
    return {"status": "success", "message": "Logs limpos"}

# Usar Pydantic para validação de dados nas rotas POST
from pydantic import BaseModel, Field
from typing import Optional

class AutoClearSettings(BaseModel):
    enabled: Optional[bool] = None
    interval: Optional[int] = Field(None, ge=1, le=60) # Intervalo em minutos

@app.post("/api/toggle-auto-clear", summary="Ativa/desativa ou ajusta a limpeza automática de logs")
async def toggle_auto_clear_api(settings: AutoClearSettings):
    """Ativa/desativa a limpeza automática ou ajusta o intervalo (em minutos)."""
    global AUTO_CLEAR_LOGS, AUTO_CLEAR_INTERVAL, log_clear_task
    response_message = []

    if settings.enabled is not None:
        AUTO_CLEAR_LOGS = settings.enabled
        response_message.append(f"Limpeza automática {'ativada' if AUTO_CLEAR_LOGS else 'desativada'}.")
        logger.info(f"Limpeza automática alterada para: {AUTO_CLEAR_LOGS}")
        # Reiniciar tarefa de agendamento
        if log_clear_task and not log_clear_task.done():
            log_clear_task.cancel()
        if AUTO_CLEAR_LOGS:
            log_clear_task = asyncio.create_task(schedule_log_clearing_async())
        
    if settings.interval is not None:
        AUTO_CLEAR_INTERVAL = settings.interval * 60 # Converter minutos para segundos
        response_message.append(f"Intervalo de limpeza definido para {settings.interval} minutos.")
        logger.info(f"Intervalo de limpeza automática alterado para: {settings.interval} min")
        # Reiniciar tarefa de agendamento se estiver ativa
        if AUTO_CLEAR_LOGS:
            if log_clear_task and not log_clear_task.done():
                log_clear_task.cancel()
            log_clear_task = asyncio.create_task(schedule_log_clearing_async())

    if not response_message:
         raise HTTPException(status_code=400, detail="Nenhuma configuração fornecida (enabled ou interval)")

    return {"status": "success", "message": " ".join(response_message)}

class ConnectRequest(BaseModel):
    session_name: str
    phone: Optional[str] = None

@app.post("/api/connect", summary="Inicia o processo de conexão com o Telegram")
async def connect_api(payload: ConnectRequest):
    """Recebe nome da sessão e telefone (opcional) e inicia a conexão."""
    session_file_path = f"{payload.session_name}.session"
    is_new_session = not os.path.exists(session_file_path)

    if is_new_session and not payload.phone:
        raise HTTPException(status_code=400, detail="Número de telefone é obrigatório para conectar uma nova conta.")

    logger.info(f"API: Solicitação para conectar sessão '{payload.session_name}'.")
    
    # Chama a função que inicia a tarefa async do Telegram
    success = await start_telegram_client_logic(payload.session_name, payload.phone)
    
    if success:
        return {"success": True, "message": "Processo de conexão iniciado"}
    else:
        raise HTTPException(status_code=500, detail="Falha ao iniciar a tarefa de conexão") 

@app.post("/api/disconnect", summary="Desconecta a sessão ativa do Telegram")
async def disconnect_api():
    """Inicia o processo de desconexão do cliente Telegram ativo."""
    logger.info("API: Solicitação para desconectar.")
    if not connected:
         return {"status": "error", "message": "Não conectado"} # Já desconectado
         
    # Chama a função que lida com a desconexão
    success = await disconnect_telegram_logic()
    
    if success:
        return {"status": "disconnected", "message": "Processo de desconexão iniciado/concluído"}
    else:
         raise HTTPException(status_code=500, detail="Falha ao iniciar/concluir a desconexão")

class SessionRequest(BaseModel):
    session_name: str

@app.post("/api/remove-session", summary="Remove um arquivo de sessão salvo")
async def remove_session_api(payload: SessionRequest):
    """Remove o arquivo .session especificado."""
    global current_session, connected
    session_file = f"{payload.session_name}.session"
    logger.info(f"API: Tentando remover sessão {payload.session_name}")
    
    if payload.session_name == current_session and connected:
        logger.info(f"Tentando desconectar sessão ativa {payload.session_name} antes de remover.")
        await disconnect_telegram_logic()

    if os.path.exists(session_file):
        try:
            os.remove(session_file)
            logger.info(f"Arquivo de sessão removido: {session_file}")
            await sio.emit('sessions_updated', {"sessions": get_available_sessions()}) # Notificar UI
            return {"status": "success", "message": f"Sessão {payload.session_name} removida."}
        except OSError as e:
            logger.error(f"Erro ao remover arquivo de sessão {session_file}: {e}")
            raise HTTPException(status_code=500, detail=f"Erro ao remover arquivo: {e}")
    else:
        logger.warning(f"Tentativa de remover sessão inexistente: {payload.session_name}")
        return {"status": "error", "message": "Sessão não encontrada"}

@app.get("/api/chats", summary="Obtém a lista de chats recentes")
async def get_chats_api():
    """Retorna a lista de chats com mensagens nos últimos 7 dias."""
    if not connected or not telegram_client:
        raise HTTPException(status_code=400, detail="Cliente não conectado")

    # Chama a lógica async para buscar chats
    try:
        chats, reconquest_map_id = await get_chats_logic()
        return {
            "status": "success",
            "chats": chats,
            "reconquest_map_id": reconquest_map_id
        }
    except Exception as e:
         logger.error(f"Erro na API /api/chats: {e}", exc_info=True)
         raise HTTPException(status_code=500, detail=f"Erro ao buscar chats: {e}")

class SendMessageRequest(BaseModel):
    chat_id: str | int
    message: str

@app.post("/api/send-message", summary="Envia uma mensagem para um chat")
async def send_message_api(payload: SendMessageRequest):
    """Envia uma mensagem de texto para o chat_id especificado."""
    if not connected or not telegram_client:
         raise HTTPException(status_code=400, detail="Cliente não conectado")
         
    # Chama a lógica async para enviar mensagem
    try:
        message_id = await send_message_logic(payload.chat_id, payload.message)
        return {
            "status": "success",
            "message": "Mensagem enviada com sucesso",
            "message_id": message_id
        }
    except Exception as e:
        # send_message_logic já levanta HTTPException em caso de erro
        # Mas podemos capturar outros erros inesperados aqui
        logger.error(f"Erro inesperado na API /api/send-message: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erro inesperado ao enviar mensagem: {e}")

# Novo modelo para a requisição de envio de foto
class SendPhotoRequest(BaseModel):
    chat_id: str | int
    photo: str  # Espera-se uma URL aqui
    caption: Optional[str] = None
    parse_mode: Optional[str] = None # 'markdown' or 'html'

# --- Lógica do Telegram (Adaptada para asyncio) ---

# Fila para comunicação entre callbacks e handlers socketio
auth_queue = asyncio.Queue()

async def ask_telegram_code():
    """Callback async chamado pelo Telethon quando o código é necessário."""
    try:
        logger.info("[Callback] Pedindo código...")
        await sio.emit('ask_code')
        logger.info("[Callback] Evento 'ask_code' emitido. Aguardando fila...")
        code = await asyncio.wait_for(auth_queue.get(), timeout=300.0) 
        auth_queue.task_done() 
        logger.info(f"[Callback] Código recebido da fila: {code}")
        return code
    except asyncio.TimeoutError:
        logger.error("[Callback] Timeout esperando pelo código do usuário.")
        raise TimeoutError("Timeout esperando pelo código do usuário.")
    except Exception as e:
        logger.error(f"[Callback] Erro no ask_telegram_code: {e}", exc_info=True)
        raise 

async def ask_telegram_password():
    """Callback async chamado pelo Telethon quando a senha 2FA é necessária."""
    try:
        logger.info("[Callback] Pedindo senha 2FA...")
        await sio.emit('ask_password')
        logger.info("[Callback] Evento 'ask_password' emitido. Aguardando fila...")
        password = await asyncio.wait_for(auth_queue.get(), timeout=300.0)
        auth_queue.task_done()
        logger.info("[Callback] Senha recebida da fila.") 
        return password
    except asyncio.TimeoutError:
        logger.error("[Callback] Timeout esperando pela senha 2FA do usuário.")
        raise TimeoutError("Timeout esperando pela senha 2FA do usuário.")
    except Exception as e:
        logger.error(f"[Callback] Erro no ask_telegram_password: {e}", exc_info=True)
        raise

async def run_telegram_client(session_name: str, phone: str | None):
    """Corrotina principal que gerencia a conexão e ciclo de vida do cliente Telegram."""
    global telegram_client, connected, user_info, current_session, telegram_client_task
    
    while not auth_queue.empty():
        try: auth_queue.get_nowait(); auth_queue.task_done()
        except asyncio.QueueEmpty: break
    logger.info(f"[TG Task] Fila de autenticação limpa para {session_name}.")

    temp_client = None
    session_file_path = f"{session_name}.session"
    session_exists = os.path.exists(session_file_path)
        
    try:
        logger.info(f"[TG Task] Iniciando para sessão: {session_name}. Existe: {session_exists}. ...")
        temp_client = TelegramSync(session_name=session_name)
        
        phone_to_use_in_start = phone 
        
        if session_exists:
            logger.info(f"[TG Task] Tentando validar sessão existente {session_name} com client.connect()...")
            connected_initially = False
            try:
                connected_initially = await temp_client.client.connect()
                if not connected_initially:
                    logger.warning(f"[TG Task] client.connect() para sessão existente {session_name} retornou False. Sessão inválida.")
                    if os.path.exists(session_file_path):
                       try: os.remove(session_file_path); logger.info(f"[TG Task] Arquivo de sessão inválido removido: {session_file_path}")
                       except OSError as remove_err: logger.error(f"[TG Task] Erro ao remover {session_file_path}: {remove_err}")
                    raise ConnectionError("Sessão existente inválida")
                else:
                    logger.info(f"[TG Task] client.connect() para {session_name} bem-sucedido.")
                    phone_to_use_in_start = None 
            except Exception as connect_err:
                logger.error(f"[TG Task] Erro durante client.connect() para sessão existente {session_name}: {connect_err}", exc_info=True)
                if os.path.exists(session_file_path):
                       try: os.remove(session_file_path); logger.info(f"[TG Task] Arquivo de sessão inválido removido após erro connect(): {session_file_path}")
                       except OSError as remove_err: logger.error(f"[TG Task] Erro ao remover {session_file_path}: {remove_err}")
                raise ConnectionError(f"Erro ao validar sessão existente: {connect_err}")

        await temp_client.setup_handlers()
        
        logger.info(f"[TG Task] Chamando temp_client.start (Telefone: {'Sim' if phone_to_use_in_start else 'Não'})...")
        await temp_client.start(
            phone=phone_to_use_in_start, 
            code_callback=ask_telegram_code, 
            password_callback=ask_telegram_password 
        )
        logger.info("[TG Task] temp_client.start finalizado.")
        
        if await temp_client.client.is_user_authorized():
            me = await temp_client.client.get_me()
            telegram_client = temp_client
            user_info = {"first_name": me.first_name, "id": me.id}
            connected = True
            current_session = session_name
            logger.info(f"[TG Task] Conectado como {me.first_name} (ID: {me.id})")
            await sio.emit('status_update', {
                "connected": True,
                "user_info": user_info,
                "session": current_session
            })
            logger.info("[TG Task] Cliente conectado. Aguardando desconexão...")
            await telegram_client.client.run_until_disconnected()
            logger.info(f"[TG Task] Cliente {session_name} foi desconectado.")
        else:
            logger.warning(f"[TG Task] Falha na autorização final para a sessão {session_name}.")
            if os.path.exists(session_file_path):
                try: os.remove(session_file_path); logger.info(f"[TG Task] Arquivo de sessão removido após falha final: {session_file_path}")
                except OSError as remove_err: logger.error(f"[TG Task] Erro ao remover {session_file_path}: {remove_err}")
            raise ConnectionRefusedError("Falha na autorização final")
            
    except (TimeoutError, ConnectionError, ConnectionRefusedError) as auth_err:
        logger.error(f"[TG Task] Erro de conexão/autenticação para {session_name}: {auth_err}")
        await sio.emit('status_update', {"connected": False, "error": str(auth_err), "session": session_name })
    except Exception as e:
        logger.error(f"[TG Task] Erro inesperado na tarefa do cliente {session_name}: {e}", exc_info=True)
        await sio.emit('status_update', {"connected": False, "error": f"Erro inesperado: {e}", "session": session_name })
    finally:
        logger.info(f"[TG Task] Tarefa run_telegram_client para {session_name} finalizando.")
        if current_session == session_name:
             logger.info(f"[TG Task] Limpando estado global para {session_name}.")
             connected = False
             telegram_client = None
             current_session = None
             user_info = {"first_name": None, "id": None}
             telegram_client_task = None
             await sio.emit('status_update', {"connected": False, "user_info": None, "session": None})

async def start_telegram_client_logic(session_name: str, phone: str | None) -> bool:
    """Inicia a tarefa de fundo para conectar ao Telegram."""
    global telegram_client_task, connected
    
    if telegram_client_task and not telegram_client_task.done():
        logger.info("Cancelando tarefa anterior do cliente Telegram...")
        telegram_client_task.cancel()
        try: await telegram_client_task 
        except asyncio.CancelledError: logger.info("Tarefa anterior cancelada com sucesso.")
        except Exception as e: logger.error(f"Erro ao aguardar cancelamento da tarefa anterior: {e}")
        if connected: # Forçar reset se a tarefa foi cancelada enquanto conectada
            connected = False; telegram_client = None; current_session = None; user_info = {"first_name": None, "id": None}; telegram_client_task = None
            await sio.emit('status_update', {"connected": False, "user_info": None, "session": None})
            
    logger.info(f"Criando nova tarefa asyncio para run_telegram_client ({session_name})")
    telegram_client_task = asyncio.create_task(run_telegram_client(session_name, phone))
    return True 

async def disconnect_telegram_logic() -> bool:
    """Cancela a tarefa do cliente Telegram e aguarda."""
    global telegram_client_task, connected, telegram_client, current_session, user_info # Acessa globais para limpar
    
    if telegram_client_task and not telegram_client_task.done():
        logger.info("Iniciando processo de desconexão lógica (cancelando task)...")
        # Tentar desconectar o cliente primeiro (melhor esforço)
        if telegram_client and telegram_client.client.is_connected():
            try:
                await telegram_client.client.disconnect()
                logger.info("Cliente Telegram desconectado via API antes de cancelar task.")
            except Exception as e:
                logger.warning(f"Erro ao desconectar cliente antes de cancelar task: {e}")
                
        telegram_client_task.cancel()
        try:
            await telegram_client_task
            logger.info("Tarefa do cliente Telegram finalizada após cancelamento.")
            # O finally dentro de run_telegram_client deve limpar o estado
            return True
        except asyncio.CancelledError:
            logger.info("Tarefa do cliente Telegram cancelada com sucesso (esperado).")
             # O finally dentro de run_telegram_client DEVE ser chamado aqui também
            if current_session: # Limpar estado se cancelamento foi rápido
                connected = False; telegram_client = None; current_session = None; user_info = {"first_name": None, "id": None}; telegram_client_task = None
                await sio.emit('status_update', {"connected": False, "user_info": None, "session": None})
            return True 
        except Exception as e:
             logger.error(f"Erro ao aguardar cancelamento da tarefa Telegram: {e}")
             # Forçar reset do estado mesmo com erro no cancelamento
             if connected:
                connected = False; telegram_client = None; current_session = None; user_info = {"first_name": None, "id": None}; telegram_client_task = None
                await sio.emit('status_update', {"connected": False, "user_info": None, "session": None})
             return False
    else:
        logger.warning("Tentativa de desconectar, mas nenhuma tarefa ativa encontrada.")
        if connected: # Garantir que o estado global esteja correto
            connected = False; telegram_client = None; current_session = None; user_info = {"first_name": None, "id": None}; telegram_client_task = None
            await sio.emit('status_update', {"connected": False, "user_info": None, "session": None})
        return True 

async def get_chats_logic():
     """Lógica async para buscar chats recentes."""
     if not telegram_client:
         raise HTTPException(status_code=500, detail="Cliente Telegram não inicializado")
     try:
         chats = []
         reconquest_map_id = None
         seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
         async for dialog in telegram_client.client.iter_dialogs():
             if dialog.date < seven_days_ago: continue
             entity = dialog.entity
             chat_info = { "id": entity.id, "name": dialog.name or "(Nome Indisponível)", "type": entity.__class__.__name__ }
             if hasattr(entity, 'username') and entity.username: chat_info["username"] = entity.username
             if hasattr(entity, 'first_name') and entity.first_name: chat_info["first_name"] = entity.first_name
             if hasattr(entity, 'last_name') and entity.last_name:
                 chat_info["last_name"] = entity.last_name
                 if chat_info["type"] == 'User': chat_info["name"] = f"{entity.first_name or ''} {entity.last_name or ''}".strip()
             if dialog.name and "TheReconquestMap" in dialog.name: reconquest_map_id = entity.id
             chats.append(chat_info)
         logger.info(f"[Lógica Chats] Encontrados {len(chats)} diálogos recentes.")
         return chats, reconquest_map_id
     except Exception as e:
         logger.error(f"Erro na lógica get_chats_logic: {e}", exc_info=True)
         raise HTTPException(status_code=500, detail=f"Erro interno ao buscar chats: {e}")

async def send_message_logic(chat_id: str | int, message: str) -> int | None:
    """Lógica async para enviar mensagem."""
    if not telegram_client:
        raise HTTPException(status_code=500, detail="Cliente Telegram não inicializado")
    try:
        # Tentar converter chat_id para int
        try:
            parsed_chat_id = int(chat_id)
        except ValueError:
             parsed_chat_id = chat_id # Manter como string se não for número
             
        logger.info(f"[Lógica Envio] Enviando para {parsed_chat_id}...")
        sent_message = await telegram_client.send_message(parsed_chat_id, message)
        logger.info(f"[Lógica Envio] Mensagem enviada. ID: {getattr(sent_message, 'id', None)}")
        return getattr(sent_message, 'id', None)
    except Exception as e:
        logger.error(f"Erro ao enviar mensagem (lógica async): {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erro ao enviar mensagem: {e}")

async def send_photo_logic(chat_id: str | int, photo_url: str, caption: Optional[str], parse_mode_str: Optional[str]) -> Optional[int]:
    """Lógica async para enviar foto com legenda."""
    if not telegram_client or not telegram_client.client.is_connected():
         logger.warning("send_photo_logic chamado sem cliente conectado.")
         raise HTTPException(status_code=400, detail="Cliente não conectado")

    # Validar e usar parse_mode string diretamente
    valid_parse_modes = ['markdown', 'html']
    pm_to_use = None
    if parse_mode_str and parse_mode_str.lower() in valid_parse_modes:
        pm_to_use = parse_mode_str.lower() # Usar a string diretamente
    elif parse_mode_str:
         logger.warning(f"send_photo_logic: parse_mode '{parse_mode_str}' inválido. Enviando sem formatação especial.")
         # Não definir pm_to_use

    # Tentar converter chat_id para int se parecer numérico
    entity_id_to_use: str | int = chat_id
    try:
        # Tenta converter se for uma string que representa um número (positivo ou negativo)
        if isinstance(chat_id, str) and chat_id.strip().lstrip('-').isdigit():
             entity_id_to_use = int(chat_id)
    except ValueError:
        logger.warning(f"Não foi possível converter chat_id '{chat_id}' para int. Usando como string.")
        # Mantém como string se a conversão falhar (ex: é um username)

    try:
        # Tentar obter a entidade de destino usando o ID processado
        try:
             # Use a variável entity_id_to_use aqui!
             target_entity = await telegram_client.client.get_entity(entity_id_to_use)
             logger.info(f"[Lógica Envio Foto] Enviando para entidade: {target_entity.id} (Tipo: {type(target_entity).__name__})")
        except ValueError as e:
             # Logar o ID que foi tentado (string ou int)
             logger.error(f"[Lógica Envio Foto] Não foi possível encontrar a entidade para chat_id '{entity_id_to_use}' (tipo: {type(entity_id_to_use).__name__}): {e}")
             raise HTTPException(status_code=404, detail=f"Chat ID '{chat_id}' não encontrado ou inválido.")
        except TypeError as e: # Capturar erro se get_entity não gostar do tipo mesmo assim
             logger.error(f"[Lógica Envio Foto] Erro de tipo ao chamar get_entity com '{entity_id_to_use}' (tipo: {type(entity_id_to_use).__name__}): {e}")
             raise HTTPException(status_code=400, detail=f"Tipo de Chat ID '{chat_id}' inválido para get_entity.")
        except Exception as e_entity:
             logger.error(f"[Lógica Envio Foto] Erro ao obter entidade para chat_id '{entity_id_to_use}': {e_entity}", exc_info=True)
             raise HTTPException(status_code=500, detail=f"Erro ao verificar Chat ID '{chat_id}': {e_entity}")

        # Enviar a foto usando a URL e a entidade validada
        # Telethon baixa a URL automaticamente
        logger.info(f"[Lógica Envio Foto] Tentando enviar arquivo da URL: {photo_url} com parse_mode: {pm_to_use}")
        sent_message = await telegram_client.client.send_file(
            target_entity,
            file=photo_url,
            caption=caption or '', # Usar string vazia se caption for None
            parse_mode=pm_to_use # Passar a string ('markdown', 'html') ou None
        )

        message_id = getattr(sent_message, 'id', None)
        if message_id:
             logger.info(f"[Lógica Envio Foto] Foto enviada para {target_entity.id}. ID da Mensagem: {message_id}")
        else:
             logger.warning(f"[Lógica Envio Foto] Foto enviada para {target_entity.id}, mas não foi possível obter o ID da mensagem.")
        return message_id

    except ForbiddenError as e:
         logger.error(f"[Lógica Envio Foto] Erro de permissão ao enviar para {chat_id}: {e}", exc_info=True)
         raise HTTPException(status_code=403, detail=f"Permissão negada para enviar foto para '{chat_id}': {e}")
    except UserIsBlockedError:
         logger.error(f"[Lógica Envio Foto] Erro: Você foi bloqueado pelo usuário {chat_id}.", exc_info=True)
         raise HTTPException(status_code=403, detail=f"Você foi bloqueado pelo usuário '{chat_id}'.")
    except Exception as e: # Capturar outros erros (download da URL, envio, etc.)
        logger.error(f"[Lógica Envio Foto] Erro inesperado ao enviar foto para {chat_id} da URL {photo_url}: {e}", exc_info=True)
        error_msg = str(e)
        # Tentar dar mensagens mais úteis para erros comuns
        if "Could not download file from URL" in error_msg:
             raise HTTPException(status_code=400, detail=f"Erro ao baixar imagem da URL fornecida: {photo_url}")
        if "Entity not found" in error_msg: # Pode acontecer se get_entity falhar de outra forma
             raise HTTPException(status_code=404, detail=f"Chat ID '{chat_id}' não encontrado.")
        if hasattr(e, 'message'): error_msg = e.message # Usar mensagem específica se disponível
        raise HTTPException(status_code=500, detail=f"Erro ao enviar foto: {error_msg}")

# --- Rotas FastAPI ---

@app.post("/api/send-photo", summary="Envia uma foto (via URL) com legenda para um chat")
async def send_photo_api(payload: SendPhotoRequest):
    """Recebe chat_id, URL da foto, legenda e parse_mode, e envia via Telegram."""
    logger.info(f"API: Recebida solicitação para /api/send-photo para chat {payload.chat_id}")
    if not connected or not telegram_client:
         raise HTTPException(status_code=400, detail="Cliente não conectado")

    try:
        message_id = await send_photo_logic(
            chat_id=payload.chat_id,
            photo_url=payload.photo,
            caption=payload.caption,
            parse_mode_str=payload.parse_mode
        )
        return {
            "status": "success",
            "message": "Foto enviada com sucesso",
            "message_id": message_id
        }
    except HTTPException as http_exc:
         # A lógica já logou o erro e levantou HTTPException, apenas re-levante
         raise http_exc
    except Exception as e:
        # Captura qualquer outro erro inesperado que não veio da lógica
        logger.error(f"Erro inesperado na API /api/send-photo: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erro inesperado no servidor ao enviar foto: {getattr(e, 'message', str(e))}")

# --- Handlers Socket.IO ---

# ... (connect, disconnect como antes) ...

@sio.event
async def code_response(sid, data):
    code = data.get('code')
    if code:
        logger.info(f"Código recebido de {sid}: {'*' * len(code)}")
        await auth_queue.put(code)
    else:
        logger.warning(f"Recebido code_response sem código de {sid}")

@sio.event
async def password_response(sid, data):
    password = data.get('password')
    if password:
        logger.info(f"Senha recebida de {sid}.")
        await auth_queue.put(password)
    else:
        logger.warning(f"Recebido password_response sem senha de {sid}")

# ... (startup/shutdown events) ...

# Nota: Para rodar, use: uvicorn main:socket_app --reload --host 0.0.0.0 --port 8080 