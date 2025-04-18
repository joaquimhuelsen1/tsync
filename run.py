#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Script para iniciar o Telegram Sync Web com Uvicorn.
Certifique-se de que o ambiente virtual está ativado e
as dependências (incluindo uvicorn) estão instaladas
antes de executar este script.
"""

import uvicorn
import os
import sys

# Cores para saída no terminal (Opcional, mas mantido)
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

def print_colored(text, color):
    """Imprime texto colorido no terminal"""
    print(f"{color}{text}{Colors.ENDC}")

if __name__ == "__main__":
    print_colored("🚀 Iniciando o Telegram Sync Web...", Colors.HEADER + Colors.BOLD)

    # Configurações do Uvicorn
    port = 8080
    app_module = "main:socket_app" # Aponta para o objeto ASGI em main.py
    reload_dev = False # Definir reload como False para produção/Docker

    print_colored(f"Iniciando servidor Uvicorn em http://0.0.0.0:{port}", Colors.BLUE)
    print_colored(f"Carregando aplicação de: {app_module}", Colors.BLUE)
    if reload_dev:
        print_colored("Reload automático está ATIVADO (para desenvolvimento).", Colors.YELLOW)
    else:
        print_colored("Reload automático está DESATIVADO.", Colors.BLUE)

    # Executar Uvicorn
    uvicorn.run(
        app_module,
        host="0.0.0.0",
        port=port,
        reload=reload_dev,
        log_level="info", # Nível de log do Uvicorn
    )
