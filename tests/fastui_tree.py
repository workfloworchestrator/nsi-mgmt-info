# Copyright 2026 SURF.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Walk the FastUI component tree a page returns."""

from collections.abc import Iterator
from itertools import chain
from typing import Any


def walk(node: Any) -> Iterator[dict]:
    """Yield every component dict in a FastUI tree."""
    match node:
        case dict():
            yield node
            yield from chain.from_iterable(walk(v) for v in node.values())
        case list():
            yield from chain.from_iterable(walk(v) for v in node)


def texts(tree: Any) -> list[str]:
    """Every rendered text string in a FastUI tree."""
    return [text for node in walk(tree) if isinstance(text := node.get("text"), str)]
