# Cold outreach templates

Send 20 of these per day. Track replies in a spreadsheet.

---

## Template A — Academic comp-chem / cheminformatics labs

**Subject:** Free pre-computed descriptor dataset (RDKit, 100k+ molecules) — useful for your group?

Hi Dr. {LastName},

I maintain Q-Mol — a continuously-updated dataset of molecular descriptors
(MW, logP, TPSA, QED, ECFP4, ring counts, etc.) computed with RDKit from
PubChem structures. It's designed as a drop-in featurizer for QSAR / ADMET
ML pipelines.

- Parquet + CSV, loads in one line
- Free tier (CC BY-NC): https://huggingface.co/datasets/{YOUR-HF-USER}/qmol
- 100-row sample: {LANDING-URL}#sample

Would a copy save your students re-running RDKit over 100k+ SMILES?
Happy to tailor the descriptor set to your use case.

Best,
{YOUR-NAME}

---

## Template B — Pharma / biotech ML engineers

**Subject:** Drop-in molecular descriptor dataset — Parquet, commercial license available

Hi {FirstName},

Saw your post about {TOPIC — e.g., "QSAR featurization bottlenecks"}.

I ship Q-Mol, a continuously-updated Parquet of RDKit descriptors
(MW, logP, TPSA, HBD/HBA, QED, ECFP4 hash) over PubChem. Commercial license
is a one-time $299 per team; or I can run your private SMILES list and
deliver the same schema under NDA.

Free 100-row sample: {LANDING-URL}#sample

Worth a 15-minute call to see if it fits your pipeline?

Best,
{YOUR-NAME}

---

## Template C — Kaggle / ML community

**Subject:** Pre-featurized molecular descriptor dataset for your next comp-chem comp

Hi {FirstName},

I've been publishing Q-Mol — RDKit descriptors over PubChem, continuously
updated — on Hugging Face and Kaggle. It's a reproducible baseline for
QSAR / ADMET models; saves the "spend a day running RDKit" step.

- HF: https://huggingface.co/datasets/{YOUR-HF-USER}/qmol
- Sample + docs: {LANDING-URL}

If you want a descriptor I'm not computing yet, reply and I'll add it.

Cheers,
{YOUR-NAME}

---

## Subject-line A/B pool

1. "Free pre-computed RDKit descriptors (Parquet) — useful?"
2. "Saves a day of RDKit runs — Q-Mol sample inside"
3. "Drop-in molecular featurizer for your QSAR pipeline"
4. "100k RDKit descriptors, one Parquet, free sample"

---

## Reply-handling rules

- If they ask for a specific descriptor → add it to `src/compute.py`, ship in next release, email the file back.
- If they ask for a commercial quote → $299 per team flat, $999 for redistribution rights, custom compute $50/hr.
- If they ask about quantum methods → offer to run small subset with pyQPanda/PySCF on request (mark as premium tier).
- If they go silent → one follow-up in 5 days, then drop.
