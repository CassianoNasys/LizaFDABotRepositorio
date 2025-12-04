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
    """Abre a imagem sem pré-processamento agressivo que destrói texto pequeno."""
    img = Image.open(image_path)
    # Não aplicamos binarização agressiva, pois destroi o texto pequeno das coordenadas
    # O Tesseract consegue ler melhor a imagem original ou com contraste suave
    return img

def clean_ocr_text(text: str) -> str:
    """Limpa o texto extraído pelo OCR."""
    text = re.sub(r'denov', 'de nov', text, flags=re.IGNORECASE)
    logger.info(f"Texto após a limpeza:\n---\n{text}\n---")
    return text

def parse_coordinates(coords_str: str) -> tuple[float, float] | None:
    """
    Processa coordenadas GPS no formato: -6,6386S -51,9896W
    Retorna uma tupla (latitude, longitude) como números decimais.
    """
    try:
        # Divide a string em duas partes (latitude e longitude)
        parts = coords_str.strip().split()
        if len(parts) != 2:
            logger.error(f"Formato de coordenadas inválido: {coords_str}")
            return None
        
        lat_str, lon_str = parts
        
        # Processa a latitude
        # Remove a letra de direção (N, S) e substitui vírgula por ponto
        lat_str = lat_str.replace(',', '.').replace('S', '').replace('N', '')
        latitude = float(lat_str)
        
        # Processa a longitude
        # Remove a letra de direção (E, W, L, O) e substitui vírgula por ponto
        lon_str = lon_str.replace(',', '.').replace('W', '').replace('E', '').replace('L', '').replace('O', '')
        longitude = float(lon_str)
        
        # Valida os valores
        if not (-90 <= latitude <= 90):
            logger.error(f"Latitude fora do intervalo válido: {latitude}")
            return None
        if not (-180 <= longitude <= 180):
            logger.error(f"Longitude fora do intervalo válido: {longitude}")
            return None
        
        logger.info(f"Coordenadas processadas com sucesso: Latitude={latitude}, Longitude={longitude}")
        return (latitude, longitude)
    
    except ValueError as e:
        logger.error(f"Erro ao converter coordenadas para números: {e}")
        return None

def find_datetime_in_text(text: str) -> datetime | None:
    """Busca por data e hora no texto usando várias regras."""
    month_map = {
        'jan': 1, 'fev': 2, 'mar': 3, 'abr': 4, 'mai': 5, 'jun': 6, 
        'jul': 7, 'ago': 8, 'set': 9, 'out': 10, 'nov': 11, 'dez': 12
    }

    # REGRA 1 (sem alterações)
    match1 = re.search(r'(\d{1,2})\s*(?:de\s*)?([a-z]{3,})\.?\s*(?:de\s*)?(\d{4})\s*.*?(\d{2}:\d{2}(?::\d{2})?)', text, re.IGNORECASE)
    if match1:
        logger.info("Padrão 1 ('DD de Mês de AAAA') encontrado!")
        day, month_str, year, time_str = match1.groups()
        month = month_map.get(month_str.lower()[:3])
        if month:
            try:
                # Adiciona :00 se os segundos estiverem faltando
                if len(time_str) == 5: time_str += ':00'
                return datetime(int(year), month, int(day), int(time_str[:2]), int(time_str[3:5]), int(time_str[6:]))
            except ValueError:
                logger.error("Valores de data/hora inválidos no Padrão 1.")

    # REGRA 2 ATUALIZADA: Segundos (:\d{2}) agora são opcionais
    match2 = re.search(r'(\d{2}/\d{2}/\d{4})\s*(\d{2}:\d{2}(?::\d{2})?)', text)
    if match2:
        logger.info("Padrão 2 ('DD/MM/AAAA') encontrado!")
        date_str, time_str = match2.groups()
        try:
            # Adiciona :00 se os segundos estiverem faltando
            if len(time_str) == 5: time_str += ':00'
            return datetime.strptime(f"{date_str} {time_str}", '%d/%m/%Y %H:%M:%S')
        except ValueError:
            logger.error("Formato de data/hora inválido para DD/MM/AAAA.")

    logger.info("Nenhum padrão de data/hora conhecido foi encontrado no texto.")
    return None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Envia uma mensagem quando o comando /start é emitido."""
    await update.message.reply_text("Olá! Envie uma foto com data e hora para que eu possa extrair as informações.")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not (update.message.photo or update.message.document):
        return

    if update.message.photo:
        file = await update.message.photo[-1].get_file()
    else:
        file = await update.message.document.get_file()

    file_path = f"temp_{file.file_id}.jpg"
    
    dt_object = None
    coords_str = None

    try:
        await file.download_to_drive(file_path)
        
        processed_image = preprocess_image_for_ocr(file_path)
        raw_text = pytesseract.image_to_string(processed_image, lang='por+eng')
        logger.info(f"Texto extraído (bruto):\n---\n{raw_text}\n---")

        cleaned_text = clean_ocr_text(raw_text)
        logger.info(f"Texto limpo para busca de coordenadas:\n---\n{cleaned_text}\n---")
        
        dt_object = find_datetime_in_text(cleaned_text)
        
        # --- REGEX DE COORDENADAS ATUALIZADA ---
        # Procura por padrão: -6,6386S -51,9866W
        # Permite: hífen opcional, dígitos, vírgula ou ponto, dígitos, letra de direção
        # Tenta com re.IGNORECASE para ser mais flexível
        coords_match = re.search(r'(-?\d+[\.,]\d+[NSns])\s+(-?\d+[\.,]\d+[EWLOwvloe])', cleaned_text, re.IGNORECASE)
        if coords_match:
            coords_str = f"{coords_match.group(1)} {coords_match.group(2)}"
            logger.info(f"Coordenadas GPS encontradas (bruto): {coords_str}")
            
            # Processa as coordenadas para formato numérico
            parsed_coords = parse_coordinates(coords_str)
            if parsed_coords:
                latitude, longitude = parsed_coords
                coords_str = f"{latitude:.4f}, {longitude:.4f}"
            else:
                coords_str = None

    except Exception as e:
        logger.error(f"Erro ao processar a imagem: {e}")
        await update.message.reply_text("Ocorreu um erro ao tentar processar esta imagem.")
        return
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)

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

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, handle_photo))

    logger.info("Bot iniciado e escutando...")
    application.run_polling()

if __name__ == "__main__":
    main()