from flask import Flask, render_template, jsonify, request
import time
import subprocess
import psutil
import threading
import os
import json
import platform
import re
import shutil

# WiringPi GPIO (for Raspberry Pi and other compatible SBCs)
try:
    import wiringpi
    GPIO_AVAILABLE = True
    
    STANDBY_LED_PIN = 6   # GPIO 25 in BCM, WiringPi pin 6
    STREAMING_LED_PIN = 1  # GPIO 12 in BCM, WiringPi pin 1
    
    wiringpi.wiringPiSetup()
    wiringpi.pinMode(STANDBY_LED_PIN, wiringpi.OUTPUT)
    wiringpi.pinMode(STREAMING_LED_PIN, wiringpi.OUTPUT)
    
    wiringpi.digitalWrite(STANDBY_LED_PIN, wiringpi.LOW)
    wiringpi.digitalWrite(STREAMING_LED_PIN, wiringpi.LOW)
    
    def standby_led_on():
        wiringpi.digitalWrite(STANDBY_LED_PIN, wiringpi.HIGH)
    
    def standby_led_off():
        wiringpi.digitalWrite(STANDBY_LED_PIN, wiringpi.LOW)
    
    def streaming_led_on():
        wiringpi.digitalWrite(STREAMING_LED_PIN, wiringpi.HIGH)
    
    def streaming_led_off():
        wiringpi.digitalWrite(STREAMING_LED_PIN, wiringpi.LOW)
        
except ImportError:
    GPIO_AVAILABLE = False
    
    def standby_led_on(): pass
    def standby_led_off(): pass
    def streaming_led_on(): pass
    def streaming_led_off(): pass

app = Flask(__name__, 
    static_folder='/etc/rtl_web_monitor/static',
    template_folder='/etc/rtl_web_monitor/templates')

status = {
    "service_running": False,
    "streaming_active": False,
    "cpu_usage": 0,
    "cpu_temp": 0,
    "memory_total": 0,
    "memory_available": 0,
    "memory_percent": 0,
    "swap_total": 0,
    "swap_free": 0,
    "swap_percent": 0,
    "network_sent": 0,
    "network_recv": 0,
    "rtl_tcp_pid": None,
    "update_time": 0,
    "gpio_available": GPIO_AVAILABLE
}

# Check service status
def is_service_running(service_name="rtl_tcp.service"):
    try:
        result = subprocess.run(
            ["systemctl", "is-active", service_name],
            capture_output=True, text=True, check=False
        )
        return result.stdout.strip() == "active"
    except Exception:
        return False

# Get rtl_tcp PID
def get_rtl_tcp_pid():
    try:
        result = subprocess.run(
            ["pgrep", "-f", "rtl_tcp"],
            capture_output=True, text=True, check=False
        )
        if result.stdout.strip():
            return int(result.stdout.strip())
        return None
    except Exception:
        return None

# Check streaming connections
def check_streaming_connections():
    try:
        connections = psutil.net_connections(kind='tcp')
        for conn in connections:
            if conn.laddr.port == 1234 and conn.status == 'ESTABLISHED':
                return True
        return False
    except:
        try:
            result = subprocess.run(
                ["netstat", "-tn"], 
                capture_output=True, 
                text=True, 
                check=False
            )
            output = result.stdout.lower()
            for line in output.split('\n'):
                if ':1234' in line and 'established' in line:
                    return True
            return False
        except:
            return False

# Get CPU temperature
def get_cpu_temperature():
    if platform.system() == 'Linux':
        try:
            if os.path.exists('/sys/class/thermal/thermal_zone0/temp'):
                with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f:
                    temp = float(f.read()) / 1000.0
                    return temp
            if os.path.exists('/sys/class/hwmon'):
                for hwmon in os.listdir('/sys/class/hwmon'):
                    hwmon_path = os.path.join('/sys/class/hwmon', hwmon)
                    for subdir in os.listdir(hwmon_path):
                        if subdir.startswith('temp') and subdir.endswith('_input'):
                            with open(os.path.join(hwmon_path, subdir), 'r') as f:
                                temp = float(f.read()) / 1000.0
                                return temp
            try:
                result = subprocess.run(
                    ["sensors"],
                    capture_output=True, text=True, check=False
                )
                output = result.stdout
                for line in output.split('\n'):
                    if 'Core 0' in line or 'CPU Temp' in line or 'temp1' in line:
                        parts = line.split('+')
                        if len(parts) > 1:
                            temp_part = parts[1].split('°')[0]
                            return float(temp_part)
            except:
                pass
        except:
            pass
    return 0

# Get system statistics
def get_system_stats():
    global status
    
    status["cpu_usage"] = psutil.cpu_percent(interval=None)
    
    status["cpu_temp"] = get_cpu_temperature()
    
    mem = psutil.virtual_memory()
    status["memory_total"] = mem.total
    status["memory_available"] = mem.available
    status["memory_percent"] = mem.percent
    
    swap = psutil.swap_memory()
    status["swap_total"] = swap.total
    status["swap_free"] = swap.free
    status["swap_percent"] = swap.percent
    
    status["rtl_tcp_pid"] = get_rtl_tcp_pid()
    
    net_io = psutil.net_io_counters()
    status["network_sent"] = net_io.bytes_sent
    status["network_recv"] = net_io.bytes_recv
    
    status["update_time"] = time.time()

# Update status in background
def update_status_loop():
    global status
    
    last_network_sent = 0
    last_network_recv = 0
    last_update_time = time.time()
    
    last_standby_state = None
    last_streaming_state = None
    
    while True:
        status["service_running"] = is_service_running("rtl_tcp.service")
        
        status["streaming_active"] = False
        if status["service_running"]:
            status["streaming_active"] = check_streaming_connections()
        
        get_system_stats()
        
        if GPIO_AVAILABLE:
            if last_standby_state != (status["service_running"] and not status["streaming_active"]) or \
            last_streaming_state != status["streaming_active"]:
                
                if status["service_running"]:
                    if status["streaming_active"]:
                        streaming_led_on()
                        standby_led_off()
                    else:
                        standby_led_on()
                        streaming_led_off()
                else:
                    standby_led_off()
                    streaming_led_off()
                    
                last_standby_state = status["service_running"] and not status["streaming_active"]
                last_streaming_state = status["streaming_active"]
        
        time.sleep(1)

# Get systemctl status
def get_service_status(service_name="rtl_tcp.service"):
    try:
        result = subprocess.run(
            ["sudo", "systemctl", "status", service_name],
            capture_output=True, text=True, check=False
        )
        return result.stdout if result.returncode in [0, 3] else f"Error: {result.stderr}"
    except Exception as e:
        return f"Error: {str(e)}"

# Get full ExecStart command line
def get_full_exec_command():
    try:
        service_file = '/etc/systemd/system/rtl_tcp.service'
        with open(service_file, 'r') as f:
            content = f.read()
            
        # Find ExecStart line
        exec_start_match = re.search(r'(ExecStart=.*)', content)
        if exec_start_match:
            return exec_start_match.group(1)
        return "ExecStart=/usr/local/bin/rtl_tcp -a 0.0.0.0 -p 1234 -s 2048000"
    except Exception as e:
        print(f"Error getting exec command: {str(e)}")
        return "ExecStart=/usr/local/bin/rtl_tcp -a 0.0.0.0 -p 1234 -s 2048000"

# Update service file with direct command
def update_direct_command(command_line):
    try:
        service_file = '/etc/systemd/system/rtl_tcp.service'
        
        backup_file = f"{service_file}.bak"
        shutil.copy2(service_file, backup_file)
        
        with open(service_file, 'r') as f:
            content = f.read()
            
        if not command_line.startswith('ExecStart='):
            command_line = 'ExecStart=' + command_line
            
        updated_content = re.sub(
            r'ExecStart=.*', 
            command_line, 
            content
        )
        
        with open(service_file, 'w') as f:
            f.write(updated_content)
        
        reload_result = subprocess.run(
            ["sudo", "systemctl", "daemon-reload"],
            capture_output=True, text=True, check=False
        )
        
        if reload_result.returncode != 0:
            return False, f"Error reloading systemd: {reload_result.stderr}"
        
        restart_result = subprocess.run(
            ["sudo", "systemctl", "restart", "rtl_tcp.service"],
            capture_output=True, text=True, check=False
        )
        
        if restart_result.returncode != 0:
            return False, f"Error restarting service: {restart_result.stderr}"
        
        return True, "Command updated and service restarted"
    
    except Exception as e:
        return False, f"Configuration update error: {str(e)}"

def get_rtl_tcp_config():
    config = {
        "address": "0.0.0.0",
        "port": "1234",
        "sample_rate": "2048000"
    }
    
    try:
        with open('/etc/systemd/system/rtl_tcp.service', 'r') as f:
            content = f.read()
            
            exec_start_match = re.search(r'ExecStart=.*rtl_tcp\s+(.*)', content)
            if exec_start_match:
                args = exec_start_match.group(1)
                
                addr_match = re.search(r'-a\s+([^\s]+)', args)
                if addr_match:
                    config["address"] = addr_match.group(1)
                
                port_match = re.search(r'-p\s+([^\s]+)', args)
                if port_match:
                    config["port"] = port_match.group(1)
                
                sample_match = re.search(r'-s\s+([^\s]+)', args)
                if sample_match:
                    config["sample_rate"] = sample_match.group(1)
    except Exception as e:
        print(f"Error loading config file: {str(e)}")
    
    return config

def update_rtl_tcp_config(address, port, sample_rate):
    try:
        service_file = '/etc/systemd/system/rtl_tcp.service'
        
        backup_file = f"{service_file}.bak"
        shutil.copy2(service_file, backup_file)
        
        with open(service_file, 'r') as f:
            content = f.read()
        
        new_exec_start = f"ExecStart=/usr/local/bin/rtl_tcp -a {address} -p {port} -s {sample_rate}"
        
        updated_content = re.sub(
            r'ExecStart=.*rtl_tcp.*', 
            new_exec_start, 
            content
        )
        
        with open(service_file, 'w') as f:
            f.write(updated_content)
        
        reload_result = subprocess.run(
            ["sudo", "systemctl", "daemon-reload"],
            capture_output=True, text=True, check=False
        )
        
        if reload_result.returncode != 0:
            return False, f"Error reloading systemd: {reload_result.stderr}"
        
        restart_result = subprocess.run(
            ["sudo", "systemctl", "restart", "rtl_tcp.service"],
            capture_output=True, text=True, check=False
        )
        
        if restart_result.returncode != 0:
            return False, f"Error restarting service: {restart_result.stderr}"
        
        return True, "Configuration updated and service restarted"
    
    except Exception as e:
        return False, f"Configuration update error: {str(e)}"

# Create static files
def create_static_files():
    base_dir = '/etc/rtl_web_monitor'
    os.makedirs(f'{base_dir}/templates', exist_ok=True)
    os.makedirs(f'{base_dir}/static', exist_ok=True)
    os.makedirs(f'{base_dir}/static/css', exist_ok=True)
    os.makedirs(f'{base_dir}/static/js', exist_ok=True)

    with open('templates/index.html', 'w') as f:
        f.write("""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>RTL-SDR Monitor</title>
    <link rel="stylesheet" href="{{ url_for('static', filename='css/style.css') }}">
</head>
<body>
    <div class="container">
        <h1>RTL-SDR Monitor</h1>
        
        <div class="status-panel">
            <div class="status-item">
                <h2>Status</h2>
                <div class="status-indicator">
                    <div id="service-status" class="status-light"></div>
                    <span id="service-text">Loading...</span>
                </div>
                <div class="button-group">
                    <button id="start-service" class="action-button start">On Air</button>
                    <button id="stop-service" class="action-button stop">Stop</button>
                    <button id="restart-service" class="action-button restart">Reboot</button>
                </div>
            </div>
            
            <div class="status-item">
                <h2>Streaming Status</h2>
                <div class="status-indicator">
                    <div id="streaming-status" class="status-light"></div>
                    <span id="streaming-text">Loading...</span>
                </div>
                <div id="gpio-status">
                    <div class="gpio-leds">
                        <div class="gpio-led">
                            <div class="led-label">Standby LED (WiringPi 6)</div>
                            <div id="standby-led" class="led"></div>
                        </div>
                        <div class="gpio-led">
                            <div class="led-label">Streaming LED (WiringPi 1)</div>
                            <div id="streaming-led" class="led"></div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        
        <div class="service-info-panel">
            <h2>RTL-TCP Service Status</h2>
            <div class="service-status-output">
                <pre id="service-status-output">Loading status information...</pre>
            </div>
        </div>

        <div class="service-config-panel">
            <h2>RTL-TCP Service Configuration</h2>
            <div class="config-mode-selector">
                <label>Configuration Mode:</label>
                <div class="toggle-group">
                    <button id="easy-mode-btn" class="toggle-button active">Easy Setup</button>
                    <button id="direct-mode-btn" class="toggle-button">Direct Edit</button>
                </div>
            </div>
            
            <!-- Easy Setup Form -->
            <form id="rtl-tcp-config-form" class="config-form">
                <div class="config-item">
                    <label for="address">Address (-a):</label>
                    <input type="text" id="address" name="address" placeholder="0.0.0.0">
                </div>
                
                <div class="config-item">
                    <label for="port">Port (-p):</label>
                    <input type="number" id="port" name="port" placeholder="1234" min="1" max="65535">
                </div>
                
                <div class="config-item">
                    <label for="sample-rate">Sample Rate (-s):</label>
                    <select id="sample-rate" name="sample-rate">
                        <option value="250000">250000</option>
                        <option value="1024000">1024000</option>
                        <option value="1536000">1536000</option>
                        <option value="1792000">1792000</option>
                        <option value="1920000">1920000</option>
                        <option value="2048000" selected>2048000</option>
                        <option value="2400000">2400000</option>
                        <option value="2560000">2560000</option>
                    </select>
                </div>
                
                <button type="submit" class="action-button">Apply Settings and Restart</button>
            </form>
            
            <!-- Direct Edit Form -->
            <form id="direct-edit-form" class="config-form" style="display:none;">
                <div class="config-item">
                    <label for="direct-command">Service Command Line:</label>
                    <input type="text" id="direct-command" name="direct-command" class="full-width-input">
                    <div class="hint">Example: /usr/local/bin/rtl_tcp -a 0.0.0.0 -p 1234 -s 2048000</div>
                </div>
                
                <button type="submit" class="action-button">Apply Command and Restart</button>
            </form>
        </div>
        
        <div class="metrics-panel">
            <div class="metric-item">
                <h2>CPU Load</h2>
                <div class="metric-value">
                    <span id="cpu-usage">0</span><span>%</span>
                </div>
                <div class="progress-bar">
                    <div id="cpu-bar" class="progress" style="width: 0%;"></div>
                </div>
            </div>
            
            <div class="metric-item">
                <h2>CPU Temp</h2>
                <div class="metric-value">
                    <span id="cpu-temp">0</span><span>°C</span>
                </div>
                <div class="progress-bar">
                    <div id="cpu-temp-bar" class="progress" style="width: 0%;"></div>
                </div>
            </div>
            
            <div class="metric-item">
                <h2>Memory</h2>
                <div class="metric-value">
                    <span id="memory-percent">0</span><span>%</span>
                    <div class="sub-metric">
                        Available: <span id="memory-available">0</span> MB / <span id="memory-total">0</span> MB
                    </div>
                </div>
                <div class="progress-bar">
                    <div id="memory-bar" class="progress" style="width: 0%;"></div>
                </div>
            </div>
            
            <div class="metric-item">
                <h2>Swap</h2>
                <div class="metric-value">
                    <span id="swap-percent">0</span><span>%</span>
                    <div class="sub-metric">
                        Free: <span id="swap-free">0</span> MB / <span id="swap-total">0</span> MB
                    </div>
                </div>
                <div class="progress-bar">
                    <div id="swap-bar" class="progress" style="width: 0%;"></div>
                </div>
            </div>
            
            <div class="metric-item">
                <h2>Network</h2>
                <div class="network-metrics">
                    <div>
                        <span>RX: </span>
                        <span id="network-recv">0</span>
                        <span> KB/s</span>
                    </div>
                    <div>
                        <span>TX: </span>
                        <span id="network-sent">0</span>
                        <span> KB/s</span>
                    </div>
                </div>
            </div>
        </div>
    </div>
    
    <script src="{{ url_for('static', filename='js/script.js') }}"></script>
</body>
</html>""")

    # Create CSS
    with open(f'{base_dir}/static/css/style.css', 'w') as f:
            f.write("""* {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}

body {
    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
    background-color: #f5f5f5;
    color: #333;
}

.container {
    max-width: 800px;
    margin: 0 auto;
    padding: 20px;
}

h1 {
    text-align: center;
    margin-bottom: 30px;
    color: #2c3e50;
}

h2 {
    font-size: 1.2rem;
    margin-bottom: 10px;
    color: #34495e;
}

.status-panel, .metrics-panel, .service-info-panel, .service-config-panel {
    background-color: white;
    border-radius: 8px;
    box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1);
    padding: 20px;
    margin-bottom: 20px;
    display: flex;
    flex-wrap: wrap;
    justify-content: space-between;
}

.status-item, .metric-item {
    flex-basis: 48%;
    margin-bottom: 15px;
}

.status-indicator {
    display: flex;
    align-items: center;
    margin-bottom: 15px;
}

.status-light {
    width: 20px;
    height: 20px;
    border-radius: 50%;
    margin-right: 10px;
    background-color: #95a5a6;
}

.status-light.active {
    background-color: #2ecc71;
    box-shadow: 0 0 10px rgba(46, 204, 113, 0.5);
}

.status-light.inactive {
    background-color: #e74c3c;
    box-shadow: 0 0 10px rgba(231, 76, 60, 0.5);
}

.status-light.standby {
    background-color: #f39c12;
    box-shadow: 0 0 10px rgba(243, 156, 18, 0.5);
}

.gpio-leds {
    display: flex;
    justify-content: space-between;
    margin-top: 15px;
}

.gpio-led {
    text-align: center;
    margin: 0 10px;
}

.led-label {
    font-size: 0.8rem;
    margin-bottom: 5px;
}

.led {
    width: 30px;
    height: 30px;
    border-radius: 50%;
    margin: 0 auto;
    background-color: #95a5a6;
    border: 2px solid #7f8c8d;
}

.led.on {
    background-color: #2ecc71;
    box-shadow: 0 0 15px rgba(46, 204, 113, 0.8);
}

.led.standby-on {
    background-color: #f39c12;
    box-shadow: 0 0 15px rgba(243, 156, 18, 0.8);
}

.button-group {
    display: flex;
    gap: 10px;
}

.action-button {
    padding: 8px 15px;
    border: none;
    border-radius: 4px;
    color: white;
    font-weight: bold;
    cursor: pointer;
    transition: all 0.3s ease;
}

.action-button.start {
    background-color: #2ecc71;
}

.action-button.stop {
    background-color: #e74c3c;
}

.action-button.restart {
    background-color: #3498db;
}

.action-button:hover {
    opacity: 0.8;
}

.action-button:disabled {
    background-color: #95a5a6;
    cursor: not-allowed;
}

.metric-value {
    font-size: 2rem;
    font-weight: bold;
    margin-bottom: 10px;
}

.sub-metric {
    font-size: 0.9rem;
    font-weight: normal;
    margin-top: 5px;
}

.progress-bar {
    width: 100%;
    height: 10px;
    background-color: #ecf0f1;
    border-radius: 5px;
    overflow: hidden;
}

.progress {
    height: 100%;
    background-color: #3498db;
    transition: width 0.5s ease;
}

.progress.warning {
    background-color: #f39c12;
}

.progress.danger {
    background-color: #e74c3c;
}

.network-metrics {
    font-size: 1.1rem;
    line-height: 1.6;
}

.service-status-output {
    background-color: #2c3e50;
    color: #ecf0f1;
    padding: 15px;
    border-radius: 5px;
    font-family: monospace;
    overflow-x: auto;
    max-height: 250px;
    overflow-y: auto;
}

.service-status-output pre {
    margin: 0;
    white-space: pre-wrap;
}

.config-item {
    margin-bottom: 15px;
    width: 100%;
}

.config-item label {
    display: block;
    margin-bottom: 5px;
    font-weight: bold;
}

.config-item input, .config-item select {
    width: 100%;
    padding: 8px;
    border: 1px solid #ccc;
    border-radius: 4px;
}

.full-width-input {
    width: 100%;
    font-family: monospace;
}

.hint {
    font-size: 0.8rem;
    color: #7f8c8d;
    margin-top: 5px;
}

.config-form button {
    background-color: #3498db;
    margin-top: 10px;
    width: 100%;
    padding: 10px;
}

.config-mode-selector {
    width: 100%;
    margin-bottom: 20px;
    display: flex;
    align-items: center;
}

.config-mode-selector label {
    margin-right: 10px;
    font-weight: bold;
}

.toggle-group {
    display: flex;
    border-radius: 4px;
    overflow: hidden;
}

.toggle-button {
    padding: 8px 15px;
    background-color: #ecf0f1;
    border: none;
    color: #7f8c8d;
    font-weight: bold;
    cursor: pointer;
}

.toggle-button.active {
    background-color: #3498db;
    color: white;
}

@media (max-width: 600px) {
    .status-item, .metric-item {
        flex-basis: 100%;
    }
}""")

    # Create JavaScript
    with open(f'{base_dir}/static/js/script.js', 'w') as f:
            f.write("""document.addEventListener('DOMContentLoaded', function() {
    // Get elements
    const serviceStatus = document.getElementById('service-status');
    const serviceText = document.getElementById('service-text');
    const streamingStatus = document.getElementById('streaming-status');
    const streamingText = document.getElementById('streaming-text');
    
    // GPIO LED display
    const standbyLed = document.getElementById('standby-led');
    const streamingLed = document.getElementById('streaming-led');
    
    // CPU
    const cpuUsage = document.getElementById('cpu-usage');
    const cpuBar = document.getElementById('cpu-bar');
    
    // CPU temperature
    const cpuTemp = document.getElementById('cpu-temp');
    const cpuTempBar = document.getElementById('cpu-temp-bar');
    
    // Memory
    const memoryPercent = document.getElementById('memory-percent');
    const memoryAvailable = document.getElementById('memory-available');
    const memoryTotal = document.getElementById('memory-total');
    const memoryBar = document.getElementById('memory-bar');
    
    // Swap
    const swapPercent = document.getElementById('swap-percent');
    const swapFree = document.getElementById('swap-free');
    const swapTotal = document.getElementById('swap-total');
    const swapBar = document.getElementById('swap-bar');
    
    // Network
    const networkRecv = document.getElementById('network-recv');
    const networkSent = document.getElementById('network-sent');
    
    // Button elements
    const startServiceBtn = document.getElementById('start-service');
    const stopServiceBtn = document.getElementById('stop-service');
    const restartServiceBtn = document.getElementById('restart-service');
    
    // Config mode toggle buttons
    const easyModeBtn = document.getElementById('easy-mode-btn');
    const directModeBtn = document.getElementById('direct-mode-btn');
    const easyModeForm = document.getElementById('rtl-tcp-config-form');
    const directModeForm = document.getElementById('direct-edit-form');
    
    // Previous network values
    let lastNetworkSent = 0;
    let lastNetworkRecv = 0;
    let lastUpdateTime = Date.now();
    
    // Mode toggle
    easyModeBtn.addEventListener('click', function() {
        easyModeBtn.classList.add('active');
        directModeBtn.classList.remove('active');
        easyModeForm.style.display = 'block';
        directModeForm.style.display = 'none';
    });
    
    directModeBtn.addEventListener('click', function() {
        directModeBtn.classList.add('active');
        easyModeBtn.classList.remove('active');
        directModeForm.style.display = 'block';
        easyModeForm.style.display = 'none';
        
        // Load current command
        loadDirectCommand();
    });
    
    // Load direct command
    function loadDirectCommand() {
        fetch('/api/service/direct_command')
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    const commandInput = document.getElementById('direct-command');
                    const command = data.command.replace('ExecStart=', '');
                    commandInput.value = command;
                } else {
                    console.error('Error loading direct command:', data.message);
                }
            })
            .catch(error => {
                console.error('Error fetching direct command:', error);
            });
    }
    
    // Service operations
    startServiceBtn.addEventListener('click', () => {
        fetch('/api/service/start', { method: 'POST' })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    alert('Service started successfully');
                } else {
                    alert('Error: ' + data.message);
                }
            });
    });
    
    stopServiceBtn.addEventListener('click', () => {
        fetch('/api/service/stop', { method: 'POST' })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    alert('Service stopped successfully');
                } else {
                    alert('Error: ' + data.message);
                }
            });
    });
    
    restartServiceBtn.addEventListener('click', () => {
        fetch('/api/service/restart', { method: 'POST' })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    alert('Service restarted successfully');
                } else {
                    alert('Error: ' + data.message);
                }
            });
    });
    
    // Direct edit form submission
    directModeForm.addEventListener('submit', function(event) {
        event.preventDefault();
        
        const commandLine = document.getElementById('direct-command').value;
        
        fetch('/api/service/update_direct', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ command: commandLine })
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                alert('Command updated and service restarted');
                // Update status
                updateServiceStatusOutput();
            } else {
                alert('Error: ' + data.message);
            }
        })
        .catch(error => {
            console.error('Error updating command:', error);
            alert('Error occurred while updating command');
        });
    });
    
    // Set progress bar class
    function setProgressClass(element, value, warningThreshold, dangerThreshold) {
        element.classList.remove('warning', 'danger');
        if (value >= dangerThreshold) {
            element.classList.add('danger');
        } else if (value >= warningThreshold) {
            element.classList.add('warning');
        }
    }
    
    // Convert bytes to MB
    function bytesToMB(bytes) {
        return (bytes / (1024 * 1024)).toFixed(0);
    }
    
    // Update status
    function updateStatus() {
        fetch('/api/status')
            .then(response => response.json())
            .then(data => {
                // Current time
                const now = Date.now();
                const timeDiff = (now - lastUpdateTime) / 1000; // in seconds
                
                // Service status
                if (data.service_running) {
                    serviceStatus.className = 'status-light active';
                    serviceText.textContent = '📡RUNNING📡';
                    startServiceBtn.disabled = true;
                    stopServiceBtn.disabled = false;
                    restartServiceBtn.disabled = false;
                } else {
                    serviceStatus.className = 'status-light inactive';
                    serviceText.textContent = 'Stopped';
                    startServiceBtn.disabled = false;
                    stopServiceBtn.disabled = true;
                    restartServiceBtn.disabled = true;
                }
                
                // Streaming status
                if (data.streaming_active) {
                    streamingStatus.className = 'status-light active';
                    streamingText.textContent = 'On Air';
                    
                    // LED display
                    streamingLed.className = 'led on';
                    standbyLed.className = 'led';
                } else if (data.service_running) {
                    streamingStatus.className = 'status-light standby';
                    streamingText.textContent = 'Stand By';
                    
                    // LED display
                    streamingLed.className = 'led';
                    standbyLed.className = 'led standby-on';
                } else {
                    streamingStatus.className = 'status-light inactive';
                    streamingText.textContent = 'Stopped';
                    
                    // LED display
                    streamingLed.className = 'led';
                    standbyLed.className = 'led';
                }
                
                // CPU usage
                cpuUsage.textContent = data.cpu_usage.toFixed(1);
                cpuBar.style.width = data.cpu_usage + '%';
                setProgressClass(cpuBar, data.cpu_usage, 70, 90);
                
                // CPU temperature
                cpuTemp.textContent = data.cpu_temp.toFixed(1);
                
                // CPU temperature progress bar (0-100°C scale)
                const tempPercent = Math.min(100, Math.max(0, data.cpu_temp * 100 / 100));
                cpuTempBar.style.width = tempPercent + '%';
                setProgressClass(cpuTempBar, data.cpu_temp, 60, 80);
                
                // Memory usage
                memoryPercent.textContent = data.memory_percent.toFixed(1);
                memoryAvailable.textContent = bytesToMB(data.memory_available);
                memoryTotal.textContent = bytesToMB(data.memory_total);
                memoryBar.style.width = data.memory_percent + '%';
                setProgressClass(memoryBar, data.memory_percent, 70, 90);
                
                // Swap usage
                swapPercent.textContent = data.swap_percent.toFixed(1);
                swapFree.textContent = bytesToMB(data.swap_free);
                swapTotal.textContent = bytesToMB(data.swap_total);
                swapBar.style.width = data.swap_percent + '%';
                setProgressClass(swapBar, data.swap_percent, 70, 90);
                
                // Network usage (KB/s)
                if (lastNetworkSent > 0 && timeDiff > 0) {
                    const sentRate = (data.network_sent - lastNetworkSent) / 1024 / timeDiff;
                    const recvRate = (data.network_recv - lastNetworkRecv) / 1024 / timeDiff;
                    
                    networkSent.textContent = sentRate.toFixed(2);
                    networkRecv.textContent = recvRate.toFixed(2);
                }
                
                // Hide GPIO status if not available
                if (!data.gpio_available) {
                    const gpioStatus = document.getElementById('gpio-status');
                    if (gpioStatus) {
                        gpioStatus.style.display = 'none';
                    }
                }
                
                // Update previous values
                lastNetworkSent = data.network_sent;
                lastNetworkRecv = data.network_recv;
                lastUpdateTime = now;
            })
            .catch(error => {
                console.error('Error fetching status:', error);
            });
    }
    
    // Get and display service status
    function updateServiceStatusOutput() {
        fetch('/api/service/status')
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    document.getElementById('service-status-output').textContent = data.output;
                } else {
                    document.getElementById('service-status-output').textContent = 'Error: ' + data.message;
                }
            })
            .catch(error => {
                console.error('Error fetching service status:', error);
                document.getElementById('service-status-output').textContent = 'Failed to get service status';
            });
    }

    // Get current configuration
    function loadCurrentConfig() {
        fetch('/api/service/config')
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    document.getElementById('address').value = data.address || '0.0.0.0';
                    document.getElementById('port').value = data.port || '1234';
                    
                    // Set sample rate dropdown
                    const sampleRateSelect = document.getElementById('sample-rate');
                    if (data.sample_rate) {
                        // Check if matching option exists
                        const options = Array.from(sampleRateSelect.options);
                        const matchingOption = options.find(option => option.value === data.sample_rate);
                        
                        if (matchingOption) {
                            matchingOption.selected = true;
                        } else {
                            // Add new option if no match found
                            const newOption = document.createElement('option');
                            newOption.value = data.sample_rate;
                            newOption.textContent = data.sample_rate;
                            newOption.selected = true;
                            sampleRateSelect.appendChild(newOption);
                        }
                    }
                } else {
                    console.error('Error loading config:', data.message);
                }
            })
            .catch(error => {
                console.error('Error fetching config:', error);
            });
    }

    // RTL-TCP config form submission
    function setupConfigForm() {
        const form = document.getElementById('rtl-tcp-config-form');
        if (form) {
            form.addEventListener('submit', function(event) {
                event.preventDefault();
                
                const address = document.getElementById('address').value || '0.0.0.0';
                const port = document.getElementById('port').value || '1234';
                const sampleRate = document.getElementById('sample-rate').value;
                
                const configData = {
                    address: address,
                    port: port,
                    sample_rate: sampleRate
                };
                
                // Update configuration
                fetch('/api/service/update_config', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify(configData)
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        alert('RTL-TCP configuration updated and service restarted');
                        // Update status
                        updateServiceStatusOutput();
                    } else {
                        alert('Error: ' + data.message);
                    }
                })
                .catch(error => {
                    console.error('Error updating config:', error);
                    alert('Error occurred while updating configuration');
                });
            });
        }
    }
    
    // Initial status update
    updateStatus();
    
    // Regular status updates (every 1 second)
    setInterval(updateStatus, 1000);
    
    // Service status regular updates
    updateServiceStatusOutput();
    setInterval(updateServiceStatusOutput, 5000); // Every 5 seconds
    
    // Initialize config form
    loadCurrentConfig();
    setupConfigForm();
});""")

# Root route
@app.route('/')
def index():
    return render_template('index.html')

# API endpoint - Get current status
@app.route('/api/status')
def api_status():
    return jsonify(status)

# API endpoint - Start service
@app.route('/api/service/start', methods=['POST'])
def api_service_start():
    try:
        result = subprocess.run(
            ["sudo", "systemctl", "start", "rtl_tcp.service"],
            capture_output=True, text=True, check=False
        )
        if result.returncode == 0:
            return jsonify({"success": True})
        else:
            return jsonify({"success": False, "message": result.stderr})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})

# API endpoint - Stop service
@app.route('/api/service/stop', methods=['POST'])
def api_service_stop():
    try:
        result = subprocess.run(
            ["sudo", "systemctl", "stop", "rtl_tcp.service"],
            capture_output=True, text=True, check=False
        )
        if result.returncode == 0:
            return jsonify({"success": True})
        else:
            return jsonify({"success": False, "message": result.stderr})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})

# API endpoint - Restart service
@app.route('/api/service/restart', methods=['POST'])
def api_service_restart():
    try:
        result = subprocess.run(
            ["sudo", "systemctl", "restart", "rtl_tcp.service"],
            capture_output=True, text=True, check=False
        )
        if result.returncode == 0:
            return jsonify({"success": True})
        else:
            return jsonify({"success": False, "message": result.stderr})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})

# API endpoint - Get service status
@app.route('/api/service/status')
def api_service_status():
    status_output = get_service_status("rtl_tcp.service")
    return jsonify({"success": True, "output": status_output})

# API endpoint - Get current configuration
@app.route('/api/service/config')
def api_service_config():
    config = get_rtl_tcp_config()
    return jsonify({"success": True, **config})

# API endpoint - Get direct command
@app.route('/api/service/direct_command')
def api_direct_command():
    command = get_full_exec_command()
    return jsonify({"success": True, "command": command})

# API endpoint - Update configuration
@app.route('/api/service/update_config', methods=['POST'])
def api_update_config():
    try:
        data = request.json
        
        address = data.get('address', '0.0.0.0')
        port = data.get('port', '1234')
        sample_rate = data.get('sample_rate', '2048000')
        
        success, message = update_rtl_tcp_config(address, port, sample_rate)
        
        return jsonify({"success": success, "message": message})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})

# API endpoint - Update direct command
@app.route('/api/service/update_direct', methods=['POST'])
def api_update_direct():
    try:
        data = request.json
        command = data.get('command', '')
        
        success, message = update_direct_command(command)
        
        return jsonify({"success": success, "message": message})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})

if __name__ == "__main__":
    create_static_files()
    
    status_thread = threading.Thread(target=update_status_loop, daemon=True)
    status_thread.start()
    
    app.run(host='0.0.0.0', port=5678, debug=True)
