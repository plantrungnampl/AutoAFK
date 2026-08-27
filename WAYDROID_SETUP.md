# Chạy AutoAFK với Waydroid trên Linux

Hướng dẫn setup Waydroid (Android container native cho Linux) làm emulator cho AutoAFK trên Arch/CachyOS với KDE Wayland.

## 1. Cài đặt phụ thuộc

```bash
# ADB và Waydroid
sudo pacman -S android-tools waydroid

# Tk cho GUI AutoAFK
sudo pacman -S tk
```

## 2. Khởi tạo Waydroid

```bash
sudo waydroid init -s GAPPS
```

Quá trình này tải Android system image + GApps (~800MB), mất 5-15 phút.

## 3. Fix firewall cho Waydroid

Đây là bước quan trọng nhất — UFW (firewall mặc định Arch/CachyOS) sẽ block DNS/DHCP của container nếu không config:

```bash
sudo ufw allow 53                  # DNS
sudo ufw allow 67                  # DHCP
sudo ufw default allow FORWARD     # cho phép forward traffic
sudo ufw reload
```

Nếu dùng iptables thuần (không UFW):
```bash
sudo iptables -P FORWARD ACCEPT
```

Nếu dùng firewalld:
```bash
sudo firewall-cmd --zone=trusted --add-interface=waydroid0 --permanent
sudo firewall-cmd --reload
```

## 4. Disable ADB authentication

Mặc định Waydroid yêu cầu authorize ADB key qua dialog UI mỗi lần kết nối. Tắt nó cho tiện:

```bash
sudo sed -i 's/ro.adb.secure=1/ro.adb.secure=0/' /var/lib/waydroid/waydroid_base.prop
```

## 5. Cài libhoudini (ARM translation)

Waydroid x86_64 không chạy được APK chỉ có ARM (như AFK Arena). Cài libhoudini để dịch ARM → x86:

```bash
git clone https://github.com/casualsnek/waydroid_script.git /tmp/waydroid_script
python3 -m venv /tmp/waydroid_script/venv
/tmp/waydroid_script/venv/bin/pip install -r /tmp/waydroid_script/requirements.txt
sudo /tmp/waydroid_script/venv/bin/python3 /tmp/waydroid_script/main.py install libhoudini
```

> Lưu ý: script này có thể reset `ro.adb.secure` về 1, chạy lại lệnh sed ở bước 4 nếu cần.

Verify ARM translation hoạt động:
```bash
adb shell getprop ro.product.cpu.abilist
# Phải có arm64-v8a, armeabi-v7a
```

## 6. Khởi động Waydroid

```bash
# Khởi động container service
sudo systemctl start waydroid-container

# Khởi động session
waydroid session start &

# Đợi 10-15s cho đến khi log hiện "Android with user 0 is ready"

# Mở UI Android
waydroid show-full-ui &
```

## 7. Kết nối ADB

```bash
adb connect 192.168.240.112:5555
adb devices  # Phải hiển thị "device" (không phải "unauthorized" hay "offline")
```

Nếu IP mặc định không hoạt động (`waydroid status` báo `IP address: UNKNOWN`), cấp IP thủ công:

```bash
sudo waydroid shell -- ip addr add 192.168.240.112/24 dev eth0
sudo waydroid shell -- ip route add default via 192.168.240.1 dev eth0
```

## 8. Cài AFK Arena

### Cách A: từ Play Store (cần đăng nhập Google)

Trong Waydroid UI → mở Play Store → đăng nhập → search "AFK Arena" → Install.

### Cách B: cài APK qua ADB (không cần Google)

Tải APK Bundle (`.apkm`) từ APKMirror:

```bash
# Extract APK bundle
mkdir -p /tmp/afkarena_apk
unzip -o /path/to/AFKArena.apkm -d /tmp/afkarena_apk

# Cài split APKs (base + ARM + DPI matching + assets)
adb install-multiple -r \
  /tmp/afkarena_apk/base.apk \
  /tmp/afkarena_apk/split_config.arm64_v8a.apk \
  /tmp/afkarena_apk/split_config.xhdpi.apk \
  /tmp/afkarena_apk/split_extraAsset.apk

# Launch game
adb shell am start -n com.lilithgame.hgame.gp/sh.lilithgame.hgame.AppActivity
```

Chọn split APK theo:
- **ABI**: `arm64_v8a` (Waydroid x86_64 + libhoudini hỗ trợ)
- **DPI**: kiểm tra bằng `adb shell wm density`. Override 240 → dùng `xhdpi`

## 9. Cấu hình resolution cho AutoAFK

AutoAFK yêu cầu **1080x1920 (portrait) DPI 240**:

```bash
waydroid prop set persist.waydroid.width 1080
waydroid prop set persist.waydroid.height 1920

# Restart session để áp dụng
waydroid session stop
waydroid session start &
```

> Cảnh báo: cửa sổ portrait 1080x1920 sẽ vượt chiều cao màn hình laptop/monitor 1080p. Bạn có thể bỏ qua resolution này nếu chỉ chạy AutoAFK ở chế độ headless và không cần tương tác UI Waydroid.

## 10. Cấu hình AutoAFK

Mở `settings.ini`:

```ini
[ADVANCED]
port = 5555
deviceip = 192.168.240.112
adbrestart = False
emulatorpath = 
loadingmuliplier = 1.0
debug = False
```

> Cần các sửa đổi ở `src/core/device_manager.py` để hỗ trợ `deviceip` và bỏ qua kill ADB khi `adbrestart = False` (đã apply trong workspace này).

## 11. Chạy AutoAFK

```bash
.venv/bin/python3 main.py
```

Bấm **Run Dailies** trong GUI.

---

## Quick start (lần sau)

Sau khi setup lần đầu, mỗi phiên chỉ cần:

```bash
# 1. Khởi động Waydroid
sudo systemctl start waydroid-container
waydroid session start &
sleep 10
waydroid show-full-ui &

# 2. Cấp IP (nếu IP UNKNOWN)
sudo waydroid shell -- ip addr add 192.168.240.112/24 dev eth0

# 3. Kết nối ADB
adb connect 192.168.240.112:5555

# 4. Chạy AutoAFK
cd /Data/AutoAFK && .venv/bin/python3 main.py
```

Hoặc dùng script tự động: `sudo ./waydroid-net-fix.sh`

---

## Troubleshooting

### Apps báo "Failed to connect. Please check your network settings"

→ UFW đang block. Quay lại bước 3.

Verify mạng từ container:
```bash
adb shell dumpsys connectivity --short | grep -E "DnsAddresses|Routes"
```
- `DnsAddresses: [ ]` rỗng → UFW chặn DNS hoặc Waydroid không lấy DHCP
- Thiếu route `0.0.0.0/0` → forward bị chặn

### `IP address: UNKNOWN` trong `waydroid status`

Container không tự cấu hình mạng (thường do firewall block DHCP). Sửa UFW (bước 3) rồi restart, hoặc cấp IP thủ công ở bước 7.

### `failed to authenticate to 192.168.240.112:5555`

`ro.adb.secure=1`. Quay lại bước 4 và restart Waydroid:
```bash
waydroid session stop
sudo systemctl restart waydroid-container
waydroid session start &
```

### `failed to connect: No route to host`

Container chưa boot xong, bị FROZEN, hoặc mất IP. Mở `waydroid show-full-ui` để wake up container.

### `Container: FROZEN`

Waydroid tự freeze container khi UI không hiển thị quá lâu. Mở lại UI để unfreeze.

### APK ARM-only báo lỗi khi launch

Chưa cài libhoudini. Quay lại bước 5.

### Cửa sổ Waydroid bị khuất (vượt chiều cao màn hình)

Resolution 1080x1920 lớn hơn màn hình 1080p. Tạm thời clear:
```bash
waydroid prop set persist.waydroid.width ""
waydroid prop set persist.waydroid.height ""
waydroid session stop && waydroid session start &
```

### Hết kết nối sau khi đóng AutoAFK

AutoAFK gọi `adb kill-server` khi đóng nếu `adbrestart = True`. Set `adbrestart = False` trong `settings.ini`. Hoặc reconnect:
```bash
adb start-server
adb connect 192.168.240.112:5555
```

---

## Tham khảo

- [Waydroid Networking Docs](https://docs.waydro.id/debugging/networking-issues) — fix firewall chính thức
- [waydroid_script (libhoudini)](https://github.com/casualsnek/waydroid_script) — ARM translation cho APK
- [APKMirror](https://www.apkmirror.com/) — tải APK Bundle
