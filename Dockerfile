# Use uma imagem base oficial do Python
FROM python:3.10-slim

# Instala o Tesseract e o pacote de idioma português usando o gerenciador de pacotes padrão do Debian (apt-get)
# Este é o método mais confiável
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-por \
    && rm -rf /var/lib/apt/lists/*

# Define o diretório de trabalho dentro do container
WORKDIR /app

# Copia o arquivo de dependências do Python
COPY requirements.txt requirements.txt

# Instala as dependências do Python
RUN pip install --no-cache-dir -r requirements.txt

# Copia o resto do código do seu bot
COPY . .

# Define o comando para iniciar o bot quando o container rodar
CMD ["python", "bot.py"]
