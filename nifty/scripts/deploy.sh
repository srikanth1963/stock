#!/bin/bash
# SMB Algo — VM Deployment Script
# Run this once on the GCP VM after uploading the zip
# Usage: bash /opt/smb-algo/scripts/deploy.sh

set -e
echo ""
echo "========================================"
echo "  SMB Algo Platform — Deployment Script"
echo "========================================"
echo ""

APP_DIR="/opt/smb-algo"
VENV="$APP_DIR/venv"
USER="srikanth"

# ── 1. Set permissions ────────────────────────────────────────────────────────
echo "[ 1/6 ] Setting permissions..."
sudo chown -R $USER:$USER $APP_DIR
chmod +x $APP_DIR/scripts/*.sh 2>/dev/null || true

# ── 2. Create data directory ──────────────────────────────────────────────────
echo "[ 2/6 ] Creating data directory..."
mkdir -p $APP_DIR/data
touch $APP_DIR/data/.gitkeep

# ── 3. Copy .env if not exists ────────────────────────────────────────────────
echo "[ 3/6 ] Checking .env..."
if [ ! -f "$APP_DIR/.env" ]; then
    cp $APP_DIR/.env.example $APP_DIR/.env
    echo "  ⚠  .env created from template — fill in your credentials!"
else
    echo "  ✓  .env already exists"
fi

# ── 4. Install systemd service ────────────────────────────────────────────────
echo "[ 4/6 ] Installing systemd service..."
sudo cp $APP_DIR/scripts/smb-algo.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable smb-algo
echo "  ✓  Service installed and enabled"

# ── 5. Configure Nginx ────────────────────────────────────────────────────────
echo "[ 5/6 ] Configuring Nginx..."
sudo cp $APP_DIR/scripts/nginx.conf /etc/nginx/sites-available/smb-algo
sudo ln -sf /etc/nginx/sites-available/smb-algo /etc/nginx/sites-enabled/smb-algo
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl restart nginx
echo "  ✓  Nginx configured"

# ── 6. Start app ──────────────────────────────────────────────────────────────
echo "[ 6/6 ] Starting SMB Algo..."
sudo systemctl start smb-algo
sleep 3
sudo systemctl status smb-algo --no-pager | head -20

echo ""
echo "========================================"
echo "  Deployment complete!"
echo ""
echo "  Next step: Set up SSL certificate"
echo "  Run: sudo certbot --nginx -d trading.smbenablers.com"
echo "========================================"
