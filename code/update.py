"""The total cophenetic index of every valid NWB file's internal hierarchy.

The file's own structure is the tree: groups are internal nodes, and every dataset plus every
childless group is a leaf. The total cophenetic index (Mir, Rossello & Rotger, 2013) is

    Phi(T) = sum over unordered leaf pairs {i, j} of depth(LCA(i, j))

with depth(root) = 0, so it measures how deep in the tree pairs of leaves tend to meet. The walk
that computes it is in the shared library, because it is a property of the arrangement and the
traversal is the only place the arrangement exists.

Two things this cache does that its siblings do not, both preserved from what it has published:

- `LINKS_FOLLOWED`, so the hierarchy is walked as it is named. Every entry of a group is a child
  of it, whatever kind of link put it there, and a group already walked contributes no further
  leaves, which is what stops a link cycle. The default policy would skip soft links entirely and
  give a different tree.
- HDF5 only. `layout` is named rather than probed, exactly as this cache has always done: it reads
  the content-addressed blob directly, so a Zarr asset fails to open and is left for a later run
  rather than recorded.

Everything shared with the other caches -- the argument parsing, the logging, the batch cap, the
error logs, the output paths, testing mode, and the structural walk itself -- comes from
`dandi_cache_utils`, which the runtime image carries.
"""

import dandi_cache_utils as dandi_cache


def compute_cophenetic_index(content_id, item) -> int:
    """Walk one HDF5 asset, resolved straight from its content ID, and score its tree's shape."""
    item.stage = "reading the NWB file"
    structure = dandi_cache.nwb.walk_structure(
        content_id,
        layout=dandi_cache.nwb.HDF5,
        links=dandi_cache.nwb.LINKS_FOLLOWED,
    )
    return structure.total_cophenetic_index


def main() -> None:
    dataset, arguments = dandi_cache.open_dataset()

    # Only the assets the upstream cache marked valid are measured.
    validity = dataset.read_input()
    valid_content_ids = [content_id for content_id, is_valid in validity.items() if is_valid is True]

    dandi_cache.run_incremental_update(
        dataset,
        candidates=valid_content_ids,
        process=compute_cophenetic_index,
        limit=dandi_cache.effective_limit(testing=dataset.testing, limit=arguments.limit),
        # These files were already opened successfully upstream, so a failure here is almost always
        # transient. Leave the item for a later run rather than recording a wrong index.
        on_failure=dandi_cache.SKIP,
        stages={"reading the NWB file": "file_read_errors.txt"},
        describe=lambda index: f"cophenetic index {index}",
        checkpoint_every=50,
    )


if __name__ == "__main__":
    main()
