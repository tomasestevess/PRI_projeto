# PRI M2 — Retrieval Evaluation Documentation

## 1. Purpose and scope

This document describes the evaluation workflow implemented for Milestone 2 (M2) of the PRI project. The objective is to evaluate and compare two information-retrieval configurations over four defined information needs (IN1–IN4), using manually assessed relevance judgements.

The evaluation pipeline includes:
- building a judgement pool from retrieval runs;
- manually judging listing relevance;
- merging multiple assessors' decisions into final relevance labels;
- measuring assessor agreement;
- producing TREC-format relevance judgements (qrels);
- computing retrieval metrics and precision–recall curves;
- comparing Setup 1 and Setup 2; and
- conducting a parameter ablation study for the eDisMax `tie` parameter.

The project evaluates Airbnb listing documents for Porto and Lisbon, combining listing data, reviews, OpenStreetMap points of interest (POIs), and Wikipedia information about POIs.

---

## 2. Evaluation targets

### 2.1 Retrieval configurations

**Setup 1 — Flat baseline**
- One flat document per listing.
- Simple text analysis.
- No nested review or POI documents.
- Listing text query fields: `name^3`, `description^2`, `host_about^0.5`.
- Phrase fields: `name^6`, `description^4`.
- eDisMax with `tie=0.1` and `mm="2<-1 5<50%"`.

**Setup 2 — Enriched/nested retrieval**
- Listing documents with nested review and POI child documents.
- Multi-language text analysis and derived folding analyzers.
- English review field (`comments_en`) and POI fields (`poi_name`, `wikipedia_title`, `wikipedia_text`).
- Combines listing-text retrieval with review-parent and POI-parent matches.
- Includes a listing boost based on review rating and number of reviews.
- The current configuration uses `tie=0.1`.

### 2.2 Information needs

Evaluation covers these four information needs:

| ID | Information need | Main relevance evidence |
|---|---|---|
| IN1 | Quiet apartment near historic monuments in Porto | Porto listing, historic POI within 500 m, and quietness supported by description or reviews |
| IN2 | Family beach holiday in Lisbon | Lisbon listing, beach POI within 500 m, capacity for at least four guests, and reviews mentioning families/children |
| IN3 | Late arrival / easy self check-in | Reviews indicate easy/smooth late check-in or responsive host; review evidence is required |
| IN4 | Accessible stay / functioning elevator | Elevator mentioned in description/amenities and not contradicted by reviews stating it is broken or absent |

The detailed criteria and the handling of doubtful cases are defined in `docs/relevance-criteria.md`.

---

## 3. Relevance assessment

### 3.1 Binary labels

Each pooled listing receives a binary relevance label:
- `1` — relevant;
- `0` — not relevant.

If the evidence is missing or the assessor cannot confidently decide, the assessor assigns `0` and records `?` in the notes. The criteria also contain explicit rules for borderline cases.

### 3.2 Evidence shown to assessors

The evaluation pool includes evidence to support consistent decisions:
- listing metadata and URL;
- listing description sentences containing query words;
- matching amenities;
- number of matching reviews;
- selected matching reviews;
- number of matching POIs;
- selected POIs;
- POIs satisfying topic-specific conditions (where applicable).

For reviews and POIs, evidence is retrieved from Setup 2 using Solr subqueries. The pool builder uses looser evidence queries than the retrieval setups, so evidence needed for judging is not hidden by the retrieval configuration's own minimum-match restrictions. Review snippets are restricted to reviews containing actual query words; POIs may match through their Wikipedia text.

The pool CSV deliberately does **not** reveal the retrieval setup, rank, or source run to assessors. The provenance of each pooled listing is recorded separately in `evaluation/pool_sources.csv`, helping reduce assessment bias.

### 3.3 Independent judging

There are four assessor files:
- `evaluation/judgements_A.csv`
- `evaluation/judgements_B.csv`
- `evaluation/judgements_C.csv`
- `evaluation/judgements_D.csv`

The project instructions support two workflows:
1. **Independent assessment:** each assessor judges every pooled listing without consulting other assessors' files or discussing listings before finishing. This is the workflow intended for agreement analysis.
2. **Work-split assessment:** listings already judged by another assessor can be skipped, allowing assessment workload to be divided. This is useful operationally, but does not provide the same complete independent-assessment data for Fleiss' kappa.

The repository contains four assessor files and an agreement output indicating that all four assessors have complete judgements for the listings used in the agreement calculation.

---

## 4. Pool construction

### 4.1 Retrieval-run pooling

The judgement pool is created by `scripts/make_pool.py` (`make pool`).

For each information need, the pool contains the unique listings found in the top 50 results of the main runs. The project can also include extra runs, such as runs from the `tie` ablation, using the `--extra-runs` argument. Listings are merged without duplication.

### 4.2 TF-IDF pool expansion

To reduce the risk of missing relevant listings just below the retrieval cutoff:
- the main runs' results ranked from 51 through 200 are considered (default `--tfidf-depth 200`);
- candidates not already in the pool are scored with TF-IDF against the information need's title and description;
- text consists of the listing name and description;
- the top 10 positive-scoring candidates per need are added (default `--tfidf-n 10`).

This expansion is semi-automatic and is used only to discover additional candidates for manual assessment. It does not replace the retrieval systems being evaluated.

### 4.3 Pool outputs

- `evaluation/pool.csv` — pooled listings and evidence, assessor columns, final label, and notes.
- `evaluation/pool_sources.csv` — records which run/step contributed each listing, keeping source/rank information separate from the blinded judgement sheet.

---

## 5. Combining judgements and producing qrels

The merge procedure is implemented in `scripts/merge_judgements.py` (`make qrels`).

For each listing:
- if only one assessor has judged it, that judgement is used;
- if multiple assessors judged it, majority voting is used;
- non-unanimous cases are written to `evaluation/conflicts.csv`;
- a tie (e.g. 2–2) is initially treated as non-relevant (`0`) until a decision is entered in `evaluation/resolutions.csv`;
- an explicit resolution in `resolutions.csv` overrides the automatic decision.

The resulting `evaluation/qrels.txt` uses TREC format:

```text
qid 0 docid relevance
```

where relevance is `0` or `1`.

The merge script reports missing assessments and unresolved ties. Therefore, a complete evaluation should verify that every pooled listing has a final judgement and that any ties requiring resolution have been addressed.

---

## 6. Inter-assessor agreement

Agreement is calculated by `scripts/agreement.py` (`make agreement`).

### 6.1 Fleiss' kappa

With four assessors judging the same listings, the project uses **Fleiss' kappa**, which accounts for agreement expected by chance.

The output includes:
- `raters` — number of assessors;
- `listings` — listings judged by every assessor;
- `all_agree` — proportion where all assessors gave the same label;
- `observed_agreement` — average proportion of agreeing assessor pairs across listings;
- `fleiss_kappa` — chance-corrected agreement.

The repository's current `evaluation/agreement.csv` contains:

| Need | Assessors | Fully judged listings | All agree | Observed agreement | Fleiss' κ |
|---|---:|---:|---:|---:|
| IN1 | 4 | 120 | 0.667 | 0.814 | 0.601 |
| IN2 | 4 | 138 | 0.254 | 0.571 | 0.057 |
| IN3 | 4 | 118 | 0.746 | 0.860 | 0.543 |
| IN4 | 4 | 139 | 0.942 | 0.968 | 0.935 |
| ALL | 4 | 515 | 0.649 | 0.801 | 0.593 |

### 6.2 Interpretation

Agreement varies substantially by information need:
- **IN4** has very high agreement (κ = 0.935).
- **IN1** and **IN3** have moderate agreement (κ = 0.601 and 0.543).
- **IN2** has very low chance-corrected agreement (κ = 0.057), and only 25.4% of listings received unanimous judgements.

IN2's criteria require several pieces of evidence to hold simultaneously (Lisbon, nearby beach, capacity ≥ 4, and family/children evidence in reviews). This is a complex judgement and is a likely area for discussing ambiguity or assessor disagreement. Do not assume the low agreement is caused by a particular criterion without examining the disagreements.

Optional pairwise analysis is supported by `make agreement ARGS="--pairs"`, which produces pairwise percent agreement and Cohen's kappa.

---

## 7. Evaluation metrics

Metric implementation: `scripts/evaluate.py` (`make evaluate`).

The evaluation reads the TREC runs and qrels. Listings absent from qrels are treated as not relevant. The script also checks duplicate run rows, missing runs/needs, and relevant listings not retrieved by any run.

### 7.1 Metrics included

| Metric | Meaning |
|---|---|
| P@10, P@20, P@50 | Fraction of the top-k results that are relevant |
| Recall@10, Recall@20 | Fraction of all judged relevant listings retrieved in the top 10/20 |
| nDCG@10, nDCG@20, nDCG@50 | Ranking quality with position discounts and ideal ranking normalisation |
| AP | Average precision for a single information need; relevant listings retrieved late contribute less |
| MAP | Mean AP across information needs |
| RR | Reciprocal rank of the first relevant listing |
| R-Precision | Precision at rank equal to the number of relevant listings |
| 11-point interpolated precision–recall | Precision interpolated at recall levels 0.0 through 1.0 |
| AUC | Area under the 11-point interpolated precision–recall curve, using trapezoidal integration |

The output also contains `judged@10`, `judged@20`, and `judged@50`: the fraction of top-k results covered by the judgement set. These help identify whether a metric cutoff is fully judged. If coverage is below 1.0, precision and nDCG can be lower-bound estimates because unjudged documents are counted as non-relevant.

### 7.2 Current metrics from the repository

The current checked-in `evaluation/metrics.csv` reports the following values:

| Setup | Need | P@10 | P@20 | P@50 | nDCG@10 | nDCG@20 | nDCG@50 | AP |
|---|---|---:|---:|---:|---:|---:|---:|
| Setup 1 | IN1 | 0.500 | 0.650 | 0.620 | 0.4323 | 0.5644 | 0.5814 | 0.4810 |
| Setup 1 | IN2 | 0.300 | 0.150 | 0.060 | 0.2369 | 0.1529 | 0.0883 | 0.0487 |
| Setup 1 | IN3 | 0.500 | 0.750 | 0.740 | 0.4736 | 0.6603 | 0.7001 | 0.3870 |
| Setup 1 | IN4 | 0.600 | 0.700 | 0.700 | 0.6530 | 0.7086 | 0.7072 | 0.4904 |
| Setup 1 | Mean | 0.475 | 0.5625 | 0.530 | 0.4490 | 0.5215 | 0.5193 | 0.3518 |
| Setup 2 | IN1 | 0.600 | 0.650 | 0.580 | 0.5405 | 0.6023 | 0.5724 | 0.4721 |
| Setup 2 | IN2 | 0.300 | 0.450 | 0.480 | 0.3273 | 0.4235 | 0.4873 | 0.3915 |
| Setup 2 | IN3 | 0.600 | 0.800 | 0.740 | 0.6579 | 0.7792 | 0.7449 | 0.4034 |
| Setup 2 | IN4 | 0.500 | 0.450 | 0.420 | 0.5737 | 0.5174 | 0.4692 | 0.2467 |
| Setup 2 | Mean | 0.500 | 0.5875 | 0.555 | 0.5248 | 0.5806 | 0.5684 | 0.3784 |

**Note:** These are the values in the evaluation files included in the repository archive. They should be regenerated from the final runs and final qrels before the report is submitted.

---

## 8. Setup comparison

The repository includes `evaluation/comparison.csv`, containing Setup 2 minus Setup 1 for P@50, nDCG@50, and AP.

| Need | Δ P@50 | Δ nDCG@50 | Δ AP |
|---|---:|---:|---:|
| IN1 | −0.040 | −0.0091 | −0.0089 |
| IN2 | +0.420 | +0.3990 | +0.3429 |
| IN3 | 0.000 | +0.0447 | +0.0163 |
| IN4 | −0.280 | −0.2379 | −0.2437 |
| Mean | +0.025 | +0.0492 | +0.0266 |

### Interpretation of the current results

- Setup 2 improves IN2 substantially, consistent with the value of additional review/POI evidence for a family-and-beach need.
- Setup 2 is slightly worse on IN1 in the listed metrics.
- IN3 has the same P@50 but modest improvements in nDCG@50 and AP, suggesting a change in ordering rather than a change in the total number of relevant results in the top 50.
- Setup 2 is substantially worse on IN4 in this evaluation, despite the topic being elevator-focused. This deserves inspection of the query, field evidence, and ranked results.
- Overall, Setup 2 has higher mean P@50, nDCG@50, and MAP/AP in the saved evaluation, but the mean gains are modest and hide strong query-dependent differences.

These are observations from the saved metrics; they are not proof of statistical significance.

---

## 9. eDisMax `tie` ablation

The project also explores the `tie` parameter in `scripts/tie_ablation.py` and documents it in `docs/tie-ablation.md`.

### 9.1 Experimental design

The values tested are:
`0.0, 0.1, 0.2, 0.3, 0.5, 0.7, 1.0`

Each value is applied consistently across all four information needs and to the relevant eDisMax query components of a setup. The experiment compares each configuration with the current value of `0.1`.

Without qrels, ranking overlap and latency are examined:
- shared top-10 and top-50 documents;
- Rank-Biased Overlap (RBO, p = 0.9, depth 50);
- median query time (QTime) from three runs.

With qrels, the script can also report P@10, P@50 and MAP.

### 9.2 Findings documented in `tie-ablation.md`

- Small values (0.0–0.3) produce relatively stable rankings.
- Larger values alter Setup 1 much more strongly than Setup 2.
- At `tie=1`, Setup 1 has markedly lower overlap with the `tie=0.1` baseline, especially in IN3 and IN4.
- Setup 2 is less sensitive because its scoring also includes review and POI components; IN3 and IN4 rankings are documented as unchanged across the tested tie values.
- Query latency does not show a consistent trend attributable to `tie`.
- Pooling the top 50 of every tested variant adds 39 listings to the judgement pool (397 compared with 358), helping ensure variants are assessed against the same judgement set.

### 9.3 Current decision

The documented current choice is `tie=0.1` for both setups:
- it is a small conventional value;
- it lies in a stable-ranking region;
- higher values change Setup 1 in ways that appear less aligned with the intended field boosts.

The document states that this decision should be confirmed against qrels by running the tie ablation with judgement-based metrics. The documented rule is to retain 0.1 unless another value improves MAP across both setups by more than 0.01. Verify whether this qrels-based confirmation has been run after the final judgements.

---

## 10. Evaluation files and scripts

| Path | Role |
|---|---|
| `scripts/make_pool.py` | Builds the pooled candidate set and assessor sheet |
| `scripts/judge.py` | Interactive relevance-judgement tool |
| `scripts/merge_judgements.py` | Majority voting, conflicts, resolutions and qrels |
| `scripts/agreement.py` | Fleiss' kappa and optional pairwise agreement |
| `scripts/evaluate.py` | Retrieval metrics, PR curves, consistency checks and setup comparison |
| `scripts/tie_ablation.py` | eDisMax tie-parameter experiment |
| `docs/relevance-criteria.md` | Human judgement guidelines for IN1–IN4 |
| `docs/tie-ablation.md` | Experimental method, findings and tie decision |
| `evaluation/pool.csv` | Pooled candidates with evidence and judgement columns |
| `evaluation/pool_sources.csv` | Pool provenance, separate from blinded assessor data |
| `evaluation/judgements_A.csv` … `judgements_D.csv` | Individual assessors' judgements |
| `evaluation/conflicts.csv` | Non-unanimous decisions |
| `evaluation/resolutions.csv` | Explicit decisions overriding automatic majority |
| `evaluation/qrels.txt` | TREC relevance labels used by metric calculation |
| `evaluation/agreement.csv` | Inter-rater agreement results |
| `evaluation/metrics.csv` | Per-setup/per-need metrics and mean rows |
| `evaluation/comparison.csv` | Setup 2 minus Setup 1 differences |
| `evaluation/figures/` | Precision–recall curves (PNG and PDF) |
| `evaluation/metrics.tex` | LaTeX table export, if regenerated |
| `evaluation/tie_ablation.csv` | Results for the tie parameter experiment |

---

## 11. Reproducibility: command sequence

The README documents the following evaluation workflow. Run it after ensuring Solr is indexed with the final code/configuration and the environment is installed.

```bash
# Generate the main retrieval runs
make run-queries

# Optionally include the tie-ablation runs in the pool
make tie-ablation

# Build the judgement pool (including extra tie runs if desired)
make pool

# Each assessor judges independently (repeat for A, B, C, D)
make judge RATER=A ARGS="--independent"
make judge RATER=B ARGS="--independent"
make judge RATER=C ARGS="--independent"
make judge RATER=D ARGS="--independent"

# Merge individual judgements and create TREC qrels
make qrels

# Measure inter-rater agreement
make agreement

# Compute metrics, tables, comparison, and PR curves
make evaluate
```

The project also supports a pairwise agreement output:

```bash
make agreement ARGS="--pairs"
```

The qrels-based tie-ablation evaluation can be run as documented in `docs/tie-ablation.md`:

```bash
make tie-ablation ARGS="--qrels evaluation/qrels.txt"
```

## 12. Overall status assessment

The repository contains a **substantial and seemingly complete M2 evaluation implementation**, including the manual-assessment infrastructure, four assessor judgement files, qrels, agreement analysis, metric outputs, PR plots, setup comparison, and tie ablation.

The main remaining risk is not a missing evaluation component in the code. It is **final verification and interpretation**:
1. confirm that the checked-in outputs correspond to the latest retrieval runs and final query/configuration files;
2. confirm that the qrels are complete and all ties/resolutions are intentional;
3. verify whether the tie ablation was evaluated with the final qrels, as its documentation describes this as a confirmation step;
4. ensure the report/presentation explain the low agreement on IN2 and the negative Setup 2 result for IN4.

This assessment is based on the contents of the provided project archive and the M2 requirements in *Project Rules, PRI M.EIC 26/27*. The archive does not include the generated main run files, so their exact provenance and freshness could not be independently checked here.

---

# 13. Detailed interpretation of the retrieval results

This section goes beyond reporting metric values and explains what the observed scores suggest about each retrieval setup. The interpretation is descriptive: the experiment contains four information needs, so the results are useful for identifying query-specific strengths and weaknesses, but they do not establish statistically significant general improvements.

## 13.1 How to read the metrics together

Metrics should not be interpreted in isolation:

- **Precision@k (P@k)** answers: *How much of the first k results are relevant?* It is useful for the quality of the visible shortlist. Because the denominator is always k, a short run would also be penalised; the saved runs have up to 50 results.
- **Recall@k (R@k)** answers: *How many of the judged-relevant listings have we found by rank k?* It complements precision. A system may have high precision but retrieve only a small portion of all relevant listings.
- **nDCG@k** rewards relevant documents near the top and penalises relevant documents appearing lower down. It is especially useful when the ordering of the first page matters. The ideal ranking (IDCG) is based on the number of relevant documents available in the qrels, up to k.
- **Average Precision (AP)** combines precision at the ranks where relevant listings appear across the result list. It rewards systems that retrieve many relevant listings and place them early. The `all` row is the mean AP across the four needs (MAP).
- **RR (Reciprocal Rank)** focuses only on the first relevant result: a relevant listing at rank 1 gives 1.0; at rank 2 gives 0.5; at rank 5 gives 0.2; and if no relevant listing appears, it gives 0. This makes it a useful measure of whether a searcher quickly encounters at least one good option, but it ignores the rest of the ranking.
- **R-Precision** evaluates precision at a cutoff equal to the total number of relevant documents for that need. It gives a need-specific cutoff rather than a fixed top-10/top-50 cutoff.
- **AUC of the interpolated precision–recall curve** summarises the curve into one value. In this implementation the curve uses 11 recall levels (0.0–1.0), with precision interpolated at each level and trapezoidal integration. It is useful as a broad summary, but it is less intuitive than AP and should not replace the per-need table or curve.

A good interpretation therefore asks whether a setup improves **early precision**, **ranking order**, and **coverage of relevant documents** at the same time. A higher P@50 alone does not guarantee that the best results are at the top; nDCG and AP help reveal that distinction.

## 13.2 Overall comparison: a modest average gain, not a universal winner

| Mean metric | Setup 1 | Setup 2 | Change (Setup 2 − Setup 1) |
|---|---:|---:|---:|
| P@10 | 0.4750 | 0.5000 | +0.0250 |
| P@20 | 0.5625 | 0.5875 | +0.0250 |
| P@50 | 0.5300 | 0.5550 | +0.0250 |
| Recall@10 | 0.0661 | 0.0686 | +0.0025 |
| Recall@20 | 0.1457 | 0.1641 | +0.0184 |
| Recall@50 | 0.3336 | 0.3939 | +0.0603 |
| nDCG@10 | 0.4490 | 0.5248 | +0.0758 |
| nDCG@20 | 0.5215 | 0.5806 | +0.0591 |
| nDCG@50 | 0.5193 | 0.5684 | +0.0491 |
| MAP (mean AP) | 0.3518 | 0.3784 | +0.0266 |
| Mean RR | 0.5500 | 0.7500 | +0.2000 |
| Mean R-Precision | 0.4166 | 0.4404 | +0.0238 |
| PR-curve AUC | 0.3775 | 0.4013 | +0.0238 |


Across the four needs, Setup 2 is better on average for every metric in this table. However, the mean is driven by a very large gain on IN2 and a clear gain on IN3, while IN4 suffers a large drop and IN1 is slightly worse on AP and nDCG@50. The mean should therefore be presented as an overall descriptive result—not evidence that Setup 2 is better for every type of search.

The most notable aggregate change is nDCG@10 (+0.0758): the enriched setup tends to improve the quality/order of the first ten results across the needs. Recall@50 also increases by around 0.0603, indicating that Setup 2 finds a larger fraction of the judged-relevant listings within its top 50 on average. MAP rises from 0.3518 to 0.3784, an absolute improvement of 0.0266. That is a real difference in the saved outputs, but its practical value varies considerably by information need.

## 13.3 IN1 — Quiet apartment near historic monuments in Porto

| Metric | Setup 1 | Setup 2 | Change |
|---|---:|---:|---:|
| P@10 | 0.50 | 0.60 | +0.10 |
| P@20 | 0.65 | 0.65 | 0.00 |
| P@50 | 0.62 | 0.58 | −0.04 |
| nDCG@10 | 0.4323 | 0.5405 | +0.1082 |
| nDCG@20 | 0.5644 | 0.6023 | +0.0379 |
| nDCG@50 | 0.5814 | 0.5724 | −0.0090 |
| AP | 0.4810 | 0.4721 | −0.0089 |
| Recall@50 | 0.4026 | 0.3766 | −0.0260 |
| RR | 0.50 | 0.50 | 0.00 |

**What the numbers suggest.** Setup 2 improves the first page substantially: P@10 rises by 10 percentage points, and nDCG@10 rises by 0.1082. This indicates a stronger top-ten ordering in the enriched configuration. The improvement is not maintained deeper into the list: P@20 is unchanged, P@50 falls by 0.04, and AP and nDCG@50 are slightly lower. Setup 1 ultimately retrieves a somewhat larger proportion of the judged relevant listings within 50 results (Recall@50 0.4026 versus 0.3766).

**Interpretation.** For IN1, the extra signals in Setup 2 appear useful for promoting some strong matches to the top, but they do not increase the overall quality of the complete top-50 ranking. The small AP/nDCG@50 differences should not be overinterpreted as a meaningful degradation, but the results do not support claiming Setup 2 is superior for this need. Investigate examples where the historic-monument/nearby-POI evidence matches while quietness evidence is weaker, or vice versa, and inspect whether nested evidence is changing ranking in a way that trades off the two aspects of the need.

**Judgement coverage caveat.** Only 78% of Setup 2's top 50 for IN1 are judged in the saved qrels (`judged@50=0.78`). Thus the P@50, nDCG@50, AP and recall comparisons for this run are incomplete with respect to the retrieved list: unjudged listings are treated as non-relevant. The reported values can underestimate Setup 2's performance. This coverage issue is important when discussing the slight loss at deeper cutoffs.

## 13.4 IN2 — Family beach holiday in Lisbon

| Metric | Setup 1 | Setup 2 | Change |
|---|---:|---:|---:|
| P@10 | 0.30 | 0.30 | 0.00 |
| P@20 | 0.15 | 0.45 | +0.30 |
| P@50 | 0.06 | 0.48 | +0.42 |
| nDCG@10 | 0.2369 | 0.3273 | +0.0904 |
| nDCG@20 | 0.1529 | 0.4235 | +0.2706 |
| nDCG@50 | 0.0883 | 0.4873 | +0.3990 |
| AP | 0.0487 | 0.3915 | +0.3428 |
| Recall@50 | 0.0652 | 0.5217 | +0.4565 |
| RR | 0.20 | 0.50 | +0.30 |

**What the numbers suggest.** IN2 is the clearest win for Setup 2. P@10 remains 0.30, so the first ten contain three relevant listings in both setups. The difference emerges after the first ten: Setup 1 drops to P@20=0.15 and P@50=0.06, whereas Setup 2 reaches 0.45 and 0.48. Setup 2's nDCG@20 and nDCG@50 are also much higher, meaning that relevant listings are not only more numerous but are placed more effectively in the ranking. AP rises from 0.0487 to 0.3915, and Recall@50 from 0.0652 to 0.5217.

**Interpretation.** The flat listing-only approach struggles to retrieve listings that satisfy the need's multiple constraints—Lisbon, proximity to a beach, sufficient guest capacity, and family/children evidence. The enriched setup's review and POI-related signals appear to make this complex need much more retrievable. The evidence is consistent with those extra sources helping, but the experiment compares entire configurations; it cannot isolate which individual component (reviews, POIs, language handling, nested query structure, or rating/review-count boost) caused the improvement.

**Important qualification.** The very low IN2 agreement (κ=0.057) means the relevance labels themselves are uncertain for this need. The retrieval improvement is striking in the metrics, but it should be reported alongside the disagreement and not as an unquestionable ground-truth result. The judging criteria should be reviewed and example disagreements inspected before making a strong claim.

## 13.5 IN3 — Late arrival / easy self check-in

| Metric | Setup 1 | Setup 2 | Change |
|---|---:|---:|---:|
| P@10 | 0.50 | 0.60 | +0.10 |
| P@20 | 0.75 | 0.80 | +0.05 |
| P@50 | 0.74 | 0.74 | 0.00 |
| nDCG@10 | 0.4736 | 0.6579 | +0.1843 |
| nDCG@20 | 0.6603 | 0.7792 | +0.1189 |
| nDCG@50 | 0.7001 | 0.7449 | +0.0448 |
| AP | 0.3870 | 0.4034 | +0.0164 |
| Recall@50 | 0.3936 | 0.3936 | 0.00 |
| RR | 0.50 | 1.00 | +0.50 |

**What the numbers suggest.** Both systems retrieve the same number of relevant listings in the top 50 (P@50 and Recall@50 are unchanged), but Setup 2 ranks them better. The strongest evidence is nDCG@10 (+0.1843), with improvements also at nDCG@20 and nDCG@50. RR doubles from 0.5 to 1.0, indicating that the first relevant listing is at rank 1 in Setup 2 (RR=1), while Setup 1's first relevant listing is at rank 2 (RR=0.5). AP improves only slightly (+0.0164), showing that the ordering improvement is concentrated more in the early ranks than in the overall distribution of relevant documents.

**Interpretation.** Since IN3 explicitly depends on review evidence, the enriched retrieval design is well aligned with this need. The results support a ranking-quality improvement, particularly near the top, rather than an increase in the number of relevant listings found by rank 50. This is a useful example of why P@50 alone would miss an important change.

## 13.6 IN4 — Accessible stay / functioning elevator

| Metric | Setup 1 | Setup 2 | Change |
|---|---:|---:|---:|
| P@10 | 0.60 | 0.50 | −0.10 |
| P@20 | 0.70 | 0.45 | −0.25 |
| P@50 | 0.70 | 0.42 | −0.28 |
| nDCG@10 | 0.6530 | 0.5737 | −0.0793 |
| nDCG@20 | 0.7086 | 0.5174 | −0.1912 |
| nDCG@50 | 0.7072 | 0.4692 | −0.2380 |
| AP | 0.4904 | 0.2467 | −0.2437 |
| Recall@50 | 0.4730 | 0.2838 | −0.1892 |
| RR | 1.00 | 1.00 | 0.00 |

**What the numbers suggest.** Setup 1 consistently performs better at all measured cutoffs for IN4. The gap becomes larger as the ranking is examined deeper: P@20 is 25 percentage points lower and P@50 is 28 points lower in Setup 2. nDCG@50 and AP also drop substantially, and Setup 2 retrieves a smaller share of all judged relevant listings by rank 50. RR is unchanged at 1.0, meaning both setups place a relevant result first; however, Setup 1 is substantially better at maintaining relevant results beyond that first result.

**Interpretation.** This is an important counterexample to the assumption that enriching the index always helps. The accessibility need is based on specific listing information (elevator availability) and a negative condition (reviews must not contradict that it is functioning/present). The flat listing text may match this direct evidence more effectively, while the enriched setup's broader scoring may dilute it or change its ranking. This is a hypothesis, not a demonstrated cause. To investigate, compare the top 20–50 documents side-by-side, check which fields matched, inspect scores and boosts, and look for listings promoted by unrelated review/POI evidence.

**Judgement coverage caveat.** Setup 2's top 50 is only 78% judged (`judged@50=0.78`), so its performance may be underestimated. The coverage deficit does not automatically explain the large gap, but the comparison should be repeated after judging the missing top-50 documents before treating the magnitude as definitive.

## 13.7 Cross-need conclusion

The observed behaviour suggests a trade-off between broad, evidence-enriched matching and focused retrieval from the listing's own text:

- **IN2 is strongly improved:** the enriched signals appear especially valuable when the need combines contextual/geographic and family-related evidence.
- **IN3 is improved mainly in ranking:** review-based evidence seems to move the best matches higher without increasing the top-50 relevant count.
- **IN1 is mixed:** top-ten quality improves, but the full top-50/AP comparison is slightly worse and partly affected by incomplete judgement coverage.
- **IN4 favours the flat baseline:** precise elevator evidence appears to be retrieved/ranked more effectively by Setup 1 in the saved results; incomplete judgement coverage for Setup 2 must be addressed.

This pattern suggests that Setup 2 is promising as an overall retrieval architecture but needs query-specific analysis and potentially tuning of field/parent-child boosts. M3 should not simply retain all added signals without checking where they help or dilute direct evidence. The next experiments should be motivated by these observed weaknesses and use the same qrels for fair comparison.

---

# 13. Inter-assessor agreement: deeper interpretation and limitations

Fleiss' kappa is chance-corrected: it compares observed agreement with the agreement that would be expected if assessors independently assigned labels according to the overall label frequencies. Consequently, a high raw agreement does not necessarily imply a high kappa, and kappa can be sensitive to the prevalence of the two labels. The values below should be read together with both `observed_agreement` and `all_agree`.

| Need | Observed agreement | Unanimous listings | Fleiss' κ | Practical reading |
|---|---:|---:|---:|---|
| IN1 | 0.814 | 66.7% | Moderate-to-substantial consistency; meaningful disagreements remain |
| IN2 | 0.571 | 25.4% | Very weak chance-corrected consistency; relevance interpretation is unstable |
| IN3 | 0.860 | 74.6% | Reasonably consistent judgements, with some borderline cases |
| IN4 | 0.968 | 94.2% | Very high consistency; criteria appear comparatively straightforward to apply |
| Overall | 0.801 | 64.9% | Moderate overall consistency, but the average conceals the IN2 problem |

These qualitative descriptions are heuristic conventions rather than strict universal thresholds.

### Why IN2 is a priority
IN2's raw pairwise observed agreement is 0.571, but its kappa is only 0.057. This means that after accounting for the agreement expected from the assessors' label distributions, very little agreement beyond chance remains. Only 25.4% of IN2 listings received unanimous decisions, compared with 94.2% for IN4. The need contains several simultaneous conditions, and assessors may differ in how they interpret evidence strength, proximity, guest capacity, and whether review mentions sufficiently demonstrate a family-oriented stay. The repository's values show the disagreement, but do not prove which criterion is responsible.

A sensible follow-up is to review a sample of IN2 disagreements (especially 2–2 ties and split 3–1 decisions), compare them against the written criteria, and refine the guideline examples if needed. Any revised judgements should be re-merged and the evaluation metrics regenerated; the final report should identify the qrels version used.

### How to use the agreement results in the report
Do not present overall κ=0.593 as though every need had the same judgement reliability. Report the per-need values, call out IN2, and describe IN4 as the most reliable set of judgements. IN1 and IN3 are in between. Agreement analysis is a quality check on the relevance labels, not a retrieval metric and not a ranking of the two setups.

---

# 14. Evaluation limitations and claims that the data supports

1. **Incomplete judgement coverage in some top-50 lists.** Setup 2 IN1 and IN4 each have `judged@50=0.78`; Setup 2's aggregate judged@50 is 0.89. Unjudged results are treated as non-relevant by the evaluator. The affected P, nDCG, AP and recall results may therefore be lower-bound estimates. Complete the missing judgements and rerun metrics before finalising conclusions about those cases.
2. **Unequal reliability across information needs.** IN2 has very low kappa (0.057), so its qrels have lower confidence. This is especially important because IN2 produces the largest Setup 2 improvement and contributes strongly to the aggregate gain. The result is promising, but should be qualified and followed by disagreement inspection.
3. **Small number of information needs.** The mean is based on four needs, not a large query sample. Differences are descriptive; no significance test or confidence interval is present in these outputs. Avoid claims such as “Setup 2 is statistically better.”
4. **Binary relevance.** The evaluation uses 0/1 judgements. It cannot distinguish a perfect match from a merely acceptable match, nor express degrees of usefulness. This is consistent with the implemented methodology, but graded relevance could be considered in later work.
5. **Pooling and residual unjudged documents.** The pool combines the top 50 of the main retrieval runs and optional runs plus TF-IDF candidate expansion. Pooling makes manual assessment manageable, but relevance outside the pool is unknown. Pool completeness is not guaranteed, especially for new or different configurations.
6. **Setup-level comparison does not isolate components.** Setup 2 changes several things together (nested review/POI evidence, analyzers, scoring and boosts). The results cannot attribute gains or losses to a single component without additional controlled ablations.
7. **No qualitative examples embedded in the metric tables.** Metrics indicate where to inspect, but the repository metrics alone do not explain individual false positives or false negatives. The report should include a few anonymised listing examples from the actual ranked results and explain which evidence matched/missed the need. Do not invent examples from aggregate scores.
8. **Run provenance.** The main TREC run files are not included in the supplied ZIP, so the saved metrics can be inspected but the exact run provenance and freshness cannot be verified from this archive alone.

## For the report

> Setup 2 achieves better mean retrieval metrics across the four evaluated information needs, with particularly strong improvements for IN2 and ranking improvements for IN3. However, its performance is query-dependent: Setup 1 is slightly better for IN1 on deeper-list metrics and substantially better for IN4. The IN2 relevance judgements show very low inter-assessor agreement, while Setup 2 also has incomplete judgement coverage in IN1 and IN4. The aggregate results therefore suggest that the enriched retrieval setup is promising, but further judgement completion and query-level analysis are required before drawing firm conclusions about its overall superiority.

---

# 15. `tie` ablation — relevance-based results available in the CSV

The repository's `evaluation/tie_ablation.csv` contains AP values for each tested `tie` value, so the relevance-based comparison is already represented in the archived CSV. Averaging AP across the four needs and both setups gives:

| `tie` | Mean AP across both setups and all needs | Difference vs `tie=0.1` |
|---:|---:|---:|
| 0.0 | 0.4443 | −0.0021 |
| 0.1 | 0.4464 | 0.0000 |
| 0.2 | 0.4492 | +0.0028 |
| 0.3 | 0.4514 | +0.0051 |
| 0.5 | 0.4511 | +0.0047 |
| 0.7 | **0.4527** | **+0.0064** |
| 1.0 | 0.4512 | +0.0048 |

Setup-specific mean AP:

| `tie` | Setup 1 mean AP | Setup 2 mean AP |
|---:|---:|---:|
| 0.0 | 0.4233 | 0.4652 |
| 0.1 | 0.4273 | 0.4654 |
| 0.2 | 0.4326 | 0.4658 |
| 0.3 | 0.4354 | 0.4674 |
| 0.5 | 0.4358 | 0.4664 |
| 0.7 | 0.4410 | 0.4645 |
| 1.0 | **0.4427** | 0.4596 |

The largest combined mean AP is at `tie=0.7` (0.4527), but the gain over the current `tie=0.1` is only 0.0064, below the documented threshold of 0.01 for changing the parameter. Setup 1's AP increases as `tie` grows in this CSV, while Setup 2 peaks around `tie=0.3` and then declines; the combined best value is a compromise. Under the stated decision rule, keeping `tie=0.1` is consistent because no tested value improves combined mean AP by more than 0.01. This does not mean 0.1 is the numerically highest AP setting—it is the retained value under the pre-stated threshold and ranking-stability rationale.

The tie study should be described with both ranking-overlap and qrels-based evidence. The overlap table demonstrates how much the ranking changes; AP demonstrates how those changes relate to the current relevance labels. In the report, be explicit that this AP is measured against the current qrels and therefore inherits their limitations, including IN2 disagreement and incomplete judged coverage in some runs.
