import os
import json
import re
import time
from typing import Any, Dict, List, Optional

import requests
import urllib3
from flask import Flask, request, render_template_string, jsonify

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "change-me")

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
session = requests.Session()

CONFIG_PATH = os.environ.get("WANEM_CONFIG_PATH", "wanem_config.json")
REQUEST_TIMEOUT = 15

DEFAULT_CONFIG = {
    "vyos_base_url": "https://192.168.68.10",
    "verify_tls": False,
    "max_delay_ms": 2000,
    "default_refresh_seconds": 10,
    "interfaces": [
        {"name": "eth2", "policy": "WANEM-1", "bandwidth": "10mbit", "direction": "egress", "default_delay_ms": 10},
        {"name": "eth3", "policy": "WANEM-2", "bandwidth": "10mbit", "direction": "egress", "default_delay_ms": 10},
        {"name": "eth4", "policy": "WANEM-3", "bandwidth": "10mbit", "direction": "egress", "default_delay_ms": 10},
        {"name": "eth5", "policy": "WANEM-4", "bandwidth": "10mbit", "direction": "egress", "default_delay_ms": 10},
        {"name": "eth6", "policy": "WANEM-5", "bandwidth": "10mbit", "direction": "egress", "default_delay_ms": 10},
        {"name": "eth7", "policy": "WANEM-6", "bandwidth": "10mbit", "direction": "egress", "default_delay_ms": 10}
    ]
}


def load_config() -> Dict[str, Any]:
    if not os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, indent=2)
        return json.loads(json.dumps(DEFAULT_CONFIG))

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    merged = json.loads(json.dumps(DEFAULT_CONFIG))
    merged.update(cfg)
    if "interfaces" not in merged or not isinstance(merged["interfaces"], list):
        merged["interfaces"] = DEFAULT_CONFIG["interfaces"]
    return merged


APP_CONFIG = load_config()
VYOS_BASE_URL = os.environ.get("VYOS_BASE_URL", APP_CONFIG.get("vyos_base_url", "https://192.168.68.10"))
VYOS_API_KEY = os.environ.get("VYOS_API_KEY", "")
VERIFY_TLS = os.environ.get("VYOS_VERIFY_TLS", str(APP_CONFIG.get("verify_tls", False))).lower() in {"1", "true", "yes", "on"}
MAX_DELAY_MS = int(APP_CONFIG.get("max_delay_ms", 2000))
DEFAULT_REFRESH_SECONDS = int(APP_CONFIG.get("default_refresh_seconds", 10))
INTERFACES = APP_CONFIG.get("interfaces", [])

THROUGHPUT_CACHE: Dict[str, Dict[str, float]] = {}

PAGE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>VyOS Latency Control</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 24px; background: #f7f7f9; color: #222; }
    .wrap { max-width: 1350px; margin: 0 auto; }
    .card { background: white; border-radius: 10px; padding: 18px; margin-bottom: 16px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }
    h1 { margin-top: 0; }
    .muted { color: #666; }
    .row { display: grid; grid-template-columns: 100px 120px 1fr 95px 55px 110px 110px 170px; gap: 10px; align-items: center; margin: 12px 0; }
    .hdr { font-weight: bold; border-bottom: 1px solid #ddd; padding-bottom: 8px; }
    input[type=range] { width: 100%; }
    input[type=number] { width: 100%; padding: 7px; box-sizing: border-box; }
    button { padding: 8px 14px; border: 0; border-radius: 6px; cursor: pointer; background: #1967d2; color: white; }
    button.secondary { background: #555; }
    button.warn { background: #0b8043; }
    button:disabled { opacity: 0.6; cursor: wait; }
    code { background: #f2f2f2; padding: 2px 4px; border-radius: 4px; }
    .footer { margin-top: 20px; color: #666; font-size: 0.95em; }
    .status { font-size: 0.95em; }
    .status.ok { color: #137333; }
    .status.err { color: #c5221f; }
    .status.busy { color: #666; }
    .topbar { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
    .metric { font-variant-numeric: tabular-nums; }
  </style>
</head>
<body>
<div class="wrap">
  <div class="card">
    <h1>VyOS Latency Control</h1>
    <div class="muted">Move a slider, release it, and the delay is pushed immediately.</div>
  </div>

  <div class="card">
    <div class="topbar">
      <button id="setup-btn" type="button" class="warn">Setup WANEM</button>
      <label for="set-all-value"><strong>Set all:</strong></label>
      <input id="set-all-value" type="number" min="0" max="{{ max_delay_ms }}" step="1" value="10" style="width:100px; padding:7px; box-sizing:border-box;">
      <button id="set-all-btn" type="button">Apply to all</button>
      <button id="refresh-btn" type="button" class="secondary">Refresh now</button>
      <label for="refresh-seconds"><strong>Refresh:</strong></label>
      <input id="refresh-seconds" type="range" min="1" max="10" step="1" value="{{ default_refresh_seconds }}" oninput="updateRefreshLabel(this.value)" onchange="setRefreshSeconds(this.value)">
      <span id="refresh-label" class="metric">{{ default_refresh_seconds }}s</span>
      <span id="global-status" class="status"></span>
    </div>
  </div>

  <div class="card">
    <div class="row hdr">
      <div>Interface</div>
      <div>Policy</div>
      <div>Delay</div>
      <div>Value</div>
      <div>Unit</div>
      <div>RX Mbps</div>
      <div>TX Mbps</div>
      <div>Status</div>
    </div>

    {% for item in interfaces %}
    <div class="row" data-iface="{{ item.name }}">
      <div><strong>{{ item.name }}</strong></div>
      <div>{{ item.policy }}</div>
      <div>
        <input type="range" min="0" max="{{ max_delay_ms }}" step="1" value="{{ item.delay_ms }}" data-role="slider"
               oninput="syncValue('{{ item.name }}', this.value)"
               onchange="applyRow('{{ item.name }}')">
      </div>
      <div>
        <input id="v-{{ item.name }}" type="number" min="0" max="{{ max_delay_ms }}" step="1" value="{{ item.delay_ms }}" data-role="number"
               oninput="syncSlider('{{ item.name }}', this.value)"
               onchange="applyRow('{{ item.name }}')">
      </div>
      <div>ms</div>
      <div id="rx-{{ item.name }}" class="metric">-</div>
      <div id="tx-{{ item.name }}" class="metric">-</div>
      <div id="status-{{ item.name }}" class="status"></div>
    </div>
    {% endfor %}
  </div>

  <div class="footer">
    Router: <code>{{ base_url }}</code><br>
    Config file: <code>{{ config_path }}</code><br>
    TLS verify: <code>{{ verify_tls }}</code>
  </div>
</div>

<script>
const MAX_DELAY_MS = {{ max_delay_ms }};
let refreshTimer = null;

function rowFor(iface) { return document.querySelector(`[data-iface="${iface}"]`); }
function sliderFor(iface) { return rowFor(iface).querySelector('[data-role="slider"]'); }
function numberFor(iface) { return document.getElementById(`v-${iface}`); }
function statusFor(iface) { return document.getElementById(`status-${iface}`); }
function syncValue(iface, value) { numberFor(iface).value = value; }
function syncSlider(iface, value) { sliderFor(iface).value = value; }
function clampValue(v) {
  const n = parseInt(v, 10);
  if (isNaN(n)) return 0;
  return Math.max(0, Math.min(MAX_DELAY_MS, n));
}
function clampRefreshSeconds(v) {
  const n = parseInt(v, 10);
  if (isNaN(n)) return 10;
  return Math.max(1, Math.min(10, n));
}
function updateRefreshLabel(v) {
  document.getElementById('refresh-label').textContent = `${clampRefreshSeconds(v)}s`;
}
function startRefreshTimer(seconds) {
  if (refreshTimer) clearInterval(refreshTimer);
  refreshTimer = setInterval(async () => {
    await refreshState(false);
    await refreshThroughput(false);
  }, seconds * 1000);
}
function setRefreshSeconds(v) {
  const seconds = clampRefreshSeconds(v);
  document.getElementById('refresh-seconds').value = seconds;
  updateRefreshLabel(seconds);
  startRefreshTimer(seconds);
}
function setBusy(iface, message) { const el = statusFor(iface); el.className = 'status busy'; el.textContent = message; }
function setOk(iface, message) { const el = statusFor(iface); el.className = 'status ok'; el.textContent = message; }
function setErr(iface, message) { const el = statusFor(iface); el.className = 'status err'; el.textContent = message; }
function setRate(iface, rxMbps, txMbps) {
  const rx = document.getElementById(`rx-${iface}`);
  const tx = document.getElementById(`tx-${iface}`);
  rx.textContent = rxMbps == null ? '-' : rxMbps.toFixed(3);
  tx.textContent = txMbps == null ? '-' : txMbps.toFixed(3);
}

async function applyRow(iface) {
  const value = clampValue(numberFor(iface).value);
  numberFor(iface).value = value;
  sliderFor(iface).value = value;
  setBusy(iface, 'Applying...');
  const form = new URLSearchParams();
  form.append('iface', iface);
  form.append('delay_ms', String(value));
  try {
    const res = await fetch('/set-delay', { method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body: form.toString() });
    const data = await res.json();
    if (!res.ok || !data.success) throw new Error(data.error || 'Unknown error');
    setOk(iface, `Applied ${data.delay_ms} ms`);
  } catch (err) {
    setErr(iface, `Failed: ${err.message}`);
  }
}

async function refreshState(showGlobal=false) {
  const globalStatus = document.getElementById('global-status');
  if (showGlobal) { globalStatus.className = 'status busy'; globalStatus.textContent = 'Refreshing...'; }
  try {
    const res = await fetch('/api/state');
    const data = await res.json();
    if (!res.ok || !data.success) throw new Error(data.error || 'Unknown error');
    for (const item of data.interfaces) {
      if (document.getElementById(`v-${item.name}`)) {
        numberFor(item.name).value = item.delay_ms;
        sliderFor(item.name).value = item.delay_ms;
      }
    }
    if (showGlobal) {
      globalStatus.className = 'status ok';
      globalStatus.textContent = 'Refreshed';
      setTimeout(() => { globalStatus.textContent = ''; }, 1500);
    }
  } catch (err) {
    if (showGlobal) {
      globalStatus.className = 'status err';
      globalStatus.textContent = `Refresh failed: ${err.message}`;
    }
  }
}

async function refreshThroughput(showGlobal=false) {
  const globalStatus = document.getElementById('global-status');
  try {
    const res = await fetch('/api/throughput');
    const data = await res.json();
    if (!res.ok || !data.success) throw new Error(data.error || 'Unknown error');
    for (const item of data.interfaces) {
      setRate(item.name, item.rx_mbps, item.tx_mbps);
    }
  } catch (err) {
    if (showGlobal) {
      globalStatus.className = 'status err';
      globalStatus.textContent = `Throughput failed: ${err.message}`;
    }
  }
}

async function applyAll() {
  const globalStatus = document.getElementById('global-status');
  const btn = document.getElementById('set-all-btn');
  const value = clampValue(document.getElementById('set-all-value').value);
  document.getElementById('set-all-value').value = value;
  btn.disabled = true;
  globalStatus.className = 'status busy';
  globalStatus.textContent = `Applying ${value} ms to all...`;
  const form = new URLSearchParams();
  form.append('delay_ms', String(value));
  try {
    const res = await fetch('/set-all-delays', { method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body: form.toString() });
    const data = await res.json();
    if (!res.ok || !data.success) throw new Error(data.error || 'Unknown error');
    const rows = document.querySelectorAll('[data-iface]');
    for (const row of rows) {
      const iface = row.getAttribute('data-iface');
      numberFor(iface).value = value;
      sliderFor(iface).value = value;
      setOk(iface, `Applied ${value} ms`);
    }
    globalStatus.className = 'status ok';
    globalStatus.textContent = `Applied ${value} ms to all interfaces`;
    setTimeout(() => { globalStatus.textContent = ''; }, 2000);
  } catch (err) {
    globalStatus.className = 'status err';
    globalStatus.textContent = `Apply all failed: ${err.message}`;
  } finally {
    btn.disabled = false;
  }
}

async function setupWanem() {
  const globalStatus = document.getElementById('global-status');
  const btn = document.getElementById('setup-btn');
  btn.disabled = true;
  globalStatus.className = 'status busy';
  globalStatus.textContent = 'Pushing WANEM baseline config...';
  try {
    const res = await fetch('/setup-wanem', { method: 'POST' });
    const data = await res.json();
    if (!res.ok || !data.success) throw new Error(data.error || 'Unknown error');
    globalStatus.className = 'status ok';
    globalStatus.textContent = `Setup complete: ${data.count} config ops applied`;
    await refreshState(false);
    await refreshThroughput(false);
    setTimeout(() => { globalStatus.textContent = ''; }, 2500);
  } catch (err) {
    globalStatus.className = 'status err';
    globalStatus.textContent = `Setup failed: ${err.message}`;
  } finally {
    btn.disabled = false;
  }
}

document.getElementById('refresh-btn').addEventListener('click', async () => {
  await refreshState(true);
  await refreshThroughput(false);
});
document.getElementById('set-all-btn').addEventListener('click', applyAll);
document.getElementById('setup-btn').addEventListener('click', setupWanem);
updateRefreshLabel(document.getElementById('refresh-seconds').value);
startRefreshTimer({{ default_refresh_seconds }});
refreshThroughput(false);
</script>
</body>
</html>
"""


def _require_api_config() -> None:
    if not VYOS_API_KEY:
        raise RuntimeError("VYOS_API_KEY is not set")


def vyos_post(endpoint: str, data_obj: Any) -> Dict[str, Any]:
    _require_api_config()
    url = f"{VYOS_BASE_URL.rstrip('/')}/{endpoint.lstrip('/')}"
    payload = {"data": json.dumps(data_obj), "key": VYOS_API_KEY}
    response = session.post(url, data=payload, verify=VERIFY_TLS, timeout=REQUEST_TIMEOUT)
    if response.status_code != 200:
        raise RuntimeError(f"VyOS API HTTP {response.status_code} from {endpoint}: {response.text}")
    result = response.json()
    if not result.get("success", False):
        raise RuntimeError(result.get("error") or f"VyOS API call failed: {endpoint}")
    return result


def vyos_show(path: List[str]) -> str:
    result = vyos_post("show", {"op": "show", "path": path})
    return result.get("data", "") or ""


def parse_delay_to_ms(delay_value: Optional[str]) -> int:
    if delay_value is None:
        return 0
    s = str(delay_value).strip().lower()
    try:
        if s.replace(".", "", 1).isdigit():
            return int(round(float(s)))
    except Exception:
        pass
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(us|ms|secs|sec|s)", s)
    if not m:
        return 0
    value = float(m.group(1))
    unit = m.group(2)
    if unit == "us":
        return int(round(value / 1000.0))
    if unit in {"secs", "sec", "s"}:
        return int(round(value * 1000.0))
    return int(round(value))


def delay_ms_to_vyos(delay_ms: int) -> str:
    delay_ms = max(0, min(MAX_DELAY_MS, int(delay_ms)))
    return str(delay_ms)


def get_qos_config() -> Dict[str, Any]:
    result = vyos_post("retrieve", {"op": "showConfig", "path": ["qos"]})
    return result.get("data", {}) or {}


def get_policy_delay_ms(qos_cfg: Dict[str, Any], policy_name: str) -> int:
    try:
        value = qos_cfg["policy"]["network-emulator"][policy_name].get("delay")
    except Exception:
        return 0
    return parse_delay_to_ms(value)


def get_interface_counters(iface: str) -> Dict[str, int]:
    output = vyos_show(["interfaces", "ethernet", iface])
    rx_match = re.search(r"RX:\s+bytes\s+packets.*?\n\s*(\d+)\s+(\d+)", output, re.DOTALL)
    tx_match = re.search(r"TX:\s+bytes\s+packets.*?\n\s*(\d+)\s+(\d+)", output, re.DOTALL)
    if not rx_match or not tx_match:
        raise RuntimeError(f"Could not parse counters for {iface}")
    return {
        "rx_bytes": int(rx_match.group(1)),
        "rx_packets": int(rx_match.group(2)),
        "tx_bytes": int(tx_match.group(1)),
        "tx_packets": int(tx_match.group(2)),
    }


def get_throughput_snapshot() -> List[Dict[str, Any]]:
    now = time.time()
    rows: List[Dict[str, Any]] = []
    for item in INTERFACES:
        iface = item["name"]
        counters = get_interface_counters(iface)
        rx_mbps = None
        tx_mbps = None
        prev = THROUGHPUT_CACHE.get(iface)
        if prev:
            elapsed = now - prev["ts"]
            if elapsed > 0:
                rx_bps = max(0, counters["rx_bytes"] - int(prev["rx_bytes"])) * 8.0 / elapsed
                tx_bps = max(0, counters["tx_bytes"] - int(prev["tx_bytes"])) * 8.0 / elapsed
                rx_mbps = rx_bps / 1_000_000.0
                tx_mbps = tx_bps / 1_000_000.0
        THROUGHPUT_CACHE[iface] = {
            "ts": now,
            "rx_bytes": counters["rx_bytes"],
            "tx_bytes": counters["tx_bytes"],
        }
        rows.append({
            "name": iface,
            "rx_mbps": rx_mbps,
            "tx_mbps": tx_mbps,
            "rx_bytes": counters["rx_bytes"],
            "tx_bytes": counters["tx_bytes"],
        })
    return rows


def build_setup_ops() -> List[Dict[str, Any]]:
    ops: List[Dict[str, Any]] = []
    for item in INTERFACES:
        default_delay = int(item.get("default_delay_ms", 10))
        ops.append({"op": "set", "path": ["qos", "policy", "network-emulator", item["policy"], "bandwidth", item.get("bandwidth", "10mbit")]})
        ops.append({"op": "set", "path": ["qos", "policy", "network-emulator", item["policy"], "delay", delay_ms_to_vyos(default_delay)]})
        ops.append({"op": "set", "path": ["qos", "interface", item["name"], item.get("direction", "egress"), item["policy"]]})
    return ops


def apply_delay(item: Dict[str, str], delay_ms: int) -> None:
    op = {"op": "set", "path": ["qos", "policy", "network-emulator", item["policy"], "delay", delay_ms_to_vyos(delay_ms)]}
    vyos_post("configure", op)


def apply_all_delays(delay_ms: int) -> None:
    delay_ms = max(0, min(MAX_DELAY_MS, int(delay_ms)))
    ops: List[Dict[str, Any]] = []
    for item in INTERFACES:
        ops.append({"op": "set", "path": ["qos", "policy", "network-emulator", item["policy"], "delay", delay_ms_to_vyos(delay_ms)]})
    vyos_post("configure", ops)


def setup_wanem() -> int:
    ops = build_setup_ops()
    vyos_post("configure", ops)
    return len(ops)


def get_interface_rows() -> List[Dict[str, Any]]:
    qos_cfg = get_qos_config()
    rows = []
    for item in INTERFACES:
        rows.append({
            "name": item["name"],
            "policy": item["policy"],
            "bandwidth": item.get("bandwidth", "10mbit"),
            "delay_ms": get_policy_delay_ms(qos_cfg, item["policy"]),
        })
    return rows


@app.route("/", methods=["GET"])
def index():
    try:
        interfaces = get_interface_rows()
    except Exception:
        interfaces = [{**i, "delay_ms": int(i.get("default_delay_ms", 10))} for i in INTERFACES]
    return render_template_string(
        PAGE,
        interfaces=interfaces,
        base_url=VYOS_BASE_URL,
        verify_tls=VERIFY_TLS,
        max_delay_ms=MAX_DELAY_MS,
        default_refresh_seconds=DEFAULT_REFRESH_SECONDS,
        config_path=CONFIG_PATH,
    )


@app.route("/set-delay", methods=["POST"])
def set_delay():
    iface = request.form.get("iface", "").strip()
    raw_delay = request.form.get("delay_ms", "0").strip()
    try:
        delay_ms = int(raw_delay)
        if delay_ms < 0 or delay_ms > MAX_DELAY_MS:
            raise ValueError(f"Delay must be between 0 and {MAX_DELAY_MS} ms")
        item = next((x for x in INTERFACES if x["name"] == iface), None)
        if not item:
            raise ValueError(f"Unknown interface: {iface}")
        apply_delay(item, delay_ms)
        return jsonify({"success": True, "iface": iface, "policy": item["policy"], "delay_ms": delay_ms})
    except Exception as exc:
        return jsonify({"success": False, "iface": iface, "error": str(exc)}), 400


@app.route("/set-all-delays", methods=["POST"])
def set_all_delays():
    raw_delay = request.form.get("delay_ms", "0").strip()
    try:
        delay_ms = int(raw_delay)
        if delay_ms < 0 or delay_ms > MAX_DELAY_MS:
            raise ValueError(f"Delay must be between 0 and {MAX_DELAY_MS} ms")
        apply_all_delays(delay_ms)
        return jsonify({"success": True, "delay_ms": delay_ms, "interfaces": [item["name"] for item in INTERFACES]})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 400


@app.route("/setup-wanem", methods=["POST"])
def setup_wanem_route():
    try:
        count = setup_wanem()
        return jsonify({"success": True, "count": count})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 400


@app.route("/api/state", methods=["GET"])
def api_state():
    try:
        return jsonify({"success": True, "interfaces": get_interface_rows()})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@app.route("/api/throughput", methods=["GET"])
def api_throughput():
    try:
        return jsonify({"success": True, "interfaces": get_throughput_snapshot()})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=True)

