# Setup VPS

Les commandes ci-dessous supposent un serveur Debian ou Ubuntu vierge avec un utilisateur sudo.

```bash
sudo apt update
sudo apt install -y apache2 docker.io docker-compose-plugin git certbot python3-certbot-apache
sudo a2enmod proxy proxy_http headers ssl

sudo mkdir -p /opt
cd /opt
sudo git clone <URL_DU_DEPOT_GIT> deezer_sync
sudo chown -R $USER:$USER /opt/deezer_sync

cd /opt/deezer_sync
cp .env.example .env
nano .env
touch state.json

sudo systemctl enable --now docker

sudo cp deploy/deezer.beraud.dev.conf /etc/apache2/sites-available/deezer.beraud.dev.conf
sudo a2ensite deezer.beraud.dev.conf
sudo systemctl reload apache2

sudo docker compose up -d --build
sudo docker compose ps

sudo certbot --apache -d deezer.beraud.dev
```

## Verification utile

```bash
cd /opt/deezer_sync
docker compose ps
curl -I http://127.0.0.1:8000/api/status
sudo apache2ctl configtest
sudo docker compose logs --tail=100
```
