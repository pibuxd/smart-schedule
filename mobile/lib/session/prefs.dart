import 'dart:async';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Small values the app keeps between starts: the session key and the chosen company. They live in the system's
/// secure storage (Keychain on iOS, Keystore-encrypted on Android) and are read once at start, so screens know them
/// at once; writes go to storage in the background.
abstract class KeyValueStore {
  Future<String?> read(String key);
  Future<void> write(String key, String? value);
}

class SecureStore implements KeyValueStore {
  const SecureStore([this._storage = const FlutterSecureStorage()]);

  final FlutterSecureStorage _storage;

  @override
  Future<String?> read(String key) => _storage.read(key: key);

  @override
  Future<void> write(String key, String? value) =>
      value == null ? _storage.delete(key: key) : _storage.write(key: key, value: value);
}

/// Tests and previews: nothing leaves memory.
class MemoryStore implements KeyValueStore {
  MemoryStore([Map<String, String>? values]) : values = {...?values};

  final Map<String, String> values;

  @override
  Future<String?> read(String key) async => values[key];

  @override
  Future<void> write(String key, String? value) async {
    if (value == null) {
      values.remove(key);
    } else {
      values[key] = value;
    }
  }
}

class Prefs {
  Prefs._(this._store, this._values);

  static const sessionKey = 'grafikomat.session';
  static const companyKey = 'grafikomat.company';

  final KeyValueStore _store;
  final Map<String, String?> _values;

  /// Reads every value once. Storage that cannot be read (a damaged keychain entry) counts as empty: the person
  /// logs in again.
  static Future<Prefs> load(KeyValueStore store) async {
    final values = <String, String?>{};
    for (final key in [sessionKey, companyKey]) {
      try {
        values[key] = await store.read(key);
      } catch (_) {
        values[key] = null;
      }
    }
    return Prefs._(store, values);
  }

  String? get(String key) => _values[key];

  void set(String key, String? value) {
    if (_values[key] == value) return;
    _values[key] = value;
    unawaited(_store.write(key, value).catchError((Object _) {}));
  }
}
