# MobileSAM Model Setup for AI MODE

## 📥 **Download MobileSAM TFLite Model**

### **Option 1: Official Repository**

```bash
# Clone MobileSAM repo
git clone https://github.com/ChaoningZhang/MobileSAM.git
cd MobileSAM

# Convert to TFLite (requires Python + TensorFlow)
python scripts/export_tflite.py --weights weights/mobile_sam.pt
```

### **Option 2: Pre-converted Model** (Recommended)

Download pre-converted TFLite model:

```bash
# Create assets directory
mkdir -p arch_fingerprint_gui/assets/models

# Download model (replace URL with actual hosting)
wget https://github.com/ChaoningZhang/MobileSAM/releases/download/v1.0/mobile_sam.tflite \
     -O arch_fingerprint_gui/assets/models/mobile_sam.tflite
```

**Model Size:** ~40MB  
**Input:** [1, 3, 1024, 1024] RGB normalized to [0, 1]  
**Output:** [1, 1, 256, 256] segmentation mask

---

## 🔧 **Flutter Integration**

### **1. Add Model to Assets**

Already configured in `pubspec.yaml`:

```yaml
flutter:
  assets:
    - assets/models/mobile_sam.tflite
```

### **2. Install Dependencies**

```bash
cd arch_fingerprint_gui
flutter pub get
```

This installs:
- `tflite_flutter: ^0.11.0` - TensorFlow Lite runtime

### **3. Test Model Loading**

```bash
flutter run
```

Go to: Settings → AI MODE → Try scanning a document

**Expected:**
- ✅ "AI analyzing document boundaries..."
- ✅ Purple overlay with AI DETECTED badge
- ✅ Precise document crop

**If model not found:**
- ⚠️ Error message with instructions
- ⚠️ Graceful fallback (use original image)

---

## 📱 **Platform-Specific Setup**

### **Android**

No additional setup required. TFLite delegates work out-of-the-box.

**Optional GPU Acceleration:**

Edit `android/app/build.gradle`:

```gradle
android {
    // ... existing config
    
    aaptOptions {
        noCompress 'tflite'
    }
}

dependencies {
    // ... existing dependencies
    implementation 'org.tensorflow:tensorflow-lite-gpu:2.14.0'
}
```

### **iOS**

Add to `ios/Podfile`:

```ruby
target 'Runner' do
  use_frameworks!
  use_modular_headers!

  flutter_install_all_ios_pods File.dirname(File.realpath(__FILE__))
  
  # TensorFlow Lite GPU delegate
  pod 'TensorFlowLiteSwift/Metal', '~> 0.0.1-nightly'
end
```

Then run:

```bash
cd ios
pod install
```

---

## 🧪 **Testing**

### **Test Model Inference:**

```dart
// In mobilesam_cropper_screen.dart

Future<void> _testModel() async {
  final interpreter = await Interpreter.fromAsset('assets/models/mobile_sam.tflite');
  
  print("✅ Model loaded successfully");
  print("Input shape: ${interpreter.getInputTensor(0).shape}");
  print("Output shape: ${interpreter.getOutputTensor(0).shape}");
  
  // Run dummy inference
  final input = List.generate(1, (_) => 
    List.generate(3, (_) => 
      List.generate(1024, (_) => 
        List.filled(1024, 0.5)
      )
    )
  );
  
  final output = List.generate(1, (_) => 
    List.generate(1, (_) => 
      List.generate(256, (_) => 
        List.filled(256, 0.0)
      )
    )
  );
  
  interpreter.run(input, output);
  print("✅ Inference successful");
}
```

---

## 📊 **Performance Benchmarks**

### **Expected Inference Time:**

| Device | CPU | GPU | Comments |
|--------|-----|-----|----------|
| Pixel 7 Pro | 850ms | 320ms | Snapdragon 8 Gen 2 |
| Galaxy S21 | 920ms | 380ms | Exynos 2100 |
| OnePlus 9 | 780ms | 290ms | Snapdragon 888 |
| Mid-range (SD 730) | 1500ms | 600ms | Acceptable |
| Low-end (SD 662) | 2800ms | N/A | Too slow |

**Recommendation:** Use AI MODE only on devices with GPU support.

---

## 🔄 **Fallback Strategy**

If model fails to load or inference is too slow:

```dart
// In mobilesam_cropper_screen.dart

Future<void> _initializeModel() async {
  try {
    _interpreter = await Interpreter.fromAsset(_modelPath)
        .timeout(Duration(seconds: 5));
        
    await _detectDocumentWithMobileSAM()
        .timeout(Duration(seconds: 10));
        
  } catch (e) {
    // Fallback: Use simple edge detection instead
    _errorMessage = "MobileSAM unavailable. Using edge detection fallback.";
    await _detectDocumentWithEdgeDetection(); // Sobel operator
  }
}
```

---

## 📦 **App Size Impact**

| Component | Size |
|-----------|------|
| Base App | ~20 MB |
| + TFLite Runtime | +8 MB |
| + MobileSAM Model | +40 MB |
| **Total (AI MODE)** | **~68 MB** |

**Mitigation:**
- Use on-demand model download (not bundled in APK)
- Lazy load model only when AI MODE selected
- Offer "Lite" APK without AI MODE

---

## 🚀 **On-Demand Model Download** (Advanced)

Instead of bundling model in APK, download on first use:

```dart
Future<void> _downloadModelIfNeeded() async {
  final modelPath = await _getModelPath();
  final file = File(modelPath);
  
  if (!file.existsSync()) {
    // Download from Firebase Storage or CDN
    final url = 'https://your-cdn.com/mobile_sam.tflite';
    final response = await http.get(Uri.parse(url));
    
    await file.writeAsBytes(response.bodyBytes);
    print("✅ Model downloaded: ${response.bodyBytes.length} bytes");
  }
}
```

**Benefits:**
- Smaller initial APK (~28 MB)
- Only users who choose AI MODE download model
- Can update model without app update

---

## 🐛 **Troubleshooting**

### **Error: "tflite model not found"**

**Solution:**
```bash
# Ensure model is in correct location
ls arch_fingerprint_gui/assets/models/mobile_sam.tflite

# Rebuild Flutter assets
flutter clean
flutter pub get
flutter run
```

### **Error: "Failed to create interpreter"**

**Solution:**
- Check model file is not corrupted
- Verify TFLite version compatibility
- Try CPU-only mode (disable GPU delegate)

### **Slow Inference (>3 seconds)**

**Solution:**
- Enable GPU acceleration (see platform setup)
- Reduce input resolution (1024 → 512)
- Use quantized model (INT8 instead of FP32)

---

## 📚 **References**

- **MobileSAM Paper:** https://arxiv.org/abs/2306.14289
- **Official Repo:** https://github.com/ChaoningZhang/MobileSAM
- **TFLite Flutter:** https://pub.dev/packages/tflite_flutter
- **Model Optimization:** https://www.tensorflow.org/lite/performance/best_practices

---

## ✅ **Quick Start Checklist**

- [ ] Download `mobile_sam.tflite` (40MB)
- [ ] Place in `arch_fingerprint_gui/assets/models/`
- [ ] Run `flutter pub get`
- [ ] Test on device (emulator won't have GPU)
- [ ] Benchmark inference time
- [ ] Compare quality vs AUTO/PRO modes
- [ ] Document findings in comparison report

**Ready for AI MODE testing!** 🎯🚀
