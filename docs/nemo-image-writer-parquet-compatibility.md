# NeMo ImageWriterStage Parquet Compatibility

## Tested Source Contract

The tested boundary is the [`ImageWriterStage` writer source](https://github.com/NVIDIA-NeMo/Curator/blob/15cc645cbf9e9314fed9e11fc89f6535ea9a8820/nemo_curator/stages/image/io/image_writer.py) and its [`ImageObject` task type](https://github.com/NVIDIA-NeMo/Curator/blob/15cc645cbf9e9314fed9e11fc89f6535ea9a8820/nemo_curator/tasks/image.py) at one pinned revision.

- Repository: `NVIDIA-NeMo/Curator`
- Commit: `15cc645cbf9e9314fed9e11fc89f6535ea9a8820`
- Writer columns: `image_id`, `tar_file`, `member_name`, `original_path`, `metadata`
- VULCA contract: `nemo.image_writer.parquet.source-first.v1`

## Observed Documentation Difference

At the pinned commit, the writer constructs rows with the five fields above. NVIDIA's current [image export documentation](https://docs.nvidia.com/nemo/curator/latest/curate-images/save-export.html) separately describes processing metadata in the Parquet sidecar, while the [image-processing documentation](https://docs.nvidia.com/nemo/curator/latest/about/concepts/image/data/processing) includes aesthetic and NSFW scores among that metadata.

The adapter therefore accepts `aesthetic_score` and `nsfw_score` as optional forward-compatible fields and never invents them when they are absent. Those fields appear only in the enriched fixture; the source-first fixture remains the exact five-column shape.

## Reproduce

From a clean Python 3.11 environment at the repository root, install the optional Parquet dependency:

```bash
python3.11 -m pip install -e ".[nemo-parquet]"
```

Build both synthetic fixtures from their readable JSON sources:

```bash
python3.11 scripts/build_nemo_image_writer_parquet_fixtures.py --source-dir samples --out samples
```

Run the source-first fixture through the existing release-readiness stage:

```bash
python3.11 -m vulca_curator_adapter triage samples/nemo_image_writer_source_first.parquet --parser nemo --profile creative-release --out demo-output
```

## Boundary

The fixtures are synthetic and generated locally from readable JSON. This reproduction does not execute NeMo Curator, inspect tar members, validate multiple shards, or exercise a GPU/Xenna pipeline. It is source-pinned local engineering evidence; it does not claim generic support or upstream endorsement.
