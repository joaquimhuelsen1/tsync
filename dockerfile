    # Use uma imagem Python oficial como base
    FROM python:3.11-slim

    # Defina variáveis de ambiente
    ENV PYTHONDONTWRITEBYTECODE=1 # Impede o Python de criar arquivos .pyc
    ENV PYTHONUNBUFFERED=1      # Garante que os logs apareçam imediatamente

    # Crie o diretório de trabalho ANTES de qualquer cópia ou instalação
    WORKDIR /app

    # Copie apenas o requirements.txt primeiro para aproveitar o cache do Docker
    COPY requirements.txt .

    # Instale as dependências como ROOT (antes de criar/mudar para appuser)
    # Removida a flag --user, instalando globalmente
    # Adicionado --break-system-packages para compatibilidade com imagens mais recentes
    RUN pip install --no-cache-dir --break-system-packages -r requirements.txt

    # Agora crie o usuário não-root e o grupo
    RUN groupadd -r appuser && useradd -r -g appuser -d /app appuser

    # Copie o restante dos arquivos da aplicação, definindo o dono como appuser
    COPY --chown=appuser:appuser main.py .
    COPY --chown=appuser:appuser run.py .
    COPY --chown=appuser:appuser telegram_sync.py .
    COPY --chown=appuser:appuser static static/
    COPY --chown=appuser:appuser templates templates/
    # NÃO copie o diretório sessions/ ou venv/ ou logs ou .gitignore etc.

    # Defina o dono do diretório de trabalho para o appuser
    # Embora os arquivos já tenham sido copiados com chown, garante a posse do diretório em si.
    RUN chown appuser:appuser /app

    # Mude para o usuário não-root
    USER appuser

    # Exponha a porta que o Uvicorn (via run.py) usará
    EXPOSE 8080

    # Defina o comando padrão para rodar a aplicação com run.py
    # O run.py agora define a porta e o reload
    CMD ["python3", "run.py"]