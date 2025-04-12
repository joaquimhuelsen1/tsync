#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import asyncio
import threading
import logging
import tkinter as tk
from tkinter import ttk, scrolledtext
import queue
from datetime import datetime
from telegram_sync import TelegramSync, logger

# Queue para comunicação entre threads
log_queue = queue.Queue()
event_queue = queue.Queue()

# Handler personalizado para redirecionar logs para a UI
class QueueHandler(logging.Handler):
    def __init__(self, log_queue):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record):
        self.log_queue.put(self.format(record))

# Classe principal da UI
class TelegramSyncUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Telegram Sync")
        self.root.geometry("800x500")
        self.root.minsize(800, 500)
        
        # Estilo
        self.style = ttk.Style()
        self.style.configure("TFrame", background="#f0f0f0")
        self.style.configure("Header.TLabel", font=("Helvetica", 14, "bold"), background="#f0f0f0")
        self.style.configure("Status.TLabel", font=("Helvetica", 12), background="#f0f0f0")
        self.style.configure("Connected.TLabel", foreground="green")
        self.style.configure("Disconnected.TLabel", foreground="red")
        
        # Variáveis de estado
        self.is_connected = tk.BooleanVar(value=False)
        self.user_info = tk.StringVar(value="Desconectado")
        self.status_text = tk.StringVar(value="Desconectado")
        
        # Instância do TelegramSync
        self.telegram_sync = None
        self.client_task = None
        self.loop = None
        
        # Criar interface
        self.create_widgets()
        
        # Configurar fila de logs
        handler = QueueHandler(log_queue)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        
        # Iniciar processamento de logs
        self.process_logs()
        
        # Manter a referência do loop de eventos
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        
    def create_widgets(self):
        # Frame principal
        main_frame = ttk.Frame(self.root, padding="10", style="TFrame")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Frame superior - informações de status
        status_frame = ttk.Frame(main_frame, style="TFrame")
        status_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(status_frame, text="Telegram Sync", style="Header.TLabel").pack(side=tk.LEFT, padx=(0, 10))
        
        # Frame de usuário e status
        user_frame = ttk.Frame(status_frame, style="TFrame")
        user_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        ttk.Label(user_frame, textvariable=self.user_info, style="Status.TLabel").pack(anchor=tk.W)
        
        self.status_label = ttk.Label(user_frame, textvariable=self.status_text, style="Disconnected.TLabel")
        self.status_label.pack(anchor=tk.W)
        
        # Frame de botões
        button_frame = ttk.Frame(status_frame, style="TFrame")
        button_frame.pack(side=tk.RIGHT)
        
        self.connect_button = ttk.Button(button_frame, text="Conectar", command=self.connect)
        self.connect_button.pack(side=tk.LEFT, padx=(0, 5))
        
        self.disconnect_button = ttk.Button(button_frame, text="Desconectar", command=self.disconnect, state=tk.DISABLED)
        self.disconnect_button.pack(side=tk.LEFT)
        
        # Frame de logs
        log_frame = ttk.LabelFrame(main_frame, text="Logs", style="TFrame")
        log_frame.pack(fill=tk.BOTH, expand=True)
        
        self.log_text = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD)
        self.log_text.pack(fill=tk.BOTH, expand=True)
        self.log_text.config(state=tk.DISABLED)
    
    def update_connection_status(self, is_connected, user_info=None):
        self.is_connected.set(is_connected)
        
        if is_connected:
            self.status_text.set("Conectado")
            self.status_label.configure(style="Connected.TLabel")
            self.connect_button.config(state=tk.DISABLED)
            self.disconnect_button.config(state=tk.NORMAL)
            if user_info:
                self.user_info.set(f"Usuário: {user_info}")
        else:
            self.status_text.set("Desconectado")
            self.status_label.configure(style="Disconnected.TLabel")
            self.user_info.set("Desconectado")
            self.connect_button.config(state=tk.NORMAL)
            self.disconnect_button.config(state=tk.DISABLED)
    
    def add_log(self, message):
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)  # Rola para o final
        self.log_text.config(state=tk.DISABLED)
    
    def process_logs(self):
        try:
            while True:
                message = log_queue.get_nowait()
                self.add_log(message)
        except queue.Empty:
            pass
        
        # Processa eventos da thread do Telegram
        try:
            while True:
                event = event_queue.get_nowait()
                if event["type"] == "connected":
                    self.update_connection_status(True, event["user_info"])
                elif event["type"] == "disconnected":
                    self.update_connection_status(False)
                elif event["type"] == "error":
                    self.add_log(f"ERRO: {event['message']}")
        except queue.Empty:
            pass
        
        self.root.after(100, self.process_logs)
    
    async def start_client(self):
        try:
            self.telegram_sync = TelegramSync()
            await self.telegram_sync.setup_handlers()
            
            await self.telegram_sync.client.start()
            
            if await self.telegram_sync.client.is_user_authorized():
                me = await self.telegram_sync.client.get_me()
                event_queue.put({
                    "type": "connected", 
                    "user_info": f"{me.first_name} (ID: {me.id})"
                })
                await self.telegram_sync.client.run_until_disconnected()
            else:
                event_queue.put({
                    "type": "error", 
                    "message": "Falha na autenticação"
                })
                event_queue.put({"type": "disconnected"})
        except Exception as e:
            event_queue.put({
                "type": "error", 
                "message": str(e)
            })
            event_queue.put({"type": "disconnected"})
        finally:
            event_queue.put({"type": "disconnected"})
    
    def connect(self):
        if self.telegram_sync is not None:
            # Já existe uma instância, limpar
            self.telegram_sync = None
        
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        
        self.client_task = self.loop.create_task(self.start_client())
        
        # Executa o loop de eventos em uma thread separada
        thread = threading.Thread(target=self.run_async_loop, daemon=True)
        thread.start()
    
    def run_async_loop(self):
        self.loop.run_forever()
    
    def disconnect(self):
        if self.telegram_sync and self.telegram_sync.client:
            async def disconnect_client():
                await self.telegram_sync.client.disconnect()
                event_queue.put({"type": "disconnected"})
            
            if self.loop:
                future = asyncio.run_coroutine_threadsafe(disconnect_client(), self.loop)
                future.result()
    
    def on_close(self):
        self.disconnect()
        self.root.destroy()
        sys.exit()

if __name__ == "__main__":
    # Configurar logging
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler("telegram_sync.log")
        ]
    )
    
    # Iniciar a interface
    root = tk.Tk()
    app = TelegramSyncUI(root)
    root.mainloop() 