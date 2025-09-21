#!/bin/bash

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
RAINBOW='\033[1;31m\033[1;33m\033[1;32m\033[1;36m\033[1;34m\033[1;35m'
NC='\033[0m' # No Color

# Script configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="/usr/bin"
SERVICE_DIR="/etc/systemd/system"
CONFIG_DIR="/etc/rtl_web_monitor"

# print colored output
print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# check if running as root/sudo
check_sudo() {
    if [[ $EUID -eq 0 ]]; then
        print_error "This script should not be run as root directly."
        print_info "Please run: ./install.sh (without sudo)"
        print_info "The script will ask for sudo when needed."
        exit 1
    fi
    
    if ! sudo -v 2>/dev/null; then
        print_error "This script requires sudo permissions."
        print_info "Please ensure you can run sudo commands."
        exit 1
    fi
    
    print_success "Sudo access confirmed"
}

# check RTL-SDR installation
check_rtl_sdr() {
    print_info "Checking for RTL-SDR installation..." >&2
    
    # Check for rtl_tcp in common locations using simple file tests
    if [[ -f "/usr/local/bin/rtl_tcp" ]]; then
        print_success "RTL-SDR found at: /usr/local/bin/rtl_tcp" >&2
        echo "/usr/local/bin/rtl_tcp"
        return 0
    elif [[ -f "/usr/bin/rtl_tcp" ]]; then
        print_success "RTL-SDR found at: /usr/bin/rtl_tcp" >&2
        echo "/usr/bin/rtl_tcp"
        return 0
    else
        local rtl_tcp_path
        rtl_tcp_path=$(timeout 3 which rtl_tcp 2>/dev/null || echo "")
        if [[ -n "$rtl_tcp_path" && -f "$rtl_tcp_path" ]]; then
            print_success "RTL-SDR found at: $rtl_tcp_path" >&2
            echo "$rtl_tcp_path"
            return 0
        fi
        
        # RTL-SDR not found
        return 1
    fi
}

# show RTL-SDR not found message and exit
show_rtl_sdr_not_found() {
    echo
    print_error "RTL-SDR (rtl_tcp) not found!"
    echo
    print_warning "Please install RTL-SDR first before running this installer."
    echo
    print_info "Installation options:"
    print_info "1. Package manager: sudo apt-get install rtl-sdr"
    print_info "2. From source: https://github.com/rtlsdrblog/rtl-sdr-blog"
    echo
    print_info "After installing RTL-SDR, run this installer again."
    echo
    exit 1
}

# update rtl_tcp.service with correct path
update_rtl_tcp_service_path() {
    local rtl_tcp_path="$1"
    
    if [[ -f "$SCRIPT_DIR/rtl_tcp.service" ]]; then
        local temp_service="/tmp/rtl_tcp.service.tmp"
        
        while IFS= read -r line; do
            if [[ $line =~ ^ExecStart= ]]; then
                local args=$(echo "$line" | sed -E 's/^ExecStart=.*rtl_tcp(.*)/\1/')
                echo "ExecStart=${rtl_tcp_path}${args}"
            else
                echo "$line"
            fi
        done < "$SCRIPT_DIR/rtl_tcp.service" > "$temp_service"
        
        # Move the temporary file back
        mv "$temp_service" "$SCRIPT_DIR/rtl_tcp.service"
        
        print_info "Updated rtl_tcp.service with path: $rtl_tcp_path"
    fi
}

get_cpu_cores() {
    nproc 2>/dev/null || echo "1"
}

check_library() {
    local lib_name="$1"
    local search_paths=("/usr/local/lib" "/usr/lib" "/usr/lib/x86_64-linux-gnu" "/usr/lib/aarch64-linux-gnu" "/usr/lib/arm-linux-gnueabihf")
    
    for path in "${search_paths[@]}"; do
        if find "$path" -name "*${lib_name}*" 2>/dev/null | grep -q .; then
            return 0
        fi
    done
    return 1
}

# install lgpio library
install_lgpio() {
    print_info "Installing lgpio library..."
    
    sudo apt-get update
    sudo apt-get install -y swig python3-dev python3-setuptools git build-essential
    
    cd /tmp
    
    rm -rf lg
    
    print_info "Cloning lgpio repository..."
    git clone https://github.com/joan2937/lg.git
    cd lg
    
    print_info "Building lgpio with $(get_cpu_cores) cores..."
    make -j$(get_cpu_cores)
    
    print_info "Installing lgpio..."
    sudo make install
    sudo ldconfig
    
    cd ../
    
    print_success "lgpio library installed successfully"
}

# install WiringPi library
install_wiringpi() {
    print_info "Installing WiringPi library..."
    
    sudo apt-get update
    sudo apt-get install -y python3-dev python3-setuptools swig git build-essential
    
    cd /tmp
    
    rm -rf WiringPi WiringPi-Python
    
    print_info "Cloning WiringPi repository..."
    git clone https://github.com/WiringPi/WiringPi
    cd WiringPi
    ./build
    cd ../
    
    print_info "Installing WiringPi Python bindings..."
    git clone --recursive https://github.com/WiringPi/WiringPi-Python.git
    cd WiringPi-Python
    sudo python3 setup.py install
    cd ../
    
    print_success "WiringPi library installed successfully"
}

check_and_install_deps() {
    local version="$1"
    
    case "$version" in
        "wiringpi")
            if ! check_library "wiringPi"; then
                print_warning "WiringPi library not found"
                install_wiringpi
            else
                print_success "WiringPi library found"
            fi
            ;;
        "lgpio")
            if ! check_library "lgpio"; then
                print_warning "lgpio library not found"
                install_lgpio
            else
                print_success "lgpio library found"
            fi
            ;;
        "non-gpio")
            print_info "No GPIO library required for this version"
            ;;
    esac
}

# install Python dependencies
install_python_deps() {
    print_info "Installing Python dependencies..."
    sudo apt-get update
    
    print_info "Installing Python packages via apt..."
    sudo apt-get install -y \
        python3 \
        python3-dev \
        python3-flask \
        python3-psutil
    
    if ! python3 -c "import flask" 2>/dev/null; then
        print_warning "Flask not found via apt, installing via pip3..."
        sudo apt-get install -y python3-pip
        sudo pip3 install flask
    fi
    
    if ! python3 -c "import psutil" 2>/dev/null; then
        print_warning "psutil not found via apt, installing via pip3..."
        sudo apt-get install -y python3-pip
        sudo pip3 install psutil
    fi
    
    print_success "Python dependencies installed"
}

# install the selected version
install_version() {
    local version="$1"
    local source_file=""
    local target_file="rtl_web_monitor.py"
    
    case "$version" in
        "non-gpio")
            source_file="rtl_web_monitor_non-gpio.py"
            ;;
        "wiringpi")
            source_file="rtl_web_monitor_wp.py"
            ;;
        "lgpio")
            source_file="rtl_web_monitor_lg.py"
            ;;
    esac
    
    if [[ ! -f "$SCRIPT_DIR/$source_file" ]]; then
        print_error "Source file $source_file not found in $SCRIPT_DIR"
        exit 1
    fi
    
    # Check and install GPIO dependencies
    check_and_install_deps "$version"
    
    # Install Python dependencies
    install_python_deps
    
    # Copy the main script and rename it
    print_info "Installing $source_file to $INSTALL_DIR/$target_file"
    sudo cp "$SCRIPT_DIR/$source_file" "$INSTALL_DIR/$target_file"
    sudo chmod +x "$INSTALL_DIR/$target_file"
    
    print_success "Installation completed successfully!"
}

# install services
install_services() {
    print_info "Installing systemd services..."
    
    # Copy service files
    if [[ -f "$SCRIPT_DIR/rtl_web_monitor.service" ]]; then
        print_info "Installing web monitor service file"
        sudo cp "$SCRIPT_DIR/rtl_web_monitor.service" "$SERVICE_DIR/"
    else
        print_error "rtl_web_monitor.service not found!"
        return 1
    fi
    
    if [[ -f "$SCRIPT_DIR/rtl_tcp.service" ]]; then
        print_info "Installing RTL-TCP service file"
        sudo cp "$SCRIPT_DIR/rtl_tcp.service" "$SERVICE_DIR/"
    else
        print_error "rtl_tcp.service not found!"
        return 1
    fi
    
    sudo mkdir -p "$CONFIG_DIR"
    sudo mkdir -p "$CONFIG_DIR/static/css"
    sudo mkdir -p "$CONFIG_DIR/static/js"
    sudo mkdir -p "$CONFIG_DIR/templates"
    
    print_info "Reloading systemd daemon..."
    sudo systemctl daemon-reload
    
    print_success "Services installed successfully!"
}

# start services
start_services() {
    print_info "Enabling and starting services..."
    
    sudo systemctl enable --now rtl_web_monitor.service
    sudo systemctl enable --now rtl_tcp.service
    
    if systemctl is-active --quiet rtl_web_monitor.service; then
        print_success "RTL Web Monitor service is running"
    else
        print_warning "RTL Web Monitor service failed to start"
        print_info "Check logs with: sudo journalctl -u rtl_web_monitor.service"
    fi
    
    if systemctl is-active --quiet rtl_tcp.service; then
        print_success "RTL-TCP service is running"
    else
        print_info "RTL-TCP service is not running (this is normal, it can be started via web interface)"
    fi
}

# get IP address
get_ip_address() {
    hostname -I | awk '{print $1}' || echo "localhost"
}

# show completion message
show_completion() {
    local ip_addr=$(get_ip_address)
    
    echo
    print_success "=== Installation Complete! ==="
    echo
    print_info "Access your RTL-SDR Web Monitor at:"
    echo -e "${CYAN}  Local:  http://localhost:5678${NC}"
    echo -e "${CYAN}  Network: http://${ip_addr}:5678${NC}"
    echo
    echo -e "${RAINBOW}Enjoy!!${NC}"
    echo
}

# uninstall
uninstall() {
    print_warning "=== Uninstalling RTL-SDR Web Monitor ==="
    echo
    
    print_info "Stopping services..."
    sudo systemctl stop rtl_web_monitor.service 2>/dev/null || true
    sudo systemctl stop rtl_tcp.service 2>/dev/null || true
    sudo systemctl disable rtl_web_monitor.service 2>/dev/null || true
    sudo systemctl disable rtl_tcp.service 2>/dev/null || true
    
    print_info "Removing service files..."
    sudo rm -f "$SERVICE_DIR/rtl_web_monitor.service"
    sudo rm -f "$SERVICE_DIR/rtl_tcp.service"
    
    print_info "Removing main script..."
    sudo rm -f "$INSTALL_DIR/rtl_web_monitor.py"
    
    print_info "Removing configuration directory..."
    sudo rm -rf "$CONFIG_DIR"
    
    sudo systemctl daemon-reload
    
    print_success "Uninstallation completed!"
    print_info "Note: GPIO libraries (WiringPi/lgpio) were not removed"
    print_info "Note: Python packages were not removed"
}

# Main menu
show_menu() {
    echo
    print_info "=== RTL-SDR Web Monitor Installation ==="
    echo
    print_warning "This installer requires sudo permissions for:"
    print_warning "- Installing system packages and libraries"
    print_warning "- Copying files to system directories"
    print_warning "- Setting up systemd services"
    echo
    echo -e "${GREEN}Please select an option:${NC}"
    echo -e "${GREEN}1) Non-GPIO version (no LED indicators)${NC}"
    echo -e "${GREEN}2) WiringPi version (for old systems)${NC}"
    echo -e "${GREEN}3) lgpio version (modern GPIO library)${NC}"
    echo -e "${GREEN}4) Uninstall${NC}"
    echo -e "${GREEN}5) Exit${NC}"
    echo
}

main() {
    local choice
    local version
    local rtl_tcp_path
    
    check_sudo
    
    # Check for RTL-SDR installation and capture the path
    rtl_tcp_path=$(check_rtl_sdr)
    if [[ $? -ne 0 ]]; then
        show_rtl_sdr_not_found
    fi
    
    while true; do
        show_menu
        echo -e "${GREEN}Enter your choice (1-5):${NC} "
        read choice
        
        case $choice in
            1)
                version="non-gpio"
                print_info "Selected: Non-GPIO version"
                break
                ;;
            2)
                version="wiringpi"
                print_info "Selected: WiringPi version (for old systems)"
                break
                ;;
            3)
                version="lgpio"
                print_info "Selected: lgpio version"
                break
                ;;
            4)
                uninstall
                exit 0
                ;;
            5)
                print_info "Installation cancelled"
                exit 0
                ;;
            *)
                print_error "Invalid choice. Please enter 1-5."
                ;;
        esac
    done
    
    update_rtl_tcp_service_path "$rtl_tcp_path"
    
    # Confirm installation
    echo
    print_warning "About to install RTL-SDR Web Monitor ($version version)"
    echo -e "${GREEN}Continue? (Y/n):${NC} "
    read -n 1 -r
    echo
    if [[ $REPLY =~ ^[Nn]$ ]]; then
        print_info "Installation cancelled"
        exit 0
    fi
    
    # Perform installation
    print_info "Starting installation..."
    install_version "$version"
    
    # Ask about installing services
    echo
    echo -e "${GREEN}Install systemd services? (Y/n):${NC} "
    read -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Nn]$ ]]; then
        install_services
        
        # Ask about starting services
        echo
        echo -e "${GREEN}Start services now? (Y/n):${NC} "
        read -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Nn]$ ]]; then
            start_services
        fi
    fi
    
    show_completion
}

# Check if script is being sourced or executed
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi