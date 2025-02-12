# Amazon Price Monitor Bot

Un bot qui surveille les prix sur Amazon pour détecter les erreurs de prix sur les produits high-tech et jeux vidéo.

## Fonctionnalités
- Surveillance continue des prix Amazon
- Détection des erreurs de prix
- Notifications via Discord et email
- Stockage des données dans SQLite
- Exécution 24/7 avec gestion des pauses

## Installation
1. Cloner le repository
2. Installer les dépendances : `pip install -r requirements.txt`
3. Créer un fichier `.env` avec vos informations :
```
# Discord
DISCORD_TOKEN=your_discord_bot_token
DISCORD_CHANNEL_ID=your_channel_id

# Email (Gmail)
EMAIL_ADDRESS=lucasgugliardi6@gmail.com
EMAIL_PASSWORD=your_app_specific_password
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
```

## Configuration Discord
1. Créez une application Discord sur https://discord.com/developers/applications
2. Créez un bot et récupérez son token
3. Invitez le bot sur votre serveur Discord
4. Copiez l'ID du canal où vous voulez recevoir les alertes

## Configuration Email
1. Activez l'authentification à deux facteurs sur votre compte Gmail
2. Générez un mot de passe d'application spécifique pour le bot
3. Utilisez ce mot de passe dans le fichier `.env`

## Configuration des produits
- Ajoutez vos produits à surveiller dans le fichier `products.json`
- Ajustez les seuils de prix dans la configuration

## Lancement
```bash
python price_monitor.py
```

Le bot vérifiera les prix toutes les 5 minutes par défaut et vous alertera sur Discord et par email si une baisse de prix significative est détectée.
