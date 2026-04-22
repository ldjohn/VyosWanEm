# VyOS WANEM Controller

Small Flask GUI to:
- set per-interface delay
- apply delay to all interfaces
- push baseline WANEM config
- view RX/TX throughput

## Run

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
export VYOS_API_KEY='your-api-key'
python3 app.py
