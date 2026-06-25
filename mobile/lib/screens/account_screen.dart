import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';
import '../api.dart';
import '../store.dart';
import '../main.dart' show kPrivacyUrl, kTermsUrl;

/// Account tab: usage, legal links, sign-out, and the Play-required
/// "delete account & data" action.
class AccountScreen extends StatefulWidget {
  const AccountScreen({
    super.key,
    required this.api,
    required this.apiKey,
    required this.onKey,
  });

  final QmolApi api;
  final String? apiKey;
  final void Function(String?) onKey;

  @override
  State<AccountScreen> createState() => _AccountScreenState();
}

class _AccountScreenState extends State<AccountScreen> {
  Map<String, dynamic>? _usage;
  String? _error;
  String? _lastKeyLoaded;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final key = widget.apiKey;
    if (key != null && key != _lastKeyLoaded) {
      _lastKeyLoaded = key;
      _load(key);
    }
  }

  Future<void> _load(String key) async {
    try {
      final u = await widget.api.usage(key);
      if (mounted) setState(() => _usage = u);
    } catch (e) {
      if (mounted) setState(() => _error = e.toString());
    }
  }

  Future<void> _open(String url) =>
      launchUrl(Uri.parse(url), mode: LaunchMode.externalApplication);

  Future<void> _delete() async {
    final key = widget.apiKey;
    if (key == null) return;
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: const Text('Delete account?'),
        content: const Text(
            'This permanently deletes your account and all associated data. '
            'This cannot be undone.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('Delete')),
        ],
      ),
    );
    if (ok != true) return;
    try {
      await widget.api.accountDelete(key);
      await Store.clear();
      widget.onKey(null);
      if (mounted) setState(() => _usage = null);
    } catch (e) {
      if (mounted) setState(() => _error = e.toString());
    }
  }

  @override
  Widget build(BuildContext context) {
    if (widget.apiKey == null) {
      return const Center(
        child: Padding(
          padding: EdgeInsets.all(20),
          child: Text('No key yet. Get a free key on the Compute tab, or subscribe.'),
        ),
      );
    }
    return ListView(
      padding: const EdgeInsets.all(20),
      children: [
        const Text('Account',
            style: TextStyle(fontSize: 22, fontWeight: FontWeight.bold)),
        const SizedBox(height: 12),
        if (_usage != null) ...[
          ListTile(title: const Text('Tier'), trailing: Text('${_usage!['tier']}')),
          ListTile(
              title: const Text('Used this month'),
              trailing: Text('${_usage!['used_this_month']}')),
          ListTile(
              title: const Text('Monthly quota'),
              trailing: Text('${_usage!['monthly_quota']}')),
        ],
        if (_error != null)
          Text(_error!, style: const TextStyle(color: Colors.redAccent)),
        const Divider(),
        ListTile(
            leading: const Icon(Icons.privacy_tip_outlined),
            title: const Text('Privacy policy'),
            onTap: () => _open(kPrivacyUrl)),
        ListTile(
            leading: const Icon(Icons.description_outlined),
            title: const Text('Terms of service'),
            onTap: () => _open(kTermsUrl)),
        const Divider(),
        ListTile(
            leading: const Icon(Icons.logout),
            title: const Text('Sign out (forget key)'),
            onTap: () async {
              await Store.clear();
              widget.onKey(null);
            }),
        ListTile(
            leading: const Icon(Icons.delete_forever, color: Colors.redAccent),
            title: const Text('Delete account & data'),
            onTap: _delete),
      ],
    );
  }
}
