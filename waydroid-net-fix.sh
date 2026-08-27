#!/bin/bash
# Waydroid network fix script
# Sets up IP, route, NAT, firewall, DNS, and Android netd network in one go
#
# Usage: sudo ./waydroid-net-fix.sh
#
# Run after every `waydroid session start` (or once after boot).

set -e

CONTAINER_IP="192.168.240.112"
HOST_IP="192.168.240.1"
SUBNET="192.168.240.0/24"
DNS1="8.8.8.8"
DNS2="1.1.1.1"

if [ "$EUID" -ne 0 ]; then
    echo "Run with sudo"
    exit 1
fi

echo "[1/6] Checking Waydroid is running..."
if ! waydroid status 2>/dev/null | grep -q "Container:.*RUNNING"; then
    echo "ERROR: Waydroid container not running. Start it with:"
    echo "  sudo systemctl start waydroid-container"
    echo "  waydroid session start &"
    exit 1
fi

echo "[2/6] Setting up host firewall (allow forwarding + NAT)..."
sysctl -w net.ipv4.ip_forward=1 > /dev/null
iptables -I FORWARD -i waydroid0 -j ACCEPT 2>/dev/null || true
iptables -I FORWARD -o waydroid0 -j ACCEPT 2>/dev/null || true
# MASQUERADE rule (idempotent check)
if ! iptables -t nat -C POSTROUTING -s "$SUBNET" -j MASQUERADE 2>/dev/null; then
    iptables -t nat -A POSTROUTING -s "$SUBNET" -j MASQUERADE
fi

echo "[3/6] Assigning IP to container..."
waydroid shell -- ip addr add "$CONTAINER_IP/24" dev eth0 2>/dev/null || echo "  (IP already set)"
waydroid shell -- ip route add default via "$HOST_IP" dev eth0 2>/dev/null || echo "  (route already set)"

echo "[4/6] Configuring Android netd network..."
waydroid shell -- ndc network create 100 2>/dev/null || echo "  (network 100 exists)"
waydroid shell -- ndc network interface add 100 eth0 2>/dev/null || echo "  (interface added)"
waydroid shell -- ndc network route add 100 eth0 0.0.0.0/0 "$HOST_IP" 2>/dev/null || echo "  (route added)"
waydroid shell -- ndc network default set 100

echo "[5/6] Setting DNS..."
waydroid shell -- setprop net.dns1 "$DNS1"
waydroid shell -- setprop net.dns2 "$DNS2"
waydroid shell -- setprop net.eth0.dns1 "$DNS1"
waydroid shell -- setprop net.eth0.dns2 "$DNS2"
# For Android 10+ with DnsResolver service
waydroid shell -- ndc resolver setnetdns 100 "" "$DNS1" "$DNS2" 2>/dev/null || \
    waydroid shell -- ndc resolver setresolverconfiguration 100 "$DNS1" "$DNS2" 2>/dev/null || \
    echo "  (ndc resolver API not supported, falling back to props only)"

echo "[6/6] Testing connectivity..."
sleep 1
if waydroid shell -- ping -c 1 -W 3 8.8.8.8 > /dev/null 2>&1; then
    echo "  ✓ Internet IP reachable"
else
    echo "  ✗ Cannot reach 8.8.8.8 — check host firewall"
fi

if waydroid shell -- getent hosts google.com > /dev/null 2>&1; then
    echo "  ✓ DNS working"
elif waydroid shell -- ping -c 1 -W 3 google.com > /dev/null 2>&1; then
    echo "  ✓ DNS working"
else
    echo "  ✗ DNS not resolving — apps may show 'check network settings'"
    echo "    Try: sudo iptables -t nat -A PREROUTING -i waydroid0 -p udp --dport 53 -j DNAT --to-destination $DNS1:53"
fi

echo ""
echo "Done. Now connect ADB:"
echo "  adb connect $CONTAINER_IP:5555"
