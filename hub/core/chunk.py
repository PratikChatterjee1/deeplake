from hub.core.index.index import Index
from hub.core.storage.cachable import Cachable
from typing import List, Optional, Sequence, Tuple
import numpy as np
from io import BytesIO
from math import ceil

from hub.core.meta.encode.shape import ShapeEncoder
from hub.core.meta.encode.byte_positions import BytePositionsEncoder

from hub.constants import DEFAULT_CHUNK_MAX_SIZE


class Chunk(Cachable):
    """A Chunk should only be provided data to store in bytes form, alongside the meta information (like shape/num_samples). The
    byte ranges are to be generated by this chunk, and it can also spawn new chunks as needed."""

    def __init__(self, max_data_bytes: int = DEFAULT_CHUNK_MAX_SIZE):
        # no need to load these encoders, if `frombuffer` is called, it will override them.
        self.index_shape_encoder = ShapeEncoder()
        self.index_byte_range_encoder = BytePositionsEncoder()

        self.max_data_bytes = max_data_bytes
        self.min_data_bytes_target = max_data_bytes // 2

        self.data = bytearray()

        self.next_chunk = None

    @property
    def num_samples(self):
        return self.index_byte_range_encoder.num_samples

    @property
    def num_data_bytes(self):
        return len(self.data)

    @property
    def has_space(self):
        return self.num_data_bytes < self.min_data_bytes_target

    def extend(
        self,
        incoming_buffer: memoryview,
        num_samples: int,
        sample_shape: Tuple[int],
        _leftover_buffer_from_previous_chunk: bool = False,
    ) -> Tuple["Chunk"]:
        # TODO: docstring

        if self.next_chunk is not None:
            # TODO: exceptions.py
            raise Exception(
                "Cannot extend a chunk that is connected to the next chunk."
            )

        if not self.has_space:
            # TODO: exceptions.py
            raise Exception("Cannot extend a chunk that has no space left.")

        incoming_num_bytes = len(incoming_buffer)

        # update headers first because erroneous headers are better than un-accounted for data.
        if not _leftover_buffer_from_previous_chunk:
            self._update_headers(incoming_num_bytes, num_samples, sample_shape)

        processed_num_bytes = self._fill(incoming_buffer)

        if processed_num_bytes >= incoming_num_bytes:
            # this chunk was able to store all incoming bytes!
            return tuple()

        forwarding_buffer = incoming_buffer[processed_num_bytes:]

        child_chunk = self._spawn_child_chunk()
        child_chunk_children = child_chunk.extend(
            forwarding_buffer,
            num_samples,
            sample_shape,
            _leftover_buffer_from_previous_chunk=True,
        )

        return (child_chunk, *child_chunk_children)

    def _fill(self, incoming_buffer: memoryview) -> int:
        # TODO: docstring

        incoming_num_bytes = len(incoming_buffer)

        min_chunks_for_incoming_bytes = self._min_chunks_required_for_num_bytes(
            incoming_num_bytes
        )
        min_chunks_for_incoming_and_current_bytes = (
            self._min_chunks_required_for_num_bytes(
                incoming_num_bytes + self.num_data_bytes
            )
        )
        incoming_num_bytes_that_will_fit = min(
            incoming_num_bytes, self.max_data_bytes - self.num_data_bytes
        )
        if min_chunks_for_incoming_bytes == min_chunks_for_incoming_and_current_bytes:
            self.data += incoming_buffer[:incoming_num_bytes_that_will_fit]

        return incoming_num_bytes_that_will_fit

    def _min_chunks_required_for_num_bytes(self, num_bytes: int) -> int:
        """Calculates the minimum number of chunks in which data with length of `num_bytes` can be fit."""
        return ceil(num_bytes / self.max_data_bytes)

    def _spawn_child_chunk(self) -> "Chunk":
        # TODO: docstring

        if self.next_chunk is not None:
            # TODO: exceptions.py
            raise Exception("A chunk has already been spawned for this one.")

        chunk = Chunk(self.max_data_bytes)
        self.next_chunk = chunk
        return chunk

    def _update_headers(
        self, incoming_num_bytes: int, num_samples: int, sample_shape: Sequence[int]
    ):
        # TODO: docstring

        _validate_incoming_buffer(incoming_num_bytes, num_samples)

        num_bytes_per_sample = incoming_num_bytes // num_samples
        self.index_shape_encoder.add_shape(sample_shape, num_samples)
        self.index_byte_range_encoder.add_byte_position(
            num_bytes_per_sample, num_samples
        )

    def __getitem__(self, sample_index: int) -> np.ndarray:
        raise NotImplementedError

    def __eq__(self, o: object) -> bool:
        raise NotImplementedError

    def __len__(self):
        # this should not call `tobytes` because it will be slow. should calculate the amount of bytes this chunk takes up in total. (including headers)

        shape_nbytes = self.index_shape_encoder.nbytes
        range_nbytes = self.index_byte_range_encoder.nbytes
        error_bytes = 32  # to account for any extra delimeters/stuff that `np.savez` may create in excess

        return shape_nbytes + range_nbytes + self.num_data_bytes + error_bytes

    def tobytes(self) -> memoryview:
        out = BytesIO()
        np.savez(
            out,
            index_shape_encoder=self.index_shape_encoder,
            index_byte_range_encoder=self.index_byte_range_encoder,
            data=self.data,
        )
        out.seek(0)
        return out.getbuffer()

    @classmethod
    def frombuffer(cls, buffer: bytes):
        instance = super().frombuffer(buffer)

        # TODO: this should also set `next_chunk`

        raise NotImplementedError
        return instance


def _validate_incoming_buffer(
    incoming_num_bytes: bytes,
    num_samples: int,
):
    if num_samples <= 0:
        raise ValueError(
            f"The number of samples a buffer can represent has to be greater than 0. Got {num_samples}"
        )

    if incoming_num_bytes % num_samples != 0:
        raise ValueError(
            f"Incoming buffer length should be perfectly divisible by the number of samples it represents. length={incoming_num_bytes}, num_samples={num_samples}"
        )
