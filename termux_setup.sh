#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

pkg update -y
pkg install -y python curl git
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

export BTC_ADDRESS="bc1qt3rukpe7qp737zj5j5xpxxmcqv90cfefhg5e00"
export ETH_ADDRESS="0xA5E6eB31868A85127B1ED82b8C760193356206ED"

python setup_ucash.py

echo "Configuración terminada."
echo 'Para iniciar: python agent.py'
