import os
import logging
import sqlite3
import json
import smtplib
import email.message
from typing import Dict, Optional, List
from datetime import datetime
import asyncio
import aiohttp
from bs4 import BeautifulSoup
from fake_useragent import UserAgent
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import discord
from discord.ext import commands
from dotenv import load_dotenv
import requests
import random
import socket

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('price_monitor.log'),
        logging.StreamHandler()
    ]
)

# Configurer le DNS pour utiliser Unbound
socket.setdefaulttimeout(5)  # Définir un délai d'attente pour les connexions

class AmazonPriceMonitor(discord.Client):
    def __init__(self):
        # Configuration des intentions Discord
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        
        # Chargement des variables d'environnement
        load_dotenv()
        self.discord_token = os.getenv('DISCORD_TOKEN')
        if not self.discord_token:
            raise ValueError("Token Discord non trouvé")
            
        self.discord_channel_id = os.getenv('DISCORD_CHANNEL_ID')
        if not self.discord_channel_id:
            raise ValueError("ID du canal Discord non trouvé")
        self.discord_channel_id = int(self.discord_channel_id)
        
        self.discord_channel_id_promo = os.getenv('DISCORD_CHANNEL_ID_PROMO')  # ID du salon pour les promotions
        if not self.discord_channel_id_promo:
            raise ValueError("ID du canal Discord pour les promotions non trouvé")
        self.discord_channel_id_promo = int(self.discord_channel_id_promo)
        
        # Configuration email
        self.email_address = os.getenv('EMAIL_ADDRESS')
        self.email_password = os.getenv('EMAIL_PASSWORD')
        self.smtp_server = os.getenv('SMTP_SERVER')
        self.smtp_port = int(os.getenv('SMTP_PORT'))
        
        self.ua = UserAgent()
        self.proxies = [
            {'http': 'http://proxy1.com:8080'},
            {'http': 'http://proxy2.com:8080'},
            {'http': 'http://proxy3.com:8080'},
            {'http': 'http://votre-nordvpn-proxy:port'},  # Remplacez par l'adresse de votre proxy NordVPN
            {'http': 'http://proxy4.com:8080'},  # Nouveau proxy
            {'http': 'http://proxy5.com:8080'},  # Nouveau proxy
            {'http': 'http://proxy6.com:8080'}   # Nouveau proxy
        ]
        self.init_database()
        self.load_products()
        
        # URLs des catégories à surveiller
        self.category_urls = {
            "PS5 Games": "https://www.amazon.fr/s?k=jeux+ps5&rh=n%3A13910681",
            "Switch Games": "https://www.amazon.fr/s?k=jeux+nintendo+switch&rh=n%3A13910681",
            "Washing Machines": "https://www.amazon.fr/s?k=machine+à+laver&rh=n%3A13910671",
            "Dishwashers": "https://www.amazon.fr/s?k=lave+vaisselle&rh=n%3A13910671",
            "Ovens": "https://www.amazon.fr/s?k=four+encastrable&rh=n%3A13910671",
            "Gaming Laptops": "https://www.amazon.fr/s?k=pc+portable+gaming&rh=n%3A13910711",
            "Gaming PCs": "https://www.amazon.fr/s?k=pc+gamer+fixe&rh=n%3A13910711"
        }

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
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS products (
                name TEXT,
                url TEXT,
                normal_price REAL,
                threshold REAL
            )
        ''')
        self.conn.commit()

    def load_products(self):
        """Charge la configuration des produits depuis le fichier JSON"""
        with open('products.json', 'r') as f:
            self.config = json.load(f)
        self.products = self.config['products']
        self.settings = self.config['settings']

    async def is_url_accessible(self, url: str) -> bool:
        """Vérifie si une URL est accessible"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    return response.status == 200
        except Exception as e:
            logging.error(f"Erreur lors de l'accès à l'URL {url}: {str(e)}")
            return False

    async def log_invalid_urls(self, url: str):
        """Enregistre les URLs invalides dans un fichier"""
        with open('invalid_urls.log', 'a') as f:
            f.write(url + '\n')

    async def scrape_category(self, category_name: str, url: str) -> List[Dict]:
        """Scrape une catégorie Amazon pour trouver tous les produits"""
        products = []
        retries = 5  # Nombre de tentatives de récupération
        for attempt in range(retries):
            if not await self.is_url_accessible(url):
                logging.warning(f"L'URL {url} n'est pas accessible, saut de cette catégorie.")
                await self.log_invalid_urls(url)  # Enregistrer l'URL invalide
                return products
            try:
                headers = {'User-Agent': self.ua.random}
                proxy = random.choice(self.proxies)  # Choisir un proxy aléatoire
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, headers=headers, proxy=proxy['http']) as response:
                        if response.status == 200:
                            soup = BeautifulSoup(await response.text(), 'html.parser')
                            items = soup.find_all('div', {'data-component-type': 's-search-result'})
                            
                            for item in items:
                                try:
                                    name = item.find('span', {'class': 'a-text-normal'}).text.strip()
                                    price_elem = item.find('span', {'class': 'a-price-whole'})
                                    if price_elem:
                                        price_text = price_elem.text.replace(',', '.').replace('€', '').strip()
                                        # Vérifier si le texte du prix peut être converti en float
                                        if price_text.replace('.', '', 1).isdigit():
                                            current_price = float(price_text)
                                            product_url = 'https://www.amazon.fr' + item.find('a', {'class': 'a-link-normal'})['href']
                                            
                                            # Enregistrer le prix normal
                                            await self.save_price(name, current_price, product_url)
                                            
                                            # Vérifier si le prix a chuté
                                            await self.check_price_drop({'name': name, 'url': product_url}, current_price)
                                            
                                            products.append({
                                                'name': name,
                                                'url': product_url,
                                                'normal_price': current_price,
                                                'threshold': 0.8
                                            })
                                        else:
                                            logging.warning(f"Prix non valide pour {name}: {price_text}")
                                except Exception as e:
                                    logging.error(f"Erreur lors du parsing d'un produit: {str(e)}")
                                    continue
                        else:
                            logging.warning(f"Impossible de récupérer le prix pour {category_name} (tentative {attempt + 1})")
                        await asyncio.sleep(10)  # Délai entre chaque tentative
                break  # Sortir de la boucle si la récupération réussit
            except Exception as e:
                logging.error(f"Erreur lors de la récupération des prix: {str(e)}")
                await asyncio.sleep(15 * (attempt + 1))  # Attendre avant de réessayer avec un délai exponentiel
        return products

    async def save_price(self, product_name: str, current_price: float, product_url: str):
        """Enregistre le prix normal d'un produit"""
        with sqlite3.connect('prices.db') as conn:
            c = conn.cursor()
            c.execute('INSERT OR REPLACE INTO products (name, url, normal_price) VALUES (?, ?, ?)',
                      (product_name, product_url, current_price))
            conn.commit()

    async def check_price_drop(self, product: Dict, current_price: float):
        """Vérifie si le prix a chuté de 70 % ou plus"""
        with sqlite3.connect('prices.db') as conn:
            c = conn.cursor()
            c.execute('SELECT normal_price FROM products WHERE name = ?', (product['name'],))
            result = c.fetchone()
            if result:
                normal_price = result[0]
                if current_price <= normal_price * 0.3:  # 70 % de réduction
                    await self.send_discord_alert(product, current_price)
                elif current_price <= normal_price * 0.5:  # 50 % de réduction
                    message = f"Promotion sur {product['name']}: maintenant à {current_price}€ !"
                    await self.send_discord_alert({'name': product['name'], 'message': message}, current_price)
                elif current_price <= normal_price * 0.0:  # 100 % de réduction
                    await self.send_discord_alert(product, current_price)

    async def update_product_list(self):
        """Met à jour la liste des produits depuis toutes les catégories"""
        all_products = []
        for category_name, url in self.category_urls.items():
            logging.info(f"Scraping de la catégorie {category_name}...")
            products = await self.scrape_category(category_name, url)
            all_products.extend(products)
            logging.info(f"Trouvé {len(products)} produits dans {category_name}")
            await asyncio.sleep(10)  # Délai pour éviter d'être bloqué

        # Mise à jour de la base de données
        with sqlite3.connect('prices.db') as conn:
            c = conn.cursor()
            c.execute('DELETE FROM products')  # Supprime les anciens produits
            for product in all_products:
                c.execute('INSERT INTO products VALUES (?, ?, ?, ?)',
                         (product['name'], product['url'], product['normal_price'], product['threshold']))
            conn.commit()

        self.products = all_products
        logging.info(f"Liste des produits mise à jour avec {len(all_products)} produits au total")

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
        if 'message' in product:
            message = product['message']
        else:
            message = (
                " ALERTE PRIX BAS!\n\n"
                f"Produit: {product['name']}\n"
                f"Prix actuel: {price}€\n"
                f"Prix normal: {product['normal_price']}€\n"
                f"Économie: {product['normal_price'] - price:.2f}€\n\n"
                f"Lien: {product['url']}"
            )
        channel = self.get_channel(self.discord_channel_id)
        if price <= product['normal_price'] * 0.5:  # Si c'est une promotion à -50%
            channel = self.get_channel(self.discord_channel_id_promo)
        if channel:
            await channel.send(message)
        else:
            logging.error(f"Canal Discord non trouvé: {self.discord_channel_id}")

    def send_email_alert(self, product: Dict, price: float):
        """Envoie une alerte par email"""
        msg = email.message.Message()
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
        
        msg.attach(email.mime.Text.MIMEText(body, 'plain'))

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
                
                await asyncio.sleep(5)  # Délai de 5 secondes entre les vérifications des prix
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
