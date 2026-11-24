#!/usr/bin/env bash
# One-time setup of a small Ubuntu server (e.g. Oracle Always Free, 1 GB RAM) for Rimy.
# Safe to run again: every step checks whether it is already done.
set -euo pipefail

# 1. Swap: 1 GB of RAM is not enough to build the image (npm + pip) next to another bot
if ! swapon --show | grep -q /swapfile; then
  sudo fallocate -l 2G /swapfile
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile
  sudo swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
fi

# 2. Docker with the compose plugin (from Ubuntu's own repositories)
if ! command -v docker >/dev/null; then
  sudo apt-get update -y
  sudo apt-get install -y docker.io docker-compose-v2
  sudo usermod -aG docker "$USER"
fi

# 3. Oracle images block everything except SSH in iptables: open 80/443 for Caddy (HTTPS for the Mini App)
for port in 80 443; do
  if ! sudo iptables -C INPUT -p tcp --dport "$port" -j ACCEPT 2>/dev/null; then
    sudo iptables -I INPUT 6 -p tcp -m state --state NEW --dport "$port" -j ACCEPT
  fi
done
if command -v netfilter-persistent >/dev/null; then sudo netfilter-persistent save; fi

echo "server ready: $(free -m | awk '/Mem/{print $2" MB RAM"}'), swap $(swapon --show --noheadings | awk '{print $3}')"
