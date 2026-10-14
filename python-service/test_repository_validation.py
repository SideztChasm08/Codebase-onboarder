
from repository_ingestion import validate_repository_url

invalid_urls = [
    "http://github.com/example/repo.git",
    "not-a-url",
    "",
]

for url in invalid_urls:
    try:
        validate_repository_url(url)
        raise AssertionError(f"Invalid URL was accepted: {url!r}")
    except ValueError:
        print(f"Correctly rejected: {url!r}")

print("Repository URL validation tests passed!")
