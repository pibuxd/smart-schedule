import 'package:material_ui/material_ui.dart';

import 'theme.dart';

/// The name of the app with its mark: a sheet of squared paper with a blue header (as `Wordmark.tsx` on the website).
class Wordmark extends StatelessWidget {
  const Wordmark({super.key});

  @override
  Widget build(BuildContext context) {
    return Semantics(
      label: 'Grafikomat',
      excludeSemantics: true,
      child: const Row(
        children: [
          SizedBox(width: 28, height: 28, child: CustomPaint(painter: _MarkPainter())),
          SizedBox(width: 10),
          Text(
            'Grafikomat',
            style: TextStyle(fontSize: 18, fontWeight: FontWeight.w800, color: AppColors.ink),
          ),
        ],
      ),
    );
  }
}

class _MarkPainter extends CustomPainter {
  const _MarkPainter();

  @override
  void paint(Canvas canvas, Size size) {
    final scale = size.width / 28;
    canvas.scale(scale);
    final sheet = RRect.fromRectAndRadius(const Rect.fromLTWH(1, 1, 26, 26), const Radius.circular(6));
    canvas.drawRRect(sheet, Paint()..color = AppColors.surface);
    canvas.save();
    canvas.clipRRect(sheet);
    canvas.drawRect(const Rect.fromLTWH(1, 1, 26, 8), Paint()..color = AppColors.accent);
    canvas.restore();
    final line = Paint()
      ..color = AppColors.accent
      ..strokeWidth = 1.5
      ..style = PaintingStyle.stroke;
    canvas.drawLine(const Offset(10, 9), const Offset(10, 27), line);
    canvas.drawLine(const Offset(19, 9), const Offset(19, 27), line);
    canvas.drawLine(const Offset(1, 18), const Offset(27, 18), line);
    canvas.drawRRect(sheet, line..strokeWidth = 2);
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}
