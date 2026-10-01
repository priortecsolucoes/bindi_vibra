# Bindi - Vibra - imagem pra rodar via Cron Schedule no Railway.
# Selenium >= 4.6 já resolve o chromedriver certo sozinho (Selenium Manager),
# então só precisamos instalar o Google Chrome em si. Tag fixa (não "slim"
# solto) pra não pegar uma base Debian diferente/mais nova sem aviso.
FROM python:3.11-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
        wget gnupg ca-certificates fonts-liberation \
    && wget -q -O /tmp/google-chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb \
    # SEM --no-install-recommends aqui: o .deb do Chrome declara algumas
    # bibliotecas de runtime (libgbm, libnss3, libasound2 etc.) como
    # "Recommends", não "Depends" - com --no-install-recommends o apt não as
    # instala e o processo do Chrome morre na inicialização sem erro claro
    # (era a causa mais provável do "Chrome instance exited").
    && apt-get install -y /tmp/google-chrome.deb \
    && rm /tmp/google-chrome.deb \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Sem display no container - headless é obrigatório aqui (diferente do
# padrão local em .env.example, que é 0 pra acompanhar a execução).
ENV CHROME_HEADLESS=1

CMD ["python", "main.py"]
