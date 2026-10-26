"""Start-up restore and result push move many small files concurrently."""
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from eawiki import sync  # noqa: E402


class _Blob:
    def __init__(self, name, log):
        self.name, self.md5_hash, self._log = name, "x", log

    def download_to_filename(self, path):
        self._log.append(threading.get_ident())
        time.sleep(0.02)                              # one round trip
        Path(path).write_text("data")


class _Client:
    def __init__(self, names):
        self.names, self.log = names, []

    def list_blobs(self, bucket, prefix=""):
        return [_Blob(prefix + n, self.log) for n in self.names]


def test_download_is_concurrent_and_complete():
    names = [f"d/{i}.json" for i in range(64)]
    c = _Client(names)
    s = sync.Sync("kb", "gs://state/x", client=c)
    root = Path(tempfile.mkdtemp())
    t0 = time.time()
    n = s._download(("kb", ""), root)
    took = time.time() - t0
    assert n == 64 and all((root / x).exists() for x in names)
    assert len(set(c.log)) > 1                         # more than one thread did the work
    assert took < 64 * 0.02 * 0.6                      # clearly faster than one after another


if __name__ == "__main__":
    test_download_is_concurrent_and_complete()
    print("ok")
