import logging
import os
import json
import asyncio
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

# Variáveis globais para controlar o delay de geração de mapa
mapa_timer = None
application_context = None

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

def coordinate_exists(latitude: float, longitude: float, timestamp: str) -> bool:
    """Verifica se uma coordenada já existe (deduplicação)."""
    coords_list = load_coordinates()
    
    for coord in coords_list:
        # Compara com tolerância de 0.0001 graus (aproximadamente 10 metros)
        lat_match = abs(coord["latitude"] - latitude) < 0.0001
        lon_match = abs(coord["longitude"] - longitude) < 0.0001
        time_match = coord["timestamp"] == timestamp
        
        if lat_match and lon_match and time_match:
            logger.info(f"Coordenada duplicada detectada: {latitude}, {longitude} em {timestamp}")
            return True
    
    return False

def add_coordinate(latitude: float, longitude: float, timestamp: str) -> bool:
    """Adiciona uma nova coordenada à lista (se não for duplicada)."""
    # Verifica se é duplicada
    if coordinate_exists(latitude, longitude, timestamp):
        logger.info("Ignorando coordenada duplicada")
        return False
    
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

async def schedule_map_generation(context: ContextTypes.DEFAULT_TYPE, delay: int = 60):
    """Agenda a geração de mapa com delay de 60 segundos."""
    global mapa_timer
    
    # Cancela o timer anterior se existir
    if mapa_timer is not None:
        mapa_timer.cancel()
        logger.info("Timer anterior cancelado")
    
    # Cria um novo timer
    logger.info(f"Agendando geração de mapa em {delay} segundos...")
    
    async def send_map_after_delay():
        await asyncio.sleep(delay)
        logger.info("Gerando mapa após delay de 60 segundos...")
        
        if generate_map() and os.path.exists(MAPA_FILE):
            try:
                coords_list = load_coordinates()
                with open(MAPA_FILE, 'rb') as mapa_file:
                    await context.bot.send_document(
                        chat_id=RELATORIO_GROUP_ID,
                        document=mapa_file,
                        caption=f"🗺️ Mapa atualizado!\n\n"
                                f"📊 Total de pontos: {len(coords_list)}\n"
                                f"⏰ Atualizado em: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
                    )
                logger.info("Mapa enviado para o grupo de relatórios")
            except Exception as e:
                logger.error(f"Erro ao enviar mapa para o grupo: {e}")
    
    # Cria uma task assíncrona
    mapa_timer = asyncio.create_task(send_map_after_delay())

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

def extract_data_from_image(image_path: str, max_retries: int = 2) -> tuple[datetime | None, str | None, float | None, float | None]:
    """
    Extrai data/hora e coordenadas da imagem com retry.
    
    Args:
        image_path: Caminho da imagem
        max_retries: Número máximo de tentativas (padrão 2 retries = 3 tentativas totais)
    
    Returns:
        Tupla (dt_object, coords_str, latitude, longitude)
    """
    dt_object = None
    coords_str = None
    latitude = None
    longitude = None
    
    for attempt in range(max_retries + 1):
        try:
            logger.info(f"Tentativa {attempt + 1} de {max_retries + 1}")
            
            processed_image = preprocess_image_for_ocr(image_path)
            raw_text = pytesseract.image_to_string(processed_image, lang='por+eng')
            logger.info(f"Texto extraído (bruto) - Tentativa {attempt + 1}:\n---\n{raw_text}\n---")

            cleaned_text = clean_ocr_text(raw_text)
            logger.info(f"Texto limpo - Tentativa {attempt + 1}:\n---\n{cleaned_text}\n---")
            
            # Procura por data/hora
            dt_object = find_datetime_in_text(cleaned_text)
            
            # Procura por coordenadas
            coords_match = re.search(r'(-?\d+[\.,]\d+[NSns])\s+(-?\d+[\.,]\d+[EWLOwvloe])', cleaned_text, re.IGNORECASE)
            if coords_match:
                coords_str_raw = f"{coords_match.group(1)} {coords_match.group(2)}"
                logger.info(f"Coordenadas GPS encontradas (bruto) - Tentativa {attempt + 1}: {coords_str_raw}")
                
                # Processa as coordenadas para formato numérico
                parsed_coords = parse_coordinates(coords_str_raw)
                if parsed_coords:
                    latitude, longitude = parsed_coords
                    coords_str = f"{latitude:.4f}, {longitude:.4f}"
                    logger.info(f"Coordenadas processadas com sucesso na tentativa {attempt + 1}")
                    break  # Sucesso, sai do loop
            
            # Se conseguiu extrair algo, sai do loop
            if dt_object or coords_str:
                logger.info(f"Dados extraídos com sucesso na tentativa {attempt + 1}")
                break
        
        except Exception as e:
            logger.error(f"Erro na tentativa {attempt + 1}: {e}")
            if attempt < max_retries:
                logger.info(f"Tentando novamente...")
            continue
    
    return dt_object, coords_str, latitude, longitude

# ============================================================================
# HANDLERS DO BOT
# ============================================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Envia uma mensagem quando o comando /start é emitido."""
    await update.message.reply_text(
        "Olá! 👋\n\n"
        "Envie uma foto com data e hora para que eu possa extrair as informações.\n\n"
        "As coordenadas serão armazenadas e um mapa será gerado automaticamente no grupo 'FDA Relatorios'.\n\n"
        "💡 Dica: Você pode enviar múltiplas fotos em lote. O mapa será gerado 60 segundos após a última foto!"
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
    is_duplicate = False

    try:
        await file.download_to_drive(file_path)
        
        # Extrai dados com retry
        dt_object, coords_str, latitude, longitude = extract_data_from_image(file_path, max_retries=2)

        # Se encontrou coordenadas, verifica se é duplicada
        if coords_str and dt_object:
            timestamp = dt_object.strftime('%d/%m/%Y %H:%M:%S')
            
            # Tenta adicionar à lista (retorna False se for duplicada)
            if not add_coordinate(latitude, longitude, timestamp):
                is_duplicate = True
                logger.info("Foto duplicada ignorada")

    except Exception as e:
        logger.error(f"Erro ao processar a imagem: {e}")
        import traceback
        traceback.print_exc()
        await update.message.reply_text("❌ Ocorreu um erro ao tentar processar esta imagem.")
        return
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)

    # Prepara resposta
    if is_duplicate:
        reply_text = "⚠️ Esta foto é duplicada (mesma data, hora e localização). Ignorada."
    elif dt_object or coords_str:
        reply_parts = ["✅ Dados extraídos da imagem! 📸"]
        if dt_object:
            reply_parts.append(f"🕐 Data e Hora: {dt_object.strftime('%d/%m/%Y %H:%M:%S')}")
        if coords_str:
            reply_parts.append(f"📍 Coordenadas: {coords_str}")
        
        reply_text = "\n".join(reply_parts)
    else:
        reply_text = "❌ Não consegui encontrar data/hora ou coordenadas na imagem após 3 tentativas. 😕"
            
    await update.message.reply_text(reply_text)
    
    # Se encontrou coordenadas (e não é duplicada), agenda geração de mapa
    if coords_str and not is_duplicate:
        logger.info("Agendando geração de mapa com delay de 60 segundos...")
        await schedule_map_generation(context, delay=60)

def main() -> None:
    """Função principal que inicia o bot."""
    token = os.environ.get("BOT_TOKEN")
    if not token:
        logger.error("O BOT_TOKEN não foi configurado!")
        return

    logger.info("🚀 Iniciando o bot...")
    global application_context
    application = Application.builder().token(token).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, handle_photo))

    logger.info("✅ Bot configurado e escutando mensagens...")
    application.run_polling()

if __name__ == "__main__":
    main()