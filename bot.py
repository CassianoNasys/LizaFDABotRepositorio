import logging
import os
from datetime import datetime
from PIL import Image, ImageOps

import pytesseract
import re

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Configuração do Tesseract
pytesseract.pytesseract.tesseract_cmd = r'/usr/bin/tesseract'

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

def preprocess_image_for_ocr(image_path: str) -> Image.Image:
    """Aplica filtros na imagem para melhorar a qualidade do OCR."""
    img = Image.open(image_path)
    img = img.convert('L')
    img = ImageOps.autocontrast(img)
    img = img.point(lambda x: 0 if x < 128 else 255, '1')
    return img

def clean_ocr_text(text: str) -> str:
    """Limpa o texto extraído pelo OCR."""
    text = re.sub(r'denov', 'de nov', text, flags=re.IGNORECASE)
    logger.info(f"Texto após a limpeza:\n---\n{text}\n---")
    return text

def find_datetime_in_text(text: str) -> datetime | None:
    """Busca por data e hora no texto usando várias regras."""
    month_map = {
        'jan': 1, 'fev': 2, 'mar': 3, 'abr': 4, 'mai': 5, 'jun': 6, 
        'jul': 7, 'ago': 8, 'set': 9, 'out': 10, 'nov': 11, 'dez': 12
    }

    # REGRA 1: "DD de Mês de AAAA HH:MM:SS"
    match1 = re.search(r'(\d{1,2})\s*(?:de\s*)?([a-z]{3,})\.?\s*(?:de\s*)?(\d{4})\s*.*?(\d{2}:\d{2}:\d{2})', text, re.IGNORECASE)
    if match1:
        logger.info("Padrão 1 ('DD de Mês de AAAA') encontrado!")
        day, month_str, year, time = match1.groups()
        month = month_map.get(month_str.lower()[:3])
        if month:
            try:
                return datetime(int(year), month, int(day), int(time[:2]), int(time[3:5]), int(time[6:]))
            except ValueError:
                logger.error("Valores de data/hora inválidos no Padrão 1.")

    # REGRA 2: "DD/MM/AAAA HH:MM:SS" (espaço opcional)
    match2 = re.search(r'(\d{2}/\d{2}/\d{4})\s*(\d{2}:\d{2}:\d{2})', text)
    if match2:
        logger.info("Padrão 2 ('DD/MM/AAAA') encontrado!")
        date_str, time_str = match2.groups()
        try:
            return datetime.strptime(f"{date_str} {time_str}", '%d/%m/%Y %H:%M:%S')
        except ValueError:
            logger.error("Formato de data/hora inválido para DD/MM/AAAA.")

    logger.info("Nenhum padrão de data/hora conhecido foi encontrado no texto.")
    return None

# --- FUNÇÃO handle_photo ATUALIZADA PARA EXTRAIR COORDENADAS ---
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not (update.message.photo or update.message.document):
        return

    if update.message.photo:
        file = await update.message.photo[-1].get_file()
    else:
        file = await update.message.document.get_file()

    file_path = f"temp_{file.file_id}.jpg"
    
    # Mensagens padrão
    dt_object = None
    coords_str = None

    try:
        await file.download_to_drive(file_path)
        
        processed_image = preprocess_image_for_ocr(file_path)
        raw_text = pytesseract.image_to_string(processed_image, lang='por')
        logger.info(f"Texto extraído (bruto):\n---\n{raw_text}\n---")

        cleaned_text = clean_ocr_text(raw_text)
        
        # PASSO 1: Tenta encontrar a data e hora
        dt_object = find_datetime_in_text(cleaned_text)
        
        # PASSO 2: Tenta encontrar as coordenadas GPS
        # Regex para encontrar: [número].[número]S [número].[número]W
        coords_match = re.search(r'(\d+\.\d+S\s+\d+\.\d+W)', cleaned_text, re.IGNORECASE)
        if coords_match:
            coords_str = coords_match.group(1)
            logger.info(f"Coordenadas GPS encontradas: {coords_str}")

    except Exception as e:
        logger.error(f"Erro ao processar a imagem: {e}")
        await update.message.reply_text("Ocorreu um erro ao tentar processar esta imagem.")
        return
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)

    # PASSO 3: Constrói a resposta final com base no que foi encontrado
    if dt_object or coords_str:
        reply_parts = ["Dados extraídos da imagem! 📸"]
        if dt_object:
            reply_parts.append(f"Data e Hora: {dt_object.strftime('%d/%m/%Y %H:%M:%S')}")
        if coords_str:
            reply_parts.append(f"Coordenadas: {coords_str}")
        
        reply_text = "\n".join(reply_parts)
    else:
        reply_text = "Não consegui encontrar data/hora ou coordenadas na imagem. 😕"
            
    await update.message.reply_text(reply_text)

def main() -> None:
    token = os.environ.get("BOT_TOKEN")
    if not token:
        logger.error("O BOT_TOKEN não foi configurado!")
        return

    application = Application.builder().token(token).build()

    # O comando /start não foi alterado
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, handle_photo))

    logger.info("Bot iniciado e escutando...")
    application.run_polling()

if __name__ == "__main__":
    main()
