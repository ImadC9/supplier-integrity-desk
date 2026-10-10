# Labelled Evaluation

## Goal

Measure how well the current deterministic duplicate detector recovers known
duplicate relationships. This step evaluates the existing behavior before any
threshold is changed.

```text
Supplier_Master -> DuplicateDetector -> scored prediction pairs
                                          |
Ground_Truth -> labelled cluster pairs ----+-> confusion matrix
```

`Ground_Truth` is loaded only by `evaluation.py`. The LangGraph workflow,
controlled tools, retrieval system, embedding model, and analysis provider do
not import or receive it. This prevents the agent from seeing the answers while
it investigates a supplier.

## Why evaluation is pair-level

Duplicate detection compares two records. The ground-truth sheet identifies
duplicate clusters rather than listing every pair. The evaluator converts each
cluster into every unique pair.

For a three-record cluster containing `A`, `B`, and `C`, the labelled positive
pairs are:

```text
A-B
A-C
B-C
```

The supplied workbook has 30 three-record clusters, so it contains 90 labelled
positive pairs.

## Confusion matrix

At the selected threshold, every possible supplier pair belongs to one group:

- **True positive:** labelled duplicate and predicted duplicate.
- **False positive:** not a labelled duplicate but predicted duplicate.
- **False negative:** labelled duplicate but not predicted duplicate.
- **True negative:** not a labelled duplicate and not predicted duplicate.

The evaluator does not write almost half a million true-negative rows. It
calculates their count and writes only true positives, false positives, and
false negatives to `evaluation_cases.csv` for practical review.

## Metrics

```text
Precision = TP / (TP + FP)
Recall    = TP / (TP + FN)
F1        = 2TP / (2TP + FP + FN)
```

- Precision asks: when the detector flags a pair, how often is it right?
- Recall asks: of the known duplicate pairs, how many did it find?
- F1 balances precision and recall.
- Candidate-pair recall checks whether candidate generation surfaced the known
  duplicates before the final score threshold was applied.

Accuracy is included but should not drive the decision because almost every
possible supplier pair is a true negative. A detector could miss many
duplicates and still appear highly accurate.

## Threshold comparison

The report compares thresholds 25, 40, 50, 65, 75, 85, and 95. This is a
diagnostic sensitivity table, not automatic tuning. We keep 65 as the selected
headline threshold because changing detector behavior should be a separate,
explicit decision.

On this synthetic workbook, thresholds from 40 through 95 all score perfectly.
That does not identify a uniquely correct threshold; it shows that the
intentional duplicate cases are cleanly separated from the other generated
records.

## Current result at threshold 65

```text
Labelled records:             1,000
Ground-truth duplicate pairs:    90
Detector candidate pairs:       145
Predicted duplicate pairs:       90
True positives:                  90
False positives:                  0
False negatives:                  0
Precision / Recall / F1:      1.000
```

## Important limitation

This is a synthetic benchmark designed around recognizable duplicate variants.
A perfect score proves the code recovers those designed examples. It does not
predict performance on real supplier data with typos, reused identifiers,
subsidiaries, transliteration, outdated addresses, or incomplete records.

The workbook also labels missing identifiers, status anomalies, shared bank
accounts, and currency anomalies. `label_profile.csv` makes those cases visible,
but the current detector does not predict those issue classes. Duplicate F1
must not be presented as overall supplier-data-quality coverage.

## Run it

```powershell
supplier-desk evaluate --input sample_suppliers.xlsx --threshold 65 --output-dir outputs/evaluation
```

Generated files:

- `evaluation_summary.json`: machine-readable metrics and methodology.
- `evaluation_cases.csv`: inspectable TP, FP, and FN pairs.
- `threshold_analysis.csv`: sensitivity by score threshold.
- `label_profile.csv`: all labelled issue types and expected decisions.
- `evaluation_report.md`: concise human-readable result and limitations.

## What Step 8 did not do

- It did not change a detector threshold.
- It did not train or fine-tune a model.
- It did not send labels to Gemini.
- It did not evaluate on approved real company records.
- It did not add missing-field, lifecycle, or currency-anomaly detectors.

Those distinctions keep the result honest and preserve Step 9 as the real-data
pilot rather than quietly turning this synthetic test into a production claim.
