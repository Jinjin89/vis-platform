# Analysis-platform source contract

This is the implemented adapter boundary, not a claim about the existing platform's API. Supply its representative response and base URL to map that API in `data/providers.py` without changing the catalog, agents, or UI.

The configured base URL owns all source requests. The optional token is sent only by the backend as a bearer token. Content locations must stay within that origin and base path; redirects are not followed. Public dataset responses exclude the source's content locations.

## Discovery

`GET {base_url}/datasets?cursor=...` returns:

```json
{
  "datasets": [
    {
      "source_id": "study-42",
      "revision": "v3",
      "name": "Treatment study",
      "description": "Measurements and sample annotations.",
      "object_count": 2
    }
  ],
  "next_cursor": null
}
```

Source IDs are stable logical identifiers. Revisions identify the metadata and data state; a changed meaning, schema, relationship, or content requires a new revision. The registry maps source identifiers into project-scoped local identities.

## Collection description

`GET {base_url}/datasets/{source_id}` returns a manifest. The complete schema is exported to `contracts/analysis-platform-source-v1.schema.json`.

```json
{
  "source_id": "study-42",
  "revision": "v3",
  "name": "Treatment study",
  "description": "Measurements linked to treatment assignments.",
  "objects": [
    {
      "source_object_id": "measurements",
      "description": {
        "name": "Measurements",
        "description": "One measured value per sample.",
        "kind": "table",
        "format": "csv",
        "dimensions": [4, 2],
        "observation_unit": "sample",
        "columns": [
          { "name": "sample_id", "data_type": "string" },
          { "name": "value", "data_type": "number", "unit": "mg" }
        ]
      },
      "content_path": "objects/measurements/v3.csv"
    },
    {
      "source_object_id": "samples",
      "description": {
        "name": "Samples",
        "description": "Treatment assignment for each sample.",
        "kind": "table",
        "format": "csv",
        "dimensions": [4, 2],
        "columns": [
          { "name": "sample_id", "data_type": "string" },
          { "name": "group", "data_type": "string" }
        ]
      },
      "content_path": "objects/samples/v3.csv"
    }
  ],
  "relationships": [
    {
      "relationship_id": "sample-mapping",
      "left_object_id": "measurements",
      "right_object_id": "samples",
      "kind": "join",
      "left_key": "sample_id",
      "right_key": "sample_id",
      "cardinality": "one_to_one",
      "description": "The same sample identifiers connect both tables."
    }
  ]
}
```

`description` contains semantic metadata only. Content paths, credentials, and storage configuration belong outside it. No local object, dataset-owner, or revision identifiers are required from the platform; the backend assigns them.

A supplied `columns` list describes the complete table schema; it can be omitted when unknown. The backend checks supplied dimensions and columns when the object is materialized. Scientific descriptions and units are preserved, while actual profiles are measured locally. Matrix and model objects retain their native structure.

Each object can additionally carry `sha256` for its source bytes and `object_path` for a logical object inside a JSON or R container. For example, `object_path: ["analysis", "counts"]` selects named members (or R slots), and integer steps select zero-based list entries. A platform object location and selector must identify exactly one logical object. Several logical objects may share a content location.

For a relationship, each join side selects either a table column (`left_key` / `right_key`) or matrix axis identifiers (`left_axis` / `right_axis`, values `rows` or `columns`). The two selectors are mutually exclusive on each side. Cardinality can be one-to-one, many-to-one, one-to-many, many-to-many, or unknown. Execution checks actual keys and alignment; unresolved unmatched rows are not silently discarded.

`sha256` is recommended for version-verifiable retrieval, including old revisions. Without a hash, resolving an uncached revision requires the source to still report that revision before and after download. Saved local inputs are checked against their recorded content hash on every use.

## Connection status

The workspace returns `connected: false` for the external connection when the base URL is not configured. The composed platform picker still lists built-in transcriptomic demo collections, marked with `contains_demo_data: true`. Their reserved source IDs (`demo.single-cell` and `demo.spatial`) and `builtin-demo/` locators cannot be supplied by an external source. A configured but failing source returns a stable API error rather than an empty successful catalog or a substitute demonstration dataset. Failed refreshes preserve the previous usable dataset revision.
