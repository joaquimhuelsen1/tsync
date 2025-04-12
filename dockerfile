    # Use uma imagem Python oficial como base
    FROM python:3.11-slim

    # Defina variáveis de ambiente
    ENV PYTHONDONTWRITEBYTECODE 1 # Impede o Python de criar arquivos .pyc
    ENV PYTHONUNBUFFERED 1      # Garante que os logs apareçam imediatamente
    ENV PORT 8080                 # Porta padrão que a aplicação usará internamente

    # Crie e defina o diretório de trabalho
    WORKDIR /app

    # Crie uma virtual environment
    RUN python3 -m venv /app/venv
    ENV PATH="/app/venv/bin:$PATH"

    # Instale dependências primeiro para aproveitar o cache do Docker
    COPY requirements.txt .
    RUN pip install --no-cache-dir -r requirements.txt

    # Copie o restante do código da aplicação para o diretório de trabalho
    COPY . .

    # Exponha a porta que o Gunicorn usará
    EXPOSE 8080

    # Defina o comando padrão para rodar a aplicação com Gunicorn e Eventlet
    # Este comando será executado quando o container iniciar
    CMD ["gunicorn", "--worker-class", "eventlet", "-w", "1", "--bind", "0.0.0.0:8080", "app:app"]