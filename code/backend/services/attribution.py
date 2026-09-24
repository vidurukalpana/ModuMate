"""Build public citations from trusted retrieval metadata, never model-written paths."""

from pathlib import PurePosixPath


def source_reference(passage, source_id):
    path = passage['source']
    if (not isinstance(path, str) or not path or '\\' in path or ':' in path
            or PurePosixPath(path).is_absolute() or '..' in PurePosixPath(path).parts):
        raise ValueError('Source must be a relative course path')
    return {
        'id': source_id,
        'source': path,
        'topic': passage['topic'],
        'chunk_index': passage.get('chunk_index'),
        'excerpt': passage['text'],
    }
