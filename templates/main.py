#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import asyncio
import os
# from queue import Queue, Empty # Não mais necessário
import threading # Removeremos eventualmente
import time
import glob
import json # Para rotas de API

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import socketio
from dotenv import load_dotenv

from telegram_sync import TelegramSync, logger as telegram_logger

# --- Configuração Inicial ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("telegram_web_fastapi.log")
    ]
)
logger = logging.getLogger(__name__)
logger.info("Iniciando aplicação FastAPI Telegram Sync...")

load_dotenv()
logger.info("Variáveis de ambiente carregadas.")

# --- Variáveis Globais ---
telegram_client: TelegramSync | None = None
connected: bool = False
user_info: dict = {"first_name": None, "id": None}
current_session: str | None = None
logs: list[str] = []
MAX_LOGS: int = 100
AUTO_CLEAR_LOGS: bool = True
AUTO_CLEAR_INTERVAL: int = 5 * 60 # 5 minutos
log_clear_task: asyncio.Task | None = None
auth_queue = asyncio.Queue() # Usar asyncio.Queue
telegram_client_task: asyncio.Task | None = None # Tarefa asyncio para o cliente

logger.info("Variáveis globais definidas.")

# --- Configuração FastAPI e Socket.IO ---
app = FastAPI(title="Telegram Sync Web")

# Montar arquivos estáticos (CSS, JS)
app.mount("/static", StaticFiles(directory="static"), name="static")

# Configurar templates Jinja2
templates = Jinja2Templates(directory="templates")

# Configurar Socket.IO (modo ASGI)
# O socketio.AsyncServer precisa ser criado ANTES do ASGIApp
sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')
# O ASGIApp envolve o servidor Socket.IO e o app FastAPI
socket_app = socketio.ASGIApp(sio, other_asgi_app=app)


logger.info("FastAPI e Socket.IO configurados.")

# --- Handlers de Log (Adaptado) ---
# Enviando logs para a UI via Socket.IO
async def log_to_clients(message, log_type='info'):
    global logs
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S,%f')[:-3]
    log_entry = f"{timestamp} - {log_type.upper()} - {message}"
    logs.append(log_entry)
    if len(logs) > MAX_LOGS:
        logs = logs[-MAX_LOGS:]
    try:
        # Usar sio.emit que é thread-safe/async-safe
        await sio.emit('log', {'message': log_entry, 'type': log_type})
    except Exception as e:
        # Usar print aqui, pois o logger pode causar loop infinito
        print(f"Erro crítico ao emitir log via Socket.IO: {e}")

class SocketIOAsyncHandler(logging.Handler):
    def emit(self, record):
        try:
            # Formatamos a mensagem aqui
            log_message = self.format(record)
            # Criamos uma task para enviar o log de forma assíncrona
            # Evita bloquear a thread de logging
            asyncio.create_task(log_to_clients(log_message, record.levelname.lower()))
        except Exception:
            self.handleError(record) # Deixa o logging padrão tratar o erro

# Configurar o handler de log
socket_handler = SocketIOAsyncHandler()
formatter = logging.Formatter('%(message)s') # Formatação básica, data/level adicionados em log_to_clients
socket_handler.setFormatter(formatter)
# Adicionar handler aos loggers relevantes
logger.addHandler(socket_handler)
telegram_logger.addHandler(socket_handler)
logging.getLogger('socketio').addHandler(socket_handler) # Log do socketio também
logging.getLogger('engineio').addHandler(socket_handler) # Log do engineio
logging.getLogger('uvicorn.error').addHandler(socket_handler)
logging.getLogger('uvicorn.access').addHandler(socket_handler)

logger.info("Handler de log Socket.IO configurado.")


# --- Rotas FastAPI ---

@app.get("/", response_class=HTMLResponse, summary="Renderiza a página principal")
async def read_root(request: Request):
    """Renderiza o arquivo `index.html`."""
    return templates.TemplateResponse("index.html", {"request": request})

# ... (Outras rotas serão adicionadas aqui em breve) ...


# --- Lógica do Telegram (Adaptada para asyncio) ---

# ... (Funções start_telegram_client_task, run_telegram_client, ask_code, ask_password serão adicionadas aqui) ...


# --- Handlers Socket.IO ---

@sio.event
async def connect(sid, environ):
    """Chamado quando um cliente WebSocket conecta."""
    logger.info(f"Cliente conectado: {sid}")
    # Enviar status atual ao conectar
    await sio.emit('status_update', {
        "connected": connected,
        "user_info": user_info,
        "current_session": current_session,
        "auto_clear_logs": AUTO_CLEAR_LOGS,
        "auto_clear_interval": AUTO_CLEAR_INTERVAL // 60 # Envia em minutos
    }, room=sid)
    # Enviar logs existentes
    await sio.emit('initial_logs', logs, room=sid)

@sio.event
async def disconnect(sid):
    """Chamado quando um cliente WebSocket desconecta."""
    logger.info(f"Cliente desconectado: {sid}")

# ... (Handlers para code_response, password_response serão adicionados aqui) ...


# --- Inicialização e Limpeza da Aplicação (Eventos Startup/Shutdown) ---

async def schedule_log_clearing_async():
    """Tarefa assíncrona para limpar logs periodicamente."""
    global log_clear_task # Referência à própria task para cancelamento
    while True:
        try:
            await asyncio.sleep(AUTO_CLEAR_INTERVAL)
            if AUTO_CLEAR_LOGS:
                global logs
                old_count = len(logs)
                logs = []
                log_message = f"Logs limpos automaticamente. {old_count} entradas removidas."
                logger.info(log_message)
                await sio.emit('logs_cleared', {'message': log_message})
        except asyncio.CancelledError:
            logger.info("Tarefa de limpeza de logs cancelada.")
            break
        except Exception as e:
            logger.error(f"Erro na tarefa de limpeza de logs: {e}", exc_info=True)
            # Esperar um pouco antes de tentar novamente para evitar spam de erros
            await asyncio.sleep(60)

@app.on_event("startup")
async def startup_event():
    """Executa tarefas na inicialização do servidor FastAPI."""
    logger.info("Executando tarefas de inicialização...")
    # Iniciar agendamento de limpeza de logs
    global log_clear_task
    log_clear_task = asyncio.create_task(schedule_log_clearing_async())
    logger.info("Agendador de limpeza de logs iniciado.")

@app.on_event("shutdown")
async def shutdown_event():
    """Executa tarefas no encerramento do servidor FastAPI."""
    logger.info("Executando tarefas de encerramento...")
    # Cancelar tarefa de limpeza de logs
    if log_clear_task:
        log_clear_task.cancel()
        try:
            await log_clear_task # Esperar que a tarefa termine
        except asyncio.CancelledError:
            pass # Esperado
        logger.info("Agendador de limpeza de logs finalizado.")

    # Parar cliente Telegram se estiver conectado
    # (A lógica de desconexão precisa ser adaptada e chamada aqui)
    # await disconnect_telegram_logic() # Precisaremos de uma função async para isso
    # logger.info("Tentativa de desconexão do Telegram no shutdown.")


# Nota: Para rodar, use: uvicorn main:socket_app --reload --host 0.0.0.0 --port 8080
# 'main' é o nome do arquivo (main.py), 'socket_app' é o objeto ASGIApp criado.