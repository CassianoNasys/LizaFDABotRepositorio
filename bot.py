#!/usr/bin/env python3
"""
Bot do Telegram para extrair coordenadas GPS de fotos.
Formato esperado: -6,6386S -51,9896W

Deploy no Railway:
1. Configure a variável de ambiente BOT_TOKEN com seu token do Telegram
2. Execute: python3 bot_telegram.py
"""

import logging
import os
import re
import io
from datetime import datetime
from pathlib import Path
from PIL import Image, ImageOps

import pytesseract
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Configuração do Tesseract
pytesseract.pytesseract.tesseract_cmd = r'/usr/bin/tesseract'

# Configuração de logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ============================================================================
# FUNÇÕES DE PROCESSAMENTO DE COORDENADAS
# ============================================================================

def parse_coordinates(coords_str: str) -> tuple[float, float] | None:
    """
    Processa coordenadas GPS no formato: -6,6386S -51,9896W
    Retorna uma tupla (latitude, longitude) como números decimais.
    
    Args:
        coords_str: String com coordenadas no formato "-6,6386S -51,9896W"
    
    Returns:
        Tupla (latitude, longitude) ou None se inválido
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
        
        logger.info(f"✓ Coordenadas processadas: Lat={latitude}, Lon={longitude}")
        return (latitude, longitude)
    
    except ValueError as e:
        logger.error(f"Erro ao converter coordenadas para números: {e}")
        return None

def format_coordinates(latitude: float, longitude: float) -> str:
    """
    Formata coordenadas para exibição amigável.
    
    Args:
        latitude: Valor da latitude
        longitude: Valor da longitude
    
    Returns:
        String formatada com coordenadas
    """
    lat_dir = "S" if latitude < 0 else "N"
    lon_dir = "W" if longitude < 0 else "E"
    
    lat_abs = abs(latitude)
    lon_abs = abs(longitude)
    
    return f"{lat_abs:.4f}° {lat_dir} | {lon_abs:.4f}° {lon_dir}"

# ============================================================================
# FUNÇÕES DE PROCESSAMENTO DE IMAGEM
# ============================================================================

def preprocess_image_for_ocr(image: Image.Image) -> Image.Image:
    """
    Aplica filtros na imagem para melhorar a qualidade do OCR.
    
    Args:
        image: Objeto PIL Image
    
    Returns:
        Imagem processada
    """
    try:
        # Converte para escala de cinza
        img = image.convert('L')
        # Aumenta o contraste automaticamente
        img = ImageOps.autocontrast(img)
        # Converte para preto e branco (binarização)
        img = img.point(lambda x: 0 if x < 128 else 255, '1')
        return img
    except Exception as e:
        logger.error(f"Erro ao pré-processar imagem: {e}")
        return image

def extract_text_from_image(image: Image.Image) -> str:
    """
    Extrai texto de uma imagem usando OCR.
    
    Args:
        image: Objeto PIL Image
    
    Returns:
        Texto extraído
    """
    try:
        # Pré-processa a imagem
        processed_image = preprocess_image_for_ocr(image)
        # Executa OCR
        text = pytesseract.image_to_string(processed_image, lang='por')
        logger.info(f"Texto extraído (bruto):\n{text}")
        return text
    except Exception as e:
        logger.error(f"Erro ao extrair texto da imagem: {e}")
        return ""

def extract_coordinates_from_text(text: str) -> str | None:
    """
    Procura por coordenadas GPS no texto extraído.
    Padrão esperado: -6,6386S -51,9896W
    
    Args:
        text: Texto extraído da imagem
    
    Returns:
        String com coordenadas ou None se não encontrado
    """
    # Regex para encontrar coordenadas no formato: -6,6386S -51,9896W
    # Permite: hífen opcional, dígitos, vírgula ou ponto, dígitos, letra de direção
    coords_match = re.search(
        r'(-?\d+[\.,]\d+[NSns])\s+(-?\d+[\.,]\d+[EWLOwvloe])',
        text
    )
    
    if coords_match:
        coords_str = f"{coords_match.group(1)} {coords_match.group(2)}"
        logger.info(f"Coordenadas encontradas (bruto): {coords_str}")
        return coords_str
    
    logger.info("Nenhuma coordenada encontrada no texto.")
    return None

# ============================================================================
# HANDLERS DO BOT
# ============================================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handler para o comando /start.
    Envia uma mensagem de boas-vindas.
    """
    welcome_message = (
        "👋 **Bem-vindo ao Bot de Coordenadas GPS!**\n\n"
        "Envie uma foto com coordenadas GPS visíveis e eu vou extrair as informações para você.\n\n"
        "📸 **Formato esperado das coordenadas:**\n"
        "`-6,6386S -51,9896W`\n\n"
        "Comandos disponíveis:\n"
        "/start - Mostra esta mensagem\n"
        "/help - Ajuda detalhada\n"
    )
    await update.message.reply_text(welcome_message, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handler para o comando /help.
    Exibe instruções detalhadas.
    """
    help_message = (
        "🆘 **AJUDA - Como usar o bot**\n\n"
        "1️⃣ **Tire uma foto** com um aplicativo que adicione coordenadas GPS\n"
        "   Exemplos: GPS Map Camera, Solocator, ou câmera nativa com GPS ativado\n\n"
        "2️⃣ **Envie a foto** para este chat\n\n"
        "3️⃣ **O bot vai:**\n"
        "   ✓ Extrair o texto da imagem (OCR)\n"
        "   ✓ Procurar pelas coordenadas GPS\n"
        "   ✓ Validar e formatar as coordenadas\n"
        "   ✓ Mostrar o resultado\n\n"
        "📍 **Formato de coordenadas suportado:**\n"
        "`-6,6386S -51,9896W`\n"
        "(Latitude Longitude com direção)\n\n"
        "❓ **Dúvidas?**\n"
        "Certifique-se de que:\n"
        "• A câmera tem GPS ativado\n"
        "• As coordenadas estão visíveis na imagem\n"
        "• O formato é similar ao exemplo acima\n"
    )
    await update.message.reply_text(help_message, parse_mode='Markdown')

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handler para fotos enviadas ao bot.
    Extrai coordenadas GPS da imagem.
    """
    
    # Verifica se é uma foto ou documento
    if update.message.photo:
        file = await update.message.photo[-1].get_file()
        file_name = f"photo_{update.message.photo[-1].file_id}.jpg"
    elif update.message.document:
        file = await update.message.document.get_file()
        file_name = update.message.document.file_name or f"document_{file.file_id}"
    else:
        return
    
    # Envia mensagem de processamento
    processing_msg = await update.message.reply_text(
        "⏳ Processando a imagem... Por favor, aguarde."
    )
    
    temp_file_path = f"/tmp/{file_name}"
    
    try:
        # Faz o download da imagem
        await file.download_to_drive(temp_file_path)
        logger.info(f"Imagem salva em: {temp_file_path}")
        
        # Abre a imagem
        image = Image.open(temp_file_path)
        logger.info(f"Imagem aberta: {image.size} pixels")
        
        # Extrai texto da imagem
        extracted_text = extract_text_from_image(image)
        
        if not extracted_text.strip():
            await processing_msg.edit_text(
                "❌ Não consegui extrair texto da imagem.\n"
                "Certifique-se de que as coordenadas estão visíveis e legíveis."
            )
            return
        
        # Procura por coordenadas no texto
        coords_str = extract_coordinates_from_text(extracted_text)
        
        if not coords_str:
            await processing_msg.edit_text(
                "❌ Não encontrei coordenadas GPS na imagem.\n\n"
                "📍 Formato esperado: `-6,6386S -51,9896W`\n\n"
                "Verifique se:\n"
                "• As coordenadas estão visíveis na imagem\n"
                "• O formato é similar ao exemplo acima\n"
                "• A câmera tem GPS ativado"
            )
            return
        
        # Processa as coordenadas
        parsed_coords = parse_coordinates(coords_str)
        
        if not parsed_coords:
            await processing_msg.edit_text(
                "❌ Não consegui processar as coordenadas.\n\n"
                f"Coordenadas encontradas: `{coords_str}`\n\n"
                "Verifique se o formato está correto."
            )
            return
        
        # Formata a resposta
        latitude, longitude = parsed_coords
        formatted_coords = format_coordinates(latitude, longitude)
        
        response_message = (
            "✅ **Coordenadas Extraídas com Sucesso!**\n\n"
            f"📍 **Localização:** {formatted_coords}\n\n"
            f"**Valores Numéricos:**\n"
            f"• Latitude: `{latitude:.6f}`\n"
            f"• Longitude: `{longitude:.6f}`\n\n"
            f"**Formato Original:** `{coords_str}`\n\n"
            f"⏰ Processado em: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
        )
        
        await processing_msg.edit_text(response_message, parse_mode='Markdown')
        logger.info(f"Resposta enviada com sucesso para o usuário.")
    
    except Exception as e:
        logger.error(f"Erro ao processar a imagem: {e}")
        await processing_msg.edit_text(
            f"❌ Ocorreu um erro ao processar a imagem:\n`{str(e)}`\n\n"
            "Por favor, tente novamente com outra imagem."
        )
    
    finally:
        # Limpa o arquivo temporário
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)
            logger.info(f"Arquivo temporário removido: {temp_file_path}")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handler para mensagens de texto.
    Responde com instruções.
    """
    await update.message.reply_text(
        "📸 Por favor, envie uma **foto** com coordenadas GPS visíveis.\n\n"
        "Use /help para mais informações."
    )

# ============================================================================
# FUNÇÃO PRINCIPAL
# ============================================================================

def main() -> None:
    """
    Função principal que inicia o bot.
    """
    # Obtém o token do Telegram
    token = os.environ.get("BOT_TOKEN")
    
    if not token:
        logger.error(
            "❌ BOT_TOKEN não foi configurado!\n"
            "Configure a variável de ambiente BOT_TOKEN com seu token do Telegram."
        )
        return
    
    logger.info("🚀 Iniciando o bot do Telegram...")
    
    # Cria a aplicação
    application = Application.builder().token(token).build()
    
    # Adiciona handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(
        MessageHandler(filters.PHOTO | filters.Document.IMAGE, handle_photo)
    )
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    logger.info("✅ Bot configurado e escutando mensagens...")
    logger.info("Pressione Ctrl+C para parar o bot.")
    
    # Inicia o bot
    application.run_polling()

if __name__ == "__main__":
    main()