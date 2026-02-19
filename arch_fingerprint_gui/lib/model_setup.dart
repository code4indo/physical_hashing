import 'dart:io';
import 'package:path_provider/path_provider.dart';

/// Manages MobileSAM model setup and download
class ModelSetup {
  static const String _modelFileName = 'mobile_sam.tflite';
  static const String _modelDir = 'models';
  
  /// Download instructions for setting up MobileSAM model
  static const String SETUP_INSTRUCTIONS = """
MobileSAM Model Setup Required for AI MODE

The AI MODE requires the MobileSAM TensorFlow Lite model to function.

OPTION 1: Manual Download (Recommended for large files)
=========================================================
1. Download mobile_sam.tflite from:
   https://github.com/ChainBreak/mobile-sam (releases section)
   or
   https://huggingface.co/space-nomas/MobileSAM

2. Place the file in: assets/models/mobile_sam.tflite

3. Add this to pubspec.yaml:
   assets:
     - assets/models/mobile_sam.tflite

4. Run: flutter clean && flutter pub get

OPTION 2: Automatic Download (Future)
======================================
We are working on automatic model download on first app launch.
This feature will be available in the next update.

Current Status
==============
- AUTO MODE: ✅ Ready (Google ML Kit)
- PRO MODE:  ✅ Ready (Edge Detection)
- AI MODE:   ⏳ Awaiting model setup

Questions?
==========
See: docs/MOBILESAM_SETUP.md
""";

  /// Check if model file exists locally
  static Future<bool> isModelAvailable() async {
    try {
      final modelPath = await _getModelPath();
      final file = File(modelPath);
      return await file.exists();
    } catch (e) {
      print("Error checking model: $e");
      return false;
    }
  }

  /// Get the full path to model file
  static Future<String> getModelPath() async {
    return await _getModelPath();
  }

  /// Internal: Get model path from assets or app documents
  static Future<String> _getModelPath() async {
    // Check assets first (if bundled with app)
    final assetsPath = 'assets/models/$_modelFileName';
    
    // Try app documents directory
    try {
      final appDir = await getApplicationDocumentsDirectory();
      final docPath = '${appDir.path}/models/$_modelFileName';
      if (await File(docPath).exists()) {
        return docPath;
      }
    } catch (e) {
      print("Cannot access documents directory: $e");
    }
    
    // Return assets path (will be loaded by TFLite)
    return assetsPath;
  }

  /// Get setup status message
  static Future<String> getSetupStatus() async {
    final available = await isModelAvailable();
    
    if (available) {
      return "✅ MobileSAM model is ready";
    } else {
      return "⚠️  MobileSAM model not found - AI MODE will use fallback detection";
    }
  }

  /// Get detailed setup instructions
  static String getInstructions() {
    return SETUP_INSTRUCTIONS;
  }
}
