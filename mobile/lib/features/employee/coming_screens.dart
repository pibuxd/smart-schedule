import 'package:material_ui/material_ui.dart';

import '../../ui/status.dart';
import '../../ui/theme.dart';
import 'employee_shell.dart';

/// The tabs whose screens come in the next stages of the app (docs/plan.md section 49). Each says so plainly, so a
/// tester knows the empty tab is expected.
class ComingScreen extends StatelessWidget {
  const ComingScreen({super.key, required this.title, required this.what});

  final String title;
  final String what;

  @override
  Widget build(BuildContext context) {
    return TabScreen(
      title: title,
      children: [
        EmptyView(
          title: 'Ten ekran jest jeszcze w budowie',
          children: [Text(what, style: const TextStyle(color: AppColors.inkMuted))],
        ),
      ],
    );
  }
}

class ScheduleTab extends StatelessWidget {
  const ScheduleTab({super.key});

  @override
  Widget build(BuildContext context) => const ComingScreen(
    title: 'Mój grafik',
    what: 'Tu zobaczysz swoje zmiany, oddasz zmianę i weźmiesz cudzą. Na razie sprawdzisz to na stronie Grafikomatu.',
  );
}

class AvailabilityTab extends StatelessWidget {
  const AvailabilityTab({super.key});

  @override
  Widget build(BuildContext context) => const ComingScreen(
    title: 'Kiedy mogę',
    what: 'Tu zaznaczysz, kiedy możesz pracować, i napiszesz do asystenta. Na razie zrobisz to na stronie Grafikomatu.',
  );
}

class NotificationsTab extends StatelessWidget {
  const NotificationsTab({super.key});

  @override
  Widget build(BuildContext context) => const ComingScreen(
    title: 'Powiadomienia',
    what: 'Tu zobaczysz powiadomienia o grafiku i zmianach. Na razie sprawdzisz je na stronie Grafikomatu.',
  );
}
