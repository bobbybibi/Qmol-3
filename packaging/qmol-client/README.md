# qmol-client

Thin Python client + CLI for the [Q-Mol](https://qmol.ai) molecular descriptor API.

```bash
pip install qmol-client
export QMOL_API_KEY=qmol_...
qmol compute "CCO" "c1ccccc1"
```

```python
from qmol_client import QMolClient
c = QMolClient(api_key="qmol_...")
print(c.compute(["CCO", "c1ccccc1"]))
print(c.similarity("CCO", top_k=5))
```

License: Apache-2.0.
