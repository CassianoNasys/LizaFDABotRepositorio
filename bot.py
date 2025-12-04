import logging
import os
import json
from datetime import datetime
from pathlib import Path
from PIL import Image
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

# ID do grupo FDA Relatorios
RELATORIO_GROUP_ID = -5078417185

# Arquivo para armazenar coordenadas
COORDS_FILE = "coordenadas.json"
MAPA_FILE = "mapa.html"

# ============================================================================
# FUNÇÕES DE ARMAZENAMENTO
# ============================================================================

def load_coordinates() -> list:
    """Carrega as coordenadas do arquivo JSON."""
    if os.path.exists(COORDS_FILE):
        try:
            with open(COORDS_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Erro ao carregar coordenadas: {e}")
            return []
    return []

def save_coordinates(coords_list: list) -> bool:
    """Salva as coordenadas no arquivo JSON."""
    try:
        with open(COORDS_FILE, 'w') as f:
            json.dump(coords_list, f, indent=2, ensure_ascii=False)
        logger.info(f"Coordenadas salvas: {len(coords_list)} pontos")
        return True
    except Exception as e:
        logger.error(f"Erro ao salvar coordenadas: {e}")
        return False

def add_coordinate(latitude: float, longitude: float, timestamp: str) -> bool:
    """Adiciona uma nova coordenada à lista."""
    coords_list = load_coordinates()
    
    new_coord = {
        "latitude": latitude,
        "longitude": longitude,
        "timestamp": timestamp,
        "id": len(coords_list) + 1
    }
    
    coords_list.append(new_coord)
    return save_coordinates(coords_list)

# ============================================================================
# FUNÇÕES DE MAPA
# ============================================================================

def generate_map() -> bool:
    """Gera um mapa interativo com todas as coordenadas usando Folium."""
    try:
        import folium
        
        coords_list = load_coordinates()
        
        if not coords_list:
            logger.warning("Nenhuma coordenada para gerar mapa")
            return False
        
        # Calcula o centro do mapa
        lats = [c["latitude"] for c in coords_list]
        lons = [c["longitude"] for c in coords_list]
        center_lat = sum(lats) / len(lats)
        center_lon = sum(lons) / len(lons)
        
        # Cria o mapa
        mapa = folium.Map(
            location=[center_lat, center_lon],
            zoom_start=12,
            tiles="OpenStreetMap"
        )
        
        # Adiciona os marcadores
        for coord in coords_list:
            folium.Marker(
                location=[coord["latitude"], coord["longitude"]],
                popup=f"<b>Ponto {coord['id']}</b><br>Data: {coord['timestamp']}<br>Lat: {coord['latitude']:.4f}<br>Lon: {coord['longitude']:.4f}",
                tooltip=f"Ponto {coord['id']} - {coord['timestamp']}",
                icon=folium.Icon(color="blue", icon="info-sign")
            ).add_to(mapa)
        
        # Salva como HTML
        mapa.save(MAPA_FILE)
        logger.info(f"Mapa HTML gerado: {MAPA_FILE} com {len(coords_list)} pontos")
        return True
    
    except ImportError:
        logger.error("Folium não está instalado")
        return False
    except Exception as e:
        logger.error(f"Erro ao gerar mapa: {e}")
        import traceback
        traceback.print_exc()
        return False

# ============================================================================
# FUNÇÕES DE OCR E PROCESSAMENTO
# ============================================================================

def preprocess_image_for_ocr(image_path: str) -> Image.Image:
    """Abre a imagem sem pré-processamento agressivo que destrói texto pequeno."""
    img = Image.open(image_path)
    return img

def clean_ocr_text(text: str) -> str:
    """Limpa o texto extraído pelo OCR."""
    text = re.sub(r'denov', 'de nov', text, flags=re.IGNORECASE)
    return text

def parse_coordinates(coords_str: str) -> tuple[float, float] | None:
    """Processa coordenadas GPS no formato: -6,6386S -51,9896W"""
    try:
        parts = coords_str.strip().split()
        if len(parts) != 2:
            logger.error(f"Formato de coordenadas inválido: {coords_str}")
            return None
        
        lat_str, lon_str = parts
        
        lat_str = lat_str.replace(',', '.').replace('S', '').replace('N', '')
        latitude = float(lat_str)
        
        lon_str = lon_str.replace(',', '.').replace('W', '').replace('E', '').replace('L', '').replace('O', '')
        longitude = float(lon_str)
        
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

    # REGRA 1: DD de Mês de AAAA HH:MM:SS
    match1 = re.search(r'(\d{1,2})\s*(?:de\s*)?([a-z]{3,})\.?\s*(?:de\s*)?(\d{4})\s*.*?(\d{2}:\d{2}(?::\d{2})?)', text, re.IGNORECASE)
    if match1:
        logger.info("Padrão 1 ('DD de Mês de AAAA') encontrado!")
        day, month_str, year, time_str = match1.groups()
        month = month_map.get(month_str.lower()[:3])
        if month:
            try:
                if len(time_str) == 5: time_str += ':00'
                return datetime(int(year), month, int(day), int(time_str[:2]), int(time_str[3:5]), int(time_str[6:]))
            except ValueError:
                logger.error("Valores de data/hora inválidos no Padrão 1.")

    # REGRA 2: DD/MM/AAAA HH:MM:SS
    match2 = re.search(r'(\d{2}/\d{2}/\d{4})\s*(\d{2}:\d{2}(?::\d{2})?)', text)
    if match2:
        logger.info("Padrão 2 ('DD/MM/AAAA') encontrado!")
        date_str, time_str = match2.groups()
        try:
            if len(time_str) == 5: time_str += ':00'
            return datetime.strptime(f"{date_str} {time_str}", '%d/%m/%Y %H:%M:%S')
        except ValueError:
            logger.error("Formato de data/hora inválido para DD/MM/AAAA.")

    logger.info("Nenhum padrão de data/hora conhecido foi encontrado no texto.")
    return None

# ============================================================================
# HANDLERS DO BOT
# ============================================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Envia uma mensagem quando o comando /start é emitido."""
    await update.message.reply_text(
        "Olá! 👋\n\n"
        "Envie uma foto com data e hora para que eu possa extrair as informações.\n\n"
        "As coordenadas serão armazenadas e um mapa será gerado automaticamente no grupo 'FDA Relatorios'."
    )

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler para fotos enviadas ao bot."""
    if not (update.message.photo or update.message.document):
        return

    if update.message.photo:
        file = await update.message.photo[-1].get_file()
    else:
        file = await update.message.document.get_file()

    file_path = f"temp_{file.file_id}.jpg"
    
    dt_object = None
    coords_str = None
    latitude = None
    longitude = None

    try:
        await file.download_to_drive(file_path)
        
        processed_image = preprocess_image_for_ocr(file_path)
        raw_text = pytesseract.image_to_string(processed_image, lang='por+eng')
        logger.info(f"Texto extraído (bruto):\n---\n{raw_text}\n---")

        cleaned_text = clean_ocr_text(raw_text)
        logger.info(f"Texto limpo para busca de coordenadas:\n---\n{cleaned_text}\n---")
        
        dt_object = find_datetime_in_text(cleaned_text)
        
        # Procura por coordenadas
        coords_match = re.search(r'(-?\d+[\.,]\d+[NSns])\s+(-?\d+[\.,]\d+[EWLOwvloe])', cleaned_text, re.IGNORECASE)
        if coords_match:
            coords_str_raw = f"{coords_match.group(1)} {coords_match.group(2)}"
            logger.info(f"Coordenadas GPS encontradas (bruto): {coords_str_raw}")
            
            # Processa as coordenadas para formato numérico
            parsed_coords = parse_coordinates(coords_str_raw)
            if parsed_coords:
                latitude, longitude = parsed_coords
                coords_str = f"{latitude:.4f}, {longitude:.4f}"
                
                # Adiciona à lista de coordenadas
                timestamp = dt_object.strftime('%d/%m/%Y %H:%M:%S') if dt_object else datetime.now().strftime('%d/%m/%Y %H:%M:%S')
                add_coordinate(latitude, longitude, timestamp)
                
                # Gera novo mapa
                logger.info("Gerando novo mapa...")
                if generate_map():
                    logger.info("Mapa gerado com sucesso")
                else:
                    logger.error("Falha ao gerar mapa")
            else:
                coords_str = None

    except Exception as e:
        logger.error(f"Erro ao processar a imagem: {e}")
        import traceback
        traceback.print_exc()
        await update.message.reply_text("Ocorreu um erro ao tentar processar esta imagem.")
        return
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)

    # Prepara resposta
    if dt_object or coords_str:
        reply_parts = ["✅ Dados extraídos da imagem! 📸"]
        if dt_object:
            reply_parts.append(f"🕐 Data e Hora: {dt_object.strftime('%d/%m/%Y %H:%M:%S')}")
        if coords_str:
            reply_parts.append(f"📍 Coordenadas: {coords_str}")
        
        reply_text = "\n".join(reply_parts)
    else:
        reply_text = "❌ Não consegui encontrar data/hora ou coordenadas na imagem. 😕"
            
    await update.message.reply_text(reply_text)
    
    # Se encontrou coordenadas, envia mapa para o grupo de relatórios
    if coords_str and os.path.exists(MAPA_FILE):
        try:
            coords_list = load_coordinates()
            with open(MAPA_FILE, 'rb') as mapa_file:
                await context.bot.send_document(
                    chat_id=RELATORIO_GROUP_ID,
                    document=mapa_file,
                    caption=f"🗺️ Mapa atualizado!\n\n"
                            f"📍 Nova coordenada: {coords_str}\n"
                            f"🕐 Data/Hora: {dt_object.strftime('%d/%m/%Y %H:%M:%S') if dt_object else 'N/A'}\n"
                            f"📊 Total de pontos: {len(coords_list)}"
                )
            logger.info("Mapa enviado para o grupo de relatórios")
        except Exception as e:
            logger.error(f"Erro ao enviar mapa para o grupo: {e}")
            import traceback
            traceback.print_exc()

def main() -> None:
    """Função principal que inicia o bot."""
    token = os.environ.get("BOT_TOKEN")
    if not token:
        logger.error("O BOT_TOKEN não foi configurado!")
        return

    logger.info("🚀 Iniciando o bot...")
    application = Application.builder().token(token).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, handle_photo))

    logger.info("✅ Bot configurado e escutando mensagens...")
    application.run_polling()

if __name__ == "__main__":
    main()