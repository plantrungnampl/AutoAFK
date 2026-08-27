# Chạy AutoAFK với Genymotion

Setup ngắn cho Genymotion Personal (Linux/Windows/macOS). Đơn giản hơn Waydroid vì
Genymotion đã lo phần ADB, ARM translation, networking, và display.

## 1. Cài đặt

- Genymotion Desktop: <https://www.genymotion.com/download/>
  (cần tài khoản free Personal Edition)
- VirtualBox (bản Linux/Windows; macOS Apple Silicon dùng backend khác)
- ADB:
  ```bash
  # Linux / Arch
  sudo pacman -S android-tools

  # macOS
  brew install --cask android-platform-tools
  ```

## 2. Tạo virtual device

Mở Genymotion → **+ Add a new virtual device** → chọn:

| Field | Value |
|-------|-------|
| Device model | **Pixel 5** (hoặc bất kỳ device nào ở **1080×1920 portrait, DPI 240**) |
| Android version | 9.0 hoặc 11.0 |
| Form factor | Phone |

Ấn **Install** rồi **Start**. Lần đầu boot mất 30–60 s.

> Nếu device list không có sẵn 1080×1920 dpi 240, click **Custom** và nhập tay.
> AutoAFK template được crop ở resolution này; sai sẽ làm `image_recognition` miss.

## 3. Cài AFK Arena

- **Cách A**: trong Genymotion → biểu tượng **Open GApps** ở sidebar phải để cài
  Play Store, đăng nhập Google, search "AFK Arena", Install.
- **Cách B**: tải APK Bundle từ APKMirror, chọn `arm64-v8a` + `xhdpi` (cho dpi 240),
  rồi `adb install foo.apk` hoặc kéo-thả vào cửa sổ Genymotion.

## 4. Kiểm tra ADB

```bash
adb devices
# Mong đợi: 127.0.0.1:6555  device   (port của instance Genymotion đầu tiên)

adb -s 127.0.0.1:6555 shell wm size
# Mong đợi: Physical size: 1080x1920

adb -s 127.0.0.1:6555 shell wm density
# Mong đợi: Physical density: 240
```

Nếu instance thứ hai chạy thì port sẽ là `5557`, `5559`… Genymotion cấp port
theo công thức `5555 + 2*i`.

## 5. Cấu hình AutoAFK

`settings.ini` đã có sẵn block `[ADVANCED]`:

```ini
[ADVANCED]
port = 6555
deviceip = 127.0.0.1
```

Đổi `port` cho khớp output của `adb devices` nếu khác.

## 6. Chạy AutoAFK

```bash
# GUI
python main.py

# Headless dailies
python main.py --dailies

# Push tower King's Tower
python main.py --tower kt

# Dev recorder (chỉ developer)
python main.py --llm-recorder
```

## Troubleshooting

### `adb devices` rỗng
- Genymotion chưa boot xong → đợi 30–60 s, hoặc xem trong cửa sổ Genymotion đã
  vào homescreen chưa.
- ADB server lệch phiên bản: `adb kill-server && adb start-server`.

### `failed to connect to 127.0.0.1:6555: Connection refused`
- Genymotion chưa start → nhấn nút Play trên virtual device.
- Hoặc port khác — `adb devices` xem chính xác port.

### Game lag / OpenCV match miss
- Vào Settings của virtual device tăng RAM lên 4096 MB, CPU 4 cores.
- Bật **GPU Mode = Hardware** (mặc định nhưng nhiều khi bị fallback Software).

### Resolution sai sau khi đổi device
Genymotion cho đổi resolution runtime: **Display → Resolution**, chọn 1080×1920.

## Notes

- Genymotion hỗ trợ ARM dịch sang x86 trong nhân, không cần libhoudini như Waydroid.
- Khác với Waydroid, Genymotion **không** dùng `[ADVANCED] emulatorpath` để tự
  bật emulator. Bạn tự bật instance Genymotion trước rồi chạy AutoAFK.
- Nếu định build `.exe` cho người khác (`build.bat`), Genymotion phía bạn chỉ
  để dev/test; người dùng cuối tự dùng emulator của họ (Bluestacks, LDPlayer,
  MEmu…).
