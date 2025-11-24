import logging
import os
from datetime import datetime
from PIL import Image, ImageOps # ImageOps é novo, para pré-processamento

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

# --- NOVA FUNÇÃO DE PRÉ-PROCESSAMENTO DE IMAGEM ---
def preprocess_image_for_ocr(image_path: str) -> Image.Image:
    """
    Abre uma imagem, aplica filtros para melhorar a qualidade do OCR e a retorna.
    """
    img = Image.open(image_path)
    # 1. Converte para escala de cinza
    img = img.convert('L')
    # 2. Aumenta o contraste
    img = ImageOps.autocontrast(img)
    # 3. Binarização: converte pixels abaixo de um limiar para preto, e acima para branco.
    # O valor 128 é um bom ponto de partida, mas pode precisar de ajuste.
    img = img.point(lambda x: 0 if x < 128 else 255, '1')
    return img

def clean_ocr_text(text: str) -> str:
    """Limpa o texto extraído pelo OCR para corrigir erros comuns."""
    text = re.sub(r'denov', 'de nov', text, flags=re.IGNORECASE)
    logger.info(f"Texto após a limpeza:\n---\n{text}\n---")
    return text

def find_datetime_in_text(text: str) -> datetime | None:
    """Tenta encontrar uma data e hora no texto extraído usando várias regras."""
    month_map = {
        'jan': 1, 'fev': 2, 'mar': 3, 'abr': 4, 'mai': 5, 'jun': 6, 
        'jul': 7, 'ago': 8, 'set': 9, 'out': 10, 'nov': 11, 'dez': 12
    }

    # REGRA 1 (sem alterações)
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

    # REGRA 2 ATUALIZADA: Espaço entre data e hora agora é opcional (\s*)
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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Olá! Envie uma foto com data e hora para que eu possa extrair as informações.")

# --- FUNÇÃO handle_photo ATUALIZADA PARA USAR PRÉ-PROCESSAMENTO ---
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
        
        # PASSO 1: Pré-processa a imagem para melhorar o OCR
        processed_image = preprocess_image_for_ocr(file_path)
        
        # PASSO 2: Executa o OCR na imagem processada
        raw_text = pytesseract.image_to_string(processed_image, lang='por')
        logger.info(f"Texto extraído (bruto):\n---\n{raw_text}\n---")

        # PASSO 3: Limpa o texto
        cleaned_text = clean_ocr_text(raw_text)
        
        # PASSO 4: Busca a data no texto limpo
        dt_object = find_datetime_in_text(cleaned_text)
        
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
    token = os.environ.get("BOT_TOKEN")
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
