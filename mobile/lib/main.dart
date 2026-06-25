import 'package:flutter/material.dart';
import 'api.dart';
import 'billing.dart';
import 'store.dart';
import 'screens/compute_screen.dart';
import 'screens/subscribe_screen.dart';
import 'screens/account_screen.dart';

/// API base URL. Override at build time:
///   flutter build appbundle --dart-define=QMOL_API=https://your-domain
const String kApiBase = String.fromEnvironment(
  'QMOL_API',
  defaultValue: 'https://qua-22p1.onrender.com',
);
const String kPrivacyUrl = '$kApiBase/privacy';
const String kTermsUrl = '$kApiBase/terms';

void main() => runApp(const QmolApp());

class QmolApp extends StatelessWidget {
  const QmolApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Q-Mol',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorSchemeSeed: const Color(0xFF38BDF8),
        brightness: Brightness.dark,
        useMaterial3: true,
      ),
      home: const RootPage(),
    );
  }
}

class RootPage extends StatefulWidget {
  const RootPage({super.key});
  @override
  State<RootPage> createState() => _RootPageState();
}

class _RootPageState extends State<RootPage> {
  final QmolApi api = QmolApi(kApiBase);
  late final Billing billing = Billing(api);
  int _tab = 0;
  String? _key;

  @override
  void initState() {
    super.initState();
    Store.getKey().then((k) => setState(() => _key = k));
  }

  void _setKey(String? k) => setState(() => _key = k);

  @override
  void dispose() {
    billing.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final pages = <Widget>[
      ComputeScreen(api: api, apiKey: _key, onKey: _setKey),
      SubscribeScreen(api: api, billing: billing, onKey: _setKey),
      AccountScreen(api: api, apiKey: _key, onKey: _setKey),
    ];
    return Scaffold(
      appBar: AppBar(title: const Text('Q-Mol')),
      body: pages[_tab],
      bottomNavigationBar: NavigationBar(
        selectedIndex: _tab,
        onDestinationSelected: (i) => setState(() => _tab = i),
        destinations: const [
          NavigationDestination(icon: Icon(Icons.science_outlined), label: 'Compute'),
          NavigationDestination(
              icon: Icon(Icons.workspace_premium_outlined), label: 'Subscribe'),
          NavigationDestination(icon: Icon(Icons.person_outline), label: 'Account'),
        ],
      ),
    );
  }
}
