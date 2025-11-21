import logging
import os
from datetime import datetime
from PIL import Image
from PIL.ExifTags import TAGS
import json # Importamos a biblioteca JSON

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ... (configuração do logging igual) ...
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- NOVA FUNÇÃO "ESPIÃ" ---
async def spy_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Registra TODAS as atualizações recebidas para depuração."""
    # Converte o objeto 'update' para um dicionário e depois para uma string JSON formatada
    update_as_dict = update.to_dict()
    update_as_json = json.dumps(update_as_dict, indent=2)
    logger.info(f"--- NOVA ATUALIZAÇÃO RECEBIDA ---\n{update_as_json}")
    # Esta linha é importante para garantir que outros handlers também sejam processados
    return

# Função para o comando /start (sem alterações)
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Olá! Me adicione a um grupo e envie uma foto como 'Arquivo' para que eu possa ler a data e hora de captura.")

# Função para processar fotos (sem alterações)
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # ... (o resto da função handle_photo continua exatamente igual) ...
    if update.message.chat.type == 'private':
        await update.message.reply_text("Por favor, use esta função em um grupo.")
        return

    document = update.message.document
    if not document or not document.mime_type.startswith('image/'):
        if update.message.photo:
            await update.message.reply_text("Por favor, envie a imagem como 'Arquivo' ou 'Documento' para que eu possa ler os metadados.")
        return

    photo_file = await document.get_file()
    file_path = f"temp_{photo_file.file_id}.jpg"
    try:
        await photo_file.download_to_drive(file_path)
        img = Image.open(file_path)
        exif_data = img.getexif()
        date_time_original = None
        if 36867 in exif_data:
            date_time_original = exif_data[36867]
            dt_object = datetime.strptime(date_time_original, '%Y:%m:%d %H:%M:%S')
            reply_text = f"Foto recebida! 📸\nData e Hora da Captura: {dt_object.strftime('%d/%m/%Y %H:%M:%S')}"
            logger.info(f"Data extraída da foto: {dt_object}")
        else:
            reply_text = "Foto recebida, mas não consegui encontrar a data e hora de captura nos metadados (dados EXIF). 😕"
    except Exception as e:
        logger.error(f"Erro ao processar a imagem: {e}")
        reply_text = "Ocorreu um erro ao tentar ler os dados desta foto."
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)
    await update.message.reply_text(reply_text)

def main() -> None:
    token = os.environ.get("TELEGRAM_TOKEN")
    if not token:
        logger.error("O TELEGRAM_TOKEN não foi configurado nas variáveis de ambiente!")
        return

    application = Application.builder().token(token).build()

    # --- ADICIONANDO O HANDLER ESPIÃO ---
    # O 'group=-1' garante que este handler rode ANTES de todos os outros.
    application.add_handler(MessageHandler(filters.ALL, spy_handler), group=-1)

    # Handlers originais
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.Document.IMAGE, handle_photo))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    logger.info("Bot iniciado e escutando...")
    application.run_polling()

if __name__ == "__main__":
    main()
