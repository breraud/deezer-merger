# Setup VPS

Les commandes ci-dessous supposent un serveur Debian ou Ubuntu vierge avec un utilisateur sudo.

```bash
sudo apt update
sudo apt install -y apache2 python3 python3-venv python3-pip git certbot python3-certbot-apache
sudo a2enmod proxy proxy_http headers ssl

sudo mkdir -p /opt
cd /opt
sudo git clone <URL_DU_DEPOT_GIT> deezer_sync
sudo chown -R $USER:$USER /opt/deezer_sync

cd /opt/deezer_sync
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt

cp .env.example .env
nano .env

sudo cp deploy/deezer.beraud.dev.conf /etc/apache2/sites-available/deezer.beraud.dev.conf
sudo a2ensite deezer.beraud.dev.conf
sudo systemctl reload apache2

sudo cp deploy/deezer-mix.service /etc/systemd/system/deezer-mix.service
sudo systemctl daemon-reload
sudo systemctl enable deezer-mix.service
sudo systemctl start deezer-mix.service
sudo systemctl status deezer-mix.service

sudo certbot --apache -d deezer.beraud.dev
```

## Verification utile

```bash
cd /opt/deezer_sync
.venv/bin/python -m unittest tests.test_deezer_client tests.test_main -v
curl -I http://127.0.0.1:8000/api/status
sudo apache2ctl configtest
```
