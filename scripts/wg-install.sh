#!/usr/bin/env bash
# wg-install.sh — bootstrap a WireGuard server on a fresh Ubuntu/Debian VPS.
#
# Usage (as root):
#   curl -fsSL https://raw.githubusercontent.com/jupiteriaa55/chronicle-vpn/main/scripts/wg-install.sh | bash
#   # or after cloning the repo:
#   sudo bash scripts/wg-install.sh
#
# What it does:
#   * Installs wireguard, qrencode, iptables-persistent.
#   * Generates server keypair → /etc/wireguard/{server.key,server.pub}.
#   * Writes a starter /etc/wireguard/wg0.conf with no peers (the bot manages them).
#   * Enables IPv4 forwarding and NAT masquerade on the egress interface.
#   * Opens UDP/51820 in ufw (if installed).
#   * Enables and starts wg-quick@wg0.
#   * Prints the values you need to put into the bot's .env (server pubkey, host).
#
# It does NOT install the bot itself; deploy that separately (e.g. with docker compose).
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Run as root (sudo bash $0)" >&2
  exit 1
fi

WG_PORT="${WG_PORT:-51820}"
WG_NETWORK="${WG_NETWORK:-10.13.13.0/24}"
WG_INTERFACE="${WG_INTERFACE:-wg0}"
EGRESS_IFACE="${EGRESS_IFACE:-$(ip route show default | awk '/default/ {print $5; exit}')}"

echo "==> Installing packages…"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y wireguard wireguard-tools qrencode iptables iptables-persistent

echo "==> Enabling IP forwarding…"
sed -i 's/^#\?net.ipv4.ip_forward.*/net.ipv4.ip_forward=1/' /etc/sysctl.conf
sysctl -p >/dev/null

mkdir -p /etc/wireguard
cd /etc/wireguard
umask 077

if [[ ! -f server.key ]]; then
  echo "==> Generating server keypair…"
  wg genkey | tee server.key | wg pubkey > server.pub
fi
SERVER_PRIV=$(cat server.key)
SERVER_PUB=$(cat server.pub)

# Compute the .1 host of WG_NETWORK as the server iface address
SERVER_IP="${WG_NETWORK%/*}"
SERVER_IP="${SERVER_IP%.*}.1"
PREFIX="${WG_NETWORK#*/}"

if [[ ! -f "${WG_INTERFACE}.conf" ]]; then
  echo "==> Writing initial ${WG_INTERFACE}.conf…"
  cat > "${WG_INTERFACE}.conf" <<EOF
[Interface]
Address = ${SERVER_IP}/${PREFIX}
ListenPort = ${WG_PORT}
PrivateKey = ${SERVER_PRIV}
SaveConfig = false
PostUp = iptables -A FORWARD -i %i -j ACCEPT; iptables -A FORWARD -o %i -j ACCEPT; iptables -t nat -A POSTROUTING -o ${EGRESS_IFACE} -j MASQUERADE
PostDown = iptables -D FORWARD -i %i -j ACCEPT; iptables -D FORWARD -o %i -j ACCEPT; iptables -t nat -D POSTROUTING -o ${EGRESS_IFACE} -j MASQUERADE
EOF
fi

echo "==> Opening firewall (best effort)…"
if command -v ufw >/dev/null 2>&1; then
  ufw allow "${WG_PORT}/udp" || true
fi

echo "==> Enabling wg-quick@${WG_INTERFACE}…"
systemctl enable --now "wg-quick@${WG_INTERFACE}"

# Public IP guess
PUBLIC_IP=$(curl -fsSL ifconfig.me || hostname -I | awk '{print $1}')

cat <<INFO

================================================================
WireGuard server is up on UDP/${WG_PORT} (interface ${WG_INTERFACE}).
Egress NAT through: ${EGRESS_IFACE}
Server public IP : ${PUBLIC_IP}

Put these into the bot's .env :

  WG_SERVER_HOST=${PUBLIC_IP}
  WG_SERVER_PORT=${WG_PORT}
  WG_SERVER_PUBKEY=${SERVER_PUB}
  WG_INTERFACE=${WG_INTERFACE}
  WG_NETWORK=${WG_NETWORK}
  WG_CONFIG_PATH=/etc/wireguard/${WG_INTERFACE}.conf

If running the bot on a SEPARATE host, also set:
  WG_RELOAD_MODE=ssh
  WG_SSH_USER=root
  WG_SSH_KEY=/path/to/private/key

If running the bot on this SAME host, set:
  WG_RELOAD_MODE=wg-quick
================================================================
INFO
