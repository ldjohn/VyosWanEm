# VyOS WANEM Controller

A small Flask-based web GUI for controlling VyOS WAN emulator delay per interface.

It lets you:

- set delay per interface with a slider
- apply the same delay to all configured interfaces
- push a baseline WANEM config to VyOS if the policies are not already present
- monitor live RX/TX throughput per interface
- tune background refresh interval from the UI
- keep the lab topology and interface mappings in a JSON config file instead of hardcoding them in Python

This is built for lab and testing use, not for production hardening.

---

## Features

### Per-interface delay control

Each configured interface gets:

- a delay slider
- a numeric input box
- live status feedback

Changes are sent through the VyOS API.

### Apply to all

The **Apply to all** button sends a single combined `/configure` request to VyOS with one delay update per configured policy.

That is faster and cleaner than sending one request per interface.

### Setup button

The **Setup WANEM** button pushes the baseline WANEM config to VyOS:

- creates or refreshes each `network-emulator` policy
- sets the configured bandwidth
- sets the configured default delay
- binds the policy to the configured interface and direction

This is useful if the router starts with no WANEM config.

### Throughput view

The UI polls interface counters and calculates:

- RX Mbps
- TX Mbps

This is done by sampling byte counters over time and calculating the rate between samples.

### Config file support

The app reads topology and behaviour from `wanem_config.json` instead of hardcoding all values in the Python source.

If the config file does not exist, it is created with defaults.

---

## How it works

The app talks to VyOS over the HTTPS API.

It uses:

- `/configure` for changing WANEM delay and pushing baseline config
- `/retrieve` for reading current QoS config
- `/show` for operational interface information used to calculate throughput

Delay values sent to VyOS are plain numeric values.

---

## Requirements

- Python 3.9+
- Flask
- requests
- urllib3
- a VyOS router with:
  - HTTPS API enabled
  - API key configured
- network reachability from the host running the Flask app to the VyOS API endpoint

---

## Installation

Clone the repo:

```bash
git clone https://github.com/ldjohn/VyosWanEm.git
cd VyosWanEm
```

Create a virtual environment and install dependencies:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Set your API key:

```bash
export VYOS_API_KEY='your-api-key-here'
```

Run the app:

```bash
python3 app.py
```

Then open the web UI in your browser, usually on:

```text
http://<host-running-app>:5000
```

---

## VyOS requirements

The app expects the VyOS HTTPS API to be enabled.

Example minimum setup on VyOS:

```bash
set service https api keys id GUI key 'your-api-key-here'
set service https api rest
commit
save
```

The app can push the WANEM baseline config for you, so the policies do not need to exist beforehand if you use the **Setup WANEM** button.

---

## Configuration

The app reads settings from:

```text
wanem_config.json
```

If the file does not exist, it is created automatically.

### Example config

```json
{
  "vyos_base_url": "https://192.168.68.10",
  "verify_tls": false,
  "max_delay_ms": 2000,
  "default_refresh_seconds": 10,
  "interfaces": [
    {
      "name": "eth2",
      "policy": "WANEM-1",
      "bandwidth": "10mbit",
      "direction": "egress",
      "default_delay_ms": 10
    },
    {
      "name": "eth3",
      "policy": "WANEM-2",
      "bandwidth": "10mbit",
      "direction": "egress",
      "default_delay_ms": 10
    }
  ]
}
```

### Config fields

#### `vyos_base_url`

Base URL for the VyOS HTTPS API.

Example:

```json
"vyos_base_url": "https://192.168.1.10"
```

#### `verify_tls`

Whether to verify the VyOS HTTPS certificate.

Example:

```json
"verify_tls": false
```

For lab use with self-signed certs, `false` is common. For a cleaner and safer setup, use a trusted certificate and set this to `true`.

#### `max_delay_ms`

Maximum delay value allowed in the UI.

Example:

```json
"max_delay_ms": 2000
```

#### `default_refresh_seconds`

Default interval for UI background refresh.

Example:

```json
"default_refresh_seconds": 10
```

#### `interfaces`

List of interfaces to manage.

Each entry defines:

- `name` — VyOS interface name
- `policy` — WANEM policy name
- `bandwidth` — network-emulator bandwidth setting
- `direction` — normally `egress`
- `default_delay_ms` — baseline delay used by setup

Example:

```json
{
  "name": "eth2",
  "policy": "WANEM-1",
  "bandwidth": "10mbit",
  "direction": "egress",
  "default_delay_ms": 10
}
```

---

## Usage

### 1. Start the app

Run:

```bash
python3 app.py
```

### 2. Open the web interface

Browse to the Flask host on port 5000.

### 3. Push baseline WANEM config

Click **Setup WANEM**.

This will create or refresh the WANEM policies and bind them to the configured interfaces.

### 4. Adjust per-interface delay

Move a slider and release it.

The change is sent immediately.

### 5. Apply one delay to all interfaces

Enter a value in the **Set all** box and click **Apply to all**.

### 6. Monitor traffic

Watch the RX/TX Mbps columns update on each refresh interval.

---

## Throughput calculation

The throughput view is based on the difference between interface byte counters across samples.

The app:

1. reads RX/TX byte counters from VyOS
2. stores the previous sample in memory
3. calculates the bit rate over elapsed time

Formula:

```text
rate_bps = (current_bytes - previous_bytes) * 8 / elapsed_seconds
```

Displayed values are shown in Mbps.

Notes:

- the first sample usually shows no rate yet
- the second sample onwards gives usable values
- lower refresh intervals mean more API calls to the router

---

## Project layout

Typical files:

```text
app.py
README.md
requirements.txt
LICENSE
.gitignore
wanem_config.example.json
```

Recommended local-only file:

```text
wanem_config.json
```

---

## Security notes

This project is for lab use and needs some care before wider use.

### Do not commit secrets

Do not hardcode or commit:

- live API keys
- private router addresses you do not want published
- lab-specific secrets

Use environment variables for the API key:

```bash
export VYOS_API_KEY='your-api-key'
```

### Keep local config out of git

Your real `wanem_config.json` should usually stay local.

Commit a safe example file instead, such as:

```text
wanem_config.example.json
```

### TLS verification

If `verify_tls` is set to `false`, HTTPS certificate validation is disabled.

That is often fine for a closed lab, but not ideal for anything more serious.

---

## Limitations

- changes go through the VyOS config API, so they are not truly instantaneous
- `/configure` commits changes as part of the request path
- throughput values are sampled estimates, not hardware-rate telemetry
- interface counter parsing depends on expected VyOS command output
- this is not hardened for multi-user or Internet-facing deployment

---

### Self-signed certificate warnings

Set `verify_tls` appropriately for your environment.
For lab use, disabling verification is common, but it is less secure.

---

## License

MIT License.
