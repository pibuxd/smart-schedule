import 'dart:math' as math;

import 'package:material_ui/material_ui.dart';

import '../../ui/theme.dart';

/// The assistant's square sign next to its messages.
class AssistantMark extends StatelessWidget {
  const AssistantMark({super.key, this.large = false});

  final bool large;

  @override
  Widget build(BuildContext context) {
    final size = large ? 56.0 : 32.0;
    return ExcludeSemantics(
      child: Container(
        width: size,
        height: size,
        decoration: BoxDecoration(color: AppColors.accent, borderRadius: BorderRadius.circular(AppRadius.md)),
        child: Icon(Icons.chat_bubble_outline, size: large ? 28 : 18, color: AppColors.accentInk),
      ),
    );
  }
}

/// One message: mine on the right in a tinted bubble, the assistant's on the left next to its sign.
class ChatMessage extends StatelessWidget {
  const ChatMessage({super.key, required this.mine, required this.child, this.at, this.label});

  final bool mine;
  final Widget child;
  final DateTime? at;
  final String? label;

  @override
  Widget build(BuildContext context) {
    final time = at?.toLocal();
    final head = Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Row(
        mainAxisAlignment: mine ? MainAxisAlignment.end : MainAxisAlignment.start,
        children: [
          Text(
            label ?? (mine ? 'Ty' : 'Asystent'),
            style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: AppColors.inkMuted),
          ),
          if (time != null) ...[
            const SizedBox(width: 8),
            Text(
              '${time.hour.toString().padLeft(2, '0')}:${time.minute.toString().padLeft(2, '0')}',
              style: const TextStyle(fontSize: 12, color: AppColors.inkMuted),
            ),
          ],
        ],
      ),
    );
    if (mine) {
      return Align(
        alignment: Alignment.centerRight,
        child: FractionallySizedBox(
          widthFactor: 0.88,
          alignment: Alignment.centerRight,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              head,
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
                decoration: const BoxDecoration(
                  color: AppColors.accentSoft,
                  borderRadius: BorderRadius.only(
                    topLeft: Radius.circular(16),
                    topRight: Radius.circular(4),
                    bottomLeft: Radius.circular(16),
                    bottomRight: Radius.circular(16),
                  ),
                ),
                child: child,
              ),
            ],
          ),
        ),
      );
    }
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const AssistantMark(),
        const SizedBox(width: 12),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [head, child]),
        ),
      ],
    );
  }
}

/// "Myślę…" with a small robot reading a book: its eyes run along a line and jump back (Piotr, 22.11.2026: every wait
/// for the assistant reads „Myślę…”).
class ChatTyping extends StatelessWidget {
  const ChatTyping({super.key, this.text = 'Myślę…'});

  final String text;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      liveRegion: true,
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 4),
        child: Row(
          children: [
            const ReadingRobot(),
            const SizedBox(width: 8),
            Text(text, style: const TextStyle(fontSize: 14, color: AppColors.inkMuted)),
          ],
        ),
      ),
    );
  }
}

class ReadingRobot extends StatefulWidget {
  const ReadingRobot({super.key});

  @override
  State<ReadingRobot> createState() => _ReadingRobotState();
}

class _ReadingRobotState extends State<ReadingRobot> with SingleTickerProviderStateMixin {
  late final AnimationController _reading = AnimationController(vsync: this, duration: const Duration(seconds: 2))
    ..repeat();

  @override
  void dispose() {
    _reading.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return ExcludeSemantics(
      child: AnimatedBuilder(
        animation: _reading,
        builder: (context, _) => CustomPaint(size: const Size.square(28), painter: _RobotPainter(_reading.value)),
      ),
    );
  }
}

/// The website's robot drawing (24 × 24): the eyes move along a line for most of the time, then jump back; the head
/// nods a little.
class _RobotPainter extends CustomPainter {
  const _RobotPainter(this.t);

  final double t;

  @override
  void paint(Canvas canvas, Size size) {
    canvas.scale(size.width / 24);
    final line = Paint()
      ..color = AppColors.accent
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.6
      ..strokeCap = StrokeCap.round
      ..strokeJoin = StrokeJoin.round;
    final fill = Paint()..color = AppColors.accent;
    final eyes = t < 0.8 ? -1.2 + 2.4 * (t / 0.8) : -1.2;
    final nod = -4 * math.pi / 180 * math.sin(t * math.pi);

    canvas.save();
    canvas.translate(12, 15);
    canvas.rotate(nod);
    canvas.translate(-12, -15);
    canvas.drawLine(const Offset(12, 2.8), const Offset(12, 5), line);
    canvas.drawRRect(RRect.fromLTRBR(5, 5, 19, 15, const Radius.circular(3)), line);
    canvas.drawCircle(Offset(9.5 + eyes, 9.5), 1.2, fill);
    canvas.drawCircle(Offset(14.5 + eyes, 9.5), 1.2, fill);
    canvas.drawLine(const Offset(10, 12.5), const Offset(14, 12.5), line);
    canvas.restore();

    final book = Path()
      ..moveTo(4, 18.5)
      ..cubicTo(6.7, 17.2, 9.3, 17.2, 12, 18.5)
      ..cubicTo(14.7, 17.2, 17.3, 17.2, 20, 18.5)
      ..lineTo(20, 22)
      ..cubicTo(17.3, 20.7, 14.7, 20.7, 12, 22)
      ..cubicTo(9.3, 20.7, 6.7, 20.7, 4, 22)
      ..close();
    canvas.drawPath(book, line);
    canvas.drawLine(const Offset(12, 18.5), const Offset(12, 22), line);
  }

  @override
  bool shouldRepaint(_RobotPainter old) => old.t != t;
}

/// The field to write in, with the send button beside it. Enter makes a new line (a request is often a few
/// sentences); the button sends. The length shows near the limit.
class ChatComposer extends StatelessWidget {
  const ChatComposer({
    super.key,
    required this.controller,
    required this.onSend,
    required this.label,
    required this.sendLabel,
    required this.placeholder,
    this.disabled = false,
    this.sending = false,
    this.footer,
  });

  final TextEditingController controller;
  final VoidCallback onSend;
  final String label;
  final String sendLabel;
  final String placeholder;
  final bool disabled;
  final bool sending;
  final String? footer;

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: controller,
      builder: (context, _) {
        final text = controller.text;
        final canSend = text.trim().isNotEmpty && !disabled && !sending;
        return Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                Expanded(
                  child: TextField(
                    controller: controller,
                    enabled: !disabled && !sending,
                    minLines: 1,
                    maxLines: 6,
                    maxLength: 1000,
                    keyboardType: TextInputType.multiline,
                    textInputAction: TextInputAction.newline,
                    textCapitalization: TextCapitalization.sentences,
                    decoration: InputDecoration(labelText: label, hintText: placeholder, counterText: ''),
                  ),
                ),
                const SizedBox(width: 8),
                FilledButton.icon(
                  onPressed: canSend ? onSend : null,
                  icon: const Icon(Icons.arrow_upward, size: 18),
                  label: Text(sending ? 'Wysyłam…' : sendLabel),
                ),
              ],
            ),
            if (footer != null || text.length > 800)
              Padding(
                padding: const EdgeInsets.fromLTRB(4, 6, 4, 0),
                child: Row(
                  children: [
                    if (footer != null)
                      Expanded(
                        child: Text(
                          sending ? 'Wysyłam…' : footer!,
                          style: const TextStyle(fontSize: 12, color: AppColors.inkMuted),
                        ),
                      )
                    else
                      const Spacer(),
                    if (text.length > 800)
                      Text('${text.length}/1000', style: const TextStyle(fontSize: 12, color: AppColors.inkMuted)),
                  ],
                ),
              ),
          ],
        );
      },
    );
  }
}
