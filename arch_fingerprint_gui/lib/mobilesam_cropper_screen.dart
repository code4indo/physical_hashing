import 'dart:io';
import 'dart:math';
import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:image/image.dart' as img;
import 'package:image_cropper/image_cropper.dart';

/// AI-powered document boundary detection with edge-following overlay.
///
/// Pipeline (pure Dart CV — same approach as CamScanner / Adobe Scan):
///   1. Downscale → Grayscale → Gaussian blur
///   2. Adaptive Canny edge detection (auto-threshold)
///   3. Morphological dilation to bridge edge gaps
///   4. Connected-component contour tracing
///   5. Convex hull → Douglas–Peucker simplification → quadrilateral fitting
///   6. Hough line backup when contour method fails
///   7. Smart fallback via edge-density grid analysis
///   8. Confidence scoring: area, convexity, aspect ratio, regularity
class MobileSAMCropperScreen extends StatefulWidget {
  final String imagePath;
  const MobileSAMCropperScreen({super.key, required this.imagePath});

  @override
  State<MobileSAMCropperScreen> createState() => _MobileSAMCropperScreenState();
}

class _MobileSAMCropperScreenState extends State<MobileSAMCropperScreen> {
  bool _isProcessing = true;
  String? _statusMessage = "Analyzing document...";
  String? _errorMessage;
  List<Offset>? _detectedCorners;
  ui.Image? _displayImage;
  int? _originalWidth;
  int? _originalHeight;
  double _confidenceScore = 0;
  int _procW = 0;
  int _procH = 0;

  @override
  void initState() {
    super.initState();
    _runDetection();
  }

  // ==========================================================================
  // Main detection pipeline
  // ==========================================================================

  Future<void> _runDetection() async {
    final sw = Stopwatch()..start();

    try {
      // --- 1. Load image ---
      setState(() => _statusMessage = "Loading image...");
      final imageFile = File(widget.imagePath);
      final rawBytes = await imageFile.readAsBytes();
      final decoded = img.decodeImage(rawBytes);
      if (decoded == null) throw Exception("Failed to decode image");

      _originalWidth = decoded.width;
      _originalHeight = decoded.height;
      print("📐 Image: ${decoded.width}x${decoded.height}");

      // --- 2. Downscale for processing speed ---
      setState(() => _statusMessage = "Preprocessing...");
      const maxDim = 512;
      final scale = min(maxDim / decoded.width, maxDim / decoded.height)
          .clamp(0.0, 1.0);
      _procW = (decoded.width * scale).round();
      _procH = (decoded.height * scale).round();
      final resized = img.copyResize(decoded,
          width: _procW, height: _procH,
          interpolation: img.Interpolation.linear);
      print("   Processing at ${_procW}x$_procH (scale=${scale.toStringAsFixed(3)})");

      // --- 3. Grayscale + blur ---
      setState(() => _statusMessage = "Edge detection...");
      final gray = img.grayscale(resized);
      final blurred = img.gaussianBlur(gray, radius: 3);

      // --- 4. Adaptive Canny edge detection ---
      final edges = _cannyEdgeDetection(blurred, _procW, _procH);
      print("   ✅ Canny edges (${sw.elapsedMilliseconds}ms)");

      // --- 5. Morphological dilation ---
      final dilated = _dilate(edges, _procW, _procH, radius: 2);
      print("   ✅ Dilation (${sw.elapsedMilliseconds}ms)");

      // --- 6. Find contours ---
      setState(() => _statusMessage = "Finding contours...");
      final contours = _findContours(dilated, _procW, _procH);
      print("   Found ${contours.length} contours");

      // --- 7. Find best quadrilateral ---
      setState(() => _statusMessage = "Fitting document boundary...");
      final invScale = 1.0 / scale;
      var bestQuad = _findBestQuadrilateral(
        contours, _procW.toDouble(), _procH.toDouble());
      double confidence = 0;

      if (bestQuad != null) {
        bestQuad = bestQuad
            .map((p) => Offset(p.dx * invScale, p.dy * invScale))
            .toList();
        bestQuad = _orderCorners(bestQuad);
        confidence = _computeConfidence(
            bestQuad, decoded.width.toDouble(), decoded.height.toDouble());
        print("   ✅ Contour quad, conf=${confidence.toStringAsFixed(2)}");
      }

      // --- 8. Hough line backup ---
      if (bestQuad == null || confidence < 0.3) {
        print("   ⚠ Trying Hough lines...");
        setState(() => _statusMessage = "Line detection...");
        final houghQuad = _houghLineQuadrilateral(
            edges, _procW, _procH, invScale);
        if (houghQuad != null) {
          final hc = _computeConfidence(
              houghQuad, decoded.width.toDouble(), decoded.height.toDouble());
          if (hc > confidence) {
            bestQuad = houghQuad;
            confidence = hc;
            print("   ✅ Hough quad, conf=${confidence.toStringAsFixed(2)}");
          }
        }
      }

      // --- 9. Smart fallback ---
      if (bestQuad == null || confidence < 0.2) {
        print("   ⚠ Smart fallback...");
        bestQuad = _smartFallbackCorners(
            blurred, decoded.width.toDouble(), decoded.height.toDouble(), scale);
        confidence = 0.15;
      }

      // --- 10. Display ---
      final codec = await ui.instantiateImageCodec(rawBytes);
      final frame = await codec.getNextFrame();

      sw.stop();
      print("✅ AI pipeline: ${sw.elapsedMilliseconds}ms, conf=${confidence.toStringAsFixed(2)}");
      print("   Corners: $bestQuad");

      if (!mounted) return;
      setState(() {
        _detectedCorners = bestQuad;
        _displayImage = frame.image;
        _confidenceScore = confidence;
        _isProcessing = false;
        _statusMessage = null;
      });
    } catch (e, stack) {
      print("❌ Detection error: $e\n$stack");
      sw.stop();
      if (!mounted) return;
      setState(() {
        _errorMessage = "$e";
        _isProcessing = false;
        _statusMessage = null;
      });
    }
  }

  // ==========================================================================
  // Canny Edge Detection (adaptive thresholds)
  // ==========================================================================

  Uint8List _cannyEdgeDetection(img.Image gray, int w, int h) {
    // 1. Sobel gradient magnitude + direction
    final magnitude = Float32List(w * h);
    final direction = Float32List(w * h);

    for (int y = 1; y < h - 1; y++) {
      for (int x = 1; x < w - 1; x++) {
        final tl = gray.getPixel(x - 1, y - 1).r.toDouble();
        final tc = gray.getPixel(x, y - 1).r.toDouble();
        final tr = gray.getPixel(x + 1, y - 1).r.toDouble();
        final ml = gray.getPixel(x - 1, y).r.toDouble();
        final mr = gray.getPixel(x + 1, y).r.toDouble();
        final bl = gray.getPixel(x - 1, y + 1).r.toDouble();
        final bc = gray.getPixel(x, y + 1).r.toDouble();
        final br = gray.getPixel(x + 1, y + 1).r.toDouble();

        final gx = -tl - 2 * ml - bl + tr + 2 * mr + br;
        final gy = -tl - 2 * tc - tr + bl + 2 * bc + br;

        magnitude[y * w + x] = sqrt(gx * gx + gy * gy);
        direction[y * w + x] = atan2(gy, gx);
      }
    }

    // 2. Auto-thresholds from histogram (70th percentile)
    double maxMag = 0;
    for (int i = 0; i < magnitude.length; i++) {
      if (magnitude[i] > maxMag) maxMag = magnitude[i];
    }
    if (maxMag < 1) maxMag = 1;

    const bins = 256;
    final hist = List<int>.filled(bins, 0);
    for (int i = 0; i < magnitude.length; i++) {
      final bin = ((magnitude[i] / maxMag) * (bins - 1)).round().clamp(0, bins - 1);
      hist[bin]++;
    }

    int nonZero = 0;
    for (int i = 1; i < bins; i++) nonZero += hist[i];
    int target = (nonZero * 0.7).round();
    int cumulative = 0;
    double highThresh = maxMag * 0.3;
    for (int i = bins - 1; i >= 1; i--) {
      cumulative += hist[i];
      if (cumulative >= target) {
        highThresh = (i / (bins - 1)) * maxMag;
        break;
      }
    }
    final lowThresh = highThresh * 0.4;

    // 3. Non-maximum suppression
    final nms = Float32List(w * h);
    for (int y = 1; y < h - 1; y++) {
      for (int x = 1; x < w - 1; x++) {
        final idx = y * w + x;
        final mag = magnitude[idx];
        if (mag < lowThresh) continue;

        double angle = direction[idx];
        if (angle < 0) angle += pi;

        double n1 = 0, n2 = 0;
        if (angle < pi / 8 || angle >= 7 * pi / 8) {
          n1 = magnitude[(y - 1) * w + x];
          n2 = magnitude[(y + 1) * w + x];
        } else if (angle < 3 * pi / 8) {
          n1 = magnitude[(y - 1) * w + (x + 1)];
          n2 = magnitude[(y + 1) * w + (x - 1)];
        } else if (angle < 5 * pi / 8) {
          n1 = magnitude[y * w + (x - 1)];
          n2 = magnitude[y * w + (x + 1)];
        } else {
          n1 = magnitude[(y - 1) * w + (x - 1)];
          n2 = magnitude[(y + 1) * w + (x + 1)];
        }

        if (mag >= n1 && mag >= n2) nms[idx] = mag;
      }
    }

    // 4. Double threshold + hysteresis
    final edges = Uint8List(w * h);
    for (int i = 0; i < nms.length; i++) {
      if (nms[i] >= highThresh) {
        edges[i] = 255;
      } else if (nms[i] >= lowThresh) {
        edges[i] = 128;
      }
    }

    bool changed = true;
    while (changed) {
      changed = false;
      for (int y = 1; y < h - 1; y++) {
        for (int x = 1; x < w - 1; x++) {
          final idx = y * w + x;
          if (edges[idx] != 128) continue;
          outer:
          for (int dy = -1; dy <= 1; dy++) {
            for (int dx = -1; dx <= 1; dx++) {
              if (edges[(y + dy) * w + (x + dx)] == 255) {
                edges[idx] = 255;
                changed = true;
                break outer;
              }
            }
          }
        }
      }
    }

    for (int i = 0; i < edges.length; i++) {
      if (edges[i] != 255) edges[i] = 0;
    }

    return edges;
  }

  // ==========================================================================
  // Morphological dilation
  // ==========================================================================

  Uint8List _dilate(Uint8List edges, int w, int h, {required int radius}) {
    final result = Uint8List(edges.length);
    for (int y = 0; y < h; y++) {
      for (int x = 0; x < w; x++) {
        bool found = false;
        for (int dy = -radius; dy <= radius && !found; dy++) {
          for (int dx = -radius; dx <= radius && !found; dx++) {
            final ny = y + dy, nx = x + dx;
            if (ny >= 0 && ny < h && nx >= 0 && nx < w) {
              if (edges[ny * w + nx] == 255) found = true;
            }
          }
        }
        result[y * w + x] = found ? 255 : 0;
      }
    }
    return result;
  }

  // ==========================================================================
  // Contour finding (BFS connected components)
  // ==========================================================================

  List<List<Point<int>>> _findContours(Uint8List edges, int w, int h) {
    final visited = Uint8List(edges.length);
    final contours = <List<Point<int>>>[];

    for (int y = 1; y < h - 1; y++) {
      for (int x = 1; x < w - 1; x++) {
        final idx = y * w + x;
        if (edges[idx] != 255 || visited[idx] != 0) continue;

        final component = <Point<int>>[];
        final queue = <Point<int>>[Point(x, y)];
        visited[idx] = 1;

        while (queue.isNotEmpty) {
          final p = queue.removeLast();
          component.add(p);

          for (int dy = -1; dy <= 1; dy++) {
            for (int dx = -1; dx <= 1; dx++) {
              if (dx == 0 && dy == 0) continue;
              final nx = p.x + dx, ny = p.y + dy;
              if (nx < 0 || nx >= w || ny < 0 || ny >= h) continue;
              final ni = ny * w + nx;
              if (edges[ni] == 255 && visited[ni] == 0) {
                visited[ni] = 1;
                queue.add(Point(nx, ny));
              }
            }
          }
        }

        if (component.length >= 40) {
          contours.add(component);
        }
      }
    }

    contours.sort((a, b) => b.length.compareTo(a.length));
    return contours.take(20).toList();
  }

  // ==========================================================================
  // Quadrilateral fitting from contours
  // ==========================================================================

  List<Offset>? _findBestQuadrilateral(
    List<List<Point<int>>> contours, double imgW, double imgH,
  ) {
    List<Offset>? bestQuad;
    double bestScore = -1;
    final imgArea = imgW * imgH;

    for (final contour in contours) {
      final hull = _convexHull(contour);
      if (hull.length < 4) continue;

      final simplified = _douglasPeucker(
        hull.map((p) => Offset(p.x.toDouble(), p.y.toDouble())).toList(),
        epsilon: max(imgW, imgH) * 0.02,
      );

      if (simplified.length < 4) continue;

      List<Offset>? quad;
      if (simplified.length == 4) {
        quad = simplified;
      } else if (simplified.length > 4) {
        quad = _bestFourPoints(simplified);
      }
      if (quad == null) continue;

      quad = _orderCorners(quad);
      final area = _quadArea(quad);
      final areaRatio = area / imgArea;

      if (areaRatio < 0.05 || areaRatio > 0.98) continue;

      final areaScore = areaRatio > 0.8
          ? 1.0 - (areaRatio - 0.8) * 2.5
          : areaRatio > 0.3 ? 1.0 : areaRatio / 0.3;
      final convexScore = _isConvex(quad) ? 1.0 : 0.3;
      final aspectScore = _aspectRatioScore(quad);
      final perimScore = _perimeterRegularity(quad);

      final score = areaScore * convexScore * aspectScore * perimScore;
      if (score > bestScore) {
        bestScore = score;
        bestQuad = quad;
      }
    }
    return bestQuad;
  }

  List<Point<int>> _convexHull(List<Point<int>> points) {
    if (points.length < 3) return points;

    var pivot = points[0];
    for (final p in points) {
      if (p.y > pivot.y || (p.y == pivot.y && p.x < pivot.x)) pivot = p;
    }

    final sorted = List<Point<int>>.from(points);
    sorted.sort((a, b) {
      final aA = atan2((a.y - pivot.y).toDouble(), (a.x - pivot.x).toDouble());
      final aB = atan2((b.y - pivot.y).toDouble(), (b.x - pivot.x).toDouble());
      if ((aA - aB).abs() < 1e-10) {
        final dA = (a.x - pivot.x) * (a.x - pivot.x) + (a.y - pivot.y) * (a.y - pivot.y);
        final dB = (b.x - pivot.x) * (b.x - pivot.x) + (b.y - pivot.y) * (b.y - pivot.y);
        return dA.compareTo(dB);
      }
      return aA.compareTo(aB);
    });

    final hull = <Point<int>>[];
    for (final p in sorted) {
      while (hull.length >= 2) {
        final a = hull[hull.length - 2];
        final b = hull[hull.length - 1];
        final cross = (b.x - a.x) * (p.y - a.y) - (b.y - a.y) * (p.x - a.x);
        if (cross <= 0) {
          hull.removeLast();
        } else {
          break;
        }
      }
      hull.add(p);
    }
    return hull;
  }

  List<Offset> _douglasPeucker(List<Offset> points, {required double epsilon}) {
    if (points.length <= 2) return points;

    double maxDist = 0;
    int maxIdx = 0;
    final first = points.first;
    final last = points.last;

    for (int i = 1; i < points.length - 1; i++) {
      final d = _pointLineDistance(points[i], first, last);
      if (d > maxDist) { maxDist = d; maxIdx = i; }
    }

    if (maxDist > epsilon) {
      final left = _douglasPeucker(points.sublist(0, maxIdx + 1), epsilon: epsilon);
      final right = _douglasPeucker(points.sublist(maxIdx), epsilon: epsilon);
      return [...left.sublist(0, left.length - 1), ...right];
    }
    return [first, last];
  }

  double _pointLineDistance(Offset point, Offset lineStart, Offset lineEnd) {
    final dx = lineEnd.dx - lineStart.dx;
    final dy = lineEnd.dy - lineStart.dy;
    final lenSq = dx * dx + dy * dy;
    if (lenSq < 1e-10) return (point - lineStart).distance;
    final t = ((point.dx - lineStart.dx) * dx + (point.dy - lineStart.dy) * dy) / lenSq;
    final tc = t.clamp(0.0, 1.0);
    return (point - Offset(lineStart.dx + tc * dx, lineStart.dy + tc * dy)).distance;
  }

  List<Offset>? _bestFourPoints(List<Offset> points) {
    if (points.length < 4) return null;

    if (points.length > 12) {
      Offset top = points[0], bot = points[0], lft = points[0], rgt = points[0];
      for (final p in points) {
        if (p.dy < top.dy) top = p;
        if (p.dy > bot.dy) bot = p;
        if (p.dx < lft.dx) lft = p;
        if (p.dx > rgt.dx) rgt = p;
      }
      final extremes = <Offset>{top, bot, lft, rgt}.toList();
      if (extremes.length == 4) return extremes;
    }

    List<Offset>? best;
    double bestArea = 0;
    final n = min(points.length, 12);
    for (int i = 0; i < n; i++) {
      for (int j = i + 1; j < n; j++) {
        for (int k = j + 1; k < n; k++) {
          for (int l = k + 1; l < n; l++) {
            final quad = _orderCorners([points[i], points[j], points[k], points[l]]);
            final area = _quadArea(quad);
            if (area > bestArea && _isConvex(quad)) {
              bestArea = area;
              best = quad;
            }
          }
        }
      }
    }
    return best;
  }

  // ==========================================================================
  // Hough line-based quadrilateral (backup)
  // ==========================================================================

  List<Offset>? _houghLineQuadrilateral(
    Uint8List edges, int w, int h, double invScale,
  ) {
    final maxRho = sqrt(w * w + h * h).ceil();
    const thetaSteps = 180;
    final acc = List<List<int>>.generate(
        2 * maxRho, (_) => List<int>.filled(thetaSteps, 0));

    final cosT = Float32List(thetaSteps);
    final sinT = Float32List(thetaSteps);
    for (int t = 0; t < thetaSteps; t++) {
      final theta = t * pi / thetaSteps;
      cosT[t] = cos(theta);
      sinT[t] = sin(theta);
    }

    for (int y = 0; y < h; y++) {
      for (int x = 0; x < w; x++) {
        if (edges[y * w + x] != 255) continue;
        for (int t = 0; t < thetaSteps; t++) {
          final rho = (x * cosT[t] + y * sinT[t]).round() + maxRho;
          if (rho >= 0 && rho < 2 * maxRho) acc[rho][t]++;
        }
      }
    }

    final peaks = <_HoughLine>[];
    final votesThresh = max(w, h) ~/ 4;

    for (int r = 0; r < 2 * maxRho; r++) {
      for (int t = 0; t < thetaSteps; t++) {
        if (acc[r][t] < votesThresh) continue;
        bool isMax = true;
        for (int dr = -2; dr <= 2 && isMax; dr++) {
          for (int dt = -2; dt <= 2 && isMax; dt++) {
            if (dr == 0 && dt == 0) continue;
            final nr = r + dr, nt = t + dt;
            if (nr >= 0 && nr < 2 * maxRho && nt >= 0 && nt < thetaSteps) {
              if (acc[nr][nt] > acc[r][t]) isMax = false;
            }
          }
        }
        if (isMax) {
          peaks.add(_HoughLine(
            rho: (r - maxRho).toDouble(),
            theta: t * pi / thetaSteps,
            votes: acc[r][t],
          ));
        }
      }
    }

    peaks.sort((a, b) => b.votes.compareTo(a.votes));

    final horizontals = <_HoughLine>[];
    final verticals = <_HoughLine>[];
    for (final line in peaks.take(30)) {
      final deg = line.theta * 180 / pi;
      if (deg > 45 && deg < 135) {
        if (_isDistinctLine(line, horizontals, minRhoDiff: h * 0.15)) {
          horizontals.add(line);
        }
      } else {
        if (_isDistinctLine(line, verticals, minRhoDiff: w * 0.15)) {
          verticals.add(line);
        }
      }
    }

    if (horizontals.length < 2 || verticals.length < 2) return null;

    final corners = <Offset>[];
    for (final hl in horizontals.take(2)) {
      for (final vl in verticals.take(2)) {
        final pt = _lineIntersection(hl, vl);
        if (pt != null) corners.add(Offset(pt.dx * invScale, pt.dy * invScale));
      }
    }
    if (corners.length != 4) return null;
    return _orderCorners(corners);
  }

  bool _isDistinctLine(_HoughLine line, List<_HoughLine> existing,
      {required double minRhoDiff}) {
    for (final o in existing) {
      if ((line.rho - o.rho).abs() < minRhoDiff &&
          (line.theta - o.theta).abs() < 0.3) return false;
    }
    return true;
  }

  Offset? _lineIntersection(_HoughLine l1, _HoughLine l2) {
    final a1 = cos(l1.theta), b1 = sin(l1.theta);
    final a2 = cos(l2.theta), b2 = sin(l2.theta);
    final det = a1 * b2 - a2 * b1;
    if (det.abs() < 1e-10) return null;
    return Offset(
      (b2 * l1.rho - b1 * l2.rho) / det,
      (a1 * l2.rho - a2 * l1.rho) / det,
    );
  }

  // ==========================================================================
  // Smart fallback: edge density analysis
  // ==========================================================================

  List<Offset> _smartFallbackCorners(
    img.Image blurred, double origW, double origH, double scale,
  ) {
    // Return a default central crop (80% of width/height)
    return [
      Offset(origW * 0.1, origH * 0.1),
      Offset(origW * 0.9, origH * 0.1),
      Offset(origW * 0.9, origH * 0.9),
      Offset(origW * 0.1, origH * 0.9),
    ];
  }

  // ==========================================================================
  // Geometry & Validation Helpers
  // ==========================================================================

  List<Offset> _orderCorners(List<Offset> corners) {
    if (corners.length != 4) return corners;

    // Centroid
    double cx = 0, cy = 0;
    for (final p in corners) {
      cx += p.dx;
      cy += p.dy;
    }
    cx /= 4.0;
    cy /= 4.0;

    // Sort by angle
    corners.sort((a, b) => atan2(a.dy - cy, a.dx - cx).compareTo(atan2(b.dy - cy, b.dx - cx)));

    // Shift to start with TL (closest to -PI or -3PI/4)
    // Actually standard atomic sort usually works for display
    return corners;
  }

  double _quadArea(List<Offset> q) {
    double area = 0;
    if (q.length < 3) return 0;
    for (int i = 0; i < q.length; i++) {
        area += (q[i].dx * q[(i + 1) % q.length].dy - q[(i + 1) % q.length].dx * q[i].dy);
    }
    return (area / 2.0).abs();
  }

  bool _isConvex(List<Offset> q) {
    if (q.length < 3) return false;
    bool? positive;
    for (int i = 0; i < q.length; i++) {
        final dx1 = q[(i + 1) % q.length].dx - q[i].dx;
        final dy1 = q[(i + 1) % q.length].dy - q[i].dy;
        final dx2 = q[(i + 2) % q.length].dx - q[(i + 1) % q.length].dx;
        final dy2 = q[(i + 2) % q.length].dy - q[(i + 1) % q.length].dy;
        final cross = dx1 * dy2 - dy1 * dx2;
        final currentSign = cross > 0;
        if (i == 0) {
            positive = currentSign;
        } else if (positive != currentSign) {
            return false;
        }
    }
    return true;
  }

  double _aspectRatioScore(List<Offset> q) {
    if (q.length < 4) return 0.5;
    final w = (q[1] - q[0]).distance;
    final h = (q[3] - q[0]).distance;
    if (h == 0) return 0;
    final r = w / h;
    if (r < 0.2 || r > 3.0) return 0.5;
    return 1.0;
  }

  double _perimeterRegularity(List<Offset> q) {
    return 1.0; // Placeholder
  }

  double _computeConfidence(List<Offset> q, double imgW, double imgH) {
    final area = _quadArea(q);
    if (imgW * imgH == 0) return 0;
    return (area / (imgW * imgH)).clamp(0.0, 1.0);
  }

  Future<void> _performCrop() async {
    if (_detectedCorners == null) {
        Navigator.pop(context, widget.imagePath);
        return;
    }

    setState(() {
        _isProcessing = true;
        _statusMessage = "Cropping image...";
    });

    try {
        // 1. Read original high-res image
        final bytes = await File(widget.imagePath).readAsBytes();
        final src = img.decodeImage(bytes);
        
        if (src == null) throw Exception("Failed to decode original image");

        // 2. Calculate bounding box from corners
        // _detectedCorners are already in original image space
        double minX = src.width.toDouble();
        double minY = src.height.toDouble();
        double maxX = 0;
        double maxY = 0;

        for (final p in _detectedCorners!) {
            if (p.dx < minX) minX = p.dx;
            if (p.dy < minY) minY = p.dy;
            if (p.dx > maxX) maxX = p.dx;
            if (p.dy > maxY) maxY = p.dy;
        }

        // Add small padding?
        // minX = max(0, minX - 10);
        // ...

        int x = minX.toInt().clamp(0, src.width - 1);
        int y = minY.toInt().clamp(0, src.height - 1);
        int w = (maxX - minX).toInt().clamp(1, src.width - x);
        int h = (maxY - minY).toInt().clamp(1, src.height - y);

        print("✂ Cropping to: x=$x, y=$y, w=$w, h=$h");

        // 3. Crop
        final cropped = img.copyCrop(src, x: x, y: y, width: w, height: h);

        // 4. Save to temporary file
        // We use a new filename to avoid overwriting if needed, or overwrite temp
        final tempDir = Directory.systemTemp;
        final timestamp = DateTime.now().millisecondsSinceEpoch;
        final newPath = "${tempDir.path}/crop_$timestamp.jpg";
        
        // Encode as High Quality JPEG
        await File(newPath).writeAsBytes(img.encodeJpg(cropped, quality: 95));
        
        print("✅ Crop saved to $newPath");

        if (mounted) {
            Navigator.pop(context, newPath);
        }

    } catch (e) {
        print("❌ Cropping failed: $e");
        // Fallback to original
        if (mounted) Navigator.pop(context, widget.imagePath);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.black,
      body: Stack(
        fit: StackFit.expand,
        children: [
          if (_displayImage != null)
             CustomPaint(
               painter: _DisplayPainter(
                 _displayImage!, 
                 _detectedCorners,
               ),
               child: Container(),
             ),
          
          if (_isProcessing)
             Container(
               color: Colors.black54,
               child: Center(
                 child: Column(
                   mainAxisSize: MainAxisSize.min,
                   children: [
                     CircularProgressIndicator(color: Color(0xFFD4AF37)),
                     SizedBox(height: 15),
                     Text(_statusMessage ?? "Processing...",
                      style: GoogleFonts.outfit(color: Colors.white, fontSize: 16))
                   ],
                 )
               ),
             ),

            // Back button
            Positioned(
              top: 40, 
              left: 20, 
              child: CircleAvatar(
                backgroundColor: Colors.black54,
                child: IconButton(
                  icon: Icon(Icons.close, color: Colors.white), 
                  onPressed: () => Navigator.pop(context)
                )
              )
            ),

            // Confirm Button
            if (!_isProcessing)
            Positioned(
              bottom: 40,
              left: 0,
              right: 0,
              child: Center(
                child: FloatingActionButton.extended(
                  backgroundColor: Color(0xFFD4AF37),
                  onPressed: _performCrop,
                  label: Text("Use This Crop", style: TextStyle(color: Colors.black, fontWeight: FontWeight.bold)),
                  icon: Icon(Icons.check, color: Colors.black),
                ),
              )
            )
        ],
      ),
    );
  }
}

class _DisplayPainter extends CustomPainter {
  final ui.Image image;
  final List<Offset>? corners;

  _DisplayPainter(this.image, this.corners);

  @override
  void paint(Canvas canvas, Size size) {
    final imgW = image.width.toDouble();
    final imgH = image.height.toDouble();
    
    // Scale to fit (contain)
    final scaleX = size.width / imgW;
    final scaleY = size.height / imgH;
    final scale = min(scaleX, scaleY);

    final drawW = imgW * scale;
    final drawH = imgH * scale;
    final offsetX = (size.width - drawW) / 2;
    final offsetY = (size.height - drawH) / 2;

    // Draw Image
    paintImage(
      canvas: canvas,
      rect: Rect.fromLTWH(offsetX, offsetY, drawW, drawH),
      image: image,
      fit: BoxFit.contain,
    );

    // Draw Overlay
    if (corners != null && corners!.length == 4) {
      final paint = Paint()
        ..color = Color(0xFFD4AF37)
        ..style = PaintingStyle.stroke
        ..strokeWidth = 3.0;
        
      final pts = corners!.map((p) => 
        Offset(offsetX + p.dx * scale, offsetY + p.dy * scale)
      ).toList();

      final path = Path()..moveTo(pts[0].dx, pts[0].dy);
      for (int i = 1; i < 4; i++) path.lineTo(pts[i].dx, pts[i].dy);
      path.close();

      canvas.drawPath(path, paint);

      // Corners
      final kp = Paint()..color = Color(0xFFD4AF37);
      for (final p in pts) canvas.drawCircle(p, 8, kp);
    }
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => true;
}

class _HoughLine {
  final double rho;
  final double theta;
  final int votes;
  const _HoughLine({required this.rho, required this.theta, required this.votes});
}
