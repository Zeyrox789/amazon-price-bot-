import os
import logging
import sqlite3
import json
import smtplib
import email.message
from typing import Dict, Optional
from datetime import datetime
import asyncio
import aiohttp
from bs4 import BeautifulSoup
from fake_useragent import UserAgent
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import discord
from discord.ext import commands
from dotenv import load_dotenv

# Configuration du proxy pour PythonAnywhere
PYTHONANYWHERE = "pythonanywhere.com" in os.environ.get("HOSTNAME", "")
if PYTHONANYWHERE:
    os.environ["http_proxy"] = "http://proxy.server:3128"
    os.environ["https_proxy"] = "http://proxy.server:3128"
    import ssl
    ssl._create_default_https_context = ssl._create_unverified_context

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('price_monitor.log'),
        logging.StreamHandler()
    ]
)

class AmazonPriceMonitor(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.presences = True
        super().__init__(intents=intents)
        
        load_dotenv()
        self.discord_token = os.getenv('DISCORD_TOKEN')
        if not self.discord_token:
            raise ValueError(" Token Discord non trouvé dans le fichier .env")
            
        self.discord_channel_id = os.getenv('DISCORD_CHANNEL_ID')
        if not self.discord_channel_id:
            raise ValueError(" ID du canal Discord non trouvé dans le fichier .env")
        self.discord_channel_id = int(self.discord_channel_id)
        
        # Configuration email
        self.email_address = os.getenv('EMAIL_ADDRESS')
        self.email_password = os.getenv('EMAIL_PASSWORD')
        self.smtp_server = os.getenv('SMTP_SERVER')
        self.smtp_port = int(os.getenv('SMTP_PORT'))
        
        self.ua = UserAgent()
        self.init_database()
        self.load_products()
        
        # Créer le scheduler
        self.scheduler = AsyncIOScheduler()
        
    def init_database(self):
        """Initialise la base de données SQLite"""
        self.conn = sqlite3.connect('prices.db')
        self.cursor = self.conn.cursor()
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS price_history (
                product_name TEXT,
                price REAL,
                timestamp DATETIME,
                url TEXT
            )
        ''')
        self.conn.commit()

    def load_products(self):
        """Charge la configuration des produits depuis le fichier JSON"""
        with open('products.json', 'r') as f:
            self.config = json.load(f)
        self.products = self.config['products']
        self.settings = self.config['settings']

    def get_amazon_price(self, url: str) -> Optional[float]:
        """Récupère le prix d'un produit sur Amazon"""
        headers = {
            'User-Agent': self.ua.random,
            'Accept-Language': 'fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7'
        }
        
        try:
            response = requests.get(url, headers=headers)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                price_element = soup.find('span', class_='a-offscreen')
                if price_element:
                    price_str = price_element.text.replace('€', '').replace(',', '.').strip()
                    return float(price_str)
            return None
        except Exception as e:
            logging.error(f"Erreur lors de la récupération du prix: {str(e)}")
            return None

    def check_price_error(self, product: Dict, current_price: float) -> bool:
        """Vérifie si le prix actuel est anormalement bas"""
        threshold = product['normal_price'] * (1 - product['threshold'])
        return current_price < threshold

    def save_price(self, product_name: str, price: float, url: str):
        """Enregistre le prix dans la base de données"""
        self.cursor.execute(
            'INSERT INTO price_history (product_name, price, timestamp, url) VALUES (?, ?, ?, ?)',
            (product_name, price, datetime.now(), url)
        )
        self.conn.commit()

    async def send_discord_alert(self, product: Dict, price: float):
        """Envoie une alerte Discord"""
        message = (
            " ALERTE PRIX BAS!\n\n"
            f"Produit: {product['name']}\n"
            f"Prix actuel: {price}€\n"
            f"Prix normal: {product['normal_price']}€\n"
            f"Économie: {product['normal_price'] - price:.2f}€\n\n"
            f"Lien: {product['url']}"
        )
        channel = self.get_channel(self.discord_channel_id)
        if channel:
            await channel.send(message)
        else:
            logging.error(f"Canal Discord non trouvé: {self.discord_channel_id}")

    def send_email_alert(self, product: Dict, price: float):
        """Envoie une alerte par email"""
        msg = MIMEMultipart()
        msg['From'] = self.email_address
        msg['To'] = self.email_address
        msg['Subject'] = f" Alerte Prix Bas - {product['name']}"

        body = (
            f"Une baisse de prix importante a été détectée !\n\n"
            f"Produit: {product['name']}\n"
            f"Prix actuel: {price}€\n"
            f"Prix normal: {product['normal_price']}€\n"
            f"Économie: {product['normal_price'] - price:.2f}€\n\n"
            f"Lien: {product['url']}\n\n"
            f"Ne manquez pas cette opportunité !"
        )
        
        msg.attach(MIMEText(body, 'plain'))

        try:
            server = smtplib.SMTP(self.smtp_server, self.smtp_port)
            server.starttls()
            server.login(self.email_address, self.email_password)
            server.send_message(msg)
            server.quit()
            logging.info(f"Email d'alerte envoyé pour {product['name']}")
        except Exception as e:
            logging.error(f"Erreur lors de l'envoi de l'email: {str(e)}")

    async def monitor_prices(self):
        """Fonction principale de surveillance des prix"""
        logging.info("==========================================")
        logging.info(" DÉBUT DE LA VÉRIFICATION DES PRIX...")
        logging.info(f" {datetime.now().strftime('%H:%M:%S')}")
        logging.info("==========================================")
        
        for product in self.products:
            try:
                logging.info(f"Vérification de {product['name']}...")
                current_price = self.get_amazon_price(product['url'])
                if current_price:
                    self.save_price(product['name'], current_price, product['url'])
                    
                    if self.check_price_error(product, current_price):
                        logging.info(f" PRIX BAS DÉTECTÉ pour {product['name']}: {current_price}€ (Normal: {product['normal_price']}€)")
                        await self.send_discord_alert(product, current_price)
                        self.send_email_alert(product, current_price)
                    else:
                        logging.info(f" Prix normal pour {product['name']}: {current_price}€")
                else:
                    logging.warning(f" Impossible de récupérer le prix pour {product['name']}")
                
                await asyncio.sleep(2)  # Petit délai entre chaque produit
            except Exception as e:
                logging.error(f" Erreur lors du traitement de {product['name']}: {str(e)}")
        
        logging.info("==========================================")
        logging.info(" FIN DE LA VÉRIFICATION")
        logging.info("==========================================")

    async def setup_hook(self):
        """Configure le bot au démarrage"""
        try:
            self.scheduler.add_job(
                self.monitor_prices,
                'interval',
                seconds=self.settings['check_interval']
            )
            self.scheduler.start()
            logging.info(" Scheduler démarré avec succès")
        except Exception as e:
            logging.error(f" Erreur lors du démarrage du scheduler: {str(e)}")
            
    async def on_ready(self):
        """Appelé quand le bot est connecté et prêt"""
        logging.info(f" Bot connecté en tant que {self.user}")
        try:
            channel = self.get_channel(self.discord_channel_id)
            if channel:
                await channel.send(" Bot de surveillance des prix Amazon démarré !")
                logging.info(f" Message envoyé sur le canal {channel.name}")
            else:
                logging.error(f" Canal Discord non trouvé: {self.discord_channel_id}")
        except Exception as e:
            logging.error(f" Erreur lors de l'envoi du message Discord: {str(e)}")

async def main():
    bot = AmazonPriceMonitor()
    async with bot:
        try:
            await bot.start(os.getenv('DISCORD_TOKEN'))
        except Exception as e:
            logging.error(f" Erreur lors de la connexion au serveur Discord: {str(e)}")

if __name__ == "__main__":
    asyncio.run(main())
