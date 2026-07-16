# Semantic Registry and QueryPlan

[← README](../README.md) · [Architecture](architecture.md)

The runtime query path is deliberately separated into four deterministic
layers:

1. `dbt manifest.json` and `semantic_manifest.json` provide physical models,
   dimensions, measures, metrics, and default time dimensions.
2. `ontology.yml` is an overlay for business entities, property-to-column
   mappings, relationship cardinality, and display metadata.
3. `SemanticRegistry` validates and combines those sources. Generate the
   inspectable artifact after dbt parsing with:

   ```powershell
   python scripts/build_semantic_registry.py
   ```

4. `QueryPlan` is the only accepted query representation. The compiler turns a
   validated plan into PostgreSQL SQL; LLMs never supply executable SQL.

## Query modes

`metric_analysis` compiles metrics, dimensions, filters and time ranges from a
single semantic model. Scalar metrics from several models are pre-aggregated in
separate CTEs before a `CROSS JOIN`, preventing fact-table fan-out.

`entity_analysis` starts from an ontology entity and follows validated forward
or reverse relationships. Denormalized relationships reuse their source alias
and do not emit a self join.

`metadata_qa` does not compile SQL and is answered from the metadata retrieval
path.

## Invariants

- Every plan identifier must exist in the registry.
- A relationship step can only start from an entity already present in the plan.
- Entity-plan cycles and properties outside the relationship graph are rejected.
- A time range uses the semantic model's declared default time dimension, never
  a hard-coded fallback such as `day`.
- Physical column differences are explicit in the ontology, for example
  `Order.customer_city -> fact_orders.city`.

## Verification

Run the hermetic tests with:

```powershell
.env\Scripts\python.exe -m pytest -p no:cacheprovider -q
```

After `dbt build` and a PostgreSQL service are available, include execution
tests with:

```powershell
$env:RUN_DB_INTEGRATION = '1'
.\venv\Scripts\python.exe -m pytest -p no:cacheprovider -m integration -q
```
