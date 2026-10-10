# Evaluation

`supplier-desk evaluate` compares detected pairs with the labelled duplicate
clusters in the `Ground_Truth` sheet of the sample workbook. The labels are read
only by `supplier_agent/evaluation.py`; the scan, the agent and the UI never see them.

```bash
supplier-desk sample sample_suppliers.xlsx
supplier-desk evaluate --input sample_suppliers.xlsx --threshold 65 --output-dir outputs/evaluation
```

## Result on the bundled sample (threshold 65)

The sample has 1,000 fictional suppliers with 30 planted duplicate clusters (90 duplicate
pairs) and planted look-alikes that are **not** duplicates: sister companies sharing an
address, unrelated suppliers paid through the same factoring account, and same-brand
subsidiaries in other countries.

| Metric | Result |
|---|---:|
| Suppliers / possible pairs | 1,000 / 499,500 |
| Candidate pairs generated | 120 |
| Labelled duplicate pairs | 90 |
| True positives / false positives / false negatives | 90 / 0 / 0 |
| Precision / recall / F1 | 1.00 / 1.00 / 1.00 |

| Threshold | Pairs flagged | Precision | Recall |
|---:|---:|---:|---:|
| 25 | 114 | 0.79 | 1.00 |
| 40 | 91 | 0.99 | 1.00 |
| 50 – 95 | 90 | 1.00 | 1.00 |

At 25 the look-alikes (sister companies at one address, shared factoring accounts) are counted as
duplicates; at 40 one of them still is. From 50 upwards every planted duplicate is found and nothing
else. Matching email and phone numbers keep re-entered variants above 85 even when the bank account
changed or the tax ID was left blank. The default priorities (High ≥ 65, Medium ≥ 40) put the planted
duplicates in High and leave the single look-alike at Medium, where a reviewer sees it.

## How to read this

The planted cases are cleaner than real data, so this shows that the implementation
recovers the designed cases — **not** that it will be perfect on your data. Thresholds
are compared on the same labels (there is no held-out set). Quality-rule recall, LLM
explanation quality and time saved are not measured. To evaluate on your own data, add a
`Ground_Truth` sheet with `SUPPLIER_ID`, `ISSUE_TYPE`, `DUPLICATE_CLUSTER_ID`,
`EXPECTED_DECISION` and `NOTES`, include hard negatives, and run the same command. The
sample itself is produced by `scripts/generate_sample_data.py`, so you can change the mix
and regenerate it.

## Performance

Measured on a 2-core cloud VM with deliberately similar random names (a worst
case): 1,000 suppliers in about 2 s; 20,000 suppliers spread over 20 countries
in about 25 s; 3,000 suppliers in a single country in about 10 s. Fuzzy
comparison runs inside each country with RapidFuzz's vectorized `cdist`, so
time grows with the square of the largest country; more CPU cores help.
