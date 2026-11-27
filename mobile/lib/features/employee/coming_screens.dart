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

class NotificationsTab extends StatelessWidget {
  const NotificationsTab({super.key});

  @override
  Widget build(BuildContext context) => const ComingScreen(
    title: 'Powiadomienia',
    what: 'Tu zobaczysz powiadomienia o grafiku i zmianach. Na razie sprawdzisz je na stronie Grafikomatu.',
  );
}
