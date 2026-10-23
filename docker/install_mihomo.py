"""Install a pinned official Mihomo binary plus its license and matching source."""
import gzip
import hashlib
import io
import json
import platform
from pathlib import Path
import tarfile
import time
import urllib.request

VERSION = "v1.19.32"
COMMIT = "88dcbf7f1614a67c3b36b848ee3592dfa92ada36"
ASSETS = {
    "x86_64": ("mihomo-linux-amd64-v1-v1.19.32.gz",
               "306f81e723e60ce6b828899a6fe83e1d00e9ecefb2dc8d4d849312a5bc00efdc"),
    "aarch64": ("mihomo-linux-arm64-v1.19.32.gz",
                "9dd862e28b46ff7d775f169cceebc28deccaa0a9e804237d421cd2571e0caba0"),
}
SOURCE_URL = "https://codeload.github.com/MetaCubeX/mihomo/tar.gz/refs/tags/v1.19.32"
SOURCE_HASH = "ab130b7fab3893d01aa44c0d39be34a26da716c1d36832fbac9fa054a1d862a0"


def verified_download(url, digest):
    for attempt in range(3):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "MediaCrawler-image-builder"})
            with urllib.request.urlopen(request, timeout=180) as response:
                data = response.read(64 * 1024 * 1024 + 1)
            if len(data) > 64 * 1024 * 1024:
                raise ValueError("Mihomo artifact exceeds size limit")
            if hashlib.sha256(data).hexdigest() != digest:
                raise ValueError("Mihomo artifact checksum mismatch")
            return data
        except (OSError, TimeoutError):
            if attempt == 2:
                raise
            time.sleep(2)


def main():
    asset, digest = ASSETS[platform.machine()]
    url = f"https://github.com/MetaCubeX/mihomo/releases/download/{VERSION}/{asset}"
    binary = gzip.decompress(verified_download(url, digest))
    executable = Path("/usr/local/bin/mihomo")
    executable.write_bytes(binary)
    executable.chmod(0o755)
    source = verified_download(SOURCE_URL, SOURCE_HASH)
    doc = Path("/usr/share/doc/mihomo")
    doc.mkdir(parents=True, exist_ok=True)
    (doc / "source.tar.gz").write_bytes(source)
    # Read only this file; never extract archive-controlled paths.
    with tarfile.open(fileobj=io.BytesIO(source), mode="r:gz") as archive:
        license_file = archive.extractfile("mihomo-1.19.32/LICENSE")
        if license_file is None:
            raise ValueError("Mihomo license missing")
        (doc / "LICENSE").write_bytes(license_file.read())
    (doc / "provenance.json").write_text(json.dumps({
        "version": VERSION, "commit": COMMIT, "binary_url": url,
        "binary_archive_sha256": digest, "source_url": SOURCE_URL,
        "source_archive_sha256": SOURCE_HASH, "license": "GPL-3.0",
        "changes": "Official binary, unmodified. Application communicates via HTTP proxy/controller.",
    }, indent=2), encoding="utf-8")
    print(f"Installed verified Mihomo {VERSION} ({platform.machine()})", flush=True)


if __name__ == "__main__":
    main()
