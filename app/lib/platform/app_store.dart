import 'package:shared_preferences/shared_preferences.dart';

abstract interface class AppStore {
  Future<String?> read(String key);
  Future<void> write(String key, String value);
}

class PreferencesAppStore implements AppStore {
  final _preferences = SharedPreferencesAsync();

  @override
  Future<String?> read(String key) => _preferences.getString(key);

  @override
  Future<void> write(String key, String value) =>
      _preferences.setString(key, value);
}
