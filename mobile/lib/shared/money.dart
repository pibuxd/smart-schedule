// Amounts of money in złoty, written as on the website (`frontend/src/lib/money.ts`, the browser's pl-PL format):
// a decimal comma, groups of three digits only from five digits on, and "zł" after a non-breaking space.

const _space = ' ';

/// 3768 -> "3768,00 zł", 12345.5 -> "12 345,50 zł".
String moneyText(num value) {
  final cents = (value * 100).round();
  final sign = cents < 0 ? '-' : '';
  final whole = (cents.abs() ~/ 100).toString();
  final rest = (cents.abs() % 100).toString().padLeft(2, '0');
  return '$sign${_grouped(whole)},$rest${_space}zł';
}

String _grouped(String digits) {
  if (digits.length < 5) return digits;
  final groups = <String>[];
  for (var end = digits.length; end > 0; end -= 3) {
    groups.insert(0, digits.substring(end - 3 < 0 ? 0 : end - 3, end));
  }
  return groups.join(_space);
}
