import 'package:shared_preferences/shared_preferences.dart';

/// Local persistence for the API key.
class Store {
  static const _kKey = 'qmol_api_key';

  static Future<String?> getKey() async =>
      (await SharedPreferences.getInstance()).getString(_kKey);

  static Future<void> setKey(String key) async =>
      (await SharedPreferences.getInstance()).setString(_kKey, key);

  static Future<void> clear() async =>
      (await SharedPreferences.getInstance()).remove(_kKey);
}
