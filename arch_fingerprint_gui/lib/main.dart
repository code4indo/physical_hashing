import 'dart:io';
import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart'; // For Clipboard
import 'package:camera/camera.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:http/http.dart' as http;
import 'package:path_provider/path_provider.dart';
import 'package:path/path.dart' show join;
import 'package:flutter_spinkit/flutter_spinkit.dart';
import 'package:google_nav_bar/google_nav_bar.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:google_mlkit_document_scanner/google_mlkit_document_scanner.dart';
import 'dart:convert';
import 'preferences_service.dart'; // Local service
import 'camera_screen.dart'; // Local screen
import 'document_cropper_screen.dart'; // Auto-crop screen (Edge Detection)
import 'mobilesam_cropper_screen.dart'; // AI crop screen (MobileSAM)

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final cameras = await availableCameras();
  runApp(ArchFingerprintApp(cameras: cameras));
}

class ArchFingerprintApp extends StatelessWidget {
  final List<CameraDescription> cameras;
  const ArchFingerprintApp({super.key, required this.cameras});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'ARCH-FINGERPRINT',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        brightness: Brightness.dark,
        scaffoldBackgroundColor: const Color(0xFF121212),
        primaryColor: const Color(0xFFD4AF37), // Metallic Gold
        colorScheme: const ColorScheme.dark(
          primary: Color(0xFFD4AF37),
          secondary: Color(0xFFC5A028),
          surface: Color(0xFF1E1E1E),
        ),
        textTheme: GoogleFonts.outfitTextTheme(ThemeData.dark().textTheme),
        inputDecorationTheme: InputDecorationTheme(
          filled: true,
          fillColor: const Color(0xFF2C2C2C),
          border: OutlineInputBorder(
            borderRadius: BorderRadius.circular(12),
            borderSide: BorderSide.none,
          ),
          focusedBorder: OutlineInputBorder(
            borderRadius: BorderRadius.circular(12),
            borderSide: const BorderSide(color: Color(0xFFD4AF37)),
          ),
          labelStyle: const TextStyle(color: Colors.grey),
        ),
      ),
      home: MainNavigation(cameras: cameras),
    );
  }
}

class MainNavigation extends StatefulWidget {
  final List<CameraDescription> cameras;
  const MainNavigation({super.key, required this.cameras});

  @override
  State<MainNavigation> createState() => _MainNavigationState();
}

class _MainNavigationState extends State<MainNavigation> {
  int _selectedIndex = 0;

  // We don't keep pages in a list state anymore to force rebuild (and re-init camera) 
  // when switching tabs. This avoids camera resource conflicts.

  @override
  Widget build(BuildContext context) {
    // Determine which page to show based on index
    Widget currentPage;
    switch (_selectedIndex) {
      case 0:
        currentPage = ScannerPage(cameras: widget.cameras);
        break;
      case 1:
        currentPage = RegisterPage(cameras: widget.cameras);
        break;
      case 2:
        currentPage = const HistoryPage();
        break;
      case 3:
        currentPage = const SettingsPage();
        break;
      default:
        currentPage = ScannerPage(cameras: widget.cameras);
    }

    return Scaffold(
      body: currentPage, // Direct child, not IndexedStack, to trigger dispose() on switch
      bottomNavigationBar: Container(
        color: const Color(0xFF1E1E1E),
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
        child: GNav(
          backgroundColor: const Color(0xFF1E1E1E),
          color: Colors.grey[600],
          activeColor: const Color(0xFFD4AF37),
          tabBackgroundColor: const Color(0xFFD4AF37).withOpacity(0.1),
          gap: 6,
          padding: const EdgeInsets.all(12),
          tabs: const [
            GButton(icon: Icons.qr_code_scanner_rounded, text: 'Identify'),
            GButton(icon: Icons.add_a_photo_rounded, text: 'Register'),
            GButton(icon: Icons.history_rounded, text: 'History'),
            GButton(icon: Icons.settings_rounded, text: 'Settings'),
          ],
          selectedIndex: _selectedIndex,
          onTabChange: (index) {
            setState(() {
              _selectedIndex = index;
            });
          },
        ),
      ),
    );
  }
}

// --- IDENTIFY PAGE (Updated with ML Kit Document Scanner) ---

class ScannerPage extends StatefulWidget {
  final List<CameraDescription> cameras;
  const ScannerPage({super.key, required this.cameras});

  @override
  State<ScannerPage> createState() => _ScannerPageState();
}

class _ScannerPageState extends State<ScannerPage> {
  bool _isScanning = false;
  String _serverUrl = "http://192.168.1.10:8000";

  @override
  void initState() {
    super.initState();
    _loadServerUrl();
  }

  Future<void> _loadServerUrl() async {
    final url = await PreferencesService().getServerUrl();
    if (url.isNotEmpty && mounted) {
      setState(() => _serverUrl = url);
    }
  }

  Future<void> _startIdentification() async {
    if (_isScanning) return;
    
    // Check Preference
    bool usePro = await PreferencesService().getProCameraMode();
    String? finalImagePath;

    if (usePro) {
       // PRO MODE: Manual Camera
       final result = await Navigator.push(context, MaterialPageRoute(builder: (_) => ProCameraScreen(cameras: widget.cameras)));
       if (result != null && result is XFile) {
          finalImagePath = result.path;
       } else {
          return; // Cancelled
       }
    } else {
      // AUTO MODE: ML Kit Scanner
      try {
        final options = DocumentScannerOptions(
          mode: ScannerMode.full,
          pageLimit: 1,
        );
        
        final scanner = DocumentScanner(options: options);
        final result = await scanner.scanDocument();

        if (result.images == null || result.images!.isEmpty) {
           return; // User cancelled
        }
        finalImagePath = result.images!.first;
      } catch(e) {
          print("Scanner error: $e");
          return;
      }
    }
    
    if (finalImagePath == null) return;
    
    try {
      // 2. Send to Search API
      setState(() => _isScanning = true);
      await _searchDocument(finalImagePath);

    } catch (e) {
      print("Error scanning document: $e");
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text("Scan cancelled or failed: $e"), backgroundColor: Colors.orange),
      );
    } finally {
        if (mounted) setState(() => _isScanning = false);
    }
  }

  Future<void> _searchDocument(String imagePath) async {
    try {
      // Load configurable thresholds from user settings
      final prefs = PreferencesService();
      final visualTh = await prefs.getVisualThreshold();
      final textTh = await prefs.getTextThreshold();
      final visualOnlyTh = await prefs.getVisualOnlyThreshold();
      final useOcr = await prefs.getUseOcrVerification();

      var request = http.MultipartRequest('POST', Uri.parse('$_serverUrl/api/v1/search'));
      request.files.add(await http.MultipartFile.fromPath('image', imagePath));
      request.fields['top_k'] = '5';
      request.fields['visual_threshold'] = visualTh.toStringAsFixed(2);
      request.fields['text_threshold'] = textTh.toStringAsFixed(2);
      request.fields['visual_only_threshold'] = visualOnlyTh.toStringAsFixed(2);
      request.fields['use_ocr'] = useOcr.toString();
      request.fields['region_strategy'] = await prefs.getRegionStrategy();

      // Increase timeout: server runs rembg + DINOv2 inference (heavy)
      var streamedResponse = await request.send().timeout(const Duration(seconds: 300));
      var response = await http.Response.fromStream(streamedResponse);
      
      if (response.statusCode != 200) {
        throw Exception("Server Error: ${response.statusCode}");
      }

      var data = json.decode(response.body);

      if (data['results'] != null && (data['results'] as List).isNotEmpty) {
        double score = data['results'][0]['similarity_score'];
        // Show result regardless of score, user can decide
        _showResult(data['results'][0]);
      } else {
        if (!mounted) return;
        _showNoMatchDialog();
      }
    } on TimeoutException catch (_) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text("Server timeout. AI processing took too long. Please try again."),
          backgroundColor: Colors.orange,
          duration: Duration(seconds: 5),
        ),
      );
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text("Identification Error: $e"), backgroundColor: Colors.red),
      );
    }
  }
  
  void _showNoMatchDialog() {
      showDialog(
        context: context,
        builder: (context) => AlertDialog(
            backgroundColor: const Color(0xFF1E1E1E),
            title: const Text("Not Found", style: TextStyle(color: Colors.white)),
            content: const Text("No matching document found in the archive.", style: TextStyle(color: Colors.white70)),
            actions: [
                TextButton(
                    onPressed: () => Navigator.pop(context), 
                    child: const Text("OK", style: TextStyle(color: Color(0xFFD4AF37)))
                )
            ],
        )
      );
  }

  void _showResult(dynamic result) {
    // Construct full image URL
    String? relativeUrl = result['image_url'];
    String fullImageUrl = "";
    if (relativeUrl != null && relativeUrl.isNotEmpty) {
       // Simple concatenation handling basic slash issues
       fullImageUrl = "$_serverUrl$relativeUrl";
       // If both have slash or neither, we might need cleaner logic, but standard usually works if serverUrl has no trailing slash and relativeUrl has leading slash
    }

    showModalBottomSheet(
      context: context,
      backgroundColor: Colors.transparent,
      isScrollControlled: true,
      builder: (context) => Container(
        height: MediaQuery.of(context).size.height * 0.85, // Increased height for image
        decoration: const BoxDecoration(
          color: Color(0xFF1E1E1E),
          borderRadius: BorderRadius.vertical(top: Radius.circular(30)),
          boxShadow: [
            BoxShadow(color: Colors.black54, blurRadius: 20, spreadRadius: 5),
          ],
        ),
        child: Column(
          children: [
            const SizedBox(height: 15),
            Container(
              width: 50,
              height: 5,
              decoration: BoxDecoration(
                color: Colors.grey[700],
                borderRadius: BorderRadius.circular(10),
              ),
            ),
            const SizedBox(height: 20),
            Text(
              "Identity Found!",
              style: GoogleFonts.outfit(
                fontSize: 24,
                fontWeight: FontWeight.bold,
                color: const Color(0xFFD4AF37),
              ),
            ),
            
            // === REGISTERED IMAGE PREVIEW ===
            if (fullImageUrl.isNotEmpty)
              Padding(
                padding: const EdgeInsets.fromLTRB(20, 20, 20, 10),
                child: GestureDetector(
                  onTap: () {
                     // Open full screen viewer
                     Navigator.push(context, MaterialPageRoute(builder: (_) => FullScreenImageViewer(imageUrl: fullImageUrl)));
                  },
                  child: Hero(
                    tag: fullImageUrl, // Unique tag for animation
                    child: Container(
                      height: 200,
                      width: double.infinity,
                      decoration: BoxDecoration(
                        borderRadius: BorderRadius.circular(15),
                        border: Border.all(color: Colors.white24),
                        color: Colors.black,
                      ),
                      child: ClipRRect(
                        borderRadius: BorderRadius.circular(15),
                        child: Image.network(
                          fullImageUrl,
                          fit: BoxFit.contain,
                          loadingBuilder: (c, child, p) => p == null ? child : const Center(child: CircularProgressIndicator(color: Color(0xFFD4AF37))),
                          errorBuilder: (_, __, ___) => const Center(child: Icon(Icons.broken_image, color: Colors.grey)),
                        ),
                      ),
                    ),
                  ),
                ),
              ),

            const SizedBox(height: 10),
            Container(
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                decoration: BoxDecoration(
                    color: const Color(0xFFD4AF37).withOpacity(0.1),
                    borderRadius: BorderRadius.circular(20),
                    border: Border.all(color: const Color(0xFFD4AF37).withOpacity(0.3))
                ),
                child: Text(
                "Match Confidence: ${(result['similarity_score'] * 100).toStringAsFixed(1)}%",
                style: const TextStyle(color: Color(0xFFD4AF37), fontWeight: FontWeight.bold),
                ),
            ),
            const SizedBox(height: 20),
            Expanded(
              child: ListView(
                padding: const EdgeInsets.symmetric(horizontal: 25),
                children: [
                  _infoTile("Khazanah / Collection", result['khazanah']),
                  const Divider(color: Colors.white10),
                  _infoTile("Page Number", result['page_number']?.toString() ?? "-"),
                  const Divider(color: Colors.white10),
                  const SizedBox(height: 10),
                  const Text("Description:", style: TextStyle(fontWeight: FontWeight.bold, color: Colors.grey)),
                  const SizedBox(height: 8),
                  Text(
                    result['description'] ?? "No description available.",
                    style: const TextStyle(color: Colors.white, fontSize: 16),
                  ),
                  const SizedBox(height: 30),
                  ElevatedButton(
                    onPressed: () => Navigator.pop(context),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: const Color(0xFFD4AF37),
                      foregroundColor: Colors.black,
                      minimumSize: const Size(double.infinity, 55),
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(15)),
                      elevation: 5,
                    ),
                    child: const Text("Close Result", style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
                  ),
                  const SizedBox(height: 30),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _infoTile(String label, String value) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 12.0),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(label, style: const TextStyle(color: Colors.grey, fontSize: 14)),
          Text(value, style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 18, color: Colors.white)),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
         body: Container(
            width: double.infinity,
            decoration: BoxDecoration(
                gradient: LinearGradient(
                    begin: Alignment.topCenter,
                    end: Alignment.bottomCenter,
                    colors: [Color(0xFF1E1E1E), Color(0xFF121212)]
                )
            ),
            child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                    Container(
                        padding: EdgeInsets.all(20),
                        decoration: BoxDecoration(
                            shape: BoxShape.circle,
                            color: Color(0xFFD4AF37).withOpacity(0.1),
                            border: Border.all(color: Color(0xFFD4AF37), width: 2)
                        ),
                        child: Icon(Icons.fingerprint_rounded, size: 80, color: Color(0xFFD4AF37)),
                    ),
                    SizedBox(height: 30),
                    Text(
                        "Identify Document",
                        style: GoogleFonts.outfit(fontSize: 28, fontWeight: FontWeight.bold, color: Colors.white)
                    ),
                    SizedBox(height: 10),
                    Padding(
                        padding: EdgeInsets.symmetric(horizontal: 40),
                        child: Text(
                            "Scan a historical document to identify its origin, page number, and metadata.",
                            textAlign: TextAlign.center,
                            style: TextStyle(color: Colors.white54)
                        ),
                    ),
                    SizedBox(height: 50),
                    
                    if (_isScanning)
                        Column(children: [
                            SpinKitRipple(color: Color(0xFFD4AF37), size: 60),
                            SizedBox(height: 20),
                            Text("Analyzing Structure & Reading Text...", style: TextStyle(color: Color(0xFFD4AF37), fontWeight: FontWeight.w600)),
                            SizedBox(height: 5),
                            Text("(Please wait up to 30s for verification)", style: TextStyle(color: Colors.white38, fontSize: 12))
                        ])
                    else
                        ElevatedButton.icon(
                            onPressed: _startIdentification,
                            icon: Icon(Icons.search_rounded),
                            label: Text("START IDENTIFICATION"),
                            style: ElevatedButton.styleFrom(
                                backgroundColor: Color(0xFFD4AF37),
                                foregroundColor: Colors.black,
                                padding: EdgeInsets.symmetric(horizontal: 30, vertical: 16),
                                textStyle: TextStyle(fontSize: 16, fontWeight: FontWeight.bold, letterSpacing: 1),
                                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(30))
                            ),
                        )
                ],
            ),
         ),
    );
  }
}

// --- REGISTER PAGE (Updated with ML Kit Document Scanner) ---

class RegisterPage extends StatefulWidget {
  final List<CameraDescription> cameras;
  const RegisterPage({super.key, required this.cameras});

  @override
  State<RegisterPage> createState() => _RegisterPageState();
}

class _RegisterPageState extends State<RegisterPage> {
  List<XFile> _capturedImages = []; // Stores batch images
  
  bool _isBatchMode = true; // Default to Batch Mode for mass scanning
  bool _isSubmitting = false;
  int _uploadProgress = 0;
  int _totalUploads = 0;

  String _scanMode = "book"; // Default 'book' for mass scanning
  String _writingMode = "print"; // Default 'print'
  final _formKey = GlobalKey<FormState>();
  
  final _khazanahController = TextEditingController();
  final _pageController = TextEditingController();
  final _descController = TextEditingController();

  String _serverUrl = "http://192.168.1.10:8000";

  @override
  void initState() {
    super.initState();
    _loadServerUrl();
  }

  Future<void> _loadServerUrl() async {
    final url = await PreferencesService().getServerUrl();
    if (url.isNotEmpty && mounted) {
      setState(() => _serverUrl = url);
    }
  }

  @override
  void dispose() {
    _khazanahController.dispose();
    _pageController.dispose();
    _descController.dispose();
    super.dispose();
  }

  Future<void> _startScan() async {
    String scannerMode = await PreferencesService().getScannerMode();

    if (scannerMode == 'auto') {
        // === AUTO MODE: ML Kit Document Scanner ===
        try {
          final options = DocumentScannerOptions(
            mode: ScannerMode.base, // Changed to base to avoid default auto-enhance
            pageLimit: _isBatchMode ? 100 : 1, // Set to 100 for Batch (0 throws error)
            isGalleryImport: false,
          );

          final scanner = DocumentScanner(options: options);
          final result = await scanner.scanDocument();

          if (result.images != null && result.images!.isNotEmpty) {
            setState(() {
              // In batch mode, we REPLACE the current list with the new session
              // Assuming user scans a full batch at once. 
              _capturedImages = result.images!.map((path) => XFile(path)).toList();
            });
          }
        } catch (e) {
          print("ML Kit error: $e");
          if (!mounted) return;
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text("Scan failed: $e"), backgroundColor: Colors.orange),
          );
        }
    } else {
        // === PRO / AI Mode ===
        // Currently supports single capture. 
        // TODO: Update loop for Pro Mode if needed.
        final capturedImage = await Navigator.push(
          context, 
          MaterialPageRoute(builder: (_) => ProCameraScreen(cameras: widget.cameras))
        );
        
        if (capturedImage != null && capturedImage is XFile) {
            XFile? finalImage = capturedImage;
            
            // Auto-Crop Logic for Manual Modes
            if (scannerMode == 'pro') {
                final cropped = await Navigator.push(
                   context, MaterialPageRoute(builder: (_) => DocumentCropperScreen(imagePath: finalImage!.path))
                );
                if (cropped != null) finalImage = XFile(cropped);
            } else if (scannerMode == 'ai') {
                final cropped = await Navigator.push(
                   context, MaterialPageRoute(builder: (_) => MobileSAMCropperScreen(imagePath: finalImage!.path))
                );
                if (cropped != null) finalImage = XFile(cropped);
            }

            setState(() {
               _capturedImages = [finalImage!]; // Single item list
            });
        }
    }
  }

  void _retake() {
    setState(() {
      _capturedImages.clear();
    });
  }

  // Helper to upload a single file
  Future<bool> _uploadSingleImage(XFile image, int? pageNumber) async {
    try {
      var uri = Uri.parse('$_serverUrl/api/v1/register');
      var request = http.MultipartRequest('POST', uri);

      var file = await http.MultipartFile.fromPath('image', image.path);
      request.files.add(file);

      request.fields['khazanah'] = _khazanahController.text;
      
      if (pageNumber != null) {
          request.fields['page_number'] = pageNumber.toString();
      } else if (_pageController.text.isNotEmpty) {
          request.fields['page_number'] = _pageController.text;
      }
      
      if (_descController.text.isNotEmpty) {
        request.fields['description'] = _descController.text;
      }
      
      request.fields['scan_mode'] = _scanMode;
      request.fields['writing_mode'] = _writingMode;

      // Send
      var streamedResponse = await request.send().timeout(const Duration(seconds: 45));
      var response = await http.Response.fromStream(streamedResponse);

      return (response.statusCode == 201 || response.statusCode == 202);
    } catch (e) {
      print("Upload Error: $e");
      return false;
    }
  }

  Future<void> _submitRegistration() async {
    if (!_formKey.currentState!.validate()) return;
    if (_capturedImages.isEmpty) return;

    setState(() {
      _isSubmitting = true;
      _uploadProgress = 0;
      _totalUploads = _capturedImages.length;
    });

    // Parse Start Page
    int startPage = 1;
    if (_pageController.text.isNotEmpty) {
        startPage = int.tryParse(_pageController.text) ?? 1;
    }

    List<XFile> failedImages = [];
    int successCount = 0;

    // Loop through batch
    // Using simple loop to allow sequential start page increment
    for (int i = 0; i < _capturedImages.length; i++) {
        int currentPage = startPage + i;
        bool result = await _uploadSingleImage(_capturedImages[i], currentPage);
        
        if (result) {
            successCount++;
            setState(() => _uploadProgress = successCount);
        } else {
            failedImages.add(_capturedImages[i]);
            print("Failed to upload page $currentPage");
        }
    }

    if (mounted) {
        if (failedImages.isEmpty) {
            // ALL SUCCESS
            ScaffoldMessenger.of(context).showSnackBar(
               const SnackBar(content: Text("✅ Batch Upload Complete!"), backgroundColor: Colors.green)
            );
            
            setState(() {
              _capturedImages.clear();
              _isSubmitting = false;
              // AUTO INCREMENT: Prepare start page for NEXT batch
              _pageController.text = (startPage + successCount).toString();
              // Keep Khazanah logic intact - user unlikely to change khazanah mid-box
            });
            
        } else {
            // PARTIAL SUCCESS
            ScaffoldMessenger.of(context).showSnackBar(
               SnackBar(
                 content: Text("⚠️ Uploaded $successCount. Failed ${failedImages.length}. Retrying failed ones..."), 
                 backgroundColor: Colors.orange,
                 duration: const Duration(seconds: 4),
               )
            );
            setState(() {
              _capturedImages = failedImages; // Keep only failed
              _isSubmitting = false;
              // Update page number to continue from where we left off (roughly)
              // This is tricky. Ideally user should check what failed.
              // For now, we don't auto-update page if failure occurred to avoid skip.
            });
        }
    }
  }

  Widget _buildModeButton(String label, String value, IconData icon) {
    bool isSelected = _scanMode == value;
    return GestureDetector(
      onTap: () {
         setState(() => _scanMode = value);
      },
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
        decoration: BoxDecoration(
          color: isSelected ? const Color(0xFFD4AF37) : Colors.transparent,
          borderRadius: BorderRadius.circular(20),
        ),
        child: Row(
          children: [
            Icon(icon, size: 16, color: isSelected ? Colors.black : Colors.white54),
            const SizedBox(width: 8),
            Text(label, style: TextStyle(color: isSelected ? Colors.black : Colors.white54, fontWeight: FontWeight.bold)),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    // === VIEW 1: LANDING (START SCAN) ===
    if (_capturedImages.isEmpty) {
      return Scaffold(
         body: Container(
            width: double.infinity,
            decoration: const BoxDecoration(
                gradient: LinearGradient(
                    begin: Alignment.topCenter,
                    end: Alignment.bottomCenter,
                    colors: [Color(0xFF1E1E1E), Color(0xFF121212)]
                )
            ),
            child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                    const Icon(Icons.document_scanner_rounded, size: 80, color: Color(0xFFD4AF37)),
                    const SizedBox(height: 20),
                    Text(
                        "Mass Scanner",
                        style: GoogleFonts.outfit(fontSize: 28, fontWeight: FontWeight.bold, color: Colors.white)
                    ),
                    const SizedBox(height: 10),
                    const Padding(
                        padding: EdgeInsets.symmetric(horizontal: 40),
                        child: Text(
                            "Optimize for speed using 'Batch Mode'. Scan multiple pages, then upload in bulk.",
                            textAlign: TextAlign.center,
                            style: TextStyle(color: Colors.white54)
                        ),
                    ),
                    const SizedBox(height: 30),

                    // Batch Mode Toggle
                    Container(
                        width: 280,
                        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                        decoration: BoxDecoration(
                            color: Colors.white10,
                            borderRadius: BorderRadius.circular(15),
                            border: Border.all(color: _isBatchMode ? const Color(0xFFD4AF37) : Colors.transparent)
                        ),
                        child: Row(
                            mainAxisAlignment: MainAxisAlignment.spaceBetween,
                            children: [
                                const Text("Batch Mode (Multi-Page)", style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold)),
                                Switch(
                                    value: _isBatchMode,
                                    activeColor: const Color(0xFFD4AF37),
                                    onChanged: (val) => setState(() => _isBatchMode = val),
                                )
                            ]
                        ),
                    ),
                    
                    const SizedBox(height: 40),
                    ElevatedButton.icon(
                        onPressed: _startScan,
                        icon: const Icon(Icons.camera_alt),
                        label: Text(_isBatchMode ? "START BATCH SCAN" : "SCAN SINGLE PAGE"),
                        style: ElevatedButton.styleFrom(
                            backgroundColor: const Color(0xFFD4AF37),
                            foregroundColor: Colors.black,
                            padding: const EdgeInsets.symmetric(horizontal: 30, vertical: 15),
                            textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold)
                        ),
                    )
                ],
            ),
         ),
      );
    }

    // === VIEW 2: BATCH REVIEW & UPLOAD ===
    return Scaffold(
      appBar: AppBar(
        title: Text("Batch Review (${_capturedImages.length} Pages)"),
        backgroundColor: Colors.transparent,
        elevation: 0,
        leading: IconButton(onPressed: _retake, icon: const Icon(Icons.close)), // Clear/Cancel
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(20),
        child: Form(
          key: _formKey,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              // Batch Preview Horizontal List
              SizedBox(
                height: 150,
                child: ListView.separated(
                    scrollDirection: Axis.horizontal,
                    itemCount: _capturedImages.length,
                    separatorBuilder: (_, __) => const SizedBox(width: 10),
                    itemBuilder: (ctx, i) {
                        return Stack(
                            children: [
                                ClipRRect(
                                    borderRadius: BorderRadius.circular(10),
                                    child: Image.file(File(_capturedImages[i].path), width: 100, height: 150, fit: BoxFit.cover),
                                ),
                                Positioned(
                                    right: 5, top: 5,
                                    child: CircleAvatar(
                                        radius: 10,
                                        backgroundColor: Colors.black54,
                                        child: Text("${i+1}", style: const TextStyle(fontSize: 10, color: Colors.white)),
                                    ),
                                )
                            ]
                        );
                    },
                ),
              ),
              const SizedBox(height: 20),
              
              TextFormField(
                controller: _khazanahController,
                style: const TextStyle(color: Colors.white),
                decoration: const InputDecoration(
                  labelText: "Khazanah / Box Name *",
                  hintText: "e.g., BOX_001",
                  prefixIcon: Icon(Icons.folder_shared, color: Color(0xFFD4AF37)),
                  helperText: "Applies to all pages in this batch",
                  helperStyle: TextStyle(color: Colors.white30)
                ),
                validator: (v) => v!.isEmpty ? "Required" : null,
              ),
              const SizedBox(height: 15),

              TextFormField(
                controller: _pageController,
                keyboardType: TextInputType.number,
                style: const TextStyle(color: Colors.white),
                decoration: const InputDecoration(
                  labelText: "Start Page Number",
                  hintText: "Auto-increments (e.g. 1)",
                  prefixIcon: Icon(Icons.pages, color: Color(0xFFD4AF37)),
                  helperText: "First page index. Subsequent pages will be +1, +2...",
                  helperStyle: TextStyle(color: Colors.white30)
                ),
              ),
              const SizedBox(height: 15),
              
              const SizedBox(height: 15),

              DropdownButtonFormField<String>(
                value: _writingMode,
                dropdownColor: const Color(0xFF1E1E1E),
                style: const TextStyle(color: Colors.white),
                decoration: const InputDecoration(
                  labelText: "Writing Mode",
                  prefixIcon: Icon(Icons.edit_note, color: Color(0xFFD4AF37)),
                  helperText: "Handwriting skips OCR to avoid errors",
                  helperStyle: TextStyle(color: Colors.white30),
                  enabledBorder: OutlineInputBorder(borderSide: BorderSide(color: Colors.white24)),
                  focusedBorder: OutlineInputBorder(borderSide: BorderSide(color: Color(0xFFD4AF37))),
                ),
                items: const [
                  DropdownMenuItem(value: "print", child: Text("Printed / Typed")),
                  DropdownMenuItem(value: "handwriting", child: Text("Handwriting (Paleography)")),
                ],
                onChanged: (val) => setState(() => _writingMode = val!),
              ),
              
              const SizedBox(height: 30),

              SizedBox(
                height: 55,
                child: ElevatedButton(
                  onPressed: _isSubmitting ? null : _submitRegistration,
                  style: ElevatedButton.styleFrom(
                    backgroundColor: const Color(0xFFD4AF37),
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                  ),
                  child: _isSubmitting 
                    ? Row(mainAxisAlignment: MainAxisAlignment.center, children: [
                        const CircularProgressIndicator(color: Colors.black, strokeWidth: 2),
                        const SizedBox(width: 15),
                        Text("UPLOADING $_uploadProgress / $_totalUploads", style: const TextStyle(color: Colors.black, fontWeight: FontWeight.bold))
                      ])
                    : Text("UPLOAD BATCH (${_capturedImages.length} FILES)", 
                        style: const TextStyle(color: Colors.black, fontWeight: FontWeight.bold, fontSize: 16)),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

// --- HISTORY & SETTINGS ---

class HistoryPage extends StatefulWidget {
  const HistoryPage({super.key});

  @override
  State<HistoryPage> createState() => _HistoryPageState();
}

class _HistoryPageState extends State<HistoryPage> {
  List<dynamic> _documents = [];
  bool _isLoading = true;
  bool _isViewModeGrid = true; // Toggle between grid and list view
  // Use the same server URL (ideally move to a config/service)
  String _serverUrl = "http://192.168.1.10:8000"; 

  // Multi-select delete
  bool _isSelectionMode = false;
  final Set<int> _selectedDocIds = {};

  // Add OCR status to document metadata
  String? _ocrStatus;
  String? _ocrContent;

  @override
  void initState() {
    super.initState();
    _loadUrlAndFetch();
  }

  Future<void> _loadUrlAndFetch() async {
    final url = await PreferencesService().getServerUrl();
    if (mounted) {
      setState(() => _serverUrl = url);
      _fetchDocuments();
    }
  }

  Future<void> _fetchDocuments() async {
    try {
      final uri = Uri.parse('$_serverUrl/api/v1/documents?per_page=10');
      final response = await http.get(uri);

      if (response.statusCode == 200) {
        final data = json.decode(response.body);
        if (mounted) {
          setState(() {
            _documents = data['documents'];
            _isLoading = false;
          });
        }
      } else {
        throw Exception("Server error: ${response.statusCode}");
      }
    } catch (e) {
      if (mounted) {
        setState(() => _isLoading = false);
        // Silent error or snackbar
      }
    }
  }
  
  Future<void> _checkOCRStatus(String docId) async {
    try {
      final uri = Uri.parse('$_serverUrl/api/v1/documents/$docId/ocr');
      final response = await http.get(uri);
      
      if (response.statusCode == 200) {
        final data = json.decode(response.body);
        if (mounted) {
          setState(() {
            _ocrStatus = data['status'];
            _ocrContent = data['content'];
          });
        }
      } else {
        throw Exception("Failed to get OCR status");
      }
    } catch (e) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text("Error checking OCR status: $e"), backgroundColor: Colors.red)
      );
    }
  }
  
  Future<void> _viewOCRContent(String docId) async {
    try {
      final uri = Uri.parse('$_serverUrl/api/v1/documents/$docId/ocr');
      final response = await http.get(uri);
      
      if (response.statusCode == 200) {
        final data = json.decode(response.body);
        final content = data['content'] ?? "No OCR content available";
        
        await showDialog<void>(
          context: context,
          builder: (BuildContext context) {
            return AlertDialog(
              backgroundColor: Colors.grey[900],
              title: const Text("OCR Content", style: TextStyle(color: Colors.white)),
              content: SingleChildScrollView(
                child: Text(
                  content,
                  style: const TextStyle(color: Colors.white70),
                  textAlign: TextAlign.left,
                ),
              ),
              actions: [
                TextButton(
                  onPressed: () => Navigator.pop(context),
                  child: const Text("Close", style: TextStyle(color: Colors.white)),
                ),
              ],
            );
          },
        );
      } else {
        throw Exception("Failed to get OCR content");
      }
    } catch (e) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text("Error viewing OCR content: $e"), backgroundColor: Colors.red)
      );
    }
  }

  void _toggleSelectionMode() {
    setState(() {
      _isSelectionMode = !_isSelectionMode;
      if (!_isSelectionMode) _selectedDocIds.clear();
    });
  }

  void _toggleDocSelection(int docId) {
    setState(() {
      if (_selectedDocIds.contains(docId)) {
        _selectedDocIds.remove(docId);
        if (_selectedDocIds.isEmpty) _isSelectionMode = false;
      } else {
        _selectedDocIds.add(docId);
      }
    });
  }

  void _selectAllDocs() {
    setState(() {
      if (_selectedDocIds.length == _documents.length) {
        _selectedDocIds.clear();
      } else {
        _selectedDocIds.clear();
        for (final doc in _documents) {
          _selectedDocIds.add(doc['id'] as int);
        }
      }
    });
  }

  Future<void> _deleteSelectedDocuments() async {
    if (_selectedDocIds.isEmpty) return;

    final count = _selectedDocIds.length;
    final confirm = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: Colors.grey[900],
        title: const Text("Delete Selected", style: TextStyle(color: Colors.white)),
        content: Text(
          "Are you sure you want to delete $count selected document${count > 1 ? 's' : ''}? This action cannot be undone.",
          style: const TextStyle(color: Colors.white70),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text("Cancel"),
          ),
          TextButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text("Delete", style: TextStyle(color: Colors.red)),
          ),
        ],
      ),
    );

    if (confirm != true) return;

    setState(() => _isLoading = true);

    try {
      int successCount = 0;
      int failCount = 0;
      final idsToDelete = List<int>.from(_selectedDocIds);

      for (final docId in idsToDelete) {
        try {
          final uri = Uri.parse('$_serverUrl/api/v1/documents/$docId');
          final response = await http.delete(uri);
          if (response.statusCode == 200) {
            successCount++;
          } else {
            failCount++;
          }
        } catch (e) {
          failCount++;
        }
      }

      if (mounted) {
        String message;
        if (failCount == 0) {
          message = "✅ $successCount document${successCount > 1 ? 's' : ''} deleted";
        } else {
          message = "⚠️ Deleted $successCount, $failCount failed";
        }

        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(message),
            backgroundColor: failCount == 0 ? Colors.green : Colors.orange,
            duration: const Duration(seconds: 3),
          ),
        );

        _selectedDocIds.clear();
        _isSelectionMode = false;
        await _fetchDocuments();
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text("Error: $e"), backgroundColor: Colors.red),
        );
        setState(() => _isLoading = false);
      }
    }
  }

  Future<void> _deleteAllDocuments() async {
    if (_documents.isEmpty) return;

    final confirm = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: Colors.grey[900],
        title: const Text("Delete All Documents", style: TextStyle(color: Colors.white)),
        content: Text(
          "Are you sure you want to delete all ${_documents.length} documents? This action cannot be undone.",
          style: const TextStyle(color: Colors.white70),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text("Cancel"),
          ),
          TextButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text("Delete All", style: TextStyle(color: Colors.red)),
          ),
        ],
      ),
    );

    if (confirm != true) return;

    setState(() => _isLoading = true);

    try {
      int successCount = 0;
      int failCount = 0;

      for (final doc in _documents) {
        try {
          final uri = Uri.parse('$_serverUrl/api/v1/documents/${doc['id']}');
          final response = await http.delete(uri);
          if (response.statusCode == 200) {
            successCount++;
          } else {
            failCount++;
          }
        } catch (e) {
          failCount++;
          print("Failed to delete doc ${doc['id']}: $e");
        }
      }

      if (mounted) {
        String message;
        if (failCount == 0) {
          message = "✅ All $successCount documents deleted successfully";
        } else {
          message = "⚠️ Deleted $successCount documents, $failCount failed";
        }

        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(message),
            backgroundColor: failCount == 0 ? Colors.green : Colors.orange,
            duration: const Duration(seconds: 3),
          ),
        );

        await _fetchDocuments();
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text("Error deleting documents: $e"), backgroundColor: Colors.red),
        );
        setState(() => _isLoading = false);
      }
    }
  }

  Future<void> _deleteSingleDocument(String docId) async {
    final confirm = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: Colors.grey[900],
        title: const Text("Delete Document", style: TextStyle(color: Colors.white)),
        content: const Text("Are you sure? This action cannot be undone.", style: TextStyle(color: Colors.white70)),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text("Cancel")),
          TextButton(onPressed: () => Navigator.pop(ctx, true), child: const Text("Delete", style: TextStyle(color: Colors.red))),
        ],
      ),
    );

    if (confirm != true) return;

    try {
      final uri = Uri.parse('$_serverUrl/api/v1/documents/$docId');
      final response = await http.delete(uri);
      
      if (response.statusCode == 200) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text("Document deleted successfully")));
        await _fetchDocuments(); // Refresh the list
      } else {
        throw Exception("Failed to delete");
      }
    } catch (e) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text("Error: $e"), backgroundColor: Colors.red));
    }
  }

  Future<void> _deleteDocument(BuildContext context, String docId) async {
    final serverUrl = await PreferencesService().getServerUrl();
    if (serverUrl.isEmpty) return;

    final confirm = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: Colors.grey[900],
        title: const Text("Delete Document", style: TextStyle(color: Colors.white)),
        content: const Text("Are you sure? This action cannot be undone.", style: TextStyle(color: Colors.white70)),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text("Cancel"),
          ),
          TextButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text("Delete", style: TextStyle(color: Colors.red)),
          ),
        ],
      ),
    );

    if (confirm == true) {
      try {
        final uri = Uri.parse('$serverUrl/api/v1/documents/$docId');
        final response = await http.delete(uri);
        
        if (response.statusCode == 200) {
          Navigator.pop(context, true); // Return true to indicate deletion
          ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text("Document deleted successfully")));
        } else {
           throw Exception("Failed to delete");
        }
      } catch (e) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text("Error: $e"), backgroundColor: Colors.red));
      }
    }
  }
  
  Future<void> _deleteDocumentWithOCRCheck(BuildContext context, String docId) async {
    final serverUrl = await PreferencesService().getServerUrl();
    if (serverUrl.isEmpty) return;

    final confirm = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: Colors.grey[900],
        title: const Text("Delete Document", style: TextStyle(color: Colors.white)),
        content: const Text("Are you sure? This action cannot be undone.", style: TextStyle(color: Colors.white70)),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text("Cancel"),
          ),
          TextButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text("Delete", style: TextStyle(color: Colors.red)),
          ),
        ],
      ),
    );

    if (confirm == true) {
      try {
        final uri = Uri.parse('$serverUrl/api/v1/documents/$docId');
        final response = await http.delete(uri);
        
        if (response.statusCode == 200) {
          Navigator.pop(context, true); // Return true to indicate deletion
          ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text("Document deleted successfully")));
        } else {
           throw Exception("Failed to delete");
        }
      } catch (e) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text("Error: $e"), backgroundColor: Colors.red));
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    Widget content;
    if (_documents.isEmpty) {
      content = LayoutBuilder(
        builder: (context, constraints) => SingleChildScrollView(
          physics: const AlwaysScrollableScrollPhysics(),
          child: ConstrainedBox(
            constraints: BoxConstraints(minHeight: constraints.maxHeight),
            child: Center(
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Icon(Icons.history_rounded, size: 80, color: Colors.grey[800]),
                  const SizedBox(height: 15),
                  const Text("No documents found.", style: TextStyle(color: Colors.grey)),
                  const SizedBox(height: 10),
                  const Text("Pull down to refresh", style: TextStyle(color: Colors.grey, fontSize: 12)),
                ],
              ),
            ),
          ),
        ),
      );
    } else if (_isViewModeGrid) {
      content = GridView.builder(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.all(16),
        gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
          crossAxisCount: 2,
          crossAxisSpacing: 16,
          mainAxisSpacing: 16,
          childAspectRatio: 0.75,
        ),
        itemCount: _documents.length,
        itemBuilder: (ctx, index) {
          final doc = _documents[index];
          final docId = doc['id'] as int;
          final imageUrl = "$_serverUrl${doc['image_url']}?v=${DateTime.now().millisecondsSinceEpoch}";
          final isSelected = _selectedDocIds.contains(docId);
          
          return GestureDetector(
            onTap: () {
              if (_isSelectionMode) {
                _toggleDocSelection(docId);
              } else {
                Navigator.push(context, MaterialPageRoute(builder: (_) => DocumentDetailPage(doc: doc, serverUrl: _serverUrl)))
                  .then((val) {
                     if (val == true) {
                        _fetchDocuments();
                     }
                  });
              }
            },
            onLongPress: () {
              if (!_isSelectionMode) {
                setState(() => _isSelectionMode = true);
              }
              _toggleDocSelection(docId);
            },
            child: AnimatedContainer(
              duration: const Duration(milliseconds: 200),
              decoration: BoxDecoration(
                color: const Color(0xFF1E1E1E),
                borderRadius: BorderRadius.circular(15),
                border: Border.all(
                  color: isSelected ? const Color(0xFFD4AF37) : Colors.white10,
                  width: isSelected ? 2.5 : 1,
                ),
              ),
              child: Stack(
                children: [
                  Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      // Image Preview
                      Expanded(
                        child: ClipRRect(
                          borderRadius: const BorderRadius.vertical(top: Radius.circular(15)),
                          child: Container(
                              color: Colors.black, 
                              child: Image.network(
                                  imageUrl,
                                  fit: BoxFit.cover,
                                  loadingBuilder: (c, child, p) => p == null ? child : const Center(child: CircularProgressIndicator(strokeWidth: 2)),
                                  errorBuilder: (_, __, ___) => const Center(child: Icon(Icons.broken_image, color: Colors.grey)),
                              ),
                          )
                        ),
                      ),
                      Padding(
                        padding: const EdgeInsets.all(8),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              doc['khazanah'] ?? "Unknown Collection",
                              style: const TextStyle(
                                fontWeight: FontWeight.bold,
                                fontSize: 12,
                                color: Color(0xFFD4AF37),
                              ),
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                            ),
                            const SizedBox(height: 2),
                            Text("Page: ${doc['page_number'] ?? '-'}", style: const TextStyle(color: Colors.white70, fontSize: 10)),
                            const SizedBox(height: 4),
                            Row(
                              mainAxisAlignment: MainAxisAlignment.spaceBetween,
                              children: [
                                Expanded(
                                  child: Text(
                                    doc['fingerprint'] != null ? "ID: ${doc['fingerprint'].toString().substring(0, 6)}..." : "No ID",
                                    style: const TextStyle(color: Colors.grey, fontSize: 9, fontFamily: 'monospace'),
                                    maxLines: 1,
                                    overflow: TextOverflow.ellipsis,
                                  ),
                                ),
                                _buildStatusBadge(doc['status'] ?? 'pending'),
                              ],
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                  // Selection checkbox overlay
                  if (_isSelectionMode)
                    Positioned(
                      top: 8,
                      left: 8,
                      child: AnimatedContainer(
                        duration: const Duration(milliseconds: 150),
                        width: 28,
                        height: 28,
                        decoration: BoxDecoration(
                          color: isSelected ? const Color(0xFFD4AF37) : Colors.black54,
                          shape: BoxShape.circle,
                          border: Border.all(color: isSelected ? const Color(0xFFD4AF37) : Colors.white54, width: 2),
                        ),
                        child: isSelected
                          ? const Icon(Icons.check, color: Colors.black, size: 18)
                          : const SizedBox.shrink(),
                      ),
                    ),
                ],
              ),
            ),
          );
        },
      );
    } else {
      content = ListView.separated(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.all(16),
        itemCount: _documents.length,
        separatorBuilder: (_, __) => const SizedBox(height: 12),
        itemBuilder: (ctx, index) {
          final doc = _documents[index];
          final docId = doc['id'] as int;
          final isSelected = _selectedDocIds.contains(docId);
          
          return GestureDetector(
            onTap: () {
              if (_isSelectionMode) {
                _toggleDocSelection(docId);
              } else {
                Navigator.push(context, MaterialPageRoute(builder: (_) => DocumentDetailPage(doc: doc, serverUrl: _serverUrl)))
                  .then((val) {
                     if (val == true) {
                        _fetchDocuments();
                     }
                  });
              }
            },
            onLongPress: () {
              if (!_isSelectionMode) {
                setState(() => _isSelectionMode = true);
              }
              _toggleDocSelection(docId);
            },
            child: AnimatedContainer(
              duration: const Duration(milliseconds: 200),
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                color: isSelected ? const Color(0xFFD4AF37).withOpacity(0.08) : const Color(0xFF1E1E1E),
                borderRadius: BorderRadius.circular(12),
                border: Border.all(
                  color: isSelected ? const Color(0xFFD4AF37) : Colors.white10,
                  width: isSelected ? 2 : 1,
                ),
              ),
              child: Row(
                children: [
                  // Checkbox (shown in selection mode)
                  if (_isSelectionMode) ...[
                    AnimatedContainer(
                      duration: const Duration(milliseconds: 150),
                      width: 28,
                      height: 28,
                      decoration: BoxDecoration(
                        color: isSelected ? const Color(0xFFD4AF37) : Colors.transparent,
                        shape: BoxShape.circle,
                        border: Border.all(color: isSelected ? const Color(0xFFD4AF37) : Colors.white54, width: 2),
                      ),
                      child: isSelected
                        ? const Icon(Icons.check, color: Colors.black, size: 18)
                        : const SizedBox.shrink(),
                    ),
                    const SizedBox(width: 12),
                  ],
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            Expanded(
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(
                                    doc['khazanah'] ?? "Unknown Collection",
                                    style: const TextStyle(
                                      fontWeight: FontWeight.bold,
                                      fontSize: 16,
                                      color: Color(0xFFD4AF37),
                                    ),
                                  ),
                                  const SizedBox(height: 4),
                                  Text(
                                    "Page ${doc['page_number'] ?? '-'} • ${doc['created_at'] ?? 'Unknown date'}",
                                    style: const TextStyle(color: Colors.white70, fontSize: 12),
                                  ),
                                ],
                              ),
                            ),
                            _buildStatusBadge(doc['status'] ?? 'pending'),
                          ],
                        ),
                        const SizedBox(height: 12),
                        if (doc['description'] != null && doc['description'].toString().isNotEmpty)
                          Text(
                            doc['description'],
                            style: const TextStyle(color: Colors.white, fontSize: 14),
                            maxLines: 2,
                            overflow: TextOverflow.ellipsis,
                          ),
                        const SizedBox(height: 8),
                        Row(
                          children: [
                            Text(
                              "ID: ${doc['id']} • Vector: ${doc['vector_id'] == -1 ? 'Pending' : doc['vector_id']}",
                              style: const TextStyle(color: Colors.grey, fontSize: 10),
                            ),
                            const Spacer(),
                            if (!_isSelectionMode)
                              IconButton(
                                icon: const Icon(Icons.delete, size: 20, color: Colors.red),
                                onPressed: () => _deleteSingleDocument(doc['id'].toString()),
                                tooltip: "Delete this document",
                              ),
                          ],
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          );
        },
      );
    }

    return Scaffold(
      appBar: AppBar(
        leading: _isSelectionMode
          ? IconButton(
              onPressed: () => setState(() {
                _isSelectionMode = false;
                _selectedDocIds.clear();
              }),
              icon: const Icon(Icons.close),
              tooltip: "Cancel Selection",
            )
          : null,
        title: _isSelectionMode
          ? Text("${_selectedDocIds.length} selected")
          : Text("Recent Scans${_documents.isNotEmpty ? ' (${_documents.length})' : ''}"),
         actions: [
           if (_isSelectionMode) ...[
             // Select All button
             IconButton(
               onPressed: _selectAllDocs,
               icon: Icon(
                 _selectedDocIds.length == _documents.length
                   ? Icons.deselect
                   : Icons.select_all,
               ),
               tooltip: _selectedDocIds.length == _documents.length ? "Deselect All" : "Select All",
             ),
             // Delete selected button
             IconButton(
               onPressed: _selectedDocIds.isNotEmpty ? _deleteSelectedDocuments : null,
               icon: Icon(Icons.delete, color: _selectedDocIds.isNotEmpty ? Colors.red : Colors.grey),
               tooltip: "Delete Selected",
             ),
           ] else ...[
             // View toggle button
             IconButton(
               onPressed: () => setState(() => _isViewModeGrid = !_isViewModeGrid),
               icon: Icon(_isViewModeGrid ? Icons.list : Icons.grid_view),
               tooltip: _isViewModeGrid ? "Switch to List View" : "Switch to Grid View",
             ),
             // Selection mode toggle
             if (_documents.isNotEmpty)
               IconButton(
                 onPressed: _toggleSelectionMode,
                 icon: const Icon(Icons.checklist_rounded),
                 tooltip: "Select Documents",
               ),
             // Delete all button
             if (_documents.isNotEmpty)
               IconButton(
                 onPressed: _deleteAllDocuments,
                 icon: const Icon(Icons.delete_sweep, color: Colors.red),
                 tooltip: "Delete All Documents",
               ),
             // Refresh button
             IconButton(onPressed: _fetchDocuments, icon: const Icon(Icons.refresh))
           ],
         ]
      ),
      body: _isLoading
          ? const Center(child: CircularProgressIndicator(color: Color(0xFFD4AF37)))
          : RefreshIndicator(
              onRefresh: _fetchDocuments,
              color: const Color(0xFFD4AF37),
              backgroundColor: Colors.grey[900],
              child: content,
            ),
    );
  }
  
  Widget _buildStatusBadge(String status) {
    Color color;
    IconData icon;
    String label;

    switch (status) {
      case 'completed':
      case 'indexed':
        color = Colors.green;
        icon = Icons.verified_user_rounded;
        label = "HASHED";
        break;
      case 'processing':
        color = Colors.blue;
        icon = Icons.sync;
        label = "PROCESSING";
        break;
      case 'failed':
        color = Colors.red;
        icon = Icons.error_outline;
        label = "FAILED";
        break;
      default:
        color = Colors.orange;
        icon = Icons.hourglass_top_rounded;
        label = "PENDING";
    }

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      decoration: BoxDecoration(
        color: color.withOpacity(0.15),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: color.withOpacity(0.5)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(width: 6, height: 6, decoration: BoxDecoration(color: color, shape: BoxShape.circle)),
          const SizedBox(width: 6),
          Text(label, style: TextStyle(color: color, fontWeight: FontWeight.bold, fontSize: 10)),
        ],
      ),
    );
  }
  
  Widget _buildStatusBadgeInDetail(String status) {
    Color color;
    switch (status) {
      case 'completed':
      case 'indexed':
        color = Colors.green; break;
      case 'processing': color = Colors.blue; break;
      case 'failed': color = Colors.red; break;
      default: color = Colors.orange;
    }
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      decoration: BoxDecoration(
        color: color.withOpacity(0.15),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: color.withOpacity(0.5)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(width: 6, height: 6, decoration: BoxDecoration(color: color, shape: BoxShape.circle)),
          const SizedBox(width: 6),
          Text(status.toUpperCase(), style: TextStyle(color: color, fontWeight: FontWeight.bold, fontSize: 10)),
        ],
      ),
    );
  }
  
  Widget _buildOCRStatusBadgeInDetail(String? ocrStatus) {
    if (ocrStatus == null) {
      return Container();
    }
    
    Color color;
    String label;

    switch (ocrStatus) {
      case 'completed':
        color = Colors.green;
        label = "OCR READY";
        break;
      case 'processing':
        color = Colors.blue;
        label = "OCR PROCESSING";
        break;
      case 'failed':
        color = Colors.red;
        label = "OCR FAILED";
        break;
      case 'not_available':
        color = Colors.grey;
        label = "OCR N/A";
        break;
      default:
        color = Colors.orange;
        label = "OCR PENDING";
    }

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      decoration: BoxDecoration(
        color: color.withOpacity(0.15),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: color.withOpacity(0.5)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(width: 6, height: 6, decoration: BoxDecoration(color: color, shape: BoxShape.circle)),
          const SizedBox(width: 6),
          Text(label, style: TextStyle(color: color, fontWeight: FontWeight.bold, fontSize: 10)),
        ],
      ),
    );
  }
}

Future<void> _deleteDocumentFromDetail(BuildContext context, String docId, String serverUrl) async {
  final confirmed = await showDialog<bool>(
    context: context,
    builder: (context) => AlertDialog(
      backgroundColor: const Color(0xFF1E1E1E),
      title: const Text("Confirm Delete", style: TextStyle(color: Colors.white)),
      content: const Text("Are you sure you want to delete this document?", style: TextStyle(color: Colors.white70)),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context, false),
          child: const Text("Cancel"),
        ),
        ElevatedButton(
          onPressed: () => Navigator.pop(context, true),
          style: ElevatedButton.styleFrom(backgroundColor: Colors.red),
          child: const Text("Delete", style: TextStyle(color: Colors.white)),
        ),
      ],
    ),
  );

  if (confirmed != true) return;

  try {
    final response = await http.delete(Uri.parse('$serverUrl/api/v1/documents/$docId'));
    if (!context.mounted) return;

    if (response.statusCode == 200) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text("Document deleted successfully"), backgroundColor: Colors.green),
      );
      Navigator.pop(context, true); // Return true to indicate deletion
    } else {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text("Failed to delete: ${response.body}"), backgroundColor: Colors.red),
      );
    }
  } catch (e) {
    if (!context.mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text("Error: $e"), backgroundColor: Colors.red),
    );
  }
}

class DocumentDetailPage extends StatelessWidget {
  final Map<String, dynamic> doc;
  final String serverUrl;

  const DocumentDetailPage({super.key, required this.doc, required this.serverUrl});

  // Helper method to determine OCR status from text_content
  String _getOCRStatus() {
    final textContent = doc['text_content'];
    final status = doc['status'] ?? 'pending';
    
    if (textContent != null && textContent.toString().trim().isNotEmpty) {
      return 'completed'; // OCR has extracted text successfully
    } else if (status == 'processing') {
      return 'processing'; // Document is currently being processed
    } else if (status == 'pending') {
      return 'pending'; // Not yet processed
    } else {
      // Status is 'completed' or 'indexed' but no OCR text
      // This could mean: old document (before OCR feature) or OCR was skipped
      return 'not_available'; // OCR not available (not necessarily failed)
    }
  }

  @override
  Widget build(BuildContext context) {
    final imageUrl = "$serverUrl${doc['image_url']}";
    final status = doc['status'] ?? 'pending';
    final ocrStatus = _getOCRStatus();

    return Scaffold(
      backgroundColor: Colors.black,
      appBar: AppBar(title: const Text("Document Details"), backgroundColor: Colors.black),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Preview Card
            Container(
              decoration: BoxDecoration(
                color: const Color(0xFF1E1E1E),
                borderRadius: BorderRadius.circular(15),
                border: Border.all(color: Colors.white10),
              ),
              child: ClipRRect(
                borderRadius: BorderRadius.circular(15),
                child: Column(
                  children: [
                    Stack(
                      children: [
                        GestureDetector(
                          onTap: () {
                            Navigator.push(
                              context,
                              MaterialPageRoute(
                                builder: (_) => FullScreenImageViewer(imageUrl: imageUrl),
                              ),
                            );
                          },
                          child: Hero(
                            tag: imageUrl,
                            child: Container(
                              height: 400,
                              width: double.infinity,
                              color: Colors.black,
                              child: Image.network(
                                imageUrl,
                                fit: BoxFit.contain,
                                loadingBuilder: (c, child, p) => p == null ? child : const Center(child: CircularProgressIndicator(color: Color(0xFFD4AF37))),
                                errorBuilder: (_, __, ___) => const Center(child: Icon(Icons.broken_image, size: 80, color: Colors.grey)),
                              ),
                            ),
                          ),
                        ),
                        Positioned(
                          bottom: 15,
                          right: 15,
                          child: Container(
                            padding: const EdgeInsets.all(8),
                            decoration: BoxDecoration(
                              color: Colors.black54,
                              borderRadius: BorderRadius.circular(20),
                              border: Border.all(color: const Color(0xFFD4AF37)),
                            ),
                            child: const Row(
                              mainAxisSize: MainAxisSize.min,
                              children: [
                                Icon(Icons.zoom_in, color: Color(0xFFD4AF37), size: 16),
                                SizedBox(width: 5),
                                Text("TAP TO ZOOM", style: TextStyle(color: Colors.white, fontSize: 10, fontWeight: FontWeight.bold)),
                              ],
                            ),
                          ),
                        ),
                      ],
                    ),
                    Container(
                      padding: const EdgeInsets.all(15),
                      width: double.infinity,
                      color: Colors.white.withOpacity(0.05),
                      child: Row(
                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                        children: [
                          const Text("AI PROCESSING PROOF", style: TextStyle(color: Colors.grey, fontSize: 10, letterSpacing: 1.5, fontWeight: FontWeight.bold)),
                          _buildStatusBadge(status),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 30),

            Center(
              child: ElevatedButton.icon(
                onPressed: () => _deleteDocumentFromDetail(context, doc['id'].toString(), serverUrl),
                icon: const Icon(Icons.delete_forever, color: Colors.white),
                label: const Text("DELETE DOCUMENT"),
                style: ElevatedButton.styleFrom(
                  backgroundColor: Colors.red[900],
                  padding: const EdgeInsets.symmetric(horizontal: 30, vertical: 15),
                ),
              ),
            ),
            
            const SizedBox(height: 30),

            const Text("METADATA", style: TextStyle(letterSpacing: 2, fontWeight: FontWeight.bold, color: Color(0xFFD4AF37), fontSize: 12)),
            const Divider(color: Colors.white10, height: 25),
            
            _buildInfoRow(Icons.folder_shared, "Khazanah", doc['khazanah'] ?? "-"),
            _buildInfoRow(Icons.pages, "Page Number", doc['page_number']?.toString() ?? "-"),
            _buildInfoRow(Icons.description, "Description", doc['description'] ?? "No description provided."),
            _buildInfoRow(Icons.calendar_today, "Accepted At", doc['created_at'] ?? "-"),
            
            const SizedBox(height: 30),
            const Text("TECHNICAL INFO", style: TextStyle(letterSpacing: 2, fontWeight: FontWeight.bold, color: Color(0xFFD4AF37), fontSize: 12)),
            const Divider(color: Colors.white10, height: 25),
            
            // Fingerprint UUID (most important - user-facing ID)
            _buildFingerprintRow(context, doc['fingerprint'] ?? "N/A"),
            
            _buildInfoRow(Icons.fingerprint, "Vector ID", doc['vector_id'] == -1 ? "GENERATING..." : doc['vector_id']?.toString() ?? "Pending"),
            _buildInfoRow(Icons.numbers, "DB ID", doc['id'].toString()),
            _buildInfoRow(Icons.image_outlined, "Storage Path", doc['image_path'] ?? "-"),
            if (doc['content_hash'] != null)
              _buildInfoRow(Icons.tag, "Content Hash", "${doc['content_hash'].toString().substring(0, 16)}..."),

            // OCR Status Section
            const SizedBox(height: 30),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                const Text("OCR EXTRACTION", style: TextStyle(letterSpacing: 2, fontWeight: FontWeight.bold, color: Color(0xFFD4AF37), fontSize: 12)),
                _buildOCRStatusBadge(ocrStatus),
              ],
            ),
            const Divider(color: Colors.white10, height: 25),
            
            // View OCR Button (only show if OCR is completed)
            if (ocrStatus == 'completed')
              Center(
                child: ElevatedButton.icon(
                  onPressed: () => _viewOCRContent(context, doc['id'].toString()),
                  icon: const Icon(Icons.text_snippet, color: Colors.white),
                  label: const Text("VIEW OCR CONTENT"),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: const Color(0xFFD4AF37),
                    foregroundColor: Colors.black,
                    padding: const EdgeInsets.symmetric(horizontal: 30, vertical: 15),
                  ),
                ),
              )
            // Process OCR Button (for documents without OCR or failed)
            else if (ocrStatus == 'not_available' || ocrStatus == 'failed')
              Center(
                child: Column(
                  children: [
                    Padding(
                      padding: const EdgeInsets.symmetric(vertical: 8.0),
                      child: Text(
                        ocrStatus == 'failed'
                          ? "❌ OCR extraction failed"
                          : "ℹ️ OCR not available (old document or not processed)",
                        style: const TextStyle(color: Colors.grey, fontSize: 14),
                        textAlign: TextAlign.center,
                      ),
                    ),
                    const SizedBox(height: 8),
                    ElevatedButton.icon(
                      onPressed: () => _processOCR(context, doc['id'].toString()),
                      icon: const Icon(Icons.replay, color: Colors.white),
                      label: Text(ocrStatus == 'failed' ? "RETRY OCR" : "PROCESS OCR"),
                      style: ElevatedButton.styleFrom(
                        backgroundColor: Colors.blue[700],
                        foregroundColor: Colors.white,
                        padding: const EdgeInsets.symmetric(horizontal: 30, vertical: 15),
                      ),
                    ),
                  ],
                ),
              )
            else
              Center(
                child: Padding(
                  padding: const EdgeInsets.all(16.0),
                  child: Text(
                    ocrStatus == 'processing' 
                      ? "⏳ OCR extraction in progress..." 
                      : "⏸️ OCR not yet processed",
                    style: const TextStyle(color: Colors.grey, fontSize: 14),
                    textAlign: TextAlign.center,
                  ),
                ),
              ),

            if (status == 'failed' && doc['error_message'] != null) ...[
               const SizedBox(height: 25),
               const Text("ERROR DETAILS", style: TextStyle(color: Colors.redAccent, fontWeight: FontWeight.bold, fontSize: 12)),
               const Divider(color: Colors.redAccent, height: 25),
               Container(
                 padding: const EdgeInsets.all(12),
                 decoration: BoxDecoration(color: Colors.red.withOpacity(0.1), borderRadius: BorderRadius.circular(8)),
                 child: Text(doc['error_message'], style: const TextStyle(color: Colors.redAccent, fontSize: 13)),
               ),
            ]
          ],
        ),
      ),
    );
  }

  Widget _buildInfoRow(IconData icon, String label, String value) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 12),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            padding: const EdgeInsets.all(8),
            decoration: BoxDecoration(color: Colors.white.withOpacity(0.05), borderRadius: BorderRadius.circular(8)),
            child: Icon(icon, size: 18, color: const Color(0xFFD4AF37)),
          ),
          const SizedBox(width: 15),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(label, style: const TextStyle(color: Colors.grey, fontSize: 11, fontWeight: FontWeight.bold)),
                const SizedBox(height: 4),
                Text(value, style: const TextStyle(color: Colors.white, fontSize: 15)),
              ],
            ),
          ),
        ],
      ),
    );
  }
  
  Widget _buildOCRStatusBadge(String? ocrStatus) {
    if (ocrStatus == null) {
      return const SizedBox.shrink();
    }
    
    Color color;
    IconData icon;
    String label;

    switch (ocrStatus) {
      case 'completed':
        color = Colors.green;
        icon = Icons.check_circle;
        label = "EXTRACTED";
        break;
      case 'processing':
        color = Colors.blue;
        icon = Icons.sync;
        label = "PROCESSING";
        break;
      case 'failed':
        color = Colors.red;
        icon = Icons.error_outline;
        label = "FAILED";
        break;
      case 'not_available':
        color = Colors.grey;
        icon = Icons.info_outline;
        label = "N/A";
        break;
      default:
        color = Colors.orange;
        icon = Icons.pending_outlined;
        label = "PENDING";
    }

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      decoration: BoxDecoration(
        color: color.withOpacity(0.15),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: color.withOpacity(0.5)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 14, color: color),
          const SizedBox(width: 6),
          Text(label, style: TextStyle(color: color, fontWeight: FontWeight.bold, fontSize: 10)),
        ],
      ),
    );
  }

  Future<void> _viewOCRContent(BuildContext context, String docId) async {
    // Get OCR text directly from document data (text_content field)
    final ocrText = doc['text_content'];
    
    if (ocrText == null || ocrText.toString().trim().isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text("No OCR content available"),
          backgroundColor: Colors.orange,
        ),
      );
      return;
    }

    Navigator.push(
      context,
      MaterialPageRoute(
        builder: (_) => OCRViewerPage(
          docId: docId,
          ocrText: ocrText.toString(),
          documentName: doc['khazanah'] ?? 'Unknown',
          pageNumber: doc['page_number']?.toString() ?? '-',
        ),
      ),
    );
  }

  Future<void> _processOCR(BuildContext context, String docId) async {
    // Confirm before processing
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        backgroundColor: const Color(0xFF1E1E1E),
        title: const Text("Process OCR", style: TextStyle(color: Colors.white)),
        content: const Text(
          "This will extract text from the document image. Continue?",
          style: TextStyle(color: Colors.white70),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text("Cancel"),
          ),
          ElevatedButton(
            onPressed: () => Navigator.pop(context, true),
            style: ElevatedButton.styleFrom(backgroundColor: Colors.blue[700]),
            child: const Text("Process", style: TextStyle(color: Colors.white)),
          ),
        ],
      ),
    );

    if (confirmed != true) return;

    // Show loading dialog
    showDialog(
      context: context,
      barrierDismissible: false,
      builder: (context) => const AlertDialog(
        backgroundColor: Color(0xFF1E1E1E),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            CircularProgressIndicator(color: Color(0xFFD4AF37)),
            SizedBox(height: 16),
            Text(
              "Processing OCR...\nThis may take a few seconds",
              style: TextStyle(color: Colors.white70),
              textAlign: TextAlign.center,
            ),
          ],
        ),
      ),
    );

    try {
      final uri = Uri.parse('$serverUrl/api/v1/documents/$docId/ocr/process');
      final response = await http.post(uri);

      if (!context.mounted) return;
      Navigator.pop(context); // Close loading dialog

      if (response.statusCode == 200 || response.statusCode == 202) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text("OCR processing started! Refresh to see results."),
            backgroundColor: Colors.green,
            duration: Duration(seconds: 3),
          ),
        );
        
        // Optionally refresh the page after a delay
        await Future.delayed(const Duration(seconds: 2));
        if (context.mounted) {
          Navigator.pop(context, true); // Return true to trigger refresh in parent
        }
      } else {
        final errorMsg = response.body.isNotEmpty ? response.body : 'Unknown error';
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text("Failed to process OCR: $errorMsg"),
            backgroundColor: Colors.red,
            duration: const Duration(seconds: 4),
          ),
        );
      }
    } catch (e) {
      if (!context.mounted) return;
      Navigator.pop(context); // Close loading dialog
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text("Error: $e"),
          backgroundColor: Colors.red,
          duration: const Duration(seconds: 4),
        ),
      );
    }
  }

  Widget _buildFingerprintRow(BuildContext context, String fingerprint) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 12),
      child: Container(
        padding: const EdgeInsets.all(15),
        decoration: BoxDecoration(
          color: const Color(0xFFD4AF37).withOpacity(0.1),
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: const Color(0xFFD4AF37).withOpacity(0.3)),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const Icon(Icons.qr_code_2, size: 20, color: Color(0xFFD4AF37)),
                const SizedBox(width: 10),
                const Text(
                  "DOCUMENT FINGERPRINT",
                  style: TextStyle(
                    color: Color(0xFFD4AF37),
                    fontSize: 11,
                    fontWeight: FontWeight.bold,
                    letterSpacing: 1.2,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 10),
            Row(
              children: [
                Expanded(
                  child: Text(
                    fingerprint,
                    style: const TextStyle(
                      color: Colors.white,
                      fontSize: 13,
                      fontFamily: 'monospace',
                      letterSpacing: 0.5,
                    ),
                  ),
                ),
                const SizedBox(width: 10),
                IconButton(
                  icon: const Icon(Icons.copy, size: 20, color: Color(0xFFD4AF37)),
                  onPressed: () {
                    Clipboard.setData(ClipboardData(text: fingerprint));
                    ScaffoldMessenger.of(context).showSnackBar(
                      const SnackBar(
                        content: Text("📋 Fingerprint copied to clipboard!"),
                        backgroundColor: Color(0xFFD4AF37),
                        duration: Duration(seconds: 2),
                      ),
                    );
                  },
                  tooltip: "Copy fingerprint",
                ),
              ],
            ),
            const SizedBox(height: 8),
            const Text(
              "Use this unique ID to reference this document across systems",
              style: TextStyle(color: Colors.grey, fontSize: 10, fontStyle: FontStyle.italic),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildStatusBadge(String status) {
    Color color;
    IconData icon;
    String label;

    switch (status) {
      case 'completed':
      case 'indexed':
        color = Colors.green;
        icon = Icons.verified_user_rounded;
        label = "HASHED";
        break;
      case 'processing':
        color = Colors.blue;
        icon = Icons.sync;
        label = "PROCESSING";
        break;
      case 'failed':
        color = Colors.red;
        icon = Icons.error_outline;
        label = "FAILED";
        break;
      default:
        color = Colors.orange;
        icon = Icons.hourglass_top_rounded;
        label = "PENDING";
    }

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      decoration: BoxDecoration(
        color: color.withOpacity(0.15),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: color.withOpacity(0.5)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(width: 6, height: 6, decoration: BoxDecoration(color: color, shape: BoxShape.circle)),
          const SizedBox(width: 6),
          Text(label, style: TextStyle(color: color, fontWeight: FontWeight.bold, fontSize: 10)),
        ],
      ),
    );
  }
  
  Widget _buildStatusBadgeInDetail(String status) {
    Color color;
    switch (status) {
      case 'completed':
      case 'indexed':
        color = Colors.green; break;
      case 'processing': color = Colors.blue; break;
      case 'failed': color = Colors.red; break;
      default: color = Colors.orange;
    }
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      decoration: BoxDecoration(
        color: color.withOpacity(0.15),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: color.withOpacity(0.5)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(width: 6, height: 6, decoration: BoxDecoration(color: color, shape: BoxShape.circle)),
          const SizedBox(width: 6),
          Text(status.toUpperCase(), style: TextStyle(color: color, fontWeight: FontWeight.bold, fontSize: 10)),
        ],
      ),
    );
  }
  
  Widget _buildOCRStatusBadgeInDetail(String? ocrStatus) {
    if (ocrStatus == null) {
      return Container();
    }
    
    Color color;
    String label;

    switch (ocrStatus) {
      case 'completed':
        color = Colors.green;
        label = "OCR READY";
        break;
      case 'processing':
        color = Colors.blue;
        label = "OCR PROCESSING";
        break;
      case 'failed':
        color = Colors.red;
        label = "OCR FAILED";
        break;
      default:
        color = Colors.orange;
        label = "OCR PENDING";
    }

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      decoration: BoxDecoration(
        color: color.withOpacity(0.15),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: color.withOpacity(0.5)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(width: 6, height: 6, decoration: BoxDecoration(color: color, shape: BoxShape.circle)),
          const SizedBox(width: 6),
          Text(label, style: TextStyle(color: color, fontWeight: FontWeight.bold, fontSize: 10)),
        ],
      ),
    );
  }
}

// OCR Viewer Page
class OCRViewerPage extends StatelessWidget {
  final String docId;
  final String ocrText;
  final String documentName;
  final String pageNumber;

  const OCRViewerPage({
    super.key,
    required this.docId,
    required this.ocrText,
    required this.documentName,
    required this.pageNumber,
  });

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.black,
      appBar: AppBar(
        title: const Text("OCR Content"),
        backgroundColor: const Color(0xFF1E1E1E),
        actions: [
          IconButton(
            icon: const Icon(Icons.copy_all),
            onPressed: () {
              Clipboard.setData(ClipboardData(text: ocrText));
              ScaffoldMessenger.of(context).showSnackBar(
                const SnackBar(
                  content: Text("📋 OCR content copied to clipboard!"),
                  backgroundColor: Color(0xFFD4AF37),
                  duration: Duration(seconds: 2),
                ),
              );
            },
            tooltip: "Copy all text",
          ),
        ],
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Document Info Card
            Container(
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                color: const Color(0xFF1E1E1E),
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: Colors.white10),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      const Icon(Icons.description, color: Color(0xFFD4AF37), size: 24),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              documentName,
                              style: const TextStyle(
                                color: Color(0xFFD4AF37),
                                fontSize: 18,
                                fontWeight: FontWeight.bold,
                              ),
                            ),
                            Text(
                              "Page $pageNumber",
                              style: const TextStyle(color: Colors.white70, fontSize: 14),
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                  const Divider(color: Colors.white10, height: 24),
                  Row(
                    children: [
                      const Icon(Icons.text_fields, color: Colors.grey, size: 16),
                      const SizedBox(width: 8),
                      Text(
                        "${ocrText.split(' ').length} words • ${ocrText.length} characters",
                        style: const TextStyle(color: Colors.grey, fontSize: 12),
                      ),
                    ],
                  ),
                ],
              ),
            ),
            
            const SizedBox(height: 24),
            
            // Extracted Text Section
            const Row(
              children: [
                Icon(Icons.text_snippet, color: Color(0xFFD4AF37), size: 20),
                SizedBox(width: 8),
                Text(
                  "EXTRACTED TEXT",
                  style: TextStyle(
                    letterSpacing: 2,
                    fontWeight: FontWeight.bold,
                    color: Color(0xFFD4AF37),
                    fontSize: 12,
                  ),
                ),
              ],
            ),
            const Divider(color: Colors.white10, height: 25),
            
            // OCR Text Content
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                color: const Color(0xFF1E1E1E),
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: Colors.white10),
              ),
              child: SelectableText(
                ocrText.isEmpty ? "No text extracted" : ocrText,
                style: const TextStyle(
                  color: Colors.white,
                  fontSize: 15,
                  height: 1.6,
                  fontFamily: 'monospace',
                ),
              ),
            ),
            
            const SizedBox(height: 30),
            
            // Action Buttons
            Row(
              children: [
                Expanded(
                  child: ElevatedButton.icon(
                    onPressed: () {
                      Clipboard.setData(ClipboardData(text: ocrText));
                      ScaffoldMessenger.of(context).showSnackBar(
                        const SnackBar(
                          content: Text("📋 Text copied!"),
                          backgroundColor: Color(0xFFD4AF37),
                          duration: Duration(seconds: 2),
                        ),
                      );
                    },
                    icon: const Icon(Icons.copy),
                    label: const Text("COPY TEXT"),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: const Color(0xFFD4AF37),
                      foregroundColor: Colors.black,
                      padding: const EdgeInsets.symmetric(vertical: 15),
                    ),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class FullScreenImageViewer extends StatelessWidget {
  final String imageUrl;

  const FullScreenImageViewer({super.key, required this.imageUrl});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.black,
      appBar: AppBar(
        backgroundColor: Colors.black,
        iconTheme: const IconThemeData(color: Colors.white),
        actions: [
          IconButton(
            icon: const Icon(Icons.close),
            onPressed: () => Navigator.pop(context),
          ),
        ],
      ),
      body: Center(
        child: Hero(
          tag: imageUrl,
          child: InteractiveViewer(
            panEnabled: true,
            boundaryMargin: const EdgeInsets.all(20),
            minScale: 0.5,
            maxScale: 10.0, // High zoom capability
            child: Image.network(
              imageUrl,
              loadingBuilder: (c, child, p) => p == null 
                  ? child 
                  : const Center(child: CircularProgressIndicator(color: Color(0xFFD4AF37))),
              errorBuilder: (_, __, ___) => const Center(
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Icon(Icons.broken_image, size: 100, color: Colors.grey),
                      SizedBox(height: 20),
                      Text("Failed to load image", style: TextStyle(color: Colors.white54)),
                    ],
                  )
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class SettingsPage extends StatefulWidget {
  const SettingsPage({super.key});

  @override
  State<SettingsPage> createState() => _SettingsPageState();
}

class _SettingsPageState extends State<SettingsPage> {
  String _scannerMode = 'auto'; // 'auto', 'pro', or 'ai'
  bool _isCheckingConnection = false;
  String _connectionStatus = "Not checked";
  String _serverUrl = "http://192.168.1.10:8000";
  bool _defaultFlash = false;

  // Configurable search thresholds
  double _visualThreshold = 0.55;
  double _textThreshold = 0.20;
  double _visualOnlyThreshold = 0.70;
  bool _useOcrVerification = false;
  String _regionStrategy = '4-strip';

  @override
  void initState() {
    super.initState();
    _loadSettings();
  }

  Future<void> _loadSettings() async {
    final prefs = PreferencesService();
    final mode = await prefs.getScannerMode();
    final url = await prefs.getServerUrl();
    final flash = await prefs.getDefaultFlashMode();
    final vt = await prefs.getVisualThreshold();
    final tt = await prefs.getTextThreshold();
    final vot = await prefs.getVisualOnlyThreshold();
    final ocr = await prefs.getUseOcrVerification();
    final rs = await prefs.getRegionStrategy();
    if (mounted) setState(() {
      _scannerMode = mode;
      _serverUrl = url;
      _defaultFlash = flash;
      _visualThreshold = vt;
      _textThreshold = tt;
      _visualOnlyThreshold = vot;
      _useOcrVerification = ocr;
      _regionStrategy = rs;
    });
  }

  Future<void> _resetThresholds() async {
    await PreferencesService().resetThresholds();
    setState(() {
      _visualThreshold = 0.55;
      _textThreshold = 0.20;
      _visualOnlyThreshold = 0.70;
      _useOcrVerification = false;
      _regionStrategy = '4-strip';
    });
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text("✅ Thresholds reset to defaults"),
          backgroundColor: Colors.green,
        ),
      );
    }
  }

  Future<void> _toggleDefaultFlash(bool value) async {
    await PreferencesService().setDefaultFlashMode(value);
    if (mounted) setState(() => _defaultFlash = value);
  }

  Future<void> _setScannerMode(String mode) async {
    await PreferencesService().setScannerMode(mode);
    if (mounted) setState(() => _scannerMode = mode);
  }

  Future<void> _checkConnection() async {
    setState(() {
      _isCheckingConnection = true;
      _connectionStatus = "Checking...";
    });

    final isConnected = await PreferencesService().checkConnection();

    if (mounted) {
      setState(() {
        _isCheckingConnection = false;
        _connectionStatus = isConnected ? "✅ Connected" : "❌ Disconnected";
      });
    }
  }

  Future<void> _editServerUrl() async {
    final controller = TextEditingController(text: _serverUrl);
    final newUrl = await showDialog<String>(
      context: context,
      builder: (context) => AlertDialog(
        backgroundColor: const Color(0xFF1E1E1E),
        title: const Text("Edit Server URL", style: TextStyle(color: Colors.white)),
        content: TextField(
          controller: controller,
          style: const TextStyle(color: Colors.white),
          decoration: const InputDecoration(
            hintText: "http://192.168.1.10:8000",
            hintStyle: TextStyle(color: Colors.grey),
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text("Cancel", style: TextStyle(color: Colors.grey)),
          ),
          TextButton(
            onPressed: () => Navigator.pop(context, controller.text),
            child: const Text("Save", style: TextStyle(color: Color(0xFFD4AF37))),
          ),
        ],
      ),
    );

    if (newUrl != null && newUrl.isNotEmpty && newUrl != _serverUrl) {
      await PreferencesService().setServerUrl(newUrl);
      setState(() => _serverUrl = newUrl);
      // Auto-check connection after change
      _checkConnection();
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text("Settings"),
        backgroundColor: Colors.black,
      ),
      body: ListView(
        children: [
          // === SCANNER MODE SELECTION ===
          Padding(
            padding: const EdgeInsets.all(16.0),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    const Icon(Icons.document_scanner, 
                              color: Color(0xFFD4AF37), size: 28),
                    const SizedBox(width: 12),
                    Text(
                      "Document Scanner Mode",
                      style: GoogleFonts.outfit(
                        fontSize: 18,
                        fontWeight: FontWeight.bold,
                        color: Colors.white,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 8),
                Text(
                  "Choose the scanner method for document capture. Each mode uses different detection algorithms.",
                  style: TextStyle(color: Colors.grey[400], fontSize: 13),
                ),
              ],
            ),
          ),
          
          // AUTO MODE (ML Kit)
          _buildScannerModeCard(
            mode: 'auto',
            title: 'AUTO MODE',
            subtitle: 'Google ML Kit Scanner',
            icon: Icons.auto_awesome,
            color: Colors.blue,
            description: '✓ Automatic edge detection\n'
                        '✓ Perspective correction\n'
                        '✓ Built-in filters (B&W, contrast)\n'
                        '✓ Fastest processing',
            badge: 'RECOMMENDED',
          ),
          
          const SizedBox(height: 8),
          
          // PRO MODE (Edge Detection)
          _buildScannerModeCard(
            mode: 'pro',
            title: 'PRO MODE',
            subtitle: 'Manual Camera + Edge Detection',
            icon: Icons.camera_alt,
            color: const Color(0xFFD4AF37),
            description: '✓ Maximum resolution capture\n'
                        '✓ Manual controls (flash, focus)\n'
                        '✓ Sobel edge detection preview\n'
                        '✓ Best for archival documents',
            badge: 'HIGH QUALITY',
          ),
          
          const SizedBox(height: 8),
          
          // AI MODE (MobileSAM)
          _buildScannerModeCard(
            mode: 'ai',
            title: 'AI MODE',
            subtitle: 'MobileSAM AI Segmentation',
            icon: Icons.psychology,
            color: const Color(0xFF6A0DAD),
            description: '✓ AI-powered boundary detection\n'
                        '✓ Precise document segmentation\n'
                        '✓ Handles complex backgrounds\n'
                        '⚠ Requires model download (40MB)',
            badge: 'EXPERIMENTAL',
          ),
          
          // AI MODE Info Banner
          Container(
            margin: const EdgeInsets.fromLTRB(16, 12, 16, 0),
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: const Color(0xFF6A0DAD).withOpacity(0.1),
              border: Border.all(color: const Color(0xFF6A0DAD).withOpacity(0.5)),
              borderRadius: BorderRadius.circular(8),
            ),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Icon(Icons.download, color: Color(0xFF6A0DAD), size: 20),
                const SizedBox(width: 12),
                Expanded(
                  child: Text(
                    "AI MODE requires downloading the MobileSAM model (40MB). "
                    "Without it, AI MODE will fallback to edge detection.\n\n"
                    "See docs/MOBILESAM_SETUP.md for setup instructions.",
                    style: const TextStyle(
                      color: Color(0xFF9DB4D4),
                      fontSize: 12,
                      height: 1.4,
                    ),
                  ),
                ),
              ],
            ),
          ),

          
          const Divider(color: Colors.white10, height: 32),

          // === CAMERA SETTINGS ===
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
            child: Text("Camera Preferences", style: GoogleFonts.outfit(fontSize: 18, fontWeight: FontWeight.bold, color: Colors.white)),
          ),
          
          SwitchListTile(
            title: const Text("Default Flash (Torch Mode)", style: TextStyle(color: Colors.white)),
            subtitle: const Text("(Pro/AI Mode Only) Turn on light automatically when camera opens.", style: TextStyle(color: Colors.grey, fontSize: 12)),
            value: _defaultFlash,
            activeColor: const Color(0xFFD4AF37),
            onChanged: _toggleDefaultFlash,
            secondary: Icon(Icons.highlight, color: _defaultFlash ? const Color(0xFFD4AF37) : Colors.grey),
            contentPadding: const EdgeInsets.symmetric(horizontal: 16),
          ),
          
          const Divider(color: Colors.white10, height: 32),

          // === SEARCH MODE ===
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
            child: Row(
              children: [
                Icon(_useOcrVerification ? Icons.biotech : Icons.bolt,
                     color: _useOcrVerification ? const Color(0xFF6A0DAD) : Colors.amber, size: 28),
                const SizedBox(width: 12),
                Text(
                  "Search Mode",
                  style: GoogleFonts.outfit(
                    fontSize: 18,
                    fontWeight: FontWeight.bold,
                    color: Colors.white,
                  ),
                ),
                const SizedBox(width: 8),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                  decoration: BoxDecoration(
                    color: _useOcrVerification
                        ? const Color(0xFF6A0DAD).withAlpha(50)
                        : Colors.amber.withAlpha(50),
                    borderRadius: BorderRadius.circular(6),
                  ),
                  child: Text(
                    _useOcrVerification ? "THOROUGH" : "FAST",
                    style: TextStyle(
                      fontSize: 11,
                      fontWeight: FontWeight.bold,
                      color: _useOcrVerification
                          ? const Color(0xFF6A0DAD)
                          : Colors.amber,
                    ),
                  ),
                ),
              ],
            ),
          ),

          // Mode selector cards
          Container(
            margin: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
            child: Row(
              children: [
                // FAST Mode
                Expanded(
                  child: GestureDetector(
                    onTap: () async {
                      await PreferencesService().setUseOcrVerification(false);
                      setState(() => _useOcrVerification = false);
                    },
                    child: Container(
                      padding: const EdgeInsets.all(12),
                      decoration: BoxDecoration(
                        color: !_useOcrVerification
                            ? Colors.amber.withAlpha(25)
                            : const Color(0xFF1E1E1E),
                        border: Border.all(
                          color: !_useOcrVerification ? Colors.amber : Colors.white10,
                          width: !_useOcrVerification ? 2 : 1,
                        ),
                        borderRadius: BorderRadius.circular(10),
                      ),
                      child: Column(
                        children: [
                          Icon(Icons.bolt, color: !_useOcrVerification ? Colors.amber : Colors.grey, size: 28),
                          const SizedBox(height: 6),
                          Text("FAST", style: TextStyle(
                            fontWeight: FontWeight.bold,
                            color: !_useOcrVerification ? Colors.amber : Colors.grey,
                          )),
                          const SizedBox(height: 4),
                          Text("~5-8 sec", style: TextStyle(fontSize: 11, color: Colors.grey[500])),
                          Text("Visual Only", style: TextStyle(fontSize: 10, color: Colors.grey[600])),
                        ],
                      ),
                    ),
                  ),
                ),
                const SizedBox(width: 10),
                // THOROUGH Mode
                Expanded(
                  child: GestureDetector(
                    onTap: () async {
                      await PreferencesService().setUseOcrVerification(true);
                      setState(() => _useOcrVerification = true);
                    },
                    child: Container(
                      padding: const EdgeInsets.all(12),
                      decoration: BoxDecoration(
                        color: _useOcrVerification
                            ? const Color(0xFF6A0DAD).withAlpha(25)
                            : const Color(0xFF1E1E1E),
                        border: Border.all(
                          color: _useOcrVerification ? const Color(0xFF6A0DAD) : Colors.white10,
                          width: _useOcrVerification ? 2 : 1,
                        ),
                        borderRadius: BorderRadius.circular(10),
                      ),
                      child: Column(
                        children: [
                          Icon(Icons.biotech, color: _useOcrVerification ? const Color(0xFF6A0DAD) : Colors.grey, size: 28),
                          const SizedBox(height: 6),
                          Text("THOROUGH", style: TextStyle(
                            fontWeight: FontWeight.bold,
                            color: _useOcrVerification ? const Color(0xFF6A0DAD) : Colors.grey,
                          )),
                          const SizedBox(height: 4),
                          Text("~20-40 sec", style: TextStyle(fontSize: 11, color: Colors.grey[500])),
                          Text("Visual + OCR", style: TextStyle(fontSize: 10, color: Colors.grey[600])),
                        ],
                      ),
                    ),
                  ),
                ),
              ],
            ),
          ),

          // Info banner
          Container(
            margin: const EdgeInsets.fromLTRB(16, 8, 16, 0),
            padding: const EdgeInsets.all(10),
            decoration: BoxDecoration(
              color: Colors.white.withAlpha(8),
              borderRadius: BorderRadius.circular(8),
            ),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Icon(Icons.info_outline, color: Colors.grey[600], size: 18),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    _useOcrVerification
                        ? "THOROUGH mode runs OCR text extraction on the query image and compares text content. Best for pages with identical layouts but different text."
                        : "FAST mode uses visual fingerprinting only. Recommended for most use cases. Switch to THOROUGH if you have visually similar pages.",
                    style: TextStyle(color: Colors.grey[500], fontSize: 11, height: 1.4),
                  ),
                ),
              ],
            ),
          ),

          const Divider(color: Colors.white10, height: 32),

          // === DNA FINGERPRINT DEPTH (Region Strategy) ===
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
            child: Row(
              children: [
                const Icon(Icons.grid_on, color: Color(0xFFD4AF37), size: 28),
                const SizedBox(width: 12),
                Expanded(
                  child: Text(
                    "DNA Fingerprint Depth",
                    style: GoogleFonts.outfit(
                      fontSize: 18,
                      fontWeight: FontWeight.bold,
                      color: Colors.white,
                    ),
                  ),
                ),
              ],
            ),
          ),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: Text(
              "More regions = more unique fingerprint = better document-as-barcode identification, but slower processing.",
              style: TextStyle(color: Colors.grey[400], fontSize: 13),
            ),
          ),
          const SizedBox(height: 12),

          // Region strategy cards
          _buildRegionCard(
            strategy: '4-strip',
            label: '4 Strips',
            icon: Icons.view_agenda,
            color: Colors.cyan,
            regions: 4,
            speed: '~2-4s',
            description: '4 horizontal strips + global\nFastest option',
            diagram: '▬▬▬\n▬▬▬\n▬▬▬\n▬▬▬',
          ),
          _buildRegionCard(
            strategy: '9-grid',
            label: '9 Grid (3×3)',
            icon: Icons.grid_3x3,
            color: const Color(0xFFD4AF37),
            regions: 10,
            speed: '~5-10s',
            description: '3×3 grid + global\nBalanced accuracy & speed',
            diagram: '┌─┬─┬─┐\n├─┼─┼─┤\n└─┴─┴─┘',
            badge: 'RECOMMENDED',
          ),
          _buildRegionCard(
            strategy: '16-grid',
            label: '16 Grid (4×4)',
            icon: Icons.grid_4x4,
            color: const Color(0xFF6A0DAD),
            regions: 17,
            speed: '~10-18s',
            description: '4×4 grid + global\nMaximum accuracy',
            diagram: '┌┬┬┬┐\n├┼┼┼┤\n├┼┼┼┤\n└┴┴┴┘',
            badge: 'PRECISION',
          ),

          const Divider(color: Colors.white10, height: 32),

          // === IDENTIFICATION THRESHOLDS ===
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
            child: Row(
              children: [
                const Icon(Icons.tune, color: Color(0xFFD4AF37), size: 28),
                const SizedBox(width: 12),
                Text(
                  "Identification Thresholds",
                  style: GoogleFonts.outfit(
                    fontSize: 18,
                    fontWeight: FontWeight.bold,
                    color: Colors.white,
                  ),
                ),
              ],
            ),
          ),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: Text(
              "Control how strict the document matching is. Lower values = more results (potential false positives). Higher values = fewer but more accurate results.",
              style: TextStyle(color: Colors.grey[400], fontSize: 13),
            ),
          ),
          const SizedBox(height: 12),

          // Visual Similarity Threshold
          _buildThresholdSlider(
            icon: Icons.visibility,
            label: "Visual Similarity",
            description: "Min weighted visual score to consider a match",
            value: _visualThreshold,
            min: 0.30,
            max: 0.95,
            color: Colors.blue,
            defaultVal: 0.55,
            onChanged: (v) async {
              setState(() => _visualThreshold = v);
              await PreferencesService().setVisualThreshold(v);
            },
          ),

          // Text Verification Threshold (only relevant in THOROUGH mode)
          if (_useOcrVerification) ...[
            _buildThresholdSlider(
              icon: Icons.text_fields,
              label: "Text Verification",
              description: "Min combined OCR text match ratio (Hybrid DNA)",
              value: _textThreshold,
              min: 0.05,
              max: 0.80,
              color: Colors.green,
              defaultVal: 0.20,
              onChanged: (v) async {
                setState(() => _textThreshold = v);
                await PreferencesService().setTextThreshold(v);
              },
            ),

            // Visual-Only Fallback Threshold
            _buildThresholdSlider(
              icon: Icons.image_search,
              label: "Visual-Only Fallback",
              description: "Min visual score when OCR fails during search",
              value: _visualOnlyThreshold,
              min: 0.40,
              max: 0.95,
              color: Colors.orange,
              defaultVal: 0.70,
              onChanged: (v) async {
                setState(() => _visualOnlyThreshold = v);
                await PreferencesService().setVisualOnlyThreshold(v);
              },
            ),
          ],

          // Reset button
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
            child: OutlinedButton.icon(
              onPressed: _resetThresholds,
              icon: const Icon(Icons.restart_alt, color: Colors.grey),
              label: const Text("Reset to Defaults", style: TextStyle(color: Colors.grey)),
              style: OutlinedButton.styleFrom(
                side: const BorderSide(color: Colors.white10),
                minimumSize: const Size(double.infinity, 44),
              ),
            ),
          ),

          const Divider(color: Colors.white10, height: 32),
          
          // === SERVER SETTINGS ===
          ListTile(
            leading: const Icon(Icons.link, color: Colors.grey),
            title: const Text("Server URL", style: TextStyle(color: Colors.white)),
            subtitle: Text(_serverUrl, style: const TextStyle(color: Colors.grey)),
            trailing: IconButton(
              icon: const Icon(Icons.edit, color: Color(0xFFD4AF37)),
              onPressed: _editServerUrl,
              tooltip: "Edit server URL",
            ),
          ),
          const Divider(color: Colors.white10),
          ListTile(
            leading: Icon(Icons.wifi, color: _connectionStatus.contains("✅") ? Colors.green : _connectionStatus.contains("❌") ? Colors.red : Colors.grey),
            title: const Text("Server Connection", style: TextStyle(color: Colors.white)),
            subtitle: Text(_connectionStatus, style: const TextStyle(color: Colors.grey)),
            trailing: _isCheckingConnection
                ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2))
                : IconButton(
                    icon: const Icon(Icons.refresh, color: Color(0xFFD4AF37)),
                    onPressed: _checkConnection,
                    tooltip: "Check connection",
                  ),
          ),
          const Divider(color: Colors.white10),
          const ListTile(
            leading: Icon(Icons.info_outline, color: Colors.grey),
            title: Text("Version", style: TextStyle(color: Colors.white)),
            subtitle: Text("2.0.0 (3-Mode Scanner)", style: TextStyle(color: Colors.grey)),
          ),
        ],
      ),
    );
  }
  
  Widget _buildRegionCard({
    required String strategy,
    required String label,
    required IconData icon,
    required Color color,
    required int regions,
    required String speed,
    required String description,
    required String diagram,
    String? badge,
  }) {
    final isSelected = _regionStrategy == strategy;
    return GestureDetector(
      onTap: () async {
        await PreferencesService().setRegionStrategy(strategy);
        setState(() => _regionStrategy = strategy);
      },
      child: Container(
        margin: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: isSelected ? color.withAlpha(20) : const Color(0xFF1E1E1E),
          border: Border.all(
            color: isSelected ? color : Colors.white10,
            width: isSelected ? 2 : 1,
          ),
          borderRadius: BorderRadius.circular(12),
        ),
        child: Row(
          children: [
            // Grid diagram
            Container(
              width: 48,
              height: 48,
              decoration: BoxDecoration(
                color: color.withAlpha(isSelected ? 40 : 15),
                borderRadius: BorderRadius.circular(8),
              ),
              alignment: Alignment.center,
              child: Icon(icon, color: isSelected ? color : Colors.grey, size: 28),
            ),
            const SizedBox(width: 14),
            // Info
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Text(label, style: TextStyle(
                        color: isSelected ? Colors.white : Colors.grey[400],
                        fontWeight: FontWeight.bold,
                        fontSize: 15,
                      )),
                      if (badge != null) ...[
                        const SizedBox(width: 8),
                        Container(
                          padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                          decoration: BoxDecoration(
                            color: color.withAlpha(50),
                            borderRadius: BorderRadius.circular(4),
                          ),
                          child: Text(badge, style: TextStyle(fontSize: 9, fontWeight: FontWeight.bold, color: color)),
                        ),
                      ],
                    ],
                  ),
                  const SizedBox(height: 2),
                  Text(description, style: TextStyle(color: Colors.grey[600], fontSize: 11, height: 1.3)),
                ],
              ),
            ),
            // Stats
            Column(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                  decoration: BoxDecoration(
                    color: color.withAlpha(isSelected ? 40 : 15),
                    borderRadius: BorderRadius.circular(6),
                  ),
                  child: Text("$regions rgn", style: TextStyle(
                    color: isSelected ? color : Colors.grey,
                    fontWeight: FontWeight.bold,
                    fontSize: 12,
                  )),
                ),
                const SizedBox(height: 4),
                Text(speed, style: TextStyle(color: Colors.grey[600], fontSize: 10)),
              ],
            ),
            const SizedBox(width: 8),
            // Selection indicator
            Icon(
              isSelected ? Icons.check_circle : Icons.radio_button_unchecked,
              color: isSelected ? color : Colors.grey[700],
              size: 22,
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildThresholdSlider({
    required IconData icon,
    required String label,
    required String description,
    required double value,
    required double min,
    required double max,
    required Color color,
    required double defaultVal,
    required Function(double) onChanged,
  }) {
    final isDefault = (value - defaultVal).abs() < 0.01;
    return Container(
      margin: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: const Color(0xFF1E1E1E),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: Colors.white10),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(icon, color: color, size: 22),
              const SizedBox(width: 10),
              Expanded(
                child: Text(label, style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 15)),
              ),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                decoration: BoxDecoration(
                  color: color.withAlpha(40),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Text(
                  "${(value * 100).round()}%",
                  style: TextStyle(color: color, fontWeight: FontWeight.bold, fontSize: 14),
                ),
              ),
              if (isDefault) ...[
                const SizedBox(width: 6),
                const Text("Default", style: TextStyle(color: Colors.grey, fontSize: 10)),
              ],
            ],
          ),
          const SizedBox(height: 4),
          Text(description, style: TextStyle(color: Colors.grey[500], fontSize: 12)),
          const SizedBox(height: 8),
          SliderTheme(
            data: SliderThemeData(
              activeTrackColor: color,
              inactiveTrackColor: color.withAlpha(50),
              thumbColor: color,
              overlayColor: color.withAlpha(30),
              trackHeight: 4,
              thumbShape: const RoundSliderThumbShape(enabledThumbRadius: 8),
            ),
            child: Slider(
              value: value,
              min: min,
              max: max,
              divisions: ((max - min) * 100).round(),
              onChanged: (v) => onChanged(double.parse(v.toStringAsFixed(2))),
            ),
          ),
          // Min/Max labels
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 8),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Text("${(min * 100).round()}% (Loose)", style: TextStyle(color: Colors.grey[600], fontSize: 10)),
                Text("${(max * 100).round()}% (Strict)", style: TextStyle(color: Colors.grey[600], fontSize: 10)),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildScannerModeCard({
    required String mode,
    required String title,
    required String subtitle,
    required IconData icon,
    required Color color,
    required String description,
    String? badge,
  }) {
    final isSelected = _scannerMode == mode;
    
    return GestureDetector(
      onTap: () => _setScannerMode(mode),
      child: Container(
        margin: const EdgeInsets.symmetric(horizontal: 16),
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: isSelected 
              ? color.withOpacity(0.15) 
              : const Color(0xFF1E1E1E),
          border: Border.all(
            color: isSelected ? color : Colors.white10,
            width: isSelected ? 2 : 1,
          ),
          borderRadius: BorderRadius.circular(12),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Container(
                  padding: const EdgeInsets.all(10),
                  decoration: BoxDecoration(
                    color: color.withOpacity(0.2),
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Icon(icon, color: color, size: 24),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          Text(
                            title,
                            style: GoogleFonts.outfit(
                              fontSize: 16,
                              fontWeight: FontWeight.bold,
                              color: Colors.white,
                            ),
                          ),
                          if (badge != null) ...[
                            const SizedBox(width: 8),
                            Container(
                              padding: const EdgeInsets.symmetric(
                                horizontal: 8,
                                vertical: 2,
                              ),
                              decoration: BoxDecoration(
                                color: color.withOpacity(0.3),
                                borderRadius: BorderRadius.circular(4),
                              ),
                              child: Text(
                                badge,
                                style: TextStyle(
                                  fontSize: 10,
                                                                   fontWeight: FontWeight.bold,
                                  color: color,
                                ),
                              ),
                            ),
                          ],
                        ],
                      ),
                      const SizedBox(height: 2),
                      Text(
                        subtitle,
                        style: TextStyle(
                          fontSize: 12,
                          color: Colors.grey[400],
                        ),
                      ),
                    ],
                  ),
                ),
                if (isSelected)
                  Icon(Icons.check_circle, color: color, size: 28),
              ],
            ),
            const SizedBox(height: 12),
            Text(
              description,
              style: TextStyle(
                fontSize: 13,
                color: Colors.grey[300],
                height: 1.4,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
