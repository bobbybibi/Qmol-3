import 'package:flutter/material.dart';
import '../api.dart';
import '../store.dart';

/// Compute tab: enter a SMILES, get descriptors. Prompts for a free key first.
class ComputeScreen extends StatefulWidget {
  const ComputeScreen({
    super.key,
    required this.api,
    required this.apiKey,
    required this.onKey,
  });

  final QmolApi api;
  final String? apiKey;
  final void Function(String?) onKey;

  @override
  State<ComputeScreen> createState() => _ComputeScreenState();
}

class _ComputeScreenState extends State<ComputeScreen> {
  final _smiles = TextEditingController(text: 'CC(=O)Oc1ccccc1C(=O)O');
  final _email = TextEditingController();
  static const _shown = [
    'MolWt', 'TPSA', 'MolLogP', 'NumHDonors', 'NumHAcceptors', 'qed'
  ];

  bool _busy = false;
  String? _error;
  List<Map<String, dynamic>> _results = const [];

  Future<void> _getFreeKey() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final k = await widget.api.signup(_email.text.trim());
      await Store.setKey(k);
      widget.onKey(k);
    } catch (e) {
      setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _compute() async {
    final key = widget.apiKey;
    if (key == null) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final r = await widget.api
          .descriptors(key, [_smiles.text.trim()], names: _shown);
      setState(() => _results = r);
    } catch (e) {
      setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (widget.apiKey == null) {
      return Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const SizedBox(height: 8),
            const Text('Get a free API key',
                style: TextStyle(fontSize: 22, fontWeight: FontWeight.bold)),
            const SizedBox(height: 4),
            const Text('500 molecules / month. No card required.'),
            const SizedBox(height: 16),
            TextField(
              controller: _email,
              keyboardType: TextInputType.emailAddress,
              decoration: const InputDecoration(
                  labelText: 'Email', border: OutlineInputBorder()),
            ),
            const SizedBox(height: 12),
            FilledButton(
                onPressed: _busy ? null : _getFreeKey,
                child: Text(_busy ? 'Working…' : 'Get free key')),
            if (_error != null)
              Padding(
                padding: const EdgeInsets.only(top: 12),
                child: Text(_error!,
                    style: const TextStyle(color: Colors.redAccent)),
              ),
          ],
        ),
      );
    }

    return Padding(
      padding: const EdgeInsets.all(20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          TextField(
            controller: _smiles,
            decoration: const InputDecoration(
                labelText: 'SMILES', border: OutlineInputBorder()),
          ),
          const SizedBox(height: 12),
          FilledButton(
              onPressed: _busy ? null : _compute,
              child: Text(_busy ? 'Computing…' : 'Compute descriptors')),
          const SizedBox(height: 12),
          if (_error != null)
            Text(_error!, style: const TextStyle(color: Colors.redAccent)),
          Expanded(
            child: ListView(
              children: [
                for (final row in _results)
                  for (final k in _shown)
                    ListTile(
                      dense: true,
                      title: Text(k),
                      trailing:
                          Text('${(row['descriptors'] as Map)[k] ?? '—'}'),
                    ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
