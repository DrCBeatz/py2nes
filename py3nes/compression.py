"""Small, deterministic encodings for immutable ROM room data.

The public map and collision APIs retain their unpacked representation. Only
the generated ROM uses these encodings; no gameplay RAM stores a second copy.
"""


def pack_runs(data: bytes) -> bytes:
    """Encode literal packets (1..127) and repeated bytes (128..255).

    A zero control byte ends the stream. Literal controls are their byte count;
    repeat controls store count minus one in their low seven bits. Three or
    more equal bytes start a repeat packet. Inputs may contain every byte value.
    """
    data = bytes(data)
    encoded = bytearray()
    position = 0
    while position < len(data):
        count = 1
        while count < 128 and position + count < len(data) and data[position + count] == data[position]:
            count += 1
        if count >= 3:
            encoded.extend((0x80 | (count - 1), data[position]))
            position += count
            continue
        start = position
        position += count
        while position < len(data) and position - start < 127:
            count = 1
            while count < 3 and position + count < len(data) and data[position + count] == data[position]:
                count += 1
            if count >= 3:
                break
            position += min(count, 127 - (position - start))
        encoded.append(position - start)
        encoded.extend(data[start:position])
    encoded.append(0)
    return bytes(encoded)


def nametable_storage(data: bytes) -> tuple[bytes, bool]:
    """Choose RLE only when it pays for the shared decoder by itself."""
    data = bytes(data)
    encoded = pack_runs(data)
    # The decoder occupies fewer than 80 PRG bytes. This conservative threshold
    # prevents a nearly incompressible single room from making its ROM larger.
    return (encoded, True) if len(data) - len(encoded) >= 80 else (data, False)


def pack_collision(data: bytes) -> bytes:
    """Store the 32 by 30 boolean collision grid as 120 MSB-first bytes."""
    if len(data) != 960:
        raise ValueError("collision grid must contain exactly 960 bytes")
    encoded = bytearray(120)
    for index, value in enumerate(data):
        if value:
            encoded[index // 8] |= 0x80 >> (index & 7)
    return bytes(encoded)


def initial_oam(sprites) -> bytes:
    """Return the OAM prefix through the last statically described sprite.

    Everything after the prefix is $FF. Actor rendering fills its own slots
    after room loading, so actor-only rooms need no initial OAM ROM data.
    """
    sprites = tuple(sprites)
    end = max((sprite.index + 1 for sprite in sprites), default=0) * 4
    data = bytearray([255] * end)
    for sprite in sprites:
        attributes = (sprite.palette | (int(sprite.behind_background) << 5)
                      | (int(sprite.flip_horizontal) << 6) | (int(sprite.flip_vertical) << 7))
        offset = sprite.index * 4
        data[offset:offset + 4] = bytes((sprite.y, sprite.tile, attributes, sprite.x))
    return bytes(data)
