import 'package:flutter/material.dart';
import 'package:in_app_purchase/in_app_purchase.dart';
import '../api.dart';
import '../billing.dart';

/// Subscribe tab: lists Play subscription products and starts a Play Billing
/// purchase. On success the backend verifies the token and returns the key.
class SubscribeScreen extends StatefulWidget {
  const SubscribeScreen({
    super.key,
    required this.api,
    required this.billing,
    required this.onKey,
  });

  final QmolApi api;
  final Billing billing;
  final void Function(String?) onKey;

  @override
  State<SubscribeScreen> createState() => _SubscribeScreenState();
}

class _SubscribeScreenState extends State<SubscribeScreen> {
  List<ProductDetails> _products = const [];
  bool _loading = true;
  String? _msg;

  @override
  void initState() {
    super.initState();
    widget.billing.start(
      onKey: (k) {
        widget.onKey(k);
        if (mounted) setState(() => _msg = 'Subscription active — your key is saved.');
      },
      onError: (e) {
        if (mounted) setState(() => _msg = e);
      },
    );
    _load();
  }

  Future<void> _load() async {
    try {
      if (!await widget.billing.available()) {
        setState(() {
          _msg = 'In-app billing is unavailable on this device.';
          _loading = false;
        });
        return;
      }
      final p = await widget.billing.products();
      setState(() {
        _products = p;
        _loading = false;
      });
    } catch (e) {
      setState(() {
        _msg = e.toString();
        _loading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) return const Center(child: CircularProgressIndicator());
    return Padding(
      padding: const EdgeInsets.all(20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const Text('Subscribe',
              style: TextStyle(fontSize: 22, fontWeight: FontWeight.bold)),
          const SizedBox(height: 4),
          const Text('Higher quotas + all endpoints. Billed securely via Google Play.'),
          const SizedBox(height: 16),
          for (final p in _products)
            Card(
              child: ListTile(
                title: Text(p.title.isEmpty ? p.id : p.title),
                subtitle: Text(p.description),
                trailing: FilledButton(
                    onPressed: () => widget.billing.buy(p),
                    child: Text(p.price)),
              ),
            ),
          if (_products.isEmpty)
            const Padding(
              padding: EdgeInsets.symmetric(vertical: 12),
              child: Text(
                  'No subscription products found. Create them in Play Console '
                  'with ids qmol_research_monthly / qmol_commercial_monthly.'),
            ),
          if (_msg != null)
            Padding(
              padding: const EdgeInsets.only(top: 16),
              child: Text(_msg!),
            ),
        ],
      ),
    );
  }
}
