import 'package:shared_preferences/shared_preferences.dart';
import 'package:http/http.dart' as http;

class PreferencesService {
  static final PreferencesService _instance = PreferencesService._internal();

  factory PreferencesService() => _instance;

  PreferencesService._internal();

  // Scanner mode: 'auto' (ML Kit), 'pro' (Manual + Edge), 'ai' (MobileSAM)
  static const String keyScannerMode = "scanner_mode";
  static const String keyProCamera = "pro_camera_mode"; // Legacy, keep for compatibility

  /// Get scanner mode: 'auto', 'pro', or 'ai'
  Future<String> getScannerMode() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString(keyScannerMode) ?? 'auto'; // Default: AUTO (ML Kit)
  }

  /// Set scanner mode
  Future<void> setScannerMode(String mode) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(keyScannerMode, mode);
  }

  /// Legacy: Pro camera mode (for backward compatibility)
  Future<void> setProCameraMode(bool value) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(keyProCamera, value);
    // Also update new scanner mode
    await setScannerMode(value ? 'pro' : 'auto');
  }

  Future<bool> getProCameraMode() async {
    final mode = await getScannerMode();
    return mode == 'pro' || mode == 'ai';
  }

  Future<String> getServerUrl() async {
    final prefs = await SharedPreferences.getInstance();
    final saved = prefs.getString('server_url') ?? 'http://127.0.0.1:8000';
    return _normalizeUrl(saved);
  }

  Future<void> setServerUrl(String url) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('server_url', _normalizeUrl(url));
  }

  /// Normalizes URL: adds http:// if missing, strips trailing slash.
  String _normalizeUrl(String url) {
    String result = url.trim();
    if (result.isEmpty) return 'http://127.0.0.1:8000';
    if (!result.startsWith('http://') && !result.startsWith('https://')) {
      result = 'http://$result';
    }
    if (result.endsWith('/')) {
      result = result.substring(0, result.length - 1);
    }
    return result;
  }

  static const String keyDefaultFlash = "default_flash";

  /// Get default flash mode: true (ON/Torch) or false (OFF)
  Future<bool> getDefaultFlashMode() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getBool(keyDefaultFlash) ?? false; // Default: OFF
  }

  /// Set default flash mode
  Future<void> setDefaultFlashMode(bool enabled) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(keyDefaultFlash, enabled);
  }

  Future<bool> checkConnection() async {
    final url = await getServerUrl();
    try {
      final response = await http.get(Uri.parse('$url/health')).timeout(const Duration(seconds: 5));
      return response.statusCode == 200;
    } catch (e) {
      return false;
    }
  }

  // === SEARCH THRESHOLD SETTINGS ===
  static const String keyVisualThreshold = "visual_threshold";
  static const String keyTextThreshold = "text_threshold";
  static const String keyVisualOnlyThreshold = "visual_only_threshold";

  /// Visual similarity threshold — min weighted score to consider a candidate
  Future<double> getVisualThreshold() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getDouble(keyVisualThreshold) ?? 0.55;
  }

  Future<void> setVisualThreshold(double value) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setDouble(keyVisualThreshold, value);
  }

  /// Text verification threshold — min combined text ratio for hybrid match
  Future<double> getTextThreshold() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getDouble(keyTextThreshold) ?? 0.20;
  }

  Future<void> setTextThreshold(double value) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setDouble(keyTextThreshold, value);
  }

  /// Visual-only fallback threshold — when OCR is unavailable
  Future<double> getVisualOnlyThreshold() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getDouble(keyVisualOnlyThreshold) ?? 0.70;
  }

  Future<void> setVisualOnlyThreshold(double value) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setDouble(keyVisualOnlyThreshold, value);
  }

  /// OCR verification during search (FAST vs THOROUGH mode)
  static const String keyUseOcr = "use_ocr_verification";

  Future<bool> getUseOcrVerification() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getBool(keyUseOcr) ?? false; // Default: FAST mode (no OCR)
  }

  Future<void> setUseOcrVerification(bool value) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(keyUseOcr, value);
  }

  /// Region strategy for document fingerprinting
  static const String keyRegionStrategy = "region_strategy";

  /// Get region strategy: '4-strip', '9-grid', or '16-grid'
  Future<String> getRegionStrategy() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString(keyRegionStrategy) ?? '4-strip';
  }

  Future<void> setRegionStrategy(String strategy) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(keyRegionStrategy, strategy);
  }

  /// Reset all thresholds to default values
  Future<void> resetThresholds() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(keyVisualThreshold);
    await prefs.remove(keyTextThreshold);
    await prefs.remove(keyVisualOnlyThreshold);
    await prefs.remove(keyUseOcr);
    await prefs.remove(keyRegionStrategy);
  }
}
