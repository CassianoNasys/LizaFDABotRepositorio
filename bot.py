import logging
import os
from datetime import datetime
from PIL import Image
from PIL.ExifTags import TAGS

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Configura o logging para ver erros no Render
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Função para o comando /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Envia uma mensagem de boas-vindas."""
    await update.message.reply_text("Olá! Me adicione a um grupo e envie uma foto como 'Arquivo' para que eu possa ler a data e hora de captura.")

# Função para processar fotos
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Baixa a foto, extrai a data/hora do EXIF e responde."""
    # Verifica se a mensagem veio de um grupo, para evitar spam no privado
    if update.message.chat.type == 'private':
        await update.message.reply_text("Por favor, use esta função em um grupo.")
        return

    # Pega o arquivo da foto (enviado como documento/arquivo)
    document = update.message.document
    if not document or not document.mime_type.startswith('image/'):
        # Se foi enviado como foto comprimida, avisa o usuário
        if update.message.photo:
            await update.message.reply_text("Por favor, envie a imagem como 'Arquivo' ou 'Documento' para que eu possa ler os metadados.")
        return

    photo_file = await document.get_file()
    
    # Define um nome de arquivo temporário
    file_path = f"temp_{photo_file.file_id}.jpg"

    try:
        # Baixa o arquivo
        await photo_file.download_to_drive(file_path)
        
        # Abre a imagem e tenta extrair os dados EXIF
        img = Image.open(file_path)
        exif_data = img.getexif()
        
        date_time_original = None
        # A tag 'DateTimeOriginal' (código 36867) é a que contém a data de captura
        if 36867 in exif_data:
            date_time_original = exif_data[36867]
            # Formata a data para uma leitura mais amigável
            dt_object = datetime.strptime(date_time_original, '%Y:%m:%d %H:%M:%S')
            reply_text = f"Foto recebida! 📸\nData e Hora da Captura: {dt_object.strftime('%d/%m/%Y %H:%M:%S')}"
            
            # Futuramente, aqui você salvaria 'dt_object' em um banco de dados
            logger.info(f"Data extraída da foto: {dt_object}")
        else:
            reply_text = "Foto recebida, mas não consegui encontrar a data e hora de captura nos metadados (dados EXIF). 😕"

    except Exception as e:
        logger.error(f"Erro ao processar a imagem: {e}")
        reply_text = "Ocorreu um erro ao tentar ler os dados desta foto."
    finally:
        # Limpa o arquivo temporário, independentemente do resultado
        if os.path.exists(file_path):
            os.remove(file_path)
            
    await update.message.reply_text(reply_text)

def main() -> None:
    """Inicia o bot."""
    # Pega o token da variável de ambiente que configuramos no Render
    token = os.environ.get("TELEGRAM_TOKEN")
    if not token:
        logger.error("O TELEGRAM_TOKEN não foi configurado nas variáveis de ambiente!")
        return

    # Cria a aplicação do bot
    application = Application.builder().token(token).build()

    # Adiciona os "handlers" (comandos que o bot escuta)
    application.add_handler(CommandHandler("start", start))
    # Este handler reage a 'documentos' que são imagens
    application.add_handler(MessageHandler(filters.Document.IMAGE, handle_photo))
    # Este handler reage a 'fotos' (comprimidas) e instrui o usuário
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    # Inicia o bot
    logger.info("Bot iniciado e escutando...")
    application.run_polling()

if __name__ == "__main__":
    main()
