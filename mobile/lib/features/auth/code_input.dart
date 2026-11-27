import 'package:flutter/services.dart';
import 'package:material_ui/material_ui.dart';

import '../../ui/theme.dart';

/// Six big boxes for the SMS code. Underneath is one ordinary field, so the phone can offer the code from the SMS
/// (above the keyboard on an iPhone) and pasting works.
class CodeInput extends StatefulWidget {
  const CodeInput({super.key, required this.controller, this.enabled = true, this.invalid = false});

  final TextEditingController controller;
  final bool enabled;
  final bool invalid;

  @override
  State<CodeInput> createState() => _CodeInputState();
}

class _CodeInputState extends State<CodeInput> {
  final _focus = FocusNode();

  @override
  void initState() {
    super.initState();
    widget.controller.addListener(_changed);
    _focus.addListener(_changed);
  }

  @override
  void dispose() {
    widget.controller.removeListener(_changed);
    _focus.dispose();
    super.dispose();
  }

  void _changed() => setState(() {});

  @override
  Widget build(BuildContext context) {
    final value = widget.controller.text;
    final active = value.length.clamp(0, 5);
    return GestureDetector(
      onTap: () => _focus.requestFocus(),
      child: Stack(
        children: [
          ExcludeSemantics(
            child: Row(
              children: [
                for (var i = 0; i < 6; i++) ...[
                  if (i > 0) const SizedBox(width: 8),
                  Expanded(
                    child: Container(
                      height: 64,
                      alignment: Alignment.center,
                      decoration: BoxDecoration(
                        color: AppColors.surface,
                        borderRadius: BorderRadius.circular(AppRadius.md),
                        border: Border.all(
                          width: 2,
                          color: widget.invalid
                              ? AppColors.cannot
                              : (widget.enabled && _focus.hasFocus && i == active ? AppColors.accent : AppColors.line),
                        ),
                      ),
                      child: Text(
                        i < value.length ? value[i] : '',
                        style: const TextStyle(fontSize: 21, fontWeight: FontWeight.w800),
                      ),
                    ),
                  ),
                ],
              ],
            ),
          ),
          Positioned.fill(
            child: Opacity(
              opacity: 0,
              child: TextField(
                controller: widget.controller,
                focusNode: _focus,
                autofocus: true,
                enabled: widget.enabled,
                keyboardType: TextInputType.number,
                autofillHints: const [AutofillHints.oneTimeCode],
                inputFormatters: [FilteringTextInputFormatter.digitsOnly, LengthLimitingTextInputFormatter(6)],
                showCursor: false,
                enableInteractiveSelection: true,
                decoration: const InputDecoration(
                  labelText: 'Kod z SMS-a, 6 cyfr',
                  border: InputBorder.none,
                  counterText: '',
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}
