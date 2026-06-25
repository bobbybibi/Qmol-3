import 'dart:convert';
import 'package:http/http.dart' as http;

/// Thin client for the Q-Mol API. Point [baseUrl] at your deployment, e.g.
/// `--dart-define=QMOL_API=https://your-domain`.
class QmolApi {
  QmolApi(this.baseUrl);
  final String baseUrl;

  Uri _u(String path) => Uri.parse('$baseUrl$path');

  Map<String, dynamic> _json(http.Response r) {
    final body = r.body.isEmpty ? '{}' : r.body;
    final j = jsonDecode(body);
    if (j is! Map<String, dynamic>) return {'value': j};
    return j;
  }

  Never _fail(http.Response r) =>
      throw ApiError(r.statusCode, (_json(r)['detail'] ?? r.body).toString());

  /// Free-tier signup → returns the API key.
  Future<String> signup(String email) async {
    final r = await http.post(_u('/signup'),
        headers: const {'content-type': 'application/json'},
        body: jsonEncode({'email': email}));
    if (r.statusCode != 200) _fail(r);
    return _json(r)['api_key'] as String;
  }

  /// Full RDKit descriptor panel (optionally a named subset).
  Future<List<Map<String, dynamic>>> descriptors(String apiKey,
      List<String> smiles, {List<String>? names}) async {
    final r = await http.post(_u('/descriptors'),
        headers: {'content-type': 'application/json', 'x-api-key': apiKey},
        body: jsonEncode({'smiles': smiles, if (names != null) 'names': names}));
    if (r.statusCode != 200) _fail(r);
    return (_json(r)['results'] as List).cast<Map<String, dynamic>>();
  }

  Future<Map<String, dynamic>> usage(String apiKey) async {
    final r = await http.get(_u('/usage'), headers: {'x-api-key': apiKey});
    if (r.statusCode != 200) _fail(r);
    return _json(r);
  }

  /// Verify a Google Play purchase server-side; returns the provisioned key.
  Future<String> playVerify(String productId, String purchaseToken,
      {String? email}) async {
    final r = await http.post(_u('/billing/play/verify'),
        headers: const {'content-type': 'application/json'},
        body: jsonEncode({
          'product_id': productId,
          'purchase_token': purchaseToken,
          if (email != null) 'email': email,
        }));
    if (r.statusCode != 200) _fail(r);
    return _json(r)['api_key'] as String;
  }

  Future<Map<String, dynamic>> accountExport(String apiKey) async {
    final r = await http.get(_u('/account/export'), headers: {'x-api-key': apiKey});
    if (r.statusCode != 200) _fail(r);
    return _json(r);
  }

  Future<void> accountDelete(String apiKey) async {
    final r = await http.delete(_u('/account'), headers: {'x-api-key': apiKey});
    if (r.statusCode != 200) _fail(r);
  }
}

class ApiError implements Exception {
  ApiError(this.status, this.detail);
  final int status;
  final String detail;
  @override
  String toString() => 'API $status: $detail';
}
