import 'package:flutter/services.dart';
import 'package:material_ui/material_ui.dart';

import '../../shared/phone.dart';
import '../../ui/theme.dart';

/// A phone number with its country in front: "+48" unless someone picks another one from the list (a sheet from the
/// bottom). A number typed with "+" is taken as it is, whatever country is picked (`phoneToSend`).
class PhoneInput extends StatelessWidget {
  const PhoneInput({
    super.key,
    required this.region,
    required this.onRegionChanged,
    required this.controller,
    this.focusNode,
    this.error,
    this.enabled = true,
    this.onSubmitted,
  });

  final String region;
  final ValueChanged<String> onRegionChanged;
  final TextEditingController controller;
  final FocusNode? focusNode;
  final String? error;
  final bool enabled;
  final VoidCallback? onSubmitted;

  @override
  Widget build(BuildContext context) {
    final country = phoneCountry(region);
    final border = error != null ? AppColors.cannot : AppColors.ink;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Container(
          constraints: const BoxConstraints(minHeight: touchMain),
          decoration: BoxDecoration(
            color: AppColors.surface,
            border: Border.all(color: border, width: 2),
            borderRadius: BorderRadius.circular(AppRadius.md),
          ),
          clipBehavior: Clip.antiAlias,
          child: IntrinsicHeight(
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Semantics(
                  button: true,
                  label: 'Kraj numeru: ${country?.name ?? 'inny kraj'}',
                  excludeSemantics: true,
                  child: InkWell(
                    onTap: enabled ? () => _pickCountry(context) : null,
                    child: Container(
                      color: AppColors.grid,
                      padding: const EdgeInsets.symmetric(horizontal: 12),
                      child: Row(
                        children: [
                          Text(
                            country != null ? '+${country.code}' : 'Inny',
                            style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
                          ),
                          const Icon(Icons.expand_more, size: 20),
                        ],
                      ),
                    ),
                  ),
                ),
                Expanded(
                  child: TextField(
                    controller: controller,
                    focusNode: focusNode,
                    enabled: enabled,
                    keyboardType: TextInputType.phone,
                    textInputAction: TextInputAction.send,
                    autofillHints: const [AutofillHints.telephoneNumber],
                    inputFormatters: [FilteringTextInputFormatter.allow(RegExp(r'[\d\s+\-./()]'))],
                    onSubmitted: (_) => onSubmitted?.call(),
                    style: const TextStyle(fontSize: 18, letterSpacing: 0.5),
                    decoration: InputDecoration(
                      hintText: country?.example ?? '+ kierunkowy i numer',
                      border: InputBorder.none,
                      enabledBorder: InputBorder.none,
                      focusedBorder: InputBorder.none,
                      filled: false,
                      contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
                      semanticCounterText: '',
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
        if (error != null) ...[
          const SizedBox(height: 6),
          Text(error!, style: const TextStyle(fontSize: 14, color: AppColors.cannot)),
        ],
      ],
    );
  }

  Future<void> _pickCountry(BuildContext context) async {
    final picked = await showModalBottomSheet<String>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      useSafeArea: true,
      backgroundColor: AppColors.surface,
      builder: (context) => _CountrySheet(selected: region),
    );
    if (picked != null) {
      onRegionChanged(picked);
      // Straight on to the number (the keyboard opens).
      focusNode?.requestFocus();
    }
  }
}

class _CountrySheet extends StatelessWidget {
  const _CountrySheet({required this.selected});

  final String selected;

  @override
  Widget build(BuildContext context) {
    final options = [
      for (final c in phoneCountries) (c.region, '${c.name} +${c.code}'),
      (otherCountry, 'Inny kraj (wpisz numer z +)'),
    ];
    return DraggableScrollableSheet(
      expand: false,
      initialChildSize: 0.7,
      maxChildSize: 0.95,
      builder: (context, scroll) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(gutter, 0, gutter, 8),
            child: Semantics(header: true, child: Text('Kraj numeru', style: Theme.of(context).textTheme.titleMedium)),
          ),
          Expanded(
            child: ListView(
              controller: scroll,
              children: [
                for (final (region, label) in options)
                  ListTile(
                    minTileHeight: touch,
                    title: Text(label),
                    selected: region == selected,
                    trailing: region == selected ? const Icon(Icons.check) : null,
                    onTap: () => Navigator.of(context).pop(region),
                  ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
