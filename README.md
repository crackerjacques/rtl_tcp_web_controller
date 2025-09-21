# RTL-TCP Web Frontend

<img width="700" height="910" alt="2025-09-21_23-18-41" src="https://github.com/user-attachments/assets/72510499-03bd-4171-b22a-29c1c0040c57" />

# Setup RTL-SDR

```
# install rtlsdr
sudo apt install libusb-1.0.0-dev pkg-config build-essential cmake # optional -> cmake-curses-gui 
git clone https://github.com/rtlsdrblog/rtl-sdr-blog.git
cd rtl-sdr-blog
mkdir build ; cd build
cmake -DINSTALL_UDEV_RULES=ON -DDETACH_KERNEL_DRIVER=ON -DENABLE_ZEROCOPY=ON .. # or ccmake ..
make -j$(nproc)
sudo make install
sudo ldconfig
```

__Setup blacklist if rtl-sdr did not work.__
```
echo -e "blacklist dvb_usb_rtl28xxu\nblacklist rtl2830\nblacklist dvb_usb_v2\nblacklist dvb_core" | sudo tee /etc/modprobe.d/rtlsdr-blacklist.conf > /dev/null
sudo depmod -a
sudo update-initramfs -u # or sudo reboot
```

# With auto installer script
```
# Clone this repo
git clone https://github.com/crackerjacques/rtl_tcp_web_controller.git
cd rtl_tcp_web_controller
chmod +x install.sh
./install.sh

# Please answer the questions several times.
```

# Manual install

```
# main script
mv rtl_web_monitor_[your_gpio].py rtl_web_monitor.py
chmod +x rtl_web_monitor.py
sudo cp rtl_web_monitor.py /usr/bin
```

__edit service file__

```
nano rtl_web_monitor.service
```

```
# Edit path to your install dir (e.g. /usr/bin/rtl_tcp  , /opt/bin/rtl_tcp  )

[Service]
ExecStart=/usr/local/bin/rtl_tcp -a 0.0.0.0 -s 2400000

```
sudo cp rtl_tcp.service /etc/systemd/system/
sudo cp rtl_web_monitor.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now rtl_tcp.service
sudo systemctl enable --now rtl_web_monitor.service \

```
