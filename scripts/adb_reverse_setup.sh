#!/bin/bash
# =============================================================================
# adb_reverse_setup.sh
# Jalankan script ini sekali untuk setup auto adb-reverse saat HP tersambung.
# Setelah setup, cukup colok HP dan port 8000 otomatis ter-forward.
# =============================================================================

VENDOR_ID="22d9"   # OPPO/Realme vendor ID
PORT=8000
RULE_FILE="/etc/udev/rules.d/99-adb-reverse.rules"
SCRIPT_FILE="/usr/local/bin/adb-reverse-arch.sh"

echo "=== Setup Auto adb reverse untuk ARCH-FINGERPRINT ==="

# 1. Buat script yang dipanggil udev
sudo tee "$SCRIPT_FILE" > /dev/null << 'EOF'
#!/bin/bash
# Tunggu sebentar agar adb server siap
sleep 2
export HOME=/root
/usr/bin/adb -s "$1" reverse tcp:8000 tcp:8000 >> /tmp/adb-reverse.log 2>&1
echo "[$(date)] adb reverse done for $1" >> /tmp/adb-reverse.log
EOF

sudo chmod +x "$SCRIPT_FILE"
echo "✅ Script dibuat: $SCRIPT_FILE"

# 2. Buat udev rule
sudo tee "$RULE_FILE" > /dev/null << EOF
# Auto adb reverse saat HP Realme/OPPO tersambung via USB
SUBSYSTEM=="usb", ATTR{idVendor}=="$VENDOR_ID", ACTION=="add", RUN+="$SCRIPT_FILE %k"
EOF

echo "✅ udev rule dibuat: $RULE_FILE"

# 3. Reload udev
sudo udevadm control --reload-rules
sudo udevadm trigger
echo "✅ udev rules di-reload"

echo ""
echo "=== Selesai! ==="
echo "Sekarang setiap kali HP di-colok, adb reverse tcp:$PORT tcp:$PORT akan"
echo "berjalan otomatis. Log tersimpan di /tmp/adb-reverse.log"
echo ""
echo "Untuk cek log: cat /tmp/adb-reverse.log"
