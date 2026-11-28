import 'package:flutter_test/flutter_test.dart';
import 'package:grafikomat/shared/bank_account.dart';
import 'package:grafikomat/shared/phone.dart';

// The same cases as the website's `frontend/src/features/auth/phone.test.ts`, so both number the same way.
void main() {
  test('puts the picked country in front of the typed digits', () {
    expect(phoneToSend('PL', '512 345 678'), '+48512345678');
    expect(phoneToSend('PL', '48 512-345-678'), '+48512345678');
    expect(phoneToSend('UA', '50 123 45 67'), '+380501234567');
    // The national 0 people write in their own country stays: the server knows where to drop it.
    expect(phoneToSend('UA', '050 123 45 67'), '+3800501234567');
    expect(phoneToSend(otherCountry, '1 202 555 0123'), '+12025550123');
  });

  test('takes a number typed with + or 00 whole, whatever country is picked', () {
    expect(phoneToSend('PL', '+380 50 123 4567'), '+380501234567');
    expect(phoneToSend('PL', '0048 512 345 678'), '+48512345678');
    expect(phoneToSend('UA', '+48 512 345 678'), '+48512345678');
  });

  test('asks for 9 digits of a Polish number and for a whole number elsewhere', () {
    expect(phoneProblem('PL', '12 34'), startsWith('Wpisz 9 cyfr'));
    expect(phoneProblem('PL', '512 345 678'), isNull);
    expect(phoneProblem('PL', 'abc'), 'Wpisz same cyfry numeru.');
    expect(phoneProblem('UA', '50 12'), 'Wpisz cały numer telefonu.');
    expect(phoneProblem('UA', '50 123 4567'), isNull);
  });

  test('writes stored numbers with the country code apart', () {
    expect(prettyPhone('+48512345678'), '+48 512 345 678');
    expect(prettyPhone('+380501234567'), '+380 501 234 567');
    expect(prettyPhone('+4915123456789'), '+49 151 234 567 89');
    expect(prettyPhone('+447400123456'), '+44 740 012 3456');
    expect(prettyPhone('512 345 678'), '512 345 678');
    expect(isE164('+380501234567'), isTrue);
    expect(isE164('050 123 4567'), isFalse);
  });

  test('tidies a bank account number like the server', () {
    expect(tidyBankAccount('  12 3456   7890 '), '12 3456 7890');
    expect(tidyBankAccount('   '), '');
  });
}
