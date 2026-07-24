# Pinned Earth-orientation data provenance

- Source distribution: `astropy-iers-data`
- Release: `0.2026.5.11.1.8.52`
- Source URL: `https://pypi.org/project/astropy-iers-data/0.2026.5.11.1.8.52/`
- Wheel file: `astropy_iers_data-0.2026.5.11.1.8.52-py3-none-any.whl`
- Wheel SHA-256: `40c449c35bd8deabc20053f024f3d4c0cbea2947adf620fcbb6f4242b55e2090`
- License: BSD-3-Clause; retained in `LICENSE.rst`

## Retained files

| File | Bytes | SHA-256 |
|---|---:|---|
| `finals2000A.all` | 3,741,200 | `eeb76193cd43c065b763d78923f8a8ce2f8a62df5d3e1519a3217fac433bdaa6` |
| `ReadMe.finals2000A` | 3,429 | `7c6182cc0fd0cbece39711f648d15e48b49168925602e360a5709c5ccc8d5a12` |
| `Leap_Second.dat` | 1,359 | `6f7bc6a25841bc394f82bdfd5d7bb22ffcd4548ee28e9822f2927a909e4f912f` |

`finals2000A.all` spans MJD 41684 through 61533. `Leap_Second.dat`
declares an expiry date of 2026-12-27. Both cover the project's canonical
2026-07-20 scenario epoch. `ReadMe.finals2000A` fixes the table's column
interpretation. Orbit verifies all three data hashes before using the default
files and never performs a runtime data download.
