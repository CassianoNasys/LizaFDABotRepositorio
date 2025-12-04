import logging
import os
import json
import asyncio
import math
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

# ============================================================================
# CONFIGURAÇÃO DE CLIENTES E GEOFENCES
# ============================================================================

CLIENTES_OURILANDIA = {
    "Oia Giro": {
        "latitude": -6.754173,
        "longitude": -51.071787,
        "raio_metros": 500,
        "cor": "blue"
    },
    "Oia Ideal": {
        "latitude": -6.750542,
        "longitude": -51.080360,
        "raio_metros": 500,
        "cor": "red"
    },
    "Oia Macre": {
        "latitude": -6.759242,
        "longitude": -51.071143,
        "raio_metros": 500,
        "cor": "green"
    },
    "Oia Parazao": {
        "latitude": -6.751243,
        "longitude": -51.078318,
        "raio_metros": 500,
        "cor": "purple"
    },
    "Oia Norte Sul": {
        "latitude": -6.752724,
        "longitude": -51.076518,
        "raio_metros": 500,
        "cor": "orange"
    },
    "Oia Mix": {
        "latitude": -6.730903,
        "longitude": -51.071559,
        "raio_metros": 500,
        "cor": "darkred"
    }
}

# ============================================================================
# FUNÇÕES DE GEOFENCE
# ============================================================================

def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calcula a distância em metros entre dois pontos usando a fórmula de Haversine.
    """
    R = 6371000  # Raio da Terra em metros
    
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    
    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    
    return R * c

def find_cliente_by_geofence(latitude: float, longitude: float) -> str | None:
    """
    Encontra o cliente baseado na geofence (500 metros).
    Retorna o nome do cliente ou None se não encontrar.
    """
    for cliente_name, cliente_info in CLIENTES_OURILANDIA.items():
        distancia = haversine_distance(
            latitude, longitude,
            cliente_info["latitude"], cliente_info["longitude"]
        )
        
        if distancia <= cliente_info["raio_metros"]:
            logger.info(f"Coordenada {latitude}, {longitude} pertence a {cliente_name} (distância: {distancia:.2f}m)")
            return cliente_name
    
    logger.warning(f"Coordenada {latitude}, {longitude} não pertence a nenhum cliente")
    return None

# ============================================================================
# FUNÇÕES DE EXTRAÇÃO DE TAGS
# ============================================================================

def extract_client_tag(text: str) -> list[str]:
    """
    Extrai tags de cliente do formato #Oia NomeCliente.
    Retorna uma lista de clientes encontrados.
    """
    # Procura por padrão: #Oia NomeCliente
    pattern = r'#Oia\s+(\w+)'
    matches = re.findall(pattern, text, re.IGNORECASE)
    
    if matches:
        logger.info(f"Tags encontradas: {matches}")
    
    return matches

def validate_client_tag(tag: str) -> bool:
    """
    Valida se o tag corresponde a um cliente conhecido.
    """
    for cliente_name in CLIENTES_OURILANDIA.keys():
        if cliente_name.lower() == f"oia {tag}".lower():
            return True
    return False

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
        lat_match = abs(coord["latitude"] - latitude) < 0.0001
        lon_match = abs(coord["longitude"] - longitude) < 0.0001
        time_match = coord["timestamp"] == timestamp
        
        if lat_match and lon_match and time_match:
            logger.info(f"Coordenada duplicada detectada: {latitude}, {longitude} em {timestamp}")
            return True
    
    return False

def add_coordinate(latitude: float, longitude: float, timestamp: str, cliente: str | None = None) -> bool:
    """Adiciona uma nova coordenada à lista (se não for duplicada)."""
    if coordinate_exists(latitude, longitude, timestamp):
        logger.info("Ignorando coordenada duplicada")
        return False
    
    coords_list = load_coordinates()
    
    new_coord = {
        "latitude": latitude,
        "longitude": longitude,
        "timestamp": timestamp,
        "cliente": cliente,
        "id": len(coords_list) + 1
    }
    
    coords_list.append(new_coord)
    return save_coordinates(coords_list)

# ============================================================================
# FUNÇÕES DE MAPA
# ============================================================================

def generate_map() -> bool:
    """Gera um mapa interativo com todas as coordenadas agrupadas por cliente."""
    try:
        import folium
        
        coords_list = load_coordinates()
        
        if not coords_list:
            logger.warning("Nenhuma coordenada para gerar mapa")
            return False
        
        # Filtra apenas coordenadas com cliente definido
        coords_com_cliente = [c for c in coords_list if c.get("cliente")]
        
        if not coords_com_cliente:
            logger.warning("Nenhuma coordenada com cliente para gerar mapa")
            return False
        
        # Calcula o centro do mapa
        lats = [c["latitude"] for c in coords_com_cliente]
        lons = [c["longitude"] for c in coords_com_cliente]
        center_lat = sum(lats) / len(lats)
        center_lon = sum(lons) / len(lons)
        
        # Cria o mapa
        mapa = folium.Map(
            location=[center_lat, center_lon],
            zoom_start=13,
            tiles="OpenStreetMap"
        )
        
        # Agrupa coordenadas por cliente
        coords_por_cliente = {}
        for coord in coords_com_cliente:
            cliente = coord.get("cliente")
            if cliente not in coords_por_cliente:
                coords_por_cliente[cliente] = []
            coords_por_cliente[cliente].append(coord)
        
        # Adiciona marcadores para cada cliente
        for cliente_name, coords in coords_por_cliente.items():
            if cliente_name in CLIENTES_OURILANDIA:
                cor = CLIENTES_OURILANDIA[cliente_name]["cor"]
                
                for coord in coords:
                    folium.Marker(
                        location=[coord["latitude"], coord["longitude"]],
                        popup=f"<b>{cliente_name}</b><br>ID: {coord['id']}<br>Data: {coord['timestamp']}<br>Lat: {coord['latitude']:.4f}<br>Lon: {coord['longitude']:.4f}",
                        tooltip=f"{cliente_name} - {coord['timestamp']}",
                        icon=folium.Icon(color=cor, icon="info-sign")
                    ).add_to(mapa)
        
        # Adiciona legenda com contagem
        legend_html = '''
        <div style="position: fixed; 
                    bottom: 50px; right: 50px; width: 250px; height: auto; 
                    background-color: white; border:2px solid grey; z-index:9999; 
                    font-size:14px; padding: 10px">
            <b>Clientes - Ourilândia</b><br>
        '''
        
        for cliente_name, coords in sorted(coords_por_cliente.items()):
            cor = CLIENTES_OURILANDIA[cliente_name]["cor"]
            contagem = len(coords)
            legend_html += f'<i style="background:{cor}; width: 18px; height: 18px; float: left; margin-right: 8px; border-radius: 50%;"></i>{cliente_name}: {contagem}<br>'
        
        legend_html += '</div>'
        
        mapa.get_root().html.add_child(folium.Element(legend_html))
        
        # Salva como HTML
        mapa.save(MAPA_FILE)
        logger.info(f"Mapa HTML gerado: {MAPA_FILE} com {len(coords_com_cliente)} pontos")
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
    
    if mapa_timer is not None:
        mapa_timer.cancel()
        logger.info("Timer anterior cancelado")
    
    logger.info(f"Agendando geração de mapa em {delay} segundos...")
    
    async def send_map_after_delay():
        await asyncio.sleep(delay)
        logger.info("Gerando mapa após delay de 60 segundos...")
        
        if generate_map() and os.path.exists(MAPA_FILE):
            try:
                coords_list = load_coordinates()
                coords_com_cliente = [c for c in coords_list if c.get("cliente")]
                
                with open(MAPA_FILE, 'rb') as mapa_file:
                    await context.bot.send_document(
                        chat_id=RELATORIO_GROUP_ID,
                        document=mapa_file,
                        caption=f"🗺️ Mapa Ourilândia Atualizado!\n\n"
                                f"📊 Total de pontos: {len(coords_com_cliente)}\n"
                                f"⏰ Atualizado em: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
                    )
                logger.info("Mapa enviado para o grupo de relatórios")
            except Exception as e:
                logger.error(f"Erro ao enviar mapa para o grupo: {e}")
    
    mapa_timer = asyncio.create_task(send_map_after_delay())

# ============================================================================
# FUNÇÕES DE OCR E PROCESSAMENTO
# ============================================================================

def preprocess_image_for_ocr(image_path: str) -> Image.Image:
    """Abre a imagem sem pré-processamento agressivo."""
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
    """Busca por data e hora no texto."""
    month_map = {
        'jan': 1, 'fev': 2, 'mar': 3, 'abr': 4, 'mai': 5, 'jun': 6, 
        'jul': 7, 'ago': 8, 'set': 9, 'out': 10, 'nov': 11, 'dez': 12
    }

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

def extract_data_from_image(image_path: str, max_retries: int = 2) -> tuple[datetime | None, str | None, float | None, float | None, list[str]]:
    """
    Extrai data/hora, coordenadas e tags de cliente da imagem com retry.
    
    Returns:
        Tupla (dt_object, coords_str, latitude, longitude, tags)
    """
    dt_object = None
    coords_str = None
    latitude = None
    longitude = None
    tags = []
    
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
            
            # Procura por tags de cliente
            tags = extract_client_tag(cleaned_text)
            
            # Procura por coordenadas
            coords_match = re.search(r'(-?\d+[\.,]\d+[NSns])\s+(-?\d+[\.,]\d+[EWLOwvloe])', cleaned_text, re.IGNORECASE)
            if coords_match:
                coords_str_raw = f"{coords_match.group(1)} {coords_match.group(2)}"
                logger.info(f"Coordenadas GPS encontradas (bruto) - Tentativa {attempt + 1}: {coords_str_raw}")
                
                parsed_coords = parse_coordinates(coords_str_raw)
                if parsed_coords:
                    latitude, longitude = parsed_coords
                    coords_str = f"{latitude:.4f}, {longitude:.4f}"
                    logger.info(f"Coordenadas processadas com sucesso na tentativa {attempt + 1}")
                    break
            
            if dt_object or coords_str or tags:
                logger.info(f"Dados extraídos com sucesso na tentativa {attempt + 1}")
                break
        
        except Exception as e:
            logger.error(f"Erro na tentativa {attempt + 1}: {e}")
            if attempt < max_retries:
                logger.info(f"Tentando novamente...")
            continue
    
    return dt_object, coords_str, latitude, longitude, tags

# ============================================================================
# HANDLERS DO BOT
# ============================================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Envia uma mensagem quando o comando /start é emitido."""
    await update.message.reply_text(
        "Olá! 👋\n\n"
        "Envie uma foto com data, hora, coordenadas e tag de cliente para que eu possa extrair as informações.\n\n"
        "Formato esperado:\n"
        "Linha 1: Data e Hora\n"
        "Linha 2: Coordenadas (ou tag de cliente)\n"
        "Linha 3: Tag de cliente (#Oia NomeCliente)\n\n"
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
    tags = []
    cliente_definido = None
    is_duplicate = False
    ignorada = False

    try:
        await file.download_to_drive(file_path)
        
        # Extrai dados com retry
        dt_object, coords_str, latitude, longitude, tags = extract_data_from_image(file_path, max_retries=2)

        # Hierarquia de definição de cliente
        if len(tags) == 1:
            # Exatamente 1 tag: use o tag como cliente
            tag_cliente = f"Oia {tags[0]}"
            if tag_cliente in CLIENTES_OURILANDIA:
                cliente_definido = tag_cliente
                logger.info(f"Cliente definido por tag: {cliente_definido}")
            else:
                logger.warning(f"Tag inválido: {tag_cliente}")
                ignorada = True
        elif len(tags) > 1:
            # Mais de 1 tag: use as coordenadas
            logger.warning(f"Múltiplos tags encontrados: {tags}. Usando coordenadas para definir cliente.")
            if latitude and longitude:
                cliente_definido = find_cliente_by_geofence(latitude, longitude)
        else:
            # Sem tag: use as coordenadas
            if latitude and longitude:
                cliente_definido = find_cliente_by_geofence(latitude, longitude)

        # Se encontrou coordenadas e cliente, adiciona à lista
        if coords_str and cliente_definido and dt_object and not ignorada:
            timestamp = dt_object.strftime('%d/%m/%Y %H:%M:%S')
            
            if not add_coordinate(latitude, longitude, timestamp, cliente_definido):
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
    if ignorada:
        reply_text = "⚠️ Tag de cliente inválido. Foto ignorada."
    elif is_duplicate:
        reply_text = "⚠️ Esta foto é duplicada (mesma data, hora e localização). Ignorada."
    elif cliente_definido and coords_str and dt_object:
        reply_parts = ["✅ Dados extraídos da imagem! 📸"]
        reply_parts.append(f"🕐 Data e Hora: {dt_object.strftime('%d/%m/%Y %H:%M:%S')}")
        reply_parts.append(f"📍 Coordenadas: {coords_str}")
        reply_parts.append(f"👥 Cliente: {cliente_definido}")
        reply_text = "\n".join(reply_parts)
    else:
        reply_text = "❌ Não consegui extrair dados completos da imagem (data, hora, coordenadas e cliente). Foto ignorada."
            
    await update.message.reply_text(reply_text)
    
    # Se encontrou tudo, agenda geração de mapa
    if cliente_definido and coords_str and not is_duplicate and not ignorada:
        logger.info("Agendando geração de mapa com delay de 60 segundos...")
        await schedule_map_generation(context, delay=60)

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