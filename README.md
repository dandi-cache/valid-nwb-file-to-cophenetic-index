# DANDI Cache: `valid-nwb-file-to-cophenetic-index`

A mapping from the content ID of every valid, HDF5-backed NWB file on the DANDI archive to the total cophenetic index of that file's internal object hierarchy.

The set of valid NWB files is taken from the [`content-id-to-valid-nwb-file`](https://github.com/dandi-cache/content-id-to-valid-nwb-file) cache, restricted to the entries it marked `true`. Only HDF5 assets are processed (Zarr-backed NWB stores are skipped); each HDF5 file is streamed directly from the public DANDI S3 bucket with [remfile](https://github.com/flatironinstitute/remfile) and read with [h5py](https://www.h5py.org/), and the total cophenetic index of its object hierarchy is computed.

## What is computed

The **total cophenetic index** (Mir, Rossello & Rotger, 2013) measures tree imbalance for trees of arbitrary degree (not just binary trees) by summing, over every unordered pair of leaves, the depth of their lowest common ancestor (LCA):

$$\Phi(T) = \sum_{\{i, j\}} \mathrm{depth}(\mathrm{LCA}(i, j))$$

An NWB file is itself a tree — the file's own group/dataset structure is used directly:

- **Internal nodes** are groups that contain at least one child.
- **Leaves** are nodes with no children: every dataset, plus any empty group.
- `depth(root) = 0`, and `depth(v)` is `v`'s number of ancestors.

Rather than enumerating leaf pairs directly (quadratic in the number of leaves), $\Phi$ is computed in a single post-order traversal, linear in the number of nodes. For each node $v$, let $L_v$ be its number of leaf descendants (a leaf has $L_v = 1$). A leaf pair is first joined at $v$ exactly when its two leaves fall under two different children of $v$, so

$$\Phi(T) = \sum_{v \text{ internal}} \mathrm{depth}(v) \cdot \frac{L_v^2 - \sum_{c \in \mathrm{children}(v)} L_c^2}{2}$$

Soft links that resolve back to an already-visited group (forming a cycle) are not re-descended into.

Each line of the derivatives is a JSON object of the form:

```json
{"<content_id>": <cophenetic_index>}
```

Updated frequently.

Primarily for use by developers.



## One-time use

If you only plan to use this cache infrequently or from disparate locations, you can directly download the latest version of the cache as a compressed [JSON Lines](https://jsonlines.org/) file from the `dist` branch:

### Python API (recommended)

```python
import gzip
import json

import requests

url = "https://raw.githubusercontent.com/dandi-cache/valid-nwb-file-to-cophenetic-index/refs/heads/dist/derivatives/valid_nwb_file_to_cophenetic_index.jsonl.gz"
response = requests.get(url)
lines = gzip.decompress(data=response.content).decode("utf-8").splitlines()
valid_nwb_file_to_cophenetic_index = [json.loads(line) for line in lines]
```

Each line is a single-entry mapping of `{"<content_id>": <cophenetic_index>}`.

### Save to file

```bash
curl https://raw.githubusercontent.com/dandi-cache/valid-nwb-file-to-cophenetic-index/refs/heads/dist/derivatives/valid_nwb_file_to_cophenetic_index.jsonl.gz -o valid_nwb_file_to_cophenetic_index.jsonl.gz
```



## Repeated use

If you plan on using this cache regularly, clone the `derivatives` branch of this repository:

```bash
git clone --branch derivatives https://github.com/dandi-cache/valid-nwb-file-to-cophenetic-index.git
```

Or, if you prefer [DataLad](https://www.datalad.org/):

```bash
datalad clone https://github.com/dandi-cache/valid-nwb-file-to-cophenetic-index.git --branch derivatives
```

Then set up a CRON on your system to pull the latest version of the cache at your desired frequency.

For example, through `crontab -e`, add:

```bash
0 0 * * * git -C /path/to/valid-nwb-file-to-cophenetic-index pull
```

This will minimize data overhead by only loading the most recent changes.
