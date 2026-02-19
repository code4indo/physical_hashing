
import 'package:camera/camera.dart';
import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import 'preferences_service.dart';

class ProCameraScreen extends StatefulWidget {
  final List<CameraDescription> cameras;

  const ProCameraScreen({super.key, required this.cameras});

  @override
  State<ProCameraScreen> createState() => _ProCameraScreenState();
}

class _ProCameraScreenState extends State<ProCameraScreen> {
  late CameraController _controller;
  bool _isInit = false;
  bool _isTakingPicture = false;
  FlashMode _flashMode = FlashMode.off;

  @override
  void initState() {
    super.initState();
    _initCamera();
  }

  Future<void> _initCamera() async {
    // Pro Mode: Use maximum resolution available
    _controller = CameraController(
      widget.cameras[0],
      ResolutionPreset.max, // Highest possible quality
      enableAudio: false,
      imageFormatGroup: ImageFormatGroup.jpeg,
    );

    try {
      await _controller.initialize();
      
      // Load preference
      final isFlashOn = await PreferencesService().getDefaultFlashMode();
      print("📸 [ProCamera] Loading preference. Flash should be: $isFlashOn");
      
      _flashMode = isFlashOn ? FlashMode.torch : FlashMode.off;
      
      // Determine if flash is turned on
      try {
        await _controller.setFlashMode(_flashMode);
        // Use standard auto-focus (continuous not available in this version)
        await _controller.setFocusMode(FocusMode.auto);
        print("📸 [ProCamera] Flash: $_flashMode, Focus: Auto");
      } catch (e) {
        print("📸 [ProCamera] Failed to set flash/focus: $e");
      }
    } catch (e) {
      if (mounted) {
         ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Camera Error: $e')));
      }
    }

    if (mounted) {
      setState(() => _isInit = true);
    }
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  Future<void> _takePicture() async {
    if (_isTakingPicture || !_controller.value.isInitialized) return;

    setState(() => _isTakingPicture = true);

    try {
      // Focus before capture (if supported)
      if (_controller.value.focusPointSupported) {
           await _controller.setFocusMode(FocusMode.locked);
           await _controller.setExposureMode(ExposureMode.locked);
      }
      
      final image = await _controller.takePicture();
      
      // Auto-unlock focus
      if (_controller.value.focusPointSupported) {
           await _controller.setFocusMode(FocusMode.auto);
           await _controller.setExposureMode(ExposureMode.auto);
      }

      if (mounted) {
        Navigator.pop(context, image); // Return the captured file
      }
    } catch (e) {
      print("Error taking picture: $e");
    } finally {
      if (mounted) setState(() => _isTakingPicture = false);
    }
  }

  void _toggleFlash() {
    setState(() {
      _flashMode = _flashMode == FlashMode.off ? FlashMode.torch : FlashMode.off;
      _controller.setFlashMode(_flashMode);
    });
  }

  @override
  Widget build(BuildContext context) {
    if (!_isInit) return const Scaffold(backgroundColor: Colors.black, body: Center(child: CircularProgressIndicator()));

    return Scaffold(
      backgroundColor: Colors.black,
      body: Stack(
        children: [
          // 1. Camera Preview (Full Screen)
          SizedBox.expand(
            child: CameraPreview(_controller),
          ),
          
          // 2. Grid Overlay (Optional, for archival alignment)
          _buildGrid(),

          // 3. Top Controls
          SafeArea(
            child: Align(
              alignment: Alignment.topCenter,
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 20),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    IconButton(
                      icon: const Icon(Icons.close, color: Colors.white, size: 30),
                      onPressed: () => Navigator.pop(context),
                    ),
                     Container(
                        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                        decoration: BoxDecoration(color: Colors.black54, borderRadius: BorderRadius.circular(20)),
                        child: Text("PRO MODE (RAW)", style: GoogleFonts.outfit(color: Color(0xFFD4AF37), fontWeight: FontWeight.bold)) 
                     ),
                    IconButton(
                      icon: Icon(_flashMode == FlashMode.torch ? Icons.flash_on : Icons.flash_off, color: Colors.white, size: 30),
                      onPressed: _toggleFlash,
                    ),
                  ],
                ),
              ),
            ),
          ),

          // 4. Bottom Controls (Shutter)
          Align(
            alignment: Alignment.bottomCenter,
            child: Container(
              height: 180,
              width: double.infinity,
              decoration: const BoxDecoration(
                gradient: LinearGradient(
                    colors: [Colors.transparent, Colors.black87],
                    begin: Alignment.topCenter,
                    end: Alignment.bottomCenter
                )
              ),
              child: Center(
                child: GestureDetector(
                  onTap: _takePicture,
                  child: Container(
                    width: 80,
                    height: 80,
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      border: Border.all(color: Colors.white, width: 4),
                    ),
                    child: Center(
                      child: Container(
                        width: 70,
                        height: 70,
                        decoration: BoxDecoration(
                          shape: BoxShape.circle,
                          color: _isTakingPicture ? Colors.red : Colors.white,
                        ),
                      ),
                    ),
                  ),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildGrid() {
    return IgnorePointer(
      child: Center(
        child: Container(
          decoration: BoxDecoration(
            border: Border.all(color: Colors.white24, width: 1),
          ),
          child: Column(
            children: [
              Expanded(child: Row(children: [Expanded(child: Container(decoration: BoxDecoration(border: Border.all(color: Colors.white12)))), Expanded(child: Container(decoration: BoxDecoration(border: Border.all(color: Colors.white12))))])),
              Expanded(child: Row(children: [Expanded(child: Container(decoration: BoxDecoration(border: Border.all(color: Colors.white12)))), Expanded(child: Container(decoration: BoxDecoration(border: Border.all(color: Colors.white12))))])),
            ],
          ),
        ),
      ),
    );
  }
}
