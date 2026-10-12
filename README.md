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

`dist` publishes each output as a [Zarr](https://zarr.dev/) store: the cache itself is `derivatives/valid_nwb_file_to_cophenetic_index.zarr/`.
A store is one array of [JSON Lines](https://jsonlines.org/) text cut into chunk files, each holding whole lines and gzip-compressed.
It can be read with the standard library alone, or opened remotely with any Zarr library.

### Python API (recommended)

The chunk files are gzip-compressed [JSON Lines](https://jsonlines.org/): list them, then read them in order as you would any JSONL files.

```python
import gzip, json, urllib.request

chunks = "https://api.github.com/repos/dandi-cache/valid-nwb-file-to-cophenetic-index/contents/derivatives/valid_nwb_file_to_cophenetic_index.zarr/stream/c?ref=dist"
files = sorted((entry["download_url"] for entry in json.load(urllib.request.urlopen(chunks))), key=lambda url: int(url.rsplit("/", 1)[1]))
valid_nwb_file_to_cophenetic_index = {key: value for url in files for line in gzip.decompress(urllib.request.urlopen(url).read()).decode().splitlines() if line for key, value in json.loads(line).items()}
```

Each line is a single-entry mapping of `{"<content_id>": <cophenetic_index>}`.

### Remote Zarr store

Anything that opens Zarr can open the store over HTTP, reading only the chunks it needs.
The group's `zarr.json` carries the array's metadata, so opening it takes one request:

```bash
pip install "zarr>=3" fsspec aiohttp
```

```python
import json

import zarr

url = "https://raw.githubusercontent.com/dandi-cache/valid-nwb-file-to-cophenetic-index/refs/heads/dist/derivatives/valid_nwb_file_to_cophenetic_index.zarr"
stream = zarr.open_group(url, mode="r")["stream"]
print(stream.shape, stream.chunks)  # Bytes in all, and bytes per chunk.

# The first chunk, fetched and decompressed on its own: whole lines, each `{"<key>": <value>}`.
first_chunk = stream[: stream.chunks[0]].tobytes().decode("utf-8")
for line in first_chunk.splitlines():
    if line.strip():
        print(json.loads(line))
        break
```

Reading `stream[:]` returns the whole text; to read it in pieces, step through it by `stream.chunks[0]`, as each chunk is fetched whole.

### Save to file

A raw URL cannot be listed, so to fetch every chunk at once clone the `dist` branch, which holds nothing else:

```bash
git clone --branch dist --depth 1 https://github.com/dandi-cache/valid-nwb-file-to-cophenetic-index.git
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

Each output is a store on the `derivatives` branch, where it is the whole log, uncompacted, and plain text:

```python
import json, pathlib

chunks = sorted(pathlib.Path("valid-nwb-file-to-cophenetic-index/derivatives/valid_nwb_file_to_cophenetic_index.zarr/stream/c").iterdir(), key=lambda path: int(path.name))
valid_nwb_file_to_cophenetic_index = {key: value for chunk in chunks for line in chunk.read_text().splitlines() if line for key, value in json.loads(line).items()}
```


## Reading the `derivatives` branch

Each output is kept on the `derivatives` branch as a [Zarr](https://zarr.dev/) v3 store of JSON Lines: a one-dimensional `uint8` array whose bytes are the lines, padded with newlines to the end of its last chunk.
A key recorded more than once keeps its last line, which the dictionary below does by itself.

```python
import json

import zarr  # zarr>=3, with fsspec and aiohttp to read over HTTP

url = "https://raw.githubusercontent.com/dandi-cache/valid-nwb-file-to-cophenetic-index/derivatives/derivatives/valid_nwb_file_to_cophenetic_index.zarr"
stream = zarr.open_group(url, mode="r")["stream"]
lines = stream[:].tobytes().decode("utf-8").splitlines()
valid_nwb_file_to_cophenetic_index = {key: value for line in lines if line for key, value in json.loads(line).items()}
```

Without Zarr, each chunk is a plain file of whole lines at `derivatives/valid_nwb_file_to_cophenetic_index.zarr/stream/c/<n>`, read in order of `n`.
