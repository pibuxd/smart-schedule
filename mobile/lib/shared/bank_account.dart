/// The number the way the server keeps it: as written, any bank, with runs of spaces made one (Piotr, 25.11.2026;
/// as `frontend/src/features/auth/bank-account.ts`).
String tidyBankAccount(String typed) => typed.trim().split(RegExp(r'\s+')).where((part) => part.isNotEmpty).join(' ');
