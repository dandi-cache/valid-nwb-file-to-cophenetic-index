import argparse
import itertools
import json
import pathlib
import urllib.error
import urllib.request

import h5py
import numpy as np
import remfile

# Testing mode processes only this many items and writes to its own designated file
# (`derivatives/testing.jsonl`), leaving the real cache untouched.
_TESTING_LIMIT = 10
_CACHE_FILE_NAME = "valid_nwb_file_to_cophenetic_index.jsonl"
_TESTING_FILE_NAME = "testing.jsonl"

# The input is the `content-id-to-valid-nwb-file` cache, registered as an input subdataset.
_INPUT_FILE_PATH = (
    pathlib.Path("sourcedata") / "content-id-to-valid-nwb-file" / "derivatives" / "content_id_to_valid_nwb_file.jsonl"
)

# The public DANDI archive S3 bucket. Every asset is content-addressed, so a valid HDF5 NWB
# file is reachable directly from its content ID without consulting the DANDI API: it is
# stored as a single blob at `blobs/<c[:3]>/<c[3:6]>/<content_id>`. Zarr-backed NWB stores (no
# such blob) are out of scope here, since this cache is restricted to h5py/remfile only.
_BLOB_URL_TEMPLATE = "https://dandiarchive.s3.amazonaws.com/blobs/{prefix}/{infix}/{content_id}"


def _load_content_id_to_validity(file_path: pathlib.Path) -> dict:
    """Load the `{content_id: bool}` mapping from the input JSONL, or an empty dict if missing."""
    records: dict = {}
    if not file_path.exists():
        return records
    with file_path.open(mode="r") as file_stream:
        for line in file_stream:
            if line.strip():
                records.update(json.loads(line))
    return records


def _load_previous_cache(file_path: pathlib.Path) -> dict:
    """Load the previously computed `{content_id: cophenetic_index}` mapping (empty on bootstrap)."""
    records: dict = {}
    if not file_path.exists():
        return records
    with file_path.open(mode="r") as file_stream:
        for line in file_stream:
            if line.strip():
                records.update(json.loads(line))
    return records


def _write_cache(file_path: pathlib.Path, records: dict) -> None:
    """Write the `{content_id: cophenetic_index}` mapping, one sorted content ID per line."""
    with file_path.open(mode="w") as file_stream:
        file_stream.writelines(f"{json.dumps({content_id: records[content_id]})}\n" for content_id in sorted(records))


def _is_hdf5_blob(blob_url: str) -> bool:
    """Whether `blob_url` resolves to an HDF5 blob (as opposed to a Zarr store, which has no such blob)."""
    request = urllib.request.Request(url=blob_url, method="HEAD")
    try:
        with urllib.request.urlopen(request):
            return True
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return False
        raise


def _object_address(obj: h5py.HLObject) -> int:
    """
    Stable identifier of the underlying HDF5 object (its header address in the file).

    Two different paths (e.g. a soft link and the target it points to) resolve to the same
    address, which is exactly what distinguishes a genuine cycle from an ordinary subtree.
    """
    return h5py.h5o.get_info(obj.id).addr


def _total_cophenetic_index(h5py_file: h5py.File) -> int:
    """
    Total cophenetic index of the file's internal object hierarchy (Mir, Rossello & Rotger, 2013).

    The tree: groups are internal nodes when they have at least one child; every dataset, plus
    any empty group, is a leaf. depth(root) = 0, and depth(v) is v's number of ancestors.

        Phi(T) = sum over unordered leaf pairs {i, j} of depth(LCA(i, j))

    A single post-order traversal computes this in O(n): for each node v, let L_v be its number
    of leaf descendants (a leaf has L_v = 1). Consider a leaf pair whose LCA is exactly v: the
    two leaves must come from two *different* children of v (a pair from the same child has a
    deeper LCA, down in that child's subtree). Summing L_v^2 over the children double-counts the
    same-child pairs (including each leaf against itself), so

        (L_v^2 - sum_{c in children(v)} L_c^2) / 2

    is exactly the count of unordered leaf pairs first joined at v, and each contributes depth(v)
    to Phi. Summing that over every internal node gives Phi(T), since every leaf pair has exactly
    one LCA and is counted exactly once, at that node.
    """
    visited_addresses: set[int] = set()
    phi = 0

    def _walk(obj: h5py.HLObject, depth: int) -> int:
        nonlocal phi
        if isinstance(obj, h5py.Dataset):
            return 1

        address = _object_address(obj)
        if address in visited_addresses:
            # A soft link resolves back to an already-visited group (e.g. an ancestor, forming
            # a cycle): do not re-descend into it. Its leaves were already (or will already be)
            # counted through the path that first reached it.
            return 0
        visited_addresses.add(address)

        child_names = list(obj.keys())
        if not child_names:
            return 1  # An empty group is itself a leaf.

        child_leaf_counts = np.array([_walk(obj[name], depth + 1) for name in child_names], dtype=np.int64)
        L_v = int(child_leaf_counts.sum())
        pairs_first_joined_at_v = (L_v * L_v - int(np.sum(child_leaf_counts * child_leaf_counts))) // 2
        phi += depth * pairs_first_joined_at_v
        return L_v

    _walk(h5py_file, 0)
    return phi


def _compute_cophenetic_index(content_id: str) -> int:
    """Stream the HDF5 NWB file identified by `content_id` and compute its total cophenetic index."""
    blob_url = _BLOB_URL_TEMPLATE.format(prefix=content_id[:3], infix=content_id[3:6], content_id=content_id)
    rem_file = remfile.File(url=blob_url)
    with h5py.File(name=rem_file, mode="r") as h5py_file:
        return _total_cophenetic_index(h5py_file=h5py_file)


def _run(base_directory: pathlib.Path, testing: bool, limit: int | None) -> None:
    content_id_to_validity = _load_content_id_to_validity(file_path=base_directory / _INPUT_FILE_PATH)
    # Only the assets the upstream cache marked valid ('true') are candidates.
    valid_content_ids = {content_id for content_id, is_valid in content_id_to_validity.items() if is_valid is True}

    derivatives_directory = base_directory / "derivatives"
    derivatives_directory.mkdir(parents=True, exist_ok=True)
    cache_file_path = derivatives_directory / (_TESTING_FILE_NAME if testing else _CACHE_FILE_NAME)
    valid_nwb_file_to_cophenetic_index = _load_previous_cache(file_path=cache_file_path)

    # Already-computed content IDs are exactly the keys already in the output, so re-runs skip
    # them and only pick up content IDs newly marked valid upstream.
    content_ids_to_process = sorted(valid_content_ids - valid_nwb_file_to_cophenetic_index.keys())

    # A testing run caps the batch tightly; otherwise the optional `--limit` bounds a single
    # run because streaming and walking each file is heavy.
    effective_limit = _TESTING_LIMIT if testing else limit
    content_ids_to_process = list(itertools.islice(content_ids_to_process, effective_limit))

    for content_id in content_ids_to_process:
        blob_url = _BLOB_URL_TEMPLATE.format(prefix=content_id[:3], infix=content_id[3:6], content_id=content_id)
        if not _is_hdf5_blob(blob_url=blob_url):
            # Zarr-backed NWB stores are out of scope for this cache (h5py/remfile only).
            continue
        try:
            cophenetic_index = _compute_cophenetic_index(content_id=content_id)
        except Exception as exception:
            # These files were already opened successfully upstream, so a failure here is
            # almost always transient (network). Skip it and leave it for a later run to retry
            # rather than recording a wrong value.
            print(f"Skipping `{content_id}`: {type(exception).__name__}: {exception}", flush=True)
            continue
        valid_nwb_file_to_cophenetic_index[content_id] = cophenetic_index

    _write_cache(file_path=cache_file_path, records=valid_nwb_file_to_cophenetic_index)


if __name__ == "__main__":
    default_base_directory = pathlib.Path(__file__).parent.parent

    parser = argparse.ArgumentParser(description="Update the valid-nwb-file-to-cophenetic-index DANDI cache.")
    parser.add_argument(
        "--base-directory",
        type=pathlib.Path,
        default=default_base_directory,
        help=(
            "The directory containing the `sourcedata` and `derivatives` directories. "
            "Set to the mounted dataset path when run inside the pipeline container; "
            "defaults to the repository root."
        ),
    )
    parser.add_argument(
        "--testing",
        action="store_true",
        help=(
            f"Run in testing mode: process only the first {_TESTING_LIMIT} items and write "
            f"`derivatives/{_TESTING_FILE_NAME}` instead of the real cache, leaving it "
            "untouched. Omit for a complete update."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional cap on the number of newly valid content IDs to process in this run.",
    )
    args = parser.parse_args()

    _run(base_directory=args.base_directory, testing=args.testing, limit=args.limit)
