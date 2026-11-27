/// Phone numbers, as on the website (`frontend/src/features/auth/phone.ts`, same rules and the same test cases in
/// `test/shared/phone_test.dart`). The server stores and returns them in E.164 ("+48512345678") and checks them;
/// here they are only put together from the country and the typed digits, and written out.
library;

class PhoneCountry {
  const PhoneCountry({required this.region, required this.name, required this.code, required this.example});

  /// ISO code, the value of the country list.
  final String region;
  final String name;

  /// Calling code without "+".
  final String code;

  /// A number of that country after its code, as the placeholder.
  final String example;
}

const poland = PhoneCountry(region: 'PL', name: 'Polska', code: '48', example: '512 345 678');

/// Poland first, then Ukraine (most people from abroad in Polish venues), then the rest alphabetically. Anyone else
/// picks "Inny kraj" and writes the number with its code; a number typed with "+" works whatever is picked.
const phoneCountries = <PhoneCountry>[
  poland,
  PhoneCountry(region: 'UA', name: 'Ukraina', code: '380', example: '50 123 4567'),
  PhoneCountry(region: 'BY', name: 'Białoruś', code: '375', example: '29 491 19 11'),
  PhoneCountry(region: 'CZ', name: 'Czechy', code: '420', example: '601 123 456'),
  PhoneCountry(region: 'PH', name: 'Filipiny', code: '63', example: '905 123 4567'),
  PhoneCountry(region: 'GE', name: 'Gruzja', code: '995', example: '555 12 34 56'),
  PhoneCountry(region: 'IN', name: 'Indie', code: '91', example: '81234 56789'),
  PhoneCountry(region: 'KZ', name: 'Kazachstan', code: '7', example: '771 000 9998'),
  PhoneCountry(region: 'CO', name: 'Kolumbia', code: '57', example: '321 1234567'),
  PhoneCountry(region: 'LT', name: 'Litwa', code: '370', example: '612 34567'),
  PhoneCountry(region: 'MD', name: 'Mołdawia', code: '373', example: '621 12 345'),
  PhoneCountry(region: 'NP', name: 'Nepal', code: '977', example: '984 1234567'),
  PhoneCountry(region: 'DE', name: 'Niemcy', code: '49', example: '1512 3456789'),
  PhoneCountry(region: 'RO', name: 'Rumunia', code: '40', example: '712 034 567'),
  PhoneCountry(region: 'SK', name: 'Słowacja', code: '421', example: '912 123 456'),
  PhoneCountry(region: 'TR', name: 'Turcja', code: '90', example: '501 234 56 78'),
  PhoneCountry(region: 'UZ', name: 'Uzbekistan', code: '998', example: '91 234 56 78'),
  PhoneCountry(region: 'GB', name: 'Wielka Brytania', code: '44', example: '7400 123456'),
  PhoneCountry(region: 'VN', name: 'Wietnam', code: '84', example: '912 345 678'),
];

/// The value of "Inny kraj": the number is typed whole, with "+" and its code.
const otherCountry = 'other';

PhoneCountry? phoneCountry(String region) {
  for (final country in phoneCountries) {
    if (country.region == region) return country;
  }
  return null;
}

final _separators = RegExp(r'[\s\-./()]');

/// The number to send: typed with "+" or "00" it is taken whole (whatever country is picked), otherwise the picked
/// country's code goes in front. A Polish number typed with 48 in front still works ("48 512 345 678").
String phoneToSend(String region, String typed) {
  final compact = typed.replaceAll(_separators, '');
  if (compact.startsWith('+')) return compact;
  if (compact.startsWith('00')) return '+${compact.substring(2)}';
  final country = phoneCountry(region);
  if (country == null) return '+$compact';
  if (identical(country, poland) && RegExp(r'^48\d{9}$').hasMatch(compact)) return '+$compact';
  return '+${country.code}$compact';
}

/// What is wrong with a typed number before anything is sent (the server checks the rest), or null.
String? phoneProblem(String region, String typed) {
  final whole = phoneToSend(region, typed);
  if (!RegExp(r'^\+\d+$').hasMatch(whole)) return 'Wpisz same cyfry numeru.';
  if (region == poland.region && whole.startsWith('+48') && whole.length != 12) {
    return 'Wpisz 9 cyfr numeru, na przykład 512 345 678.';
  }
  if (whole.length < 9 || whole.length > 16) return 'Wpisz cały numer telefonu.';
  return null;
}

// Every country calling code (ITU), for splitting a stored number into the code and the rest. No code is the
// beginning of another, so the first one that matches is the right one.
final _callingCodes =
    ('1 7 20 27 30 31 32 33 34 36 39 40 41 43 44 45 46 47 48 49 51 52 53 54 55 56 57 58 60 61 62 63 64 65 66 81 82 '
            '84 86 90 91 92 93 94 95 98 211 212 213 216 218 220 221 222 223 224 225 226 227 228 229 230 231 232 233 234 '
            '235 236 237 238 239 240 241 242 243 244 245 246 247 248 249 250 251 252 253 254 255 256 257 258 260 261 262 '
            '263 264 265 266 267 268 269 290 291 297 298 299 350 351 352 353 354 355 356 357 358 359 370 371 372 373 374 '
            '375 376 377 378 380 381 382 383 385 386 387 389 420 421 423 500 501 502 503 504 505 506 507 508 509 590 591 '
            '592 593 594 595 596 597 598 599 670 672 673 674 675 676 677 678 679 680 681 682 683 685 686 687 688 689 690 '
            '691 692 850 852 853 855 856 880 886 960 961 962 963 964 965 966 967 968 970 971 972 973 974 975 976 977 992 '
            '993 994 995 996 998')
        .split(' ')
        .toSet();

String _groups(String digits) {
  final parts = RegExp(r'\d{1,3}').allMatches(digits).map((m) => m.group(0)!).toList();
  // No lonely last digit: "151 123 456 7" reads better as "151 123 4567".
  if (parts.length > 1 && parts.last.length == 1) {
    final last = parts.removeLast();
    parts.add(parts.removeLast() + last);
  }
  return parts.join(' ');
}

/// "+48512345678" -> "+48 512 345 678", "+380501234567" -> "+380 501 234 567".
String prettyPhone(String e164) {
  if (!RegExp(r'^\+\d{6,15}$').hasMatch(e164)) return e164;
  final digits = e164.substring(1);
  for (final n in [1, 2, 3]) {
    final code = digits.substring(0, n);
    if (_callingCodes.contains(code)) return '+$code ${_groups(digits.substring(n))}';
  }
  return e164;
}

/// A stored number (E.164), not a number as someone typed it.
bool isE164(String phone) => RegExp(r'^\+\d{7,15}$').hasMatch(phone);
