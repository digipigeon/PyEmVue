#!/usr/bin/env python3
"""
PyEmVue to Grafana Cloud Exporter

Exports Emporia Vue energy monitoring data to Grafana Cloud using Prometheus remote write.

Configuration (all via environment variables):
    Emporia Vue:
    - EMPORIA_USERNAME: Your Emporia Vue account email
    - EMPORIA_PASSWORD: Your Emporia Vue account password

    Grafana Cloud:
    - GRAFANA_REMOTE_WRITE_URL: Your Grafana Cloud Prometheus remote write URL
    - GRAFANA_USERNAME: Your Grafana Cloud instance ID (numeric)
    - GRAFANA_API_KEY: Your Grafana Cloud API key with metrics push permissions

    Optional:
    - SCRAPE_INTERVAL: Seconds between metric collection (default: 60)
    - LOG_LEVEL: Logging level - DEBUG, INFO, WARNING, ERROR (default: INFO)

Usage:
    docker-compose up -d
    # or
    python grafana_exporter.py
"""

import os
import sys
import time
import logging
from typing import Optional

# Load .env file if present (for local development)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv not installed, rely on actual env vars

import requests
import pyemvue
from pyemvue.enums import Scale, Unit

# Configure logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_config() -> dict:
    """Load configuration from environment variables."""
    return {
        # Emporia Vue credentials
        "emporia_username": os.getenv("EMPORIA_USERNAME", ""),
        "emporia_password": os.getenv("EMPORIA_PASSWORD", ""),
        # Grafana Cloud credentials
        "grafana_remote_write_url": os.getenv("GRAFANA_REMOTE_WRITE_URL", ""),
        "grafana_username": os.getenv("GRAFANA_USERNAME", ""),
        "grafana_api_key": os.getenv("GRAFANA_API_KEY", ""),
        # Settings
        "scrape_interval": int(os.getenv("SCRAPE_INTERVAL", "60")),
    }


def validate_config(config: dict) -> list[str]:
    """Validate configuration and return list of missing items."""
    missing = []
    
    if not config["emporia_username"]:
        missing.append("EMPORIA_USERNAME")
    if not config["emporia_password"]:
        missing.append("EMPORIA_PASSWORD")
    if not config["grafana_remote_write_url"]:
        missing.append("GRAFANA_REMOTE_WRITE_URL")
    if not config["grafana_username"]:
        missing.append("GRAFANA_USERNAME")
    if not config["grafana_api_key"]:
        missing.append("GRAFANA_API_KEY")
    
    return missing


def create_prometheus_remote_write_payload(metrics: list[dict]) -> bytes:
    """Create metrics in Prometheus remote write protobuf format with snappy compression."""
    import snappy
    import struct
    from io import BytesIO
    
    timestamp_ms = int(time.time() * 1000)
    
    # Build protobuf manually (simplified WriteRequest format)
    # This follows the prometheus remote write protobuf spec
    def encode_varint(value):
        bits = value & 0x7f
        value >>= 7
        result = b''
        while value:
            result += bytes([0x80 | bits])
            bits = value & 0x7f
            value >>= 7
        result += bytes([bits])
        return result
    
    def encode_string(s):
        encoded = s.encode('utf-8')
        return encode_varint(len(encoded)) + encoded
    
    def encode_label(name, value):
        # Label message: field 1 = name (string), field 2 = value (string)
        content = b'\x0a' + encode_string(name) + b'\x12' + encode_string(value)
        return content
    
    def encode_sample(value, timestamp):
        # Sample message: field 1 = value (double), field 2 = timestamp (int64)
        import struct
        content = b'\x09' + struct.pack('<d', value)  # field 1, type double
        content += b'\x10' + encode_varint(timestamp)  # field 2, type varint
        return content
    
    def encode_timeseries(labels_list, samples_list):
        # TimeSeries message: field 1 = labels (repeated), field 2 = samples (repeated)
        content = b''
        for name, value in labels_list:
            label_bytes = encode_label(name, value)
            content += b'\x0a' + encode_varint(len(label_bytes)) + label_bytes
        for value, timestamp in samples_list:
            sample_bytes = encode_sample(value, timestamp)
            content += b'\x12' + encode_varint(len(sample_bytes)) + sample_bytes  # field 2, wire type 2
        return content
    
    # Build all timeseries
    timeseries_data = b''
    for metric in metrics:
        if metric.get('usage_kwh') is None:
            continue
            
        base_labels = [
            ('device_gid', str(metric['device_gid'])),
            ('device_name', metric['device_name']),
            ('channel_num', str(metric['channel_num'])),
            ('channel_name', metric['channel_name']),
        ]
        
        # Energy metric
        labels_kwh = [('__name__', 'emporia_energy_kwh')] + base_labels
        ts_kwh = encode_timeseries(labels_kwh, [(metric['usage_kwh'], timestamp_ms)])
        timeseries_data += b'\x0a' + encode_varint(len(ts_kwh)) + ts_kwh
        
        # Power metric
        watts = metric['usage_kwh'] * 60 * 1000
        labels_watts = [('__name__', 'emporia_power_watts')] + base_labels
        ts_watts = encode_timeseries(labels_watts, [(watts, timestamp_ms)])
        timeseries_data += b'\x0a' + encode_varint(len(ts_watts)) + ts_watts
    
    # Compress with snappy
    compressed = snappy.compress(timeseries_data)
    return compressed


def push_to_grafana_cloud(config: dict, metrics_data: bytes) -> bool:
    """Push metrics to Grafana Cloud using Prometheus remote write."""
    url = config["grafana_remote_write_url"]
    username = config["grafana_username"]
    api_key = config["grafana_api_key"]
    
    logger.debug(f"Pushing to URL: {url}")
    
    try:
        response = requests.post(
            url,
            data=metrics_data,
            auth=(username, api_key),
            headers={
                "Content-Type": "application/x-protobuf",
                "Content-Encoding": "snappy",
                "X-Prometheus-Remote-Write-Version": "0.1.0",
            },
            timeout=30
        )
        
        if response.status_code in (200, 204):
            logger.info("Successfully pushed metrics to Grafana Cloud")
            return True
        else:
            logger.error(f"Failed to push metrics: {response.status_code} - {response.text}")
            return False
            
    except requests.RequestException as e:
        logger.error(f"Error pushing metrics to Grafana Cloud: {e}")
        return False


def collect_metrics(vue: pyemvue.PyEmVue) -> list[dict]:
    """Collect energy metrics from all devices."""
    metrics = []
    
    try:
        devices = vue.get_devices()
        device_gids = []
        device_info = {}
        
        for device in devices:
            if device.device_gid not in device_gids:
                device_gids.append(device.device_gid)
                device_info[device.device_gid] = device
            else:
                device_info[device.device_gid].channels += device.channels
        
        if not device_gids:
            logger.warning("No devices found")
            return metrics
        
        # Get usage data
        usage_dict = vue.get_device_list_usage(
            deviceGids=device_gids,
            instant=None,
            scale=Scale.MINUTE.value,
            unit=Unit.KWH.value
        )
        
        # Extract metrics recursively
        def extract_metrics(usage_dict, device_info, collected_metrics):
            for gid, device in usage_dict.items():
                device_name = device_info.get(gid, {})
                if hasattr(device_name, 'device_name'):
                    device_name = device_name.device_name or f"Device_{gid}"
                else:
                    device_name = f"Device_{gid}"
                
                for channel_num, channel in device.channels.items():
                    channel_name = channel.name
                    if channel_name == 'Main':
                        channel_name = device_name
                    
                    if channel.usage is not None:
                        collected_metrics.append({
                            'device_gid': gid,
                            'device_name': device_name,
                            'channel_num': channel_num,
                            'channel_name': channel_name or f"Channel_{channel_num}",
                            'usage_kwh': channel.usage
                        })
                    
                    if channel.nested_devices:
                        extract_metrics(channel.nested_devices, device_info, collected_metrics)
        
        extract_metrics(usage_dict, device_info, metrics)
        logger.info(f"Collected {len(metrics)} metrics from {len(device_gids)} devices")
        
    except Exception as e:
        logger.error(f"Error collecting metrics: {e}")
    
    return metrics


def run_exporter(config: dict):
    """Main exporter loop."""
    logger.info("Starting PyEmVue Grafana Cloud Exporter")
    logger.info(f"Scrape interval: {config['scrape_interval']} seconds")
    
    # Initialize PyEmVue
    vue = pyemvue.PyEmVue()
    
    try:
        logger.info(f"Logging in as {config['emporia_username']}...")
        vue.login(
            username=config["emporia_username"],
            password=config["emporia_password"]
        )
        logger.info("Successfully logged in to Emporia Vue")
    except Exception as e:
        logger.error(f"Failed to login: {e}")
        sys.exit(1)
    
    interval = config["scrape_interval"]
    
    while True:
        try:
            # Collect metrics
            metrics = collect_metrics(vue)
            
            if metrics:
                # Generate Prometheus format
                metrics_data = create_prometheus_remote_write_payload(metrics)
                
                # Push to Grafana Cloud
                push_to_grafana_cloud(config, metrics_data)
            else:
                logger.warning("No metrics collected")
            
        except Exception as e:
            logger.error(f"Error in exporter loop: {e}")
        
        logger.debug(f"Sleeping for {interval} seconds...")
        time.sleep(interval)


def main():
    """Entry point."""
    config = get_config()
    
    # Validate configuration
    missing = validate_config(config)
    
    if missing:
        logger.error("Missing required environment variables:")
        for var in missing:
            logger.error(f"  - {var}")
        
        print("""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PyEmVue Grafana Cloud Exporter - Configuration Required
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Set the following environment variables:

  Emporia Vue Account:
    EMPORIA_USERNAME    Your Emporia Vue email
    EMPORIA_PASSWORD    Your Emporia Vue password

  Grafana Cloud:
    GRAFANA_REMOTE_WRITE_URL  e.g., https://prometheus-prod-XX-prod-us-east-0.grafana.net/api/prom/push
    GRAFANA_USERNAME          Your Grafana Cloud instance ID (numeric)
    GRAFANA_API_KEY           API key with MetricsPublisher role

  Optional:
    SCRAPE_INTERVAL     Seconds between collections (default: 60)
    LOG_LEVEL           DEBUG, INFO, WARNING, ERROR (default: INFO)

Example:
  export EMPORIA_USERNAME="you@email.com"
  export EMPORIA_PASSWORD="your-password"
  export GRAFANA_REMOTE_WRITE_URL="https://prometheus-prod-01-prod-us-east-0.grafana.net/api/prom/push"
  export GRAFANA_USERNAME="123456"
  export GRAFANA_API_KEY="glc_xxxxx"
  python grafana_exporter.py

Or use Docker:
  cp .env.example .env
  # Edit .env with your credentials
  docker-compose up -d

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
""")
        sys.exit(1)
    
    run_exporter(config)


if __name__ == "__main__":
    main()
