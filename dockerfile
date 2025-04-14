    # Use uma imagem Python oficial como base
    FROM python:3.11-slim

    # Defina variáveis de ambiente
    ENV PYTHONDONTWRITEBYTECODE 1 # Impede o Python de criar arquivos .pyc
    ENV PYTHONUNBUFFERED 1      # Garante que os logs apareçam imediatamente

    # Crie um usuário não-root e um grupo
    RUN groupadd -r appuser && useradd -r -g appuser appuser

    # Crie o diretório de trabalho e defina permissões
    WORKDIR /app
    # Não precisamos mais chown aqui, pois copiaremos com --chown

    # Mude para o usuário não-root
    USER appuser

    # Instale dependências primeiro para aproveitar o cache do Docker
    # Copie apenas o requirements.txt
    COPY --chown=appuser:appuser requirements.txt .
    # Usar --user para instalar no diretório home do usuário não-root
    # Adicionar --break-system-packages se necessário em bases slim mais recentes
    RUN pip install --no-cache-dir --user -r requirements.txt 

    # Copie apenas os arquivos necessários da aplicação
    # Garanta que as permissões estão corretas com --chown
    COPY --chown=appuser:appuser main.py .
    COPY --chown=appuser:appuser run.py .
    COPY --chown=appuser:appuser telegram_sync.py .
    COPY --chown=appuser:appuser static static/
    COPY --chown=appuser:appuser templates templates/
    # NÃO copie o diretório sessions/ ou venv/ ou logs ou .gitignore etc.

    # Exponha a porta que o Uvicorn (via run.py) usará
    EXPOSE 8080

    # Defina o comando padrão para rodar a aplicação com run.py
    # O run.py agora define a porta e o reload 
    # Adicionar o diretório local de binários do usuário ao PATH
    ENV PATH="/home/appuser/.local/bin:${PATH}"

    # Recomenda-se editar run.py para ter reload=False para produção Docker
    CMD ["python", "run.py"]