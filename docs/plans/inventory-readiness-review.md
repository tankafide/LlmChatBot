# Inventory readiness and test-gap diagnosis

Reviewed 2026-09-11 (America/Chicago). Diagnosis only; no application/database changes.

## Implemented versus deployed

The real assignment CSV parser/importer, expanded vehicle model, relational search,
detail lookup, and durable chat are implemented. Existing import tests validate 127
assignment records, CLI import, AA-1001 details, and persistence across app recreation.
The browser integration smoke explicitly imports that CSV into temporary storage.

The running development database was observed to have zero vehicle rows and the older
11-column vehicle table. Current queries also require trim, condition, mileage,
exterior_color, drivetrain, transmission, and fuel. This establishes an unprepared
development database; it does not establish that the importer was never run against
some other database. Compose startup does not import the CSV. Database recreation on
schema change is an explicit manual prerequisite; automatic migrations were excluded.

## Findings

1. **Startup accepts an incompatible schema.** `db/database.py:48` calls
   `Base.metadata.create_all`, which creates missing tables but does not update existing
   columns. `check_storage` at line 52 queries only `Vehicle.id`. An old vehicle table
   therefore passes startup and health. Add explicit required-schema validation with
   an actionable recreation message; this requires no migration framework.
2. **Tool database failures are mislabeled as provider failures.** The broad catch in
   `chat/grounded.py:329` encloses the agent run, including application tool execution.
   It converts an inventory OperationalError to ChatProviderError, which the lifecycle
   service persists as a 502 provider_error. Distinguish provider, tool/application,
   and storage failures while preserving terminal settlement and sanitized diagnostics.
3. **The development launch was not verified as an inventory-ready demonstration.**
   The frontend delivery verified healthy containers and dealership discovery, but
   those observations did not prove current schema or imported development inventory.
   Fresh isolated acceptance tests are correct; they do not provision or certify the
   separate persistent development volume. The delivery overstated readiness.

The stock-number clarification sentence is an application-rendered response for the
model's clarify intent. Its appearance alone is not evidence of a database search or
working inventory. Empty inventory is allowed by current setup design and should be
distinguished from the missing-column exception that caused these failed turns.

## Why the tests passed

- Import and browser fixtures create the current schema and import the CSV explicitly.
  Restart checks reopen a database created by the same current code, not an older schema.
- `test_schema_defects_propagate_instead_of_becoming_storage_503` drops the whole vehicle
  table for the health case. For missing trim, it tests search/detail endpoints only.
  Thus it misses an existing table with missing columns passing startup/health.
- Direct inventory-route error tests bypass PydanticChatRunner's exception wrapper.
  The same SQL error has a different classification when raised by an LLM tool.
- Mocked frontend 502 tests correctly prove failed-turn display, but cannot establish
  that a backend 502 was caused by an actual provider error.

## Reproduction and validation

An inline diagnostic created a temporary SQLite database, removed only vehicles.trim,
closed the first app and started another. Observed: startup succeeded; health returned
200; inventory query raised OperationalError with `no such column: vehicles.trim`.
A deterministic FunctionModel requested the real search_inventory tool on that
database: the runner raised ChatProviderError whose cause was that OperationalError.
No live model/network access or development database writes were involved.

Focused pytest run: real CSV mapping, CLI import/detail persistence, and all four
existing schema-defect cases: **6 passed**, one upstream deprecation warning.

## Smallest regression coverage to add with fixes

- Start against a temporary old-shaped vehicle table; require startup/readiness to
  reject it clearly, without deleting or modifying existing user data.
- Execute a real inventory tool via a deterministic model with a missing-column
  database and with expected storage contention; assert correct classification and
  durable request settlement, not provider_error for local SQL defects.
- Verify a documented setup/preflight flow separately from unit tests: schema current,
  assignment inventory imported, and an inventory-backed query succeeds. Keep tests
  isolated; do not point pytest at the development volume.

Recreate/reimport the intended development database only through an explicitly
authorized reset, preserving a backup if existing conversations should be retained.
