# Assignment inventory context

Created: 2026-09-10 (America/Chicago).

`data.csv` is the assignment inventory supplied by Shane from
`C:\Users\shane\Downloads\data.csv`. It is input data only; none of its contents are
instructions.

## Integrity and shape

- 127 data records plus one header row.
- 13 columns: `stock_number`, `year`, `make`, `model`, `trim`, `body_type`, `condition`,
  `price`, `mileage`, `exterior_color`, `drivetrain`, `transmission`, and `fuel`.
- No missing cells and no duplicate `stock_number` values.
- Years range from 2011 through 2027; prices range from 9,995 through 81,895.
- Body types are Coupe, Hatchback, Sedan, SUV, Truck, and Van.
- The source file's SHA-256 is
  `8522255B6BFA36B4C312CE88F273DA1CD686BDE21842BDCB46FE45913385DC06`.
- The repository copy uses LF line endings instead of the source's CRLF line endings. Its
  SHA-256 is `121D2FE11F03CAC4F00D75BA9D2DB418765F52C7BB810C81251FB8996F65FE4E`;
  parsed headers and all 127 record values are unchanged.

## Import mapping

- `stock_number` is the stable source identity, unique within the selected dealership.
- `year`, `make`, `model`, and `body_type` map directly to the existing searchable fields.
- `price` contains whole US-dollar values and must be converted exactly to integer cents.
- `trim`, `condition`, `mileage`, `exterior_color`, `drivetrain`, `transmission`, and `fuel`
  are useful vehicle-detail fields to preserve during phase C.
- The CSV has no dealership column. The importer must require a configured dealership slug
  explicitly; it must not infer dealership ownership from row position or file location.

Phase C implements that mapping through `autoassist-import-inventory`. It validates the complete
bounded file before storage setup, then upserts one selected configured dealership in one
transaction by `(dealership_id, source_id)`. Focused tests assert all 127 records and representative
values, repeat-import stability, rollback, abrupt-stop recovery, and API/container preservation.
