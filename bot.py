import logging
import os
from datetime import datetime
from PIL import Image
import pytesseract # Nova importação
import re # Nova importação para Expressões Regulares

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- Configuração do Tesseract (IMPORTANTE PARA O RENDER) ---
# Diz ao pytesseract onde encontrar o executável do Tesseract no sistema do Render
pytesseract.pytesseract.tesseract_cmd = r'/usr/bin/tesseract'

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Função para o comando /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Olá! Envie uma foto com data e hora para que eu possa extrair as informações.")

# --- FUNÇÃO handle_photo ATUALIZADA COM OCR ---
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not (update.message.photo or update.message.document):
        return

    # Pega o arquivo da foto, seja enviado como foto ou documento
    if update.message.photo:
        file = await update.message.photo[-1].get_file() # Pega a maior resolução
    else:
        file = await update.message.document.get_file()

    file_path = f"temp_{file.file_id}.jpg"
    reply_text = "Não consegui encontrar uma data e hora na imagem. 😕" # Mensagem padrão

    try:
        await file.download_to_drive(file_path)
        
        # --- LÓGICA DE OCR ---
        # Extrai todo o texto da imagem, especificando o idioma português
        extracted_text = pytesseract.image_to_string(Image.open(file_path), lang='por')
        logger.info(f"Texto extraído via OCR:\n---\n{extracted_text}\n---")

        # --- LÓGICA DE REGEX PARA ENCONTRAR DATA E HORA ---
        # Regex para encontrar "DD de Mês de AAAA HH:MM:SS"
        # Ex: "14 de nov. de 2025 07:40:50"
        match = re.search(r'(\d{1,2})\s+de\s+([a-z]{3,})\.?\s+de\s+(\d{4})\s+(\d{2}:\d{2}:\d{2})', extracted_text, re.IGNORECASE)
        
        if match:
            # Se encontrou o padrão, formata a data e a hora
            day, month_str, year, time = match.groups()
            # Mapeamento de meses em português para número
            month_map = {
                'jan': 1, 'fev': 2, 'mar': 3, 'abr': 4, 'mai': 5, 'jun': 6, 
                'jul': 7, 'ago': 8, 'set': 9, 'out': 10, 'nov': 11, 'dez': 12
            }
            month = month_map.get(month_str.lower()[:3], 1) # Pega as 3 primeiras letras e busca no mapa
            
            # Cria o objeto datetime
            dt_object = datetime(int(year), month, int(day), int(time[:2]), int(time[3:5]), int(time[6:]))
            reply_text = f"Texto encontrado na imagem! 📸\nData e Hora: {dt_object.strftime('%d/%m/%Y %H:%M:%S')}"
        else:
            logger.info("Nenhum padrão de data/hora 'DD de Mês de AAAA' encontrado. Tentando outros formatos...")
            # Adicione aqui outras tentativas de regex se necessário

    except Exception as e:
        logger.error(f"Erro ao processar a imagem com OCR: {e}")
        reply_text = "Ocorreu um erro ao tentar ler o texto desta imagem."
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)
            
    await update.message.reply_text(reply_text)

def main() -> None:
    token = os.environ.get("TELEGRAM_TOKEN")
    if not token:
        logger.error("O TELEGRAM_TOKEN não foi configurado!")
        return

    application = Application.builder().token(token).build()

    application.add_handler(CommandHandler("start", start))
    # Este handler agora reage a fotos E documentos para tentar o OCR em ambos
    application.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, handle_photo))

    logger.info("Bot iniciado e escutando...")
    application.run_polling()

if __name__ == "__main__":
    main()
