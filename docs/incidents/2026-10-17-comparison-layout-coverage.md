# Comparison layout coverage and metric identity

Date: 2026-10-17
Status: focused remediation accepted in two independent review iterations

Whole-issue visual reconciliation found three complete comparison-table source
occurrences missing from the parser plan. The additive layout parser accepted
only ungrouped market capitalization values and rejected the printed European
thousands grouping. It also assigned its fixed valuation slots to the supported
forecast year without reading the source header's metric identity and year.
The private reviewer import remained on hold throughout remediation.

The layout parser now accepts strictly grouped decimal market capitalization
and consumes the exact number of ordered valuation slots declared by the
header. Metric names and explicit adjacent years must have unambiguous column
alignment. Unsupported years and book-value metrics remain blank in supported
workbook fields. An ambiguous year leaves valuation fields blank with a
diagnostic note. Supported year values retain their source metric identity.
Numeric market capitalization is preserved by both the pattern and converter.

Controlled recommendation remainders prevent missing or extra numeric columns
from shifting into a recommendation or another metric. Malformed grouping,
missing valuation slots and extra valuation slots are rejected. Primary embedded
text remains authoritative and layout recovery remains additive.

Synthetic regressions cover grouped capitalization, optional dividend columns,
one or two declared valuation slots, supported and unsupported forecast years,
book-value headers, unaligned years, malformed grouping, and missing/extra
metrics with signed or unsigned performance. Source PDFs, row values, renders
and candidate inventories remain ignored and private.

Transfer classification is local parser coverage. The existing whole-issue
reconciliation workflow caught both coverage and semantic identity failures
before live replacement; no new workspace policy is required.

The extraction review confirmed exact source equality for the three recovered
rows and blank supported-year fields for the later-year source metrics. The
privacy review found one additional ambiguity: duplicate supported valuation
identities could overwrite each other. Those fields now remain blank with an
ambiguity note. Synthetic duplicate-metric tests also prove that a supported
year can coexist with a different unsupported year without losing the supported
value. Both final review dispositions passed with no required findings.

The wrapped historical issue token advisory is accepted: an unbound token stays
blank rather than being attributed by proximity. Developer and primary each
passed compile, all 369 repository tests and the diff check. The rebuilt private
plan's bytes are unchanged by the duplicate-identity safeguard. Live draft
import, SEC refresh and cache replay remain pending operational gates. See
[the review record](../reviews/2026-10-17-comparison-layout-coverage.md).
