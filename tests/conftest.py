# Copyright 2024-2026 SURF.
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

"""Root test configuration and shared fixtures."""

from pathlib import Path

# Create dummy PEM files before any amiss import triggers settings validation
# (Settings validates FilePath fields at import time).
for _pem in ("amiss-certificate.pem", "amiss-private-key.pem"):
    Path(_pem).touch(exist_ok=True)
