# Provider routing

Four providers are allowed, in this order: `codex`, `openai`, `nano-banana`, `seedream`. The order is enforced by `manage-run.py`; a candidate recorded with a provider outside the tuple is rejected.

The character is chosen by which model actually answers, not by branding:

| Provider | Model family | Endpoint shape | Reference images |
|---|---|---|---|
| `openai` | `gpt-image-*`, and OpenAI-compatible gateways | `/images/generations`, `/images/edits` | yes, as a multipart edit or an `image_url` array |
| `nano-banana` | `gemini-*-image` / `nanobanana*` | JSON `image_url` (grok-imagine) or `aspect_ratio` + `image_size` (nanobanana) | yes, up to several |
| `seedream` | `seedream-*`, `doubao-seedream-*` | `/images/generations`, reference images as a JSON `image` array | yes |
| `codex` | the local Codex image path | local tool invocation | yes |

A gateway that only exposes chat and embedding models is not an image provider even if the name suggests otherwise. When the provider that actually answered is not in this table, stop and report the mismatch instead of recording a wrong name: the run manifest would otherwise attribute the picture to an endpoint that never touched it. Extending this table means editing `PROVIDERS` in `scripts/manage-run.py`, which is a deliberate, reviewable change, not a runtime detail.

## Order and fallback

1. Use the first provider that is actually configured for this machine.
2. On a retryable failure, fall back to the next provider in the order and record the error first:

```
python scripts/manage-run.py record-error --run-dir <run_dir> --image <image_id> \
  --provider <provider> --model <model> --category <category> --details "<what happened>"
```

3. `record-error` does not spend image budget. `--category` must be one of `authentication`, `rate_limit`, `timeout`, `service`, `safety`.

## Error categories

| Category | Meaning | Action |
|---|---|---|
| `authentication` | credential missing, invalid or expired | do not retry this provider; fall back and tell the user which credential to fix |
| `rate_limit` | provider throttled the request | wait, then retry the same provider once before falling back |
| `timeout` | no response inside the wait window | retry once, then fall back |
| `service` | provider-side error or refusal unrelated to content | fall back |
| `safety` | the provider rejected the content | do NOT route around it; record it and stop that image |

A `safety` error is a root-cause stop. Rewording until a different endpoint accepts it is forbidden. Record it, leave the image open, and tell the user what was refused.

## Budget rules

- `per_image_candidates` ≤ 8 per image; `per_provider_candidates` ≤ 3 per provider; `run_candidates` ≥ `image_count × per_image_candidates`.
- When `image_count × per_image_candidates` exceeds 24, `budget.confirmed_over_24` must be `true` and an `approval_note` is required. Ask the user before spending that much.
- A candidate already over budget cannot be recorded.
- Never let one provider's failure burn another provider's budget.

## Parallelism

- `execution.requested_parallelism` is 1–5; `max_parallelism` is 5.
- Parallel work is only safe at the generation step. Prompt building, recording, promoting and finalizing are coordinator-serial because they mutate the run manifest.
- `init --effective-parallelism <n>` records the parallelism actually used, which may be lower than requested.
- Two images may never share a run directory write at the same time.

## Honesty

Report which provider actually produced each promoted file, and every error you recorded, including ones you recovered from. A run that silently fell back three providers and reports only the winner is not a valid report.

## Materialising the result

A provider never returns the frozen output intent. Every returned file goes through:

```
python scripts/materialize-image.py --run-dir <run_dir> --image <image_id> \
  --source <provider_output> --output staging/<image_id>/candidate-01.png --report staging/<image_id>/candidate-01.materialize.json
```

It fixes the container, the pixel size and the alpha policy, and it refuses to do anything destructive silently:

- a needed crop may not exceed `--max-crop` (2% by default); a bigger crop means regenerate, not chop;
- a needed resize is refused unless `--allow-scale` is passed, and is always Lanczos;
- a forbidden alpha channel is removed by compositing onto the frozen background colour, never by dropping the channel onto black;
- it never works in place and never overwrites an existing output.

Then run `validate-composite.py` on the materialised file, not on the raw provider download. A candidate that only passes because the provider happened to return RGB is not a passed candidate.

