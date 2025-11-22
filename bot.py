import logging
import os
from datetime import datetime
from PIL import Image
import pytesseract
import re

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Configuração do Tesseract (agora usando o caminho padrão do Dockerfile)
pytesseract.pytesseract.tesseract_cmd = r'/usr/bin/tesseract'

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- NOVA FUNÇÃO INTELIGENTE PARA ENCONTRAR DATA ---
def find_datetime_in_text(text: str) -> datetime | None:
    """
    Tenta encontrar uma data e hora no texto extraído usando várias regras (regex).
    Retorna um objeto datetime se encontrar, ou None se não encontrar.
    """
    # Mapeamento de meses para números
    month_map = {
        'jan': 1, 'fev': 2, 'mar': 3, 'abr': 4, 'mai': 5, 'jun': 6, 
        'jul': 7, 'ago': 8, 'set': 9, 'out': 10, 'nov': 11, 'dez': 12
    }

    # --- REGRA 1: Formato "DD de Mês de AAAA HH:MM:SS" (mais flexível) ---
    # Ex: "18 denov de 2025 :31:44" ou "14 de nov. de 2025 07:40:50"
    # Esta regex é mais tolerante a espaços e caracteres extras.
    match1 = re.search(r'(\d{1,2})\s*de\s*([a-z]{3,})\.?\s*de\s*(\d{4})\s*.*?(\d{2}:\d{2}:\d{2})', text, re.IGNORECASE)
    if match1:
        logger.info("Padrão 1 ('DD de Mês de AAAA') encontrado!")
        day, month_str, year, time = match1.groups()
        month = month_map.get(month_str.lower()[:3])
        if month:
            try:
                return datetime(int(year), month, int(day), int(time[:2]), int(time[3:5]), int(time[6:]))
            except ValueError:
                logger.error("Valores de data/hora inválidos encontrados no Padrão 1.")

    # --- REGRA 2: Formato "DD/MM/AAAA HH:MM:SS" ---
    match2 = re.search(r'(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2}:\d{2})', text)
    if match2:
        logger.info("Padrão 2 ('DD/MM/AAAA') encontrado!")
        date_str, time_str = match2.groups()
        try:
            return datetime.strptime(f"{date_str} {time_str}", '%d/%m/%Y %H:%M:%S')
        except ValueError:
            logger.error("Formato de data/hora inválido para DD/MM/AAAA.")

    logger.info("Nenhum padrão de data/hora conhecido foi encontrado no texto.")
    return None # Retorna None se nenhuma regra funcionar

# Função para o comando /start (sem alterações)
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Olá! Envie uma foto com data e hora para que eu possa extrair as informações.")

# --- FUNÇÃO handle_photo ATUALIZADA PARA USAR A NOVA LÓGICA ---
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not (update.message.photo or update.message.document):
        return

    if update.message.photo:
        file = await update.message.photo[-1].get_file()
    else:
        file = await update.message.document.get_file()

    file_path = f"temp_{file.file_id}.jpg"
    reply_text = "Não consegui encontrar uma data e hora na imagem. 😕"

    try:
        await file.download_to_drive(file_path)
        
        extracted_text = pytesseract.image_to_string(Image.open(file_path), lang='por')
        logger.info(f"Texto extraído via OCR:\n---\n{extracted_text}\n---")

        # Chama a nova função inteligente
        dt_object = find_datetime_in_text(extracted_text)
        
        if dt_object:
            reply_text = f"Data e Hora encontradas! 📸\n{dt_object.strftime('%d/%m/%Y %H:%M:%S')}"
        
    except Exception as e:
        logger.error(f"Erro ao processar a imagem: {e}")
        reply_text = "Ocorreu um erro ao tentar processar esta imagem."
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)
            
    await update.message.reply_text(reply_text)

def main() -> None:
    token = os.environ.get("BOT_TOKEN") # Usando BOT_TOKEN como definimos
    if not token:
        logger.error("O BOT_TOKEN não foi configurado!")
        return

    application = Application.builder().token(token).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, handle_photo))

    logger.info("Bot iniciado e escutando...")
    application.run_polling()

if __name__ == "__main__":
    main()
