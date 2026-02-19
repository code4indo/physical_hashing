import 'dart:io';
import 'dart:math';
import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:image/image.dart' as img;
import 'package:image_cropper/image_cropper.dart';

/// Auto-crops document using edge detection before upload.
/// 
/// Flow:
/// 1. User takes photo
/// 2. Auto-detect document boundaries (edge detection)
/// 3. Show preview with crop overlay
/// 4. Allow manual adjustment
/// 5. Crop and return to upload
class DocumentCropperScreen extends StatefulWidget {
  final String imagePath;

  const DocumentCropperScreen({super.key, required this.imagePath});

  @override
  State<DocumentCropperScreen> createState() => _DocumentCropperScreenState();
}

class _DocumentCropperScreenState extends State<DocumentCropperScreen> {
  bool _isProcessing = true;
  String? _errorMessage;
  List<Offset>? _detectedCorners; // Auto-detected document corners
  ui.Image? _displayImage;
  int? _originalWidth;
  int? _originalHeight;
  
  @override
  void initState() {
    super.initState();
    _detectDocumentBoundaries();
  }

  Future<void> _detectDocumentBoundaries() async {
    setState(() => _isProcessing = true);

    try {
      // Load image
      final imageFile = File(widget.imagePath);
      final bytes = await imageFile.readAsBytes();
      
      // Decode image
      final decodedImage = img.decodeImage(bytes);
      if (decodedImage == null) {
        throw Exception("Failed to decode image");
      }

      _originalWidth = decodedImage.width;
      _originalHeight = decodedImage.height;

      // 1. DOWNSCALE High-Res images for processing speed
      // Processing 12MP images in Dart is too slow. Resize to ~600px safely.
      double scale = 1.0;
      img.Image processedImage = decodedImage;
      const maxDimension = 600;
      
      if (decodedImage.width > maxDimension || decodedImage.height > maxDimension) {
        scale = maxDimension / max(decodedImage.width, decodedImage.height);
        processedImage = img.copyResize(
          decodedImage, 
          width: (decodedImage.width * scale).toInt(),
          height: (decodedImage.height * scale).toInt()
        );
      }

      // 2. Grayscale
      final grayscale = img.grayscale(processedImage);
      
      // 3. Blur (Box blur is faster and sufficient)
      final blurred = img.gaussianBlur(grayscale, radius: 3);
      
      // 4. Edge Detection
      final edges = _detectEdges(blurred);
      
      // 5. Find Contour (Extreme Points)
      final corners = _findLargestQuadrilateral(edges);
      
      // 6. Scale corners back to original resolution
      final scaledCorners = corners?.map((point) {
        return Offset(point.dx / scale, point.dy / scale);
      }).toList();
      
      // Load UI image for display
      final codec = await ui.instantiateImageCodec(bytes);
      final frame = await codec.getNextFrame();
      
      if (mounted) {
        setState(() {
          _detectedCorners = scaledCorners;
          _displayImage = frame.image;
          _isProcessing = false;
        });
      }

    } catch (e) {
      print("Error detecting boundaries: $e");
      if (mounted) {
        setState(() {
          _errorMessage = "Auto-detection failed: $e";
          _isProcessing = false;
        });
      }
    }
  }

  /// Simple and efficient edge detection
  img.Image _detectEdges(img.Image grayscale) {
    final width = grayscale.width;
    final height = grayscale.height;
    final edges = img.Image(width: width, height: height);
    
    // Sobel Kernels
    // We use a simplified calculation for performance:
    // |G| ~= |Gx| + |Gy|
    
    for (int y = 1; y < height - 1; y++) {
      for (int x = 1; x < width - 1; x++) {
        // Neighbors
        // p1 p2 p3
        // p4 p5 p6
        // p7 p8 p9
        
        final p1 = grayscale.getPixel(x - 1, y - 1).r;
        final p2 = grayscale.getPixel(x, y - 1).r;
        final p3 = grayscale.getPixel(x + 1, y - 1).r;
        final p4 = grayscale.getPixel(x - 1, y).r;
        final p6 = grayscale.getPixel(x + 1, y).r;
        final p7 = grayscale.getPixel(x - 1, y + 1).r;
        final p8 = grayscale.getPixel(x, y + 1).r;
        final p9 = grayscale.getPixel(x + 1, y + 1).r;

        // Sobel X
        // -1 0 1
        // -2 0 2
        // -1 0 1
        final gx = (p3 + 2*p6 + p9) - (p1 + 2*p4 + p7);
        
        // Sobel Y
        // -1 -2 -1
        //  0  0  0
        //  1  2  1
        final gy = (p7 + 2*p8 + p9) - (p1 + 2*p2 + p3);
        
        final magnitude = (gx.abs() + gy.abs()).clamp(0, 255).toInt();
        
        // Thresholding to make it binary-ish for the point finder
        final val = magnitude > 50 ? 255 : 0;
        
        edges.setPixel(x, y, img.ColorRgb8(val, val, val));
      }
    }
    
    return edges;
  }

  /// Find largest quadrilateral using "Extreme Points" method.
  /// Works best for documents which are roughly convex and corner-oriented.
  List<Offset>? _findLargestQuadrilateral(img.Image edges) {
    double? minSum, maxSum, minDiff, maxDiff;
    Offset? tl, tr, bl, br;

    final width = edges.width;
    final height = edges.height;
    
    // Scan inner area to avoid image boundary noise
    final margin = 5; 
    
    // We iterate pixels to find extremes
    for (int y = margin; y < height - margin; y++) {
      for (int x = margin; x < width - margin; x++) {
        final pixel = edges.getPixel(x, y);
        
        if (pixel.r > 128) { // If edge pixel
          final sum = (x + y).toDouble();
          final diff = (x - y).toDouble();

          // Top-Left: Min(x + y)
          if (minSum == null || sum < minSum) {
            minSum = sum;
            tl = Offset(x.toDouble(), y.toDouble());
          }
          // Bottom-Right: Max(x + y)
          if (maxSum == null || sum > maxSum) {
            maxSum = sum;
            br = Offset(x.toDouble(), y.toDouble());
          }
          // Top-Right: Max(x - y)  (large x, small y)
          if (maxDiff == null || diff > maxDiff) {
            maxDiff = diff;
            tr = Offset(x.toDouble(), y.toDouble());
          }
          // Bottom-Left: Min(x - y) (small x, large y)
          if (minDiff == null || diff < minDiff) {
            minDiff = diff;
            bl = Offset(x.toDouble(), y.toDouble());
          }
        }
      }
    }

    if (tl != null && tr != null && bl != null && br != null) {
      // Check if points are distinct enough to form a quad?
      // For now, return them. 
      final p1 = tl!;
      final p2 = tr!;
      final p3 = br!;
      final p4 = bl!;

      // Calculate approximate dimensions
      final topW = sqrt(pow(p2.dx - p1.dx, 2) + pow(p2.dy - p1.dy, 2));
      final botW = sqrt(pow(p3.dx - p4.dx, 2) + pow(p3.dy - p4.dy, 2));
      final leftH = sqrt(pow(p4.dx - p1.dx, 2) + pow(p4.dy - p1.dy, 2));
      final rightH = sqrt(pow(p3.dx - p2.dx, 2) + pow(p3.dy - p2.dy, 2));
      
      final avgW = (topW + botW) / 2;
      final avgH = (leftH + rightH) / 2;
      
      // 1. Minimum Area Filter (must be > 10% of image area)
      final docArea = avgW * avgH;
      final imgArea = width * height;
      if (docArea < imgArea * 0.1) {
        print("Ignored detection: Too small (${(docArea/imgArea*100).toStringAsFixed(1)}%)");
        // Fallthrough to fallback
      } else {
         // 2. Aspect Ratio Filter
         // Standard docs (A4, Letter, Legal) are between 1.0 and 1.8
         // Keyboards/Monitor strips are usually > 2.5
         final ratio = max(avgW, avgH) / min(avgW, avgH); // Always >= 1.0
         
         if (ratio > 2.5) {
            print("Ignored detection: Too wide/thin (Ratio: ${ratio.toStringAsFixed(2)})");
         } else {
            // Valid document candidate
            return [p1, p2, p3, p4];
         }
      }
    }

    // Fallback: Return 10% margin rect if detection fails
    final w = width.toDouble();
    final h = height.toDouble();
    final m = 0.1;
    return [
      Offset(w * m, h * m),
      Offset(w * (1 - m), h * m),
      Offset(w * (1 - m), h * (1 - m)),
      Offset(w * m, h * (1 - m)),
    ];
  }

  /// Convert image-space corners to screen-space for overlay rendering.
  List<Offset> _cornersToScreen(List<Offset> corners, Size screenSize) {
    if (_originalWidth == null || _originalHeight == null) return [];
    
    final imgW = _originalWidth!.toDouble();
    final imgH = _originalHeight!.toDouble();
    
    // Fit logic (contain) matches the RawImage display
    final scaleX = screenSize.width / imgW;
    final scaleY = screenSize.height / imgH;
    final scale = min(scaleX, scaleY); 
    
    final renderedW = imgW * scale;
    final renderedH = imgH * scale;
    
    final offsetX = (screenSize.width - renderedW) / 2.0;
    final offsetY = (screenSize.height - renderedH) / 2.0;
    
    return corners
        .map((c) => Offset(offsetX + c.dx * scale, offsetY + c.dy * scale))
        .toList();
  }

  Future<void> _cropAndContinue() async {
    if (_detectedCorners == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text("No document detected. Using original image."))
      );
      Navigator.pop(context, widget.imagePath);
      return;
    }

    // Use image_cropper for manual adjustment
    try {
      final croppedFile = await ImageCropper().cropImage(
        sourcePath: widget.imagePath,
        compressFormat: ImageCompressFormat.jpg,
        compressQuality: 95,
        uiSettings: [
          AndroidUiSettings(
            toolbarTitle: 'Adjust Document Crop',
            toolbarColor: Colors.black,
            toolbarWidgetColor: const Color(0xFFD4AF37),
            initAspectRatio: CropAspectRatioPreset.original,
            lockAspectRatio: false,
            aspectRatioPresets: [
              CropAspectRatioPreset.original,
              CropAspectRatioPreset.square,
              CropAspectRatioPreset.ratio4x3,
            ],
          ),
          IOSUiSettings(
            title: 'Adjust Document Crop',
            aspectRatioPresets: [
              CropAspectRatioPreset.original,
              CropAspectRatioPreset.square,
              CropAspectRatioPreset.ratio4x3,
            ],
          ),
        ],
      );

      if (croppedFile != null && mounted) {
        Navigator.pop(context, croppedFile.path);
      } else {
        // User cancelled, use original
        Navigator.pop(context, widget.imagePath);
      }
    } catch (e) {
      print("❌ ImageCropper error: $e");
      if (mounted) {
        Navigator.pop(context, widget.imagePath);
      }
    }
  }

  void _skipCrop() {
    Navigator.pop(context, widget.imagePath);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.black,
      appBar: AppBar(
        backgroundColor: Colors.black,
        elevation: 0,
        leading: IconButton(
          icon: const Icon(Icons.arrow_back, color: Colors.white),
          onPressed: () => Navigator.pop(context),
        ),
        title: Text(
          "Auto-Crop Document",
          style: GoogleFonts.outfit(color: Colors.white, fontWeight: FontWeight.bold),
        ),
        centerTitle: true,
      ),
      body: _isProcessing
          ? const Center(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  CircularProgressIndicator(color: Color(0xFFD4AF37)),
                  SizedBox(height: 16),
                  Text(
                    "Detecting document boundaries...",
                    style: TextStyle(color: Colors.white70),
                  ),
                ],
              ),
            )
          : _errorMessage != null
              ? Center(
                  child: Padding(
                    padding: const EdgeInsets.all(20),
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        const Icon(Icons.error_outline, color: Colors.red, size: 60),
                        const SizedBox(height: 16),
                        Text(
                          _errorMessage!,
                          style: const TextStyle(color: Colors.white70),
                          textAlign: TextAlign.center,
                        ),
                        const SizedBox(height: 24),
                        ElevatedButton(
                          onPressed: _skipCrop,
                          style: ElevatedButton.styleFrom(
                            backgroundColor: const Color(0xFFD4AF37),
                          ),
                          child: const Text("Continue with Original"),
                        ),
                      ],
                    ),
                  ),
                )
              : Column(
                  children: [
                    // Preview with overlay
                    Expanded(
                      child: LayoutBuilder(
                        builder: (context, constraints) {
                          final screenSize = Size(
                            constraints.maxWidth,
                            constraints.maxHeight,
                          );
                          final screenCorners =
                              (_detectedCorners != null &&
                                      _originalWidth != null &&
                                      _originalHeight != null)
                                  ? _cornersToScreen(_detectedCorners!, screenSize)
                                  : null;

                          return Stack(
                            children: [
                              // Image
                              if (_displayImage != null)
                                Center(
                                  child: RawImage(
                                    image: _displayImage,
                                    fit: BoxFit.contain,
                                  ),
                                ),

                              // Crop overlay
                              if (screenCorners != null)
                                CustomPaint(
                                  painter: _CropOverlayPainter(screenCorners),
                                  child: Container(),
                                ),
                            ],
                          );
                        },
                      ),
                    ),
                    
                    // Controls
                    Container(
                      padding: const EdgeInsets.all(20),
                      decoration: const BoxDecoration(
                        color: Colors.black87,
                        border: Border(top: BorderSide(color: Colors.white24)),
                      ),
                      child: SafeArea(
                        top: false,
                        child: Column(
                          children: [
                            // Info
                            Text(
                              _detectedCorners != null
                                  ? "✓ Document detected. Tap 'Crop' to adjust."
                                  : "No document detected. Use original?",
                              style: GoogleFonts.outfit(
                                color: const Color(0xFFD4AF37),
                                fontSize: 14,
                              ),
                              textAlign: TextAlign.center,
                            ),
                            const SizedBox(height: 16),
                            
                            // Buttons
                            Row(
                              children: [
                                Expanded(
                                  child: OutlinedButton.icon(
                                    onPressed: _skipCrop,
                                    icon: const Icon(Icons.close, color: Colors.white70),
                                    label: const Text("Skip", style: TextStyle(color: Colors.white70)),
                                    style: OutlinedButton.styleFrom(
                                      side: const BorderSide(color: Colors.white24),
                                      padding: const EdgeInsets.symmetric(vertical: 14),
                                    ),
                                  ),
                                ),
                                const SizedBox(width: 12),
                                Expanded(
                                  flex: 2,
                                  child: ElevatedButton.icon(
                                    onPressed: _cropAndContinue,
                                    icon: const Icon(Icons.crop, color: Colors.black),
                                    label: const Text("Crop & Continue", style: TextStyle(color: Colors.black)),
                                    style: ElevatedButton.styleFrom(
                                      backgroundColor: const Color(0xFFD4AF37),
                                      padding: const EdgeInsets.symmetric(vertical: 14),
                                    ),
                                  ),
                                ),
                              ],
                            ),
                          ],
                        ),
                      ),
                    ),
                  ],
                ),
    );
  }
}

/// Draws crop overlay on detected document corners
class _CropOverlayPainter extends CustomPainter {
  final List<Offset> corners;

  _CropOverlayPainter(this.corners);

  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = const Color(0xFFD4AF37)
      ..strokeWidth = 3
      ..style = PaintingStyle.stroke;

    final path = Path()
      ..moveTo(corners[0].dx, corners[0].dy)
      ..lineTo(corners[1].dx, corners[1].dy)
      ..lineTo(corners[2].dx, corners[2].dy)
      ..lineTo(corners[3].dx, corners[3].dy)
      ..close();

    canvas.drawPath(path, paint);

    // Draw corner handles
    final handlePaint = Paint()
      ..color = const Color(0xFFD4AF37)
      ..style = PaintingStyle.fill;

    for (final corner in corners) {
      canvas.drawCircle(corner, 8, handlePaint);
    }
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => true;
}
